# BTCUSDT 单标的研究到回测

## 产品范围

使用已确认的 1 分钟价量动量因子，完成正式 Web 上的策略定义、策略研究、冻结、实验性回测和结果解读。保留现有模型配置和两轮因子研究。该实现不授予 SIM 或 LIVE 权限。

因子保持原版本：`((close - lag(close,20)) / lag(close,20)) * (volume / mean(volume,20))`。仅使用已收盘行情；均值含当前和之前 19 根。空仓且因子大于等于 `0.001` 时产生入场信号；持仓且因子小于等于 `0` 时产生离场信号；中间区间维持状态。预热不足、缺值及零分母不产生新入场信号。

## 交易约定

- Binance 现货 BTCUSDT，初始虚拟资金 `10000 USDT`，每次买入 `0.01 BTC`；仅一笔多头，不加仓、不借贷、不做空。
- 收盘决策最早在下一根开盘成交；买价为开盘乘 `1.0002`，卖价为开盘乘 `0.9998`。
- 每边手续费 `0.10%`，模拟以 USDT 收取，不使用 BNB 折扣。不声称这是历史账户真实费率。
- 数量和名义金额规则由 Binance 插件提供明确快照；不得将当前规则伪称为历史规则。
- 有待处理订单时不重复开仓。期末取消未成交订单，未平仓部分按最后收盘估值，独立显示未实现盈亏。
- 账户、数量、资本、费用和执行策略独立于 Strategy Revision 身份。

## 数据和证据

策略研究：2025-01-02 12:00 至 2025-01-03 00:00 UTC；固定回测：2025-01-03 00:00 至 12:00 UTC。2025-01-05 至 06 的受保护区间不得读取。预热数据单独绑定且不计入交易收益。此前已看过的样本只能称为探索性验证。

复用已确认 Factor 的精确依赖和实现。策略研究必须产生完整决策图的向量/逐条一致性证据；已有 Factor 统计报告不授予 Freeze。Freeze 唯一创建 immutable Strategy Revision，随后通过精确策略、策略研究结果、政策和 Qualification/Promotion 证据获准实验性 BACKTEST。

Rust Product Application 拥有命令及编排；复用现有 Calculation、Strategy、Execution、Runtime Persistence 和 Backtest。Python 仅保留独立算法职责；不新增根目录 `src/` 内容。不创建第二套交易引擎、策略 DSL 或 mutable latest 解析。

## Web 路线

研究会话中已确认因子 → 创建策略草稿 → 查看并确认交易规则 → 策略研究 → 冻结 → 配置并确认回测 → 进度/取消/恢复 → 结果 → 当前模型解读。

使用现有 Ant Design、Lightweight Charts 和 ECharts。研究、冻结、回测、失败和恢复状态用普通量化词汇表达。网络中断由系统核查原命令，不能要求用户解释内部命令或盲目重跑。

结果包括：净收益、收益率、最大回撤、手续费、成交/完整交易数、期末持仓、权益/回撤曲线、订单与成交的信号来源；同数量和成本口径的买入持有基准。12 小时结果不展示误导性年化收益或夏普率。模型基于精确结果进行解读，不拥有事实或准入权限。

## 参考与边界

- [TradingView Strategy Report](https://www.tradingview.com/support/solutions/43000764138-tradingview-strategy-report-how-to-start/)：图表、成交标记、结果分区。
- [QuantConnect Backtest Results](https://www.quantconnect.com/docs/v2/cloud-platform/backtesting/results)：核心指标、权益与回撤、订单/成交。
- [TradingView strategy execution](https://www.tradingview.com/pine-script-docs/concepts/strategies/)：明确收盘计算与下一可用时点成交。
- [Binance filters](https://github.com/binance/binance-spot-api-docs/blob/master/filters.md) 和 [fees](https://www.binance.com/en/fee/trading)：规则在插件边界，费率为显式模拟假设。

这些产品只提供交互和方法参考，不定义 OnlyAlpha Authority。范围不包括调参优化、多标的、期货、SIM 或 LIVE。Constitution Impact: NO。
