# Bert Morning Review Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `bert/`, a new interactive whole-mailbox "morning review" surface that summarizes tickets cheaply (Haiku map/reduce), drafts every reply via a fan-out that injects a shared standing brief, and posts drafts on approval — reusing the existing pipeline primitives without touching the live orchestrator.

**Architecture:** New self-contained `bert/` package. It reuses the existing draft "brain" (`orchestrator._call_claude_draft_with_action_retry`, `_build_dynamic_user_message`, `load_policy_docs`) and Help Scout / account / Stripe fetchers rather than reimplementing them. A per-morning JSON state file holds the lightweight ticket index and the standing brief. `.claude/skills/bert-*` drive the loop from a session.

**Tech Stack:** Python 3.9 (`from __future__ import annotations`), `anthropic`, `requests`, `pytest` with `monkeypatch`. No new dependencies.

## Global Constraints

- Every module starts with `from __future__ import annotations` (repo runs on Python 3.9; `X | None` is used in annotations only).
- Summary (MAP) model: `claude-haiku-4-5`. Draft model: `claude-sonnet-5` (reuse `orchestrator.DEFAULT_CLAUDE_MODEL`; `CLAUDE_DRAFT_MODEL` env still overrides).
- Enrichment/summary steps fail soft (log + continue); one bad ticket never blocks the batch.
- Do NOT modify `orchestrator.py`, `triage_tickets.py`, `account_context.py`, `maven_customer_context.py`, or `process_ticket_sync`. Reuse by import only.
- Atomic JSON writes (mirror `draft_registry._atomic_write_json`).
- Tests mock external calls via `monkeypatch`; no live network in the suite.

---

### Task 1: `bert/` package + state file (`bert/state.py`)

**Files:**
- Create: `bert/__init__.py` (empty)
- Create: `bert/state.py`
- Test: `tests/test_bert_state.py`

**Interfaces:**
- Produces:
  - `state_path(date_str: str, base_dir: str | None = None) -> str`
  - `new_state(date_str: str) -> dict` → `{"date", "records": [], "brief": [], "statuses": {}}`
  - `load(date_str: str, base_dir: str | None = None) -> dict` (returns `new_state` if file absent)
  - `save(state: dict, base_dir: str | None = None) -> None` (atomic)
  - `set_records(state: dict, records: list[dict]) -> None`
  - `append_brief(state: dict, note: str) -> None`
  - `render_brief(state: dict) -> str` (bulleted; `""` when empty)
  - `set_status(state: dict, cid: str, **fields) -> None`

- [ ] **Step 1: Write failing tests** in `tests/test_bert_state.py`:

```python
from __future__ import annotations
import bert.state as st

def test_new_state_shape():
    s = st.new_state("2026-07-06")
    assert s == {"date": "2026-07-06", "records": [], "brief": [], "statuses": {}}

def test_save_and_load_roundtrip(tmp_path):
    s = st.new_state("2026-07-06")
    st.append_brief(s, "Streak bug fixed 7/5")
    st.set_records(s, [{"conversation_id": 1}])
    st.save(s, base_dir=str(tmp_path))
    loaded = st.load("2026-07-06", base_dir=str(tmp_path))
    assert loaded["brief"] == ["Streak bug fixed 7/5"]
    assert loaded["records"] == [{"conversation_id": 1}]

def test_load_missing_returns_new(tmp_path):
    assert st.load("1999-01-01", base_dir=str(tmp_path))["records"] == []

def test_render_brief_empty_and_bulleted():
    s = st.new_state("d")
    assert st.render_brief(s) == ""
    st.append_brief(s, "A"); st.append_brief(s, "B")
    assert st.render_brief(s) == "- A\n- B"

def test_append_brief_dedupes_exact():
    s = st.new_state("d")
    st.append_brief(s, "same"); st.append_brief(s, "same")
    assert s["brief"] == ["same"]

def test_set_status_merges(tmp_path):
    s = st.new_state("d")
    st.set_status(s, "42", drafted=True, confidence="low")
    st.set_status(s, "42", posted=True)
    assert s["statuses"]["42"] == {"drafted": True, "confidence": "low", "posted": True}
```

- [ ] **Step 2: Run to verify fail** — `python3 -m pytest tests/test_bert_state.py -q` → FAIL (module missing).
- [ ] **Step 3: Implement** `bert/state.py` with an atomic writer (copy `draft_registry` pattern), default dir `data/morning_review/`, filename `<date>.json`. `append_brief` skips exact duplicates. `set_status` merges into `statuses[cid]`.
- [ ] **Step 4: Run to verify pass.**
- [ ] **Step 5: Commit** — `feat(bert): morning-review state file (index + standing brief)`.

---

### Task 2: Mailbox stats + HTML render (`bert/render.py`)

**Files:**
- Create: `bert/render.py`
- Test: `tests/test_bert_render.py`

**Interfaces:**
- Consumes: records shaped `{conversation_id, customer, category, one_line, urgent, is_new, matches_known_bug}`.
- Produces:
  - `mailbox_stats(records: list[dict]) -> dict` → `{"total", "urgent_count", "new_count", "by_category": dict, "known_bug_hits": dict}`
  - `render_summary_html(state: dict) -> str` (standalone `<div>`; escapes text)

- [ ] **Step 1: Write failing tests:**

```python
from __future__ import annotations
import bert.render as r

RECS = [
    {"conversation_id": 1, "customer": "A", "category": "billing", "one_line": "refund", "urgent": True, "is_new": True, "matches_known_bug": None},
    {"conversation_id": 2, "customer": "B", "category": "billing", "one_line": "charge", "urgent": False, "is_new": False, "matches_known_bug": "streaks"},
    {"conversation_id": 3, "customer": "C", "category": "bug", "one_line": "<script>", "urgent": False, "is_new": True, "matches_known_bug": "streaks"},
]

def test_stats():
    s = r.mailbox_stats(RECS)
    assert s["total"] == 3
    assert s["urgent_count"] == 1
    assert s["new_count"] == 2
    assert s["by_category"] == {"billing": 2, "bug": 1}
    assert s["known_bug_hits"] == {"streaks": 2}

def test_stats_empty():
    assert r.mailbox_stats([])["total"] == 0

def test_html_contains_ids_and_escapes():
    html = r.render_summary_html({"date": "2026-07-06", "records": RECS, "brief": ["x"], "statuses": {}})
    assert "2026-07-06" in html and "billing" in html
    assert "&lt;script&gt;" in html and "<script>" not in html
```

- [ ] **Step 2: Run to verify fail.**
- [ ] **Step 3: Implement.** `mailbox_stats` pure aggregation. `render_summary_html` builds a `<div>` with a header (date + counts), a per-category rollup, a known-bug rollup, and a table of one row per record (id, customer, category, one_line, urgent flag). Escape every interpolated string with `html.escape`.
- [ ] **Step 4: Run to verify pass.**
- [ ] **Step 5: Commit** — `feat(bert): mailbox stats + HTML summary render`.

---

### Task 3: Summarize (MAP) — prompt + parse + fan-out (`bert/summarize.py`)

**Files:**
- Create: `bert/summarize.py`
- Test: `tests/test_bert_summarize.py`

**Interfaces:**
- Produces:
  - `SUMMARY_MODEL = "claude-haiku-4-5"`
  - `build_summary_prompt(ticket: dict) -> str` (ticket = `{conversation_id, subject, body, tags}`)
  - `parse_summary(text: str, conversation_id: int) -> dict` (tolerant JSON parse → record; on failure returns a record with `category="unknown"`, `one_line="(summary unavailable)"`, others falsy)
  - `summarize_ticket(client, ticket: dict) -> dict`
  - `summarize_mailbox(tickets: list[dict], client, *, max_workers: int = 8) -> list[dict]` (fan-out, isolate per-ticket failures)

- [ ] **Step 1: Write failing tests:**

```python
from __future__ import annotations
import json
import bert.summarize as sm

def test_build_prompt_includes_fields():
    p = sm.build_summary_prompt({"conversation_id": 9, "subject": "Refund", "body": "double charged", "tags": ["billing"]})
    assert "Refund" in p and "double charged" in p

def test_parse_good_json():
    raw = json.dumps({"category": "billing", "one_line": "refund req", "urgent": True, "is_new": False, "matches_known_bug": None})
    rec = sm.parse_summary(raw, 9)
    assert rec["conversation_id"] == 9 and rec["category"] == "billing" and rec["urgent"] is True

def test_parse_with_fences():
    rec = sm.parse_summary('```json\n{"category":"bug","one_line":"x","urgent":false,"is_new":true,"matches_known_bug":"streaks"}\n```', 3)
    assert rec["matches_known_bug"] == "streaks"

def test_parse_bad_json_fails_soft():
    rec = sm.parse_summary("not json", 7)
    assert rec["conversation_id"] == 7 and rec["category"] == "unknown" and rec["one_line"] == "(summary unavailable)"

class _FakeMsg:
    def __init__(self, text): self.content = [type("B", (), {"type": "text", "text": text})()]
class _FakeClient:
    def __init__(self, text): self._t = text; self.messages = self
    def create(self, **k): return _FakeMsg(self._t)

def test_summarize_ticket_uses_client():
    c = _FakeClient(json.dumps({"category":"billing","one_line":"r","urgent":False,"is_new":True,"matches_known_bug":None}))
    rec = sm.summarize_ticket(c, {"conversation_id": 1, "subject": "s", "body": "b", "tags": []})
    assert rec["category"] == "billing"

def test_summarize_mailbox_isolates_failures():
    class Boom:
        messages = None
        def create(self, **k): raise RuntimeError("api down")
    c = Boom()
    recs = sm.summarize_mailbox([{"conversation_id": 1, "subject":"s","body":"b","tags":[]}], c, max_workers=2)
    assert len(recs) == 1 and recs[0]["one_line"] == "(summary unavailable)"
```

- [ ] **Step 2: Run to verify fail.**
- [ ] **Step 3: Implement.** Use `orchestrator.claude_utils`-style text extraction — reuse `claude_utils.extract_text` (already in repo) to read the response. `summarize_ticket` calls `client.messages.create(model=SUMMARY_MODEL, max_tokens=300, ...)`. `summarize_mailbox` uses `concurrent.futures.ThreadPoolExecutor`; any exception per ticket → `parse_summary("", cid)` fallback record. Preserve input order.
- [ ] **Step 4: Run to verify pass.**
- [ ] **Step 5: Commit** — `feat(bert): mailbox summarize map step (Haiku fan-out)`.

---

### Task 4: Shared draft seams (`bert/pipeline.py`)

**Files:**
- Create: `bert/pipeline.py`
- Test: `tests/test_bert_pipeline.py`

**Interfaces:**
- Consumes: `orchestrator` primitives (`load_policy_docs`, `_load_system_prompt`, `_build_dynamic_user_message`, `_call_claude_draft_with_action_retry`, `REPLY_MODE_PROMPT_PREFIX`, `_helpscout_post`, `draft_registry`, `BASE_URL`); `triage_tickets` fetchers.
- Produces:
  - `BRIEF_PREFIX = "\n\n=== STANDING BRIEF (internal team context — apply, do not quote to customer) ===\n"`
  - `inject_brief(dynamic_message: str, brief: str) -> str` (append brief block iff brief non-empty)
  - `hydrate_ticket(session, conversation_id: int) -> dict` → `{conversation_id, subject, customer_name, hs_customer_id, email, body, conversation_history, reply_mode, account_blob, stripe_block, existing_tags}`
  - `draft_one(client, ctx: dict, brief: str, *, model: str) -> dict` → parsed draft dict + `{"draft_reply", "confidence", "referenced_policies", "reasoning", "needs_action", "escalate", "open_question", "bug_report"}`
  - `post_draft(session, conversation_id: str, hs_customer_id: int, draft_reply: str, timestamp: str) -> str | None` (returns HS draft id; updates `draft_registry`)

- [ ] **Step 1: Write failing tests** (unit-test the pure/logic parts + mock the orchestrator seam):

```python
from __future__ import annotations
import bert.pipeline as pl

def test_inject_brief_appends_when_present():
    out = pl.inject_brief("MSG", "- streak fixed")
    assert out.startswith("MSG") and "STANDING BRIEF" in out and "streak fixed" in out

def test_inject_brief_noop_when_empty():
    assert pl.inject_brief("MSG", "") == "MSG"

def test_draft_one_injects_brief_and_parses(monkeypatch):
    captured = {}
    def fake_call(client, *, system_prompt, policy_docs, dynamic_user_message, model):
        captured["msg"] = dynamic_user_message
        return (object(), {"draft_reply": "hi", "confidence": "high", "referenced_policies": ["p"],
                           "needs_action": False, "escalate": False, "reasoning": "r",
                           "open_question": None, "bug_report": None}, "raw")
    monkeypatch.setattr(pl.orchestrator, "_call_claude_draft_with_action_retry", fake_call)
    monkeypatch.setattr(pl.orchestrator, "load_policy_docs", lambda: "POLICIES")
    monkeypatch.setattr(pl.orchestrator, "_load_system_prompt", lambda: "SYS")
    ctx = {"conversation_id": 1, "subject": "s", "body": "b", "customer_name": "N",
           "email": "e@x.co", "account_blob": "A", "stripe_block": "S",
           "conversation_history": "", "reply_mode": False}
    res = pl.draft_one(object(), ctx, "- streak fixed", model="claude-sonnet-5")
    assert res["draft_reply"] == "hi" and res["confidence"] == "high"
    assert "STANDING BRIEF" in captured["msg"] and "streak fixed" in captured["msg"]

def test_draft_one_reply_mode_prefixes(monkeypatch):
    captured = {}
    def fake_call(client, *, system_prompt, policy_docs, dynamic_user_message, model):
        captured["msg"] = dynamic_user_message
        return (object(), {"draft_reply": "x"}, "raw")
    monkeypatch.setattr(pl.orchestrator, "_call_claude_draft_with_action_retry", fake_call)
    monkeypatch.setattr(pl.orchestrator, "load_policy_docs", lambda: "P")
    monkeypatch.setattr(pl.orchestrator, "_load_system_prompt", lambda: "SYS")
    ctx = {"conversation_id": 1, "subject": "s", "body": "b", "customer_name": "N",
           "email": "e", "account_blob": "A", "stripe_block": "S",
           "conversation_history": "prev", "reply_mode": True}
    pl.draft_one(object(), ctx, "", model="m")
    assert pl.orchestrator.REPLY_MODE_PROMPT_PREFIX.split()[0] in captured["msg"]

def test_post_draft_records_registry(monkeypatch):
    class R:
        headers = {"Resource-ID": "tid-9"}
        def raise_for_status(self): pass
    monkeypatch.setattr(pl.orchestrator, "_helpscout_post", lambda s, u, p: R())
    sets = {}
    monkeypatch.setattr(pl.orchestrator.draft_registry, "set", lambda cid, tid, ts: sets.update({cid: tid}))
    rid = pl.post_draft(object(), "5", 100, "draft text", "2026-07-06T00:00:00Z")
    assert rid == "tid-9" and sets == {"5": "tid-9"}
```

- [ ] **Step 2: Run to verify fail.**
- [ ] **Step 3: Implement.** `import orchestrator`, `import triage_tickets`. `hydrate_ticket` mirrors the read path of `process_ticket_sync` (lines 707–820) using the same helpers; wrap account/Stripe in try/except → fail-soft blobs. `draft_one` builds the message via `orchestrator._build_dynamic_user_message`, applies reply-mode prefix, then `inject_brief`, then calls the shared draft primitive; normalizes the parsed dict. `post_draft` POSTs the reply draft and calls `draft_registry.set`.
- [ ] **Step 4: Run to verify pass.**
- [ ] **Step 5: Commit** — `feat(bert): shared hydrate/draft/post seams reusing orchestrator brain`.

---

### Task 5: Draft fan-out + partition (`bert/fanout.py`)

**Files:**
- Create: `bert/fanout.py`
- Test: `tests/test_bert_fanout.py`

**Interfaces:**
- Consumes: `bert.pipeline.hydrate_ticket`, `bert.pipeline.draft_one`.
- Produces:
  - `draft_all(records, session, client, brief, *, model, max_workers=6) -> list[dict]` — one result per record: the `draft_one` dict plus `{conversation_id, hs_customer_id, ok: bool, error: str | None}`; per-ticket failures isolated (`ok=False`).
  - `partition(results: list[dict]) -> dict` → `{"ready": [...], "review": [...]}`. A result goes to `review` if `not ok`, `confidence in (None, "low")`, `needs_action`, `escalate`, truthy `open_question`, or `bug_report.is_bug`; else `ready`.

- [ ] **Step 1: Write failing tests:**

```python
from __future__ import annotations
import bert.fanout as fo

def test_partition_routes_low_and_flagged():
    results = [
        {"conversation_id": 1, "ok": True, "confidence": "high", "needs_action": False, "escalate": False, "open_question": None, "bug_report": None},
        {"conversation_id": 2, "ok": True, "confidence": "low", "needs_action": False, "escalate": False, "open_question": None, "bug_report": None},
        {"conversation_id": 3, "ok": True, "confidence": "high", "needs_action": True, "escalate": False, "open_question": None, "bug_report": None},
        {"conversation_id": 4, "ok": False, "confidence": None, "error": "boom"},
        {"conversation_id": 5, "ok": True, "confidence": "high", "needs_action": False, "escalate": False, "open_question": "which plan?", "bug_report": None},
        {"conversation_id": 6, "ok": True, "confidence": "high", "needs_action": False, "escalate": False, "open_question": None, "bug_report": {"is_bug": True}},
    ]
    p = fo.partition(results)
    assert [r["conversation_id"] for r in p["ready"]] == [1]
    assert {r["conversation_id"] for r in p["review"]} == {2, 3, 4, 5, 6}

def test_draft_all_isolates_failures(monkeypatch):
    def fake_hydrate(session, cid):
        if cid == 2: raise RuntimeError("hydrate fail")
        return {"conversation_id": cid, "hs_customer_id": 100 + cid}
    def fake_draft(client, ctx, brief, *, model):
        return {"draft_reply": "d", "confidence": "high", "needs_action": False,
                "escalate": False, "open_question": None, "bug_report": None,
                "referenced_policies": ["p"], "reasoning": "r"}
    monkeypatch.setattr(fo.pipeline, "hydrate_ticket", fake_hydrate)
    monkeypatch.setattr(fo.pipeline, "draft_one", fake_draft)
    recs = [{"conversation_id": 1}, {"conversation_id": 2}]
    out = fo.draft_all(recs, object(), object(), "", model="m", max_workers=2)
    by_id = {r["conversation_id"]: r for r in out}
    assert by_id[1]["ok"] is True and by_id[1]["draft_reply"] == "d"
    assert by_id[2]["ok"] is False and "hydrate fail" in by_id[2]["error"]
```

- [ ] **Step 2: Run to verify fail.**
- [ ] **Step 3: Implement.** `import bert.pipeline as pipeline`. `draft_all` runs a `ThreadPoolExecutor`; each task hydrates then drafts, catching exceptions into `{ok: False, error}`. Merge `conversation_id` + `hs_customer_id` into each result. `partition` applies the routing rule.
- [ ] **Step 4: Run to verify pass.**
- [ ] **Step 5: Commit** — `feat(bert): draft fan-out + confidence partition`.

---

### Task 6: Bert system prompt + skills (`bert/prompts/`, `.claude/skills/bert-*`)

**Files:**
- Create: `bert/prompts/bert_system_prompt.txt`
- Create: `.claude/skills/bert-morning-review/SKILL.md`
- Create: `.claude/skills/bert-summarize-mailbox/SKILL.md`
- Create: `.claude/skills/bert-hydrate-ticket/SKILL.md`
- Create: `.claude/skills/bert-draft-all/SKILL.md`
- Create: `.claude/skills/bert-resolve/SKILL.md`
- Create: `.claude/skills/bert-post/SKILL.md`
- Test: `tests/test_bert_skills.py` (structural: files exist, have frontmatter, reference real entry points)

**Interfaces:** Documentation/instructions only; no Python API. `bert-morning-review` is the entry point and sequences the others.

- [ ] **Step 1: Write failing test:**

```python
from __future__ import annotations
import os, glob

SKILL_DIR = ".claude/skills"
EXPECTED = ["bert-morning-review", "bert-summarize-mailbox", "bert-hydrate-ticket", "bert-draft-all", "bert-resolve", "bert-post"]

def test_all_skills_exist_with_frontmatter():
    for name in EXPECTED:
        path = os.path.join(SKILL_DIR, name, "SKILL.md")
        assert os.path.exists(path), f"missing {path}"
        head = open(path).read(400)
        assert head.startswith("---") and "name:" in head and "description:" in head

def test_morning_review_references_steps():
    body = open(os.path.join(SKILL_DIR, "bert-morning-review", "SKILL.md")).read()
    for step in ["summarize", "draft", "resolve", "post"]:
        assert step in body.lower()

def test_system_prompt_exists():
    assert os.path.exists("bert/prompts/bert_system_prompt.txt")
    assert len(open("bert/prompts/bert_system_prompt.txt").read()) > 200
```

- [ ] **Step 2: Run to verify fail.**
- [ ] **Step 3: Implement.** Write the system prompt (foreman persona: holds the standing brief, drives the loop, never quotes internal context to customers, defaults to safe classifications). Write each SKILL.md with YAML frontmatter (`name`, `description`) and a body describing when/how to run the corresponding `bert/` entry point and what to hand back to the session. `bert-morning-review` documents the full loop and delegates to the others.
- [ ] **Step 4: Run to verify pass.**
- [ ] **Step 5: Commit** — `feat(bert): system prompt + morning-review skill set`.

---

### Task 7: CLI entry + full-suite green

**Files:**
- Modify: `bert/summarize.py` (add `fetch_open_tickets(session, mailbox_id=None) -> list[dict]` + `__main__` block)
- Test: covered by Task 3 test file (add fetch test with mocked `api_get`)

**Interfaces:**
- Produces: `fetch_open_tickets(session, mailbox_id: int | None = None, *, status: str = "active") -> list[dict]` returning ticket dicts `{conversation_id, subject, body, tags}` (reuse `triage_tickets.api_get` + `get_conversation_text`).

- [ ] **Step 1: Write failing test** in `tests/test_bert_summarize.py`:

```python
def test_fetch_open_tickets_maps_fields(monkeypatch):
    import bert.summarize as sm
    monkeypatch.setattr(sm, "_list_conversations", lambda session, mailbox_id, status: [
        {"id": 11, "subject": "Hi", "tags": [{"tag": "billing"}]}])
    monkeypatch.setattr(sm, "_conversation_text", lambda session, cid: "body text")
    out = sm.fetch_open_tickets(object())
    assert out == [{"conversation_id": 11, "subject": "Hi", "body": "body text", "tags": ["billing"]}]
```

- [ ] **Step 2: Run to verify fail.**
- [ ] **Step 3: Implement.** Add thin `_list_conversations` (wraps `triage_tickets.api_get` on `/conversations?status=active`) and `_conversation_text` (wraps `triage_tickets.get_conversation_text`) so they're monkeypatchable; `fetch_open_tickets` maps to the ticket dict shape. Add a `if __name__ == "__main__":` block: get token, build session, fetch + summarize, write state, print the HTML artifact path.
- [ ] **Step 4: Run full suite** — `python3 -m pytest -q` → all bert tests pass; pre-existing `test_maven_orchestrator` failure unrelated (env leakage) and unchanged.
- [ ] **Step 5: Commit** — `feat(bert): open-ticket fetch + CLI entry`.

---

## Self-Review

- **Spec coverage:** state file (T1), summary map + reduce/stats + render (T2, T3, T7), standing brief + two-context injection (T1 brief, T4 `inject_brief`/`draft_one`), fan-out with brief (T5), partition into ready/review (T5), skills + system prompt (T6), knowledge-capture write-back — **partially deferred**: the `capture-knowledge` write-back to `policies/*.md` is documented in the `bert-resolve` skill (T6) as a session-driven action reusing existing `process_answered_gaps.py`/file edits, not a new Python module in this plan (YAGNI for v1; the session performs the edit).
- **Deviation from spec Phase 1:** the plan does NOT rewire `process_ticket_sync`; instead Bert reuses the same draft primitives directly. Rationale: the spec's safety gate for that refactor is a live eval-run diff, unavailable in this environment. Same brain, zero production risk. Flag to Cassidy; the DRY rewire remains a future follow-up.
- **Placeholder scan:** none.
- **Type consistency:** record shape identical across T2/T3/T5; `draft_one` output keys consumed by `partition` (T5) match those produced in T4.
