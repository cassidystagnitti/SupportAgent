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


def test_apply_result_tags_auto_send_when_draft_posted(monkeypatch):
    monkeypatch.setattr(fo.pipeline, "find_draft_threads", lambda s, cid: [])
    monkeypatch.setattr(fo.pipeline, "conversation_status", lambda s, cid: "active")
    monkeypatch.setattr(fo.pipeline, "post_draft", lambda s, cid, hcid, txt, ts: "rid")
    monkeypatch.setattr(fo.pipeline, "should_post_note", lambda parsed: False)
    tagged = []
    monkeypatch.setattr(fo, "apply_auto_send_tag",
                        lambda s, r: tagged.append(r["conversation_id"]) or "tagged")
    result = {"conversation_id": 5, "ok": True, "draft_reply": "hi", "hs_customer_id": 9,
              "parsed": {"needs_action": False}}
    status = fo.apply_result(object(), result, timestamp="t")
    assert status["draft_action"] == "posted_new"
    assert tagged == [5]
    assert status["auto_send_tagged"] == "tagged"


def test_apply_result_does_not_tag_when_draft_skipped(monkeypatch):
    monkeypatch.setattr(fo.pipeline, "find_draft_threads", lambda s, cid: [])
    monkeypatch.setattr(fo.pipeline, "conversation_status", lambda s, cid: "closed")
    monkeypatch.setattr(fo.pipeline, "should_post_note", lambda parsed: False)
    called = []
    monkeypatch.setattr(fo, "apply_auto_send_tag", lambda s, r: called.append(1) or "tagged")
    result = {"conversation_id": 5, "ok": True, "draft_reply": "hi", "hs_customer_id": 9,
              "parsed": {"needs_action": False}}
    status = fo.apply_result(object(), result, timestamp="t")
    assert status["draft_action"] == "skipped_closed"
    assert called == []
    assert status["auto_send_tagged"] is None


def test_apply_result_posts_new_when_no_draft(monkeypatch):
    monkeypatch.setattr(fo.pipeline, "find_draft_threads", lambda s, cid: [])
    monkeypatch.setattr(fo.pipeline, "conversation_status", lambda s, cid: "active")
    posted = {}
    monkeypatch.setattr(fo.pipeline, "post_draft", lambda s, cid, hcid, txt, ts: posted.update(cid=cid))
    monkeypatch.setattr(fo.pipeline, "should_post_note", lambda parsed: False)
    result = {"conversation_id": 5, "ok": True, "draft_reply": "hi", "hs_customer_id": 9,
              "parsed": {"needs_action": False}}
    status = fo.apply_result(object(), result, timestamp="t")
    assert status["draft_action"] == "posted_new" and posted == {"cid": "5"}
    assert status["note_posted"] is False


def test_apply_result_skips_new_draft_on_closed_conversation(monkeypatch):
    # A ticket a human has already answered + closed since the draft snapshot
    # must NOT get a fresh (never-to-be-sent) draft stacked on it.
    monkeypatch.setattr(fo.pipeline, "find_draft_threads", lambda s, cid: [])
    monkeypatch.setattr(fo.pipeline, "conversation_status", lambda s, cid: "closed")
    posted = []
    monkeypatch.setattr(fo.pipeline, "post_draft", lambda *a, **k: posted.append(1))
    monkeypatch.setattr(fo.pipeline, "should_post_note", lambda parsed: False)
    result = {"conversation_id": 5, "ok": True, "draft_reply": "hi", "hs_customer_id": 9,
              "parsed": {"needs_action": False}}
    status = fo.apply_result(object(), result, timestamp="t")
    assert status["draft_action"] == "skipped_closed"
    assert posted == []


def test_apply_result_posts_new_when_status_unknown(monkeypatch):
    # If the live status check fails, fail soft toward posting (active is the
    # common case for a ticket with no draft yet).
    monkeypatch.setattr(fo.pipeline, "find_draft_threads", lambda s, cid: [])

    def boom_status(s, cid):
        raise RuntimeError("HS status down")

    monkeypatch.setattr(fo.pipeline, "conversation_status", boom_status)
    posted = {}
    monkeypatch.setattr(fo.pipeline, "post_draft", lambda s, cid, hcid, txt, ts: posted.update(cid=cid))
    monkeypatch.setattr(fo.pipeline, "should_post_note", lambda parsed: False)
    result = {"conversation_id": 5, "ok": True, "draft_reply": "hi", "hs_customer_id": 9,
              "parsed": {"needs_action": False}}
    status = fo.apply_result(object(), result, timestamp="t")
    assert status["draft_action"] == "posted_new" and posted == {"cid": "5"}


def test_apply_result_updates_existing_draft_even_if_closed(monkeypatch):
    # Updating an existing draft in place is harmless (never auto-sends); only
    # CREATING a new draft on a closed convo is the noise we guard against.
    monkeypatch.setattr(fo.pipeline, "find_draft_threads", lambda s, cid: [11])
    updated = []
    monkeypatch.setattr(fo.pipeline, "update_draft", lambda s, cid, tid, txt: updated.append(tid))
    monkeypatch.setattr(fo.pipeline, "conversation_status", lambda s, cid: "closed")
    monkeypatch.setattr(fo.pipeline, "should_post_note", lambda parsed: False)
    result = {"conversation_id": 5, "ok": True, "draft_reply": "hi", "hs_customer_id": 9,
              "parsed": {"needs_action": False}}
    status = fo.apply_result(object(), result, timestamp="t")
    assert status["draft_action"] == "updated" and updated == [11]


def test_stale_drafts_matching_selects_by_content_not_tag():
    results = [
        {"conversation_id": 1, "draft_reply": "<p>Set Happier to Unrestricted and check Sleeping apps.</p>"},
        {"conversation_id": 2, "draft_reply": "<p>The fix is released — update from the Play Store.</p>"},
        {"conversation_id": 3, "draft_reply": "<p>Your meditation keeps pausing; try the battery setting.</p>"},
        {"conversation_id": 4, "ok": False, "draft_reply": ""},
    ]
    hits = fo.stale_drafts_matching(results, include=["battery", "unrestricted", "pausing"],
                                    exclude=["fix is released", "play store"])
    assert {r["conversation_id"] for r in hits} == {1, 3}


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


def test_apply_result_continues_when_one_thread_fails(monkeypatch):
    monkeypatch.setattr(fo.pipeline, "find_draft_threads", lambda s, cid: [1, 2])
    done = []

    def flaky_update(s, cid, tid, txt):
        if tid == 1:
            raise RuntimeError("400 transient")
        done.append(tid)

    monkeypatch.setattr(fo.pipeline, "update_draft", flaky_update)
    monkeypatch.setattr(fo.pipeline, "should_post_note", lambda parsed: True)
    monkeypatch.setattr(fo.pipeline, "has_ai_note", lambda s, cid: False)
    note = []
    monkeypatch.setattr(fo.pipeline, "post_note", lambda *a, **k: note.append(1) or "n1")
    result = {"conversation_id": 5, "ok": True, "draft_reply": "hi", "parsed": {"needs_action": True}}
    status = fo.apply_result(object(), result, timestamp="t")
    # thread 2 still updated, note still posted, and the failure is recorded
    assert done == [2] and status["threads_updated"] == 1
    assert note == [1] and status["note_posted"] is True
    assert "thread 1" in status["error"]


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
