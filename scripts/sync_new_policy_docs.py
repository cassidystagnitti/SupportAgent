#!/usr/bin/env python3
"""Sync specific policies/*.md files to Notion as child pages.

Creates (or updates, if a same-titled child page already exists) a Notion
child page under the Support Policy Docs page for each markdown file given.
Rerunnable: re-running with the same docs will not create duplicates — it
detects an existing child page by title, clears its content, and re-appends.

Mirrors the Notion API auth/header pattern used by pull_policy_docs.py.

Environment:
  NOTION_TOKEN          — Notion integration secret (required)
  NOTION_VERSION        — API version header (default: 2022-06-28)

Usage:
  python scripts/sync_new_policy_docs.py
  python scripts/sync_new_policy_docs.py --dry-run
  python scripts/sync_new_policy_docs.py policies/known-bugs.md policies/downloads-offline.md
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from typing import Any

import requests
from dotenv import load_dotenv

_SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
_SUPPORT_DIR = os.path.dirname(_SCRIPTS_DIR)
_ROOT_DIR = os.path.dirname(_SUPPORT_DIR)
load_dotenv(os.path.join(_SUPPORT_DIR, ".env"))
load_dotenv(os.path.join(_ROOT_DIR, ".env"))

NOTION_API = "https://api.notion.com/v1"
SUPPORT_POLICY_DOCS_PAGE_ID = "356cffdf527f808da4fcf7d05499523f"

# Notion API limits
MAX_BLOCKS_PER_REQUEST = 100
MAX_RICH_TEXT_CHARS = 2000

DEFAULT_DOCS = [
    "policies/known-bugs.md",
    "policies/downloads-offline.md",
    "policies/check-ins-goals-intentions.md",
    "policies/non-support-requests.md",
]


def _notion_headers() -> dict[str, str]:
    token = (os.getenv("NOTION_TOKEN") or "").strip()
    if not token:
        print("Set NOTION_TOKEN to a Notion integration token.", file=sys.stderr)
        sys.exit(2)
    version = (os.getenv("NOTION_VERSION") or "2022-06-28").strip()
    return {
        "Authorization": f"Bearer {token}",
        "Notion-Version": version,
        "Content-Type": "application/json",
    }


def _request(
    session: requests.Session, method: str, url: str, **kwargs: Any
) -> requests.Response:
    while True:
        r = session.request(method, url, timeout=60, **kwargs)
        if r.status_code == 429:
            time.sleep(int(r.headers.get("Retry-After", 3)))
            continue
        if not r.ok:
            print(f"Notion API error {r.status_code} for {method} {url}", file=sys.stderr)
            print(r.text, file=sys.stderr)
        r.raise_for_status()
        return r


def _title_from_markdown(path: str) -> str:
    """First '# Heading' line is the title; fall back to filename."""
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line.startswith("# "):
                return line[2:].strip()
    base = os.path.basename(path)
    return os.path.splitext(base)[0].replace("-", " ").title()


def _split_rich_text(text: str) -> list[dict[str, Any]]:
    """Split text into <=2000-char rich_text objects (Notion per-object cap)."""
    if not text:
        return [{"type": "text", "text": {"content": ""}}]
    chunks = [
        text[i : i + MAX_RICH_TEXT_CHARS]
        for i in range(0, len(text), MAX_RICH_TEXT_CHARS)
    ] or [""]
    return [{"type": "text", "text": {"content": c}} for c in chunks]


def _rich_text_block(block_type: str, text: str, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {"rich_text": _split_rich_text(text)}
    if extra:
        payload.update(extra)
    return {"object": "block", "type": block_type, block_type: payload}


def _markdown_to_blocks(markdown: str) -> list[dict[str, Any]]:
    """Convert markdown to a flat list of Notion block objects.

    Rules:
      # heading      -> heading_1
      ## heading     -> heading_2
      ### heading    -> heading_3
      - / * bullet   -> bulleted_list_item
      table (| ... |, contiguous lines) -> single code block (plain text table)
      everything else (non-blank)       -> paragraph
      blank lines / other markdown noise (---, blank) are skipped as separators
    """
    lines = markdown.splitlines()
    blocks: list[dict[str, Any]] = []
    i = 0
    n = len(lines)

    while i < n:
        raw = lines[i]
        line = raw.rstrip()
        stripped = line.strip()

        if not stripped:
            i += 1
            continue

        # Table: contiguous run of lines starting with '|'
        if stripped.startswith("|"):
            table_lines: list[str] = []
            while i < n and lines[i].strip().startswith("|"):
                table_lines.append(lines[i].rstrip())
                i += 1
            table_text = "\n".join(table_lines)
            blocks.append(
                _rich_text_block(
                    "code",
                    table_text[: MAX_RICH_TEXT_CHARS * 1],  # single object below handles chunking
                    extra={"language": "plain text"},
                )
            )
            # code block rich_text can also exceed 2000 chars; reuse splitter
            blocks[-1]["code"]["rich_text"] = _split_rich_text(table_text)
            continue

        # Divider
        if stripped in ("---", "***", "___"):
            blocks.append({"object": "block", "type": "divider", "divider": {}})
            i += 1
            continue

        # Headings
        if stripped.startswith("### "):
            blocks.append(_rich_text_block("heading_3", stripped[4:].strip()))
            i += 1
            continue
        if stripped.startswith("## "):
            blocks.append(_rich_text_block("heading_2", stripped[3:].strip()))
            i += 1
            continue
        if stripped.startswith("# "):
            blocks.append(_rich_text_block("heading_1", stripped[2:].strip()))
            i += 1
            continue

        # Bullets
        if stripped.startswith("- ") or stripped.startswith("* "):
            blocks.append(_rich_text_block("bulleted_list_item", stripped[2:].strip()))
            i += 1
            continue
        if stripped in ("-", "*"):
            blocks.append(_rich_text_block("bulleted_list_item", ""))
            i += 1
            continue

        # Numbered list (bonus: treat like Notion numbered_list_item)
        if len(stripped) > 2 and stripped[0].isdigit():
            dot = stripped.find(". ")
            if dot != -1 and stripped[:dot].isdigit():
                blocks.append(_rich_text_block("numbered_list_item", stripped[dot + 2 :].strip()))
                i += 1
                continue

        # Default: paragraph
        blocks.append(_rich_text_block("paragraph", stripped))
        i += 1

    return blocks


def _chunked(seq: list[Any], size: int) -> list[list[Any]]:
    return [seq[i : i + size] for i in range(0, len(seq), size)]


def _list_children(session: requests.Session, block_id: str) -> list[dict[str, Any]]:
    block_id = block_id.replace("-", "")
    out: list[dict[str, Any]] = []
    cursor = None
    while True:
        params: dict[str, Any] = {"page_size": 100}
        if cursor:
            params["start_cursor"] = cursor
        url = f"{NOTION_API}/blocks/{block_id}/children"
        r = _request(session, "GET", url, params=params)
        data = r.json()
        out.extend(data.get("results") or [])
        if not data.get("has_more"):
            break
        cursor = data.get("next_cursor")
    return out


def _find_existing_child_page(
    session: requests.Session, parent_id: str, title: str
) -> str | None:
    for block in _list_children(session, parent_id):
        if block.get("type") == "child_page":
            existing_title = ((block.get("child_page") or {}).get("title") or "").strip()
            if existing_title == title:
                return str(block.get("id"))
    return None


def _create_child_page(session: requests.Session, parent_id: str, title: str) -> str:
    url = f"{NOTION_API}/pages"
    body = {
        "parent": {"type": "page_id", "page_id": parent_id},
        "properties": {
            "title": {"title": [{"type": "text", "text": {"content": title}}]}
        },
    }
    r = _request(session, "POST", url, json=body)
    return str(r.json()["id"])


def _delete_all_children(session: requests.Session, page_id: str) -> None:
    """Archive (delete) all existing children of a page so it can be re-populated."""
    for block in _list_children(session, page_id):
        block_id = block.get("id")
        if not block_id:
            continue
        url = f"{NOTION_API}/blocks/{block_id}"
        _request(session, "DELETE", url)


def _append_blocks(session: requests.Session, page_id: str, blocks: list[dict[str, Any]]) -> None:
    page_id = page_id.replace("-", "")
    for chunk in _chunked(blocks, MAX_BLOCKS_PER_REQUEST):
        url = f"{NOTION_API}/blocks/{page_id}/children"
        _request(session, "PATCH", url, json={"children": chunk})


def sync_doc(session: requests.Session, parent_id: str, path: str, dry_run: bool = False) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        markdown = f.read()

    title = _title_from_markdown(path)
    blocks = _markdown_to_blocks(markdown)

    if dry_run:
        print(f"{title!r} <- {path} ({len(blocks)} blocks)")
        return {"title": title, "path": path, "blocks": len(blocks), "action": "dry-run"}

    existing_id = _find_existing_child_page(session, parent_id, title)
    if existing_id:
        _delete_all_children(session, existing_id)
        _append_blocks(session, existing_id, blocks)
        print(f"Updated {title!r} (page {existing_id}) from {path} — {len(blocks)} blocks")
        return {"title": title, "path": path, "page_id": existing_id, "action": "updated"}

    page_id = _create_child_page(session, parent_id, title)
    _append_blocks(session, page_id, blocks)
    print(f"Created {title!r} (page {page_id}) from {path} — {len(blocks)} blocks")
    return {"title": title, "path": path, "page_id": page_id, "action": "created"}


def main() -> None:
    parser = argparse.ArgumentParser(description="Sync policy markdown docs to Notion child pages.")
    parser.add_argument(
        "docs",
        nargs="*",
        default=None,
        help="Paths to markdown files to sync (default: the four new policy docs)",
    )
    parser.add_argument(
        "--page-id",
        default=SUPPORT_POLICY_DOCS_PAGE_ID,
        help="Notion parent page ID that will receive the child pages",
    )
    parser.add_argument("--dry-run", action="store_true", help="Print planned blocks only; no API calls that mutate")
    args = parser.parse_args()

    doc_paths = args.docs or [os.path.join(_SUPPORT_DIR, d) if not os.path.isabs(d) else d for d in DEFAULT_DOCS]
    # Normalize default paths relative to repo root if user passed relative custom paths
    resolved = []
    for d in doc_paths:
        if os.path.isabs(d):
            resolved.append(d)
        elif os.path.exists(d):
            resolved.append(os.path.abspath(d))
        else:
            resolved.append(os.path.join(_SUPPORT_DIR, d))
    doc_paths = resolved

    missing = [d for d in doc_paths if not os.path.isfile(d)]
    if missing:
        print(f"Missing files: {missing}", file=sys.stderr)
        sys.exit(2)

    session = requests.Session()
    if not args.dry_run:
        session.headers.update(_notion_headers())

    parent_id = args.page_id.replace("-", "")
    results = []
    for path in doc_paths:
        results.append(sync_doc(session, parent_id, path, dry_run=args.dry_run))

    ok = sum(1 for r in results if r.get("action") in ("created", "updated"))
    print(f"\nDone: {ok}/{len(results)} pages synced.")


if __name__ == "__main__":
    main()
