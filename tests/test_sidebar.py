from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

import sidebar_chat
import sidebar_server


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setattr(sidebar_server, "SIDEBAR_SECRET", "testsecret")
    monkeypatch.setattr(sidebar_chat, "STORE", sidebar_chat.SessionStore())
    return TestClient(sidebar_server.app)


def test_chat_message_starts_turn(client):
    with patch("sidebar_server.threading.Thread") as t:
        resp = client.post("/chat/message", json={
            "conversation_id": "555", "text": "hi", "secret": "testsecret",
        })
    assert resp.status_code == 202
    t.assert_called_once()
    sess = sidebar_chat.STORE.peek("555")
    assert sess["busy"] is True  # acquired before the thread starts


def test_chat_message_bad_secret_401(client):
    resp = client.post("/chat/message", json={
        "conversation_id": "555", "text": "hi", "secret": "wrong",
    })
    assert resp.status_code == 401


def test_chat_message_busy_409(client):
    sidebar_chat.STORE.try_acquire("555")
    resp = client.post("/chat/message", json={
        "conversation_id": "555", "text": "hi", "secret": "testsecret",
    })
    assert resp.status_code == 409


def test_chat_message_validates_input(client):
    assert client.post("/chat/message", json={
        "conversation_id": "abc", "text": "hi", "secret": "testsecret",
    }).status_code == 400
    assert client.post("/chat/message", json={
        "conversation_id": "555", "text": "   ", "secret": "testsecret",
    }).status_code == 400


def test_poll_returns_messages_and_draft_state(client):
    sidebar_chat.STORE.get_or_create("555")
    sidebar_chat.STORE.add_ui_message("555", "user", "hi")
    sidebar_chat.STORE.add_ui_message("555", "bert", "hello")
    sess = sidebar_chat.STORE.peek("555")
    sess["draft_thread_id"] = 900

    resp = client.get("/chat/messages/555", params={"after": 1, "secret": "testsecret"})
    assert resp.status_code == 200
    data = resp.json()
    assert [m["seq"] for m in data["messages"]] == [2]
    assert data["busy"] is False
    assert data["draft"] == {"exists": True, "thread_id": 900}


def test_poll_requires_secret(client):
    assert client.get("/chat/messages/555", params={"after": 0}).status_code == 401


def test_poll_unknown_conversation_empty(client):
    resp = client.get("/chat/messages/999", params={"after": 0, "secret": "testsecret"})
    assert resp.json() == {"messages": [], "busy": False, "draft": None}


def test_draft_state_live_check(client):
    hs = MagicMock()
    with patch("sidebar_server.sidebar_chat._hs_session", return_value=hs), \
         patch("sidebar_server.bert_pipeline") as bp:
        bp.find_draft_threads.return_value = [901]
        resp = client.get("/chat/draft-state/555", params={"secret": "testsecret"})
    assert resp.status_code == 200
    assert resp.json() == {"exists": True, "thread_id": 901}


def test_draft_state_requires_secret(client):
    assert client.get("/chat/draft-state/555").status_code == 401


def test_poll_overlays_current_proposal_status(client):
    sidebar_chat.STORE.get_or_create("555")
    sess = sidebar_chat.STORE.peek("555")
    sess["proposals"]["p1"] = {"id": "p1", "status": "confirmed"}
    sidebar_chat.STORE.add_ui_message("555", "proposal", payload={
        "proposal_id": "p1", "diff": "+x", "rationale": "r", "status": "pending",
    })
    resp = client.get("/chat/messages/555", params={"after": 0, "secret": "testsecret"})
    msg = resp.json()["messages"][0]
    assert msg["payload"]["status"] == "confirmed"


def test_confirm_policy_happy_path(client):
    sidebar_chat.STORE.get_or_create("555")
    sess = sidebar_chat.STORE.peek("555")
    sess["proposals"]["p1"] = {"id": "p1", "policy_file": "refunds.md", "status": "pending"}
    with patch("sidebar_server.policy_updater.confirm_proposal",
               return_value={"commit_sha": "abcdef1234"}) as c:
        resp = client.post("/chat/confirm-policy", json={
            "conversation_id": "555", "proposal_id": "p1", "secret": "testsecret",
        })
    assert resp.status_code == 200
    assert resp.json()["commit_sha"] == "abcdef1234"
    c.assert_called_once()
    events = [m for m in sidebar_chat.STORE.ui_messages_after("555", 0) if m["kind"] == "event"]
    assert any("abcdef1" in m["text"] for m in events)


def test_confirm_policy_failure_returns_502_and_keeps_pending(client):
    sidebar_chat.STORE.get_or_create("555")
    sess = sidebar_chat.STORE.peek("555")
    sess["proposals"]["p1"] = {"id": "p1", "policy_file": "refunds.md", "status": "pending"}
    with patch("sidebar_server.policy_updater.confirm_proposal",
               side_effect=RuntimeError("gh down")):
        resp = client.post("/chat/confirm-policy", json={
            "conversation_id": "555", "proposal_id": "p1", "secret": "testsecret",
        })
    assert resp.status_code == 502
    assert sess["proposals"]["p1"]["status"] == "pending"


def test_confirm_policy_unknown_proposal_404(client):
    resp = client.post("/chat/confirm-policy", json={
        "conversation_id": "555", "proposal_id": "nope", "secret": "testsecret",
    })
    assert resp.status_code == 404


def test_confirm_policy_already_confirmed_409(client):
    sidebar_chat.STORE.get_or_create("555")
    sess = sidebar_chat.STORE.peek("555")
    sess["proposals"]["p1"] = {"id": "p1", "policy_file": "r.md", "status": "confirmed"}
    resp = client.post("/chat/confirm-policy", json={
        "conversation_id": "555", "proposal_id": "p1", "secret": "testsecret",
    })
    assert resp.status_code == 409


def test_dismiss_policy(client):
    sidebar_chat.STORE.get_or_create("555")
    sess = sidebar_chat.STORE.peek("555")
    sess["proposals"]["p1"] = {"id": "p1", "policy_file": "r.md", "status": "pending"}
    resp = client.post("/chat/dismiss-policy", json={
        "conversation_id": "555", "proposal_id": "p1", "secret": "testsecret",
    })
    assert resp.status_code == 200
    assert sess["proposals"]["p1"]["status"] == "dismissed"


def test_trigger_endpoints_are_gone(client):
    assert client.post("/trigger-draft", json={}).status_code == 404
    assert client.get("/trigger-status/1").status_code == 404


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


# --- Task 7: send & close ---


def _send_setup(sess_draft="<p>d</p>"):
    """Common context for /chat/send tests: mocked HS session + chat session."""
    hs = MagicMock()
    hs.patch.return_value = MagicMock(status_code=204, ok=True, raise_for_status=MagicMock())
    hs.put.return_value = MagicMock(status_code=204, ok=True, raise_for_status=MagicMock())
    sess = sidebar_chat.STORE.get_or_create("555")
    sess["draft_text"] = sess_draft
    p1 = patch("sidebar_server.sidebar_chat._hs_session", return_value=hs)
    p2 = patch("sidebar_server.bert_pipeline")
    return hs, p1, p2


def test_send_happy_path_publishes_then_closes(client):
    hs, p1, p2 = _send_setup()
    with p1, p2 as bp, patch("sidebar_server.sidebar_chat._thread_body", return_value="<p>d</p>"):
        bp.find_draft_threads.return_value = [900]
        bp.conversation_status.return_value = "active"
        resp = client.post("/chat/send", json={"conversation_id": "555", "secret": "testsecret"})
    assert resp.status_code == 200
    data = resp.json()
    assert data == {"ok": True, "sent": True, "closed": True}
    # Send is a two-step schedule dance: PUT a schedule, then PATCH publish.
    assert hs.put.call_count == 1
    put_url = hs.put.call_args_list[0][0][0]
    put_body = hs.put.call_args_list[0][1]["json"]
    assert put_url.endswith("/conversations/555/threads/900/schedule")
    assert put_body["scheduledFor"] and put_body["sendAsCreator"] is True
    urls = [c[0][0] for c in hs.patch.call_args_list]
    assert urls[0].endswith("/conversations/555/threads/900/schedule")
    assert urls[1].endswith("/conversations/555")
    assert hs.patch.call_args_list[0][1]["json"] == {"op": "replace", "path": "/state", "value": "published"}
    assert hs.patch.call_args_list[1][1]["json"] == {"op": "replace", "path": "/status", "value": "closed"}
    events = [m["text"] for m in sidebar_chat.STORE.ui_messages_after("555", 0) if m["kind"] == "event"]
    assert any("sent" in t.lower() for t in events)


def test_send_no_draft_400(client):
    hs, p1, p2 = _send_setup()
    with p1, p2 as bp:
        bp.find_draft_threads.return_value = []
        bp.conversation_status.return_value = "active"
        resp = client.post("/chat/send", json={"conversation_id": "555", "secret": "testsecret"})
    assert resp.status_code == 400
    assert "draft" in resp.json()["detail"].lower()


def test_send_already_closed_400(client):
    hs, p1, p2 = _send_setup()
    with p1, p2 as bp:
        bp.find_draft_threads.return_value = [900]
        bp.conversation_status.return_value = "closed"
        resp = client.post("/chat/send", json={"conversation_id": "555", "secret": "testsecret"})
    assert resp.status_code == 400
    assert "closed" in resp.json()["detail"].lower()


def test_send_draft_mismatch_409_and_force_overrides(client):
    hs, p1, p2 = _send_setup(sess_draft="<p>chat version</p>")
    with p1, p2 as bp, patch("sidebar_server.sidebar_chat._thread_body",
                             return_value="<p>edited by human</p>"):
        bp.find_draft_threads.return_value = [900]
        bp.conversation_status.return_value = "active"
        resp = client.post("/chat/send", json={"conversation_id": "555", "secret": "testsecret"})
        assert resp.status_code == 409
        resp2 = client.post("/chat/send", json={
            "conversation_id": "555", "secret": "testsecret", "force": True,
        })
        assert resp2.status_code == 200


def test_send_close_failure_reports_partial(client):
    hs, p1, p2 = _send_setup()
    publish_ok = MagicMock(status_code=204, raise_for_status=MagicMock())
    close_fail = MagicMock()
    close_fail.raise_for_status.side_effect = RuntimeError("HS 500")
    hs.patch.side_effect = [publish_ok, close_fail]
    with p1, p2 as bp, patch("sidebar_server.sidebar_chat._thread_body", return_value="<p>d</p>"):
        bp.find_draft_threads.return_value = [900]
        bp.conversation_status.return_value = "active"
        resp = client.post("/chat/send", json={"conversation_id": "555", "secret": "testsecret"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["sent"] is True and data["closed"] is False
    assert "error" in data


def test_send_publish_failure_surfaces_hs_error_not_500(client):
    """A rejected publish must surface Help Scout's reason as a clean 502,
    never an opaque 500, must cancel the schedule, and must NOT close."""
    hs, p1, p2 = _send_setup()
    publish_fail = MagicMock(status_code=400, ok=False)
    publish_fail.json.return_value = {
        "message": "The thread is not in a publishable state",
        "_embedded": {"errors": [{"path": "/state", "message": "invalid transition"}]},
    }
    publish_fail.text = '{"message": "The thread is not in a publishable state"}'
    hs.patch.return_value = publish_fail
    with p1, p2 as bp, patch("sidebar_server.sidebar_chat._thread_body", return_value="<p>d</p>"):
        bp.find_draft_threads.return_value = [900]
        bp.conversation_status.return_value = "active"
        resp = client.post("/chat/send", json={"conversation_id": "555", "secret": "testsecret"})
    assert resp.status_code == 502
    assert "publishable" in resp.json()["detail"].lower()
    # schedule created, publish attempted once, schedule cancelled, close skipped
    assert hs.put.call_count == 1
    assert hs.patch.call_count == 1
    assert hs.patch.call_args_list[0][0][0].endswith("/threads/900/schedule")
    assert hs.delete.call_count == 1
    assert hs.delete.call_args_list[0][0][0].endswith("/threads/900/schedule")


def test_send_schedule_failure_surfaces_hs_error_not_500(client):
    """If the scheduling PUT is rejected, surface it as a 502 and never attempt
    to publish or close."""
    hs, p1, p2 = _send_setup()
    sched_fail = MagicMock(status_code=400, ok=False)
    sched_fail.json.return_value = {"message": "scheduledFor must be in the future"}
    sched_fail.text = '{"message": "scheduledFor must be in the future"}'
    hs.put.return_value = sched_fail
    with p1, p2 as bp, patch("sidebar_server.sidebar_chat._thread_body", return_value="<p>d</p>"):
        bp.find_draft_threads.return_value = [900]
        bp.conversation_status.return_value = "active"
        resp = client.post("/chat/send", json={"conversation_id": "555", "secret": "testsecret"})
    assert resp.status_code == 502
    assert "future" in resp.json()["detail"].lower()
    assert hs.put.call_count == 1
    assert hs.patch.call_count == 0  # publish + close never attempted


def test_send_close_only_retry(client):
    hs, p1, p2 = _send_setup()
    with p1, p2 as bp:
        bp.find_draft_threads.return_value = []      # draft already published
        bp.conversation_status.return_value = "active"
        resp = client.post("/chat/send", json={
            "conversation_id": "555", "secret": "testsecret", "close_only": True,
        })
    assert resp.status_code == 200
    assert resp.json()["closed"] is True
    urls = [c[0][0] for c in hs.patch.call_args_list]
    assert len(urls) == 1 and urls[0].endswith("/conversations/555")


def test_send_mismatch_check_skipped_when_no_session_draft(client):
    hs, p1, p2 = _send_setup(sess_draft="")
    with p1, p2 as bp:
        bp.find_draft_threads.return_value = [900]
        bp.conversation_status.return_value = "active"
        resp = client.post("/chat/send", json={"conversation_id": "555", "secret": "testsecret"})
    assert resp.status_code == 200


# --- Task 8: static sidebar serving ---


def test_sidebar_get_serves_static_html_with_injection(client):
    resp = client.get("/sidebar", params={"id": "123", "customer_email": "a@b.com"})
    assert resp.status_code == 200
    html = resp.text
    assert '"123"' in html
    assert "GET_APP_CONTEXT" in html          # handshake preserved
    assert "secure.helpscout.net" in html     # origin allowlist preserved
    assert "/chat/message" in html            # chat wiring present
    assert "__CID__" not in html              # injection happened


def test_sidebar_post_form_context(client):
    resp = client.post("/sidebar", data={"conversation[id]": "456", "customer[email]": "c@d.com"})
    assert resp.status_code == 200
    assert '"456"' in resp.text


def test_sidebar_post_rejects_missing_cid(client):
    resp = client.post("/sidebar", data={})
    assert resp.status_code == 400


def test_root_aliases_serve_sidebar(client):
    resp = client.get("/", params={"id": "123"})
    assert resp.status_code == 200
    assert "GET_APP_CONTEXT" in resp.text
    resp = client.post("/", data={"conversation[id]": "456", "customer[email]": "c@d.com"})
    assert resp.status_code == 200
    assert '"456"' in resp.text
