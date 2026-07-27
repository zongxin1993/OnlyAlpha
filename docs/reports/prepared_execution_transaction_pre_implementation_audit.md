# Prepared Execution Transaction 修改前审计

- 日期：2026-07-27
- 事实来源：当前源码、测试与已接受 ADR；Prompt 仅规定本次目标。

## 审计结论

1. 当前 Trade 顺序为 Order、Position、Allocation、Settlement、Margin、Fee、Account、Strategy Ledger、Reservation、Risk、Invariant、Event commit、Journal append。
2. 上述 Manager 均在 Journal append 前被修改；late commit failure 只能进入 reconciliation，不能回滚。
3. `OnlyCommittedExecutionFact` 保存完整成交权威字段和各组件增量，但没有足以重建各 Manager after-state 的强类型 Projection。
4. `OnlyExecutionProcessor` 通过旧 `OnlyExecutionCommitPort.next_sequence()` 预分配 sequence，再调用 `append_transaction()`。
5. 旧 Memory/SQLite Journal 原子写 Fact 与 Outbox，但 commit 后 Outbox 立即可见，没有 Projection Ready gate。
6. Manager 没有统一记录 `execution_sequence + payload_hash + entity version`。
7. 旧 Journal、Outbox 和 Processor 测试直接依赖 `next_sequence()` / `append_transaction()`；当前 Runtime 主链仍依赖该接口。
8. 旧 `OnlyDurableExecutionCommit` 只持有 Fact、Event 和可选 checkpoint，不持有 ordered Projection。
9. 当前 Event 来自事务内 Event Buffer；Manager 仍有历史 publisher 边界，但新 Projection 合同不依赖它。
10. Runtime assembly、Processor、Collector query、Result 和 Outbox delivery 仍依赖 legacy committed journal；本阶段按任务边界不切换 Trade 主链。

因此本阶段新增独立、无继承关系的 Transaction Store。旧 Runtime Journal 只为未切换的生产主链暂存；下一阶段完成 Planner/Coordinator/Manager Target 后删除。
