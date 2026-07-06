from __future__ import annotations

import json

import bert.summarize as sm


def test_build_prompt_includes_fields():
    p = sm.build_summary_prompt(
        {"conversation_id": 9, "subject": "Refund", "body": "double charged", "tags": ["billing"]}
    )
    assert "Refund" in p and "double charged" in p


def test_parse_good_json():
    raw = json.dumps(
        {"category": "billing", "one_line": "refund req", "urgent": True,
         "is_new": False, "matches_known_bug": None}
    )
    rec = sm.parse_summary(raw, 9)
    assert rec["conversation_id"] == 9
    assert rec["category"] == "billing"
    assert rec["urgent"] is True


def test_parse_with_fences():
    rec = sm.parse_summary(
        '```json\n{"category":"bug","one_line":"x","urgent":false,"is_new":true,"matches_known_bug":"streaks"}\n```',
        3,
    )
    assert rec["matches_known_bug"] == "streaks"


def test_parse_bad_json_fails_soft():
    rec = sm.parse_summary("not json", 7)
    assert rec["conversation_id"] == 7
    assert rec["category"] == "unknown"
    assert rec["one_line"] == "(summary unavailable)"


class _FakeMsg:
    def __init__(self, text):
        self.content = [type("B", (), {"type": "text", "text": text})()]


class _FakeClient:
    def __init__(self, text):
        self._t = text
        self.messages = self

    def create(self, **k):
        return _FakeMsg(self._t)


def test_summarize_ticket_uses_client():
    c = _FakeClient(
        json.dumps({"category": "billing", "one_line": "r", "urgent": False,
                    "is_new": True, "matches_known_bug": None})
    )
    rec = sm.summarize_ticket(c, {"conversation_id": 1, "subject": "s", "body": "b", "tags": []})
    assert rec["category"] == "billing"


def test_summarize_mailbox_isolates_failures():
    class Boom:
        messages = None

        def create(self, **k):
            raise RuntimeError("api down")

    c = Boom()
    recs = sm.summarize_mailbox(
        [{"conversation_id": 1, "subject": "s", "body": "b", "tags": []}], c, max_workers=2
    )
    assert len(recs) == 1
    assert recs[0]["one_line"] == "(summary unavailable)"


def test_summarize_mailbox_preserves_order():
    c = _FakeClient(
        json.dumps({"category": "x", "one_line": "o", "urgent": False,
                    "is_new": False, "matches_known_bug": None})
    )
    tickets = [{"conversation_id": i, "subject": "s", "body": "b", "tags": []} for i in [5, 2, 9]]
    recs = sm.summarize_mailbox(tickets, c, max_workers=3)
    assert [r["conversation_id"] for r in recs] == [5, 2, 9]


def test_fetch_open_tickets_maps_fields(monkeypatch):
    monkeypatch.setattr(
        sm, "_list_conversations",
        lambda session, mailbox_id, status: [{"id": 11, "subject": "Hi", "tags": [{"tag": "billing"}]}],
    )
    monkeypatch.setattr(sm, "_conversation_text", lambda session, cid: "body text")
    out = sm.fetch_open_tickets(object())
    assert out == [{"conversation_id": 11, "subject": "Hi", "body": "body text", "tags": ["billing"]}]
