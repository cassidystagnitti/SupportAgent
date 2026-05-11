"""Maven AGI support pipeline: triage → account → Stripe (optional) → Maven draft → Help Scout."""

from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timezone
from typing import Any, Callable, Optional

import requests
from dotenv import load_dotenv
from mavenagi import MavenAGI
from mavenagi.commons import EntityIdBase
from mavenagi.conversation.types.stream_response import StreamResponse_End, StreamResponse_Text

_SUPPORT_DIR = os.path.dirname(os.path.abspath(__file__))
_ROOT_DIR = os.path.dirname(_SUPPORT_DIR)
load_dotenv(os.path.join(_SUPPORT_DIR, ".env"))
load_dotenv(os.path.join(_ROOT_DIR, ".env"))

from account_context import fetch_account_contexts_for_ticket, fetch_customer_emails_from_helpscout  # noqa: E402
from orchestrator import (  # noqa: E402
    _customer_display_name,
    _customer_from_conversation,
    _extract_tag_names,
    _helpscout_post,
    _html_escape,
    _subscription_platform,
    _update_conversation_tags,
)
from product_prioritization import run_product_prioritization  # noqa: E402
from stripe_context import fetch_stripe_context, format_stripe_context  # noqa: E402
from triage_tickets import (  # noqa: E402
    BASE_URL,
    fetch_conversation,
    get_access_token,
    get_conversation_history,
    get_conversation_text,
    run_triage,
)

log = logging.getLogger("maven_orchestrator")


def _maven_client() -> MavenAGI:
    org_id = os.getenv("MAVEN_ORG_ID", "")
    agent_id = os.getenv("MAVEN_AGENT_ID", "")
    app_id = os.getenv("MAVEN_APP_ID", "")
    app_secret = os.getenv("MAVEN_APP_SECRET", "")
    missing = [k for k, v in {
        "MAVEN_ORG_ID": org_id,
        "MAVEN_AGENT_ID": agent_id,
        "MAVEN_APP_ID": app_id,
        "MAVEN_APP_SECRET": app_secret,
    }.items() if not v]
    if missing:
        raise RuntimeError(f"Missing Maven env vars: {', '.join(missing)}")
    return MavenAGI(
        organization_id=org_id,
        agent_id=agent_id,
        app_id=app_id,
        app_secret=app_secret,
    )


def _call_maven_draft(
    *,
    conversation_id: str,
    subject: str,
    ticket_body: str,
    account_blob: str,
    stripe_context: str,
    conversation_history: str = "",
    log_callback: Optional[Callable[[str], None]] = None,
) -> str:
    """Initialize a Maven conversation and stream the reply. Returns full reply text."""

    def _log(msg: str) -> None:
        log.info(msg)
        if log_callback:
            log_callback(msg)

    client = _maven_client()
    cid_ref = f"hs-{conversation_id}"
    msg_ref = f"hs-{conversation_id}-msg-{int(time.time() * 1000)}"

    _log("Maven: initializing conversation")
    client.conversation.initialize(
        conversation_id=EntityIdBase(reference_id=cid_ref),
        subject=subject,
        messages=[],
    )

    transient: dict[str, str] = {
        "account_context": account_blob[:4000],
        "stripe_context": stripe_context[:1000],
    }
    if conversation_history:
        transient["conversation_history"] = conversation_history[:4000]

    _log("Maven: asking...")
    chunks: list[str] = []
    for event in client.conversation.ask_stream(
        conversation_id=cid_ref,
        conversation_message_id=EntityIdBase(reference_id=msg_ref),
        user_id=EntityIdBase(reference_id="support-pipeline"),
        text=ticket_body,
        transient_data=transient,
    ):
        if isinstance(event, StreamResponse_Text):
            chunks.append(event.contents)
        elif isinstance(event, StreamResponse_End) and event.error:
            raise ValueError(f"Maven stream error: {event.error}")

    reply = "".join(chunks).strip()
    if not reply:
        raise ValueError("Maven returned empty reply")
    _log(f"Maven: response received ({len(reply)} chars)")
    return reply


def process_maven_ticket_sync(
    conversation_id: str,
    customer_email: Optional[str] = None,
    *,
    is_reply: bool = False,
    log_callback: Optional[Callable[[str], None]] = None,
) -> dict[str, Any]:
    """Maven pipeline: triage → account → Stripe (optional) → Maven draft → Help Scout draft + note."""
    t0 = time.monotonic()
    cid = str(conversation_id).strip()

    def _log(msg: str) -> None:
        log.info(msg)
        if log_callback:
            log_callback(msg)

    out: dict[str, Any] = {
        "conversation_id": cid,
        "customer_email": customer_email or "",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "engine": "maven",
        "triage_success": False,
        "account_lookup_success": False,
        "stripe_enrichment_attempted": False,
        "stripe_enrichment_success": False,
        "stripe_platform": None,
        "multiple_subscribed": False,
        "emails_checked": [],
        "escalated": False,
        "escalate_reason": None,
        "needs_action": True,
        "auto_sendable": False,
        "confidence": "n/a (maven)",
        "referenced_policies": [],
        "do_not_send_reasons": [],
        "draft_created": False,
        "note_created": False,
        "helpscout_draft_id": None,
        "helpscout_note_id": None,
        "latency_ms": None,
        "draft_text": None,
        "reasoning": None,
        "product_prioritization": None,
        "error": None,
    }

    email_in = (customer_email or "").strip()

    try:
        # Step 1 — Triage
        if is_reply:
            _log("Triage: skipped (reply)")
        else:
            try:
                run_triage(conversation_ids=[cid], auto_apply=True, skip_unassigned_scan=True)
                out["triage_success"] = True
                _log("Triage: complete")
            except SystemExit as e:
                log.warning("run_triage sys.exit (%s) — check env", e.code)
            except Exception:
                log.exception("triage failed — continuing pipeline")
                _log("Triage: failed (continuing)")

        # Step 2 — Help Scout session
        app_id = os.getenv("HELPSCOUT_APP_ID")
        app_secret = os.getenv("HELPSCOUT_APP_SECRET")
        if not app_id or not app_secret:
            raise RuntimeError("HELPSCOUT_APP_ID / HELPSCOUT_APP_SECRET required.")

        token = get_access_token()
        session = requests.Session()
        session.headers.update({"Authorization": f"Bearer {token}"})

        convo = fetch_conversation(session, int(cid))
        cust = _customer_from_conversation(convo)
        hs_customer_id = cust.get("id")
        convo_email = (cust.get("email") or "").strip()
        email = email_in or convo_email
        out["customer_email"] = email
        existing_tags = _extract_tag_names(convo.get("tags", []))
        customer_name = _customer_display_name(cust)
        subject = convo.get("subject") or "(no subject)"

        if is_reply:
            conversation_history, body = get_conversation_history(session, int(cid))
            body = body or "(empty)"
        else:
            conversation_history = ""
            body = get_conversation_text(session, int(cid)) or "(empty)"

        # Step 3 — Account lookup
        account_blob = ""
        try:
            hs_emails = fetch_customer_emails_from_helpscout(session, hs_customer_id) if hs_customer_id else []
            ctx = fetch_account_contexts_for_ticket(
                primary_email=email or None,
                ticket_text=body,
                extra_emails=hs_emails,
            )
            account_blob = ctx["combined_blob"]
            out["emails_checked"] = ctx["emails_checked"]
            out["multiple_subscribed"] = ctx["multiple_subscribed"]
            out["account_lookup_success"] = bool(account_blob.strip())
            _log(f"Account lookup: {email or '(unknown)'} — {'found' if out['account_lookup_success'] else 'not found'}")
        except Exception as e:
            account_blob = f"Account lookup failed — {e}"
            out["account_lookup_success"] = False
            _log(f"Account lookup: failed ({e})")
            log.exception("account_context failed")

        # Step 4 — Stripe enrichment (Stripe + gift only)
        platform = _subscription_platform(account_blob)
        out["stripe_platform"] = platform
        stripe_block = ""

        if (platform and platform.lower() == "stripe") or ("gift-subscription" in existing_tags):
            out["stripe_enrichment_attempted"] = True
            try:
                stripe_ctx_dict = fetch_stripe_context(email) if email else None
                stripe_block = format_stripe_context(stripe_ctx_dict)
                out["stripe_enrichment_success"] = stripe_ctx_dict is not None
                _log("Stripe: enriched")
            except Exception as e:
                stripe_block = "Stripe data unavailable"
                out["stripe_enrichment_success"] = False
                _log(f"Stripe: failed ({e})")
                log.exception("Stripe enrichment failed")
        else:
            stripe_block = f"N/A — customer is on {platform or 'unknown'} (not Stripe web billing)"
            _log("Stripe: skipped")

        # Step 5 — Maven draft
        draft_reply = _call_maven_draft(
            conversation_id=cid,
            subject=subject,
            ticket_body=body,
            account_blob=account_blob,
            stripe_context=stripe_block,
            conversation_history=conversation_history,
            log_callback=log_callback,
        )
        out["draft_text"] = draft_reply

        # Step 6 — Tags
        tags_to_add = ["maven-draft", "technical"]
        try:
            _update_conversation_tags(session, cid, existing_tags, tags_to_add)
        except requests.RequestException:
            log.exception("Failed to update tags on conversation %s", cid)

        # Step 7 — Help Scout draft
        if hs_customer_id is None:
            log.error("No HS customer id — cannot create draft. Draft:\n%s", draft_reply[:8000])
        else:
            reply_url = f"{BASE_URL}/conversations/{cid}/reply"
            payload = {"customer": {"id": int(hs_customer_id)}, "text": draft_reply, "draft": True}
            try:
                r = _helpscout_post(session, reply_url, payload)
                r.raise_for_status()
                out["helpscout_draft_id"] = r.headers.get("Resource-ID") or r.headers.get("resource-id")
                out["draft_created"] = True
                _log("Help Scout: draft created")
            except requests.RequestException as e:
                log.exception("Help Scout draft failed: %s\nDraft:\n%s", e, draft_reply[:8000])
                _log(f"Help Scout: draft failed ({e})")

        # Step 8 — Internal note
        note_user_id = os.getenv("HELPSCOUT_NOTE_USER_ID", "").strip()
        if note_user_id:
            note_html = (
                "<p><strong>🤖 Maven AGI Draft</strong></p><hr/>"
                f"<p>Draft generated by Maven AGI.<br/>"
                f"Conversation ref: hs-{cid}<br/>"
                f"Customer: {_html_escape(email or '(unknown)')}</p>"
                "<p><strong>Needs Action:</strong> Yes<br/>"
                "<strong>Auto-Sendable:</strong> No</p>"
            )
            note_url = f"{BASE_URL}/conversations/{cid}/notes"
            try:
                r2 = _helpscout_post(session, note_url, {"text": note_html, "user": int(note_user_id)})
                r2.raise_for_status()
                out["helpscout_note_id"] = r2.headers.get("Resource-ID") or r2.headers.get("resource-id")
                out["note_created"] = True
                _log("Help Scout: note created")
            except requests.RequestException:
                log.exception("Help Scout note failed")

        # Step 9 — Product prioritization
        pp = run_product_prioritization(
            ticket_subject=subject, ticket_body=body, tags=existing_tags, conversation_id=cid,
        )
        out["product_prioritization"] = pp
        if not pp.get("skipped"):
            log.info("product_prioritization: %s", pp)

        out["latency_ms"] = int((time.monotonic() - t0) * 1000)
        _log("Done")
        log.info("%s", {k: out[k] for k in out if k != "draft_text"})
        return out

    except Exception as e:
        out["error"] = str(e)
        out["latency_ms"] = int((time.monotonic() - t0) * 1000)
        _log(f"Error: {e}")
        log.exception("process_maven_ticket_sync failed: %s", e)
        raise
