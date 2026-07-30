# ADR 0053: Complete Durable Long Close Lifecycle

- Status: Accepted
- Date: 2026-07-30
- Supersedes: ADR 0052 中关于首个 whole Fill 与 Partial/Multi-Close gate 的当前产品限制

## Context

ADR 0052 将 Generic T0 Cash `LIMIT SELL CLOSE LONG NETTING` 的首个 whole Fill 接入统一 Prepared
Transaction，但一个 Close Order 的后续 Fill 仍被 `PARTIAL_CLOSE_NOT_READY` 拒绝，Position 与 Allocation 又以有限精度
平均价乘本次数量释放成本。部分成交后的 Cancel/Reject 还会直接修改多个 Manager，无法获得与 Trade Fill 相同的 durable
commit、ordered projection、Outbox 和 causal recovery 边界。

本决策只完成单币种 CASH Account、无 Margin 的 `GENERIC_T0_CASH + LIMIT SELL CLOSE + LONG + NETTING`。它不建立
Close 专用 Store、Coordinator、Recovery Phase、Manager 或结果模型。

## Decision

### Exact Close Cost Authority

Position 与 Allocation 必须共同调用纯函数 `only_reduce_average_cost_close()`。设 Close 前精确累计开仓价数量为 `C`、数量为
`Q`、本次成交量为 `q`：

```text
q == Q: released_cost = C, remaining_cost = 0
q <  Q: released_cost = C × q / Q, remaining_cost = C - released_cost
```

计算在局部 Decimal context 中执行，使用足以覆盖输入有效位与数量精度的精度及 `ROUND_HALF_EVEN`；不修改全局 Decimal
context。最终 Fill 无条件释放全部剩余精确成本，因此所有 Fill 的 released cost 之和严格等于初始 `C`，最终成本严格为零。
Realized PnL 的唯一权威是 Position reducer 的 `(fill_price × q - released_cost) × multiplier`；Allocation、Account、Strategy
Ledger 与 Committed Fact 只消费该增量，不重新计算。

### Multi-Close Authority

一个 Close Order 的每个 Fill 都形成独立 `TRADE_FILL` Transaction，并保持既有 Fill Identity、Payload Fingerprint、per-Order
Fill Index 和 Transaction ID 语义。Order 累计 filled/remaining/value/count；Position 与 Allocation 逐笔减少；Position
Reservation 和 Risk Reservation 显式累计 `consumed`，中间 Fill 保留 remaining；Risk Active Count 只在最终 Fill 减少一次。
Fee Resolver 仍生成唯一 Fee Instruction，Order Fee Accrual 把订单累计最低佣金转换为本次增量；FeeManager 只安装已决定事实。
Account 和 Ledger 分别消费相同 sale cash、fee 与 Position realized-PnL delta。

Virtual Broker 不增加 SELL/CLOSE 分支。既有 WHOLE/MAX_PER_BAR/SCHEDULE Fill Plan、ONE_PER_BAR/ALL_DUE、stable Step
identity、pending publish 与 checkpoint cursor 同时适用于开仓和 Long Close，因此同 Bar及跨 Bar `300 → 400 → 300`
都经正式 Broker Queue 自动产生三个 Transaction。

### Durable Terminal Operation

部分成交后的 `CANCELLED`、`REJECTED`、`EXPIRED` 是 `ORDER_TERMINAL`，不是 Trade。Terminal Identity 由 Runtime、Gateway、
Account、Order、Broker Update 和终态状态规范化生成 `ETERM-<sha256>`；Payload Fingerprint 独立覆盖完整标准化 Update。同一
Identity/同一 Payload 幂等，同一 Identity/不同 Payload 以 `TERMINAL_IDENTITY_CONFLICT` fail closed。Terminal 不复用 Fill
Identity，不创建伪 Trade ID，也不增加 Fill Index。

Terminal Fact 记录终态、累计已成交数量、Order 剩余量、Position/Risk Reservation 的 consumed/released/remaining delta、
Risk Active Count delta、scope、时间与 causation。固定 Projection 顺序为：

```text
ORDER → POSITION_RESERVATION → RISK_RESERVATION → RISK
```

Order Projection 保留历史 Fill；两个 Reservation 只释放 remaining；Risk Active Count 只减少一次。四项 Projection 与 Trade
Fill 共用 Transaction Store、Commit Coordinator、Applied Projection Ledger、Projection Ready、durable Outbox 和 causal recovery。

### Capability and Legacy Closure

`only_resolve_execution_capability()` 是 Processor 路由、Runtime Context Builder 和 Planner 共同使用的支持范围矩阵。正式
Generic T0 Long Close Trade 必须解析为 `DURABLE_TRADE`，终态必须解析为 `DURABLE_TERMINAL`。`_unmigrated_trade()` 和直接
`_terminal_order()` 保留给未迁移组合，但带有 formal-scope hard guard；受支持 Long Close 不能落入这两个路径。

### Persistence and Recovery

Prepared/Committed transaction codec schema 仍为 v4，并增加 Operation Kind 判别、nullable Trade ID、Terminal Identity、Terminal
Fact 与 Terminal Order Projection。Runtime Persistence schema 从 2 升到 3，因为 `execution_transactions.trade_id` 不再可强制
非空，并新增 Operation Kind/Terminal Identity 索引。旧 schema 2 数据库不迁移、不删除、不降级到 Memory；启动时报告
expected 3 / actual 2 并 fail fast。

不增加 Recovery Phase，也不修改 Commit Coordinator、Runtime Event Gate 或 Outbox 语义。Trade 与 Terminal 都通过既有
execute/publish、commit、mid-projection、Projection Ready、Outbox、checkpoint tail 和 A→B→C forward recovery。Virtual Broker
execute-before-publish checkpoint 只恢复待发布 Fill，不重复 Broker execution。

### Result

Projection Ready query 可以包含 `TRADE_FILL` 与 `ORDER_TERMINAL`。Backtest Collector 和 RunPlan 只把
`OnlyCommittedExecutionFact` 投影为 Execution/Trade Result；Terminal Fact 只影响最终 Order/Reservation/Risk authority，不计入
成交列表、费用统计或交易分析。

## Consequences

- Long Close 的精确成本、累计费用、Reservation、Risk、Account 与 Ledger 可跨任意合法 Fill 序列确定性恢复。
- Partial Fill 后 Cancel/Reject/Expire 不再直接跨 Manager 修改 formal authority。
- Runtime schema 3 与 schema 2 不向后兼容；这是明确的 fail-fast 边界，不是数据迁移功能。
- Trade Fill Identity/Index、Commit Coordinator、Recovery Phase、Event Gate、Virtual Broker checkpoint schema 2 和
  at-least-once Outbox 语义保持不变。

## Out of Scope

Short、Hedging、CloseToday/CloseYesterday、Futures/Margin、Market/IOC/FOK/GTD、Paper/Live recovery、Exactly-once
delivery、Subscriber ACK、schema migration、distributed checkpoint 和完整 Broker reconciliation 不在本决策范围。
