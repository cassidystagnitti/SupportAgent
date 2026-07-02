# Bert Test Run — Progress Ledger

Plan: docs/superpowers/plans/2026-07-02-bert-test-run.md

Task 1: complete — company context appended to prompts/draft_system_prompt.txt
Task 2: complete — test_run.py created, 82/82 tickets drafted, 0 errors, results in eval/2026-07-02/results.json
  Note: product_prioritization.py has ThinkingBlock bug with Sonnet 5 (spawned fix task)
  Stats: 41 high, 27 medium, 14 low confidence | 52 auto-sendable | 28 needs_action | 21 streak-related
Task 2b: complete — fix_reply_drafts.py re-ran 22 reply tickets with is_reply=True, results.json updated
  Note: Help Scout API doesn't support DELETE on draft threads — old drafts remain, new correct ones added on top

# Bert v1 Build-Out — Progress Ledger
Plan: docs/superpowers/plans/2026-07-02-bert-v1-buildout.md
Branch: bert-v1-buildout (baseline commit above)
Task 1: complete (commits 923a051..eeb5aee, review clean)
Task 2: complete — reply mode derived from conversation threads (SUP-447); detect_reply_mode() in orchestrator.py, webhook event already whitelisted, 18/19 tests pass (pre-existing unrelated failure in test_maven_orchestrator.py)
Task 2: complete (commits eeb5aee..07a2ee3, review clean after fix: duplicate thread fetch eliminated)
  Minor for final review: (a) redundant reply-mode instruction — REPLY_MODE_PROMPT_PREFIX overlaps _build_dynamic_user_message's follow-up text (orchestrator.py:287-291 vs 395-399); (b) _fetch_conversation_threads has no direct unit test (pagination/embedded short-circuit)
Task 3: complete (commits 07a2ee3..c762453, review approved; composition risk resolved by controller — retry loops fixed-bound range(2))
  Minor for final review: (a) _format_internal_note_html doesn't show action_system; (b) test_run_analysis._guess_action_system now redundant
Task 4: complete (commits c762453..b61d412, review clean)
  Note for final review: triage_tickets/product_prioritization still default to claude-sonnet-4-6 (out of scope per spec; draft model only)
Task 5: complete (commits b61d412..355764f, review clean; Notion sync deferred to Task 7 by design)
Task 6: complete (commits 355764f..f9ff471, review clean; all saved-reply names verified real)
Task 7: complete (commits f9ff471..69dec3d, review clean; 4 policy pages LIVE in Notion via MCP connector)
  IMPORTANT: NOTION_TOKEN is ABSENT from .env — REST script + pipeline Notion writes need it. Manual step for Cassidy at the end.
  Minor for final review: dead-code truncation construct in sync script lines 159-167; _notion_headers duplicated with pull_policy_docs.py
Task 8: complete — notion_bridge.py (gap queue + action log) + process_answered_gaps.py write-back script (SUP-451/456)
  18/18 new tests pass, 44/45 full suite (pre-existing test_maven_orchestrator failure, out of scope)
  Live via MCP connector: Bert Ops page (391cffdf-527f-8127-9dc0-e9aa16830794) + Bert Gap Queue db (3d1669df-974c-46e6-b1f7-eb67033c2ad1) + Bert Action Log db (dbd2c888-6814-4987-ad7d-8e1a00097405) created under Support Policy Docs; schemas verified via notion-fetch; ids cached in data/notion_ids.json (force-added, data/ is gitignored)
  Still no NOTION_TOKEN in .env — upsert_gap/upsert_action/fetch_answered_gaps/mark_incorporated REST paths are unit-tested (payload builders) but not live-tested end-to-end; will work once token is added
Task 8: complete (commits 69dec3d..efad22c, review clean)
  Live: Bert Ops page 391cffdf-527f-8127-9dc0-e9aa16830794, Gap DB 3d1669df-974c-46e6-b1f7-eb67033c2ad1, Action DB dbd2c888-6814-4987-ad7d-8e1a00097405; IDs cached in data/notion_ids.json
  Minor for final review: _target_doc_path exact-match only; _request post-loop raise style
Task 9: complete (commits efad22c..ed0d1c1, review clean; bug_report sink lands in Task 13 by design)
Task 10: complete — action_executor.py scaffold (ActionPlan, prepare_coupon, prepare_cancellation, execute gated on STRIPE_WRITE_API_KEY + ACTION_EXECUTION_ENABLED=true, format_actions_note) + "Actions needed" section prepended to internal note (SUP-457)
  13/13 new tests pass, 65/66 full suite (pre-existing test_maven_orchestrator failure, out of scope)
  stripe_context.py key mapping: brief's `customer_id` -> real `stripe_customer_id`; `subscription_id` matches as-is
  execute() still raises NotImplementedError past the env gate — no real Stripe write calls yet (write key pending approval)
