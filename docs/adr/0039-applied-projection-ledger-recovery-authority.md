# ADR 0039: Applied Projection Ledger Recovery Authority

- Status: Accepted
- Date: 2026-07-28

## Context

ADR 0038 在 Manager restore 后记录 `OnlyAppliedProjectionLedger`。若进程在两者之间失败，Manager 已是 Result Authority，空
ledger 重试却会把它误报为 version conflict。若再把 ledger 建成独立持久业务真相，它又可能与 durable transaction store 永久
分叉。

## Decision

`OnlyRuntimePersistenceStorePort` 中的 transaction 记录是唯一持久业务事务权威。`OnlyAppliedProjectionLedger` 是 Runtime Projection Application
Acceleration Index：它按 execution sequence/component 快速识别重复 apply，支持 batch forward recovery，并避免每次重查完整
Manager authority。

Applied Ledger 必须能由正确 Bootstrap Authority 加 ordered committed transaction replay 确定性重建。当前只提供
`OnlyInMemoryAppliedProjectionLedger`；不新增 SQLite ledger。未来若为性能持久化，它仍是可丢弃、可重建的 checkpoint/cache，
不能决定交易、费用、结算或账户历史。

Target 状态机固定为：

```text
matching record                         → IDEMPOTENT
conflicting record                      → PAYLOAD_CONFLICT
Current == Expected                     → install Result → APPLIED
Current == Result, record missing        → repair indexes → RECOVERED
version outside Expected/Result          → VERSION_CONFLICT
accepted version with mismatched content → STATE_CONFLICT
component mismatch                       → INVALID_COMPONENT
```

RECOVERED 不运行 reducer、fee resolver、market rule 或普通 Manager mutation，不推进业务 version/event sequence，不重复 record、
timeline 或 Reservation consumption。它只验证/修复 committed Result 所要求的 Manager-owned replay index，随后重建 applied record。

单 Target 使用预验证、完整 install plan、copy-on-write container、Repository `replace_execution_authority()` 和不可失败 container
swap。Ledger record 仍位于 Manager install 之后；该窗口不做跨资源 rollback，而由上述 RECOVERED forward recovery 关闭。

## Consequences

Manager install 成功而 ledger record 失败不再破坏可恢复性。Applied Ledger 丢失不会丢失业务真相，也不会成为第二份 durable
authority。Batch 仍不跨 Manager 回滚；冲突保持 Manager 与 ledger 不变。
