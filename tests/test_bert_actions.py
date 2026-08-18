from __future__ import annotations

from types import SimpleNamespace

import pytest
import stripe

import sidebar_chat
from bert import actions
from bert import mcp_tools


def eligible_sub(**overrides):
    base = {
        "id": "sub_1",
        "status": "active",
        "cancel_at_period_end": False,
        "cancel_at": None,
        "pause_collection": None,
        "schedule": None,
        "metadata": {},
        "discount": None,
        "discounts": [],
        "current_period_end": 1_790_000_000,
        "items": {"data": [{"current_period_end": 1_790_000_000}]},
    }
    base.update(overrides)
    return base


APPLIED_RESULT = {
    "action": "cancel_at_period_end",
    "customer_id": "cus_1",
    "subscription_id": "sub_1",
    "conversation_id": "3391134628",
    "actor": "sidebar:9",
    "released_schedule": None,
    "access_continues_through": "July 31, 2026",
    "executed_at": "2026-07-22T00:00:00+00:00",
}


def wire_executor(monkeypatch, subs, execute_result=None):
    """Stub the CLI-module boundary the executor drives, plus the HS note."""
    calls = {"execute": [], "notes": []}
    monkeypatch.setattr(actions.cancel_script, "write_gates_ok", lambda: (True, ""))
    monkeypatch.setattr(actions.cancel_script, "_configure_stripe_key", lambda apply: None)
    monkeypatch.setattr(actions.cancel_script, "_fetch_customer",
                        lambda cid: {"id": cid, "email": "a@b.c"})
    monkeypatch.setattr(actions.cancel_script, "_fetch_subscriptions", lambda cid: subs)

    def fake_execute(plan, conversation_id, actor=None):
        calls["execute"].append((plan, conversation_id, actor))
        return dict(execute_result or APPLIED_RESULT, actor=actor or "cli")

    monkeypatch.setattr(actions.cancel_script, "execute_plan", fake_execute)
    monkeypatch.setattr(actions, "_post_executed_note",
                        lambda cid, result, hs=None: calls["notes"].append(cid) or True)
    return calls


# --- executor: bert.actions.cancel_subscription ----------------------------

def test_rejects_bad_customer_id():
    got = actions.cancel_subscription("sub_123", "3391134628", actor="mcp")
    assert got["status"] == "error" and "customer ID" in got["reason"]


def test_requires_conversation_id():
    got = actions.cancel_subscription("cus_1", "", actor="mcp")
    assert got["status"] == "error" and "conversation" in got["reason"]


def test_gates_down_returns_disabled_without_stripe_calls(monkeypatch):
    monkeypatch.setattr(actions.cancel_script, "write_gates_ok",
                        lambda: (False, "STRIPE_WRITE_API_KEY is not set"))
    monkeypatch.setattr(actions.cancel_script, "_fetch_customer",
                        lambda cid: pytest.fail("stripe touched with gates down"))
    got = actions.cancel_subscription("cus_1", "3391134628", actor="sidebar:9")
    assert got["status"] == "disabled"
    assert "NOT performed" in got["reason"]


def test_applied_flow_passes_actor_and_posts_note(monkeypatch):
    calls = wire_executor(monkeypatch, [eligible_sub()])
    got = actions.cancel_subscription("cus_1", "3391134628", actor="sidebar:9")
    assert got["status"] == "applied"
    assert got["actor"] == "sidebar:9"
    assert got["note_posted"] is True
    assert calls["execute"][0][1] == "3391134628"
    assert calls["execute"][0][2] == "sidebar:9"
    assert calls["notes"] == ["3391134628"]
    assert isinstance(got["notes"], list)


def test_already_off_is_noop_without_execution(monkeypatch):
    calls = wire_executor(monkeypatch, [eligible_sub(cancel_at_period_end=True)])
    got = actions.cancel_subscription("cus_1", "3391134628", actor="mcp")
    assert got["status"] == "already_off"
    assert calls["execute"] == [] and calls["notes"] == []


def test_multiple_eligible_refused(monkeypatch):
    calls = wire_executor(monkeypatch, [eligible_sub(id="sub_1"), eligible_sub(id="sub_2")])
    got = actions.cancel_subscription("cus_1", "3391134628", actor="mcp")
    assert got["status"] == "refused" and "2 subscriptions" in got["reason"]
    assert calls["execute"] == []


def test_stripe_error_becomes_structured_error(monkeypatch):
    wire_executor(monkeypatch, [eligible_sub()])
    def boom(cid):
        raise stripe.error.StripeError("kaboom")
    monkeypatch.setattr(actions.cancel_script, "_fetch_subscriptions", boom)
    got = actions.cancel_subscription("cus_1", "3391134628", actor="mcp")
    assert got["status"] == "error" and "kaboom" in got["reason"]


def test_system_exit_from_cli_helpers_is_caught(monkeypatch):
    wire_executor(monkeypatch, [eligible_sub()])
    def deleted(cid):
        raise SystemExit("ERROR: customer cus_1 is deleted in Stripe.")
    monkeypatch.setattr(actions.cancel_script, "_fetch_customer", deleted)
    got = actions.cancel_subscription("cus_1", "3391134628", actor="mcp")
    assert got["status"] == "error" and "deleted" in got["reason"]


def test_executed_note_html_escapes_and_includes_fields():
    html = actions._executed_note_html(dict(APPLIED_RESULT, subscription_id="sub_<x>"))
    assert "sub_&lt;x&gt;" in html
    assert "July 31, 2026" in html and "sidebar:9" in html
    assert "Action executed" in html


# --- sidebar handler --------------------------------------------------------

def make_store_and_session(stripe_customer=None):
    store = sidebar_chat.SessionStore()
    session_data = store.get_or_create("3391134628")
    session_data["ctx"] = {
        "conversation_id": 3391134628,
        "stripe_ctx": {"stripe_customer_id": stripe_customer} if stripe_customer else None,
    }
    return store, session_data


def ui_texts(store, cid="3391134628"):
    return [m.get("text") or "" for m in store.ui_messages_after(cid, after=0)]


def test_sidebar_handler_without_stripe_customer_never_executes(monkeypatch):
    monkeypatch.setattr(sidebar_chat.bert_actions, "cancel_subscription",
                        lambda *a, **k: pytest.fail("executed without a customer"))
    store, session_data = make_store_and_session(stripe_customer=None)
    out = sidebar_chat._handle_cancel_subscription(store, "3391134628", session_data)
    assert "cannot execute" in out


def test_sidebar_handler_applied_instructs_draft_update(monkeypatch):
    seen = {}
    def fake(customer_id, cid, actor):
        seen.update(customer_id=customer_id, cid=cid, actor=actor)
        return dict(APPLIED_RESULT, status="applied", notes=["note a"], note_posted=True)
    monkeypatch.setattr(sidebar_chat.bert_actions, "cancel_subscription", fake)
    monkeypatch.setenv("HELPSCOUT_AGENT_USER_ID", "9")

    store, session_data = make_store_and_session(stripe_customer="cus_1")
    out = sidebar_chat._handle_cancel_subscription(store, "3391134628", session_data)

    assert seen == {"customer_id": "cus_1", "cid": "3391134628", "actor": "sidebar:9"}
    assert "update the draft" in out
    assert "July 31, 2026" in out
    assert any("Auto-renew turned off" in t for t in ui_texts(store))


def test_sidebar_handler_refusal_is_honest(monkeypatch):
    monkeypatch.setattr(sidebar_chat.bert_actions, "cancel_subscription",
                        lambda *a, **k: {"status": "refused", "reason": "2 subscriptions are eligible"})
    store, session_data = make_store_and_session(stripe_customer="cus_1")
    out = sidebar_chat._handle_cancel_subscription(store, "3391134628", session_data)
    assert "NOT executed" in out and "2 subscriptions" in out
    assert any("not executed" in t.lower() for t in ui_texts(store))


def test_sidebar_tool_registered_with_no_model_inputs():
    tool = next(t for t in sidebar_chat.TOOLS if t["name"] == "cancel_subscription")
    assert tool["input_schema"]["properties"] == {}


def test_run_turn_dispatches_cancel_tool(monkeypatch):
    monkeypatch.setattr(sidebar_chat.bert_actions, "cancel_subscription",
                        lambda *a, **k: dict(APPLIED_RESULT, status="applied", notes=[], note_posted=True))

    tool_block = SimpleNamespace(type="tool_use", name="cancel_subscription", input={}, id="tu_1")
    done_block = SimpleNamespace(type="text", text="Done — draft updated.")

    class FakeClient:
        def __init__(self):
            self.calls = 0
            outer = self

            class _Messages:
                def create(self, **kwargs):
                    outer.calls += 1
                    outer.last_kwargs = kwargs
                    if outer.calls == 1:
                        return SimpleNamespace(content=[tool_block])
                    return SimpleNamespace(content=[done_block])

            self.messages = _Messages()

    store = sidebar_chat.SessionStore()
    session_data = store.get_or_create("3391134628")
    session_data["ctx"] = {
        "conversation_id": 3391134628, "subject": "Cancel please",
        "customer_name": "A", "email": "a@b.c", "reply_mode": False,
        "conversation_history": "hi", "body": "hi", "account_blob": "",
        "stripe_block": "", "stripe_ctx": {"stripe_customer_id": "cus_1"},
    }
    store.try_acquire("3391134628")
    sidebar_chat.run_turn(store, "3391134628", "cancel the subscription", client=FakeClient())

    tool_results = [
        blk for msg in session_data["api_messages"] if isinstance(msg.get("content"), list)
        for blk in msg["content"] if isinstance(blk, dict) and blk.get("type") == "tool_result"
    ]
    assert tool_results and "auto-renew is OFF" in tool_results[0]["content"]


# --- MCP adapter -------------------------------------------------------------

def test_mcp_cancel_resolves_customer_server_side(monkeypatch):
    monkeypatch.setattr(mcp_tools, "_hs_session", lambda: "hs-session")
    monkeypatch.setattr(mcp_tools.bert_pipeline, "hydrate_ticket",
                        lambda hs, cid: {"stripe_ctx": {"stripe_customer_id": "cus_77"}})
    seen = {}
    def fake(customer_id, cid, actor, hs=None):
        seen.update(customer_id=customer_id, cid=cid, actor=actor, hs=hs)
        return {"status": "applied"}
    monkeypatch.setattr(mcp_tools.bert_actions, "cancel_subscription", fake)

    got = mcp_tools.cancel_subscription(3391134628)
    assert got == {"status": "applied"}
    assert seen == {"customer_id": "cus_77", "cid": "3391134628", "actor": "mcp", "hs": "hs-session"}


def test_mcp_cancel_refuses_without_stripe_customer(monkeypatch):
    monkeypatch.setattr(mcp_tools, "_hs_session", lambda: "hs-session")
    monkeypatch.setattr(mcp_tools.bert_pipeline, "hydrate_ticket",
                        lambda hs, cid: {"stripe_ctx": None})
    monkeypatch.setattr(mcp_tools.bert_actions, "cancel_subscription",
                        lambda *a, **k: pytest.fail("must not execute"))
    got = mcp_tools.cancel_subscription(3391134628)
    assert got["status"] == "refused" and "Apple/Google" in got["reason"]


# --- reactivate_subscription rails ------------------------------------------

def cancelling_sub(**overrides):
    return eligible_sub(cancel_at_period_end=True,
                        items={"data": [{"current_period_end": 4_000_000_000,
                                         "price": {"unit_amount": 9999, "currency": "usd"}}]},
                        current_period_end=4_000_000_000, **overrides)


def _arm_write_gates(monkeypatch):
    monkeypatch.setenv("STRIPE_WRITE_API_KEY", "rk_live_x")
    monkeypatch.setenv("ACTION_EXECUTION_ENABLED", "true")


def test_reactivate_rejects_a_non_customer_id():
    got = actions.reactivate_subscription("sub_1", "3390692208", actor="test")
    assert got["status"] == "error" and "customer ID" in got["reason"]


def test_reactivate_requires_a_conversation_id():
    got = actions.reactivate_subscription("cus_ABC", "", actor="test")
    assert got["status"] == "error" and "conversation id" in got["reason"]


def test_reactivate_is_disabled_without_the_gates(monkeypatch):
    monkeypatch.delenv("STRIPE_WRITE_API_KEY", raising=False)
    monkeypatch.delenv("ACTION_EXECUTION_ENABLED", raising=False)
    got = actions.reactivate_subscription("cus_ABC", "3390692208", actor="test")
    assert got["status"] == "disabled"
    assert "NOT performed" in got["reason"]


def test_reactivate_applies_and_posts_the_audit_note(monkeypatch):
    _arm_write_gates(monkeypatch)
    notes = []
    monkeypatch.setattr(actions.reactivate_script, "_configure_stripe_key", lambda apply: None)
    monkeypatch.setattr(actions.reactivate_script, "_fetch_customer",
                        lambda cid: {"id": cid, "email": "a@b.com"})
    monkeypatch.setattr(actions.reactivate_script, "_fetch_subscriptions",
                        lambda cid: [cancelling_sub()])
    monkeypatch.setattr(actions.reactivate_script, "execute_plan",
                        lambda plan, cid, actor=None: {"subscription_id": plan["subscription_id"],
                                                       "renews_on": "June 1, 2027",
                                                       "renewal_amount_display": "$99.99",
                                                       "actor": actor})
    monkeypatch.setattr(actions, "_post_executed_note",
                        lambda cid, result, hs=None, render=None: notes.append(render(result)) or True)

    got = actions.reactivate_subscription("cus_ABC", "3390692208", actor="mcp")
    assert got["status"] == "applied"
    assert got["renews_on"] == "June 1, 2027"
    assert "back ON" in notes[0] and "stripe_reactivate_subscription" in notes[0]


def test_reactivate_reports_already_renewing(monkeypatch):
    _arm_write_gates(monkeypatch)
    monkeypatch.setattr(actions.reactivate_script, "_configure_stripe_key", lambda apply: None)
    monkeypatch.setattr(actions.reactivate_script, "_fetch_customer", lambda cid: {"id": cid})
    monkeypatch.setattr(actions.reactivate_script, "_fetch_subscriptions",
                        lambda cid: [eligible_sub()])

    got = actions.reactivate_subscription("cus_ABC", "3390692208", actor="test")
    assert got["status"] == "already_on"


def test_reactivate_relays_a_refusal(monkeypatch):
    _arm_write_gates(monkeypatch)
    monkeypatch.setattr(actions.reactivate_script, "_configure_stripe_key", lambda apply: None)
    monkeypatch.setattr(actions.reactivate_script, "_fetch_customer", lambda cid: {"id": cid})
    monkeypatch.setattr(actions.reactivate_script, "_fetch_subscriptions",
                        lambda cid: [cancelling_sub(status="canceled")])

    got = actions.reactivate_subscription("cus_ABC", "3390692208", actor="test")
    assert got["status"] == "refused" and "already ENDED" in got["reason"]


def test_reactivate_never_raises_into_the_chat_turn(monkeypatch):
    _arm_write_gates(monkeypatch)
    monkeypatch.setattr(actions.reactivate_script, "_configure_stripe_key", lambda apply: None)

    def _boom(cid):
        raise RuntimeError("stripe exploded")

    monkeypatch.setattr(actions.reactivate_script, "_fetch_customer", _boom)
    got = actions.reactivate_subscription("cus_ABC", "3390692208", actor="test")
    assert got["status"] == "error"


# --- link_customer_email rails ----------------------------------------------

class _IdentityHS:
    def __init__(self, existing=(), owner=None):
        self.existing = [{"id": i, "value": v, "type": "home"}
                         for i, v in enumerate(existing, start=1)]
        self.owner = owner


def _patch_identity(monkeypatch, hs, *, owner=None, added=None, merged=None):
    added = [] if added is None else added
    merged = {} if merged is None else merged
    monkeypatch.setattr(actions.helpscout_identity, "list_customer_emails",
                        lambda s, cid: hs.existing)
    monkeypatch.setattr(actions.helpscout_identity, "find_customer_by_email",
                        lambda s, email: owner)
    monkeypatch.setattr(actions.helpscout_identity, "add_email",
                        lambda s, cid, email: added.append((cid, email)))
    monkeypatch.setattr(actions.helpscout_identity, "audit", lambda entry: None)
    monkeypatch.setattr(actions.helpscout_identity, "merge_contacts",
                        lambda s, keep_id, dup_id, conversation_id, actor: merged)


def test_link_email_refuses_a_role_address():
    got = actions.link_customer_email("3390692208", "support@acme.com", 1, actor="test",
                                      hs=object())
    assert got["status"] == "refused" and "role address" in got["reason"]


def test_link_email_refuses_our_own_domain():
    got = actions.link_customer_email("3390692208", "cassidy@meditatehappier.com", 1,
                                      actor="test", hs=object())
    assert got["status"] == "refused"


def test_link_email_needs_a_conversation_id():
    got = actions.link_customer_email("", "a@b.com", 1, actor="test", hs=object())
    assert got["status"] == "error"


def test_link_email_honours_the_deployment_switch(monkeypatch):
    monkeypatch.setenv("HELPSCOUT_IDENTITY_WRITES", "false")
    got = actions.link_customer_email("3390692208", "a@b.com", 1, actor="test", hs=object())
    assert got["status"] == "disabled" and "Help Scout UI" in got["reason"]


def test_link_email_attaches_when_unowned(monkeypatch):
    monkeypatch.delenv("HELPSCOUT_IDENTITY_WRITES", raising=False)
    added = []
    _patch_identity(monkeypatch, _IdentityHS(existing=["jane@example.net"]), added=added)

    got = actions.link_customer_email("3390692208", "Jane@Old.com ", 1, actor="test", hs=object())
    assert got["status"] == "linked" and got["already_present"] is False
    assert added == [(1, "jane@old.com")]


def test_link_email_is_idempotent(monkeypatch):
    monkeypatch.delenv("HELPSCOUT_IDENTITY_WRITES", raising=False)
    added = []
    _patch_identity(monkeypatch, _IdentityHS(existing=["jane@old.com"]), added=added)

    got = actions.link_customer_email("3390692208", "jane@old.com", 1, actor="test", hs=object())
    assert got["status"] == "linked" and got["already_present"] is True
    assert added == []


def test_link_email_merges_a_conflicting_contact(monkeypatch):
    monkeypatch.delenv("HELPSCOUT_IDENTITY_WRITES", raising=False)
    _patch_identity(
        monkeypatch, _IdentityHS(existing=["jane@example.net"]),
        owner={"id": 2},
        merged={"keep_id": 1, "dup_id": 2, "conversations_moved": [7, 8],
                "emails_moved": ["jane@old.com"], "errors": []},
    )
    got = actions.link_customer_email("3390692208", "jane@old.com", 1, actor="test", hs=object())
    assert got["status"] == "merged" and got["conversations_moved"] == [7, 8]


def test_link_email_never_raises(monkeypatch):
    monkeypatch.delenv("HELPSCOUT_IDENTITY_WRITES", raising=False)

    def _boom(*a, **k):
        raise RuntimeError("help scout is down")

    monkeypatch.setattr(actions.helpscout_identity, "list_customer_emails", _boom)
    got = actions.link_customer_email("3390692208", "a@b.com", 1, actor="test", hs=object())
    assert got["status"] == "error"
