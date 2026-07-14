# 并发与线程安全

## 1. 原则

不得无设计地混用：

- 多线程；
- asyncio；
- 多进程；
- SDK 回调线程。

## 2. 默认建议

- 单个 Cluster 内事件串行；
- 不同 Cluster 可独立调度；
- 实盘关键状态更新有确定顺序；
- CPU 密集型投研使用进程池；
- I/O 可使用 asyncio 或专用线程；
- 不在持锁时调用外部接口；
- 队列必须有界；
- 所有后台任务可停止和回收。

## 3. 共享状态

每份共享状态必须明确：

- 所有者；
- 读写线程；
- 锁；
- 生命周期；
- 一致性；
- 恢复方式。

## 4. Gateway 回调

第三方 SDK 回调不得直接执行复杂业务。

应：

1. 快速校验；
2. 标准化；
3. 投递到受控队列；
4. 由 Runtime/Event Bus 处理。

## 5. Web 调用

Web 线程不得直接操作非线程安全 Engine 对象。

通过 Command Queue 或 Application Service 进入受控执行上下文。

## 6. Backtest Runtime

第一版 `OnlyBacktestRuntime` 不创建后台线程，单线程同步执行 Clock、Timer、Pipeline、Dispatcher 和
ClusterManager。相同 deadline 的 Timer 使用 Clock 的 deadline/registration sequence/timer ID 顺序，
并在同时间 Bar 之前完成。Cluster callback 不并行；一个 Cluster 失败不改变其他 Cluster 的执行序列。
