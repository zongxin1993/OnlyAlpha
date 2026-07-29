# PR4.2.2a Recovery Phase / Boundary 预实现审计

日期：2026-07-29
基线：`master`，HEAD `7900f53`
范围：Execution causal recovery、Backtest replay/runtime、MarketData completion、Virtual Broker、checkpoint、result progress、现有恢复测试与架构门禁。

## 结论

当前实现把三个不同事实压缩成两个相互耦合的布尔语义：`OnlyExecutionRecoverySession.complete` 只表示持久 transaction tail 的索引已经耗尽，`boundary_complete` 则由 Recovery Replay Service 在一条 `HistoricalReplayService.run(single_record)` 返回后主动设置。Replay Service 又以 `session.complete` 决定调用 `complete_boundary()` 和停止，因此“最后一个持久 transaction 已解决”被错误地当成“其所在 MarketData boundary 已完整完成”。当最后一个持久 transaction 在 Strategy 前恢复、同一 Bar 后续又产生新正式 Trade 时，Session 已无 expected entry，`require_expected()` 会抛出 `RECOVERY_TRANSACTION_MISSING`，而不是走正常 durable commit。

## 逐项审计

1. **`OnlyExecutionRecoverySession.complete` 的准确含义**

   它仅等价于 `_index == len(_plan.entries)`，即 plan 中 Ready prefix / Unprojected suffix 已逐项 `resolve()`；它不证明 MarketData `_finish()`、Audit、Result Progress、EventBus drain 或 checkpoint cursor 已完成。

2. **`boundary_complete` 的设置者**

   状态保存在 Execution Session 的 `_boundary_complete`。唯一生产设置路径是 `OnlyBacktestRecoveryReplayService.run()` 发现 `session.complete` 后调用 `session.complete_boundary()`；Runtime 的 MarketData 完成回调不设置该状态。

3. **Recovery Replay 的停止点**

   `OnlyBacktestRecoveryReplayService.run()` 对每个 remaining record 构造单记录 cursor，调用 `self._replay.run()`；返回后若 `session.complete`，立即 `complete_boundary()`、设置局部 `resolved=True` 并 `break`。

4. **`HistoricalReplayService.run(single_record)` 的完整阶段**

   `step()` 先把 Backtest Clock 推进到 update event time，再调用 MarketData Processor。Processor 依次执行 validation、MarketData dedup、sequence/gap、pipeline；`before_market_dispatch()` 发布 market facts、结算/估值、Virtual Broker `on_bar()` 并第一次 drain Broker queue；Dispatcher 执行 Cluster 的 Indicator/Factor/Strategy；`after_market_dispatch()` 执行 Broker `run_due()` 并第二次 drain；随后 `_finish()` 构造 Processing Result、追加 MarketData Audit、发布 MarketData internal event，再调用 Runtime `after_market_processing()` 更新 Result Progress、drain owned EventBus、推进 cursor/执行 checkpoint barrier。之后 Replay Service 才取得单记录 run result。

5. **Broker 在 Strategy 前后的 Update 时机**

   Strategy 前，Virtual Broker `on_bar()` 先运行 due acceptance/cancel，匹配此前已 Accepted/Partially Filled 且满足 next-bar 的订单，调度并运行到期 fill publish；Runtime 随后 drain queue。Strategy 后，Runtime 调用 `run_due()`，处理本 Bar Strategy submit 后到期的 acceptance/rejection/cancel 等 update，再次 drain queue。

6. **生产 Virtual Broker 是否支持 Strategy submit 后同 Bar成交**

   不支持。`OnlyNextBarMatchingEngine` 只在 Strategy 前的 `on_bar()` 匹配，且 `_accepted_bar >= _bar_sequence` 时拒绝同 Bar匹配；Strategy 后只有 scheduler `run_due()`，不会再次执行 matching。

7. **测试专用同 Bar Broker Driver 的构造方式**

   应在测试包提供确定性的 Broker plugin/factory/driver，通过 Engine services 与正式 Runtime composition root 注入。Driver 保持公共 Broker SPI、由 Strategy submit 产生正式 Broker order request，并在 Strategy 后 `run_due()` 产生标准 Trade Update 写入其 Runtime-owned inbound callback；测试不修改生产 Virtual Broker、不读取 Runtime 私有字段，也不手工向 queue 注入 Trade。

8. **Recovery Session 活跃时 Broker Update 的 Processor 路径**

   Runtime `drain_execution_updates()` 从 Runtime-owned Broker inbound queue 顺序 drain。存在 `_execution_recovery_session` 时，每个 update 都调用 `execution_processor.replay(update, session)`；不存在时调用 `process(update)` 并执行 Delivery Coordinator。`replay()` 对所有结果强制返回 `delivery_intent=NONE`。

9. **Tail 消费完后新正式 Trade 的当前错误路径**

   新 Trade 仍进入 `_prepared_trade()`，使用正式 Planning Context 与 Planner 得到 Prepared；Recovery 分支无条件调用 `session.require_expected(update, prepared)`。此时 `next_entry is None`，直接抛出 `OnlyExecutionRecoveryError("RECOVERY_TRANSACTION_MISSING")`，异常向上导致当前 MarketData processing failed。

10. **Coordinator 在 Recovery 期间提交新 transaction 的能力**

    Coordinator 本身没有 Recovery 禁令。`commit()` 会校验 Prepared、调用同一 Store commit port 分配 execution sequence、应用 projection、标记 ready，并保留 transaction/outbox。当前阻碍只在 Processor Recovery 分支从不选择 `commit()`。

11. **Recovery 新 transaction 的 Outbox 是否保持 Pending**

    正常 `commit()` 在 Store commit 时创建 durable outbox row；`ExecutionProcessor.replay()` 最终把 processing result 的 delivery intent 替换为 `NONE`，Runtime 在 Session 活跃时也不调用 Delivery Coordinator。因此 continuation 可保持 Pending，直到既有 recovery finalization 路径结束后交付。

12. **Deduplicator 与 Sequence Tracker 的推进情况**

    Checkpoint 会恢复 Execution deduplicator、sequence tracker 和 processor processing sequence 到 checkpoint boundary。每个 Ready rehydrate / Unprojected recover 成功后，Processor 仍调用 deduplicator `remember()` 和 sequence tracker `observe()`，所以 tail 按原因果点推进；新 continuation 随后可在相同 tracker 上继续。

13. **Replay Cursor 的更新阶段**

    Runtime `after_market_processing()` 先更新 Result Progress、drain EventBus，再对 APPLIED/GAP_DETECTED result 调用 `_checkpoint_barrier(completion)`；barrier 用完整 completion identity 更新内存 `_replay_cursor`，然后才决定是否写普通 checkpoint。

14. **Result Progress 与 MarketData Audit 的完成时机**

    Audit 在 `OnlyMarketDataProcessor._finish()` 构造 result 后先追加；MarketData internal event 随后发布；Runtime `after_market_processing()` 再调用 `result_progress.observe_market_data_result()`，之后 drain owned EventBus。故它们都晚于 Strategy/Broker 阶段，并处于单记录 `HistoricalReplayService.run()` 返回之前。

15. **Recovery 活跃时为何必须继续禁止普通每 Bar checkpoint**

    Tail resolved 与整个 recovery finalization 不等价。即使内存 cursor 已推进，普通 checkpoint 若在 Session deactivate 前写入，会把 recovery 中间态、尚未统一交付的 Pending Outbox 或未完成的收尾 authority 固化为普通稳定 checkpoint。现有 `_recover_runtime()` 在 causal replay 返回、恢复生命周期完成及校验路径中创建 post-recovery checkpoint；本 PR 不应建立第二个 finalizer。

16. **Orchestrator 的 `session.require_complete()` 调整**

    当前 Orchestrator 在 causal replay 返回后只调用 Execution Session `require_complete()`。实施后它必须同时依赖 Replay Service 返回的 Backtest boundary result/contract：Execution Session 使用 `require_tail_resolved()`，Backtest Session 使用 `require_boundary_completed()`；Orchestrator 不自行推导 boundary，也不保留旧 wrapper。

17. **Recovery Diagnostic 的 continuation 信息**

    需要独立的 `continuation_transaction_count`，可同时记录 final boundary update identity。Continuation 不能计入 `rehydrated_transaction_count` 或 `recovered_transaction_count`；这些是 operational diagnostics，不进入 canonical business projection。

18. **只验证 Session、未验证真实 Engine 的现有测试**

    `tests/execution/test_causal_execution_recovery.py` 直接构造 Store/Plan/Session 并手工 `require_expected()`、`resolve()`、`complete_boundary()`，只覆盖模型。Execution processor 的既有单元测试主要覆盖普通 processing/coordinator，不证明 Engine restart 的 same-Bar continuation。真正经过 Engine restart 的现有场景主要在 `test_engine_continuous_restart.py`、`test_engine_multi_transaction_tail_recovery.py`、`test_engine_recovery_causal_ordering.py` 等，但都没有构造 Strategy 后同 Bar continuation fill。

19. **仅做源码字符串检查的现有 Architecture Test**

    `tests/architecture/test_causal_recovery_result_equivalence_boundaries.py` 通过 `Path.read_text()` 和字符串/index 断言检查 Runtime 单 Session、Prepared 比较、completion/checkpoint 顺序、canonical projection 与 lifecycle；它是辅助门禁，不是行为证明。`tests/integration/test_engine_recovery_checkpoint_window.py` 中也有类似源码顺序断言。

20. **实施后必须删除的旧状态/API/假设**

    删除 Execution Session 的 `complete`、`boundary_complete`、`_boundary_complete`、`complete_boundary()`、`require_complete()` 和 `require_expected()`/`resolve()` 旧命名；Runtime 删除 `_execution_recovery_session`，只保存一个 Backtest Recovery Session；Replay Service 删除基于 `session.complete` 主动完成 boundary 的逻辑；删除旧测试中手工完成 boundary 及把 tail complete 当 boundary complete 的断言，不保留兼容 wrapper。

## 实施约束

- Execution 层只拥有 persisted-tail phase、decision、resolution 和 continuation sequence，不导入 Runtime/Backtest 类型。
- Backtest Session 拥有 exact MarketData boundary identity 与 completion contract。
- Tail 未 resolved 时任何 store-missing Trade 继续 fail closed；Tail resolved 后的新 Trade 必须走同一 Planner 与 `coordinator.commit()`。
- Continuation 在 Recovery 中 durable、projection ready、outbox pending、processing status APPLIED，但不即时 delivery。
- Boundary completion 只能由 Audit → Result Progress → EventBus drain → Runtime `after_market_processing()` 路径观察。
