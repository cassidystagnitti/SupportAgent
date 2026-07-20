---
name: bert-disambiguate-10-percent
description: Use during the Bert morning review whenever a ticket references "Ten Percent Happier," Dan Harris, the podcast, ad-free episodes, live events, "heard on the show," or anything else that could mean either Happier Meditation or Dan Harris's 10% Happier — before forming a verdict or drafting a boundary reply.
---

# Bert — Disambiguate "Ten Percent Happier" (RESEARCH + VERDICT)

The brand "Ten Percent Happier" (spelled out) no longer exists — a customer writing it may mean Happier Meditation (us) or Dan Harris's 10% Happier. We have **no visibility into the 10% Happier side, and their side changes**: what the podcast, membership, app, or events look like *today* is a live question, not a memory. The policy doc and your training data tell you the boundary rules; only fresh research tells you what's currently true over there. Read `policies/happier-vs-10-percent-happier.md` alongside this skill.

## The verdict is built from three inputs — gather all three

1. **Extract the ambiguous references.** List every brand-ambiguous signal in the ticket: "Ten Percent Happier" / "TPH", Dan Harris, the podcast, ad-free feed, live events, "heard on the show," membership benefits we don't offer, legacy-era subscriptions. Note the account signal too (does this email have a Happier Meditation account? a legacy Ten-Percent-Happier-era subscription with *us*?).

2. **Research the current 10% Happier side (web search — run it even when the verdict looks obvious).** The searches answer two questions: *what is 10% Happier / Dan Harris currently doing*, and *does each thing the customer named exist on their side today?* Start from:
   - `Dan Harris 10% Happier podcast` (current name, feed status, any rebrand or shutdown)
   - `10% Happier app` / `10% Happier membership` (does a paid product still exist on their side, and what's in it)
   - One search per ticket-specific reference (e.g. `10% Happier live events`, or the "big change" the customer heard about)
   Prefer results dated within the last few months; note the date of whatever you rely on. If their side has rebranded, shut something down, or moved platforms since the policy was written, that finding usually *is* the answer to the ticket.

3. **Combine with the ticket + account signals** per the policy's Required Context section.

## Output: the verdict card

Give Cassidy (or the drafter) exactly this shape:

- **Verdict:** `us` / `them` / `mixed` (handle each half separately) / `still-ambiguous`.
- **Per-reference mapping:** each extracted reference → which product it points to, with the evidence (ticket signal + what the research found, with source and date).
- **If `them`:** the redirect target, *verified current by the research* — never point a customer at a 10% Happier channel you didn't just confirm exists.
- **If `still-ambiguous`:** the clarifying question to ask the customer. Never guess, and never send a boundary explanation that might be wrong in either direction.
- **Naming reminder for the draft:** our product is **"Happier Meditation"**; Dan Harris's brand is **"10% Happier"** (numerals, always) — never "Ten Percent Happier" spelled out, even when the customer wrote it that way. And the draft may only assert facts about the 10% Happier side that the research just confirmed as current.

## Capture-knowledge

If the research shows the policy doc is stale (their membership/events/podcast changed), update `policies/happier-vs-10-percent-happier.md` per the `bert-resolve` capture step — that's how this stops being a fresh research job every morning.
