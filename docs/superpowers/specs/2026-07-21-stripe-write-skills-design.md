# Stripe Write Skills — Design (2026-07-21)

## Goal

Give Bert the ability to execute the recurring Stripe actions from "Actions needed"
notes — without handing Claude a general-purpose Stripe key. Every write goes through
a purpose-built script (exposed as a skill) that enforces policy parameters in code.
Claude picks the script and arguments; the script decides whether the action is
legal. `action_executor.execute()`'s env gates (`STRIPE_WRITE_API_KEY` +
`ACTION_EXECUTION_ENABLED`) remain the master switch.

## Evidence: what the notes actually ask for

### Live mailbox scan — 2026-07-21 (evening)

25 of 78 active conversations carry an "Actions needed" note. Stripe-actionable
items, mapped to the skills below:

- **Turn off auto-renew / cancel** ×5 — #3390692208 (`sub_1RfxVK…`), #3391134628
  (`sub_JueiBY…`), #3392053928 (trial sub), #3390232067 (conditional: cancel if
  today's renewal hasn't charged), #3393162231 (chargeback threat → escalation
  first, then cancel).
- **Full refund, usually + cancel** ×3 — #3385520077 (refund renewal + cancel
  immediately + bug flag), #3390232067 (refund $59.99 if already charged),
  #3390548887 (refund once account located).
- **Reactivate (auto-renew back on)** ×1 — #3391273650.
- **Apply 40% renewal coupon** ×1 — #3391273650 (same ticket, combo with
  reactivate — exactly eval ticket #3375785121's shape).
- **Update payment method / send update-card path** ×1 — #3387811788 (in-app
  option missing for the customer; renewal 7/30). New category — see Deferred.

Everything else: comp grants via admin tool ×5 (#3377030109, #3390986334,
#3391273364, #3392279170, #3392990285) · Happier-admin streak/history/account
fixes ×5 · Google Play cancel ×1 (#3391170406) · engineering/bug/await-info ×5 ·
senior-judgment edge cases ×2.

### Eval-run history (corroborates the distribution)

**2026-07-02 (30 tickets):** apply coupon / turn off auto-renew ×5 · process
cancellation ×5 · refund investigation ×3 · Happier-admin streak fixes ×12 · bug
reports ×5.

**2026-07-06 (23 tickets):** full refund + immediate cancel ("Finish Now") ×1 ·
40% partial refund + reverse an erroneous cancellation ×1 · cancel trial before
conversion (locate sub by card last4) ×1 · comp extension / comp annual ×2 ·
Google Play refunds/cancels ×4 · Happier-admin history/streak fixes ×6 ·
engineering bug filings ×6 · multi-account investigations ×2.

### What a Stripe write key can and cannot cover

Stable across the live scan and both eval runs:

| Bucket | Share of actions | Stripe key? |
|---|---|---|
| Stripe subscription/refund writes | ~35–40% | Yes — this design |
| Happier admin (streaks, history, comps, merges) | ~35–40% | No — internal admin tool (comps corrected to admin-tool 2026-07-20) |
| Google Play refunds/cancels | ~5–15% | No — Play console, stays human |
| Engineering/bug filing/investigations | ~10–20% | No — Linear (already built) |

## Skills to build (phase 1)

All scripts share the common harness (see Guardrail architecture). Frequency-ordered:

### 1. `stripe_cancel_subscription.py` — highest volume
Turn off auto-renew (`cancel_at_period_end=true`).
- Default is ALWAYS at period end. `--immediately` is accepted only when
  `subscription.status ∈ {past_due, unpaid}` (the dunning rule in
  cancellation-policy.md); any other immediate termination must go through the
  refund script's `--and-cancel-now`.
- Idempotent: auto-renew already off → success, no write; print expiration date
  (the reply needs it in natural language).
- Works for trial cancellation too (trialing status, before conversion).

### 2. `stripe_apply_discount.py` — harden `apply_renewal_coupon.py`
Apply the 40/50% renewal discount (Paths 1 & 3, forever variants).
- **Coupon allowlist**: exactly four named tiers → coupon IDs pinned in the script
  (`40-once`, `40-forever`, `50-once`, `50-forever`). Arbitrary coupon IDs refused.
- Annual plans only (renewal-discount policy does not apply to monthly).
- Keep existing safeties: skip if same coupon present; refuse to replace a
  different discount without `--replace-existing`; single email per invocation
  (`--emails-file` batch mode is human-run only, not exposed to the skill).

### 3. `stripe_refund.py` — full refund, window-enforced
- Window computed by the script from the Stripe charge timestamp — never from
  model-supplied dates: 30 days annual / 24 hours monthly, `--boundary-grace`
  allows exactly +1 day/hour (the "be generous at day 30" rule).
- Full amount of the charge only. Any other amount refused (no proration, ever —
  the only partial is script 4).
- Refuses if the charge is disputed (chargeback → accept dispute in dashboard,
  human) or already refunded.
- `--and-cancel-now`: the "Finish Now" combo — refund + immediate cancellation
  in one audited step.

### 4. `stripe_partial_refund_40.py` — Path 2 retroactive discount
- Amount is computed, not supplied: `round(0.40 × last_invoice.amount_paid)`.
- **Hard-fails if the last invoice already carried a coupon** — reuses
  `stripe_context._fetch_last_invoice` (`amount_paid`, `coupon_name`,
  `percent_off`). This is the exact HS #3377107792 failure mode the policy
  calls out; the guard is code, not prompt.
- Only within 30 days of that invoice's charge (retry-window successful-charge
  date counts, per policy).

### 5. `stripe_reactivate_subscription.py` — undo an erroneous cancellation
- Sets `cancel_at_period_end=false` on a still-active subscription.
- Refuses fully-canceled/suspended subs (policy: no restoring old subscriptions
  after suspension — that's a new-subscription conversation).

### 6. `stripe_retry_payment.py` — dunning manual retry
- Pays the latest open invoice only when `status ∈ {past_due, unpaid}`.
- Registry-capped (e.g., max 2 manual retries per subscription) — policy says
  don't keep retrying a failing card; send them to their bank.

### Deferred (phase 2, or never)
- **Update-card path (billing portal)** — surfaced live 2026-07-21
  (#3387811788: in-app update option missing for the customer). Researched
  2026-07-22, two flavors:
  1. **Per-customer deep link** — `BillingPortal.Session.create(customer=…,
     flow_data={type: "payment_method_update"})` lands directly on the
     update-card screen. Needs **Customer portal: Write** on the write key
     (session creation is a POST; Read only covers portal configurations).
     Session URLs are documented as **short-lived**, so links must be minted
     at SEND time (sidebar chat button), never embedded in drafts that sit
     for hours. Precedent: the platform's own admin API already mints plain
     portal sessions (changecollective
     api/admin/v1/user/billing_portal_sessions_controller.rb).
  2. **No-code permanent login link** — one static Stripe-hosted URL per
     portal configuration (Dashboard → Settings → Billing → Customer portal;
     `login_page` on the configuration object). Customer enters their email,
     Stripe sends a sign-in link. Zero API scopes, never expires — safe to
     bake into policy docs / saved replies immediately.
  Either way, policies/failed-payment-dunning-stripe.md's "never invent web
  URLs" rule needs an explicit carve-out for Stripe-generated portal URLs
  before Bert drafts may include them.
- **Refund-and-resubscribe / plan switch** — creates subscriptions; needs price
  IDs and more thought. Keep human for now.
- **Comp subscriptions / extensions** — granted via the internal admin tool, not
  Stripe (corrected 2026-07-20). Out of Stripe scope entirely.
- **Dispute acceptance** — dashboard, human.
- **Google Play anything** — no API integration; Play console, human.

## Stripe restricted key (`STRIPE_WRITE_API_KEY`)

Request a restricted key with exactly (row names per the dashboard UI —
CORRECTED 2026-07-22: there is no standalone Refunds permission; refund creation
is governed by the charges/refunds row):

| Dashboard row | Permission | Used by |
|---|---|---|
| Customers | Read | email → customer lookup |
| Subscriptions | Write | cancel, coupon apply, reactivate, trial cancel, schedule release |
| Charges (charges / refunds) | **Write** | refund creation lives on this row; also charge lookup for window math |
| Invoices | Read → Write later | Read now for the last-invoice guard; bump to Write only when the dunning-retry script ships (`invoice.pay`) |
| Coupons | Read | allowlist verification (applying a coupon is Subscriptions: Write) |

Everything else **None** — explicitly: no Customers Write, no PaymentMethods, no
Payouts/Balance/Transfers, no Products/Prices Write, no Coupons Write (Claude can
apply the four sanctioned coupons, never mint new ones), no PaymentIntents Write.

Because refunds and charge creation share one permission row, the key alone
cannot express "refunds yes, new charges never" — that guarantee comes from the
script layer (no script constructs a charge, ever) plus the audit log. This is
the strongest argument for the wrapper-script design: Stripe's permission
granularity bottoms out exactly where our scripts pick up. Amount/velocity caps
are likewise inexpressible on keys and live in the script harness below.

**Env-var naming (found 2026-07-21, resolved 2026-07-22):** exactly two names,
by role — `STRIPE_READ_API_KEY` for enrichment (should hold a truly read-only
key), `STRIPE_WRITE_API_KEY` + `ACTION_EXECUTION_ENABLED=true` for the write
scripts. `STRIPE_API_KEY` is retired: `apply_renewal_coupon.py` (its only
consumer) now uses the same two-var write-gate contract as
`scripts/stripe_*.py`; delete the `.env` line and deactivate the old key in
the dashboard.

## Guardrail architecture (shared harness)

1. **Two-key separation.** `STRIPE_READ_API_KEY` stays for enrichment everywhere.
   `STRIPE_WRITE_API_KEY` is read only inside the action scripts, never exported
   into the general session env or printed.
2. **Dry-run by default.** Every script prints a plan (who, what, current state,
   amounts); mutation requires `--apply`. Same pattern as `apply_renewal_coupon.py`.
3. **Ticket-bound audit.** `--conversation-id` is required. On `--apply` the script
   (a) appends a JSON line to `data/stripe_action_log.jsonl` and (b) posts an HS
   internal note ("✅ Executed: …" with ids + amounts) via the existing note helper,
   so every write is visible on the ticket it served.
4. **Idempotency registry.** `action_registry` keyed by
   `(conversation_id, action_kind, subscription_id)` — a second `--apply` of the
   same action is a no-op with a loud warning. Prevents double refunds.
5. **Caps in code.** Refund ≤ the charge amount and ≤ $120 absolute (annual is
   $99.99); registry-enforced daily ceiling (e.g., >10 writes/day requires
   `--override-daily-cap`, which the skill docs tell Claude never to pass —
   it exists for Cassidy).
6. **Policy parameters are code, not prompt.** Coupon allowlist, refund windows
   from Stripe timestamps, 40% computed from `amount_paid`, immediate-cancel
   status gate. A wrong model belief can't move money.
7. **Master switch.** Scripts run the same gate as `action_executor.execute()`:
   both `STRIPE_WRITE_API_KEY` and `ACTION_EXECUTION_ENABLED=true` required.
8. **Claude Code permissions.** Allowlist only `python3 scripts/stripe_*.py …` in
   `.claude/settings.json`; ad-hoc `python -c "import stripe…"` stays behind a
   permission prompt. Each skill's SKILL.md mandates: dry-run → show Cassidy the
   plan (or auto-proceed only for classes the standing brief green-lights) →
   `--apply`.

## Rollout order

1. Issue the restricted key; set both env gates on the machine(s) that run Bert.
2. Ship scripts 1–2 (cancel, discount) — they cover ~2/3 of Stripe actions and
   are the most reversible. Run 1 week with dry-run-only skills (Bert prepares,
   Cassidy applies) to validate plans against what she would have done.
3. Enable `--apply` for 1–2; ship 3–5 (refunds, reactivate) with mandatory
   human confirm on refunds.
4. Script 6 (dunning retry) last — lowest volume, easy to add.
