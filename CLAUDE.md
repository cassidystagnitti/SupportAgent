# Support Agent — Claude Project Instructions

## Project Summary

AI-powered support agent for Happier Meditation. Processes Help Scout tickets end-to-end: triage → account lookup → Stripe enrichment → policy loading → Claude draft → Help Scout draft + internal note. Everything drafts for human review now; auto-send is a future gate.

---

## Repository Map

| File | Status | Purpose |
|---|---|---|
| `orchestrator.py` | Built | Main pipeline: sequences all steps, creates HS draft + note |
| `sidebar_server.py` | Live | FastAPI app for the HS sidebar: serves the chat UI, chat endpoints, policy confirm, send-and-close |
| `sidebar_chat.py` | Live | Per-ticket chat sessions with Bert: hydration via bert/pipeline, Anthropic tool loop (update_draft, propose_policy_update) |
| `policy_updater.py` | Live | Confirmed policy updates: live apply + GitHub commit (`[skip render]`); git is the single source of truth |
| `mcp_server.py` | Live | Bert MCP server (FastMCP, streamable HTTP): exposes the morning-review pipeline as MCP tools for the `support` marketplace plugin; Bearer-token auth (`SUPPORT_MCP_TOKEN`). Deployed on Render alongside the sidebar. Requires Python ≥3.10. |
| `bert/mcp_tools.py` | Live | Adapter behind `mcp_server.py`: thin wrappers over `bert.summarize`/`pipeline`/`fanout`, `research_agent`, `policy_updater`; keeps heavy draft results in an ephemeral server-side run store, returns compact views. No MCP import (unit-testable on any Python). |
| `static/sidebar.html` | Live | Sidebar chat frontend (vanilla JS; postMessage context handshake) |
| `triage_tickets.py` | Live | Tags, team, priority, tier classification via Claude |
| `account_context.py` | Built, not connected | Fetches customer/account data from Happier Maven API |
| `maven_customer_context.py` | Built | HTTP client for Maven API (user lookup, subscription, normalization) |
| `stripe_context.py` | Built | Stripe subscription, pricing, discount, upcoming invoice enrichment |
| `pull_policy_docs.py` | Vestigial | (Notion policy sync abandoned 2026-07-14) formerly synced policy docs from Notion into `policies/` |
| `pull_saved_replies.py` | Standalone CLI | Fetches Help Scout saved replies |
| `build_saved_reply_embeddings.py` | Standalone CLI | Embeds saved replies for semantic search |
| `search_saved_replies.py` | Standalone CLI | Searches embedded saved replies |
| `push_kb_docs.py` | Standalone CLI | Syncs policies/*.md to Help Scout Docs (private/internal collection) |
| `lab_app.py` | Experimental | Scratch/lab code — not part of the production pipeline |
| `claude_utils.py` | Live | Shared helper to extract text from Anthropic API responses (tolerates ThinkingBlock) |
| `notion_bridge.py` | Live | Bert Gap Queue + Bert Action Log Notion databases: upsert gap/action rows, fetch answered gaps; fails soft (raises internally) when `NOTION_TOKEN` is unset |
| `linear_client.py` | Live | GraphQL client for the Technical team's Linear board: search + create issues (bug filing/dedupe) |
| `research_agent.py` | Live | Two-pass codebase + Linear research agent; runs when the first draft is low-confidence, cites no policy, or flags a product question |
| `bug_registry.py` | Live | New-bug candidate registry; auto-files a Linear Technical issue once a fuzzy-matched bug summary has 2+ reports |
| `action_executor.py` | Built, execution gated | Prepared-action scaffold for Stripe-affecting actions (coupon, cancellation); builds the "Actions needed" note now, real writes wait on `STRIPE_WRITE_API_KEY` + `ACTION_EXECUTION_ENABLED` |
| `draft_registry.py` | Live | Local JSON registry of conversation → drafted thread; prevents duplicate Help Scout drafts and drives the skip/supersede decision |
| `eval_run.py` | Standalone CLI | Repeatable eval harness: batch-runs the draft pipeline over active tickets, writes `eval/<date>/results.json` |
| `eval_draft_accuracy.py` | Standalone CLI | Compares Bert's draft against the reply a human agent actually sent, per eval run |
| `eval_reports.py` | Built | Shared report generators (action log, policy gaps, new bugs, scorecard) used by `eval_run.py` |
| `process_answered_gaps.py` | Vestigial | (Notion policy sync abandoned 2026-07-14) formerly wrote answered Gap Queue rows back into `policies/*.md` |
| `scripts/sync_new_policy_docs.py` | Vestigial | (Notion policy sync abandoned 2026-07-14) formerly pushed `policies/*.md` to Notion child pages |
| `scripts/list_stale_drafts.py` | Standalone CLI | Seeds the draft registry from a past eval run and lists conversations with duplicate live drafts to clean up manually |
| `policies/` | Live | 21 markdown policy docs, loaded wholesale into every draft prompt |
| `prompts/draft_system_prompt.txt` | Live | System prompt for draft generation (edit here, not in Python) |
| `prompts/triage_prompt.txt` | Live | System prompt for triage classification |

The saved-reply embedding tools (`pull_saved_replies.py`, `build_saved_reply_embeddings.py`, `search_saved_replies.py`) are standalone CLI utilities — not part of the orchestrator pipeline.

---

## Interfaces

There are three ways tickets get worked:

1. **Bert via Claude Chat** (local) — the bert-morning-review skill family in `.claude/skills/`:
   summarize the mailbox, batch-draft with the standing brief, review, post drafts. Runs the
   pipeline directly against this repo (Cassidy's local dev loop).
2. **`support` marketplace plugin → Bert MCP server** (the shareable morning review) —
   teammates install `support@happier` from `TenPercentHappier/claude-marketplace`, and its
   `support-review` / `support-resolve` skills drive `mcp_server.py` (deployed on Render) over
   MCP. Same conversational loop as #1, but no local secrets/Python — the server holds them.
   The standing brief lives in the coworker's Claude session and is passed into `draft_all`.
3. **Help Scout sidebar chat** (Render) — `sidebar_server.py` + `sidebar_chat.py`. An agent
   opens a conversation, chats with Bert (context rehydrated on demand via
   `bert/pipeline.hydrate_ticket`), Bert updates the HS draft in place via tool calls,
   proposes policy-doc updates as diff cards (Confirm → live apply + GitHub commit with
   `[skip render]`; git is the single source of truth), and the agent can Send & close (publish draft thread →
   close conversation) as the Support Automations user.

The webhook auto-trigger (`webhook_server.py`) and the MavenAGI draft engine were sunset
2026-07-14 (see docs/superpowers/specs/2026-07-14-hs-sidebar-chat-design.md).

## Pipeline Flow (draft brain, shared by both interfaces)

```
orchestrator.py (invoked per ticket by Bert skills / sidebar chat hydration)
        0. detect_reply_mode()         — is there already a published agent thread? changes which
                                          message the draft addresses (latest reply vs. original)
        1. triage_tickets.py          — tags / team / priority / tier (skipped in reply mode)
        2. account_context.py         — Maven customer + subscription data
        3. stripe_context.py          — Stripe pricing / discount / invoice (Stripe subscribers only)
        4. policies/*.md              — all policy docs loaded as full text
        5. Claude (draft_system_prompt.txt) — draft reply + classification JSON
        5a. research_agent.py          — two-pass codebase + Linear research, only when the first
                                          draft is low-confidence, cites no policy, or flags a product
                                          question; re-drafts with findings appended
        6. draft_registry.py           — skip a duplicate draft, or mark this one as superseding an
                                          earlier draft thread (reply mode / forced re-draft)
        7. Help Scout POST /v2/conversations/{id}/reply  (draft: true)
        8. Help Scout POST /v2/conversations/{id}/notes  (classification metadata + supersede banner)
        9. notion_bridge.py            — best-effort: log an open policy gap and/or a manual action
                                          row to Notion (Bert Gap Queue / Bert Action Log); fails soft
                                          if NOTION_TOKEN is unset or the API call errors
       10. bug_registry.py             — best-effort: track new-bug candidates, auto-file to Linear
                                          Technical once a fuzzy-matched summary has 2+ reports
```

---

## Key Architecture Decisions

- **All policy docs are loaded into every prompt (no RAG).** The corpus is ~17 docs, ~15-20k tokens. Full context is more reliable than retrieval at this scale. Revisit if corpus exceeds ~40 docs.
- **Stripe enrichment only runs for Stripe subscribers.** Apple/Google subscribers are skipped — we can't act on their subscriptions from the backend anyway.
- **Classification and draft come from one Claude call.** No separate classifier. One call returns: `draft_reply`, `needs_action`, `auto_sendable`, `confidence`, `referenced_policies`, `reasoning`.
- **`needs_action` is a send-precondition on the DRAFT, not a property of the conversation.** It is true only when a human must complete an action to make the drafted reply true *before it can be sent* (e.g. the reply says "I've refunded $99.99" and the refund must actually be run first). A reply that is true and sendable exactly as written — even when the customer's issue will need follow-up work on a later turn — is `needs_action = false`. Canonical case: a refund request where we can't find the account gets a self-contained "confirm the email on your account" reply → `needs_action = false`, no action note, auto-send candidate; the refund only becomes a send-blocking action on the later turn where we actually have the account. This is the model that moves us toward auto-sending every draft that can go as-is and attaching an "Actions needed" note only to the drafts a human must act on first. The send-precondition test lives in `prompts/draft_system_prompt.txt`; `should_post_note` (note) and the `auto_sendable` invariant in `orchestrator.py` both key off it. **The decision is per-draft, not per-ticket — it is re-made every time a draft is (re)generated or edited, and it can flip across a ticket's lifecycle.** The batch pipeline re-classifies on every run (reply mode / stale-redraft / force), so it recomputes automatically; the sidebar chat's `update_draft` tool requires a fresh `needs_action` (+ `action_description`) on every call (`sidebar_chat.py` records it on the session and surfaces "sendable as-is" vs. "blocked on action" to the teammate).
- **`auto_sendable` is captured but not acted on (auto-send is still gated off).** It is forced `false` whenever `needs_action` is true, on escalations, and on ambiguous-account cases — a draft can only ever be auto-sent when it's true and complete exactly as written. Right now everything still goes to draft for human review.
- **Default to safe classifications.** If genuinely uncertain whether the draft asserts a not-yet-completed action: `needs_action = true`, `auto_sendable = false`. A false positive (unnecessary human review) is far less costly than a false negative (sending something that isn't true yet). But do not reflexively flag — a self-contained reply is `needs_action = false` even when the conversation will need action later.

---

## Policy Doc Source of Truth

**The `policies/` directory in this git repo is the single source of truth for policy docs.** The old two-way Notion sync (Support Policy Docs page) was abandoned on 2026-07-14 — do NOT sync policy docs to Notion, and do not treat Notion as a policy source. The team reads policies via GitHub; the sidebar chat's Confirm flow commits policy updates directly to the repo. The Notion-sync CLIs (`pull_policy_docs.py`, `scripts/sync_new_policy_docs.py`, `process_answered_gaps.py`) are vestigial.

## Creating Policy Documents

When asked to create a new policy document, follow these steps in order:

1. **Read all existing policy docs** — read every file in `policies/` to understand current coverage, tone, and formatting conventions.
2. **Read all saved replies** — load `data/saved_replies.json` and extract the full list of saved reply names from `mailboxes[0].saved_replies`.
3. **Ask for context** — ask the user for a short summary of the policy area: what triggers this type of ticket, what the correct response is, any edge cases or exceptions, and any relevant saved replies they already know about.
4. **Create the policy doc** — write a new `.md` file in `policies/` following the exact structure used by existing docs:
   - `# <Title>`
   - `# Summary` — one paragraph
   - `# Trigger Conditions` — bullet list of ticket signals, account signals, keywords
   - `# Required Context` — checklist of what the agent needs before responding
   - `# Policy / Correct Response` — Standard Case, Variations, Edge Cases & Exceptions
   - `# Action Classification` — No Action Required / Human Action Required / Do Not Auto-Send Conditions / Escalation Triggers
   - `# Confidence Notes` — high confidence areas, judgment call areas, gaps
   - `# Saved Reply Mapping` — a table (or set of tables by platform/condition) mapping user state + use case → specific saved reply title. Every row must reference an exact saved reply name from `data/saved_replies.json`.
   - `# Related Policies` — cross-references to other policy docs
5. **Commit it** — the git repo is the single source of truth; no Notion step.

Never create a policy doc without a Saved Reply Mapping section. If no saved replies exist yet for the area, note that and flag it as a gap.

---

## Working Principles

- **Don't modify `triage_tickets.py`, `account_context.py`, or `maven_customer_context.py` unless there's a specific integration issue.** The orchestrator calls them — it doesn't rewrite them.
- **Policy knowledge lives in `policies/*.md`, not in Python or prompts.** Never hardcode support policies in code.
- **Prompts live in `prompts/`, not inline in Python.** This lets us iterate on prompts without touching code.
- **Log everything.** Every pipeline run should emit: success/failure per step, classification outputs, token usage, latency, errors. This is how we evaluate and improve.
- **Test with real tickets.** Unit tests are not sufficient — validate against actual Help Scout conversations covering the documented edge cases.

---

## Environment Variables

```bash
# Help Scout
HELPSCOUT_APP_ID
HELPSCOUT_APP_SECRET
HELPSCOUT_WEBHOOK_SECRET      # for signature verification
HELPSCOUT_NOTE_USER_ID        # HS user id AI-authored notes are attributed to. REQUIRED for notes:
                              # if unset, internal notes (incl. "Actions needed" lists) are silently
                              # SKIPPED — drafts still post. Set to the Support Automations agent user id.

# Anthropic
ANTHROPIC_API_KEY

# Sidebar chat (sidebar_server.py / sidebar_chat.py / policy_updater.py)
SIDEBAR_SECRET                # random string; gates every sidebar chat endpoint
HELPSCOUT_AGENT_USER_ID       # HS user id for chat-created drafts + send attribution;
                              # falls back to HELPSCOUT_NOTE_USER_ID
GITHUB_TOKEN                  # fine-grained PAT (contents:write, this repo only) for policy commits
GITHUB_REPO                   # default: cassidystagnitti/SupportAgent
GITHUB_BRANCH                 # default: main

# Bert MCP server (mcp_server.py — the `support` marketplace plugin's backend)
SUPPORT_MCP_TOKEN             # shared bearer token that gates every MCP tool call. Self-issued
                              # (openssl rand -hex 32); set here AND in each teammate's env. Without
                              # it the server fails closed (500). Same pattern as SIDEBAR_SECRET.
BERT_DRAFT_MODEL              # optional — draft model for the MCP draft tools (default: claude-sonnet-5)

# Happier backend ("Maven" API — account/subscription lookup; account_context.py)
HAPPIER_BEARER_TOKEN          # REQUIRED for account lookup (fallback name: ACCOUNT_CONTEXT_BEARER_TOKEN).
                              # Without it, lookup fails soft: drafts still generate but with
                              # "Account lookup failed" context and no Stripe enrichment.
HAPPIER_MAVEN_BASE_URL        # optional — defaults to https://my.happierapp.com/api/maven/v1

# Stripe (optional enrichment)
STRIPE_READ_API_KEY           # read-only restricted key

# Linear (product prioritization)
LINEAR_API_KEY                # personal API key from Linear settings
LINEAR_PRODUCT_TEAM_ID        # UUID of the product prioritization team; run `python product_prioritization.py` to list all team IDs
LINEAR_TECHNICAL_TEAM_ID      # UUID of the Technical team's board; used by linear_client.py + bug_registry.py for bug search/filing.
                               # KNOWN GAP: as of 2026-07-02 the LINEAR_API_KEY in use can see the Product team but not
                               # Technical — Technical-team searches return [] rather than erroring (fails soft), but no
                               # bug is ever actually matched/filed until a key with Technical visibility is supplied.

# Notion (Bert Gap Queue + Bert Action Log — notion_bridge.py)
NOTION_TOKEN                  # Notion integration secret. KNOWN GAP: EMPTY as of 2026-07-02 — every notion_bridge call
                               # raises RuntimeError("NOTION_TOKEN not configured") internally; orchestrator.py catches
                               # this per-call (record_gap_and_action) so it never blocks a draft, but no gap/action rows
                               # are actually written to Notion until this is set.
NOTION_VERSION                # Notion API version header (default: 2022-06-28)

# Help Scout Docs (internal KB sync — push_kb_docs.py)
HELPSCOUT_DOCS_API_KEY        # Docs API key: Settings → Docs → Your Site → API Keys
HELPSCOUT_DOCS_COLLECTION_ID  # ID of the private/internal collection (run push_kb_docs.py --list-collections)

# Stripe write actions (action_executor.py — SUP-457)
STRIPE_WRITE_API_KEY          # write-capable Stripe key for real coupon/cancellation execution. NOT YET SET — execute()
                               # raises NotImplementedError past the env gate until this is approved and provided.
ACTION_EXECUTION_ENABLED      # "true" to allow action_executor.execute() to run at all; default off. Both this AND
                               # STRIPE_WRITE_API_KEY must be set before any real Stripe write happens.

# Future
AUTO_SEND_ENABLED=false       # gate for UNATTENDED auto-send; currently always false. (Human-clicked
                              # sends happen via the sidebar's Send & close button — that's not auto-send.)
```

---

## API Reference Notes

### Help Scout Mailbox API v2
- Drafts: `POST /v2/conversations/{id}/reply` with `{"draft": true}`
- Notes: `POST /v2/conversations/{id}/notes` — notes cannot be saved as drafts
- Auth: OAuth2 client credentials (`APP_ID` + `APP_SECRET` → bearer token)
- Webhook verification: HMAC-SHA1 of request body against `HELPSCOUT_WEBHOOK_SECRET`, compared to `X-HelpScout-Signature` header

### Stripe API
- Customer lookup by email: `stripe.Customer.search(query=f"email:'{email}'")`
- Subscription with expansion: `expand=["data.items.data.price", "data.discount"]`
- Upcoming invoice: `stripe.Invoice.upcoming(customer=customer_id)`
- Always use the **read-only restricted key** — never a full secret key

### Anthropic API
- Model: `claude-sonnet-5` (current default)
- Use prompt caching on system prompt and policy docs (large, static content)
- Parse Claude's response as JSON; handle malformed output gracefully with retry logic

---

## Local Dev Server

The lab/test server runs on `http://127.0.0.1:8765/` via `python3 lab_app.py --port 8765`.

**After any Python file change, kill and restart the server:**
```bash
lsof -ti:8765 | xargs kill -9 && python3 lab_app.py --port 8765 &
```

Policy doc changes (`policies/*.md`) take effect immediately without restart — they are loaded fresh on each request.

---

## Claude's Role in This Project

You are a senior Python backend engineer working on this pipeline. When helping with this codebase:

- Treat the existing working modules as stable unless there's a clear integration bug
- Keep new code composable and focused — the orchestrator sequences steps, each module does one thing
- Fail soft on enrichment steps (Stripe, account lookup), hard on core steps (triage, draft generation)
- When modifying prompts, edit the `.txt` files in `prompts/`, not Python strings
- When adding policy content, add a markdown file to `policies/`, not code
