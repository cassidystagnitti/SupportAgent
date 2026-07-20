# Summary

When an unsubscribed user — whether a lapsed subscriber or someone with no account — asks for a discount or reduced price on an annual subscription, support offers discounts through an escalating ladder. We start with **40% off annual (intro)** and can escalate to **50% off annual (intro)**. If the customer expresses an ongoing, non-time-bounded need (fixed income, health challenges, etc.), we pivot to the **forever ladder**: **40% off annual forever**, escalating to **50% off annual forever**. Offers are made one at a time; we wait for the customer's response before escalating.

This policy applies only to customers who are **not currently subscribed**. Subscribed customers requesting discounts route to *Renewal Discount Requests* (annual) or *Monthly Discount Requests* (monthly). Customers who express inability to pay or request a free subscription route to *Need-Based Complimentary Subscriptions*.

# Trigger Conditions

- **Ticket signals:** unsubscribed user asks for a discount, deal, lower price, promo code, or reduced rate on the annual subscription; mentions they'd like to come back but at a lower price; asks if there are any offers available
- **Account signals:** `Subscribed: false` in account lookup (expired/canceled subscription or never subscribed), OR `Account Found: false` (no account at all)
- **Keywords / phrases:** "discount," "deal," "promo," "coupon," "lower price," "reduced rate," "any offers," "can't justify full price," "too expensive," "willing to pay but," "come back if cheaper," "is there a deal," "student discount," "senior discount," "regional pricing," "price in my country," "purchasing power," "exchange rate," "too expensive in [country]"

# Required Context

- [ ]  Account lookup result: is the user subscribed? (Must be `Subscribed: false` or `Account Found: false` for this policy to apply)
- [ ]  If account exists: previous subscription history (provider, plan, when it expired) — useful context but does not change the offer
- [ ]  Whether the customer expresses a time-bounded vs. ongoing/permanent need (determines intro vs. forever ladder)
- [ ]  Whether the customer expresses inability to pay vs. willingness to pay at a reduced rate (determines this policy vs. *Need-Based Complimentary Subscriptions*)

# Policy / Correct Response

## Standard Case

**The offer is always on the annual plan. We do not offer discounts on monthly subscriptions.**

**Two ladders, used separately based on the customer's situation:**

### Intro Ladder (default — time-bounded or no specific need expressed)

For customers who simply ask for a discount, want a deal to resubscribe, or mention a short-term budget concern:

1. **First offer: 40% off annual (intro).** Send the 40% off annual INTRO link from account lookup.
2. **If customer responds that 40% isn't enough:** Escalate to **50% off annual (intro).** Send the 50% off annual INTRO link.
3. **If 50% intro still isn't enough and the customer expresses willingness to pay:** Hold — there's no further intro offer. If they express hardship/inability to pay, pivot to *Need-Based Complimentary Subscriptions*.

### Forever Ladder (ongoing/permanent need expressed)

For customers who mention a non-time-bounded reason they need a reduced price — fixed income, chronic health challenges, disability, retirement, or similar permanent circumstances:

> **Regional / purchasing-power pricing requests** (customer says the price is unaffordable in their country/currency — e.g. India): treat as an ongoing need under this forever ladder; there is no separate regional-pricing program. The resolution offer is **50% off annual (forever)**. Escalate to a *Need-Based Complimentary Subscription* **only if the customer has already declined 50% off forever** (confirmed 2026-07-20).

1. **First offer: 40% off annual (forever).** Send the 40% off annual FOREVER link from account lookup.
2. **If customer responds that 40% forever isn't enough:** Escalate to **50% off annual (forever).** Send the 50% off annual FOREVER link.
3. **If 50% forever still isn't enough:** If the customer expresses genuine inability to pay even at 50% off, pivot to *Need-Based Complimentary Subscriptions*.

**Key behavioral rules:**

- **Offer one tier at a time.** Never present multiple discount levels in a single reply. Send the first offer, wait for the customer's response, then escalate if needed.
- **The intro and forever ladders are separate tracks.** A customer typically enters one or the other based on their stated situation. They don't climb the intro ladder and then switch to the forever ladder — if they express ongoing need, start them on the forever ladder directly.
- **These discounts are not marketed.** We never proactively advertise them. They're offered only when the customer writes in and asks.

## Variations

- **Customer asks for a discount on monthly:** We do not discount monthly. This is not a discount-request scenario for this policy — it's a *Monthly Discount Requests* scenario. Route there (counter-offer is 50% off annual).
- **Customer is currently subscribed and asking for a discount:** This policy doesn't apply. Route to *Renewal Discount Requests* (annual subscribers) or *Monthly Discount Requests* (monthly subscribers).
- **Customer has no account at all** (`Account Found: false`): Same offer ladder applies. Send them the appropriate discount link — they'll create an account through the link.
- **Customer is a lapsed subscriber** (account exists, `Subscribed: false`): Same offer ladder. No difference in handling vs. never-subscribed.
- **Customer mentions both a willingness to pay and financial hardship** (e.g., "I'd love to resubscribe but I'm on a fixed income"): Start on the forever ladder. The key signal is **willingness to pay at a reduced rate**. If at any point they indicate even the forever discounts aren't feasible, pivot to *Need-Based Complimentary Subscriptions*.
- **Customer asks for a specific percentage we don't offer** (e.g., 25%, 75%): Offer the closest available tier. If they ask for less than 40%, offer 40%. If they ask for more than 50%, 50% is the ceiling for discounts — beyond that is the complimentary path.

## Edge Cases & Exceptions

- **Customer's language is ambiguous between "I want a deal" and "I can't afford it":** Default to the discount ladder (this policy). The distinguishing signal is **willingness to pay**. "Too expensive" + "is there a deal" = discount request. "I can't afford it" / "is there a free option" / "I'm struggling financially" = *Need-Based Complimentary Subscriptions*.
- **Customer asks for a "student discount" or "senior discount" specifically:** We don't have named discount tiers. Offer the standard 40% intro (or 40% forever if they indicate ongoing need like being on a fixed income). Frame it as "we'd love to offer you a discount" without calling it a student/senior program.
- **Customer was previously on a complimentary subscription and now asks for a discount:** They can receive a discount offer. The fact that they previously had a comp subscription and are now expressing willingness to pay is a positive signal — offer the appropriate ladder.
- **Customer asks for a discount on behalf of someone else** (e.g., a family member): Fine — send the link. The link is not account-specific; whoever uses it gets the discount applied to their account.

# Action Classification

## No Action Required (reply only)

**All standard discount offers under this policy are reply-only / auto-sendable.** The customer is not currently subscribed, so there is no existing subscription to modify. The AI sends the appropriate pre-built Stripe discount link from the Account Lookup Data Model. The customer completes the purchase themselves through the link.

This applies to:

- 40% off annual intro offer
- 50% off annual intro offer
- 40% off annual forever offer
- 50% off annual forever offer
- All of the above regardless of whether the customer has an account or not

## Human Action Required

No human action is typically required for this policy. The entire flow is link-based.

**Exception:** If the conversation pivots to *Need-Based Complimentary Subscriptions*, that policy's action classification takes over (complimentary grants require human review).

## Do Not Auto-Send Conditions

Even though this is reply-only, flag for human review before sending if any of the following are true:

- Customer's language is ambiguous between discount request and hardship/inability to pay — human should assess whether to offer a discount or pivot to complimentary
- Customer is escalating past 50% off and becoming frustrated — human should manage the conversation and determine if complimentary is appropriate
- Customer mentions a specific circumstance that doesn't cleanly fit the intro or forever ladder (e.g., temporary disability, short-term job loss) — judgment call on which ladder applies
- Customer has a history of frequent discount or complimentary requests visible in ticket history — human should assess the pattern

## Escalation Triggers

- **Two or more subscribed accounts found across any email in the ticket** → escalate immediately to support leadership. Do not send any reply.

- **Customer pushes past 50% off forever and is not satisfied** → senior support to assess whether complimentary is warranted or whether to hold the line.
- **Customer's situation is borderline between discount and complimentary** → senior support if the handling agent is unsure.

# Confidence Notes

- **High confidence areas:** The two-ladder structure (intro vs. forever). The 40%/50% tiers. One offer at a time, escalated on response. Annual only — no monthly discounts. Unsubscribed only — subscribed users route elsewhere. Links from Account Lookup Data Model are the delivery mechanism. All offers are reply-only (no admin action).
- **Judgment call areas:** Distinguishing "willingness to pay at a discount" (this policy) from "inability to pay" (*Need-Based Complimentary Subscriptions*). The line is the customer's expressed intent, but it can be ambiguous. Default is to start here (discount) and pivot to complimentary only if the customer signals they can't pay at all.
- **Gaps:**
    - No defined limit on how many times a customer can request and receive discount links over time (e.g., they ask every few months, never subscribe, ask again).
    - Whether there's any consideration of why the customer's previous subscription lapsed (e.g., they churned after a refund dispute vs. simply let it expire) — currently no difference in handling.
    - Whether the forever discount links work for new accounts the same as existing accounts (assumed yes, but not explicitly confirmed).

# Related Policies

- *Subscription & Billing Overview*
- *Renewal Discount Requests*
- *Monthly Discount Requests*
- *Need-Based Complimentary Subscriptions*
- *Account Lookup Data Model*