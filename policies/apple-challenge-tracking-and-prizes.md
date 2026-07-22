# Mindful Minute Challenge — Minutes, Tracking, Medals & Prizes (Apple Mailbox)

# Summary

**Scope: Apple mailbox (`3. Happier Apple Support`, id 201086).** Applies during and right after a challenge event; see the join doc for getting in.

Completion rule: **meditate at least one full minute a day on 25 of the challenge month's 31 days.** Minutes register from meditating in the Happier app or via Apple Health integration; medals are cosmetic tiers based on daily average; **prizes belong to Apple Wellness, not us.** Most tickets here are "my minutes didn't count" — the answer is almost always the under-60-seconds rule, a date-attribution rule, or a broken Health-app connection.

# Trigger Conditions

- **Ticket signals:** "my meditation didn't count," "calendar shows a missed day," "can I make up a day," "do podcasts count," Apple Watch / Fitness+ minutes missing, "what do the medals mean," "how do I get my prize," "am I on track to complete"
- **Keywords:** "minutes," "streak," "calendar," "Health app," "medal," "gold/silver/bronze," "prize," "complete the challenge"

# Required Context

- [ ] The account the app is signed into (their history/stats live there).
- [ ] Was the session ≥60 seconds, and did it finish before/after midnight?
- [ ] Done inside the Happier app, or externally (Watch, Fitness+, other app) — i.e., does it depend on the Health connection?
- [ ] For status questions: their session count vs. the 25 needed (`#SESSIONS` in `Support PrizeAccountInfo FILLIN`).

# Policy / Correct Response

## Standard Case — what counts, and when

**Counts toward Challenge time:** meditations in the Courses, Singles, or Sleep tabs; Practice in Action; Wisdom Clips; the Unguided Timer; Apple Watch Mindfulness app and Fitness+ meditations (only with the Health connection set up); minutes logged manually in the Health app.
**Does not count:** talks and podcasts; any session **under 60 seconds**.

Date-attribution rules (`Support MinutesWhyDidn'tMyMinutesRegister`):

- **Past Sessions** count on the day you actually meditate, not the day the content was released (tap Past Sessions on the Challenge screen to access earlier content).
- A session that **crosses midnight** counts on the date it *finishes*.
- After adding minutes via the Health app, the Happier app should update; if not, Force Quit and reopen.

## Missed days and manual adds

- **A day with no meditation at all cannot be made up** — but it usually doesn't matter: only 25 of 31 days are needed → `Support MinutesCan'tRedoMissedDay`.
- **A session that actually happened but didn't register** can be added with the Health app, with the correct date, and will flow into Happier stats and the Challenge calendar → `SNIPPET AddMinutes` (articles 21 + 87). This is the honest-correction path, not a loophole for skipped days.

## Health-app connection troubleshooting (external minutes missing)

1. **Connection/settings check:** both articles — *Connect Your Health and Happier Apps* (21) and *Use the Apple Health App to Add Minutes* (87); all settings must match → `Minutes CheckHealthAppSettings`.
2. **Health permission broken/disabled:** delete the Happier app **fully** (not App Library), reinstall from the App Store, sign back into the same account (registration + method go in the reply), reconnect Health via article 21 → `Support MinutesHealthAppDisabledDelAndReinstallApp FILLIN`; the variant that also covers the under-60s rule and re-adding via Health → `Minutes Under60SecondsAddYourOwn`.
3. **Support-side fix:** an agent can add a missed meditation to the customer's history directly; confirm with → `Minutes MeditationAdded`.

## Calendar

The Challenge calendar lives behind the Challenge card: open the app → tap **More** on the Challenge card → the progress calendar shows → `Minutes Can'tSeeCalendar`.

## Medals

Automatic tiers from **average minutes per day** — nothing to configure, and they **do not affect the Apple Wellness prize** (no registration changes needed):

- 🥇 Gold — 10+ min/day average
- 🥈 Silver — 5+ min/day average
- 🥉 Bronze — 1+ min/day average

Reply also lists every way to log more/fewer minutes than the featured session (Courses/Singles/Sleep, Practice in Action, Wisdom Clips, Unguided Timer, Watch/Fitness+ via Health, manual Health adds) → `Support Medals`.

## Prizes & completion status

- **Prizes are handled entirely by the Apple Wellness team** — after the event ends, Wellness communicates prize info; direct questions to `wellness@apple.com`. We never confirm prize eligibility, timelines, or contents → `Support PrizeAfterChallenge`.
- **"Am I on track?"** — give their verified numbers: sessions completed out of 25, the ≥1-full-minute rule, and the Health-app correction path → `Support PrizeAccountInfo FILLIN`.
- Post-event, remind them the **Global Access subscription is theirs year-round** (see *Global Access*).

## Edge Cases & Exceptions

- **Sessions under 60 seconds "missing":** working as designed — they don't register; meditate ≥1 full minute (`Minutes Under60SecondsAddYourOwn`).
- **Meditating before the join completed:** those in-app minutes are credited to the Challenge calendar once joined (`SNIPPET KeepMeditating`).
- **Disputed history we can't reproduce:** ask for a Contact-a-Human email (device data) before promising corrections.

# Action Classification

## No Action Required (reply only)

- What-counts questions, date-attribution explanations, calendar directions, medal explanations, Health-app setup guidance, prize redirects to Wellness.

## Human Action Required

- **Add a meditation to a customer's history** (server-side) when it verifiably didn't register → then `Minutes MeditationAdded`.
- **Pull completion stats** for `Support PrizeAccountInfo FILLIN` (#SESSIONS must come from real account data).

## Do Not Auto-Send Conditions

- Any reply quoting session counts or completion status not read from the account.
- Anything asserting prize eligibility, prize contents, or prize timing — that's Wellness's domain.
- Unfilled `FILLIN` placeholders.

## Escalation Triggers

- Prize disputes or "Wellness says I didn't complete but I did" → `wellness@apple.com` (customer-side) and flag internally.
- Widespread minutes-not-registering reports in one day → likely product incident; flag with diagnostics.

# Confidence Notes

- **High confidence:** the 25-day / ≥1-minute rule, under-60s exclusion, date-attribution rules, medal thresholds, Wellness-owns-prizes — verbatim from saved replies (pulled 2026-07-22).
- **Judgment call:** whether a "missing day" is correctable (session happened, add via Health) vs. not (no session that day).
- **Gaps / known copy inconsistency:** one reply says "25 out of the 30 days" (`Support MinutesCan'tRedoMissedDay`) while others say 31 (`Support PrizeAccountInfo FILLIN`, `SNIPPET KeepMeditating`) — treat **25 required days** as the constant and the month length as 31 unless the team says otherwise for a given cycle.

# Saved Reply Mapping

All names from `data/saved_replies_apple.json` (mailbox 201086), quoted exactly.

| Situation | Saved reply |
|---|---|
| Why didn't my minutes register (dates, past sessions, midnight) | `Support MinutesWhyDidn'tMyMinutesRegister` |
| Can I make up a missed day | `Support MinutesCan'tRedoMissedDay` |
| Add unrecorded minutes via Health app | `SNIPPET AddMinutes` |
| External/Watch minutes not syncing — settings check | `Minutes CheckHealthAppSettings` |
| Health permission broken — delete & reinstall | `Support MinutesHealthAppDisabledDelAndReinstallApp FILLIN` |
| Under-60-second sessions missing + self-correction | `Minutes Under60SecondsAddYourOwn` |
| Agent added the session server-side | `Minutes MeditationAdded` |
| Where's my progress calendar | `Minutes Can'tSeeCalendar` |
| What are the medals / log more or fewer minutes | `Support Medals` |
| Prize questions after the event | `Support PrizeAfterChallenge` |
| Completion status with real numbers | `Support PrizeAccountInfo FILLIN` |
| Minutes while un-joined still count | `SNIPPET KeepMeditating` |

# Related Policies

- *Mindful Minute Challenge — Registration & Join (Apple Mailbox)* — join problems, token issues
- *Global Access (Apple Wellness Complimentary Subscription)* — the year-round subscription after the event
- *Apple Mailbox Overview (Apple Wellness Programs)* — links, conventions, account identification
- *Meditation History & Streaks* — general (non-challenge) history/stats questions
