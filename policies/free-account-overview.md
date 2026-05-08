# Free Account Overview

# Summary

Covers tickets from users on free accounts — no active subscription, trial, gift, or promo access of any kind. The most common questions are "what is a free account," "why is content locked," and "where is the free content." Standard handling is to explain what a free account is, describe what content is freely available, and welcome them to explore it. A secondary scenario is when a user is surprised their account has reverted to free — in that case, look into account history and let them know if a subscription recently expired.

# Trigger Conditions

- **Ticket signals:** customer asks what a free account is, why content is locked, why they see lock icons, what they can access without subscribing, or where to find the free content
- **Account signals:** `Subscribed: false`, no active trial, no active gift or promo subscription — all content access is locked except free-tier content
- **Secondary signals:** customer is surprised, confused, or frustrated that their account "changed" or content they previously had access to is now locked
- **Keywords / phrases:** "free account," "locked content," "why is everything locked," "what's free," "what can I access," "lock icons," "paywall," "limited access," "my account changed," "used to have access," "why can't I access"

# Required Context

- [ ]  `Account Found` status — is there an account on the contact email?
- [ ]  Whether the account has any subscription history (prior Stripe, Apple, Google, gift, or promo subscription that may have lapsed)
- [ ]  Whether the customer's question is purely informational ("what's free?") or signals surprise/frustration about lost access
- [ ]  Platform (Apple/Google/Stripe) if the customer is interested in subscribing — needed to direct to the right flow

# Policy / Correct Response

## Standard Case: Customer asking what a free account is or where to find free content

Explain clearly:

- A **free account** is an account with no active subscription. The majority of the app's content is subscriber-only and appears locked with a lock icon. Tapping locked content shows a subscription prompt.
- The following content is **free for all users**, with no subscription required:
  - **50+ single meditations** spread throughout the app
  - **The Getting Started course**
  - **The Dalai Lama's Guide to Happiness**
  - **The unguided timer** (meditate for any length of time without a guided session)
- Free users are welcome to meditate as much as they want on free content — there is no usage cap.
- There is **no way to sort or filter by free content** in the app currently. Free content is interspersed throughout the library.

Always welcome them to explore the free content. If they express interest in subscribing or getting full access, surface the appropriate subscription or trial reply.

## Variation: Customer surprised their account has reverted to free

When a user who previously had access writes in confused about why content is now locked:

1. Look up their account history — check for a recently expired subscription (Stripe, Apple, Google Play), an expired gift certificate, or an expired promo/need-based code.
2. Let them know what happened: which subscription ended, when it ended, and how (auto-cancelled, payment failure, gift/promo expired, etc.).
3. If they want to resubscribe, offer the appropriate subscription or discount reply.

Do not assume the account was "always free" without checking history first. A surprising number of "why is my account free?" tickets come from lapsed subscribers who lost track of their subscription.

## Edge Cases & Exceptions

- **User thinks they're subscribed but shows as free:** This is likely a login issue (wrong email) or a platform mismatch (subscribed under a different account). Do not treat as a free account question — see *Login Issues* and *No Account Found Troubleshooting*.
- **Expired gift subscription:** Treat the same as an expired paid subscription. Explain the gift period ended and offer options to subscribe.
- **Expired promo / need-based code:** Same treatment. Note that need-based promos can be re-requested if circumstances remain — see *Need-Based Complimentary Subscriptions*.
- **Free user asking to cancel:** There is nothing to cancel on a free account. See `CancelRefund FreeAccountCancel`.
- **Free user asking for a refund:** If they have no subscription history, there is nothing to refund. If they have a recent lapsed charge, investigate and see *Refund Policy*.

# Action Classification

## No Action Required (reply only)

- **Informational question about free account / free content:** Explain + point to free content. No account action needed.
- **Expired subscription identified:** Inform the customer of what happened. No action needed unless they want to resubscribe.

## Human Action Required

None for standard free account inquiries. If the customer wants to resubscribe:

- **Stripe:** Support can apply a discount coupon if offering a promotional rate.
- **Apple / Google:** Redirect to self-service. No direct action available.

## Do Not Auto-Send Conditions

- Customer expresses surprise or frustration about lost access — human review recommended to ensure the account history explanation is accurate and the tone is right
- Customer mentions a charge or payment in the same ticket — may involve a refund or billing issue; see *Refund Policy*
- Account history shows a failed payment as the reason access lapsed — do not auto-send; human should frame the explanation carefully

## Escalation Triggers

- Multiple subscriptions found across different emails with overlapping access periods → escalate; may indicate an account merge situation (see *Multi-Account Merge*)
- Customer reports losing access immediately after a payment was processed → investigate; should not happen; escalate if confirmed

# Confidence Notes

- **High confidence areas:** What a free account is. What content is free. Free users have no usage cap. No sort-by-free-content feature exists.
- **Judgment call areas:** How much detail to give about the free content library (list it fully vs. summarize). Whether to proactively offer a trial or discount to an informational inquiry, or wait for the user to express interest.
- **Gaps:** No saved reply currently exists that comprehensively describes all free content in one place beyond `SNIPPET FreeContentIncludes`. If that snippet is incomplete or outdated, flag it for a content update.

# Saved Reply Mapping

## Informational — explaining free account / free content

| Condition | Saved Reply | Notes |
|---|---|---|
| Customer asks what's free / what they can access | `SNIPPET FreeContentIncludes` | Short snippet: mentions Getting Started course, Dalai Lama's Guide to Happiness, and meditations without a lock icon. Does not mention the unguided timer or call out "50+ singles" — add that context manually if relevant. Use as an inline snippet, not a standalone reply. |
## Free account — cancel / close request (nothing to cancel)

| Condition | Saved Reply | Notes |
|---|---|---|
| Free account, no subscription, customer wants to "cancel" | `CancelRefund FreeAccountCancel` | Confirms the account has no trial, subscription, or pending charges. Also prompts: if they have a receipt or believe they're subscribed, ask them to send it or check for a hidden Sign in with Apple address. |


# Related Policies

- *Subscription & Billing Overview*
- *Free Trial Policy*
- *Login Issues* (if user thinks they're subscribed but shows as free)
- *No Account Found Troubleshooting* (if account lookup returns nothing)
- *Need-Based Complimentary Subscriptions* (if customer cites financial hardship)
- *Gift Subscriptions* (if access lapsed due to an expired gift certificate)
- *Cancellation Policy* (if free account user wants to "cancel")
