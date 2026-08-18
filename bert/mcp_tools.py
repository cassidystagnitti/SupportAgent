"""Backend adapter for the Bert MCP server.

Every function here is a thin wrapper over the existing pipeline
(`bert.summarize`, `bert.pipeline`, `bert.fanout`, `research_agent`,
`policy_updater`). No MCP dependency lives in this module on purpose: it stays
importable and unit-testable on any Python (including the 3.9 dev machine),
while `mcp_server.py` supplies the FastMCP transport + auth on top.

Design notes (see docs/superpowers/specs/2026-07-15-support-plugin-mcp-design.md):
- Heavy draft "result" objects (they carry `parsed`, `stripe_ctx`, …) never
  round-trip through the client. `draft_all` stashes them in an ephemeral
  server-side RunStore keyed by a `run_id` and returns a COMPACT review view;
  `post_drafts` / `draft_ticket` operate on the stored results by `run_id`.
- Policy proposals are likewise stashed by id; `commit_policy` looks them up.
- Every tool returns JSON-serializable primitives only.
"""

from __future__ import annotations

import os
import threading
import uuid
from collections import OrderedDict
from datetime import datetime, timezone
from typing import Any

import anthropic
import requests

import orchestrator
import policy_updater
import research_agent
from bert import actions as bert_actions
from bert import fanout as bert_fanout
from bert import pipeline as bert_pipeline
from bert import summarize as bert_summarize

DRAFT_MODEL = os.getenv("BERT_DRAFT_MODEL", "claude-sonnet-5")

_MAX_RUNS = 50
_MAX_PROPOSALS = 200


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# --- shared clients -------------------------------------------------------

def _hs_session() -> requests.Session:
    """Authenticated Help Scout session (mirrors sidebar_chat._hs_session)."""
    token = orchestrator.get_access_token()
    s = requests.Session()
    s.headers.update({"Authorization": f"Bearer {token}"})
    return s


def _anthropic_client() -> anthropic.Anthropic:
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY not configured on the MCP server")
    return anthropic.Anthropic(api_key=api_key)


# --- ephemeral server-side state ------------------------------------------

class _LRU:
    """Tiny thread-safe LRU map. Values are opaque."""

    def __init__(self, max_items: int):
        self._d: "OrderedDict[str, Any]" = OrderedDict()
        self._lock = threading.Lock()
        self._max = max_items

    def put(self, key: str, value: Any) -> None:
        with self._lock:
            self._d[key] = value
            self._d.move_to_end(key)
            while len(self._d) > self._max:
                self._d.popitem(last=False)

    def get(self, key: str) -> Any:
        with self._lock:
            if key not in self._d:
                return None
            self._d.move_to_end(key)
            return self._d[key]


_RUNS = _LRU(_MAX_RUNS)
_PROPOSALS = _LRU(_MAX_PROPOSALS)


# --- compact views --------------------------------------------------------

def _review_reasons(result: dict) -> list[str]:
    """Human-readable reasons a draft landed in the review bucket."""
    reasons = []
    if not result.get("ok"):
        reasons.append("draft_failed")
    if result.get("confidence") in (None, "low"):
        reasons.append("low_confidence")
    if result.get("needs_action"):
        reasons.append("needs_action")
    if result.get("escalate"):
        reasons.append("escalate")
    if result.get("open_question"):
        reasons.append("open_question")
    bug = result.get("bug_report")
    if isinstance(bug, dict) and bug.get("is_bug"):
        reasons.append("suspected_bug")
    return reasons


def _compact_draft(result: dict, customer: str | None) -> dict:
    """The client-facing view of one drafted ticket (no heavy objects)."""
    reasons = _review_reasons(result)
    return {
        "conversation_id": result.get("conversation_id"),
        "customer": customer,
        "ok": bool(result.get("ok")),
        "error": result.get("error"),
        "confidence": result.get("confidence"),
        "needs_action": bool(result.get("needs_action")),
        "escalate": bool(result.get("escalate")),
        "open_question": result.get("open_question"),
        "bug_report": result.get("bug_report"),
        "referenced_policies": result.get("referenced_policies") or [],
        "reasoning": result.get("reasoning"),
        "draft_reply": result.get("draft_reply") or "",
        "needs_review": bool(reasons),
        "review_reasons": reasons,
    }


# --- tools ----------------------------------------------------------------

def summarize_mailbox(mailbox_id: int | None = None, status: str = "active") -> dict:
    """Fetch open tickets and summarize them (Haiku map/reduce).

    Returns {"records": [ {conversation_id, customer, category, one_line,
    urgent, is_new, matches_known_bug}, … ], "total": N}. The client holds the
    records as the mailbox index and passes them back into draft_all.
    """
    session = _hs_session()
    client = _anthropic_client()
    tickets = bert_summarize.fetch_open_tickets(session, mailbox_id, status=status)
    known_bugs = bert_summarize.known_bug_catalog()
    records = bert_summarize.summarize_mailbox(tickets, client, known_bugs=known_bugs)
    return {"records": records, "total": len(records)}


def hydrate_ticket(conversation_id: int) -> dict:
    """Full read-only context for one ticket (a deep dive). No writes.

    Drops non-serializable enrichment objects (`stripe_ctx`) and keeps the
    formatted, human-readable fields.
    """
    session = _hs_session()
    ctx = bert_pipeline.hydrate_ticket(session, int(conversation_id))
    return {
        "conversation_id": ctx.get("conversation_id"),
        "subject": ctx.get("subject"),
        "customer_name": ctx.get("customer_name"),
        "hs_customer_id": ctx.get("hs_customer_id"),
        "email": ctx.get("email"),
        "reply_mode": ctx.get("reply_mode"),
        "body": ctx.get("body"),
        "conversation_history": ctx.get("conversation_history", ""),
        "account_blob": ctx.get("account_blob", ""),
        "stripe_block": ctx.get("stripe_block", ""),
        "stripe_customer_id": (ctx.get("stripe_ctx") or {}).get("stripe_customer_id"),
        "existing_tags": ctx.get("existing_tags", []),
    }


def cancel_subscription(conversation_id: int) -> dict:
    """Execute cancel-at-period-end for the ticket's own Stripe customer.

    The customer is resolved SERVER-SIDE by re-hydrating the conversation —
    a client-supplied customer id is never accepted, so this tool cannot act
    outside the named ticket. Eligibility, env gates, audit line, and the
    executed-note all come from bert.actions (same pipeline as the CLI).
    """
    session = _hs_session()
    ctx = bert_pipeline.hydrate_ticket(session, int(conversation_id))
    customer_id = ((ctx.get("stripe_ctx") or {}).get("stripe_customer_id") or "").strip()
    if not customer_id:
        return {
            "status": "refused",
            "reason": "no Stripe customer attached to this ticket "
            "(customer may be on Apple/Google or unmatched) — manual action.",
        }
    return bert_actions.cancel_subscription(
        customer_id, str(conversation_id), actor="mcp", hs=session
    )


def reactivate_subscription(conversation_id: int) -> dict:
    """Restore auto-renew (un-cancel) for the ticket's own Stripe customer.

    Same server-side customer resolution as ``cancel_subscription``: the
    conversation is re-hydrated and a client-supplied customer id is never
    accepted. Unlike cancelling, this RE-ARMS a renewal charge — the caller is
    responsible for having the customer's word that they want to stay.
    """
    session = _hs_session()
    ctx = bert_pipeline.hydrate_ticket(session, int(conversation_id))
    customer_id = ((ctx.get("stripe_ctx") or {}).get("stripe_customer_id") or "").strip()
    if not customer_id:
        return {
            "status": "refused",
            "reason": "no Stripe customer attached to this ticket "
            "(customer may be on Apple/Google or unmatched) — manual action.",
        }
    return bert_actions.reactivate_subscription(
        customer_id, str(conversation_id), actor="mcp", hs=session
    )


def link_email(conversation_id: int, email: str) -> dict:
    """Add another address to this ticket's Help Scout contact (merging if needed).

    Help Scout CRM only — it does not merge Happier accounts, move a
    subscription, or copy meditation history.
    """
    session = _hs_session()
    ctx = bert_pipeline.hydrate_ticket(session, int(conversation_id))
    return bert_actions.link_customer_email(
        str(conversation_id), email, ctx.get("hs_customer_id"), actor="mcp", hs=session
    )


def research(question: str, account_summary: str = "", platform_hint: str | None = None) -> dict:
    """Investigate a product question across the codebases + Linear.

    Returns {"findings": str, "sources": [str], "tool_calls": int}. Fails soft.
    """
    return research_agent.run_research(question, account_summary, platform_hint)


def draft_all(records: list[dict], brief: str = "", model: str | None = None) -> dict:
    """Draft every ticket in `records` with the standing `brief`.

    Stashes the full results server-side under a fresh run_id and returns
    {"run_id", "ready": [compact], "review": [compact], "counts": {...}}.
    """
    if not isinstance(records, list) or not records:
        raise ValueError("records must be a non-empty list of mailbox records")
    session = _hs_session()
    client = _anthropic_client()
    results = bert_fanout.draft_all(records, session, client, brief or "", model=model or DRAFT_MODEL)

    run_id = uuid.uuid4().hex[:12]
    results_by_cid = {str(r.get("conversation_id")): r for r in results}
    customer_by_cid = {str(rec.get("conversation_id")): rec.get("customer") for rec in records}
    _RUNS.put(run_id, {
        "created_at": _now_iso(),
        "brief": brief or "",
        "records": records,
        "customer_by_cid": customer_by_cid,
        "results_by_cid": results_by_cid,
    })

    part = bert_fanout.partition(results)
    ready = [_compact_draft(r, customer_by_cid.get(str(r.get("conversation_id")))) for r in part["ready"]]
    review = [_compact_draft(r, customer_by_cid.get(str(r.get("conversation_id")))) for r in part["review"]]
    close = [_compact_draft(r, customer_by_cid.get(str(r.get("conversation_id")))) for r in part["close"]]
    return {
        "run_id": run_id,
        "ready": ready,
        "review": review,
        "close": close,
        "counts": {"total": len(results), "ready": len(ready), "review": len(review),
                   "close": len(close)},
    }


def draft_ticket(run_id: str, conversation_id: int, brief: str = "", model: str | None = None) -> dict:
    """Re-draft one ticket in an existing run (after a revision).

    Updates the stored result in place and returns the new compact view.
    """
    run = _RUNS.get(run_id)
    if not run:
        raise ValueError(f"unknown run_id {run_id!r} (it may have expired)")
    cid = str(conversation_id)
    record = next((r for r in run["records"] if str(r.get("conversation_id")) == cid), None)
    if record is None:
        record = {"conversation_id": conversation_id}
    session = _hs_session()
    client = _anthropic_client()
    results = bert_fanout.draft_all([record], session, client, brief or run.get("brief") or "",
                                    model=model or DRAFT_MODEL)
    result = results[0]
    run["results_by_cid"][cid] = result
    return _compact_draft(result, run["customer_by_cid"].get(cid))


def post_drafts(run_id: str, conversation_ids: list[int] | None = None) -> dict:
    """Post the run's drafts to Help Scout (draft only — never auto-send).

    With `conversation_ids`, posts only those; otherwise posts all in the run.
    Auto-send candidates go through the verifier stage (bert/verify.py); the
    auto_send tag follows the verdict. Returns {"statuses": [ apply_result
    status, … ]} — including verify_verdict / verify_findings per ticket.
    """
    run = _RUNS.get(run_id)
    if not run:
        raise ValueError(f"unknown run_id {run_id!r} (it may have expired)")
    session = _hs_session()
    try:
        client = _anthropic_client()
    except Exception:
        # Posting must not require the Anthropic key — candidates just stay
        # unverified (and therefore untagged).
        client = None
    ts = _now_iso()
    if conversation_ids:
        wanted = {str(c) for c in conversation_ids}
        results = [run["results_by_cid"][c] for c in wanted if c in run["results_by_cid"]]
    else:
        results = list(run["results_by_cid"].values())
    statuses = [bert_fanout.apply_result(session, r, timestamp=ts,
                                         verify_client=client, brief=run.get("brief") or "")
                for r in results]
    return {"statuses": statuses, "posted": len(statuses)}


def propose_policy_update(policy_file: str, edit_type: str, target_text: str,
                          new_text: str, rationale: str) -> dict:
    """Build a policy-doc diff card for review (applies nothing).

    Returns {id, policy_file, edit_type, diff, status}. Confirm with commit_policy.
    """
    proposal = policy_updater.build_proposal(
        policy_file=policy_file, edit_type=edit_type, target_text=target_text,
        new_text=new_text, rationale=rationale,
    )
    _PROPOSALS.put(proposal["id"], proposal)
    return {
        "id": proposal["id"],
        "policy_file": proposal["policy_file"],
        "edit_type": proposal["edit_type"],
        "diff": proposal["diff"],
        "status": proposal["status"],
    }


def commit_policy(proposal_id: str, source_conversation_id: str | None = None) -> dict:
    """Live-apply + commit a proposed policy edit to the repo (single source of truth).

    Returns {"commit_sha": str}. Fails loudly on drift / GitHub error.
    """
    proposal = _PROPOSALS.get(proposal_id)
    if not proposal:
        raise ValueError(f"unknown proposal_id {proposal_id!r} (it may have expired)")
    cid = str(source_conversation_id or "morning-review")
    return policy_updater.confirm_proposal(proposal, conversation_id=cid)
