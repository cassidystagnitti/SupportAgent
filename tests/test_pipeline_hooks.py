from __future__ import annotations

import orchestrator


def test_gap_recorded_for_open_question(monkeypatch):
    calls = []
    monkeypatch.setattr(orchestrator.notion_bridge, "upsert_gap", lambda *a, **k: calls.append(("gap", a)))
    monkeypatch.setattr(orchestrator.notion_bridge, "upsert_action", lambda *a, **k: calls.append(("act", a)))
    parsed = {"open_question": "Where do podcast pitches go?", "confidence": "medium",
              "needs_action": False, "referenced_policies": []}
    out = {"conversation_id": "1", "ticket_subject": "Pitch", "customer_email": "a@b.c"}
    orchestrator.record_gap_and_action(out, parsed)
    assert ("gap", ("Where do podcast pitches go?", "1", "Pitch")) in [(c[0], c[1]) for c in calls]


def test_notion_failure_does_not_raise(monkeypatch):
    def boom(*a, **k): raise RuntimeError("notion down")
    monkeypatch.setattr(orchestrator.notion_bridge, "upsert_gap", boom)
    orchestrator.record_gap_and_action(
        {"conversation_id": "1", "ticket_subject": "s", "customer_email": "e"},
        {"open_question": "q?", "needs_action": False, "confidence": "low", "referenced_policies": []})


def test_gap_synthesized_for_low_confidence_without_open_question(monkeypatch):
    calls = []
    monkeypatch.setattr(orchestrator.notion_bridge, "upsert_gap", lambda *a, **k: calls.append(("gap", a)))
    monkeypatch.setattr(orchestrator.notion_bridge, "upsert_action", lambda *a, **k: calls.append(("act", a)))
    parsed = {"open_question": None, "confidence": "low", "needs_action": False, "referenced_policies": []}
    out = {"conversation_id": "42", "ticket_subject": "Refund question", "customer_email": "a@b.c"}
    orchestrator.record_gap_and_action(out, parsed)
    assert ("gap", ("How should we answer: Refund question?", "42", "Refund question")) in [
        (c[0], c[1]) for c in calls
    ]


def test_no_gap_when_confidence_not_low_and_no_open_question(monkeypatch):
    calls = []
    monkeypatch.setattr(orchestrator.notion_bridge, "upsert_gap", lambda *a, **k: calls.append(("gap", a)))
    monkeypatch.setattr(orchestrator.notion_bridge, "upsert_action", lambda *a, **k: calls.append(("act", a)))
    parsed = {"open_question": None, "confidence": "high", "needs_action": False, "referenced_policies": []}
    out = {"conversation_id": "42", "ticket_subject": "Refund question", "customer_email": "a@b.c"}
    orchestrator.record_gap_and_action(out, parsed)
    assert calls == []


def test_action_recorded_with_system_mapping_and_confidence_capitalized(monkeypatch):
    calls = []
    monkeypatch.setattr(orchestrator.notion_bridge, "upsert_gap", lambda *a, **k: calls.append(("gap", a)))
    monkeypatch.setattr(orchestrator.notion_bridge, "upsert_action", lambda *a, **k: calls.append(("act", a)))
    parsed = {
        "open_question": None,
        "confidence": "medium",
        "needs_action": True,
        "action_description": "Apply 40% renewal coupon to sub_ABC123",
        "action_system": "stripe",
        "referenced_policies": [],
    }
    out = {"conversation_id": "77", "ticket_subject": "Cancel request", "customer_email": "cust@example.com"}
    orchestrator.record_gap_and_action(out, parsed)
    assert ("act", ("Apply 40% renewal coupon to sub_ABC123", "Stripe", "77", "cust@example.com", "Medium")) in [
        (c[0], c[1]) for c in calls
    ]


def test_action_recorded_with_fallback_description_and_system(monkeypatch):
    calls = []
    monkeypatch.setattr(orchestrator.notion_bridge, "upsert_gap", lambda *a, **k: calls.append(("gap", a)))
    monkeypatch.setattr(orchestrator.notion_bridge, "upsert_action", lambda *a, **k: calls.append(("act", a)))
    parsed = {
        "open_question": None,
        "confidence": "high",
        "needs_action": True,
        "action_description": None,
        "action_system": None,
        "referenced_policies": [],
    }
    out = {"conversation_id": "88", "ticket_subject": "Weird ticket", "customer_email": "cust@example.com"}
    orchestrator.record_gap_and_action(out, parsed)
    assert ("act", ("Unspecified — see reasoning", "Other", "88", "cust@example.com", "High")) in [
        (c[0], c[1]) for c in calls
    ]


def test_action_system_mapping_for_all_known_values(monkeypatch):
    mapped = {}

    def fake_upsert_action(action, system, ticket_id, customer_email, confidence):
        mapped[ticket_id] = system

    monkeypatch.setattr(orchestrator.notion_bridge, "upsert_gap", lambda *a, **k: None)
    monkeypatch.setattr(orchestrator.notion_bridge, "upsert_action", fake_upsert_action)

    cases = [
        ("happier_admin", "Happier admin"),
        ("helpscout", "Help Scout"),
        ("something_else", "Other"),
    ]
    for i, (raw, expected) in enumerate(cases):
        parsed = {
            "open_question": None,
            "confidence": "high",
            "needs_action": True,
            "action_description": "do something",
            "action_system": raw,
            "referenced_policies": [],
        }
        out = {"conversation_id": str(i), "ticket_subject": "s", "customer_email": "e"}
        orchestrator.record_gap_and_action(out, parsed)
        assert mapped[str(i)] == expected


def test_action_failure_does_not_raise(monkeypatch):
    monkeypatch.setattr(orchestrator.notion_bridge, "upsert_gap", lambda *a, **k: None)

    def boom(*a, **k):
        raise RuntimeError("notion down")

    monkeypatch.setattr(orchestrator.notion_bridge, "upsert_action", boom)
    orchestrator.record_gap_and_action(
        {"conversation_id": "1", "ticket_subject": "s", "customer_email": "e"},
        {"open_question": None, "confidence": "high", "needs_action": True,
         "action_description": "do it", "action_system": "stripe", "referenced_policies": []},
    )
