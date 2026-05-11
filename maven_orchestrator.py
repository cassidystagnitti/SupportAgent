"""Maven AGI support pipeline: triage → account → Stripe (optional) → Maven draft → Help Scout."""

from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timezone
from typing import Any, Callable, Optional

import requests
from dotenv import load_dotenv
from mavenagi import MavenAGI
from mavenagi.commons import EntityIdBase
from mavenagi.conversation.types.stream_response import StreamResponse_End, StreamResponse_Text

_SUPPORT_DIR = os.path.dirname(os.path.abspath(__file__))
_ROOT_DIR = os.path.dirname(_SUPPORT_DIR)
load_dotenv(os.path.join(_SUPPORT_DIR, ".env"))
load_dotenv(os.path.join(_ROOT_DIR, ".env"))

from account_context import fetch_account_contexts_for_ticket, fetch_customer_emails_from_helpscout  # noqa: E402
from orchestrator import (  # noqa: E402
    _customer_display_name,
    _customer_from_conversation,
    _extract_tag_names,
    _helpscout_post,
    _html_escape,
    _subscription_platform,
    _update_conversation_tags,
)
from product_prioritization import run_product_prioritization  # noqa: E402
from stripe_context import fetch_stripe_context, format_stripe_context  # noqa: E402
from triage_tickets import (  # noqa: E402
    BASE_URL,
    fetch_conversation,
    get_access_token,
    get_conversation_history,
    get_conversation_text,
    run_triage,
)

log = logging.getLogger("maven_orchestrator")


def _maven_client() -> MavenAGI:
    org_id = os.getenv("MAVEN_ORG_ID", "")
    agent_id = os.getenv("MAVEN_AGENT_ID", "")
    app_id = os.getenv("MAVEN_APP_ID", "")
    app_secret = os.getenv("MAVEN_APP_SECRET", "")
    missing = [k for k, v in {
        "MAVEN_ORG_ID": org_id,
        "MAVEN_AGENT_ID": agent_id,
        "MAVEN_APP_ID": app_id,
        "MAVEN_APP_SECRET": app_secret,
    }.items() if not v]
    if missing:
        raise RuntimeError(f"Missing Maven env vars: {', '.join(missing)}")
    return MavenAGI(
        organization_id=org_id,
        agent_id=agent_id,
        app_id=app_id,
        app_secret=app_secret,
    )
