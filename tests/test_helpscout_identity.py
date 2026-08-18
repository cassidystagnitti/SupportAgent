from __future__ import annotations

import json

import pytest

import helpscout_identity as hi


# --- fake Help Scout --------------------------------------------------------

class _Resp:
    def __init__(self, payload=None, status_code=200, headers=None):
        self._payload = payload or {}
        self.status_code = status_code
        self.headers = headers or {}

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeHS:
    """Minimal stand-in for the Help Scout customers/conversations endpoints."""

    def __init__(self, contacts=None, conversations=None, fail_on=()):
        # {customer_id: {"firstName":…, "lastName":…, "conversationCount":…,
        #                "emails":[{"id":…, "value":…, "type":…}]}}
        self.contacts = contacts or {}
        self.conversations = conversations or []   # [{"id":…, "primaryCustomer":{"id":…}}]
        self.fail_on = set(fail_on)                # email values whose POST should fail
        self.posts, self.deletes, self.patches = [], [], []

    # -- reads
    def get(self, url, params=None, timeout=None):
        if url.endswith("/emails"):
            cid = int(url.split("/customers/")[1].split("/")[0])
            return _Resp({"_embedded": {"emails": self.contacts[cid]["emails"]}})
        if "/customers" in url and params and "email" in params:
            for cid, contact in self.contacts.items():
                if any(e["value"] == params["email"] for e in contact["emails"]):
                    return _Resp({"_embedded": {"customers": [{"id": cid, **contact}]}})
            return _Resp({"_embedded": {"customers": []}})
        if "/conversations" in url:
            return _Resp({"_embedded": {"conversations": self.conversations},
                          "page": {"totalPages": 1}})
        raise AssertionError(f"unexpected GET {url}")

    # -- writes
    def post(self, url, json=None, timeout=None):
        cid = int(url.split("/customers/")[1].split("/")[0])
        value = json["value"]
        self.posts.append((cid, value))
        if value in self.fail_on:
            return _Resp(status_code=400)
        self.contacts[cid]["emails"].append({"id": 9000 + len(self.posts), "value": value,
                                             "type": json["type"]})
        return _Resp(status_code=201, headers={"Resource-Id": str(9000 + len(self.posts))})

    def delete(self, url, timeout=None):
        cid = int(url.split("/customers/")[1].split("/")[0])
        email_id = int(url.rsplit("/", 1)[1])
        self.deletes.append((cid, email_id))
        self.contacts[cid]["emails"] = [e for e in self.contacts[cid]["emails"]
                                        if e["id"] != email_id]
        return _Resp(status_code=204)

    def patch(self, url, json=None, timeout=None):
        self.patches.append((url, json))
        return _Resp(status_code=204)


def contact(first="Jane", last="Doe", emails=(("jane@example.net", 1),), conversations=2):
    return {"firstName": first, "lastName": last, "conversationCount": conversations,
            "emails": [{"id": eid, "value": v, "type": "home"} for v, eid in emails]}


# --- address filter ---------------------------------------------------------

@pytest.mark.parametrize("email", [
    "support@happier.com", "no-reply@foo.com", "billing@acme.io", "notifications@x.org",
])
def test_role_addresses_are_never_linkable(email):
    ok, why = hi.is_linkable_address(email)
    assert not ok and "role address" in why


@pytest.mark.parametrize("email", [
    "someone@meditatehappier.com", "x@mail.meditatehappier.com", "y@email.apple.com",
    "invoice+statements@stripe.com", "z@example.com",
])
def test_internal_and_vendor_domains_are_never_linkable(email):
    ok, why = hi.is_linkable_address(email)
    assert not ok and "internal or vendor domain" in why


@pytest.mark.parametrize("email", [
    "jane@icloud.com", "jane@me.com", "jane.doe@gmail.com", "d8xk2mn4p9@privaterelay.appleid.com",
])
def test_personal_addresses_are_linkable(email):
    """Apple/Google PERSONAL domains are customers, not vendors — including a
    genuine Hide My Email address, which is what a SIWA account lives under."""
    assert hi.is_linkable_address(email) == (True, "")


def test_apple_reply_relay_for_a_sender_is_rejected():
    """These ride in on every forwarded receipt and encode OUR address, not theirs."""
    relay = "support_at_mail_meditatehappier_com_2e4qje8gzj_d66c5d31@privaterelay.appleid.com"
    ok, why = hi.is_linkable_address(relay)
    assert not ok and "reply-relay" in why
    assert hi.is_apple_reply_relay(relay)
    assert not hi.is_apple_reply_relay("d8xk2mn4p9@privaterelay.appleid.com")


def test_garbage_is_rejected():
    assert hi.is_linkable_address("not-an-email")[0] is False
    assert hi.is_linkable_address("")[0] is False


# --- ownership evidence -----------------------------------------------------

@pytest.mark.parametrize("text", [
    "Hi, my other email is jane@old.com — can you check that one?",
    "I signed up with jane@old.com originally.",
    "My old email address (jane@old.com) still has my history.",
    "I think I registered under jane@old.com.",
    "You can reach me at jane@old.com too.",
])
def test_first_person_claims_are_recognized(text):
    assert hi.claims_ownership(text, "jane@old.com")


@pytest.mark.parametrize("text", [
    "I saw a charge — please ask jane@old.com about it.",
    "The receipt lists jane@old.com.",
    "jane@old.com",
])
def test_bare_mentions_are_not_a_claim(text):
    assert not hi.claims_ownership(text, "jane@old.com")


@pytest.mark.parametrize("text", [
    "Please send the gift to my wife at jane@old.com.",
    "My daughter uses jane@old.com.",
    "Can you set up jane@old.com for my colleague?",
    "Her email is jane@old.com.",
    "This is a gift for jane@old.com.",
])
def test_third_party_markers_veto_the_link(text):
    assert hi.mentions_third_party(text, "jane@old.com")
    assert not hi.claims_ownership(text, "jane@old.com")


def test_a_third_party_marker_anywhere_beats_a_claim_elsewhere():
    """Ambiguity goes to a human, not to a write."""
    text = ("I signed up with jane@old.com. Also jane@old.com is my wife's, "
            "please move hers too.")
    assert not hi.claims_ownership(text, "jane@old.com")


def test_claims_are_scoped_to_the_address_in_question():
    text = "My other email is jane@old.com. Separately, bob@corp.com wrote to you last week."
    assert hi.claims_ownership(text, "jane@old.com")
    assert not hi.claims_ownership(text, "bob@corp.com")


# --- name comparison --------------------------------------------------------

def test_names_agree_only_on_a_real_match():
    assert hi.names_agree("Paul", "Paul Dwyer")
    assert hi.names_agree("paul ", "PAUL")
    assert not hi.names_agree("", "Paul")
    assert not hi.names_agree("Paul", "")


def test_names_conflict_needs_both_sides():
    assert hi.names_conflict("Brenda", "John Peterson")
    assert not hi.names_conflict("", "John")
    assert not hi.names_conflict("John", "John Peterson")


# --- classify_candidate -----------------------------------------------------

def _cand(email, source="customer message", strong=False):
    return {"email": email, "sources": [source], "presumed_strong": strong}


def test_account_name_match_is_strong_evidence():
    got = hi.classify_candidate(
        _cand("jane@old.com"), customer_text="see jane@old.com", contact_name="Jane Doe",
        lookup_account_name=lambda e: "Jane")
    assert got["strength"] == "strong"
    assert "also named Jane" in got["evidence"]


def test_account_name_mismatch_is_only_a_proposal():
    got = hi.classify_candidate(
        _cand("brenda@old.com"), customer_text="see brenda@old.com", contact_name="John Peterson",
        lookup_account_name=lambda e: "Brenda")
    assert got["strength"] == "weak"
    assert "different person?" in got["evidence"]


def test_caller_verified_candidates_are_trusted():
    got = hi.classify_candidate(
        _cand("jane@old.com", source="stripe charge match", strong=True),
        customer_text="", contact_name="Jane", lookup_account_name=lambda e: None)
    assert got["strength"] == "strong"


def test_blocked_addresses_short_circuit_before_any_lookup():
    def _boom(email):
        raise AssertionError("must not look up a blocked address")

    got = hi.classify_candidate(_cand("support@acme.com"), customer_text="",
                                contact_name="Jane", lookup_account_name=_boom)
    assert got["strength"] == "blocked"


# --- plan_ticket_identity ---------------------------------------------------

def _plan(session, **kw):
    kw.setdefault("conversation_id", 111)
    kw.setdefault("hs_customer_id", 1)
    kw.setdefault("primary_email", "jane@example.net")
    kw.setdefault("contact_name", "Jane Doe")
    kw.setdefault("lookup_account_name", lambda e: None)
    return hi.plan_ticket_identity(session, **kw)


def test_unowned_claimed_address_is_linked():
    hs = FakeHS({1: contact(emails=(("jane@example.net", 1),))})
    plan = _plan(hs, customer_text="my other email is jane@old.com")
    assert [(a["action"], a["email"]) for a in plan["actions"]] == [(hi.LINK, "jane@old.com")]


def test_unclaimed_address_is_only_proposed():
    hs = FakeHS({1: contact()})
    plan = _plan(hs, customer_text="the receipt shows jane@old.com")
    assert plan["actions"][0]["action"] == hi.PROPOSE_LINK


def test_addresses_already_on_the_contact_are_ignored():
    hs = FakeHS({1: contact(emails=(("jane@example.net", 1), ("jane@old.com", 2)))})
    plan = _plan(hs, customer_text="my other email is jane@old.com")
    assert plan["actions"] == []


def test_the_primary_address_is_never_a_candidate():
    hs = FakeHS({1: contact()})
    plan = _plan(hs, customer_text="I signed up with jane@example.net")
    assert plan["actions"] == []


def test_duplicate_contact_with_agreeing_names_is_merged():
    hs = FakeHS({
        1: contact(first="Jane", emails=(("jane@example.net", 1),)),
        2: contact(first="Jane", last="Doe", emails=(("jane@old.com", 2),), conversations=3),
    })
    plan = _plan(hs, customer_text="my other email is jane@old.com")
    action = plan["actions"][0]
    assert action["action"] == hi.MERGE
    assert action["dup_customer_id"] == 2


def test_duplicate_contact_with_conflicting_names_is_only_proposed():
    hs = FakeHS({
        1: contact(first="John", last="Peterson", emails=(("john@example.net", 1),)),
        2: contact(first="Brenda", last="Peterson", emails=(("brenda@old.com", 2),)),
    })
    plan = _plan(hs, primary_email="john@example.net", contact_name="John Peterson",
                 customer_text="my other email is brenda@old.com")
    action = plan["actions"][0]
    assert action["action"] == hi.PROPOSE_MERGE
    assert "names disagree" in action["reason"]


def test_a_weakly_evidenced_duplicate_is_only_proposed():
    hs = FakeHS({
        1: contact(emails=(("jane@example.net", 1),)),
        2: contact(first="Jane", emails=(("jane@old.com", 2),)),
    })
    plan = _plan(hs, customer_text="the receipt shows jane@old.com")
    assert plan["actions"][0]["action"] == hi.PROPOSE_MERGE


def test_a_large_duplicate_is_left_to_the_help_scout_ui(monkeypatch):
    monkeypatch.setenv("HELPSCOUT_IDENTITY_MERGE_MAX_CONVERSATIONS", "5")
    hs = FakeHS({
        1: contact(emails=(("jane@example.net", 1),)),
        2: contact(first="Jane", emails=(("jane@old.com", 2),), conversations=99),
    })
    plan = _plan(hs, customer_text="my other email is jane@old.com")
    action = plan["actions"][0]
    assert action["action"] == hi.PROPOSE_MERGE
    assert "Help Scout UI" in action["reason"]


def test_missing_customer_id_is_reported_not_raised():
    plan = _plan(FakeHS(), hs_customer_id=None)
    assert plan["error"] and plan["actions"] == []


def test_plan_has_writes_reflects_only_automatic_actions():
    assert hi.plan_has_writes({"actions": [{"action": hi.LINK}]})
    assert not hi.plan_has_writes({"actions": [{"action": hi.PROPOSE_MERGE},
                                               {"action": hi.SKIP}]})


# --- apply_identity_plan ----------------------------------------------------

@pytest.fixture(autouse=True)
def _audit_to_tmp(tmp_path, monkeypatch):
    monkeypatch.setattr(hi, "AUDIT_LOG_PATH", str(tmp_path / "identity.jsonl"))
    monkeypatch.delenv("HELPSCOUT_IDENTITY_WRITES", raising=False)
    return tmp_path / "identity.jsonl"


def test_apply_links_and_audits(_audit_to_tmp):
    hs = FakeHS({1: contact(emails=(("jane@example.net", 1),))})
    plan = _plan(hs, customer_text="my other email is jane@old.com")
    applied = hi.apply_identity_plan(hs, plan)

    assert applied["linked"] == ["jane@old.com"]
    assert hs.posts == [(1, "jane@old.com")]
    logged = json.loads(_audit_to_tmp.read_text().splitlines()[0])
    assert logged["action"] == "link_email" and logged["email"] == "jane@old.com"


def test_writes_can_be_switched_off_per_deployment(monkeypatch):
    monkeypatch.setenv("HELPSCOUT_IDENTITY_WRITES", "false")
    hs = FakeHS({1: contact(emails=(("jane@example.net", 1),))})
    plan = _plan(hs, customer_text="my other email is jane@old.com")
    applied = hi.apply_identity_plan(hs, plan)

    assert applied["skipped_disabled"] == ["jane@old.com"]
    assert hs.posts == []


def test_proposals_are_never_written():
    hs = FakeHS({1: contact()})
    plan = _plan(hs, customer_text="the receipt shows jane@old.com")
    applied = hi.apply_identity_plan(hs, plan)
    assert applied == {"linked": [], "merged": [], "errors": [], "skipped_disabled": []}
    assert hs.posts == []


def test_a_failed_link_is_reported_not_raised():
    hs = FakeHS({1: contact(emails=(("jane@example.net", 1),))}, fail_on={"jane@old.com"})
    plan = _plan(hs, customer_text="my other email is jane@old.com")
    applied = hi.apply_identity_plan(hs, plan)
    assert applied["linked"] == []
    assert "jane@old.com" in applied["errors"][0]


# --- merge_contacts ---------------------------------------------------------

def test_merge_moves_conversations_then_addresses(_audit_to_tmp):
    hs = FakeHS(
        contacts={1: contact(emails=(("jane@example.net", 1),)),
                  2: contact(first="Jane", emails=(("jane@old.com", 2),))},
        conversations=[{"id": 777, "primaryCustomer": {"id": 2}}],
    )
    out = hi.merge_contacts(hs, keep_id=1, dup_id=2, conversation_id=111)

    assert out["conversations_moved"] == [777]
    assert hs.patches[0][1] == {"op": "replace", "path": "/primaryCustomer.id", "value": 1}
    assert out["emails_moved"] == ["jane@old.com"]
    assert hs.deletes == [(2, 2)]          # detached from the duplicate first
    assert hs.posts == [(1, "jane@old.com")]  # then attached to the keeper
    assert out["errors"] == []
    assert json.loads(_audit_to_tmp.read_text())["action"] == "merge_contacts"


def test_merge_leaves_other_customers_conversations_alone():
    hs = FakeHS(
        contacts={1: contact(emails=(("jane@example.net", 1),)),
                  2: contact(emails=(("jane@old.com", 2),))},
        conversations=[{"id": 777, "primaryCustomer": {"id": 3}}],
    )
    out = hi.merge_contacts(hs, keep_id=1, dup_id=2, conversation_id=111)
    assert out["conversations_moved"] == [] and hs.patches == []


def test_merge_restores_an_address_when_the_keeper_rejects_it():
    """Delete-then-add can strand an address on no contact — it must go back."""
    hs = FakeHS(
        contacts={1: contact(emails=(("jane@example.net", 1),)),
                  2: contact(emails=(("jane@old.com", 2),))},
        fail_on={"jane@old.com"},
    )
    hs.fail_on = {"jane@old.com"}
    calls = {"n": 0}
    real_post = hs.post

    def flaky_post(url, json=None, timeout=None):
        calls["n"] += 1
        if calls["n"] == 1:          # the attach to the keeper fails …
            return _Resp(status_code=400)
        hs.fail_on = set()           # … the rollback onto the duplicate succeeds
        return real_post(url, json=json, timeout=timeout)

    hs.post = flaky_post
    out = hi.merge_contacts(hs, keep_id=1, dup_id=2, conversation_id=111)

    assert out["emails_moved"] == []
    assert any("restored to the duplicate" in e for e in out["errors"])


def test_merge_never_deletes_the_duplicate_contact():
    hs = FakeHS(contacts={1: contact(emails=(("jane@example.net", 1),)),
                          2: contact(emails=(("jane@old.com", 2),))})
    hi.merge_contacts(hs, keep_id=1, dup_id=2, conversation_id=111)
    assert 2 in hs.contacts          # emptied, but still there


# --- sync + reporting -------------------------------------------------------

def test_sync_plans_and_applies_in_one_call():
    hs = FakeHS({1: contact(emails=(("jane@example.net", 1),))})
    out = hi.sync_ticket_identity(
        hs, conversation_id=111, hs_customer_id=1, primary_email="jane@example.net",
        contact_name="Jane Doe", customer_text="my other email is jane@old.com")
    assert out["applied"]["linked"] == ["jane@old.com"]
    assert "Linked" in out["note_html"]
    assert out["summary"] == "linked 1"


def test_sync_can_plan_without_applying():
    hs = FakeHS({1: contact(emails=(("jane@example.net", 1),))})
    out = hi.sync_ticket_identity(
        hs, conversation_id=111, hs_customer_id=1, primary_email="jane@example.net",
        customer_text="my other email is jane@old.com", apply=False)
    assert hs.posts == [] and out["applied"]["linked"] == []


def test_sync_swallows_a_help_scout_outage():
    class Broken:
        def get(self, *a, **k):
            raise RuntimeError("help scout is down")

    out = hi.sync_ticket_identity(Broken(), conversation_id=111, hs_customer_id=1,
                                  primary_email="jane@example.net")
    assert out["applied"]["linked"] == []
    assert "did not run" in out["note_html"]


def test_note_disclaims_happier_account_merges():
    """The draft brain must never read this as 'their accounts were merged'."""
    hs = FakeHS({1: contact(emails=(("jane@example.net", 1),))})
    out = hi.sync_ticket_identity(
        hs, conversation_id=111, hs_customer_id=1, primary_email="jane@example.net",
        customer_text="my other email is jane@old.com")
    assert "does not merge Happier" in out["note_html"]
    assert "meditation history" in out["note_html"]


def test_quiet_tickets_get_no_note():
    hs = FakeHS({1: contact()})
    out = hi.sync_ticket_identity(hs, conversation_id=111, hs_customer_id=1,
                                  primary_email="jane@example.net", customer_text="hello!")
    assert out["note_html"] == "" and out["summary"] == ""


def test_note_escapes_customer_supplied_text():
    plan = {"actions": [{"action": hi.PROPOSE_LINK, "email": "<script>@x.com",
                         "evidence": "a & b"}]}
    html = hi.identity_note_html(plan)
    assert "&lt;script&gt;" in html and "a &amp; b" in html


# --- thread filtering -------------------------------------------------------

def test_only_customer_authored_threads_are_scanned():
    threads = [                      # Help Scout returns newest-first
        {"type": "note", "body": "internal: try noted@x.com"},
        {"type": "message", "body": "<p>Agent here — reply to agent@x.com</p>"},
        {"type": "customer", "body": "<p>my other email is jane@old.com</p>"},
    ]
    text = hi.customer_text_from_threads(threads)
    assert "jane@old.com" in text
    assert "agent@x.com" not in text and "noted@x.com" not in text
