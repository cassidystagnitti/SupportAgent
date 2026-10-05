# Complete Customer Replies

# Summary

Never send a Help Scout customer reply that only answers part of their question. Every customer reply must respond to everything the customer asked. If you cannot answer the whole ask, hold until you can (or send one complete follow-up once the missing answer is known). Taught 2026-10-05 on Rick #322556.

# Trigger Conditions

- **Ticket signals:** customer asks more than one question; customer combines a request with a follow-up ask; multi-part messages; any ticket where a draft would leave an asked question unanswered
- **Account signals:** none required — this applies to every Help Scout customer reply
- **Keywords / phrases:** any multi-part ask (questions joined by "also," "and," numbered lists, separate paragraphs of asks)

# Required Context

- [ ] List every distinct question or request in the customer's latest message (and any still-unanswered asks earlier in the thread that this reply is meant to cover)
- [ ] Confirm the draft addresses each one, or that we are holding because at least one answer is still missing

# Policy / Correct Response

## Standard Case (taught 2026-10-05 — Rick #322556)

**Never send a customer reply that only answers part of their question.** Every Help Scout customer reply must respond to everything the customer asked.

If you cannot answer the whole ask yet:
1. **Hold** — do not send a partial reply.
2. Once the missing answer is known, send **one complete follow-up** that covers the full ask (including anything you already knew).

Do not send a first reply that covers only the easy parts and promise a later answer for the rest, unless policy for that topic explicitly requires a staged investigation reply (e.g. No Account Found). Even then, the investigation reply itself must fully cover what that step is supposed to communicate — it is not a license to ignore other asks in the same message.

## Variations

- **Multi-part question, all answers known:** Answer every part in one reply.
- **Multi-part question, one part blocked:** Hold the whole send until you can answer every part, then send one complete reply.
- **Follow-up after a hold:** One complete reply that covers the full original ask — do not leave prior unanswered parts hanging.

## Edge Cases & Exceptions

- **Thanks-only / close_no_reply:** If there is nothing to answer, close per *Thanks-Only Follow-Ups* — this policy does not require inventing a reply.
- **True escalation with no draft:** When escalation policy says no customer draft (human owns the reply), do not send a partial AI reply either.
- **Staged investigation templates** (e.g. No Account Found): Allowed only as documented for that step; still address every ask that step can address, and do not drop unrelated asks from the same message.

# Action Classification

- **No Action Required:** N/A — this is a reply-completeness rule, not a Stripe/admin action.
- **Human Action Required:** Hold sending when any part of the ask is unanswered; complete research/actions first, then send one full reply.
- **Do Not Auto-Send Conditions:** Any draft that leaves a customer question unanswered must not auto-send — hold or rewrite until complete.
- **Escalation Triggers:** Escalate only if answering the full ask requires human judgment under *Escalation Policy* / Solo vs Ping; do not escalate merely to send a partial reply.

# Confidence Notes

- **High confidence:** Customer listed multiple clear questions; draft omits one → hold or rewrite.
- **Judgment:** Whether a phrase is a separate ask vs. background — when unsure, treat it as an ask and answer it.
- **Gaps:** none

# Saved Reply Mapping

No saved reply is dedicated to this rule. Completeness applies on top of whatever topic-specific saved reply or custom draft is used.

| Situation | Saved Reply | Notes |
|---|---|---|
| Any multi-part customer ask | (topic-specific reply / custom draft) | Reply must cover every asked part; hold if it cannot |

# Related Policies

- *Escalation Policy* (hold / no partial stalling drafts)
- *Thanks-Only Follow-Ups* (when no reply is needed)
- *No Account Found Troubleshooting* (staged investigation replies)
