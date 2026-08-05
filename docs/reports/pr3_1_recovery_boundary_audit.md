# PR3.1 Projection Recovery Boundary 修改前审计

审计日期：2026-07-28
审计 HEAD：`d9bfc7e322adbbf6e5d5938a2383faa287023824`（`Feat: Real Manager Projection Targets 与完整 Authority Replay`）

## 结论

当前实现证明的是“正确 Bootstrap/Before Authority + 已提交 Trade Transaction Tail → Runtime Manager After
Authority”，不是从空 Runtime 完整恢复。`OnlyExecutionTransactionStore` 已保存 durable transaction 和
projection-ready 状态，但尚未装配 Runtime Commit Coordinator；`OnlyAppliedRuntimeProjectionLedger` 只有内存实现，当前实际
用途是进程内逐 Component 幂等索引。

Fee 与 Settlement Target 在发现 Manager 中存在 instruction 后直接令 `current = projection.after`，没有读取 Manager
真实 authority。因此 Manager 已安装而 Applied Ledger 丢失时会被基类按 version 冲突处理，也无法发现 instruction、record、
sequence 或 settlement release flag 被篡改。

## 十二项审计回答

1. **Fee Manager authority**：保存 append-only `_records`、已处理 key 的 `_instruction_keys` 和全局 `_sequence`。
2. **原始 Fee Instruction**：不保存。相同 key 再次 `apply()` 只返回空 tuple，不能验证 instruction 内容是否一致。
3. **Fee Projection state**：`instruction`（instruction/runtime/cluster/account/order/trade/calculation source/key/created-at）、
   `records`（record/instruction/account/order/trade/amount/component type）、authoritative total、完整 fee breakdown、version 和
   Manager global record sequence head。
4. **Settlement pending authority**：`_pending[instruction_id]` 保存 mutable `_OnlyPendingSettlement`，内容是原始 runtime
   instruction 与 asset/trade-cash/withdrawable-cash/legal-settled 四个 release flag；records 和 global sequence 分开保存。
5. **Settlement per-instruction version**：没有。Projection 有 version，但 Manager pending state 没有对应 version authority。
6. **Sequence 语义**：Fee/Settlement Projection state 中的 `record_sequence_head` 对应 Manager 全局 record sequence，不是单
   instruction 局部 sequence。
7. **Target current 判定**：除 Fee/Settlement 外由 Manager snapshot/query 转换成正式 execution state；Fee/Settlement 仅检查
   `has_instruction*()`，存在时直接把 `projection.after` 冒充 current。基类只接受 current==expected，没有 result recovery 分支。
8. **restore 原子性**：Position/Allocation 在 Manager 容器替换前调用 Repository `save()`；Account 与 Strategy Ledger 在完整
   结果校验/Repository 写入前逐字段修改实体及内部索引；Account/Strategy cash reservation 先修改 reservation 容器再保存
   Repository；Valuation 依次修改 valuation authority、Account/Strategy timeline 和 valuation versions。Order、Risk Reservation、
   Risk 也直接原地替换多个索引。现有 in-memory Repository 的 `save()` 不失败，但 Port 允许失败注入，故边界尚未收口。
9. **Ledger record 失败窗口**：`_complete()` 在 Manager restore 和 after-hash 校验后才调用 ledger `record()`；record 抛错时
   Manager 已处于 Result Authority，Applied Ledger 仍缺失。重试会被误判为 `VERSION_CONFLICT`。
10. **前一 transaction 未 ready 时处理后一 transaction**：当前 Runtime 尚未装配 transaction commit/apply/ready coordinator，
    因而产品链既没有执行该序列，也没有建立这项 Runtime 调度保证；Store 能列出未 ready transaction，但该约束属于 PR4。
11. **Trade Projection Before Authority 来源**：测试/Planning Context 从已组装 Runtime 的真实 Manager 读取 Order、Account、
    Ledger、Reservation、Risk、Valuation 和可选 Position/Allocation；Settlement/Fee 初始为 `None`，并显式冻结 cycle、record
    sequence、instrument、market/fee instruction、valuation timeline 等 planning authority。
12. **空 Runtime 尚缺的非 Trade authority**：Runtime config、Account/Ledger creation、Instrument、Market Profile/compiled rule
    reference、Order submit/accepted/rejected/cancelled、Reservation creation、初始 valuation、external cash flow、Broker
    account/position update、market valuation、trading-day settlement、fee adjustment 和 Broker connection state。

## 恢复与持久权威判断

`OnlyExecutionTransactionStore` 应保持唯一持久业务事务权威。Applied Ledger 必须改为可由 Bootstrap Authority 加有序 committed
transaction replay 重建的 projection application acceleration index；本阶段不新增 SQLite Applied Ledger。

单 Target 继续采用 forward recovery，不提供跨 Manager rollback。所需边界是：先验证 scope/identity/version/hash/replay
metadata/repository constraints，在副本中构造完整 install plan，一次提交 Manager-owned authority，再验证 Result Authority，最后
记录 Applied Ledger。Manager 安装成功而 ledger record 失败必须通过 `RECOVERED` 重建索引，且不得重复经济 mutation、record、
timeline、version 或 event。
