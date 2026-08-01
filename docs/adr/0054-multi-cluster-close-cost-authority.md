# ADR 0054: Multi-Cluster Close Cost Authority

- Status: Accepted
- Date: 2026-08-01
- Supersedes: ADR 0053 中“Position 与 Allocation 分别按自身平均成本归约”的 Multi-Cluster 语义

## Context

共享 Account 的 Position 是多个 Cluster Allocation 的聚合状态。不同 Cluster 以不同价格建仓后，使用 Position 平均成本决定某个 Cluster 的平仓成本，会把其他 Cluster 的成本转移给本次平仓；Position 与 Allocation 各算一次又会产生互相矛盾的 released cost、剩余成本和 realized PnL。

## Decision

Allocation 是 Close Attribution Authority，Position 是 Aggregate Authority。Planner 在纯规划阶段从订单所属 Cluster Allocation 创建不可变 `OnlyAttributedCloseCostAuthority`：

1. 校验 Runtime、Account、Cluster、Instrument、Order、Position、Allocation 与 Reservation scope；
2. 校验 Position 数量/成本等于所有活跃 Allocation 的聚合，当前不允许 Unallocated Quantity/Cost；
3. 仅在 Authority builder 中调用一次 `only_reduce_average_cost_close()`；
4. 用 Allocation released cost 同时减少 Allocation 与 Position 的精确累计成本；
5. 从剩余精确成本和数量按 Instrument price precision 重派生两层平均价；
6. 仅计算一次毛 realized PnL，并传递给 Position、Allocation、Account、Strategy Ledger 和 Fact。

Projection 顺序、Transaction/Fact codec、Store、Commit Coordinator、Recovery Phase 和 Outbox 语义不变。Authority 由 Projection Before/After、现有 Fact 字段以及 authority/payload hash 冻结，不新增持久化模型。

Multi-Cluster 的 durable capability 使用共享 Account 对所有 Strategy Ledger 的聚合 parity，不能与当前单 Ledger 比较。Strategy Ledger equity sequence 是 Runtime 全局序列；checkpoint 必须按该序列排序并以完整快照恢复，因此不依赖 Cluster 注册顺序。

## Economic invariants

- Position Quantity = sum(Allocation Quantity)
- Position cumulative cost = sum(Allocation cumulative cost)
- Position released cost = Allocation released cost = Fact released cost
- Position/Allocation 剩余平均价由剩余精确成本派生；全平时数量、成本归零且平均价为 `None`
- Position/Allocation/Account/Ledger PnL delta = Fact PnL delta
- Account 与所有 Strategy Ledger 按既有 Fixed Capital 模型对账

## Consequences

不同成本 Cluster 可以按各自经济归属平仓，Partial/Multi-Fill 最终无成本尾差；恢复只重放已冻结 Projection，不重新选择成本。错误 scope、数量不足或无法解释的 Unallocated Cost 在 Commit 前 fail closed。

## Out of scope

Unallocated Close、Cross-Cluster Close、FIFO/LIFO、Short、Hedging、Futures、Margin、CloseToday/CloseYesterday、多币种与 FX。
