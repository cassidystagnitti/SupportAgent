# Renewal discount requests
# Summary

When an annual customer's intro discount expires and they're surprised by the full-price renewal, support can apply a **40% off discount** through one of three paths depending on timing: pre-renewal (apply for upcoming renewal), retroactive within 30 days (40% partial refund), or post-renewal past 30 days (apply 40% off on the next renewal). In specific cases — explicit ongoing-need request, fixed income, or a 3+ year pattern of requesting renewal discounts — we apply a **forever 40% discount** on every renewal.

This policy applies only to **Stripe** (and to **Apple/Google customers willing to migrate to Stripe** — see *Apple/Google → Stripe Migration*).

# Trigger Conditions

- **Ticket signals:** customer mentions their renewal coming up at full price, just renewed at higher rate than before, intro discount ended, asks for the discount again, says price went up
- **Account signals:** annual subscriber whose first-year intro discount has expired or is about to expire; renewal at standard $99.99 either upcoming or recently processed
- **Keywords / phrases:** "renewal," "renewing soon," "price went up," "discount expired," "can I keep the discount," "any way to lower," "still get the discount," "renew at a discount," "I had a discount before"

# Required Context

- [ ]  Determine provider(Apple,Google,Stripe,Comp)
- [ ]  Confirm plan is annual (this policy doesn't apply to monthly)
- [ ]  Date of upcoming renewal OR date of recent renewal charge
- [ ]  Days elapsed since renewal charge (determines which path applies)
- [ ]  Whether customer has previously asked for a renewal discount (and how many times — relevant for forever-discount qualification)
- [ ]  Whether customer mentions financial need / fixed income / ongoing hardship

# Policy / Correct Response

## Standard Case

**Three-path framework based on timing:**

### Path 1: Pre-renewal request

**Trigger:** Customer writes in *before* their next annual renewal, asking about the upcoming full-price charge.

**Action:** Apply a **40% off coupon** to their Stripe subscription so the upcoming renewal charges at the discounted rate.

### Path 2: Retroactive within 30 days of renewal

**Trigger:** Customer renewed at full price recently (within 30 days) and is asking for help / refund.

**Action:** Issue a **40% partial refund** of the renewal charge. The customer keeps their subscription for the full renewal period; we refund 40% of what they paid, effectively retroactively applying the discounted rate.

> **Before issuing any "difference" or partial refund, confirm what they were ACTUALLY charged on the last renewal.** Read the `Last Invoice Amount Charged` / `Last Invoice Coupon Applied` fields in the Stripe block — **not** `Base Plan`, `Active Coupon`, `Effective Price`, or `Next Renewal Amount`, which are current/forward-looking and read as "full price / no coupon" even when a one-time coupon already discounted the last charge. If `Last Invoice Coupon Applied` shows the renewal already went through at 40% off, **no refund is owed** — do not tell the customer we refunded a difference that doesn't exist. See *Account Lookup Data Model → Stripe Enrichment: Last-Invoice (Actual Charge) Fields*. (HS #3377107792 was drafted with exactly this error.)

*Note: This is a partial refund (rate adjustment), not a pro-rated refund. We never pro-rate based on unused time. This path is the only sanctioned partial-refund scenario in our policy — it's a deliberate, narrow exception.*

### Path 3: Post-renewal past 30 days

**Trigger:** Customer renewed at full price more than 30 days ago and is asking for help.

**Action:** Apply a **40% off coupon** for the **next** renewal (one cycle out). No retroactive refund — the 30-day window has passed for that.

### Forever / ongoing discount

Apply a **recurring 40% off** on every future renewal if **any** of the following are true:

- Customer **explicitly requests an ongoing discount** ("can you just keep this discount on every renewal?")
- Customer mentions **fixed income, financial hardship, or non-time-bounded need** ("I'm on a fixed income," "I can only afford it at the discounted rate")
- Customer has **written in for a renewal discount 3+ years in a row** (firm threshold — pattern of recurring requests indicates ongoing need; granted automatically at year 3+)

The forever discount can also ladder: start with **40% off forever**, and if the customer indicates that's not sufficient, escalate to **50% off forever**. The 50% forever escalation is less common but available when needed.

**These discounts are not marketed.** We never proactively advertise them. They're applied only when the customer writes in and one of the trigger conditions is met.

## Variations

- **Customer is on Apple or Google annual** and asks for a renewal discount: We can't apply it on their provider. Offer *Apple/Google → Stripe Migration* — they cancel/expire on the original provider, we send a Stripe link with the 40% discount.
- **Customer is on monthly and asking for a renewal discount:** This isn't a renewal discount scenario — see *Monthly Discount Requests*. Offer 50% annual as the counter.
- **Customer was on a 50% intro discount and is now renewing:** Standard path applies (40% off on renewal). We can escalate to 50% on renewal if specifically asked for.
- **Customer is in their first year (still on intro discount) and writes in pre-renewal:** This is the typical first-renewal request. Apply 40% off for the upcoming renewal (Path 1).
- **Customer is in their second year (was on intro then 40% renewal discount) and writes in again:** Apply 40% again. Track this — they're on year 2 of asking. At year 3+, they qualify for the forever discount automatically.

## Edge Cases & Exceptions

- **Customer asks for more than 40% off** (e.g., "can I get 50% again?"): The 40% renewal discount can ladder to **50% off** if the customer pushes back or indicates that 40% isn't sufficient. This is less common but available. There are no discounts beyond 50% off.
- **Customer claims they shouldn't have been charged at all because the intro "should have been forever":** Check account info to confirm if they ever had a *forever* discount. If a charge failed and they signed back up through a different offer, they may have renewed at full price. Always honor what support offered in the past.
- **Customer's renewal happened during a Stripe failed-payment retry window** (renewed late after card issues): Treat the successful charge date as the renewal date for the 30-day retroactive refund window calculation.
- **Customer mentions hardship but not enough to clearly qualify for a complimentary subscription:** 40% renewal discount + flag for potential complimentary subscription if they push further. See *Need-Based Complimentary Subscriptions*.
- **Customer has been a multi-year subscriber but doesn't fit the 3+ years of asking pattern** (e.g., 5-year subscriber who is asking for the first time): Apply 40% via the appropriate path. If they ask again next year and the year after, year 3 of asking = forever discount.
- **Customer is on the forever discount and asks if they can get more off:** If on 40% forever, can ladder to 50% forever. If already on 50% forever and asking for more, that's the ceiling for discounts. If they raise hardship, see *Need-Based Complimentary Subscriptions*.

# Action Classification

## No Action Required (reply only)

- **Apple/Google annual customers requesting a renewal discount:** AI sends cancellation/expiry instructions for their current provider + the pre-built Stripe 40% off annual link. This is reply-only because the customer is not an existing Stripe account holder (or is a past Stripe user who needs to re-enter card info). No admin action on our end. See *Apple/Google → Stripe Migration* and *Account Lookup Data Model*.

## Human Action Required

- **Action:** Apply 40% off coupon on an **existing Stripe subscription** for upcoming renewal.
- **When:** Path 1 (pre-renewal) or Path 3 (post-renewal past 30 days, applied to next renewal). Customer is a current Stripe subscriber.
- **Why AI can't do it:** Stripe coupon application requires admin access.
- **Action:** Issue 40% partial refund on Stripe.
- **When:** Path 2 (retroactive within 30 days of renewal). Customer is a current Stripe subscriber.
- **Why AI can't do it:** Refund issuance requires Stripe admin access.
- **Action:** Configure recurring 40% off coupon on every renewal.
- **When:** Customer qualifies for forever discount (explicit request, hardship, or 3+ year pattern). Customer is a current Stripe subscriber.
- **Why AI can't do it:** Stripe subscription configuration change requires admin access.
- **Action:** Cancel/refund Google annual subscription on our end (if customer requests it as part of migration).
- **When:** Customer is on Google annual, accepts migration, and wants us to cancel the Google sub rather than self-serving.
- **Why AI can't do it:** Google admin access required.

## Do Not Auto-Send Conditions

Even when the reply is "reply-only" (no admin action needed), flag for human review before sending if any of the following are true:

- Customer asks for more than 40% off — requires judgment on whether to offer 50% or hold the line
- Customer claims the intro discount was misrepresented as ongoing/permanent — tone-sensitive, may need ticket history review to verify what was originally communicated
- Customer mentions financial hardship but it's unclear whether they qualify for complimentary vs. just the 40% renewal discount — discretionary boundary
- Customer appears to be at the 3-year threshold for the forever discount but exact history is unclear — human should verify before committing to a recurring coupon
- Customer's renewal happened during a failed-payment retry window and the charge timing is ambiguous — human should verify which date counts as the renewal for refund window purposes

## Escalation Triggers

- **Two or more subscribed accounts found across any email in the ticket** → escalate immediately to support leadership. Do not send any reply.

- **Customer requests more than 40% off** and pushes hard → senior support if churn risk.
- **Customer's situation is borderline between renewal-discount and need-based complimentary** → senior support judgment if support agent is unsure.
- **Customer claims the intro discount was misrepresented as ongoing** → senior support to review original signup.

# Confidence Notes

- **High confidence areas:** The three-path framework. The 40% rate as the standard starting point, with 50% available as an escalation. Stripe-only application. Annual-only application. The 3+ years of asking → forever discount rule (firm threshold). Forever discount qualifies on explicit ongoing-need ask OR fixed income OR 3+ year pattern. Forever discount can ladder from 40% to 50%.
- **Judgment call areas:** What counts as "financial hardship" vs. just "asking for a discount" — leaning toward applying the 40% generously since it's already a relatively low-friction offer. The harder judgment is when to pivot to complimentary instead.
- **Gaps:**
    - Whether "3+ years of asking" must be 3 *consecutive* years or 3 *total* across more years. Currently treated as consecutive.
    - How we track the pattern across years — relies on account history / past tickets being readable. If customer has switched email addresses or accounts, this is hard to verify.
    - Whether the forever discount survives a subscription gap (customer cancels and resubscribes later).

# Related Policies

- *Subscription & Billing Overview*
- *Refund Policy*
- *Apple/Google → Stripe Migration*
- *Monthly Discount Requests*
- *Discount Requests (Unsubscribed Users)*
- *Need-Based Complimentary Subscriptions*
- *Plan Switching*
