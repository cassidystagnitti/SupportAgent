#!/usr/bin/env python3
"""Two-pass codebase + Linear research agent (SUP-462).

When the first support draft is low-confidence, cites no policy, or the model
flags a product-behavior question, the orchestrator calls `run_research`. The
research agent investigates the three product codebases (rails / android /
ios_v1) and the Linear board via a bounded Anthropic tool-use loop, then returns
a short, sourced findings block. The orchestrator re-runs the draft with those
findings appended.

Guardrails (binding):
- Read-only tools only (search_code, read_file, search_linear).
- `_safe_path` refuses any path resolving outside the three repo roots.
- Tool loop capped at MAX_ITERATIONS; wall clock capped at WALL_CLOCK_SECONDS.
- Findings <= ~300 words, ending with a `SOURCES:` list.
- System prompt forbids quoting code to customers.
- `run_research` fails soft: any exception → {"findings": "", "sources": [],
  "tool_calls": N}.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import time
from typing import Any

import anthropic
from dotenv import load_dotenv

import linear_client
from claude_utils import extract_text

_SUPPORT_DIR = os.path.dirname(os.path.abspath(__file__))
_ROOT_DIR = os.path.dirname(_SUPPORT_DIR)
load_dotenv(os.path.join(_SUPPORT_DIR, ".env"))
load_dotenv(os.path.join(_ROOT_DIR, ".env"))

log = logging.getLogger("research_agent")

RESEARCH_MODEL = "claude-sonnet-5"
MAX_ITERATIONS = 15
WALL_CLOCK_SECONDS = 180.0
MAX_MATCHES = 20
MAX_READ_LINES = 200
# Defensive output caps: a single match/line can be enormous (minified assets,
# lockfiles, schema dumps, JSON fixtures). Uncapped, one tool result can blow the
# context window (observed a 1M-token overflow in the live smoke). Truncate per
# line and cap the whole tool result.
MAX_LINE_CHARS = 300
MAX_TOOL_OUTPUT_CHARS = 8000

# Repo roots are siblings of SupportAgent. Resolve to absolute paths at import
# so `_safe_path` can compare canonical prefixes regardless of cwd.
_REPO_RELPATHS = {
    "rails": "../changecollective.com",
    "android": "../HappierHybrid-Android",
    "ios_v1": "../ten-percent-ios",
}
REPO_ROOTS: dict[str, str] = {
    name: os.path.realpath(os.path.join(_SUPPORT_DIR, rel))
    for name, rel in _REPO_RELPATHS.items()
}


# ---------------------------------------------------------------------------
# Pure decision helpers
# ---------------------------------------------------------------------------

def should_research(parsed: dict) -> bool:
    """True when the first draft warrants a research pass.

    Triggers when confidence is low, when no policy was referenced, or when the
    model explicitly flagged that the question is about product behavior.
    """
    confidence = str(parsed.get("confidence") or "").strip().lower()
    if confidence == "low":
        return True
    if not (parsed.get("referenced_policies") or []):
        return True
    if parsed.get("needs_product_research"):
        return True
    return False


def detect_platform(ticket_text: str, account_data: dict | None) -> str:
    """Best-effort platform for scoping the research.

    Ticket keywords win over subscription platform (a Google subscriber can
    still write in about their iPhone). Subscription platform maps apple→ios,
    google→android, stripe→web. Returns "ios" | "android" | "web" | "unknown".
    """
    text = (ticket_text or "").lower()

    # Ticket-keyword overrides (checked first, most specific wins).
    ios_kw = ("iphone", "ipad", "ios", "app store", "apple", "safari")
    android_kw = ("android", "google play", "play store", "pixel", "samsung", "galaxy")
    web_kw = ("website", "web app", "browser", "chrome", "firefox", "desktop", "laptop", "on the web")

    has_ios = any(k in text for k in ios_kw)
    has_android = any(k in text for k in android_kw)
    has_web = any(k in text for k in web_kw)

    # If exactly one platform family is named in the ticket, that wins.
    named = [p for p, hit in (("ios", has_ios), ("android", has_android), ("web", has_web)) if hit]
    if len(named) == 1:
        return named[0]

    # Fall back to subscription platform from account data.
    plat = str((account_data or {}).get("platform") or "").strip().lower()
    if plat in ("apple", "ios", "itunes", "app_store"):
        return "ios"
    if plat in ("google", "android", "play", "google_play"):
        return "android"
    if plat in ("stripe", "web"):
        return "web"

    # Ambiguous ticket keywords with no account signal.
    if len(named) > 1:
        return "unknown"
    return "unknown"


# ---------------------------------------------------------------------------
# Path safety
# ---------------------------------------------------------------------------

def _safe_path(path: str) -> str | None:
    """Resolve `path` and return it only if it lives inside a repo root.

    `path` may be absolute or relative to SupportAgent. Symlinks and `..`
    traversal are canonicalised via realpath before the prefix check, so a path
    that starts inside a repo but climbs out is refused. Returns the resolved
    absolute path, or None if it escapes all three roots.
    """
    if not path:
        return None
    candidate = path if os.path.isabs(path) else os.path.join(_SUPPORT_DIR, path)
    resolved = os.path.realpath(candidate)
    for root in REPO_ROOTS.values():
        # Ensure resolved is the root itself or a child of it (with separator
        # boundary so "/repo-evil" doesn't match "/repo").
        if resolved == root or resolved.startswith(root + os.sep):
            return resolved
    return None


# ---------------------------------------------------------------------------
# Read-only tools
# ---------------------------------------------------------------------------

def _clip_line(line: str) -> str:
    """Truncate an over-long single line so one match can't flood the context."""
    if len(line) > MAX_LINE_CHARS:
        return line[:MAX_LINE_CHARS] + " …[truncated]"
    return line


def _cap_output(text: str) -> str:
    """Hard cap on total tool-result size (belt-and-suspenders vs runaway output)."""
    if len(text) > MAX_TOOL_OUTPUT_CHARS:
        return text[:MAX_TOOL_OUTPUT_CHARS] + "\n…[output truncated]"
    return text


def _tool_search_code(query: str, repo: str) -> str:
    """Search one repo root for `query`, capped at MAX_MATCHES lines.

    Uses ripgrep when available, else falls back to a recursive grep. Output is
    `path:lineno:text` lines relative to the repo root.
    """
    root = REPO_ROOTS.get(repo)
    if not root:
        return f"Error: unknown repo '{repo}'. Valid repos: {', '.join(REPO_ROOTS)}."
    if not os.path.isdir(root):
        return f"Error: repo '{repo}' not found on disk at {root}."
    if not (query or "").strip():
        return "Error: empty query."

    rg = shutil.which("rg")
    try:
        if rg:
            cmd = [rg, "-n", "--max-count", str(MAX_MATCHES), "--no-heading",
                   "-e", query, root]
        else:
            # grep fallback: -r recursive, -n line numbers, -I skip binary,
            # -m caps matches per file.
            cmd = ["grep", "-rnI", "-m", str(MAX_MATCHES), "-e", query, root]
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=25,
        )
    except subprocess.TimeoutExpired:
        return f"Search timed out for query {query!r} in {repo}."
    except Exception as e:  # pragma: no cover - defensive
        return f"Search failed: {e}"

    # grep/rg exit 1 == no matches (not an error).
    out = (proc.stdout or "").strip()
    if not out:
        return f"No matches for {query!r} in {repo}."

    lines = out.splitlines()[:MAX_MATCHES]
    # Present paths relative to the repo root for compact, readable output, and
    # clip any single over-long match line.
    rel_lines = []
    for ln in lines:
        rel = ln.replace(root + os.sep, "").replace(root, "")
        rel_lines.append(_clip_line(rel))
    header = f"Matches for {query!r} in {repo} (repo root: {os.path.basename(root)}):"
    return _cap_output(header + "\n" + "\n".join(rel_lines))


def _tool_read_file(path: str, start_line: int | None = None, end_line: int | None = None) -> str:
    """Read a slice of a file inside a repo root, capped at MAX_READ_LINES."""
    resolved = _safe_path(path)
    if resolved is None:
        return f"Refused: path {path!r} resolves outside the allowed repo roots."
    if not os.path.isfile(resolved):
        return f"Error: not a file: {path!r}."

    try:
        start = int(start_line) if start_line else 1
    except (TypeError, ValueError):
        start = 1
    if start < 1:
        start = 1
    try:
        end = int(end_line) if end_line else start + MAX_READ_LINES - 1
    except (TypeError, ValueError):
        end = start + MAX_READ_LINES - 1
    # Enforce the 200-line cap regardless of the requested range.
    if end - start + 1 > MAX_READ_LINES:
        end = start + MAX_READ_LINES - 1

    try:
        with open(resolved, encoding="utf-8", errors="replace") as f:
            selected = []
            for i, line in enumerate(f, start=1):
                if i < start:
                    continue
                if i > end:
                    break
                selected.append(f"{i}\t{_clip_line(line.rstrip(chr(10)))}")
    except Exception as e:
        return f"Error reading {path!r}: {e}"

    if not selected:
        return f"(no lines {start}-{end} in {path!r})"
    rel = path
    return _cap_output(f"{rel} (lines {start}-{end}):\n" + "\n".join(selected))


def _tool_search_linear(query: str) -> str:
    """Search the Linear board via linear_client.search_issues."""
    if not (query or "").strip():
        return "Error: empty query."
    try:
        issues = linear_client.search_issues(query, first=10)
    except Exception as e:
        return f"Linear search failed: {e}"
    if not issues:
        return f"No Linear issues found for {query!r}."
    lines = []
    for it in issues:
        desc = (it.get("description") or "").strip().replace("\n", " ")
        if len(desc) > 200:
            desc = desc[:200] + "…"
        lines.append(
            f"[{it.get('identifier','')}] {it.get('title','')} "
            f"({it.get('state','')}) — {it.get('url','')}"
            + (f"\n    {desc}" if desc else "")
        )
    return _cap_output(f"Linear issues for {query!r}:\n" + "\n".join(lines))


# ---------------------------------------------------------------------------
# Tool schemas + dispatch
# ---------------------------------------------------------------------------

_TOOLS: list[dict[str, Any]] = [
    {
        "name": "search_code",
        "description": (
            "Search one product codebase for a literal/regex pattern. Returns up "
            "to 20 matching lines as path:lineno:text. Use this to find where a "
            "feature or setting is implemented."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search pattern (ripgrep/grep syntax)."},
                "repo": {
                    "type": "string",
                    "enum": list(REPO_ROOTS.keys()),
                    "description": "Which codebase: 'rails' (web backend/frontend), "
                    "'android', or 'ios_v1' (legacy iOS).",
                },
            },
            "required": ["query", "repo"],
        },
    },
    {
        "name": "read_file",
        "description": (
            "Read a slice of a file inside one of the product codebases (max 200 "
            "lines). Paths outside the repos are refused. Use after search_code to "
            "read the surrounding context of a match."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path (relative to the repo, e.g. ../changecollective.com/app/models/user.rb)."},
                "start_line": {"type": "integer", "description": "First line (1-based)."},
                "end_line": {"type": "integer", "description": "Last line (inclusive)."},
            },
            "required": ["path"],
        },
    },
    {
        "name": "search_linear",
        "description": (
            "Search the engineering Linear board for issues/bugs matching a query. "
            "Use to check whether reported behavior is a known bug or planned work."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Full-text search term."},
            },
            "required": ["query"],
        },
    },
]


def _dispatch_tool(name: str, tool_input: dict[str, Any]) -> str:
    """Route a tool_use block to its implementation; never raises."""
    try:
        if name == "search_code":
            return _tool_search_code(tool_input.get("query", ""), tool_input.get("repo", ""))
        if name == "read_file":
            return _tool_read_file(
                tool_input.get("path", ""),
                tool_input.get("start_line"),
                tool_input.get("end_line"),
            )
        if name == "search_linear":
            return _tool_search_linear(tool_input.get("query", ""))
        return f"Error: unknown tool {name!r}."
    except Exception as e:  # pragma: no cover - defensive
        log.exception("tool %s raised", name)
        return f"Tool {name} error: {e}"


_RESEARCH_SYSTEM_PROMPT = """You are a research assistant for a customer-support pipeline at Happier, a meditation app.

A first-pass support draft was low-confidence or the customer's question is about how the product actually behaves. Your job: investigate the SPECIFIC product question using the read-only tools, then report concise findings that help a support agent answer accurately.

Codebases available via tools:
- rails: the web backend + Hotwire frontend (changecollective.com) — the current v2 app.
- android: the Android hybrid wrapper.
- ios_v1: the legacy native iOS app (older; may not reflect current behavior).
The Linear board holds engineering bugs and planned work.

How to work:
1. Search the codebase(s) most relevant to the customer's platform for the feature/setting in question.
2. Read the surrounding code to confirm whether the behavior/setting actually exists and how it works.
3. Check Linear for known bugs or planned changes if the question is about a defect or missing feature.
4. Stop as soon as you can answer the question; do not over-investigate.

Rules for your final answer:
- Answer the specific question: does the setting/behavior exist, where, and any caveats.
- Keep findings under ~300 words.
- NEVER include code snippets, class names dumps, or verbatim code in your findings — the support team may paraphrase to a customer. Describe behavior in plain language.
- Base claims on what you actually found in the tools. If you could not confirm something, say so plainly.
- End your final message with a line `SOURCES:` followed by a bullet list of the file paths and Linear issue identifiers you relied on. If you found nothing conclusive, still write `SOURCES:` with what you checked.
"""


_SOURCE_LINE_RE = re.compile(r"^\s*(?:[-*•]\s*)?(.+?)\s*$")


def _extract_sources(findings: str) -> list[str]:
    """Pull the SOURCES: list off the end of the findings block."""
    if not findings:
        return []
    idx = findings.rfind("SOURCES:")
    if idx < 0:
        return []
    tail = findings[idx + len("SOURCES:"):]
    sources: list[str] = []
    for raw in tail.splitlines():
        line = raw.strip()
        if not line:
            continue
        m = _SOURCE_LINE_RE.match(line)
        if not m:
            continue
        val = m.group(1).strip()
        if val:
            sources.append(val)
    return sources


def run_research(ticket_text: str, account_summary: str, platform_hint: str | None) -> dict[str, Any]:
    """Investigate a product question across the codebases + Linear.

    Returns {"findings": str, "sources": list[str], "tool_calls": int}.
    Fails soft: any exception or timeout yields empty findings (never raises).
    """
    tool_calls = 0
    try:
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            log.warning("run_research: ANTHROPIC_API_KEY unset — skipping research")
            return {"findings": "", "sources": [], "tool_calls": 0}

        client = anthropic.Anthropic(api_key=api_key)
        model = os.getenv("RESEARCH_MODEL", RESEARCH_MODEL)

        plat = (platform_hint or "unknown").strip() or "unknown"
        user_prompt = (
            f"Customer platform (best guess): {plat}\n"
            f"Account summary: {account_summary}\n\n"
            f"Question to research:\n{ticket_text}\n\n"
            "Investigate using the tools, then report your findings."
        )
        messages: list[dict[str, Any]] = [{"role": "user", "content": user_prompt}]

        deadline = time.monotonic() + WALL_CLOCK_SECONDS
        final_text = ""

        for iteration in range(MAX_ITERATIONS):
            if time.monotonic() >= deadline:
                log.warning("run_research: wall clock exceeded before iteration %s", iteration)
                break

            try:
                message = client.messages.create(
                    model=model,
                    max_tokens=2048,
                    system=_RESEARCH_SYSTEM_PROMPT,
                    tools=_TOOLS,
                    messages=messages,
                )
            except anthropic.AnthropicError as e:
                log.warning("run_research: Anthropic API error on iteration %s: %s", iteration, e)
                break

            stop_reason = getattr(message, "stop_reason", None)

            # Collect any tool_use blocks this turn.
            tool_uses = [
                b for b in (getattr(message, "content", None) or [])
                if getattr(b, "type", None) == "tool_use"
            ]

            if stop_reason != "tool_use" or not tool_uses:
                # Model produced its final answer (or stopped for another reason).
                final_text = extract_text(message)
                break

            # Record the assistant turn (must precede the tool_result user turn).
            messages.append({"role": "assistant", "content": message.content})

            tool_results = []
            for block in tool_uses:
                tool_calls += 1
                result_text = _dispatch_tool(block.name, block.input or {})
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": result_text,
                })
            messages.append({"role": "user", "content": tool_results})
        else:
            log.warning("run_research: hit MAX_ITERATIONS (%s) without end_turn", MAX_ITERATIONS)

        findings = (final_text or "").strip()
        sources = _extract_sources(findings)
        return {"findings": findings, "sources": sources, "tool_calls": tool_calls}

    except Exception as e:
        log.exception("run_research failed soft: %s", e)
        return {"findings": "", "sources": [], "tool_calls": tool_calls}


if __name__ == "__main__":
    import json

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    res = run_research(
        "User asks: is there a setting to hide practice goals?",
        "v2 app subscriber",
        "android",
    )
    print(json.dumps(res, indent=2))
