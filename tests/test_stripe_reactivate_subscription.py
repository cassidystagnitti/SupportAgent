from __future__ import annotations

import json

import pytest

from scripts import stripe_reactivate_subscription as sr

# Far-future timestamps so "has the period already lapsed?" stays deterministic.
FUTURE = 4_000_000_000
PAST = 1_000_000_000


def sub(**overrides):
    """A subscription that is set to cancel at period end unless overridden."""
    base = {
        "id": "sub_1",
        "status": "active",
        "cancel_at_period_end": True,
        "cancel_at": None,
        "pause_collection": None,
        "schedule": None,
        "metadata": {},
        "discount": None,
        "discounts": [],
        "current_period_end": FUTURE,
        "items": {"data": [{"current_period_end": FUTURE,
                            "price": {"unit_amount": 9999, "currency": "usd"}}]},
    }
    base.update(overrides)
    return base


# --- classify_subscription --------------------------------------------------

def test_cancelling_subscription_is_eligible():
    got = sr.classify_subscription(sub())
    assert got["state"] == sr.ELIGIBLE
    assert "set to cancel" in got["reason"]


def test_fixed_cancel_at_is_eligible():
    got = sr.classify_subscription(sub(cancel_at_period_end=False, cancel_at=FUTURE))
    assert got["state"] == sr.ELIGIBLE


def test_already_renewing_is_noop():
    got = sr.classify_subscription(sub(cancel_at_period_end=False))
    assert got["state"] == sr.ALREADY_ON
    assert "already ON" in got["reason"]


def test_trialing_is_eligible():
    assert sr.classify_subscription(sub(status="trialing"))["state"] == sr.ELIGIBLE


@pytest.mark.parametrize("status", ["canceled", "incomplete_expired"])
def test_ended_subscription_cannot_be_revived(status):
    got = sr.classify_subscription(sub(status=status))
    assert got["state"] == sr.INELIGIBLE
    assert "already ENDED" in got["reason"]
    assert "resubscribe" in got["reason"].lower()


@pytest.mark.parametrize("status", ["past_due", "unpaid"])
def test_dunning_is_refused_with_policy_pointer(status):
    got = sr.classify_subscription(sub(status=status))
    assert got["state"] == sr.INELIGIBLE
    assert "dunning" in got["reason"]


def test_paused_collection_is_refused():
    got = sr.classify_subscription(sub(pause_collection={"behavior": "void"}))
    assert got["state"] == sr.INELIGIBLE


def test_lapsed_period_is_refused():
    """The cancellation already took effect — nothing left to restore."""
    got = sr.classify_subscription(
        sub(current_period_end=PAST, items={"data": [{"current_period_end": PAST}]}),
        now=PAST + 10,
    )
    assert got["state"] == sr.INELIGIBLE
    assert "already taken effect" in got["reason"]


def test_period_end_falls_back_to_item_level():
    assert sr.period_end(sub(current_period_end=None)) == FUTURE


# --- select_target ----------------------------------------------------------

def test_single_eligible_proceeds():
    decision = sr.select_target([sr.classify_subscription(sub())])
    assert decision["decision"] == "proceed"


def test_multiple_cancelling_subscriptions_refuse():
    decision = sr.select_target(
        [sr.classify_subscription(sub()), sr.classify_subscription(sub(id="sub_2"))])
    assert decision["decision"] == "refuse"
    assert "refusing to guess" in decision["reason"]


def test_already_on_is_noop_decision():
    decision = sr.select_target([sr.classify_subscription(sub(cancel_at_period_end=False))])
    assert decision["decision"] == "noop"


def test_no_subscriptions_mentions_apple_google():
    decision = sr.select_target([])
    assert decision["decision"] == "refuse"
    assert "Apple/Google" in decision["reason"]


# --- build_plan -------------------------------------------------------------

def test_plan_leads_with_the_charge_the_customer_will_take():
    plan = sr.build_plan({"id": "cus_1", "email": "a@b.com"}, sub())
    assert plan["action"] == "reactivate_auto_renew"
    assert plan["renewal_amount_display"] == "$99.99"
    assert "WILL be charged" in plan["notes"][0]
    assert "asked to stay" in plan["notes"][0]


def test_plan_points_at_the_coupon_script_when_undiscounted():
    plan = sr.build_plan({"id": "cus_1"}, sub())
    assert any("stripe_apply_coupon" in n for n in plan["notes"])


def test_plan_reports_an_existing_discount_instead():
    discounted = sub(discounts=[{"coupon": {"id": "c1", "percent_off": 40, "duration": "once"}}])
    plan = sr.build_plan({"id": "cus_1"}, discounted)
    assert any("40% off" in n for n in plan["notes"])
    assert not any("stripe_apply_coupon" in n for n in plan["notes"])


def test_plan_flags_a_schedule_for_release():
    plan = sr.build_plan({"id": "cus_1"}, sub(schedule={"id": "sub_sched_1", "status": "active"}))
    assert plan["release_schedule"]["id"] == "sub_sched_1"
    assert any("RELEASED" in n for n in plan["notes"])


def test_released_schedule_is_none_when_already_released():
    plan = sr.build_plan({"id": "cus_1"}, sub(schedule={"id": "s1", "status": "released"}))
    assert plan["release_schedule"] is None


def test_plan_notes_a_cancel_at_date():
    plan = sr.build_plan({"id": "cus_1"}, sub(cancel_at_period_end=False, cancel_at=FUTURE))
    assert plan["had_cancel_at"] is True
    assert any("cleared" in n for n in plan["notes"])


# --- execute_plan -----------------------------------------------------------

class _FakeStripe:
    """Returns each queued subscription state in turn (one per modify call)."""

    def __init__(self, *returns):
        self.returns = list(returns)
        self.modify_calls = []
        self.released = []

    def modify(self, sub_id, **kwargs):
        self.modify_calls.append((sub_id, kwargs))
        return self.returns[min(len(self.modify_calls), len(self.returns)) - 1]

    def release(self, schedule_id):
        self.released.append(schedule_id)


@pytest.fixture
def audit_path(tmp_path, monkeypatch):
    path = tmp_path / "stripe_action_log.jsonl"
    monkeypatch.setattr(sr, "AUDIT_LOG_PATH", str(path))
    return path


def _patch_stripe(monkeypatch, fake):
    monkeypatch.setattr(sr.stripe.Subscription, "modify", fake.modify)
    monkeypatch.setattr(sr.stripe.SubscriptionSchedule, "release", fake.release)


def test_execute_turns_off_cancel_at_period_end(monkeypatch, audit_path):
    fake = _FakeStripe(sub(cancel_at_period_end=False))
    _patch_stripe(monkeypatch, fake)

    plan = sr.build_plan({"id": "cus_1"}, sub())
    result = sr.execute_plan(plan, "3390692208", actor="cli")

    assert fake.modify_calls == [("sub_1", {"cancel_at_period_end": False})]
    assert result["action"] == "reactivate_auto_renew"
    assert result["conversation_id"] == "3390692208"
    assert json.loads(audit_path.read_text())["subscription_id"] == "sub_1"


def test_execute_clears_a_cancel_at_that_survived_the_flag(monkeypatch, audit_path):
    """A fixed-date cancellation ignores cancel_at_period_end — clear it explicitly."""
    fake = _FakeStripe(
        sub(cancel_at_period_end=False, cancel_at=FUTURE),   # after the canonical write
        sub(cancel_at_period_end=False, cancel_at=None),     # after the explicit clear
    )
    _patch_stripe(monkeypatch, fake)

    plan = sr.build_plan({"id": "cus_1"}, sub(cancel_at_period_end=False, cancel_at=FUTURE))
    result = sr.execute_plan(plan, "3390692208")

    assert [c[1] for c in fake.modify_calls] == [{"cancel_at_period_end": False},
                                                 {"cancel_at": ""}]
    assert result["cleared_cancel_at"] is True


def test_execute_does_not_touch_cancel_at_when_the_flag_cleared_it(monkeypatch, audit_path):
    """The common shape: both fields set, and one write clears both."""
    fake = _FakeStripe(sub(cancel_at_period_end=False, cancel_at=None))
    _patch_stripe(monkeypatch, fake)

    plan = sr.build_plan({"id": "cus_1"}, sub(cancel_at_period_end=True, cancel_at=FUTURE))
    result = sr.execute_plan(plan, "3390692208")

    assert [c[1] for c in fake.modify_calls] == [{"cancel_at_period_end": False}]
    assert result["cleared_cancel_at"] is False


def test_execute_releases_the_schedule_first(monkeypatch, audit_path):
    fake = _FakeStripe(sub(cancel_at_period_end=False))
    _patch_stripe(monkeypatch, fake)

    plan = sr.build_plan({"id": "cus_1"}, sub(schedule={"id": "sub_sched_1", "status": "not_started"}))
    result = sr.execute_plan(plan, "3390692208")

    assert fake.released == ["sub_sched_1"]
    assert result["released_schedule"] == "sub_sched_1"


def test_execute_raises_when_stripe_did_not_take_the_change(monkeypatch, audit_path):
    """Post-write verification: never report success on a silent no-op."""
    fake = _FakeStripe(sub(cancel_at_period_end=True))
    _patch_stripe(monkeypatch, fake)

    plan = sr.build_plan({"id": "cus_1"}, sub())
    with pytest.raises(RuntimeError, match="still reports"):
        sr.execute_plan(plan, "3390692208")
    assert not audit_path.exists()


def test_execute_raises_when_cancel_at_survives_both_writes(monkeypatch, audit_path):
    fake = _FakeStripe(sub(cancel_at_period_end=False, cancel_at=FUTURE))
    _patch_stripe(monkeypatch, fake)

    plan = sr.build_plan({"id": "cus_1"}, sub(cancel_at_period_end=False, cancel_at=FUTURE))
    with pytest.raises(RuntimeError, match="still reports"):
        sr.execute_plan(plan, "3390692208")
    assert not audit_path.exists()


# --- gates ------------------------------------------------------------------

def test_write_gates_need_both(monkeypatch):
    monkeypatch.delenv("STRIPE_WRITE_API_KEY", raising=False)
    monkeypatch.delenv("ACTION_EXECUTION_ENABLED", raising=False)
    assert sr.write_gates_ok() == (False, "STRIPE_WRITE_API_KEY is not set")

    monkeypatch.setenv("STRIPE_WRITE_API_KEY", "rk_live_x")
    assert sr.write_gates_ok() == (False, "ACTION_EXECUTION_ENABLED is not 'true'")

    monkeypatch.setenv("ACTION_EXECUTION_ENABLED", "true")
    assert sr.write_gates_ok() == (True, "")


# --- CLI --------------------------------------------------------------------

def test_cli_rejects_a_non_customer_id(capsys):
    assert sr.main(["sub_1"]) == 2


def test_cli_apply_requires_a_conversation_id(monkeypatch):
    monkeypatch.setenv("STRIPE_WRITE_API_KEY", "rk_live_x")
    monkeypatch.setenv("ACTION_EXECUTION_ENABLED", "true")
    assert sr.main(["cus_ABC123", "--apply"]) == 2


def test_cli_apply_refuses_without_gates(monkeypatch):
    monkeypatch.delenv("STRIPE_WRITE_API_KEY", raising=False)
    monkeypatch.delenv("ACTION_EXECUTION_ENABLED", raising=False)
    assert sr.main(["cus_ABC123", "--apply", "--conversation-id", "123456"]) == 2


def test_cli_dry_run_prints_the_plan_and_writes_nothing(monkeypatch, capsys):
    monkeypatch.setenv("STRIPE_READ_API_KEY", "rk_test_read")
    monkeypatch.setattr(sr, "_fetch_customer", lambda cid: {"id": cid, "email": "a@b.com"})
    monkeypatch.setattr(sr, "_fetch_subscriptions", lambda cid: [sub()])
    monkeypatch.setattr(sr.stripe.Subscription, "modify",
                        lambda *a, **k: pytest.fail("dry run must not write"))

    assert sr.main(["cus_ABC123"]) == 0
    out = capsys.readouterr().out
    assert "PLAN: restore auto-renew" in out
    assert "Dry run only" in out


def test_cli_reports_already_renewing_as_success(monkeypatch, capsys):
    monkeypatch.setenv("STRIPE_READ_API_KEY", "rk_test_read")
    monkeypatch.setattr(sr, "_fetch_customer", lambda cid: {"id": cid, "email": "a@b.com"})
    monkeypatch.setattr(sr, "_fetch_subscriptions", lambda cid: [sub(cancel_at_period_end=False)])

    assert sr.main(["cus_ABC123"]) == 0
    assert "already renews" in capsys.readouterr().out


def test_cli_refuses_an_ended_subscription(monkeypatch, capsys):
    monkeypatch.setenv("STRIPE_READ_API_KEY", "rk_test_read")
    monkeypatch.setattr(sr, "_fetch_customer", lambda cid: {"id": cid, "email": "a@b.com"})
    monkeypatch.setattr(sr, "_fetch_subscriptions", lambda cid: [sub(status="canceled")])

    assert sr.main(["cus_ABC123"]) == 2
    assert "already ENDED" in capsys.readouterr().err
