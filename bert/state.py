"""Morning-review state file: the lightweight ticket index + the standing brief.

One JSON file per morning under ``data/morning_review/<date>.json``. It holds:
  - ``records``:  the per-ticket index produced by the Haiku map step
  - ``brief``:    the standing brief — append-only notes (bug-truths, company
                  context, wording preferences) the session injects into every
                  draft worker
  - ``statuses``: per-conversation progress (summarized/hydrated/drafted/posted)

The session holds this whole object; it stays tiny because ``records`` are
one-liners and ``brief`` is a handful of notes — never full ticket bodies.
"""

from __future__ import annotations

import json
import os
import tempfile
from typing import Any

DEFAULT_BASE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "morning_review")


def state_path(date_str: str, base_dir: str | None = None) -> str:
    directory = base_dir if base_dir is not None else DEFAULT_BASE_DIR
    return os.path.join(directory, f"{date_str}.json")


def new_state(date_str: str) -> dict:
    return {"date": date_str, "records": [], "brief": [], "statuses": {}}


def _atomic_write_json(path: str, data: Any) -> None:
    """Write JSON atomically: tmp file in the same dir, then rename."""
    directory = os.path.dirname(path)
    os.makedirs(directory, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=directory, prefix=".morning_review_", suffix=".tmp")
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


def load(date_str: str, base_dir: str | None = None) -> dict:
    """Load the morning's state, or a fresh state if the file does not exist."""
    path = state_path(date_str, base_dir)
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return new_state(date_str)
    # Backfill any missing keys so callers can rely on the full shape.
    base = new_state(date_str)
    base.update({k: data.get(k, base[k]) for k in base})
    return base


def save(state: dict, base_dir: str | None = None) -> None:
    _atomic_write_json(state_path(state["date"], base_dir), state)


def set_records(state: dict, records: list[dict]) -> None:
    state["records"] = list(records)


def append_brief(state: dict, note: str) -> None:
    """Add a note to the standing brief, skipping blanks and exact duplicates."""
    note = (note or "").strip()
    if not note or note in state["brief"]:
        return
    state["brief"].append(note)


def render_brief(state: dict) -> str:
    """The standing brief as a bulleted block for prompt injection ('' if empty)."""
    return "\n".join(f"- {n}" for n in state["brief"])


def set_status(state: dict, cid: str, **fields) -> None:
    """Merge status fields for a conversation."""
    current = state["statuses"].get(str(cid), {})
    current.update(fields)
    state["statuses"][str(cid)] = current
