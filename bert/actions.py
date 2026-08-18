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
the outcome marker: applied | already_off | already_on | refused | disabled |
error.

The Help Scout contact helpers (``link_customer_email``) live here too. They
are not Stripe writes and carry no Stripe gates — see helpscout_identity for
the evidence rules and the HELPSCOUT_IDENTITY_WRITES switch.
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
import helpscout_identity
from scripts import stripe_cancel_subscription as cancel_script
from scripts import stripe_reactivate_subscription as reactivate_script

log = logging.getLogger(__name__)

_CONVERSATION_ID_RE = re.compile(r"^\d{5,}$")


def _esc(s: Any) -> str:
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _hs_session() -> requests.Session:
    token = orchestrator.get_access_token()
    s = requests.Session()
    s.headers.update({"Authorization": f"Bearer {token}"})
    return s


def _reactivated_note_html(result: dict[str, Any]) -> str:
    items = [
        "<li><strong>Action:</strong> Turned auto-renew back ON (subscription will renew)</li>",
        f"<li><strong>Subscription:</strong> {_esc(result.get('subscription_id'))} "
        f"({_esc(result.get('customer_id'))})</li>",
        f"<li><strong>Renews:</strong> {_esc(result.get('renews_on'))} for "
        f"{_esc(result.get('renewal_amount_display'))} (before any discount)</li>",
        f"<li><strong>Actor:</strong> {_esc(result.get('actor'))}</li>",
    ]
    if result.get("released_schedule"):
        items.append(
            f"<li><strong>Released schedule:</strong> {_esc(result['released_schedule'])} "
            "(pending scheduled changes discarded)</li>"
        )
    if result.get("cleared_cancel_at"):
        items.append("<li><strong>Cleared</strong> the fixed cancel_at date</li>")
    return (
        "<p><strong>✅ Action executed</strong> (stripe_reactivate_subscription)</p>"
        f"<ul>{''.join(items)}</ul>"
    )


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


def _post_executed_note(conversation_id: str, result: dict[str, Any], hs: requests.Session | None = None,
                        render=_executed_note_html) -> bool:
    """Best-effort internal note on the ticket. Never raises."""
    try:
        session = hs or _hs_session()
        body: dict[str, Any] = {"text": render(result)}
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


def reactivate_subscription(
    customer_id: str,
    conversation_id: str,
    actor: str,
    hs: requests.Session | None = None,
) -> dict[str, Any]:
    """Restore auto-renew for one customer, from a server surface.

    The retention-save half of a "I'll stay if you can help on price" ticket:
    a renewal coupon is inert while the subscription is set to cancel, so this
    runs first. Unlike cancelling, this RE-ARMS a charge — only call it when the
    customer has asked to stay.
    """
    customer_id = (customer_id or "").strip()
    conversation_id = str(conversation_id or "").strip()

    if not reactivate_script.CUSTOMER_ID_RE.match(customer_id):
        return {"status": "error", "reason": f"{customer_id!r} is not a Stripe customer ID (cus_…)"}
    if not _CONVERSATION_ID_RE.match(conversation_id):
        return {"status": "error", "reason": "a Help Scout conversation id is required for the audit trail"}

    ok, why = reactivate_script.write_gates_ok()
    if not ok:
        return {
            "status": "disabled",
            "reason": f"Stripe writes are not armed on this deployment ({why}). "
            "The action was NOT performed — leave it as a manual 'Actions needed' item.",
        }

    try:
        reactivate_script._configure_stripe_key(apply=True)
        customer = reactivate_script._fetch_customer(customer_id)
        raw_subs = reactivate_script._fetch_subscriptions(customer_id)
        classified = [reactivate_script.classify_subscription(s) for s in raw_subs]
        decision = reactivate_script.select_target(classified)

        if decision["decision"] == "noop":
            return {"status": "already_on", **decision["target"]}
        if decision["decision"] == "refuse":
            return {"status": "refused", "reason": decision["reason"]}

        target_id = decision["target"]["subscription_id"]
        raw = next(s for s in raw_subs if reactivate_script._g(s, "id") == target_id)
        plan = reactivate_script.build_plan(customer, raw)
        result = reactivate_script.execute_plan(plan, conversation_id, actor=actor)
        result["notes"] = plan.get("notes", [])
        result["note_posted"] = _post_executed_note(
            conversation_id, result, hs=hs, render=_reactivated_note_html)
        return {"status": "applied", **result}

    except SystemExit as e:  # the CLI helpers signal hard stops this way (e.g. deleted customer)
        return {"status": "error", "reason": str(e)}
    except stripe.error.StripeError as e:
        return {"status": "error", "reason": getattr(e, "user_message", None) or str(e)}
    except Exception as e:  # a server surface must never take down the chat turn
        log.exception("reactivate_subscription rails failed for %s", customer_id)
        return {"status": "error", "reason": str(e)[:300]}


def link_customer_email(
    conversation_id: str,
    email: str,
    hs_customer_id: int | str,
    actor: str,
    hs: requests.Session | None = None,
) -> dict[str, Any]:
    """Attach one more address to this ticket's Help Scout contact.

    The agent asking for it IS the evidence here — they have the thread in
    front of them — so the automatic pipeline's ownership heuristics do not
    apply. The address filter still does: role mailboxes and our own domains
    are refused, since linking one of those would fuse unrelated customers.

    When another contact already owns the address, the two records are merged
    into this one (conversations re-pointed, addresses moved). Status is one of:
    linked | merged | refused | disabled | error.
    """
    conversation_id = str(conversation_id or "").strip()
    email = helpscout_identity.normalize_email(email)

    if not _CONVERSATION_ID_RE.match(conversation_id):
        return {"status": "error", "reason": "a Help Scout conversation id is required for the audit trail"}
    if not hs_customer_id:
        return {"status": "error", "reason": "no Help Scout contact on this ticket"}

    ok, why = helpscout_identity.is_linkable_address(email)
    if not ok:
        return {"status": "refused", "reason": f"{email or '(blank)'} cannot be linked — {why}."}
    if not helpscout_identity.writes_enabled():
        return {
            "status": "disabled",
            "reason": "contact writes are turned off on this deployment "
            "(HELPSCOUT_IDENTITY_WRITES=false) — add the address in the Help Scout UI instead.",
        }

    session = hs or _hs_session()
    try:
        existing = {e["value"] for e in helpscout_identity.list_customer_emails(session, hs_customer_id)}
        if email in existing:
            return {"status": "linked", "email": email, "already_present": True,
                    "reason": "already on this contact — nothing to do."}

        owner = helpscout_identity.find_customer_by_email(session, email)
        if owner is None:
            helpscout_identity.add_email(session, hs_customer_id, email)
            helpscout_identity.audit({"action": "link_email", "conversation_id": conversation_id,
                                      "actor": actor, "customer_id": hs_customer_id, "email": email,
                                      "evidence": "support agent instruction"})
            return {"status": "linked", "email": email, "already_present": False}

        if str(owner.get("id")) == str(hs_customer_id):
            return {"status": "linked", "email": email, "already_present": True,
                    "reason": "already on this contact — nothing to do."}

        outcome = helpscout_identity.merge_contacts(
            session, keep_id=hs_customer_id, dup_id=owner.get("id"),
            conversation_id=conversation_id, actor=actor)
        return {"status": "merged", "email": email, **outcome}

    except Exception as e:
        log.exception("link_customer_email failed for conversation %s", conversation_id)
        return {"status": "error", "reason": str(e)[:300]}
