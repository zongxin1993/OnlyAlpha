# Cluster 与策略插件设计

## 1. 定义

一个 Cluster 是一个独立策略运行单元。

建议类型：

```text
OnlyCluster
OnlyClusterContext
OnlyClusterConfig
OnlyClusterState
OnlyClusterResult
OnlyClusterMetadata
OnlyClusterRegistry
OnlyClusterLoader
```

## 2. 生命周期

```text
CREATED
LOADED
INITIALIZED
STARTING
RUNNING
PAUSED
STOPPING
STOPPED
FAILED
UNLOADED
```

建议回调：

```python
on_load()
on_initialize()
on_start()
on_market_event(...)
on_timer(...)
on_order_update(...)
on_trade_update(...)
on_stop()
on_unload()
on_error(...)
```

## 3. 隔离

Cluster 不得：

- 直接访问其他 Cluster；
- 共享可变全局状态；
- 直接访问数据库；
- 直接调用券商 SDK；
- 直接修改账户真值；
- 使用无命名空间缓存。

## 4. 静态注册

```python
registry.register("demo", OnlyDemoCluster)
```

必须检查：

- 重复注册；
- 类型；
- 版本；
- 配置；
- 元数据。

## 5. 动态加载

支持：

- 模块路径；
- 文件路径；
- 插件目录扫描；
- 配置驱动；
- 类型校验；
- 依赖校验；
- 卸载；
- 错误隔离。

## 6. 配置示例

```yaml
clusters:
  - id: etf_t0_001
    module: clusters.etf_t0
    class: OnlyEtfT0Cluster
    enabled: true
    runtimes:
      - paper
      - backtest
    config:
      instrument_id: 510300.XSHG
      timeframe: 1m
```
