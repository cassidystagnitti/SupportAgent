# Apple Mailbox — Ticket Intake & Link Recognition

# Summary

**Scope: Apple mailbox (`3. Happier Apple Support`, id 201086).**

How to recognize what an Apple-mailbox ticket *is* — which program, which intake path, which account — from its subject line, links, and structured fields, before picking a flow from the program docs. Built from the mailbox's most recent 200 conversations (2025-10-23 → 2026-08-11, pulled 2026-08-11), the mailbox's 69 saved replies, and the Internal KB article *Apple Mailbox Tagging*.

The single highest-value skill: **reading the issued deep link.** Both Apple programs email each person a unique tokenized link on the *same base URL* — the query string is what tells the Mindful Minute Challenge apart from Global Access. Second highest: the in-app "Failed to Join Organization" report includes the **exact account the app is signed into**, which diagnoses most tickets on sight.

# Trigger Conditions

- Any ticket containing a `my.meditatehappier.com/challenges?…` link (legacy `my.happierapp.com/challenges?…` still circulates)
- Subjects: **"Unlock Happier Meditation"**, **"Help joining organization"**, **"Re: Registration confirmation: <year> Mindful Minute Challenge"**, "Trouble joining Apple organization"
- Structured blocks in the body: `Troubleshooting Info: URL: …` or `Title: Failed to Join Organization … Email: … Org: … Challenge: … Token: …`
- Error texts: "Failed to Join Organization", "There was an issue with your unique link", "Safari cannot open the page because the address is invalid"

# Required Context

- [ ] The customer's full issued link **or** in-app report block (both carry their personal token — never work from a guessed or reused link).
- [ ] Program classification from the **query string** (below), not from how the customer describes it.
- [ ] The account the app is signed into — free from the in-app report's `Email:` line; otherwise ask (`Support WhatEmailDidYouUseToRegister FILLIN`).
- [ ] Open sibling tickets from the same customer — the two intake forms often arrive as **separate tickets** for one incident.

# Policy / Correct Response

## Standard Case — classify the link first

Both programs issue personal tokenized deep links on the same base URL:
`https://my.meditatehappier.com/challenges?org=apple&…` (older emails: `my.happierapp.com/challenges?…`, e.g. ticket #299811 — same handling).

| Program | Query-string shape | Real example (token truncated) |
|---|---|---|
| **Global Access** | `org=apple&token=<token>&event=719` — **no `challenge` param** | `…/challenges?org=apple&token=gUB8HC…smRUQ%3D%3D&event=719` (#319211, 2026-08-11) |
| **Mindful Minute Challenge** | `org=apple&challenge=apple-challenge-<year>&token=<token>&event=<id>` | `…/challenges?org=apple&challenge=apple-challenge-2025&token=u76RI…v4jrpQ%3D%3D&event=3167` (#306586) |

**Recognition rule:** a `challenge=apple-challenge-<year>` parameter → challenge token (2025's event id was `3167`). Bare `org=apple&token=…&event=719` → Global Access. Trust the `challenge=` param over the event id if a future cycle uses new ids. The token is ~88 characters of URL-encoded base64, unique per person — never share one between customers or paste one from another ticket.

Where each link comes from:

- **Global Access:** register at `https://wellness.apple.com/content/804` → Wellness emails **"Unlock Happier Meditation"** with the tokenized link.
- **Challenge:** register on the challenge signup page (2025: `people.apple.com/page/11893` / `signups.apple.com/event/…`) → Wellness (`wellness@apple.com`) emails **"Registration confirmation: <year> Mindful Minute Challenge"** — "Do not forward or share this email with anyone, the link below is uniquely assigned to you" — with the link and QR.

## The three structured intake formats

1. **"Unlock Happier Meditation"** (12 of the last 200) — the support form inside the Wellness Global Access email. Body ends with `Troubleshooting Info: URL: <the customer's own tokenized link>` — classify from that URL.
2. **"Help joining organization"** (41 of the last 200 — the most common structured intake) — sent from the in-app **Failed to Join Organization** error screen ("Go ahead and send this email as-is…"). Pre-filled fields:
   - `Title: Failed to Join Organization`
   - `Description: There was an issue with your unique link…`
   - **`Email:`** — **the account the app is currently signed into.** An `…@privaterelay.appleid.com` value = hidden Sign in with Apple account (e.g. #318913) → SIWA sign-in flow, or align to the registered address.
   - `Name:` / `Login Source:` / `Org: apple`
   - **`Challenge:`** — empty = Global Access; `apple-challenge-<year>` = challenge (42 empty vs 2 filled in the sample).
   - `Token:` — their personal token.
3. **Reply to "Registration confirmation…"** — the customer replying to their own challenge token email; the quoted Wellness email contains their link and the canonical join steps.

**Sibling tickets:** one failure frequently produces *both* forms as separate tickets (e.g. #318913 + #319211 — same customer, same token, four days apart). Check for open siblings from the same address before drafting; consolidate to one thread.

## Error-message taxonomy (observed in real tickets)

| Exact error text | Where it appears | What it usually is → response used |
|---|---|---|
| "Failed to Join Organization — There was an issue with your unique link." | In-app, after tapping the link | Most often a **sign-in mismatch**. **Taught 2026-08-28 (Alexis #316713, Aline #316652, Christopher #316573):** Classify as Global Access if `Challenge:` is blank (`org=apple`). Look up Happier admin Users for **BOTH** the ticket-from email AND the in-app report `Email:` line. If Apple org membership is on **one of those accounts**, send the login reply filled with **that address**: `Support GlobalAccesLoginEmail` (email/Google identity) or `Support GlobalAccessLoginSIWA` if the address is `…@privaterelay.appleid.com`. If **neither account** has Apple org membership (including no user found), send `Support GlobalAccessTapLinkAgain` — do not write a custom mismatch letter; do not claim Wellness-side registration. |
| "Safari cannot open the page because the address is invalid." | Tapping the link from Mail | Recurring 2026 report (#316183, #317776 — unresolved as of 2026-08-11). Start with: link opened on the iPhone that has the app; then the cancel-and-re-register recovery (`Support GlobalAccessTapLinkAgain`). Multiple reports in a short window → treat as a possible deep-link bug and flag. |
| "failed to join organization" during an open challenge window | In-app | During mmc 2025, Apple Wellness support re-sent the person's unique link directly in-thread (#299811). Token problems during an event belong to Wellness. |

The cancel-and-re-register recovery is customer-confirmed: "the instructions you gave (cancel and register) got me all sorted out" (#305675).

## What actually gets sent (164 agent replies across 200 tickets)

Roughly half of agent replies are saved replies; measured usage: `Minutes MeditationAdded` ×34 (the challenge-season workhorse — a human adds the missed session server-side, then confirms), `Support GlobalAccessTapLinkAgain` ×16, `Support GlobalAccessLoginSIWA` ×8, `Minutes CheckHealthAppSettings` ×8, `Support WhatEmailDidYouUseToRegister FILLIN` ×6, `Support GlobalAccesLoginEmail` ×6, `Support GlobalAccessInstructions` ×4, plus scattered singles. The rest are short hand-written confirmations that follow the recurring patterns below.

## Recurring hand-written replies → proposed new saved replies (verbatim from sent tickets)

These were each hand-written multiple times in the sample; none exists as a saved reply yet. Texts are word-for-word from sent replies (names swapped for placeholders):

1. **Prize handoff** (×4, e.g. #299821) — proposed name `Support PrizeWellnessWillReachOut`:
   > Hi NAME, Thanks for participating! Apple Wellness will reach out with next steps for your prize. Take care, AGENT
2. **Completion shortfall with real numbers** (×2, e.g. #299981) — proposed `Support PrizeDaysShort FILLIN` (#DAYS must come from account data):
   > Hi NAME, It looks like you completed #DAYS out of the 25 days needed to receive the prize this year. Sorry for the confusion! Take care, AGENT
3. **Account data reset done** (×2, e.g. #305045) — proposed `Support AccountDataReset`:
   > Hi NAME, I reset the data on your account so you should be all set! Take care, AGENT
4. **Challenge credit confirmed** (×2, e.g. #299566) — proposed `Support ChallengeCreditConfirmed`:
   > Hi NAME, You're all set to receive credit for the Challenge. Thanks for participating! Take care, AGENT
5. **Missed days are final** (×2, e.g. #299222) — short form of the `Support MinutesCan'tRedoMissedDay` policy:
   > Hi NAME, Thanks for writing in! Unfortunately, the meditations count for the day they are completed on so there's no way to make them up at this point. Take care, AGENT

## Tagging & workflows (Internal KB *Apple Mailbox Tagging* + observed)

- **Teams:** Apple Wellness (an automatic workflow routes all Apple Wellness conversations), Feedback (manual workflow), Other (manual tags, no workflow), Support, Tech Support.
- **During a challenge window:** the event tag — KB format `mmc 20XX`; live tag observed as **`ac: mmc 2025`**. **Outside the window:** `subscription` + `sub acquisition` (2026 tickets also carry `sub b2b` and `technical`).
- **Bugs:** challenge-specific bugs get `ac:bug`; general app bugs are unprefixed.
- **Workflows observed in threads:** "Apple Wellness" (auto), "TAG MMC2025", "TAG Support Global Subscription", "TAG & ASSIGN Subscription Get" / "Subscription Use", and "MOVE to Apple Mailbox" (tickets arriving from the main queue).

## Apple Wellness replies inside our threads

Tickets flow through the `apple@meditatehappier.com` Google Group, and the **Apple Wellness team (`wellness@apple.com`) replies directly in the same threads** — their messages render as customer-type posts authored by "Apple Wellness" (Michelle, Earl in the sample). **If Wellness has already answered, do not answer again on their behalf** — the ticket may only need closing.

Facts Wellness stated in-thread for the 2025 cycle (theirs to state, not ours to promise — refer reward-status questions to them):

- The 2025 reward (a journal) ships from a fulfillment center **~9–11 weeks after the challenge ends**; tracking at `signups.apple.com/orders` once shipped (#306427).
- Rewards go only to participants with **≥25 logged days**; Wellness checks the count (#306586).

## Volume & seasonality (sets expectations and the standing brief)

- **mmc 2025:** registration confirmations dated ~2025-09-16; event month **October 2025** (31 days, 25 needed). Ticket spike: Oct (69) + Nov (37) of the 200-ticket sample. Reward-question wave in January — matches the 9–11-week fulfillment window.
- **Since Dec 2025:** a steady Global Access trickle (1–28/month), dominated by "Help joining organization" and "Unlock Happier Meditation" tickets.
- **mmc 2026:** expect registration around **September 2026** — customers already assume the September cadence (Matthias #318146 asked in July about pre-registering; taught 2026-08-28 that there is no Happier-side pre-registration mechanism).

## Edge Cases & Exceptions

- **Pre-registration for the next challenge (taught 2026-08-28, Matthias #318146):** There is **no Happier-side mechanism** to pre-register. Apple Wellness owns the registration window; customers sign up on Wellness Web when it opens. Do not use `Support JoinClosed` for a future event that hasn't opened. Do not promise dates or workarounds.
- **Partner/spouse asks for "their own unique link":** personal tokens are per-employee; family members go through the `APPLEFAM` gift code instead (#310898 → `Support AppleFamPromoCode`).
- **Old challenge token used while the window is closed:** never troubleshoot the token — Global Access redirect (see *Global Access*).

# Action Classification

## No Action Required (reply only)

- Link classification + redirect replies, sign-in alignment, cancel-and-re-register guidance, family-code replies, prize handoffs to Wellness.

## Human Action Required

- **Add a meditation to history** (the #1 real-world action: 34 of 200 tickets) → confirm with `Minutes MeditationAdded`.
- **Account data reset**, **Android/manual benefit apply**, **token verify/reset with Wellness**.

## Do Not Auto-Send Conditions

- Any reply naming a registered address that wasn't read from the in-app report's `Email:` line or account data.
- Completion counts or prize eligibility not read from account data.
- Anything speaking for Wellness on rewards, fulfillment, or eligibility.

## Escalation Triggers

- Multiple identical link errors ("Safari cannot open…", "Failed to Join Organization") in a short window → possible deep-link or token-service bug; flag with Contact-a-Human diagnostics.
- Token or reward disputes → Apple Wellness.

# Confidence Notes

- **High confidence:** link formats, intake formats, exact error texts, tag taxonomy, usage counts — all read directly from the last 200 tickets (pulled 2026-08-11) and the Internal KB.
- **Judgment call:** future cycles may use new event ids — classify by the `challenge=` parameter, not the event number.
- **Gaps:** root cause of "Safari cannot open the page…" (two open tickets, no confirmed resolution yet); whether pre-registration for mmc 2026 will exist; the proposed saved replies above are not yet created in Help Scout.

# Saved Reply Mapping

Existing replies referenced by this doc (names exact, from `data/saved_replies_apple.json`, mailbox 201086). The five **proposed** replies are quoted verbatim above and don't exist in Help Scout yet — treat as a gap until created.

| Situation | Saved reply |
|---|---|
| Sign-in mismatch, email registration (fill address from report/account) | `Support GlobalAccesLoginEmail` |
| Sign-in mismatch, hidden SIWA (`…@privaterelay.appleid.com` in report) | `Support GlobalAccessLoginSIWA` |
| Link not working / cancel-and-re-register recovery | `Support GlobalAccessTapLinkAgain` |
| Bare Global Access claim steps | `Support GlobalAccessInstructions` |
| Challenge link during closed window | `Support JoinClosed` |
| Registration unknown, must ask | `Support WhatEmailDidYouUseToRegister FILLIN` |
| Meditation added server-side | `Minutes MeditationAdded` |
| Family member wants access | `Support AppleFamPromoCode` |

## Workhorse reply texts (verbatim)

For drafting without opening Help Scout — the period's most-used texts, word for word (`{%…%}` are Help Scout merge fields; ALL-CAPS words are FILLIN placeholders):

**`Support GlobalAccessInstructions`**
> Hi {%customer.firstName,fallback=there%},
>
> I'm glad you wrote so I can help you use the free Happier subscription you get from Apple Wellness! Claim your subscription through Wellness Web using this link. This sign up method is only available on iOS so if you're using Android, let me know and I'll put your subscription on from here.
>
> I hope you have a good day and please let us know if we can help with anything else,
> {%user.firstName%}

("this link" carries `https://wellness.apple.com/content/804`.)

**`Support GlobalAccessTapLinkAgain`**
> Hi {%customer.firstName,fallback=there%},
>
> I'm glad you wrote so I can help you use the free Happier subscription you get from Apple Wellness! First, did you start at this page on Wellness Web so you get registered with them?
> If you did, make sure the link Apple Wellness sent you is on your iPhone
> Tap it
> Then tap Open in Happier.
> If you're still having trouble you'll need to
> Cancel the registration through your Wellness page.
> Re-register by clicking the "Register" button after canceling.
>
> Also, this sign up method is only available on iOS so if you're using an Android, let me know and I'll apply access from here.
>
> I hope you have a good day and please let us know if we can help with anything else,
> {%user.firstName%}

**`Support GlobalAccesLoginEmail`** (name sic — missing an "s")
> Hi {%customer.firstName,fallback=there%},
>
> Thanks for asking about your subscription to Happier Meditation! The registration Apple Wellness has on file is ADDRESS so let's make sure that's the account you're signing into.
>
> Download the App
> You probably have the free Happier app downloaded onto your iPhone, iPad or Android mobile device already but if not, please go ahead and do that now. You don't pay to download the app.
>
> Make Sure You're on the Sign In Page
> When you open the app, you should see two choices, Get Started and Already have an account? Sign In. If you don't see this, you need to get back to it.
> Sign out of the app with the steps in this article, Sign Out of the Happier App
> or
> If you're halfway signed in, give it a quick reboot using Force Quit (Apple Devices) or Force Stop (Android device).
>
> Sign In
> When you see Already have an account? Sign In at the bottom of the screen, follow these steps:
> Tap on the words Sign In at the very bottom of the screen.
> Tap the Sign in with Email button.
> Type in your email address EMAILADDRESS.
> Type in your password. If you need to reset your password, here's our Help Center article: Reset Your Password.
> Tap Sign In.
>
> Give this a try and let us know if you're still running into trouble or if we can keep helping,
> {%user.firstName%}

**`Minutes MeditationAdded`**
> Hi {%customer.firstName,fallback=there%},
>
> I added that meditation to your history so you should be all set now. Thanks for participating!
> {%user.firstName,fallback=%}

**`Support JoinClosed`**
> Hi {%customer.firstName,fallback=there%},
>
> Thanks for your interest in this year's Mindful Minute Challenge. The join window allowing you to register and still complete this month's goal has unfortunately closed. We'd still like to have you meditate with us and shared a few steps below to help get started.
>
> Claim your complimentary Happier subscription through Wellness Web using this link. This sign up method is only available on iOS so if you're using Android, let me know and I'll put your subscription on from here.
>
> I hope you have a good day and please let us know if we can help with anything else,
> {%user.firstName%}

# Related Policies

- *Apple Mailbox Overview (Apple Wellness Programs)* — program split, key links, conventions
- *Global Access (Apple Wellness Complimentary Subscription)* — the claim flow these links feed into
- *Mindful Minute Challenge — Registration & Join (Apple Mailbox)* — join troubleshooting once classified
- *Mindful Minute Challenge — Minutes, Tracking, Medals & Prizes (Apple Mailbox)* — rewards, completion counts
- *Login Issues* / *No Account Found Troubleshooting* — deeper sign-in flows behind the mismatch cases
