from __future__ import annotations

import json

import bert.summarize as sm


def test_build_prompt_includes_fields():
    p = sm.build_summary_prompt(
        {"conversation_id": 9, "subject": "Refund", "body": "double charged", "tags": ["billing"]}
    )
    assert "Refund" in p and "double charged" in p


def test_slugify():
    assert sm._slugify("Streaks Broken or Reset") == "streaks-broken-or-reset"
    assert sm._slugify("Do Not Disturb Toggle Missing or Broken (Android v2)") == "do-not-disturb-toggle-missing-or-broken-android-v2"


def test_known_bug_catalog_parses(tmp_path):
    doc = tmp_path / "known-bugs.md"
    doc.write_text(
        "# Known Bugs\n\n## 1. Streaks Broken or Reset\nstuff\n\n## 2. Milestones Broken (New App)\nmore\n"
    )
    cat = sm.known_bug_catalog(str(doc))
    assert cat == [
        ("streaks-broken-or-reset", "Streaks Broken or Reset"),
        ("milestones-broken-new-app", "Milestones Broken (New App)"),
    ]


def test_build_prompt_lists_known_bug_slugs():
    p = sm.build_summary_prompt(
        {"conversation_id": 1, "subject": "s", "body": "b", "tags": []},
        known_bugs=[("streaks-broken-or-reset", "Streaks Broken or Reset")],
    )
    assert "streaks-broken-or-reset" in p
    assert "Streaks Broken or Reset" in p


def test_parse_coerces_unknown_slug_to_null():
    raw = '{"category":"bug","one_line":"x","urgent":false,"is_new":true,"matches_known_bug":"made-up-slug"}'
    rec = sm.parse_summary(raw, 3, valid_bug_slugs={"streaks-broken-or-reset"})
    assert rec["matches_known_bug"] is None


def test_parse_keeps_valid_slug():
    raw = '{"category":"bug","one_line":"x","urgent":false,"is_new":true,"matches_known_bug":"streaks-broken-or-reset"}'
    rec = sm.parse_summary(raw, 3, valid_bug_slugs={"streaks-broken-or-reset"})
    assert rec["matches_known_bug"] == "streaks-broken-or-reset"


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
        lambda session, mailbox_id, status: [
            {"id": 11, "subject": "Hi", "tags": [{"tag": "billing"}],
             "primaryCustomer": {"id": 1, "firstName": "Jo", "lastName": "Doe"}}
        ],
    )
    monkeypatch.setattr(sm, "_conversation_text", lambda session, cid: "body text")
    out = sm.fetch_open_tickets(object())
    assert out == [{
        "conversation_id": 11, "customer": "Jo Doe", "subject": "Hi",
        "body": "body text", "tags": ["billing"],
    }]


def test_list_conversations_paginates(monkeypatch):
    pages = {
        1: {"_embedded": {"conversations": [{"id": 1}, {"id": 2}]}, "page": {"totalPages": 3, "number": 1}},
        2: {"_embedded": {"conversations": [{"id": 3}, {"id": 4}]}, "page": {"totalPages": 3, "number": 2}},
        3: {"_embedded": {"conversations": [{"id": 5}]}, "page": {"totalPages": 3, "number": 3}},
    }
    calls = []

    def fake_api_get(session, url, params=None):
        calls.append(params["page"])
        return pages[params["page"]]

    monkeypatch.setattr(sm.triage_tickets, "api_get", fake_api_get)
    out = sm._list_conversations(object(), None, "active")
    assert [c["id"] for c in out] == [1, 2, 3, 4, 5]
    assert calls == [1, 2, 3]
