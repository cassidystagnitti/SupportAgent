# Known Bugs & Current Product Status

# Summary

This doc is the **single source of truth for current bugs and product status** affecting support tickets — most urgently the wave of reports following the Hotwire Native Android app (v2) launch. It exists so that bug status can change without touching prompts or code: when a bug is fixed, newly discovered, or re-prioritized, **update this file directly** (this git repo is the single source of truth — the old Notion mirror was retired 2026-07-14). Never hardcode bug status in `prompts/draft_system_prompt.txt` or anywhere in Python — the prompt loads this doc wholesale along with the rest of `policies/*.md`.

**Update process:**
1. Edit the relevant `##` entry below (Status, dates, customer-facing script) in this repo and commit.
2. Do not edit `prompts/draft_system_prompt.txt` or any `.py` file to reflect a bug status change — if you find yourself doing that, stop and update this doc instead.
3. When a bug is fully resolved and no longer generating tickets, leave the entry in place with Status `Fixed` and a Date Resolved — don't delete history, it's useful for pattern-matching recurring issues.

# Trigger Conditions

- **Ticket signals:** customer reports something broken, missing, frozen, unresponsive, or changed unexpectedly after the app update; customer asks "is this a known issue?"; customer reports a bug that matches one of the entries below
- **Account signals:** none required — these are app-level issues that occur regardless of subscription state
- **Keywords / phrases:** "freezing," "frozen," "spinning," "won't respond," "broken," "not working," "reset," "missing," "disappeared," "white screen," "new app," "update," "glitch," "bug," "since the update," "Shortcuts," "Siri," "Play a Sleep Meditation," "auto-lock," "screen stays on," "screen stays lit," "sleep meditation"

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
- **Auto-send:** Do NOT auto-send — and since the fix is released, treat any report of this bug STILL happening (especially post-update) as an ESCALATION (`escalate = true`): Cassidy needs to know about every still-affected user, because each one is evidence the fix didn't fully land (confirmed 2026-07-21).
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

- **Status:** FIXED — root cause identified: streaks were breaking because podcast episodes weren't being counted correctly toward the streak. Fixed by support directly on individual affected accounts as reports come in (not a mass backfill) as of 2026-07-23.
- **Platforms:** New app (Hotwire Native v2)
- **What to tell the customer:** Acknowledge the report, confirm we've corrected their streak count so it reflects their actual practice, and reassure them their meditation history itself was never affected — only the streak display. No need to explain the podcast root cause to the customer unless it's directly relevant to their question.
- **Linear ticket:** T-786
- **Date added:** 2026-07-02
- **Date resolved:** 2026-07-23

## 4. Downloads / Offline Meditations Unavailable (Android v2)

- **Status:** FIXED — downloads restored in Android app version **2026.07.21**. Customers must update to the latest version from the Google Play Store.
- **Platforms:** Android (Hotwire Native v2 app)
- **What to tell the customer:** Give the good news: the download issue is fixed. Tell them to **update the Happier app to the latest version (2026.07.21 or later) from the Google Play Store** — once updated, their **previously downloaded meditations are restored** and they can **download new ones again**. Play Store rollout is gradual, so if the update isn't visible yet, check back in a few hours. Add a light safety net: if downloads still aren't working after updating, ask them to reply so we can dig in. This reply also fulfills the earlier "we'll notify you once downloads are working again" commitment — on older threads, frame it as that promised follow-up. Do NOT proactively offer compensation.
- **Auto-send:** The good-news restored reply IS auto-sendable. NOT auto-sendable: a report that downloads are **still broken after updating to 2026.07.21+** — flag for human review (each one is evidence the fix didn't fully land). See `downloads-offline.md` for the full policy.
- **Linear ticket:** Not yet filed / tracked internally
- **Date added:** 2026-07-02
- **Date resolved:** 2026-07-21 (fix released in Android app version 2026.07.21)

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

- **Status:** Legibility/contrast issue (light/thin text on light backgrounds) FIXED as of 2026-07-22 — confirmed by support team. General theme/visual-preference feedback (colors, "I liked the old look") remains Not a bug — treat as feedback.
- **Platforms:** New app (Hotwire Native v2)
- **What to tell the customer:**
  - **Legibility/contrast complaints** (light or thin text on light backgrounds, hard to read especially in low light): the fix has shipped — tell the customer contrast/readability has been improved and ask them to check the app and report back if anything still looks off. Do not offer the old "no setting to change theme" language for this specific contrast issue anymore.
  - **General theme / visual-preference complaints** (colors, white background, "I liked the old look" — not a readability/contrast complaint): still treat as feedback, not a technical issue. Acknowledge kindly, validate that preferences differ, and let them know we've passed it to the team. There is currently no user-facing setting to change the theme. Do not apologize as though something broke. Log the sentiment as feedback (see `feedback-policy.md`).
  - **Accessibility concerns beyond the fixed contrast issue** (text size, other low-vision needs): take these seriously. Acknowledge the concern genuinely, let them know accessibility matters to us and that we'll work on improvements, and log it as high-priority feedback. Do not dismiss an accessibility concern as mere preference.
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

## 11a. Network Errors During Playback — Ask About VPN

- **Status:** Known interference source — not a bug fix, a troubleshooting step
- **Platforms:** All platforms
- **What to tell the customer:** A VPN can sometimes interfere with our player and cause "network error" messages when trying to play a meditation. When a customer reports a network error, always ask whether they're using a VPN and, if so, suggest turning it off to see if that resolves the issue. This should be a standard question in any network-error troubleshooting reply, alongside device/OS, app version, and Wi-Fi vs. cellular.
- **Linear ticket:** N/A
- **Date added:** 2026-07-13
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

**Known bugs are SOLO-sendable (decision 2026-09-02):** When a reported symptom clearly matches a documented entry above, send the known-bug acknowledgment (real, ours, known, working on a fix; no date unless Linear says otherwise). Check Linear, comment/link Help Scout ticket, send the ack. Do not hold for Cassidy unless the bug combines with billing demands or significant harm.

**New bugs are SOLO-file-and-send (decision 2026-09-02):** When a reported symptom does NOT match any entry above and appears to be a new systemic issue, file a Linear issue on team Technical with Help Scout / Bug / iOS-or-Android / Support labels, update this known-bugs.md file with a new entry, post to Slack #customer-support-watcher (channel C0BLA516L1K) with Linear + Help Scout + one-line description, THEN send the customer ack and close. Do not hold new-bug filing or customer acks for Cassidy.

**Status-check before filing or repeating bugs (decision 2026-09-02):** Before filing or repeating any bug report, always check: (1) latest #customer-support-watcher (engineer replies: Jawad, Lynn, PRs, ship timing), (2) Linear issue status (state, assignee, comments, linked PRs), and (3) GitHub PRs tied to that Linear ticket. Do not re-report bugs already being worked (In Progress, Ready for Deploy, PR in flight, engineer said they are on it) — comment the new Help Scout thread on the existing Linear issue instead. If a bug was filed and has NOT been picked up (still unstarted / backlog / no PR / no engineer reply), send it again in #customer-support-watcher. Cassidy will bump a watcher post if it is very, very urgent. Keep this known-bugs.md file and related operating docs current when status changes so support answers from latest info.

**Customer-facing bug acks must match the Linear Technical status (decision 2026-09-02).** Do not use a generic "working on a fix / releasing soon" line. Never name Linear states to the customer. Hopeful, no "on us," no future-app-update, no ship date unless we have one. Sign-off remains Take care / Happier Meditation Support Team. Linear status → customer-facing language map:

1. **Priorities / Product Backlog / Engineering Backlog** with no confirmed cause → "We are investigating this now."
2. **Cause known** (engineer comment, Slack, root cause written) but not yet Implementation/QA → "We have identified the issue."
3. **Implementation or QA**, or an open fix PR → "We are resolving it now."
4. **Ready for Deploy**, or fix PR merged and waiting on ship → "We are in the process of releasing the fix."
5. **Done**: treat as released. If the customer still hits it, investigate whether it is the same bug; do not promise it is already on their phone.

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

## Do Not Ask Customers For Their App Version (added 2026-07-23)

If we have the customer's account, don't ask them to look up or report their app version in a draft reply — support can find this directly from account/admin data. This supersedes any wording elsewhere in this doc (e.g. entries 7 and 8's "ask for platform and app version" scripts) or in other policy docs that instructs asking the customer for their app version as a first step. If the version isn't already present in the context provided to Bert, a human agent should look it up via internal tooling rather than the draft asking the customer directly.

## 12. Cory Muscara Content Removed (Not a Bug)

- **Status:** Not a bug — confirmed product/roster change
- **Platforms:** All
- **What to tell the customer:** Cory Muscara is no longer a teacher on Happier Meditation, so his content (including previously popular sessions like his 5-minute sleep meditation) has been removed from the app. This is not a bug, glitch, or side effect of an app update — do not troubleshoot app version or search placement for missing Cory Muscara content. We don't currently have information on where his content is available elsewhere; don't speculate. Acknowledge the disappointment and offer to log it as feedback / recommend alternative content.
- **Linear ticket:** N/A
- **Date added:** 2026-07-23
- **Date resolved:** N/A (not a bug)

## 13. Meditation Pausing / Freezing / Stopping During Playback (iOS)

- **Status:** Investigating (newly reported)
- **Platforms:** iOS. Distinct from Entry 1, which is the Android v2 (Hotwire Native) version of this symptom and is already FIXED (released 2026-07-08). Entry 1's "assume Android, don't ask platform" guidance no longer holds now that iOS reports exist — confirm platform when a customer reports playback pausing/stopping when the screen goes dark, since the correct response differs by platform (Android → fixed, update the app; iOS → investigating, no fix yet).
- **What to tell the customer:** Acknowledge the report, confirm we're looking into it on iOS, and do not promise a fix date or workaround.
- **Linear ticket:** Not yet filed
- **Date added:** 2026-07-23
- **Date resolved:** —

## 14. iOS Shortcuts “Play a Sleep Meditation” Action Broken (v2)

- **Status:** Investigating (newly reported). Regression after the iOS v2 rebuild; Help Scout ticket 320046. Internal note filed this as Linear **T-1697** (assigned Lynn Hurley; described as a regression from T-911). Support’s Linear API key currently only sees the Prod Prioritization team, so T-1697 cannot be re-opened from that key — do not file a duplicate on team P.
- **Platforms:** iOS (reported on app `2026.817.1` / v2 rebuild). Apple Shortcuts action “Play a Sleep Meditation,” including as a standalone action.
- **What to tell the customer:** This is not an intentional removal. The iOS app recently went through a major rebuild, and that timing lines up with the Shortcuts action stopping. We’ve flagged it to engineering. Do not promise a fix date. Sleep meditations still play from the Sleep tab inside the app; acknowledge that is not the one-tap shortcut they built. Nothing more they need to do on their end. Do not ask them for app version if we already have account/ticket data.
- **Linear ticket:** T-1697
- **Date added:** 2026-08-27
- **Date resolved:** —

## 15. iOS Screen Stays On During Meditation / Auto-Lock Never Returns (v2)

- **Status:** Investigating. Cassidy reproduced on her device 2026-08-27. Help Scout ticket 320168. Linear **T-1760**. Related to T-700 (keep-screen-awake during playback), which likely overshot for sleep sessions.
- **Platforms:** iOS (reported on app `2026.817.1` / v2 rebuild). Device auto-lock is set (e.g. 4 minutes) but the screen stays lit for the whole meditation, especially sleep sessions.
- **What to tell the customer:** This is a bug, not something they did. We cannot restore a previous App Store version. We've flagged it to engineering and we'll get it fixed as soon as we can. They can still lock the phone with the side button if they want the room dark while audio continues. Do not promise a date. Do not ask for app version if we already have it. Distinct from entry 13 (playback pausing when the screen *does* lock).
- **Linear ticket:** T-1760
- **Date added:** 2026-08-27
- **Date resolved:** —

## 16. Audio Not Playing / No Sound (Including After Turning Off Captions or After an Update)

- **Status:** Troubleshooting — not a confirmed product bug. First-line steps before treating as a new Linear issue.
- **Platforms:** All
- **What to tell the customer:** Do not promise a bug or a fix. Do not ask for app version if we already have the account. Start with first-line troubleshooting: (1) force quit the Happier app and reopen it; (2) try playback with VPN off and with VPN on (a VPN can interfere with the player); (3) ask them to let us know if that does not resolve it. Do not jump to a new Linear bug until those steps fail on a later reply.
- **Linear ticket:** None unless troubleshooting fails on a later reply
- **Date added:** 2026-08-28. Taught from Help Scout 320202.
- **Date resolved:** —
- **Cross-ref:** Related to entry 11a (VPN for network-error reports), but this first-line flow applies to no-audio / audio-not-playing reports — not only tickets that say "network error." Includes reports after turning off closed captions and when the customer mentions the new update.

## 17. iOS v2 Significant Lag / App Unusable

- **Status:** Investigating. Filed Linear **T-1797** from Help Scout 320536 (Heather, iOS 2026.817.1). Distinct from T-568 (mobile Safari slowness, Done) and T-1741 (oversized UI).
- **Platforms:** iOS native v2 (`2026.817.1`).
- **What to tell the customer:** The app should not lag so much that it is unusable. This is a known bug. We are working on a fix now. We are releasing the fix soon. Do not promise a date. Do not send them to an App Store update. Meantime: force-quit Happier and reopen. If it is still laggy, ask them to reply. Do not ask for app version if we already have it.
- **Linear ticket:** T-1797
- **Date added:** 2026-09-02
- **Date resolved:** —

## 18. iOS v2 Monthly Check-In Home Prompt Showing Incorrectly

- **Status:** FIXED and LIVE as of 2026-09-02 ~11:47 AM ET. Rails-only fix. Lynn Hurley merged to master and deployed. Cassidy confirmed on-device.
- **Platforms:** iOS v2. An incomplete first fix went live ~3:15 PM ET Sep 1 (force quit loaded the plan, but completing check-in still showed the Home start card). The 11:47 AM ET Sep 2 deploy is the complete fix.
- **What to tell the customer:** This was a bug causing the monthly check-in Home prompt to display incorrectly, and it is now fixed and live. The fix is Rails-side (already deployed), so no app update is needed. If they are still seeing the issue, ask them to force quit the Happier app and reopen it. If the problem persists after force quit, treat it as a new report and investigate further — do not assume T-1791 is still open.
- **Linear ticket:** T-1791
- **Date added:** 2026-09-02
- **Date resolved:** 2026-09-02 (11:47 AM ET)
- **Slack reference:** https://happierapp.slack.com/archives/C094NGF9JTZ/p1788275859366179

