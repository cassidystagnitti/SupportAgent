from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    helpscout_client_id: str
    helpscout_client_secret: str
    helpscout_mailbox_id: int | None
    anthropic_api_key: str
    anthropic_model: str
    helpscout_draft_tag: str | None
    helpscout_skip_if_tag: str | None
    helpscout_webhook_secret: str | None


def load_settings() -> Settings:
    cid = os.environ.get("HELPSCOUT_CLIENT_ID", "").strip()
    secret = os.environ.get("HELPSCOUT_CLIENT_SECRET", "").strip()
    if not cid or not secret:
        raise SystemExit(
            "HELPSCOUT_CLIENT_ID and HELPSCOUT_CLIENT_SECRET must be set in the environment or .env"
        )

    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not key:
        raise SystemExit("ANTHROPIC_API_KEY must be set in the environment or .env")

    mb_raw = os.environ.get("HELPSCOUT_MAILBOX_ID", "").strip()
    mailbox_id = int(mb_raw) if mb_raw else None

    draft_tag = os.environ.get("HELPSCOUT_DRAFT_TAG", "ai-claude-draft").strip()
    skip_tag = os.environ.get("HELPSCOUT_SKIP_IF_TAG", "ai-claude-draft").strip()
    wh_secret = os.environ.get("HELPSCOUT_WEBHOOK_SECRET", "").strip()

    return Settings(
        helpscout_client_id=cid,
        helpscout_client_secret=secret,
        helpscout_mailbox_id=mailbox_id,
        anthropic_api_key=key,
        anthropic_model=os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-20250514").strip(),
        helpscout_draft_tag=draft_tag or None,
        helpscout_skip_if_tag=skip_tag or None,
        helpscout_webhook_secret=wh_secret or None,
    )
