import pytest


def test_set_status_running_clears_logs():
    """Setting status to 'running' resets the logs list."""
    import sidebar_server
    sidebar_server._status.clear()
    sidebar_server._set_status("cid1", "running")
    sidebar_server._append_log("cid1", "first log")
    sidebar_server._set_status("cid1", "running")  # second run
    s = sidebar_server._get_status("cid1")
    assert s["logs"] == []


def test_append_log_accumulates_entries():
    """_append_log adds timestamped entries to the logs list."""
    import sidebar_server
    sidebar_server._status.clear()
    sidebar_server._set_status("cid2", "running")
    sidebar_server._append_log("cid2", "step one")
    sidebar_server._append_log("cid2", "step two")
    s = sidebar_server._get_status("cid2")
    assert len(s["logs"]) == 2
    assert "step one" in s["logs"][0]
    assert "step two" in s["logs"][1]


def test_set_status_done_preserves_logs():
    """Transitioning to 'done' keeps the accumulated logs."""
    import sidebar_server
    sidebar_server._status.clear()
    sidebar_server._set_status("cid3", "running")
    sidebar_server._append_log("cid3", "Maven: asking...")
    sidebar_server._set_status("cid3", "done", "Draft created")
    s = sidebar_server._get_status("cid3")
    assert s["status"] == "done"
    assert any("Maven: asking..." in entry for entry in s["logs"])


def test_get_status_returns_idle_for_unknown():
    """_get_status returns idle for unknown conversation IDs."""
    import sidebar_server
    sidebar_server._status.clear()
    s = sidebar_server._get_status("unknown-cid")
    assert s["status"] == "idle"
    assert s.get("logs", []) == []


def test_trigger_draft_accepts_engine_param():
    """
    /trigger-draft with engine=maven routes to maven pipeline (smoke test via mock).
    This exercises the dispatch logic without hitting any external services.
    """
    from fastapi.testclient import TestClient
    from unittest.mock import patch, MagicMock
    import sidebar_server

    sidebar_server.SIDEBAR_SECRET = "testsecret"
    client = TestClient(sidebar_server.app)

    with patch("sidebar_server.threading.Thread") as mock_thread:
        resp = client.post("/trigger-draft", json={
            "conversation_id": "999",
            "customer_email": "a@b.com",
            "secret": "testsecret",
            "engine": "maven",
        })

    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["engine"] == "maven"
    # Thread was started
    mock_thread.assert_called_once()
    # engine kwarg passed to thread target
    _, kwargs = mock_thread.call_args
    assert kwargs.get("kwargs", {}).get("engine") == "maven"
