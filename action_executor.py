"""Prepared-action scaffold for Stripe-affecting support actions.

Bert cannot execute Stripe writes yet — the write-capable API key is pending
approval. Until then, this module:

  1. Builds a structured `ActionPlan` describing what *would* be done
     (`prepare_coupon`, `prepare_cancellation`).
  2. Renders those plans into an "Actions needed" HTML block for the Help
     Scout internal note (`format_actions_note`), so a human can execute
     the action manually.
  3. Gates real execution behind two env vars (`execute`). Even when both
     gates pass, no Stripe call is implemented yet — `execute` raises
     `NotImplementedError` past the gate. Real Stripe write calls land in a
     later task.

Uses the stripe_context.py dict shape: `subscription_id`, `stripe_customer_id`,
`plan_amount`, etc. (see stripe_context.fetch_stripe_context).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ActionPlan:
    """A prepared-but-not-yet-executed action against an external system."""

    kind: str
    params: dict[str, Any] = field(default_factory=dict)
    human_summary: str = ""


def prepare_coupon(stripe_ctx: dict[str, Any] | None, percent: int) -> ActionPlan:
    """Build a plan to apply a percent-off coupon to the customer's subscription.

    `stripe_ctx` is the dict shape returned by `stripe_context.fetch_stripe_context`
    (keys: `subscription_id`, `stripe_customer_id`, ...). Either may be absent;
    params fall back to None so the plan is still inspectable/renderable.
    """
    ctx = stripe_ctx or {}
    subscription_id = ctx.get("subscription_id")
    customer_id = ctx.get("stripe_customer_id")

    summary = f"Apply a {percent}% coupon"
    if subscription_id:
        summary += f" to subscription {subscription_id}"
    if customer_id:
        summary += f" (customer {customer_id})"

    return ActionPlan(
        kind="apply_coupon",
        params={
            "subscription_id": subscription_id,
            "customer_id": customer_id,
            "percent": percent,
        },
        human_summary=summary,
    )


def prepare_cancellation(stripe_ctx: dict[str, Any] | None, at_period_end: bool = True) -> ActionPlan:
    """Build a plan to cancel the customer's subscription.

    `stripe_ctx` is the dict shape returned by `stripe_context.fetch_stripe_context`
    (key: `subscription_id`). May be absent; param falls back to None.
    """
    ctx = stripe_ctx or {}
    subscription_id = ctx.get("subscription_id")

    if at_period_end:
        summary = "Cancel subscription at end of current billing period"
    else:
        summary = "Cancel subscription immediately"
    if subscription_id:
        summary += f" ({subscription_id})"

    return ActionPlan(
        kind="cancel_subscription",
        params={
            "subscription_id": subscription_id,
            "at_period_end": at_period_end,
        },
        human_summary=summary,
    )


def execute(plan: ActionPlan) -> dict[str, Any]:
    """Execute a prepared action plan.

    Gated behind two env vars — BOTH must be set before any execution is
    attempted:
      - STRIPE_WRITE_API_KEY: the write-capable Stripe key (pending approval;
        not yet issued as of this task).
      - ACTION_EXECUTION_ENABLED=true: explicit opt-in flag.

    Raises RuntimeError if either gate is not satisfied. Raises
    NotImplementedError past the gate — no real Stripe write calls exist yet.
    """
    write_key = (os.environ.get("STRIPE_WRITE_API_KEY") or "").strip()
    enabled = (os.environ.get("ACTION_EXECUTION_ENABLED") or "").strip().lower() == "true"

    if not write_key or not enabled:
        raise RuntimeError("action execution disabled")

    raise NotImplementedError(f"execute() has no implementation yet for action kind={plan.kind!r}")


def _html_escape(s: str) -> str:
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def format_actions_note(parsed: dict[str, Any], stripe_ctx: dict[str, Any] | None) -> str:
    """Render the "Actions needed" HTML block for the Help Scout internal note.

    Returns an empty string when `parsed.needs_action` is falsy. Otherwise
    returns `<p><strong>...Actions needed</strong></p><ul>...</ul>` built
    from `action_description` + `action_system`, plus subscription id/amount
    from `stripe_ctx` when available.
    """
    if not parsed.get("needs_action"):
        return ""

    action_description = (parsed.get("action_description") or "").strip() or "Unspecified — see reasoning"
    action_system = (parsed.get("action_system") or "").strip() or "unknown"

    items = [
        f"<li><strong>Action:</strong> {_html_escape(action_description)}</li>",
        f"<li><strong>System:</strong> {_html_escape(action_system)}</li>",
    ]

    ctx = stripe_ctx or {}
    subscription_id = ctx.get("subscription_id")
    if subscription_id:
        items.append(f"<li><strong>Subscription ID:</strong> {_html_escape(str(subscription_id))}</li>")

    customer_id = ctx.get("stripe_customer_id")
    if customer_id:
        items.append(f"<li><strong>Stripe Customer ID:</strong> {_html_escape(str(customer_id))}</li>")

    amount = ctx.get("plan_amount")
    if amount is not None:
        currency = (ctx.get("plan_currency") or "usd").upper()
        items.append(f"<li><strong>Plan Amount:</strong> ${amount / 100:.2f} {currency}</li>")

    return (
        "<p><strong>\U0001f527 Actions needed</strong></p>"
        f"<ul>{''.join(items)}</ul>"
    )
