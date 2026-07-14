# OnlyAlpha RuntimeContext、Runtime 与 Cluster 受控运行环境构建任务

## 1. 任务目标

现在开始构建 OnlyAlpha 的 RuntimeContext 组件，将已经存在或已经达到预期的以下组件组装成一个真正可运行、可隔离、可测试、可重放的策略运行环境：

```text
OnlyClock
OnlyEventBus
OnlyMarketDataPipeline
OnlyMarketDataCache
OnlyMarketDataSnapshot
OnlyStrategyBarDispatcher
OnlyCluster
```

本任务的最终目标是实现：

```text
OnlyRuntime
    ├── 独立 OnlyClock
    ├── 独立 OnlyRuntimeEventBus
    ├── 独立 OnlyMarketDataPipeline
    ├── 独立 OnlyMarketDataCache
    ├── 独立 Bar Aggregation 状态
    ├── 独立 Indicator 状态
    ├── 多个相互隔离的 OnlyCluster
    └── OnlyRuntimeContext
```

Cluster 必须通过受限的 `OnlyRuntimeContext` 使用 Runtime 能力。

Cluster 不得直接访问：

* Clock 的时间推进接口；
* EventBus 的底层队列；
* 可变 MarketData Cache；
* Bar Aggregator；
* Indicator Pipeline 内部状态；
* Gateway；
* Engine；
* Storage 实现；
* 其他 Cluster 内部状态。

本阶段需要打通以下最小运行闭环：

```text
OnlyBacktestClock 推进
    ↓
Runtime 接收基础 1m Bar
    ↓
OnlyMarketDataPipeline
    ↓
生成派生 3m Bar
    ↓
更新指标
    ↓
创建不可变 Snapshot
    ↓
OnlyStrategyBarDispatcher
    ↓
OnlyDemoCluster.on_bar(primary_bar, context)
```

策略订阅：

```text
1m
3m
```

默认主周期：

```text
1m
```

输入三根 1m Bar 后，期望：

```text
09:31 on_bar updated={1m}
09:32 on_bar updated={1m}
09:33 on_bar updated={1m,3m}
```

第三次回调中，Cluster 必须能够从 Context 的 Snapshot 中读取刚关闭的 3m Bar。

当前任务只建立运行环境和生命周期，不实现完整下单、撮合、持仓、账户或真实 Gateway。

---

# 2. 核心设计原则

必须遵循：

```text
Runtime 拥有运行资源
Context 只暴露受限能力
Cluster 只依赖 Context
Clock、EventBus、Cache 和 Pipeline 不跨 Runtime 共享可变状态
策略回调前数据必须完全准备
同一输入必须得到确定性结果
生命周期必须由 Manager 控制
```

更明确地说：

```text
Runtime 是资源所有者
RuntimeContext 是能力门面
Cluster 是受控执行单元
Snapshot 是一致性只读数据视图
Manager 是生命周期编排者
```

---

# 3. 执行前必须阅读

开始实现前必须阅读：

```text
AGENTS.md
docs/architecture.md
docs/domain_model.md
docs/time_model.md
docs/clock.md
docs/event.md
docs/market_data_pipeline.md
docs/bar_subscription.md
docs/cluster.md
docs/runtime.md
docs/concurrency.md
docs/coding_style.md
docs/testing.md
docs/architecture_principles.md
docs/adr/
```

重点检查当前已有实现：

```text
OnlyClock
OnlyClockView
OnlyControllableClock
OnlyLiveClock
OnlyBacktestClock
OnlyVirtualClock

OnlyEvent
OnlyEventBus
OnlyRuntimeEventBus

OnlyMarketDataPipeline
OnlyMarketDataCache
OnlyMarketDataSnapshot
OnlyBarContext
OnlyBarAggregationManager
OnlyIndicatorPipeline
OnlyStrategyBarDispatcher

OnlyCluster
OnlyBarSubscription
```

同时分析 MyQuant：

```text
https://github.com/zongxin1993/MyQuant
```

重点参考：

* 策略初始化过程；
* 策略对象如何获得服务；
* 实盘和回测上下文差异；
* 策略生命周期；
* 多策略运行；
* 异常处理；
* 停止和资源回收。

只参考行为，不复制旧架构。

---

# 4. 先创建差距分析

创建：

```text
docs/runtime_context_analysis.md
```

至少记录：

## 4.1 当前组件状态

| 组件 | 当前实现 | 可否复用 | 风险 | 本次调整 |
| -- | ---- | ---- | -- | ---- |

至少分析：

* Clock；
* EventBus；
* MarketData Pipeline；
* Cache；
* Snapshot；
* Dispatcher；
* Cluster；
* Config；
* Logger。

## 4.2 当前依赖问题

检查是否存在：

* Cluster 直接持有 EventBus；
* Cluster 直接持有可变 Cache；
* Cluster 直接持有具体 BacktestClock；
* Cluster 可以调用 `advance_to()`；
* Cluster 直接访问 Aggregator；
* Cluster 直接调用 Gateway；
* Runtime 之间共享 Cache；
* Runtime 之间共享 Clock；
* Runtime 之间共享聚合器；
* Cluster 自行修改生命周期；
* 生命周期依赖布尔变量而不是状态机；
* Cluster 停止后仍接收数据；
* Runtime 停止时资源未释放；
* Context 暴露内部可变对象；
* Context 逐渐变成无边界 Service Locator。

## 4.3 当前运行链路

画出当前：

```text
Bar 输入
→ Pipeline
→ Snapshot
→ Dispatcher
→ Cluster
```

并指出生命周期、Scope 和错误隔离缺口。

先完成分析，再开始修改。

---

# 5. 建议新增或完善的核心类型

至少实现或完善：

```text
OnlyRuntime
OnlyRuntimeContext
OnlyRuntimeContextView
OnlyRuntimeConfig
OnlyRuntimeId
OnlyRuntimeMode
OnlyRuntimeState
OnlyRuntimeError
OnlyRuntimeLifecycleError
OnlyRuntimeManager
OnlyRuntimeServices

OnlyCluster
OnlyClusterContext
OnlyClusterConfig
OnlyClusterId
OnlyClusterState
OnlyClusterError
OnlyClusterLifecycleError
OnlyClusterManager
OnlyClusterRegistry
OnlyClusterLoader
OnlyClusterExecutionResult

OnlyClockView
OnlyMarketDataView
OnlyInstrumentView
OnlySubscriptionService
OnlyTimerService
OnlyRuntimeLogger
```

可根据现有工程命名调整，但所有自定义类型必须以 `Only` 开头。

---

# 6. Runtime 职责

`OnlyRuntime` 是一个独立运行环境的资源所有者。

负责拥有和管理：

* RuntimeId；
* Runtime Mode；
* Runtime State；
* Clock；
* Runtime EventBus；
* MarketData Pipeline；
* MarketData Cache；
* Bar Aggregation Manager；
* Indicator Pipeline；
* Strategy Dispatcher；
* Cluster Manager；
* Subscription Service；
* Timer Service；
* Logger；
* 后续扩展的 OrderService、AccountQuery、PositionQuery。

Runtime 不负责：

* 具体策略逻辑；
* 具体交易所规则；
* 具体券商 SDK；
* Web 请求处理；
* 具体数据库 SQL；
* Engine 全局管理。

---

# 7. Runtime 类型

至少预留：

```text
OnlyRuntime
OnlyLiveRuntime
OnlyPaperRuntime
OnlyBacktestRuntime
OnlyResearchRuntime
```

当前阶段重点实现：

```text
OnlyBacktestRuntime
```

可为其他 Runtime 建立接口、配置和最小骨架，但不要实现真实交易。

## 7.1 Backtest Runtime

必须：

* 拥有独立 `OnlyBacktestClock`；
* 不读取系统当前时间；
* 显式接收输入 Bar；
* 显式推进 Clock；
* 同步执行 MarketData Pipeline；
* 同步创建 Snapshot；
* 同步分发 Cluster；
* 不创建后台线程；
* 相同输入确定性执行。

## 7.2 Live/Paper Runtime

本阶段只需保留扩展点，明确它们未来使用：

```text
OnlyLiveClock
实时数据输入
相同 MarketData Pipeline
相同 Strategy Dispatcher
相同 Cluster 接口
```

不得为 Live 和 Backtest 建立两套 Cluster API。

---

# 8. Runtime 生命周期

建议状态：

```text
CREATED
INITIALIZING
READY
STARTING
RUNNING
PAUSING
PAUSED
STOPPING
STOPPED
FAILED
CLOSED
```

如果当前工程希望减少状态，可以适当精简，但至少要区分：

```text
CREATED
READY
RUNNING
STOPPING
STOPPED
FAILED
CLOSED
```

必须定义合法状态迁移。

例如：

```text
CREATED → INITIALIZING → READY
READY → STARTING → RUNNING
RUNNING → PAUSED → RUNNING
RUNNING → STOPPING → STOPPED
STOPPED → CLOSED
任意活动状态 → FAILED
FAILED → STOPPING 或 CLOSED
```

非法迁移必须抛出：

```text
OnlyRuntimeLifecycleError
```

禁止通过多个布尔值表示生命周期：

```python
is_running
is_stopped
is_failed
```

状态必须有唯一来源。

---

# 9. Runtime 基础接口

建议：

```python
class OnlyRuntime(ABC):
    @property
    def runtime_id(self) -> OnlyRuntimeId:
        ...

    @property
    def mode(self) -> OnlyRuntimeMode:
        ...

    @property
    def state(self) -> OnlyRuntimeState:
        ...

    def initialize(self) -> None:
        ...

    def start(self) -> None:
        ...

    def pause(self) -> None:
        ...

    def resume(self) -> None:
        ...

    def stop(self) -> None:
        ...

    def close(self) -> None:
        ...

    def add_cluster(self, cluster: OnlyCluster) -> None:
        ...

    def remove_cluster(self, cluster_id: OnlyClusterId) -> None:
        ...

    def process_bar(self, bar: OnlyBar) -> OnlyRuntimeProcessResult:
        ...

    def get_status(self) -> OnlyRuntimeStatus:
        ...
```

具体签名应结合已有代码调整。

`process_bar()` 第一版只用于 Backtest/Paper 等明确输入模式。

Live Runtime 未来可由 Market Gateway Adapter 调用相同内部处理接口。

---

# 10. RuntimeContext 设计

`OnlyRuntimeContext` 是 Cluster 使用 Runtime 能力的唯一入口。

它必须是一个受控门面，不是直接暴露所有内部组件的 Service Locator。

建议对 Cluster 暴露：

```text
clock
market_data
instruments
subscriptions
timers
logger
runtime_info
```

后续再增加：

```text
orders
positions
accounts
cache_view
```

本阶段不实现完整交易服务。

建议接口：

```python
class OnlyRuntimeContext:
    @property
    def clock(self) -> OnlyClockView:
        ...

    @property
    def market_data(self) -> OnlyMarketDataView:
        ...

    @property
    def instruments(self) -> OnlyInstrumentView:
        ...

    @property
    def subscriptions(self) -> OnlySubscriptionService:
        ...

    @property
    def timers(self) -> OnlyTimerService:
        ...

    @property
    def logger(self) -> OnlyRuntimeLogger:
        ...

    @property
    def runtime_id(self) -> OnlyRuntimeId:
        ...

    @property
    def runtime_mode(self) -> OnlyRuntimeMode:
        ...
```

---

# 11. RuntimeContext 权限边界

## 11.1 Clock

Cluster 只能获得：

```text
OnlyClockView
```

允许：

```python
now_utc()
timestamp_ns()
schedule_at()
schedule_after()
schedule_every()
cancel_timer()
```

禁止：

```python
advance_to()
advance_by()
set_time()
restore_snapshot()
```

推进时间的接口只能由 Backtest Runtime 使用。

## 11.2 Market Data

Cluster 只能获得只读：

```text
OnlyMarketDataView
```

允许：

```python
latest_closed(bar_type)
history(bar_type, count)
latest_indicator(indicator_id)
current_snapshot()
```

禁止：

* 更新 Cache；
* 插入 Bar；
* 直接访问 Aggregator；
* 修改 Indicator 状态；
* 获取其他 Runtime 数据。

在 `on_bar` 中，应优先使用本次回调传入的 Snapshot，而不是重新查询全局当前状态。

## 11.3 EventBus

Cluster 默认不直接获得完整 EventBus。

Cluster 可以获得受限事件能力，例如：

```text
OnlyClusterEventPublisher
OnlyClusterEventSubscriptionView
```

本阶段甚至可以不暴露 EventBus，只由 Runtime Dispatcher 调用 Cluster。

如果必须允许 Cluster 发布自定义事实事件：

* 自动填充 runtime_id；
* 自动填充 cluster_id；
* 禁止伪造其他 Scope；
* 不能直接操作底层队列；
* 不能关闭 EventBus；
* 不能清空队列。

## 11.4 Logger

Logger 自动绑定：

```text
runtime_id
cluster_id
mode
```

Cluster 不应自行创建无上下文全局 Logger。

---

# 12. RuntimeServices

可以定义内部聚合类型：

```text
OnlyRuntimeServices
```

用于 Runtime 内部持有组件：

```text
clock
event_bus
market_data_pipeline
market_data_cache
aggregation_manager
indicator_pipeline
strategy_dispatcher
subscription_service
timer_service
instrument_registry
logger
```

但不得把 `OnlyRuntimeServices` 原样暴露给 Cluster。

RuntimeContext 应只暴露受限 View 或 Protocol。

---

# 13. Cluster 设计

建议定义：

```text
OnlyCluster
OnlyClusterConfig
OnlyClusterContext
OnlyClusterState
OnlyClusterMetadata
```

Cluster 表示独立策略实例。

必须包含：

```text
cluster_id
name
version
config
state
subscriptions
metadata
```

Cluster 不得包含 Runtime 的内部资源所有权。

---

# 14. Cluster 生命周期

建议状态：

```text
CREATED
LOADED
INITIALIZING
INITIALIZED
STARTING
RUNNING
PAUSING
PAUSED
STOPPING
STOPPED
FAILED
UNLOADING
UNLOADED
```

可以适当简化，但必须具备明确状态机。

建议回调：

```python
on_load()
on_initialize(context)
on_start()
on_bar(bar, context)
on_timer(event, context)
on_pause()
on_resume()
on_stop()
on_unload()
on_error(error, context)
```

生命周期回调由 `OnlyClusterManager` 调用。

Cluster 自己不得：

* 修改 state；
* 调用自己的 start/stop；
* 绕过 Manager；
* 在 CREATED 状态接收 Bar；
* 在 STOPPED 状态继续执行策略。

---

# 15. ClusterManager

`OnlyClusterManager` 负责：

* 注册 Cluster；
* 加载 Cluster；
* 初始化；
* 启动；
* 暂停；
* 恢复；
* 停止；
* 卸载；
* 状态转换；
* 异常隔离；
* Context 创建；
* Subscription 注册；
* Dispatcher 绑定；
* 资源释放。

建议接口：

```python
register(cluster)
load(cluster_id)
initialize(cluster_id)
start(cluster_id)
pause(cluster_id)
resume(cluster_id)
stop(cluster_id)
unload(cluster_id)
get(cluster_id)
list_clusters()
get_status(cluster_id)
```

## 15.1 状态所有权

只有 ClusterManager 可以修改 Cluster State。

Cluster 回调只返回结果或抛出异常。

## 15.2 异常隔离

Cluster A 抛出异常时：

* 捕获异常；
* 将 A 标记为 FAILED；
* 停止向 A 分发新数据；
* 记录 Runtime/Cluster/Bar/Event 上下文；
* 不影响 Cluster B；
* 根据配置决定是否调用 `on_error()`；
* 不自动无限重启。

---

# 16. ClusterRegistry 与 Loader

本阶段至少提供最小能力：

```text
OnlyClusterRegistry
OnlyClusterLoader
```

## 16.1 静态注册

```python
registry.register(
    name="demo",
    cluster_type=OnlyDemoCluster,
)
```

检查：

* 类型；
* Only 前缀约束；
* 重复名称；
* 元数据；
* 配置类型。

## 16.2 动态加载

第一版可以支持：

```text
Python module path
class name
```

例如：

```yaml
cluster:
  id: demo_001
  module: examples.demo_cluster
  class: OnlyDemoCluster
```

必须：

* 校验是否继承或实现 `OnlyCluster`；
* 校验类名；
* 捕获 ImportError；
* 返回明确错误；
* 不污染其他 Runtime；
* 卸载时释放订阅和 Timer。

不要在 Runtime 主类中直接写复杂 importlib 逻辑。

---

# 17. Bar 订阅注册

Cluster 在初始化阶段声明订阅。

推荐方式之一：

```python
def on_initialize(self, context: OnlyClusterContext) -> None:
    context.subscriptions.subscribe_bars(
        cluster_id=self.cluster_id,
        bar_types=[
            self.bar_type_1m,
            self.bar_type_3m,
        ],
        primary_bar_type=None,
        delivery_mode=OnlyBarDeliveryMode.PRIMARY_ONLY,
    )
```

也可以让 ClusterConfig 提前声明。

必须明确：

* 订阅只能在允许生命周期阶段新增；
* Running 后是否允许动态修改需要明确；
* 停止/卸载时自动取消；
* 默认最小时间周期为主周期；
* 可以显式覆盖；
* 非时间 Bar 必须显式指定主周期；
* Cluster 只能看到已订阅数据。

---

# 18. Runtime 与 MarketData Pipeline 集成

Backtest Runtime 的 `process_bar()` 必须按以下固定顺序：

```text
1. 检查 Runtime State == RUNNING
2. 校验输入 Bar Scope 和 Instrument
3. 将 Backtest Clock 推进到 Bar ts_event
4. 处理在该时间前到期的 Timer
5. 调用 MarketData Pipeline
6. 获得 OnlyMarketDataUpdateResult
7. 发布必要 Runtime 事实事件
8. Strategy Dispatcher 选择本次需要执行的 Cluster
9. 为每个 Cluster 创建受限 OnlyBarContext
10. 调用 ClusterManager 执行 on_bar
11. 收集执行结果
12. 返回 OnlyRuntimeProcessResult
```

必须明确 Clock 与 Bar 的推进顺序。

推荐：

> 先让 Clock 到达 Bar 的事件时间，再执行该 Bar 对应 Pipeline。

这样策略 `on_bar` 看到的 Runtime Clock 与主 Bar `ts_event` 一致。

---

# 19. Timer 与 Cluster 集成

Clock 不直接依赖 Cluster。

建议：

```text
Cluster 注册 Timer
    ↓
OnlyTimerService
    ↓
Runtime Clock
    ↓
Timer 到期
    ↓
Runtime 创建 OnlyTimerFiredEvent
    ↓
ClusterManager 调用目标 Cluster.on_timer()
```

Timer 必须自动绑定：

```text
runtime_id
cluster_id
timer_id
```

Cluster 停止或卸载时：

* 自动取消其 Timer；
* 不再接收 Timer 回调。

Backtest Runtime 推进 Bar 时间时，必须先触发在该时间前或该时间点到期的 Timer。

需要明确同一时间点 Timer 和 Bar 的顺序。

建议第一版规则：

```text
deadline < bar.ts_event 的 Timer
    先触发

deadline == bar.ts_event 的 Timer
    默认先触发 Timer，再处理 Bar
```

或者选择 Bar 优先，但必须全工程固定，并写入 ADR。

推荐使用：

```text
Timer 先于同时间 Bar
```

理由：

* Clock 先推进到逻辑时间；
* 到期 Timer 是该时间点需要先处理的调度事实；
* 然后再输入市场数据。

但如果现有设计已有相反约定，可保留，只要明确、确定、回测与实盘一致。

---

# 20. Strategy Dispatcher 与 ClusterManager 边界

`OnlyStrategyBarDispatcher` 负责确定：

* 哪些 Cluster 本次应执行；
* 每个 Cluster 的 Primary Bar；
* 每个 Cluster 的 Snapshot View。

`OnlyClusterManager` 负责实际执行：

```python
execute_bar(
    cluster_id,
    bar,
    context,
) -> OnlyClusterExecutionResult
```

Dispatcher 不直接修改 Cluster State。

ClusterManager 不负责 Bar 聚合或 Snapshot 选择。

建议流程：

```text
Dispatcher 创建 Dispatch Plan
    ↓
ClusterManager 执行 Plan
    ↓
收集 Result
```

---

# 21. OnlyBarContext

策略回调上下文建议定义为：

```text
OnlyBarContext
```

包含：

```text
runtime_context_view
snapshot
primary_bar
updated_bar_types
clock_view
instrument_view
logger
```

本阶段可以暂不加入 OrderService。

建议：

```python
class OnlyBarContext:
    @property
    def snapshot(self) -> OnlyMarketDataSnapshot:
        ...

    @property
    def clock(self) -> OnlyClockView:
        ...

    @property
    def instruments(self) -> OnlyInstrumentView:
        ...

    @property
    def logger(self) -> OnlyRuntimeLogger:
        ...
```

Context 必须不可变或只读。

---

# 22. Context 生命周期

不要把同一个可变 Context 永久复用于所有回调。

建议区分：

```text
OnlyRuntimeContext
    Runtime 生命周期级能力门面

OnlyClusterContext
    Cluster 生命周期级上下文

OnlyBarContext
    单次 Bar 回调级一致性上下文

OnlyTimerContext
    单次 Timer 回调上下文
```

其中：

* RuntimeContext：长期存在；
* ClusterContext：绑定 cluster_id；
* BarContext：绑定本次 Snapshot；
* TimerContext：绑定本次 Timer Event。

这样可以避免长期 Context 中携带过期 Snapshot。

---

# 23. Scope 与隔离

必须保证：

## 23.1 Runtime 隔离

两个 Runtime 即使具有相同：

```text
instrument_id
cluster_id 名称
bar_type
```

也不能共享：

* Clock；
* EventBus；
* Cache；
* Aggregator；
* Indicator 状态；
* Subscription；
* Timer；
* Snapshot。

## 23.2 Cluster 隔离

两个 Cluster：

* 不共享策略可变状态；
* 不直接引用对方；
* 不读对方私有 Snapshot View；
* 不取消对方 Timer；
* 不发布伪造 cluster_id 的事件；
* 一个失败不影响另一个。

---

# 24. Runtime 配置

建议定义：

```text
OnlyRuntimeConfig
```

至少包含：

```text
runtime_id
mode
event_queue_capacity
clock_config
market_data_config
cluster_configs
error_policy
timer_order_policy
shutdown_timeout
```

本阶段配置不得包含真实账户密钥。

## 24.1 错误策略

建议：

```text
OnlyRuntimeErrorPolicy
```

至少考虑：

```text
FAIL_CLUSTER
FAIL_RUNTIME
CONTINUE
```

默认：

* Cluster 回调异常：FAIL_CLUSTER；
* MarketData Pipeline 核心失败：FAIL_RUNTIME 或返回失败；
* Snapshot 构造失败：不执行策略；
* 可选指标失败：根据配置继续。

---

# 25. 启动顺序

Runtime 初始化建议：

```text
1. 校验 Config
2. 创建 Runtime 资源
3. 初始化 Clock
4. 初始化 EventBus
5. 初始化 Instrument View
6. 初始化 Cache
7. 初始化 Aggregator
8. 初始化 Indicator Pipeline
9. 初始化 MarketData Pipeline
10. 初始化 Subscription Service
11. 初始化 Dispatcher
12. 初始化 ClusterManager
13. 加载 Cluster
14. 初始化 Cluster
15. Runtime 进入 READY
```

Runtime 启动：

```text
1. 启动 Clock（如果需要）
2. 启动 EventBus（如果需要）
3. 启动 Cluster
4. Runtime 进入 RUNNING
5. 发布 OnlyRuntimeStartedEvent
```

Backtest Runtime 不应启动后台线程。

---

# 26. 停止和关闭顺序

停止建议：

```text
1. Runtime 进入 STOPPING
2. 拒绝新的 Bar 输入
3. 停止向 Cluster 分发
4. 停止 Cluster
5. 取消 Cluster Timer
6. 清空或处理 EventBus 队列
7. 刷新必要状态
8. Runtime 进入 STOPPED
```

关闭建议：

```text
1. 卸载 Cluster
2. 关闭 Dispatcher
3. 关闭 Pipeline
4. 关闭 EventBus
5. 关闭 Clock
6. 释放 Cache 和内部资源
7. Runtime 进入 CLOSED
```

`stop()` 和 `close()` 必须幂等。

---

# 27. Runtime 状态查询

建议定义：

```text
OnlyRuntimeStatus
OnlyClusterStatus
```

Runtime Status 至少包含：

```text
runtime_id
mode
state
clock_time
cluster_count
running_cluster_count
failed_cluster_count
event_queue_size
active_timer_count
subscription_count
last_error
```

状态对象必须是 Snapshot/DTO，不直接暴露内部可变资源。

---

# 28. 最小 Demo Cluster

创建：

```text
OnlyDemoCluster
```

订阅：

```text
1m
3m
```

默认主周期：

```text
1m
```

回调：

```python
def on_bar(
    self,
    bar: OnlyBar,
    context: OnlyBarContext,
) -> None:
    latest_3m = context.snapshot.latest_closed(self.bar_type_3m)

    self.records.append(
        OnlyDemoRecord(
            ts_event=bar.ts_event,
            primary_bar_type=bar.bar_type,
            updated_bar_types=context.snapshot.updated_bar_types,
            latest_3m=latest_3m,
        )
    )
```

Demo Cluster 不下单。

---

# 29. 最小 Backtest Runtime Demo

创建：

```text
examples/runtime_context_demo/
├── README.md
├── basic_runtime_demo.py
├── multi_cluster_demo.py
├── runtime_isolation_demo.py
└── cluster_failure_demo.py
```

## 29.1 Basic Demo

创建：

* 一个 Backtest Runtime；
* 一个 Demo Cluster；
* 一个 1m 基础 Bar；
* 一个 3m 派生订阅。

输入三根 1m Bar。

输出：

```text
Runtime: backtest_001
Cluster: demo_001

09:31 on_bar primary=1m updated={1m}
09:32 on_bar primary=1m updated={1m}
09:33 on_bar primary=1m updated={1m,3m}
latest_3m=09:30-09:33
```

## 29.2 Multi Cluster Demo

Cluster A：

```text
主周期 1m
```

Cluster B：

```text
主周期 3m
```

输入三根 1m Bar。

期望：

```text
A 调用 3 次
B 调用 1 次
共享同一个 3m 聚合结果
```

## 29.3 Runtime Isolation Demo

创建两个 Backtest Runtime。

输入不同 Bar。

验证：

* Clock 独立；
* Cache 独立；
* Cluster 记录独立；
* Event Scope 独立；
* Aggregator 状态独立。

## 29.4 Cluster Failure Demo

Cluster A 在第二次回调抛异常。

Cluster B 正常运行。

期望：

```text
A → FAILED
B → RUNNING
Runtime → RUNNING
A 不再接收后续 Bar
B 继续接收
```

---

# 30. 必须新增的测试

建议：

```text
tests/runtime/
├── test_runtime_state_machine.py
├── test_runtime_initialization.py
├── test_runtime_start_stop_close.py
├── test_runtime_context_permissions.py
├── test_runtime_clock_ownership.py
├── test_runtime_event_scope.py
├── test_runtime_market_data_flow.py
├── test_runtime_process_bar_order.py
├── test_runtime_timer_order.py
├── test_runtime_isolation.py
├── test_runtime_determinism.py
├── test_runtime_status.py
└── test_runtime_error_policy.py

tests/cluster/
├── test_cluster_state_machine.py
├── test_cluster_manager.py
├── test_cluster_context_permissions.py
├── test_cluster_bar_subscription.py
├── test_cluster_primary_bar_delivery.py
├── test_cluster_stop_delivery.py
├── test_cluster_failure_isolation.py
├── test_cluster_timer_cleanup.py
├── test_cluster_registry.py
├── test_cluster_loader.py
└── test_multi_cluster.py

tests/integration/
├── test_backtest_runtime_1m_3m.py
├── test_backtest_runtime_explicit_3m_primary.py
├── test_two_runtimes_isolated.py
├── test_cluster_failure_does_not_stop_runtime.py
└── test_runtime_replay_determinism.py
```

---

# 31. 核心验收场景

## 31.1 生命周期

验证：

```text
Runtime:
CREATED → READY → RUNNING → STOPPED → CLOSED

Cluster:
CREATED → LOADED → INITIALIZED → RUNNING → STOPPED → UNLOADED
```

非法迁移失败。

## 31.2 Context 权限

测试 Cluster 无法：

* 推进 Clock；
* 关闭 EventBus；
* 修改 Cache；
* 修改 Snapshot；
* 访问 Aggregator；
* 访问其他 Runtime；
* 伪造其他 Cluster Scope。

## 31.3 1m + 3m

输入三根 1m：

```text
Cluster 调用 3 次
第三次 updated={1m,3m}
```

## 31.4 显式 3m 主周期

输入三根 1m：

```text
Cluster 调用 1 次
primary=3m
latest_closed(1m)=第三根 1m
```

## 31.5 Cluster 停止

Cluster 停止后：

* 不再接收 Bar；
* Timer 被取消；
* Subscription 被释放；
* Cache 仍由 Runtime 管理；
* 其他 Cluster 不受影响。

## 31.6 Cluster 异常

A 异常：

* A 标记 FAILED；
* B 继续；
* Runtime 默认继续；
* 错误包含 runtime_id、cluster_id、ts_event、bar_type。

## 31.7 Runtime 隔离

两个 Runtime 输入相同 Instrument 的不同数据。

不得相互读取。

## 31.8 确定性

同一配置、同一初始 Clock、同一输入 Bar 重复执行 100 次：

* Cluster 调用次数一致；
* 调用顺序一致；
* Snapshot 一致；
* Clock 一致；
* 派生 Bar 一致；
* Event Sequence 一致。

---

# 32. 直接依赖扫描

增加静态测试，禁止 Cluster 模块直接 import：

```text
onlyalpha.gateway
onlyalpha.engine
具体 OnlyBacktestClock 实现
具体 OnlyLiveClock 实现
MarketData Cache 实现类
Bar Aggregator 实现类
EventBus 底层实现类
Storage 实现类
```

Cluster 应依赖 Protocol/View/Context。

---

# 33. 文档输出

创建或更新：

```text
docs/runtime_context.md
docs/runtime.md
docs/cluster.md
docs/event.md
docs/market_data_pipeline.md
docs/concurrency.md
docs/testing.md
docs/architecture_principles.md
```

`docs/runtime_context.md` 至少包含：

1. Runtime 资源所有权；
2. RuntimeContext 职责；
3. 权限边界；
4. Runtime 生命周期；
5. Cluster 生命周期；
6. Context 类型层次；
7. Clock 集成；
8. EventBus 集成；
9. MarketData Pipeline 集成；
10. Snapshot 集成；
11. Timer 集成；
12. 多 Cluster；
13. 多 Runtime；
14. 错误隔离；
15. 停止和关闭；
16. Demo；
17. 已知限制。

---

# 34. ADR

创建：

```text
docs/adr/0007-runtime-context-and-cluster-lifecycle.md
```

至少记录：

## 背景

Clock、EventBus、MarketData Pipeline 和 Cluster 需要被组装为受控运行环境，同时保证回测和实盘接口一致。

## 决策

* Runtime 拥有所有可变运行资源；
* 每个 Runtime 拥有独立 Clock、EventBus、Cache 和 Aggregator；
* Cluster 只通过受限 RuntimeContext 使用服务；
* Cluster 不能推进 Clock；
* Cluster 不能访问可变 Cache；
* Cluster 生命周期由 ClusterManager 管理；
* Strategy Dispatcher 负责选择执行对象；
* ClusterManager 负责调用和异常隔离；
* 回调级 Context 携带不可变 Snapshot；
* 第一版 Backtest Runtime 同步、单线程、确定性。

## 拒绝方案

* Cluster 直接持有所有组件；
* Engine 全局共享一个 Runtime Context；
* Cluster 自行管理生命周期；
* Cluster 直接订阅全局 EventBus；
* Runtime 之间共享 Aggregator；
* Context 暴露完整内部 Service Container。

---

# 35. Architecture Principles 新增规则

加入：

```text
Rule: Runtime 是 Clock、EventBus、Cache、Pipeline 和 Cluster 的资源所有者。

Rule: 每个 Runtime 必须隔离所有可变运行状态。

Rule: Cluster 只能通过 RuntimeContext 使用 Runtime 能力。

Rule: RuntimeContext 不能暴露底层可变实现。

Rule: Cluster 不能推进 Clock。

Rule: Cluster 不能直接访问 Gateway。

Rule: Cluster 不能直接访问可变 MarketData Cache。

Rule: 生命周期状态只能由 Manager 修改。

Rule: Cluster 停止后不得继续接收事件和 Timer。

Rule: 一个 Cluster 失败不得默认导致其他 Cluster 失败。

Rule: Snapshot 属于单次回调上下文，不能长期复用为可变全局状态。

Rule: 回测和实盘必须使用相同 Cluster 回调接口。
```

---

# 36. 实现顺序

严格按以下顺序：

1. 扫描当前 Runtime 和 Cluster 实现；
2. 创建差距分析；
3. 定义 Runtime/Cluster 状态机；
4. 完成状态机测试；
5. 定义 ClockView、MarketDataView 等受限接口；
6. 实现 OnlyRuntimeContext；
7. 完成 Context 权限测试；
8. 实现 OnlyClusterManager；
9. 完成 Cluster 生命周期测试；
10. 实现 Subscription Service 集成；
11. 实现 Timer Service 集成；
12. 实现 OnlyBacktestRuntime；
13. 接入 MarketData Pipeline；
14. 接入 Strategy Dispatcher；
15. 实现 OnlyDemoCluster；
16. 完成 1m→3m 集成测试；
17. 完成多 Cluster 测试；
18. 完成 Runtime 隔离测试；
19. 完成 Cluster 异常隔离测试；
20. 创建 Demo；
21. 更新文档；
22. 创建 ADR；
23. 运行全部相关测试；
24. 输出验收报告。

不要同时实现完整交易链路。

---

# 37. 验收标准

完成后必须满足：

* Runtime 拥有独立 Clock；
* Runtime 拥有独立 EventBus；
* Runtime 拥有独立 MarketData Cache；
* Runtime 拥有独立 Aggregator 和 Indicator 状态；
* RuntimeContext 只暴露受限能力；
* Cluster 无法推进 Clock；
* Cluster 无法修改 Snapshot；
* Cluster 无法访问底层 Cache；
* Cluster 无法直接访问 Gateway；
* Runtime 和 Cluster 状态机明确；
* 非法生命周期迁移被拒绝；
* Cluster 停止后不再接收 Bar；
* Cluster Timer 在停止后自动取消；
* Cluster A 异常不影响 Cluster B；
* Runtime 可以运行多个 Cluster；
* 两个 Runtime 完全隔离；
* 默认最小周期主驱动正确；
* 显式主周期覆盖正确；
* 策略回调前 Snapshot 已准备完成；
* Backtest Clock 与 Bar 时间一致；
* 相同输入执行结果确定；
* Runtime 可以优雅 stop 和 close；
* 文档、测试、Demo、ADR 完整。

---

# 38. 一票否决项

存在以下任一项，不得标记完成：

* Cluster 可以调用 `advance_to()`；
* Cluster 直接持有具体 BacktestClock；
* Cluster 直接修改 MarketData Cache；
* Cluster 直接访问 Aggregator；
* Cluster 直接调用 Gateway；
* Runtime 之间共享可变 Clock；
* Runtime 之间共享可变 Cache；
* Runtime 之间共享可变 Aggregator；
* Cluster 自行修改生命周期；
* Cluster 停止后仍收到 Bar；
* Cluster 异常导致所有 Cluster 无条件停止；
* RuntimeContext 暴露完整内部 Service Container；
* Backtest Runtime 读取系统当前时间；
* Backtest 和 Live 使用不同 Cluster API；
* Snapshot 在回调期间发生变化；
* 相同输入重复运行结果不同；
* Stop/Close 不幂等；
* 资源关闭后仍触发 Timer 或回调。

---

# 39. 最终交付报告

完成后必须输出：

```text
新增文件
修改文件
Runtime 资源所有权设计
RuntimeContext API
Context 权限边界
Runtime 状态机
Cluster 状态机
ClusterManager 设计
Subscription 集成
Timer 集成
MarketData Pipeline 集成
Strategy Dispatcher 集成
Clock 与 Bar 时间顺序
Runtime 错误策略
Cluster 异常隔离结果
多 Runtime 隔离结果
测试通过数
测试失败数
测试跳过数
确定性测试结果
Demo 运行结果
已知限制
一票否决项
是否建议进入 OrderService
是否建议进入 RiskPipeline
是否建议进入 Backtest Execution Pipeline
```

最终结论：

```text
ACCEPTED
CONDITIONALLY_ACCEPTED
REJECTED
```

当前任务只实现：

```text
Runtime
RuntimeContext
Cluster 生命周期
ClusterManager
Subscription 集成
Timer 集成
MarketData Pipeline 集成
Snapshot 回调
Backtest Runtime MVP
Demo
测试
文档
ADR
```

不要在本任务中实现：

* 完整 Engine；
* 真实 Gateway；
* OrderService；
* RiskPipeline；
* 撮合引擎；
* Position；
* Account；
* Storage；
* Web；
* 多线程 Runtime；
* 分布式调度；
* 真实交易。
