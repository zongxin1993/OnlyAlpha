# Risk Demo

这些脚本用固定回测时钟和 Placeholder Execution 展示 ACCEPT、规则拒绝、Cluster Profile、即时预占、Fail Closed 和不可变 Snapshot。它们不会连接真实券商，也不会生成成交。

从仓库根目录运行，例如：

```bash
uv run python examples/risk_demo/accepted_order_demo.py
uv run python examples/risk_demo/reservation_demo.py
```
