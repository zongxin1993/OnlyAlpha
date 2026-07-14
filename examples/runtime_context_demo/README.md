# RuntimeContext Demo

从仓库根目录运行：

```bash
uv run python examples/runtime_context_demo/basic_runtime_demo.py
uv run python examples/runtime_context_demo/multi_cluster_demo.py
uv run python examples/runtime_context_demo/runtime_isolation_demo.py
uv run python examples/runtime_context_demo/cluster_failure_demo.py
```

四个 Demo 分别验证 1m→3m 完整闭环、多 Cluster 主周期、多 Runtime 资源隔离和 Cluster 失败隔离。
