# OnlyAlpha Integration Demo

本 Demo 使用一个 `OnlyIntegrationEnvironment` 和现有正式 Runtime/Context/Manager 接口，按顺序运行 12 个场景：

```text
Runtime → 1m/3m Pipeline → Cluster → Order → Risk → Placeholder Execution
→ standardized Fill/Trade → Position → Allocation → Strategy Ledger → Event → Snapshot
```

`OnlyPlaceholderExecutionService` 只记录提交，不生成 Accepted 或 Fill。场景显式注入标准化 Gateway Update 和
`OnlyPositionTrade`，再交给 Runtime 单写入者入口编排。

运行：

```bash
UV_CACHE_DIR=/tmp/onlyalpha-uv-cache uv run python -m examples.integration_demo.run_all
```
