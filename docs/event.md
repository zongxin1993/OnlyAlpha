# Event Bus 设计

## 1. 事件类型

```text
OnlyEvent
OnlyMarketEvent
OnlyTickEvent
OnlyBarEvent
OnlyOrderEvent
OnlyTradeEvent
OnlyPositionEvent
OnlyAccountEvent
OnlyTimerEvent
OnlyRiskEvent
OnlySystemEvent
OnlyInstrumentEvent
```

## 2. 公共字段

```text
event_id
event_type
timestamp
engine_id
runtime_id
cluster_id
source
sequence
payload
metadata
```

## 3. 顺序

同一订单、同一 Instrument、同一 Cluster 的关键事件必须定义顺序保证。

## 4. 背压

不得使用无限队列。

必须定义：

- 最大容量；
- 满载行为；
- 丢弃策略；
- 阻塞策略；
- 优先级；
- 告警；
- Metrics。

交易和账户事件通常不得静默丢弃。

## 5. 异常隔离

单个处理器异常：

- 记录上下文；
- 不破坏 Event Bus 主循环；
- 根据事件类型决定重试、隔离或停止；
- 不无限重试。

## 6. 关闭

关闭时：

- 停止接收新事件；
- 处理或持久化在途事件；
- 退出消费者；
- 释放资源。
