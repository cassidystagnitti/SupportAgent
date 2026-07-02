# Bert v1 Build-Out — Design Spec

**Date:** 2026-07-02
**Scope:** Implement Linear sub-issues SUP-447, 448, 449, 451–462 under SUP-446 (Bert).
**Explicitly excluded:** SUP-450 (auto-send gate). Everything continues to draft; the `auto_send` tag builds confidence first. Actual sending is a future phase.

## Decisions locked with Cassidy

| Decision | Answer |
|---|---|
| Gap queue + action log destination | Notion databases (source of truth) |
| Research skill integration | Two-pass: draft → conditional research → re-draft |
| Downloads policy truth | Coming back soon, no hard ETA, we WILL notify users when restored |
| Check-ins opt-out stance | No setting exists; log removal requests as product feedback |
| Non-support requests routing | Polite decline + close; cold sales: tag + close, no reply |
| Stripe action execution | Scaffold now; v1 = structured "Actions needed" note on the HS ticket; real execution flips on later when write key is approved |
| Standard draft model | `claude-sonnet-5` (code default; env var remains an override) |

## Existing infrastructure to reuse

- `NOTION_TOKEN` (used by `pull_policy_docs.py`) — the pipeline can write Notion databases directly.
- `LINEAR_API_KEY` (used by `product_prioritization.py`) — the pipeline can query/create Linear issues directly.
- Help Scout OAuth2 client (`triage_tickets.py: get_access_token`, `BASE_URL`).
- Tag writing (`orchestrator.py: _update_conversation_tags`).
- JSON-retry pattern (`orchestrator.py: DRAFT_JSON_RETRY_USER_SUFFIX`).
- Local repos for research: `~/code/code-happierMeditation/changecollective.com` (Rails v2), `HappierHybrid-Android` (v2 wrapper), `ten-percent-ios` (v1 native).

---

## Component 1: Pipeline core fixes (SUP-447, 448, 449, 460, model default)

### 1a. Reply detection (SUP-447)

- `process_ticket_sync()` fetches the conversation **first** and inspects threads for published agent messages (`type == "message"`, `state == "published"`). If any exist → reply mode.
- Reply mode is **derived, not passed**: the `is_reply` caller parameter becomes an internal decision (keep the kwarg for backward compat but ignore/log it).
- Reply mode behavior: full conversation history via `get_conversation_history()` feeds the draft prompt; the prompt receives an explicit framing block: "This is an ongoing thread. Respond to the customer's LATEST message. Do not re-answer the original question."
- `webhook_server.py` subscribes to / handles customer-reply webhook events (verify exact HS event name during build, e.g. `convo.customer.reply.created`) and routes them through the same pipeline.

### 1b. action_description reliability (SUP-448)

- `prompts/draft_system_prompt.txt`:
  - `action_description` is REQUIRED (non-null, specific, executable) whenever `needs_action=true`.
  - New field `action_system`: one of `"stripe" | "happier_admin" | "helpscout" | "other"`.
  - 3 few-shot examples of good action descriptions with real-looking parameters.
- Orchestrator validation: `needs_action=true` with empty `action_description` → one corrective retry appended to the conversation (mirror the JSON-retry pattern). If it still fails, fall back to reasoning text and log a warning metric.

### 1c. auto_send tag (SUP-449)

- In the existing tag block: add `auto_send` when `auto_sendable == true` AND `confidence != "low"`.
- Keep `automated`/`technical`/`escalation` behavior unchanged.

### 1d. ThinkingBlock fix (SUP-460)

- Add shared helper (in a small `claude_utils.py` or inside `orchestrator.py` and import): `extract_text(message) -> str` — first content block with `type == "text"`.
- Fix `product_prioritization.py:~155`; audit and fix any other `content[0].text` in `triage_tickets.py`, `maven_orchestrator.py`, `lab_app.py`, `batch_maven_drafts.py`.

### 1e. Model default

- `DEFAULT_CLAUDE_MODEL = "claude-sonnet-5"` in `orchestrator.py`. `CLAUDE_DRAFT_MODEL` env var still overrides. Update `CLAUDE.md` API notes.

## Component 2: Policy docs (SUP-452, 453, 454, 455)

Four new docs in `policies/`, each following the standard structure from `SupportAgent/CLAUDE.md` (Summary, Trigger Conditions, Required Context, Policy/Correct Response, Action Classification, Confidence Notes, Saved Reply Mapping, Related Policies), each synced to the Support Policy Docs Notion page (ID `356cffdf-527f-808d-a4fc-f7d05499523f`). Where no saved reply exists for an area, the mapping section flags the gap explicitly.

### 2a. `downloads-offline.md` (SUP-452)

- Downloads temporarily unavailable in the new app; being restored; coming back soon — no specific date promised.
- We WILL notify users when it's restored (Bert may commit to this).
- Previously downloaded content is inaccessible during this window; do not speculate about whether it must be re-downloaded.
- Churn-threat variant (cancel threats over downloads): acknowledge + notify commitment + do NOT auto-send; flag for human review.
- Never fabricate an ETA.

### 2b. `check-ins-goals-intentions.md` (SUP-453)

- Feature overview: check-ins, monthly practice goals, intention setting.
- Opt-out stance: **no setting exists to hide/disable**; acknowledge, brief explanation, log as product feedback (feedback-policy conduit).
- Known bugs cross-reference: intention text box (T-788), goal-save freeze, check-in flow issues → see `known-bugs.md`.

### 2c. `known-bugs.md` (SUP-454) — living doc

- One entry per bug: status (investigating / fix in progress / fixed on DATE — ask users to update), affected platforms/versions, customer script, Linear ticket link, date added/resolved.
- Seed with: meditation pausing (fixed 7/1 — ask to update), milestones broken, streaks broken (T-786), downloads unavailable (see downloads doc), Do Not Disturb broken (T-787), intention text box (T-788), Restart Course button unresponsive, goal-setting freeze on save, UI theme/white background change.
- **Remove the hardcoded `=== CURRENT COMPANY CONTEXT ===` block from `prompts/draft_system_prompt.txt`** — this doc replaces it and loads with the rest of `policies/`.
- Update process documented at the top of the doc: edit this doc (repo + Notion) when a bug's status changes; no prompt/code edits.

### 2d. `non-support-requests.md` (SUP-455)

- Categories: podcast/guest pitch, partnership, press, influencer/collab, cold sales, spam.
- Response: polite one-paragraph decline, close conversation. Cold sales/spam: tag + close, no reply.
- Escalation: genuine major-press or significant-partner inquiries → human review (do not auto-send).

## Component 3: Notion workspace (SUP-451, SUP-456)

New module `notion_bridge.py` (Notion REST API via `NOTION_TOKEN`):

### 3a. Bert Gap Queue database

Properties: Question (title) · Status (Open / Answered / Incorporated) · Source tickets (HS links, multi) · Frequency (number) · First seen / Last seen (dates) · Answer (rich text) · Target policy doc (select) · Notes.

- Pipeline hook: on every result with `confidence == "low"` OR empty `referenced_policies` OR gap phrasing in reasoning → Bert formulates the **specific question it needs answered** via a new `open_question` field in the draft JSON schema (no extra API call) and upserts to the queue.
- Dedupe: fuzzy match on normalized question text (difflib ratio ≥ 0.75 — no embedding infra); duplicates increment Frequency and append source tickets. **No filtering — every one-off is captured.**

### 3b. Bert Action Log database

Properties: Action (title) · System (Stripe / Happier admin / Help Scout / Other) · Ticket (HS link) · Customer email · Confidence · Done (checkbox) · Created (date).

- Pipeline hook: every `needs_action=true` result upserts a row (idempotent per conversation+action).

### 3c. Write-back flow

- `process_answered_gaps.py`: reads Status=Answered rows → drafts the policy-doc addition (new doc or section edit in `policies/`) → prints diff for human approval → on approval writes repo file + syncs Notion policy page → sets row to Incorporated.
- Run manually/by Claude session for now; cron later.

## Component 4: Research skill — two-pass (SUP-462)

New module `research_agent.py`:

- **Trigger** (after first draft): `confidence == "low"` OR empty `referenced_policies` OR new JSON flag `needs_product_research == true` (added to draft schema for product-behavior questions).
- **Inputs:** ticket text, account data, platform/version detection (from ticket text + subscription platform: apple → iOS, google → Android, stripe → any; v1 native vs v2 Hotwire Native inferred from app-version clues in ticket).
- **Tools (agentic loop, Anthropic tool use):**
  1. `search_code(query, repo)` — ripgrep over configured repo roots (`changecollective.com`, `HappierHybrid-Android`, `ten-percent-ios`), returns matches with file paths.
  2. `read_file(path, start, end)` — bounded file reads.
  3. `search_linear(query, states)` — Technical team ("T") issues via `LINEAR_API_KEY`: open/in-progress/recently-completed.
- **Limits:** max 15 tool calls or 3 minutes; read-only everywhere.
- **Output:** findings summary + sources list (file paths, Linear IDs).
- **Second pass:** re-run the draft call with a `=== RESEARCH FINDINGS ===` block; the internal note gains a "Research: checked X, Y, Z" section with sources. On timeout/failure → current flag-for-review behavior (fail soft).
- Findings also recorded on the gap-queue row so the same question is never researched twice.
- Guardrail in prompt: never quote code or internal ticket contents to the customer.

## Component 5: Bug surfacing (SUP-458)

- Draft JSON schema gains `bug_report`: `{ "is_bug": bool, "matches_known_bug": "<known-bugs.md entry name or null>", "new_bug_summary": "<one-line or null>" }`.
- New module `bug_registry.py`: local JSON registry (`data/bug_candidates.json`) of new-bug candidates — summary, reports[] (email, ticket id, verbatim excerpt), first/last seen.
- Dedupe: against `known-bugs.md` entries and open T-board tickets (reuse `search_linear`); candidate-to-candidate matching by summary similarity.
- **Threshold:** 2+ independent reports → auto-create a Technical-team Linear ticket in the T-759 format (symptom summary, affected users, verbatim quotes) and add the bug to the surfacing note; 1 report → stays in registry, surfaced via gap queue.
- After filing: registry entry links the Linear ticket; future matching reports append a comment or are logged for append.

## Component 6: Actions note v1 + execution scaffold (SUP-457)

- Internal note gains a structured section when `needs_action=true`:

  **Actions needed** — checklist with exact parameters, e.g. "Apply 40% renewal coupon to `sub_xyz` — Stripe dashboard" — derived from `action_description` + `action_system` + Stripe context (real IDs/amounts).
- New module `action_executor.py`:
  - `prepare_coupon(stripe_ctx, pct) -> ActionPlan`, `prepare_cancellation(stripe_ctx, at_period_end=True) -> ActionPlan` — build exact Stripe API params.
  - `execute(plan)` — raises/refuses unless `STRIPE_WRITE_API_KEY` set AND `ACTION_EXECUTION_ENABLED=true`; logs everything; posts a confirmation note on execution.
  - Refunds: prepare/investigate only — money movement stays human even after the key lands.
- Mirrored to the Notion Action Log (Component 3b).

## Component 7: Draft lifecycle (SUP-461)

- Build-time investigation: attempt `PATCH /v2/conversations/{id}/threads/{threadId}` on a draft thread in a test conversation.
  - **If supported:** pipeline records its draft thread ID per conversation (`data/draft_registry.json`) and updates in place on re-draft.
  - **If not:** before drafting, detect an existing Bert draft (via registry or thread scan); skip unless `force=true`; forced re-drafts prepend "⚠️ Supersedes the earlier draft below — discard the old one" to the note.
- Customer reply while a draft is pending → automatic re-draft (reply mode), superseding the stale draft.
- One-off cleanup output: list of the 22 double-drafted conversations from 2026-07-02 (from `fix_reply_drafts.py` results) for manual discard.

## Component 8: Eval harness (SUP-459)

- `eval_run.py`: merge `test_run.py` + `test_run_analysis.py` → one command producing `eval/YYYY-MM-DD/` with results.json, scorecard, action log, policy gaps, new bugs. `--limit`, `--mailbox`, `--dry-run` flags.
- `eval_draft_accuracy.py`: for a past results.json, fetch each conversation's actually-sent reply from HS and classify Bert's draft as sent-unedited / edited / discarded (text similarity); outputs the accuracy number that gates SUP-450 later.
- `eval/trends.md`: appended per run — draft rate, policy coverage, confidence mix, gap count, accuracy.
- Prompt caching: add `cache_control` to the system prompt + policy block if absent; log `cache_read_input_tokens` per call to verify.

## Error handling principles

- Enrichment steps (Notion writes, Linear queries, research, bug registry) **fail soft**: log and continue; a Notion outage must never block a draft.
- Core steps (draft generation, HS draft creation) fail hard as today.
- All new modules follow the existing logging pattern (per-step success/failure, latency, tokens).

## Testing

- Unit tests with mocked HTTP for: reply detection thread parsing, action validation/retry, tag logic, notion_bridge upserts/dedupe, bug registry threshold, action plans, extract_text helper.
- Live validation (acceptance criteria from the Linear tickets): re-run the specific gap tickets from `eval/2026-07-02/results.json` — downloads tickets must reference `downloads-offline.md` at medium/high confidence; DND ticket must match the known-bugs entry; reply conversations must draft against the latest message.
- Final step: full eval run against the live queue and compare the scorecard to today's baseline.

## Build order

1. **Phase 1 — Core fixes:** 1a–1e (SUP-447, 448, 449, 460, model).
2. **Phase 2 — Policy docs:** Component 2 (SUP-452–455), including prompt cleanup + Notion sync.
3. **Phase 3 — Notion + actions:** Components 3 and 6 (SUP-451, 456, 457).
4. **Phase 4 — Research + bugs:** Components 4 and 5 (SUP-462, 458).
5. **Phase 5 — Lifecycle + eval:** Components 7 and 8 (SUP-461, 459).
6. **Validation:** live eval run, scorecard comparison, update Linear tickets.
