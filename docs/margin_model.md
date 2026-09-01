# Margin Model

`OnlyMarginModel` 以 `price × quantity × contract_multiplier` 计算 notional，再计算 initial 与 maintenance margin。
`OnlyMarginState` 独立表达 collateral、used、available、maintenance 和 ratio，保证金不会塞入 CashBalance。

A 股与 Generic T0/Crypto Spot 是 Cash。Generic Futures 使用 10% initial、8% maintenance，并验证资金不足拒绝。
平仓释放、逐日盯市和强平尚未接入生产 ExecutionProcessor；Cross/Isolated、Mark Price、Liquidation 与 Funding 仅是 Perpetual
后续扩展边界。

Order planning 的 margin reservation 接受当前 operation 已解析的 optional planning price，优先级为 Order price、explicit planning
price、legacy non-reference callback。它不读取 realtime market projection；因此 realtime-reference MARKET planning 与 Risk、fee 和
cash reservation 使用同一价格。Valuation 是独立 logical operation，仍使用既有 closed-Bar mark policy；本合同不引入 Trade-driven
valuation。
