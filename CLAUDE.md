# Support Agent — Claude Project Instructions

## Project Summary

AI-powered support agent for Happier Meditation. Processes Help Scout tickets end-to-end: triage → account lookup → Stripe enrichment → policy loading → Claude draft → Help Scout draft + internal note. Everything drafts for human review now; auto-send is a future gate.

---

## Repository Map

| File | Status | Purpose |
|---|---|---|
| `orchestrator.py` | Built | Main pipeline: sequences all steps, creates HS draft + note |
| `webhook_server.py` | Live | FastAPI webhook receiver; triggers the orchestrator |
| `triage_tickets.py` | Live | Tags, team, priority, tier classification via Claude |
| `account_context.py` | Built, not connected | Fetches customer/account data from Happier Maven API |
| `maven_customer_context.py` | Built | HTTP client for Maven API (user lookup, subscription, normalization) |
| `stripe_context.py` | Built | Stripe subscription, pricing, discount, upcoming invoice enrichment |
| `pull_policy_docs.py` | Built | Syncs policy docs from Notion into `policies/` |
| `pull_saved_replies.py` | Standalone CLI | Fetches Help Scout saved replies |
| `build_saved_reply_embeddings.py` | Standalone CLI | Embeds saved replies for semantic search |
| `search_saved_replies.py` | Standalone CLI | Searches embedded saved replies |
| `lab_app.py` | Experimental | Scratch/lab code — not part of the production pipeline |
| `policies/` | Live | 17 markdown policy docs, loaded wholesale into every draft prompt |
| `prompts/draft_system_prompt.txt` | Live | System prompt for draft generation (edit here, not in Python) |
| `prompts/triage_prompt.txt` | Live | System prompt for triage classification |

The saved-reply embedding tools (`pull_saved_replies.py`, `build_saved_reply_embeddings.py`, `search_saved_replies.py`) are standalone CLI utilities — not part of the orchestrator pipeline.

---

## Pipeline Flow

```
Help Scout webhook
  → webhook_server.py (signature verification)
    → orchestrator.py
        1. triage_tickets.py          — tags / team / priority / tier
        2. account_context.py         — Maven customer + subscription data
        3. stripe_context.py          — Stripe pricing / discount / invoice (Stripe subscribers only)
        4. policies/*.md              — all policy docs loaded as full text
        5. Claude (draft_system_prompt.txt) — draft reply + classification JSON
        6. Help Scout POST /v2/conversations/{id}/reply  (draft: true)
        7. Help Scout POST /v2/conversations/{id}/notes  (classification metadata)
```

---

## Key Architecture Decisions

- **All policy docs are loaded into every prompt (no RAG).** The corpus is ~17 docs, ~15-20k tokens. Full context is more reliable than retrieval at this scale. Revisit if corpus exceeds ~40 docs.
- **Stripe enrichment only runs for Stripe subscribers.** Apple/Google subscribers are skipped — we can't act on their subscriptions from the backend anyway.
- **Classification and draft come from one Claude call.** No separate classifier. One call returns: `draft_reply`, `needs_action`, `auto_sendable`, `confidence`, `referenced_policies`, `reasoning`.
- **`auto_sendable` is captured but not acted on.** Auto-send is a future feature gated by env var. Right now everything goes to draft.
- **Default to safe classifications.** If uncertain: `needs_action = true`, `auto_sendable = false`. A false positive (unnecessary human review) is far less costly than a false negative.

---

## Notion Sync

Policy docs live in two places: the `policies/` directory in this repo (used by the AI pipeline) and the **Support Policy Docs** page in Notion (used by the human team). **Both must be kept in sync.** Whenever a policy doc is updated in either place, update the other immediately. The repo is the source of truth for structure and AI-facing content; Notion is the source of truth for human readability and team review.

**This is a hard requirement every time a policy doc is created or updated:**
1. Add/update the `.md` file in `policies/`
2. Add/update the corresponding page in the **Support Policy Docs** Notion page (ID: `356cffdf-527f-808d-a4fc-f7d05499523f`)

Never consider a policy doc task complete until both locations are updated.

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
5. **Sync to Notion** — follow the Notion Sync requirement: add the corresponding page under the **Support Policy Docs** Notion page (ID: `356cffdf-527f-808d-a4fc-f7d05499523f`).

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
HELPSCOUT_NOTE_USER_ID        # HS user id for AI-authored notes (optional but recommended)

# Anthropic
ANTHROPIC_API_KEY

# Maven / Happier API
MAVEN_API_BASE_URL
MAVEN_API_KEY                 # or equivalent auth

# Stripe (optional enrichment)
STRIPE_READ_API_KEY           # read-only restricted key

# Linear (product prioritization)
LINEAR_API_KEY                # personal API key from Linear settings
LINEAR_PRODUCT_TEAM_ID        # UUID of the product prioritization team; run `python product_prioritization.py` to list all team IDs

# Future
AUTO_SEND_ENABLED=false       # gate for auto-send; currently always false
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
- Model: `claude-sonnet-4-6` (current default)
- Use prompt caching on system prompt and policy docs (large, static content)
- Parse Claude's response as JSON; handle malformed output gracefully with retry logic

---

## Claude's Role in This Project

You are a senior Python backend engineer working on this pipeline. When helping with this codebase:

- Treat the existing working modules as stable unless there's a clear integration bug
- Keep new code composable and focused — the orchestrator sequences steps, each module does one thing
- Fail soft on enrichment steps (Stripe, account lookup), hard on core steps (triage, draft generation)
- When modifying prompts, edit the `.txt` files in `prompts/`, not Python strings
- When adding policy content, add a markdown file to `policies/`, not code
