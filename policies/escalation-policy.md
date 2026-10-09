# Escalation Policy

## When to Escalate

Set `escalate: true` and `draft_reply: null` for any of the following situations. Do not draft a reply — tag the ticket for human review.

**NOTE:** This policy covers true escalations (no draft, tag for human). For the broader "Solo vs Ping Cassidy" framework — which tickets can be sent autonomously vs. which should be drafted and held for Cassidy's review — see the top-level guidance in CLAUDE.md (decision 2026-09-02). Key hold-backs: truly no clue, Google Play subscriptions, B2B/org/enterprise, and really high-touch emotional tickets.

### Mandatory Escalation Triggers

- **Legal threats**: Customer mentions legal action, a lawyer, small claims court, or "reporting" to a consumer agency (BBB, FTC, App Store reviews used as leverage, etc.)
- **Chargeback / dispute**: Customer has filed or is threatening a chargeback or credit card dispute on a charge we can find. **Exception (solo, 2026-10-09):** if we only see an expired subscription and no charge that matches, send the adjusted `CancelRefund PlatformUnclearRefund` (*Refund Policy*) and close.
- **Fraud or account security**: Suspected unauthorized account access, identity issues, or requests that could expose another customer's data. (Unsolicited security / bug-bounty "vulnerability reports" from strangers are NOT this — mark spam; see *Non-Support Requests*.)
- **Multiple subscribed accounts**: More than one active subscription found across the emails in this ticket (handled automatically by the pipeline — escalate regardless of ticket content). **Solo exceptions (2026-10-09):** one account with a Stripe + Apple sub double charge (*Refund Policy*), and a Sign in with Apple / Hide My Email second account holding an Apple purchase (*Login Issues*).
- **Extreme distress**: Customer expresses severe emotional distress, crisis language, or is clearly in a very vulnerable state
- **Sensitive PR risk**: Ticket could become a public complaint or social media issue if handled poorly (e.g., public figure, journalist, or customer explicitly referencing a public platform)
- **Teams / org seat-reduction** (cut the paid seat count / change Stripe quantity): Rare; ALWAYS escalate to a human. Do not run individual cancel (that would cancel the whole org plan). Do not change Stripe quantity yourself. (taught 2026-08-27, #320031)
- **Teams / org team-member removal (taught 2026-10-09 — Kristen #322843):** the org admin asks us to remove named members but not to reduce seats. Bert can't remove members (admin only) — leave one internal note for Cassidy listing the member emails, Stripe sub id and seat count, and release the claim (no customer draft needed). **Once Cassidy confirms she removed them, the reply is pre-approved — send it and close:** "We've removed <members> from your team. Your plan still includes <N> seats, so you now have <k> open seats you can give to new team members anytime. If you'd rather reduce your plan to fewer seats, just let us know." Never add the members' emails to the admin's Help Scout profile (they belong to other people).

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
