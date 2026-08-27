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
- **Stripe Path-2 40% partial refunds are NO LONGER a human action** — Bert executes them via `scripts/stripe_path2_refund.py` (see *Bert Execution: Path 2* below). After `applied`, the ticket is reply-only and auto-sendable (subject to Do Not Auto-Send Conditions).
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

# Bert Execution: Apply Renewal Coupon (Stripe) — added 2026-07-23

Bert applies renewal discount coupons itself (`scripts/stripe_apply_coupon.py`). **Use it starting immediately** for eligible Stripe annual renewal-discount tickets during the morning review or a sidebar session. This covers the **coupon-application** paths only:

- **Path 1 (pre-renewal)** and **Path 3 (post-renewal past 30 days, applied to the next renewal)** → default `--duration once`: discounts the upcoming renewal invoice.
- **Forever / ongoing discount** (explicit ongoing-need ask, fixed income, or 3+ year pattern) → `--forever`: recurring discount on every renewal.

It does **not** do **Path 2** (retroactive 40% partial refund within 30 days) — that rides on a charge, not the subscription; use `scripts/stripe_path2_refund.py`. It is **annual-only**: a monthly customer is refused (route to *Monthly Discount Requests* — offer 50% annual as the counter).

## Pre-flight: check eligibility BEFORE running the script

Screen from context you already have — never post a draft promising a discount you haven't applied:

1. **Platform must be Stripe.** Apple/Google → migration reply (pre-built Stripe 40% link), not this script.
2. **Plan must be annual.** Monthly → *Monthly Discount Requests*.
3. **Rate:** 40% is standard; ladder to 50% only if the customer pushes back or clearly needs it. **50% is the ceiling — never more.**
4. **Duration:** one renewal (`once`) by default; `--forever` only when a forever-discount trigger is met (explicit ongoing ask, fixed income, or 3+ years of asking).
5. **Two or more subscribed accounts anywhere in the ticket → escalate, do not run the script or reply.**

## How to run it

1. **Dry-run first** (read-only, always safe): `python3 scripts/stripe_apply_coupon.py <cus_…> --json` (add `--percent 50` and/or `--forever` as the case requires). The plan shows the single eligible annual subscription, the current → estimated discounted renewal price, the coupon id, and whether that coupon will be created.
2. **Ladder up:** to raise an existing 40% to 50%, add `--percent 50 --replace-existing`. The script refuses to overwrite a different discount without `--replace-existing` (guards against silently lowering a customer's better discount).
3. **Apply**: `python3 scripts/stripe_apply_coupon.py <cus_…> [--percent 50] [--forever] --apply --conversation-id <HS id> --json`. Same env gates and audit line as the cancel/refund skills. The coupon is reusable across customers (keyed by percent+duration); it is created on first use — this needs the write key's **Coupons:Write** scope.

## Refusals are eligibility answers — map them into the draft

The script refuses (exit 2) rather than guessing. **Each refusal tells you what the reply should say** — never leave a draft claiming a discount that was refused:

| Refusal | Meaning | Draft response | Remaining action |
|---|---|---|---|
| `bills every month … annual-only` | monthly plan | *Monthly Discount Requests* — offer 50% annual as the counter | none (reply-only) |
| `already set to cancel … retention save` | sub is cancelling | Retention save: decide whether to un-cancel + discount | human judgment |
| `not an active, renewing subscription` (unpaid/past_due) | dunning | Resolve the failed payment first (dunning), not a coupon | human |
| `N subscriptions are active … escalation signal` | multiple live subs | Do not reply | escalate to leadership |
| `no Stripe subscriptions … Apple/Google` | not a Stripe sub | Migration offer (Stripe 40% link) per *Apple/Google → Stripe Migration* | reply-only |
| `already carries N% off` (no-op success, exit 0) | discount already there | Confirm the discount already in place; promise nothing new | none |
| `already carries a different discount … --replace-existing` | conflicting discount | Only ladder UP (40%→50%); rerun with `--replace-existing` if correct | rerun |
| `coupon … exists but is not N% off` | canonical coupon mismatch | Fix `--coupon`/canonical coupon before applying | human |
| Stripe permission error (Coupons:Write) | key scope gap | Grant Coupons:Write on the write key (CLAUDE.md) | human, one-time |

## Auto-sendability after execution

Mirrors the cancel/refund skills. Once the coupon is **`applied`** (or already-applied) there is no remaining human action: `needs_action = false`, the ticket joins the auto-send bucket (verifier conditions still apply). The draft's present/past tense ("I've applied a 40% discount to your renewal…") must be TRUE at post/verify time — **execute before posting**. An **"Action executed"** note goes on the ticket (sidebar/MCP rails post it automatically; post the equivalent manually on CLI executions). If the script **refused**, the ticket stays a needs-action or escalation ticket per the table above.


# Bert Execution: Path 2 Retroactive Partial Refund (Stripe) — added 2026-08-27

Bert issues Path-2 partial refunds itself (`scripts/stripe_path2_refund.py`). **Use it starting immediately** for eligible Stripe annual Path-2 tickets. This is a **rate adjustment**, not a pro-rated refund and not a cancel: refund 40% (or 50% if they pushed back) of the last full-price renewal charge; the customer **keeps the subscription** for the rest of the paid year.

It does **not** do Path 1 / Path 3 / forever coupons — those remain `scripts/stripe_apply_coupon.py`. It is **annual-only**. Never pass a cancel flag.

## Pre-flight: check eligibility BEFORE running the script

Screen from context you already have — never post a draft promising a partial refund you haven't executed:

1. **Platform must be Stripe.** Apple/Google → migration reply, not this script.
2. **Plan must be annual.** Monthly → *Monthly Discount Requests*.
3. **Confirm what they were actually charged.** Read `Last Invoice Amount Charged` / `Last Invoice Coupon Applied` — not Base Plan / Active Coupon / Effective Price / Next Renewal Amount. If the last invoice already had 40% off, **no refund is owed**.
4. **Window:** within 30 days of the renewal charge. Obviously older? Path 3 (coupon on the next renewal), not this script. Near the line? The script is the authority — dry-run it; `--boundary-grace` only for day 30–31.
5. **Rate:** 40% is standard (`--percent` default). Ladder to 50% only if the customer pushed back. **50% is the ceiling.**
6. **Two or more subscribed accounts anywhere in the ticket → escalate, do not run the script or reply.**

## How to run it

1. **Dry-run first** (read-only, always safe): `python3 scripts/stripe_path2_refund.py <cus_…> --json` — targets the most recent succeeded charge; add `--charge-id <ch_…>` when the ticket is about a specific charge. The plan shows the charge, the computed refund (`$40.00` of `$99.99` at 40%), the 30-day window verdict, and that the subscription is kept.
2. **Apply**: `python3 scripts/stripe_path2_refund.py <cus_…> [--charge-id <ch_…>] [--percent 50] --apply --conversation-id <HS id> --json`. Same env gates and audit line as the other Stripe write skills.
3. There is **no cancel option**. Path 2 keeps access. If the customer also wants out, that is a different policy (full refund within window, or cancel-at-period-end past window).

## Refusals are eligibility answers — map them into the draft

The script refuses (exit 2) rather than guessing. **Each refusal tells you what the reply should say** — never leave a draft claiming a partial refund that was refused:

| Refusal | Meaning | Draft response | Remaining action |
|---|---|---|---|
| `PAST the 30-day Path-2 retroactive window` | too late for a difference refund | Path 3: 40% off the *next* renewal via `scripts/stripe_apply_coupon.py` | coupon script |
| past the window *but within grace* (day 30–31) | boundary case | Policy says be generous — rerun with `--boundary-grace` | rerun |
| `already carried a N% off coupon` | last invoice already discounted | No refund owed; confirm they already got the rate | none |
| `already carries a partial refund` | Path 2 already ran, or irregular history | Confirm the existing difference refund; promise nothing new | human if unclear |
| `already fully refunded` | charge is gone | Confirm the existing refund | none |
| `is DISPUTED` | active chargeback | No refund on top | human: accept dispute |
| `bills every month … annual-only` | monthly plan | *Monthly Discount Requests* | none (reply-only) |
| `not a subscription charge` / no invoice | gift or one-off | Not Path 2 | human review |
| charge not owned / `no succeeded charges` | wrong account or platform | Re-run the account/charge hunt | investigate |
| amount exceeds the $120 cap | anomalous charge | Escalate — never refund via skill | human |
| unsanctioned `--percent` | not 40 or 50 | Use 40 (default) or 50 (ladder only) | rerun |

## Auto-sendability after execution

Once the partial refund is **`applied`** there is no remaining human action: `needs_action = false`, the ticket joins the auto-send bucket (verifier conditions still apply). The draft's past tense ("I've refunded $40 of the $99.99 renewal…") must be TRUE at post/verify time — **execute before posting**. The reply includes the refunded amount, that they keep the year, and the 5–10 business days card timing. An **"Action executed"** note goes on the ticket. If the script **refused**, the ticket stays a needs-action or escalation ticket per the table above.

# Related Policies

- *Subscription & Billing Overview*
- *Refund Policy*
- *Apple/Google → Stripe Migration*
- *Monthly Discount Requests*
- *Discount Requests (Unsubscribed Users)*
- *Need-Based Complimentary Subscriptions*
- *Plan Switching*
