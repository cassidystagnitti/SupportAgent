"""Bert MCP server — remote MCP endpoint for the `support` marketplace plugin.

Exposes the Bert morning-review pipeline as MCP tools so teammates can run the
full conversational review from a Claude session without any local secrets or
Python. Secrets stay here (this process, deployed on Render alongside the
sidebar); the plugin ships only skills + a pointer to this server.

Run (Render start command — REQUIRES Python >= 3.10, the MCP SDK floor):
    uvicorn mcp_server:app --host 0.0.0.0 --port $PORT

Auth: every request must carry `Authorization: Bearer $SUPPORT_MCP_TOKEN`.
The token is a self-issued shared secret (like SIDEBAR_SECRET) — generate with
`openssl rand -hex 32`, set it here and in each teammate's SUPPORT_MCP_TOKEN.

See docs/superpowers/specs/2026-07-15-support-plugin-mcp-design.md.
"""

from __future__ import annotations

import contextlib
import functools
import hmac
import logging
import os

import anyio
from dotenv import load_dotenv

_SUPPORT_DIR = os.path.dirname(os.path.abspath(__file__))
_ROOT_DIR = os.path.dirname(_SUPPORT_DIR)
load_dotenv(os.path.join(_SUPPORT_DIR, ".env"))
load_dotenv(os.path.join(_ROOT_DIR, ".env"))

from fastapi import FastAPI  # noqa: E402
from mcp.server.fastmcp import FastMCP  # noqa: E402
from starlette.middleware.base import BaseHTTPMiddleware  # noqa: E402
from starlette.responses import JSONResponse, PlainTextResponse  # noqa: E402

from bert import mcp_tools as tools  # noqa: E402

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("bert_mcp")

SUPPORT_MCP_TOKEN = os.getenv("SUPPORT_MCP_TOKEN", "")

mcp = FastMCP("bert")


async def _run(fn, *args, **kwargs):
    """Run a blocking adapter call in a worker thread (keeps the loop free)."""
    return await anyio.to_thread.run_sync(functools.partial(fn, *args, **kwargs))


@mcp.tool()
async def summarize_mailbox(mailbox_id: int | None = None, status: str = "active") -> dict:
    """Fetch every open Help Scout ticket and summarize the mailbox (Haiku).

    Returns {"records": [...], "total": N}. Each record is
    {conversation_id, customer, category, one_line, urgent, is_new,
    matches_known_bug}. Hold the records as the mailbox index and pass them
    back into draft_all. Call this first when starting a support review.
    """
    return await _run(tools.summarize_mailbox, mailbox_id, status)


@mcp.tool()
async def hydrate_ticket(conversation_id: int) -> dict:
    """Pull one ticket's full read-only context for a deep dive.

    Returns subject, customer, email, reply_mode, body, conversation_history,
    account_blob, stripe_block, existing_tags. No writes, no side effects.
    """
    return await _run(tools.hydrate_ticket, conversation_id)


@mcp.tool()
async def research(question: str, account_summary: str = "", platform_hint: str | None = None) -> dict:
    """Investigate a product question across the codebases + Linear.

    Returns {"findings": str, "sources": [str], "tool_calls": int}. Use during
    discussion to settle a bug-truth or product behavior. Fails soft.
    """
    return await _run(tools.research, question, account_summary, platform_hint)


@mcp.tool()
async def draft_all(records: list[dict], brief: str = "", model: str | None = None) -> dict:
    """Draft a reply for every ticket in `records`, injecting the standing `brief`.

    Pass the records from summarize_mailbox and the current standing brief
    (the accumulated truths from the discussion). Returns
    {"run_id", "ready": [...], "review": [...], "counts": {...}} where each
    entry is a compact draft view. Keep the run_id — post_drafts and
    draft_ticket need it. The `review` set is what to walk through together
    (low confidence, needs action, escalations, open questions, suspected bugs).
    """
    return await _run(tools.draft_all, records, brief, model)


@mcp.tool()
async def draft_ticket(run_id: str, conversation_id: int, brief: str = "",
                       model: str | None = None) -> dict:
    """Re-draft one ticket in an existing run after a revision to the brief.

    Updates the stored draft in place and returns its new compact view.
    """
    return await _run(tools.draft_ticket, run_id, conversation_id, brief, model)


@mcp.tool()
async def post_drafts(run_id: str, conversation_ids: list[int] | None = None) -> dict:
    """Post the run's approved drafts to Help Scout as DRAFTS (never auto-sent).

    Omit conversation_ids to post the whole run, or pass a subset. Returns
    {"statuses": [...], "posted": N}; each status reports draft_action,
    threads_updated, note_posted, and any per-ticket error.
    """
    return await _run(tools.post_drafts, run_id, conversation_ids)


@mcp.tool()
async def propose_policy_update(policy_file: str, edit_type: str, target_text: str,
                                new_text: str, rationale: str) -> dict:
    """Build a policy-doc diff card for review (applies nothing yet).

    edit_type is one of the policy_updater edit kinds (e.g. replace / append).
    Returns {id, policy_file, edit_type, diff, status}. Show the diff, then
    confirm with commit_policy once the human approves.
    """
    return await _run(tools.propose_policy_update, policy_file, edit_type,
                      target_text, new_text, rationale)


@mcp.tool()
async def commit_policy(proposal_id: str, source_conversation_id: str | None = None) -> dict:
    """Live-apply + commit an approved policy edit to the repo (single source of truth).

    Pass the proposal id from propose_policy_update. Returns {"commit_sha"}.
    Fails loudly on file drift or GitHub error.
    """
    return await _run(tools.commit_policy, proposal_id, source_conversation_id)


class _BearerAuthMiddleware(BaseHTTPMiddleware):
    """Gate every request on Authorization: Bearer $SUPPORT_MCP_TOKEN."""

    async def dispatch(self, request, call_next):
        if request.url.path == "/health":
            return PlainTextResponse("ok")
        if request.method == "OPTIONS":
            return await call_next(request)
        if not SUPPORT_MCP_TOKEN:
            return JSONResponse({"error": "SUPPORT_MCP_TOKEN not configured on server"}, status_code=500)
        header = request.headers.get("authorization", "")
        supplied = header[7:] if header.lower().startswith("bearer ") else ""
        if not hmac.compare_digest(supplied, SUPPORT_MCP_TOKEN):
            return JSONResponse({"error": "invalid or missing bearer token"}, status_code=401)
        return await call_next(request)


# Serve the MCP endpoint at the sub-app root so it lands at exactly `/mcp`
# once mounted at that prefix (rather than the default `/mcp/mcp`).
mcp.settings.streamable_http_path = "/"

# The MCP ASGI sub-app, gated by the bearer-token middleware. Both deployment
# modes reuse this same instance:
#   1. mounted into sidebar_server.app at /mcp (the live supportagent host), and
#   2. served standalone via `uvicorn mcp_server:app`.
mcp_asgi = mcp.streamable_http_app()
mcp_asgi.add_middleware(_BearerAuthMiddleware)


@contextlib.asynccontextmanager
async def session_lifespan(_app):
    """Run the MCP streamable-HTTP session manager for the host app's lifetime.

    A mounted sub-app's lifespan does NOT run automatically, so whichever
    FastAPI/Starlette app hosts `mcp_asgi` must install this as its lifespan.
    """
    async with mcp.session_manager.run():
        yield


def mount_into(host_app, path: str = "/mcp") -> None:
    """Mount the MCP endpoint onto an existing app at `path` (e.g. /mcp).

    The host app must also use `session_lifespan` as (part of) its lifespan.
    """
    host_app.mount(path, mcp_asgi)


# Standalone app (for `uvicorn mcp_server:app`), equivalent to the mounted form.
app = FastAPI(title="Bert MCP server", lifespan=session_lifespan)


@app.get("/health")
async def _health():
    return {"status": "ok"}


mount_into(app)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8000")))
