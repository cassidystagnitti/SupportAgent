"""Keep one Help Scout contact per human.

Customers write in from whichever address is in front of them — the phone's
iCloud alias, the work account, the address they signed up with five years ago.
Help Scout keys contacts on the email address, so each one becomes a *separate*
contact record: the agent opening the ticket sees "no previous conversations"
for someone who has written eight times, and the account lookup runs against an
address that has no Happier account behind it.

This module closes that gap at intake:

  * ``plan_ticket_identity`` (READ-ONLY) collects every address the ticket
    exposes, decides which ones actually belong to this human, and asks Help
    Scout whether some other contact record already owns one.
  * ``apply_identity_plan`` (WRITES) links the verified addresses onto the
    ticket's contact and folds duplicate contacts into it.

Evidence, not guesswork. An address is linked automatically only when the
customer's own words claim it ("my other email is …", "I signed up with …") or
a Happier account under that address carries the same first name as the
contact. Everything else — a gift recipient, a forwarded receipt, a colleague on
the thread — is reported for a human and never written. A third-party marker
near the address ("my wife's email", "send the gift to …") vetoes the link
outright, even if an ownership phrase also appears.

Merges are composed by hand, because the Mailbox API has no merge endpoint: each
conversation on the duplicate contact is re-pointed at the keeper (``PATCH
/v2/conversations/{id}`` → ``/primaryCustomer.id``), then the duplicate's
addresses move over one at a time — an address can only live on one contact, so
the delete must precede the add. The emptied duplicate record is LEFT IN PLACE;
this module never deletes a contact.

The keeper is always the contact the current conversation sits on, so an
in-flight draft's ``customer.id`` stays valid while the merge runs.

Scope boundary — this touches Help Scout CRM records ONLY. It does not merge
Happier accounts, move subscriptions, or copy meditation history; those are
admin actions (policies/multi-account-merge.md). A reply must never tell a
customer their accounts were merged on the strength of what happens here.

Safety:
  * ``HELPSCOUT_IDENTITY_WRITES=false`` disables every write on a deployment.
    The plan still runs and each action is reported as a proposal instead.
  * A merge bigger than ``HELPSCOUT_IDENTITY_MERGE_MAX_CONVERSATIONS``
    (default 25) is proposed, not executed — Help Scout's own UI merge is one
    click and safer at that size.
  * Contacts whose names disagree are never merged automatically. Family
    members share surnames and payment methods; gift buyers share households.
  * Every write appends an audit line to ``data/helpscout_identity_log.jsonl``
    with enough detail to reverse it by hand.
"""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timezone
from typing import Any

import requests

log = logging.getLogger(__name__)

_SUPPORT_DIR = os.path.dirname(os.path.abspath(__file__))
AUDIT_LOG_PATH = os.path.join(_SUPPORT_DIR, "data", "helpscout_identity_log.jsonl")

BASE_URL = "https://api.helpscout.net/v2"

DEFAULT_MERGE_MAX_CONVERSATIONS = 25

# Help Scout only accepts these three on a customer email object.
EMAIL_TYPE = "other"

_EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")


# --------------------------------------------------------------------------
# Address filtering
# --------------------------------------------------------------------------

# Mailbox names that belong to a function, not a person. Linking one of these
# to a contact merges every customer who ever quoted it.
ROLE_LOCALPARTS = frozenset({
    "abuse", "accounts", "admin", "administrator", "alerts", "billing",
    "bounce", "bounces", "care", "careers", "contact", "customerservice",
    "do-not-reply", "donotreply", "feedback", "help", "hello", "hostmaster",
    "hr", "info", "invoice", "invoices", "jobs", "legal", "mail",
    "mailer-daemon", "marketing", "media", "news", "newsletter", "no-reply",
    "noreply", "notification", "notifications", "notify", "order", "orders",
    "payments", "postmaster", "press", "privacy", "receipts", "reply", "root",
    "sales", "security", "service", "support", "team", "unsubscribe",
    "updates", "webmaster",
})

# Our own domains (an agent signature is not a customer address) plus the
# vendors whose receipts customers paste in wholesale. Personal-mail domains
# that merely belong to those vendors — icloud.com, me.com, gmail.com,
# privaterelay.appleid.com — are deliberately NOT here: those are real
# customer addresses, and the Apple relay in particular is the address a Sign
# in with Apple account lives under.
BLOCKED_DOMAINS = frozenset({
    "10percenthappier.com", "apple.com", "changecollective.com", "example.com",
    "example.net", "example.org", "facebook.com", "google.com", "helpscout.com",
    "helpscout.net", "instagram.com", "intercom.io", "linear.app",
    "linkedin.com", "localhost", "mailchimp.com", "meditatehappier.com",
    "happierapp.com", "notion.so", "paypal.com", "sendgrid.net", "slack.com",
    "stripe.com", "tenpercenthappier.com", "test.com", "twitter.com",
    "zendesk.com",
})

# Subdomain families of the same vendors (email.apple.com, mail.google.com,
# payments.google.com, …).
BLOCKED_DOMAIN_SUFFIXES = (
    ".apple.com", ".google.com", ".paypal.com", ".stripe.com", ".amazonses.com",
    ".helpscout.net", ".meditatehappier.com", ".happierapp.com",
    ".tenpercenthappier.com", ".changecollective.com",
)


def normalize_email(raw: Any) -> str:
    return str(raw or "").strip().strip("<>").strip(".,;:").lower()


APPLE_RELAY_DOMAIN = "privaterelay.appleid.com"


def is_apple_reply_relay(email: str) -> bool:
    """True for an Apple relay address that encodes a SENDER, not the customer.

    Hide My Email gives a customer a random address —
    ``d8xk2mn4p9@privaterelay.appleid.com`` — and that one is genuinely theirs.
    Apple *also* mints per-sender reply-back relays whose local part spells out
    who wrote to them: ``support_at_mail_meditatehappier_com_2e4qje8gzj_…``.
    Those turn up in quoted headers on every forwarded receipt, and linking one
    would attach our own support address (or Stripe's billing robot) to a
    customer's contact. The ``_at_`` marker is what separates the two.
    """
    local, _, domain = normalize_email(email).partition("@")
    return domain == APPLE_RELAY_DOMAIN and "_at_" in local


def is_linkable_address(email: str) -> tuple[bool, str]:
    """Can this address ever be attached to a personal contact?

    Returns (ok, reason). The reason is shown to a human when ok is False.
    """
    email = normalize_email(email)
    if not email or not _EMAIL_RE.fullmatch(email):
        return False, "not a valid email address"
    local, _, domain = email.partition("@")
    if local in ROLE_LOCALPARTS:
        return False, f"role address ({local}@…), not a person"
    if domain in BLOCKED_DOMAINS or domain.endswith(BLOCKED_DOMAIN_SUFFIXES):
        return False, f"{domain} is an internal or vendor domain"
    if is_apple_reply_relay(email):
        return False, "Apple reply-relay address for a sender (from a forwarded header), not the customer's own"
    return True, ""


# --------------------------------------------------------------------------
# Ownership evidence in the customer's own words
# --------------------------------------------------------------------------

_OWNERSHIP_CUE = re.compile(
    r"(?:"
    r"\bmy\s+(?:other|old|new|original|previous|second|2nd|former|current|main|primary|"
    r"personal|work|home|backup|alternate|alternative|another)?\s*"
    r"(?:e-?mail|address|account|login|log-?in|username|user\s+name)"
    r"|\bi\s+(?:also\s+|originally\s+|accidentally\s+|first\s+|previously\s+|already\s+|"
    r"normally\s+|usually\s+)*"
    r"(?:signed\s*up|sign\s*up|registered|subscribed|created|have|had|use|used|"
    r"log\s*in|logged\s*in|sign\s*in|signed\s*in|purchased|bought|paid)"
    r"|\b(?:signed\s*up|registered|subscribed|created\s+(?:an?\s+)?account|"
    r"subscription\s+is)\s+(?:with|under|using|as|on)"
    r"|\b(?:reach|contact|email)\s+me\s+(?:at|on)"
    r"|\b(?:same|both)\s+(?:person|account)"
    r"|\bit'?s\s+(?:also\s+)?me\b"
    r"|\bthat'?s\s+(?:also\s+)?(?:my|me)\b"
    r"|\balso\s+mine\b"
    r")",
    re.IGNORECASE,
)

_THIRD_PARTY_CUE = re.compile(
    r"(?:"
    r"\bmy\s+(?:wife|husband|spouse|partner|friend|daughter|son|mom|mother|dad|father|"
    r"sister|brother|parents?|kids?|child|children|boss|colleague|co-?worker|teammate|"
    r"client|patient|student|assistant|employee|manager|team|neighbou?r|aunt|uncle|"
    r"cousin|grandmother|grandfather)"
    r"|\b(?:his|her|their)\s+(?:e-?mail|address|account|behalf)"
    r"|\bgift(?:ed|ing|s)?\b|\brecipient\b|\bon\s+behalf\s+of\b"
    r"|\bfor\s+(?:a|my)\s+(?:friend|colleague|relative)\b"
    r")",
    re.IGNORECASE,
)


def _windows_around(text: str, email: str, *, before: int = 200, after: int = 100) -> list[str]:
    """Every slice of text surrounding a mention of the address.

    A window stops at any OTHER address it would otherwise swallow, so evidence
    stays attached to the address it is about. Without that clip, "my other
    email is jane@old.com. Separately, bob@corp.com wrote to you" reads as a
    first-person claim on bob@corp.com too.
    """
    if not text or not email:
        return []
    haystack = text.lower()
    needle = email.lower()

    def _clip_start(lo: int, start: int) -> int:
        others = [m for m in _EMAIL_RE.finditer(text, lo, start) if m.group(0).lower() != needle]
        return others[-1].end() if others else lo

    def _clip_end(end: int, hi: int) -> int:
        others = [m for m in _EMAIL_RE.finditer(text, end, hi) if m.group(0).lower() != needle]
        return others[0].start() if others else hi

    out: list[str] = []
    start = haystack.find(needle)
    while start != -1:
        end = start + len(needle)
        lo = _clip_start(max(0, start - before), start)
        hi = _clip_end(end, min(len(text), end + after))
        out.append(text[lo:hi])
        start = haystack.find(needle, end)
    return out


def claims_ownership(customer_text: str, email: str) -> bool:
    """True when the customer's own words claim this address, unopposed.

    A third-party marker anywhere near ANY mention vetoes the claim — "I signed
    up with a@b.com, please move my wife's c@d.com too" must not silently link
    c@d.com, and an ambiguous sentence should reach a human rather than a write.
    """
    windows = _windows_around(customer_text, email)
    if not windows:
        return False
    if any(_THIRD_PARTY_CUE.search(w) for w in windows):
        return False
    return any(_OWNERSHIP_CUE.search(w) for w in windows)


def mentions_third_party(customer_text: str, email: str) -> bool:
    return any(_THIRD_PARTY_CUE.search(w) for w in _windows_around(customer_text, email))


def _first_name(value: Any) -> str:
    """Comparable first name: 'Paul ' → 'paul', '' → ''."""
    return re.sub(r"[^a-z]", "", str(value or "").strip().lower().split(" ")[0])


def names_agree(a: Any, b: Any) -> bool:
    """True when two first names match. Blank on either side is NOT agreement."""
    na, nb = _first_name(a), _first_name(b)
    return bool(na) and na == nb


def names_conflict(a: Any, b: Any) -> bool:
    """True only when both names are present and differ."""
    na, nb = _first_name(a), _first_name(b)
    return bool(na) and bool(nb) and na != nb


def account_first_name(email: str) -> str | None:
    """First name on the Happier account for this address, if any. Fail-soft."""
    try:
        import maven_customer_context as maven

        if not maven.maven_builtin_available():
            return None
        session = requests.Session()
        session.headers.update(maven._headers())
        user = maven._user_from_email(session, maven._maven_base(), email)
        return (user or {}).get("first_name") or None
    except Exception:
        log.debug("account_first_name lookup failed for %s", email, exc_info=True)
        return None


# --------------------------------------------------------------------------
# Help Scout reads
# --------------------------------------------------------------------------

def list_customer_emails(session: requests.Session, customer_id: int | str) -> list[dict]:
    """Every email object ({id, value, type}) on a contact. Values lowercased."""
    r = session.get(f"{BASE_URL}/customers/{customer_id}/emails", timeout=30)
    r.raise_for_status()
    emails = (r.json() or {}).get("_embedded", {}).get("emails", []) or []
    return [
        {"id": e.get("id"), "value": normalize_email(e.get("value")), "type": e.get("type")}
        for e in emails
        if e.get("value")
    ]


def get_customer(session: requests.Session, customer_id: int | str) -> dict:
    r = session.get(f"{BASE_URL}/customers/{customer_id}", timeout=30)
    r.raise_for_status()
    return r.json() or {}


def find_customer_by_email(session: requests.Session, email: str) -> dict | None:
    """The contact that currently owns this address, or None.

    Help Scout enforces one owner per address, so this is the authoritative
    conflict check: a hit with a different id is the duplicate contact.
    """
    email = normalize_email(email)
    if not email:
        return None
    r = session.get(f"{BASE_URL}/customers", params={"email": email}, timeout=30)
    r.raise_for_status()
    found = (r.json() or {}).get("_embedded", {}).get("customers", []) or []
    return found[0] if found else None


def conversations_for_email(
    session: requests.Session,
    email: str,
    *,
    status: str = "all",
    max_pages: int = 20,
) -> list[dict]:
    """Every conversation Help Scout associates with this address.

    Used to size and then execute a merge. Embedded quotes would corrupt the
    query syntax, so they are stripped (degrades the match, never errors).
    """
    email = normalize_email(email).replace('"', "")
    if not email:
        return []
    out: list[dict] = []
    page = 1
    while page <= max_pages:
        r = session.get(
            f"{BASE_URL}/conversations",
            params={"query": f'(email:"{email}")', "status": status, "page": page},
            timeout=30,
        )
        r.raise_for_status()
        data = r.json() or {}
        convos = data.get("_embedded", {}).get("conversations", []) or []
        out.extend(convos)
        total_pages = ((data.get("page") or {}).get("totalPages")) or 1
        if page >= total_pages or not convos:
            break
        page += 1
    return out


# --------------------------------------------------------------------------
# Help Scout writes (audited)
# --------------------------------------------------------------------------

def writes_enabled() -> bool:
    """Per-deployment kill switch. Default ON — linking is the point."""
    raw = (os.getenv("HELPSCOUT_IDENTITY_WRITES") or "").strip().lower()
    return raw not in ("false", "0", "off", "no")


def merge_max_conversations() -> int:
    raw = (os.getenv("HELPSCOUT_IDENTITY_MERGE_MAX_CONVERSATIONS") or "").strip()
    try:
        return max(1, int(raw))
    except ValueError:
        return DEFAULT_MERGE_MAX_CONVERSATIONS


def audit(entry: dict) -> None:
    """Append one line to the identity audit log. Never raises."""
    try:
        os.makedirs(os.path.dirname(AUDIT_LOG_PATH), exist_ok=True)
        line = {"ts": datetime.now(timezone.utc).isoformat(), **entry}
        with open(AUDIT_LOG_PATH, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(line, default=str) + "\n")
    except Exception:
        log.warning("identity audit write failed: %s", entry, exc_info=True)


def add_email(session: requests.Session, customer_id: int | str, email: str) -> int | None:
    """POST a new address onto a contact. Returns the new email id if given."""
    r = session.post(
        f"{BASE_URL}/customers/{customer_id}/emails",
        json={"type": EMAIL_TYPE, "value": normalize_email(email)},
        timeout=30,
    )
    r.raise_for_status()
    rid = r.headers.get("Resource-Id") or r.headers.get("Resource-ID") or r.headers.get("resource-id")
    return int(rid) if rid and str(rid).isdigit() else None


def delete_email(session: requests.Session, customer_id: int | str, email_id: int | str) -> None:
    r = session.delete(f"{BASE_URL}/customers/{customer_id}/emails/{email_id}", timeout=30)
    r.raise_for_status()


def reassign_conversation(session: requests.Session, conversation_id: int | str, customer_id: int | str) -> None:
    """Re-point one conversation at a different contact."""
    r = session.patch(
        f"{BASE_URL}/conversations/{conversation_id}",
        json={"op": "replace", "path": "/primaryCustomer.id", "value": int(customer_id)},
        timeout=30,
    )
    r.raise_for_status()


# --------------------------------------------------------------------------
# Planning (read-only)
# --------------------------------------------------------------------------

LINK = "link"
MERGE = "merge"
PROPOSE_LINK = "propose_link"
PROPOSE_MERGE = "propose_merge"
SKIP = "skip"

# Actions that write. Everything else is a report for a human.
WRITE_ACTIONS = (LINK, MERGE)


def _candidate_emails(
    *,
    primary_email: str,
    customer_text: str,
    account_emails: list[str] | None,
    extra_candidates: list[dict] | None,
) -> list[dict]:
    """Every address the ticket exposes, deduped, with where it came from."""
    seen: dict[str, dict] = {}

    def _add(email: str, source: str, *, presumed_strong: bool = False) -> None:
        email = normalize_email(email)
        if not email or email == normalize_email(primary_email):
            return
        if email in seen:
            seen[email]["sources"].append(source)
            seen[email]["presumed_strong"] = seen[email]["presumed_strong"] or presumed_strong
            return
        seen[email] = {"email": email, "sources": [source], "presumed_strong": presumed_strong}

    for email in _EMAIL_RE.findall(customer_text or ""):
        _add(email, "customer message")
    for email in account_emails or []:
        _add(email, "account lookup")
    for cand in extra_candidates or []:
        _add(cand.get("email", ""), cand.get("source") or "caller", presumed_strong=bool(cand.get("strong")))

    return list(seen.values())


def classify_candidate(
    candidate: dict,
    *,
    customer_text: str,
    contact_name: str,
    lookup_account_name=account_first_name,
) -> dict:
    """Decide whether one address may be linked automatically.

    STRONG (auto-link) needs one of:
      * the customer's own words claiming it, or
      * a Happier account under that address whose first name matches the
        contact's, or
      * a caller that already verified ownership (``strong`` on the candidate).

    Everything else is reported, not written.
    """
    email = candidate["email"]
    ok, reason = is_linkable_address(email)
    if not ok:
        return {**candidate, "strength": "blocked", "evidence": reason}

    if mentions_third_party(customer_text, email):
        return {**candidate, "strength": "blocked",
                "evidence": "described as someone else's address (family member, gift recipient, third party)"}

    if candidate.get("presumed_strong"):
        return {**candidate, "strength": "strong",
                "evidence": f"ownership verified by {candidate['sources'][0]}"}

    if claims_ownership(customer_text, email):
        return {**candidate, "strength": "strong", "evidence": "customer claims it in their own message"}

    account_name = lookup_account_name(email)
    if account_name and names_agree(account_name, contact_name):
        return {**candidate, "strength": "strong",
                "evidence": f"Happier account under this address is also named {account_name}"}
    if account_name and names_conflict(account_name, contact_name):
        return {**candidate, "strength": "weak",
                "evidence": f"Happier account under this address is named {account_name}, "
                            f"contact is {contact_name or 'unnamed'} — different person?"}
    if account_name:
        return {**candidate, "strength": "weak",
                "evidence": "Happier account exists under this address but the names cannot be compared"}

    return {**candidate, "strength": "weak", "evidence": "mentioned in the ticket, no ownership claim"}


def plan_ticket_identity(
    session: requests.Session,
    *,
    conversation_id: int | str,
    hs_customer_id: int | str,
    primary_email: str,
    contact_name: str = "",
    customer_text: str = "",
    account_emails: list[str] | None = None,
    extra_candidates: list[dict] | None = None,
    lookup_account_name=account_first_name,
) -> dict:
    """Work out what should happen to this contact. Performs no writes.

    ``customer_text`` must be CUSTOMER-authored text only — an address we typed
    into an agent reply is not the customer claiming it.
    """
    plan = {
        "conversation_id": conversation_id,
        "customer_id": hs_customer_id,
        "primary_email": normalize_email(primary_email),
        "contact_name": contact_name,
        "existing_emails": [],
        "actions": [],
        "writes_enabled": writes_enabled(),
        "error": None,
    }
    if not hs_customer_id:
        plan["error"] = "no Help Scout customer id on the conversation"
        return plan

    try:
        existing = list_customer_emails(session, hs_customer_id)
    except Exception as e:
        plan["error"] = f"could not read contact emails: {e}"
        return plan
    plan["existing_emails"] = [e["value"] for e in existing]
    already = set(plan["existing_emails"]) | {plan["primary_email"]}

    candidates = _candidate_emails(
        primary_email=plan["primary_email"],
        customer_text=customer_text,
        account_emails=account_emails,
        extra_candidates=extra_candidates,
    )

    max_convos = merge_max_conversations()

    for candidate in candidates:
        email = candidate["email"]
        if email in already:
            continue

        verdict = classify_candidate(
            candidate,
            customer_text=customer_text,
            contact_name=contact_name,
            lookup_account_name=lookup_account_name,
        )
        if verdict["strength"] == "blocked":
            plan["actions"].append({**verdict, "action": SKIP})
            continue

        # Does another contact already own it? That is the merge case.
        try:
            owner = find_customer_by_email(session, email)
        except Exception as e:
            plan["actions"].append({**verdict, "action": SKIP,
                                    "evidence": f"{verdict['evidence']}; owner lookup failed: {e}"})
            continue

        if owner is None:
            plan["actions"].append({
                **verdict,
                "action": LINK if verdict["strength"] == "strong" else PROPOSE_LINK,
            })
            continue

        if str(owner.get("id")) == str(hs_customer_id):
            continue  # already ours — the emails listing was stale

        dup_name = " ".join(x for x in (owner.get("firstName"), owner.get("lastName")) if x).strip()
        dup = {
            **verdict,
            "dup_customer_id": owner.get("id"),
            "dup_name": dup_name,
            "dup_conversation_count": owner.get("conversationCount"),
        }

        blockers = []
        if verdict["strength"] != "strong":
            blockers.append(verdict["evidence"])
        if names_conflict(dup_name, contact_name):
            blockers.append(f"contact names disagree ({dup_name or 'unnamed'} vs {contact_name or 'unnamed'})")
        count = owner.get("conversationCount")
        if isinstance(count, int) and count > max_convos:
            blockers.append(f"{count} conversations to move (over the {max_convos} limit) — "
                            "merge it in the Help Scout UI instead")

        if blockers:
            plan["actions"].append({**dup, "action": PROPOSE_MERGE, "reason": "; ".join(blockers)})
        else:
            plan["actions"].append({**dup, "action": MERGE})

    return plan


def plan_has_writes(plan: dict) -> bool:
    return any(a.get("action") in WRITE_ACTIONS for a in plan.get("actions", []))


# --------------------------------------------------------------------------
# Applying (writes)
# --------------------------------------------------------------------------

def merge_contacts(
    session: requests.Session,
    *,
    keep_id: int | str,
    dup_id: int | str,
    conversation_id: int | str,
    actor: str = "bert",
) -> dict:
    """Fold the duplicate contact into the keeper.

    Conversations move first, then the addresses. An address can only live on
    one contact, so each move is delete-then-add; a failed add is rolled back
    onto the duplicate so the address is never lost. The emptied duplicate
    record is left in place — Help Scout's UI can finish it off, and nothing
    here deletes customer data.
    """
    result: dict[str, Any] = {
        "keep_id": keep_id, "dup_id": dup_id, "conversations_moved": [],
        "emails_moved": [], "errors": [],
    }

    try:
        dup_emails = list_customer_emails(session, dup_id)
    except Exception as e:
        result["errors"].append(f"could not read duplicate's emails: {e}")
        return result

    # 1. Re-point every conversation on the duplicate at the keeper. A
    # conversation can match more than one of the duplicate's addresses, so
    # track what has already moved rather than re-patching it.
    moved: set = set()
    for email in dup_emails:
        try:
            convos = conversations_for_email(session, email["value"], status="all")
        except Exception as e:
            result["errors"].append(f"conversation search for {email['value']} failed: {e}")
            continue
        for convo in convos:
            cid = convo.get("id")
            owner_id = (convo.get("primaryCustomer") or {}).get("id")
            if cid is None or cid in moved or str(owner_id) != str(dup_id):
                continue
            try:
                reassign_conversation(session, cid, keep_id)
                moved.add(cid)
                result["conversations_moved"].append(cid)
            except Exception as e:
                result["errors"].append(f"conversation {cid}: {e}")

    # 2. Move the addresses across, one at a time.
    for email in dup_emails:
        value, email_id = email["value"], email["id"]
        try:
            delete_email(session, dup_id, email_id)
        except Exception as e:
            result["errors"].append(f"{value}: could not detach from duplicate ({e})")
            continue
        try:
            add_email(session, keep_id, value)
            result["emails_moved"].append(value)
        except Exception as e:
            result["errors"].append(f"{value}: detached from duplicate but could not attach to keeper ({e})")
            try:
                add_email(session, dup_id, value)
                result["errors"].append(f"{value}: restored to the duplicate contact")
            except Exception as rollback_error:
                result["errors"].append(
                    f"{value}: ROLLBACK FAILED ({rollback_error}) — address is now on no contact, re-add it by hand")

    audit({
        "action": "merge_contacts", "conversation_id": conversation_id, "actor": actor,
        "keep_customer_id": keep_id, "dup_customer_id": dup_id,
        "conversations_moved": result["conversations_moved"],
        "emails_moved": result["emails_moved"], "errors": result["errors"],
    })
    return result


def apply_identity_plan(session: requests.Session, plan: dict, *, actor: str = "bert") -> dict:
    """Execute a plan's LINK and MERGE actions. Never raises."""
    applied: dict[str, Any] = {"linked": [], "merged": [], "errors": [], "skipped_disabled": []}
    cid = plan.get("conversation_id")
    keep_id = plan.get("customer_id")

    if not writes_enabled():
        applied["skipped_disabled"] = [a["email"] for a in plan.get("actions", [])
                                       if a.get("action") in WRITE_ACTIONS]
        return applied

    for action in plan.get("actions", []):
        kind, email = action.get("action"), action.get("email")
        try:
            if kind == LINK:
                add_email(session, keep_id, email)
                applied["linked"].append(email)
                audit({"action": "link_email", "conversation_id": cid, "actor": actor,
                       "customer_id": keep_id, "email": email, "evidence": action.get("evidence")})
            elif kind == MERGE:
                outcome = merge_contacts(
                    session, keep_id=keep_id, dup_id=action["dup_customer_id"],
                    conversation_id=cid, actor=actor)
                applied["merged"].append({"email": email, **outcome})
                applied["errors"].extend(outcome["errors"])
        except Exception as e:
            applied["errors"].append(f"{email}: {e}")
            audit({"action": kind, "conversation_id": cid, "actor": actor,
                   "customer_id": keep_id, "email": email, "error": str(e)})

    return applied


# --------------------------------------------------------------------------
# Reporting
# --------------------------------------------------------------------------

def _esc(value: Any) -> str:
    return (str(value).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def summary_line(plan: dict, applied: dict | None = None) -> str:
    """One-line summary for logs and the morning-review scorecard."""
    applied = applied or {}
    bits = []
    if applied.get("linked"):
        bits.append(f"linked {len(applied['linked'])}")
    if applied.get("merged"):
        moved = sum(len(m.get("conversations_moved", [])) for m in applied["merged"])
        bits.append(f"merged {len(applied['merged'])} contact(s), {moved} conversation(s)")
    proposals = [a for a in plan.get("actions", []) if a.get("action") in (PROPOSE_LINK, PROPOSE_MERGE)]
    if proposals:
        bits.append(f"{len(proposals)} to review")
    if applied.get("skipped_disabled"):
        bits.append(f"{len(applied['skipped_disabled'])} held (writes off)")
    if applied.get("errors"):
        bits.append(f"{len(applied['errors'])} error(s)")
    return "; ".join(bits)


def identity_note_html(plan: dict, applied: dict | None = None) -> str:
    """Internal-note HTML for what happened (and what a human should decide).

    Returns "" when there is nothing worth a note — the common case.
    """
    applied = applied or {}
    items: list[str] = []

    for email in applied.get("linked", []):
        action = next((a for a in plan.get("actions", []) if a.get("email") == email), {})
        items.append(f"<li>✅ Linked <strong>{_esc(email)}</strong> to this contact — "
                     f"{_esc(action.get('evidence', 'verified'))}.</li>")

    for merged in applied.get("merged", []):
        moved = len(merged.get("conversations_moved", []))
        emails = ", ".join(merged.get("emails_moved", [])) or "none"
        items.append(
            f"<li>🔗 Merged duplicate contact <strong>{_esc(merged.get('dup_id'))}</strong> into this one — "
            f"{moved} conversation(s) moved, address(es): {_esc(emails)}. "
            "The emptied duplicate record was left in place.</li>")

    for action in plan.get("actions", []):
        kind = action.get("action")
        if kind == PROPOSE_LINK:
            items.append(
                f"<li>❓ <strong>{_esc(action['email'])}</strong> appears in this ticket but was not linked — "
                f"{_esc(action.get('evidence'))}. Add it to the contact if it is theirs.</li>")
        elif kind == PROPOSE_MERGE:
            items.append(
                f"<li>❓ <strong>{_esc(action['email'])}</strong> belongs to a separate contact "
                f"(<strong>{_esc(action.get('dup_customer_id'))}</strong>"
                f"{', ' + _esc(action['dup_name']) if action.get('dup_name') else ''}, "
                f"{_esc(action.get('dup_conversation_count'))} conversation(s)) — not merged: "
                f"{_esc(action.get('reason') or action.get('evidence'))}.</li>")

    for email in applied.get("skipped_disabled", []):
        items.append(f"<li>⏸️ <strong>{_esc(email)}</strong> was ready to link, but contact writes are "
                     "disabled on this deployment (HELPSCOUT_IDENTITY_WRITES=false).</li>")

    for error in applied.get("errors", []):
        items.append(f"<li>⚠️ {_esc(error)}</li>")

    if plan.get("error"):
        items.append(f"<li>⚠️ Contact check did not run: {_esc(plan['error'])}</li>")

    if not items:
        return ""

    return (
        "<p><strong>Contact records</strong> (Help Scout only — this does not merge Happier "
        "accounts, move subscriptions, or copy meditation history)</p>"
        f"<ul>{''.join(items)}</ul>"
    )


def sync_ticket_identity(
    session: requests.Session,
    *,
    conversation_id: int | str,
    hs_customer_id: int | str,
    primary_email: str,
    contact_name: str = "",
    customer_text: str = "",
    account_emails: list[str] | None = None,
    extra_candidates: list[dict] | None = None,
    actor: str = "bert",
    apply: bool = True,
    lookup_account_name=account_first_name,
) -> dict:
    """Plan and (optionally) apply in one call. Never raises.

    Returns {"plan": …, "applied": …, "note_html": …, "summary": …}.
    """
    empty = {"linked": [], "merged": [], "errors": [], "skipped_disabled": []}
    try:
        plan = plan_ticket_identity(
            session,
            conversation_id=conversation_id,
            hs_customer_id=hs_customer_id,
            primary_email=primary_email,
            contact_name=contact_name,
            customer_text=customer_text,
            account_emails=account_emails,
            extra_candidates=extra_candidates,
            lookup_account_name=lookup_account_name,
        )
    except Exception as e:
        log.warning("identity plan failed for conversation %s", conversation_id, exc_info=True)
        plan = {"conversation_id": conversation_id, "customer_id": hs_customer_id,
                "actions": [], "error": str(e)}
        return {"plan": plan, "applied": empty,
                "note_html": identity_note_html(plan, empty), "summary": ""}

    applied = apply_identity_plan(session, plan, actor=actor) if apply else empty
    return {
        "plan": plan,
        "applied": applied,
        "note_html": identity_note_html(plan, applied),
        "summary": summary_line(plan, applied),
    }


def customer_text_from_threads(threads: list | None) -> str:
    """Text of the CUSTOMER-authored threads only, oldest first.

    Agent replies and internal notes are excluded on purpose: an address we
    typed into a reply is not the customer claiming it, and our own signature
    would otherwise read as a candidate on every ticket.
    """
    from triage_tickets import strip_html

    parts = [
        strip_html(t.get("body") or "").strip()
        for t in reversed(threads or [])
        if t.get("type") == "customer"
    ]
    return "\n\n".join(p for p in parts if p)
