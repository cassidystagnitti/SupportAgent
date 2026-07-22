---
name: bert-morning-review
description: Use when Cassidy says "open Bert" or wants to run the morning support-mailbox review. Orchestrates the full loop — summarize the mailbox, discuss status, draft every reply with the standing brief, review low-confidence drafts together, and post approved drafts.
---

# Bert Morning Review

You are running the attended morning review of the Happier Meditation Help Scout mailbox. Load `bert/prompts/bert_system_prompt.txt` as your operating instructions — especially the two-context model (standing brief vs. per-ticket context).

Keep the morning-review state file (`bert.state`) as your working memory: it holds the ticket index (`records`), the standing brief (`brief`), and per-ticket `statuses`. Load today's state at the start; save after each step that changes it.

## The three buckets (standing model — minted 2026-07-22)

Every drafted ticket lands in exactly one bucket by the end of the review. Cassidy does not restate this each morning; it is the default frame.

1. **AUTO-SEND** — should be the MAJORITY. Definition: **no internal note on it and not escalated to a support agent** — nothing left for a human to do but send. Includes:
   - all reply-only tickets (known-bug good news, how-to, already-cancelled confirms, redirects), and
   - tickets whose only required action was a **Stripe cancel-at-period-end that Bert has ALREADY EXECUTED** via `scripts/stripe_cancel_subscription.py` (see `policies/cancellation-policy.md` → "Bert Execution"). After a successful `applied`/`already_off` run, flip the drafted result — `needs_action=false`, `parsed.needs_action=false`, `parsed.auto_sendable=true` — so it joins this bucket and no "Actions needed" note is posted.
2. **NEEDS-ACTION (notes)** — a human must still perform an action Bert cannot execute: refunds, Google Play cancels, coupons, account changes, immediate/dunning cancellations, anything the write skill refused. These get the "Actions needed" internal note; the draft is written as if the action is already done (per `bert_system_prompt.txt`).
3. **ESCALATED** — routed to a human support agent per `policies/escalation-policy.md`: escalation tag + internal note, NO customer draft. Talk these through with Cassidy.

**Order of operations:** execute eligible cancel-at-period-end actions and settle buckets 2 and 3 first (notes added, escalations discussed), **then run the VERIFIER over the whole auto-send bucket** (`apply_result` with `verify_client` — the `auto_send` tag follows the verdict). Take the run as far as possible — drafts posted, notes on, verifier done — before coming back to Cassidy for review; bring policy questions and unclarity with you.

## The loop

Run these in order, but treat step 2 as a hub you can stay in as long as Cassidy wants before moving on.

1. **Summarize** — use the `bert-summarize-mailbox` skill. Present the status: total open, urgent, new, category rollup, known-bug clusters. Do not dump every ticket; give the shape of the mailbox.

2. **Discuss** (hub — loop freely):
   - Dive into a specific ticket → `bert-hydrate-ticket`.
   - Look something up in the codebase or Linear → the existing `research_agent` (`run_research`).
   - Ticket references "Ten Percent Happier," Dan Harris, the podcast, or live events → `bert-disambiguate-10-percent` to web-research the current 10% Happier side and settle which product the customer means.
   - Cassidy states a bug-truth / company context / wording preference → append it to the standing brief with `bert.state.append_brief`, then save.
   - **Same customer, two open tickets about the SAME issue** (often surfaced by the
     verifier's sibling check) → consolidate instead of answering twice:
     `bert.pipeline.consolidate_duplicate(session, keep_cid, dup_cid)` — `keep_cid` is the
     conversation whose draft will actually answer. It copies the duplicate's customer
     messages into an internal note on the keeper, posts a "Duplicate of #keeper" note on
     the duplicate, and closes it (in that order — the duplicate is never closed before its
     content lands on the keeper; fails soft and reports what happened). Closing the
     duplicate also unblocks the sibling check, which only counts open conversations.
     Relevance is a judgment call — if the two tickets are about DIFFERENT issues, leave
     both open and answer each.
   - **Mindful Minute Challenge ticket (the Apple-org event ONLY)** → do NOT draft a reply.
     Per `policies/mindful-minute-challenge.md`, move it to the Apple mailbox:
     `bert.fanout.move_to_apple_mailbox(session, conversation_id)`. It returns `"moved"`,
     `"no_mailbox_id"` (APPLE_MAILBOX_ID env var unset — tell Cassidy), or `None` (move
     failed; surface it and leave the ticket for a manual move in the HS UI). Exclude moved
     tickets from the draft fan-out. This applies ONLY to the Mindful Minute Challenge —
     Happier's other meditation challenges (ENL join, in-app challenge events) are normal
     tickets: draft them as usual, never move them.

3. **Draft** — when Cassidy says to draft, use `bert-draft-all`. It injects the *current* standing brief into every worker.

4. **Resolve** — the drafts partition into `ready` and `review`. Walk the `review` set with Cassidy (low-confidence, needs-action, escalations, open questions, suspected bugs). Revise as directed. Use the `bert-resolve` skill to capture any newly-settled truth back into `policies/*.md`.

5. **Post** — on Cassidy's approval, use `bert-post` to post the approved drafts to Help Scout (drafts only — never auto-send).

## Principles

- The standing brief is the mechanism: Cassidy's feedback lands there once and propagates to every draft.
- Never auto-send. Never quote internal context to a customer.
- Fail soft: surface what broke, keep going.
