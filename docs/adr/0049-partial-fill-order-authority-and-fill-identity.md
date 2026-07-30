# ADR 0049: Partial-Fill Order Authority and Durable Fill Identity

- Status: Accepted
- Date: 2026-07-30

## Context

Prepared execution previously admitted only the first whole Fill. Its pure Order reducer always produced `FILLED`, and both the
reducer and mutable Order entity reconstructed prior notional from a quantized average price. The transaction Store deduplicated
Update/Trade envelopes but had no durable identity for the external Fill business fact. A new Update and Trade ID could therefore
re-report one Venue Trade after restart without a durable duplicate/conflict decision.

## Decision

Each Fill is one immutable prepared/committed execution transaction. A committed transaction is never appended to or rewritten;
the Order is the cumulative authority across transactions. A transaction records this Fill's price, quantity and identity, while
the Order records cumulative filled/remaining quantity, fill count, exact `Σ(price × quantity)`, derived average price and last
Trade ID.

The canonical Fill business identity has schema version 1 and scope:

```text
runtime_id + gateway_id + account_id + order_id
+ (venue_trade_id else external_event_id else trade_id)
```

The authority is SHA-256 encoded as `EFILL-...`. Venue Trade ID has priority because it is the strongest venue business identity;
external event ID and local Trade ID are deterministic fallbacks. This identity does not replace the existing `ETX-...`
transaction ID: ETX identifies a Broker Update envelope transaction; EFILL identifies the underlying Fill business fact.

The Fill payload fingerprint is SHA-256 over canonical, key-sorted UTF-8 JSON. It includes Runtime/Gateway/Account/Order/Trade,
venue identities, exact price/quantity plus precision, event/init nanoseconds, source/external sequences, external event,
liquidity, reported fee evidence, reference price and metadata. Decimal values use fixed precision strings and enums use values.
Python `hash()` and `repr()` are forbidden.

Same identity plus same fingerprint is a duplicate and returns the existing transaction without sequence, Projection, Outbox or
Order changes. Same identity plus a different fingerprint is a fail-closed conflict. Transaction-envelope key conflicts retain
their stricter prepared authority/payload hash semantics.

Each Order Fill receives a durable, contiguous index starting at one. The Store validates `(runtime_id, order_id, fill_index)` in
the same commit lock/SQLite `BEGIN IMMEDIATE` boundary. Source sequence is Gateway/Account global, execution sequence is Runtime
global, and Update ID is not numeric; none can serve as a per-Order Fill index.

Average price is calculated only from exact cumulative `price × quantity`, with quantization at the final price construction.
Quantized average price is never used to reconstruct historical cumulative value. This makes serialize/restore/continued-Fill
results equal to direct recomputation.

`PENDING_CANCEL` plus a non-final Fill retains `PENDING_CANCEL` authority but emits `ORDER_PARTIALLY_FILLED`; a final Fill becomes
`FILLED` and emits `ORDER_FILLED`. Terminal and never-submitted Orders reject Fill.

## Compatibility and product gate

Pre-0049 unfilled snapshots derive fill count/value `0`; completed whole-fill snapshots derive count `1` and cumulative value
`average × filled`. When no historical Trade ID exists, an explicit legacy-missing marker is retained instead of fabricating an
identity. Legacy committed facts derive one Fill identity/index/value at read time. Historical rows are not rewritten and no new
SQLite table or checkpoint schema version is introduced.

PR4.3.1 deliberately does not open Runtime product partial fills. The pure Order Authority, committed fact and Store support the
foundation, but the complete Planner returns `PARTIAL_FILL_ACCOUNTING_NOT_READY` before commit because Account/Strategy/Risk
Reservation, active-order Risk, fee accrual, Account and Ledger still lack incremental consumption. PR4.3.2 owns those accounting
changes. Recovery Gate/Outcome/Finalizer, Commit Coordinator and Reservation/Accounting reducers remain unchanged.

## Consequences

Whole-fill Generic T0 behavior remains one Fill, index/count one, terminal true. Durable queries can find a Fill identity and all
transactions for an Order in stable index/sequence order. Virtual Broker partial schedules, multi-fill recovery, SELL/CLOSE,
Futures/Margin and cross-Fill minimum commission remain outside this decision.
