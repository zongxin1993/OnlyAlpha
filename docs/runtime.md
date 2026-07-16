# Runtime 设计

## 1. Runtime 类型

```text
OnlyRuntime
OnlyLiveRuntime
OnlyPaperRuntime
OnlyBacktestRuntime
OnlyResearchRuntime
```

## 2. 统一上下文

Cluster 通过受限 `OnlyRuntimeContext` 获取：

- Clock；
- 只读 MarketData View；
- 不可变回调 Snapshot；
- Logger；
- Timer；
- Instrument Registry；
- Account 只读 View；
- Cluster 命名空间化 Subscription/Timer Service。

Cluster 不接触具体 Gateway、撮合器、EventBus、可变 Cache、Aggregator 或 Runtime 内部 Service Container。
完整权限和生命周期见 `docs/runtime_context.md`。

## 3. 隔离要求

每个 Runtime 必须有独立：

- runtime_id；
- Clock；
- Event Stream；
- Account Context；
- Position Context；
- Order Namespace；
- Cache Namespace；
- Metrics；
- 日志上下文。

## 4. Live

实盘 Runtime 使用真实行情和真实交易 Gateway。

默认禁止在测试环境下启动真实交易。

## 5. Paper

实时行情 + 模拟成交。

用于策略验证和 Web 操作演示。

## 6. Backtest

正式成品式入口为 `OnlyRunConfig.load(path) → OnlyEngineRunService.run(config)`。通用 Assembler 仅从 Runtime Registry
取得 `OnlyRuntime`；Backtest Factory 再通过 DataSource、Broker 与 Strategy Registry 装配抽象组件。调用方只使用
`initialize/run/pause/resume/stop/close/snapshot` 父接口，Replay、Broker drain、最终不变量、Result 与资源关闭封装在
`OnlyBacktestRuntime.run()` 内。闭合 Bar 在 Broker 对账与 Cluster 回调前更新 Account/Strategy 估值；Calendar-derived
TradingDay 切换驱动本地 SettlementService。

历史数据驱动虚拟时钟。

必须可配置：

- 撮合模型；
- 手续费模型；
- 滑点模型；
- 延迟模型；
- 交易日历；
- 初始资金；
- Instrument 历史版本；
- 数据缺失策略。

## 7. Research

只做数据、因子、统计和绘图，不产生真实交易状态。

## 8. 同时运行

同一 Engine 可同时存在多个 Runtime，但任意事件必须明确归属 runtime_id。

## 9. Runtime 时间约束

所有 Runtime Clock 返回 UTC。`OnlyBacktestClock` 拒绝 naive 和非 UTC 时间，并只能
单调推进。Backtest/Paper/Live 必须通过同一 `OnlyTradingCalendar` 判断 Session、午休、
夜盘与 TradingDay；不得从 UTC date、本地自然 date 或 Runtime 自建规则推导。
Backtest 数据按历史 Calendar 与 Instrument 版本解析。当前已实现最小 Next-Bar Virtual Broker 撮合；完整历史数据驱动与
更复杂撮合仍必须遵守 `docs/time_model.md` 和 `docs/virtual_broker.md`。

每个 Runtime 独占并在关闭时关闭自己的 `OnlyClock`。Cluster Context 只接收只读
`OnlyClockView`；Timer 必须通过自动命名空间化的 `OnlyTimerService` 注册。只有 Backtest Runtime
的历史事件驱动器可持有 `OnlyBacktestClock` 控制接口。

## 10. MarketData 隔离

每个 Runtime 必须独占 EventBus、`OnlyMarketDataPipeline`、`OnlyMarketDataCache`、
`OnlyBarAggregationManager`、`OnlyIndicatorPipeline` 和 Dispatcher。一个 Runtime 内多个 Cluster
共享确定的派生 Bar/标准 Indicator；Live 与 Backtest 使用同一数据准备顺序。当前组件已实现这些独立
对象。`OnlyBacktestRuntime.process_bar` 是单记录版本化 Source/Request 的正式 Replay facade；实际顺序由
ReplayService 执行 Clock→MarketDataProcessor→Pipeline→Event facts→Dispatcher→ClusterManager。Live/Paper 真实 Adapter
资源装配仍在后续阶段。

## 11. 标准化成交编排

每个可交易 Runtime 独占 `OnlyExecutionProcessor`、Update Deduplicator、Sequence Tracker、Invariant Checker、Audit Store、
Reconciliation Queue 与事务事实 Publisher。Runtime `drain_broker_inbound()` 只做生命周期门禁和 FIFO 消费，所有
`OnlyBrokerInboundUpdate` 统一调用 `processor.process(update)`。`process_trade(update)` 只是仍强制 Queue 的便捷 ingress，
不存在 Fill/PositionTrade 双参数旁路。

Processor 同步执行 Order、Position、Allocation、Strategy Ledger、Account、Valuation、Reservation、Risk、不变量与事实提交。
配置 Virtual Broker 时，ExecutionService 只提交标准 Broker Request；Matching Engine 产生的 Update 必须先进入 Runtime
Inbound Queue。无 Broker 配置的 Runtime 仍使用明确 Placeholder。`settle_positions()` 只接受 Calendar 推导的 TradingDay。

## 12. Market Data Source 装配

Backtest Runtime 还独占 MarketData Source Registry、Reference Source、历史 Source、MarketData Queue、InMemory Gateway、
Processor、Deduplicator、SequenceTracker、GapDetector、AuditStore 和 ReplayService。实时 Queue 与 Broker Queue 物理分离。
历史链为 `Source → ReplayService → BacktestClock → Processor → Pipeline`；实时链为
`Gateway → Queue → Processor → Pipeline`。`process_bar()` 仅保留正式单记录 Replay facade。
