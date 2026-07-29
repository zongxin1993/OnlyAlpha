# PR4.2.1 Recovery Causal Ordering 预实现审计

日期：2026-07-29
基线：`master`，HEAD `689415a`
范围：Backtest Runtime、MarketData Processor、Virtual Broker、Execution Transaction Store、Recovery、Cluster 生命周期、Result 与 Artifact。

## 结论

当前实现仍是“恢复 checkpoint → 重放时跳过已有事务 → 重放结束后批量 Rehydrate/Recover”的 PR4.2 模型。它无法保证后续 Strategy callback 在原 Broker Update 因果点观察到已恢复的 Manager authority。Checkpoint barrier 也早于 MarketData `_finish()`，因此 Audit 与完整 Result 前缀不属于 checkpoint 稳定边界。Result 仍组合当前 Replay 计数和若干进程内历史，完整字段不具备跨 Engine 等价性。

## 逐项审计

1. **一个 Bar 的当前完整阶段顺序**

   Historical Replay 推进 Backtest Clock；MarketData Processor 增加 processing sequence 并执行 validate、dedup、sequence/gap；Pipeline 标准化/聚合；`before_market_dispatch` 发布行情 facts、处理跨交易日结算与估值、让 Virtual Broker `on_bar()` 撮合并第一次 drain Broker Queue；Dispatcher 按稳定 Cluster 顺序执行 Indicator、Factor、Strategy；`after_market_dispatch` 调用 Broker `run_due()` 并第二次 drain Broker Queue、drain EventBus、执行 checkpoint barrier；返回 Processor 后 `_finish()` 才构造 Processing Result、追加 MarketData Audit 并发布 MarketData 内部事件。当前 checkpoint 因而早于 Processing Result、Audit 和最后的 MarketData event finalization。

2. **Virtual Broker 在 Strategy 前后执行的动作**

   Strategy 前：`deterministic_broker_driver.on_bar(base_bar)` 推进 bar sequence，对所有此前已 Accepted/Partially Filled 且满足 next-bar 条件的 open order 撮合，生成 Trade Update，并执行 Broker scheduler 到期任务；随后 Runtime drain Broker Queue。Strategy 后：`run_due()` 执行本 Bar Strategy 新提交订单产生的到期 accept/reject/cancel 等任务，随后再次 drain Broker Queue。因 before 阶段 `on_bar()` 自身也调用 `run_due()`，其新生成的到期动作同样在 Strategy 前被 drain。

3. **一个 Bar 内可能产生多少个 Broker Update**

   不限定为一个。每个可撮合 open order 可产生 Trade Update；scheduler 可同时产生多个 accepted/rejected/cancelled/connection 等 Update；Strategy 后提交的多个订单又可产生多个到期 Update。Queue 按稳定顺序逐条处理。

4. **一个 Bar 内是否可能产生多笔正式 Transaction**

   可以。一个 Bar 可撮合多个受正式 Prepared Transaction 路由支持的订单，每个 Broker Trade Update 独立生成一笔 Store-owned execution sequence，故同一 Bar 可产生多笔正式 Transaction。

5. **Checkpoint 当前位于 Processor 的阶段**

   `_checkpoint_barrier(update)` 位于 `after_market_dispatch()` 内，即 Strategy dispatch、第二次 Broker drain 和一次 EventBus drain 之后，但仍在 `OnlyMarketDataProcessor.process()` 调用 `_finish()` 之前。

6. **MarketData Audit 当前何时追加**

   `OnlyMarketDataProcessor._finish()` 构造 `OnlyMarketDataProcessingResult` 后立即向 `OnlyMarketDataAuditStore` 追加记录，随后调用 MarketData Event Publisher。对成功 Bar，这发生在 `after_market_dispatch()` 和 checkpoint 之后。

7. **Result Count 当前来源**

   `generated_count` 来自 RunPlan 再次调用 source `load_bars()` 得到的总记录数；`processed_count` 来自 Runtime replay cursor；`duplicate_count` 和 `gap_count` 来自本 Engine 本次 `OnlyHistoricalReplayResult`，不含 checkpoint 前缀；rejected/failed 只参与本次 replay status，未形成持久 Result Progress。

8. **Result Collector 依赖的瞬态内存历史**

   Collector 用 `event_bus.dispatch_results` 决定初始 sequence，用 `market_data_audit_store.records()` 构造 MarketData failures，用 `historical_replay_service.events` 构造 Strategy callback failures；RunPlan 另用内存 Audit records 汇总 quality flags，并用当前 replay result 汇总 duplicate/gap。这些均不是完整 checkpoint authority。

9. **Existing Transaction 当前在哪里被跳过**

   Backtest Runtime 构造的 `drain_execution_updates()` 在 `_in_recovery_replay` 为真时，先调用 persistence store `get_by_update()`；命中后只记录 seen update、把 ExecutionProcessor processing sequence 推到 committed fact sequence，然后 `continue`，Update 不进入 `OnlyExecutionProcessor.process()`。

10. **Ready Tail 当前何时 Rehydrate**

    `OnlyRuntimeRecoveryOrchestrator.recover()` 先执行 catch-up MarketData replay；catch-up 结束后调用 `OnlyExecutionReadyTailRehydrationService.rehydrate(tail.ready_prefix)` 批量应用真实 Projection Target。

11. **Unprojected Tail 当前何时恢复**

    同样在 catch-up replay 结束和 Ready prefix 批量 rehydrate 之后，由 `OnlyExecutionRecoveryService.recover(runtime_id)` 调用 Coordinator 的批量 `recover_unprojected()`。

12. **Recovery Replay 时 Strategy 的 Cluster State**

    存在 checkpoint 时 `_recover_runtime()` 在 orchestrator 前调用 `cluster_manager.start_all()`，Cluster 由 INITIALIZED 经 STARTING 进入 RUNNING；Dispatcher 因此以普通 RUNNING 状态执行恢复 Bar callback，没有专门 RECOVERING 权限边界。

13. **恢复时是否重复调用 `on_start()`**

    是。新 Engine 先 initialize 新 Cluster，检测到 checkpoint 后调用正常 `start_all()`，执行 Factor/Strategy `on_start()`，随后才 restore checkpoint。恢复完成后 Runtime start 路径虽然因 `_clusters_started` 避免再次 start，但恢复前的普通 `on_start()` 已造成一次不受恢复协议保护的业务副作用。

14. **Store 是否保存完整 Prepared Payload**

    SQLite `execution_transactions.prepared_payload` 保存 canonical 编码后的完整 `OnlyPreparedExecutionTransaction`，同时保存 prepared authority hash 和 payload hash；Memory commit 目前只做 Prepared codec round-trip 验证，没有把 Prepared 对象保存在独立 record 中。

15. **Memory Store 是否保留 Prepared Transaction**

    否。Memory Store 只保存 `OnlyCommittedExecutionTransaction`；Prepared 仅在 commit 栈内编码/解码验证后丢弃，当前 query 无法返回原 Prepared Contract。

16. **如何按 Broker Update 查询 Stored Prepared + Committed**

    当前做不到。现有 `get_by_update()` 只返回 committed。SQLite `_decode_row()` 会读取并校验 prepared payload，但只把 committed 返回；Memory Store 更未保存 Prepared。需要新增 Recovery Query Port 与 `OnlyStoredExecutionTransaction(prepared, committed)`，两种 Store 同契约实现。

17. **当前 Result Fingerprint 未覆盖的业务字段**

    `determinism_fingerprint` 的手工 projection 未覆盖 status、完整 run/data summary（包括 generated/processed/duplicate/gap/quality）、execution summary、Strategy extension、Factor/Indicator snapshots 与 business diagnostics。`result_fingerprint` 使用另一份手工字段表，同样遗漏 run/data/execution summary、performance、cluster results 等，并通过 `replace(... execution_recoveries=())` 临时删除恢复诊断。两者不是同一个 canonical business projection。

18. **当前 Artifact Manifest 使用的结果投影**

    Manifest 的 `result_fingerprint` 直接取 `result.result_fingerprint`；Artifact content fingerprint 则由 Artifact Writer 对其自行选择的规范化 dataset 内容再次调用 `only_result_fingerprint()`。它没有共享一个明确的 `only_backtest_business_projection()` 合同。

19. **业务诊断范围**

    MarketData validation/processing failure、Strategy callback failure、不可恢复的 execution/reconciliation/invariant failure、影响最终业务 status/facts 的 warning/error 属于业务诊断，必须和 baseline 等价并进入 Result Progress 或其他可恢复业务 authority。

20. **仅恢复运维诊断范围**

    checkpoint sequence/write 记录、recovery status/count、Ready/Unprojected 恢复计数、catch-up bar count、Outbox attempt count、Engine/connection identity、实际 artifact 路径和 wall-clock duration 只属于 operational diagnostics，不得进入 business fingerprint。

## 必须替换的生产路径

- 删除 Runtime 的 `_in_recovery_replay`、`_recovery_expected_update_ids`、`_recovery_seen_update_ids`。
- 删除 Runtime 外层 Existing Transaction skip。
- Runtime restart 不再调用批量 Ready rehydration 或批量 unprojected recovery。
- 所有 Broker Update 通过 ExecutionProcessor 的显式 NORMAL/RECOVERY 入口。
- Recovery 以 Stored Prepared + Committed 构建严格 sequence session，在原 Broker Update 点逐笔 resolve。
- MarketData `_finish()` 完成 Result、Audit、Result Progress、内部事件 drain 后才能 checkpoint。
- Cluster 恢复使用 RECOVERING/RECOVERED 生命周期，不运行普通 `on_start()`。
- Result count、quality 和 business failure 前缀由 checkpoint participant 恢复。
- Fingerprint、restart comparison 与 artifact business hash 统一使用唯一 canonical business projection。
