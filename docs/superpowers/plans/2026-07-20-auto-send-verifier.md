# Auto-Send Verifier Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a VERIFIER stage to the Bert draft pipeline: every auto-send candidate gets an adversarial review, and the `auto_send` tag in Help Scout follows the verifier's verdict (applied only on SEND_AS_IS, removed on MINOR/ERROR).

**Architecture:** New module `bert/verify.py` (deterministic pre-lint + sibling-ticket check + one Claude call per draft using the full policy corpus). Wired into `bert/fanout.py` after `apply_result` posts/updates a draft. Fail-soft: a verifier failure never blocks the draft; it just means no `auto_send` tag.

**Tech Stack:** Python 3, anthropic SDK, requests (Help Scout API), pytest with monkeypatch (repo's existing test style).

## Global Constraints

- Prompts live in `prompts/*.txt`, never inline in Python (repo convention).
- Verifier model default: `claude-sonnet-5`, configurable via `BERT_VERIFY_MODEL`.
- Verdict values: exactly `SEND_AS_IS` | `MINOR` | `ERROR`.
- Finding shape: `{class, detail, fix_type, suggested_fix}` where class ∈ A–I.
- Error rubric classes: A factual/account mismatch; B policy violation; C over-claim/unperformable action; D stale-world claim; E naming/brand violation ("Ten Percent Happier" spelled out — Dan Harris is always "10% Happier" in numerals); F wrong-thread; G tone/AI-tell; H mechanical (broken HTML, raw URLs, placeholders, mojibake); I missed suppression signal.
- Pre-lint (no model call) catches: spelled-out "Ten Percent Happier" (→E), leftover `{placeholders}` (→H), mojibake sequences like `â€"` (→H), bare `my.meditatehappier.com/start/sign_in` links WITHOUT a `coupon=` param (→B; coupon checkout links are legitimate per policies/login-issues.md).
- Sibling check: other **active** Help Scout conversations for the same customer email → automatic ERROR, class I, fix_type `consolidate`.
- Tag reconcile: apply `auto_send` only on SEND_AS_IS; remove an existing `auto_send` tag on any other outcome (MINOR/ERROR/verify failure). Removal = `PUT /v2/conversations/{id}/tags` with the tag list minus `auto_send`.
- Verdicts + findings must appear in the `apply_result` status dict (`verify_verdict`, `verify_findings`, `verify_error`) and be recorded into the day's state via `bert.state.set_status` (caller/skill responsibility — `set_status` already merges arbitrary fields).
- Test command: `PYTHONPATH=<worktree> /Users/cassidystagnitti/code/code-happierMeditation/SupportAgent/.venv/bin/python -m pytest tests/ -q`

---

### Task 1: `bert/verify.py` — pre-lint + sibling check (deterministic, no model)

**Files:**
- Create: `bert/verify.py`
- Test: `tests/test_bert_verify.py`

**Interfaces:**
- Produces: `prelint(draft_reply: str) -> list[dict]` (findings, empty when clean); `find_sibling_conversations(session, email, *, exclude_cid) -> list[int]` (raises on API failure — caller decides fail-soft).

- [ ] **Step 1: Write failing tests** (`tests/test_bert_verify.py`)

```python
"""Tests for the auto-send verifier (bert/verify.py)."""
import bert.verify as verify


# --- prelint: deterministic must-not-send checks (no model call) ---

def test_prelint_clean_draft_returns_no_findings():
    assert verify.prelint("<p>Hi there! Thanks for meditating with us.</p>") == []

def test_prelint_flags_spelled_out_brand_name():
    findings = verify.prelint("<p>Dan Harris wrote Ten Percent Happier.</p>")
    assert any(f["class"] == "E" for f in findings)

def test_prelint_flags_leftover_placeholder():
    findings = verify.prelint("<p>Hi {%customer.firstName%}, welcome back.</p>")
    assert any(f["class"] == "H" and "placeholder" in f["detail"].lower() for f in findings)

def test_prelint_flags_mojibake():
    findings = verify.prelint("<p>Weâ€™re happy to help â€” truly.</p>")
    assert any(f["class"] == "H" and "mojibake" in f["detail"].lower() for f in findings)

def test_prelint_flags_bare_website_signin_link():
    findings = verify.prelint('<a href="https://my.meditatehappier.com/start/sign_in">sign in</a>')
    assert any(f["class"] == "B" for f in findings)

def test_prelint_allows_coupon_checkout_link():
    assert verify.prelint('<a href="https://my.meditatehappier.com/start/sign_in?coupon=WINBACK40">40% off</a>') == []

def test_prelint_ok_with_10_percent_happier_numerals():
    assert verify.prelint("<p>Dan Harris's 10% Happier podcast.</p>") == []


# --- sibling check ---

def test_siblings_excludes_own_conversation(monkeypatch):
    monkeypatch.setattr(verify.triage_tickets, "api_get", lambda s, url, params=None: {
        "_embedded": {"conversations": [{"id": 5}, {"id": 9}]}})
    assert verify.find_sibling_conversations(object(), "a@b.com", exclude_cid=5) == [9]

def test_siblings_empty_email_short_circuits(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("must not hit the API without an email")
    monkeypatch.setattr(verify.triage_tickets, "api_get", boom)
    assert verify.find_sibling_conversations(object(), "", exclude_cid=5) == []

def test_siblings_queries_active_by_email(monkeypatch):
    seen = {}
    def fake_get(session, url, params=None):
        seen["params"] = params
        return {"_embedded": {"conversations": []}}
    monkeypatch.setattr(verify.triage_tickets, "api_get", fake_get)
    verify.find_sibling_conversations(object(), "a@b.com", exclude_cid=5)
    assert seen["params"]["status"] == "active"
    assert 'a@b.com' in seen["params"]["query"]
```

- [ ] **Step 2: Run tests, verify they fail** (`ModuleNotFoundError: bert.verify`)
- [ ] **Step 3: Implement `bert/verify.py`** (prelint + find_sibling_conversations; module docstring; constants for mojibake markers and sign-in link regex)
- [ ] **Step 4: Run tests, verify pass**
- [ ] **Step 5: Commit** `feat: verifier pre-lint + sibling-ticket check (bert/verify.py)`

### Task 2: verifier prompt + `verify_draft` model call

**Files:**
- Create: `prompts/verify_system_prompt.txt`
- Modify: `bert/verify.py`
- Test: `tests/test_bert_verify.py`

**Interfaces:**
- Consumes: `orchestrator._parse_claude_json`, `claude_utils.extract_text`, `orchestrator.load_policy_docs` (passed in by caller).
- Produces: `verify_draft(client, result, ctx, brief, policies, *, model=None) -> dict` returning `{"verdict": ..., "findings": [...]}`; raises on unusable model output (caller fail-softs). `DEFAULT_VERIFY_MODEL = os.getenv("BERT_VERIFY_MODEL", "claude-sonnet-5")`.

- [ ] **Step 1: Write failing tests** — fake anthropic client returning a JSON verdict; assert verdict normalization (lowercase → upper), findings normalized to the 4-key shape, policies + draft + brief present in the request, invalid verdict raises ValueError, JSON-parse failure retries once then raises.
- [ ] **Step 2: Run tests, verify fail**
- [ ] **Step 3: Write `prompts/verify_system_prompt.txt`** — adversarial reviewer role, full A–I rubric, verdict semantics (SEND_AS_IS = zero must-fix findings, safe to send unedited; MINOR = small human touch-up needed; ERROR = must not send), default-to-not-clean when uncertain, JSON-only output contract.
- [ ] **Step 4: Implement `verify_draft`** — system block (prompt file, cache_control ephemeral) + user content [policy corpus block with cache_control, dynamic message with ticket ctx/account/Stripe/brief/draft]. `max_tokens=4000`. One strict-JSON retry.
- [ ] **Step 5: Run tests, verify pass**
- [ ] **Step 6: Commit** `feat: verifier model call + rubric prompt`

### Task 3: wire verifier into `bert/fanout.py`; tag follows verdict

**Files:**
- Modify: `bert/fanout.py`
- Test: `tests/test_bert_autosend_tag.py` (rewrite apply-tag section), `tests/test_bert_fanout.py` (update the two auto-send tests)

**Interfaces:**
- Produces: `reconcile_auto_send_tag(session, cid, verdict) -> str | None` ("tagged"/"already"/"removed"/None, never raises); `verify_and_tag(session, client, result, *, brief="", model=None) -> {"verdict", "findings", "tag", "error"}` (never raises); `apply_result(session, result, *, timestamp=None, verify_client=None, brief="", verify_model=None)` with new status keys `verify_verdict`, `verify_findings`, `verify_error`.
- Removes: `apply_auto_send_tag` (unverified tagging is a footgun now that the tag means "verified clean").

- [ ] **Step 1: Write failing tests** covering: prelint hit → ERROR without model call or hydration; siblings → ERROR/class I/consolidate + tag removed; SEND_AS_IS → tag applied; MINOR → existing tag removed; verifier exception → fail-soft (error recorded, no tag); reconcile idempotency ("already", None when absent and verdict bad); apply_result passes brief and records verdict keys; apply_result without verify_client leaves candidate untagged (and strips an existing tag).
- [ ] **Step 2: Run tests, verify fail**
- [ ] **Step 3: Implement fanout changes**
- [ ] **Step 4: Run full test suite, verify pass**
- [ ] **Step 5: Commit** `feat: auto_send tag follows verifier verdict in fanout apply`

### Task 4: `bert/mcp_tools.py` post_drafts passes the verifier client

**Files:**
- Modify: `bert/mcp_tools.py` (post_drafts: `verify_client=_anthropic_client(), brief=run.get("brief") or ""`)
- Test: `tests/test_mcp_tools.py` (assert post_drafts passes a verify client + run brief through to apply_result)

- [ ] Steps: failing test → implement → pass → commit `feat: MCP post_drafts verifies auto-send candidates`

### Task 5: docs — skills + CLAUDE.md

**Files:**
- Modify: `.claude/skills/bert-post/SKILL.md` (apply_result signature, verifier behavior, set_status verify fields)
- Modify: `.claude/skills/bert-draft-all/SKILL.md` (note: auto-send candidates are verified at post time)
- Modify: `CLAUDE.md` (repo map row for `bert/verify.py`; verifier paragraph after Pipeline Flow; `BERT_VERIFY_MODEL` env var)

- [ ] Steps: edit docs → commit `docs: verifier stage in skills + CLAUDE.md`

### Task 6: full verification + PR

- [ ] Run entire test suite with the primary venv; fix any fallout
- [ ] Push branch, open PR to main

---

## Amendment (Cassidy via check-in session, 2026-07-20): verify → REPAIR → re-verify

### Task 7: bounded repair loop

**Files:**
- Create: `prompts/repair_system_prompt.txt`
- Modify: `bert/verify.py`, `bert/fanout.py`
- Test: `tests/test_bert_verify.py`, `tests/test_bert_autosend_tag.py`

**Interfaces:**
- `verify.repairable(findings) -> bool` — non-empty and every finding has `fix_type == "rewrite"` (the verifier prompt is updated so "rewrite" means "fully fixable from the provided policies/brief/context"; external-fact, human-action, and consolidation findings get other fix_types).
- `verify.repair_draft(client, result, ctx, brief, policies, findings, *, model=None) -> str` — one Claude call applying ONLY the findings' fixes; JSON `{"draft_reply": ...}`; raises on unusable output.
- `fanout.verify_and_tag` loop: while verdict is MINOR/ERROR, findings are repairable, and repairs < 2 → find draft threads (break if none), repair, `pipeline.update_draft` in place, mutate `result["draft_reply"]`, re-verify (prelint, then model). Tag only if the FINAL verdict is SEND_AS_IS.
- Output/status gains `initial_verdict`, `initial_findings`, `repairs` → `apply_result` status keys `verify_initial_verdict`, `verify_initial_findings`, `verify_repairs` (so the scorecard can distinguish "clean on first pass" from "dirty → repaired → clean").
- Class I (siblings/consolidate) and any non-`rewrite` finding: no repair, no tag, finding surfaced.

- [ ] Failing tests → implement → suite green → commit → update skill docs/CLAUDE.md → PR
