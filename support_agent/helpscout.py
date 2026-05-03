from __future__ import annotations

import time
from typing import Any
from urllib.parse import urlparse

import httpx

HELPSCOUT_API = "https://api.helpscout.net/v2"


class HelpScoutError(RuntimeError):
    pass


class HelpScout:
    """Mailbox API 2.0 client (OAuth2 client credentials)."""

    def __init__(self, client_id: str, client_secret: str) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._token: str | None = None
        self._token_expires_at: float = 0.0

    def _ensure_token(self) -> str:
        now = time.time()
        if self._token and now < self._token_expires_at - 60:
            return self._token

        with httpx.Client(timeout=60.0) as client:
            r = client.post(
                f"{HELPSCOUT_API}/oauth2/token",
                data={
                    "grant_type": "client_credentials",
                    "client_id": self._client_id,
                    "client_secret": self._client_secret,
                },
            )
        if r.status_code != 200:
            raise HelpScoutError(f"OAuth token failed: {r.status_code} {r.text}")
        data = r.json()
        self._token = data["access_token"]
        self._token_expires_at = now + float(data.get("expires_in", 172800))
        return self._token

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: Any | None = None,
        follow_redirects: bool = False,
    ) -> httpx.Response:
        token = self._ensure_token()
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        url = f"{HELPSCOUT_API}{path}" if path.startswith("/") else f"{HELPSCOUT_API}/{path}"
        with httpx.Client(timeout=120.0) as client:
            r = client.request(
                method,
                url,
                headers=headers,
                params=params,
                json=json_body,
                follow_redirects=follow_redirects,
            )
        if r.status_code == 401:
            self._token = None
            token = self._ensure_token()
            headers["Authorization"] = f"Bearer {token}"
            with httpx.Client(timeout=120.0) as client:
                r = client.request(
                    method,
                    url,
                    headers=headers,
                    params=params,
                    json=json_body,
                    follow_redirects=follow_redirects,
                )
        return r

    def get_conversation(self, conversation_id: int) -> dict[str, Any]:
        r = self._request(
            "GET",
            f"/conversations/{conversation_id}",
            params={"embed": "threads"},
            follow_redirects=False,
        )
        if r.status_code == 301:
            loc = r.headers.get("Location") or ""
            new_id = _conversation_id_from_url(loc)
            if not new_id:
                raise HelpScoutError(f"Conversation moved but no id in Location: {loc!r}")
            return self.get_conversation(new_id)
        if r.status_code != 200:
            raise HelpScoutError(f"get conversation {conversation_id}: {r.status_code} {r.text}")
        return r.json()

    def list_threads(self, conversation_id: int) -> list[dict[str, Any]]:
        """Full thread bodies (paginated); use when embed=threads is truncated."""
        page = 1
        all_threads: list[dict[str, Any]] = []
        while True:
            r = self._request(
                "GET",
                f"/conversations/{conversation_id}/threads",
                params={"page": page},
                follow_redirects=False,
            )
            if r.status_code == 301:
                loc = r.headers.get("Location") or ""
                new_id = _conversation_id_from_url(loc)
                if not new_id:
                    raise HelpScoutError(
                        f"Threads: merged conversation, could not parse Location {loc!r}"
                    )
                return self.list_threads(new_id)
            if r.status_code != 200:
                raise HelpScoutError(f"list threads {conversation_id}: {r.status_code} {r.text}")
            data = r.json()
            chunk = (data.get("_embedded") or {}).get("threads") or []
            all_threads.extend(chunk)
            pager = data.get("page") or {}
            total_pages = int(pager.get("totalPages") or 1)
            if page >= total_pages:
                break
            page += 1
        return all_threads

    def list_conversations(
        self,
        *,
        mailbox_id: int | None,
        status: str = "active",
        sort_field: str = "waitingSince",
        sort_order: str = "asc",
        page: int = 1,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            "status": status,
            "sortField": sort_field,
            "sortOrder": sort_order,
            "page": page,
        }
        if mailbox_id is not None:
            params["mailbox"] = mailbox_id
        r = self._request("GET", "/conversations", params=params)
        if r.status_code != 200:
            raise HelpScoutError(f"list conversations: {r.status_code} {r.text}")
        return r.json()

    def create_webhook(
        self,
        *,
        url: str,
        secret: str,
        events: list[str],
        label: str | None = None,
        mailbox_ids: list[int] | None = None,
    ) -> int:
        body: dict[str, Any] = {
            "url": url,
            "secret": secret,
            "events": events,
            "payloadVersion": "V2",
        }
        if label:
            body["label"] = label
        if mailbox_ids:
            body["mailboxIds"] = mailbox_ids
        r = self._request("POST", "/webhooks", json_body=body)
        if r.status_code != 201:
            raise HelpScoutError(f"create webhook: {r.status_code} {r.text}")
        raw = r.headers.get("Resource-Id") or r.headers.get("Resource-ID")
        if raw:
            return int(raw)
        raise HelpScoutError("create webhook: missing Resource-Id header")

    def create_draft_reply(self, conversation_id: int, *, customer_id: int, text: str) -> int | None:
        r = self._request(
            "POST",
            f"/conversations/{conversation_id}/reply",
            json_body={
                "customer": {"id": customer_id},
                "text": text,
                "draft": True,
            },
        )
        if r.status_code not in (200, 201):
            raise HelpScoutError(f"draft reply: {r.status_code} {r.text}")
        raw = r.headers.get("Resource-Id") or r.headers.get("Resource-ID")
        if raw:
            return int(raw)
        return None

    def merge_tags(self, conversation_id: int, existing: list[str], add: str) -> None:
        tags = sorted({*existing, add})
        r = self._request(
            "PUT",
            f"/conversations/{conversation_id}/tags",
            json_body={"tags": tags},
        )
        if r.status_code not in (200, 204):
            raise HelpScoutError(f"update tags: {r.status_code} {r.text}")


def conversation_tag_names(conv: dict[str, Any]) -> list[str]:
    out: list[str] = []
    for t in conv.get("tags") or []:
        if isinstance(t, dict):
            name = t.get("tag")
            if name:
                out.append(str(name))
        elif isinstance(t, str):
            out.append(t)
    return out


def _conversation_id_from_url(loc: str) -> int | None:
    if not loc:
        return None
    path = urlparse(loc).path.rstrip("/")
    if "/conversations/" not in path:
        return None
    tail = path.split("/conversations/")[-1]
    part = tail.split("/")[0]
    try:
        return int(part)
    except ValueError:
        return None


def primary_customer_id(conv: dict[str, Any]) -> int:
    pc = conv.get("primaryCustomer") or {}
    cid = pc.get("id")
    if cid is None:
        raise HelpScoutError("Conversation has no primaryCustomer.id")
    return int(cid)
