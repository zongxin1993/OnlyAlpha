# ADR 0056: A-Share Pre-Trade Rule Decision Authority

- Status: Accepted
- Date: 2026-08-05
- Modules: reference, market, risk, order, checkpoint, result, artifact

## Context

Runtime 已调用 `OnlyMarketRuleEngine`，但 Domain 仍公开第二套 `OnlyMarketOrderValidator`；Risk 也再次实现 Session、
Tick、Quantity 与 Price Limit。A 股 Profile 只有永久有效的静态 10%，独立 ST helper 会把创业板/科创板风险警示错误降为
5%，上下限未按 Tick 舍入，14:57 后阶段、科创板数量与拒绝诊断均不完整。扁平 Decision 无法证明所用制度和恢复权威。

## Decision

`OnlyMarketRuleEngine.evaluate_pre_trade()` 是唯一正式申报前市场规则权威，旧 Validator 和 Risk 内重复市场规则被删除。
Order 通过 Risk 编排消费 Market Decision；Risk 只继续处理账户/策略风险与 Reservation，不重算市场制度。

Reference Authority 只拥有按 Instrument + Trading Day 解析的证券事实；Profile Registry 只拥有左闭右开的制度版本。
`CN_A_SHARE_CASH@2025.1` 在 2026-07-06 截止，`2026.07` 自该日生效。Compiler 将有效版本与 Reference 的 board、
ST、RAW previous close、tick 和 lot 一次解析为最终 Session、Price Band 与 Quantity Policy。evaluate 阶段不重新读取原始
制度输入；compiled fingerprint 覆盖最终 Policy。

Decision 使用固定 Evaluation 顺序，主错误码是首个 FAILED Evaluation，并冻结交易日、阶段、提交价格/数量、价格带、数量
Policy、Reference/Profile/Compiled 指纹和动态价格笼子状态。Checkpoint participant schema 升至 3，Artifact schema 升至
4；旧版本不兼容，Reference、Profile 或 compiled fingerprint 变化均 Fail Closed。

集合竞价阶段被准确识别，但当前 Matching 不支持，返回 `TRADING_PHASE_NOT_SUPPORTED`。动态价格笼子需要正式实时
Quote/OrderBook Authority；Bar 或 previous close 不能冒充，因此本阶段明确记录 `NOT_EVALUATED`。

## Consequences

Generic T0/Futures/Crypto 也由 Compiler 生成统一的 compiled price/quantity policy，不保留 legacy adapter 或 compatibility
mode。A 股 T+1 bucket、费用闭环、Durable Execution、Virtual Broker 涨跌停流动性、集合竞价撮合与动态价格笼子不在本
ADR 范围。
