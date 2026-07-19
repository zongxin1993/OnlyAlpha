# 回测结果框架实现报告

## 1. 修改前分析

修改前 `OnlyBacktestResult` 已包含运行、数据、执行、绩效和最终 Snapshot，但 Order/Broker Trade 与 Strategy Extension 并非统一分析事实；Engine Manifest 负责运行布局，Event/Audit 和各 Manager 才是交易真值。旧报告由 Exporter 直接从投影生成，缺少标准 Signal/Execution/Equity、结构化根因、Parquet Schema 与内容指纹。

## 2. 架构设计

依赖方向固定为 `Result ← Collector → Runtime facts`，随后 `Result → Analytics → Artifact → Report`。Engine 只编排。Result 不含文件或插件对象；Analytics 不读取 Runtime；Artifact 不计算 PnL；Report 不计算 Return。

## 3. Result 模型

核心对象为 `OnlyBacktestResult`、`OnlyBacktestFacts`、`OnlyBacktestDiagnostics`，以及 Signal、OrderRequest、Order、Execution、Position、Account、Equity、Failure/Warning Record。记录不可变、稳定排序，Money/PnL 保持 `Decimal`；旧 Strategy Extension 和 Result 字段兼容保留。

## 4. Collector

Collector 从 Market Data Audit、Order/Execution/Position/Account 公开 Snapshot 与受限 Strategy Recorder 收集事实。Bar 只保留统计而不复制巨大序列。Collector 在 CREATED→STARTED→SEALED 生命周期中观察数据，不下单、不修改 Manager、不推进 Clock，因此不会改变交易行为。异常按 sequence 保留首个真实根因。

## 5. Analytics

Trade Builder 对 Execution 执行 long-only FIFO，支持分批建仓、分批平仓和费用守恒。Analytics 输出 Net Profit、Total Return、Equity Drawdown、Order/Execution/Trade Statistics 与 Exposure。净值不足、零初始资金、未匹配平仓或开放 Lot 返回 warning/`None`，不虚构年化指标。

## 6. Artifact

Manifest 为每个文件记录 Schema 版本、Parquet 行数、SHA-256 和内容指纹。标准输出包括三个数据 JSON、七个 Parquet、Artifact Manifest 和 Report。Writer 在同盘 staging 中写入并读回校验，先发布数据，最后发布 Manifest；失败清理 staging。

固定往返示例行数为 Orders 2、Executions 2、Trades 1、Positions 0、Accounts 1、Equity 1、Signals 2。

## 7. Report

CLI 默认输出单行 JSON，例如 `bar_count`、`trade_count`、`total_return`、三个指纹和路径。`--console-report` 显示 Run/Trading/Performance/Artifacts。Markdown 包含 Run、Data、Strategy、Order、Execution、Trade、Performance、Final Account/Positions、Diagnostics、Artifacts、Fingerprints，不生成图表。

## 8. Fingerprint

Result 指纹包含排序事实、最终状态、稳定诊断和数据身份；Analysis 指纹包含算法版本、FIFO Trade 与所有分析值；Artifact Content 指纹包含各文件内容身份。三者排除 run_id、起止墙钟、绝对路径、主机/PID、临时目录、traceback 和文件时间。固定示例、Synthetic MACD 与 Tushare CACHE_ONLY 的重复运行均一致。

## 9. Diagnostics

结构化失败包含 `stage`、`exception_type`、`message`、`sequence`，并可带 `ts_event`、instrument/cluster/strategy/account/order/execution ID。Replay 聚合失败不会覆盖 Pipeline 或 Strategy 的首个根因；Artifact/Report 失败追加独立 stage。

## 10. 测试

真实执行：

```text
OnlyAlpha: mypy src/onlyalpha; pytest -q; ruff check .; format/diff check
OnlyAlpha-examples: mypy src/onlyalpha_examples; pytest -q; ruff/format/diff check
OnlyAlpha-plugins: workspace pytest; ruff; mypy
```

阶段 7 完成时核心仓为 363 passed，Examples 为 4 passed。覆盖无交易、FIFO 分批、费用守恒、零初始净值、回撤恢复、高精度 Decimal、原子失败、正式 CLI、MACD、多 Cluster 与 CACHE_ONLY。

## 11. Tushare 验收

2026-07-19 通过正式 CLI 运行 600000.XSHG 2025 日线：243 Bars、4 Signals、4 Orders、4 Executions、2 Trades，Ending Equity `999906.00 CNY`，Total Return `-0.000094`。随后移除 Token，以同一 user-data 执行 CACHE_ONLY；Result `0a2cc5…a9899d`、Analysis `4f93ae…1191b`、Artifact Content `b92a92…e8e7356` 与在线运行完全一致。
