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


def test_apply_result_updates_and_posts_note(monkeypatch):
    calls = {"updated": [], "note": 0}
    monkeypatch.setattr(fo.pipeline, "find_draft_threads", lambda s, cid: [11, 12])
    monkeypatch.setattr(fo.pipeline, "update_draft", lambda s, cid, tid, txt: calls["updated"].append(tid))
    monkeypatch.setattr(fo.pipeline, "should_post_note", lambda parsed: True)
    monkeypatch.setattr(fo.pipeline, "has_ai_note", lambda s, cid: False)
    monkeypatch.setattr(fo.pipeline, "post_note", lambda *a, **k: calls.update(note=calls["note"] + 1) or "note-1")
    result = {"conversation_id": 5, "ok": True, "draft_reply": "hi", "hs_customer_id": 9,
              "parsed": {"needs_action": True}, "stripe_block": "N/A", "stripe_ctx": None}
    status = fo.apply_result(object(), result, timestamp="t")
    assert status["draft_action"] == "updated"
    assert status["threads_updated"] == 2 and calls["updated"] == [11, 12]
    assert status["note_posted"] is True and calls["note"] == 1


def test_apply_result_posts_new_when_no_draft(monkeypatch):
    monkeypatch.setattr(fo.pipeline, "find_draft_threads", lambda s, cid: [])
    posted = {}
    monkeypatch.setattr(fo.pipeline, "post_draft", lambda s, cid, hcid, txt, ts: posted.update(cid=cid))
    monkeypatch.setattr(fo.pipeline, "should_post_note", lambda parsed: False)
    result = {"conversation_id": 5, "ok": True, "draft_reply": "hi", "hs_customer_id": 9,
              "parsed": {"needs_action": False}}
    status = fo.apply_result(object(), result, timestamp="t")
    assert status["draft_action"] == "posted_new" and posted == {"cid": "5"}
    assert status["note_posted"] is False


def test_apply_result_skips_note_if_exists(monkeypatch):
    monkeypatch.setattr(fo.pipeline, "find_draft_threads", lambda s, cid: [1])
    monkeypatch.setattr(fo.pipeline, "update_draft", lambda *a: True)
    monkeypatch.setattr(fo.pipeline, "should_post_note", lambda parsed: True)
    monkeypatch.setattr(fo.pipeline, "has_ai_note", lambda s, cid: True)
    posted = []
    monkeypatch.setattr(fo.pipeline, "post_note", lambda *a, **k: posted.append(1))
    result = {"conversation_id": 5, "ok": True, "draft_reply": "hi", "parsed": {"needs_action": True}}
    status = fo.apply_result(object(), result, timestamp="t")
    assert status["note_skipped_reason"] == "note_exists" and posted == []


def test_apply_result_isolates_failure(monkeypatch):
    def boom(s, cid):
        raise RuntimeError("HS down")
    monkeypatch.setattr(fo.pipeline, "find_draft_threads", boom)
    result = {"conversation_id": 5, "ok": True, "draft_reply": "hi", "parsed": {}}
    status = fo.apply_result(object(), result, timestamp="t")
    assert "HS down" in status["error"]


def test_apply_result_skips_failed_generation():
    status = fo.apply_result(object(), {"conversation_id": 5, "ok": False, "error": "gen fail"}, timestamp="t")
    assert status["error"] == "gen fail" and status["draft_action"] is None


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
