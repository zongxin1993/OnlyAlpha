# ADR 0042: Projection Ready Query and Runtime Recovery Hook

- Status: Accepted
- Date: 2026-07-28

## Context

ADR 0041 建立了 durable commit、ordered real Manager Projection、Projection Ready 与 durable Outbox，但
`OnlyExecutionTransactionQueryPort.records()` 同时被管理恢复和正式 Result 使用，Runtime 启动也没有自动完成未 Ready 的
transaction tail。Committed transaction 因而可能在 Manager authority 尚不完整时进入业务结果，且崩溃后的恢复依赖手工调用。

## Decision

Committed 与 Projection Ready 是两个不可合并的状态：Committed 表示事务已经不可丢失、必须恢复；Projection Ready 表示全部
真实 Manager Projection 已完成，可以成为正式业务成交。`OnlyExecutionTransactionQueryPort` 是 Admin/Recovery query，可读取全部
committed transaction；`OnlyProjectionReadyExecutionQueryPort` 是 Business query，只提供 `ready_records()` 与 `ready_count()`。
Collector、RunPlan、Result、fee attribution、execution fingerprint、Analytics、Scenario、Artifact、Report 与 Application query 只能沿
Business query 读取。

Backtest Runtime 组装唯一 Store、Applied Ledger、真实 Target Registry、Projection Applier 和 Coordinator，并保存职责分离的 Query、
Projection State 与 Outbox Port。`OnlyExecutionRecoveryService` 在插件资源 initialize/connect 和 Cluster initialize 之后、Runtime 进入
`READY` 之前，严格按 execution sequence 调用 Coordinator 完成所有未 Ready transaction。任何 Projection、sequence 或 Store failure
都使 Runtime 进入 `FAILED`；Cluster 不启动，也不接收 MarketData、Broker update 或 Historical Replay。

Runtime `start()` 在插件资源 start 后、Cluster start 前发布 recovered Outbox。Backtest 采用严格启动语义：Outbox 仍有 failed 或
remaining record 时启动失败。该失败与 Projection Recovery failure 分离：Transaction 已 Ready，Manager 不回滚、不重放，Event ID
保持稳定并按 at-least-once 语义重试，不承诺 exactly-once。

Applied Ledger 仍是只存在于内存、可由正确 Bootstrap Authority 和 ordered transaction tail 重建的幂等索引，不是第二持久业务
权威。Recovery 只执行 deterministic forward recovery，不重新运行 Planner、Broker、Market Rule 或 Fee 计算，不跳过失败 sequence，
也不覆盖 version/state/payload conflict。

## Consequences

- 未 Ready transaction 只能进入 Coordinator、Recovery、Admin 和 Diagnostic，不能进入正式 trade count、fee attribution 或制品。
- Runtime-owned recovery diagnostic 进入 Backtest Result diagnostic projection。
- In-memory 与 SQLite Store 以相同排序和 scope 语义实现 Ready Query；SQLite 在 SQL 中过滤 `projection_ready=1`。
- 真实 12 Target 的 before-target、manager-install-before-ledger、after-ledger、version/state/payload conflict 由测试专用 decorator 注入，
  生产代码没有故障开关。

本 ADR 仍只覆盖 Generic T0 Cash、LIMIT、BUY、OPEN、整单成交，以及“正确 Bootstrap Authority + ordered committed Trade tail”。它不
实现 Full Bootstrap Snapshot、Empty Runtime Recovery、Partial/Multi Fill、SELL/CLOSE、Futures/Margin、Non-Trade Transaction 或
Paper/Live Recovery。
