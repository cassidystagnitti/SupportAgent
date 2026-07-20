---
name: bert-morning-review
description: Use when Cassidy says "open Bert" or wants to run the morning support-mailbox review. Orchestrates the full loop — summarize the mailbox, discuss status, draft every reply with the standing brief, review low-confidence drafts together, and post approved drafts.
---

# Bert Morning Review

You are running the attended morning review of the Happier Meditation Help Scout mailbox. Load `bert/prompts/bert_system_prompt.txt` as your operating instructions — especially the two-context model (standing brief vs. per-ticket context).

Keep the morning-review state file (`bert.state`) as your working memory: it holds the ticket index (`records`), the standing brief (`brief`), and per-ticket `statuses`. Load today's state at the start; save after each step that changes it.

## The loop

Run these in order, but treat step 2 as a hub you can stay in as long as Cassidy wants before moving on.

1. **Summarize** — use the `bert-summarize-mailbox` skill. Present the status: total open, urgent, new, category rollup, known-bug clusters. Do not dump every ticket; give the shape of the mailbox.

2. **Discuss** (hub — loop freely):
   - Dive into a specific ticket → `bert-hydrate-ticket`.
   - Look something up in the codebase or Linear → the existing `research_agent` (`run_research`).
   - Cassidy states a bug-truth / company context / wording preference → append it to the standing brief with `bert.state.append_brief`, then save.
   - **Mindful Minute Challenge / Apple challenge ticket** → do NOT draft a reply. Per
     `policies/mindful-minute-challenge.md`, move it to the Apple mailbox:
     `bert.fanout.move_to_apple_mailbox(session, conversation_id)`. It returns `"moved"`,
     `"no_mailbox_id"` (APPLE_MAILBOX_ID env var unset — tell Cassidy), or `None` (move
     failed — likely the API credentials still can't access the Apple mailbox; surface it
     and leave the ticket for a manual move in the HS UI). Exclude moved tickets from the
     draft fan-out.

3. **Draft** — when Cassidy says to draft, use `bert-draft-all`. It injects the *current* standing brief into every worker.

4. **Resolve** — the drafts partition into `ready` and `review`. Walk the `review` set with Cassidy (low-confidence, needs-action, escalations, open questions, suspected bugs). Revise as directed. Use the `bert-resolve` skill to capture any newly-settled truth back into `policies/*.md`.

5. **Post** — on Cassidy's approval, use `bert-post` to post the approved drafts to Help Scout (drafts only — never auto-send).

## Principles

- The standing brief is the mechanism: Cassidy's feedback lands there once and propagates to every draft.
- Never auto-send. Never quote internal context to a customer.
- Fail soft: surface what broke, keep going.
