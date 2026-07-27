# Execution Trade Planning

`OnlyTradeExecutionTransactionPlanner` 是 Generic T0 Cash `LIMIT BUY OPEN` 整单成交的纯事务编译器。它只接收
`OnlyTradeExecutionPlanningContext`，不读取 Manager、Runtime、Clock、Broker、Store 或 EventBus，也不分配 Store
execution sequence。

Planning Context 在一个明确逻辑时点固定 Broker Trade Update、`prepared_at`、Engine/Strategy 身份、处理序列、Trading Day、
合约乘数、Position Scope、Market Trade Instruction、Fee Instruction、完整 before execution state、Position/Allocation creation
authority，以及 Settlement/Fee record sequence head。Context 不包含可调用对象或可变容器。

Planner 固定执行：验证 → Planned Trade → Order → Position → Allocation → Settlement → Fee → Account → Strategy Ledger →
Account Cash Reservation → Strategy Cash Reservation → Risk Reservation → Risk → Valuation → Fact Draft → Projection →
Precondition → deterministic Event → Prepared Transaction。最终 Projection 顺序使用 `OnlyExecutionProjectionOrder`；本场景包含
12 项 Projection，不包含 Position Reservation、Margin 或 Margin Reservation。

Position 与 Allocation 的新实体身份由调用方按现有 Manager cycle 规则预先读取并放入 creation authority。Reducer 只验证并
使用该身份，不读取 cycle，也不生成随机 ID。Projection Builder 统一生成 expected/result version、state hash 和 payload hash；
Precondition 从最终 Projection 一一派生。Reducer 只产生 Event Intent，Planner 在 transaction ID 确定后通过
`OnlyExecutionTransactionEventFactory` 生成连续、确定的 durable event identity。

当前明确不支持 SELL、CLOSE、部分成交、多次成交累计、最低佣金跨 Fill 累计、Short、Hedging、Margin、Futures、FX 与多币种。
这些输入以稳定 `OnlyTradeExecutionPlanningErrorCode` 拒绝。

本实现尚未接入 `OnlyExecutionProcessor`，也没有实现 Store Commit Coordinator 或真实 Manager Projection Target。生产主链仍使用
现有 Manager-before-Journal 路径；新旧路径的等价对照只存在于测试。
