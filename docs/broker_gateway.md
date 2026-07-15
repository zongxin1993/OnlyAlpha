# Broker Gateway 通用边界

Broker 边界由小 Port 组合：Connection、Trading、Account、Position、Order Query 和 Trade Query。Capability 必须显式声明；
SDK 或虚拟券商数据先标准化为 immutable OnlyAlpha DTO，任何原始 SDK 对象都不能进入 Runtime Manager。

`submit_order()`/`cancel_order()` 的同步结果只表示接口是否接收请求，不代表 Accepted/Cancelled。业务终态只由标准化
`OnlyBrokerInboundUpdate` 表达，并进入 Runtime 拥有的有界 inbound queue。Runtime 单线程依次调用 Order、Position、
Allocation、Strategy Ledger、Account、Risk 和 Event 正式接口；EventBus 不驱动状态机。

Broker Update 必须携带 Gateway/Account/Update ID、source sequence、event/init timestamp、correlation/causation ID、
quality flags 和 metadata。Runtime 以 update ID 幂等，Manager 依据 source sequence 处理迟到状态，终态不得回退。
