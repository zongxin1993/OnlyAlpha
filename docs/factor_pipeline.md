# Factor 与 Cluster Pipeline

`OnlyFactorDependencyGraph` 生成稳定拓扑 `OnlyFactorExecutionPlan`。每个 Bar 逻辑时间点执行 MarketData ready barrier 后，Cluster Pipeline 更新匹配 BarType 的 Indicator，再按计划执行时序 Factor 和截面 Factor，生成 Snapshot/Score bundle，最后检查 Strategy Required Factors。

依赖 Factor 未 READY 时，下游 Factor 不执行；Required Factor 未 READY 时 Strategy 不执行。截面 Context 只包含相同 `bar_end` 的资产，并按 Instrument ID 稳定排序，避免未来函数和输入顺序漂移。

失败由 Cluster Manager 隔离；一个 Cluster 失败不会默认停止同 Runtime 其他 Cluster。Pipeline 不用 EventBus 表达命令顺序。
