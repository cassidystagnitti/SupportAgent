"""One-off eval runner: generate Claude Sonnet 5 drafts for all active tickets and save results.

Similar to batch_maven_drafts.py, but:
  - Forces CLAUDE_DRAFT_MODEL=claude-sonnet-5 (set before importing orchestrator).
  - Captures the original ticket subject/body text alongside each pipeline result.
  - Writes results to eval/2026-07-02/results.json instead of stdout.
"""

from __future__ import annotations

import json
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from dotenv import load_dotenv
import os

_DIR = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_DIR)
load_dotenv(os.path.join(_DIR, ".env"))
load_dotenv(os.path.join(_ROOT, ".env"))

# Must be set before importing orchestrator — it reads this env var at import time.
os.environ["CLAUDE_DRAFT_MODEL"] = "claude-sonnet-5"

from triage_tickets import BASE_URL, get_access_token, api_get, get_conversation_text  # noqa: E402
from orchestrator import process_ticket_sync  # noqa: E402

MAILBOX_ID = os.getenv("BATCH_MAILBOX_ID", "185235")
MAX_WORKERS = 5
OUTPUT_PATH = os.path.join(_DIR, "eval", "2026-07-02", "results.json")

_print_lock = threading.Lock()


def _log(msg: str, *, err: bool = False) -> None:
    with _print_lock:
        print(msg, file=sys.stderr if err else sys.stdout, flush=True)


def fetch_active_conversations(session: requests.Session, mailbox_id: str) -> list[dict]:
    convos = []
    page = 1
    while True:
        data = api_get(session, f"{BASE_URL}/conversations", params={
            "status": "active",
            "mailbox": mailbox_id,
            "sortField": "createdAt",
            "sortOrder": "desc",
            "page": page,
        })
        page_convos = data.get("_embedded", {}).get("conversations", [])
        convos.extend(page_convos)
        total_pages = data.get("page", {}).get("totalPages", 1)
        _log(f"  Page {page}/{total_pages}: {len(page_convos)} conversations")
        if page >= total_pages:
            break
        page += 1
    return convos


def process_one(i: int, total: int, convo: dict) -> dict:
    cid = str(convo["id"])
    subject = convo.get("subject", "(no subject)")
    customer = (
        convo.get("customer")
        or convo.get("primaryCustomer")
        or (convo.get("_embedded") or {}).get("primaryCustomer")
        or {}
    )
    email = customer.get("email")
    _log(f"[{i}/{total}] #{cid} — {subject[:70]}")
    try:
        result = process_ticket_sync(cid, email, skip_triage=True)
        status = "draft_created" if result.get("draft_created") else "no_draft"
        if result.get("escalated"):
            status = "escalated"
        if result.get("error"):
            status = f"error: {result['error'][:80]}"
        _log(f"  → #{cid} {status} | {result.get('latency_ms', '?')}ms")
    except Exception as exc:
        _log(f"  → #{cid} EXCEPTION: {exc}", err=True)
        result = {"conversation_id": cid, "error": str(exc)}

    # Enrich with the original ticket text for eval purposes.
    try:
        session = requests.Session()
        session.headers.update({"Authorization": f"Bearer {get_access_token()}"})
        ticket_body = get_conversation_text(session, int(cid))
    except Exception as exc:
        _log(f"  → #{cid} failed to fetch ticket text: {exc}", err=True)
        ticket_body = None

    result["ticket_subject"] = subject
    result["ticket_body"] = ticket_body
    return result


def main() -> None:
    token = get_access_token()
    session = requests.Session()
    session.headers.update({"Authorization": f"Bearer {token}"})

    _log(f"Fetching active conversations in mailbox {MAILBOX_ID} …")
    convos = fetch_active_conversations(session, MAILBOX_ID)
    total = len(convos)
    _log(f"Found {total} conversation(s). Running {MAX_WORKERS} workers.\n")

    if not convos:
        _log("Nothing to do.")
        return

    results: list[dict] = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {
            pool.submit(process_one, i, total, convo): convo
            for i, convo in enumerate(convos, 1)
        }
        for future in as_completed(futures):
            results.append(future.result())

    results.sort(key=lambda r: int(r.get("conversation_id", 0) or 0))

    drafts = sum(1 for r in results if r.get("draft_created"))
    escalated = sum(1 for r in results if r.get("escalated"))
    errors = sum(1 for r in results if r.get("error"))
    _log(f"\nDone. {drafts} draft(s) created, {escalated} escalated, {errors} error(s) out of {total}.")

    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "w") as f:
        json.dump(results, f, indent=2, default=str)
    _log(f"Saved {len(results)} result(s) to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
