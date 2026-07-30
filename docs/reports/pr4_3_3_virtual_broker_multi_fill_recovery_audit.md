# PR4.3.3 Virtual Broker Multi-Fill Recovery 预实施审计

- 审计日期：2026-07-30
- 实际分支：`master`
- 实际起始提交：`1274963617fff3b51af00ed682386845eeaa8f6b`
- 提示词预期提交：`1274963617fff3b51af00ed682386845eeaa8f6b`
- 基线差异：无；PR4.3.1 与 PR4.3.2 已按 ADR 0049、0050 完成，PR4.3.3 尚未被其他提交实现。

本审计以当前源码、测试、ADR 0049/0050、架构文档和 Roadmap 为事实来源。结论是沿用现有
Virtual Broker、Runtime Checkpoint、Transaction/Projection/Outbox 与 Recovery 架构，只在插件增加确定性 Fill Plan
authority，并将 `broker.virtual` participant 升级到 version 2。

## 当前实现逐项审计

1. `maximum_fill_quantity` 由 Factory 从顶层 extensions 或 `matching.maximum_fill_quantity` 解析为 `Decimal`，创建
   `OnlyQuantity` 后注入 Gateway。`OnlyNextBarMatchingEngine.match()` 在触价时取
   `min(order.remaining_quantity, maximum_fill_quantity)`，因此每个后续触价 Bar 隐式产生一个部分成交。
2. 是。`on_bar()` 对稳定性尚未保证的 `order_store.open()` 结果遍历一次，每个订单只调用一次 `_execute()`。
3. 否。当前没有同一订单同 Bar 多 Step/多 Fill 的配置或执行循环。
4. `OnlyBrokerOrderSnapshot.filled_quantity` 显式保存累计成交量；每次 `_execute()` 用旧累计量加本次 Fill quantity，
   并据此选择 `PARTIALLY_FILLED` 或 `FILLED`。
5. 否。`remaining_quantity` 是 `quantity - filled_quantity` 的只读派生 property，不是独立存储字段。
6. `_trade_sequence` 每次 Broker execute 递增；Trade ID、Venue Trade ID 和 Fill external event ID 分别使用
   `virtual-trade-%08d`、`virtual-venue-trade-%08d`、`virtual-fill-%08d`。Broker Update ID 使用
   `virtual-update-<source_sequence>`；Fill 发布复用执行时取得的 source sequence。
7. `_next_sequence()` 推进 Gateway 全局 `_source_sequence`。Submitted Order、Accepted/Rejected/Cancelled Order snapshot、
   对应 Broker Update 以及每个 Fill 都使用该序列；Fill execute 取得一次序列，后续 `PUBLISH_FILL` 复用它而不再次推进。
8. 是。`_execute()` 先更新 Broker Account、Order、Trade，再向 Scheduler 写入 `PUBLISH_FILL`；到期 action 才向 Runtime
   inbound queue 发布 `OnlyBrokerTradeUpdate`。
9. 可以保存并恢复基本事实：checkpoint 已包含更新后的 Account/Order/Trade、序列和 Scheduler 完整 action payload，
   restore 后只运行发布 action。但当前缺少 Plan cursor 以及 Plan/Order/Trade/Scheduler 的交叉 authority 校验，无法证明
   多 Fill 下不会重做或丢失。
10. 当前 `PUBLISH_FILL` payload 保存 `type`、`order_id`、完整 `fill` JSON、`sequence` 与 `timestamp_ns`；Scheduler 另保存
    `due_ns` 和 scheduler `sequence`。它尚未保存 `plan_id` 与 `plan_step_index`。
11. 否。Gateway payload 没有 `schema_version`。
12. Runtime 中 `broker.virtual` participant version 为 1；插件 descriptor 的 checkpoint schema version 也是 1。
13. 是。`OrderStore.list()` 直接遍历 dict values，`open()` 继承该顺序。
14. 能。capture 按 Order ID 排序，restore 按 payload 顺序重建 dict，因此原始提交/插入顺序可能在重启后变成 Order ID
    顺序，导致多订单撮合顺序变化。
15. 否。`TradeStore.list()` 和 `query_trades()` 当前依赖 dict 插入顺序；checkpoint round-trip 会按 Trade ID 重建，虽在
    当前顺序 ID 下通常相同，但合同没有以 `source_sequence, trade_id` 明确冻结。
16. 接单时按 limit/reference price × 全部 remaining quantity 冻结现金；每次 BUY Fill 用相同订单价格对应的本次
    quantity 作为 reserved delta，`apply_buy()` 从 `frozen_cash` 扣除该 delta，并从 cash 扣实际 cost 与 fee。
17. `_cancel()` 对 `ACCEPTED/PARTIALLY_FILLED` 调用 `release_order()`；BUY 按 order price × remaining quantity 释放剩余
    Broker frozen cash，再保存 `CANCELLED` 并发布取消 Update。
18. `scenario_014` 中 `committed == ()` 已被 PR4.3.2 淘汰；现在部分 Fill 必须形成一笔 Projection Ready transaction，
    并验证 Fill Index、部分消费 Reservation 与 Risk active authority。`scenario_023` 已验证 Runtime 剩余 Reservation
    释放，但尚未验证 Broker Fill Plan 进入 `CANCELLED` 且未来 Step 不再执行。
19. 可复用 `OnlyFailOnceRuntimePersistenceStore` 的 COMMIT/AFTER_COMMIT/MARK_READY/Outbox/Checkpoint fault，
    `OnlyFailOnceExecutionProjectionTarget`、`OnlyFailOnceAppliedProjectionLedger`、after-commit checkpoint wrapper，及现有
    test-only Broker/Factory/Scheduler wrapper；不需要生产 fault switch。
20. 是。`test_engine_recovery_same_bar_continuation.py` 与 `test_engine_recovery_multiple_continuations.py` 已覆盖同一 Bar
    tail 恢复后的一个/三个正式 continuation transaction，但不是同一订单的 Virtual Broker Fill Plan。
21. 是。`test_engine_recovery_multi_boundary_tail.py` 覆盖跨两个 exact MarketData boundary 的 transaction tail。
22. 不需要。现有 Checkpoint Restore → exact replay → stored rehydration/unprojected recovery → continuation → authority
    validation → durable finalization → Event Gate OPEN 足以承载多 Fill。
23. 不需要。每个 Fill 已是一笔独立 immutable transaction，现有 Coordinator 已支持连续 sequence、Projection Ready
    和 Outbox；本任务只提供更多确定性 Broker Fill 输入及恢复测试。
24. 预计修改插件 `config.py`、`factory.py`、`matching.py`、`gateway.py`、`scheduler.py`、`stores.py`、`descriptor.py`、
    `__init__.py`，新增 `fill_plan.py` 与 `fill_plan_store.py`；Core 只修改
    `src/onlyalpha/runtime/backtest/runtime.py` 的 `broker.virtual` participant version。测试和规定文档同步更新。
25. 明确不修改 `trade_planner.py`、`commit_coordinator.py`、`fill_identity.py`、execution reducers、fee accrual、Runtime
    Event Gate/Router、Recovery Finalizer/Outcome；不改变 Transaction/Fill identity、Fill Index、PR4.3.2 accounting 或
    Outbox 语义，不实现 SELL/CLOSE、Futures/Margin、订单簿或生产 fault injection。

## 冻结实施合同

- 旧 `maximum_fill_quantity=None` 统一归一化为 WHOLE；正值统一归一化为 MAX_PER_BAR。
- 显式 SCHEDULE 支持 quantity 或 ratio steps；ONE_PER_BAR 拒绝重复 bar offset，ALL_DUE 按 step index 同 Bar执行。
- Plan 在 acceptance 校验并创建，和 ACCEPTED Order 一起成为 Broker-owned projection authority；Plan ID/Fingerprint 使用
  canonical JSON + SHA-256。
- Gateway checkpoint payload 与插件/Runtime participant 一并升级为 version 2；version 1 fail fast，不推测旧 Plan。
- Restore 按 Account → Order → Trade → Plan → Bar/sequence → Scheduler 顺序安装，再执行纯 authority validation。
- 已 Broker execute 但未 publish 的 Fill 只恢复 `PUBLISH_FILL`；取消只终止尚未 execute 的 Step。
- 多订单、Order query 和 Trade query 均使用显式稳定排序。
