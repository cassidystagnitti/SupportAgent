from __future__ import annotations

import pytest

from notion_bridge import (
    action_key,
    build_action_properties,
    build_gap_properties,
    question_matches,
)


def test_question_fuzzy_match():
    assert question_matches("What do we tell users about downloads returning?",
                            "what should we tell users about downloads coming back") is True


def test_question_distinct():
    assert question_matches("Where do podcast pitches go?",
                            "What is the streak restore procedure?") is False


def test_action_key_stable():
    assert action_key("123", "Apply coupon") == action_key("123", "Apply coupon")
    assert action_key("123", "Apply coupon") != action_key("124", "Apply coupon")


def test_action_key_not_builtin_hash():
    # sha1-based keys must be stable across process runs (unlike builtin hash(),
    # which is salted per-process for str objects unless PYTHONHASHSEED is fixed).
    import hashlib
    expected = f"123:{hashlib.sha1(b'Apply coupon').hexdigest()[:8]}"
    assert action_key("123", "Apply coupon") == expected


def test_action_key_different_actions_differ():
    assert action_key("123", "Apply coupon") != action_key("123", "Refund order")


# --- payload builders -------------------------------------------------


def test_build_gap_properties_shape():
    props = build_gap_properties(
        question="What do we tell users about downloads returning?",
        ticket_url="https://secure.helpscout.net/conversation/555",
        frequency=1,
        seen_date="2026-07-02",
    )
    assert props["Question"]["title"][0]["text"]["content"] == (
        "What do we tell users about downloads returning?"
    )
    assert props["Status"]["select"]["name"] == "Open"
    assert props["Frequency"]["number"] == 1
    assert props["First Seen"]["date"]["start"] == "2026-07-02"
    assert props["Last Seen"]["date"]["start"] == "2026-07-02"
    assert props["Source Tickets"]["rich_text"][0]["text"]["content"] == (
        "https://secure.helpscout.net/conversation/555"
    )


def test_build_gap_properties_truncates_long_text():
    long_question = "x" * 2500
    props = build_gap_properties(
        question=long_question,
        ticket_url="https://secure.helpscout.net/conversation/1",
        frequency=1,
        seen_date="2026-07-02",
    )
    assert len(props["Question"]["title"][0]["text"]["content"]) <= 2000


def test_build_action_properties_shape():
    props = build_action_properties(
        action="Apply coupon",
        system="Stripe",
        ticket_url="https://secure.helpscout.net/conversation/999",
        customer_email="user@example.com",
        confidence="High",
        key="999:abcd1234",
        created_date="2026-07-02",
    )
    assert props["Action"]["title"][0]["text"]["content"] == "Apply coupon"
    assert props["System"]["select"]["name"] == "Stripe"
    assert props["Ticket"]["url"] == "https://secure.helpscout.net/conversation/999"
    assert props["Customer"]["email"] == "user@example.com"
    assert props["Confidence"]["select"]["name"] == "High"
    assert props["Done"]["checkbox"] is False
    assert props["Created"]["date"]["start"] == "2026-07-02"
    assert props["Key"]["rich_text"][0]["text"]["content"] == "999:abcd1234"


def test_build_action_properties_invalid_system_raises():
    with pytest.raises(ValueError):
        build_action_properties(
            action="Apply coupon",
            system="NotASystem",
            ticket_url="https://secure.helpscout.net/conversation/999",
            customer_email="user@example.com",
            confidence="High",
            key="999:abcd1234",
            created_date="2026-07-02",
        )


# --- fail-soft env guard ------------------------------------------------


def test_public_functions_raise_without_token(monkeypatch, tmp_path):
    monkeypatch.delenv("NOTION_TOKEN", raising=False)
    import notion_bridge as nb

    monkeypatch.setattr(nb, "_notion_token", lambda: "")
    # Point the ids cache at an empty temp path so ensure_databases() can't
    # short-circuit via cache-first and must hit the token guard instead.
    monkeypatch.setattr(nb, "_IDS_CACHE_PATH", str(tmp_path / "notion_ids.json"))

    with pytest.raises(RuntimeError, match="NOTION_TOKEN not configured"):
        nb.ensure_databases()
    with pytest.raises(RuntimeError, match="NOTION_TOKEN not configured"):
        nb.upsert_gap("q", "1", "subject")
    with pytest.raises(RuntimeError, match="NOTION_TOKEN not configured"):
        nb.upsert_action("a", "Stripe", "1", "a@b.com", "High")
    with pytest.raises(RuntimeError, match="NOTION_TOKEN not configured"):
        nb.fetch_answered_gaps()
    with pytest.raises(RuntimeError, match="NOTION_TOKEN not configured"):
        nb.mark_incorporated("page-id")


def test_ensure_databases_cache_first_no_token_needed(monkeypatch, tmp_path):
    """When data/notion_ids.json already has all three ids, ensure_databases()
    must return from cache without requiring NOTION_TOKEN at all."""
    import json

    import notion_bridge as nb

    cache_path = tmp_path / "notion_ids.json"
    cache_path.write_text(json.dumps({"bert_ops_page": "p1", "gap_db": "g1", "action_db": "a1"}))
    monkeypatch.setattr(nb, "_IDS_CACHE_PATH", str(cache_path))
    monkeypatch.setattr(nb, "_notion_token", lambda: "")

    assert nb.ensure_databases() == {"gap_db": "g1", "action_db": "a1"}
