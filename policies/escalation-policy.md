# Escalation Policy

## When to Escalate

Set `escalate: true` and `draft_reply: null` for any of the following situations. Do not draft a reply — tag the ticket for human review.

### Mandatory Escalation Triggers

- **Legal threats**: Customer mentions legal action, a lawyer, small claims court, or "reporting" to a consumer agency (BBB, FTC, App Store reviews used as leverage, etc.)
- **Chargeback / dispute**: Customer has filed or is threatening a chargeback or credit card dispute
- **Fraud or account security**: Suspected unauthorized account access, identity issues, or requests that could expose another customer's data
- **Multiple subscribed accounts**: More than one active subscription found across the emails in this ticket (handled automatically by the pipeline — escalate regardless of ticket content)
- **Extreme distress**: Customer expresses severe emotional distress, crisis language, or is clearly in a very vulnerable state
- **Sensitive PR risk**: Ticket could become a public complaint or social media issue if handled poorly (e.g., public figure, journalist, or customer explicitly referencing a public platform)
- **Teams / org seat-reduction**: customer wants to cut seats on a Teams Annual org plan (keep only the billing owner's membership, drop other members, change Stripe quantity). Rare; ALWAYS escalate to a human. Do not draft a customer reply. Do not run individual cancel (that would cancel the whole org plan). Do not change Stripe quantity yourself. Leave no customer draft; move on. (taught 2026-08-27, #320031)

### Use Judgment to Escalate

- Situations that require coordination with another internal team (e.g., engineering, finance)
- Edge cases not covered by any policy document where guessing would be risky
- Any ticket where you have low confidence and the stakes are high
- **Compensation via subscription extension**: customer asks for their subscription to be extended because access was blocked (login/account issue, outage). This is possible but never standard — always escalate; a human decides case-by-case. Never promise or confirm an extension in a draft (confirmed 2026-07-20).

## What Happens on Escalation

When `escalate: true`:
- The pipeline adds the **"escalation"** tag to the Help Scout conversation
- **No draft reply is created** — a human agent reviews and responds directly
- An internal note is added with your classification reasoning and `escalate_reason`

**Escalation = handoff to a human support agent.** An escalated ticket leaves Bert's queue entirely: the support agent owns the reply, the resolution, and any customer promises. This is one of the three standing buckets of the morning review (see `.claude/skills/bert-morning-review/SKILL.md`): auto-send (no note, not escalated — the majority), needs-action (internal "Actions needed" note for a human step), and escalated (support agent owns it). Escalations are always discussed with Cassidy during the review before the morning run is considered settled; the verifier only runs over the auto-send bucket after notes and escalations are in place.

## What Not to Escalate

Routine situations that have clear policy coverage should be handled with a draft reply even if they are sensitive:
- Standard refund requests within policy
- Cancellation requests on an individual personal plan (not Teams/org seat-reduction — that always escalates; see above)
- Apple/Google subscription questions (answer per policy; we cannot take action on their subscriptions)
- Subscription pricing or discount questions
- Account lookup failures (follow the No Account Found policy)

## Draft Language: Never Reference a Pending Internal Review

Every AI-drafted reply already passes through human review before it is sent — the support teammate reviewing/editing the draft in Help Scout *is* that review; there is no separate later review step. Do not draft customer-facing language that implies otherwise, e.g.:

- "I've flagged this for a member of our team to double-check."
- "I'm escalating this internally and will follow up shortly."
- "Someone will review this and get back to you."

This creates a false expectation of a second review cycle that has, in effect, already happened by the time the draft reaches the customer. If a ticket genuinely can't be resolved without human judgment, either escalate properly (`escalate: true`, no draft — see above) so a human handles it directly, or draft the best supportable answer / a clarifying question. Never draft a stalling reply that promises a future internal check that is actually just this same draft-review step already in progress.

## Draft Language: Avoid "Genuine" / "Genuinely"

Do not use the words "genuine" or "genuinely" in customer-facing drafts (e.g. "a genuine bug," "genuinely frustrating"). It reads as stilted/AI-generated filler. State the fact plainly instead — e.g. "you've found a bug we hadn't caught yet" rather than "this is a genuine bug." This applies across all policy areas, not just escalations.
