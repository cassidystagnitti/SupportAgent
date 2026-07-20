# Refund policy
# Summary

Defines refund eligibility windows for Stripe and Google Play subscriptions, and the support actions required. Apple refunds are out of scope — Apple owns their refund process entirely.

# Trigger Conditions

- **Ticket signals:** customer requests a refund, mentions being charged unexpectedly, mentions a renewal they didn't want, mentions wanting their money back, asks about getting a refund
- **Account signals:** recent charge on Stripe, Apple, or Google Play (within or near refund windows), active or recently-canceled subscription
- **Keywords / phrases:** "refund," "money back," "charge back," "didn't mean to renew," "can I get a refund," "unexpected charge," "return my money," "reverse the charge"

# Required Context

- [ ]  Payment provider (Stripe, Google Play, or Apple)
- [ ]  Plan type (annual or monthly)
- [ ]  Date of the charge they want refunded
- [ ]  Whether the charge was an initial purchase or a renewal (rule is the same, but useful for response framing)
- [ ]  Number of days elapsed since the charge
- [ ]  If the charge can't be found on our side and the customer mentions "Ten Percent Happier," Dan Harris, or the podcast: confirm the charge is actually ours — run the `bert-disambiguate-10-percent` skill (see *Happier vs. 10% Happier*) before declining or redirecting.

# Policy / Correct Response

## Standard Case

**Refund eligibility is governed solely by a time window measured from the charge date.** There are no other gates — no usage-based disqualifiers, no per-customer refund caps, no penalty for prior refunds.

**We do not offer pro-rated refunds under any circumstances.** If a customer cancels mid-period, we do not refund the unused portion of their subscription. They keep access until the period ends; that's it. This is distinct from *partial refunds* in the renewal-discount sense (refunding the difference between full price and a discounted rate while the customer keeps their full subscription period) — those *are* available in specific scenarios. See *Renewal Discount Requests* Path 2.

### Annual subscription

- **Emailed support within 30 days of the charge:** Full refund. Applies to both initial purchase and renewals.
- **Emailed support after 30 days:** No refund. Cancel at next renewal only. **No proration, ever.**

### Monthly subscription

- **Emailed within 24 hours of the charge:** Full refund. Applies to both initial purchase and renewals.
- **Emailed after 24 hours:** No refund. Cancel at next renewal only. **No proration, ever.**

### Provider handling

- **Stripe:** Support processes the refund directly.
- **Google Play:** Support processes the refund through Google's flow. Customer may also self-serve via Google Play.
- **Apple:** Support cannot refund. Redirect to Apple's `reportaproblem` flow.

## Variations

- **If customer is on Apple:** Always redirect to Apple. Do not promise or imply we can refund. Provide Apple's refund documentation link.
- **If customer is past the window and is asking for a refund due to renewal-discount:** They may be eligible for a *retroactive renewal discount* (40% partial refund) — see *Renewal Discount Requests*. The refund window rule above does NOT block this; the renewal-discount policy is a separate path.
- **If customer is past the window and wants a plan switch:** No refund, but they can be queued for a switch at next renewal — see *Plan Switching*.

## Edge Cases & Exceptions

- **Non-USD original charge (Stripe):** Refund the full original USD amount. Customer may see a small FX discrepancy. Disclose only if they raise it.
- **Customer says "I was charged twice" / duplicate charges:** This is not a standard refund request — investigate before refunding. Could be a billing error needing engineering visibility. Treat as needing human review until verified.
- **Customer says they were overcharged / charged full price when they had a discount:** Before agreeing or refunding a "difference," verify what they were actually billed. Read the `Last Invoice Amount Charged` / `Last Invoice Coupon Applied` fields in the Stripe block — **not** `Base Plan` / `Active Coupon` / `Effective Price` / `Next Renewal Amount`, which are current/forward-looking and can miss a one-time coupon that already discounted the last charge. If the last invoice shows the discount was already applied, there is nothing to refund. See *Account Lookup Data Model → Stripe Enrichment: Last-Invoice (Actual Charge) Fields* and *Renewal Discount Requests* Path 2.
- **Customer requests pro-rated refund** ("I only used 3 months of my annual, can I get 9 months back?"): No. We do not pro-rate. The standard refund-window rule is full refund within window, nothing after. Politely decline and offer to cancel at next renewal.
- **Customer requests partial refund within window for a different reason** (e.g., "I want to keep my subscription but get some money back"): Outside the standard refund flow. The only sanctioned partial-refund scenario is the retroactive renewal-discount path — see *Renewal Discount Requests* Path 2. If their request doesn't fit that, decline.
- **Customer's charge is exactly at the window boundary** (day 30 for annual, hour 24 for monthly): Be generous — honor the refund. If the timing is meaningfully past (day 31+, hour 25+), the rule is firm.
- **Customer chargeback already initiated with their bank:** Don't process a refund on top of an active chargeback. Accept the “dispute” within stripe or escalate to senior support.

# Action Classification

## No Action Required (reply only)

- **Apple refund requests:** reply-only. Redirect to Apple's documentation. No action available to us.
- **Customer past refund window** asking about refund eligibility (and not eligible for renewal-discount path): reply-only with the policy and offer to cancel at next renewal.

## Human Action Required

- **Action:** Process refund in Stripe or Google Play.
- **When:** Customer is within window (30 days annual / 24 hours monthly) and on Stripe or Google Play.
- **Why AI can't do it:** Issuing refunds is an irreversible billing action requiring provider admin access and human verification of charge details.

## Do Not Auto-Send Conditions

Even when the reply is "reply-only" (no admin action needed), flag for human review before sending if any of the following are true:

- Customer's charge is at or near the refund window boundary (day 28-30 for annual, hour 22-24 for monthly) — timing judgment required
- Customer mentions a chargeback or dispute alongside the refund request — tone and legal sensitivity require human eyes
- Customer's refund request is combined with a complaint about app quality, data loss, or service failure — may warrant a goodwill exception beyond standard policy
- Customer's account shows multiple recent refunds or a pattern of refund requests — may indicate a gaming pattern that standard policy doesn't address
- The ticket involves a non-USD Stripe charge and the customer has raised a discrepancy concern — FX explanation requires careful framing

## Escalation Triggers

- **Two or more subscribed accounts found across any email in the ticket** → escalate immediately to support leadership. Do not send any reply.

- **Suspected duplicate charges or billing system errors** → senior support / engineering for investigation before any refund.
- **Refund request tied to a complaint about app behavior, data loss, or service failure** → senior support to assess whether goodwill / out-of-policy refund is warranted.

# Confidence Notes

- **High confidence areas:** The 30-day annual / 24-hour monthly windows. The no-proration rule. The no-disqualifier rule (window is the only gate). Apple = always redirect.
- **Judgment call areas:** Boundary timing (day 30 vs. day 31). Goodwill refunds outside policy — currently undefined, defaulting to escalation.
- **Gaps:**
    - Goodwill / out-of-policy refunds — when, if ever, do we issue these? Currently routing to escalation.
    - Duplicate charge investigation flow — needs definition.

# Saved Reply Mapping

The correct saved reply is determined by account and Stripe data — not ticket language. Work through platform → window → special circumstances.

## Platform unknown / no account found

| Condition | Saved Reply |
|---|---|
| Refund requested, no account found on ticket email | `CancelRefund PlatformUnclearRefund` |

## Apple

| Condition | Saved Reply | Notes |
|---|---|---|
| Active subscription, refund requested | `CancelRefund AppleRefund` | Standard Apple redirect — we cannot refund |
| Trial just converted, refund requested | `CancelRefund AppleRefundAfterTrial` | Warmer trial framing |
| Trial cancellation crossed with auto-enrollment | `CancelRefund AppleRefundAfterTrialEarlyAutoEnrollComplaint` | For "I canceled but was still charged" timing complaints |
| Previous trial already used; customer signed up for full sub | `CancelRefund AppleRefundPreviousTrial` | Explains no second trial; includes 40% resubscribe offer |
| Customer reports Apple already denied their refund | `CancelRefund AppleRefundDenied` | Escalates to AppleCare phone; no action from our end |

## Google Play

| Condition | Saved Reply | Notes |
|---|---|---|
| Within window, regular subscription | `CancelRefund GoogleRefund Subscription` | We process through Google Play |
| Within window, trial just converted | `CancelRefund GoogleRefundAfterTrial` | Warmer trial framing |
| Outside window | *(no saved reply — human review)* | Cancel the subscription; explain no refund; needs custom reply |

## Stripe — Within window (annual ≤30 days, monthly ≤24 hours)

| Condition | Saved Reply | Notes |
|---|---|---|
| Trial just converted to annual | `CancelRefund StripeRefundTrial` | Specifically acknowledges "free trial converted at end of trial period"; includes 40% restart offer |
| Customer intent unclear — cancel or refund? | `CancelRefund StripeCancelOrRefund` | Offers 3 options (keep / 40% discount / full refund); use when customer says "cancel" but charge is recent enough to refund |
| Clear refund intent, no discount on subscription | `CancelRefund StripeRefund NoDiscount` | Clean refund, no retention offer |
| Clear refund intent, customer missed renewal notice | `CancelRefund StripeRefund NoticeMissedNoDiscount` | Adds "sorry you missed the notice" framing; same outcome as NoDiscount |
| Clear refund intent, subscription has/had a discount | `CancelRefund StripeRefund WithDiscount` | Full refund + offer to restart at 40% |
| Has discount, customer missed renewal notice | `CancelRefund StripeRefund NoticeMissedWithDiscount` | Missed notice framing + 40% restart offer |
| Gift certificate purchase | `CancelRefund StripeRefund GiftCertificate` | For gift cert purchases only, not regular subscriptions |
| Charge already disputed with bank | `CancelRefund StripeRefund ChargeDisputed` | Accept dispute in Stripe + cancel renewal; no additional refund possible |

> **Note:** `CancelRefund StripeFullRefund` and `CancelRefund StripeRefund NoDiscount` are nearly identical in content. Likely redundant — confirm with team which to deprecate.

## Stripe — Outside window (annual >30 days, monthly >24 hours)

| Condition | Saved Reply | Notes |
|---|---|---|
| Customer explicitly requests pro-rated refund | `CancelRefund StripeRefund ProRatedRefundRequested FILLIN` | Decline clearly; fill in EXPIRATIONDATE; cancel subscription |
| Same, customer mentions Dan Harris | `CancelRefund StripeDanNoProratedRefund` | Same decline, Dan-specific warm framing |
| General refund request (not pro-rated) | *(no saved reply — human review)* | Explain policy, offer to cancel; no template currently covers this |

## Stripe — Special circumstances (any window state)

| Condition | Saved Reply | Notes |
|---|---|---|
| Refund sent but landed on expired/canceled card | `CancelRefund StripeRefund ARN1CanceledCard` | Set a follow-up reminder; explains ARN process to customer |
| ARN now available, sharing it with customer | `CancelRefund StripeRefund SentToExpiredCard FILLIN` | Fill in BANKNAME and ARNFROMSTRIPE |

## Post-refund retention path (follow-up reply, not first reply)

| Condition | Saved Reply | Notes |
|---|---|---|
| Customer accepted 40% discount offer instead of full refund | `CancelRefund StripeRefundDiscount` | Issues $40 partial refund; sent after customer confirms they want the discount |

# Related Policies

- *Subscription & Billing Overview*
- *Renewal Discount Requests* (retroactive 40% partial refund path for past-window cases)
- *Plan Switching* (refund-and-resubscribe path within window)
- *Apple/Google → Stripe Migration*