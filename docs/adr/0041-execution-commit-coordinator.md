# ADR 0041: Execution Commit Coordinator

- Status: Accepted
- Date: 2026-07-28

## Context

旧成交路径先直接修改 Runtime Manager，再向 `OnlyCommittedExecutionJournal` 追加事实。Journal 失败会留下已改变但没有 durable transaction authority 的状态，也无法用明确的 projection progress 恢复。Prepared Transaction、Transaction Store、真实 Projection Target 与 Applied Projection Ledger 已存在，但此前没有进入 Runtime 产品主链。

## Decision

`OnlyRuntimePersistenceStorePort` 中的 transaction 记录是唯一 durable Trade authority。`OnlyAppliedRuntimeProjectionLedger` 仅记录某个 Projection 是否已应用，是可由 checkpoint authority 与有序 transaction tail 重建的幂等索引，不是第二业务真值。

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

Runtime sequence gate 要求当前事务的直接前序已经 Projection Ready；不能跳过未完成事务。Target 按 `OnlyRuntimeProjectionOrder` 顺序执行。任一 Target 失败时保留已完成前缀、记录 projection failure、隐藏 Outbox，并停止后续事务；重试通过 Applied Ledger 的 APPLIED/IDEMPOTENT/RECOVERED 语义继续 forward recovery。全部 Target 完成后才标记 Projection Ready。

Outbox 记录与事务一起 durable commit，但 `pending()` 只返回 Projection Ready 且未发布的记录。发布为 at-least-once；Event ID 稳定，消费者仍须幂等。本 ADR 不声称 exactly-once。

## Supported scope

产品主链当前覆盖 Generic T0 Cash、LIMIT、BUY、OPEN 的 whole fill。PR4.3.1 已建立多 Fill Order Authority 与 durable Fill
identity/index，但完整 partial-fill accounting 仍 fail closed；SELL/CLOSE、Futures/Margin 与多 Cluster 固定资金归约仍受各自
产品能力边界约束。不受支持的路径不得写入 Runtime Persistence Store 或生成正式 committed execution 结果。

## Recovery boundary

ADR 0044 已补全这里原先缺失的 Runtime Recovery：新 Engine 从完整 checkpoint authority 恢复，再按精确 replay cursor 追赶连续 transaction tail；不执行跨 Manager rollback。

## Removed design

删除 `OnlyInMemoryCommittedExecutionJournal`、`OnlySqliteCommittedExecutionJournal`、`OnlyExecutionCommitPort`、`OnlyCommittedExecutionQueryPort`、旧 append transaction DTO、旧 Builder/Commit Context、相关公共导出和旧 Journal 测试。受支持路径不再执行 Manager-before-Journal，也没有 fallback、feature flag、双写或兼容构造函数。

## Consequences

- Store failure 不产生 Manager Projection。
- Commit 后的 Projection failure 需要 reconciliation/forward recovery，而不是回滚或隐式重走旧路径。
- Result、Analytics、Artifact 和 Report 只消费 Projection Ready Transaction 中的 fact。
- 扩展成交范围必须先扩展纯 Planner、完整 Projection contract、真实 Target parity 和故障矩阵，再进入产品路由。
