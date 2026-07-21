"""Unit tests for the Bert MCP adapter (bert/mcp_tools.py).

These exercise the wrapping/run-store logic with the backend monkeypatched, so
they run anywhere (no network, no secrets, no MCP SDK — importable on 3.9).
"""

from __future__ import annotations

import pytest

from bert import mcp_tools


@pytest.fixture(autouse=True)
def _no_real_clients(monkeypatch):
    """Never build real Help Scout / Anthropic clients in these tests."""
    monkeypatch.setattr(mcp_tools, "_hs_session", lambda: "SESSION")
    monkeypatch.setattr(mcp_tools, "_anthropic_client", lambda: "CLIENT")


def _rec(cid, customer="Ann"):
    return {"conversation_id": cid, "customer": customer, "category": "billing",
            "one_line": "x", "urgent": False, "is_new": True, "matches_known_bug": None}


# --- summarize_mailbox ----------------------------------------------------

def test_summarize_mailbox_shapes_records(monkeypatch):
    monkeypatch.setattr(mcp_tools.bert_summarize, "fetch_open_tickets",
                        lambda s, m, status="active": [{"conversation_id": 1}, {"conversation_id": 2}])
    monkeypatch.setattr(mcp_tools.bert_summarize, "known_bug_catalog", lambda: [])
    monkeypatch.setattr(mcp_tools.bert_summarize, "summarize_mailbox",
                        lambda tickets, client, known_bugs=None: [_rec(1), _rec(2)])

    out = mcp_tools.summarize_mailbox()
    assert out["total"] == 2
    assert [r["conversation_id"] for r in out["records"]] == [1, 2]


# --- draft_all / partition / run store ------------------------------------

def _fake_draft_result(cid, *, ok=True, confidence="high", needs_action=False):
    return {"conversation_id": cid, "hs_customer_id": 99, "ok": ok, "error": None,
            "confidence": confidence, "needs_action": needs_action, "escalate": False,
            "open_question": None, "bug_report": None, "referenced_policies": [],
            "reasoning": "because", "draft_reply": f"reply-{cid}", "parsed": {}}


def test_draft_all_partitions_and_stores(monkeypatch):
    def fake_draft_all(records, session, client, brief, *, model, max_workers=6):
        return [_fake_draft_result(1, confidence="high"),
                _fake_draft_result(2, confidence="low")]
    monkeypatch.setattr(mcp_tools.bert_fanout, "draft_all", fake_draft_all)

    out = mcp_tools.draft_all([_rec(1), _rec(2)], brief="be kind")
    assert out["counts"] == {"total": 2, "ready": 1, "review": 1, "close": 0}
    assert out["ready"][0]["conversation_id"] == 1
    assert out["review"][0]["conversation_id"] == 2
    assert "low_confidence" in out["review"][0]["review_reasons"]
    assert out["ready"][0]["customer"] == "Ann"

    # results are stored server-side under the run_id, not round-tripped
    run = mcp_tools._RUNS.get(out["run_id"])
    assert set(run["results_by_cid"].keys()) == {"1", "2"}


def test_draft_all_rejects_empty():
    with pytest.raises(ValueError):
        mcp_tools.draft_all([])


# --- post_drafts ----------------------------------------------------------

def test_post_drafts_filters_by_cid(monkeypatch):
    monkeypatch.setattr(mcp_tools.bert_fanout, "draft_all",
                        lambda *a, **k: [_fake_draft_result(1), _fake_draft_result(2)])
    applied = []
    monkeypatch.setattr(mcp_tools.bert_fanout, "apply_result",
                        lambda session, r, timestamp=None, **kw: applied.append(r["conversation_id"]) or
                        {"conversation_id": r["conversation_id"], "draft_action": "updated"})

    run_id = mcp_tools.draft_all([_rec(1), _rec(2)])["run_id"]
    out = mcp_tools.post_drafts(run_id, conversation_ids=[2])
    assert out["posted"] == 1
    assert applied == [2]


def test_post_drafts_fail_soft_without_anthropic_client(monkeypatch):
    # Posting already-drafted replies must not require the Anthropic key —
    # candidates just stay unverified (and untagged).
    monkeypatch.setattr(mcp_tools.bert_fanout, "draft_all",
                        lambda *a, **k: [_fake_draft_result(1)])
    seen = {}

    def fake_apply(session, r, timestamp=None, **kw):
        seen.update(kw)
        return {"conversation_id": r["conversation_id"], "draft_action": "updated"}

    monkeypatch.setattr(mcp_tools.bert_fanout, "apply_result", fake_apply)
    run_id = mcp_tools.draft_all([_rec(1)])["run_id"]

    def boom():
        raise RuntimeError("ANTHROPIC_API_KEY not configured")

    monkeypatch.setattr(mcp_tools, "_anthropic_client", boom)
    out = mcp_tools.post_drafts(run_id)
    assert out["posted"] == 1
    assert seen["verify_client"] is None


def test_post_drafts_passes_verifier_client_and_run_brief(monkeypatch):
    monkeypatch.setattr(mcp_tools.bert_fanout, "draft_all",
                        lambda *a, **k: [_fake_draft_result(1)])
    seen = {}

    def fake_apply(session, r, timestamp=None, **kw):
        seen.update(kw)
        return {"conversation_id": r["conversation_id"], "draft_action": "updated"}

    monkeypatch.setattr(mcp_tools.bert_fanout, "apply_result", fake_apply)
    run_id = mcp_tools.draft_all([_rec(1)], brief="- streak bug fixed")["run_id"]
    mcp_tools.post_drafts(run_id)
    assert seen["verify_client"] == "CLIENT"
    assert seen["brief"] == "- streak bug fixed"


def test_post_drafts_unknown_run():
    with pytest.raises(ValueError):
        mcp_tools.post_drafts("nope")


# --- draft_ticket ---------------------------------------------------------

def test_draft_ticket_updates_run(monkeypatch):
    monkeypatch.setattr(mcp_tools.bert_fanout, "draft_all",
                        lambda *a, **k: [_fake_draft_result(1, confidence="low")])
    run_id = mcp_tools.draft_all([_rec(1)])["run_id"]

    monkeypatch.setattr(mcp_tools.bert_fanout, "draft_all",
                        lambda *a, **k: [_fake_draft_result(1, confidence="high")])
    out = mcp_tools.draft_ticket(run_id, 1, brief="fixed it")
    assert out["confidence"] == "high"
    assert mcp_tools._RUNS.get(run_id)["results_by_cid"]["1"]["confidence"] == "high"


# --- policy proposal / commit --------------------------------------------

def test_propose_then_commit(monkeypatch):
    monkeypatch.setattr(mcp_tools.policy_updater, "build_proposal",
                        lambda **kw: {"id": "abc123", "policy_file": "known-bugs.md",
                                      "edit_type": kw["edit_type"], "diff": "--- a\n+++ b\n",
                                      "status": "pending", **kw})
    committed = {}
    monkeypatch.setattr(mcp_tools.policy_updater, "confirm_proposal",
                        lambda proposal, conversation_id: committed.update(
                            {"pid": proposal["id"], "cid": conversation_id}) or {"commit_sha": "deadbeef"})

    prop = mcp_tools.propose_policy_update("known-bugs.md", "append", "", "new line", "why")
    assert prop["id"] == "abc123"
    assert prop["diff"].startswith("--- a")

    out = mcp_tools.commit_policy("abc123", source_conversation_id="555")
    assert out["commit_sha"] == "deadbeef"
    assert committed == {"pid": "abc123", "cid": "555"}


def test_commit_unknown_proposal():
    with pytest.raises(ValueError):
        mcp_tools.commit_policy("missing")


# --- compact view helpers -------------------------------------------------

def test_review_reasons_flags():
    r = _fake_draft_result(1, ok=False)
    assert "draft_failed" in mcp_tools._review_reasons(r)
    r2 = _fake_draft_result(1, needs_action=True)
    assert "needs_action" in mcp_tools._review_reasons(r2)
    r3 = _fake_draft_result(1)  # high confidence, no flags
    assert mcp_tools._review_reasons(r3) == []
