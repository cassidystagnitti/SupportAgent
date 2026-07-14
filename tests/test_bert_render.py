from __future__ import annotations

import bert.render as r

RECS = [
    {"conversation_id": 1, "customer": "A", "category": "billing", "one_line": "refund",
     "urgent": True, "is_new": True, "matches_known_bug": None},
    {"conversation_id": 2, "customer": "B", "category": "billing", "one_line": "charge",
     "urgent": False, "is_new": False, "matches_known_bug": "streaks"},
    {"conversation_id": 3, "customer": "C", "category": "bug", "one_line": "<script>",
     "urgent": False, "is_new": True, "matches_known_bug": "streaks"},
]


def test_stats():
    s = r.mailbox_stats(RECS)
    assert s["total"] == 3
    assert s["urgent_count"] == 1
    assert s["new_count"] == 2
    assert s["by_category"] == {"billing": 2, "bug": 1}
    assert s["known_bug_hits"] == {"streaks": 2}


def test_stats_empty():
    s = r.mailbox_stats([])
    assert s["total"] == 0
    assert s["by_category"] == {}
    assert s["known_bug_hits"] == {}


def test_html_contains_ids_and_escapes():
    html = r.render_summary_html(
        {"date": "2026-07-06", "records": RECS, "brief": ["x"], "statuses": {}}
    )
    assert "2026-07-06" in html
    assert "billing" in html
    assert "&lt;script&gt;" in html
    assert "<script>" not in html


def test_html_handles_empty_mailbox():
    html = r.render_summary_html({"date": "2026-07-06", "records": [], "brief": [], "statuses": {}})
    assert "2026-07-06" in html
