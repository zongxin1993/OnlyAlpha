# ADR 0036: Core Projection Replay Completeness

Status: Accepted

## Context

Prepared schema v2 的核心 Projection 只保存成交 delta 或平铺 before/after 数值，无法创建或恢复真实领域实体。Version-only Apply 不能证明 reducer 读取的 Before authority 与安装时当前状态相同；通用 Cash Reservation owner scope 也丢失了领域身份。SQLite 又把所有 `IntegrityError` 当成业务冲突。

## Decision

Schema v3 不兼容 v2，不提供 alias、wrapper 或隐式迁移。

Projection 保存完整权威 Execution State。Order 保存完整请求、scope、订单参数、生命周期、成交累计、时间、拒绝/失败、版本、外部顺序、tags 与 metadata。Position/Allocation 保存完整 key、数量 buckets、冻结/预留/限制、成本、累计 PnL/fees、时间、版本和最后成交顺序；Position 另保存质量标志与 broker available quantity。Account 保存 scope/type/currency/status、现金、估值、PnL、fees、equity、margin、时间、版本、外部顺序、质量标志与 metadata。Ledger 保存完整 key/status、资本、现金、成本/市值、PnL/fees/equity、cash/fee entries、时间、版本、成交顺序和质量标志。

Account、Strategy、Position、Margin 和 Risk Reservation 分别保存各自完整身份、scope、原始 authority、消费/剩余、生命周期、时间和版本。Account/Ledger State 不重复嵌入 Reservation entity，避免双 authority。

win rate、profit factor、drawdown、return、展示汇总等从权威交易和估值时间线确定性重算，不进入 Ledger Execution State。Position available quantity 等纯公式值也不重复持久化；其输入 buckets 必须持久化。Metadata 会影响 State Hash，因为它属于 Order、Account 或 Reservation 的持久业务 authority。

Version 表达有序演进，State Hash 表达具体内容；两者必须同时匹配。新实体使用 `before=None`、version 0 和 SHA-256(`null`)。Canonical State Hash 使用排序 JSON、Decimal 字符串、Enum value、规范 Identifier、Unix-nanosecond Timestamp 和有序 Tuple，不使用 repr、pickle、Python hash 或对象地址。

Prepared 构造调用纯 `OnlyPreparedExecutionEconomicInvariantValidator`，交叉验证 Fact、Order、Position、Allocation、Fee、Account、Ledger、Settlement、Margin、Reservation 和 scope。该验证器不依赖 Manager、Runtime、Store 或 EventBus。

业务幂等键与不同 authority 的复用使用 `OnlyExecutionTransactionConflict`；I/O、SQLite trigger/lock/malformed/schema、非业务 integrity、Outbox 和 serialization 故障使用 `OnlyExecutionTransactionStoreError` 并保留 cause。

## Consequences

PR2 可以直接依赖 `Only*ExecutionState`、`Only*ExecutionProjection`、强制 State Hash Precondition、`only_execution_state_hash`、经济不变量验证器与 Generic T0 Fixture，构建 Planning Context、Pure Reducers 和 Transaction Planner，而不修改这些核心数据模型。

本 ADR 不实现 Pure Reducers、Transaction Planner、真实 Manager Projection Targets、Commit Coordinator、Processor Switch、Runtime Store 装配或 Full Replay Runtime，也不宣称已经解决 Manager-before-Journal。
