# Bert Test Run — Design Spec

## Goal

Run the full support pipeline against all active assigned Help Scout tickets using Sonnet 5, with current company context injected. Produce:

1. Real drafts posted to Help Scout for human review
2. A Linear ticket for streak-related bug reports (modeled on T-759)
3. An action log of things needing manual intervention (Stripe refunds, coupon applications, etc.)
4. A policy gap doc listing questions/topics the pipeline couldn't confidently answer
5. A surface of any new/unknown bugs found in the tickets
6. A holistic eval of the pipeline's performance
7. A build proposal for Bert v1

---

## Architecture

No new systems. We modify the existing `batch_maven_drafts.py` flow with three changes:

### 1. Company Context Injection

Add a `CURRENT_CONTEXT` block to the system prompt (`prompts/draft_system_prompt.txt`) that gives the model situational awareness. This goes at the end of the existing system prompt, before the response format section:

```
=== CURRENT COMPANY CONTEXT (as of July 2, 2026) ===
- We just released the Hotwire Native Android app. Bug reports from Android users are expected.
- Meditation pausing/freezing bug: This was FIXED yesterday (July 1). If a user reports this issue, 
  ask them to update their app and let us know if the issue persists after the update.
- Milestones are currently broken on the new app. We are actively working on a fix. Acknowledge 
  the issue and let the user know we're working on it.
- Streak data issues: We are aware of reports of streaks being broken/reset. We are investigating. 
  Acknowledge and let the user know we're looking into it.
```

### 2. Model Override

Set `CLAUDE_DRAFT_MODEL=claude-sonnet-5` in the environment for this run.

### 3. Test Run Script

Create `test_run.py` — a modified batch script that:

- Pulls all **active** tickets from the mailbox (same as `batch_maven_drafts.py`)
- Runs `process_ticket_sync` on each with `skip_triage=True` (triage separately to save time, drafts are the focus)
- Captures full results JSON to `test_run_results_{timestamp}.json`
- Does NOT modify the batch script itself — new file, imports from existing modules

The existing pipeline already:
- Posts drafts to Help Scout (`draft: true`)
- Captures `needs_action`, `action_description`, `escalated`, `confidence`, `referenced_policies`, `reasoning`
- Returns structured JSON per ticket

### 4. Post-Run Analysis Script

Create `test_run_analysis.py` that reads the results JSON and produces:

**a) Streak Bug Report → Linear Ticket**
- Filter tickets where tags/subject/body mention "streak" or the model's reasoning references streak issues
- Collect: email addresses, ticket text (truncated), conversation IDs
- Format as a Linear ticket description matching T-759's structure (user reports with emails, separated by `---`)
- Create the ticket via Linear MCP in team T (Engineering Priorities)

**b) Action Log (Admin + Stripe To-Do List)**
- Filter tickets where `needs_action == true`
- Group by `action_description` type (refund, coupon, cancellation, account merge, etc.)
- For each action, specify WHERE it needs to happen: Stripe dashboard, Happier admin, Help Scout, or elsewhere
- Output: conversation ID, customer email, action needed, where to do it, confidence
- This is a concrete checklist of things Cassidy needs to go do in Stripe/admin after reviewing drafts

**c) Policy Gap Doc**
- Filter tickets where `confidence == "low"` or `referenced_policies` is empty
- Include the ticket subject, the model's reasoning, and what policy was missing
- Also flag any ticket where the model says "I don't have a policy for this" in the draft or reasoning

**d) New Bug Surface**
- Filter tickets that mention bugs/issues not covered by the three known ones (meditation pause, milestones, streaks)
- Present: conversation ID, subject, relevant excerpt, customer email

**e) Eval Scorecard**
For each ticket, capture:
- `confidence` (from Claude's self-assessment)
- `auto_sendable` (Claude's judgment on whether this could be auto-sent)
- `escalated` (did it punt to a human?)
- `needs_action` (does it require non-reply work?)
- `referenced_policies` (did it find relevant policy docs?)
- `account_lookup_success` / `stripe_enrichment_success` (did enrichment work?)
- `latency_ms`
- Token usage

Aggregate into:
- Total tickets processed
- Draft success rate (drafts created / total)
- Escalation rate
- Action-required rate
- Auto-sendable rate
- Confidence distribution (high/medium/low)
- Policy coverage (% of tickets that matched at least one policy)
- Average latency and token usage
- Account lookup success rate
- Stripe enrichment success rate

---

## Output Files

All outputs go to `SupportAgent/eval/2026-07-02/`:

| File | Contents |
|------|----------|
| `results.json` | Raw pipeline output for every ticket |
| `action_log.md` | Tickets needing manual Stripe/account actions |
| `policy_gaps.md` | Low-confidence tickets and missing policy areas |
| `new_bugs.md` | Unrecognized bug reports to review |
| `eval_scorecard.md` | Aggregate metrics and per-ticket scores |
| `build_proposal.md` | Final build proposal for Bert v1 (written after eval review) |

The streak bug Linear ticket is created directly via the Linear API, not as a local file.

---

## What We're NOT Changing

- `orchestrator.py` — no modifications, we call `process_ticket_sync` as-is
- `webhook_server.py` — not involved in this test
- `triage_tickets.py` — not modified
- Policy docs — not modified (we're evaluating them as-is)
- `batch_maven_drafts.py` — not modified (we write a new script that does similar work with extras)

---

## Risks & Mitigations

- **Drafts posted to real tickets**: This is intentional — user chose to post real drafts. All drafts are marked `draft: true` so they require manual send.
- **Rate limiting**: Help Scout and Stripe both rate-limit. The existing pipeline handles 429s with retry. We run 5 workers max (same as batch script).
- **Model availability**: If `claude-sonnet-5` is unavailable or errors, the pipeline's retry logic handles transient failures. We'll see it in the results.
- **System prompt modification**: We append to the existing prompt, not replace it. Easy to revert — just remove the `CURRENT COMPANY CONTEXT` block after the test.

---

## Success Criteria

This test run succeeds if we can answer:
1. What % of tickets does the pipeline handle correctly with a draft-quality reply?
2. What policy gaps exist?
3. What account actions are needed that we can't automate yet?
4. What new bugs are customers reporting?
5. Is the pipeline reliable enough to run on every incoming ticket?
