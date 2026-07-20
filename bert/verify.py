"""Auto-send verifier — adversarial review of auto-send candidate drafts.

Three layers, cheapest first:
  1. ``prelint``                     — deterministic must-not-send checks, no API calls
  2. ``find_sibling_conversations``  — mechanical same-customer check against Help Scout
  3. ``verify_draft``                — one Claude call reviewing the draft against the full
                                       policy corpus, ticket context, and the standing brief

``bert.fanout.verify_and_tag`` orchestrates the three and reconciles the
``auto_send`` tag with the verdict. Findings use the error-class rubric from the
2026-07-20 manual review (classes A–I, see prompts/verify_system_prompt.txt).
"""

from __future__ import annotations

import json
import os
import re

import claude_utils
import orchestrator
import triage_tickets

VERDICTS = ("SEND_AS_IS", "MINOR", "ERROR")
DEFAULT_VERIFY_MODEL = os.getenv("BERT_VERIFY_MODEL", "claude-sonnet-5")

_PROMPT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..",
                            "prompts", "verify_system_prompt.txt")

_JSON_RETRY_SUFFIX = (
    "\n\nIMPORTANT: your previous response was not parseable JSON. Respond with ONLY the "
    "JSON verdict object — no prose, no markdown fences."
)

# Sequences that only appear when UTF-8 text was decoded as Latin-1/CP1252
# somewhere along the way ("â€™", "â€”", …) or replaced outright ("ï¿½", "�").
_MOJIBAKE_MARKERS = ("â€", "Ã¢â‚¬", "ï¿½", "�")

# Any leftover template placeholder: {%customer.firstName%}, {EMAIL}, {name} …
_PLACEHOLDER_RE = re.compile(r"\{%?[^{}]{1,80}%?\}")

# Website sign-in links. Checkout links carrying a coupon= param are legitimate
# (policies/login-issues.md: the web is checkout-only); bare sign-in links are not.
_SIGNIN_LINK_RE = re.compile(r"my\.meditatehappier\.com/start/sign_in[^\s\"'<>]*", re.IGNORECASE)

_SPELLED_OUT_BRAND_RE = re.compile(r"ten\s+percent\s+happier", re.IGNORECASE)


def _finding(cls: str, detail: str, fix_type: str, suggested_fix: str) -> dict:
    return {"class": cls, "detail": detail, "fix_type": fix_type, "suggested_fix": suggested_fix}


def prelint(draft_reply: str) -> list[dict]:
    """Deterministic must-not-send checks on the draft text (no model call).

    Returns rubric-shaped findings; an empty list means the draft passes the
    lint. Any finding here is an automatic ERROR verdict — these are exactly
    the mechanical failures a model reviewer sometimes waves through.
    """
    text = draft_reply or ""
    findings: list[dict] = []

    if _SPELLED_OUT_BRAND_RE.search(text):
        findings.append(_finding(
            "E", 'spelled-out "Ten Percent Happier" — the Dan Harris brand is always "10% Happier" in numerals',
            "rewrite", 'Replace with "10% Happier".'))

    placeholders = _PLACEHOLDER_RE.findall(text)
    if placeholders:
        findings.append(_finding(
            "H", f"leftover template placeholder(s): {', '.join(placeholders[:5])}",
            "rewrite", "Fill in the placeholder(s) with the customer's actual values."))

    if any(m in text for m in _MOJIBAKE_MARKERS):
        findings.append(_finding(
            "H", "mojibake sequence in draft (UTF-8 decoded as Latin-1, e.g. 'â€')",
            "rewrite", "Re-type the affected punctuation as plain characters."))

    for link in _SIGNIN_LINK_RE.findall(text):
        if "coupon=" not in link.lower():
            findings.append(_finding(
                "B", f"bare website sign-in link ({link}) — content access is app-only; "
                     "the web is checkout-only (policies/login-issues.md)",
                "rewrite", "Route sign-in through the app's welcome screen instead of the website."))
            break

    return findings


def find_sibling_conversations(session, email, *, exclude_cid) -> list:
    """Other ACTIVE Help Scout conversations for the same customer email.

    A non-empty result means the customer has parallel open tickets and the
    reply should be consolidated, not auto-sent. Raises on API failure — the
    caller decides fail-soft.
    """
    email = (email or "").strip()
    if not email:
        return []
    data = triage_tickets.api_get(
        session,
        f"{triage_tickets.BASE_URL}/conversations",
        params={"query": f'(email:"{email}")', "status": "active"},
    )
    convos = (data or {}).get("_embedded", {}).get("conversations", [])
    return [c.get("id") for c in convos
            if c.get("id") is not None and int(c["id"]) != int(exclude_cid)]


def _load_verify_prompt() -> str:
    with open(_PROMPT_PATH, encoding="utf-8") as f:
        return f.read()


def _build_verify_user_message(result: dict, ctx: dict, brief: str) -> str:
    brief = (brief or "").strip()
    history = (ctx.get("conversation_history") or "").strip()
    history_section = f"\n=== CONVERSATION HISTORY ===\n{history}\n" if history else ""
    reply_mode_note = (
        "\nNOTE: this is an ongoing thread — the draft must address the customer's "
        "LATEST message only.\n" if ctx.get("reply_mode") else ""
    )
    return f"""=== TICKET ===
Subject: {ctx.get('subject') or '(no subject)'}
Customer: {ctx.get('customer_name') or '(unknown)'} <{ctx.get('email') or 'unknown'}>
{reply_mode_note}
=== CUSTOMER MESSAGE ===
{ctx.get('body') or '(empty)'}
{history_section}
=== ACCOUNT CONTEXT ===
{ctx.get('account_blob') or '(none)'}

=== STRIPE CONTEXT ===
{ctx.get('stripe_block') or '(none)'}

=== STANDING BRIEF (live internal team context) ===
{brief or '(empty)'}

=== DRAFTING MODEL'S SELF-ASSESSMENT ===
Confidence: {result.get('confidence')}
Referenced policies: {', '.join(result.get('referenced_policies') or []) or '(none)'}
Reasoning: {result.get('reasoning') or '(none)'}

=== DRAFT REPLY UNDER REVIEW ===
{result.get('draft_reply') or '(empty)'}

Review the draft against everything above and return your JSON verdict."""


def _normalize_verdict(parsed: dict) -> dict:
    verdict = str(parsed.get("verdict") or "").strip().upper()
    if verdict not in VERDICTS:
        raise ValueError(f"verifier returned unknown verdict {parsed.get('verdict')!r}")
    findings = []
    for f in parsed.get("findings") or []:
        if not isinstance(f, dict):
            continue
        findings.append({
            "class": str(f.get("class") or "").strip().upper(),
            "detail": str(f.get("detail") or ""),
            "fix_type": str(f.get("fix_type") or ""),
            "suggested_fix": str(f.get("suggested_fix") or ""),
        })
    return {"verdict": verdict, "findings": findings}


def verify_draft(client, result: dict, ctx: dict, brief: str, policies: str, *,
                 model: str | None = None) -> dict:
    """One adversarial Claude review of an auto-send candidate draft.

    Returns {"verdict": SEND_AS_IS|MINOR|ERROR, "findings": [...]}. Raises on an
    unusable model response (bad JSON twice, unknown verdict, API error) — the
    caller fail-softs that into "no auto_send tag".
    """
    system_blocks = [{
        "type": "text",
        "text": _load_verify_prompt(),
        "cache_control": {"type": "ephemeral"},
    }]
    dynamic = _build_verify_user_message(result, ctx, brief)

    last_err: Exception | None = None
    for attempt in range(2):
        content = [
            {
                "type": "text",
                "text": f"=== POLICY DOCUMENTS ===\n{policies}\n",
                "cache_control": {"type": "ephemeral"},
            },
            {"type": "text", "text": dynamic + (_JSON_RETRY_SUFFIX if attempt else "")},
        ]
        message = client.messages.create(
            model=model or DEFAULT_VERIFY_MODEL,
            max_tokens=4000,
            system=system_blocks,
            messages=[{"role": "user", "content": content}],
        )
        text = claude_utils.extract_text(message)
        try:
            return _normalize_verdict(orchestrator._parse_claude_json(text))
        except json.JSONDecodeError as e:
            last_err = e
    raise ValueError(f"verifier did not return parseable JSON after retry: {last_err}")
