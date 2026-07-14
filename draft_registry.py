"""Draft lifecycle registry — prevents duplicate Help Scout drafts (SUP-461).

Help Scout's Mailbox API does not support deleting a draft thread once
created, so re-running the pipeline against a conversation that already has
a Bert-authored draft used to stack a second, duplicate draft. This module
tracks "we already drafted conversation X, thread Y, at time Z" in a small
local JSON registry so `orchestrator.process_ticket_sync` can decide whether
to skip, supersede, or (if ever supported) update the existing draft.

Step 1 investigation — PATCH update-in-place (2026-07-02, CORRECTED 2026-07-06):
    Original 2026-07-02 finding said update-in-place was NOT usable, because
    `PATCH {BASE_URL}/conversations/{cid}/threads/{tid}` returned HTTP 400 for
    both a `{"text": "..."}` body and a JSON-Patch *array*
    (`[{"op": "replace", "path": "/text", "value": ...}]`).

    CORRECTION (2026-07-06): update-in-place DOES work. The request body must
    be a SINGLE JSON-Patch object, not an array:
        {"op": "replace", "path": "/text", "value": "..."}
    Verified live against a real draft thread → HTTP 204, body changed, and a
    follow-up PATCH restored the original. See `bert.pipeline.update_draft`,
    which Bert uses to rewrite existing drafts in place (avoiding duplicate
    drafts, since Help Scout still has no DELETE for draft threads).

    The supersede-marker path below remains as a fallback for callers that do
    not update in place.

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


def should_skip_draft(
    existing: dict[str, Any] | None,
    reply_mode: bool,
    force: bool,
    draft_is_stale: bool = False,
) -> bool:
    """True only when there's an existing draft that is still current and neither
    reply_mode nor force applies.

    In that case the pipeline should skip drafting entirely rather than
    stack a duplicate. When reply_mode or force is set, the caller instead
    takes the supersede (or update-in-place) path.

    `draft_is_stale` — set when a customer has replied since we drafted, so the
    existing draft no longer addresses the latest message. A stale draft must
    never be skipped: the caller refreshes it in place against the newest
    message instead. Defaults False (existing draft assumed current).
    """
    return bool(existing) and not reply_mode and not force and not draft_is_stale
