# Check-Ins, Goals & Intentions

# Summary

Covers tickets about the check-ins, monthly practice goals, and intention-setting features — all new in the v2 (Hotwire Native) app as part of the Practice Plan experience. The most common tickets are confusion about what the features are, requests to hide or disable them, and bug reports about them freezing or not saving. There is **no setting to hide or disable** any of these features today. The official stance on opt-out requests is to acknowledge honestly, explain there's no option currently, and log the feedback through the standard feedback conduit — never to imply a workaround or hidden setting that doesn't exist. Bug reports about these specific flows should be cross-checked against `known-bugs.md` before drafting, since two known issues (intention text box, goal-save freeze) already have documented status language.

# Trigger Conditions

- **Ticket signals:** customer asks what check-ins/goals/intentions are; customer asks how to turn off, hide, skip, or disable check-ins, monthly goals, or intention prompts; customer is frustrated by being asked to set intentions or goals repeatedly; customer reports the intention text box won't accept input; customer reports goal-setting freezes, spins, or won't save; customer says these features feel intrusive, unnecessary, or "in the way" of just meditating
- **Account signals:** none required — these are new v2 app features, not account- or subscription-dependent
- **Keywords / phrases:** "check-in," "check ins," "intention," "set an intention," "monthly goal," "practice goal," "practice plan," "why is it asking me," "can I turn this off," "can I skip this," "get rid of this," "stop asking me," "won't let me type," "won't save," "freezes when I try to save," "spinning," "annoying"

# Required Context

- [ ] Which specific feature the customer means: check-ins, monthly practice goals, or intention-setting (they are related but distinct; tickets sometimes conflate them)
- [ ] Whether the ticket is a **bug report** (something isn't working) vs. an **opt-out/preference request** (it works, but they don't want it) vs. a **general question** (what is this?)
- [ ] Platform and app version, if the ticket is a bug report — needed to match against `known-bugs.md` entries 6 and 8
- [ ] Emotional tone — genuinely frustrated "get rid of this" tickets need empathy before the feedback-conduit framing lands well

# Policy / Correct Response

## Standard Case

**Feature overview:** Check-ins, monthly practice goals, and intention-setting are new additions in the v2 app, part of the broader Practice Plan experience. They prompt users to reflect periodically and set light goals or intentions around their practice.

**No opt-out exists.** There is currently no setting anywhere in the app to hide, disable, or skip these features permanently. Be direct and honest about this rather than hedging — do not imply a setting might exist elsewhere in the app or that one is imminent.

**Official response pattern for opt-out requests:**
1. Acknowledge the request and validate that not everyone wants this kind of prompt.
2. State plainly that there's no option today to turn it off.
3. Let them know the request is being logged as product feedback (see *Feedback Policy* for the conduit framing — this routes as an engineering/design feature request, not a bug).
4. Close warmly. Do not promise the feature will be added or removed, and do not give a timeline.

## Variations

- **"How do I change / update my goal?" (edit request, not opt-out):** Check-ins currently run on a **monthly** cadence. There is **no way to edit or update a practice goal mid-cycle** right now. Tell the customer plainly: we run check-ins monthly at the moment, we're working on making it so goals can be updated anytime, and for now they'll get another chance to set their goal at the **end of the month** when the next check-in comes around. Do not invent an in-app "edit goal" path — one does not exist today. (This is a reply-only answer, not a bug.)
- **General question ("what is this feature?"):** Briefly explain what check-ins/goals/intentions are and how they fit into the Practice Plan experience. No feedback logging needed unless they also express a preference to change it.
- **Frustrated "get rid of this" ticket:** Lead with empathy — acknowledge that the prompts can feel like friction for some users. Then give the honest "no option today" answer, log as feedback, reply-only. Do not over-apologize or imply the team already knows this is a problem beyond what's documented.
- **Bug report — intention text box unresponsive:** Cross-reference `known-bugs.md` Entry 6 (Intention-Setting Text Box Unresponsive, Status: Investigating). Use that entry's script: acknowledge, confirm we're looking into it, no workaround to offer.
- **Bug report — goal-setting freezes/spins on save:** Cross-reference `known-bugs.md` Entry 8 (Goal-Setting Freezes or Spins on Save, Status: Reported, gathering info). Ask for platform and app version before a full response, per that entry's required context.
- **Customer conflates a bug with a request to remove the feature entirely** (e.g., "this keeps freezing, just get rid of it"): Address the bug portion per the relevant `known-bugs.md` entry, and separately note the removal request is logged as feedback. Don't let the bug fix become an implicit promise to remove the feature, and don't let the opt-out framing minimize the real bug.

## Edge Cases & Exceptions

- **Customer says the prompts are affecting their ability to meditate at all** (e.g., stuck on a screen, can't get past it): Treat as a bug/blocking issue first — check against `known-bugs.md` entries 6 and 8. If it doesn't match either entry, treat as a new, unlisted bug per that doc's standard case (acknowledge, ask clarifying questions, flag for human review).
- **Customer asks if check-ins are mandatory to keep their streak or access content:** No confirmed policy ties check-ins/goals/intentions to streaks or content access. Do not state or imply a connection that hasn't been documented — if the customer asks this directly and it's unclear, flag for human review rather than guessing.
- **Customer wants their previous check-in or goal answers reviewed by a real person, or wants to see their answers:** This is a separate, existing feature request — see `Feedback FeatureRequestSeeCheckInAnswers` under *Feedback Policy*. Do not conflate with the opt-out request.

# Action Classification

## No Action Required (reply only)

- General questions about what the features are: reply-only, explanatory.
- Opt-out / "get rid of this" requests: reply-only — acknowledge, explain no option exists, log as feedback. No account or backend action.
- Bug reports matching `known-bugs.md` entries 6 or 8: reply-only, using that entry's script (entry 8 requires a clarifying question on platform/version before the full response).

## Human Action Required

None. There is no backend setting to toggle and no account-level action available for opt-out requests. Bug fixes for entries 6 and 8 are engineering-owned, tracked in `known-bugs.md`, not something support can action directly.

## Do Not Auto-Send Conditions

- Customer's frustration escalates beyond standard annoyance into a broader complaint about the v2 app redesign or a churn threat — flag for human review (may need to route part of the reply through *Cancellation Policy*)
- Bug report describes data loss beyond a display glitch (e.g., "my saved goals disappeared entirely," not just a freeze on save) — flag for human review per the data-loss escalation path in `known-bugs.md`
- Report doesn't clearly match `known-bugs.md` entries 6 or 8 and doesn't look like a standard opt-out request either — treat as unlisted, flag for human review rather than force-fitting a response

## Escalation Triggers

- Customer combines the opt-out request with a subscription cancellation threat — route the cancellation portion under *Cancellation Policy*; do not auto-send a feedback-only reply that ignores the churn signal
- Multiple customers appear to be describing the same new, unlisted symptom around these features — flag as a potential new systemic bug per `known-bugs.md`'s escalation guidance

# Confidence Notes

- **High confidence areas:** No opt-out setting exists today. The acknowledge + honest "no option today" + feedback-log pattern for removal requests. Cross-referencing entries 6 and 8 in `known-bugs.md` for bug reports specifically about these features.
- **Judgment call areas:** Distinguishing a frustrated-but-standard opt-out request from one that's really a churn threat in disguise. Deciding whether a "can I turn this off" ticket is purely informational curiosity vs. a genuine preference request worth logging as feedback (when in doubt, log it — low cost, matches the conduit framing).
- **Gaps:** No saved reply exists yet specifically for "no opt-out for check-ins/goals/intentions" — see Saved Reply Mapping below. No confirmed policy on whether these features relate to streaks or content gating; don't speculate.

# Saved Reply Mapping

No saved reply in `data/saved_replies.json` directly addresses "there's no setting to disable check-ins, goals, or intentions." This is a **gap** — flag for the team to create a dedicated saved reply once this opt-out stance stabilizes. Use the adjacent replies below only as drafting references, and personalize per this doc's Standard Case language rather than sending them unedited:

| Situation | Closest existing saved reply | Note |
|---|---|---|
| General or uncategorized feature-removal feedback, no specific reply fits | `Feedback PassedOn` | Generic catch-all for logging the opt-out request as feedback |
| General feature request framing (if customer frames it as "please add a setting to turn this off") | `Feedback FeatureRequest` | Fill in REQUEST with "setting to disable check-ins/goals/intentions" |
| Customer wants to see their check-in answers (different request, don't conflate) | `Feedback FeatureRequestSeeCheckInAnswers` | Only for the "see my answers" request, not the opt-out request |
| Bug report — intention text box (Entry 6) | *(see `known-bugs.md` Saved Reply Mapping)* | `TechSupport SendUsScreenshot` if more detail is needed; no dedicated saved reply for this exact bug yet |
| Bug report — goal-setting freeze (Entry 8) | *(see `known-bugs.md` Saved Reply Mapping)* | `TechSupport SendUsScreenshot` to request platform/app version; `TechSupport med_stats_bug` as a generic bug-acknowledgment reference only |

# Related Policies

- *Feedback Policy* (conduit framing for opt-out/removal requests; routing to design/engineering)
- *Known Bugs & Current Product Status* (Entries 6 and 8 — bug-specific scripts for this feature area)
- *Cancellation Policy* (if opt-out frustration turns into an actual cancellation request)
- *Escalation Policy* (for unlisted symptoms or PR-risk situations)
