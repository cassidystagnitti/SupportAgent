"""Repeatable eval harness (SUP-459): batch-run the draft pipeline over active tickets.

Consolidates the one-off test_run.py (batch runner) + test_run_analysis.py
(report generators, now in eval_reports.py) into one CLI:

    python3 eval_run.py [--date YYYY-MM-DD] [--limit N] [--mailbox ID] [--dry-run]

Produces eval/<date>/:
    results.json        — full pipeline output per ticket
    eval_scorecard.md   — aggregate + per-ticket metrics
    action_log.md       — manual actions to-do list
    policy_gaps.md      — low-confidence / uncovered tickets
    new_bugs.md         — bug-ish tickets not matching known issue patterns
and appends one summary line to eval/trends.md (created with header if missing).

--dry-run passes create_draft=False to process_ticket_sync: the read path and
the Claude draft call run for real (real classification JSON) but NO external
writes happen — no Help Scout drafts/notes/tags, no draft-registry write, no
Notion or bug-registry or product-prioritization hooks — and the two-pass
research step is skipped to save cost. See process_ticket_sync's docstring.

Tickets that already have a Bert draft recorded in the draft registry are
skipped by the pipeline (skipped_existing_draft=True) and surfaced in the
scorecard's "Skipped (existing draft)" row.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date

import requests
from dotenv import load_dotenv

_DIR = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_DIR)
load_dotenv(os.path.join(_DIR, ".env"))
load_dotenv(os.path.join(_ROOT, ".env"))

# Eval runs pin the draft model unless the caller overrides it explicitly.
os.environ.setdefault("CLAUDE_DRAFT_MODEL", "claude-sonnet-5")

from eval_reports import (  # noqa: E402
    find_policy_gaps,
    generate_action_log,
    generate_eval_scorecard,
    generate_new_bugs,
    generate_policy_gaps,
)

DEFAULT_MAILBOX_ID = os.getenv("BATCH_MAILBOX_ID", "185235")
MAX_WORKERS = 5

TRENDS_HEADER = (
    "# Eval Trends\n"
    "\n"
    "| date | tickets | draft% | coverage% | high/med/low | gaps | avg_ms | cache_read_avg |\n"
    "|------|---------|--------|-----------|--------------|------|--------|----------------|\n"
)

_print_lock = threading.Lock()


def _log(msg: str, *, err: bool = False) -> None:
    with _print_lock:
        print(msg, file=sys.stderr if err else sys.stdout, flush=True)


def fetch_active_conversations(session: requests.Session, mailbox_id: str) -> list[dict]:
    """All active conversations in the mailbox, newest first (test_run.py's fetch logic)."""
    from triage_tickets import BASE_URL, api_get

    convos = []
    page = 1
    while True:
        data = api_get(session, f"{BASE_URL}/conversations", params={
            "status": "active",
            "mailbox": mailbox_id,
            "sortField": "createdAt",
            "sortOrder": "desc",
            "page": page,
        })
        page_convos = data.get("_embedded", {}).get("conversations", [])
        convos.extend(page_convos)
        total_pages = data.get("page", {}).get("totalPages", 1)
        _log(f"  Page {page}/{total_pages}: {len(page_convos)} conversations")
        if page >= total_pages:
            break
        page += 1
    return convos


def process_one(i: int, total: int, convo: dict, *, dry_run: bool) -> dict:
    from orchestrator import process_ticket_sync
    from triage_tickets import get_access_token, get_conversation_text

    cid = str(convo["id"])
    subject = convo.get("subject", "(no subject)")
    customer = (
        convo.get("customer")
        or convo.get("primaryCustomer")
        or (convo.get("_embedded") or {}).get("primaryCustomer")
        or {}
    )
    email = customer.get("email")
    _log(f"[{i}/{total}] #{cid} — {subject[:70]}")
    try:
        result = process_ticket_sync(cid, email, skip_triage=True, create_draft=not dry_run)
        status = "draft_created" if result.get("draft_created") else "no_draft"
        if result.get("skipped_existing_draft"):
            status = "skipped_existing_draft"
        if result.get("escalated"):
            status = "escalated"
        if result.get("error"):
            status = f"error: {result['error'][:80]}"
        _log(f"  → #{cid} {status} | {result.get('latency_ms', '?')}ms")
    except Exception as exc:
        _log(f"  → #{cid} EXCEPTION: {exc}", err=True)
        result = {"conversation_id": cid, "error": str(exc)}

    # Enrich with the original ticket text for the reports (read-only).
    try:
        session = requests.Session()
        session.headers.update({"Authorization": f"Bearer {get_access_token()}"})
        ticket_body = get_conversation_text(session, int(cid))
    except Exception as exc:
        _log(f"  → #{cid} failed to fetch ticket text: {exc}", err=True)
        ticket_body = None

    result["ticket_subject"] = subject
    result["ticket_body"] = ticket_body
    return result


def build_trends_line(results: list[dict], run_date: str) -> str:
    """One `| date | tickets | draft% | coverage% | high/med/low | gaps | avg_ms | cache_read_avg |` row."""
    total = len(results)
    successful = [r for r in results if not r.get("error")]
    drafts = sum(1 for r in results if r.get("draft_created"))
    has_policies = sum(1 for r in successful if r.get("referenced_policies"))

    def pct(n: int, d: int) -> str:
        return f"{n * 100 // d}%" if d else "n/a"

    conf = {"high": 0, "medium": 0, "low": 0}
    for r in successful:
        c = r.get("confidence")
        if c in conf:
            conf[c] += 1

    gaps = len(find_policy_gaps(results))
    latencies = [r["latency_ms"] for r in successful if r.get("latency_ms")]
    cache_reads = [r["cache_read_input_tokens"] for r in successful if r.get("cache_read_input_tokens")]
    avg_ms = sum(latencies) // len(latencies) if latencies else 0
    cache_read_avg = sum(cache_reads) // len(cache_reads) if cache_reads else 0

    return (
        f"| {run_date} | {total} | {pct(drafts, total)} | {pct(has_policies, len(successful))} "
        f"| {conf['high']}/{conf['medium']}/{conf['low']} | {gaps} | {avg_ms} | {cache_read_avg} |"
    )


def append_trends_line(trends_path: str, line: str) -> None:
    """Append one row to eval/trends.md, creating it with the header if missing."""
    os.makedirs(os.path.dirname(trends_path), exist_ok=True)
    if not os.path.exists(trends_path):
        with open(trends_path, "w", encoding="utf-8") as f:
            f.write(TRENDS_HEADER)
    with open(trends_path, "a", encoding="utf-8") as f:
        f.write(line.rstrip("\n") + "\n")


def main() -> None:
    from triage_tickets import get_access_token

    parser = argparse.ArgumentParser(description="Batch-run the Bert draft pipeline and write eval reports.")
    parser.add_argument("--date", default=date.today().isoformat(),
                        help="Run label / output folder name under eval/ (default: today)")
    parser.add_argument("--limit", type=int, default=None, help="Process at most N conversations")
    parser.add_argument("--mailbox", default=DEFAULT_MAILBOX_ID,
                        help=f"Help Scout mailbox id (default {DEFAULT_MAILBOX_ID})")
    parser.add_argument("--dry-run", action="store_true",
                        help="No external writes anywhere (create_draft=False); research pass skipped")
    args = parser.parse_args()

    eval_dir = os.path.join(_DIR, "eval", args.date)

    session = requests.Session()
    session.headers.update({"Authorization": f"Bearer {get_access_token()}"})

    _log(f"Fetching active conversations in mailbox {args.mailbox} …")
    convos = fetch_active_conversations(session, args.mailbox)
    if args.limit is not None:
        convos = convos[: args.limit]
    total = len(convos)
    mode = "DRY-RUN (no external writes)" if args.dry_run else "live"
    _log(f"Found {total} conversation(s) to process ({mode}). Running {MAX_WORKERS} workers.\n")

    if not convos:
        _log("Nothing to do.")
        return

    results: list[dict] = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {
            pool.submit(process_one, i, total, convo, dry_run=args.dry_run): convo
            for i, convo in enumerate(convos, 1)
        }
        for future in as_completed(futures):
            results.append(future.result())

    results.sort(key=lambda r: int(r.get("conversation_id", 0) or 0))

    drafts = sum(1 for r in results if r.get("draft_created"))
    skipped = sum(1 for r in results if r.get("skipped_existing_draft"))
    escalated = sum(1 for r in results if r.get("escalated"))
    errors = sum(1 for r in results if r.get("error"))
    _log(
        f"\nDone. {drafts} draft(s) created, {skipped} skipped (existing draft), "
        f"{escalated} escalated, {errors} error(s) out of {total}."
    )

    os.makedirs(eval_dir, exist_ok=True)
    results_path = os.path.join(eval_dir, "results.json")
    with open(results_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, default=str)
    _log(f"Saved {len(results)} result(s) to {results_path}")

    outputs = {
        "eval_scorecard.md": generate_eval_scorecard(results, run_date=args.date),
        "action_log.md": generate_action_log(results),
        "policy_gaps.md": generate_policy_gaps(results),
        "new_bugs.md": generate_new_bugs(results),
    }
    for filename, content in outputs.items():
        path = os.path.join(eval_dir, filename)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        _log(f"  {filename}: written ({len(content)} chars)")

    trends_path = os.path.join(_DIR, "eval", "trends.md")
    line = build_trends_line(results, args.date)
    append_trends_line(trends_path, line)
    _log(f"Appended to {trends_path}:\n  {line}")


if __name__ == "__main__":
    main()
