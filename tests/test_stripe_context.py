"""Tests for last-invoice (actual charge) enrichment in stripe_context.

Regression coverage for HS #3377107792: the Stripe block only exposed
forward-looking fields (Base Plan / Active Coupon / Effective Price / Next
Renewal), so a one-time coupon already consumed on the last renewal read as
"Active Coupon: None / full price" and produced a wrong "$40 difference" refund.
These tests lock in the "what was ACTUALLY charged" fields.
"""

from types import SimpleNamespace
from unittest.mock import patch

import stripe_context


# ---------------------------------------------------------------------------
# _parse_last_invoice — interpret a Stripe invoice object into flat fields
# ---------------------------------------------------------------------------

def test_parse_last_invoice_discount_from_total_discount_amounts():
    inv = SimpleNamespace(
        amount_paid=5999,
        subtotal=9999,
        total=5999,
        currency="usd",
        status_transitions=SimpleNamespace(paid_at=1718409600),
        created=1718409000,
        total_discount_amounts=[{"amount": 4000, "discount": "di_x"}],
    )
    parsed = stripe_context._parse_last_invoice(inv)
    assert parsed["amount_paid"] == 5999
    assert parsed["subtotal"] == 9999
    assert parsed["discount_amount"] == 4000
    assert parsed["percent_off"] == 40
    assert parsed["currency"] == "usd"
    assert parsed["date"] == 1718409600


def test_parse_last_invoice_discount_derived_from_subtotal_total_gap():
    # No explicit discount amounts — derive from subtotal vs total.
    inv = SimpleNamespace(
        amount_paid=5999,
        subtotal=9999,
        total=5999,
        currency="usd",
        status_transitions=SimpleNamespace(paid_at=1718409600),
    )
    parsed = stripe_context._parse_last_invoice(inv)
    assert parsed["discount_amount"] == 4000
    assert parsed["percent_off"] == 40


def test_parse_last_invoice_full_price_no_discount():
    inv = SimpleNamespace(
        amount_paid=9999,
        subtotal=9999,
        total=9999,
        currency="usd",
        status_transitions=SimpleNamespace(paid_at=1718409600),
    )
    parsed = stripe_context._parse_last_invoice(inv)
    assert parsed["discount_amount"] == 0
    assert not parsed["percent_off"]


def test_parse_last_invoice_coupon_name_best_effort():
    coupon = SimpleNamespace(name="support-discount-40-ONCE", percent_off=40, id="cpn_x")
    inv = SimpleNamespace(
        amount_paid=5999,
        subtotal=9999,
        total=5999,
        currency="usd",
        status_transitions=SimpleNamespace(paid_at=1718409600),
        discount=SimpleNamespace(coupon=coupon),
    )
    parsed = stripe_context._parse_last_invoice(inv)
    assert parsed["coupon_name"] == "support-discount-40-ONCE"
    assert parsed["percent_off"] == 40


# ---------------------------------------------------------------------------
# format_stripe_context — the block Claude actually reads
# ---------------------------------------------------------------------------

def _base_ctx(**overrides):
    ctx = {
        "stripe_customer_id": "cus_1",
        "subscription_id": "sub_1",
        "subscription_status": "active",
        "current_period_start": 1718409600,
        "current_period_end": 1749945600,
        "plan_interval": "year",
        "plan_amount": 9999,
        "plan_currency": "usd",
        "discount": None,
        "effective_plan_amount": 9999,
        "upcoming_invoice_amount": 9999,
    }
    ctx.update(overrides)
    return ctx


def test_format_renders_discounted_last_charge():
    ctx = _base_ctx(last_invoice={
        "amount_paid": 5999,
        "subtotal": 9999,
        "total": 5999,
        "currency": "usd",
        "date": 1718409600,
        "discount_amount": 4000,
        "percent_off": 40,
        "coupon_name": "support-discount-40-ONCE",
    })
    block = stripe_context.format_stripe_context(ctx)
    assert "Last Invoice Amount Charged: $59.99 USD" in block
    assert "Last Charge Date: 2024-06-15" in block
    assert "40% off" in block
    assert "$40.00 off $99.99 list price" in block


def test_format_renders_full_price_last_charge():
    ctx = _base_ctx(last_invoice={
        "amount_paid": 9999,
        "subtotal": 9999,
        "total": 9999,
        "currency": "usd",
        "date": 1718409600,
        "discount_amount": 0,
        "percent_off": None,
        "coupon_name": None,
    })
    block = stripe_context.format_stripe_context(ctx)
    assert "Last Invoice Amount Charged: $99.99 USD" in block
    assert "Last Invoice Coupon Applied: None — paid full list price" in block


def test_format_omits_last_charge_when_absent():
    ctx = _base_ctx()  # no last_invoice key
    block = stripe_context.format_stripe_context(ctx)
    assert "Last Charge" not in block
    assert "Last Invoice" not in block


# ---------------------------------------------------------------------------
# _fetch_last_invoice — pulls the most recent PAID invoice
# ---------------------------------------------------------------------------

def test_fetch_last_invoice_queries_paid_invoice():
    inv = SimpleNamespace(
        amount_paid=5999,
        subtotal=9999,
        total=5999,
        currency="usd",
        status_transitions=SimpleNamespace(paid_at=1718409600),
        total_discount_amounts=[{"amount": 4000, "discount": "di_x"}],
    )
    result_obj = SimpleNamespace(data=[inv])
    with patch.object(stripe_context.stripe.Invoice, "list", return_value=result_obj) as mock_list:
        parsed = stripe_context._fetch_last_invoice("cus_1", "sub_1")
    assert parsed["amount_paid"] == 5999
    assert parsed["percent_off"] == 40
    kwargs = mock_list.call_args.kwargs
    assert kwargs["customer"] == "cus_1"
    assert kwargs["subscription"] == "sub_1"
    assert kwargs["status"] == "paid"
    assert kwargs["limit"] == 1


def test_fetch_last_invoice_none_when_no_invoices():
    result_obj = SimpleNamespace(data=[])
    with patch.object(stripe_context.stripe.Invoice, "list", return_value=result_obj):
        assert stripe_context._fetch_last_invoice("cus_1", "sub_1") is None
