import triage_tickets
from orchestrator import detect_reply_mode
from triage_tickets import get_conversation_history, get_conversation_text


def test_new_conversation_is_not_reply():
    threads = [{"type": "customer", "state": "published"}]
    assert detect_reply_mode(threads) is False


def test_agent_reply_makes_it_reply_mode():
    threads = [{"type": "customer", "state": "published"},
               {"type": "message", "state": "published"},
               {"type": "customer", "state": "published"}]
    assert detect_reply_mode(threads) is True


def test_draft_agent_message_does_not_count():
    threads = [{"type": "customer", "state": "published"},
               {"type": "message", "state": "draft"}]
    assert detect_reply_mode(threads) is False


def test_notes_do_not_count():
    threads = [{"type": "customer", "state": "published"},
               {"type": "note", "state": "published"}]
    assert detect_reply_mode(threads) is False


def test_passing_threads_avoids_refetch(monkeypatch):
    """get_conversation_text/get_conversation_history must use pre-fetched
    threads when provided, instead of calling _fetch_all_threads again."""

    def _boom(session, conversation_id):
        raise AssertionError("_fetch_all_threads should not be called when threads are provided")

    monkeypatch.setattr(triage_tickets, "_fetch_all_threads", _boom)

    # Help Scout returns threads newest-first.
    threads = [
        {"type": "customer", "state": "published", "body": "Latest customer message"},
        {"type": "message", "state": "published", "body": "Support reply"},
        {"type": "customer", "state": "published", "body": "Older message"},
    ]

    text = get_conversation_text(session=None, conversation_id=123, threads=threads)
    assert text == "Older message"

    history, latest = get_conversation_history(session=None, conversation_id=123, threads=threads)
    assert latest == "Latest customer message"
    assert "Support reply" in history
