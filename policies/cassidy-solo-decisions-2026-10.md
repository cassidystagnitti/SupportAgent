# Cassidy's solo decisions — Oct 8–9, 2026 (index)

**Purpose:** every case below used to be held for Cassidy. She decided them on Oct 8–9, 2026 and wants Berts to handle them **solo** from now on: do the work, send, close, internal note, clear claim/tags. Each line points to the policy that holds the full rule. Where a policy says something older that conflicts, this index and the dated section in that policy win.

| # | Case | Solo rule | Full rule |
|---|---|---|---|
| 1 | Every ticket | Add every email seen (from, Account/footer, CCs, relay, thread, admin/Stripe lookups) to the HS profile before any work, even when escalating/moving/holding. Spam is the only skip. | CLAUDE.md; *Account Lookup Data Model* |
| 2 | Hardship / need-based Comp ask | Grant on the existing admin user, verify, send, close. Lean generous. **Only denials** hold for Cassidy. | *Need-Based Complimentary Subscriptions* |
| 3a | In-window Stripe refund (30d annual / 24h monthly, to first customer email) | Refund + cancel now via `stripe_refund.py`, verify, send, close. Never ask. Includes a Stripe + Apple double charge on one account (refund/cancel Stripe, leave Apple). | *Refund Policy* (2026-10-08/09 section) |
| 3b | Up to 5 days past the annual window with a mitigating reason (our error/delay, renewal notice to a hidden relay email, hardship) | `stripe_refund.py --and-cancel-now --mitigated-grace "<reason>"` (cap 35 days; logged). Identity must clearly match. >5 days or no reason → Cassidy. | *Refund Policy* |
| 4 | Pro-rated / partial refund ask | We never pro-rate. In-window → full refund + cancel, solo. Past window → decline pro-ration, turn off auto-renew. | *Refund Policy* |
| 5 | Accepts the 40% offer after we canceled | `cancel_at_period_end=false`, apply coupon `9UdSyyhB`, verify preview invoice = $59.99, send, close. | *Cancellation Policy* |
| 6 | Two accounts from Sign in with Apple / Hide My Email + Apple purchase | Explanation reply (two accounts, how, SIWA + HME, Apple refund steps, cancel Apple renewal, sign in with email+password). | *Login Issues*; `docs/reply-templates/siwa-two-accounts-apple-purchase.md` |
| 7 | Dispute / charge where we only see an expired sub and no matching charge | `CancelRefund PlatformUnclearRefund` adjusted (one account, expired sub, nothing matches; Apple route; ask for receipt/last 4/date/amount/descriptor/other emails). Close. | *Refund Policy*; *Escalation Policy* |
| 8 | Apple employee-benefit charge (signups.apple.com / Challenge token, then App Store charge) | Move to mailbox 201086 with a note; no reply. | *Apple Mailbox Overview* |
| 9 | Unsolicited security / bug-bounty report | Spam, no reply. | *Non-Support Requests* |
| 10 | New reproducible bug | Standing yes to file Linear: dedupe first (incl. same-day digest issues), reproduce on web as `supportbot@meditatehappier.com`, steps + screenshots + HS link + code location; ack + close. | *Known Bugs*; CLAUDE.md |
| 11 | Missing days / streak | Add each single missing day in admin (even months back); that restores the streak; never say we can't restore. Grief context: gentle reply, no platitudes, solo. >3 consecutive missing days → Cassidy. | *Meditation History & Streaks*; *Grief and Loss Content* |
| 12 | "Respond to this email only" | Reply only to that address: send with `customer: {"email": …}` (no id), no CC/BCC; verify the published thread. | *Account Lookup Data Model* |
| 13 | Gift certificate PDF resend | `Get GiftCertificateCopy` + PDF attached per `resend-happier-gift-certificate-pdf`; verify the attachment on the thread before closing. | *Gift Subscriptions* |
| 14 | B2B team-member removal (not seat reduction) | Note for Cassidy to remove members in admin; once she confirms, the reply (members removed, seats stay the same unless they ask to reduce) is pre-approved — send, close. | *Escalation Policy* |
| 15 | Deletion with an active sub; third-party erasures (McAfee, PrivacyHawk, Yorba) | Turn off auto-renew + `DeleteAccountActiveSubscription` ack (solo) → on confirm, hold for Cassidy to delete → after she deletes, verify gone and send `DeleteAccountCompletedByUs`. | *Account Deletion* |
| 16 | Marketing-list removal for a deleted account | Braze is retired: confirm removal as completed, solo. | *Account Deletion* |
| 17 | Google Play refund / cancel | Cassidy does the Play Console part; Bert holds with one note, then sends the reply when she says it's done (no draft review). | *Cancellation Policy*; *Refund Policy* |
| 18 | "Is Happier taking a pause / shutting down?" | Warm short reply: not pausing, still producing new content, not sure what they heard, we haven't said that, happy to answer questions. | *Feedback Policy*; `docs/reply-templates/happier-pause-rumor.md` |
| 19 | Hardship at renewal | 40% coupon on the upcoming renewal, verify, send, close (Comp if they can't pay at all; also solo). | *Renewal Discount Requests* |
| 20 | Google sub already off | Confirm with the end date, solo. | *Cancellation Policy* |

**Still Cassidy's (unchanged):** Comp/hardship denials; refunds more than 5 days past the window or without a mitigating reason; Play Console actions; account deletion itself; admin team-member removal; seat-count reductions; >3-consecutive-day history gaps; legal threats; disputes on a charge we can find; truly unknown tickets.
