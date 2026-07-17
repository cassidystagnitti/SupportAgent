"""Tests for the Bert morning-review auto_send tagging (bert/fanout.py)."""
import bert.fanout as fanout


def _result(*, ok=True, auto_sendable=True, confidence="high",
            escalate=False, needs_action=False, cid=42):
    """A drafted result dict shaped like bert.fanout.draft_all output."""
    return {
        "ok": ok,
        "conversation_id": cid,
        "confidence": confidence,
        "escalate": escalate,
        "needs_action": needs_action,
        "parsed": {
            "auto_sendable": auto_sendable,
            "confidence": confidence,
            "escalate": escalate,
            "needs_action": needs_action,
        },
    }


# --- should_auto_send: the gate ---

def test_high_confidence_auto_sendable_qualifies():
    assert fanout.should_auto_send(_result(confidence="high")) is True


def test_medium_confidence_auto_sendable_qualifies():
    assert fanout.should_auto_send(_result(confidence="medium")) is True


def test_low_confidence_does_not_qualify():
    assert fanout.should_auto_send(_result(confidence="low")) is False


def test_blank_confidence_does_not_qualify():
    assert fanout.should_auto_send(_result(confidence="")) is False


def test_not_auto_sendable_does_not_qualify():
    assert fanout.should_auto_send(_result(auto_sendable=False)) is False


def test_escalate_does_not_qualify():
    assert fanout.should_auto_send(_result(escalate=True)) is False


def test_needs_action_does_not_qualify():
    assert fanout.should_auto_send(_result(needs_action=True)) is False


def test_failed_result_does_not_qualify():
    assert fanout.should_auto_send(_result(ok=False)) is False


# --- apply_auto_send_tag: the side-effecting apply (fail-soft) ---

def test_apply_tags_qualifying_and_preserves_existing(monkeypatch):
    captured = {}
    monkeypatch.setattr(fanout.orchestrator, "fetch_conversation",
                        lambda session, cid: {"tags": [{"tag": "billing"}]})

    def fake_update(session, cid, existing, to_add):
        captured["existing"] = existing
        captured["to_add"] = to_add

    monkeypatch.setattr(fanout.orchestrator, "_update_conversation_tags", fake_update)

    ret = fanout.apply_auto_send_tag(object(), _result())
    assert ret == "tagged"
    assert "billing" in captured["existing"]
    assert captured["to_add"] == ["auto_send"]


def test_apply_idempotent_when_tag_present(monkeypatch):
    calls = {"n": 0}
    monkeypatch.setattr(fanout.orchestrator, "fetch_conversation",
                        lambda session, cid: {"tags": [{"tag": "auto_send"}]})
    monkeypatch.setattr(fanout.orchestrator, "_update_conversation_tags",
                        lambda *a, **k: calls.__setitem__("n", calls["n"] + 1))

    ret = fanout.apply_auto_send_tag(object(), _result())
    assert ret == "already"
    assert calls["n"] == 0


def test_apply_returns_none_when_not_qualifying(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("must not fetch when result does not qualify")

    monkeypatch.setattr(fanout.orchestrator, "fetch_conversation", boom)
    assert fanout.apply_auto_send_tag(object(), _result(confidence="low")) is None


def test_apply_fails_soft_on_api_error(monkeypatch):
    def boom(session, cid):
        raise RuntimeError("help scout down")

    monkeypatch.setattr(fanout.orchestrator, "fetch_conversation", boom)
    assert fanout.apply_auto_send_tag(object(), _result()) is None
