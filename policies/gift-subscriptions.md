# Gift subscriptions
# Summary

Covers all tickets where someone is purchasing, redeeming, or asking about a gift subscription. Gift subscriptions are purchased on our website; the purchaser receives a receipt and a PDF gift certificate which they forward to the recipient. The recipient redeems the code on our website — creating an account or signing into their existing one during the process — and the subscription is then available in the app. Gift subscriptions do not auto-renew; they expire cleanly at the end of the term with no charges and no action required. Support offers a 40% discount on gift purchases on request, escalating to 50% if needed.

# Trigger Conditions

- **Ticket signals:** customer wants to buy a gift subscription, received a gift and wants to redeem it, lost their gift certificate PDF, wants to buy a gift for themselves, asking if a gift can be applied to an existing account, gift subscription expired and they want to continue
- **Account signals:** `Subscription Platform: Gift/Promo` or similar comp/gift type on account; or `Subscribed: false` with customer writing about redeeming a code; or any active subscription where the customer is trying to stack a gift on top of it
- **Keywords / phrases:** "gift," "gift certificate," "gift subscription," "gift code," "redeem," "promo code," "give to a friend," "buy for someone," "gifted subscription," "gift card"

# Required Context

- [ ] Is the customer the **purchaser** or the **recipient**?
- [ ] If recipient: do they have an existing Happier Meditation account?
- [ ] If they have an existing account: is there currently an **active subscription** on it?
- [ ] If active subscription: what platform is it on and when does it expire?
- [ ] If purchaser: are they asking for purchase info, requesting a discount, or requesting a copy of the certificate?
- [ ] Is this a **refund request** on a gift purchase? (→ see *Refund Policy*)
- [ ] **Check the Stripe context block.** Stripe enrichment runs automatically on gift tickets. If the purchaser's email matches a Stripe customer, the purchase record will be present. If Stripe returns "not found," the purchase was likely made with a different email — see below for how to locate it.

# Policy / Correct Response

## How gift subscriptions work

**Purchasing:**
- Gift subscriptions are purchased at: https://my.meditatehappier.com/gifts
- Available terms: **1 year** and **4 months**
- The purchaser enters **their own email address** at checkout — the receipt and PDF gift certificate go to the purchaser, not the recipient
- The purchaser then forwards the PDF to whoever they're gifting it to

**Gift subscription terms:**
- **No auto-renewal.** The subscription expires at the end of the term with no further charges and no cancellation action needed.
- **No expiration on the code.** The recipient can redeem the code at any time — there is no deadline to start using it.
- **Cannot be stacked on top of an active subscription.** If the recipient already has an active subscription, they must wait until it expires before redeeming the gift code.

**Discounts:**
- Standard pricing applies unless the customer specifically asks for a discount.
- On request: offer **40% off** the annual gift ($99.99 → $59.99). Purchase link: https://my.meditatehappier.com/gifts?coupons=TNW594Ee&skus=sku_DzZ9r3QEKUYa6b
- If 40% isn't sufficient or the customer specifically asks for it: escalate to **50% off** the annual gift ($99.99 → $49.99). Purchase link: https://my.meditatehappier.com/gifts?coupons=YzR7XLXM&skus=sku_DzZ9r3QEKUYa6b
- Do not proactively advertise discount links — offer only when the customer asks.
- **Link formatting:** never paste a raw gift/discount URL into a reply. Always hyperlink it with descriptive anchor text — e.g. `<a href="...">40% off an annual gift</a>`, `<a href="...">redeem your gift</a>`. See the link-formatting rule in *Account Lookup Data Model*.

## Standard Case

### Purchasing a gift subscription

Send the purchase link and explain how it works. Key points to communicate:
- They enter their own email at checkout — receipt and PDF go to them
- They then forward the PDF to the recipient
- No auto-renewal, no recurring charges at the end
- The code has no expiration date — the recipient can use it whenever

### Redeeming a gift subscription

**Scenario 1: Recipient has no existing Happier Meditation account**
1. Open the redemption link: https://my.meditatehappier.com/redeem/register
2. Create a new account
3. Enter the gift code (capital letters and hyphens both count)
4. Tap Redeem
5. Download the app and sign in using the same method used during redemption

**Scenario 2: Recipient already has a Happier Meditation account**
1. First, verify which account the app is registered to (see Help Center link below) — the gift must land on the right account
2. Open the redemption link: https://my.meditatehappier.com/redeem/register
3. **Sign into their existing account** — do not create a new one
4. Enter the gift code
5. Tap Redeem
6. Return to the app — everything will be unlocked

**Critical:** The recipient must sign in with the same account they use in the app. If they create a new account during redemption, the gift lands on the wrong account. Always direct them to verify their account registration first using [How to Tell What Address Your App Is Signed Into](https://support.meditatehappier.com/article/92-how-can-i-tell-what-email-my-accounts-registered-to).

### Recipient has an active subscription

The gift code cannot be applied while a subscription is currently active — they will get an error. They must wait until the existing subscription expires, then redeem.

Always include the expiration date of their current subscription so they know exactly when to come back.

**Active Apple subscription:** Support cannot cancel Apple subscriptions. Direct the recipient to turn off Apple auto-renewal now so the subscription expires naturally, then redeem afterward. Include Apple cancellation steps in the reply.

**Active Stripe or Google subscription:** Support can turn off auto-renewal if the recipient wants, or they can simply wait it out. Either way, redemption happens after expiry.

### Lost gift certificate — purchaser needs a copy

Support can resend the PDF gift certificate. Attach a copy directly to the reply along with the Help Center redemption link for the recipient.

**Locating the purchase in Stripe:**
- Check the Stripe context block first. If the purchaser's email is on file in Stripe, the purchase is locatable directly.
- If Stripe returns "not found," the purchase was likely made under a different email address. Ask the customer for the **last 4 digits of the card used** and the **approximate date of purchase** — these are sufficient to locate the transaction in Stripe. Do not attempt to resend the certificate until the purchase is confirmed.

### Self-gifting

Customers can purchase a gift subscription for themselves. They follow the normal purchase flow (their own email at checkout, receive the PDF, redeem it themselves). If they have an active subscription, they must wait until it expires before redeeming — same rule as any recipient. Reassure them the code won't expire in the meantime.

### Gift subscription expired, customer wants to continue

The gift subscription ends cleanly — no action needed on their end. The customer can resubscribe:
- **In-app:** tap any locked content
- **Website:** https://my.meditatehappier.com/start/register

Remind them to sign into their existing account (not create a new one) to preserve their history and settings.

### Gift subscription refund

Standard *Refund Policy* windows apply: **30 days from purchase** for the annual gift (there is no monthly gift term). Gift subscriptions are always purchased through our website (Stripe). If within window, cancel and refund. If the recipient has already redeemed the code, see Edge Cases.

## Variations

- **Customer wants to buy a monthly gift subscription:** Only 1-year and 4-month gift terms are available. There is no monthly gift option. Clarify the available terms.
- **Recipient tried to redeem but got an error:** Most common cause is an active subscription on their account. Verify account state and guide them to the deferred redemption path if needed.
- **Recipient redeemed onto the wrong account (created a new account by mistake):** Support can manually apply the gift code to the correct account. Use `Get GiftCertificateWePutCodeOnYourAccount`.
- **Purchaser asks if the recipient will be auto-charged at the end:** No — gift subscriptions never auto-renew. Confirm this clearly.

## Edge Cases & Exceptions

- **Recipient created a new account during redemption instead of signing into their existing one:** The gift is on the wrong account. Support can manually apply it to the correct account (`Get GiftCertificateWePutCodeOnYourAccount`). Confirm the correct account email before acting.
- **Gift code already redeemed, purchaser never gave it to anyone:** Gift codes are single-use. If it's been redeemed, verify which account it landed on. If it was redeemed in error (e.g., the purchaser accidentally redeemed it themselves), support may be able to transfer it — flag for human review.
- **Purchaser requesting a refund after recipient already redeemed the code:** Outside standard policy — the subscription has been used. Escalate; this is a discretionary decision.
- **Customer asks whether the gift can be transferred to a different account:** Not self-serve, but support can manually apply it. Use `Get GiftCertificateWePutCodeOnYourAccount`.
- **Purchaser never received the gift certificate PDF:** It was sent to the email address they entered at checkout. Confirm that email and resend. If the wrong email was entered at purchase, check the Stripe context block — if the purchase isn't found there, ask for the **last 4 digits of the card used** and the **approximate date of purchase** to locate the transaction in Stripe before resending.

# Action Classification

## No Action Required (reply only)

- Gift purchase information and links (standard or discounted)
- Redemption instructions for any scenario (no account, existing account, deferred redemption)
- Resending a lost gift certificate PDF
- Confirming no auto-renewal and explaining the expiry behavior
- Post-gift resubscription information and links
- Self-gifting guidance

## Human Action Required

- **Action:** Manually apply gift code to a customer's account
- **When:** Recipient created the wrong account during redemption, cannot self-redeem due to a technical issue, or requests a code transfer
- **Why AI can't do it:** Requires admin access to apply subscription codes to specific accounts

- **Action:** Process refund on a gift purchase
- **When:** Within the 30-day refund window and the code has not been redeemed by the recipient
- **Why AI can't do it:** Requires Stripe admin access to cancel and refund

## Do Not Auto-Send Conditions

Even when the reply is "reply-only" (no admin action needed), flag for human review before sending if any of the following are true:

- Purchaser is requesting a refund and the recipient has already redeemed the code — not covered by standard refund policy; discretionary decision
- The situation involves multiple accounts or ambiguous ownership (e.g., code redeemed onto the wrong account and the correct account belongs to a different email) — human should verify before modifying subscription state
- Customer is asking for more than 50% off — 50% is the ceiling for gift discounts; anything further requires human judgment
- Purchaser entered the wrong email at checkout and the certificate went to the wrong person — may require Stripe lookup to confirm purchase before acting

## Escalation Triggers

- **Two or more subscribed accounts found across any email in the ticket** → escalate immediately to support leadership. Do not send any reply.
- **Purchaser requesting a refund after recipient has already redeemed and used the subscription** → escalate for discretionary judgment.
- **Gift code reported as invalid or already redeemed but the purchaser has not given it to anyone** → possible system or fraud issue; escalate for investigation.

# Confidence Notes

- **High confidence areas:** No auto-renewal on gift subscriptions. Code has no redemption deadline. Cannot apply while an active subscription exists — must wait for expiry. Purchaser gets the PDF, not the recipient. 40% off is the standard discount offer, 50% is the escalation. Standard 30-day refund window applies to gift purchases. All gift purchases go through Stripe (website only).
- **Stripe enrichment:** Stripe data is automatically enriched for any ticket tagged `gift-subscription`. If the purchaser wrote in from the email they used at checkout, the Stripe customer record will be present. If not found, the purchase was likely made under a different email — ask for last 4 digits of card + approximate purchase date before attempting to locate or resend.
- **Judgment call areas:** Whether to proactively surface the 40% discount when someone asks about gift pricing without specifically asking for a deal. Current guidance: don't volunteer — offer only when they ask about discounts.
- **Gaps:**
    - Whether gift terms beyond 1-year and 4-month exist (the purchase page should be the source of truth).
    - What happens if a gift code is redeemed onto an account that has a pending renewal mid-dunning — is the renewal affected?
    - No defined policy on refunding a gift where the code has been partially used (e.g., redeemed but only 1 week in).
    - No saved reply exists for asking the purchaser for card last 4 + purchase date when the Stripe lookup returns nothing. Should be created.

# Saved Reply Mapping

Work through: purchaser or recipient? → if recipient, account state? → active subscription?

## Purchaser — buying or managing a gift

| Condition | Saved Reply | Notes |
|---|---|---|
| Asking about gift subscriptions, no discount requested | `Get GiftCertificateFullPriced` | Links to purchase page; explains terms, no auto-renew |
| Requesting a discount (first offer) | `Get GiftCertificatePurchase40%Discount` | 40% off ($59.99); only on request |
| 40% insufficient, customer pushes for more | `Get GiftCertificatePurchase50%Discount` | 50% off ($49.99); escalation only |
| Needs copy of gift certificate resent | `Get GiftCertificateCopy` | Attach PDF; includes redemption Help Center link |
| Bought gift for themselves (self-gifting) | `Get GiftCertificateSelfGifting FILLIN` | Fill in current subscription expiry date |
| Refund request, code not yet redeemed, within window | `CancelRefund StripeRefund GiftCertificate` | Cancel + refund; 30-day window from purchase |

## Recipient — redeeming a gift

| Condition | Saved Reply | Notes |
|---|---|---|
| No existing Happier Meditation account | `Get GiftCertificateRedeemGeneral` | Full walkthrough: create account → redeem → sign into app |
| Has existing account, no active subscription | `Get GiftCertificateRedeemOntoExistingAccount` | Sign into existing account before redeeming; verify email first |
| Has active subscription (any platform), must wait | `Get GiftCertificateRedeemLater FILLIN` | Fill in current subscription expiry date |
| Has active Apple subscription, must cancel Apple first | `Get GiftCertificateRedeemLaterCancelAppleSub FILLIN` | Fill in Apple expiry date; includes Apple cancellation steps |
| Support is manually applying the code to their account | `Get GiftCertificateWePutCodeOnYourAccount` | Used when customer can't self-redeem; confirms code applied |

## Gift subscription management

| Condition | Saved Reply | Notes |
|---|---|---|
| Gift subscription expired, customer wants to continue | `Get ResubscribeAfterGiftSubscriptionExpires` | Links to in-app resubscription or website |
| Customer asks if they need to cancel / worried about charges | `CancelRefund FreePromoGuestGiftSub FILLIN` | No action needed; fill in expiry date; confirm no charges |
| Account has gift sub, customer wants to delete account | `AccountManagement DeleteAccountHasPromoGuestGiftSub FILLIN` | Fill in expiry date; offer to help sign in; confirm before deleting |

# Links Reference

| Purpose | URL |
|---|---|
| Purchase gift (full price) | https://my.meditatehappier.com/gifts |
| Purchase gift (40% off) | https://my.meditatehappier.com/gifts?coupons=TNW594Ee&skus=sku_DzZ9r3QEKUYa6b |
| Purchase gift (50% off) | https://my.meditatehappier.com/gifts?coupons=YzR7XLXM&skus=sku_DzZ9r3QEKUYa6b |
| Redeem a gift code | https://my.meditatehappier.com/redeem/register |
| Help Center — Redeem a Gift | https://support.meditatehappier.com/article/32-redeem-a-gift-or-promotional-subscription |
| Help Center — Sign Into Existing Account | https://support.meditatehappier.com/article/52-sign-into-happier-with-an-existing-account |
| Help Center — Find What Address App Is Signed Into | https://support.meditatehappier.com/article/92-how-can-i-tell-what-email-my-accounts-registered-to |
| Help Center — Find Out When Subscription Ends | https://support.meditatehappier.com/article/150-find-out-when-your-subscription-ends |
| Resubscribe after gift expires | https://my.meditatehappier.com/start/register |
| Apple App Store | http://apple.co/1V7sqo9 |
| Google Play Store | https://play.google.com/store/apps/details?id=com.changecollective.tenpercenthappier |

# Related Policies

- *Refund Policy* (refund window applies to gift purchases; 30 days from purchase date)
- *Subscription & Billing Overview* (general platform context; pricing)
- *Account Lookup Data Model* (account state — `Subscription Platform: Gift/Promo/Comp`)
- *Login Issues* (if recipient is having trouble signing in after redemption)
- *No Account Found — Troubleshooting* (if recipient redeemed onto an account they can't access)
- *Need-Based Complimentary Subscriptions* (if customer cannot afford even a discounted gift and needs a free subscription)
