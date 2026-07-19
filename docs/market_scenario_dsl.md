# Market Scenario DSL

计划中的 YAML Schema 使用带版本的 metadata、一个 Profile 请求、Synthetic Instrument Reference、UTC Bars、确定性 Action 和 Expected Assertions。价格、数量、金额、费率均为字符串 Decimal。市场制度只来自 Profile，标的差异来自 Reference，场景不得重复写 T+1、lot、价格限制或卖空制度。

当前已交付严格 `OnlyMarketScenarioParser`：拒绝未知字段，要求 schema version `1`、带时区 UTC 时间和带引号 Decimal，
并复用正式 `OnlyMarketConfig` 与 Reference Config 解析。Domain 支持 BACKTEST/PAPER/LIVE/SHADOW；后三者规划时明确返回
`SCENARIO_RUNTIME_MODE_UNSUPPORTED`。正式 Engine Runner 尚未交付，Parser 可用不代表场景可自动执行。
