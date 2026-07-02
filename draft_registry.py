"""Draft lifecycle registry — prevents duplicate Help Scout drafts (SUP-461).

Help Scout's Mailbox API does not support deleting a draft thread once
created, so re-running the pipeline against a conversation that already has
a Bert-authored draft used to stack a second, duplicate draft. This module
tracks "we already drafted conversation X, thread Y, at time Z" in a small
local JSON registry so `orchestrator.process_ticket_sync` can decide whether
to skip, supersede, or (if ever supported) update the existing draft.

Step 1 investigation — PATCH update-in-place (2026-07-02):
    Tested `PATCH {BASE_URL}/conversations/{cid}/threads/{tid}` against a
    real, still-in-`draft`-state thread (conversation 3365380903, thread
    10295011235, recorded in eval/2026-07-02/results.json) with body
    `{"text": "..."}`.

    Result: HTTP 400 `Error parsing request body into JSON`
    (developer.helpscout.net/mailbox-api/overview/errors#invalid-json).
    A control `PUT` to the same URL confirmed PATCH is in fact the only
    supported method (`PUT` → 400 invalid-http-method, listing PATCH as
    supported), and a JSON-Patch-style array body
    (`[{"op": "replace", "path": "/text", "value": ...}]`) was tried too —
    same generic parse-error 400. No variant attempted returned 2xx.

    Verdict: 4xx → update-in-place is NOT usable. Falling back to the
    supersede-marker path per spec: create a new draft as usual and prepend
    a "Supersedes the earlier draft" warning to the internal note, rather
    than editing the existing draft thread. The original draft thread body
    was verified unchanged after the failed PATCH attempts (no data lost).

Registry JSON shape (see REGISTRY_PATH):
    {"<conversation_id>": {"thread_id": str, "drafted_at": str (ISO8601)}}

Writes are atomic (tmp file in the same directory + os.replace), mirroring
bug_registry.py's pattern, so a crash mid-write never corrupts the registry.

Fail-soft: any read/write failure in `get`/`set` is caught and logged; the
caller treats it as "no existing draft" / "record skipped" rather than
letting a registry problem block drafting.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from typing import Any

log = logging.getLogger("draft_registry")

_SUPPORT_DIR = os.path.dirname(os.path.abspath(__file__))

# Module-level so tests can monkeypatch it per-test (tmp_path isolation).
REGISTRY_PATH = os.path.join(_SUPPORT_DIR, "data", "draft_registry.json")


def _load_registry() -> dict[str, Any]:
    if not os.path.exists(REGISTRY_PATH):
        return {}
    try:
        with open(REGISTRY_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}
    if not isinstance(data, dict):
        return {}
    return data


def _atomic_write_json(path: str, data: Any) -> None:
    """Write JSON atomically: write to a tmp file in the same dir, then rename."""
    directory = os.path.dirname(path)
    os.makedirs(directory, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=directory, prefix=".draft_registry_", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, sort_keys=True)
            f.write("\n")
        os.replace(tmp_path, path)
    except BaseException:
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        raise


def get(cid: str) -> dict[str, Any] | None:
    """Return {"thread_id": str, "drafted_at": str} for `cid`, or None.

    Fail-soft: any read error is treated as "no existing draft" — a
    registry outage must never block drafting.
    """
    try:
        registry = _load_registry()
    except Exception:
        log.exception("draft_registry.get failed for conversation %s — treating as no existing draft", cid)
        return None
    entry = registry.get(str(cid))
    if not isinstance(entry, dict):
        return None
    return entry


def set(cid: str, thread_id: str, drafted_at: str) -> None:
    """Record that conversation `cid` now has a drafted thread `thread_id`.

    Fail-soft: any write error is logged and swallowed — a registry outage
    must never block or fail the drafting pipeline.
    """
    try:
        registry = _load_registry()
        registry[str(cid)] = {"thread_id": str(thread_id), "drafted_at": str(drafted_at)}
        _atomic_write_json(REGISTRY_PATH, registry)
    except Exception:
        log.exception("draft_registry.set failed for conversation %s — continuing without recording", cid)


def should_skip_draft(existing: dict[str, Any] | None, reply_mode: bool, force: bool) -> bool:
    """True only when there's an existing draft and neither reply_mode nor force applies.

    In that case the pipeline should skip drafting entirely rather than
    stack a duplicate. When reply_mode or force is set, the caller instead
    takes the supersede (or future update-in-place) path.
    """
    return bool(existing) and not reply_mode and not force
