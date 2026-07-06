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


def test_confidence_tag_high():
    assert "confidence-high" in compute_tags({"auto_sendable": True, "confidence": "high", "escalate": False})


def test_confidence_tag_medium():
    assert "confidence-medium" in compute_tags({"auto_sendable": False, "confidence": "medium", "escalate": False})


def test_confidence_tag_low():
    assert "confidence-low" in compute_tags({"auto_sendable": False, "confidence": "low", "escalate": False})


def test_confidence_tag_normalizes_case_and_whitespace():
    assert "confidence-high" in compute_tags({"auto_sendable": True, "confidence": " High ", "escalate": False})


def test_no_confidence_tag_when_missing_or_unknown():
    assert not any(t.startswith("confidence-") for t in compute_tags({"auto_sendable": False, "escalate": False}))
    assert not any(t.startswith("confidence-") for t in compute_tags({"auto_sendable": False, "confidence": "", "escalate": False}))
