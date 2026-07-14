# Stale-draft skip fix (webhook path) — Design

**Date:** 2026-07-09
**Scope:** `orchestrator.py`, `draft_registry.py` (no Bert changes)
**Related:** SUP-461 (draft lifecycle registry), draft-registry supersede logic

## Problem

The webhook `convo.customer.reply.created` fires when a customer replies, and
`webhook_server._run_pipeline_sync` calls `orchestrator.process_ticket_sync`.
When a customer sends a follow-up *before any agent has replied*, `reply_mode`
(derived from `detect_reply_mode`, which only looks for a **published agent**
message) stays `False`. With an existing recorded draft and no `force`,
`draft_registry.should_skip_draft` returns `True` and the pipeline returns early
with `skipped_existing_draft=True`.

Result: the existing draft is left **frozen on the earlier customer message** and
never incorporates the new one. The agent later finds a draft that answers a
stale message and — because Help Scout renders the draft above the newer
customer reply — fears it will go out out-of-order.

## Goal

Guarantee the draft always reflects the **most recent** customer message. When a
customer has replied since we drafted, re-draft and refresh the existing draft
**in place** (single draft, no stacking) instead of skipping.

Explicitly **out of scope** (deferred): the draft's *position* in the Help Scout
thread list, the Bert morning-review flow (already updates drafts in place), and
`reply_mode`'s supersede behavior.

## Changes

### 1. Staleness detector — `orchestrator._customer_replied_after_draft(threads, draft_thread_id)`

Locate the recorded draft thread by id and compare its `createdAt` against every
`type == "customer"` thread.

- Returns `True`  — a customer thread is newer than the draft (stale).
- Returns `False` — draft is current (no newer customer thread).
- Returns `None`  — the recorded draft thread is not present in the conversation
  (registry points at a gone/deleted thread).

Comparison is on the ISO-8601 `createdAt` strings (UTC, lexicographically
orderable). Threads missing `createdAt` are ignored in the comparison.

### 2. Skip decision — `draft_registry.should_skip_draft(existing, reply_mode, force, draft_is_stale=False)`

Add a fourth parameter, defaulting to `False` (preserves current behavior and
existing tests):

```python
return bool(existing) and not reply_mode and not force and not draft_is_stale
```

The orchestrator computes `draft_is_stale = (_customer_replied_after_draft(...) is True)`.
The `None` case (recorded draft thread not present in the conversation) is treated
as **not stale** — the pipeline preserves today's skip behavior rather than
posting a fresh draft against a thread it can no longer locate. Only a genuinely
newer customer message flips `draft_is_stale` to `True`.

### 3. Write path — `orchestrator.process_ticket_sync` draft-write branch

At the final `else` (currently POST-new only):

- **Stale re-draft** — a live existing draft thread + a newer customer message,
  not `reply_mode`, not `force`: **PATCH the same thread in place** via a new
  helper `orchestrator._helpscout_patch_thread_text(session, cid, thread_id,
  text)` (mirrors `bert.pipeline.update_draft`; implemented inline in
  `orchestrator` to avoid a circular import, since `bert` imports
  `orchestrator`). Set `out["helpscout_draft_id"]` to the existing thread id,
  `out["draft_created"] = True`, `out["draft_updated_in_place"] = True`, and
  refresh the registry timestamp.
- **Everything else** — first draft, `reply_mode` supersede, or draft thread
  gone (`None` case): unchanged POST-new behavior.

`out` gains a new telemetry field `draft_updated_in_place` (default `False`).

## Testing (TDD)

- `_customer_replied_after_draft`: newer customer → `True`; only older
  threads → `False`; recorded thread id absent → `None`; threads without
  `createdAt` ignored.
- `should_skip_draft` new arg: `draft_is_stale=True` → `False` (don't skip)
  even with an existing draft and no reply_mode/force; default still skips.
- Orchestrator integration: existing draft + newer customer thread → routes to
  PATCH (`session.patch` / helper called), **not** a POST-new reply; registry
  keeps the same thread id; `draft_updated_in_place=True`.
- Regression: existing "skip when current draft" test still passes (threads with
  no newer customer message).
