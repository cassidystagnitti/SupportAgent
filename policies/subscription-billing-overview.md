# Subscription & billing overview
# Summary

Foundational reference for our subscription model, pricing, payment providers, and what support can and cannot do for each provider. This doc establishes baseline facts that other policies reference; it does not by itself resolve any specific ticket type.

# Trigger Conditions

This doc is rarely the sole match for a ticket — it's pulled as supporting context whenever a ticket involves subscription status, billing, payment method, or cancellation/refund mechanics.

- **Ticket signals:** any mention of subscription, billing, payment, renewal, cancellation, refund, plan change, or "how do I…" questions about account management
- **Account signals:** customer has (or recently had) an active subscription on any provider
- **Keywords / phrases:** "subscription," "renew," "renewal," "cancel," "refund," "charge," "billed," "Apple," "Google Play," "credit card," "annual," "monthly," "auto-renew"

# Required Context

Before applying provider-specific guidance, the AI must determine:

- [ ]  Which payment provider the customer is on: **Stripe**, **Apple**, **Google Play, or Free(complimentary)**
- [ ]  Plan type: **annual** or **monthly**
- [ ]  Whether the subscription is currently active, canceled, expired, or in trial
- [ ]  Whether the customer is on an introductory/discounted rate or standard pricing

# Policy / Correct Response

## Standard Case

### Plans and pricing

- Primary offering: **annual subscription at $99.99 USD/year** (standard price).
- Secondary offering: **monthly subscription at $14.99 USD/month**.
- **Introductory discounts:**
    - Standard intro offer: **40% off year 1** of the annual plan.
    - Occasionally: **50% off year 1** (rarer).
    - Very rarely: BOGO / buy-1-get-1-free promos. Not offered by support, only in marketing.
    - **When a customer references "the discount" without specifics, assume 40% off.**
    - Discounts apply to **annual plans only** and are issued through **Stripe only**. Apple and Google have no mechanism for us to apply discounts on their platforms.
- Renewals revert to **standard $99.99/year** unless a renewal-discount policy applies (see *Renewal Discount Requests*).
- **No discounts are offered on monthly subscriptions.** Counter-offer is 50% off annual; see *Monthly Discount Requests*.

### What a subscription includes (product scope)

- A subscription unlocks **full, ad-free access to the Happier Meditation in-app library** — guided meditations, courses, the Getting Started course, the Dalai Lama's Guide to Happiness, and the rest of the app content.
- **Happier Meditation is a separate product from 10% Happier and from Dan Harris's podcast.** A subscription does **not** include the podcast (ad-free or otherwise), and the app should not be described as "formerly 10% Happier" or as bundling Dan Harris podcast content. If a customer asks whether their subscription covers the podcast or Dan Harris content, the answer is **no — that is a different product.**
- When a customer writes in believing they subscribed to 10% Happier, redirect them (we are not affiliated); see the `10%HappierSub` row in *Cancellation Policy*. If it's unclear which product they actually subscribed to (e.g., they wrote "Ten Percent Happier", mention Dan Harris or the podcast, or no account matches their email), run the `bert-disambiguate-10-percent` skill before answering — see *Happier vs. 10% Happier*.
- **Sharon Salzberg series with Dan Harris (current):** Dan Harris (our former partner) is currently running a series with Sharon Salzberg. **It is not on the Happier Meditation app and is not coming to it.** Customers have written in confused, expecting to find it here. If a customer asks about the new Sharon Salzberg / Dan Harris series, do **not** imply it is or will be available on Happier — point them exclusively to Dan Harris's **10% Happier** side, which is where that series lives. (His app/platform names change; run `bert-disambiguate-10-percent` to confirm the current name and channel before citing one — and never write the old spelled-out brand name in a reply.)

### Free trial

- **7-day free trial**, **annual plan only**, available on all providers.
- **Payment method required** at trial start; auto-converts to paid annual subscription at trial end.
- Customer may cancel during trial without being charged. Self-serve or via support (Apple = external only, as always).
- See *Free Trial Policy* for full handling.

### Currency

- All Stripe pricing is **listed and charged in USD**. Customer's bank handles any FX conversion at time of purchase.
- **Apple and Google manage their own regional pricing and currency** — we have no visibility or control over their displayed prices.
- Refund FX note: when refunding a non-USD Stripe charge, the customer may see a small discrepancy due to FX movement between charge and refund. **We disclose this only if the customer raises it.**

### Payment providers — capability matrix

| Provider | Cancellation by support? | Refund by support? | Card/payment update by support? | Discount application by support? | Customer self-service? |
| --- | --- | --- | --- | --- | --- |
| **Stripe** | Yes | Yes | Yes (or in-app) | Yes (coupon code) | Yes — in-app: cancel, update card, toggle auto-renew |
| **Google Play** | Yes | Yes | No | No | Yes — via Google Play subscription management |
| **Apple** | **No** | **No** | **No** | **No** | Yes — must go through Apple |

### Apple subscriptions — important constraint

We have **no ability** to cancel, refund, modify, or discount Apple subscriptions on the customer's behalf. All such requests must be redirected to Apple. Standard practice: reference Apple's subscription management and refund documentation in the reply.

### Google Play subscriptions

We **can** cancel and refund Google Play subscriptions via support. Customers can also self-serve via Google Play. **We cannot apply discounts or change plans on Google's side** — for those, see *Apple/Google → Stripe Migration*.

### Stripe subscriptions

Customers can self-serve cancellations, card updates, and auto-renew toggles via in-app settings. **Refunds, plan changes, and discounts require writing in to support** — no self-service path exists for those.

## Variations

- **If customer is on Apple:** Redirect to Apple for any cancellation, refund, payment method change, plan change, or discount. Do not promise action we cannot take.
- **If customer is on Google Play:** Either process cancellation/refund via support or point them to Google Play self-service. For plan changes or discounts, redirect to *Apple/Google → Stripe Migration*.
- **If customer is on Stripe and asking how to cancel / update card / turn back on auto-renew:** Point them to in-app settings.
- **If customer is on Stripe and asking for a refund, discount, or plan change:** Support handles end-to-end.

## Edge Cases & Exceptions

- **Customer doesn't know which provider they're on** → Identify by checking account data; if undeterminable, ask the customer how they originally subscribed (App Store / Google Play / website) before giving provider-specific instructions. Refer to *Account Identification*
- **Customer mentions a discount % we don't recognize** (e.g., 25%, 75%) → Don't assume; ask or check their billing record. Default assumption "they mean 40%" applies only when no specific % is given.

# Action Classification

This doc is reference material, not a ticket-resolution policy. Action classification belongs in the specific policy docs that build on this one.

## No Action Required (reply only)

- Purely informational questions about pricing, plan options, or how to self-serve on Stripe/Google Play.
- Redirecting Apple subscribers to Apple's documentation (we have no action to take regardless).
- **Migrating Apple/Google customers to Stripe** when they are not current active Stripe subscribers: send cancellation/expiry instructions for their current provider + the appropriate pre-built Stripe discount link. No admin action on our end. Past Stripe users also get the link (they need to re-enter current card info). See *Apple/Google → Stripe Migration* and *Account Lookup Data Model* for details and link references.

## Human Action Required

- Any actual billing change, cancellation, refund, plan switch, or discount application on an **existing active Stripe subscription** requires support action. Defer to specific policy docs for whether/when these are auto-sendable vs. human-required.
- Cancellations and refunds on **Google Play** are support actions (we have admin access).
- Apple: never requires human action on our end (we cannot act on their platform).

## Escalation Triggers

- **Two or more subscribed accounts found across any email in the ticket** → escalate immediately to support leadership. Do not send any reply.
- **Teams / org seat-reduction** (cut seats on a Teams Annual org plan, keep only the billing owner's membership, Stripe quantity change) → always escalate to a human. Do not draft. Do not cancel the org plan or change quantity. See *Escalation Policy*.

- Defer to specific policy docs (refunds, chargebacks, etc.) for escalation rules.

# Confidence Notes

- **High confidence areas:** Pricing ($99.99 annual / $14.99 monthly), no-discount-on-monthly rule, Apple's hard constraint that we cannot act on their subscriptions, the three supported providers, USD-only Stripe pricing, 7-day annual-only trial.
- **Judgment call areas:** When a Google Play customer asks about cancellation, whether to process it ourselves vs. redirect to Google Play self-service. Both are valid.
- **Gaps:** None currently flagged. Refund windows, dunning, plan switching, discounts, and trials are all covered in their dedicated policy docs.

# Related Policies

- *Refund Policy*
- *Free Trial Policy*
- *Failed Payment / Dunning*
- *Account Lookup Data Model*
- *Plan Switching*
- *Apple/Google → Stripe Migration*
- *Monthly Discount Requests*
- *Renewal Discount Requests*
- *Need-Based Complimentary Subscriptions*

### Weekly newsletter / blog

The weekly newsletter (sometimes referred to as "the blog") is **free content available to anyone on our website** — it is not gated behind a subscription and is not a subscriber perk. If a customer asks whether their subscription includes the weekly newsletter/blog, clarify that it's free to everyone regardless of subscription status.
