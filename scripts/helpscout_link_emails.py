"""Link a customer's other email addresses to one Help Scout contact (and merge duplicates).

The manual counterpart to the automatic pass that runs during drafting
(``helpscout_identity.plan_ticket_identity`` / ``apply_identity_plan``). Point it
at a conversation to see exactly what the pipeline would do and why, or hand it
an explicit address when you already know the two records belong to the same
person and just want them joined.

Two modes:

    # 1. What does this ticket's contact look like, and what would we change?
    python3 scripts/helpscout_link_emails.py --conversation 3422862139

    # execute that plan (links + merges):
    python3 scripts/helpscout_link_emails.py --conversation 3422862139 --apply

    # 2. You know the address is theirs — link it, merging if another
    #    contact owns it. Your instruction is the evidence, so the ownership
    #    heuristics are skipped (the role/vendor address filter still applies).
    python3 scripts/helpscout_link_emails.py --conversation 3422862139 \
        --email old.address@gmail.com --apply

Dry-run by default: without --apply nothing is written anywhere. Writes also
require HELPSCOUT_IDENTITY_WRITES to be unset or true.

Every write appends a line to data/helpscout_identity_log.jsonl.

Exit codes: 0 = success (plan built or applied) · 2 = refused · 1 = error.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

import requests
from dotenv import load_dotenv

_SUPPORT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _SUPPORT_DIR)
load_dotenv(os.path.join(_SUPPORT_DIR, ".env"))

import helpscout_identity as identity  # noqa: E402
import orchestrator  # noqa: E402
import triage_tickets  # noqa: E402


def _session() -> requests.Session:
    session = requests.Session()
    session.headers.update({"Authorization": f"Bearer {orchestrator.get_access_token()}"})
    return session


def _describe(action: dict) -> str:
    kind = action.get("action")
    marker = {identity.LINK: "->", identity.MERGE: "=>",
              identity.PROPOSE_LINK: " ?", identity.PROPOSE_MERGE: " ?",
              identity.SKIP: " x"}.get(kind, "  ")
    line = f"  {marker} {action['email']} [{kind}]: {action.get('evidence')}"
    if action.get("dup_customer_id"):
        line += (f"\n        owned by contact {action['dup_customer_id']} "
                 f"({action.get('dup_name') or 'unnamed'}, "
                 f"{action.get('dup_conversation_count')} conversation(s))")
    if action.get("reason"):
        line += f"\n        not automatic: {action['reason']}"
    return line


def run_plan(session, conversation_id: str, *, apply: bool) -> tuple[dict, int]:
    """The full ticket pass: same plan the drafting pipeline builds."""
    convo = orchestrator.fetch_conversation(session, int(conversation_id))
    threads = orchestrator._fetch_conversation_threads(session, convo, int(conversation_id))
    customer = orchestrator._customer_from_conversation(convo)

    plan = identity.plan_ticket_identity(
        session,
        conversation_id=conversation_id,
        hs_customer_id=customer.get("id"),
        primary_email=customer.get("email") or "",
        contact_name=orchestrator._customer_display_name(customer),
        customer_text=identity.customer_text_from_threads(threads),
    )

    print(f"Conversation {conversation_id} — contact {plan.get('customer_id')} "
          f"({plan.get('contact_name') or 'unnamed'})")
    print(f"  addresses already on the contact: {', '.join(plan['existing_emails']) or 'none'}")
    if plan.get("error"):
        print(f"\nERROR: {plan['error']}", file=sys.stderr)
        return {"status": "error", "reason": plan["error"]}, 1
    if not plan["actions"]:
        print("\nNothing to change — no other addresses found in this ticket.")
        return {"status": "noop", **plan}, 0

    print("\nPLAN:")
    for action in plan["actions"]:
        print(_describe(action))

    if not apply:
        writes = [a for a in plan["actions"] if a["action"] in identity.WRITE_ACTIONS]
        print(f"\nDry run only — {len(writes)} automatic change(s) available. "
              "Re-run with --apply to execute.")
        return {"status": "plan", **plan}, 0

    applied = identity.apply_identity_plan(session, plan, actor="cli")
    print(f"\nAPPLIED: {identity.summary_line(plan, applied) or 'nothing to do'}")
    for error in applied["errors"]:
        print(f"  error: {error}", file=sys.stderr)
    return {"status": "applied", "plan": plan, "applied": applied}, 0


def run_single(session, conversation_id: str, email: str, *, apply: bool) -> tuple[dict, int]:
    """Link one named address, merging a conflicting contact into this one."""
    convo = orchestrator.fetch_conversation(session, int(conversation_id))
    customer = orchestrator._customer_from_conversation(convo)
    keep_id = customer.get("id")
    email = identity.normalize_email(email)

    ok, why = identity.is_linkable_address(email)
    if not ok:
        print(f"REFUSED: {email or '(blank)'} cannot be linked — {why}.", file=sys.stderr)
        return {"status": "refused", "reason": why}, 2

    existing = {e["value"] for e in identity.list_customer_emails(session, keep_id)}
    if email in existing:
        print(f"{email} is already on contact {keep_id} — nothing to do.")
        return {"status": "noop", "email": email}, 0

    owner = identity.find_customer_by_email(session, email)
    if owner is not None and str(owner.get("id")) != str(keep_id):
        dup_name = " ".join(x for x in (owner.get("firstName"), owner.get("lastName")) if x).strip()
        print(f"PLAN: merge contact {owner.get('id')} ({dup_name or 'unnamed'}, "
              f"{owner.get('conversationCount')} conversation(s)) into {keep_id}, "
              f"bringing {email} with it.")
        if not apply:
            print("\nDry run only — re-run with --apply to execute.")
            return {"status": "plan", "email": email, "dup_customer_id": owner.get("id")}, 0
        outcome = identity.merge_contacts(session, keep_id=keep_id, dup_id=owner.get("id"),
                                          conversation_id=conversation_id, actor="cli")
        print(f"\nMERGED: {len(outcome['conversations_moved'])} conversation(s) moved, "
              f"address(es) {', '.join(outcome['emails_moved']) or 'none'} attached to {keep_id}.")
        for error in outcome["errors"]:
            print(f"  error: {error}", file=sys.stderr)
        return {"status": "merged", "email": email, **outcome}, 0

    print(f"PLAN: link {email} to contact {keep_id} (no other contact owns it).")
    if not apply:
        print("\nDry run only — re-run with --apply to execute.")
        return {"status": "plan", "email": email}, 0
    identity.add_email(session, keep_id, email)
    identity.audit({"action": "link_email", "conversation_id": conversation_id, "actor": "cli",
                    "customer_id": keep_id, "email": email, "evidence": "operator instruction"})
    print(f"\nLINKED: {email} is now on contact {keep_id}.")
    return {"status": "linked", "email": email}, 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Link a customer's other addresses to one Help Scout contact (and merge duplicates).")
    parser.add_argument("--conversation", required=True,
                        help="Help Scout conversation id — its contact is the one kept")
    parser.add_argument("--email",
                        help="Link this specific address (skips the ownership heuristics). "
                             "Without it, the ticket is scanned the way the pipeline scans it.")
    parser.add_argument("--apply", action="store_true", help="Execute (default: dry run)")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    args = parser.parse_args(argv)

    if args.apply and not identity.writes_enabled():
        print("ERROR: contact writes are disabled (HELPSCOUT_IDENTITY_WRITES=false).", file=sys.stderr)
        return 2

    session = _session()
    try:
        if args.email:
            payload, code = run_single(session, args.conversation, args.email, apply=args.apply)
        else:
            payload, code = run_plan(session, args.conversation, apply=args.apply)
    except requests.RequestException as e:
        print(f"ERROR: Help Scout API error: {e}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True, default=str))
    return code


if __name__ == "__main__":
    sys.exit(main())
