# Feedback Policy

# Summary

Covers all inbound app feedback, content suggestions, feature requests, positive notes, and newsletter feedback. The support team acts as a conduit: the goal is to make the user feel heard and validated, then pass the feedback to the correct internal team (design, engineering, pedagogy/production, editorial, or marketing). Responses are short, match the user's tone and emotional register, and never promise timelines or specific delivery. Vitriolic or harassing messages are not engaged with — they are closed neutrally or escalated.

# Trigger Conditions

- **Ticket signals:** customer shares an opinion, suggestion, or reaction rather than asking for help; customer praises the app or a specific teacher; customer expresses frustration with a missing feature; customer requests a new feature, meditation type, teacher, topic, or language; customer asks about Android feature parity; customer asks for a web or desktop app; customer replies to the newsletter; customer sends a kind or encouraging note to the team
- **Account signals:** none required — feedback tickets are not account-dependent
- **Keywords / phrases:** "I wish," "would love," "feature request," "suggestion," "can you add," "when will you," "love the app," "thank you," "just wanted to say," "feedback," "idea," "would be great if," "any plans to," "missing feature," "not on Android yet," "desktop version," "newsletter"

# Required Context

- [ ] Type of feedback: feature request, content suggestion, positive/kind note, neutral/closing, newsletter, or negative
- [ ] Emotional tone of the user: warm and enthusiastic, frustrated, neutral, or hostile/vitriolic
- [ ] Which internal team the feedback is relevant to (see routing guide below)
- [ ] Whether the message contains hate speech, harassment, or personal attacks (escalation trigger)

# Policy / Correct Response

## Standard Case

**Our role is conduit, not resolver.** We do not build features, create content, or make product decisions. We acknowledge the feedback, validate the user's perspective, confirm it has been passed on, and close warmly. We do not promise timelines, roadmap inclusion, or specific outcomes.

**Match tone and length to the user.** A short, warm note gets a short, warm reply. A thoughtful paragraph of feedback gets a slightly fuller acknowledgment. Do not over-explain or add boilerplate that doesn't fit the register of the message.

**Routing by feedback type:**

| Feedback type | Internal team |
|---|---|
| Feature request (app design, UX, new functionality) | Design team |
| Feature request (engineering-specific: check-in answers, milestones, confetti, Android parity) | Engineering team |
| Content suggestion (new meditations, teachers, topics, series) | Pedagogy and production teams |
| Language support request | Pedagogy and production teams (with explanation — we don't have non-English teachers and translation doesn't work for meditation) |
| Web / desktop app request | Engineering team (with explanation — mobile-only currently, website has some resources) |
| Newsletter feedback | Editorial team |
| Positive note / praise | Full team (forward to brighten the day) |
| General or uncategorized feedback | Decision makers / general feedback review |

## Variations

- **Positive / kind note:** Acknowledge warmly, share that it was forwarded to the whole team. Use `Feedback ThanksForTheKindNote`.
- **General feature request with no specific category:** Use `Feedback FeatureRequest` — passes to design team with REQUEST filled in.
- **Content suggestion:** Use `Feedback ContentSuggestion` — passes to pedagogy and production with REQUEST filled in. Do **not** use this saved reply for teacher / content-tone feedback (see next bullet).
- **Teacher / content-tone feedback (taught 2026-08-28, Heidi-Jane #320283, Help Scout cid 3433427757):** Straight-up content feedback, not a request for other titles. Example: Pascal's Soft(er) Separation breakup videos felt "abnormally chipper" / alienating for someone who lost the love of their life — they still like Pascal. Make them feel understood. Pass it to pedagogy/production so we are really considering that the tone matches the topic. **Do not dump other grief titles as a deflection** (do not switch this to the *Grief and Loss Content* path or recommend Befriending Grief as a substitute). **Do not paste `Feedback ContentSuggestion`** (too chipper; signs off Best / first-name). Write a custom understood + pass-to-pedagogy reply; still log/forward internally. Draft for Cassidy unless she says send. Sign-off remains `Take care,` then `Happier Meditation Support Team`. Never Cass/Cassidy/first name. Never Best wishes.
- **Language request:** Use `Feedback FeatureRequestOtherLanguages` — explains the constraint (no non-English teachers, translation doesn't work for meditation) and closes warmly.
- **Web/desktop request:** Use `Feedback FeatureRequestWebApp` — explains mobile-only, links to website resources.
- **Android parity:** Use `Feedback LaunchNotOnAndroidYet` — confirms engineering is working on it, no timeline, they'll hear about it when it's ready.
- **Newsletter feedback:** Use `Feedback NewsletterFeedback` — passes to editorial team.
- **Feedback that doesn't fit any specific category but needs acknowledgment:** Use `Feedback PassedOn` — generic "I hear you, forwarded to decision makers."
- **Neutral / negative feedback, conversation is ending, no escalation needed:** Use `Feedback NeutralResponseConversationEnded` — brief, professional, no warmth push.
- **Marketing wants to use a customer quote:** Use `Feedback QuoteRequestPositiveFeedback FILLIN` — fill in the customer's quote, ask permission to use it.

## Edge Cases & Exceptions

- **Feedback combined with a support request** (e.g., "I love the app but I can't log in"): Handle the support issue first under the appropriate policy; acknowledge the feedback briefly at the end. Do not file under feedback alone.
- **Frustrated but not hostile:** Still use the standard feedback path — validate the frustration, pass it on, don't escalate. Match the warmer end of the tone scale.
- **Customer follows up asking if their feedback was acted on:** There is no feedback status tracking available to support. Acknowledge that feedback is reviewed in planning cycles, but we don't have individual update visibility. Do not fabricate status.
- **Customer requests a feature that already exists:** Redirect to the relevant FAQ or help resource. This becomes a tech support ticket, not a feedback ticket.
- **Library feels stale / "the same sit on repeat" (taught 2026-08-28, Judi #320268):** Hear them. If newer work isn't finding them, that's on presentation. Name only actually-new titles (`created_at`, not a misleading 2026 `release_date` on old work). Invite specifics so pedagogy can use them in planning. Do **not** Path-2 a 40% refund just because they complained unless they ask to cancel (see *Renewal Discount Requests*).

# Action Classification

## No Action Required (reply only)

All standard feedback tickets are reply-only. No account changes, billing actions, or engineering tasks are initiated by support for feedback. The "action" of passing feedback to internal teams is implicit in the reply — no separate internal ticket is created unless explicitly flagged by a senior team member.

## Human Action Required

- **Escalation for hate, harassment, or personal attacks:** Do not reply. Escalate to support leadership. See Escalation Triggers below.
- **Marketing quote request:** Requires human to confirm with marketing before sending `Feedback QuoteRequestPositiveFeedback FILLIN`. Do not send without confirmation.
- **Teacher / content-tone feedback on grief or emotionally intense topics (taught 2026-08-28, Heidi-Jane #320283):** Draft for Cassidy. Do not send until she says send.

## Do Not Auto-Send Conditions

- Message contains any hostile, hateful, or harassing language — requires human review before any response
- Feedback is emotionally intense (deeply distressed, grieving, in crisis) — tone calibration requires human judgment
- Marketing quote request — requires human confirmation before sending
- Customer's feedback about a specific named team member or teacher: the standard thank-and-log acknowledgment is auto-sendable as of 2026-07-21 (the feedback itself is still logged/forwarded internally). ONLY if the feedback is sensitive — alleging misconduct, harm, or anything beyond content/style preference — forward to senior support before replying.
- **Teacher / content-tone feedback on emotionally intense or grief-adjacent topics (taught 2026-08-28, Heidi-Jane #320283):** Draft for Cassidy unless she says send. The 2026-07-21 teacher-feedback auto-send rule does **not** cover grief/breakup tone complaints — even when they are content/style preference, not misconduct. This aligns with the top-level Solo vs Ping guidance (CLAUDE.md, decision 2026-09-02): really high-touch emotional tickets hold for Cassidy.
- **B2B / partnership / enterprise feedback or inquiries:** Hold for Cassidy review. See *Non-Support Requests* for routing; B2B/org/enterprise tickets are a top-level hold-back (CLAUDE.md, decision 2026-09-02).

## Escalation Triggers

- **Hate speech, harassment, or personal attacks toward the team or any individual:** Escalate to support leadership immediately. Do not engage, do not reply, do not send `Feedback NeutralResponseConversationEnded` without leadership sign-off.
- **Customer appears to be in emotional distress or crisis** (not just frustrated): Escalate — this is outside standard support scope.

# Confidence Notes

- **High confidence areas:** Routing by feedback type. The "conduit not resolver" framing. Tone-matching as a core behavior. `Feedback NeutralResponseConversationEnded` for ending neutral/negative threads.
- **Judgment call areas:** Distinguishing frustrated-but-standard from hostile/vitriolic. Knowing when to combine a feedback reply with a support reply vs. treating them as separate threads.
- **Gaps:**
  - No feedback status tracking — if customers follow up asking for updates, we have no information to give them.
  - No defined policy for repeated feedback from the same user (e.g., customer emails monthly about the same feature request).
  - Marketing quote request flow is not fully defined — confirm approval process with team.

# Saved Reply Mapping

## Positive and kind notes

| User state | Saved Reply |
|---|---|
| Customer sends praise, gratitude, or an encouraging note | `Feedback ThanksForTheKindNote` |
| Marketing wants to use a positive customer quote | `Feedback QuoteRequestPositiveFeedback FILLIN` |

## Feature requests

| User state | Saved Reply | Notes |
|---|---|---|
| General app feature request | `Feedback FeatureRequest` | Fill in REQUEST with the specific feature |
| Request to see check-in or reflection practice answers | `Feedback FeatureRequestSeeCheckInAnswers` | Engineering-specific path |
| Feedback about milestones or confetti feature | `Feedback FeatureRequestMilestonesConfettiIssues` | Engineering-specific; acknowledges ongoing changes |
| Android feature parity ("when is X coming to Android?") | `Feedback LaunchNotOnAndroidYet` | No timeline; confirms engineering is working on it |
| Request for web or desktop app | `Feedback FeatureRequestWebApp` | Explains mobile-only; links to website resources |
| Request for non-English language support | `Feedback FeatureRequestOtherLanguages` | Explains constraint; no other saved reply appropriate |

## Content suggestions

| User state | Saved Reply | Notes |
|---|---|---|
| Suggestion for new meditations, teachers, topics, or series | `Feedback ContentSuggestion` | Fill in REQUEST with the specific suggestion; routes to pedagogy and production |
| Teacher / content-tone feedback (tone doesn't match the topic; e.g. too chipper for grief/breakup) | Do **not** paste `Feedback ContentSuggestion` | Custom understood + pass-to-pedagogy reply. Log/forward internally. Draft for Cassidy unless she says send. Emotionally intense/grief tone still needs human (Cassidy) review before send. Sign-off: `Take care,` then `Happier Meditation Support Team`. Never Cass/Cassidy/first name. Never Best wishes. Taught 2026-08-28, Heidi-Jane #320283. |
| Library feels like the same sit on repeat | Do **not** dump a title list from `Feedback ContentSuggestion` or grief snippets | Hear them; name only actually-new titles by `created_at` (not a misleading 2026 `release_date` on old work); invite specifics for planning. Not a Path-2 40% refund unless they ask to cancel. Taught 2026-08-28, Judi #320268. |

## Newsletter

| User state | Saved Reply |
|---|---|
| Feedback about the Happier Meditation newsletter | `Feedback NewsletterFeedback` |

## General and neutral

| User state | Saved Reply | Notes |
|---|---|---|
| General or uncategorized feedback, no specific reply fits | `Feedback PassedOn` | Catch-all; routes to decision makers |
| Neutral or negative feedback; conversation is ending; no escalation needed | `Feedback NeutralResponseConversationEnded` | Brief and professional; do not add warmth that doesn't fit |

# Related Policies

- *Escalation Policy* (hate, harassment, or crisis escalation path)
- *Tech Support* (if feedback includes a support issue, resolve that first)
- *Renewal Discount Requests* (do not Path-2 a 40% refund just because they complained about the library unless they ask to cancel)
- *Grief and Loss Content* (for customers *asking* for grief/death content — not for tone feedback on a specific teacher or course; do not use that path as a deflection)

## Draft Language: Avoid Meta-Commentary About Honesty (added 2026-07-22)

Never write phrases like "I want to be straight with you rather than guess," "I don't want to make something up," or similar meta-commentary about the act of being honest. This reads as AI-generated filler and draws attention to itself rather than just being direct. Simply state what we know and don't know in plain language, without narrating the decision to be truthful. E.g. instead of "I want to be straight with you rather than guess — I don't have visibility into X," just write "I don't have visibility into X, so I can't speak to why that's changed."
