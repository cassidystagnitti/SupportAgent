from __future__ import annotations

import bert.fanout as fo


def test_partition_routes_low_and_flagged():
    results = [
        {"conversation_id": 1, "ok": True, "confidence": "high", "needs_action": False,
         "escalate": False, "open_question": None, "bug_report": None},
        {"conversation_id": 2, "ok": True, "confidence": "low", "needs_action": False,
         "escalate": False, "open_question": None, "bug_report": None},
        {"conversation_id": 3, "ok": True, "confidence": "high", "needs_action": True,
         "escalate": False, "open_question": None, "bug_report": None},
        {"conversation_id": 4, "ok": False, "confidence": None, "error": "boom"},
        {"conversation_id": 5, "ok": True, "confidence": "high", "needs_action": False,
         "escalate": False, "open_question": "which plan?", "bug_report": None},
        {"conversation_id": 6, "ok": True, "confidence": "high", "needs_action": False,
         "escalate": False, "open_question": None, "bug_report": {"is_bug": True}},
    ]
    p = fo.partition(results)
    assert [r["conversation_id"] for r in p["ready"]] == [1]
    assert {r["conversation_id"] for r in p["review"]} == {2, 3, 4, 5, 6}


def test_partition_missing_confidence_goes_to_review():
    results = [{"conversation_id": 9, "ok": True, "needs_action": False, "escalate": False,
                "open_question": None, "bug_report": None}]
    p = fo.partition(results)
    assert p["ready"] == []
    assert [r["conversation_id"] for r in p["review"]] == [9]


def test_draft_all_isolates_failures(monkeypatch):
    def fake_hydrate(session, cid):
        if cid == 2:
            raise RuntimeError("hydrate fail")
        return {"conversation_id": cid, "hs_customer_id": 100 + cid}

    def fake_draft(client, ctx, brief, *, model):
        return {"draft_reply": "d", "confidence": "high", "needs_action": False,
                "escalate": False, "open_question": None, "bug_report": None,
                "referenced_policies": ["p"], "reasoning": "r"}

    monkeypatch.setattr(fo.pipeline, "hydrate_ticket", fake_hydrate)
    monkeypatch.setattr(fo.pipeline, "draft_one", fake_draft)
    recs = [{"conversation_id": 1}, {"conversation_id": 2}]
    out = fo.draft_all(recs, object(), object(), "", model="m", max_workers=2)
    by_id = {r["conversation_id"]: r for r in out}
    assert by_id[1]["ok"] is True
    assert by_id[1]["draft_reply"] == "d"
    assert by_id[1]["hs_customer_id"] == 101
    assert by_id[2]["ok"] is False
    assert "hydrate fail" in by_id[2]["error"]


def test_draft_all_passes_brief_through(monkeypatch):
    seen = {}
    monkeypatch.setattr(fo.pipeline, "hydrate_ticket", lambda s, cid: {"conversation_id": cid, "hs_customer_id": 1})

    def fake_draft(client, ctx, brief, *, model):
        seen["brief"] = brief
        return {"draft_reply": "d", "confidence": "high", "needs_action": False,
                "escalate": False, "open_question": None, "bug_report": None,
                "referenced_policies": [], "reasoning": ""}

    monkeypatch.setattr(fo.pipeline, "draft_one", fake_draft)
    fo.draft_all([{"conversation_id": 1}], object(), object(), "- streak fixed", model="m")
    assert seen["brief"] == "- streak fixed"
