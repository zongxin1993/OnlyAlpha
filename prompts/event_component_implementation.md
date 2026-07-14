
# OnlyAlpha Event、MarketData Pipeline 与策略 Bar 驱动组件构建任务

## 1. 任务目标

现在开始实现 OnlyAlpha 的 Event 组件及其第一套核心事件流：

```text
基础 Bar 输入
    ↓
派生 Bar 聚合
    ↓
Bar Cache 更新
    ↓
指标更新
    ↓
生成一致性 Snapshot
    ↓
调用策略主周期 on_bar
```

本阶段需要实现一套确定性、可测试、可重放的事件基础设施，并验证以下策略运行模式：

> 策略可以订阅多个 Bar 周期。

> 默认使用最小订阅周期作为主周期。

> 策略也可以显式指定其他周期作为主周期。

> 每当主周期 Bar 关闭时，框架必须先完成当前逻辑时刻所有可生成的派生 Bar、指标和缓存更新。

> 数据准备完成后，生成不可变 Snapshot。

> 最后只调用一次策略 `on_bar(primary_bar, context)`。

> 策略通过 Snapshot 查询其他订阅周期的最新已关闭 Bar、当前时刻更新情况和指标值。

示例：

```text
策略订阅：
1m
3m
15m

默认主周期：
1m
```

在 09:33 时必须按以下顺序执行：

```text
接收并校验 09:32-09:33 的 1m Bar
更新 1m Cache
将 1m Bar 输入 3m 和 15m Aggregator
生成 09:30-09:33 的 3m Bar
15m 尚未关闭
更新 3m Cache
更新 1m 指标
更新 3m 指标
构造 09:33 Snapshot
调用一次策略 on_bar，参数为 1m 主 Bar
```

策略回调中可以读取：

```text
当前 1m 主 Bar
最新已关闭 3m Bar
最新已关闭 15m Bar
本时间片刚更新的 BarType
已准备好的指标
```

本阶段重点是：

* Event Model；
* EventBus；
* MarketData Pipeline；
* Bar 聚合调度；
* Snapshot；
* 策略 Bar 订阅；
* 主周期驱动；
* 数据准备屏障；
* 确定性回调。

本阶段不要实现完整交易系统。

---

# 2. 执行前必须阅读

开始实现前，必须阅读：

```text
AGENTS.md
docs/architecture.md
docs/domain_model.md
docs/instrument_model.md
docs/time_model.md
docs/clock.md
docs/runtime.md
docs/event.md
docs/concurrency.md
docs/coding_style.md
docs/testing.md
docs/adr/
```

重点检查当前已有：

```text
OnlyClock
OnlyLiveClock
OnlyBacktestClock
OnlyVirtualClock

OnlyBar
OnlyBarType
OnlyBarSpecification
OnlyTick
OnlyInstrument
OnlyTradingCalendar
```

先扫描现有工程中：

* Event 类型；
* publish/subscribe；
* Bar 订阅；
* Bar Cache；
* Bar Aggregator；
* Indicator；
* Cluster 回调；
* Runtime；
* 当前市场数据流；
* MyQuant 中多周期策略实现。

分析 MyQuant 路径：

```text
https://github.com/zongxin1993/MyQuant
```

只参考行为，不直接复制旧架构。

---

# 3. 先输出差距分析

创建：

```text
docs/event_component_analysis.md
```

至少记录：

## 3.1 当前事件实现

| 模块 | 当前实现 | 当前问题 | 目标实现 |
| -- | ---- | ---- | ---- |

## 3.2 当前 Bar 数据流

记录：

* 基础 Bar 来源；
* 多周期 Bar 如何生成；
* 是否每个策略重复聚合；
* 是否使用后台线程；
* Cache 在何时更新；
* 指标在何时计算；
* 策略回调在何时触发；
* 回测和实盘顺序是否一致。

## 3.3 风险

重点检查：

* 不同周期回调顺序依赖注册顺序；
* EventBus 承担业务工作流；
* 事件作用域不清；
* 回测事件串入实盘；
* Bar 聚合和策略回调并发；
* 策略读到半更新 Cache；
* 指标尚未完成时策略已经执行；
* 使用可变全局 Cache；
* 多策略重复聚合相同 Bar；
* 派生 Bar 边界未结合 Trading Calendar；
* Snapshot 不可重放；
* 事件顺序不确定。

先完成分析，再开始修改代码。

---

# 4. 总体架构

推荐实现以下调用链：

```text
Gateway / Historical Source
        ↓
OnlyBarInputEvent
        ↓
OnlyMarketDataPipeline
    1. 校验基础 Bar
    2. 更新基础 Bar Cache
    3. 更新所有相关 Aggregator
    4. 收集当前时间点关闭的派生 Bar
    5. 按依赖顺序更新派生 Bar Cache
    6. 更新相关指标
    7. 创建不可变 Snapshot
        ↓
OnlyMarketDataUpdateEvent
        ↓
OnlyStrategyBarDispatcher
        ↓
OnlyCluster.on_bar(primary_bar, context)
```

必须严格区分：

```text
EventBus
    负责传播已经发生的事实

Pipeline
    负责具有严格顺序的数据准备过程

Dispatcher
    负责按策略订阅配置调用策略

Snapshot
    负责为策略提供一致的只读数据视图
```

EventBus 不得替代 MarketData Pipeline。

不能让：

```text
Bar Cache
Aggregator
Indicator
Cluster
```

各自独立订阅基础 Bar，然后依赖订阅顺序完成业务流程。

---

# 5. Command、Query 与 Event 边界

必须遵循：

```text
Command
    明确接口调用

Query
    明确接口调用

Event
    表达已经发生的事实
```

例如：

## Command

```python
market_data_service.subscribe_bars(...)
market_data_pipeline.process_bar(...)
cluster_manager.start_cluster(...)
```

## Query

```python
snapshot.latest_closed(...)
snapshot.indicator(...)
instrument_registry.get(...)
```

## Event

```text
OnlyBarReceivedEvent
OnlyBarClosedEvent
OnlyDerivedBarCreatedEvent
OnlyMarketDataSnapshotReadyEvent
OnlyClusterBarHandledEvent
```

禁止使用：

```text
OnlyBuildThreeMinuteBarEvent
OnlyCalculateIndicatorEvent
OnlyCallStrategyEvent
```

这些是命令或内部步骤，不是领域事实。

---

# 6. Event Model

至少定义或完善：

```text
OnlyEvent
OnlyEventId
OnlyEventType
OnlyEventSource
OnlyEventScope
OnlyEventPriority
OnlyEventSequence
OnlyCorrelationId
OnlyCausationId
```

基础事件字段建议包括：

```text
event_id
event_type
ts_event
ts_init
sequence
engine_id
runtime_id
cluster_id
source
correlation_id
causation_id
metadata
payload
```

要求：

* `ts_event` 使用 Clock 的 UTC 时间语义；
* `ts_init` 表示 OnlyAlpha 创建事件的 UTC 时间；
* 事件不可变；
* 事件可序列化；
* 事件可回放；
* 事件类型稳定；
* 不允许裸字符串 ID；
* 不允许事件序列化丢失时间精度。

---

# 7. Event Scope

OnlyAlpha 支持同一 Engine 同时运行多个 Runtime。

必须保证 Event 不跨 Runtime 污染。

建议定义：

```text
OnlyEngineEventBus
OnlyRuntimeEventBus
```

或者统一实现配合：

```text
OnlyEventScope
```

至少包含：

```text
engine_id
runtime_id
cluster_id
```

推荐：

* Engine 生命周期事件进入 Engine Scope；
* Market Data、Order、Trade、Position、Account 进入 Runtime Scope；
* Cluster 私有事件可带 cluster_id；
* 回测 Runtime 和实盘 Runtime 使用独立队列；
* Cluster 不直接持有全局 Engine EventBus。

---

# 8. EventBus 第一版设计

第一版必须优先保证：

```text
同步
单线程
FIFO
有界队列
确定性
可测试
可关闭
```

不要一开始实现：

* 多线程消费者；
* asyncio EventBus；
* Redis；
* Kafka；
* 分布式事件；
* 动态 Topic 表达式；
* 复杂优先级工作流。

建议核心类型：

```text
OnlyEventBus
OnlySubscription
OnlySubscriptionId
OnlyEventHandler
OnlyEventQueuePolicy
OnlyEventDispatchResult
OnlyEventHandlerResult
```

建议接口：

```python
subscribe(...)
unsubscribe(...)
publish(...)
publish_many(...)
dispatch(...)
drain(...)
pending_count(...)
close(...)
```

## 8.1 Handler 顺序

同一事件的多个 Handler：

```text
显式 priority
    ↓
registration_sequence
```

但业务代码不得依赖未声明的注册顺序。

## 8.2 事件顺序

Runtime 内必须保持 FIFO。

相同输入多次运行，事件顺序必须完全一致。

## 8.3 有界队列

队列必须配置最大容量。

至少支持：

```text
REJECT
FAIL_RUNTIME
DROP_LOW_PRIORITY
```

第一版建议：

* 市场数据、订单、成交等核心事件：队列满时拒绝并返回错误；
* 不允许静默丢弃；
* 回测中队列满应视为实现错误。

## 8.4 异常隔离

Handler 异常：

* 不能破坏 EventBus 主循环；
* 必须形成结构化结果；
* 必须记录 event_id 和 handler；
* 不无限重试；
* 不静默吞掉。

---

# 9. Bar 订阅模型

策略可以订阅多个 `OnlyBarType`。

建议定义：

```text
OnlyBarSubscription
OnlyBarSubscriptionId
OnlyBarDeliveryMode
OnlyBarDependency
OnlyBarFreshnessPolicy
OnlyBarSubscriptionSet
```

## 9.1 默认主周期

默认规则：

```text
主周期 = 策略订阅的最小时间周期
```

例如：

```text
1m
3m
15m
```

默认：

```text
primary_bar_type = 1m
```

但必须允许显式覆盖：

```python
subscribe_bars(
    bar_types=[bar_1m, bar_3m],
    primary_bar_type=bar_3m,
)
```

## 9.2 非时间 Bar

如果订阅包含：

* Tick Bar；
* Volume Bar；
* Notional Bar；
* Session Bar；

则“最小周期”可能没有天然比较关系。

此时必须要求显式指定 `primary_bar_type`。

禁止框架猜测。

## 9.3 Delivery Mode

建议支持：

```text
PRIMARY_ONLY
EACH_BAR
TIME_SLICE
```

本阶段重点实现：

```text
PRIMARY_ONLY
```

语义：

> 只在主周期 Bar 关闭时调用一次策略 on_bar。

其他模式可以只定义枚举和扩展点，不必完整实现。

---

# 10. 主周期驱动规则

对于 `PRIMARY_ONLY`：

```text
策略订阅多个 BarType
主周期 Bar 关闭
    ↓
完成所有当前时刻可生成派生 Bar
    ↓
完成指标更新
    ↓
生成 Snapshot
    ↓
调用一次 on_bar
```

如果某个辅助周期在当前时刻未关闭：

* Snapshot 返回最近已关闭的辅助 Bar；
* `updated_this_slice()` 返回 False；
* 不允许隐式返回正在形成的 Partial Bar。

策略显式请求 Partial Bar 时，必须使用独立 API。

---

# 11. MarketData Pipeline

建议定义：

```text
OnlyMarketDataPipeline
OnlyMarketDataUpdateResult
OnlyMarketDataPipelineError
OnlyDataReadyBarrier
```

核心接口建议：

```python
process_bar(
    bar: OnlyBar,
) -> OnlyMarketDataUpdateResult
```

结果至少包括：

```text
input_bar
base_bar
derived_bars
updated_bar_types
updated_indicator_ids
snapshot
ts_event
trading_day
sequence
```

## 11.1 严格处理顺序

必须固定：

```text
1. 校验输入 Bar
2. 去重与顺序检查
3. 更新基础 Bar Cache
4. 将基础 Bar 输入 Aggregation Manager
5. 收集当前逻辑时间关闭的派生 Bar
6. 对派生 Bar 进行验证
7. 按依赖拓扑更新派生 Bar Cache
8. 更新所有受影响指标
9. 验证 Required Dependency
10. 创建不可变 Snapshot
11. 返回 Update Result
12. 再允许策略执行
```

策略不得在第 12 步之前执行。

## 11.2 失败策略

如果以下任一关键步骤失败：

* 基础 Bar 校验；
* 派生 Bar 聚合；
* 必需指标；
* Snapshot 构造；

则默认不调用策略。

生成明确错误结果和事件。

可选指标失败时可以：

* 在 Snapshot 标记缺失；
* 继续执行；
* 记录错误。

必须区分：

```text
REQUIRED
OPTIONAL
```

---

# 12. Bar Aggregation Manager

建议定义：

```text
OnlyBarAggregationManager
OnlyBarAggregationGraph
OnlyBarAggregator
OnlyTimeBarAggregator
OnlyTickBarAggregator
OnlyVolumeBarAggregator
OnlyNotionalBarAggregator
OnlyAggregationDependency
```

## 12.1 Runtime 级共享

Aggregator 属于 Runtime 级 MarketData Service。

不要让每个 Cluster 重复创建同一个派生 Bar Aggregator。

例如多个 Cluster 都订阅：

```text
510300.XSHG 3m
```

同一 Runtime 中只应存在一个对应聚合器。

可使用引用计数管理生命周期。

## 12.2 Runtime 隔离

不同 Runtime 不能共享可变聚合状态：

```text
Live Runtime Aggregator
Backtest Runtime Aggregator
```

必须独立。

## 12.3 依赖图

维护基础和派生 BarType 的依赖关系。

例如：

```text
1m external
├── 3m internal
├── 5m internal
└── 15m internal
```

必须检测：

* 循环依赖；
* 无基础数据源；
* 重复聚合器；
* 不兼容聚合链；
* 无法确定边界。

## 12.4 派生顺序

同一逻辑时间生成多个派生 Bar 时：

```text
dependency_level
    ↓
bar_duration
    ↓
stable_bar_type_id
```

用于内部稳定处理。

但策略在 `PRIMARY_ONLY` 模式下不会分别收到这些回调，而是通过 Snapshot 一次性读取。

---

# 13. Bar 边界

派生 Bar 不能简单根据 Unix Timestamp 取模。

必须结合：

```text
OnlyTradingCalendar
OnlyTradingSession
OnlyBarSpecification
```

例如 A 股 3 分钟 Bar：

```text
09:30-09:33
09:33-09:36
```

区间语义统一为：

```text
[start, end)
```

必须正确处理：

* A 股午休；
* 中国期货夜盘；
* 美股盘前盘后；
* DST；
* 提前收盘；
* 特殊 Session；
* 24x7 数字货币；
* Session 末尾不完整 Bar。

---

# 14. 不完整 Bar 策略

建议定义：

```text
OnlyIncompleteBarPolicy
```

至少包含：

```text
DROP
EMIT_PARTIAL
TRUNCATE_AT_SESSION_END
REJECT
```

禁止派生 Bar 无说明地跨 Session 拼接。

如果生成 Partial Bar，必须：

```text
is_partial = True
```

策略默认的：

```python
snapshot.latest_closed(...)
```

不得返回未关闭 Partial Bar。

---

# 15. 缺失数据策略

定义：

```text
OnlyMissingBarPolicy
```

至少考虑：

```text
REJECT
SKIP_WINDOW
EMIT_PARTIAL
INSERT_EMPTY
FILL_FORWARD
```

默认不建议自动填充。

必须区分：

```text
无成交
数据缺失
停牌
市场关闭
维护窗口
```

聚合器和 Snapshot 必须保留数据质量信息。

---

# 16. MarketData Cache

建议定义：

```text
OnlyMarketDataCache
OnlyBarCache
OnlyIndicatorCache
OnlyMarketDataVersion
```

内部 Cache：

* 可变；
* 由 Runtime 所有；
* 策略不可直接修改；
* 更新顺序由 Pipeline 控制。

至少支持：

```python
latest_closed(bar_type)
current_partial(bar_type)
history(bar_type, count)
version(bar_type)
```

策略不得直接持有可变 Cache 引用。

---

# 17. 不可变 Snapshot

必须定义：

```text
OnlyMarketDataSnapshot
OnlyBarSnapshot
OnlyIndicatorSnapshot
OnlyBarContext
```

Snapshot 必须：

* 不可变；
* 代表一个明确逻辑时间；
* 在整个策略回调期间保持一致；
* 可回放；
* 可序列化或生成可序列化 DTO；
* 不受后台更新影响；
* 只暴露策略已订阅数据。

Snapshot 至少包含：

```text
ts_event
ts_init
runtime_id
cluster_id
instrument_id
primary_bar_type
primary_bar
updated_bar_types
latest_closed_bars
partial_bars（仅显式允许）
indicator_values
data_versions
trading_day
session_type
quality_flags
```

建议 API：

```python
latest_closed(bar_type)
require_latest_closed(bar_type)
current_partial(bar_type)
was_updated(bar_type)
require_same_event_time(bar_type)
indicator(indicator_id)
require_indicator(indicator_id)
history(bar_type, count)
```

## 17.1 Latest Closed 语义

默认：

```text
latest_closed
```

只返回已经关闭的 Bar。

禁止返回正在形成的 Bar。

## 17.2 Updated This Slice

```python
snapshot.was_updated(bar_type)
```

表示该 BarType 是否在本次数据准备过程中生成或更新。

例如：

```text
09:31 updated = {1m}
09:32 updated = {1m}
09:33 updated = {1m, 3m}
```

## 17.3 Same Event Time

```python
snapshot.require_same_event_time(bar_type)
```

只允许读取：

```text
bar.end == primary_bar.end
```

否则抛出明确异常。

---

# 18. 指标 Pipeline

建议定义：

```text
OnlyIndicator
OnlyIndicatorId
OnlyIndicatorPipeline
OnlyIndicatorDependency
OnlyIndicatorUpdateResult
OnlyIndicatorRequirement
```

指标计算必须在策略回调前完成。

执行顺序：

```text
Bar Cache 更新
    ↓
计算受影响指标
    ↓
更新 Indicator Cache
    ↓
创建 Snapshot
```

## 18.1 共享指标

标准、确定、可共享指标可以由 Runtime 级 Pipeline 计算。

例如：

```text
MA
EMA
RSI
ATR
```

相同参数和数据源的指标可以复用。

## 18.2 策略私有指标

策略特有逻辑可以保留在 Cluster 内。

不要把所有策略状态都塞进全局 Indicator Pipeline。

## 18.3 Required 和 Optional

```text
REQUIRED
OPTIONAL
```

如果 REQUIRED 指标失败：

* 不调用策略；
* 返回 Pipeline 错误；
* 产生错误事实事件。

如果 OPTIONAL 指标失败：

* Snapshot 中标记缺失；
* 策略可以继续执行。

---

# 19. Strategy Bar Dispatcher

建议定义：

```text
OnlyStrategyBarDispatcher
OnlyBarDispatchPlan
OnlyClusterBarSubscription
OnlyBarDispatchResult
```

Dispatcher 负责：

* 判断某个 Cluster 是否应在当前 Update Result 中执行；
* 确定主周期；
* 生成该 Cluster 的受限 Snapshot；
* 调用一次 `on_bar`；
* 隔离 Cluster 异常；
* 记录执行结果。

## 19.1 默认主周期

时间 Bar 中：

```text
最小订阅周期
```

默认作为主周期。

## 19.2 显式覆盖

策略可以显式指定：

```text
primary_bar_type
```

显式配置优先于默认规则。

## 19.3 调用条件

只有当：

```text
primary_bar_type in updated_bar_types
```

时才调用该策略。

例如 A 策略：

```text
订阅 1m、3m
主周期 1m
```

每分钟调用。

B 策略：

```text
订阅 1m、3m
主周期 3m
```

每三分钟调用。

## 19.4 单次调用

在一个逻辑时间片中，同一个 Cluster 最多调用一次 `on_bar`。

即使当前同时更新：

```text
1m
3m
5m
15m
```

也只调用一次。

---

# 20. Cluster 回调接口

建议统一为：

```python
def on_bar(
    self,
    bar: OnlyBar,
    context: OnlyBarContext,
) -> None:
    ...
```

其中：

```text
bar
```

必须是该 Cluster 的主周期 Bar。

`OnlyBarContext` 至少提供：

```text
snapshot
clock_view
instrument_view
indicator_view
order_service（后续 Runtime 阶段接入）
```

当前阶段可以只实现市场数据相关只读能力。

示例：

```python
def on_bar(
    self,
    bar: OnlyBar,
    context: OnlyBarContext,
) -> None:
    bar_3m = context.snapshot.latest_closed(self.bar_type_3m)

    if context.snapshot.was_updated(self.bar_type_3m):
        self._refresh_three_minute_state(bar_3m)

    rsi_3m = context.snapshot.indicator(self.rsi_3m_id)
```

策略不得通过 Context 修改 Cache。

---

# 21. 同步数据准备屏障

本阶段必须实现明确的：

```text
OnlyDataReadyBarrier
```

它不一定需要是一个独立线程同步原语，也可以是 Pipeline 完成语义。

必须保证：

```text
所有派生 Bar 已完成
所有必需指标已完成
所有 Cache 已完成更新
Snapshot 已创建
```

之后才允许 Dispatcher 调用 Cluster。

不要实现为：

```text
线程 A 聚合 Bar
线程 B 计算指标
策略线程不断轮询 Cache
```

第一版使用同步、逻辑串行 Pipeline。

---

# 22. Clock 与 Event 的关系

Clock 不直接依赖 EventBus。

Timer 到期后，由后续 Runtime Timer Service 转换成：

```text
OnlyTimerFiredEvent
```

当前 MarketData Event 必须使用 Clock 提供：

```text
ts_init
```

基础 Bar 自带：

```text
ts_event
```

派生 Bar 推荐：

```text
bar_start
bar_end
ts_event = bar_end
ts_init = 创建派生 Bar 的 Clock UTC 时间
```

Snapshot 的 `ts_event` 应与主周期 Bar 结束时间一致。

---

# 23. Event 类型建议

本阶段至少定义：

```text
OnlyBarReceivedEvent
OnlyBarValidatedEvent
OnlyDerivedBarCreatedEvent
OnlyBarCacheUpdatedEvent
OnlyIndicatorUpdatedEvent
OnlyMarketDataSnapshotReadyEvent
OnlyMarketDataPipelineFailedEvent
OnlyClusterBarHandledEvent
OnlyClusterBarHandlerFailedEvent
```

注意：

不是所有内部步骤都必须发布到公共 EventBus。

例如：

```text
OnlyBarCacheUpdatedEvent
OnlyIndicatorUpdatedEvent
```

可以先作为内部可观测事件或调试事件。

不要为了“全事件化”让 Pipeline 失去明确顺序。

推荐：

* Pipeline 内使用直接接口调用；
* Pipeline 完成后发布关键事实；
* Strategy Dispatcher 使用明确接口调用 Cluster；
* Cluster 执行结果可以发布 Event。

---

# 24. 多 Cluster 处理

同一 Runtime 中多个 Cluster 可以订阅相同 Bar。

必须保证：

* Bar 聚合结果共享；
* Indicator 可按规范共享；
* 每个 Cluster 获得独立只读 Snapshot View；
* Cluster A 异常不影响 Cluster B；
* Cluster 之间不共享可变策略状态；
* 执行顺序稳定；
* 不承诺 Cluster 之间存在业务依赖。

同一 Snapshot 可以共享底层不可变数据，但 Cluster View 必须限制到已订阅范围。

---

# 25. 并发设计

第一版市场数据核心路径建议：

```text
单线程
逻辑串行
确定性
```

不允许：

* 聚合器后台线程和策略线程竞争 Cache；
* 指标线程尚未完成就执行策略；
* 回测和实盘使用不同顺序；
* Event Handler 在多个线程无序执行。

后续可以优化并发，但必须保留数据准备屏障和相同可见性语义。

---

# 26. 去重、乱序和迟到数据

MarketData Pipeline 至少要有明确策略：

```text
重复 Bar
乱序 Bar
迟到 Bar
修订 Bar
```

建议定义：

```text
OnlyMarketDataSequencePolicy
OnlyLateDataPolicy
OnlyBarRevisionPolicy
```

第一版可以：

* 重复 Bar：拒绝或幂等忽略；
* 早于最近处理时间的 Bar：默认拒绝；
* 修订 Bar：明确不支持或使用 revision；
* 不允许静默重写已经用于策略决策的数据。

回测重放必须得到同样结果。

---

# 27. 序列化与重放

以下对象必须支持无损序列化或稳定 DTO：

```text
OnlyEvent
OnlyBarSubscription
OnlyMarketDataUpdateResult
OnlyMarketDataSnapshot
OnlyBarDispatchResult
```

必须保持：

* Decimal；
* UTC 时间；
* BarType；
* InstrumentId；
* updated_bar_types；
* IndicatorId；
* data_versions；
* sequence；
* Runtime Scope。

提供重放测试：

```text
输入事件序列
    ↓
第一次执行
    ↓
保存
    ↓
重新加载
    ↓
第二次执行
```

两次：

```text
Snapshot
策略调用次数
调用时间
主 Bar
updated_bar_types
```

必须一致。

---

# 28. 建议目录

```text
src/onlyalpha/
├── event/
│   ├── base.py
│   ├── bus.py
│   ├── subscription.py
│   ├── scope.py
│   └── events/
├── market_data/
│   ├── pipeline.py
│   ├── cache.py
│   ├── snapshot.py
│   ├── subscriptions.py
│   ├── dispatcher.py
│   └── aggregation/
├── indicator/
│   ├── base.py
│   ├── pipeline.py
│   └── cache.py
└── cluster/
    └── bar_context.py
```

根据现有工程结构调整，但职责不能混合。

---

# 29. 必须新增的测试

建议创建：

```text
tests/event/
├── test_event_model.py
├── test_event_scope.py
├── test_event_bus_fifo.py
├── test_event_bus_subscriptions.py
├── test_event_bus_capacity.py
├── test_event_bus_errors.py
├── test_event_bus_close.py
└── test_event_replay.py

tests/market_data/
├── test_bar_subscription.py
├── test_primary_bar_selection.py
├── test_explicit_primary_bar.py
├── test_bar_aggregation_1m_to_3m.py
├── test_multiple_derived_bars.py
├── test_market_data_pipeline_order.py
├── test_snapshot_immutability.py
├── test_snapshot_latest_closed.py
├── test_snapshot_updated_this_slice.py
├── test_indicator_ready_barrier.py
├── test_required_indicator_failure.py
├── test_optional_indicator_failure.py
├── test_strategy_primary_only_delivery.py
├── test_multi_cluster_shared_aggregation.py
├── test_runtime_isolation.py
├── test_missing_bar_policy.py
├── test_incomplete_session_bar.py
├── test_duplicate_and_late_bar.py
├── test_replay_determinism.py
└── test_backtest_live_semantics.py
```

---

# 30. 核心验收场景

## 30.1 1m + 3m 默认主周期

策略订阅：

```text
1m
3m
```

未显式指定主周期。

输入：

```text
09:30-09:31 1m
09:31-09:32 1m
09:32-09:33 1m
```

期望：

```text
on_bar 调用 3 次
```

第三次 Snapshot：

```text
primary_bar = 09:32-09:33 1m
updated_bar_types = {1m, 3m}
latest_closed(3m) = 09:30-09:33
```

前两次：

```text
updated_bar_types = {1m}
latest_closed(3m) 可以为空或为之前已关闭 Bar
```

## 30.2 显式使用 3m 主周期

策略订阅：

```text
1m
3m
```

显式：

```text
primary_bar_type = 3m
```

输入三根 1m。

期望：

```text
只调用一次 on_bar
primary_bar = 09:30-09:33 3m
snapshot.latest_closed(1m) = 09:32-09:33
```

## 30.3 1m + 3m + 5m + 15m

在 09:45 同时关闭多个 Bar。

主周期为 1m 时：

```text
只调用一次
updated_bar_types = {1m, 3m, 5m, 15m}
```

Snapshot 中全部是当前时间点已完成的数据。

## 30.4 多 Cluster

Cluster A：

```text
订阅 1m、3m
主周期 1m
```

Cluster B：

```text
订阅 1m、3m
主周期 3m
```

输入三根 1m。

期望：

```text
A 调用 3 次
B 调用 1 次
```

两者共享同一 3m 聚合结果。

## 30.5 Snapshot 不可变

策略回调期间：

* Runtime 继续处理下一事件前，不得改变当前 Snapshot；
* 策略不能修改 Bar、Indicator 或 Snapshot；
* 修改行为必须失败。

## 30.6 指标准备

3m 指标依赖 3m Bar。

09:33 时必须保证：

```text
3m Bar 已更新
3m 指标已更新
之后才调用策略
```

---

# 31. Demo

创建：

```text
examples/event_market_data_demo/
├── README.md
├── primary_1m_demo.py
├── primary_3m_demo.py
├── multi_cluster_demo.py
└── replay_demo.py
```

示例输出：

```text
09:31
Cluster A on_bar primary=1m updated={1m}

09:32
Cluster A on_bar primary=1m updated={1m}

09:33
Cluster A on_bar primary=1m updated={1m,3m}
Cluster B on_bar primary=3m updated={1m,3m}
```

必须证明：

* 同一派生 Bar 不重复计算；
* 不同主周期策略可以共存；
* Snapshot 数据一致；
* 重放顺序一致。

---

# 32. 文档输出

创建或更新：

```text
docs/event.md
docs/market_data_pipeline.md
docs/bar_subscription.md
docs/runtime.md
docs/cluster.md
docs/testing.md
docs/architecture_principles.md
```

`docs/market_data_pipeline.md` 至少包含：

1. 基础 Bar 输入；
2. 聚合顺序；
3. Cache 更新；
4. Indicator 更新；
5. Data Ready Barrier；
6. Snapshot；
7. 主周期规则；
8. 多 Cluster；
9. 缺失数据；
10. Session 边界；
11. 重放；
12. 已知限制。

---

# 33. ADR

创建：

```text
docs/adr/0006-event-and-primary-bar-delivery.md
```

至少记录：

## 背景

多周期策略如果为每个周期分别回调，会产生回调顺序和数据一致性问题。

## 决策

* EventBus 传播事实；
* MarketData Pipeline 编排强顺序；
* 派生 Bar 在 Runtime 级共享生成；
* 策略默认由最小订阅周期驱动；
* 允许显式指定主周期；
* 主周期触发前完成派生 Bar、指标和 Cache 更新；
* 策略读取不可变 Snapshot；
* 一个逻辑时间片内每个 Cluster 最多调用一次；
* 默认只使用已关闭 Bar；
* 第一版核心路径同步串行。

## 拒绝方案

* 不同周期分别无条件回调；
* 使用注册顺序控制多周期逻辑；
* 后台线程持续聚合并让策略直接读可变 Cache；
* 每个 Cluster 独立聚合；
* 全部步骤通过 EventBus 订阅优先级控制。

---

# 34. Architecture Principles 新增规则

加入：

```text
Rule: Event 只表达已经发生的事实。

Rule: EventBus 不承担强业务顺序。

Rule: MarketData Pipeline 必须在策略执行前完成数据准备。

Rule: 默认最小订阅时间周期为主周期。

Rule: 非时间 Bar 无法比较时必须显式指定主周期。

Rule: 策略可以显式覆盖主周期。

Rule: 一个逻辑时间片内一个 Cluster 最多执行一次主 Bar 回调。

Rule: 策略读取不可变 Snapshot，不直接读取可变全局 Cache。

Rule: 策略默认只能读取已关闭 Bar。

Rule: 派生 Bar 在 Runtime 级共享，不在 Cluster 内重复生成。

Rule: 指标强依赖必须在策略执行前完成。

Rule: 回测与实盘必须使用相同的数据准备顺序。
```

---

# 35. 实现顺序

严格按以下顺序：

1. 扫描当前 Event 和 MarketData 实现；
2. 创建差距分析；
3. 完成 Event 基础类型；
4. 实现同步 FIFO EventBus；
5. 完成 EventBus 测试；
6. 定义 Bar Subscription；
7. 实现主周期选择；
8. 实现 MarketData Cache；
9. 实现不可变 Snapshot；
10. 实现 1m → 3m Time Bar Aggregator；
11. 实现 Aggregation Manager；
12. 实现 Indicator Pipeline 最小接口；
13. 实现 Data Ready Barrier；
14. 实现 Strategy Bar Dispatcher；
15. 完成多 Cluster 场景；
16. 完成重放测试；
17. 创建 Demo；
18. 更新文档；
19. 创建 ADR；
20. 运行全部测试；
21. 输出验收报告。

不要一次性实现所有 Bar 类型。

第一版先完整支持：

```text
时间 Bar
1m 基础 Bar
3m / 5m / 15m 派生 Bar
```

但接口要预留 Tick、Volume 和 Notional Bar。

---

# 36. 验收标准

完成后必须满足：

* Event 使用统一 UTC 时间语义；
* EventBus 同步、FIFO、有界、确定；
* Event Scope 可以隔离 Runtime；
* EventBus 不承担 MarketData 强顺序；
* 最小时间周期可以自动成为主周期；
* 可以显式覆盖主周期；
* 非时间 Bar 无法比较时要求显式主周期；
* 派生 Bar 在 Runtime 级共享生成；
* 策略执行前完成 Bar 聚合；
* 策略执行前完成 Required Indicator；
* Snapshot 不可变；
* Snapshot 默认只返回已关闭 Bar；
* `was_updated()` 语义正确；
* 同一逻辑时间每个 Cluster 最多调用一次；
* 多 Cluster 可以使用不同主周期；
* 多 Cluster 共享聚合结果；
* 回测和实盘的数据准备顺序一致；
* 相同输入重放结果一致；
* 不使用后台线程竞争 Cache；
* 不依赖注册顺序决定业务结果；
* 文档、测试、Demo 和 ADR 完整。

---

# 37. 一票否决项

存在以下任一项，不得标记完成：

* 策略直接读取可变全局 Cache；
* 派生 Bar 在后台线程未完成时策略已经执行；
* 指标未完成时策略已经执行；
* 1m 和 3m 分别回调且依赖全局固定顺序；
* 使用订阅注册顺序决定多周期业务逻辑；
* 每个 Cluster 重复创建相同 Aggregator；
* 回测和实盘使用不同 Pipeline 顺序；
* EventBus 订阅优先级承担订单或 MarketData 事务；
* Snapshot 返回正在形成的 Bar 却没有明确标记；
* Runtime 之间共享可变聚合状态；
* 相同输入重放结果不同；
* 一个时间片内同一 Cluster 被重复调用；
* 非时间 Bar 自动主周期选择含义不明确；
* Event 或 Snapshot 丢失时间精度；
* 队列满时静默丢弃核心事件。

---

# 38. 最终交付报告

完成后必须输出：

```text
新增文件
修改文件
Event Model 设计
Event Scope 设计
EventBus 队列和顺序策略
Bar Subscription API
默认主周期选择规则
显式主周期覆盖规则
MarketData Pipeline 顺序
Aggregation Manager 设计
Indicator Ready Barrier
Snapshot 设计
Cluster 调用语义
多 Cluster 共享情况
测试通过数
测试失败数
测试跳过数
重放测试结果
已知限制
一票否决项
是否建议进入 RuntimeContext
是否建议进入 Cluster 生命周期
是否建议进入 Backtest MVP
```

最终结论：

```text
ACCEPTED
CONDITIONALLY_ACCEPTED
REJECTED
```

当前任务只实现：

```text
Event Model
EventBus
Bar Subscription
MarketData Pipeline
Bar Aggregation
Indicator 准备接口
Snapshot
Strategy Bar Dispatcher
测试
Demo
文档
ADR
```

不要在本任务中实现：

* 完整 Runtime；
* 真实 Gateway；
* 订单撮合；
* Position；
* Account；
* Web；
* 分布式 EventBus；
* 多线程市场数据 Pipeline；
* 真实交易。
