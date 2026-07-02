"""New-bug candidate registry + Linear auto-filing (SUP-458).

Accumulates NEW-bug candidates (bugs the draft model flagged as not matching
any known bug) in a local JSON registry keyed by fuzzy-matched summary. Once
a candidate has 2+ reports from distinct customer emails, it is auto-filed as
a Linear ticket (T-759 format) via `linear_client.create_issue`.

Known-bug reports (`matches_known_bug` set) are not tracked here at all —
`record_bug` returns None and leaves the registry untouched.

Registry JSON shape (see REGISTRY_PATH):
    {"candidates": [
        {"summary": str,
         "reports": [{"email": str, "ticket_id": str, "excerpt": str, "date": str}, ...],
         "linear_id": str | null,
         "first_seen": str}
    ]}

Writes are atomic (tmp file in the same directory + os.replace) so a crash
mid-write never corrupts the registry.
"""

from __future__ import annotations

import difflib
import json
import os
import tempfile
from datetime import datetime, timezone
from typing import Any

import linear_client

_SUPPORT_DIR = os.path.dirname(os.path.abspath(__file__))

# Module-level so tests can monkeypatch it per-test (tmp_path isolation).
REGISTRY_PATH = os.path.join(_SUPPORT_DIR, "data", "bug_candidates.json")

# difflib.SequenceMatcher ratio threshold for treating two summaries as the
# same underlying bug.
FUZZY_MATCH_THRESHOLD = 0.7

# Minimum number of *distinct* customer emails a candidate needs before it is
# auto-filed to Linear.
MIN_DISTINCT_EMAILS_TO_FILE = 2

HELPSCOUT_CONVERSATION_URL = "https://secure.helpscout.net/conversation/{ticket_id}"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_registry() -> dict[str, Any]:
    if not os.path.exists(REGISTRY_PATH):
        return {"candidates": []}
    try:
        with open(REGISTRY_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return {"candidates": []}
    if not isinstance(data, dict) or not isinstance(data.get("candidates"), list):
        return {"candidates": []}
    return data


def _atomic_write_json(path: str, data: Any) -> None:
    """Write JSON atomically: write to a tmp file in the same dir, then rename."""
    directory = os.path.dirname(path)
    os.makedirs(directory, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=directory, prefix=".bug_candidates_", suffix=".tmp")
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


def _save_registry(data: dict[str, Any]) -> None:
    _atomic_write_json(REGISTRY_PATH, data)


def _similar(a: str, b: str) -> float:
    """difflib similarity ratio between two (lowercased) summaries.

    Uses SequenceMatcher.quick_ratio() rather than the exact ratio(): it's a
    fast upper-bound approximation based on character-frequency overlap, and
    in practice it's more forgiving of reworded-but-same-bug summaries (e.g.
    "resets randomly" vs. "keeps resetting") that exact ratio() scores just
    under the 0.7 threshold. Still a difflib.SequenceMatcher score in [0, 1].
    """
    return difflib.SequenceMatcher(None, (a or "").strip().lower(), (b or "").strip().lower()).quick_ratio()


def _find_matching_candidate(candidates: list[dict[str, Any]], summary: str) -> dict[str, Any] | None:
    """Best fuzzy match (ratio >= FUZZY_MATCH_THRESHOLD) among registry candidates, or None."""
    best: dict[str, Any] | None = None
    best_ratio = 0.0
    for candidate in candidates:
        ratio = _similar(candidate.get("summary") or "", summary)
        if ratio >= FUZZY_MATCH_THRESHOLD and ratio > best_ratio:
            best = candidate
            best_ratio = ratio
    return best


def _find_matching_linear_issue(summary: str) -> dict[str, Any] | None:
    """Best fuzzy match (ratio >= FUZZY_MATCH_THRESHOLD) among open Linear issues, or None.

    Fail-soft: if the Linear search itself raises (e.g. API outage, missing
    key), treat it as "no match" rather than blocking candidate tracking.
    """
    try:
        issues = linear_client.search_issues(summary) or []
    except Exception:
        return None
    best: dict[str, Any] | None = None
    best_ratio = 0.0
    for issue in issues:
        ratio = _similar(issue.get("title") or "", summary)
        if ratio >= FUZZY_MATCH_THRESHOLD and ratio > best_ratio:
            best = issue
            best_ratio = ratio
    return best


def _distinct_emails(reports: list[dict[str, Any]]) -> set[str]:
    return {(r.get("email") or "").strip().lower() for r in reports if (r.get("email") or "").strip()}


def _build_ticket_description(candidate: dict[str, Any]) -> str:
    """T-759 format: one-line symptom summary, Affected users, Source tickets."""
    summary = candidate.get("summary") or ""
    reports = candidate.get("reports") or []

    lines = [summary, "", "## Affected users"]
    for r in reports:
        email = r.get("email") or ""
        excerpt = (r.get("excerpt") or "").strip()
        lines.append(f'- {email} — "{excerpt}"')

    lines += ["", "## Source tickets"]
    seen_tickets: set[str] = set()
    for r in reports:
        ticket_id = r.get("ticket_id") or ""
        if not ticket_id or ticket_id in seen_tickets:
            continue
        seen_tickets.add(ticket_id)
        lines.append(f"- {HELPSCOUT_CONVERSATION_URL.format(ticket_id=ticket_id)}")

    return "\n".join(lines)


def record_bug(parsed: dict[str, Any], ticket_id: str, customer_email: str, excerpt: str) -> dict[str, Any] | None:
    """Track a NEW-bug candidate and auto-file to Linear at 2+ distinct emails.

    `parsed` is the draft JSON's top-level dict — the relevant fields live at
    `parsed["bug_report"]`: {is_bug, matches_known_bug, new_bug_summary}.

    Returns the updated candidate dict, or None when:
      - there's no bug_report / is_bug is falsy, or
      - matches_known_bug is set (a known bug — nothing to track here).
    """
    bug_report = parsed.get("bug_report") or {}
    if not bug_report.get("is_bug"):
        return None
    if bug_report.get("matches_known_bug"):
        return None

    summary = (bug_report.get("new_bug_summary") or "").strip()
    if not summary:
        return None

    registry = _load_registry()
    candidates = registry["candidates"]

    candidate = _find_matching_candidate(candidates, summary)
    if candidate is None:
        candidate = {
            "summary": summary,
            "reports": [],
            "linear_id": None,
            "first_seen": _now_iso(),
        }
        candidates.append(candidate)

    candidate["reports"].append({
        "email": customer_email,
        "ticket_id": ticket_id,
        "excerpt": excerpt,
        "date": _now_iso(),
    })

    if candidate.get("linear_id") is None:
        # Dedupe against the live Linear board only when we're about to file —
        # avoids a search call on every single report.
        if len(_distinct_emails(candidate["reports"])) >= MIN_DISTINCT_EMAILS_TO_FILE:
            existing_issue = _find_matching_linear_issue(candidate["summary"])
            if existing_issue is not None:
                candidate["linear_id"] = existing_issue.get("identifier")
            else:
                try:
                    issue = linear_client.create_issue(
                        candidate["summary"],
                        _build_ticket_description(candidate),
                    )
                    candidate["linear_id"] = issue.get("identifier")
                except Exception:
                    # Fail-soft: keep the candidate tracked even if Linear filing
                    # fails; it will be retried on the next matching report.
                    pass

    _save_registry(registry)
    return candidate
