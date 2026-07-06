---
name: bert-post
description: Use at the end of the Bert morning review to post the approved drafts to Help Scout as drafts (never auto-send), with internal notes.
---

# Bert — Post Drafts

Post the approved drafts. Everything goes to Help Scout as a DRAFT for human send — Bert never auto-sends.

## How to run

For each approved result (from the `ready` set plus any `review` items Cassidy signed off on), call:

`bert.fanout.apply_result(session, result, timestamp=...)`

It does the whole apply step for one ticket:
1. **Draft** — if the ticket already has Bert draft thread(s), it **updates them in place** via `pipeline.update_draft` (no duplicate drafts). If none exist and there's an `hs_customer_id`, it posts a new draft via `pipeline.post_draft`. A ticket with no customer id is skipped.
2. **Note** — if the classification needs one (`pipeline.should_post_note` → escalation or needs_action), it posts a SHORT internal note via `pipeline.post_note`: an "Actions needed" bullet list of the concrete steps a rep must take (from `action_items`, falling back to `action_description`) — nothing else, no classification metadata. Idempotent: skips if an AI note already exists, and no-ops if there are no actions or `HELPSCOUT_NOTE_USER_ID` is unset.

`apply_result` never raises — it returns a status dict `{draft_action, threads_updated, note_posted, note_skipped_reason, error}`, so a batch keeps going on per-ticket failures.

3. Mark each ticket in state (`bert.state.set_status(state, cid, posted=True, ...)`) from the returned status and save.

**Config note:** notes require `HELPSCOUT_NOTE_USER_ID` (the Help Scout user the note is attributed to — currently the Support Automations agent). Without it, drafts still post but notes are silently skipped.

## What to tell Cassidy

How many drafts were posted, how many were skipped and why, and any post failures (which are per-ticket and do not abort the batch). Confirm nothing was sent — only drafted.
