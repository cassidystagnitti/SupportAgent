"""Fix reply tickets: delete bad drafts and re-run with is_reply=True.

The test_run.py ran all tickets without is_reply=True, so reply conversations
got drafts responding to the original message instead of the latest reply.

This script:
1. Reads results.json to find all tickets
2. Checks each conversation's threads to detect actual replies (has prior agent messages)
3. Deletes the bad draft thread from Help Scout
4. Re-runs the pipeline with is_reply=True
5. Updates results.json with corrected results
"""

from __future__ import annotations

import json
import os
import sys
import time

import requests
from dotenv import load_dotenv

_DIR = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_DIR)
load_dotenv(os.path.join(_DIR, ".env"))
load_dotenv(os.path.join(_ROOT, ".env"))

os.environ["CLAUDE_DRAFT_MODEL"] = "claude-sonnet-5"

from triage_tickets import BASE_URL, get_access_token, _fetch_all_threads  # noqa: E402
from orchestrator import process_ticket_sync  # noqa: E402

RESULTS_PATH = os.path.join(_DIR, "eval", "2026-07-02", "results.json")


def _is_reply_conversation(session: requests.Session, conversation_id: int) -> bool:
    threads = _fetch_all_threads(session, conversation_id)
    for t in threads:
        if t.get("type") == "message" and t.get("state") == "published":
            return True
    return False


def _find_draft_thread_id(session: requests.Session, conversation_id: int) -> int | None:
    threads = _fetch_all_threads(session, conversation_id)
    for t in threads:
        if t.get("type") == "message" and t.get("state") == "draft":
            return t.get("id")
    return None


def _delete_thread(session: requests.Session, conversation_id: int, thread_id: int) -> bool:
    url = f"{BASE_URL}/conversations/{conversation_id}/threads/{thread_id}"
    resp = session.delete(url)
    if resp.status_code == 204:
        return True
    if resp.status_code == 429:
        retry_after = int(resp.headers.get("Retry-After", 10))
        print(f"  Rate limited — waiting {retry_after}s")
        time.sleep(retry_after)
        resp = session.delete(url)
        return resp.status_code == 204
    print(f"  Delete failed: {resp.status_code} {resp.text[:200]}")
    return False


def main() -> None:
    with open(RESULTS_PATH) as f:
        results = json.load(f)

    token = get_access_token()
    session = requests.Session()
    session.headers.update({"Authorization": f"Bearer {token}"})

    print(f"Loaded {len(results)} results. Checking for reply conversations...\n")

    reply_results = []
    for r in results:
        cid = int(r["conversation_id"])
        if _is_reply_conversation(session, cid):
            reply_results.append(r)

    print(f"Found {len(reply_results)} reply conversations that need re-drafting.\n")

    if not reply_results:
        print("Nothing to fix.")
        return

    results_by_cid = {r["conversation_id"]: r for r in results}
    fixed = 0
    failed = 0

    for i, r in enumerate(reply_results, 1):
        cid = r["conversation_id"]
        cid_int = int(cid)
        subject = r.get("ticket_subject", "(no subject)")
        email = r.get("customer_email")
        print(f"[{i}/{len(reply_results)}] #{cid} — {subject[:60]}")

        draft_thread_id = _find_draft_thread_id(session, cid_int)
        if draft_thread_id:
            if _delete_thread(session, cid_int, draft_thread_id):
                print(f"  Deleted bad draft thread {draft_thread_id}")
            else:
                print(f"  WARNING: Could not delete draft thread {draft_thread_id}")
        else:
            print(f"  No draft thread found (may have been manually deleted)")

        try:
            new_result = process_ticket_sync(cid, email, skip_triage=True, is_reply=True)
            new_result["ticket_subject"] = r.get("ticket_subject")
            new_result["ticket_body"] = r.get("ticket_body")

            status = "draft_created" if new_result.get("draft_created") else "no_draft"
            if new_result.get("escalated"):
                status = "escalated"
            print(f"  Re-drafted: {status} | conf={new_result.get('confidence')} | {new_result.get('latency_ms', '?')}ms")

            results_by_cid[cid] = new_result
            fixed += 1
        except Exception as exc:
            print(f"  ERROR re-drafting: {exc}")
            failed += 1

    updated_results = list(results_by_cid.values())
    updated_results.sort(key=lambda r: int(r.get("conversation_id", 0) or 0))

    with open(RESULTS_PATH, "w") as f:
        json.dump(updated_results, f, indent=2, default=str)

    print(f"\nDone. {fixed} fixed, {failed} failed out of {len(reply_results)} reply conversations.")
    print(f"Updated {RESULTS_PATH}")


if __name__ == "__main__":
    main()
