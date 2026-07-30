# PR4.2.2c Recovery Event Gate 失败语义预实施审计

## 基线与范围

- 审计基线：`master` / `HEAD` 均为 `1cccfc40ed912d1d2b977919f4e2e16cd6c48ddd`。
- Prompt 预期基线与实际仓库一致；开始审计时仅 Prompt 文件未跟踪。
- 本报告先于任何生产代码修改完成。审计以当前源码、测试与 ADR 0048 为准。

## 现有覆盖与缺口

1. Gate 单元测试覆盖 fresh staging/FIFO open、批量 staging 容量原子失败、recovery bootstrap discard、
   RECOVERING/FINALIZING direct suppression、有界诊断样本、OPEN 前 durable/lifecycle 拒绝及 fail/close 幂等。
2. Router 单元测试覆盖 fresh flush、三类 route、recovery suppression、OPEN 前 route 拒绝、scope 前置校验及
   OPEN 后 EventBus capacity failure；缺少 empty batch 全 phase、批量 scope 尾部错误、open flush 首条/中间失败。
3. Fresh Bootstrap 已验证 initialize 后事件留在 staging、无 dispatch，start 后 FIFO flush，且
   `RUNTIME_STARTED` 最后发布。
4. Recovery Bootstrap 已验证 checkpoint 存在时丢弃临时 bootstrap，`ACCOUNT_CREATED` 与
   `STRATEGY_LEDGER_CREATED` 不在 OPEN 后补发。
5. Historical Direct suppression 现有测试只检查 suppression counter/sample 非空，以及 sample 中的投影未在
   OPEN 后 dispatch；它没有逐类证明所有正式生产链路事件。
6. 缺少 MarketData、Order、Risk、Account、Position/Allocation、Ledger、Fee/Settlement/Valuation 的独立小场景。
7. 现有 finalization failure 覆盖 Authority Validation mismatch 与 checkpoint commit-then-raise；正常 finalization
   也被覆盖。
8. Capture、pre-write、durable read-back verify，以及 Broker queue、MarketData queue、EventBus pending 三种
   quiescence failure 尚无完整 Engine Event Gate 断言。
9. `Router.open()` 先把 Gate 转为 OPEN、取出并清空 staged，随后逐条 `EventBus.publish()`；异常时 Gate FAILED。
10. 该 flush 当前不具批量原子性：中间失败前的前缀可以已经进入 EventBus queue，后缀不再尝试。
11. `EventBus.publish_many()` 只是循环调用 `publish()`，同样不具批量原子性。
12. Runtime start 在 router open、Outbox delivery、Cluster start/resume、`RUNTIME_STARTED` publish 全部完成后调用
    `event_bus.drain()`；finalizer 在 cluster completion 后也 drain，以便执行 quiescence 检查。
13. Plugin `start()` 发生在 `router.open()` 之前，故 Plugin Start failure 属于 OPEN 前失败。
14. Outbox delivery 发生在 `router.open()` 成功之后。
15. recovered Cluster resume 发生在 router OPEN 且 Outbox 完成之后。
16. `RUNTIME_STARTED` 仅在 Cluster start/resume 与 `_after_clusters_started()` 成功、Runtime 进入 RUNNING 后经
    lifecycle route 发布；其 publication failure 会令 Runtime/Gate FAILED。
17. Runtime FAILED 后 `stop()` 跳过 Outbox drain，但会 drain EventBus；这意味着 OPEN 后已接受前缀可在 cleanup
    dispatch，OPEN 前失败则应保持 queue 为空。
18. `EventBus.close()` 停止接收后会 drain queue。
19. Outbox `published` 仅表示 Router/EventBus 接受成功且本地 `mark_published()` 完成。
20. 当前不存在 Subscriber ACK。
21. 当前不存在 Event Delivery Watermark。
22. Direct Event 是 best-effort；没有 durable journal 时不能同时保证不重不丢。
23. OPEN 前 failure 合同是完全静默；OPEN 后 failure 保留已被 EventBus 接受的事实资格，cleanup 可 drain，
    但不得发布 `RUNTIME_STARTED` 或重复 dispatch。
24. 可复用支持包括 `only_create_tail_failure()`、same-bar continuation config/services、validation mismatch store、
    commit-then-raise store、SQLite reader、Event Gate/Router event factory 与既有三阶段 projection 比较。
25. 需要一个最小生产修复：为 EventBus 增加在 REJECT/FAIL_RUNTIME policy 下的通用原子批量入队，并令
    Router bootstrap flush 使用它；DROP_LOW_PRIORITY 明确拒绝该 API。其余缺口优先仅补测试与文档。

## 冻结合同

- OPEN 前：Gate/Runtime FAILED，queue 与 dispatch 为空，不投递 Outbox，不 start/resume Cluster，不发布
  `RUNTIME_STARTED`，bootstrap staging 清空，historical direct 永不补发。
- OPEN 后：已接受 Event 可能在 cleanup drain；未接受 Event 不得伪装为已发布，不得重复 dispatch，且仍不得
  发布 `RUNTIME_STARTED`。
- Outbox 保持 at-least-once；不引入 Subscriber ACK、Delivery Watermark、Direct Durable Journal 或 exactly-once。

## 实施结果

红测确认并修复了两个生产缺陷：

1. Bootstrap flush 原先逐条入队，中间 capacity/publication failure 会留下部分前缀。新增通用
   `OnlyEventBus.publish_many_atomic()`，在 REJECT/FAIL_RUNTIME policy 下先校验 accepting、全量 scope 与批量容量，
   再一次性 append；DROP_LOW_PRIORITY 明确拒绝该 API。Router `open()` 仅用该 API flush staged batch。
2. Cluster `on_start()` failure 原先只令 Cluster FAILED，Runtime 仍会进入 RUNNING 并发布 `RUNTIME_STARTED`。
   Runtime 现在在 fresh start/recovered resume 后检查所有 Cluster 均为 RUNNING，否则保留原始 Cluster failure 信息并
   fail closed。旧的多 Runtime 隔离测试相应冻结为：失败 Runtime 不得伪成功，其他 Runtime 仍可独立 RUNNING。

没有修改 Gate phase/route、Recovery Outcome、Finalizer phase、Cluster recovery lifecycle、Checkpoint/Outbox schema、
Execution Planner 或交易模型。

## 新增故障矩阵

- Finalization：Validation、pre-write、after-commit、read-back verify 的真实 SQLite A→B→C；capture 与三类
  quiescence failure 由既有 Finalizer 单测矩阵覆盖。
- Router：batch scope 尾部错误、所有 active phase empty batch、FAILED empty batch 既有拒绝语义、atomic FIFO、
  capacity failure 无部分入队、DROP_LOW_PRIORITY 明确拒绝。
- Runtime start：Plugin Start、Router Open、Outbox 首条/中间失败、fresh Cluster Start、recovered resume 调用边界、
  lifecycle publication failure。
- Cleanup：OPEN 前完全静默；OPEN 后已接受 bootstrap/Outbox 前缀只 drain 一次；重复 close 幂等。
- Direct/Durable categories：MarketData、Order、Risk、Account 与 Ledger 历史 Direct suppression，以及 Position、Fee、
  Settlement、Account、Ledger、Valuation 正式 Transaction Outbox delivery；suppressed Direct 永不补发。
- A→B→C：B after-commit failure 保留 checkpoint 且不投递 Outbox；C 按 B checkpoint 恢复、OPEN、投递 Outbox、
  最后发布 `RUNTIME_STARTED`，并保持 canonical business projection、fingerprint、Orders、Trades、Positions、
  Allocations、Account 与 Ledgers 等价。Artifact Manifest 等价继续由原三阶段产品测试覆盖。

## 验证记录

- `uv lock --check`：通过。
- `uv sync --frozen --all-packages --all-groups`：通过。
- `uv run ruff check src tests examples packages`：通过。
- `uv run ruff format --check src tests examples packages`：840 files already formatted。
- `uv run mypy src/onlyalpha`：410 source files，无问题。
- Virtual Broker / Tushare / MiniQMT Mypy：分别 11 / 15 / 25 source files，无问题。
- Runtime Event/Recovery/Checkpoint：102 passed。
- 新旧 Event Gate 集成集合：20 passed；Architecture Gate：9 passed。
- `tests/execution`：374 passed；`tests/order`：19 passed；`tests/risk`：23 passed。
- `tests/integration`：114 passed。
- `tests/architecture`：77 passed。
- Core 非外部全集：1008 passed。
- Virtual Broker：11 passed；Tushare：16 passed、1 deselected；MiniQMT：10 passed、1 skipped。
- Prompt 点名的其余 recovery 回归：7 passed。
- `uv run python scripts/version_sync.py check`：所有包同步于 `0.2.11`。
- `git diff --check`：通过；Windows 仅报告 LF→CRLF 提示。
- `uv build --all-packages`：Core 与三个插件的 sdist/wheel 全部成功。
- 干净 Python 3.12 venv wheel smoke：四个包导入成功；DataSource entry points 为 `miniqmt,tushare`，Broker entry
  points 为 `miniqmt,virtual`。
- 按用户要求未执行 pre-commit；未执行真实网络、Tushare Token 或本地 QMT 外部测试。

## 基线与交付状态

- 实际 `master` commit：`1cccfc40ed912d1d2b977919f4e2e16cd6c48ddd`。
- 本任务起始 commit：`1cccfc40ed912d1d2b977919f4e2e16cd6c48ddd`。
- 最终工作树 HEAD：`1cccfc40ed912d1d2b977919f4e2e16cd6c48ddd`；本任务未获授权创建 commit，变更尚未提交。
- 用户提供的 `prompts/RecoveryEventGateFailureSemanticsHardenin.md` 保持未跟踪且未修改。

## 明确未实现

Exactly-once、Direct Durable Journal、Delivery Watermark、Subscriber ACK、Partial/Multi-Fill、SELL/CLOSE 与
Paper/Live Recovery 均未实现。PR4.2.2c 已按当前源码合同冻结；下一步为 PR4.3 Partial / Multi-Fill Durable
Transaction。
