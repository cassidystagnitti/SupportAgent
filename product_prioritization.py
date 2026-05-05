"""Product prioritization feedback routing.

When a ticket is tagged 'feedback', checks whether the customer's message maps
to an existing issue on the Linear product-prioritization board. If it does,
adds a comment on that Linear issue linking back to the Help Scout ticket.

Requires LINEAR_API_KEY and LINEAR_PRODUCT_TEAM_ID in the environment.
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any

import anthropic
import requests
from dotenv import load_dotenv

_SUPPORT_DIR = os.path.dirname(os.path.abspath(__file__))
_ROOT_DIR = os.path.dirname(_SUPPORT_DIR)
load_dotenv(os.path.join(_SUPPORT_DIR, ".env"))
load_dotenv(os.path.join(_ROOT_DIR, ".env"))

log = logging.getLogger("product_prioritization")

LINEAR_API_URL = "https://api.linear.app/graphql"
PROMPT_PATH = os.path.join(_SUPPORT_DIR, "prompts", "product_prioritization_prompt.txt")
DEFAULT_MODEL = "claude-sonnet-4-6"
HS_CONVERSATION_BASE_URL = "https://secure.helpscout.net/conversation"


# ---------------------------------------------------------------------------
# Linear API helpers
# ---------------------------------------------------------------------------

def _linear_headers() -> dict[str, str]:
    key = os.getenv("LINEAR_API_KEY", "").strip()
    if not key:
        raise RuntimeError("LINEAR_API_KEY is not set")
    return {"Authorization": key, "Content-Type": "application/json"}


def _gql(query: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
    resp = requests.post(
        LINEAR_API_URL,
        json={"query": query, "variables": variables or {}},
        headers=_linear_headers(),
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()
    if "errors" in data:
        raise RuntimeError(f"Linear GraphQL errors: {data['errors']}")
    return data["data"]


def list_linear_teams() -> list[dict[str, Any]]:
    """Utility: list all teams and IDs to find the right LINEAR_PRODUCT_TEAM_ID."""
    data = _gql("{ teams { nodes { id name } } }")
    return (data.get("teams") or {}).get("nodes") or []


def fetch_linear_team_issues(team_id: str) -> list[dict[str, Any]]:
    """Fetch open/backlog issues from the product prioritization team."""
    query = """
    query TeamIssues($teamId: String!) {
      team(id: $teamId) {
        issues(
          filter: { state: { type: { in: ["backlog", "unstarted", "started"] } } }
          first: 250
        ) {
          nodes {
            id
            identifier
            title
            description
            state { name }
            labels { nodes { name } }
          }
        }
      }
    }
    """
    data = _gql(query, {"teamId": team_id})
    team = data.get("team") or {}
    return (team.get("issues") or {}).get("nodes") or []


def _add_comment(issue_id: str, body: str) -> bool:
    mutation = """
    mutation AddComment($issueId: String!, $body: String!) {
      commentCreate(input: { issueId: $issueId, body: $body }) {
        success
      }
    }
    """
    data = _gql(mutation, {"issueId": issue_id, "body": body})
    return bool((data.get("commentCreate") or {}).get("success"))


# ---------------------------------------------------------------------------
# Claude call
# ---------------------------------------------------------------------------

def _format_issues_for_prompt(issues: list[dict[str, Any]]) -> str:
    if not issues:
        return "(no existing issues on the board)"
    lines = []
    for issue in issues:
        identifier = issue.get("identifier", "")
        title = issue.get("title", "")
        state = (issue.get("state") or {}).get("name", "")
        labels = [lb["name"] for lb in (issue.get("labels") or {}).get("nodes", [])]
        label_str = f" [{', '.join(labels)}]" if labels else ""
        desc = (issue.get("description") or "").strip()
        if len(desc) > 250:
            desc = desc[:250] + "…"
        lines.append(f"- id:{issue.get('id')}  [{identifier}] {title}{label_str} ({state})")
        if desc:
            lines.append(f"  {desc}")
    return "\n".join(lines)


def _load_prompt() -> str:
    with open(PROMPT_PATH, encoding="utf-8") as f:
        return f.read()


def _call_claude(
    client: anthropic.Anthropic,
    *,
    ticket_subject: str,
    ticket_body: str,
    issues_text: str,
    model: str,
) -> dict[str, Any]:
    system_prompt = _load_prompt()
    user_message = (
        f"=== CUSTOMER FEEDBACK TICKET ===\n"
        f"Subject: {ticket_subject}\n\n"
        f"{ticket_body}\n\n"
        f"=== EXISTING ISSUES ON PRODUCT PRIORITIZATION BOARD ===\n"
        f"{issues_text}\n\n"
        f"Respond with a JSON object only."
    )
    message = client.messages.create(
        model=model,
        max_tokens=512,
        system=system_prompt,
        messages=[{"role": "user", "content": user_message}],
    )
    text = (message.content[0].text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text).strip()
    return json.loads(text)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def run_product_prioritization(
    ticket_subject: str,
    ticket_body: str,
    tags: list[str],
    conversation_id: str,
) -> dict[str, Any]:
    """Check whether a feedback ticket maps to a Linear product board issue.

    If it does, adds a comment on that issue linking back to the Help Scout
    ticket. Returns a result dict; never raises. Returns {skipped: True} when
    the ticket is not tagged 'feedback' or required env vars are missing.
    """
    out: dict[str, Any] = {
        "skipped": False,
        "matched": False,
        "linear_issue_id": None,
        "linear_issue_identifier": None,
        "reasoning": None,
        "error": None,
    }

    if "feedback" not in [t.lower() for t in (tags or [])]:
        out["skipped"] = True
        return out

    team_id = os.getenv("LINEAR_PRODUCT_TEAM_ID", "").strip()
    if not team_id:
        log.warning("LINEAR_PRODUCT_TEAM_ID not set — skipping product prioritization")
        out["skipped"] = True
        return out

    model = os.getenv("CLAUDE_DRAFT_MODEL", DEFAULT_MODEL)
    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

    try:
        issues = fetch_linear_team_issues(team_id)
        issues_text = _format_issues_for_prompt(issues)
        log.info("product_prioritization: fetched %d Linear issues", len(issues))

        parsed = _call_claude(
            client,
            ticket_subject=ticket_subject,
            ticket_body=ticket_body,
            issues_text=issues_text,
            model=model,
        )

        out["reasoning"] = parsed.get("reasoning")

        if not parsed.get("match"):
            log.info("product_prioritization: no matching issue — %s", parsed.get("reasoning"))
            return out

        issue_id = parsed.get("issue_id")
        issue_identifier = parsed.get("issue_identifier")
        if not issue_id:
            out["error"] = "match=true but no issue_id in Claude response"
            log.warning("product_prioritization: %s", out["error"])
            return out

        hs_url = f"{HS_CONVERSATION_BASE_URL}/{conversation_id}"
        customer_quote = (parsed.get("customer_quote") or "").strip()
        comment_lines = [f"**Customer feedback via Help Scout:** [#{conversation_id}]({hs_url})"]
        if customer_quote:
            comment_lines.append(f"\n> {customer_quote}")
        comment_body = "\n".join(comment_lines)

        success = _add_comment(issue_id, comment_body)
        if success:
            out["matched"] = True
            out["linear_issue_id"] = issue_id
            out["linear_issue_identifier"] = issue_identifier
            log.info(
                "product_prioritization: linked HS #%s to Linear issue %s",
                conversation_id,
                issue_identifier,
            )
        else:
            out["error"] = "commentCreate returned success=false"

    except Exception as e:
        out["error"] = str(e)
        log.exception("product_prioritization failed: %s", e)

    return out


# ---------------------------------------------------------------------------
# CLI helper — print team IDs so you can set LINEAR_PRODUCT_TEAM_ID
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    print("Linear teams in your workspace:\n")
    try:
        teams = list_linear_teams()
        for t in teams:
            print(f"  {t['id']}  {t['name']}")
        print("\nSet LINEAR_PRODUCT_TEAM_ID to the id of your product prioritization team.")
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
