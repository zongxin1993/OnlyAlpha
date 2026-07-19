# Market Scenario Assertions

`OnlyScenarioAssertionEngine` 输入 Expected Facts 与标准事实 Mapping，只执行 selector 和比较。首批 operator 包含存在性、数量、
相等、顺序、大小和精确 Decimal；近似 Decimal 必须显式提供 tolerance。Selector 使用稳定业务 ID，不使用行号。

Assertion 不读取 Manager，不解析 Profile，不重算 Settlement、Margin、Fee、T+1 或撮合。某类正式事实尚未由 Collector 提供时，
场景应失败或报告能力缺失，不能在 Assertion 中补算。
