# OnlyAlpha 市场数据源、历史数据源与确定性回放组件实现任务

## 1. 任务目标

现在开始实现 OnlyAlpha 的市场数据源相关组件。

本任务需要建立一套独立于券商交易接口的数据入口体系，使 OnlyAlpha 可以分别接入：

* 实时市场数据服务；
* 本地历史数据；
* 在线历史数据服务；
* Instrument 和交易规则参考数据；
* 回测历史数据回放；
* Paper 和 Live Runtime 的实时数据推送。

必须明确：

```text
市场数据源
    ≠
券商交易接口
```

实际系统允许使用不同供应商：

```text
实时行情
    来自行情供应商 A

历史数据
    来自本地 Parquet 或数据供应商 B

Instrument / TradingCalendar
    来自 Reference Data 服务 C

交易下单
    通过券商 D
```

Runtime、Cluster、MarketData Pipeline 和策略不得假设行情与交易来自同一公司。

本阶段需要建立：

```text
OnlyMarketDataGateway
OnlyHistoricalDataSource
OnlyReferenceDataSource
OnlyMarketDataProcessor
OnlyHistoricalReplayService
```

并将其接入当前完整 Vertical Slice。

---

# 2. 项目身份

OnlyAlpha 是一个完全独立、从零设计的量化交易系统。

本任务只依据：

```text
AGENTS.md
docs/
docs/adr/
当前 OnlyAlpha 代码
当前已批准的架构设计
```

禁止：

* 参考其他本地工程；
* 复制历史实现；
* 为兼容旧工程增加接口；
* 保留未记录的历史语义；
* 创建迁移专用 Wrapper。

---

# 3. 核心架构原则

必须遵守：

```text
市场数据平面与交易执行平面完全分离

MarketDataGateway 不属于 BrokerGateway

实时数据和历史数据使用统一 Domain 类型

实时订阅和历史查询使用不同 Port

MarketDataGateway 不直接调用 Cluster

HistoricalDataSource 不直接推进策略

所有数据必须先标准化

标准化数据必须进入 MarketDataProcessor

MarketDataProcessor 再调用 MarketDataPipeline

Backtest 时间由 HistoricalReplayService 推进

Paper 和 Live 数据通过 Runtime MarketData Inbound Queue

所有内部绝对时间统一 UTC

TradingDay 由 TradingCalendar 推导

所有数据保留 Source、Sequence、Version 和 Quality

正式回测默认使用版本化、可重放的数据快照

在线历史数据不得成为正式确定性回测的隐式依赖

相同数据输入必须产生确定性结果

每个新增组件必须完成全部历史组件连通验证
```

---

# 4. 总体架构

目标结构：

```text
市场数据平面
├── OnlyMarketDataGateway
│   ├── Connection Port
│   ├── Subscription Port
│   └── Stream Port
│
├── OnlyHistoricalDataSource
│   ├── OnlyInMemoryHistoricalDataSource
│   ├── OnlyParquetHistoricalDataSource
│   ├── OnlyCsvHistoricalDataSource
│   └── Future Remote Data Sources
│
├── OnlyReferenceDataSource
│   ├── Instrument Source
│   ├── TradingCalendar Source
│   └── MarketRule Source
│
├── OnlyMarketDataInboundQueue
├── OnlyMarketDataProcessor
└── OnlyHistoricalReplayService
```

数据进入 Runtime 后：

```text
实时行情 Gateway
→ 标准化 MarketData Update
→ Runtime MarketData Inbound Queue
→ OnlyMarketDataProcessor
→ OnlyMarketDataPipeline
→ Cache / Aggregation / Indicator
→ Snapshot
→ Cluster
```

回测链路：

```text
OnlyHistoricalDataSource
→ OnlyHistoricalReplayService
→ Backtest Clock
→ OnlyMarketDataProcessor
→ OnlyMarketDataPipeline
→ Snapshot
→ Cluster
```

交易执行链保持独立：

```text
Cluster
→ Order
→ Risk
→ BrokerGateway
→ ExecutionProcessor
```

---

# 5. 本阶段实现范围

本阶段需要实现或完善：

```text
OnlyMarketDataSourceId
OnlyMarketDataGatewayId
OnlyDataVersion
OnlyDataSequence

OnlyMarketDataCapability
OnlyMarketDataCapabilities

OnlyMarketDataConnectionPort
OnlyMarketDataSubscriptionPort
OnlyMarketDataStreamPort
OnlyMarketDataGateway

OnlyHistoricalDataSource
OnlyHistoricalBarSource
OnlyHistoricalQuoteSource
OnlyHistoricalTradeSource

OnlyReferenceDataSource
OnlyInstrumentDataSource
OnlyTradingCalendarDataSource
OnlyMarketRuleDataSource

OnlyHistoricalBarRequest
OnlyHistoricalQuoteRequest
OnlyHistoricalTradeRequest
OnlyHistoricalDataRange
OnlyHistoricalDataQueryResult
OnlyHistoricalDataStream

OnlyMarketDataSubscriptionRequest
OnlyMarketDataUnsubscriptionRequest
OnlyMarketDataSubscriptionResult

OnlyMarketDataInboundUpdate
OnlyBarUpdate
OnlyQuoteTickUpdate
OnlyTradeTickUpdate
OnlyInstrumentStatusUpdate

OnlyMarketDataQuality
OnlyMarketDataQualityFlag
OnlyMarketDataValidationResult

OnlyMarketDataProcessor
OnlyMarketDataProcessingResult
OnlyMarketDataProcessingStatus
OnlyMarketDataDeduplicator
OnlyMarketDataSequenceTracker
OnlyMarketDataGapDetector

OnlyHistoricalReplayService
OnlyHistoricalReplayConfig
OnlyHistoricalReplayCursor
OnlyHistoricalReplayResult
OnlyHistoricalReplayEvent
OnlyHistoricalMergePolicy

OnlyInMemoryHistoricalDataSource
OnlyParquetHistoricalDataSource
OnlyCsvHistoricalDataSource

OnlyInMemoryMarketDataGateway
OnlyReplayMarketDataGateway

OnlyMarketDataSourceRegistry
OnlyMarketDataSourceFactory

OnlyMarketDataEventPublisher
OnlyMarketDataAuditRecord
OnlyMarketDataAuditStore
```

如果当前工程已有部分同名或同语义类型，优先复用和完善，不得重复定义。

---

# 6. 本阶段不实现

本任务不要实现：

```text
商业行情供应商 Adapter
真实 WebSocket 行情源
交易所专线
完整 Level 2 Order Book
公司行动完整处理
复权引擎
复杂多源融合
自动主备切换
分布式 MarketData Service
大规模数据库服务
Tick 数据压缩引擎
实时数据落盘集群
Web
ARL
```

可以定义扩展 Port，但不得伪装已经完整支持。

---

# 7. 执行前必须阅读

开始实现前必须阅读：

```text
AGENTS.md

docs/architecture.md
docs/architecture_principles.md
docs/integration_vertical_slice.md

docs/domain_model.md
docs/instrument_model.md
docs/time_model.md
docs/clock.md
docs/event.md

docs/runtime.md
docs/runtime_context.md
docs/cluster.md

docs/market_data_pipeline.md
docs/order.md
docs/risk.md
docs/position.md
docs/strategy_ledger.md
docs/account.md
docs/broker_gateway.md
docs/virtual_broker.md
docs/execution_processor.md

docs/testing.md
docs/coding_style.md
docs/adr/
```

重点检查已有：

```text
OnlyBar
OnlyBarType
OnlyQuoteTick
OnlyTradeTick
OnlyInstrument
OnlyTradingCalendar
OnlyMarketRule

OnlyClock
OnlyBacktestClock
OnlyRuntimeInboundQueue

OnlyMarketDataPipeline
OnlyMarketDataSnapshot
OnlyBarAggregationManager
OnlyIndicatorPipeline
OnlyMarketDataCache

OnlyCluster
OnlyRuntime
```

禁止重复建立另一套 Bar、Tick、Instrument 或时间模型。

---

# 8. 先创建差距分析

创建：

```text
docs/market_data_source_component_analysis.md
```

至少包含：

## 8.1 当前数据进入链路

画出当前实现：

```text
文件 / DataFrame / 测试数据
→ ?
→ MarketData Pipeline
→ Snapshot
→ Cluster
```

检查：

* Runtime 是否直接读取 CSV；
* Backtest 是否自行排序数据；
* Pipeline 是否接收 DataFrame；
* 策略是否直接访问数据源；
* 实时数据是否直接调用 Cluster；
* 是否缺少 Source ID；
* 是否缺少 Sequence；
* 是否缺少 Quality；
* 是否缺少数据版本；
* 是否使用系统时间；
* 是否历史和实时使用不同 Domain 类型；
* 是否回测中直接请求在线 API；
* 是否存在非确定性排序。

## 8.2 当前数据模型

检查：

```text
Bar
Quote Tick
Trade Tick
Instrument Status
Trading Calendar
Market Rule
```

是否已经完整包含：

```text
instrument_id
bar_type
source_id
source_sequence
ts_event
ts_init
data_version
quality_flags
```

如果 Domain 实体不应直接带 Source 元数据，则定义标准化 Update Envelope，不要污染核心价格实体。

## 8.3 当前回测数据处理

检查：

* 多 Instrument 如何归并；
* 相同时间的数据如何排序；
* Clock 由谁推进；
* 是否使用未来数据；
* 是否一次性加载全部数据；
* 是否支持流式读取；
* 是否可重放；
* 是否记录数据版本。

完成分析后再修改代码。

---

# 9. 数据 Domain 与 Update Envelope

实时和历史数据必须输出统一 Domain：

```text
OnlyBar
OnlyQuoteTick
OnlyTradeTick
OnlyInstrumentStatus
```

但数据来源元信息建议放入：

```text
OnlyMarketDataInboundUpdate
```

建议字段：

```text
update_id
source_id
source_sequence
data_version

instrument_id
data_type
payload

ts_event
ts_init

quality_flags
correlation_id
metadata
```

`payload` 必须是明确的联合类型，不得使用任意 dict。

例如：

```text
OnlyBarUpdate
OnlyQuoteTickUpdate
OnlyTradeTickUpdate
OnlyInstrumentStatusUpdate
```

---

# 10. 数据时间语义

必须区分：

```text
ts_event
    市场事件发生时间

ts_init
    OnlyAlpha 接收或初始化时间

source_sequence
    数据源顺序

processing_sequence
    Runtime 内处理顺序
```

所有绝对时间为 UTC。

禁止：

```python
datetime.now()
datetime.utcnow()
time.time()
```

历史数据中 `ts_init` 可以由 Replay Clock 或加载过程确定，但必须稳定。

不能用文件读取时的系统当前时间作为确定性回放字段。

---

# 11. MarketData Capability

定义：

```text
OnlyMarketDataCapability
```

至少支持：

```text
CONNECT
AUTHENTICATE
SUBSCRIBE_BAR
SUBSCRIBE_QUOTE
SUBSCRIBE_TRADE
UNSUBSCRIBE
PUSH_BAR
PUSH_QUOTE
PUSH_TRADE
QUERY_HISTORICAL_BAR
QUERY_HISTORICAL_QUOTE
QUERY_HISTORICAL_TRADE
QUERY_INSTRUMENT
QUERY_CALENDAR
QUERY_MARKET_RULE
```

每个数据源明确声明能力。

不支持时返回：

```text
UNSUPPORTED_CAPABILITY
```

不要抛出普通 `NotImplementedError` 后继续运行。

---

# 12. 实时连接 Port

定义：

```python
class OnlyMarketDataConnectionPort(Protocol):
    def connect(self) -> OnlyMarketDataConnectionResult:
        ...

    def authenticate(self) -> OnlyMarketDataAuthenticationResult:
        ...

    def disconnect(self) -> OnlyMarketDataDisconnectResult:
        ...

    def connection_snapshot(self) -> OnlyMarketDataConnectionSnapshot:
        ...
```

连接状态至少：

```text
DISCONNECTED
CONNECTING
CONNECTED
AUTHENTICATING
READY
RECONNECTING
FAILED
```

MarketDataGateway 不得与 BrokerGateway 共用连接对象。

---

# 13. 实时订阅 Port

定义：

```python
class OnlyMarketDataSubscriptionPort(Protocol):
    def subscribe(
        self,
        request: OnlyMarketDataSubscriptionRequest,
    ) -> OnlyMarketDataSubscriptionResult:
        ...

    def unsubscribe(
        self,
        request: OnlyMarketDataUnsubscriptionRequest,
    ) -> OnlyMarketDataSubscriptionResult:
        ...
```

订阅请求至少包含：

```text
request_id
source_id
instrument_ids
data_types
bar_types
depth
start_mode
metadata
```

订阅结果只表示：

```text
请求是否被数据源接收
```

不表示已经收到第一条有效行情。

异步订阅状态变化可以使用标准化 Update 或状态 Event。

---

# 14. MarketData Stream Port

数据源通过受限 Sink 或 Queue 发送标准化 Update。

推荐：

```python
class OnlyMarketDataUpdateSink(Protocol):
    def submit(
        self,
        update: OnlyMarketDataInboundUpdate,
    ) -> None:
        ...
```

或：

```text
OnlyMarketDataInboundQueue
```

Gateway 不得：

* 直接调用 MarketDataPipeline；
* 直接调用 Cluster；
* 直接修改 Cache；
* 直接调用 Indicator。

正确：

```text
Gateway
→ MarketData Inbound Queue
→ Runtime Thread
→ MarketDataProcessor
```

---

# 15. HistoricalDataSource 接口

定义统一历史数据源：

```python
class OnlyHistoricalDataSource(Protocol):
    @property
    def source_id(self) -> OnlyMarketDataSourceId:
        ...

    @property
    def capabilities(self) -> OnlyMarketDataCapabilities:
        ...

    def load_bars(
        self,
        request: OnlyHistoricalBarRequest,
    ) -> OnlyHistoricalDataStream[OnlyBarUpdate]:
        ...

    def load_quotes(
        self,
        request: OnlyHistoricalQuoteRequest,
    ) -> OnlyHistoricalDataStream[OnlyQuoteTickUpdate]:
        ...

    def load_trades(
        self,
        request: OnlyHistoricalTradeRequest,
    ) -> OnlyHistoricalDataStream[OnlyTradeTickUpdate]:
        ...
```

不要将核心接口固定为返回 DataFrame。

可以提供：

```text
OnlyPandasHistoricalDataAdapter
```

但底层应支持 Iterator / Stream / Cursor。

---

# 16. 历史查询请求

`OnlyHistoricalBarRequest` 至少包含：

```text
request_id
instrument_ids
bar_types

start_time
end_time

data_version
adjustment_mode
timezone_policy
sort_policy
quality_policy

batch_size
metadata
```

要求：

* start/end 为 UTC；
* 时间范围语义明确；
* 左闭右开或左右闭合必须统一；
* adjustment_mode 明确；
* 数据版本可指定；
* 不允许隐式使用“最新数据”而不记录版本。

---

# 17. Adjustment Mode

定义：

```text
OnlyPriceAdjustmentMode
├── RAW
├── FORWARD_ADJUSTED
├── BACKWARD_ADJUSTED
└── PROVIDER_DEFINED
```

第一版完整支持：

```text
RAW
```

其他模式可以定义，但未实现时必须返回明确 unsupported。

不得把复权数据当作原始数据而不标记。

---

# 18. ReferenceDataSource

定义：

```text
OnlyReferenceDataSource
OnlyInstrumentDataSource
OnlyTradingCalendarDataSource
OnlyMarketRuleDataSource
```

职责分别是：

```text
Instrument
    资产静态定义

TradingCalendar
    交易日、节假日、Session

MarketRule
    Tick、Lot、价格限制、结算规则引用
```

Reference Data 不应混入 Tick 或 Bar 接口。

第一版可实现：

```text
OnlyInMemoryReferenceDataSource
OnlyFileReferenceDataSource
```

如果当前工程已有 Instrument Registry，可以定义 Adapter，不要重复建立另一套 Registry。

---

# 19. Corporate Action 扩展边界

定义未来接口：

```text
OnlyCorporateActionDataSource
```

但本阶段只记录扩展点。

如果读取复权数据，必须能够标记其 Corporate Action 版本。

不得本阶段实现复杂公司行动业务。

---

# 20. MarketDataProcessor

定义：

```text
OnlyMarketDataProcessor
```

它是标准化行情 Update 进入 MarketData Pipeline 的统一入口。

建议接口：

```python
class OnlyMarketDataProcessor:
    def process(
        self,
        update: OnlyMarketDataInboundUpdate,
    ) -> OnlyMarketDataProcessingResult:
        ...
```

职责：

* Scope 校验；
* Source 校验；
* Domain 校验；
* 时间校验；
* 去重；
* Sequence 检查；
* Gap 检测；
* Quality 评估；
* 调用 MarketDataPipeline；
* 汇总处理结果；
* 发布事实事件；
* 记录 Audit。

不负责：

* 连接数据源；
* 读取文件；
* 策略回调编排之外的业务；
* 下单；
* 撮合。

---

# 21. MarketData Processing Status

定义：

```text
OnlyMarketDataProcessingStatus
├── APPLIED
├── DUPLICATE
├── STALE
├── GAP_DETECTED
├── REJECTED
├── IGNORED
└── FAILED
```

禁止只返回 bool。

结果至少包含：

```text
update_id
source_id
instrument_id
data_type
status
pipeline_result
snapshot
quality
events
failure
sequence
```

---

# 22. 数据校验

Processor 至少验证：

```text
Instrument 存在
BarType 合法
价格合法
数量合法
OHLC 不变量
时间为 UTC
时间顺序合法
Source 已注册
Sequence 合法
Data Version 合法
Quality Policy 允许
```

Bar 不变量至少：

```text
high >= open
high >= close
low <= open
low <= close
high >= low
volume >= 0
```

不得让无效数据进入 Cache。

---

# 23. 数据去重

定义：

```text
OnlyMarketDataDeduplicator
```

去重 Key 根据数据类型：

```text
Bar:
source_id + instrument_id + bar_type + ts_event + data_version

Quote:
source_id + instrument_id + source_sequence

Trade:
source_id + instrument_id + trade_id/source_sequence
```

重复数据：

* 不更新 Cache；
* 不重复聚合；
* 不重复计算 Indicator；
* 不重复调用 Cluster；
* 不增加 Snapshot Version；
* 返回 `DUPLICATE`。

---

# 24. Sequence Tracker

定义：

```text
OnlyMarketDataSequenceTracker
```

Scope 至少考虑：

```text
source_id
instrument_id
data_type
bar_type
```

如果 Source 提供 sequence，优先使用。

如果没有 sequence：

```text
ts_event
→ stable update_id
```

必须明确其质量较低。

---

# 25. Gap Detector

定义：

```text
OnlyMarketDataGapDetector
```

检测：

* Bar 周期缺失；
* Source Sequence 跳号；
* 时间跳跃；
* 数据断层；
* Session 内缺失；
* Session 边界合法间隔。

Gap 不一定总是错误。

例如午间休市不能算缺失。

必须依赖：

```text
OnlyTradingCalendar
OnlyTradingSession
```

结果质量标记：

```text
GAP_DETECTED
EXPECTED_SESSION_GAP
UNEXPECTED_GAP
```

---

# 26. 数据质量

定义：

```text
OnlyMarketDataQualityFlag
```

至少：

```text
VALID
DELAYED
STALE
DUPLICATE
OUT_OF_ORDER
GAP_DETECTED
EXPECTED_SESSION_GAP
ADJUSTED
UNADJUSTED
PARTIAL
SOURCE_CONFLICT
UNKNOWN_SEQUENCE
NON_DETERMINISTIC_SOURCE
```

质量是数据的一等属性。

策略 Snapshot 应能读取必要质量信息。

但策略不能修改质量状态。

---

# 27. HistoricalReplayService

定义：

```text
OnlyHistoricalReplayService
```

职责：

* 打开一个或多个历史流；
* 多 Instrument 归并；
* 多 DataType 归并；
* 稳定排序；
* 推进 Backtest Clock；
* 将标准 Update 送入 MarketDataProcessor；
* 控制 Replay 生命周期；
* 输出 Replay Report；
* 支持暂停、继续和停止；
* 支持确定性重放。

建议接口：

```python
class OnlyHistoricalReplayService:
    def prepare(
        self,
        config: OnlyHistoricalReplayConfig,
    ) -> OnlyHistoricalReplayCursor:
        ...

    def run(
        self,
        cursor: OnlyHistoricalReplayCursor,
    ) -> OnlyHistoricalReplayResult:
        ...

    def step(
        self,
        cursor: OnlyHistoricalReplayCursor,
    ) -> OnlyHistoricalReplayEvent | None:
        ...
```

---

# 28. Replay 排序规则

必须定义稳定全序。

推荐：

```text
1. ts_event
2. data_type_priority
3. instrument_id
4. bar_type
5. source_priority
6. source_sequence
7. stable update_id
```

`data_type_priority` 必须配置或文档化。

例如同一时刻：

```text
Instrument Status
→ Quote
→ Trade
→ Bar Close
```

具体顺序必须根据当前系统语义确定。

禁止依赖：

* dict 顺序；
* 文件枚举顺序；
* 数据源返回顺序；
* 线程到达顺序。

---

# 29. Replay 与 Clock

每条 Replay Event：

```text
读取下一条最小 ts_event
→ BacktestClock.advance_to(ts_event)
→ MarketDataProcessor.process(update)
```

禁止 Processor 自行推进 Clock。

禁止数据源直接推进 Clock。

禁止 Backtest Runtime 自己在多个地方推进 Clock。

Clock 回退必须拒绝。

---

# 30. 同一时间多事件

同一个 `ts_event` 可能有多个 Instrument 和数据类型。

Replay Service 必须：

* 按稳定全序处理；
* 明确是否同一逻辑批次；
* 完成所有应先处理的数据；
* 再产生对应 Snapshot / Cluster Callback。

如果当前 MarketData Pipeline 已有逻辑时间片概念，必须复用。

不得因为文件顺序造成策略结果变化。

---

# 31. Lookahead 防护

HistoricalReplayService 必须避免未来数据泄露。

规则：

* 只处理当前 Clock 时间及之前数据；
* Pipeline 不可查询未来 Bar；
* Next-Bar Matching 只能使用提交后的下一根 Bar；
* 指标只能使用已关闭数据；
* 在线预下载数据也不能绕过 Replay 顺序；
* DataFrame Adapter 不得把完整未来 DataFrame 暴露给 Cluster。

必须新增 Lookahead 测试。

---

# 32. InMemory Historical Source

实现：

```text
OnlyInMemoryHistoricalDataSource
```

用途：

* 单元测试；
* Integration Scenario；
* 最小 Demo；
* 确定性 Replay。

必须支持：

* Bar；
* 最小 Quote/Trade；
* 多 Instrument；
* 数据版本；
* 稳定顺序；
* 分批读取。

---

# 33. Parquet Historical Source

实现：

```text
OnlyParquetHistoricalDataSource
```

要求：

* 支持分区目录；
* 支持时间范围过滤；
* 支持 Instrument 过滤；
* 支持 BarType 过滤；
* 流式或批量读取；
* 保持 Decimal 或可无损转换；
* 校验 schema；
* 保留 source/data version；
* 不一次性无条件加载整个数据集；
* 不依赖 LibreOffice 或文档工具。

建议分区：

```text
data_type=bar/
venue=XSHG/
instrument=510300/
bar_type=1m/
trading_day=YYYY-MM-DD/
```

具体结构可根据现有工程调整。

---

# 34. CSV Historical Source

实现：

```text
OnlyCsvHistoricalDataSource
```

定位：

* 导入；
* 测试；
* 小规模数据；
* 兼容外部文件。

CSV 不应成为大型正式回测的默认高性能格式。

要求：

* 明确 schema；
* 明确 timezone；
* 明确 decimal 解析；
* 明确列映射；
* 严格错误报告；
* 不猜测缺失字段。

---

# 35. 在线 Historical Source 边界

本阶段只定义：

```text
OnlyRemoteHistoricalDataSource
```

不实现具体供应商。

必须在文档中规定：

```text
正式确定性回测
    默认不直接依赖在线请求

在线数据
    先下载、标准化、校验、版本化、落盘
    再由本地 HistoricalDataSource 回放
```

允许探索模式在线读取，但必须标记：

```text
NON_DETERMINISTIC_SOURCE
```

Replay 报告必须显示该标记。

---

# 36. Source Registry

定义：

```text
OnlyMarketDataSourceRegistry
```

负责：

* Source 注册；
* Capability 查询；
* Source ID 唯一性；
* 优先级；
* Runtime Scope；
* 配置解析；
* Factory 创建。

不得成为通用 Service Locator。

只管理市场数据源相关对象。

---

# 37. Source Priority

预留：

```text
OnlyMarketDataSourcePriority
```

第一版规则：

* 一个订阅只选择一个主 Source；
* 不自动混合不同 Source 的同类数据；
* Source 切换必须有明确事件；
* Source ID 必须保留到 Audit。

复杂主备切换留到后续。

---

# 38. Reference Data Authority

Instrument 和 MarketRule 可能来自不同来源。

必须明确 Authority：

```text
Instrument Registry
    当前 Runtime 的规范化 Instrument 真值

Reference Data Source
    提供候选或更新数据

Reference Data Reconciliation
    校验后才进入 Registry
```

不得让 ReferenceDataSource 返回值直接静默覆盖正在交易的 Instrument 定义。

第一版可以只实现加载时校验。

---

# 39. 实时 MarketData Queue

定义或完善：

```text
OnlyMarketDataInboundQueue
```

与：

```text
OnlyBrokerInboundQueue
```

分开。

原因：

* 行情高频；
* Broker 回报不能被行情淹没；
* 背压策略不同；
* 错误处理不同；
* 优先级不同。

Runtime 应明确调度策略，但本任务不实现复杂多线程调度。

第一版保持单线程可确定执行。

---

# 40. Backpressure

预留：

```text
OnlyMarketDataBackpressurePolicy
```

至少：

```text
BLOCK
REJECT_NEW
DROP_OLDEST
DROP_LATEST
COALESCE
FAIL_RUNTIME
```

第一版建议：

```text
Backtest:
    BLOCK / 不丢数据

Paper/Live:
    默认有界队列，关键数据不静默丢失
```

具体高频 Tick 策略可后续实现。

任何丢弃必须产生质量或系统事件。

---

# 41. Event

定义事实事件：

```text
OnlyMarketDataSourceConnectedEvent
OnlyMarketDataSourceDisconnectedEvent
OnlyMarketDataSubscribedEvent
OnlyMarketDataUnsubscribedEvent

OnlyMarketDataReceivedEvent
OnlyMarketDataAppliedEvent
OnlyMarketDataDuplicateEvent
OnlyMarketDataStaleEvent
OnlyMarketDataGapDetectedEvent
OnlyMarketDataRejectedEvent

OnlyHistoricalReplayStartedEvent
OnlyHistoricalReplayPausedEvent
OnlyHistoricalReplayCompletedEvent
OnlyHistoricalReplayFailedEvent
```

Event 在处理结果形成后发布。

EventBus 不负责处理数据状态。

---

# 42. Audit

定义：

```text
OnlyMarketDataAuditRecord
```

至少包含：

```text
audit_id
runtime_id
source_id
update_id
instrument_id
data_type
status

source_sequence
processing_sequence
data_version
quality_flags

ts_event
ts_init
ts_processed

validation_result
pipeline_result
failure
```

历史 Replay 报告必须能统计：

* 总记录；
* 应用；
* 重复；
* 过期；
* 缺失；
* 拒绝；
* 错误。

---

# 43. ctx.market_data 边界

策略继续通过：

```python
ctx.market_data
```

读取 MarketData Snapshot。

策略不得访问：

```text
MarketDataGateway
HistoricalDataSource
ReplayService
MarketDataProcessor
MarketDataInboundQueue
Source Registry
```

策略不应知道数据来自：

* Parquet；
* CSV；
* 在线 API；
* 实时行情源。

---

# 44. Runtime 装配

Backtest Runtime：

```text
OnlyHistoricalDataSource
→ OnlyHistoricalReplayService
→ OnlyBacktestClock
→ OnlyMarketDataProcessor
→ OnlyMarketDataPipeline
```

Paper Runtime：

```text
OnlyMarketDataGateway
→ OnlyMarketDataInboundQueue
→ OnlyMarketDataProcessor
→ OnlyMarketDataPipeline
```

Live Runtime 同 Paper Runtime 数据链路，但使用真实 Gateway。

不要复制三套 MarketData Pipeline。

---

# 45. 推荐目录

根据现有工程调整，建议：

```text
src/onlyalpha/data/
├── __init__.py
├── identifiers.py
├── enums.py
├── capabilities.py
├── versions.py
├── quality.py
├── requests.py
├── results.py
├── updates.py
├── streams.py
├── registry.py
├── factory.py
├── audit.py
├── events.py
├── publisher.py
└── exceptions.py

src/onlyalpha/data/ports/
├── connection.py
├── subscription.py
├── stream.py
├── historical.py
├── reference.py
└── corporate_action.py

src/onlyalpha/data/processor/
├── processor.py
├── validation.py
├── deduplication.py
├── sequence.py
├── gaps.py
└── results.py

src/onlyalpha/data/replay/
├── service.py
├── config.py
├── cursor.py
├── merge.py
├── ordering.py
└── results.py

src/onlyalpha/data/sources/
├── memory.py
├── parquet.py
├── csv.py
├── replay_gateway.py
└── reference_memory.py
```

不要将 DataSource 放入 Broker 模块。

---

# 46. 单元测试

建议新增：

```text
tests/data/
├── test_market_data_capabilities.py
├── test_market_data_update.py
├── test_market_data_quality.py

├── test_historical_bar_request.py
├── test_historical_time_range.py
├── test_historical_stream.py

├── test_market_data_processor_validation.py
├── test_market_data_processor_duplicate.py
├── test_market_data_processor_stale.py
├── test_market_data_processor_gap.py
├── test_market_data_processor_sequence.py
├── test_market_data_processor_scope.py

├── test_replay_single_instrument.py
├── test_replay_multi_instrument.py
├── test_replay_multi_bar_type.py
├── test_replay_stable_order.py
├── test_replay_clock_advance.py
├── test_replay_same_timestamp.py
├── test_replay_no_lookahead.py
├── test_replay_pause_resume.py
├── test_replay_determinism.py

├── test_in_memory_historical_source.py
├── test_parquet_historical_source.py
├── test_parquet_schema_validation.py
├── test_parquet_range_filter.py
├── test_csv_historical_source.py
├── test_csv_timezone_validation.py
├── test_reference_data_source.py

├── test_market_data_source_registry.py
├── test_unsupported_capability.py
├── test_market_data_serialization.py
└── test_market_data_runtime_isolation.py
```

---

# 47. 完整连通测试强制要求

本任务必须严格遵守：

```text
AGENTS.md
docs/integration_vertical_slice.md
scripts/run_component_validation.sh
```

不能只实现 DataSource 单元测试。

必须把当前所有已实现组件接入正式数据入口。

更新后的完整 Vertical Slice：

```text
OnlyHistoricalDataSource / OnlyMarketDataGateway
    ↓
HistoricalReplayService / MarketDataInboundQueue
    ↓
OnlyMarketDataProcessor
    ↓
OnlyMarketDataPipeline
    ↓
Aggregation / Indicator / Snapshot
    ↓
Cluster
    ↓
Order
    ↓
Risk
    ↓
Broker / VirtualBroker
    ↓
ExecutionProcessor
    ↓
Position
    ↓
Allocation
    ↓
StrategyLedger
    ↓
Account
    ↓
Event
    ↓
Final Report
```

正常场景不得：

* Runtime 直接读取 CSV；
* 测试直接调用 MarketDataPipeline；
* Demo 手工调用 Cluster；
* DataSource 直接调用 Cluster；
* 绕过 MarketDataProcessor；
* 手工推进多个不同 Clock。

---

# 48. Integration Environment 更新

更新：

```text
OnlyIntegrationEnvironment
```

加入：

```text
market_data_source_registry
historical_data_source
reference_data_source
market_data_gateway
market_data_inbound_queue
market_data_processor
market_data_deduplicator
market_data_sequence_tracker
market_data_gap_detector
historical_replay_service
market_data_audit_store
```

---

# 49. 新增 Integration Scenarios

至少新增以下场景。

## 49.1 本地历史 Bar 回放

```text
InMemory Historical Source
→ Replay
→ Clock
→ Processor
→ Pipeline
→ Snapshot
→ Cluster
```

验证正式入口完整。

## 49.2 Parquet 回测

```text
Parquet Source
→ 时间范围过滤
→ Replay
→ 完整交易闭环
```

验证：

* 数据版本；
* Decimal；
* UTC；
* 排序；
* 最终 PnL。

## 49.3 多 Instrument 归并

两个 Instrument 的 Bar 时间交错。

验证稳定全序和策略回调结果。

## 49.4 1m → 3m 聚合

历史源只提供 1m。

Pipeline 自动生成 3m。

第三分钟时：

* 3m 已完成；
* Indicator 已更新；
* 主周期回调只执行一次；
* Snapshot 可查询 3m。

## 49.5 重复 Bar

同一个 Bar 输入两次。

验证：

* 第二次 DUPLICATE；
* 不重复聚合；
* 不重复调用策略；
* 不重复下单。

## 49.6 缺失 Bar

Session 内缺少一根 Bar。

验证：

* Gap Detector；
* Quality；
* Pipeline Policy；
* Report。

午间休市不应误报。

## 49.7 同时间多 Instrument

多个资产同一 `ts_event`。

验证稳定排序和 Replay 确定性。

## 49.8 No Lookahead

策略在当前 Bar 不能读取未来 Bar。

Next-Bar Matching 不能使用订单提交前的未来信息。

## 49.9 实时 InMemory Gateway

```text
InMemory Gateway
→ MarketData Queue
→ Processor
→ Pipeline
→ Cluster
```

模拟 Paper Runtime 的数据入口。

## 49.10 完整交易闭环

```text
Historical Source
→ Replay
→ Cluster
→ Order
→ Risk
→ Virtual Broker
→ ExecutionProcessor
→ Position
→ Allocation
→ Ledger
→ Account
```

必须验证所有已实现组件继续连通。

---

# 50. 历史场景回归

必须运行所有历史场景：

```text
Domain
Clock
Runtime
Context
Cluster
MarketData Pipeline
Order
Risk
Position
Position Allocation
Strategy Ledger
Account
Broker
Virtual Broker
Execution Processor
```

如果旧场景直接向 Pipeline 手工注入数据，应迁移到：

```text
DataSource / Gateway
→ Processor
→ Pipeline
```

但不得修改原业务预期。

不得：

* 删除；
* Skip；
* 放宽断言；
* 建立旁路；
* 只运行新增测试。

---

# 51. 完整不变量

全链路结束后至少验证：

```text
MarketData 与 Broker 接口完全独立

DataSource 不直接调用 Cluster

所有实时数据通过 MarketData Queue

所有历史数据通过 ReplayService

所有数据通过 MarketDataProcessor

Clock 只由 ReplayService 推进

相同时间事件顺序稳定

重复数据不重复更新

Gap 检测考虑 TradingSession

Snapshot 不包含未来数据

派生 Bar 不重复

Indicator 顺序正确

Cluster 不知道 Source 实现

回测结果不依赖文件枚举顺序

在线源被标记为非确定性时报告可见

交易链全部历史不变量继续成立

相同输入重放结果一致
```

---

# 52. Deterministic Replay

使用固定：

```text
Runtime 配置
Instrument
TradingCalendar
MarketRule
Data Source 配置
Data Version
历史数据
Replay 排序策略
Clock
Cluster 配置
Risk 配置
Virtual Broker 配置
```

至少重复执行 100 次。

比较：

```text
Processing Result
Clock 序列
MarketData Audit
Snapshot Version
Bar Aggregation
Indicator Result
Cluster Callback 顺序
Order
Risk
Broker Update
Position
Allocation
Ledger
Account
Event Sequence
最终 Report
```

必须完全一致。

---

# 53. Demo

创建：

```text
examples/data_source_demo/
├── README.md
├── in_memory_history_demo.py
├── parquet_history_demo.py
├── csv_import_demo.py
├── multi_instrument_replay_demo.py
├── gap_detection_demo.py
├── live_in_memory_gateway_demo.py
└── full_vertical_slice_demo.py
```

更新：

```text
examples/integration_demo/
```

统一运行入口：

```bash
python examples/integration_demo/run_all.py
```

Demo 必须使用正式：

```text
DataSource / Gateway
→ Queue / Replay
→ Processor
→ Pipeline
```

---

# 54. 文档

创建或更新：

```text
docs/market_data_source.md
docs/historical_data_source.md
docs/reference_data_source.md
docs/historical_replay.md
docs/market_data_pipeline.md
docs/runtime.md
docs/runtime_context.md
docs/time_model.md
docs/integration_vertical_slice.md
docs/testing.md
docs/architecture.md
docs/architecture_principles.md
```

`docs/market_data_source.md` 至少包括：

1. 数据平面与执行平面；
2. 实时与历史接口区别；
3. Gateway Ports；
4. HistoricalDataSource；
5. ReferenceDataSource；
6. Update Envelope；
7. Source/Sequence/Version；
8. Quality；
9. Processor；
10. Gap Detection；
11. Queue；
12. Backpressure；
13. Runtime 接入；
14. Source Registry；
15. 已知限制。

`docs/historical_replay.md` 至少包括：

1. Replay 职责；
2. Clock 推进；
3. 多流归并；
4. 稳定排序；
5. 同时间事件；
6. Lookahead 防护；
7. Data Version；
8. 在线数据限制；
9. Replay Audit；
10. Determinism。

---

# 55. ADR

创建：

```text
docs/adr/0017-market-data-sources-and-deterministic-replay.md
```

至少记录：

## 背景

OnlyAlpha 的实时行情、历史数据、参考数据和券商交易服务可能来自不同供应商。Backtest、Paper 和 Live 需要统一 Domain，但数据获取方式不同。

## 决策

* MarketDataGateway 与 BrokerGateway 分离；
* 实时订阅和历史查询使用不同 Port；
* 实时和历史输出统一 Domain；
* 数据通过 Update Envelope 保留来源元数据；
* 所有数据进入 MarketDataProcessor；
* 历史数据通过 HistoricalReplayService 推进 Clock；
* 正式回测默认使用版本化本地数据；
* 在线历史源不作为确定性回测的隐式依赖；
* 数据质量是一级属性；
* MarketData Queue 与 Broker Queue 分离；
* 所有已实现组件继续执行完整 Vertical Slice。

## 拒绝方案

* MarketData 放入 BrokerGateway；
* Runtime 直接读取 CSV；
* DataSource 直接调用 Cluster；
* 回测自行排序 DataFrame；
* 在线 API 在正式回测过程中即时请求；
* 使用文件顺序决定事件顺序；
* 数据不带 Source/Version/Quality；
* 历史和实时使用不同 Bar 类型。

---

# 56. Architecture Principles 新增规则

加入：

```text
Rule: 市场数据平面与交易执行平面必须分离。

Rule: MarketDataGateway 不属于 BrokerGateway。

Rule: 实时数据和历史数据使用统一 Domain 类型。

Rule: 实时数据必须通过 MarketData Inbound Queue。

Rule: 历史数据必须通过 HistoricalReplayService。

Rule: 所有标准化数据必须经过 MarketDataProcessor。

Rule: HistoricalReplayService 是 Backtest Clock 的唯一数据推进者。

Rule: 正式确定性回测默认使用版本化本地数据。

Rule: 在线数据源必须明确标记非确定性风险。

Rule: 数据来源、Sequence、Version 和 Quality 必须可追踪。

Rule: 数据缺口检测必须理解 TradingCalendar 和 Session。

Rule: 策略不得访问 DataSource、Gateway 或 ReplayService。

Rule: 每个新增组件必须接入完整 Vertical Slice。
```

---

# 57. 实现顺序

严格按以下顺序：

1. 扫描当前数据入口和回测数据读取实现；
2. 创建差距分析；
3. 定义 Source ID、Capability、Version、Quality；
4. 定义 MarketData Update Envelope；
5. 定义实时 Connection/Subscription/Stream Ports；
6. 定义 HistoricalDataSource；
7. 定义 ReferenceDataSource；
8. 实现历史请求和 Stream；
9. 实现 MarketDataProcessor；
10. 实现 Validation；
11. 实现 Deduplication；
12. 实现 Sequence Tracker；
13. 实现 Gap Detector；
14. 实现 InMemory Historical Source；
15. 实现 HistoricalReplayService；
16. 实现稳定多流归并；
17. 接入 BacktestClock；
18. 实现 InMemory MarketDataGateway；
19. 实现 MarketData Queue；
20. 实现 Parquet Source；
21. 实现 CSV Source；
22. 实现 InMemory Reference Source；
23. 实现 Source Registry；
24. 实现 Event 和 Audit；
25. 接入 Runtime；
26. 更新 Integration Environment；
27. 迁移旧数据注入场景；
28. 新增完整场景；
29. 运行所有历史测试；
30. 运行 Deterministic Replay；
31. 创建 Demo；
32. 更新文档；
33. 创建 ADR；
34. 生成集成报告。

---

# 58. 验收标准

完成后必须满足：

* MarketData 与 Broker 完全分离；
* 实时和历史使用统一 Domain；
* 实时订阅 Port 清晰；
* HistoricalDataSource Port 清晰；
* ReferenceDataSource Port 清晰；
* DataSource 不调用 Cluster；
* Processor 是统一数据入口；
* 回测数据全部经过 ReplayService；
* ReplayService 推进 Clock；
* 多 Instrument 稳定归并；
* 同时间事件顺序稳定；
* 重复数据幂等；
* Gap 检测正确；
* 午间休市不误报；
* Data Version 可追踪；
* Quality 可追踪；
* Parquet 范围过滤正确；
* CSV 严格校验；
* 正式回测无在线隐式依赖；
* Lookahead 测试通过；
* MarketData Queue 与 Broker Queue 分离；
* 所有历史组件连通测试通过；
* Deterministic Replay 通过；
* 文档、Demo、ADR、报告完整。

---

# 59. 一票否决项

存在以下任一项，任务必须判定为 `REJECTED`：

* 将 MarketData 接口放入 BrokerGateway；
* DataSource 直接调用 Cluster；
* Gateway 直接修改 MarketData Cache；
* Runtime 直接读取 CSV 或 Parquet 驱动策略；
* 历史数据绕过 ReplayService；
* 实时数据绕过 MarketDataProcessor；
* 多流顺序依赖文件顺序；
* Processor 使用系统时间；
* Replay Clock 可回退；
* 策略可以访问 DataSource；
* 正式回测隐式调用在线 API；
* 数据版本不可追踪；
* 数据重复导致重复下单；
* Gap 检测把合法 Session 间隔当成错误；
* 出现未来数据泄露；
* 历史场景被删除、Skip 或放宽；
* 完整 Vertical Slice 失败；
* 相同输入重放结果不同；
* 新增 ARL；
* 引入历史兼容设计。

---

# 60. 集成报告

生成：

```text
docs/reports/market_data_source_integration_report.md
```

至少包含：

```text
新增文件
修改文件
市场数据组件边界
MarketData 与 Broker 分离结果
实时 Gateway Ports
HistoricalDataSource
ReferenceDataSource
Update Envelope
Source ID
Sequence
Data Version
Quality Flags
MarketDataProcessor
Validation
Deduplication
Gap Detection
HistoricalReplayService
Replay 排序规则
Clock 推进规则
Lookahead 防护
InMemory Source
Parquet Source
CSV Source
在线数据源边界
MarketData Queue
Runtime 接入
Integration Environment 更新
新增集成场景
历史场景结果
单元测试结果
上下游集成测试结果
完整 Vertical Slice 结果
Deterministic Replay 结果
关键不变量
已知限制
一票否决项
是否建议进入 OnlyPaperRuntime
是否建议实现持久化数据目录
是否建议接入首个真实 MarketDataGateway
```

最终结论只能是：

```text
ACCEPTED
CONDITIONALLY_ACCEPTED
REJECTED
```
