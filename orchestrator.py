#!/usr/bin/env python3
"""Support pipeline: triage → account → Stripe (optional) → policies → Claude draft → Help Scout."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import re
import sys
import time
from datetime import datetime, timezone
from typing import Any

import anthropic
import requests
from dotenv import load_dotenv

_SUPPORT_DIR = os.path.dirname(os.path.abspath(__file__))
_ROOT_DIR = os.path.dirname(_SUPPORT_DIR)
load_dotenv(os.path.join(_SUPPORT_DIR, ".env"))
load_dotenv(os.path.join(_ROOT_DIR, ".env"))

import bug_registry  # noqa: E402
import draft_registry  # noqa: E402
import notion_bridge  # noqa: E402
from account_context import fetch_account_contexts_for_ticket, fetch_customer_emails_from_helpscout  # noqa: E402
from action_executor import format_actions_note  # noqa: E402
from product_prioritization import run_product_prioritization  # noqa: E402
from research_agent import detect_platform, run_research, should_research  # noqa: E402
from stripe_context import fetch_stripe_context, format_stripe_context  # noqa: E402
from triage_tickets import (  # noqa: E402
    BASE_URL,
    api_get,
    fetch_conversation,
    get_access_token,
    get_conversation_history,
    get_conversation_text,
    run_triage,
)

log = logging.getLogger("support_orchestrator")

DRAFT_SYSTEM_PROMPT_PATH = os.path.join(_SUPPORT_DIR, "prompts", "draft_system_prompt.txt")
DEFAULT_CLAUDE_MODEL = "claude-sonnet-5"

DRAFT_JSON_RETRY_USER_SUFFIX = """

IMPORTANT — your last reply was empty or not valid JSON for this pipeline.

Reply with ONLY one JSON object (no markdown fences, no commentary before or after).
Required keys: draft_reply, escalate, escalate_reason, needs_action, action_description,
action_items, action_system, auto_sendable, do_not_send_reasons, referenced_policies, confidence,
reasoning, open_question, needs_product_research, bug_report.
action_items must be an array of short action strings (empty array when needs_action is false).
Use null for action_description and action_system when needs_action is false.
Use null for escalate_reason when escalate is false.
Use null for draft_reply when escalate is true.
Use null for open_question when there is no unanswered policy question.
bug_report must be an object: {"is_bug": bool, "matches_known_bug": string|null, "new_bug_summary": string|null}.
If you must shorten draft_reply to fit, keep JSON valid and closed."""

ACTION_DESCRIPTION_RETRY_USER_SUFFIX = (
    "\n\nYour JSON set needs_action=true but action_description was null/empty. "
    "Re-send the SAME JSON with a specific, executable action_description (and action_system)."
)


def needs_action_retry(parsed: dict) -> bool:
    """True iff the draft JSON claims an action is needed but gave no description for it."""
    return bool(parsed.get("needs_action")) and not (parsed.get("action_description") or "").strip()


def should_post_note(is_escalation: bool, parsed: dict) -> bool:
    """Internal note posts for escalations and for any ticket needing manual action."""
    return bool(is_escalation or parsed.get("needs_action"))


def compute_tags(parsed: dict) -> list[str]:
    """Derive Help Scout conversation tags from classification output.

    `parsed` carries (at least) `escalate`, `auto_sendable`, and `confidence` —
    either the raw Claude classification dict or the equivalent post-escalation
    `out` fields.
    """
    tags: list[str] = []
    if parsed.get("escalate"):
        tags.append("escalation")
    tags.append("automated" if parsed.get("auto_sendable") else "technical")
    if parsed.get("auto_sendable") and parsed.get("confidence") != "low":
        tags.append("auto_send")
    conf = (parsed.get("confidence") or "").strip().lower()
    if conf in ("high", "medium", "low"):
        tags.append(f"confidence-{conf}")
    return tags


_ACTION_SYSTEM_MAP = {
    "stripe": "Stripe",
    "happier_admin": "Happier admin",
    "helpscout": "Help Scout",
}


def _map_action_system(raw: Any) -> str:
    """Map the draft JSON's action_system value onto the exact Notion select options."""
    key = (raw or "").strip().lower()
    return _ACTION_SYSTEM_MAP.get(key, "Other")


def record_gap_and_action(out: dict, parsed: dict) -> None:
    """Fail-soft hook: record an open policy gap and/or a manual action in Notion.

    Never raises — a Notion outage or missing NOTION_TOKEN must never block a draft.
    Each branch (gap, action) is independently wrapped so a failure in one doesn't
    suppress the other.
    """
    ticket_id = out.get("conversation_id")
    ticket_subject = out.get("ticket_subject")
    customer_email = out.get("customer_email")

    open_question = (parsed.get("open_question") or "").strip()
    confidence = (parsed.get("confidence") or "").strip().lower()
    if not open_question and confidence == "low":
        open_question = f"How should we answer: {ticket_subject}?"

    if open_question:
        try:
            notion_bridge.upsert_gap(open_question, ticket_id, ticket_subject)
        except Exception:
            log.exception("record_gap_and_action: upsert_gap failed for conversation %s", ticket_id)

    if parsed.get("needs_action"):
        try:
            action_description = (parsed.get("action_description") or "").strip() or "Unspecified — see reasoning"
            action_system = _map_action_system(parsed.get("action_system"))
            confidence_display = confidence.capitalize() if confidence else confidence
            notion_bridge.upsert_action(
                action_description,
                action_system,
                ticket_id,
                customer_email,
                confidence_display,
            )
        except Exception:
            log.exception("record_gap_and_action: upsert_action failed for conversation %s", ticket_id)


def load_policy_docs(policy_dir: str | None = None) -> str:
    """Read all .md files from the policies directory and concatenate them."""
    base = policy_dir or os.path.join(_SUPPORT_DIR, "policies")
    if not os.path.isdir(base):
        raise FileNotFoundError(f"policies directory missing: {base}")
    docs: list[str] = []
    for filename in sorted(os.listdir(base)):
        if not filename.endswith(".md"):
            continue
        path = os.path.join(base, filename)
        if os.path.isfile(path):
            with open(path, encoding="utf-8") as f:
                content = f.read()
            docs.append(f"--- POLICY DOC: {filename} ---\n{content}")
    if not docs:
        raise ValueError(f"No .md policy files in {base}")
    return "\n\n".join(docs)


def _load_system_prompt() -> str:
    with open(DRAFT_SYSTEM_PROMPT_PATH, encoding="utf-8") as f:
        return f.read()


def _subscription_platform(account_blob: str) -> str | None:
    for line in (account_blob or "").splitlines():
        stripped = line.strip()
        if stripped.lower().startswith("subscription platform:"):
            return stripped.split(":", 1)[1].strip()
    return None


def _customer_from_conversation(convo: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(convo, dict):
        return {}
    for key in ("primaryCustomer", "customer"):
        c = convo.get(key)
        if isinstance(c, dict) and c.get("id") is not None:
            return c
    emb = convo.get("_embedded") or {}
    for key in ("primaryCustomer", "customer"):
        c = emb.get(key)
        if isinstance(c, dict) and c.get("id") is not None:
            return c
    return {}


def _customer_display_name(customer: dict[str, Any]) -> str:
    fn = (customer.get("firstName") or customer.get("first") or "").strip()
    ln = (customer.get("lastName") or customer.get("last") or "").strip()
    if fn and ln:
        return f"{fn} {ln}"
    return fn or ln or "there"


def _helpscout_post(session: requests.Session, url: str, json_body: dict, *, retries_on_5xx: int = 1):
    attempt = 0
    while True:
        resp = session.post(url, json=json_body)
        if resp.status_code == 429:
            retry_after = int(resp.headers.get("Retry-After", 10))
            log.warning("Help Scout rate limited — sleeping %ss", retry_after)
            time.sleep(retry_after)
            continue
        if 500 <= resp.status_code < 600 and attempt < retries_on_5xx:
            attempt += 1
            log.warning("Help Scout 5xx — retry %s/%s", attempt, retries_on_5xx)
            time.sleep(1)
            continue
        return resp


def _helpscout_patch_thread_text(session: requests.Session, cid: str, thread_id: str, text: str):
    """Edit an existing draft thread's text IN PLACE via Help Scout PATCH.

    The working request body is a SINGLE JSON-Patch object (not an array):
    {"op": "replace", "path": "/text", "value": "..."} → HTTP 204. Mirrors
    ``bert.pipeline.update_draft``; implemented here (rather than imported) to
    avoid a circular import, since ``bert`` imports ``orchestrator``. Used to
    refresh a stale draft against the newest customer message without stacking
    a duplicate (Help Scout has no DELETE for draft threads).
    """
    url = f"{BASE_URL}/conversations/{int(cid)}/threads/{int(thread_id)}"
    body = {"op": "replace", "path": "/text", "value": text}
    resp = session.patch(url, json=body)
    resp.raise_for_status()
    return resp


def _customer_replied_after_draft(threads: list, draft_thread_id: str) -> bool | None:
    """Has the customer replied since we recorded draft `draft_thread_id`?

    Returns True if any customer thread is newer (by `createdAt`) than the draft
    thread, False if the draft is still the latest customer-facing activity, and
    None if the recorded draft thread is not present in the conversation (a stale
    registry entry — the caller preserves today's skip behavior in that case).

    `createdAt` values are ISO-8601 UTC strings, which sort lexicographically;
    threads missing `createdAt` are ignored rather than crashing the comparison.
    """
    draft_created_at = None
    for t in threads or []:
        if str(t.get("id")) == str(draft_thread_id):
            draft_created_at = t.get("createdAt")
            break
    if draft_created_at is None:
        return None
    for t in threads or []:
        if t.get("type") != "customer":
            continue
        created = t.get("createdAt")
        if created and created > draft_created_at:
            return True
    return False


def _assistant_text_from_message(message: Any) -> str:
    """Concatenate all text blocks (handles multi-block responses and empty first blocks)."""
    parts: list[str] = []
    for block in getattr(message, "content", None) or []:
        t = getattr(block, "text", None)
        if isinstance(t, str) and t:
            parts.append(t)
    return "".join(parts).strip()


def _parse_claude_json(text: str) -> dict[str, Any]:
    response_text = (text or "").strip()
    if not response_text:
        raise json.JSONDecodeError("empty assistant text", response_text, 0)

    if response_text.startswith("```"):
        response_text = re.sub(r"^```(?:json)?\s*", "", response_text)
        response_text = re.sub(r"\s*```$", "", response_text).strip()

    try:
        return json.loads(response_text)
    except json.JSONDecodeError:
        pass

    # Leading prose, e.g. "Here is the JSON:\n{ ... "
    brace = response_text.find("{")
    if brace >= 0:
        tail = response_text[brace:]
        try:
            return json.loads(tail)
        except json.JSONDecodeError:
            pass
        end = tail.rfind("}")
        if end > 0:
            return json.loads(tail[: end + 1])

    raise json.JSONDecodeError("could not parse JSON object", response_text, 0)


def _should_retry_claude(err: BaseException) -> bool:
    """Retry once on timeouts, rate limits, and server errors."""
    return isinstance(
        err,
        (
            anthropic.APIConnectionError,
            anthropic.APITimeoutError,
            anthropic.RateLimitError,
            anthropic.InternalServerError,
        ),
    )


def _call_claude_draft(
    client: anthropic.Anthropic,
    *,
    system_prompt: str,
    policy_docs: str,
    dynamic_user_message: str,
    model: str,
) -> tuple[Any, dict[str, Any], str]:
    """Returns (message, parsed_json, raw_assistant_text)."""
    system_blocks = [
        {
            "type": "text",
            "text": system_prompt,
            "cache_control": {"type": "ephemeral"},
        }
    ]

    def _user_content(retry: bool) -> list[dict]:
        dynamic = dynamic_user_message.strip() + (DRAFT_JSON_RETRY_USER_SUFFIX if retry else "")
        return [
            {
                "type": "text",
                "text": f"=== POLICY DOCUMENTS ===\n{policy_docs}\n",
                "cache_control": {"type": "ephemeral"},
            },
            {
                "type": "text",
                "text": dynamic,
            },
        ]

    last_json_err: json.JSONDecodeError | None = None
    last_api_err: BaseException | None = None
    last_raw_text = ""

    for variant_idx in range(2):
        if variant_idx == 1:
            log.info("Retrying Claude draft with strict JSON-only user suffix")
        for api_attempt in range(2):
            try:
                message = client.messages.create(
                    model=model,
                    max_tokens=16000,
                    system=system_blocks,
                    messages=[{"role": "user", "content": _user_content(variant_idx == 1)}],
                )
                text = _assistant_text_from_message(message)
                last_raw_text = text
                if not text:
                    stop = getattr(message, "stop_reason", None)
                    log.warning(
                        "Claude returned empty text (variant=%s api_attempt=%s stop_reason=%s)",
                        variant_idx,
                        api_attempt,
                        stop,
                    )
                    raise json.JSONDecodeError("empty assistant text", "", 0)

                parsed = _parse_claude_json(text)
                return message, parsed, text

            except json.JSONDecodeError as e:
                last_json_err = e
                log.warning(
                    "Claude draft JSON parse failed (variant=%s): %s; preview=%r",
                    variant_idx,
                    e,
                    last_raw_text[:400],
                )
                break

            except anthropic.AnthropicError as e:
                last_api_err = e
                if api_attempt == 0 and _should_retry_claude(e):
                    log.warning("Claude API error, retrying once: %s", e)
                    time.sleep(0.75)
                    continue
                raise

    detail = repr(last_raw_text[:800]) if last_raw_text else "(empty)"
    raise ValueError(
        f"Claude did not return parseable draft JSON after retries. Last parse error: {last_json_err}. "
        f"Raw preview: {detail}"
    ) from (last_json_err or last_api_err)


def _call_claude_draft_with_action_retry(
    client: anthropic.Anthropic,
    *,
    system_prompt: str,
    policy_docs: str,
    dynamic_user_message: str,
    model: str,
) -> tuple[Any, dict[str, Any], str]:
    """Wraps _call_claude_draft with a one-time corrective retry when needs_action=true
    but action_description came back null/empty. On persistent failure, keeps the result
    and flags it via the caller (see action_description_missing in process_ticket_sync)."""
    message, parsed, raw_text = _call_claude_draft(
        client,
        system_prompt=system_prompt,
        policy_docs=policy_docs,
        dynamic_user_message=dynamic_user_message,
        model=model,
    )

    if needs_action_retry(parsed):
        log.warning(
            "Draft JSON has needs_action=true with missing action_description — retrying once"
        )
        retry_message = dynamic_user_message.strip() + ACTION_DESCRIPTION_RETRY_USER_SUFFIX
        message, parsed, raw_text = _call_claude_draft(
            client,
            system_prompt=system_prompt,
            policy_docs=policy_docs,
            dynamic_user_message=retry_message,
            model=model,
        )
        if needs_action_retry(parsed):
            log.warning(
                "action_description still missing after corrective retry — keeping result and flagging"
            )

    return message, parsed, raw_text


def _build_dynamic_user_message(
    *,
    ticket_subject: str,
    ticket_body: str,
    customer_name: str,
    customer_email: str,
    account_blob: str,
    stripe_context: str,
    agent_name: str,
    conversation_history: str = "",
) -> str:
    today = datetime.now(timezone.utc).strftime("%B %d, %Y")
    is_reply = bool(conversation_history)

    history_section = (
        f"\n=== CONVERSATION HISTORY ===\n{conversation_history}\n"
        if is_reply
        else ""
    )
    instruction = (
        "This is a follow-up in an ongoing conversation. Use the conversation history above for context, "
        f"but respond to the latest customer message only. Sign off as {agent_name}."
        if is_reply
        else f"Draft a reply to this ticket. Sign off as {agent_name}."
    )

    return f"""
=== CUSTOMER ACCOUNT DATA ===
Today's Date: {today}
Customer Name: {customer_name}
Customer Email: {customer_email}

{account_blob}

{stripe_context}
{history_section}
=== TICKET ===
Subject: {ticket_subject}

{ticket_body}

=== INSTRUCTIONS ===
{instruction} Respond with the JSON object specified in your instructions.
"""


def _format_internal_note_html(
    *,
    parsed: dict[str, Any],
    stripe_lines_for_note: str,
    stripe_ctx: dict[str, Any] | None = None,
    research_ran: bool = False,
    research_sources: list[str] | None = None,
    supersedes_existing_draft: bool = False,
) -> str:
    supersede_html = (
        "<p style='color:#b45309'><strong>"
        "⚠️ Supersedes the earlier draft — discard the old one."
        "</strong></p>"
        if supersedes_existing_draft
        else ""
    )
    actions_html = ""
    try:
        actions_html = format_actions_note(parsed, stripe_ctx)
    except Exception:
        log.exception("format_actions_note failed — omitting actions-needed section from note")

    escalate = bool(parsed.get("escalate"))
    escalate_reason = parsed.get("escalate_reason")
    needs_action = parsed.get("needs_action")
    auto_sendable = parsed.get("auto_sendable")
    confidence = parsed.get("confidence", "")
    reasoning = parsed.get("reasoning", "")
    action_desc = parsed.get("action_description")
    policies = parsed.get("referenced_policies") or []
    flags = parsed.get("do_not_send_reasons") or []

    def yn(val: Any) -> str:
        return "Yes" if val else "No"

    pol_lines = "".join(f"<li>{_html_escape(str(p))}</li>" for p in policies)
    flag_lines = "".join(f"<li>{_html_escape(str(f))}</li>" for f in flags) or "<li>None</li>"
    action_html = (
        f"<p><strong>Action description:</strong> {_html_escape(str(action_desc))}</p>"
        if action_desc
        else ""
    )
    escalation_html = (
        f"<p style='color:red'><strong>ESCALATION — no draft created.</strong><br/>"
        f"Reason: {_html_escape(str(escalate_reason or '(see reasoning)'))}</p>"
        if escalate
        else ""
    )

    research_html = ""
    if research_ran:
        srcs = research_sources or []
        src_items = "".join(f"<li>{_html_escape(str(s))}</li>" for s in srcs) or "<li>(none)</li>"
        research_html = (
            "<p><strong>Research:</strong> codebase + Linear investigation informed this draft."
            f"</p><ul>{src_items}</ul>"
        )

    return (
        f"{supersede_html}"
        f"{actions_html}"
        "<p><strong>🤖 AI Draft Classification</strong></p>"
        "<hr/>"
        f"{escalation_html}"
        f"{research_html}"
        f"<p><strong>Escalation:</strong> {yn(escalate)}<br/>"
        f"<strong>Action Required:</strong> {yn(needs_action)}<br/>"
        f"<strong>Auto-Sendable:</strong> {yn(auto_sendable)}<br/>"
        f"<strong>Confidence:</strong> {_html_escape(str(confidence))}</p>"
        f"{action_html}"
        f"<p><strong>Reasoning:</strong> {_html_escape(str(reasoning))}</p>"
        "<p><strong>Policies Referenced:</strong></p>"
        f"<ul>{pol_lines}</ul>"
        "<p><strong>Do Not Auto-Send Flags:</strong></p>"
        f"<ul>{flag_lines}</ul>"
        "<p><strong>Stripe Pricing Context:</strong><br/>"
        f"{stripe_lines_for_note}</p>"
    )


def _extract_tag_names(tags_field: list) -> list[str]:
    names = []
    for t in tags_field or []:
        if isinstance(t, dict):
            names.append(t.get("tag") or t.get("name") or "")
        else:
            names.append(str(t))
    return [n for n in names if n]


def _update_conversation_tags(session: requests.Session, cid: str, existing_tags: list[str], tags_to_add: list[str]) -> None:
    current = list(existing_tags)
    for tag in tags_to_add:
        if tag not in current:
            current.append(tag)
    if current == existing_tags:
        return
    resp = session.put(f"{BASE_URL}/conversations/{cid}/tags", json={"tags": current})
    resp.raise_for_status()


def _html_escape(s: str) -> str:
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


REPLY_MODE_PROMPT_PREFIX = (
    "NOTE: This is an ongoing thread — a support agent has already replied at least once. "
    "Respond to the customer's LATEST message only; do not re-answer the original question. "
    "Full thread history follows."
)


def detect_reply_mode(threads: list) -> bool:
    """True iff a support agent has already sent a published reply."""
    for t in threads or []:
        if t.get("type") == "message" and t.get("state") == "published":
            return True
    return False


def _fetch_conversation_threads(session: requests.Session, convo: dict[str, Any], conversation_id: int) -> list[dict]:
    """Return the conversation's threads, reusing `_embedded.threads` if `fetch_conversation`
    already embedded them; otherwise fetch via GET /conversations/{id}/threads (paginated).

    Only a NON-EMPTY embed is trusted: Help Scout's GET /conversations/{id} returns
    `_embedded: {"threads": []}` even for conversations with real thread history
    (observed live 2026-07-02), so an empty embed means "not included", not "no threads"."""
    embedded = (convo or {}).get("_embedded") or {}
    embedded_threads = embedded.get("threads")
    if embedded_threads:
        return embedded_threads

    threads: list[dict] = []
    page = 1
    while True:
        data = api_get(
            session,
            f"{BASE_URL}/conversations/{conversation_id}/threads",
            params={"page": page},
        )
        page_threads = data.get("_embedded", {}).get("threads", [])
        threads.extend(page_threads)
        total_pages = data.get("page", {}).get("totalPages", 1)
        if page >= total_pages:
            break
        page += 1
    return threads


def process_ticket_sync(
    conversation_id: str,
    customer_email: str | None = None,
    *,
    is_reply: bool = False,
    skip_triage: bool = False,
    force: bool = False,
    create_draft: bool = True,
) -> dict[str, Any]:
    """
    Full pipeline: triage → account lookup → stripe enrichment → policy retrieval →
    Claude draft → Help Scout draft + note.

    Returns dict with draft_text, needs_action, reasoning, referenced_policies,
    helpscout_draft_id, helpscout_note_id, plus telemetry fields.

    `force`: when True, bypass the draft registry's duplicate-draft guard even
    outside reply mode — used for deliberate manual re-drafts. See
    draft_registry.should_skip_draft for the skip/supersede decision table.

    `create_draft`: when False (eval dry-run mode, SUP-459), the pipeline still
    runs the read path — conversation fetch, reply-mode detection, triage-skip
    logic, account/Stripe enrichment, and the Claude draft call — so the
    classification JSON is real, but performs NO external writes anywhere:
      - no Help Scout draft POST, internal-note POST, or tag PUT;
      - no draft-registry write;
      - no Notion gap/action hooks;
      - no bug-registry hook (which can auto-file Linear issues);
      - no product-prioritization pass (which can post Linear comments);
      - triage is skipped outright (run_triage auto-applies tags/teams,
        which are Help Scout writes).
    The two-pass research step is also skipped in dry-run to save cost — a
    dry-run classification therefore reflects the FIRST draft only, without
    the research re-draft low-confidence tickets would get in production.
    In dry-run, `draft_created=True` means "a draft WOULD have been posted"
    (non-escalated, non-empty draft text, customer id present);
    `helpscout_draft_id` stays None and the draft registry is not updated.
    """
    t0 = time.monotonic()
    cid = str(conversation_id).strip()
    out: dict[str, Any] = {
        "conversation_id": cid,
        "customer_email": customer_email or "",
        "ticket_subject": None,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "triage_success": False,
        "reply_mode": False,
        "account_lookup_success": False,
        "stripe_enrichment_attempted": False,
        "stripe_enrichment_success": False,
        "stripe_platform": None,
        "multiple_subscribed": False,
        "emails_checked": [],
        "claude_model": os.getenv("CLAUDE_DRAFT_MODEL", DEFAULT_CLAUDE_MODEL),
        "escalated": False,
        "escalate_reason": None,
        "needs_action": None,
        "action_description": None,
        "action_system": None,
        "action_description_missing": False,
        "auto_sendable": None,
        "confidence": None,
        "referenced_policies": [],
        "do_not_send_reasons": [],
        "open_question": None,
        "needs_product_research": None,
        "bug_report": None,
        "bug_candidate": None,
        "research_ran": False,
        "research_sources": [],
        "draft_created": False,
        "draft_updated_in_place": False,
        "skipped_existing_draft": False,
        "supersedes_existing_draft": False,
        "note_created": False,
        "helpscout_draft_id": None,
        "helpscout_note_id": None,
        "total_input_tokens": None,
        "total_output_tokens": None,
        "cache_read_input_tokens": None,
        "dry_run": not create_draft,
        "latency_ms": None,
        "draft_text": None,
        "reasoning": None,
        "product_prioritization": None,
        "error": None,
    }

    email_in = (customer_email or "").strip()

    if is_reply:
        log.warning(
            "process_ticket_sync(is_reply=True) is deprecated — reply mode is now derived "
            "from conversation threads. The passed value is ignored."
        )

    try:
        app_id = os.getenv("HELPSCOUT_APP_ID")
        app_secret = os.getenv("HELPSCOUT_APP_SECRET")
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not app_id or not app_secret:
            raise RuntimeError("HELPSCOUT_APP_ID / HELPSCOUT_APP_SECRET required for Help Scout API.")
        if not api_key:
            raise RuntimeError("ANTHROPIC_API_KEY required for draft generation.")

        token = get_access_token()
        session = requests.Session()
        session.headers.update({"Authorization": f"Bearer {token}"})

        convo = fetch_conversation(session, int(cid))
        threads = _fetch_conversation_threads(session, convo, int(cid))
        reply_mode = detect_reply_mode(threads)
        out["reply_mode"] = reply_mode

        existing_draft = draft_registry.get(cid)
        existing_draft_thread_id = (existing_draft or {}).get("thread_id")
        # A customer follow-up before any agent reply leaves reply_mode False; without
        # this staleness check the pipeline would skip and freeze the draft on the
        # earlier message. Scoped to the pure follow-up case (not reply_mode, not
        # force) so it never diverts those from their existing supersede path.
        stale_redraft = (
            bool(existing_draft)
            and not reply_mode
            and not force
            and _customer_replied_after_draft(threads, existing_draft_thread_id) is True
        )
        if draft_registry.should_skip_draft(existing_draft, reply_mode, force, draft_is_stale=stale_redraft):
            log.info(
                "Skipping draft for conversation %s — existing draft thread %s already recorded "
                "(not reply_mode, not forced, no newer customer reply)",
                cid,
                existing_draft_thread_id,
            )
            out["skipped_existing_draft"] = True
            out["latency_ms"] = int((time.monotonic() - t0) * 1000)
            log.info("%s", json.dumps({k: out[k] for k in out if k != "draft_text"}, default=str))
            return out

        if stale_redraft:
            log.info(
                "Refreshing stale draft for conversation %s — customer replied after draft thread %s; "
                "updating it in place against the latest message",
                cid,
                existing_draft_thread_id,
            )

        supersedes_existing_draft = bool(existing_draft) and (reply_mode or force)

        if reply_mode or skip_triage or not create_draft:
            if not create_draft and not (reply_mode or skip_triage):
                log.info(
                    "Dry-run: skipping triage for conversation %s (run_triage auto-applies "
                    "tags/teams — external Help Scout writes)",
                    cid,
                )
            else:
                log.info("Skipping triage for conversation %s", cid)
        else:
            try:
                run_triage(
                    conversation_ids=[cid],
                    auto_apply=True,
                    skip_unassigned_scan=True,
                )
                out["triage_success"] = True
            except SystemExit as e:
                log.warning("run_triage called sys.exit (%s) — check Help Scout / Anthropic env", e.code)
            except Exception:
                log.exception("triage failed — continuing pipeline")

        cust = _customer_from_conversation(convo)
        hs_customer_id = cust.get("id")
        convo_email = (cust.get("email") or "").strip()
        email = email_in or convo_email
        out["customer_email"] = email
        existing_tags = _extract_tag_names(convo.get("tags", []))

        customer_name = _customer_display_name(cust)
        subject = convo.get("subject") or "(no subject)"
        out["ticket_subject"] = subject

        if reply_mode:
            conversation_history, body = get_conversation_history(session, int(cid), threads=threads)
            body = body or "(empty)"
        else:
            conversation_history = ""
            body = get_conversation_text(session, int(cid), threads=threads) or "(empty)"

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
            if ctx["multiple_subscribed"]:
                log.warning(
                    "ESCALATION: multiple subscribed accounts found for ticket %s — emails: %s",
                    cid,
                    ctx["emails_checked"],
                )
            if not account_blob.strip():
                account_blob = (
                    "Account lookup failed — could not retrieve customer data "
                    "(missing customer email or empty response)."
                )
                out["account_lookup_success"] = False
            else:
                out["account_lookup_success"] = True
        except Exception as e:
            account_blob = f"Account lookup failed — could not retrieve customer data ({e})"
            out["account_lookup_success"] = False
            log.exception("account_context failed")

        platform = _subscription_platform(account_blob)
        out["stripe_platform"] = platform
        stripe_ctx_dict: dict[str, Any] | None = None
        stripe_block_for_prompt = ""
        stripe_note_block = ""

        is_stripe_platform = platform and platform.lower() == "stripe"
        is_gift_ticket = "gift-subscription" in existing_tags
        if is_stripe_platform or is_gift_ticket:
            out["stripe_enrichment_attempted"] = True
            try:
                stripe_ctx_dict = fetch_stripe_context(email) if email else None
                stripe_block_for_prompt = format_stripe_context(stripe_ctx_dict)
                out["stripe_enrichment_success"] = stripe_ctx_dict is not None
                stripe_note_block = stripe_block_for_prompt.replace("\n", "<br/>")
            except Exception:
                log.exception("Stripe enrichment failed")
                stripe_block_for_prompt = "Stripe data unavailable"
                stripe_note_block = _html_escape(stripe_block_for_prompt)
                out["stripe_enrichment_success"] = False
        else:
            plat_disp = platform if platform else "unknown"
            stripe_block_for_prompt = f"N/A — customer is on {plat_disp} (not Stripe web billing)"
            stripe_note_block = _html_escape(stripe_block_for_prompt)

        policy_docs = load_policy_docs()
        system_prompt = _load_system_prompt()
        agent_name = os.getenv("SUPPORT_AGENT_SIGNOFF_NAME", "Happier Meditation Support")

        dynamic_message = _build_dynamic_user_message(
            ticket_subject=subject,
            ticket_body=body,
            customer_name=customer_name,
            customer_email=email or "(unknown)",
            account_blob=account_blob,
            stripe_context=stripe_block_for_prompt,
            agent_name=agent_name,
            conversation_history=conversation_history,
        )
        if reply_mode:
            dynamic_message = f"{REPLY_MODE_PROMPT_PREFIX}\n\n{dynamic_message}"

        client = anthropic.Anthropic(api_key=api_key)
        model = out["claude_model"]
        msg, parsed, _raw_assistant = _call_claude_draft_with_action_retry(
            client,
            system_prompt=system_prompt,
            policy_docs=policy_docs,
            dynamic_user_message=dynamic_message,
            model=model,
        )

        # --- Two-pass research (fail-soft): if the first draft is low-confidence,
        # cited no policy, or flagged a product question, investigate the
        # codebases + Linear and re-draft with findings appended. Any research
        # exception or empty findings → keep the first draft untouched.
        # Skipped entirely in dry-run (create_draft=False) to save cost.
        if not create_draft:
            if should_research(parsed):
                log.info("Dry-run: skipping research pass for conversation %s (cost saving)", cid)
        elif should_research(parsed):
            try:
                research = run_research(
                    ticket_text=f"Subject: {subject}\n\n{body}",
                    account_summary=account_blob,
                    platform_hint=detect_platform(body, {"platform": platform}),
                )
            except Exception:
                log.exception("run_research raised (should be fail-soft) — keeping first draft")
                research = {"findings": "", "sources": [], "tool_calls": 0}

            findings = (research.get("findings") or "").strip()
            if findings:
                sources = research.get("sources") or []
                log.info(
                    "Research ran for conversation %s: %s tool calls, %s sources",
                    cid,
                    research.get("tool_calls"),
                    len(sources),
                )
                research_block = (
                    "\n\n=== RESEARCH FINDINGS (internal, do not quote code to customer) ===\n"
                    f"{findings}\n"
                    f"SOURCES: {sources}\n"
                )
                try:
                    msg, parsed, _raw_assistant = _call_claude_draft_with_action_retry(
                        client,
                        system_prompt=system_prompt,
                        policy_docs=policy_docs,
                        dynamic_user_message=dynamic_message + research_block,
                        model=model,
                    )
                    out["research_ran"] = True
                    out["research_sources"] = sources
                except Exception:
                    # Re-draft failed — fall back to the first draft/parse.
                    log.exception("Research re-draft failed — keeping first draft for conversation %s", cid)
            else:
                log.info("Research produced no findings for conversation %s — keeping first draft", cid)

        usage = getattr(msg, "usage", None)
        if usage:
            out["total_input_tokens"] = getattr(usage, "input_tokens", None)
            out["total_output_tokens"] = getattr(usage, "output_tokens", None)
            out["cache_read_input_tokens"] = getattr(usage, "cache_read_input_tokens", None)

        draft_reply = parsed.get("draft_reply") or ""
        out["draft_text"] = draft_reply
        is_escalation = bool(parsed.get("escalate")) or out["multiple_subscribed"]
        out["escalated"] = is_escalation
        out["escalate_reason"] = parsed.get("escalate_reason")
        out["needs_action"] = True if (is_escalation or out["multiple_subscribed"]) else bool(parsed.get("needs_action"))
        out["auto_sendable"] = False if (is_escalation or out["multiple_subscribed"]) else bool(parsed.get("auto_sendable"))
        out["confidence"] = parsed.get("confidence")
        out["referenced_policies"] = parsed.get("referenced_policies") or []
        out["do_not_send_reasons"] = parsed.get("do_not_send_reasons") or []
        out["reasoning"] = parsed.get("reasoning")
        out["action_description"] = parsed.get("action_description")
        out["action_system"] = parsed.get("action_system")
        out["open_question"] = parsed.get("open_question")
        out["needs_product_research"] = parsed.get("needs_product_research")
        out["bug_report"] = parsed.get("bug_report")
        if needs_action_retry(parsed):
            out["action_description_missing"] = True
            log.warning(
                "action_description_missing=True for conversation %s (needs_action=true, no description after retry)",
                cid,
            )

        # --- Tags (single PUT to avoid clobbering; skipped in dry-run) ---
        tags_to_add = compute_tags(
            {"escalate": is_escalation, "auto_sendable": out["auto_sendable"], "confidence": out["confidence"]}
        )
        if create_draft:
            try:
                _update_conversation_tags(session, cid, existing_tags, tags_to_add)
                log.info("Tags updated for conversation %s: added %s", cid, tags_to_add)
            except requests.RequestException:
                log.exception("Failed to update tags on conversation %s", cid)
        else:
            log.info("Dry-run: would have added tags %s to conversation %s", tags_to_add, cid)

        # --- Draft reply ---
        if is_escalation:
            log.info(
                "Escalation: skipping draft reply for conversation %s. Reason: %s",
                cid,
                out["escalate_reason"] or "(multiple subscribed accounts)" if out["multiple_subscribed"] else out["escalate_reason"],
            )
        elif hs_customer_id is None:
            log.error(
                "No Help Scout customer id on conversation — cannot create draft. Draft text logged below.\n%s",
                draft_reply[:8000],
            )
        elif not create_draft:
            # Dry-run: no Help Scout POST, no draft-registry write. draft_created=True
            # records that a draft WOULD have been posted (real classification JSON).
            if draft_reply:
                out["draft_created"] = True
                out["supersedes_existing_draft"] = supersedes_existing_draft
            log.info(
                "Dry-run: skipping Help Scout draft POST for conversation %s (draft length %s)",
                cid,
                len(draft_reply),
            )
        elif stale_redraft and existing_draft_thread_id:
            # Customer replied after our draft: refresh the SAME thread in place so
            # it answers the newest message, without stacking a duplicate draft
            # (Help Scout has no DELETE for draft threads).
            try:
                _helpscout_patch_thread_text(session, cid, existing_draft_thread_id, draft_reply)
                out["helpscout_draft_id"] = existing_draft_thread_id
                out["draft_created"] = True
                out["draft_updated_in_place"] = True
                draft_registry.set(cid, existing_draft_thread_id, out["timestamp"])
            except requests.RequestException as e:
                log.exception(
                    "Help Scout draft in-place update failed — preserving draft in logs. Error: %s\nDraft:\n%s",
                    e,
                    draft_reply[:8000],
                )
        else:
            reply_url = f"{BASE_URL}/conversations/{cid}/reply"
            payload = {
                "customer": {"id": int(hs_customer_id)},
                "text": draft_reply,
                "draft": True,
            }
            try:
                r = _helpscout_post(session, reply_url, payload)
                r.raise_for_status()
                draft_rid = r.headers.get("Resource-ID") or r.headers.get("resource-id")
                out["helpscout_draft_id"] = draft_rid
                out["draft_created"] = True
                out["supersedes_existing_draft"] = supersedes_existing_draft
                if draft_rid:
                    draft_registry.set(cid, draft_rid, out["timestamp"])
            except requests.RequestException as e:
                log.exception(
                    "Help Scout draft reply failed — preserving draft in logs. Error: %s\nDraft:\n%s",
                    e,
                    draft_reply[:8000],
                )

        # --- Notion gap/action hooks (fail-soft; never blocks the draft;
        # skipped in dry-run — Notion page writes) ---
        if create_draft:
            record_gap_and_action(out, parsed)

        # --- Bug candidate registry / Linear auto-filing (fail-soft; never
        # blocks the draft; skipped in dry-run — registry write + potential
        # Linear issue creation). `out` has no ticket_body field — `body` is
        # the customer's ticket text already resolved above (reply-mode aware).
        if create_draft:
            try:
                excerpt = (out.get("ticket_body") or body or "")[:300]
                candidate = bug_registry.record_bug(parsed, cid, out["customer_email"], excerpt)
                if candidate:
                    out["bug_candidate"] = {
                        "summary": candidate.get("summary"),
                        "linear_id": candidate.get("linear_id"),
                    }
            except Exception:
                log.exception("bug_registry.record_bug failed for conversation %s", cid)

        # --- Internal note (escalations, needs_action tickets, and superseding
        # drafts; skipped in dry-run — Help Scout POST) ---
        if create_draft and (should_post_note(is_escalation, parsed) or out["supersedes_existing_draft"]):
            note_user_id = os.getenv("HELPSCOUT_NOTE_USER_ID", "").strip()
            if note_user_id:
                note_html = _format_internal_note_html(
                    parsed=parsed,
                    stripe_lines_for_note=stripe_note_block,
                    stripe_ctx=stripe_ctx_dict,
                    research_ran=out["research_ran"],
                    research_sources=out["research_sources"],
                    supersedes_existing_draft=out["supersedes_existing_draft"],
                )
                note_url = f"{BASE_URL}/conversations/{cid}/notes"
                try:
                    r2 = _helpscout_post(session, note_url, {"text": note_html, "user": int(note_user_id)})
                    r2.raise_for_status()
                    nid = r2.headers.get("Resource-ID") or r2.headers.get("resource-id")
                    out["helpscout_note_id"] = nid
                    out["note_created"] = True
                except requests.RequestException:
                    log.exception("Help Scout internal note failed")
            else:
                log.warning("HELPSCOUT_NOTE_USER_ID unset — skipping escalation note")

        # Skipped in dry-run: run_product_prioritization can post Linear
        # comments (external write) and burns an extra Claude call.
        if not create_draft:
            pp = {
                "skipped": True,
                "matched": False,
                "linear_issue_id": None,
                "linear_issue_identifier": None,
                "reasoning": "dry_run (create_draft=False)",
                "error": None,
            }
        else:
            pp = run_product_prioritization(
                ticket_subject=subject,
                ticket_body=body,
                tags=existing_tags,
                conversation_id=cid,
            )
        out["product_prioritization"] = pp
        if not pp.get("skipped"):
            log.info(
                "product_prioritization: matched=%s issue=%s reasoning=%s error=%s",
                pp.get("matched"),
                pp.get("linear_issue_identifier"),
                pp.get("reasoning"),
                pp.get("error"),
            )

        out["latency_ms"] = int((time.monotonic() - t0) * 1000)
        log.info("%s", json.dumps({k: out[k] for k in out if k != "draft_text"}, default=str))
        return out

    except Exception as e:
        out["error"] = str(e)
        out["latency_ms"] = int((time.monotonic() - t0) * 1000)
        log.exception("process_ticket_sync failed: %s", e)
        log.info("%s", json.dumps({k: out[k] for k in out if k != "draft_text"}, default=str))
        raise


async def process_ticket(conversation_id: str, customer_email: str | None = None) -> dict[str, Any]:
    """Async wrapper (runs sync pipeline in a worker thread)."""
    return await asyncio.to_thread(process_ticket_sync, conversation_id, customer_email)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    p = argparse.ArgumentParser(description="Run full support draft pipeline for one conversation.")
    p.add_argument("--conversation-id", "-c", required=True, help="Help Scout conversation id")
    p.add_argument("--email", "-e", default=None, help="Customer email (optional if on conversation)")
    args = p.parse_args()
    try:
        result = process_ticket_sync(args.conversation_id, args.email)
        print(json.dumps(result, indent=2, default=str))
    except Exception:
        sys.exit(1)


if __name__ == "__main__":
    main()
