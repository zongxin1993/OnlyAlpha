# Event、MarketData Pipeline 与主周期交付验收报告

- 日期：2026-07-14
- 最终结论：**ACCEPTED**

## 新增文件

- `src/onlyalpha/market_data/`：Subscription、Cache、Snapshot、Aggregation、Pipeline、Dispatcher。
- `src/onlyalpha/indicator/`：Indicator contract、Requirement、同步 Pipeline 与内部 Cache。
- `src/onlyalpha/cluster/bar_context.py`：策略只读 Bar Context。
- `tests/event/`、`tests/market_data/`：31 项专项验证。
- `examples/event_market_data_demo/`：默认/显式 primary、多 Cluster、重放四个 Demo。
- `docs/event_component_analysis.md`
- `docs/market_data_pipeline.md`
- `docs/bar_subscription.md`
- `docs/adr/0009-event-and-primary-bar-delivery.md`
- `docs/event_component_acceptance_report.md`

任务建议 ADR-0006 已被 Accepted 的 MarketRule ADR 占用；未覆盖既有决策，按连续编号使用 ADR-0009。

## 修改文件

- `src/onlyalpha/event/model.py`：强类型、Scope、correlation/causation、priority、Unix 纳秒 DTO、事实事件。
- `src/onlyalpha/event/bus.py`：Subscription、unsubscribe、Scope、三种满载策略、结构化 dispatch/drop/failure。
- `src/onlyalpha/cluster/base.py`：增加 `on_bar(primary_bar, OnlyBarContext)`。
- 各 package `__init__.py`：导出新增公共组件。
- `docs/event.md`、`docs/runtime.md`、`docs/cluster.md`、`docs/testing.md`、
  `docs/architecture_principles.md`：同步架构和验收规则。

工作区中原有的 `AGENTS.md` 修改与任务 prompt 未被本次实现改写。

## Event Model 设计

Event 是不可变已发生事实，不表达“构建 Bar”“计算指标”“调用策略”等命令。Envelope 使用强类型
Event ID/Type/Source/Sequence、Engine/Runtime/Cluster Scope、Correlation/Causation、priority、metadata
和可重放 payload。UTC datetime 是兼容视图，`timestamp_ns/ts_init_ns` 是无损 Unix 纳秒真值。

## Event Scope 设计

Engine Scope 可包含 Runtime；Runtime Scope 可包含本 Runtime 的 Cluster。Bus publish 时强制 scope includes，
跨 Runtime Event 明确失败。Runtime 的 MarketData Cache、Aggregation Manager、Indicator Pipeline 和
Dispatcher 均为独立实例，不共享可变状态。

## EventBus 队列和顺序策略

同步、单线程 dispatch、FIFO、有界 deque。handler 顺序为显式 priority 后 registration sequence，但该顺序
只适用于事实观察者，不参与 MarketData 强业务步骤。REJECT/FAIL_RUNTIME 明确失败；DROP_LOW_PRIORITY
只显式替换更低 priority 项，并保留 `OnlyDroppedEvent`，不静默丢弃。handler 异常结构化留存且不阻断其他
handler；close 先停止接收再 drain。

## Bar Subscription API

`OnlyBarSubscription` 保存不可变 BarType 集、PRIMARY_ONLY delivery、freshness 与 primary。首版同一订阅
限制一个 Instrument。EACH_BAR/TIME_SLICE 只定义扩展枚举，构造时明确拒绝，避免未完成语义进入策略。

## 默认与显式主周期

全部 TIME Bar 默认按 `specification.step` 选择最小周期；输入/注册顺序不参与。显式 primary 优先且必须属于
订阅集合。包含 Tick/Volume/Value 等不可自然比较 Bar 时强制显式 primary，不做框架猜测。

## MarketData Pipeline 顺序

```text
输入校验/重复乱序检查
→ 基础 1m Cache
→ Runtime 共享 Aggregation Manager
→ 全部当期派生 Bar Cache
→ 受影响 Indicator
→ Required Dependency Barrier
→ 不可变 Snapshot
→ Dispatcher
→ Cluster.on_bar
```

Pipeline 与 Dispatcher 使用直接同步接口；源码不导入或调用 EventBus 来完成该顺序。失败在 Snapshot/策略前
终止，并保存 PipelineFailed 事实。

## Aggregation Manager 设计

Runtime 内按目标 BarType 唯一持有 Aggregator，重复 Cluster Subscription 只增加引用，不重复创建状态。
首版支持外部 1m TIME 到内部 3m/5m/15m。窗口由 TradingCalendar Session interval 起点锚定，区间
`[start,end)`；上午/下午不跨午休拼接，也不使用 Unix timestamp 取模。派生顺序是依赖级、duration、稳定
BarType ID。Session 尾部不完整窗口默认 DROP；partial 相关策略未实现时明确拒绝。

## Indicator Ready Barrier

Cache 完成后，Indicator 按稳定 ID 同步计算。REQUIRED 失败抛 Pipeline Error，Dispatcher 无 Update Result
可执行；OPTIONAL 失败移除可能的陈旧值、写 quality flag 后允许继续。Barrier 五项全部 ready 才返回结果。

## Snapshot 设计

Snapshot 保存纳秒逻辑时间、Scope、主 Bar、updated BarTypes、latest closed/history、Indicator value/version、
TradingDay/Session/quality flags。Bar frozen，映射为 MappingProxy，历史为 tuple。Cluster View 仅含已订阅
Bar/Indicator；`latest_closed` 从不返回正在形成的 Bar，`require_same_event_time` 强制 end 与主 Bar 相同。
Snapshot 与 Update Result 提供稳定 DTO，可重放 Decimal、UTC、BarType、version 和 sequence。

## Cluster 调用语义与共享情况

PRIMARY_ONLY 只有 primary 在 `updated_bar_types` 时调用。多个周期同刻关闭仍只调用一次；Dispatcher 记录
Cluster+纳秒时间片，重复调用明确失败。Cluster 按稳定 ID 遍历而非注册顺序；一个 Cluster 异常不会阻止
其他 Cluster。同 Runtime 相同 3m 请求实测 `aggregator_count=1, creation_count=1`。

## 测试结果

- Event + MarketData 专项：31 passed，0 failed，0 skipped，0.05s。
- 全量：106 passed，0 failed，0 skipped，0.26s。
- Ruff：通过。
- mypy strict：52 个 source files，无问题。
- `git diff --check`：通过。
- 四个 Demo：全部通过。

## 重放验证

三根序列化 `OnlyEvent<OnlyBar>` 分别在两个全新 Pipeline/Dispatcher 实例中重放。结果：

```text
replay_equal=True
calls=3
updated: {1m}, {1m}, {1m,3m}
```

Snapshot DTO、策略调用次数、调用时刻、主 Bar 和 updated BarTypes 一致。另有测试证明实际 Live Clock 与
Virtual/Backtest Clock 使用相同 Pipeline 准备和调用语义。

## 已知限制

- 只完整支持 1m→3m/5m/15m TIME Bar。
- 不生成 partial Bar；EMIT_PARTIAL/TRUNCATE/INSERT_EMPTY/FILL_FORWARD 尚未实现。
- 修订 Bar 默认拒绝；尚无审计后的 revision replay/replacement。
- Snapshot callback 期间同步串行，慢策略会阻塞该 Runtime 后续 MarketData。
- 复杂 Indicator 向量 DTO、持久化恢复、真实 Gateway 和完整 RuntimeContext 装配留待后续。

## 一票否决项

逐项检查均未触发：策略不持有可变 MarketData Cache；无后台聚合/Indicator 线程；策略只在 Barrier 后执行；
不存在 1m/3m 分别回调并依赖顺序；业务不依赖 Subscription 注册顺序或 EventBus priority；Aggregator Runtime
级共享；Live/Backtest 顺序相同；Snapshot closed-only 且纳秒无损；Runtime 状态隔离；每时间片单次调用；
非时间 Bar 强制显式 primary；核心 Event 满载不静默丢弃。

## 后续建议

- 是否建议进入 RuntimeContext：**是**。装配 Runtime 自有 Pipeline/Cache/Aggregator/Indicator/Dispatcher，
  Cluster Context 继续只提供 ClockView 和市场数据只读能力。
- 是否建议进入 Cluster 生命周期：**是**。在 initialize/start/stop 中注册和释放 Subscription 引用，并增加
  paused/failed Cluster 的 delivery policy。
- 是否建议进入 Backtest MVP：**是，有边界条件**。先接历史 1m Source、Calendar 版本解析和 Clock 推进，
  继续复用当前 Pipeline；撮合、订单和账户另设明确阶段，不能反向侵入本组件。
