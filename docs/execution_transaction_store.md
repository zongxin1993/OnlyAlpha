# Execution Transaction Store

Memory 与 SQLite Store 使用相同原子 commit、幂等和错误契约。相同 Transaction/Trade/Update 业务键且 `authority_hash` 相同返回原 committed transaction；同一业务键指向不同 authority，或多个幂等索引指向不同事务，只抛出 `OnlyExecutionTransactionConflict`。

`OnlyExecutionTransactionStoreError` 表示非业务存储失败，包括 SQLite trigger abort、I/O/locked/malformed/schema 故障、非业务唯一约束、Outbox 写入失败、序列化持久化失败和已存 payload 损坏。异常通过 `raise ... from exc` 保留 cause，不能伪装为 Conflict。

SQLite 仅在捕获 `IntegrityError` 后查询明确的 Transaction/Trade/Update 业务幂等键；不存在匹配事务时转换为 Store Error。Memory 在异常时恢复 transaction、三个幂等索引和 outbox 的原快照。SQLite transaction、indexes 与 outbox 处于同一 `BEGIN IMMEDIATE` 事务。两者失败均无部分写入，重试 sequence 不跳号。

Store 保存 Prepared/Committed schema v3 canonical payload 及相关 hash。读取时重新解码并验证 Prepared authority/payload、Committed payload、Prepared/Committed 关联与 Outbox Event；v2 明确拒绝。

Outbox 在 Projection Ready 前不可见。Ready 后保留确定性 Event ID，并独立记录发布尝试、失败和发布审计状态。
