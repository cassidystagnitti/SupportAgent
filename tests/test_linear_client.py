"""Tests for linear_client.py — Linear GraphQL search + issue creation."""

from __future__ import annotations

import linear_client


# ---------------------------------------------------------------------------
# search_issues
# ---------------------------------------------------------------------------

def test_search_parses_nodes(monkeypatch):
    class R:
        status_code = 200

        def json(self):
            return {"data": {"searchIssues": {"nodes": [
                {"identifier": "T-787", "title": "DND broken",
                 "state": {"name": "Todo"}, "url": "https://linear.app/x", "description": "d"}]}}}

        def raise_for_status(self):
            pass

    captured = {}

    def fake_post(*args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return R()

    monkeypatch.setattr(linear_client.requests, "post", fake_post)
    out = linear_client.search_issues("do not disturb")

    assert out[0]["identifier"] == "T-787"
    assert out[0]["state"] == "Todo"
    assert out[0]["title"] == "DND broken"
    assert out[0]["url"] == "https://linear.app/x"
    assert out[0]["description"] == "d"

    # Verify request shape: correct endpoint, auth header (no Bearer), term variable
    kwargs = captured["kwargs"]
    assert kwargs["headers"]["Authorization"] == linear_client._linear_headers()["Authorization"]
    assert "Bearer" not in kwargs["headers"]["Authorization"]
    body = kwargs["json"]
    assert "searchIssues" in body["query"]
    assert body["variables"]["term"] == "do not disturb"
    assert body["variables"]["first"] == 10


def test_search_issues_empty_nodes(monkeypatch):
    class R:
        status_code = 200

        def json(self):
            return {"data": {"searchIssues": {"nodes": []}}}

        def raise_for_status(self):
            pass

    monkeypatch.setattr(linear_client.requests, "post", lambda *a, **k: R())
    out = linear_client.search_issues("nonexistent thing")
    assert out == []


def test_search_issues_missing_state_defaults_empty(monkeypatch):
    class R:
        status_code = 200

        def json(self):
            return {"data": {"searchIssues": {"nodes": [
                {"identifier": "T-1", "title": "No state", "state": None,
                 "url": "https://linear.app/y", "description": None}]}}}

        def raise_for_status(self):
            pass

    monkeypatch.setattr(linear_client.requests, "post", lambda *a, **k: R())
    out = linear_client.search_issues("no state")
    assert out[0]["state"] == ""
    assert out[0]["description"] == ""


def test_search_issues_respects_first_param(monkeypatch):
    captured = {}

    class R:
        status_code = 200

        def json(self):
            return {"data": {"searchIssues": {"nodes": []}}}

        def raise_for_status(self):
            pass

    def fake_post(*args, **kwargs):
        captured["kwargs"] = kwargs
        return R()

    monkeypatch.setattr(linear_client.requests, "post", fake_post)
    linear_client.search_issues("streak", first=5)
    assert captured["kwargs"]["json"]["variables"]["first"] == 5


def test_search_issues_uses_technical_team_env(monkeypatch):
    monkeypatch.setenv("LINEAR_TECHNICAL_TEAM_ID", "custom-team-id")
    captured = {}

    class R:
        status_code = 200

        def json(self):
            return {"data": {"searchIssues": {"nodes": []}}}

        def raise_for_status(self):
            pass

    def fake_post(*args, **kwargs):
        captured["kwargs"] = kwargs
        return R()

    monkeypatch.setattr(linear_client.requests, "post", fake_post)
    linear_client.search_issues("streak")
    assert captured["kwargs"]["json"]["variables"]["teamId"] == "custom-team-id"


def test_search_issues_falls_back_to_constant_team_id(monkeypatch):
    monkeypatch.delenv("LINEAR_TECHNICAL_TEAM_ID", raising=False)
    captured = {}

    class R:
        status_code = 200

        def json(self):
            return {"data": {"searchIssues": {"nodes": []}}}

        def raise_for_status(self):
            pass

    def fake_post(*args, **kwargs):
        captured["kwargs"] = kwargs
        return R()

    monkeypatch.setattr(linear_client.requests, "post", fake_post)
    linear_client.search_issues("streak")
    assert captured["kwargs"]["json"]["variables"]["teamId"] == linear_client.DEFAULT_TECHNICAL_TEAM_ID
    assert linear_client.DEFAULT_TECHNICAL_TEAM_ID == "6c1b8aa7-78ae-4e98-919d-e0171f5b0f15"


# ---------------------------------------------------------------------------
# create_issue
# ---------------------------------------------------------------------------

def test_create_issue_success(monkeypatch):
    captured = {}

    class R:
        status_code = 200

        def json(self):
            return {"data": {"issueCreate": {
                "success": True,
                "issue": {
                    "identifier": "T-800",
                    "title": "New bug",
                    "url": "https://linear.app/x/issue/T-800",
                    "state": {"name": "Backlog"},
                    "description": "desc",
                },
            }}}

        def raise_for_status(self):
            pass

    def fake_post(*args, **kwargs):
        captured["kwargs"] = kwargs
        return R()

    monkeypatch.setattr(linear_client.requests, "post", fake_post)
    out = linear_client.create_issue("New bug", "desc")

    assert out["identifier"] == "T-800"
    assert out["state"] == "Backlog"
    variables = captured["kwargs"]["json"]["variables"]
    assert variables["title"] == "New bug"
    assert variables["description"] == "desc"
    assert variables["teamId"] == linear_client.DEFAULT_TECHNICAL_TEAM_ID


def test_create_issue_with_explicit_team_id(monkeypatch):
    captured = {}

    class R:
        status_code = 200

        def json(self):
            return {"data": {"issueCreate": {
                "success": True,
                "issue": {"identifier": "T-801", "title": "t", "url": "u",
                          "state": {"name": "Todo"}, "description": "d"},
            }}}

        def raise_for_status(self):
            pass

    def fake_post(*args, **kwargs):
        captured["kwargs"] = kwargs
        return R()

    monkeypatch.setattr(linear_client.requests, "post", fake_post)
    linear_client.create_issue("t", "d", team_id="other-team-id")
    assert captured["kwargs"]["json"]["variables"]["teamId"] == "other-team-id"


def test_create_issue_raises_on_graphql_error(monkeypatch):
    class R:
        status_code = 200

        def json(self):
            return {"errors": [{"message": "boom"}]}

        def raise_for_status(self):
            pass

    monkeypatch.setattr(linear_client.requests, "post", lambda *a, **k: R())
    try:
        linear_client.create_issue("t", "d")
        assert False, "expected RuntimeError"
    except RuntimeError as e:
        assert "boom" in str(e)


def test_create_issue_raises_when_success_false(monkeypatch):
    class R:
        status_code = 200

        def json(self):
            return {"data": {"issueCreate": {"success": False, "issue": None}}}

        def raise_for_status(self):
            pass

    monkeypatch.setattr(linear_client.requests, "post", lambda *a, **k: R())
    try:
        linear_client.create_issue("t", "d")
        assert False, "expected RuntimeError"
    except RuntimeError:
        pass


# ---------------------------------------------------------------------------
# auth / env
# ---------------------------------------------------------------------------

def test_missing_api_key_raises(monkeypatch):
    monkeypatch.delenv("LINEAR_API_KEY", raising=False)
    try:
        linear_client._linear_headers()
        assert False, "expected RuntimeError"
    except RuntimeError as e:
        assert "LINEAR_API_KEY" in str(e)
