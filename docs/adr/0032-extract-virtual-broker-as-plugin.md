# ADR 0032: Extract Virtual Broker as an Independent Plugin

- Status: Accepted; trade-journal wording superseded by ADR 0033
- Date: 2026-07-22

## Context

> Historical note: references below to the Applied Trade Journal describe the boundary at this ADR's acceptance time.
> ADR 0033 replaces that model without changing this ADR's plugin-extraction decision.

Core previously contained a concrete Virtual Broker and Backtest Runtime directly imported its queue, gateway, config,
`on_bar()`/`run_due()` methods, dynamic `bind_market_rules`, and Broker trade query. This reversed the plugin dependency,
mixed external Broker projection with Runtime truth, and made Core-only installation impossible to reason about.

## Decision

`onlyalpha-plugin-broker-virtual` is an independent lockstep-versioned distribution discovered through
`onlyalpha.brokers:virtual`. Core contains only normalized Broker DTO/Ports, a bounded Runtime-owned inbound queue,
`OnlyBrokerComponent`, and `OnlyDeterministicBrokerDriver`. There is no compatibility module, alias, conditional import,
built-in registration, or fallback implementation.

Backtest assembly validates `simulated_execution` and the deterministic driver before Runtime construction. Generic
Broker Gateway remains separate from deterministic simulation driving. The plugin does not receive the complete Market
Rule Engine and does not use post-construction binding.

Runtime remains the authority for Order, applied Trade, Position, Allocation, Account, Strategy Ledger, Settlement,
Margin, Fee, Risk, Audit, Reconciliation, and Result. Plugin stores are external simulated Broker projections. The
ExecutionProcessor appends a trade to the Runtime-owned `OnlyAppliedTradeJournal` only after successful application,
invariant validation, and fact commit. Result and Artifact read this journal; Broker `query_trades()` is reserved for
external query and reconciliation.

The Runtime fee chain remains `market.fees + brokers[].fees → OnlyFeeResolver → ExecutionProcessor`. Virtual fills use
no-report semantics (`reported_fee=None`, `fee_reporting_mode=NONE`) and never apply local fee instructions.

## Consequences

Core can be installed and imported without a concrete Broker. A configuration referencing `plugin: virtual` fails with
`BROKER_PLUGIN_NOT_FOUND` when the plugin is absent. Backtests using it must install both distributions. Paper/Live
Runtimes can use the same generic Broker component without acquiring simulation-only methods. Historical imports from
`onlyalpha.broker.virtual` intentionally fail.
