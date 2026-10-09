# Summary

Covers tickets where a customer has explicitly stated they want their account deleted. The account is found on the contact email, has no active subscription, trial, or pending charges, and the customer's intent is unambiguous. The primary tasks are: confirm what we see on the account, direct them to self-serve deletion, and make sure we haven't missed a subscription on a different email before closing the ticket.

# Trigger Conditions

- **Ticket signals:** customer explicitly states they want their account deleted or data removed — phrasing is typically direct and clear ("please delete my account," "I want my account deleted," "remove all my data," "I'd like to close my account")
- **Account signals:** `Account Found: true`, `Subscribed: false`, no trial, no pending charges on the contact email
- **Keywords / phrases:** "delete my account," "close my account," "remove my data," "delete my data," "I want to be removed," "please close my account," "GDPR," "right to erasure," "data deletion"

> **Scope note:** This policy is for tickets where deletion is the stated, primary intent. If the customer's main concern is a charge they don't recognize or a subscription they can't find — and deletion is secondary or not mentioned — see **Account Found, No Subscription (Charge Inquiry)** instead.
> 

# Required Context

- [ ]  `Account Found: true` and `Subscribed: false` confirmed on contact email
- [ ]  Whether the customer also mentions a charge, receipt, or subscription they believe exists
- [ ]  Whether the customer is on iPhone/iPad (→ Sign in with Apple second-account check may apply)
- [ ]  Whether the customer invokes GDPR, "right to erasure," or other data privacy language (→ changes handling — see Variations)

# Policy / Correct Response

## Standard Case

The customer wants their account deleted. The account on the contact email is free with no subscription. Do the following:

1. **Confirm what we see** — tell the customer their account is free, name the email it's on, and confirm there's no trial, subscription, or pending charges.
2. **Direct them to self-serve deletion** — the customer can fully delete the account from the account page inside the app. We do not need to do this on their behalf for a standard request.
3. **Briefly flag the second-account possibility** — even when deletion is the only stated concern, include a short note: if they ever received a receipt or believe a subscription exists elsewhere, they should send it to us. This protects against the case where a subscription lives under a different email and the customer doesn't realize it.

**Standard reply template:**

> Hi {firstName},
> 

> 
> 

> Your account is registered to {email} — it's a free account with no trial, subscription, or pending charges on it.
> 

> 
> 

> You can fully delete this account from the account page inside the app. Once deleted, your data will be removed from our system.
> 

> 
> 

> One thing worth mentioning: if you ever received a receipt from Happier Meditation, there may be a second account registered to a different email address. If that's the case, send us the receipt or any details about the charge and we'll look into it. If you're on an iPhone or iPad, it's also worth checking for a hidden Sign in with Apple address — our Help Center article [Check for a Hidden Sign in with Apple Address](https://support.meditatehappier.com/article/314-check-for-a-hidden-sign-in-with-apple-address) explains how.
> 

> 
> 

> I hope you have a happy day, {firstName}
> 

## Variations

- **If the customer also mentions a charge or unrecognized receipt alongside the deletion request:** Do not proceed with the deletion reply. Investigate the charge first — the account they want deleted might not be the account with the subscription. Route to **Account Found, No Subscription (Charge Inquiry)**.
- **If the customer invokes GDPR or "right to erasure":** Handle through the standard deletion flow — our cancellation/account-deletion process is GDPR compliant (confirmed 2026-07-20), so no separate compliance procedure is needed. See Edge Cases below.
- **If the customer says they can't find the deletion option in the app:** Confirm which app version they're on and provide navigation steps. If the option is missing or broken, escalate to support engineering.
- **If the customer is on iPhone/iPad and deletion fails:** Sign in with Apple complications can sometimes block in-app deletion. Escalate to a senior agent to handle manually.

## Edge Cases & Exceptions

- **Customer invokes GDPR / right to erasure** → Non-issue: the standard cancellation/account-deletion process is GDPR compliant (confirmed 2026-07-20). Handle exactly like a standard deletion request — same reply, same self-serve or agent-assisted path. No dedicated GDPR procedure, timeline tracking, or data-privacy-owner routing is required.
- **Customer wants written confirmation of deletion** → Human review. An agent should draft confirmation after the customer completes in-app deletion. The AI should not send this automatically.
- **Account not found on contact email** → This policy does not apply. Do not send deletion instructions for an account we cannot confirm exists. Investigate which email the account may be under first.
- **Customer wants deletion but has an active subscription** → follow *Deletion with an active subscription* below (solo first step; taught 2026-10-09).
- **Customer previously submitted a deletion request** → Check ticket history. If a prior agent already handled it, confirm current account status and inform the customer. If deletion was completed, confirm and close.

- **Marketing-list removal for a deleted account (taught 2026-10-09, Cassidy, Yorba #321942):** Happier Meditation no longer uses Braze. When a customer or an authorized agent (Yorba, PrivacyHawk, McAfee, etc.) asks to remove a deleted account's email from marketing lists, there is nothing left to suppress. Confirm it's completed ("We've removed <email> from all Happier Meditation marketing lists…") and close. Solo, no hold. Older notes that wait on a "Braze unsubscribe" are obsolete.

## Deletion with an active subscription — SOLO first step (taught 2026-10-09 — Yagnesh #322791)
1. **Stripe:** turn off auto-renew (`stripe_cancel_subscription.py --apply`), verify `cancel_at_period_end` true. (Apple: send the Apple cancel steps; Google: hold for Cassidy's Play Console cancel.) No refund unless they asked and it's in-window.
2. Send the cancel confirmation **plus** the `AccountManagement DeleteAccountActiveSubscription` acknowledgement in one reply: "We've turned off auto-renew … so you won't be charged on <date>. You'll keep access until then. Before we delete your account, we need you to acknowledge that: you're giving up any remaining subscription access; you'll lose your app history; you'll need to register again to use the app; deletion cannot be undone. Would you write back to confirm…?" Close.
3. **When they confirm:** hold with one internal note for Cassidy to delete the account in admin (Berts don't delete accounts). Release the claim.
4. **After Cassidy deletes:** verify no user remains (admin/Maven by email — a stale Maven search can lag; re-check the user uuid returns 404) and that any Stripe sub is canceled (the deletion usually cancels it; if not, cancel it now and log it). Then send the `AccountManagement DeleteAccountCompletedByUs` confirmation ("I deleted your account registered to <email>, and all traces of your data will be completely removed from the Happier Meditation systems within 30 days.") and close.

## Third-party erasure requests (McAfee Online Account Cleanup, PrivacyHawk, Yorba, etc.)
Same shape: confirm what we hold (account, Stripe), hold with a note for Cassidy to delete, then — after verifying the account is gone — send the DeleteAccountCompletedByUs-style confirmation and close (Phyllis #322578, Julie Waters #322858). If the account was already deleted earlier, confirm that with the date. Marketing-list removal asks for deleted accounts are confirmed as completed (Braze is retired; see the 2026-10-09 rule above).

# Action Classification

## No Action Required (reply only)

Safe to handle as reply-only when **all** of the following are true:

- Account confirmed: found, no subscription, no trial, no pending charges
- Customer has not mentioned a charge, receipt, or any subscription
- No GDPR or legal/data privacy language in the ticket
- Customer is asking to delete a free account with no complications

Send the standard reply. Close the ticket after the customer confirms deletion or after a reasonable follow-up window with no response.

## Human Action Required

- **Action:** Handle as a formal data privacy / GDPR request
    
    **When:** Customer uses GDPR, "right to erasure," "data deletion request," or similar legal language
    
    **Why AI can't do it:** Requires verified fulfillment, a documentation record, and potentially agent-executed deletion with compliance logging
    
- **Action:** Manually execute account deletion
    
    **When:** Customer cannot complete in-app deletion due to a technical issue (button missing, error thrown, Sign in with Apple blocking deletion)
    
    **Why AI can't do it:** Requires admin access to the account system
    
- **Action:** Investigate charge before responding
    
    **When:** Customer mentions a receipt or charge alongside the deletion request
    
    **Why AI can't do it:** Requires looking up billing records — potentially across multiple emails — before the correct reply can be determined
    

## Do Not Auto-Send Conditions

Even when the reply is "reply-only" (no admin action needed), flag for human review before sending if any of the following are true:

- Customer mentions a charge, receipt, or subscription alongside the deletion request — investigation needed before any deletion guidance
- Customer uses GDPR, "right to erasure," or any legal/data privacy language — formal compliance handling required
- Customer mentions they've previously requested deletion and it wasn't completed — human should verify current account state and prior ticket history
- Customer is threatening legal action — tone-sensitive, immediate human handling

## Escalation Triggers

- **Two or more subscribed accounts found across any email in the ticket** → escalate immediately to support leadership. Do not send any reply.

- GDPR / right to erasure invoked → Senior agent or data privacy owner
- In-app deletion is broken or erroring → Support engineering
- Customer is threatening legal action alongside the deletion request → Senior agent immediately

# Confidence Notes

- **High confidence areas:** Standard case (free account, explicit deletion request, no charge mentioned) — this is clear-cut; safe to auto-draft with human review before sending
- **Judgment call areas:** Whether to include the second-account note when the customer has made zero mention of a subscription. Current guidance is always include it. Some agents may find it unnecessary in certain cases — flag for calibration if this comes up.
- **Gaps:** GDPR/data privacy fulfillment procedure is not fully captured here. This doc flags the trigger and routes to human review, but a dedicated **GDPR / Data Privacy Requests** policy doc needs to be created.

# Related Policies

- Account Found, No Subscription (Charge Inquiry)
- APPLE SUPPORT DOC: Sign in with Apple — Hidden Address Check