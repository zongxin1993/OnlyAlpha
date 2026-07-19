# Multi-Market Fees

Fee 基于 Execution 计算，支持 notional、quantity、contract、fixed，支持方向过滤与最低费用。
`OnlyFeeBreakdown` 稳定保存 commission、exchange、clearing、regulatory、tax、transfer、borrow、funding、other 和扩展 components。

A 股 2025.1 基础 schedule：双向佣金（最低 5 CNY）、卖出印花税、过户费。Generic Futures 按合约；Generic Crypto 使用 Taker
notional fee。最低佣金跨部分成交累计需要 `OnlyOrderFeeAccumulator` 的生产集成，当前模型的单次 calculation 不声称已经解决
跨 Fill 累计。

