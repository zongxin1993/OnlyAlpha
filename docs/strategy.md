# Strategy 模型

`OnlyStrategy` 是交易决策单元，与 `OnlyCluster` 分离。Strategy 读取一个或多个 Factor Snapshot/Score，维护私有决策状态，并且只能通过 `OnlyStrategyContext.orders` 下单。

Context 可用能力：Clock、MarketData 只读视图、Factor 只读视图、Instrument、Order capability、Position/Account/Ledger/Risk 只读视图、Logger 和 Timer。它不暴露 Indicator Registry、Factor Registry mutation、Runtime、Manager、Broker、EventBus 或 DataSource。

Context 只能绑定一次，绑定前访问会抛出明确异常。通用结果不识别具体策略类型；`build_result_extension()` 返回 JSON 兼容扩展。MACD 示例策略位于 `examples/strategies/macd/`，只读取 `OnlyMacdSignalFactorSnapshot`，不创建或计算 MACD。
