"""Smoke test: run the coupon script's dry-run path against the REAL Stripe account.

Read-only by construction — every Stripe write method the script can reach is
monkeypatched to blow up, so this also proves a dry run cannot mutate anything
even against live data. Opt-in because it needs network + real keys:

    RUN_STRIPE_SMOKE=1 .venv/bin/python -m pytest tests/smoke_stripe_apply_coupon.py -v

Target selection: STRIPE_SMOKE_CUSTOMER_ID if set, else the customer on the
most recent charge in the account.
"""

from __future__ import annotations

import os

import pytest

from scripts import stripe_apply_coupon as ac

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_STRIPE_SMOKE") != "1",
    reason="live-Stripe smoke test; set RUN_STRIPE_SMOKE=1 to run",
)


@pytest.fixture()
def read_only_stripe(monkeypatch):
    """Live read key + booby-trapped writes."""
    key = (os.environ.get("STRIPE_READ_API_KEY") or "").strip()
    if not key:
        pytest.skip("STRIPE_READ_API_KEY not configured")

    def _forbidden(*args, **kwargs):
        raise AssertionError("smoke test attempted a Stripe WRITE — dry run must never write")

    for obj, name in [
        (ac.stripe.Subscription, "modify"),
        (ac.stripe.Coupon, "create"),
        (ac.stripe.Coupon, "modify"),
        (ac.stripe.Coupon, "delete"),
    ]:
        if hasattr(obj, name):
            monkeypatch.setattr(obj, name, _forbidden)
    return key


def _pick_customer(key: str) -> str:
    explicit = (os.environ.get("STRIPE_SMOKE_CUSTOMER_ID") or "").strip()
    if explicit:
        return explicit
    ac.stripe.api_key = key
    charges = ac.stripe.Charge.list(limit=1)
    if not charges.data:
        pytest.skip("account has no charges to smoke against")
    customer = charges.data[0].customer
    if customer is None:
        pytest.skip("most recent charge has no customer attached")
    return customer if isinstance(customer, str) else customer.id


def test_dry_run_against_live_account(read_only_stripe, capsys):
    customer_id = _pick_customer(read_only_stripe)

    exit_code = ac.main([customer_id, "--json"])

    out = capsys.readouterr().out
    # Whatever state the customer's subscriptions are in, the script must resolve
    # to a deliberate outcome — never an unhandled error (exit 1).
    assert exit_code in (0, 2), out
    assert f"Customer {customer_id}" in out
    assert '"status"' in out


def test_dry_run_forever_50_is_still_readonly(read_only_stripe, capsys):
    customer_id = _pick_customer(read_only_stripe)

    exit_code = ac.main([customer_id, "--percent", "50", "--forever", "--json"])

    out = capsys.readouterr().out
    assert exit_code in (0, 2), out


def test_dry_run_rejects_garbage_customer_id(read_only_stripe, capsys):
    assert ac.main(["cus_00000000DOESNOTEXIST"]) == 1  # Stripe: no such customer
    assert "Stripe API error" in capsys.readouterr().err


def test_unsanctioned_percent_refused_before_any_call(read_only_stripe, capsys):
    customer_id = _pick_customer(read_only_stripe)
    assert ac.main([customer_id, "--percent", "60", "--json"]) == 2
    assert "sanctioned renewal-discount rate" in capsys.readouterr().err
