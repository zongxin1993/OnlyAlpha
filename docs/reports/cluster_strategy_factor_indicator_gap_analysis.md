# Cluster、Strategy、Factor、Indicator 架构差距分析

日期：2026-07-16

## 分析依据

本分析以当前工程代码、`AGENTS.md`、总体/Runtime/Cluster/MarketData/测试文档及既有 ADR 为准，不以历史对话或旧工程为实现依据。

## 修改前的实际问题

| 边界 | 修改前行为 | 架构风险 | 目标 |
|---|---|---|---|
| Cluster / Strategy | 具体策略继承 `OnlyCluster` 并在 Cluster 回调里交易 | 容器、算法和生命周期无法独立演化 | Cluster 只持有且调度一个 Strategy |
| Strategy / Indicator | Strategy Factory 同时构造策略与 Indicator | 装配层知道算法内部依赖 | Strategy Factory 只创建 Strategy |
| Factor | 没有正式 Factor 抽象、Context、Factory、Registry 或依赖图 | 无法表达指标组合、Warmup 和多因子依赖 | 区分 TimeSeries/CrossSection Factor，并做 DAG 校验 |
| Runtime / Indicator | Backtest 装配识别 MACD，订阅携带 `indicator_ids` | Runtime 被具体算法污染 | Factor 通过 Cluster-scope Registry 创建 Indicator |
| Context | Strategy 通过通用 Runtime Context 读取 Indicator | 权限边界不精确 | Strategy 只读 Factor；Factor 只有 Indicator/行情等非交易能力 |
| Result | 通用回测 Result 写入 MACD 信号字段 | 核心结果模型依赖示例算法 | 通用 Cluster Result 提供扩展、Factor 结果和 Indicator 诊断 |
| 示例位置 | MACD Factor/Strategy 位于 `src/onlyalpha` | 示例业务成为核心生产依赖 | MACD Indicator 留在标准库，Factor/Strategy 移至 `examples/` |
| 截面语义 | 没有 Point-in-Time Universe 与缺失成员质量 | 截面排名可能混合时点或静默缺失 | 不可变、稳定排序、同一时点并显式缺失成员的 Universe Snapshot |

## 必须保留的既有纵切面

重构不能绕过或重写已批准的交易链：`Run Config → Runtime Factory → Replay → MarketData → Cluster → Orders → Risk → Virtual Broker → Execution Processor → Position → Allocation → Strategy Ledger → Account → Result`。Order、Risk、Execution、Position、Allocation、Ledger 与 Account 的正式接口和业务语义保持不变。

## 变更边界

本任务只调整策略计算体系的所有权、装配、Context、配置和结果扩展：

- 新增 Strategy/Factor/Indicator 正式抽象及注册表；
- 把 Cluster 改为容器，并固定 `Indicator → Factor → Strategy`；
- 迁移 Product MACD 示例和配置；
- 删除具体算法从 Runtime、Subscription 和通用 Result 的泄漏；
- 保留核心 MACD 及其他标准 Indicator，实现统一 Snapshot/Score/Factory；
- 补齐单元、直接集成、完整纵切面与确定性重放证据。

不在范围内：真实 Gateway、真实账户、分布式执行、生产级 CrossSection 数据同步服务、Live/Paper 外部适配。

## 验收判据

只有静态边界、组件测试、历史全量测试、Integration Demo、Product MACD、完整 Vertical Slice 和至少 100 次相同输入重放全部通过，且无跳过/删除/放宽旧测试，最终报告才可标记 `ACCEPTED`。
