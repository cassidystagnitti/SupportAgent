from __future__ import annotations

import json
import logging
from typing import Any

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from support_agent.config import load_settings
from support_agent.draft_service import run_draft_for_conversation
from support_agent.helpscout import HelpScout
from support_agent.webhook_verify import verify_helpscout_webhook_signature

log = logging.getLogger(__name__)

EVENT_CONVO_CREATED = "convo.created"


def _header_event(request: Request) -> str | None:
    return request.headers.get("X-HelpScout-Event") or request.headers.get("x-helpscout-event")


def _header_signature(request: Request) -> str | None:
    return request.headers.get("X-HelpScout-Signature") or request.headers.get("x-helpscout-signature")


async def health(_: Request) -> Response:
    return JSONResponse({"status": "ok"})


async def helpscout_webhook(request: Request) -> Response:
    if request.method != "POST":
        return Response(status_code=405)

    settings = request.app.state.settings
    secret = settings.helpscout_webhook_secret
    if not secret:
        log.error("HELPSCOUT_WEBHOOK_SECRET is not set")
        return JSONResponse({"error": "webhook not configured"}, status_code=500)

    raw = await request.body()
    sig = _header_signature(request)
    if not verify_helpscout_webhook_signature(secret, raw, sig):
        log.warning("invalid webhook signature")
        return JSONResponse({"error": "invalid signature"}, status_code=401)

    event = _header_event(request) or ""
    if event != EVENT_CONVO_CREATED:
        return JSONResponse({"ok": True, "ignored_event": event})

    try:
        payload: dict[str, Any] = json.loads(raw.decode("utf-8") or "{}")
    except json.JSONDecodeError as e:
        log.warning("invalid json body: %s", e)
        return JSONResponse({"error": "invalid json"}, status_code=400)

    conv_id = payload.get("id")
    if conv_id is None:
        return JSONResponse({"ok": True, "skipped": True, "reason": "no_conversation_id"})

    if settings.helpscout_mailbox_id is not None:
        mb = payload.get("mailboxId")
        if mb is not None and int(mb) != settings.helpscout_mailbox_id:
            return JSONResponse(
                {
                    "ok": True,
                    "skipped": True,
                    "reason": "mailbox_filter",
                    "mailboxId": mb,
                }
            )

    hs: HelpScout = request.app.state.helpscout
    try:
        result = run_draft_for_conversation(settings, hs, int(conv_id))
    except Exception:
        log.exception("draft workflow failed for conversation %s", conv_id)
        return JSONResponse({"error": "draft_failed"}, status_code=500)

    return JSONResponse(result)


def build_app() -> Starlette:
    settings = load_settings()
    if not settings.helpscout_webhook_secret:
        raise SystemExit(
            "HELPSCOUT_WEBHOOK_SECRET must be set for the webhook server (same secret you register in Help Scout)"
        )

    app = Starlette(
        routes=[
            Route("/health", health, methods=["GET"]),
            Route("/webhooks/helpscout", helpscout_webhook, methods=["POST"]),
            # alias for providers that mount at root /webhook
            Route("/webhook/helpscout", helpscout_webhook, methods=["POST"]),
        ],
    )
    app.state.settings = settings
    app.state.helpscout = HelpScout(settings.helpscout_client_id, settings.helpscout_client_secret)
    return app
