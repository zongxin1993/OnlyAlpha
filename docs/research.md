# 投研、因子、统计与绘图

## 1. 核心类型

```text
OnlyResearchEngine
OnlyResearchContext
OnlyFactor
OnlyFactorRegistry
OnlyFactorPipeline
OnlyFactorResult
OnlyDataset
OnlyFeatureSet
OnlyAnalyticsService
OnlyChartService
OnlyReportBuilder
```

## 2. 因子

因子需声明：

- 名称；
- 版本；
- 输入；
- 参数；
- 输出；
- 频率；
- 预热；
- 缺失值；
- 依赖；
- 元数据。

支持：

- 单因子；
- 多因子；
- 横截面；
- 时序；
- 增量；
- 批量；
- 缓存；
- 去极值；
- 标准化；
- 中性化。

## 3. 统计

至少预留：

- 累计收益；
- 年化收益；
- 波动率；
- Sharpe；
- Sortino；
- 最大回撤；
- Calmar；
- 胜率；
- 盈亏比；
- 换手率；
- 手续费；
- 滑点；
- IC；
- Rank IC；
- 分组收益；
- 因子衰减；
- 相关性；
- 回归。

## 4. 绘图

至少支持：

- 净值；
- 基准；
- 回撤；
- 收益分布；
- 月度热力图；
- 仓位；
- 买卖点 K 线；
- 订单成交；
- IC；
- 分组收益；
- 相关性；
- 滚动指标。

统计计算与绘图必须分离。
