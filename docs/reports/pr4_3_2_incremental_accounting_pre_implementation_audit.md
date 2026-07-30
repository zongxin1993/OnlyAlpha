# PR4.3.2 Incremental Multi-Fill Accounting: Pre-Implementation Audit

- Audit date: 2026-07-30
- Actual branch: `master`
- Actual/task baseline: `a93416d8ea66fd978b756e90118400df4931346b`
- Baseline difference: none. The only pre-existing worktree item is the untracked task Prompt.

## Current authority and failure analysis

1. The Account cash reducer consumes the current trade cost but forces the reservation remainder to zero and the state to
   `RELEASED`.
2. The Strategy cash reducer has the same whole-fill behavior and additionally forces its lifecycle stage to `RELEASED`.
3. Both public reservation models and execution states already admit `PARTIALLY_CONSUMED`; the prepared-trade reducers do not
   use it.
4. Account accounting subtracts the complete pre-fill `remaining_amount` from `frozen_cash`, rather than an explicit consumed
   and released delta.
5. Ledger accounting likewise subtracts the complete Strategy reservation remainder from `cash_reserved`.
6. Each Fill releases everything because both reservation reducers always set remaining to zero, state to `RELEASED`, advance
   by two versions, and emit consumed plus released intents.
7. Risk reservation contains cumulative consumed/remaining quantity and notional fields and already subtracts one Fill, but its
   downstream Risk reducer incorrectly derives changes from original reserved authority.
8. Risk accounting decrements Runtime and Cluster active-order counts on every Fill.
9. `remaining_order_notional` is the current Cluster's aggregate notional of unfilled quantities on active orders. Each Fill
   therefore subtracts that Fill's gross notional; it must never underflow.
10. Position and Allocation reducers currently reconstruct weighted cost as quantized average price times existing quantity.
11. That reconstruction accumulates rounding error across different-price Fills.
12. Ledger `position_cost` also multiplies the quantized Allocation average by total quantity and multiplier.
13. A fee rule currently applies `minimum` and `maximum` independently to each resolver call, which today is one Fill.
14. `OnlyFeeManager` is an immutable instruction/fact target with idempotency and checkpoint duties; making it parse schedules or
    query Orders would violate its existing entity scope and dependency boundary.
15. A Fee Instruction is scoped to one Trade/Fill and is the command consumed by the existing `FEE` projection.
16. Explicit broker-reported fees are resolved according to the broker reporting mode; modes without current-fill authority are
    deferred/fail closed by the resolver. Cumulative order reports are not represented and must not be guessed.
17. Yes. Order-level accrual has different identity, versioning and replay semantics and requires an independent
    `ORDER_FEE_ACCRUAL` projection component.
18. No new database table is required because the authority is carried by immutable transaction projections and Runtime
    checkpoints. Transaction rows already persist typed projection payloads.
19. No SQLite migration is required. Adding a checkpoint participant changes the strict participant registry fingerprint, so an
    older checkpoint fails fast rather than fabricating authority.
20. Legacy whole-fill Position/Allocation payloads derive exact cumulative value once at their decode/snapshot adapter boundary
    as `average_open_price * total_quantity`. New payloads persist the exact field.
21. The product gate is in `OnlyTradeExecutionTransactionPlanner._validate` and returns
    `PARTIAL_FILL_ACCOUNTING_NOT_READY` when the Fill is non-terminal or the Order already has fills.
22. It may be removed only after exact Position/Allocation cost, cumulative fee authority, incremental Account/Strategy/Risk
    reservations and accounting, codecs, projection apply, checkpoint participation, committed audit facts, whole-fill
    regression, and sequential three-Fill tests are complete.
23. Expected production changes cover execution state/context/planner/reducers/projection/codec/targets/facts, fee models and
    schedules plus a new accrual manager, Position/Allocation state, Runtime assembly/checkpoint wiring, and public exports.
24. Commit Coordinator, Runtime Event Gate/Router, Recovery Finalizer/Outcome/Orchestrator, durable outbox identity, transaction
    identity and fill identity are outside the implementation boundary and must remain unchanged.

## Implementation decision

Order reduction remains the only terminal-Fill authority. All later reducers consume its explicit decision. Reservation reducers
emit explicit consumed/released deltas; Account, Ledger, and Risk do not re-derive them. The product gate remains present until the
end-to-end accounting path and its persistence tests pass.
