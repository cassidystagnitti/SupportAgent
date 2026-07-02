from orchestrator import detect_reply_mode


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
