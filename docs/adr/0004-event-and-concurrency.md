# ADR-0004：首阶段同步有界事件总线与 Cluster 串行语义

- 状态：Accepted
- 日期：2026-07-13
- 关联模块：event、runtime、cluster、concurrency

## 背景

系统未来需接收 SDK 回调并并行运行多个 Runtime，但初始化骨架必须先保证确定顺序、背压、关闭和异常隔离，且不能过早绑定 asyncio 或线程模型。

## 决策

第一阶段采用进程内同步 `OnlyEventBus`：队列有明确容量，FIFO drain；handler 异常被记录并允许其他 handler 继续。每个 Runtime 拥有独立 Event Bus，单 Cluster 默认串行。关闭后拒绝新事件并排空已有事件。

## 备选方案

直接采用 asyncio 会把事件循环所有权扩散到 Engine、Web 和 SDK 边界；立即建立线程池会增加顺序和关闭测试成本；无限队列不满足背压要求。

## 结果与验证

当前实现不提供吞吐承诺、持久队列、优先级或重试。后续引入异步/线程调度属于公共并发语义变更，必须更新 ADR。测试验证容量、FIFO、关闭、handler 异常隔离和 Runtime 隔离。
