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

`OnlyExecutionProjectionApplyContext` 提供 transaction ID、正 execution sequence、完整 `OnlyCommittedExecutionFact` 和 projection。Target 先检查 Component 和 Applied Ledger，再通过 Manager authority query 与正式 converter 读取真实 Current Authority。Current 与 Expected version/hash 一致时安装 Result；Current 已与 Result 一致而 ledger 缺失时只修复 Manager-owned replay index 并重建 ledger record。

Applied Ledger 的重复键只有完全相同记录才是 `IDEMPOTENT`；相同 sequence/component 的不同 transaction、entity 或 payload 是 `PAYLOAD_CONFLICT`。Expected path 成功是 `APPLIED`，Result authority + missing ledger 是 `RECOVERED`。Current version 同时不等于 Expected/Result 是 `VERSION_CONFLICT`；可接受 version 下 hash、scope、record、sequence 或 replay index 冲突是 `STATE_CONFLICT`。

## Restored authority

- Order：实体、查询索引、open/creation index 与 external/trade/venue dedup identity。
- Position/Allocation：active/closed repository、cycle 与统一 trade fingerprints。
- Settlement/Fee：原始 instruction、per-instruction version、release flags、instrument/scope、records 与显式 global sequence head；Target 不再用 `projection.after` 冒充 current。
- Account/Ledger：完整经济 snapshot、repository/index、trade/fee/cash identity；Reservation 由独立 Target 恢复。
- Risk：Reservation identity/order index/sequence 与 Cluster aggregate snapshot。
- Valuation：Runtime、Account、Ledger valuation versions，Account performance timeline，Strategy equity timeline 与 sequence。

Projection schema v4 将 replay-only metadata 纳入 canonical payload hash。Position/Allocation ID 的 cycle 不从字符串解析；Strategy valuation line、timeline point 和 record head 不从最终余额反推。

## Failure and side effects

Target 不发布业务 Event，不写 durable outbox 或 transaction store，不触发 audit/reconciliation/broker queue，也不调用普通 Manager mutation API。Applied Projection Ledger 是可丢弃、可重建的 Runtime 应用索引，不是第二持久业务真相；唯一 durable transaction authority 是 `OnlyExecutionTransactionStore`。

Batch 采用 forward recovery：Component N 失败时，1..N-1 保持 APPLIED；有 record 的 Component 重试返回 IDEMPOTENT，Manager 已安装但 record 缺失的 Component 返回 RECOVERED。单 Target 使用预验证、copy-on-write install plan、Repository authority replace 和不可失败 container swap 收口原子边界；不执行跨 Manager 回滚，也不标记 projection-ready。

## Current scope

Pure Planner、Real Manager Targets、Applied Ledger、Commit Coordinator 与 Runtime 正式装配已完成。受支持的 ExecutionProcessor 路径使用 commit-before-mutation，并在完整 Target Batch 后标记 Projection Ready。当前能力是“正确 Bootstrap/Before Authority + ordered committed transaction tail → Runtime Authority Recovery”，不是 Empty Runtime Full Replay；Applied Ledger 仍是可重建索引而非业务真值。

12 个 Generic T0 Target 现由 Runtime startup Recovery 使用同一正式 Registry。测试以 Target wrapper 和 failing Applied Ledger 覆盖每个
Component 的 target 前、Manager install/ledger 前、target 返回后、payload/version/state conflict，并比较真实 Manager economic digest；
生产 Target 没有故障开关。Recovery 完成前 Transaction 不进入 Ready Query 或 Outbox。
