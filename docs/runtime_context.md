# Runtime 资源所有权与受限 Context

## 1. 所有权

每个 `OnlyBacktestRuntime` 独占 `OnlyBacktestClock`、有 Runtime Scope 的 `OnlyEventBus`、
`OnlyMarketDataCache`、`OnlyBarAggregationManager`、`OnlyIndicatorPipeline`、
`OnlyMarketDataPipeline`、`OnlyStrategyBarDispatcher` 和 `OnlyClusterManager`。内部
`OnlyRuntimeServices` 只用于装配，绝不进入 Cluster Context。不同 Runtime 不共享可变资源。

## 2. Context 能力

`OnlyRuntimeContext` 是 Cluster 绑定的 frozen facade：

- `clock`：只读 `OnlyClockView`，没有推进、关闭或调度方法；
- `market_data`：只能读取已订阅 Bar、已声明 Indicator 和当前回调 Snapshot；
- `instruments`：只读查询；
- `subscriptions`：只在 `on_initialize` 接受声明；
- `timers`：自动加 `runtime_id:cluster_id` 命名空间；
- `logger`：自动绑定 Runtime/Cluster/Mode 字段。

Context 不含 EventBus、可变 Cache、Aggregator、Indicator 内部对象、Gateway、Storage、Engine、
其他 Cluster 或内部 Service Container。Cluster 不能伪造 Scope，也不能推进 Runtime Clock。

## 3. Context 层次

```text
OnlyRuntimeContext / OnlyClusterContext
├── OnlyClockView
├── OnlyMarketDataView
├── OnlyInstrumentView
├── OnlySubscriptionService
├── OnlyTimerService
└── OnlyRuntimeLogger

OnlyBarContext
├── 单次不可变 OnlyMarketDataSnapshot
└── 当前 Cluster 的 OnlyRuntimeContextView

OnlyTimerContext
├── OnlyTimerEvent
└── 当前 Cluster 的 OnlyRuntimeContextView
```

Snapshot 只在一次 Bar 回调期间作为 `current_snapshot()` 可见；回调后 Runtime 清除该引用。

## 4. 生命周期

Runtime：`CREATED → READY → RUNNING → STOPPING → STOPPED → CLOSED`，另有 `PAUSED/FAILED`。
`stop()` 与 `close()` 幂等，STOPPING 后拒绝新 Bar。Runtime 初始化 Cluster 后才进入 READY。

Cluster：`CREATED → LOADED → INITIALIZED → STARTING → RUNNING → STOPPING → STOPPED → UNLOADED`，
另有 `PAUSED/FAILED`。`OnlyClusterManager` 是状态唯一真值；Cluster 只实现回调，不提供自助生命周期方法。
停止或失败会取消全部 Timer、释放 Bar Subscription 并停止后续分发。

## 5. 同步 Backtest 顺序

`OnlyBacktestRuntime.process_bar()` 固定执行：

```text
校验 Runtime RUNNING
→ BacktestClock.advance_to(bar.ts_event)
→ 触发 deadline <= ts_event 的 Timer（同时间 Timer 先于 Bar）
→ MarketData Pipeline：校验/Cache/聚合/Indicator/Barrier/Snapshot
→ 发布已完成事实到 Runtime EventBus
→ Dispatcher 按稳定 Cluster ID 选择主周期执行计划
→ ClusterManager 串行调用、记录失败并隔离 Cluster
→ drain EventBus 并返回结构化结果
```

Backtest Runtime 不读取系统当前时间、不开线程、不 sleep。Clock 到达 Bar 时刻后 Pipeline 才处理 Bar；
策略回调前所有可生成派生 Bar、Required Indicator 和不可变 Snapshot 已同步完成。

## 6. Subscription 与主周期

Cluster 在 `on_initialize` 通过 `subscriptions.subscribe_bars()` 声明一次不可变订阅。默认最小 TIME step
是主周期，可显式覆盖。1m+3m 默认在 09:31、09:32、09:33 调用三次，第三次 Snapshot 更新集为
`{1m,3m}`；显式 3m 主周期只在 09:33 调用一次，并可读取第三根已关闭 1m。

多个 Cluster 对同一派生 Bar 使用 Runtime 级引用计数 Aggregator；停止一个 Cluster 只释放其引用。

## 7. Timer

Cluster 只能通过 `OnlyTimerService` 注册本 Cluster Timer，不能提交裸 Clock callback 或其他 Scope 的 ID。
Timer 的 deadline/registration sequence/timer ID 顺序由 Clock 保证。回调由 Runtime 路由给
`OnlyClusterManager.execute_timer`；Cluster 停止、失败或 Runtime 关闭时自动取消。

## 8. 错误与隔离

Pipeline、Clock 推进或 EventBus 核心失败使 Runtime 进入 FAILED 并保留 `last_error`。Cluster callback
默认采用 `ISOLATE_CLUSTER`：失败 Cluster 进入 FAILED、释放资源且不再接收回调，其他 Cluster 与 Runtime
继续。`FAIL_RUNTIME` 可显式把 Cluster Bar 失败升级为 Runtime FAILED。结构化 Cluster failure 包含
runtime_id、cluster_id、callback、ts_event、bar_type、错误类型和消息。

## 9. 多 Runtime 与并发

第一版 Backtest Runtime 单线程同步执行；单 Cluster 回调天然串行。Runtime 间没有 Clock、Cache、
Aggregator、Indicator、Dispatcher、Timer 或 Event Scope 共享。未来 Live/Paper 必须复用相同 Cluster
回调和 Context 权限，但其线程与 Gateway 装配不在本阶段。

## 10. Demo 与限制

`examples/runtime_context_demo` 包含基础闭环、多 Cluster、Runtime 隔离和 Cluster 失败四个 Demo。
当前只支持已关闭外部 1m TIME Bar 到内部时间 Bar，不包含订单、风控、撮合、账户、真实 Gateway、Storage、
多线程 Runtime 或 Runtime 重启。旧四参数 Backtest Runtime 构造器仅为骨架兼容；新代码应使用
`OnlyRuntimeConfig + OnlyTradingCalendar + initial_time`。
