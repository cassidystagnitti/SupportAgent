from __future__ import annotations

import json

import pytest

from scripts import stripe_apply_coupon as ac


# --- fixtures ----------------------------------------------------------------

def coupon(**overrides):
    """A 40%-off, once-duration coupon unless overridden."""
    base = {"id": "happier_renewal_40_off_once", "percent_off": 40, "duration": "once", "currency": None}
    base.update(overrides)
    return base


def subscription(**overrides):
    """An active annual subscription with no discount unless overridden."""
    base = {
        "id": "sub_1",
        "status": "active",
        "cancel_at_period_end": False,
        "cancel_at": None,
        "discount": None,
        "discounts": [],
        "items": {"data": [{"price": {"unit_amount": 9999, "currency": "usd",
                                       "recurring": {"interval": "year"}}}]},
    }
    base.update(overrides)
    return base


def monthly_sub(**overrides):
    return subscription(
        items={"data": [{"price": {"unit_amount": 1499, "currency": "usd",
                                   "recurring": {"interval": "month"}}}]},
        **overrides,
    )


def with_discount(pct, duration="once", **overrides):
    return subscription(
        discounts=[{"coupon": {"id": f"c_{pct}_{duration}", "percent_off": pct, "duration": duration}}],
        **overrides,
    )


# --- ID / percent validation -------------------------------------------------

def test_main_rejects_non_customer_ids(capsys):
    assert ac.main(["sub_123"]) == 2
    assert "not a Stripe customer ID" in capsys.readouterr().err


@pytest.mark.parametrize("bad", ["cus_", "cus_abc!", "CUS_123", "cus_1 2", "cus_a-b"])
def test_customer_id_regex_is_strict(bad):
    assert not ac.CUSTOMER_ID_RE.match(bad)


@pytest.mark.parametrize("pct", [0, 10, 25, 45, 60, 100])
def test_unsanctioned_percent_refused(pct, capsys):
    assert ac.main(["cus_123", "--percent", str(pct)]) == 2
    assert "sanctioned renewal-discount rate" in capsys.readouterr().err


@pytest.mark.parametrize("pct", [40, 50])
def test_sanctioned_percents_pass_validation(pct):
    # invalid coupon id short-circuits before any Stripe call, proving percent passed
    assert ac.main(["cus_123", "--percent", str(pct), "--coupon", "bad id!"]) == 2


def test_50_is_the_ceiling():
    assert ac.PERCENT_CEILING == 50
    assert 60 not in ac.ALLOWED_PERCENTS


# --- coupon resolution -------------------------------------------------------

def test_canonical_id_default():
    assert ac.canonical_coupon_id(40, "once") == "happier_renewal_40_off_once"
    assert ac.canonical_coupon_id(50, "forever") == "happier_renewal_50_off_forever"


def test_canonical_id_env_override(monkeypatch):
    monkeypatch.setenv("COUPON_RENEWAL_40_ONCE", "SPRING40")
    assert ac.canonical_coupon_id(40, "once") == "SPRING40"


def test_coupon_matches():
    assert ac.coupon_matches(coupon(percent_off=40, duration="once"), 40, "once")
    assert not ac.coupon_matches(coupon(percent_off=40, duration="once"), 50, "once")
    assert not ac.coupon_matches(coupon(percent_off=40, duration="once"), 40, "forever")
    assert not ac.coupon_matches(coupon(percent_off=None, duration="once"), 40, "once")


# --- classify_subscription ---------------------------------------------------

def test_clean_annual_is_eligible():
    c = ac.classify_subscription(subscription(), 40, "once")
    assert c["state"] == ac.ELIGIBLE
    assert "conflicting_discount" not in c


def test_same_discount_is_already_applied():
    c = ac.classify_subscription(with_discount(40, "once"), 40, "once")
    assert c["state"] == ac.ALREADY_APPLIED


def test_different_percent_is_eligible_but_conflicts():
    c = ac.classify_subscription(with_discount(40, "once"), 50, "once")
    assert c["state"] == ac.ELIGIBLE
    assert c["conflicting_discount"] and "40% off" in c["conflicting_discount"]


def test_same_percent_different_duration_conflicts():
    c = ac.classify_subscription(with_discount(40, "once"), 40, "forever")
    assert c["state"] == ac.ELIGIBLE
    assert c.get("conflicting_discount")


def test_monthly_is_ineligible():
    c = ac.classify_subscription(monthly_sub(), 40, "once")
    assert c["state"] == ac.INELIGIBLE
    assert "annual-only" in c["reason"] and "monthly-discount" in c["reason"]


def test_canceling_subscription_is_ineligible():
    c = ac.classify_subscription(subscription(cancel_at_period_end=True), 40, "once")
    assert c["state"] == ac.INELIGIBLE
    assert "retention save" in c["reason"]


@pytest.mark.parametrize("status", ["past_due", "canceled", "unpaid", "incomplete"])
def test_non_actionable_status_ineligible(status):
    c = ac.classify_subscription(subscription(status=status), 40, "once")
    assert c["state"] == ac.INELIGIBLE


# --- select_target -----------------------------------------------------------

def test_select_single_eligible():
    d = ac.select_target([ac.classify_subscription(subscription(), 40, "once")])
    assert d["decision"] == "proceed"


def test_select_no_subscriptions_refuses_with_apple_google_hint():
    d = ac.select_target([])
    assert d["decision"] == "refuse" and "Apple/Google" in d["reason"]


def test_select_multiple_eligible_refuses_as_escalation():
    subs = [ac.classify_subscription(subscription(id="sub_1"), 40, "once"),
            ac.classify_subscription(subscription(id="sub_2"), 40, "once")]
    d = ac.select_target(subs)
    assert d["decision"] == "refuse" and "escalation signal" in d["reason"]


def test_select_already_applied_is_noop():
    d = ac.select_target([ac.classify_subscription(with_discount(40, "once"), 40, "once")])
    assert d["decision"] == "noop"


# --- build_plan --------------------------------------------------------------

def test_plan_estimates_discounted_price():
    sub = subscription()
    c = ac.classify_subscription(sub, 40, "once")
    plan = ac.build_plan({"id": "cus_1", "email": "a@b.com"}, sub, c, 40, "once",
                         "happier_renewal_40_off_once", coupon(), False)
    assert plan["estimated_renewal_amount"] == 5999  # 9999 * 0.6 rounded
    assert plan["percent_off"] == 40 and plan["duration"] == "once"
    assert plan["will_create_coupon"] is False


def test_plan_flags_coupon_creation_when_missing():
    sub = subscription()
    c = ac.classify_subscription(sub, 50, "forever")
    plan = ac.build_plan({"id": "cus_1", "email": "a@b.com"}, sub, c, 50, "forever",
                         "happier_renewal_50_off_forever", None, False)
    assert plan["will_create_coupon"] is True
    assert any("CREATED on --apply" in n for n in plan["notes"])


def test_plan_notes_replacement_when_laddering():
    sub = with_discount(40, "once")
    c = ac.classify_subscription(sub, 50, "once")
    plan = ac.build_plan({"id": "cus_1", "email": "a@b.com"}, sub, c, 50, "once",
                         "happier_renewal_50_off_once", coupon(percent_off=50), True)
    assert plan["replace_existing"] is True
    assert any("REPLACES existing discount" in n for n in plan["notes"])


# --- gates -------------------------------------------------------------------

def test_write_gates_need_both(monkeypatch):
    monkeypatch.delenv("STRIPE_WRITE_API_KEY", raising=False)
    monkeypatch.delenv("ACTION_EXECUTION_ENABLED", raising=False)
    ok, why = ac.write_gates_ok()
    assert not ok and "STRIPE_WRITE_API_KEY" in why

    monkeypatch.setenv("STRIPE_WRITE_API_KEY", "rk_test")
    ok, why = ac.write_gates_ok()
    assert not ok and "ACTION_EXECUTION_ENABLED" in why

    monkeypatch.setenv("ACTION_EXECUTION_ENABLED", "true")
    ok, why = ac.write_gates_ok()
    assert ok and why == ""


def test_apply_without_conversation_id_refuses(monkeypatch, capsys):
    monkeypatch.setenv("STRIPE_WRITE_API_KEY", "rk_test")
    monkeypatch.setenv("ACTION_EXECUTION_ENABLED", "true")
    assert ac.main(["cus_123", "--apply"]) == 2
    assert "requires --conversation-id" in capsys.readouterr().err


def test_apply_with_gates_off_refuses(monkeypatch, capsys):
    monkeypatch.setenv("STRIPE_WRITE_API_KEY", "rk_test")
    monkeypatch.delenv("ACTION_EXECUTION_ENABLED", raising=False)
    assert ac.main(["cus_123", "--apply", "--conversation-id", "42"]) == 2
    assert "action execution disabled" in capsys.readouterr().err


# --- execute_plan (audit + verification, no network) -------------------------

class _FakeSubs:
    def __init__(self, after_modify):
        self._after = after_modify
        self.modify_calls = []

    def modify(self, sub_id, **kwargs):
        self.modify_calls.append((sub_id, kwargs))
        return self._after

    def retrieve(self, sub_id, **kwargs):
        return self._after


class _FakeCoupons:
    def __init__(self):
        self.created = []

    def create(self, **kwargs):
        self.created.append(kwargs)
        return dict(kwargs)


def _plan(**overrides):
    base = {
        "action": "apply_renewal_coupon",
        "customer_id": "cus_1",
        "subscription_id": "sub_1",
        "coupon_id": "happier_renewal_40_off_once",
        "percent_off": 40,
        "duration": "once",
        "will_create_coupon": False,
        "conflicting_discount": None,
        "replace_existing": False,
    }
    base.update(overrides)
    return base


def test_execute_applies_and_audits(tmp_path, monkeypatch):
    log = tmp_path / "log.jsonl"
    monkeypatch.setattr(ac, "AUDIT_LOG_PATH", str(log))
    applied_sub = subscription(discounts=[{"coupon": {"id": "happier_renewal_40_off_once",
                                                      "percent_off": 40, "duration": "once"}}])
    monkeypatch.setattr(ac.stripe, "Subscription", _FakeSubs(applied_sub))

    result = ac.execute_plan(_plan(), "3394816296")
    assert result["coupon_id"] == "happier_renewal_40_off_once"
    assert result["conversation_id"] == "3394816296"
    assert result["coupon_created"] is False

    line = json.loads(log.read_text().strip())
    assert line["coupon_id"] == "happier_renewal_40_off_once"
    assert line["action"] == "apply_renewal_coupon"


def test_execute_creates_missing_coupon(tmp_path, monkeypatch):
    monkeypatch.setattr(ac, "AUDIT_LOG_PATH", str(tmp_path / "log.jsonl"))
    applied_sub = subscription(discounts=[{"coupon": {"id": "happier_renewal_50_off_forever",
                                                      "percent_off": 50, "duration": "forever"}}])
    coupons = _FakeCoupons()
    monkeypatch.setattr(ac.stripe, "Subscription", _FakeSubs(applied_sub))
    monkeypatch.setattr(ac.stripe, "Coupon", coupons)

    result = ac.execute_plan(
        _plan(coupon_id="happier_renewal_50_off_forever", percent_off=50, duration="forever",
              will_create_coupon=True),
        "42",
    )
    assert result["coupon_created"] is True
    assert coupons.created and coupons.created[0]["percent_off"] == 50


def test_execute_raises_when_coupon_not_attached(tmp_path, monkeypatch):
    monkeypatch.setattr(ac, "AUDIT_LOG_PATH", str(tmp_path / "log.jsonl"))
    # Modify returns a sub WITHOUT the coupon → verification must raise.
    monkeypatch.setattr(ac.stripe, "Subscription", _FakeSubs(subscription()))
    with pytest.raises(RuntimeError, match="does not report coupon"):
        ac.execute_plan(_plan(), "42")
