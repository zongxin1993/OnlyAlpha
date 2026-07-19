# Results Framework Handoff

## Stable public behavior

- `onlyalpha run` 默认仍输出单行 JSON；旧字段未删除。
- `OnlyBacktestResult` 的旧构造参数保持不变，新字段均有默认值。
- Strategy 自定义 Result Extension 继续保留，标准 Signal 通过 `ctx.results.record_signal()` 记录。
- 旧 Run Manifest 和 determinism fingerprint 保留；新增三层结果指纹。

## Extension rules

- 新事实类型放在 `onlyalpha.result`，不得依赖插件、CLI、pandas 或 pyarrow。
- 新指标放在 `onlyalpha.analytics`，输入必须是 Result DTO/只读端口。
- 新文件格式放在 `onlyalpha.artifact`，不得计算交易或绩效。
- 新展示放在 `onlyalpha.report`，不得读取 Runtime 内部状态。
- 任何写入失败必须保留原 Runtime failure，并增加明确的 `ARTIFACT_WRITE` 或 `REPORT` failure。

## Known limits

当前 Equity Collector 只保证正式可用的账户快照；若净值点不足，回撤/Exposure 会明确告警。Trade Builder 是 long-only FIFO。跨币种结果不做隐式加总。HTML、图表、Sharpe 等高级指标和大规模流式事实集未实现。

## Verification

核心仓运行 `pytest -q`、`ruff check .`、定向 `ruff format --check` 和 `mypy src/onlyalpha`。Examples 运行对应四项命令。Plugins 运行 workspace 测试与静态检查；真实 Tushare 测试需要显式 Token，CACHE_ONLY 验收必须移除 Token。
