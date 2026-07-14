# OnlyAlpha Order 订单组件设计、实现与验证任务

## 1. 任务目标

现在开始单独实现 OnlyAlpha 的 Order 订单组件。

本阶段只实现订单领域、订单状态机、订单管理、订单查询、订单幂等、订单序列化以及策略侧 `ctx.orders` 接口。

本阶段暂不实现：

* RiskPipeline；
* 资金风控；
* 持仓风控；
* PositionManager；
* AccountManager；
* TradeManager；
* 完整撮合引擎；
* 真实券商 SDK；
* 真实 Gateway；
* 实盘账户同步；
* Web；
* 数据库具体实现；
* 完整 ExecutionProcessor。

券商下单接口只需要定义抽象接口和明确的占位实现，用于固定未来 Order 与券商之间的调用边界。

最终需要建立以下结构：

```text
OnlyRuntime
    └── OnlyOrderManager
            ├── 当前 Runtime 的全部订单
            ├── 订单状态机
            ├── 订单索引
            ├── 幂等处理
            └── 不可变订单快照
```

策略只能通过：

```python
ctx.orders.submit(...)
ctx.orders.cancel(...)
ctx.orders.get(...)
ctx.orders.list_open(...)
```

使用订单能力。

策略不得直接访问：

```text
OnlyOrderManager
OnlyExecutionService
OnlyTradeGateway
券商 SDK
订单内部可变实体
```

---

# 2. 核心架构原则

必须遵循：

```text
Order Command 使用函数调用
Order Query 使用函数调用
Order 状态修改使用函数调用
Order 状态变化通知使用 Event
EventBus 不负责驱动订单状态机
每个 Runtime 拥有独立 OnlyOrderManager
Cluster 不单独拥有 OrderManager
Engine 不拥有全局可变 OrderManager
```

完整边界：

```text
OnlyCluster
    ↓
ctx.orders
    ↓
OnlyOrderServiceView
    ↓
OnlyOrderService
    ↓
OnlyOrderManager
    ↓
OnlyOrderMutationResult
    ↓
订单事实 Event
```

未来券商接入：

```text
OnlyOrderService
    ↓
OnlyExecutionService
    ↓
OnlyTradeGateway
    ↓
券商 SDK
```

但本阶段只实现 `OnlyExecutionService` 和 `OnlyTradeGateway` 的抽象接口或占位实现，不发送真实订单。

---

# 3. 执行前必须阅读

开始实现前必须阅读：

```text
AGENTS.md
docs/architecture.md
docs/domain_model.md
docs/runtime_context.md
docs/runtime.md
docs/cluster.md
docs/event.md
docs/time_model.md
docs/clock.md
docs/coding_style.md
docs/testing.md
docs/architecture_principles.md
docs/adr/
```

重点检查当前已有类型：

```text
OnlyPrice
OnlyQuantity
OnlyMoney
OnlyInstrumentId
OnlyAccountId
OnlyClusterId
OnlyRuntimeId
OnlyTimestamp
OnlyEvent
OnlyRuntimeContext
OnlyClusterContext
```

还需要分析 MyQuant 中现有订单相关实现：

```text
https://github.com/zongxin1993/MyQuant/blob/master/MyQuant/broker/broker_xt.py
```

重点分析：

* 策略如何发起订单；
* 订单 ID 如何生成；
* 订单对象字段；
* 订单状态定义；
* 券商订单 ID；
* 部分成交；
* 撤单；
* 拒单；
* 成交均价；
* 重复回报；
* 乱序回报；
* 查询订单；
* 回测和实盘订单差异。

只参考行为，不直接复制旧架构。

---

# 4. 先输出差距分析

创建：

```text
docs/order_component_analysis.md
```

至少记录：

## 4.1 当前订单类型

| 类型 | 当前职责 | 当前问题 | 目标类型 |
| -- | ---- | ---- | ---- |

## 4.2 当前订单链路

画出当前：

```text
策略
→ 订单请求
→ 订单管理
→ Gateway
→ 回报
→ 状态更新
```

指出：

* 是否直接调用 Gateway；
* 是否通过 Event 修改订单；
* 状态是否可以随意赋值；
* Order 与 OrderRequest 是否混用；
* 内部订单 ID 和券商订单 ID 是否混用；
* 是否有幂等；
* 是否处理乱序；
* 是否使用裸 float；
* 是否存在跨 Runtime 订单污染；
* 是否向策略暴露可变订单实体。

## 4.3 当前风险

重点检查：

* Engine 是否持有一个全局 OrderManager；
* 每个 Cluster 是否创建自己的 OrderManager；
* OrderManager 是否直接调用券商 SDK；
* 策略是否可以修改订单状态；
* EventBus 是否承担状态迁移；
* 重复成交是否重复累计；
* 迟到 Accepted 是否导致状态回退；
* 撤单后成交是否被错误拒绝；
* `CANCELLED` 是否被误解为从未成交；
* 市价单和限价单字段约束是否混乱；
* 序列化是否丢失精度和时区。

先完成分析，再修改代码。

---

# 5. 组件职责边界

## 5.1 Order 组件负责

Order 组件负责：

* 订单请求对象；
* 撤单请求对象；
* 订单实体；
* 订单标识符；
* 订单枚举；
* 订单状态机；
* 订单状态迁移；
* 部分成交累计；
* 剩余数量计算；
* 平均成交价计算；
* 订单拒绝信息；
* 订单失败信息；
* 重复成交检测；
* 乱序状态更新处理；
* 订单索引；
* 订单快照；
* 订单查询；
* Order Repository 抽象；
* Execution/Gateway 抽象占位；
* 订单事实 Event。

## 5.2 Order 组件不负责

Order 组件不负责：

* 检查账户资金；
* 检查持仓；
* 检查交易时段；
* 检查涨跌停；
* 检查价格 Tick；
* 检查数量 Step；
* 风控决策；
* 计算持仓；
* 计算账户权益；
* 决定成交价格；
* 生成真实成交；
* 调用真实券商 SDK；
* 修改 Position；
* 修改 Account；
* Web 展示；
* 数据库 SQL。

这些能力将在后续组件实现。

---

# 6. 推荐目录

根据当前工程结构调整，但建议职责类似：

```text
src/onlyalpha/order/
├── __init__.py
├── enums.py
├── identifiers.py
├── requests.py
├── entities.py
├── fills.py
├── rejections.py
├── state_machine.py
├── snapshots.py
├── results.py
├── manager.py
├── service.py
├── views.py
├── query.py
├── repository.py
├── id_generator.py
├── events.py
├── exceptions.py
└── execution/
    ├── service.py
    ├── gateway.py
    ├── models.py
    └── placeholder.py
```

如果部分订单对象已经位于 Domain 中，应复用或迁移，不得重复定义两套订单模型。

---

# 7. 标识符设计

至少定义或复用：

```text
OnlyOrderId
OnlyClientOrderId
OnlyVenueOrderId
OnlyOrderRequestId
OnlyOrderEventId
OnlyTradeId
```

含义：

```text
OnlyOrderId
    OnlyAlpha 内部订单唯一 ID

OnlyClientOrderId
    OnlyAlpha 提交给执行端的客户端订单 ID

OnlyVenueOrderId
    券商、交易所或外部执行场所返回的订单 ID

OnlyOrderRequestId
    策略提交请求的幂等标识
```

禁止混用一个普通字符串表示所有 ID。

建议定义：

```text
OnlyOrderRef
    runtime_id
    order_id
```

用于 Engine 层未来跨 Runtime 聚合查询。

订单本身仍应保存：

```text
runtime_id
cluster_id
account_id
```

---

# 8. 订单枚举

至少定义或复用：

```text
OnlyOrderSide
OnlyOrderType
OnlyTimeInForce
OnlyOrderStatus
OnlyOrderRejectionCode
OnlyOrderFailureCode
OnlyOrderMutationType
OnlyOrderApplyResult
```

## 8.1 Order Side

至少：

```text
BUY
SELL
```

如果 Domain 已将期货方向、开平仓分开定义，应复用：

```text
OnlyDirection
OnlyOffset
OnlyPositionSide
```

不要为了未来期货把所有语义塞进 `OnlyOrderSide`。

## 8.2 Order Type

第一版完整支持：

```text
MARKET
LIMIT
```

可以预留但暂不完整实现：

```text
STOP
STOP_LIMIT
TRAILING_STOP
PEGGED
ICEBERG
OCO
BRACKET
```

未实现的订单类型必须明确拒绝，不能静默退化为 MARKET 或 LIMIT。

## 8.3 Time In Force

至少定义：

```text
DAY
GTC
IOC
FOK
```

第一版只要求订单对象正确表达，不要求占位 Gateway 真正模拟全部语义。

---

# 9. OrderRequest 与 Order 必须分离

## 9.1 OnlyOrderRequest

表示策略交易意图，还不是正式订单。

建议字段：

```text
request_id
instrument_id
account_id（可以为空，使用 Cluster 默认账户）
side
order_type
quantity
price
stop_price
time_in_force
expire_time
tags
metadata
```

策略不能填写：

```text
runtime_id
cluster_id
order_id
client_order_id
venue_order_id
status
filled_quantity
average_fill_price
```

这些由 Context、OrderService 和 OrderManager 生成或维护。

`OnlyOrderRequest` 建议不可变。

## 9.2 OnlyCancelOrderRequest

建议字段：

```text
order_id
reason
request_id
metadata
```

Runtime 和 Cluster Scope 由 `ctx.orders` 自动绑定。

## 9.3 OnlyOrder

表示 OnlyAlpha 已创建并登记的订单实体。

不能将 `OnlyOrderRequest` 直接加入订单集合。

流程必须是：

```text
OnlyOrderRequest
    ↓
OnlyOrderService
    ↓
生成 Scope 和 ID
    ↓
OnlyOrderManager.create_order()
    ↓
OnlyOrder
```

---

# 10. OnlyOrder 实体设计

建议 `OnlyOrder` 使用：

> 内部受控可变实体，外部只暴露不可变 Snapshot。

原因：

* 订单生命周期会持续变化；
* 每次创建完整不可变副本会增加实现复杂度；
* 受控领域方法可以保证不变量；
* 外部不应获得直接修改权限。

建议字段：

```text
order_id
request_id
client_order_id
venue_order_id

runtime_id
cluster_id
account_id
instrument_id

side
order_type
time_in_force

quantity
price
stop_price
expire_time

status
filled_quantity
average_fill_price

created_at
updated_at
submitted_at
accepted_at
cancel_requested_at
cancelled_at
filled_at
rejected_at
expired_at
failed_at

version
last_external_sequence
rejection
failure
metadata
```

`remaining_quantity` 建议通过：

```text
quantity - filled_quantity
```

推导。

不要维护一个可能与累计成交量不一致的独立可写字段。

---

# 11. Order 实体封装规则

外部禁止：

```python
order.status = ...
order.filled_quantity = ...
order.average_fill_price = ...
order.venue_order_id = ...
```

必须通过领域方法：

```python
order.mark_submitted(...)
order.apply_accepted(...)
order.apply_fill(...)
order.request_cancel(...)
order.apply_cancelled(...)
order.apply_rejected(...)
order.apply_expired(...)
order.apply_failed(...)
```

所有领域方法必须：

* 验证状态迁移；
* 验证数量；
* 验证时间；
* 验证 sequence；
* 验证幂等；
* 增加 version；
* 更新 updated_at；
* 返回结构化 Mutation Result。

---

# 12. 订单状态机

建议状态：

```text
CREATED
SUBMITTED
ACCEPTED
PARTIALLY_FILLED
PENDING_CANCEL
CANCELLED
FILLED
REJECTED
EXPIRED
FAILED
```

## 12.1 状态语义

```text
CREATED
    本地订单已经创建，但尚未交给执行端

SUBMITTED
    下单请求已经交给执行端，但尚未获得场所确认

ACCEPTED
    券商或交易场所已经接受订单

PARTIALLY_FILLED
    已有部分成交，仍有剩余未终结

PENDING_CANCEL
    已发送撤单请求，等待确认

CANCELLED
    剩余未成交部分已取消

FILLED
    订单数量全部成交

REJECTED
    订单被业务系统、券商或交易场所明确拒绝

EXPIRED
    订单因有效期结束而终止

FAILED
    OnlyAlpha 内部或执行链出现系统失败，订单状态可能需要人工确认
```

## 12.2 合法迁移

至少支持：

```text
CREATED → SUBMITTED
CREATED → REJECTED
CREATED → FAILED

SUBMITTED → ACCEPTED
SUBMITTED → PARTIALLY_FILLED
SUBMITTED → FILLED
SUBMITTED → REJECTED
SUBMITTED → PENDING_CANCEL
SUBMITTED → CANCELLED
SUBMITTED → FAILED

ACCEPTED → PARTIALLY_FILLED
ACCEPTED → FILLED
ACCEPTED → PENDING_CANCEL
ACCEPTED → CANCELLED
ACCEPTED → EXPIRED
ACCEPTED → FAILED

PARTIALLY_FILLED → PARTIALLY_FILLED
PARTIALLY_FILLED → FILLED
PARTIALLY_FILLED → PENDING_CANCEL
PARTIALLY_FILLED → CANCELLED
PARTIALLY_FILLED → EXPIRED
PARTIALLY_FILLED → FAILED

PENDING_CANCEL → PARTIALLY_FILLED
PENDING_CANCEL → FILLED
PENDING_CANCEL → CANCELLED
PENDING_CANCEL → FAILED
```

状态机应允许场所跳过 `ACCEPTED`：

```text
SUBMITTED → PARTIALLY_FILLED
SUBMITTED → FILLED
```

## 12.3 非法迁移

例如：

```text
FILLED → ACCEPTED
FILLED → CANCELLED
REJECTED → SUBMITTED
CANCELLED → ACCEPTED
```

必须明确失败或作为迟到重复回报处理，不能让状态回退。

---

# 13. 终态与迟到数据

终态建议：

```text
CANCELLED
FILLED
REJECTED
EXPIRED
FAILED
```

但必须注意：

> CANCELLED 表示剩余部分已取消，不代表订单从未成交。

以下状态是合法的：

```text
status = CANCELLED
filled_quantity > 0
remaining_quantity = 0
```

因为剩余部分已经取消。

迟到成交的处理必须有明确策略。

例如：

```text
订单已经 CANCELLED
收到一个此前已发生但延迟到达的成交
```

如果成交：

* trade_id 未处理；
* event time 合法；
* 累计数量不超过订单数量；

可以允许补录成交事实，但订单最终状态仍可保持 `CANCELLED`，表示剩余数量已取消。

不得简单地因为状态是 CANCELLED 就丢弃真实成交。

需要在文档中明确这一语义。

---

# 14. OnlyOrderFill

定义：

```text
OnlyOrderFill
```

建议字段：

```text
trade_id
venue_trade_id
order_id
venue_order_id
price
quantity
fee（可选，本阶段不参与账户计算）
liquidity_side（可选）
ts_event
ts_init
external_sequence
metadata
```

`OnlyOrderFill` 不等于完整 `OnlyTrade` 组件。

本阶段它只是 Order 聚合成交数量和成交均价所需的输入事实。

---

# 15. 部分成交与平均成交价

通过：

```python
order.apply_fill(fill)
```

完成：

```text
幂等检查
sequence 检查
成交数量检查
累计 filled_quantity
计算 average_fill_price
更新状态
更新 version
生成事实 Event
```

平均成交价必须使用精确金融数值计算：

```text
旧累计成交金额 + 新成交金额
────────────────────────
新累计成交数量
```

禁止使用裸 float。

必须验证：

```text
filled_quantity <= quantity
```

超过订单总数量的成交必须拒绝并返回结构化错误。

---

# 16. 幂等处理

真实券商可能重复推送订单或成交回报。

必须支持至少通过以下字段去重：

```text
trade_id
venue_trade_id
external_event_id
external_sequence
```

OrderManager 或 Order 实体应能判断：

```text
APPLIED
DUPLICATE
STALE
INVALID
CONFLICT
```

重复 Fill：

```python
order.apply_fill(same_fill)
```

第二次必须：

```text
changed = False
duplicate = True
version 不增加
filled_quantity 不变化
不生成新 Event
```

---

# 17. 乱序回报

必须处理：

```text
Trade 先到
Accepted 后到
```

推荐规则：

* 成交事实优先，不因未收到 ACCEPTED 而丢弃；
* `SUBMITTED → PARTIALLY_FILLED/FILLED` 合法；
* 后续迟到 ACCEPTED 可以补充 `venue_order_id`；
* 迟到 ACCEPTED 不得把 FILLED 状态退回 ACCEPTED；
* 旧 sequence 不得覆盖新数据；
* 无 sequence 时使用 event time 和幂等 ID，并标记数据质量。

状态机必须集中处理这些规则，不能分散在不同 Adapter 中。

---

# 18. 状态变化结果

定义：

```text
OnlyOrderMutationResult
```

至少包含：

```text
order_id
mutation_type
previous_status
current_status
changed
duplicate
stale
version
snapshot
events
error
warnings
```

例如重复成交：

```text
changed = False
duplicate = True
events = ()
```

非法迁移：

```text
changed = False
error = OnlyInvalidOrderTransitionError(...)
```

不要只返回 `bool`。

---

# 19. Order Snapshot

定义不可变：

```text
OnlyOrderSnapshot
```

策略、Web、日志、查询和 Event 均使用 Snapshot，而不是内部可变实体。

建议包含：

```text
order_id
request_id
client_order_id
venue_order_id

runtime_id
cluster_id
account_id
instrument_id

side
order_type
time_in_force
quantity
price
stop_price

status
filled_quantity
remaining_quantity
average_fill_price

created_at
updated_at
submitted_at
accepted_at
cancel_requested_at
cancelled_at
filled_at
rejected_at
expired_at
failed_at

version
rejection
failure
metadata
```

Snapshot 必须不可变、可比较、可序列化。

---

# 20. OnlyOrderManager

每个 Runtime 拥有一个 `OnlyOrderManager`。

结构：

```text
OnlyEngine
├── OnlyLiveRuntime
│   └── OnlyOrderManager
├── OnlyPaperRuntime
│   └── OnlyOrderManager
└── OnlyBacktestRuntime
    └── OnlyOrderManager
```

一个 Runtime 内多个 Cluster 共用一个 OrderManager。

OrderManager 是该 Runtime 订单状态的唯一可信来源。

## 20.1 主要职责

建议接口：

```python
create_order(...)
get_snapshot(...)
require_snapshot(...)
find_by_client_order_id(...)
find_by_venue_order_id(...)

mark_submitted(...)
apply_accepted(...)
apply_fill(...)
request_cancel(...)
apply_cancelled(...)
apply_rejected(...)
apply_expired(...)
apply_failed(...)

list_open_orders(...)
list_by_cluster(...)
list_by_account(...)
list_by_instrument(...)
snapshot_all(...)
```

## 20.2 不负责

OrderManager 不负责：

```text
Risk
Gateway 网络调用
账户检查
持仓检查
撮合
生成 Trade
修改 Position
修改 Account
```

---

# 21. OrderManager 索引

第一版使用内存实现。

至少维护：

```text
orders_by_order_id
order_id_by_request_id
order_id_by_client_order_id
order_id_by_venue_order_id
open_order_ids
order_ids_by_cluster_id
order_ids_by_account_id
order_ids_by_instrument_id
```

索引更新必须集中在 OrderManager。

禁止外部直接操作索引字典。

必须测试索引与订单状态始终一致。

---

# 22. Open Order 定义

明确哪些状态属于 Open：

```text
CREATED
SUBMITTED
ACCEPTED
PARTIALLY_FILLED
PENDING_CANCEL
```

终态：

```text
CANCELLED
FILLED
REJECTED
EXPIRED
FAILED
```

如果未来 `FAILED` 表示状态不确定，可能需要单独的 reconciliation 集合，但本阶段先将其视为非活动订单并记录风险。

---

# 23. ID Generator

定义：

```text
OnlyOrderIdGenerator
OnlyClientOrderIdGenerator
```

建议使用 Protocol 或抽象类。

## 23.1 Backtest

需要确定性实现，例如逻辑上：

```text
runtime_id + sequence
```

相同初始状态和输入必须生成相同 ID。

## 23.2 Live

未来可以使用：

```text
runtime_id + trading_day + sequence
```

或 UUID。

本阶段只需要：

* 抽象接口；
* 确定性的内存 Sequence 实现；
* 不实现真实券商特定 ID。

---

# 24. 策略侧 ctx.orders

策略统一通过：

```text
ctx.orders
```

访问订单能力。

定义：

```text
OnlyOrderServiceView
OnlyOrderQueryView
```

或者组合为一个受限：

```text
OnlyOrderContextView
```

建议接口：

```python
submit(request) -> OnlyOrderSubmitResult
cancel(request_or_order_id) -> OnlyOrderCancelResult

get(order_id) -> OnlyOrderSnapshot | None
require(order_id) -> OnlyOrderSnapshot
list_open() -> tuple[OnlyOrderSnapshot, ...]
list_recent(limit=...) -> tuple[OnlyOrderSnapshot, ...]
```

策略不能访问：

```text
mark_submitted
apply_fill
apply_accepted
apply_rejected
set_status
内部 Order 实体
全部 Runtime 订单
```

## 24.1 自动绑定 Scope

`ctx.orders` 自动绑定：

```text
runtime_id
cluster_id
default_account_id
permissions
logger context
```

策略的 `OnlyOrderRequest` 不需要填写 runtime_id 和 cluster_id。

Cluster A 默认只能：

* 查询自己的订单；
* 撤销自己的订单；
* 提交自己 Scope 的订单。

跨 Cluster 订单操作必须显式授权，本阶段不实现。

---

# 25. OnlyOrderService

本阶段实现最小 `OnlyOrderService`。

职责：

```text
接收 ctx.orders 命令
补充 Runtime/Cluster Scope
处理 request_id 幂等
生成 OrderId/ClientOrderId
调用 OrderManager 创建订单
调用 ExecutionService 占位接口
根据占位结果更新订单
返回结构化结果
发布事实 Event
```

但本阶段不实现 RiskPipeline。

必须预留未来调用位置：

```text
OnlyOrderService
    ↓
Request Validation
    ↓
Future OnlyRiskPipeline
    ↓
OnlyOrderManager
    ↓
OnlyExecutionService
```

当前阶段可使用：

```text
OnlyNoOpOrderRiskPort
```

或明确 TODO Port，但不能在 OrderService 中写假的资金风控。

---

# 26. Order Submit 语义

策略调用：

```python
result = ctx.orders.submit(request)
```

返回值表示：

> OnlyAlpha 是否成功创建本地订单，并将订单请求交给当前 Execution Port。

它不表示：

> 券商或交易所已经接受订单。

成功流程：

```text
OrderRequest
    ↓
创建 OnlyOrder: CREATED
    ↓
ExecutionService 占位提交
    ↓
标记 SUBMITTED
    ↓
返回 OnlyOrderSubmitResult
```

未来收到券商接受回报后，才：

```text
SUBMITTED → ACCEPTED
```

本阶段占位执行接口不得直接伪造真实券商 Accepted。

---

# 27. Submit Result

定义：

```text
OnlyOrderSubmitResult
```

至少包含：

```text
accepted_locally
order_id
client_order_id
snapshot
error
events
```

建议避免使用 `accepted=True` 造成与交易所 Accepted 混淆。

推荐命名：

```text
created
submitted
```

或者：

```text
local_status
```

示例：

```text
created = True
submitted = True
venue_accepted = False / Unknown
```

本阶段不应存在假的 `venue_accepted=True`。

---

# 28. Cancel 语义

策略调用：

```python
result = ctx.orders.cancel(order_id)
```

本阶段流程：

```text
查询订单
    ↓
检查当前状态是否允许发起撤单
    ↓
OrderManager.request_cancel()
    ↓
ExecutionService.cancel_order() 占位接口
    ↓
订单保持 PENDING_CANCEL
    ↓
返回 OnlyOrderCancelResult
```

不能在占位接口返回成功时直接标记 `CANCELLED`。

`CANCELLED` 必须由未来场所回报或测试输入明确应用：

```python
order_manager.apply_cancelled(...)
```

---

# 29. 券商对接抽象接口

本阶段只定义抽象边界，不对接真实 SDK。

至少定义：

```text
OnlyExecutionService
OnlyTradeGateway
OnlyGatewayOrderRequest
OnlyGatewayCancelRequest
OnlyGatewaySubmitResult
OnlyGatewayCancelResult
OnlyGatewayOrderUpdate
OnlyGatewayOrderAcceptedUpdate
OnlyGatewayOrderRejectedUpdate
OnlyGatewayOrderCancelledUpdate
OnlyGatewayOrderFillUpdate
```

## 29.1 OnlyExecutionService

建议接口：

```python
class OnlyExecutionService(Protocol):
    def submit_order(
        self,
        order: OnlyOrderSnapshot,
    ) -> OnlyExecutionSubmitResult:
        ...

    def cancel_order(
        self,
        request: OnlyExecutionCancelRequest,
    ) -> OnlyExecutionCancelResult:
        ...
```

职责是未来：

* 根据 account_id 选择 Gateway；
* 将内部订单转换为 Gateway Request；
* 统一错误；
* 路由不同账户和券商。

当前阶段只实现占位。

## 29.2 OnlyTradeGateway

建议抽象接口：

```python
class OnlyTradeGateway(ABC):
    @abstractmethod
    def connect(self) -> None:
        ...

    @abstractmethod
    def disconnect(self) -> None:
        ...

    @abstractmethod
    def submit_order(
        self,
        request: OnlyGatewayOrderRequest,
    ) -> OnlyGatewaySubmitResult:
        ...

    @abstractmethod
    def cancel_order(
        self,
        request: OnlyGatewayCancelRequest,
    ) -> OnlyGatewayCancelResult:
        ...

    @abstractmethod
    def query_orders(
        self,
        account_id: OnlyAccountId,
    ) -> tuple[OnlyGatewayOrderSnapshot, ...]:
        ...

    @abstractmethod
    def query_trades(
        self,
        account_id: OnlyAccountId,
    ) -> tuple[OnlyGatewayTradeSnapshot, ...]:
        ...
```

账户和持仓查询接口可以先定义在 Gateway Protocol 中，但不实现 Manager 或同步逻辑。

---

# 30. 占位执行实现

实现：

```text
OnlyPlaceholderExecutionService
OnlyPlaceholderTradeGateway
```

其目的只是证明接口连接正确。

建议行为：

## Submit

* 接收 Order Snapshot；
* 记录请求；
* 返回“请求已被占位执行层接收”；
* 不生成 VenueOrderId；
* 不标记 ACCEPTED；
* 不生成 Fill；
* 不修改订单实体。

## Cancel

* 接收 Cancel Request；
* 记录请求；
* 返回“撤单请求已被占位层接收”；
* 不标记 CANCELLED。

必须在名称和文档中明确：

```text
Placeholder
```

禁止让人误以为它是模拟成交器。

后续 Backtest Matching Engine 或 Simulated Gateway 将单独实现。

---

# 31. Gateway Update 处理边界

本阶段可以定义：

```text
OnlyOrderUpdateProcessor
```

或占位 Application Port，用于未来处理标准化 Gateway Update。

建议接口：

```python
process_accepted(update)
process_rejected(update)
process_cancelled(update)
process_fill(update)
```

内部未来调用：

```text
OrderManager.apply_accepted()
OrderManager.apply_rejected()
OrderManager.apply_cancelled()
OrderManager.apply_fill()
```

本阶段可以实现这些标准化更新到 OrderManager 的调用，但不要连接真实 SDK。

这样测试可以手工注入：

```text
Accepted Update
Fill Update
Cancelled Update
```

验证状态机。

---

# 32. Order Event

定义订单状态变化事实：

```text
OnlyOrderCreatedEvent
OnlyOrderSubmittedEvent
OnlyOrderAcceptedEvent
OnlyOrderRejectedEvent
OnlyOrderPartiallyFilledEvent
OnlyOrderFilledEvent
OnlyOrderCancelRequestedEvent
OnlyOrderCancelledEvent
OnlyOrderExpiredEvent
OnlyOrderFailedEvent
```

事件必须使用过去式或事实语义。

事件包含：

```text
event_id
ts_event
ts_init
runtime_id
cluster_id
order_id
previous_status
current_status
order_snapshot
correlation_id
causation_id
```

Order 组件内部正确顺序：

```text
函数调用
    ↓
状态机校验
    ↓
修改订单
    ↓
更新索引
    ↓
生成 MutationResult
    ↓
发布 Event
```

禁止：

```text
先发布 Event
再由 Handler 修改 Order
```

---

# 33. Event Publisher Port

Order Domain 和 OrderManager 不应直接依赖完整 EventBus。

定义：

```text
OnlyOrderEventPublisher
```

接口：

```python
publish(event: OnlyOrderEvent) -> None
publish_many(events: tuple[OnlyOrderEvent, ...]) -> None
```

提供：

```text
OnlyNoOpOrderEventPublisher
OnlyRuntimeOrderEventPublisherAdapter
```

本阶段可以使用 NoOp 或内存记录 Publisher 测试。

OrderManager 返回 Events，由 `OnlyOrderService` 或 Application 层发布。

---

# 34. Query Service

定义：

```text
OnlyOrderQueryService
```

只返回 Snapshot。

支持：

```text
get
require
find_by_client_order_id
find_by_venue_order_id
list_open
list_by_cluster
list_by_account
list_by_instrument
list_recent
```

策略侧 `OnlyOrderQueryView` 必须自动限制为当前 Cluster Scope。

Runtime 内部查询服务可以访问全部 Runtime 订单。

---

# 35. Repository 抽象

定义：

```text
OnlyOrderRepository
```

本阶段只定义 Protocol 和内存实现：

```text
OnlyInMemoryOrderRepository
```

接口建议：

```python
save(snapshot, expected_version=None)
get(order_id)
list_open(...)
list_by_cluster(...)
```

需要明确：

* OrderManager 是运行时内存真值；
* Repository 是持久化 Port；
* 本阶段不实现数据库；
* 不让 Domain 依赖 SQL。

如果当前架构暂时不需要 Repository，可只定义接口和最小内存实现，不强制接入所有状态更新。

---

# 36. 序列化

以下对象必须支持无损序列化：

```text
OnlyOrderRequest
OnlyCancelOrderRequest
OnlyOrderSnapshot
OnlyOrderFill
OnlyOrderMutationResult 的稳定 DTO
OnlyOrderEvent
Gateway Request/Result 占位 DTO
```

回环：

```python
restored == original
```

必须保持：

* Decimal；
* OnlyPrice；
* OnlyQuantity；
* UTC 时间；
* Enum；
* 各种 ID 类型；
* Optional 字段；
* metadata；
* version。

禁止将 Decimal 转为 float。

---

# 37. 并发策略

第一版明确：

```text
OnlyOrderManager 由单 Runtime 线程串行修改
```

OrderManager 本身可以不是线程安全对象。

未来券商 SDK 回调必须：

```text
SDK Callback Thread
    ↓
Gateway 标准化
    ↓
Runtime Inbound Queue
    ↓
Runtime 线程
    ↓
Order Update Processor
    ↓
OrderManager
```

禁止外部线程直接修改 OrderManager。

当前测试应验证 Manager 的所有修改都从受控调用链进入。

---

# 38. RuntimeContext 集成

将以下能力加入受限 Context：

```text
ctx.orders
```

类型为：

```text
OnlyOrderServiceView
```

需要更新：

```text
OnlyRuntimeContext
OnlyClusterContext
OnlyBarContext
OnlyTimerContext
```

但不能把 OrderManager 放入 Context。

正确：

```python
ctx.orders.submit(request)
ctx.orders.cancel(order_id)
ctx.orders.get(order_id)
```

禁止：

```python
ctx.order_manager
ctx.execution_service
ctx.trade_gateway
ctx.orders.apply_fill(...)
```

---

# 39. 最小 Demo

创建：

```text
examples/order_demo/
├── README.md
├── create_and_submit_demo.py
├── partial_fill_demo.py
├── cancel_demo.py
├── duplicate_fill_demo.py
├── out_of_order_demo.py
└── context_order_demo.py
```

## 39.1 创建与提交

```text
ctx.orders.submit()
→ CREATED
→ Placeholder Execution
→ SUBMITTED
```

输出 Snapshot。

## 39.2 Accepted 与部分成交

手工注入：

```text
Accepted Update
Fill 40
Fill 60
```

期望：

```text
SUBMITTED
→ ACCEPTED
→ PARTIALLY_FILLED
→ FILLED
```

## 39.3 撤单

```text
SUBMITTED
→ ACCEPTED
→ PENDING_CANCEL
→ CANCELLED
```

## 39.4 部分成交后撤单

```text
ACCEPTED
→ PARTIALLY_FILLED
→ PENDING_CANCEL
→ CANCELLED
```

最终：

```text
filled_quantity > 0
remaining_quantity = 0
status = CANCELLED
```

## 39.5 重复成交

同一 trade_id 注入两次，只应用一次。

## 39.6 乱序

```text
SUBMITTED
→ Fill
→ Accepted
```

最终不能退回 ACCEPTED。

---

# 40. 必须新增的测试

建议：

```text
tests/order/
├── test_order_request.py
├── test_cancel_order_request.py
├── test_order_creation.py
├── test_order_state_machine.py
├── test_order_invalid_transitions.py
├── test_order_submitted.py
├── test_order_accepted.py
├── test_order_rejected.py
├── test_order_partial_fill.py
├── test_order_full_fill.py
├── test_order_average_fill_price.py
├── test_order_cancel_request.py
├── test_order_cancelled.py
├── test_order_cancel_after_partial_fill.py
├── test_order_expired.py
├── test_order_failed.py
├── test_duplicate_fill.py
├── test_overfill_rejected.py
├── test_out_of_order_accepted.py
├── test_late_fill_after_cancel.py
├── test_external_sequence.py
├── test_order_mutation_result.py
├── test_order_snapshots.py
├── test_order_manager_indexes.py
├── test_order_manager_open_orders.py
├── test_order_manager_runtime_isolation.py
├── test_order_query_scope.py
├── test_order_id_generator.py
├── test_order_serialization.py
├── test_order_events.py
├── test_order_event_publish_after_mutation.py
├── test_placeholder_execution_service.py
├── test_gateway_abstract_interface.py
├── test_context_order_permissions.py
└── test_order_determinism.py
```

---

# 41. 核心验收场景

## 41.1 每 Runtime 一个 OrderManager

创建两个 Runtime。

各自生成：

```text
ORDER-000001
```

允许内部序列相同，但通过 runtime_id 明确区分。

两个 Runtime 的订单不得互相查询或修改。

## 41.2 多 Cluster 共享 Manager

Runtime 中 Cluster A、B 提交订单。

同一个 OrderManager 管理全部订单。

Cluster A 的 `ctx.orders.list_open()` 默认只能看到 A 的订单。

Cluster B 不能撤销 A 的订单。

## 41.3 状态机

完整验证所有合法和非法迁移。

## 41.4 幂等

重复 RequestId 不重复创建订单。

重复 Fill 不重复累计。

重复 Cancelled Update 不重复生成 Event。

## 41.5 乱序

迟到 Accepted 不回退状态。

成交可在 Accepted 前应用。

## 41.6 Context 权限

策略无法：

* 修改状态；
* 应用成交；
* 设置 VenueOrderId；
* 查询其他 Cluster 订单；
* 获取 OrderManager；
* 获取 Gateway。

## 41.7 确定性

相同 RuntimeId、初始 sequence、请求和更新序列运行 100 次：

* OrderId 一致；
* 状态一致；
* version 一致；
* Event 顺序一致；
* Snapshot 一致。

---

# 42. 文档输出

创建或更新：

```text
docs/order.md
docs/runtime_context.md
docs/cluster.md
docs/event.md
docs/architecture.md
docs/testing.md
docs/architecture_principles.md
```

`docs/order.md` 至少包括：

1. Order 组件边界；
2. Request 与 Order 区别；
3. ID 类型；
4. Order Entity；
5. 状态机；
6. 部分成交；
7. 平均成交价；
8. 撤单；
9. 幂等；
10. 乱序；
11. OrderManager；
12. Runtime 所有权；
13. Context API；
14. Command 与 Event 边界；
15. Execution/Gateway 抽象；
16. Snapshot；
17. Query；
18. 序列化；
19. 并发；
20. Demo；
21. 已知限制。

---

# 43. ADR

创建：

```text
docs/adr/0011-order-component-and-execution-port.md
```

至少记录：

## 背景

策略需要统一订单 API，同时保证回测与实盘接口一致，并为未来券商适配预留边界。

## 决策

* 每个 Runtime 一个 OrderManager；
* Cluster 通过 `ctx.orders` 使用订单能力；
* OrderRequest 与 Order 分离；
* Order 使用内部受控可变实体；
* 外部只使用不可变 Snapshot；
* 状态修改使用函数调用；
* 状态变化后发布事实 Event；
* EventBus 不驱动状态机；
* OrderManager 不直接调用券商 SDK；
* 通过 ExecutionService 和 TradeGateway Port 对接外部执行；
* 当前只实现 Placeholder Execution；
* 不在本阶段实现 Risk、Position、Account 和真实撮合。

## 拒绝方案

* Engine 全局单一可变 OrderManager；
* 每个 Cluster 一个 OrderManager；
* 策略直接调用 Gateway；
* 订单状态完全由 EventBus 订阅修改；
* 暴露可变 Order 给策略；
* SDK 返回成功直接标记 ACCEPTED；
* 占位 Gateway 自动生成虚假成交。

---

# 44. Architecture Principles 新增规则

加入：

```text
Rule: 每个 Runtime 拥有一个订单状态域和一个 OnlyOrderManager。

Rule: Cluster 不拥有 OrderManager。

Rule: Cluster 只能通过 ctx.orders 使用订单能力。

Rule: Order Command、Query 和 State Mutation 使用函数调用。

Rule: Order Event 只表达状态已经发生变化的事实。

Rule: EventBus 不负责订单状态迁移。

Rule: OnlyOrderManager 是 Runtime 内订单状态唯一可信来源。

Rule: OrderRequest 不等于 Order。

Rule: 内部 Order 可以受控修改，外部只能获得 immutable Snapshot。

Rule: OnlyOrderManager 不直接依赖具体券商 SDK。

Rule: 外部执行通过 OnlyExecutionService 和 OnlyTradeGateway Port 接入。

Rule: SDK 提交成功不等于 Venue Accepted。

Rule: 撤单请求成功不等于订单已经 Cancelled。

Rule: 重复回报必须幂等。

Rule: 迟到回报不得导致订单状态回退。

Rule: 策略不能修改其他 Cluster 的订单。
```

---

# 45. 实现顺序

严格按以下顺序：

1. 扫描现有 Order 实现；
2. 创建差距分析；
3. 确认或补充订单 ID；
4. 定义 Enum；
5. 实现 OnlyOrderRequest；
6. 实现 OnlyCancelOrderRequest；
7. 实现 OnlyOrder 实体；
8. 实现状态机；
9. 完成状态机测试；
10. 实现 OnlyOrderFill；
11. 完成部分成交和均价测试；
12. 实现幂等和乱序处理；
13. 实现 OnlyOrderSnapshot；
14. 实现 OnlyOrderMutationResult；
15. 实现 OnlyOrderManager；
16. 完成索引和 Scope 测试；
17. 实现 ID Generator；
18. 实现 OnlyOrderQueryService；
19. 实现 OnlyOrderService；
20. 实现 ctx.orders 受限 View；
21. 定义 ExecutionService Port；
22. 定义 TradeGateway Port；
23. 实现 Placeholder Execution/Gateway；
24. 实现标准化 Gateway Update 占位类型；
25. 实现 Order Event；
26. 接入 Event Publisher Port；
27. 完成序列化；
28. 创建 Demo；
29. 更新文档；
30. 创建 ADR；
31. 运行全部测试；
32. 输出验收报告。

---

# 46. 验收标准

完成后必须满足：

* 每个 Runtime 拥有独立 OrderManager；
* 多个 Cluster 共用 Runtime OrderManager；
* Cluster 只通过 ctx.orders 访问；
* ctx.orders 自动绑定 Runtime 和 Cluster；
* OrderRequest 与 Order 分离；
* Order 状态不可外部直接赋值；
* 所有状态迁移集中管理；
* MARKET 与 LIMIT 字段验证明确；
* 部分成交正确；
* 平均成交价正确；
* Overfill 被拒绝；
* 重复 Fill 幂等；
* 迟到 Accepted 不回退状态；
* Cancelled 可以保留历史部分成交；
* RequestId 幂等；
* OrderManager 索引一致；
* Query 返回 immutable Snapshot；
* 策略不能查询或撤销其他 Cluster 订单；
* OrderManager 不依赖具体 Gateway；
* TradeGateway 只存在抽象接口和 Placeholder；
* Placeholder 不生成假成交；
* Submit 成功不等于 Venue Accepted；
* Cancel 请求成功不等于 Cancelled；
* 状态变化后才发布 Event；
* EventBus 不驱动状态迁移；
* 序列化无损；
* 相同输入结果确定；
* 文档、测试、Demo、ADR 完整。

---

# 47. 一票否决项

存在以下任一项，不得标记完成：

* Engine 使用一个全局可变 OrderManager 管理所有 Runtime；
* 每个 Cluster 创建自己的 OrderManager；
* 策略直接访问 OrderManager；
* 策略直接访问 Gateway；
* 策略可以调用 apply_fill 或 set_status；
* OrderRequest 和 Order 使用同一个对象；
* Order 状态可以直接赋值；
* 核心价格或数量使用裸 float；
* 重复 Fill 重复累计；
* 迟到 Accepted 让 FILLED 回退到 ACCEPTED；
* SDK submit 返回成功后直接标记 ACCEPTED；
* cancel 调用返回成功后直接标记 CANCELLED；
* Placeholder Gateway 生成虚假真实成交；
* Event 发布在状态修改之前；
* Event Handler 承担订单状态机；
* Query 返回可变 Order 实体；
* Runtime 之间订单状态串流；
* Cluster 可以查看其他 Cluster 订单；
* 序列化丢失 Decimal 或 UTC；
* 相同输入生成不同订单结果。

---

# 48. 最终交付报告

完成后必须输出：

```text
新增文件
修改文件
Order 组件边界
OrderRequest 设计
OnlyOrder Entity 设计
状态机设计
合法迁移
终态语义
部分成交实现
平均成交价实现
幂等策略
乱序策略
OrderManager 所有权
OrderManager 索引
ctx.orders API
Cluster 权限边界
OrderService 调用链
ExecutionService 抽象
TradeGateway 抽象
Placeholder 行为
Order Event 设计
序列化方案
测试通过数
测试失败数
测试跳过数
确定性测试结果
Demo 运行结果
已知限制
一票否决项
是否建议进入 RiskPipeline
是否建议进入 ExecutionSimulator
是否建议进入 PositionManager
```

最终结论：

```text
ACCEPTED
CONDITIONALLY_ACCEPTED
REJECTED
```

当前任务只实现：

```text
Order Domain
Order State Machine
Order Manager
Order Query
Order Service
ctx.orders
Order Snapshot
Order Event
Execution/Gateway 抽象接口
Placeholder Execution
测试
Demo
文档
ADR
```

不要在本任务中实现：

* 真实券商 SDK；
* RiskPipeline；
* AccountManager；
* PositionManager；
* TradeManager；
* 完整撮合；
* 模拟成交；
* 真实成交；
* 资金计算；
* 持仓计算；
* Web；
* 数据库具体实现。
