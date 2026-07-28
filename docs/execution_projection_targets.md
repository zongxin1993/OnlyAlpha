# Real Manager Projection Targets

## Product boundary

本组件把已经提交的 Generic T0 Cash transaction 恢复到真实 Runtime-owned Manager。它是 committed transaction 的 Authority replay 层，不是第二套 ExecutionProcessor，也不改变当前产品切换点。

```text
Committed Transaction
→ OnlyExecutionProjectionApplier
→ Component Target
→ Manager restore API
→ Applied Projection Ledger
```

Target Registry 由 `only_create_generic_t0_execution_projection_targets()` 一次创建，完整注册 12 个 Component。缺失 Target 明确使 Batch 失败；Margin、Position Reservation 和 Margin Reservation 不属于 Generic T0 Cash transaction，不注册空实现。

## Apply contract

`OnlyExecutionProjectionApplyContext` 提供 transaction ID、正 execution sequence、完整 `OnlyCommittedExecutionFact` 和 projection。Target 先检查 Component 和 Applied Ledger，再检查 Manager 当前 version/state hash，最后一次安装 After Authority 并记录 ledger。

Applied Ledger 的重复键只有完全相同记录才是 `IDEMPOTENT`；相同 sequence/component 的不同 transaction、entity 或 payload 是 `PAYLOAD_CONFLICT`。Manager version 或 state 不符合 precondition 时分别返回 `VERSION_CONFLICT`、`STATE_CONFLICT`，且不得修改 Manager。

## Restored authority

- Order：实体、查询索引、open/creation index 与 external/trade/venue dedup identity。
- Position/Allocation：active/closed repository、cycle 与统一 trade fingerprints。
- Settlement/Fee：instruction idempotency、records 与显式 global sequence head。
- Account/Ledger：完整经济 snapshot、repository/index、trade/fee/cash identity；Reservation 由独立 Target 恢复。
- Risk：Reservation identity/order index/sequence 与 Cluster aggregate snapshot。
- Valuation：Runtime、Account、Ledger valuation versions，Account performance timeline，Strategy equity timeline 与 sequence。

Projection schema v4 将 replay-only metadata 纳入 canonical payload hash。Position/Allocation ID 的 cycle 不从字符串解析；Strategy valuation line、timeline point 和 record head 不从最终余额反推。

## Failure and side effects

Target 不发布业务 Event，不写 durable outbox、transaction store 或 committed journal，不触发 audit/reconciliation/broker queue，也不调用普通 Manager mutation API。Applied Projection Ledger 是唯一新增副作用。

Batch 采用 forward recovery：Component N 失败时，1..N-1 保持 APPLIED；重试时它们返回 IDEMPOTENT，然后继续 N..end。Target 不执行跨 Manager 回滚，也不标记 projection-ready；这些属于后续 commit coordinator。

## Current scope

已完成 Generic T0 Cash 的 BUY OPEN、新建/增仓、零/非零费用和超额 Reservation release。当前 PR3 没有切换正式 ExecutionProcessor，也没有实现持久化 Applied Ledger 或 PR4 coordinator；`OnlyInMemoryAppliedProjectionLedger` 是正式内存实现和持久化实现的 Protocol 基准。
