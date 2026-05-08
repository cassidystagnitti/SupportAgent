"""
Help Scout Custom App sidebar — triggers the AI draft pipeline from the HS sidebar.

Deploy this as the Render start command:
  uvicorn sidebar_server:app --host 0.0.0.0 --port $PORT

Configure the Help Scout app URL as a plain static URL (no template variables):
  https://<your-render-host>/sidebar

Help Scout POSTs form-encoded context to that URL when an agent opens a conversation.
The response HTML is rendered in the sidebar iframe.

Environment:
  SIDEBAR_SECRET            — random string you generate; sent with every /trigger-draft
                               POST so random callers can't spam the pipeline
  HELPSCOUT_APP_ID          — same as the rest of the pipeline
  HELPSCOUT_APP_SECRET      — same as the rest of the pipeline
  ANTHROPIC_API_KEY         — same as the rest of the pipeline
  (all other pipeline env vars apply as documented in CLAUDE.md)
"""

import hashlib
import hmac
import json
import logging
import os
import threading
from datetime import datetime, timezone
from typing import Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse

from orchestrator import process_ticket_sync

_SUPPORT_DIR = os.path.dirname(os.path.abspath(__file__))
_ROOT_DIR = os.path.dirname(_SUPPORT_DIR)
load_dotenv(os.path.join(_SUPPORT_DIR, ".env"))
load_dotenv(os.path.join(_ROOT_DIR, ".env"))

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("helpscout_sidebar")

SIDEBAR_SECRET = os.getenv("SIDEBAR_SECRET", "")

_status: dict[str, dict] = {}
_status_lock = threading.Lock()
_MAX_STATUS_ENTRIES = 500


def _set_status(cid: str, status: str, message: str = "") -> None:
    with _status_lock:
        _status[cid] = {
            "status": status,
            "message": message,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        if len(_status) > _MAX_STATUS_ENTRIES:
            del _status[next(iter(_status))]


def _get_status(cid: str) -> dict:
    with _status_lock:
        return dict(_status.get(cid, {"status": "idle"}))


def _run_pipeline(cid: str, email: Optional[str]) -> None:
    try:
        result = process_ticket_sync(cid, email)
        if result.get("escalated"):
            _set_status(cid, "done", "Escalation flagged — check the internal note")
        else:
            _set_status(cid, "done", "Draft created — check the Reply editor")
    except Exception as e:
        _set_status(cid, "error", str(e)[:300])
        log.exception("sidebar pipeline failed for conversation %s", cid)


app = FastAPI(title="Help Scout sidebar app")


_SIDEBAR_HTML = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>AI Draft</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    font-size: 13px;
    color: #333;
    background: #fff;
    padding: 16px;
  }
  h2 { font-size: 14px; font-weight: 600; color: #1a1a1a; margin-bottom: 4px; }
  .conv-id { font-size: 11px; color: #999; margin-bottom: 14px; }
  button {
    width: 100%;
    padding: 9px 14px;
    background: #1f73b7;
    color: #fff;
    border: none;
    border-radius: 4px;
    font-size: 13px;
    font-weight: 500;
    cursor: pointer;
    transition: background 0.15s;
  }
  button:hover:not(:disabled) { background: #1a62a0; }
  button:disabled { background: #8ab4d6; cursor: default; }
  #status {
    margin-top: 12px;
    padding: 10px 12px;
    border-radius: 4px;
    font-size: 12px;
    line-height: 1.5;
    display: none;
  }
  .running { background: #f0f7ff; color: #1f73b7; border: 1px solid #c1daf4; }
  .done    { background: #f0faf0; color: #2e7d32; border: 1px solid #a8d5a2; }
  .error   { background: #fff4f4; color: #c62828; border: 1px solid #f5c0c0; }
  #loading { font-size: 12px; color: #999; }
  .spinner {
    display: inline-block;
    width: 11px; height: 11px;
    border: 2px solid currentColor;
    border-top-color: transparent;
    border-radius: 50%;
    animation: spin 0.7s linear infinite;
    vertical-align: middle;
    margin-right: 6px;
  }
  @keyframes spin { to { transform: rotate(360deg); } }
</style>
</head>
<body>
<h2>AI Draft Generator</h2>
<p class="conv-id">Conversation #<span id="cid-label">…</span></p>
<div id="loading"><span class="spinner"></span>Connecting to Help Scout…</div>
<button id="btn" onclick="generate()" style="display:none">Generate Draft</button>
<div id="status"></div>
<script>
var CID    = __CID__;
var EMAIL  = __EMAIL__;
var SECRET = __SECRET__;
var pollTimer = null;

// If the server already injected a CID (POST path or ?id= test param), use it immediately.
if (CID) {
  ready(CID, EMAIL);
} else {
  // Ask Help Scout for context via postMessage (SDK protocol).
  var ALLOWED_ORIGINS = [
    'https://secure.helpscout.net',
    /^https:\/\/hs-app\..+\.hsenv\.io$/
  ];
  function isAllowed(origin) {
    return ALLOWED_ORIGINS.some(function(o) {
      return typeof o === 'string' ? o === origin : o.test(origin);
    });
  }
  window.addEventListener('message', function(event) {
    if (!isAllowed(event.origin)) return;
    var data = event.data;
    if (!data || data.type !== 'SEND_APP_CONTEXT') return;
    var cid = data.conversation && String(data.conversation.id);
    var emails = data.customer && data.customer.emails;
    var email = (emails && emails.length > 0 && emails[0].value) || '';
    if (cid) ready(cid, email);
  });
  // Send the context request to the Help Scout parent frame.
  var appId = (window.name || '').replace(/app-side-panel-|app-/, '');
  window.parent.postMessage(
    { type: 'GET_APP_CONTEXT', appId: appId, iframeId: window.name || '' },
    document.referrer || '*'
  );
}

function ready(cid, email) {
  CID   = cid;
  EMAIL = email;
  document.getElementById('cid-label').textContent = CID;
  document.getElementById('loading').style.display = 'none';
  document.getElementById('btn').style.display     = 'block';
}

async function generate() {
  var btn = document.getElementById('btn');
  btn.disabled = true;
  btn.textContent = 'Generating…';
  showStatus('running', 'Running pipeline — this takes 20–40 seconds…');

  try {
    var resp = await fetch('/trigger-draft', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ conversation_id: CID, customer_email: EMAIL, secret: SECRET })
    });
    if (!resp.ok) {
      var txt = await resp.text();
      showStatus('error', 'Request failed: ' + txt);
      resetBtn('Retry');
      return;
    }
    startPolling();
  } catch (e) {
    showStatus('error', 'Network error: ' + e.message);
    resetBtn('Retry');
  }
}

function startPolling() {
  if (pollTimer) clearInterval(pollTimer);
  pollTimer = setInterval(async function() {
    try {
      var resp = await fetch('/trigger-status/' + encodeURIComponent(CID));
      var data = await resp.json();
      if (data.status === 'done') {
        clearInterval(pollTimer);
        showStatus('done', '✓ ' + (data.message || 'Draft created — check the Reply editor'));
        resetBtn('Regenerate');
      } else if (data.status === 'error') {
        clearInterval(pollTimer);
        showStatus('error', '✗ ' + (data.message || 'Pipeline failed — check server logs'));
        resetBtn('Retry');
      }
    } catch (_) { /* network hiccup — keep polling */ }
  }, 3000);
}

function showStatus(cls, msg) {
  var el = document.getElementById('status');
  el.className = cls;
  el.style.display = 'block';
  el.innerHTML = cls === 'running'
    ? '<span class=\\'spinner\\'></span>' + msg
    : msg;
}

function resetBtn(label) {
  var btn = document.getElementById('btn');
  btn.disabled = false;
  btn.textContent = label;
}
</script>
</body>
</html>
"""


def _render_sidebar(cid: str, email: str) -> HTMLResponse:
    html = (
        _SIDEBAR_HTML
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


@app.post("/trigger-draft")
async def trigger_draft(request: Request):
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="invalid JSON body")

    if not SIDEBAR_SECRET:
        raise HTTPException(status_code=500, detail="SIDEBAR_SECRET not configured on server")

    if not hmac.compare_digest(str(body.get("secret", "")), SIDEBAR_SECRET):
        raise HTTPException(status_code=401, detail="invalid secret")

    cid = str(body.get("conversation_id", "")).strip()
    if not cid or not cid.isdigit():
        raise HTTPException(status_code=400, detail="conversation_id must be a numeric string")

    with _status_lock:
        if _status.get(cid, {}).get("status") == "running":
            return {"ok": True, "conversation_id": cid, "status": "already_running"}

    _set_status(cid, "running")
    email: Optional[str] = body.get("customer_email") or None
    threading.Thread(target=_run_pipeline, args=(cid, email), daemon=True).start()
    log.info("sidebar triggered pipeline for conversation %s", cid)
    return {"ok": True, "conversation_id": cid, "status": "started"}


@app.get("/trigger-status/{conversation_id}")
async def trigger_status(conversation_id: str):
    return _get_status(conversation_id)


@app.get("/health")
async def health():
    return {"status": "ok"}
