# Support Plugin (Bert MCP Server) — Design

**Date:** 2026-07-15
**Status:** Approved (brainstorming) — ready for implementation plan
**Author:** Cassidy Stagnitti (with Claude)

## Goal

Give Happier's support teammates a **`support` plugin** they install from the org
marketplace. A coworker opens a Claude session, says *"start doing support tickets,"* and
gets the full **conversational** morning review — summarize the mailbox → discuss the
tickets that need discussing → draft every reply → review the low-confidence ones → post
drafts to Help Scout → capture settled truths back into the policy docs. Same interactive
loop Cassidy runs today, available to the whole team with a trivial install.

This is a **third interface**, distinct from the two in CLAUDE.md: it is mailbox-wide and
conversational (in a Claude session), where the Help Scout sidebar is per-ticket.

## The core problem this solves

The only hard part of sharing Bert is **secrets**. The pipeline needs Help Scout, Anthropic,
Stripe, Happier backend, and GitHub credentials. Putting that `.env` (plus a Python env) on
every teammate's laptop means secret-sprawl, rotation pain, and "works on my machine"
breakage. Every earlier option (self-contained plugin, cloned backend) inherited that pain.

**Solution: stop distributing secrets.** Keep the pipeline and its secrets in one place —
the Render service that already runs the sidebar — and expose Bert's operations as an **MCP
server**. The plugin ships no Python, no `.env`, no clone: just skills + a pointer to the
hosted server + one low-sensitivity auth token. The conversation happens in the coworker's
Claude session; the secret-bearing work happens server-side.

## Architecture

```
Coworker's Claude session                    Render (secrets already here)
┌───────────────────────────┐   MCP/HTTP    ┌──────────────────────────────┐
│ support plugin (skills)    │ ───────────▶ │ Bert MCP server              │
│  - orchestrates the loop   │   Bearer     │  wraps existing backend fns  │
│  - holds standing brief    │   token      │   summarize / pipeline /     │
│    + ticket index in       │ ◀─────────── │   fanout / research /        │
│    session working memory  │   results    │   policy_updater             │
└───────────────────────────┘               │  reads .env, policies/, repo │
                                             └──────────────────────────────┘
```

- **Secrets & pipeline:** stay in the backend repo, deployed on Render. No pipeline rewrite —
  the MCP server is a thin adapter over functions that already exist.
- **Plugin:** thin, marketplace-native (like `devops`/`analytics`). Ships skills + `.mcp.json`
  + README. Nothing sensitive.
- **Conversation + standing brief:** live in the coworker's Claude session. The brief is
  working memory, appended to as they talk, and passed into `draft_all` on every call — so a
  mid-review correction propagates to every subsequent draft (the batch-wide brief loop that
  makes the review valuable).

## MCP tools (v1)

Each tool wraps code that already exists; the server is an adapter + auth layer.

| Tool | Wraps | Purpose |
|---|---|---|
| `summarize_mailbox()` | `bert.summarize` | Fetch open tickets, Haiku map/reduce → mailbox index (records) |
| `hydrate_ticket(conversation_id)` | `bert.pipeline.hydrate_ticket` | Full read-only context for one ticket (deep dive) — no writes |
| `research(query)` | `research_agent.run_research` | Codebase + Linear lookup during discussion |
| `draft_all(records, brief)` | `bert.fanout.draft_all` + `partition` | Draft every reply with the current brief → `{ready, review}` |
| `draft_ticket(conversation_id, brief)` | `bert.fanout` | Re-draft one ticket after a revision |
| `post_drafts(results)` | `bert.fanout.apply_result` | Post drafts to Help Scout (draft only, never auto-send) + notes |
| `propose_policy_update(policy_file, edit_type, target_text, new_text)` | `policy_updater.build_proposal` | Build a policy-doc diff card for review |
| `commit_policy(proposal)` | `policy_updater.confirm_proposal` | Live-apply + commit the policy edit to the repo (`[skip render]`) |

Notes:
- `post_drafts` and `commit_policy` are the only side-effectful tools. Both preserve current
  invariants: drafts never auto-send; policy commits go to git as the single source of truth.
- The backend's `draft_registry` (server-side JSON) dedupes drafts. Centralizing it is a bonus:
  it now prevents two coworkers from double-drafting the same ticket.

## Skills (in `plugins/support/skills/`)

The 6 local skills consolidate, because "how to run this Python" is now a single tool call:

- **`support-review`** — the orchestrator. Describes the loop and when to call which tool:
  summarize → discuss (hub: `hydrate_ticket`, `research`, append to brief) → `draft_all` →
  walk the `review` set → `post_drafts`. Triggered by "start doing support tickets" / "open Bert".
- **`support-resolve`** — the judgment-heavy policy-capture discipline: when a settled truth
  should become a policy edit, how to draft it, and the `propose_policy_update` → review →
  `commit_policy` flow.

(The old `summarize` / `draft-all` / `hydrate` / `post` skills fold into tool calls; whether a
thin wrapper skill survives for any of them is an implementation-plan detail.)

Cassidy's local `.claude/skills/` are **retired** — the plugin + MCP server is the single code
path for everyone, including Cassidy. Cassidy still develops the backend locally and deploys.

## Plugin layout (`plugins/support/` in the marketplace repo)

```
plugins/support/
  .claude-plugin/plugin.json     # name: support, version, description, author
  .mcp.json                      # remote MCP server + Bearer ${SUPPORT_MCP_TOKEN}
  skills/
    support-review/SKILL.md
    support-resolve/SKILL.md
  README.md                      # install + token setup
```

`.mcp.json`:
```json
{
  "mcpServers": {
    "bert": {
      "type": "http",
      "url": "https://<render-service-host>/mcp",
      "headers": { "Authorization": "Bearer ${SUPPORT_MCP_TOKEN}" }
    }
  }
}
```

Plus a new entry in the marketplace's `.claude-plugin/marketplace.json`
(`{ "name": "support", "source": "./plugins/support", "description": "..." }`).

## Setup for a coworker

1. `/plugin marketplace add TenPercentHappier/claude-marketplace` (already done for other plugins)
2. `/plugin install support@happier`
3. Set one env var: `SUPPORT_MCP_TOKEN` (obtained from Cassidy / 1Password).
4. Open Claude, say "start doing support tickets."

No Python, no clone, no venv, no `.env`. One token, not a credential set.

## Changes to the backend repo (this repo)

1. **Add the MCP server** — a new module (e.g. `mcp_server.py`) exposing the 8 tools above by
   calling existing functions. Built with the Python MCP SDK (FastMCP or equivalent).
2. **Auth** — validate a Bearer token against `SUPPORT_MCP_TOKEN` (single shared secret for v1;
   per-user tokens a later option) on every tool call.
3. **Deploy on Render** — as a process/service alongside the sidebar, reusing the existing
   secret configuration. No new secrets beyond `SUPPORT_MCP_TOKEN`.
4. **Retire `.claude/skills/`** — move to the marketplace plugin (consolidated) so there is one
   skill set.
5. **Update `CLAUDE.md`** — document the third interface (Claude session via the support plugin).

No changes to the 18 pipeline files, the orchestrator, or the sidebar behavior.

## Marketplace repo changes (`TenPercentHappier/claude-marketplace`)

- Add `plugins/support/` (layout above).
- Add the `support` entry to `.claude-plugin/marketplace.json`.
- (Delivered via a branch/PR to that repo.)

## Design risks & how we handle them

- **`draft_all` latency.** It fans out many Claude calls; a synchronous MCP tool call could
  exceed the client timeout on a large mailbox. v1: run synchronous with the existing parallel
  fan-out and a generous server timeout. **Fallback if it bites:** split into `start_draft_all`
  (returns a job id) + `get_draft_status(job_id)` and have the skill poll — the same 202+poll
  pattern `sidebar_server.py` already uses for chat.
- **Concurrent reviewers.** Two coworkers reviewing the same mailbox could target the same
  tickets. The shared server-side `draft_registry` prevents duplicate drafts; beyond that, v1
  assumes one reviewer at a time (documented, not enforced).
- **Auth strength.** A single shared `SUPPORT_MCP_TOKEN` gates all tools. It is far less
  sensitive than the full `.env`, rotates in one place, and can be upgraded to per-user tokens
  or OAuth later.

## Acceptance / testing

1. Run the MCP server locally; connect a Claude session via a local `.mcp.json`; confirm each
   tool returns sane data (summarize, hydrate, research, draft_all, draft_ticket).
2. Drive the full loop end-to-end against a real ticket: "start doing support tickets" →
   summary → discuss → draft → review → `post_drafts` → confirm a **draft** (never auto-sent)
   lands in Help Scout.
3. Exercise policy capture: propose a policy edit in conversation → `commit_policy` → confirm
   the commit lands in the repo with `[skip render]`.
4. Deploy to Render; install the plugin from the marketplace on a **non-Cassidy** machine with
   only `SUPPORT_MCP_TOKEN` set; confirm the full loop works with nothing else installed.

## Out of scope (v1)

- Slack integration (evaluated, set aside — can't carry the conversational loop without a rebuild).
- Vendoring or cloning the backend to teammates' machines (superseded by the MCP server).
- Auto-send (remains gated; drafts only).
- Changes to the Help Scout sidebar chat.
- Per-user auth / OAuth for the MCP server (single shared token in v1).

## Open follow-ups (non-blocking)

- Whether any per-user server-side state (e.g. resumable review sessions) is worth adding; v1
  keeps state in the Claude session.
- Async job pattern for `draft_all` if synchronous latency proves too high (see risks).
- Retiring `pull_policy_docs.py` / other vestigial modules is unrelated and stays out.
