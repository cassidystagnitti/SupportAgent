# Global Access (Apple Wellness Complimentary Subscription)

# Summary

**Scope: Apple mailbox (`3. Happier Apple Support`, id 201086).**

Global Access is the **year-round complimentary Happier Meditation subscription** Apple employees get as a wellness benefit from Apple Wellness. It is separate from the Mindful Minute Challenge (the annual event): the subscription is always claimable, requires no challenge participation, and unlocks the full app.

**We are in the Global Access period now (as of 2026-07-22): the challenge join window is closed.** The defining ticket of this period: a user tries to sign up with a **challenge link** — an event registration page, or the unique link/QR from a challenge confirmation email — and it fails or does nothing. They must instead claim through the **Global Access link**, which is different:

- **Global Access (correct, always works): `https://wellness.apple.com/content/804`**
- Challenge links (wrong right now): `people.apple.com/page/11893`, `signups.apple.com/event/...` pages, or a tokenized link/QR from a challenge email

Never troubleshoot a challenge link while the join window is closed — switch the user to the Global Access flow.

# Trigger Conditions

- **Ticket signals:** "free subscription from Apple," "Apple Wellness benefit," "claim my subscription," "everything is locked," "asked to pay / hit a paywall," "my link doesn't work," "trying to sign up for the challenge" (during closed period), "missed the challenge," Android user asking for access, "bought a subscription but it's supposed to be free," "when does my access expire/renew"
- **Account signals:** Apple-org benefit subscription on the account, or no subscription on an Apple employee's account
- **Keywords:** "Global Access," "Wellness Web," "wellness.apple.com," "complimentary," "benefit"

# Required Context

- [ ] Which link did they use — Global Access (`wellness.apple.com/content/804`) or a challenge link? (Ask for a full copy of the link/email if unclear.)
- [ ] Did they register on the Wellness Web page first? (Registration with Wellness must exist before the link works.)
- [ ] Device: iPhone/iPad (self-serve) or Android (manual apply by support)?
- [ ] The address Apple Wellness has on file vs. what the app is signed into (email or hidden Sign in with Apple address).
- [ ] Does the account already show the benefit? (If yes, this is a sign-in problem, not a claim problem.)

# Policy / Correct Response

## Standard Case — claiming Global Access (iOS)

1. Go to the Global Access page on Wellness Web: `https://wellness.apple.com/content/804` and register.
2. Make sure the link Apple Wellness sends is on the iPhone (forward the email to the phone if needed).
3. Tap the link, then tap **Open in Happier**.
4. Follow the prompts — the subscription unlocks in the app.

Saved reply: `Support GlobalAccessInstructions`. This claim flow is **iOS-only** — see the Android variation below.

## Standard Case — user tried a challenge link (the current #1 ticket)

Explain that the challenge join window has closed, and give them the Global Access claim steps above so they still get the free subscription. Saved replies:

- Asked to join / used an event link → `Support JoinClosed`
- Thought they had joined, but the token was never connected (join never completed) → `Join TryingToJoinLateNeverJoined` — confirms what we see on their account, states the window has closed, then gives the Global Access link
- Bare claim instructions → `Support GlobalAccessInstructions`

Do not promise late enrollment, prize eligibility, or exceptions — the window is owned by Apple Wellness, not us.

## Troubleshooting ladder (claim not working)

Work in order; each step maps to a saved reply:

1. **Confirm they started at the Wellness Web page** (`wellness.apple.com/content/804`) so a Wellness registration exists → `Support GlobalAccessTapLinkAgain`.
2. **Link on the iPhone → tap → Open in Happier.** The tap must happen on the same device that has the Happier app.
3. **Still stuck:** have them **cancel the registration on their Wellness page, then re-register** (tap Register again) to get a fresh link → same reply, `Support GlobalAccessTapLinkAgain`.
4. **Stuck on the free-trial start page:** there's an **X in the upper corner** — tap it to get straight to the subscription → `Support GlobalAccessTrialStartPage`. Never have a Global Access user start a paid trial or purchase to get in.
5. **Claimed but app still locked — it's a sign-in mismatch.** Make sure the app is signed into the account Apple Wellness has on file:
   - Registered by email → sign out (article 51) or Force Quit if half-signed-in, then Sign In → **Sign in with Email** → their address + password (reset via article 15 if needed) → `Support GlobalAccesLoginEmail` (sic — reply name is missing an "s")
   - Registered via Sign in with Apple → Sign In → **Sign in with Apple**, authenticate (choose Hide My Email if prompted) → `Support GlobalAccessLoginSIWA`; find the hidden address via `SNIPPET SIWACheckSettingsForMaskedAddress` / article 314
6. **Benefit already on the account:** tell them they're all set and give the sign-in article pack in case the app shows locked → `Support GlobalAccessAllSet FILLIN`.

## Variations

- **Android user:** the Wellness Web claim flow doesn't exist on Android. Have them download the Happier app from the Play Store and create a **free** account (tap the X when offered a trial), send us the address they registered, and **support applies the benefit server-side**. Ask → `Support AndroidNoAccount`; confirm after applying → `Support AndroidAccessApplied FILLIN`. The same manual-apply path is the fallback for anyone who can't complete the iOS flow.
- **User bought a subscription they should be getting free:** they must request the refund **through Apple**, not us — receipt "Report a Problem," `reportaproblem.apple.com`, or AppleCare billing (Apple phone list HT201232). After they cancel, the Wellness subscription remains on their account (as long as they're enrolled). → `Support RefundRequest`. Never promise a Happier-side refund for an Apple App Store purchase (*Refund Policy*: Apple purchases are refunded only by Apple).
- **"When does it expire / do I need to re-claim?"** — the benefit is extended **at the end of October** for another year, handled entirely on our side; the user does nothing on Wellness Web or in the app → `SNIPPET RenewalOnOct30`.
- **Family members:** Apple and Happier have a shared gift code — **`APPLEFAM-X83B4`**, redeemed at `https://app.tenpercent.com/redeem?promo_code=APPLEFAM-X83B4`, giving a **free 6-month subscription**. The reply includes both paths (create account → redeem, or sign in → redeem, then sign into the app the same way). Questions from family → `apple@happierapp.com`. → `Support AppleFamPromoCode`.

## Edge Cases & Exceptions

- **User half-signed-in / no Sign In screen:** sign out via article 51, or Force Quit and reopen, until the Get Started / "Already have an account? Sign In" screen shows. Always sign in via "Already have an account? Sign In" — never Get Started, which creates a duplicate account.
- **User created a second account while trying to claim:** align them onto the account Wellness has on file; if the benefit landed on the wrong account, a human can move the registration (see *Multi-Account & Merge*).
- **Non-Apple customer asking for Global Access:** it's an Apple-employee benefit; family goes through the family code. Don't extend it to anyone else.

# Action Classification

## No Action Required (reply only)

- Claim instructions, challenge-link → Global-Access-link redirects, cancel-and-re-register guidance, trial-page X instruction, sign-in help, renewal reassurance, Apple-refund redirect, family-code instructions.

## Human Action Required

- **Apply the benefit server-side** (Android, or iOS flow that can't be completed): needs the registered account address; confirm afterward with `Support AndroidAccessApplied FILLIN`.
- **Fix a wrong-account claim / registration email change**: admin-side account work.

## Do Not Auto-Send Conditions

- Any `FILLIN` reply whose placeholders (account address, etc.) aren't filled from verified account data.
- "All set / benefit applied" claims not verified against the account.
- Anything stating Wellness-side registration status (we can see our side; Wellness registration facts should be hedged or verified).

## Escalation Triggers

- Eligibility disputes (who qualifies, contractor/family edge cases) → Apple Wellness owns eligibility; don't improvise.
- The Global Access link itself appears broken for multiple users → flag to the team immediately (partnership-level issue).

# Confidence Notes

- **High confidence:** the Global Access URL, claim steps, cancel-and-re-register recovery, iOS-only limitation, Android manual apply, trial-page X, Apple-only refunds, October renewal, family code — all verbatim from saved replies (pulled 2026-07-22).
- **Judgment call:** whether a vague "can't sign up" ticket is a challenge-link case (closed-window redirect) or a genuine Global Access claim failure — ask for the link if not obvious.
- **Gaps:** precise eligibility rules and the shape of the Wellness-issued Global Access email aren't documented in saved replies; the `APPLEFAM-X83B4` code and the Oct-30 renewal date are period-specific facts that should be re-confirmed each cycle.

# Saved Reply Mapping

All names from `data/saved_replies_apple.json` (mailbox 201086), quoted exactly.

| User state | Use case | Saved reply |
|---|---|---|
| Any | How do I claim my free subscription? | `Support GlobalAccessInstructions` |
| Used a challenge link, window closed | Wants to sign up / join | `Support JoinClosed` |
| Token never connected, window closed | Thought they joined; didn't complete | `Join TryingToJoinLateNeverJoined` |
| Registered but link not working | Claim troubleshooting / re-register | `Support GlobalAccessTapLinkAgain` |
| Stuck on trial start page | Sees paywall/trial screen | `Support GlobalAccessTrialStartPage` |
| Claimed, app locked, email account | Sign into registered email account | `Support GlobalAccesLoginEmail` |
| Claimed, app locked, SIWA account | Sign in with Apple to reconnect | `Support GlobalAccessLoginSIWA` |
| Benefit already on account | Reassure + sign-in article pack | `Support GlobalAccessAllSet FILLIN` |
| Android, no account | Create free account, send address | `Support AndroidNoAccount` |
| Android (or manual apply), done | Confirm benefit applied | `Support AndroidAccessApplied FILLIN` |
| Bought a subscription | Refund via Apple; benefit remains | `Support RefundRequest` |
| Asks about expiry/renewal | October extension, no action needed | `SNIPPET RenewalOnOct30` |
| Family member access | 6-month family gift code | `Support AppleFamPromoCode` |
| Identity unclear | What address did you register? | `Support WhatEmailDidYouUseToRegister FILLIN` |

# Related Policies

- *Apple Mailbox Overview (Apple Wellness Programs)* — program split, key links, conventions
- *Mindful Minute Challenge — Registration & Join (Apple Mailbox)* — when the join window is open
- *Refund Policy* — Apple purchases are refunded only by Apple
- *Free Trial Policy* — why the trial-start-page X matters (payment method up front)
- *Multi-Account & Merge* — benefit landed on the wrong account
