# Backtest Results Framework

OnlyAlpha 的正式结果链是：

```text
Runtime facts → Result Collector → immutable Result → Analytics → Artifact → Report
```

依赖方向只能向右。Report 不重新计算指标，Artifact 不推导 PnL，Analytics 不读取 Runtime、插件、日志或文件，Collector 不参与交易决策。

## Result 与 Collector

`onlyalpha.result` 定义 provider-neutral、不可变且以 `Decimal` 表示数值的 Signal、Order Request、Order、Execution、Position、Account 和 Equity 记录。`OnlyBacktestResult` 保留旧摘要和 Strategy 扩展，同时新增 `facts`、`diagnostics` 与 `result_fingerprint`。

Collector 在 Runtime 正式生命周期中只读取 Manager Snapshot、Audit 和受限 Strategy Result Recorder。记录按稳定 sequence 封存；失败保留 stage、异常类型、消息、时间、标的和首个根因。Collector 不能提交订单、修改账户或控制回放。

## Analytics

`OnlyBacktestAnalyticsService` 是纯函数式服务。它基于 Execution Facts 使用 long-only FIFO 重建 Trade，正确处理分批成交和费用分摊，并生成：

- 收益、净利润和基础回报；
- 净值回撤及恢复状态；
- Trade、Order、Execution 和 Exposure 统计。

数据不足时返回 `None` 与稳定 warning，例如 `INSUFFICIENT_EQUITY_CURVE`；不会虚构 Sharpe、年化收益或未知估值。

## Artifacts

单 Runtime 的标准文件位于 `runs/<engine>/<run>/`；多 Runtime 位于 `runtimes/<runtime>/artifacts/`：

| File | Purpose |
| --- | --- |
| `summary.json` | Result 与 Analysis 摘要 |
| `diagnostics.json` | failures、warnings、首个根因 |
| `data_manifest.json` | 数据来源与统计 |
| `artifact_manifest.json` | Schema、行数、SHA-256 和内容指纹 |
| `orders.parquet` | 标准订单事实 |
| `executions.parquet` | 标准成交事实 |
| `trades.parquet` | FIFO 重建交易 |
| `positions.parquet` | 持仓事实 |
| `accounts.parquet` | 账户事实 |
| `equity.parquet` | 净值与 Exposure 事实 |
| `signals.parquet` | Strategy 标准信号 |
| `report.md` | 无图表 Markdown 报告 |

Artifact 先写 staging、读回验证，再发布 Manifest；失败不留下宣称完整的 Manifest。

## Reports and CLI

默认 `onlyalpha run` 输出单行简洁 JSON，不包含巨大订单或净值列表。使用 `--console-report` 可在 JSON 前显示 Run、Trading、Performance 和 Artifact 摘要。`report.md` 包含 Run、Data、Strategy、Order、Execution、Trade、Performance、Final Account/Positions、Diagnostics、Artifacts 与 Fingerprints。

## Fingerprints

Result、Analysis 和 Artifact Content 指纹基于排序后的规范内容。它们包含事实、最终状态、稳定诊断和数据内容身份；排除 run_id、墙钟时间、绝对路径、PID、hostname、traceback、临时目录与文件时间。相同配置和数据应产生相同指纹。

当前范围不包含 HTML、图表、高级风险指标、归因、参数实验或跨币种汇率换算。

Scenario Assertion 只能消费本结果链的标准事实。Profile timeline、compiled rule identity 和 market decisions 已由正式
Collector 投影。FeeManager 已在正式成交事务中消费唯一 Fee Instruction；完整 adjustment/reconciliation timeline 的 Artifact
投影仍待 Live/Paper 对账入口落地，Assertion 不得离线重算费用或把 Broker Snapshot 差额当作新费用。
