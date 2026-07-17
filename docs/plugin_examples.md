# Example Plugin

示例 Python 组件位于独立的 `plugins/onlyalpha_examples` 包，根项目通过本地 editable dependency 安装。
MACD Strategy 只读取 MACD Signal Factor，Factor 通过核心 Indicator Registry 创建 `OnlyMacdIndicator`。

配置使用 `onlyalpha_examples.strategies.macd...` 与 `onlyalpha_examples.factors.macd_signal...` 动态类路径。
核心 `src/onlyalpha` 不包含示例 Strategy/Factor，`examples/` 不包含 Python 产品脚本。
