# Bert auto_send tagging — design

**Date:** 2026-07-17
**Status:** approved, pre-implementation

## Problem

The morning-review post flow (`bert.fanout.apply_result`) posts drafts and
internal notes but applies no Help Scout tags. The old `auto_send` tag —
produced by `orchestrator.compute_tags` and applied inside
`orchestrator.process_ticket_sync` — stopped reaching conversations when the
webhook auto-pipeline was sunset (2026-07-14). Support wants the `auto_send`
tag back so they can sort/filter auto-sendable drafts in Help Scout, build
confidence in the classifier, and target quality improvements.

## Goal

Re-apply a single `auto_send` tag to conversations the morning-review flow
drafts on, when the draft genuinely qualifies as auto-sendable. Backfill
today's already-posted drafts so sorting can start immediately.

Out of scope (YAGNI): the full `compute_tags` taxonomy
(`automated`/`technical`/`confidence-*`/`escalation`), and the sidebar-chat
draft path. Either can be added later.

## The rule

`compute_tags` derived `auto_send` as `auto_sendable && confidence != "low"`,
but it relied on the orchestrator having already forced `auto_sendable = false`
for escalations and multi-subscriber tickets ([orchestrator.py:975]). Bert's
`draft_one` passes Claude's **raw** `auto_sendable` through and does not apply
that override, so the gate is reconstructed explicitly here:

> Tag `auto_send` when the result is `ok` **and** `parsed.auto_sendable` is true
> **and** confidence is `high` or `medium` **and** not `escalate` **and** not
> `needs_action`.

Rationale for the guards:
- `needs_action` / `escalate` — a needs-action draft is written in confirmed
  past tense ("I've refunded you") and is never truly send-as-is, so it must not
  enter the auto_send bucket. Escalations likewise.
- confidence `high`/`medium` only (stricter than the old `!= "low"`) — an
  unknown/blank confidence should not pollute the very set being used to *build*
  confidence.

## Components (bert/fanout.py)

- `should_auto_send(result: dict) -> bool` — the gate above. Pure function over a
  drafted result dict.
- `apply_auto_send_tag(session, result) -> str | None` — if the gate passes:
  fetch the conversation's **current** tags (`orchestrator.fetch_conversation` +
  `orchestrator._extract_tag_names`), and if `auto_send` is absent, merge it in
  via `orchestrator._update_conversation_tags` (a full-set PUT that no-ops when
  unchanged). Returns `"tagged"`, `"already"`, or `None` (not qualifying or
  soft-failed). **Never raises** — a tagging error must not break a post.

## Integration

`apply_result` calls `apply_auto_send_tag` only when it actually drafted on the
conversation (`draft_action in ("posted_new", "updated")`) — never on
`skipped_closed` / `skipped_no_customer`. The returned value is recorded on the
status dict as `auto_send_tagged`.

## Backfill

A one-off pass over today's persisted `data/morning_review/drafts-2026-07-17.json`
calling `apply_auto_send_tag` per result. It only tags — it does not re-post
drafts. Idempotent: re-running skips conversations already carrying `auto_send`.

## Error handling

Fail-soft, consistent with the rest of the Bert pipeline: `apply_auto_send_tag`
swallows fetch/PUT errors and returns `None`; a per-ticket tag failure never
aborts the batch and never blocks the draft/note that already posted.

## Testing (TDD)

`tests/test_bert_autosend_tag.py`, mirroring `tests/test_tags.py`:
- `should_auto_send`: high → tag, medium → tag, low → no, blank conf → no,
  not auto_sendable → no, escalate → no, needs_action → no, not-ok → no.
- `apply_auto_send_tag` (mocked session + monkeypatched orchestrator helpers):
  tags when qualifying and preserves existing tags; returns `"already"` (no PUT)
  when the tag is present; returns `None` when not qualifying; swallows a PUT/fetch
  error and returns `None`.

Regression: existing `tests/test_bert_*.py` and `tests/test_tags.py` stay green.

[orchestrator.py:975]: ../../orchestrator.py
