"""Server-side executor for guarded Stripe write actions (the sidebar + MCP rails).

The CLI scripts under scripts/ stay the canonical implementations; this module
invokes the same functions in-process so the Help Scout sidebar chat and the
Bert MCP server can execute an action straight from conversation ("cancel the
subscription") without anyone shelling out. Per Cassidy 2026-07-22 there is no
confirm step on these rails — the support agent's chat instruction IS the
authorization (the actions are reversible; cancel is at-period-end only). All
other guardrails are identical to the CLI path:

  * same env gates (STRIPE_WRITE_API_KEY + ACTION_EXECUTION_ENABLED=true) —
    on a deployment without them (e.g. Render before arming) every call
    returns {"status": "disabled"} and nothing is attempted;
  * same eligibility pipeline (classify → select → plan → execute) run fresh
    at execution time — never against stale state;
  * same audit line in data/stripe_action_log.jsonl, tagged with the actor;
  * plus an "Action executed" internal note posted to the ticket (fail-soft).

Every function returns a JSON-serializable dict whose top-level "status" is
the outcome marker: applied | already_off | refused | disabled | error.
"""

from __future__ import annotations

import logging
import os
import re
from typing import Any

import requests
import stripe

import orchestrator
import triage_tickets
from scripts import stripe_cancel_subscription as cancel_script

log = logging.getLogger(__name__)

_CONVERSATION_ID_RE = re.compile(r"^\d{5,}$")


def _esc(s: Any) -> str:
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _hs_session() -> requests.Session:
    token = orchestrator.get_access_token()
    s = requests.Session()
    s.headers.update({"Authorization": f"Bearer {token}"})
    return s


def _executed_note_html(result: dict[str, Any]) -> str:
    items = [
        "<li><strong>Action:</strong> Turned off auto-renew (cancel at period end)</li>",
        f"<li><strong>Subscription:</strong> {_esc(result.get('subscription_id'))} "
        f"({_esc(result.get('customer_id'))})</li>",
        f"<li><strong>Access continues through:</strong> {_esc(result.get('access_continues_through'))} "
        "— no further charges</li>",
        f"<li><strong>Actor:</strong> {_esc(result.get('actor'))}</li>",
    ]
    if result.get("released_schedule"):
        items.append(
            f"<li><strong>Released schedule:</strong> {_esc(result['released_schedule'])} "
            "(pending scheduled changes discarded)</li>"
        )
    return (
        "<p><strong>✅ Action executed</strong> (stripe_cancel_subscription)</p>"
        f"<ul>{''.join(items)}</ul>"
    )


def _post_executed_note(conversation_id: str, result: dict[str, Any], hs: requests.Session | None = None) -> bool:
    """Best-effort internal note on the ticket. Never raises."""
    try:
        session = hs or _hs_session()
        body: dict[str, Any] = {"text": _executed_note_html(result)}
        note_user = (os.environ.get("HELPSCOUT_NOTE_USER_ID") or "").strip()
        if note_user.isdigit():
            body["user"] = int(note_user)
        r = session.post(
            f"{triage_tickets.BASE_URL}/conversations/{conversation_id}/notes",
            json=body,
            timeout=30,
        )
        return r.status_code in (200, 201)
    except Exception:
        log.exception("executed-note post failed for conversation %s", conversation_id)
        return False


def cancel_subscription(
    customer_id: str,
    conversation_id: str,
    actor: str,
    hs: requests.Session | None = None,
) -> dict[str, Any]:
    """Cancel-at-period-end for one customer, from a server surface.

    Runs the full CLI pipeline in-process and executes immediately when
    exactly one subscription is eligible. Returns the outcome dict; the
    calling surface narrates it and updates the draft.
    """
    customer_id = (customer_id or "").strip()
    conversation_id = str(conversation_id or "").strip()

    if not cancel_script.CUSTOMER_ID_RE.match(customer_id):
        return {"status": "error", "reason": f"{customer_id!r} is not a Stripe customer ID (cus_…)"}
    if not _CONVERSATION_ID_RE.match(conversation_id):
        return {"status": "error", "reason": "a Help Scout conversation id is required for the audit trail"}

    ok, why = cancel_script.write_gates_ok()
    if not ok:
        return {
            "status": "disabled",
            "reason": f"Stripe writes are not armed on this deployment ({why}). "
            "The action was NOT performed — leave it as a manual 'Actions needed' item.",
        }

    try:
        # One Stripe read: classify then execute. Do not dry-run via CLI first
        # when hydrate already showed a single eligible sub.
        cancel_script._configure_stripe_key(apply=True)
        customer = cancel_script._fetch_customer(customer_id)
        raw_subs = cancel_script._fetch_subscriptions(customer_id)
        classified = [cancel_script.classify_subscription(s) for s in raw_subs]
        decision = cancel_script.select_target(classified)

        if decision["decision"] == "noop":
            return {"status": "already_off", **decision["target"]}
        if decision["decision"] == "refuse":
            return {"status": "refused", "reason": decision["reason"]}

        target_id = decision["target"]["subscription_id"]
        raw = next(s for s in raw_subs if cancel_script._g(s, "id") == target_id)
        plan = cancel_script.build_plan(customer, raw)
        result = cancel_script.execute_plan(plan, conversation_id, actor=actor)
        result["notes"] = plan.get("notes", [])
        result["note_posted"] = _post_executed_note(conversation_id, result, hs=hs)
        return {"status": "applied", **result}

    except SystemExit as e:  # the CLI helpers signal hard stops this way (e.g. deleted customer)
        return {"status": "error", "reason": str(e)}
    except stripe.error.StripeError as e:
        return {"status": "error", "reason": getattr(e, "user_message", None) or str(e)}
    except Exception as e:  # a server surface must never take down the chat turn
        log.exception("cancel_subscription rails failed for %s", customer_id)
        return {"status": "error", "reason": str(e)[:300]}
