# Market Data Source

## 边界

市场数据平面与交易执行平面物理分离。`OnlyMarketDataGateway` 只负责实时连接、订阅和把标准 Update 写入 Runtime 的独立有界
Queue；它不属于 BrokerGateway，不持有 Pipeline、Cache、Cluster、Clock 或任何交易 Manager。实时与历史入口复用 Domain 的
`OnlyBar`、`OnlyQuoteTick`、`OnlyTradeTick`，来源元数据由 frozen `OnlyMarketDataInboundUpdate` 保存。

```text
Decision Lane:  closed BAR → MarketData Queue → Processor → Bar Pipeline → Strategy
Reference Lane: TRADE → MarketData Queue → Processor → Realtime Market State → immutable Snapshot
Trading execution: Strategy Decision + immutable Snapshot → Order/Risk → Broker Queue → ExecutionProcessor
BACKTEST: Local HistoricalDataSource → ReplayService → Clock → Processor → Bar Pipeline
```

Strategy Revision 的正式市场输入仍是 closed Bar（第一生产阶段为 1 Minute Closed Bar）。Trade 不进入 Bar Pipeline、不触发
Strategy/Cluster dispatch，也不改变 Strategy fingerprint；它只在通过同一 Processor 的 scope、identity、sequence、gap 和 quality
检查后，以 `APPLIED` 状态推进 Runtime-wide、provider-neutral 的 realtime reference projection。Execution/Risk 在一次 planning
cycle 开始时只 capture 一份 immutable snapshot，后到 Trade 只影响后续 cycle。缺失、过期、错误 source/quality 或 unresolved gap
对新的 risk-increasing execution fail closed；risk-reducing/neutral safety path 不依赖该 reference。

Decision continuity 与 reference continuity 是不同的 Runtime consequence lane。Bar gap 继续进入既有 decision-lane historical
recovery；Trade gap 只把对应 realtime reference scope 标记为 unresolved，trusted Trade 停在 gap 前，Streaming Runtime 与 closed-Bar
Strategy lane 继续运行。Provider/DataSource 仍独占 provider-native reconnect、baseline 与 gap backfill；Core 不重建 provider Trade
sequence。Provider 随后给出的精确 canonical Trade suffix 必须经同一 `OnlyMarketDataProcessor` 验证，normal worker 与 Bar recovery
期间的 buffered/catch-up suffix 使用相同的 Trade pass-through admission，不能静默丢弃 Trade，也不能绕过 Processor 直接修 projection。

SIM 已实现第一条 realtime/streaming 数据路径，并由 continuity/recovery 与 durable restart 测试冻结。
Research 使用 Historical Dataset 与纯计算边界，不经过 Trading Cluster、Broker Queue 或 ExecutionProcessor。

连接、订阅、Stream、历史查询、Instrument、Calendar 和 MarketRule 都是独立窄 Port。Envelope 保存 Runtime/Update/Source ID、
Source Sequence、Data Version、Instrument、DataType、强类型 payload、UTC `ts_event/ts_init`、Quality 和稳定 metadata。

`OnlyMarketDataProcessor` 是 Queue/Replay 之后唯一入口，依次执行 Scope/Source/Instrument/UTC/Lookahead 校验、去重、Sequence、
Session-aware Gap、Quality、Pipeline、Snapshot、Dispatcher、事实与 Audit。重复 Bar 不更新任何下游状态。Source sequence 跳号
与同 Session 缺口标记 `UNEXPECTED_GAP`；午休、隔夜等 Session 边界标记 `EXPECTED_SESSION_GAP`。

Realtime projection 是可重建的 operational state，不是 Market Fact 或持久化 Authority。Runtime restart 后它从 EMPTY/NOT_READY
开始，不从 ClickHouse 的历史“latest Trade”恢复 READY。ClickHouse 仅负责 typed fact durability、历史查询、revision、replay 与 audit，
不作为 realtime Execution/Risk 的集成 API。

Provider observation 只有在 append-only WAL frame 完成 fsync 后才取得 durable acceptance。Recorder 在同 scope 内使用有界 rolling
segment，并在 record limit、scope change 或 clean shutdown 时 seal；provider callback 不同步等待 ClickHouse/PostgreSQL。Sealed
segment 进入 bounded normal-operation drain，复用 crash recovery coordinator 完成：

```text
WAL sealed segment → ClickHouse typed fact write → exact verification
                   → PostgreSQL coverage/revision/manifest commit → WAL GC eligibility
```

数据库不可用时 sealed WAL 仍是 durable backlog，drain health 显式 DEGRADED 并通过同一 idempotent recovery path 重试；不得静默
丢弃 Trade 或伪造数据库 commit。WAL 容量和内存 queue 均保持有界。

MarketData Queue 与 Broker Queue 分离，默认有界且不静默丢数据。Trading Runtime 独占 Registry、Queue、Processor、
Deduplicator、SequenceTracker、GapDetector、AuditStore、ReplayService 和 Gateway。Cluster 的 `ctx.market_data` 仍只返回
immutable Snapshot。Research Runtime 只拥有其 Dataset/Calculation state，不为结构对称创建 Broker Queue 或交易处理器。

一个订阅选择一个主 Source，不自动融合或切换。Runtime subscription requirement 由 Strategy BAR requirement 与显式
Execution/Risk TRADE reference requirement 组合成 union，但二者 Authority 和 identity 保持独立。尚未实现 Level 2、分布式服务、
自动主备或复杂公司行动。
