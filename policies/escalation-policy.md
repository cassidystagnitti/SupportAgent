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

## What Not to Escalate

Routine situations that have clear policy coverage should be handled with a draft reply even if they are sensitive:
- Standard refund requests within policy
- Cancellation requests
- Apple/Google subscription questions (answer per policy; we cannot take action on their subscriptions)
- Subscription pricing or discount questions
- Account lookup failures (follow the No Account Found policy)

## Draft Language: Never Reference a Pending Internal Review

Every AI-drafted reply already passes through human review before it is sent — the support teammate reviewing/editing the draft in Help Scout *is* that review; there is no separate later review step. Do not draft customer-facing language that implies otherwise, e.g.:

- "I've flagged this for a member of our team to double-check."
- "I'm escalating this internally and will follow up shortly."
- "Someone will review this and get back to you."

This creates a false expectation of a second review cycle that has, in effect, already happened by the time the draft reaches the customer. If a ticket genuinely can't be resolved without human judgment, either escalate properly (`escalate: true`, no draft — see above) so a human handles it directly, or draft the best supportable answer / a clarifying question. Never draft a stalling reply that promises a future internal check that is actually just this same draft-review step already in progress.
