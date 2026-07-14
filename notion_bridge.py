#!/usr/bin/env python3
"""Notion bridge: gap queue + action log databases for the support pipeline.

Two Notion databases live under a "Bert Ops" page (a child of the Support
Policy Docs page):

  Bert Gap Queue  — unanswered policy questions the pipeline couldn't resolve
                    from existing policy docs. The support team answers them
                    in Notion; `process_answered_gaps.py` later writes those
                    answers back into policies/*.md.
  Bert Action Log — manual to-dos the pipeline identified (e.g. "apply coupon
                    in Stripe") that a human needs to actually perform.

Environment:
  NOTION_TOKEN          — Notion integration secret (required for all writes/reads)
  NOTION_VERSION        — API version header (default: 2022-06-28)

All public functions raise RuntimeError("NOTION_TOKEN not configured") early
when the token is missing, so pipeline callers can fail soft:

    try:
        notion_bridge.upsert_gap(question, ticket_id, subject)
    except RuntimeError:
        logger.warning("Notion gap logging unavailable", exc_info=True)
"""

from __future__ import annotations

import difflib
import hashlib
import json
import os
import sys
import tempfile
import time
from datetime import datetime, timezone
from typing import Any

import requests
from dotenv import load_dotenv

_SUPPORT_DIR = os.path.dirname(os.path.abspath(__file__))
_ROOT_DIR = os.path.dirname(_SUPPORT_DIR)
load_dotenv(os.path.join(_SUPPORT_DIR, ".env"))
load_dotenv(os.path.join(_ROOT_DIR, ".env"))

NOTION_API = "https://api.notion.com/v1"
SUPPORT_POLICY_DOCS_PAGE_ID = "356cffdf-527f-808d-a4fc-f7d05499523f"

BERT_OPS_PAGE_TITLE = "Bert Ops"
GAP_DB_TITLE = "Bert Gap Queue"
ACTION_DB_TITLE = "Bert Action Log"

_IDS_CACHE_PATH = os.path.join(_SUPPORT_DIR, "data", "notion_ids.json")

QUESTION_MATCH_THRESHOLD = 0.75
_MAX_RICH_TEXT_CHARS = 2000

ACTION_SYSTEMS = ("Stripe", "Happier admin", "Help Scout", "Other")
GAP_STATUSES = ("Open", "Answered", "Incorporated")


# --- small utilities -----------------------------------------------------


def _notion_token() -> str:
    return (os.getenv("NOTION_TOKEN") or "").strip()


def _require_token() -> str:
    token = _notion_token()
    if not token:
        raise RuntimeError("NOTION_TOKEN not configured")
    return token


def _notion_headers() -> dict[str, str]:
    token = _require_token()
    version = (os.getenv("NOTION_VERSION") or "2022-06-28").strip()
    return {
        "Authorization": f"Bearer {token}",
        "Notion-Version": version,
        "Content-Type": "application/json",
    }


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update(_notion_headers())
    return s


def _request(session: requests.Session, method: str, url: str, **kwargs: Any) -> dict[str, Any]:
    """requests wrapper with basic 429 retry, mirroring pull_policy_docs.py."""
    for _ in range(5):
        r = session.request(method, url, timeout=60, **kwargs)
        if r.status_code == 429:
            time.sleep(int(r.headers.get("Retry-After", 3)))
            continue
        r.raise_for_status()
        return r.json() if r.content else {}
    r.raise_for_status()
    return {}


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _truncate(text: str, limit: int = _MAX_RICH_TEXT_CHARS) -> str:
    return text[:limit]


def _rich_text(text: str) -> list[dict[str, Any]]:
    text = _truncate(text or "")
    if not text:
        return []
    return [{"type": "text", "text": {"content": text}}]


def _title(text: str) -> list[dict[str, Any]]:
    return _rich_text(text) or [{"type": "text", "text": {"content": ""}}]


def _plain_text(rich: list[dict[str, Any]] | None) -> str:
    if not rich:
        return ""
    return "".join((t.get("plain_text") or t.get("text", {}).get("content", "") or "") for t in rich)


def _atomic_write_json(path: str, data: Any) -> None:
    """Write JSON atomically: write to a tmp file in the same dir, then rename."""
    directory = os.path.dirname(path)
    os.makedirs(directory, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=directory, prefix=".notion_ids_", suffix=".tmp")
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


def _load_ids_cache() -> dict[str, str] | None:
    if not os.path.exists(_IDS_CACHE_PATH):
        return None
    try:
        with open(_IDS_CACHE_PATH, encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return None
    if not isinstance(data, dict):
        return None
    if not {"bert_ops_page", "gap_db", "action_db"} <= set(data):
        return None
    return data


def ticket_url(ticket_id: str) -> str:
    return f"https://secure.helpscout.net/conversation/{ticket_id}"


# --- pure logic (unit-testable, no network) -------------------------------


def question_matches(a: str, b: str) -> bool:
    """Fuzzy match two questions using difflib ratio on lowercased/stripped text."""
    ratio = difflib.SequenceMatcher(None, a.lower().strip(), b.lower().strip()).ratio()
    return ratio >= QUESTION_MATCH_THRESHOLD


def action_key(ticket_id: str, action: str) -> str:
    """Stable (cross-run) idempotency key for an action log row.

    Uses sha1, NOT the builtin hash() — builtin hash() of str is salted per
    process (PYTHONHASHSEED) and is not stable across runs.
    """
    digest = hashlib.sha1(action.encode("utf-8")).hexdigest()[:8]
    return f"{ticket_id}:{digest}"


def build_gap_properties(
    *,
    question: str,
    ticket_url: str,
    frequency: int,
    seen_date: str,
    status: str = "Open",
    answer: str = "",
    target_doc: str = "",
) -> dict[str, Any]:
    """Build the Notion `properties` payload for a Bert Gap Queue row."""
    if status not in GAP_STATUSES:
        raise ValueError(f"Invalid gap status {status!r}; expected one of {GAP_STATUSES}")
    props: dict[str, Any] = {
        "Question": {"title": _title(question)},
        "Status": {"select": {"name": status}},
        "Source Tickets": {"rich_text": _rich_text(ticket_url)},
        "Frequency": {"number": frequency},
        "First Seen": {"date": {"start": seen_date}},
        "Last Seen": {"date": {"start": seen_date}},
    }
    if answer:
        props["Answer"] = {"rich_text": _rich_text(answer)}
    if target_doc:
        props["Target Policy Doc"] = {"rich_text": _rich_text(target_doc)}
    return props


def build_action_properties(
    *,
    action: str,
    system: str,
    ticket_url: str,
    customer_email: str,
    confidence: str,
    key: str,
    created_date: str,
    done: bool = False,
) -> dict[str, Any]:
    """Build the Notion `properties` payload for a Bert Action Log row."""
    if system not in ACTION_SYSTEMS:
        raise ValueError(f"Invalid action system {system!r}; expected one of {ACTION_SYSTEMS}")
    return {
        "Action": {"title": _title(action)},
        "System": {"select": {"name": system}},
        "Ticket": {"url": ticket_url or None},
        "Customer": {"email": customer_email or None},
        "Confidence": {"select": {"name": confidence}} if confidence else {"select": None},
        "Done": {"checkbox": done},
        "Created": {"date": {"start": created_date}},
        "Key": {"rich_text": _rich_text(key)},
    }


# --- database bootstrap ---------------------------------------------------


def _create_bert_ops_page(session: requests.Session) -> str:
    payload = {
        "parent": {"type": "page_id", "page_id": SUPPORT_POLICY_DOCS_PAGE_ID},
        "properties": {"title": {"title": _title(BERT_OPS_PAGE_TITLE)}},
    }
    data = _request(session, "POST", f"{NOTION_API}/pages", json=payload)
    return data["id"]


def _create_gap_database(session: requests.Session, parent_page_id: str) -> str:
    payload = {
        "parent": {"type": "page_id", "page_id": parent_page_id},
        "title": _title(GAP_DB_TITLE),
        "properties": {
            "Question": {"title": {}},
            "Status": {"select": {"options": [{"name": s} for s in GAP_STATUSES]}},
            "Source Tickets": {"rich_text": {}},
            "Frequency": {"number": {}},
            "First Seen": {"date": {}},
            "Last Seen": {"date": {}},
            "Answer": {"rich_text": {}},
            "Target Policy Doc": {"rich_text": {}},
        },
    }
    data = _request(session, "POST", f"{NOTION_API}/databases", json=payload)
    return data["id"]


def _create_action_database(session: requests.Session, parent_page_id: str) -> str:
    payload = {
        "parent": {"type": "page_id", "page_id": parent_page_id},
        "title": _title(ACTION_DB_TITLE),
        "properties": {
            "Action": {"title": {}},
            "System": {"select": {"options": [{"name": s} for s in ACTION_SYSTEMS]}},
            "Ticket": {"url": {}},
            "Customer": {"email": {}},
            "Confidence": {"select": {"options": [{"name": n} for n in ("Low", "Medium", "High")]}},
            "Done": {"checkbox": {}},
            "Created": {"date": {}},
            "Key": {"rich_text": {}},
        },
    }
    data = _request(session, "POST", f"{NOTION_API}/databases", json=payload)
    return data["id"]


def ensure_databases() -> dict[str, str]:
    """Ensure the Bert Ops page + gap/action databases exist; return their ids.

    Reads data/notion_ids.json first (cache-first). Only attempts to create
    the page/databases via the REST API when the cache file is missing or
    incomplete. Returns {"gap_db": id, "action_db": id}.
    """
    cached = _load_ids_cache()
    if cached:
        return {"gap_db": cached["gap_db"], "action_db": cached["action_db"]}

    _require_token()
    session = _session()

    bert_ops_page = _create_bert_ops_page(session)
    gap_db = _create_gap_database(session, bert_ops_page)
    action_db = _create_action_database(session, bert_ops_page)

    ids = {"bert_ops_page": bert_ops_page, "gap_db": gap_db, "action_db": action_db}
    _atomic_write_json(_IDS_CACHE_PATH, ids)
    return {"gap_db": gap_db, "action_db": action_db}


# --- gap queue -------------------------------------------------------------


def _query_database(session: requests.Session, database_id: str, filter_payload: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    cursor = None
    while True:
        body: dict[str, Any] = {"page_size": 100}
        if filter_payload:
            body["filter"] = filter_payload
        if cursor:
            body["start_cursor"] = cursor
        data = _request(session, "POST", f"{NOTION_API}/databases/{database_id}/query", json=body)
        results.extend(data.get("results") or [])
        if not data.get("has_more"):
            break
        cursor = data.get("next_cursor")
    return results


def _find_matching_gap_row(session: requests.Session, database_id: str, question: str) -> dict[str, Any] | None:
    filter_payload = {
        "or": [
            {"property": "Status", "select": {"equals": "Open"}},
            {"property": "Status", "select": {"equals": "Answered"}},
        ]
    }
    rows = _query_database(session, database_id, filter_payload)
    for row in rows:
        props = row.get("properties") or {}
        existing_question = _plain_text((props.get("Question") or {}).get("title"))
        if existing_question and question_matches(question, existing_question):
            return row
    return None


def upsert_gap(question: str, ticket_id: str, ticket_subject: str) -> str:
    """Record an unanswered policy question in the Bert Gap Queue.

    Fuzzy-dedupes against existing Open/Answered rows (difflib ratio >= 0.75
    on lowercased question text). On a match: increments Frequency, appends
    the new ticket link to Source Tickets, and bumps Last Seen. Otherwise
    creates a new row (Status=Open, Frequency=1). Returns the page id.
    """
    _require_token()
    ids = ensure_databases()
    database_id = ids["gap_db"]
    session = _session()

    link = ticket_url(ticket_id)
    today = _today()

    existing = _find_matching_gap_row(session, database_id, question)
    if existing:
        page_id = existing["id"]
        props = existing.get("properties") or {}
        frequency = int((props.get("Frequency") or {}).get("number") or 0) + 1
        source_tickets = _plain_text((props.get("Source Tickets") or {}).get("rich_text"))
        if link not in source_tickets.splitlines():
            source_tickets = f"{source_tickets}\n{link}".strip("\n") if source_tickets else link
        update_payload = {
            "properties": {
                "Frequency": {"number": frequency},
                "Source Tickets": {"rich_text": _rich_text(source_tickets)},
                "Last Seen": {"date": {"start": today}},
            }
        }
        _request(session, "PATCH", f"{NOTION_API}/pages/{page_id}", json=update_payload)
        return page_id

    create_payload = {
        "parent": {"database_id": database_id},
        "properties": build_gap_properties(
            question=question,
            ticket_url=link,
            frequency=1,
            seen_date=today,
            status="Open",
        ),
    }
    data = _request(session, "POST", f"{NOTION_API}/pages", json=create_payload)
    return data["id"]


def fetch_answered_gaps() -> list[dict[str, Any]]:
    """Return gap rows with Status=Answered as plain dicts.

    Each dict: {page_id, question, answer, target_doc, source_tickets}
    """
    _require_token()
    ids = ensure_databases()
    session = _session()

    filter_payload = {"property": "Status", "select": {"equals": "Answered"}}
    rows = _query_database(session, ids["gap_db"], filter_payload)

    out: list[dict[str, Any]] = []
    for row in rows:
        props = row.get("properties") or {}
        out.append(
            {
                "page_id": row["id"],
                "question": _plain_text((props.get("Question") or {}).get("title")),
                "answer": _plain_text((props.get("Answer") or {}).get("rich_text")),
                "target_doc": _plain_text((props.get("Target Policy Doc") or {}).get("rich_text")),
                "source_tickets": _plain_text((props.get("Source Tickets") or {}).get("rich_text")),
            }
        )
    return out


def mark_incorporated(page_id: str) -> None:
    """Flip a gap row's Status to Incorporated after its answer has been written back."""
    _require_token()
    session = _session()
    payload = {"properties": {"Status": {"select": {"name": "Incorporated"}}}}
    _request(session, "PATCH", f"{NOTION_API}/pages/{page_id}", json=payload)


# --- action log -------------------------------------------------------------


def _find_action_row_by_key(session: requests.Session, database_id: str, key: str) -> dict[str, Any] | None:
    filter_payload = {"property": "Key", "rich_text": {"equals": key}}
    rows = _query_database(session, database_id, filter_payload)
    return rows[0] if rows else None


def upsert_action(action: str, system: str, ticket_id: str, customer_email: str, confidence: str) -> str:
    """Record a manual to-do in the Bert Action Log, idempotent per (ticket_id, action).

    Idempotency is via the stable `Key` rich_text property (see action_key()).
    Returns the page id (existing or newly created).
    """
    _require_token()
    ids = ensure_databases()
    database_id = ids["action_db"]
    session = _session()

    key = action_key(ticket_id, action)
    existing = _find_action_row_by_key(session, database_id, key)
    if existing:
        return existing["id"]

    create_payload = {
        "parent": {"database_id": database_id},
        "properties": build_action_properties(
            action=action,
            system=system,
            ticket_url=ticket_url(ticket_id),
            customer_email=customer_email,
            confidence=confidence,
            key=key,
            created_date=_today(),
        ),
    }
    data = _request(session, "POST", f"{NOTION_API}/pages", json=create_payload)
    return data["id"]


if __name__ == "__main__":
    print(json.dumps(ensure_databases(), indent=2))
    sys.exit(0)
