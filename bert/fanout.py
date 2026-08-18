"""Draft fan-out + confidence partition.

``draft_all`` runs one worker per ticket (hydrate → draft with the standing
brief injected), isolating per-ticket failures. ``partition`` splits the
results into the ones ready to post and the ones that need Cassidy's eyes
before sending.
"""

from __future__ import annotations

import concurrent.futures
import logging
from datetime import datetime, timezone
from typing import Any

import helpscout_identity
import orchestrator
import stripe_research
import triage_tickets
import bert.pipeline as pipeline
import bert.verify as verify

log = logging.getLogger(__name__)

AUTO_SEND_TAG = "auto_send"
MAX_REPAIRS = 2


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
                "identity_plan": ctx.get("identity_plan"),
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
    """True when a drafted result belongs to the AUTO-SEND bucket.

    Three-bucket model (Cassidy 2026-07-22): every ok draft that needs no human
    action and is not escalated IS the auto-send bucket — the draft brain's
    per-ticket ``auto_sendable``/``confidence`` no longer gate it. The VERIFIER
    is the quality gate: an ERROR verdict moves the ticket to the needs-action
    bucket (``verify_and_tag`` + the ERROR note in ``apply_result``) instead of
    leaving it untagged in this one. Close-candidates are excluded because they
    get CLOSED during the review, not sent.
    """
    if not result.get("ok"):
        return False
    parsed = result.get("parsed") or {}
    if _close_no_reply(result):
        return False
    if result.get("escalate") or parsed.get("escalate"):
        return False
    if result.get("needs_action") or parsed.get("needs_action"):
        return False
    return True


def reconcile_auto_send_tag(session, cid, verdict) -> str | None:
    """Make the conversation's ``auto_send`` tag match the verifier verdict.

    SEND_AS_IS or MINOR → tag applied ("tagged", or "already" if present) —
    the lowered bar (Cassidy 2026-07-22): minor imperfections don't hold a
    bucket-1 draft back. ERROR or None (not a candidate / conversation-over) →
    an existing tag is stripped ("removed", or None if it wasn't there;
    "remove_failed" when the strip itself errored, because a lingering tag the
    verdict forbids must be visible). Never raises — a tagging error must not
    break the post that already landed.
    """
    try:
        convo = orchestrator.fetch_conversation(session, int(cid))
        existing = orchestrator._extract_tag_names(convo.get("tags", []))
    except Exception:
        log.warning("auto_send reconcile: could not read tags for %s", cid, exc_info=True)
        return None
    try:
        if verdict in ("SEND_AS_IS", "MINOR"):
            if AUTO_SEND_TAG in existing:
                return "already"
            orchestrator._update_conversation_tags(session, str(cid), existing, [AUTO_SEND_TAG])
            return "tagged"
        if AUTO_SEND_TAG not in existing:
            return None
        remaining = [t for t in existing if t != AUTO_SEND_TAG]
        triage_tickets.api_put(session, f"{orchestrator.BASE_URL}/conversations/{cid}/tags",
                               {"tags": remaining})
        return "removed"
    except Exception:
        log.warning("auto_send reconcile: tag write failed for %s (verdict=%s)",
                    cid, verdict, exc_info=True)
        return "remove_failed" if verdict not in ("SEND_AS_IS", "MINOR") else None


def move_to_apple_mailbox(session, conversation_id) -> str | None:
    """Route a Mindful Minute Challenge ticket to the Apple mailbox (fail-soft).

    ONLY for the Mindful Minute Challenge (the Apple-org event) — Happier's
    other meditation challenges are normal tickets and must never be moved.
    Per policies/mindful-minute-challenge.md, these tickets are moved to
    the Apple mailbox instead of being answered from the main queue. Returns
    ``"moved"`` on success, ``"no_mailbox_id"`` when APPLE_MAILBOX_ID is not
    configured, or ``None`` when the move call failed. Never raises.
    """
    mailbox_id = pipeline.apple_mailbox_id()
    if not mailbox_id:
        return "no_mailbox_id"
    return "moved" if pipeline.move_conversation(session, conversation_id, mailbox_id) else None


def _initial_verdict(session, client, result: dict, *, brief: str,
                     model: str | None):
    """First-pass verdict, cheapest check first. Returns (verdict_dict, ctx,
    policies); ctx/policies are None when an earlier layer short-circuited."""
    cid = result.get("conversation_id")
    pre = verify.prelint(result.get("draft_reply") or "")
    if pre:
        return {"verdict": "ERROR", "findings": pre}, None, None
    ctx = pipeline.hydrate_ticket(session, cid)
    try:
        siblings = verify.find_sibling_conversations(session, ctx.get("email"),
                                                     exclude_cid=cid)
    except Exception:
        # Best-effort: the model review still runs, but losing this guard is
        # worth a trace ("log everything").
        log.warning("sibling check failed for conversation %s — continuing without it",
                    cid, exc_info=True)
        siblings = []
    if siblings:
        return {"verdict": "ERROR", "findings": [verify.sibling_finding(siblings)]}, ctx, None
    try:
        # Deterministic Stripe truth check (read-only): a draft that references
        # a Stripe object that doesn't exist / isn't the customer's, or claims
        # an action with no locatable object, is an automatic ERROR (class A /
        # class C, fix_type "none" — never auto-repaired).
        truth = stripe_research.verify_claimed_stripe_objects(
            result, customer_email=ctx.get("email"))
        if truth.get("findings"):
            return {"verdict": "ERROR", "findings": truth["findings"]}, ctx, None
    except Exception:
        log.warning("stripe truth check failed for conversation %s — continuing without it",
                    cid, exc_info=True)
    policies = orchestrator.load_policy_docs()
    return verify.verify_draft(client, result, ctx, brief, policies, model=model), ctx, policies


def verify_and_tag(session, client, result: dict, *, brief: str = "",
                   model: str | None = None) -> dict:
    """VERIFIER stage for one auto-send candidate: verify → repair → re-verify
    (bounded), then tag reconcile.

    First pass runs the cheapest check first: deterministic pre-lint (no API),
    the mechanical same-customer sibling check (other open conversations →
    automatic ERROR, consolidate), then one adversarial Claude review against
    the full policy corpus + standing brief. When the verdict is MINOR/ERROR
    and every finding is a pure ``rewrite`` (fixable from documented truths),
    the draft is repaired, the Help Scout draft is updated in place, and the
    revised draft re-verifies — at most ``MAX_REPAIRS`` times. The ``auto_send``
    tag is applied ONLY when the FINAL verdict is SEND_AS_IS and stripped
    otherwise — including when the verifier itself fails (fail-soft: the draft
    stays, unverified drafts never carry the tag).

    Mutates ``result["draft_reply"]`` to the repaired text when a repair lands.
    Returns {"verdict", "findings", "initial_verdict", "initial_findings",
    "repairs", "tag", "error"} and never raises.
    """
    cid = result.get("conversation_id")
    out = {"verdict": None, "findings": [], "initial_verdict": None,
           "initial_findings": [], "repairs": 0, "tag": None, "error": None}
    try:
        v, ctx, policies = _initial_verdict(session, client, result, brief=brief, model=model)
        out["initial_verdict"], out["initial_findings"] = v["verdict"], v["findings"]
        while (v["verdict"] in ("MINOR", "ERROR") and out["repairs"] < MAX_REPAIRS
               and verify.repairable(v["findings"])):
            tids = pipeline.find_draft_threads(session, cid)
            if not tids:
                # nothing to rewrite in Help Scout — the flawed draft would
                # stay live, so the verdict stands unrepaired
                break
            if ctx is None:
                ctx = pipeline.hydrate_ticket(session, cid)
            if policies is None:
                policies = orchestrator.load_policy_docs()
            revised = verify.repair_draft(client, result, ctx, brief, policies,
                                          v["findings"], model=model)
            for tid in tids:
                pipeline.update_draft(session, cid, tid, revised)
            result["draft_reply"] = revised
            out["repairs"] += 1
            pre = verify.prelint(revised)
            v = ({"verdict": "ERROR", "findings": pre} if pre
                 else verify.verify_draft(client, result, ctx, brief, policies, model=model))
        out["verdict"], out["findings"] = v["verdict"], v["findings"]
    except Exception as e:
        log.warning("verifier failed for conversation %s", cid, exc_info=True)
        out["error"] = str(e)
    # Fail-OPEN on a verifier crash (Cassidy 2026-07-22): bucket membership
    # governs the tag; a crashed verifier doesn't demote a bucket-1 draft.
    # A real ERROR verdict still strips (and apply_result moves the ticket to
    # the needs-action bucket with a findings note).
    tag_verdict = out["verdict"] if out["verdict"] else ("SEND_AS_IS" if out["error"] else None)
    out["tag"] = reconcile_auto_send_tag(session, cid, tag_verdict)
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
    verify_initial_verdict, verify_initial_findings, verify_repairs,
    verify_findings, verify_error, error}. Never raises — per-ticket failures
    are captured so a batch can continue.
    """
    cid = result.get("conversation_id")
    status = {"conversation_id": cid, "draft_action": None, "threads_updated": 0,
              "note_posted": False, "note_skipped_reason": None,
              "auto_send_tagged": None, "verify_verdict": None,
              "verify_initial_verdict": None, "verify_initial_findings": [],
              "verify_repairs": 0, "verify_findings": [], "verify_error": None,
              "verifier_error_note": False, "identity_summary": "",
              "identity_linked": [], "identity_merged": [], "error": None}
    if not result.get("ok"):
        status["error"] = result.get("error") or "draft generation failed"
        return status

    # --- contact records: execute the plan hydration built (link verified
    # addresses onto this contact, fold duplicate contacts in). Runs before the
    # draft work and on every bucket — consolidating a customer's records is
    # right whether or not this ticket gets a reply. Never blocks the draft.
    apply_identity(session, result, status)
    if _close_no_reply(result):
        # Conversation is over (thanks-only follow-up): no draft, no verifier.
        # Three-bucket model (Cassidy 2026-07-22): close candidates are CLOSED
        # during the initial review, not held for approval. A stale auto_send
        # tag from an earlier run is stripped first.
        status["auto_send_tagged"] = reconcile_auto_send_tag(session, cid, None)
        try:
            pipeline.post_plain_note(
                session, cid,
                "<p>Closed during morning review — conversation over (thanks-only / "
                "resolution-confirmed follow-up); nothing to answer.</p>")
        except Exception:
            log.warning("close note failed for %s — closing anyway", cid, exc_info=True)
        try:
            pipeline.close_conversation(session, cid)
            status["draft_action"] = "closed_no_reply"
        except Exception as e:
            status["draft_action"] = "skipped_close_no_reply"
            status["error"] = f"close failed: {e}"
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

    # --- auto_send tag: follows the VERIFIER verdict on every conversation we
    # actually drafted on. Non-candidates and unverified candidates must not
    # carry the tag, so a stale tag from an earlier run is stripped. ---
    if status["draft_action"] in ("posted_new", "updated"):
        if should_auto_send(result) and verify_client is not None:
            v = verify_and_tag(session, verify_client, result,
                               brief=brief, model=verify_model)
            status["verify_verdict"] = v["verdict"]
            status["verify_initial_verdict"] = v.get("initial_verdict")
            status["verify_initial_findings"] = v.get("initial_findings") or []
            status["verify_repairs"] = v.get("repairs", 0)
            status["verify_findings"] = v["findings"]
            status["verify_error"] = v["error"]
            status["auto_send_tagged"] = v["tag"]
            if v["verdict"] == "ERROR":
                # Three-bucket invariant: an ERROR draft leaves the auto-send
                # bucket by carrying the needs-action marker — never untagged
                # limbo. The note tells the rep what the verifier found.
                try:
                    items = "".join(
                        f"<li>{orchestrator._html_escape((f.get('detail') or '')[:300])}</li>"
                        for f in (v["findings"] or [])[:4]
                    ) or "<li>Verifier ERROR — see morning-review state for details</li>"
                    pipeline.post_plain_note(
                        session, cid,
                        f"<p><strong>Actions needed</strong> — verifier flagged this draft "
                        f"(not auto-sendable as-is):</p><ul>{items}</ul>")
                    status["verifier_error_note"] = True
                except Exception:
                    log.warning("verifier ERROR note failed for %s", cid, exc_info=True)
        else:
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


def apply_identity(session, result: dict, status: dict) -> None:
    """Execute one ticket's contact-record plan and note what changed.

    Fail-soft by contract: a Help Scout CRM hiccup must never cost us the
    draft, so every outcome (including the errors) is reported into ``status``
    and, when there is something a human should see, an internal note.
    """
    plan = result.get("identity_plan")
    if not plan or not plan.get("actions"):
        return
    cid = result.get("conversation_id")
    try:
        applied = helpscout_identity.apply_identity_plan(session, plan, actor="bert")
        status["identity_summary"] = helpscout_identity.summary_line(plan, applied)
        status["identity_linked"] = applied["linked"]
        status["identity_merged"] = [m["dup_id"] for m in applied["merged"]]
        note_html = helpscout_identity.identity_note_html(plan, applied)
        if note_html:
            pipeline.post_plain_note(session, cid, note_html)
    except Exception as e:
        status["identity_summary"] = f"contact sync failed: {e}"
        log.warning("identity apply failed for %s", cid, exc_info=True)


def _close_no_reply(result: dict) -> bool:
    """True when the draft brain marked this thread as conversation-over."""
    return bool(result.get("close_no_reply")
                or (result.get("parsed") or {}).get("close_no_reply"))


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
    """Split results into {'ready': [...], 'review': [...], 'close': [...]}.

    ``close`` = successful drafts flagged ``close_no_reply`` (thanks-only
    follow-ups): no draft gets posted; the human approves the close. A FAILED
    worker always lands in ``review`` regardless of any close flag.
    """
    ready, review, close = [], [], []
    for r in results:
        if r.get("ok") and _close_no_reply(r):
            close.append(r)
        elif _needs_review(r):
            review.append(r)
        else:
            ready.append(r)
    return {"ready": ready, "review": review, "close": close}
