# Prepared Execution Transaction

`OnlyPreparedExecutionTransaction` 是 Broker Trade Update 与 durable commit 之间的不可变权威输入，schema version 为 2。事务 ID 由 identity schema version、Runtime、Gateway、Account、Broker Update 与 Trade ID 通过唯一 SHA-256 工厂推导；`source_sequence` 不进入 ID，因为 Broker Update ID 已是 Gateway scope 内的稳定唯一身份。

`prepared_at` 仅表示 Runtime 完成 Prepared 计算的 UTC 审计时间，不得早于 Broker `ts_event`。它不进入 Transaction ID、Durable Event ID 或 `authority_hash`，但进入完整 `payload_hash`。

`authority_hash` 覆盖业务 scope、Fact Draft 权威字段、有序 Projection、逐项 Precondition 与 Event 业务语义，用于 Store 幂等和冲突判断。`payload_hash` 覆盖完整 canonical Prepared envelope，包括 `prepared_at`、完整 Event envelope、metadata、Event ID 与 authority hash，用于序列化完整性和 SQLite 损坏检测。

Durable Execution Event ID 由 Transaction ID、从 1 连续的 Event Sequence 与 Event Type 通过固定 UUID5 namespace 推导。Prepared 构造会验证 Transaction ID、Event ID、Runtime scope、Projection 固定顺序、Projection payload hash，以及 Precondition 与 Projection 的 `(component, entity_key, expected_version)` 一一对应。

当前尚未完成 Trade Planner、Manager reducer/target、Commit Coordinator、ExecutionProcessor 主链切换与 full recovery。
