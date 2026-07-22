from __future__ import annotations

import json

import pytest

from scripts import stripe_cancel_subscription as sc


def sub(**overrides):
    """A renewing, healthy subscription unless overridden."""
    base = {
        "id": "sub_1",
        "status": "active",
        "cancel_at_period_end": False,
        "cancel_at": None,
        "pause_collection": None,
        "schedule": None,
        "metadata": {},
        "discount": None,
        "discounts": [],
        "current_period_end": 1_790_000_000,
        "items": {"data": [{"current_period_end": 1_790_000_000}]},
    }
    base.update(overrides)
    return base


# --- classify_subscription: the three checks -------------------------------

def test_active_renewing_is_eligible():
    assert sc.classify_subscription(sub())["state"] == sc.ELIGIBLE


def test_trialing_is_eligible():
    assert sc.classify_subscription(sub(status="trialing"))["state"] == sc.ELIGIBLE


@pytest.mark.parametrize("status", ["past_due", "unpaid"])
def test_dunning_statuses_are_refused_with_policy_pointer(status):
    got = sc.classify_subscription(sub(status=status))
    assert got["state"] == sc.INELIGIBLE
    assert "IMMEDIATELY" in got["reason"]


@pytest.mark.parametrize("status", ["canceled", "incomplete", "incomplete_expired", "paused"])
def test_non_active_statuses_are_ineligible(status):
    assert sc.classify_subscription(sub(status=status))["state"] == sc.INELIGIBLE


def test_cancel_at_period_end_already_set_is_noop():
    got = sc.classify_subscription(sub(cancel_at_period_end=True))
    assert got["state"] == sc.ALREADY_OFF
    assert "access continues through" in got["reason"]


def test_cancel_at_date_counts_as_already_off():
    got = sc.classify_subscription(sub(cancel_at=1_795_000_000))
    assert got["state"] == sc.ALREADY_OFF


def test_pause_collection_is_refused():
    got = sc.classify_subscription(sub(pause_collection={"behavior": "void"}))
    assert got["state"] == sc.INELIGIBLE


# --- period_end across Stripe API versions ---------------------------------

def test_period_end_prefers_top_level_field():
    assert sc.period_end(sub(current_period_end=111)) == 111


def test_period_end_falls_back_to_items_post_basil():
    s = sub(current_period_end=None, items={"data": [{"current_period_end": 222}]})
    assert sc.period_end(s) == 222


def test_period_end_none_when_absent():
    assert sc.period_end(sub(current_period_end=None, items={"data": []})) is None


# --- select_target: exactly-one rule ----------------------------------------

def test_single_eligible_proceeds():
    decision = sc.select_target([sc.classify_subscription(sub())])
    assert decision["decision"] == "proceed"
    assert decision["target"]["subscription_id"] == "sub_1"


def test_multiple_eligible_refuses():
    classified = [
        sc.classify_subscription(sub(id="sub_1")),
        sc.classify_subscription(sub(id="sub_2")),
    ]
    decision = sc.select_target(classified)
    assert decision["decision"] == "refuse"
    assert "2 subscriptions" in decision["reason"]


def test_already_off_wins_as_noop_over_ineligible():
    classified = [
        sc.classify_subscription(sub(id="sub_1", status="canceled")),
        sc.classify_subscription(sub(id="sub_2", cancel_at_period_end=True)),
    ]
    decision = sc.select_target(classified)
    assert decision["decision"] == "noop"


def test_only_ineligible_refuses_with_reasons():
    decision = sc.select_target([sc.classify_subscription(sub(status="canceled"))])
    assert decision["decision"] == "refuse"
    assert "sub_1" in decision["reason"]


def test_no_subscriptions_refuses_with_platform_hint():
    decision = sc.select_target([])
    assert decision["decision"] == "refuse"
    assert "Apple/Google" in decision["reason"]


# --- build_plan notes --------------------------------------------------------

def test_plan_flags_free_trial():
    plan = sc.build_plan({"id": "cus_1", "email": "a@b.c"}, sub(status="trialing"))
    assert any("FREE TRIAL" in n for n in plan["notes"])


def test_plan_flags_retention_pause_not_trial():
    s = sub(status="trialing", metadata={"retention_extension": "true"})
    plan = sc.build_plan({"id": "cus_1", "email": "a@b.c"}, s)
    assert any("retention pause/extension" in n for n in plan["notes"])
    assert not any("FREE TRIAL" in n for n in plan["notes"])


def test_plan_flags_full_price_retention_offer():
    plan = sc.build_plan({"id": "cus_1", "email": "a@b.c"}, sub())
    assert any("40% retention offer" in n for n in plan["notes"])


def test_plan_omits_retention_note_when_discounted():
    plan = sc.build_plan({"id": "cus_1", "email": "a@b.c"}, sub(discount={"coupon": {"id": "x"}}))
    assert not any("40% retention offer" in n for n in plan["notes"])


def test_plan_marks_active_schedule_for_release():
    s = sub(schedule={"id": "sub_sched_1", "status": "active"})
    plan = sc.build_plan({"id": "cus_1", "email": "a@b.c"}, s)
    assert plan["release_schedule"] == {"id": "sub_sched_1", "status": "active"}
    assert any("RELEASED" in n for n in plan["notes"])


def test_plan_ignores_completed_schedule():
    s = sub(schedule={"id": "sub_sched_1", "status": "completed"})
    plan = sc.build_plan({"id": "cus_1", "email": "a@b.c"}, s)
    assert plan["release_schedule"] is None


def test_plan_unexpanded_schedule_id_still_released():
    plan = sc.build_plan({"id": "cus_1", "email": "a@b.c"}, sub(schedule="sub_sched_9"))
    assert plan["release_schedule"] == {"id": "sub_sched_9", "status": None}


# --- execute_plan: write path, schedule release, audit ----------------------

class _StripeSpy:
    def __init__(self, monkeypatch, modified_result=None):
        self.released: list[str] = []
        self.modified: list[tuple] = []
        result = modified_result or sub(cancel_at_period_end=True)

        def release(schedule_id):
            self.released.append(schedule_id)

        def modify(sub_id, **kwargs):
            self.modified.append((sub_id, kwargs))
            return result

        monkeypatch.setattr(sc.stripe.SubscriptionSchedule, "release", release)
        monkeypatch.setattr(sc.stripe.Subscription, "modify", modify)


def _plan(**overrides):
    plan = sc.build_plan({"id": "cus_1", "email": "a@b.c"}, sub(**overrides))
    return plan


def test_execute_sets_cancel_at_period_end_and_audits(monkeypatch, tmp_path):
    spy = _StripeSpy(monkeypatch)
    audit = tmp_path / "audit.jsonl"
    monkeypatch.setattr(sc, "AUDIT_LOG_PATH", str(audit))

    result = sc.execute_plan(_plan(), conversation_id="333")

    assert spy.modified == [("sub_1", {"cancel_at_period_end": True})]
    assert spy.released == []
    assert result["conversation_id"] == "333"
    logged = json.loads(audit.read_text().strip())
    assert logged["subscription_id"] == "sub_1"
    assert logged["action"] == "cancel_at_period_end"


def test_execute_releases_active_schedule_first(monkeypatch, tmp_path):
    spy = _StripeSpy(monkeypatch)
    monkeypatch.setattr(sc, "AUDIT_LOG_PATH", str(tmp_path / "audit.jsonl"))

    result = sc.execute_plan(
        _plan(schedule={"id": "sub_sched_1", "status": "active"}), conversation_id="333"
    )

    assert spy.released == ["sub_sched_1"]
    assert result["released_schedule"] == "sub_sched_1"


def test_execute_raises_if_stripe_reports_still_renewing(monkeypatch, tmp_path):
    _StripeSpy(monkeypatch, modified_result=sub(cancel_at_period_end=False))
    monkeypatch.setattr(sc, "AUDIT_LOG_PATH", str(tmp_path / "audit.jsonl"))

    with pytest.raises(RuntimeError, match="still reports"):
        sc.execute_plan(_plan(), conversation_id="333")


# --- env gates ---------------------------------------------------------------

def test_gates_require_write_key(monkeypatch):
    monkeypatch.delenv("STRIPE_WRITE_API_KEY", raising=False)
    monkeypatch.setenv("ACTION_EXECUTION_ENABLED", "true")
    ok, why = sc.write_gates_ok()
    assert not ok and "STRIPE_WRITE_API_KEY" in why


def test_gates_require_enable_flag(monkeypatch):
    monkeypatch.setenv("STRIPE_WRITE_API_KEY", "rk_test_x")
    monkeypatch.delenv("ACTION_EXECUTION_ENABLED", raising=False)
    ok, why = sc.write_gates_ok()
    assert not ok and "ACTION_EXECUTION_ENABLED" in why


def test_gates_pass_when_both_set(monkeypatch):
    monkeypatch.setenv("STRIPE_WRITE_API_KEY", "rk_test_x")
    monkeypatch.setenv("ACTION_EXECUTION_ENABLED", "true")
    assert sc.write_gates_ok() == (True, "")


# --- main: CLI contract ------------------------------------------------------

def _wire_read_path(monkeypatch, subs):
    """Stub the Stripe read calls main() makes, and trip on any write."""
    monkeypatch.setenv("STRIPE_READ_API_KEY", "rk_test_read")
    monkeypatch.setattr(sc.stripe.Customer, "retrieve", lambda cid: {"id": cid, "email": "a@b.c"})
    monkeypatch.setattr(sc, "_fetch_subscriptions", lambda cid: subs)

    def _no_write(*a, **k):
        raise AssertionError("write attempted during dry run")

    monkeypatch.setattr(sc.stripe.Subscription, "modify", _no_write)
    monkeypatch.setattr(sc.stripe.SubscriptionSchedule, "release", _no_write)


def test_main_rejects_non_customer_ids(capsys):
    assert sc.main(["sub_123"]) == 2
    assert "not a Stripe customer ID" in capsys.readouterr().err


def test_main_apply_requires_conversation_id(capsys):
    assert sc.main(["cus_123", "--apply"]) == 2
    assert "--conversation-id" in capsys.readouterr().err


def test_main_apply_blocked_without_gates(monkeypatch, capsys):
    monkeypatch.delenv("STRIPE_WRITE_API_KEY", raising=False)
    monkeypatch.delenv("ACTION_EXECUTION_ENABLED", raising=False)
    assert sc.main(["cus_123", "--apply", "--conversation-id", "1"]) == 2
    assert "action execution disabled" in capsys.readouterr().err


def test_main_dry_run_never_writes_and_exits_zero(monkeypatch, capsys):
    _wire_read_path(monkeypatch, [sub()])
    assert sc.main(["cus_123"]) == 0
    out = capsys.readouterr().out
    assert "PLAN: turn off auto-renew on sub_1" in out
    assert "Dry run only" in out
    assert "access continues through" in out


def test_main_already_off_is_noop_success(monkeypatch, capsys):
    _wire_read_path(monkeypatch, [sub(cancel_at_period_end=True)])
    assert sc.main(["cus_123"]) == 0
    assert "all set" in capsys.readouterr().out


def test_main_multiple_eligible_refuses(monkeypatch, capsys):
    _wire_read_path(monkeypatch, [sub(id="sub_1"), sub(id="sub_2")])
    assert sc.main(["cus_123"]) == 2
    assert "REFUSED" in capsys.readouterr().err


def test_main_json_output_carries_status(monkeypatch, capsys):
    _wire_read_path(monkeypatch, [sub()])
    assert sc.main(["cus_123", "--json"]) == 0
    out = capsys.readouterr().out
    payload = json.loads(out[out.index("{"):])
    assert payload["status"] == "plan"
    assert payload["subscription_id"] == "sub_1"
