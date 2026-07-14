---
name: bert-hydrate-ticket
description: Use during the Bert morning review when Cassidy wants to dive into one specific ticket — pull its full context (thread, account, Stripe, reply-mode) into the session.
---

# Bert — Hydrate One Ticket (LAZY FETCH)

This is the deliberate exception to "the session doesn't hold every ticket." When Cassidy wants to look at a specific ticket, pull its full context in — just this one.

## How to run

Use `bert.pipeline.hydrate_ticket(session, conversation_id)`. It mirrors the production read path (conversation → threads → reply-mode → account lookup → Stripe enrichment for Stripe/gift tickets) with **no write side effects**. It returns:

```
{conversation_id, subject, customer_name, hs_customer_id, email, body,
 conversation_history, reply_mode, account_blob, stripe_block, existing_tags}
```

## What to do with it

- Read the ticket with Cassidy: what's really being asked, what the account state is.
- If the dive settles a bug-truth or context ("this is the streak bug, fixed 7/5"), append it to the standing brief (`bert.state.append_brief`) and save — so every draft downstream inherits it.
- Mark progress on the ticket with `bert.state.set_status(state, cid, hydrated=True)`.

Hydrate a few tickets a morning, not all of them — the fan-out hydrates the rest itself at draft time.
