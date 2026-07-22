"""Apply a specific coupon to active, renewing Stripe subscriptions.

Takes one or more customer emails, finds each customer's subscriptions, and for
every subscription that is active and set to renew, applies a given coupon so the
subscription renews at a discounted price.

Safety:
  * Dry-run by default. Nothing is mutated unless you pass --apply.
  * Dry runs use STRIPE_WRITE_API_KEY (or STRIPE_READ_API_KEY as fallback — reads
    only). --apply strictly requires STRIPE_WRITE_API_KEY plus
    ACTION_EXECUTION_ENABLED=true — the same write gates as scripts/stripe_*.py.
  * Skips subscriptions that already carry the target coupon (idempotent).
  * Skips subscriptions that carry a *different* discount unless --replace-existing.

Usage:
    # interactive single-email test (prompts for email + coupon), dry-run:
    python3 apply_renewal_coupon.py

    # explicit single email, dry-run:
    python3 apply_renewal_coupon.py --email someone@example.com --coupon COUPON_ID

    # actually apply:
    python3 apply_renewal_coupon.py --email someone@example.com --coupon COUPON_ID --apply

    # batch from a file (one email per line), dry-run:
    python3 apply_renewal_coupon.py --emails-file emails.txt --coupon COUPON_ID
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import Any

import stripe
from dotenv import load_dotenv

_SUPPORT_DIR = os.path.dirname(os.path.abspath(__file__))
_ROOT_DIR = os.path.dirname(_SUPPORT_DIR)
load_dotenv(os.path.join(_SUPPORT_DIR, ".env"))
load_dotenv(os.path.join(_ROOT_DIR, ".env"))

# A subscription is eligible if its status is in this set AND it is not scheduled
# to cancel at period end (i.e. it will actually renew).
ELIGIBLE_STATUSES = {"active", "trialing"}


def _money(amount: int | None, currency: str | None) -> str:
    if amount is None:
        return "?"
    return f"${amount / 100:.2f} {(currency or 'usd').upper()}"


def _existing_discounts(sub: Any) -> list[Any]:
    """Return discount objects on a subscription, across SDK shapes."""
    discounts = getattr(sub, "discounts", None) or []
    discounts = [d for d in discounts if not isinstance(d, str)]
    if discounts:
        return discounts
    single = getattr(sub, "discount", None)
    return [single] if single else []


def _coupon_id_of(discount: Any) -> str | None:
    coupon = getattr(discount, "coupon", None)
    return getattr(coupon, "id", None) if coupon else None


def _estimate_discounted(amount: int | None, coupon: Any) -> int | None:
    if amount is None or coupon is None:
        return amount
    percent_off = getattr(coupon, "percent_off", None)
    amount_off = getattr(coupon, "amount_off", None)
    if percent_off:
        return round(amount * (1 - percent_off / 100))
    if amount_off:
        return max(0, amount - amount_off)
    return amount


def _load_coupon(coupon_id: str) -> Any | None:
    """Best-effort coupon fetch for nicer logging. Key may lack Coupons:Read."""
    try:
        return stripe.Coupon.retrieve(coupon_id)
    except stripe.error.PermissionError:
        return None
    except stripe.error.InvalidRequestError as e:
        print(f"  ! Coupon '{coupon_id}' could not be retrieved: {e.user_message or e}")
        return None
    except stripe.error.StripeError:
        return None


def _customers_for_email(email: str) -> list[Any]:
    try:
        result = stripe.Customer.list(email=email, limit=100)
    except stripe.error.StripeError as e:
        print(f"  ! Customer lookup failed: {e.user_message or e}")
        return []
    return list(result.auto_paging_iter())


def process_email(
    email: str,
    coupon_id: str,
    coupon_obj: Any | None,
    apply: bool,
    replace_existing: bool,
) -> dict[str, int]:
    """Process a single email. Returns counts for the run summary."""
    counts = {"eligible": 0, "applied": 0, "skipped": 0, "ineligible": 0}
    email = email.strip()
    if not email:
        return counts

    print(f"\n=== {email} ===")
    customers = _customers_for_email(email)
    if not customers:
        print("  No Stripe customer found.")
        return counts

    for customer in customers:
        try:
            subs = stripe.Subscription.list(
                customer=customer.id,
                status="all",
                limit=100,
                expand=["data.items.data.price"],
            )
        except stripe.error.StripeError as e:
            print(f"  ! Subscription lookup failed for {customer.id}: {e.user_message or e}")
            continue

        sub_list = list(subs.auto_paging_iter())
        if not sub_list:
            print(f"  Customer {customer.id}: no subscriptions.")
            continue

        for sub in sub_list:
            status = getattr(sub, "status", None)
            cancel_at_period_end = bool(getattr(sub, "cancel_at_period_end", False))
            items_data = sub.items.data if getattr(sub, "items", None) else []
            price = items_data[0].price if items_data else None
            unit_amount = getattr(price, "unit_amount", None) if price else None
            currency = getattr(price, "currency", None) if price else None

            renewing = status in ELIGIBLE_STATUSES and not cancel_at_period_end
            if not renewing:
                reason = "cancels at period end" if cancel_at_period_end else f"status={status}"
                print(f"  - {sub.id}: INELIGIBLE ({reason})")
                counts["ineligible"] += 1
                continue

            counts["eligible"] += 1
            existing = _existing_discounts(sub)
            existing_coupons = [c for c in (_coupon_id_of(d) for d in existing) if c]

            if coupon_id in existing_coupons:
                print(f"  - {sub.id}: SKIP — coupon '{coupon_id}' already applied.")
                counts["skipped"] += 1
                continue

            if existing_coupons and not replace_existing:
                print(
                    f"  - {sub.id}: SKIP — has a different discount {existing_coupons} "
                    f"(use --replace-existing to overwrite)."
                )
                counts["skipped"] += 1
                continue

            new_amount = _estimate_discounted(unit_amount, coupon_obj)
            price_note = _money(unit_amount, currency)
            if coupon_obj is not None and new_amount != unit_amount:
                price_note = f"{_money(unit_amount, currency)} -> ~{_money(new_amount, currency)}"

            if not apply:
                print(f"  - {sub.id}: WOULD APPLY '{coupon_id}'  ({status}, renews; {price_note})")
                continue

            try:
                stripe.Subscription.modify(sub.id, discounts=[{"coupon": coupon_id}])
                print(f"  - {sub.id}: APPLIED '{coupon_id}'  ({price_note})")
                counts["applied"] += 1
            except stripe.error.StripeError as e:
                print(f"  - {sub.id}: ERROR applying coupon: {e.user_message or e}")
                counts["skipped"] += 1

    return counts


def _collect_emails(args: argparse.Namespace) -> list[str]:
    if args.emails_file:
        with open(args.emails_file, encoding="utf-8") as fh:
            return [line.strip() for line in fh if line.strip()]
    if args.email:
        return [args.email]
    entered = input("Enter customer email: ").strip()
    return [entered] if entered else []


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--email", help="Single customer email")
    parser.add_argument("--emails-file", help="Path to a file with one email per line")
    parser.add_argument("--coupon", help="Coupon ID to apply")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually apply the coupon (default is a dry run).",
    )
    parser.add_argument(
        "--replace-existing",
        action="store_true",
        help="Overwrite an existing different discount instead of skipping.",
    )
    args = parser.parse_args()

    write_key = (os.environ.get("STRIPE_WRITE_API_KEY") or "").strip()
    read_key = (os.environ.get("STRIPE_READ_API_KEY") or "").strip()
    if args.apply:
        enabled = (os.environ.get("ACTION_EXECUTION_ENABLED") or "").strip().lower() == "true"
        if not write_key or not enabled:
            print(
                "ERROR: Stripe writes are gated — set STRIPE_WRITE_API_KEY and "
                "ACTION_EXECUTION_ENABLED=true (see CLAUDE.md).",
                file=sys.stderr,
            )
            return 1
        key = write_key
    else:
        key = write_key or read_key
        if not key:
            print(
                "ERROR: no Stripe key available (STRIPE_WRITE_API_KEY / STRIPE_READ_API_KEY).",
                file=sys.stderr,
            )
            return 1
    stripe.api_key = key

    coupon_id = (args.coupon or input("Enter coupon ID to apply: ")).strip()
    if not coupon_id:
        print("ERROR: a coupon ID is required.", file=sys.stderr)
        return 1

    emails = _collect_emails(args)
    if not emails:
        print("ERROR: no emails provided.", file=sys.stderr)
        return 1

    coupon_obj = _load_coupon(coupon_id)
    mode = "APPLY (live)" if args.apply else "DRY RUN (no changes)"
    coupon_desc = ""
    if coupon_obj is not None:
        if getattr(coupon_obj, "percent_off", None):
            coupon_desc = f" — {coupon_obj.percent_off}% off"
        elif getattr(coupon_obj, "amount_off", None):
            coupon_desc = f" — {_money(coupon_obj.amount_off, getattr(coupon_obj, 'currency', None))} off"
        dur = getattr(coupon_obj, "duration", None)
        if dur:
            coupon_desc += f", duration: {dur}"

    print(f"Mode: {mode}")
    print(f"Coupon: {coupon_id}{coupon_desc}")
    print(f"Emails: {len(emails)}")

    totals = {"eligible": 0, "applied": 0, "skipped": 0, "ineligible": 0}
    for email in emails:
        counts = process_email(
            email, coupon_id, coupon_obj, args.apply, args.replace_existing
        )
        for k in totals:
            totals[k] += counts[k]

    print("\n--- Summary ---")
    print(f"  Eligible (active & renewing): {totals['eligible']}")
    print(f"  Coupon applied:              {totals['applied']}")
    print(f"  Skipped:                     {totals['skipped']}")
    print(f"  Ineligible:                  {totals['ineligible']}")
    if not args.apply:
        print("\nDry run only — re-run with --apply to make changes.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
