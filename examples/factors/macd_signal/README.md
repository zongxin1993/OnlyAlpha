# MACD Signal Factor

示例时序因子。它在 `on_initialize()` 中通过 Factor Context 创建核心库的 `OnlyMacdIndicator`，将强类型 MACD Snapshot 和 Canonical Momentum Score 解释为 Factor Snapshot/Score；不具备下单能力。
