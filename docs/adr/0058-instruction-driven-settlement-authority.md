# ADR 0058: Instruction-Driven Settlement Authority

Status: Accepted

## Decision

Settlement is an instruction-owned rights-transition process. Market rules compile a pure dated schedule; the Trade
Planner freezes the final instruction, including Runtime/account/cluster, order/trade, exact Position and Allocation
lifecycle identities, asset and cash legs, and rule/reference fingerprints.

`OnlySettlementAuthority` is the sole mutable settlement authority. It stores immutable instruction snapshots and
publishes deterministic due transitions. A Runtime trading-day boundary plans each due instruction as a
`SETTLEMENT_MATURITY` transaction before valuation and Strategy callbacks. Position, Allocation, Settlement, and
Account changes are projections of that single durable transaction; Runtime and Managers do not directly settle.

Account cash authority is split into ledger cash, trade-available cash, withdrawable cash, order-reserved cash, and
unsettled receivable cash. A sell credit can be trade-available on T while remaining non-withdrawable until T+1.

## Consequences

Every fill creates an independent instruction and maturity identity. Duplicate maturity is idempotent; identity or
lifecycle conflict fails closed. Checkpoint recovery restores instruction snapshots and resumes committed projection
tails before the Runtime opens.
