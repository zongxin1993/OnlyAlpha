# ADR 0020: Cluster、Strategy、Factor 与 Indicator 模型

- Status: Accepted
- Date: 2026-07-16
- Modules: engine, runtime, cluster, strategy, factor, indicator, config, examples
- Numbering: 任务建议使用 0018，但 0018 已是 Accepted 的 Product Demo ADR，因此使用下一个连续可用编号 0020。

## Context

旧实现把 `OnlyCluster` 直接当具体策略基类，Strategy Factory 同时创建 Cluster 与 Indicator，Bar Subscription 携带 `indicator_ids`，Runtime Backtest Factory 和通用 Result 识别 MACD。这无法表达一个 Cluster 一个 Strategy、多个 Factor 的所有权，也把算法扩展泄漏到 Runtime。

## Decision

- Engine/Runtime 管理多个隔离 Cluster；Cluster 是容器且只持有一个 Strategy。
- Cluster 持有零个或多个 Factor；计算型 Factor 通过受限 Context 创建一个或多个 Indicator。
- Strategy 只读 Factor Snapshot/Score 并通过 Strategy Context 下单；Factor 无交易能力。
- Indicator 提供统一 Warmup、Reset、强类型 Snapshot 和可选带 Dimension 的 Canonical Score。
- Factor 分为 TimeSeries 与 CrossSection，并由稳定依赖图和固定 Pipeline 调度。
- Indicator 实例按 Runtime/Cluster/Factor/Indicator Scope 隔离。
- YAML 由 Factor Config 解析 Indicator Spec；Runtime 和 Assembly 不实例化具体指标。
- 通用指标留在 `src/onlyalpha/indicator/<type>/`；示例 Factor/Strategy 留在 `examples/`。
- 通用 Backtest Result 通过 Cluster 扩展、Factor 结果和 Indicator diagnostics 输出，不依赖具体算法类型。

## Rejected alternatives

拒绝 Cluster 等于 Strategy、Strategy Factory 创建 Indicator、Strategy 直接管理通用 Indicator、Factor 下单、Runtime 按 YAML 实例化具体 Indicator、任意 getter、共享可变 Indicator，以及把 MACD 示例策略留在核心库。

## Consequences

配置从 `strategies` 破坏性变更为 `clusters[].strategy + clusters[].factors[]`。旧 MACD 专用 Factory/Result/Runtime assembly 被移除。代价是首阶段产品装配仍只支持一个启用 Cluster、一个账户/数据源/Broker，Universe DataSource 展开仍待后续能力；核心截面 Pipeline 已具备同时间多资产稳定上下文。

## Validation

Indicator/Factor/Strategy/Cluster 专项测试、Product MACD Vertical Slice、全部历史 Integration 场景、100 次产品重放、100 次完整 Vertical Slice 重放、架构静态检查、全量 Pytest、Ruff 和 Mypy 共同验证。
