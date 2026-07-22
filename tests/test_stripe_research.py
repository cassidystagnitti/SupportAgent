"""Tests for stripe_research — the read-only Stripe charge hunt
(policies/no-account-found-troubleshooting.md, Step 3) and the pre-send
truth check on claimed Stripe objects.

Added 2026-07-20 after a manual read-only hunt (charges by card last4,
Customer.search by email and name~) conclusively resolved HS #3384480359:
the claimed charge wasn't in our Stripe at all, invalidating a pending
draft that had confirmed a cancellation.
"""

from types import SimpleNamespace

import stripe

import stripe_research


def _key(monkeypatch):
    monkeypatch.setenv("STRIPE_READ_API_KEY", "rk_test_x")


def _charge(**overrides):
    base = {
        "id": "ch_1",
        "amount": 9999,
        "currency": "usd",
        "created": 1749945600,  # 2025-06-15 UTC
        "status": "succeeded",
        "paid": True,
        "refunded": False,
        "customer": "cus_9",
        "description": "Subscription renewal",
        "billing_details": {"email": "jane@doe.com", "name": "Jane Doe"},
        "payment_method_details": {"card": {"last4": "4242"}},
    }
    base.update(overrides)
    return base


class _SearchResult(dict):
    """Duck-types a Stripe SearchResult: iterable .data + has_more."""

    def __init__(self, data, has_more=False):
        super().__init__(data=data, has_more=has_more)
        self.data = data
        self.has_more = has_more


# ---------------------------------------------------------------------------
# search_charges_by_last4
# ---------------------------------------------------------------------------

def test_search_charges_by_last4_builds_query_and_normalizes(monkeypatch):
    _key(monkeypatch)
    captured = {}

    def fake_search(**kwargs):
        captured.update(kwargs)
        return _SearchResult([_charge()])

    monkeypatch.setattr(stripe_research.stripe.Charge, "search", fake_search)
    out = stripe_research.search_charges_by_last4("4242")
    assert out["ok"] is True
    assert "payment_method_details.card.last4:'4242'" in captured["query"]
    ch = out["charges"][0]
    assert ch["id"] == "ch_1"
    assert ch["amount"] == 9999
    assert ch["card_last4"] == "4242"
    assert ch["billing_email"] == "jane@doe.com"
    assert ch["customer_id"] == "cus_9"


def test_search_charges_by_last4_rejects_non_4_digits(monkeypatch):
    _key(monkeypatch)

    def boom(**kwargs):
        raise AssertionError("must not call Stripe for invalid last4")

    monkeypatch.setattr(stripe_research.stripe.Charge, "search", boom)
    assert stripe_research.search_charges_by_last4("12a4")["ok"] is False
    assert stripe_research.search_charges_by_last4("12345")["ok"] is False
    assert stripe_research.search_charges_by_last4("")["ok"] is False


def test_search_charges_fail_soft_on_stripe_error(monkeypatch):
    _key(monkeypatch)

    def boom(**kwargs):
        raise stripe.error.StripeError("rate limited")

    monkeypatch.setattr(stripe_research.stripe.Charge, "search", boom)
    out = stripe_research.search_charges_by_last4("4242")
    assert out["ok"] is False
    assert "rate limited" in out["error"]


def test_search_unavailable_without_api_key(monkeypatch):
    monkeypatch.delenv("STRIPE_READ_API_KEY", raising=False)
    out = stripe_research.search_charges_by_last4("4242")
    assert out["ok"] is False
    assert "STRIPE_READ_API_KEY" in out["error"]


# ---------------------------------------------------------------------------
# search_customers_by_email / search_customers_by_name
# ---------------------------------------------------------------------------

def test_search_customers_by_email_builds_query(monkeypatch):
    _key(monkeypatch)
    captured = {}

    def fake_search(**kwargs):
        captured.update(kwargs)
        return _SearchResult([{"id": "cus_9", "email": "jane@doe.com", "name": "Jane Doe"}])

    monkeypatch.setattr(stripe_research.stripe.Customer, "search", fake_search)
    out = stripe_research.search_customers_by_email("Jane@Doe.com")
    assert out["ok"] is True
    assert captured["query"] == "email:'jane@doe.com'"
    assert out["customers"] == [{"id": "cus_9", "email": "jane@doe.com", "name": "Jane Doe"}]


def test_search_customers_by_email_strips_embedded_quotes(monkeypatch):
    _key(monkeypatch)
    captured = {}
    monkeypatch.setattr(stripe_research.stripe.Customer, "search",
                        lambda **kw: captured.update(kw) or _SearchResult([]))
    stripe_research.search_customers_by_email("a'b@x.co")
    assert captured["query"] == "email:'ab@x.co'"


def test_search_customers_by_name_uses_substring_match(monkeypatch):
    _key(monkeypatch)
    captured = {}
    monkeypatch.setattr(stripe_research.stripe.Customer, "search",
                        lambda **kw: captured.update(kw) or _SearchResult([]))
    out = stripe_research.search_customers_by_name("Smith")
    assert out["ok"] is True
    assert captured["query"] == "name~'Smith'"


def test_search_customers_by_name_rejects_blank(monkeypatch):
    _key(monkeypatch)
    monkeypatch.setattr(stripe_research.stripe.Customer, "search",
                        lambda **kw: (_ for _ in ()).throw(AssertionError("no call")))
    assert stripe_research.search_customers_by_name("  ")["ok"] is False


# ---------------------------------------------------------------------------
# date / amount scan helpers (pure)
# ---------------------------------------------------------------------------

def test_filter_charges_by_amount():
    charges = [{"id": "ch_1", "amount": 9999}, {"id": "ch_2", "amount": 6999}]
    assert [c["id"] for c in stripe_research.filter_charges_by_amount(charges, 6999)] == ["ch_2"]
    assert stripe_research.filter_charges_by_amount(charges, 1234) == []


def test_filter_charges_by_date_with_tolerance():
    charges = [
        {"id": "ch_1", "created": 1749945600},  # 2025-06-15
        {"id": "ch_2", "created": 1735689600},  # 2025-01-01
    ]
    hits = stripe_research.filter_charges_by_date(charges, "2025-06-13", tolerance_days=3)
    assert [c["id"] for c in hits] == ["ch_1"]
    assert stripe_research.filter_charges_by_date(charges, "2025-03-01", tolerance_days=3) == []


def test_filter_charges_by_date_bad_input_returns_empty():
    assert stripe_research.filter_charges_by_date([{"created": 1}], "not-a-date") == []


# ---------------------------------------------------------------------------
# detect_charge_hunt_signals
# ---------------------------------------------------------------------------

def test_detect_signals_card_ending_in():
    sig = stripe_research.detect_charge_hunt_signals(
        "I was billed on my Visa ending in 4242 but you say I have no account")
    assert sig is not None
    assert sig["last4"] == ["4242"]


def test_detect_signals_last_four_digits_phrasing():
    sig = stripe_research.detect_charge_hunt_signals(
        "The last 4 digits of the card are 9871.")
    assert sig is not None
    assert sig["last4"] == ["9871"]


def test_detect_signals_masked_card_number():
    sig = stripe_research.detect_charge_hunt_signals("It shows card ****1234 on the receipt")
    assert sig is not None
    assert sig["last4"] == ["1234"]


def test_detect_signals_charge_language_with_amount_and_no_subscription():
    blob = "Account Found: false"
    sig = stripe_research.detect_charge_hunt_signals(
        "I was charged $99.99 on June 3rd but I can't log in", account_blob=blob)
    assert sig is not None
    assert sig["amounts_cents"] == [9999]


def test_detect_signals_none_when_account_subscribed_and_no_last4():
    blob = "Account Found: true\nSubscribed: true"
    sig = stripe_research.detect_charge_hunt_signals(
        "I was charged $99.99 yesterday, why?", account_blob=blob)
    assert sig is None


def test_detect_signals_ignores_years_and_plain_numbers():
    assert stripe_research.detect_charge_hunt_signals(
        "I signed up in 2024 and meditated 1500 minutes") is None


def test_detect_signals_ignores_markdown_bold_before_a_year():
    assert stripe_research.detect_charge_hunt_signals(
        "It was **great** 2024 was my best year") is None


def test_detect_signals_empty_text():
    assert stripe_research.detect_charge_hunt_signals("") is None
    assert stripe_research.detect_charge_hunt_signals(None) is None


# ---------------------------------------------------------------------------
# summarize_charge_hunt — the decisive, factual roll-up
# ---------------------------------------------------------------------------

def test_summarize_clean_miss(monkeypatch):
    _key(monkeypatch)
    monkeypatch.setattr(stripe_research.stripe.Charge, "search", lambda **kw: _SearchResult([]))
    monkeypatch.setattr(stripe_research.stripe.Customer, "search", lambda **kw: _SearchResult([]))
    out = stripe_research.summarize_charge_hunt(
        last4s=["4242"], emails=["a@x.co"], names=["Smith"])
    assert out["available"] is True
    assert out["verdict"] == "no_match"
    assert out["charge_matches"] == []
    assert out["customer_matches"] == []
    assert out["errors"] == []


def test_summarize_match_found_with_owning_customer(monkeypatch):
    _key(monkeypatch)
    monkeypatch.setattr(stripe_research.stripe.Charge, "search",
                        lambda **kw: _SearchResult([_charge()]))
    monkeypatch.setattr(stripe_research.stripe.Customer, "search",
                        lambda **kw: _SearchResult([]))
    out = stripe_research.summarize_charge_hunt(last4s=["4242"], emails=["a@x.co"])
    assert out["verdict"] == "match_found"
    m = out["charge_matches"][0]
    assert m["billing_email"] == "jane@doe.com"
    assert m["customer_id"] == "cus_9"


def test_summarize_search_failure_is_unavailable_not_clean_miss(monkeypatch):
    _key(monkeypatch)

    def boom(**kw):
        raise stripe.error.StripeError("boom")

    monkeypatch.setattr(stripe_research.stripe.Charge, "search", boom)
    monkeypatch.setattr(stripe_research.stripe.Customer, "search", boom)
    out = stripe_research.summarize_charge_hunt(last4s=["4242"], emails=["a@x.co"])
    assert out["available"] is False
    assert out["verdict"] == "unavailable"
    assert out["errors"]


def test_summarize_partial_failure_with_match_still_reports_match(monkeypatch):
    _key(monkeypatch)
    monkeypatch.setattr(stripe_research.stripe.Charge, "search",
                        lambda **kw: _SearchResult([_charge()]))

    def boom(**kw):
        raise stripe.error.StripeError("boom")

    monkeypatch.setattr(stripe_research.stripe.Customer, "search", boom)
    out = stripe_research.summarize_charge_hunt(last4s=["4242"], emails=["a@x.co"])
    assert out["verdict"] == "match_found"
    assert out["errors"]  # the failed leg is still surfaced


def test_summarize_marks_truncated_when_more_pages_exist(monkeypatch):
    _key(monkeypatch)
    monkeypatch.setattr(stripe_research.stripe.Charge, "search",
                        lambda **kw: _SearchResult([_charge()], has_more=True))
    monkeypatch.setattr(stripe_research.stripe.Customer, "search",
                        lambda **kw: _SearchResult([]))
    out = stripe_research.summarize_charge_hunt(last4s=["0000"], emails=["a@x.co"])
    assert out["truncated"] is True
    block = stripe_research.format_charge_hunt_block(out)
    assert "first page" in block.lower() or "more results exist" in block.lower()


def test_summarize_not_truncated_on_single_page(monkeypatch):
    _key(monkeypatch)
    monkeypatch.setattr(stripe_research.stripe.Charge, "search",
                        lambda **kw: _SearchResult([]))
    out = stripe_research.summarize_charge_hunt(last4s=["4242"])
    assert out["truncated"] is False


def test_summarize_no_key_is_unavailable(monkeypatch):
    monkeypatch.delenv("STRIPE_READ_API_KEY", raising=False)
    out = stripe_research.summarize_charge_hunt(last4s=["4242"])
    assert out["available"] is False
    assert out["verdict"] == "unavailable"


# ---------------------------------------------------------------------------
# format_charge_hunt_block — facts only, for the draft prompt
# ---------------------------------------------------------------------------

def test_format_block_no_match_states_facts():
    summary = {
        "available": True, "verdict": "no_match",
        "searched": {"last4s": ["4242"], "emails": ["a@x.co"], "names": ["Smith"]},
        "charge_matches": [], "customer_matches": [], "errors": [],
    }
    block = stripe_research.format_charge_hunt_block(summary)
    assert "STRIPE CHARGE HUNT" in block
    assert "4242" in block and "a@x.co" in block and "Smith" in block
    assert "NO MATCH" in block


def test_format_block_match_lists_charge_and_owner():
    summary = {
        "available": True, "verdict": "match_found",
        "searched": {"last4s": ["4242"], "emails": [], "names": []},
        "charge_matches": [{
            "id": "ch_1", "amount": 9999, "currency": "usd", "created": 1749945600,
            "status": "succeeded", "paid": True, "refunded": False, "card_last4": "4242",
            "customer_id": "cus_9", "billing_email": "jane@doe.com",
            "billing_name": "Jane Doe", "description": "Subscription renewal",
        }],
        "customer_matches": [], "errors": [],
    }
    block = stripe_research.format_charge_hunt_block(summary)
    assert "ch_1" in block
    assert "$99.99" in block
    assert "jane@doe.com" in block
    assert "2025-06-15" in block


def test_format_block_unavailable_is_not_a_clean_miss():
    summary = {
        "available": False, "verdict": "unavailable",
        "searched": {"last4s": ["4242"], "emails": [], "names": []},
        "charge_matches": [], "customer_matches": [], "errors": ["charges: boom"],
    }
    block = stripe_research.format_charge_hunt_block(summary)
    assert "UNAVAILABLE" in block
    assert "NO MATCH" not in block


# ---------------------------------------------------------------------------
# run_charge_hunt_for_ticket — signal gate + candidate assembly
# ---------------------------------------------------------------------------

def test_run_charge_hunt_no_signals_returns_none(monkeypatch):
    _key(monkeypatch)

    def boom(**kw):
        raise AssertionError("no Stripe call without signals")

    monkeypatch.setattr(stripe_research.stripe.Charge, "search", boom)
    monkeypatch.setattr(stripe_research.stripe.Customer, "search", boom)
    out = stripe_research.run_charge_hunt_for_ticket(
        body="How do I reset my password?", email="a@x.co", customer_name="Jane Doe")
    assert out is None


def test_run_charge_hunt_assembles_candidates_from_ticket(monkeypatch):
    _key(monkeypatch)
    queries = []

    def fake_charge_search(**kw):
        queries.append(kw["query"])
        return _SearchResult([])

    def fake_customer_search(**kw):
        queries.append(kw["query"])
        return _SearchResult([])

    monkeypatch.setattr(stripe_research.stripe.Charge, "search", fake_charge_search)
    monkeypatch.setattr(stripe_research.stripe.Customer, "search", fake_customer_search)
    out = stripe_research.run_charge_hunt_for_ticket(
        body="My card ending in 4242 was charged. My other email is old@me.com.",
        email="a@x.co", customer_name="Jane Doe",
        account_blob="Account Found: false")
    assert out is not None
    assert out["verdict"] == "no_match"
    joined = " ".join(queries)
    assert "last4:'4242'" in joined
    assert "email:'a@x.co'" in joined
    assert "email:'old@me.com'" in joined
    assert "name~'Doe'" in joined


# ---------------------------------------------------------------------------
# hydrate_ticket wiring (bert/pipeline) — hunt runs on signals, fail-soft
# ---------------------------------------------------------------------------

def _hydrate_env(monkeypatch, *, body, blob="Account Found: false"):
    import bert.pipeline as pl
    o = pl.orchestrator
    monkeypatch.setattr(o, "fetch_conversation", lambda s, cid: {"subject": "Sub", "tags": []})
    monkeypatch.setattr(o, "_fetch_conversation_threads", lambda s, c, cid: [])
    monkeypatch.setattr(o, "detect_reply_mode", lambda threads: False)
    monkeypatch.setattr(o, "_customer_from_conversation", lambda c: {"id": 77, "email": "c@x.co"})
    monkeypatch.setattr(o, "_customer_display_name", lambda c: "Jane Doe")
    monkeypatch.setattr(o, "_extract_tag_names", lambda t: [])
    monkeypatch.setattr(o, "get_conversation_text", lambda s, cid, threads=None: body)
    monkeypatch.setattr(o, "fetch_customer_emails_from_helpscout", lambda s, cid: [])
    monkeypatch.setattr(o, "fetch_account_contexts_for_ticket",
                        lambda **k: {"combined_blob": blob})
    monkeypatch.setattr(o, "_subscription_platform", lambda blob: "")
    return pl


def test_hydrate_runs_hunt_on_last4_signal_and_appends_block(monkeypatch):
    _key(monkeypatch)
    pl = _hydrate_env(monkeypatch, body="I was charged on my card ending in 4242.")
    monkeypatch.setattr(stripe_research.stripe.Charge, "search", lambda **kw: _SearchResult([]))
    monkeypatch.setattr(stripe_research.stripe.Customer, "search", lambda **kw: _SearchResult([]))
    ctx = pl.hydrate_ticket(object(), 5)
    assert ctx["stripe_research"] is not None
    assert ctx["stripe_research"]["verdict"] == "no_match"
    assert "STRIPE CHARGE HUNT" in ctx["stripe_block"]
    assert "NO MATCH" in ctx["stripe_block"]


def test_hydrate_skips_hunt_without_signals(monkeypatch):
    _key(monkeypatch)
    pl = _hydrate_env(monkeypatch, body="How do I reset my password?",
                      blob="Account Found: true\nSubscribed: true")
    called = []
    monkeypatch.setattr(stripe_research.stripe.Charge, "search",
                        lambda **kw: called.append(1) or _SearchResult([]))
    ctx = pl.hydrate_ticket(object(), 5)
    assert ctx["stripe_research"] is None
    assert "STRIPE CHARGE HUNT" not in ctx["stripe_block"]
    assert called == []


def test_hydrate_scans_conversation_history_in_reply_mode(monkeypatch):
    # The last-4 usually arrives in an EARLIER customer reply; the latest
    # message may just be "did you find it?". The hunt must scan the history.
    _key(monkeypatch)
    import bert.pipeline as pl
    o = pl.orchestrator
    monkeypatch.setattr(o, "fetch_conversation", lambda s, cid: {"subject": "Sub", "tags": []})
    monkeypatch.setattr(o, "_fetch_conversation_threads", lambda s, c, cid: [])
    monkeypatch.setattr(o, "detect_reply_mode", lambda threads: True)
    monkeypatch.setattr(o, "_customer_from_conversation", lambda c: {"id": 77, "email": "c@x.co"})
    monkeypatch.setattr(o, "_customer_display_name", lambda c: "Jane Doe")
    monkeypatch.setattr(o, "_extract_tag_names", lambda t: [])
    monkeypatch.setattr(o, "get_conversation_history",
                        lambda s, cid, threads=None: (
                            "[customer] my card ending in 4242 was charged", "Did you find it?"))
    monkeypatch.setattr(o, "fetch_customer_emails_from_helpscout", lambda s, cid: [])
    monkeypatch.setattr(o, "fetch_account_contexts_for_ticket",
                        lambda **k: {"combined_blob": "Account Found: false"})
    monkeypatch.setattr(o, "_subscription_platform", lambda blob: "")
    monkeypatch.setattr(stripe_research.stripe.Charge, "search", lambda **kw: _SearchResult([]))
    monkeypatch.setattr(stripe_research.stripe.Customer, "search", lambda **kw: _SearchResult([]))
    ctx = pl.hydrate_ticket(object(), 5)
    assert ctx["stripe_research"] is not None
    assert "4242" in " ".join(ctx["stripe_research"]["searched"]["last4s"])


def test_hydrate_fail_soft_when_hunt_explodes(monkeypatch):
    _key(monkeypatch)
    pl = _hydrate_env(monkeypatch, body="card ending in 4242 was charged")

    def boom(**kwargs):
        raise RuntimeError("unexpected explosion")

    monkeypatch.setattr(stripe_research, "run_charge_hunt_for_ticket", boom)
    ctx = pl.hydrate_ticket(object(), 5)  # must not raise
    assert ctx["stripe_research"] is None
    assert ctx["conversation_id"] == 5


# ---------------------------------------------------------------------------
# verify_claimed_stripe_objects — pre-send truth check
# ---------------------------------------------------------------------------

def _missing(kind_msg):
    return stripe.error.InvalidRequestError(
        f"No such {kind_msg}", param=None, code="resource_missing")


def test_truth_check_flags_nonexistent_subscription_id(monkeypatch):
    _key(monkeypatch)

    def fake_retrieve(sid):
        raise _missing("subscription: " + sid)

    monkeypatch.setattr(stripe_research.stripe.Subscription, "retrieve", fake_retrieve)
    result = {
        "draft_reply": "I've cancelled subscription sub_NOPE12345 for you.",
        "parsed": {},
    }
    out = stripe_research.verify_claimed_stripe_objects(result, customer_email="a@x.co")
    assert out["available"] is True
    findings = out["findings"]
    assert len(findings) == 1
    f = findings[0]
    assert f["class"] == "A"
    assert "sub_NOPE12345" in f["detail"]
    assert f["fix_type"] == "none"


def test_truth_check_flags_ownership_mismatch(monkeypatch):
    _key(monkeypatch)
    monkeypatch.setattr(stripe_research.stripe.Subscription, "retrieve",
                        lambda sid: SimpleNamespace(id=sid, customer="cus_OTHER"))
    monkeypatch.setattr(stripe_research.stripe.Customer, "retrieve",
                        lambda cid: SimpleNamespace(id=cid, email="someone-else@y.co", name="Other"))
    result = {"draft_reply": "Your subscription sub_ABC123456 is set to cancel.", "parsed": {}}
    out = stripe_research.verify_claimed_stripe_objects(result, customer_email="a@x.co")
    assert len(out["findings"]) == 1
    f = out["findings"][0]
    assert f["class"] == "A"
    assert "someone-else@y.co" in f["detail"] or "belongs" in f["detail"]


def test_truth_check_passes_owned_subscription(monkeypatch):
    _key(monkeypatch)
    monkeypatch.setattr(stripe_research.stripe.Subscription, "retrieve",
                        lambda sid: SimpleNamespace(id=sid, customer="cus_9"))
    monkeypatch.setattr(stripe_research.stripe.Customer, "retrieve",
                        lambda cid: SimpleNamespace(id=cid, email="a@x.co", name="Jane"))
    result = {"draft_reply": "Your subscription sub_ABC123456 stays active until June.",
              "parsed": {}}
    out = stripe_research.verify_claimed_stripe_objects(result, customer_email="a@x.co")
    assert out["findings"] == []


def test_truth_check_flags_action_claim_without_locatable_object(monkeypatch):
    _key(monkeypatch)
    monkeypatch.setattr(stripe_research.stripe.Customer, "search", lambda **kw: _SearchResult([]))
    result = {
        "draft_reply": "Good news — your refund has been processed and will land in 5-10 days.",
        "parsed": {},
    }
    out = stripe_research.verify_claimed_stripe_objects(result, customer_email="ghost@x.co")
    findings = out["findings"]
    assert len(findings) == 1
    assert findings[0]["class"] == "C"
    assert findings[0]["fix_type"] == "none"


def test_truth_check_claim_ok_when_stripe_ctx_already_located():
    # Enrichment already found the subscription — no extra Stripe calls needed.
    result = {
        "draft_reply": "Your subscription has been cancelled and stays active until June.",
        "parsed": {},
        "stripe_ctx": {"subscription_id": "sub_REAL", "stripe_customer_id": "cus_9"},
    }
    out = stripe_research.verify_claimed_stripe_objects(result, customer_email="a@x.co")
    assert out["findings"] == []


def test_truth_check_no_claims_no_ids_makes_no_api_calls(monkeypatch):
    _key(monkeypatch)

    def boom(*a, **kw):
        raise AssertionError("no Stripe call expected")

    monkeypatch.setattr(stripe_research.stripe.Customer, "search", boom)
    monkeypatch.setattr(stripe_research.stripe.Subscription, "retrieve", boom)
    result = {"draft_reply": "Here's how to reset your password.", "parsed": {}}
    out = stripe_research.verify_claimed_stripe_objects(result, customer_email="a@x.co")
    assert out["findings"] == []


def test_truth_check_fail_soft_on_stripe_outage(monkeypatch):
    _key(monkeypatch)

    def boom(sid):
        raise stripe.error.APIConnectionError("network down")

    monkeypatch.setattr(stripe_research.stripe.Subscription, "retrieve", boom)
    result = {"draft_reply": "I've cancelled subscription sub_NOPE12345.", "parsed": {}}
    out = stripe_research.verify_claimed_stripe_objects(result, customer_email="a@x.co")
    # Outage ≠ evidence of a lie: no finding, but flagged unavailable.
    assert out["findings"] == []
    assert out["available"] is False


def test_truth_check_unavailable_without_key(monkeypatch):
    monkeypatch.delenv("STRIPE_READ_API_KEY", raising=False)
    result = {"draft_reply": "I've cancelled subscription sub_NOPE12345.", "parsed": {}}
    out = stripe_research.verify_claimed_stripe_objects(result)
    assert out["available"] is False
    assert out["findings"] == []


def test_truth_check_scans_action_description_too(monkeypatch):
    _key(monkeypatch)

    def fake_retrieve(sid):
        raise _missing("subscription")

    monkeypatch.setattr(stripe_research.stripe.Subscription, "retrieve", fake_retrieve)
    result = {"draft_reply": "We're on it!",
              "parsed": {"action_description": "Cancel sub_GHOST9999 in Stripe"}}
    out = stripe_research.verify_claimed_stripe_objects(result, customer_email="a@x.co")
    assert len(out["findings"]) == 1
    assert "sub_GHOST9999" in out["findings"][0]["detail"]


# ---------------------------------------------------------------------------
# verifier wiring (bert/fanout._initial_verdict) — truth check gates the
# model review and surfaces findings as an ERROR verdict
# ---------------------------------------------------------------------------

def test_initial_verdict_errors_on_truth_check_finding(monkeypatch):
    import bert.fanout as fo
    monkeypatch.setattr(fo.verify, "prelint", lambda text: [])
    monkeypatch.setattr(fo.pipeline, "hydrate_ticket",
                        lambda s, cid: {"email": "a@x.co", "conversation_id": cid})
    monkeypatch.setattr(fo.verify, "find_sibling_conversations",
                        lambda s, email, exclude_cid: [])
    finding = {"class": "A", "detail": "sub_X does not exist", "fix_type": "none",
               "suggested_fix": "Locate the real subscription before claiming."}
    monkeypatch.setattr(fo.stripe_research, "verify_claimed_stripe_objects",
                        lambda result, customer_email=None: {"available": True,
                                                             "findings": [finding]})
    monkeypatch.setattr(fo.verify, "verify_draft",
                        lambda *a, **kw: (_ for _ in ()).throw(
                            AssertionError("model review must not run")))
    result = {"conversation_id": 5, "draft_reply": "I've cancelled sub_X.", "parsed": {}}
    v, ctx, policies = fo._initial_verdict(object(), object(), result, brief="", model=None)
    assert v["verdict"] == "ERROR"
    assert v["findings"] == [finding]


def test_initial_verdict_proceeds_to_model_review_when_truth_check_clean(monkeypatch):
    import bert.fanout as fo
    monkeypatch.setattr(fo.verify, "prelint", lambda text: [])
    monkeypatch.setattr(fo.pipeline, "hydrate_ticket",
                        lambda s, cid: {"email": "a@x.co", "conversation_id": cid})
    monkeypatch.setattr(fo.verify, "find_sibling_conversations",
                        lambda s, email, exclude_cid: [])
    monkeypatch.setattr(fo.stripe_research, "verify_claimed_stripe_objects",
                        lambda result, customer_email=None: {"available": True, "findings": []})
    monkeypatch.setattr(fo.orchestrator, "load_policy_docs", lambda: "POLICIES")
    monkeypatch.setattr(fo.verify, "verify_draft",
                        lambda *a, **kw: {"verdict": "SEND_AS_IS", "findings": []})
    result = {"conversation_id": 5, "draft_reply": "hi", "parsed": {}}
    v, ctx, policies = fo._initial_verdict(object(), object(), result, brief="", model=None)
    assert v["verdict"] == "SEND_AS_IS"


def test_initial_verdict_truth_check_never_blocks_on_exception(monkeypatch):
    # verify_claimed_stripe_objects is contractually never-raises, but the
    # wiring must also survive if that contract breaks.
    import bert.fanout as fo
    monkeypatch.setattr(fo.verify, "prelint", lambda text: [])
    monkeypatch.setattr(fo.pipeline, "hydrate_ticket",
                        lambda s, cid: {"email": "a@x.co", "conversation_id": cid})
    monkeypatch.setattr(fo.verify, "find_sibling_conversations",
                        lambda s, email, exclude_cid: [])

    def boom(result, customer_email=None):
        raise RuntimeError("contract break")

    monkeypatch.setattr(fo.stripe_research, "verify_claimed_stripe_objects", boom)
    monkeypatch.setattr(fo.orchestrator, "load_policy_docs", lambda: "POLICIES")
    monkeypatch.setattr(fo.verify, "verify_draft",
                        lambda *a, **kw: {"verdict": "SEND_AS_IS", "findings": []})
    result = {"conversation_id": 5, "draft_reply": "hi", "parsed": {}}
    v, ctx, policies = fo._initial_verdict(object(), object(), result, brief="", model=None)
    assert v["verdict"] == "SEND_AS_IS"
