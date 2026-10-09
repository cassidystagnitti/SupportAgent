"""--mitigated-grace window math (decision 2026-10-09): annual only, +5 days max."""
import importlib
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
sr = importlib.import_module("stripe_refund")

DAY = 86400
CREATED = 1_000_000


def _w(age_days, **kw):
    return sr.check_window("year", CREATED, now_ts=int(CREATED + age_days * DAY), **kw)


def test_standard_window_unchanged():
    assert _w(29.9)["ok"] and not _w(29.9)["used_grace"]
    assert not _w(31.5)["ok"]


def test_mitigated_grace_allows_up_to_five_days():
    w = _w(31.5, mitigated_grace=True)
    assert w["ok"] and w["used_mitigated_grace"]
    assert _w(35.0, mitigated_grace=True)["ok"]


def test_mitigated_grace_hard_cap():
    w = _w(35.1, mitigated_grace=True)
    assert not w["ok"] and not w["used_mitigated_grace"]


def test_mitigated_grace_ignored_for_monthly():
    w = sr.check_window("month", CREATED, now_ts=CREATED + 2 * DAY, mitigated_grace=True)
    assert not w["ok"]


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
    print("ok")
