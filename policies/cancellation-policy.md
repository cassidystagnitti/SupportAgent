# Cancellation policy
# Summary

Handles requests to cancel a subscription (turn off auto-renewal). The customer keeps full access through their period end date. Support can cancel directly on Stripe and Google Play; Apple customers are redirected to self-service. A key edge case: many customers write in when auto-renew is already off — in that case, simply confirm they're set and include the expiration date. For Stripe customers renewing at full price, offer a 40% retention discount before canceling.

**As of 2026-07-22, Bert can EXECUTE Stripe cancel-at-period-end directly** via the guarded write skill (`scripts/stripe_cancel_subscription.py`). A straightforward Stripe cancellation is therefore no longer a human-action ticket: Bert executes the cancellation, and the confirmation reply becomes **auto-sendable** (see "Bert execution" below). Google Play cancellations remain a human action; Apple remains self-serve redirect.

# Trigger Conditions

- **Ticket signals:** customer wants to cancel, doesn't want to renew, wants to turn off auto-renewal, asks how to cancel, wants to stop being charged
- **Account signals:** active subscription with auto-renew on (or customer believes it's on); subscription approaching renewal
- **Keywords / phrases:** "cancel," "cancel my subscription," "don't want to renew," "turn off auto-renew," "stop charging me," "end my subscription," "how do I cancel," "want to cancel"

# Required Context

- [ ]  Provider (Stripe, Apple, Google Play)
- [ ]  Auto-renew status — is it already off?
- [ ]  Subscription expiration / next renewal date
- [ ]  Whether the subscription has an active discount (Stripe only — relevant for retention offer eligibility)
- [ ]  Plan type (annual or monthly)
- [ ]  If no subscription is found and the customer mentions "Ten Percent Happier," Dan Harris, or the podcast: which product are they actually subscribed to? Run the `bert-disambiguate-10-percent` skill (see *Happier vs. 10% Happier*) before sending the redirect or the free-account reply.

# Policy / Correct Response

## Standard Case

**Cancellations are always at period end.** We do not terminate subscriptions immediately. The customer keeps full access until their expiration date. Always communicate the expiration date in natural language (e.g., "your access will continue through May 31").

### Auto-renew already off

If account data shows auto-renew is already disabled: reply-only confirming they're all set. Include expiration date. No admin action needed.

**Critical language rule:** When auto-renew is off, the expiration date is the date access ends — not a renewal date. Never say "set to renew on [date]" or "will renew on [date]." Always say "access continues through [date]" or "expires on [date]."

### By provider

**Stripe**
- Support turns off auto-renew directly in the admin. Self-service cancellation in the app is also available — offer this as an alternative if helpful.
- If the customer is set to renew at **full price** (no active discount): process the cancellation as requested, and include a 40% retention discount offer in the same reply in case they'd like to stay instead. Do not gate the cancellation on their response to the offer — always do what the customer asked.
- If the customer has an **active discount**: cancel without a retention offer.
- Always confirm the cancellation and include the expiration date in the reply.

**Apple**
- We cannot cancel Apple subscriptions on the customer's behalf. Redirect with Apple-specific instructions for managing subscriptions.
- Include expiration date if available from account data.

**Google Play**
- Support can cancel directly through the Google Play admin, OR redirect the customer to Google Play's self-service instructions — both are acceptable.
- Always confirm cancellation and include expiration date.

## Variations

- **Auto-renew already off:** Confirm they're set + expiration date. No action needed. True for all platforms.
- **Stripe, full price:** Process the cancellation and include the 40% retention offer in the same reply, in case they'd like to stay instead.
- **Stripe, discounted:** Cancel directly, no retention offer.
- **Apple:** Redirect only. No direct action available to support.
- **Google Play:** Cancel directly or redirect to self-service.

## Edge Cases & Exceptions

- **Customer says they already canceled but is still being charged:** Investigate whether auto-renew was actually turned off before the last billing cycle. If it wasn't, this may be a refund scenario — see *Refund Policy*. If auto-renew was off and they were still charged, escalate.
- **Customer wants to cancel immediately and lose access now:** We don't offer immediate termination. Explain that cancellation takes effect at period end and they retain access until then.
- **Customer wants to cancel and also get a refund:** This is a combined scenario — see *Refund Policy*. If within the refund window, a refund also cancels the subscription. If outside the window, cancel at period end per this policy.
- **Customer on Apple is frustrated that we can't help directly:** Acknowledge the limitation and provide clear instructions. If Apple gives them trouble, offer to escalate.
- **Customer mentions a cancellation error but auto-renew is already off:** Confirm it worked and they're all set. Do not investigate or address the error. Use the appropriate "already off" reply for their platform. Do NOT say the subscription is "set to renew" — it is set to expire. Use "access continues through [date]."
- **Cancellation request is vague — customer might want a refund:** If the customer's charge is recent enough to qualify for a refund, surface the option. Don't just cancel without checking refund eligibility when intent is unclear (see `CancelRefund StripeCancelOrRefund`).
- **Teams / org seat-reduction** (cut seats / keep only the billing owner's membership / quantity change on a Teams Annual org plan): Rare. ALWAYS escalate to a human — see *Escalation Policy*. Do not run `stripe_cancel_subscription.py` or any individual cancel; that would cancel the whole org plan. Do not change Stripe quantity yourself. Leave no customer draft. Move on.

# Bert Execution: Cancel at Period End (Stripe) — added 2026-07-22

Bert executes Stripe cancel-at-period-end itself with the first Stripe write skill. **Use it starting immediately** for any eligible Stripe cancellation ticket during the morning review or sidebar session.

## How to run it

`--apply` re-runs the same eligibility checks as a dry-run, so a second Stripe read is wasted when we already have a clean picture of the subscription.

1. **Skip the dry-run** when hydrate (Help Scout sidebar / Maven / `hydrate_ticket`) already shows **exactly one** Stripe subscription that is active or trialing and set to renew, and we have the `cus_` id. Go straight to apply.
2. **Dry-run first** only when hydrate is missing, ambiguous, shows multiple subs, dunning, a schedule we have not inspected, or we do not have a `cus_` yet: `python3 scripts/stripe_cancel_subscription.py <cus_…> --json` — prints the classification of every subscription and the exact plan (subscription id, access-continues-through date, schedule release, trial/discount notes).
3. **Apply**: `python3 scripts/stripe_cancel_subscription.py <cus_…> --apply --conversation-id <HS id> --json`. Every apply requires the env gates (`STRIPE_WRITE_API_KEY` + `ACTION_EXECUTION_ENABLED=true`) and appends an audit line to `data/stripe_action_log.jsonl`.
4. Outcomes: `applied` (auto-renew turned off), `already_off` (idempotent no-op — customer was already set; use the "already off" confirm reply), or `refused` (see below).

## Eligibility (enforced in code — the script refuses rather than guessing)

- **Stripe only.** Google Play cancels remain a human action (note); Apple remains self-serve redirect.
- **Teams / org (volume/tiered) plans are not this skill.** Seat-reduction is a mandatory human escalation, not cancel-at-period-end. Never apply this script to an org plan.
- Subscription must be **active or trialing** and **set to renew**. Trialing covers real free trials and retention pauses — both cancel cleanly at the trial/extension end.
- **Dunning (past_due/unpaid) → refused**: policy is IMMEDIATE cancellation for subs stuck in billing retry, which is a different path — handle in the Stripe dashboard (human action note).
- **Multiple renewing subscriptions → refused**: escalation signal per this policy — do not guess.
- **Paused collection → refused**: resolve in the dashboard first.
- Subscriptions under a Billing-Portal schedule are handled automatically (schedule released first; the dry-run plan calls it out).

## Auto-sendability after execution

**Once the cancellation is EXECUTED (`applied`) or confirmed already off (`already_off`), there is no remaining human action** — the ticket moves to the auto-send bucket:

- Treat the result as `needs_action = false`, `auto_sendable = true`; no "Actions needed" internal note is posted. Instead, an **"Action executed"** informational note goes on the ticket (subscription id, access-continues-through date, actor — `bert/actions.py` posts it automatically on the sidebar/MCP rails; post the equivalent manually on CLI executions), and the audit log records the write.
- The draft's past tense ("I've turned off auto-renewal…") must be TRUE at post time — **execute before posting/verifying**, so the verifier's deterministic Stripe truth check sees `cancel_at_period_end = true` on the live subscription.
- The standard reply rules still apply: confirmation + expiration date in natural language, and the 40% retention offer when the customer was renewing at full price.
- The normal do-not-auto-send conditions below still override (refund component, claims of being charged after cancelling, escalating frustration, app-quality complaint combos) — execution removes the ACTION barrier, not the judgment barriers.
- If the script **refused**, the ticket stays a human-action (note) or escalation ticket per the refusal reason. Never auto-send a reply claiming a cancellation that wasn't executed.

## After sending

Leave the conversation **closed**. Help Scout auto-reopens it if the customer replies (for example to take the 40% stay-on offer). If they don't reply, they were all set and the ticket should stay closed. Do not reopen a sent cancel confirmation to wait on the offer.

Help Scout has no Mailbox API for deleting a thread. If sending leaves a leftover draft (for example a Cass-signed duplicate from a first pass), delete it in the Help Scout UI. If the UI is not available, overwrite that leftover draft in place with a do-not-send stub via PATCH `{"op": "replace", "path": "/text", "value": "..."}` so it cannot be published later.


# Action Classification

## No Action Required (reply only)

- **Auto-renew already off (any platform):** Confirm they're all set, share expiration date. No admin action.
- **Apple cancellation requests:** Redirect to Apple instructions. No action available to support.

## Bert-Executable Action (auto-send after execution)

- **Action:** Turn off auto-renew in Stripe (cancel at period end).
- **When:** Active Stripe subscription, auto-renew on, customer wants to cancel, script checks pass.
- **How:** `scripts/stripe_cancel_subscription.py` per "Bert Execution" above. After `applied`/`already_off`, the ticket is reply-only and auto-sendable (subject to Do Not Auto-Send Conditions).

## Human Action Required

- **Action:** Turn off auto-renew in Google Play.
- **When:** Active Google Play subscription, auto-renew is on, customer confirms cancellation.
- **Why AI can't do it:** Requires Google Play admin access.
- **Action:** Immediate cancellation of a dunning/past-due Stripe subscription (and any case the write script refuses).
- **When:** Subscription in billing retry (past_due/unpaid), paused collection, or other refusal reasons.
- **Why AI can't do it:** The write skill deliberately only implements period-end cancellation; these paths run through the Stripe dashboard.

## Do Not Auto-Send Conditions

**Google Play subscriptions hold for Cassidy (decision 2026-09-02):** Google Play cancels, billing, plan changes are a top-level hold-back. See CLAUDE.md Solo vs Ping guidance. Draft the reply but hold for Cassidy review before sending.

Even when the reply is "reply-only" (no admin action needed) or Stripe cancellation is executed, flag for human review before sending if any of the following are true:

- Customer's cancellation request is combined with frustration about a charge — possible refund component requiring human judgment
- Customer claims to have already canceled but is still seeing charges — may be a billing or system error that needs investigation before any reply
- Customer is on Apple and expressing escalating frustration about not being able to get direct help — warrants human-reviewed framing
- Cancellation is combined with a complaint about app quality or experience — potential goodwill scenario beyond standard policy

## Escalation Triggers

- **Two or more subscribed accounts found across any email in the ticket** → escalate immediately to support leadership. Do not send any reply.
- **Teams / org seat-reduction** → escalate immediately. No customer draft. Do not cancel the org subscription or change Stripe quantity. See *Escalation Policy*.
- **Subscription is in a billing retry period (Stripe unpaid/past_due, dunning in progress)** → do NOT escalate. Cancel the subscription immediately (not at period end) — a sub stuck in retry/unpaid status has already failed to renew, so there is no remaining paid period to preserve access through. Confirm to the customer that the cancellation is effective immediately and that no further charges will be attempted.
- **Customer claims to have canceled but was still charged** → investigate before replying; may be a billing or system error.
- **Customer insists on immediate access termination and is escalating** → senior support.

# Confidence Notes

- **High confidence areas:** Period-end-only cancellation. Auto-renew already off → confirm + expiration date. Stripe: support can cancel directly. Apple: redirect only. Google: support can cancel or redirect. Retention offer applies only to full-price Stripe subscribers.
- **Judgment call areas:** How hard to push the retention offer before canceling. When to proactively surface refund eligibility alongside a cancellation request.
- **Gaps:** No policy yet on canceling during a free trial (presumably ends the trial with no charge — verify with team).

# Saved Reply Mapping

The correct saved reply is determined by account and subscription data. Work through: account status → auto-renew status → platform → discount status → expiry timing.

## No subscription / edge cases

| Condition | Saved Reply | Notes |
|---|---|---|
| Free account, no subscription | `CancelRefund FreeAccountCancel` | Explains no active sub; asks for receipt/alternate email if they think they're subscribed |
| Account has been deleted | `CancelRefund AllCancelDeletedAccount FILLIN` | Fill in ACCOUNTADDRESS |
| Platform unclear, need more info | `CancelRefund PlatformUnclearCancel` | Use when we can't determine provider from account data |
| Customer is actually 10% Happier | `CancelRefund 10%HappierSub` | Redirect to 10% Happier support; we are not affiliated. Unsure it's actually theirs? Run `bert-disambiguate-10-percent` first |

## Auto-renew already off

| Condition | Saved Reply | Notes |
|---|---|---|
| Stripe, auto-renew already off | `CancelRefund StripeCancelConfirm` | Confirms cancel + expiry; first-contact reply |
| Apple, auto-renew already off | `CancelRefund AppleConfirmCancelOfAutoRenew` | Confirms cancel + links Apple's manage subscriptions page |
| Google Play, auto-renew already off | `CancelRefund AllSet` | Generic confirm; no Google-specific reply exists |
| Any platform, customer writing back after prior cancellation | `CancelRefund AllSet` | Short follow-up confirm |

> **Always include expiration date in natural language** (e.g., "May 31, 2026").

## Stripe — Active auto-renew, cancellation requested

| Condition | Saved Reply | Notes |
|---|---|---|
| Full price (no active discount) | `CancelRefund StripeCancel Into40%Discount` | Cancels + offers 40% to stay; only use when renewing at full price |
| Has active discount, expiry is far out | `CancelRefund StripeCancel EndsLater` | Cancels; emphasizes they can still use the app in the meantime |
| Has active discount, expiry is soon | `CancelRefund StripeCancel EndsSoon` | Cancels; focuses on what happens after expiry |
| Subscription already expired, turn off renewal notices | `CancelRefund StripeCancel ChurnBuster` | For lapsed subs receiving billing notices; cancels the renewal |
| Trial cancellation (Stripe or Google) | `CancelRefund Stripe/GoogleCancel Trial` | Cancels trial auto-renewal; includes feedback ask |
| Customer intent unclear — cancel or refund? | `CancelRefund StripeCancelOrRefund` | Use when charge is recent and refund eligibility is in play; see *Refund Policy* |

## Apple — Cancellation requested

| Condition | Saved Reply | Notes |
|---|---|---|
| Active subscription, wants to cancel | `CancelRefund AppleCancel` | Provides Apple cancellation steps; we cannot cancel for them |
| Trial cancellation | `CancelRefund AppleCancelTrial` | Trial-specific framing + Apple cancellation steps |

## Google Play — Cancellation requested

| Condition | Saved Reply | Notes |
|---|---|---|
| Active subscription, wants to cancel | `CancelRefund GoogleCancel` | Support cancels directly in Google Play admin |
| Trial cancellation | `CancelRefund Stripe/GoogleCancel Trial` | Shared with Stripe trial reply |

# Related Policies

- *Subscription & Billing Overview*
- *Refund Policy*
- *Renewal Discount Requests* (if customer wants to keep the subscription at a discount instead of canceling)
- *Plan Switching* (if customer wants to switch plans instead of cancel)
- *Apple/Google → Stripe Migration*
