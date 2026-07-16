# Indicator 标准库

Indicator 是无交易副作用的最底层确定性计算单元。统一接口包含 identity/type、ready、Warmup、`update_bar()`、`snapshot()`、`reset()` 和可选 `canonical_score()`。它不访问 Factor、Strategy、Cluster、Runtime、Broker 或 Manager，也不读取系统时间。

内置标准库位于各自子目录：MACD、RSI、EMA、SMA、ATR、Bollinger、Rolling Return、Rolling Volatility 和 Z-Score。Config 自己提供默认参数并校验；Factory 只把请求交给 Config。专有结果通过不可变强类型 Snapshot 输出，不增加任意 getter。

Canonical Score 的值域为 `[-1, 1]`，但 Dimension 决定语义：Momentum 的正值可以表示正动量，Volatility 的正值只表示波动较高，不能解释为看涨。原始 Snapshot 始终是权威结果。
