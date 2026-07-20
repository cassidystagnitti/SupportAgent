"""Tests for the auto-send verifier (bert/verify.py)."""
from types import SimpleNamespace

import pytest

import bert.verify as verify


# --- prelint: deterministic must-not-send checks (no model call) ---

def test_prelint_clean_draft_returns_no_findings():
    assert verify.prelint("<p>Hi there! Thanks for meditating with us.</p>") == []


def test_prelint_flags_spelled_out_brand_name():
    findings = verify.prelint("<p>Dan Harris wrote Ten Percent Happier.</p>")
    assert any(f["class"] == "E" for f in findings)


def test_prelint_brand_check_is_case_insensitive():
    findings = verify.prelint("<p>the ten percent happier podcast</p>")
    assert any(f["class"] == "E" for f in findings)


def test_prelint_ok_with_10_percent_happier_numerals():
    assert verify.prelint("<p>Dan Harris's 10% Happier podcast.</p>") == []


def test_prelint_flags_leftover_placeholder():
    findings = verify.prelint("<p>Hi {%customer.firstName%}, welcome back.</p>")
    assert any(f["class"] == "H" and "placeholder" in f["detail"].lower() for f in findings)


def test_prelint_flags_bare_curly_placeholder():
    findings = verify.prelint("<p>Sign in with {EMAIL}.</p>")
    assert any(f["class"] == "H" and "placeholder" in f["detail"].lower() for f in findings)


def test_prelint_flags_mojibake():
    findings = verify.prelint("<p>Weâ€™re happy to help â€” truly.</p>")
    assert any(f["class"] == "H" and "mojibake" in f["detail"].lower() for f in findings)


def test_prelint_flags_bare_website_signin_link():
    findings = verify.prelint('<a href="https://my.meditatehappier.com/start/sign_in">sign in here</a>')
    assert any(f["class"] == "B" for f in findings)


def test_prelint_allows_coupon_checkout_link():
    html = '<a href="https://my.meditatehappier.com/start/sign_in?coupon=WINBACK40">40% off</a>'
    assert verify.prelint(html) == []


def test_prelint_empty_draft_is_clean():
    assert verify.prelint("") == []


def test_prelint_findings_have_full_shape():
    for f in verify.prelint("<p>Ten Percent Happier {X} â€”</p>"):
        assert set(f) == {"class", "detail", "fix_type", "suggested_fix"}


# --- find_sibling_conversations: the mechanical same-customer check ---

def test_siblings_excludes_own_conversation(monkeypatch):
    monkeypatch.setattr(verify.triage_tickets, "api_get", lambda s, url, params=None: {
        "_embedded": {"conversations": [{"id": 5}, {"id": 9}]}})
    assert verify.find_sibling_conversations(object(), "a@b.com", exclude_cid=5) == [9]


def test_siblings_empty_when_only_own_ticket(monkeypatch):
    monkeypatch.setattr(verify.triage_tickets, "api_get", lambda s, url, params=None: {
        "_embedded": {"conversations": [{"id": 5}]}})
    assert verify.find_sibling_conversations(object(), "a@b.com", exclude_cid=5) == []


def test_siblings_empty_email_short_circuits(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("must not hit the API without an email")
    monkeypatch.setattr(verify.triage_tickets, "api_get", boom)
    assert verify.find_sibling_conversations(object(), "", exclude_cid=5) == []
    assert verify.find_sibling_conversations(object(), None, exclude_cid=5) == []


def test_siblings_queries_active_by_email(monkeypatch):
    seen = {}

    def fake_get(session, url, params=None):
        seen["url"] = url
        seen["params"] = params
        return {"_embedded": {"conversations": []}}

    monkeypatch.setattr(verify.triage_tickets, "api_get", fake_get)
    verify.find_sibling_conversations(object(), "a@b.com", exclude_cid=5)
    assert seen["url"].endswith("/conversations")
    assert seen["params"]["status"] == "active"
    assert 'a@b.com' in seen["params"]["query"]


def test_siblings_api_error_propagates(monkeypatch):
    # The caller (fanout) decides fail-soft; the helper itself must not swallow.
    def boom(*a, **k):
        raise RuntimeError("HS down")
    monkeypatch.setattr(verify.triage_tickets, "api_get", boom)
    try:
        verify.find_sibling_conversations(object(), "a@b.com", exclude_cid=5)
        assert False, "expected RuntimeError"
    except RuntimeError:
        pass


# --- verify_draft: the one-Claude-call adversarial review ---

class _FakeMessage:
    def __init__(self, text):
        self.content = [SimpleNamespace(type="text", text=text)]


class _FakeClient:
    """Anthropic stand-in: returns queued response texts, records each request."""

    def __init__(self, *texts):
        self.calls = []
        self._texts = list(texts)
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        return _FakeMessage(self._texts.pop(0))


def _ctx(**over):
    base = {"conversation_id": 5, "subject": "Can't log in", "customer_name": "Pat",
            "email": "pat@x.com", "body": "help me sign in", "conversation_history": "",
            "reply_mode": False, "account_blob": "Subscribed: yes", "stripe_block": "N/A",
            "existing_tags": []}
    base.update(over)
    return base


def _result(**over):
    base = {"conversation_id": 5, "draft_reply": "<p>Hi Pat!</p>", "confidence": "high",
            "referenced_policies": ["login-issues"], "reasoning": "standard login",
            "parsed": {"auto_sendable": True}}
    base.update(over)
    return base


def test_verify_draft_parses_verdict_and_findings():
    client = _FakeClient('{"verdict": "send_as_is", "findings": []}')
    out = verify.verify_draft(client, _result(), _ctx(), "- brief note", "POLICY CORPUS")
    assert out == {"verdict": "SEND_AS_IS", "findings": []}


def test_verify_draft_normalizes_finding_shape():
    client = _FakeClient('{"verdict": "ERROR", "findings": [{"class": "A", "detail": "wrong email"}]}')
    out = verify.verify_draft(client, _result(), _ctx(), "", "P")
    assert out["verdict"] == "ERROR"
    assert out["findings"] == [{"class": "A", "detail": "wrong email",
                                "fix_type": "", "suggested_fix": ""}]


def test_verify_draft_request_contains_policies_draft_and_brief():
    client = _FakeClient('{"verdict": "MINOR", "findings": []}')
    verify.verify_draft(client, _result(), _ctx(), "- streak bug is fixed", "THE POLICY CORPUS")
    call = client.calls[0]
    blob = " ".join(b["text"] for b in call["messages"][0]["content"])
    assert "THE POLICY CORPUS" in blob
    assert "<p>Hi Pat!</p>" in blob
    assert "- streak bug is fixed" in blob
    assert call["system"][0]["cache_control"] == {"type": "ephemeral"}


def test_verify_draft_uses_default_model_env(monkeypatch):
    client = _FakeClient('{"verdict": "MINOR", "findings": []}')
    verify.verify_draft(client, _result(), _ctx(), "", "P")
    assert client.calls[0]["model"] == verify.DEFAULT_VERIFY_MODEL
    client2 = _FakeClient('{"verdict": "MINOR", "findings": []}')
    verify.verify_draft(client2, _result(), _ctx(), "", "P", model="claude-opus-4-8")
    assert client2.calls[0]["model"] == "claude-opus-4-8"


def test_verify_draft_invalid_verdict_raises():
    client = _FakeClient('{"verdict": "MAYBE", "findings": []}')
    with pytest.raises(ValueError):
        verify.verify_draft(client, _result(), _ctx(), "", "P")


def test_verify_draft_retries_once_on_bad_json_then_succeeds():
    client = _FakeClient("not json at all", '{"verdict": "SEND_AS_IS", "findings": []}')
    out = verify.verify_draft(client, _result(), _ctx(), "", "P")
    assert out["verdict"] == "SEND_AS_IS"
    assert len(client.calls) == 2


def test_verify_draft_raises_after_two_bad_json_responses():
    client = _FakeClient("junk", "more junk")
    with pytest.raises(ValueError):
        verify.verify_draft(client, _result(), _ctx(), "", "P")
    assert len(client.calls) == 2
