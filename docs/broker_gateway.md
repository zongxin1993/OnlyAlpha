# Broker Gateway 通用边界

Broker 边界由小 Port 组合：Connection、Trading、Account、Position、Order Query 和 Trade Query。Capability 必须显式声明；
SDK 或虚拟券商数据先标准化为 immutable OnlyAlpha DTO，任何原始 SDK 对象都不能进入 Runtime Manager。

`submit_order()`/`cancel_order()` 的同步结果只表示接口是否接收请求，不代表 Accepted/Cancelled。业务终态只由标准化
`OnlyBrokerInboundUpdate` 表达，并进入 Runtime 拥有的有界 inbound queue。Runtime 单线程只调用独占的
`OnlyExecutionProcessor`，由 Processor 依次调用 Order、Position、Allocation、Strategy Ledger、Account、Reservation、Risk
和 Event 正式接口；EventBus 不驱动状态机。

Broker Update 必须携带 Runtime/Gateway/Account/Update ID、source sequence、event/init timestamp、correlation/causation ID、
quality flags 和 metadata。这些字段保留 observation provenance，但不定义 Accepted、Fill、Terminal 的业务事实身份。
Runtime 使用 v2 semantic identity/fingerprint 作为持久幂等 Authority；同一 Venue fact 经 Stream、REST 或 recovery 再次观察为
`DUPLICATE`，同一权威身份下的不同业务 payload 为 `CONFLICT`。Update ID 只能作为 ingress 优化与审计索引。

真实 Broker submit 必须先由 Runtime `ORDER_INTENT` transaction 持久化并投影完整 canonical Order 与既有 reservation/economic
authority。只有 `COMMITTED_AND_PROJECTED` 或 `ALREADY_READY` 才能进入 Broker。Broker command evidence 保存 canonical request、
命令身份、request fingerprint，以及 Runtime intent transaction/hash 引用；它不是第二份 Order authority。随后记录
`DISPATCHED`，最后才允许调用外部 venue。submit 与 cancel 使用同一命令证据协议；任何 post-dispatch
超时、HTTP 5xx 或供应商明确声明 execution status unknown 的错误都保持 `UNKNOWN`，不得作为拒绝或触发新的外部命令身份。
重启从证据恢复原 request 与 ClientOrderId，并在 reconciliation 完成前禁止第二次 side effect。

Reconciliation 只能发现并投递标准 Broker facts，不能直接修改 Order Manager。REST 首次发现 terminal snapshot 时直接表达
已验证的 terminal fact 和 VenueOrderId；不得补造 Accepted 历史，也不得在供应商没有序列语义时伪造 sequence。此类 update
必须标记 `PROVIDER_SEQUENCE_UNAVAILABLE`。Runtime 仅在 `OnlyExecutionProcessor` 返回 `APPLIED` 或 `DUPLICATE` 后生成
`OnlyBrokerFactApplicationReceipt`；Coordinator 必须收到与待确认 update ID 精确一致的 receipt 集合，并再次验证 venue 状态，
才能记录 `RESOLVED`、清除 UNKNOWN 和允许 readiness 收敛。`PRESENT` 且没有 missing facts 时，Coordinator 直接验证
Local 与 authoritative Venue snapshot；验证通过的 zero-delta 是合法收敛，不制造 update。Provider plugin 将查询结果映射为
`PRESENT`、`ABSENT_PROVEN` 或 `INCONCLUSIVE`：只有 submit 的强负证明可以写入 reconciliation proof 并清除 UNKNOWN；它不生成
Rejected/Cancelled/Expired 等 Venue fact，也不触发自动重发。cancel absence、5xx、timeout、归档/重置窗口及证明不足均保持
UNKNOWN。外部身份冲突必须 fail closed。
