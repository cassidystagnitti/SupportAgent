"""Auto-send verifier — adversarial review + bounded repair of auto-send
candidate drafts.

Layers, cheapest first:
  1. ``prelint``                     — deterministic must-not-send checks, no API calls
  2. ``find_sibling_conversations``  — mechanical same-customer check against Help Scout
  3. ``verify_draft``                — one Claude call reviewing the draft against the full
                                       policy corpus, ticket context, and the standing brief
  4. ``repair_draft``                — one Claude call applying a verdict's ``rewrite``
                                       findings (``repairable``) so the draft can re-verify

``bert.fanout.verify_and_tag`` orchestrates the layers (verify → repair →
re-verify, bounded) and reconciles the ``auto_send`` tag with the FINAL
verdict. Findings use the error-class rubric from the 2026-07-20 manual review
(classes A–I, see prompts/verify_system_prompt.txt).
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone

import anthropic

import claude_utils
import orchestrator
import triage_tickets

VERDICTS = ("SEND_AS_IS", "MINOR", "ERROR")
DEFAULT_VERIFY_MODEL = os.getenv("BERT_VERIFY_MODEL", "claude-sonnet-5")

_PROMPTS_DIR = os.path.dirname(orchestrator.DRAFT_SYSTEM_PROMPT_PATH)
_VERIFY_PROMPT_PATH = os.path.join(_PROMPTS_DIR, "verify_system_prompt.txt")
_REPAIR_PROMPT_PATH = os.path.join(_PROMPTS_DIR, "repair_system_prompt.txt")

_JSON_RETRY_SUFFIX = (
    "\n\nIMPORTANT: your previous response was not parseable JSON. Respond with ONLY the "
    "JSON object — no prose, no markdown fences."
)

# Sequences that only appear when UTF-8 text was decoded as Latin-1/CP1252
# somewhere along the way ("â€™", "â€”", …) or replaced outright ("ï¿½", "�").
_MOJIBAKE_MARKERS = ("â€", "Ã¢â‚¬", "ï¿½", "�")

# Any leftover template placeholder: {%customer.firstName%}, {EMAIL}, {name} …
_PLACEHOLDER_RE = re.compile(r"\{%?[^{}]{1,80}%?\}")

# Website sign-in links. Checkout links carrying a coupon= or plan= param are
# legitimate (policies/login-issues.md: the web is checkout-only;
# policies/account-lookup-data-model.md prescribes plan-only checkout links);
# bare sign-in links are not.
_SIGNIN_LINK_RE = re.compile(r"my\.meditatehappier\.com/start/sign_in[^\s\"'<>]*", re.IGNORECASE)
_CHECKOUT_PARAMS = ("coupon=", "plan=")

_SPELLED_OUT_BRAND_RE = re.compile(r"ten\s+percent\s+happier", re.IGNORECASE)

# Dead help-center domain: support.happierapp.com 405s (verified 2026-07-22) —
# the live Help Center is support.meditatehappier.com. The dead domain leaked
# into two policy docs (fixed same day); this catches any regression.
_DEAD_HELP_DOMAIN = "support.happierapp.com"
_LIVE_HELP_DOMAIN = "support.meditatehappier.com"


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
        if not any(p in link.lower() for p in _CHECKOUT_PARAMS):
            findings.append(_finding(
                "B", f"bare website sign-in link ({link}) — content access is app-only; "
                     "the web is checkout-only (policies/login-issues.md)",
                "rewrite", "Route sign-in through the app's welcome screen instead of the website."))
            break

    if _DEAD_HELP_DOMAIN in text.lower():
        findings.append(_finding(
            "B", f"dead Help Center domain ({_DEAD_HELP_DOMAIN}) — that host returns an error; "
                 f"the live Help Center is {_LIVE_HELP_DOMAIN}",
            "rewrite", f"Replace {_DEAD_HELP_DOMAIN} with {_LIVE_HELP_DOMAIN} in the link."))

    return findings


def sibling_finding(siblings: list) -> dict:
    """The rubric finding for a customer with other open conversations."""
    return _finding(
        "I", f"customer has {len(siblings)} other open conversation(s): {siblings}",
        "consolidate", "Answer once on the primary thread and consolidate the duplicates.")


def find_sibling_conversations(session, email, *, exclude_cid) -> list:
    """Other OPEN (active or pending) Help Scout conversations for the same
    customer email.

    A non-empty result means the customer has parallel open tickets and the
    reply should be consolidated, not auto-sent. Raises on API failure — the
    caller decides fail-soft.
    """
    # Embedded quotes (legal in RFC 5322 local parts) would corrupt the query
    # syntax; stripping them degrades the match rather than erroring out.
    email = (email or "").strip().replace('"', "")
    if not email:
        return []
    data = triage_tickets.api_get(
        session,
        f"{triage_tickets.BASE_URL}/conversations",
        params={"query": f'(email:"{email}")', "status": "open"},
    )
    convos = (data or {}).get("_embedded", {}).get("conversations", [])
    return [c.get("id") for c in convos
            if c.get("id") is not None and int(c["id"]) != int(exclude_cid)]


def _load_prompt(path: str) -> str:
    with open(path, encoding="utf-8") as f:
        return f.read()


def _build_ticket_context(result: dict, ctx: dict, brief: str) -> str:
    brief = (brief or "").strip()
    today = datetime.now(timezone.utc).strftime("%B %d, %Y")
    history = (ctx.get("conversation_history") or "").strip()
    history_section = f"\n=== CONVERSATION HISTORY ===\n{history}\n" if history else ""
    reply_mode_note = (
        "\nNOTE: this is an ongoing thread — the draft must address the customer's "
        "LATEST message only.\n" if ctx.get("reply_mode") else ""
    )
    return f"""Today's date: {today}

=== TICKET ===
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
Reasoning: {result.get('reasoning') or '(none)'}"""


def _call_json(client, *, system_prompt: str, policies: str, dynamic: str,
               model: str, max_tokens: int) -> dict:
    """One Claude call that must return a JSON object; retries once on bad JSON
    (with a strict suffix) and once on a transient API error. Raises otherwise."""
    system_blocks = [{
        "type": "text",
        "text": system_prompt,
        "cache_control": {"type": "ephemeral"},
    }]
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
        for api_attempt in range(2):
            try:
                message = client.messages.create(
                    model=model,
                    max_tokens=max_tokens,
                    system=system_blocks,
                    messages=[{"role": "user", "content": content}],
                )
                break
            except anthropic.AnthropicError as e:
                if api_attempt == 0 and orchestrator._should_retry_claude(e):
                    continue
                raise
        text = claude_utils.extract_text(message)
        try:
            parsed = orchestrator._parse_claude_json(text)
            if not isinstance(parsed, dict):
                raise json.JSONDecodeError("top-level JSON is not an object", text, 0)
            return parsed
        except json.JSONDecodeError as e:
            last_err = e
    raise ValueError(f"model did not return a parseable JSON object after retry: {last_err}")


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
    # A self-contradictory "clean but here are problems" response must never
    # earn the tag — downgrade it to a human-review verdict.
    if verdict == "SEND_AS_IS" and findings:
        verdict = "MINOR"
    return {"verdict": verdict, "findings": findings}


def verify_draft(client, result: dict, ctx: dict, brief: str, policies: str, *,
                 model: str | None = None) -> dict:
    """One adversarial Claude review of an auto-send candidate draft.

    Returns {"verdict": SEND_AS_IS|MINOR|ERROR, "findings": [...]}. Raises on an
    unusable model response (bad JSON twice, unknown verdict, API error) — the
    caller fail-softs that into "no auto_send tag".
    """
    dynamic = (f"{_build_ticket_context(result, ctx, brief)}\n\n"
               f"=== DRAFT REPLY UNDER REVIEW ===\n{result.get('draft_reply') or '(empty)'}\n\n"
               "Review the draft against everything above and return your JSON verdict.")
    parsed = _call_json(
        client,
        system_prompt=_load_prompt(_VERIFY_PROMPT_PATH),
        policies=policies,
        dynamic=dynamic,
        model=model or DEFAULT_VERIFY_MODEL,
        # 16000, matching repair_draft: the model emits thinking before the JSON
        # verdict, and on hard tickets thinking alone can blow through a 4000
        # budget — the call then returns thinking-only content with empty text
        # ("empty assistant text" failures, 3/13 candidates on 2026-07-22).
        max_tokens=16000,
    )
    return _normalize_verdict(parsed)


def repairable(findings: list) -> bool:
    """True when the repair loop may fix these findings autonomously: at least
    one finding, and every one is a pure ``rewrite`` (fully determined by the
    policies/brief/context — never external facts, human action, or
    consolidation)."""
    findings = findings or []
    return bool(findings) and all(f.get("fix_type") == "rewrite" for f in findings)


def repair_draft(client, result: dict, ctx: dict, brief: str, policies: str,
                 findings: list, *, model: str | None = None) -> str:
    """One Claude call applying the findings' fixes to the draft.

    Returns the revised draft text. Raises on an unusable model response or an
    empty revision — the caller fail-softs that into "no auto_send tag".
    """
    findings_block = "\n".join(
        f"- class {f.get('class')}: {f.get('detail')}\n  Fix: {f.get('suggested_fix') or '(apply the obvious correction)'}"
        for f in findings
    )
    dynamic = (f"{_build_ticket_context(result, ctx, brief)}\n\n"
               f"=== DRAFT REPLY TO REPAIR ===\n{result.get('draft_reply') or '(empty)'}\n\n"
               f"=== VERIFIER FINDINGS TO FIX ===\n{findings_block}\n\n"
               "Apply ONLY these fixes and return the JSON object with the revised draft.")
    parsed = _call_json(
        client,
        system_prompt=_load_prompt(_REPAIR_PROMPT_PATH),
        policies=policies,
        dynamic=dynamic,
        model=model or DEFAULT_VERIFY_MODEL,
        max_tokens=16000,
    )
    revised = str(parsed.get("draft_reply") or "").strip()
    if not revised:
        raise ValueError("repair returned an empty draft_reply")
    return revised
