"""Fully refund one Stripe charge for one customer, window-enforced (optionally ending access now).

The second Stripe write skill (script #3 in
docs/superpowers/specs/2026-07-21-stripe-write-skills-design.md). Takes exactly
ONE Stripe customer ID, targets one charge (explicit --charge-id, or the
customer's most recent succeeded charge), and refunds it IN FULL. The refund
window and every eligibility rule from policies/refund-policy.md is enforced
in code — never trusted from model-supplied dates or amounts.

Checks enforced in code (not prompt):
  * The charge exists, BELONGS to that customer, and has status "succeeded".
  * It is not disputed (active chargeback → never refund on top of it; accept
    the dispute in the Stripe dashboard per policies/refund-policy.md).
  * It has never been refunded, not even partially (any amount_refunded > 0 →
    refuse, human review). The only sanctioned partial refund is the Path-2
    retroactive 40% discount (policies/renewal-discount-requests.md) — a
    SEPARATE future script; this one is full refunds only.
  * The refund window is computed from the charge's `created` timestamp
    to when the customer emailed support (first customer thread on the
    Help Scout conversation), against the plan interval of the subscription
    the charge paid for: 30 days (annual) / 24 hours (monthly). Running the
    script later does not burn the window. --boundary-grace extends it by
    exactly 1 day / 1 hour — the policy's "be generous at the boundary" rule,
    never more. If the interval cannot be determined (one-off/gift charge,
    no linked subscription), refuse — human review. --conversation-id is
    required so the email timestamp is read from Help Scout, not guessed.
  * Full amount only: Refund.create is called WITHOUT an `amount` param, so
    Stripe refunds the charge in full. Hard cap: any charge over $120.00
    (12000 cents) is refused as anomalous (annual is $99.99).

--and-cancel-now (the "Finish Now" combo): after a successful refund, end
access immediately. Refunded customers don't keep access, so a subscription
that is merely set to cancel_at_period_end is still canceled NOW; only a
fully-canceled subscription is a no-op. Schedule-managed subscriptions get
their schedule RELEASED first (Stripe refuses direct cancellation while a
schedule is attached — same lesson as the cancel-at-period-end script).
Refund-first ordering: if the refund fails, nothing is canceled. If the
refund succeeds and the cancel leg then fails, the audit line still records
the refund and the script raises loudly — never re-run --apply after that;
the money already moved.

Charge → subscription resolution works across Stripe API versions: the
charge's `invoice` field when present (pre-basil shapes), else the
InvoicePayment mapping via the charge's payment_intent (basil/dahlia, where
Charge carries no invoice field), then invoice → subscription (top-level
`subscription` or `parent.subscription_details.subscription`).

Safety:
  * Dry-run by default; nothing is mutated unless --apply is passed.
  * --apply requires BOTH env gates: STRIPE_WRITE_API_KEY and
    ACTION_EXECUTION_ENABLED=true (same contract as action_executor.execute),
    plus --conversation-id so every write is tied to a Help Scout ticket.
  * Dry-run works with STRIPE_READ_API_KEY alone (never uses STRIPE_API_KEY).
  * Post-write verification: the charge must report refunded=true (or
    amount_refunded equal to the charge amount) or the script raises loudly.
  * Every apply appends an audit line to data/stripe_action_log.jsonl.

Usage:
    # dry run — inspect and print the plan, no writes possible.
    # --conversation-id is required so the window uses when they emailed:
    python3 scripts/stripe_refund.py cus_ABC123 --conversation-id 3429285444
    python3 scripts/stripe_refund.py cus_ABC123 --charge-id ch_XYZ789 --conversation-id 3429285444

    # the Finish Now combo, executed (both env gates must be set):
    python3 scripts/stripe_refund.py cus_ABC123 --and-cancel-now --apply --conversation-id 3390548887

    # machine-readable output for the skill layer:
    python3 scripts/stripe_refund.py cus_ABC123 --json

Exit codes: 0 = success (applied or plan built) · 2 = checks refused the
action · 1 = unexpected/Stripe error.
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
CHARGE_ID_RE = re.compile(r"^ch_[A-Za-z0-9]+$")

# Refund windows per plan interval, measured from the charge `created`
# timestamp to the first customer email on the Help Scout ticket
# (policies/refund-policy.md): 30 days annual, 24 hours monthly.
# Wall-clock "now" is not the cutoff — processing delay must not refuse
# an in-window email.
WINDOW_SECONDS = {"year": 30 * 86400, "month": 24 * 3600}
# --boundary-grace adds exactly one more day/hour — the policy's "be generous
# at the boundary" rule (day 30 / hour 24). Never more than that.
GRACE_SECONDS = {"year": 86400, "month": 3600}
WINDOW_DISPLAY = {"year": "30-day", "month": "24-hour"}
GRACE_DISPLAY = {"year": "1-day", "month": "1-hour"}
PLAN_LABEL = {"year": "annual", "month": "monthly"}

# Hard cap: annual is $99.99 — anything over $120.00 is anomalous. Refuse.
REFUND_CAP_CENTS = 12000

# Statuses meaning the subscription is already dead for --and-cancel-now.
FULLY_CANCELED_STATUSES = {"canceled", "incomplete_expired"}


def _g(obj: Any, key: str, default: Any = None) -> Any:
    """Read a key off a Stripe object or plain dict."""
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _ref_id(ref: Any) -> str | None:
    """The id behind an expandable reference (bare id string or object)."""
    if ref is None:
        return None
    return ref if isinstance(ref, str) else _g(ref, "id")


def _now_ts() -> int:
    """Current unix time — a function so tests can pin the clock."""
    return int(datetime.now(tz=timezone.utc).timestamp())


def _fmt_datetime(ts: int | None) -> str:
    if not ts:
        return "unknown date"
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%B %-d, %Y at %H:%M UTC")


def _fmt_amount(cents: int | None, currency: str | None = "usd") -> str:
    if cents is None:
        return "unknown amount"
    cur = (currency or "usd").lower()
    if cur == "usd":
        return f"${cents / 100:.2f}"
    return f"{cents / 100:.2f} {cur.upper()}"


def _fmt_age(seconds: int | float) -> str:
    seconds = max(0, seconds)
    if seconds >= 2 * 86400:
        return f"{seconds / 86400:.1f} days"
    return f"{seconds / 3600:.1f} hours"



def _parse_iso_ts(value: str | None) -> int | None:
    """Unix seconds from a Help Scout ISO-8601 timestamp."""
    if not value:
        return None
    value = value.strip()
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    try:
        return int(datetime.fromisoformat(value).timestamp())
    except ValueError:
        return None


def first_customer_email_ts(conversation_id: str) -> int:
    """When the customer first emailed on this Help Scout conversation.

    policies/refund-policy.md gates the window on "emailed support within
    30 days / 24 hours of the charge," not on when Bert runs this script.
    """
    import urllib.error
    import urllib.parse
    import urllib.request

    app_id = os.getenv("HELPSCOUT_APP_ID", "").strip()
    secret = os.getenv("HELPSCOUT_APP_SECRET", "").strip()
    if not app_id or not secret:
        raise RuntimeError(
            "HELPSCOUT_APP_ID and HELPSCOUT_APP_SECRET are required to measure "
            "the refund window from the ticket (when the customer emailed)."
        )
    token_body = urllib.parse.urlencode(
        {"grant_type": "client_credentials", "client_id": app_id, "client_secret": secret}
    ).encode()
    token_req = urllib.request.Request(
        "https://api.helpscout.net/v2/oauth2/token",
        data=token_body,
        method="POST",
    )
    with urllib.request.urlopen(token_req, timeout=20) as resp:
        token = json.loads(resp.read().decode())["access_token"]
    conv_req = urllib.request.Request(
        f"https://api.helpscout.net/v2/conversations/{conversation_id}?embed=threads",
        headers={"Authorization": f"Bearer {token}"},
    )
    try:
        with urllib.request.urlopen(conv_req, timeout=30) as resp:
            conv = json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        raise RuntimeError(
            f"Help Scout conversation {conversation_id} could not be loaded "
            f"(HTTP {e.code}) — cannot measure the emailed-at refund window."
        ) from e
    times: list[int] = []
    for thread in (conv.get("_embedded") or {}).get("threads") or []:
        if thread.get("type") == "customer":
            ts = _parse_iso_ts(thread.get("createdAt"))
            if ts is not None:
                times.append(ts)
    if not times:
        ts = _parse_iso_ts(conv.get("createdAt"))
        if ts is not None:
            times.append(ts)
    if not times:
        raise RuntimeError(
            f"Help Scout conversation {conversation_id} has no customer-email "
            "timestamp — cannot measure the refund window."
        )
    return min(times)


def _schedule_info(sub: Any) -> dict[str, Any] | None:
    """Normalize the sub's schedule (expanded object or bare id) to a dict."""
    schedule = _g(sub, "schedule")
    if not schedule:
        return None
    if isinstance(schedule, str):
        return {"id": schedule, "status": None}
    return {"id": _g(schedule, "id"), "status": _g(schedule, "status")}


# --- charge eligibility ------------------------------------------------------

def check_charge(charge: Any, customer_id: str) -> str | None:
    """First policy refusal for this charge, or None when it is refundable."""
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
            f"({_fmt_amount(amount_refunded, currency)} of {_fmt_amount(amount, currency)}) — human review. "
            "The only sanctioned partial refund is the Path-2 retroactive 40% discount "
            "(policies/renewal-discount-requests.md), which is a separate script, never this one."
        )

    if amount > REFUND_CAP_CENTS:
        return (
            f"charge {charge_id} is {_fmt_amount(amount, currency)} — over the "
            f"{_fmt_amount(REFUND_CAP_CENTS)} hard cap (annual is $99.99). "
            "Anomalous amount; human review."
        )

    return None


# --- charge → subscription resolution ---------------------------------------

def _invoice_subscription_ref(invoice: Any) -> Any:
    """Invoice → subscription reference across Stripe API versions.

    Pre-basil the invoice carries a top-level `subscription`; from
    2025-03-31.basil onward it lives at `parent.subscription_details.subscription`.
    """
    sub = _g(invoice, "subscription")
    if sub:
        return sub
    details = _g(_g(invoice, "parent") or {}, "subscription_details")
    return _g(details, "subscription") if details else None


def _charge_invoice(charge: Any) -> Any:
    """The invoice behind a charge (object or bare id), or None.

    Pre-basil shapes expose `charge.invoice` directly. Post-basil (the SDK
    pins a dahlia version) the Charge has no invoice field, so we walk the
    InvoicePayment mapping via the charge's payment_intent instead.
    """
    inv = _g(charge, "invoice")
    if inv:
        return inv
    pi_id = _ref_id(_g(charge, "payment_intent"))
    if not pi_id:
        return None
    payments = stripe.InvoicePayment.list(
        payment={"type": "payment_intent", "payment_intent": pi_id},
        expand=["data.invoice"],
        limit=10,
    )
    for row in _g(payments, "data") or []:
        inv = _g(row, "invoice")
        if inv:
            return inv
    return None


def resolve_subscription(charge: Any) -> tuple[Any, str]:
    """The subscription this charge paid for, or (None, why-not).

    The interval of that subscription decides the refund window, so a charge
    that resolves to no subscription is a refusal (human review), not a guess.
    """
    charge_id = _g(charge, "id")
    invoice = _charge_invoice(charge)
    if invoice is None:
        return None, (
            f"charge {charge_id} has no linked invoice — looks like a one-off/gift payment, "
            "not a subscription charge. The refund window needs the plan interval "
            "(30-day annual / 24-hour monthly) — human review."
        )
    if isinstance(invoice, str):
        invoice = stripe.Invoice.retrieve(invoice)
    sub_ref = _invoice_subscription_ref(invoice)
    if not sub_ref:
        return None, (
            f"invoice {_g(invoice, 'id')} was not generated by a subscription — cannot determine "
            "the plan interval for the refund window; human review."
        )
    if not isinstance(sub_ref, str) and _g(sub_ref, "items"):
        return sub_ref, ""  # already expanded with items
    return stripe.Subscription.retrieve(_ref_id(sub_ref), expand=["schedule"]), ""


def subscription_interval(sub: Any) -> str | None:
    """The single billing interval ("year"/"month"/…) across the sub's items.

    Prices carry it at `recurring.interval`; legacy plan objects at `interval`.
    Mixed or missing intervals → None (refuse — never guess a window).
    """
    items = _g(_g(sub, "items") or {}, "data") or []
    intervals = set()
    for item in items:
        price = _g(item, "price") or _g(item, "plan") or {}
        recurring = _g(price, "recurring")
        interval = _g(recurring, "interval") if recurring else _g(price, "interval")
        if interval:
            intervals.add(interval)
    return intervals.pop() if len(intervals) == 1 else None


# --- window math --------------------------------------------------------------

def check_window(
    interval: str,
    charge_created: int,
    boundary_grace: bool = False,
    now_ts: int | None = None,
) -> dict[str, Any]:
    """Apply the refund window. `now_ts` is when the customer emailed support, not wall clock."""
    now = now_ts if now_ts is not None else _now_ts()
    age = max(0, now - (charge_created or 0))
    limit = WINDOW_SECONDS[interval]
    grace = GRACE_SECONDS[interval] if boundary_grace else 0
    ok = age <= limit + grace
    used_grace = ok and age > limit

    label, window_disp, grace_disp = PLAN_LABEL[interval], WINDOW_DISPLAY[interval], GRACE_DISPLAY[interval]
    if ok and used_grace:
        verdict = (
            f"past the {window_disp} window but within the {grace_disp} boundary grace "
            f"(charge age {_fmt_age(age)}) — the policy's be-generous-at-the-boundary rule"
        )
    elif ok:
        verdict = f"within the {window_disp} {label} refund window (charge age {_fmt_age(age)})"
    elif boundary_grace:
        verdict = (
            f"PAST the {window_disp} {label} refund window even with the {grace_disp} "
            f"boundary grace (charge age {_fmt_age(age)})"
        )
    else:
        verdict = f"PAST the {window_disp} {label} refund window (charge age {_fmt_age(age)})"

    return {
        "ok": ok,
        "age_seconds": age,
        "limit_seconds": limit,
        "grace_seconds": grace,
        "used_grace": used_grace,
        "verdict": verdict,
    }


# --- plan ----------------------------------------------------------------------

def build_cancel_now(sub: Any) -> dict[str, Any]:
    """What --and-cancel-now will do to this subscription after the refund."""
    status = _g(sub, "status")
    if status in FULLY_CANCELED_STATUSES:
        return {
            "will_cancel": False,
            "reason": f"subscription is already fully canceled (status={status}) — nothing to end.",
            "release_schedule": None,
        }
    schedule = _schedule_info(sub)
    release = schedule if schedule and schedule["status"] in (None, "active", "not_started") else None
    reason = f"subscription [{status}] will be canceled IMMEDIATELY — access ends now, not at period end."
    if _g(sub, "cancel_at_period_end") or _g(sub, "cancel_at"):
        reason += (
            " (cancel_at_period_end was already set, but refunded customers don't keep access — "
            "canceling now anyway.)"
        )
    return {"will_cancel": True, "reason": reason, "release_schedule": release}


def build_plan(
    customer: Any,
    charge: Any,
    sub: Any,
    interval: str,
    window: dict[str, Any],
    and_cancel_now: bool,
) -> dict[str, Any]:
    """Assemble the human-reviewable plan for one refundable charge."""
    amount = _g(charge, "amount")
    currency = (_g(charge, "currency") or "usd").lower()
    created = _g(charge, "created")

    notes: list[str] = []
    trial_end = _g(sub, "trial_end")
    if trial_end and (trial_end - 3600) <= (created or 0) <= (trial_end + 3 * 86400):
        notes.append(
            "this is the trial-conversion charge (created right at trial_end) — use the "
            "trial-conversion refund framing (CancelRefund StripeRefundTrial) per policies/refund-policy.md."
        )
    discount = _g(sub, "discount") or (_g(sub, "discounts") or [None])[0]
    if discount:
        notes.append(
            "subscription carries a discount — the WithDiscount refund replies (full refund + "
            "40% restart offer) apply per policies/refund-policy.md."
        )
    if window["used_grace"]:
        notes.append(
            "past the standard window — honored ONLY under the boundary-generosity rule "
            "(--boundary-grace); double-check the timing story in the ticket."
        )
    if currency != "usd":
        notes.append(
            f"non-USD charge ({currency.upper()}) — refund the full original amount; the customer "
            "may see a small FX discrepancy (disclose only if they raise it)."
        )

    cancel_now = build_cancel_now(sub) if and_cancel_now else None
    sub_status = _g(sub, "status")
    still_renewing = sub_status in ("active", "trialing") and not (
        _g(sub, "cancel_at_period_end") or _g(sub, "cancel_at")
    )
    if not and_cancel_now and still_renewing:
        notes.append(
            "subscription remains ACTIVE and set to renew — a refund alone does not stop future "
            "charges; pass --and-cancel-now (Finish Now) or run stripe_cancel_subscription.py "
            "if the customer is leaving."
        )

    return {
        "action": "refund_full",
        "customer_id": _g(customer, "id"),
        "customer_email": _g(customer, "email"),
        "charge_id": _g(charge, "id"),
        # NB: keyed "charge_status" / "subscription_status" (never "status") so
        # this dict can merge into the CLI's JSON payload, whose "status" field
        # is the outcome marker.
        "charge_status": _g(charge, "status"),
        "amount_cents": amount,
        "currency": currency,
        "amount_display": _fmt_amount(amount, currency),
        "charge_created": created,
        "charge_date": _fmt_datetime(created),
        "charge_age": _fmt_age(window["age_seconds"]),
        "plan_interval": interval,
        "window_verdict": window["verdict"],
        "window_used_grace": window["used_grace"],
        "subscription_id": _g(sub, "id"),
        "subscription_status": sub_status,
        "cancel_now": cancel_now,
        "notes": notes,
    }


# --- gates / audit / execution --------------------------------------------------

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


def _verify_refund(refund: Any, plan: dict[str, Any]) -> None:
    """Raise loudly unless Stripe reports the charge as fully refunded."""
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
        fresh = stripe.Charge.retrieve(plan["charge_id"])  # response wasn't expanded — re-read
    refunded = bool(_g(fresh, "refunded"))
    amount_refunded = _g(fresh, "amount_refunded") or 0
    if not (refunded or amount_refunded == plan["amount_cents"]):
        raise RuntimeError(
            f"Stripe accepted the refund call but charge {plan['charge_id']} still reports "
            f"refunded={refunded} / amount_refunded={amount_refunded} of {plan['amount_cents']} — "
            "verify in the dashboard before doing ANYTHING else."
        )


def execute_plan(plan: dict[str, Any], conversation_id: str) -> dict[str, Any]:
    """Perform the writes described by an eligible plan. Assumes gates passed.

    Refund first, always: if Refund.create fails, no cancellation happens and
    no audit line is written (nothing did). If the refund succeeds but the
    cancel-now leg fails, the audit line still records the refund and we raise.
    """
    # Full refund: deliberately NO `amount` param — Stripe refunds the charge
    # in full. expand=["charge"] returns the freshly-updated charge so the
    # post-write verification reads Stripe's own view of the result.
    # reason="requested_by_customer" is Stripe's canonical tag for
    # support-driven refunds (dashboard forensics; keeps Radar signals clean).
    refund = stripe.Refund.create(
        charge=plan["charge_id"],
        reason="requested_by_customer",
        expand=["charge"],
    )
    _verify_refund(refund, plan)

    cancel_outcome: dict[str, Any] = {"requested": bool(plan.get("cancel_now"))}
    cancel_error = None
    cn = plan.get("cancel_now")
    if cn:
        if not cn["will_cancel"]:
            cancel_outcome.update(result="skipped", reason=cn["reason"])
        else:
            try:
                released = None
                schedule = cn.get("release_schedule")
                if schedule:
                    stripe.SubscriptionSchedule.release(schedule["id"])
                    released = schedule["id"]
                canceled = stripe.Subscription.cancel(plan["subscription_id"])
                if _g(canceled, "status") != "canceled":
                    raise RuntimeError(
                        f"Stripe accepted the cancel call but {plan['subscription_id']} still "
                        f"reports status={_g(canceled, 'status')!r} — verify in the dashboard."
                    )
                cancel_outcome.update(result="canceled", released_schedule=released)
            except Exception as e:  # keep the refund auditable even if the cancel leg dies
                cancel_error = str(e)
                cancel_outcome.update(result="failed", error=cancel_error)

    result = {
        "action": plan["action"],
        "customer_id": plan["customer_id"],
        "charge_id": plan["charge_id"],
        "amount_cents": plan["amount_cents"],
        "currency": plan["currency"],
        "refund_id": _g(refund, "id"),
        "subscription_id": plan.get("subscription_id"),
        "and_cancel_now": cancel_outcome,
        "conversation_id": conversation_id,
        "executed_at": datetime.now(tz=timezone.utc).isoformat(),
    }
    _append_audit(result)

    if cancel_error:
        raise RuntimeError(
            f"refund {result['refund_id']} for {plan['charge_id']} SUCCEEDED (audit logged) but the "
            f"immediate cancellation of {plan['subscription_id']} FAILED: {cancel_error} — cancel it "
            "manually in the Stripe dashboard. Do NOT re-run --apply; the refund already went through."
        )
    return result


# --- Stripe wiring ----------------------------------------------------------------

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


def _fetch_charge(charge_id: str) -> Any:
    """Retrieve one charge; None when it doesn't exist (a refusal, not a crash)."""
    try:
        return stripe.Charge.retrieve(charge_id)
    except stripe.error.InvalidRequestError as e:
        if getattr(e, "code", None) == "resource_missing":
            return None
        raise


def _latest_succeeded_charge(customer_id: str) -> Any:
    """The customer's most recent succeeded charge (Stripe lists newest first)."""
    charges = stripe.Charge.list(customer=customer_id, limit=100)
    for charge in _g(charges, "data") or []:
        if _g(charge, "status") == "succeeded":
            return charge
    return None


# --- CLI ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Fully refund one Stripe charge for one customer (refund window enforced in code).",
    )
    parser.add_argument("customer_id", help="Stripe customer ID (cus_…) — exactly one")
    parser.add_argument(
        "--charge-id",
        help="Charge to refund (ch_…); default: the customer's most recent succeeded charge",
    )
    parser.add_argument(
        "--and-cancel-now",
        action="store_true",
        help="After the refund, cancel the charge's subscription IMMEDIATELY (the Finish Now combo)",
    )
    parser.add_argument(
        "--boundary-grace",
        action="store_true",
        help="Extend the window by exactly 1 day (annual) / 1 hour (monthly) — the boundary-generosity rule",
    )
    parser.add_argument("--apply", action="store_true", help="Execute the refund (default: dry run)")
    parser.add_argument(
        "--conversation-id",
        help="Help Scout conversation (required): window is first customer email on this ticket, not run time",
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

    if not args.conversation_id:
        print(
            "ERROR: --conversation-id is required so the refund window uses when the "
            "customer emailed support, not when this script runs.",
            file=sys.stderr,
        )
        return emit({"status": "error", "reason": "missing conversation id"}, 2)
    if args.apply:
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
        if interval is None:
            reason = (
                f"subscription {_g(sub, 'id')} has no single billing interval (mixed or missing "
                "price data) — cannot compute the refund window; human review."
            )
            print(f"\nREFUSED: {reason}", file=sys.stderr)
            return emit({"status": "refused", "reason": reason, "charge_id": charge_id}, 2)
        if interval not in WINDOW_SECONDS:
            reason = (
                f"subscription {_g(sub, 'id')} bills every {interval!r} — the refund policy only "
                "defines windows for annual and monthly plans; human review."
            )
            print(f"\nREFUSED: {reason}", file=sys.stderr)
            return emit({"status": "refused", "reason": reason, "charge_id": charge_id}, 2)

        emailed_ts = first_customer_email_ts(args.conversation_id)
        print(
            f"  customer emailed {_fmt_datetime(emailed_ts)} "
            f"(window clock = Help Scout first customer thread, not now)"
        )
        window = check_window(
            interval, _g(charge, "created"), args.boundary_grace, now_ts=emailed_ts
        )
        if not window["ok"]:
            reason = (
                f"{window['verdict']}. No refund — cancel at next renewal only "
                "(policies/refund-policy.md)."
            )
            print(f"\nREFUSED: {reason}", file=sys.stderr)
            return emit({"status": "refused", "reason": reason, "charge_id": charge_id}, 2)

        plan = build_plan(customer, charge, sub, interval, window, args.and_cancel_now)

        print(f"\nPLAN: fully refund {plan['charge_id']} — {plan['amount_display']} back to the customer")
        print(f"  charge date {plan['charge_date']} — age {plan['charge_age']}")
        print(f"  window: {plan['window_verdict']}")
        print(
            f"  subscription {plan['subscription_id']} [{plan['subscription_status']}] — "
            f"bills per {plan['plan_interval']}"
        )
        if plan["cancel_now"]:
            print(f"  and-cancel-now: {plan['cancel_now']['reason']}")
            if plan["cancel_now"].get("release_schedule"):
                print(
                    f"    (subscription schedule {plan['cancel_now']['release_schedule']['id']} "
                    "will be RELEASED first)"
                )
        for note in plan["notes"]:
            print(f"  note: {note}")

        if not args.apply:
            print("\nDry run only — re-run with --apply --conversation-id <id> to execute.")
            return emit({"status": "plan", **plan}, 0)

        result = execute_plan(plan, args.conversation_id)
        print(
            f"\nAPPLIED: refund {result['refund_id']} issued — {plan['amount_display']} "
            f"returned on {plan['charge_id']}."
        )
        cn = result["and_cancel_now"]
        if cn.get("result") == "canceled":
            print(
                f"  and-cancel-now: subscription {result['subscription_id']} canceled immediately — "
                "access has ended."
            )
            if cn.get("released_schedule"):
                print(f"    (released subscription schedule {cn['released_schedule']} first.)")
        elif cn.get("result") == "skipped":
            print(f"  and-cancel-now: skipped — {cn['reason']}")
        return emit({"status": "applied", **result}, 0)

    except stripe.error.StripeError as e:
        msg = getattr(e, "user_message", None) or str(e)
        print(f"ERROR: Stripe API error: {msg}", file=sys.stderr)
        return emit({"status": "error", "reason": msg}, 1)


if __name__ == "__main__":
    sys.exit(main())
