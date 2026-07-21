from __future__ import annotations

import bert.fanout as fo
import bert.pipeline as pl


def _result(**kw):
    base = {"ok": True, "conversation_id": 1, "confidence": "high",
            "needs_action": False, "escalate": False, "open_question": None,
            "bug_report": None, "draft_reply": "<p>hi</p>", "parsed": {}}
    base.update(kw)
    return base


# --- partition ---------------------------------------------------------------

def test_partition_close_bucket():
    results = [
        _result(conversation_id=1, close_no_reply=True),
        _result(conversation_id=2),
        _result(conversation_id=3, confidence="low"),
    ]
    p = fo.partition(results)
    assert [r["conversation_id"] for r in p["close"]] == [1]
    assert [r["conversation_id"] for r in p["ready"]] == [2]
    assert [r["conversation_id"] for r in p["review"]] == [3]


def test_partition_close_from_parsed_fallback():
    p = fo.partition([_result(parsed={"close_no_reply": True})])
    assert len(p["close"]) == 1 and not p["ready"] and not p["review"]


def test_partition_failed_close_no_reply_goes_to_review():
    # a failed worker must surface even if it claimed close_no_reply
    p = fo.partition([_result(ok=False, close_no_reply=True, error="boom")])
    assert not p["close"]
    assert len(p["review"]) == 1


def test_partition_always_has_close_key():
    assert fo.partition([]) == {"ready": [], "review": [], "close": []}


# --- apply_result ------------------------------------------------------------

def test_apply_result_skips_draft_for_close_no_reply(monkeypatch):
    monkeypatch.setattr(fo.pipeline, "find_draft_threads",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not touch drafts")))
    monkeypatch.setattr(fo, "reconcile_auto_send_tag", lambda session, cid, verdict: "removed")
    s = fo.apply_result(object(), _result(close_no_reply=True))
    assert s["draft_action"] == "skipped_close_no_reply"
    assert s["auto_send_tagged"] == "removed"  # stale tag stripped
    assert s["error"] is None


def test_apply_result_close_no_reply_never_verifies(monkeypatch):
    monkeypatch.setattr(fo, "reconcile_auto_send_tag", lambda *a: None)
    called = {"verify": False}
    monkeypatch.setattr(fo, "verify_and_tag", lambda *a, **k: called.__setitem__("verify", True))
    s = fo.apply_result(object(), _result(close_no_reply=True,
                                          parsed={"auto_sendable": True, "confidence": "high"}),
                        verify_client=object())
    assert s["draft_action"] == "skipped_close_no_reply"
    assert called["verify"] is False


# --- draft_one lifts the flag ------------------------------------------------

def test_draft_one_lifts_close_no_reply(monkeypatch):
    def fake_call(client, *, system_prompt, policy_docs, dynamic_user_message, model):
        return (object(), {"draft_reply": "thanks!", "close_no_reply": True}, "raw")

    monkeypatch.setattr(pl.orchestrator, "_call_claude_draft_with_action_retry", fake_call)
    monkeypatch.setattr(pl.orchestrator, "load_policy_docs", lambda: "P")
    monkeypatch.setattr(pl.orchestrator, "_load_system_prompt", lambda: "SYS")
    ctx = {"conversation_id": 1, "subject": "s", "body": "b", "customer_name": "N",
           "email": "e", "account_blob": "A", "stripe_block": "S",
           "conversation_history": "", "reply_mode": True}
    res = pl.draft_one(object(), ctx, "", model="m")
    assert res["close_no_reply"] is True


# --- prompts carry the instruction -------------------------------------------

def test_reply_mode_prefix_forbids_repeats_and_offers_close():
    prefix = pl.orchestrator.REPLY_MODE_PROMPT_PREFIX.lower()
    assert "repeat" in prefix
    assert "close_no_reply" in prefix


def test_draft_system_prompt_documents_close_no_reply():
    with open("prompts/draft_system_prompt.txt", encoding="utf-8") as f:
        assert "close_no_reply" in f.read()
