# Bert Morning Review — Design Spec

**Date:** 2026-07-06
**Scope:** An interactive, attended "morning review" surface for Bert — a Claude session that reads the whole mailbox with Cassidy, discusses status and bug-truths, drafts every reply via a fan-out, surfaces the low-confidence ones for discussion, and posts drafts on approval.
**Relationship to prior work:** This is a **second front door** onto the capabilities built in `2026-07-02-bert-v1-buildout-design.md`. That spec built the *brain* (enrichment, drafting, research, Notion, bug registry, draft lifecycle) and the *unattended door* (`webhook_server.py` → `orchestrator.py`). This spec adds the *attended door*. It does **not** replace or refactor the production pipeline.

> **As-built note (2026-07-06):** v1 shipped as the `bert/` package + `.claude/skills/bert-*` (see `docs/superpowers/plans/2026-07-06-bert-morning-review.md`). One deviation from Component C below: `process_ticket_sync` was **not** surgically refactored. The safety gate for that refactor is a live eval-run diff, which wasn't runnable in the build environment. Instead, Bert's `bert/pipeline.py` reuses the *same primitives* the orchestrator calls (`_call_claude_draft_with_action_retry`, `_build_dynamic_user_message`, `load_policy_docs`) — same brain, zero production risk. Rewiring the orchestrator to share the extracted seams remains a future DRY follow-up, to be done behind the eval-diff gate.

---

## Guiding principle: one brain, two front doors

```
                  ┌─ webhook_server.py → orchestrator.py   (unattended, per-ticket, live)
shared capability ─┤
                  └─ bert/ + .claude/skills/bert-*          (attended, whole-mailbox, new)
```

Both doors call the **same** enrichment, drafting, research, and draft-registry logic. Bert never reimplements drafting inside a skill — if it did, the two doors would silently drift. The interactive surface is glue and orchestration around existing modules, plus a few small shared seams extracted from `orchestrator.py`.

---

## The two-context model (the cost-critical decision)

The design hinges on keeping two kinds of context strictly separate:

**1. The standing brief — small, lives in the session, flows *down*.**
What the interactive session actually holds: the lightweight per-ticket index (Haiku output, one line each) + the running discussion + everything Cassidy establishes during review (bug-truths, company context, wording preferences). It grows as the conversation goes, but stays tiny relative to full ticket bodies. Persisted as part of the morning-review state file.

**2. Per-ticket full context — heavy, lives in ephemeral workers, never sits in the session.**
Drafting fans out: one throwaway worker per ticket. Each worker's prompt = `[standing brief] + [this one ticket's hydrated context] + [relevant policies]`. It drafts, scores confidence, and returns **only** the draft + confidence + reasoning. The session sees results, not raw tickets.

```
Session (brief + index)  ──inject brief──▶  Worker(ticket #1)  ──draft+confidence──▶ back
                         ──inject brief──▶  Worker(ticket #2)  ──draft+confidence──▶ back
                         ──inject brief──▶  Worker(ticket #N)  ──draft+confidence──▶ back
```

The session's context stays roughly **constant** regardless of mailbox size — that is the cost win. Heavy, repetitive per-ticket reading happens in cheap, parallel workers.

**The one deliberate exception:** when Cassidy says "dive into that ticket," that single ticket is hydrated *directly into the session* so they can look at it together. A few tickets a morning, not all of them. Any truth that surfaces during a dive ("the streak bug is fixed as of yesterday") is written into the standing brief, so every downstream draft worker inherits it automatically.

---

## The morning loop

```
open Bert
 → summarize-mailbox (MAP, Haiku)        one cheap call per ticket → per-ticket records → state file
 → mailbox-status (REDUCE, session)      roll up volume/new/urgent → render visual artifact
 → discuss (human-in-loop, a hub)        loop freely:
       ├─ hydrate-ticket                 pull one ticket's full context into the session
       ├─ lookup-code / lookup-linear    research dive (reuses research_agent)
       └─ inject bug-truth               Cassidy states current truth → into the standing brief
 → draft-all (fan-out, strong model)     one worker per ticket; brief + policies injected; confidence scored
 → partition                             high-confidence → ready; low-confidence/flagged → review
 → resolve-low-confidence (human-in-loop) discuss flagged drafts + open Qs; revise; capture-knowledge → policies
 → post-drafts                           HS drafts via draft_registry dedupe + internal note
 → done                                  mailbox drafted & reviewed; KB updated
```

The three human-in-the-loop points are `discuss`, `inject bug-truth`, and `resolve-low-confidence`. Everything else Bert does on its own.

---

## Components

### Component A: `bert/` package (net-new glue)

```
bert/
  summarize.py    # Haiku fan-out → per-ticket records (the MAP step)
  state.py        # morning-review state file: the index + the standing brief
  fanout.py       # per-ticket draft workers (inject brief + policies), collect results
  render.py       # summary → visual artifact (HTML) for glanceability
  prompts/bert_system_prompt.txt   # the foreman persona + loop instructions
```

- **`summarize.py`** — fetches open conversations (reuse the Help Scout OAuth client from `triage_tickets.py: get_access_token` / `BASE_URL`), fans out one Haiku call per ticket, each returning a structured record: `{ conversation_id, customer, category, one_line, urgent, is_new, matches_known_bug }`. Embarrassingly parallel. Model: `claude-haiku-4-5`.
- **`state.py`** — reads/writes a single JSON state file per morning (e.g. `data/morning_review/<date>.json`) holding: the list of per-ticket records (the index), the standing brief (accumulated bug-truths / company context / preferences), and per-ticket status (summarized → hydrated? → drafted? → confidence → posted?). Makes re-running the summary near-free and drill-downs instant once hydrated.
- **`fanout.py`** — the drafting fan-out. For each ticket: build `[standing brief] + [hydrated ticket context] + [policies]`, call the shared draft function (see Component C), collect `{ draft, confidence, referenced_policies, reasoning, open_question, bug_report }`. Runs concurrently with a bounded worker pool. Model: `claude-sonnet-5` (the shared default).
- **`render.py`** — turns the reduced summary into an HTML artifact: volume vs. normal, what's new, what's common, urgent flags, color-coded, one row per ticket with its `conversation_id`. Glanceable status without building an app.

### Component B: `.claude/skills/bert-*` (net-new instructions)

Repo-local skills the session loads. These are *instructions that call into `bert/` and the shared modules* — they hold no policy or drafting logic themselves.

```
.claude/skills/
  bert-morning-review/SKILL.md     # the top-level loop; orchestrates the others
  bert-summarize-mailbox/SKILL.md  # invoke bert/summarize.py, render status
  bert-hydrate-ticket/SKILL.md     # pull one ticket's full context into the session
  bert-lookup/SKILL.md             # code / Linear research dive (wraps research_agent)
  bert-draft-all/SKILL.md          # invoke bert/fanout.py with the current standing brief
  bert-resolve/SKILL.md            # walk the low-confidence/flagged set; revise; capture-knowledge
  bert-post/SKILL.md               # post approved drafts via the shared post path
```

`bert-morning-review/SKILL.md` is the entry point ("open Bert") and drives the loop; the others are the callable steps. The standing brief is passed explicitly into `bert-draft-all` so Cassidy's feedback propagates to every worker.

### Component C: Shared seams extracted from `orchestrator.py` (surgical, behavior-preserving)

Some logic Bert needs is currently buried inside `orchestrator.py: process_ticket_sync()` (the one-ticket-at-a-time flow). Extract these as thin, importable functions with **identical behavior**, so both the orchestrator and `bert/` call the same code:

- `hydrate_ticket(conversation_id) -> ticket_context` — fetch conversation + threads (`_fetch_conversation_threads`, `detect_reply_mode`), Maven account, Stripe enrichment. This is the "gather everything about one ticket" step, factored out of `process_ticket_sync`.
- `draft_one(ticket_context, brief, policies) -> draft_result` — the Claude draft call (`_call_claude_draft_with_action_retry` + `_build_dynamic_user_message`) plus JSON parse/retry, taking an explicit `brief` string that is injected into the user message alongside the ticket. `orchestrator.py` calls it with an empty/standing-config brief; Bert calls it with the accumulated standing brief.
- `post_draft(conversation_id, draft_result) -> None` — the HS reply-draft + internal note write, including `draft_registry` dedupe/supersede (already its own module).

Reuse without change: `load_policy_docs()`, `research_agent.py`, `draft_registry.py`, `notion_bridge.py`, `bug_registry.py`, `triage_tickets.get_access_token`.

The extraction refactors `process_ticket_sync` to *call* these three functions rather than inlining them — reducing duplication, not forking it. The webhook path's behavior must be byte-for-byte unchanged (verified by re-running the eval harness before/after).

---

## Model tiers

| Step | Model | Why |
|---|---|---|
| summarize-mailbox (MAP) | `claude-haiku-4-5` | bulk, cheap, parallel; extraction only |
| mailbox-status (REDUCE) + discussion | session model (Opus/Sonnet) | reasoning + conversation |
| draft-all workers | `claude-sonnet-5` | quality drafting (shared default) |
| lookup / research | per `research_agent.py` | unchanged |

---

## Knowledge capture (the compounding loop)

`capture-knowledge` inside `bert-resolve`: when discussion establishes a new truth (a bug status, a policy stance), Bert writes it back to the relevant `policies/*.md` file and, per the CLAUDE.md hard requirement, syncs the corresponding Notion page (Support Policy Docs, ID `356cffdf-527f-808d-a4fc-f7d05499523f`). It also updates the Bert Gap Queue row (Status → Answered/Incorporated) via `notion_bridge.py`. The point: a question answered in the morning review stops being a question tomorrow.

---

## Error handling

- **Enrichment / summary steps fail soft:** a Haiku summary call that errors marks that ticket "summary unavailable" in the index and continues; the mailbox review is never blocked by one bad ticket.
- **Fan-out is isolated:** one draft worker throwing drops that ticket to a "draft failed — review manually" state; the other N-1 drafts are unaffected.
- **Post step fails hard per-ticket** (as today) but does not abort the batch; failures are reported back for retry.
- All steps follow the existing logging pattern (per-step success/failure, latency, tokens).

---

## Build order

1. **Phase 1 — Shared seams (Component C).** Extract `hydrate_ticket` / `draft_one` / `post_draft` from `process_ticket_sync`; refactor the orchestrator to call them; prove the webhook path unchanged via an eval-run before/after diff.
2. **Phase 2 — Summary + state (`bert/summarize.py`, `bert/state.py`, `bert/render.py`).** Standalone: `python -m bert.summarize` produces the index + artifact for a mailbox. No drafting yet.
3. **Phase 3 — Draft fan-out (`bert/fanout.py`).** Wire the standing brief → workers → results, calling `draft_one`.
4. **Phase 4 — Skills (Component B).** Author the `.claude/skills/bert-*` set that drives the loop; the morning review becomes runnable end-to-end from a session.
5. **Phase 5 — Knowledge capture + polish.** `capture-knowledge` write-back + gap-queue sync; artifact refinements from living in it.

Each phase is independently useful and leaves the production pipeline intact.

---

## Out of scope (deferred)

- **A standalone app/UI.** Session-first by decision (2026-07-06). Friction discovered living in the session becomes the spec for a UI later, if teammate access or approve/post ergonomics demand it.
- **Auto-send.** Unchanged from prior specs — everything drafts for human review; auto-send stays a future gate.
- **Changes to `triage_tickets.py`, `account_context.py`, `maven_customer_context.py`.** Imported as-is.
