# Prepared Execution Transaction

`OnlyPreparedExecutionTransaction` 是 Broker Trade Update 与 durable commit 之间的不可变权威输入。它固定 Runtime、Gateway、Account、Update、Trade scope，包含完整 `OnlyCommittedExecutionFactDraft`、有序强类型 Projection、原始 Outbox Event 和状态前置条件。

Prepared Transaction 不含最终 `execution_sequence` 和 commit timestamp，也不持有 Runtime、Manager、Clock、EventBus、Callable 或 Broker SDK 对象。`stable_hash` 覆盖 schema、scope、Broker identity、Fact Draft、Projection 顺序、Event（含原始 event ID）和 Preconditions；不覆盖 Store sequence 或 commit time。

稳定 codec 使用 canonical JSON：Decimal 使用十进制字符串，`OnlyTimestamp` 使用 Unix nanoseconds，Enum 使用稳定 value，Identifier 使用规范字符串，tuple 保留顺序，mapping 按 key 排序。禁止 `repr()`、pickle 和 Python 对象地址。

当前已完成 Prepared Transaction Domain、Fact Draft、canonical round-trip 和 stable hash。当前未完成 pure Trade reducers、Transaction Planner 和现有 `OnlyExecutionProcessor` 主链切换。
