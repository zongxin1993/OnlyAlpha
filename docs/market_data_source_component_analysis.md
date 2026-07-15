# Market Data Source 组件差距分析

## 1. 当前数据进入链路

审计时的生产链路为：

```text
测试/Demo 构造 OnlyBar
→ OnlyBacktestRuntime.process_bar()
→ Runtime 直接推进 OnlyBacktestClock
→ OnlyMarketDataPipeline.process_bar()
→ Cache / Aggregation / Indicator / immutable Snapshot
→ OnlyStrategyBarDispatcher
→ Cluster
```

Runtime 没有读取 CSV、Parquet 或 DataFrame，Pipeline 也不接收 DataFrame，Cluster 不访问数据源。但
`process_bar()` 同时承担数据入口、Clock 推进和 Pipeline 调用，因此历史数据可以绕过版本化数据源、ReplayService、统一校验、
去重、质量评估与审计。现有 Live/Paper 类型也没有独立的 MarketData inbound queue。

当前代码没有隐式在线 API 或系统时间读取；Backtest Clock 确定，但输入顺序由调用方决定。多 Instrument 的稳定全序、Source
优先级和同时间 DataType 顺序均未建模。

## 2. 当前数据模型

现有 Domain 类型继续作为实时与历史的统一载荷，不重复定义：

- `OnlyBar` 已包含 Instrument/BarType、OHLCV、`ts_event`、`ts_init`、TradingDay、Session、Adjustment 与关闭语义；
- `OnlyQuoteTick`、`OnlyTradeTick` 已包含 Instrument、Source、Sequence 和 UTC 双时间；
- `OnlyInstrument`、`OnlyTradingCalendar`、`OnlyMarketRule` 已版本化并具备强类型约束；
- 当前没有 `OnlyInstrumentStatus`，本任务只定义不可变状态 Update 载荷，不建立新的交易领域状态机。

Bar 没有 Source、Source Sequence、Data Version 或 Quality。这些是数据获取/处理元数据，不应污染 Pure Financial Domain，必须
由 `OnlyMarketDataInboundUpdate` envelope 保存。Snapshot 当前只有 Indicator 质量字符串，缺少输入数据质量的传播。

## 3. 当前回测数据处理

- 多 Instrument：没有数据源级归并；调用方顺序即处理顺序；
- 同时间排序：没有显式全序；
- Clock：`OnlyBacktestRuntime.process_bar()` 每 Bar 推进一次；
- Lookahead：Pipeline 拒绝 Clock 早于 Bar，但调用方可预先持有全部数据，系统没有统一 Replay 边界；
- 加载方式：没有历史 Source/Stream/Cursor；
- 重放：现有测试重放调用序列，但不记录数据版本、Source、Quality 或处理 Audit；
- Gap：聚合器能处理不完整窗口，但没有基于 TradingCalendar/Session 的数据源缺口检测。

## 4. 目标变更边界

本任务只增加市场数据获取与应用层边界，不修改 Bar/Tick/Instrument/Calendar/MarketRule 的领域语义：

```text
Live/Paper Gateway → 独立有界 MarketData Queue → MarketDataProcessor
Local Historical Source → HistoricalReplayService → BacktestClock → MarketDataProcessor
MarketDataProcessor → 现有 MarketDataPipeline → Dispatcher → Cluster
```

`OnlyBacktestRuntime.process_bar()` 仅保留为兼容的单 Bar 正式回放便利入口，内部必须创建版本化 Update 并经过 ReplayService；它不再
直接推进 Clock 或调用 Pipeline。MarketData Queue 与 Broker Queue 分离，DataSource/Gateway 不获得 Pipeline、Cache、Cluster
或 Clock。Parquet 使用显式 `pyarrow` 本地依赖并严格校验 schema；正式回测不实现任何远程隐式获取。
