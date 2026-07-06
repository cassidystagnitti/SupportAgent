from __future__ import annotations

import bert.pipeline as pl


def test_inject_brief_appends_when_present():
    out = pl.inject_brief("MSG", "- streak fixed")
    assert out.startswith("MSG")
    assert "STANDING BRIEF" in out
    assert "streak fixed" in out


def test_inject_brief_noop_when_empty():
    assert pl.inject_brief("MSG", "") == "MSG"
    assert pl.inject_brief("MSG", "   ") == "MSG"


def test_draft_one_injects_brief_and_parses(monkeypatch):
    captured = {}

    def fake_call(client, *, system_prompt, policy_docs, dynamic_user_message, model):
        captured["msg"] = dynamic_user_message
        captured["model"] = model
        return (object(), {"draft_reply": "hi", "confidence": "high", "referenced_policies": ["p"],
                           "needs_action": False, "escalate": False, "reasoning": "r",
                           "open_question": None, "bug_report": None}, "raw")

    monkeypatch.setattr(pl.orchestrator, "_call_claude_draft_with_action_retry", fake_call)
    monkeypatch.setattr(pl.orchestrator, "load_policy_docs", lambda: "POLICIES")
    monkeypatch.setattr(pl.orchestrator, "_load_system_prompt", lambda: "SYS")
    ctx = {"conversation_id": 1, "subject": "s", "body": "b", "customer_name": "N",
           "email": "e@x.co", "account_blob": "A", "stripe_block": "S",
           "conversation_history": "", "reply_mode": False}
    res = pl.draft_one(object(), ctx, "- streak fixed", model="claude-sonnet-5")
    assert res["draft_reply"] == "hi"
    assert res["confidence"] == "high"
    assert res["referenced_policies"] == ["p"]
    assert captured["model"] == "claude-sonnet-5"
    assert "STANDING BRIEF" in captured["msg"]
    assert "streak fixed" in captured["msg"]
    # the ticket body must still be present (real _build_dynamic_user_message ran)
    assert "b" in captured["msg"]


def test_draft_one_reply_mode_prefixes(monkeypatch):
    captured = {}

    def fake_call(client, *, system_prompt, policy_docs, dynamic_user_message, model):
        captured["msg"] = dynamic_user_message
        return (object(), {"draft_reply": "x"}, "raw")

    monkeypatch.setattr(pl.orchestrator, "_call_claude_draft_with_action_retry", fake_call)
    monkeypatch.setattr(pl.orchestrator, "load_policy_docs", lambda: "P")
    monkeypatch.setattr(pl.orchestrator, "_load_system_prompt", lambda: "SYS")
    ctx = {"conversation_id": 1, "subject": "s", "body": "b", "customer_name": "N",
           "email": "e", "account_blob": "A", "stripe_block": "S",
           "conversation_history": "prev", "reply_mode": True}
    pl.draft_one(object(), ctx, "", model="m")
    assert pl.orchestrator.REPLY_MODE_PROMPT_PREFIX.split()[0] in captured["msg"]


def test_draft_one_normalizes_missing_keys(monkeypatch):
    def fake_call(client, *, system_prompt, policy_docs, dynamic_user_message, model):
        return (object(), {"draft_reply": "only"}, "raw")

    monkeypatch.setattr(pl.orchestrator, "_call_claude_draft_with_action_retry", fake_call)
    monkeypatch.setattr(pl.orchestrator, "load_policy_docs", lambda: "P")
    monkeypatch.setattr(pl.orchestrator, "_load_system_prompt", lambda: "SYS")
    ctx = {"conversation_id": 1, "subject": "s", "body": "b", "customer_name": "N",
           "email": "e", "account_blob": "A", "stripe_block": "S",
           "conversation_history": "", "reply_mode": False}
    res = pl.draft_one(object(), ctx, "", model="m")
    assert res["confidence"] is None
    assert res["referenced_policies"] == []
    assert res["needs_action"] is False
    assert res["bug_report"] is None


def test_post_draft_records_registry(monkeypatch):
    class R:
        headers = {"Resource-ID": "tid-9"}

        def raise_for_status(self):
            pass

    monkeypatch.setattr(pl.orchestrator, "_helpscout_post", lambda s, u, p: R())
    sets = {}
    monkeypatch.setattr(pl.orchestrator.draft_registry, "set", lambda cid, tid, ts: sets.update({cid: tid}))
    rid = pl.post_draft(object(), "5", 100, "draft text", "2026-07-06T00:00:00Z")
    assert rid == "tid-9"
    assert sets == {"5": "tid-9"}


def test_find_draft_threads_filters(monkeypatch):
    monkeypatch.setattr(pl.triage_tickets, "_fetch_all_threads", lambda s, cid: [
        {"id": 1, "type": "message", "state": "published"},
        {"id": 2, "type": "message", "state": "draft"},
        {"id": 3, "type": "note", "state": "draft"},
        {"id": 4, "type": "message", "state": "draft"},
    ])
    assert pl.find_draft_threads(object(), 99) == [2, 4]


def test_update_draft_patches_single_object(monkeypatch):
    captured = {}

    class R:
        status_code = 204

        def raise_for_status(self):
            pass

    class Sess:
        def patch(self, url, json=None):
            captured["url"] = url
            captured["json"] = json
            return R()

    ok = pl.update_draft(Sess(), 5, 777, "new text")
    assert ok is True
    assert captured["json"] == {"op": "replace", "path": "/text", "value": "new text"}
    assert captured["url"].endswith("/conversations/5/threads/777")


def test_hydrate_ticket_assembles_context(monkeypatch):
    o = pl.orchestrator
    monkeypatch.setattr(o, "fetch_conversation", lambda s, cid: {"subject": "Sub", "tags": []})
    monkeypatch.setattr(o, "_fetch_conversation_threads", lambda s, c, cid: [])
    monkeypatch.setattr(o, "detect_reply_mode", lambda threads: False)
    monkeypatch.setattr(o, "_customer_from_conversation", lambda c: {"id": 77, "email": "c@x.co"})
    monkeypatch.setattr(o, "_customer_display_name", lambda c: "Cust")
    monkeypatch.setattr(o, "_extract_tag_names", lambda t: [])
    monkeypatch.setattr(o, "get_conversation_text", lambda s, cid, threads=None: "ticket body")
    monkeypatch.setattr(o, "fetch_customer_emails_from_helpscout", lambda s, cid: [])
    monkeypatch.setattr(o, "fetch_account_contexts_for_ticket",
                        lambda **k: {"combined_blob": "ACCT", "emails_checked": ["c@x.co"], "multiple_subscribed": False})
    monkeypatch.setattr(o, "_subscription_platform", lambda blob: "apple")
    ctx = pl.hydrate_ticket(object(), 5)
    assert ctx["conversation_id"] == 5
    assert ctx["subject"] == "Sub"
    assert ctx["hs_customer_id"] == 77
    assert ctx["body"] == "ticket body"
    assert ctx["account_blob"] == "ACCT"
    assert ctx["reply_mode"] is False
    # non-stripe platform → stripe_block is an N/A note, enrichment not attempted
    assert "apple" in ctx["stripe_block"].lower()
