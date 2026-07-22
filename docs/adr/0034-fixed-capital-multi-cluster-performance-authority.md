# ADR 0034: Fixed-Capital Multi-Cluster Performance Authority

- Status: Accepted
- Date: 2026-07-22

## Context

Compatible Clusters share one Runtime Account, but the former implementation copied the Account initial cash into every
Strategy Ledger and used the first Ledger's currency, return and drawdown as Runtime values. List order was therefore an
undeclared accounting identity. Account had no equity timeline, Cluster results had no formal performance object, and no
service proved that the shared Account reconciled with all attributed Ledgers.

## Decision

The supported model is one Account, one Base Currency and one or more `FIXED_CAPITAL` Clusters. A single Cluster may omit
capital and receives exactly the Account initial cash. Every Cluster in a multi-Cluster Runtime must declare non-negative
capital in the Account currency, and the exact sum must equal Account initial cash. `SHARED_POOL`, percentage allocation,
automatic borrowing and dynamic reallocation are not implemented.

Every Strategy Ledger is located through the complete Runtime/Account/Cluster/Currency scope. Manager creation maintains a
unique scope index and `OnlyStrategyLedgerLocator` is the shared boundary for execution, reservations, risk, valuation,
results and reconciliation. Cluster-only lookup and list-position selection are not valid APIs.

Runtime portfolio performance is derived exclusively from the shared Account equity timeline. Cluster performance is
derived exclusively from the corresponding Strategy Ledger timeline. Both timelines retain explicit sequence numbers.
Result schema v3 names the former `runtime_performance`, embeds performance in every Cluster result, and includes the two
timelines plus a structured reconciliation result. No old field aliases, config fallback or dual writes remain.

At final backtest seal, reconciliation checks initial equity, cash, position market value, realized and unrealized PnL,
fees and equity. It also checks committed per-Trade fees against the attributed Cluster Ledger. A mismatch is reported with
both values and involved Clusters and makes the backtest fail; reconciliation never mutates accounting state.

## Consequences

Registration and sorting order no longer define accounting identity. Runtime return and maximum drawdown describe the
actual Account path, while each Cluster retains its allocated-capital return and drawdown. JSON, Parquet, Markdown, console,
analytics and artifacts expose both authorities.

This ADR does not add multi-Account, multi-Currency, FX, System Ledger, TWR/MWR, Paper/Live performance recovery, persistent
recovery, Futures daily MTM, or intermediate valuation-barrier reconciliation.
