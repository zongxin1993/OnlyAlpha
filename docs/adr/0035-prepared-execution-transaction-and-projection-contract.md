# ADR 0035: Prepared Execution Transaction and Projection Contract

- Status: Accepted
- Date: 2026-07-27

## Context

当前 Processor 在 durable Journal append 前修改多个 Manager，并由调用方先分配 execution sequence。Committed Fact 能审计成交经济结果，但不足以无损重建所有 Manager after-state；Outbox 也没有 Projection Ready gate。late append failure 因而会留下 Manager 已变而 durable authority 缺失的 reconciliation 边界。

## Decision

引入 schema version 2 的 immutable `OnlyPreparedExecutionTransaction`、完整 Fact Draft、15 项 ordered typed Projection、Precondition、Committed Transaction 和 canonical codec。Transaction Store 在单一锁或 SQLite transaction 中分配 sequence、finalize Fact，并原子保存 Transaction 与 Outbox。

Transaction ID 唯一由 identity schema version、Runtime、Gateway、Account、Broker Update 和 Trade ID 推导。`source_sequence` 不进入 ID：Broker Update ID 的公共契约已要求它在 Gateway scope 内稳定唯一。Durable Event ID 由 Transaction ID、Event Sequence 和 Event Type 通过固定 UUID5 namespace 推导。

业务幂等使用不含 `prepared_at` 和 Store/Outbox 状态的 `authority_hash`；完整载荷与 SQLite 损坏检测使用包含 Prepared audit envelope 和完整 Event envelope 的 `payload_hash`。Committed 记录分别保留 prepared authority hash、prepared payload hash 与 committed payload hash。

Settlement、Fee 与 Risk payload 改为可重放 DTO；统一 Reservation 被现金、持仓、保证金、Risk 四个有单位类型替代。Projection 与 Precondition 按 `(component, entity_key, expected_version)` 严格一一对应。

各 Projection Target 自身以 execution sequence、payload hash 和 entity version 保证幂等。Projection Applier 不发布 Event、不修改 Store。Outbox 只有在 Store 标记 Projection Ready 后可见。

本阶段不切换现有 ExecutionProcessor Trade 主链。新的 Transaction Store 与 legacy Runtime Journal 暂时并存，命名和接口完全分离；新体系不继承、不包装 `next_sequence()` / `append_transaction()` 语义。

## Consequences

当前已完成 Prepared Transaction Domain、Projection Contract、Store-assigned sequence、Memory/SQLite durable transaction、Projection Ready gate 和 Projection idempotency contract。

当前未完成 ExecutionProcessor 主链切换、具体 Manager pure reducer、具体 Manager Projection Target、full replay recovery、non-Trade durable facts 和 exactly-once delivery。不能声称本 ADR 已解决现有 Manager-before-Journal 问题；它建立的是下一阶段消除该问题所需的正式数据模型和持久化边界。
