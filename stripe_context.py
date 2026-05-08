"""Stripe read-only enrichment for Stripe-platform subscribers.

Uses STRIPE_READ_API_KEY. Safe to call without key — returns None.

Not run by this module for non-Stripe platforms; orchestrator gates on account blob.
"""

from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timezone
from typing import Any

import stripe
from dotenv import load_dotenv

_SUPPORT_DIR = os.path.dirname(os.path.abspath(__file__))
_ROOT_DIR = os.path.dirname(_SUPPORT_DIR)
load_dotenv(os.path.join(_SUPPORT_DIR, ".env"))
load_dotenv(os.path.join(_ROOT_DIR, ".env"))

log = logging.getLogger(__name__)


def _format_timestamp(ts: int | None) -> str:
    if ts is None:
        return ""
    try:
        dt = datetime.fromtimestamp(ts, tz=timezone.utc)
        return dt.strftime("%Y-%m-%d %H:%M UTC")
    except (OSError, ValueError, OverflowError):
        return str(ts)


def _stripe_retry(callable_fn, max_attempts: int = 2):
    last_exc: Exception | None = None
    for attempt in range(max_attempts):
        try:
            return callable_fn()
        except stripe.error.APIConnectionError as e:
            last_exc = e
            if attempt + 1 < max_attempts:
                time.sleep(0.75)
        except stripe.error.APIError as e:
            last_exc = e
            code = getattr(e, "http_status", None)
            if code is not None and 500 <= code < 600 and attempt + 1 < max_attempts:
                time.sleep(0.75)
                continue
            raise
    if last_exc:
        raise last_exc
    raise RuntimeError("stripe retry exhausted")


def fetch_stripe_context(customer_email: str) -> dict[str, Any] | None:
    """
    Look up Stripe customer by email and return subscription + pricing context.

    Returns None if no API key, customer not found, or no subscription data.
    """
    key = (os.environ.get("STRIPE_READ_API_KEY") or "").strip()
    if not key:
        log.warning("STRIPE_READ_API_KEY not set — skipping Stripe enrichment")
        return None
    if not (customer_email or "").strip():
        return None

    stripe.api_key = key

    def list_customers():
        return stripe.Customer.list(email=customer_email.strip(), limit=1)

    try:
        customers = _stripe_retry(list_customers)
    except stripe.error.StripeError as e:
        log.exception("Stripe Customer.list failed: %s", e)
        return None

    if not customers.data:
        return None
    customer = customers.data[0]

    def list_subs(**kwargs):
        return stripe.Subscription.list(customer=customer.id, limit=5, **kwargs)

    try:
        subscriptions = _stripe_retry(
            lambda: list_subs(status="active", expand=["data.items.data.price", "data.discount"])
        )
    except stripe.error.StripeError as e:
        log.exception("Stripe Subscription.list (active) failed: %s", e)
        return None

    if not subscriptions.data:
        try:
            subscriptions = _stripe_retry(
                lambda: list_subs(expand=["data.items.data.price", "data.discount"])
            )
        except stripe.error.StripeError as e:
            log.exception("Stripe Subscription.list failed: %s", e)
            return None

    if not subscriptions.data:
        return None

    sub = subscriptions.data[0]
    items = getattr(sub, "items", None)
    items_data = items.data if items else []
    if not items_data:
        return None
    price = items_data[0].price

    unit_amount = getattr(price, "unit_amount", None)
    recurring = getattr(price, "recurring", None)
    interval = getattr(recurring, "interval", None) if recurring else None

    ctx: dict[str, Any] = {
        "stripe_customer_id": customer.id,
        "subscription_id": sub.id,
        "subscription_status": getattr(sub, "status", None),
        "current_period_start": getattr(sub, "current_period_start", None),
        "current_period_end": getattr(sub, "current_period_end", None),
        "plan_interval": interval or "",
        "plan_amount": unit_amount,
        "plan_currency": getattr(price, "currency", "") or "",
        "plan_product_id": getattr(price, "product", None),
        "discount": None,
        "upcoming_invoice_amount": None,
    }

    discount_obj = getattr(sub, "discount", None)
    if discount_obj is None:
        discounts = getattr(sub, "discounts", None) or []
        if discounts:
            discount_obj = discounts[0] if not isinstance(discounts[0], str) else None

    if discount_obj:
        coupon = getattr(discount_obj, "coupon", None)
        if coupon:
            ctx["discount"] = {
                "coupon_id": getattr(coupon, "id", None),
                "coupon_name": getattr(coupon, "name", None) or "",
                "percent_off": getattr(coupon, "percent_off", None),
                "amount_off": getattr(coupon, "amount_off", None),
                "duration": getattr(coupon, "duration", None),
                "duration_in_months": getattr(coupon, "duration_in_months", None),
            }

    # Effective price = what they actually pay per period after coupon applied
    effective = unit_amount
    d = ctx.get("discount")
    if effective is not None and d:
        if d.get("percent_off"):
            effective = round(effective * (1 - d["percent_off"] / 100))
        elif d.get("amount_off"):
            effective = max(0, effective - d["amount_off"])
    ctx["effective_plan_amount"] = effective

    def fetch_next_invoice_preview():
        """Upcoming invoice API removed in newer Stripe SDKs; use create_preview with subscription."""
        inv = stripe.Invoice
        if hasattr(inv, "create_preview"):
            return inv.create_preview(customer=customer.id, subscription=sub.id)
        if hasattr(inv, "upcoming"):
            return inv.upcoming(customer=customer.id)
        return None

    try:
        preview = _stripe_retry(fetch_next_invoice_preview)
        if preview is not None:
            ctx["upcoming_invoice_amount"] = getattr(preview, "amount_due", None)
    except stripe.error.InvalidRequestError:
        pass
    except stripe.error.StripeError as e:
        log.warning("Stripe invoice preview/upcoming failed (non-fatal): %s", e)

    return ctx


def format_stripe_context(ctx: dict[str, Any] | None) -> str:
    """Human-readable block for Claude prompts and internal notes."""
    if ctx is None:
        return (
            "Stripe Data: Not available "
            "(customer not found in Stripe or not a Stripe subscriber)"
        )

    amt = ctx.get("plan_amount")
    effective = ctx.get("effective_plan_amount")
    currency = (ctx.get("plan_currency") or "usd").upper()
    interval = ctx.get("plan_interval") or "?"

    if amt is not None:
        plan_line = f"{interval}ly at ${amt / 100:.2f} {currency} (base/full price)"
    else:
        plan_line = "unknown plan"

    lines = [
        "Stripe Subscription Data:",
        f"  Stripe Customer ID: {ctx.get('stripe_customer_id')}",
        f"  Subscription ID: {ctx.get('subscription_id')}",
        f"  Status: {ctx.get('subscription_status')}",
        f"  Base Plan: {plan_line}",
        f"  Current Period: {_format_timestamp(ctx.get('current_period_start'))} to "
        f"{_format_timestamp(ctx.get('current_period_end'))}",
    ]

    d = ctx.get("discount")
    if d:
        if d.get("percent_off"):
            discount_desc = f"{d['percent_off']}% off"
        elif d.get("amount_off"):
            discount_desc = f"${d['amount_off'] / 100:.2f} off"
        else:
            discount_desc = "discount active"
        duration_desc = d.get("duration") or ""
        if duration_desc == "repeating" and d.get("duration_in_months"):
            duration_desc = f"repeating ({d['duration_in_months']} months)"
        lines.append(
            f"  Active Coupon: {d.get('coupon_id')} — {discount_desc}, duration: {duration_desc}"
        )
        if d.get("coupon_name"):
            lines.append(f"  Coupon Name: {d['coupon_name']}")
    else:
        lines.append("  Active Coupon: None")

    if effective is not None and amt is not None:
        if effective == amt:
            lines.append(f"  Effective Price (what they pay): ${effective / 100:.2f} {currency}/{interval} — no discount applied")
        else:
            lines.append(f"  Effective Price (what they pay): ${effective / 100:.2f} {currency}/{interval} — discounted from ${amt / 100:.2f}")
    elif effective is not None:
        lines.append(f"  Effective Price (what they pay): ${effective / 100:.2f} {currency}/{interval}")

    upcoming = ctx.get("upcoming_invoice_amount")
    if upcoming is not None:
        lines.append(f"  Next Renewal Amount (from Stripe): ${upcoming / 100:.2f} {currency} — use this as their renewal price")

    return "\n".join(lines)
