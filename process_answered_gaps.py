#!/usr/bin/env python3
"""Write answered Bert Gap Queue rows back into policies/*.md.

Fetches gap-queue rows with Status=Answered from Notion (via notion_bridge),
drafts a markdown addition for each using Claude, shows the human a diff-like
preview, and on approval appends the addition to the target policy doc (or
creates a new one), then marks the row Incorporated in Notion.

This script does NOT push the updated policy doc back to Notion — per the
project's Notion Sync convention, that is a separate manual step (see
scripts/sync_new_policy_docs.py from Task 7 / pull_policy_docs.py).

Usage:
  python3 process_answered_gaps.py                 # interactive, prompts per gap
  python3 process_answered_gaps.py --dry-run        # print proposals only, no writes
"""

from __future__ import annotations

import argparse
import os
import re
import sys

import anthropic
from dotenv import load_dotenv

_SUPPORT_DIR = os.path.dirname(os.path.abspath(__file__))
_ROOT_DIR = os.path.dirname(_SUPPORT_DIR)
load_dotenv(os.path.join(_SUPPORT_DIR, ".env"))
load_dotenv(os.path.join(_ROOT_DIR, ".env"))

from claude_utils import extract_text  # noqa: E402
import notion_bridge  # noqa: E402

CLAUDE_MODEL = "claude-sonnet-5"
POLICIES_DIR = os.path.join(_SUPPORT_DIR, "policies")

DRAFT_SYSTEM_PROMPT = """You are a support policy editor for Happier Meditation's support pipeline.
You are given a question that came up in customer support tickets but wasn't answered by
any existing policy doc, plus the answer the support team provided in Notion.

Draft a small markdown addition capturing this as reusable policy guidance. Follow the
existing policy doc conventions: clear, concise, written for an AI support agent to read
directly (not customer-facing prose). Do not invent details beyond what's given.

Respond with ONLY the markdown addition (no commentary, no code fences). Structure it as
one of:
  - A new subsection with a "###" heading suitable for appending under an existing doc's
    "# Policy / Correct Response" section, OR
  - If this doesn't fit any existing doc, say so on the first line as exactly:
    NEW_DOC_SUGGESTED: <short-kebab-case-filename-without-extension>
    followed by a blank line and then a complete minimal policy doc body (starting with
    "# <Title>") following the standard structure: Summary, Trigger Conditions, Required
    Context, Policy / Correct Response, Action Classification, Confidence Notes, Saved
    Reply Mapping (note if no saved reply exists yet), Related Policies.
"""


def _sanitize_filename(name: str) -> str:
    s = name.strip().lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    s = re.sub(r"-+", "-", s).strip("-")
    return s or "untitled-policy"


def _target_doc_path(target_doc: str) -> str | None:
    """Resolve a Target Policy Doc string (from Notion) to a path under policies/."""
    if not target_doc:
        return None
    name = target_doc.strip()
    if not name:
        return None
    if not name.endswith(".md"):
        name = _sanitize_filename(name) + ".md"
    else:
        name = _sanitize_filename(name[:-3]) + ".md"
    path = os.path.join(POLICIES_DIR, name)
    return path if os.path.exists(path) else None


def draft_policy_addition(client: anthropic.Anthropic, question: str, answer: str) -> str:
    """One Claude call drafting a markdown addition (or new-doc proposal) for a gap."""
    user_message = f"Question:\n{question}\n\nAnswer from support team:\n{answer}\n"
    message = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=1500,
        system=DRAFT_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}],
    )
    return extract_text(message).strip()


def _parse_draft(draft_text: str) -> tuple[str | None, str]:
    """Return (new_doc_filename_or_None, body). new_doc_filename is set only when
    the draft proposes a brand-new policy doc."""
    marker = "NEW_DOC_SUGGESTED:"
    if draft_text.startswith(marker):
        first_line, _, rest = draft_text.partition("\n")
        suggested_name = first_line[len(marker):].strip()
        body = rest.lstrip("\n")
        fname = _sanitize_filename(suggested_name) + ".md"
        return fname, body
    return None, draft_text


def apply_addition(target_doc: str, draft_text: str) -> str:
    """Append/create the policy doc addition on disk. Returns the file path written."""
    new_doc_name, body = _parse_draft(draft_text)

    if new_doc_name:
        path = os.path.join(POLICIES_DIR, new_doc_name)
        with open(path, "w", encoding="utf-8") as f:
            f.write(body.rstrip("\n") + "\n")
        return path

    existing_path = _target_doc_path(target_doc)
    if existing_path:
        with open(existing_path, "a", encoding="utf-8") as f:
            f.write("\n" + body.rstrip("\n") + "\n")
        return existing_path

    fname = _sanitize_filename(target_doc or "gap-addition") + ".md"
    path = os.path.join(POLICIES_DIR, fname)
    with open(path, "w", encoding="utf-8") as f:
        f.write(body.rstrip("\n") + "\n")
    return path


def process_gap(client: anthropic.Anthropic, gap: dict, dry_run: bool) -> None:
    question = gap.get("question") or ""
    answer = gap.get("answer") or ""
    target_doc = gap.get("target_doc") or ""
    page_id = gap["page_id"]

    print("=" * 72)
    print(f"Gap: {question}")
    print(f"Answer: {answer}")
    print(f"Target doc: {target_doc or '(none specified)'}")
    print("-" * 72)

    draft_text = draft_policy_addition(client, question, answer)
    new_doc_name, _body = _parse_draft(draft_text)

    if new_doc_name:
        print(f"Proposed NEW policy doc: policies/{new_doc_name}")
    else:
        existing_path = _target_doc_path(target_doc)
        dest = existing_path or os.path.join(
            POLICIES_DIR, _sanitize_filename(target_doc or "gap-addition") + ".md"
        )
        verb = "append to" if existing_path else "create"
        print(f"Proposed change ({verb} {dest}):")
    print(draft_text)
    print("-" * 72)

    if dry_run:
        print("[dry-run] No changes written.")
        return

    answer_input = input("Apply? [y/N] ").strip().lower()
    if answer_input != "y":
        print("Skipped.")
        return

    written_path = apply_addition(target_doc, draft_text)
    print(f"Wrote {written_path}")
    print(
        "Reminder: sync this policy doc change to the Support Policy Docs Notion page "
        "(see pull_policy_docs.py / scripts/sync_new_policy_docs.py) — the repo and "
        "Notion must stay in sync."
    )

    try:
        notion_bridge.mark_incorporated(page_id)
        print(f"Marked Notion gap row {page_id} as Incorporated.")
    except RuntimeError as e:
        print(f"Could not mark Incorporated in Notion ({e}); update it manually.", file=sys.stderr)


def main() -> None:
    parser = argparse.ArgumentParser(description="Write answered Bert Gap Queue rows back into policies/*.md.")
    parser.add_argument("--dry-run", action="store_true", help="Print proposals without writing or marking Incorporated")
    args = parser.parse_args()

    api_key = (os.getenv("ANTHROPIC_API_KEY") or "").strip()
    if not api_key:
        print("Set ANTHROPIC_API_KEY.", file=sys.stderr)
        sys.exit(2)

    try:
        gaps = notion_bridge.fetch_answered_gaps()
    except RuntimeError as e:
        print(f"Notion unavailable: {e}", file=sys.stderr)
        sys.exit(2)

    if not gaps:
        print("No answered gaps to process.")
        return

    client = anthropic.Anthropic(api_key=api_key)
    for gap in gaps:
        process_gap(client, gap, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
