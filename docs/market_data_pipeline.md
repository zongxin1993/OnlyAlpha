# MarketData Pipeline

## 1. 基础 Bar 输入

首版命令入口是 `OnlyMarketDataPipeline.process_bar(OnlyBar)`，支持外部、已关闭、revision=0 的 1m TIME
Bar。要求 `ts_event == bar_end`、Runtime Clock 不早于事件、BarType 内顺序单调；重复、乱序、迟到与修订
默认拒绝，不静默覆盖已用于策略决策的数据。

## 2. 固定数据准备顺序

```text
校验/去重 → 基础 Bar Cache → Runtime Aggregation Manager → 派生 Bar 校验/Cache
→ 受影响 Indicator → Required Dependency Barrier → 不可变 Snapshot → Dispatcher → Cluster.on_bar
```

Pipeline 内是直接同步调用，EventBus 只传播完成事实。`OnlyDataReadyBarrier` 的 Cache、Aggregation、
Indicator、Required Dependency 和 Snapshot 五项全部 ready 后，Dispatcher 才能执行。

## 3. 聚合与 Session 边界

一个 Runtime 的 `OnlyBarAggregationManager` 按目标 BarType 唯一持有 Aggregator；多个 Cluster 用引用计数
共享 3m/5m/15m 结果，不共享可变策略状态。派生处理顺序是 dependency level（首版均为一级）、duration、
稳定 BarType ID。

`OnlyTimeBarAggregator` 使用 `OnlyTradingCalendar.session_intervals_for_trading_day()` 锚定窗口，区间
`[start,end)`，不对 Unix timestamp 取模。上午、午休、下午、夜盘、DST 与特殊 Session 由同一 Calendar
解释，禁止跨 Session 拼接。Session 尾部不足一个目标周期默认 DROP；REJECT 可配置。首版不生成 partial，
因此 Snapshot 的 `latest_closed` 不可能隐式返回 partial。

## 4. Cache

`OnlyMarketDataCache` 是 Runtime 所有的可变内部真值，按 BarType 保存 latest closed、history 与单调 version。
只有 Pipeline 可更新。Cluster 不获得 Cache 引用，只读取 Snapshot 中复制为 tuple/MappingProxy 的数据。

## 5. Indicator Ready Barrier

`OnlyIndicatorPipeline` 按稳定 Indicator ID 更新当前时间片受影响的共享指标。Required 失败抛
`OnlyMarketDataPipelineError` 并阻止 Snapshot/策略；Optional 失败进入 Snapshot quality flag，策略可继续。
Cache 已更新后才计算指标，Snapshot 创建后才执行策略。策略私有状态仍留在 Cluster，不塞进全局 Pipeline。

## 6. Snapshot

`OnlyMarketDataSnapshot` 使用 Unix 纳秒 ts_event/ts_init、Runtime/Cluster Scope、主 Bar、当前时间片 updated
BarTypes、latest closed/history、Indicator value/version、TradingDay、SessionType 和 quality flags。所有映射
只读，Bar 本身 frozen。Cluster View 只包含其订阅的 BarType/Indicator。

查询 API 包括 `latest_closed/require_latest_closed/current_partial/was_updated/require_same_event_time`、
`indicator/require_indicator/history`。`require_same_event_time` 只接受 `bar_end == primary_bar.end`。

## 7. 主周期与多 Cluster

PRIMARY_ONLY 下，默认主周期是订阅中最小 TIME step；显式 `primary_bar_type` 覆盖。若含 Tick/Volume/Value
等不可自然比较 Bar，必须显式指定。只有主周期在 `updated_bar_types` 中时才调用，每 Cluster/纳秒时间片
最多一次。多个周期同时关闭仍只调用一次，策略从 Snapshot 读取其他周期。

Dispatcher 按稳定 Cluster ID 遍历，不以注册顺序表达业务依赖；单 Cluster 异常形成失败结果，其他 Cluster
继续。不同 Runtime 的 Cache、Aggregator、Indicator 和 Dispatcher 实例完全隔离。

## 8. 缺失数据与不完整 Bar

默认 Missing Policy 为 REJECT；可用 SKIP_WINDOW 明确跳过受损窗口。EMIT_PARTIAL、INSERT_EMPTY、
FILL_FORWARD 与 TRUNCATE 接口已预留但首版明确拒绝，避免把无成交、缺失、停牌或闭市混为一谈。

## 9. 重放

Event、Bar Subscription、Update Result、Snapshot 和 Dispatch Result 均提供稳定 DTO。Event/Snapshot 保存
Unix 纳秒，Bar 保存 Decimal/UTC/强类型 Domain DTO。相同序列在新 Runtime Pipeline 中重放，Snapshot、
主 Bar、updated types、调用次数与调用时刻一致。Live/Backtest 共用同一 prepare/dispatch 实现。

## 10. 已知限制

- 只支持外部 1m TIME Bar 到内部 3m/5m/15m。
- 尚无 Tick/Volume/Value Aggregator、partial Bar、修订替换、自动填充或持久化恢复。
- 核心路径同步串行；长策略 callback 会阻塞该 Runtime 的后续输入。
- 尚未把 Pipeline/Dispatcher 装配进完整 RuntimeContext 或真实 Gateway。
- Indicator 值首版限 Decimal/int/string/bool/None，复杂向量需后续稳定 DTO。
