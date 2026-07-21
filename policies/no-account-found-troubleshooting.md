# No account found troubleshooting
# Summary

Covers all tickets where the email address submitted with the ticket does not match any account in the system. The goal is to locate the correct account before applying any downstream policy. This flow applies to any request type — cancellation, refund, login help, billing question — not just cancellations.

**One exception:** if the customer is on Apple and their request can be handled through Apple directly (cancellation, refund), we can provide those directions in parallel without needing to find the account first. But we still send the investigation reply to locate the account.

# Trigger Conditions

- **Ticket signals:** any request — cancellation, refund, login trouble, billing question, account access — where the contact email returns no account
- **Account signals:** `Account Found: false` on lookup by ticket email address
- **Keywords / phrases:** N/A — trigger is the account lookup result, not ticket language

> **Do not attempt to resolve the customer's underlying request until the correct account is identified.** This is a prerequisite step for all ticket types except the Apple parallel-directions exception above.
> 

# Required Context

- [ ]  `Account Found: false` confirmed on ticket email address
- [ ]  Whether a second email address is visible anywhere in the ticket body or subject line
- [ ]  What the customer's underlying request is — determines which downstream policy to apply once the account is found
- [ ]  Whether customer mentions iPhone, iPad, or App Store (→ include Sign in with Apple prompt)

# Policy / Correct Response

## Standard Case

When `Account Found: false`, the account is almost certainly registered under a different email. The most common reasons:

1. The customer has a separate email they used to sign up
2. They used **Sign in with Apple**, which creates a hidden private relay address they may not recognize
3. There was a typo in the contact email
4. They genuinely have no account (less common when writing in about a charge or active subscription)

### Step 1: Check the ticket body for a second email

Before replying, read the full ticket. Customers often mention or paste a different email. If one is visible, look it up immediately. If that account is found, proceed directly to the downstream policy — no investigation reply needed.

### Step 2: Send the standard investigation reply

If no second email is visible, send this reply. It is the same regardless of what the customer is asking for — the only goal at this stage is to locate the account.

**Standard investigation reply template:**

I'm {user.firstName} from the Support team and I'm happy to help you get connected to your subscription. I can see your email address [ADDRESS] which doesn't have a subscription on it so let's find the purchase and you'll be able to get set up.

Our accounts are registered to either an email address or Sign in with Apple address and I'm guessing you have more than one account going. Would you send some more information so we can find your subscription? Here's what'll help us:

- If you're an Apple customer, check to see if you used [Sign in with Apple](https://support.apple.com/en-us/HT210318) to create your account. Our Help Center article [Check for a Hidden Sign in with Apple Address](https://support.happierapp.com/article/314-check-for-a-hidden-sign-in-with-apple-address) has some steps to help you find that.

If you don’t have a Hidden Sign in with Apple Address, please provide the following so we can locate your account:

- A copy of the receipt if you have it.
- The date, merchant name, and amount of the charge to your bank account.
- The last 4 digits of the credit card you used to purchase the subscription.
- List other email addresses you have.

Thanks in advance for the additional information - I look forward to hearing back from you, {user.firstName}

### Step 3: Run the Stripe charge hunt (when payment details arrive)

Once the customer provides card last-4, a charge date/amount, alternate emails, or name variants, run the read-only Stripe search **before** replying — do not ask the customer for more information that a search can answer. Read-only Stripe research is pre-approved (confirmed 2026-07-20): it carries no write risk, so AI runs it autonomously as part of drafting.

The procedure (added 2026-07-20 after it fully resolved a live ticket):

1. **Charges by card:** search charges on `payment_method_details.card.last4:'<digits>'` (REST search API) and scan the results for the claimed date and amount.
2. **Customers by email:** `stripe.Customer.search(query="email:'<each candidate email>'")` for every email in the thread.
3. **Customers by name:** `name~'<each surname variant>'` — married/maiden names, spouses.
4. **Interpret decisively:**
   - **Match found** → verify it belongs to this customer (email/name lines up), then apply the downstream policy (cancellation, refund, etc.). Never confirm an action on a subscription/charge whose Stripe object you haven't actually located.
   - **No match across all searches** → the charge did not go through our Stripe. Say so plainly and ask for the two facts that resolve it: the **exact merchant descriptor** and **amount** on their card statement. Explain the likely places it lives: an Apple subscription under a different Apple ID or family sharing (`APPLE.COM/BILL`), Google Play billing (`GOOGLE*`), or a different company's app entirely (e.g. 10% Happier, which customers regularly conflate with us — see *Happier Meditation vs. 10% Happier*).
5. **Never** reply with a cancellation/refund confirmation drafted on the assumption the search will succeed.

## Variations

- **Second email found in ticket body:** Look it up before replying. If found, skip the investigation reply and apply the downstream policy directly.
- **Second email in ticket body, auto-renew already off:** Find the account on the second email, verify `Auto Renew Status: false` and expiration date is in the future. Reply confirming cancellation is already processed and access continues until expiration. Reply-only, no action needed.
- **Customer says they've never had an account but was charged:** Not a standard no-account-found case — this is a billing dispute. Treat as needing human review; investigate before replying.
- **Business/org email, customer mentions a work subscription:** May be an organizational account. Look for `Subscription Platform: Org` signals. See *Subscription & Billing Overview*.

# Action Classification

## No Action Required (reply only)

- Sending the standard investigation reply
- Confirming cancellation is already processed once account is located (Ticket 3 pattern)

## Human Action Required

- **Action:** Look up the account by Sign in with Apple relay address, or in Apple/Google billing records, when the Stripe charge hunt (Step 3) comes up empty and the merchant descriptor points at Apple or Google
- **When:** Customer has responded with identifying information and the Stripe-side search has already been run without a match
- **Why AI can't do it:** Apple App Store Connect / Google Play Console lookups require console access. (The Stripe-side search itself is NO LONGER a human action — since 2026-07-20 AI runs it read-only as Step 3.)
- **Action:** Apply the appropriate downstream policy once the account is found (cancellation, refund, login help, etc.)
- **When:** Account is successfully identified
- **Why AI can't do it:** Downstream actions require admin access; see relevant policy docs

## Do Not Auto-Send Conditions

Even when the reply is "reply-only" (no admin action needed), flag for human review before sending if any of the following are true:

- Customer says they've never had an account but was charged — this is a billing dispute, not a standard no-account case; needs investigation before any reply
- Customer mentions a business, organization, or work-provided subscription — may be an org account with different handling
- A second email was found in the ticket body and the account on it is unsubscribed or ambiguous — human should verify before sending login instructions for the wrong account
- Customer has already responded to a previous investigation reply with identifying info (receipt, last-4, relay address) — AI runs the Step 3 Stripe charge hunt and drafts from its actual findings, but the reply stays human-reviewed before send

## Escalation Triggers

- **Two investigation replies already sent without locating the account/subscription** → do NOT send a third template ask. Escalate (`escalate = true`) with a summary of everything gathered so far (emails tried, receipts/last-4 received, Step 3 results). Repeating the same request list a third time reads as a scripted loop and stalls the customer (confirmed 2026-07-21).
- **Two or more subscribed accounts found across any email in the ticket** → escalate immediately to support leadership. Do not send any reply.

- **Merchant descriptor confirms the charge is ours, but the Step 3 Stripe hunt and account lookups still can't locate it** → senior support for deeper billing investigation. (A clean Step 3 miss alone is NOT an escalation — it gets the "not in our billing, send the descriptor + amount" reply.)
- **A second account is located but is unsubscribed/clearly not the one the user is looking for →** senior support
- **Account found but identity mismatch** (wrong person's account located via shared card) → senior support
- **Customer provides identifying info other than email address (receipt, last-4)** → Escalate to senior support.
- **Account found via lookup but belongs to a different person** (e.g., shared credit card) → Escalate

# Confidence Notes

- **High confidence areas:** The standard investigation reply template and its universal use regardless of request type. The "check ticket body first" step. Sign in with Apple bullet included universally. The Apple exception (provide directions in parallel without needing account found). The Ticket 3 pattern (auto-renew already off → reply-only confirmation).
- **Judgment call areas:**
    - When to add Apple parallel directions: only if the ticket signals an Apple subscription request, not speculatively. Current guidance: if the customer mentions iPhone, iPad, App Store, or explicitly says Apple → include. Otherwise → investigation reply only.
    - How many follow-up rounds before escalating. Currently assumed: one investigation reply → if still not found after customer responds with identifying info → escalate.

# Examples

These examples share the same account trigger (`Account Found: false`) — what changes is the original request type, which shapes the tone and framing of the investigation reply.

**Account context (same for all three):**
- `Account Found: false` on ticket email
- No second email visible in ticket body
- Subscription platform unknown

---

## Example 1 — No account found, original request: cancellation

**Classification:** Reply only. Investigation reply needed before any action can be taken. Cancellation-specific framing — includes Apple self-serve directions in parallel since we can't rule out Apple platform.

**Response:**

> Hi [Name],
>
> I'm glad you wrote so I can help you get your Happier Meditation subscription cancelled.
>
> There's no subscription registered to [email] so we need to find out what address your subscription's registered to and where you bought it.
>
> **Apple**
> If you started your subscription through Apple's App Store, you'll need to work with them directly. For your security, they don't let us cancel on your behalf but it's easy to do right on your phone. You'll find the steps here: If you want to cancel a subscription from Apple.
>
> **Google Play or our Website**
> If you started your subscription through our website or the Google Play store, we need to find the registration.
>
> If you're still signed into the app, check the app settings like this:
> - Open your Profile in the upper corner of the app.
> - Tap Settings (gear icon) in the upper right corner.
> - Tap Account under MEMBERSHIP.
> - Check the Login Method and the Email and let us know what's there.
>
> If you're not signed into the app anymore, send me the following and I'll keep researching:
> - A copy of the receipt if you have it.
> - The last 4 digits of the credit card you used.
> - If you use an iPhone or iPad, please check to see if you used Sign in with Apple to create your Happier Meditation account. Our Help Center article Check for a Hidden Sign in with Apple Address has the steps.
> - If you have none of the above, send a list of other email addresses you have.
>
> I hope you're having a good day and I look forward to hearing back from you,
> [Agent name]

**Notes:**
- Apple self-serve cancellation directions are included in parallel even before the account is located — we can unblock them on Apple regardless of whether we find the account
- "I'm glad you wrote so I can help you get your subscription cancelled" — lead with the intent to help, not with the problem

---

## Example 2 — No account found, original request: login issue

**Classification:** Reply only. Investigation reply needed to locate the subscribed account before login instructions can be sent.

**Response:**

> Hi [Name],
>
> I'm [Agent] from the Support team and I'm happy to help you get connected to your subscription. I can see your email address [ADDRESS] which doesn't have a subscription on it so let's find the purchase and you'll be able to get set up.
>
> Our accounts are registered to either an email address or Sign in with Apple address and I'm guessing you have more than one account going. Would you send some more information so we can find your subscription? Here's what'll help us:
>
> - If you're an Apple customer, check to see if you used Sign in with Apple to create your account. Our Help Center article Check for a Hidden Sign in with Apple Address has some steps to help you find that.
> - A copy of the receipt if you have it.
> - The date and amount of the charge to your bank account.
> - The last 4 digits of the credit card you used to purchase the subscription.
> - List other email addresses you have.
>
> Thanks in advance for the additional information - I look forward to hearing back from you,
> [Agent name]

**Notes:**
- Framing is optimistic ("let's find the purchase and you'll be able to get set up") — not "we can't find you"
- The email address placeholder [ADDRESS] is filled with the actual contact email in the real reply
- No Apple parallel directions here (unlike cancellation) — login can't be unblocked until we find the account

---

## Example 3 — No account found, original request: generic / unclear

**Classification:** Reply only. Investigation reply with neutral framing — no request-specific action can be offered until the account is located.

**Response:**

> Hi [Name],
>
> Thanks for writing in so we can help get everything straightened out. To get started, I need to know the address you used to register your Happier Meditation account. We don't have an account in our systems registered to [email].
>
> If you're still signed into the app you can check it like this:
> - Tap the Profile icon at the top of your screen.
> - Tap Settings (gear icon) in the upper right corner.
> - Tap Account under Membership.
> - Check the Login Method and the Email and let us know what you see there.
>
> If you're not signed into the app, send us any other email addresses you use and, if you're an Apple customer, check for a hidden Sign in with Apple address. Our Help Center article Check for a Hidden Sign in with Apple Address has the steps.
>
> I look forward to hearing back from you!
>
> Thanks,
> [Agent name]

**Notes:**
- "Get everything straightened out" — neutral framing that works for any underlying request
- In-app account check is offered first (fastest path to finding the email) before asking for receipts/card digits
- Use this framing when the original request is ambiguous, billing-related but not clearly a cancellation, or a general inquiry

# Related Policies

- *Account Lookup Data Model* (field definitions, `Account Found` handling)
- *Subscription & Billing Overview* (provider-specific capabilities)
- *Refund Policy* (apply once account is located and customer is within refund window)
- *Apple/Google → Stripe Migration* (if Apple customer wants to cancel and resubscribe on Stripe)
- *Free Trial Policy* (if account found shows a trial that needs cancellation)
- *[Account Found — No Subscription / Account Deletion]* (adjacent scenario: contact email matches an account but no subscription exists)

## Note on Family Sharing as a troubleshooting suggestion

When investigating an Apple-billed subscription that can't be matched (merchant descriptor `APPLE.COM/BILL`), don't default to suggesting the customer check whether the subscription is under a family member's Apple ID via Family Sharing. Many customers don't have Family Sharing set up at all, and offering it as a blanket step wastes their time. Only raise the Family Sharing possibility if the customer has indicated they use Family Sharing, or after confirming with them that it's enabled. The standard, generally-applicable checks remain: Settings → [name] → Subscriptions on the device itself, and checking for a hidden Sign in with Apple relay address.
