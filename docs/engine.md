# OnlyEngine 设计

## 1. 职责

`OnlyEngine` 负责：

- 组件初始化；
- 生命周期；
- Runtime 注册和管理；
- Cluster 管理入口；
- Event Bus；
- Gateway 管理；
- Cache/Storage 管理；
- Application Service；
- 状态汇总；
- 优雅关闭；
- 系统级错误处理。

## 2. 生命周期

```text
CREATED
INITIALIZING
READY
RUNNING
STOPPING
STOPPED
FAILED
```

非法状态迁移必须被拒绝。

## 3. 建议接口

```python
initialize()
start()
stop()
close()

register_runtime(...)
remove_runtime(...)
start_runtime(...)
stop_runtime(...)

load_cluster(...)
unload_cluster(...)
start_cluster(...)
stop_cluster(...)

get_status()
health_check()
```

## 4. 禁止职责

OnlyEngine 不实现：

- 策略；
- 因子；
- SQL；
- 券商 SDK；
- 撮合算法；
- 图表；
- 具体费用公式。

## 5. 关闭顺序

建议：

1. 停止接受新请求；
2. 停止 Cluster 新任务；
3. 停止 Runtime 数据输入；
4. 等待在途事件；
5. 刷新订单、成交和状态；
6. 落盘；
7. 关闭 Gateway；
8. 关闭 Event Bus；
9. 释放线程、进程和句柄；
10. 标记 STOPPED。

关闭流程必须幂等。
