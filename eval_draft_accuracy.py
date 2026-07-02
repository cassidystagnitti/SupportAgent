"""Draft accuracy tracker (SUP-459): how did Bert's drafts fare with human agents?

For each result in an eval run's results.json, fetches the conversation's
threads from Help Scout, locates the reply the agent actually SENT, and
classifies Bert's draft against it:

  - sent_unedited — normalized similarity >= 0.95 (agent sent it as-is or
    with trivial whitespace/HTML changes)
  - edited        — similarity in [0.5, 0.95) (agent kept the draft but
    reworked it)
  - discarded     — similarity < 0.5, or no sent agent reply found (which
    includes drafts still sitting unsent — see note in the report)

Bert's draft text comes from results.json (`draft_text` — the authoritative
record of what Bert wrote; once a draft is sent, its Help Scout thread state
flips to published, so the thread alone can't distinguish draft from edit).
The sent reply is located in the threads: the thread whose id matches the
recorded `helpscout_draft_id` if it is now published (the draft itself was
sent, possibly edited first), otherwise the earliest published agent message
created at/after the draft's timestamp, otherwise the newest published agent
message.

Usage:
    python3 eval_draft_accuracy.py --results eval/2026-07-02/results.json

Writes eval/<date>/draft_accuracy.md next to the results file.
"""

from __future__ import annotations

import argparse
import difflib
import html
import json
import os
import re
import sys
from typing import Any

_DIR = os.path.dirname(os.path.abspath(__file__))

_TAG_RE = re.compile(r"<[^>]+>")

UNEDITED_THRESHOLD = 0.95
EDITED_THRESHOLD = 0.5


def _normalize(text: str) -> str:
    """Strip HTML tags, unescape entities, and collapse all whitespace runs."""
    no_tags = _TAG_RE.sub(" ", text or "")
    return " ".join(html.unescape(no_tags).split())


def similarity_ratio(draft: str, sent: str | None) -> float | None:
    """Normalized difflib ratio between draft and sent text; None when sent is None."""
    if sent is None:
        return None
    return difflib.SequenceMatcher(None, _normalize(draft), _normalize(sent)).ratio()


def classify_similarity(draft: str, sent: str | None) -> str:
    """Classify how a Bert draft fared: 'sent_unedited', 'edited', or 'discarded'.

    Pure function. `sent` is None when no agent reply was sent → 'discarded'.
    Thresholds on difflib.SequenceMatcher ratio over normalized text
    (HTML tags stripped, entities unescaped, whitespace collapsed):
    >= 0.95 'sent_unedited'; >= 0.5 'edited'; else 'discarded'.
    """
    ratio = similarity_ratio(draft, sent)
    if ratio is None:
        return "discarded"
    if ratio >= UNEDITED_THRESHOLD:
        return "sent_unedited"
    if ratio >= EDITED_THRESHOLD:
        return "edited"
    return "discarded"


def _fetch_threads(session, cid: str) -> list[dict]:
    """All threads for a conversation, oldest info preserved (HS returns newest-first)."""
    from triage_tickets import BASE_URL, api_get  # deferred: keeps classify_similarity import-light

    threads: list[dict] = []
    page = 1
    while True:
        data = api_get(
            session,
            f"{BASE_URL}/conversations/{cid}/threads",
            params={"page": page},
        )
        page_threads = data.get("_embedded", {}).get("threads", [])
        threads.extend(page_threads)
        total_pages = data.get("page", {}).get("totalPages", 1)
        if page >= total_pages:
            break
        page += 1
    return threads


def find_sent_reply(threads: list[dict], helpscout_draft_id: str | None, drafted_at: str | None) -> str | None:
    """Locate the body of the agent reply that was actually sent, or None.

    Preference order:
      1. The thread whose id matches the recorded draft id AND is now published
         (Bert's own draft was sent, possibly edited before sending).
      2. The earliest published agent message created at/after the draft's
         timestamp (agent discarded the draft and wrote their own — ISO8601
         strings compare correctly lexicographically within the same offset).
      3. The newest published agent message (fallback when timestamps are
         missing or the draft predates available history).
    """
    published = [
        t for t in threads or []
        if t.get("type") == "message" and t.get("state") == "published"
    ]
    if not published:
        return None

    if helpscout_draft_id:
        for t in published:
            if str(t.get("id")) == str(helpscout_draft_id):
                return t.get("body") or ""

    if drafted_at:
        after = [t for t in published if (t.get("createdAt") or "") >= drafted_at]
        if after:
            earliest = min(after, key=lambda t: t.get("createdAt") or "")
            return earliest.get("body") or ""

    # Threads come newest-first from the API; be defensive and sort explicitly.
    newest = max(published, key=lambda t: t.get("createdAt") or "")
    return newest.get("body") or ""


def generate_draft_accuracy_report(rows: list[dict], run_date: str) -> str:
    classified = [r for r in rows if r["classification"] is not None]
    total = len(classified)

    def pct(n: int) -> str:
        return f"{n}/{total} ({n * 100 // total}%)" if total else "0/0"

    counts = {"sent_unedited": 0, "edited": 0, "discarded": 0}
    for r in classified:
        counts[r["classification"]] += 1

    lines = [
        "# Draft Accuracy\n",
        f"**Run date:** {run_date}",
        f"**Drafts evaluated:** {total}"
        + (f" ({len(rows) - total} result(s) had no draft and were excluded)" if len(rows) != total else ""),
        "",
        "| Outcome | Count |",
        "|---------|-------|",
        f"| Sent unedited | {pct(counts['sent_unedited'])} |",
        f"| Edited | {pct(counts['edited'])} |",
        f"| Discarded | {pct(counts['discarded'])} |",
        "",
        "_Note: 'discarded' includes drafts with no sent agent reply yet — for",
        "conversations still awaiting a human decision, re-run later for a final",
        "number._",
        "",
        "## Per-Ticket Detail\n",
        "| # | Subject | Outcome | Similarity |",
        "|---|---------|---------|------------|",
    ]

    for r in rows:
        cid = r["conversation_id"]
        subj = (r["ticket_subject"] or "?")[:40]
        outcome = r["classification"] or "(no draft)"
        ratio = r["ratio"]
        ratio_disp = f"{ratio:.3f}" if ratio is not None else "—"
        lines.append(f"| {cid} | {subj} | {outcome} | {ratio_disp} |")

    lines.append("")
    return "\n".join(lines)


def main() -> None:
    from dotenv import load_dotenv

    load_dotenv(os.path.join(_DIR, ".env"))
    load_dotenv(os.path.join(os.path.dirname(_DIR), ".env"))

    import requests

    from triage_tickets import get_access_token

    parser = argparse.ArgumentParser(description="Classify how Bert's eval drafts fared with human agents.")
    parser.add_argument("--results", required=True, help="Path to an eval run's results.json")
    args = parser.parse_args()

    results_path = os.path.abspath(args.results)
    with open(results_path, encoding="utf-8") as f:
        results = json.load(f)

    eval_dir = os.path.dirname(results_path)
    run_date = os.path.basename(eval_dir)

    session = requests.Session()
    session.headers.update({"Authorization": f"Bearer {get_access_token()}"})

    rows: list[dict] = []
    for r in sorted(results, key=lambda x: str(x.get("conversation_id", ""))):
        cid = str(r.get("conversation_id", "?"))
        draft = r.get("draft_text")
        row: dict[str, Any] = {
            "conversation_id": cid,
            "ticket_subject": r.get("ticket_subject"),
            "classification": None,
            "ratio": None,
        }
        if not draft:
            print(f"#{cid}: no draft text — excluded")
            rows.append(row)
            continue
        try:
            threads = _fetch_threads(session, cid)
        except Exception as exc:
            print(f"#{cid}: failed to fetch threads ({exc}) — excluded", file=sys.stderr)
            rows.append(row)
            continue
        sent = find_sent_reply(threads, r.get("helpscout_draft_id"), r.get("timestamp"))
        row["ratio"] = similarity_ratio(draft, sent)
        row["classification"] = classify_similarity(draft, sent)
        print(f"#{cid}: {row['classification']}" + (f" (ratio {row['ratio']:.3f})" if row["ratio"] is not None else ""))
        rows.append(row)

    report = generate_draft_accuracy_report(rows, run_date)
    out_path = os.path.join(eval_dir, "draft_accuracy.md")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(report)
    print(f"\nWrote {out_path}")


if __name__ == "__main__":
    main()
