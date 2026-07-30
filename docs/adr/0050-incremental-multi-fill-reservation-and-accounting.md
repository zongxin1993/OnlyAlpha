# ADR 0050: Incremental Multi-Fill Reservation and Accounting

- Status: Accepted
- Date: 2026-07-30

## Context

ADR 0049 made each Fill an immutable transaction and made Order the exact cumulative Fill authority, but the product Planner still
assumed whole fills for cash reservations, fees, Account, Strategy Ledger and Risk. Opening the product path required every
economic authority to advance by the current Fill delta without releasing or closing order-level authority early.

## Decision

The Order reducer is the sole terminal-Fill authority. It compares cumulative filled quantity with ordered quantity and passes its
`terminal_fill` result to reservation and Risk reducers. Those reducers do not infer terminal state independently.

Position and Allocation persist exact `cumulative_open_price_quantity = Σ(price × quantity)`. Average open price is a derived,
finally quantized view and is never multiplied back into quantity to recover cost. Strategy Ledger position cost uses the exact
Allocation value. Legacy snapshots without the field derive `average_open_price × total_quantity` once at decode time; current
snapshots and checkpoints preserve the exact field.

Fee rules declare `OnlyFeeCalculationScope` explicitly:

- `FILL` charges the current Fill rule result;
- `ORDER_CUMULATIVE` calculates a cumulative target from cumulative Order notional/quantity, then charges only
  `target_after - cumulative_charged_before`.

Minimum and maximum values never imply a scope. A negative cumulative increment fails closed and future corrections belong to a
formal Fee Adjustment transaction. Broker reports documented as current-Fill fees use `FILL`; cumulative broker reports are
rejected when their semantics cannot be represented safely.

Order fee accrual is a separate Runtime-owned authority and `ORDER_FEE_ACCRUAL` Projection Component. It records cumulative Fill
quantity/notional, raw/target/charged amounts per stable component key, cumulative charged total, Fill count and version.
`OnlyFeeManager` remains an append-only receiver of already determined Fee Instructions; it does not read Orders or schedules and
does not calculate minimum commission. `OnlyOrderFeeAccrualManager` stores/replays accrual state but does not parse schedules.

Account and Strategy cash reservations consume explicit `consumed_delta` on every Fill. A non-terminal Fill becomes
`PARTIALLY_CONSUMED`, retains positive remaining authority and emits no release. A terminal exact consume becomes `CONSUMED` and
emits no empty release. A terminal Fill with excess authority becomes `RELEASED` and emits one release. Strategy reservation Stage
stays at its Broker lifecycle Stage for partial/exact consumption and changes to `RELEASED` only when money is actually released.
Account and Ledger receive these explicit consumed/released deltas; neither reconstructs them from before/after reservation state.

Risk Reservation consumes the current Fill quantity and notional, remains active for partial fills and becomes `CONSUMED` only on
the terminal Fill. Risk active-order counts decrease exactly once, on that terminal Fill. `remaining_order_notional` means the
remaining limit/order-notional budget after actual Fill notional deltas; it is distinct from the Reservation's remaining actual
exposure and may retain price-improvement headroom when quantity reaches zero.

The fixed Generic T0 Cash projection order is:

```text
ORDER → POSITION → ALLOCATION → SETTLEMENT → ORDER_FEE_ACCRUAL → FEE
→ ACCOUNT → STRATEGY_LEDGER → ACCOUNT_CASH_RESERVATION
→ STRATEGY_CASH_RESERVATION → RISK_RESERVATION → RISK → VALUATION
```

Committed Fact stores incremental fee, cumulative order fee, account/strategy consumed and released deltas, Risk consumed
quantity/notional, and exact Position/Allocation cumulative cost after the Fill. All transactions remain frozen and independently
committed.

The accrual Manager participates in Runtime checkpoint capture/restore. Projection codec and Memory/SQLite transaction payloads
carry the new component without a new persistence table. Legacy whole-fill payloads derive compatible defaults; absent legacy
order accrual begins from the first newly processed Fill rather than mutating history.

## Scope boundary

PR4.3.2 opens incremental Generic T0 Cash LIMIT BUY OPEN accounting for externally supplied partial Fill updates. It deliberately
does not add SELL/CLOSE, Futures/Margin, a Virtual Broker partial-fill schedule, production fault switches, or complete multi-fill
restart recovery. Commit Coordinator, Runtime Event Gate/Router and Recovery Finalizer/Outcome are unchanged.

PR4.3.3 owns Virtual Broker Partial Fill Schedule and end-to-end Multi-Fill Recovery scenarios across restart boundaries.

## Consequences

Whole-fill behavior remains compatible. Partial fills now produce one Projection Ready transaction per Fill, preserve exact
financial conservation, do not duplicate accounting for duplicate Fill identity, and reject conflicting identity before authority
mutation. More Runtime authority is checkpointed, but fee calculation and persistence responsibilities remain separated.
