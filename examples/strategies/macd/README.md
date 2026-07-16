# MACD Strategy

示例策略只读取 `OnlyMacdSignalFactorSnapshot`，将金叉/死叉转换为订单并且只通过 `OnlyStrategyContext.orders` 提交。MACD 计算、Warmup 和评分均属于 Factor 内部使用的核心 Indicator。
