"""
Fetch all saved replies from Help Scout and write a local JSON snapshot for embedding/indexing.

Uses separate OAuth app credentials from triage so production triage rate limits stay isolated.

Environment (required for this script):
  HELPSCOUT_INDEX_APP_ID
  HELPSCOUT_INDEX_APP_SECRET

Run from repo root:
  .venv/bin/python pull_saved_replies.py --list-mailboxes
  .venv/bin/python pull_saved_replies.py
  (default mailbox: 185235 — 1. Happier Support)
  .venv/bin/python pull_saved_replies.py --mailbox-id 12345
  .venv/bin/python pull_saved_replies.py --all-mailboxes --output data/saved_replies.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone

import requests
from dotenv import load_dotenv

from triage_tickets import strip_html

_SUPPORT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(_SUPPORT_DIR)
load_dotenv(os.path.join(_SUPPORT_DIR, ".env"))
load_dotenv(os.path.join(ROOT_DIR, ".env"))

BASE_URL = "https://api.helpscout.net/v2"
TOKEN_URL = f"{BASE_URL}/oauth2/token"

INDEX_APP_ID = os.getenv("HELPSCOUT_INDEX_APP_ID")
INDEX_APP_SECRET = os.getenv("HELPSCOUT_INDEX_APP_SECRET")

# Default inbox when neither --mailbox-id nor --all-mailboxes is passed (1. Happier Support).
DEFAULT_MAILBOX_ID = 185235


def get_access_token(app_id: str, app_secret: str) -> str:
    resp = requests.post(
        TOKEN_URL,
        data={
            "grant_type": "client_credentials",
            "client_id": app_id,
            "client_secret": app_secret,
        },
        timeout=60,
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


def api_get(session: requests.Session, url: str, params: dict | None = None):
    while True:
        resp = session.get(url, params=params, timeout=120)
        if resp.status_code == 429:
            retry_after = int(resp.headers.get("Retry-After", 10))
            print(f"  Rate limited — waiting {retry_after}s …")
            time.sleep(retry_after)
            continue
        resp.raise_for_status()
        return resp.json()


def _embedded_rows(payload) -> list:
    """Normalize Help Scout list responses (plain array or HAL _embedded)."""
    if isinstance(payload, list):
        return payload
    embedded = payload.get("_embedded") or {}
    rows: list = []
    for v in embedded.values():
        if isinstance(v, list) and v:
            # Prefer the longest list if multiple (e.g. links vs items)
            if len(v) > len(rows):
                rows = v
    return rows


def _total_pages(payload) -> int:
    if isinstance(payload, list):
        return 1
    page = payload.get("page") or {}
    return max(1, int(page.get("totalPages") or 1))


def list_all_saved_reply_summaries(
    session: requests.Session,
    mailbox_id: int,
    *,
    include_chat: bool,
) -> list[dict]:
    summaries: list[dict] = []
    first = api_get(
        session,
        f"{BASE_URL}/mailboxes/{mailbox_id}/saved-replies",
        params={
            "page": 1,
            **({"includeChatReplies": "true"} if include_chat else {}),
        },
    )
    summaries.extend(_embedded_rows(first))
    for p in range(2, _total_pages(first) + 1):
        data = api_get(
            session,
            f"{BASE_URL}/mailboxes/{mailbox_id}/saved-replies",
            params={
                "page": p,
                **({"includeChatReplies": "true"} if include_chat else {}),
            },
        )
        summaries.extend(_embedded_rows(data))
    return summaries


def fetch_saved_reply_detail(
    session: requests.Session,
    mailbox_id: int,
    saved_reply_id: int,
) -> dict:
    return api_get(
        session,
        f"{BASE_URL}/mailboxes/{mailbox_id}/saved-replies/{saved_reply_id}",
    )


def fetch_mailboxes(session: requests.Session) -> list[dict]:
    data = api_get(session, f"{BASE_URL}/mailboxes")
    return data.get("_embedded", {}).get("mailboxes", [])


def pull_mailbox(
    session: requests.Session,
    mailbox_id: int,
    mailbox_name: str | None,
    *,
    include_chat: bool,
    detail_batch_size: int,
    batch_pause_sec: float,
) -> dict:
    print(f"Mailbox {mailbox_id}" + (f" ({mailbox_name})" if mailbox_name else "") + " — listing saved replies …")
    summaries = list_all_saved_reply_summaries(session, mailbox_id, include_chat=include_chat)
    print(f"  {len(summaries)} saved replies in list API.")

    replies: list[dict] = []
    for i in range(0, len(summaries), detail_batch_size):
        chunk = summaries[i : i + detail_batch_size]
        for s in chunk:
            rid = s["id"]
            detail = fetch_saved_reply_detail(session, mailbox_id, rid)
            text = (detail.get("text") or "").strip()
            chat_text = (detail.get("chatText") or "").strip()
            replies.append(
                {
                    "id": detail.get("id"),
                    "mailbox_id": mailbox_id,
                    "name": detail.get("name") or s.get("name"),
                    "text": text,
                    "text_plain": strip_html(text) if text else "",
                    "chat_text": chat_text,
                    "chat_text_plain": chat_text,
                }
            )
        done = min(i + detail_batch_size, len(summaries))
        print(f"  fetched details {done}/{len(summaries)}")
        if batch_pause_sec > 0 and i + detail_batch_size < len(summaries):
            time.sleep(batch_pause_sec)

    return {
        "id": mailbox_id,
        "name": mailbox_name,
        "saved_replies": replies,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Pull Help Scout saved replies into a local JSON file.")
    parser.add_argument(
        "--list-mailboxes",
        action="store_true",
        help="Print mailbox id and name for each inbox (index app creds), then exit.",
    )
    parser.add_argument(
        "--output",
        "-o",
        default=os.path.join(_SUPPORT_DIR, "data", "saved_replies.json"),
        help="Output JSON path (default: data/saved_replies.json)",
    )
    parser.add_argument(
        "--mailbox-id",
        type=int,
        action="append",
        dest="mailbox_ids",
        metavar="ID",
        help="Mailbox ID to pull (repeat for multiple). Default: mailbox 185235 (Happier Support).",
    )
    parser.add_argument(
        "--all-mailboxes",
        action="store_true",
        help="Pull every mailbox in the account.",
    )
    parser.add_argument(
        "--no-chat-replies",
        action="store_true",
        help="Omit chat-only saved replies (default: include them).",
    )
    parser.add_argument(
        "--detail-batch-size",
        type=int,
        default=25,
        metavar="N",
        help="Number of detail GETs before optional pause (default: 25).",
    )
    parser.add_argument(
        "--batch-pause-sec",
        type=float,
        default=0.0,
        metavar="SEC",
        help="Sleep this many seconds between detail batches (default: 0).",
    )
    args = parser.parse_args()

    if not INDEX_APP_ID or not INDEX_APP_SECRET:
        print(
            "Error: set HELPSCOUT_INDEX_APP_ID and HELPSCOUT_INDEX_APP_SECRET in .env.\n"
            "Use a separate Help Scout OAuth app from production triage so rate limits are not shared.",
            file=sys.stderr,
        )
        sys.exit(1)

    include_chat = not args.no_chat_replies

    print("Authenticating (index app) …")
    token = get_access_token(INDEX_APP_ID, INDEX_APP_SECRET)
    session = requests.Session()
    session.headers.update({"Authorization": f"Bearer {token}"})

    mailboxes = fetch_mailboxes(session)
    if not mailboxes:
        print("Error: no mailboxes returned by API.", file=sys.stderr)
        sys.exit(1)

    if args.list_mailboxes:
        name_key = lambda m: ((m.get("name") or "").lower(), m["id"])
        print("id\tname")
        for m in sorted(mailboxes, key=name_key):
            print(f"{m['id']}\t{m.get('name', '')}")
        return

    if args.all_mailboxes:
        targets = [(m["id"], m.get("name")) for m in mailboxes]
    elif args.mailbox_ids:
        wanted = set(args.mailbox_ids)
        targets = [(m["id"], m.get("name")) for m in mailboxes if m["id"] in wanted]
        missing = wanted - {t[0] for t in targets}
        if missing:
            print(f"Warning: mailbox IDs not found in account: {sorted(missing)}", file=sys.stderr)
    else:
        m = next((mb for mb in mailboxes if mb["id"] == DEFAULT_MAILBOX_ID), None)
        if not m:
            print(
                f"Error: default mailbox ID {DEFAULT_MAILBOX_ID} not in this account. "
                "Use --list-mailboxes or --mailbox-id.",
                file=sys.stderr,
            )
            sys.exit(1)
        targets = [(m["id"], m.get("name"))]
        print(
            f"Using default mailbox: \"{m.get('name')}\" (ID {m['id']}). "
            "Override with --mailbox-id or --all-mailboxes."
        )

    payload = {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "source": "helpscout_mailbox_api",
        "include_chat_replies": include_chat,
        "mailboxes": [],
    }

    for mid, mname in targets:
        payload["mailboxes"].append(
            pull_mailbox(
                session,
                mid,
                mname,
                include_chat=include_chat,
                detail_batch_size=max(1, args.detail_batch_size),
                batch_pause_sec=max(0.0, args.batch_pause_sec),
            )
        )

    out_path = os.path.abspath(args.output)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
        f.write("\n")

    total = sum(len(mb["saved_replies"]) for mb in payload["mailboxes"])
    print(f"Wrote {total} saved replies to {out_path}")


if __name__ == "__main__":
    main()
