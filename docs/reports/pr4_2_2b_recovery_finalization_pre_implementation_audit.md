# PR4.2.2b Recovery Finalization 预实现审计

## 基线与范围

审计基线为 `fa74bdbc1038e5bb5dd6a4edc06395405a11faeb`（`Feat: Recovery Phase State Machine 与 Exact Replay Boundary`），与任务预期基线一致。工作区开始时除任务 Prompt 外无未提交修改。本审计以当前源码、测试及 ADR 0039、0042、0044、0045、0046 为事实来源，不改变 PR4.2.2a 的因果重放和精确边界语义。

## 逐项结论

1. `_recover_runtime()` 当前顺序是：确认 checkpoint 开启；注册 Cluster participants；绑定 registry fingerprint；查询 latest；若存在 checkpoint，先 drain broker inbound 并以 `replay_non_transaction()` 处理 bootstrap update，再 `enter_recovery_all()`；调用 orchestrator `recover()`；异常时仅调用 `fail_recovery_all()`；成功后追加 diagnostic；`complete_recovery_all()`；设置 `_clusters_recovered=True`；执行 Runtime 私有 `_validate_post_recovery_authority()`；最后调用 checkpoint service `create()`。
2. Cluster 在 `OnlyClusterManager.complete_recovery_all()` 中，`on_recovery_complete()` 返回后立即由 `RECOVERING` 转为 `RECOVERED`。
3. Validation 位于该转换之后。Validation 失败时 Runtime 初始化最终失败，但 `fail_recovery_all()` 没有在该调用窗口执行；即使执行，它也只处理 `RECOVERING`，因此 Cluster 会残留 `RECOVERED`，直到外层关闭路径触发其他生命周期动作。
4. 当前 checkpoint `create()` 的顺序是：查询并验证连续 projection-ready transaction prefix；查询 previous 决定 sequence；构建 capture context；registry capture；构建含 `aggregate_payload_hash="pending"` 的 header；`only_seal_runtime_checkpoint()` 计算 sealed header；validate components；store `write_checkpoint()`。Capture、seal、write 尚未拆成独立服务方法。
5. 可以出现 commit 成功后 wrapper 抛异常。SQLite store 自身在事务中提交 checkpoint；当前 Port 和调用层允许测试/装饰 wrapper 在 delegate 返回后抛错，现有 checkpoint-window 测试已经展示该注入方式，但 Finalizer 尚不存在，无法分类或读回确认。
6. 可用于 read-back verify 的 header 字段包括 runtime id、checkpoint sequence、covered execution sequence、schema version、created_at、完整 replay cursor、config fingerprint、participant registry fingerprint、aggregate payload hash、pending outbox count；checkpoint 还包含完整 components，可逐项比较并重新执行 contract validation。
7. 恢复后的 Runtime authority 包括 execution transaction/store 与 ready query、durable outbox、order、account、position、allocation、strategy ledger、account/position/risk/margin reservations、fee、settlement、margin、execution processor/dedup/sequence/audit/reconciliation、applied projection ledger、broker projection、market-data processor、result progress、replay cursor、clock、broker/market-data inbound queues 和 EventBus。
8. 现有只读 API：store 提供 `records()`、ready/recovery query、`outbox_records()`、`pending_count()`、`latest_checkpoint()`；order 有 query service/list/open/get；account 有 `OnlyAccountQueryService.list_accounts/get`；position manager/query 有 `list_open/list_for_account/list_for_instrument`，allocation/position reconciliation已有公共 snapshot/query；strategy ledger 有 query/view；fee/settlement/margin manager分别暴露 records、authority lookup或 active reservations；broker 公共 query port有 open/all order query；EventBus 有 `pending_count()`；result progress有 `snapshot()`；applied ledger有 `record()`/`get()`。
9. 缺口主要是面向 Validator 的稳定聚合只读 Port：所有 reservation 类型的统一 authority view、包含 terminal order 的全量 order view、跨全部账户/Cluster 的 reconciliation 输入、broker checkpointable recovery view、runtime boundary 聚合 view、applied projection range view。应以最小 adapter/view 补齐，不能把 `OnlyRuntimeServices` 或 manager 私有容器交给 Validator。
10. `OnlyRuntimeLedgerReconciliationService.reconcile()` 接收账户、position、allocation、strategy ledger 与 valuation 等正式 snapshot/query 输入，生成 runtime 级差异；Backtest run plan 已在结果组装时调用。Validator 应复用它，而不是复制 capital/cash/PnL/equity 公式。
11. `OnlyExecutionInvariantChecker.check(account_id, instrument_id)` 可检查负账户余额、账户 frozen/available 等关系、负 position/allocation、T+1 availability、ledger equity view、account equity，以及账户/position reservation 的负数与 scope/quantity 基础关系。它按账户与标的检查，不替代全 Runtime 归约。
12. Position reconciliation 可比较账户 position 与 Cluster allocation 的 scope、数量和缺失/孤立关系；完整 authority 仍需按 account/instrument/side（hedging 时保持 side 独立）遍历所有 snapshot。
13. `OnlyInMemoryAppliedRuntimeProjectionLedger` 在每个 Runtime assembly 时新建，由 projection targets 记录本进程已应用/恢复 projection 的 payload/result hash；重启后只会因本次 tail/continuation 重放重新形成相关记录。
14. 它是可丢弃的加速与幂等索引，不在 checkpoint/SQLite 中作为事务事实持久化，也不覆盖 checkpoint prefix。持久交易存在性和 projection-ready 真值只属于 Runtime persistence store，因此它不能决定交易是否存在。
15. Outbox query 可读取 runtime 的全部 outbox row，包括 key（runtime/sequence/event index）、event、idempotency key、published 状态、attempt count、时间及错误，并可查询 pending count，足以检查 identity、引用和发布状态。
16. 标准 broker query port可提供 open/all order snapshot；当前 gateway snapshot包括 broker/local order id、account、instrument、side、status、quantity/filled/remaining、price及 broker sequence（实现可用时）。能力由 plugin capability 声明；checkpoint-enabled Backtest 当前只要求 deterministic checkpoint driver，尚未对 recovery authority query fail-fast。
17. `ResultProgress.processed_bar_count` 是成功应用或 gap-detected 的业务 bar 数；`last_market_processing_sequence` 是每次 market-data processing attempt 的连续 processor sequence。MarketDataProcessor `processing_sequence` 是处理尝试序列。Replay cursor 的 `processed_bar_count` 是 cursor 所覆盖的已处理 bar 数；这些只能同维比较，不能继续用 processing sequence 与 bar count 做大小关系。
18. EventBus 已有公开线程安全 `pending_count()`，也有 `drain()`；Finalizer 可在 callback 后 drain，再检查 pending count 为零。
19. `OnlyCluster.on_recovery_complete()` 是公开扩展 callback，默认空实现，但自定义 Cluster/Strategy 容器可以修改自己的恢复状态并通过已绑定 context 间接发布内部事件，因此 callback 后必须 drain 并重新检查 quiescence。
20. pending durable outbox 在 Base Runtime `start()` 内、plugin resources start 后、Cluster resume 前由 `_drain_execution_outbox()` 投递。初始化/finalization 期间当前不会投递。
21. recovered Cluster 同样在 Base Runtime `start()` 中，在 outbox 成功清空后由 `resume_recovered_all()` 从 `RECOVERED` 转为 `RUNNING`，随后 Runtime 才转 `RUNNING`。
22. 现有覆盖包括 checkpoint contract/corruption、连续 restart、execution outbox restart、checkpoint open-order restart、causal ordering、checkpoint window before/after-commit、multi-boundary tail、same-bar continuation、multiple continuation、result progress、stateful strategy restart及相关架构边界测试。它们验证因果恢复和业务等价，但没有完整 finalizer/authority matrix。
23. 完全缺失的窗口包括：callback 成功后 validation 失败的 Cluster cleanup；capture 失败；write 前失败的统一 finalizer phase；write 后 commit 已成功的 read-back 分类；latest missing/mismatch/hash/components mismatch；验证失败后禁止 outbox/resume/READY；完整 transaction/outbox identity；manager authority checker；broker parity；Engine A→B→C 以 post-recovery checkpoint after-commit fault 连续恢复。
24. 本任务应删除 Backtest Runtime 私有 `_validate_post_recovery_authority()`、直接作为 post-recovery finalization 的 checkpoint `create()` 调用、`complete_recovery_all()` 与弱语义 `fail_recovery_all()`；具体 error code和 authority 规则应迁出 Runtime。普通 per-bar `create()` 语义可保留为 capture+write facade。
25. 不得触碰 PR4.2.2a 的 `OnlyExecutionRecoverySession` 决策协议、prepared transaction 完整比较、`replay(update, session.execution_session)`、persisted-tail resolution、continuation commit、`OnlyBacktestRecoverySession.enter_boundary/observe_completion/require_boundary_completed`、after-market-processing 中 progress→event drain→boundary completion→checkpoint 的顺序，以及 replay service 的精确 cursor/boundary 终止规则。

## 实施结论

现状只能证明 causal replay 已结束，不能证明 Runtime authority 完整自洽或新 checkpoint 已真实持久。实施必须保持 Orchestrator 只产生 outcome；Validator 只依赖只读 Port并产出稳定报告；Finalizer 严格编排 callback、quiescence、validation、capture、write、read-back verify 和失败清理。只有完整成功后 Cluster 才可进入 `RECOVERED`，Runtime 才可进入 `READY`。
