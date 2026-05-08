# Monthly discount requests
# Summary

We do not offer discounts on monthly subscriptions. When a monthly customer asks for a discount, the standard counter-offer is **50% off an annual subscription** (better long-term value). If that doesn't fit the customer's needs, we can explore a need-based complimentary subscription.

# Trigger Conditions

- **Ticket signals:** monthly subscriber asks for a discount, lower price, deal, promo, says monthly is too expensive
- **Account signals:** active monthly subscription on any provider
- **Keywords / phrases:** "discount," "deal," "promo," "too expensive," "can't afford," "cheaper option," "any deals," "reduce my price," "lower rate"

# Required Context

- [ ]  Confirm customer is on monthly (not annual)
- [ ]  Provider (Stripe, Apple, Google Play) — affects whether we can offer the 50% annual ourselves or need to migrate them
- [ ]  Whether they've expressed any need-based reason (financial hardship, fixed income, etc.)
- [ ]  Whether they've previously requested discounts or had a complimentary subscription (context for tone)

# Policy / Correct Response

## Standard Case

**The offer ladder:**

1. **First offer: 50% off annual.** Frame it as the better-value option compared to continuing at $14.99/month. Annual at 50% off = ~$50 vs. ~$180/year on monthly. Make the math obvious.
2. **If 50% off annual doesn't work for them** (they truly need monthly, can't afford the upfront annual cost, etc.) and they express need-based concerns: explore a **need-based complimentary subscription** per *Need-Based Complimentary Subscriptions*.
3. **Never just decline outright.** Always offer the 50% annual first.

**Why not offer monthly discounts directly:** Firm policy. Monthly is priced as it is, and discounts on monthly aren't part of our pricing structure. The 50% annual offer gives customers a real path to a lower effective rate while keeping monthly pricing clean.

## Variations

- **Customer is on Stripe monthly:** We can apply the 50% annual coupon directly through a refund-and-resubscribe or by setting up the new annual subscription with the coupon. Standard *Plan Switching* + *Apple/Google → Stripe Migration* logic.
- **Customer is on Apple monthly:** They must cancel Apple monthly themselves, then we send a Stripe annual subscription link with 50% off. See *Apple/Google → Stripe Migration*.
- **Customer is on Google monthly:** We can cancel/refund the Google monthly per *Refund Policy*, then send them a Stripe annual link with 50% off. See *Apple/Google → Stripe Migration*.
- **Customer accepts 50% annual:** Process per provider rules.
- **Customer declines 50% annual and expresses financial hardship:** Pivot to *Need-Based Complimentary Subscriptions*.
- **Customer declines 50% annual without hardship reason:** Politely close — we don't have other discount options. They may continue on monthly or cancel.

## Edge Cases & Exceptions

- **Customer asks for a monthly discount specifically ("I want monthly cheaper, not annual")**: Hold the line — no monthly discounts, full stop. Offer the 50% annual as the only available option. If declined, no further offer except hardship path.
- **Customer is converting from a previously discounted annual to monthly because of upfront cost:** Annual at 50% off may actually solve their problem. Make the math explicit.
- **Customer mentions hardship right away** (before being offered the 50% annual): It's still worth offering the 50% annual first — it's the standard ladder, and many customers in hardship can manage the discounted annual lump sum. If they can't, move to complimentary.
- **Customer is asking for a discount because they're using monthly as an extended trial:** Not a hardship case. 50% annual offer stands; if declined, no further offer.

# Action Classification

## No Action Required (reply only)

- Initial offer of 50% off annual (sending the offer and explaining the math).
- Declining when customer rejects 50% annual without a hardship reason.
- **Apple/Google monthly customer accepts 50% annual offer:** AI sends Apple/Google cancellation instructions + pre-built Stripe 50% off annual link. This is reply-only because the customer is not an existing Stripe account holder — no admin action on our end. See *Apple/Google → Stripe Migration* and *Account Lookup Data Model*.

## Human Action Required

- **Action:** Process the plan switch for an **existing Stripe monthly subscriber** (refund monthly + create discounted annual subscription, or apply coupon code on their Stripe account).
- **When:** Customer is on Stripe monthly and accepts the 50% annual offer.
- **Why AI can't do it:** Multi-step billing action on an existing Stripe subscription — refund + new subscription creation + coupon application.
- **Action:** Cancel/refund Google monthly subscription on our end (if customer requests it as part of migration).
- **When:** Customer is on Google monthly, accepts 50% annual, and wants us to cancel the Google sub rather than self-serving.
- **Why AI can't do it:** Google admin access required.
- **Action:** Set up need-based complimentary subscription.
- **When:** Customer declines 50% annual and expresses hardship.
- **Why AI can't do it:** Discretionary judgment + admin setup. See *Need-Based Complimentary Subscriptions*.

## Do Not Auto-Send Conditions

Even when the reply is "reply-only" (no admin action needed), flag for human review before sending if any of the following are true:

- Customer expresses financial hardship alongside the discount request — may need to pivot to complimentary subscription path, which is a discretionary judgment
- Customer is angry, threatening churn, or mentions chargebacks — tone-sensitive response requiring human calibration
- Customer has previously received a complimentary subscription or multiple discounts (visible in ticket history) — human should assess the pattern before making another offer
- Customer is asking for a specific non-standard arrangement (quarterly billing, custom pricing) — outside standard policy

## Escalation Triggers

- **Two or more subscribed accounts found across any email in the ticket** → escalate immediately to support leadership. Do not send any reply.

- **Customer is highly upset about monthly pricing and threatens churn / chargeback** → senior support.
- **Customer is requesting an unusual arrangement** (e.g., quarterly billing, custom pricing) → senior support; we don't offer these.

# Confidence Notes

- **High confidence areas:** No discounts on monthly. 50% annual as the universal counter-offer. Pivot to complimentary subscription on hardship.
- **Judgment call areas:** Whether to offer the 50% annual to every monthly discount request, or only those that seem genuine. Currently the rule is **always offer it** — even if the customer seems unlikely to accept, the offer is the standard practice.

# Related Policies

- *Subscription & Billing Overview*
- *Plan Switching*
- *Apple/Google → Stripe Migration*
- *Need-Based Complimentary Subscriptions*
- *Renewal Discount Requests*
