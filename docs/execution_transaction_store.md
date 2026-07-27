# Execution Transaction Store

Memory 与 SQLite Store 使用相同事务契约。相同 Transaction/Trade/Update 幂等键且 `authority_hash` 相同时返回原 committed transaction；即使重试的 `prepared_at` 和 `payload_hash` 不同也不产生冲突。相同任一业务键但 authority 不同会抛出 `OnlyExecutionTransactionConflict`。

Store 保存 Prepared canonical payload、prepared authority hash、prepared payload hash、Committed canonical payload 与 committed payload hash。SQLite 读取时重新解码并验证 Prepared 双 Hash、Committed payload hash、Prepared/Committed authority 关联及 Outbox Event ID；schema version 1 明确拒绝，不做隐式迁移。

Sequence 在 commit 临界区或 SQLite `BEGIN IMMEDIATE` 内分配。Memory 在所有 codec、transaction 与 outbox 记录构造成功后才更新正式集合；SQLite 的 transaction 与 outbox insert 在同一事务中提交或回滚。

Outbox 在 Projection Ready 前不可见。Ready 后保留确定性 Event ID，并独立记录发布尝试、失败与发布审计状态；这些投递状态不改变原始业务 authority。
