import os
import pytest
from typing import Optional
from unittest.mock import patch, MagicMock
from mavenagi import ErrorMessage
from mavenagi.conversation.types.stream_response import StreamResponse_Text, StreamResponse_End


def test_maven_client_raises_when_env_missing():
    """_maven_client() raises RuntimeError if any of the four env vars is absent."""
    import importlib
    with patch.dict(os.environ, {}, clear=False):
        for key in ("MAVEN_ORG_ID", "MAVEN_AGENT_ID", "MAVEN_APP_ID", "MAVEN_APP_SECRET"):
            os.environ.pop(key, None)
        # Re-import to get a clean module state with env cleared
        import maven_orchestrator
        importlib.reload(maven_orchestrator)
        with pytest.raises(RuntimeError, match="Missing Maven env vars"):
            maven_orchestrator._maven_client()


def test_maven_client_returns_client_with_valid_env():
    """_maven_client() returns a MavenAGI instance when all env vars are set."""
    env = {
        "MAVEN_ORG_ID": "org1",
        "MAVEN_AGENT_ID": "agent1",
        "MAVEN_APP_ID": "app1",
        "MAVEN_APP_SECRET": "secret1",
    }
    with patch.dict(os.environ, env):
        with patch("maven_orchestrator.MavenAGI") as mock_cls:
            import maven_orchestrator
            maven_orchestrator._maven_client()
            mock_cls.assert_called_once_with(
                organization_id="org1",
                agent_id="agent1",
                app_id="app1",
                app_secret="secret1",
            )


# ---------------------------------------------------------------------------
# Task 3: _call_maven_draft
# ---------------------------------------------------------------------------

def _make_text_event(contents: str) -> StreamResponse_Text:
    return StreamResponse_Text(contents=contents)


def _make_end_event(error: Optional[str] = None) -> StreamResponse_End:
    err_obj = ErrorMessage(message=error) if error is not None else None
    return StreamResponse_End(error=err_obj)


def test_call_maven_draft_concatenates_text_chunks():
    """_call_maven_draft() collects StreamResponse_Text chunks and joins them."""
    mock_client = MagicMock()
    mock_client.conversation.ask_stream.return_value = iter([
        _make_text_event("Hello "),
        _make_text_event("world!"),
        _make_end_event(),
    ])

    with patch("maven_orchestrator._maven_client", return_value=mock_client):
        import maven_orchestrator
        result = maven_orchestrator._call_maven_draft(
            conversation_id="123",
            subject="Test subject",
            ticket_body="Help me with my account",
            account_blob="Account Found: true",
            stripe_context="N/A",
        )

    assert result == "Hello world!"
    mock_client.conversation.initialize.assert_called_once()
    mock_client.conversation.ask_stream.assert_called_once()


def test_call_maven_draft_raises_on_stream_error():
    """_call_maven_draft() raises ValueError when StreamResponse_End carries an error."""
    mock_client = MagicMock()
    mock_client.conversation.ask_stream.return_value = iter([
        _make_end_event(error="something went wrong"),
    ])

    with patch("maven_orchestrator._maven_client", return_value=mock_client):
        import maven_orchestrator
        with pytest.raises(ValueError, match="Maven stream error"):
            maven_orchestrator._call_maven_draft(
                conversation_id="123",
                subject="Test",
                ticket_body="Help",
                account_blob="",
                stripe_context="",
            )


def test_call_maven_draft_raises_on_empty_reply():
    """_call_maven_draft() raises ValueError when Maven returns no text chunks."""
    mock_client = MagicMock()
    mock_client.conversation.ask_stream.return_value = iter([_make_end_event()])

    with patch("maven_orchestrator._maven_client", return_value=mock_client):
        import maven_orchestrator
        with pytest.raises(ValueError, match="empty reply"):
            maven_orchestrator._call_maven_draft(
                conversation_id="123",
                subject="Test",
                ticket_body="Help",
                account_blob="",
                stripe_context="",
            )


def test_call_maven_draft_invokes_log_callback():
    """_call_maven_draft() calls log_callback with progress messages."""
    mock_client = MagicMock()
    mock_client.conversation.ask_stream.return_value = iter([
        _make_text_event("response"),
        _make_end_event(),
    ])
    logs: list = []

    with patch("maven_orchestrator._maven_client", return_value=mock_client):
        import maven_orchestrator
        maven_orchestrator._call_maven_draft(
            conversation_id="123",
            subject="Test",
            ticket_body="Help",
            account_blob="",
            stripe_context="",
            log_callback=logs.append,
        )

    assert any("initializing" in msg for msg in logs)
    assert any("asking" in msg for msg in logs)
    assert any("response received" in msg for msg in logs)


# ---------------------------------------------------------------------------
# Task 4: process_maven_ticket_sync
# ---------------------------------------------------------------------------

def test_process_maven_ticket_sync_returns_expected_shape():
    """process_maven_ticket_sync returns a dict with engine=maven and core fields set."""
    import maven_orchestrator

    mock_convo = {
        "subject": "Can't log in",
        "tags": [],
        "_embedded": {},
        "primaryCustomer": {"id": 42, "email": "user@example.com", "firstName": "Test", "lastName": "User"},
    }

    hs_env = {"HELPSCOUT_APP_ID": "app1", "HELPSCOUT_APP_SECRET": "secret1"}
    with (
        patch.dict(os.environ, hs_env),
        patch("maven_orchestrator.run_triage"),
        patch("maven_orchestrator.get_access_token", return_value="tok"),
        patch("maven_orchestrator.requests.Session") as mock_session_cls,
        patch("maven_orchestrator.fetch_conversation", return_value=mock_convo),
        patch("maven_orchestrator.get_conversation_text", return_value="I can't log in"),
        patch("maven_orchestrator.fetch_customer_emails_from_helpscout", return_value=[]),
        patch("maven_orchestrator.fetch_account_contexts_for_ticket", return_value={
            "combined_blob": "Account Found: true\nSubscribed: true",
            "emails_checked": ["user@example.com"],
            "multiple_subscribed": False,
        }),
        patch("maven_orchestrator._subscription_platform", return_value="Apple"),
        patch("maven_orchestrator._call_maven_draft", return_value="Here's what you can do…"),
        patch("maven_orchestrator._update_conversation_tags"),
        patch("maven_orchestrator._helpscout_post") as mock_post,
        patch("maven_orchestrator.run_product_prioritization", return_value={"skipped": True}),
    ):
        mock_resp = MagicMock()
        mock_resp.status_code = 201
        mock_resp.headers = {"Resource-ID": "draft-99"}
        mock_post.return_value = mock_resp

        result = maven_orchestrator.process_maven_ticket_sync("555", "user@example.com")

    assert result["engine"] == "maven"
    assert result["draft_text"] == "Here's what you can do…"
    assert result["draft_created"] is True
    assert result["needs_action"] is True
    assert result["auto_sendable"] is False
    assert result["escalated"] is False
    assert result["error"] is None
