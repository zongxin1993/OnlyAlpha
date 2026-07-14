# Order 订单组件

## 1. 边界与所有权

每个 Runtime 独占一个 `OnlyOrderManager`，它是该 Runtime 订单状态、版本和索引的唯一可信来源；同一
Runtime 的多个 Cluster 共享它，但 Cluster 只能使用自动绑定 Runtime/Cluster Scope 的 `ctx.orders`。
Order 组件不实现 Risk、Position、Account、Trade 管理、撮合或真实券商连接。

## 2. Request、Entity 与 Snapshot

`OnlyOrderRequest` 表达策略意图，只包含 request ID、Instrument、方向、类型、数量、TIF、可选账户、
价格、标签和元数据；它不包含 Runtime、Cluster、Order ID、Venue ID、状态或成交。第一阶段只接受
MARKET 和 LIMIT，并显式验证价格与 GTD expiry。`OnlyCancelOrderRequest` 是独立幂等命令。

`OnlyOrder` 是 Manager 私有的受控可变聚合，不能从 Context 或 Query 获得，也不能直接赋值状态。
所有外部读取均返回 frozen、可序列化的 `OnlyOrderSnapshot`，其中包含 Scope、身份、状态、数量、均价、
各生命周期时间、version、外部序列以及 rejection/failure。

订单标识使用 `OnlyOrderRequestId`、`OnlyOrderId`、`OnlyClientOrderId`、`OnlyVenueOrderId`；成交去重还使用
`OnlyTradeId` 与 `OnlyVenueTradeId`。Backtest 的 Order/Client ID 生成器按 Runtime 独立递增，固定输入可重放。

## 3. 状态机

```text
CREATED → SUBMITTED → ACCEPTED → PARTIALLY_FILLED → FILLED
                        └────────→ PENDING_CANCEL → CANCELLED
SUBMITTED → REJECTED | FAILED
ACCEPTED/PARTIALLY_FILLED → EXPIRED | FAILED
```

Fill 可先于 Accepted 到达；迟到 Accepted 只能补充 Venue ID，不能把 PARTIALLY_FILLED、FILLED 或 CANCELLED
回退到 ACCEPTED。取消后迟到 Fill 可记录为警告事实并累计成交，但状态保持 CANCELLED。取消订单的
`remaining_quantity` 为零，历史 `filled_quantity` 和均价仍保留。非法、重复、过期或冲突更新不改变 version，
不产生事件，分别返回 `INVALID/DUPLICATE/STALE/CONFLICT`。

部分成交按 Decimal 加权：`(旧均价×旧成交量 + 新价格×新成交量) / 新累计量`，使用价格精度和明确舍入；
Overfill 被拒绝。价格与数量使用 `OnlyPrice/OnlyQuantity`，不使用裸 float。

## 4. Manager、Query 与 Context API

Manager 维护 request/client/venue ID 唯一索引，以及 Cluster、Account、Instrument、open/recent 索引。
`OnlyOrderQueryService` 只返回 Snapshot。策略 API 为：

```text
ctx.orders.submit(request)
ctx.orders.cancel(request_or_order_id)
ctx.orders.get(order_id)
ctx.orders.require(order_id)
ctx.orders.list_open()
ctx.orders.list_recent(limit)
```

查询和撤单自动限制为当前 Cluster；View 不暴露 Manager、Gateway、`apply_fill`、`set_status` 或 Venue ID 修改。
Cluster 停止、失败或 Runtime 不可接单时拒绝命令。

## 5. Command、Update 与 Event

策略命令、查询和状态修改都是同步函数调用。调用链固定为：创建本地 Order → 发布 CREATED → 调用
ExecutionService → transport 收到后变为 SUBMITTED → 发布 SUBMITTED。Execution submit 收到不等于
Venue Accepted；cancel 收到只进入 PENDING_CANCEL，不等于 CANCELLED。

Gateway 数据必须先标准化为 `OnlyGatewayOrderUpdate` 子类，再由 Runtime 线程调用
`OnlyOrderUpdateProcessor.process()`。Manager 完成校验和状态变更后才构造过去式 Order Event，Publisher
再投递到 Runtime EventBus；Event handler 不驱动订单状态机。事件保留 Runtime/Cluster Scope、纳秒时间、
稳定序列和变更后的 Snapshot。

## 6. Execution 与 Gateway Port

`OnlyExecutionService` 是 Order Service 的窄执行端口；`OnlyTradeGateway` 定义连接、提交、撤单和标准化查询
的抽象边界。`OnlyPlaceholderExecutionService` 与 `OnlyPlaceholderTradeGateway` 只记录调用并明确返回
“已收到”，不生成 Venue Order ID、Accepted、Cancelled、Fill 或 Trade，不连接任何 SDK。

## 7. 幂等、乱序、序列化与并发

创建按 request ID 去重，Fill 按 trade ID/venue trade ID 去重，外部更新按 event ID 和 sequence 判定重复、
过期或冲突；Venue Order ID 在 Runtime 内唯一。Snapshot、Fill、Update 和 MutationResult 使用版本化 DTO，
Decimal 与 Unix 纳秒无损往返。

首版 Backtest Manager 只允许 Runtime 所在线程同步调用，不在 Manager 内加锁。未来 Live Runtime 必须把
SDK callback 标准化后排入 Runtime 单写线程，不能从 SDK 线程直接修改聚合。

## 8. Demo 与已知限制

`examples/order_demo` 覆盖创建提交、显式 Accepted/部分成交、撤单、重复成交、乱序和 Context Scope。
当前没有 RiskPipeline、ExecutionSimulator、PositionManager、AccountManager、真实成交或恢复持久化；
Repository 仅定义接口和内存占位，Live/Paper Gateway 装配留待后续 ADR。
