"""Fetch customer/account context for retrieval + rerank prompts.

Configuration (first match wins):

1) Full URL template:
   ACCOUNT_CONTEXT_URL_TEMPLATE=... with {email} or {customer_id}
   HAPPIER_BEARER_TOKEN (or ACCOUNT_CONTEXT_BEARER_TOKEN) for Authorization unless HEADERS_JSON set.

2) Happier base + custom path (generic HTTP, not Maven user object):
   HAPPIER_MAVEN_BASE_URL + HAPPIER_ACCOUNT_CONTEXT_PATH + placeholders

3) Built-in Maven (recommended for Happier): leave (1) and (2) unset. With HAPPIER_BEARER_TOKEN,
   calls GET /users?email=… then GET /users/{uuid}/subscriptions and formats the fixed summary block.

Optional: ACCOUNT_CONTEXT_HTTP_HEADERS_JSON, ACCOUNT_CONTEXT_HTTP_METHOD, ACCOUNT_CONTEXT_HTTP_BODY_JSON

Test:
   .venv/bin/python account_context.py --email you@example.com
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from urllib.parse import quote

import requests
from dotenv import load_dotenv

_SUPPORT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(_SUPPORT_DIR)
load_dotenv(os.path.join(_SUPPORT_DIR, ".env"))
load_dotenv(os.path.join(ROOT_DIR, ".env"))

_DEFAULT_HAPPIER_BASE = "https://my.happierapp.com/api/maven/v1"


def _header_dict() -> dict[str, str]:
    raw = (os.getenv("ACCOUNT_CONTEXT_HTTP_HEADERS_JSON") or "").strip()
    if raw:
        return json.loads(raw)
    h: dict[str, str] = {"Accept": "application/json"}
    bearer = (
        (os.getenv("HAPPIER_BEARER_TOKEN") or os.getenv("ACCOUNT_CONTEXT_BEARER_TOKEN") or "")
        .strip()
    )
    if bearer:
        h["Authorization"] = f"Bearer {bearer}"
    return h


def _apply_url_placeholders(template: str, email: str | None, customer_id: str | None) -> str:
    url = template
    if "{email}" in template:
        if not email:
            return ""
        url = template.replace("{email}", quote(email, safe=""))
    elif "{customer_id}" in template:
        if customer_id is None or str(customer_id).strip() == "":
            return ""
        url = template.replace("{customer_id}", quote(str(customer_id).strip(), safe=""))
    return url


def _resolve_account_url(
    *,
    email: str | None,
    customer_id: str | None,
) -> tuple[str, str]:
    """Return (url, source_label) or ('', '') if unconfigured."""
    generic = (os.getenv("ACCOUNT_CONTEXT_URL_TEMPLATE") or "").strip()
    if generic:
        url = _apply_url_placeholders(generic, email, customer_id)
        return url, "ACCOUNT_CONTEXT_URL_TEMPLATE"

    path = (os.getenv("HAPPIER_ACCOUNT_CONTEXT_PATH") or "").strip()
    if not path:
        return "", ""

    base = (os.getenv("HAPPIER_MAVEN_BASE_URL") or _DEFAULT_HAPPIER_BASE).rstrip("/")
    if not path.startswith("/"):
        path = "/" + path
    full_template = base + path
    url = _apply_url_placeholders(full_template, email, customer_id)
    return url, "HAPPIER_MAVEN_BASE_URL+HAPPIER_ACCOUNT_CONTEXT_PATH"


def _fetch_generic_http(
    url: str,
    *,
    timeout_sec: float,
) -> str:
    headers = _header_dict()
    method = (os.getenv("ACCOUNT_CONTEXT_HTTP_METHOD") or "GET").strip().upper()
    body_raw = (os.getenv("ACCOUNT_CONTEXT_HTTP_BODY_JSON") or "").strip()

    try:
        if method == "POST" and body_raw:
            body = json.loads(body_raw)
            resp = requests.post(url, json=body, headers=headers, timeout=timeout_sec)
        else:
            resp = requests.get(url, headers=headers, timeout=timeout_sec)
        resp.raise_for_status()
    except requests.RequestException as e:
        return f"(Account API error: {e})"

    ct = (resp.headers.get("Content-Type") or "").lower()
    if "application/json" in ct:
        try:
            return json.dumps(resp.json(), indent=2, ensure_ascii=False)[:20000]
        except ValueError:
            pass
    text = resp.text.strip()
    return text[:20000] if text else "(empty response)"


def fetch_account_context(
    *,
    email: str | None = None,
    customer_id: str | None = None,
    timeout_sec: float = 30.0,
) -> str:
    """Structured Maven block, raw JSON from a custom URL, or empty if nothing applies."""
    from maven_customer_context import (
        fetch_maven_customer_context,
        normalize_email_for_maven_lookup,
        should_use_maven_builtin,
    )

    email = normalize_email_for_maven_lookup(email)

    url, _source = _resolve_account_url(email=email, customer_id=customer_id)
    if url:
        return _fetch_generic_http(url, timeout_sec=timeout_sec)

    if should_use_maven_builtin(email=email, user_uuid=str(customer_id).strip() if customer_id else None):
        return fetch_maven_customer_context(email=email, user_uuid=customer_id, timeout_sec=timeout_sec)

    return ""


def main() -> None:
    parser = argparse.ArgumentParser(description="Smoke-test account context (HTTP template or Maven built-in).")
    parser.add_argument("--email", default=None)
    parser.add_argument("--customer-id", default=None, dest="customer_id", help="Maven user UUID when using built-in without email")
    args = parser.parse_args()

    from maven_customer_context import normalize_email_for_maven_lookup, should_use_maven_builtin

    norm_email = normalize_email_for_maven_lookup(args.email)
    url, source = _resolve_account_url(email=norm_email, customer_id=args.customer_id)

    use_maven = should_use_maven_builtin(
        email=norm_email,
        user_uuid=str(args.customer_id).strip() if args.customer_id else None,
    )

    if url:
        print(f"Resolved URL ({source}): {url[:120]}{'…' if len(url) > 120 else ''}\n")
        print(fetch_account_context(email=args.email, customer_id=args.customer_id))
    elif use_maven:
        print("Using built-in Maven API (GET /users + GET /users/{uuid}/subscriptions)\n")
        print(fetch_account_context(email=args.email, customer_id=args.customer_id))
    else:
        print(
            "No account context configured for this invocation.\n\n"
            "Either set a custom URL:\n"
            "  ACCOUNT_CONTEXT_URL_TEMPLATE=...  or  HAPPIER_ACCOUNT_CONTEXT_PATH=...\n"
            "or use built-in Maven with:\n"
            "  HAPPIER_BEARER_TOKEN=...\n"
            "and pass --email (or --customer-id with a user UUID).\n",
            file=sys.stderr,
        )
        sys.exit(2)


if __name__ == "__main__":
    main()
