"""MAP step: summarize each open ticket cheaply with Haiku, in parallel.

Each ticket becomes a one-line index record. This is the map half of the
map/reduce; ``bert.render`` is the reduce half. Failures are isolated per
ticket — one bad summary never blocks the mailbox review.

CLI:  python3 -m bert.summarize            # summarize the active mailbox, write today's state, print artifact
"""

from __future__ import annotations

import concurrent.futures
import json
import os
import re
from datetime import date
from typing import Any

import anthropic
import requests

import claude_utils
import triage_tickets

SUMMARY_MODEL = "claude-haiku-4-5"

_RECORD_KEYS = ("category", "one_line", "urgent", "is_new", "matches_known_bug")

_KNOWN_BUGS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "policies", "known-bugs.md")
_ENTRY_RE = re.compile(r"^##\s+\d+\.\s+(.+?)\s*$", re.MULTILINE)


def _slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (text or "").lower())
    return slug.strip("-")


def known_bug_catalog(path: str | None = None) -> list:
    """Parse the canonical `## N. Title` entries from known-bugs.md → [(slug, title)]."""
    doc_path = path or _KNOWN_BUGS_PATH
    try:
        with open(doc_path, encoding="utf-8") as f:
            text = f.read()
    except OSError:
        return []
    return [(_slugify(title), title) for title in _ENTRY_RE.findall(text)]


def build_summary_prompt(ticket: dict, known_bugs: list | None = None) -> str:
    tags = ", ".join(ticket.get("tags") or []) or "(none)"
    body = (ticket.get("body") or "").strip()
    if known_bugs:
        bug_lines = "\n".join(f"  - {slug}: {title}" for slug, title in known_bugs)
        bug_instruction = (
            "  matches_known_bug (if this ticket matches one of the KNOWN BUGS below, use its EXACT slug; "
            "otherwise null — do NOT invent a new slug).\n"
            "KNOWN BUGS (slug: description):\n"
            f"{bug_lines}\n"
        )
    else:
        bug_instruction = "  matches_known_bug (short slug if it looks like a known product bug, else null).\n"
    return (
        "Summarize this support ticket into one JSON object with exactly these keys:\n"
        '  category (short lowercase noun, e.g. "billing", "bug", "account", "how-to"),\n'
        "  one_line (<=12 word plain summary of what the customer wants),\n"
        "  urgent (bool — cancellation threat, angry, payment failure, or time-sensitive),\n"
        "  is_new (bool — true unless the ticket references an ongoing/prior thread),\n"
        f"{bug_instruction}"
        "Reply with ONLY the JSON object, no fences, no commentary.\n\n"
        f"Subject: {ticket.get('subject') or '(no subject)'}\n"
        f"Tags: {tags}\n"
        f"Body:\n{body}\n"
    )


def parse_summary(text: str, conversation_id: int, valid_bug_slugs: set | None = None) -> dict:
    """Tolerant parse → record. On any failure, a fail-soft 'unavailable' record."""
    record = {
        "conversation_id": conversation_id,
        "customer": "",
        "category": "unknown",
        "one_line": "(summary unavailable)",
        "urgent": False,
        "is_new": False,
        "matches_known_bug": None,
    }
    if not text:
        return record
    cleaned = text.strip()
    cleaned = re.sub(r"^```(?:json)?", "", cleaned).strip()
    cleaned = re.sub(r"```$", "", cleaned).strip()
    match = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if not match:
        return record
    try:
        data = json.loads(match.group(0))
    except (json.JSONDecodeError, ValueError):
        return record
    if not isinstance(data, dict):
        return record
    for key in _RECORD_KEYS:
        if key in data:
            record[key] = data[key]
    record["conversation_id"] = conversation_id
    # Enforce canonical bug slugs: anything off the catalog becomes null so the
    # known-bug rollup actually clusters instead of fragmenting.
    if valid_bug_slugs is not None and record["matches_known_bug"] not in valid_bug_slugs:
        record["matches_known_bug"] = None
    return record


def summarize_ticket(client, ticket: dict, known_bugs: list | None = None) -> dict:
    valid_slugs = {slug for slug, _ in known_bugs} if known_bugs else None
    msg = client.messages.create(
        model=SUMMARY_MODEL,
        max_tokens=300,
        messages=[{"role": "user", "content": build_summary_prompt(ticket, known_bugs)}],
    )
    record = parse_summary(claude_utils.extract_text(msg), ticket["conversation_id"], valid_slugs)
    # customer is deterministic conversation data, not something Haiku should guess
    record["customer"] = ticket.get("customer") or ""
    return record


def summarize_mailbox(tickets: list[dict], client, *, known_bugs: list | None = None, max_workers: int = 8) -> list[dict]:
    """Fan out one summary call per ticket; isolate failures; preserve input order."""
    results: list[Any] = [None] * len(tickets)

    def _one(index: int, ticket: dict) -> None:
        try:
            results[index] = summarize_ticket(client, ticket, known_bugs)
        except Exception:
            fallback = parse_summary("", ticket["conversation_id"])
            fallback["customer"] = ticket.get("customer") or ""
            results[index] = fallback

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = [pool.submit(_one, i, t) for i, t in enumerate(tickets)]
        for f in futures:
            f.result()
    return results


# --- Open-ticket fetch (thin, monkeypatchable wrappers around triage_tickets) ---

def _list_conversations(session, mailbox_id: int | None, status: str) -> list[dict]:
    """Page through ALL matching conversations (Help Scout returns 25/page)."""
    url = f"{triage_tickets.BASE_URL}/conversations"
    conversations: list[dict] = []
    page = 1
    while True:
        params = {"status": status, "page": page}
        if mailbox_id:
            params["mailbox"] = mailbox_id
        data = triage_tickets.api_get(session, url, params=params)
        batch = (data.get("_embedded", {}) or {}).get("conversations", []) or []
        conversations.extend(batch)
        page_info = data.get("page", {}) or {}
        total_pages = page_info.get("totalPages")
        # Stop when we've read the last page (or got an empty/short batch as a safety net).
        if total_pages is not None:
            if page >= total_pages:
                break
        elif not batch:
            break
        page += 1
    return conversations


def _conversation_text(session, conversation_id: int) -> str:
    return triage_tickets.get_conversation_text(session, conversation_id) or ""


def _tag_names(tags_field) -> list[str]:
    names = []
    for t in tags_field or []:
        if isinstance(t, dict):
            names.append(t.get("tag") or t.get("name") or "")
        elif isinstance(t, str):
            names.append(t)
    return [n for n in names if n]


def _customer_name(convo: dict) -> str:
    import orchestrator
    return orchestrator._customer_display_name(orchestrator._customer_from_conversation(convo))


def fetch_open_tickets(session, mailbox_id: int | None = None, *, status: str = "active") -> list[dict]:
    """Return open conversations as ticket dicts: {conversation_id, customer, subject, body, tags}."""
    tickets = []
    for convo in _list_conversations(session, mailbox_id, status):
        cid = convo.get("id")
        tickets.append({
            "conversation_id": cid,
            "customer": _customer_name(convo),
            "subject": convo.get("subject") or "(no subject)",
            "body": _conversation_text(session, cid),
            "tags": _tag_names(convo.get("tags")),
        })
    return tickets


def main() -> None:
    import bert.render as render
    import bert.state as state

    token = triage_tickets.get_access_token()
    session = requests.Session()
    session.headers.update({"Authorization": f"Bearer {token}"})
    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

    tickets = fetch_open_tickets(session)
    records = summarize_mailbox(tickets, client, known_bugs=known_bug_catalog())

    today = date.today().isoformat()
    s = state.load(today)
    state.set_records(s, records)
    state.save(s)

    html = render.render_summary_html(s)
    out_dir = os.path.join(state.DEFAULT_BASE_DIR, "artifacts")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, f"{today}.html")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"Summarized {len(records)} tickets → state {state.state_path(today)}")
    print(f"Artifact: {out_path}")


if __name__ == "__main__":
    main()
