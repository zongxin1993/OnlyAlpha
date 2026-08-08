# ADR 0059: Market-Neutral Durable Fee Authority

Status: Accepted

Fee authority input and Binding-v1 portions are superseded by ADR 0060. Durable assessment, accrual, application,
transaction and reconciliation decisions remain accepted.

## Context

The previous unified fee implementation mixed local policy assessment with broker-reported evidence, used a synthetic Trade
identity for order estimates, resolved schedule versions again at Fill time, and encoded raw calculation values in metadata.
Its order-cumulative reducer was Runtime-owned and durable, but its component identity could not prove the selected rule,
rounding, direction or resolution policy. Reconciliation was an in-memory service and could not recover through the Runtime
transaction kernel.

## Decision

OnlyAlpha separates four immutable facts and two authorities:

```text
Policy Pack -> Order Binding -> Fee Assessment (target)
                              -> Order Fee Accrual Authority
                              -> Fee Application (increment)
                              -> TRADE_FILL durable transaction

External Fee Evidence -> Reconciliation Planner
                      -> Decision + optional Adjustment / Risk Gate
                      -> FEE_RECONCILIATION durable transaction
```

The Fee Engine is a market-neutral pure service. Rules explicitly declare formula terms, basis, scope, resolution policy,
economic direction, bounds, rounding and pipeline. Runtime assembly explicitly installs compatible immutable Policy Packs;
Core does not silently install a default fee schedule. `ORDER_FIXED` versions are frozen in the Order Snapshot, while
`FILL_EFFECTIVE` schedule IDs resolve by the Fill trading day. Currency conversion is unsupported and fails closed.

Fee Assessment expresses targets only. Order Fee Accrual is the sole authority that converts those targets to an incremental
Fee Application. Downstream accounting consumes only the Application. Charge and rebate amounts remain non-negative and their
direction determines cash effect.

External Fee Evidence is append-only and separate from local calculation. Even a matched report creates a committed
`FEE_RECONCILIATION` fact. Adjustments never overwrite local applications and are installed only by ordered transaction
projections. Statement adjustments without reliable Cluster attribution remain account-level unallocated authority. Material
unknown differences block only risk-increasing trading and still allow query, cancel, close and further reconciliation.

Runtime transaction schema 6, checkpoint schema 3, Order fee-binding schema 1, Result schema 4 and Artifact schema 5 are
intentionally incompatible with their previous representations. Older schemas are rejected; no compatibility reader, dual
write or implicit migration is provided.

## Projection contracts

TRADE_FILL order is:

```text
ORDER -> POSITION -> ALLOCATION -> SETTLEMENT -> MARGIN -> ORDER_FEE_ACCRUAL
-> FEE_LEDGER -> ACCOUNT -> STRATEGY_LEDGER -> ACCOUNT_CASH_RESERVATION
-> STRATEGY_CASH_RESERVATION -> POSITION_RESERVATION -> MARGIN_RESERVATION
-> RISK_RESERVATION -> RISK -> VALUATION
```

FEE_RECONCILIATION order is:

```text
EXTERNAL_FEE_EVIDENCE -> FEE_RECONCILIATION -> FEE_ADJUSTMENT_LEDGER?
-> ACCOUNT? -> STRATEGY_LEDGER? -> UNALLOCATED_EXTERNAL_FEE?
-> RECONCILIATION_RISK_GATE -> VALUATION?
```

Every committed transaction is forward-recovered. Applied projection state is an idempotency index, not fee truth.

## Consequences

The public fee API and persistence schemas are breaking changes. Legacy fee calculation requests, instructions, records,
configuration modes, reconciliation service, projection names, built-in registries and aliases are removed in the same
release. Generic Cash, Futures and Crypto packs prove kernel neutrality but do not claim formal market product support.
