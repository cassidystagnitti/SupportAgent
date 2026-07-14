from unittest.mock import MagicMock, patch

import base64

import pytest
import requests

import policy_updater
from policy_updater import ProposalError


@pytest.fixture()
def policies_dir(tmp_path, monkeypatch):
    d = tmp_path / "policies"
    d.mkdir()
    (d / "refunds.md").write_text(
        "# Refunds\n\n# Summary\nWe refund within 30 days.\n", encoding="utf-8"
    )
    monkeypatch.setattr(policy_updater, "POLICIES_DIR", str(d))
    return d


def test_build_proposal_replace_produces_diff(policies_dir):
    p = policy_updater.build_proposal(
        policy_file="refunds.md",
        edit_type="replace",
        target_text="We refund within 30 days.",
        new_text="We refund within 45 days.",
        rationale="Policy changed 2026-07-14",
    )
    assert p["status"] == "pending"
    assert p["policy_file"] == "refunds.md"
    assert "-We refund within 30 days." in p["diff"]
    assert "+We refund within 45 days." in p["diff"]
    assert len(p["id"]) == 12


def test_build_proposal_append(policies_dir):
    p = policy_updater.build_proposal(
        policy_file="refunds.md",
        edit_type="append",
        target_text="",
        new_text="# New Section\nStuff.",
        rationale="r",
    )
    assert "+# New Section" in p["diff"]


def test_replace_requires_unique_target(policies_dir):
    (policies_dir / "refunds.md").write_text("dup\ndup\n", encoding="utf-8")
    with pytest.raises(ProposalError, match="2 times"):
        policy_updater.build_proposal(
            policy_file="refunds.md", edit_type="replace",
            target_text="dup", new_text="x", rationale="r",
        )


def test_replace_missing_target_rejected(policies_dir):
    with pytest.raises(ProposalError, match="not found"):
        policy_updater.build_proposal(
            policy_file="refunds.md", edit_type="replace",
            target_text="no such text", new_text="x", rationale="r",
        )


def test_unknown_file_and_traversal_rejected(policies_dir):
    with pytest.raises(ProposalError):
        policy_updater.build_proposal(
            policy_file="nope.md", edit_type="append",
            target_text="", new_text="x", rationale="r",
        )
    with pytest.raises(ProposalError):
        policy_updater.build_proposal(
            policy_file="../CLAUDE.md", edit_type="append",
            target_text="", new_text="x", rationale="r",
        )


def test_unknown_edit_type_rejected(policies_dir):
    with pytest.raises(ProposalError, match="edit_type"):
        policy_updater.build_proposal(
            policy_file="refunds.md", edit_type="delete",
            target_text="", new_text="x", rationale="r",
        )


def test_apply_edit_append_normalizes_trailing_newline():
    out = policy_updater._apply_edit("body\n", "append", "", "tail")
    assert out.endswith("tail\n")
    assert "\n\ntail" in out


# --- Task 2: confirm flow (live apply, GitHub commit, rollback, Notion) ---


def _resp(status, payload=None):
    r = MagicMock()
    r.status_code = status
    r.json.return_value = payload or {}
    if status >= 400:
        r.raise_for_status.side_effect = requests.HTTPError(f"HTTP {status}")
    else:
        r.raise_for_status.return_value = None
    return r


@pytest.fixture()
def github_env(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "tok")
    monkeypatch.setenv("GITHUB_REPO", "owner/repo")
    monkeypatch.setenv("GITHUB_BRANCH", "main")


def test_commit_policy_file_happy_path(github_env):
    with patch("policy_updater.requests.get") as g, patch("policy_updater.requests.put") as p:
        g.return_value = _resp(200, {"sha": "oldsha"})
        p.return_value = _resp(200, {"commit": {"sha": "newsha"}})
        sha = policy_updater.commit_policy_file("refunds.md", "content", "msg\n\n[skip render]")
    assert sha == "newsha"
    url = p.call_args[0][0]
    assert url.endswith("/repos/owner/repo/contents/policies/refunds.md")
    body = p.call_args[1]["json"]
    assert body["sha"] == "oldsha"
    assert body["branch"] == "main"
    assert base64.b64decode(body["content"]).decode() == "content"


def test_commit_policy_file_retries_on_conflict(github_env):
    with patch("policy_updater.requests.get") as g, patch("policy_updater.requests.put") as p:
        g.side_effect = [_resp(200, {"sha": "s1"}), _resp(200, {"sha": "s2"})]
        p.side_effect = [_resp(409), _resp(200, {"commit": {"sha": "done"}})]
        sha = policy_updater.commit_policy_file("refunds.md", "c", "m")
    assert sha == "done"
    assert p.call_count == 2


def test_commit_policy_file_rejects_non_policy_path(github_env):
    with pytest.raises(ValueError):
        policy_updater.commit_policy_file("evil.py", "c", "m")


def test_commit_requires_token(monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    with pytest.raises(RuntimeError, match="GITHUB_TOKEN"):
        policy_updater.commit_policy_file("refunds.md", "c", "m")


def test_confirm_proposal_applies_and_commits(policies_dir, github_env):
    p = policy_updater.build_proposal(
        policy_file="refunds.md", edit_type="replace",
        target_text="We refund within 30 days.", new_text="We refund within 45 days.",
        rationale="changed",
    )
    with patch("policy_updater.commit_policy_file", return_value="abc1234def") as c, \
         patch("policy_updater.sync_policy_to_notion") as n:
        out = policy_updater.confirm_proposal(p, conversation_id="123")
    assert out["commit_sha"] == "abc1234def"
    assert out["notion_warning"] is None
    assert p["status"] == "confirmed"
    live = (policies_dir / "refunds.md").read_text(encoding="utf-8")
    assert "45 days" in live
    msg = c.call_args[0][2]
    assert "[skip render]" in msg
    assert "conversation/123" in msg
    n.assert_called_once()


def test_confirm_rolls_back_live_file_when_commit_fails(policies_dir, github_env):
    p = policy_updater.build_proposal(
        policy_file="refunds.md", edit_type="replace",
        target_text="We refund within 30 days.", new_text="XX",
        rationale="r",
    )
    with patch("policy_updater.commit_policy_file", side_effect=RuntimeError("gh down")):
        with pytest.raises(RuntimeError, match="gh down"):
            policy_updater.confirm_proposal(p, conversation_id="1")
    live = (policies_dir / "refunds.md").read_text(encoding="utf-8")
    assert "30 days" in live          # rolled back
    assert p["status"] == "pending"   # still confirmable


def test_confirm_notion_failure_is_warn_only(policies_dir, github_env):
    p = policy_updater.build_proposal(
        policy_file="refunds.md", edit_type="append",
        target_text="", new_text="tail", rationale="r",
    )
    with patch("policy_updater.commit_policy_file", return_value="sha"), \
         patch("policy_updater.sync_policy_to_notion", side_effect=RuntimeError("no token")):
        out = policy_updater.confirm_proposal(p, conversation_id="1")
    assert p["status"] == "confirmed"
    assert "Notion sync failed" in out["notion_warning"]


def test_confirm_fails_loudly_on_drift(policies_dir, github_env):
    p = policy_updater.build_proposal(
        policy_file="refunds.md", edit_type="replace",
        target_text="We refund within 30 days.", new_text="XX", rationale="r",
    )
    (policies_dir / "refunds.md").write_text("# Refunds\nsomething else\n", encoding="utf-8")
    with pytest.raises(ProposalError, match="not found"):
        policy_updater.confirm_proposal(p, conversation_id="1")
    assert p["status"] == "pending"
