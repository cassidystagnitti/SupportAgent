---
name: daily-summary-run
description: Daily 8:40am ET support brief: research shipped/in-progress customer-facing fixes, fan-out draft all tickets, assemble brief (news + 3-bucket pie chart + policy questions + automate-able actions), post to Slack #claude-support
---

> PORTABLE TEMPLATE. `setup-for-teammate.sh` installs this into `~/.claude/scheduled-tasks/daily-summary-run/SKILL.md` and replaces `__CODE_HOME__` with the directory that contains your `SupportAgent` clone (e.g. `~/code`). Source of truth is Cass's live task — sanity-check against it if in doubt.

Run the Happier Meditation daily support brief. You research the day's customer-facing news yourself, draft replies to every open ticket, assemble a structured brief, and post it to Slack #claude-support (channel id C0BKDEKA36V). Work from __CODE_HOME__ (Bert pipeline lives in __CODE_HOME__/SupportAgent).

**COVERAGE MODE (Cass on vacation):** the person running this (Julia) has no deep context. Anywhere this task would "tell Cass," instead put the item under the brief's **Needs a human** list and it will be handled by the on-call/escalation contact. NEVER auto-send a past-tense draft for an action that did not actually execute.

## Step 1 — Research what has gone out / is in progress (last ~24h)

Determine new customer-facing bug changes (just bug fixes right now — not features), both SHIPPED and IN PROGRESS:

- GitHub (org `tenpercenthappier`; `gh` CLI authenticated): merged PRs + releases/tags in `changecollective.com` (Rails) and `HappierHybrid-Android`. "Gone out" = Rails deployed to prod, or Android in a released, updatable version (versions look like `2026.07.21` — check tags/releases for what merged work actually shipped). Work merged but not yet released/deployed = "in progress".
- Linear (Linear MCP tools, e.g. list_issues): bug tickets recently completed (Done) = fixed; bug tickets in In Progress/In Review = in progress. Cross-reference with PRs so each fix is counted once.

STANDING FILTERS (Cass, pervasive until revoked — also in memory file customer-facing-release-comms.md):
- Only Android and Rails deployments that are UI/UX-related (user-visible behavior) are customer-facing/relevant.
- Ignore ALL iOS PRs and iOS Linear tickets.
- Ignore operational/internal items (infra, CI, tooling, analytics, refactors, dev-process).
- NEVER share marketing/growth items with users.
- Never expose inner dev process. Each item is ONE line, either "this bug is fixed" or "this bug is in progress" phrasing — no PR numbers, ticket IDs, branch names, or jargon.

If nothing customer-facing qualifies, the line is simply "No new customer-facing fixes to announce." Don't pad. Check yesterday's brief/state (SupportAgent bert.state) so you don't re-announce news already sent.

## Step 2 — Summarize the mailbox + fan out draft replies

In __CODE_HOME__/SupportAgent:
- Build the open-ticket index: `python3 -m bert.summarize` (Haiku map/reduce; writes today's state). Or invoke the `bert-summarize-mailbox` skill.
- Render the current standing brief with today's Step-1 news as the "big update", then fan out one draft worker per ticket: the `bert-draft-all` skill (`bert.fanout.draft_all(records, session, client, brief, model="claude-sonnet-5")`), then `bert.fanout.partition(results)`.
- Three-bucket model (see bert-morning-review SKILL): AUTO-SEND (no unresolved "Actions needed" note, not escalated), NEEDS-ACTION (human/API action pending), ESCALATED. Anything carrying a pending/open policy question is ESCALATED until the needed info is provided.
- EXECUTE AUTOMATE-ABLE ACTIONS (Cass 2026-07-23 — the run does the thing, it does not just flag it). For every result whose action maps to a LIVE guarded write skill, execute it with `--apply` BEFORE finalizing the draft, then re-run that single ticket through `draft_all([rec]) → apply_result` so the executed action flips it out of needs-action into auto-send with an accurate past-tense draft (verifier Stripe truth-check then confirms and tags it):
  - Cancel-at-period-end → `__CODE_HOME__/SupportAgent/.venv/bin/python __CODE_HOME__/SupportAgent/scripts/stripe_cancel_subscription.py <cus_id> --apply --conversation-id <cid> --json` (look up the `cus_` id by the account email if the note only has the email). Skip the dry-run when hydrate already showed exactly one eligible renewing Stripe sub and the dates match; `--apply` re-runs the same checks. Dry-run (omit `--apply`) only when hydrate is missing or ambiguous.
  - Full refund (within policy) → `__CODE_HOME__/SupportAgent/.venv/bin/python __CODE_HOME__/SupportAgent/scripts/stripe_refund.py …  --apply --conversation-id <cid> --json`. The script enforces its own guards (window 30d annual / 24h monthly, $120 cap, ownership, dispute block) — respect a refusal, do not override.
  - Invoke with those ABSOLUTE paths so the Bash allow-rules in `__CODE_HOME__/.claude/settings.local.json` match. If a write is blocked by the permission classifier, the rule is missing — in COVERAGE MODE, do NOT stop the whole run: skip the execution, leave that ticket in NEEDS-ACTION with its (present-tense) draft, list it under "Needs a human," and never auto-send a past-tense draft for an action that did not execute.
  - DO NOT auto-execute: coupon/discount requests (coupon skill NOT live), any ticket with an open bank dispute (policy forbids refunding a disputed charge), or human judgment calls (extensions, comps, account merges) — these stay needs-action/escalated with a note.
- Run the verifier via `bert.fanout.apply_result(session, r, timestamp=ts, verify_client=client, brief=brief)` per result — it posts/updates the HS draft, runs the verifier, applies the `auto_send` tag, posts action notes, and closes `close_no_reply` tickets. The verifier owns the tag: SEND_AS_IS/MINOR → tagged; ERROR → tag stripped + ticket demoted to needs-action with a findings note. Record outcomes into state.
- COUNT BUCKETS POST-VERIFIER, not from the pre-verifier `partition()`. An auto-send candidate that gets an ERROR verdict moves OUT of auto-send INTO needs-action — so final AUTO-SEND = candidates that ended SEND_AS_IS/MINOR (tag present); final NEEDS-ACTION = pre-verifier needs-action + ERROR-demoted. Note: `apply_result`'s `auto_send_tagged` is a STRING (`"tagged"`/`"already"`/`"removed"`/None), NOT a boolean — count `in ("tagged","already")`. `close_no_reply` tickets are closed and are NOT one of the three buckets.
- Env: run under `SupportAgent/.venv` with `.env` loaded (`bert.summarize` does not auto-load dotenv), e.g. `.venv/bin/python -c "from dotenv import load_dotenv; load_dotenv(); ..."`.
- Do NOT publish or send any customer reply. Drafting + tagging only; auto-send publishing happens only after a human approves.

## Step 3 — Assemble the brief and post to #claude-support

Compose a single Slack message to #claude-support (channel id C0BKDEKA36V) containing, in this order:
1. **Daily brief** — the customer-facing fixed/in-progress one-liners from Step 1 (or the "nothing to announce" line).
2. **Three-bucket breakdown** — counts + percentages for AUTO-SEND / NEEDS-ACTION / ESCALATED. The Slack connector CANNOT upload images, so render the "pie chart" as a proportional emoji bar (🟩 auto-send / 🟨 needs-action / 🟥 escalated, ~10 blocks scaled to the split) with the counts and percentages beside each bucket. Also state the count of tickets closed during review (not a bucket). If a verifier ERROR spike occurs (e.g. most auto-send candidates demoted), flag it as a one-line callout.
3. **Policy questions needing answers** — every open/pending policy question surfaced during drafting. Note that each such ticket is escalated until answered.
4. **Actions** — two sub-lists: (a) **Executed today** — the cancels/refunds the run actually ran in Step 2 (customer + what was done + resulting date/amount, confirmed in `data/stripe_action_log.jsonl`); (b) **Needs a human** — actions with no live skill or that policy keeps manual: coupon/discount requests (coupon skill not yet shipped), open bank disputes (never auto-refund a disputed charge), judgment calls (extensions, comps, account merges), AND any write that was blocked/skipped this run — each with its customer/conversation.

Keep the brief itself glanceable and in a terse digest style (brief bullets, one sentence per item). Do not include inner dev-process detail in the customer-facing section.

## Step 4 — Health ping (coverage mode)

At the very end, whether the run succeeded or hit a problem, confirm in the same Slack message (or a short follow-up) that the run completed and at what time — so the covering teammate knows the morning brief actually ran today. If the run could not complete, post a one-line "⚠️ daily run did not finish — run it manually (see JULIA-RUNBOOK.md §5)" so silence is never mistaken for "no tickets."

After posting, return the Slack message link.
