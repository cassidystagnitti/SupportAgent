"""
Happier Maven API: load user by email or UUID, fetch subscriptions, format agent context.

Used for embedding + rerank when HAPPIER_BEARER_TOKEN is set and no generic ACCOUNT URL is configured.
See account_context.fetch_account_context.
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote

import requests
from dotenv import load_dotenv

_SUPPORT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(_SUPPORT_DIR)
load_dotenv(os.path.join(_SUPPORT_DIR, ".env"))
load_dotenv(os.path.join(ROOT_DIR, ".env"))

_DEFAULT_BASE = "https://my.happierapp.com/api/maven/v1"


def _maven_base() -> str:
    return (os.getenv("HAPPIER_MAVEN_BASE_URL") or _DEFAULT_BASE).rstrip("/")


def _bearer() -> str:
    return (os.getenv("HAPPIER_BEARER_TOKEN") or os.getenv("ACCOUNT_CONTEXT_BEARER_TOKEN") or "").strip()


def maven_builtin_available() -> bool:
    return bool(_bearer())


def normalize_email_for_maven_lookup(email: str | None) -> str | None:
    """Strip and lowercase. Maven stores emails lowercase; /users?email= match is case-sensitive."""
    if email is None:
        return None
    s = email.strip().lower()
    return s or None


def _headers() -> dict[str, str]:
    raw = (os.getenv("ACCOUNT_CONTEXT_HTTP_HEADERS_JSON") or "").strip()
    if raw:
        return json.loads(raw)
    tok = _bearer()
    if not tok:
        return {"Accept": "application/json"}
    return {"Accept": "application/json", "Authorization": f"Bearer {tok}"}


def _uuid_re(s: str) -> bool:
    return bool(
        re.match(
            r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
            s.strip().lower(),
        )
    )


def should_use_maven_builtin(
    *,
    email: str | None,
    user_uuid: str | None,
) -> bool:
    if not maven_builtin_available():
        return False
    if normalize_email_for_maven_lookup(email):
        return True
    if user_uuid and _uuid_re(str(user_uuid).strip()):
        return True
    return False


def _parse_dt(value: str | None) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    s = value.strip().replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return None


def _pick_primary_subscription(subs: list[dict]) -> dict | None:
    if not subs:
        return None
    now = datetime.now(timezone.utc)

    def sort_key(s: dict) -> tuple[int, datetime]:
        exp = _parse_dt(s.get("expiration_date"))
        exp_naive = exp or datetime.min.replace(tzinfo=timezone.utc)
        future = 1 if exp_naive > now else 0
        return (future, exp_naive)

    return sorted(subs, key=sort_key, reverse=True)[0]


def _organization_platform_label(user: dict[str, Any]) -> str | None:
    raw = user.get("organization_names")
    if not raw or not isinstance(raw, (list, tuple)):
        return None
    names = [str(n).strip() for n in raw if str(n).strip()]
    if not names:
        return None
    return 'Org: "' + ", ".join(names) + '"'


def _format_auto_renew(auto: Any) -> str:
    """Maven often sends 0/1 for auto_renew_status; prompts use false/true words."""
    if auto is None:
        return ""
    if isinstance(auto, bool):
        return str(auto).lower()
    if isinstance(auto, (int, float)):
        return "true" if auto else "false"
    if isinstance(auto, str):
        s = auto.strip()
        if s.isdigit():
            return "true" if int(s) else "false"
        low = s.lower()
        if low in ("true", "false"):
            return low
    return ""


def _normalize_platform(user: dict[str, Any], sub: dict[str, Any] | None) -> str:
    if sub:
        src = (sub.get("source") or "").strip().lower()
        if src == "apple":
            return "Apple"
        if src == "google":
            return "Google"
        if src == "stripe":
            return "Stripe"
        if src:
            return src.title() + " (other)"

    st = (user.get("subscription_state") or "").lower()
    codes = user.get("content_codes") or []
    code_blob = " ".join(str(c) for c in codes).lower()
    org = " ".join(user.get("organization_names") or []).lower()
    if "gift" in st or "gift" in code_blob or "gift" in org:
        return "Gift"
    if "promo" in st or "promo" in code_blob or "promotion" in st:
        return "Promo"
    if "comp" in st or "complimentary" in st:
        return "Comp"
    return "Other"


def _user_from_email(session: requests.Session, base: str, email: str) -> dict[str, Any] | None:
    url = f"{base}/users?email={quote(email, safe='@')}"
    r = session.get(url, timeout=30)
    r.raise_for_status()
    data = r.json()
    users = data.get("users") or []
    if not users:
        return None
    return users[0]


def _user_from_uuid(session: requests.Session, base: str, uuid: str) -> dict[str, Any] | None:
    url = f"{base}/users/{quote(uuid.strip(), safe='')}"
    r = session.get(url, timeout=30)
    if r.status_code == 404:
        return None
    r.raise_for_status()
    return r.json()


def _subscriptions(session: requests.Session, base: str, user_uuid: str) -> list[dict[str, Any]]:
    url = f"{base}/users/{quote(user_uuid, safe='')}/subscriptions"
    r = session.get(url, timeout=30)
    if r.status_code == 404:
        return []
    r.raise_for_status()
    data = r.json()
    return data if isinstance(data, list) else []


def format_customer_context_block(
    *,
    user: dict[str, Any] | None,
    subscriptions: list[dict[str, Any]],
) -> str:
    """Fixed labels for embedding + rerank prompts."""
    if not user:
        return "\n".join(
            [
                "Account Found: false",
                "Subscribed: false",
                "Subscription Platform: null",
                "Subscription Start Date:",
                "Subscription Expiration Date:",
                "Auto Renew Status: false",
                "Trial Status: (no account)",
            ]
        )

    sub = _pick_primary_subscription(subscriptions)
    account_found = True
    st = (user.get("subscription_state") or "").lower()
    now = datetime.now(timezone.utc)
    exp_user = _parse_dt(user.get("subscription_expiration_date"))
    exp_sub = _parse_dt(sub.get("expiration_date")) if sub else None
    exp_effective = exp_sub or exp_user

    subscribed = st in ("active", "subscribed") or (
        exp_effective is not None and exp_effective > now
    )

    org_platform = _organization_platform_label(user)
    if subscribed and org_platform:
        platform = org_platform
    elif subscribed:
        platform = _normalize_platform(user, sub)
    else:
        platform = "null"

    start = (sub.get("start_date") if sub else None) or user.get("subscription_start_date") or ""
    end = (sub.get("expiration_date") if sub else None) or user.get("subscription_expiration_date") or ""

    auto = sub.get("auto_renew_status") if sub is not None else None
    auto_str = _format_auto_renew(auto)

    if sub:
        trial_code = sub.get("trial_status") or ""
        trial_desc = sub.get("trial_status_description") or ""
        if trial_code or trial_desc:
            trial_status = f"{trial_code} — {trial_desc}".strip(" —")
        else:
            trial_status = "(trial fields empty on subscription)"
    else:
        trial_status = (
            f"(no subscription rows; user subscription_state={user.get('subscription_state')!r})"
        )

    lines = [
        f"Account Found: {str(account_found).lower()}",
        f"Subscribed: {str(subscribed).lower()}",
        f"Subscription Platform: {platform}",
        f"Subscription Start Date: {start}",
        f"Subscription Expiration Date: {end}",
        f"Auto Renew Status: {auto_str}",
        f"Trial Status: {trial_status}",
    ]
    return "\n".join(lines)


def fetch_maven_customer_context(
    *,
    email: str | None = None,
    user_uuid: str | None = None,
    timeout_sec: float = 30.0,
) -> str:
    """
    Call Maven (users + subscriptions) and return the structured text block.
    On HTTP errors, returns a block with Account Found false and an error Trial Status line.
    """
    tok = _bearer()
    if not tok:
        return format_customer_context_block(user=None, subscriptions=[])

    email = normalize_email_for_maven_lookup(email)

    base = _maven_base()
    session = requests.Session()
    session.headers.update(_headers())

    try:
        user: dict[str, Any] | None = None
        if email:
            user = _user_from_email(session, base, email)
        elif user_uuid and user_uuid.strip() and _uuid_re(user_uuid):
            user = _user_from_uuid(session, base, user_uuid.strip())
        else:
            return format_customer_context_block(user=None, subscriptions=[])

        if not user:
            return format_customer_context_block(user=None, subscriptions=[])

        uid = user.get("uuid")
        if not uid:
            return format_customer_context_block(user=user, subscriptions=[])

        subs = _subscriptions(session, base, str(uid))
        return format_customer_context_block(user=user, subscriptions=subs)
    except requests.RequestException as e:
        return "\n".join(
            [
                "Account Found: false",
                "Subscribed: false",
                "Subscription Platform: null",
                "Subscription Start Date:",
                "Subscription Expiration Date:",
                "Auto Renew Status: false",
                f"Trial Status: (Maven API error: {e})",
            ]
        )


if __name__ == "__main__":
    import argparse
    import sys

    p = argparse.ArgumentParser(description="Test Maven → customer context block.")
    p.add_argument("--email")
    p.add_argument("--customer-id", dest="uuid", help="User UUID (Maven /users/{uuid})")
    a = p.parse_args()
    if not _bearer():
        print("Set HAPPIER_BEARER_TOKEN in .env", file=sys.stderr)
        sys.exit(1)
    print(
        fetch_maven_customer_context(email=a.email, user_uuid=a.uuid),
    )
