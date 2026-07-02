# Bert v1 Build-Out Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement all Bert sub-issues (SUP-447–449, 451–462; NOT SUP-450) per the spec at `docs/superpowers/specs/2026-07-02-bert-v1-buildout-design.md`.

**Architecture:** Extend the existing single-call draft pipeline with: derived reply detection, a richer draft JSON schema, Notion gap-queue/action-log bridges, a conditional two-pass research agent, a bug-candidate registry with Linear auto-filing, an action-execution scaffold, and a consolidated eval harness. All enrichment fails soft; core drafting fails hard.

**Tech Stack:** Python 3.9 (`from __future__ import annotations` everywhere), requests, anthropic SDK, pytest (tests in `SupportAgent/tests/`), Notion REST API (`NOTION_TOKEN`), Linear GraphQL (`LINEAR_API_KEY`), Help Scout Mailbox API v2.

## Global Constraints

- Working dir for all commands: `/Users/cassidystagnitti/code/code-happierMeditation/SupportAgent` (its own git repo — commit after each task).
- Python 3.9 runtime: no `match`, no stdlib generics in runtime positions without `__future__` annotations import.
- Policy knowledge lives in `policies/*.md`, never in Python or prompts. Prompts live in `prompts/*.txt`.
- Every policy doc change must ALSO sync to the Support Policy Docs Notion page (ID `356cffdf-527f-808d-a4fc-f7d05499523f`).
- Enrichment steps (Notion, Linear, research, registry) fail soft: `log.exception` + continue. Core steps (draft, HS draft creation) fail hard.
- Default draft model: `claude-sonnet-5`; `CLAUDE_DRAFT_MODEL` env var overrides.
- Never modify `account_context.py` / `maven_customer_context.py`.
- Run tests with: `python3 -m pytest tests/ -v`.

---

### Task 1: `claude_utils.extract_text()` + ThinkingBlock fixes (SUP-460)

**Files:**
- Create: `claude_utils.py`, `tests/test_claude_utils.py`
- Modify: `product_prioritization.py` (line ~155), plus any other `content[0].text` sites (`grep -rn "content\[0\].text" *.py`)

**Interfaces:**
- Produces: `extract_text(message) -> str` — first `type == "text"` block's text, else `""`.

- [ ] **Step 1: Failing test**

```python
# tests/test_claude_utils.py
from types import SimpleNamespace
from claude_utils import extract_text

def _msg(blocks):
    return SimpleNamespace(content=blocks)

def test_extract_text_skips_thinking_block():
    blocks = [SimpleNamespace(type="thinking", thinking="hmm"),
              SimpleNamespace(type="text", text="hello")]
    assert extract_text(_msg(blocks)) == "hello"

def test_extract_text_plain():
    assert extract_text(_msg([SimpleNamespace(type="text", text="x")])) == "x"

def test_extract_text_no_text_block():
    assert extract_text(_msg([SimpleNamespace(type="thinking", thinking="only")])) == ""
```

Run: `python3 -m pytest tests/test_claude_utils.py -v` → FAIL (no module).

- [ ] **Step 2: Implement**

```python
# claude_utils.py
"""Shared helpers for Anthropic API responses."""
from __future__ import annotations


def extract_text(message) -> str:
    """Return the first text block's text; thinking blocks are skipped."""
    for block in getattr(message, "content", []) or []:
        if getattr(block, "type", None) == "text":
            return block.text
    return ""
```

- [ ] **Step 3: Tests pass**; then replace every `message.content[0].text` (or equivalent first-block assumption) in `product_prioritization.py` and any other module found by grep with `extract_text(message)`. Do NOT touch `account_context.py`/`maven_customer_context.py`.
- [ ] **Step 4: Verify** `grep -rn "content\[0\].text" *.py` returns nothing. Commit: `fix: tolerate ThinkingBlock in Claude responses (SUP-460)`.

### Task 2: Reply detection derived from threads (SUP-447)

**Files:**
- Modify: `orchestrator.py` (`process_ticket_sync`), `webhook_server.py`, `prompts/draft_system_prompt.txt`
- Test: `tests/test_reply_detection.py`

**Interfaces:**
- Produces: `detect_reply_mode(threads: list[dict]) -> bool` in `orchestrator.py` — True iff any published agent message thread exists.
- `process_ticket_sync` keeps its `is_reply` kwarg for compat but derives the real value; log a deprecation warning if caller passes `is_reply=True`.

- [ ] **Step 1: Failing test**

```python
# tests/test_reply_detection.py
from orchestrator import detect_reply_mode

def test_new_conversation_is_not_reply():
    threads = [{"type": "customer", "state": "published"}]
    assert detect_reply_mode(threads) is False

def test_agent_reply_makes_it_reply_mode():
    threads = [{"type": "customer", "state": "published"},
               {"type": "message", "state": "published"},
               {"type": "customer", "state": "published"}]
    assert detect_reply_mode(threads) is True

def test_draft_agent_message_does_not_count():
    threads = [{"type": "customer", "state": "published"},
               {"type": "message", "state": "draft"}]
    assert detect_reply_mode(threads) is False

def test_notes_do_not_count():
    threads = [{"type": "customer", "state": "published"},
               {"type": "note", "state": "published"}]
    assert detect_reply_mode(threads) is False
```

- [ ] **Step 2: Implement**

```python
def detect_reply_mode(threads: list) -> bool:
    """True iff a support agent has already sent a published reply."""
    for t in threads or []:
        if t.get("type") == "message" and t.get("state") == "published":
            return True
    return False
```

In `process_ticket_sync`: after fetching the conversation, fetch its threads (`GET {BASE_URL}/conversations/{cid}/threads`, or reuse the embedded threads if `fetch_conversation` already embeds them), compute `reply_mode = detect_reply_mode(threads)`, and use `reply_mode` wherever `is_reply` was used (choosing `get_conversation_history` vs `get_conversation_text`). Record `out["reply_mode"] = reply_mode`.

- [ ] **Step 3: Prompt framing.** When `reply_mode`, prepend to the user message (not the system prompt): `"NOTE: This is an ongoing thread — a support agent has already replied at least once. Respond to the customer's LATEST message only; do not re-answer the original question. Full thread history follows."`
- [ ] **Step 4: Webhook.** In `webhook_server.py`, find the event whitelist and add the customer-reply event (`convo.customer.reply.created`) routing to the same handler as new conversations. Confirm the exact event name against the existing webhook code/HS docs comment in the file.
- [ ] **Step 5:** Tests pass; commit `feat: derive reply mode from conversation threads (SUP-447)`.

### Task 3: action_description reliability + action_system (SUP-448)

**Files:**
- Modify: `prompts/draft_system_prompt.txt`, `orchestrator.py`
- Test: `tests/test_action_validation.py`

**Interfaces:**
- Produces: `needs_action_retry(parsed: dict) -> bool` in `orchestrator.py`; new JSON fields `action_system` (`"stripe"|"happier_admin"|"helpscout"|"other"|null`).

- [ ] **Step 1: Prompt changes.** In the RESPONSE FORMAT JSON block add after `action_description`:

```
  "action_system": "If needs_action is true: where the action happens — one of \"stripe\", \"happier_admin\", \"helpscout\", \"other\". If false: null.",
```

In IMPORTANT RULES add:

```
- When needs_action is true, action_description is REQUIRED and must be specific and executable. Good examples:
  * "Process refund of $49.99 in Stripe for the June 28 charge on sub_ABC123"
  * "Apply the 40% renewal coupon to Stripe subscription sub_XYZ789 (customer asked to keep membership at a discount)"
  * "Restore streak to 145 days in Happier admin for user jane@example.com"
  Never leave action_description null when needs_action is true.
```

- [ ] **Step 2: Failing test**

```python
# tests/test_action_validation.py
from orchestrator import needs_action_retry

def test_action_without_description_needs_retry():
    assert needs_action_retry({"needs_action": True, "action_description": None}) is True
    assert needs_action_retry({"needs_action": True, "action_description": "  "}) is True

def test_action_with_description_ok():
    assert needs_action_retry({"needs_action": True, "action_description": "Apply coupon to sub_1"}) is False

def test_no_action_ok():
    assert needs_action_retry({"needs_action": False, "action_description": None}) is False
```

- [ ] **Step 3: Implement**

```python
def needs_action_retry(parsed: dict) -> bool:
    return bool(parsed.get("needs_action")) and not (parsed.get("action_description") or "").strip()
```

Wire into the draft-call flow next to the existing JSON retry: if `needs_action_retry(parsed)`, re-call once appending a user message: `"Your JSON set needs_action=true but action_description was null/empty. Re-send the SAME JSON with a specific, executable action_description (and action_system)."` If still empty, keep the result, set `out["action_description_missing"] = True`, log warning.

- [ ] **Step 4:** Tests pass; commit `feat: require executable action_description + action_system (SUP-448)`.

### Task 4: auto_send tag + model default (SUP-449, part SUP-459)

**Files:**
- Modify: `orchestrator.py` (tag block ~line 582, `DEFAULT_CLAUDE_MODEL` line 41), `CLAUDE.md` (API notes)
- Test: `tests/test_tags.py`

**Interfaces:**
- Produces: `compute_tags(parsed: dict) -> list[str]` — pure function used by the tag block.

- [ ] **Step 1: Failing test**

```python
# tests/test_tags.py
from orchestrator import compute_tags

def test_auto_send_high_confidence():
    t = compute_tags({"auto_sendable": True, "confidence": "high", "escalate": False})
    assert "auto_send" in t and "automated" in t

def test_no_auto_send_when_low_confidence():
    t = compute_tags({"auto_sendable": True, "confidence": "low", "escalate": False})
    assert "auto_send" not in t

def test_not_auto_sendable():
    t = compute_tags({"auto_sendable": False, "confidence": "high", "escalate": False})
    assert "auto_send" not in t and "technical" in t

def test_escalation():
    assert "escalation" in compute_tags({"auto_sendable": False, "confidence": "low", "escalate": True})
```

- [ ] **Step 2: Implement** — extract the existing inline tag logic into `compute_tags`, preserving current behavior (`escalation`, `automated`/`technical`) and adding: `if parsed.get("auto_sendable") and parsed.get("confidence") != "low": tags.append("auto_send")`. Replace the inline block with a call.
- [ ] **Step 3:** Change `DEFAULT_CLAUDE_MODEL = "claude-sonnet-5"`; update the `CLAUDE.md` "Anthropic API" note (`claude-sonnet-4-6` → `claude-sonnet-5`).
- [ ] **Step 4:** Tests pass; commit `feat: auto_send tag gated on confidence; default model sonnet-5 (SUP-449)`.

### Task 5: known-bugs.md living doc + prompt cleanup (SUP-454)

**Files:**
- Create: `policies/known-bugs.md`
- Modify: `prompts/draft_system_prompt.txt` (DELETE the `=== CURRENT COMPANY CONTEXT ===` block entirely)

- [ ] **Step 1: Write the doc** with standard policy structure. `# Known Bugs & Current Product Status` — top section explains: "This doc is the single source of truth for current bugs. Update HERE (repo + Notion) when status changes; never edit prompts." Then one `##` entry per bug with: Status / Platforms / What to tell the customer / Linear ticket / Dates. Seed all nine:
  1. Meditation pausing/freezing — FIXED July 1, 2026; ask user to update app and confirm.
  2. Milestones broken (new app) — fix in progress; acknowledge.
  3. Streaks broken/reset — investigating (T-786); acknowledge, reassure data recoverable pending investigation.
  4. Downloads/offline unavailable — see `downloads-offline.md`; coming back soon; we will notify.
  5. Do Not Disturb toggle missing/broken on Android (T-787) — investigating; no workaround; acknowledge.
  6. Intention-setting text box unresponsive (T-788) — investigating; acknowledge.
  7. Restart Course button unresponsive — reported, gathering info; ask platform/app version.
  8. Goal-setting freezes/spins on save — reported, gathering info; ask platform/app version.
  9. UI theme change/white background — intentional redesign of the new app, not a bug; no user-facing setting to change theme; acknowledge kindly, log feedback.
  Action Classification: all entries reply-only, no account action; auto-sendable when the report clearly matches a listed bug; do NOT auto-send when the ticket mixes a bug report with billing/refund demands. Saved Reply Mapping: flag as gap (none exist yet).
- [ ] **Step 2:** Remove the entire `=== CURRENT COMPANY CONTEXT (as of July 2, 2026) ===` block from `prompts/draft_system_prompt.txt`.
- [ ] **Step 3: Verify prompt loads clean** — `python3 -c "import orchestrator"` succeeds and `grep -c "CURRENT COMPANY CONTEXT" prompts/draft_system_prompt.txt` returns 0. Live draft verification of the known-bugs doc happens in Task 16 acceptance runs (no duplicate drafts created here).
- [ ] **Step 4:** Commit `feat: living known-bugs policy doc replaces hardcoded prompt context (SUP-454)`.

### Task 6: Three remaining policy docs (SUP-452, 453, 455)

**Files:**
- Create: `policies/downloads-offline.md`, `policies/check-ins-goals-intentions.md`, `policies/non-support-requests.md`

Follow the standard structure for each (read 2–3 existing docs in `policies/` first for tone/format; read `data/saved_replies.json` names for the mapping section — flag gaps where none match).

- [ ] **Step 1: downloads-offline.md.** Policy truth (locked with Cassidy): downloads temporarily unavailable in the new app; being restored; "coming back soon" — NO specific date; **we WILL notify users when it's restored** (Bert may commit to this). Previously downloaded content is inaccessible during this window; don't speculate about re-download needs. Variations: churn threat (acknowledge + notify commitment; needs_action=false but auto_sendable=false → human review); never-subscribed user asking about downloads (feature is for subscribers; explain politely). Never fabricate ETA.
- [ ] **Step 2: check-ins-goals-intentions.md.** Feature overview (check-ins, monthly practice goals, intention setting — new in the v2 app). Opt-out stance: **no setting exists to hide/disable; acknowledge + log as product feedback** (cross-ref `feedback-policy.md`). Bug reports about the feature → cross-ref `known-bugs.md` entries 6/8. Frustrated "get rid of this" tickets: empathetic acknowledgment, honest "no option today", feedback conduit, reply-only.
- [ ] **Step 3: non-support-requests.md.** Categories: podcast/guest pitch, partnership, press, influencer/collab, cold sales, spam. Standard: **polite one-paragraph decline, close conversation**. Cold sales/spam: tag + close, NO reply. Escalation trigger: major-press or significant-partner inquiries → human review, do not auto-send.
- [ ] **Step 4:** Commit `feat: policy docs for downloads, check-ins, non-support requests (SUP-452/453/455)`.

### Task 7: Sync all four new policy docs to Notion

**Files:** none (Notion side-effect) — use `push_kb_docs.py`/`pull_policy_docs.py` as reference for the Notion API pattern; write a one-off `scripts/sync_new_policy_docs.py` if no generic push-to-Notion exists.

- [ ] **Step 1:** Inspect `pull_policy_docs.py` to learn the page structure under Support Policy Docs page `356cffdf-527f-808d-a4fc-f7d05499523f`; create four child pages (title = doc title, body = markdown converted to Notion blocks — headings, paragraphs, bullets, tables as simple paragraphs are acceptable v1).
- [ ] **Step 2:** Run it; verify pages exist via the Notion API (list child pages). Commit the script: `chore: sync new policy docs to Notion (SUP-452-455)`.

### Task 8: `notion_bridge.py` — gap queue + action log databases (SUP-451, 456)

**Files:**
- Create: `notion_bridge.py`, `tests/test_notion_bridge.py`, `data/notion_ids.json` (created at runtime)

**Interfaces:**
- Produces:
  - `ensure_databases() -> dict` — creates (once) a "Bert Ops" page under the Support Policy Docs page containing two databases ("Bert Gap Queue", "Bert Action Log"); caches IDs in `data/notion_ids.json`; returns `{"gap_db": id, "action_db": id}`.
  - `upsert_gap(question: str, ticket_id: str, ticket_subject: str) -> str` — fuzzy-dedupes (difflib `SequenceMatcher.ratio() >= 0.75` on lowercased question) against existing Open/Answered rows; on match increments Frequency and appends the ticket link; else creates row (Status=Open, Frequency=1). Returns page id.
  - `upsert_action(action: str, system: str, ticket_id: str, customer_email: str, confidence: str) -> str` — idempotent per (ticket_id, action) via a stable `Key` rich_text property `f"{ticket_id}:{hash(action) % 10**8}"`.
  - `fetch_answered_gaps() -> list[dict]` — rows with Status=Answered: `{page_id, question, answer, target_doc, source_tickets}`.
  - `mark_incorporated(page_id: str) -> None`.
- Gap DB properties: `Question` (title), `Status` (select: Open/Answered/Incorporated), `Source Tickets` (rich_text — newline-separated HS URLs `https://secure.helpscout.net/conversation/{id}`), `Frequency` (number), `First Seen` (date), `Last Seen` (date), `Answer` (rich_text), `Target Policy Doc` (rich_text).
- Action DB properties: `Action` (title), `System` (select: Stripe/Happier admin/Help Scout/Other), `Ticket` (url), `Customer` (email), `Confidence` (select), `Done` (checkbox), `Created` (date), `Key` (rich_text).

- [ ] **Step 1: Failing tests** — pure-logic tests only (no live Notion): dedupe matcher + key stability.

```python
# tests/test_notion_bridge.py
from notion_bridge import question_matches, action_key

def test_question_fuzzy_match():
    assert question_matches("What do we tell users about downloads returning?",
                            "what should we tell users about downloads coming back") is True

def test_question_distinct():
    assert question_matches("Where do podcast pitches go?",
                            "What is the streak restore procedure?") is False

def test_action_key_stable():
    assert action_key("123", "Apply coupon") == action_key("123", "Apply coupon")
    assert action_key("123", "Apply coupon") != action_key("124", "Apply coupon")
```

- [ ] **Step 2: Implement.** `question_matches(a, b)` = `difflib.SequenceMatcher(None, a.lower().strip(), b.lower().strip()).ratio() >= 0.75`. `action_key(ticket_id, action)` = `f"{ticket_id}:{hashlib.sha1(action.encode()).hexdigest()[:8]}"` (NOT builtin `hash` — not stable across runs). Notion HTTP: `requests` with `Authorization: Bearer {NOTION_TOKEN}`, `Notion-Version: 2022-06-28`. All public functions wrapped so callers can fail soft.
- [ ] **Step 3:** Run `python3 -c "from notion_bridge import ensure_databases; print(ensure_databases())"` live — verify the Bert Ops page + both databases appear in Notion; verify `data/notion_ids.json` written. Then live-test one `upsert_gap` twice with paraphrased questions → single row, Frequency=2. Delete test row manually or leave flagged `[TEST]`.
- [ ] **Step 4: Write-back script.** Create `process_answered_gaps.py` (CLI): calls `fetch_answered_gaps()`; for each, one Claude call (`claude-sonnet-5`, reuse `claude_utils.extract_text`) drafting a markdown addition to the `Target Policy Doc` (or proposing a new doc name) given the Question + Answer; prints the proposed diff and prompts `Apply? [y/N]` (`input()`); on yes: appends/edits the file in `policies/`, prints a reminder to sync Notion (Task 7 script), and calls `mark_incorporated(page_id)`. `--dry-run` flag prints proposals without writing.
- [ ] **Step 5:** Tests pass; commit `feat: Notion gap queue + action log bridge + answered-gap write-back (SUP-451/456)`.

### Task 9: Draft schema extensions + pipeline hooks (SUP-451, 456, 458 schema)

**Files:**
- Modify: `prompts/draft_system_prompt.txt`, `orchestrator.py`
- Test: `tests/test_pipeline_hooks.py`

**Interfaces:**
- New JSON fields (all required in the schema, nullable):
  - `"open_question"`: string|null — "If this ticket raises a question our policy docs cannot answer, state the SPECIFIC question a policy owner must answer. Else null."
  - `"needs_product_research"`: bool — "true if answering correctly requires knowing actual product behavior/feature existence/bug status not documented in the policies."
  - `"bug_report"`: `{"is_bug": bool, "matches_known_bug": string|null (known-bugs.md entry title), "new_bug_summary": string|null}`.
- Produces in `orchestrator.py`: `record_gap_and_action(out: dict, parsed: dict) -> None` — fail-soft hook calling `notion_bridge.upsert_gap` (when `open_question` OR low confidence with no `open_question` — synthesize `f"How should we answer: {subject}?"`) and `notion_bridge.upsert_action` (when needs_action).

- [ ] **Step 1:** Add the three fields to the prompt's RESPONSE FORMAT + retry suffix key list.
- [ ] **Step 2: Failing test** — `record_gap_and_action` calls the right bridge functions (monkeypatch `notion_bridge`):

```python
# tests/test_pipeline_hooks.py
import orchestrator

def test_gap_recorded_for_open_question(monkeypatch):
    calls = []
    monkeypatch.setattr(orchestrator.notion_bridge, "upsert_gap", lambda *a, **k: calls.append(("gap", a)))
    monkeypatch.setattr(orchestrator.notion_bridge, "upsert_action", lambda *a, **k: calls.append(("act", a)))
    parsed = {"open_question": "Where do podcast pitches go?", "confidence": "medium",
              "needs_action": False, "referenced_policies": []}
    out = {"conversation_id": "1", "ticket_subject": "Pitch", "customer_email": "a@b.c"}
    orchestrator.record_gap_and_action(out, parsed)
    assert ("gap", ("Where do podcast pitches go?", "1", "Pitch")) in [(c[0], c[1]) for c in calls]

def test_notion_failure_does_not_raise(monkeypatch):
    def boom(*a, **k): raise RuntimeError("notion down")
    monkeypatch.setattr(orchestrator.notion_bridge, "upsert_gap", boom)
    orchestrator.record_gap_and_action(
        {"conversation_id": "1", "ticket_subject": "s", "customer_email": "e"},
        {"open_question": "q?", "needs_action": False, "confidence": "low", "referenced_policies": []})
```

- [ ] **Step 3: Implement + wire** into `process_ticket_sync` after the draft is created. Every branch wrapped in try/except with `log.exception`.
- [ ] **Step 4:** Tests pass; commit `feat: open_question/needs_product_research/bug_report schema + Notion hooks (SUP-451/456/458)`.

### Task 10: Actions-needed note + `action_executor.py` scaffold (SUP-457)

**Files:**
- Create: `action_executor.py`, `tests/test_action_executor.py`
- Modify: `orchestrator.py` (note builder — the function around line 355)

**Interfaces:**
- `ActionPlan` dataclass: `{kind: str, params: dict, human_summary: str}`.
- `prepare_coupon(stripe_ctx: dict, percent: int) -> ActionPlan` — params include customer/subscription IDs from stripe_ctx when present.
- `prepare_cancellation(stripe_ctx: dict, at_period_end: bool = True) -> ActionPlan`.
- `execute(plan: ActionPlan) -> dict` — raises `RuntimeError("action execution disabled")` unless BOTH `STRIPE_WRITE_API_KEY` env set AND `ACTION_EXECUTION_ENABLED=true`. (No real Stripe calls implemented yet — raise `NotImplementedError` past the gate.)
- `format_actions_note(parsed: dict, stripe_ctx: dict | None) -> str` — HTML `<p><strong>🔧 Actions needed</strong></p><ul>…</ul>` from `action_description` + `action_system` (+ subscription id/amount from stripe_ctx when available); empty string when `needs_action` false.

- [ ] **Step 1: Failing tests**

```python
# tests/test_action_executor.py
import pytest
from action_executor import prepare_coupon, prepare_cancellation, execute, format_actions_note

def test_prepare_coupon_includes_sub_id():
    plan = prepare_coupon({"subscription_id": "sub_123", "customer_id": "cus_9"}, 40)
    assert plan.params["subscription_id"] == "sub_123" and plan.params["percent"] == 40
    assert "40%" in plan.human_summary

def test_execute_disabled_by_default(monkeypatch):
    monkeypatch.delenv("STRIPE_WRITE_API_KEY", raising=False)
    monkeypatch.delenv("ACTION_EXECUTION_ENABLED", raising=False)
    with pytest.raises(RuntimeError):
        execute(prepare_cancellation({"subscription_id": "sub_1"}))

def test_actions_note_lists_action():
    html = format_actions_note({"needs_action": True, "action_description": "Apply 40% coupon",
                                "action_system": "stripe"}, {"subscription_id": "sub_1"})
    assert "Actions needed" in html and "Apply 40% coupon" in html and "stripe" in html.lower()

def test_actions_note_empty_when_no_action():
    assert format_actions_note({"needs_action": False}, None) == ""
```

- [ ] **Step 2: Implement.** Check `stripe_context.py` for the actual dict keys it returns and use those names in `prepare_*` (adjust tests to the real key names before implementing).
- [ ] **Step 3: Wire** `format_actions_note` output into the internal-note HTML in `orchestrator.py` (prepend before the classification section when non-empty).
- [ ] **Step 4:** Tests pass; commit `feat: actions-needed note + execution scaffold behind env gate (SUP-457)`.

### Task 11: `linear_client.py` (supports SUP-458, 462)

**Files:**
- Create: `linear_client.py`, `tests/test_linear_client.py`

**Interfaces:**
- `search_issues(query: str, first: int = 10) -> list[dict]` — GraphQL `issueSearch` (or `searchIssues`) filtered to the Technical team; returns `[{identifier, title, state, url, description}]`.
- `create_issue(title: str, description: str, team_id: str | None = None) -> dict` — `issueCreate` mutation; default team id from env `LINEAR_TECHNICAL_TEAM_ID`, fallback constant `6c1b8aa7-78ae-4e98-919d-e0171f5b0f15`.
- Endpoint `https://api.linear.app/graphql`, header `Authorization: {LINEAR_API_KEY}`.

- [ ] **Step 1: Failing test** (mock `requests.post`):

```python
# tests/test_linear_client.py
import linear_client

def test_search_parses_nodes(monkeypatch):
    class R:
        status_code = 200
        def json(self):
            return {"data": {"searchIssues": {"nodes": [
                {"identifier": "T-787", "title": "DND broken",
                 "state": {"name": "Todo"}, "url": "https://linear.app/x", "description": "d"}]}}}
        def raise_for_status(self): pass
    monkeypatch.setattr(linear_client.requests, "post", lambda *a, **k: R())
    out = linear_client.search_issues("do not disturb")
    assert out[0]["identifier"] == "T-787" and out[0]["state"] == "Todo"
```

- [ ] **Step 2: Implement**, verifying the actual GraphQL query shape used by `product_prioritization.py` (reuse its endpoint/auth pattern). Flatten `state.name` → `state`.
- [ ] **Step 3: Live smoke test:** `python3 -c "import linear_client; print(linear_client.search_issues('streak')[:2])"` → should surface T-786. Do NOT live-test `create_issue`.
- [ ] **Step 4:** Tests pass; commit `feat: Linear client for search + issue creation (SUP-458/462)`.

### Task 12: `research_agent.py` two-pass research (SUP-462)

**Files:**
- Create: `research_agent.py`, `tests/test_research_agent.py`
- Modify: `orchestrator.py` (two-pass trigger)

**Interfaces:**
- `should_research(parsed: dict) -> bool` — `confidence == "low"` OR empty `referenced_policies` OR `needs_product_research` truthy.
- `run_research(ticket_text: str, account_summary: str, platform_hint: str | None) -> dict` — returns `{"findings": str, "sources": list[str], "tool_calls": int}`; empty findings on failure/timeout (fail soft).
- `detect_platform(ticket_text: str, account_data: dict | None) -> str` — `"ios" | "android" | "web" | "unknown"` (subscription platform: apple→ios, google→android; ticket keywords override).
- Tools (Anthropic tool-use loop, model `claude-sonnet-5`, `max_iterations=15`, wall clock 180s):
  1. `search_code {query, repo}` — `rg -n --max-count 20` over repo roots `REPO_ROOTS = {"rails": "../changecollective.com", "android": "../HappierHybrid-Android", "ios_v1": "../ten-percent-ios"}` (paths relative to SupportAgent; make absolute at import).
  2. `read_file {path, start_line, end_line}` — refuse paths outside REPO_ROOTS; max 200 lines.
  3. `search_linear {query}` — `linear_client.search_issues`.
- System prompt for the researcher: investigate the SPECIFIC product question; cite files/tickets; NEVER include code snippets in findings destined for customers; findings ≤ 300 words; end with `SOURCES:` list.
- Orchestrator integration: after first draft parse, `if should_research(parsed): research = run_research(...)`; if findings non-empty → second draft call with `=== RESEARCH FINDINGS (internal, do not quote code to customer) ===\n{findings}\nSOURCES: {sources}` appended to the user message; internal note gains `<p><strong>Research:</strong> …sources…</p>`. Record `out["research_ran"]`, `out["research_sources"]`.

- [ ] **Step 1: Failing tests** for the pure parts:

```python
# tests/test_research_agent.py
from research_agent import should_research, detect_platform, _safe_path

def test_should_research_low_confidence():
    assert should_research({"confidence": "low", "referenced_policies": ["x"]}) is True

def test_should_research_flag():
    assert should_research({"confidence": "high", "referenced_policies": ["x"],
                            "needs_product_research": True}) is True

def test_no_research_happy_path():
    assert should_research({"confidence": "high", "referenced_policies": ["x"],
                            "needs_product_research": False}) is False

def test_platform_from_google_sub():
    assert detect_platform("app is broken", {"platform": "google"}) == "android"

def test_platform_ticket_overrides():
    assert detect_platform("on my iPhone the app crashes", {"platform": "google"}) == "ios"

def test_safe_path_blocks_escape():
    assert _safe_path("../../etc/passwd") is None
```

- [ ] **Step 2: Implement** the pure functions; then the tool loop (anthropic `tools=[...]` + while loop dispatching `tool_use` blocks, collecting `tool_result` messages; stop on `end_turn`, iteration cap, or timeout; use `claude_utils.extract_text` for the final message).
- [ ] **Step 3: Live smoke test:** `run_research("User asks: is there a setting to hide practice goals?", "v2 app subscriber", "android")` → findings should cite real file paths from the rails/android repos. Print tool_calls count.
- [ ] **Step 4: Wire two-pass** into `process_ticket_sync` (fail soft: research exceptions → proceed with first draft). Tests pass; commit `feat: two-pass codebase+Linear research agent (SUP-462)`.

### Task 13: `bug_registry.py` + auto-filing (SUP-458)

**Files:**
- Create: `bug_registry.py`, `tests/test_bug_registry.py`, `data/bug_candidates.json` (runtime)
- Modify: `orchestrator.py` (hook after parse)

**Interfaces:**
- `record_bug(parsed: dict, ticket_id: str, customer_email: str, excerpt: str) -> dict | None` — if `parsed["bug_report"]["is_bug"]` and no `matches_known_bug`: fuzzy-match `new_bug_summary` (difflib ≥ 0.7) against registry candidates and open Linear issues (`linear_client.search_issues`); append report or create candidate; when a candidate reaches **2+ distinct customer emails** and has no `linear_id`, call `linear_client.create_issue` with T-759 format (title = summary; body = symptom + bullet list of `email — "excerpt"` + source HS links) and store `linear_id`. Returns the updated candidate dict or None.
- Registry JSON shape: `{"candidates": [{"summary": str, "reports": [{"email", "ticket_id", "excerpt", "date"}], "linear_id": str|null, "first_seen": str}]}` with atomic write (tmp + rename).

- [ ] **Step 1: Failing tests** (tmp_path registry, monkeypatched linear_client):

```python
# tests/test_bug_registry.py
import bug_registry

def _parsed(summary):
    return {"bug_report": {"is_bug": True, "matches_known_bug": None, "new_bug_summary": summary}}

def test_single_report_no_ticket(tmp_path, monkeypatch):
    monkeypatch.setattr(bug_registry, "REGISTRY_PATH", str(tmp_path / "r.json"))
    monkeypatch.setattr(bug_registry.linear_client, "search_issues", lambda q: [])
    created = []
    monkeypatch.setattr(bug_registry.linear_client, "create_issue",
                        lambda t, d: created.append(t) or {"identifier": "T-900"})
    c = bug_registry.record_bug(_parsed("Sleep timer resets randomly"), "1", "a@x.com", "it resets")
    assert c["linear_id"] is None and not created

def test_second_report_files_ticket(tmp_path, monkeypatch):
    monkeypatch.setattr(bug_registry, "REGISTRY_PATH", str(tmp_path / "r.json"))
    monkeypatch.setattr(bug_registry.linear_client, "search_issues", lambda q: [])
    monkeypatch.setattr(bug_registry.linear_client, "create_issue",
                        lambda t, d: {"identifier": "T-900", "url": "u"})
    bug_registry.record_bug(_parsed("Sleep timer resets randomly"), "1", "a@x.com", "resets")
    c = bug_registry.record_bug(_parsed("sleep timer keeps resetting"), "2", "b@y.com", "keeps resetting")
    assert c["linear_id"] == "T-900" and len(c["reports"]) == 2

def test_same_customer_twice_does_not_file(tmp_path, monkeypatch):
    monkeypatch.setattr(bug_registry, "REGISTRY_PATH", str(tmp_path / "r.json"))
    monkeypatch.setattr(bug_registry.linear_client, "search_issues", lambda q: [])
    monkeypatch.setattr(bug_registry.linear_client, "create_issue", lambda t, d: {"identifier": "T-901"})
    bug_registry.record_bug(_parsed("Player shows wrong time"), "1", "a@x.com", "e1")
    c = bug_registry.record_bug(_parsed("player shows the wrong time"), "2", "a@x.com", "e2")
    assert c["linear_id"] is None

def test_known_bug_skipped(tmp_path, monkeypatch):
    monkeypatch.setattr(bug_registry, "REGISTRY_PATH", str(tmp_path / "r.json"))
    p = {"bug_report": {"is_bug": True, "matches_known_bug": "Milestones broken", "new_bug_summary": None}}
    assert bug_registry.record_bug(p, "1", "a@x.com", "e") is None
```

- [ ] **Step 2: Implement**; hook into `process_ticket_sync` (fail soft) after `record_gap_and_action`.
- [ ] **Step 3:** Tests pass; commit `feat: bug candidate registry with 2-report Linear auto-filing (SUP-458)`.

### Task 14: Draft lifecycle (SUP-461)

**Files:**
- Create: `draft_registry.py`, `tests/test_draft_registry.py`, `scripts/list_stale_drafts.py`
- Modify: `orchestrator.py`

**Interfaces:**
- `draft_registry.get(cid) -> dict | None`, `draft_registry.set(cid, thread_id, drafted_at) -> None` — JSON at `data/draft_registry.json`, atomic write.
- Orchestrator behavior: before drafting, `existing = draft_registry.get(cid)`. If existing and NOT reply_mode and not `force=True` (new kwarg) → skip drafting, return `out["skipped_existing_draft"] = True`. If existing and (reply_mode or force): try in-place update (Step 1 investigation); else create new draft whose note starts with `"⚠️ Supersedes the earlier draft — discard the old one."` After creating a draft, extract the created thread id from the HS response `Resource-ID`/`Location` header and record it.

- [ ] **Step 1: Investigate PATCH.** On a closed/test conversation, create a draft, then `PATCH {BASE_URL}/conversations/{cid}/threads/{tid}` body `{"text": "updated"}` — record status code. Document the result in a comment atop `draft_registry.py`. If 2xx → implement update-in-place path; if 4xx → supersede-marker path only.
- [ ] **Step 2: Failing tests** for registry get/set round-trip (tmp_path) + skip logic as a pure function `should_skip_draft(existing: dict | None, reply_mode: bool, force: bool) -> bool` (True only when existing and not reply_mode and not force).
- [ ] **Step 3: Implement + wire.** Also write `scripts/list_stale_drafts.py`: read `eval/2026-07-02/results.json`, print the 22 conversations where a re-draft happened (two drafts live) as a checklist with HS URLs → save to `eval/2026-07-02/stale_drafts_cleanup.md`.
- [ ] **Step 4:** Tests pass; commit `feat: draft registry prevents duplicate drafts; stale-draft cleanup list (SUP-461)`.

### Task 15: Eval harness (SUP-459)

**Files:**
- Create: `eval_run.py`, `eval_draft_accuracy.py`, `tests/test_eval_accuracy.py`
- Modify: none (reuses `test_run.py`/`test_run_analysis.py` logic — move shared report generators into `eval_reports.py` imported by both old and new entry points)

**Interfaces:**
- `eval_run.py` CLI: `--date` (default today), `--limit N`, `--mailbox ID` (default 185235), `--dry-run` (no HS drafts — requires a `create_draft=False` passthrough added to `process_ticket_sync`). Produces `eval/<date>/{results.json, eval_scorecard.md, action_log.md, policy_gaps.md, new_bugs.md}` and appends one summary line to `eval/trends.md` (`date | tickets | draft% | coverage% | high/med/low | gaps | avg_ms | cache_read_avg`).
- `eval_draft_accuracy.py` CLI: `--results eval/<date>/results.json`. For each conversation: fetch threads; find Bert's draft text + the actually-sent agent reply; classify `sent_unedited` (similarity ≥ 0.95), `edited` (0.5–0.95), `discarded` (<0.5 or no sent reply while convo closed); output `eval/<date>/draft_accuracy.md` with the three percentages.
- `classify_similarity(draft: str, sent: str | None) -> str` — pure, tested.
- Scorecard gains a `cache_read_input_tokens` average column (already returned by the API; ensure `process_ticket_sync` records it in `out`).

- [ ] **Step 1: Failing test**

```python
# tests/test_eval_accuracy.py
from eval_draft_accuracy import classify_similarity

def test_unedited():
    assert classify_similarity("Hello Jane, thanks!", "Hello Jane, thanks!") == "sent_unedited"

def test_edited():
    assert classify_similarity("Hello Jane, thanks for reaching out about your refund.",
                               "Hi Jane! Thanks for reaching out about the refund — done!") == "edited"

def test_discarded():
    assert classify_similarity("Totally different draft", None) == "discarded"
```

- [ ] **Step 2: Implement** (`difflib.SequenceMatcher` on normalized text — strip HTML tags/whitespace). Build `eval_reports.py` by extracting the four `generate_*` functions from `test_run_analysis.py` (leave a thin wrapper there for compat). Build `eval_run.py` on `test_run.py`'s executor pattern.
- [ ] **Step 3:** Tests pass. Smoke: `python3 eval_run.py --limit 2 --dry-run` (no HS drafts created; results + reports written to today's folder — use a `--date 2026-07-02-smoke` folder and delete after).
- [ ] **Step 4:** Commit `feat: consolidated eval harness + draft accuracy tracking (SUP-459)`.

### Task 16: Final validation + Linear/doc updates

- [ ] **Step 1:** Full unit suite green: `python3 -m pytest tests/ -v` (pre-existing failures in `test_maven_orchestrator.py`/`test_sidebar.py`, if any, are out of scope — note them).
- [ ] **Step 2: Acceptance re-runs** (live, `--dry-run` off is OK — drafts on these tickets are expected and reviewable): re-run through `process_ticket_sync(skip_triage=True)`:
  - a downloads ticket (`3372568142`) → expects `downloads-offline.md` referenced, confidence ≥ medium, notify-commitment present, no fabricated ETA;
  - the DND ticket (`3372229124`) → `known-bugs.md` matched via `bug_report.matches_known_bug`;
  - the practice-goals ticket (`3373518340`) → `check-ins-goals-intentions.md` referenced, no-setting stance;
  - the podcast pitch (`3372998714`) → `non-support-requests.md`, polite decline;
  - one reply conversation from the 22 (pick from `eval/2026-07-02/results.json`) → `reply_mode=True`, draft addresses latest message, draft_registry supersede path exercised.
  Record each result (confidence, referenced_policies, tags) in `eval/2026-07-02/acceptance_validation.md`.
- [ ] **Step 3:** Verify Notion: gap rows and action rows created by the acceptance runs exist; screenshot-level check via API list.
- [ ] **Step 4:** Update `CLAUDE.md` repository map (new modules: claude_utils, notion_bridge, linear_client, research_agent, bug_registry, action_executor, draft_registry, eval_run, eval_draft_accuracy, eval_reports) and env vars (`LINEAR_TECHNICAL_TEAM_ID`, `STRIPE_WRITE_API_KEY`, `ACTION_EXECUTION_ENABLED`, `NOTION_TOKEN`).
- [ ] **Step 5:** Commit `docs: update repo map + env vars`. Mark Linear sub-issues Done (SUP-447, 448, 449, 451–462 minus 450) with a one-line completion comment each; leave SUP-457 in progress-note that execution awaits the write key; leave SUP-461 note with the PATCH investigation outcome.
