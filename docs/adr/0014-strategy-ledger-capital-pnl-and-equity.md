# ADR 0014: Strategy Ledger capital, PnL and equity

- Status: Accepted
- Date: 2026-07-15

## Context

多个 Cluster 可以共用一个券商账户，但券商只提供真实账户现金和合并持仓，无法表达策略独立资金、费用、收益、净值与回撤。
使用账户合并均价或按总收益比例分摊会破坏归因，也无法支持连续下单的策略资金预占。提示建议的 0011 已被 Order ADR 使用，
因此本决策使用下一个可用编号 0014，避免覆盖既有架构历史。

## Decision

每个 Runtime 独占 `OnlyStrategyLedgerManager`，每个 Cluster 使用 Runtime/Account/Cluster/BaseCurrency Key 创建 Fixed
Capital Ledger。券商真实账与策略虚拟账分离；成交收益与成本只接受该 Cluster 的 Position Allocation before/after。
Cash、Fee、Reservation、Realized/Unrealized PnL、双视图 Equity、Simple Return、HWM 和 Drawdown 均由 Ledger 受控更新。

买单在 Order/Risk Reservation 之后、调用 Execution Port 之前建立虚拟现金预占。Context 只暴露 frozen Snapshot；Risk
读取 Ledger View，非 ACTIVE 状态 Fail Closed。所有变更在 Runtime 单写入者顺序内完成，Event 只发布已发生事实。
Repository 保存不可变 DTO；Replay 从有序、可序列化 Command 重新执行。

## Consequences

Cluster PnL 不再依赖账户平均价，多个策略可在同一 Account/Instrument 上保持独立成本和收益。双视图不一致会显式阻断。
代价是 Runtime 必须在 Position Allocation 更新后编排 Ledger Trade Accounting，并维护稳定 Replay 顺序。

第一版不支持多币种换汇、保证金、融资融券、Funding、分红、自动再平衡、策略间转账、完整 AccountManager、真实券商现金同步
或完整 ExecutionProcessor。
