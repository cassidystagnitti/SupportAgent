from __future__ import annotations

import json

import pytest

from scripts import stripe_refund as sr

NOW = 1_753_000_000  # pinned "now" so window math is deterministic


def days(n: float) -> int:
    return int(n * 86400)


def hours(n: float) -> int:
    return int(n * 3600)


def charge(**overrides):
    """A fresh, refundable annual-renewal charge unless overridden."""
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


def subscription(**overrides):
    """An active annual subscription unless overridden."""
    base = {
        "id": "sub_1",
        "status": "active",
        "cancel_at_period_end": False,
        "cancel_at": None,
        "schedule": None,
        "trial_end": None,
        "metadata": {},
        "discount": None,
        "discounts": [],
        "items": {"data": [{"price": {"recurring": {"interval": "year"}}}]},
    }
    base.update(overrides)
    return base


def monthly_sub(**overrides):
    return subscription(items={"data": [{"price": {"recurring": {"interval": "month"}}}]}, **overrides)


def invoice(**overrides):
    base = {"id": "in_1", "subscription": "sub_1"}
    base.update(overrides)
    return base


# --- ID validation ------------------------------------------------------------

def test_main_rejects_non_customer_ids(capsys):
    assert sr.main(["sub_123"]) == 2
    assert "not a Stripe customer ID" in capsys.readouterr().err


def test_main_rejects_bad_charge_ids(capsys):
    assert sr.main(["cus_123", "--charge-id", "in_123"]) == 2
    assert "not a Stripe charge ID" in capsys.readouterr().err


@pytest.mark.parametrize("bad", ["cus_", "cus_abc!", "CUS_123", "cus_123 456", "cus_abc-def"])
def test_customer_id_regex_is_strict(bad):
    assert not sr.CUSTOMER_ID_RE.match(bad)


@pytest.mark.parametrize("bad", ["ch_", "ch_abc-def", "re_123", "py_123", "ch_1;rm"])
def test_charge_id_regex_is_strict(bad):
    assert not sr.CHARGE_ID_RE.match(bad)


# --- check_charge: eligibility ---------------------------------------------------

def test_healthy_charge_passes():
    assert sr.check_charge(charge(), "cus_123") is None


def test_charge_owned_by_other_customer_refused():
    reason = sr.check_charge(charge(customer="cus_OTHER"), "cus_123")
    assert reason and "cus_OTHER" in reason and "refusing" in reason


def test_charge_with_no_customer_refused():
    reason = sr.check_charge(charge(customer=None), "cus_123")
    assert reason and "nobody" in reason


def test_charge_with_expanded_customer_object_matches():
    assert sr.check_charge(charge(customer={"id": "cus_123"}), "cus_123") is None


@pytest.mark.parametrize("status", ["pending", "failed"])
def test_non_succeeded_charge_refused(status):
    reason = sr.check_charge(charge(status=status), "cus_123")
    assert reason and "succeeded" in reason


def test_disputed_charge_refused_points_to_dispute_flow():
    reason = sr.check_charge(charge(disputed=True), "cus_123")
    assert reason and "DISPUTED" in reason and "dashboard" in reason


def test_fully_refunded_charge_refused():
    reason = sr.check_charge(charge(refunded=True, amount_refunded=9999), "cus_123")
    assert reason and "already fully refunded" in reason


def test_partially_refunded_charge_refused_to_human_review():
    reason = sr.check_charge(charge(amount_refunded=4000), "cus_123")
    assert reason and "partial refund" in reason and "human review" in reason
    assert "Path-2" in reason  # partial refunds are the separate retroactive-discount script


def test_over_cap_charge_refused():
    reason = sr.check_charge(charge(amount=15000), "cus_123")
    assert reason and "$120.00" in reason and "$150.00" in reason


def test_cap_boundary_120_exactly_allowed():
    assert sr.check_charge(charge(amount=12000), "cus_123") is None


# --- window math ------------------------------------------------------------------

def test_annual_29_days_within_window():
    w = sr.check_window("year", NOW - days(29), boundary_grace=False, now_ts=NOW)
    assert w["ok"] and not w["used_grace"]


def test_annual_31_days_refused():
    w = sr.check_window("year", NOW - days(31), boundary_grace=False, now_ts=NOW)
    assert not w["ok"]
    assert "PAST the 30-day annual refund window" in w["verdict"]


def test_annual_just_past_30_days_needs_grace():
    created = NOW - days(30) - hours(6)
    assert not sr.check_window("year", created, boundary_grace=False, now_ts=NOW)["ok"]
    w = sr.check_window("year", created, boundary_grace=True, now_ts=NOW)
    assert w["ok"] and w["used_grace"]
    assert "boundary grace" in w["verdict"]


def test_annual_grace_is_exactly_one_day():
    past_grace = NOW - days(31) - hours(1)
    w = sr.check_window("year", past_grace, boundary_grace=True, now_ts=NOW)
    assert not w["ok"]
    assert "even with the 1-day boundary grace" in w["verdict"]


def test_monthly_23_hours_within_window():
    w = sr.check_window("month", NOW - hours(23), boundary_grace=False, now_ts=NOW)
    assert w["ok"] and not w["used_grace"]


def test_monthly_25_hours_refused():
    w = sr.check_window("month", NOW - hours(25), boundary_grace=False, now_ts=NOW)
    assert not w["ok"]
    assert "PAST the 24-hour monthly refund window" in w["verdict"]


def test_monthly_just_past_24_hours_needs_grace():
    created = NOW - hours(24) - 600
    assert not sr.check_window("month", created, boundary_grace=False, now_ts=NOW)["ok"]
    w = sr.check_window("month", created, boundary_grace=True, now_ts=NOW)
    assert w["ok"] and w["used_grace"]


def test_monthly_grace_is_exactly_one_hour():
    w = sr.check_window("month", NOW - hours(25) - 60, boundary_grace=True, now_ts=NOW)
    assert not w["ok"]


def test_grace_never_applied_when_within_standard_window():
    w = sr.check_window("year", NOW - days(10), boundary_grace=True, now_ts=NOW)
    assert w["ok"] and not w["used_grace"]


# --- interval determination ---------------------------------------------------------

def test_interval_from_price_recurring():
    assert sr.subscription_interval(subscription()) == "year"


def test_interval_from_legacy_plan_object():
    s = subscription(items={"data": [{"plan": {"interval": "month"}}]})
    assert sr.subscription_interval(s) == "month"


def test_interval_none_when_no_items():
    assert sr.subscription_interval(subscription(items={"data": []})) is None


def test_interval_none_when_mixed():
    s = subscription(
        items={
            "data": [
                {"price": {"recurring": {"interval": "year"}}},
                {"price": {"recurring": {"interval": "month"}}},
            ]
        }
    )
    assert sr.subscription_interval(s) is None


# --- charge → subscription resolution ------------------------------------------------

def test_resolve_via_charge_invoice_field(monkeypatch):
    monkeypatch.setattr(sr.stripe.Invoice, "retrieve", lambda iid, **k: invoice())
    monkeypatch.setattr(sr.stripe.Subscription, "retrieve", lambda sid, **k: subscription(id=sid))
    sub, why = sr.resolve_subscription(charge())
    assert why == "" and sub["id"] == "sub_1"


def test_resolve_via_invoice_payments_when_charge_has_no_invoice_field(monkeypatch):
    """Post-basil/dahlia: Charge carries no invoice — the InvoicePayment mapping fills in."""
    calls = {}

    def fake_ip_list(**kwargs):
        calls.update(kwargs)
        return {
            "data": [
                {
                    "invoice": invoice(
                        subscription=None,
                        parent={"subscription_details": {"subscription": "sub_9"}},
                    )
                }
            ]
        }

    monkeypatch.setattr(sr.stripe.InvoicePayment, "list", fake_ip_list)
    monkeypatch.setattr(sr.stripe.Subscription, "retrieve", lambda sid, **k: subscription(id=sid))
    sub, why = sr.resolve_subscription(charge(invoice=None))
    assert sub["id"] == "sub_9"
    assert calls["payment"] == {"type": "payment_intent", "payment_intent": "pi_1"}


def test_resolve_refuses_oneoff_charge(monkeypatch):
    monkeypatch.setattr(sr.stripe.InvoicePayment, "list", lambda **k: {"data": []})
    sub, why = sr.resolve_subscription(charge(invoice=None))
    assert sub is None and "one-off" in why and "human review" in why


def test_resolve_refuses_charge_with_no_pi_and_no_invoice():
    sub, why = sr.resolve_subscription(charge(invoice=None, payment_intent=None))
    assert sub is None and "no linked invoice" in why


def test_resolve_refuses_non_subscription_invoice(monkeypatch):
    monkeypatch.setattr(
        sr.stripe.Invoice, "retrieve", lambda iid, **k: {"id": "in_1", "subscription": None, "parent": None}
    )
    sub, why = sr.resolve_subscription(charge())
    assert sub is None and "not generated by a subscription" in why


# --- plan building -------------------------------------------------------------------

def _plan(ch=None, sub=None, interval="year", grace=False, and_cancel_now=False):
    ch = ch or charge()
    sub = sub or subscription()
    window = sr.check_window(interval, ch["created"], boundary_grace=grace, now_ts=NOW)
    assert window["ok"], "test fixture built an out-of-window plan"
    return sr.build_plan({"id": "cus_123", "email": "a@b.c"}, ch, sub, interval, window, and_cancel_now)


def test_plan_shows_required_dry_run_fields():
    plan = _plan()
    assert plan["customer_id"] == "cus_123"
    assert plan["customer_email"] == "a@b.c"
    assert plan["charge_id"] == "ch_1"
    assert plan["amount_cents"] == 9999
    assert plan["amount_display"] == "$99.99"
    assert plan["charge_age"] == "4.0 days"
    assert "within the 30-day annual refund window" in plan["window_verdict"]
    assert plan["subscription_id"] == "sub_1"
    assert plan["subscription_status"] == "active"
    assert plan["plan_interval"] == "year"


def test_plan_flags_trial_conversion_charge():
    ch = charge(created=NOW - days(2))
    sub = subscription(trial_end=NOW - days(2) - 300)  # trial ended 5 minutes before the charge
    plan = _plan(ch=ch, sub=sub)
    assert any("trial-conversion" in n for n in plan["notes"])


def test_plan_no_trial_note_for_ordinary_renewal():
    plan = _plan(sub=subscription(trial_end=NOW - days(400)))
    assert not any("trial-conversion" in n for n in plan["notes"])


def test_plan_flags_discounted_subscription():
    plan = _plan(sub=subscription(discount={"coupon": {"id": "x"}}))
    assert any("WithDiscount" in n for n in plan["notes"])


def test_plan_warns_refund_alone_leaves_sub_renewing():
    plan = _plan(and_cancel_now=False)
    assert plan["cancel_now"] is None
    assert any("does not stop future charges" in n for n in plan["notes"])


def test_plan_no_renewal_warning_when_cancel_now_requested():
    plan = _plan(and_cancel_now=True)
    assert not any("does not stop future charges" in n for n in plan["notes"])


def test_plan_grace_note_present_when_used():
    ch = charge(created=NOW - days(30) - hours(3))
    plan = _plan(ch=ch, grace=True)
    assert plan["window_used_grace"]
    assert any("boundary-generosity" in n for n in plan["notes"])


def test_plan_non_usd_note():
    plan = _plan(ch=charge(currency="gbp"))
    assert any("FX" in n for n in plan["notes"])
    assert plan["amount_display"] == "99.99 GBP"


def test_cancel_now_on_active_sub():
    cn = sr.build_cancel_now(subscription())
    assert cn["will_cancel"]
    assert "IMMEDIATELY" in cn["reason"]
    assert cn["release_schedule"] is None


def test_cancel_now_noop_on_fully_canceled_sub():
    cn = sr.build_cancel_now(subscription(status="canceled"))
    assert not cn["will_cancel"]
    assert "already fully canceled" in cn["reason"]


def test_cancel_now_still_cancels_when_only_cancel_at_period_end_set():
    cn = sr.build_cancel_now(subscription(cancel_at_period_end=True))
    assert cn["will_cancel"]
    assert "canceling now anyway" in cn["reason"]


def test_cancel_now_releases_active_schedule_first():
    cn = sr.build_cancel_now(subscription(schedule={"id": "sub_sched_1", "status": "active"}))
    assert cn["release_schedule"] == {"id": "sub_sched_1", "status": "active"}


def test_cancel_now_ignores_completed_schedule():
    cn = sr.build_cancel_now(subscription(schedule={"id": "sub_sched_1", "status": "completed"}))
    assert cn["release_schedule"] is None


# --- execute_plan: write path, ordering, verification, audit --------------------------

class _StripeSpy:
    """Records Stripe calls in order; responses are configurable."""

    def __init__(
        self,
        monkeypatch,
        refund_result=None,
        cancel_result=None,
        cancel_raises=None,
        fresh_charge=None,
    ):
        self.calls: list[tuple] = []
        refund_result = refund_result or {
            "id": "re_1",
            "status": "succeeded",
            "charge": {"id": "ch_1", "refunded": True, "amount_refunded": 9999},
        }
        cancel_result = cancel_result or {"id": "sub_1", "status": "canceled"}
        fresh_charge = fresh_charge or {"id": "ch_1", "refunded": True, "amount_refunded": 9999}

        def refund_create(**kwargs):
            self.calls.append(("refund_create", kwargs))
            return refund_result

        def sub_cancel(sub_id, **kwargs):
            self.calls.append(("subscription_cancel", sub_id))
            if cancel_raises:
                raise cancel_raises
            return cancel_result

        def sched_release(sched_id, **kwargs):
            self.calls.append(("schedule_release", sched_id))

        def charge_retrieve(cid, **kwargs):
            self.calls.append(("charge_retrieve", cid))
            return fresh_charge

        monkeypatch.setattr(sr.stripe.Refund, "create", refund_create)
        monkeypatch.setattr(sr.stripe.Subscription, "cancel", sub_cancel)
        monkeypatch.setattr(sr.stripe.SubscriptionSchedule, "release", sched_release)
        monkeypatch.setattr(sr.stripe.Charge, "retrieve", charge_retrieve)


def test_execute_full_refund_call_shape_never_passes_amount(monkeypatch, tmp_path):
    spy = _StripeSpy(monkeypatch)
    monkeypatch.setattr(sr, "AUDIT_LOG_PATH", str(tmp_path / "audit.jsonl"))

    result = sr.execute_plan(_plan(), conversation_id="333")

    kind, kwargs = spy.calls[0]
    assert kind == "refund_create"
    assert kwargs["charge"] == "ch_1"
    assert "amount" not in kwargs  # full refund = Stripe computes the amount, we never do
    assert kwargs["reason"] == "requested_by_customer"
    assert result["refund_id"] == "re_1"
    assert result["conversation_id"] == "333"


def test_execute_refund_before_cancel_ordering(monkeypatch, tmp_path):
    spy = _StripeSpy(monkeypatch)
    monkeypatch.setattr(sr, "AUDIT_LOG_PATH", str(tmp_path / "audit.jsonl"))

    result = sr.execute_plan(_plan(and_cancel_now=True), conversation_id="333")

    kinds = [k for k, *_ in spy.calls if k in ("refund_create", "subscription_cancel")]
    assert kinds == ["refund_create", "subscription_cancel"]
    assert result["and_cancel_now"]["result"] == "canceled"


def test_execute_refund_failure_cancels_nothing(monkeypatch, tmp_path):
    audit = tmp_path / "audit.jsonl"
    monkeypatch.setattr(sr, "AUDIT_LOG_PATH", str(audit))

    def boom(**kwargs):
        raise sr.stripe.error.StripeError("card issuer says no")

    def trap(*a, **k):
        raise AssertionError("cancel ran after the refund failed")

    monkeypatch.setattr(sr.stripe.Refund, "create", boom)
    monkeypatch.setattr(sr.stripe.Subscription, "cancel", trap)
    monkeypatch.setattr(sr.stripe.SubscriptionSchedule, "release", trap)

    with pytest.raises(sr.stripe.error.StripeError):
        sr.execute_plan(_plan(and_cancel_now=True), conversation_id="333")
    assert not audit.exists()  # nothing happened → nothing audited


def test_execute_cancel_skipped_when_sub_already_canceled(monkeypatch, tmp_path):
    spy = _StripeSpy(monkeypatch)
    monkeypatch.setattr(sr, "AUDIT_LOG_PATH", str(tmp_path / "audit.jsonl"))

    plan = _plan(sub=subscription(status="canceled"), and_cancel_now=True)
    result = sr.execute_plan(plan, conversation_id="333")

    assert result["and_cancel_now"]["result"] == "skipped"
    assert not any(k == "subscription_cancel" for k, *_ in spy.calls)


def test_execute_releases_schedule_before_cancel(monkeypatch, tmp_path):
    spy = _StripeSpy(monkeypatch)
    monkeypatch.setattr(sr, "AUDIT_LOG_PATH", str(tmp_path / "audit.jsonl"))

    plan = _plan(sub=subscription(schedule={"id": "sub_sched_1", "status": "active"}), and_cancel_now=True)
    result = sr.execute_plan(plan, conversation_id="333")

    kinds = [k for k, *_ in spy.calls]
    assert kinds.index("schedule_release") < kinds.index("subscription_cancel")
    assert result["and_cancel_now"]["released_schedule"] == "sub_sched_1"


def test_execute_verification_raises_when_charge_not_refunded(monkeypatch, tmp_path):
    _StripeSpy(
        monkeypatch,
        refund_result={
            "id": "re_1",
            "status": "succeeded",
            "charge": {"id": "ch_1", "refunded": False, "amount_refunded": 0},
        },
    )
    monkeypatch.setattr(sr, "AUDIT_LOG_PATH", str(tmp_path / "audit.jsonl"))

    with pytest.raises(RuntimeError, match="still reports"):
        sr.execute_plan(_plan(), conversation_id="333")


def test_execute_verification_raises_on_failed_refund_status(monkeypatch, tmp_path):
    _StripeSpy(monkeypatch, refund_result={"id": "re_1", "status": "failed", "charge": None})
    monkeypatch.setattr(sr, "AUDIT_LOG_PATH", str(tmp_path / "audit.jsonl"))

    with pytest.raises(RuntimeError, match="nothing was refunded"):
        sr.execute_plan(_plan(), conversation_id="333")


def test_execute_verification_falls_back_to_charge_retrieve(monkeypatch, tmp_path):
    # Refund response carries only the charge id (unexpanded) — verify via re-read.
    spy = _StripeSpy(monkeypatch, refund_result={"id": "re_1", "status": "succeeded", "charge": "ch_1"})
    monkeypatch.setattr(sr, "AUDIT_LOG_PATH", str(tmp_path / "audit.jsonl"))

    sr.execute_plan(_plan(), conversation_id="333")

    assert ("charge_retrieve", "ch_1") in spy.calls


def test_execute_cancel_failure_still_audits_refund_and_raises(monkeypatch, tmp_path):
    audit = tmp_path / "audit.jsonl"
    _StripeSpy(monkeypatch, cancel_raises=sr.stripe.error.StripeError("schedule says no"))
    monkeypatch.setattr(sr, "AUDIT_LOG_PATH", str(audit))

    with pytest.raises(RuntimeError, match="Do NOT re-run"):
        sr.execute_plan(_plan(and_cancel_now=True), conversation_id="333")

    logged = json.loads(audit.read_text().strip())
    assert logged["refund_id"] == "re_1"  # the refund DID happen and is on record
    assert logged["and_cancel_now"]["result"] == "failed"


def test_audit_line_content(monkeypatch, tmp_path):
    _StripeSpy(monkeypatch)
    audit = tmp_path / "audit.jsonl"
    monkeypatch.setattr(sr, "AUDIT_LOG_PATH", str(audit))

    sr.execute_plan(_plan(and_cancel_now=True), conversation_id="3390548887")

    logged = json.loads(audit.read_text().strip())
    assert logged["action"] == "refund_full"
    assert logged["customer_id"] == "cus_123"
    assert logged["charge_id"] == "ch_1"
    assert logged["amount_cents"] == 9999
    assert logged["currency"] == "usd"
    assert logged["refund_id"] == "re_1"
    assert logged["subscription_id"] == "sub_1"
    assert logged["conversation_id"] == "3390548887"
    assert logged["and_cancel_now"]["result"] == "canceled"
    assert "executed_at" in logged


# --- env gates -----------------------------------------------------------------------

def test_gates_require_write_key(monkeypatch):
    monkeypatch.delenv("STRIPE_WRITE_API_KEY", raising=False)
    monkeypatch.setenv("ACTION_EXECUTION_ENABLED", "true")
    ok, why = sr.write_gates_ok()
    assert not ok and "STRIPE_WRITE_API_KEY" in why


def test_gates_require_enable_flag(monkeypatch):
    monkeypatch.setenv("STRIPE_WRITE_API_KEY", "rk_test_x")
    monkeypatch.delenv("ACTION_EXECUTION_ENABLED", raising=False)
    ok, why = sr.write_gates_ok()
    assert not ok and "ACTION_EXECUTION_ENABLED" in why


def test_gates_pass_when_both_set(monkeypatch):
    monkeypatch.setenv("STRIPE_WRITE_API_KEY", "rk_test_x")
    monkeypatch.setenv("ACTION_EXECUTION_ENABLED", "true")
    assert sr.write_gates_ok() == (True, "")


# --- main: CLI contract -----------------------------------------------------------------

def _wire_read_path(monkeypatch, charges=None, sub=None, inv=None):
    """Stub the Stripe reads main() makes, pin the clock, and trip on any write."""
    monkeypatch.setenv("STRIPE_READ_API_KEY", "rk_test_read")
    monkeypatch.setattr(sr, "_now_ts", lambda: NOW)
    monkeypatch.setattr(sr.stripe.Customer, "retrieve", lambda cid: {"id": cid, "email": "a@b.c"})

    charges = charges if charges is not None else [charge()]
    by_id = {c["id"]: c for c in charges}
    monkeypatch.setattr(sr.stripe.Charge, "list", lambda **k: {"data": charges})
    monkeypatch.setattr(sr.stripe.Charge, "retrieve", lambda cid, **k: by_id[cid])
    monkeypatch.setattr(sr.stripe.Invoice, "retrieve", lambda iid, **k: inv or invoice())
    monkeypatch.setattr(sr.stripe.Subscription, "retrieve", lambda sid, **k: sub or subscription())
    monkeypatch.setattr(sr.stripe.InvoicePayment, "list", lambda **k: {"data": []})

    def _no_write(*a, **k):
        raise AssertionError("write attempted during dry run")

    monkeypatch.setattr(sr.stripe.Refund, "create", _no_write)
    monkeypatch.setattr(sr.stripe.Subscription, "cancel", _no_write)
    monkeypatch.setattr(sr.stripe.Subscription, "delete", _no_write)
    monkeypatch.setattr(sr.stripe.Subscription, "modify", _no_write)
    monkeypatch.setattr(sr.stripe.SubscriptionSchedule, "release", _no_write)


def test_main_apply_requires_conversation_id(capsys):
    assert sr.main(["cus_123", "--apply"]) == 2
    assert "--conversation-id" in capsys.readouterr().err


def test_main_apply_blocked_without_gates(monkeypatch, capsys):
    monkeypatch.delenv("STRIPE_WRITE_API_KEY", raising=False)
    monkeypatch.delenv("ACTION_EXECUTION_ENABLED", raising=False)
    assert sr.main(["cus_123", "--apply", "--conversation-id", "1"]) == 2
    assert "action execution disabled" in capsys.readouterr().err


def test_main_dry_run_never_writes_and_exits_zero(monkeypatch, capsys):
    _wire_read_path(monkeypatch)
    assert sr.main(["cus_123"]) == 0
    out = capsys.readouterr().out
    assert "PLAN: fully refund ch_1" in out
    assert "Dry run only" in out
    assert "$99.99" in out


def test_main_dry_run_with_cancel_now_never_writes(monkeypatch, capsys):
    _wire_read_path(monkeypatch)
    assert sr.main(["cus_123", "--and-cancel-now"]) == 0
    out = capsys.readouterr().out
    assert "and-cancel-now" in out
    assert "IMMEDIATELY" in out


def test_main_picks_latest_succeeded_charge(monkeypatch, capsys):
    charges = [
        charge(id="ch_failed", status="failed", created=NOW - hours(1)),
        charge(id="ch_new", created=NOW - hours(2)),
        charge(id="ch_old", created=NOW - days(10)),
    ]
    _wire_read_path(monkeypatch, charges=charges)
    assert sr.main(["cus_123", "--json"]) == 0
    out = capsys.readouterr().out
    payload = json.loads(out[out.index("{"):])
    assert payload["charge_id"] == "ch_new"  # newest SUCCEEDED, not newest overall


def test_main_no_succeeded_charge_refuses(monkeypatch, capsys):
    _wire_read_path(monkeypatch, charges=[charge(status="failed")])
    assert sr.main(["cus_123"]) == 2
    assert "no succeeded charges" in capsys.readouterr().err


def test_main_explicit_charge_must_belong_to_customer(monkeypatch, capsys):
    _wire_read_path(monkeypatch, charges=[charge(customer="cus_OTHER")])
    assert sr.main(["cus_123", "--charge-id", "ch_1"]) == 2
    assert "REFUSED" in capsys.readouterr().err


def test_main_missing_charge_id_is_refusal_not_crash(monkeypatch, capsys):
    _wire_read_path(monkeypatch)

    def gone(cid, **k):
        raise sr.stripe.error.InvalidRequestError("No such charge", "id", code="resource_missing")

    monkeypatch.setattr(sr.stripe.Charge, "retrieve", gone)
    assert sr.main(["cus_123", "--charge-id", "ch_gone"]) == 2
    assert "does not exist" in capsys.readouterr().err


def test_main_disputed_charge_refuses(monkeypatch, capsys):
    _wire_read_path(monkeypatch, charges=[charge(disputed=True)])
    assert sr.main(["cus_123"]) == 2
    assert "DISPUTED" in capsys.readouterr().err


def test_main_past_window_refuses(monkeypatch, capsys):
    _wire_read_path(monkeypatch, charges=[charge(created=NOW - days(45))])
    assert sr.main(["cus_123"]) == 2
    err = capsys.readouterr().err
    assert "PAST the 30-day" in err and "cancel at next renewal" in err


def test_main_boundary_grace_flag_rescues_day_30(monkeypatch, capsys):
    _wire_read_path(monkeypatch, charges=[charge(created=NOW - days(30) - hours(1))])
    assert sr.main(["cus_123"]) == 2  # without the flag: refused
    capsys.readouterr()
    assert sr.main(["cus_123", "--boundary-grace"]) == 0  # with it: honored
    assert "boundary grace" in capsys.readouterr().out


def test_main_monthly_window_ok_at_23h(monkeypatch, capsys):
    _wire_read_path(monkeypatch, charges=[charge(created=NOW - hours(23))], sub=monthly_sub())
    assert sr.main(["cus_123"]) == 0
    assert "24-hour monthly" in capsys.readouterr().out


def test_main_monthly_window_refused_at_25h(monkeypatch, capsys):
    _wire_read_path(monkeypatch, charges=[charge(created=NOW - hours(25))], sub=monthly_sub())
    assert sr.main(["cus_123"]) == 2
    assert "PAST the 24-hour" in capsys.readouterr().err


def test_main_indeterminable_interval_refuses(monkeypatch, capsys):
    _wire_read_path(monkeypatch, charges=[charge(invoice=None, payment_intent=None)])
    assert sr.main(["cus_123"]) == 2
    assert "no linked invoice" in capsys.readouterr().err


def test_main_unsupported_interval_refuses(monkeypatch, capsys):
    weekly = subscription(items={"data": [{"price": {"recurring": {"interval": "week"}}}]})
    _wire_read_path(monkeypatch, sub=weekly)
    assert sr.main(["cus_123"]) == 2
    assert "annual and monthly" in capsys.readouterr().err


def test_main_json_status_discipline_on_plan(monkeypatch, capsys):
    _wire_read_path(monkeypatch)
    assert sr.main(["cus_123", "--json"]) == 0
    out = capsys.readouterr().out
    payload = json.loads(out[out.index("{"):])
    assert payload["status"] == "plan"  # the outcome marker owns "status"
    assert payload["charge_status"] == "succeeded"  # Stripe statuses live under renamed keys
    assert payload["subscription_status"] == "active"
    assert payload["action"] == "refund_full"


def test_main_refused_json_carries_reason(monkeypatch, capsys):
    _wire_read_path(monkeypatch, charges=[charge(disputed=True)])
    assert sr.main(["cus_123", "--json"]) == 2
    out = capsys.readouterr().out
    payload = json.loads(out[out.index("{"):])
    assert payload["status"] == "refused"
    assert "DISPUTED" in payload["reason"]


def test_main_apply_end_to_end(monkeypatch, capsys, tmp_path):
    monkeypatch.setenv("STRIPE_WRITE_API_KEY", "rk_test_write")
    monkeypatch.setenv("ACTION_EXECUTION_ENABLED", "true")
    monkeypatch.setattr(sr, "AUDIT_LOG_PATH", str(tmp_path / "audit.jsonl"))
    monkeypatch.setattr(sr, "_now_ts", lambda: NOW)
    monkeypatch.setattr(sr.stripe.Customer, "retrieve", lambda cid: {"id": cid, "email": "a@b.c"})
    monkeypatch.setattr(sr.stripe.Charge, "list", lambda **k: {"data": [charge()]})
    monkeypatch.setattr(sr.stripe.Invoice, "retrieve", lambda iid, **k: invoice())
    monkeypatch.setattr(sr.stripe.Subscription, "retrieve", lambda sid, **k: subscription())
    monkeypatch.setattr(sr.stripe.InvoicePayment, "list", lambda **k: {"data": []})
    _StripeSpy(monkeypatch)

    assert sr.main(["cus_123", "--and-cancel-now", "--apply", "--conversation-id", "42", "--json"]) == 0

    out = capsys.readouterr().out
    payload = json.loads(out[out.index("{"):])
    assert payload["status"] == "applied"
    assert payload["refund_id"] == "re_1"
    assert payload["and_cancel_now"]["result"] == "canceled"
    assert (tmp_path / "audit.jsonl").exists()
    assert "APPLIED: refund re_1" in out
