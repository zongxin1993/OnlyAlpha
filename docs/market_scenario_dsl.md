# Market Scenario DSL

计划中的 YAML Schema 使用带版本的 metadata、一个 Profile 请求、Synthetic Instrument Reference、UTC Bars、确定性 Action 和 Expected Assertions。价格、数量、金额、费率均为字符串 Decimal。市场制度只来自 Profile，标的差异来自 Reference，场景不得重复写 T+1、lot、价格限制或卖空制度。

当前已交付严格 `OnlyMarketScenarioParser`：拒绝未知字段，要求 schema version `1`、带时区 UTC 时间和带引号 Decimal，
并复用正式 `OnlyMarketConfig` 与 Reference Config 解析。当前 schema 仍识别源码 spelling
`BACKTEST/PAPER/LIVE/SHADOW`；除 `BACKTEST` 外均在规划时明确返回 `SCENARIO_RUNTIME_MODE_UNSUPPORTED`。其中
`PAPER` 是 Sim Migration Source，standalone `SHADOW` 是待删除实现债务；两者不是目标 Runtime。目标 taxonomy 是
`RESEARCH/BACKTEST/SIM/LIVE`。`SIM` 已有独立 enum/config/Factory 和 realtime Virtual Broker normal path，但当前 Scenario
schema/Runner 尚未接入其长生命周期 driver；因此不能把 SIM 写成已可执行 Scenario。当前 Runner 只对可执行
`BACKTEST` plan 通过 `OnlyEngine` 运行完整产品纵切面；Parser 能识别某个 legacy spelling 不表示该场景可执行。
