"""Tests for bug_registry.py — new-bug candidate accumulation + Linear auto-filing."""

from __future__ import annotations

import json

import bug_registry


def _parsed(summary):
    return {"bug_report": {"is_bug": True, "matches_known_bug": None, "new_bug_summary": summary}}


def test_single_report_no_ticket(tmp_path, monkeypatch):
    monkeypatch.setattr(bug_registry, "REGISTRY_PATH", str(tmp_path / "r.json"))
    monkeypatch.setattr(bug_registry.linear_client, "search_issues", lambda q: [])
    created = []
    monkeypatch.setattr(bug_registry.linear_client, "create_issue",
                        lambda t, d: created.append(t) or {"identifier": "T-900"})
    c = bug_registry.record_bug(_parsed("Sleep timer resets randomly"), "1", "a@x.com", "it resets")
    assert c["linear_id"] is None and not created


def test_second_report_files_ticket(tmp_path, monkeypatch):
    monkeypatch.setattr(bug_registry, "REGISTRY_PATH", str(tmp_path / "r.json"))
    monkeypatch.setattr(bug_registry.linear_client, "search_issues", lambda q: [])
    monkeypatch.setattr(bug_registry.linear_client, "create_issue",
                        lambda t, d: {"identifier": "T-900", "url": "u"})
    bug_registry.record_bug(_parsed("Sleep timer resets randomly"), "1", "a@x.com", "resets")
    c = bug_registry.record_bug(_parsed("sleep timer keeps resetting"), "2", "b@y.com", "keeps resetting")
    assert c["linear_id"] == "T-900" and len(c["reports"]) == 2


def test_same_customer_twice_does_not_file(tmp_path, monkeypatch):
    monkeypatch.setattr(bug_registry, "REGISTRY_PATH", str(tmp_path / "r.json"))
    monkeypatch.setattr(bug_registry.linear_client, "search_issues", lambda q: [])
    monkeypatch.setattr(bug_registry.linear_client, "create_issue", lambda t, d: {"identifier": "T-901"})
    bug_registry.record_bug(_parsed("Player shows wrong time"), "1", "a@x.com", "e1")
    c = bug_registry.record_bug(_parsed("player shows the wrong time"), "2", "a@x.com", "e2")
    assert c["linear_id"] is None


def test_known_bug_skipped(tmp_path, monkeypatch):
    monkeypatch.setattr(bug_registry, "REGISTRY_PATH", str(tmp_path / "r.json"))
    p = {"bug_report": {"is_bug": True, "matches_known_bug": "Milestones broken", "new_bug_summary": None}}
    assert bug_registry.record_bug(p, "1", "a@x.com", "e") is None


# ---------------------------------------------------------------------------
# Additional coverage: not_a_bug short-circuit, registry persistence/shape,
# fuzzy-match threshold, distinct-candidate creation, Linear dedupe search,
# atomic write.
# ---------------------------------------------------------------------------

def test_not_a_bug_returns_none_and_touches_nothing(tmp_path, monkeypatch):
    registry_path = str(tmp_path / "r.json")
    monkeypatch.setattr(bug_registry, "REGISTRY_PATH", registry_path)
    p = {"bug_report": {"is_bug": False, "matches_known_bug": None, "new_bug_summary": None}}
    assert bug_registry.record_bug(p, "1", "a@x.com", "e") is None
    assert not bug_registry.os.path.exists(registry_path)


def test_missing_bug_report_key_returns_none(tmp_path, monkeypatch):
    monkeypatch.setattr(bug_registry, "REGISTRY_PATH", str(tmp_path / "r.json"))
    assert bug_registry.record_bug({}, "1", "a@x.com", "e") is None


def test_dissimilar_summaries_create_separate_candidates(tmp_path, monkeypatch):
    monkeypatch.setattr(bug_registry, "REGISTRY_PATH", str(tmp_path / "r.json"))
    monkeypatch.setattr(bug_registry.linear_client, "search_issues", lambda q: [])
    monkeypatch.setattr(bug_registry.linear_client, "create_issue", lambda t, d: {"identifier": "T-999"})
    bug_registry.record_bug(_parsed("Sleep timer resets randomly"), "1", "a@x.com", "e1")
    bug_registry.record_bug(_parsed("App crashes on launch"), "2", "b@y.com", "e2")
    data = json.loads(open(str(tmp_path / "r.json")).read())
    assert len(data["candidates"]) == 2


def test_registry_persists_atomically_across_calls(tmp_path, monkeypatch):
    registry_path = str(tmp_path / "r.json")
    monkeypatch.setattr(bug_registry, "REGISTRY_PATH", registry_path)
    monkeypatch.setattr(bug_registry.linear_client, "search_issues", lambda q: [])
    monkeypatch.setattr(bug_registry.linear_client, "create_issue", lambda t, d: {"identifier": "T-900"})
    bug_registry.record_bug(_parsed("Sleep timer resets randomly"), "1", "a@x.com", "resets")
    # No leftover tmp files after a successful write.
    leftovers = [f for f in tmp_path.iterdir() if f.name != "r.json"]
    assert leftovers == []
    data = json.loads(open(registry_path).read())
    assert "candidates" in data
    assert data["candidates"][0]["summary"] == "Sleep timer resets randomly"
    assert data["candidates"][0]["reports"][0]["email"] == "a@x.com"
    assert data["candidates"][0]["reports"][0]["ticket_id"] == "1"
    assert data["candidates"][0]["reports"][0]["excerpt"] == "resets"
    assert "date" in data["candidates"][0]["reports"][0]
    assert "first_seen" in data["candidates"][0]


def test_linear_ticket_body_contains_t759_format(tmp_path, monkeypatch):
    monkeypatch.setattr(bug_registry, "REGISTRY_PATH", str(tmp_path / "r.json"))
    monkeypatch.setattr(bug_registry.linear_client, "search_issues", lambda q: [])
    captured = {}

    def fake_create_issue(title, description):
        captured["title"] = title
        captured["description"] = description
        return {"identifier": "T-900", "url": "https://linear.app/x/issue/T-900"}

    monkeypatch.setattr(bug_registry.linear_client, "create_issue", fake_create_issue)
    bug_registry.record_bug(_parsed("Sleep timer resets randomly"), "1", "a@x.com", "it resets")
    bug_registry.record_bug(_parsed("sleep timer keeps resetting"), "2", "b@y.com", "keeps resetting")

    assert captured["title"] == "Sleep timer resets randomly"
    desc = captured["description"]
    assert "## Affected users" in desc
    assert 'a@x.com — "it resets"' in desc
    assert 'b@y.com — "keeps resetting"' in desc
    assert "## Source tickets" in desc
    assert "https://secure.helpscout.net/conversation/1" in desc
    assert "https://secure.helpscout.net/conversation/2" in desc


def test_existing_open_linear_issue_prevents_duplicate_filing(tmp_path, monkeypatch):
    monkeypatch.setattr(bug_registry, "REGISTRY_PATH", str(tmp_path / "r.json"))
    monkeypatch.setattr(
        bug_registry.linear_client,
        "search_issues",
        lambda q: [{"identifier": "T-500", "title": "Sleep timer resets randomly", "url": "u"}],
    )
    created = []
    monkeypatch.setattr(bug_registry.linear_client, "create_issue",
                        lambda t, d: created.append(t) or {"identifier": "T-999"})
    bug_registry.record_bug(_parsed("Sleep timer resets randomly"), "1", "a@x.com", "e1")
    c = bug_registry.record_bug(_parsed("sleep timer keeps resetting"), "2", "b@y.com", "e2")
    assert c["linear_id"] == "T-500"
    assert not created
