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
- **If the customer invokes GDPR or "right to erasure":** Human action required. Do not send the standard reply or direct to self-serve deletion. See Edge Cases below.
- **If the customer says they can't find the deletion option in the app:** Confirm which app version they're on and provide navigation steps. If the option is missing or broken, escalate to support engineering.
- **If the customer is on iPhone/iPad and deletion fails:** Sign in with Apple complications can sometimes block in-app deletion. Escalate to a senior agent to handle manually.

## Edge Cases & Exceptions

- **Customer invokes GDPR / right to erasure** → Human action required. GDPR requests have specific response and fulfillment timelines and may require agent-executed deletion with a documented confirmation record. Do not instruct self-serve deletion. Flag for senior agent or data privacy owner immediately.
- **Customer wants written confirmation of deletion** → Human review. An agent should draft confirmation after the customer completes in-app deletion. The AI should not send this automatically.
- **Account not found on contact email** → This policy does not apply. Do not send deletion instructions for an account we cannot confirm exists. Investigate which email the account may be under first.
- **Customer wants deletion but has an active subscription** → Different policy applies. Do not advise deletion until the subscription is cancelled. See **Cancellation + Account Deletion**.
- **Customer previously submitted a deletion request** → Check ticket history. If a prior agent already handled it, confirm current account status and inform the customer. If deletion was completed, confirm and close.

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