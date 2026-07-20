# Need-based complimentary subscriptions
# Summary

We offer complimentary (free) annual subscriptions on a discretionary, case-by-case basis to customers expressing genuine financial need. This is a real, available option but is not marketed. Any support agent can grant it without senior approval. The standard offer is a free year. The path to this offer is typically: customer expresses need, we first offer a relevant discount (50% annual or 40% renewal), and if that doesn't fit, we extend the complimentary offer.

# Trigger Conditions

- **Ticket signals:** customer expresses financial hardship, mentions being unable to afford the subscription, asks if there are any scholarships / free options / financial assistance, mentions specific life circumstances (fixed income, unemployment, illness, etc.)
- **Account signals:** active or recently-canceled subscription on any provider; customer engagement level may inform discretion (long-term users vs. brand-new accounts)
- **Keywords / phrases:** "can't afford," "financial hardship," "fixed income," "scholarship," "free option," "complimentary," "hardship," "unemployed," "between jobs," "on disability," "any free options," "is there any way I can keep using this"

**Important routing note:** Some trigger keywords here (e.g., "fixed income," "health challenges") overlap with *Discount Requests (Unsubscribed Users)*, which also serves customers mentioning ongoing need. The distinguishing signal is **willingness to pay vs. inability to pay.** If the customer is unsubscribed and expresses willingness to pay at a reduced rate, see *Discount Requests (Unsubscribed Users)* first — they enter the forever-discount ladder there. This policy applies when the customer signals they **cannot afford to pay at all**, or when discount offers have been exhausted and the customer still can't manage the cost.

# Required Context

- [ ]  Customer's stated reason for needing assistance (informs discretion, not a hard gate)
- [ ]  Whether a relevant discount has already been offered and declined / found insufficient
- [ ]  Provider (determines what the customer must cancel first — the comp itself is always granted through the internal admin tool)
- [ ]  Whether they currently have an active subscription that needs to be canceled/refunded first
- [ ]  What price is their current subscription
- [ ]  Whether they’ve had a comp subscription in the past

# Policy / Correct Response

## Standard Case

**The offer ladder:**

1. **First, offer the appropriate discount** for their situation:
    - Monthly customer expressing hardship → offer 50% off annual first (per *Monthly Discount Requests*).
    - Annual customer near/past renewal expressing hardship → offer 40% off renewal (per *Renewal Discount Requests*).
2. **If the discount doesn't fit their situation** — they truly cannot afford even the discounted rate, or they outright ask for a free/scholarship option — extend a **complimentary annual subscription**.
3. **Standard offer: a free year** (12 months complimentary). After that year, they can write in again if they still need help.

**Trigger signals for extending the complimentary offer:**

- Customer explicitly mentions financial concerns ("I can't afford this," "I'm on a fixed income," "I just lost my job")
- Customer asks outright about scholarships or complimentary options
- Customer declines a discount offer specifically because of inability to pay (not just preference)

**Authority:**

- **Any support agent can grant a complimentary subscription** without senior approval.
- **No formal documentation required** for who got one and why — it's case-by-case discretion.
- **The expectation is good-faith judgment.** Extend it when the situation seems genuine; don't extend it when the customer is just hunting for a free product without need signals.

## Variations

**Fulfillment (corrected 2026-07-20): complimentary subscriptions are granted through the internal admin tool, NOT Stripe.** The provider only determines what has to be cancelled first — the comp itself is always an admin-tool grant on the customer's account.

- **Customer is on Stripe:** Cancel/refund the existing paid subscription in Stripe if applicable, then grant the complimentary subscription through the admin tool.
- **Customer is on Apple:** They must cancel themselves on Apple. Once that's done (or expired), grant the complimentary subscription through the admin tool on their account email. See *Apple/Google → Stripe Migration*.
- **Customer is on Google:** Cancel/refund on Google per *Refund Policy*, then grant the complimentary through the admin tool. Same migration logic.
- **Customer doesn't yet have a subscription** (e.g., trial about to expire and they can't afford the conversion): Grant a complimentary subscription through the admin tool; no cancellation needed.
- **Customer wants a complimentary monthly:** We default to a complimentary annual (12 months free). Monthly complimentary isn't typical — the annual is cleaner.

## Edge Cases & Exceptions

- **Customer has clearly received a complimentary subscription before and is asking again:** Use judgment. If the original year is up and they still need help, granting another year is reasonable. If they're asking shortly after one was granted, may warrant a check-in or escalation.
- **Customer asks for a complimentary subscription with no expressed need signal:** Don't extend it on a cold ask. Offer the relevant standard discount (50% annual or 40% renewal). If they then express specific need, revisit.
- **Customer mentions they're requesting on behalf of someone else** (e.g., elderly parent): Fine in principle — extend the complimentary based on the situation described. Make sure the subscription is set up under the right email / account.
- **Customer is hostile or threatening** in the way they're requesting: Don't reward hostility with a complimentary offer reflexively. Consider escalation or simply offering the standard discount and holding the line.
- **Customer's account shows pattern of frequent disputes or chargebacks:** Use discretion. The complimentary offer is for genuine hardship; not for customers gaming the system. Escalate if unsure.
- **Customer is on the forever 40% discount already and now asks for a complimentary subscription:** Reasonable scenario — the forever discount may not be enough. Extend the complimentary; they've already shown ongoing need.

# Action Classification

## No Action Required (reply only)

- Initial reply offering a relevant discount when customer expresses hardship (before complimentary is on the table).
- Explaining the offer ladder if the customer asks what options exist.
- **Apple/Google customers being offered the complimentary path:** AI sends cancellation/expiry instructions for their current provider + the pre-built Stripe complimentary subscription link. This is reply-only because the customer is not an existing Stripe account holder (or is a past Stripe user who needs to re-enter card info). No admin action on our end. See *Apple/Google → Stripe Migration* and *Account Lookup Data Model*. *(NOTE 2026-07-20: comps are granted via the admin tool, so this pre-built self-serve link flow may be stale — confirm it still exists before sending it.)*

## Human Action Required

- **Action:** Grant a complimentary annual subscription (full year, free) through the **internal admin tool** — not Stripe.
- **When:** Customer has expressed need, discount-first step has been considered, and we've decided to extend the complimentary offer.
- **Why AI can't do it:** Discretionary judgment + admin-tool access required.
- **Action:** Cancel/refund existing Stripe or Google paid subscription as part of transitioning to complimentary.
- **When:** Customer has an active paid Stripe or Google subscription and we're moving them to complimentary.
- **Why AI can't do it:** Refund/cancellation = provider admin action.

## Do Not Auto-Send Conditions

Even when the reply is "reply-only" (no admin action needed), flag for human review before sending if any of the following are true:

- **All complimentary subscription offers should be flagged for human review before sending.** This is an inherently discretionary decision — the AI should draft the reply but a human must approve it. Even when the customer's need signals are clear, the grant decision is a judgment call.
- Customer's request involves unusual circumstances (on behalf of someone else, institutional/group access, multi-year request)
- Customer has a history of disputes, chargebacks, or prior complimentary subscriptions
- Customer is hostile or threatening in tone — do not reward hostility reflexively; human should assess

## Escalation Triggers

- **Two or more subscribed accounts found across any email in the ticket** → escalate immediately to support leadership. Do not send any reply.

- **Repeat complimentary requests in a short window** (e.g., second request within 6 months of being granted one) → senior support for judgment.
- **Customer's request involves unusual circumstances** (group / institutional access, multi-year complimentary, etc.) → senior support; standard policy is single-year complimentary.
- **Customer is hostile or pattern of disputes** → senior support to assess.
- **Borderline cases where the support agent is unsure** → senior support, when in doubt.

# Confidence Notes

- **High confidence areas:** Any agent can grant. No senior approval required. Default offer is a free year. Discount-first is the standard ladder. Apple/Google customers route through migration to Stripe for setup.
- **Judgment call areas:**
    - **What constitutes genuine need.** Intentionally left to discretion. The narration framing is "in good faith, when they mention specific financial concerns or ask outright about scholarships."
    - **When to extend on a first ask vs. offering discount first.** Default is discount first, but if the customer is clearly indicating no amount of paid is feasible, jumping straight to complimentary is acceptable.
    - **Repeat complimentary requests** — currently routes to escalation, but reasonable agents could just renew it.
- **Gaps:**
    - No defined cap on how many complimentary years a single customer can receive over a lifetime.
    - No defined response for customers who are clearly fishing for a free subscription without genuine need — current rule is "don't extend on a cold ask without signals," but this is judgment-based.
    - The interaction between forever 40% discount and complimentary subscription isn't formally defined — in practice, complimentary supersedes if granted.

# Related Policies

- *Subscription & Billing Overview*
- *Monthly Discount Requests*
- *Renewal Discount Requests*
- *Discount Requests (Unsubscribed Users)*
- *Apple/Google → Stripe Migration*
- *Refund Policy*