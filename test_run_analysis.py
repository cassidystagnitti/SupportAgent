"""Analyze Bert test run results: action log, policy gaps, new bugs, eval scorecard, streak reports."""

from __future__ import annotations

import json
import os
from collections import Counter

_DIR = os.path.dirname(os.path.abspath(__file__))
EVAL_DIR = os.path.join(_DIR, "eval", "2026-07-02")
RESULTS_PATH = os.path.join(EVAL_DIR, "results.json")

STREAK_KEYWORDS = ["streak", "day count", "days in a row", "consecutive"]
MEDITATION_KEYWORDS = ["meditation", "pause", "freez", "stop", "audio", "timer"]
MILESTONE_KEYWORDS = ["milestone", "badge", "achievement"]
DOWNLOAD_KEYWORDS = ["download", "offline", "cloud icon"]

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
    "restore": "Happier admin",
    "streak": "Happier admin",
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
    gap_phrases = [
        "no policy", "not covered", "no documentation", "unclear policy",
        "outside of", "not in the policy", "don't have a policy",
        "no specific policy", "no existing policy",
    ]
    gaps = []
    for r in results:
        if r.get("error"):
            continue
        reasoning_and_draft = (r.get("reasoning") or "") + " " + (r.get("draft_text") or "")
        is_gap = (
            r.get("confidence") == "low"
            or not r.get("referenced_policies")
            or _matches_any(reasoning_and_draft, gap_phrases)
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
    bug_keywords = [
        "bug", "broken", "error", "crash", "glitch", "not working",
        "doesn't work", "won't load", "can't", "cannot", "issue",
        "problem", "fail", "stuck", "malfunction",
    ]
    known_patterns = (
        MEDITATION_KEYWORDS + MILESTONE_KEYWORDS + STREAK_KEYWORDS + DOWNLOAD_KEYWORDS
    )

    new_bugs = []
    for r in results:
        subject = r.get("ticket_subject", "")
        body = r.get("ticket_body", "") or ""
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
        return f"{n}/{d} ({n * 100 // d}%)" if d else "0/0"

    avg_latency = sum(latencies) // len(latencies) if latencies else 0
    avg_input = sum(input_tokens) // len(input_tokens) if input_tokens else 0
    avg_output = sum(output_tokens) // len(output_tokens) if output_tokens else 0

    lines = [
        "# Eval Scorecard\n",
        "**Date:** July 2, 2026",
        "**Model:** claude-sonnet-5",
        f"**Total tickets:** {total}\n",
        "## Aggregate Metrics\n",
        "| Metric | Value |",
        "|--------|-------|",
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
        "| Level | Count |",
        "|-------|-------|",
        f"| High | {conf_counts.get('high', 0)} |",
        f"| Medium | {conf_counts.get('medium', 0)} |",
        f"| Low | {conf_counts.get('low', 0)} |",
        "",
        "## Performance\n",
        "| Metric | Value |",
        "|--------|-------|",
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
    }

    for filename, content in outputs.items():
        if not content:
            print(f"  {filename}: skipped (no content)")
            continue
        path = os.path.join(EVAL_DIR, filename)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        print(f"  {filename}: written ({len(content)} chars)")

    print(f"\nAll outputs in {EVAL_DIR}/")


if __name__ == "__main__":
    main()
