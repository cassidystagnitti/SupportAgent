#!/usr/bin/env python3
"""Estimate the ANTHROPIC_API_KEY (fan-out) cost of the daily support runs.

Reads the morning-review state files (``data/morning_review/<date>.json``) and
counts the actual per-run Claude calls that hit the API key — summaries (Haiku),
drafts, verifies, and repairs (Sonnet) — then prices them with per-call rates
calibrated from the 2026-07-06 eval scorecard (per draft: ~941 fresh input +
~87.6k cache-read + ~2,370 output; verify/repair similar).

This covers the *fan-out* only — the part billed to the metered API key. The
orchestrator (research + brief assembly) runs on the operator's Claude
subscription and is NOT included here.

It's an estimate: the daily run does not persist exact per-call token usage, so
costs come from real call *counts* × calibrated per-call averages. For exact
token totals on a sample, run ``eval_run.py`` (it records real usage).

Usage:
    python3 scripts/weekly_cost_report.py                 # last 7 days, intro pricing
    python3 scripts/weekly_cost_report.py --since 2026-07-21 --until 2026-07-25
    python3 scripts/weekly_cost_report.py --pricing standard
"""
from __future__ import annotations

import argparse
import glob
import json
import os
from datetime import date, datetime, timedelta

STATE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         "data", "morning_review")

# Per-1M-token rates. Intro Sonnet 5 pricing runs through 2026-08-31.
PRICING = {
    "intro":    {"sonnet_in": 2.0, "sonnet_out": 10.0, "haiku_in": 1.0, "haiku_out": 5.0},
    "standard": {"sonnet_in": 3.0, "sonnet_out": 15.0, "haiku_in": 1.0, "haiku_out": 5.0},
}
# Calibrated per-call token shapes (from the eval scorecard + verifier config).
DRAFT  = {"fresh_in": 941,   "cache_read": 87_640, "out": 2_370}
VERIFY = {"fresh_in": 2_000, "cache_read": 87_640, "out": 3_000}
REPAIR = {"fresh_in": 941,   "cache_read": 87_640, "out": 2_370}
SUMMARY = {"in": 1_800, "out": 150}          # Haiku, no caching
CACHE_READ_MULT = 0.1                          # cache reads bill at ~0.1x input


def _sonnet_cost(shape: dict, p: dict) -> float:
    return (shape["fresh_in"] * p["sonnet_in"]
            + shape["cache_read"] * p["sonnet_in"] * CACHE_READ_MULT
            + shape["out"] * p["sonnet_out"]) / 1_000_000


def _haiku_cost(shape: dict, p: dict) -> float:
    return (shape["in"] * p["haiku_in"] + shape["out"] * p["haiku_out"]) / 1_000_000


def _counts(state: dict) -> dict:
    st = state.get("statuses", {}) or {}
    recs = state.get("records", []) or []
    drafted = sum(1 for v in st.values()
                  if v.get("drafted") or v.get("draft_action") in ("created", "updated", "superseded"))
    verified = sum(1 for v in st.values() if v.get("verify_verdict"))
    repairs = sum(int(v.get("verify_repairs") or 0) for v in st.values())
    return {"summaries": len(recs), "drafts": drafted, "verifies": verified, "repairs": repairs}


def _day_cost(counts: dict, p: dict) -> float:
    return (counts["summaries"] * _haiku_cost(SUMMARY, p)
            + counts["drafts"] * _sonnet_cost(DRAFT, p)
            + counts["verifies"] * _sonnet_cost(VERIFY, p)
            + counts["repairs"] * _sonnet_cost(REPAIR, p))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", help="YYYY-MM-DD (default: 7 days ago)")
    ap.add_argument("--until", help="YYYY-MM-DD (default: today)")
    ap.add_argument("--pricing", choices=["intro", "standard"], default="intro")
    args = ap.parse_args()

    until = datetime.strptime(args.until, "%Y-%m-%d").date() if args.until else date.today()
    since = datetime.strptime(args.since, "%Y-%m-%d").date() if args.since else until - timedelta(days=7)
    p = PRICING[args.pricing]

    rows, totals = [], {"summaries": 0, "drafts": 0, "verifies": 0, "repairs": 0, "cost": 0.0}
    for path in sorted(glob.glob(os.path.join(STATE_DIR, "*.json"))):
        d = os.path.splitext(os.path.basename(path))[0]
        try:
            day = datetime.strptime(d, "%Y-%m-%d").date()
        except ValueError:
            continue
        if not (since <= day <= until):
            continue
        try:
            state = json.load(open(path))
        except (OSError, json.JSONDecodeError):
            continue
        c = _counts(state)
        cost = _day_cost(c, p)
        rows.append((d, c, cost))
        for k in ("summaries", "drafts", "verifies", "repairs"):
            totals[k] += c[k]
        totals["cost"] += cost

    print(f"Fan-out API cost — {since} to {until}  ({args.pricing} pricing)")
    print("-" * 72)
    print(f"{'date':<12}{'tickets':>8}{'drafts':>8}{'verify':>8}{'repair':>8}{'cost':>12}")
    for d, c, cost in rows:
        print(f"{d:<12}{c['summaries']:>8}{c['drafts']:>8}{c['verifies']:>8}{c['repairs']:>8}{'$'+format(cost, '.2f'):>12}")
    print("-" * 72)
    print(f"{'TOTAL':<12}{totals['summaries']:>8}{totals['drafts']:>8}{totals['verifies']:>8}"
          f"{totals['repairs']:>8}{'$'+format(totals['cost'], '.2f'):>12}")
    print()
    print("Note: fan-out (API key) only; the orchestrator runs on the Claude subscription.")
    print("Estimate from real call counts × eval-calibrated per-call averages, not logged tokens.")


if __name__ == "__main__":
    main()
