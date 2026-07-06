---
name: bert-post
description: Use at the end of the Bert morning review to post the approved drafts to Help Scout as drafts (never auto-send), with internal notes.
---

# Bert — Post Drafts

Post the approved drafts. Everything goes to Help Scout as a DRAFT for human send — Bert never auto-sends.

## How to run

For each approved result (from the `ready` set plus any `review` items Cassidy signed off on, excluding escalations that should not get a customer draft):

1. Post the draft: `bert.pipeline.post_draft(session, conversation_id, hs_customer_id, draft_reply, timestamp)`.
   - Returns the Help Scout draft thread id and records it in `draft_registry` (dedupe / supersede is handled there).
   - Skip a ticket with no `hs_customer_id` (log it) — it can't receive a draft.
2. For escalations and needs-action tickets, post the internal note as the production pipeline does (`orchestrator._format_internal_note_html` + the notes endpoint), so the human reviewer has the classification + reasoning.
3. Mark each posted ticket in state (`bert.state.set_status(state, cid, posted=True, draft_id=...)`) and save.

## What to tell Cassidy

How many drafts were posted, how many were skipped and why, and any post failures (which are per-ticket and do not abort the batch). Confirm nothing was sent — only drafted.
