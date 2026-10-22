# Market Data Source

## 边界

市场数据平面与交易执行平面物理分离。`OnlyMarketDataGateway` 只负责实时连接、订阅和把标准 Update 写入 Runtime 的独立有界
Queue；它不属于 BrokerGateway，不持有 Pipeline、Cache、Cluster、Clock 或任何交易 Manager。实时与历史入口复用 Domain 的
`OnlyBar`、`OnlyQuoteTick`、`OnlyTradeTick`，来源元数据由 frozen `OnlyMarketDataInboundUpdate` 保存。

```text
Decision Lane:  provider BAR → MarketData Queue → Processor → Construction/Bar Pipeline → Strategy
                provider TRADE → MarketData Queue → Processor → Construction Manager → closed BAR → Strategy
Reference Lane: TRADE → MarketData Queue → Processor → Realtime Market State → immutable Snapshot
Trading execution: Strategy Decision + immutable Snapshot → Order/Risk → Broker Queue → ExecutionProcessor
BACKTEST: Local HistoricalDataSource → ReplayService → Clock → Processor → Construction/Bar Pipeline
```

Streaming Runtime 在 recovery plan 捕获 frontier 前，通过 Driver/Worker 握手取得 inbound queue 的消费权：当前完整
update/callback 先结束并得到确认，之后 Worker 不再 dequeue，Runtime 独占 historical replay 和 suffix reconciliation。
Producer 仍可按原 bounded backpressure 入队。成功 checkpoint 并发布 LIVE 后才恢复 Worker；terminal failure 不恢复
market-data 消费，Stop 唤醒 ownership waiters。该握手不改变 Semantic Lane 的 mutation authority，也不持锁执行 Provider I/O。

Strategy Revision 的正式交付输入仍是 closed Bar。冻结的 Construction Recipe 可以要求 provider BAR，也可以要求
provider TRADE 并通过注册 executor 构造 Bar。raw Trade 本身永不触发 Strategy/Cluster dispatch；只有新的 canonical
closed Bar 会进入 Cache/Snapshot/Dispatcher。同一 Trade 也可在通过 Processor 检查后独立推进 realtime reference
projection，但 reference requirement 与 Strategy construction requirement 互不授权。Execution/Risk 在一次 planning cycle
开始时只 capture 一份 immutable snapshot；缺失、过期、错误 source/quality 或 unresolved gap 对新的
risk-increasing execution fail closed。

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
                   → PostgreSQL immutable per-Segment physical proof + coverage/revision/manifest commit
                   → WAL GC eligibility
```

Sealed historical reads load that PostgreSQL proof and recompute a digest from every current authoritative ClickHouse
physical column before returning facts. The exact Revision read also rebuilds the stored Coverage Manifest. Segments
created before the physical proof migration remain `UNPROVABLE` for exact reads and require new, independently
captured evidence; current ClickHouse rows alone never create expected authority.

The TRADE physical `provider_event_id` projection is the canonical typed TradeId value; a language-specific object display is not a provider identity. Canonical Fact, WAL and Segment identities do not change. Recovery first authenticates every stored physical column with the original immutable PostgreSQL proof, then requires every current WAL-derived physical column to match exactly before publication or collection. A historical producer's incorrect physical projection is UNPROVABLE: preserve the original WAL and facts without rewriting, a legacy-format fallback or new proof derived from current rows.

数据库不可用时 sealed WAL 仍是 durable backlog，drain health 显式 DEGRADED 并通过同一 idempotent recovery path 重试；不得静默
丢弃 Trade 或伪造数据库 commit。WAL 容量和内存 queue 均保持有界。

WAL append may reuse the next ordinal only when the current file bytes exactly equal the previously validated prefix of that
same open segment. This bounded, volatile prefix is an optimization, never durable authority: a changed prefix or interrupted
write requires full frame validation; seal and restart always validate the complete file. Every accepted frame still requires
a complete write and fsync. Short writes return no durable receipt, and torn tails use the existing quarantine/recovery path.

MarketData Queue 与 Broker Queue 分离，默认有界且不静默丢数据。Trading Runtime 独占 Registry、Queue、Processor、
Deduplicator、SequenceTracker、GapDetector、AuditStore、ReplayService 和 Gateway。Cluster 的 `ctx.market_data` 仍只返回
immutable Snapshot。Research Runtime 只拥有其 Dataset/Calculation state，不为结构对称创建 Broker Queue 或交易处理器。

一个订阅选择一个主 Source，不自动融合或切换。Runtime 从 generic Construction Graph provider inputs 投影
BAR/TRADE 数据族与 instrument scope：纯 Trade-root 的 provider `bar_types` 合法为空，但 `instrument_ids` 不得丢失。
Backtest 只要求 construction 需要的 historical BAR/TICK capability；SIM historical capability 同样只来自 bootstrap
construction，live capability 才与显式 Execution/Risk TRADE reference requirement 求并集。两种 Authority 和 identity 保持独立。
尚未实现 Level 2、分布式服务、自动主备或复杂公司行动。

Streaming 生命周期保持四条显式 lane：Historical Construction 只从 Construction Graph 的 provider BAR/TRADE root
重建 Strategy Bar 状态；Realtime Construction 让实时 provider root 经 Processor 继续 Construction；Execution/Risk Reference
只允许实时 TRADE 更新 operational projection；Recovery 组合 provider-input frontier 与 Construction checkpoint 后，经同一
Processor 重放。实时 reference requirement 不授权 historical Trade bootstrap。derived Tick/Volume/Value Bar 不是 provider
continuity frontier；其恢复 cursor 属于 provider Trade identity/sequence，pending construction state 属于 executor checkpoint。
Core historical recovery 同样只枚举 Construction Graph provider root；reference-only Trade frontier 只能由 provider-native
reconnect/baseline 恢复。每个 cursor 直接绑定 exact Streaming key（source、data version、instrument、data kind、BarType），
不得使用同 source/data kind 下其他 instrument 或 BarType 的最大 sequence。
当一个 Runtime 有多个 provider root 时，每个 root 的历史 replay 仍使用自己的 exact cursor，但它们共同属于一个 Runtime recovery
transaction；Runtime-global realtime suffix 只能在全部 root replay 完成后处理一次，全部 continuity 验证完成前不得恢复 LIVE。

## 规范 Market Source identity

DataSource 实现通过 `OnlyDataSourceMarketIdentityV1` 声明 canonical Market Source identity（`provider/venue`、
`market`、provider-owned `environment` 与稳定 `source_id`）。变化率判断属于插件：同一 provider 的 LIVE 与 provider testnet
是不同的外部行情 universe，必须拥有不同 `source_id`；timeout、reconnect、batch size 等非语义 runtime 设置变化不得改变
`source_id`。Core/Application 不包含任何 provider 名称分支，只消费插件声明的身份。

Durable Market Data scope 由该 canonical `source_id`、market、instrument、data kind、data version 与 bar type 共同决定，
因此不同 environment 的同名 instrument 永不共享 scope、coverage、revision 或 seal。

`Integration Runtime Provenance` 与 Market Source identity 是两件事：前者回答"由哪个 exact Integration Revision/runtime
binding 取得数据"，属于 provenance，不参与 canonical market fact identity。调整 timeout 而产生新的 binding 仍收敛到同一
canonical market fact identity，但会产生合法的、彼此独立的 Acquisition Intent。

## Durable Acquisition identity

Acquisition Intent identity 绑定 canonical `source_id`、`requested_scope`、provenance 与 exact
`integration_binding_fingerprint`；同一 intent 重复进入是 exact re-entry，保留最初 admission 时间而不因新的 retry 时间冲突。
Acquisition Intent 必须在任何 provider session、WAL、reference lookup 或 provider fetch 之前 durable，否则 Product 不得声称
自己进入过该状态。

持久 Acquisition identity 显式版本化：历史 V1 仅包含 `source_id + requested_scope + provenance`，保持原 ID 与 admission
时间且允许 binding provenance 缺失；新写入 V2 额外包含 exact `integration_binding_fingerprint`。V1 不会被重算或回填为 V2。

每次真实执行是独立 append-only occurrence，由每个 intent 内单调的 `attempt_number` 标识；PostgreSQL 在锁定对应 Intent 行的
同一事务内分配编号并写入 started occurrence，terminal outcome 是另一条 append-only fact。两次相同失败不得折叠为一行；
started occurrence 缺少 outcome 明确表示被中断或结果未知。
canonical 成功权威始终是 Coverage COMPLETE + Market Data Revision + Seal；terminal FAILED 只有在 durable failure evidence
存在时才可返回，failure evidence 无法持久化时必须返回显式 uncertainty 而不是 FAILED。

旧执行 lease 已释放且新的显式历史采集重新取得独占 lease 时，可以分配新的 attempt occurrence；旧 started 行仍保持其原始
UNKNOWN，不补造 FAILED。Application 必须先恢复、重新验证现有 sealed coverage，再只获取剩余 gaps。该历史读取执行与
ClickHouse 写入重发是不同边界：先前不明 submission 的 durable witness 不因新 attempt 而失效，ABSENT 也不能授权盲目重插。

历史查询 fail closed：只有显式 `SEALED_REVISION_NOT_FOUND` 可以投影为"尚无数据"，catalog 不可用、损坏或 schema 不兼容必须
传播为 Product error，且任何数据库失败都不得触发 provider acquisition。GET 路径只读 canonical database facts，不做任何 mutation。

## 日内 Time-Bar Product 投影

Product 的 Bar Specification 使用 Core 的 `TIME + step + LAST` 语义；当前支持 1–240 整数分钟，优先选择 Source
capability 精确声明的 provider-native interval。当前 Binance Spot 原生分钟为 **1、3、5、15、30、60、120、240**。
原生 plan 的历史查询、显式 Acquisition 和 Realtime 都使用该选定 interval 与原生 canonical Bar，不得把已支持的原生
interval 静默改成 1m 派生身份。原生 cursor 使用 bar start 除以选定 interval stride 的序号；session Calendar 和原生
对齐规则由插件提供，Core 不硬编码 provider 规则。

仅当目标分钟无精确原生 capability 时，已关闭目标 Bar 才从精确 sealed 1m Revision、插件 session Calendar 和
`TIME_BAR_V1` 聚合规则计算为 INTERNAL 投影。GET 只输出完全落在已证明范围内且从 session 起点对齐的完整目标窗口，
不为范围两端不足一个窗口的部分伪造目标 Bar。响应保留实际输入 Revision ID/fingerprint、Calendar fingerprint、
resolution plan 与聚合语义版本；缺少完整 coverage 时返回实际 acquisition gaps。显式 Acquisition 依同一 plan 选择
原生 interval，只有派生 plan 获取 1m；派生 GET 的 base 范围最多七天。

Realtime 的原生 plan 订阅该原生 interval，并按同一 interval 修复连续性；派生 plan 才订阅 provider 1m，先从 durable
1m facts 重建当前目标窗口，再以同一聚合器生成 operational preview 与已关闭目标 Bar。派生链的 base minute sequence
独立作为连续性 cursor。重建缺分钟时拒绝 READY 并要求刷新历史；socket 连接成功本身不构成 READY。

## Browser Bar Ledger

唯一 canonical 开发 Compose 栈在 Web 启动前，通过 versioned Product API 自动创建并发布 Binance Spot Market Data
公共行情源，无需人工添加或 API key；已有来源和后续人工禁用/修改会保留（见 `docs/deployment.md`）。发布配置不等于
行情 READY 认证，也不授予交易 LIVE Authority。

Web 工作区的开发默认偏好是 `binance.spot.market_data` / `GLOBAL`（公共实盘行情），不是持久化来源绑定或 Provider availability
Authority。只有 Product sources 投影中恰有一个匹配来源时才自动选定；零个显示配置入口，多个要求显式选择。
Integration ID、Revision fingerprint 与 Source ID 均来自服务端。选定匹配来源后，使用正式 Instrument query
搜索 `BTCUSDT`，仅采用唯一的 `BTCUSDT.BINANCE` 成员；缺失或重复不得以其他标的代替。第一笔历史查询和
实时订阅使用 `15m / LAST / RAW / SESSION_START`，不先加载 1m。非默认来源仍可通过显式来源、标的和周期选择使用。

工作区只渲染 Product bars，未配置、不可用、缺少标的或尚未得到完整 Coverage 时不填充占位 K 线。自选读数与检查器
只展示当前服务端行情上下文；未接入的 Research/Backtest 面板和 Indicator/Factor Catalog 显示缺口态，既不伪造
业务行，也不生成本地指标/因子数值。默认偏好不写 localStorage，不改变 Query/Command、Ledger 或 Renderer 的 Authority。

Web Console 的 Browser Bar Ledger 只是当前图表上下文内的 presentation state，不是 Market Data、Coverage 或 Revision Authority。
服务端仍独占 canonical Coverage、Revision、history projection 与 acquisition planning；浏览器只按 exact Integration Revision、
Instrument 和 Bar Semantic 合并 Product API 返回的 closed Bar，并单独维护最多一个 operational preview。

视口接近左缘时，浏览器以 ledger 当前最早 Bar 的精确纳秒时间发起 query-first `BEFORE_TIME` 请求。Coverage 不完整时，浏览器
只提交响应中 `planned_acquisition_ranges` 明示的范围，完成后重放同一 frozen query；不得自行推导缺口、直接调用 provider 或把
preview 当作 canonical history。相同 timestamp 的 exact duplicate 是幂等输入；payload 冲突以
`MARKET_DATA_BAR_LEDGER_CONFLICT` fail closed，旧上下文的迟到结果也不得进入当前图表。

Chart presentation admission 在 Ledger 变更前校验时间与有限数值；OnlyAlpha-owned projection 保留精确 start/end 纳秒、
OHLCV 字符串及 closed/preview 状态，renderer number 仅是显式有损投影。图表类型是浏览器展示偏好，不参与 Product query、
chart context 或 Stream identity。十字线只选择当前 context 内的精确 Bar identity，读数始终从当前 projection 派生，
不得把 renderer `seriesData` 当作行情事实；没有真实 Bar 时显示 unavailable，不用 synthetic 数值补齐。


## 商品发现与自选报价

统一搜索 `GET /api/v2/market/instruments/search` 仅查询当前 ACTIVE、有发布 Revision、通过当前 runtime admission 的配置来源，
并在返回前重新检查 exact Source read grant。插件通过 `OnlyDataSourceDiscoveryCapabilitiesV1` 声明可搜索资产范围。
Application 不包含 provider 分支；`asset_class` 与 `instrument_types` 直接使用 canonical 枚举值，过滤必须先于结果截断。
每条结果携带 exact Source selection 和 Instrument projection，不按相似 ticker 合并商品或静默替换来源。

Provider 调用位于独立、可终止的轻量子进程，不重新执行 Web/Application 服务入口。Factory 必须由可导入模块定义并可序列化，不能使用服务 `__main__` 或局部类。所有请求共用最多四个 provider process，搜索与报价单来源截止八秒，搜索整体截止十秒，Web 等待上限十二秒。
该预算包含冷启动与网络：完整公开目录在 dev 容器实测约 4.2 秒，其中冷启动约 1 秒；五秒预算在真实 UI 首搜出现超时，不能仅凭单次网络成功认定可用。上述上限保留网络波动余量，不授权自动重试或无界等待。
截止也包含等待 process slot 的时间；超时进程 kill 并 reap，不以取消 Python Future 假装终止 Provider。
来源分别返回 COMPLETE、TIMEOUT、UNAVAILABLE 或 UNSUPPORTED，只有 COMPLETE 且无匹配才表示该来源没有结果。
部分结果可展示，但不得把失败来源、目录上限或结果截断包装成完整的无匹配证明。

声明 `catalogue_snapshot` 的插件提供最多 10001 条投影（10000 条容量加一个截断哨兵），并授权按展示代码或完整 Instrument ID
做 literal substring 搜索。snapshot 是可丢弃的 reference projection；父侧内存缓存最多 32 个 exact Integration Revision / binding，
有效期 60 秒。每次使用仍先解析 owning runtime / grant，不从缓存重建权限或 availability 证明。它不是 Market Fact、交易或
Research Evidence Authority，也不授权从 catalogue 响应获取行情历史。

`GET /api/v2/market-data/quotes` 是独立的 operational read，要求 REALTIME_PREVIEW 权限，最多请求同一来源 25 个 Instrument。
插件通过 `OnlyDataSourceQuotes` 提供当前成交价、涨跌幅、明确的 ROLLING_24H / PREVIOUS_CLOSE 基准及事件时间。
缺少某一 Instrument 的报价返回该行 UNAVAILABLE 与 null，不用 K 线收盘价补位。decimal 值和纳秒时间通过字符串传输；
Web 不重算涨跌幅、不合并来源、不将 operational quote 用作 sealed history 或 execution reference。
Binance Spot 使用正式 `/api/v3/exchangeInfo?permissions=SPOT&showPermissionSets=false` 目录和 `/api/v3/ticker/24hr` 报价，其涨跌幅口径为 ROLLING_24H。

Binance 公共 HTTP 协商 gzip，压缩 wire 与解压 JSON 分别受同一配置的响应大小上限约束；不支持或损坏的编码 fail closed。
Provider evidence observer 收到解码后的原始 JSON bytes；JSON 无效时仍记录该 payload 并报告解析失败，不把它当空目录。
目录查询按 [Binance 官方 REST Contract](https://github.com/binance/binance-spot-api-docs/blob/master/rest-api.md?plain=1)
省略未消费的 permissionSets，不改变商品、市场状态、价格步长或数量规则。单来源预算包含轻量进程启动、
Provider 网络往返、解码和投影，仍服从搜索整体截止；Web transport deadline 不授予服务端额外时间。
