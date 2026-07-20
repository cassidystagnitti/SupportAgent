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

import orchestrator
import bert.pipeline as pipeline
import bert.verify as verify

AUTO_SEND_TAG = "auto_send"


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


def should_auto_send(result: dict) -> bool:
    """True when a drafted result qualifies for the ``auto_send`` review tag.

    Bert passes Claude's raw ``auto_sendable`` through (unlike the orchestrator,
    which forces it false for escalations / multi-subscriber tickets), so the
    gate is reconstructed explicitly: only high/medium-confidence, genuinely
    auto-sendable drafts that need no human action and aren't escalated.
    """
    if not result.get("ok"):
        return False
    parsed = result.get("parsed") or {}
    if not parsed.get("auto_sendable"):
        return False
    confidence = (result.get("confidence") or parsed.get("confidence") or "").strip().lower()
    if confidence not in ("high", "medium"):
        return False
    if result.get("escalate") or parsed.get("escalate"):
        return False
    if result.get("needs_action") or parsed.get("needs_action"):
        return False
    return True


def reconcile_auto_send_tag(session, cid, verdict) -> str | None:
    """Make the conversation's ``auto_send`` tag match the verifier verdict.

    SEND_AS_IS → tag applied ("tagged", or "already" if present). Any other
    verdict — MINOR, ERROR, or None (unverified / verifier failure) — → an
    existing tag is stripped ("removed", or None if it wasn't there). Never
    raises — a tagging error must not break the post that already landed; a
    soft failure just returns None (i.e. no tag applied).
    """
    try:
        convo = orchestrator.fetch_conversation(session, int(cid))
        existing = orchestrator._extract_tag_names(convo.get("tags", []))
        if verdict == "SEND_AS_IS":
            if AUTO_SEND_TAG in existing:
                return "already"
            orchestrator._update_conversation_tags(session, str(cid), existing, [AUTO_SEND_TAG])
            return "tagged"
        if AUTO_SEND_TAG not in existing:
            return None
        remaining = [t for t in existing if t != AUTO_SEND_TAG]
        resp = session.put(f"{orchestrator.BASE_URL}/conversations/{cid}/tags",
                           json={"tags": remaining})
        resp.raise_for_status()
        return "removed"
    except Exception:
        return None


def verify_and_tag(session, client, result: dict, *, brief: str = "",
                   model: str | None = None) -> dict:
    """VERIFIER stage for one auto-send candidate, then tag reconcile.

    Cheapest check first: deterministic pre-lint (no API), then the mechanical
    same-customer sibling check (other active conversations → automatic ERROR,
    consolidate), then one adversarial Claude review against the full policy
    corpus + standing brief. The ``auto_send`` tag is applied ONLY on a
    SEND_AS_IS verdict and stripped otherwise — including when the verifier
    itself fails (fail-soft: the draft stays, unverified drafts never carry the
    tag). Returns {"verdict", "findings", "tag", "error"} and never raises.
    """
    cid = result.get("conversation_id")
    out = {"verdict": None, "findings": [], "tag": None, "error": None}
    try:
        findings = verify.prelint(result.get("draft_reply") or "")
        if findings:
            out["verdict"], out["findings"] = "ERROR", findings
        else:
            ctx = pipeline.hydrate_ticket(session, cid)
            try:
                siblings = verify.find_sibling_conversations(session, ctx.get("email"),
                                                             exclude_cid=cid)
            except Exception:
                siblings = []  # sibling check is best-effort; the model review still runs
            if siblings:
                out["verdict"] = "ERROR"
                out["findings"] = [{
                    "class": "I",
                    "detail": f"customer has {len(siblings)} other active conversation(s): {siblings}",
                    "fix_type": "consolidate",
                    "suggested_fix": "Answer once on the primary thread and consolidate the duplicates.",
                }]
            else:
                v = verify.verify_draft(client, result, ctx, brief,
                                        orchestrator.load_policy_docs(), model=model)
                out["verdict"], out["findings"] = v["verdict"], v["findings"]
    except Exception as e:
        out["error"] = str(e)
    out["tag"] = reconcile_auto_send_tag(session, cid, out["verdict"])
    return out


def apply_result(session, result: dict, *, timestamp: str | None = None,
                 verify_client=None, brief: str = "",
                 verify_model: str | None = None) -> dict:
    """Apply one drafted result to Help Scout: update existing draft(s) in place
    (or post a new one), run the VERIFIER on auto-send candidates, then post the
    internal action-note when needed.

    ``verify_client`` is the Anthropic client for the verifier stage; the
    ``auto_send`` tag follows the verifier verdict (see ``verify_and_tag``).
    Without a client, candidates stay unverified and never carry the tag.

    Returns a status dict: {conversation_id, draft_action, threads_updated,
    note_posted, note_skipped_reason, auto_send_tagged, verify_verdict,
    verify_findings, verify_error, error}. Never raises — per-ticket failures
    are captured so a batch can continue.
    """
    cid = result.get("conversation_id")
    status = {"conversation_id": cid, "draft_action": None, "threads_updated": 0,
              "note_posted": False, "note_skipped_reason": None,
              "auto_send_tagged": None, "verify_verdict": None,
              "verify_findings": [], "verify_error": None, "error": None}
    if not result.get("ok"):
        status["error"] = result.get("error") or "draft generation failed"
        return status
    ts = timestamp or datetime.now(timezone.utc).isoformat()
    errors = []

    # --- draft: update every existing thread in place (one bad thread does not
    # block the others), or post a new draft if none exist ---
    try:
        tids = pipeline.find_draft_threads(session, cid)
    except Exception as e:
        status["error"] = f"find_draft_threads: {e}"
        return status

    if tids:
        status["draft_action"] = "updated"
        for tid in tids:
            try:
                pipeline.update_draft(session, cid, tid, result["draft_reply"])
                status["threads_updated"] += 1
            except Exception as e:
                errors.append(f"thread {tid}: {e}")
    elif result.get("hs_customer_id"):
        # No existing draft to update. Only post a NEW draft if the conversation
        # is still open — a ticket a human has already answered and closed since
        # the draft snapshot must not get a fresh (never-to-be-sent) draft
        # stacked on it. Fail soft toward posting if the status can't be read.
        conv_status = None
        try:
            conv_status = pipeline.conversation_status(session, cid)
        except Exception:
            conv_status = None
        if conv_status in ("closed", "spam"):
            status["draft_action"] = "skipped_closed"
        else:
            try:
                pipeline.post_draft(session, str(cid), result["hs_customer_id"], result["draft_reply"], ts)
                status["draft_action"] = "posted_new"
            except Exception as e:
                errors.append(f"post_draft: {e}")
    else:
        status["draft_action"] = "skipped_no_customer"

    # --- auto_send tag: follows the VERIFIER verdict, only on conversations we
    # actually drafted on ---
    if status["draft_action"] in ("posted_new", "updated") and should_auto_send(result):
        if verify_client is not None:
            v = verify_and_tag(session, verify_client, result,
                               brief=brief, model=verify_model)
            status["verify_verdict"] = v["verdict"]
            status["verify_findings"] = v["findings"]
            status["verify_error"] = v["error"]
            status["auto_send_tagged"] = v["tag"]
        else:
            # No verifier client → the candidate stays unverified; it must not
            # carry the tag, and a stale tag from an earlier run is stripped.
            status["auto_send_tagged"] = reconcile_auto_send_tag(session, cid, None)

    # --- note: attempted regardless of partial thread failures above ---
    try:
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
        errors.append(f"note: {e}")

    if errors:
        status["error"] = "; ".join(errors)
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


def stale_drafts_matching(results: list[dict], *, include: list[str],
                          exclude: list[str] | None = None) -> list[dict]:
    """Select drafts by CONTENT, not by classifier tag.

    Returns every result whose ``draft_reply`` contains at least one of the
    ``include`` signals (case-insensitive) and none of the ``exclude`` signals.
    Use this to sweep for drafts affected by a standing-brief change (e.g. a
    bug fix) without trusting ``matches_known_bug`` — the summarizer under-tags,
    so a tag-based sweep misses stragglers.
    """
    exclude = exclude or []
    inc = [s.lower() for s in include]
    exc = [s.lower() for s in exclude]
    hits = []
    for r in results:
        text = (r.get("draft_reply") or "").lower()
        if not text:
            continue
        if any(s in text for s in inc) and not any(s in text for s in exc):
            hits.append(r)
    return hits


def partition(results: list[dict]) -> dict:
    """Split results into {'ready': [...], 'review': [...]}."""
    ready, review = [], []
    for r in results:
        (review if _needs_review(r) else ready).append(r)
    return {"ready": ready, "review": review}
