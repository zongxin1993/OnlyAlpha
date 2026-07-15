# Architecture Consolidation M1 Report

- 日期：2026-07-15
- 范围：现有组件装配、Vertical Slice、架构审计与回归验证
- 结论：**ACCEPTED**

## 1. 已集成组件

本次没有新增领域组件。统一链路实际复用了以下既有组件：Domain、Clock、EventBus、Backtest Runtime、RuntimeContext、
Cluster、MarketData Pipeline、Bar Aggregation、MarketData Snapshot、Order、Risk、Position、Position Allocation、
Strategy Ledger、Settlement Service 和 Placeholder Execution Service。

## 2. 组件关系图

```text
OnlyEngine
└── OnlyBacktestRuntime (唯一可变资源所有者 / 单写入者)
    ├── Clock
    ├── EventBus
    ├── MarketData Pipeline ── Aggregation ── immutable Snapshot
    ├── ClusterManager ── Cluster ── scoped RuntimeContext Views
    ├── OrderManager ── RiskService ── PlaceholderExecutionService
    ├── PositionManager
    ├── PositionAllocationManager
    ├── PositionReservationManager
    └── StrategyLedgerManager
```

生产模块 AST import graph 的强连通分量检查结果为零：未发现循环依赖。

## 3. Runtime 装配关系

`OnlyBacktestRuntime` 从构造起独占 Clock、EventBus、Pipeline、OrderManager、RiskService、PositionManager、
PositionAllocationManager、PositionReservationManager 和 StrategyLedgerManager。不同 Runtime 的 Manager 实例均不共享。

Runtime 新增的 `process_trade(fill_update, position_trade)` 是现有 Manager 的同步编排入口，不是新业务状态域，也不执行撮合。
`settle_positions(previous_trading_day, trading_day)` 只代理既有、由 TradingDay 驱动的 Settlement Service。

## 4. Context 注入关系

```text
OnlyRuntimeContext (frozen, Cluster-scoped)
├── OnlyClockView
├── OnlyMarketDataView
├── OnlyInstrumentView
├── OnlySubscriptionService
├── OnlyTimerService
├── OnlyOrderServiceView
├── OnlyRiskSnapshotView
├── OnlyPositionContextView
└── OnlyStrategyLedgerContextView
```

Context 不暴露 EventBus、Manager、Gateway、Pipeline、Aggregator、可变 Cache、Reservation Manager、Settlement、
Reconciliation 或 Placeholder Execution。Cluster 只能通过 `ctx.orders` 发出订单命令，其余交易状态均为 scoped 只读 View。

## 5. Vertical Slice 流程图

```text
1m Bar
→ Runtime Clock advance
→ MarketData Pipeline
→ shared 3m Bar / immutable Snapshot
→ Cluster.on_bar()
→ ctx.orders.submit()
→ final synchronous Risk evaluation
→ Order + Risk/Position/Cash Reservations
→ Placeholder Execution transport received
→ explicit standardized Accepted / Fill / PositionTrade
→ Runtime.process_trade()
→ Order Update
→ Account Position
→ Cluster Position Allocation
→ Strategy Ledger Trade Accounting
→ Allocation-authoritative Valuation
→ Reservation completion
→ past-tense fact Events
→ immutable Final Integration Snapshot
→ Report
```

Placeholder 不生成 Venue Accepted、Fill 或 Trade。Integration Scenario 明确构造标准化外部事实，再交给 Runtime 正式入口。

## 6. Integration Environment 与场景

`examples/integration_demo/` 提供一个统一 `OnlyIntegrationEnvironment`、EventRecorder、ReportBuilder、共享 fixtures/assertions
边界、一个 `run_all.py` 和 12 个顺序场景：

1. Runtime 启动；
2. 1m→3m Bar 聚合；
3. Order 提交；
4. Risk 通过；
5. 买单成交；
6. Position 更新；
7. Position Allocation 更新；
8. Strategy Ledger 更新；
9. 第二天 T+1 结算；
10. 卖出；
11. 已实现收益；
12. 最终 Snapshot 与跨组件不变量。

## 7. 架构原则审计结果

| 检查项 | 结果 | 证据 |
|---|---|---|
| Architecture Principles | PASS | 自动架构测试与完整链路共同验证 |
| Runtime 装配全部现有交易组件 | PASS | 12 场景使用同一 Runtime |
| Context 注入全部 scoped View | PASS | 禁止能力集合与 Context API 审计 |
| Manager 仅由 Runtime 拥有 | PASS | 双 Runtime 实例隔离测试 |
| 循环依赖 | PASS | AST import graph 无环 |
| Event 驱动状态机 | PASS | 生产代码除 EventBus 自身外无 subscriber；业务均为函数调用 |
| 直接修改内部状态 | PASS | Integration Demo AST 禁止内部 Manager 字段访问 |
| Snapshot immutable | PASS | Order、MarketData、Position、Allocation、Ledger frozen 检查 |
| Context 只暴露 View | PASS | Manager/EventBus/Gateway/Cache/Pipeline 均不可见 |
| Reservation 生命周期 | PASS | Risk=CONSUMED、Position remaining=0、Cash remaining=0 |

## 8. 跨组件不变量

- Runtime/Cluster Scope 没有串流；
- 1m→3m 只由 Runtime 共享 Aggregator 生成一次；
- Pipeline Snapshot 在 Cluster 回调前完成，Cluster 收到自身 scoped frozen Snapshot；
- Risk ACCEPT 后立即建立预占，Placeholder 收到前完成资金/仓位保护；
- Risk Reject/Error 的历史单元测试仍证明不会创建 Order 或调用 Execution；
- Order、Position、Allocation 和 Ledger 的状态修改均通过正式同步接口；
- Position 事实在成功修改后进入 Runtime EventBus，Event 不反向驱动状态；
- Account Position = Cluster Allocation Sum + Unallocated；完整场景中 Unallocated 为零；
- T+1 买入当日不可卖，TradingDay 切换后账户与 Allocation 同步结算；
- 买入 100×10.00、费用 1.00，卖出 100×12.00、费用 1.00：Realized PnL=200.00，Net PnL=198.00；
- Cash View 与 PnL View 均为 1,000,198.00 CNY；
- 完整平仓后 Account Position 与 Cluster Allocation 均为空；
- 相同输入的 Order Snapshot、Position/Allocation 历史、Ledger Snapshot 和 Event Trace 可确定性重放。

## 9. 测试结果

最终通过 `scripts/run_component_validation.sh` 一次性执行：

| 层次 | 命令 | 结果 |
|---|---|---|
| 所有历史与新增测试 | `uv run pytest -q` | **196 passed in 1.01s** |
| Integration | `uv run pytest -q tests/integration` | **22 passed in 0.47s** |
| 12 场景 Vertical Slice | `uv run python -m examples.integration_demo.run_all` | **12 PASS** |
| Deterministic Replay | `uv run pytest -q tests/integration/test_vertical_slice_replay.py` | **1 passed in 0.21s**；内部重复 10 次 |
| Ruff | `uv run ruff check .` | **PASS** |
| Format | `uv run ruff format --check .` | **296 files already formatted** |
| Mypy | `uv run mypy src/onlyalpha` | **137 source files, no issues** |

没有删除、skip 或放宽任何历史测试；全量测试从整合前 175 个增加到 196 个。

## 10. 发现并修复的问题

1. **完整成交没有 Runtime 编排入口**：增加同步 `process_trade()`，固定 Order→Position→Allocation→Ledger→Event 顺序。
2. **Cash Reservation 会被 Order Fill 和 Ledger Accounting 重复消费**：完整入口延迟到 Ledger Accounting 唯一消费；独立
   `process_order_update()` 保持原有行为。
3. **Risk Reservation 在 FILLED 后保持 ACTIVE**：复用既有 `CONSUMED` 状态，在完整成交成功后完成生命周期。
4. **Position 事实没有接入 Runtime EventBus**：绑定 Runtime Position Event Publisher Adapter；事件只在状态成功后发布。
5. **Position Allocation 缺少只读 closed history 查询**：增加 frozen closed Snapshot 查询，用于完整平仓后的 Ledger Accounting。
6. **验证脚本不可执行且含占位符**：改为真实全量验证入口，包含 pytest、Integration、Demo、Replay、Ruff、Format 和 Mypy。
7. **Position/Strategy Ledger 文档仍声明彼此或纵切面未接入**：同步修正文档和 ADR 实施记录。

## 11. 使用的 Placeholder / Test Boundary

- `OnlyPlaceholderExecutionService`：生产已有明确 Placeholder，只记录 transport received，不制造 Venue Fact；
- Integration Scenario：显式标准化 Accepted、Fill 和 `OnlyPositionTrade`，代表未来 Gateway 输出；
- `OnlyEventRecorder` / `OnlyReportBuilder`：仅位于 Demo，读取公开 Event dispatch history 和 frozen Snapshot，不修改业务状态。

没有使用未标注 Fake，也没有绕过 Risk、Runtime Scope、Context 或 Manager 正式接口。

## 12. 仍存在的问题与限制

- Live/Paper/Research Runtime 尚未完成与 Backtest 相同的交易资源装配；
- 没有真实 Gateway、Broker SDK、AccountManager、撮合器或持久化 Repository；
- 多 Manager 内存写入尚无持久化事务日志、崩溃恢复或补偿编排；当前通过前置一致性校验、单线程和幂等保证确定性正常路径；
- Risk 部分成交仍保守保留整单活动预占，完整成交后才进入 CONSUMED；
- 第一阶段仍仅支持 Fixed Capital、单币种、NETTING Long-only、Average Cost、Linear PnL 和当前 T+1 规则能力；
- Integration Environment 当前验证单 Runtime/单 Cluster 的完整成交；多 Runtime/多 Cluster 隔离继续由历史专项测试覆盖。

这些限制没有被 Demo 隐藏，也没有被当成已实现的真实交易能力。

## 13. 架构成熟度评估

当前架构已从“组件分别可测”提升到“Backtest 内存模式完整同步纵切面可运行、可审计、可重放”。Pure Domain、Runtime
所有权、Context 权限、事实 Event、不可变 Snapshot、强类型金融值和 Reservation 分层均得到跨组件验证。

成熟度定位：**M1 架构整合完成，可进入下一阶段，但仍不是 Live-ready**。进入真实 Gateway、持久化或并发 Runtime 前，
必须新增相应 ADR，并优先解决 Runtime inbound serialization、事务日志/恢复和 Broker reconciliation 启动门禁。

## 14. 是否允许进入下一阶段

**允许。最终结论：ACCEPTED。**

该结论仅表示本任务定义的 Backtest Vertical Slice、历史回归、确定性重放和架构不变量全部满足；不表示可以启动真实交易。
