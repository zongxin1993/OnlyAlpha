# ADR-0001：Engine、Runtime 与 Cluster 分层

- 状态：Accepted
- 日期：2026-07-13
- 关联模块：engine、runtime、cluster

## 背景

系统需要在同一进程中同时运行回测、模拟盘、实盘和投研，并管理多个互相独立的策略。

## 决策

采用：

```text
OnlyEngine
  └── 多个 OnlyRuntime
        └── 多个 OnlyCluster
```

Engine 管理系统级资源。

Runtime 管理运行环境和状态隔离。

Cluster 管理策略生命周期。

## 结果

- 回测和实盘可共存；
- Cluster 不直接依赖具体运行环境；
- 新增 Runtime 不修改 Cluster 核心接口；
- 需要明确 Event、Clock、Cache 和 Account 的隔离键。
