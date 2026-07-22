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
