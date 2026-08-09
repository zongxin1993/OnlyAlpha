# ADR 0037: Generic T0 Cash Pure Trade Planner

> The profile-specific support gate and planner naming are superseded by ADR 0065. The immutable planning and reduction
> boundaries remain in force.

- Status: Accepted
- Date: 2026-07-27

## Context

当前 Trade 主链在 durable Journal 前依次修改 Order、Position、Allocation、Settlement、Fee、Account、Strategy Ledger、
Reservation 和 Risk。后续任一步失败都会留下多个 Manager 的部分修改，而普通 Python 异常无法原子回滚这些独立所有者。
ADR 0035/0036 已建立 replay-complete Prepared Transaction、Execution State、Projection、Precondition、State Hash 和经济不变量，
但尚无从真实 before authority 计算完整事务的纯业务链。

## Decision

新增只支持 `GENERIC_T0_CASH`、`LIMIT BUY OPEN LONG NETTING`、单 Account/Cluster/Currency、无 Margin、整单成交的
`OnlyTradeExecutionTransactionPlanner`。Planning Context 显式携带 Broker Update、Market/Fee Instruction、所有 before state、
逻辑时间、scope、sequence head 和 creation authority。Planner 与 reducer 不读取系统时间、不生成随机 ID、不查询或修改
Manager/Runtime/Broker/Store/EventBus。

Planned Trade 是成交数量、价格、合约乘数、notional、fee、settlement bucket、scope 和 stable order 的唯一共享权威。各 reducer
只执行 `before + authority → after + result + event intent`。历史重放安装已提交 Projection，不重新运行 reducer，避免规则版本变化
改写历史经济结果。

Position 和 Allocation ID 依赖 Manager-owned cycle；调用方在进入纯计算前读取 cycle，并按正式 ID 公式构造不可变 creation
authority。Reducer 不分配身份。统一 Projection Builder 生成 version、state hash 和 payload hash；Precondition 从最终 Projection
自动一一派生。Event Intent 不含随机身份，Planner 在 transaction ID 确定后使用正式 Event Factory 生成 durable Event。

PR2.1 选择保留真实 Manager 最终版本（方案 A）。一个 Projection 可以表达原主链多次正式 mutation 的最终结果：Account 与
Strategy Ledger 在 Trade、Valuation、Reservation consume/release 后为 before `+4`；Account/Strategy Cash Reservation 在完整成交
后统一 consume 再 release，为 before `+2` 且最终 `RELEASED`。Position/Allocation ID cycle 与 Settlement/Fee record sequence 均由
调用方冻结并注入。时间语义保留原主链：成交事实使用 `ts_event`，处理/Reservation 更新时间使用 `ts_init`；估值价格由 Context
显式传入，不能用 fill price 冒充 mark price。

`OnlyRiskExecutionState` 的正式含义是 Runtime/Cluster/Account 聚合风险快照。成交完成减少 active-order 与 reservation aggregate；
订单级数量/金额的消费保留在 `OnlyRiskReservationExecutionState`。Account/Ledger 相等只作为本 ADR 单 Account、单 Cluster、单
Currency 的场景约束，不进入通用 State 或 Projection Contract。

Legacy 与 durable event 使用如下语义规则：ORDER/POSITION/ACCOUNT/STRATEGY/Reservation 事实一一映射，其中 Legacy
`ACCOUNT_RESERVATION_*` 规范命名为 `ACCOUNT_CASH_RESERVATION_*`，并保留 consume/release 的跨组件顺序。新事务额外显式记录
Settlement、Fee、Risk state；Legacy `EXECUTION_UPDATE_APPLIED` 是处理完成标记，由 Prepared Transaction 与 committed fact
envelope 表达。Legacy 的中间 Snapshot payload 与事务的 terminal Snapshot payload 不要求字节相同，但 scope、业务增量、最终
authority、timestamp 与映射后顺序必须相同。Event ID 不相等是既有决策，Planner ID 必须确定且可重放。

本阶段不接入 Store，因为 Store 只应负责 sequence 分配和原子持久化；不实现真实 Projection Target，因为状态安装属于 PR3；
也不切换 ExecutionProcessor。旧 Manager 路径和新 reducer 路径的等价比较只能存在于测试，生产代码不得双写。

## Consequences

OnlyAlpha 现在可将一笔受支持的真实 Broker Trade Update 与完整 immutable before authority 编译成确定、无副作用、可持久化的
Prepared Transaction。相同 Context 产生相同 transaction ID、Projection、Event ID、authority hash、payload hash 和 canonical
payload；仅 `prepared_at` 改变时 business authority hash 保持不变。

真实性由双 Runtime harness 证明：一侧运行真实 Legacy Manager 链，另一侧仅运行 Planner；四个合法场景的完整状态与事件语义
一致，且 Planner 前后包含 Manager 内部索引、repository、dedup、sequence、journal、event buffer/bus、audit 和 reconciliation 的
稳定 authority digest 完全不变。所有稳定 planning error code 与 19 个构造阶段故障均验证无 Prepared Transaction 和无外部副作用。

当前不支持 SELL、CLOSE、Partial Fill、多 Fill 累计、最低佣金累计、Short、Hedging、Margin、Futures、Daily MTM、Margin Call、
多 Account、多 Currency、FX 或 Corporate Action。

后续职责：真实 Manager Projection Targets 已由 ADR 0038 完成；PR4 实现 Commit Coordinator 与 projection-ready 编排；PR5 切换
ExecutionProcessor 并完成 recovery/replay。当前不得声称 Store Commit Coordinator、ExecutionProcessor Switch、Legacy Journal
Removal 或 Full Runtime Replay 已完成。
