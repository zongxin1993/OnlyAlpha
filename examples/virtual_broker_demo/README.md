# Virtual Broker Demo

复用统一 `OnlyIntegrationEnvironment`，展示 `ctx.orders.submit()` 到 Next-Bar 撮合、Broker Update、Runtime Inbound
Queue 和本地 Account/Position/Ledger 的完整路径。Demo 不手工制造成交。

```bash
UV_CACHE_DIR=/tmp/onlyalpha-uv-cache uv run python -m examples.virtual_broker_demo.run_demo
```
