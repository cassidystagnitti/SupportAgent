---
name: bert-draft-all
description: Use during the Bert morning review when Cassidy says to draft the replies — fans out one draft worker per ticket, injecting the current standing brief, and partitions results into ready vs. needs-review.
---

# Bert — Draft All (FAN-OUT)

Draft every ticket at once. Each ticket gets its own worker that hydrates its full context and drafts using the **same brain** as the production pipeline, with the current standing brief injected.

## How to run

1. Render the current standing brief: `brief = bert.state.render_brief(state)`.
2. Fan out: `bert.fanout.draft_all(records, session, client, brief, model="claude-sonnet-5")`.
   - One result per record: the draft dict (`draft_reply`, `confidence`, `referenced_policies`, `needs_action`, `escalate`, `open_question`, `bug_report`, …) plus `conversation_id`, `hs_customer_id`, `ok`, `error`.
   - Per-ticket failures are isolated (`ok=False`, `error` set) — they never block the batch.
3. Partition: `bert.fanout.partition(results)` → `{"ready": [...], "review": [...]}`.
   - `review` = anything not ok, low/absent confidence, needs_action, escalate, an open_question, or a suspected bug.
4. Record each ticket's outcome into state (`bert.state.set_status`, e.g. `drafted=True, confidence=...`) and save.

## What to tell Cassidy

How many drafted cleanly (ready) vs. how many need discussion (review), plus any that errored. Then move to the `bert-resolve` skill for the review set. Do not post yet.
