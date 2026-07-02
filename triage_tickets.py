import argparse
import csv
import json
import os
import re
import sys
import time
from html import unescape

import anthropic
import requests
from dotenv import load_dotenv

from claude_utils import extract_text

_SUPPORT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(_SUPPORT_DIR)
load_dotenv(os.path.join(_SUPPORT_DIR, ".env"))
load_dotenv(os.path.join(ROOT_DIR, ".env"))

BASE_URL = "https://api.helpscout.net/v2"
TOKEN_URL = f"{BASE_URL}/oauth2/token"
DEFAULT_TRIAGE_MODEL = os.getenv("CLAUDE_TRIAGE_MODEL", "claude-sonnet-4-6")

APP_ID = os.getenv("HELPSCOUT_APP_ID")
APP_SECRET = os.getenv("HELPSCOUT_APP_SECRET")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")

_CSV_DIR = os.path.join(_SUPPORT_DIR, "csv")
TAGS_CSV = os.path.join(_CSV_DIR, "tags.csv")
TEAMS_CSV = os.path.join(_CSV_DIR, "teams.csv")
CUSTOM_FIELDS_CSV = os.path.join(_CSV_DIR, "custom_fields.csv")
BATCH_SIZE = 20

TRIAGE_PROMPT_PATH = os.path.join(_SUPPORT_DIR, "prompts", "triage_prompt.txt")


def _load_triage_prompt_template():
    with open(TRIAGE_PROMPT_PATH, encoding="utf-8") as f:
        return f.read()


TRIAGE_RETRY_SUFFIX = """

IMPORTANT — your last response was incomplete or invalid. Reply with ONE JSON array only. Every object MUST include:
- "tags": a non-empty array of tag names copied EXACTLY from the Allowed Tags list (same spelling).
- "team": the single best team, copied EXACTLY from one line under Allowed Teams (same spelling and spacing as listed).
- "priority": exactly "P1", "P2", or "P3".
- "tier": exactly "T1", "T2", or "T3".
If the conversation is spam, include the "spam" tag; priority and tier are still required. Team must match the list unless the spam tag applies (then team routing in Help Scout is skipped)."""


def _normalize_team_key(name):
    return re.sub(r"\s+", " ", (name or "").strip()).lower()


def get_access_token():
    resp = requests.post(TOKEN_URL, data={
        "grant_type": "client_credentials",
        "client_id": APP_ID,
        "client_secret": APP_SECRET,
    })
    resp.raise_for_status()
    return resp.json()["access_token"]


def strip_html(html):
    text = re.sub(r"<br\s*/?>", "\n", html, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    text = unescape(text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text


def api_get(session, url, params=None):
    while True:
        resp = session.get(url, params=params)
        if resp.status_code == 429:
            retry_after = int(resp.headers.get("Retry-After", 10))
            print(f"  Rate limited — waiting {retry_after}s …")
            time.sleep(retry_after)
            continue
        resp.raise_for_status()
        return resp.json()


def api_put(session, url, json_body):
    while True:
        resp = session.put(url, json=json_body)
        if resp.status_code == 429:
            retry_after = int(resp.headers.get("Retry-After", 10))
            print(f"  Rate limited — waiting {retry_after}s …")
            time.sleep(retry_after)
            continue
        resp.raise_for_status()
        return resp


def api_patch(session, url, json_body):
    while True:
        resp = session.patch(url, json=json_body)
        if resp.status_code == 429:
            retry_after = int(resp.headers.get("Retry-After", 10))
            print(f"  Rate limited — waiting {retry_after}s …")
            time.sleep(retry_after)
            continue
        resp.raise_for_status()
        return resp


def load_tags():
    tags = {}
    with open(TAGS_CSV, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            tags[row["name"].strip()] = int(row["id"])
    return tags


def load_teams():
    teams = {}
    with open(TEAMS_CSV, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            name = row["name"].strip()
            if name:
                teams[name] = int(row["id"])
    return teams


def load_custom_fields():
    """Return dict: {field_name: {"id": int, "options": {label: option_id}}}"""
    fields = {}
    with open(CUSTOM_FIELDS_CSV, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            name = row["name"].strip()
            field_id = int(row["id"])
            options = {}
            if row.get("options"):
                for pair in row["options"].split("; "):
                    label, opt_id = pair.rsplit(":", 1)
                    options[label.strip()] = int(opt_id)
            fields[name] = {"id": field_id, "options": options}
    return fields


def get_first_mailbox_id(session):
    data = api_get(session, f"{BASE_URL}/mailboxes")
    mailboxes = data.get("_embedded", {}).get("mailboxes", [])
    if not mailboxes:
        sys.exit("Error: no mailboxes found in this Help Scout account.")
    mb = mailboxes[0]
    print(f"Using mailbox: \"{mb['name']}\" (ID {mb['id']})")
    return mb["id"]


def fetch_conversation(session, conversation_id):
    return api_get(session, f"{BASE_URL}/conversations/{conversation_id}")


def fetch_unassigned_conversations(session, mailbox_id):
    conversations = []
    page = 1

    while True:
        print(f"Fetching conversations page {page} …")
        data = api_get(session, f"{BASE_URL}/conversations", params={
            "mailbox": mailbox_id,
            "status": "active",
            "sortField": "createdAt",
            "sortOrder": "desc",
            "page": page,
        })

        page_convos = data.get("_embedded", {}).get("conversations", [])
        unassigned = [c for c in page_convos if not c.get("assignee")]
        conversations.extend(unassigned)

        total_pages = data.get("page", {}).get("totalPages", 1)
        print(f"  Page {page}/{total_pages} — {len(unassigned)} unassigned of {len(page_convos)}")

        if page >= total_pages:
            break
        page += 1

    return conversations


def conversation_to_ticket(session, convo, log_prefix=""):
    """Build a ticket dict from a conversation API object; return None if skipped."""
    convo_id = convo["id"]
    subject = convo.get("subject", "(no subject)")
    existing_tags = extract_tag_names(convo.get("tags", []))
    if convo.get("assignee"):
        print(f"{log_prefix}#{convo_id}: already assigned — skipping.")
        return None
    body = get_conversation_text(session, convo_id)
    return {
        "id": convo_id,
        "subject": subject,
        "body": body or "(empty)",
        "existing_tags": existing_tags,
    }


def build_tickets_for_ids(session, conversation_ids):
    tickets = []
    for cid in conversation_ids:
        try:
            convo = fetch_conversation(session, cid)
        except requests.HTTPError as e:
            print(f"#{cid}: failed to fetch conversation ({e})")
            continue
        t = conversation_to_ticket(session, convo)
        if t:
            tickets.append(t)
    return tickets


def _fetch_all_threads(session, conversation_id):
    threads = []
    page = 1
    while True:
        data = api_get(
            session,
            f"{BASE_URL}/conversations/{conversation_id}/threads",
            params={"page": page},
        )
        page_threads = data.get("_embedded", {}).get("threads", [])
        threads.extend(page_threads)
        total_pages = data.get("page", {}).get("totalPages", 1)
        if page >= total_pages:
            break
        page += 1
    return threads


def get_conversation_text(session, conversation_id):
    threads = _fetch_all_threads(session, conversation_id)
    customer_threads = [t for t in threads if t.get("type") == "customer"]
    if not customer_threads:
        return None
    body = customer_threads[-1].get("body", "")
    return strip_html(body) if body else None


def get_conversation_history(session, conversation_id):
    """Return (history_text, latest_customer_message) for reply processing.

    history_text is a chronological transcript of all prior turns (customer +
    support), excluding the most recent customer message. latest_customer_message
    is the stripped body of that most recent customer thread.
    """
    threads = _fetch_all_threads(session, conversation_id)

    customer_threads = [t for t in threads if t.get("type") == "customer"]
    if not customer_threads:
        return "", ""

    # Threads are returned newest-first; index 0 is the most recent customer message.
    latest = customer_threads[0]
    latest_body = strip_html(latest.get("body", "") or "")

    prior_threads = [t for t in threads if t is not latest and t.get("type") in ("customer", "message")]
    # Reverse to present history oldest-first.
    lines = []
    for t in reversed(prior_threads):
        body = strip_html(t.get("body", "") or "").strip()
        if not body:
            continue
        role = "[Customer]" if t.get("type") == "customer" else "[Support]"
        lines.append(f"{role}\n{body}")

    return "\n\n".join(lines), latest_body


def extract_tag_names(tags_field):
    names = []
    for t in tags_field or []:
        if isinstance(t, dict):
            names.append(t.get("tag", t.get("name", "")))
        else:
            names.append(str(t))
    return [n for n in names if n]


def triage_batch(client, tickets, tag_names, team_names, strict=False):
    tickets_text = ""
    for t in tickets:
        body_preview = t["body"][:3000] if len(t["body"]) > 3000 else t["body"]
        tickets_text += (
            f"--- TICKET ID: {t['id']} ---\n"
            f"Subject: {t['subject']}\n"
            f"Body:\n{body_preview}\n"
            f"--- END TICKET ---\n\n"
        )

    tags_list = "\n".join(f"- {name}" for name in sorted(tag_names))
    teams_list = "\n".join(f"- {name}" for name in sorted(team_names))

    prompt = _load_triage_prompt_template().format(
        tags_list=tags_list,
        teams_list=teams_list,
        tickets_text=tickets_text,
    )
    if strict:
        prompt += TRIAGE_RETRY_SUFFIX

    message = client.messages.create(
        model=DEFAULT_TRIAGE_MODEL,
        max_tokens=8192,
        messages=[{"role": "user", "content": prompt}],
    )

    response_text = extract_text(message).strip()
    if response_text.startswith("```"):
        response_text = re.sub(r"^```(?:json)?\s*", "", response_text)
        response_text = re.sub(r"\s*```$", "", response_text)

    return json.loads(response_text)


def _claude_result_to_row(ticket, result, valid_tags, team_lookup, priority_field, tier_field):
    """Map one Claude JSON object + ticket context to the row dict used for apply."""
    raw_tags = result.get("tags", [])
    filtered_tags = [t for t in raw_tags if t in valid_tags]

    raw_team = result.get("team", "")
    team_match = team_lookup.get(_normalize_team_key(raw_team))
    team_name = team_match[0] if team_match else None
    team_id = team_match[1] if team_match else None

    raw_priority = result.get("priority", "")
    priority_option_id = (
        priority_field["options"].get(raw_priority)
        if priority_field else None
    )
    raw_tier = result.get("tier", "")
    tier_option_id = (
        tier_field["options"].get(raw_tier)
        if tier_field else None
    )

    reason = result.get("reason", "")
    return {
        **ticket,
        "new_tags": filtered_tags,
        "team_name": team_name,
        "team_id": team_id,
        "priority": raw_priority,
        "priority_option_id": priority_option_id,
        "tier": raw_tier,
        "tier_option_id": tier_option_id,
        "reason": reason,
    }


def _row_meets_requirements(row):
    """Tags, priority, and tier are always required; team is required unless spam tag is present."""
    if not row["new_tags"]:
        return False
    if not row.get("priority_option_id") or not row.get("tier_option_id"):
        return False
    is_spam = "spam" in row["new_tags"]
    if not row.get("team_id") and not is_spam:
        return False
    return True


def apply_tags(session, conversation_id, existing_tags, new_tags):
    merged = list(set(existing_tags + new_tags))
    api_put(
        session,
        f"{BASE_URL}/conversations/{conversation_id}/tags",
        {"tags": merged},
    )


def assign_team(session, conversation_id, team_id):
    api_patch(
        session,
        f"{BASE_URL}/conversations/{conversation_id}",
        {"op": "replace", "path": "/assignTo", "value": team_id},
    )


def set_spam_status(session, conversation_id):
    """Move a conversation to Help Scout's spam folder by changing its status."""
    url = f"{BASE_URL}/conversations/{conversation_id}"
    while True:
        resp = session.patch(url, json={"op": "replace", "path": "/status", "value": "spam"})
        if resp.status_code == 429:
            retry_after = int(resp.headers.get("Retry-After", 10))
            print(f"  Rate limited — waiting {retry_after}s …")
            time.sleep(retry_after)
            continue
        resp.raise_for_status()
        return resp


def set_custom_fields(session, conversation_id, fields_payload):
    """PUT the full list of custom field values onto a conversation."""
    while True:
        resp = session.put(
            f"{BASE_URL}/conversations/{conversation_id}/fields",
            json={"fields": fields_payload},
        )
        if resp.status_code == 429:
            retry_after = int(resp.headers.get("Retry-After", 10))
            print(f"  Rate limited — waiting {retry_after}s …")
            time.sleep(retry_after)
            continue
        resp.raise_for_status()
        return resp


def run_triage(
    *,
    conversation_ids=None,
    auto_apply=False,
    skip_unassigned_scan=False,
):
    """Run triage: either all unassigned in the first mailbox, or specific conversation IDs.

    If ``skip_unassigned_scan`` is True and ``conversation_ids`` is empty after fetches
    (e.g. all already assigned), return quietly (for webhook).
    """
    if not APP_ID or not APP_SECRET:
        sys.exit("Error: set HELPSCOUT_APP_ID and HELPSCOUT_APP_SECRET in your .env file.")
    if not ANTHROPIC_API_KEY:
        sys.exit("Error: set ANTHROPIC_API_KEY in your .env file.")

    print("Loading tags, teams, and custom fields …")
    valid_tags = load_tags()
    valid_teams = load_teams()
    custom_fields = load_custom_fields()
    priority_field = custom_fields.get("Priority - Urgency")
    tier_field = custom_fields.get("Tier - Complexity")
    print(f"  {len(valid_tags)} tags, {len(valid_teams)} teams, {len(custom_fields)} custom fields loaded.\n")

    if not valid_tags or not valid_teams:
        print(
            "ERROR: tags.csv and teams.csv must each contain at least one row. "
            "Cannot triage without allowed tags and teams.\n"
        )
        return

    print("Authenticating with Help Scout …")
    token = get_access_token()
    session = requests.Session()
    session.headers.update({"Authorization": f"Bearer {token}"})

    if conversation_ids:
        ids = [int(x) for x in conversation_ids]
        if len(ids) == 1:
            print(f"Triage mode: conversation #{ids[0]}.\n")
        else:
            print(f"Triage mode: {len(ids)} conversations.\n")
        tickets = build_tickets_for_ids(session, ids)
    else:
        mailbox_id = get_first_mailbox_id(session)
        conversations = fetch_unassigned_conversations(session, mailbox_id)
        print(f"\nFound {len(conversations)} unassigned conversations.\n")

        if not conversations:
            print("Nothing to process.")
            return

        tickets = []
        for i, convo in enumerate(conversations, 1):
            convo_id = convo["id"]
            subject = convo.get("subject", "(no subject)")
            print(f"[{i}/{len(conversations)}] Fetching #{convo_id}: {subject[:60]}")
            t = conversation_to_ticket(session, convo)
            if t:
                tickets.append(t)

    if not tickets:
        if skip_unassigned_scan:
            return
        print("\nNo tickets to triage.")
        return

    single_convo = len(tickets) == 1
    if single_convo:
        print(f"\nTriaging conversation #{tickets[0]['id']} with Claude …\n")
    else:
        print(f"\nTriaging {len(tickets)} conversations with Claude …\n")

    claude = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    team_lookup = {
        _normalize_team_key(name): (name, tid)
        for name, tid in valid_teams.items()
    }

    all_results = []
    for batch_start in range(0, len(tickets), BATCH_SIZE):
        batch = tickets[batch_start:batch_start + BATCH_SIZE]
        batch_num = batch_start // BATCH_SIZE + 1
        total_batches = (len(tickets) + BATCH_SIZE - 1) // BATCH_SIZE
        if single_convo and len(batch) == 1:
            print("Calling Claude …")
        else:
            print(f"Batch {batch_num}/{total_batches} ({len(batch)} conversations) → Claude …")

        try:
            results = triage_batch(claude, batch, valid_tags.keys(), valid_teams.keys())
        except json.JSONDecodeError as e:
            print(f"  Failed to parse Claude response: {e}")
            print("  Skipping this batch.")
            continue
        except Exception as e:
            print(f"  Claude API error: {e}")
            print("  Skipping this batch.")
            continue

        result_map = {int(r["id"]): r for r in results}

        for ticket in batch:
            result = result_map.get(ticket["id"])
            if not result:
                print(f"  #{ticket['id']}: Claude returned no row for this id — skipped.")
                continue

            row = _claude_result_to_row(
                ticket, result, valid_tags, team_lookup, priority_field, tier_field
            )

            if not _row_meets_requirements(row):
                print(
                    f"  #{ticket['id']}: incomplete triage "
                    f"(need ≥1 valid tag, valid team unless spam tag, P1–P3, T1–T3); retrying …"
                )
                try:
                    retry = triage_batch(
                        claude,
                        [ticket],
                        valid_tags.keys(),
                        valid_teams.keys(),
                        strict=True,
                    )
                except (json.JSONDecodeError, Exception) as e:
                    print(f"  #{ticket['id']}: retry failed ({e}) — skipped.")
                    continue
                result_map_r = {int(r["id"]): r for r in retry}
                result2 = result_map_r.get(ticket["id"])
                if not result2:
                    print(f"  #{ticket['id']}: retry returned no row — skipped.")
                    continue
                row = _claude_result_to_row(
                    ticket, result2, valid_tags, team_lookup, priority_field, tier_field
                )

            if not _row_meets_requirements(row):
                print(
                    f"  #{ticket['id']}: ERROR — still missing required tag, team, priority, or tier "
                    f"after retry. No Help Scout changes applied for this conversation."
                )
                continue

            tag_str = ", ".join(row["new_tags"])
            team_str = row["team_name"] or ("(spam — no team assign)" if "spam" in row["new_tags"] else "?")
            pri_str = row["priority"]
            tier_str = row["tier"]
            reason = row.get("reason", "")
            print(
                f"  #{ticket['id']} → tags: [{tag_str}]  team: {team_str}  "
                f"priority: {pri_str}  tier: {tier_str}  — {reason}"
            )

            all_results.append(row)

    if not all_results:
        print("\nNo triage results passed validation. Nothing to apply.")
        return

    one = len(all_results) == 1

    print(f"\n{'=' * 70}")
    if one:
        print("  Plan for this conversation")
    else:
        print(f"  Triage plan for {len(all_results)} conversations")
    print(f"{'=' * 70}")
    for r in all_results:
        tag_str = ", ".join(r["new_tags"])
        is_spam = "spam" in r["new_tags"]
        team_str = "(spam — assign team skipped)" if is_spam else r["team_name"]
        pri_str = r["priority"]
        tier_str = r["tier"]
        print(f"  #{r['id']}  {r['subject'][:50]}")
        print(f"          tags: [{tag_str}]  →  team: {team_str}  |  {pri_str} / {tier_str}")
    print(f"{'=' * 70}")

    if not auto_apply:
        if one:
            r0 = all_results[0]
            extra = (
                " and move to spam if tagged spam"
                if "spam" in r0["new_tags"]
                else ""
            )
            prompt = (
                f"\nApply tags, team, priority/tier fields{extra} "
                f"to conversation #{r0['id']}? (y/n): "
            )
        else:
            prompt = f"\nApply this plan to all {len(all_results)} conversations? (y/n): "
        answer = input(prompt).strip().lower()
        if answer != "y":
            print("Aborted — no changes made.")
            return

    print()
    tagged_count = 0
    assigned_count = 0
    spam_count = 0
    fields_count = 0
    for i, r in enumerate(all_results, 1):
        is_spam = "spam" in r["new_tags"]
        if one:
            print(f"Applying triage to conversation #{r['id']} …")
        else:
            print(f"[{i}/{len(all_results)}] Conversation #{r['id']} — ", end="")

        try:
            apply_tags(session, r["id"], r["existing_tags"], r["new_tags"])
            tagged_count += 1
            if one:
                print(f"  Tags: {', '.join(r['new_tags'])}")
            else:
                print(f"tags [{', '.join(r['new_tags'])}] … ", end="")
        except requests.HTTPError as e:
            if one:
                print(f"  Tags: FAILED ({e})")
            else:
                print(f"tag failed ({e}) … ", end="")

        if is_spam:
            try:
                set_spam_status(session, r["id"])
                spam_count += 1
                if one:
                    print("  Spam folder: moved to spam")
                else:
                    print("status → spam … ", end="")
            except requests.HTTPError as e:
                if one:
                    print(f"  Spam folder: not updated ({e})")
                else:
                    print(f"spam status failed ({e}) … ", end="")
        elif r["team_id"]:
            try:
                assign_team(session, r["id"], r["team_id"])
                assigned_count += 1
                if one:
                    print(f"  Team: {r['team_name']}")
                else:
                    print(f"→ {r['team_name']} … ", end="")
            except requests.HTTPError as e:
                if one:
                    print(f"  Team: FAILED ({e})")
                else:
                    print(f"assign failed ({e}) … ", end="")

        fields_payload = []
        if r["priority_option_id"] and priority_field:
            fields_payload.append({"id": priority_field["id"], "value": str(r["priority_option_id"])})
        if r["tier_option_id"] and tier_field:
            fields_payload.append({"id": tier_field["id"], "value": str(r["tier_option_id"])})

        try:
            set_custom_fields(session, r["id"], fields_payload)
            fields_count += 1
            if one:
                print(f"  Priority / tier: {r['priority']} / {r['tier']}")
            else:
                print(f"{r['priority']}/{r['tier']} ✓")
        except requests.HTTPError as e:
            if one:
                print(f"  Priority / tier: FAILED ({e})")
            else:
                print(f"custom fields failed ({e})")

        if not one:
            print()

    if one:
        r0 = all_results[0]
        bits = [f"tags ({', '.join(r0['new_tags'])})"]
        if r0.get("team_id"):
            bits.append(f"team → {r0['team_name']}")
        elif "spam" in r0["new_tags"]:
            bits.append("team skipped (spam)")
        bits.append(f"priority / tier → {r0['priority']} / {r0['tier']}")
        if spam_count:
            bits.append("moved to spam")
        print(f"\nDone. Conversation #{r0['id']}: " + "; ".join(bits) + ".")
    else:
        print(
            f"\nDone. Updated {len(all_results)} conversations: "
            f"{tagged_count} tagged, {assigned_count} assigned to a team, "
            f"{spam_count} moved to spam, {fields_count} with priority/tier fields set."
        )


def main():
    parser = argparse.ArgumentParser(description="Triage Help Scout tickets with Claude.")
    parser.add_argument(
        "--conversation-id",
        "-c",
        action="append",
        dest="conversation_ids",
        metavar="ID",
        help="Triage only this conversation (repeat for multiple). Default: all unassigned in first mailbox.",
    )
    parser.add_argument(
        "-y",
        "--yes",
        action="store_true",
        help="Apply triage without confirmation (for automation / webhooks).",
    )
    args = parser.parse_args()
    run_triage(
        conversation_ids=args.conversation_ids,
        auto_apply=args.yes,
    )


if __name__ == "__main__":
    main()
