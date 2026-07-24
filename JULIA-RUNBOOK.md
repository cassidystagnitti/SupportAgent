# Bert Support Runbook — Daily Coverage

**For:** Julia, covering the Happier Meditation support mailbox while Cass is out.
**Rule of thumb:** Bert *drafts and researches* everything for you. Your job is to **review, approve/send, and handle the few things Bert flags.** When in doubt, **don't send — escalate.**

> ⚠️ **The single most important guardrail:** never send a reply you don't understand, and never override a Stripe refusal. A held ticket is fine; a wrong send to a customer is not.

---

## 0. Who to contact (fill this in before Cass leaves)

- **If you're stuck or unsure about a ticket:** `[ESCALATION CONTACT — name + Slack handle]`
- **If the system is broken (nothing posts, errors everywhere):** `[TECH CONTACT — name + Slack handle]`
- **Cass (emergencies only, on vacation):** `[how/whether to reach Cass]`

---

## 1. One-time setup (do this once, before your first morning)

You need these on your laptop:

- **Your own Claude Code + Claude subscription** (Max or Pro). The "thinking" part of the run bills to *your* account this way — that's intended.
- **Python 3.11**, **git**, and the **GitHub CLI (`gh`)**.
- **Access** to: the Happier Help Scout, the `tenpercenthappier` GitHub org, Linear, and the Slack `#claude-support` channel.

### Step 1 — Clone the repo

```bash
mkdir -p ~/code && cd ~/code
git clone https://github.com/cassidystagnitti/SupportAgent.git
cd SupportAgent
```

### Step 2 — Run the setup script

```bash
./setup-for-teammate.sh
```

This creates the Python environment, installs dependencies, and prints the exact next steps (including the Bash allow-rules you'll need, with *your* home path filled in). Follow what it prints.

### Step 3 — Add the secrets file

Cass will send you a `.env` file **securely** (password manager or an encrypted channel — never plain Slack/email). Save it as `~/code/SupportAgent/.env`. Do **not** commit it, forward it, or paste its contents anywhere.

Verify it loaded:

```bash
.venv/bin/python -c "from dotenv import load_dotenv; import os; load_dotenv(); print('OK' if os.getenv('ANTHROPIC_API_KEY') else 'MISSING KEY — ask Cass')"
```

### Step 4 — Connect your Claude Code environment

In **your** Claude Code:
- Log in with **your** Claude subscription.
- Connect the **Slack** and **Linear** connectors (so the run can research Linear and post the brief to `#claude-support`).
- Authenticate `gh`: `gh auth login` (choose the `tenpercenthappier` org).
- *(Optional)* Install the shareable support plugin: `/plugin install support@happier` — gives you `support-review` / `support-resolve` in Slack and Claude Code. See §6.

### Step 5 — Install the morning routine

The daily run is a scheduled Claude Code task. The setup script copies the task definition into `~/.claude/scheduled-tasks/daily-summary-run/` with your paths. To schedule it for **8:40am ET each weekday**, ask your Claude Code: `/schedule the daily-summary-run task for 8:40am ET on weekdays`.

> You can always run it by hand instead — see §5. During coverage week, running it manually when you sit down is perfectly fine and arguably safer (you're watching it live).

---

## 2. Your daily loop (the part that matters)

Every morning there are **two surfaces**:

- **Slack `#claude-support`** — the *brief*: a glanceable summary of the day (news, ticket buckets, policy questions, actions). This is your map.
- **Help Scout** — where the actual drafted replies live and where you send them. This is where you work.

**The flow:**

1. **Read the brief in `#claude-support`.** It has four sections:
   - **Daily brief** — what customer-facing bug fixes shipped / are in progress (so you know what to tell people).
   - **Three-bucket breakdown** — 🟩 auto-send / 🟨 needs-action / 🟥 escalated, with counts.
   - **Policy questions** — tickets waiting on a decision (these are escalated until answered).
   - **Actions** — (a) *Executed today* (cancels/refunds the run already did) and (b) *Needs a human*.

2. **Work the 🟩 auto-send bucket first (easy wins).** These are already drafted in Help Scout *and* checked by the verifier. Open each in Help Scout, **read the draft**, and if it looks right, **send it**. Light review — the verifier has already checked tone, policy, and any claimed Stripe facts.

3. **Work the 🟨 needs-action bucket.** These have a drafted reply *plus* a note saying what a human must do (e.g. a discount/coupon, an account merge, something Bert can't do automatically). Do the action if you can and it's clearly within policy; otherwise **hold and escalate** (§0).

4. **Work the 🟥 escalated bucket.** Judgment calls and anything with an **open policy question**. Don't guess — answer only if you're confident it's within documented policy; otherwise escalate.

5. **Verify the "Executed today" actions.** These are real cancels/refunds the run performed. Skim them against `data/stripe_action_log.jsonl` — if anything looks wrong (wrong customer, wrong amount), **do not send that ticket's reply** and escalate.

> The system **never sends on its own.** Everything waits for you to click send in Help Scout. Drafting ≠ sending.

---

## 3. Red flags — stop and escalate

- **A draft claims an action that didn't happen** (e.g. "I've refunded you" but the brief says the write was *blocked* or *failed*). **Do not send it.** Flag it to `[ESCALATION CONTACT]`.
- **A Stripe action was refused by the script** (window expired, dispute open, over the cap). The script is right — **do not try to force it.** Reply per the refusal guidance in the note, or escalate.
- **The brief didn't post** (no morning message in `#claude-support`, or the health ping says "didn't run"). Run it manually (§5). If it errors, contact `[TECH CONTACT]`.
- **A customer mentions a bank dispute / chargeback.** Never refund a disputed charge. Escalate.
- **Anything about "10% Happier" / Dan Harris / the podcast.** That's a *different company* — see the `happier-vs-10-percent-happier` policy. When unsure, escalate.

---

## 4. What NOT to do

- Don't send a reply you don't fully understand.
- Don't override a Stripe script refusal or edit a past-tense draft to claim an action that didn't run.
- Don't answer an open policy question you're not sure about — hold it.
- Don't hand the `.env` / any key to anyone or paste it anywhere.
- Don't auto-run anything for coupons/discounts, account merges, extensions, or comps — those are human judgment calls (they'll be in the 🟨/🟥 buckets).

---

## 5. Running the brief manually

If the scheduled run didn't fire, or you'd rather drive it yourself, in your Claude Code just say:

```
Run the daily-summary-run routine.
```

(It's the skill at `~/.claude/scheduled-tasks/daily-summary-run/`.) It will: research the day's shipped/in-progress customer-facing fixes → summarize the mailbox → draft every open ticket → execute any auto-runnable cancels/refunds → post the brief to `#claude-support`. It takes several minutes. Watch it; if it asks you something, answer plainly.

To *only* rebuild the mailbox index without drafting:

```bash
cd ~/code/SupportAgent && .venv/bin/python -m bert.summarize
```

---

## 6. Optional: the Slack / plugin path

If you'd rather work conversationally instead of running the full routine, install the support plugin (`/plugin install support@happier`) and use:
- **`support-review`** — summarize the mailbox and draft replies, same as the routine but interactive.
- **`support-resolve`** — walk through the low-confidence / flagged drafts one at a time.

Same underlying system; it just lets you drive it turn-by-turn from Slack or Claude Code. The daily brief still posts either way.

---

## 7. Glossary (quick)

- **Bert** — the support agent (this system). It drafts; it doesn't send.
- **Draft** — a reply saved in Help Scout, not sent. Nothing reaches a customer until you send it.
- **Three-bucket model** — every ticket ends up 🟩 auto-send (drafted + verified, just needs your send), 🟨 needs-action (a human must do something first), or 🟥 escalated (judgment call / open policy question).
- **Verifier** — an automated check that reads each auto-send draft against policy and confirms any Stripe facts before tagging it green. If it finds a problem, the ticket drops to 🟨 with a note.
- **Auto-send tag** — means the verifier passed it. It still doesn't send automatically — *you* send it.
