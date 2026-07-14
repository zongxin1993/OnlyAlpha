# ADR-0011：Order 组件与执行端口

- 状态：Accepted
- 日期：2026-07-14
- 关联模块：domain、order、runtime、cluster、event、gateway

## 背景

策略需要统一订单 API，同时保证回测与未来实盘的接口一致。订单状态必须具备单一真值、Scope 隔离、
幂等与乱序保护，并为券商适配保留边界，但当前阶段不能连接真实 SDK 或假造成交。

## 决策

- 每个 Runtime 拥有一个 `OnlyOrderManager`；同 Runtime Cluster 共享，Runtime 间隔离。
- Cluster 只通过自动绑定 Scope 的 `ctx.orders` 使用订单能力。
- `OnlyOrderRequest` 与内部 `OnlyOrder` 分离；外部只获得不可变 `OnlyOrderSnapshot`。
- Command、Query、State Mutation 使用函数调用；状态成功变化后才发布过去式事实 Event。
- EventBus 不驱动状态机，OrderManager 是 Runtime 内订单状态唯一可信来源。
- OrderManager 不依赖具体券商 SDK；外部执行通过 `OnlyExecutionService` 和 `OnlyTradeGateway` Port。
- SDK transport submit 成功不等于 Accepted，cancel 请求成功不等于 Cancelled。
- 当前只提供记录调用的 Placeholder，不生成 Venue ID、成交或终态。
- 本阶段不实现 Risk、Position、Account、撮合、模拟成交或真实交易。

## 拒绝方案

- Engine 全局单一可变 OrderManager：破坏 Runtime 隔离。
- 每个 Cluster 一个 Manager：无法形成 Runtime 订单单一真值。
- 策略直接调用 Gateway 或持有可变 Order：绕过 Scope 和状态机。
- 由 EventBus subscriber 修改订单：业务正确性依赖注册顺序且难以原子化。
- SDK 返回成功立即标记 Accepted/Cancelled：混淆 transport 与 venue fact。
- Placeholder 自动生成成交：形成无法审计的虚假交易事实。

## 结果

回测 Runtime 具备确定性的本地订单域和受限策略 API，未来 Gateway 可在不改变策略接口的前提下接入。
代价是当前订单只能到 Placeholder 的 SUBMITTED/PENDING_CANCEL，任何后续 Venue 状态都必须由测试或未来
适配器显式提交标准化 Update。

## 验证

状态机、幂等、乱序、Overfill、均价、索引、Runtime/Cluster Scope、Context 权限、序列化、事件发布顺序、
Placeholder 行为和 100 次确定性重放测试，以及六个 Order Demo 验证本决策。
