# Execution Processor Demo

这些示例全部复用 `OnlyIntegrationEnvironment`。正常成交由 Virtual Broker/Matching Engine 产生，所有回报固定经过
`Runtime Inbound Queue → OnlyExecutionProcessor`；Rejected、乱序和中途失败使用明确命名的标准 Broker Update/Fault Test
Adapter，仍不直接调用任何 Manager 成交接口。

```bash
UV_CACHE_DIR=/tmp/onlyalpha-uv-cache uv run python -m examples.execution_processor_demo.full_vertical_slice_demo
```
