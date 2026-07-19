# Trading Sessions

Session Model 支持多个阶段、午休、跨午夜与 24×7。状态含 phase、业务交易日、session name 和 allows_orders。
A 股基础 Profile 表达上午连续交易、午休不可下单、下午连续交易；当前日线收盘决策兼容路径保持不变。

跨午夜 session 用 anchor date 与 trading-day offset 映射业务日，不能以 UTC date 或自然日推断。Crypto Generic 的全日 session
周末可交易。盘前、集合竞价、收盘竞价、盘后和 maintenance/outage 已有 phase/状态表达，但详细撮合尚未实现。

