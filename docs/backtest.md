# Internal Backtest Engine Contract

> 本文描述 Kernel 内部 Backtest Engine/Runtime 组合，不是外部 Product client 使用指南。当前尚无 governed Backtest Product API；
> 下述 direct `OnlyEngine` 代码只作为 `LEGACY_K8_TARGET` 的内部工程事实保留，外部用户不得据此绕过 Product Control Plane。

内建 `scenario-exact` 通过 DataSource SPI 和正式 Historical Replay 提供 exact bars；Action Strategy 只经 `ctx.orders` 下单。

Deterministic Scenario 是 Backtest 外层消费者，不是 Backtest 专用 API。人工 Bar 仍须走 DataSource、Replay、Pipeline 和
Strategy dispatch；Action 仍经公共 `ctx.orders`。当前 Scenario Runner 尚未接通，禁止以 `process_bar()` 组件测试宣称完成。

## Internal Engine composition

```python
engine = OnlyEngine(OnlyEngineConfig(OnlyEngineId("onlyalpha"), Path("user_data")))
engine.add_cluster_from_file("../OnlyAlpha-plugins/clusters/my_cluster/config.yaml")
result = engine.run()
```

`OnlyClusterRunConfig` parses common fields and Cluster-owned Strategy/Factor import specs. Runtime-specific, Synthetic and Virtual Broker
parameters are parsed by their concrete factories；Indicator 参数由 Factor Config 解析。`OnlyEngine` is the sole internal execution boundary; Backtest `run()` owns
historical replay and final invariant evaluation, while `OnlyEngineResultExporter` writes through `OnlyUserDataLayout`.

## Fixed workflow

```text
HistoricalDataSource → HistoricalReplayService → BacktestClock → MarketDataProcessor
→ MarketDataPipeline → immutable Snapshot → Cluster Factory
→ Factor-created Indicator → Factor Snapshot/Score → Strategy → ctx.orders
→ Risk → Order → BrokerExecutionService → VirtualBroker → MatchingEngine
→ Broker queue → ExecutionProcessor → Position → Allocation → StrategyLedger → Account → Result
```

其中受支持的 Generic T0 Cash LIMIT BUY OPEN 与 LIMIT SELL CLOSE LONG NETTING 每个 whole/partial Fill，均细化为
`Pure Planner → Prepared Transaction → durable Transaction Store commit → ordered incremental Projection Targets →
Projection Ready → at-least-once Outbox`。Close 在同一批次分段消费 Position/Risk Reservation，不携带现金 Reservation，并
支持仓位部分保留或完全归零。Virtual Broker 对 BUY OPEN 与 SELL CLOSE 共用 Partial Fill Schedule；Long Close 的同 Bar/
跨 Bar Multi-Fill、Fill Plan checkpoint、完整 Recovery 以及部分成交后 durable Terminal Operation 已完成。Short、Hedging、
Futures/Margin 和多 Cluster 固定资金归约仍是明确的后续边界。

Backtest Runtime 在 `INITIALIZING → RECOVERING → RECOVERY_FINALIZING → READY` 中自动恢复最新完整 checkpoint，并以严格 Execution Recovery Session 在原 Broker Update 因果点逐笔处理 Ready 与未投影 transaction；每笔都重跑正式 Planner 并完整比较 Stored Prepared。最后一个 persisted entry 只把 Execution phase 推进为 `TAIL_RESOLVED`，独立 Backtest Recovery Session 仍保持当前 exact boundary open。该 Bar 后续 Strategy/Broker 产生的新 Trade 作为 continuation 走正式 Coordinator commit，Outbox 在 recovery 中不即时交付。只有 Processing Result、Audit、Result Progress 和 Event drain 完成且 `after_market_processing()` 确认完整 source/data-version/update/sequence identity 后 replay 才停止。随后只读 Validator 验证 Runtime authority，post-recovery checkpoint 经 capture/write/read-back 完整比较后 Cluster 才进入 `RECOVERED`；任一步失败都会阻止 READY、Outbox 投递和 resume。Collector/RunPlan 的统计前缀来自 checkpointable Result Progress，fingerprint 与 restart equality 使用唯一 canonical business projection。

外部事件由 Runtime Recovery Gate 单独控制而不停止上述同步业务重建：构造与 `add_cluster()` 的 fresh Direct facts 暂存到
OPEN；发现 checkpoint 时这些临时 bootstrap facts 被丢弃；replay/finalization 的 MarketData、Order、Risk 与 manager Direct
facts被抑制且不补发。Continuation transaction 的 durable Outbox 保持 pending，只有 finalization durable verification 成功、
Runtime READY 且 start 打开 Router 后才交付，随后才 resume Cluster 并发布 `RUNTIME_STARTED`。
Committed-but-not-ready transaction 只进入恢复/管理 diagnostic，即使失败运行构建部分 Result，也不会成为正式 execution fact。

持久恢复必须显式启用：

```yaml
runtime:
  persistence:
    backend: SQLITE
    checkpoint:
      enabled: true
      retain_last: 2
    # path: nested/runtime.sqlite3  # 可选，相对 Runtime state root
```

未配置时为 `MEMORY`，不会创建 state 目录。SQLite 默认路径为
`user_data/state/engines/<engine-id>/runtimes/<runtime-id>/runtime.sqlite3`。绝对路径、空路径和 `..` 逃逸被拒绝；Store
identity、Participant Registry、schema 或 checkpoint hash 不匹配不会覆盖旧库或 fallback。SQLite Runtime Persistence 使用
schema version 3，明确拒绝旧 version 1/2 且不迁移；Virtual Broker participant checkpoint schema 仍为 2。初始稳定边界和
每个完整 Bar 都写 checkpoint；写入失败阻止后续 Bar。

Only ReplayService advances the data-driven Clock. The product loop never reads DataFrames or online APIs and never calls
Pipeline, Cluster or Managers directly. Runtime marks Account and Strategy values from closed Bars before Broker
reconciliation and strategy dispatch. Calendar TradingDay changes invoke SettlementService; strategies only see the resulting
available Allocation.

## Result

`OnlyBacktestResult` implements the common `OnlyRuntimeResult` view. Schema v3 separates Account-authoritative
`runtime_performance` from every Ledger-authoritative `cluster_performance`. It also contains the full Account and Cluster
equity timelines, one `final_account`, final Position/Allocation/Ledger snapshots, committed facts, structured diagnostics,
final Runtime/Ledger reconciliation and stable fingerprints. The ambiguous `performance` and `final_accounts` fields were
deleted without aliases. Engine 在 Runtime 完成后依次调用纯 Analytics、原子 Artifact Writer 与 Report；Runtime 和 Result 不写文件。

## Current limits

First-phase Backtest 支持一个共享 Account、一个 Base Currency 和多个显式 `FIXED_CAPITAL` Cluster。单 Cluster 可省略
capital，此时等于 Account initial cash；多 Cluster 必须逐个声明，且精确加总为 Account initial cash。当前不支持
SHARED_POOL、动态再分配、多 Account、FX、System Ledger 或 TWR/MWR。中途逐点对账仍是后续工作；当前正式结果执行最终
Account/Ledger 对账并在不一致时失败。

`determinism_fingerprint` hashes stable product authority, normalized Result Facts, performance, reconciliation and equity
timelines. Replay-process counters, EventBus delivery order, Factor/Indicator diagnostics and restart diagnostics are operational
metadata and are not part of that fingerprint. `result_fingerprint` likewise excludes only execution-recovery diagnostics, while
retaining failures, warnings and all economic result fields; this makes an interrupted/recovered run comparable with its
uninterrupted product baseline without hiding business differences.
