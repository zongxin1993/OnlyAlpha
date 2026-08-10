# Unified Trading Runtime Market Rules

正式依赖链为 `Instrument Reference → Profile Resolver → Compiler → OnlyMarketRuleEngine → restricted
Runtime Ports → ExecutionProcessor → Result Collector`。Market Profile 是带生效区间、版本、来源与内容指纹的制度配置；
Instrument Reference 提供每个标的的 tick、step、lot、minimum notional、board、ST、停牌与 multiplier。

在目标架构中，`market` 是 Backtest/Sim/Live Trading Runtime 的必填配置，不存在 Legacy 缺省路径。当前配置 schema 仍识别
`BACKTEST/PAPER/LIVE/SHADOW`：其中 `PAPER` 是 Legacy Streaming Implementation / Sim Migration Source，standalone
`SHADOW` 是 unsupported implementation debt；两者不是目标 Runtime 或兼容合同。Research 可以复用 Reference、Calendar 与
MarketData Domain，但不承担正式交易 Market Rule lifecycle。

新规则不得写入通用 Order、Position 或 Account。Broker 只产生决定和更新，ExecutionProcessor 保持唯一正式交易状态写入者。
所有数值使用 Decimal，规则决定按稳定顺序记录。

| 能力 | A股 | 港股 | 美股 | 期货 | Crypto Spot | Perpetual |
| --- | --- | --- | --- | --- | --- | --- |
| T+0/T+1 | 正式 T+1 | 仅预留 | 仅预留 | Generic T+0 | Generic T+0 | 仅预留 |
| Long | 正式 | 仅预留 | 仅预留 | Generic | Generic | 仅预留 |
| Short | 禁止 | 仅预留 | 仅预留 | Generic | 不支持 | 仅预留 |
| Netting/Hedging | Long-only | 仅预留 | 仅预留 | Generic Hedging | Long-only | 仅预留 |
| Margin | Cash | 仅预留 | 仅预留 | Generic | Cash | 接口预留 |
| 24×7 | 否 | 否 | 否 | 否 | Generic | 接口预留 |
| Multi-session | 正式日间 | 接口预留 | 接口预留 | Generic | Continuous | 接口预留 |
| Fractional Qty | 否 | 接口预留 | 接口预留 | 否 | Generic | 接口预留 |
| Lot/Minimum Notional | 正式/无 | 接口预留 | 接口预留 | 整数合约 | Generic | 接口预留 |
| Price Limit | 正式基础规则 | 接口预留 | 接口预留 | 接口预留 | 无 | 接口预留 |
| Maker/Taker/Funding | 否 | 否 | 接口预留 | 否 | Taker Generic | 接口预留 |
