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


def test_prelint_allows_plan_checkout_link():
    # policies/account-lookup-data-model.md prescribes plan-only checkout links
    # (e.g. standard monthly) with no coupon param — those are legitimate too.
    html = ('<a href="https://my.meditatehappier.com/start/sign_in'
            '?plan=com.10percenthappier.subscription_1month_1499.intro_none">monthly</a>')
    assert verify.prelint(html) == []


def test_prelint_flags_dead_help_center_domain():
    html = ('<a href="https://support.happierapp.com/article/314-check-for-a-hidden'
            '-sign-in-with-apple-address">article</a>')
    findings = verify.prelint(html)
    assert any(f["class"] == "B" and "support.meditatehappier.com" in f["suggested_fix"]
               for f in findings)


def test_prelint_allows_live_help_center_domain():
    html = ('<a href="https://support.meditatehappier.com/article/314-check-for-a-hidden'
            '-sign-in-with-apple-address">article</a>')
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


def test_siblings_queries_open_by_email(monkeypatch):
    # "open" = active + pending; a duplicate parked as pending is still a sibling.
    seen = {}

    def fake_get(session, url, params=None):
        seen["url"] = url
        seen["params"] = params
        return {"_embedded": {"conversations": []}}

    monkeypatch.setattr(verify.triage_tickets, "api_get", fake_get)
    verify.find_sibling_conversations(object(), "a@b.com", exclude_cid=5)
    assert seen["url"].endswith("/conversations")
    assert seen["params"]["status"] == "open"
    assert 'a@b.com' in seen["params"]["query"]


def test_siblings_strips_embedded_quotes_from_email(monkeypatch):
    # A quoted local part must not corrupt the (email:"...") query syntax.
    seen = {}

    def fake_get(session, url, params=None):
        seen["params"] = params
        return {"_embedded": {"conversations": []}}

    monkeypatch.setattr(verify.triage_tickets, "api_get", fake_get)
    verify.find_sibling_conversations(object(), 'o"brien@x.com', exclude_cid=5)
    assert seen["params"]["query"].count('"') == 2


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


def test_verify_draft_send_as_is_with_findings_downgrades_to_minor():
    # A self-contradictory model response must never earn the tag.
    client = _FakeClient('{"verdict": "SEND_AS_IS", "findings": [{"class": "A", "detail": "wrong date"}]}')
    out = verify.verify_draft(client, _result(), _ctx(), "", "P")
    assert out["verdict"] == "MINOR"
    assert out["findings"][0]["class"] == "A"


def test_verify_draft_non_dict_json_retries():
    client = _FakeClient('["valid json, wrong shape"]', '{"verdict": "SEND_AS_IS", "findings": []}')
    out = verify.verify_draft(client, _result(), _ctx(), "", "P")
    assert out["verdict"] == "SEND_AS_IS"
    assert len(client.calls) == 2


def test_verify_draft_retries_once_on_transient_api_error(monkeypatch):
    import anthropic

    class _Transient(anthropic.AnthropicError):
        pass

    monkeypatch.setattr(verify.orchestrator, "_should_retry_claude", lambda e: True)
    calls = {"n": 0}

    class _FlakyClient:
        def __init__(self):
            self.messages = SimpleNamespace(create=self._create)

        def _create(self, **kwargs):
            calls["n"] += 1
            if calls["n"] == 1:
                raise _Transient("overloaded")
            return _FakeMessage('{"verdict": "SEND_AS_IS", "findings": []}')

    out = verify.verify_draft(_FlakyClient(), _result(), _ctx(), "", "P")
    assert out["verdict"] == "SEND_AS_IS"
    assert calls["n"] == 2


def test_verify_draft_context_includes_today(monkeypatch):
    # Date claims (class A/D) are only checkable if the verifier knows today.
    client = _FakeClient('{"verdict": "SEND_AS_IS", "findings": []}')
    verify.verify_draft(client, _result(), _ctx(), "", "P")
    blob = " ".join(b["text"] for b in client.calls[0]["messages"][0]["content"])
    assert "Today's date:" in blob


# --- repairable: which findings the repair loop may fix autonomously ---

def _f(cls="G", fix_type="rewrite"):
    return {"class": cls, "detail": "d", "fix_type": fix_type, "suggested_fix": "s"}


def test_repairable_all_rewrite_findings():
    assert verify.repairable([_f(), _f("H")]) is True


def test_repairable_false_when_any_finding_needs_more_than_a_rewrite():
    assert verify.repairable([_f(), _f("I", "consolidate")]) is False
    assert verify.repairable([_f("A", "none")]) is False
    assert verify.repairable([_f("C", "suppress")]) is False


def test_repairable_false_when_no_findings():
    assert verify.repairable([]) is False


# --- repair_draft: apply the findings' fixes, return the revised draft ---

def test_repair_draft_returns_revised_text():
    client = _FakeClient('{"draft_reply": "<p>Fixed!</p>"}')
    out = verify.repair_draft(client, _result(), _ctx(), "- brief", "POLICIES",
                              [_f("E")])
    assert out == "<p>Fixed!</p>"


def test_repair_draft_request_contains_findings_draft_and_policies():
    client = _FakeClient('{"draft_reply": "<p>Fixed!</p>"}')
    finding = {"class": "E", "detail": "spelled-out brand", "fix_type": "rewrite",
               "suggested_fix": 'Use "10% Happier".'}
    verify.repair_draft(client, _result(), _ctx(), "", "THE POLICY CORPUS", [finding])
    blob = " ".join(b["text"] for b in client.calls[0]["messages"][0]["content"])
    assert "THE POLICY CORPUS" in blob
    assert "<p>Hi Pat!</p>" in blob
    assert "spelled-out brand" in blob and '10% Happier' in blob


def test_repair_draft_empty_revision_raises():
    client = _FakeClient('{"draft_reply": ""}')
    with pytest.raises(ValueError):
        verify.repair_draft(client, _result(), _ctx(), "", "P", [_f()])


def test_repair_draft_retries_once_on_bad_json():
    client = _FakeClient("junk", '{"draft_reply": "<p>ok</p>"}')
    assert verify.repair_draft(client, _result(), _ctx(), "", "P", [_f()]) == "<p>ok</p>"
    assert len(client.calls) == 2
