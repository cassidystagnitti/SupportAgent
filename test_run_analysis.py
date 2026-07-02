"""Analyze Bert test run results: action log, policy gaps, new bugs, eval scorecard.

Thin backward-compat wrapper: the four `generate_*` report functions now live
in `eval_reports.py` (shared with `eval_run.py`, SUP-459). This script keeps
its original one-off behavior — reading `eval/2026-07-02/results.json` and
writing reports to the same directory.
"""

from __future__ import annotations

import json
import os

from eval_reports import (  # noqa: F401
    generate_action_log,
    generate_eval_scorecard,
    generate_new_bugs,
    generate_policy_gaps,
)

_DIR = os.path.dirname(os.path.abspath(__file__))
EVAL_DIR = os.path.join(_DIR, "eval", "2026-07-02")
RESULTS_PATH = os.path.join(EVAL_DIR, "results.json")


def load_results() -> list[dict]:
    with open(RESULTS_PATH, encoding="utf-8") as f:
        return json.load(f)


def main() -> None:
    results = load_results()
    print(f"Loaded {len(results)} results from {RESULTS_PATH}")

    outputs = {
        "action_log.md": generate_action_log(results),
        "policy_gaps.md": generate_policy_gaps(results),
        "new_bugs.md": generate_new_bugs(results),
        "eval_scorecard.md": generate_eval_scorecard(results, run_date="July 2, 2026"),
    }

    for filename, content in outputs.items():
        if not content:
            print(f"  {filename}: skipped (no content)")
            continue
        path = os.path.join(EVAL_DIR, filename)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        print(f"  {filename}: written ({len(content)} chars)")

    print(f"\nAll outputs in {EVAL_DIR}/")


if __name__ == "__main__":
    main()
