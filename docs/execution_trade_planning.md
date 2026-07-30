# Execution Trade Planning

Planner 输出的 v4 Projection 已可由 13 个真实经济 Target 直接安装。Planner 仍保持纯函数边界；Target 只消费 committed fact/After Authority，不重新执行 reducer 或市场、费用、结算、风险规则。连续 replay 与 forward recovery 见 [Real Manager Projection Targets](execution_projection_targets.md)。

`OnlyTradeExecutionTransactionPlanner` 是 Generic T0 Cash `LIMIT BUY OPEN` 每个 Fill 的纯事务编译器。它只接收
`OnlyTradeExecutionPlanningContext`，不读取 Manager、Runtime、Clock、Broker、Store 或 EventBus，也不分配 Store
execution sequence。

Planning Context 在一个明确逻辑时点固定 Broker Trade Update、`prepared_at`、Engine/Strategy 身份、处理序列、Trading Day、
合约乘数、Position Scope、Market Trade Instruction、Fee Instruction、完整 before execution state、Position/Allocation creation
authority、Settlement/Fee record sequence head，以及由最新 Closed Bar 提供的 `valuation_price`。成交价负责成本，估值价负责
市值和未实现盈亏；Context 不包含可调用对象或可变容器。

Planner 固定执行：验证 → Planned Trade → Order → Position → Allocation → Settlement → Fee → Account → Strategy Ledger →
Account Cash Reservation → Strategy Cash Reservation → Risk Reservation → Risk → Valuation → Fact Draft → Projection →
Precondition → deterministic Event → Prepared Transaction。最终 Projection 顺序使用 `OnlyExecutionProjectionOrder`；本场景包含
12 项 Projection，不包含 Position Reservation、Margin 或 Margin Reservation。

Position 与 Allocation 的新实体身份由调用方按现有 Manager cycle 规则预先读取并放入 creation authority。Reducer 只验证并
使用该身份，不读取 cycle，也不生成随机 ID。Projection Builder 统一生成 expected/result version、state hash 和 payload hash；
Precondition 从最终 Projection 一一派生。Reducer 只产生 Event Intent，Planner 在 transaction ID 确定后通过
`OnlyExecutionTransactionEventFactory` 生成连续、确定的 durable event identity。

PR2.1 的业务基线不是 Projection fixture，而是两个独立 Runtime 中的真实 Manager。测试先从未修改的 Runtime 读取正式 Snapshot，
通过公开 converter 构造 Context；一侧执行 `OnlyExecutionProcessor.process()`，另一侧只执行 Planner。Order、Position、Allocation、
Settlement、Fee、Account、Ledger、三类 Reservation、Risk 和 Valuation 的完整 after state（包括 Version、时间、记录和 sequence）
必须逐字段相等。覆盖零费用、非零费用、超额现金预留和已有 Position/Allocation 增仓四种场景。

Planner 保持现有 Manager 的最终版本语义：Order/Position/Allocation/Settlement/Fee/Risk Reservation/Risk/Valuation 各推进一次；
Account 和 Strategy Ledger 因 Trade、Valuation、Reservation consume、Reservation release 最终推进四次；Account 和 Strategy Cash
Reservation 均执行 consume 后 release，最终推进两次并处于 `RELEASED`。Settlement/Fee record ID 使用调用方冻结的全局 sequence
head 加一。`filled_at`、Position/Allocation/Settlement 的业务时间使用 `ts_event`；Manager 的处理更新时间及 Reservation/Risk 的
更新时间使用 `ts_init`；当前同步回放基线中 Account/Valuation valuation time 使用 `ts_init`，Ledger 使用 `ts_event`。

Risk Projection 表示 Runtime/Cluster/Account 的聚合风险快照，不表示成交后的持仓暴露；它减少 active order count 和预留数量/
金额。订单级已消费风险由 Risk Reservation Projection 表达。Account 与 Strategy Ledger 的 equity 相等只在本 Planner 明确限制的
单 Account、单 Cluster、单 Currency 场景验证，不是通用 Execution State 不变量。

Durable Event 保留 Legacy 的业务顺序，并将 `ACCOUNT_RESERVATION_*` 规范为 `ACCOUNT_CASH_RESERVATION_*`。Settlement、Fee 和
Risk 增加显式 durable state fact；Legacy `EXECUTION_UPDATE_APPLIED` 是处理器完成标记，由 Prepared Transaction/fact envelope
承载而非重复业务事件。Event ID 机制有意不同，但 type、scope、timestamp、terminal payload 和映射后的业务顺序均有真实路径测试。

当前明确不支持 SELL、CLOSE、部分成交、多次成交累计、最低佣金跨 Fill 累计、Short、Hedging、Margin、Futures、FX 与多币种。
这些输入以稳定 `OnlyTradeExecutionPlanningErrorCode` 拒绝。

本 Planner 已接入 `OnlyExecutionProcessor` 的 Generic T0 Cash、LIMIT BUY OPEN whole/partial Fill 产品路径。Prepared Transaction 由 Coordinator 先写入 Transaction Store，再经过 Runtime sequence gate 和 13 个真实经济 Projection Target；Planner 仍保持纯函数边界，不导入 Runtime、Manager、Store 或 EventBus。

## Runtime Recovery 边界

Startup Recovery 从 durable committed payload 开始，不重新调用 Trade Planner。Planner、Broker、Market Rule 与 Fee Resolver 都不参与
tail replay；否则重启时的外部状态或当前规则可能改变已提交 Authority。只有 Projection Ready transaction 才进入正式 Result，未 Ready
transaction 仍由其原始 Prepared payload 和 hash 驱动确定性前向恢复。
