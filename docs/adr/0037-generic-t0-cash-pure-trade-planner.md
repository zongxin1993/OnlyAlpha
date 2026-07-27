# ADR 0037: Generic T0 Cash Pure Trade Planner

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

本阶段不接入 Store，因为 Store 只应负责 sequence 分配和原子持久化；不实现真实 Projection Target，因为状态安装属于 PR3；
也不切换 ExecutionProcessor。旧 Manager 路径和新 reducer 路径的等价比较只能存在于测试，生产代码不得双写。

## Consequences

OnlyAlpha 现在可将一笔受支持的真实 Broker Trade Update 与完整 immutable before authority 编译成确定、无副作用、可持久化的
Prepared Transaction。相同 Context 产生相同 transaction ID、Projection、Event ID、authority hash、payload hash 和 canonical
payload；仅 `prepared_at` 改变时 business authority hash 保持不变。

当前不支持 SELL、CLOSE、Partial Fill、多 Fill 累计、最低佣金累计、Short、Hedging、Margin、Futures、Daily MTM、Margin Call、
多 Account、多 Currency、FX 或 Corporate Action。

后续职责：PR3 实现真实 Manager Projection Targets；PR4 实现 Commit Coordinator 与 projection-ready 编排；PR5 切换
ExecutionProcessor 并完成 recovery/replay。当前不得声称 Store Commit Coordinator、ExecutionProcessor Switch、Legacy Journal
Removal 或 Full Runtime Replay 已完成。
