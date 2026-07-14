# RuntimeContext 验收报告

- 日期：2026-07-14
- 结论：**ACCEPTED**

## 新增文件

- `src/onlyalpha/runtime/context.py`
- `src/onlyalpha/cluster/manager.py`
- `tests/runtime/`（12 个测试用例）
- `examples/runtime_context_demo/`（4 个可运行 Demo 与公共 fixture）
- `docs/runtime_context_analysis.md`
- `docs/runtime_context.md`
- `docs/adr/0010-runtime-context-and-cluster-lifecycle.md`
- 本报告

## 修改文件

- Runtime/Cluster：`runtime/runtime.py`、`cluster/base.py`、`cluster/bar_context.py`、`cluster/demo.py`
- 资源边界：`core/clock.py`、`market_data/dispatcher.py`、`market_data/pipeline.py`、
  `market_data/aggregation/manager.py`
- 生命周期适配：`engine/engine.py`
- 公共导出与循环依赖消除：顶层、cluster、runtime、market_data 的 `__init__.py`
- 文档：runtime、cluster、event、market_data_pipeline、concurrency、testing、architecture_principles

## Runtime 资源所有权设计

每个 Backtest Runtime 独占 Clock、Runtime-scoped EventBus、MarketData Cache、Aggregator、Indicator Pipeline、
MarketData Pipeline、Dispatcher 和 ClusterManager。内部 `OnlyRuntimeServices` 不通过任何 Context 暴露。

## RuntimeContext API 与权限边界

Cluster 只获得只读 Clock、订阅范围内 MarketData、Instrument View、初始化期 Subscription、命名空间化 Timer
和绑定 Logger。Context 没有 EventBus、可变 Cache、Aggregator、Gateway、Storage、Engine 或 Service
Container。ClockView 不含调度、推进和关闭；Snapshot 与 BarContext 不可变。

## Runtime 状态机

已实现 CREATED、READY、RUNNING、PAUSED、STOPPING、STOPPED、FAILED、CLOSED。非法迁移抛
`OnlyLifecycleError`；`stop/close` 幂等；非 RUNNING 状态拒绝 Bar。

## Cluster 状态机与 ClusterManager

已实现 CREATED、LOADED、INITIALIZED、STARTING、RUNNING、PAUSED、STOPPING、STOPPED、FAILED、UNLOADED。
Cluster 没有公开 initialize/start/stop 状态修改入口；Manager 统一绑定 Context、调用 callback、转换状态、记录
结构化错误和清理资源。单 Cluster 可单独停止。

## Subscription 与 Timer 集成

Subscription 只在 `on_initialize` 接受，一个 Cluster 首版一个 Bar Subscription；停止/失败自动释放并递减
Aggregator 引用。Timer ID 自动变为 `runtime_id:cluster_id:timer_id`；停止/失败后自动取消且拒绝新 Timer。
同 deadline 顺序仍由 Clock 的 deadline、registration sequence、timer ID 决定。

## MarketData Pipeline 与 Dispatcher 集成

Runtime 先推进 Clock，再同步执行 Pipeline 数据屏障并发布完成事实；Dispatcher 只按稳定 Cluster ID 选择
主周期目标，调用委托给 ClusterManager。没有使用 EventBus priority 或注册顺序表达多周期业务逻辑。

## Clock 与 Bar 时间顺序

同一 `ts_event` 的 Timer 在 `process_bar` 的 Clock advance 阶段先完成，随后处理 1m Bar。策略回调时 Clock、
Snapshot 和主 Bar 的事件时间一致；第三根 1m 前已完成 3m 聚合和 Snapshot。

## Runtime 错误策略与 Cluster 异常隔离

Pipeline/Clock/EventBus 核心异常使 Runtime FAILED。Cluster 默认 `ISOLATE_CLUSTER`：A 第二次回调失败后为
FAILED 且不接收第三根；B 保持 RUNNING 并接收三根；Runtime 保持 RUNNING。结构化错误包含 Runtime、
Cluster、时间、BarType、callback 和原错误。

## 多 Runtime 隔离结果

两个 Runtime 的 ClockView、Cache 数据、Aggregator 状态、Cluster 记录和 Event Scope 独立；相同 Instrument
输入不同价格不会互读。Runtime 构造不使用全局可变资源。

## 测试结果

- `ruff check src tests examples/runtime_context_demo`：通过
- `mypy src/onlyalpha`（strict）：54 个 source files，通过
- `pytest -q`：118 passed，0 failed，0 skipped
- RuntimeContext 专项：12 passed
- 确定性：相同配置、初始 Clock 和三根 Bar 重建 Runtime 并重放 100 次，记录、Snapshot/派生 Bar、Clock、
  Pipeline sequence 全部一致

## Demo 结果

- Basic：1m 回调 3 次；第三次 updated=`{1m,3m}`；3m 区间 09:30–09:33
- Multi Cluster：A(1m primary)=3 次，B(3m primary)=1 次，共享 3m 结果相等
- Runtime Isolation：Clock capability 和行情数据独立
- Cluster Failure：A=FAILED/2 次，B=RUNNING/3 次，Runtime=RUNNING

## 已知限制

- 仅完整装配同步单线程 Backtest Runtime；Live/Paper/Research 仍为后续资源装配边界。
- 仅支持首版已关闭外部 1m TIME Bar 及现有内部时间聚合。
- 不支持 Runtime 重启；STOPPED 后应 close 并新建 Runtime 重放。
- 兼容旧四参数 Backtest 构造器；新代码应使用 RuntimeConfig、Calendar、initial time。
- 本阶段没有 OrderService、RiskPipeline、撮合、Account/Position、真实 Gateway、Storage 或 Web。

## 一票否决项审计

全部未触发：Cluster 无法 advance/close Clock，不持有具体 Backtest/Live Clock，不可写 Cache，不可访问
Aggregator/Gateway/EventBus；Runtime 不共享可变资源；Manager 管理 Cluster 状态；停止/失败后无 Bar/Timer；
Snapshot 回调期间不可变；Backtest 不读系统时间；stop/close 幂等；重复运行结果一致。

## 后续阶段建议

- 是否建议进入 OrderService：**是**，Runtime/Context capability 边界已稳定，可先定义命令与状态真值。
- 是否建议进入 RiskPipeline：**否（暂缓）**，应在 OrderService 请求/状态模型完成后接入。
- 是否建议进入 Backtest Execution Pipeline：**否（暂缓）**，应等待 OrderService 与 RiskPipeline 的确定接口。
