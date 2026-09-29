# MarketData Pipeline

MarketData Snapshot 只表达标准化、聚合后的不可变行情视图。具体指标不再附着在 Bar Subscription 或策略可见的 MarketData View；Factor 通过 Cluster-scoped Indicator Registry 创建和读取强类型 Indicator Snapshot。

本文的 Cache、Aggregation、Dispatcher 与 Cluster 边界属于 Trading Runtime。Research 可以复用 canonical Bar、Indicator
和 Factor 定义，但只拥有 Dataset/Calculation/Result state，不为结构对称创建 Trading Cluster 或交易 authority。

## 1. Provider 输入

Pipeline 有两种 provider 入口：`process_bar(OnlyBar)` 处理 provider-native 已关闭 Bar；
`process_trade(OnlyTradeTick)` 只在 Construction Graph 存在 `TRADE → BAR` lane 时驱动已注册 executor。
Strategy 的交付语义始终是 closed Bar，raw Trade 不会直接 dispatch。executor 未闭合 Bar 时不产生
Cache/Snapshot/dispatch；闭合后的真实 Bar 进入与 provider Bar 共用的 commit 路径。

Provider Bar 要求 `ts_event == bar_end`、Runtime Clock 不早于事件、BarType 内顺序单调；重复、乱序、
迟到与修订默认拒绝，不静默覆盖已用于策略决策的数据。

## 2. 固定数据准备顺序

```text
校验/去重 → Runtime Aggregation Manager → 已关闭 Bar 校验/Cache
→ 不可变 MarketData Snapshot → Dispatcher → Cluster Pipeline
→ scoped Indicator → TimeSeries Factor → CrossSection Factor → Required Factor Barrier → Strategy
```

Pipeline 内是直接同步调用，EventBus 只传播完成事实。`OnlyDataReadyBarrier` 的 Cache、Aggregation、
Indicator、Required Dependency 和 Snapshot 五项全部 ready 后，Dispatcher 才能执行。

## 3. 聚合与 Session 边界

一个 Trading Runtime 的 `OnlyBarAggregationManager` 按 Construction Lane ID 持有 Executor；多个 Cluster 用引用计数
共享相同 Recipe 与 Source Binding 的结果，不共享可变策略状态。当前同一 Bar Semantic 的 Native 与 Derived
Construction 不能同时激活，显式报 `RUNTIME_CONSTRUCTION_LANE_CONFLICT`。派生处理顺序是 dependency level
递增、同层 Construction Lane ID 递增；edge 声明和 Cluster 注册顺序不参与执行顺序。

`OnlyTimeBarAggregator` 使用 `OnlyTradingCalendar.session_intervals_for_trading_day()` 锚定窗口，区间
`[start,end)`，不对 Unix timestamp 取模。上午、午休、下午、夜盘、DST 与特殊 Session 由同一 Calendar
解释，禁止跨 Session 拼接。Session 尾部不足一个目标周期默认 DROP；REJECT 可配置。首版不生成 partial，
因此 Snapshot 的 `latest_closed` 不可能隐式返回 partial。

固定时长 Bar 的 canonical semantic 分别绑定 `window_minutes`（Bar 覆盖时长）与 `stride_minutes`（输出网格间隔）；
旧 `step=N` 不再被配置、Contract 或持久化入口接受。现有 `TIME_BAR@1`
由 `OnlyAlignedTumblingWindowPolicy` 实现且只接受 `window == stride`；rolling semantic 使用独立的
`ROLLING_TIME_BAR@1` recipe identity，但执行仍 fail closed，尚未启用 sliding policy。

`OnlyBarConstructionRecipe` 是 Native/Derived construction 的唯一 Authority；`OnlyBarType` 只绑定 instrument 与
`OnlyBarSemantic`。Resolution plan schema v3、Construction identity schema v2 与 Bar semantic schema v2 才是
当前持久格式；旧 identity 不静默重解释，读取时要求 rebuild。

Construction Graph schema v1 使用 typed BAR/TRADE provider input node；TRADE→BAR 可以表达和持久化，
未注册的 TICK_BAR/VOLUME_BAR/VALUE_BAR executor fail closed。TIME_BAR@1 由 Algorithm Registry 的 factory 创建，
Manager 不选择具体算法。Runtime Lane ID 绑定 output、recipe fingerprint 与 source binding identity；
Dataset 的 ConstructionIdentity 仍是独立的 durable evidence。Bar Subscription schema v3 与 Aggregation checkpoint
participant v3 拒绝旧格式并要求 rebuild。Compiled Graph 以 provider lane 和 derived lane 为路由 Authority，按
topological level、lane ID 稳定顺序同步传播到 fixpoint；任一 Construction executor 失败都会令
Manager fail-stop，且在有效 constructed Bar 进入 Cache/dispatch 前失败。

## 4. Cache

`OnlyMarketDataCache` 是 Trading Runtime 所有的可变内部真值，按 BarType 保存 latest closed、history 与单调 version。
只有 Pipeline 可更新。Cluster 不获得 Cache 引用，只读取 Snapshot 中复制为 tuple/MappingProxy 的数据。

## 5. Indicator 与 Factor Ready Barrier

Cluster Pipeline 按完整 Runtime/Cluster/Factor/Indicator Scope 更新匹配 BarType 的 Indicator，再按稳定依赖计划执行 Factor。Indicator/Factor Snapshot 的 Ready 与质量显式输出；Required Factor 未 Ready 时 Strategy 不执行。Runtime/Assembly 不识别具体指标，Strategy 不读 Indicator Registry。

## 6. Snapshot

`OnlyMarketDataSnapshot` 使用 Unix 纳秒 ts_event/ts_init、Runtime/Cluster Scope、主 Bar、当前时间片 updated
BarTypes、latest closed/history、TradingDay、SessionType 和 quality flags。所有映射只读，Bar 本身 frozen。Cluster View 只包含其订阅的 BarType。

查询 API 包括 `latest_closed/require_latest_closed/current_partial/was_updated/require_same_event_time`、
`history`。`require_same_event_time` 只接受 `bar_end == primary_bar.end`。

## 7. 主周期与多 Cluster

PRIMARY_ONLY 下，默认主周期是订阅中最小 fixed-duration stride；显式 `primary_bar_type` 覆盖。若含 Tick/Volume/Value
等不可自然比较 Bar，必须显式指定。只有主周期在 `updated_bar_types` 中时才调用，每 Cluster/纳秒时间片
最多一次。多个周期同时关闭仍只调用一次，策略从 Snapshot 读取其他周期。

Dispatcher 按稳定 Cluster ID 遍历，不以注册顺序表达业务依赖；单 Cluster 异常形成失败结果，其他 Cluster
继续。Runtime 装配中 Dispatcher 将执行委托给 ClusterManager，FAILED/STOPPED Cluster 不再调用。不同
Runtime 的 Cache、Aggregator、Indicator 和 Dispatcher 实例完全隔离。

## 8. 缺失数据与不完整 Bar

默认 Missing Policy 为 REJECT；可用 SKIP_WINDOW 明确跳过受损窗口。EMIT_PARTIAL、INSERT_EMPTY、
FILL_FORWARD 与 TRUNCATE 接口已预留但首版明确拒绝，避免把无成交、缺失、停牌或闭市混为一谈。

## 9. 重放

Event、Bar Subscription、provider-Bar Update Result、Snapshot 和 Dispatch Result 均提供稳定 DTO。Trade construction
使用独立 immutable result，保留 input Trade 和 constructed Bars，不伪造 provider base Bar。Event/Snapshot 保存
Unix 纳秒，Bar 保存 Decimal/UTC/强类型 Domain DTO。相同序列在新 Runtime Pipeline 中重放，Snapshot、
主 Bar、updated types、调用次数与调用时刻一致。Backtest、Sim 与 future Live 共用同一 prepare/dispatch 语义。当前
Backtest 已装配完整同步路径，SIM 已装配 realtime/streaming path。

历史 Trade bootstrap 与正常实时 Trade 共享 Processor 的 scope/source/instrument/lookahead/dedup/sequence/gap/quality admission，
但 consequence authority 显式分离：bootstrap 只进入 Construction，不更新 realtime execution-reference projection；正常实时
Trade 按 Runtime 已组合的 Construction/Reference requirement 执行 construction-only、reference-only 或二者。一个
Trade-trigger transaction 若产生重复 BarType，会在 Cache、Indicator、Snapshot 与 dispatch 前 fail closed，避免映射覆盖造成
静默丢失。

## 10. 已知限制

- 支持 provider-native 1m TIME Bar 到同标的、同价格类型、derived N>1 分钟 TIME Bar；产品层仍须独立限制请求范围。
- Domain 接受任意正数 fixed-duration window/stride（stride 不大于 window）；当前 Resolution 层对超过 240m
  返回 `BAR_RESOLUTION_UNSUPPORTED`。
- 尚无正式 Tick/Volume/Value Aggregator、partial Bar、修订替换或自动填充；Construction executor state 已纳入
  graph/lane-aware checkpoint 恢复。
- 核心路径同步串行；长策略 callback 会阻塞该 Runtime 的后续输入。
- Pipeline/Dispatcher 已装配进同步 Backtest RuntimeContext 与 SIM streaming path；Live 的 Real Broker 组合尚未实现。
- Indicator 值首版限 Decimal/int/string/bool/None，复杂向量需后续稳定 DTO。

## 11. 标准数据入口

Pipeline 不负责连接、读文件、推进 Clock、Source 去重或数据质量判定。所有生产输入先成为带 Source/Sequence/Version/Quality 的
`OnlyMarketDataInboundUpdate`，实时经独立 Queue、历史经 ReplayService，再由 `OnlyMarketDataProcessor` 调用 Pipeline。输入
Quality 合并进 immutable Snapshot；重复 Update 在 Pipeline 前停止。
