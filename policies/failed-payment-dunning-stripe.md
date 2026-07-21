# Summary

Covers failed payment / declined card scenarios across all three providers. Stripe has a managed dunning flow we support directly; Apple and Google manage their own dunning, and we redirect customers to their respective platforms. See *Account Lookup Data Model* for how to determine the customer's provider.

# Trigger Conditions

- **Ticket signals:** customer mentions a failed payment, declined card, expired card, needing to update credit card, getting a payment failure email, losing access, "my subscription lapsed"
- **Account signals:** subscription with recent failed charge, in retry/grace period, or recently suspended/expired due to payment failure
- **Keywords / phrases:** "payment failed," "card declined," "expired card," "new card," "update card," "can't pay," "renewal failed," "got an email about my payment," "lost access," "suspended"

# Required Context

- [ ]  **Subscription Platform** from account lookup (Stripe, Apple, or Google) — determines which flow applies
- [ ]  **Subscribed** status and **Subscription Expiration Date** — is the customer still in a grace/retry period or already suspended?
- [ ]  **Auto Renew Status** — is the subscription still set to renew (payment issue) vs. already canceled by the customer?
- [ ]  If Stripe: date of first failed charge attempt (determines position in 30-day retry window)
- [ ]  Whether the customer has already updated their payment method (per their statement)

# Policy / Correct Response

## Stripe

### How Stripe dunning works

- **Retry window:** Stripe automatically retries the charge over a **30-day period** from the first failure.
- **Access during retry window:** Customer **retains access** for the full 30 days while retries continue.
- **Suspension:** If no successful charge by day 31, the subscription is suspended and access is revoked.
- **Dunning emails:** Sent automatically with a link to update credit card.
- **Customer self-serve:** Customers can update their card via in-app settings (same outcome as the dunning email link). **The canonical self-serve path is IN APP: Profile → Settings → Subscription** (confirmed 2026-07-21). When drafting, give these in-app steps — do NOT invent a web URL for card updates; no standalone update-card web page is documented. (The "update-card link" below refers to the link inside Stripe's automated dunning emails, which the customer already has; support replies point to the in-app path.)

### Standard support response (Stripe)

1. **Customer hasn't updated card yet:** Send the **update-card link** (same one used in dunning emails). **Reply-only — no support action.**
2. **Customer says they already updated their card** but the charge hasn't gone through: Support can **manually retry** the Stripe charge. **Human action required.**
3. **Customer wants to cancel instead of paying:** Cancel the subscription. Standard cancellation flow.
4. **Customer is past the 30-day retry window (already suspended):** They'll need to start a new subscription. The old one is gone. Send subscription link. **Reply-only.**

## Apple

### How Apple dunning works

Apple manages its own payment retry and grace period flow entirely. We have **no visibility into Apple's retry schedule**, no ability to retry charges, and no ability to update the customer's payment method.

### Standard support response (Apple)

- **Direct the customer to Apple's subscription and payment management.** They need to update their payment method through Apple (Settings → Apple ID → Payment & Shipping, or via the App Store).
- **If the customer says they've updated their payment on Apple's side and it's still failing:** We cannot troubleshoot Apple's billing. Advise them to contact Apple Support directly.
- **If the customer has lost access due to Apple payment failure and wants to keep using the app:** If they can resolve the payment issue with Apple, their subscription will resume. If they can't or won't, offer the *Apple/Google → Stripe Migration* path — they can cancel the failed Apple subscription and start fresh on Stripe.
- **All Apple failed-payment responses are reply-only.** We have no admin action to take.

## Google Play

### How Google Play dunning works

Google manages its own payment retry and grace period flow. Similar to Apple, we have **limited visibility into Google's retry schedule**.

### Standard support response (Google)

- **Direct the customer to Google Play's subscription and payment management** to update their payment method.
- **If the customer says they've updated their payment on Google's side and it's still failing:** We cannot troubleshoot Google's billing retry. Advise them to contact Google Play Support.
- **If the customer has lost access due to Google payment failure and wants to keep using the app:** If they can resolve the payment issue with Google, their subscription will resume. If they can't or won't, offer the *Apple/Google → Stripe Migration* path — they can let the Google subscription expire and start fresh on Stripe. We can also cancel the Google subscription on our end if needed.
- **Informational responses (directing to Google docs) are reply-only.** Canceling the Google subscription on our end is **human action required.**

# Variations

- **Customer on Stripe, hasn't updated card:** Send update-card link. Reply only.
- **Customer on Stripe, says card is updated:** Manual retry. Human action.
- **Customer on Stripe, past 30-day window (suspended):** Send new subscription link. Reply only.
- **Customer on Apple:** Redirect to Apple payment management. Reply only. Offer Stripe migration if they can't resolve with Apple.
- **Customer on Google:** Redirect to Google Play payment management. Reply only. Offer Stripe migration if they can't resolve with Google. Cancel Google sub if they request it (human action).
- **Customer on any provider who wants to cancel instead of fixing payment:** Process per standard cancellation rules — Stripe and Google via support, Apple via Apple.
- **Customer doesn't know why they lost access:** Check account data — `Subscribed` status, `Auto Renew Status`, `Subscription Expiration Date`. If expired with `auto_renew = false`, they canceled. If expired with `auto_renew = true` or recently failed charges, it's a payment issue. Route accordingly.

# Edge Cases & Exceptions

- **Customer on Stripe claims they updated card but Stripe shows no update:** Could be a save failure, wrong card type, or a payment method Stripe is declining. Walk them through the update flow again. If repeated failures, escalate.
- **Customer's Stripe card keeps failing after multiple updates:** Likely a card/bank issue (international card, fraud lock, insufficient funds). Suggest they contact their bank. Don't keep manually retrying.
- **Customer wants a refund for a Stripe charge that succeeded after multiple failures:** Standard *Refund Policy* applies — within 30 days of the successful charge = refundable.
- **Customer wants extended access without paying:** Not a standard offer. If hardship-related, see *Need-Based Complimentary Subscriptions*.
- **Customer on Stripe is suspended and wants their old subscription "reactivated":** We can't restore the old subscription after suspension. They start fresh. If they were on an intro discount and lost it due to suspension, judgment call — flag for senior support.
- **Customer on Apple/Google is confused about why we can't help with their payment:** Explain clearly: their subscription is managed by Apple/Google, and payment updates must go through that platform. We don't have access to their Apple/Google billing. Offer migration to Stripe as the alternative for future flexibility.
- **Customer on Apple/Google wants to migrate to Stripe after failed payment:** Follow *Apple/Google → Stripe Migration* — send cancellation instructions for current provider + appropriate Stripe link. **Reply-only / auto-sendable** since they're not an existing Stripe account holder (or if they are a past Stripe user, we still send the link so they re-enter current card info).

# Action Classification

## No Action Required (reply only)

- **Stripe:** Sending the update-card link when customer hasn't updated yet. Sending a new subscription link when customer is past the retry window and suspended.
- **Apple:** All failed-payment responses. Redirecting to Apple documentation. Offering migration path (sending Apple cancellation instructions + Stripe link).
- **Google:** Redirecting to Google Play documentation. Offering migration path (sending Google cancellation instructions + Stripe link).
- **Any provider:** Explaining what happened (why access was lost, what their options are).

## Human Action Required

- **Action:** Manually retry Stripe charge.
- **When:** Customer on Stripe states they have updated their card but the charge hasn't retried.
- **Why AI can't do it:** Stripe admin action requiring authenticated access.
- **Action:** Cancel subscription (Stripe or Google) on customer's request.
- **When:** Customer wants to cancel instead of fixing payment.
- **Why AI can't do it:** Subscription state change requires provider admin access.
- **Action:** Cancel Google subscription as part of migration to Stripe.
- **When:** Customer on Google wants to migrate after failed payment and requests we cancel on Google's side.
- **Why AI can't do it:** Google admin action.

## Do Not Auto-Send Conditions

Even when the reply is "reply-only" (no admin action needed), flag for human review before sending if any of the following are true:

- Customer claims they were suspended despite having a working card — potential system error, needs investigation before responding
- Customer is asking for extended access without paying and mentions hardship — requires judgment on whether to pivot to complimentary subscription path
- Customer's Stripe card has failed multiple times across multiple updates — situation is complex enough to warrant human assessment of next steps
- Customer on Apple/Google is confused or frustrated about why we can't help with their payment — tone-sensitive explanation requires human review
- Suspended Stripe customer asks about recovering intro pricing or special terms they had before suspension — judgment call on whether to honor

## Escalation Triggers

- **Two or more subscribed accounts found across any email in the ticket** → escalate immediately to support leadership. Do not send any reply.

- **Repeated Stripe card failures across multiple update attempts** → senior support to investigate; may flag engineering if Stripe-side issue.
- **Customer claims they were suspended despite a working card** → senior support / engineering.
- **Suspended Stripe customer requesting restoration of an intro discount or special pricing** → senior support judgment call.
- **Customer on any provider claiming unauthorized charges during a dunning/retry window** → senior support.

# Confidence Notes

- **High confidence areas:** Stripe's 30-day retry window, access maintained during retries, suspension at day 31, dunning email flow, update-card link as primary response, manual retry available when card already updated. Apple and Google = redirect to their platforms, we can't help directly with their payment issues.
- **Judgment call areas:** Restoring intro discounts after Stripe suspension. Goodwill access extension during dunning. When to proactively suggest Stripe migration vs. just helping them fix their Apple/Google payment.
- **Gaps:**
    - Whether suspended Stripe customers can recover old subscription terms (grandfathered pricing, etc.).
    - No defined limit on how many manual Stripe retries we'll do for one customer.
    - Specific Apple and Google grace period durations — we don't control or necessarily know these. If a customer asks "how long do I have before I lose access on Apple," we can only point them to Apple's documentation.

# Related Policies

- *Account Lookup Data Model* (for determining provider and subscription status)
- *Subscription & Billing Overview*
- *Refund Policy*
- *Apple/Google → Stripe Migration*
- *Need-Based Complimentary Subscriptions* (if hardship)