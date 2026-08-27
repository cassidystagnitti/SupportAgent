"""Apply a renewal discount coupon (40% standard, 50% ceiling) to one Stripe customer's annual subscription.

The third Stripe write skill (see docs/superpowers/specs/2026-07-21-stripe-write-skills-design.md).
Takes exactly ONE Stripe customer ID, finds the single renewing ANNUAL
subscription, and attaches a percent-off coupon so it renews at the discounted
rate. This covers the coupon-application paths of policies/renewal-discount-requests.md:

  * Path 1 (pre-renewal) and Path 3 (post-renewal, applied to the next renewal)
    → `--duration once` (default): discounts the upcoming renewal invoice.
  * Forever / ongoing discount → `--forever`: discounts every future renewal.

It does NOT do the Path-2 retroactive partial refund (that rides on a charge,
not the subscription — scripts/stripe_path2_refund.py), and it is annual-only:
monthly discount requests are a different policy (policies/monthly-discount-requests.md).

Checks enforced in code (not prompt):
  * Percent is one of the sanctioned rates {40, 50}; 50 is the hard ceiling —
    "no discounts beyond 50%" (policies/renewal-discount-requests.md). Anything
    else is refused.
  * Exactly one active/trialing subscription that is actually set to renew.
    Zero or multiple → refuse (multiple live subscriptions is an escalation
    signal per policy; a subscription already set to cancel is a retention-save
    judgment call, not a plain coupon apply).
  * The subscription bills annually (interval "year"). Monthly/other → refuse,
    route to the monthly-discount policy.
  * Idempotent: a subscription that already carries the SAME rate + duration is
    a no-op success. A DIFFERENT existing discount is refused unless
    --replace-existing is passed (the sanctioned 40%→50% ladder overwrites).

Coupon resolution: the target coupon is reusable across customers, keyed by
(percent, duration). It is looked up by a deterministic id — overridable per
rate via COUPON_RENEWAL_<PCT>_<DURATION> env vars — and created on --apply when
missing (needs the write key's Coupons:Write scope). Dry-run works read-only and
reports whether the coupon exists or would be created.

Safety:
  * Dry-run by default; nothing is mutated unless --apply is passed.
  * --apply requires BOTH env gates: STRIPE_WRITE_API_KEY and
    ACTION_EXECUTION_ENABLED=true (same contract as action_executor.execute),
    plus --conversation-id so every write is tied to a Help Scout ticket.
  * Dry-run works with STRIPE_READ_API_KEY alone (never uses STRIPE_API_KEY).
  * Post-write verification: the subscription must report the coupon attached
    or the script raises loudly.
  * Every apply appends an audit line to data/stripe_action_log.jsonl.

Usage:
    # dry run — inspect and print the plan, no writes possible:
    python3 scripts/stripe_apply_coupon.py cus_ABC123
    python3 scripts/stripe_apply_coupon.py cus_ABC123 --percent 50 --forever

    # execute (both env gates must be set):
    python3 scripts/stripe_apply_coupon.py cus_ABC123 --apply --conversation-id 3394816296

    # ladder an existing 40% up to 50%:
    python3 scripts/stripe_apply_coupon.py cus_ABC123 --percent 50 --replace-existing --apply --conversation-id 3394816296

    # machine-readable output for the skill layer:
    python3 scripts/stripe_apply_coupon.py cus_ABC123 --json

Exit codes: 0 = success (applied, plan built, or already applied) · 2 = checks
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
COUPON_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")

# Sanctioned renewal-discount rates (policies/renewal-discount-requests.md):
# 40% is standard, 50% is the ceiling — "no discounts beyond 50%".
ALLOWED_PERCENTS = (40, 50)
PERCENT_CEILING = 50

# This policy is annual-only; monthly is a different policy.
ANNUAL_INTERVAL = "year"

# Statuses this script will act on. `trialing` covers real free trials and paid
# subs under a retention pause (trial_end push) — both can carry a renewal coupon.
ACTIONABLE_STATUSES = {"active", "trialing"}

ELIGIBLE = "eligible"
ALREADY_APPLIED = "already_applied"
INELIGIBLE = "ineligible"


def _g(obj: Any, key: str, default: Any = None) -> Any:
    """Read a key off a Stripe object or plain dict."""
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _money(cents: int | None, currency: str | None = "usd") -> str:
    if cents is None:
        return "unknown amount"
    cur = (currency or "usd").lower()
    if cur == "usd":
        return f"${cents / 100:.2f}"
    return f"{cents / 100:.2f} {cur.upper()}"


def _duration_label(duration: str) -> str:
    return "every renewal (forever)" if duration == "forever" else "the next renewal only"


# --- coupon resolution -------------------------------------------------------

def canonical_coupon_id(percent: int, duration: str) -> str:
    """Deterministic, reusable coupon id for a (percent, duration) pair.

    Overridable per rate via COUPON_RENEWAL_<PCT>_<DURATION> (e.g.
    COUPON_RENEWAL_40_ONCE) so an existing dashboard coupon can be reused.
    """
    override = (os.environ.get(f"COUPON_RENEWAL_{percent}_{duration.upper()}") or "").strip()
    return override or f"happier_renewal_{percent}_off_{duration}"


def coupon_matches(coupon: Any, percent: int, duration: str) -> bool:
    """True when a Stripe coupon is a percent-off of `percent` and `duration`."""
    pct = _g(coupon, "percent_off")
    return pct is not None and int(pct) == percent and _g(coupon, "duration") == duration


def get_coupon(coupon_id: str) -> Any | None:
    """Retrieve a coupon, or None when it does not exist (a signal, not a crash)."""
    try:
        return stripe.Coupon.retrieve(coupon_id)
    except stripe.error.InvalidRequestError as e:
        if getattr(e, "code", None) == "resource_missing":
            return None
        raise


def create_coupon(coupon_id: str, percent: int, duration: str) -> Any:
    """Create the canonical percent-off coupon (needs Coupons:Write)."""
    return stripe.Coupon.create(
        id=coupon_id,
        percent_off=percent,
        duration=duration,
        name=f"Renewal {percent}% off ({'forever' if duration == 'forever' else 'one renewal'})",
    )


# --- subscription helpers ----------------------------------------------------

def period_end(sub: Any) -> int | None:
    """Current period end across Stripe API versions (top-level or per-item)."""
    top = _g(sub, "current_period_end")
    if top:
        return top
    items = _g(_g(sub, "items") or {}, "data") or []
    ends = [e for e in (_g(item, "current_period_end") for item in items) if e]
    return max(ends) if ends else None


def subscription_interval(sub: Any) -> str | None:
    """The single billing interval across the sub's items, or None if mixed/missing."""
    items = _g(_g(sub, "items") or {}, "data") or []
    intervals = set()
    for item in items:
        price = _g(item, "price") or _g(item, "plan") or {}
        recurring = _g(price, "recurring")
        interval = _g(recurring, "interval") if recurring else _g(price, "interval")
        if interval:
            intervals.add(interval)
    return intervals.pop() if len(intervals) == 1 else None


def _unit_amount(sub: Any) -> tuple[int | None, str | None]:
    """The renewal unit amount + currency off the first item's price."""
    items = _g(_g(sub, "items") or {}, "data") or []
    price = _g(items[0], "price") if items else None
    return (_g(price, "unit_amount") if price else None,
            _g(price, "currency") if price else None)


def existing_discounts(sub: Any) -> list[Any]:
    """Discount objects on a subscription across SDK shapes (never bare ids)."""
    discounts = [d for d in (_g(sub, "discounts") or []) if not isinstance(d, str)]
    if discounts:
        return discounts
    single = _g(sub, "discount")
    return [single] if single else []


_COUPON_CACHE: dict[str, Any] = {}


def _resolve_coupon(coupon: Any) -> Any | None:
    """A coupon object, retrieving it when Stripe handed us a bare id string."""
    if not isinstance(coupon, str):
        return coupon
    if coupon not in _COUPON_CACHE:
        try:
            _COUPON_CACHE[coupon] = stripe.Coupon.retrieve(coupon)
        except Exception:  # noqa: BLE001 — an unreadable coupon must not break a plan
            _COUPON_CACHE[coupon] = {"id": coupon}
    return _COUPON_CACHE[coupon]


def _discount_coupon(discount: Any) -> Any | None:
    """The coupon carried by a discount, across Stripe API shapes.

    Older shapes nest the coupon object under ``coupon``. The shape Stripe
    returns now (seen live 2026-08-10 on sub_1Pr7jUEELzdEgNUIZr9W3dgY) has no
    ``coupon`` key at all — it carries ``source: {"type": "coupon", "coupon":
    "<id>"}`` with the coupon as a bare id. Reading only ``coupon`` made a
    coupon that HAD attached look missing, so ``_verify_applied`` raised after
    the write already landed (and the audit line was never written). It also
    made an existing discount undetectable, which is the mis-ladder trap the
    standing brief warns about.
    """
    if not discount:
        return None
    coupon = _g(discount, "coupon")
    if not coupon:
        source = _g(discount, "source") or {}
        if _g(source, "type") in (None, "coupon"):
            coupon = _g(source, "coupon")
    return _resolve_coupon(coupon) if coupon else None


def _describe_discount(discount: Any) -> str:
    coupon = _discount_coupon(discount)
    if coupon is None:
        return "an unknown discount"
    pct = _g(coupon, "percent_off")
    amt = _g(coupon, "amount_off")
    dur = _g(coupon, "duration") or "unknown"
    if pct:
        return f"{int(pct)}% off ({dur})"
    if amt:
        return f"{_money(amt, _g(coupon, 'currency'))} off ({dur})"
    return f"coupon {_g(coupon, 'id')}"


def _estimate_discounted(amount: int | None, percent: int) -> int | None:
    if amount is None:
        return None
    return round(amount * (1 - percent / 100))


# --- eligibility -------------------------------------------------------------

def classify_subscription(sub: Any, percent: int, duration: str) -> dict[str, Any]:
    """Apply the eligibility checks to one subscription for a coupon apply.

    Returns {"state": ELIGIBLE | ALREADY_APPLIED | INELIGIBLE, "reason": str, ...}.
    """
    sub_id = _g(sub, "id")
    status = _g(sub, "status")
    amount, currency = _unit_amount(sub)
    # NB: keyed "subscription_status" (not "status") so these dicts can merge
    # into the CLI's JSON payload, whose "status" field is the outcome marker.
    info: dict[str, Any] = {
        "subscription_id": sub_id,
        "subscription_status": status,
        "unit_amount": amount,
        "currency": currency,
    }

    if status not in ACTIONABLE_STATUSES:
        info.update(state=INELIGIBLE, reason=f"status={status}: not an active, renewing subscription.")
        return info

    if _g(sub, "cancel_at_period_end") or _g(sub, "cancel_at"):
        info.update(
            state=INELIGIBLE,
            reason=(
                "already set to cancel at period end — it will not renew, so a renewal "
                "discount is moot. If the customer wants to stay AND get the discount, that is a "
                "retention save (un-cancel + discount) — human judgment, not this script."
            ),
        )
        return info

    interval = subscription_interval(sub)
    if interval != ANNUAL_INTERVAL:
        info.update(
            state=INELIGIBLE,
            reason=(
                f"bills every {interval or 'unknown'}, not annually — renewal discounts are "
                "annual-only. Monthly requests follow policies/monthly-discount-requests.md "
                "(offer 50% annual as the counter)."
            ),
        )
        return info

    discounts = existing_discounts(sub)
    if any(coupon_matches(_discount_coupon(d), percent, duration) for d in discounts):
        info.update(
            state=ALREADY_APPLIED,
            reason=f"already carries {percent}% off ({_duration_label(duration)}) — nothing to do.",
        )
        return info

    if discounts:
        info.update(
            state=ELIGIBLE,
            reason=f"active and renewing, but already carries {_describe_discount(discounts[0])}.",
            conflicting_discount=_describe_discount(discounts[0]),
        )
        return info

    info.update(state=ELIGIBLE, reason="active, renewing, no existing discount.")
    return info


def select_target(classified: list[dict[str, Any]]) -> dict[str, Any]:
    """Pick the single actionable subscription, or explain why we refuse."""
    eligible = [c for c in classified if c["state"] == ELIGIBLE]
    already = [c for c in classified if c["state"] == ALREADY_APPLIED]

    if len(eligible) == 1:
        return {"decision": "proceed", "target": eligible[0]}
    if len(eligible) > 1:
        return {
            "decision": "refuse",
            "reason": (
                f"{len(eligible)} subscriptions are active and set to renew — refusing to guess. "
                "Multiple live subscriptions is an escalation signal (see policy); resolve in the "
                "Stripe dashboard."
            ),
            "candidates": eligible,
        }
    if already:
        return {"decision": "noop", "reason": already[0]["reason"], "target": already[0]}
    if classified:
        reasons = "; ".join(f"{c['subscription_id']}: {c['reason']}" for c in classified)
        return {"decision": "refuse", "reason": f"no subscription eligible for a renewal coupon. {reasons}"}
    return {
        "decision": "refuse",
        "reason": (
            "no Stripe subscriptions on this customer. If they claim an active plan, they may be "
            "on Apple/Google — check account context (renewal discounts need a Stripe sub, or a "
            "migration offer per policies/renewal-discount-requests.md)."
        ),
    }


# --- plan --------------------------------------------------------------------

def build_plan(
    customer: Any,
    sub: Any,
    classified: dict[str, Any],
    percent: int,
    duration: str,
    coupon_id: str,
    coupon: Any | None,
    replace_existing: bool,
) -> dict[str, Any]:
    """Assemble the human-reviewable plan for one eligible subscription."""
    amount, currency = _unit_amount(sub)
    discounted = _estimate_discounted(amount, percent)

    notes: list[str] = []
    if _g(sub, "status") == "trialing":
        notes.append("subscription is trialing — the coupon discounts the first real renewal charge.")
    conflicting = classified.get("conflicting_discount")
    if conflicting:
        notes.append(
            f"REPLACES existing discount ({conflicting}). Only sanctioned to ladder UP "
            "(e.g. 40%→50%); confirm you are not lowering a customer's better discount."
        )
    if coupon is None:
        notes.append(
            f"coupon {coupon_id!r} does not exist yet — it will be CREATED on --apply "
            "(needs the write key's Coupons:Write scope)."
        )

    return {
        "action": "apply_renewal_coupon",
        "customer_id": _g(customer, "id"),
        "customer_email": _g(customer, "email"),
        "subscription_id": _g(sub, "id"),
        "subscription_status": _g(sub, "status"),
        "percent_off": percent,
        "duration": duration,
        "duration_label": _duration_label(duration),
        "coupon_id": coupon_id,
        "coupon_exists": coupon is not None,
        "will_create_coupon": coupon is None,
        "replace_existing": bool(conflicting) and replace_existing,
        "conflicting_discount": conflicting,
        "current_amount": amount,
        "currency": currency,
        "estimated_renewal_amount": discounted,
        "price_display": (
            f"{_money(amount, currency)} -> ~{_money(discounted, currency)}"
            if amount is not None else "renewal price unknown"
        ),
        "period_end": period_end(sub),
        "notes": notes,
    }


# --- gates / audit / execution -----------------------------------------------

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


def _verify_applied(sub: Any, coupon_id: str) -> None:
    """Raise loudly unless the subscription now carries the target coupon."""
    applied = {_g(_discount_coupon(d), "id") for d in existing_discounts(sub)}
    if coupon_id not in applied:
        raise RuntimeError(
            f"Stripe accepted the modify call but subscription {_g(sub, 'id')} does not report "
            f"coupon {coupon_id!r} attached (discounts={applied or 'none'}) — verify in the dashboard."
        )


def execute_plan(plan: dict[str, Any], conversation_id: str, actor: str | None = None) -> dict[str, Any]:
    """Perform the writes described by an eligible plan. Assumes gates passed.

    Creates the coupon if it does not exist yet, attaches it to the subscription,
    verifies it stuck, then appends the audit line.
    """
    coupon_id = plan["coupon_id"]
    created_coupon = False
    if plan.get("will_create_coupon"):
        create_coupon(coupon_id, plan["percent_off"], plan["duration"])
        created_coupon = True

    updated = stripe.Subscription.modify(
        plan["subscription_id"], discounts=[{"coupon": coupon_id}]
    )
    if not existing_discounts(updated):
        # Re-read WITH the discounts expanded. An unexpanded read returns
        # ``discounts`` as bare ``di_…`` id strings, which ``existing_discounts``
        # drops — so the verification below saw "discounts=none" and raised on a
        # coupon that had in fact attached (hit live 2026-08-10). Discounts have
        # no standalone retrieve endpoint; expansion is the only way to read them.
        updated = stripe.Subscription.retrieve(
            plan["subscription_id"], expand=["discounts.coupon"]
        )
    _verify_applied(updated, coupon_id)

    result = {
        "action": plan["action"],
        "customer_id": plan["customer_id"],
        "subscription_id": plan["subscription_id"],
        "coupon_id": coupon_id,
        "percent_off": plan["percent_off"],
        "duration": plan["duration"],
        "coupon_created": created_coupon,
        "replaced_discount": plan.get("conflicting_discount") if plan.get("replace_existing") else None,
        "conversation_id": conversation_id,
        "actor": actor or "cli",
        "executed_at": datetime.now(tz=timezone.utc).isoformat(),
    }
    _append_audit(result)
    return result


# --- Stripe wiring -----------------------------------------------------------

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


# --- CLI ---------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Apply a renewal discount coupon (40%/50%) to one Stripe customer's annual subscription.",
    )
    parser.add_argument("customer_id", help="Stripe customer ID (cus_…) — exactly one")
    parser.add_argument(
        "--percent", type=int, default=40,
        help="Discount percent (policy-sanctioned: 40 standard, 50 ceiling). Default 40.",
    )
    parser.add_argument(
        "--forever", action="store_true",
        help="Recurring discount on every renewal (forever discount). Default: next renewal only.",
    )
    parser.add_argument(
        "--coupon",
        help="Explicit Stripe coupon id to use (default: the canonical id for this percent+duration)",
    )
    parser.add_argument(
        "--replace-existing", action="store_true",
        help="Overwrite a DIFFERENT existing discount (the sanctioned 40%%→50%% ladder)",
    )
    parser.add_argument("--apply", action="store_true", help="Execute the change (default: dry run)")
    parser.add_argument(
        "--conversation-id",
        help="Help Scout conversation this action serves (required with --apply)",
    )
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    args = parser.parse_args(argv)

    duration = "forever" if args.forever else "once"

    def emit(payload: dict[str, Any], code: int) -> int:
        if args.json:
            print(json.dumps(payload, indent=2, sort_keys=True))
        return code

    if not CUSTOMER_ID_RE.match(args.customer_id):
        print(f"ERROR: {args.customer_id!r} is not a Stripe customer ID (cus_…).", file=sys.stderr)
        return emit({"status": "error", "reason": "invalid customer id"}, 2)

    if args.percent not in ALLOWED_PERCENTS:
        reason = (
            f"{args.percent}% is not a sanctioned renewal-discount rate. Policy allows "
            f"{ALLOWED_PERCENTS[0]}% (standard) and up to {PERCENT_CEILING}% (ceiling) — "
            "there are no discounts beyond 50% (policies/renewal-discount-requests.md)."
        )
        print(f"ERROR: {reason}", file=sys.stderr)
        return emit({"status": "refused", "reason": reason}, 2)

    if args.coupon and not COUPON_ID_RE.match(args.coupon):
        print(f"ERROR: {args.coupon!r} is not a valid coupon id.", file=sys.stderr)
        return emit({"status": "error", "reason": "invalid coupon id"}, 2)

    if args.apply:
        if not args.conversation_id:
            print("ERROR: --apply requires --conversation-id (every write is tied to a ticket).", file=sys.stderr)
            return emit({"status": "error", "reason": "missing conversation id"}, 2)
        ok, why = write_gates_ok()
        if not ok:
            print(f"ERROR: action execution disabled — {why}.", file=sys.stderr)
            return emit({"status": "error", "reason": why}, 2)

    _configure_stripe_key(args.apply)
    coupon_id = args.coupon or canonical_coupon_id(args.percent, duration)

    try:
        customer = _fetch_customer(args.customer_id)
        raw_subs = _fetch_subscriptions(args.customer_id)
        classified = [classify_subscription(s, args.percent, duration) for s in raw_subs]
        decision = select_target(classified)

        email = _g(customer, "email") or "no email on record"
        print(f"Customer {args.customer_id} ({email})")
        for c in classified:
            marker = {ELIGIBLE: "->", ALREADY_APPLIED: "ok", INELIGIBLE: " x"}[c["state"]]
            print(f"  {marker} {c['subscription_id']} [{c['subscription_status']}]: {c['reason']}")

        if decision["decision"] == "noop":
            print("\nNothing to do — the discount is already in place.")
            return emit({"status": "already_applied", **decision["target"]}, 0)

        if decision["decision"] == "refuse":
            print(f"\nREFUSED: {decision['reason']}", file=sys.stderr)
            return emit({"status": "refused", "reason": decision["reason"]}, 2)

        target = decision["target"]
        # Existing DIFFERENT discount requires an explicit ladder/replace opt-in.
        if target.get("conflicting_discount") and not args.replace_existing:
            reason = (
                f"subscription {target['subscription_id']} already carries "
                f"{target['conflicting_discount']}. Refusing to overwrite silently — re-run with "
                "--replace-existing to ladder/replace it (only ladder UP, e.g. 40%→50%)."
            )
            print(f"\nREFUSED: {reason}", file=sys.stderr)
            return emit({"status": "refused", "reason": reason, "subscription_id": target["subscription_id"]}, 2)

        raw = next(s for s in raw_subs if _g(s, "id") == target["subscription_id"])
        coupon = get_coupon(coupon_id)
        if coupon is not None and not coupon_matches(coupon, args.percent, duration):
            reason = (
                f"coupon {coupon_id!r} exists but is not {args.percent}% off / duration={duration} "
                f"(it is {_describe_discount({'coupon': coupon})}). Refusing to apply a mismatched "
                "coupon — pass the right --coupon or fix the canonical coupon."
            )
            print(f"\nREFUSED: {reason}", file=sys.stderr)
            return emit({"status": "refused", "reason": reason}, 2)

        plan = build_plan(customer, raw, target, args.percent, duration, coupon_id, coupon, args.replace_existing)

        print(
            f"\nPLAN: apply {plan['percent_off']}% off ({plan['duration_label']}) to "
            f"{plan['subscription_id']} via coupon {plan['coupon_id']}"
        )
        print(f"  renewal price: {plan['price_display']}")
        for note in plan["notes"]:
            print(f"  note: {note}")

        if not args.apply:
            print("\nDry run only — re-run with --apply --conversation-id <id> to execute.")
            return emit({"status": "plan", **plan}, 0)

        # A Coupons:Write gap surfaces as a PermissionError from execute_plan and
        # is turned into a clean refusal by the handler below.
        result = execute_plan(plan, args.conversation_id)
        print(
            f"\nAPPLIED: {result['percent_off']}% off attached to {result['subscription_id']} "
            f"({plan['duration_label']}) via coupon {result['coupon_id']}."
        )
        if result["coupon_created"]:
            print(f"  created coupon {result['coupon_id']} first.")
        if result["replaced_discount"]:
            print(f"  replaced prior discount: {result['replaced_discount']}.")
        return emit({"status": "applied", **result}, 0)

    except stripe.error.PermissionError as e:
        msg = getattr(e, "user_message", None) or str(e)
        reason = (
            f"Stripe permission error: {msg}. Applying/creating a coupon needs the write key's "
            "Coupons:Write scope — grant it in the Stripe dashboard (see CLAUDE.md env notes)."
        )
        print(f"ERROR: {reason}", file=sys.stderr)
        return emit({"status": "error", "reason": reason}, 1)
    except stripe.error.StripeError as e:
        msg = getattr(e, "user_message", None) or str(e)
        print(f"ERROR: Stripe API error: {msg}", file=sys.stderr)
        return emit({"status": "error", "reason": msg}, 1)


if __name__ == "__main__":
    sys.exit(main())
