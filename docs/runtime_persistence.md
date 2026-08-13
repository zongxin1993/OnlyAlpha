# Runtime Persistence

`OnlyRuntimePersistenceStorePort` 是 Runtime 的统一持久化边界。Memory 与 SQLite 实现共享事务提交、投影进度、Outbox、检查点、幂等和错误契约；Runtime 只能装配一个 Store 实例，不能分别创建成交与检查点数据库。

同一 Transaction/Trade/Update 业务键且 `authority_hash` 相同时返回原 committed transaction；同一业务键指向不同 authority，或多个幂等索引指向不同事务时抛出 `OnlyRuntimeTransactionConflict`。I/O、SQLite lock/malformed/schema、非业务唯一约束、Outbox、序列化和损坏数据错误统一抛出 `OnlyRuntimePersistenceStoreError` 并保留 cause。

SQLite Runtime Persistence schema v7 将 metadata、transactions、indexes、outbox、checkpoint headers/components 和 durable Timer
occurrence journal 保存在同一数据库。事务、索引与 Outbox 使用同一 `BEGIN IMMEDIATE`；一个检查点的 header、全部 components
和 retention 删除也使用单一原子事务。旧 Persistence schema 与历史 `execution_store_metadata` 布局均明确拒绝，
不提供隐式迁移或 Memory fallback。Runtime Checkpoint envelope 使用独立 schema v5，不能与 Store schema 混为一谈。

Store 保存 canonical payload 与 SHA-256 hash，读取时重新验证。Outbox 在 Projection Ready 前不可见；Ready 后保留确定性 Event ID，并独立记录发布尝试与发布状态。检查点读取验证 Runtime/config/participant-registry 身份、连续序号、header hash、component hash、组件全集和 schema version。

Runtime 只通过窄 Port 使用成交、Outbox、Timer occurrence 与检查点能力。Store 不负责恢复 Manager；恢复由
`OnlyRuntimeRecoveryOrchestrator` 分为 local durable bootstrap、driver-specific continuity completion 和 common verified finalization。

Checkpoint 保存的是 proven canonical semantic boundary，不是 Python process snapshot。Streaming checkpoint 不包含 inbound queue、
partial live Bar、subscription ID、线程、锁、socket 或 clock scheduler state。SIM durable product 只接受稳定 state root 下的 SQLite；
相同 `engine_id/runtime_id/state_root` 自动恢复，identity/schema/fingerprint/hash/Timer authority/continuity 任一不一致即 fail closed。
`OnlyRuntimeStateLease` 使用 OS advisory lock 提供单 writer authority，diagnostic metadata 不是 stale-lease 决策依据。
