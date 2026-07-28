# ADR 0041: Execution Commit Coordinator

- Status: Accepted
- Date: 2026-07-28

## Context

旧成交路径先直接修改 Runtime Manager，再向 `OnlyCommittedExecutionJournal` 追加事实。Journal 失败会留下已改变但没有 durable transaction authority 的状态，也无法用明确的 projection progress 恢复。Prepared Transaction、Transaction Store、真实 Projection Target 与 Applied Projection Ledger 已存在，但此前没有进入 Runtime 产品主链。

## Decision

`OnlyExecutionTransactionStore` 是唯一 durable Trade authority。`OnlyAppliedProjectionLedger` 仅记录某个 Projection 是否已应用，是可由 authoritative bootstrap state 与有序 transaction tail 重建的幂等索引，不是第二业务真值。

当前正式流程固定为：

```text
Broker Trade Update
→ pure Planner / Prepared Transaction
→ durable Store commit
→ exact Runtime predecessor-ready gate
→ ordered real Manager Projection Targets
→ Projection Ready
→ durable Outbox visibility
→ at-least-once publication
```

Coordinator 接收显式 `committed_at` 与 `projected_at`，只依赖 Commit、Query、Projection State Port 和 Projection Applier，不导入 Manager。Store commit 必须发生在任何业务 Projection mutation 之前。同一幂等键与相同完整 Prepared payload 返回已有事务；同键不同 payload 是冲突。

Runtime sequence gate 要求当前事务的直接前序已经 Projection Ready；不能跳过未完成事务。Target 按 `OnlyExecutionProjectionOrder` 顺序执行。任一 Target 失败时保留已完成前缀、记录 projection failure、隐藏 Outbox，并停止后续事务；重试通过 Applied Ledger 的 APPLIED/IDEMPOTENT/RECOVERED 语义继续 forward recovery。全部 Target 完成后才标记 Projection Ready。

Outbox 记录与事务一起 durable commit，但 `pending()` 只返回 Projection Ready 且未发布的记录。发布为 at-least-once；Event ID 稳定，消费者仍须幂等。本 ADR 不声称 exactly-once。

## Supported scope

产品主链当前覆盖 Generic T0 Cash、LIMIT、BUY、OPEN、未成交订单的一次整单 Fill。SELL/CLOSE、Partial/Multi Fill、Futures/Margin 与多 Cluster 固定资金归约尚未迁移。这些既有路径与正式路径清晰分离，且不得写入 Transaction Store 或生成正式 committed execution 结果。

## Recovery boundary

该设计提供已 durable commit transaction tail 的 forward recovery，不提供跨 Manager rollback，也不等于 Full Runtime Recovery。空 Runtime 的完整恢复仍需要可靠的 bootstrap snapshot、持久 Applied Ledger 策略以及 Runtime 生命周期 orchestrator。

## Removed design

删除 `OnlyInMemoryCommittedExecutionJournal`、`OnlySqliteCommittedExecutionJournal`、`OnlyExecutionCommitPort`、`OnlyCommittedExecutionQueryPort`、旧 append transaction DTO、旧 Builder/Commit Context、相关公共导出和旧 Journal 测试。受支持路径不再执行 Manager-before-Journal，也没有 fallback、feature flag、双写或兼容构造函数。

## Consequences

- Store failure 不产生 Manager Projection。
- Commit 后的 Projection failure 需要 reconciliation/forward recovery，而不是回滚或隐式重走旧路径。
- Result、Analytics、Artifact 和 Report 只消费 Projection Ready Transaction 中的 fact。
- 扩展成交范围必须先扩展纯 Planner、完整 Projection contract、真实 Target parity 和故障矩阵，再进入产品路由。
