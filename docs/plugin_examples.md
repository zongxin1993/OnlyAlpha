# Example Plugin

官方 Strategy、Factor、扩展组件和 Cluster 配置统一归属并列的 `OnlyAlpha-plugins` 项目；官方示例的入口、教程和生成结果
统一归属 `OnlyAlpha-examples`。OnlyAlpha 核心不得反向依赖二者。

核心 `src/onlyalpha` 不包含官方 Strategy/Factor/Cluster 配置。核心纵切面使用 `tests/runtime_support` Test Adapter，且不会打包。
