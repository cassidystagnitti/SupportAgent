#!/usr/bin/env python3
"""Register (create) a Help Scout Mailbox API webhook pointing at your public URL."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from support_agent.config import load_settings
from support_agent.helpscout import HelpScout, HelpScoutError


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--url",
        required=True,
        help="Public HTTPS URL, e.g. https://your-service.onrender.com/webhooks/helpscout",
    )
    p.add_argument(
        "--secret",
        help="Webhook secret (defaults to HELPSCOUT_WEBHOOK_SECRET from env; must match server)",
    )
    p.add_argument(
        "--events",
        default="convo.created",
        help="Comma-separated Help Scout event names (default: convo.created)",
    )
    p.add_argument("--label", default="SupportAgent Claude draft")
    p.add_argument(
        "--mailbox",
        type=int,
        nargs="*",
        help="Optional mailbox ids to scope the webhook (defaults: all mailboxes)",
    )
    args = p.parse_args()

    settings = load_settings()
    secret = (args.secret or settings.helpscout_webhook_secret or "").strip()
    if not secret:
        raise SystemExit("Provide --secret or set HELPSCOUT_WEBHOOK_SECRET")

    events = [e.strip() for e in args.events.split(",") if e.strip()]
    hs = HelpScout(settings.helpscout_client_id, settings.helpscout_client_secret)

    try:
        wid = hs.create_webhook(
            url=args.url.rstrip("/"),
            secret=secret,
            events=events,
            label=args.label,
            mailbox_ids=args.mailbox or None,
        )
    except HelpScoutError as e:
        raise SystemExit(str(e)) from e

    print(f"Webhook created with id {wid}. Point Help Scout at:\n  {args.url}")


if __name__ == "__main__":
    main()
