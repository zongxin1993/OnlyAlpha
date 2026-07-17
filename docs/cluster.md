# Cluster 容器模型

`OnlyCluster` 是 Runtime 内的隔离容器，不是策略基类。每个 Cluster 必须持有且只持有一个 `OnlyStrategy`，可以持有零个或多个 `OnlyFactor`，并拥有按 Runtime/Cluster/Factor/Indicator 完整 Scope 隔离的 Indicator Registry。

```text
OnlyRuntime
└── OnlyCluster
    ├── OnlyStrategy (exactly one)
    ├── OnlyFactor (zero or more)
    │   └── OnlyIndicator (one or more for computational Factors)
    └── OnlyClusterPipeline
```

## 固定调度

Bar 到达前 MarketData Pipeline 已完成标准化、聚合与不可变 Snapshot。Cluster 回调内固定执行：

```text
matching Indicator.update_bar
→ TimeSeries Factor
→ same-time CrossSection Factor
→ Factor Snapshot/Score bundle
→ Required Factor ready gate
→ Strategy callback
→ ctx.orders.submit
```

顺序由 `OnlyFactorDependencyGraph` 的稳定拓扑计划决定，不依赖注册顺序、字典顺序或 EventBus priority。时序 Factor 不得在同一时间点依赖截面 Factor；缺失依赖和循环依赖在组装阶段失败。

## 生命周期与隔离

Manager 仍是 Cluster 状态唯一真值：`CREATED → LOADED → INITIALIZED → STARTING → RUNNING → PAUSED → STOPPING → STOPPED`，异常进入 `FAILED`。初始化顺序为 Factor Context 绑定、Factor 初始化并创建 Indicator、Strategy Context 绑定、Strategy 初始化、订阅批准。暂停/恢复/停止会转发到 Strategy，停止按逆序停止 Factor。

不同 Cluster 不共享可变 Strategy、Factor 或 Indicator 实例。Cluster 只能持有 Runtime 提供的受限 Context，不接触 Gateway、Broker、Manager、EventBus、DataSource 或可变 Cache。

产品配置遵守“一文件一 Cluster”。Engine 在运行前通过 `add_cluster(config)` 返回不可变 `OnlyClusterHandle`；外部不持有
Cluster 内部可变对象。卸载通过 `OnlyClusterRemovalPolicy` 执行并减少共享资源引用，禁止直接从 Registry 删除对象。
