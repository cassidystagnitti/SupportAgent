"""Draft fan-out + confidence partition.

``draft_all`` runs one worker per ticket (hydrate → draft with the standing
brief injected), isolating per-ticket failures. ``partition`` splits the
results into the ones ready to post and the ones that need Cassidy's eyes
before sending.
"""

from __future__ import annotations

import concurrent.futures
from datetime import datetime, timezone
from typing import Any

import bert.pipeline as pipeline


def draft_all(records, session, client, brief, *, model, max_workers: int = 6) -> list[dict]:
    """Hydrate + draft every record concurrently. One result per record.

    Each result is the ``draft_one`` dict (incl. full ``parsed``) plus
    ``conversation_id``, ``hs_customer_id``, ``stripe_block``, ``stripe_ctx``,
    ``ok`` and ``error``. A failure in one ticket becomes ``ok=False`` and never
    affects the others.
    """
    results: list[Any] = [None] * len(records)

    def _one(index: int, record: dict) -> None:
        cid = record.get("conversation_id")
        try:
            ctx = pipeline.hydrate_ticket(session, cid)
            drafted = pipeline.draft_one(client, ctx, brief, model=model)
            results[index] = {
                **drafted,
                "conversation_id": cid,
                "hs_customer_id": ctx.get("hs_customer_id"),
                "stripe_block": ctx.get("stripe_block", ""),
                "stripe_ctx": ctx.get("stripe_ctx"),
                "ok": True,
                "error": None,
            }
        except Exception as e:
            results[index] = {
                "conversation_id": cid,
                "hs_customer_id": None,
                "ok": False,
                "error": str(e),
                "confidence": None,
            }

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = [pool.submit(_one, i, r) for i, r in enumerate(records)]
        for f in futures:
            f.result()
    return results


def apply_result(session, result: dict, *, timestamp: str | None = None) -> dict:
    """Apply one drafted result to Help Scout: update existing draft(s) in place
    (or post a new one), then post the internal action-note when needed.

    Returns a status dict: {conversation_id, draft_action, threads_updated,
    note_posted, note_skipped_reason, error}. Never raises — per-ticket failures
    are captured so a batch can continue.
    """
    cid = result.get("conversation_id")
    status = {"conversation_id": cid, "draft_action": None, "threads_updated": 0,
              "note_posted": False, "note_skipped_reason": None, "error": None}
    if not result.get("ok"):
        status["error"] = result.get("error") or "draft generation failed"
        return status
    ts = timestamp or datetime.now(timezone.utc).isoformat()
    try:
        tids = pipeline.find_draft_threads(session, cid)
        if tids:
            for tid in tids:
                pipeline.update_draft(session, cid, tid, result["draft_reply"])
            status["draft_action"] = "updated"
            status["threads_updated"] = len(tids)
        elif result.get("hs_customer_id"):
            pipeline.post_draft(session, str(cid), result["hs_customer_id"], result["draft_reply"], ts)
            status["draft_action"] = "posted_new"
        else:
            status["draft_action"] = "skipped_no_customer"

        parsed = result.get("parsed") or {}
        if pipeline.should_post_note(parsed):
            if pipeline.has_ai_note(session, cid):
                status["note_skipped_reason"] = "note_exists"
            else:
                nid = pipeline.post_note(session, cid, parsed,
                                         result.get("stripe_block", ""), result.get("stripe_ctx"))
                if nid:
                    status["note_posted"] = True
                else:
                    status["note_skipped_reason"] = "no_note_user_id"
    except Exception as e:
        status["error"] = str(e)
    return status


def _needs_review(result: dict) -> bool:
    if not result.get("ok"):
        return True
    if result.get("confidence") in (None, "low"):
        return True
    if result.get("needs_action"):
        return True
    if result.get("escalate"):
        return True
    if result.get("open_question"):
        return True
    bug = result.get("bug_report")
    if isinstance(bug, dict) and bug.get("is_bug"):
        return True
    return False


def partition(results: list[dict]) -> dict:
    """Split results into {'ready': [...], 'review': [...]}."""
    ready, review = [], []
    for r in results:
        (review if _needs_review(r) else ready).append(r)
    return {"ready": ready, "review": review}
