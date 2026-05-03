"""
Help Scout webhook receiver: verifies signatures and runs triage for new conversations.

Deploy behind HTTPS. Register the URL in Help Scout: Manage → Apps → Webhooks,
or via POST https://api.helpscout.net/v2/webhooks with events + secret.

Environment:
  HELPSCOUT_WEBHOOK_SECRET — same secret configured on the webhook (for signature verification)
  HELPSCOUT_APP_ID, HELPSCOUT_APP_SECRET, ANTHROPIC_API_KEY — same as triage_tickets.py

Run locally (tunnel with ngrok/cloudflared for Help Scout to reach you):
  uvicorn webhook_server:app --host 0.0.0.0 --port 8000
"""

import base64
import hashlib
import hmac
import json
import logging
import os
import threading
from typing import Optional

from dotenv import load_dotenv
from fastapi import FastAPI, Header, HTTPException, Request

from triage_tickets import run_triage

_SUPPORT_DIR = os.path.dirname(os.path.abspath(__file__))
_ROOT_DIR = os.path.dirname(_SUPPORT_DIR)
load_dotenv(os.path.join(_SUPPORT_DIR, ".env"))
load_dotenv(os.path.join(_ROOT_DIR, ".env"))

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("helpscout_webhook")

WEBHOOK_SECRET = os.getenv("HELPSCOUT_WEBHOOK_SECRET", "")

# Subscribe to these in Help Scout. convo.created can arrive before the first
# customer thread exists; add convo.customer.reply.created if triage often sees empty bodies.
TRIAGE_EVENTS = frozenset({
    "convo.created",
    "convo.customer.reply.created",
})

app = FastAPI(title="Help Scout triage webhook")


def _verify_signature(raw_body: bytes, signature: str) -> bool:
    if not WEBHOOK_SECRET or not signature:
        return False
    mac = hmac.new(WEBHOOK_SECRET.encode("utf-8"), raw_body, hashlib.sha1).digest()
    expected = base64.b64encode(mac).decode("ascii")
    return hmac.compare_digest(expected.strip(), signature.strip())


def _conversation_id_from_payload(payload: dict) -> Optional[int]:
    if not isinstance(payload, dict):
        return None
    cid = payload.get("id")
    if cid is None:
        return None
    try:
        return int(cid)
    except (TypeError, ValueError):
        return None


def _run_triage_sync(conversation_id: int) -> None:
    try:
        run_triage(
            conversation_ids=[str(conversation_id)],
            auto_apply=True,
            skip_unassigned_scan=True,
        )
    except Exception:
        log.exception("triage failed for conversation %s", conversation_id)


@app.post("/helpscout/webhook")
async def helpscout_webhook(
    request: Request,
    x_helpscout_event: Optional[str] = Header(None, alias="X-HelpScout-Event"),
    x_helpscout_signature: Optional[str] = Header(None, alias="X-HelpScout-Signature"),
):
    raw = await request.body()

    if not _verify_signature(raw, x_helpscout_signature or ""):
        raise HTTPException(status_code=401, detail="invalid signature")

    event = (x_helpscout_event or "").strip()
    if event not in TRIAGE_EVENTS:
        return {"ok": True, "ignored": True, "event": event or None}

    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        raise HTTPException(status_code=400, detail=f"invalid json: {e}") from e

    cid = _conversation_id_from_payload(payload)
    if cid is None:
        log.warning("no conversation id in payload for event=%s", event)
        return {"ok": True, "skipped": True, "reason": "no conversation id"}

    # Respond immediately so Help Scout does not retry; run triage in a thread.
    threading.Thread(target=_run_triage_sync, args=(cid,), daemon=True).start()
    log.info("queued triage for conversation %s (%s)", cid, event)
    return {"ok": True, "conversation_id": cid, "event": event}


@app.get("/health")
async def health():
    return {"status": "ok"}
