# Summary

When an Apple or Google customer wants something we can't do on their original platform — a discount, a plan switch (in some cases), or any subscription action requiring our admin tools — we end the existing subscription on their original provider and resubscribe them through Stripe. This is the universal workaround for limitations of Apple and Google's billing systems.

# Trigger Conditions

- **Ticket signals:** Apple or Google customer asks for a discount, plan change in a way Google/Apple can't accommodate, ongoing discount, or any other action we have no native ability to perform on their original provider
- **Account signals:** active or recently-active Apple or Google subscription; customer requesting something requiring our billing admin access
- **Keywords / phrases:** "discount," "can you do anything," "switch," "change my subscription," "is there a deal," "I'm on Apple/Google but…"

# Required Context

- [ ]  Customer's current provider (Apple or Google Play)
- [ ]  What they're asking for (discount type, plan change, ongoing arrangement)
- [ ]  Their current renewal date or expiration date — determines when the migration can happen
- [ ]  Whether they've already canceled or refunded on their original provider
- [ ]  Auto-renew status
- [ ]  Whether they're aware they'll need to resubscribe (vs. expecting a seamless transfer)

# Policy / Correct Response

## Standard Case

**The migration path:**

1. **End the existing subscription on the original provider.**
    - **Apple:** Customer must cancel on their own via Apple subscription management. We cannot. They can also request a refund via Apple's `reportaproblem` flow if they're within Apple's refund window.
    - **Google:** Customer can cancel themselves via Google Play subscription management, or support can cancel/refund on the Google side (per *Refund Policy* if within refund window).
2. **Wait for the existing subscription to expire** (or refund to process), so the customer isn't double-paying. They will see an error if they try to resubscribe while they currently have access. 
    - If they're refunded: action can happen quickly.
    - If they're just canceling the next renewal: they keep access until their current period ends, then resubscribe via Stripe.
3. **Send the customer a Stripe subscription link** for the plan they want, with any applicable discount applied (e.g., 40% off renewal coupon, complimentary subscription, etc.).

**Set expectations clearly in the reply:**

- They will need to take action themselves (cancel on Apple/Google, click the Stripe link).
- The discount or special arrangement only applies on the new Stripe subscription.
- They will have to wait until their expiration date before resubscribing. Always mention the date specifically.
- This isn't seamless — there's a window of action required from them.

## Variations

- **Customer wants ongoing 40% renewal discount** but is on Apple → migrate to Stripe with the discount applied to the new subscription.
- **Customer wants 50% off annual** (counter-offer to a monthly discount request) but is on Apple/Google monthly → migrate to Stripe annual with the 50% applied.
- **Customer wants a plan switch** within their refund window → see *Plan Switching* (refund-and-resubscribe path).
- **Customer wants something we don't actually offer** (e.g., a one-time payment instead of subscription) → decline; this isn't a migration scenario.

## Edge Cases & Exceptions

- **Customer is hesitant about migrating** because they trust Apple/Google billing more: That's fine — we don't force migration. The trade-off is they don't get the discount/feature they're asking for. Be clear: the option is theirs.
- **Customer migrates to Stripe and then has issues** (failed payment, etc.): They're now subject to *Failed Payment / Dunning (Stripe)* policy.
- **Customer's Apple/Google subscription auto-renews before they migrate:** Refund per *Refund Policy* if within window. If past window on Google, we can cancel the next renewal but they'll need to wait it out. Apple = redirect to Apple.
- **Customer wants the migration but doesn't want to manage two cancellations / waits:** Be honest about the friction. Some customers will decline. That's an acceptable outcome.
- **Customer migrates and then asks to migrate back** (Stripe → Apple/Google): They'd need to cancel Stripe and resubscribe on the original provider themselves. We don't push customers off Stripe.

# Action Classification

**Key principle:** The migration path for Apple/Google customers who are NOT existing Stripe account holders is **reply-only / auto-sendable.** We have **standardized pre-built Stripe links** with discounts baked in. The AI sends: (1) cancellation/expiry instructions for the current provider, and (2) the appropriate Stripe link. No admin action on our end.

**Past Stripe users:** Even if the customer had a previous Stripe subscription, we still send the Stripe link (not modify on our end). We want them to re-enter current card info. This is the same as new-to-Stripe — **reply-only.**

**How to determine Stripe account status:** Check `Subscription Platform` in the account lookup data. See *Account Lookup Data Model*.

## No Action Required (reply only)

- **The entire Apple/Google → Stripe migration flow when the customer is not a current active Stripe subscriber.** This covers the vast majority of migrations. The AI:
    - Sends cancellation instructions for Apple (customer-managed) or Google (customer-managed, or we can cancel — see below)
    - Sends the appropriate pre-built Stripe link (40% off, 50% off, standard, complimentary, etc.) from the *Account Lookup Data Model* Standardized Stripe Links section
- Apple cancellation step is always reply-only (we can't act).
- Explaining the migration path, framing the value proposition, answering questions about the process.

## Human Action Required

- **Action:** Cancel or refund the Google subscription on Google's side.
- **When:** Customer is on Google and wants us to cancel/refund before migrating to Stripe. (They can also self-serve this via Google Play.)
- **Why AI can't do it:** Google admin access required for cancellation/refund on our end.
- **Action:** Set up the new Stripe subscription with discount/coupon applied directly on the customer's existing active Stripe account.
- **When:** Customer is a **current active Stripe subscriber** and we're modifying their existing subscription (not migrating from Apple/Google).
- **Why AI can't do it:** Stripe admin access required to modify an existing subscription.

## Do Not Auto-Send Conditions

Even when the reply is "reply-only" (no admin action needed), flag for human review before sending if any of the following are true:

- Customer is hesitant or expressing distrust about switching billing platforms — tone-sensitive persuasion that requires human calibration
- The migration involves a complimentary subscription setup — discretionary grant, always requires human approval (see *Need-Based Complimentary Subscriptions*)
- Customer's current subscription is mid-period and the timing/overlap explanation is complex — human should verify the reply correctly addresses their specific renewal date and expected gap
- Customer is frustrated by the friction of migration and mentions churn risk — human judgment on whether to offer additional accommodation
- The Stripe link placeholders in *Account Lookup Data Model* have not been filled in yet — do not send a reply that references links that don't exist

## Escalation Triggers

- **Two or more subscribed accounts found across any email in the ticket** → escalate immediately to support leadership. Do not send any reply.

- **Customer wants a migration arrangement that involves non-standard pricing or terms beyond documented offerings** → senior support.
- **Customer is highly frustrated by the friction of migration** → senior support if they're at churn risk.

# Confidence Notes

- **High confidence areas:** Migration is the universal workaround. Apple cancellation must be customer-initiated. Google resubscribe must be customer-initiated. Default destination is Stripe.
- **Judgment call areas:** When to proactively suggest migration vs. just answer the original question. Generally: if the customer is asking for something we can't do on their provider, suggest migration; otherwise don't volunteer it.
- **Gaps:**
    - No defined policy on whether we offer any goodwill credit / extension to compensate for the friction of migration.
    - Behavior when customer's Apple subscription is mid-period and they want immediate access to a Stripe-only feature (none currently exist, but worth noting).

# Related Policies

- *Subscription & Billing Overview*
- *Refund Policy*
- *Plan Switching*
- *Renewal Discount Requests*
- *Monthly Discount Requests*
- *Need-Based Complimentary Subscriptions*