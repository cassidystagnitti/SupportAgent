"""Issue a Path-2 retroactive renewal discount: a 40% (or 50%) partial refund.

The sanctioned partial-refund skill for policies/renewal-discount-requests.md
Path 2. Takes exactly ONE Stripe customer ID, targets one charge (explicit
--charge-id, or the customer's most recent succeeded charge), and refunds a
fixed percent of that charge. The customer KEEPS the subscription for the
full remaining period — this is a rate adjustment, never a pro-rated refund
and never a cancel.

This is a SEPARATE script from scripts/stripe_refund.py, which is full
refunds only and must never take an `amount` param.

Checks enforced in code (not prompt):
  * Percent is one of the sanctioned rates {40, 50}; 50 is the hard ceiling.
    Default is 40. Anything else is refused.
  * The charge exists, BELONGS to that customer, and has status "succeeded".
  * It is not disputed.
  * It has never been refunded, not even partially (any amount_refunded > 0
    → refuse, human review). Re-running Path 2 on a charge that already got
    its 40% would double-refund.
  * The charge paid for an ANNUAL subscription. Monthly → refuse (this
    policy is annual-only; route to Monthly Discount Requests).
  * The 30-day Path-2 window is computed from the charge's `created`
    timestamp. --boundary-grace extends it by exactly 1 day — the policy's
    "be generous at the boundary" rule, never more.
  * The last invoice that produced this charge must NOT already carry a
    coupon / percent-off. If it does, the renewal already went through at a
    discount and no Path-2 refund is owed (HS #3377107792).
  * Refund amount is ROUND-HALF-UP of (charge.amount * percent / 100) in
    cents. For the $99.99 annual that's $40.00 at 40%. Hard cap: the charge
    itself must be ≤ $120.00; the refund must be strictly less than the
    charge (this script never issues a full refund).

Safety:
  * Dry-run by default; nothing is mutated unless --apply is passed.
  * --apply requires BOTH env gates: STRIPE_WRITE_API_KEY and
    ACTION_EXECUTION_ENABLED=true, plus --conversation-id.
  * Dry-run works with STRIPE_READ_API_KEY alone.
  * Post-write verification: the charge must report amount_refunded equal
    to the planned refund cents, or the script raises loudly.
  * Every apply appends an audit line to data/stripe_action_log.jsonl.
  * There is NO --and-cancel-now. Path 2 keeps access.

Usage:
    # dry run:
    python3 scripts/stripe_path2_refund.py cus_ABC123
    python3 scripts/stripe_path2_refund.py cus_ABC123 --charge-id ch_XYZ789

    # 50% ladder (only when the customer pushed back on 40%):
    python3 scripts/stripe_path2_refund.py cus_ABC123 --percent 50

    # execute:
    python3 scripts/stripe_path2_refund.py cus_ABC123 --apply --conversation-id 3428334286

    # machine-readable:
    python3 scripts/stripe_path2_refund.py cus_ABC123 --json

Exit codes: 0 = success (applied or plan built) · 2 = checks refused the
action · 1 = unexpected/Stripe error.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from typing import Any

import stripe

try:
    from scripts.stripe_refund import (  # package import (pytest)
        CHARGE_ID_RE,
        CUSTOMER_ID_RE,
        REFUND_CAP_CENTS,
        _append_audit,
        _charge_invoice,
        _configure_stripe_key,
        _fetch_charge,
        _fetch_customer,
        _fmt_amount,
        _fmt_datetime,
        _g,
        _latest_succeeded_charge,
        _now_ts,
        _ref_id,
        resolve_subscription,
        subscription_interval,
        write_gates_ok,
    )
except ImportError:  # direct `python3 scripts/stripe_path2_refund.py`
    from stripe_refund import (
        CHARGE_ID_RE,
        CUSTOMER_ID_RE,
        REFUND_CAP_CENTS,
        _append_audit,
        _charge_invoice,
        _configure_stripe_key,
        _fetch_charge,
        _fetch_customer,
        _fmt_amount,
        _fmt_datetime,
        _g,
        _latest_succeeded_charge,
        _now_ts,
        _ref_id,
        resolve_subscription,
        subscription_interval,
        write_gates_ok,
    )

SANCTIONED_PERCENTS = {40, 50}
DEFAULT_PERCENT = 40
WINDOW_SECONDS = 30 * 86400
GRACE_SECONDS = 86400


def refund_cents(amount_cents: int, percent: int) -> int:
    """Round-half-up percent of amount, in cents.

    9999 * 40% → 4000 ($40.00 of $99.99). Integer cents only.
    """
    if amount_cents < 0:
        raise ValueError("amount_cents must be >= 0")
    return (amount_cents * percent + 50) // 100


def check_window(
    charge_created: int,
    boundary_grace: bool = False,
    now_ts: int | None = None,
) -> dict[str, Any]:
    now = now_ts if now_ts is not None else _now_ts()
    age = max(0, now - (charge_created or 0))
    grace = GRACE_SECONDS if boundary_grace else 0
    ok = age <= WINDOW_SECONDS + grace
    used_grace = ok and age > WINDOW_SECONDS
    if ok and used_grace:
        verdict = (
            f"past the 30-day Path-2 window but within the 1-day boundary grace "
            f"(charge age {age / 86400:.1f} days)"
        )
    elif ok:
        verdict = f"within the 30-day Path-2 retroactive window (charge age {age / 86400:.1f} days)"
    elif boundary_grace:
        verdict = (
            f"PAST the 30-day Path-2 window even with the 1-day boundary grace "
            f"(charge age {age / 86400:.1f} days)"
        )
    else:
        verdict = f"PAST the 30-day Path-2 retroactive window (charge age {age / 86400:.1f} days)"
    return {
        "ok": ok,
        "age_seconds": age,
        "limit_seconds": WINDOW_SECONDS,
        "grace_seconds": grace,
        "used_grace": used_grace,
        "verdict": verdict,
    }


def _coupon_percent(coupon: Any) -> int | None:
    if not coupon:
        return None
    pct = _g(coupon, "percent_off")
    if pct is None:
        return None
    try:
        return int(pct)
    except (TypeError, ValueError):
        return None


def invoice_discount_percent(invoice: Any) -> int | None:
    """Percent-off already applied on the invoice that produced this charge.

    Checks discount.coupon, discounts[], and the basil-era
    `total_discount_amounts` / `discounts` shapes. Any percent-off means the
    renewal already went through at a discount — Path 2 is not owed.
    """
    if invoice is None:
        return None
    percents: list[int] = []

    discount = _g(invoice, "discount")
    if discount:
        pct = _coupon_percent(_g(discount, "coupon") or discount)
        if pct is not None:
            percents.append(pct)

    for row in _g(invoice, "discounts") or []:
        if isinstance(row, str):
            continue
        pct = _coupon_percent(_g(row, "coupon") or row)
        if pct is not None:
            percents.append(pct)

    for row in _g(invoice, "total_discount_amounts") or []:
        discount = _g(row, "discount")
        if isinstance(discount, str) or discount is None:
            continue
        pct = _coupon_percent(_g(discount, "coupon") or discount)
        if pct is not None:
            percents.append(pct)

    return max(percents) if percents else None


def check_charge(charge: Any, customer_id: str) -> str | None:
    """First Path-2 refusal for this charge, or None when it is eligible."""
    charge_id = _g(charge, "id")
    currency = _g(charge, "currency")

    owner = _ref_id(_g(charge, "customer"))
    if owner != customer_id:
        return (
            f"charge {charge_id} belongs to customer {owner or 'nobody'}, not {customer_id} — "
            "refusing to refund across customers; re-check the account/charge lookup."
        )

    status = _g(charge, "status")
    if status != "succeeded":
        return (
            f"charge {charge_id} has status={status!r}, not 'succeeded' — "
            "there is no settled payment to refund."
        )

    if _g(charge, "disputed"):
        return (
            f"charge {charge_id} is DISPUTED — never refund on top of an active chargeback. "
            "Accept the dispute in the Stripe dashboard instead (policies/refund-policy.md)."
        )

    if _g(charge, "refunded"):
        return f"charge {charge_id} is already fully refunded — nothing left to refund."

    amount = _g(charge, "amount") or 0
    amount_refunded = _g(charge, "amount_refunded") or 0
    if amount_refunded > 0:
        return (
            f"charge {charge_id} already carries a partial refund "
            f"({_fmt_amount(amount_refunded, currency)} of {_fmt_amount(amount, currency)}) — "
            "human review. Do not re-run Path 2 on a charge that already got a difference refund."
        )

    if amount > REFUND_CAP_CENTS:
        return (
            f"charge {charge_id} is {_fmt_amount(amount, currency)} — over the "
            f"{_fmt_amount(REFUND_CAP_CENTS)} hard cap (annual is $99.99). "
            "Anomalous amount; human review."
        )

    return None


def build_plan(
    customer: Any,
    charge: Any,
    sub: Any,
    window: dict[str, Any],
    percent: int,
    invoice: Any,
) -> dict[str, Any]:
    amount = _g(charge, "amount") or 0
    currency = (_g(charge, "currency") or "usd").lower()
    created = _g(charge, "created")
    cents = refund_cents(amount, percent)
    notes: list[str] = []
    if window["used_grace"]:
        notes.append(
            "past the standard 30-day Path-2 window — honored ONLY under the "
            "boundary-generosity rule (--boundary-grace)."
        )
    if currency != "usd":
        notes.append(
            f"non-USD charge ({currency.upper()}) — refund {percent}% of the original amount; "
            "the customer may see a small FX discrepancy (disclose only if they raise it)."
        )
    notes.append(
        "Path 2 keeps the subscription. Do NOT cancel. The customer keeps access "
        "for the rest of the paid year at the discounted effective rate."
    )
    return {
        "action": "refund_path2",
        "customer_id": _g(customer, "id"),
        "customer_email": _g(customer, "email"),
        "charge_id": _g(charge, "id"),
        "charge_status": _g(charge, "status"),
        "amount_cents": amount,
        "refund_cents": cents,
        "percent": percent,
        "currency": currency,
        "amount_display": _fmt_amount(amount, currency),
        "refund_display": _fmt_amount(cents, currency),
        "charge_created": created,
        "charge_date": _fmt_datetime(created),
        "plan_interval": "year",
        "window_verdict": window["verdict"],
        "window_used_grace": window["used_grace"],
        "subscription_id": _g(sub, "id"),
        "subscription_status": _g(sub, "status"),
        "invoice_id": _g(invoice, "id") if invoice is not None else None,
        "notes": notes,
    }


def _verify_refund(refund: Any, plan: dict[str, Any]) -> None:
    refund_id = _g(refund, "id")
    r_status = _g(refund, "status")
    if r_status in ("failed", "canceled"):
        raise RuntimeError(
            f"Stripe returned refund {refund_id} with status={r_status!r} "
            f"(failure_reason={_g(refund, 'failure_reason')!r}) — nothing was refunded; "
            "investigate in the dashboard."
        )
    fresh = _g(refund, "charge")
    if fresh is None or isinstance(fresh, str):
        fresh = stripe.Charge.retrieve(plan["charge_id"])
    amount_refunded = _g(fresh, "amount_refunded") or 0
    if amount_refunded != plan["refund_cents"]:
        raise RuntimeError(
            f"Stripe accepted the refund call but charge {plan['charge_id']} reports "
            f"amount_refunded={amount_refunded} (expected {plan['refund_cents']}) — "
            "verify in the dashboard before doing ANYTHING else."
        )


def execute_plan(plan: dict[str, Any], conversation_id: str) -> dict[str, Any]:
    refund = stripe.Refund.create(
        charge=plan["charge_id"],
        amount=plan["refund_cents"],
        reason="requested_by_customer",
        expand=["charge"],
    )
    _verify_refund(refund, plan)
    result = {
        "action": plan["action"],
        "customer_id": plan["customer_id"],
        "charge_id": plan["charge_id"],
        "amount_cents": plan["amount_cents"],
        "refund_cents": plan["refund_cents"],
        "percent": plan["percent"],
        "currency": plan["currency"],
        "refund_id": _g(refund, "id"),
        "subscription_id": plan.get("subscription_id"),
        "conversation_id": conversation_id,
        "executed_at": datetime.now(tz=timezone.utc).isoformat(),
    }
    _append_audit(result)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Path-2 retroactive renewal discount: partial-refund a percent of one "
            "annual Stripe charge. Customer keeps the year."
        ),
    )
    parser.add_argument("customer_id", help="Stripe customer ID (cus_…) — exactly one")
    parser.add_argument(
        "--charge-id",
        help="Charge to partially refund (ch_…); default: the customer's most recent succeeded charge",
    )
    parser.add_argument(
        "--percent",
        type=int,
        default=DEFAULT_PERCENT,
        help="Percent of the charge to refund (40 default, 50 ceiling)",
    )
    parser.add_argument(
        "--boundary-grace",
        action="store_true",
        help="Extend the 30-day Path-2 window by exactly 1 day",
    )
    parser.add_argument("--apply", action="store_true", help="Execute the refund (default: dry run)")
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
    if args.charge_id and not CHARGE_ID_RE.match(args.charge_id):
        print(f"ERROR: {args.charge_id!r} is not a Stripe charge ID (ch_…).", file=sys.stderr)
        return emit({"status": "error", "reason": "invalid charge id"}, 2)
    if args.percent not in SANCTIONED_PERCENTS:
        reason = (
            f"percent {args.percent} is not sanctioned — Path 2 is 40% (default) or 50% "
            "(ladder only). No discounts beyond 50%."
        )
        print(f"ERROR: {reason}", file=sys.stderr)
        return emit({"status": "error", "reason": reason}, 2)

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
        email = _g(customer, "email") or "no email on record"
        print(f"Customer {args.customer_id} ({email})")

        if args.charge_id:
            charge = _fetch_charge(args.charge_id)
            if charge is None:
                reason = f"charge {args.charge_id} does not exist on this Stripe account."
                print(f"\nREFUSED: {reason}", file=sys.stderr)
                return emit({"status": "refused", "reason": reason}, 2)
        else:
            charge = _latest_succeeded_charge(args.customer_id)
            if charge is None:
                reason = (
                    f"no succeeded charges on customer {args.customer_id}. If they claim a charge, "
                    "it may be on Apple/Google or another Stripe customer — re-run the account/charge "
                    "hunt before replying."
                )
                print(f"\nREFUSED: {reason}", file=sys.stderr)
                return emit({"status": "refused", "reason": reason}, 2)

        charge_id = _g(charge, "id")
        print(
            f"  charge {charge_id}: {_fmt_amount(_g(charge, 'amount'), _g(charge, 'currency'))} "
            f"on {_fmt_datetime(_g(charge, 'created'))} [{_g(charge, 'status')}]"
        )

        refusal = check_charge(charge, args.customer_id)
        if refusal:
            print(f"\nREFUSED: {refusal}", file=sys.stderr)
            return emit({"status": "refused", "reason": refusal, "charge_id": charge_id}, 2)

        sub, why_not = resolve_subscription(charge)
        if sub is None:
            print(f"\nREFUSED: {why_not}", file=sys.stderr)
            return emit({"status": "refused", "reason": why_not, "charge_id": charge_id}, 2)

        interval = subscription_interval(sub)
        if interval != "year":
            reason = (
                f"subscription {_g(sub, 'id')} bills every {interval!r} — Path 2 is annual-only. "
                "Monthly discount requests are a different policy."
            )
            print(f"\nREFUSED: {reason}", file=sys.stderr)
            return emit({"status": "refused", "reason": reason, "charge_id": charge_id}, 2)

        invoice = _charge_invoice(charge)
        if invoice is not None and isinstance(invoice, str):
            invoice = stripe.Invoice.retrieve(invoice, expand=["discount.coupon", "discounts"])
        already_pct = invoice_discount_percent(invoice)
        if already_pct is not None:
            reason = (
                f"invoice {_g(invoice, 'id')} already carried a {already_pct}% off coupon — "
                "the renewal already went through at a discount. No Path-2 refund is owed."
            )
            print(f"\nREFUSED: {reason}", file=sys.stderr)
            return emit({"status": "refused", "reason": reason, "charge_id": charge_id}, 2)

        window = check_window(_g(charge, "created"), args.boundary_grace)
        if not window["ok"]:
            reason = (
                f"{window['verdict']}. No Path-2 partial refund — offer Path 3 "
                "(40% off the NEXT renewal) instead (policies/renewal-discount-requests.md)."
            )
            print(f"\nREFUSED: {reason}", file=sys.stderr)
            return emit({"status": "refused", "reason": reason, "charge_id": charge_id}, 2)

        plan = build_plan(customer, charge, sub, window, args.percent, invoice)
        if plan["refund_cents"] <= 0:
            reason = f"computed refund is {plan['refund_cents']} cents — nothing to refund."
            print(f"\nREFUSED: {reason}", file=sys.stderr)
            return emit({"status": "refused", "reason": reason, "charge_id": charge_id}, 2)
        if plan["refund_cents"] >= plan["amount_cents"]:
            reason = (
                f"computed refund {plan['refund_display']} is not strictly less than the charge "
                f"{plan['amount_display']} — Path 2 never issues a full refund. Human review."
            )
            print(f"\nREFUSED: {reason}", file=sys.stderr)
            return emit({"status": "refused", "reason": reason, "charge_id": charge_id}, 2)

        print(
            f"\nPLAN: Path-2 {plan['percent']}% partial refund of {plan['charge_id']} — "
            f"{plan['refund_display']} of {plan['amount_display']} back to the customer"
        )
        print(f"  charge date {plan['charge_date']}")
        print(f"  window: {plan['window_verdict']}")
        print(
            f"  subscription {plan['subscription_id']} [{plan['subscription_status']}] — "
            "KEPT (access continues for the rest of the year)"
        )
        for note in plan["notes"]:
            print(f"  note: {note}")

        if not args.apply:
            print("\nDry run only — re-run with --apply --conversation-id <id> to execute.")
            return emit({"status": "plan", **plan}, 0)

        result = execute_plan(plan, args.conversation_id)
        print(
            f"\nAPPLIED: refund {result['refund_id']} issued — {plan['refund_display']} "
            f"({plan['percent']}% of {plan['amount_display']}) returned on {plan['charge_id']}. "
            "Subscription kept."
        )
        return emit({"status": "applied", **result}, 0)

    except stripe.error.StripeError as e:
        msg = getattr(e, "user_message", None) or str(e)
        print(f"ERROR: Stripe API error: {msg}", file=sys.stderr)
        return emit({"status": "error", "reason": msg}, 1)


if __name__ == "__main__":
    sys.exit(main())
