"""Shared draft seams for Bert — hydrate one ticket, draft it (with the standing
brief injected), post the draft.

These reuse the *same* draft brain the production orchestrator uses
(``orchestrator._call_claude_draft_with_action_retry`` +
``_build_dynamic_user_message`` + ``load_policy_docs``) rather than
reimplementing drafting. The only Bert-specific addition is the standing-brief
block, injected via ``inject_brief`` so the team's live context reaches every
draft worker.

``hydrate_ticket`` mirrors the read path of ``orchestrator.process_ticket_sync``
(conversation → threads → reply-mode → account → Stripe) without any of its
write side effects.
"""

from __future__ import annotations

import os

import orchestrator
import triage_tickets

BRIEF_PREFIX = (
    "\n\n=== STANDING BRIEF (internal team context — apply it, but never quote it "
    "verbatim to the customer) ===\n"
)


def inject_brief(dynamic_message: str, brief: str) -> str:
    """Append the standing-brief block iff the brief is non-empty."""
    brief = (brief or "").strip()
    if not brief:
        return dynamic_message
    return f"{dynamic_message}{BRIEF_PREFIX}{brief}\n"


def hydrate_ticket(session, conversation_id: int) -> dict:
    """Gather one ticket's full context (read-only). Fail-soft on enrichment."""
    o = orchestrator
    cid = int(conversation_id)
    convo = o.fetch_conversation(session, cid)
    threads = o._fetch_conversation_threads(session, convo, cid)
    reply_mode = o.detect_reply_mode(threads)

    cust = o._customer_from_conversation(convo)
    hs_customer_id = cust.get("id")
    email = (cust.get("email") or "").strip()
    customer_name = o._customer_display_name(cust)
    subject = convo.get("subject") or "(no subject)"
    existing_tags = o._extract_tag_names(convo.get("tags", []))

    if reply_mode:
        conversation_history, body = o.get_conversation_history(session, cid, threads=threads)
        body = body or "(empty)"
    else:
        conversation_history = ""
        body = o.get_conversation_text(session, cid, threads=threads) or "(empty)"

    account_blob = ""
    try:
        hs_emails = o.fetch_customer_emails_from_helpscout(session, hs_customer_id) if hs_customer_id else []
        ctx = o.fetch_account_contexts_for_ticket(
            primary_email=email or None,
            ticket_text=body,
            extra_emails=hs_emails,
        )
        account_blob = ctx.get("combined_blob", "")
        if not account_blob.strip():
            account_blob = "Account lookup failed — could not retrieve customer data."
    except Exception:
        account_blob = "Account lookup failed — could not retrieve customer data."

    platform = o._subscription_platform(account_blob)
    is_stripe = bool(platform) and platform.lower() == "stripe"
    is_gift = "gift-subscription" in existing_tags
    stripe_block = ""
    if is_stripe or is_gift:
        try:
            stripe_ctx = o.fetch_stripe_context(email) if email else None
            stripe_block = o.format_stripe_context(stripe_ctx)
        except Exception:
            stripe_block = "Stripe data unavailable"
    else:
        stripe_block = f"N/A — customer is on {platform or 'unknown'} (not Stripe web billing)"

    return {
        "conversation_id": cid,
        "subject": subject,
        "customer_name": customer_name,
        "hs_customer_id": hs_customer_id,
        "email": email,
        "body": body,
        "conversation_history": conversation_history,
        "reply_mode": reply_mode,
        "account_blob": account_blob,
        "stripe_block": stripe_block,
        "existing_tags": existing_tags,
    }


def draft_one(client, ctx: dict, brief: str, *, model: str) -> dict:
    """Draft one ticket via the shared brain, with the standing brief injected."""
    o = orchestrator
    agent_name = os.getenv("SUPPORT_AGENT_SIGNOFF_NAME", "Happier Meditation Support")

    dynamic_message = o._build_dynamic_user_message(
        ticket_subject=ctx["subject"],
        ticket_body=ctx["body"],
        customer_name=ctx["customer_name"],
        customer_email=ctx.get("email") or "(unknown)",
        account_blob=ctx["account_blob"],
        stripe_context=ctx["stripe_block"],
        agent_name=agent_name,
        conversation_history=ctx.get("conversation_history", ""),
    )
    if ctx.get("reply_mode"):
        dynamic_message = f"{o.REPLY_MODE_PROMPT_PREFIX}\n\n{dynamic_message}"
    dynamic_message = inject_brief(dynamic_message, brief)

    _msg, parsed, _raw = o._call_claude_draft_with_action_retry(
        client,
        system_prompt=o._load_system_prompt(),
        policy_docs=o.load_policy_docs(),
        dynamic_user_message=dynamic_message,
        model=model,
    )

    return {
        "draft_reply": parsed.get("draft_reply") or "",
        "confidence": parsed.get("confidence"),
        "referenced_policies": parsed.get("referenced_policies") or [],
        "reasoning": parsed.get("reasoning"),
        "needs_action": bool(parsed.get("needs_action")),
        "escalate": bool(parsed.get("escalate")),
        "open_question": parsed.get("open_question"),
        "bug_report": parsed.get("bug_report"),
        "action_description": parsed.get("action_description"),
        "action_system": parsed.get("action_system"),
    }


def post_draft(session, conversation_id: str, hs_customer_id: int, draft_reply: str, timestamp: str) -> str | None:
    """POST a draft reply to Help Scout and record it in the draft registry."""
    o = orchestrator
    cid = str(conversation_id)
    reply_url = f"{o.BASE_URL}/conversations/{cid}/reply"
    payload = {"customer": {"id": int(hs_customer_id)}, "text": draft_reply, "draft": True}
    r = o._helpscout_post(session, reply_url, payload)
    r.raise_for_status()
    draft_rid = r.headers.get("Resource-ID") or r.headers.get("resource-id")
    if draft_rid:
        o.draft_registry.set(cid, draft_rid, timestamp)
    return draft_rid


def find_draft_threads(session, conversation_id) -> list:
    """Return the ids of all live draft message threads on a conversation."""
    threads = triage_tickets._fetch_all_threads(session, int(conversation_id))
    return [t.get("id") for t in threads
            if t.get("type") == "message" and t.get("state") == "draft" and t.get("id") is not None]


def update_draft(session, conversation_id, thread_id, text: str) -> bool:
    """Edit an existing draft thread's text IN PLACE via Help Scout PATCH.

    Contrary to the older note in draft_registry.py, update-in-place IS
    supported — the working request is a SINGLE JSON-Patch object (not an
    array): {"op": "replace", "path": "/text", "value": "..."}. Verified
    2026-07-06 (HTTP 204). Using this avoids stacking duplicate drafts, since
    Help Scout still has no DELETE for draft threads.
    """
    url = f"{orchestrator.BASE_URL}/conversations/{int(conversation_id)}/threads/{int(thread_id)}"
    body = {"op": "replace", "path": "/text", "value": text}
    r = session.patch(url, json=body)
    r.raise_for_status()
    return r.status_code == 204
