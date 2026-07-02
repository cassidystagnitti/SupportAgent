from orchestrator import compute_tags


def test_auto_send_high_confidence():
    t = compute_tags({"auto_sendable": True, "confidence": "high", "escalate": False})
    assert "auto_send" in t and "automated" in t


def test_no_auto_send_when_low_confidence():
    t = compute_tags({"auto_sendable": True, "confidence": "low", "escalate": False})
    assert "auto_send" not in t


def test_not_auto_sendable():
    t = compute_tags({"auto_sendable": False, "confidence": "high", "escalate": False})
    assert "auto_send" not in t and "technical" in t


def test_escalation():
    assert "escalation" in compute_tags({"auto_sendable": False, "confidence": "low", "escalate": True})
