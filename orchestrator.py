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

from account_context import fetch_account_contexts_for_ticket  # noqa: E402
from stripe_context import fetch_stripe_context, format_stripe_context  # noqa: E402
from triage_tickets import (  # noqa: E402
    BASE_URL,
    fetch_conversation,
    get_access_token,
    get_conversation_text,
    run_triage,
)

log = logging.getLogger("support_orchestrator")

DRAFT_SYSTEM_PROMPT_PATH = os.path.join(_SUPPORT_DIR, "prompts", "draft_system_prompt.txt")
DEFAULT_CLAUDE_MODEL = "claude-opus-4-6"

DRAFT_JSON_RETRY_USER_SUFFIX = """

IMPORTANT — your last reply was empty or not valid JSON for this pipeline.

Reply with ONLY one JSON object (no markdown fences, no commentary before or after).
Required keys: draft_reply, escalate, escalate_reason, needs_action, action_description,
auto_sendable, do_not_send_reasons, referenced_policies, confidence, reasoning.
Use null for action_description when needs_action is false.
Use null for escalate_reason when escalate is false.
Use null for draft_reply when escalate is true.
If you must shorten draft_reply to fit, keep JSON valid and closed."""



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
    user_message: str,
    model: str,
) -> tuple[Any, dict[str, Any], str]:
    """Returns (message, parsed_json, raw_assistant_text)."""
    user_variants = [user_message, user_message.strip() + DRAFT_JSON_RETRY_USER_SUFFIX]
    last_json_err: json.JSONDecodeError | None = None
    last_api_err: BaseException | None = None
    last_raw_text = ""

    for variant_idx, msg_body in enumerate(user_variants):
        if variant_idx == 1:
            log.info("Retrying Claude draft with strict JSON-only user suffix")
        for api_attempt in range(2):
            try:
                message = client.messages.create(
                    model=model,
                    max_tokens=8192,
                    system=system_prompt,
                    messages=[{"role": "user", "content": msg_body}],
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


def _build_user_prompt(
    *,
    ticket_subject: str,
    ticket_body: str,
    customer_name: str,
    customer_email: str,
    account_blob: str,
    stripe_context: str,
    policy_docs: str,
    agent_name: str,
) -> str:
    return f"""
=== POLICY DOCUMENTS ===
{policy_docs}

=== CUSTOMER ACCOUNT DATA ===
Customer Name: {customer_name}
Customer Email: {customer_email}

{account_blob}

{stripe_context}

=== TICKET ===
Subject: {ticket_subject}

{ticket_body}

=== INSTRUCTIONS ===
Draft a reply to this ticket. Sign off as {agent_name}. Respond with the JSON object specified in your instructions.
"""


def _format_internal_note_html(
    *,
    parsed: dict[str, Any],
    stripe_lines_for_note: str,
) -> str:
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

    return (
        "<p><strong>🤖 AI Draft Classification</strong></p>"
        "<hr/>"
        f"{escalation_html}"
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


def _add_escalation_tag(session: requests.Session, cid: str, existing_tags: list[str]) -> None:
    if "escalation" in existing_tags:
        return
    merged = existing_tags + ["escalation"]
    resp = session.put(f"{BASE_URL}/conversations/{cid}/tags", json={"tags": merged})
    resp.raise_for_status()


def _html_escape(s: str) -> str:
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def process_ticket_sync(conversation_id: str, customer_email: str | None = None) -> dict[str, Any]:
    """
    Full pipeline: triage → account lookup → stripe enrichment → policy retrieval →
    Claude draft → Help Scout draft + note.

    Returns dict with draft_text, needs_action, reasoning, referenced_policies,
    helpscout_draft_id, helpscout_note_id, plus telemetry fields.
    """
    t0 = time.monotonic()
    cid = str(conversation_id).strip()
    out: dict[str, Any] = {
        "conversation_id": cid,
        "customer_email": customer_email or "",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "triage_success": False,
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
        "auto_sendable": None,
        "confidence": None,
        "referenced_policies": [],
        "do_not_send_reasons": [],
        "draft_created": False,
        "note_created": False,
        "helpscout_draft_id": None,
        "helpscout_note_id": None,
        "total_input_tokens": None,
        "total_output_tokens": None,
        "latency_ms": None,
        "draft_text": None,
        "reasoning": None,
        "error": None,
    }

    email_in = (customer_email or "").strip()

    try:
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
        cust = _customer_from_conversation(convo)
        hs_customer_id = cust.get("id")
        convo_email = (cust.get("email") or "").strip()
        email = email_in or convo_email
        out["customer_email"] = email
        existing_tags = _extract_tag_names(convo.get("tags", []))

        customer_name = _customer_display_name(cust)
        subject = convo.get("subject") or "(no subject)"
        body = get_conversation_text(session, int(cid)) or "(empty)"

        account_blob = ""
        try:
            ctx = fetch_account_contexts_for_ticket(
                primary_email=email or None,
                ticket_text=body,
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

        if platform and platform.lower() == "stripe":
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

        user_message = _build_user_prompt(
            ticket_subject=subject,
            ticket_body=body,
            customer_name=customer_name,
            customer_email=email or "(unknown)",
            account_blob=account_blob,
            stripe_context=stripe_block_for_prompt,
            policy_docs=policy_docs,
            agent_name=agent_name,
        )

        client = anthropic.Anthropic(api_key=api_key)
        model = out["claude_model"]
        msg, parsed, _raw_assistant = _call_claude_draft(
            client,
            system_prompt=system_prompt,
            user_message=user_message,
            model=model,
        )

        usage = getattr(msg, "usage", None)
        if usage:
            out["total_input_tokens"] = getattr(usage, "input_tokens", None)
            out["total_output_tokens"] = getattr(usage, "output_tokens", None)

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

        if is_escalation:
            try:
                _add_escalation_tag(session, cid, existing_tags)
                log.info("Escalation: added 'escalation' tag to conversation %s", cid)
            except requests.RequestException:
                log.exception("Failed to add escalation tag to conversation %s", cid)

        note_user_id = os.getenv("HELPSCOUT_NOTE_USER_ID", "").strip()
        note_html = _format_internal_note_html(
            parsed=parsed,
            stripe_lines_for_note=stripe_note_block,
        )

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
            except requests.RequestException as e:
                log.exception(
                    "Help Scout draft reply failed — preserving draft in logs. Error: %s\nDraft:\n%s",
                    e,
                    draft_reply[:8000],
                )

        if note_user_id:
            note_url = f"{BASE_URL}/conversations/{cid}/notes"
            note_payload = {"text": note_html, "user": int(note_user_id)}
            try:
                r2 = _helpscout_post(session, note_url, note_payload)
                r2.raise_for_status()
                nid = r2.headers.get("Resource-ID") or r2.headers.get("resource-id")
                out["helpscout_note_id"] = nid
                out["note_created"] = True
            except requests.RequestException:
                log.exception("Help Scout internal note failed — draft may still exist")
        else:
            log.warning("HELPSCOUT_NOTE_USER_ID unset — skipping internal note")

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
