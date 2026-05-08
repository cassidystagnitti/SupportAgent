#!/usr/bin/env python3
"""Pull Support Policy pages from Notion into policies/*.md snapshot files.

Manual step after policy updates in Notion. Requires a Notion integration with
read access to the Support Policy Docs page and its descendants.

Environment:
  NOTION_TOKEN          — Notion integration secret (required)
  NOTION_VERSION        — API version header (default: 2022-06-28)

Usage:
  python pull_policy_docs.py
  python pull_policy_docs.py --out-dir ./policies --dry-run
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from typing import Any

import requests
from dotenv import load_dotenv

_SUPPORT_DIR = os.path.dirname(os.path.abspath(__file__))
_ROOT_DIR = os.path.dirname(_SUPPORT_DIR)
load_dotenv(os.path.join(_SUPPORT_DIR, ".env"))
load_dotenv(os.path.join(_ROOT_DIR, ".env"))

NOTION_API = "https://api.notion.com/v1"
SUPPORT_POLICY_DOCS_PAGE_ID = "356cffdf527f808da4fcf7d05499523f"


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


def _sanitize_filename(title: str) -> str:
    s = title.strip().lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    s = re.sub(r"-+", "-", s).strip("-")
    return s or "untitled-policy"


def _rich_text_plain(rich: list[dict[str, Any]] | None) -> str:
    if not rich:
        return ""
    parts: list[str] = []
    for t in rich:
        parts.append(t.get("plain_text", "") or "")
    return "".join(parts)


def _block_to_lines(block: dict[str, Any]) -> list[str]:
    btype = block.get("type")
    payload = block.get(btype) or {}
    rich = payload.get("rich_text") or []
    text = _rich_text_plain(rich).strip()

    if btype == "paragraph":
        return [text] if text else [""]
    if btype == "heading_1":
        return [f"# {text}".strip(), ""]
    if btype == "heading_2":
        return [f"## {text}".strip(), ""]
    if btype == "heading_3":
        return [f"### {text}".strip(), ""]
    if btype == "bulleted_list_item":
        return [f"- {text}".strip()] if text else ["-"]
    if btype == "numbered_list_item":
        return [f"1. {text}".strip()] if text else ["1."]
    if btype == "quote":
        return ([f"> {text}".strip()] if text else [">"])
    if btype == "code":
        lang = (payload.get("language") or "").strip()
        fence = "```" + lang
        body = _rich_text_plain(payload.get("rich_text") or [])
        return [fence, body, "```", ""]
    if btype == "divider":
        return ["---", ""]
    if btype == "to_do":
        checked = payload.get("checked", False)
        mark = "[x]" if checked else "[ ]"
        return [f"- {mark} {text}".strip()]
    if btype == "callout":
        icon = (payload.get("icon") or {}).get("emoji") or "ℹ️"
        line = f"> {icon} {text}".strip() if text else f"> {icon}"
        return [line, ""]
    return []


def _list_children(session: requests.Session, block_id: str) -> list[dict[str, Any]]:
    block_id = block_id.replace("-", "")
    out: list[dict[str, Any]] = []
    cursor = None
    while True:
        params: dict[str, Any] = {"page_size": 100}
        if cursor:
            params["start_cursor"] = cursor
        url = f"{NOTION_API}/blocks/{block_id}/children"
        r = session.get(url, params=params, timeout=60)
        if r.status_code == 429:
            time.sleep(int(r.headers.get("Retry-After", 3)))
            continue
        r.raise_for_status()
        data = r.json()
        out.extend(data.get("results") or [])
        if not data.get("has_more"):
            break
        cursor = data.get("next_cursor")
    return out


def _blocks_to_markdown(session: requests.Session, root_block_id: str) -> str:
    lines: list[str] = []

    def walk(bid: str, depth: int) -> None:
        if depth > 40:
            return
        for block in _list_children(session, bid):
            lines.extend(_block_to_lines(block))
            if block.get("has_children"):
                nested_id = str(block.get("id", "")).replace("-", "")
                if nested_id:
                    walk(nested_id, depth + 1)

    walk(root_block_id.replace("-", ""), 0)
    md = "\n".join(lines).strip()
    return md + ("\n" if md else "")


def main() -> None:
    parser = argparse.ArgumentParser(description="Export Notion Support Policy pages to markdown files.")
    parser.add_argument(
        "--page-id",
        default=SUPPORT_POLICY_DOCS_PAGE_ID,
        help="Notion page whose direct child_page blocks become policy files",
    )
    parser.add_argument(
        "--out-dir",
        default=os.path.join(_SUPPORT_DIR, "policies"),
        help="Directory to write *.md files into",
    )
    parser.add_argument("--dry-run", action="store_true", help="Print planned files only")
    args = parser.parse_args()

    headers = _notion_headers()
    session = requests.Session()
    session.headers.update(headers)

    root_id = args.page_id.replace("-", "")
    children = _list_children(session, root_id)
    child_pages = [b for b in children if b.get("type") == "child_page"]

    if not child_pages:
        print(
            "No child_page blocks found under the root page. "
            "Ensure policies are direct children of that Notion page.",
            file=sys.stderr,
        )
        sys.exit(3)

    os.makedirs(args.out_dir, exist_ok=True)

    for block in child_pages:
        cp = block.get("child_page") or {}
        title = (cp.get("title") or "untitled").strip()
        fname = _sanitize_filename(title) + ".md"
        path = os.path.join(args.out_dir, fname)
        page_id = (block.get("id") or "").replace("-", "")
        if args.dry_run:
            print(f"{title!r} → {path}")
            continue
        body = _blocks_to_markdown(session, page_id)
        header = f"# {title}\n\n"
        with open(path, "w", encoding="utf-8") as f:
            f.write(header + body)
        print(f"Wrote {path}")

    if args.dry_run:
        print(json.dumps({"planned_files": len(child_pages)}, indent=2))


if __name__ == "__main__":
    main()
