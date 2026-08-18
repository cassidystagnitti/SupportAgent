# Multi-Account Management & Account Merge

# Summary

Covers tickets where a customer has two accounts and wants to consolidate them — typically because they accidentally signed up with a new email, signed in under the wrong account, or purchased a subscription on the wrong account. Support can transfer a Stripe subscription between accounts, copy meditation history from one account to another, change an account's email address, and perform a soft delete of an unsubscribed account when needed to free up an email. Apple and Google subscriptions cannot be transferred directly — the path for those is Restore Purchases or an email change on the subscribed account.

# Trigger Conditions

- **Ticket signals:** customer has two accounts, wants to merge or combine accounts, has meditation history on the wrong account, purchased a subscription on the wrong account, accidentally signed into a new account and did meditations there, wants to consolidate two emails into one, lost subscription access after switching accounts
- **Account signals:** two account records found on different emails; one may have an active Stripe/Apple/Google subscription while the other has meditation history (or vice versa); occasionally both accounts have active subscriptions
- **Keywords / phrases:** "merge my accounts," "two accounts," "wrong account," "accidentally signed in," "my history is on a different account," "move my subscription," "combine accounts," "subscribed to the wrong email," "I have two emails," "I started over by mistake," "my stats aren't there"

# Required Context

- [ ] Both email addresses — which account has the subscription and which has the history (or both)
- [ ] Which account the customer wants to use going forward
- [ ] Subscription provider on each account (Stripe, Apple, Google Play, or none)
- [ ] Whether the secondary account has meaningful meditation history worth copying (check admin)
- [ ] Whether both accounts have active subscriptions (case-by-case handling required)
- [ ] Login method on the desired final account (email/password, Sign in with Apple, Google)

# Policy / Correct Response

## Standard Case: Stripe subscription + meditation history merge

When a customer has a Stripe subscription on one account and meditation history on another, support handles the full merge end-to-end:

1. **Check for meditation history on the secondary account.** If there is no meaningful history (e.g., a brand new account with zero or minimal sessions), skip the copy step.
2. **Transfer the Stripe subscription** to the desired account using the MoveSubscription admin feature.
3. **Copy meditation history** to the desired account if it exists on the other. History is always copied — never deleted from the source.
4. **Leave the source account as-is** unless the customer explicitly asks to have it deleted.
5. **Reply confirming the end state:** tell the customer which email address has their subscription and history going forward, and how to sign into that account (login method). Do not describe the internal actions taken.

### Getting both email addresses

If only one email is known (the ticket contact email), ask the customer to check the app for the other before proceeding:
- Tap Profile icon → Settings (gear) → Account under MEMBERSHIP → note the email listed
- Then sign out and sign back into their main account

Use `Use MultipleAccountsWeSeeOneAddress FILLIN` for this investigation step.

## Stripe-only (no history to move)

When the subscription is on the wrong Stripe account but there is no meaningful meditation history to copy (e.g., customer just signed up), transfer the Stripe subscription to the desired account only. No history step needed.

## History-only (no Stripe subscription)

When meditation history exists on a secondary account but there is no Stripe subscription involved, copy the history to the desired account. No subscription transfer needed.

## Apple or Google subscription: Restore Purchases path

We cannot transfer Apple or Google subscriptions between accounts directly. The primary path is:

1. Customer signs out of the current (new/wrong) account in the app.
2. Customer signs back into the desired (original/main) account.
3. Customer uses Restore Purchases in the app to re-link the Apple or Google subscription to the correct account.

If Restore Purchases resolves it, no further action needed. If it does not, see the email change path below.

## Apple or Google subscription: email change path

When Restore Purchases is not viable, or the customer cannot access the correct account, use an email change to bring everything together:

1. **If an unsubscribed account is blocking the email address the customer wants:** soft delete the unsubscribed account to free up that email, then change the email on the subscribed account to that address.
2. **If no blocking account exists:** change the email on the subscribed account to the email the customer wants to use.
3. **Sign in with Apple accounts** require an additional step after email change — the customer must set a new password via the password reset link since SIWA accounts do not have a password on file.

> **Soft deletion scope:** A soft delete outside of the standard account deletion policy is only performed in two cases: (1) the customer explicitly requests it, or (2) an unsubscribed account needs to be removed to free up an email address for a merge. Never soft delete a subscribed account.

## Two active subscriptions

Handle case by case:
- Confirm which subscription the customer wants to keep.
- If the other is within the standard refund window (30 days annual / 24 hours monthly), apply a refund per *Refund Policy*.
- If past the refund window, provide refund instructions or cancel at next renewal.
- Once resolved, proceed with the standard merge flow above.

## Variations

- **Customer doesn't know both email addresses:** Use `Use MultipleAccountsWeSeeOneAddress FILLIN` to guide them to check the app, sign out, sign back into the main account, and report back.
- **Customer is on Sign in with Apple:** May not recognize the relay address. After email change, the customer must set a password using the password reset link. Use `AccountManagement EmailUpdatedFromSIWA`.
- **Customer deleted one of their accounts:** Meditation history from the deleted account is permanently gone — it cannot be recovered. If the subscription is recoverable (Stripe), locate it by receipt or last-4 card digits and place it on the remaining account. Use `Use DeletedAccountLostSubscriptionAccess`.
- **Customer only wants an email change (no merge):** Just update the email on the account. Use `AccountManagement EmailUpdated FILLIN` or `AccountManagement EmailUpdatedFromSIWA` as appropriate.

## Edge Cases & Exceptions

- **Customer cannot access either account:** Locate the subscription-bearing account by receipt or last-4 card digits before proceeding. See *No Account Found / Account Troubleshooting* for the investigation flow.
- **Accounts appear to belong to different people** (different names, shared payment method, family member scenarios): Do not merge without explicit confirmation. Escalate if identity is ambiguous.
- **Customer asks to delete the old account after the merge:** Process per the standard account deletion policy. Confirm no active subscription remains before deleting.
- **App still shows free after subscription transfer:** Customer needs to sign out and sign back in. Include sign-out/sign-in steps in the reply.
- **Customer has meditation history on both accounts worth keeping:** Copy history from the secondary account to the primary. Both sets of history will exist on the primary going forward.

# Action Classification

## No Action Required (reply only)

- Asking the customer to check the app for their second email address — customer action needed before support can proceed
- Sending Apple or Google Restore Purchases instructions — the customer performs this themselves
- Confirming the completed merge once all actions are done — reply only

## Human Action Required

- **Action:** Transfer Stripe subscription from one account to another (MoveSubscription admin feature)
- **When:** Customer wants their subscription on a different account
- **Why AI can't do it:** Admin access required for subscription transfers

- **Action:** Copy meditation history from one account to another
- **When:** Meaningful history exists on the secondary account
- **Why AI can't do it:** Admin access required for data operations

- **Action:** Change email address on an account
- **When:** Customer wants to use a different email, or an email change is needed to free up an address for the merge
- **Why AI can't do it:** Admin account update required

- **Action:** Soft delete an unsubscribed account
- **When:** Customer requests it, OR an unsubscribed account is blocking the email address needed for the merge
- **Why AI can't do it:** Admin deletion action

- **Action:** Refund one of two active Stripe subscriptions
- **When:** Customer has active subscriptions on both accounts; one needs to be canceled/refunded
- **Why AI can't do it:** Requires Stripe admin access and timing/eligibility judgment — see *Refund Policy*

## Do Not Auto-Send Conditions

- Customer has two active subscriptions — which to keep and whether a refund applies requires human judgment
- Accounts may belong to different people — identity ambiguity requires human review before any action
- Customer deleted one account — do not auto-send recovery instructions without human confirming the subscription recovery path
- Sign in with Apple email change path — multi-step flow with friction; human should verify the reply is correct before sending

## Escalation Triggers

- **Two or more subscribed accounts found across any email in the ticket** → escalate immediately to support leadership. Do not send any reply.
- **Account identity mismatch** (accounts appear to belong to different people, e.g., conflicting names or shared payment method) → senior support before any action
- **Customer cannot access either account and cannot provide a receipt or last-4 card digits** → senior support for deeper investigation

# Confidence Notes

- **High confidence areas:** Stripe subscription transfer and history copy are standard admin operations with clear tooling. Apple/Google Restore Purchases is always the first path for those providers. Soft delete is only for unsubscribed accounts in the two defined cases. Reply communicates end state only — not actions taken. Source account is never deleted unless explicitly requested or needed to free the email.
- **Judgment call areas:** Whether meditation history on a secondary account is "meaningful" enough to copy (a brand new account with one or two sessions may not be worth the step — use judgment). Two active subscriptions: when the right call is a refund vs. just canceling the unwanted subscription depends on timing and customer preference.
- **Gaps:** No single saved reply currently covers the full Apple/Google email-change-plus-migration flow in one template. Custom replies are often needed for those cases.

# Saved Reply Mapping

## Both emails known — full merge (Stripe + history)

| Condition | Saved Reply | Notes |
|---|---|---|
| Stripe sub + meditation history both transferred to new account | `Use MovedSubAndStatsToNewAccount FILLIN` | Fill in OLDACCOUNTADDRESS and NEWACCOUNT; may offer to delete old account |
| Stripe sub moved only (no meaningful history to copy) | `Use MoveSubscription` | Fill in both email addresses; may offer to delete old account |
| Meditation history copied only (no Stripe sub to move) | `Use CopiedMedHistory` | Fill in EMAILADDRESS; asks customer to confirm everything looks right |

## One email known — investigation step (get the second email)

| Condition | Saved Reply | Notes |
|---|---|---|
| We see one email address; need customer to report the other | `Use MultipleAccountsWeSeeOneAddress FILLIN` | Fill in ACCOUNTADDRESS (the main account); guides customer to check app, sign out, sign back in |

## Apple / Google — Restore Purchases

| Condition | Saved Reply | Notes |
|---|---|---|
| Apple subscription not linked to current account | `Use AppleRestorePurchases` | Customer performs Restore Purchases themselves |
| Google subscription not linked to current account | `Use GoogleRestorePurchases` | Customer performs Restore Purchases themselves |

## Email change

| Condition | Saved Reply | Notes |
|---|---|---|
| Email updated on a standard account | `AccountManagement EmailUpdated FILLIN` | Fill in NEWEMAIL; includes sign-out/sign-in instructions |
| Email updated on a Sign in with Apple account | `AccountManagement EmailUpdatedFromSIWA` | Fill in NEWEMAIL; customer must set a new password via reset link |

## Post-deletion recovery

| Condition | Saved Reply | Notes |
|---|---|---|
| Customer deleted one account; subscription and/or history may be lost | `Use DeletedAccountLostSubscriptionAccess` | Attach PDF; help locate subscription by receipt or last-4 card digits |

# Help Scout Contact Linking (internal, automatic) — added 2026-08-18

Separate from everything above, the pipeline keeps the **Help Scout contact record** tidy on its own (`helpscout_identity.py`). When a customer writes in from one address and their ticket shows another that is verifiably theirs, that address is added to the same Help Scout contact; if a *second* Help Scout contact record already owns it, the two records are consolidated into the one this ticket is on — its conversations move over and its addresses come with them.

**This is CRM housekeeping and nothing more.** It makes one person's history readable in one place. It does **not**:

- merge their Happier accounts,
- move a subscription between accounts,
- copy meditation history,
- change any email address on a Happier account.

Every one of those is still the admin work described above, and still human action.

> **Never tell a customer their accounts were merged because of this.** A reply that says "I've merged your accounts" when only the Help Scout contact was linked is a false claim of completed work — the customer will sign in and find their history still split. Describe only what was actually done to their Happier account.

## What gets linked automatically, and what waits for a human

An address is added on its own **only** with ownership evidence: the customer claims it in their own words ("my other email is …", "I signed up with …"), or a Happier account under that address carries the same first name as the contact. Anything else is written into the internal note as a suggestion and left alone.

Addresses are never linked automatically when:

- someone else is described as the owner — "my wife's email", "send the gift to …", a recipient. **This is the case that matters most**: a gift buyer's ticket names the recipient, and fusing the two contacts would put a stranger's history on the buyer's record.
- the address is a role mailbox (`support@`, `no-reply@`), one of our own domains, or a vendor's (Apple, Stripe, Google receipts).
- the two contact records carry different first names — a shared payment method usually means a household, not one person.
- the duplicate contact has more conversations than the merge cap (default 25) — Help Scout's own UI merge is one click and safer at that size.

Each of those lands in the ticket's internal note with the reason. When the note asks about an address you can confirm from the thread, act on it: the sidebar's `link_email` (or `python3 scripts/helpscout_link_emails.py --conversation <id> --email <address> --apply`) links it and merges the duplicate, treating your instruction as the evidence.

`HELPSCOUT_IDENTITY_WRITES=false` turns the automatic writes off on a deployment; the suggestions still appear in the note.

## How this changes the tickets above

A merge ticket now often arrives with the customer's other address **already on the contact**, and their earlier conversations already visible. Read that history before drafting — it frequently contains the second email address, the platform, or an earlier answer to the same question. It does not, however, tell you anything about the state of their Happier accounts: check those with the account lookup as always.

# Related Policies

- *Account Deletion*
- *Subscription & Billing Overview*
- *Refund Policy*
- *Apple/Google → Stripe Migration*
- *No Account Found / Account Troubleshooting*
- *Login Issues*
