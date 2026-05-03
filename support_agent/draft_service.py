from __future__ import annotations

from typing import Any

from support_agent.claude_draft import generate_draft_reply
from support_agent.config import Settings
from support_agent.helpscout import (
    HelpScout,
    conversation_tag_names,
    primary_customer_id,
)
from support_agent.transcript import build_transcript


def run_draft_for_conversation(
    settings: Settings,
    hs: HelpScout,
    conv_id: int,
    *,
    dry_run: bool = False,
    no_tag: bool = False,
) -> dict[str, Any]:
    """
    Fetch threads, generate a Claude reply, and create a Help Scout draft (unless dry_run).
    Returns a small status dict for logging or HTTP responses.
    """
    conv = hs.get_conversation(conv_id)
    conv_id = int(conv.get("id", conv_id))

    if settings.helpscout_skip_if_tag:
        tags = conversation_tag_names(conv)
        if settings.helpscout_skip_if_tag in tags:
            return {
                "conversation_id": conv_id,
                "ok": True,
                "skipped": True,
                "reason": "skip_if_tag_present",
            }

    subject = str(conv.get("subject") or "(no subject)")
    threads = hs.list_threads(conv_id)
    transcript = build_transcript(threads)
    if not transcript.strip():
        return {
            "conversation_id": conv_id,
            "ok": True,
            "skipped": True,
            "reason": "empty_transcript",
        }

    draft = generate_draft_reply(settings, subject=subject, transcript=transcript)

    if dry_run:
        return {
            "conversation_id": conv_id,
            "ok": True,
            "dry_run": True,
            "draft": draft,
        }

    cust_id = primary_customer_id(conv)
    hs.create_draft_reply(conv_id, customer_id=cust_id, text=draft)

    if not no_tag and settings.helpscout_draft_tag:
        existing = conversation_tag_names(conv)
        hs.merge_tags(conv_id, existing, settings.helpscout_draft_tag)

    return {"conversation_id": conv_id, "ok": True, "draft_created": True}
