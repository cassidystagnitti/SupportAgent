#!/usr/bin/env bash
#
# setup-for-teammate.sh — one-shot setup for running the Bert daily support brief
# from a teammate's laptop (coverage while the owner is out).
#
# It does the SAFE, mechanical parts (Python env, deps, task install) and PRINTS
# the steps that need a human decision or a secret (the .env, the write
# allow-rules, connectors). See JULIA-RUNBOOK.md for the full flow.
#
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CODE_HOME="$(dirname "$REPO_DIR")"
VENV="$REPO_DIR/.venv"
TASK_SRC="$REPO_DIR/deploy/daily-summary-run/SKILL.md"
TASK_DEST_DIR="$HOME/.claude/scheduled-tasks/daily-summary-run"

bold() { printf "\033[1m%s\033[0m\n" "$*"; }
warn() { printf "\033[33m%s\033[0m\n" "$*"; }
ok()   { printf "\033[32m%s\033[0m\n" "$*"; }

bold "== Bert teammate setup =="
echo "Repo:      $REPO_DIR"
echo "Code home: $CODE_HOME"
echo

# --- 1. Prereqs -------------------------------------------------------------
bold "1. Checking prerequisites"
missing=0
check() { if command -v "$1" >/dev/null 2>&1; then ok "  ✓ $1"; else warn "  ✗ $1 — install it ($2)"; missing=1; fi; }
check git    "https://git-scm.com"
check gh     "https://cli.github.com  (then: gh auth login → tenpercenthappier)"
PY=""
for c in python3.11 python3; do if command -v "$c" >/dev/null 2>&1; then PY="$c"; break; fi; done
if [ -n "$PY" ]; then ok "  ✓ python ($PY — $($PY --version 2>&1))"; else warn "  ✗ python3.11 — install it"; missing=1; fi
if command -v claude >/dev/null 2>&1; then ok "  ✓ claude (Claude Code)"; else warn "  ✗ claude (Claude Code) — install & log in with YOUR Claude subscription"; fi
[ "$missing" -eq 1 ] && { warn "Install the missing tools above, then re-run."; exit 1; }
echo

# --- 2. Python env ----------------------------------------------------------
bold "2. Python environment"
if [ ! -d "$VENV" ]; then "$PY" -m venv "$VENV"; ok "  created .venv"; else ok "  .venv already exists"; fi
"$VENV/bin/pip" install --quiet --upgrade pip
"$VENV/bin/pip" install --quiet -r "$REPO_DIR/requirements.txt"
ok "  dependencies installed"
echo

# --- 3. Secrets check -------------------------------------------------------
bold "3. Secrets (.env)"
if [ -f "$REPO_DIR/.env" ]; then
  if "$VENV/bin/python" -c "from dotenv import load_dotenv; import os; load_dotenv('$REPO_DIR/.env'); exit(0 if os.getenv('ANTHROPIC_API_KEY') else 1)"; then
    ok "  ✓ .env present and ANTHROPIC_API_KEY is set"
  else
    warn "  .env present but ANTHROPIC_API_KEY missing — ask Cass for a complete .env"
  fi
else
  warn "  ✗ No .env yet. Cass must send you one SECURELY (password manager)."
  warn "    Save it as: $REPO_DIR/.env   (never commit or forward it)"
fi
echo

# --- 4. Install the morning routine ----------------------------------------
bold "4. Morning routine (scheduled task)"
mkdir -p "$TASK_DEST_DIR"
sed "s#__CODE_HOME__#$CODE_HOME#g" "$TASK_SRC" > "$TASK_DEST_DIR/SKILL.md"
ok "  installed → $TASK_DEST_DIR/SKILL.md  (paths point at $CODE_HOME)"
echo "  To schedule 8:40am ET weekdays, tell your Claude Code:"
echo "      /schedule the daily-summary-run task for 8:40am ET on weekdays"
echo "  (or just run it by hand each morning — see JULIA-RUNBOOK.md §5)"
echo

# --- 5. Write allow-rules (print, do not guess) -----------------------------
bold "5. Stripe write allow-rules  ⚠️ VERIFY THESE"
CANCEL="$VENV/bin/python $REPO_DIR/scripts/stripe_cancel_subscription.py"
REFUND="$VENV/bin/python $REPO_DIR/scripts/stripe_refund.py"
cat <<EOF
  The routine auto-runs cancels/refunds. Claude Code must be allowed to run the
  two write scripts unattended, or they'll be blocked (and — because the owner is
  away — writes would silently fail). Add these to:
      $CODE_HOME/.claude/settings.local.json

  {
    "permissions": {
      "allow": [
        "Bash($CANCEL:*)",
        "Bash($REFUND:*)"
      ]
    }
  }

EOF
warn "  BEFORE relying on the routine, TEST that a write isn't blocked:"
echo  "    1) dry run (safe):  $CANCEL --help"
echo  "    2) have Cass confirm one real --apply on a test conversation is NOT blocked."
warn "  If a write is blocked, the rule syntax/path is off — fix it before the owner leaves."
echo

# --- 6. What's left (human steps) ------------------------------------------
bold "6. Finish in your Claude Code (see JULIA-RUNBOOK.md §1)"
echo "  • Log in with YOUR Claude subscription (orchestrator bills to your account)."
echo "  • Connect the Slack + Linear connectors (research + posting to #claude-support)."
echo "  • gh auth login  → tenpercenthappier"
echo "  • (optional) /plugin install support@happier"
echo
ok "Setup script done. Read JULIA-RUNBOOK.md next."
