"""Integration tests for the draft-registry wiring inside process_ticket_sync (SUP-461)."""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest


def _mock_convo():
    return {
        "subject": "Can't log in",
        "tags": [],
        "_embedded": {"threads": []},
        "primaryCustomer": {"id": 42, "email": "user@example.com", "firstName": "Test", "lastName": "User"},
    }


HS_ENV = {"HELPSCOUT_APP_ID": "app1", "HELPSCOUT_APP_SECRET": "secret1", "ANTHROPIC_API_KEY": "key1"}


def test_supersede_note_includes_warning_banner():
    import orchestrator

    parsed = {
        "escalate": False,
        "needs_action": False,
        "auto_sendable": True,
        "confidence": "high",
        "reasoning": "x",
        "referenced_policies": [],
        "do_not_send_reasons": [],
    }
    html = orchestrator._format_internal_note_html(
        parsed=parsed,
        stripe_lines_for_note="n/a",
        supersedes_existing_draft=True,
    )
    assert "⚠️ Supersedes the earlier draft — discard the old one." in html


def test_note_omits_warning_banner_by_default():
    import orchestrator

    parsed = {
        "escalate": False,
        "needs_action": False,
        "auto_sendable": True,
        "confidence": "high",
        "reasoning": "x",
        "referenced_policies": [],
        "do_not_send_reasons": [],
    }
    html = orchestrator._format_internal_note_html(parsed=parsed, stripe_lines_for_note="n/a")
    assert "Supersedes" not in html


def test_skips_drafting_when_existing_draft_and_not_reply_mode(tmp_path, monkeypatch):
    """A conversation with an existing recorded draft, not in reply mode, and no
    force flag should return early with skipped_existing_draft=True and never
    reach the Claude call or create a Help Scout draft."""
    import orchestrator

    monkeypatch.setattr(orchestrator.draft_registry, "REGISTRY_PATH", str(tmp_path / "r.json"))
    orchestrator.draft_registry.set("555", "thread-1", "2026-07-02T00:00:00+00:00")

    claude_called = []

    with (
        patch.dict(os.environ, HS_ENV),
        patch("orchestrator.get_access_token", return_value="tok"),
        patch("orchestrator.requests.Session"),
        patch("orchestrator.fetch_conversation", return_value=_mock_convo()),
        patch("orchestrator._fetch_conversation_threads", return_value=[]),
        patch("orchestrator.run_triage"),
        patch("orchestrator.anthropic.Anthropic", side_effect=lambda **k: claude_called.append(1)),
        patch("orchestrator._helpscout_post") as mock_post,
    ):
        result = orchestrator.process_ticket_sync("555", "user@example.com")

    assert result["skipped_existing_draft"] is True
    assert result["draft_created"] is False
    assert not claude_called
    mock_post.assert_not_called()


def test_does_not_skip_when_reply_mode(tmp_path, monkeypatch):
    """Existing draft + reply_mode=True should NOT skip — it should proceed to
    supersede (new draft created, existing draft left as-is)."""
    import orchestrator

    monkeypatch.setattr(orchestrator.draft_registry, "REGISTRY_PATH", str(tmp_path / "r.json"))
    orchestrator.draft_registry.set("556", "thread-2", "2026-07-02T00:00:00+00:00")

    threads = [{"type": "message", "state": "published"}]

    with (
        patch.dict(os.environ, HS_ENV),
        patch("orchestrator.get_access_token", return_value="tok"),
        patch("orchestrator.requests.Session"),
        patch("orchestrator.fetch_conversation", return_value=_mock_convo()),
        patch("orchestrator._fetch_conversation_threads", return_value=threads),
        patch("orchestrator.run_triage"),
        patch("orchestrator.get_conversation_history", return_value=("history", "latest message")),
        patch("orchestrator.fetch_customer_emails_from_helpscout", return_value=[]),
        patch("orchestrator.fetch_account_contexts_for_ticket", return_value={
            "combined_blob": "Account Found: true\nSubscribed: true\nSubscription Platform: Apple",
            "emails_checked": ["user@example.com"],
            "multiple_subscribed": False,
        }),
        patch("orchestrator._call_claude_draft_with_action_retry") as mock_claude,
        patch("orchestrator.should_research", return_value=False),
        patch("orchestrator._update_conversation_tags"),
        patch("orchestrator._helpscout_post") as mock_post,
        patch("orchestrator.record_gap_and_action"),
        patch("orchestrator.bug_registry.record_bug", return_value=None),
        patch("orchestrator.run_product_prioritization", return_value={"skipped": True}),
    ):
        mock_msg = MagicMock()
        mock_msg.usage = None
        mock_claude.return_value = (
            mock_msg,
            {
                "draft_reply": "Here's help.",
                "escalate": False,
                "needs_action": False,
                "auto_sendable": True,
                "confidence": "high",
                "referenced_policies": [],
                "do_not_send_reasons": [],
                "reasoning": "straightforward",
            },
            "raw",
        )
        mock_resp = MagicMock()
        mock_resp.status_code = 201
        mock_resp.headers = {"Resource-ID": "draft-new-99"}
        mock_post.return_value = mock_resp

        result = orchestrator.process_ticket_sync("556", "user@example.com")

    assert result.get("skipped_existing_draft") is False
    assert result["draft_created"] is True
    assert result["supersedes_existing_draft"] is True
    # Registry now points at the NEW thread id, not the stale one.
    assert orchestrator.draft_registry.get("556")["thread_id"] == "draft-new-99"


def test_records_new_draft_in_registry_when_no_existing_draft(tmp_path, monkeypatch):
    """First-time draft creation (no existing registry entry) should record the
    new thread id in the registry and NOT mark it as superseding anything."""
    import orchestrator

    monkeypatch.setattr(orchestrator.draft_registry, "REGISTRY_PATH", str(tmp_path / "r.json"))

    with (
        patch.dict(os.environ, HS_ENV),
        patch("orchestrator.get_access_token", return_value="tok"),
        patch("orchestrator.requests.Session"),
        patch("orchestrator.fetch_conversation", return_value=_mock_convo()),
        patch("orchestrator._fetch_conversation_threads", return_value=[]),
        patch("orchestrator.run_triage"),
        patch("orchestrator.get_conversation_text", return_value="I can't log in"),
        patch("orchestrator.fetch_customer_emails_from_helpscout", return_value=[]),
        patch("orchestrator.fetch_account_contexts_for_ticket", return_value={
            "combined_blob": "Account Found: true\nSubscribed: true\nSubscription Platform: Apple",
            "emails_checked": ["user@example.com"],
            "multiple_subscribed": False,
        }),
        patch("orchestrator._call_claude_draft_with_action_retry") as mock_claude,
        patch("orchestrator.should_research", return_value=False),
        patch("orchestrator._update_conversation_tags"),
        patch("orchestrator._helpscout_post") as mock_post,
        patch("orchestrator.record_gap_and_action"),
        patch("orchestrator.bug_registry.record_bug", return_value=None),
        patch("orchestrator.run_product_prioritization", return_value={"skipped": True}),
    ):
        mock_msg = MagicMock()
        mock_msg.usage = None
        mock_claude.return_value = (
            mock_msg,
            {
                "draft_reply": "Here's help.",
                "escalate": False,
                "needs_action": False,
                "auto_sendable": True,
                "confidence": "high",
                "referenced_policies": [],
                "do_not_send_reasons": [],
                "reasoning": "straightforward",
            },
            "raw",
        )
        mock_resp = MagicMock()
        mock_resp.status_code = 201
        mock_resp.headers = {"Resource-ID": "draft-fresh-1"}
        mock_post.return_value = mock_resp

        result = orchestrator.process_ticket_sync("557", "user@example.com")

    assert result["draft_created"] is True
    assert result["supersedes_existing_draft"] is False
    assert orchestrator.draft_registry.get("557")["thread_id"] == "draft-fresh-1"


def test_force_bypasses_skip_and_supersedes(tmp_path, monkeypatch):
    """force=True with an existing draft (even outside reply_mode) should
    supersede rather than skip."""
    import orchestrator

    monkeypatch.setattr(orchestrator.draft_registry, "REGISTRY_PATH", str(tmp_path / "r.json"))
    orchestrator.draft_registry.set("558", "thread-old", "2026-07-02T00:00:00+00:00")

    with (
        patch.dict(os.environ, HS_ENV),
        patch("orchestrator.get_access_token", return_value="tok"),
        patch("orchestrator.requests.Session"),
        patch("orchestrator.fetch_conversation", return_value=_mock_convo()),
        patch("orchestrator._fetch_conversation_threads", return_value=[]),
        patch("orchestrator.run_triage"),
        patch("orchestrator.get_conversation_text", return_value="I can't log in"),
        patch("orchestrator.fetch_customer_emails_from_helpscout", return_value=[]),
        patch("orchestrator.fetch_account_contexts_for_ticket", return_value={
            "combined_blob": "Account Found: true\nSubscribed: true\nSubscription Platform: Apple",
            "emails_checked": ["user@example.com"],
            "multiple_subscribed": False,
        }),
        patch("orchestrator._call_claude_draft_with_action_retry") as mock_claude,
        patch("orchestrator.should_research", return_value=False),
        patch("orchestrator._update_conversation_tags"),
        patch("orchestrator._helpscout_post") as mock_post,
        patch("orchestrator.record_gap_and_action"),
        patch("orchestrator.bug_registry.record_bug", return_value=None),
        patch("orchestrator.run_product_prioritization", return_value={"skipped": True}),
    ):
        mock_msg = MagicMock()
        mock_msg.usage = None
        mock_claude.return_value = (
            mock_msg,
            {
                "draft_reply": "Here's help.",
                "escalate": False,
                "needs_action": False,
                "auto_sendable": True,
                "confidence": "high",
                "referenced_policies": [],
                "do_not_send_reasons": [],
                "reasoning": "straightforward",
            },
            "raw",
        )
        mock_resp = MagicMock()
        mock_resp.status_code = 201
        mock_resp.headers = {"Resource-ID": "draft-forced-1"}
        mock_post.return_value = mock_resp

        result = orchestrator.process_ticket_sync("558", "user@example.com", force=True)

    assert result["skipped_existing_draft"] is False
    assert result["draft_created"] is True
    assert result["supersedes_existing_draft"] is True


# ---------------------------------------------------------------------------
# _customer_replied_after_draft — staleness detector
# ---------------------------------------------------------------------------

def test_customer_replied_after_draft_true_when_customer_newer():
    import orchestrator

    threads = [
        {"id": "c2", "type": "customer", "createdAt": "2026-07-09T10:00:00Z"},
        {"id": "d1", "type": "message", "state": "draft", "createdAt": "2026-07-09T09:00:00Z"},
        {"id": "c1", "type": "customer", "createdAt": "2026-07-09T08:00:00Z"},
    ]
    assert orchestrator._customer_replied_after_draft(threads, "d1") is True


def test_customer_replied_after_draft_false_when_no_newer_customer():
    import orchestrator

    threads = [
        {"id": "d1", "type": "message", "state": "draft", "createdAt": "2026-07-09T09:00:00Z"},
        {"id": "c1", "type": "customer", "createdAt": "2026-07-09T08:00:00Z"},
    ]
    assert orchestrator._customer_replied_after_draft(threads, "d1") is False


def test_customer_replied_after_draft_false_when_no_customer_threads():
    import orchestrator

    threads = [{"id": "d1", "type": "message", "state": "draft", "createdAt": "2026-07-09T09:00:00Z"}]
    assert orchestrator._customer_replied_after_draft(threads, "d1") is False


def test_customer_replied_after_draft_none_when_draft_thread_absent():
    import orchestrator

    threads = [{"id": "c1", "type": "customer", "createdAt": "2026-07-09T10:00:00Z"}]
    assert orchestrator._customer_replied_after_draft(threads, "d-missing") is None


def test_customer_replied_after_draft_ignores_threads_without_createdat():
    import orchestrator

    threads = [
        {"id": "c2", "type": "customer"},  # no createdAt — must be ignored, not crash
        {"id": "d1", "type": "message", "state": "draft", "createdAt": "2026-07-09T09:00:00Z"},
    ]
    assert orchestrator._customer_replied_after_draft(threads, "d1") is False


def test_stale_draft_refreshes_in_place_not_new_post(tmp_path, monkeypatch):
    """Existing draft + a newer CUSTOMER reply (no agent reply, not forced) must
    NOT skip and must NOT stack a new draft — it refreshes the same thread in
    place via PATCH so the draft answers the most recent message."""
    import orchestrator

    monkeypatch.setattr(orchestrator.draft_registry, "REGISTRY_PATH", str(tmp_path / "r.json"))
    orchestrator.draft_registry.set("559", "thread-live", "2026-07-09T09:00:00Z")

    threads = [
        {"id": "c-new", "type": "customer", "createdAt": "2026-07-09T10:00:00Z"},
        {"id": "thread-live", "type": "message", "state": "draft", "createdAt": "2026-07-09T09:00:00Z"},
        {"id": "c-old", "type": "customer", "createdAt": "2026-07-09T08:00:00Z"},
    ]

    with (
        patch.dict(os.environ, HS_ENV),
        patch("orchestrator.get_access_token", return_value="tok"),
        patch("orchestrator.requests.Session"),
        patch("orchestrator.fetch_conversation", return_value=_mock_convo()),
        patch("orchestrator._fetch_conversation_threads", return_value=threads),
        patch("orchestrator.run_triage"),
        patch("orchestrator.get_conversation_text", return_value="original + newest customer message"),
        patch("orchestrator.fetch_customer_emails_from_helpscout", return_value=[]),
        patch("orchestrator.fetch_account_contexts_for_ticket", return_value={
            "combined_blob": "Account Found: true\nSubscribed: true\nSubscription Platform: Apple",
            "emails_checked": ["user@example.com"],
            "multiple_subscribed": False,
        }),
        patch("orchestrator._call_claude_draft_with_action_retry") as mock_claude,
        patch("orchestrator.should_research", return_value=False),
        patch("orchestrator._update_conversation_tags"),
        patch("orchestrator._helpscout_post") as mock_post,
        patch("orchestrator._helpscout_patch_thread_text") as mock_patch,
        patch("orchestrator.record_gap_and_action"),
        patch("orchestrator.bug_registry.record_bug", return_value=None),
        patch("orchestrator.run_product_prioritization", return_value={"skipped": True}),
    ):
        mock_msg = MagicMock()
        mock_msg.usage = None
        mock_claude.return_value = (
            mock_msg,
            {
                "draft_reply": "Fresh reply addressing the newest message.",
                "escalate": False,
                "needs_action": False,
                "auto_sendable": True,
                "confidence": "high",
                "referenced_policies": [],
                "do_not_send_reasons": [],
                "reasoning": "straightforward",
            },
            "raw",
        )

        result = orchestrator.process_ticket_sync("559", "user@example.com")

    assert result["skipped_existing_draft"] is False
    assert result["draft_created"] is True
    assert result["draft_updated_in_place"] is True
    # Refreshed the same thread in place; did NOT POST a new reply draft.
    mock_patch.assert_called_once()
    patch_args = mock_patch.call_args
    assert "thread-live" in [str(a) for a in patch_args.args] or \
        str(patch_args.kwargs.get("thread_id")) == "thread-live"
    for call in mock_post.call_args_list:
        url = call.args[1] if len(call.args) > 1 else call.kwargs.get("url", "")
        assert "/reply" not in str(url), f"unexpected reply POST: {url}"
    # Registry still points at the same thread — no stacking.
    assert orchestrator.draft_registry.get("559")["thread_id"] == "thread-live"
