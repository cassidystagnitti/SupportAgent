from __future__ import annotations

import html
import re
from typing import Any

_TAG_RE = re.compile(r"<[^>]+>")


def strip_html_to_text(raw: str) -> str:
    """Best-effort HTML email body to plain text for model prompts."""
    if not raw:
        return ""
    text = html.unescape(raw)
    text = _TAG_RE.sub(" ", text)
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def thread_speaker_label(thread: dict[str, Any]) -> str:
    t = thread.get("type")
    created = thread.get("createdBy") or {}
    ctype = created.get("type")
    if t == "customer":
        return "Customer"
    if t == "note":
        return "Internal note"
    if t == "message" and ctype == "user":
        first = (created.get("first") or "").strip()
        last = (created.get("last") or "").strip()
        name = f"{first} {last}".strip()
        return f"Agent ({name})" if name else "Agent"
    if t == "message" and ctype == "customer":
        return "Customer"
    if t in ("chat", "phone", "beaconchat"):
        return f"{t.title()} thread"
    if t in ("lineitem", "forwardparent", "forwardchild"):
        return "System"
    return str(t or "Unknown")


def should_include_thread(thread: dict[str, Any]) -> bool:
    t = thread.get("type")
    if t == "lineitem":
        return False
    state = thread.get("state")
    if state == "hidden":
        return False
    body = (thread.get("body") or "").strip()
    if t == "note" and not body:
        return False
    return True


def build_transcript(threads: list[dict[str, Any]], max_chars: int = 48_000) -> str:
    """Threads oldest-first; truncates from the middle if needed."""
    sorted_threads = sorted(threads, key=lambda th: th.get("createdAt") or "")
    lines: list[str] = []
    for th in sorted_threads:
        if not should_include_thread(th):
            continue
        label = thread_speaker_label(th)
        when = th.get("createdAt") or ""
        body = strip_html_to_text(str(th.get("body") or ""))
        if not body and th.get("type") != "note":
            continue
        lines.append(f"[{when}] {label}:\n{body}\n")

    text = "\n".join(lines).strip()
    if len(text) <= max_chars:
        return text

    head = text[: max_chars // 2]
    tail = text[-max_chars // 2 :]
    return f"{head}\n\n…[transcript truncated]…\n\n{tail}"
