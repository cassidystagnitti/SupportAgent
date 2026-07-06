"""One-off: redraft the meditation-pausing tickets after known-bugs.md entry #1
was reopened (fix shipped but reports persist). force=True bypasses the
draft-registry duplicate guard and posts a fresh draft + supersede note.
"""
import json, os, sys, threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dotenv import load_dotenv

_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(_DIR, ".env"))
os.environ.setdefault("CLAUDE_DRAFT_MODEL", "claude-sonnet-5")

REDRAFT_IDS = [
    # Group A — drafts told the customer it's fixed / cited Entry 1 as Fixed
    "3374330906", "3375196346", "3375296440", "3375940863", "3376277126",
    "3376577808", "3377149056", "3377346995", "3377444590", "3377362766",
    # Ongoing pausing/stopping reports handled as new/unconfirmed under stale doc
    "3374720644", "3374894215", "3375387896", "3375464130", "3375690387",
    "3376148751", "3376178714", "3376362900", "3376382809", "3376876379",
    "3377072901", "3377073278", "3377305999",
]

results = {r["conversation_id"]: r for r in json.load(open(os.path.join(_DIR, "eval/2026-07-06/results.json")))}
_lock = threading.Lock()

def _log(m):
    with _lock:
        print(m, flush=True)

def redraft(cid):
    from orchestrator import process_ticket_sync
    email = (results.get(cid) or {}).get("customer_email")
    try:
        r = process_ticket_sync(cid, email, skip_triage=True, force=True, create_draft=True)
        br = r.get("bug_report") or {}
        _log(f"#{cid} conf={r.get('confidence')} auto={r.get('auto_sendable')} "
             f"supersede={r.get('supersedes_existing_draft')} matched={br.get('matches_known_bug')!r} "
             f"draft_id={r.get('helpscout_draft_id')}")
        return r
    except Exception as e:
        _log(f"#{cid} EXCEPTION: {e}")
        return {"conversation_id": cid, "error": str(e)}

def main():
    _log(f"Redrafting {len(REDRAFT_IDS)} pausing tickets (force=True, live)…\n")
    out = []
    with ThreadPoolExecutor(max_workers=5) as pool:
        futs = {pool.submit(redraft, cid): cid for cid in REDRAFT_IDS}
        for f in as_completed(futs):
            out.append(f.result())
    ok = sum(1 for r in out if r.get("draft_created") and not r.get("error"))
    err = sum(1 for r in out if r.get("error"))
    _log(f"\nDone. {ok} redrafted, {err} error(s).")
    json.dump(out, open(os.path.join(_DIR, "eval/2026-07-06/redraft_pausing_results.json"), "w"),
              indent=2, default=str)

if __name__ == "__main__":
    main()
