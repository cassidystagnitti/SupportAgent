"""Per-conversation chat sessions with Bert for the Help Scout sidebar.

In-memory only (mirrors sidebar_server's old _status pattern): history is
lost on restart, which is fine — context rehydrates on demand and everything
the chat *does* (drafts, commits, sent replies) persists in Help Scout,
GitHub, and Notion.

See docs/superpowers/specs/2026-07-14-hs-sidebar-chat-design.md §1.
"""

from __future__ import annotations

import logging
import os
import threading
from datetime import datetime, timezone

import anthropic
import requests

import draft_registry
import orchestrator
import policy_updater
import triage_tickets
from bert import actions as bert_actions
from bert import pipeline as bert_pipeline

log = logging.getLogger("sidebar_chat")

_SUPPORT_DIR = os.path.dirname(os.path.abspath(__file__))

MODEL = os.getenv("SIDEBAR_CHAT_MODEL", "claude-sonnet-5")
MAX_SESSIONS = 200
MAX_TOOL_ITERATIONS = 8
CHAT_SYSTEM_PROMPT_PATH = os.path.join(_SUPPORT_DIR, "prompts", "sidebar_chat_system_prompt.txt")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class SessionStore:
    """Thread-safe, LRU-capped map of conversation id -> chat session."""

    def __init__(self, max_sessions: int = MAX_SESSIONS):
        self._sessions: dict[str, dict] = {}
        self._lock = threading.Lock()
        self._max = max_sessions

    def _new_session(self) -> dict:
        return {
            "api_messages": [],
            "ui_messages": [],
            "next_seq": 1,
            "ctx": None,
            "draft_thread_id": None,
            "draft_text": "",
            "proposals": {},
            "busy": False,
            "created_at": _now_iso(),
        }

    def _get_or_create_locked(self, cid: str) -> dict:
        cid = str(cid)
        if cid in self._sessions:
            self._sessions[cid] = self._sessions.pop(cid)  # refresh LRU position
            return self._sessions[cid]
        sess = self._new_session()
        self._sessions[cid] = sess
        while len(self._sessions) > self._max:
            self._sessions.pop(next(iter(self._sessions)))
        return sess

    def get_or_create(self, cid: str) -> dict:
        with self._lock:
            return self._get_or_create_locked(cid)

    def peek(self, cid: str) -> dict | None:
        with self._lock:
            return self._sessions.get(str(cid))

    def try_acquire(self, cid: str) -> tuple[dict, bool]:
        """Reserve the session for one worker turn. (session, acquired)."""
        with self._lock:
            sess = self._get_or_create_locked(cid)
            if sess["busy"]:
                return sess, False
            sess["busy"] = True
            return sess, True

    def release(self, cid: str) -> None:
        with self._lock:
            sess = self._sessions.get(str(cid))
            if sess is not None:
                sess["busy"] = False

    def add_ui_message(self, cid: str, kind: str, text: str = "", payload: dict | None = None) -> dict:
        with self._lock:
            sess = self._get_or_create_locked(cid)
            msg = {
                "seq": sess["next_seq"],
                "kind": kind,
                "text": text,
                "payload": payload,
                "ts": _now_iso(),
            }
            sess["next_seq"] += 1
            sess["ui_messages"].append(msg)
            return msg

    def ui_messages_after(self, cid: str, after: int) -> list:
        with self._lock:
            sess = self._sessions.get(str(cid))
            if sess is None:
                return []
            return [dict(m) for m in sess["ui_messages"] if m["seq"] > after]


STORE = SessionStore()


def _hs_session() -> requests.Session:
    token = orchestrator.get_access_token()
    s = requests.Session()
    s.headers.update({"Authorization": f"Bearer {token}"})
    return s


def _agent_user_id() -> int | None:
    raw = (os.getenv("HELPSCOUT_AGENT_USER_ID") or os.getenv("HELPSCOUT_NOTE_USER_ID") or "").strip()
    return int(raw) if raw.isdigit() else None


def _thread_body(hs, cid: int, thread_id) -> str:
    for t in triage_tickets._fetch_all_threads(hs, int(cid)):
        if t.get("id") == thread_id:
            return t.get("body") or ""
    return ""


def live_draft_threads(hs, cid) -> list:
    """Every live draft thread on the conversation, NEWEST FIRST.

    ``find_draft_threads`` preserves Help Scout's thread order, and Help Scout
    returns threads newest-first (the invariant ``triage_tickets`` relies on in
    ``get_conversation_text``). So the newest draft is index 0 — indexing ``[-1]``
    picks the OLDEST one, which is what the sidebar used to do while claiming the
    opposite.
    """
    return bert_pipeline.find_draft_threads(hs, int(cid))


def newest_draft_thread(hs, cid):
    """The draft thread Help Scout's reply editor is showing, or None."""
    ids = live_draft_threads(hs, cid)
    return ids[0] if ids else None


def hydrate(session_data: dict, cid: str) -> None:
    """Populate ctx + live draft info. Read-only against Help Scout."""
    hs = _hs_session()
    session_data["ctx"] = bert_pipeline.hydrate_ticket(hs, int(cid))
    thread_id = newest_draft_thread(hs, int(cid))
    session_data["draft_thread_id"] = thread_id
    session_data["draft_text"] = _thread_body(hs, int(cid), thread_id) if thread_id else ""


def _load_chat_prompt() -> str:
    with open(CHAT_SYSTEM_PROMPT_PATH, encoding="utf-8") as f:
        return f.read()


def _context_block(session_data: dict) -> str:
    ctx = session_data["ctx"]
    draft = session_data.get("draft_text") or "(no draft yet)"
    reply_mode = ("yes — an agent already replied; address the customer's latest message"
                  if ctx.get("reply_mode") else "no — first response to this ticket")
    return "\n\n".join([
        f"=== TICKET #{ctx['conversation_id']}: {ctx['subject']} ===",
        f"Customer: {ctx['customer_name']} <{ctx.get('email') or 'unknown'}>",
        f"Reply mode: {reply_mode}",
        "=== CONVERSATION ===",
        ctx.get("conversation_history") or ctx.get("body") or "(empty)",
        "=== ACCOUNT ===",
        ctx.get("account_blob") or "(unavailable)",
        "=== STRIPE ===",
        ctx.get("stripe_block") or "(unavailable)",
        "=== CURRENT DRAFT (in the Help Scout reply editor) ===",
        draft,
    ])


TOOLS = [
    {
        "name": "update_draft",
        "description": (
            "Replace the Help Scout draft reply for this ticket with new HTML "
            "(clean <p> paragraphs). Creates the draft if none exists. Use this for "
            "ANY change to the customer reply — never paste a draft into chat."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "html": {"type": "string",
                         "description": "The complete draft reply as clean <p> HTML paragraphs."},
            },
            "required": ["html"],
        },
    },
    {
        "name": "cancel_subscription",
        "description": (
            "Turn off auto-renew (cancel at period end) for THIS ticket's Stripe customer. "
            "Executes IMMEDIATELY — no confirmation step — so call it only when the support "
            "agent in this chat explicitly asks to cancel / take the action. Stripe only "
            "(Apple/Google requests stay manual). The customer is resolved server-side from "
            "the ticket; there is nothing to pass. After an 'applied' or 'already_off' result, "
            "ALWAYS update_draft so the reply states what is now true (access continues "
            "through the returned date — never say 'will renew')."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "reactivate_subscription",
        "description": (
            "Turn auto-renew back ON (un-cancel) for THIS ticket's Stripe customer — the "
            "retention save for 'I cancelled, but I'll stay if you can help on the price'. "
            "Executes IMMEDIATELY — no confirmation step. This RE-ARMS a charge on the renewal "
            "date, so call it ONLY when the customer has said they want to stay, never to "
            "'fix' a cancellation they asked for. A renewal coupon does nothing while a "
            "subscription is set to cancel, so run this BEFORE applying a discount. Stripe only. "
            "After an 'applied' result, ALWAYS update_draft so the reply states the real renewal "
            "date and amount."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "link_email",
        "description": (
            "Add another email address to THIS ticket's Help Scout CONTACT record, so every "
            "address this person writes from lands on one contact with one history. If a "
            "separate contact record already owns the address, the two are merged into this "
            "one (its conversations move over). Use when the customer says they also use "
            "another address, or you can see they wrote in before from a different one. "
            "This is Help Scout CRM housekeeping ONLY — it does NOT merge their Happier "
            "accounts, move a subscription, or copy meditation history (those are admin "
            "actions, see multi-account-merge.md), so never tell the customer their accounts "
            "were merged because of this."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "email": {"type": "string",
                          "description": "The other address belonging to this same person."},
            },
            "required": ["email"],
        },
    },
    {
        "name": "propose_policy_update",
        "description": (
            "Propose an edit to a policy doc in policies/. NOT applied — it renders as a "
            "diff card the support agent must confirm. Use when the chat establishes a "
            "policy fact that is missing or wrong in the docs."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "policy_file": {"type": "string",
                                "description": "Basename of an existing policies/*.md file, e.g. 'known-bugs.md'."},
                "edit_type": {"type": "string", "enum": ["replace", "append"]},
                "target_text": {"type": "string",
                                "description": "replace only: exact text to replace — must occur exactly once."},
                "new_text": {"type": "string",
                             "description": "Replacement text (replace) or block to append (append)."},
                "rationale": {"type": "string",
                              "description": "Why this update is correct; shown to the agent and used in the commit message."},
            },
            "required": ["policy_file", "edit_type", "new_text", "rationale"],
        },
    },
]


def _handle_update_draft(store: SessionStore, cid: str, session_data: dict, html: str) -> str:
    html = (html or "").strip()
    if not html:
        return "update_draft failed: empty html"
    hs = _hs_session()
    # Re-resolve the live drafts on EVERY call rather than trusting the id cached
    # at hydrate time. ``hydrate`` runs once per session and sessions outlive the
    # draft: once it has been sent, discarded, or replaced (by the morning review,
    # by Send & close, or by the agent in the Help Scout UI), the cached id points
    # at a thread that is no longer the draft. Patching it still succeeded, so the
    # sidebar reported "Draft updated" while nothing in the reply editor changed —
    # the "sometimes it doesn't update at all" report.
    thread_ids = live_draft_threads(hs, int(cid))
    if thread_ids:
        # Update EVERY live draft, the way bert.fanout.apply_result does. Help Scout
        # has no DELETE for draft threads, so duplicates do accumulate, and leaving
        # the others stale is how a superseded reply gets sent later.
        updated, failures = 0, []
        for tid in thread_ids:
            try:
                bert_pipeline.update_draft(hs, int(cid), int(tid), html)
                updated += 1
            except Exception as e:  # noqa: BLE001 — one bad thread must not lose the rest
                log.warning("draft update failed for cid=%s thread=%s", cid, tid, exc_info=True)
                failures.append(f"{tid}: {e}")
        if not updated:
            raise RuntimeError("no draft thread could be updated: " + "; ".join(failures))
        session_data["draft_thread_id"] = thread_ids[0]
        session_data["draft_text"] = html
        extra = f" ({updated} draft threads on this ticket)" if updated > 1 else ""
        store.add_ui_message(
            cid, "event", f"Draft updated{extra} — refresh the reply editor to see it.")
        if failures:
            store.add_ui_message(
                cid, "error", f"{len(failures)} draft thread(s) could not be updated: "
                              + "; ".join(failures)[:200])
        return f"Draft updated in place in the Help Scout reply editor{extra}."

    ctx = session_data["ctx"]
    payload: dict = {"customer": {"id": int(ctx["hs_customer_id"])}, "text": html, "draft": True}
    agent_user = _agent_user_id()
    if agent_user:
        payload["user"] = agent_user
    r = orchestrator._helpscout_post(hs, f"{orchestrator.BASE_URL}/conversations/{cid}/reply", payload)
    r.raise_for_status()
    rid = r.headers.get("Resource-ID") or r.headers.get("resource-id")
    if rid:
        draft_registry.set(str(cid), rid, _now_iso())
        session_data["draft_thread_id"] = rid
    session_data["draft_text"] = html
    store.add_ui_message(cid, "event", "Draft created — open the reply editor to see it.")
    return "Draft created in the Help Scout reply editor."


def _handle_cancel_subscription(store: SessionStore, cid: str, session_data: dict) -> str:
    """Execute cancel-at-period-end for the ticket's own Stripe customer.

    The customer id comes ONLY from the hydrated server-side context — never
    from the model — so this tool cannot act outside the open ticket.
    """
    ctx = session_data.get("ctx") or {}
    stripe_ctx = ctx.get("stripe_ctx") or {}
    customer_id = (stripe_ctx.get("stripe_customer_id") or "").strip()
    if not customer_id:
        return (
            "No Stripe customer is attached to this ticket's context (customer may be on "
            "Apple/Google or unmatched) — cannot execute. Handle as a manual action instead."
        )

    actor = f"sidebar:{_agent_user_id() or 'unknown'}"
    result = bert_actions.cancel_subscription(customer_id, cid, actor=actor)
    status = result.get("status")

    if status == "applied":
        store.add_ui_message(
            cid, "event",
            f"✅ Auto-renew turned off on {result.get('subscription_id')} — access continues "
            f"through {result.get('access_continues_through')}. Audit note posted.",
        )
        notes = "; ".join(result.get("notes") or [])
        return (
            f"Executed: auto-renew is OFF on {result.get('subscription_id')} "
            f"({customer_id}). Access continues through {result.get('access_continues_through')} — "
            f"no further charges. {('Plan notes: ' + notes) if notes else ''} "
            "Now update the draft so the reply states this outcome."
        )
    if status == "already_off":
        return (
            f"No write needed — auto-renew is already off; access continues through "
            f"{result.get('period_end_display', 'the period end')}. Update the draft to confirm "
            "they're all set (say 'access continues through …', never 'will renew')."
        )
    # refused / disabled / error — relay the reason, never claim success.
    store.add_ui_message(cid, "event", f"⚠️ Cancellation not executed: {result.get('reason', status)}")
    return (
        f"NOT executed ({status}): {result.get('reason', 'unknown')} "
        "Do not tell the customer the cancellation is done. If this needs a human, keep it as "
        "an 'Actions needed' item in the note and draft accordingly."
    )


def _handle_reactivate_subscription(store: SessionStore, cid: str, session_data: dict) -> str:
    """Restore auto-renew for the ticket's own Stripe customer.

    Like the cancel handler, the customer id comes ONLY from the hydrated
    server-side context — never from the model — so this cannot act outside
    the open ticket.
    """
    ctx = session_data.get("ctx") or {}
    stripe_ctx = ctx.get("stripe_ctx") or {}
    customer_id = (stripe_ctx.get("stripe_customer_id") or "").strip()
    if not customer_id:
        return (
            "No Stripe customer is attached to this ticket's context (customer may be on "
            "Apple/Google or unmatched) — cannot execute. Handle as a manual action instead."
        )

    actor = f"sidebar:{_agent_user_id() or 'unknown'}"
    result = bert_actions.reactivate_subscription(customer_id, cid, actor=actor)
    status = result.get("status")

    if status == "applied":
        store.add_ui_message(
            cid, "event",
            f"✅ Auto-renew restored on {result.get('subscription_id')} — renews "
            f"{result.get('renews_on')} for {result.get('renewal_amount_display')}. Audit note posted.",
        )
        return (
            f"Executed: auto-renew is back ON for {result.get('subscription_id')} ({customer_id}). "
            f"It renews {result.get('renews_on')} at {result.get('renewal_amount_display')} before "
            "any discount. If this is a retention save, apply the discount next — otherwise the "
            "customer pays full price. Now update the draft to state the real renewal date and price."
        )
    if status == "already_on":
        return (
            "No write needed — this subscription already renews. Update the draft to confirm "
            "they're all set; do not imply anything was changed."
        )
    store.add_ui_message(cid, "event", f"⚠️ Reactivation not executed: {result.get('reason', status)}")
    return (
        f"NOT executed ({status}): {result.get('reason', 'unknown')} "
        "Do not tell the customer their subscription was restored. If this needs a human, keep it "
        "as an 'Actions needed' item in the note and draft accordingly."
    )


def _handle_link_email(store: SessionStore, cid: str, session_data: dict, args: dict) -> str:
    """Attach another address to this ticket's Help Scout contact."""
    ctx = session_data.get("ctx") or {}
    result = bert_actions.link_customer_email(
        cid,
        (args or {}).get("email", ""),
        ctx.get("hs_customer_id"),
        actor=f"sidebar:{_agent_user_id() or 'unknown'}",
    )
    status, email = result.get("status"), result.get("email")

    if status == "linked":
        if result.get("already_present"):
            return f"{email} was already on this contact — nothing changed."
        store.add_ui_message(cid, "event", f"🔗 Linked {email} to this contact.")
        return (
            f"Linked {email} to this Help Scout contact — future emails from it land here. "
            "This changed Help Scout only: their Happier accounts, subscription, and meditation "
            "history are untouched, so do not say anything to the customer about merged accounts."
        )
    if status == "merged":
        moved = len(result.get("conversations_moved") or [])
        store.add_ui_message(
            cid, "event",
            f"🔗 Merged the separate contact for {email} into this one ({moved} conversation(s) moved).")
        errors = "; ".join(result.get("errors") or [])
        return (
            f"{email} belonged to a separate Help Scout contact — merged into this one: "
            f"{moved} conversation(s) moved, addresses consolidated. "
            f"{('Problems: ' + errors) if errors else ''} "
            "Help Scout records only — their Happier accounts were NOT merged and no subscription "
            "or history moved. Read the newly visible history before you finish the reply."
        )
    store.add_ui_message(cid, "event", f"⚠️ Contact not updated: {result.get('reason', status)}")
    return (
        f"NOT linked ({status}): {result.get('reason', 'unknown')} "
        "Leave the contact as it is and mention it in the internal note if a human should look."
    )


def _handle_propose_policy(store: SessionStore, cid: str, session_data: dict, args: dict) -> str:
    try:
        proposal = policy_updater.build_proposal(
            policy_file=args.get("policy_file", ""),
            edit_type=args.get("edit_type", ""),
            target_text=args.get("target_text") or "",
            new_text=args.get("new_text") or "",
            rationale=args.get("rationale") or "",
        )
    except policy_updater.ProposalError as e:
        return f"Proposal rejected: {e}"
    session_data["proposals"][proposal["id"]] = proposal
    store.add_ui_message(cid, "proposal", payload={
        "proposal_id": proposal["id"],
        "policy_file": proposal["policy_file"],
        "diff": proposal["diff"],
        "rationale": proposal["rationale"],
        "status": "pending",
    })
    return (
        "Proposal registered and shown to the agent as a diff card — it is NOT applied yet. "
        "Tell the agent it's waiting for their Confirm; do not claim the policy is updated."
    )


def run_turn(store: SessionStore, cid: str, user_text: str, client=None) -> None:
    """Run one chat turn. The caller must hold the session's busy flag; this
    function always releases it, and turns errors into visible chat messages."""
    cid = str(cid)
    session_data = store.get_or_create(cid)
    try:
        store.add_ui_message(cid, "user", user_text)
        if session_data.get("ctx") is None:
            store.add_ui_message(cid, "event", "Reading the ticket, account, and policies…")
            hydrate(session_data, cid)

        session_data["api_messages"].append({"role": "user", "content": user_text})
        if client is None:
            client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

        system_blocks = [
            {"type": "text", "text": _load_chat_prompt(),
             "cache_control": {"type": "ephemeral"}},
            {"type": "text",
             "text": f"=== POLICY DOCUMENTS ===\n{orchestrator.load_policy_docs()}\n",
             "cache_control": {"type": "ephemeral"}},
            {"type": "text", "text": _context_block(session_data)},
        ]

        for _ in range(MAX_TOOL_ITERATIONS):
            message = client.messages.create(
                model=MODEL,
                max_tokens=4096,
                system=system_blocks,
                tools=TOOLS,
                messages=session_data["api_messages"],
            )
            session_data["api_messages"].append({"role": "assistant", "content": message.content})
            text = "".join(
                b.text for b in message.content if getattr(b, "type", None) == "text"
            ).strip()
            if text:
                store.add_ui_message(cid, "bert", text)
            tool_uses = [b for b in message.content if getattr(b, "type", None) == "tool_use"]
            if not tool_uses:
                break
            results = []
            for tu in tool_uses:
                try:
                    if tu.name == "update_draft":
                        out = _handle_update_draft(store, cid, session_data,
                                                   (tu.input or {}).get("html", ""))
                    elif tu.name == "propose_policy_update":
                        out = _handle_propose_policy(store, cid, session_data, tu.input or {})
                    elif tu.name == "cancel_subscription":
                        out = _handle_cancel_subscription(store, cid, session_data)
                    elif tu.name == "reactivate_subscription":
                        out = _handle_reactivate_subscription(store, cid, session_data)
                    elif tu.name == "link_email":
                        out = _handle_link_email(store, cid, session_data, tu.input or {})
                    else:
                        out = f"Unknown tool: {tu.name}"
                except Exception as e:
                    log.exception("tool %s failed for cid=%s", tu.name, cid)
                    store.add_ui_message(cid, "error", f"{tu.name} failed: {str(e)[:200]}")
                    out = f"Tool failed: {e}"
                results.append({"type": "tool_result", "tool_use_id": tu.id, "content": out})
            session_data["api_messages"].append({"role": "user", "content": results})
        else:
            store.add_ui_message(
                cid, "error",
                "Stopped after too many tool steps — try a more specific ask.",
            )
    except Exception as e:
        log.exception("chat turn failed for cid=%s", cid)
        store.add_ui_message(cid, "error", f"Something went wrong: {str(e)[:200]}")
    finally:
        store.release(cid)
