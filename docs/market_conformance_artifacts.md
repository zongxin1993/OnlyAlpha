# Market Conformance Artifacts

Scenario Artifact 保存 definition、plan、summary、diagnostics、actions/assertions 及标准事实 Parquet 和 manifest。Backtest Artifact
新增 `profile_timeline.parquet` 与 `compiled_market_rules.parquet`，零行仍有稳定 schema。Pack Artifact 保存 status、coverage 与
pack fingerprint。指纹排除 run directory、墙钟、PID、hostname 和随机 run ID。
