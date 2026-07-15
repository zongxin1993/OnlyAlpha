# ADR 0015: Account, Broker Ports and deterministic Virtual Broker

- Status: Accepted
- Date: 2026-07-15

## Context

此前完整纵切面使用 Placeholder Execution 后手工注入 Accepted/Fill/Trade，没有本地账户现金真值，也无法验证 Broker 延迟、
部分成交、撤单、乱序、重复回报或 Broker/Local 冲突。Strategy Ledger 是 Cluster 虚拟账，不能兼任账户合并真值；真实或
虚拟 Broker 也不能持有 Runtime Manager 或直接修改其状态。

## Decision

每个 Runtime 独占 `OnlyAccountManager`、Account Query/Risk View 和有界 Broker inbound queue。Account、Position、Order 与
Strategy Ledger 继续是独立状态域。Broker 以 Connection/Trading/Account/Position/Order/Trade Query 小 Port 组合，所有
回报标准化为 immutable Broker Update 后进入 Runtime 单写入者线程。

`OnlyVirtualBrokerGateway` 实现这些 Port，并独占 Broker Account/Order/Trade Store。撮合由独立 `OnlyMatchingEngine` 完成；
默认使用无未来数据的 Next-Bar 规则。Commission、Slippage、Latency 独立配置，延迟只依赖 Runtime Clock 与确定性 Scheduler。
本地与 Broker Snapshot 通过字段级 Authority/Reconciliation 比较，禁止全量覆盖。

## Consequences

Integration 主路径不再手工制造成交，能够真实验证请求接收与业务接受的区别、异步回报、T+1、部分成交、撤单、多 Cluster
共享账户、对账冲突和重放。代价是 Runtime 必须维护明确的 inbound 顺序、多个独立 Reservation 生命周期和跨账一致性检查。

## Rejected alternatives

- Virtual Broker 复用 AccountManager/PositionManager：无法产生真实 Broker/Local 差异。
- Broker callback 直接调用 Manager：破坏 Runtime 单写入者和确定性。
- EventBus 驱动订单/账户状态：业务顺序不再显式。
- Strategy Ledger 兼作 Account：多 Cluster 共享账户时语义冲突。
- Gateway 内写死撮合、手续费和延迟：无法复用或独立验证。
