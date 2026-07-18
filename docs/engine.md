# OnlyEngine 设计

## 1. 职责

`OnlyEngine` 负责：

- 组件初始化；
- 生命周期；
- Runtime 规划和 Session 管理；
- Cluster 管理入口；
- Event Bus；
- Gateway 管理；
- Cache/Storage 管理；
- Application Service；
- 状态汇总；
- 优雅关闭；
- 系统级错误处理。
- 单 Cluster 配置加载与 Cluster Handle；
- Runtime Compatibility 分组；
- 共享基础设施冲突检查和引用计数；
- user_data 运行结果汇总。

## 2. 生命周期

```text
CREATED
CONFIGURING
READY
RUNNING
STOPPING
STOPPED
FAILED
```

非法状态迁移必须被拒绝。

产品链路固定为：`add_cluster()` 只校验并注册不可变 Definition；`initialize()` 生成
`OnlyEngineExecutionPlan` 并装配/持有真实 `OnlyRuntimeSession` 与 `OnlyClusterSession`；`start()` 启动 Session；`run()`
只执行已装配 Runtime；`stop()` 按 Cluster、Runtime、基础设施、输出/存储的逆序幂等关闭。一个 Engine 实例只能运行
一次，进入 `STOPPED` 或 `FAILED` 后必须新建 Engine。

```text
OnlyEngine
├── cluster_definitions: OnlyClusterRunConfig[]
├── cluster_sessions: OnlyClusterSession[]
├── runtime_sessions: OnlyRuntimeSession[]
└── execution_plan: OnlyEngineExecutionPlan
```

## 3. 唯一产品接口

```python
initialize()
start()
stop()
add_cluster_from_file(path)
add_cluster(config)
remove_cluster(cluster_id, policy)
validate()
run()
snapshot()

start_cluster(...)
pause_cluster(...)
resume_cluster(...)
```

Backtest 历史回放中途加入/卸载 Cluster 在首阶段返回结构化“不支持当前 Runtime 阶段”；API、状态门禁、失败回滚与资源释放已存在。

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
