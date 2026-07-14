from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

import sidebar_chat
from sidebar_chat import SessionStore


# --- Task 3: SessionStore ---


def test_get_or_create_initializes_session():
    s = SessionStore()
    sess = s.get_or_create("101")
    assert sess["busy"] is False
    assert sess["ctx"] is None
    assert sess["proposals"] == {}
    assert s.get_or_create("101") is sess  # same object back


def test_lru_eviction():
    s = SessionStore(max_sessions=2)
    s.get_or_create("1")
    s.get_or_create("2")
    s.get_or_create("1")   # touch 1 so 2 is oldest
    s.get_or_create("3")   # evicts 2
    assert s.peek("2") is None
    assert s.peek("1") is not None
    assert s.peek("3") is not None


def test_try_acquire_and_release():
    s = SessionStore()
    _, ok1 = s.try_acquire("7")
    _, ok2 = s.try_acquire("7")
    assert ok1 is True
    assert ok2 is False
    s.release("7")
    _, ok3 = s.try_acquire("7")
    assert ok3 is True


def test_ui_messages_sequence_and_after():
    s = SessionStore()
    s.get_or_create("5")
    m1 = s.add_ui_message("5", "user", "hi")
    m2 = s.add_ui_message("5", "bert", "hello")
    assert (m1["seq"], m2["seq"]) == (1, 2)
    tail = s.ui_messages_after("5", after=1)
    assert [m["seq"] for m in tail] == [2]
    assert s.ui_messages_after("5", after=0)[0]["text"] == "hi"
    assert s.ui_messages_after("nope", after=0) == []


def test_add_ui_message_payload_roundtrip():
    s = SessionStore()
    s.get_or_create("9")
    m = s.add_ui_message("9", "proposal", payload={"proposal_id": "abc", "status": "pending"})
    assert m["payload"]["proposal_id"] == "abc"
    assert m["kind"] == "proposal"


# --- Task 4: hydration + context block ---


CTX = {
    "conversation_id": 555,
    "subject": "Refund please",
    "customer_name": "Ana",
    "hs_customer_id": 42,
    "email": "ana@x.com",
    "body": "I want a refund",
    "conversation_history": "",
    "reply_mode": False,
    "account_blob": "ACCOUNT-DATA",
    "stripe_block": "STRIPE-DATA",
    "stripe_ctx": None,
    "existing_tags": [],
}


def test_hydrate_fills_ctx_draft_and_text():
    sess = {"ctx": None, "draft_thread_id": None, "draft_text": ""}
    threads = [
        {"id": 900, "type": "message", "state": "draft", "body": "<p>draft body</p>"},
        {"id": 800, "type": "customer", "state": "published", "body": "hi"},
    ]
    with patch("sidebar_chat._hs_session", return_value=MagicMock()), \
         patch("sidebar_chat.bert_pipeline") as bp, \
         patch("sidebar_chat.triage_tickets") as tt:
        bp.hydrate_ticket.return_value = dict(CTX)
        bp.find_draft_threads.return_value = [900]
        tt._fetch_all_threads.return_value = threads
        sidebar_chat.hydrate(sess, "555")
    assert sess["ctx"]["subject"] == "Refund please"
    assert sess["draft_thread_id"] == 900
    assert sess["draft_text"] == "<p>draft body</p>"


def test_hydrate_no_draft():
    sess = {"ctx": None, "draft_thread_id": None, "draft_text": ""}
    with patch("sidebar_chat._hs_session", return_value=MagicMock()), \
         patch("sidebar_chat.bert_pipeline") as bp:
        bp.hydrate_ticket.return_value = dict(CTX)
        bp.find_draft_threads.return_value = []
        sidebar_chat.hydrate(sess, "555")
    assert sess["draft_thread_id"] is None
    assert sess["draft_text"] == ""


def test_context_block_contains_all_sections():
    sess = {"ctx": dict(CTX), "draft_thread_id": 900, "draft_text": "<p>d</p>"}
    block = sidebar_chat._context_block(sess)
    for expected in ("Refund please", "ana@x.com", "ACCOUNT-DATA", "STRIPE-DATA", "<p>d</p>"):
        assert expected in block


def test_context_block_no_draft_placeholder():
    sess = {"ctx": dict(CTX), "draft_thread_id": None, "draft_text": ""}
    assert "(no draft yet)" in sidebar_chat._context_block(sess)


def test_load_chat_prompt_reads_file():
    text = sidebar_chat._load_chat_prompt()
    assert "update_draft" in text
    assert "propose_policy_update" in text


def test_agent_user_id_fallback(monkeypatch):
    monkeypatch.delenv("HELPSCOUT_AGENT_USER_ID", raising=False)
    monkeypatch.setenv("HELPSCOUT_NOTE_USER_ID", "777")
    assert sidebar_chat._agent_user_id() == 777
    monkeypatch.setenv("HELPSCOUT_AGENT_USER_ID", "888")
    assert sidebar_chat._agent_user_id() == 888
    monkeypatch.delenv("HELPSCOUT_AGENT_USER_ID", raising=False)
    monkeypatch.delenv("HELPSCOUT_NOTE_USER_ID", raising=False)
    assert sidebar_chat._agent_user_id() is None


# --- Task 5: tools + run_turn loop ---


def _text_block(text):
    return SimpleNamespace(type="text", text=text)


def _tool_block(name, tool_input, block_id="tu_1"):
    return SimpleNamespace(type="tool_use", name=name, input=tool_input, id=block_id)


class FakeClient:
    """Yields queued fake responses; records requests."""
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []
        outer = self

        class _Messages:
            def create(self, **kwargs):
                outer.calls.append(kwargs)
                return outer._responses.pop(0)

        self.messages = _Messages()


def _store_with_hydrated_session(cid="555", thread_id=900):
    store = SessionStore()
    sess = store.get_or_create(cid)
    sess["ctx"] = dict(CTX)
    sess["draft_thread_id"] = thread_id
    sess["draft_text"] = "<p>old</p>"
    sess["busy"] = True  # run_turn expects the busy flag already held
    return store, sess


def test_run_turn_plain_text_reply():
    store, sess = _store_with_hydrated_session()
    client = FakeClient([SimpleNamespace(content=[_text_block("Because policy X.")])])
    with patch("sidebar_chat.orchestrator") as o:
        o.load_policy_docs.return_value = "POLICIES"
        sidebar_chat.run_turn(store, "555", "why does the draft say that?", client=client)
    kinds = [m["kind"] for m in store.ui_messages_after("555", 0)]
    assert kinds == ["user", "bert"]
    assert sess["busy"] is False
    # system blocks: prompt (cached), policies (cached), context (uncached)
    system = client.calls[0]["system"]
    assert len(system) == 3
    assert system[0]["cache_control"] == {"type": "ephemeral"}
    assert system[1]["cache_control"] == {"type": "ephemeral"}
    assert "cache_control" not in system[2]


def test_run_turn_update_existing_draft():
    store, sess = _store_with_hydrated_session()
    client = FakeClient([
        SimpleNamespace(content=[_tool_block("update_draft", {"html": "<p>new</p>"})]),
        SimpleNamespace(content=[_text_block("Done — draft updated.")]),
    ])
    with patch("sidebar_chat.orchestrator") as o, \
         patch("sidebar_chat.bert_pipeline") as bp, \
         patch("sidebar_chat._hs_session", return_value=MagicMock()):
        o.load_policy_docs.return_value = "P"
        sidebar_chat.run_turn(store, "555", "shorten the draft", client=client)
        bp.update_draft.assert_called_once()
        args = bp.update_draft.call_args[0]
        assert args[1] == 555 and args[2] == 900 and args[3] == "<p>new</p>"
    assert sess["draft_text"] == "<p>new</p>"
    kinds = [m["kind"] for m in store.ui_messages_after("555", 0)]
    assert "event" in kinds  # "Draft updated" chip


def test_run_turn_creates_draft_with_agent_user(monkeypatch):
    monkeypatch.setenv("HELPSCOUT_AGENT_USER_ID", "321")
    store, sess = _store_with_hydrated_session(thread_id=None)
    sess["draft_text"] = ""
    client = FakeClient([
        SimpleNamespace(content=[_tool_block("update_draft", {"html": "<p>fresh</p>"})]),
        SimpleNamespace(content=[_text_block("Drafted.")]),
    ])
    post_resp = MagicMock()
    post_resp.headers = {"Resource-ID": "1234"}
    with patch("sidebar_chat.orchestrator") as o, \
         patch("sidebar_chat._hs_session", return_value=MagicMock()), \
         patch("sidebar_chat.draft_registry") as reg:
        o.load_policy_docs.return_value = "P"
        o.BASE_URL = "https://api.helpscout.net/v2"
        o._helpscout_post.return_value = post_resp
        sidebar_chat.run_turn(store, "555", "draft a reply", client=client)
        payload = o._helpscout_post.call_args[0][2]
        assert payload["draft"] is True
        assert payload["user"] == 321
        assert payload["customer"] == {"id": 42}
        reg.set.assert_called_once()
    assert sess["draft_thread_id"] == "1234"


def test_run_turn_proposal_registered_not_applied():
    store, sess = _store_with_hydrated_session()
    client = FakeClient([
        SimpleNamespace(content=[_tool_block("propose_policy_update", {
            "policy_file": "refunds.md", "edit_type": "append",
            "new_text": "new fact", "rationale": "settled in chat",
        })]),
        SimpleNamespace(content=[_text_block("Proposed — waiting for your confirm.")]),
    ])
    with patch("sidebar_chat.orchestrator") as o, \
         patch("sidebar_chat.policy_updater") as pu:
        o.load_policy_docs.return_value = "P"
        pu.build_proposal.return_value = {
            "id": "abc123", "policy_file": "refunds.md", "edit_type": "append",
            "target_text": "", "new_text": "new fact", "rationale": "settled in chat",
            "diff": "+new fact", "status": "pending",
        }
        pu.ProposalError = Exception
        sidebar_chat.run_turn(store, "555", "update the policy", client=client)
    assert "abc123" in sess["proposals"]
    proposal_msgs = [m for m in store.ui_messages_after("555", 0) if m["kind"] == "proposal"]
    assert len(proposal_msgs) == 1
    assert proposal_msgs[0]["payload"]["proposal_id"] == "abc123"


def test_run_turn_tool_exception_reported_and_busy_released():
    store, sess = _store_with_hydrated_session()
    client = FakeClient([
        SimpleNamespace(content=[_tool_block("update_draft", {"html": "<p>x</p>"})]),
        SimpleNamespace(content=[_text_block("Sorry, that failed.")]),
    ])
    with patch("sidebar_chat.orchestrator") as o, \
         patch("sidebar_chat.bert_pipeline") as bp, \
         patch("sidebar_chat._hs_session", return_value=MagicMock()):
        o.load_policy_docs.return_value = "P"
        bp.update_draft.side_effect = RuntimeError("HS down")
        sidebar_chat.run_turn(store, "555", "edit", client=client)
    assert sess["busy"] is False
    assert any(m["kind"] == "error" for m in store.ui_messages_after("555", 0))


def test_run_turn_iteration_cap():
    store, sess = _store_with_hydrated_session()
    responses = [
        SimpleNamespace(content=[_tool_block("update_draft", {"html": f"<p>{i}</p>"}, f"tu_{i}")])
        for i in range(sidebar_chat.MAX_TOOL_ITERATIONS)
    ]
    client = FakeClient(responses)
    with patch("sidebar_chat.orchestrator") as o, \
         patch("sidebar_chat.bert_pipeline"), \
         patch("sidebar_chat._hs_session", return_value=MagicMock()):
        o.load_policy_docs.return_value = "P"
        sidebar_chat.run_turn(store, "555", "loop forever", client=client)
    msgs = store.ui_messages_after("555", 0)
    assert any(m["kind"] == "error" and "tool steps" in m["text"] for m in msgs)
    assert sess["busy"] is False


def test_run_turn_hydrates_when_ctx_missing():
    store = SessionStore()
    sess = store.get_or_create("777")
    sess["busy"] = True
    client = FakeClient([SimpleNamespace(content=[_text_block("hi")])])

    def fake_hydrate(session_data, cid):
        session_data["ctx"] = dict(CTX)
        session_data["draft_thread_id"] = None
        session_data["draft_text"] = ""

    with patch("sidebar_chat.orchestrator") as o, \
         patch("sidebar_chat.hydrate", side_effect=fake_hydrate) as h:
        o.load_policy_docs.return_value = "P"
        sidebar_chat.run_turn(store, "777", "hello", client=client)
        h.assert_called_once()
    assert sess["ctx"] is not None


def test_run_turn_top_level_failure_reports_error():
    store = SessionStore()
    sess = store.get_or_create("888")
    sess["busy"] = True
    with patch("sidebar_chat.hydrate", side_effect=RuntimeError("HS auth failed")):
        sidebar_chat.run_turn(store, "888", "hello", client=FakeClient([]))
    assert sess["busy"] is False
    msgs = store.ui_messages_after("888", 0)
    assert any(m["kind"] == "error" for m in msgs)
    assert sess["ctx"] is None  # next message retries hydration
