# PR4.1 Ready Query 与 Runtime Recovery 修改前审计

- 审计日期：2026-07-28
- 审计基线：`cab2658 Feat: 实现 Execution Commit Coordinator 与正式事务提交主链`
- 工作树状态：仅有用户提供的 `prompts/ReadyQueryRuntimeRecoveryHook.md` 未跟踪；实现开始前没有其他源码改动。

## 第一性原理结论

1. Durable Commit 表示成交事务已经成为不可丢失、必须按顺序完成的持久 Trade authority；Projection Ready 表示事务的全部真实 Manager projection 已完成，因而可以进入 Result、Analytics、Scenario、Artifact、Report 和 Outbox。
2. Coordinator、Recovery、Admin、Diagnostic 和 Store contract 需要读取全部 committed transaction，包括未 Ready 记录。
3. Collector、RunPlan、正式 trade count、fee attribution、execution fingerprint、Scenario、Artifact、Report 和 Application query 只允许读取 Ready transaction。
4. 当前 Backtest Runtime 在插件资源 `initialize/connect` 与 Cluster `initialize_all()` 完成后拥有本阶段要求的正确 Bootstrap/Before Authority；应在设置 `READY` 前恢复 transaction tail。
5. Recovery 失败意味着 Manager authority 不完整，Runtime 必须进入 `FAILED`，不得启动 Cluster、发布 `RUNTIME_STARTED`、执行 Replay，或接收新 MarketData/Broker update。
6. Projection Recovery failure 与 Outbox Delivery failure 不同：前者是业务 Authority 未完成，后者发生在 Transaction 已 Ready 之后，不能回滚 Manager 或重放 Projection。当前 Backtest 启动采用严格 Outbox delivery 语义。
7. Manager 已是 projection Result authority 而 Applied Ledger 缺失时，真实 Target 的 `_prepare()` 通过 result version 和 result state hash 判断 `RECOVER`，仅修复 Manager-owned replay index 并重建 Applied Ledger，不执行 reducer 或普通 mutation。
8. 真实 Manager 不重复扣款、加仓、收费或追加 Timeline 的证明必须来自 12 个真实 Target 的 authority digest：恢复前后的 cash、frozen cash、quantity、available quantity、cost、fee、PnL、equity、reservation、timeline、manager version 和 event sequence 均保持预期；对象身份不构成证明。
9. PR4.1 只恢复“正确 Bootstrap Authority + ordered committed Trade transaction tail”。Full Bootstrap Snapshot、Empty Runtime Recovery、非 Trade transaction、Partial/Multi Fill、SELL/CLOSE、Futures/Margin 及 Paper/Live Recovery 均不在范围内。
10. 故障注入只放在 `tests/execution/support/` 的 Target、Applied Ledger、Store 和 EventBus decorator 中，不向生产 Runtime config、环境变量或 Target 增加故障开关。

## 查询调用方与权限分类

### 正式业务读取（必须迁移至 Ready Query）

- `src/onlyalpha/collector/backtest.py::OnlyBacktestResultCollector.collect()`：调用 `runtime.committed_execution_query.records()` 构建正式 execution facts。当前可把未 Ready transaction 混入 Result、Scenario、Artifact 和 Report 的下游事实。
- `src/onlyalpha/runtime/backtest/run_plan.py::OnlyBacktestRunPlan._build_result()`：调用同一 `records()` 构建 `trades`，并据此计算 `trade_count`、`OnlyCommittedTradeFeeAttribution`、reconciliation、result execution records 与 determinism fingerprint。当前未 Ready transaction 可进入正式计数和费用归因。
- `tests/integration_demo/scenarios/scenario_014_partial_fill.py`：示例场景直接读取 `runtime.committed_execution_query.records()`；属于产品示例读取，必须迁移至明确 Query。

`OnlyScenarioRunner`、Analytics、Artifact Writer 和 Report Builder 当前消费 `OnlyBacktestResult`/`OnlyBacktestFacts`，没有直接调用 Transaction Store；风险来自上述 Collector/RunPlan 上游。迁移上游后这些下游只能得到 Ready transaction。

### 管理、恢复、诊断读取（保留 Admin Query）

- `src/onlyalpha/execution/commit_coordinator.py::OnlyRuntimeTransactionCoordinator._coordinate()` 使用 `get_by_sequence()` 验证当前事务和直接前序的 durable state；这是 Coordinator 管理读取。
- `src/onlyalpha/execution/commit_coordinator.py::recover_unprojected()` 使用 Projection State Port 的 `unprojected()`；这是恢复读取。
- Store contract、Coordinator 和故障测试中的 `records()` 用于证明 commit 原子性、完整事务集合及故障状态，属于测试管理/诊断读取。
- `tests/execution/support/manager_authority_digest.py` 把全部 transaction store records 纳入测试诊断 digest；该用途不是业务 Result，应迁移为显式 Admin Query 名称但继续读取全部 committed transaction。

其他 `.records()` 调用属于 MarketData Audit Store、Execution Audit Store、Applied Projection Ledger、Fee/Settlement 等不同类型，不是 `OnlyRuntimeTransactionQueryPort` 调用，不应迁移。

## Store 查询语义

- `src/onlyalpha/execution/transaction_store.py::OnlyRuntimeTransactionQueryPort.records()` 明确定义为全部 committed transaction。
- `OnlyInMemoryRuntimePersistenceStore.records()` 在锁内按 `(runtime_id, execution_sequence)` 排序，但不筛选 `projection_ready`。
- `OnlySqliteRuntimePersistenceStore.records()` 通过 SQL 按 `runtime_id, execution_sequence` 排序，同样不筛选 `projection_ready`。
- 两个 Store 的 `unprojected()` 都表示未 Ready 记录；SQLite 当前先加载 `records()` 后用 Python 过滤。
- 两个 Store 均没有正式 `OnlyProjectionReadyRuntimeQueryPort`、`ready_records()` 或 `ready_count()`。因此 Admin 与 Business query 尚未分离。

## Runtime 装配与生命周期缺口

- `src/onlyalpha/runtime/backtest/runtime.py::OnlyBacktestRuntime.__init__()` 构造唯一的 `OnlyInMemoryRuntimePersistenceStore`、`OnlyInMemoryAppliedRuntimeProjectionLedger`、真实 12 Target、`OnlyRuntimeProjectionApplier`、`OnlyRuntimeTransactionCoordinator` 和 `OnlyExecutionOutboxPublisher`。
- Coordinator 随后只注入 `OnlyExecutionProcessor`；`src/onlyalpha/runtime/runtime.py::OnlyRuntimeServices` 没有保存 Coordinator、Recovery Service、Projection State 或 Outbox Port，只保存模糊的 `committed_execution_query`。
- `OnlyRuntime.initialize()` 当前执行插件 `initialize/connect`、Cluster `initialize_all()` 后直接设置 `READY`，没有 `recover_unprojected()`。
- `OnlyRuntime.start()` 当前先启动插件资源和 Cluster，再调用 `_drain_execution_outbox()`；旧 transaction event 可能晚于 Cluster 新业务事件。
- `_drain_execution_outbox()` 当前只记录 delivery diagnostic，不检查 `failed`/`remaining`，所以启动可能在 recovered Outbox 未完成时继续进入 `RUNNING`。
- `OnlyBacktestRuntime.receive_market_data_update()` 已检查 `RUNNING`；`receive_broker_update()` 当前没有状态检查，可在 Recovery 失败后继续入队。
- `OnlyRuntime` 没有 Runtime-owned execution recovery diagnostic，也没有 `OnlyRuntimeRecoveryError`。
- Runtime 失败后 RunPlan/Collector 仍可能构建部分 Result；由于它们读取全部 `records()`，当前 committed-but-not-ready transaction 可能进入正式 Result。

## 真实 Target 与现有故障覆盖

- `src/onlyalpha/execution/projection_targets.py::only_create_generic_t0_execution_projection_targets()` 注册 ORDER、POSITION、ALLOCATION、SETTLEMENT、FEE、ACCOUNT、STRATEGY_LEDGER、ACCOUNT_CASH_RESERVATION、STRATEGY_CASH_RESERVATION、RISK_RESERVATION、RISK、VALUATION 共 12 个真实 Target。
- 所有 12 Target 都通过 `_OnlyProjectionTargetBase._complete()` 在 Manager authority 安装并验证 result hash 后调用 `OnlyAppliedRuntimeProjectionLedger.record()`，因此全部存在“Manager 已安装、Applied Ledger 未记录”的真实故障窗口。
- `tests/execution/test_real_projection_target_forward_recovery.py` 使用真实 Target 验证逐点前向恢复，但直接调用 Projection Applier，没有经过 Store、Coordinator、Recovery Service 或 Runtime lifecycle。
- `tests/execution/test_projection_target_record_failure_recovery.py` 只对单 Target 验证 ledger record failure。
- `tests/execution/test_execution_commit_coordinator.py` 的 Coordinator 故障与恢复主要使用 `OnlyReferenceRuntimeProjectionTarget`，不能证明真实 Manager 的经济状态、Timeline、version 和 event sequence 不重复。
- 现有测试没有对 12 个真实 Target 统一覆盖 Before Target、After Manager/Before Ledger、After Ledger/Before Coordinator Completion、Version Conflict、State Conflict 和 Payload Conflict，也没有 In-memory/SQLite Runtime restart 产品测试。

## 相关 ADR 约束

- ADR 0038 固定真实 12 Target 顺序、受控 restore API 和 forward recovery。
- ADR 0039 规定 Applied Ledger 是可重建幂等索引，并定义 `RECOVERED` lost-ledger 路径。
- ADR 0040 限定当前能力为 Correct Bootstrap Authority + Transaction Tail，不是 Empty Runtime Full Recovery。
- ADR 0041 规定 Store 是唯一 durable Trade authority、Outbox 仅在 Projection Ready 后可见，并已要求 Result/Analytics/Artifact/Report 只消费 Ready transaction；当前调用方尚未落实该决策。
