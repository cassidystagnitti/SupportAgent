"""Turn off auto-renew for one Stripe customer's subscription (cancel at period end).

The first Stripe write skill (see docs/superpowers/specs/2026-07-21-stripe-write-skills-design.md).
Takes exactly ONE Stripe customer ID, finds the single renewing subscription, and
schedules it to cancel at period end. Never terminates access immediately.

Checks enforced in code (not prompt):
  * The subscription is active (or trialing — real trials AND the self-serve
    platform's retention "pause", which is a trial_end push; see
    changecollective.com SubscriptionManagement::Cancellation::Extension).
  * It is NOT in a delinquent status (past_due / unpaid / incomplete / paused):
    per policies/cancellation-policy.md those take the immediate-cancel path,
    which this script deliberately does not implement.
  * It is currently set to renew (cancel_at_period_end false, no cancel_at).
    Already-off subscriptions are an idempotent no-op success — mirroring the
    self-serve platform's short-circuit (changecollective.com V2::BillingController).
  * Exactly one subscription qualifies. Zero or multiple → refuse with reasons
    (multiple subscriptions is an escalation signal per policy).

Subscription schedules: the customer-facing platform cancels through Stripe's
Billing Portal, whose plan-change flows put subscriptions under a
SubscriptionSchedule. Setting cancel_at_period_end on a schedule-managed
subscription is rejected/overridden by Stripe, so when a schedule in status
not_started/active is attached we RELEASE it first (keeps the subscription,
detaches the schedule, discards pending scheduled changes — correct when the
customer wants to stop renewing; the dry-run plan calls this out loudly).

Safety:
  * Dry-run by default; nothing is mutated unless --apply is passed.
  * --apply requires BOTH env gates: STRIPE_WRITE_API_KEY and
    ACTION_EXECUTION_ENABLED=true (same contract as action_executor.execute),
    plus --conversation-id so every write is tied to a Help Scout ticket.
  * Dry-run works with STRIPE_READ_API_KEY alone (never uses STRIPE_API_KEY).
  * Every apply appends an audit line to data/stripe_action_log.jsonl.

Usage:
    # dry run — inspect and print the plan, no writes possible:
    python3 scripts/stripe_cancel_subscription.py cus_ABC123

    # execute (both env gates must be set):
    python3 scripts/stripe_cancel_subscription.py cus_ABC123 --apply --conversation-id 3390692208

    # machine-readable output for the skill layer:
    python3 scripts/stripe_cancel_subscription.py cus_ABC123 --json

Exit codes: 0 = success (applied, plan built, or already off) · 2 = checks
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

# Statuses this script will act on. `trialing` is included on purpose: it covers
# both real free trials (policy: support can cancel) and paid subscriptions under
# a retention pause/extension (trial_end push with metadata.retention_extension).
ACTIONABLE_STATUSES = {"active", "trialing"}

# Delinquent statuses: policy routes these to immediate cancellation, a
# different (not yet built) script. Refuse here rather than silently doing the
# wrong kind of cancel.
DUNNING_STATUSES = {"past_due", "unpaid"}

ELIGIBLE = "eligible"
ALREADY_OFF = "already_off"
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


def period_end(sub: Any) -> int | None:
    """Current period end across Stripe API versions.

    Older API versions expose `current_period_end` on the subscription; from
    2025-03-31.basil onward it lives on each subscription item. The SDK in use
    pins a post-basil version, so the item-level field is the primary source.
    """
    top = _g(sub, "current_period_end")
    if top:
        return top
    items = _g(_g(sub, "items") or {}, "data") or []
    ends = [e for e in (_g(item, "current_period_end") for item in items) if e]
    return max(ends) if ends else None


def _schedule_info(sub: Any) -> dict[str, Any] | None:
    """Normalize the sub's schedule (expanded object or bare id) to a dict."""
    schedule = _g(sub, "schedule")
    if not schedule:
        return None
    if isinstance(schedule, str):
        return {"id": schedule, "status": None}
    return {"id": _g(schedule, "id"), "status": _g(schedule, "status")}


def classify_subscription(sub: Any) -> dict[str, Any]:
    """Apply the eligibility checks to one subscription.

    Returns {"state": ELIGIBLE | ALREADY_OFF | INELIGIBLE, "reason": str, ...}.
    """
    sub_id = _g(sub, "id")
    status = _g(sub, "status")
    end_ts = period_end(sub)
    # NB: keyed "subscription_status" (not "status") so these dicts can merge
    # into the CLI's JSON payload, whose "status" field is the outcome marker.
    info: dict[str, Any] = {
        "subscription_id": sub_id,
        "subscription_status": status,
        "period_end": end_ts,
        "period_end_display": _fmt_date(end_ts),
    }

    if status in DUNNING_STATUSES:
        info.update(
            state=INELIGIBLE,
            reason=(
                f"status={status}: in the failed-payment/dunning flow. Policy is to cancel "
                "IMMEDIATELY (no paid period left to preserve) — that path is not this "
                "script; handle in the Stripe dashboard per policies/cancellation-policy.md."
            ),
        )
        return info

    if status not in ACTIONABLE_STATUSES:
        info.update(state=INELIGIBLE, reason=f"status={status}: not an active, renewing subscription.")
        return info

    if _g(sub, "pause_collection"):
        info.update(
            state=INELIGIBLE,
            reason="payment collection is paused (pause_collection set) — resolve the pause "
            "in the dashboard before changing renewal state.",
        )
        return info

    cancel_at = _g(sub, "cancel_at")
    if _g(sub, "cancel_at_period_end") or cancel_at:
        when = _fmt_date(cancel_at or end_ts)
        info.update(
            state=ALREADY_OFF,
            reason=f"auto-renew is already off — access continues through {when}.",
        )
        return info

    info.update(state=ELIGIBLE, reason="active and set to renew.")
    return info


def select_target(classified: list[dict[str, Any]]) -> dict[str, Any]:
    """Pick the single actionable subscription, or explain why we refuse."""
    eligible = [c for c in classified if c["state"] == ELIGIBLE]
    already_off = [c for c in classified if c["state"] == ALREADY_OFF]

    if len(eligible) == 1:
        return {"decision": "proceed", "target": eligible[0]}
    if len(eligible) > 1:
        return {
            "decision": "refuse",
            "reason": (
                f"{len(eligible)} subscriptions are active and set to renew — refusing to "
                "guess. Multiple live subscriptions is an escalation signal (see policy); "
                "resolve in the Stripe dashboard."
            ),
            "candidates": eligible,
        }
    if already_off:
        return {"decision": "noop", "reason": already_off[0]["reason"], "target": already_off[0]}
    if classified:
        reasons = "; ".join(f"{c['subscription_id']}: {c['reason']}" for c in classified)
        return {"decision": "refuse", "reason": f"no cancellable subscription. {reasons}"}
    return {
        "decision": "refuse",
        "reason": (
            "no Stripe subscriptions on this customer. If they claim an active plan, "
            "they may be on Apple/Google — check account context before replying."
        ),
    }


def build_plan(customer: Any, sub: Any) -> dict[str, Any]:
    """Assemble the human-reviewable plan for one eligible subscription."""
    status = _g(sub, "status")
    metadata = _g(sub, "metadata") or {}
    discount = _g(sub, "discount") or (_g(sub, "discounts") or [None])[0]
    schedule = _schedule_info(sub)
    end_ts = period_end(sub)

    notes: list[str] = []
    if status == "trialing":
        if _g(metadata, "retention_extension"):
            notes.append(
                "status=trialing via a retention pause/extension (paid sub, trial_end push) — "
                "cancelling stops the renewal at the extended date."
            )
        else:
            notes.append("this is a FREE TRIAL — cancelling prevents conversion; no charge occurs.")
    if discount is None:
        notes.append(
            "no active discount — renewing at full price, so the 40% retention offer applies "
            "in the reply per policies/cancellation-policy.md."
        )
    if schedule:
        notes.append(
            f"managed by subscription schedule {schedule['id']} "
            f"(status={schedule['status'] or 'unknown'}) — the schedule will be RELEASED first; "
            "any pending scheduled changes (e.g. a queued plan switch) are discarded."
        )

    return {
        "action": "cancel_at_period_end",
        "customer_id": _g(customer, "id"),
        "customer_email": _g(customer, "email"),
        "subscription_id": _g(sub, "id"),
        "subscription_status": status,
        "period_end": end_ts,
        "access_continues_through": _fmt_date(end_ts),
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


def execute_plan(plan: dict[str, Any], conversation_id: str) -> dict[str, Any]:
    """Perform the writes described by an eligible plan. Assumes gates passed."""
    released = None
    schedule = plan.get("release_schedule")
    if schedule:
        stripe.SubscriptionSchedule.release(schedule["id"])
        released = schedule["id"]

    updated = stripe.Subscription.modify(plan["subscription_id"], cancel_at_period_end=True)
    if not _g(updated, "cancel_at_period_end"):
        raise RuntimeError(
            f"Stripe accepted the modify call but {plan['subscription_id']} still reports "
            "cancel_at_period_end=false — verify in the dashboard."
        )

    end_ts = period_end(updated) or plan.get("period_end")
    result = {
        "action": plan["action"],
        "customer_id": plan["customer_id"],
        "subscription_id": plan["subscription_id"],
        "conversation_id": conversation_id,
        "released_schedule": released,
        "access_continues_through": _fmt_date(end_ts),
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
    # Only `schedule` needs expanding; items (with inline prices) come embedded,
    # so the key needs no Products/Prices access — Customers:Read +
    # Subscriptions:Write is the complete permission set for this script.
    subs = stripe.Subscription.list(
        customer=customer_id,
        status="all",
        limit=100,
        expand=["data.schedule"],
    )
    return list(subs.auto_paging_iter())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Turn off auto-renew (cancel at period end) for one Stripe customer.",
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
            marker = {ELIGIBLE: "->", ALREADY_OFF: "ok", INELIGIBLE: " x"}[c["state"]]
            print(f"  {marker} {c['subscription_id']} [{c['subscription_status']}]: {c['reason']}")

        if decision["decision"] == "noop":
            print("\nNothing to do — customer is all set.")
            return emit({"status": "already_off", **decision["target"]}, 0)

        if decision["decision"] == "refuse":
            print(f"\nREFUSED: {decision['reason']}", file=sys.stderr)
            return emit({"status": "refused", "reason": decision["reason"]}, 2)

        # Exactly one eligible subscription — build the plan against the raw object.
        target_id = decision["target"]["subscription_id"]
        raw = next(s for s in raw_subs if _g(s, "id") == target_id)
        plan = build_plan(customer, raw)

        print(f"\nPLAN: turn off auto-renew on {plan['subscription_id']}")
        print(f"  access continues through {plan['access_continues_through']} (period end)")
        for note in plan["notes"]:
            print(f"  note: {note}")

        if not args.apply:
            print("\nDry run only — re-run with --apply --conversation-id <id> to execute.")
            return emit({"status": "plan", **plan}, 0)

        result = execute_plan(plan, args.conversation_id)
        print(
            f"\nAPPLIED: {result['subscription_id']} will not renew — "
            f"access continues through {result['access_continues_through']}."
        )
        if result["released_schedule"]:
            print(f"  released subscription schedule {result['released_schedule']} first.")
        return emit({"status": "applied", **result}, 0)

    except stripe.error.StripeError as e:
        msg = getattr(e, "user_message", None) or str(e)
        print(f"ERROR: Stripe API error: {msg}", file=sys.stderr)
        return emit({"status": "error", "reason": msg}, 1)


if __name__ == "__main__":
    sys.exit(main())
