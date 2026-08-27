# Meditation History & Streaks

# Summary

Covers tickets where a customer reports a missing meditation session, a broken or incorrect streak, or stats that don't reflect activity they know they completed. The profile area of the app shows total sessions, total days meditated, total minutes, a daily/weekly streak counter (toggled by tapping), and a last-four-weeks calendar graphic where a filled circle indicates a day with a completed session. The most common triggers are a single missed day due to a glitch, a streak that reset unexpectedly, or a session that didn't register. Our default response is to manually add the missing session(s) to the customer's history on the backend and send a short confirmation — we do not instruct customers to do this themselves first. For iOS users only, Apple Health integration is available as a fallback but is offered only upon escalation, not as a first-line suggestion.

# Trigger Conditions

- **Ticket signals:** customer says their streak was reset, a session didn't count, a meditation didn't show up in their history, their stats look wrong, a day is missing from the calendar, or minutes/sessions aren't adding up
- **Account signals:** any subscription state — this issue occurs for free and paid users alike; account must be found to take action
- **Keywords / phrases:** "streak," "missed a day," "didn't count," "lost my streak," "stats," "history," "minutes aren't right," "session didn't register," "calendar," "days meditated," "I meditated but it didn't show," "glitch," "bug," "reset," "starting over," "lost progress"

# Required Context

- [ ] Account found on contact email (required before any action can be taken)
- [ ] Which day(s) or session(s) are missing or incorrect — ask the customer if not stated
- [ ] The calendar day immediately before and after the reported date, checked in admin Mindful Sessions (streak intact)
- [ ] Platform (iOS or Android) — determines whether Apple Health integration is relevant
- [ ] Whether the customer has already attempted any troubleshooting (force quit, app update, etc.)
- [ ] Whether this appears to be a one-time glitch or a recurring/systemic issue

# Policy / Correct Response

## Standard Case

The customer reports a missing session or broken streak. We manually add the missing meditation(s) to their history on the backend and send a short confirmation reply.

**Do not instruct the customer to fix this themselves as a first step.** We handle it for them.

### Steps

1. **Identify the missing session(s)** — review the customer's message for the date(s) and approximate duration (if provided). If the customer doesn't specify, ask before taking action: we need at least the date(s) to make the correct edit.
2. **Check the day before and the day after** — in admin Mindful Sessions, confirm the calendar day immediately before and after the reported date each have a session, so the streak is actually intact. A named date can already be present while a neighbor day is the real break. If a neighbor day is empty and the customer meditates daily, include it in the same fix (add it, or ask if the date is unclear). Do not skip this check even when the named date already has a row. (Taught 2026-08-27 on Diane #320027.)
3. **Manually add the session(s) to their account** — this is done in the backend/admin tooling. Add each missing day with a reasonable session length if one was provided; if not, use a standard duration consistent with what the customer seems to describe.
4. **Send the confirmation reply** — a short, warm note letting the customer know we've updated their history and what they should now see in the app.

### Confirmation reply template

```
Hi {firstName},

I've gone ahead and updated your meditation history — you should now see {date(s)} reflected in your stats and streak.

Give the app a quick refresh if you don't see the update right away. Let us know if anything still looks off and we'll take another look!

Take care,
Happier Meditation Support Team
```

## Variations

- **Customer provides a date range instead of a single day:** Add each day individually. Confirm the range in the reply (e.g., "I've added back the sessions for March 3–5").
- **Customer doesn't know the exact date:** Ask in a brief reply before making any edits. Don't guess — an incorrect edit is harder to undo than a one-question follow-up.
- **Named date already has a session:** Still check the day before and the day after before sending. The streak break may be a neighbor day.
- **Streak shows the wrong number but all sessions appear to be in history:** This may be a display bug rather than a missing session. Acknowledge, investigate whether the count matches the actual sessions, and escalate to support engineering if the data looks correct but the counter is wrong.
- **Android user:** Same process — manually add the session(s). Apple Health is not available on Android; do not suggest it.
- **iOS user, recurring issue:** If the customer has reported the same glitch more than once, offer Apple Health integration as a fallback after fixing the current instance. See Apple Health section below.

## Apple Health Integration (iOS Only — Escalation Path)

Apple Health integration allows iOS users to have sessions from other apps (including Apple's native Mindful Minutes) or manually added Apple Health entries automatically populate into their Happier Meditation history. This integration is available in the app under Settings.

**This is not a first-line suggestion.** It requires setup steps and has some friction. Our default is to fix the issue manually. Offer Apple Health only when:

- The customer is on iOS, **and**
- The issue is recurring (they've come back more than once for the same type of glitch), **or**
- The customer explicitly asks about a way to prevent this from happening again

When offering Apple Health, use the Apple Health troubleshooting saved reply, which walks through enabling the integration from the app's Settings.

## Edge Cases & Exceptions

- **Customer says sessions are missing but the account can't be found:** Do not make any edits. Follow the *No Account Found — Troubleshooting* path first.
- **Customer wants all-time history restored after account deletion or reinstall:** This is a data recovery issue, not a single-session correction. Escalate — history restoration beyond a session-level edit requires backend investigation.
- **Customer believes they've meditated every day for months and the streak should be much higher:** Do not add bulk history without verifying against backend records first. If records don't support the claim, a human agent should review before making edits.
- **Customer is frustrated or emotionally attached to their streak:** Acknowledge the frustration warmly before fixing. A streak represents real effort — validate it.

# Action Classification

## No Action Required (reply only)

No cases in this policy are reply-only at the outset. Every ticket requires a backend edit before a confirmation reply can be sent. The one exception: if we need to ask for clarifying information (which date(s)?) before taking action, the first reply is informational — but action is still required once we have the answer.

## Human Action Required

- **Action:** Manually add missing meditation session(s) to the customer's history
  **When:** Any time a customer reports a missing session, incorrect stat, or broken streak — which is all standard cases
  **Why AI can't do it:** Requires admin/backend access to edit a user's meditation history

- **Action:** Investigate display bug
  **When:** Session history appears complete but streak counter or stats are still wrong
  **Why AI can't do it:** Requires backend investigation to determine whether the issue is a display bug vs. a data issue; may need support engineering

- **Action:** Bulk history review or restoration
  **When:** Customer claims extended missing history (weeks or months), not a single session
  **Why AI can't do it:** Requires cross-referencing backend records before edits; scale of edit warrants human verification

## Do Not Auto-Send Conditions

- Customer hasn't provided the specific date(s) — don't send a confirmation before we know what to add
- The customer's described history loss is large or spans a long period — human should verify before making edits
- The streak counter appears to be a display bug rather than missing data — needs investigation before any confirmation language is sent
- Customer tone suggests significant frustration or emotional distress about the lost streak — personalize before sending

## Escalation Triggers

- Stats counter appears incorrect despite all sessions being present in history → support engineering
- Customer requests bulk restoration of long-term history that we can't verify → senior agent
- Customer has written in multiple times for the same recurring glitch → consider systemic bug; flag to engineering

# Confidence Notes

- **High confidence areas:** The standard case (single missing day, customer provides the date) is clear and low-risk — manual add + confirmation is the right move every time
- **Judgment call areas:**
  - What session duration to add when the customer doesn't specify — current practice is to use a reasonable default; flagged as a gap to standardize
  - When exactly to introduce Apple Health vs. just fixing again — current guidance is "recurring issue" as the threshold, but "recurring" is not precisely defined
- **Gaps:**
  - No standardized default session duration to add when the customer doesn't specify one
  - Apple Health integration setup documentation should be linked once a Help Center article exists
  - Android equivalent to Apple Health (if any) is not currently defined

# Saved Reply Mapping

## Standard case — session added, confirmation sent

| Platform | Situation | Saved Reply |
|---|---|---|
| iOS | Session(s) manually added to stats/streak | `Engagement AppleAddMinutesToStatsStreak` |
| Android | Session(s) manually added to stats/streak | `Engagement AndroidAddMinutesToStatsStreak FILLIN` |

## Apple Health troubleshooting (iOS escalation path only)

| Situation | Saved Reply |
|---|---|
| iOS user, recurring glitch — offering Apple Health setup | `Engagement AppleHealthAppMinutesTroubleshoot` |

## Stats or app bug

| Situation | Saved Reply |
|---|---|
| Suspected app-level stats/tracking bug | `TechSupport med_stats_bug` |

# Related Policies

- *No Account Found — Troubleshooting* — if account lookup fails before we can make any edits
- *Escalation Policy* — if the issue appears systemic or involves data integrity concerns
- *Login Issues* — if the customer is also having trouble getting into the app
