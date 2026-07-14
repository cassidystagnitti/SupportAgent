"""Tests for the eval harness (SUP-459): dry-run write-safety, trends line, scorecard rows.

Dry-run write-safety approach: rather than spinning up a network-level
recorder, every write-phase function the pipeline can reach (Help Scout
POST/PUT, draft-registry write, Notion hooks, bug-registry hook, Linear
product-prioritization, triage, research) is monkeypatched to RAISE if
called. process_ticket_sync(create_draft=False) is then run over a mocked
read path with a classification crafted to trigger every write branch
(needs_action=True, low confidence + open_question, new-bug report). If any
gated branch still fires, the test fails with that hook's AssertionError.
"""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

import eval_run
from eval_reports import generate_eval_scorecard

HS_ENV = {"HELPSCOUT_APP_ID": "app1", "HELPSCOUT_APP_SECRET": "secret1", "ANTHROPIC_API_KEY": "key1"}


def _mock_convo():
    return {
        "subject": "Can't log in",
        "tags": [],
        "_embedded": {"threads": []},
        "primaryCustomer": {"id": 42, "email": "user@example.com", "firstName": "Test", "lastName": "User"},
    }


def _raiser(name):
    def _boom(*args, **kwargs):
        raise AssertionError(f"dry-run performed an external write: {name} was called")
    return _boom


def _account_ctx():
    return {
        "combined_blob": "Account Found: true\nSubscribed: true\nSubscription Platform: Apple",
        "emails_checked": ["user@example.com"],
        "multiple_subscribed": False,
    }


def test_dry_run_performs_no_external_writes(tmp_path, monkeypatch):
    """create_draft=False must not reach ANY write phase, even for a
    classification that would normally trigger every write hook."""
    import orchestrator

    monkeypatch.setattr(orchestrator.draft_registry, "REGISTRY_PATH", str(tmp_path / "r.json"))

    mock_msg = MagicMock()
    mock_msg.usage = MagicMock(input_tokens=100, output_tokens=200, cache_read_input_tokens=5000)
    parsed = {
        # Crafted to hit every gated write branch if the gates were missing:
        "draft_reply": "Here's help.",
        "escalate": False,
        "needs_action": True,               # → note POST + Notion action
        "action_description": "Refund sub_X in Stripe",
        "action_system": "stripe",
        "auto_sendable": False,
        "confidence": "low",                # → Notion gap + research trigger
        "open_question": "What is the refund window?",
        "referenced_policies": [],
        "do_not_send_reasons": [],
        "reasoning": "unsure",
        "bug_report": {"is_bug": True, "matches_known_bug": None, "new_bug_summary": "New crash on login"},
    }

    with (
        patch.dict(os.environ, {**HS_ENV, "HELPSCOUT_NOTE_USER_ID": "7"}),
        patch("orchestrator.get_access_token", return_value="tok"),
        patch("orchestrator.requests.Session"),
        patch("orchestrator.fetch_conversation", return_value=_mock_convo()),
        patch("orchestrator._fetch_conversation_threads", return_value=[]),
        patch("orchestrator.get_conversation_text", return_value="I can't log in"),
        patch("orchestrator.fetch_customer_emails_from_helpscout", return_value=[]),
        patch("orchestrator.fetch_account_contexts_for_ticket", return_value=_account_ctx()),
        patch("orchestrator._call_claude_draft_with_action_retry", return_value=(mock_msg, parsed, "raw")),
        # Write phases: all must raise if reached.
        patch("orchestrator.run_triage", side_effect=_raiser("run_triage")),
        patch("orchestrator._helpscout_post", side_effect=_raiser("_helpscout_post")),
        patch("orchestrator._update_conversation_tags", side_effect=_raiser("_update_conversation_tags")),
        patch("orchestrator.record_gap_and_action", side_effect=_raiser("record_gap_and_action (Notion)")),
        patch.object(orchestrator.bug_registry, "record_bug", side_effect=_raiser("bug_registry.record_bug")),
        patch.object(orchestrator.draft_registry, "set", side_effect=_raiser("draft_registry.set")),
        patch("orchestrator.run_product_prioritization", side_effect=_raiser("run_product_prioritization")),
        # Research: would trigger for low confidence — must be skipped for cost.
        patch("orchestrator.should_research", return_value=True),
        patch("orchestrator.run_research", side_effect=_raiser("run_research")),
    ):
        # skip_triage=False on purpose: dry-run alone must gate triage writes.
        result = orchestrator.process_ticket_sync("901", "user@example.com", create_draft=False)

    assert result["dry_run"] is True
    assert result["error"] is None
    # Classification is real and telemetry recorded, including cache-read usage.
    assert result["confidence"] == "low"
    assert result["cache_read_input_tokens"] == 5000
    assert result["total_input_tokens"] == 100
    # draft_created=True means "would have been posted"; nothing actually posted.
    assert result["draft_created"] is True
    assert result["helpscout_draft_id"] is None
    assert result["note_created"] is False
    assert result["research_ran"] is False
    assert result["product_prioritization"]["skipped"] is True
    # Registry untouched.
    assert orchestrator.draft_registry.get("901") is None


def test_dry_run_escalation_creates_no_draft(tmp_path, monkeypatch):
    """Escalations in dry-run behave like live: no draft, escalated=True."""
    import orchestrator

    monkeypatch.setattr(orchestrator.draft_registry, "REGISTRY_PATH", str(tmp_path / "r.json"))

    mock_msg = MagicMock()
    mock_msg.usage = None
    parsed = {
        "draft_reply": None,
        "escalate": True,
        "escalate_reason": "legal threat",
        "needs_action": True,
        "action_description": "Escalate to lead",
        "action_system": "helpscout",
        "auto_sendable": False,
        "confidence": "high",
        "referenced_policies": ["escalations.md"],
        "do_not_send_reasons": [],
        "reasoning": "legal",
    }

    with (
        patch.dict(os.environ, HS_ENV),
        patch("orchestrator.get_access_token", return_value="tok"),
        patch("orchestrator.requests.Session"),
        patch("orchestrator.fetch_conversation", return_value=_mock_convo()),
        patch("orchestrator._fetch_conversation_threads", return_value=[]),
        patch("orchestrator.get_conversation_text", return_value="I will sue"),
        patch("orchestrator.fetch_customer_emails_from_helpscout", return_value=[]),
        patch("orchestrator.fetch_account_contexts_for_ticket", return_value=_account_ctx()),
        patch("orchestrator._call_claude_draft_with_action_retry", return_value=(mock_msg, parsed, "raw")),
        patch("orchestrator._helpscout_post", side_effect=_raiser("_helpscout_post")),
        patch("orchestrator._update_conversation_tags", side_effect=_raiser("_update_conversation_tags")),
        patch("orchestrator.record_gap_and_action", side_effect=_raiser("record_gap_and_action")),
        patch.object(orchestrator.bug_registry, "record_bug", side_effect=_raiser("record_bug")),
        patch.object(orchestrator.draft_registry, "set", side_effect=_raiser("draft_registry.set")),
        patch("orchestrator.run_product_prioritization", side_effect=_raiser("run_product_prioritization")),
        patch("orchestrator.should_research", return_value=False),
    ):
        result = orchestrator.process_ticket_sync("902", "user@example.com", create_draft=False, skip_triage=True)

    assert result["escalated"] is True
    assert result["draft_created"] is False
    assert result["note_created"] is False


def test_dry_run_still_skips_existing_draft(tmp_path, monkeypatch):
    """The draft-registry skip guard still applies in dry-run so the scorecard's
    skipped count reflects reality."""
    import orchestrator

    monkeypatch.setattr(orchestrator.draft_registry, "REGISTRY_PATH", str(tmp_path / "r.json"))
    orchestrator.draft_registry.set("903", "thread-1", "2026-07-02T00:00:00+00:00")

    with (
        patch.dict(os.environ, HS_ENV),
        patch("orchestrator.get_access_token", return_value="tok"),
        patch("orchestrator.requests.Session"),
        patch("orchestrator.fetch_conversation", return_value=_mock_convo()),
        patch("orchestrator._fetch_conversation_threads", return_value=[]),
        patch("orchestrator.anthropic.Anthropic", side_effect=_raiser("anthropic client")),
    ):
        result = orchestrator.process_ticket_sync("903", "user@example.com", create_draft=False)

    assert result["skipped_existing_draft"] is True
    assert result["draft_created"] is False


# ---------------------------------------------------------------------------
# Trends line + scorecard additions
# ---------------------------------------------------------------------------

def _synthetic_results():
    return [
        {
            "conversation_id": "1", "confidence": "high", "draft_created": True,
            "referenced_policies": ["a.md"], "latency_ms": 1000,
            "cache_read_input_tokens": 20000, "reasoning": "fine", "draft_text": "x",
        },
        {
            "conversation_id": "2", "confidence": "low", "draft_created": True,
            "referenced_policies": [], "latency_ms": 3000,
            "cache_read_input_tokens": 10000, "reasoning": "no policy covers this", "draft_text": "y",
        },
        {
            "conversation_id": "3", "skipped_existing_draft": True, "draft_created": False,
            "referenced_policies": [], "latency_ms": 5,
        },
        {"conversation_id": "4", "error": "boom"},
    ]


def test_build_trends_line_format():
    line = eval_run.build_trends_line(_synthetic_results(), "2026-07-02")
    cells = [c.strip() for c in line.strip().strip("|").split("|")]
    assert cells[0] == "2026-07-02"
    assert cells[1] == "4"           # tickets
    assert cells[2] == "50%"         # draft% (2/4)
    assert cells[3] == "33%"         # coverage% (1/3 successful)
    assert cells[4] == "1/0/1"       # high/med/low
    assert cells[5] == "2"           # gaps: low-conf + no-policy skipped ticket
    assert cells[6] == "1335"        # avg_ms over successful with latency
    assert cells[7] == "15000"       # cache_read_avg


def test_append_trends_line_creates_file_with_header(tmp_path):
    trends = tmp_path / "trends.md"
    eval_run.append_trends_line(str(trends), "| 2026-07-02 | 4 | 50% | 33% | 1/0/1 | 2 | 1335 | 15000 |")
    content = trends.read_text()
    assert content.startswith("# Eval Trends\n")
    assert "| date | tickets | draft% | coverage% | high/med/low | gaps | avg_ms | cache_read_avg |" in content
    assert content.rstrip().endswith("| 2026-07-02 | 4 | 50% | 33% | 1/0/1 | 2 | 1335 | 15000 |")


def test_append_trends_line_appends_without_duplicate_header(tmp_path):
    trends = tmp_path / "trends.md"
    eval_run.append_trends_line(str(trends), "| a |")
    eval_run.append_trends_line(str(trends), "| b |")
    content = trends.read_text()
    assert content.count("# Eval Trends") == 1
    assert content.rstrip().split("\n")[-2:] == ["| a |", "| b |"]


def test_scorecard_includes_skipped_and_cache_read_rows():
    sc = generate_eval_scorecard(_synthetic_results(), run_date="2026-07-02")
    assert "| Skipped (existing draft) | 1/4 |" in sc
    assert "| Avg cache-read tokens | 15000 |" in sc


def test_scorecard_empty_results():
    assert "No tickets processed" in generate_eval_scorecard([])
