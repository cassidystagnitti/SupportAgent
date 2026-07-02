from __future__ import annotations

import pytest

from action_executor import execute, format_actions_note, prepare_cancellation, prepare_coupon


def test_prepare_coupon_includes_sub_id():
    plan = prepare_coupon({"subscription_id": "sub_123", "stripe_customer_id": "cus_9"}, 40)
    assert plan.params["subscription_id"] == "sub_123" and plan.params["percent"] == 40
    assert "40%" in plan.human_summary


def test_prepare_coupon_includes_customer_id():
    plan = prepare_coupon({"subscription_id": "sub_123", "stripe_customer_id": "cus_9"}, 40)
    assert plan.params["customer_id"] == "cus_9"


def test_prepare_coupon_missing_ids_defaults_none():
    plan = prepare_coupon({}, 25)
    assert plan.params["subscription_id"] is None
    assert plan.params["customer_id"] is None
    assert plan.params["percent"] == 25
    assert plan.kind == "apply_coupon"


def test_prepare_cancellation_defaults_at_period_end():
    plan = prepare_cancellation({"subscription_id": "sub_1"})
    assert plan.params["subscription_id"] == "sub_1"
    assert plan.params["at_period_end"] is True
    assert plan.kind == "cancel_subscription"
    assert "sub_1" in plan.human_summary


def test_prepare_cancellation_immediate():
    plan = prepare_cancellation({"subscription_id": "sub_1"}, at_period_end=False)
    assert plan.params["at_period_end"] is False
    assert "immediately" in plan.human_summary.lower()


def test_execute_disabled_by_default(monkeypatch):
    monkeypatch.delenv("STRIPE_WRITE_API_KEY", raising=False)
    monkeypatch.delenv("ACTION_EXECUTION_ENABLED", raising=False)
    with pytest.raises(RuntimeError):
        execute(prepare_cancellation({"subscription_id": "sub_1"}))


def test_execute_disabled_with_only_key_set(monkeypatch):
    monkeypatch.setenv("STRIPE_WRITE_API_KEY", "sk_live_fake")
    monkeypatch.delenv("ACTION_EXECUTION_ENABLED", raising=False)
    with pytest.raises(RuntimeError):
        execute(prepare_cancellation({"subscription_id": "sub_1"}))


def test_execute_disabled_with_only_flag_set(monkeypatch):
    monkeypatch.delenv("STRIPE_WRITE_API_KEY", raising=False)
    monkeypatch.setenv("ACTION_EXECUTION_ENABLED", "true")
    with pytest.raises(RuntimeError):
        execute(prepare_cancellation({"subscription_id": "sub_1"}))


def test_execute_raises_not_implemented_when_gate_passes(monkeypatch):
    monkeypatch.setenv("STRIPE_WRITE_API_KEY", "sk_live_fake")
    monkeypatch.setenv("ACTION_EXECUTION_ENABLED", "true")
    with pytest.raises(NotImplementedError):
        execute(prepare_cancellation({"subscription_id": "sub_1"}))


def test_actions_note_lists_action():
    html = format_actions_note(
        {"needs_action": True, "action_description": "Apply 40% coupon", "action_system": "stripe"},
        {"subscription_id": "sub_1"},
    )
    assert "Actions needed" in html and "Apply 40% coupon" in html and "stripe" in html.lower()


def test_actions_note_empty_when_no_action():
    assert format_actions_note({"needs_action": False}, None) == ""


def test_actions_note_includes_subscription_id_when_available():
    html = format_actions_note(
        {"needs_action": True, "action_description": "Cancel subscription", "action_system": "stripe"},
        {"subscription_id": "sub_42", "plan_amount": 1999},
    )
    assert "sub_42" in html


def test_actions_note_handles_missing_stripe_ctx():
    html = format_actions_note(
        {"needs_action": True, "action_description": "Update account email", "action_system": "happier_admin"},
        None,
    )
    assert "Actions needed" in html and "Update account email" in html
