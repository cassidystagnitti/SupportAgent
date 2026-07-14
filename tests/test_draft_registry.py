"""Tests for draft_registry.py — draft-lifecycle registry (SUP-461)."""

from __future__ import annotations

import json
import os

import draft_registry


def test_get_returns_none_when_no_registry_file(tmp_path, monkeypatch):
    monkeypatch.setattr(draft_registry, "REGISTRY_PATH", str(tmp_path / "r.json"))
    assert draft_registry.get("123") is None


def test_set_then_get_round_trip(tmp_path, monkeypatch):
    monkeypatch.setattr(draft_registry, "REGISTRY_PATH", str(tmp_path / "r.json"))
    draft_registry.set("123", "999", "2026-07-02T00:00:00+00:00")
    result = draft_registry.get("123")
    assert result == {"thread_id": "999", "drafted_at": "2026-07-02T00:00:00+00:00"}


def test_get_missing_conversation_returns_none(tmp_path, monkeypatch):
    monkeypatch.setattr(draft_registry, "REGISTRY_PATH", str(tmp_path / "r.json"))
    draft_registry.set("123", "999", "2026-07-02T00:00:00+00:00")
    assert draft_registry.get("456") is None


def test_set_overwrites_existing_entry(tmp_path, monkeypatch):
    monkeypatch.setattr(draft_registry, "REGISTRY_PATH", str(tmp_path / "r.json"))
    draft_registry.set("123", "999", "2026-07-02T00:00:00+00:00")
    draft_registry.set("123", "1000", "2026-07-03T00:00:00+00:00")
    result = draft_registry.get("123")
    assert result == {"thread_id": "1000", "drafted_at": "2026-07-03T00:00:00+00:00"}


def test_set_persists_to_disk_as_json(tmp_path, monkeypatch):
    registry_path = str(tmp_path / "r.json")
    monkeypatch.setattr(draft_registry, "REGISTRY_PATH", registry_path)
    draft_registry.set("123", "999", "2026-07-02T00:00:00+00:00")
    assert os.path.exists(registry_path)
    with open(registry_path) as f:
        data = json.load(f)
    assert data["123"] == {"thread_id": "999", "drafted_at": "2026-07-02T00:00:00+00:00"}


def test_get_on_corrupt_registry_returns_none_not_raise(tmp_path, monkeypatch):
    registry_path = tmp_path / "r.json"
    registry_path.write_text("{not valid json")
    monkeypatch.setattr(draft_registry, "REGISTRY_PATH", str(registry_path))
    assert draft_registry.get("123") is None


def test_multiple_conversations_independent(tmp_path, monkeypatch):
    monkeypatch.setattr(draft_registry, "REGISTRY_PATH", str(tmp_path / "r.json"))
    draft_registry.set("123", "999", "2026-07-02T00:00:00+00:00")
    draft_registry.set("456", "888", "2026-07-02T01:00:00+00:00")
    assert draft_registry.get("123") == {"thread_id": "999", "drafted_at": "2026-07-02T00:00:00+00:00"}
    assert draft_registry.get("456") == {"thread_id": "888", "drafted_at": "2026-07-02T01:00:00+00:00"}


# ---------------------------------------------------------------------------
# should_skip_draft truth table — True only when existing and not reply_mode
# and not force.
# ---------------------------------------------------------------------------

def test_should_skip_when_existing_and_not_reply_and_not_force():
    assert draft_registry.should_skip_draft({"thread_id": "1"}, False, False) is True


def test_should_not_skip_when_no_existing():
    assert draft_registry.should_skip_draft(None, False, False) is False


def test_should_not_skip_when_existing_and_reply_mode():
    assert draft_registry.should_skip_draft({"thread_id": "1"}, True, False) is False


def test_should_not_skip_when_existing_and_force():
    assert draft_registry.should_skip_draft({"thread_id": "1"}, False, True) is False


def test_should_not_skip_when_existing_and_reply_mode_and_force():
    assert draft_registry.should_skip_draft({"thread_id": "1"}, True, True) is False


def test_should_not_skip_when_no_existing_reply_mode_and_force_combinations():
    assert draft_registry.should_skip_draft(None, True, False) is False
    assert draft_registry.should_skip_draft(None, False, True) is False
    assert draft_registry.should_skip_draft(None, True, True) is False


def test_should_not_skip_when_draft_is_stale():
    """A newer customer message (draft_is_stale=True) overrides the skip even with
    an existing draft and neither reply_mode nor force set — so the stale draft
    gets refreshed against the latest message instead of frozen."""
    assert draft_registry.should_skip_draft({"thread_id": "1"}, False, False, draft_is_stale=True) is False


def test_draft_is_stale_defaults_false_preserving_skip():
    assert draft_registry.should_skip_draft({"thread_id": "1"}, False, False) is True
