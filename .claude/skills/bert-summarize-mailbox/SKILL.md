---
name: bert-summarize-mailbox
description: Use during the Bert morning review to build the mailbox index — the cheap Haiku map/reduce summary of every open ticket — and render the glanceable status.
---

# Bert — Summarize Mailbox (MAP + REDUCE)

Build the lightweight index of the mailbox. This is the map/reduce summary; it holds one-liners and pointers, never full ticket bodies.

## How to run

1. Fetch open tickets and summarize them with `bert.summarize`:
   - `bert.summarize.fetch_open_tickets(session)` → list of `{conversation_id, subject, body, tags}`.
   - `bert.summarize.summarize_mailbox(tickets, client)` → one record per ticket via Haiku (`claude-haiku-4-5`), failures isolated. Record shape: `{conversation_id, customer, category, one_line, urgent, is_new, matches_known_bug}`.
   - The `python3 -m bert.summarize` CLI does all of this and writes today's state + an HTML artifact.

2. Store the records into the morning-review state (`bert.state.set_records`) and `save`.

3. Present the REDUCE with `bert.render`:
   - `bert.render.mailbox_stats(records)` → totals, urgent/new counts, category rollup, known-bug hits.
   - `bert.render.render_summary_html(state)` → a standalone HTML block. Surface it as an Artifact for glanceability.

## What to tell Cassidy

Give the shape, not the list: total open, how it compares to a normal day, what's urgent, what's new, and any known-bug clusters. Each ticket keeps its `conversation_id` so any of them can be hydrated on demand.
