# ADR 0038: Real Manager Projection Targets

状态：Accepted

## Context

ADR 0035–0037 建立了可提交的强类型 Projection、完整 replay payload 与纯 Generic T0 Cash Planner，但通用 Applier 仍只有 reference target。提交后的 After Authority 尚不能恢复真实 Runtime Manager，崩溃后也没有逐 Component 的应用幂等权威。

## Decision

Generic T0 Cash 的正式 replay 顺序固定为 Order、Position、Allocation、Settlement、Fee、Account、Strategy Ledger、Account Cash Reservation、Strategy Cash Reservation、Risk Reservation、Risk、Valuation。每个 Component 使用独立真实 Target，并且只能调用对应领域所有者的受控 restore API。

Target 接收 `OnlyRuntimeProjectionApplyContext`，其中包含 transaction identity、execution sequence、完整 committed fact 与 projection。Target 直接安装已提交 After State；不调用 Reducer、规则引擎、Fee Resolver、Broker、Clock 或普通业务 mutation API，也不发布 Event、不写 Transaction Store/Journal、不标记 projection-ready。

`OnlyAppliedRuntimeProjectionLedger` 以 `(execution_sequence, component)` 为键保存 transaction、entity、payload hash 与 result state hash。ADR 0039 补充其派生索引语义与 `RECOVERED` lost-ledger 路径。Batch 中途失败不跨 Manager 回滚；已完成 Component 保留记录，Manager 已安装但 record 缺失的 Component 通过真实 Current Authority 恢复索引。

Projection schema 升至 v4。Replay payload 显式携带 Position/Allocation cycle、Fee/Settlement record sequence head、Strategy valuation lines，以及 Account/Strategy equity timeline points。Trade fingerprints 由 committed fact 的 trade、broker update 与 venue trade identity 统一生成。Valuation Target 同步 Account、Strategy Ledger 与 Runtime valuation version authority，但不再次推进经济状态版本。

单 Target 原子边界是一个领域所有者的一次受控安装加 Applied Ledger 记录。所有冲突必须在安装前返回且保持 Authority 不变；restore API 先验证 replay metadata，再替换其拥有的索引、实体和序列。Batch 不提供跨 Manager 回滚，因为 committed authority 的恢复模型是 forward recovery。

## Consequences

- Runtime Manager 的 snapshot、repository、cycle、fingerprint、dedup index、record sequence 和 valuation timeline 可由 committed transaction 确定性恢复。
- Reservation Target 只恢复 Reservation Authority；Account/Ledger Target 恢复经济状态，Valuation Target 恢复版本与 timeline，职责不重复消费。
- Reference target 仅保留为独立 Applier contract test，并明确命名为 `OnlyReferenceRuntimeProjectionTarget`。
- PR4 可以在相同 Target Registry 和 Applied Ledger Protocol 上实现 commit coordinator 与 projection-ready 编排；若未来持久化 Applied Ledger，它仍只能是可丢弃 checkpoint/cache。本 ADR 不切换 ExecutionProcessor 产品路径。

## Verification

测试覆盖 12 Target 的正常、重复、version/state/payload/component 冲突；四个 PR2.1 场景的完整 Manager Authority parity；三笔连续 BUY OPEN；12 个逐点失败的 forward recovery；查询、后续 sequence/dedup 行为；timeline；无 Event、Journal、Audit、Reconciliation 或 Transaction Store 副作用；以及架构边界。
