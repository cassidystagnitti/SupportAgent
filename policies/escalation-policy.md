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
