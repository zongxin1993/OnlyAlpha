# ADR 0023: Backtest Results Framework Boundaries

- Status: Accepted
- Date: 2026-07-19
- Modules: result, runtime/backtest, analytics, artifact, report, engine, cli

## Context

旧 Backtest Result 主要面向运行摘要与 Strategy 扩展，订单、成交、账户和诊断缺少统一事实模型；Exporter 生成的 JSON/Markdown 也不足以支持独立分析、可验证 Parquet 和跨运行比较。

## Decision

- Result 定义不可变、provider-neutral 的标准事实和结构化诊断；
- Runtime-owned Collector 只观察正式 Snapshot/Audit，Strategy 只能通过受限 Recorder 写 Signal；
- Analytics 只消费 Result，并以 FIFO 从 Execution 重建 Trade；
- Artifact 只序列化 Result/Analysis，采用 staging、读回验证、SHA-256 和 Manifest-last 发布；
- Report 只格式化 Result/Analysis/Artifact Manifest；
- Engine 负责顺序编排，但 Runtime、Broker、Strategy 和插件均不依赖 Analytics、Artifact 或 Report；
- 保留旧 Result、CLI JSON、Run Manifest、Strategy Extension 与 determinism fingerprint 字段。

## Rejected Alternatives

- 从日志或 Strategy 扩展解析交易事实；
- 由 Broker 写文件或计算报告；
- 用 Execution 数量代替 Trade 数量；
- Artifact/Report 重新计算收益；
- 将 DataFrame、Arrow Table、文件句柄或插件 Client 放入 Result；
- 在指纹中加入 run_id、绝对路径、traceback 或墙钟元数据。

## Consequences

同一事实可产生稳定 Result、Analysis 和 Artifact Content 指纹。基础报告可自动化消费，失败保留首个真实根因。第一版只实现 long-only FIFO 和基础指标；高级风险、图表、HTML、归因、跨币种换算与流式超大结果集仍是后续工作。
