# ADR 0032: Extract Virtual Broker as an Independent Plugin

- 状态：部分替代。交易日志以 ADR 0033 为准。原生 Rust 模拟场所的目录与发行归属以[仓库架构](../repository-product-architecture.md)为准。
- Date: 2026-07-22

## Context

> 以下记录保留原插件的发行和发现方式。原生 Rust 模拟场所现由 `crates/broker-virtual` 提供，随 `libs` 统一发行，Provider ID 仍为 `virtual`。已发行插件和旧运行继续绑定原身份及原工件。场所拥有模拟订单与成交观察，Runtime 负责本地经济事实的应用。原决定中的 Applied Trade Journal 已由 ADR 0033 替代。

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
