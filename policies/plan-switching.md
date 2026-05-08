# Plan switching
# Summary

Plan switches (annual ↔ monthly) are uncommon but supported. The default path is to switch at next renewal with no proration. Customers within their refund window can be refunded and resubscribed to a different plan immediately. Apple customers manage switches themselves; Google customers requiring a switch outside the refund window are pushed to Stripe.

# Trigger Conditions

- **Ticket signals:** customer wants to switch from annual to monthly, monthly to annual, change plan, downgrade, upgrade
- **Account signals:** active subscription on any provider; plan type currently differs from what customer is requesting
- **Keywords / phrases:** "switch plan," "change to monthly," "change to annual," "downgrade," "upgrade," "different plan," "yearly to monthly," "monthly to yearly"

# Required Context

- [ ]  Current provider (Stripe, Apple, Google Play)
- [ ]  Current plan (annual or monthly)
- [ ]  Desired plan
- [ ]  Date of last charge — is the customer within refund window? (30 days annual / 24 hours monthly)
- [ ]  Whether customer mentions wanting / needing a discount on the new plan

# Policy / Correct Response

## Standard Case

**Default rule: switch at next renewal, no proration.** The current subscription period runs out as scheduled. The new plan begins on the next renewal date.

### By provider

- **Apple:** Customer switches themselves via Apple subscription management. We cannot do this for them. Redirect with instructions.
- **Stripe:** Support queues the plan change for the next renewal. Or, if customer is within refund window, see refund-and-resubscribe path below.
- **Google Play:** Same as Stripe — switch at next renewal. Or, if within refund window, refund-and-resubscribe.

### Refund-and-resubscribe path (immediate switch)

If the customer is within the standard refund window:

- **Annual within 30 days** of charge
- **Monthly within 24 hours** of charge

Then support can:

1. Refund the current subscription (per *Refund Policy*).
2. Resubscribe them on the desired plan.

**Resubscribe handling differs by provider:**

- **Stripe:** Support handles the entire flow — refund + create new subscription on the desired plan. End-to-end support action.
- **Google:** Support refunds, but **the customer must resubscribe themselves**. We cannot create a subscription in Google Play. **Default practice: push them to Stripe** for the new subscription (send a Stripe subscription link). They get better support tooling and we can serve them more flexibly going forward.

## Variations

- **If customer is on Apple and wants to switch:** Redirect to Apple. They handle it.
- **If customer is on Stripe and within refund window:** Offer the refund-and-resubscribe path if they want an immediate switch. Otherwise, queue the switch at next renewal.
- **If customer is on Stripe and past refund window:** Switch at next renewal only. No mid-cycle switch, no proration.
- **If customer is on Google and within refund window:** Refund + push to Stripe for the new subscription (preferred). Customer can also resubscribe on Google themselves if they prefer.
- **If customer is on Google and past refund window:** Switch at next renewal only. (Or they can cancel and resubscribe on Stripe at any time, but this is a customer-driven action.)
- **If customer wants a discount on the new plan (monthly → annual):** Discount is opt-in. Apply only if they specifically request it. See *Renewal Discount Requests* and *Monthly Discount Requests* for the relevant rules.

## Edge Cases & Exceptions

- **Customer on intro discount wants to switch annual → monthly:** They lose the intro discount (no discounts on monthly). Make sure they understand the trade-off before processing. Worth flagging in the reply: "Switching to monthly means losing your discounted annual rate of $X — are you sure you want to proceed?"
- **Customer wants to switch monthly → annual and asks for a discount:** Discount is available on annual; apply 40% (or whatever's relevant) **only if they ask**. Default to standard $99.99 pricing if they don't mention discount. Cross-reference *Renewal Discount Requests* if they had previously been on an intro discount.
- **Customer is on Apple and wants the discount that's only available via Stripe:** They must cancel/expire on Apple, then we send them a Stripe subscription link with the discount applied. This is *Apple/Google → Stripe Migration* territory.
- **Customer wants to switch from one annual to a different annual** (e.g., promo to non-promo, or vice versa): Not really a plan switch — handle via *Renewal Discount Requests* if the goal is discount adjustment.

# Action Classification

## No Action Required (reply only)

- Apple customers: redirect to Apple, reply only.
- Explaining the next-renewal switch policy when the customer is past the refund window and providing the appropriate Stripe sign up link for after expiration.

## Human Action Required

- **Action:** Refund + resubscribe end-to-end (Stripe).
- **When:** Customer is within refund window and wants an immediate switch.
- **Why AI can't do it:** Multi-step billing action requiring admin access and judgment.
- **Action:** Refund on Google + send Stripe subscription link.
- **When:** Customer is on Google, within refund window, and wants an immediate switch.
- **Why AI can't do it:** Refund processing + decision to push to Stripe is a support action.

## Do Not Auto-Send Conditions

Even when the reply is "reply-only" (no admin action needed), flag for human review before sending if any of the following are true:

- Customer is on an intro discount and switching annual → monthly — they'll lose the discount, and the trade-off warning requires human judgment on framing
- Customer is pushing back on the no-proration rule — tone-sensitive response, potential churn risk
- Customer's plan switch request is combined with a discount request — multi-policy interaction needs human verification that the correct offer is being made
- Customer's desired switch involves a provider migration (Apple/Google → Stripe) — multi-step explanation with friction; verify reply completeness

## Escalation Triggers

- **Two or more subscribed accounts found across any email in the ticket** → escalate immediately to support leadership. Do not send any reply.

- **Customer pushing back on the no-proration rule** → senior support if they're insistent or mention a heart wrenching personal circumstance.
- **Customer wants a custom plan or non-standard switching arrangement** → senior support.

# Confidence Notes

- **High confidence areas:** No proration ever. Switch at next renewal as default. Refund-and-resubscribe path within refund window. Apple = customer-managed. Google resubscribe must be customer-initiated, push to Stripe by default.
- **Judgment call areas:** Whether to proactively warn customers about losing intro discounts when switching annual → monthly. Currently we should — but it's framed as best practice, not a hard rule.

# Related Policies

- *Subscription & Billing Overview*
- *Refund Policy*
- *Apple/Google → Stripe Migration*
- *Renewal Discount Requests*
- *Monthly Discount Requests*