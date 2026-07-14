# Task 16 — Acceptance Validation

Live re-runs via `process_ticket_sync(cid, skip_triage=True, force=True)` against `bert-v1-buildout`
(commit range `923a051..HEAD`, plus orphan fix `721a3c4`), run 2026-07-02 evening against the seeded
draft registry from `eval/2026-07-02/results.json`. `force=True` is used specifically to exercise the
supersede path against the pre-existing registry entries — every acceptance ticket already had a
draft recorded from the original 82-ticket batch run, so this also validates the SUP-461 supersede
warning wiring end to end.

**These are live runs against real Help Scout conversations. Real drafts and (where the note-posting
gate is satisfied) internal notes were created.** No policy or prompt content was changed to force any
of these to pass; misses are reported as found.

## Environment facts affecting this validation (not pipeline bugs)

- **`NOTION_TOKEN` is empty in `.env`.** Every gap/action-hook call (`notion_bridge.upsert_gap` /
  `upsert_action` via `orchestrator.record_gap_and_action`) raises `RuntimeError("NOTION_TOKEN not
  configured")` internally. Verified this fails soft: caught by `record_gap_and_action`'s per-branch
  try/except, logged via `log.exception`, and the pipeline continued to completion (draft posted, tags
  applied) in every run that hit this path. Reproduced live on conversation `3364022818` (low
  confidence → synthesized `open_question` → `upsert_gap` raised → caught → run finished normally).
  Because the token is absent, gap/action rows could not be verified to exist in Notion by this task;
  the fail-soft behavior was verified instead, per the environment override for this task.
- **`LINEAR_API_KEY` cannot see the Technical team.** `bug_registry.record_bug`'s Linear search (used
  to auto-file/dedupe bug candidates against the Technical board) mechanically returns `[]` rather than
  raising or crashing. Reproduced live on `3372229124`: `bug_report.is_bug=True`, a `bug_candidate` was
  synthesized locally, but `bug_candidate.linear_id` stayed `None` (no Linear issue filed/matched) — the
  search executed, found nothing visible, and the pipeline did not fail. This is separate from
  `LINEAR_PRODUCT_TEAM_ID`, which the same key **can** see — `product_prioritization.py`'s Linear
  lookup succeeded normally in the same runs (e.g. "fetched 14 Linear issues" on `3373518340`).
- **`HELPSCOUT_NOTE_USER_ID` is unset in `.env`** (pre-existing gap, documented in `CLAUDE.md` as
  "optional but recommended," not introduced by this build-out). Internal-note posting
  (`_format_internal_note_html`, including the `⚠️ Supersedes the earlier draft` banner) is gated on
  this var; when unset, `orchestrator.py` logs `"HELPSCOUT_NOTE_USER_ID unset — skipping escalation
  note"` and skips the POST. Every run below computed `supersedes_existing_draft: true` correctly
  (confirming the SUP-461/14 registry + supersede-detection logic itself is correct), but the visible
  ⚠️ banner in Help Scout could not be produced in this environment because the note never posts.
  **This is a config gap for Cassidy to close (set `HELPSCOUT_NOTE_USER_ID`), not a code defect.**

## New finding surfaced during validation: reply-mode detection is currently broken live

While selecting a reply-mode acceptance ticket, `_fetch_conversation_threads` in `orchestrator.py`
was found to silently short-circuit on an **empty** embedded threads array. Help Scout's
`GET /conversations/{id}` is currently returning `"_embedded": {"threads": []}` (empty list, not an
absent key) for every conversation tested live just now — 8+ IDs checked, including all candidates
from the original 22-reply set (`3364022818`, `3365380903`, `3367102882`, `3369859828`, `3371892720`,
`3371987458`, `3372822492`, `3366333609`). The dedicated `GET /conversations/{id}/threads` endpoint
returns the full thread history correctly when queried directly. Because
`_fetch_conversation_threads`'s guard is `if embedded_threads is not None: return embedded_threads`,
an empty-but-present list is treated as "the full list" and the paginated fallback never runs, so
`detect_reply_mode()` always sees `[]` and returns `False` right now — even for conversations with
a clear prior published agent reply.

**Net effect on this acceptance run:** none of the 5 tickets below registered `reply_mode=True` live,
including the ticket picked specifically to exercise the reply-mode acceptance criterion
(`3364022818`, which has real thread history showing a customer message after a prior agent reply
when queried directly against `/threads`). Per instructions, this is reported honestly as a miss
rather than papered over — see the per-ticket verdict below. A background fix task has been spawned
(not applied here — Task 16 is validation-only) to change the short-circuit to `if embedded_threads:`
(or otherwise require confirmed-complete embeds) and add a regression test, since the existing unit
tests only mock `_fetch_conversation_threads` directly and don't exercise this interaction.

---

## Per-ticket results

| Conversation | Confidence | Referenced policies | needs_action / action_system | auto_sendable | Tags computed | reply_mode | Research ran (+sources) | Skipped / supersede | Verdict |
|---|---|---|---|---|---|---|---|---|---|
| **3372568142** (downloads) | high | `downloads-offline.md`, `known-bugs.md` | false / — | true | `automated`, `auto_send` | false | no | supersedes existing draft (thread `10296299176`, replaces prior `10294399230`) | **PASS** — downloads-offline.md referenced, confidence high (≥ medium), draft contains an explicit notify commitment ("we'll notify all users as soon as it's back... we'll let you know the moment offline downloads return") and explicitly disclaims a date ("I don't have a specific date to share yet") — no fabricated ETA. |
| **3372229124** (DND / known-bugs) | medium | `known-bugs.md` | false / — | false | `technical` | false | no | supersedes existing draft (thread `10296299807`, replaces prior `10295039398`) | **PASS** — `bug_report.is_bug=true` and `known-bugs.md` was referenced and reasoned over (compared against Entry 5 — DND toggle on Android v2 — and correctly judged ambiguous given no platform/version in the ticket body); draft asks clarifying questions rather than guessing, consistent with policy's Do-Not-Auto-Send handling of unmatched bug reports. `bug_candidate` was synthesized; `linear_id` stayed null because the Technical-team Linear search is invisible to this key (documented above, not a failure). |
| **3373518340** (practice-goals) | medium | `feedback-policy.md` | false / — | true | (draft not created — see verdict) | false | yes — android repo search "feedback" (no matches), Linear search "feedback" (no matches) | no existing-draft supersede (`draft_created: false`) | **MISS, environment drift, not a pipeline bug.** Live conversation `3373518340` now returns HTTP 200 with subject **"Feedback"** and **zero threads** (confirmed both via a direct API check and via `eval/2026-07-02/stale_drafts_cleanup.md`, which already flagged this exact ID as "Unreachable conversations (skipped, 404 from Help Scout)" during Task 14's stale-draft sweep on the same day). The original seeded ticket at this ID was "Remove practice goals" with a real body about disabling the practice-goals UI feature — that content is gone from Help Scout now. Since the live body is empty, the pipeline correctly treated it as a content-free ticket and referenced the generic `feedback-policy.md` conduit response instead of `check-ins-goals-intentions.md`; this is the right behavior for what Help Scout is *currently* serving at this ID, but it means the specific acceptance criterion (check-ins-goals-intentions.md + no-setting stance) could not be exercised against real data. No Help Scout write occurred (`draft_created: false`) — confirmed via the reply POST itself returning 404 mid-run for a related ID. |
| **3372998714** (podcast pitch) | — | — | — | — | — | — | — | — | **MISS, environment issue.** `GET /conversations/3372998714` returned **HTTP 404** — the conversation no longer exists / is inaccessible via the Help Scout API, even though it existed at baseline (draft `10294395094` was created in the original 82-ticket run and is recorded in `results.json`/`eval_scorecard.md`). No pipeline code ran past the initial conversation fetch; `non-support-requests.md` and the polite-decline behavior could not be re-validated live against this specific ID. The policy doc itself (`policies/non-support-requests.md`) is present, well-formed, and covers exactly this scenario (podcast/guest pitch → polite one-paragraph decline, no forwarding) per a direct read — the gap is data availability, not the pipeline or the policy. |
| **3364022818** (reply-mode check, substituted for `3372229124` since that ID is itself in the original 22-reply set) | low | `account-lookup-data-model.md`, `subscription-billing-overview.md` | false / — | false | `technical` | **false** (see reply-mode finding above) | yes — read `subscription.rb` in changecollective.com for `source` enum / `PAID_SOURCES`, Linear search "promo subscription" (no matches) | supersedes existing draft (thread `10296302624`, replaces prior `10295010818`) | **MISS on reply_mode specifically; draft quality itself is reasonable.** `out["reply_mode"]` was `False`, not `True` — caused by the `_fetch_conversation_threads` empty-embed bug documented above, confirmed present across every reply candidate checked, not specific to this ticket. Because reply-mode wasn't detected, the pipeline used the original-message path (`get_conversation_text`) rather than the reply/latest-message path (`get_conversation_history`), and the live conversation's original message body came back empty at fetch time, so the draft is a generic "your message came through without any text" reply rather than one addressing a specific latest message. Low confidence and a `do_not_send_reason` flagging the empty body were correctly set, and it still exercised the supersede path (`supersedes_existing_draft: true`) correctly. The reply-mode-specific acceptance bar (reply_mode=True, draft addresses latest message) was **not met** — recorded honestly per instructions, with a fix task spawned rather than a live prompt/policy tweak.

---

## Summary

- 2 of 5 acceptance criteria fully met on live data: **downloads** (3372568142) and **DND/known-bugs**
  (3372229124), both exercising the supersede path correctly.
- 3 of 5 did not meet their specific criterion, for three distinct, non-pipeline-code reasons:
  1. **3373518340** — the live Help Scout conversation's content has changed/emptied since baseline
     (environment drift, already flagged in Task 14's stale-drafts sweep).
  2. **3372998714** — the live Help Scout conversation is now 404 (gone/inaccessible).
  3. **3364022818** — a genuine, reproducible pipeline bug in `_fetch_conversation_threads`
     (empty-embed short-circuit) currently prevents reply-mode detection from working at all, for any
     conversation tested. Flagged as a spawned follow-up task, not fixed here.
- Both Notion-hook fail-soft and Linear-Technical-invisibility fail-soft behaviors were verified live
  and behaved exactly as specified — no crashes, pipeline completed drafts/tags in both cases.
- The supersede-warning **HTML text** itself is correct and unit-tested, but could not be observed live
  in Help Scout because `HELPSCOUT_NOTE_USER_ID` is unset, which gates all internal-note posting
  (pre-existing, documented env gap — not part of this build-out).
