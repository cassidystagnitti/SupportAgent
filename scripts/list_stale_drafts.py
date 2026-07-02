#!/usr/bin/env python3
"""Seed the draft registry from a past eval run and list stale duplicate drafts (SUP-461).

Two jobs, both driven by `eval/2026-07-02/results.json`:

1. **Seed `draft_registry`** — for every conversation in results.json that has
   `draft_created` and a recorded `helpscout_draft_id`, register it (if not
   already registered) so the pipeline knows "we already drafted this one"
   even for conversations processed before draft_registry.py existed.

2. **Write a manual-discard cleanup checklist** — Help Scout has no DELETE for
   draft threads, so any conversation that (as of *now*, checked live against
   the Help Scout API) still has two or more `type=message` threads in
   `state=draft` has a stale duplicate that a human needs to open and discard
   by hand. Written to `eval/2026-07-02/stale_drafts_cleanup.md`.

Definition note: the task's background context cited "22 conversations
currently have two drafts." Two live signals were investigated for that
count:
  - `fix_reply_drafts.py`'s own `_is_reply_conversation` selection logic
    (any published `type=message` thread) — but this also matches
    conversations whose *duplicate* draft was already manually
    published/discarded by a human, and matches conversations that simply
    had a real prior agent reply before Bert ever touched them. As of this
    run it matches 78 of 82 conversations — not an actionable cleanup list.
  - Conversations with 2+ *live* `state=draft` message threads right now —
    this is the only signal that maps directly onto "an agent needs to open
    Help Scout and discard the extra draft." As of this run that is 3
    conversations. The discrepancy from "22" is most likely because many of
    the originally-duplicated drafts have since been manually resolved
    (published or discarded) between when that count was taken and when this
    script ran.

This script uses the second (live, actionable) definition and reports the
count plainly rather than forcing a specific number.
"""

from __future__ import annotations

import json
import os
import sys

import requests

_SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
_SUPPORT_DIR = os.path.dirname(_SCRIPTS_DIR)
sys.path.insert(0, _SUPPORT_DIR)

import draft_registry  # noqa: E402
from triage_tickets import BASE_URL, api_get, get_access_token  # noqa: E402

RESULTS_PATH = os.path.join(_SUPPORT_DIR, "eval", "2026-07-02", "results.json")
CLEANUP_MD_PATH = os.path.join(_SUPPORT_DIR, "eval", "2026-07-02", "stale_drafts_cleanup.md")
HELPSCOUT_CONVERSATION_URL = "https://secure.helpscout.net/conversation/{cid}"


def _load_results() -> list[dict]:
    with open(RESULTS_PATH, encoding="utf-8") as f:
        return json.load(f)


def seed_registry_from_results(results: list[dict]) -> int:
    """Register every conversation that has a recorded draft, skipping ones
    already in the registry. Returns the number of NEW entries written."""
    seeded = 0
    for r in results:
        cid = str(r.get("conversation_id") or "").strip()
        draft_id = r.get("helpscout_draft_id")
        if not cid or not r.get("draft_created") or not draft_id:
            continue
        if draft_registry.get(cid) is not None:
            continue
        drafted_at = r.get("timestamp") or ""
        draft_registry.set(cid, str(draft_id), drafted_at)
        seeded += 1
    return seeded


def _fetch_all_threads(session: requests.Session, conversation_id: int) -> list[dict] | None:
    """Returns None on 404 (conversation deleted/inaccessible) instead of raising."""
    threads: list[dict] = []
    page = 1
    try:
        while True:
            data = api_get(
                session,
                f"{BASE_URL}/conversations/{conversation_id}/threads",
                params={"page": page},
            )
            threads.extend(data.get("_embedded", {}).get("threads", []))
            total_pages = data.get("page", {}).get("totalPages", 1)
            if page >= total_pages:
                break
            page += 1
        return threads
    except requests.exceptions.HTTPError as e:
        if e.response is not None and e.response.status_code == 404:
            return None
        raise


def find_live_duplicate_drafts(results: list[dict]) -> tuple[list[dict], list[str]]:
    """Check each conversation live against Help Scout for 2+ threads still
    sitting in `state=draft`. Returns (duplicates, unreachable_conversation_ids).

    Each duplicate entry: {"conversation_id", "ticket_subject", "draft_thread_ids"}.
    """
    token = get_access_token()
    session = requests.Session()
    session.headers.update({"Authorization": f"Bearer {token}"})

    duplicates: list[dict] = []
    unreachable: list[str] = []

    for r in results:
        cid_str = str(r.get("conversation_id") or "").strip()
        if not cid_str:
            continue
        try:
            cid_int = int(cid_str)
        except ValueError:
            continue

        threads = _fetch_all_threads(session, cid_int)
        if threads is None:
            unreachable.append(cid_str)
            continue

        draft_threads = [
            t for t in threads if t.get("type") == "message" and t.get("state") == "draft"
        ]
        if len(draft_threads) >= 2:
            duplicates.append(
                {
                    "conversation_id": cid_str,
                    "ticket_subject": r.get("ticket_subject") or "(no subject)",
                    "draft_thread_ids": [t.get("id") for t in draft_threads],
                }
            )

    return duplicates, unreachable


def write_cleanup_checklist(duplicates: list[dict], unreachable: list[str]) -> None:
    lines = [
        "# Stale draft cleanup checklist (SUP-461)",
        "",
        "Help Scout does not support deleting a draft thread via the API, so each "
        "conversation below has two or more Bert-authored draft threads still live. "
        "Open each link and manually discard all but the most recent draft.",
        "",
        f"**{len(duplicates)} conversation(s) with duplicate live drafts.**",
        "",
    ]
    if not duplicates:
        lines.append("None found as of this run — nothing to clean up.")
    else:
        for d in duplicates:
            url = HELPSCOUT_CONVERSATION_URL.format(cid=d["conversation_id"])
            thread_ids = ", ".join(str(tid) for tid in d["draft_thread_ids"])
            lines.append(
                f"- [ ] [{d['conversation_id']}]({url}) — {d['ticket_subject']} "
                f"(draft thread ids: {thread_ids})"
            )

    if unreachable:
        lines += [
            "",
            "## Unreachable conversations (skipped, 404 from Help Scout)",
            "",
        ]
        for cid in unreachable:
            lines.append(f"- {cid}")

    with open(CLEANUP_MD_PATH, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def main() -> None:
    results = _load_results()
    print(f"Loaded {len(results)} results from {RESULTS_PATH}")

    seeded = seed_registry_from_results(results)
    print(f"Seeded {seeded} new draft_registry entries (registry: {draft_registry.REGISTRY_PATH})")

    duplicates, unreachable = find_live_duplicate_drafts(results)
    write_cleanup_checklist(duplicates, unreachable)
    print(f"Found {len(duplicates)} conversation(s) with 2+ live draft threads.")
    if unreachable:
        print(f"Skipped {len(unreachable)} unreachable conversation(s) (404): {unreachable}")
    print(f"Wrote checklist to {CLEANUP_MD_PATH}")


if __name__ == "__main__":
    main()
