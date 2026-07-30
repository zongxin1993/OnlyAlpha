# ADR 0052: Generic T0 Cash Long Close Durable Transaction

- Status: Proposed
- Date: 2026-07-30

## Context

Generic T0 Cash `LIMIT BUY OPEN LONG NETTING` 已使用 Prepared Transaction、Durable Commit、Ordered Projection、Projection Ready、Durable Outbox 与 Recovery。相同市场下的 `LIMIT SELL CLOSE LONG NETTING` 仍进入 `_unmigrated_trade()`，逐个修改 Manager；中途失败只能进入 Reconciliation，无法撤销已经形成的半完成 Authority。

## Decision

PR4.4.1 将单币种 CASH Account、无 Margin 的 Generic T0 Cash `LIMIT SELL CLOSE LONG NETTING` Whole Fill 接入现有 `OnlyTradeExecutionTransactionPlanner`。Whole Fill 仅表示 Fill quantity 等于 Close Order remaining quantity，且 Order 在该 Fill 前没有历史 Fill；它可以只减少账户 Position 的一部分。

Planning Context 一次性捕获 Order、Position、Allocation、Position Reservation、Settlement、Order Fee Accrual、Fee、Account、Strategy Ledger、Risk Reservation、Risk 与 Valuation before authority。Close 禁止 Position/Allocation creation authority、Account/Strategy cash reservation 与 Margin reservation。

Position Close Reduction 是 Realized PnL 唯一计算权威：

```text
realized_pnl_delta = (fill_price - average_open_price_before) × fill_quantity × multiplier
```

Position 与 Allocation 都按 Fill quantity 减少；剩余平均开仓价不变，精确累计成本按 `average_open_price_before × fill_quantity` 释放，不能用量化后的平均价乘剩余量反推。归零时关闭实体并清空平均价、精确成本与未实现价值。Allocation 使用 Position 已计算的同一 Realized PnL Delta，且只能减少下单 Cluster 的 Allocation。

Position Reservation 由纯 Reducer在同一 Transaction 内消费。Reducer保留 Account hold、Allocation hold 与 Broker Acknowledgement Stage 的既有语义，Projection Target 原子安装 After Authority；Transaction 完成后不得再调用 Manager `consume()`。Risk Reservation 按同一 Fill quantity/notional 消费，Order Reduction 的 `terminal_fill` 是唯一终态输入。

Settlement 只使用 `OnlyTradeApplicationInstruction.settlement_instruction`；SELL cash availability 与 legal settlement day 来自 Profile/Calendar。Fee/Tax 只使用 Runtime Fee Resolver 输出与 Order Fee Accrual Delta；Planner、Position、Fee Manager 均不解析或硬编码费率。

Account 与 Strategy Ledger 接收 `gross_notional - incremental_fee` 的现金流、Position/Allocation 产生的 Realized PnL Delta、增量 Fee 与 Position After 估值。二者不重新计算 PnL。Ledger 延续现有 `SELL_SETTLEMENT`/`FEE` entry 模型，避免重复经济记账。

固定 Close Projection 顺序为：

```text
ORDER → POSITION → ALLOCATION → SETTLEMENT → ORDER_FEE_ACCRUAL → FEE
→ ACCOUNT → STRATEGY_LEDGER → POSITION_RESERVATION
→ RISK_RESERVATION → RISK → VALUATION
```

Committed Fact 记录 SELL/CLOSE scope、逐 Fill identity/index、Position/Allocation before/after/delta、精确成本 before/after/released、gross/net cash inflow、统一 Realized PnL Delta、Position/Risk Reservation 消费量与 closed flags，并强制交叉不变量。

Recovery 复用 checkpoint restore、exact replay、Stored Transaction rehydrate、unprojected recovery、continuation、authority validation、durable finalization 与 Event Gate。Position Reservation 使用现有 Component/Codec/checkpoint authority，新增正式 Projection Target；不新增 Recovery Phase。

## Scope boundary

本决策不实现一个 Close Order 的 Partial/Multi-Fill、Partial Close 后 Cancel、Short、Hedging、CloseToday/CloseYesterday、Futures/Margin、Market/IOC/FOK/GTD、FX、真实 Broker 或 Paper/Live Recovery。Whole-Fill gate 在任何 Prepared/Commit/Projection/Outbox/Authority Mutation 前 fail closed。

PR4.4.2 将在相同事务基础设施上处理 Partial / Multi-Fill CLOSE Incremental Accounting。

## Consequences

Generic T0 Cash 的 Long Open 与 Long Close 共享唯一 Transaction、Projection、Outbox、Checkpoint 与 Recovery 主链。`_unmigrated_trade()` 暂时保留给未迁移的 Futures/Margin/Short 等范围。Transaction Identity、Fill Identity、Fill Index、Commit Coordinator、Recovery Phase、Event Gate 与 Outbox 语义保持不变。
