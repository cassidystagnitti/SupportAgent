# Task 2 Report — Reply detection derived from threads (SUP-447)

## Summary

`process_ticket_sync` no longer trusts a manually-passed `is_reply` flag to decide whether a
ticket is a fresh conversation or an ongoing thread. It now fetches the conversation's threads
and derives reply mode itself via a new `detect_reply_mode(threads)` function, fixing the root
cause of the 22/82 tickets in the last test run that were drafted against the original message
instead of the customer's latest reply.

## TDD Evidence

### RED

Created `tests/test_reply_detection.py` with the four tests from the brief (verbatim). Ran before
implementing `detect_reply_mode`:

```
$ python3 -m pytest tests/test_reply_detection.py -v
ImportError while importing test module '.../tests/test_reply_detection.py'
E   ImportError: cannot import name 'detect_reply_mode' from 'orchestrator'
```

### GREEN

Implemented `detect_reply_mode` in `orchestrator.py` (verbatim from the brief):

```
$ python3 -m pytest tests/test_reply_detection.py -v
tests/test_reply_detection.py::test_new_conversation_is_not_reply PASSED
tests/test_reply_detection.py::test_agent_reply_makes_it_reply_mode PASSED
tests/test_reply_detection.py::test_draft_agent_message_does_not_count PASSED
tests/test_reply_detection.py::test_notes_do_not_count PASSED
4 passed in 0.29s
```

## Implementation

### 1. `detect_reply_mode(threads: list) -> bool` (`orchestrator.py`)

Verbatim from the brief — True iff any thread has `type == "message"` and `state == "published"`.

### 2. Thread fetching (`orchestrator.py`)

Checked `fetch_conversation` (in `triage_tickets.py`) first — it's a plain
`GET /conversations/{id}` and does **not** embed `_embedded.threads`. `get_conversation_history`
and `get_conversation_text` each independently call a private `_fetch_all_threads` helper that
paginates `GET /conversations/{id}/threads`.

Rather than depend on `triage_tickets._fetch_all_threads` (underscore-prefixed, not part of the
brief's exported surface), I added `_fetch_conversation_threads(session, convo, conversation_id)`
in `orchestrator.py`:
- Reuses `convo["_embedded"]["threads"]` if `fetch_conversation` ever returns it embedded
  (future-proofing / avoids a redundant call if the API response shape changes).
- Otherwise fetches via `api_get` (imported from `triage_tickets`, already handles 429 retry),
  paginating `GET {BASE_URL}/conversations/{id}/threads` the same way
  `triage_tickets._fetch_all_threads` does.

### 3. Wiring into `process_ticket_sync`

- Moved the HELPSCOUT/ANTHROPIC env checks, token fetch, session creation, and
  `fetch_conversation` call to happen **before** the triage-skip decision (previously triage ran
  first). This reordering is safe: `run_triage` re-fetches everything it needs internally by
  conversation ID and doesn't depend on anything computed later in `process_ticket_sync`.
- Added `threads = _fetch_conversation_threads(...)` and `reply_mode = detect_reply_mode(threads)`
  right after `fetch_conversation`.
- `out["reply_mode"] = reply_mode` is recorded (also initialized to `False` in the `out` dict
  skeleton for shape consistency with other telemetry fields).
- Replaced both remaining `is_reply` usages inside the function body with `reply_mode`:
  - The triage-skip check: `if reply_mode or skip_triage: ... skip triage`
  - The history-vs-text branch: `if reply_mode: get_conversation_history(...) else: get_conversation_text(...)`
- The `is_reply` kwarg stays on the signature for backward compatibility. If a caller passes
  `is_reply=True`, a deprecation warning is logged and the value is otherwise ignored (real mode
  is always derived from threads):
  ```python
  if is_reply:
      log.warning(
          "process_ticket_sync(is_reply=True) is deprecated — reply mode is now derived "
          "from conversation threads. The passed value is ignored."
      )
  ```
- Note: a *different*, pre-existing local variable named `is_reply` inside
  `_build_dynamic_user_message` (derived from `bool(conversation_history)`) was left untouched —
  it's local to that helper and unrelated to the kwarg being deprecated.

### 4. Prompt framing (Step 3)

Added a module-level constant `REPLY_MODE_PROMPT_PREFIX` with the exact text from the brief, and
prepend it to the **user message** (not the system prompt) when `reply_mode` is true:

```python
if reply_mode:
    dynamic_message = f"{REPLY_MODE_PROMPT_PREFIX}\n\n{dynamic_message}"
```

**Discrepancy note:** the brief's file list says to modify `prompts/draft_system_prompt.txt`, but
Step 3's instructions explicitly say to prepend the framing to the *user* message, not the system
prompt. I followed the explicit Step 3 mechanism (Python-side prepend to the dynamic user
message) and left `prompts/draft_system_prompt.txt` unmodified, since editing it would contradict
Step 3. Flagging this for awareness in case the file-list line was intentional and I'm missing
context.

### 5. Webhook (Step 4)

Inspected `webhook_server.py`. The event whitelist (`TRIAGE_EVENTS`) **already contained**
`"convo.customer.reply.created"` alongside `"convo.created"`, both routed through the same
`/helpscout/webhook` handler to `_run_pipeline_sync` → `process_ticket_sync`. So the whitelisting
part of Step 4 was already done prior to this task.

What I changed:
- Extracted the event name into a module-level constant `CUSTOMER_REPLY_EVENT =
  "convo.customer.reply.created"` with a comment citing where to confirm it (Help Scout: Manage →
  Apps → Webhooks → available events → "Customer Reply Created"). I could not reach Help Scout's
  docs from this environment to independently verify the exact string against live API docs; the
  value already present in the codebase (and referenced in `CLAUDE.md`/prior commits) is
  `convo.customer.reply.created`, which I kept as-is and just gave a name + comment per the task's
  "add as a module-level constant" instruction for the ambiguous-naming case.
- Removed the webhook's `is_reply` computation and no longer passes `is_reply=` into
  `_run_pipeline_sync` / `process_ticket_sync`. Since `process_ticket_sync` now derives reply mode
  itself from live thread state (more reliable than inferring it from which webhook event fired —
  e.g. Help Scout could fire `convo.customer.reply.created` for the first message in some edge
  cases, or an agent could reply between the webhook firing and the pipeline running), passing a
  redundant/stale `is_reply` guess would only trigger the new deprecation warning on every
  customer-reply webhook for no benefit. Updated `_run_pipeline_sync`'s signature accordingly and
  added a comment explaining why.

## Files changed

- `orchestrator.py` — added `detect_reply_mode`, `_fetch_conversation_threads`,
  `REPLY_MODE_PROMPT_PREFIX`; reordered/rewired `process_ticket_sync` to derive and use
  `reply_mode`; added deprecation warning for `is_reply=True`; imported `api_get` from
  `triage_tickets`.
- `webhook_server.py` — named the customer-reply event as `CUSTOMER_REPLY_EVENT` constant with
  clarifying comment; stopped passing `is_reply` through to the pipeline.
- `tests/test_reply_detection.py` — new, four tests verbatim from the brief.
- `prompts/draft_system_prompt.txt` — **not modified** (see discrepancy note above).

## Verification

Full suite once before commit:

```
$ python3 -m pytest tests/ -v
...
18 passed, 1 failed in ~0.8-1.7s
FAILED tests/test_maven_orchestrator.py::test_maven_client_raises_when_env_missing
```

That failure is pre-existing (confirmed present on a clean run before any of my changes — same
failure, same message) and explicitly called out as out-of-scope in the task instructions.
18 passing includes all 15 pre-existing passing tests plus the 4 new `test_reply_detection.py`
tests (14 baseline passed + 4 new = 18; baseline had 14 passed / 1 failed out of 15 total).

Additional manual verification (not part of the automated suite, but run to sanity-check the
non-pure-function wiring that unit tests can't easily cover without a live Help Scout account):
- `_fetch_conversation_threads` reuses `_embedded.threads` when present without making an HTTP
  call, confirmed via a fake session + convo dict.
- `_fetch_conversation_threads` falls back to `api_get(session, f"{BASE_URL}/conversations/{id}/threads", ...)`
  when threads aren't embedded, confirmed by monkeypatching `orchestrator.api_get` and checking
  the URL and pagination params passed.
- Confirmed `process_ticket_sync(..., is_reply=True)` logs the deprecation warning
  (`"is_reply=True) is deprecated"` substring found in captured log output) before failing fast on
  missing `HELPSCOUT_APP_ID`/`HELPSCOUT_APP_SECRET` (used a real call path up to the env-var
  guard, since no live Help Scout/Anthropic credentials are available in this environment).
- `python3 -m py_compile orchestrator.py webhook_server.py` — both compile cleanly.

## Self-review

- Confirmed `account_context.py` and `maven_customer_context.py` were not touched.
- Confirmed no changes to `triage_tickets.py` — only added an existing public function
  (`api_get`) to the import list in `orchestrator.py`.
- Confirmed `is_reply` kwarg remains on `process_ticket_sync`'s signature for compatibility;
  existing callers (`fix_reply_drafts.py`, which passes `is_reply=True`) continue to work — they
  will now get a deprecation warning logged and correctly-derived `reply_mode` behavior instead of
  their manual flag, which is the intended fix for the underlying bug (manual flags were wrong for
  22/82 tickets).
- `batch_maven_drafts.py`, `test_run.py`, `sidebar_server.py` call `process_ticket_sync` without
  `is_reply` at all — unaffected, and they now benefit from automatic reply detection for free.
- Did not modify `prompts/draft_system_prompt.txt` — see discrepancy note under Step 3 above.
- The reordering of triage-skip-check vs. env-var/token/convo fetch inside `process_ticket_sync`
  is a behavior-preserving refactor for the non-reply-mode path: previously, if `HELPSCOUT_APP_ID`
  was missing, triage would still be *attempted* first (and likely `sys.exit`/warn) before hitting
  the `RuntimeError`. Now the env check happens first. This is arguably an improvement (fail fast
  before attempting triage with bad config) but is a subtle behavior change worth flagging.

## Concerns / open questions

1. **Discrepancy between brief's file list and Step 3 instructions** regarding
   `prompts/draft_system_prompt.txt` (see above) — resolved in favor of the explicit Step 3
   mechanism (Python-side user-message prepend), but flagging in case the other reading was
   intended.
2. **Event name for Step 4** could not be independently verified against live Help Scout API
   docs from this sandboxed environment (no network access to Help Scout docs). Used the value
   already present and exercised in this codebase (`convo.customer.reply.created`, also referenced
   in `CLAUDE.md` history and `fix_reply_drafts.py`'s reason for existing). Named it as a
   module-level constant (`CUSTOMER_REPLY_EVENT`) with a comment per the task instructions for the
   ambiguous-naming case.
3. **Minor behavior change**: the env-var/config validation for Help Scout/Anthropic credentials
   now runs before the triage-skip decision (previously triage could attempt to run first even
   with bad config). This only affects the failure-path ordering, not the happy path.
4. No test exists for `_fetch_conversation_threads` itself (only manual verification, since it
   wasn't part of the brief's Step 1 test list) — the brief's `detect_reply_mode` unit tests don't
   exercise the HTTP-fetching code paths. If desired, a follow-up could add
   `tests/test_conversation_threads.py` with mocked `api_get`.
