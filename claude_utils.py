"""Shared helpers for Anthropic API responses."""
from __future__ import annotations


def extract_text(message) -> str:
    """Return the first text block's text; thinking blocks are skipped."""
    for block in getattr(message, "content", []) or []:
        if getattr(block, "type", None) == "text":
            return block.text
    return ""
