"""
Help Scout Custom App sidebar — per-ticket chat with Bert.

Deploy as the Render start command:
  uvicorn sidebar_server:app --host 0.0.0.0 --port $PORT

Help Scout loads https://<render-host>/sidebar in the conversation-view iframe
(postMessage handshake supplies the conversation id). The page is a chat UI:
Bert answers with fully hydrated ticket context, edits the HS draft in place
via tool calls, proposes policy-doc updates as diff cards (Confirm commits to
GitHub — the single source of truth for policies), and a Send & close button
publishes the draft and closes the conversation as the Support Automations
agent user.

Environment:
  SIDEBAR_SECRET             — random string; required on every chat endpoint call
  HELPSCOUT_AGENT_USER_ID    — HS user for chat-created drafts (falls back to
                               HELPSCOUT_NOTE_USER_ID)
  GITHUB_TOKEN / GITHUB_REPO / GITHUB_BRANCH — policy-update commits
  (all other pipeline env vars apply as documented in CLAUDE.md)
"""

import hmac
import json
import logging
import os
import re
import threading

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse

_SUPPORT_DIR = os.path.dirname(os.path.abspath(__file__))
_ROOT_DIR = os.path.dirname(_SUPPORT_DIR)
load_dotenv(os.path.join(_SUPPORT_DIR, ".env"))
load_dotenv(os.path.join(_ROOT_DIR, ".env"))

import orchestrator  # noqa: E402
import policy_updater  # noqa: E402
import sidebar_chat  # noqa: E402
from bert import pipeline as bert_pipeline  # noqa: E402

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("helpscout_sidebar")

SIDEBAR_SECRET = os.getenv("SIDEBAR_SECRET", "")

# Mount the Bert MCP server onto this same service so `/mcp` is served on the
# existing supportagent host (no separate Render service). Fully guarded: if the
# MCP SDK is missing (e.g. Python < 3.10 on the dev box) or the wiring fails, the
# sidebar keeps serving normally and `/mcp` simply 404s.
try:
    import mcp_server  # noqa: E402
    _mcp_lifespan = mcp_server.session_lifespan
    log.info("Bert MCP server available — mounting at /mcp")
except Exception as e:  # pragma: no cover - depends on runtime Python / deps
    mcp_server = None
    _mcp_lifespan = None
    log.warning("Bert MCP server unavailable, /mcp disabled: %s", e)

app = FastAPI(title="Help Scout sidebar app", lifespan=_mcp_lifespan)

if mcp_server is not None:
    try:
        mcp_server.mount_into(app, "/mcp")
    except Exception as e:  # pragma: no cover
        log.warning("Failed to mount Bert MCP server at /mcp: %s", e)


def _check_secret(supplied: str) -> None:
    if not SIDEBAR_SECRET:
        raise HTTPException(status_code=500, detail="SIDEBAR_SECRET not configured on server")
    if not hmac.compare_digest(str(supplied or ""), SIDEBAR_SECRET):
        raise HTTPException(status_code=401, detail="invalid secret")


def _require_cid(raw) -> str:
    cid = str(raw or "").strip()
    if not cid.isdigit():
        raise HTTPException(status_code=400, detail="conversation_id must be a numeric string")
    return cid


async def _json_body(request: Request) -> dict:
    try:
        return await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="invalid JSON body")


@app.post("/chat/message", status_code=202)
async def chat_message(request: Request):
    body = await _json_body(request)
    _check_secret(body.get("secret"))
    cid = _require_cid(body.get("conversation_id"))
    text = str(body.get("text") or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="text is required")

    _, acquired = sidebar_chat.STORE.try_acquire(cid)
    if not acquired:
        raise HTTPException(status_code=409, detail="Bert is still working on the last message")

    threading.Thread(
        target=sidebar_chat.run_turn,
        args=(sidebar_chat.STORE, cid, text),
        daemon=True,
    ).start()
    return {"ok": True, "conversation_id": cid, "status": "started"}


@app.get("/chat/messages/{cid}")
async def chat_messages(cid: str, after: int = 0, secret: str = ""):
    _check_secret(secret)
    cid = _require_cid(cid)
    sess = sidebar_chat.STORE.peek(cid)
    if sess is None:
        # No session yet — draft state unknown here; the frontend does a one-time
        # live check via /chat/draft-state instead (poll must stay HS-API-free).
        return {"messages": [], "busy": False, "draft": None}
    messages = sidebar_chat.STORE.ui_messages_after(cid, after)
    for m in messages:  # overlay live proposal status so reloads render correctly
        if m["kind"] == "proposal" and m.get("payload"):
            p = sess["proposals"].get(m["payload"].get("proposal_id"))
            if p:
                m["payload"] = dict(m["payload"], status=p["status"])
    thread_id = sess.get("draft_thread_id")
    return {
        "messages": messages,
        "busy": bool(sess.get("busy")),
        "draft": {"exists": thread_id is not None, "thread_id": thread_id},
    }


@app.get("/chat/draft-state/{cid}")
async def draft_state(cid: str, secret: str = ""):
    """One-time live draft check for a freshly opened sidebar (no chat session yet)."""
    _check_secret(secret)
    cid = _require_cid(cid)
    hs = sidebar_chat._hs_session()
    draft_ids = bert_pipeline.find_draft_threads(hs, cid)
    thread_id = draft_ids[-1] if draft_ids else None
    return {"exists": thread_id is not None, "thread_id": thread_id}


def _find_proposal(cid: str, proposal_id: str) -> dict:
    sess = sidebar_chat.STORE.peek(cid)
    proposal = (sess or {}).get("proposals", {}).get(str(proposal_id or ""))
    if proposal is None:
        raise HTTPException(status_code=404, detail="unknown proposal")
    return proposal


@app.post("/chat/confirm-policy")
async def confirm_policy(request: Request):
    body = await _json_body(request)
    _check_secret(body.get("secret"))
    cid = _require_cid(body.get("conversation_id"))
    proposal = _find_proposal(cid, body.get("proposal_id"))
    if proposal["status"] != "pending":
        raise HTTPException(status_code=409, detail=f"proposal is {proposal['status']}")
    try:
        outcome = policy_updater.confirm_proposal(proposal, conversation_id=cid)
    except Exception as e:
        log.exception("policy confirm failed for cid=%s", cid)
        sidebar_chat.STORE.add_ui_message(
            cid, "error",
            f"Policy update failed: {str(e)[:200]} — nothing was committed. Try Confirm again.")
        raise HTTPException(status_code=502, detail=str(e)[:300])
    sidebar_chat.STORE.add_ui_message(
        cid, "event",
        f"Policy updated: {proposal['policy_file']} committed ({outcome['commit_sha'][:7]}).")
    return {"ok": True, "commit_sha": outcome["commit_sha"]}


@app.post("/chat/dismiss-policy")
async def dismiss_policy(request: Request):
    body = await _json_body(request)
    _check_secret(body.get("secret"))
    cid = _require_cid(body.get("conversation_id"))
    proposal = _find_proposal(cid, body.get("proposal_id"))
    proposal["status"] = "dismissed"
    return {"ok": True}


def _normalize_html(s: str) -> str:
    """Strip tags + whitespace so cosmetic HS normalization doesn't trip the guard."""
    return re.sub(r"<[^>]+>|\s+|&nbsp;", "", s or "")


def _hs_error_detail(resp) -> str:
    """Best-effort human-readable reason from a Help Scout error response.

    HS error bodies look like
      {"message": "...", "_embedded": {"errors": [{"path": "...", "message": "..."}]}}.
    Falls back to the raw (truncated) body, then the bare status code.
    """
    try:
        data = resp.json()
    except Exception:
        return (getattr(resp, "text", "") or "").strip()[:300] or f"HTTP {resp.status_code}"
    msg = (data.get("message") or "").strip()
    field_errs = [
        "; ".join(str(e.get(k)) for k in ("path", "message") if e.get(k))
        for e in ((data.get("_embedded") or {}).get("errors") or [])
    ]
    field_errs = [p for p in field_errs if p]
    if msg and field_errs:
        detail = f"{msg} ({'; '.join(field_errs)})"
    else:
        detail = msg or "; ".join(field_errs)
    return (detail or f"HTTP {resp.status_code}").strip()[:400]


@app.post("/chat/send")
async def chat_send(request: Request):
    body = await _json_body(request)
    _check_secret(body.get("secret"))
    cid = _require_cid(body.get("conversation_id"))
    force = bool(body.get("force"))
    close_only = bool(body.get("close_only"))

    hs = sidebar_chat._hs_session()
    status = bert_pipeline.conversation_status(hs, cid)
    if status == "closed":
        raise HTTPException(status_code=400, detail="conversation is already closed")

    sent = False
    if not close_only:
        draft_ids = bert_pipeline.find_draft_threads(hs, cid)
        if not draft_ids:
            raise HTTPException(status_code=400, detail="no draft to send on this conversation")
        thread_id = draft_ids[-1]

        sess = sidebar_chat.STORE.peek(cid)
        chat_draft = (sess or {}).get("draft_text") or ""
        if chat_draft and not force:
            live_body = sidebar_chat._thread_body(hs, int(cid), thread_id)
            if _normalize_html(live_body) != _normalize_html(chat_draft):
                raise HTTPException(
                    status_code=409,
                    detail="draft was edited outside this chat — review it, then Send anyway",
                )

        r_pub = hs.patch(
            f"{orchestrator.BASE_URL}/conversations/{cid}/threads/{thread_id}/schedule",
            json={"op": "replace", "path": "/state", "value": "published"},
        )
        if not r_pub.ok:
            reason = _hs_error_detail(r_pub)
            # Surface the real Help Scout reason instead of an opaque 500, and log
            # the full response body so the underlying cause is diagnosable. The
            # conversation stays open — nothing was sent.
            log.error(
                "publish failed for cid=%s thread=%s: HTTP %s — %s",
                cid, thread_id, r_pub.status_code, (getattr(r_pub, "text", "") or "")[:1000],
            )
            raise HTTPException(
                status_code=502,
                detail=f"Help Scout rejected the send (HTTP {r_pub.status_code}): {reason}",
            )
        sent = True

    try:
        r_close = hs.patch(
            f"{orchestrator.BASE_URL}/conversations/{cid}",
            json={"op": "replace", "path": "/status", "value": "closed"},
        )
        r_close.raise_for_status()
    except Exception as e:
        log.exception("close failed for cid=%s (sent=%s)", cid, sent)
        sidebar_chat.STORE.add_ui_message(
            cid, "error",
            f"Reply {'sent' if sent else 'not sent'}, but closing failed: {str(e)[:150]} — retry close.")
        return {"ok": False, "sent": sent, "closed": False, "error": str(e)[:300]}

    sidebar_chat.STORE.add_ui_message(
        cid, "event",
        "Reply sent and conversation closed." if sent else "Conversation closed.")
    return {"ok": True, "sent": sent, "closed": True}


_SIDEBAR_HTML_PATH = os.path.join(_SUPPORT_DIR, "static", "sidebar.html")


def _render_sidebar(cid: str, email: str) -> HTMLResponse:
    with open(_SIDEBAR_HTML_PATH, encoding="utf-8") as f:
        html = f.read()
    html = (
        html
        .replace("__CID__", json.dumps(cid))
        .replace("__EMAIL__", json.dumps(email))
        .replace("__SECRET__", json.dumps(SIDEBAR_SECRET))
    )
    return HTMLResponse(html)


@app.post("/sidebar", response_class=HTMLResponse)
async def sidebar_post(request: Request):
    """
    Help Scout POSTs form-encoded context here when an agent opens a conversation.
    Fields: conversation[id], customer[email], customer[fname], customer[lname],
            mailbox[id], timestamp, signature.
    """
    form = await request.form()
    cid = str(form.get("conversation[id]") or "").strip()
    email = str(form.get("customer[email]") or "").strip()

    if not cid or not cid.isdigit():
        return HTMLResponse(
            "<p style='font-family:sans-serif;padding:16px'>No conversation id received from Help Scout.</p>",
            status_code=400,
        )
    return _render_sidebar(cid, email)


@app.get("/sidebar", response_class=HTMLResponse)
async def sidebar_get(request: Request):
    """
    Loaded by Help Scout as an iframe (GET, no params).
    The page uses postMessage to request context from Help Scout.
    Pass ?id=12345 to bypass the SDK for local testing.
    """
    cid = str(request.query_params.get("id") or "").strip()
    email = str(request.query_params.get("customer_email") or "").strip()
    return _render_sidebar(cid, email)


# Root aliases: a Help Scout app configured with the bare host (no /sidebar
# path) used to get FastAPI's JSON 404 in the iframe. Serve the sidebar there too.
@app.post("/", response_class=HTMLResponse, include_in_schema=False)
async def sidebar_post_root(request: Request):
    return await sidebar_post(request)


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
async def sidebar_get_root(request: Request):
    return await sidebar_get(request)


@app.get("/health")
async def health():
    return {"status": "ok"}
