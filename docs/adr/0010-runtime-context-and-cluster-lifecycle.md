# ADR-0010：RuntimeContext 与 Cluster 生命周期

- 状态：Accepted
- 日期：2026-07-14
- 关联模块：runtime、cluster、clock、event、market_data
- 编号说明：任务建议使用 0007，但 ADR-0007 已被 UTC 与交易日历决策占用，因此使用下一个连续编号 0010。

## 背景

Clock、EventBus、MarketData Pipeline 和 Cluster 需要组装成受控运行环境，同时保持回测与未来实盘的
Cluster API 一致。旧 Context 暴露完整 EventBus 和可写 Cache，Cluster 自行改变状态，Backtest Runtime
也没有明确驱动顺序，无法证明权限、隔离与确定性。

## 决策

- Runtime 拥有全部可变运行资源，每个 Runtime 独占 Clock、EventBus、Cache、Aggregator 和 Indicator 状态。
- Cluster 只通过受限 `OnlyRuntimeContext` 使用只读查询和命名空间化 capability。
- Cluster 不能推进 Clock、访问可变 Cache、Aggregator、Gateway 或底层 EventBus。
- Cluster 生命周期由 `OnlyClusterManager` 管理；Dispatcher 只选择执行对象，Manager 调用并隔离异常。
- 回调级 `OnlyBarContext` 携带已完成数据屏障后的不可变 Snapshot。
- Cluster Subscription 只在初始化声明，Timer 由 Runtime 命名空间化并在停止/失败时清理。
- 第一版 Backtest Runtime 同步、单线程、确定性；Timer 在相同事件时间先于 Bar 处理。

## 拒绝方案

- Cluster 直接持有所有组件：权限无法限制，生命周期与资源释放分散。
- Engine 全局共享 Runtime Context：Clock、Cache 和 Aggregator 会跨 Runtime 污染。
- Cluster 自行管理生命周期：状态没有唯一真值，失败后可能继续分发。
- Cluster 直接订阅全局 EventBus：Scope 可伪造且业务顺序依赖观察者配置。
- Runtime 间共享 Aggregator：历史输入会相互污染。
- Context 暴露完整 Service Container：窄接口失效，Gateway/Storage 等未来能力会泄漏。

## 结果

Runtime 可以同步编排 1m 输入、3m 聚合、Snapshot 和多 Cluster 回调；失败 Cluster 被隔离，停止后不再
接收 Bar/Timer。代价是首版只提供单线程 Backtest MVP，Live/Paper 资源装配和交易链路继续后置。

## 验证

状态机、权限、Timer 顺序、默认/显式主周期、失败隔离、多 Runtime 隔离、100 次重放、全量测试和四个
Demo 共同验证本决策。
