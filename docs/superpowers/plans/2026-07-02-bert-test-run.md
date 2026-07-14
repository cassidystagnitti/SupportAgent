# Bert Test Run Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run the full support draft pipeline against all active Help Scout tickets with Sonnet 5 and current company context, then analyze results to produce an action log, policy gap doc, bug surface, eval scorecard, streak Linear ticket, and build proposal.

**Architecture:** Three phases — (1) inject company context into the system prompt and set model to Sonnet 5, (2) run the batch pipeline posting real drafts to Help Scout and capturing results JSON, (3) analyze the results to produce all deliverables. No existing files are modified except the system prompt (appended to). Two new scripts: `test_run.py` and `test_run_analysis.py`.

**Tech Stack:** Python 3, existing SupportAgent modules (`orchestrator.process_ticket_sync`, `triage_tickets.get_access_token/api_get`), Anthropic API (claude-sonnet-5), Help Scout API v2, Stripe API (read-only), Linear MCP.

## Global Constraints

- Model: `claude-sonnet-5`
- All drafts posted as `draft: true` — never auto-send
- Do NOT modify `orchestrator.py`, `triage_tickets.py`, `batch_maven_drafts.py`, or any policy docs
- Output directory: `SupportAgent/eval/2026-07-02/`
- Max 5 concurrent workers for Help Scout rate limiting

---

### Task 1: Inject Company Context into System Prompt

**Files:**
- Modify: `prompts/draft_system_prompt.txt` (append after line 42, before end of file)

**Interfaces:**
- Consumes: nothing
- Produces: updated system prompt loaded by `orchestrator.load_policy_docs()` → `_load_system_prompt()` at runtime

- [ ] **Step 1: Append the company context block to the system prompt**

Add this block at the end of `prompts/draft_system_prompt.txt`:

```
=== CURRENT COMPANY CONTEXT (as of July 2, 2026) ===
- We just released the Hotwire Native Android app. Bug reports from Android users are expected.
- Meditation pausing/freezing bug: This was FIXED yesterday (July 1). If a user reports this issue, ask them to update their app and let us know if the issue persists after the update.
- Milestones are currently broken on the new app. We are actively working on a fix. Acknowledge the issue and let the user know we're working on it.
- Streak data issues: We are aware of reports of streaks being broken/reset. We are investigating. Acknowledge and let the user know we're looking into it.
```

- [ ] **Step 2: Verify the prompt loads correctly**

```bash
cd /Users/cassidystagnitti/code/code-happierMeditation/SupportAgent
python3 -c "
with open('prompts/draft_system_prompt.txt') as f:
    text = f.read()
assert 'CURRENT COMPANY CONTEXT' in text
assert 'Hotwire Native Android' in text
assert 'Meditation pausing/freezing bug' in text
assert 'Milestones are currently broken' in text
assert 'Streak data issues' in text
print('OK — context block present')
print(f'Total prompt length: {len(text)} chars')
"
```

Expected: `OK — context block present` and a character count.

---

### Task 2: Create Test Run Script

**Files:**
- Create: `test_run.py`

**Interfaces:**
- Consumes: `orchestrator.process_ticket_sync(conversation_id: str, customer_email: str | None, *, skip_triage: bool) -> dict`
- Consumes: `triage_tickets.get_access_token() -> str`, `triage_tickets.api_get(session, url, params) -> dict`, `triage_tickets.BASE_URL`
- Produces: `eval/2026-07-02/results.json` — JSON array of dicts, one per ticket, each with keys: `conversation_id`, `customer_email`, `timestamp`, `triage_success`, `account_lookup_success`, `stripe_enrichment_attempted`, `stripe_enrichment_success`, `stripe_platform`, `escalated`, `escalate_reason`, `needs_action`, `auto_sendable`, `confidence`, `referenced_policies`, `do_not_send_reasons`, `draft_created`, `note_created`, `total_input_tokens`, `total_output_tokens`, `latency_ms`, `draft_text`, `reasoning`, `action_description`, `error`, `ticket_subject`, `ticket_body`

- [ ] **Step 1: Create the test run script**

```python
"""Bert test run: pull all active Help Scout tickets, run draft pipeline with Sonnet 5, save results."""

from __future__ import annotations

import json
import os
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

import requests
from dotenv import load_dotenv

_DIR = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_DIR)
load_dotenv(os.path.join(_DIR, ".env"))
load_dotenv(os.path.join(_ROOT, ".env"))

os.environ["CLAUDE_DRAFT_MODEL"] = "claude-sonnet-5"

from triage_tickets import BASE_URL, get_access_token, api_get, get_conversation_text  # noqa: E402
from orchestrator import process_ticket_sync  # noqa: E402

MAILBOX_ID = os.getenv("BATCH_MAILBOX_ID", "185235")
MAX_WORKERS = 5
EVAL_DIR = os.path.join(_DIR, "eval", "2026-07-02")

_print_lock = threading.Lock()


def _log(msg: str, *, err: bool = False) -> None:
    with _print_lock:
        print(msg, file=sys.stderr if err else sys.stdout, flush=True)


def fetch_active_conversations(session: requests.Session, mailbox_id: str) -> list[dict]:
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


def _extract_email(convo: dict) -> str | None:
    for key in ("customer", "primaryCustomer"):
        c = convo.get(key)
        if isinstance(c, dict):
            email = c.get("email")
            if email:
                return str(email).strip()
    emb = convo.get("_embedded") or {}
    for key in ("primaryCustomer", "customer"):
        c = emb.get(key)
        if isinstance(c, dict):
            email = c.get("email")
            if email:
                return str(email).strip()
    return None


def _extract_subject(convo: dict) -> str:
    return convo.get("subject", "(no subject)")


def process_one(i: int, total: int, convo: dict, hs_session: requests.Session) -> dict:
    cid = str(convo["id"])
    subject = _extract_subject(convo)
    email = _extract_email(convo)
    _log(f"[{i}/{total}] #{cid} — {subject[:70]}")

    ticket_body = ""
    try:
        ticket_body = get_conversation_text(hs_session, int(cid)) or ""
    except Exception:
        _log(f"  Could not fetch body for #{cid}", err=True)

    try:
        result = process_ticket_sync(cid, email, skip_triage=True)
        result["ticket_subject"] = subject
        result["ticket_body"] = ticket_body

        status = "draft_created" if result.get("draft_created") else "no_draft"
        if result.get("escalated"):
            status = "escalated"
        if result.get("error"):
            status = f"error: {result['error'][:80]}"
        _log(f"  -> #{cid} {status} | conf={result.get('confidence')} | {result.get('latency_ms', '?')}ms")
        return result
    except Exception as exc:
        _log(f"  -> #{cid} EXCEPTION: {exc}", err=True)
        return {
            "conversation_id": cid,
            "customer_email": email or "",
            "ticket_subject": subject,
            "ticket_body": ticket_body,
            "error": str(exc),
        }


def main() -> None:
    os.makedirs(EVAL_DIR, exist_ok=True)

    token = get_access_token()
    session = requests.Session()
    session.headers.update({"Authorization": f"Bearer {token}"})

    _log(f"Model: claude-sonnet-5")
    _log(f"Fetching active conversations in mailbox {MAILBOX_ID} ...")
    convos = fetch_active_conversations(session, MAILBOX_ID)
    total = len(convos)
    _log(f"Found {total} conversation(s). Running {MAX_WORKERS} workers.\n")

    if not convos:
        _log("Nothing to do.")
        return

    results: list[dict] = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {
            pool.submit(process_one, i, total, convo, session): convo
            for i, convo in enumerate(convos, 1)
        }
        for future in as_completed(futures):
            results.append(future.result())

    results.sort(key=lambda r: r.get("conversation_id", ""))

    out_path = os.path.join(EVAL_DIR, "results.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, default=str)

    drafts = sum(1 for r in results if r.get("draft_created"))
    escalated = sum(1 for r in results if r.get("escalated"))
    errors = sum(1 for r in results if r.get("error"))
    _log(f"\nDone. {drafts} draft(s), {escalated} escalated, {errors} error(s) out of {total}.")
    _log(f"Results saved to {out_path}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Create eval output directory**

```bash
mkdir -p /Users/cassidystagnitti/code/code-happierMeditation/SupportAgent/eval/2026-07-02
```

- [ ] **Step 3: Verify the script imports correctly**

```bash
cd /Users/cassidystagnitti/code/code-happierMeditation/SupportAgent
python3 -c "import test_run; print('imports OK')"
```

Expected: `imports OK`

- [ ] **Step 4: Run the test**

```bash
cd /Users/cassidystagnitti/code/code-happierMeditation/SupportAgent
python3 test_run.py 2>&1 | tee eval/2026-07-02/run_log.txt
```

This will take several minutes depending on ticket count. Watch for:
- Each ticket logging its status
- Final summary line with draft/escalated/error counts
- `results.json` written to `eval/2026-07-02/`

- [ ] **Step 5: Verify results file**

```bash
cd /Users/cassidystagnitti/code/code-happierMeditation/SupportAgent
python3 -c "
import json
with open('eval/2026-07-02/results.json') as f:
    results = json.load(f)
print(f'{len(results)} tickets processed')
for r in results[:3]:
    print(f'  #{r[\"conversation_id\"]} conf={r.get(\"confidence\")} action={r.get(\"needs_action\")} draft={r.get(\"draft_created\")}')
"
```

---

### Task 3: Create Analysis Script and Generate All Deliverables

**Files:**
- Create: `test_run_analysis.py`

**Interfaces:**
- Consumes: `eval/2026-07-02/results.json` (produced by Task 2)
- Produces: `eval/2026-07-02/action_log.md`, `eval/2026-07-02/policy_gaps.md`, `eval/2026-07-02/new_bugs.md`, `eval/2026-07-02/eval_scorecard.md`, `eval/2026-07-02/streak_reports.md` (local copy of what goes to Linear)

- [ ] **Step 1: Create the analysis script**

```python
"""Analyze Bert test run results: action log, policy gaps, new bugs, eval scorecard, streak reports."""

from __future__ import annotations

import json
import os
import re
from collections import Counter

_DIR = os.path.dirname(os.path.abspath(__file__))
EVAL_DIR = os.path.join(_DIR, "eval", "2026-07-02")
RESULTS_PATH = os.path.join(EVAL_DIR, "results.json")

KNOWN_BUGS = ["meditation", "pause", "freez", "milestone", "streak"]
STREAK_KEYWORDS = ["streak", "day count", "days in a row", "consecutive"]
MEDITATION_KEYWORDS = ["meditation", "pause", "freez", "stop", "audio", "timer"]
MILESTONE_KEYWORDS = ["milestone", "badge", "achievement"]

ACTION_SYSTEM_MAP = {
    "refund": "Stripe dashboard",
    "coupon": "Stripe dashboard",
    "discount": "Stripe dashboard",
    "cancel": "Stripe dashboard",
    "subscription": "Stripe dashboard",
    "invoice": "Stripe dashboard",
    "merge": "Happier admin",
    "account": "Happier admin",
    "delete": "Happier admin",
    "password": "Happier admin",
    "email": "Help Scout / Happier admin",
    "tag": "Help Scout",
}


def load_results() -> list[dict]:
    with open(RESULTS_PATH, encoding="utf-8") as f:
        return json.load(f)


def _matches_any(text: str, keywords: list[str]) -> bool:
    text_lower = (text or "").lower()
    return any(kw in text_lower for kw in keywords)


def _guess_action_system(action_desc: str) -> str:
    action_lower = (action_desc or "").lower()
    for keyword, system in ACTION_SYSTEM_MAP.items():
        if keyword in action_lower:
            return system
    return "Unknown — review manually"


def generate_action_log(results: list[dict]) -> str:
    action_tickets = [r for r in results if r.get("needs_action") and not r.get("escalated")]
    if not action_tickets:
        return "# Action Log\n\nNo tickets require manual actions.\n"

    lines = ["# Action Log (Admin + Stripe To-Do List)\n"]
    lines.append(f"**{len(action_tickets)} ticket(s) need manual action.**\n")

    by_system: dict[str, list[dict]] = {}
    for r in action_tickets:
        action = r.get("action_description") or "Unspecified action"
        system = _guess_action_system(action)
        by_system.setdefault(system, []).append(r)

    for system, tickets in sorted(by_system.items()):
        lines.append(f"\n## {system}\n")
        for r in tickets:
            cid = r.get("conversation_id", "?")
            email = r.get("customer_email", "?")
            action = r.get("action_description") or "Unspecified"
            conf = r.get("confidence", "?")
            lines.append(f"- [ ] **#{cid}** | {email} | {action} | confidence: {conf}")
        lines.append("")

    return "\n".join(lines)


def generate_policy_gaps(results: list[dict]) -> str:
    gaps = []
    for r in results:
        if r.get("error"):
            continue
        is_gap = (
            r.get("confidence") == "low"
            or not r.get("referenced_policies")
            or _matches_any(r.get("reasoning", "") + (r.get("draft_text") or ""),
                           ["no policy", "not covered", "no documentation", "unclear policy",
                            "outside of", "not in the policy", "don't have a policy"])
        )
        if is_gap:
            gaps.append(r)

    if not gaps:
        return "# Policy Gaps\n\nAll tickets matched existing policy docs with medium or high confidence.\n"

    lines = ["# Policy Gaps\n"]
    lines.append(f"**{len(gaps)} ticket(s) had low confidence or missing policy coverage.**\n")

    for r in gaps:
        cid = r.get("conversation_id", "?")
        subject = r.get("ticket_subject", "(no subject)")
        conf = r.get("confidence", "?")
        reasoning = r.get("reasoning", "(no reasoning)")
        policies = r.get("referenced_policies") or ["(none)"]
        lines.append(f"### #{cid}: {subject}")
        lines.append(f"- **Confidence:** {conf}")
        lines.append(f"- **Policies referenced:** {', '.join(str(p) for p in policies)}")
        lines.append(f"- **Reasoning:** {reasoning}")
        lines.append("")

    return "\n".join(lines)


def generate_new_bugs(results: list[dict]) -> str:
    bug_keywords = ["bug", "broken", "error", "crash", "glitch", "not working",
                    "doesn't work", "won't load", "can't", "cannot", "issue",
                    "problem", "fail", "stuck"]
    known_patterns = MEDITATION_KEYWORDS + MILESTONE_KEYWORDS + STREAK_KEYWORDS

    new_bugs = []
    for r in results:
        subject = r.get("ticket_subject", "")
        body = r.get("ticket_body", "")
        combined = f"{subject} {body}"

        if not _matches_any(combined, bug_keywords):
            continue
        if _matches_any(combined, known_patterns):
            continue
        new_bugs.append(r)

    if not new_bugs:
        return "# New Bugs\n\nNo unrecognized bug reports found. All bug-related tickets match known issues.\n"

    lines = ["# New Bugs\n"]
    lines.append(f"**{len(new_bugs)} ticket(s) may contain new, unrecognized bugs.**\n")

    for r in new_bugs:
        cid = r.get("conversation_id", "?")
        subject = r.get("ticket_subject", "(no subject)")
        email = r.get("customer_email", "?")
        body = (r.get("ticket_body") or "")[:500]
        lines.append(f"### #{cid}: {subject}")
        lines.append(f"- **Email:** {email}")
        lines.append(f"- **Excerpt:** {body}")
        lines.append("")

    return "\n".join(lines)


def generate_streak_reports(results: list[dict]) -> str:
    streak_tickets = []
    for r in results:
        combined = f"{r.get('ticket_subject', '')} {r.get('ticket_body', '')} {r.get('reasoning', '')}"
        if _matches_any(combined, STREAK_KEYWORDS):
            streak_tickets.append(r)

    if not streak_tickets:
        return ""

    lines = ["Streak data broken / reset after Android app update\n"]
    lines.append("Steps to replicate:\n")
    lines.append("* User updates to new Hotwire Native Android app")
    lines.append("* Streak count resets or shows incorrect data")
    lines.append("* Varies by user — some see 0, others see wrong counts\n")

    for r in streak_tickets:
        email = r.get("customer_email", "(unknown)")
        body = (r.get("ticket_body") or "(no body)")[:600]
        body_cleaned = body.replace("\n", "\n> ")
        lines.append(f"User report: *{body_cleaned}*\n")
        lines.append(f"Email: [{email}](mailto:{email})\n")
        lines.append("---\n")

    return "\n".join(lines)


def generate_eval_scorecard(results: list[dict]) -> str:
    total = len(results)
    if total == 0:
        return "# Eval Scorecard\n\nNo tickets processed.\n"

    successful = [r for r in results if not r.get("error")]
    errors = [r for r in results if r.get("error")]
    drafts = [r for r in results if r.get("draft_created")]
    escalated = [r for r in results if r.get("escalated")]
    action_required = [r for r in results if r.get("needs_action")]
    auto_sendable = [r for r in results if r.get("auto_sendable")]
    account_ok = [r for r in results if r.get("account_lookup_success")]
    stripe_attempted = [r for r in results if r.get("stripe_enrichment_attempted")]
    stripe_ok = [r for r in results if r.get("stripe_enrichment_success")]
    has_policies = [r for r in successful if r.get("referenced_policies")]

    conf_counts = Counter(r.get("confidence") for r in successful)
    latencies = [r["latency_ms"] for r in successful if r.get("latency_ms")]
    input_tokens = [r["total_input_tokens"] for r in successful if r.get("total_input_tokens")]
    output_tokens = [r["total_output_tokens"] for r in successful if r.get("total_output_tokens")]

    def pct(n: int, d: int) -> str:
        return f"{n}/{d} ({n*100//d}%)" if d else "0/0"

    avg_latency = sum(latencies) // len(latencies) if latencies else 0
    avg_input = sum(input_tokens) // len(input_tokens) if input_tokens else 0
    avg_output = sum(output_tokens) // len(output_tokens) if output_tokens else 0

    lines = [
        "# Eval Scorecard\n",
        f"**Date:** July 2, 2026",
        f"**Model:** claude-sonnet-5",
        f"**Total tickets:** {total}\n",
        "## Aggregate Metrics\n",
        f"| Metric | Value |",
        f"|--------|-------|",
        f"| Draft success rate | {pct(len(drafts), total)} |",
        f"| Escalation rate | {pct(len(escalated), total)} |",
        f"| Action-required rate | {pct(len(action_required), total)} |",
        f"| Auto-sendable rate | {pct(len(auto_sendable), total)} |",
        f"| Error rate | {pct(len(errors), total)} |",
        f"| Policy coverage | {pct(len(has_policies), len(successful))} |",
        f"| Account lookup success | {pct(len(account_ok), total)} |",
        f"| Stripe enrichment success | {pct(len(stripe_ok), len(stripe_attempted))} |",
        "",
        "## Confidence Distribution\n",
        f"| Level | Count |",
        f"|-------|-------|",
        f"| High | {conf_counts.get('high', 0)} |",
        f"| Medium | {conf_counts.get('medium', 0)} |",
        f"| Low | {conf_counts.get('low', 0)} |",
        "",
        "## Performance\n",
        f"| Metric | Value |",
        f"|--------|-------|",
        f"| Avg latency | {avg_latency}ms |",
        f"| Avg input tokens | {avg_input} |",
        f"| Avg output tokens | {avg_output} |",
        f"| Total input tokens | {sum(input_tokens)} |",
        f"| Total output tokens | {sum(output_tokens)} |",
        "",
        "## Per-Ticket Detail\n",
        "| # | Subject | Conf | Draft | Action | Auto | Policies | Latency |",
        "|---|---------|------|-------|--------|------|----------|---------|",
    ]

    for r in sorted(results, key=lambda x: x.get("conversation_id", "")):
        cid = r.get("conversation_id", "?")
        subj = (r.get("ticket_subject") or "?")[:40]
        conf = r.get("confidence", "err" if r.get("error") else "?")
        draft = "Y" if r.get("draft_created") else ("ESC" if r.get("escalated") else "N")
        action = "Y" if r.get("needs_action") else "N"
        auto = "Y" if r.get("auto_sendable") else "N"
        pols = len(r.get("referenced_policies") or [])
        lat = r.get("latency_ms", "?")
        lines.append(f"| {cid} | {subj} | {conf} | {draft} | {action} | {auto} | {pols} | {lat}ms |")

    lines.append("")
    return "\n".join(lines)


def main() -> None:
    results = load_results()
    print(f"Loaded {len(results)} results from {RESULTS_PATH}")

    outputs = {
        "action_log.md": generate_action_log(results),
        "policy_gaps.md": generate_policy_gaps(results),
        "new_bugs.md": generate_new_bugs(results),
        "eval_scorecard.md": generate_eval_scorecard(results),
        "streak_reports.md": generate_streak_reports(results),
    }

    for filename, content in outputs.items():
        if not content:
            print(f"  {filename}: skipped (no matching tickets)")
            continue
        path = os.path.join(EVAL_DIR, filename)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        print(f"  {filename}: written ({len(content)} chars)")

    print(f"\nAll outputs in {EVAL_DIR}/")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run the analysis**

```bash
cd /Users/cassidystagnitti/code/code-happierMeditation/SupportAgent
python3 test_run_analysis.py
```

Expected: each output file listed with char count.

- [ ] **Step 3: Verify outputs exist**

```bash
ls -la /Users/cassidystagnitti/code/code-happierMeditation/SupportAgent/eval/2026-07-02/
```

Expected: `results.json`, `action_log.md`, `policy_gaps.md`, `new_bugs.md`, `eval_scorecard.md`, `streak_reports.md`.

---

### Task 4: Create Streak Linear Ticket and Surface New Bugs

**Files:**
- Reads: `eval/2026-07-02/streak_reports.md` (produced by Task 3)
- Reads: `eval/2026-07-02/new_bugs.md` (produced by Task 3)

**Interfaces:**
- Consumes: `streak_reports.md` content for Linear ticket body
- Produces: Linear ticket in team T (Engineering Priorities), modeled on T-759

- [ ] **Step 1: Read the streak reports file**

Read `eval/2026-07-02/streak_reports.md`. If it's empty or says "no matching tickets," skip Linear ticket creation.

- [ ] **Step 2: Create Linear ticket**

Use the Linear MCP `save_issue` tool:
- Title: "Streak data broken/reset after Android app update"
- Description: contents of `streak_reports.md`
- Team: T (Technical, ID `6c1b8aa7-78ae-4e98-919d-e0171f5b0f15`)
- Label: Bug

- [ ] **Step 3: Surface new bugs in chat**

Read `eval/2026-07-02/new_bugs.md` and present the contents directly in chat for Cassidy to review.

---

### Task 5: Review Results and Write Build Proposal

**Files:**
- Reads: all files in `eval/2026-07-02/`
- Creates: `eval/2026-07-02/build_proposal.md`

**Interfaces:**
- Consumes: all analysis outputs from Task 3
- Produces: `build_proposal.md` — the final deliverable

- [ ] **Step 1: Read all analysis outputs**

Read `eval_scorecard.md`, `action_log.md`, `policy_gaps.md`, `new_bugs.md`.

- [ ] **Step 2: Write the build proposal**

Based on the eval results, write `eval/2026-07-02/build_proposal.md` covering:

1. **Executive summary** — what worked, what didn't, key numbers
2. **What the pipeline handles well today** — high-confidence categories, auto-sendable rate
3. **Gaps and failures** — policy gaps, action gaps, low-confidence areas
4. **Recommended build priorities for Bert v1:**
   - Account action automation (which specific actions, what keys/permissions needed)
   - Knowledge gap loop (the ask-Cassidy interface — Slack vs Help Scout notes vs web UI)
   - Auto-send gating criteria
   - Policy doc additions needed
   - Monitoring and quality feedback
5. **Cost estimate** — based on token usage from this run, projected monthly cost at current ticket volume
6. **Proposed timeline** — phased rollout

- [ ] **Step 3: Present the build proposal in chat**

Read and present `build_proposal.md` to Cassidy for review.
