# Downloads / Offline Meditations

# Summary

Covers tickets about downloading meditations for offline playback. The ability to download meditations was **temporarily removed** in the new (v2) app. It is being restored, and we will notify users when that happens — but there is no specific date to give. Previously downloaded content is inaccessible during this window. Support acknowledges the gap, commits to notifying the customer when downloads return, and does not speculate about timelines or about whether previously downloaded files can be recovered. This is the same issue tracked as Entry 4 in `known-bugs.md`; that doc's entry summarizes the status, this doc is the full policy.

# Trigger Conditions

- **Ticket signals:** customer asks how to download a meditation for offline use; customer reports the download button or feature is missing/gone; customer says previously downloaded meditations are no longer playable or no longer appear; customer asks why offline mode disappeared after updating; customer threatens to cancel or unsubscribe because they need downloads (e.g., for travel, flights, gym, poor signal areas)
- **Account signals:** none required — this affects all users of the new (v2) app regardless of subscription state, though it is only relevant to subscribers since downloads are a subscriber feature
- **Keywords / phrases:** "download," "offline," "airplane mode," "no wifi," "no signal," "can't download anymore," "downloads are gone," "used to be able to download," "save for later," "download button missing"

# Required Context

- [ ] Platform and app version (new v2 app vs. legacy app, if the customer hasn't updated)
- [ ] Whether the customer has ever subscribed (downloads are a subscriber-only feature)
- [ ] Whether the ticket includes a churn/cancellation threat tied to this issue
- [ ] Whether the customer is asking about *new* downloads or about *previously downloaded* content that's now inaccessible

# Policy / Correct Response

## Standard Case

Acknowledge that downloading meditations for offline use was temporarily removed in the new app. Let the customer know it's being restored and that **we will notify users when it's restored** — this commitment is safe to make. Do **not** give a specific date, week, or month, and do not imply a timeframe (e.g., "soon," "in the next update") beyond "coming back."

Previously downloaded meditations are not accessible during this window. Do not speculate about whether existing downloads will reappear, need to be re-downloaded, or are recoverable in any way — that has not been determined. Stick to: downloads are temporarily unavailable, they're coming back, we'll notify the customer.

## Variations

- **Churn threat** ("I'm going to cancel if I can't download," "this is a dealbreaker"): Acknowledge the frustration directly, restate the notify-when-restored commitment, and do not push back on the threat or over-apologize. This response is **not auto-sendable** — `needs_action = false` (no backend action required) but `auto_sendable = false` (human should review tone and decide whether a retention gesture is warranted before sending). See *Cancellation Policy* if the customer follows through with an explicit cancellation request — that becomes a separate, standard cancellation flow.
- **Never-subscribed user asking about downloads:** Downloads are a subscriber feature. Explain politely that offline downloads are part of the paid subscription (and are additionally unavailable right now for everyone during this restoration window), and point them to subscribing if they're interested. Do not frame this as only a "coming back soon" issue for a free user — lead with the feature being subscriber-only.
- **Customer asks specifically "when" or pushes for a date:** Reiterate that there's no specific date to share yet, and that they'll be notified as soon as it's back. Do not invent a window to placate them.

## Edge Cases & Exceptions

- **Customer reports this as if it's a bug/glitch rather than a known removal:** Clarify it's a temporary, intentional removal during the new app transition, not a bug — same customer-facing framing either way (coming back, will notify).
- **Customer combines this with a refund or cancellation request tied to lost access to paid content:** Handle the billing/cancellation portion under *Cancellation Policy* or *Refund Policy*; do not resolve the billing action from this doc alone — flag for human review per Do Not Auto-Send Conditions below.
- **Customer asks if they can get downloads on the legacy/old app instead:** Do not suggest downgrading or switching app versions as a workaround — no such guidance has been confirmed. Stick to the standard response and flag for human review if they push on this.
- **Customer asks about downloading the app itself (not meditations for offline use):** This is a different request — see app installation links, not this policy.

# Action Classification

## No Action Required (reply only)

- Standard "where did downloads go" / "how do I download" inquiries with no churn threat: reply-only, no backend action.
- Never-subscribed user asking about downloads: reply-only, explain subscriber-feature + temporary unavailability.

## Human Action Required

None — there is no backend or account action available to restore downloads or expedite the fix. This is purely a product/engineering timeline outside support's control.

## Do Not Auto-Send Conditions

- Any churn or cancellation threat tied to missing downloads — `auto_sendable = false`, human review required even though no backend action is needed
- Ticket combines this issue with an active refund or cancellation request — route the billing portion through *Refund Policy* / *Cancellation Policy* and flag for human review before sending anything
- Customer pushes hard for a specific ETA and the drafted reply is at risk of implying one — flag for human review rather than risk a fabricated date going out
- Customer reports severe impact (e.g., "I paid for annual specifically for offline access and use it every day for flights") — acknowledge but flag for human review; may warrant a goodwill gesture beyond standard policy

## Escalation Triggers

- Customer explicitly disputes the "temporary" framing and claims this was permanently removed / demands confirmation it's coming back — escalate if reassurance per this policy doesn't resolve it
- Any threat to leave a public review or contact press/media over this issue — escalate per *Escalation Policy* (sensitive PR risk)

# Confidence Notes

- **High confidence areas:** Downloads are temporarily unavailable in the new app; they are being restored; we will notify users when restored; no ETA should ever be given; previously downloaded content is inaccessible during this window.
- **Judgment call areas:** How much empathy to lead with on a churn-threat ticket before the human reviewer takes over. Whether a given ticket's "impact" language rises to the level of flagging for a goodwill gesture.
- **Gaps:** No saved reply currently exists for this exact issue (temporary downloads removal + notify-when-restored commitment). This is a **gap** — flag for the team to create a dedicated saved reply. No confirmed guidance on whether previously downloaded files will need to be re-downloaded once the feature returns; do not speculate either way until this doc is updated.

# Saved Reply Mapping

No saved reply in `data/saved_replies.json` directly matches "downloads temporarily removed, will notify when restored." This is a **gap** — flag for the team. In the meantime, draft a personalized reply from this policy's Standard Case language rather than forcing an unrelated saved reply. The following existing replies are adjacent but not a direct match — use only as tone/structure references, not as-is:

| Situation | Closest existing saved reply | Note |
|---|---|---|
| Customer needs the app installed to access any content (not the same as offline download capability) | `Engagement DownloadAppDirectly SNIPPET` | This is about installing the app itself, not offline meditation downloads — do not use for this issue; listed only to rule it out |
| General uncategorized feedback tied to this feature being missed | `Feedback PassedOn` | Only appropriate if the ticket is pure sentiment with no expectation of a direct answer about downloads |
| Never-subscribed user asking how to subscribe (after downloads are explained as subscriber-only) | `Get HowtoSubscribe` | Use as a follow-on if they express interest in subscribing |

# Related Policies

- *Known Bugs & Current Product Status* (Entry 4 — summary and status pointer back to this doc)
- *Cancellation Policy* (if a churn threat becomes an actual cancellation request)
- *Refund Policy* (if combined with a refund request)
- *Feedback Policy* (if the ticket is purely sentiment about the missing feature with no support ask)
- *Escalation Policy* (sensitive PR risk if press/public threats are involved)
