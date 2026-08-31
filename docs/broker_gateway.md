# Broker Gateway 通用边界

Broker 边界由小 Port 组合：Connection、Trading、Account、Position、Order Query 和 Trade Query。Capability 必须显式声明；
SDK 或虚拟券商数据先标准化为 immutable OnlyAlpha DTO，任何原始 SDK 对象都不能进入 Runtime Manager。

`submit_order()`/`cancel_order()` 的同步结果只表示接口是否接收请求，不代表 Accepted/Cancelled。业务终态只由标准化
`OnlyBrokerInboundUpdate` 表达，并进入 Runtime 拥有的有界 inbound queue。Runtime 单线程只调用独占的
`OnlyExecutionProcessor`，由 Processor 依次调用 Order、Position、Allocation、Strategy Ledger、Account、Reservation、Risk
和 Event 正式接口；EventBus 不驱动状态机。

Broker Update 必须携带 Runtime/Gateway/Account/Update ID、source sequence、event/init timestamp、correlation/causation ID、
quality flags 和 metadata。Runtime 以 update ID 幂等，Manager 依据 source sequence 处理迟到状态，终态不得回退。

真实 Broker 的风险增加命令必须先通过 Runtime 提供的 `OnlyBrokerCommandEvidenceStore` 持久化 canonical request、命令身份和
request fingerprint，再记录 `DISPATCHED`，最后才允许调用外部 venue。submit 与 cancel 使用同一协议；任何 post-dispatch
超时、HTTP 5xx 或供应商明确声明 execution status unknown 的错误都保持 `UNKNOWN`，不得作为拒绝或触发新的外部命令身份。
重启从证据恢复原 request 与 ClientOrderId，并在 reconciliation 完成前禁止第二次 side effect。

Reconciliation 只能发现并投递标准 Broker facts，不能直接修改 Order Manager。REST 首次发现 terminal snapshot 时直接表达
已验证的 terminal fact 和 VenueOrderId；不得补造 Accepted 历史，也不得在供应商没有序列语义时伪造 sequence。此类 update
必须标记 `PROVIDER_SEQUENCE_UNAVAILABLE`。Runtime 仅在 `OnlyExecutionProcessor` 返回 `APPLIED` 或 `DUPLICATE` 后生成
`OnlyBrokerFactApplicationReceipt`；Coordinator 必须收到与待确认 update ID 精确一致的 receipt 集合，并再次验证 venue 状态，
才能记录 `RESOLVED`、清除 UNKNOWN 和允许 readiness 收敛。外部身份冲突必须 fail closed。
