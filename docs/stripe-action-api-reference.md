# Stripe API Calls for Bert's Action Categories

Reference for SUP-457 (action execution). Based on the 2026-07-02 test run's action log:
10 cancellations, 5 coupon/auto-renew requests, 3 refund investigations. All snippets
verified against the installed SDK (stripe-python 15.1.0). Applies to Stripe subscribers
only — Apple/Google subscriptions are not reachable from the backend.

Amounts are integer cents. Subscription/customer IDs come from `stripe_context.py`
enrichment (`subscription_id`, `stripe_customer_id`).

## Cancellations

```python
stripe.Subscription.modify("sub_XXX", cancel_at_period_end=True)
```
Schedules the cancellation for the end of the paid period, so the customer keeps the access they already paid for — the right call for nearly every "please cancel" ticket.

```python
stripe.Subscription.cancel("sub_XXX")
```
Ends the subscription immediately (no automatic refund of unused time) — only for explicit "cut me off now" requests, usually paired with a refund below.

```python
stripe.Subscription.modify("sub_XXX", cancel_at_period_end=False)
```
Un-schedules a pending cancellation when a customer changes their mind before the period ends.

## Retention discounts (coupon / "turn off auto-renew" saves)

```python
stripe.Subscription.modify("sub_XXX", discounts=[{"coupon": "RENEWAL40"}])
```
Applies the 40% renewal coupon to the subscription so the discount hits the next invoice — the standard save offer from the renewal-discount policy (`apply_renewal_coupon.py` already wraps this with eligibility checks).

```python
stripe.Subscription.delete_discount("sub_XXX")
```
Removes an existing discount from the subscription, needed before applying a different coupon when one is already present.

```python
stripe.Subscription.modify("sub_XXX", pause_collection={"behavior": "void"})
```
Pauses billing without cancelling (invoices are voided while paused) — a retention alternative for "I need a break" tickets; resume with `pause_collection=""`.

## Refund investigation + processing

```python
stripe.Charge.list(customer="cus_XXX", limit=10)
```
Lists the customer's recent charges with amounts, dates, and statuses — the first step of every "I was wrongly charged" investigation.

```python
stripe.Refund.create(charge="ch_XXX")
```
Refunds a specific charge in full back to the original payment method; add `amount=1250` for a partial refund (e.g. prorating unused time).

```python
stripe.Customer.create_balance_transaction("cus_XXX", amount=-1250, currency="usd")
```
Credits the customer's Stripe balance (negative = credit) so the amount offsets their next invoice — an alternative to a cash refund for goodwill adjustments.

## Read-only investigation (extends current enrichment)

```python
stripe.Invoice.create_preview(customer="cus_XXX", subscription="sub_XXX")
```
Previews the next invoice with all discounts applied, so a draft can state the exact amount the customer will actually be charged at renewal (already used by `stripe_context.py`).

```python
stripe.Invoice.list(customer="cus_XXX", limit=12)
```
Shows the customer's invoice history with paid/open/void status — how you diagnose failed-payment/dunning situations before they escalate.

```python
stripe.Customer.list(email="user@example.com", limit=1)
```
Looks up the Stripe customer by email — the entry point the pipeline already uses for enrichment.

## Restricted write-key scopes to request (for SUP-457)

Create at Dashboard → Developers → API keys → "Create restricted key". Minimum scopes for the calls above:

| Resource | Permission | Enables |
|---|---|---|
| Customers | Read | email lookup, balance reads |
| Subscriptions | **Write** | cancel, cancel_at_period_end, discounts, pause |
| Charges | Read | refund investigation |
| Refunds | **Write** | Refund.create |
| Invoices | Read | history + create_preview |
| Customer balance transactions | Write (optional) | goodwill credits |

Guardrails already designed into `action_executor.py`: execution requires both
`STRIPE_WRITE_API_KEY` and `ACTION_EXECUTION_ENABLED=true`; refunds stay
prepare-only (money movement remains human) in v1.
