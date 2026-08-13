# Market Data Source

## 边界

市场数据平面与交易执行平面物理分离。`OnlyMarketDataGateway` 只负责实时连接、订阅和把标准 Update 写入 Runtime 的独立有界
Queue；它不属于 BrokerGateway，不持有 Pipeline、Cache、Cluster、Clock 或任何交易 Manager。实时与历史入口复用 Domain 的
`OnlyBar`、`OnlyQuoteTick`、`OnlyTradeTick`，来源元数据由 frozen `OnlyMarketDataInboundUpdate` 保存。

```text
Target SIM/LIVE: Gateway → MarketData Queue → Processor → Pipeline
BACKTEST: Local HistoricalDataSource → ReplayService → Clock → Processor → Pipeline
Trading execution: Cluster → Order/Risk → Broker Queue → ExecutionProcessor
```

SIM 已实现第一条 realtime/streaming 数据路径，并由 continuity/recovery 与 durable restart 测试冻结。
Research 使用 Historical Dataset 与纯计算边界，不经过 Trading Cluster、Broker Queue 或 ExecutionProcessor。

连接、订阅、Stream、历史查询、Instrument、Calendar 和 MarketRule 都是独立窄 Port。Envelope 保存 Runtime/Update/Source ID、
Source Sequence、Data Version、Instrument、DataType、强类型 payload、UTC `ts_event/ts_init`、Quality 和稳定 metadata。

`OnlyMarketDataProcessor` 是 Queue/Replay 之后唯一入口，依次执行 Scope/Source/Instrument/UTC/Lookahead 校验、去重、Sequence、
Session-aware Gap、Quality、Pipeline、Snapshot、Dispatcher、事实与 Audit。重复 Bar 不更新任何下游状态。Source sequence 跳号
与同 Session 缺口标记 `UNEXPECTED_GAP`；午休、隔夜等 Session 边界标记 `EXPECTED_SESSION_GAP`。

MarketData Queue 与 Broker Queue 分离，默认有界且不静默丢数据。Trading Runtime 独占 Registry、Queue、Processor、
Deduplicator、SequenceTracker、GapDetector、AuditStore、ReplayService 和 Gateway。Cluster 的 `ctx.market_data` 仍只返回
immutable Snapshot。Research Runtime 只拥有其 Dataset/Calculation state，不为结构对称创建 Broker Queue 或交易处理器。

第一版一个订阅选择一个主 Source，不自动融合或切换。尚未实现商业 Adapter、WebSocket、Level 2、分布式服务、Tick 落盘、自动
主备或复杂公司行动。
