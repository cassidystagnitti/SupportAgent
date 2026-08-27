---
name: bert-morning-review
description: Use when Cassidy says "open Bert" or wants to run the morning support-mailbox review. Orchestrates the full loop — summarize the mailbox, discuss status, draft every reply with the standing brief, review low-confidence drafts together, and post approved drafts.
---

# Bert Morning Review

You are running the attended morning review of the Happier Meditation Help Scout mailbox. Load `bert/prompts/bert_system_prompt.txt` as your operating instructions — especially the two-context model (standing brief vs. per-ticket context).

Keep the morning-review state file (`bert.state`) as your working memory: it holds the ticket index (`records`), the standing brief (`brief`), and per-ticket `statuses`. Load today's state at the start; save after each step that changes it.

## The three buckets (standing model — minted 2026-07-22, tightened same day)

Every open ticket is in exactly ONE bucket at all times — **the highest-priority invariant of the review is that the mailbox always lines up with these three buckets, with nothing in limbo.** Cassidy does not restate this each morning; it is the default frame.

1. **AUTO-SEND** — the MAJORITY. Definition: **no unresolved "Actions needed" note and not escalated** — these replies go out without a human read. Membership IS the `auto_send` tag: every drafted bucket-1 conversation carries the tag (`should_auto_send` = ok draft, not needs-action, not escalated; the draft brain's per-ticket `auto_sendable`/`confidence` do NOT gate it). Includes reply-only tickets of every kind, clarifying-question replies, and tickets whose only action Bert already executed (cancel-at-period-end, full Stripe refunds — the "Action executed" note does NOT pull a ticket out; only an unresolved "Actions needed" note does, and a later "Resolved" note supersedes an earlier "Actions needed" note).
2. **NEEDS-ACTION (notes)** — a human must still perform an action Bert cannot execute: Google Play refunds/cancels, coupons, account changes, dunning cancellations, dispute acceptance, anything a write skill refused (each refusal reason maps to a draft response — see the refusal table in policies/refund-policy.md "Bert Execution") — plus any draft the **VERIFIER hit with an ERROR verdict** (`apply_result` posts an "Actions needed" note carrying the findings, which moves the ticket here). The draft is written as if the action is already done (per `bert_system_prompt.txt`).
3. **ESCALATED** — routed to a human support agent per `policies/escalation-policy.md`: escalation tag + internal note, NO customer draft.

**The verifier's role under the lowered bar (Cassidy 2026-07-22):** it runs over every bucket-1 draft at post time and REPAIRS what it can, but it never leaves a ticket untagged in bucket 1 — `SEND_AS_IS` and `MINOR` keep the tag; a verifier crash fails OPEN (tag stays); only an `ERROR` verdict demotes, and demotion means MOVING the ticket to bucket 2 with a findings note. Per-policy "Do Not Auto-Send Conditions" are enforced this same way — as verifier criteria, not as pre-gates on the bucket.

**Not tickets, handled during the initial review (never left open):**
- **Close candidates** (`close_no_reply` thanks-only follow-ups) are **closed immediately** by `apply_result` (note + close) — not held for approval.
- **Spam/bots** (gibberish senders, unsolicited marketing) are noted and closed during the review.
- **Mindful Minute Challenge / Apple-org tickets** are moved to the Apple mailbox.
- **Duplicates** (same customer, same issue) are consolidated into the keeper.
- **Pending-status conversations** (waiting on the customer) are out of scope until the customer replies.

**Stale drafts:** every open ticket is re-drafted fresh each morning — when a customer has replied since an unsent draft was written, the draft is REDRAFTED against the latest message (never left stale). Escalated tickets keep no draft; note any stale one for the support agent to discard.

**Order of operations:** execute eligible Stripe write actions (cancel-at-period-end: skip dry-run when hydrate already showed one eligible sub, apply per policies/cancellation-policy.md "Bert Execution"; full refunds — pre-flight eligibility from context, dry-run, apply per policies/refund-policy.md "Bert Execution"), move/close/consolidate the non-tickets, settle buckets 2 and 3 (notes added, escalations tagged+noted), **then run the VERIFIER over the whole auto-send bucket** (`apply_result` with `verify_client`). Take the run as far as possible before coming back to Cassidy; bring policy questions and unclarity with you. End state every day: bucket 1 fully tagged, bucket 2 fully noted, bucket 3 fully escalation-tagged — three buckets, zero leftovers.

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

5. **Post & send** — use `bert-post`: drafts post/update during the run; on Cassidy's approval of the auto-send bucket, Bert PUBLISHES the tagged drafts (send + close, with the pre-send freshness guard — a customer reply newer than the draft forces a redraft instead of a send). Buckets 2 and 3 are never sent by Bert.

## Principles

- The standing brief is the mechanism: Cassidy's feedback lands there once and propagates to every draft.
- Never auto-send. Never quote internal context to a customer.
- Fail soft: surface what broke, keep going.
