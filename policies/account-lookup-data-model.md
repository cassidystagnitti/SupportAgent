# Example Blob

This is what the account lookup data blob looks like when returned from the Happier API. The AI should expect this format when reading account data for any ticket.

**Example: Active Stripe annual subscriber, past intro discount, auto-renew on**

```
Account Found: true
Subscribed: true
Subscription Platform: Stripe
Subscription Start Date: 2024-06-15
Subscription Expiration Date: 2025-06-15
Auto Renew Status: true
Trial Status: (trial fields empty on subscription)
```

**Example: Active Apple monthly subscriber in trial**

```
Account Found: true
Subscribed: true
Subscription Platform: Apple
Subscription Start Date: 2026-04-28
Subscription Expiration Date: 2026-05-05
Auto Renew Status: true
Trial Status: in_trial — 7-day free trial active
```

**Example: Expired Google subscriber, auto-renew off (canceled)**

```
Account Found: true
Subscribed: false
Subscription Platform: null
Subscription Start Date: 2024-01-10
Subscription Expiration Date: 2025-01-10
Auto Renew Status: false
Trial Status: (trial fields empty on subscription)
```

**Example: Active Stripe annual subscriber, auto-renew off (canceled but still in paid period)**

```
Account Found: true
Subscribed: true
Subscription Platform: Stripe
Subscription Start Date: 2026-01-09
Subscription Expiration Date: 2027-01-09
Auto Renew Status: false
Trial Status: (trial fields empty on subscription)
```

> Note: `Subscribed: true` + `Auto Renew Status: false` is a normal, consistent state — it means the customer is currently in their paid period and has full access, but their subscription will not auto-renew when it expires. There is no data discrepancy here.

**Example: Organizational subscription**

```
Account Found: true
Subscribed: true
Subscription Platform: Org: "Acme Corp"
Subscription Start Date: 2025-03-01
Subscription Expiration Date: 2026-03-01
Auto Renew Status: true
Trial Status: (trial fields empty on subscription)
```

**Example: No account found**

```
Account Found: false
Subscribed: false
Subscription Platform: null
Subscription Start Date:
Subscription Expiration Date:
Auto Renew Status: false
Trial Status: (no account)
```

---

# Summary

Reference doc for the account lookup data blob returned by the Happier API. This is the canonical source of customer state for the AI — every policy that depends on "is the customer subscribed," "what platform are they on," or "are they in trial" should reference these fields. **`Subscription Platform` is the primary signal for routing migration vs. modify-on-our-end action classification.**

# Trigger Conditions

This doc is reference material, not a ticket-resolution policy. It's pulled as supporting context whenever the AI needs to interpret account data to apply a policy.

- **Ticket signals:** any ticket where account data is needed to determine the correct response
- **Account signals:** N/A — this doc defines what account signals *are*
- **Keywords / phrases:** N/A — this doc is always retrieved as context, not matched by keyword

# Lookup Scope

**The account lookup runs against every email address in the ticket — not just the Help Scout contact email.**

Before any policy is applied, the pipeline:
1. Looks up the primary contact email from the Help Scout conversation
2. Extracts any additional email addresses mentioned anywhere in the ticket body
3. Runs a separate account lookup for each unique email found
4. Returns all results as a combined context block

This means the AI receives account data for every email the customer mentioned, not just the one they wrote in from. The combined block is labelled by email so the AI can reason about which account is which.

## Escalation Triggers

- **Two or more subscribed accounts found across any email in the ticket** → escalate immediately to support leadership. Do not send any reply. The pipeline sets `needs_action: true` and `auto_sendable: false` automatically when this condition is detected.

# Data Fields

## Account Found

`true` if user record exists; `false` if no user, API error, or missing token.

**Usage:** If `false`, the customer may have a different email, no account, or there may be a system error. Do not apply any subscription-specific policy without a found account.

## Subscribed

`true` if `subscription_state` (lowercased) is `active` or `subscribed`, OR if the effective expiration date is in the future.

**Effective expiration date logic:** The primary subscription's `expiration_date` is used if present; otherwise falls back to the user-level `subscription_expiration_date`. The subscription-level date wins when present, even if the user-level date is later.

**Usage:** Primary gate for whether the customer currently has access.

## Subscription Platform

**This is the most important field for action classification across all policy docs.**

Derived as follows:

- If **not subscribed:** `null`
- If subscribed and `organization_names` has any non-empty name(s): `Org: "Name1, Name2"` — this is an organizational/enterprise subscription.
- If subscribed (no org): normalized from `sub.source` → one of: **Apple**, **Google**, **Stripe**, or **"{Source} (other)"**
- Fallback heuristics (when `sub.source` is unavailable): uses `subscription_state`, `content_codes`, `organization_names` text for **Gift/Promo/Comp** detection, else **Other**.

**Usage for action classification:**

- **Stripe** → we can modify the subscription on our end (apply coupons, refund, cancel, retry charges, etc.). Human action required.
- **Apple** → we cannot take any action. Reply-only: send Apple documentation links + any relevant Stripe links if migrating.
- **Google** → we can cancel and refund. We cannot apply discounts or change plans. For those, migrate to Stripe.
- **Customer is on Apple or Google AND is not an existing Stripe account holder** → migration path is **reply-only / auto-sendable**. We send cancellation instructions for their current provider + the appropriate pre-built Stripe discount link. No admin action on our end.
- **Customer has a past Stripe subscription but is currently on Apple/Google** → still send the Stripe link (we want them to re-enter current card info). This is the same as a new-to-Stripe migration — **reply-only**.

## Subscription Start Date

`sub.start_date` if subscription exists, else `user.subscription_start_date`; else empty.

**Usage:** Useful for calculating how long the customer has been subscribed, whether they're in a trial period, or whether intro-discount timing applies.

## Subscription Expiration Date

`sub.expiration_date` if subscription exists, else `user.subscription_expiration_date`; else empty.

**Usage:** Determines when current access ends. Key for pre-renewal requests ("my renewal is coming up") and for calculating refund window eligibility (days since last charge ≈ days until expiration minus subscription length).

## Auto Renew Status

`true` / `false` derived from `sub.auto_renew_status`. Empty if unknown or no subscription. Hard-coded `false` on error/no-account paths.

**Usage:** If `false`, the customer has already turned off auto-renewal — their subscription will expire at the expiration date. If `true`, a charge will be attempted at expiration. Key for: renewal-discount timing, dunning scenarios, cancellation requests ("I already canceled" vs. "I want to cancel").

## Trial Status

Format: `{trial_status} — {trial_status_description}` (trimmed).

Variants:

- If subscription exists but trial fields are empty: `(trial fields empty on subscription)`
- If no subscription: `(no subscription rows; user subscription_state='…')`
- If API error: `(Maven API error: …)`
- If no user: `(no account)`

**Usage:** Determines whether customer is currently in their 7-day free trial. See *Free Trial Policy* for handling.

# Stripe Enrichment: Last-Invoice (Actual Charge) Fields

For **Stripe** subscribers, the Stripe enrichment block includes two kinds of data, and it is critical not to confuse them:

**Current / forward-looking fields** (describe the subscription *as configured now* and what it *will* do next renewal):

- `Base Plan` — the list/full price of the plan.
- `Active Coupon` — a coupon attached to the subscription *going forward*. A one-time coupon that has already been applied and consumed on a past invoice does **not** appear here.
- `Effective Price` — base price minus any *currently active* coupon.
- `Next Renewal Amount` — the amount Stripe will charge at the *upcoming* renewal.

**Historical fields** (describe what was **actually charged** on the most recent paid invoice):

- `Last Charge Date` — when the most recent paid invoice was charged.
- `Last Invoice Amount Charged` — the actual dollar amount that hit the customer's card on that invoice.
- `Last Invoice Coupon Applied` — whether a discount was applied to that specific invoice (e.g. `40% off — $40.00 off $99.99 list price`), or `None — paid full list price`.

**Usage — this is the rule that prevents wrong refund decisions:** To determine what a customer was actually billed on a past renewal, read the **Last Invoice** fields. **Never infer a past charge from `Base Plan`, `Active Coupon`, `Effective Price`, or `Next Renewal Amount`** — those are current/forward-looking and will read as "full price / no coupon" even when the last renewal was in fact discounted by a one-time coupon that has since fallen off the active-coupon field.

> **Regression this closes (HS #3377107792):** an agent concluded a customer was charged full price (based on `Active Coupon: None` + `Effective Price: $99.99`) and drafted a $40 "difference" refund — but the last invoice had already renewed at 40% off via a one-time coupon. With the Last Invoice fields present, that renewal now reads `Last Invoice Amount Charged: $59.99` / `Last Invoice Coupon Applied: 40% off`, and no refund is warranted. Before issuing any "difference" or retroactive refund, confirm the discount from `Last Invoice Coupon Applied`.
>
> If the Last Invoice fields are absent for a Stripe subscriber (older data, or the fetch failed), do not assume the last charge amount — check Stripe's invoice history directly before concluding a customer was over- or under-charged.

# Action Classification Decision Tree

This is the universal decision tree that all policy docs reference for provider-based routing:

```
1. Read Subscription Platform from account lookup
2. IF platform = Apple or Google:
   a. Can we accomplish what the customer needs on their current provider?
      - Cancellation on Google → YES, human action
      - Refund on Google → YES, human action
      - Anything on Apple → NO
      - Discount, plan change, ongoing arrangement on Google → NO
   b. IF NO → Migration path:
      - Send cancellation/expiry instructions for current provider
      - Send appropriate pre-built Stripe link
      - This is REPLY-ONLY / AUTO-SENDABLE (no admin action on our end)
3. IF platform = Stripe:
   - We modify on our end → HUMAN ACTION REQUIRED
4. IF platform = Org:
   - Organizational subscription → likely needs escalation; org billing is different
5. IF platform = Other / Gift / Promo / Comp:
   - Non-standard → needs human review to understand the account setup
```

# Standardized Stripe Links

These are the links the AI sends when migrating Apple/Google customers to Stripe or when offering discounts to unsubscribed users:

- 40% off annual INTRO: https://my.meditatehappier.com/start/sign_in?coupon=9UdSyyhB&plan=com_10percenthappier_subscription-1year-5999_intro-none_support-discount-40-ONCE
- 50% off annual INTRO: https://my.meditatehappier.com/start/sign_in?coupon=i5ikFpfC&plan=com_10percenthappier_subscription-1year-4999_intro-none_support-discount-50-ONCE
- 40% off annual FOREVER: https://my.meditatehappier.com/start/sign_in?coupon=rSPX5PeI&plan=com_10percenthappier_subscription-1year-5999_intro-none_support-discount-40
- 50% off annual FOREVER: https://my.meditatehappier.com/start/register?coupon=sYzBWBEn&plan=com_10percenthappier_subscription-1year-4999_intro-none_support-discount-50
- Standard annual ($99.99): https://my.meditatehappier.com/start/new?plan=com.10percenthappier.subscription_1year_9999.intro_7day_free
- Standard monthly ($14.99): https://my.meditatehappier.com/start/sign_in?plan=com.10percenthappier.subscription_1month_1499.intro_none
- Complimentary annual: https://my.meditatehappier.com/redeem?promo_code=NEEDBASED12MONTHS
- Other links as applicable: `[PASTE LINKS]`

**Link formatting rule (applies to EVERY reply that includes any of these links):** Always present a link as a hyperlink with short, descriptive anchor text — **never paste the raw URL into the reply.** Use HTML: `<a href="URL">descriptive text</a>`. The anchor text describes the offer, not the address. Examples:

| Link | Anchor text to use |
|---|---|
| 40% off annual INTRO | `40% off your first year` |
| 50% off annual INTRO | `50% off your first year` |
| 40% off annual FOREVER | `40% off, every year` |
| 50% off annual FOREVER | `50% off, every year` |
| Standard annual ($99.99) | `start your annual subscription` |
| Standard monthly ($14.99) | `start your monthly subscription` |
| Complimentary annual | `claim your complimentary year` |

This keeps replies clean and stops customers from seeing (or distrusting) long coupon URLs. The **same rule applies to the gift links in `gift-subscriptions.md`** (e.g. `<a href="...">40% off an annual gift</a>`).

# Confidence Notes

- **High confidence areas:** The field definitions and derivation logic (directly from the API spec). The action-classification decision tree (confirmed by support lead). Past-Stripe-users get the link, not admin modification (they need to re-enter card info).
- **Judgment call areas:** Org subscriptions — routing is unclear; flagged for escalation by default.
- **Gaps:**
    - Gift/Promo/Comp heuristic details — what exactly triggers these classifications and how should the AI handle each?
    - Whether `Other` platform ever appears in practice and what it means for action classification.
    - How to handle cases where `Account Found` is `false` but the customer clearly has an account (email mismatch, etc.).

# Related Policies

- *Subscription & Billing Overview*
- *Apple/Google → Stripe Migration*
- *Refund Policy*
- *Failed Payment / Dunning*
- *All other policy docs* (this is a universal reference)

## Draft HTML Formatting — No Stray Quote Wrapping (added 2026-07-22)

When calling `update_draft`, the `html` value must be clean, raw HTML paragraphs only (e.g. `<p>Hi Francisco,</p>`). Never wrap the entire value in an extra outer pair of quotation marks, and never escape the internal quotes (e.g. `\"40% off your first year\"`) as if the HTML itself needed JSON-style escaping. Standard double quotes inside HTML attributes (e.g. `<a href="...">`) are correct and expected — the bug is adding an *extra* layer of quoting around the whole string. This has caused literal stray `"` and `\"` characters to render inside the Help Scout draft editor. Always pass the HTML directly, with no enclosing or escaped quotes beyond normal attribute quoting.


