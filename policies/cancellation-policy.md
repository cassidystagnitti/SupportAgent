# Cancellation policy
# Summary

Handles requests to cancel a subscription (turn off auto-renewal). The customer keeps full access through their period end date. Support can cancel directly on Stripe and Google Play; Apple customers are redirected to self-service. A key edge case: many customers write in when auto-renew is already off — in that case, simply confirm they're set and include the expiration date. For Stripe customers renewing at full price, offer a 40% retention discount before canceling.

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
- **Stripe, full price:** Lead with retention offer. If declined or not desired, cancel.
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

# Action Classification

## No Action Required (reply only)

- **Auto-renew already off (any platform):** Confirm they're all set, share expiration date. No admin action.
- **Apple cancellation requests:** Redirect to Apple instructions. No action available to support.

## Human Action Required

- **Action:** Turn off auto-renew in Stripe.
- **When:** Active Stripe subscription, auto-renew is on, customer confirms they want to cancel (possibly after declining retention offer).
- **Why AI can't do it:** Requires Stripe admin access.
- **Action:** Turn off auto-renew in Google Play.
- **When:** Active Google Play subscription, auto-renew is on, customer confirms cancellation.
- **Why AI can't do it:** Requires Google Play admin access.

## Do Not Auto-Send Conditions

Even when the reply is "reply-only" (no admin action needed), flag for human review before sending if any of the following are true:

- Customer's cancellation request is combined with frustration about a charge — possible refund component requiring human judgment
- Customer claims to have already canceled but is still seeing charges — may be a billing or system error that needs investigation before any reply
- Customer is on Apple and expressing escalating frustration about not being able to get direct help — warrants human-reviewed framing
- Cancellation is combined with a complaint about app quality or experience — potential goodwill scenario beyond standard policy

## Escalation Triggers

- **Two or more subscribed accounts found across any email in the ticket** → escalate immediately to support leadership. Do not send any reply.
- **Subscription is in a billing retry period** → escalate to senior support. Do not process the cancellation or send a reply until the billing state is resolved.
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
| Customer is actually 10% Happier | `CancelRefund 10%HappierSub` | Redirect to 10% Happier support; we are not affiliated |

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
