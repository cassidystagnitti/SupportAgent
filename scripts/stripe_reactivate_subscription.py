"""Turn auto-renew back ON for one Stripe customer's subscription (un-cancel).

The fourth Stripe write skill, and the exact inverse of
``scripts/stripe_cancel_subscription.py``: it clears ``cancel_at_period_end`` /
``cancel_at`` so a subscription that was set to lapse renews normally again.

Why this exists: a customer cancels, then writes back — "actually I'll stay if
you can do something on the price". Attaching a renewal coupon to a subscription
that is set to cancel does nothing at all (there is no renewal to discount), so
``scripts/stripe_apply_coupon.py`` refuses that case outright. This script is the
missing first half of that retention save; ``stripe_apply_coupon.py
--reactivate`` runs both in the right order.

**This one costs the customer money.** Cancel-at-period-end is a promise not to
charge; undoing it re-arms a charge on the renewal date. Only run it when the
customer has asked to stay — the plan output states the amount and the date so
that is impossible to do by accident.

Checks enforced in code (not prompt):
  * The subscription is active (or trialing — real trials AND the retention
    "pause", which is a trial_end push).
  * It has NOT already ended. A ``canceled`` subscription cannot be revived by
    modifying it; that customer needs a fresh checkout link, and the refusal
    says so rather than failing obscurely at the API.
  * It is NOT delinquent (past_due / unpaid). Re-arming renewal on a
    subscription that is already failing to collect just queues another failed
    charge — that is the dunning path (policies/failed-payment-dunning.md).
  * Collection is not paused.
  * It is actually set to cancel. Already-renewing subscriptions are an
    idempotent no-op success, mirroring the cancel script's ALREADY_OFF.
  * The current period has not already lapsed.
  * Exactly one subscription qualifies. Zero or multiple → refuse with reasons
    (multiple live subscriptions is an escalation signal per policy).

Subscription schedules: like cancellation, a schedule-managed subscription
rejects/overrides a direct ``cancel_at_period_end`` change, so an attached
schedule in status not_started/active is RELEASED first (keeps the
subscription, detaches the schedule, discards pending scheduled changes).

Safety:
  * Dry-run by default; nothing is mutated unless --apply is passed.
  * --apply requires BOTH env gates: STRIPE_WRITE_API_KEY and
    ACTION_EXECUTION_ENABLED=true, plus --conversation-id so every write is
    tied to a Help Scout ticket.
  * Dry-run works with STRIPE_READ_API_KEY alone (never uses STRIPE_API_KEY).
  * Every apply appends an audit line to data/stripe_action_log.jsonl.

Usage:
    # dry run — inspect the plan, no writes possible:
    python3 scripts/stripe_reactivate_subscription.py cus_ABC123

    # execute (both env gates must be set):
    python3 scripts/stripe_reactivate_subscription.py cus_ABC123 --apply --conversation-id 3390692208

    # machine-readable output for the skill layer:
    python3 scripts/stripe_reactivate_subscription.py cus_ABC123 --json

Exit codes: 0 = success (applied, plan built, or already renewing) · 2 = checks
refused the action · 1 = unexpected/Stripe error.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from typing import Any

import stripe
from dotenv import load_dotenv

_SUPPORT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(_SUPPORT_DIR, ".env"))

AUDIT_LOG_PATH = os.path.join(_SUPPORT_DIR, "data", "stripe_action_log.jsonl")

CUSTOMER_ID_RE = re.compile(r"^cus_[A-Za-z0-9]+$")

ACTIONABLE_STATUSES = {"active", "trialing"}
DUNNING_STATUSES = {"past_due", "unpaid"}
# Terminal states: nothing to un-cancel, the subscription is gone.
ENDED_STATUSES = {"canceled", "incomplete_expired"}

ELIGIBLE = "eligible"
ALREADY_ON = "already_on"
INELIGIBLE = "ineligible"


def _g(obj: Any, key: str, default: Any = None) -> Any:
    """Read a key off a Stripe object or plain dict."""
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _fmt_date(ts: int | None) -> str:
    if not ts:
        return "unknown date"
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%B %-d, %Y")


def _money(cents: int | None, currency: str | None = "usd") -> str:
    if cents is None:
        return "unknown amount"
    symbol = "$" if (currency or "usd").lower() == "usd" else f"{(currency or '').upper()} "
    return f"{symbol}{cents / 100:,.2f}"


def period_end(sub: Any) -> int | None:
    """Current period end across Stripe API versions.

    Older API versions expose `current_period_end` on the subscription; from
    2025-03-31.basil onward it lives on each subscription item.
    """
    top = _g(sub, "current_period_end")
    if top:
        return top
    items = _g(_g(sub, "items") or {}, "data") or []
    ends = [e for e in (_g(item, "current_period_end") for item in items) if e]
    return max(ends) if ends else None


def _unit_amount(sub: Any) -> tuple[int | None, str | None]:
    """The renewal unit amount + currency off the first item's price."""
    items = _g(_g(sub, "items") or {}, "data") or []
    if not items:
        return None, None
    price = _g(items[0], "price") or {}
    return _g(price, "unit_amount"), _g(price, "currency")


def _schedule_info(sub: Any) -> dict[str, Any] | None:
    """Normalize the sub's schedule (expanded object or bare id) to a dict."""
    schedule = _g(sub, "schedule")
    if not schedule:
        return None
    if isinstance(schedule, str):
        return {"id": schedule, "status": None}
    return {"id": _g(schedule, "id"), "status": _g(schedule, "status")}


def _describe_discount(sub: Any) -> str | None:
    """A short label for whatever discount rides on the renewal, if any."""
    discounts = _g(sub, "discounts") or []
    discount = discounts[0] if discounts else _g(sub, "discount")
    if not discount:
        return None
    coupon = _g(discount, "coupon") if not isinstance(discount, str) else None
    if not coupon:
        return "an existing discount"
    percent, amount_off = _g(coupon, "percent_off"), _g(coupon, "amount_off")
    if percent:
        return f"{percent:g}% off ({_g(coupon, 'duration') or 'unknown duration'})"
    if amount_off:
        return f"{_money(amount_off, _g(coupon, 'currency'))} off"
    return _g(coupon, "id") or "an existing discount"


def classify_subscription(sub: Any, *, now: int | None = None) -> dict[str, Any]:
    """Apply the eligibility checks to one subscription.

    Returns {"state": ELIGIBLE | ALREADY_ON | INELIGIBLE, "reason": str, ...}.
    """
    status = _g(sub, "status")
    end_ts = period_end(sub)
    amount, currency = _unit_amount(sub)
    # NB: keyed "subscription_status" (not "status") so these dicts can merge
    # into the CLI's JSON payload, whose "status" field is the outcome marker.
    info: dict[str, Any] = {
        "subscription_id": _g(sub, "id"),
        "subscription_status": status,
        "period_end": end_ts,
        "period_end_display": _fmt_date(end_ts),
        "unit_amount": amount,
        "currency": currency,
    }

    if status in ENDED_STATUSES:
        info.update(
            state=INELIGIBLE,
            reason=(
                f"status={status}: this subscription has already ENDED — there is nothing to "
                "un-cancel. Stripe cannot revive it; the customer needs to resubscribe through a "
                "checkout link (see the standardized links in policies/account-lookup-data-model.md)."
            ),
        )
        return info

    if status in DUNNING_STATUSES:
        info.update(
            state=INELIGIBLE,
            reason=(
                f"status={status}: in the failed-payment/dunning flow. Re-arming renewal here just "
                "queues another failed charge — fix collection first "
                "(policies/failed-payment-dunning.md)."
            ),
        )
        return info

    if status not in ACTIONABLE_STATUSES:
        info.update(state=INELIGIBLE, reason=f"status={status}: not an active subscription.")
        return info

    if _g(sub, "pause_collection"):
        info.update(
            state=INELIGIBLE,
            reason="payment collection is paused (pause_collection set) — resolve the pause "
            "in the dashboard before changing renewal state.",
        )
        return info

    cancel_at = _g(sub, "cancel_at")
    if not (_g(sub, "cancel_at_period_end") or cancel_at):
        info.update(state=ALREADY_ON, reason="auto-renew is already ON — it renews normally.")
        return info

    now = now if now is not None else int(datetime.now(tz=timezone.utc).timestamp())
    ends_at = cancel_at or end_ts
    if ends_at and ends_at <= now:
        info.update(
            state=INELIGIBLE,
            reason=(
                f"the paid period ended {_fmt_date(ends_at)} — the cancellation has already taken "
                "effect, so there is no renewal to restore. Resubscribe via a checkout link."
            ),
        )
        return info

    info.update(
        state=ELIGIBLE,
        reason=f"set to cancel on {_fmt_date(ends_at)} — auto-renew can be restored.",
    )
    return info


def select_target(classified: list[dict[str, Any]]) -> dict[str, Any]:
    """Pick the single actionable subscription, or explain why we refuse."""
    eligible = [c for c in classified if c["state"] == ELIGIBLE]
    already_on = [c for c in classified if c["state"] == ALREADY_ON]

    if len(eligible) == 1:
        return {"decision": "proceed", "target": eligible[0]}
    if len(eligible) > 1:
        return {
            "decision": "refuse",
            "reason": (
                f"{len(eligible)} subscriptions are set to cancel — refusing to guess which one "
                "the customer means. Multiple live subscriptions is an escalation signal (see "
                "policy); resolve in the Stripe dashboard."
            ),
            "candidates": eligible,
        }
    if already_on:
        return {"decision": "noop", "reason": already_on[0]["reason"], "target": already_on[0]}
    if classified:
        reasons = "; ".join(f"{c['subscription_id']}: {c['reason']}" for c in classified)
        return {"decision": "refuse", "reason": f"no subscription can be reactivated. {reasons}"}
    return {
        "decision": "refuse",
        "reason": (
            "no Stripe subscriptions on this customer. If they claim an active plan, "
            "they may be on Apple/Google — those renew through the store, not through us "
            "(check account context before replying)."
        ),
    }


def build_plan(customer: Any, sub: Any) -> dict[str, Any]:
    """Assemble the human-reviewable plan for one eligible subscription."""
    status = _g(sub, "status")
    schedule = _schedule_info(sub)
    end_ts = period_end(sub)
    cancel_at = _g(sub, "cancel_at")
    amount, currency = _unit_amount(sub)
    discount = _describe_discount(sub)

    notes: list[str] = [
        f"the customer WILL be charged {_money(amount, currency)} on "
        f"{_fmt_date(cancel_at or end_ts)} — only do this if they asked to stay."
    ]
    if discount:
        notes.append(f"carries {discount} — the actual charge is lower than the list price above.")
    else:
        notes.append(
            "no discount attached — if this is a retention save, apply the coupon too "
            "(scripts/stripe_apply_coupon.py, or --reactivate on that script to do both)."
        )
    if status == "trialing":
        notes.append(
            "status=trialing — restoring renewal means the trial (or retention extension) will "
            "convert to a paid charge at its end date."
        )
    if cancel_at:
        notes.append(f"a cancel_at date is set ({_fmt_date(cancel_at)}) — it will be cleared.")
    if schedule:
        notes.append(
            f"managed by subscription schedule {schedule['id']} "
            f"(status={schedule['status'] or 'unknown'}) — the schedule will be RELEASED first; "
            "any pending scheduled changes (e.g. a queued plan switch) are discarded."
        )

    return {
        "action": "reactivate_auto_renew",
        "customer_id": _g(customer, "id"),
        "customer_email": _g(customer, "email"),
        "subscription_id": _g(sub, "id"),
        "subscription_status": status,
        "period_end": end_ts,
        "renews_on": _fmt_date(cancel_at or end_ts),
        "renewal_amount": amount,
        "currency": currency,
        "renewal_amount_display": _money(amount, currency),
        "existing_discount": discount,
        "had_cancel_at": bool(cancel_at),
        "release_schedule": schedule if schedule and schedule["status"] in (None, "active", "not_started") else None,
        "notes": notes,
    }


def write_gates_ok() -> tuple[bool, str]:
    """Same contract as action_executor.execute: both gates or nothing."""
    key = (os.environ.get("STRIPE_WRITE_API_KEY") or "").strip()
    enabled = (os.environ.get("ACTION_EXECUTION_ENABLED") or "").strip().lower() == "true"
    if not key:
        return False, "STRIPE_WRITE_API_KEY is not set"
    if not enabled:
        return False, "ACTION_EXECUTION_ENABLED is not 'true'"
    return True, ""


def _append_audit(entry: dict[str, Any], path: str | None = None) -> None:
    path = path or AUDIT_LOG_PATH  # resolved at call time so tests can repoint it
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, sort_keys=True) + "\n")


def _verify_reactivated(sub: Any) -> None:
    """Raise loudly unless the subscription now reports that it will renew."""
    if _g(sub, "cancel_at_period_end") or _g(sub, "cancel_at"):
        raise RuntimeError(
            f"Stripe accepted the modify call but subscription {_g(sub, 'id')} still reports "
            f"cancel_at_period_end={_g(sub, 'cancel_at_period_end')!r} / "
            f"cancel_at={_g(sub, 'cancel_at')!r} — verify in the dashboard."
        )


def execute_plan(plan: dict[str, Any], conversation_id: str, actor: str | None = None) -> dict[str, Any]:
    """Perform the writes described by an eligible plan. Assumes gates passed.

    `actor` tags the audit line with who triggered the write ("cli" default;
    the server rails pass "sidebar:<agent-id>" / "mcp").
    """
    released = None
    schedule = plan.get("release_schedule")
    if schedule:
        stripe.SubscriptionSchedule.release(schedule["id"])
        released = schedule["id"]

    # Live subscriptions carry BOTH fields: setting cancel_at_period_end also
    # populates a derived cancel_at. Clearing the flag is the canonical
    # un-cancel and normally clears the date with it — but a fixed-date
    # cancellation (cancel_at set, cancel_at_period_end false) is not touched by
    # the flag at all. Rather than guess which shape Stripe returns, do the
    # canonical write, then explicitly clear a cancel_at that survived it.
    updated = stripe.Subscription.modify(plan["subscription_id"], cancel_at_period_end=False)
    cleared_cancel_at = False
    if _g(updated, "cancel_at"):
        updated = stripe.Subscription.modify(plan["subscription_id"], cancel_at="")
        cleared_cancel_at = True
    _verify_reactivated(updated)

    end_ts = period_end(updated) or plan.get("period_end")
    result = {
        "action": plan["action"],
        "customer_id": plan["customer_id"],
        "subscription_id": plan["subscription_id"],
        "conversation_id": conversation_id,
        "actor": actor or "cli",
        "released_schedule": released,
        "cleared_cancel_at": cleared_cancel_at,
        "renews_on": _fmt_date(end_ts),
        "renewal_amount_display": plan.get("renewal_amount_display"),
        "executed_at": datetime.now(tz=timezone.utc).isoformat(),
    }
    _append_audit(result)
    return result


def _configure_stripe_key(apply: bool) -> None:
    """Dry runs may use the read key; --apply strictly uses the write key."""
    write_key = (os.environ.get("STRIPE_WRITE_API_KEY") or "").strip()
    read_key = (os.environ.get("STRIPE_READ_API_KEY") or "").strip()
    key = write_key if apply else (write_key or read_key)
    if not key:
        raise SystemExit("ERROR: no Stripe key available (STRIPE_WRITE_API_KEY / STRIPE_READ_API_KEY).")
    stripe.api_key = key
    stripe.max_network_retries = 2


def _fetch_customer(customer_id: str) -> Any:
    customer = stripe.Customer.retrieve(customer_id)
    if _g(customer, "deleted"):
        raise SystemExit(f"ERROR: customer {customer_id} is deleted in Stripe.")
    return customer


def _fetch_subscriptions(customer_id: str) -> list[Any]:
    subs = stripe.Subscription.list(
        customer=customer_id,
        status="all",
        limit=100,
        expand=["data.items.data.price", "data.discounts.coupon"],
    )
    return list(subs.auto_paging_iter())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Turn auto-renew back ON for one Stripe customer's subscription (un-cancel).",
    )
    parser.add_argument("customer_id", help="Stripe customer ID (cus_…) — exactly one")
    parser.add_argument("--apply", action="store_true", help="Execute the change (default: dry run)")
    parser.add_argument(
        "--conversation-id",
        help="Help Scout conversation this action serves (required with --apply)",
    )
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    args = parser.parse_args(argv)

    def emit(payload: dict[str, Any], code: int) -> int:
        if args.json:
            print(json.dumps(payload, indent=2, sort_keys=True))
        return code

    if not CUSTOMER_ID_RE.match(args.customer_id):
        print(f"ERROR: {args.customer_id!r} is not a Stripe customer ID (cus_…).", file=sys.stderr)
        return emit({"status": "error", "reason": "invalid customer id"}, 2)

    if args.apply:
        if not args.conversation_id:
            print("ERROR: --apply requires --conversation-id (every write is tied to a ticket).", file=sys.stderr)
            return emit({"status": "error", "reason": "missing conversation id"}, 2)
        ok, why = write_gates_ok()
        if not ok:
            print(f"ERROR: action execution disabled — {why}.", file=sys.stderr)
            return emit({"status": "error", "reason": why}, 2)

    _configure_stripe_key(args.apply)

    try:
        customer = _fetch_customer(args.customer_id)
        raw_subs = _fetch_subscriptions(args.customer_id)
        classified = [classify_subscription(s) for s in raw_subs]
        decision = select_target(classified)

        email = _g(customer, "email") or "no email on record"
        print(f"Customer {args.customer_id} ({email})")
        for c in classified:
            marker = {ELIGIBLE: "->", ALREADY_ON: "ok", INELIGIBLE: " x"}[c["state"]]
            print(f"  {marker} {c['subscription_id']} [{c['subscription_status']}]: {c['reason']}")

        if decision["decision"] == "noop":
            print("\nNothing to do — this subscription already renews.")
            return emit({"status": "already_on", **decision["target"]}, 0)

        if decision["decision"] == "refuse":
            print(f"\nREFUSED: {decision['reason']}", file=sys.stderr)
            return emit({"status": "refused", "reason": decision["reason"]}, 2)

        target = decision["target"]
        raw = next(s for s in raw_subs if _g(s, "id") == target["subscription_id"])
        plan = build_plan(customer, raw)

        print(f"\nPLAN: restore auto-renew on {plan['subscription_id']}")
        print(f"  renews: {plan['renews_on']} for {plan['renewal_amount_display']}")
        for note in plan["notes"]:
            print(f"  note: {note}")

        if not args.apply:
            print("\nDry run only — re-run with --apply --conversation-id <id> to execute.")
            return emit({"status": "plan", **plan}, 0)

        result = execute_plan(plan, args.conversation_id)
        print(
            f"\nAPPLIED: auto-renew restored on {result['subscription_id']} — renews "
            f"{result['renews_on']} for {result['renewal_amount_display']}."
        )
        if result["released_schedule"]:
            print(f"  released schedule {result['released_schedule']} first.")
        if result["cleared_cancel_at"]:
            print("  cleared the fixed cancel_at date.")
        return emit({"status": "applied", **result}, 0)

    except stripe.error.StripeError as e:
        msg = getattr(e, "user_message", None) or str(e)
        print(f"ERROR: Stripe API error: {msg}", file=sys.stderr)
        return emit({"status": "error", "reason": msg}, 1)


if __name__ == "__main__":
    sys.exit(main())
