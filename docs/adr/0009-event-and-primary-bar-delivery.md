# ADR-0009：Event 事实传播与主周期 Bar 交付

- 状态：Accepted
- 日期：2026-07-14
- 关联模块：event、market_data、indicator、cluster
- 编号说明：任务建议编号 0006 已被 Accepted 的 MarketRule ADR 占用，因此使用下一个连续编号 0009。

## 背景

多周期策略若为每个周期分别回调，或让 Cache/Aggregator/Indicator/Cluster 各自订阅基础 Bar，会把业务
一致性绑定到 EventBus priority、注册顺序或线程时序。策略可能在派生 Bar或 Required Indicator 尚未完成时
读取半更新状态，回测和实盘也难以重放一致。

## 决策

- EventBus 只传播已发生事实；MarketData Pipeline 通过直接接口编排强顺序。
- Runtime 级 Aggregation Manager 唯一、共享地产生派生 Bar；不同 Runtime 状态隔离。
- 默认最小订阅 TIME step 为主周期，允许显式覆盖；不可比较的非时间 Bar 强制显式 primary。
- Pipeline 在主周期触发前同步完成基础/派生 Cache、全部相关 Indicator 和 Required Barrier。
- 策略只读取不可变、按 Subscription 限制的 Snapshot，默认只含已关闭 Bar。
- PRIMARY_ONLY 下每 Cluster/逻辑时间片最多调用一次，即使多个周期同时关闭。
- 第一版核心路径同步、单线程、确定；Live 与 Backtest 共用同一处理顺序。
- Timer/Event/Bar 的绝对时间沿用 Unix 纳秒与 UTC；Calendar 是 Session 边界唯一来源。

## 拒绝方案

- 不同周期分别无条件回调：策略需自行猜测先后，容易重复交易。
- 使用注册顺序或 EventBus priority：观察者配置不是业务事务边界，重构订阅就会改变结果。
- 后台线程聚合、策略直接读可变 Cache：存在半更新可见性和回放竞态。
- 每 Cluster 独立聚合：重复计算且同一派生 Bar可能产生差异。
- 全步骤事件化：把 Command 当 Event，弱化明确错误传播和数据准备屏障。

## 结果

多周期数据在一次回调前形成一致视图，主周期规则可解释，多 Cluster 共享计算且相互隔离。代价是首版同步
吞吐受最慢 Indicator/Cluster 限制，且只实现 1m 到 3m/5m/15m TIME Bar。

## 验证

测试覆盖 Event Scope/FIFO/容量/异常、默认和显式 primary、Calendar 聚合、午休锚定、缺失/不完整窗口、
Required/Optional Indicator、Snapshot 不可变、多 Cluster 共享与异常隔离、Runtime 隔离、Live/Backtest
同语义和序列化重放。ruff、mypy strict、全量 pytest 与四个 Demo 必须通过。
