# ADR 0035: Prepared Execution Transaction and Projection Contract

- Status: Accepted
- Date: 2026-07-27

## Context

当前 Processor 在 durable Journal append 前修改多个 Manager，并由调用方先分配 execution sequence。Committed Fact 能审计成交经济结果，但不足以无损重建所有 Manager after-state；Outbox 也没有 Projection Ready gate。late append failure 因而会留下 Manager 已变而 durable authority 缺失的 reconciliation 边界。

## Decision

引入 immutable `OnlyPreparedExecutionTransaction`、完整 Fact Draft、11 类 ordered typed Projection、Precondition、Committed Transaction 和 canonical codec。Transaction Store 在单一锁或 SQLite transaction 中分配 sequence、finalize Fact，并原子保存 Transaction 与 Outbox。

各 Projection Target 自身以 execution sequence、payload hash 和 entity version 保证幂等。Projection Applier 不发布 Event、不修改 Store。Outbox 只有在 Store 标记 Projection Ready 后可见。

本阶段不切换现有 ExecutionProcessor Trade 主链。新的 Transaction Store 与 legacy Runtime Journal 暂时并存，命名和接口完全分离；新体系不继承、不包装 `next_sequence()` / `append_transaction()` 语义。

## Consequences

当前已完成 Prepared Transaction Domain、Projection Contract、Store-assigned sequence、Memory/SQLite durable transaction、Projection Ready gate 和 Projection idempotency contract。

当前未完成 ExecutionProcessor 主链切换、具体 Manager pure reducer、具体 Manager Projection Target、full replay recovery、non-Trade durable facts 和 exactly-once delivery。不能声称本 ADR 已解决现有 Manager-before-Journal 问题；它建立的是下一阶段消除该问题所需的正式数据模型和持久化边界。
