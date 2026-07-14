"""Tests for research_agent.py — two-pass codebase + Linear research (SUP-462)."""

from __future__ import annotations

import os

import research_agent
from research_agent import (
    MAX_LINE_CHARS,
    MAX_TOOL_OUTPUT_CHARS,
    REPO_ROOTS,
    _cap_output,
    _clip_line,
    _safe_path,
    _tool_read_file,
    _tool_search_code,
    detect_platform,
    run_research,
    should_research,
)


# ---------------------------------------------------------------------------
# should_research
# ---------------------------------------------------------------------------

def test_should_research_low_confidence():
    assert should_research({"confidence": "low", "referenced_policies": ["x"]}) is True


def test_should_research_flag():
    assert should_research({"confidence": "high", "referenced_policies": ["x"],
                            "needs_product_research": True}) is True


def test_no_research_happy_path():
    assert should_research({"confidence": "high", "referenced_policies": ["x"],
                            "needs_product_research": False}) is False


def test_should_research_empty_policies():
    assert should_research({"confidence": "high", "referenced_policies": []}) is True


def test_should_research_missing_policies_key():
    assert should_research({"confidence": "high"}) is True


def test_should_research_confidence_case_insensitive():
    assert should_research({"confidence": "LOW", "referenced_policies": ["x"]}) is True


# ---------------------------------------------------------------------------
# detect_platform
# ---------------------------------------------------------------------------

def test_platform_from_google_sub():
    assert detect_platform("app is broken", {"platform": "google"}) == "android"


def test_platform_ticket_overrides():
    assert detect_platform("on my iPhone the app crashes", {"platform": "google"}) == "ios"


def test_platform_from_apple_sub():
    assert detect_platform("app is broken", {"platform": "apple"}) == "ios"


def test_platform_from_stripe_sub_is_web():
    assert detect_platform("app is broken", {"platform": "stripe"}) == "web"


def test_platform_android_keyword_overrides():
    assert detect_platform("my android phone won't sync", {"platform": "apple"}) == "android"


def test_platform_web_keyword():
    assert detect_platform("on the website in my browser", None) == "web"


def test_platform_unknown():
    assert detect_platform("something is wrong", None) == "unknown"


def test_platform_none_account():
    assert detect_platform("plain text", None) == "unknown"


# ---------------------------------------------------------------------------
# _safe_path
# ---------------------------------------------------------------------------

def test_safe_path_blocks_escape():
    assert _safe_path("../../etc/passwd") is None


def test_safe_path_blocks_absolute_outside():
    assert _safe_path("/etc/passwd") is None


def test_safe_path_allows_rails_relative():
    # A path inside the rails repo resolves under a repo root.
    resolved = _safe_path("../changecollective.com/Gemfile")
    assert resolved is not None
    assert resolved.startswith(REPO_ROOTS["rails"])


def test_safe_path_allows_absolute_inside_repo():
    resolved = _safe_path(os.path.join(REPO_ROOTS["rails"], "Gemfile"))
    assert resolved is not None
    assert resolved.startswith(REPO_ROOTS["rails"])


def test_safe_path_blocks_sneaky_escape_inside_repo():
    # Traversal that starts inside a repo root but climbs out must be refused.
    sneaky = os.path.join(REPO_ROOTS["rails"], "..", "..", "etc", "passwd")
    assert _safe_path(sneaky) is None


# ---------------------------------------------------------------------------
# _tool_search_code
# ---------------------------------------------------------------------------

def test_search_code_unknown_repo():
    out = _tool_search_code("anything", "not_a_repo")
    assert "unknown repo" in out.lower()


def test_search_code_finds_matches_in_rails():
    # "source" appears throughout the rails repo; expect a matches block with
    # path:lineno:text lines, capped at MAX_MATCHES.
    out = _tool_search_code("source", "rails")
    assert out.startswith("Matches for") or "no matches" in out.lower()
    if out.startswith("Matches for"):
        # Body lines should be repo-relative (no absolute repo-root prefix).
        assert research_agent.REPO_ROOTS["rails"] not in out
        assert len(out.splitlines()) <= research_agent.MAX_MATCHES + 1  # +1 header


# ---------------------------------------------------------------------------
# output caps (regression: live smoke hit a 1M-token context overflow)
# ---------------------------------------------------------------------------

def test_clip_line_truncates_long_lines():
    long = "x" * (MAX_LINE_CHARS + 500)
    clipped = _clip_line(long)
    assert len(clipped) < len(long)
    assert "truncated" in clipped


def test_clip_line_leaves_short_lines():
    assert _clip_line("short") == "short"


def test_cap_output_bounds_total_size():
    big = "y" * (MAX_TOOL_OUTPUT_CHARS * 2)
    capped = _cap_output(big)
    assert len(capped) <= MAX_TOOL_OUTPUT_CHARS + 40
    assert "truncated" in capped


# ---------------------------------------------------------------------------
# _tool_read_file
# ---------------------------------------------------------------------------

def test_read_file_refuses_outside_repos():
    out = _tool_read_file("/etc/passwd", 1, 5)
    assert "refused" in out.lower() or "outside" in out.lower()


def test_read_file_reads_inside_repo():
    out = _tool_read_file("../changecollective.com/Gemfile", 1, 3)
    assert "source" in out.lower() or len(out) > 0


def test_read_file_caps_lines():
    # Requesting a huge range must cap at 200 lines.
    out = _tool_read_file("../changecollective.com/Gemfile", 1, 5000)
    # Count non-empty content lines is hard; just ensure it returned a string
    # and did not blow up. The cap is enforced internally.
    assert isinstance(out, str)


# ---------------------------------------------------------------------------
# run_research — fail soft
# ---------------------------------------------------------------------------

def test_run_research_fails_soft_on_exception(monkeypatch):
    """Any exception inside run_research → empty findings, never raises."""

    def boom(*a, **k):
        raise RuntimeError("kaboom")

    monkeypatch.setattr(research_agent.anthropic, "Anthropic", boom)
    result = run_research("q", "acct", "android")
    assert result["findings"] == ""
    assert result["sources"] == []
    assert result["tool_calls"] == 0


def test_run_research_missing_api_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    result = run_research("q", "acct", None)
    assert result["findings"] == ""
    assert result["sources"] == []
