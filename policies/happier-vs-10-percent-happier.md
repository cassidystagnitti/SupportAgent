# Happier Meditation vs. 10% Happier (Dan Harris) — Brand Boundary & Naming

# Summary

Happier Meditation (us) and **10% Happier** (Dan Harris's brand — his podcast and related products) are separate products with shared history, and customers regularly conflate them. The old brand name **"Ten Percent Happier" (spelled out) no longer exists** — when a customer writes "Ten Percent Happier" they may mean either Happier Meditation or Dan Harris's 10% Happier, so the reference must be disambiguated before answering. In our own replies we never use the spelled-out form: Dan Harris's brand is always written **"10% Happier"** (numerals), and our product is always **"Happier Meditation."** We cannot see or act on anything on the 10% Happier side (podcast feeds, ad-free podcast subscriptions, their app or events); those requests get a polite boundary explanation and redirection.

# Trigger Conditions

- **Ticket signals:** customer references the podcast, Dan Harris, an ad-free podcast subscription, a feature they "heard about on the show," live events tied to the podcast, or anything from the "Ten Percent Happier" era; customer asks why their subscription doesn't include a podcast benefit; customer asks about content or features we don't have
- **Account signals:** none required — confusion occurs for subscribers and non-subscribers alike; a subscription with us plus a complaint about podcast benefits is a strong conflation signal
- **Keywords / phrases:** "Ten Percent Happier," "10% Happier," "TPH," "Dan Harris," "the podcast," "ad-free episodes," "heard on the show," "live events," "upcoming events"

# Required Context

- [ ] Which product does the customer actually mean? Signals: podcast/episodes/Dan Harris interviews → 10% Happier; meditations, courses, sleep content, our app's features → Happier Meditation
- [ ] Does the ticket mix both (e.g., a Happier Meditation billing question plus a podcast question)? Handle each half separately.
- [ ] If ambiguous after reading the full thread: run the `bert-disambiguate-10-percent` skill (web-researches what Dan Harris / 10% Happier is currently doing and combines it with the ticket signals). If still ambiguous after that, ask the customer a clarifying question rather than guessing.

# Policy / Correct Response

## Naming rules (customer-facing, hard rules)

- Our product: **"Happier Meditation"** — never "Happier app" alone in a way that could read as the podcast's brand, never "Ten Percent Happier."
- Dan Harris's brand: **"10% Happier"** — always numerals. **Never write "Ten Percent Happier" spelled out** in any customer-facing reply; that brand name no longer exists.

## Standard Case

Customer asks about a 10% Happier thing (podcast, ad-free feed, podcast subscription, Dan Harris content/events) in our mailbox:

- Explain briefly and warmly that Happier Meditation and 10% Happier (Dan Harris's podcast/brand) are separate products run by different teams, and that we don't have visibility into or control over the 10% Happier side.
- Redirect them to 10% Happier's own support/contact channels for that portion of their question.
- Do not speculate about 10% Happier's features, pricing, feeds, or events.

## Variations

- **Mixed ticket** (our billing/app issue + podcast question): resolve our portion under the relevant policy; add the boundary explanation for the podcast portion in the same reply.
- **Customer asks where the podcast is / why it's not in our app:** use the existing `Engagement WheresThePodcast` saved reply as the base.
- **Customer references a feature "from the show" or "live events" we don't have:** clarify the product boundary, confirm what Happier Meditation actually offers, and log a feature-request per *Feedback Policy* if they want it in our app.

## Edge Cases & Exceptions

- **Legacy references:** longtime customers may have genuinely subscribed in the "Ten Percent Happier" app era. References to the old name in their history are about *our* product lineage — check account data before assuming they mean Dan Harris's current brand.
- **Cannot determine which product they mean:** ask a short clarifying question. Do not auto-send a boundary explanation that might be wrong in either direction.

# Action Classification

## No Action Required (reply only)

- Clear podcast/10% Happier questions: boundary explanation + redirect, reply-only.
- Clear conflation with an easy correction (e.g., "do you have live events?" → no, that's not a Happier Meditation feature): reply-only.

## Human Action Required

- None specific to this policy — actions belong to whatever underlying policy the *our-product* portion of the ticket falls under.

## Do Not Auto-Send Conditions

- The reply would use the spelled-out phrase "Ten Percent Happier" (naming-rule violation — rewrite with "10% Happier" / "Happier Meditation")
- It is genuinely ambiguous whether the customer means Happier Meditation or 10% Happier — clarify first
- The draft makes any claim about 10% Happier's current offerings, feeds, pricing, or events — we don't have visibility into those

## Escalation Triggers

- None specific — standard *Escalation Policy* triggers apply.

# Confidence Notes

- **High confidence areas:** the naming rule (10% Happier, numerals, always) and the boundary rule (we can't see or act on the 10% Happier side).
- **Judgment call areas:** disambiguating what the customer means when they say "Ten Percent Happier" — use the `bert-disambiguate-10-percent` skill (added 2026-07-20), which checks Dan Harris's / 10% Happier's current activity and combines it with thread + account signals.
- **Gaps:** no saved reply exists for the general product-boundary explanation (only the podcast-location one). Flag for a dedicated saved reply.

# Saved Reply Mapping

| Situation | Saved reply | Note |
|---|---|---|
| Customer asks where the podcast is / podcast not in our app | `Engagement WheresThePodcast` | Base reply for podcast-location confusion |
| Cancel/refund request that turns out to be a 10% Happier subscription | `CancelRefund 10%HappierSub` | Note it already uses the correct numerals branding |
| Stripe-era Dan (10% Happier) subscription refund boundary | `CancelRefund StripeDanNoProratedRefund` | Legacy-billing adjacent case |
| General product-boundary explanation (non-podcast: events, features, content) | — **gap** | No saved reply exists; draft fresh from this policy until one is created |

# Related Policies

- *Feedback Policy* (feature requests for things customers wish we had from "the show")
- *Non-Support Requests* (podcast guest pitches etc. — different category)
- *Subscription & Billing Overview* (legacy Ten-Percent-Happier-era subscriptions on our side)
