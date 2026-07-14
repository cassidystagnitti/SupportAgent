# Known Bugs & Current Product Status

# Summary

This doc is the **single source of truth for current bugs and product status** affecting support tickets — most urgently the wave of reports following the Hotwire Native Android app (v2) launch. It exists so that bug status can change without touching prompts or code: when a bug is fixed, newly discovered, or re-prioritized, **update this file (and its mirror in Notion) directly.** Never hardcode bug status in `prompts/draft_system_prompt.txt` or anywhere in Python — the prompt loads this doc wholesale along with the rest of `policies/*.md`.

**Update process:**
1. Edit the relevant `##` entry below (Status, dates, customer-facing script) in this repo.
2. Make the same edit to the corresponding entry in the **Support Policy Docs** Notion page (ID: `356cffdf-527f-808d-a4fc-f7d05499523f`).
3. Do not edit `prompts/draft_system_prompt.txt` or any `.py` file to reflect a bug status change — if you find yourself doing that, stop and update this doc instead.
4. When a bug is fully resolved and no longer generating tickets, leave the entry in place with Status `Fixed` and a Date Resolved — don't delete history, it's useful for pattern-matching recurring issues.

# Trigger Conditions

- **Ticket signals:** customer reports something broken, missing, frozen, unresponsive, or changed unexpectedly after the app update; customer asks "is this a known issue?"; customer reports a bug that matches one of the entries below
- **Account signals:** none required — these are app-level issues that occur regardless of subscription state
- **Keywords / phrases:** "freezing," "frozen," "spinning," "won't respond," "broken," "not working," "reset," "missing," "disappeared," "white screen," "new app," "update," "glitch," "bug," "since the update"

# Required Context

- [ ] Platform (iOS or Android) and app version, if available — several entries below are Android v2 (Hotwire Native) specific
- [ ] Which specific symptom the customer is describing — match carefully against the entries below rather than assuming
- [ ] Whether the customer has already updated to the latest app version
- [ ] For "reported, gathering info" entries: platform and app version are required before a full response can be drafted — ask if not provided

# Policy / Correct Response

## Standard Case

Match the customer's reported symptom to one of the bug entries below and follow that entry's "What to tell the customer" script. Personalize with the customer's name and specifics from their ticket, but do not deviate from the documented status — do not promise fix dates, workarounds, or outcomes that aren't stated in the entry.

If a report doesn't clearly match any entry below, do not assume it's a known issue. Treat it as a new, unlisted bug: acknowledge, ask clarifying questions (platform, app version, steps to reproduce), and flag for human review rather than inventing a status.

---

## 1. Meditation Pausing / Freezing / Stopping During Playback (Android v2)

- **Status:** FIXED — fix released 2026-07-08. Rollout on the Google Play Store can take a few hours to reach everyone.
- **Platforms:** Android (Hotwire Native v2 app). **Assume Android for any pausing/stopping-during-playback report** — do not ask which platform, and do not include iOS/hedging language.
- **What to tell the customer:** Give the good news: this was a known issue causing meditations to pause / stop / freeze during playback, and **the fix is now released**. Tell them to **update the Happier app to the latest version from the Google Play Store** — once updated, playback stays steady the whole way through, even with the screen off. Note that the rollout is gradual, so if they don't see the update yet, they should **check back in a few hours**. Add a light safety net: if they still see pausing after updating, ask them to reply so we can dig in. Do NOT proactively offer compensation.
  - **Do NOT give the battery-optimization workaround anymore.** The fix supersedes it — just tell them it's fixed. (If a customer already applied the workaround, they can leave it as-is or revert it; it's harmless either way.)
  - **Battery workaround (FOR REFERENCE ONLY — do not send unless a customer explicitly can't update yet):**
    - **Pixel / stock Android:** Settings → Apps → Happier → Battery → set to **Unrestricted**.
    - **Samsung (most reporters):** same **Unrestricted** setting, **plus** make sure Happier is **not** in Device Care's "Sleeping apps" / "Deep sleeping apps" list (Battery → Background usage limits). Samsung layers its own power saving on top of Android's, so both steps matter.
- **Auto-send:** Do NOT auto-send yet — everything still drafts for human review.
- **Linear ticket:** Fix released 2026-07-08 (add ticket ref once filed)
- **Date added:** 2026-07-01
- **Date resolved:** 2026-07-08 (marked Fixed 2026-07-01; reopened 2026-07-06 after continued reports; **fix released 2026-07-08**)

## 2. Milestones Broken (New App)

- **Status:** Fix in progress
- **Platforms:** New app (Hotwire Native v2)
- **What to tell the customer:** Acknowledge that milestones are currently broken on the new app and that we're actively working on a fix. Do not commit to a date.
- **Linear ticket:** Not yet filed / tracked internally
- **Date added:** 2026-07-02
- **Date resolved:** —

## 3. Streaks Broken or Reset

- **Status:** Fix in progress (bug identified as of 2026-07-06)
- **Platforms:** New app (Hotwire Native v2)
- **What to tell the customer:** Acknowledge the report and let them know we've found a bug affecting streaks and are actively working on a fix. Reassure them that their meditation history is safe even if the streak display looks wrong. Do not promise a specific fix date.
- **Linear ticket:** T-786
- **Date added:** 2026-07-02
- **Date resolved:** —

## 4. Downloads / Offline Meditations Unavailable

- **Status:** Known issue in latest update — fix in progress
- **Platforms:** New app (Hotwire Native v2)
- **What to tell the customer:** There's a known issue affecting downloads in the latest app update, and we're actively working on a fix. We'll notify users once downloads are working again. Do NOT say downloads were "removed" or imply it was intentional — it's an unintended bug. Do not fabricate a timeline. See `downloads-offline.md` for the full policy, variations (e.g. churn-risk responses), and saved reply mapping for this issue.
- **Linear ticket:** Not yet filed / tracked internally
- **Date added:** 2026-07-02
- **Date resolved:** —

## 5. Do Not Disturb Toggle Missing or Broken (Android v2)

- **Status:** Investigating
- **Platforms:** Android (Hotwire Native v2 app)
- **What to tell the customer:** Acknowledge that the Do Not Disturb toggle is missing or not working on the new Android app and that we're investigating. There is no known workaround at this time — do not suggest one.
- **Linear ticket:** T-787
- **Date added:** 2026-07-02
- **Date resolved:** —

## 6. Intention-Setting Text Box Unresponsive

- **Status:** Investigating
- **Platforms:** New app (Hotwire Native v2) — check-in / practice plan flow
- **What to tell the customer:** Acknowledge that the intention-setting text box isn't responding to input and that we're looking into it.
- **Linear ticket:** T-788
- **Date added:** 2026-07-02
- **Date resolved:** —

## 7. Restart Course Button Unresponsive

- **Status:** Reported, gathering info
- **Platforms:** Unconfirmed — ask the customer
- **What to tell the customer:** Acknowledge the report and ask for their platform (iOS/Android) and app version so it can be investigated further. This has not yet been confirmed as a systemic issue.
- **Linear ticket:** Not yet filed
- **Date added:** 2026-07-02
- **Date resolved:** —

## 8. Goal-Setting Freezes or Spins on Save

- **Status:** Reported, gathering info
- **Platforms:** Unconfirmed — ask the customer
- **What to tell the customer:** Acknowledge the report and ask for their platform (iOS/Android) and app version so it can be investigated further. This has not yet been confirmed as a systemic issue.
- **Linear ticket:** Not yet filed
- **Date added:** 2026-07-02
- **Date resolved:** —

## 9. UI Theme / Visual Design Changes (and Accessibility)

- **Status:** Not a bug — treat as feedback (accessibility concerns taken seriously)
- **Platforms:** New app (Hotwire Native v2)
- **What to tell the customer:**
  - **General theme / visual-preference complaints** (colors, white background, "I liked the old look"): treat as feedback, not a technical issue. Acknowledge kindly, validate that preferences differ, and let them know we've passed it to the team. There is currently no user-facing setting to change the theme. Do not apologize as though something broke. Log the sentiment as feedback (see `feedback-policy.md`).
  - **Accessibility concerns** (readability, contrast, text size, hard to see/use for low-vision or other accessibility needs): take these seriously. Acknowledge the concern genuinely, let them know accessibility matters to us and that we'll work on improvements, and log it as high-priority feedback. Do not dismiss an accessibility concern as mere preference.
- **Linear ticket:** N/A — routed as feedback
- **Date added:** 2026-07-02
- **Date resolved:** —

## 10. Missing Checkmarks on Completed Meditations (Android)

- **Status:** Known issue — fix planned
- **Platforms:** Android (Hotwire Native v2 app)
- **What to tell the customer:** Acknowledge that the checkmarks that normally show on completed meditations are missing, that this is a known issue on our end (not something they're doing wrong), and that we have a fix planned. Do not promise a specific date.
- **Linear ticket:** Not yet filed
- **Date added:** 2026-07-10
- **Date resolved:** —

## 11. "Last 4 Weeks" / Weekly Time-Tracking View Missing

- **Status:** Known issue — fix planned
- **Platforms:** New app (Hotwire Native v2)
- **What to tell the customer:** Acknowledge that the weekly time-tracking view (the "Last 4 Weeks" swipe view of meditation stats) is currently missing, that this is a known issue we're aware of, and that we have a fix planned. It wasn't an intentional removal. Do not promise a specific date.
- **Linear ticket:** Not yet filed
- **Date added:** 2026-07-10
- **Date resolved:** —

# Action Classification

## No Action Required (reply only)

All nine entries above are reply-only — no backend, Stripe, or account action is required. The correct response in every case is a personalized reply using the entry's script, optionally preceded by a clarifying question (entries 7 and 8, which need platform/app version first).

## Human Action Required

None. If a report suggests a new, systemic issue not covered by an entry above, that's a signal for the *Escalation Policy*, not a required backend action from this doc.

## Do Not Auto-Send Conditions

- The ticket mixes a bug report with a billing, refund, or cancellation demand (e.g., "this app is broken, I want a refund") — do not auto-send; route the billing/refund portion through the relevant billing policy and flag the bug portion for human review
- The report doesn't clearly match any entry above — do not guess a status; flag for human review
- The customer reports one of the "investigating," "reopened," or "gathering info" bugs (entries 1, 2, 3, 5, 6, 7, 8) as causing significant financial or access harm (e.g., lost a paid course entirely) — acknowledge but flag for human review rather than auto-sending a generic "we're looking into it"
- Entry 9 (theme change) combined with a subscription cancellation threat — treat the cancellation portion under the appropriate billing policy; do not auto-send a feedback-only reply

## Escalation Triggers

- A reported symptom doesn't match any entry above and multiple customers appear to be describing the same new issue — flag as a potential new systemic bug for engineering, per the bug-surfacing process
- Any bug report tied to data loss the customer considers severe (e.g., "all my history is gone," not just a display glitch) — escalate per *Meditation History & Streaks*
- Customer disputes that entry 9 is "just a redesign" and demands the old UI back — treat as standard feedback escalation path, not a bug fix commitment

# Confidence Notes

- **High confidence areas:** Matching a clearly-described symptom to one of the nine entries above; using the exact status language documented (fixed / in progress / investigating / gathering info / not a bug) rather than softening or strengthening it
- **Judgment call areas:**
  - Entries 7 and 8 ("reported, gathering info") may turn out to be duplicates of each other or of a known entry once more reports come in — until this doc is updated, treat them as distinct, unconfirmed reports
  - Deciding whether a report is "close enough" to an existing entry or should be treated as a new, unlisted issue — when in doubt, treat as unlisted and flag for review rather than force-fitting
- **Gaps:**
  - Entries 2, 7, and 8 have no Linear ticket yet — status may change quickly; check this doc fresh each time rather than relying on memory
  - No workaround exists for entry 5 (Do Not Disturb) — if a customer asks for one, don't invent one

# Saved Reply Mapping

No saved reply currently exists that matches the specific v2-launch bug scripts in this doc (fixed/investigating/gathering-info language tied to these exact issues). This is a **gap** — flagging for the team to create saved replies once bug status stabilizes. In the meantime, use these adjacent replies as drafting references only (do not send unedited without personalizing to the specific bug and status above):

| Situation | Closest existing saved reply | Note |
|---|---|---|
| Milestones broken/feedback (entry 2) | `Feedback FeatureRequestMilestonesConfettiIssues` | Written for feature feedback, not bug status — personalize before use |
| Android-specific milestone/stat bug (entry 2) | `TechSupport AndroidMilestones` | Check wording still matches current status before sending |
| General stats/streak bug (entry 3) | `TechSupport med_stats_bug` | Generic bug acknowledgment; personalize to streak-specific wording |
| Customer hasn't updated the app (any entry where update might help) | `TechSupport AndroidUpdateApp` / `TechSupport AppleAndAndroidUpdateApp SNIPPET` | Use only where relevant to the platform. NOTE for entry 1: the fix is now released (2026-07-08) — updating to the latest Play Store version IS the resolution, so it's fine to frame it as the fix. |
| Meditation pausing/stopping (entry 1, FIXED 2026-07-08) | `TechSupport AndroidUpdateApp` / `TechSupport AppleAndAndroidUpdateApp SNIPPET` | Personalize to playback-pausing wording; tell them the fix is released and to update from the Play Store (rollout may take a few hours). Do not send the battery workaround. |
| Android home tab / general Android v2 bug context (entries 2, 5, 6, 7, 8) | `Bug android home tab not fixed` | Reference for tone only; confirm it doesn't overstate status |
| Android feature parity framing (entry 9, if customer compares to old app) | `Feedback LaunchNotOnAndroidYet` | Not a direct match — only useful if the ticket also raises a parity question |
| Need more detail before responding (entries 7, 8) | `TechSupport SendUsScreenshot` | Useful when asking for platform/app version plus a screenshot |
| Theme/design feedback with no other match (entry 9) | `Feedback PassedOn` | Generic feedback catch-all; use per `feedback-policy.md` |

# Related Policies

- *Feedback Policy* — entry 9 (UI theme change) routes here for logging as design feedback, not a bug
- *Meditation History & Streaks* — entry 3 (streaks broken/reset) and any data-loss escalation overlap with this policy's standard case
- *downloads-offline.md* — entry 4 (downloads/offline unavailable) is fully specified there; this doc only summarizes and cross-references it
- *Escalation Policy* — for any report that doesn't match a listed entry or appears to be a new systemic issue
