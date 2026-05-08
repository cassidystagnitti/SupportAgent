# Free trial policy
# Summary

We offer a 7-day free trial on the annual subscription, available on all providers. Payment method is required up front; the trial auto-converts to a paid annual subscription unless the customer cancels.

# Trigger Conditions

- **Ticket signals:** customer mentions "trial," "free trial," "trial period," wants to try the app, asks how to cancel before being charged, says they thought it was free, says they didn't mean to be charged after a trial
- **Account signals:** account is currently in trial, recently exited trial (within ~30 days), or trial converted to paid charge recently
- **Keywords / phrases:** "trial," "free trial," "7 days," "didn't want to be charged," "thought it was free," "cancel before charged," "trial ended"

# Required Context

- [ ]  Is the customer currently in trial, or has the trial already converted?
- [ ]  If converted: how many days ago? (Refund Policy windows still apply post-conversion.)
- [ ]  Provider (Stripe, Apple, Google Play)
- [ ]  Did the customer cancel during trial, or did it auto-convert?

# Policy / Correct Response

## Standard Case

**Trial terms:**

- **Duration:** 7 days.
- **Plan eligibility:** Annual subscription only. One one trial per account. **No trial on monthly.**
- **Provider availability:** All providers (Stripe, Apple, Google Play).
- **Payment method:** Required at trial start. The trial auto-converts to a paid annual subscription at day 7 unless the customer cancels.
- **Cancellation during trial:** Free, no charge. Self-serve or via support (Apple = external only).
- **Trial entry:** Customer can start a trial from within the app or on our website.

**Standard responses:**

- **"How do I cancel my trial before being charged?"** → Provider-specific instructions:
    - Stripe: cancel via app settings, or support can cancel.
    - Google Play: cancel via Google Play subscription management, or support can cancel.
    - Apple: must cancel via Apple subscription settings; we cannot.
- **"My trial converted and I was charged — I didn't want it."** → This is a refund question. Apply *Refund Policy* (within 30 days of charge = full refund on Stripe/Google; Apple = redirect to Apple).

## Variations

- **If customer is on Apple and wants to cancel trial:** Redirect to Apple subscription management. We cannot cancel for them.
- **If customer is on Stripe or Google Play and wants to cancel trial:** Support can cancel directly, or point them to self-serve.
- **If trial already converted and customer is within 30 days of the charge:** Refund per *Refund Policy*.
- **If trial already converted and customer is past 30 days:** No refund; cancel at next renewal per *Refund Policy*.

## Edge Cases & Exceptions

- **Customer claims they never started a trial but were charged:** Investigate account history before refunding. Could be account confusion (different email, family member, etc.) or genuine error. Treat as needing human review.
- **Customer asks for a second trial after a previous trial:** We can extend a 7 day comp in some cases. Flag for oversight.
- **Customer asks for a trial on the monthly plan:** We can extend a 7 day comp in some cases. Flag for oversight.
- **Customer's trial cancellation didn't go through and they were charged anyway:** Treat as a billing error. Refund (within window via standard policy) and flag for engineering visibility if pattern emerges.

# Action Classification

## No Action Required (reply only)

- Informational questions about trial terms (length, what's included, how to start one).
- Redirecting Apple customers to Apple to cancel their trial.
- Explaining that trial conversion is expected behavior when payment method was provided up front.

## Human Action Required

- **Action:** Cancel trial on Stripe or Google Play.
- **When:** Customer requests cancellation and is on Stripe or Google Play (and they're not self-serving).
- **Why AI can't do it:** Modifying subscription state requires provider admin access.
- **Action:** Refund post-conversion charge.
- **When:** Trial converted, customer is within refund window, on Stripe or Google.
- **Why AI can't do it:** Refund requires provider admin access.

## Do Not Auto-Send Conditions

Even when the reply is "reply-only" (no admin action needed), flag for human review before sending if any of the following are true:

- Customer claims they never started a trial but were charged — requires account history investigation before any reply
- Customer is asking for a second trial or a trial on monthly — discretionary decision, not a standard policy path
- Customer's trial cancellation appears to have failed (they were charged despite claiming they canceled) — potential billing error needs verification before responding
- Customer's tone suggests they feel deceived by the trial-to-paid conversion — human judgment on framing and empathy needed

## Escalation Triggers

- **Two or more subscribed accounts found across any email in the ticket** → escalate immediately to support leadership. Do not send any reply.

- **Customer claims trial fraud or unauthorized signup** → senior support.
- **Repeat trial requests** → senior support / leadership (no policy yet).
- **Pattern of failed trial cancellations** → engineering visibility.

# Confidence Notes

- **High confidence areas:** 7-day duration, annual-only, payment method required, all providers, free cancellation during trial.
- **Judgment call areas:** Repeat trials.

# Related Policies

- *Subscription & Billing Overview*
- *Refund Policy* (post-conversion charge handling)
- *Apple/Google → Stripe Migration* (if customer wants to cancel Apple trial and resubscribe via Stripe)