# OnlyAlpha Integration Demo

本 Demo 使用统一 `OnlyIntegrationEnvironment` 和正式 Runtime/Context/Broker/Manager 接口，运行 23 个自动化场景：

```text
Runtime → 1m/3m Pipeline → Cluster → Order → Risk → ExecutionService → Virtual Broker
→ Next-Bar Matching → Runtime Inbound Queue → OnlyExecutionProcessor → Order → Position → Allocation
→ Strategy Ledger → Account → Risk → Event → Snapshot
```

正常买卖、部分成交和撤单场景不手工制造 Accepted/Fill/Trade。只有冲突、重复和乱序失败路径使用明确的 fault adapter
向 Runtime 正式 inbound Port 注入标准化 Broker Update。

运行：

```bash
UV_CACHE_DIR=/tmp/onlyalpha-uv-cache uv run python -m examples.integration_demo.run_all
```
