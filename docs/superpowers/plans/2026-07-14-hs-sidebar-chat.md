# Help Scout Sidebar Chat Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the deployed Help Scout sidebar app into a per-ticket chat with Bert that can revise/create the HS draft, propose policy updates applied on agent confirmation (live apply + GitHub commit + Notion sync), and send-and-close the conversation — while deleting the webhook and Maven entry points.

**Architecture:** Two new modules do the real work — `sidebar_chat.py` (in-memory chat sessions + Anthropic tool loop reusing `bert/pipeline.py` seams) and `policy_updater.py` (proposal validation, atomic live apply, GitHub Contents API commit, Notion sync). `sidebar_server.py` is rewritten around five chat endpoints and serves a static chat frontend. Spec: `docs/superpowers/specs/2026-07-14-hs-sidebar-chat-design.md`.

**Tech Stack:** Python 3.11+, FastAPI, requests, anthropic SDK (`claude-sonnet-5`, prompt caching), vanilla-JS frontend (no build step), pytest with `unittest.mock`.

## Global Constraints

- Prompts live in `prompts/*.txt`, never inline in Python. Policy knowledge lives in `policies/*.md`, never in code.
- All sidebar write endpoints verify `SIDEBAR_SECRET` with `hmac.compare_digest`. The message poll (GET) also requires the secret (chat bodies contain account data; conversation ids are guessable).
- Draft HTML is clean `<p>` paragraphs (same convention as `draft_reply`).
- New env vars: `HELPSCOUT_AGENT_USER_ID` (falls back to `HELPSCOUT_NOTE_USER_ID`), `GITHUB_TOKEN`, `GITHUB_REPO` (default `cassidystagnitti/SupportAgent`), `GITHUB_BRANCH` (default `main`).
- GitHub commits are path-restricted to `policies/*.md` and the commit message ends with `[skip render]` so Render does not redeploy.
- Notion sync is fail-soft (warn); GitHub commit failure rolls back the live file.
- The postMessage context handshake in the sidebar HTML is preserved **verbatim** — do not touch its origin checks or message shapes.
- `batch_maven_drafts.py` is a *Claude* batch runner despite its name — do NOT delete it. Maven deletions are exactly: `maven_orchestrator.py`, `tests/test_maven_orchestrator.py`, the `mavenagi` requirement, and Maven references inside `sidebar_server.py`.
- Run tests with `python3 -m pytest tests/<file> -v` from the repo root.

## File Structure

| File | Action | Responsibility |
|---|---|---|
| `policy_updater.py` | Create | Proposal build/validate, atomic live apply, GitHub commit + rollback, Notion sync |
| `sidebar_chat.py` | Create | SessionStore, hydration, chat system blocks, tools, `run_turn` loop |
| `prompts/sidebar_chat_system_prompt.txt` | Create | Bert chat persona + tool guidance |
| `sidebar_server.py` | Rewrite | FastAPI endpoints: sidebar serving, chat, confirm/dismiss, send-and-close |
| `static/sidebar.html` | Create | Chat frontend (handshake + chat pane + diff cards + send button) |
| `scripts/__init__.py` | Create | Makes `scripts.sync_new_policy_docs` importable |
| `webhook_server.py`, `maven_orchestrator.py`, `tests/test_maven_orchestrator.py` | Delete | Sunset |
| `requirements.txt` | Modify | Drop `mavenagi>=1.2.13` |
| `tests/test_policy_updater.py`, `tests/test_sidebar_chat.py` | Create | Unit tests |
| `tests/test_sidebar.py` | Rewrite | Server endpoint tests |
| `CLAUDE.md` | Modify | Repo map, flow, env vars |

---

### Task 1: `policy_updater.py` — proposals and edit application

**Files:**
- Create: `policy_updater.py`
- Test: `tests/test_policy_updater.py`

**Interfaces:**
- Produces: `ProposalError(ValueError)`; `build_proposal(*, policy_file: str, edit_type: str, target_text: str, new_text: str, rationale: str) -> dict` returning `{id, policy_file, edit_type, target_text, new_text, rationale, diff, status: "pending"}`; `_apply_edit(content: str, edit_type: str, target_text: str, new_text: str) -> str`; `_policy_path(policy_file: str) -> str`; module constant `POLICIES_DIR`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_policy_updater.py`:

```python
import os

import pytest

import policy_updater
from policy_updater import ProposalError


@pytest.fixture()
def policies_dir(tmp_path, monkeypatch):
    d = tmp_path / "policies"
    d.mkdir()
    (d / "refunds.md").write_text(
        "# Refunds\n\n# Summary\nWe refund within 30 days.\n", encoding="utf-8"
    )
    monkeypatch.setattr(policy_updater, "POLICIES_DIR", str(d))
    return d


def test_build_proposal_replace_produces_diff(policies_dir):
    p = policy_updater.build_proposal(
        policy_file="refunds.md",
        edit_type="replace",
        target_text="We refund within 30 days.",
        new_text="We refund within 45 days.",
        rationale="Policy changed 2026-07-14",
    )
    assert p["status"] == "pending"
    assert p["policy_file"] == "refunds.md"
    assert "-We refund within 30 days." in p["diff"]
    assert "+We refund within 45 days." in p["diff"]
    assert len(p["id"]) == 12


def test_build_proposal_append(policies_dir):
    p = policy_updater.build_proposal(
        policy_file="refunds.md",
        edit_type="append",
        target_text="",
        new_text="# New Section\nStuff.",
        rationale="r",
    )
    assert "+# New Section" in p["diff"]


def test_replace_requires_unique_target(policies_dir):
    (policies_dir / "refunds.md").write_text("dup\ndup\n", encoding="utf-8")
    with pytest.raises(ProposalError, match="2 times"):
        policy_updater.build_proposal(
            policy_file="refunds.md", edit_type="replace",
            target_text="dup", new_text="x", rationale="r",
        )


def test_replace_missing_target_rejected(policies_dir):
    with pytest.raises(ProposalError, match="not found"):
        policy_updater.build_proposal(
            policy_file="refunds.md", edit_type="replace",
            target_text="no such text", new_text="x", rationale="r",
        )


def test_unknown_file_and_traversal_rejected(policies_dir):
    with pytest.raises(ProposalError):
        policy_updater.build_proposal(
            policy_file="nope.md", edit_type="append",
            target_text="", new_text="x", rationale="r",
        )
    with pytest.raises(ProposalError):
        policy_updater.build_proposal(
            policy_file="../CLAUDE.md", edit_type="append",
            target_text="", new_text="x", rationale="r",
        )


def test_unknown_edit_type_rejected(policies_dir):
    with pytest.raises(ProposalError, match="edit_type"):
        policy_updater.build_proposal(
            policy_file="refunds.md", edit_type="delete",
            target_text="", new_text="x", rationale="r",
        )


def test_apply_edit_append_normalizes_trailing_newline():
    out = policy_updater._apply_edit("body\n", "append", "", "tail")
    assert out.endswith("tail\n")
    assert "\n\ntail" in out
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_policy_updater.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'policy_updater'`

- [ ] **Step 3: Write the implementation**

Create `policy_updater.py`:

```python
"""Confirmed policy/knowledge updates from the sidebar chat.

Bert proposes an edit to a policies/*.md doc via the propose_policy_update
tool; the support agent confirms it in the sidebar. On confirm this module
applies the edit to the LIVE policy copy (atomic write), commits the file to
the GitHub repo (path-restricted, "[skip render]" so Render doesn't redeploy),
and syncs the Notion page. Notion failure is warn-only; GitHub failure rolls
the live file back.

See docs/superpowers/specs/2026-07-14-hs-sidebar-chat-design.md §2.
"""

from __future__ import annotations

import base64
import difflib
import logging
import os
import tempfile
import uuid

import requests

log = logging.getLogger("policy_updater")

_SUPPORT_DIR = os.path.dirname(os.path.abspath(__file__))
POLICIES_DIR = os.path.join(_SUPPORT_DIR, "policies")
GITHUB_API = "https://api.github.com"


class ProposalError(ValueError):
    """A proposal is invalid (bad file, missing/ambiguous target, bad edit_type)."""


def _policy_path(policy_file: str) -> str:
    base = os.path.basename(str(policy_file or "").strip())
    if not base or not base.endswith(".md"):
        raise ProposalError(f"{policy_file!r} is not a policies/*.md file")
    path = os.path.join(POLICIES_DIR, base)
    if not os.path.isfile(path):
        raise ProposalError(f"policies/{base} does not exist")
    return path


def _apply_edit(content: str, edit_type: str, target_text: str, new_text: str) -> str:
    if edit_type == "replace":
        if not target_text:
            raise ProposalError("replace requires target_text")
        n = content.count(target_text)
        if n == 0:
            raise ProposalError("target_text not found in the current policy file")
        if n > 1:
            raise ProposalError(f"target_text occurs {n} times — must be unique")
        return content.replace(target_text, new_text, 1)
    if edit_type == "append":
        sep = "" if content.endswith("\n\n") else ("\n" if content.endswith("\n") else "\n\n")
        return content + sep + new_text.strip() + "\n"
    raise ProposalError(f"unknown edit_type {edit_type!r} (want replace|append)")


def build_proposal(*, policy_file: str, edit_type: str, target_text: str,
                   new_text: str, rationale: str) -> dict:
    """Validate and register a proposed edit. Raises ProposalError; applies nothing."""
    path = _policy_path(policy_file)
    with open(path, encoding="utf-8") as f:
        current = f.read()
    updated = _apply_edit(current, edit_type, target_text, new_text)
    name = f"policies/{os.path.basename(path)}"
    diff = "".join(difflib.unified_diff(
        current.splitlines(keepends=True), updated.splitlines(keepends=True),
        fromfile=name, tofile=name,
    ))
    return {
        "id": uuid.uuid4().hex[:12],
        "policy_file": os.path.basename(path),
        "edit_type": edit_type,
        "target_text": target_text,
        "new_text": new_text,
        "rationale": rationale,
        "diff": diff,
        "status": "pending",
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_policy_updater.py -v`
Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
git add policy_updater.py tests/test_policy_updater.py
git commit -m "feat(policy): proposal build/validate for sidebar knowledge updates"
```

---

### Task 2: `policy_updater.py` — confirm flow (live apply, GitHub commit, rollback, Notion)

**Files:**
- Modify: `policy_updater.py`
- Create: `scripts/__init__.py` (empty file)
- Test: `tests/test_policy_updater.py` (extend)

**Interfaces:**
- Consumes: Task 1's `_policy_path`, `_apply_edit`.
- Produces: `confirm_proposal(proposal: dict, *, conversation_id: str) -> dict` returning `{"commit_sha": str, "notion_warning": str | None}` and setting `proposal["status"]` to `"confirmed"` (or leaving `"pending"` + raising on commit failure); `commit_policy_file(policy_file: str, content: str, message: str) -> str` (commit sha); `sync_policy_to_notion(path: str) -> None` (raises on failure — caller decides fail-soft); `_atomic_write(path: str, content: str) -> None`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_policy_updater.py`:

```python
from unittest.mock import MagicMock, patch


def _resp(status, payload=None):
    r = MagicMock()
    r.status_code = status
    r.json.return_value = payload or {}
    if status >= 400:
        r.raise_for_status.side_effect = requests.HTTPError(f"HTTP {status}")
    else:
        r.raise_for_status.return_value = None
    return r


import requests  # noqa: E402  (used by _resp)


@pytest.fixture()
def github_env(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "tok")
    monkeypatch.setenv("GITHUB_REPO", "owner/repo")
    monkeypatch.setenv("GITHUB_BRANCH", "main")


def test_commit_policy_file_happy_path(github_env):
    with patch("policy_updater.requests.get") as g, patch("policy_updater.requests.put") as p:
        g.return_value = _resp(200, {"sha": "oldsha"})
        p.return_value = _resp(200, {"commit": {"sha": "newsha"}})
        sha = policy_updater.commit_policy_file("refunds.md", "content", "msg\n\n[skip render]")
    assert sha == "newsha"
    url = p.call_args[0][0]
    assert url.endswith("/repos/owner/repo/contents/policies/refunds.md")
    body = p.call_args[1]["json"]
    assert body["sha"] == "oldsha"
    assert body["branch"] == "main"
    import base64
    assert base64.b64decode(body["content"]).decode() == "content"


def test_commit_policy_file_retries_on_conflict(github_env):
    with patch("policy_updater.requests.get") as g, patch("policy_updater.requests.put") as p:
        g.side_effect = [_resp(200, {"sha": "s1"}), _resp(200, {"sha": "s2"})]
        p.side_effect = [_resp(409), _resp(200, {"commit": {"sha": "done"}})]
        sha = policy_updater.commit_policy_file("refunds.md", "c", "m")
    assert sha == "done"
    assert p.call_count == 2


def test_commit_policy_file_rejects_non_policy_path(github_env):
    with pytest.raises(ValueError):
        policy_updater.commit_policy_file("evil.py", "c", "m")


def test_commit_requires_token(monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    with pytest.raises(RuntimeError, match="GITHUB_TOKEN"):
        policy_updater.commit_policy_file("refunds.md", "c", "m")


def test_confirm_proposal_applies_and_commits(policies_dir, github_env):
    p = policy_updater.build_proposal(
        policy_file="refunds.md", edit_type="replace",
        target_text="We refund within 30 days.", new_text="We refund within 45 days.",
        rationale="changed",
    )
    with patch("policy_updater.commit_policy_file", return_value="abc1234def") as c, \
         patch("policy_updater.sync_policy_to_notion") as n:
        out = policy_updater.confirm_proposal(p, conversation_id="123")
    assert out["commit_sha"] == "abc1234def"
    assert out["notion_warning"] is None
    assert p["status"] == "confirmed"
    live = (policies_dir / "refunds.md").read_text(encoding="utf-8")
    assert "45 days" in live
    msg = c.call_args[0][2]
    assert "[skip render]" in msg
    assert "conversation/123" in msg
    n.assert_called_once()


def test_confirm_rolls_back_live_file_when_commit_fails(policies_dir, github_env):
    p = policy_updater.build_proposal(
        policy_file="refunds.md", edit_type="replace",
        target_text="We refund within 30 days.", new_text="XX",
        rationale="r",
    )
    with patch("policy_updater.commit_policy_file", side_effect=RuntimeError("gh down")):
        with pytest.raises(RuntimeError, match="gh down"):
            policy_updater.confirm_proposal(p, conversation_id="1")
    live = (policies_dir / "refunds.md").read_text(encoding="utf-8")
    assert "30 days" in live          # rolled back
    assert p["status"] == "pending"   # still confirmable


def test_confirm_notion_failure_is_warn_only(policies_dir, github_env):
    p = policy_updater.build_proposal(
        policy_file="refunds.md", edit_type="append",
        target_text="", new_text="tail", rationale="r",
    )
    with patch("policy_updater.commit_policy_file", return_value="sha"), \
         patch("policy_updater.sync_policy_to_notion", side_effect=RuntimeError("no token")):
        out = policy_updater.confirm_proposal(p, conversation_id="1")
    assert p["status"] == "confirmed"
    assert "Notion sync failed" in out["notion_warning"]


def test_confirm_fails_loudly_on_drift(policies_dir, github_env):
    p = policy_updater.build_proposal(
        policy_file="refunds.md", edit_type="replace",
        target_text="We refund within 30 days.", new_text="XX", rationale="r",
    )
    (policies_dir / "refunds.md").write_text("# Refunds\nsomething else\n", encoding="utf-8")
    with pytest.raises(ProposalError, match="not found"):
        policy_updater.confirm_proposal(p, conversation_id="1")
    assert p["status"] == "pending"
```

- [ ] **Step 2: Run tests to verify the new ones fail**

Run: `python3 -m pytest tests/test_policy_updater.py -v`
Expected: Task 1 tests pass; new tests FAIL with `AttributeError: ... has no attribute 'commit_policy_file'`

- [ ] **Step 3: Write the implementation**

Create the empty package marker:

```bash
touch scripts/__init__.py
```

Append to `policy_updater.py`:

```python
def _atomic_write(path: str, content: str) -> None:
    """tmp file in the same directory + os.replace — same pattern as the registries."""
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _github_config() -> tuple[str, str, str]:
    token = (os.getenv("GITHUB_TOKEN") or "").strip()
    if not token:
        raise RuntimeError("GITHUB_TOKEN not configured — cannot commit policy updates")
    repo = (os.getenv("GITHUB_REPO") or "cassidystagnitti/SupportAgent").strip()
    branch = (os.getenv("GITHUB_BRANCH") or "main").strip()
    return token, repo, branch


def commit_policy_file(policy_file: str, content: str, message: str) -> str:
    """Commit policies/<file> via the GitHub Contents API. Returns the commit sha.

    Hard path restriction: only basenames ending in .md, always under policies/.
    On a sha conflict (another commit landed between GET and PUT) refetches the
    sha and retries once.
    """
    base = os.path.basename(str(policy_file))
    if not base.endswith(".md"):
        raise ValueError("only policies/*.md may be committed from the sidebar")
    token, repo, branch = _github_config()
    url = f"{GITHUB_API}/repos/{repo}/contents/policies/{base}"
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}
    body = {
        "message": message,
        "content": base64.b64encode(content.encode("utf-8")).decode("ascii"),
        "branch": branch,
    }
    for attempt in range(2):
        r_get = requests.get(url, headers=headers, params={"ref": branch}, timeout=30)
        if r_get.status_code == 200:
            body["sha"] = r_get.json()["sha"]
        elif r_get.status_code == 404:
            body.pop("sha", None)  # new file
        else:
            r_get.raise_for_status()
        r_put = requests.put(url, headers=headers, json=body, timeout=30)
        if r_put.status_code in (200, 201):
            return r_put.json()["commit"]["sha"]
        if r_put.status_code in (409, 422) and attempt == 0:
            log.warning("policy commit conflict for %s — refetching sha and retrying", base)
            continue
        r_put.raise_for_status()
    raise RuntimeError(f"unable to commit policies/{base} after retry")


def sync_policy_to_notion(path: str) -> None:
    """Sync one policy file to its Notion child page. Raises on any failure —
    the caller (confirm_proposal) treats Notion as fail-soft."""
    if not (os.getenv("NOTION_TOKEN") or "").strip():
        raise RuntimeError("NOTION_TOKEN not configured")
    from scripts.sync_new_policy_docs import (
        SUPPORT_POLICY_DOCS_PAGE_ID,
        _notion_headers,
        sync_doc,
    )
    s = requests.Session()
    s.headers.update(_notion_headers())
    sync_doc(s, SUPPORT_POLICY_DOCS_PAGE_ID, path)


def confirm_proposal(proposal: dict, *, conversation_id: str) -> dict:
    """Apply a pending proposal: live apply -> GitHub commit -> Notion sync.

    Re-validates the edit against the CURRENT file (drift fails loudly).
    GitHub failure rolls the live file back and re-raises (proposal stays
    pending / retryable). Notion failure only produces a warning string.
    """
    path = _policy_path(proposal["policy_file"])
    with open(path, encoding="utf-8") as f:
        current = f.read()
    updated = _apply_edit(current, proposal["edit_type"],
                          proposal["target_text"], proposal["new_text"])
    _atomic_write(path, updated)

    rationale = (proposal.get("rationale") or "").strip() or "policy update from sidebar chat"
    short = rationale.splitlines()[0][:60]
    message = (
        f"policy: {proposal['policy_file']} — {short}\n\n"
        f"{rationale}\n\n"
        f"Source: Help Scout conversation "
        f"https://secure.helpscout.net/conversation/{conversation_id}\n"
        f"Confirmed by a support agent via the sidebar chat.\n\n"
        f"[skip render]"
    )
    try:
        sha = commit_policy_file(proposal["policy_file"], updated, message)
    except BaseException:
        _atomic_write(path, current)  # roll back the live copy
        raise

    notion_warning = None
    try:
        sync_policy_to_notion(path)
    except Exception as e:
        notion_warning = (
            f"Committed ({sha[:7]}), but Notion sync failed: {str(e)[:200]} — "
            f"sync policies/{proposal['policy_file']} to Notion manually."
        )
        log.warning("Notion sync failed for %s: %s", path, e)

    proposal["status"] = "confirmed"
    return {"commit_sha": sha, "notion_warning": notion_warning}
```

Note: `SUPPORT_POLICY_DOCS_PAGE_ID` is imported from `scripts/sync_new_policy_docs.py`. If that constant has a different name there, check with `grep -n "356cffdf" scripts/sync_new_policy_docs.py` and import/alias the actual name — do not hardcode a second copy of the ID.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_policy_updater.py -v`
Expected: all pass (15 tests)

- [ ] **Step 5: Commit**

```bash
git add policy_updater.py scripts/__init__.py tests/test_policy_updater.py
git commit -m "feat(policy): confirm flow — live apply, GitHub commit w/ rollback, fail-soft Notion sync"
```

---

### Task 3: `sidebar_chat.py` — SessionStore

**Files:**
- Create: `sidebar_chat.py`
- Test: `tests/test_sidebar_chat.py`

**Interfaces:**
- Produces: `SessionStore` with `get_or_create(cid) -> dict`, `peek(cid) -> dict | None`, `try_acquire(cid) -> tuple[dict, bool]`, `release(cid) -> None`, `add_ui_message(cid, kind, text="", payload=None) -> dict`, `ui_messages_after(cid, after: int) -> list`; module-level `STORE = SessionStore()`. Session dict keys: `api_messages, ui_messages, next_seq, ctx, draft_thread_id, draft_text, proposals, busy, created_at`. UI message dict: `{seq, kind, text, payload, ts}` with `kind ∈ user|bert|event|proposal|error`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_sidebar_chat.py`:

```python
import pytest

import sidebar_chat
from sidebar_chat import SessionStore


def test_get_or_create_initializes_session():
    s = SessionStore()
    sess = s.get_or_create("101")
    assert sess["busy"] is False
    assert sess["ctx"] is None
    assert sess["proposals"] == {}
    assert s.get_or_create("101") is sess  # same object back


def test_lru_eviction():
    s = SessionStore(max_sessions=2)
    s.get_or_create("1")
    s.get_or_create("2")
    s.get_or_create("1")   # touch 1 so 2 is oldest
    s.get_or_create("3")   # evicts 2
    assert s.peek("2") is None
    assert s.peek("1") is not None
    assert s.peek("3") is not None


def test_try_acquire_and_release():
    s = SessionStore()
    _, ok1 = s.try_acquire("7")
    _, ok2 = s.try_acquire("7")
    assert ok1 is True
    assert ok2 is False
    s.release("7")
    _, ok3 = s.try_acquire("7")
    assert ok3 is True


def test_ui_messages_sequence_and_after():
    s = SessionStore()
    s.get_or_create("5")
    m1 = s.add_ui_message("5", "user", "hi")
    m2 = s.add_ui_message("5", "bert", "hello")
    assert (m1["seq"], m2["seq"]) == (1, 2)
    tail = s.ui_messages_after("5", after=1)
    assert [m["seq"] for m in tail] == [2]
    assert s.ui_messages_after("5", after=0)[0]["text"] == "hi"
    assert s.ui_messages_after("nope", after=0) == []


def test_add_ui_message_payload_roundtrip():
    s = SessionStore()
    s.get_or_create("9")
    m = s.add_ui_message("9", "proposal", payload={"proposal_id": "abc", "status": "pending"})
    assert m["payload"]["proposal_id"] == "abc"
    assert m["kind"] == "proposal"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_sidebar_chat.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'sidebar_chat'`

- [ ] **Step 3: Write the implementation**

Create `sidebar_chat.py`:

```python
"""Per-conversation chat sessions with Bert for the Help Scout sidebar.

In-memory only (mirrors sidebar_server's old _status pattern): history is
lost on restart, which is fine — context rehydrates on demand and everything
the chat *does* (drafts, commits, sent replies) persists in Help Scout,
GitHub, and Notion.

See docs/superpowers/specs/2026-07-14-hs-sidebar-chat-design.md §1.
"""

from __future__ import annotations

import logging
import os
import threading
from datetime import datetime, timezone

log = logging.getLogger("sidebar_chat")

_SUPPORT_DIR = os.path.dirname(os.path.abspath(__file__))

MODEL = os.getenv("SIDEBAR_CHAT_MODEL", "claude-sonnet-5")
MAX_SESSIONS = 200
MAX_TOOL_ITERATIONS = 8
CHAT_SYSTEM_PROMPT_PATH = os.path.join(_SUPPORT_DIR, "prompts", "sidebar_chat_system_prompt.txt")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class SessionStore:
    """Thread-safe, LRU-capped map of conversation id -> chat session."""

    def __init__(self, max_sessions: int = MAX_SESSIONS):
        self._sessions: dict[str, dict] = {}
        self._lock = threading.Lock()
        self._max = max_sessions

    def _new_session(self) -> dict:
        return {
            "api_messages": [],
            "ui_messages": [],
            "next_seq": 1,
            "ctx": None,
            "draft_thread_id": None,
            "draft_text": "",
            "proposals": {},
            "busy": False,
            "created_at": _now_iso(),
        }

    def _get_or_create_locked(self, cid: str) -> dict:
        cid = str(cid)
        if cid in self._sessions:
            self._sessions[cid] = self._sessions.pop(cid)  # refresh LRU position
            return self._sessions[cid]
        sess = self._new_session()
        self._sessions[cid] = sess
        while len(self._sessions) > self._max:
            self._sessions.pop(next(iter(self._sessions)))
        return sess

    def get_or_create(self, cid: str) -> dict:
        with self._lock:
            return self._get_or_create_locked(cid)

    def peek(self, cid: str) -> dict | None:
        with self._lock:
            return self._sessions.get(str(cid))

    def try_acquire(self, cid: str) -> tuple[dict, bool]:
        """Reserve the session for one worker turn. (session, acquired)."""
        with self._lock:
            sess = self._get_or_create_locked(cid)
            if sess["busy"]:
                return sess, False
            sess["busy"] = True
            return sess, True

    def release(self, cid: str) -> None:
        with self._lock:
            sess = self._sessions.get(str(cid))
            if sess is not None:
                sess["busy"] = False

    def add_ui_message(self, cid: str, kind: str, text: str = "", payload: dict | None = None) -> dict:
        with self._lock:
            sess = self._get_or_create_locked(cid)
            msg = {
                "seq": sess["next_seq"],
                "kind": kind,
                "text": text,
                "payload": payload,
                "ts": _now_iso(),
            }
            sess["next_seq"] += 1
            sess["ui_messages"].append(msg)
            return msg

    def ui_messages_after(self, cid: str, after: int) -> list:
        with self._lock:
            sess = self._sessions.get(str(cid))
            if sess is None:
                return []
            return [dict(m) for m in sess["ui_messages"] if m["seq"] > after]


STORE = SessionStore()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_sidebar_chat.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add sidebar_chat.py tests/test_sidebar_chat.py
git commit -m "feat(chat): thread-safe LRU session store for sidebar chat"
```

---

### Task 4: chat system prompt + hydration + context block

**Files:**
- Create: `prompts/sidebar_chat_system_prompt.txt`
- Modify: `sidebar_chat.py`
- Test: `tests/test_sidebar_chat.py` (extend)

**Interfaces:**
- Consumes: `bert.pipeline.hydrate_ticket(session, cid) -> dict`, `bert.pipeline.find_draft_threads(session, cid) -> list`, `orchestrator.get_access_token()`, `triage_tickets._fetch_all_threads(session, cid)`.
- Produces: `hydrate(session_data: dict, cid: str) -> None` (fills `ctx`, `draft_thread_id`, `draft_text`); `_hs_session() -> requests.Session`; `_context_block(session_data) -> str`; `_load_chat_prompt() -> str`; `_agent_user_id() -> int | None`.

- [ ] **Step 1: Create the system prompt file**

Create `prompts/sidebar_chat_system_prompt.txt`:

```text
You are Bert, Happier Meditation's AI support agent, chatting with a HUMAN SUPPORT TEAMMATE inside the Help Scout sidebar for one specific ticket. You are never talking to the customer here — the teammate is.

You have the full ticket context: the conversation, customer account data, Stripe billing data, the current draft reply (if any), and every support policy document.

How to behave in chat:
- Keep replies short and skimmable — the sidebar is about 350px wide. A few plain sentences. No headers, no long bullet dumps unless asked.
- Answer questions about the ticket, the account, the policies, and why the current draft says what it says.
- If you can't verify something from the context or policies, say so plainly instead of guessing.

Changing the customer reply:
- ANY change to the reply goes through the update_draft tool with the complete new draft as clean <p> HTML paragraphs. Never paste draft text into the chat — the draft lives in the Help Scout reply editor.
- Draft voice: write like a real human support person — warm, casual, plain language. No "I hope this email finds you well", no "I understand your frustration", no corporate or AI-sounding filler. Short paragraphs.
- "Guest Pass" is the customer-facing name for the referral feature — never write "referral" in a draft.

Updating team knowledge:
- When the chat establishes a policy fact that is missing or wrong in the policy docs (a bug status changed, a rule clarified, an edge case settled), call propose_policy_update with a precise, minimal edit and a clear rationale.
- The proposal is NOT applied — it renders as a diff card the teammate must Confirm. Never claim a policy update is done; say it's waiting for their confirmation.

What you cannot do:
- You cannot send the reply or close the ticket. The teammate has a Send & close button for that.
- You cannot make Stripe changes (refunds, coupons, cancellations). If one is needed, say so and it goes on the ticket's action list for a human.
```

- [ ] **Step 2: Write the failing tests**

Append to `tests/test_sidebar_chat.py`:

```python
from unittest.mock import MagicMock, patch


CTX = {
    "conversation_id": 555,
    "subject": "Refund please",
    "customer_name": "Ana",
    "hs_customer_id": 42,
    "email": "ana@x.com",
    "body": "I want a refund",
    "conversation_history": "",
    "reply_mode": False,
    "account_blob": "ACCOUNT-DATA",
    "stripe_block": "STRIPE-DATA",
    "stripe_ctx": None,
    "existing_tags": [],
}


def test_hydrate_fills_ctx_draft_and_text():
    sess = {"ctx": None, "draft_thread_id": None, "draft_text": ""}
    threads = [
        {"id": 900, "type": "message", "state": "draft", "body": "<p>draft body</p>"},
        {"id": 800, "type": "customer", "state": "published", "body": "hi"},
    ]
    with patch("sidebar_chat._hs_session", return_value=MagicMock()), \
         patch("sidebar_chat.bert_pipeline") as bp, \
         patch("sidebar_chat.triage_tickets") as tt:
        bp.hydrate_ticket.return_value = dict(CTX)
        bp.find_draft_threads.return_value = [900]
        tt._fetch_all_threads.return_value = threads
        sidebar_chat.hydrate(sess, "555")
    assert sess["ctx"]["subject"] == "Refund please"
    assert sess["draft_thread_id"] == 900
    assert sess["draft_text"] == "<p>draft body</p>"


def test_hydrate_no_draft():
    sess = {"ctx": None, "draft_thread_id": None, "draft_text": ""}
    with patch("sidebar_chat._hs_session", return_value=MagicMock()), \
         patch("sidebar_chat.bert_pipeline") as bp:
        bp.hydrate_ticket.return_value = dict(CTX)
        bp.find_draft_threads.return_value = []
        sidebar_chat.hydrate(sess, "555")
    assert sess["draft_thread_id"] is None
    assert sess["draft_text"] == ""


def test_context_block_contains_all_sections():
    sess = {"ctx": dict(CTX), "draft_thread_id": 900, "draft_text": "<p>d</p>"}
    block = sidebar_chat._context_block(sess)
    for expected in ("Refund please", "ana@x.com", "ACCOUNT-DATA", "STRIPE-DATA", "<p>d</p>"):
        assert expected in block


def test_context_block_no_draft_placeholder():
    sess = {"ctx": dict(CTX), "draft_thread_id": None, "draft_text": ""}
    assert "(no draft yet)" in sidebar_chat._context_block(sess)


def test_load_chat_prompt_reads_file():
    text = sidebar_chat._load_chat_prompt()
    assert "update_draft" in text
    assert "propose_policy_update" in text


def test_agent_user_id_fallback(monkeypatch):
    monkeypatch.delenv("HELPSCOUT_AGENT_USER_ID", raising=False)
    monkeypatch.setenv("HELPSCOUT_NOTE_USER_ID", "777")
    assert sidebar_chat._agent_user_id() == 777
    monkeypatch.setenv("HELPSCOUT_AGENT_USER_ID", "888")
    assert sidebar_chat._agent_user_id() == 888
    monkeypatch.delenv("HELPSCOUT_AGENT_USER_ID", raising=False)
    monkeypatch.delenv("HELPSCOUT_NOTE_USER_ID", raising=False)
    assert sidebar_chat._agent_user_id() is None
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_sidebar_chat.py -v`
Expected: Task 3 tests pass; new tests FAIL with `AttributeError: module 'sidebar_chat' has no attribute 'hydrate'`

- [ ] **Step 4: Write the implementation**

Add to `sidebar_chat.py` (imports at top, functions after `STORE`):

```python
import requests

import draft_registry
import orchestrator
import triage_tickets
from bert import pipeline as bert_pipeline
```

```python
def _hs_session() -> requests.Session:
    token = orchestrator.get_access_token()
    s = requests.Session()
    s.headers.update({"Authorization": f"Bearer {token}"})
    return s


def _agent_user_id() -> int | None:
    raw = (os.getenv("HELPSCOUT_AGENT_USER_ID") or os.getenv("HELPSCOUT_NOTE_USER_ID") or "").strip()
    return int(raw) if raw.isdigit() else None


def _thread_body(hs, cid: int, thread_id) -> str:
    for t in triage_tickets._fetch_all_threads(hs, int(cid)):
        if t.get("id") == thread_id:
            return t.get("body") or ""
    return ""


def hydrate(session_data: dict, cid: str) -> None:
    """Populate ctx + live draft info. Read-only against Help Scout."""
    hs = _hs_session()
    session_data["ctx"] = bert_pipeline.hydrate_ticket(hs, int(cid))
    draft_ids = bert_pipeline.find_draft_threads(hs, int(cid))
    thread_id = draft_ids[-1] if draft_ids else None  # newest live draft wins
    session_data["draft_thread_id"] = thread_id
    session_data["draft_text"] = _thread_body(hs, int(cid), thread_id) if thread_id else ""


def _load_chat_prompt() -> str:
    with open(CHAT_SYSTEM_PROMPT_PATH, encoding="utf-8") as f:
        return f.read()


def _context_block(session_data: dict) -> str:
    ctx = session_data["ctx"]
    draft = session_data.get("draft_text") or "(no draft yet)"
    reply_mode = ("yes — an agent already replied; address the customer's latest message"
                  if ctx.get("reply_mode") else "no — first response to this ticket")
    return "\n\n".join([
        f"=== TICKET #{ctx['conversation_id']}: {ctx['subject']} ===",
        f"Customer: {ctx['customer_name']} <{ctx.get('email') or 'unknown'}>",
        f"Reply mode: {reply_mode}",
        "=== CONVERSATION ===",
        ctx.get("conversation_history") or ctx.get("body") or "(empty)",
        "=== ACCOUNT ===",
        ctx.get("account_blob") or "(unavailable)",
        "=== STRIPE ===",
        ctx.get("stripe_block") or "(unavailable)",
        "=== CURRENT DRAFT (in the Help Scout reply editor) ===",
        draft,
    ])
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_sidebar_chat.py -v`
Expected: 11 passed

- [ ] **Step 6: Commit**

```bash
git add prompts/sidebar_chat_system_prompt.txt sidebar_chat.py tests/test_sidebar_chat.py
git commit -m "feat(chat): hydration, context block, and Bert chat system prompt"
```

---

### Task 5: `sidebar_chat.py` — tools and the `run_turn` loop

**Files:**
- Modify: `sidebar_chat.py`
- Test: `tests/test_sidebar_chat.py` (extend)

**Interfaces:**
- Consumes: Task 1's `policy_updater.build_proposal` / `ProposalError`; Task 4's `hydrate`, `_context_block`, `_hs_session`, `_agent_user_id`; `bert.pipeline.update_draft(session, cid, thread_id, text)`; `orchestrator._helpscout_post(session, url, payload)`, `orchestrator.BASE_URL`, `orchestrator.load_policy_docs()`; `draft_registry.set(cid, thread_id, drafted_at)`.
- Produces: `run_turn(store: SessionStore, cid: str, user_text: str, client=None) -> None` — caller must hold the busy flag; always releases it. `TOOLS` (Anthropic tool schema list). `_handle_update_draft(store, cid, session_data, html) -> str`, `_handle_propose_policy(store, cid, session_data, args: dict) -> str`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_sidebar_chat.py`:

```python
from types import SimpleNamespace


def _text_block(text):
    return SimpleNamespace(type="text", text=text)


def _tool_block(name, tool_input, block_id="tu_1"):
    return SimpleNamespace(type="tool_use", name=name, input=tool_input, id=block_id)


class FakeClient:
    """Yields queued fake responses; records requests."""
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []
        outer = self

        class _Messages:
            def create(self, **kwargs):
                outer.calls.append(kwargs)
                return outer._responses.pop(0)

        self.messages = _Messages()


def _store_with_hydrated_session(cid="555", thread_id=900):
    store = SessionStore()
    sess = store.get_or_create(cid)
    sess["ctx"] = dict(CTX)
    sess["draft_thread_id"] = thread_id
    sess["draft_text"] = "<p>old</p>"
    sess["busy"] = True  # run_turn expects the busy flag already held
    return store, sess


def test_run_turn_plain_text_reply():
    store, sess = _store_with_hydrated_session()
    client = FakeClient([SimpleNamespace(content=[_text_block("Because policy X.")])])
    with patch("sidebar_chat.orchestrator") as o:
        o.load_policy_docs.return_value = "POLICIES"
        sidebar_chat.run_turn(store, "555", "why does the draft say that?", client=client)
    kinds = [m["kind"] for m in store.ui_messages_after("555", 0)]
    assert kinds == ["user", "bert"]
    assert sess["busy"] is False
    # system blocks: prompt (cached), policies (cached), context (uncached)
    system = client.calls[0]["system"]
    assert len(system) == 3
    assert system[0]["cache_control"] == {"type": "ephemeral"}
    assert system[1]["cache_control"] == {"type": "ephemeral"}
    assert "cache_control" not in system[2]


def test_run_turn_update_existing_draft():
    store, sess = _store_with_hydrated_session()
    client = FakeClient([
        SimpleNamespace(content=[_tool_block("update_draft", {"html": "<p>new</p>"})]),
        SimpleNamespace(content=[_text_block("Done — draft updated.")]),
    ])
    with patch("sidebar_chat.orchestrator") as o, \
         patch("sidebar_chat.bert_pipeline") as bp, \
         patch("sidebar_chat._hs_session", return_value=MagicMock()):
        o.load_policy_docs.return_value = "P"
        sidebar_chat.run_turn(store, "555", "shorten the draft", client=client)
        bp.update_draft.assert_called_once()
        args = bp.update_draft.call_args[0]
        assert args[1] == 555 and args[2] == 900 and args[3] == "<p>new</p>"
    assert sess["draft_text"] == "<p>new</p>"
    kinds = [m["kind"] for m in store.ui_messages_after("555", 0)]
    assert "event" in kinds  # "Draft updated" chip


def test_run_turn_creates_draft_with_agent_user(monkeypatch):
    monkeypatch.setenv("HELPSCOUT_AGENT_USER_ID", "321")
    store, sess = _store_with_hydrated_session(thread_id=None)
    sess["draft_text"] = ""
    client = FakeClient([
        SimpleNamespace(content=[_tool_block("update_draft", {"html": "<p>fresh</p>"})]),
        SimpleNamespace(content=[_text_block("Drafted.")]),
    ])
    post_resp = MagicMock()
    post_resp.headers = {"Resource-ID": "1234"}
    with patch("sidebar_chat.orchestrator") as o, \
         patch("sidebar_chat._hs_session", return_value=MagicMock()), \
         patch("sidebar_chat.draft_registry") as reg:
        o.load_policy_docs.return_value = "P"
        o.BASE_URL = "https://api.helpscout.net/v2"
        o._helpscout_post.return_value = post_resp
        sidebar_chat.run_turn(store, "555", "draft a reply", client=client)
        payload = o._helpscout_post.call_args[0][2]
        assert payload["draft"] is True
        assert payload["user"] == 321
        assert payload["customer"] == {"id": 42}
        reg.set.assert_called_once()
    assert sess["draft_thread_id"] == "1234"


def test_run_turn_proposal_registered_not_applied():
    store, sess = _store_with_hydrated_session()
    client = FakeClient([
        SimpleNamespace(content=[_tool_block("propose_policy_update", {
            "policy_file": "refunds.md", "edit_type": "append",
            "new_text": "new fact", "rationale": "settled in chat",
        })]),
        SimpleNamespace(content=[_text_block("Proposed — waiting for your confirm.")]),
    ])
    with patch("sidebar_chat.orchestrator") as o, \
         patch("sidebar_chat.policy_updater") as pu:
        o.load_policy_docs.return_value = "P"
        pu.build_proposal.return_value = {
            "id": "abc123", "policy_file": "refunds.md", "edit_type": "append",
            "target_text": "", "new_text": "new fact", "rationale": "settled in chat",
            "diff": "+new fact", "status": "pending",
        }
        pu.ProposalError = Exception
        sidebar_chat.run_turn(store, "555", "update the policy", client=client)
    assert "abc123" in sess["proposals"]
    proposal_msgs = [m for m in store.ui_messages_after("555", 0) if m["kind"] == "proposal"]
    assert len(proposal_msgs) == 1
    assert proposal_msgs[0]["payload"]["proposal_id"] == "abc123"


def test_run_turn_tool_exception_reported_and_busy_released():
    store, sess = _store_with_hydrated_session()
    client = FakeClient([
        SimpleNamespace(content=[_tool_block("update_draft", {"html": "<p>x</p>"})]),
        SimpleNamespace(content=[_text_block("Sorry, that failed.")]),
    ])
    with patch("sidebar_chat.orchestrator") as o, \
         patch("sidebar_chat.bert_pipeline") as bp, \
         patch("sidebar_chat._hs_session", return_value=MagicMock()):
        o.load_policy_docs.return_value = "P"
        bp.update_draft.side_effect = RuntimeError("HS down")
        sidebar_chat.run_turn(store, "555", "edit", client=client)
    assert sess["busy"] is False
    assert any(m["kind"] == "error" for m in store.ui_messages_after("555", 0))


def test_run_turn_iteration_cap():
    store, sess = _store_with_hydrated_session()
    responses = [
        SimpleNamespace(content=[_tool_block("update_draft", {"html": f"<p>{i}</p>"}, f"tu_{i}")])
        for i in range(sidebar_chat.MAX_TOOL_ITERATIONS)
    ]
    client = FakeClient(responses)
    with patch("sidebar_chat.orchestrator") as o, \
         patch("sidebar_chat.bert_pipeline"), \
         patch("sidebar_chat._hs_session", return_value=MagicMock()):
        o.load_policy_docs.return_value = "P"
        sidebar_chat.run_turn(store, "555", "loop forever", client=client)
    msgs = store.ui_messages_after("555", 0)
    assert any(m["kind"] == "error" and "tool steps" in m["text"] for m in msgs)
    assert sess["busy"] is False


def test_run_turn_hydrates_when_ctx_missing():
    store = SessionStore()
    sess = store.get_or_create("777")
    sess["busy"] = True
    client = FakeClient([SimpleNamespace(content=[_text_block("hi")])])

    def fake_hydrate(session_data, cid):
        session_data["ctx"] = dict(CTX)
        session_data["draft_thread_id"] = None
        session_data["draft_text"] = ""

    with patch("sidebar_chat.orchestrator") as o, \
         patch("sidebar_chat.hydrate", side_effect=fake_hydrate) as h:
        o.load_policy_docs.return_value = "P"
        sidebar_chat.run_turn(store, "777", "hello", client=client)
        h.assert_called_once()
    assert sess["ctx"] is not None


def test_run_turn_top_level_failure_reports_error():
    store = SessionStore()
    sess = store.get_or_create("888")
    sess["busy"] = True
    with patch("sidebar_chat.hydrate", side_effect=RuntimeError("HS auth failed")):
        sidebar_chat.run_turn(store, "888", "hello", client=FakeClient([]))
    assert sess["busy"] is False
    msgs = store.ui_messages_after("888", 0)
    assert any(m["kind"] == "error" for m in msgs)
    assert sess["ctx"] is None  # next message retries hydration
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_sidebar_chat.py -v`
Expected: earlier tests pass; new tests FAIL with `AttributeError: module 'sidebar_chat' has no attribute 'run_turn'`

- [ ] **Step 3: Write the implementation**

Add to `sidebar_chat.py` (new imports at top):

```python
import anthropic

import policy_updater
```

Then the tools and loop:

```python
TOOLS = [
    {
        "name": "update_draft",
        "description": (
            "Replace the Help Scout draft reply for this ticket with new HTML "
            "(clean <p> paragraphs). Creates the draft if none exists. Use this for "
            "ANY change to the customer reply — never paste a draft into chat."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "html": {"type": "string",
                         "description": "The complete draft reply as clean <p> HTML paragraphs."},
            },
            "required": ["html"],
        },
    },
    {
        "name": "propose_policy_update",
        "description": (
            "Propose an edit to a policy doc in policies/. NOT applied — it renders as a "
            "diff card the support agent must confirm. Use when the chat establishes a "
            "policy fact that is missing or wrong in the docs."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "policy_file": {"type": "string",
                                "description": "Basename of an existing policies/*.md file, e.g. 'known-bugs.md'."},
                "edit_type": {"type": "string", "enum": ["replace", "append"]},
                "target_text": {"type": "string",
                                "description": "replace only: exact text to replace — must occur exactly once."},
                "new_text": {"type": "string",
                             "description": "Replacement text (replace) or block to append (append)."},
                "rationale": {"type": "string",
                              "description": "Why this update is correct; shown to the agent and used in the commit message."},
            },
            "required": ["policy_file", "edit_type", "new_text", "rationale"],
        },
    },
]


def _handle_update_draft(store: SessionStore, cid: str, session_data: dict, html: str) -> str:
    html = (html or "").strip()
    if not html:
        return "update_draft failed: empty html"
    hs = _hs_session()
    thread_id = session_data.get("draft_thread_id")
    if thread_id:
        bert_pipeline.update_draft(hs, int(cid), int(thread_id), html)
        session_data["draft_text"] = html
        store.add_ui_message(cid, "event", "Draft updated — refresh the reply editor to see it.")
        return "Draft updated in place in the Help Scout reply editor."

    ctx = session_data["ctx"]
    payload: dict = {"customer": {"id": int(ctx["hs_customer_id"])}, "text": html, "draft": True}
    agent_user = _agent_user_id()
    if agent_user:
        payload["user"] = agent_user
    r = orchestrator._helpscout_post(hs, f"{orchestrator.BASE_URL}/conversations/{cid}/reply", payload)
    r.raise_for_status()
    rid = r.headers.get("Resource-ID") or r.headers.get("resource-id")
    if rid:
        draft_registry.set(str(cid), rid, _now_iso())
        session_data["draft_thread_id"] = rid
    session_data["draft_text"] = html
    store.add_ui_message(cid, "event", "Draft created — open the reply editor to see it.")
    return "Draft created in the Help Scout reply editor."


def _handle_propose_policy(store: SessionStore, cid: str, session_data: dict, args: dict) -> str:
    try:
        proposal = policy_updater.build_proposal(
            policy_file=args.get("policy_file", ""),
            edit_type=args.get("edit_type", ""),
            target_text=args.get("target_text") or "",
            new_text=args.get("new_text") or "",
            rationale=args.get("rationale") or "",
        )
    except policy_updater.ProposalError as e:
        return f"Proposal rejected: {e}"
    session_data["proposals"][proposal["id"]] = proposal
    store.add_ui_message(cid, "proposal", payload={
        "proposal_id": proposal["id"],
        "policy_file": proposal["policy_file"],
        "diff": proposal["diff"],
        "rationale": proposal["rationale"],
        "status": "pending",
    })
    return (
        "Proposal registered and shown to the agent as a diff card — it is NOT applied yet. "
        "Tell the agent it's waiting for their Confirm; do not claim the policy is updated."
    )


def run_turn(store: SessionStore, cid: str, user_text: str, client=None) -> None:
    """Run one chat turn. The caller must hold the session's busy flag; this
    function always releases it, and turns errors into visible chat messages."""
    cid = str(cid)
    session_data = store.get_or_create(cid)
    try:
        store.add_ui_message(cid, "user", user_text)
        if session_data.get("ctx") is None:
            store.add_ui_message(cid, "event", "Reading the ticket, account, and policies…")
            hydrate(session_data, cid)

        session_data["api_messages"].append({"role": "user", "content": user_text})
        if client is None:
            client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

        system_blocks = [
            {"type": "text", "text": _load_chat_prompt(),
             "cache_control": {"type": "ephemeral"}},
            {"type": "text",
             "text": f"=== POLICY DOCUMENTS ===\n{orchestrator.load_policy_docs()}\n",
             "cache_control": {"type": "ephemeral"}},
            {"type": "text", "text": _context_block(session_data)},
        ]

        for _ in range(MAX_TOOL_ITERATIONS):
            message = client.messages.create(
                model=MODEL,
                max_tokens=4096,
                system=system_blocks,
                tools=TOOLS,
                messages=session_data["api_messages"],
            )
            session_data["api_messages"].append({"role": "assistant", "content": message.content})
            text = "".join(
                b.text for b in message.content if getattr(b, "type", None) == "text"
            ).strip()
            if text:
                store.add_ui_message(cid, "bert", text)
            tool_uses = [b for b in message.content if getattr(b, "type", None) == "tool_use"]
            if not tool_uses:
                break
            results = []
            for tu in tool_uses:
                try:
                    if tu.name == "update_draft":
                        out = _handle_update_draft(store, cid, session_data,
                                                   (tu.input or {}).get("html", ""))
                    elif tu.name == "propose_policy_update":
                        out = _handle_propose_policy(store, cid, session_data, tu.input or {})
                    else:
                        out = f"Unknown tool: {tu.name}"
                except Exception as e:
                    log.exception("tool %s failed for cid=%s", tu.name, cid)
                    store.add_ui_message(cid, "error", f"{tu.name} failed: {str(e)[:200]}")
                    out = f"Tool failed: {e}"
                results.append({"type": "tool_result", "tool_use_id": tu.id, "content": out})
            session_data["api_messages"].append({"role": "user", "content": results})
        else:
            store.add_ui_message(
                cid, "error",
                "Stopped after too many tool steps — try a more specific ask.",
            )
    except Exception as e:
        log.exception("chat turn failed for cid=%s", cid)
        store.add_ui_message(cid, "error", f"Something went wrong: {str(e)[:200]}")
    finally:
        store.release(cid)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_sidebar_chat.py -v`
Expected: 19 passed

- [ ] **Step 5: Commit**

```bash
git add sidebar_chat.py tests/test_sidebar_chat.py
git commit -m "feat(chat): Anthropic tool loop — update_draft + propose_policy_update"
```

---

### Task 6: `sidebar_server.py` rewrite — chat endpoints, Maven/trigger removal

**Files:**
- Modify: `sidebar_server.py` (rewrite)
- Test: `tests/test_sidebar.py` (rewrite)

**Interfaces:**
- Consumes: `sidebar_chat.STORE`, `sidebar_chat.run_turn`, `policy_updater.confirm_proposal`.
- Produces: FastAPI `app` with `POST /chat/message`, `GET /chat/messages/{cid}`, `POST /chat/confirm-policy`, `POST /chat/dismiss-policy`, `GET /health`, and (Task 8) `GET|POST /sidebar`. Helper `_check_secret(supplied: str) -> None` (raises HTTPException 401/500).

The rewrite deletes: `_status`/`_set_status`/`_append_log`/`_get_status`, `_run_pipeline`, `/trigger-draft`, `/trigger-status`, the `maven_orchestrator`/`orchestrator.process_ticket_sync` imports, and `_SIDEBAR_HTML` (Task 8 replaces serving; until Task 8 lands, keep `_SIDEBAR_HTML` + `_render_sidebar` + the two `/sidebar` routes exactly as they are — this task only swaps the trigger machinery for chat endpoints).

- [ ] **Step 1: Rewrite the tests**

Replace the entire contents of `tests/test_sidebar.py`:

```python
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

import sidebar_chat
import sidebar_server


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setattr(sidebar_server, "SIDEBAR_SECRET", "testsecret")
    monkeypatch.setattr(sidebar_chat, "STORE", sidebar_chat.SessionStore())
    return TestClient(sidebar_server.app)


def test_chat_message_starts_turn(client):
    with patch("sidebar_server.threading.Thread") as t:
        resp = client.post("/chat/message", json={
            "conversation_id": "555", "text": "hi", "secret": "testsecret",
        })
    assert resp.status_code == 202
    t.assert_called_once()
    sess = sidebar_chat.STORE.peek("555")
    assert sess["busy"] is True  # acquired before the thread starts


def test_chat_message_bad_secret_401(client):
    resp = client.post("/chat/message", json={
        "conversation_id": "555", "text": "hi", "secret": "wrong",
    })
    assert resp.status_code == 401


def test_chat_message_busy_409(client):
    sidebar_chat.STORE.try_acquire("555")
    resp = client.post("/chat/message", json={
        "conversation_id": "555", "text": "hi", "secret": "testsecret",
    })
    assert resp.status_code == 409


def test_chat_message_validates_input(client):
    assert client.post("/chat/message", json={
        "conversation_id": "abc", "text": "hi", "secret": "testsecret",
    }).status_code == 400
    assert client.post("/chat/message", json={
        "conversation_id": "555", "text": "   ", "secret": "testsecret",
    }).status_code == 400


def test_poll_returns_messages_and_draft_state(client):
    sidebar_chat.STORE.get_or_create("555")
    sidebar_chat.STORE.add_ui_message("555", "user", "hi")
    sidebar_chat.STORE.add_ui_message("555", "bert", "hello")
    sess = sidebar_chat.STORE.peek("555")
    sess["draft_thread_id"] = 900

    resp = client.get("/chat/messages/555", params={"after": 1, "secret": "testsecret"})
    assert resp.status_code == 200
    data = resp.json()
    assert [m["seq"] for m in data["messages"]] == [2]
    assert data["busy"] is False
    assert data["draft"] == {"exists": True, "thread_id": 900}


def test_poll_requires_secret(client):
    assert client.get("/chat/messages/555", params={"after": 0}).status_code == 401


def test_poll_unknown_conversation_empty(client):
    resp = client.get("/chat/messages/999", params={"after": 0, "secret": "testsecret"})
    assert resp.json() == {"messages": [], "busy": False, "draft": {"exists": False, "thread_id": None}}


def test_poll_overlays_current_proposal_status(client):
    sidebar_chat.STORE.get_or_create("555")
    sess = sidebar_chat.STORE.peek("555")
    sess["proposals"]["p1"] = {"id": "p1", "status": "confirmed"}
    sidebar_chat.STORE.add_ui_message("555", "proposal", payload={
        "proposal_id": "p1", "diff": "+x", "rationale": "r", "status": "pending",
    })
    resp = client.get("/chat/messages/555", params={"after": 0, "secret": "testsecret"})
    msg = resp.json()["messages"][0]
    assert msg["payload"]["status"] == "confirmed"


def test_confirm_policy_happy_path(client):
    sidebar_chat.STORE.get_or_create("555")
    sess = sidebar_chat.STORE.peek("555")
    sess["proposals"]["p1"] = {"id": "p1", "policy_file": "refunds.md", "status": "pending"}
    with patch("sidebar_server.policy_updater.confirm_proposal",
               return_value={"commit_sha": "abcdef1234", "notion_warning": None}) as c:
        resp = client.post("/chat/confirm-policy", json={
            "conversation_id": "555", "proposal_id": "p1", "secret": "testsecret",
        })
    assert resp.status_code == 200
    assert resp.json()["commit_sha"] == "abcdef1234"
    c.assert_called_once()
    events = [m for m in sidebar_chat.STORE.ui_messages_after("555", 0) if m["kind"] == "event"]
    assert any("abcdef1" in m["text"] for m in events)


def test_confirm_policy_notion_warning_surfaces(client):
    sidebar_chat.STORE.get_or_create("555")
    sess = sidebar_chat.STORE.peek("555")
    sess["proposals"]["p1"] = {"id": "p1", "policy_file": "refunds.md", "status": "pending"}
    with patch("sidebar_server.policy_updater.confirm_proposal",
               return_value={"commit_sha": "abc", "notion_warning": "Notion sync failed"}):
        resp = client.post("/chat/confirm-policy", json={
            "conversation_id": "555", "proposal_id": "p1", "secret": "testsecret",
        })
    assert resp.status_code == 200
    errors = [m for m in sidebar_chat.STORE.ui_messages_after("555", 0) if m["kind"] == "error"]
    assert any("Notion" in m["text"] for m in errors)


def test_confirm_policy_failure_returns_502_and_keeps_pending(client):
    sidebar_chat.STORE.get_or_create("555")
    sess = sidebar_chat.STORE.peek("555")
    sess["proposals"]["p1"] = {"id": "p1", "policy_file": "refunds.md", "status": "pending"}
    with patch("sidebar_server.policy_updater.confirm_proposal",
               side_effect=RuntimeError("gh down")):
        resp = client.post("/chat/confirm-policy", json={
            "conversation_id": "555", "proposal_id": "p1", "secret": "testsecret",
        })
    assert resp.status_code == 502
    assert sess["proposals"]["p1"]["status"] == "pending"


def test_confirm_policy_unknown_proposal_404(client):
    resp = client.post("/chat/confirm-policy", json={
        "conversation_id": "555", "proposal_id": "nope", "secret": "testsecret",
    })
    assert resp.status_code == 404


def test_confirm_policy_already_confirmed_409(client):
    sidebar_chat.STORE.get_or_create("555")
    sess = sidebar_chat.STORE.peek("555")
    sess["proposals"]["p1"] = {"id": "p1", "policy_file": "r.md", "status": "confirmed"}
    resp = client.post("/chat/confirm-policy", json={
        "conversation_id": "555", "proposal_id": "p1", "secret": "testsecret",
    })
    assert resp.status_code == 409


def test_dismiss_policy(client):
    sidebar_chat.STORE.get_or_create("555")
    sess = sidebar_chat.STORE.peek("555")
    sess["proposals"]["p1"] = {"id": "p1", "policy_file": "r.md", "status": "pending"}
    resp = client.post("/chat/dismiss-policy", json={
        "conversation_id": "555", "proposal_id": "p1", "secret": "testsecret",
    })
    assert resp.status_code == 200
    assert sess["proposals"]["p1"]["status"] == "dismissed"


def test_trigger_endpoints_are_gone(client):
    assert client.post("/trigger-draft", json={}).status_code == 404
    assert client.get("/trigger-status/1").status_code == 404


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_sidebar.py -v`
Expected: FAIL (404s on /chat/*, old endpoints still present)

- [ ] **Step 3: Rewrite `sidebar_server.py`**

Replace the module docstring, imports, and everything between `SIDEBAR_SECRET = ...` and `_SIDEBAR_HTML` (delete `_status`, `_set_status`, `_append_log`, `_get_status`, `_run_pipeline`) and delete the `/trigger-draft` + `/trigger-status` routes. Keep `_SIDEBAR_HTML`, `_render_sidebar`, both `/sidebar` routes, and `/health` untouched for now (Task 8 revisits them). New content:

```python
"""
Help Scout Custom App sidebar — per-ticket chat with Bert.

Deploy as the Render start command:
  uvicorn sidebar_server:app --host 0.0.0.0 --port $PORT

Help Scout loads https://<render-host>/sidebar in the conversation-view iframe
(postMessage handshake supplies the conversation id). The page is a chat UI:
Bert answers with fully hydrated ticket context, edits the HS draft in place
via tool calls, proposes policy-doc updates as diff cards (Confirm commits to
GitHub + syncs Notion), and a Send & close button publishes the draft and
closes the conversation as the Support Automations agent user.

Environment:
  SIDEBAR_SECRET             — random string; required on every chat endpoint call
  HELPSCOUT_AGENT_USER_ID    — HS user for chat-created drafts (falls back to
                               HELPSCOUT_NOTE_USER_ID)
  GITHUB_TOKEN / GITHUB_REPO / GITHUB_BRANCH — policy-update commits
  (all other pipeline env vars apply as documented in CLAUDE.md)
"""

import hmac
import json  # still used by _render_sidebar, kept until Task 8
import logging
import os
import threading

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse

_SUPPORT_DIR = os.path.dirname(os.path.abspath(__file__))
_ROOT_DIR = os.path.dirname(_SUPPORT_DIR)
load_dotenv(os.path.join(_SUPPORT_DIR, ".env"))
load_dotenv(os.path.join(_ROOT_DIR, ".env"))

import policy_updater  # noqa: E402
import sidebar_chat  # noqa: E402

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("helpscout_sidebar")

SIDEBAR_SECRET = os.getenv("SIDEBAR_SECRET", "")

app = FastAPI(title="Help Scout sidebar app")


def _check_secret(supplied: str) -> None:
    if not SIDEBAR_SECRET:
        raise HTTPException(status_code=500, detail="SIDEBAR_SECRET not configured on server")
    if not hmac.compare_digest(str(supplied or ""), SIDEBAR_SECRET):
        raise HTTPException(status_code=401, detail="invalid secret")


def _require_cid(raw) -> str:
    cid = str(raw or "").strip()
    if not cid.isdigit():
        raise HTTPException(status_code=400, detail="conversation_id must be a numeric string")
    return cid


async def _json_body(request: Request) -> dict:
    try:
        return await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="invalid JSON body")


@app.post("/chat/message", status_code=202)
async def chat_message(request: Request):
    body = await _json_body(request)
    _check_secret(body.get("secret"))
    cid = _require_cid(body.get("conversation_id"))
    text = str(body.get("text") or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="text is required")

    _, acquired = sidebar_chat.STORE.try_acquire(cid)
    if not acquired:
        raise HTTPException(status_code=409, detail="Bert is still working on the last message")

    threading.Thread(
        target=sidebar_chat.run_turn,
        args=(sidebar_chat.STORE, cid, text),
        daemon=True,
    ).start()
    return {"ok": True, "conversation_id": cid, "status": "started"}


@app.get("/chat/messages/{cid}")
async def chat_messages(cid: str, after: int = 0, secret: str = ""):
    _check_secret(secret)
    cid = _require_cid(cid)
    sess = sidebar_chat.STORE.peek(cid)
    if sess is None:
        return {"messages": [], "busy": False, "draft": {"exists": False, "thread_id": None}}
    messages = sidebar_chat.STORE.ui_messages_after(cid, after)
    for m in messages:  # overlay live proposal status so reloads render correctly
        if m["kind"] == "proposal" and m.get("payload"):
            p = sess["proposals"].get(m["payload"].get("proposal_id"))
            if p:
                m["payload"] = dict(m["payload"], status=p["status"])
    thread_id = sess.get("draft_thread_id")
    return {
        "messages": messages,
        "busy": bool(sess.get("busy")),
        "draft": {"exists": thread_id is not None, "thread_id": thread_id},
    }


def _find_proposal(cid: str, proposal_id: str) -> dict:
    sess = sidebar_chat.STORE.peek(cid)
    proposal = (sess or {}).get("proposals", {}).get(str(proposal_id or ""))
    if proposal is None:
        raise HTTPException(status_code=404, detail="unknown proposal")
    return proposal


@app.post("/chat/confirm-policy")
async def confirm_policy(request: Request):
    body = await _json_body(request)
    _check_secret(body.get("secret"))
    cid = _require_cid(body.get("conversation_id"))
    proposal = _find_proposal(cid, body.get("proposal_id"))
    if proposal["status"] != "pending":
        raise HTTPException(status_code=409, detail=f"proposal is {proposal['status']}")
    try:
        outcome = policy_updater.confirm_proposal(proposal, conversation_id=cid)
    except Exception as e:
        log.exception("policy confirm failed for cid=%s", cid)
        sidebar_chat.STORE.add_ui_message(
            cid, "error", f"Policy update failed: {str(e)[:200]} — nothing was committed. Try Confirm again.")
        raise HTTPException(status_code=502, detail=str(e)[:300])
    sidebar_chat.STORE.add_ui_message(
        cid, "event",
        f"Policy updated: {proposal['policy_file']} committed ({outcome['commit_sha'][:7]}).")
    if outcome.get("notion_warning"):
        sidebar_chat.STORE.add_ui_message(cid, "error", outcome["notion_warning"])
    return {"ok": True, "commit_sha": outcome["commit_sha"],
            "notion_warning": outcome.get("notion_warning")}


@app.post("/chat/dismiss-policy")
async def dismiss_policy(request: Request):
    body = await _json_body(request)
    _check_secret(body.get("secret"))
    cid = _require_cid(body.get("conversation_id"))
    proposal = _find_proposal(cid, body.get("proposal_id"))
    proposal["status"] = "dismissed"
    return {"ok": True}


@app.get("/health")
async def health():
    return {"status": "ok"}
```

Note: `test_chat_message_starts_turn` asserts `busy is True` after the POST because `try_acquire` runs in the endpoint (before the mocked Thread would run). `run_turn` is responsible for releasing.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_sidebar.py tests/test_sidebar_chat.py -v`
Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add sidebar_server.py tests/test_sidebar.py
git commit -m "feat(sidebar): chat endpoints replace trigger-draft; Maven engine removed from server"
```

---

### Task 7: send & close endpoint

**Files:**
- Modify: `sidebar_server.py`
- Test: `tests/test_sidebar.py` (extend)

**Interfaces:**
- Consumes: `sidebar_chat._hs_session`, `bert.pipeline.find_draft_threads`, `bert.pipeline.conversation_status`, `triage_tickets._fetch_all_threads` (via `sidebar_chat._thread_body`), `orchestrator.BASE_URL`.
- Produces: `POST /chat/send` accepting `{conversation_id, secret, force?: bool, close_only?: bool}` returning `{ok, sent, closed, error?}`; helper `_normalize_html(s: str) -> str` in `sidebar_server.py`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_sidebar.py`:

```python
def _send_setup(draft_ids=(900,), status="active", live_body="<p>d</p>", sess_draft="<p>d</p>"):
    """Patch context for /chat/send tests. Returns the patch context managers."""
    hs = MagicMock()
    hs.patch.return_value = MagicMock(status_code=204, raise_for_status=MagicMock())
    sess = sidebar_chat.STORE.get_or_create("555")
    sess["draft_text"] = sess_draft
    p1 = patch("sidebar_server.sidebar_chat._hs_session", return_value=hs)
    p2 = patch("sidebar_server.bert_pipeline")
    return hs, p1, p2, draft_ids, status, live_body


def test_send_happy_path_publishes_then_closes(client):
    hs, p1, p2, draft_ids, status, live_body = _send_setup()
    with p1, p2 as bp, patch("sidebar_server.sidebar_chat._thread_body", return_value=live_body):
        bp.find_draft_threads.return_value = list(draft_ids)
        bp.conversation_status.return_value = status
        resp = client.post("/chat/send", json={"conversation_id": "555", "secret": "testsecret"})
    assert resp.status_code == 200
    data = resp.json()
    assert data == {"ok": True, "sent": True, "closed": True}
    urls = [c[0][0] for c in hs.patch.call_args_list]
    assert urls[0].endswith("/conversations/555/threads/900/schedule")
    assert urls[1].endswith("/conversations/555")
    assert hs.patch.call_args_list[0][1]["json"] == {"op": "replace", "path": "/state", "value": "published"}
    assert hs.patch.call_args_list[1][1]["json"] == {"op": "replace", "path": "/status", "value": "closed"}
    events = [m["text"] for m in sidebar_chat.STORE.ui_messages_after("555", 0) if m["kind"] == "event"]
    assert any("sent" in t.lower() for t in events)


def test_send_no_draft_400(client):
    hs, p1, p2, *_ = _send_setup(draft_ids=())
    with p1, p2 as bp:
        bp.find_draft_threads.return_value = []
        bp.conversation_status.return_value = "active"
        resp = client.post("/chat/send", json={"conversation_id": "555", "secret": "testsecret"})
    assert resp.status_code == 400
    assert "draft" in resp.json()["detail"].lower()


def test_send_already_closed_400(client):
    hs, p1, p2, *_ = _send_setup(status="closed")
    with p1, p2 as bp:
        bp.find_draft_threads.return_value = [900]
        bp.conversation_status.return_value = "closed"
        resp = client.post("/chat/send", json={"conversation_id": "555", "secret": "testsecret"})
    assert resp.status_code == 400
    assert "closed" in resp.json()["detail"].lower()


def test_send_draft_mismatch_409_and_force_overrides(client):
    hs, p1, p2, *_ = _send_setup(live_body="<p>edited by human</p>", sess_draft="<p>chat version</p>")
    with p1, p2 as bp, patch("sidebar_server.sidebar_chat._thread_body",
                             return_value="<p>edited by human</p>"):
        bp.find_draft_threads.return_value = [900]
        bp.conversation_status.return_value = "active"
        resp = client.post("/chat/send", json={"conversation_id": "555", "secret": "testsecret"})
        assert resp.status_code == 409
        resp2 = client.post("/chat/send", json={
            "conversation_id": "555", "secret": "testsecret", "force": True,
        })
        assert resp2.status_code == 200


def test_send_close_failure_reports_partial(client):
    hs, p1, p2, *_ = _send_setup()
    publish_ok = MagicMock(status_code=204, raise_for_status=MagicMock())
    close_fail = MagicMock()
    close_fail.raise_for_status.side_effect = RuntimeError("HS 500")
    hs.patch.side_effect = [publish_ok, close_fail]
    with p1, p2 as bp, patch("sidebar_server.sidebar_chat._thread_body", return_value="<p>d</p>"):
        bp.find_draft_threads.return_value = [900]
        bp.conversation_status.return_value = "active"
        resp = client.post("/chat/send", json={"conversation_id": "555", "secret": "testsecret"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["sent"] is True and data["closed"] is False
    assert "error" in data


def test_send_close_only_retry(client):
    hs, p1, p2, *_ = _send_setup()
    with p1, p2 as bp:
        bp.find_draft_threads.return_value = []      # draft already published
        bp.conversation_status.return_value = "active"
        resp = client.post("/chat/send", json={
            "conversation_id": "555", "secret": "testsecret", "close_only": True,
        })
    assert resp.status_code == 200
    assert resp.json()["closed"] is True
    urls = [c[0][0] for c in hs.patch.call_args_list]
    assert len(urls) == 1 and urls[0].endswith("/conversations/555")


def test_send_mismatch_check_skipped_when_no_session_draft(client):
    hs, p1, p2, *_ = _send_setup(sess_draft="")
    with p1, p2 as bp:
        bp.find_draft_threads.return_value = [900]
        bp.conversation_status.return_value = "active"
        resp = client.post("/chat/send", json={"conversation_id": "555", "secret": "testsecret"})
    assert resp.status_code == 200
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_sidebar.py -v`
Expected: new tests FAIL with 404 on /chat/send

- [ ] **Step 3: Write the implementation**

Add imports to `sidebar_server.py`:

```python
import re

import orchestrator  # noqa: E402
from bert import pipeline as bert_pipeline  # noqa: E402
```

Add the endpoint:

```python
def _normalize_html(s: str) -> str:
    """Strip tags + whitespace so cosmetic HS normalization doesn't trip the guard."""
    return re.sub(r"<[^>]+>|\s+|&nbsp;", "", s or "")


@app.post("/chat/send")
async def chat_send(request: Request):
    body = await _json_body(request)
    _check_secret(body.get("secret"))
    cid = _require_cid(body.get("conversation_id"))
    force = bool(body.get("force"))
    close_only = bool(body.get("close_only"))

    hs = sidebar_chat._hs_session()
    status = bert_pipeline.conversation_status(hs, cid)
    if status == "closed":
        raise HTTPException(status_code=400, detail="conversation is already closed")

    sent = False
    if not close_only:
        draft_ids = bert_pipeline.find_draft_threads(hs, cid)
        if not draft_ids:
            raise HTTPException(status_code=400, detail="no draft to send on this conversation")
        thread_id = draft_ids[-1]

        sess = sidebar_chat.STORE.peek(cid)
        chat_draft = (sess or {}).get("draft_text") or ""
        if chat_draft and not force:
            live_body = sidebar_chat._thread_body(hs, int(cid), thread_id)
            if _normalize_html(live_body) != _normalize_html(chat_draft):
                raise HTTPException(
                    status_code=409,
                    detail="draft was edited outside this chat — review it, then Send anyway",
                )

        r_pub = hs.patch(
            f"{orchestrator.BASE_URL}/conversations/{cid}/threads/{thread_id}/schedule",
            json={"op": "replace", "path": "/state", "value": "published"},
        )
        r_pub.raise_for_status()
        sent = True

    try:
        r_close = hs.patch(
            f"{orchestrator.BASE_URL}/conversations/{cid}",
            json={"op": "replace", "path": "/status", "value": "closed"},
        )
        r_close.raise_for_status()
    except Exception as e:
        log.exception("close failed for cid=%s (sent=%s)", cid, sent)
        sidebar_chat.STORE.add_ui_message(
            cid, "error",
            f"Reply {'sent' if sent else 'not sent'}, but closing failed: {str(e)[:150]} — retry close.")
        return {"ok": False, "sent": sent, "closed": False, "error": str(e)[:300]}

    sidebar_chat.STORE.add_ui_message(
        cid, "event",
        "Reply sent and conversation closed." if sent else "Conversation closed.")
    return {"ok": True, "sent": sent, "closed": True}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_sidebar.py -v`
Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add sidebar_server.py tests/test_sidebar.py
git commit -m "feat(sidebar): send-and-close — publish draft thread, close conversation, mismatch guard"
```

---

### Task 8: frontend — `static/sidebar.html` + serving

**Files:**
- Create: `static/sidebar.html`
- Modify: `sidebar_server.py` (replace `_SIDEBAR_HTML` string with file loading)
- Test: `tests/test_sidebar.py` (extend)

**Interfaces:**
- Consumes: all Task 6/7 endpoints.
- Produces: `GET|POST /sidebar` serving the file with `__CID__/__EMAIL__/__SECRET__` injected (JSON-encoded, exactly like the old `_render_sidebar`).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_sidebar.py`:

```python
def test_sidebar_get_serves_static_html_with_injection(client):
    resp = client.get("/sidebar", params={"id": "123", "customer_email": "a@b.com"})
    assert resp.status_code == 200
    html = resp.text
    assert 'var CID    = "123"' in html or '"123"' in html
    assert "GET_APP_CONTEXT" in html          # handshake preserved
    assert "secure.helpscout.net" in html     # origin allowlist preserved
    assert "/chat/message" in html            # chat wiring present
    assert "__CID__" not in html              # injection happened


def test_sidebar_post_form_context(client):
    resp = client.post("/sidebar", data={"conversation[id]": "456", "customer[email]": "c@d.com"})
    assert resp.status_code == 200
    assert '"456"' in resp.text


def test_sidebar_post_rejects_missing_cid(client):
    resp = client.post("/sidebar", data={})
    assert resp.status_code == 400
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_sidebar.py -v`
Expected: `test_sidebar_get_serves_static_html_with_injection` FAILS (`/chat/message` not in the old HTML)

- [ ] **Step 3: Create `static/sidebar.html`**

The `<script>` handshake block (`ALLOWED_ORIGINS`, `isAllowed`, the `message` listener, and the `GET_APP_CONTEXT` postMessage) is copied **verbatim** from the current `_SIDEBAR_HTML`. Full file:

```html
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Bert</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  html, body { height: 100%; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    font-size: 13px; color: #333; background: #fff;
    display: flex; flex-direction: column; padding: 10px; gap: 8px;
  }
  #draft-card {
    display: flex; align-items: center; gap: 8px;
    padding: 8px 10px; border: 1px solid #e3e3e3; border-radius: 6px;
    background: #fafafa; font-size: 12px;
  }
  #draft-label { flex: 1; color: #555; }
  #btn-send {
    padding: 6px 10px; border: none; border-radius: 4px; cursor: pointer;
    background: #2e7d32; color: #fff; font-size: 12px; font-weight: 500;
  }
  #btn-send:disabled { opacity: 0.5; cursor: default; }
  #send-confirm { display: none; gap: 6px; align-items: center; }
  #send-confirm button { padding: 6px 8px; border: none; border-radius: 4px; cursor: pointer; font-size: 12px; }
  #btn-send-yes { background: #2e7d32; color: #fff; }
  #btn-send-no  { background: #e0e0e0; color: #333; }
  #chat {
    flex: 1; overflow-y: auto; display: flex; flex-direction: column; gap: 6px;
    padding: 4px 0; min-height: 120px;
  }
  .msg { max-width: 92%; padding: 7px 10px; border-radius: 10px; line-height: 1.45; white-space: pre-wrap; word-break: break-word; }
  .msg.user  { align-self: flex-end; background: #1f73b7; color: #fff; border-bottom-right-radius: 3px; }
  .msg.bert  { align-self: flex-start; background: #f1f1f1; color: #222; border-bottom-left-radius: 3px; }
  .chip { align-self: center; font-size: 11px; color: #777; background: #f5f5f5; border: 1px solid #e5e5e5; border-radius: 10px; padding: 3px 10px; text-align: center; }
  .chip.error { color: #c62828; background: #fff4f4; border-color: #f5c0c0; }
  .proposal { align-self: stretch; border: 1px solid #d8c46a; border-radius: 6px; background: #fffdf3; padding: 8px; font-size: 12px; }
  .proposal .file { font-weight: 600; margin-bottom: 4px; }
  .proposal pre {
    font-family: ui-monospace, Menlo, monospace; font-size: 11px; line-height: 1.5;
    background: #fff; border: 1px solid #eee; border-radius: 4px; padding: 6px;
    overflow-x: auto; margin: 6px 0; max-height: 180px; overflow-y: auto;
  }
  .proposal .dline-add { color: #2e7d32; }
  .proposal .dline-del { color: #c62828; }
  .proposal .rationale { color: #666; margin-bottom: 6px; }
  .proposal .actions { display: flex; gap: 6px; }
  .proposal .actions button { padding: 5px 10px; border: none; border-radius: 4px; cursor: pointer; font-size: 12px; }
  .proposal .btn-confirm { background: #1f73b7; color: #fff; }
  .proposal .btn-dismiss { background: #e0e0e0; color: #333; }
  .proposal .final { font-weight: 600; }
  .proposal .final.confirmed { color: #2e7d32; }
  .proposal .final.dismissed { color: #999; }
  #input-row { display: flex; gap: 6px; }
  #input-row textarea {
    flex: 1; resize: none; height: 54px; padding: 7px 9px; font: inherit;
    border: 1px solid #ccc; border-radius: 6px;
  }
  #btn-chat {
    padding: 0 14px; border: none; border-radius: 6px; cursor: pointer;
    background: #1f73b7; color: #fff; font-size: 12px; font-weight: 500;
  }
  #btn-chat:disabled, #input-row textarea:disabled { opacity: 0.55; cursor: default; }
  .spinner {
    display: inline-block; width: 11px; height: 11px;
    border: 2px solid currentColor; border-top-color: transparent; border-radius: 50%;
    animation: spin 0.7s linear infinite; vertical-align: middle; margin-right: 6px;
  }
  @keyframes spin { to { transform: rotate(360deg); } }
  #loading { font-size: 12px; color: #999; }
</style>
</head>
<body>
<div id="loading"><span class="spinner"></span>Connecting to Help Scout...</div>
<div id="ui" style="display:none; display:none; flex-direction:column; flex:1; gap:8px; min-height:0;">
  <div id="draft-card">
    <span id="draft-label">Checking for a draft…</span>
    <button id="btn-send" onclick="askSend()" style="display:none">Send &amp; close</button>
    <span id="send-confirm">
      Send reply &amp; close?
      <button id="btn-send-yes" onclick="doSend(false)">Send</button>
      <button id="btn-send-no" onclick="hideSendConfirm()">Cancel</button>
    </span>
  </div>
  <div id="chat"></div>
  <div id="input-row">
    <textarea id="input" placeholder="Ask Bert about this ticket…"></textarea>
    <button id="btn-chat" onclick="sendMessage()">Send</button>
  </div>
</div>
<script>
var CID    = __CID__;
var EMAIL  = __EMAIL__;
var SECRET = __SECRET__;
var lastSeq = 0;
var busy = false;
var pollTimer = null;
var draftExists = false;

if (CID) {
  ready(CID, EMAIL);
} else {
  var ALLOWED_ORIGINS = [
    'https://secure.helpscout.net',
    /^https:\/\/hs-app\..+\.hsenv\.io$/
  ];
  function isAllowed(origin) {
    return ALLOWED_ORIGINS.some(function(o) {
      return typeof o === 'string' ? o === origin : o.test(origin);
    });
  }
  window.addEventListener('message', function(event) {
    if (!isAllowed(event.origin)) return;
    var data = event.data;
    if (!data || data.type !== 'SEND_APP_CONTEXT') return;
    var cid = data.conversation && String(data.conversation.id);
    var emails = data.customer && data.customer.emails;
    var email = (emails && emails.length > 0 && emails[0].value) || '';
    if (cid) ready(cid, email);
  });
  var appId = (window.name || '').replace(/app-side-panel-|app-/, '');
  window.parent.postMessage(
    { type: 'GET_APP_CONTEXT', appId: appId, iframeId: window.name || '' },
    document.referrer || '*'
  );
}

function ready(cid, email) {
  CID = cid; EMAIL = email;
  document.getElementById('loading').style.display = 'none';
  var ui = document.getElementById('ui');
  ui.style.display = 'flex';
  document.getElementById('input').addEventListener('keydown', function(e) {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(); }
  });
  schedulePoll(0);
}

function esc(s) {
  var d = document.createElement('div');
  d.textContent = s == null ? '' : String(s);
  return d.innerHTML;
}

function setBusy(b) {
  busy = b;
  document.getElementById('input').disabled = b;
  document.getElementById('btn-chat').disabled = b;
}

async function sendMessage() {
  var input = document.getElementById('input');
  var text = input.value.trim();
  if (!text || busy) return;
  setBusy(true);
  try {
    var resp = await fetch('/chat/message', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ conversation_id: CID, customer_email: EMAIL, text: text, secret: SECRET })
    });
    if (resp.status === 409) { setBusy(true); schedulePoll(800); return; }
    if (!resp.ok) { addChip('Send failed: HTTP ' + resp.status, true); setBusy(false); return; }
    input.value = '';
    schedulePoll(400);
  } catch (e) {
    addChip('Network error: ' + e.message, true);
    setBusy(false);
  }
}

function schedulePoll(delay) {
  if (pollTimer) clearTimeout(pollTimer);
  pollTimer = setTimeout(poll, delay);
}

async function poll() {
  try {
    var resp = await fetch('/chat/messages/' + encodeURIComponent(CID) +
      '?after=' + lastSeq + '&secret=' + encodeURIComponent(SECRET));
    if (resp.ok) {
      var data = await resp.json();
      (data.messages || []).forEach(renderMessage);
      updateDraftCard(data.draft || {});
      setBusy(!!data.busy);
    }
  } catch (e) { /* network hiccup — keep polling */ }
  schedulePoll(busy ? 1500 : 10000);
}

function updateDraftCard(draft) {
  draftExists = !!draft.exists;
  document.getElementById('draft-label').textContent =
    draftExists ? 'Draft ready in the reply editor' : 'No draft on this ticket yet';
  document.getElementById('btn-send').style.display = draftExists ? '' : 'none';
}

function renderMessage(m) {
  if (m.seq <= lastSeq) return;
  lastSeq = m.seq;
  var chat = document.getElementById('chat');
  var el;
  if (m.kind === 'user' || m.kind === 'bert') {
    el = document.createElement('div');
    el.className = 'msg ' + m.kind;
    el.textContent = m.text;
  } else if (m.kind === 'proposal') {
    el = renderProposal(m.payload || {});
  } else {
    el = document.createElement('div');
    el.className = 'chip' + (m.kind === 'error' ? ' error' : '');
    el.textContent = m.text;
  }
  chat.appendChild(el);
  chat.scrollTop = chat.scrollHeight;
}

function renderProposal(p) {
  var el = document.createElement('div');
  el.className = 'proposal';
  el.id = 'proposal-' + p.proposal_id;
  var diffHtml = (p.diff || '').split('\n').map(function(line) {
    var cls = line.charAt(0) === '+' ? 'dline-add' : (line.charAt(0) === '-' ? 'dline-del' : '');
    return '<span class="' + cls + '">' + esc(line) + '</span>';
  }).join('\n');
  el.innerHTML =
    '<div class="file">Policy update: ' + esc(p.policy_file) + '</div>' +
    '<div class="rationale">' + esc(p.rationale) + '</div>' +
    '<pre>' + diffHtml + '</pre>' +
    '<div class="actions"></div>';
  setProposalState(el, p.proposal_id, p.status || 'pending');
  return el;
}

function setProposalState(el, id, status) {
  var actions = el.querySelector('.actions');
  if (status === 'pending') {
    actions.innerHTML =
      '<button class="btn-confirm" onclick="confirmProposal(\'' + id + '\')">Confirm — commit &amp; sync</button>' +
      '<button class="btn-dismiss" onclick="dismissProposal(\'' + id + '\')">Dismiss</button>';
  } else {
    actions.innerHTML = '<span class="final ' + esc(status) + '">' +
      (status === 'confirmed' ? '✓ Confirmed & committed' :
       status === 'dismissed' ? 'Dismissed' : esc(status)) + '</span>';
  }
}

async function confirmProposal(id) {
  var el = document.getElementById('proposal-' + id);
  el.querySelector('.actions').innerHTML = '<span class="spinner"></span> Committing…';
  try {
    var resp = await fetch('/chat/confirm-policy', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ conversation_id: CID, proposal_id: id, secret: SECRET })
    });
    setProposalState(el, id, resp.ok ? 'confirmed' : 'pending');
    if (!resp.ok) addChip('Policy update failed — see chat for details.', true);
  } catch (e) {
    setProposalState(el, id, 'pending');
    addChip('Network error: ' + e.message, true);
  }
  schedulePoll(300);
}

async function dismissProposal(id) {
  var el = document.getElementById('proposal-' + id);
  try {
    await fetch('/chat/dismiss-policy', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ conversation_id: CID, proposal_id: id, secret: SECRET })
    });
  } catch (e) { /* leave as-is */ }
  setProposalState(el, id, 'dismissed');
}

function addChip(text, isError) {
  var chat = document.getElementById('chat');
  var el = document.createElement('div');
  el.className = 'chip' + (isError ? ' error' : '');
  el.textContent = text;
  chat.appendChild(el);
  chat.scrollTop = chat.scrollHeight;
}

function askSend() {
  document.getElementById('btn-send').style.display = 'none';
  document.getElementById('send-confirm').style.display = 'flex';
}

function hideSendConfirm() {
  document.getElementById('send-confirm').style.display = 'none';
  document.getElementById('btn-send').style.display = draftExists ? '' : 'none';
}

async function doSend(force) {
  hideSendConfirm();
  var btn = document.getElementById('btn-send');
  btn.disabled = true;
  try {
    var resp = await fetch('/chat/send', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ conversation_id: CID, secret: SECRET, force: !!force })
    });
    var data = await resp.json().catch(function() { return {}; });
    if (resp.status === 409) {
      if (window.confirm('The draft was edited outside this chat. Send it anyway?')) {
        btn.disabled = false;
        return doSend(true);
      }
    } else if (!resp.ok) {
      addChip('Send failed: ' + (data.detail || ('HTTP ' + resp.status)), true);
    } else if (data.ok === false && data.sent) {
      addChip('Reply sent, but closing failed — retrying close…', true);
      await fetch('/chat/send', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ conversation_id: CID, secret: SECRET, close_only: true })
      });
    }
  } catch (e) {
    addChip('Network error: ' + e.message, true);
  }
  btn.disabled = false;
  schedulePoll(300);
}
</script>
</body>
</html>
```

- [ ] **Step 4: Update `sidebar_server.py` to serve the file**

Delete the `_SIDEBAR_HTML` string. Replace `_render_sidebar` with:

```python
import json  # add to imports

_SIDEBAR_HTML_PATH = os.path.join(_SUPPORT_DIR, "static", "sidebar.html")


def _render_sidebar(cid: str, email: str) -> HTMLResponse:
    with open(_SIDEBAR_HTML_PATH, encoding="utf-8") as f:
        html = f.read()
    html = (
        html
        .replace("__CID__", json.dumps(cid))
        .replace("__EMAIL__", json.dumps(email))
        .replace("__SECRET__", json.dumps(SIDEBAR_SECRET))
    )
    return HTMLResponse(html)
```

The two `/sidebar` routes stay byte-for-byte identical.

- [ ] **Step 5: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_sidebar.py -v`
Expected: all pass

- [ ] **Step 6: Commit**

```bash
git add static/sidebar.html sidebar_server.py tests/test_sidebar.py
git commit -m "feat(sidebar): chat frontend — messages, diff cards, send-and-close; HTML moved to static/"
```

---

### Task 9: sunset sweep + full suite

**Files:**
- Delete: `webhook_server.py`, `maven_orchestrator.py`, `tests/test_maven_orchestrator.py`
- Modify: `requirements.txt`, `test_run.py` (comment only)

- [ ] **Step 1: Verify nothing else imports the deleted modules**

Run: `grep -rn "webhook_server\|maven_orchestrator\|mavenagi" --include="*.py" . | grep -v ".venv"`
Expected: only the files being deleted (and `test_run.py`'s comment line mentioning `batch_maven_drafts.py`, which stays).

- [ ] **Step 2: Delete**

```bash
git rm webhook_server.py maven_orchestrator.py tests/test_maven_orchestrator.py
```

Remove the `mavenagi>=1.2.13` line from `requirements.txt`. In `test_run.py`, leave the code alone but fix the stale comment on line 3 if it references deleted files (it references `batch_maven_drafts.py`, which still exists — leave it).

- [ ] **Step 3: Run the FULL test suite**

Run: `python3 -m pytest tests/ -v`
Expected: everything passes; no import errors from the deletions.

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "chore: sunset webhook_server and Maven draft engine

The sidebar chat + Bert-via-Claude-Chat are now the only two interfaces.
batch_maven_drafts.py stays — despite the name it is the Claude batch runner."
```

---

### Task 10: CLAUDE.md update

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Update the repository map table**

Remove the `webhook_server.py` row. Add rows:

```markdown
| `sidebar_server.py` | Live | FastAPI app for the HS sidebar: serves the chat UI, chat endpoints, policy confirm, send-and-close |
| `sidebar_chat.py` | Live | Per-ticket chat sessions with Bert: hydration via bert/pipeline, Anthropic tool loop (update_draft, propose_policy_update) |
| `policy_updater.py` | Live | Confirmed policy updates: live apply + GitHub commit ([skip render]) + fail-soft Notion sync |
| `static/sidebar.html` | Live | Sidebar chat frontend (vanilla JS; postMessage context handshake) |
```

- [ ] **Step 2: Replace the Pipeline Flow section**

Replace the `Help Scout webhook → webhook_server.py …` diagram with:

```markdown
## Interfaces

There are exactly two ways tickets get worked:

1. **Bert via Claude Chat** (local) — the bert-morning-review skill family: summarize the
   mailbox, batch-draft with the standing brief, review, post drafts.
2. **Help Scout sidebar chat** (Render) — `sidebar_server.py` + `sidebar_chat.py`. An agent
   opens a conversation, chats with Bert (context rehydrated on demand via
   `bert/pipeline.hydrate_ticket`), Bert updates the HS draft in place via tool calls,
   proposes policy-doc updates as diff cards (Confirm → live apply + GitHub commit with
   `[skip render]` + Notion sync), and the agent can Send & close (publish draft thread →
   close conversation) as the Support Automations user.

The webhook auto-trigger (`webhook_server.py`) and the Maven draft engine were sunset
2026-07-14 (see docs/superpowers/specs/2026-07-14-hs-sidebar-chat-design.md).
```

- [ ] **Step 3: Update the environment variables section**

Remove the MavenAGI block (`MAVEN_ORG_ID`, `MAVEN_AGENT_ID`, `MAVEN_APP_ID`, `MAVEN_APP_SECRET`) — keep `MAVEN_API_BASE_URL`/`MAVEN_API_KEY` (Happier Maven API, still used by account context). Add:

```bash
# Sidebar chat (sidebar_server.py / sidebar_chat.py / policy_updater.py)
SIDEBAR_SECRET                # random string; gates every sidebar chat endpoint
HELPSCOUT_AGENT_USER_ID       # HS user id for chat-created drafts + send attribution;
                              # falls back to HELPSCOUT_NOTE_USER_ID
GITHUB_TOKEN                  # fine-grained PAT (contents:write, this repo only) for policy commits
GITHUB_REPO                   # default: cassidystagnitti/SupportAgent
GITHUB_BRANCH                 # default: main
```

Also remove the `AUTO_SEND_ENABLED` "Future" block's claim that everything only drafts if it now conflicts — keep the flag documented but note sends now happen via the sidebar's human-clicked Send & close button.

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: CLAUDE.md — two-interface architecture, sidebar chat env vars, Maven/webhook sunset"
```

---

### Task 11: live verification (acceptance)

No new files. Follow the spec's acceptance list. This task requires Cassidy's environment (.env with real keys).

- [ ] **Step 1: Boot locally**

```bash
lsof -ti:8765 | xargs kill -9 2>/dev/null; python3 -m uvicorn sidebar_server:app --port 8765
```

Open `http://127.0.0.1:8765/sidebar?id=<real-test-conversation-id>` in a browser.

- [ ] **Step 2: Chat + draft update**

Ask "what's this ticket about?" (context correct?), then "shorten the draft" — verify the draft thread changes in Help Scout.

- [ ] **Step 3: No-draft creation**

On a ticket with no draft: "draft a reply" — verify a draft appears in HS and the sender user on the thread is the Support Automations account (`HELPSCOUT_AGENT_USER_ID`).

- [ ] **Step 4: Policy proposal → confirm**

Tell Bert a new policy fact, get the diff card, Confirm. Verify: `policies/<file>.md` changed on disk, a commit landed on GitHub with `[skip render]` in the message, chat shows the Notion warning (token unset) or the Notion page updated.

- [ ] **Step 5: Send & close**

Click Send & close on the test conversation. Verify in Help Scout: reply sent to the (test) customer, conversation status closed, and the reply + close attributed to the Support Automations agent user. **If attribution is wrong**, add `"user": _agent_user_id()` handling to `bert.pipeline.post_draft` as described in the spec §4 and re-verify.

- [ ] **Step 6: Deploy + register**

Push the branch, merge/deploy to Render per the normal flow, then in Help Scout admin: confirm the app URL still points at `/sidebar`, and disable/deregister the webhook (manual, spec §6).
