# Mindful Minute Challenge (Apple Challenge)

# Summary

The Mindful Minute Challenge — internally also called the **Apple challenge** — is a month-long meditation challenge event we run every year for **Apple employees**. It is not a general Happier Meditation product feature, and the main support team does not own it. Tickets that reference the challenge are handled by the team behind the dedicated **Apple mailbox** in Help Scout (`3. Happier Apple Support`, id 201086 — not the main `1. Happier Support` mailbox). The correct handling for a Mindful Minute Challenge ticket is to **move the conversation to the Apple mailbox**, not to answer it from the main support queue. Support does not answer its logistics questions (registration windows, pre-registration, eligibility, prizes, dates) because the answers live with the challenge team.

**Scope — this policy is Apple-org only.** Happier runs other meditation challenges (e.g. the ENL join challenge and general in-app challenge events) that have nothing to do with Apple. Those are normal support tickets: answer them from the main mailbox under the relevant policy / saved reply, and never move them to the Apple mailbox. Only the Mindful Minute Challenge routes there.

# Trigger Conditions

- **Ticket signals:** customer asks about the Mindful Minute Challenge — registration, pre-registration, dates, eligibility, how it works, past participation, prizes/completion; customer identifies as an Apple employee asking about "the challenge" or "this year's challenge"
- **Account signals:** organizational/enterprise subscription tied to Apple; corporate email domain (`@apple.com`) is a strong signal but not required
- **Keywords / phrases:** "Mindful Minute Challenge," "mindful minute," "Apple challenge"; "the challenge" / "challenge registration" / "sign up for the challenge" / "pre-register" ONLY when the Apple context is present (Apple employee, @apple.com address, Apple org subscription, or an explicit Mindful Minute reference)
- **Non-triggers (do NOT route to Apple):** any other meditation challenge — the ENL join challenge, general in-app/community challenge events, "challenge" feature questions with no Apple signal. The word "challenge" alone is NOT enough; without an Apple/Mindful-Minute signal, handle as a normal support ticket.

# Required Context

- [ ] Does the message actually reference the challenge (vs. a generic meditation-challenge feature question)?
- [ ] Is there any *separate* support issue mixed in (billing, login, app bug)? Only the challenge portion routes away.

# Policy / Correct Response

## Standard Case

**Move the conversation to the Apple mailbox.** Do not attempt to answer challenge questions from the main support mailbox — the challenge team owns registration, dates, eligibility, and all program logistics.

- No reply is required before moving; the receiving team handles the response.
- If a holding reply is appropriate (e.g., the customer has been waiting), keep it minimal: acknowledge receipt and say the team that runs the challenge will follow up. Never state registration dates, pre-registration availability, or eligibility rules — support does not own those answers.

## Variations

- **Pure challenge question** → move to the Apple mailbox, no reply from support.
- **Challenge question mixed with a real support issue** (billing, login, bug): answer the support portion under the relevant policy from the main mailbox, and note that the challenge portion is being routed to the team that runs it. If the thread is primarily a challenge ticket with a minor support aside, resolve the aside first, then move the conversation.

## Edge Cases & Exceptions

- **Non-Apple customer asking about the Mindful Minute Challenge specifically** (heard about it by name, wants to join): it is an Apple-employee event. Route to the Apple mailbox rather than improvising an eligibility answer — the challenge team owns that messaging. (A non-Apple customer asking about a *different* challenge is a normal ticket — see Non-triggers.)
- **Ticket already drafted/answered by support before the challenge reference was noticed:** still move it; the Apple team inherits the thread history.

# Action Classification

## No Action Required (reply only)

- None. Challenge tickets always require the move action.

## Human Action Required

- **Action:** Move the conversation to the Apple mailbox (`3. Happier Apple Support`, id 201086).
- **When:** Any ticket referencing the Mindful Minute Challenge / Apple challenge.
- **How:** Automated since 2026-07-20 — `bert.fanout.move_to_apple_mailbox(session, conversation_id)` (gated on the `APPLE_MAILBOX_ID` env var; the API app's HS user has Apple-mailbox access). Falls back to a manual move in the Help Scout UI if the env var is unset or the API call fails.

## Do Not Auto-Send Conditions

- Never auto-send a reply that answers challenge logistics (dates, registration, pre-registration, eligibility, prizes) — support does not own these answers.

## Escalation Triggers

- None beyond the routing itself. The move to the Apple mailbox *is* the escalation path.

# Confidence Notes

- **High confidence areas:** identification (the challenge name is distinctive) and the routing rule (always move to the Apple mailbox).
- **Judgment call areas:** mixed tickets — how much of the support portion to resolve before moving.
- **Gaps:** challenge program details (dates, registration mechanics) are intentionally not documented here because the challenge team owns them. (Apple mailbox id confirmed 2026-07-20: 201086, `3. Happier Apple Support`.)

# Saved Reply Mapping

No saved reply in `data/saved_replies.json` covers the Mindful Minute Challenge — this is a **gap**, but a small one by design: the standard handling is a mailbox move with no reply, so at most a short "routing you to the right team" holding reply is ever needed. The adjacent reply below is for a different program and must not be used:

| Situation | Closest existing saved reply | Note |
|---|---|---|
| Customer asking to join a challenge | `Challenge ENLJoin` | Different challenge/program — do not use for Mindful Minute Challenge tickets; those route to the Apple mailbox instead |

# Related Policies

- *Escalation Policy* (general routing/escalation principles)
- *Account Lookup Data Model* (organizational-subscription signals)
- *Non-Support Requests* (contrast: those get declined/closed; Mindful Minute Challenge tickets get **moved**, never declined)
