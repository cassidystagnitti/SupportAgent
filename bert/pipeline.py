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

import logging
import os

import orchestrator
import stripe_research
import triage_tickets

log = logging.getLogger(__name__)

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
    stripe_ctx = None
    if is_stripe or is_gift:
        try:
            stripe_ctx = o.fetch_stripe_context(email) if email else None
            stripe_block = o.format_stripe_context(stripe_ctx)
        except Exception:
            stripe_block = "Stripe data unavailable"
    else:
        stripe_block = f"N/A — customer is on {platform or 'unknown'} (not Stripe web billing)"

    # Step 3 charge hunt (policies/no-account-found-troubleshooting.md):
    # signal-gated, read-only, pre-approved to run autonomously (2026-07-20).
    # Findings ride in stripe_block so they reach the draft prompt (and the
    # verifier's ticket context) exactly like the enrichment block does.
    research = None
    try:
        # Scan the whole thread, not just the latest message — the payment
        # details usually arrive in an earlier customer reply.
        thread_text = f"{body}\n\n{conversation_history}".strip()
        research = stripe_research.run_charge_hunt_for_ticket(
            body=thread_text, email=email, customer_name=customer_name,
            account_blob=account_blob)
        if research:
            hunt_block = stripe_research.format_charge_hunt_block(research)
            if hunt_block:
                stripe_block = f"{stripe_block}\n\n{hunt_block}" if stripe_block else hunt_block
    except Exception:
        research = None

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
        "stripe_ctx": stripe_ctx,
        "stripe_research": research,
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
        "close_no_reply": bool(parsed.get("close_no_reply")),
        # full Claude JSON, so the internal note can be rendered faithfully
        "parsed": parsed,
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


def conversation_status(session, conversation_id) -> str | None:
    """Return the live Help Scout status of a conversation.

    One of ``active`` / ``pending`` / ``closed`` / ``spam``, or ``None`` if the
    field is absent. Used to avoid stacking a fresh draft on a ticket a human
    has already answered and closed since the morning draft snapshot.
    """
    url = f"{orchestrator.BASE_URL}/conversations/{int(conversation_id)}"
    data = triage_tickets.api_get(session, url)
    return (data or {}).get("status")


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


def apple_mailbox_id() -> int | None:
    """The Apple mailbox id from APPLE_MAILBOX_ID, or None when unset/invalid."""
    raw = os.getenv("APPLE_MAILBOX_ID", "").strip()
    try:
        return int(raw) if raw else None
    except ValueError:
        return None


def move_conversation(session, conversation_id, mailbox_id) -> bool:
    """Move a conversation to another mailbox via Help Scout PATCH (fail-soft).

    Same single-JSON-Patch-object shape as ``update_draft``:
    {"op": "move", "path": "/mailboxId", "value": <id>} → HTTP 204.

    Note: the OAuth app's token can only move into mailboxes the app-owning
    Help Scout user has access to — a destination outside GET /v2/mailboxes
    will fail. Returns True on success, False on any failure; never raises.
    """
    try:
        url = f"{orchestrator.BASE_URL}/conversations/{int(conversation_id)}"
        body = {"op": "move", "path": "/mailboxId", "value": int(mailbox_id)}
        r = session.patch(url, json=body)
        r.raise_for_status()
        print(f"Moved conversation {conversation_id} → mailbox {mailbox_id}")
        return True
    except Exception as e:
        print(f"Move FAILED for conversation {conversation_id} → mailbox {mailbox_id}: {e}")
        return False


# --- Duplicate consolidation: fold a same-customer duplicate into the keeper ---

HS_CONVERSATION_URL = "https://secure.helpscout.net/conversation/{cid}"


def customer_thread_html(session, conversation_id) -> str:
    """Concatenated HTML bodies of the customer's own messages on a conversation."""
    threads = triage_tickets._fetch_all_threads(session, int(conversation_id))
    parts = [t.get("body") or "" for t in threads if t.get("type") == "customer"]
    return "\n<hr>\n".join(p for p in parts if p)


def post_plain_note(session, conversation_id, html: str) -> str | None:
    """POST a free-form internal note. None when HELPSCOUT_NOTE_USER_ID is unset
    (Help Scout requires a user id on notes)."""
    note_user_id = os.getenv("HELPSCOUT_NOTE_USER_ID", "").strip()
    if not note_user_id:
        return None
    url = f"{orchestrator.BASE_URL}/conversations/{int(conversation_id)}/notes"
    r = orchestrator._helpscout_post(session, url, {"text": html, "user": int(note_user_id)})
    r.raise_for_status()
    return r.headers.get("Resource-ID") or r.headers.get("resource-id") or "posted"


def close_conversation(session, conversation_id) -> bool:
    """Close a conversation via the same single-JSON-Patch shape as update_draft."""
    url = f"{orchestrator.BASE_URL}/conversations/{int(conversation_id)}"
    r = session.patch(url, json={"op": "replace", "path": "/status", "value": "closed"})
    r.raise_for_status()
    return True


def consolidate_duplicate(session, keep_cid, dup_cid) -> dict:
    """Fold a same-customer DUPLICATE conversation into the one that will answer.

    Only for tickets that are genuinely about the same issue — the caller
    (Bert with Cassidy) decides relevance; unrelated tickets from the same
    customer stay open side by side.

    Ordered so nothing is lost: (1) the duplicate's customer messages are
    copied into an internal note on the keeper; only if that lands, (2) the
    duplicate gets a "Duplicate of #keeper" note (best-effort) and (3) is
    closed. Closing the duplicate also unblocks the verifier's same-customer
    sibling check on the keeper, which only counts OPEN conversations.

    Returns {"keeper_note", "dup_note", "closed", "error"}; never raises.
    """
    out = {"keeper_note": False, "dup_note": False, "closed": False, "error": None}
    try:
        dup_html = customer_thread_html(session, dup_cid)
        dup_link = HS_CONVERSATION_URL.format(cid=int(dup_cid))
        keeper_note = (
            f"<p><strong>Consolidated from duplicate conversation "
            f'<a href="{dup_link}">#{int(dup_cid)}</a></strong> '
            f"(same customer, same issue). Customer's message(s) there:</p>"
            f"{dup_html or '<p>(no customer text found)</p>'}"
        )
        if not post_plain_note(session, keep_cid, keeper_note):
            out["error"] = ("keeper note not posted (HELPSCOUT_NOTE_USER_ID unset) — "
                            "duplicate left open")
            return out
        out["keeper_note"] = True

        keep_link = HS_CONVERSATION_URL.format(cid=int(keep_cid))
        dup_note = (f'<p>Duplicate of <a href="{keep_link}">conversation #{int(keep_cid)}</a> '
                    f"— consolidated and answered there.</p>")
        try:
            out["dup_note"] = bool(post_plain_note(session, dup_cid, dup_note))
        except Exception:
            log.warning("duplicate-of note failed for %s — closing anyway", dup_cid,
                        exc_info=True)
        out["closed"] = close_conversation(session, dup_cid)
    except Exception as e:
        log.warning("consolidate_duplicate(%s -> %s) failed", dup_cid, keep_cid, exc_info=True)
        out["error"] = str(e)
    return out


# --- Internal action-note: a short "Actions needed" bullet list, nothing else ---

NOTE_MARKER = "Actions needed"
# Older long-form notes used this marker; recognize both so we don't double-post.
_LEGACY_NOTE_MARKER = "AI Draft Classification"


def should_post_note(parsed: dict) -> bool:
    """True when a ticket needs an internal note (escalation or manual action)."""
    return orchestrator.should_post_note(bool(parsed.get("escalate")), parsed)


def has_ai_note(session, conversation_id) -> bool:
    """True if an AI-authored internal note already exists (idempotency guard)."""
    for t in triage_tickets._fetch_all_threads(session, int(conversation_id)):
        if t.get("type") == "note":
            body = t.get("body") or ""
            if NOTE_MARKER in body or _LEGACY_NOTE_MARKER in body:
                return True
    return False


def action_items(parsed: dict) -> list:
    """The concrete actions a CS rep must take, as short strings.

    Prefers an explicit ``action_items`` list from the draft JSON; falls back to
    the single ``action_description``; for a bare escalation, the escalate reason.
    """
    items = []
    raw = parsed.get("action_items")
    if isinstance(raw, list):
        items = [str(x).strip() for x in raw if str(x).strip()]
    if not items:
        desc = (parsed.get("action_description") or "").strip()
        if desc:
            items = [desc]
    if not items and parsed.get("escalate"):
        items = [(parsed.get("escalate_reason") or "Review and handle — escalated").strip()]
    return items


def build_note_html(parsed: dict, *_ignored, **_kw) -> str:
    """Render the internal note as a short 'Actions needed' bullet list. Returns
    '' when there are no actions (so no empty note is posted)."""
    items = action_items(parsed)
    if not items:
        return ""
    lis = "".join(f"<li>{orchestrator._html_escape(i)}</li>" for i in items)
    return f"<p><strong>Actions needed</strong></p><ul>{lis}</ul>"


def post_note(session, conversation_id, parsed: dict, *_ignored, **_kw) -> str | None:
    """POST the short 'Actions needed' bullet note. No-op (returns None) when there
    are no actions, or when HELPSCOUT_NOTE_USER_ID is unset (HS needs a user)."""
    note_user_id = os.getenv("HELPSCOUT_NOTE_USER_ID", "").strip()
    if not note_user_id:
        return None
    note_html = build_note_html(parsed)
    if not note_html:
        return None
    url = f"{orchestrator.BASE_URL}/conversations/{int(conversation_id)}/notes"
    r = orchestrator._helpscout_post(session, url, {"text": note_html, "user": int(note_user_id)})
    r.raise_for_status()
    return r.headers.get("Resource-ID") or r.headers.get("resource-id")
