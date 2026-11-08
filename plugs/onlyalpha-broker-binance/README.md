# Binance Spot 券商协议

## 目的与职责

这个 Rust 库负责 Binance Spot 私有 REST 与 WebSocket API。宿主可用它读取账户余额、查询订单和成交、发送已经获得 Runtime 准入的原始下单或撤单命令，并在通信中断后继续对账。Binance 拥有场所订单和成交事实。插件只报告观察；订单投影、仓位、账本、费用应用和实盘批准归相应 OnlyAlpha Authority。

当前后端没有安装独立 Binance Spot 券商运行宿主。行情源注册、配置声明和本库构建各自有独立含义。库中另有一个无副作用的 USD-M 参数转换函数，供既有衍生品契约使用。

## 边界与依赖

- 测试通过 dev-dependencies 使用 Execution 的 Components 和 Runtime 的 SqliteStore，组合验证现金订单的冷恢复。正式库的依赖、后端券商安装和实盘权限各由对应宿主管理。
- [构造和绑定](src/lib.rs)使用 Broker Scope 固定 Engine、Runtime、Gateway、Account、Generation 和运行模式。宿主提供已核验的实际 Rust 工件 SHA-256、精确版本的两个 Secret Slot、Binance 账户 UID，以及 ReadOnly 或 Trading 授权。LIVE endpoint 只接受 LIVE Scope。Testnet 和生产使用各自固定的 HTTPS/WSS 地址。
- [私有传输](src/private_http.rs)以宿主提供的 Clock 签名，使用 HMAC-SHA256、reqwest、rustls 和 tokio-tungstenite。TLS 只使用显式传入的可信证书。该同步 Broker 端口须由 Tokio 异步执行上下文之外的拥有者调用。原始密钥由宿主解析到内存，插件不读取环境变量。请求头、签名 URL 和订阅请求不进入观察日志。
- 由宿主实现 [Broker Journal](../../crates/broker/src/protocol.rs)、[RuntimeReader](../../crates/broker/src/ports.rs) 和[原始观察存储](src/evidence.rs)。Journal 保存已准入原命令、发送标记、结果、规范事实和 Runtime 应用回执。ObservationStore 按绑定和连续序列原子追加场所原文，校验前缀并支持确切回读。对任一持久化结果不确定时，都要读回原操作。
- REST 支持签名账户查询、逐币余额、开放订单、已知原订单及其成交与佣金。Spot 多资产账户没有本接口所需的单币 equity，调用 AccountPort::account 将返回 BINANCE_MULTI_ASSET_ACCOUNT_USE_BALANCES。PositionPort 的空集合只表达现货账户没有衍生品仓位；持有的现货资产见逐币余额。成交序号按交易对分域，TradeQueryPort 不支持跨交易对的全局 since_sequence。

## 公开接口

| 入口 | 输入和结果 |
|---|---|
| [SpotBroker::open、checkpoint](src/gateway.rs) | 核对 Config、BoundCredentials、显式 Trust/Clock、两个持久化端口、检查点和队列容量。空历史可从头打开。已有历史要求检查点与绑定、Journal 前缀和原始观察前缀精确一致。 |
| [ConnectionPort、subscribe、poll](src/gateway.rs) | authenticate 用签名账户响应验证 UID、账户类型与权限。subscribe 在新 WS 会话发送 userDataStream.subscribe.signature。poll 从已确认的订阅接收 executionReport、outboundAccountPosition 或订阅终止通知。 |
| [dispatch、pending、acknowledge](src/gateway.rs) | 以完整 BrokerCommand、RuntimeReader 提交 MARKET 或 LIMIT 订单；限价支持 GTC、IOC、FOK。撤单绑定原标的、原 client、确切场所订单及本次独立撤单 client。返回命令状态，规范事实须另由 Runtime 应用和确认。ReadOnly 拒绝下单和撤单。 |
| [AccountPort、OrderQueryPort、TradeQueryPort、FeeEvidencePort](src/gateway.rs) | 查询同 Scope 的规范观察。每条成交保留标的、原订单、交易方向和场所成交身份。佣金报告是交易级 COMMISSION_ONLY 证据，缺失币种、错订单或成交量无法闭合会报错。 |
| [reconcile、resolve、synchronize](src/discovery.rs) | 前两者查询特定原 command，由 Broker 验证不可变发现和 Runtime 回执。synchronize 在订阅恢复后复核整个 Gateway，发现迟到成交或终态时先交由 Broker 入队。 |
| [usdm_order_parameters](src/codec.rs) | 输入已规范化 OnlyExecutionIntent 和账户的实际 Netting/Hedging 模式，输出 side、positionSide 及适用的 reduceOnly。该接口不连接合约交易端点。 |

## 状态与生命周期

1. 签名查询使用注入的时间戳和 recvWindow，最大 60,000 毫秒。单次公开操作共用绝对截止时间和请求数预算。传输超时上限为 30 秒，单个响应上限为 8 MiB。签名参数排序并编码，错误分类不采纳供应商消息正文作为交易结论。
2. 下单前校验 Scope、权限、交易能力和规范请求。Broker 从 Runtime 读取原命令的 Ready 授权，先持久化 INTENT 与 DISPATCHED，再发送给场所。发送前已知的 Retry-After 冷却或签名时钟错误直接拒绝本次派发，已订阅连接仍可在 HTTP 冷却期间接收事件。收到身份匹配的 ACK 只表示原命令已收悉。超时、HTTP 5xx、响应丢失、身份不符或 -1006/-1007 保留 UNKNOWN。重启及查询不会换一个 client 再下单。
3. 核对原账户和原订单后，按 symbol、orderId 和 fromId 从 0 分页读取 myTrades。每页检查方向、游标、订单归属和成交数量；对账还会重读原订单并与整页累计数量比较。仅 -2013、HTTP 404、空页、历史不可见或可能的 Testnet 重置均无法证明原订单从未存在。无法取得强负证明时保留不确定状态。
4. 原 client 的兼容 wire 编码保留在[协议编码](src/codec.rs)。新 Rust Generation 通过 BINANCE:&lt;symbol&gt;:&lt;数字&gt; 区分跨交易对重号，查询时仍发送原始数字。每个成功订阅拥有自己的 epoch 和 subscriptionId。流原文一并保存采样时 Broker Journal 的长度与前缀哈希，订单关联要求当时已有原命令的 DISPATCHED 标记。公开 REST 查询发现原单、开放订单或成交归属冲突时立即撤销交易信任，后续查询和撤单可继续，完整同步对账后才能恢复 Ready。REST 与 WS 共用委托数量、原价与限价有效期校验，成交价格按真实成交独立记录。断流或订阅终止立即撤销流信任，重新验证和对账后才能交易。
5. 迟到的成交和终态即使属于已 Resolved 的命令，仍须通过 Broker 的独立规范事实身份、指纹和 Runtime 回执。只要仍有待应用事实，Ready 即为假，新的 SUBMIT 在写入命令前被拒绝；观察、撤单及原命令查询可继续。连续可信流上的事实全部得到精确回执后沿用原连接，其余认证、对账和连接门槛仍须满足。相同场所事实可跨 REST、流和恢复去重。改变内容的重复观察触发冲突。队列已满时保留原始观察位置。Runtime 确认当前待应用事实后，网关按原顺序重新读取已校验的观察，通过 Broker 再次投递。一次 REST 发现的事实超过队列容量时先顺序投递可容纳的事实。Runtime 应用后，网关重新核对原订单、全页成交和订单水位，完整发现通过后才能接续原命令。

旧 Python wheel、历史 Generation 和它们的检查点继续引用原工件；本库拒绝不匹配的原生绑定。仓内旧 Python 文件保留给跨插件断言及既有历史清理流程。

## 使用与验证

在仓库根目录运行以下命令，使用固定的 onlyalpha-dev 环境进行离线验证。

```sh
python3 scripts/dev_verification.py run -- cargo test --locked --offline -p onlyalpha-broker-binance
```

[协议用例](src/tests/protocol_cases.rs)、[真实 Broker 恢复用例](src/tests/venue_recovery.rs)和[本机 TLS 协议用例](src/tests/loopback_tls.rs)使用固定输入。TLS 测试复用仓内公开的 loopback 专用证书与叶证书测试私钥。真实 Binance Spot Testnet、生产账户、实盘权限和后端产品安装均需独立验收。

[现金 Execution 消费者用例](src/tests/cash_execution.rs)在 Linux 临时目录保存原 Broker Journal、场所原文和 SQLite Ready 事务。重新打开后，应用回执逐项核对原场所事实、原派发意图和该事实对应的现金事务。用例同时检查错关联及重复处理同一事务。

[Spot Testnet 手工专项](src/tests/spot_testnet_external.rs)默认忽略，会向专用测试账户实际发送 BTC、ETH 限价单、撤单和一笔 BTC 市价单。只有获准使用全新 run id 和专用资金时才手动运行。环境变量均以 `ONLYALPHA_BINANCE_TESTNET_` 开头，必填后缀为 `AUTHORIZED`（值为 `1`）、`UID`、`API_KEY`、`API_SECRET`、`RUN_ID`（1 至 8 位 ASCII 字母或数字）及 `CA_PEM`（根证书文件路径）。另外两个可选后缀 `REST_BASE_URL` 和 `WS_BASE_URL` 如已设置，必须分别等于 `https://testnet.binance.vision` 和 `wss://ws-api.testnet.binance.vision/ws-api/v3`。不确定的响应按原 client 和场所订单查询，保留原 run id 供后续核对。

协议依据见 [Binance Spot REST](https://github.com/binance/binance-spot-api-docs/blob/master/rest-api.md)、[WebSocket API](https://github.com/binance/binance-spot-api-docs/blob/master/web-socket-api.md)、[用户数据事件](https://github.com/binance/binance-spot-api-docs/blob/master/user-data-stream.md)和[Testnet 重置说明](https://github.com/binance/binance-spot-api-docs/blob/master/testnet/general-info.md)。
