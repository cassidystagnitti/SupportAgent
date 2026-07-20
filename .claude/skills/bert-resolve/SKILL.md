---
name: bert-resolve
description: Use during the Bert morning review to work through the low-confidence / flagged drafts with Cassidy, revise them, and capture newly-settled truths back into the policy docs.
---

# Bert — Resolve Low-Confidence Drafts (HUMAN-IN-THE-LOOP)

Walk the `review` set from the fan-out with Cassidy. This is where judgment gets applied and where the knowledge base compounds.

## For each flagged draft

1. Show Cassidy why it's flagged (low confidence, needs_action, escalation, open_question, suspected bug) and the draft itself. If the flag is brand confusion — the customer might mean Dan Harris's 10% Happier rather than us — run `bert-disambiguate-10-percent` before revising; don't settle it from memory.
2. Get the answer / wording direction. If it establishes a general truth (not just this ticket), append it to the standing brief (`bert.state.append_brief`) so remaining drafts inherit it — and consider re-drafting affected tickets via `bert-draft-all`.
3. Revise the draft as directed (re-draft that ticket with the updated brief, or hand-edit).

## Capture-knowledge (the compounding step)

When a bug-truth or policy stance is settled, write it back so it stops being a question tomorrow:

- Update the relevant `policies/*.md` file (e.g. `known-bugs.md`) with the new truth.
- Per the repo's hard requirement (see `CLAUDE.md`), sync the corresponding page under the Support Policy Docs Notion page (ID `356cffdf-527f-808d-a4fc-f7d05499523f`).
- If the answer resolves an open Bert Gap Queue row, update it (Answered/Incorporated) via `notion_bridge`; `process_answered_gaps.py` already handles the queue→policy write-back flow if you prefer to route it there.

Never quote the policy text or internal reasoning verbatim to the customer — apply it in the draft.
