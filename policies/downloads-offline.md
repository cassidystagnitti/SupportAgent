# Downloads / Offline Meditations

# Summary

Covers tickets about downloading meditations for offline playback. **RESOLVED 2026-07-21:** the known issue that made downloads unavailable on the new (v2) Android app is fixed as of Android app version **2026.07.21**. Once a customer updates to the latest version from the Google Play Store, their **previously downloaded meditations are restored** and they can **download new content again**. The correct reply for almost every downloads ticket is now the good-news reply: it's fixed, update the app, prior downloads come back with the update. This also fulfills the "we'll notify you once downloads are working again" commitment made on earlier tickets. This is the same issue tracked as Entry 4 in `known-bugs.md`.

History, for context on older threads: the v2 Android app shipped with an unintended bug (never a removal, never intentional) that made downloads unavailable and hid previously downloaded content, roughly 2026-07-02 → 2026-07-21. During that window support acknowledged the bug, gave no ETA, and promised to notify customers when downloads were restored. That notification moment is now.

# Trigger Conditions

- **Ticket signals:** customer asks how to download a meditation for offline use; customer reports the download button or feature is missing/gone; customer says previously downloaded meditations are no longer playable or no longer appear; customer asks why offline mode disappeared after updating; customer threatens to cancel because they need downloads; customer replies to an earlier thread asking whether downloads are back yet
- **Account signals:** none required — the bug affected all users of the v2 Android app, though downloads are a subscriber-only feature
- **Keywords / phrases:** "download," "offline," "airplane mode," "no wifi," "no signal," "can't download anymore," "downloads are gone," "used to be able to download," "save for later," "download button missing"

# Required Context

- [ ] Platform — the bug and the fix are **Android v2**; an iOS download complaint does NOT match this policy (treat as a new/unlisted issue per `known-bugs.md`)
- [ ] Whether the customer has updated to app version 2026.07.21 or later
- [ ] Whether the customer has ever subscribed (downloads are a subscriber-only feature)
- [ ] Whether the ticket claims downloads are still broken AFTER updating to 2026.07.21+

# Policy / Correct Response

## Standard Case

Give the good news: the download issue is fixed. Tell the customer to **update the Happier app to the latest version (2026.07.21 or later) from the Google Play Store**. After updating:

- **Previously downloaded meditations are restored** — they don't lose what they had.
- **New downloads work again.**

Note that the Play Store rollout is gradual — if the update isn't visible yet, check back in a few hours. Close with a light safety net: if downloads still aren't working after updating, reply and we'll dig in. Do NOT proactively offer compensation, and do not re-litigate the outage — lead with the fix.

On threads where we previously promised to "notify you once downloads are working again," frame this reply as that promised follow-up.

## Variations

- **Churn threat tied to downloads** ("I was going to cancel over this"): the restoration news is the resolution — deliver it warmly, acknowledge the frustration briefly, no retention gesture needed by default. If the ticket ALSO contains an explicit cancellation or refund request, handle that portion under *Cancellation Policy* / *Refund Policy* as usual.
- **Never-subscribed user asking about downloads:** Downloads are a subscriber feature. Lead with that (not the bug history), mention the feature is fully working again, and point them to subscribing if interested (`Get HowtoSubscribe`).
- **Customer asks whether their old downloads survived:** Yes — previously downloaded meditations are restored once they update to 2026.07.21+.
- **Customer on an old thread where we said "no ETA":** Reply with the good news as the promised notification.

## Edge Cases & Exceptions

- **Downloads still broken after updating to 2026.07.21+:** Do NOT auto-send a generic reply. Gather device model, OS version, and exact app version, and flag for human review — each confirmed post-update failure is evidence the fix didn't fully land and Cassidy wants the signal.
- **iOS download complaints:** The bug and fix were Android v2. An iOS report does not match this entry — treat as a new, unlisted issue per `known-bugs.md` (acknowledge, ask clarifying questions, flag for review).
- **Ticket combines downloads with an active refund or cancellation request:** Deliver the restoration news AND route the billing portion through *Refund Policy* / *Cancellation Policy*; the billing portion controls auto-sendability.
- **Customer hasn't updated / can't update yet:** The fix requires the Play Store update — there is no workaround on older versions. Rollout can take a few hours; ask them to check back.

# Action Classification

## No Action Required (reply only)

- All standard downloads tickets: reply-only good-news response (fixed in 2026.07.21, update the app, prior downloads restored).
- Never-subscribed user asking about downloads: reply-only, subscriber-feature explanation.

## Human Action Required

None — the fix is shipped; the customer self-serves by updating the app.

## Do Not Auto-Send Conditions

- Downloads reported **still broken after updating to 2026.07.21+** — flag for human review (potential fix gap)
- Ticket combines downloads with an **active refund or cancellation request** — the billing portion controls; route through *Refund Policy* / *Cancellation Policy*
- Platform is **iOS** or otherwise doesn't match the Android v2 bug — unlisted issue, human review

## Escalation Triggers

- Multiple post-update "still broken" reports (pattern = fix regression) — escalate per *Escalation Policy*
- Any threat to leave a public review or contact press/media — escalate per *Escalation Policy* (sensitive PR risk)

# Confidence Notes

- **High confidence areas:** The fix shipped in Android app version 2026.07.21; updating restores prior downloads and re-enables new downloads; the good-news reply is auto-sendable; rollout may take a few hours; the reply fulfills the notify-when-restored commitment.
- **Judgment call areas:** Whether a vague "it still doesn't work" reply means the customer actually updated to 2026.07.21+ (when unclear, ask for their app version rather than assuming a fix gap).
- **Gaps:** No dedicated saved reply exists yet for the restoration announcement — draft from this policy's Standard Case language. Flag for the team to create one if downloads tickets keep arriving in volume.

# Saved Reply Mapping

No saved reply matches the restoration announcement exactly — draft personalized replies from the Standard Case above. Adjacent replies:

| Situation | Closest existing saved reply | Note |
|---|---|---|
| Customer needs to update the app (the fix) | `TechSupport AndroidUpdateApp` / `TechSupport AppleAndAndroidUpdateApp SNIPPET` | Now directly relevant: updating IS the fix — personalize to downloads wording (prior downloads restored, new downloads work) |
| Never-subscribed user interested in subscribing | `Get HowtoSubscribe` | Use as follow-on after explaining downloads are subscriber-only |
| Pure sentiment/feedback about the outage, nothing to answer | `Feedback PassedOn` | Only if there's no download question left to answer |

# Related Policies

- *Known Bugs & Current Product Status* (Entry 4 — status summary points here)
- *Cancellation Policy* / *Refund Policy* (billing portions of combined tickets)
- *Feedback Policy* (pure sentiment about the outage)
- *Escalation Policy* (post-update failures at pattern scale; PR risk)
