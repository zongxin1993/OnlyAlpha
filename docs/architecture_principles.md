# OnlyAlpha 架构原则

- Rule: 所有业务当前时间必须来自 Runtime Clock。
- Rule: Domain 和 Cluster 禁止直接读取系统时间。
- Rule: 每个 Runtime 拥有独立 Clock。
- Rule: Backtest Clock 不读取真实系统时间。
- Rule: Cluster 不能推进 Runtime Clock。
- Rule: UTC 表示绝对时间，Trading Calendar 解释市场时间。
- Rule: Monotonic Time 只用于间隔和性能，不作为业务时间持久化。
- Rule: Timer 顺序必须确定且可重放。
- Rule: Clock 不负责市场交易规则。
- Rule: Clock 不直接依赖 EventBus。
