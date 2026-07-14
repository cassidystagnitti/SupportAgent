# Help Scout Sidebar Chat — Design Spec

**Date:** 2026-07-14
**Status:** Approved for implementation
**Branch:** bert-v1-buildout

## Goal

Turn the existing Help Scout sidebar app (`sidebar_server.py`, deployed on Render) into a
per-ticket **chat interface with Bert**. From the sidebar of any conversation, a support
agent can:

1. **Chat** about the ticket — Bert answers with full hydrated context (thread, account,
   Stripe, policies) and can explain the reasoning behind the current draft.
2. **Revise or create the Help Scout draft** — Bert edits the draft in place (or creates
   one if none exists) via a tool call; the agent refreshes the reply editor to see it.
3. **Propose knowledge updates** — Bert proposes an edit to a `policies/*.md` doc as a
   diff card; on the agent's **Confirm** click the edit is applied to the live policy
   copy, committed to the GitHub repo, and synced to Notion.
4. **Send & close** — a button publishes the current draft as the reply and closes the
   conversation, attributed to the Support Automations agent user account.

Simultaneously, sunset the legacy entry points: delete `webhook_server.py` (webhook
auto-trigger) and the Maven draft engine. After this change the system has exactly two
interfaces: **Bert via Claude Chat** (local morning-review skills) and **this sidebar
chat app**.

## Non-goals

- Auto-send without a human click (unchanged — every send is an explicit agent action).
- Per-agent permissions. Anyone who can open the sidebar can chat, confirm policy
  updates, and send. The `SIDEBAR_SECRET` gate keeps non-Help-Scout callers out.
- Persisting chat history across server restarts. Context rehydrates on demand; the
  durable artifacts (drafts, commits, Notion pages, sent replies) all live elsewhere.
- Help Scout `openSidePanel()` roomier UI — possible v1.5 UX upgrade, not in scope.
- RAG / retrieval. Policies keep loading wholesale, as everywhere else in the pipeline.

## Decisions already made (brainstorm outcomes)

| Question | Decision |
|---|---|
| Chat context | Rehydrate on demand via `bert.pipeline.hydrate_ticket()` — no pipeline changes, always fresh |
| v1 scope | Chat + draft update + knowledge updates + send-and-close, all in v1 |
| Audience | Whole team; all can confirm policy updates |
| Knowledge sink | Git commit to main via GitHub API + immediate live apply + Notion sync |
| Sunset scope | Full sweep: `webhook_server.py`, Maven engine, sidebar trigger buttons all removed |
| Architecture | Extend `sidebar_server.py` (approach A); chat logic in a new `sidebar_chat.py` module |

## Architecture

```
Help Scout conversation view
  └─ sidebar iframe (static/sidebar.html, vanilla JS, postMessage handshake — unchanged)
       │  polls GET /chat/messages/{cid}?after=N
       │  POST /chat/message | /chat/confirm-policy | /chat/dismiss-policy | /chat/send
       ▼
sidebar_server.py (FastAPI, Render, SIDEBAR_SECRET-gated writes)
  ├─ sidebar_chat.py      — session store + Anthropic tool loop (the chat brain)
  │    ├─ bert/pipeline.hydrate_ticket()        (context, read-only)
  │    ├─ bert/pipeline.find_draft_threads()    (live draft discovery)
  │    ├─ bert/pipeline.update_draft()          (PATCH draft text in place)
  │    └─ draft creation w/ agent-user attribution (new; registry-recorded)
  └─ policy_updater.py    — confirmed knowledge updates
       ├─ atomic live apply to policies/*.md
       ├─ GitHub Contents API commit (path-restricted, "[skip render]")
       └─ Notion sync (reuse scripts/sync_new_policy_docs.py machinery)
```

## Components

### 1. `sidebar_chat.py` — chat sessions + tool loop

**Session store.** In-memory dict keyed by `str(conversation_id)`, guarded by a lock,
LRU-capped at 200 entries (mirrors the existing `_status` pattern). A session holds:

- `api_messages` — the Anthropic-format message list (user/assistant turns incl. tool use)
- `ui_messages` — append-only list of `{seq, kind, text|payload, ts}` the frontend renders;
  `kind` ∈ `user | bert | event | proposal | error`
- `ctx` — the hydrated ticket context (from `hydrate_ticket`)
- `draft_thread_id` — live draft thread id (from `find_draft_threads` / registry / created)
- `proposals` — `{proposal_id: {file, edit_type, target_text, new_text, rationale, diff,
  status: pending|confirmed|dismissed|failed}}`
- `busy` — one turn at a time; a message posted while busy is rejected with 409 (the UI
  disables the input while busy anyway)

**Hydration** (first message, or after restart): build an HS `requests.Session` via
`orchestrator.get_access_token()`, call `bert.pipeline.hydrate_ticket(session, cid)`,
resolve the draft thread (registry first, then `find_draft_threads` live — live wins),
and pull the current draft text so Bert knows what it's revising.

**Tool loop.** Direct Anthropic Messages API (`claude-sonnet-5`), system prompt +
policies sent as cache-controlled blocks (same caching approach as the orchestrator).
Max ~8 tool-use iterations per turn as a runaway guard. Two tools:

- `update_draft(html)` — HTML paragraphs, same `<p>` convention as `draft_reply`.
  If `draft_thread_id` exists → `bert.pipeline.update_draft()`; else create a draft via
  `POST /conversations/{cid}/reply` with `draft: true` **and `user: HELPSCOUT_AGENT_USER_ID`**
  (new — attribution, see §4), record in `draft_registry`. Emits a `event` ui-message
  ("Draft updated — refresh the reply editor") and returns success to the model.
- `propose_policy_update(policy_file, edit_type, target_text, new_text, rationale)` —
  **never applies anything.** Validates `policy_file` is an existing `policies/*.md`
  basename; `edit_type` ∈ `replace | append`. For `replace`, `target_text` must occur
  exactly once in the current live file (checked at proposal time AND again at confirm
  time, so upstream drift fails loudly instead of mis-applying); `new_text` replaces it.
  For `append`, `target_text` is ignored and `new_text` is appended to the end of the
  file as a new block (leading newline normalized). Computes a unified diff
  for the card, stores the proposal, emits a `proposal` ui-message, and tells the model
  "proposal registered — awaiting human confirmation" so Bert doesn't claim it's done.

**Chat system prompt** — new file `prompts/sidebar_chat_system_prompt.txt` (prompts live
in `prompts/`, not Python). Contents: Bert persona and voice (casual, human, no AI
tells), the hydrated-context blocks, tool guidance (draft edits go through
`update_draft`, never pasted into chat; knowledge changes only via
`propose_policy_update`; keep in-chat answers short — the agent is reading in a 350px
sidebar), and the reply-mode nuance from the draft prompt.

### 2. `policy_updater.py` — confirmed knowledge updates

On **Confirm** of a proposal, in order:

1. **Re-validate + live apply.** Re-check `target_text` uniqueness against the current
   file; apply the edit; atomic write (tmp file + `os.replace`, same as the registries).
   The very next draft/chat anywhere on the box uses the new policy immediately.
2. **GitHub commit.** Contents API `PUT /repos/{GITHUB_REPO}/contents/policies/{file}`
   on `GITHUB_BRANCH` (default `main`): GET current sha → PUT new content + sha.
   Path is hard-restricted to `policies/*.md` — the endpoint refuses anything else.
   Commit message: first line `policy: <file> — <short rationale>`, body includes the
   full rationale, the HS conversation URL, and **`[skip render]`** so the commit does
   not trigger a Render redeploy (the live copy is already updated; a redeploy would
   kill every active chat session for nothing). On sha conflict (409/422): refetch,
   re-validate `target_text` against the fresh remote content, retry once, then fail.
3. **Notion sync.** Reuse the `sync_doc()` machinery from
   `scripts/sync_new_policy_docs.py` (refactored to be importable — move the reusable
   functions into `policy_updater.py` or make `scripts/` importable; CLI stays working).
   Syncs the child page under Support Policy Docs (`356cffdf-527f-808d-a4fc-f7d05499523f`).
   **Fail-soft**: on missing `NOTION_TOKEN` or API error, log + emit a visible warning
   event in the chat ("Committed to repo, but Notion sync failed — sync manually").

Failure semantics: step 1 failure → proposal marked `failed`, error card in chat,
nothing committed. Step 2 failure → **live copy is rolled back** (restore prior
content), proposal stays `pending` so the agent can retry. Step 3 failure → warn only
(matches the repo's fail-soft-on-enrichment convention).

Dismiss simply marks the proposal `dismissed` and greys out the card.

### 3. New/changed HTTP endpoints (`sidebar_server.py`)

All POSTs carry `{secret}` verified with `hmac.compare_digest` against `SIDEBAR_SECRET`
(existing pattern). All are keyed by numeric `conversation_id`.

| Endpoint | Behavior |
|---|---|
| `POST /chat/message` | `{conversation_id, customer_email?, text, secret}` → 202; spawns a daemon thread running the tool loop; 409 if that conversation's session is busy |
| `GET /chat/messages/{cid}?after=N` | `{messages: [ui_messages with seq > N], busy, draft: {exists, thread_id, updated_at}}` — poll target |
| `POST /chat/confirm-policy` | `{conversation_id, proposal_id, secret}` → runs `policy_updater` flow synchronously (a few seconds), returns outcome; result also appended as ui-message |
| `POST /chat/dismiss-policy` | marks proposal dismissed |
| `POST /chat/send` | guards, then publish draft + close conversation (§4); returns outcome |
| `GET /sidebar`, `POST /sidebar` | unchanged handshake, but now serve `static/sidebar.html` (template-injected CID/EMAIL/SECRET) |
| `GET /health` | unchanged |

**Removed:** `POST /trigger-draft`, `GET /trigger-status/{cid}`, the `engine` concept,
and the `maven_orchestrator` import.

### 4. Send & close

Flow on `POST /chat/send`:

1. **Guards** (fail with a precise message): a live draft thread exists
   (`find_draft_threads` — checked live, not from cache); conversation status is not
   already `closed` (`conversation_status()`).
2. **Publish the draft:** `PATCH {BASE_URL}/conversations/{cid}/threads/{tid}/schedule`
   with `{"op": "replace", "path": "/state", "value": "published"}` — this converts the
   draft into a sent reply (documented Help Scout "Publish Thread Schedule" endpoint).
3. **Close:** `PATCH {BASE_URL}/conversations/{cid}` with
   `{"op": "replace", "path": "/status", "value": "closed"}`.
4. Partial failure is reported precisely: if publish succeeded but close failed, the UI
   says exactly that and offers a retry that only re-runs the close step.

**Attribution — the Support Automations agent account.** New env var
`HELPSCOUT_AGENT_USER_ID` (falls back to `HELPSCOUT_NOTE_USER_ID`). Every draft the
*chat* creates includes `"user": <that id>` so the published reply is sent as the
Support Automations agent, and internal notes already use it. Acceptance requires a
live check that a chat-created draft, once published, shows the agent account as the
sender. Drafts created earlier by the morning-review flow (`post_draft`, which sends no
`user`) are attributed to the OAuth app's owning user — if live verification shows
that's wrong for send, `bert.pipeline.post_draft` gains the same `user` field (small,
backwards-compatible change).

UI: the Send button shows a two-step inline confirm ("Send this reply and close the
conversation? **Send** / Cancel") — no browser `confirm()` dialogs.

### 5. Frontend — `static/sidebar.html`

The inline `_SIDEBAR_HTML` string moves to a static file (it's about to triple in size);
`_render_sidebar` reads it once at startup and injects `__CID__/__EMAIL__/__SECRET__`
exactly as today. The **postMessage context handshake is preserved verbatim** — it's
proven against both `secure.helpscout.net` and `hs-app.*.hsenv.io` origins.

Layout (top → bottom), vanilla JS, matching the existing visual style:

- **Draft status card** — "Draft on this ticket: yes/no · last updated HH:MM" plus the
  **Send & close** button (hidden when no draft).
- **Chat pane** — scrollable message list. `user` right-aligned, `bert` left, `event`
  as small grey chips, `error` as red chips, `proposal` as a diff card (monospace,
  green/red +/- lines, rationale text, **Confirm** / **Dismiss** buttons; after action the
  card shows its final state and the buttons disappear).
- **Input row** — textarea + send; disabled while `busy`.

Polling: ~1.5s while `busy` or a request is in flight, backing off to 10s idle. Same
`fetch` + poll pattern as the current file, no build step, no framework.

### 6. Sunset sweep

Deletions:

- `webhook_server.py` (webhook auto-trigger — sunset)
- `maven_orchestrator.py`, `tests/test_maven_orchestrator.py`
- `batch_maven_drafts.py` (verify Maven-only at implementation; delete if so)
- Maven references in `test_run.py` and `sidebar_server.py` (buttons, `engine` param,
  `process_maven_ticket_sync` import)
- `mavenagi` from `requirements.txt` if nothing else imports it

CLAUDE.md updates (same commit): repo-map rows (remove `webhook_server.py`,
`maven_orchestrator.py`; add `sidebar_server.py`, `sidebar_chat.py`,
`policy_updater.py`, `static/`), pipeline-flow section rewritten around the two
interfaces, env-var section (remove MavenAGI's `MAVEN_ORG_ID/MAVEN_AGENT_ID/
MAVEN_APP_ID/MAVEN_APP_SECRET`; **keep** the Happier Maven API vars
`MAVEN_API_BASE_URL`/`MAVEN_API_KEY` — different system; add `SIDEBAR_SECRET`,
`HELPSCOUT_AGENT_USER_ID`, `GITHUB_TOKEN`, `GITHUB_REPO`, `GITHUB_BRANCH`).

Manual steps (Cassidy, post-deploy):

1. Deregister/disable the Help Scout webhook (HS admin → Apps → Webhooks).
2. Set on Render: `GITHUB_TOKEN` (fine-grained PAT, contents:write on this repo only),
   `NOTION_TOKEN` (currently unset — Notion sync warns until then),
   `HELPSCOUT_AGENT_USER_ID` (Support Automations user id).

### 7. Environment variables (new/changed)

```bash
SIDEBAR_SECRET             # existing — gates all sidebar write endpoints
HELPSCOUT_AGENT_USER_ID    # NEW — HS user id for chat-created drafts & attribution;
                           # falls back to HELPSCOUT_NOTE_USER_ID
GITHUB_TOKEN               # NEW — fine-grained PAT, contents:write, this repo only
GITHUB_REPO                # NEW — default "cassidystagnitti/SupportAgent"
GITHUB_BRANCH              # NEW — default "main"
NOTION_TOKEN               # existing, still unset — policy Notion sync fails soft until set
# REMOVED: MAVEN_ORG_ID, MAVEN_AGENT_ID, MAVEN_APP_ID, MAVEN_APP_SECRET (MavenAGI engine)
```

### 8. Error handling summary

| Failure | Behavior |
|---|---|
| Bad/missing secret | 401, nothing runs |
| Hydration failure (HS/API down) | error ui-message; session not created; next message retries |
| Tool-loop exception | error ui-message with truncated detail; `busy` cleared; session intact |
| `update_draft` PATCH fails | tool returns failure to the model (it apologizes + suggests retry); error chip |
| Proposal `target_text` drifted | confirm fails loudly with "policy changed since proposal — re-propose" |
| GitHub commit fails | live copy rolled back; proposal stays pending; error card with retry |
| Notion sync fails | warn-only event; commit stands |
| Publish OK, close fails | precise message + close-only retry |
| Server restart mid-chat | history gone; UI starts fresh; drafts/commits/sent replies persist |

### 9. Testing

Unit (pytest, existing style — mock `requests` sessions and the Anthropic client):

- `tests/test_sidebar_chat.py` — store LRU + busy semantics; hydration wiring; tool loop
  dispatch (update existing draft vs. create-with-user; proposal registration; runaway
  iteration cap); model told "awaiting confirmation" (not "done").
- `tests/test_policy_updater.py` — replace/append apply; uniqueness validation;
  atomic write; GitHub payload (path restriction, sha flow, `[skip render]`, conflict
  retry); rollback on commit failure; Notion fail-soft.
- `tests/test_sidebar_server.py` (extend existing `test_sidebar.py`) — endpoint auth,
  409 while busy, send guards (no draft / already closed / happy path ordering:
  publish **then** close), partial-failure reporting, static HTML serving + injection.
- Sunset: test suite passes with the deleted modules gone (no dangling imports).

Live verification (acceptance):

1. Open a real test conversation → sidebar chat loads, context correct.
2. "Revise the draft to mention X" → draft thread updates in HS reply editor.
3. Ticket with no draft → "draft a reply" → draft appears, registry recorded.
4. Bert proposes a policy edit → Confirm → `policies/*.md` commit on GitHub with
   `[skip render]`, live file changed; Notion warns (token unset) or syncs.
5. **Send & close** → reply is sent, conversation closes, and the sender shown in
   Help Scout is the Support Automations agent account.
6. `webhook_server.py` gone; Render service healthy on the new code.

## Out-of-scope follow-ups (noted, not built)

- `openSidePanel()` roomy chat surface (v1.5)
- Streaming responses (SSE) instead of polling
- Chat-visible action_executor integration (coupon/cancellation) once Stripe writes are approved
