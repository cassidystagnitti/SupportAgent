"""Tests for the auto-send verifier (bert/verify.py)."""
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
