"""Draft fan-out + confidence partition.

``draft_all`` runs one worker per ticket (hydrate → draft with the standing
brief injected), isolating per-ticket failures. ``partition`` splits the
results into the ones ready to post and the ones that need Cassidy's eyes
before sending.
"""

from __future__ import annotations

import concurrent.futures
from typing import Any

import bert.pipeline as pipeline


def draft_all(records, session, client, brief, *, model, max_workers: int = 6) -> list[dict]:
    """Hydrate + draft every record concurrently. One result per record.

    Each result is the ``draft_one`` dict plus ``conversation_id``,
    ``hs_customer_id``, ``ok`` and ``error``. A failure in one ticket becomes
    ``ok=False`` and never affects the others.
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
