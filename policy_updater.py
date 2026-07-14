"""Confirmed policy/knowledge updates from the sidebar chat.

Bert proposes an edit to a policies/*.md doc via the propose_policy_update
tool; the support agent confirms it in the sidebar. On confirm this module
applies the edit to the LIVE policy copy (atomic write) and commits the file
to the GitHub repo (path-restricted, "[skip render]" so Render doesn't
redeploy). GitHub failure rolls the live file back. The git repo is the single
source of truth for policy docs — the old Notion sync was abandoned 2026-07-14.

See docs/superpowers/specs/2026-07-14-hs-sidebar-chat-design.md §2.
"""

from __future__ import annotations

import base64
import difflib
import logging
import os
import tempfile
import uuid

import requests

log = logging.getLogger("policy_updater")

_SUPPORT_DIR = os.path.dirname(os.path.abspath(__file__))
POLICIES_DIR = os.path.join(_SUPPORT_DIR, "policies")
GITHUB_API = "https://api.github.com"


class ProposalError(ValueError):
    """A proposal is invalid (bad file, missing/ambiguous target, bad edit_type)."""


def _policy_path(policy_file: str) -> str:
    base = os.path.basename(str(policy_file or "").strip())
    if not base or not base.endswith(".md"):
        raise ProposalError(f"{policy_file!r} is not a policies/*.md file")
    path = os.path.join(POLICIES_DIR, base)
    if not os.path.isfile(path):
        raise ProposalError(f"policies/{base} does not exist")
    return path


def _apply_edit(content: str, edit_type: str, target_text: str, new_text: str) -> str:
    if edit_type == "replace":
        if not target_text:
            raise ProposalError("replace requires target_text")
        n = content.count(target_text)
        if n == 0:
            raise ProposalError("target_text not found in the current policy file")
        if n > 1:
            raise ProposalError(f"target_text occurs {n} times — must be unique")
        return content.replace(target_text, new_text, 1)
    if edit_type == "append":
        sep = "" if content.endswith("\n\n") else ("\n" if content.endswith("\n") else "\n\n")
        return content + sep + new_text.strip() + "\n"
    raise ProposalError(f"unknown edit_type {edit_type!r} (want replace|append)")


def build_proposal(*, policy_file: str, edit_type: str, target_text: str,
                   new_text: str, rationale: str) -> dict:
    """Validate and register a proposed edit. Raises ProposalError; applies nothing."""
    path = _policy_path(policy_file)
    with open(path, encoding="utf-8") as f:
        current = f.read()
    updated = _apply_edit(current, edit_type, target_text, new_text)
    name = f"policies/{os.path.basename(path)}"
    diff = "".join(difflib.unified_diff(
        current.splitlines(keepends=True), updated.splitlines(keepends=True),
        fromfile=name, tofile=name,
    ))
    return {
        "id": uuid.uuid4().hex[:12],
        "policy_file": os.path.basename(path),
        "edit_type": edit_type,
        "target_text": target_text,
        "new_text": new_text,
        "rationale": rationale,
        "diff": diff,
        "status": "pending",
    }


def _atomic_write(path: str, content: str) -> None:
    """tmp file in the same directory + os.replace — same pattern as the registries."""
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _github_config() -> tuple[str, str, str]:
    token = (os.getenv("GITHUB_TOKEN") or "").strip()
    if not token:
        raise RuntimeError("GITHUB_TOKEN not configured — cannot commit policy updates")
    repo = (os.getenv("GITHUB_REPO") or "cassidystagnitti/SupportAgent").strip()
    branch = (os.getenv("GITHUB_BRANCH") or "main").strip()
    return token, repo, branch


def commit_policy_file(policy_file: str, content: str, message: str) -> str:
    """Commit policies/<file> via the GitHub Contents API. Returns the commit sha.

    Hard path restriction: only basenames ending in .md, always under policies/.
    On a sha conflict (another commit landed between GET and PUT) refetches the
    sha and retries once.
    """
    base = os.path.basename(str(policy_file))
    if not base.endswith(".md"):
        raise ValueError("only policies/*.md may be committed from the sidebar")
    token, repo, branch = _github_config()
    url = f"{GITHUB_API}/repos/{repo}/contents/policies/{base}"
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}
    body = {
        "message": message,
        "content": base64.b64encode(content.encode("utf-8")).decode("ascii"),
        "branch": branch,
    }
    for attempt in range(2):
        r_get = requests.get(url, headers=headers, params={"ref": branch}, timeout=30)
        if r_get.status_code == 200:
            body["sha"] = r_get.json()["sha"]
        elif r_get.status_code == 404:
            body.pop("sha", None)  # new file
        else:
            r_get.raise_for_status()
        r_put = requests.put(url, headers=headers, json=body, timeout=30)
        if r_put.status_code in (200, 201):
            return r_put.json()["commit"]["sha"]
        if r_put.status_code in (409, 422) and attempt == 0:
            log.warning("policy commit conflict for %s — refetching sha and retrying", base)
            continue
        r_put.raise_for_status()
    raise RuntimeError(f"unable to commit policies/{base} after retry")


def confirm_proposal(proposal: dict, *, conversation_id: str) -> dict:
    """Apply a pending proposal: live apply -> GitHub commit.

    Re-validates the edit against the CURRENT file (drift fails loudly).
    GitHub failure rolls the live file back and re-raises (proposal stays
    pending / retryable).
    """
    path = _policy_path(proposal["policy_file"])
    with open(path, encoding="utf-8") as f:
        current = f.read()
    updated = _apply_edit(current, proposal["edit_type"],
                          proposal["target_text"], proposal["new_text"])
    _atomic_write(path, updated)

    rationale = (proposal.get("rationale") or "").strip() or "policy update from sidebar chat"
    short = rationale.splitlines()[0][:60]
    message = (
        f"policy: {proposal['policy_file']} — {short}\n\n"
        f"{rationale}\n\n"
        f"Source: Help Scout conversation "
        f"https://secure.helpscout.net/conversation/{conversation_id}\n"
        f"Confirmed by a support agent via the sidebar chat.\n\n"
        f"[skip render]"
    )
    try:
        sha = commit_policy_file(proposal["policy_file"], updated, message)
    except BaseException:
        _atomic_write(path, current)  # roll back the live copy
        raise

    proposal["status"] = "confirmed"
    return {"commit_sha": sha}
