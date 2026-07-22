# Multi-Market Fees

正式产品装配链为：

```text
market.fees + brokers[].fees
→ versioned Market/Broker Schedule Registry
→ OnlyRuntimeAssemblyConfig
→ Runtime-owned OnlyFeeResolver
→ OnlyFeeInstruction
```

Market `DEFAULT` 跟随按 Instrument/Trading Day 编译的 Profile schedule；Broker 不存在 Core 隐式默认合同，必须显式选择
`NONE`、已注册 Schedule 的 `MODEL` 或 `REPORTED`。Registry 拒绝重叠有效期，Factory 在 Runtime 启动前验证运行起始日的
有效版本。Virtual Broker 不报告费用时使用 `reported_fee=None`，不能用零伪装外部确认。

Fee 基于 Execution 计算，支持 notional、quantity、contract、fixed，支持方向过滤与最低费用。
`OnlyFeeBreakdown` 稳定保存 commission、exchange、clearing、regulatory、tax、transfer、borrow、funding、other 和扩展 components。

A 股 2025.1 基础 schedule：双向佣金（最低 5 CNY）、卖出印花税、过户费。Generic Futures 按合约；Generic Crypto 使用 Taker
notional fee。最低佣金跨部分成交累计需要 `OnlyOrderFeeAccumulator` 的生产集成，当前模型的单次 calculation 不声称已经解决
跨 Fill 累计。
