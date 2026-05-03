#!/usr/bin/env python3
"""Create a Help Scout draft reply from the conversation transcript via Claude."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from support_agent.config import load_settings
from support_agent.draft_service import run_draft_for_conversation
from support_agent.helpscout import HelpScout, conversation_tag_names


def _embedded_conversations(payload: dict) -> list[dict]:
    emb = payload.get("_embedded") or {}
    for key in ("conversations", "items"):
        hit = emb.get(key)
        if isinstance(hit, list):
            return hit
    return []


def pick_next_conversation_id(
    hs: HelpScout,
    *,
    mailbox_id: int,
    skip_if_tag: str | None,
    max_pages: int = 15,
) -> int:
    for page in range(1, max_pages + 1):
        data = hs.list_conversations(mailbox_id=mailbox_id, page=page)
        items = _embedded_conversations(data)
        if not items:
            break
        for item in items:
            cid = item.get("id")
            if cid is None:
                continue
            tags: list[str] = []
            for t in item.get("tags") or []:
                if isinstance(t, dict) and t.get("tag"):
                    tags.append(str(t["tag"]))
                elif isinstance(t, str):
                    tags.append(t)
            if skip_if_tag and skip_if_tag in tags:
                continue
            conv = hs.get_conversation(int(cid))
            resolved = int(conv.get("id", cid))
            full_tags = conversation_tag_names(conv)
            if skip_if_tag and skip_if_tag in full_tags:
                continue
            return resolved
    raise SystemExit(
        "No matching active conversation found (check mailbox id, tags, or pagination)."
    )


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--conversation-id", type=int, help="Help Scout conversation id (numeric)")
    p.add_argument(
        "--pick-next",
        action="store_true",
        help="Pick the next active conversation in the mailbox (by waitingSince asc)",
    )
    p.add_argument("--mailbox", type=int, help="Inbox id (defaults to HELPSCOUT_MAILBOX_ID)")
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the draft only; do not write to Help Scout",
    )
    p.add_argument(
        "--no-tag",
        action="store_true",
        help="Do not add HELPSCOUT_DRAFT_TAG after creating the draft",
    )
    args = p.parse_args()

    if args.pick_next and args.conversation_id is not None:
        raise SystemExit("Use only one of --conversation-id or --pick-next")
    if not args.pick_next and args.conversation_id is None:
        raise SystemExit("Provide --conversation-id or --pick-next")

    settings = load_settings()
    hs = HelpScout(settings.helpscout_client_id, settings.helpscout_client_secret)

    mailbox = args.mailbox or settings.helpscout_mailbox_id
    if args.pick_next and mailbox is None:
        raise SystemExit("--pick-next requires HELPSCOUT_MAILBOX_ID or --mailbox")

    if args.pick_next:
        assert mailbox is not None
        conv_id = pick_next_conversation_id(
            hs, mailbox_id=mailbox, skip_if_tag=settings.helpscout_skip_if_tag
        )
    else:
        conv_id = int(args.conversation_id)

    result = run_draft_for_conversation(
        settings,
        hs,
        conv_id,
        dry_run=args.dry_run,
        no_tag=args.no_tag,
    )

    if result.get("skipped"):
        reason = result.get("reason", "unknown")
        if reason == "empty_transcript":
            raise SystemExit("No usable thread bodies found for this conversation.")
        print(f"Skipped ({reason}).")
        return

    if args.dry_run and result.get("draft") is not None:
        print(result["draft"])
        return

    print(f"Draft reply created on conversation {result.get('conversation_id')} (Help Scout id).")


if __name__ == "__main__":
    main()
