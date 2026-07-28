# PR4 Execution Commit Coordinator 预实施审计

审计基线：`master` at `2428931`（2026-07-28）。工作区仅有用户提供、尚未跟踪的
`prompts/ExecutionCommitCoordinator.md`，未发现待合并的源码改动。

## 当前正式产品链

1. Backtest Runtime 在 `src/onlyalpha/runtime/backtest/runtime.py:390-455` 构造
   `OnlyInMemoryCommittedExecutionJournal`、旧 Outbox Publisher 和 `OnlyExecutionProcessor`。Runtime services 在
   `src/onlyalpha/runtime/runtime.py:264-268` 只暴露旧 committed query、Processor 与 delivery 组件。
2. Broker Trade 经 `OnlyExecutionProcessor.process()`（`src/onlyalpha/execution/processor.py:219`）进入
   `_dispatch()` / `_trade()`（`:405-419`, `:599-883`）。`_trade()` 依次直接修改 Order、Position、Allocation、
   Settlement、Margin、Fee、Account、Strategy Ledger、Reservation、Risk 和 Valuation Manager。
3. Manager 全部修改且 invariant 通过后，`process()` 才在 `src/onlyalpha/execution/processor.py:312-339` 用
   `OnlyCommittedExecutionBuilder` 构造 Fact，并调用旧 Journal `append_transaction()`。因此正式顺序是
   **Manager mutation → Journal append**；中途失败会留下部分 Manager authority，而 durable Trade authority 尚不存在。

## 已有 PR1–PR3.1 能力

4. `OnlyTradeExecutionTransactionPlanner` 位于 `src/onlyalpha/execution/trade_planner.py:62-106`，只从
   `OnlyTradeExecutionPlanningContext` 生成 Prepared Transaction。ADR 0037 和 `_validate()` 将正式范围限定为
   `GENERIC_T0_CASH`、LIMIT BUY OPEN LONG NETTING、单 Account/Cluster/Currency、无 Margin、整单成交；SELL/CLOSE、
   Partial/Multi Fill、Futures/Margin/Short/FX 等尚未迁移。Planner 尚未被 Processor 或 Runtime 调用。
5. `src/onlyalpha/execution/transaction_store.py` 已提供相同 Port 下的 In-memory 与 SQLite Store：原子分配 Runtime
   `execution_sequence`，持久化 Prepared/Committed、trade/update/transaction 幂等索引、Projection 状态和 Outbox。
   两者均以相同 authority hash 判定幂等/冲突，`unprojected()` 按 sequence 返回未 ready 记录。
6. `OnlyExecutionProjectionApplier`（`src/onlyalpha/execution/projection_applier.py:36-113`）严格按
   `projection_sequence` 应用；APPLIED/IDEMPOTENT/RECOVERED 继续，缺 Target、Target 异常或任意冲突立即返回 FAILED，
   并保留失败 Component 与已应用结果。它不写 Store、不发布 Event。
7. 12 个真实 Target 在 `src/onlyalpha/execution/projection_targets.py:854-889` 由
   `only_create_generic_t0_execution_projection_targets()` 注册，顺序为 Order、Position、Allocation、Settlement、Fee、
   Account、Strategy Ledger、Account Cash Reservation、Strategy Cash Reservation、Risk Reservation、Risk、Valuation。
8. `OnlyInMemoryAppliedProjectionLedger`（`src/onlyalpha/execution/applied_projection.py:51-77`）当前只是 Runtime 内
   `(execution_sequence, component)` 加速索引。ADR 0039 明确它可丢弃、可重建、非 durable business authority；真实
   Manager 已是 Result 而 ledger 丢失时由 Target 返回 RECOVERED 并修复索引。
9. 新 Store 已实施 Projection Ready Outbox 门禁：In-memory `pending()` 在
   `src/onlyalpha/execution/transaction_store.py:341-351` 过滤 `projection_ready`；SQLite 查询在 `:632-640` 使用
   `projection_ready=1`。`mark_projection_ready()` 原子更新 transaction 和对应 outbox ready 标志。

## 缺口与重叠权威

10. Runtime 当前没有装配新 Transaction Store、Applied Ledger、真实 Target Registry、Projection Applier、Planner 或
    Commit Coordinator；这些组件只在独立 contract/recovery 测试中组装。
11. 旧 `OnlyInMemoryCommittedExecutionJournal` / `OnlyExecutionCommitPort`（
    `src/onlyalpha/execution/journal.py:64-229`）和新 Transaction Store 都能保存 Trade fact、sequence、幂等索引和 Outbox。
    正式 Runtime 只使用旧 Journal，新 Store 尚未进入产品链；若直接并存会形成两份 durable Trade authority。
12. 依赖旧 Manager-before-Journal 行为的主要测试/fixture 包括：
    `tests/execution/test_execution_processor.py`、`tests/execution/test_committed_execution_journal.py`、
    `tests/execution/test_execution_economic_invariants.py`、`tests/execution/test_trade_planner_manager_parity.py`、
    `tests/execution/support/generic_t0_trade_harness.py` 以及 integration demo 的 execution/failure scenarios。特别是 parity
    harness 将 Processor 明确当作 “legacy” Manager mutation 参考链；PR4 后必须迁移为 Coordinator 产品链测试，而不能保留
    双写或兼容构造函数。

## 第一性原则结论

- 唯一 durable Trade authority 必须是 `OnlyExecutionTransactionStore`；Manager 仅在 durable commit 成功、前序 sequence
  已 ready 后安装 committed Result Authority。
- Transaction Store 负责 Prepared 幂等/冲突和 sequence；Target + rebuildable Applied Ledger 负责 Component apply 幂等；
  Coordinator 负责 Commit → Sequence Gate → Apply → Ready → Delivery Intent 的完整编排。
- 事务只有 `projection_ready=True` 后才可对 Event consumer 可见。Outbox 提供 at-least-once，不提供 exactly-once。
- 崩溃恢复从 Store 中最早的 unprojected transaction 开始，按 sequence forward recovery；不重新运行 Planner、规则、Fee 或
  Broker。当前边界仍是 Correct Bootstrap/Before Authority + committed tail，不是 Empty Runtime full recovery。
