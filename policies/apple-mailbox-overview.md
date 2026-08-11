# Apple Mailbox Overview (Apple Wellness Programs)

# Summary

**Scope: this doc and the other `apple-*` program docs apply to tickets in the Apple mailbox (`3. Happier Apple Support`, id 201086).** Main-mailbox tickets that mention the Mindful Minute Challenge still get *moved* there per *Mindful Minute Challenge (Apple Challenge)* — these docs govern what happens after the move.

The Apple mailbox handles Happier's partnership with **Apple Wellness**. There are exactly two programs, and correctly telling them apart is the single most important skill in this mailbox:

| Program | What it is | When | Signup path |
|---|---|---|---|
| **Mindful Minute Challenge** | Annual month-long meditation event for Apple employees (≥1 mindful minute/day, 25 days out of the month) | One month per year; join window opens/closes around it | Challenge registration on Wellness Web → confirmation email with a **unique link/QR (token)** → tap on iPhone → "Open in Happier" |
| **Global Access** | Year-round complimentary Happier subscription — a wellness benefit for Apple employees | Always available | **Global Access page on Wellness Web: `https://wellness.apple.com/content/804`** → register → tap the issued link on iPhone → "Open in Happier" |

**Current period (as of 2026-08-11): the challenge join window is CLOSED; Global Access is the active signup path.** The 2025 cycle ran registration from mid-September 2025 with October 2025 as the event month, so expect **mmc 2026 registration to open around September 2026** — re-confirm dates with the team as it approaches. During the closed period, never troubleshoot a challenge link/token — redirect to Global Access. See *Global Access (Apple Wellness Complimentary Subscription)*.

Both programs issue personal tokenized deep links on the same base URL (`my.meditatehappier.com/challenges?org=apple&…`); classify by query string — `challenge=apple-challenge-<year>` = challenge token, bare `token=…&event=719` = Global Access. Full recognition rules, intake formats, and error taxonomy: *Apple Mailbox — Ticket Intake & Link Recognition*.

# Trigger Conditions

- Any ticket in the Apple mailbox; senders are Apple employees (family members via the family promo code also land here)
- Signals: "Apple Wellness," "Wellness Web," "Mindful Minute Challenge," "my free subscription from Apple," `@apple.com` addresses, join links/QR codes, token errors

# Required Context

- [ ] Which program is this about — the Challenge (event, tokens, minutes, prizes) or Global Access (year-round subscription)? Ambiguous "sign me up" requests during the closed period = Global Access.
- [ ] What account is the app signed into (email vs. hidden Sign in with Apple address), and what address does Apple Wellness have on file?
- [ ] Device: iPhone/iPad (self-serve flows) or Android (support applies the benefit manually; the Challenge itself is iOS-only)?

# Policy / Correct Response

## Program routing (which doc to use)

- Which program is a link/ticket even about, structured intake forms ("Unlock Happier Meditation" / "Help joining organization"), error-message taxonomy, tagging → *Apple Mailbox — Ticket Intake & Link Recognition*
- Signup, locked content, subscription claim, link confusion, Android access, accidental purchase, renewal, family code → *Global Access (Apple Wellness Complimentary Subscription)*
- Challenge registration/join errors, tokens, password resets while joining, friends/Circle → *Mindful Minute Challenge — Registration & Join (Apple Mailbox)*
- Minutes not counting, Health app, calendar, medals, prizes, completion → *Mindful Minute Challenge — Minutes, Tracking, Medals & Prizes (Apple Mailbox)*

## Key links (use these exact URLs)

| Purpose | Link |
|---|---|
| **Global Access signup (Wellness Web)** | `https://wellness.apple.com/content/804` |
| Issued personal deep links (both programs; unique token per person — never reuse) | `https://my.meditatehappier.com/challenges?org=apple&token=…&event=719` (Global Access) / `…&challenge=apple-challenge-<year>&token=…&event=<id>` (challenge) |
| Challenge signup (period-specific; do NOT send while join is closed) | `https://people.apple.com/page/11893`; also seen: `https://signups.apple.com/event/1712-fda4` |
| Mindful Minute Challenge FAQ (footer link on challenge replies) | `https://www.meditatehappier.com/support/apple-challenge-faq` |
| Password reset | `https://my.meditatehappier.com/passwords/new` |
| App Store / Play Store | `http://apple.co/1V7sqo9` / `https://play.google.com/store/apps/details?id=com.changecollective.tenpercenthappier` |
| Help Center: what address app is signed into / sign out / sign into existing account / reset password | support.meditatehappier.com articles 92 / 51 / 52 / 15 |
| Help Center: connect Health app / add minutes via Health / hidden SIWA address | articles 21 / 87 / 314 |
| Apple refunds | receipt "Report a Problem" / `reportaproblem.apple.com` / AppleCare billing (`https://support.apple.com/en-us/HT201232`) |
| Force Quit (iOS) / Force Stop (Android) | `https://support.apple.com/en-us/HT201330` / `https://support.google.com/android/answer/2668665` |

Domain note: the live Help Center is **support.meditatehappier.com** and the FAQ lives on **www.meditatehappier.com**. A couple of older saved replies link `happierapp.com` variants — don't copy those into new drafts.

## Identifying the account (first step of almost every troubleshoot)

The fix for most tickets is aligning three things: the address **Apple Wellness has on file**, the **Happier account registration**, and what the **app is currently signed into**.

- Customer signed into the app: Profile icon → Settings (gear) → Account under MEMBERSHIP → read **Login Method** and **Email** (`Support WhatEmailDidYouUseToRegister FILLIN` flow).
- No account found under their email: ask for other addresses and have them check for a **hidden Sign in with Apple address**: Settings app → their name → Sign-In & Security → Sign in with Apple → Happier → send the `...@privaterelay.appleid.com` string (`SNIPPET SIWACheckSettingsForMaskedAddress`, Help Center article 314).
- Need device-level data: have them send a support request via app Settings → SUPPORT → **Contact a Human** (`Support SendASupportTicket`), or during the event via the Challenge feed → **Email Support**, choosing Apple Mail so diagnostic data stays attached (`Support SendSupportEmailFromChallenge`).

## Account operations (same as main mailbox, Apple-flavored replies exist)

- **Email/registration change:** support changes it server-side, password unchanged → `Support EmailUpdated FILLIN`.
- **Account deletion:** confirm completion, data purged within 30 days → `Support DeleteAccount Completed` (policy details in *Account Deletion*).
- **Delete + reinstall** (generic broken-app fix): delete fully (not App Library/Remove from Home Screen), reinstall free, sign back into the same account; downloads must be re-downloaded → `TechSupport AppleDeleteAndReinstall FILLIN` (address known) or `TechSupport AppleDeleteAndReinstallNoAccountAddress FILLIN` (address unknown).

## Voice & formatting conventions for this mailbox

- Challenge-related replies end with the **Mindful Minute Challenge FAQ** link as a footer.
- Reply names encode usage: `FILLIN` = contains placeholders (ACCOUNTADDRESS, EMAILADDRESS, CORRECTADDRESS, INSERTEMAIL, PASSWORD, #SESSIONS, METHOD, ADDRESS, MEDITATIONHISTORYIFANY) that MUST be replaced with real account values before sending; `SNIPPET` = composable fragment, not a standalone reply.
- Tone matches the rest of Happier support: warm, brief, step-numbered instructions, "Stay mindful out there" / "We're here to support you" sign-offs.

## Edge Cases & Exceptions

- **Apple Wellness replies inside our threads.** Tickets flow through the `apple@meditatehappier.com` Google Group, and the Wellness team (`wellness@apple.com`) answers directly in the same threads (rendered as customer-type posts from "Apple Wellness"). If Wellness already answered — rewards, eligibility, token re-sends — don't answer again on their behalf; the ticket may only need closing.
- **Past incident:** playback failures in parts of China, fall 2025 — resolved; remedy was Force Quit (`Bug PlaybackChinaFall2025`). Only relevant if someone references that outage.
- **Positive/closing messages:** use the `General Glad*` family; feedback gets forwarded and acknowledged (`Feedback PassedOn`).

# Action Classification

## No Action Required (reply only)

- Program routing, link corrections, sign-in help, delete/reinstall guidance, closing/thanks replies.

## Human Action Required

- Registration email changes, account deletions, benefit applies, password resets to default, token resets — see the per-program docs for specifics. Bert drafts; a human executes the admin step.

## Do Not Auto-Send Conditions

- Any draft with an unfilled `FILLIN` placeholder.
- Any draft asserting an account-specific fact (registered address, subscription state, session count) that wasn't verified from account/Wellness data.

## Escalation Triggers

- Prize questions/disputes → Apple Wellness team (`wellness@apple.com`) — we never adjudicate prizes.
- Family promo code questions beyond the standard instructions → `apple@happierapp.com`.
- Token registration disputes → verify with the Wellness team internally (see the join doc).

# Confidence Notes

- **High confidence:** the two-program split, the Global Access URL, account-identification flows, conventions — all verbatim from the Apple mailbox saved replies (`data/saved_replies_apple.json`, pulled 2026-07-22).
- **Judgment call:** ambiguous "can't access the app" tickets — determine program by account state before picking a flow.
- **Gaps:** exact challenge dates/join-window dates are not in the saved replies; current window status (closed as of 2026-07-22) comes from the team/standing brief and should be re-confirmed when the next event approaches.

# Saved Reply Mapping

Saved replies for this mailbox live in `data/saved_replies_apple.json` (mailbox 201086 — names quoted exactly, typos included).

| Situation | Saved reply |
|---|---|
| Need account info from inside the app | `Support SendASupportTicket` |
| Need diagnostic email during the event | `Support SendSupportEmailFromChallenge` |
| No account under their email / identify registration | `Support WhatEmailDidYouUseToRegister FILLIN` |
| Check for hidden SIWA address | `SNIPPET SIWACheckSettingsForMaskedAddress` |
| Sign-out/sign-in article pack | `SNIPPET SignOutAndSignIn` |
| Registration email changed | `Support EmailUpdated FILLIN` |
| Account deleted confirmation | `Support DeleteAccount Completed` |
| Broken app, address known / unknown | `TechSupport AppleDeleteAndReinstall FILLIN` / `TechSupport AppleDeleteAndReinstallNoAccountAddress FILLIN` |
| Force Quit article link | `Link AppleForceQuitSupportArticle` |
| China playback incident (fall 2025, resolved) | `Bug PlaybackChinaFall2025` |
| It works now / thanks | `General GladIt'sWorking`, `General GladToHearIt`, `General GladToHelp` |
| Feedback acknowledged | `Feedback PassedOn` |

# Related Policies

- *Apple Mailbox — Ticket Intake & Link Recognition* — link formats, intake forms, error taxonomy, tagging (from the last 200 real tickets)
- *Global Access (Apple Wellness Complimentary Subscription)* — the current period's main doc
- *Mindful Minute Challenge — Registration & Join (Apple Mailbox)*
- *Mindful Minute Challenge — Minutes, Tracking, Medals & Prizes (Apple Mailbox)*
- *Mindful Minute Challenge (Apple Challenge)* — main-mailbox routing rule (move, don't answer)
- *Account Deletion*, *Login Issues*, *No Account Found Troubleshooting* — general flows these tickets sometimes need
