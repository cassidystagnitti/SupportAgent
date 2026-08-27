from __future__ import annotations

import json

import pytest

from scripts import stripe_path2_refund as p2

NOW = 1_753_000_000  # pinned "now" so window math is deterministic


def days(n: float) -> int:
    return int(n * 86400)


def charge(**overrides):
    base = {
        "id": "ch_1",
        "status": "succeeded",
        "amount": 9999,
        "amount_refunded": 0,
        "refunded": False,
        "disputed": False,
        "currency": "usd",
        "created": NOW - days(4),
        "customer": "cus_123",
        "payment_intent": "pi_1",
        "invoice": "in_1",
    }
    base.update(overrides)
    return base


def test_refund_cents_annual_40_is_forty_dollars():
    assert p2.refund_cents(9999, 40) == 4000


def test_refund_cents_annual_50():
    assert p2.refund_cents(9999, 50) == 5000


def test_refund_cents_round_half_up():
    # 1001 * 40% = 400.4 → 400
    assert p2.refund_cents(1001, 40) == 400
    # 1002 * 40% = 400.8 → 401
    assert p2.refund_cents(1002, 40) == 401


def test_window_ok_inside_30_days():
    w = p2.check_window(NOW - days(4), now_ts=NOW)
    assert w["ok"] is True
    assert w["used_grace"] is False


def test_window_refuses_day_31_without_grace():
    w = p2.check_window(NOW - days(31), now_ts=NOW)
    assert w["ok"] is False


def test_window_grace_covers_day_31():
    w = p2.check_window(NOW - days(31), boundary_grace=True, now_ts=NOW)
    assert w["ok"] is True
    assert w["used_grace"] is True


def test_window_grace_does_not_cover_day_32():
    w = p2.check_window(NOW - days(32), boundary_grace=True, now_ts=NOW)
    assert w["ok"] is False


def test_check_charge_refuses_wrong_customer():
    reason = p2.check_charge(charge(customer="cus_OTHER"), "cus_123")
    assert reason and "belongs to customer" in reason


def test_check_charge_refuses_partial_already():
    reason = p2.check_charge(charge(amount_refunded=4000), "cus_123")
    assert reason and "already carries a partial refund" in reason


def test_check_charge_refuses_disputed():
    reason = p2.check_charge(charge(disputed=True), "cus_123")
    assert reason and "DISPUTED" in reason


def test_check_charge_ok():
    assert p2.check_charge(charge(), "cus_123") is None


def test_invoice_discount_percent_from_coupon():
    invoice = {"id": "in_1", "discount": {"coupon": {"percent_off": 40}}}
    assert p2.invoice_discount_percent(invoice) == 40


def test_invoice_discount_percent_none_when_undiscounted():
    assert p2.invoice_discount_percent({"id": "in_1", "discount": None, "discounts": []}) is None


def test_invoice_discount_percent_from_discounts_list():
    invoice = {"id": "in_1", "discounts": [{"coupon": {"percent_off": 50}}]}
    assert p2.invoice_discount_percent(invoice) == 50


def test_main_rejects_unsanctioned_percent(capsys):
    assert p2.main(["cus_123", "--percent", "25"]) == 2
    assert "not sanctioned" in capsys.readouterr().err


def test_main_rejects_non_customer_ids(capsys):
    assert p2.main(["sub_123"]) == 2
    assert "not a Stripe customer ID" in capsys.readouterr().err


def test_build_plan_keeps_subscription():
    customer = {"id": "cus_123", "email": "a@b.c"}
    sub = {"id": "sub_1", "status": "active"}
    window = p2.check_window(NOW - days(4), now_ts=NOW)
    plan = p2.build_plan(customer, charge(), sub, window, 40, {"id": "in_1"})
    assert plan["action"] == "refund_path2"
    assert plan["refund_cents"] == 4000
    assert plan["percent"] == 40
    assert any("Do NOT cancel" in n for n in plan["notes"])
