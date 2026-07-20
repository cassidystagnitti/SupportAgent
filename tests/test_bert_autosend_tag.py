"""Tests for the Bert auto_send flow: the gate (should_auto_send), the verifier
stage (verify_and_tag), and the verdict-driven tag reconcile (bert/fanout.py)."""
import bert.fanout as fanout


def _result(*, ok=True, auto_sendable=True, confidence="high",
            escalate=False, needs_action=False, cid=42, draft="<p>Hi!</p>"):
    """A drafted result dict shaped like bert.fanout.draft_all output."""
    return {
        "ok": ok,
        "conversation_id": cid,
        "hs_customer_id": 9,
        "confidence": confidence,
        "escalate": escalate,
        "needs_action": needs_action,
        "draft_reply": draft,
        "referenced_policies": ["login-issues"],
        "reasoning": "standard",
        "parsed": {
            "auto_sendable": auto_sendable,
            "confidence": confidence,
            "escalate": escalate,
            "needs_action": needs_action,
        },
    }


class _FakeResp:
    def raise_for_status(self):
        pass


class _FakeSession:
    def __init__(self):
        self.puts = []

    def put(self, url, json=None):
        self.puts.append((url, json))
        return _FakeResp()


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


# --- reconcile_auto_send_tag: tag follows the verifier verdict (fail-soft) ---

def test_reconcile_tags_on_clean_verdict_and_preserves_existing(monkeypatch):
    captured = {}
    monkeypatch.setattr(fanout.orchestrator, "fetch_conversation",
                        lambda session, cid: {"tags": [{"tag": "billing"}]})

    def fake_update(session, cid, existing, to_add):
        captured["existing"] = existing
        captured["to_add"] = to_add

    monkeypatch.setattr(fanout.orchestrator, "_update_conversation_tags", fake_update)

    ret = fanout.reconcile_auto_send_tag(object(), 42, "SEND_AS_IS")
    assert ret == "tagged"
    assert "billing" in captured["existing"]
    assert captured["to_add"] == ["auto_send"]


def test_reconcile_idempotent_when_tag_present(monkeypatch):
    calls = {"n": 0}
    monkeypatch.setattr(fanout.orchestrator, "fetch_conversation",
                        lambda session, cid: {"tags": [{"tag": "auto_send"}]})
    monkeypatch.setattr(fanout.orchestrator, "_update_conversation_tags",
                        lambda *a, **k: calls.__setitem__("n", calls["n"] + 1))

    ret = fanout.reconcile_auto_send_tag(object(), 42, "SEND_AS_IS")
    assert ret == "already"
    assert calls["n"] == 0


def test_reconcile_removes_tag_on_downgrade(monkeypatch):
    monkeypatch.setattr(fanout.orchestrator, "fetch_conversation",
                        lambda session, cid: {"tags": [{"tag": "billing"}, {"tag": "auto_send"}]})
    session = _FakeSession()
    ret = fanout.reconcile_auto_send_tag(session, 42, "MINOR")
    assert ret == "removed"
    url, body = session.puts[0]
    assert url.endswith("/conversations/42/tags")
    assert body == {"tags": ["billing"]}


def test_reconcile_removes_tag_on_error_verdict(monkeypatch):
    monkeypatch.setattr(fanout.orchestrator, "fetch_conversation",
                        lambda session, cid: {"tags": [{"tag": "auto_send"}]})
    session = _FakeSession()
    assert fanout.reconcile_auto_send_tag(session, 42, "ERROR") == "removed"
    assert session.puts[0][1] == {"tags": []}


def test_reconcile_noop_when_downgraded_and_tag_absent(monkeypatch):
    monkeypatch.setattr(fanout.orchestrator, "fetch_conversation",
                        lambda session, cid: {"tags": [{"tag": "billing"}]})
    session = _FakeSession()
    assert fanout.reconcile_auto_send_tag(session, 42, "ERROR") is None
    assert session.puts == []


def test_reconcile_fails_soft_on_api_error(monkeypatch):
    def boom(session, cid):
        raise RuntimeError("help scout down")

    monkeypatch.setattr(fanout.orchestrator, "fetch_conversation", boom)
    assert fanout.reconcile_auto_send_tag(object(), 42, "SEND_AS_IS") is None


# --- verify_and_tag: the verifier stage (never raises) ---

def _quiet_reconcile(monkeypatch):
    seen = {}

    def fake(session, cid, verdict):
        seen["cid"] = cid
        seen["verdict"] = verdict
        return "tagged" if verdict == "SEND_AS_IS" else "removed"

    monkeypatch.setattr(fanout, "reconcile_auto_send_tag", fake)
    return seen


def test_verify_and_tag_prelint_hit_is_error_without_model_or_hydration(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("prelint hit must short-circuit before hydration/model")

    monkeypatch.setattr(fanout.pipeline, "hydrate_ticket", boom)
    monkeypatch.setattr(fanout.verify, "verify_draft", boom)
    seen = _quiet_reconcile(monkeypatch)

    out = fanout.verify_and_tag(object(), object(),
                                _result(draft="<p>Ten Percent Happier</p>"))
    assert out["verdict"] == "ERROR"
    assert any(f["class"] == "E" for f in out["findings"])
    assert out["tag"] == "removed"
    assert seen["verdict"] == "ERROR"


def test_verify_and_tag_sibling_tickets_are_automatic_error(monkeypatch):
    monkeypatch.setattr(fanout.pipeline, "hydrate_ticket",
                        lambda s, cid: {"conversation_id": cid, "email": "a@b.com"})
    monkeypatch.setattr(fanout.verify, "find_sibling_conversations",
                        lambda s, email, exclude_cid: [99, 100])

    def boom(*a, **k):
        raise AssertionError("siblings must short-circuit the model call")

    monkeypatch.setattr(fanout.verify, "verify_draft", boom)
    _quiet_reconcile(monkeypatch)

    out = fanout.verify_and_tag(object(), object(), _result())
    assert out["verdict"] == "ERROR"
    f = out["findings"][0]
    assert f["class"] == "I" and f["fix_type"] == "consolidate"
    assert "99" in f["detail"]


def test_verify_and_tag_sibling_check_failure_falls_through_to_model(monkeypatch):
    monkeypatch.setattr(fanout.pipeline, "hydrate_ticket",
                        lambda s, cid: {"conversation_id": cid, "email": "a@b.com"})

    def sibling_boom(*a, **k):
        raise RuntimeError("HS query down")

    monkeypatch.setattr(fanout.verify, "find_sibling_conversations", sibling_boom)
    monkeypatch.setattr(fanout.orchestrator, "load_policy_docs", lambda: "P")
    monkeypatch.setattr(fanout.verify, "verify_draft",
                        lambda *a, **k: {"verdict": "SEND_AS_IS", "findings": []})
    _quiet_reconcile(monkeypatch)

    out = fanout.verify_and_tag(object(), object(), _result())
    assert out["verdict"] == "SEND_AS_IS" and out["error"] is None


def test_verify_and_tag_clean_verdict_tags(monkeypatch):
    monkeypatch.setattr(fanout.pipeline, "hydrate_ticket",
                        lambda s, cid: {"conversation_id": cid, "email": "a@b.com"})
    monkeypatch.setattr(fanout.verify, "find_sibling_conversations", lambda *a, **k: [])
    monkeypatch.setattr(fanout.orchestrator, "load_policy_docs", lambda: "P")
    captured = {}

    def fake_verify(client, result, ctx, brief, policies, *, model=None):
        captured["brief"] = brief
        captured["policies"] = policies
        captured["model"] = model
        return {"verdict": "SEND_AS_IS", "findings": []}

    monkeypatch.setattr(fanout.verify, "verify_draft", fake_verify)
    seen = _quiet_reconcile(monkeypatch)

    out = fanout.verify_and_tag(object(), object(), _result(),
                                brief="- brief", model="claude-opus-4-8")
    assert out == {"verdict": "SEND_AS_IS", "findings": [], "tag": "tagged", "error": None}
    assert captured == {"brief": "- brief", "policies": "P", "model": "claude-opus-4-8"}
    assert seen["verdict"] == "SEND_AS_IS"


def test_verify_and_tag_minor_verdict_removes_tag(monkeypatch):
    monkeypatch.setattr(fanout.pipeline, "hydrate_ticket",
                        lambda s, cid: {"conversation_id": cid, "email": "a@b.com"})
    monkeypatch.setattr(fanout.verify, "find_sibling_conversations", lambda *a, **k: [])
    monkeypatch.setattr(fanout.orchestrator, "load_policy_docs", lambda: "P")
    monkeypatch.setattr(fanout.verify, "verify_draft", lambda *a, **k: {
        "verdict": "MINOR",
        "findings": [{"class": "G", "detail": "stiff tone", "fix_type": "rewrite", "suggested_fix": "loosen up"}],
    })
    seen = _quiet_reconcile(monkeypatch)

    out = fanout.verify_and_tag(object(), object(), _result())
    assert out["verdict"] == "MINOR" and out["tag"] == "removed"
    assert seen["verdict"] == "MINOR"


def test_verify_and_tag_fails_soft_when_verifier_errors(monkeypatch):
    monkeypatch.setattr(fanout.pipeline, "hydrate_ticket",
                        lambda s, cid: {"conversation_id": cid, "email": "a@b.com"})
    monkeypatch.setattr(fanout.verify, "find_sibling_conversations", lambda *a, **k: [])
    monkeypatch.setattr(fanout.orchestrator, "load_policy_docs", lambda: "P")

    def boom(*a, **k):
        raise RuntimeError("anthropic down")

    monkeypatch.setattr(fanout.verify, "verify_draft", boom)
    seen = _quiet_reconcile(monkeypatch)

    out = fanout.verify_and_tag(object(), object(), _result())
    assert out["verdict"] is None
    assert "anthropic down" in out["error"]
    # an unverified candidate must not carry the tag → reconcile ran with no verdict
    assert seen["verdict"] is None and out["tag"] == "removed"


# --- apply_result integration: verifier drives the tag ---

def _posted_new(monkeypatch):
    monkeypatch.setattr(fanout.pipeline, "find_draft_threads", lambda s, cid: [])
    monkeypatch.setattr(fanout.pipeline, "conversation_status", lambda s, cid: "active")
    monkeypatch.setattr(fanout.pipeline, "post_draft", lambda *a, **k: "rid")
    monkeypatch.setattr(fanout.pipeline, "should_post_note", lambda parsed: False)


def test_apply_result_records_verifier_verdict_and_tag(monkeypatch):
    _posted_new(monkeypatch)
    captured = {}

    def fake_verify_and_tag(session, client, result, *, brief="", model=None):
        captured["brief"] = brief
        captured["model"] = model
        return {"verdict": "SEND_AS_IS", "findings": [], "tag": "tagged", "error": None}

    monkeypatch.setattr(fanout, "verify_and_tag", fake_verify_and_tag)
    status = fanout.apply_result(object(), _result(), timestamp="t",
                                 verify_client=object(), brief="- b", verify_model="m2")
    assert status["draft_action"] == "posted_new"
    assert status["verify_verdict"] == "SEND_AS_IS"
    assert status["verify_findings"] == []
    assert status["auto_send_tagged"] == "tagged"
    assert captured == {"brief": "- b", "model": "m2"}


def test_apply_result_downgrade_removes_tag(monkeypatch):
    _posted_new(monkeypatch)
    findings = [{"class": "A", "detail": "wrong email", "fix_type": "rewrite", "suggested_fix": "fix it"}]
    monkeypatch.setattr(fanout, "verify_and_tag", lambda *a, **k: {
        "verdict": "ERROR", "findings": findings, "tag": "removed", "error": None})
    status = fanout.apply_result(object(), _result(), timestamp="t", verify_client=object())
    assert status["verify_verdict"] == "ERROR"
    assert status["verify_findings"] == findings
    assert status["auto_send_tagged"] == "removed"


def test_apply_result_without_verifier_client_never_tags(monkeypatch):
    _posted_new(monkeypatch)

    def boom(*a, **k):
        raise AssertionError("verify_and_tag needs a client")

    monkeypatch.setattr(fanout, "verify_and_tag", boom)
    seen = _quiet_reconcile(monkeypatch)
    status = fanout.apply_result(object(), _result(), timestamp="t")
    assert status["verify_verdict"] is None
    # unverified candidate: no tag applied, stale tag stripped
    assert seen["verdict"] is None
    assert status["auto_send_tagged"] == "removed"


def test_apply_result_non_candidate_skips_verifier(monkeypatch):
    _posted_new(monkeypatch)

    def boom(*a, **k):
        raise AssertionError("non-candidates must not reach the verifier")

    monkeypatch.setattr(fanout, "verify_and_tag", boom)
    monkeypatch.setattr(fanout, "reconcile_auto_send_tag", boom)
    status = fanout.apply_result(object(), _result(needs_action=True), timestamp="t",
                                 verify_client=object())
    assert status["auto_send_tagged"] is None
    assert status["verify_verdict"] is None


def test_apply_result_skipped_draft_skips_verifier(monkeypatch):
    monkeypatch.setattr(fanout.pipeline, "find_draft_threads", lambda s, cid: [])
    monkeypatch.setattr(fanout.pipeline, "conversation_status", lambda s, cid: "closed")
    monkeypatch.setattr(fanout.pipeline, "should_post_note", lambda parsed: False)

    def boom(*a, **k):
        raise AssertionError("skipped drafts must not reach the verifier")

    monkeypatch.setattr(fanout, "verify_and_tag", boom)
    status = fanout.apply_result(object(), _result(), timestamp="t", verify_client=object())
    assert status["draft_action"] == "skipped_closed"
    assert status["auto_send_tagged"] is None
