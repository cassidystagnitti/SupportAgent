# Login issues
# Summary

Covers all tickets where the customer's primary issue is logging into the Happier Meditation app — they can't sign in, they're signed in but don't see their subscription, or they think they're on the wrong account. The goal is always the same: get them signed into their **subscribed** account. We never direct a customer to log into an unsubscribed account when they believe they have a subscription.

# Trigger Conditions

- **Ticket signals:** customer says they can't log in, can't sign in, are locked out, signed in but missing premium content, signed in but missing favorites/history, on the wrong account, or asks how to access their subscription on a new device
- **Account signals:** any combination — account found and subscribed, account found but unsubscribed, no account found. The customer's stated problem is what triggers this doc, not the account state
- **Keywords / phrases:** "can't log in," "can't sign in," "locked out," "forgot password," "wrong account," "missing my subscription," "don't see premium," "not unlocked," "signed in but," "new phone," "new device," "how do I sign in," "Sign in with Apple," "Sign in with Google"

> **Login is the parent doc when the customer's stated request is access to the app.** If the customer's request is something else (cancellation, refund, billing) and the lookup fails, use *No Account Found — Troubleshooting* instead. If the customer asks about lost history or favorites specifically, that is an escalation regardless of login state — see Escalation Triggers.
> 

# Required Context

- [ ]  Result of account lookup across **all email addresses on the Help Scout profile** (this happens automatically before the AI drafts a reply)
- [ ]  `Subscribed` status of any account(s) found
- [ ]  `Subscription Platform` of any subscribed account found (informs nothing for the reply itself, but matters for related issues)
- [ ]  Whether the customer has explicitly claimed they have a subscription (see Standard Case below for what counts)
- [ ]  Whether the customer mentions an iPhone, iPad, or App Store (→ include Sign in with Apple guidance in the troubleshooting reply)
- [ ]  Whether the customer mentions lost or missing history, favorites, or saved meditations (→ escalate)
- [ ]  Whether the customer mentions being charged twice or having two subscriptions (→ escalate)

# Policy / Correct Response

## Standard Case

The core principle: **find the subscribed account, then send login instructions for that account.** We do not direct a customer to log into an unsubscribed account when they're claiming a subscription.

**Content access is app-only; the web is checkout-only (confirmed 2026-07-20, changing very soon).** Purchases work on the web — the web checkout flow, including the policy-prescribed discount coupon links (`/start/sign_in?coupon=...`) and gift purchase/redemption, is fine to send. But there is no website sign-in to *access content or the product*: all login/access instructions go through the app's welcome screen (**Already have an account? Sign In**). Never send a bare website sign-in link for account or content access, and do not proactively promise the upcoming web/desktop view.

### What counts as the customer claiming a subscription

Any of the following:

- Explicit statements: "I pay for premium," "I have a subscription," "I'm a subscriber," "I'm a paying member," "I have an annual plan"
- Charge/receipt references: "I was just charged," "I have a receipt," "my card was billed," "I paid for this"
- Feature references that imply paid access: "I had all my premium content," "I lost my downloaded meditations," "my unlocked courses are gone", “everything is locked”, “it’s treating me like I’m new”, “it wants me to sign up again”

If the customer makes any of these claims, treat as a subscription claim even if account lookup shows only a free account or no account.

### Decision flow

**1. Subscribed account found (on any email associated with the Help Scout profile)**

→ Send the **Login Instructions reply** (template below), with the subscribed account's email plugged into the EMAILADDRESS placeholder. If the subscribed email differs from the email the customer wrote in from, briefly acknowledge that in the reply so they know which one to use.

**2. Only a free/unsubscribed account found, AND the customer is claiming a subscription**

→ Treat as "subscribed account not yet located." Do **not** send login instructions for the free account. Send the *No Account Found — Troubleshooting* investigation reply to gather more info (Sign in with Apple check, receipt, last-4, other emails).

**3. No account found at all, AND the customer is claiming a subscription**

→ Same as above — send the *No Account Found — Troubleshooting* investigation reply.

**4. Only a free/unsubscribed account found, AND the customer is NOT claiming a subscription**

→ Send Login Instructions for the free account. The customer just needs help getting back into the app they have.

**5. No account found at all, AND the customer is NOT claiming a subscription**

→ Send the *No Account Found — Troubleshooting* investigation reply. They may have used a different email.

### Login Instructions reply template

This is the saved reply, adapted to include all three sign-in methods (we don't currently know which method the customer used to create their account, so we surface all three):

```
Hi {%customer.firstName,fallback=there%},

Thanks for meditating with us! If you're not seeing everything unlocked in the app, let's have you sign out (if necessary) and sign in again to make sure it's connecting to your subscription.

Download the App
* You probably have the free Happier app downloaded onto your iPhone, iPad or Android mobile device already but if not, please go ahead and do that now. You don't pay to download the app.

Make Sure You're on the Sign In Page
When you open the app, you should see two choices, Get Started and Already have an account? Sign In. If you don't see this, you need to get back to it.
* Sign out of the app with the steps in this article, Sign Out of the Happier App
or
* If you're halfway signed in, give it a quick reboot using Force Quit (Apple Devices) or Force Stop (Android device).

Sign In
When you see Already have an account? Sign In at the bottom of the screen, tap Sign In and choose the method you originally used to create your account:

* Sign in with Email
  - Tap the Sign in with Email button.
  - Type in your email address: EMAILADDRESS.
  - Type in your password. If you need to reset your password, here's our Help Center article: Reset Your Password.
  - Tap Sign In.

* Sign in with Apple
  - Tap the Sign in with Apple button.
  - Use the Apple ID associated with EMAILADDRESS (this may be a Hide My Email relay address).

* Sign in with Google
  - Tap the Sign in with Google button.
  - Choose the Google account associated with EMAILADDRESS.

Give this a try and let us know if you're still running into trouble or if we can keep helping.

As you work through the app's contents you might also want to check out our teachers' answers to common questions from other people using mindfulness meditation in their lives. Try the Meditation FAQ page on our website.

Write back anytime with questions - we'll be here!
{%user.firstName%}
```

**Where to put the email:** Replace `EMAILADDRESS` with the email of the subscribed account we located. This is the whole point of the reply — we're directing them to the correct account.

**If the subscribed email differs from the write-in email:** Add a brief acknowledgment near the top, e.g., *"I found your subscription under EMAILADDRESS — that's the one to use to sign in."* This reduces confusion and pre-empts the next ticket.

## Variations

- **If subscribed account found on the same email customer wrote in from:** Send Login Instructions as-is. No need to flag a different email.
- **If subscribed account found on a different email on the Help Scout profile:** Send Login Instructions with a brief acknowledgment that we found their subscription under a different email.
- **If the customer mentions iPhone, iPad, or App Store and we couldn't locate a subscribed account:** Use the No Account Found investigation reply, which already includes the Sign in with Apple / Hide My Email check.
- **If the customer is currently signed in to a free account but claims a subscription:** This is the classic two-account case. Send Login Instructions for the *subscribed* account once located, prefaced with a sign-out step (the saved reply already includes this).
- **If the customer is on Android and we can't find a subscribed account:** Same investigation reply path. Hide My Email isn't relevant here, but the email-mismatch reasons still apply.

## Edge Cases & Exceptions

- **Customer says they used Sign in with Apple and can't find their relay address** → Send the Sign in with Apple guidance from the *No Account Found — Troubleshooting* investigation reply. Reference [Apple's documentation](https://support.apple.com/en-us/HT210318) and our [Help Center article on Hidden Sign in with Apple Address](https://support.meditatehappier.com/article/314-check-for-a-hidden-sign-in-with-apple-address).
- **Customer asks specifically how to reset their password:** The Login Instructions reply already links to the password reset article. Send the standard reply.

# Action Classification

## No Action Required (reply only)

The vast majority of login tickets are reply-only. Specifically:

- Subscribed account found → send Login Instructions for that account
- Free-only account found, no subscription claim → send Login Instructions for the free account
- No account found, no subscription claim → send No Account Found investigation reply
- Free-only or no account found, but subscription claim → send No Account Found investigation reply (still reply-only at this stage; investigation may surface action requirements later)

## Human Action Required

- **Action:** Deeper account lookup using receipt, last-4 card digits, or Sign in with Apple relay address provided by the customer in a follow-up
- **When:** The customer responded to the investigation reply with identifying information and we still can't locate the subscribed account they're claiming
- **Why AI can't do it:** Requires querying billing records by payment details, not available via the standard account lookup API
- **Action:** Transfer history between accounts
- **When:** Customer has lost history/favorites due to a duplicate-account situation and explicitly wants old data restored
- **Why AI can't do it:** Requires admin access and judgment about which account's data is canonical; we cannot merge accounts

## Do Not Auto-Send Conditions

Even when the reply is "reply-only" (no admin action needed), flag for human review before sending if any of the following are true:

- Customer claims a subscription but only a free/unsubscribed account is found — the investigation reply path requires human judgment on whether the lookup is truly exhaustive
- Customer mentions lost history, favorites, or saved meditations alongside login trouble — escalation component needs human routing
- Customer mentions being charged twice or having two subscriptions — escalation required
- The subscribed account email differs significantly from the write-in email (different domain, different name) — human should verify it's actually the same person before directing them to the other account
- Customer's tone suggests frustration or confusion that the standard login template won't adequately address — personalization needed

## Escalation Triggers

- **Two or more subscribed accounts found across any email in the ticket** → escalate immediately to support leadership. Do not send any reply.
- **Customer mentions lost or missing history, favorites, downloaded content, or saved meditations** → escalate after the login attempt; first reply gets them logged in, second reply or internal handoff addresses the history concern
- **Customer mentions being charged twice, two subscriptions, or duplicate billing** → escalate to support leadership
- **Investigation reply has been sent and customer responded with identifying info, but the subscribed account still cannot be located** → senior support for deeper billing investigation
- **Account found via lookup but appears to belong to a different person** (e.g., shared credit card, family situation, different name) → senior support

# Confidence Notes

- **High confidence areas:**
    - The core rule: never direct a customer to log into an unsubscribed account when they're claiming a subscription
    - The auto-lookup across all Help Scout profile emails happens before the AI drafts (so the AI is reasoning over a complete picture, not asked to perform the lookup itself)
    - All three sign-in methods are surfaced in the reply since we don't currently know which method the customer used
    - History/favorites concerns and two-active-subscriptions are always escalations
    - The investigation reply for the "can't find subscribed account" path lives in *No Account Found — Troubleshooting* and is reused here verbatim
- **Judgment call areas:**
    - What counts as a "subscription claim." Current rule: explicit statements, charge/receipt references, or feature references implying paid access. Borderline cases (e.g., "I think I had a subscription a while ago") should default to investigation reply rather than logging them into a free account.
    - Whether to add the "I found your subscription under [different email]" acknowledgment when the subscribed email matches the write-in email — currently: omit, since it would be redundant.
    - For the history-escalation timing: try login first if the customer also has a login issue, then escalate the history concern. If history is the only issue, escalate immediately without attempting login first.
- **Gaps:**
    - The system currently does not surface which sign-in method (Email / Apple / Google) was used to create a given account. Once that field is exposed, the reply can be narrowed to the relevant method instead of listing all three. Flagged as a future improvement by support lead.

# Examples

## Example 1 — Subscribed account found, same email, iPad mentioned

**Ticket:**
> I've had an account for several years. My iPad Happier Meditation app won't allow me in as if I need to open a new account. Please help. Thanks.

**Account context:**
- Subscribed account found: `robertabutterfly@gmail.com`
- Same email the customer wrote in from
- Subscription platform: Stripe

**Classification:** Reply only. Subscribed account found on the write-in email. Implicit subscription claim ("several years," "as if I need to open a new account"). iPad mentioned → include Sign in with Apple guidance.

**Response:**

> Hi Roberta,
>
> Thanks for meditating with us! If you're not seeing everything unlocked in the app on your iPad, let's have you sign out (if necessary) and sign in again to make sure it's connecting to your subscription.
>
> **Download the App**
> You probably have the free Happier app downloaded onto your iPhone, iPad or Android mobile device already but if not, please go ahead and do that now. You don't pay to download the app.
>
> **Make Sure You're on the Sign In Page**
> When you open the app, you should see two choices, Get Started and Already have an account? Sign In. If you don't see this, you need to get back to it.
> - Sign out of the app with the steps in this article, Sign Out of the Happier App
> - or if you're halfway signed in, give it a quick reboot using Force Quit (Apple Devices) or Force Stop (Android device).
>
> **Sign In**
> When you see Already have an account? Sign In at the bottom of the screen, tap Sign In and choose the method you originally used to create your account:
>
> - **Sign in with Email** — Tap the Sign in with Email button. Type in your email address robertabutterfly@gmail.com. Type in your password. If you need to reset your password, here's our Help Center article: Reset Your Password. Tap Sign In.
>
> - **Sign in with Apple** — If this email address is associated with an Apple ID, tap the Sign in with Apple button. Use the Apple ID associated with robertabutterfly@gmail.com (this may be a Hide My Email relay address).
>
> - **Sign in with Google** — If this email address is associated with a Google account, tap the Sign in with Google button. Choose the Google account associated with robertabutterfly@gmail.com.
>
> Give this a try and let us know if you're still running into trouble or if we can keep helping.
>
> As you work through the app's contents you might also want to check out our teachers' answers to common questions from other people using mindfulness meditation in their lives. Try the Meditation FAQ page on our website.
>
> Write back anytime with questions - we'll be here!
> Cass

**Notes:**
- "Several years" + "as if I need to open a new account" = implicit subscription claim even though the customer never says "I have a subscription"
- iPad is mentioned → all three sign-in methods are included, with Sign in with Apple explicitly listed
- Subscribed email matches write-in email → no need to acknowledge a different email
- The iPad-specific detail ("on your iPad") is woven into the opening line to show we read the ticket

# Related Policies

- *No Account Found — Troubleshooting* — used for the investigation reply path whenever we can't locate the subscribed account the customer is claiming
- *Account Lookup Data Model* — defines `Subscribed`, `Subscription Platform`, and the lookup behavior
- *Subscription & Billing Overview* — provider context if the login issue surfaces a billing question

## Try Restore Purchases early (Apple/Google entitlement mismatches)

When a customer is on Apple or Google (or platform is unclear but they're on a mobile device), and account lookup shows no subscription despite the customer believing they have one, have them try **Restore Purchases** in-app (Profile → Settings → Account) as a first, low-friction step — before or alongside asking for receipts, last-4 card digits, or other identifying info.

Restore Purchases can silently re-link an existing Apple or Google subscription to the signed-in account without any support action, and it costs the customer almost nothing to try. This is the same mechanism used in *Multi-Account Merge* to re-link a subscription after a wrong-account sign-in — it's worth surfacing proactively here too, not just after a merge is diagnosed.

This does not replace the investigation reply (receipt / last-4 / other emails) — include both so the customer isn't stuck waiting on a reply-and-forth if Restore Purchases doesn't resolve it.
