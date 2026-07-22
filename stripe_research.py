"""Read-only Stripe charge-hunt research + pre-send truth check.

Implements Step 3 of policies/no-account-found-troubleshooting.md: when a
ticket carries payment identifiers (card last-4, a claimed charge with no
matching subscription), search our Stripe read-only — charges by
payment_method_details.card.last4, customers by email and by name~ — so
drafts are written from real findings instead of assumed success. Separate
from stripe_context.py, which enriches a KNOWN customer's subscription; this
module answers "does the claimed charge/customer exist in our Stripe at all".

Also exposes ``verify_claimed_stripe_objects``: a deterministic pre-send
truth check that any Stripe object a draft references (subscription id,
"I've cancelled...", "refund processed") actually exists and belongs to the
ticket's customer. Findings use the verifier rubric (bert/verify.py,
class A factual mismatch / class C over-claim, fix_type "none" — never
auto-repairable).

Uses STRIPE_READ_API_KEY only (read-only restricted key). Read-only Stripe
research is pre-approved to run autonomously (Cassidy, 2026-07-20). Fail
soft everywhere: any Stripe error becomes a "research unavailable" result,
never an exception into the pipeline.
"""

from __future__ import annotations

import logging
import os
import re
from datetime import datetime, timezone
from typing import Any

import stripe
from dotenv import load_dotenv

import account_context

_SUPPORT_DIR = os.path.dirname(os.path.abspath(__file__))
_ROOT_DIR = os.path.dirname(_SUPPORT_DIR)
load_dotenv(os.path.join(_SUPPORT_DIR, ".env"))
load_dotenv(os.path.join(_ROOT_DIR, ".env"))

log = logging.getLogger(__name__)

_SEARCH_LIMIT = 100  # one page of the Stripe search API

# --- ticket-signal extraction -------------------------------------------------

# Card last-4 mentions. All patterns require card context — a bare 4-digit
# number (year, minutes meditated) must never trigger a Stripe search.
_LAST4_PATTERNS = (
    re.compile(r"\b(?:end(?:s|ing)?)\s+(?:in|with)\s+(\d{4})\b", re.IGNORECASE),
    re.compile(r"\blast\s*(?:4|four)\s*(?:digits?)?[^0-9\n]{0,30}?(\d{4})\b", re.IGNORECASE),
    # 3+ mask chars so markdown bold ("**word** 2024") can't read as a card
    re.compile(r"[x*•]{3,}[\s-]*(\d{4})\b", re.IGNORECASE),
    re.compile(r"\b(?:card|visa|mastercard|amex|discover)\s*(?:#|number)?[\s:]*(\d{4})\b",
               re.IGNORECASE),
)

_CHARGE_LANGUAGE_RE = re.compile(
    r"\b(?:charg(?:e|ed|es)|billed|debit(?:ed)?|receipt|took (?:out )?\$)", re.IGNORECASE)
_AMOUNT_RE = re.compile(r"\$\s?(\d{1,4}(?:\.\d{2})?)\b")

# --- Stripe object ids / action claims in drafts -------------------------------

_OBJECT_ID_RE = re.compile(r"\b((?:sub|ch|py|cus|in|re)_[A-Za-z0-9]{6,})\b")

# Claims that a Stripe-affecting action already happened (or its object exists).
_ACTION_CLAIM_RES = (
    re.compile(r"\b(?:i|we)(?:'ve| have)\s+(?:gone ahead and\s+)?(?:cancel|refund)", re.IGNORECASE),
    re.compile(r"\b(?:has|have) been\s+(?:cancell?ed|refunded)", re.IGNORECASE),
    re.compile(r"\brefund\s+(?:has been|was|is)\s+(?:processed|issued|sent|on its way)",
               re.IGNORECASE),
    re.compile(r"\byour subscription\s+(?:has been|was|is now)\s+cancell?ed", re.IGNORECASE),
    re.compile(r"\b(?:i|we)(?:'ve| have)\s+processed\s+(?:the|your|a)\s+refund", re.IGNORECASE),
)


def _api_key() -> str | None:
    key = (os.environ.get("STRIPE_READ_API_KEY") or "").strip()
    return key or None


def _unavailable(reason: str) -> dict[str, Any]:
    return {"ok": False, "error": reason}


def _search_error(what: str, e: Exception) -> dict[str, Any]:
    log.warning("Stripe research %s failed (fail-soft): %s", what, e)
    return _unavailable(f"{what} failed: {e}")


def _g(obj: Any, key: str, default: Any = None) -> Any:
    """Read a field from a Stripe object (dict subclass) or a plain namespace."""
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _normalize_charge(ch: Any) -> dict[str, Any]:
    billing = _g(ch, "billing_details") or {}
    card = _g(_g(ch, "payment_method_details") or {}, "card") or {}
    return {
        "id": _g(ch, "id"),
        "amount": _g(ch, "amount"),
        "currency": _g(ch, "currency") or "",
        "created": _g(ch, "created"),
        "status": _g(ch, "status"),
        "paid": _g(ch, "paid"),
        "refunded": _g(ch, "refunded"),
        "card_last4": _g(card, "last4"),
        "customer_id": _g(ch, "customer"),
        "billing_email": _g(billing, "email"),
        "billing_name": _g(billing, "name"),
        "description": _g(ch, "description"),
    }


def _normalize_customer(cu: Any) -> dict[str, Any]:
    return {"id": _g(cu, "id"), "email": _g(cu, "email"), "name": _g(cu, "name")}


# --- search helpers (each fail-soft: {"ok": False, "error": ...}) ---------------

def search_charges_by_last4(last4: str) -> dict[str, Any]:
    """Search charges by payment_method_details.card.last4 (read-only)."""
    key = _api_key()
    if not key:
        return _unavailable("STRIPE_READ_API_KEY not set")
    last4 = (last4 or "").strip()
    if not re.fullmatch(r"\d{4}", last4):
        return _unavailable(f"invalid card last4 {last4!r} (need exactly 4 digits)")
    stripe.api_key = key
    try:
        result = stripe.Charge.search(
            query=f"payment_method_details.card.last4:'{last4}'", limit=_SEARCH_LIMIT)
    except Exception as e:
        return _search_error(f"charge search (last4 {last4})", e)
    data = _g(result, "data") or []
    return {"ok": True, "charges": [_normalize_charge(c) for c in data],
            "has_more": bool(_g(result, "has_more"))}


def search_customers_by_email(email: str) -> dict[str, Any]:
    """Search customers by exact email (read-only)."""
    key = _api_key()
    if not key:
        return _unavailable("STRIPE_READ_API_KEY not set")
    # Embedded quotes would corrupt the search query syntax; strip, don't error.
    email = (email or "").strip().lower().replace("'", "").replace('"', "")
    if not email:
        return _unavailable("empty email")
    stripe.api_key = key
    try:
        result = stripe.Customer.search(query=f"email:'{email}'", limit=_SEARCH_LIMIT)
    except Exception as e:
        return _search_error(f"customer search (email {email})", e)
    data = _g(result, "data") or []
    return {"ok": True, "customers": [_normalize_customer(c) for c in data],
            "has_more": bool(_g(result, "has_more"))}


def search_customers_by_name(name_fragment: str) -> dict[str, Any]:
    """Search customers by name substring (name~, read-only)."""
    key = _api_key()
    if not key:
        return _unavailable("STRIPE_READ_API_KEY not set")
    frag = (name_fragment or "").strip().replace("'", "").replace('"', "")
    if not frag:
        return _unavailable("empty name fragment")
    stripe.api_key = key
    try:
        result = stripe.Customer.search(query=f"name~'{frag}'", limit=_SEARCH_LIMIT)
    except Exception as e:
        return _search_error(f"customer search (name ~{frag})", e)
    data = _g(result, "data") or []
    return {"ok": True, "customers": [_normalize_customer(c) for c in data],
            "has_more": bool(_g(result, "has_more"))}


# --- date / amount scan helpers (pure) ------------------------------------------

def filter_charges_by_amount(charges: list, amount_cents: int) -> list:
    """Charges whose amount matches the claimed amount exactly (in cents)."""
    return [c for c in (charges or []) if c.get("amount") == amount_cents]


def filter_charges_by_date(charges: list, target_date, tolerance_days: int = 3) -> list:
    """Charges created within ``tolerance_days`` of the claimed date.

    ``target_date`` is a datetime.date or an ISO 'YYYY-MM-DD' string; bad
    input returns [] rather than raising.
    """
    if isinstance(target_date, str):
        try:
            target_date = datetime.strptime(target_date.strip(), "%Y-%m-%d").date()
        except ValueError:
            return []
    hits = []
    for c in charges or []:
        created = c.get("created")
        if created is None:
            continue
        try:
            charge_date = datetime.fromtimestamp(created, tz=timezone.utc).date()
        except (OSError, ValueError, OverflowError):
            continue
        if abs((charge_date - target_date).days) <= tolerance_days:
            hits.append(c)
    return hits


# --- ticket-signal detection ------------------------------------------------------

def extract_last4_candidates(text: str) -> list[str]:
    """Card last-4 digits mentioned in text (with card context), deduped in order."""
    found: dict[str, None] = {}
    for pattern in _LAST4_PATTERNS:
        for m in pattern.findall(text or ""):
            found.setdefault(m)
    return list(found)


def detect_charge_hunt_signals(text: str, account_blob: str = "") -> dict[str, Any] | None:
    """Decide whether a ticket warrants the Step 3 charge hunt.

    Triggers on: card last-4 digits anywhere in the ticket; or charge
    language + a dollar amount when the account lookup found no subscribed
    account. Returns the extracted signals, or None when the hunt shouldn't run.
    """
    text = text or ""
    if not text.strip():
        return None
    last4s = extract_last4_candidates(text)
    amounts = [int(round(float(a) * 100)) for a in _AMOUNT_RE.findall(text)]
    has_charge_language = bool(_CHARGE_LANGUAGE_RE.search(text))
    account_subscribed = "Subscribed: true" in (account_blob or "")

    if last4s:
        trigger = "last4"
    elif has_charge_language and amounts and not account_subscribed:
        trigger = "charge_no_subscription"
    else:
        return None
    return {"trigger": trigger, "last4": last4s, "amounts_cents": amounts,
            "charge_language": has_charge_language}


# --- the hunt itself -----------------------------------------------------------

def summarize_charge_hunt(*, last4s: list[str] | None = None,
                          emails: list[str] | None = None,
                          names: list[str] | None = None) -> dict[str, Any]:
    """Run every applicable read-only search and roll the results up factually.

    verdict: "match_found" (≥1 charge or customer located — matches include
    the owning customer where identifiable), "no_match" (every search ran
    clean and found nothing — the policy's decisive miss), or "unavailable"
    (key missing / searches failed with nothing found — NOT a clean miss).
    """
    last4s = [x for x in (last4s or []) if x]
    emails = list(dict.fromkeys(e.strip().lower() for e in (emails or []) if (e or "").strip()))
    names = list(dict.fromkeys(n.strip() for n in (names or []) if (n or "").strip()))
    searched = {"last4s": last4s, "emails": emails, "names": names}

    if not _api_key():
        return {"available": False, "verdict": "unavailable", "searched": searched,
                "charge_matches": [], "customer_matches": [],
                "errors": ["STRIPE_READ_API_KEY not set"], "truncated": False}

    charge_matches: list[dict] = []
    customer_matches: list[dict] = []
    errors: list[str] = []
    ran_any = False
    truncated = False

    for last4 in last4s:
        ran_any = True
        r = search_charges_by_last4(last4)
        if r["ok"]:
            charge_matches.extend(r["charges"])
            truncated = truncated or r.get("has_more", False)
        else:
            errors.append(f"charges last4 {last4}: {r['error']}")

    for email in emails:
        ran_any = True
        r = search_customers_by_email(email)
        if r["ok"]:
            for cu in r["customers"]:
                customer_matches.append({**cu, "via": f"email:'{email}'"})
            truncated = truncated or r.get("has_more", False)
        else:
            errors.append(f"customers email {email}: {r['error']}")

    for name in names:
        ran_any = True
        r = search_customers_by_name(name)
        if r["ok"]:
            seen = {c["id"] for c in customer_matches}
            for cu in r["customers"]:
                if cu["id"] not in seen:
                    customer_matches.append({**cu, "via": f"name~'{name}'"})
            truncated = truncated or r.get("has_more", False)
        else:
            errors.append(f"customers name {name}: {r['error']}")

    if charge_matches or customer_matches:
        verdict = "match_found"
    elif ran_any and not errors:
        verdict = "no_match"
    else:
        verdict = "unavailable"

    return {"available": verdict != "unavailable", "verdict": verdict,
            "searched": searched, "charge_matches": charge_matches,
            "customer_matches": customer_matches, "errors": errors,
            "truncated": truncated}


def _format_date(ts) -> str:
    if ts is None:
        return "?"
    try:
        return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")
    except (OSError, ValueError, OverflowError):
        return str(ts)


def format_charge_hunt_block(summary: dict[str, Any] | None) -> str:
    """Facts-only prompt block. Interpretation guidance lives in
    policies/no-account-found-troubleshooting.md (Step 3), which the draft
    brain already reads — this block states only what was searched and found."""
    if not summary:
        return ""
    searched = summary.get("searched") or {}
    lines = ["=== STRIPE CHARGE HUNT (read-only research — interpret per "
             "policies/no-account-found-troubleshooting.md, Step 3) ==="]
    ran = []
    for last4 in searched.get("last4s") or []:
        ran.append(f"charges with card last4 '{last4}'")
    for email in searched.get("emails") or []:
        ran.append(f"customers with email '{email}'")
    for name in searched.get("names") or []:
        ran.append(f"customers with name matching '{name}'")
    lines.append("Searches run: " + ("; ".join(ran) if ran else "(none)"))

    if summary.get("verdict") == "unavailable":
        errs = "; ".join(summary.get("errors") or []) or "unknown error"
        lines.append(f"Result: RESEARCH UNAVAILABLE — searches could not be completed ({errs}). "
                     "This is NOT evidence the charge doesn't exist.")
        return "\n".join(lines)

    charges = summary.get("charge_matches") or []
    customers = summary.get("customer_matches") or []
    if charges:
        lines.append(f"Charge matches ({len(charges)}):")
        for c in charges[:10]:
            amt = c.get("amount")
            amt_str = f"${amt / 100:.2f} {(c.get('currency') or 'usd').upper()}" if amt is not None else "?"
            owner = c.get("billing_email") or c.get("billing_name") or c.get("customer_id") or "unknown owner"
            flags = []
            if c.get("refunded"):
                flags.append("REFUNDED")
            if c.get("status") and c["status"] != "succeeded":
                flags.append(str(c["status"]))
            flag_str = f" [{', '.join(flags)}]" if flags else ""
            lines.append(f"  - {c.get('id')}: {amt_str} on {_format_date(c.get('created'))}, "
                         f"card •{c.get('card_last4') or '????'}{flag_str} — "
                         f"customer {c.get('customer_id') or '(none)'} ({owner})")
        if len(charges) > 10:
            lines.append(f"  ... and {len(charges) - 10} more")
    else:
        lines.append("Charge matches: none")
    if customers:
        lines.append(f"Customer matches ({len(customers)}):")
        for cu in customers[:10]:
            lines.append(f"  - {cu.get('id')}: {cu.get('email') or '(no email)'} / "
                         f"{cu.get('name') or '(no name)'} (via {cu.get('via', '?')})")
        if len(customers) > 10:
            lines.append(f"  ... and {len(customers) - 10} more")
    else:
        lines.append("Customer matches: none")

    if summary.get("verdict") == "no_match":
        lines.append("Result: NO MATCH — none of these searches found any charge or customer "
                     "in our Stripe.")
    if summary.get("truncated"):
        lines.append("Note: only the first page of results was scanned — more results exist "
                     "beyond what is listed above.")
    for err in summary.get("errors") or []:
        lines.append(f"Note: one search leg failed ({err}) — its results are missing above.")
    return "\n".join(lines)


def _surname(customer_name: str | None) -> str | None:
    parts = [p for p in (customer_name or "").strip().split() if p]
    if len(parts) >= 2 and len(parts[-1]) >= 3:
        return parts[-1]
    return None


def run_charge_hunt_for_ticket(*, body: str, email: str | None = None,
                               customer_name: str | None = None,
                               account_blob: str = "") -> dict[str, Any] | None:
    """Signal-gated hunt for one ticket: detect charge-hunt signals in the
    thread text and, when present, run the full read-only hunt over every
    candidate identifier (card last-4s, the contact email plus any emails in
    the ticket body, the customer's surname). Returns the summary dict, or
    None when the ticket carries no signals. Never raises."""
    try:
        signals = detect_charge_hunt_signals(body, account_blob=account_blob)
        if not signals:
            return None
        emails = ([email] if email else []) + account_context.extract_emails_from_text(body or "")
        names = [s for s in [_surname(customer_name)] if s]
        return summarize_charge_hunt(last4s=signals["last4"], emails=emails, names=names)
    except Exception as e:
        log.warning("charge hunt failed (fail-soft): %s", e, exc_info=True)
        return {"available": False, "verdict": "unavailable",
                "searched": {"last4s": [], "emails": [], "names": []},
                "charge_matches": [], "customer_matches": [], "errors": [str(e)],
                "truncated": False}


# --- pre-send truth check -------------------------------------------------------

def _rubric_finding(cls: str, detail: str, suggested_fix: str) -> dict:
    """A bert/verify.py-shaped finding. fix_type is always "none": verifying a
    claimed Stripe object needs external facts, so the repair loop must never
    touch these — they force human review."""
    return {"class": cls, "detail": detail, "fix_type": "none", "suggested_fix": suggested_fix}


def _object_owner_email(kind: str, obj: Any) -> str | None:
    """Best-effort owning email for a retrieved Stripe object (may call
    Customer.retrieve). Returns None when ownership can't be established."""
    if kind == "cus":
        return _g(obj, "email")
    if kind == "ch":
        billing = _g(obj, "billing_details") or {}
        if _g(billing, "email"):
            return _g(billing, "email")
    if kind == "in":
        if _g(obj, "customer_email"):
            return _g(obj, "customer_email")
    customer = _g(obj, "customer")
    if isinstance(customer, str) and customer:
        cu = stripe.Customer.retrieve(customer)
        return _g(cu, "email")
    if customer is not None:
        return _g(customer, "email")
    return None


_RETRIEVERS = {
    "sub": ("subscription", lambda oid: stripe.Subscription.retrieve(oid)),
    "ch": ("charge", lambda oid: stripe.Charge.retrieve(oid)),
    "py": ("charge", lambda oid: stripe.Charge.retrieve(oid)),
    "cus": ("customer", lambda oid: stripe.Customer.retrieve(oid)),
    "in": ("invoice", lambda oid: stripe.Invoice.retrieve(oid)),
    "re": ("refund", lambda oid: stripe.Refund.retrieve(oid)),
}


def _is_missing(e: Exception) -> bool:
    return (getattr(e, "code", None) == "resource_missing"
            or getattr(e, "http_status", None) == 404)


def verify_claimed_stripe_objects(result: dict, customer_email: str | None = None) -> dict[str, Any]:
    """Pre-send truth check: every Stripe object a draft references, and every
    "already done" cancellation/refund claim, must be backed by a real Stripe
    object belonging to the ticket's customer.

    Scans the draft reply plus the needs-action fields (action_description,
    action_items). Returns {"available", "findings", "checked", "errors"};
    findings are verifier-rubric dicts (class A: referenced object missing or
    owned by someone else; class C: action claim with no locatable object).
    Fail soft: a Stripe outage yields available=False and NO findings — an
    outage is not evidence of a false claim. Never raises.
    """
    out: dict[str, Any] = {"available": True, "findings": [], "checked": [], "errors": []}
    try:
        parsed = result.get("parsed") or {}
        texts = [result.get("draft_reply") or "", str(parsed.get("action_description") or "")]
        action_items = parsed.get("action_items")
        if isinstance(action_items, list):
            texts.extend(str(x) for x in action_items)
        text = "\n".join(texts)

        object_ids = list(dict.fromkeys(_OBJECT_ID_RE.findall(text)))
        claims = [rx.search(text) for rx in _ACTION_CLAIM_RES]
        claims = [m.group(0) for m in claims if m]

        if not object_ids and not claims:
            return out

        key = _api_key()
        if not key:
            out["available"] = False
            out["errors"].append("STRIPE_READ_API_KEY not set — claims unverifiable")
            return out
        stripe.api_key = key

        email = (customer_email or "").strip().lower()

        # 1. Every referenced object id must exist and belong to this customer.
        for oid in object_ids:
            prefix = oid.split("_", 1)[0]
            kind, retrieve = _RETRIEVERS[prefix]
            try:
                obj = retrieve(oid)
            except Exception as e:
                if _is_missing(e):
                    out["findings"].append(_rubric_finding(
                        "A",
                        f"draft references Stripe {kind} {oid}, which does not exist in our Stripe",
                        "Locate the customer's real Stripe object before making any claim about it."))
                    out["checked"].append({"id": oid, "exists": False})
                else:
                    out["available"] = False
                    out["errors"].append(f"{kind} {oid}: {e}")
                continue
            owner = None
            if email:
                try:
                    owner = (_object_owner_email(prefix, obj) or "").strip().lower() or None
                except Exception as e:
                    out["errors"].append(f"owner lookup for {oid}: {e}")
            out["checked"].append({"id": oid, "exists": True, "owner_email": owner})
            if email and owner and owner != email:
                out["findings"].append(_rubric_finding(
                    "A",
                    f"Stripe {kind} {oid} exists but belongs to {owner}, "
                    f"not the ticket's customer ({email})",
                    "Confirm the right customer's object before referencing it — possible "
                    "shared-card / wrong-account match."))

        # 2. An "already cancelled/refunded" claim needs a locatable object.
        if claims and not object_ids:
            located = bool((result.get("stripe_ctx") or {}).get("subscription_id"))
            if not located and email:
                r = search_customers_by_email(email)
                if not r["ok"]:
                    out["available"] = False
                    out["errors"].append(f"claim check: {r['error']}")
                elif not r["customers"]:
                    out["findings"].append(_rubric_finding(
                        "C",
                        f"draft claims \"{claims[0]}\" but no Stripe customer exists for "
                        f"{email} — the referenced action cannot have happened in our Stripe",
                        "Run the charge hunt / locate the real account before confirming "
                        "any cancellation or refund."))
                # A customer exists → the claim is at least plausibly anchored;
                # the adversarial model review judges the rest.
        return out
    except Exception as e:
        log.warning("verify_claimed_stripe_objects failed (fail-soft): %s", e, exc_info=True)
        return {"available": False, "findings": [], "checked": [], "errors": [str(e)]}
