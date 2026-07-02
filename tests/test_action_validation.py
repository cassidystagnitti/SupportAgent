from orchestrator import needs_action_retry


def test_action_without_description_needs_retry():
    assert needs_action_retry({"needs_action": True, "action_description": None}) is True
    assert needs_action_retry({"needs_action": True, "action_description": "  "}) is True


def test_action_with_description_ok():
    assert needs_action_retry({"needs_action": True, "action_description": "Apply coupon to sub_1"}) is False


def test_no_action_ok():
    assert needs_action_retry({"needs_action": False, "action_description": None}) is False
