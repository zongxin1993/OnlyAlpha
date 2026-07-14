# Event、MarketData Pipeline 与策略 Bar 驱动差距分析

状态：2026-07-14，实现前基线扫描

## 1. 当前事件实现

| 模块 | 当前实现 | 当前问题 | 目标实现 |
|---|---|---|---|
| `event.model` | frozen `OnlyEvent`，UTC datetime、字符串类型/Scope、UUID、基础 JSON | ID/Scope/Type/Source/Sequence 是裸值；datetime JSON 只能到微秒；无 correlation/causation/priority；payload 重放范围不明确 | 强类型 Event envelope、Unix 纳秒真值、稳定 Scope、关键事实事件和可重放 payload |
| `event.bus` | 同步、FIFO、有界 deque；handler 异常留存；close 后 drain | 无 Subscription/取消、Scope 校验、queue policy、publish_many/dispatch result；handler 只靠注册顺序 | Runtime Scope 隔离、显式 handler priority + 注册 sequence、结构化结果和明确满载策略 |
| Runtime | 每个 Runtime 有独立 Bus | Cluster 直接持有 Runtime Bus；尚无 MarketData Pipeline | Bus 传播完成事实，Pipeline 直接编排强顺序 |

## 2. 当前 Bar 数据流

- `OnlyBar`、`OnlyBarType`、`OnlyBarSpecification` 已是完整不可变 Domain 事实，区间为 `[start,end)`。
- 当前没有基础 Bar Source/Gateway 接入、Bar Subscription、Bar Cache、Aggregator、Indicator Pipeline、Snapshot 或策略 `on_bar`。
- 通用 `OnlyMemoryCache` 是带命名空间的 object KV；它不表达 latest closed、history、partial 或 version，不能作为策略市场数据视图。
- Cluster 只有生命周期回调；没有 Bar Context，也没有数据准备屏障。
- 因为尚无实际数据流，不存在后台聚合线程或每策略重复聚合，但也没有防止这些错误架构的边界。

## 3. MyQuant 行为参考

只读检查了任务指定的 `zongxin1993/MyQuant` 当前 HEAD。有效行为包括：

- Datachef 在策略逻辑之前准备数据；回测以当前窗口结束时刻作为 `current_datetime`。
- Live 过滤尚未关闭的未来标签 Bar，并跳过重复 last bar。
- 1m 历史、rolling aggregation 和 feature 结果有缓存，避免同一 Datachef 内反复计算。
- 指标/rolling handler 在策略获得结果前执行。

需要重建而不复制的部分：

- pandas `resample`/rolling 依赖自然时间栅格，不能成为跨午休、夜盘、DST、提前收盘的 Calendar 真值。
- Cache 和聚合状态属于策略 Datachef，多策略会重复且可见性边界不清。
- Backtest 和 Live 取数/过滤路径不同，时间多为本地字符串或 naive pandas timestamp。
- 策略获得可变 DataFrame/metadata，没有不可变时间片 Snapshot 或 Required Indicator barrier。

## 4. 主要风险与处理

| 风险 | 当前状态 | 本阶段处理 |
|---|---|---|
| 依赖订阅注册顺序或 EventBus priority | 尚无业务流，极易在扩展时出现 | Pipeline 直接调用固定步骤；priority 只用于 handler 分发，不控制多周期事务 |
| 回测事件串入实盘 | Runtime Bus 独立但 Event 无强 Scope | Event Scope 与 Bus scope 双重校验；聚合/Cache/Pipeline 均为 Runtime 实例 |
| 策略读到半更新 Cache | 无策略市场数据 API | Cache 只由同步 Pipeline 修改，Dispatcher 只接收 barrier 完成后的不可变 Snapshot |
| 指标未完成先执行策略 | 无 Indicator 接口 | Required 失败阻断 dispatch；Optional 缺失进入 quality flags |
| 多 Cluster 重复聚合 | 尚无 Aggregator | Runtime 级 Aggregation Manager 按稳定 BarType ID 唯一持有并引用计数 |
| 派生边界跨 Session | 尚无实现 | 使用 TradingCalendar session interval 锚定，不做 Unix timestamp 取模 |
| 重复、乱序、修订静默覆盖 | 尚无实现 | 第一版重复/乱序/修订默认拒绝，不重写已用于决策的 Cache |
| Snapshot 不可重放或时间精度丢失 | 尚无 Snapshot | Snapshot/Event DTO 保存 Unix nanoseconds、Domain Bar JSON 与稳定排序列表 |
| 多周期分别回调 | 尚无回调 | PRIMARY_ONLY；默认最小时间周期，可显式覆盖；每 Cluster/时间片最多一次 |

## 5. 变更边界

本阶段只实现 Event 基础设施、1m 外部时间 Bar到 3m/5m/15m 内部时间 Bar、Runtime 级 Cache/聚合、
最小 Indicator 接口、同步数据屏障、不可变 Snapshot 和 Dispatcher。不接入真实 Runtime/Gateway、订单、
撮合、账户、Web、后台线程或分布式消息系统。
