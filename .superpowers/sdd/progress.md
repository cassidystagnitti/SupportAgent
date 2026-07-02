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
