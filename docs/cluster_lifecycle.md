# Cluster 组件生命周期

```text
create container
→ bind Runtime Context
→ bind Factor Contexts
→ Factor.on_initialize (create scoped Indicators)
→ bind Strategy Context
→ Strategy.on_initialize
→ approve aggregated subscription
→ start Factors
→ start Strategy
→ RUNNING / PAUSED
→ stop Strategy
→ stop Factors in reverse order
```

所有 Context 只绑定一次。Manager 修改状态并负责 Timer/Subscription 清理、失败记录和回调隔离。Cluster 自身不实现具体策略、因子或指标算法。
