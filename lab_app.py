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
from account_context import fetch_account_contexts_for_ticket  # noqa: E402
from stripe_context import fetch_stripe_context, format_stripe_context  # noqa: E402
from triage_tickets import run_triage  # noqa: E402

log = logging.getLogger("pipeline_lab")

STEP_ORDER = [
    "triage",
    "helpscout_snapshot",
    "account",
    "stripe",
    "policies",
    "claude",
    "helpscout_write",
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
            sess["hs_customer_id"] = cust.get("id")
            sess["customer_name_hs"] = orch._customer_display_name(cust)
            live_subject = convo.get("subject") or ""
            live_body = orch.get_conversation_text(hs, int(cid)) or ""
            sess["live_subject"] = live_subject
            sess["live_body"] = live_body
            if sess.get("use_live_thread"):
                sess["effective_subject"] = live_subject or subject_in
                sess["effective_body"] = live_body or body_in
            else:
                sess["effective_subject"] = subject_in
                sess["effective_body"] = body_in
            preview = {
                "hs_customer_id": sess["hs_customer_id"],
                "customer_name_hs": sess["customer_name_hs"],
                "customer_email_api": (cust.get("email") or "").strip(),
                "live_subject": live_subject[:500],
                "live_body_preview": _trim(live_body, 4000),
                "effective_subject": sess["effective_subject"][:500],
                "effective_body_preview": _trim(sess["effective_body"], 4000),
                "use_live_thread": sess.get("use_live_thread"),
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
        if not platform or platform.lower() != "stripe":
            sess["stripe_block"] = (
                f"N/A — customer is on {platform or 'unknown'} (not Stripe web billing)"
            )
            tech.append("Stripe API not called (platform is not Stripe).")
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
            user_msg = orch._build_user_prompt(
                ticket_subject=sess.get("effective_subject") or subject_in,
                ticket_body=sess.get("effective_body") or body_in,
                customer_name=cust_name,
                customer_email=email or "(unknown)",
                account_blob=sess.get("account_blob") or "",
                stripe_context=sess.get("stripe_block") or "",
                policy_docs=sess.get("policy_docs") or "",
                agent_name=agent_name,
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
                user_message=user_msg,
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
        note_html = orch._format_internal_note_html(
            parsed=parsed,
            stripe_lines_for_note=(sess.get("stripe_block") or "").replace("\n", "<br/>"),
        )
        lines_out = []
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

        note_uid = os.getenv("HELPSCOUT_NOTE_USER_ID", "").strip()
        if note_uid:
            try:
                hs2 = _helpscout_session(tech)
                note_url = f"{orch.BASE_URL}/conversations/{cid}/notes"
                tech.append(f"POST note user={note_uid}, text HTML chars={len(note_html)}")
                r2 = orch._helpscout_post(
                    hs2,
                    note_url,
                    {"text": note_html, "user": int(note_uid)},
                )
                r2.raise_for_status()
                nid = r2.headers.get("Resource-ID") or r2.headers.get("resource-id")
                lines_out.append(f"Internal note created. Resource-ID: {nid}")
                tech.append(f"Note: HTTP {r2.status_code}, Resource-ID: {nid!r}")
            except requests.HTTPError as e:
                resp = e.response
                extra = ""
                if resp is not None:
                    extra = f"\nResponse body (truncated): {_trim(resp.text, 2000)}"
                tb = traceback.format_exc() + extra
                lines_out.append("Internal note FAILED:\n" + tb)
                tech.append(tb)
            except Exception:
                tb = traceback.format_exc()
                lines_out.append("Internal note FAILED:\n" + tb)
                tech.append(tb)
        else:
            lines_out.append("HELPSCOUT_NOTE_USER_ID unset — note skipped.")
            tech.append("HELPSCOUT_NOTE_USER_ID unset — internal note not POSTed.")

        ok = not any("FAILED" in line for line in lines_out)
        return {"ok": ok, "summary": "Help Scout write step finished.", "detail": "\n\n".join(lines_out), "technical_log": tech}

    return {"ok": False, "summary": "Unknown step.", "detail": step, "technical_log": []}


@app.post("/api/session")
def create_session(payload: dict[str, Any]) -> dict[str, Any]:
    convo_id = str(payload.get("convo_id") or "").strip()
    email = str(payload.get("email") or "").strip()
    subject = str(payload.get("subject") or "").strip()
    body = str(payload.get("body") or "").strip()
    skip_triage = bool(payload.get("skip_triage"))
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
        "skip_triage": skip_triage,
        "skip_helpscout_writes": skip_writes,
        "use_live_thread": use_live,
        "completed": [],
        "step_logs": {},
    }
    _sessions[sid] = sess

    if skip_triage:
        sess["completed"].append("triage")
        sess["step_logs"]["triage"] = {
            "ok": True,
            "summary": "Auto-skipped at session start.",
            "detail": "",
            "technical_log": ["Triage skipped via checkbox when session was created."],
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
    <p class="text-slate-600 mt-1 text-sm">Local only. Step through triage → snapshot → account → Stripe → policies → Claude → Help Scout writes.</p>

    <section class="mt-8 bg-white rounded-xl shadow-sm border border-slate-200 p-6">
      <h2 class="font-medium text-slate-800">1. Inputs</h2>
      <div class="mt-4 grid gap-4">
        <label class="block text-sm">
          <span class="text-slate-600">Help Scout conversation ID</span>
          <input id="convo_id" type="text" class="mt-1 w-full border rounded-lg px-3 py-2 font-mono text-sm" placeholder="e.g. 123456789"/>
        </label>
        <label class="block text-sm">
          <span class="text-slate-600">Customer email (Maven / account lookup)</span>
          <input id="email" type="email" class="mt-1 w-full border rounded-lg px-3 py-2 text-sm" placeholder="customer@example.com"/>
        </label>
        <label class="block text-sm">
          <span class="text-slate-600">Subject (used for Claude unless you use live thread)</span>
          <input id="subject" type="text" class="mt-1 w-full border rounded-lg px-3 py-2 text-sm"/>
        </label>
        <label class="block text-sm">
          <span class="text-slate-600">Body (ticket text for Claude)</span>
          <textarea id="body" rows="6" class="mt-1 w-full border rounded-lg px-3 py-2 text-sm font-mono"></textarea>
        </label>
        <div class="flex flex-wrap gap-4 text-sm">
          <label class="flex items-center gap-2 cursor-pointer"><input type="checkbox" id="skip_triage"/> Skip triage</label>
          <label class="flex items-center gap-2 cursor-pointer"><input type="checkbox" id="skip_writes"/> Skip Help Scout draft + note</label>
          <label class="flex items-center gap-2 cursor-pointer"><input type="checkbox" id="use_live_thread"/> Use live thread subject/body from Help Scout after snapshot</label>
        </div>
        <button id="btn_start" type="button" class="bg-slate-900 text-white px-4 py-2 rounded-lg text-sm font-medium hover:bg-slate-800">Start session</button>
        <p id="session_meta" class="text-xs text-slate-500 font-mono"></p>
      </div>
    </section>

    <section id="steps_wrap" class="mt-8 hidden">
      <h2 class="font-medium text-slate-800 mb-4">2. Run steps in order</h2>
      <div id="steps" class="space-y-4"></div>
    </section>
  </div>

<script>
const STEP_LABELS = {
  triage: "Triage (Help Scout tags / team / Claude triage)",
  helpscout_snapshot: "Fetch conversation (customer id, optional live thread)",
  account: "Account lookup (Maven / configured backend)",
  stripe: "Stripe enrichment (if platform is Stripe)",
  policies: "Load policy markdown corpus",
  claude: "Draft generation (Claude Sonnet)",
  helpscout_write: "Create draft reply + internal note",
};

const ORDER = ["triage","helpscout_snapshot","account","stripe","policies","claude","helpscout_write"];

document.getElementById("btn_start").onclick = async () => {
  const payload = {
    convo_id: document.getElementById("convo_id").value.trim(),
    email: document.getElementById("email").value.trim(),
    subject: document.getElementById("subject").value,
    body: document.getElementById("body").value,
    skip_triage: document.getElementById("skip_triage").checked,
    skip_helpscout_writes: document.getElementById("skip_writes").checked,
    use_live_thread: document.getElementById("use_live_thread").checked,
  };
  const r = await fetch("/api/session", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
  if (!r.ok) { alert(await r.text()); return; }
  const data = await r.json();
  window.__sid = data.session_id;
  document.getElementById("session_meta").textContent = "session_id: " + data.session_id;
  document.getElementById("steps_wrap").classList.remove("hidden");
  renderSteps(data.completed || [], data.step_logs || {});
};

function fillStepCard(card, log) {
  if (!log) return;
  const pre = card.querySelector(".step-out");
  const techD = card.querySelector(".tech-details");
  const techP = card.querySelector(".tech-pre");
  pre.classList.remove("hidden");
  pre.textContent = (log.summary || "") + "\\n\\n" + (log.detail || "");
  const tl = log.technical_log || [];
  if (tl.length) {
    techD.classList.remove("hidden");
    techP.textContent = tl.join("\\n");
  }
}

function renderSteps(completed, stepLogs) {
  stepLogs = stepLogs || {};
  const root = document.getElementById("steps");
  root.innerHTML = "";
  ORDER.forEach((step, i) => {
    const done = completed.includes(step);
    const prev = i === 0 ? true : completed.includes(ORDER[i-1]);
    const unlocked = prev || done;

    const card = document.createElement("div");
    card.className = "step-card bg-white rounded-xl border border-slate-200 p-4 shadow-sm";
    card.innerHTML = `
      <div class="flex flex-wrap items-center justify-between gap-2">
        <h3 class="font-medium text-slate-800">${STEP_LABELS[step]}</h3>
        <span class="step-status text-xs font-mono px-2 py-1 rounded ${done ? "bg-emerald-100 text-emerald-800" : "bg-slate-100 text-slate-600"}">${done ? "done" : unlocked ? "ready" : "locked"}</span>
      </div>
      <p class="text-xs text-slate-500 mt-2">Step: <code>${step}</code></p>
      <div class="mt-3 flex gap-2 items-center">
        <button type="button" class="run-btn bg-indigo-600 text-white text-sm px-3 py-1.5 rounded-lg disabled:opacity-40 disabled:cursor-not-allowed" data-step="${step}" ${done || !unlocked ? "disabled" : ""}>Run step</button>
      </div>
      <pre class="step-out mt-3 text-xs bg-slate-50 border rounded-lg p-3 overflow-auto max-h-96 whitespace-pre-wrap font-mono text-slate-800 hidden"></pre>
      <details class="tech-details mt-2 hidden border border-slate-800 rounded-lg overflow-hidden">
        <summary class="text-xs px-3 py-2 cursor-pointer bg-slate-900 text-amber-100 font-medium select-none">Technical / API log</summary>
        <pre class="tech-pre text-xs p-3 bg-slate-950 text-green-300 overflow-auto max-h-80 whitespace-pre-wrap font-mono leading-relaxed"></pre>
      </details>
    `;
    root.appendChild(card);
    if (done && stepLogs[step]) fillStepCard(card, stepLogs[step]);
  });

  root.querySelectorAll(".run-btn").forEach(btn => {
    btn.onclick = async () => {
      const step = btn.getAttribute("data-step");
      btn.disabled = true;
      const card = btn.closest(".step-card");
      const pre = card.querySelector(".step-out");
      const techD = card.querySelector(".tech-details");
      const techP = card.querySelector(".tech-pre");
      pre.classList.remove("hidden");
      techD.classList.add("hidden");
      pre.textContent = "Running…";
      const r = await fetch(`/api/session/${window.__sid}/step/${step}`, { method: "POST" });
      const raw = await r.text();
      let j;
      try { j = JSON.parse(raw); } catch { pre.textContent = raw; btn.disabled = false; return; }
      if (!r.ok) {
        pre.textContent = raw;
        btn.disabled = false;
        return;
      }
      pre.textContent = (j.summary || "") + "\\n\\n" + (j.detail || "");
      const tl = j.technical_log || [];
      if (tl.length) {
        techD.classList.remove("hidden");
        techP.textContent = tl.join("\\n");
      }
      const st = await fetch(`/api/session/${window.__sid}`);
      const s = await st.json();
      renderSteps(s.completed || [], s.step_logs || {});
    };
  });
}
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
