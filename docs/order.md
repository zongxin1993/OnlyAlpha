# Order 订单组件

买单通过 Risk 并创建 Order/Position Reservation 后，在调用 Execution Port 前建立 Strategy Cash Reservation。成交消费实际
金额与费用，拒绝、失败、过期和取消释放；Reservation 不代替 Allocation 更新后的 Strategy Trade Accounting。
预占费用和成交费用必须来自同一个 Runtime `OnlyFeeResolver`；Order、Risk 和 Broker 均不得持有第二套佣金公式。

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
`OnlyOrderQueryService` 只返回 Snapshot。所有 submit 在创建 Order 前同步经过 Runtime 的
`OnlyRiskService`，Risk REJECT/ERROR 返回结构化结果且没有 Order 或 Execution 副作用。策略 API 为：

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

Broker 数据必须先标准化为 `OnlyBrokerInboundUpdate` 子类并进入 Runtime Inbound Queue，再由 Runtime 所属
`OnlyExecutionProcessor` 将其转换为内部 `OnlyGatewayOrderUpdate`，按固定跨组件顺序调用
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
当前已有 Pre-Trade Risk Pipeline、Risk Reservation 与独立 Position/Allocation 组件，但尚未由完整
ExecutionProcessor 原子编排；也没有 ExecutionSimulator、AccountManager、真实成交或恢复持久化；
Repository 仅定义接口和内存占位，Live/Paper Gateway 装配留待后续 ADR。

## 9. Position 归属衔接

Order Snapshot 的 `cluster_id` 是后续 Position Allocation 的归属依据，必须从请求创建持续保留到 Fill/Trade。
OrderService 通过窄 Position Reservation Port 在卖单 Risk ACCEPT、Order 创建后立即建立预占，并在发送/券商确认时推进
阶段；标准化 Fill、拒单、撤单和过期回报消费或释放预占。OrderManager 本身不直接依赖或修改 Position；账户 Position、
Allocation、Account 与 Risk 的完整成交编排由当前 Runtime 单写入者完成；未来 ExecutionProcessor 只能抽取该顺序，不能改语义。

M1 补充：Backtest Runtime 已通过同步 `process_trade()` 把标准化 Fill 编排到 Position、Allocation、Strategy Ledger 和
Account。Virtual Broker Matching Engine 负责最小撮合；Placeholder 仍不生成成交，持久化事务恢复仍未实现。

ExecutionProcessor 阶段替代上述 Runtime 直接编排：所有 Broker Update 必须经 Queue 调用 Processor。Processor 调用
`OnlyOrderUpdateProcessor` 时关闭其旧的 Event/Reservation side effects，先取得有效 Order Mutation，再在完整链成功后提交
Order facts，并在固定 Reservation 步骤统一消费/释放。独立 Order 组件测试仍保留默认旧参数以验证自身正式 API。
## Account 与 Broker 接入

OrderService 在 Risk ACCEPT 后协调独立的 Risk、Account Cash、Strategy Cash 和 Sell Position Reservation，再调用
ExecutionService。Execution 同步 `received` 只令本地 Order 进入 SUBMITTED；Accepted/Rejected/Fill/Cancelled 必须由
Broker Update 经 Runtime inbound queue 到达。重复 update ID 幂等，迟到回报不能令终态回退。
