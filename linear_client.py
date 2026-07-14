"""Linear GraphQL client for bug ticket search + creation.

Lets the support pipeline (a) search the Technical team's Linear board for
existing bug tickets (dedupe + research) and (b) create new bug tickets.

Requires LINEAR_API_KEY in the environment. Filters to the Technical team via
LINEAR_TECHNICAL_TEAM_ID, falling back to a hardcoded team id if unset.

Mirrors the endpoint/auth pattern used by product_prioritization.py.
"""

from __future__ import annotations

import os
from typing import Any

import requests
from dotenv import load_dotenv

_SUPPORT_DIR = os.path.dirname(os.path.abspath(__file__))
_ROOT_DIR = os.path.dirname(_SUPPORT_DIR)
load_dotenv(os.path.join(_SUPPORT_DIR, ".env"))
load_dotenv(os.path.join(_ROOT_DIR, ".env"))

LINEAR_API_URL = "https://api.linear.app/graphql"

# Fallback Technical team id, used when LINEAR_TECHNICAL_TEAM_ID is not set.
DEFAULT_TECHNICAL_TEAM_ID = "6c1b8aa7-78ae-4e98-919d-e0171f5b0f15"

_SEARCH_ISSUES_QUERY = """
query SearchIssues($term: String!, $teamId: ID, $first: Int) {
  searchIssues(term: $term, filter: { team: { id: { eq: $teamId } } }, first: $first) {
    nodes {
      identifier
      title
      description
      url
      state { name }
    }
  }
}
"""

_ISSUE_CREATE_MUTATION = """
mutation CreateIssue($title: String!, $description: String, $teamId: String!) {
  issueCreate(input: { title: $title, description: $description, teamId: $teamId }) {
    success
    issue {
      identifier
      title
      description
      url
      state { name }
    }
  }
}
"""


def _technical_team_id() -> str:
    return os.getenv("LINEAR_TECHNICAL_TEAM_ID", "").strip() or DEFAULT_TECHNICAL_TEAM_ID


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


def _flatten_issue(issue: dict[str, Any]) -> dict[str, Any]:
    return {
        "identifier": issue.get("identifier", ""),
        "title": issue.get("title", ""),
        "state": (issue.get("state") or {}).get("name", ""),
        "url": issue.get("url", ""),
        "description": issue.get("description") or "",
    }


def search_issues(query: str, first: int = 10) -> list[dict[str, Any]]:
    """Search the Technical team's Linear board for issues matching `query`.

    Uses Linear's `searchIssues` GraphQL query (full-text search), filtered to
    the Technical team (env LINEAR_TECHNICAL_TEAM_ID, else a fallback constant).
    Returns a list of {identifier, title, state, url, description} dicts,
    with `state` flattened from `state.name`.
    """
    variables = {"term": query, "teamId": _technical_team_id(), "first": first}
    data = _gql(_SEARCH_ISSUES_QUERY, variables)
    nodes = ((data.get("searchIssues") or {}).get("nodes")) or []
    return [_flatten_issue(node) for node in nodes]


def create_issue(title: str, description: str, team_id: str | None = None) -> dict[str, Any]:
    """Create a new Linear issue on the Technical team.

    Uses the `issueCreate` mutation. Defaults to the Technical team (env
    LINEAR_TECHNICAL_TEAM_ID, else a fallback constant) when `team_id` is not
    provided. Returns the created issue as {identifier, title, state, url,
    description}. Raises RuntimeError on GraphQL errors or a success=false
    response.
    """
    variables = {
        "title": title,
        "description": description,
        "teamId": team_id or _technical_team_id(),
    }
    data = _gql(_ISSUE_CREATE_MUTATION, variables)
    result = data.get("issueCreate") or {}
    if not result.get("success"):
        raise RuntimeError(f"Linear issueCreate returned success=false: {result}")
    issue = result.get("issue") or {}
    return _flatten_issue(issue)


if __name__ == "__main__":
    import sys

    logging_query = sys.argv[1] if len(sys.argv) > 1 else "bug"
    try:
        results = search_issues(logging_query)
        for r in results:
            print(f"[{r['identifier']}] {r['title']} ({r['state']}) — {r['url']}")
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
