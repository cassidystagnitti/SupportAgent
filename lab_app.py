#!/usr/bin/env python3
"""
Local step-by-step tester for the support pipeline (no webhook).

  uvicorn lab_app:app --host 127.0.0.1 --port 8765

Open http://127.0.0.1:8765 — bind localhost only; sessions stay in memory.

Uses your existing .env (Help Scout, Anthropic, Maven, Stripe, HELPSCOUT_NOTE_USER_ID).

``prompts/draft_system_prompt.txt`` is re-read from disk on each **Claude** step — no
restart for prompt-only edits. Restart after Python code changes, or use uvicorn ``--reload``.
"""

from __future__ import annotations

import io
import json
import logging
import os
import sys
import traceback
import uuid
from contextlib import redirect_stdout
from typing import Any

import anthropic
import requests
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse

_SUPPORT_DIR = os.path.dirname(os.path.abspath(__file__))
_ROOT_DIR = os.path.dirname(_SUPPORT_DIR)
load_dotenv(os.path.join(_SUPPORT_DIR, ".env"))
load_dotenv(os.path.join(_ROOT_DIR, ".env"))

import orchestrator as orch  # noqa: E402
from account_context import fetch_account_contexts_for_ticket, fetch_customer_emails_from_helpscout  # noqa: E402
from product_prioritization import run_product_prioritization  # noqa: E402
from stripe_context import fetch_stripe_context, format_stripe_context  # noqa: E402
from triage_tickets import get_conversation_history, run_triage  # noqa: E402

log = logging.getLogger("pipeline_lab")

STEP_ORDER = [
    "triage",
    "helpscout_snapshot",
    "account",
    "stripe",
    "policies",
    "claude",
    "helpscout_write",
    "product_prioritization",
]

MAX_SESSIONS = 40
_sessions: dict[str, dict[str, Any]] = {}

app = FastAPI(title="Support pipeline lab", docs_url=None, redoc_url=None)


def _session_get(sid: str) -> dict[str, Any]:
    s = _sessions.get(sid)
    if not s:
        raise HTTPException(status_code=404, detail="unknown session")
    return s


def _trim(s: str, n: int = 12000) -> str:
    if len(s) <= n:
        return s
    return s[:n] + f"\n\n… [{len(s) - n} more chars truncated for UI]"


def _run_triage_captured(conversation_id: str) -> tuple[bool, str]:
    buf = io.StringIO()
    try:
        with redirect_stdout(buf):
            run_triage(
                conversation_ids=[conversation_id],
                auto_apply=True,
                skip_unassigned_scan=True,
            )
        ok = True
        msg = buf.getvalue() or "(triage finished — no stdout)"
    except SystemExit as e:
        ok = False
        msg = buf.getvalue() + f"\n[SystemExit: {e.code}] — check HELPSCOUT_* / ANTHROPIC_* in .env"
    except Exception:
        ok = False
        msg = buf.getvalue() + "\n" + traceback.format_exc()
    return ok, msg.strip()


def _helpscout_session(technical_log: list[str] | None = None) -> requests.Session:
    token = orch.get_access_token()
    session = requests.Session()
    session.headers.update({"Authorization": f"Bearer {token}"})
    if technical_log is not None:
        def _log_resp(resp: requests.Response, **_kwargs: Any) -> None:
            req = resp.request
            url = (req.url or "").split("?")[0]
            technical_log.append(
                f"HTTP {req.method} {url} → {resp.status_code} ({len(resp.content)} bytes)"
            )

        session.hooks["response"].append(_log_resp)
    return session


def _execute_step(sess: dict[str, Any], step: str) -> dict[str, Any]:
    cid = sess["convo_id"]
    email = sess["email"].strip()
    subject_in = sess["subject"]
    body_in = sess["body"]

    if step == "triage":
        if sess.get("skip_triage"):
            return {
                "ok": True,
                "summary": "Skipped (checkbox).",
                "detail": "",
                "technical_log": ["Step skipped by session option."],
            }
        tech = [
            "Running triage_tickets.run_triage(conversation_ids=[…], auto_apply=True, skip_unassigned_scan=True).",
            "Stdout from triage is shown in the main panel (OAuth + Help Scout calls happen inside that module).",
        ]
        ok, detail = _run_triage_captured(cid)
        return {
            "ok": ok,
            "summary": "Triage completed." if ok else "Triage failed.",
            "detail": _trim(detail, 16000),
            "technical_log": tech,
        }

    if step == "helpscout_snapshot":
        tech: list[str] = [
            "Help Scout Mailbox API — HTTP hook logs each response (Authorization header not recorded).",
        ]
        try:
            hs = _helpscout_session(tech)
            convo = orch.fetch_conversation(hs, int(cid))
            cust = orch._customer_from_conversation(convo)
            hs_customer_id = cust.get("id")
            sess["hs_customer_id"] = hs_customer_id
            sess["customer_name_hs"] = orch._customer_display_name(cust)
            hs_email = (cust.get("email") or "").strip()
            if not sess["email"] and hs_email:
                sess["email"] = hs_email
                tech.append(f"Email auto-populated from Help Scout customer: {hs_email}")
            hs_emails = fetch_customer_emails_from_helpscout(hs, hs_customer_id) if hs_customer_id else []
            sess["hs_customer_emails"] = hs_emails
            if hs_emails:
                tech.append(f"Help Scout customer emails: {hs_emails}")
            sess["existing_tags"] = orch._extract_tag_names(convo.get("tags", []))
            live_subject = convo.get("subject") or ""
            if sess.get("is_reply"):
                conversation_history, live_body = get_conversation_history(hs, int(cid))
                live_body = live_body or ""
                sess["conversation_history"] = conversation_history
                tech.append(f"Reply mode: fetched conversation history ({len(conversation_history)} chars) + latest message ({len(live_body)} chars).")
            else:
                live_body = orch.get_conversation_text(hs, int(cid)) or ""
                sess["conversation_history"] = ""
            sess["live_subject"] = live_subject
            sess["live_body"] = live_body
            # always use live thread data — that's what prod does
            sess["effective_subject"] = live_subject or subject_in
            sess["effective_body"] = live_body or body_in
            preview = {
                "hs_customer_id": sess["hs_customer_id"],
                "customer_name_hs": sess["customer_name_hs"],
                "customer_email": sess["email"],
                "live_subject": live_subject[:500],
                "live_body_preview": _trim(live_body, 4000),
            }
            return {
                "ok": True,
                "summary": "Fetched conversation from Help Scout.",
                "detail": json.dumps(preview, indent=2),
                "technical_log": tech,
            }
        except Exception:
            tech.append(traceback.format_exc())
            return {"ok": False, "summary": "Help Scout fetch failed.", "detail": traceback.format_exc(), "technical_log": tech}

    if step == "account":
        tech = [
            "account_context.fetch_account_contexts_for_ticket — looks up primary email + all emails found in ticket body.",
            "HTTP details are not hooked here; see Maven/backend logs if requests fail.",
        ]
        try:
            if not email:
                blob = (
                    "Account lookup failed — could not retrieve customer data "
                    "(missing customer email)."
                )
                sess["account_blob"] = blob
                sess["account_lookup_ok"] = False
                tech.append("No email provided — stub blob only.")
                return {
                    "ok": True,
                    "summary": "No email — using failure stub for account blob.",
                    "detail": blob,
                    "technical_log": tech,
                }
            ticket_text = sess.get("effective_body") or sess.get("body") or ""
            ctx = fetch_account_contexts_for_ticket(
                primary_email=email,
                ticket_text=ticket_text,
                extra_emails=sess.get("hs_customer_emails"),
            )
            blob = ctx["combined_blob"]
            emails_checked = ctx["emails_checked"]
            multiple_subscribed = ctx["multiple_subscribed"]
            sess["multiple_subscribed"] = multiple_subscribed
            if not blob.strip():
                blob = (
                    "Account lookup failed — could not retrieve customer data "
                    "(empty response)."
                )
                sess["account_lookup_ok"] = False
            else:
                sess["account_lookup_ok"] = True
            sess["account_blob"] = blob
            tech.append(f"Emails checked: {emails_checked}")
            tech.append(f"Multiple subscribed accounts: {multiple_subscribed}")
            tech.append(f"Account blob length: {len(blob)} characters.")
            summary = "Account context loaded."
            if multiple_subscribed:
                summary = "⚠️ ESCALATION: multiple subscribed accounts found — do not send any reply."
            return {"ok": True, "summary": summary, "detail": _trim(blob, 14000), "technical_log": tech}
        except Exception:
            sess["account_blob"] = f"Account lookup failed — could not retrieve customer data ({traceback.format_exc()})"
            sess["account_lookup_ok"] = False
            tech.append("Exception during fetch — see detail panel.")
            return {"ok": False, "summary": "Account API error.", "detail": sess["account_blob"], "technical_log": tech}

    if step == "stripe":
        platform = orch._subscription_platform(sess.get("account_blob") or "")
        sess["subscription_platform"] = platform
        tech = [
            f"Parsed Maven/account line Subscription Platform → {platform!r}",
            "Enrichment uses stripe-python (Customer.list → Subscription.list → optional Invoice.create_preview or Invoice.upcoming).",
        ]
        is_stripe_platform = platform and platform.lower() == "stripe"
        is_gift_ticket = "gift-subscription" in (sess.get("existing_tags") or [])
        tech.append(f"gift-subscription tag present: {is_gift_ticket}")
        if not is_stripe_platform and not is_gift_ticket:
            sess["stripe_block"] = (
                f"N/A — customer is on {platform or 'unknown'} (not Stripe web billing)"
            )
            tech.append("Stripe API not called (platform is not Stripe and gift-subscription tag absent).")
            return {
                "ok": True,
                "summary": "Stripe enrichment skipped (platform is not Stripe).",
                "detail": sess["stripe_block"],
                "technical_log": tech,
            }
        try:
            key_ok = bool((os.getenv("STRIPE_READ_API_KEY") or "").strip())
            tech.append(f"STRIPE_READ_API_KEY present: {key_ok}")
            ctx = fetch_stripe_context(email) if email else None
            sess["stripe_ctx"] = ctx
            sess["stripe_block"] = format_stripe_context(ctx)
            if ctx:
                tech.append(
                    "Stripe context keys: "
                    + ", ".join(sorted(ctx.keys()))
                )
                tech.append(
                    _trim(json.dumps({k: ctx[k] for k in ctx if k != "discount"}, default=str), 4000)
                )
                if ctx.get("discount"):
                    tech.append("discount: " + json.dumps(ctx["discount"], default=str))
            else:
                tech.append("Stripe returned no subscription/context for this email (see formatted detail).")
            return {"ok": True, "summary": "Stripe context loaded.", "detail": sess["stripe_block"], "technical_log": tech}
        except Exception:
            sess["stripe_block"] = "Stripe data unavailable"
            tech.append(traceback.format_exc())
            return {"ok": False, "summary": "Stripe error.", "detail": traceback.format_exc(), "technical_log": tech}

    if step == "policies":
        tech = [
            f"orch.load_policy_docs() — directory: {os.path.join(_SUPPORT_DIR, 'policies')}",
        ]
        try:
            text = orch.load_policy_docs()
            sess["policy_docs"] = text
            files = sorted(
                f for f in os.listdir(os.path.join(_SUPPORT_DIR, "policies")) if f.endswith(".md")
            )
            meta = {
                "files": files,
                "total_chars": len(text),
                "approx_tokens_note": f"~{len(text) // 4} tokens (very rough)",
            }
            sess["policy_meta"] = meta
            tech.append(f"Files: {', '.join(files)}")
            tech.append(f"Concatenated policy corpus: {len(text)} characters.")
            return {
                "ok": True,
                "summary": f"Loaded {len(files)} policy files ({len(text)} chars).",
                "detail": json.dumps(meta, indent=2) + "\n\n--- preview ---\n" + _trim(text, 6000),
                "technical_log": tech,
            }
        except Exception:
            tech.append(traceback.format_exc())
            return {"ok": False, "summary": "Policy load failed.", "detail": traceback.format_exc(), "technical_log": tech}

    if step == "claude":
        api_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
        if not api_key:
            return {
                "ok": False,
                "summary": "Missing ANTHROPIC_API_KEY.",
                "detail": "",
                "technical_log": ["ANTHROPIC_API_KEY is empty in environment."],
            }
        try:
            system_prompt = orch._load_system_prompt()
            tech = [
                f"System prompt file: {orch.DRAFT_SYSTEM_PROMPT_PATH}",
                "(Re-read from disk on each Claude step — edit & re-run step to pick up changes.)",
                f"Anthropic Messages API — model from env or default.",
            ]
            agent_name = os.getenv("SUPPORT_AGENT_SIGNOFF_NAME", "Happier Meditation Support")
            cust_name = sess.get("customer_name_hs") or "there"
            policy_docs = sess.get("policy_docs") or ""
            user_msg = orch._build_dynamic_user_message(
                ticket_subject=sess.get("effective_subject") or subject_in,
                ticket_body=sess.get("effective_body") or body_in,
                customer_name=cust_name,
                customer_email=email or "(unknown)",
                account_blob=sess.get("account_blob") or "",
                stripe_context=sess.get("stripe_block") or "",
                agent_name=agent_name,
                conversation_history=sess.get("conversation_history") or "",
            )
            sess["last_user_prompt_chars"] = len(user_msg)
            model = os.getenv("CLAUDE_DRAFT_MODEL", orch.DEFAULT_CLAUDE_MODEL)
            tech.append(f"model: {model}")
            tech.append(f"system_prompt chars: {len(system_prompt)}")
            tech.append(f"user message chars: {len(user_msg)}")
            client = anthropic.Anthropic(api_key=api_key)
            msg, parsed, raw_assistant = orch._call_claude_draft(
                client,
                system_prompt=system_prompt,
                policy_docs=policy_docs,
                dynamic_user_message=user_msg,
                model=model,
            )
            sess["claude_parsed"] = parsed
            sess["claude_model"] = model
            usage = getattr(msg, "usage", None)
            usage_d = {}
            if usage:
                usage_d = {
                    "input_tokens": getattr(usage, "input_tokens", None),
                    "output_tokens": getattr(usage, "output_tokens", None),
                }
            sess["claude_usage"] = usage_d
            tech.append(f"usage: {usage_d}")
            tech.append(f"raw assistant text chars: {len(raw_assistant)}")
            tech.append("--- raw assistant text (full JSON string from model; preview) ---")
            tech.append(_trim(raw_assistant, 12000))
            draft = parsed.get("draft_reply") or ""
            tech.append(f"parsed JSON top-level keys: {list(parsed.keys())}")
            detail = json.dumps(
                {
                    "usage": usage_d,
                    "classification": {
                        k: parsed.get(k)
                        for k in (
                            "needs_action",
                            "auto_sendable",
                            "confidence",
                            "referenced_policies",
                            "do_not_send_reasons",
                            "reasoning",
                            "action_description",
                        )
                    },
                    "draft_reply_preview": _trim(draft, 8000),
                },
                indent=2,
            )
            return {"ok": True, "summary": "Claude returned draft JSON.", "detail": detail, "technical_log": tech}
        except Exception:
            return {
                "ok": False,
                "summary": "Claude failed.",
                "detail": traceback.format_exc(),
                "technical_log": ["Claude step raised:", traceback.format_exc()],
            }

    if step == "helpscout_write":
        tech = [
            "Help Scout Mailbox API writes — hook logs HTTP responses (no Authorization header in log).",
        ]
        if sess.get("skip_helpscout_writes"):
            tech.append("Skipped: session option skip Help Scout draft + note.")
            return {"ok": True, "summary": "Skipped (checkbox).", "detail": "", "technical_log": tech}
        parsed = sess.get("claude_parsed")
        if not parsed:
            tech.append("No claude_parsed in session.")
            return {"ok": False, "summary": "Run Claude step first.", "detail": "", "technical_log": tech}
        draft_reply = parsed.get("draft_reply") or ""
        hid = sess.get("hs_customer_id")
        if hid is None:
            tech.append("Missing hs_customer_id — run snapshot step.")
            return {
                "ok": False,
                "summary": "No Help Scout customer id — run snapshot step.",
                "detail": _trim(draft_reply, 4000),
                "technical_log": tech,
            }
        is_escalation = bool(parsed.get("escalate")) or bool(sess.get("multiple_subscribed"))
        auto_sendable = False if is_escalation else bool(parsed.get("auto_sendable"))
        existing_tags = sess.get("existing_tags") or []

        # --- Tags (single PUT) ---
        tags_to_add: list[str] = []
        if is_escalation:
            tags_to_add.append("escalation")
        tags_to_add.append("automated" if auto_sendable else "technical")
        try:
            hs_tags = _helpscout_session(tech)
            orch._update_conversation_tags(hs_tags, cid, existing_tags, tags_to_add)
            lines_out_tags = f"Tags updated: added {tags_to_add}"
            tech.append(lines_out_tags)
        except Exception:
            tb = traceback.format_exc()
            tech.append("Tag update FAILED:\n" + tb)

        lines_out = []
        if is_escalation:
            lines_out.append("Escalation — draft skipped.")
        else:
            try:
                hs = _helpscout_session(tech)
                reply_url = f"{orch.BASE_URL}/conversations/{cid}/reply"
                payload_preview = {"customer": {"id": int(hid)}, "text": f"<{len(draft_reply)} chars>", "draft": True}
                tech.append(f"POST reply payload summary: {payload_preview}")
                r = orch._helpscout_post(
                    hs,
                    reply_url,
                    {"customer": {"id": int(hid)}, "text": draft_reply, "draft": True},
                )
                r.raise_for_status()
                rid = r.headers.get("Resource-ID") or r.headers.get("resource-id")
                lines_out.append(f"Draft reply created. Resource-ID: {rid}")
                tech.append(f"Reply draft: HTTP {r.status_code}, Resource-ID header: {rid!r}")
            except requests.HTTPError as e:
                resp = e.response
                extra = ""
                if resp is not None:
                    extra = f"\nResponse body (truncated): {_trim(resp.text, 2000)}"
                tb = traceback.format_exc() + extra
                lines_out.append("Draft reply FAILED:\n" + tb)
                tech.append(tb)
            except Exception:
                tb = traceback.format_exc()
                lines_out.append("Draft reply FAILED:\n" + tb)
                tech.append(tb)

        if is_escalation:
            note_uid = os.getenv("HELPSCOUT_NOTE_USER_ID", "").strip()
            if note_uid:
                note_html = orch._format_internal_note_html(
                    parsed=parsed,
                    stripe_lines_for_note=(sess.get("stripe_block") or "").replace("\n", "<br/>"),
                )
                try:
                    hs2 = _helpscout_session(tech)
                    note_url = f"{orch.BASE_URL}/conversations/{cid}/notes"
                    tech.append(f"POST escalation note user={note_uid}, text HTML chars={len(note_html)}")
                    r2 = orch._helpscout_post(hs2, note_url, {"text": note_html, "user": int(note_uid)})
                    r2.raise_for_status()
                    nid = r2.headers.get("Resource-ID") or r2.headers.get("resource-id")
                    lines_out.append(f"Escalation note created. Resource-ID: {nid}")
                    tech.append(f"Note: HTTP {r2.status_code}, Resource-ID: {nid!r}")
                except requests.HTTPError as e:
                    resp = e.response
                    extra = f"\nResponse body (truncated): {_trim(resp.text, 2000)}" if resp is not None else ""
                    tb = traceback.format_exc() + extra
                    lines_out.append("Escalation note FAILED:\n" + tb)
                    tech.append(tb)
                except Exception:
                    tb = traceback.format_exc()
                    lines_out.append("Escalation note FAILED:\n" + tb)
                    tech.append(tb)
            else:
                lines_out.append("HELPSCOUT_NOTE_USER_ID unset — escalation note skipped.")
                tech.append("HELPSCOUT_NOTE_USER_ID unset — escalation note not POSTed.")

        ok = not any("FAILED" in line for line in lines_out)
        return {"ok": ok, "summary": "Help Scout write step finished.", "detail": "\n\n".join(lines_out), "technical_log": tech}

    if step == "product_prioritization":
        tags = sess.get("existing_tags") or []
        tech = [
            f"Tags on conversation after triage: {tags}",
            "Runs only when 'feedback' tag is present and LINEAR_PRODUCT_TEAM_ID is set.",
        ]
        try:
            result = run_product_prioritization(
                ticket_subject=sess.get("effective_subject") or subject_in,
                ticket_body=sess.get("effective_body") or body_in,
                tags=tags,
                conversation_id=cid,
            )
            if result.get("skipped"):
                reason = (
                    "ticket not tagged 'feedback'"
                    if "feedback" not in [t.lower() for t in tags]
                    else "LINEAR_PRODUCT_TEAM_ID not set"
                )
                return {
                    "ok": True,
                    "summary": f"Skipped — {reason}.",
                    "detail": json.dumps(result, indent=2),
                    "technical_log": tech,
                }
            detail = json.dumps(result, indent=2)
            if result.get("matched"):
                summary = f"Matched Linear issue {result.get('linear_issue_identifier')} — comment added."
            elif result.get("error"):
                summary = f"Error: {result['error']}"
            else:
                summary = "No matching Linear issue found."
            return {"ok": not bool(result.get("error")), "summary": summary, "detail": detail, "technical_log": tech}
        except Exception:
            tech.append(traceback.format_exc())
            return {"ok": False, "summary": "Product prioritization failed.", "detail": traceback.format_exc(), "technical_log": tech}

    return {"ok": False, "summary": "Unknown step.", "detail": step, "technical_log": []}


@app.post("/api/session")
def create_session(payload: dict[str, Any]) -> dict[str, Any]:
    convo_id = str(payload.get("convo_id") or "").strip()
    email = str(payload.get("email") or "").strip()
    subject = str(payload.get("subject") or "").strip()
    body = str(payload.get("body") or "").strip()
    is_reply = bool(payload.get("is_reply"))
    skip_triage = bool(payload.get("skip_triage")) or is_reply
    skip_writes = bool(payload.get("skip_helpscout_writes"))
    use_live = bool(payload.get("use_live_thread"))

    if not convo_id.isdigit():
        raise HTTPException(status_code=400, detail="convo_id must be numeric")

    if len(_sessions) >= MAX_SESSIONS:
        first_key = next(iter(_sessions))
        _sessions.pop(first_key, None)

    sid = str(uuid.uuid4())
    sess: dict[str, Any] = {
        "convo_id": convo_id,
        "email": email,
        "subject": subject,
        "body": body,
        "is_reply": is_reply,
        "skip_triage": skip_triage,
        "skip_helpscout_writes": skip_writes,
        "use_live_thread": use_live,
        "completed": [],
        "step_logs": {},
    }
    _sessions[sid] = sess

    if skip_triage:
        reason = "Reply mode — triage skipped." if is_reply else "Triage skipped via checkbox when session was created."
        sess["completed"].append("triage")
        sess["step_logs"]["triage"] = {
            "ok": True,
            "summary": "Auto-skipped at session start.",
            "detail": "",
            "technical_log": [reason],
        }

    return {
        "session_id": sid,
        "step_order": STEP_ORDER,
        "completed": list(sess["completed"]),
        "step_logs": dict(sess["step_logs"]),
    }


@app.get("/api/session/{sid}")
def get_session(sid: str) -> dict[str, Any]:
    sess = _session_get(sid)
    return {
        "convo_id": sess["convo_id"],
        "email": sess["email"],
        "step_order": STEP_ORDER,
        "completed": sess["completed"],
        "step_logs": sess["step_logs"],
        "options": {
            "skip_triage": sess.get("skip_triage"),
            "skip_helpscout_writes": sess.get("skip_helpscout_writes"),
            "use_live_thread": sess.get("use_live_thread"),
        },
    }


@app.post("/api/session/{sid}/step/{step}")
def run_step(sid: str, step: str) -> dict[str, Any]:
    if step not in STEP_ORDER:
        raise HTTPException(status_code=400, detail="invalid step")

    sess = _session_get(sid)
    idx = STEP_ORDER.index(step)
    if idx > 0:
        prev = STEP_ORDER[idx - 1]
        if prev not in sess["completed"]:
            raise HTTPException(status_code=400, detail=f"complete {prev} first")

    if step in sess["completed"]:
        raise HTTPException(status_code=400, detail="step already completed — start a new session to re-run")

    result = _execute_step(sess, step)
    sess["step_logs"][step] = result
    sess["completed"].append(step)

    return {"step": step, **result}


@app.post("/api/session/{sid}/run-all")
def run_all(sid: str) -> dict[str, Any]:
    sess = _session_get(sid)
    for step in STEP_ORDER:
        if step in sess["completed"]:
            continue
        result = _execute_step(sess, step)
        sess["step_logs"][step] = result
        sess["completed"].append(step)
        if not result["ok"]:
            return {
                "failed_at": step,
                "completed": list(sess["completed"]),
                "step_logs": sess["step_logs"],
            }
    return {
        "failed_at": None,
        "completed": list(sess["completed"]),
        "step_logs": sess["step_logs"],
    }


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return PAGE_HTML


PAGE_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>Support pipeline lab</title>
  <script src="https://cdn.tailwindcss.com"></script>
</head>
<body class="bg-slate-100 text-slate-900 min-h-screen">
  <div class="max-w-4xl mx-auto px-4 py-10">
    <h1 class="text-2xl font-semibold tracking-tight">Support pipeline lab</h1>
    <p class="text-slate-600 mt-1 text-sm">Triage → account lookup → Stripe → policies → Claude draft → Help Scout write.</p>

    <section class="mt-8 bg-white rounded-xl shadow-sm border border-slate-200 p-6">
      <div class="grid gap-4">
        <label class="block text-sm">
          <span class="font-medium text-slate-700">Help Scout conversation ID</span>
          <input id="convo_id" type="text" autofocus
            class="mt-1 w-full border rounded-lg px-3 py-2 font-mono text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
            placeholder="e.g. 123456789"/>
        </label>
        <label class="block text-sm">
          <span class="text-slate-600">Customer email <span class="text-slate-400">(optional — auto-fetched from Help Scout)</span></span>
          <input id="email" type="email"
            class="mt-1 w-full border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
            placeholder="auto-detected from conversation"/>
        </label>
        <div class="flex flex-wrap gap-5 text-sm pt-1">
          <label class="flex items-center gap-2 cursor-pointer select-none">
            <input type="checkbox" id="is_reply" class="rounded"/> Customer reply (not new ticket)
          </label>
          <label class="flex items-center gap-2 cursor-pointer select-none">
            <input type="checkbox" id="skip_triage" class="rounded"/> Skip triage
          </label>
          <label class="flex items-center gap-2 cursor-pointer select-none">
            <input type="checkbox" id="skip_writes" class="rounded"/> Skip Help Scout draft + note
          </label>
        </div>
        <button id="btn_run" type="button"
          class="mt-1 bg-indigo-600 text-white px-5 py-2.5 rounded-lg text-sm font-semibold hover:bg-indigo-700 active:bg-indigo-800 disabled:opacity-50 disabled:cursor-not-allowed">
          Run Pipeline
        </button>
        <p id="session_meta" class="text-xs text-slate-400 font-mono hidden"></p>
      </div>
    </section>

    <section id="steps_wrap" class="mt-8 hidden">
      <div id="steps" class="space-y-3"></div>
    </section>
  </div>

<script>
const STEP_LABELS = {
  triage: "Triage",
  helpscout_snapshot: "Fetch conversation",
  account: "Account lookup",
  stripe: "Stripe enrichment",
  policies: "Load policies",
  claude: "Claude draft",
  helpscout_write: "Write to Help Scout",
  product_prioritization: "Product prioritization",
};

const ORDER = ["triage","helpscout_snapshot","account","stripe","policies","claude","helpscout_write","product_prioritization"];

function statusBadge(log) {
  if (!log) return '<span class="text-xs font-mono px-2 py-0.5 rounded bg-slate-100 text-slate-500">pending</span>';
  return log.ok
    ? '<span class="text-xs font-mono px-2 py-0.5 rounded bg-emerald-100 text-emerald-800">done</span>'
    : '<span class="text-xs font-mono px-2 py-0.5 rounded bg-red-100 text-red-700">failed</span>';
}

function renderSteps(completed, stepLogs) {
  stepLogs = stepLogs || {};
  const root = document.getElementById("steps");
  root.innerHTML = "";
  ORDER.forEach(step => {
    const log = stepLogs[step];
    const done = completed.includes(step);
    const card = document.createElement("div");
    card.className = "bg-white rounded-xl border border-slate-200 shadow-sm overflow-hidden";
    card.innerHTML = `
      <div class="flex items-center justify-between px-4 py-3 cursor-pointer select-none step-header">
        <span class="font-medium text-sm text-slate-800">${STEP_LABELS[step]}</span>
        <div class="flex items-center gap-3">
          ${log ? '<span class="text-xs text-slate-500 truncate max-w-xs">' + escHtml(log.summary || "") + '</span>' : ''}
          ${statusBadge(log)}
          ${done ? '<svg class="w-4 h-4 text-slate-400 chevron" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7"/></svg>' : ''}
        </div>
      </div>
      ${done ? `
      <div class="step-body hidden border-t border-slate-100">
        <pre class="text-xs bg-slate-50 p-4 overflow-auto max-h-96 whitespace-pre-wrap font-mono text-slate-800">${escHtml((log.detail || ""))}</pre>
        ${(log.technical_log || []).length ? `
        <details class="border-t border-slate-200">
          <summary class="text-xs px-4 py-2 cursor-pointer bg-slate-900 text-amber-100 font-medium select-none">Technical / API log</summary>
          <pre class="text-xs p-4 bg-slate-950 text-green-300 overflow-auto max-h-72 whitespace-pre-wrap font-mono leading-relaxed">${escHtml((log.technical_log || []).join("\\n"))}</pre>
        </details>` : ''}
      </div>` : ''}
    `;
    if (done) {
      card.querySelector(".step-header").onclick = () => {
        const body = card.querySelector(".step-body");
        const chev = card.querySelector(".chevron");
        body.classList.toggle("hidden");
        if (chev) chev.style.transform = body.classList.contains("hidden") ? "" : "rotate(180deg)";
      };
    }
    root.appendChild(card);
  });
}

function escHtml(s) {
  return String(s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;");
}

document.getElementById("btn_run").onclick = async () => {
  const convoId = document.getElementById("convo_id").value.trim();
  if (!convoId) { alert("Enter a conversation ID."); return; }

  const btn = document.getElementById("btn_run");
  btn.disabled = true;
  btn.textContent = "Running…";

  const payload = {
    convo_id: convoId,
    email: document.getElementById("email").value.trim(),
    subject: "",
    body: "",
    is_reply: document.getElementById("is_reply").checked,
    skip_triage: document.getElementById("skip_triage").checked,
    skip_helpscout_writes: document.getElementById("skip_writes").checked,
    use_live_thread: true,
  };

  let sid;
  try {
    const r = await fetch("/api/session", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
    if (!r.ok) { alert(await r.text()); return; }
    const data = await r.json();
    sid = data.session_id;
    window.__sid = sid;
    document.getElementById("session_meta").textContent = "session: " + sid;
    document.getElementById("session_meta").classList.remove("hidden");
    document.getElementById("steps_wrap").classList.remove("hidden");
    renderSteps(data.completed || [], data.step_logs || {});
  } catch(e) { alert("Session create failed: " + e); btn.disabled = false; btn.textContent = "Run Pipeline"; return; }

  try {
    const r2 = await fetch(`/api/session/${sid}/run-all`, { method: "POST" });
    const raw = await r2.text();
    let result;
    try { result = JSON.parse(raw); } catch { alert("Bad response: " + raw); return; }
    renderSteps(result.completed || [], result.step_logs || {});
    if (result.failed_at) {
      btn.textContent = "Failed at: " + result.failed_at + " — Run Pipeline";
      btn.disabled = false;
    } else {
      btn.textContent = "Done — Run Again";
      btn.disabled = false;
    }
  } catch(e) { alert("Run-all failed: " + e); btn.disabled = false; btn.textContent = "Run Pipeline"; }
};

document.getElementById("convo_id").addEventListener("keydown", e => {
  if (e.key === "Enter") document.getElementById("btn_run").click();
});
</script>
</body>
</html>
"""


def main() -> None:
    import uvicorn

    host = os.getenv("LAB_BIND", "127.0.0.1")
    port = int(os.getenv("LAB_PORT", "8765"))
    print(f"Open http://{host}:{port}", file=sys.stderr)
    uvicorn.run("lab_app:app", host=host, port=port, reload=False)


if __name__ == "__main__":
    main()
