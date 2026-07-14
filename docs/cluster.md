# Cluster 与策略插件设计

Cluster 可通过配置绑定 Risk Profile 和 Account/Instrument 权限，但不能删除 Mandatory System Rules，也不能取得
RiskService、Reservation、Account 或 Position 的写权限。策略仅能读取 `ctx.risk` immutable Snapshot，并通过
`ctx.orders.submit()` 触发同步最终审批；本阶段没有 `on_risk_xxx` 回调。

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

## Bar 回调

策略 Bar 接口为 `on_bar(primary_bar, OnlyBarContext)`。Context 包含不可变、按该 Cluster Subscription
裁剪的 `OnlyMarketDataSnapshot` 与受限 Runtime View，不暴露 Runtime EventBus、MarketData Cache、
Aggregator、Gateway 或 Service Container。
默认以最小订阅 TIME step 为主周期，也可显式覆盖。PRIMARY_ONLY 保证同一逻辑时间片最多调用一次；
辅助周期通过 `latest_closed/was_updated/require_same_event_time` 查询，不分别触发依赖顺序的回调。

Dispatcher 必须在 Data Ready Barrier 后调用 Cluster。Cluster 异常形成独立 dispatch failure，不阻止
同 Runtime 其他 Cluster；Cluster 间执行顺序稳定但不承诺业务依赖。Dispatcher 只选择目标，实际调用、
状态迁移、Timer/Subscription 清理和错误隔离由 `OnlyClusterManager` 完成。

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

## Order 权限

Cluster 不拥有 OrderManager，也不直接访问 Gateway。策略只能调用 `ctx.orders.submit/cancel/get/require/
list_open/list_recent`，返回值均为不可变 Snapshot。Runtime 自动绑定 cluster_id；一个 Cluster 不能查询或
撤销另一个 Cluster 的订单，也不能调用成交应用、状态赋值或 Venue ID 修改函数。

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
