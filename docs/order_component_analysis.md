# Order 组件实现前差距分析

## 1. 扫描范围

实现前已检查 `domain.execution`、订单 ID/Enum、MarketRule、RuntimeContext、Event/EventBus、Runtime 资源装配、
现有订单测试，并只读分析 MyQuant `broker_xt.py`、`core/broker.py`、`core/object.py`、`core/constant.py` 的
下单、撤单、委托回报、成交回报、主动查询和错误处理。

## 2. 当前订单类型

| 类型 | 当前职责 | 当前问题 | 目标类型 |
| --- | --- | --- | --- |
| `domain.OnlyOrderRequest` | 已带内部 Order/Account/Cluster ID 的正式请求 | 策略意图与正式订单混合，策略可填写 Scope | 无 Scope 的不可变 `OnlyOrderRequest` |
| `domain.OnlyCancelRequest` | Order/Account/时间 DTO | 缺 RequestId、原因、自动 Scope | `OnlyCancelOrderRequest` |
| `domain.OnlyOrder` | 不可变订单状态及 `transition` | 没有 Runtime、Client/Request ID、版本、索引、外部 sequence；均价由调用方给出 | 内部受控 `order.OnlyOrder` + 外部 `OnlyOrderSnapshot` |
| `domain.OnlyTrade` | 完整成交事实 | 与订单聚合输入边界过大 | 保留 Trade；新增较窄 `OnlyOrderFill` |
| `OnlyOrderStatus` | 初始化、提交、接受、成交、撤单等 | 缺 CREATED/FAILED，CANCELED 拼写与目标不一致 | 扩展为受控状态机所需状态 |
| `OnlyOrderId/OnlyVenueOrderId/OnlyTradeId` | 部分强 ID | 缺 Client/Request/Event/VenueTrade ID | 补齐独立强 ID |

现有强类型 `OnlyPrice`、`OnlyQuantity`、Account/Cluster/Runtime/Instrument ID、`OnlyTimestamp`、订单 Side/Type/
TimeInForce 将直接复用。现有同名 Request 将迁移，不并存第二套订单模型。

## 3. 当前 OnlyAlpha 链路

```text
测试/调用方
→ 直接构造带 Scope 的 OnlyOrderRequest
→ OnlyOrder.initialized()
→ 调用方直接 transition()/apply_fill()
→ 得到新不可变 OnlyOrder
```

当前没有 Runtime `OnlyOrderManager`、`ctx.orders`、Execution Port、Gateway Update Processor 或订单事实发布链。
EventBus 没有驱动订单状态，这一点应保留；但状态真值也尚未建立。

## 4. MyQuant 对应行为

```text
Strategy/PositionManager
→ BrokerXT.send_order(OrderData)
→ 生成基于系统时间的本地 ID
→ XT SDK async submit
→ seq/local ID、local/XT order ID、local/sysid 多张字典关联
→ on_stock_order/on_stock_trade/error callback 直接修改 OrderData
```

有效行为：本地 ID 与券商 ID 分离；委托和成交主动回查；部分成交/撤单状态存在；成交使用 trade ID 去重；
撤单提交不直接等同委托已撤销。

不迁移的结构：Broker 直接维护可变订单真值；SDK callback 直接改状态；Order/Position/Account 同步耦合；
状态可任意赋值；价格、数量、均价和 PnL 使用 float；ID 与时间使用裸字符串；按策略 remark 做隔离；本地 ID
读取系统时间；没有统一 external sequence/乱序状态机，也没有不可变 Snapshot。

## 5. 风险结论

- Engine 当前没有全局 OrderManager，但 Runtime 也没有独立订单域。
- Cluster 尚无订单 API；新增 API 必须是 scope-bound view，不能暴露 Manager/Gateway。
- 现有 Domain Order 的状态只能通过函数返回新对象，优于直接赋值，但没有唯一 Manager 真值和索引。
- 重复 Fill 仅支持简单 report ID；没有 venue trade/event ID 冲突检测、sequence stale 规则或 RequestId 幂等。
- `SUBMITTED → Fill`、迟到 Accepted、Cancelled 后迟到 Fill 尚未完整表达。
- 现有 Snapshot 序列化强类型且 UTC，但缺 Runtime Scope、版本和生命周期时间。
- Placeholder 若把“请求已接收”解释成 ACCEPTED/CANCELLED，会制造虚假场所事实，必须禁止。

## 6. 变更边界

本阶段迁移 Domain 的订单请求/快照输入类型，新增 `onlyalpha.order` 受控实体、状态机、Manager、查询、服务、
事件、Repository Port、Execution/Gateway Port、Placeholder 和标准化 Update Processor，并装配进每个 Runtime
及 `ctx.orders`。不实现 Risk、Position、Account、TradeManager、撮合、模拟成交、真实 Gateway/SDK、数据库
或 Web。
