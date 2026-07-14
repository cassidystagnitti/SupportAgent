# Non-Support Requests

# Summary

Covers inbound messages to the support mailbox that are not support requests at all — podcast or guest pitches, partnership proposals, press inquiries, influencer/collaboration outreach, cold sales pitches, and spam. These are not routed through triage/account/policy resolution like a customer issue; the goal is simply to close the loop appropriately. Standard categories (podcast, partnership, press, influencer/collab) get a polite one-paragraph decline and the conversation is closed. Cold sales and spam get tagged and closed with no reply at all. Genuine major-press or significant-partner inquiries are the one exception — those go to human review rather than an auto-sent decline, since a real press or partnership opportunity is a business decision, not a support decision.

# Trigger Conditions

- **Ticket signals:** message is not about the customer's own account, subscription, or app experience; sender is pitching something to Happier Meditation rather than asking for help; message reads as outreach, a proposal, or promotional content addressed to "the team," "marketing," or a named business contact rather than support
- **Account signals:** none required — these are typically not existing customers, and account lookup is not relevant to the response
- **Keywords / phrases:**
  - **Podcast/guest pitch:** "podcast," "guest," "interview," "would love to have someone from your team on," "feature you on our show"
  - **Partnership:** "partnership," "partner with us," "collaborate," "integration," "affiliate," "B2B," "corporate wellness program"
  - **Press:** "journalist," "writing an article," "press inquiry," "media request," "quote for a story," "on background," "deadline" (in a media context)
  - **Influencer/collab:** "influencer," "content creator," "sponsorship," "collab," "promo code for my audience," "UGC," "brand deal"
  - **Cold sales/spam:** unsolicited vendor pitches (SEO services, app growth tools, ad platforms, "grow your app's rating," etc.), generic mail-merge language, no genuine connection to Happier Meditation, suspicious links or generic "Dear Sir/Madam" openers

# Required Context

- [ ] Which category the message falls into: podcast/guest, partnership, press, influencer/collab, cold sales, or spam
- [ ] Whether the sender appears to represent a **major** outlet, publication, platform, or organization, or a **significant** potential partner (vs. a small/unknown outfit or individual)
- [ ] Whether the message contains any actual customer support question mixed in (changes handling — see Edge Cases)

# Policy / Correct Response

## Standard Case

**Podcast/guest pitch, partnership, press, influencer/collab:** Respond with a polite, one-paragraph decline and close the conversation. The decline should thank the sender for reaching out, briefly note that this isn't something we're pursuing through this channel (or at this time), and close warmly. Do not leave the door open with vague language like "we'll keep this in mind" unless that's genuinely true — keep it simple and final. Do not forward these to internal teams by default; that's the escalation path for the major/significant cases only (see below).

**Cold sales / spam:** Do not reply. Tag the conversation appropriately and close it. Engaging with cold outreach or spam (even to decline) tends to confirm the mailbox is monitored and invites more of it.

## Variations

- **Podcast or guest pitch:** One-paragraph decline, close. No forwarding needed unless the pitch is from a notably large or relevant outlet (see Escalation Triggers).
- **Partnership proposal (small business, unclear fit, generic B2B pitch):** One-paragraph decline, close.
- **Press inquiry (small or unclear outlet):** One-paragraph decline, close. Do not provide quotes, statements, or company information without human sign-off even for a "small" inquiry — the decline itself is safe to send, but never substitute a real answer to their question in place of the decline.
- **Influencer/collab pitch:** One-paragraph decline, close. Do not offer promo codes, free subscriptions, or affiliate terms — that's a business decision outside support's scope.
- **Cold sales pitch:** Tag and close. No reply.
- **Spam:** Tag and close. No reply.

## Edge Cases & Exceptions

- **Message mixes a pitch with a genuine support question** (e.g., a journalist who is also a paying subscriber asking about their account): Handle the support portion under the relevant policy; address the pitch portion with the standard decline language, either in the same reply or noting it's being routed separately. Don't let the pitch framing cause a real support need to be ignored.
- **Sender claims to be a major publication, well-known podcast, or significant potential partner:** Do not send the standard decline. This is an escalation — see Escalation Triggers below.
- **Ambiguous message — unclear if it's a partnership pitch or a support question:** If genuinely ambiguous, err toward treating it as a real inquiry and ask a clarifying question rather than assuming spam and going silent.
- **Sender pushes back after receiving a decline** (follow-up email insisting or escalating): A second polite decline is acceptable once. Repeated follow-ups after two declines should be flagged for human review rather than auto-replied to again.
- **Job inquiries or "how do I become a teacher on the app" messages:** These are not covered by this policy — see the existing `Other JobInquiryCheckTheWebsite` and `Other BecomeAMeditationTeacher` saved replies, which point to dedicated channels rather than a decline.
- **Customer wants to speak / correspond directly with a specific teacher or instructor** (e.g., a question about a teacher's guidance or content): We do **not** facilitate direct conversation between customers and teachers. Politely decline the direct-contact ask, and offer support-side help instead (answer what we can, or route genuine content feedback per *Feedback Policy*). Do not promise to pass a personal message to the teacher or arrange any 1:1 contact.

# Action Classification

## No Action Required (reply only)

- Standard podcast/guest, partnership, press, and influencer/collab pitches from unclear or small senders: reply-only with the one-paragraph decline, then close.

## Human Action Required

- **Action:** Tag and close with no reply.
- **When:** Cold sales pitch or spam.
- **Why AI can't do it alone:** Tagging conventions and mailbox close actions should follow the team's existing tagging taxonomy; confirm the correct tag exists before automating fully.

## Do Not Auto-Send Conditions

- Sender claims or appears to represent a major press outlet, well-known podcast/platform, or a significant potential business partner — do not auto-send a decline; route to human review (see Escalation Triggers)
- Message mixes a pitch with a real support/account issue — do not auto-send the pitch decline in isolation without also resolving or routing the support portion correctly
- Any ambiguity about whether the message is genuine outreach vs. spam vs. a real support question — when in doubt, do not silently close; flag for human review rather than guessing

## Escalation Triggers

- **Major-press inquiry** (recognizable national/major publication, large podcast, or platform with significant reach) → human review; do not auto-send a decline. This may be a real opportunity or a sensitive PR moment depending on the ask.
- **Significant-partner inquiry** (recognizable brand, large organization, or clear strategic fit) → human review; do not auto-send a decline.
- Aligns with *Escalation Policy*'s "sensitive PR risk" trigger — any inquiry that could become a public complaint or media moment if mishandled should be escalated rather than auto-resolved.

# Confidence Notes

- **High confidence areas:** Standard categories get a one-paragraph decline and close. Cold sales/spam get tagged and closed with no reply. Major-press or significant-partner inquiries require human review rather than an auto-sent decline.
- **Judgment call areas:** Where the line sits between "small/unclear" and "major/significant" for press and partnership senders — when uncertain, default to escalating rather than auto-declining, since the cost of a missed real opportunity is higher than an unnecessary human review.
- **Gaps:** No saved reply currently exists in `data/saved_replies.json` for podcast/guest, partnership, press, or influencer/collab declines, or for a cold-sales/spam classification. This is a **gap** — flag for the team to create saved replies for these categories. Until they exist, decline replies for standard cases should be drafted fresh from this policy's language rather than forced into an unrelated saved reply.

# Saved Reply Mapping

No saved reply in `data/saved_replies.json` matches podcast/guest pitches, partnerships, press inquiries, influencer/collab outreach, or cold sales/spam declines. This is a **gap** — flag for the team to create dedicated saved replies for these categories (a simple one-paragraph decline template per category would cover most cases). The two adjacent replies below exist for related-but-distinct inbound categories and should not be substituted for this policy's decline:

| Situation | Closest existing saved reply | Note |
|---|---|---|
| Someone asking how to become a meditation teacher on the app | `Other BecomeAMeditationTeacher` | Distinct from a partnership/collab pitch — use only for this specific ask |
| Job/employment inquiry | `Other JobInquiryCheckTheWebsite` | Distinct category — points to the careers page, not a decline |
| Message determined not to require any response at all | `Other NoQuestion` | Only if the message genuinely contains no actionable question after review — not a substitute for the standard pitch decline |

# Related Policies

- *Feedback Policy* (if a message is genuine user feedback rather than outreach/pitch — different conduit)
- *Escalation Policy* (sensitive PR risk trigger applies to major-press and significant-partner cases)
