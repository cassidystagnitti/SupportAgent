#!/usr/bin/env python3
"""
Sync policies/*.md to a Help Scout Docs collection (internal/private — agents only).

Requires env vars:
  HELPSCOUT_DOCS_API_KEY          — Help Scout Docs API key
                                    (Settings → Docs → Your Site → API Keys)
  HELPSCOUT_DOCS_COLLECTION_ID    — ID of the target collection
                                    (run --list-collections to find it)

Usage:
  python3 push_kb_docs.py --list-collections
  python3 push_kb_docs.py --dry-run
  python3 push_kb_docs.py
  python3 push_kb_docs.py --organize   # assign all policy articles to "Support Policies" category
"""

from __future__ import annotations

import argparse
import base64
import os
import sys
import time
from pathlib import Path

import markdown as md_lib
import requests
from dotenv import load_dotenv

_SUPPORT_DIR = Path(__file__).parent
load_dotenv(_SUPPORT_DIR / ".env")
load_dotenv(_SUPPORT_DIR.parent / ".env")

DOCS_API_BASE = "https://docsapi.helpscout.net/v1"
DOCS_API_KEY = os.getenv("HELPSCOUT_DOCS_API_KEY")
COLLECTION_ID = os.getenv("HELPSCOUT_DOCS_COLLECTION_ID")
POLICIES_DIR = _SUPPORT_DIR / "policies"
CATEGORY_NAME = "Support Policies"

WRITE_PAUSE_SEC = 0.3


def _session() -> requests.Session:
    if not DOCS_API_KEY:
        print("Error: HELPSCOUT_DOCS_API_KEY not set.", file=sys.stderr)
        sys.exit(1)
    token = base64.b64encode(f"{DOCS_API_KEY}:x".encode()).decode()
    s = requests.Session()
    s.headers.update({"Authorization": f"Basic {token}"})
    return s


def _get(session: requests.Session, path: str, params: dict | None = None) -> dict:
    resp = session.get(f"{DOCS_API_BASE}{path}", params=params, timeout=30)
    resp.raise_for_status()
    return resp.json()


def _post(session: requests.Session, path: str, payload: dict) -> None:
    resp = session.post(f"{DOCS_API_BASE}{path}", json=payload, timeout=30)
    resp.raise_for_status()


def _put(session: requests.Session, path: str, payload: dict) -> None:
    resp = session.put(f"{DOCS_API_BASE}{path}", json=payload, timeout=30)
    resp.raise_for_status()


def _md_to_html(text: str) -> str:
    return md_lib.markdown(text, extensions=["tables", "fenced_code"])


def _title_from_filename(name: str) -> str:
    return Path(name).stem.replace("-", " ").title()


def list_collections(session: requests.Session) -> list[dict]:
    data = _get(session, "/collections")
    return data.get("collections", {}).get("items", [])


def list_articles(session: requests.Session, collection_id: str) -> list[dict]:
    articles: list[dict] = []
    page = 1
    while True:
        data = _get(
            session,
            f"/collections/{collection_id}/articles",
            {"page": page, "pageSize": 100, "status": "all"},
        )
        info = data.get("articles", {})
        articles.extend(info.get("items", []))
        if page >= int(info.get("pages", 1)):
            break
        page += 1
    return articles


def list_categories(session: requests.Session, collection_id: str) -> list[dict]:
    data = _get(session, f"/collections/{collection_id}/categories")
    return data.get("categories", {}).get("items", [])


def get_or_create_category(session: requests.Session, collection_id: str, name: str) -> str:
    """Return the ID of the named category, creating it if it doesn't exist."""
    for cat in list_categories(session, collection_id):
        if cat.get("name", "").strip().lower() == name.lower():
            print(f"Category already exists: '{name}' (id={cat['id']})")
            return cat["id"]
    print(f"Creating category: '{name}'")
    resp = session.post(
        f"{DOCS_API_BASE}/categories",
        json={"collectionId": collection_id, "name": name},
        timeout=30,
    )
    resp.raise_for_status()
    # Docs API returns 201 with no body; fetch the new category by listing again
    time.sleep(0.5)
    for cat in list_categories(session, collection_id):
        if cat.get("name", "").strip().lower() == name.lower():
            return cat["id"]
    raise RuntimeError(f"Created category '{name}' but couldn't find it in subsequent list call.")


def cmd_list_collections(session: requests.Session) -> None:
    collections = list_collections(session)
    if not collections:
        print("No collections found.")
        return
    print(f"{'ID':<30}  {'Visibility':<12}  Name")
    print("-" * 70)
    for c in collections:
        print(f"{c['id']:<30}  {c.get('visibility', ''):<12}  {c.get('name', '')}")


def cmd_organize(session: requests.Session, collection_id: str) -> None:
    """Assign all policy articles to the Support Policies category."""
    category_id = get_or_create_category(session, collection_id, CATEGORY_NAME)

    policy_titles = {_title_from_filename(p.name) for p in POLICIES_DIR.glob("*.md")}
    articles = list_articles(session, collection_id)

    to_move = [a for a in articles if a.get("name", "").strip() in policy_titles]
    print(f"Policy articles found: {len(to_move)}\n")

    for article in to_move:
        print(f"  MOVE  {article['name']}")
        _put(session, f"/articles/{article['id']}", {"categories": [category_id]})
        time.sleep(WRITE_PAUSE_SEC)

    print(f"\nDone. Moved {len(to_move)} articles into '{CATEGORY_NAME}'.")


def cmd_push(session: requests.Session, collection_id: str, dry_run: bool) -> None:
    category_id = None
    if not dry_run:
        category_id = get_or_create_category(session, collection_id, CATEGORY_NAME)
        print()

    existing = {a["name"].strip(): a for a in list_articles(session, collection_id)}
    print(f"Existing articles in collection: {len(existing)}")

    policy_files = sorted(POLICIES_DIR.glob("*.md"))
    if not policy_files:
        print(f"No .md files found in {POLICIES_DIR}", file=sys.stderr)
        sys.exit(1)
    print(f"Policy docs to sync: {len(policy_files)}\n")

    created = updated = 0
    for path in policy_files:
        title = _title_from_filename(path.name)
        html = _md_to_html(path.read_text(encoding="utf-8"))

        base_payload: dict = {
            "name": title,
            "text": html,
            "status": "published",
        }
        if category_id:
            base_payload["categories"] = [category_id]

        if title in existing:
            article_id = existing[title]["id"]
            print(f"  UPDATE  {title}")
            if not dry_run:
                _put(session, f"/articles/{article_id}", base_payload)
                time.sleep(WRITE_PAUSE_SEC)
            updated += 1
        else:
            print(f"  CREATE  {title}")
            if not dry_run:
                _post(session, "/articles", {**base_payload, "collectionId": collection_id})
                time.sleep(WRITE_PAUSE_SEC)
            created += 1

    suffix = " (dry-run — no changes written)" if dry_run else ""
    print(f"\nDone. Created: {created}  Updated: {updated}{suffix}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Sync support policy docs to Help Scout Docs (internal collection)."
    )
    parser.add_argument(
        "--list-collections",
        action="store_true",
        help="Print all Docs collections and their IDs, then exit.",
    )
    parser.add_argument(
        "--organize",
        action="store_true",
        help=f"Assign all policy articles to the '{CATEGORY_NAME}' category (creating it if needed).",
    )
    parser.add_argument(
        "--collection-id",
        default=COLLECTION_ID,
        metavar="ID",
        help="Target collection ID (overrides HELPSCOUT_DOCS_COLLECTION_ID env var).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be created/updated without making any API calls.",
    )
    args = parser.parse_args()

    session = _session()

    if args.list_collections:
        cmd_list_collections(session)
        return

    collection_id = args.collection_id
    if not collection_id:
        print(
            "Error: set HELPSCOUT_DOCS_COLLECTION_ID in .env or pass --collection-id.\n"
            "Run --list-collections to see available collections.",
            file=sys.stderr,
        )
        sys.exit(1)

    if args.organize:
        cmd_organize(session, collection_id)
    else:
        cmd_push(session, collection_id, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
