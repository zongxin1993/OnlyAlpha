# Binance 数据源

## 目的与职责

负责 Binance 公开行情协议、响应边界、标的转换、原始成交序列及历史/实时行情。Spot 和 USD-M 是独立的产品协议，不能相互替代。行情原始响应及外部观察不授予交易、风控、账户或规则 Authority。

## 边界与依赖

复用 `onlyalpha-domain` 的 canonical Bar、TradeTick、MarketReferenceTick、ReferencePriceFact 和 FundingRateFact；正式数据源边界采用 `onlyalpha-integration-contract::source`。HTTP/WebSocket/TLS 使用当前已安装的 reqwest、tokio、tokio-tungstenite、rustls；证据摘要使用 SHA-256，金融数值经十进制转换，不经过浮点数。

所有真实连接由 Host 提供不可变的显式 TLS roots；不读取环境凭据，不发现代理，不跟随重定向，不自动重试。每次历史操作共享绝对 deadline，响应和分页总字节有限。Product 拥有凭据、授权、实际 WAL、不可变版本、采集输入和正式发布。

Spot 规则捕获由公开 REST 与离线归一化消费同一组响应。USD-M 归一化消费交易所及 Funding 两份公开响应和调用方提供的两份账户/杠杆响应。Crypto 市场插件消费独立的规则资源，历史资源保留原始内容、权威身份及覆盖区间。

## 公开接口

USD-M 杠杆档按协议逐字段接纳 JSON number 或既有十进制字符串，保留原 bytes SHA，不经浮点数。晚到 Funding 保留经济边界和实际可见时间；组装验证由 Runtime 读取预先冻结 source cut，并从原 Broker Journal 证明成交及边界完整前缀。

- [`spot_source::SpotFactory`](src/spot_source.rs) 是现有正式装配：Spot 标的、日历、滚动 ticker、原生周期历史及实时 Bar、临时 Chart 数据和 probe。支持 1/3/5/15/30/60/120/240 分钟；临时数据不授予持久化或发布证明。
- [`spot_rest::PublicRest`](src/spot_rest.rs) 提供受预算的公开 HTTP。`historical_trades_observed` 用 aggTrade 的 `f` 定位原始成交 ID，再读取 historicalTrades；locator 不作为成交返回。返回可能含范围外边界记录，调用者按 `[start,end)` 选择 canonical facts；空页/短页不自动证明 COMPLETE。`trade_suffix_observed` 严格补全闭区间原始 ID，缺号、错号立即失败。`reference_price_observed` 仅读取 referencePrice，绝不以 avgPrice 替代。这三项 REST 方法要求显式 GLOBAL STANDARD/GCP/API1–API4 profile；默认 PUBLIC_MARKET_DATA、US 与 Testnet 缺乏对应端点支持依据，在 I/O 前返回 Unsupported，不切换环境或主机。公开只读 WebSocket 仍按官方 market-stream 契约支持 Trade 和 Reference。
- [`PublicRest::reference_capture_observed`](src/spot_rest.rs) 用同一总时限获取 exchangeInfo 和 executionRules，保存实际请求参数和原文。支持 GLOBAL 标准、GCP、API1–API4 及 Spot Testnet；PUBLIC_MARKET_DATA 与 US 的请求在发出前返回 Unsupported。[Spot General API](https://developers.binance.info/en/docs/catalog/core-trading-spot-trading/api/rest-api/general)、[Spot Testnet 变更](https://github.com/binance/binance-spot-api-docs/blob/master/testnet/CHANGELOG.md)
- [`spot_reference`](src/spot_reference.rs) 将 Binance 原生订单类型拆为 Domain 类型及执行指令（例如 LIMIT_MAKER 对应 LIMIT 与 PostOnly），并校验 Spot 支持的 GTC、IOC、FOK。
- [`spot_facts`](src/spot_facts.rs) 提供 REST/WS 原始成交与场所参考价的纯转换，保留 raw trade ID、maker/aggressor、价格/数量精度；参考值为 null 时保留 unavailable 事实。拒绝错误标的、负序列、无效时间、非布尔 maker flag 与非参考价格事件。
- [`spot_source::SpotFactClient`](src/spot_source.rs) 提供真实 Spot Trade/Reference WebSocket 库连接。`SpotFactConnection::next` 必须先取得 owning recorder 成功，再返回事实；坏输入也保留 raw bytes，持久化失败永久停止该连接，断线返回 Gap。连接成功不授予 READY，调用者显式重连并恢复原 scope。
- [`trade_continuity::TradeContinuity`](src/trade_continuity.rs) 管理单一 Spot Source/版本/标的 scope 的易失成交检查点、有界缓冲和去重。缺口保持 Recovering，精确补全原 ID 后才能 Ready；断线、缓冲溢出、冲突与持久化失败不得维持 Ready。多个任务必须通过同一可变所有者或外部同步串行访问。
- [`reference_capture`](src/reference_capture.rs) 读取原始 Spot 双响应或显式提供的 USD-M 四响应，生成带来源的不可变捕获及规则资源。公开源与账户源分开绑定，捕获保留原字节、端点、请求范围和 SHA。
- [`reference_store`](src/reference_store.rs) 在调用方提供的私有目录发布 Spot 原始捕获及语义资源；读取原捕获会重验响应与来源，语义读取通过外部保存的 manifest SHA 校验观测时刻，无需重跑当前归一化器。错误或损坏不能覆盖。
- [`usdm_rest::UsdmRest`](src/usdm_rest.rs) 提供 USD-M contract/mark/index 的 1m 历史和 funding 历史，保留原始响应，校验半开范围、页内顺序、游标进展与返回标的；Index 使用 `pair`，其他端点使用 `symbol`。另提供 exchangeInfo/fundingInfo 公共规则输入，不查询私有账户/杠杆数据。
- [`usdm_facts`](src/usdm_facts.rs) 提供严格衍生品身份的 contract Bar、MARK/INDEX 参考事实及 funding exact-mark 配对。`Context` 显式绑定 instrument、data_version、source_sequence 和 received_at；Funding 保留旧事实 ID 算法、相同原记录 SHA、证据 ID 及 Domain 的稳定 mark-before-funding 顺序。

协议错误由 `spot_rest::Error` 返回；正式 Source 采用 `SourceError`。无效输入、未知连续性、响应不可用和证据写入失败分别保留错误语义，不降级为空成功。

**实际装配限制：**正式 `source::Resource` / `Observation` / `Stream` 当前只消费 Bar，尚未消费上述非 Bar 库事实。USD-M 原描述符无 probe contract，不能通过现行后端 Source 准入；当前没有安装 USD-M Factory。上述库接口的存在不等于正式 Web/API、Backtest/SIM/LIVE 已支持这些事实。USD-M 旧实现本来不支持实时订阅，也没有有效的历史 Trade 采集，不能由迁移声明新增支持。非 Bar 正式采集、存储与消费仍需共同闭合正式契约。

## 状态与生命周期

Spot 正式 Bar 流在单一 coordinator 中串行修改状态、缓冲、去重、恢复和 READY 证明。临时流不生成持久化 receipt。非 Bar 连接只声明 transport 和单次外部观察；`TradeContinuity` 只有在真实 baseline、订阅建立和完整后缀证明后进入 Ready。恢复输入必须与原 Source、版本和标的 scope 绑定，不能把重连视为新的序列起点。

`Recorder` 或库级 owning callback 必须完成真实持久化后返回成功；写入失败不外露数据。易失状态不是 WAL、持久游标或跨进程恢复证明。Product 的持久恢复、交易生命周期、权限及正式发布不由插件代管。

## 使用与验证

[USD-M 组装测试](tests/usdm_assembled_runtime.rs) 使用原生 Crypto 规则、Broker Journal、Virtual Broker 场所调度与 SQLite Runtime。测试的开发依赖包括 onlyalpha-broker、onlyalpha-broker-virtual、onlyalpha-runtime。Virtual Broker 按自身报价资金容量决定接单与排程；资金 100000 时原订单条件成立，资金 20 时场所会因 120 名义拒单。Runtime 独立验证初始保证金 12，依据真实终态释放原预留。永续权益与 Funding 取自 Kernel 持久状态。

在 workspace 运行 `cargo test -p onlyalpha-data-source-binance`。独立期望值位于 [`tests/canonical_facts.rs`](tests/canonical_facts.rs)，序列/恢复断言位于 [`tests/trade_continuity.rs`](tests/trade_continuity.rs)，受控真实 HTTP 位于 [`src/tests/usdm_rest.rs`](src/tests/usdm_rest.rs)，现有 Bar/实时 socket/持久化断言保留在源码测试和 [`tests/native_source.rs`](tests/native_source.rs)。测试使用受控输入，不能替代真实 Binance/Testnet 专项或正式应用权限验收。

协议参考：[Spot Market](https://developers.binance.com/en/docs/catalog/core-trading-spot-trading/api/rest-api/market)、[USD-M Market Data](https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/rest-api/market-data)。市场规则、账户模式和费用的解释归 Crypto/Broker 对应边界。
