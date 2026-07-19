# ADR 0024: Multi-Market Simulation Framework

- Status: Accepted
- Date: 2026-07-19
- Modules: market, broker, execution, position, result, artifact

## Decision

采用版本化 Market Profile 组合正交的 Session、Settlement、Position、Short、Margin、Price、Quantity、Fee、Liquidity、Slippage
和 Matching 规则。Instrument Reference 提供每标的动态规格。Broker 只作规则判定和产生成交事实，ExecutionProcessor 保持唯一正式
状态写入者；Result Collector 观察 Settlement、Margin 和 Rule Decision。

Legacy 未声明 Profile 的配置保持原行为。A 股是第一个正式 Profile，三个 Generic Profile 只用于证明核心没有 T+1、整数股、
Long-only 或工作日硬编码。

## Rejected

- 在 Position 中固定 T+1；
- 在 Order/Broker 中固定 100 股、禁止卖空或 A 股税费；
- 将自然日视为 Trading Day；
- 将 Fee Breakdown 压平成 commission；
- 为 Futures/Crypto 建立与现有 Instrument/Position 平行的领域模型。

## Consequences

规则变化进入 Profile 指纹，Settlement 的可用与法律清算分离，Cash 与 Margin 状态分离。完整 Futures/Perpetual 生产纵切面、
Borrow、Funding、Liquidation、Tick/Order Book 撮合仍需后续 ADR/实现，不得因已有接口宣称正式支持。

