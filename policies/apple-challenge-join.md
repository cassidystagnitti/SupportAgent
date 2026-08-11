# Mindful Minute Challenge — Registration & Join (Apple Mailbox)

# Summary

**Scope: Apple mailbox (`3. Happier Apple Support`, id 201086).**

How Apple employees register for and join the annual Mindful Minute Challenge, and the full troubleshooting taxonomy for when a join fails. The join is a **token handshake**: register on Wellness Web → Wellness emails a confirmation with a **unique link and/or QR code (the token)** → on the same iPhone that has the Happier app, tap the link (or scan the QR) → tap **Open in Happier** → follow the prompts → the event screen pops up in the app. A join is only complete when the token is *connected* to a Happier account.

**Status check first (as of 2026-08-11 the join window is CLOSED).** While closed, do not troubleshoot joins — use `Support JoinClosed` / `Join TryingToJoinLateNeverJoined` and pivot to Global Access (see *Global Access (Apple Wellness Complimentary Subscription)*). Everything below applies while a join window is open; it stays documented so Bert is ready when the next event starts.

**Known cadence (from real 2025-cycle tickets):** registration confirmations went out from ~2025-09-16; the event month was **October 2025** (31 days, 25 needed to complete). Expect the mmc 2026 registration window around September 2026 — confirm exact dates with the team. The challenge token link is recognizable by its `challenge=apple-challenge-<year>` parameter (`my.meditatehappier.com/challenges?org=apple&challenge=apple-challenge-2025&token=…&event=3167`); see *Apple Mailbox — Ticket Intake & Link Recognition*.

# Trigger Conditions

- **Ticket signals:** "can't join," "Failed to Join Challenge," a join error message (see taxonomy), "my link/QR doesn't work," "signed up but don't see the challenge," "used my coworker's link," password trouble while joining, "quit the challenge and want back in," friends/Circle invites
- **Keywords:** "join," "register," "token," "QR code," "Open in Happier," "Challenge Not Found," "Something Went Wrong"

# Required Context

- [ ] Is the join window open right now? (If closed → Global Access redirect, full stop.)
- [ ] Happier app installed on the iPhone/iPad, and up to date? (Challenge is iOS-only — Android can't join; offer Global Access on Android instead.)
- [ ] The address the token/registration is tied to (what Wellness has on file) vs. the account the app is signed into (email vs. hidden SIWA — article 92 / article 314).
- [ ] The exact error text, and where in the flow it appears.
- [ ] For token questions: their Apple email address, and ideally a full copy of their join link (`Support JoinMoreInfo`).

# Policy / Correct Response

## Standard Case — the canonical join steps

1. Download the free Happier Meditation app (App Store `http://apple.co/1V7sqo9`).
2. Create a **free** account if new (tap the **X** at the top when offered the free trial), or sign into the existing account (articles 92/51/52/15).
3. Register at the Mindful Minute Challenge Sign Up on Wellness Web (period-specific link; 2025 cycle used `people.apple.com/page/11893`).
4. From the confirmation email, scan the QR with the same phone the app is on, or tap the unique link on the iPhone.
5. Tap the yellow **Open in Happier** button and follow the prompts.

Success = the event screen pops up in the app. Saved replies: `Support JoinSignUpSteps` (reply) and `Join JoinSteps SNIPPET` (composable block). If they get a **Failed to Join Challenge** error, have them tap **Contact a Human** in app settings and send the resulting email so we get device data.

## Join-error taxonomy

| Error / symptom | Fix | Saved reply |
|---|---|---|
| Connection/network error during registration | Retry on wifi or reliable signal | `Support JoinErrorBadInternet` |
| "Challenge Not Found" | Re-run the steps: app installed → Wellness email on the iPhone → tap link/scan QR → Open in Happier | `Support JoinErrorChallengeNotFound` |
| JSON error | Tap the link again and redo signup; if it persists, delete + reinstall the app, retry | `Support JoinErrorJSONIssue` |
| Error because they have no Happier account | Tap the Wellness link again and choose **Get Started** (create account) instead of Sign In | `Support JoinErrorNeedToCreateAccount` |
| Account exists but never joined (token unconnected) | Sign into the registered account, then tap the link / scan the QR again | `Support JoinErrorTapLinkAgain FILLIN` |
| "Something Went Wrong / Try Again" | Force Quit → rescan and retry; then delete fully + reinstall → rescan; then send us their Apple email so we can verify the token with Wellness | `Support JoinErrorTryAgainSomethingWentWrong` |
| Old app version can't join | Update the app, sign in, then tap/scan the link again | `Support JoinUpdateHappierApp FILLIN` |

## Sign-in prerequisites (most "join errors" are really sign-in mismatches)

The app must be signed into the account **Apple Wellness has on record** before the token tap:

- **Email registration** → sign out (article 51) or Force Quit if half-signed-in → Sign In → **Sign in with Email** → registered address + password → then tap the Wellness link → `Support JoinLogIntoRegisteredEmailAccount FILLIN`
- **Hidden Sign in with Apple registration** → Sign In → **Sign in with Apple** (choose Hide My Email if prompted) → then tap the link → `Join SignIntoHiddenSIWAThenJoin`; if the user needs to see the masked address: Settings → name → Sign-In & Security → Sign in with Apple → Happier → `Support JoinLogIntoRegisteredSIWAAccount` / `SNIPPET SIWACheckSettingsForMaskedAddress`

## Token states (unique per employee)

- **Token taken** — the link is already connected to a different address: have them sign into *that* address (article pack); if that's not theirs, get their Apple email so we can check the registration with the Wellness team and reset it → `Support JoinTokenTaken FILLIN`
- **Token swap** — they joined using **another employee's** token: they must re-register on Wellness Web for their own link, sign into their own account, and tap/scan their own link → `Support JoinTokenSwap FILLIN`
- **Token reset done** — after we reset a token with Wellness: tell them it's reset and to rejoin with their address → `Support JoinTokenDeletedResetGoAheadAndRejoin`
- **Token never connected** — "joined" never completed; during an open window, walk the join steps; after close → `Join TryingToJoinLateNeverJoined`
- **Rejoining after quitting the challenge** — reopen the original Wellness confirmation email and tap the unique link / scan the QR again → `Support JoinAfterQuitting`

## Password problems while joining

- **Standard reset:** `https://my.meditatehappier.com/passwords/new` → sign in via "Already have an account? Sign In" (never Get Started — that creates a second account) → rescan the link → `Support PasswordReset FILLIN`
- **Reset email never arrives (suppression bug):** support fixes the account's email status (historically a Braze suppression), then the user retries the same reset link → `Support PasswordResetBrazeIssueFixed`
- **Apple corp address can't receive the reset:** offer three options — use credentials saved in their Password app; give us a personal address to move the registration to (challenge tracking is unaffected) and we send the reset there; or, **with their permission**, reset the password to the default and email credentials → `Join AppleEmailPasswordReset`
- **Fulfilling the default reset:** send credentials + "sign in, then tap your Wellness link" → `Join PasswordResetToDefaultThenJoin` — **never auto-send** (contains live credentials) and only after explicit permission.

## Friends & Circle

- **Invite flow (while joining is open):** open the Challenge screen → My Circle → **Invite a Coworker** → send via Messages/SMS/AirDrop (work best). Invitee signs up, accepts, lands in the Circle → `Support FriendsInstructions`
- **Invite link won't open:** copy the invite link → paste into the Notes app → tap it there → Open in Happier → `Support FriendsTroubleshooting`
- **After joining closes:** coworkers can no longer be added — acknowledge, log as feature feedback → `Support FriendsCan'tAddAfterJoin`
- **"Why no friends in the regular app?"** — feature request, votes tracked → `Feedback FeatureRequestFriends`

## Status confirmations & follow-ups

- **Enrollment verified:** confirm they're in, with the sign-out/in pack in case the Challenge card isn't showing → `Support JoinAllSet FILLIN`; short version → `Support JoinGladToHearItAllSet`
- **Proactive check-in on a stalled join thread:** `Support JoinCheckingBack LostGirlsAndBoysRecovery`
- **Need more info to find them:** ask for a full copy of the join link, their Apple email, and the in-app account (Profile → Settings → Account: Login Method + Email) → `Support JoinMoreInfo`; unknown registration → `Support WhatEmailDidYouUseToRegister FILLIN`
- **Reassurance while un-joined:** minutes meditated in the app before the join completes are credited to the Challenge calendar once they're in; daily-ish pace, 25 of 31 days completes it → `SNIPPET KeepMeditating`

## Edge Cases & Exceptions

- **Pre-registration for the next cycle:** no known mechanism — registration windows are owned by Apple Wellness. Don't promise or improvise (open example: ticket #318146, an employee traveling through the expected September window). Check with Wellness.
- **Android:** the Challenge is iPhone/iPad-only. If they have an iOS device, they can join there; either way they get the free subscription (Android manual apply) → `Support AndroidNoAccount` (see *Global Access*).
- **Bought a subscription while trying to join:** enrollment gives them the free subscription; the purchase is refunded via Apple only → `Support RefundRequest` (see *Global Access*).
- **Mixed challenge + unrelated support issue:** handle the support issue under its own policy; keep join troubleshooting in the same thread.

# Action Classification

## No Action Required (reply only)

- Join steps, every row of the error taxonomy's user-side fixes, sign-in guidance, friends instructions/workaround, status confirmations, more-info requests.

## Human Action Required

- **Token verify/reset with the Wellness team** (token taken/corrupted; user supplies Apple email).
- **Password reset to default** (only with explicit user permission) and **registration email changes**.
- **Email-suppression fix** so reset emails deliver.

## Do Not Auto-Send Conditions

- `Join PasswordResetToDefaultThenJoin` (live credentials) — always human-reviewed, permission confirmed first.
- Any unfilled `FILLIN` placeholder; any claim about token/Wellness registration state not actually verified.
- Late-join or eligibility exceptions — never promise them.

## Escalation Triggers

- Token registration disputes or suspected token misuse → Wellness team verification.
- The same join error from multiple users in one day → flag to the team (likely a systemic/app issue) and collect Contact-a-Human diagnostics.

# Confidence Notes

- **High confidence:** the join handshake, the error→reply taxonomy, token states, password flows — all verbatim from the Apple mailbox saved replies (pulled 2026-07-22).
- **Judgment call:** picking between sign-in-mismatch vs. token-state explanations when the error text is vague — ask via `Support JoinMoreInfo` rather than guessing.
- **Gaps:** each cycle's exact join-window dates and registration URL are period-specific; confirm from the team each event. 2025-cycle facts from real tickets: registration confirmations ~2025-09-16, event month October 2025, registration pages `people.apple.com/page/11893` / `signups.apple.com/event/1712-fda4`. Whether pre-registration will exist for 2026 is unknown (Wellness owns it).

# Saved Reply Mapping

All names from `data/saved_replies_apple.json` (mailbox 201086), quoted exactly — see tables above for the full state → reply map. Quick index: join steps (`Support JoinSignUpSteps`, `Join JoinSteps SNIPPET`, `Support JoinDownloadAppAndSignIn FILLIN`), errors (`Support JoinErrorBadInternet`, `Support JoinErrorChallengeNotFound`, `Support JoinErrorJSONIssue`, `Support JoinErrorNeedToCreateAccount`, `Support JoinErrorTapLinkAgain FILLIN`, `Support JoinErrorTryAgainSomethingWentWrong`, `Support JoinUpdateHappierApp FILLIN`), sign-in (`Support JoinLogIntoRegisteredEmailAccount FILLIN`, `Join SignIntoHiddenSIWAThenJoin`, `Support JoinLogIntoRegisteredSIWAAccount`), tokens (`Support JoinTokenTaken FILLIN`, `Support JoinTokenSwap FILLIN`, `Support JoinTokenDeletedResetGoAheadAndRejoin`, `Join TryingToJoinLateNeverJoined`, `Support JoinAfterQuitting`), passwords (`Support PasswordReset FILLIN`, `Support PasswordResetBrazeIssueFixed`, `Join AppleEmailPasswordReset`, `Join PasswordResetToDefaultThenJoin`), friends (`Support FriendsInstructions`, `Support FriendsTroubleshooting`, `Support FriendsCan'tAddAfterJoin`, `Feedback FeatureRequestFriends`), status (`Support JoinAllSet FILLIN`, `Support JoinGladToHearItAllSet`, `Support JoinCheckingBack LostGirlsAndBoysRecovery`, `Support JoinMoreInfo`, `SNIPPET KeepMeditating`), closed window (`Support JoinClosed`).

# Related Policies

- *Apple Mailbox — Ticket Intake & Link Recognition* — telling challenge tokens from Global Access links, intake forms, error texts
- *Global Access (Apple Wellness Complimentary Subscription)* — the closed-window redirect, Android access, refunds
- *Mindful Minute Challenge — Minutes, Tracking, Medals & Prizes (Apple Mailbox)* — after the join succeeds
- *Apple Mailbox Overview (Apple Wellness Programs)* — links, conventions, account identification
- *Login Issues* / *No Account Found Troubleshooting* — deeper general sign-in flows
