"""Reduce step: turn the ticket index into stats + a glanceable HTML summary.

``mailbox_stats`` is a pure aggregation the session uses to talk about volume /
what's new / what's urgent. ``render_summary_html`` produces a standalone block
(no external assets) suitable for an Artifact or inline widget.
"""

from __future__ import annotations

import html
from collections import Counter


def mailbox_stats(records: list[dict]) -> dict:
    by_category: Counter = Counter()
    known_bug_hits: Counter = Counter()
    urgent = 0
    new = 0
    for rec in records:
        by_category[rec.get("category") or "unknown"] += 1
        bug = rec.get("matches_known_bug")
        if bug:
            known_bug_hits[bug] += 1
        if rec.get("urgent"):
            urgent += 1
        if rec.get("is_new"):
            new += 1
    return {
        "total": len(records),
        "urgent_count": urgent,
        "new_count": new,
        "by_category": dict(by_category),
        "known_bug_hits": dict(known_bug_hits),
    }


def _esc(value) -> str:
    return html.escape(str(value if value is not None else ""))


def render_summary_html(state: dict) -> str:
    records = state.get("records", [])
    stats = mailbox_stats(records)
    date = _esc(state.get("date"))

    cats = ", ".join(f"{_esc(k)}: {v}" for k, v in sorted(stats["by_category"].items())) or "—"
    bugs = ", ".join(f"{_esc(k)}: {v}" for k, v in sorted(stats["known_bug_hits"].items())) or "—"

    rows = []
    for rec in records:
        flag = "🔴" if rec.get("urgent") else ("🆕" if rec.get("is_new") else "")
        bug = rec.get("matches_known_bug")
        bug_cell = _esc(bug) if bug else "—"
        rows.append(
            "<tr>"
            f"<td>{_esc(rec.get('conversation_id'))}</td>"
            f"<td>{_esc(rec.get('customer'))}</td>"
            f"<td>{_esc(rec.get('category'))}</td>"
            f"<td>{_esc(rec.get('one_line'))}</td>"
            f"<td>{bug_cell}</td>"
            f"<td>{flag}</td>"
            "</tr>"
        )
    body_rows = "\n".join(rows) or '<tr><td colspan="6">No open tickets.</td></tr>'

    return f"""<div class="bert-summary" style="font-family:system-ui,sans-serif;font-size:14px">
  <h2>Mailbox review — {date}</h2>
  <p><strong>{stats['total']}</strong> open ·
     <strong>{stats['urgent_count']}</strong> urgent ·
     <strong>{stats['new_count']}</strong> new</p>
  <p><strong>By category:</strong> {cats}</p>
  <p><strong>Known-bug hits:</strong> {bugs}</p>
  <table border="1" cellpadding="6" cellspacing="0" style="border-collapse:collapse;width:100%">
    <thead><tr><th>ID</th><th>Customer</th><th>Category</th><th>Summary</th><th>Known bug</th><th></th></tr></thead>
    <tbody>
{body_rows}
    </tbody>
  </table>
</div>"""
