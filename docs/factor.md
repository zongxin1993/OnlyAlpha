# Factor 模型

Factor 将一个或多个 Indicator 的权威 Snapshot 或 Canonical Score 转换为有业务含义的 `OnlyFactorSnapshot` 和 `OnlyFactorScore`。Factor 没有 Order、Position mutation、Ledger mutation、Account mutation、Risk approval 或 Broker 能力。

- `OnlyTimeSeriesFactor`：按单资产时间序列 Bar 更新。
- `OnlyCrossSectionFactor`：接收同一事件时间的 Point-in-Time Universe，键稳定排序，用于排名、分位数和多因子组合。

Factor 在 `on_initialize()` 中按自身 Config 的 Indicator Spec 调用 `ctx.indicators.create_for_bars()`。YAML 只声明 Spec；Runtime/Assembly 不实例化 MACD、RSI 等具体类。Factor Dependency Graph 检查唯一 ID、依赖存在、循环和时序/截面阶段合法性。

`OnlyFactorScore` 的 value 约束为 `[-1, 1]`，confidence 为 `[0, 1]`，并保留 Dimension、事件时间和质量标志。Strategy 的 Required Factor 未 READY 时不会收到正式 Bar 回调。
