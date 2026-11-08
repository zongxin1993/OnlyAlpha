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


### Isolated Rust common protocol

`crates/broker` is the ADR 0139 library boundary for normalized observations,
explicit ports, durable command evidence and receipt-bound reconciliation. Its owning journal
and Runtime read ports are authority boundaries, not self-authenticating JSON/hash claims.
The design is in `docs/superpowers/specs/2026-10-19-rust-broker-design.md`.
Provider SDKs, signing, network I/O, file adapters and venue rules remain outside this library.

新增 `Discovery.economic_through_ns` 表示有符号经济时间的封闭前缀，与 `as_of` 供应商序列及本次已观察的最大事件时间分开。较新事实可以已经被观察，仍不能由此推断同刻及之前不会再有事实。Virtual 所有未来事实使用不倒退的实际 now，因此只签发 checked `now−1ns`，当前纳秒仍开放；原 CLOCK、Bar 与 checkpoint Reader 不改变。Funding driver 消费边界成交并推进越界后才取得封闭前缀。旧缺字段 Discovery 保持原编码及身份。

RuntimeReader 的 order_view 对 SUBMIT 核对原 Ready ADMIT 完整请求，对 CANCEL 核对原订单、client 和 scope，返回原 SUBMIT 的 OrderView；它不回显未证明的来件。ready_intent 仍必须另证当前派发资格，取消派发的完整 pending 请求、reason 和 metadata 约束保持。
The native Execution consumer tests use its exact Ready reader; they do not activate an
application Runtime, replace the unified Runtime Store, certify LIVE or close a Web product slice.

显式 BACKTEST 来源绑定以同 scope、同代际的原来源库为准。原协议 INTENT、DISPATCHED、观察及回执保留自己的编码及预算。DISPATCHED 前同时核对原准入时刻和场所钟，落后时等待原命令。DISPATCHED 与 INGRESS 热路径均按规范 UTF-8 JSON 字节读取最新 CLOCK 或 BAR。INGRESS 以同一规则读取原事实的 stream_at。空白或对象键序偏离规范时，追加事务失败。来源写者按原前驱原子记入每个 CLOCK、BAR、命令或发布以及该步出生的事实子行。Funding 引用满足其处理时刻可见的首个全局闭合步和此前实际出生的成交。单笔委托的 Discovery 继续服务于该命令的对账。

绑定介质 v2 中，确定的 RESULT 按同一 DISPATCHED 和完整命令的实际场所结果逐值核对。回报不可知时保留 UNKNOWN。每次查询由原场所登记，再由 BoundBrokerJournal 原子核对来源及协议前驱、阶段、完整命令、presence、view 和有序原事实。reconcile_original 开始原命令对账。应用经本 Run 的 Ready 回执执行 acknowledge_original。resolve_original 需要第二次原场所查询；对已存在订单同时核对原 ACK 与当前订单视图。两次强负均须来自此原场所。
