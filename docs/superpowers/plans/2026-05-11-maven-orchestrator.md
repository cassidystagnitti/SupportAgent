# Maven Orchestrator + Sidebar Test Toggle — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Maven AGI–backed draft pipeline alongside the existing Claude pipeline, with two buttons in the Help Scout sidebar to toggle between engines and a live log panel for debugging.

**Architecture:** New `maven_orchestrator.py` mirrors `orchestrator.py` step-for-step (triage → account → Stripe → draft → HS post) but replaces the Claude call with `MavenAGI.conversation.initialize()` + `ask_stream()`. `sidebar_server.py` gains an `engine` param on `/trigger-draft`, routes to the right pipeline, and exposes per-run logs via `/trigger-status`. Classification fields Claude returns (escalate, confidence, etc.) are stubbed with safe defaults since Maven only returns plain text.

**Tech Stack:** Python 3.11+, `mavenagi` SDK (Fern-generated), FastAPI, pytest, unittest.mock

---

## File Map

| Action | Path | Responsibility |
|---|---|---|
| Create | `maven_orchestrator.py` | Full Maven pipeline; `process_maven_ticket_sync()` |
| Create | `tests/test_maven_orchestrator.py` | Unit tests for Maven client + draft call |
| Create | `tests/test_sidebar.py` | Unit tests for log infra + engine routing |
| Modify | `sidebar_server.py` | Log infra, engine routing, two-button UI |
| Modify | `requirements.txt` | Add `mavenagi` |

---

## Task 1: Add `mavenagi` to requirements and install

**Files:**
- Modify: `requirements.txt`

- [ ] **Step 1: Add dependency**

Open `requirements.txt` and append:

```
mavenagi
```

Full file after edit:
```
anthropic
requests
python-dotenv
fastapi
uvicorn[standard]
openai
numpy
stripe>=10.0.0
markdown
mavenagi
```

- [ ] **Step 2: Install**

```bash
pip install mavenagi
```

Expected: `Successfully installed mavenagi-X.Y.Z` (no errors)

- [ ] **Step 3: Verify import**

```bash
python -c "from mavenagi import MavenAGI; print('ok')"
```

Expected: `ok`

- [ ] **Step 4: Commit**

```bash
git add requirements.txt
git commit -m "feat: add mavenagi SDK dependency"
```

---

## Task 2: Create `maven_orchestrator.py` — client factory

**Files:**
- Create: `maven_orchestrator.py`
- Create: `tests/__init__.py`
- Create: `tests/test_maven_orchestrator.py`

- [ ] **Step 1: Create `tests/__init__.py`**

```bash
mkdir -p tests && touch tests/__init__.py
```

- [ ] **Step 2: Write failing test for `_maven_client()`**

Create `tests/test_maven_orchestrator.py`:

```python
import os
import pytest
from unittest.mock import patch, MagicMock


def test_maven_client_raises_when_env_missing():
    """_maven_client() raises RuntimeError if any of the four env vars is absent."""
    import importlib
    with patch.dict(os.environ, {}, clear=False):
        for key in ("MAVEN_ORG_ID", "MAVEN_AGENT_ID", "MAVEN_APP_ID", "MAVEN_APP_SECRET"):
            os.environ.pop(key, None)
        # Re-import to get a clean module state with env cleared
        import maven_orchestrator
        importlib.reload(maven_orchestrator)
        with pytest.raises(RuntimeError, match="Missing Maven env vars"):
            maven_orchestrator._maven_client()


def test_maven_client_returns_client_with_valid_env():
    """_maven_client() returns a MavenAGI instance when all env vars are set."""
    env = {
        "MAVEN_ORG_ID": "org1",
        "MAVEN_AGENT_ID": "agent1",
        "MAVEN_APP_ID": "app1",
        "MAVEN_APP_SECRET": "secret1",
    }
    with patch.dict(os.environ, env):
        with patch("maven_orchestrator.MavenAGI") as mock_cls:
            import maven_orchestrator
            maven_orchestrator._maven_client()
            mock_cls.assert_called_once_with(
                organization_id="org1",
                agent_id="agent1",
                app_id="app1",
                app_secret="secret1",
            )
```

- [ ] **Step 3: Run test to confirm it fails**

```bash
cd /Users/cassidystagnitti/code/code-happierMeditation/SupportAgent
python -m pytest tests/test_maven_orchestrator.py -v 2>&1 | head -30
```

Expected: `ERROR` or `ModuleNotFoundError` — `maven_orchestrator` doesn't exist yet

- [ ] **Step 4: Create `maven_orchestrator.py` with the client factory**

```python
"""Maven AGI support pipeline: triage → account → Stripe (optional) → Maven draft → Help Scout."""

from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timezone
from typing import Any, Callable, Optional

import requests
from dotenv import load_dotenv
from mavenagi import MavenAGI
from mavenagi.commons import EntityIdBase
from mavenagi.conversation.types.stream_response import StreamResponse_End, StreamResponse_Text

_SUPPORT_DIR = os.path.dirname(os.path.abspath(__file__))
_ROOT_DIR = os.path.dirname(_SUPPORT_DIR)
load_dotenv(os.path.join(_SUPPORT_DIR, ".env"))
load_dotenv(os.path.join(_ROOT_DIR, ".env"))

from account_context import fetch_account_contexts_for_ticket, fetch_customer_emails_from_helpscout  # noqa: E402
from orchestrator import (  # noqa: E402
    _customer_display_name,
    _customer_from_conversation,
    _extract_tag_names,
    _helpscout_post,
    _html_escape,
    _subscription_platform,
    _update_conversation_tags,
)
from product_prioritization import run_product_prioritization  # noqa: E402
from stripe_context import fetch_stripe_context, format_stripe_context  # noqa: E402
from triage_tickets import (  # noqa: E402
    BASE_URL,
    fetch_conversation,
    get_access_token,
    get_conversation_history,
    get_conversation_text,
    run_triage,
)

log = logging.getLogger("maven_orchestrator")


def _maven_client() -> MavenAGI:
    org_id = os.getenv("MAVEN_ORG_ID", "")
    agent_id = os.getenv("MAVEN_AGENT_ID", "")
    app_id = os.getenv("MAVEN_APP_ID", "")
    app_secret = os.getenv("MAVEN_APP_SECRET", "")
    missing = [k for k, v in {
        "MAVEN_ORG_ID": org_id,
        "MAVEN_AGENT_ID": agent_id,
        "MAVEN_APP_ID": app_id,
        "MAVEN_APP_SECRET": app_secret,
    }.items() if not v]
    if missing:
        raise RuntimeError(f"Missing Maven env vars: {', '.join(missing)}")
    return MavenAGI(
        organization_id=org_id,
        agent_id=agent_id,
        app_id=app_id,
        app_secret=app_secret,
    )
```

- [ ] **Step 5: Run test — should pass**

```bash
python -m pytest tests/test_maven_orchestrator.py::test_maven_client_raises_when_env_missing tests/test_maven_orchestrator.py::test_maven_client_returns_client_with_valid_env -v
```

Expected: `2 passed`

- [ ] **Step 6: Commit**

```bash
git add maven_orchestrator.py tests/__init__.py tests/test_maven_orchestrator.py
git commit -m "feat: add maven_orchestrator skeleton with _maven_client factory"
```

---

## Task 3: Implement `_call_maven_draft()`

**Files:**
- Modify: `maven_orchestrator.py` (append function)
- Modify: `tests/test_maven_orchestrator.py` (append tests)

- [ ] **Step 1: Append failing tests**

Add to the bottom of `tests/test_maven_orchestrator.py`:

```python
from mavenagi.conversation.types.stream_response import StreamResponse_Text, StreamResponse_End


def _make_text_event(contents: str) -> StreamResponse_Text:
    return StreamResponse_Text(contents=contents)


def _make_end_event(error=None) -> StreamResponse_End:
    return StreamResponse_End(error=error)


def test_call_maven_draft_concatenates_text_chunks():
    """_call_maven_draft() collects StreamResponse_Text chunks and joins them."""
    mock_client = MagicMock()
    mock_client.conversation.ask_stream.return_value = iter([
        _make_text_event("Hello "),
        _make_text_event("world!"),
        _make_end_event(),
    ])

    with patch("maven_orchestrator._maven_client", return_value=mock_client):
        import maven_orchestrator
        result = maven_orchestrator._call_maven_draft(
            conversation_id="123",
            subject="Test subject",
            ticket_body="Help me with my account",
            account_blob="Account Found: true",
            stripe_context="N/A",
        )

    assert result == "Hello world!"
    mock_client.conversation.initialize.assert_called_once()
    mock_client.conversation.ask_stream.assert_called_once()


def test_call_maven_draft_raises_on_stream_error():
    """_call_maven_draft() raises ValueError when StreamResponse_End carries an error."""
    mock_client = MagicMock()
    mock_error = MagicMock()
    mock_client.conversation.ask_stream.return_value = iter([
        _make_end_event(error=mock_error),
    ])

    with patch("maven_orchestrator._maven_client", return_value=mock_client):
        import maven_orchestrator
        with pytest.raises(ValueError, match="Maven stream error"):
            maven_orchestrator._call_maven_draft(
                conversation_id="123",
                subject="Test",
                ticket_body="Help",
                account_blob="",
                stripe_context="",
            )


def test_call_maven_draft_raises_on_empty_reply():
    """_call_maven_draft() raises ValueError when Maven returns no text chunks."""
    mock_client = MagicMock()
    mock_client.conversation.ask_stream.return_value = iter([_make_end_event()])

    with patch("maven_orchestrator._maven_client", return_value=mock_client):
        import maven_orchestrator
        with pytest.raises(ValueError, match="empty reply"):
            maven_orchestrator._call_maven_draft(
                conversation_id="123",
                subject="Test",
                ticket_body="Help",
                account_blob="",
                stripe_context="",
            )


def test_call_maven_draft_invokes_log_callback():
    """_call_maven_draft() calls log_callback with progress messages."""
    mock_client = MagicMock()
    mock_client.conversation.ask_stream.return_value = iter([
        _make_text_event("response"),
        _make_end_event(),
    ])
    logs: list[str] = []

    with patch("maven_orchestrator._maven_client", return_value=mock_client):
        import maven_orchestrator
        maven_orchestrator._call_maven_draft(
            conversation_id="123",
            subject="Test",
            ticket_body="Help",
            account_blob="",
            stripe_context="",
            log_callback=logs.append,
        )

    assert any("initializing" in msg for msg in logs)
    assert any("asking" in msg for msg in logs)
    assert any("response received" in msg for msg in logs)
```

- [ ] **Step 2: Run to confirm failure**

```bash
python -m pytest tests/test_maven_orchestrator.py::test_call_maven_draft_concatenates_text_chunks -v
```

Expected: `AttributeError` or `ImportError` — `_call_maven_draft` not yet defined

- [ ] **Step 3: Add `_call_maven_draft` to `maven_orchestrator.py`**

Append after `_maven_client()`:

```python
def _call_maven_draft(
    *,
    conversation_id: str,
    subject: str,
    ticket_body: str,
    account_blob: str,
    stripe_context: str,
    conversation_history: str = "",
    log_callback: Optional[Callable[[str], None]] = None,
) -> str:
    """Initialize a Maven conversation and stream the reply. Returns full reply text."""

    def _log(msg: str) -> None:
        log.info(msg)
        if log_callback:
            log_callback(msg)

    client = _maven_client()
    cid_ref = f"hs-{conversation_id}"
    msg_ref = f"hs-{conversation_id}-msg-{int(time.time() * 1000)}"

    _log("Maven: initializing conversation")
    client.conversation.initialize(
        conversation_id=EntityIdBase(reference_id=cid_ref),
        subject=subject,
        messages=[],
    )

    transient: dict[str, str] = {
        "account_context": account_blob[:4000],
        "stripe_context": stripe_context[:1000],
    }
    if conversation_history:
        transient["conversation_history"] = conversation_history[:4000]

    _log("Maven: asking...")
    chunks: list[str] = []
    for event in client.conversation.ask_stream(
        conversation_id=cid_ref,
        conversation_message_id=EntityIdBase(reference_id=msg_ref),
        user_id=EntityIdBase(reference_id="support-pipeline"),
        text=ticket_body,
        transient_data=transient,
    ):
        if isinstance(event, StreamResponse_Text):
            chunks.append(event.contents)
        elif isinstance(event, StreamResponse_End) and event.error:
            raise ValueError(f"Maven stream error: {event.error}")

    reply = "".join(chunks).strip()
    if not reply:
        raise ValueError("Maven returned empty reply")
    _log(f"Maven: response received ({len(reply)} chars)")
    return reply
```

- [ ] **Step 4: Run all draft tests**

```bash
python -m pytest tests/test_maven_orchestrator.py -k "draft" -v
```

Expected: `4 passed`

- [ ] **Step 5: Commit**

```bash
git add maven_orchestrator.py tests/test_maven_orchestrator.py
git commit -m "feat: add _call_maven_draft with streaming + log callback"
```

---

## Task 4: Implement `process_maven_ticket_sync()`

**Files:**
- Modify: `maven_orchestrator.py` (append function)
- Modify: `tests/test_maven_orchestrator.py` (append test)

- [ ] **Step 1: Append integration test**

Add to the bottom of `tests/test_maven_orchestrator.py`:

```python
def test_process_maven_ticket_sync_returns_expected_shape():
    """process_maven_ticket_sync returns a dict with engine=maven and core fields set."""
    import maven_orchestrator

    mock_convo = {
        "subject": "Can't log in",
        "tags": [],
        "_embedded": {},
        "primaryCustomer": {"id": 42, "email": "user@example.com", "firstName": "Test", "lastName": "User"},
    }

    with (
        patch("maven_orchestrator.run_triage"),
        patch("maven_orchestrator.get_access_token", return_value="tok"),
        patch("maven_orchestrator.requests.Session") as mock_session_cls,
        patch("maven_orchestrator.fetch_conversation", return_value=mock_convo),
        patch("maven_orchestrator.get_conversation_text", return_value="I can't log in"),
        patch("maven_orchestrator.fetch_customer_emails_from_helpscout", return_value=[]),
        patch("maven_orchestrator.fetch_account_contexts_for_ticket", return_value={
            "combined_blob": "Account Found: true\nSubscribed: true",
            "emails_checked": ["user@example.com"],
            "multiple_subscribed": False,
        }),
        patch("maven_orchestrator._subscription_platform", return_value="Apple"),
        patch("maven_orchestrator._call_maven_draft", return_value="Here's what you can do…"),
        patch("maven_orchestrator._update_conversation_tags"),
        patch("maven_orchestrator._helpscout_post") as mock_post,
        patch("maven_orchestrator.run_product_prioritization", return_value={"skipped": True}),
    ):
        mock_resp = MagicMock()
        mock_resp.status_code = 201
        mock_resp.headers = {"Resource-ID": "draft-99"}
        mock_post.return_value = mock_resp

        result = maven_orchestrator.process_maven_ticket_sync("555", "user@example.com")

    assert result["engine"] == "maven"
    assert result["draft_text"] == "Here's what you can do…"
    assert result["draft_created"] is True
    assert result["needs_action"] is True
    assert result["auto_sendable"] is False
    assert result["escalated"] is False
    assert result["error"] is None
```

- [ ] **Step 2: Run to confirm failure**

```bash
python -m pytest tests/test_maven_orchestrator.py::test_process_maven_ticket_sync_returns_expected_shape -v
```

Expected: `AttributeError` — `process_maven_ticket_sync` not yet defined

- [ ] **Step 3: Add `process_maven_ticket_sync` to `maven_orchestrator.py`**

Append after `_call_maven_draft`:

```python
def process_maven_ticket_sync(
    conversation_id: str,
    customer_email: Optional[str] = None,
    *,
    is_reply: bool = False,
    log_callback: Optional[Callable[[str], None]] = None,
) -> dict[str, Any]:
    """Maven pipeline: triage → account → Stripe (optional) → Maven draft → Help Scout draft + note."""
    t0 = time.monotonic()
    cid = str(conversation_id).strip()

    def _log(msg: str) -> None:
        log.info(msg)
        if log_callback:
            log_callback(msg)

    out: dict[str, Any] = {
        "conversation_id": cid,
        "customer_email": customer_email or "",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "engine": "maven",
        "triage_success": False,
        "account_lookup_success": False,
        "stripe_enrichment_attempted": False,
        "stripe_enrichment_success": False,
        "stripe_platform": None,
        "multiple_subscribed": False,
        "emails_checked": [],
        "escalated": False,
        "escalate_reason": None,
        "needs_action": True,
        "auto_sendable": False,
        "confidence": "n/a (maven)",
        "referenced_policies": [],
        "do_not_send_reasons": [],
        "draft_created": False,
        "note_created": False,
        "helpscout_draft_id": None,
        "helpscout_note_id": None,
        "latency_ms": None,
        "draft_text": None,
        "reasoning": None,
        "product_prioritization": None,
        "error": None,
    }

    email_in = (customer_email or "").strip()

    try:
        # Step 1 — Triage
        if is_reply:
            _log("Triage: skipped (reply)")
        else:
            try:
                run_triage(conversation_ids=[cid], auto_apply=True, skip_unassigned_scan=True)
                out["triage_success"] = True
                _log("Triage: complete")
            except SystemExit as e:
                log.warning("run_triage sys.exit (%s) — check env", e.code)
            except Exception:
                log.exception("triage failed — continuing pipeline")
                _log("Triage: failed (continuing)")

        # Step 2 — Help Scout session
        app_id = os.getenv("HELPSCOUT_APP_ID")
        app_secret = os.getenv("HELPSCOUT_APP_SECRET")
        if not app_id or not app_secret:
            raise RuntimeError("HELPSCOUT_APP_ID / HELPSCOUT_APP_SECRET required.")

        token = get_access_token()
        session = requests.Session()
        session.headers.update({"Authorization": f"Bearer {token}"})

        convo = fetch_conversation(session, int(cid))
        cust = _customer_from_conversation(convo)
        hs_customer_id = cust.get("id")
        convo_email = (cust.get("email") or "").strip()
        email = email_in or convo_email
        out["customer_email"] = email
        existing_tags = _extract_tag_names(convo.get("tags", []))
        customer_name = _customer_display_name(cust)
        subject = convo.get("subject") or "(no subject)"

        if is_reply:
            conversation_history, body = get_conversation_history(session, int(cid))
            body = body or "(empty)"
        else:
            conversation_history = ""
            body = get_conversation_text(session, int(cid)) or "(empty)"

        # Step 3 — Account lookup
        account_blob = ""
        try:
            hs_emails = fetch_customer_emails_from_helpscout(session, hs_customer_id) if hs_customer_id else []
            ctx = fetch_account_contexts_for_ticket(
                primary_email=email or None,
                ticket_text=body,
                extra_emails=hs_emails,
            )
            account_blob = ctx["combined_blob"]
            out["emails_checked"] = ctx["emails_checked"]
            out["multiple_subscribed"] = ctx["multiple_subscribed"]
            out["account_lookup_success"] = bool(account_blob.strip())
            _log(f"Account lookup: {email or '(unknown)'} — {'found' if out['account_lookup_success'] else 'not found'}")
        except Exception as e:
            account_blob = f"Account lookup failed — {e}"
            out["account_lookup_success"] = False
            _log(f"Account lookup: failed ({e})")
            log.exception("account_context failed")

        # Step 4 — Stripe enrichment (Stripe + gift only)
        platform = _subscription_platform(account_blob)
        out["stripe_platform"] = platform
        stripe_block = ""

        if (platform and platform.lower() == "stripe") or ("gift-subscription" in existing_tags):
            out["stripe_enrichment_attempted"] = True
            try:
                stripe_ctx_dict = fetch_stripe_context(email) if email else None
                stripe_block = format_stripe_context(stripe_ctx_dict)
                out["stripe_enrichment_success"] = stripe_ctx_dict is not None
                _log("Stripe: enriched")
            except Exception as e:
                stripe_block = "Stripe data unavailable"
                out["stripe_enrichment_success"] = False
                _log(f"Stripe: failed ({e})")
                log.exception("Stripe enrichment failed")
        else:
            stripe_block = f"N/A — customer is on {platform or 'unknown'} (not Stripe web billing)"
            _log("Stripe: skipped")

        # Step 5 — Maven draft
        draft_reply = _call_maven_draft(
            conversation_id=cid,
            subject=subject,
            ticket_body=body,
            account_blob=account_blob,
            stripe_context=stripe_block,
            conversation_history=conversation_history,
            log_callback=log_callback,
        )
        out["draft_text"] = draft_reply

        # Step 6 — Tags
        tags_to_add = ["maven-draft", "technical"]
        try:
            _update_conversation_tags(session, cid, existing_tags, tags_to_add)
        except requests.RequestException:
            log.exception("Failed to update tags on conversation %s", cid)

        # Step 7 — Help Scout draft
        if hs_customer_id is None:
            log.error("No HS customer id — cannot create draft. Draft:\n%s", draft_reply[:8000])
        else:
            reply_url = f"{BASE_URL}/conversations/{cid}/reply"
            payload = {"customer": {"id": int(hs_customer_id)}, "text": draft_reply, "draft": True}
            try:
                r = _helpscout_post(session, reply_url, payload)
                r.raise_for_status()
                out["helpscout_draft_id"] = r.headers.get("Resource-ID") or r.headers.get("resource-id")
                out["draft_created"] = True
                _log("Help Scout: draft created")
            except requests.RequestException as e:
                log.exception("Help Scout draft failed: %s\nDraft:\n%s", e, draft_reply[:8000])
                _log(f"Help Scout: draft failed ({e})")

        # Step 8 — Internal note
        note_user_id = os.getenv("HELPSCOUT_NOTE_USER_ID", "").strip()
        if note_user_id:
            note_html = (
                "<p><strong>🤖 Maven AGI Draft</strong></p><hr/>"
                f"<p>Draft generated by Maven AGI.<br/>"
                f"Conversation ref: hs-{cid}<br/>"
                f"Customer: {_html_escape(email or '(unknown)')}</p>"
                "<p><strong>Needs Action:</strong> Yes<br/>"
                "<strong>Auto-Sendable:</strong> No</p>"
            )
            note_url = f"{BASE_URL}/conversations/{cid}/notes"
            try:
                r2 = _helpscout_post(session, note_url, {"text": note_html, "user": int(note_user_id)})
                r2.raise_for_status()
                out["helpscout_note_id"] = r2.headers.get("Resource-ID") or r2.headers.get("resource-id")
                out["note_created"] = True
                _log("Help Scout: note created")
            except requests.RequestException:
                log.exception("Help Scout note failed")

        # Step 9 — Product prioritization
        pp = run_product_prioritization(
            ticket_subject=subject, ticket_body=body, tags=existing_tags, conversation_id=cid,
        )
        out["product_prioritization"] = pp
        if not pp.get("skipped"):
            log.info("product_prioritization: %s", pp)

        out["latency_ms"] = int((time.monotonic() - t0) * 1000)
        _log("Done")
        log.info("%s", {k: out[k] for k in out if k != "draft_text"})
        return out

    except Exception as e:
        out["error"] = str(e)
        out["latency_ms"] = int((time.monotonic() - t0) * 1000)
        _log(f"Error: {e}")
        log.exception("process_maven_ticket_sync failed: %s", e)
        raise
```

- [ ] **Step 4: Run all tests**

```bash
python -m pytest tests/test_maven_orchestrator.py -v
```

Expected: `7 passed`

- [ ] **Step 5: Commit**

```bash
git add maven_orchestrator.py tests/test_maven_orchestrator.py
git commit -m "feat: implement process_maven_ticket_sync full pipeline"
```

---

## Task 5: Sidebar — log infrastructure

**Files:**
- Create: `tests/test_sidebar.py`
- Modify: `sidebar_server.py` — `_set_status`, add `_append_log`, `_get_status`

- [ ] **Step 1: Write failing tests**

Create `tests/test_sidebar.py`:

```python
import pytest


def test_set_status_running_clears_logs():
    """Setting status to 'running' resets the logs list."""
    import sidebar_server
    sidebar_server._status.clear()
    sidebar_server._set_status("cid1", "running")
    sidebar_server._append_log("cid1", "first log")
    sidebar_server._set_status("cid1", "running")  # second run
    s = sidebar_server._get_status("cid1")
    assert s["logs"] == []


def test_append_log_accumulates_entries():
    """_append_log adds timestamped entries to the logs list."""
    import sidebar_server
    sidebar_server._status.clear()
    sidebar_server._set_status("cid2", "running")
    sidebar_server._append_log("cid2", "step one")
    sidebar_server._append_log("cid2", "step two")
    s = sidebar_server._get_status("cid2")
    assert len(s["logs"]) == 2
    assert "step one" in s["logs"][0]
    assert "step two" in s["logs"][1]


def test_set_status_done_preserves_logs():
    """Transitioning to 'done' keeps the accumulated logs."""
    import sidebar_server
    sidebar_server._status.clear()
    sidebar_server._set_status("cid3", "running")
    sidebar_server._append_log("cid3", "Maven: asking...")
    sidebar_server._set_status("cid3", "done", "Draft created")
    s = sidebar_server._get_status("cid3")
    assert s["status"] == "done"
    assert any("Maven: asking..." in entry for entry in s["logs"])


def test_get_status_returns_idle_for_unknown():
    """_get_status returns idle for unknown conversation IDs."""
    import sidebar_server
    sidebar_server._status.clear()
    s = sidebar_server._get_status("unknown-cid")
    assert s["status"] == "idle"
    assert s.get("logs", []) == []
```

- [ ] **Step 2: Run to confirm failure**

```bash
python -m pytest tests/test_sidebar.py -v
```

Expected: `4 failed` — `_append_log` doesn't exist yet, and `_set_status`/`_get_status` don't handle logs

- [ ] **Step 3: Update `sidebar_server.py` — log infrastructure**

Replace the existing `_set_status` and `_get_status` functions and add `_append_log`. Find these lines in `sidebar_server.py`:

```python
def _set_status(cid: str, status: str, message: str = "") -> None:
    with _status_lock:
        _status[cid] = {
            "status": status,
            "message": message,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        if len(_status) > _MAX_STATUS_ENTRIES:
            del _status[next(iter(_status))]


def _get_status(cid: str) -> dict:
    with _status_lock:
        return dict(_status.get(cid, {"status": "idle"}))
```

Replace with:

```python
def _set_status(cid: str, status: str, message: str = "") -> None:
    with _status_lock:
        existing_logs = _status.get(cid, {}).get("logs", []) if status != "running" else []
        _status[cid] = {
            "status": status,
            "message": message,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "logs": existing_logs,
        }
        if len(_status) > _MAX_STATUS_ENTRIES:
            del _status[next(iter(_status))]


def _append_log(cid: str, message: str) -> None:
    ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
    with _status_lock:
        if cid in _status:
            _status[cid].setdefault("logs", []).append(f"[{ts}] {message}")
            _status[cid]["updated_at"] = datetime.now(timezone.utc).isoformat()


def _get_status(cid: str) -> dict:
    with _status_lock:
        return dict(_status.get(cid, {"status": "idle", "logs": []}))
```

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/test_sidebar.py -v
```

Expected: `4 passed`

- [ ] **Step 5: Commit**

```bash
git add sidebar_server.py tests/test_sidebar.py
git commit -m "feat: add log infrastructure to sidebar (append_log, logs in status)"
```

---

## Task 6: Sidebar — engine routing in `/trigger-draft`

**Files:**
- Modify: `sidebar_server.py` — `_run_pipeline`, `trigger_draft` endpoint
- Add import of `process_maven_ticket_sync`

- [ ] **Step 1: Append failing test to `tests/test_sidebar.py`**

```python
def test_trigger_draft_accepts_engine_param():
    """
    /trigger-draft with engine=maven routes to maven pipeline (smoke test via mock).
    This exercises the dispatch logic without hitting any external services.
    """
    from fastapi.testclient import TestClient
    from unittest.mock import patch, MagicMock
    import sidebar_server

    sidebar_server.SIDEBAR_SECRET = "testsecret"
    client = TestClient(sidebar_server.app)

    with patch("sidebar_server.threading.Thread") as mock_thread:
        resp = client.post("/trigger-draft", json={
            "conversation_id": "999",
            "customer_email": "a@b.com",
            "secret": "testsecret",
            "engine": "maven",
        })

    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["engine"] == "maven"
    # Thread was started
    mock_thread.assert_called_once()
    # engine kwarg passed to thread target
    _, kwargs = mock_thread.call_args
    assert kwargs.get("kwargs", {}).get("engine") == "maven"
```

- [ ] **Step 2: Run to confirm failure**

```bash
python -m pytest tests/test_sidebar.py::test_trigger_draft_accepts_engine_param -v
```

Expected: `FAILED` — endpoint doesn't accept `engine` yet

- [ ] **Step 3: Add import of `process_maven_ticket_sync` to `sidebar_server.py`**

Find this line near the top of `sidebar_server.py`:

```python
from orchestrator import process_ticket_sync
```

Replace with:

```python
from maven_orchestrator import process_maven_ticket_sync
from orchestrator import process_ticket_sync
```

- [ ] **Step 4: Update `_run_pipeline` in `sidebar_server.py`**

Find:

```python
def _run_pipeline(cid: str, email: Optional[str]) -> None:
    try:
        result = process_ticket_sync(cid, email)
        if result.get("escalated"):
            _set_status(cid, "done", "Escalation flagged — check the internal note")
        else:
            _set_status(cid, "done", "Draft created — check the Reply editor")
    except Exception as e:
        _set_status(cid, "error", str(e)[:300])
        log.exception("sidebar pipeline failed for conversation %s", cid)
```

Replace with:

```python
def _run_pipeline(cid: str, email: Optional[str], engine: str = "claude") -> None:
    def log_callback(msg: str) -> None:
        _append_log(cid, msg)

    try:
        if engine == "maven":
            result = process_maven_ticket_sync(cid, email, log_callback=log_callback)
        else:
            result = process_ticket_sync(cid, email)

        if result.get("escalated"):
            _set_status(cid, "done", "Escalation flagged — check the internal note")
        elif result.get("draft_created"):
            _set_status(cid, "done", "Draft created — check the Reply editor")
        else:
            _set_status(cid, "done", result.get("error") or "Pipeline complete")
    except Exception as e:
        _set_status(cid, "error", str(e)[:300])
        log.exception("sidebar pipeline failed for conversation %s (engine=%s)", cid, engine)
```

- [ ] **Step 5: Update `trigger_draft` endpoint in `sidebar_server.py`**

Find:

```python
    with _status_lock:
        if _status.get(cid, {}).get("status") == "running":
            return {"ok": True, "conversation_id": cid, "status": "already_running"}

    _set_status(cid, "running")
    email: Optional[str] = body.get("customer_email") or None
    threading.Thread(target=_run_pipeline, args=(cid, email), daemon=True).start()
    log.info("sidebar triggered pipeline for conversation %s", cid)
    return {"ok": True, "conversation_id": cid, "status": "started"}
```

Replace with:

```python
    engine = str(body.get("engine", "claude")).strip().lower()
    if engine not in ("claude", "maven"):
        engine = "claude"

    with _status_lock:
        if _status.get(cid, {}).get("status") == "running":
            return {"ok": True, "conversation_id": cid, "status": "already_running"}

    _set_status(cid, "running")
    email: Optional[str] = body.get("customer_email") or None
    threading.Thread(
        target=_run_pipeline,
        args=(cid, email),
        kwargs={"engine": engine},
        daemon=True,
    ).start()
    log.info("sidebar triggered pipeline for conversation %s (engine=%s)", cid, engine)
    return {"ok": True, "conversation_id": cid, "status": "started", "engine": engine}
```

- [ ] **Step 6: Run tests**

```bash
python -m pytest tests/test_sidebar.py -v
```

Expected: `5 passed`

- [ ] **Step 7: Commit**

```bash
git add sidebar_server.py tests/test_sidebar.py
git commit -m "feat: add engine routing to sidebar trigger-draft endpoint"
```

---

## Task 7: Sidebar — two-button UI + log panel

**Files:**
- Modify: `sidebar_server.py` — `_SIDEBAR_HTML` string

- [ ] **Step 1: Replace `_SIDEBAR_HTML` in `sidebar_server.py`**

Find the entire `_SIDEBAR_HTML = """\` block (lines from `_SIDEBAR_HTML = """\ ` through the closing `"""`) and replace with:

```python
_SIDEBAR_HTML = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>AI Draft</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    font-size: 13px;
    color: #333;
    background: #fff;
    padding: 16px;
  }
  h2 { font-size: 14px; font-weight: 600; color: #1a1a1a; margin-bottom: 4px; }
  .conv-id { font-size: 11px; color: #999; margin-bottom: 14px; }
  .btn-row { display: flex; gap: 8px; }
  button {
    flex: 1;
    padding: 9px 10px;
    color: #fff;
    border: none;
    border-radius: 4px;
    font-size: 12px;
    font-weight: 500;
    cursor: pointer;
    transition: background 0.15s;
  }
  #btn-claude { background: #1f73b7; }
  #btn-claude:hover:not(:disabled) { background: #1a62a0; }
  #btn-maven  { background: #6b46c1; }
  #btn-maven:hover:not(:disabled)  { background: #5a3aad; }
  button:disabled { opacity: 0.55; cursor: default; }
  #status {
    margin-top: 12px;
    padding: 10px 12px;
    border-radius: 4px;
    font-size: 12px;
    line-height: 1.5;
    display: none;
  }
  .running { background: #f0f7ff; color: #1f73b7; border: 1px solid #c1daf4; }
  .done    { background: #f0faf0; color: #2e7d32; border: 1px solid #a8d5a2; }
  .error   { background: #fff4f4; color: #c62828; border: 1px solid #f5c0c0; }
  #loading { font-size: 12px; color: #999; }
  .spinner {
    display: inline-block;
    width: 11px; height: 11px;
    border: 2px solid currentColor;
    border-top-color: transparent;
    border-radius: 50%;
    animation: spin 0.7s linear infinite;
    vertical-align: middle;
    margin-right: 6px;
  }
  @keyframes spin { to { transform: rotate(360deg); } }
  #log-panel {
    margin-top: 10px;
    padding: 8px 10px;
    background: #f8f8f8;
    border: 1px solid #ddd;
    border-radius: 4px;
    font-size: 11px;
    font-family: monospace;
    max-height: 180px;
    overflow-y: auto;
    display: none;
    white-space: pre-wrap;
    word-break: break-all;
    color: #555;
  }
</style>
</head>
<body>
<h2>AI Draft Generator</h2>
<p class="conv-id">Conversation #<span id="cid-label">…</span></p>
<div id="loading"><span class="spinner"></span>Connecting to Help Scout…</div>
<div id="btns" class="btn-row" style="display:none">
  <button id="btn-claude" onclick="generate('claude')">Claude Draft</button>
  <button id="btn-maven"  onclick="generate('maven')">Maven Draft</button>
</div>
<div id="status"></div>
<pre id="log-panel"></pre>
<script>
var CID    = __CID__;
var EMAIL  = __EMAIL__;
var SECRET = __SECRET__;
var pollTimer = null;
var lastLogCount = 0;

if (CID) {
  ready(CID, EMAIL);
} else {
  var ALLOWED_ORIGINS = [
    'https://secure.helpscout.net',
    /^https:\\/\\/hs-app\\..+\\.hsenv\\.io$/
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
  CID   = cid;
  EMAIL = email;
  document.getElementById('cid-label').textContent = CID;
  document.getElementById('loading').style.display = 'none';
  document.getElementById('btns').style.display    = 'flex';
}

function setBtnsDisabled(disabled) {
  document.getElementById('btn-claude').disabled = disabled;
  document.getElementById('btn-maven').disabled  = disabled;
}

async function generate(engine) {
  setBtnsDisabled(true);
  lastLogCount = 0;
  var label = engine === 'maven' ? 'Maven' : 'Claude';
  showStatus('running', 'Running ' + label + ' pipeline — this takes 20–40 seconds…');
  document.getElementById('log-panel').textContent = '';
  document.getElementById('log-panel').style.display = 'block';

  try {
    var resp = await fetch('/trigger-draft', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ conversation_id: CID, customer_email: EMAIL, secret: SECRET, engine: engine })
    });
    if (!resp.ok) {
      var txt = await resp.text();
      showStatus('error', 'Request failed: ' + txt);
      setBtnsDisabled(false);
      return;
    }
    startPolling();
  } catch (e) {
    showStatus('error', 'Network error: ' + e.message);
    setBtnsDisabled(false);
  }
}

function startPolling() {
  if (pollTimer) clearInterval(pollTimer);
  pollTimer = setInterval(async function() {
    try {
      var resp = await fetch('/trigger-status/' + encodeURIComponent(CID));
      var data = await resp.json();

      // Append new log lines
      var logs = data.logs || [];
      if (logs.length > lastLogCount) {
        var panel = document.getElementById('log-panel');
        var newLines = logs.slice(lastLogCount).join('\\n');
        panel.textContent += (lastLogCount > 0 ? '\\n' : '') + newLines;
        panel.scrollTop = panel.scrollHeight;
        lastLogCount = logs.length;
      }

      if (data.status === 'done') {
        clearInterval(pollTimer);
        showStatus('done', '✓ ' + (data.message || 'Draft created — check the Reply editor'));
        setBtnsDisabled(false);
      } else if (data.status === 'error') {
        clearInterval(pollTimer);
        showStatus('error', '✗ ' + (data.message || 'Pipeline failed — check server logs'));
        setBtnsDisabled(false);
      }
    } catch (_) { /* network hiccup — keep polling */ }
  }, 3000);
}

function showStatus(cls, msg) {
  var el = document.getElementById('status');
  el.className = cls;
  el.style.display = 'block';
  el.innerHTML = cls === 'running'
    ? '<span class=\\'spinner\\'></span>' + msg
    : msg;
}
</script>
</body>
</html>
"""
```

- [ ] **Step 2: Smoke-test the sidebar renders**

```bash
cd /Users/cassidystagnitti/code/code-happierMeditation/SupportAgent
python -c "
from sidebar_server import _render_sidebar
html = _render_sidebar('123', 'test@test.com').body.decode()
assert 'btn-claude' in html
assert 'btn-maven' in html
assert 'log-panel' in html
assert 'generate' in html
print('Sidebar HTML OK')
"
```

Expected: `Sidebar HTML OK`

- [ ] **Step 3: Run full test suite**

```bash
python -m pytest tests/ -v
```

Expected: all tests pass (count depends on total — at minimum 12 tests across the two test files)

- [ ] **Step 4: Commit**

```bash
git add sidebar_server.py
git commit -m "feat: add two-button UI and live log panel to sidebar"
```

---

## Task 8: Add new env vars and manual test instructions

**Files:**
- Modify: `CLAUDE.md` — add Maven env vars to the environment variables table

- [ ] **Step 1: Update CLAUDE.md env vars section**

Find the env var block in `CLAUDE.md` and add Maven vars under `# Anthropic`:

```markdown
# MavenAGI (draft engine alternative to Claude)
MAVEN_ORG_ID          # MavenAGI organization ID
MAVEN_AGENT_ID        # MavenAGI agent ID  
MAVEN_APP_ID          # MavenAGI app ID
MAVEN_APP_SECRET      # MavenAGI app secret
```

- [ ] **Step 2: Add Maven vars to your `.env` file**

```bash
# In SupportAgent/.env (or root .env), add:
MAVEN_ORG_ID=<your org id from MavenAGI dashboard>
MAVEN_AGENT_ID=<your agent id>
MAVEN_APP_ID=<your app id>
MAVEN_APP_SECRET=<your app secret>
```

- [ ] **Step 3: Kill and restart the sidebar server**

```bash
lsof -ti:8765 | xargs kill -9 2>/dev/null; python3 sidebar_server.py --port 8765 &
```

Or via uvicorn:

```bash
lsof -ti:8765 | xargs kill -9 2>/dev/null; uvicorn sidebar_server:app --host 0.0.0.0 --port 8765 &
```

- [ ] **Step 4: Open a real Help Scout conversation in the sidebar**

Navigate to any conversation in Help Scout with your custom app sidebar loaded. You should see:
- Two buttons: **Claude Draft** (blue) and **Maven Draft** (purple)
- No status or log panel yet

- [ ] **Step 5: Click "Maven Draft" and watch the log panel**

Expected:
- Both buttons disable
- Status bar shows "Running Maven pipeline…"
- Log panel appears and populates every 3 seconds:
  ```
  [HH:MM:SS] Triage: complete
  [HH:MM:SS] Account lookup: user@example.com — found
  [HH:MM:SS] Stripe: skipped
  [HH:MM:SS] Maven: initializing conversation
  [HH:MM:SS] Maven: asking...
  [HH:MM:SS] Maven: response received (NNN chars)
  [HH:MM:SS] Help Scout: draft created
  [HH:MM:SS] Done
  ```
- Status turns green: "✓ Draft created — check the Reply editor"
- Draft appears in the Help Scout reply editor

- [ ] **Step 6: Click "Claude Draft" on the same conversation**

Expected:
- Log panel clears and a new run starts
- Claude draft appears (may differ from Maven draft)
- Both engines produce drafts independently

- [ ] **Step 7: Commit CLAUDE.md**

```bash
git add CLAUDE.md
git commit -m "docs: add Maven env vars to CLAUDE.md"
```

---

## Spec Coverage Check

| Spec requirement | Task |
|---|---|
| `maven_orchestrator.py` mirrors orchestrator pipeline | Tasks 2–4 |
| Maven credentials from env vars | Task 2 |
| `conversation.initialize()` with subject | Task 3 |
| `conversation.ask_stream()` with transient_data | Task 3 |
| Stream chunks collected via `StreamResponse_Text.contents` | Task 3 |
| Safe classification stubs (needs_action=True, auto_sendable=False) | Task 4 |
| Help Scout draft + note posts | Task 4 |
| Two sidebar buttons (Claude / Maven) | Task 7 |
| `engine` param on `/trigger-draft` | Task 6 |
| Log panel with timestamped entries | Tasks 5 + 7 |
| Logs preserved on done/error, cleared on new run | Task 5 |
| New env vars documented | Task 8 |
