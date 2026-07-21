from __future__ import annotations

import bert.pipeline as pl


class _Resp:
    def __init__(self, status_code=201, headers=None):
        self.status_code = status_code
        self.headers = headers or {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class _Session:
    """Records PATCH calls (the close); notes go through orchestrator._helpscout_post."""

    def __init__(self, patch_status=204):
        self.patch_calls = []
        self.patch_status = patch_status

    def patch(self, url, json=None):
        self.patch_calls.append((url, json))
        return _Resp(self.patch_status)


def _threads(*bodies_and_types):
    return [{"type": t, "body": b} for b, t in bodies_and_types]


def test_customer_thread_html_keeps_customer_threads_only(monkeypatch):
    monkeypatch.setattr(pl.triage_tickets, "_fetch_all_threads", lambda s, cid: _threads(
        ("<p>first msg</p>", "customer"),
        ("<p>agent reply</p>", "message"),
        ("internal", "note"),
        ("<p>second msg</p>", "customer"),
    ))
    html = pl.customer_thread_html(object(), 42)
    assert "first msg" in html and "second msg" in html
    assert "agent reply" not in html and "internal" not in html


def test_consolidate_duplicate_happy_path(monkeypatch):
    monkeypatch.setenv("HELPSCOUT_NOTE_USER_ID", "77")
    monkeypatch.setattr(pl.triage_tickets, "_fetch_all_threads",
                        lambda s, cid: _threads(("<p>dup body</p>", "customer")))
    notes = []

    def fake_post(session, url, payload):
        notes.append((url, payload))
        return _Resp(201, {"Resource-ID": "n1"})

    monkeypatch.setattr(pl.orchestrator, "_helpscout_post", fake_post)
    session = _Session()

    out = pl.consolidate_duplicate(session, keep_cid=111, dup_cid=222)

    assert out == {"keeper_note": True, "dup_note": True, "closed": True, "error": None}
    # keeper note carries the duplicate's customer text and a link back to it
    keeper_url, keeper_payload = notes[0]
    assert "/conversations/111/notes" in keeper_url
    assert "dup body" in keeper_payload["text"]
    assert "222" in keeper_payload["text"]
    assert keeper_payload["user"] == 77
    # duplicate gets the "Duplicate of" note pointing at the keeper
    dup_url, dup_payload = notes[1]
    assert "/conversations/222/notes" in dup_url
    assert "111" in dup_payload["text"]
    # and only the duplicate is closed
    assert len(session.patch_calls) == 1
    close_url, close_body = session.patch_calls[0]
    assert "/conversations/222" in close_url
    assert close_body == {"op": "replace", "path": "/status", "value": "closed"}


def test_consolidate_without_note_user_leaves_duplicate_open(monkeypatch):
    monkeypatch.delenv("HELPSCOUT_NOTE_USER_ID", raising=False)
    monkeypatch.setattr(pl.triage_tickets, "_fetch_all_threads",
                        lambda s, cid: _threads(("<p>dup body</p>", "customer")))
    monkeypatch.setattr(pl.orchestrator, "_helpscout_post",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not post")))
    session = _Session()

    out = pl.consolidate_duplicate(session, keep_cid=111, dup_cid=222)

    assert out["keeper_note"] is False
    assert out["closed"] is False
    assert out["error"]
    assert session.patch_calls == []


def test_consolidate_keeper_note_failure_leaves_duplicate_open(monkeypatch):
    monkeypatch.setenv("HELPSCOUT_NOTE_USER_ID", "77")
    monkeypatch.setattr(pl.triage_tickets, "_fetch_all_threads",
                        lambda s, cid: _threads(("<p>dup body</p>", "customer")))

    def fake_post(session, url, payload):
        return _Resp(500)

    monkeypatch.setattr(pl.orchestrator, "_helpscout_post", fake_post)
    session = _Session()

    out = pl.consolidate_duplicate(session, keep_cid=111, dup_cid=222)

    assert out["keeper_note"] is False
    assert out["closed"] is False
    assert out["error"]
    assert session.patch_calls == []


def test_consolidate_dup_note_failure_still_closes(monkeypatch):
    """The 'Duplicate of' note is best-effort: content already landed on the
    keeper, so the close must still happen."""
    monkeypatch.setenv("HELPSCOUT_NOTE_USER_ID", "77")
    monkeypatch.setattr(pl.triage_tickets, "_fetch_all_threads",
                        lambda s, cid: _threads(("<p>dup body</p>", "customer")))
    calls = {"n": 0}

    def fake_post(session, url, payload):
        calls["n"] += 1
        return _Resp(201 if calls["n"] == 1 else 500, {"Resource-ID": "n1"})

    monkeypatch.setattr(pl.orchestrator, "_helpscout_post", fake_post)
    session = _Session()

    out = pl.consolidate_duplicate(session, keep_cid=111, dup_cid=222)

    assert out["keeper_note"] is True
    assert out["dup_note"] is False
    assert out["closed"] is True
    assert len(session.patch_calls) == 1


def test_consolidate_never_raises(monkeypatch):
    monkeypatch.setenv("HELPSCOUT_NOTE_USER_ID", "77")

    def boom(*a, **k):
        raise RuntimeError("HS down")

    monkeypatch.setattr(pl.triage_tickets, "_fetch_all_threads", boom)
    out = pl.consolidate_duplicate(_Session(), keep_cid=1, dup_cid=2)
    assert out["closed"] is False
    assert "HS down" in out["error"]
