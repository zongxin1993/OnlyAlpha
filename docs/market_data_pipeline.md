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
`OnlyBarSemantic`。Resolution plan schema v3、Construction identity schema v2 与 Bar semantic schema v3 才是
当前持久格式；旧 identity 不静默重解释，读取时要求 rebuild。

Construction Graph schema v1 使用 typed BAR/TRADE provider input node；TRADE→BAR 可以表达和持久化，
未注册的 TICK_BAR/VOLUME_BAR/VALUE_BAR executor fail closed。TIME_BAR@1 由 Algorithm Registry 的 factory 创建，
Manager 不选择具体算法。Runtime Lane ID 绑定 output、recipe fingerprint 与 source binding identity；
Dataset 的 ConstructionIdentity 仍是独立的 durable evidence。Bar Subscription schema v3 与 Aggregation checkpoint
participant v3 拒绝旧格式并要求 rebuild。Compiled Graph 以 provider lane 和 derived lane 为路由 Authority，按
topological level、lane ID 稳定顺序同步传播到 fixpoint；任一 Construction executor 失败都会令
Manager fail-stop，且在有效 constructed Bar 进入 Cache/dispatch 前失败。
同一 provider trigger 返回重复 BarType 也属于 executor result contract violation，由 Manager 在 transaction 内 fail-stop；
后续调用必须先完成 Construction recovery，Pipeline 的防御检查不拥有该 transaction authority。

### Rust Construction library boundary

`crates/onlyalpha-kernel/market_data/construction/` is package `onlyalpha-market-data-construction`; its only local edge is
Domain. It owns typed recipe/requirement/capability/resolution/lineage values, stable construction graphs and compiled lane
identities, exact-version pure executor registration, session-aware TIME_BAR@1, shared registrations and component recovery.
Market-specific calendars arrive as immutable Domain inputs; provider discovery, Source continuity/grants, dispatch,
State/calculation updates, durable Dataset publication and Runtime admission remain outside this library.

Current value records retain recipe1, requirement1, graph1, resolution plan3, construction identity2 and lane1 meanings.
Map-like graph rows normalize order, duplicate identities reject and histories retain chronological order. Exact recipe
requests never substitute another recipe. Parsing lineage values does not prove referenced revisions/seals exist.
Only TIME_BAR@1 is built in; other graph algorithms require a factory registered under their exact ID/version. Factories
must create isolated, deterministic, side-effect-free executors. This in-process SPI is not a sandbox for untrusted code.

A non-Clone manager binds exact Engine/Runtime/source/calendar. Registration IDs own membership; provider/lane counts derive
from registrations. Configuration changes prepare a complete candidate before replacement and retain shared lane state.
Processing uses explicit logical init, validates closed unrevised provider Bars and all derived output contracts, propagates
in global `(topological level, lane ID)` order, and replaces executor state only after the complete trigger succeeds. Error
or unwind during execution marks recovery-required without publishing or committing a prefix. A failed owner cannot capture
or process; its coordinator must retain the last valid checkpoint and explicitly restore it. Wrong source does not rebind.
Unmatched input yields no output, never certified historical absence or readiness. Staging uses fresh executors and validated
checkpoint records per trigger; this favors bounded correctness and makes no production throughput claim.

TIME_BAR@1 consumes session-aligned, contiguous, closed revision0 source Bars. It uses Domain exact decimal arithmetic and
explicit calendar intervals, preserves the last accepted boundary after reset, rejects duplicates/late input, and enforces
source/target precision, trading-day/session and known optional currency/precision relations. Missing REJECT/SKIP_WINDOW and
tail DROP/REJECT are explicit; no synthetic Bars or silent corrections exist. Historical acquisition init does not replace
logical replay time. Output init must convert exactly to Domain datetime; sub-microsecond loss is rejected. Read-only preview
is nonclosed, cannot mutate formal state and never enters manager propagation.

Time executor component schema1 binds exact edge/calendar and EMPTY, PENDING or SETTLED state. Rust manager component schema4
binds exact owner/source/calendar, registrations/graph, complete lane/source-lane/recipe/level identities, derived reference
counts, executor states and arbitrary-precision lifetime creation count. Restore validates complete relations and all fresh
executors before a single replacement. It requires the receiver's expected typed registrations already configured; it does
not import another configuration. Duplicate rows, owner aliases, foreign contexts, malformed states and count mismatches
reject without changing the prior state or recovery-required flag. Row order may normalize; history order never does.

This Rust component schema4 is **not admitted** to the current Python Runtime aggregation participant schema3. There is no
fallback, conversion, production cutover, existing-history mutation or real restart/upgrade certification in this module.
Future admission must separately bind Generation, immutable input and checkpoint authority, preserve durable history and
prove real lifecycle behavior. Shared vectors demonstrate common valid semantics only; Python defects in absent unregister,
checkpoint duplicate collapse and permissive readers are not Rust requirements. See the
[Construction design](superpowers/specs/2026-10-18-rust-market-data-construction-design.md).

### Rust composed preparation boundary

`market_data/pipeline` composes the existing Construction, State, Delivery and Calculation owners. The program binds exact
Source/calendar/executor artifacts, Generation, scoped calculation bindings and a pure preparation consumer artifact. One BarType
has one Source owner; native and derived ownership cannot overlap. Inputs carry exact root/Source sequence and explicit logical time.
Closed Bar roots advance strictly; Trade roots can share event time under increasing sequence and can yield no closed Bar.
An ordered-prefix SHA-256 chain binds receipts to earlier admitted inputs without reserializing retained history for each Bar.

Calculation runs through the Infrastructure-owned managed Python worker port. Readiness uses each scope's current intended input
position, including explicit unobserved optional inputs. A route plan alone never proves invocation: each result reports actual pure
consumer invocation/outcome. A failed or uncertain consumer quarantines only its Cluster; shared construction/state or unknown/malformed
calculation receipts fail-stop this component until explicit complete restore. There is no automatic retry or process recreation.

Component checkpoint schema1 captures all Source managers, State, planning watermarks, scoped calculation bundles, expected input
positions, last attempted Bars, ordered frontiers and quarantines under caller-expected SHA-256. Restore constructs fresh candidates,
validates exact component relationships and worker acknowledgments, then installs the complete candidate. The consumer is deterministic
and non-effectful: it owns no recoverable trading truth. This component is not an official Runtime participant, Source-grant or gap
continuity proof, Research Evidence, economic execution or deployment/history migration. Python remains the active Runtime reference.
See the [composition design](superpowers/specs/2026-10-18-rust-market-data-pipeline-design.md).

The composed checkpoint includes a derived composition manifest binding each manager checkpoint SHA-256 to its exact root-frontier
projection and the global ordered input prefix. Neither older manager bytes nor an older manager-plus-binding can be transplanted
into a newer cutoff. The same manifest binds State, Delivery, calculation bundles and all other component fields to the same cutoff.
Healthy active calculations must match State latest Bar and version exactly; only failed/quarantined slots
may legitimately lag. The externally retained expected checkpoint digest is the trust root: this is integrity/provenance checking,
not authentication of a fully rewritten checkpoint accompanied by an attacker-chosen expected digest. It does not interpret or
redefine a custom Construction executor's opaque state.

### Rust Delivery planning boundary

MarketData is one business directory, `crates/onlyalpha-kernel/market_data/`, containing independently buildable `state/`,
`construction/`, `delivery/` and the composed `pipeline/` subcrates. Existing State/Construction package names and records retain their meanings.
Delivery adds no umbrella facade or deployment unit. Delivery depends on Domain, State and Construction; neither lower
subcrate depends on Delivery. Pure dependency/source guards and extracted builds enforce this direction.

`onlyalpha-market-data-delivery` owns explicit subscription values, active Cluster registrations, immutable scoped delivery
plans and one last-planned timestamp per active registration. It does not own Construction registration, State mutation,
calculation readiness, Source/Generation admission or actual Cluster/Strategy execution. Inputs are exact Engine/Runtime-
scoped immutable State snapshots. Only an updated primary triggers planning. Plans sort by Cluster ID, restrict views to
single-instrument subscriptions, and enforce LatestClosed or SameEventTime freshness. Default primary uses minimum fixed-
duration stride then canonical BarType order; non-time subscriptions require an explicit primary. Subscription IDs are
explicit canonical Domain identifiers, never implicitly random. Duplicate Cluster/subscription registrations reject.

A triggered primary must strictly advance its registration cursor. Different Clusters may advance at the same timestamp
in separate valid input snapshots; no global time cursor is used. The complete batch validates before any cursor changes.
Validation failures leave configuration/cursors unchanged. The returned plans are data, not executable readiness or proof
that callbacks occurred. Actual Cluster error isolation and all calculation barriers remain the coordinator's responsibility.
At-most-once planning applies within a continuously active registration; unregister retires that lifetime and its cursor.
This does not grant actual execution on re-registration, global historical ID uniqueness or durable exactly-once execution.
The future Runtime coordinator must enforce its own exact lifecycle/admission and ADR0009 execution guarantees.

Subscription component schema1 is Rust-owned and distinct from Python subscription schema3; there is no fallback reader.
Delivery checkpoint schema1 binds exact Engine/Runtime and all registrations (Cluster ID, subscription record, nullable
last-planned event nanoseconds). Receiver configuration must already match exactly; restore never adopts another configuration.
Strict fields/types, duplicate rejection, nested graph equality and exactly representable Domain timestamp checks precede
one replacement. Parsed state grants neither execution authority nor proof of durable history/Generation readiness. This
component is not registered in the official Runtime checkpoint system; activation, causal binding, real restart/upgrade and
existing-history integrity require separate scoped work.

The Python reference retains its current official implementation. Common vectors exercise real Pipeline/Dispatcher calls;
coercive result readers, decoded ready barriers and unbounded historical slice sets are classified reference limitations,
not Rust expected behavior. See the [Delivery design](superpowers/specs/2026-10-18-rust-market-data-delivery-design.md).

## 4. Cache

`OnlyMarketDataCache` 是 Trading Runtime 所有的可变内部真值，按 BarType 保存 latest closed、history 与单调 version。
只有 Pipeline 可更新。Cluster 不获得 Cache 引用，只读取 Snapshot 中复制为 tuple/MappingProxy 的数据。

### Rust State library boundary

`crates/onlyalpha-kernel/market_data/state/` owns bounded closed-Bar state and immutable scoped queries, with Domain as its
only local dependency. A non-Clone Runtime owner accepts explicit Engine/Runtime IDs, positive per-type history_limit
(default 1024), closed unrevised end-time Bars, primary type, logical initialization time and quality flags. A complete batch
and its snapshot validate before one replacement; failures never commit a prefix. Versions are lifetime arbitrary-precision
integers, independent of retention. Historical acquisition init may follow the logical Backtest snapshot init.

Runtime snapshots may contain multiple instruments; Cluster restriction selects one instrument and may include an
unmaterialized secondary type. A selected local miss returns empty/zero, while an out-of-view query fails with Scope.
Views only narrow within the same Cluster. Latest, primary/instrument/day/session derive from retained immutable Bars;
there is no Indicator state or readiness/Source/Generation certification in this library.

Current Rust component records use schema 2. Checkpoints contain exactly `schema_version`, `engine_id`, `runtime_id`,
`history_limit`, `series`; each series contains `bar_type`, `version`, `history`. Snapshot records contain exactly
`schema_version`, `engine_id`, `runtime_id`, `cluster_id`, `ts_event_ns`, `ts_init_ns`, `primary_bar_type`,
`visible_bar_types`, `updated_bar_types`, `series`, `quality_flags`. IDs are strong Domain identifier strings, cluster_id
is nullable, and times/versions are exact JSON integers. Domain records supply BarTypes and Bars. Map-like arrays use
canonical Domain-record order, reject duplicates and preserve chronological history/quality-flag order. Every materialized
series has positive version >= retained length; checkpoint history cannot exceed its declared limit. Restore validates
all rows plus exact receiver owner/config before replacing state. It never unions, coerces, trims malformed imports or
silently converts old records.

This library is not admitted as a Runtime checkpoint participant. The actual Python `market-data.cache` participant remains
schema 1; its registration, reader and stored artifacts are unchanged. Future activation requires separately authorized
outer Generation/Source/Construction binding, historical migration/integrity and real restart/upgrade evidence. Cache-only
restore and common Python/Rust vectors cannot certify these properties or a user-visible latency improvement.
See the [selected design](superpowers/specs/2026-10-18-rust-market-data-state-design.md).

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
