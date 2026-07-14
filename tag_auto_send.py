#!/usr/bin/env python3
"""Apply 'auto_send' tag to Help Scout conversations that were marked auto_sendable in the test run."""

from __future__ import annotations

import json
import logging
import os
import sys
import time

import requests
from dotenv import load_dotenv

_DIR = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_DIR)
load_dotenv(os.path.join(_DIR, ".env"))
load_dotenv(os.path.join(_ROOT, ".env"))

from triage_tickets import BASE_URL, get_access_token  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger(__name__)

RESULTS_PATH = os.path.join(_DIR, "eval", "2026-07-02", "results.json")
TAG_NAME = "auto_send"


def extract_tag_names(tags_field: list) -> list[str]:
    names = []
    for t in tags_field or []:
        if isinstance(t, dict):
            names.append(t.get("tag") or t.get("name") or "")
        else:
            names.append(str(t))
    return [n for n in names if n]


def main() -> None:
    with open(RESULTS_PATH, encoding="utf-8") as f:
        results = json.load(f)

    auto_sendable = [r for r in results if r.get("auto_sendable")]
    log.info("Found %d auto-sendable tickets in results", len(auto_sendable))

    token = get_access_token()
    session = requests.Session()
    session.headers.update({
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    })

    tagged = 0
    skipped = 0
    errors = 0

    for r in auto_sendable:
        cid = r["conversation_id"]
        try:
            resp = session.get(f"{BASE_URL}/conversations/{cid}")
            if resp.status_code == 404:
                log.warning("Conversation %s not found (closed/deleted?), skipping", cid)
                skipped += 1
                continue
            resp.raise_for_status()
            convo = resp.json()

            existing_tags = extract_tag_names(convo.get("tags", []))

            if TAG_NAME in existing_tags:
                log.info("  %s already has '%s', skipping", cid, TAG_NAME)
                skipped += 1
                continue

            new_tags = existing_tags + [TAG_NAME]
            put_resp = session.put(
                f"{BASE_URL}/conversations/{cid}/tags",
                json={"tags": new_tags},
            )
            put_resp.raise_for_status()
            tagged += 1
            log.info("  %s tagged '%s' (conf=%s)", cid, TAG_NAME, r.get("confidence", "?"))

            time.sleep(0.25)

        except Exception:
            log.exception("  Failed to tag conversation %s", cid)
            errors += 1

    log.info("Done: %d tagged, %d skipped, %d errors", tagged, skipped, errors)


if __name__ == "__main__":
    main()
