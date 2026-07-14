# RuntimeContext 实现前差距分析

## 1. 扫描范围

本分析在实现前完成，覆盖 `core.clock`、`event`、`market_data`、`indicator`、`runtime`、
`cluster`、`engine`、Cache 接口和现有测试，并以只读方式核对 MyQuant 的
`core/engine.py`、`core/strategy.py`、`core/object.py` 与 Datachef 生命周期。

## 2. 当前可复用能力

- `OnlyBacktestClock` 已提供纳秒真值、单调推进、确定 Timer 顺序和结构化失败。
- `OnlyClockView` 不暴露推进与关闭能力，可作为 Cluster 的时间 capability。
- `OnlyEventBus` 已是有界、同步、可限定 Engine/Runtime Scope 的事实总线。
- `OnlyMarketDataPipeline` 已固定执行校验、Cache、聚合、Indicator、Snapshot 的同步顺序。
- `OnlyBarAggregationManager` 在单 Runtime 内共享派生 Bar，`OnlyMarketDataCache` 保存可变行情真值。
- `OnlyMarketDataSnapshot` 不可变且可按 Cluster Subscription 裁剪。
- `OnlyStrategyBarDispatcher` 已按稳定 Cluster ID 选择主周期回调目标。

## 3. 当前关键差距

### 3.1 Runtime

旧 `OnlyRuntime` 只有 `CREATED/RUNNING/STOPPED`，构造器接收外部共享资源并公开
`clock/event_bus/cache`。`OnlyBacktestRuntime` 只是标记类，没有初始化阶段、暂停/失败/关闭状态，
也没有 Bar 输入、Clock 推进、Timer、Pipeline、EventBus 和 Cluster 调用的统一编排。

### 3.2 Cluster 与 Context

旧 `OnlyClusterContext` 直接暴露完整 `OnlyEventBus` 和可写 `OnlyCache`，违反最小权限。
Cluster 的 `initialize/start/stop` 直接修改自身状态，没有 Manager 唯一真值；停止时也没有统一释放
Subscription 与 Timer。回调级 `OnlyBarContext` 只含 Snapshot 与 ClockView，尚未关联受限 Runtime View。

### 3.3 Dispatcher

Dispatcher 既选择 Cluster 又直接调用 `on_bar`。它能隔离单次异常，但不能把失败写入 Cluster
生命周期真值，也无法保证 FAILED/STOPPED Cluster 后续不再接收 Bar。选择与执行需要分别归属
Dispatcher 和 `OnlyClusterManager`。

### 3.4 资源所有权和隔离

现有 Runtime 可接收并公开任意外部 Clock/EventBus/Cache，不能从 API 上证明不同 Runtime 的
可变资源独立。行情 Cache、Aggregator、Indicator、Pipeline 和 Dispatcher 尚未由 Runtime 统一创建。

## 4. MyQuant 行为结论

MyQuant 的 Engine 循环先调用 Datachef `on_bar()` 准备数据，再调用策略 `run_once()`；这项“数据先于
策略”的有效顺序应保留。其 `StrategyContext` 同时持有 Datachef、PositionManager、Broker 相关对象，
策略通过 `is_running` 间接控制主循环，且没有显式 Runtime/Cluster 状态机和多 Cluster 隔离。这些耦合
不复制到 OnlyAlpha。OnlyAlpha 将驱动权、可变数据和失败策略收回 Runtime/Manager，只向 Cluster 发放
只读查询与受命名空间约束的 Subscription/Timer capability。

## 5. 变更边界

本阶段实现：Runtime/Cluster 状态机、受限 Context/View、ClusterManager、Subscription/Timer 生命周期、
同步 Backtest `process_bar`、1m→3m→Snapshot→DemoCluster 闭环、多 Cluster/多 Runtime 隔离和文档测试。

本阶段不实现：订单、风控、撮合、持仓、账户、真实 Gateway、Storage、Web、多线程 Runtime 或完整 Engine
重构。Engine 只做必要的生命周期适配。

## 6. 目标所有权

```text
OnlyBacktestRuntime
├── OnlyBacktestClock（唯一推进者）
├── OnlyEventBus（Runtime Scope）
├── OnlyMarketDataCache（仅 Pipeline 写）
├── OnlyBarAggregationManager
├── OnlyIndicatorPipeline
├── OnlyMarketDataPipeline
├── OnlyStrategyBarDispatcher（只选择计划）
├── OnlyClusterManager（生命周期、调用、异常隔离）
└── Cluster-scoped RuntimeContext（窄 capability）
```

Runtime 外部只得到状态 DTO、处理结果和 Cluster Context View；内部 Service Container 不进入 Context。
