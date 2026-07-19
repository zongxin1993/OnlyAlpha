# Market Scenario DSL

计划中的 YAML Schema 使用带版本的 metadata、一个 Profile 请求、Synthetic Instrument Reference、UTC Bars、确定性 Action 和 Expected Assertions。价格、数量、金额、费率均为字符串 Decimal。市场制度只来自 Profile，标的差异来自 Reference，场景不得重复写 T+1、lot、价格限制或卖空制度。

本轮未交付 Parser/Runner；该接口是明确预留，不是可运行能力。

