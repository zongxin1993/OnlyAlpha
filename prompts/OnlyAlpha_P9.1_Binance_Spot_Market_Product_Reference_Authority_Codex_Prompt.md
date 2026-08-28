# OnlyAlpha P9.1 — Binance Spot Market Product & Reference Authority
## Codex 实现任务提示词

> 目标：切实实现 P9.1，不要停留在审计、讨论或生成报告。
>
> 核心原则：**Correctness > Architecture Consistency > Verifiability > Recoverability > Maintainability > Performance > Automation**
>
> 本任务不要求 Binance API Key/Secret，不允许把任何真实密钥写入代码、fixture、日志、文档或提交历史。

---

# 0. 任务身份

你正在 `zongxin1993/OnlyAlpha` 主线工程中实现：

**P9.1 — Binance Spot Market Product & Reference Authority**

P9.1 是 Binance Spot Golden Vertical 的第一步。

当前冻结的后续主线是：

```text
P9.1  Binance Spot Market Product & Reference Authority
  ↓
P9.2  Binance Spot Historical & Realtime DataSource
  ↓
P9.3  Production Data Foundation / WAL + ClickHouse + PostgreSQL
  ↓
P9.4  Binance Spot Real Broker
  ↓
P9.5  LIVE Runtime Composition & Safety
  ↓
P9.6  Research → Backtest → SIM → LIVE
  ↓
P9.7  Fault / Recovery / Certification
```

P9.1 的任务不是“包装 Binance REST API”。

P9.1 的任务是建立：

```text
Binance Provider Reality
        ↓
Raw Provider Evidence
        ↓
Strict / typed interpretation
        ↓
Immutable Binance Spot Reference Snapshot
        ↓
Canonical semantic fingerprint
        ↓
OnlyAlpha Market Reference Authority
        ↓
OnlyAlpha Market Product
        ↓
deterministic Market Product Binding
```

完成后，Trading Plane 在不访问 Binance 网络的情况下，也能基于一份 exact immutable reference snapshot 确定性回答：

- BTCUSDT / ETHUSDT 是什么 instrument；
- 当前冻结的 price/quantity/notional rules 是什么；
- symbol 当前 reference status 是什么；
- venue 声明了哪些 order/capability；
- 当前使用哪一份 provider evidence；
- reference fingerprint 是什么；
- 同一份 snapshot 是否能确定性重建同一 Market Product Binding。

---

# 1. 开始前必须阅读的当前工程事实

先读源码和当前正式设计，然后立即实施。不要无休止审计。

必须至少阅读：

```text
AGENTS.md
project-state.toml

docs/adr/0099-binance-spot-first-golden-vertical-and-provider-sequencing.md
docs/p9_binance_spot_golden_vertical_execution_plan.md
docs/p9_production_trading_vertical_architecture.md

docs/adr/0069-market-product-contract-and-composition-authority.md
docs/adr/0070-generic-t0-cash-market-product-and-canonical-market-ir.md

src/onlyalpha/domain/instrument.py
src/onlyalpha/domain/enums.py
src/onlyalpha/domain/market_rules.py

src/onlyalpha/market/models.py
src/onlyalpha/market/runtime_rules.py
src/onlyalpha/market/product/
src/onlyalpha/plugin/api.py

packages/market/onlyalpha-market-generic-t0-cash/
packages/market/onlyalpha-market-cn-ashare/
packages/provider/onlyalpha-plugin-tushare/

pyproject.toml
scripts/verify.py
```

特别确认当前事实：

```text
project-state.toml
next_authorized_increment = P9.1
```

`project-state.toml` 是当前工程 progression 唯一 authority。

不要为了本任务手工修改 README/roadmap 的 projected current-state 字段。

---

# 2. 外部参考材料

## 2.1 第一权威：Binance 官方文档

实现时以当前 Binance Spot 官方 API 文档为 Provider Reality authority。

重点核对：

```text
GET /api/v3/exchangeInfo
GET /api/v3/executionRules
GET /api/v3/ping
GET /api/v3/time
```

以及当前：

```text
Spot filters
Spot enum definitions
order types
time-in-force
STP
order-list capabilities
```

当前官方文档入口可从：

```text
https://developers.binance.com/docs/binance-spot-api-docs/rest-api/general-endpoints
https://developers.binance.com/docs/binance-spot-api-docs/filters
https://developers.binance.com/docs/binance-spot-api-docs/enums
```

进入。

不要依赖博客、过期 SDK README 或第三方枚举作为 Provider Reality authority。

## 2.2 NautilusTrader

参考：

```text
https://github.com/nautechsystems/nautilus_trader
```

重点学习思想：

- Data / Execution 分离；
- Instrument Provider；
- product type / environment 显式建模；
- provider internals 不泄漏到上层；
- ambiguous execution 不 blind retry；
- provider adapter 与 Core canonical semantic 分离。

## 2.3 Freqtrade

参考：

```text
https://github.com/freqtrade/freqtrade
```

重点学习思想：

- Binance-specific quirks 的集中处理；
- public data 与 private trading 分离；
- fixture / online exchange compatibility tests；
- 后续 P9.2 可参考 archive + REST fallback。

## 2.4 许可证约束

**只参考架构思想和公开行为，不复制 NautilusTrader/Freqtrade 的实现代码、测试代码或注释。**

OnlyAlpha 必须保持独立实现。

---

# 3. 冻结范围

P9.1 当前只做：

```text
Provider: Binance
Market: Spot
Reference symbols:
- BTCUSDT
- ETHUSDT
```

BTCUSDT 是主要 acceptance instrument。

ETHUSDT 用来证明实现不是 BTC-specific hard-code。

## 明确不做

```text
Binance USD-M Futures
COIN-M Futures
Margin
Real order submission
Account query
Balance query
User Data Stream
API signing
API credentials
WebSocket trading
Realtime market WebSocket
Historical Kline/Trade ingestion
ClickHouse tables
PostgreSQL production reference schema
LIVE Runtime
QMT
CTP
CCXT integration
Binance SDK integration
SBE
Kafka
Redis
Kubernetes
```

P9.1 不能偷偷扩大成 P9.2/P9.3/P9.4。

---

# 4. 第一性原理与不可破坏不变量

## 4.1 API response 不是 Authority

错误：

```text
Runtime startup
→ GET Binance exchangeInfo
→ directly build mutable rules
```

正确：

```text
ONLINE / CONTROL SIDE

Binance
→ capture
→ raw evidence
→ parse
→ normalize
→ immutable snapshot
→ verified store

---------------- authority boundary ----------------

TRADING / PRODUCT SIDE

exact snapshot
→ Reference Authority
→ Market Policy Compiler
→ Resolved Market Product Binding
```

Market Product resolution 不得依赖实时网络。

---

## 4.2 一个 semantic fact 只能有一个 Authority

必须保持：

```text
Provider raw truth
→ immutable raw capture

OnlyAlpha normalized Binance reference truth
→ immutable Reference Snapshot

Runtime market semantics
→ resolved Market Product Binding + compiled market policy
```

不要创建：

```text
mutable "latest instrument table"
+
snapshot
+
runtime cache
```

三套都声称是 authority。

Cache 只能是 cache。

---

## 4.3 Capture Identity 与 Semantic Identity 分离

必须存在两个不同概念：

```text
Raw Capture Identity
=
exact response bytes + provenance

Reference Semantic Identity
=
normalized economic / market semantics
```

例如：

```text
10:00 capture
serverTime=A
BTCUSDT tickSize=0.01

10:05 capture
serverTime=B
BTCUSDT tickSize=0.01
```

必须满足：

```text
raw_capture_fingerprint A != raw_capture_fingerprint B

reference_fingerprint A == reference_fingerprint B
```

`captured_at`、`serverTime`、HTTP headers、request latency、rate-limit usage count 等 operational/provenance 字段不得进入 market semantic fingerprint。

---

## 4.4 规则真正变化才产生新 semantic revision

```text
same normalized semantics
→ same reference fingerprint
→ idempotent semantic publication

tickSize / stepSize / status / relevant rule changes
→ new reference fingerprint
→ new immutable semantic revision
```

不允许“每次抓取都 version + 1”。

---

## 4.5 Provider DTO 不得进入 Core

严格保持：

```text
Binance JSON
→ Binance DTO
→ Binance adapter/normalizer
→ OnlyAlpha canonical / Market Product type
```

禁止：

```text
Core imports onlyalpha_plugin_binance
Core imports Binance enums
Runtime checks if venue == BINANCE
Strategy checks Binance fields
```

---

## 4.6 不允许为 Binance 建第二套 Trading Engine

禁止：

```text
BinanceEngine
BinanceRuntime
BinanceRiskManager
BinanceOrderManager
```

P9.1 必须接入既有：

```text
OnlyMarketProductFactory
OnlyMarketReferenceAuthority
OnlyMarketPolicyCompiler
OnlyResolvedMarketProductBinding
```

---

## 4.7 Immutable Binding 不得被“最新规则”偷偷修改

当前 `OnlyResolvedMarketProductBinding` 是 immutable composition authority。

因此 P9.1 的第一版必须：

```text
one Runtime/Product composition
→ bind one exact reference authority identity
→ reference does not mutate underneath binding
```

如果后续 capture 发现 Binance 规则变化：

```text
old reference
→ remains immutable

new capture
→ new semantic snapshot
→ new reference authority identity
→ new market composition identity
```

P9.1 **不实现运行中 hot-rebind**。

LIVE 对 reference change 的 fail-closed / controlled rebind 属于 P9.5。

不要为了“动态更新”把 mutable latest reference 注入 immutable binding。

---

# 5. 目标工程结构

## 5.1 Market Product package

新增：

```text
packages/market/onlyalpha-market-binance-spot/
├── pyproject.toml
├── README.md
├── src/
│   └── onlyalpha_market_binance_spot/
│       ├── __init__.py
│       ├── config.py
│       ├── reference.py
│       ├── capability.py
│       ├── compiler.py
│       ├── fee_pack.py
│       ├── factory.py
│       └── py.typed
└── tests/
```

职责：

```text
Binance Spot economic/reference semantics
OnlyMarketReferenceAuthority implementation
Policy Compiler
Market Product Factory
immutable semantic models
```

它必须：

```text
depend on OnlyAlpha Core contract
```

Core 绝不能反向依赖它。

注册：

```toml
[project.entry-points."onlyalpha.market_products"]
binance-spot = "onlyalpha_market_binance_spot.factory:OnlyBinanceSpotMarketProductFactory"
```

名称如与仓库约定冲突，以现有命名规则为准，但只能有一个正式入口。

---

## 5.2 Provider package

新增或建立：

```text
packages/provider/onlyalpha-plugin-binance/
├── pyproject.toml
├── README.md
├── src/
│   └── onlyalpha_plugin_binance/
│       ├── __init__.py
│       ├── config.py
│       ├── descriptor.py
│       ├── errors.py
│       ├── doctor.py
│       ├── common/
│       │   ├── environment.py
│       │   └── http.py
│       └── spot/
│           └── reference/
│               ├── dto.py
│               ├── client.py
│               ├── capture.py
│               ├── normalize.py
│               └── store.py
└── tests/
```

P9.1 Provider package 的职责只有：

```text
public HTTP
raw Binance response
strict required-field parsing
critical-schema compatibility detection
capture provenance
normalization
immutable snapshot publication/load verification
```

**P9.1 不注册正式 realtime DataSource。**

P9.2 再在同一个 package 内加入 `onlyalpha.data_sources`。

可以提供一个 operator CLI，例如：

```text
onlyalpha-binance-reference
```

用于：

```text
capture
inspect
verify
```

但 CLI 只做 operator tooling，不能成为第二个 product authority。

---

# 6. Workspace 集成

更新 root `pyproject.toml`，按现有 monorepo 规则加入：

```text
tool.uv.workspace.members
tool.uv.sources
pytest testpaths
mypy files
import-linter core-plugin-boundary forbidden_modules
```

至少需要把：

```text
onlyalpha_plugin_binance
onlyalpha_market_binance_spot
```

加入 Core forbidden plugin implementation 列表。

还要检查当前 version-sync/build/release scripts 是否需要登记新 workspace package。

不要通过跳过检查来让新 package “暂时通过”。

---

# 7. P9.1.0 — Generic Crypto Spot 语义预检与最小补齐

这是一次**有界 preflight + 立即实现**，不是审计阶段。

必须确认当前已有：

```text
OnlyCryptoSpot
OnlyMarketType.CASH
OnlyExchange.BINANCE
OnlyOrderType canonical vocabulary
OnlyTimeInForce
OnlyTradingSessionModel
OnlySettlementModel
OnlyMarketProduct contract
```

当前已有能力能复用就直接复用。

## Crypto Spot policy 基线

目标语义：

```text
asset_class = CRYPTOCURRENCY
instrument_type = CRYPTO_SPOT
market_type = CASH

position = LONG_ONLY / no naked short
margin = None
settlement = immediate / T+0
asset availability = immediate
cash availability = immediate

session = UTC continuous 24x7
```

如果已有完全等价的 Generic 24x7 semantics，复用。

如果缺失，只增加**最小 market-neutral contract**。

禁止增加：

```text
BinanceCalendar
BinanceSettlementRule
BinancePositionMode
```

到 Core。

应该是 generic crypto/cash semantic。

---

# 8. P9.1.1 — Binance Spot Public Reference Client

## 8.1 Environment

显式建模：

```text
LIVE
TESTNET
```

P9.1 当前 Reference acceptance 主要使用 public LIVE reference endpoint。

Environment 是 provider provenance，不是 Strategy semantic identity。

不要用：

```text
if "testnet" in url
```

推断环境。

---

## 8.2 HTTP client

只实现 public GET 所需最小 transport。

必须支持：

```text
explicit connect/read timeout
deterministic query construction
bounded response size
JSON media validation where appropriate
HTTP status classification
clear provider errors
```

禁止：

```text
infinite retry
hidden automatic retry
credential/signing
```

对于 Reference capture，可允许明确、有限、只读 GET retry policy，但必须：

```text
bounded
observable
not change semantic identity
```

如果项目已有通用 HTTP transport，优先复用。

如果没有，只引入一个必要且窄的 HTTP dependency。

**不要引入 CCXT。**
**不要引入 Freqtrade。**
**不要依赖 NautilusTrader。**
**不要引入 Binance SDK 只是为了 GET exchangeInfo。**

---

## 8.3 Endpoints

至少实现：

```text
GET /api/v3/exchangeInfo
GET /api/v3/executionRules
GET /api/v3/ping
GET /api/v3/time
```

Reference capture 对 BTCUSDT / ETHUSDT 应使用显式 symbol/symbols 参数，不依赖“下载全交易所再偷偷筛选”。

---

# 9. P9.1.2 — Raw Provider Evidence

定义 immutable raw capture，例如概念上：

```text
BinanceSpotReferenceCapture
───────────────────────────
capture_schema_version

environment
endpoint
normalized_request_parameters

captured_at_utc
http_status
selected_response_metadata

raw_body_bytes
raw_sha256

provider_server_time (if available)
parser_version
```

原则：

```text
raw_sha256 = SHA256(exact raw response bytes)
```

不要 canonicalize 后再叫 raw hash。

Raw evidence 必须可用于：

```text
re-parse
debug
schema migration
audit
```

但 raw JSON 不是 Market Product semantic identity。

---

# 10. P9.1.3 — Binance DTO 与 Schema Compatibility Policy

## 10.1 不要使用万能 dict

关键表面必须 typed：

```text
ExchangeInfo
SymbolInfo
Filter
ExecutionRules
ExecutionRule
```

所有 Decimal-like numeric values：

```text
price
qty
notional
multiplier
```

必须从原始 string → Decimal。

严禁先转 float。

---

## 10.2 Unknown field 策略

不要简单使用两种极端：

```text
所有 unknown field 都 ignore
```

或：

```text
任何新增 JSON field 都使整个系统崩溃
```

采用：

```text
required known fields
→ strict validation

unknown critical discriminator:
  filterType
  ruleType
  orderType
  status
  critical capability enum
→ fail closed for trade-eligible reference

unknown non-critical field
→ preserve in raw evidence
→ expose compatibility diagnostic
→ do not silently make it economic semantic
```

如果无法证明 unknown field 是 non-critical：

```text
reference may be captured
but cannot be marked trade-eligible
```

---

# 11. P9.1.4 — Immutable Binance Spot Reference Snapshot

## 11.1 每个 instrument 的 semantic reference

建议表达类似：

```text
OnlyBinanceSpotReference
────────────────────────
schema_version

instrument_id
raw_symbol

base_currency
quote_currency
settlement_currency

provider_status
spot_trading_allowed

price_filter
lot_size_filter
market_lot_size_filter
notional_filter
percent_price_filter
percent_price_by_side_filter
trailing_delta_rule
other explicitly supported economic rules

execution_price_range_rule

venue_order_types
venue_order_group_capabilities
quote_order_qty_market_allowed
trailing_stop_allowed
cancel_replace_allowed
amend_allowed
peg_instructions_allowed

default_stp_mode
allowed_stp_modes
permission_sets

source_raw_fingerprints
semantic_reference_fingerprint
compatibility_status
```

实际类名和拆分可按工程整洁性调整。

---

## 11.2 Instrument 与 Reference 分离

Provider normalizer 同时可产生：

```text
OnlyCryptoSpot
+
OnlyBinanceSpotReference
```

但二者 identity 不同。

必须保证：

```text
BTCUSDT identity
```

不会因为 minNotional 改变就变成另一个 instrument。

规则变化应表现为：

```text
same instrument identity
+
new reference fingerprint
```

---

# 12. Filter 语义分类

不要把全部 Binance filters 塞进 `OnlyInstrument`。

至少分成：

## A. Instrument / static economic constraints

```text
PRICE_FILTER
LOT_SIZE
MIN_NOTIONAL / NOTIONAL
```

映射到：

```text
tick
price bound
quantity increment
quantity bound
notional bound
```

---

## B. Order-type-specific constraints

```text
MARKET_LOT_SIZE
```

不得覆盖普通 LIMIT `LOT_SIZE`。

如果现有 Canonical Market IR 没有 order-type-specific quantity policy：

1. 先证明确实需要；
2. 增加最小 market-neutral abstraction；
3. 不要命名为 BinanceMarketLotSizeRule；
4. 不要用一个近似字段伪装成等价语义。

---

## C. Dynamic market constraints

```text
PERCENT_PRICE
PERCENT_PRICE_BY_SIDE
executionRules PRICE_RANGE
```

它们不是静态 `min_price/max_price`。

如果当前 Core IR 无法准确表达：

```text
reference-price-relative dynamic band
```

允许做最小的 market-neutral 扩展，例如概念：

```text
OnlyDynamicReferencePriceBand
reference_price_semantics
lookback
bid multiplier range
ask multiplier range
```

但先检查现有 `DYNAMIC_PRICE_CAGE` 和相关 market-rule contract，避免建立重复 Authority。

---

## D. Stateful venue/account capacity limits

例如：

```text
MAX_NUM_ORDERS
MAX_NUM_ALGO_ORDERS
MAX_NUM_ICEBERG_ORDERS
MAX_POSITION
MAX_NUM_ORDER_LISTS
MAX_NUM_ORDER_AMENDS
```

P9.1 必须：

```text
parse
preserve
classify
fingerprint when semantically relevant
```

但不要让 immutable Instrument 自己维护 mutable count/state。

真正 enforcement authority 后续属于 Broker/Execution state。

---

# 13. Order Capability Mapping

Binance native enum 不得进入 Core。

目标映射概念：

```text
LIMIT
→ OnlyOrderType.LIMIT

MARKET
→ OnlyOrderType.MARKET

STOP_LOSS
→ OnlyOrderType.STOP_MARKET

STOP_LOSS_LIMIT
→ OnlyOrderType.STOP_LIMIT

TAKE_PROFIT
→ OnlyOrderType.MARKET_IF_TOUCHED

TAKE_PROFIT_LIMIT
→ OnlyOrderType.LIMIT_IF_TOUCHED

LIMIT_MAKER
→ LIMIT + POST_ONLY execution instruction
```

不要新增：

```text
OnlyOrderType.LIMIT_MAKER
```

除非能从 market-neutral first principles 证明 Core 需要一个新的独立经济 order type。

---

# 14. Order Group Capability

OCO/OTO/OPO 等不是普通 OrderType。

必须概念分离：

```text
Single Order Capability
vs
Order Group Capability
```

Reference 可以记录 venue capability：

```text
OCO supported
OTO supported
OPO supported
...
```

但 P9.1 不实现这些高级订单的 Broker submission。

必须区分：

```text
Venue Capability
!=
OnlyAlpha Execution Capability
```

后续有效能力是：

```text
Effective Capability
=
Venue Capability
∩
OnlyAlpha Execution Support
```

---

# 15. Time In Force

不要错误宣称 `exchangeInfo` 返回了 per-symbol TIF，如果官方响应没有该字段。

将：

```text
GTC
IOC
FOK
```

视为 Binance Spot protocol/order semantic capability，由 adapter/provider contract 明确定义，并与 per-symbol `orderTypes` 组合判断。

不要把：

```text
GTD
DAY
```

因为 Core enum 存在就自动宣称 Binance Spot 支持。

---

# 16. STP / Permissions / Status

## Status

集中映射一次。

不要在 Runtime 分散解释 Binance status。

概念：

```text
TRADING
→ TRADABLE

HALT / BREAK
→ SUSPENDED / non-tradable

unknown
→ fail closed
```

实际映射必须依据当前官方 enum 和现有 `OnlyInstrumentTradingStatus` 定义。

---

## STP

`defaultSelfTradePreventionMode` 与 `allowedSelfTradePreventionModes`：

```text
provider reference
→ canonical capability/evidence
```

P9.1 不实现 account-level STP execution state。

---

## Permissions

保留 `permissionSets` 的真实 AND/OR 语义。

不要 flatten 成：

```text
{"SPOT", "MARGIN"}
```

然后丢掉组合关系。

第一条 Spot vertical 必须能明确证明目标 instrument 具有允许 Spot 的 permission path。

---

# 17. 24×7 Crypto Market Policy

Binance Spot Market Product 应编译出 provider-neutral：

```text
timezone = UTC
continuous_24x7 = true
phase = CONTINUOUS
```

以及：

```text
cash/asset settlement = immediate / T+0
cash/asset trading availability = immediate
short selling = disabled
position mode = long-only / cash semantics
margin = None
```

不要创建 Binance-specific Core session model。

同时必须保持：

```text
24x7 session open
!=
instrument tradable
```

Trade eligibility 至少还需要：

```text
symbol status
spot permission
required reference understood
required rule support
```

---

# 18. Reference Authority 与 Immutable Binding

新增：

```text
OnlyBinanceSpotReferenceAuthority
```

必须实现现有：

```text
OnlyMarketReferenceAuthority
```

其 `identity` 必须由：

```text
authority type/version
+
sorted exact semantic references
```

确定生成。

`resolve(instrument_id, trading_day)`：

- 不访问网络；
- 不访问 mutable latest；
- 只从 bound immutable snapshot set 解析；
- 未覆盖 instrument → fail closed；
- historical applicability 无法证明 → 不得伪造 exact historical authority。

---

# 19. 关于 current trading_day-only Reference contract

当前 Core Market Product Reference 是以：

```text
instrument_id + trading_day
```

解析。

不要为了 Binance 立刻做大规模 `as_of timestamp` 重构。

第一版遵守：

```text
one immutable reference snapshot
→ one immutable binding
```

并把 rule change 表达成：

```text
new snapshot
→ new reference authority
→ new composition identity
```

P9.1 不做 runtime hot mutation。

但是必须：

- 在 snapshot 中保存精确 `observed_at`；
- 明确不把 snapshot back-project 成 observation 之前的 exact historical rules；
- 测试中不要把同日 observation 之前的数据宣称为 exact reference coverage；
- 如果现有 API 无法诚实表达这个边界，做**最小必要 market-neutral 改动**，而不是在 Binance plugin 内撒特殊判断。

对于 P9.6 第一条 certification dataset，应选择 reference observation 之后的受控时间范围，从而不伪造历史规则。

---

# 20. Semantic Fingerprint

必须复用 OnlyAlpha 已有 canonical identity/fingerprint primitives。

不要重新：

```python
json.dumps(..., sort_keys=True)
```

创造第二套 identity 体系，除非现有 primitive 明确不能满足并有测试证明。

## Per-instrument reference fingerprint

必须仅包含会影响语义的 canonical values，例如：

```text
instrument identity
provider status / tradability
economic filters
dynamic rules
venue semantic capabilities
STP/permission semantics
schema semantic version
```

不得包含：

```text
captured_at
HTTP status
HTTP headers
request latency
serverTime
rateLimit current count
raw JSON key order
filesystem path
temporary file name
```

## Authority fingerprint

对所有 selected instrument references：

```text
stable sort
→ canonical composition
→ authority fingerprint
```

同样输入必须产生相同 fingerprint。

---

# 21. Immutable Reference Store

先搜索工程是否已有可复用的：

```text
content-addressed store
immutable artifact publication
verified load
atomic staged publication
```

如果已有，复用。

如果没有，只实现 plugin-owned 的最小 store，不要建立 universal framework。

要求：

```text
put(snapshot)
load_verified(fingerprint)
```

语义：

```text
same fingerprint + same content
→ idempotent success

same fingerprint + different content
→ deterministic conflict

corrupt bytes
→ fail closed

missing
→ explicit NOT_FOUND

no overwrite
no update
no repair-in-place
no mutable latest authority
```

可以提供 convenience catalog/index，但：

```text
latest
```

不能成为 Trading authority。

P9.3 再把 reference provenance/control persistence 与正式 PostgreSQL 基础设施连接。

---

# 22. Reference Capture Lifecycle

建议 operator 流程：

```text
capture requested symbols
        ↓
persist raw evidence
        ↓
parse/validate
        ↓
normalize
        ↓
calculate semantic fingerprint
        ↓
load existing fingerprint?
   ├─ same → semantic reuse
   └─ absent → immutable publish
        ↓
emit capture result
```

Capture Result 至少报告：

```text
raw capture fingerprint
semantic reference fingerprint
new/reused
compatibility status
symbols
observed_at
```

不能自动修改运行中 Market Product Binding。

---

# 23. Fee Authority

P9.1 没有 private API credentials。

因此：

**不能宣称拿到了 account actual maker/taker fee。**

先读当前：

```text
fee authority ADR
OnlyMarketFeePack
OnlyBrokerFeeContract
```

然后只实现现有 Market Product Binding 所需的最小、诚实 fee contract。

建议：

```text
configured baseline fee pack
```

其 provenance 明确为：

```text
CONFIGURED_BASELINE
```

而不是：

```text
ACCOUNT_ACTUAL
```

禁止：

```text
硬编码一个网上常见 Binance VIP0 费率
然后称为 Binance authoritative fee
```

P9.4 有 private account 后再解决 account-specific commission authority。

---

# 24. Config

保持很小。

概念：

```yaml
market:
  plugin_id: onlyalpha-market-binance-spot
  product_id: BINANCE_SPOT
  product_version: "1"
  config:
    reference_resource_id: ...
    expected_reference_fingerprint: ...
    fee_baseline: ...
```

Provider capture config 概念：

```yaml
binance:
  environment: LIVE
  symbols:
    - BTCUSDT
    - ETHUSDT
```

Transport-only fields：

```text
timeout
proxy
retry
log level
capture path
```

不得仅因为存在配置中就进入 economic composition identity。

---

# 25. Market Product Factory

实现：

```text
OnlyBinanceSpotMarketProductFactory
```

必须遵守现有 Factory contract。

核心流程：

```text
validate plugin/product/version
↓
parse typed config
↓
obtain exact immutable reference authority
↓
verify expected authority/reference fingerprint
↓
construct Binance Spot policy compiler
↓
construct explicit baseline Market Fee Pack
↓
OnlyResolvedMarketProductBinding.create(...)
```

不得：

```text
factory.resolve()
→ HTTP request Binance
```

不得：

```text
factory.resolve()
→ "use latest snapshot"
```

必须是 exact selection。

当前 `OnlyMarketProductResolutionContext` 已提供 resource resolver port。

优先使用现有 contract。

当前 Engine `_NoExternalMarketProductResources` 仍拒绝 external resources。

P9.1 不要为了展示 demo 而绕过它。

如果本阶段确实需要正式 Engine composition 接入：

1. 先证明这是 P9.1 exit criteria 的必要条件；
2. 增加最小 exact immutable resource resolver；
3. 不得引入 mutable latest/catalog fallback；
4. 不得削弱 Generic T0 / CN A-share 路径。

否则只在 Market Product contract/conformance tests 中使用 exact test resource resolver，并把正式 Runtime binding 留给后续 composition 阶段。

---

# 26. P9.1 分步执行

## P9.1.0 — Crypto Spot Semantic Foundation

交付：

- 复用/最小补齐 Generic 24×7 Spot semantic；
- 证明不需要 Binance-specific Core branch；
- 相关 unit/contract tests。

---

## P9.1.1 — Binance Public Reference Provider

交付：

- provider workspace package；
- environment；
- public HTTP client；
- `/exchangeInfo`；
- `/executionRules`；
- raw DTO；
- bounded error handling；
- no credentials。

---

## P9.1.2 — Raw Capture + Immutable Snapshot

交付：

- raw evidence capture；
- exact raw hash；
- semantic normalization；
- BTCUSDT fixture；
- ETHUSDT fixture；
- semantic reference fingerprint；
- immutable verified store。

---

## P9.1.3 — Binance Spot Market Product

交付：

- market workspace package；
- reference authority；
- policy compiler；
- market product factory；
- entry-point discovery；
- binding identity；
- provider-neutral compiled policy。

---

## P9.1.4 — Trading Rules & Capability Mapping

交付：

- filters 分类；
- static/dynamic/order-specific/stateful rule 处理；
- order type mapping；
- TIF semantics；
- STP；
- permissionSets；
- order-group venue capability；
- unknown critical rule fail-closed。

---

## P9.1.5 — Fee Baseline + Reference Lifecycle

交付：

- explicit configured fee baseline；
- content-change semantic revision；
- repeated capture semantic reuse；
- exact reference selection；
- no mutable latest authority。

---

## P9.1.6 — Determinism / Contract / Architecture Closure

交付：

- deterministic fixture tests；
- real public Binance contract test；
- plugin discovery；
- architecture import gates；
- package build/type/lint；
- evidence report；
- project state transition only after all task gates pass。

---

# 27. 测试要求

## 27.1 Determinism tests

必须证明：

### Case A — JSON key order changes

```text
same semantic payload
different JSON key order
→ same semantic fingerprint
```

### Case B — serverTime changes

```text
same rules
different serverTime
→ same semantic fingerprint
```

### Case C — capture time changes

```text
same rules
different captured_at
→ same semantic fingerprint
```

### Case D — tickSize changes

```text
tickSize A != B
→ reference fingerprint A != B
```

### Case E — stepSize changes

```text
→ fingerprint changes
```

### Case F — relevant status changes

```text
TRADING → HALT
→ fingerprint changes
→ tradability changes
```

### Case G — unknown critical filter

```text
unknown filterType
→ no trade-eligible reference
```

### Case H — duplicate semantic publication

```text
same fingerprint + same content
→ idempotent reuse
```

### Case I — semantic conflict

```text
same claimed fingerprint + different canonical content
→ fail closed
```

### Case J — corruption

```text
modified stored bytes
→ verified load fails
```

---

# 28. Capability tests

至少覆盖：

```text
LIMIT
MARKET
STOP_LOSS
STOP_LOSS_LIMIT
TAKE_PROFIT
TAKE_PROFIT_LIMIT
LIMIT_MAKER

GTC
IOC
FOK

OCO/OTO/OPO flags

STP modes

quoteOrderQtyMarketAllowed
trailing
cancelReplace
amend
peg
```

不要把“venue supports”误写成“OnlyAlpha Broker 已支持”。

---

# 29. Reference / Market Policy tests

BTCUSDT 与 ETHUSDT 必须通过同一路径。

禁止：

```python
if symbol == "BTCUSDT":
```

业务 hard-code。

测试至少验证：

```text
OnlyCryptoSpot
base/quote
tick
step
notional
status
24x7 session
cash settlement
long-only
no margin
reference identity
compiled policy identity
Market Product composition identity
```

---

# 30. Real Binance Public Contract Test

新增明确 marker，例如复用/扩展：

```text
external
requires_network
```

如需要新 marker：

```text
requires_binance_public
```

按仓库规则登记。

真实测试：

```text
/api/v3/ping
/api/v3/time
/api/v3/exchangeInfo for BTCUSDT/ETHUSDT
/api/v3/executionRules for BTCUSDT/ETHUSDT
```

目标不是测试 Binance uptime。

目标是：

```text
current public schema
→ our parser still understands it
→ required critical semantics known
```

该测试不得成为每次快速 unit lane 的强依赖。

放：

```text
manual / scheduled / external lane
```

---

# 31. Fixtures

Fixtures 必须由 OnlyAlpha 自己维护。

禁止复制 NautilusTrader/Freqtrade fixtures。

建议：

```text
tests/fixtures/binance/spot/reference/
```

保留：

```text
raw response fixture
fixture metadata
expected canonical semantic projection
expected semantic fingerprint
```

对 stable golden fingerprint 的变更必须显式 review。

---

# 32. Architecture Tests

必须防止：

```text
onlyalpha.*
→ onlyalpha_plugin_binance

onlyalpha.*
→ onlyalpha_market_binance_spot
```

新增 Core import。

同时防止：

```text
Binance DTO
```

出现在 Core public API。

新增 Market Product 必须通过现有：

```text
entry-point discovery
third market extension
market product contract
```

风格的测试。

不要修改测试使错误设计合法。

---

# 33. 质量要求

必须执行与改动影响匹配的：

```text
ruff
format check
mypy
pytest component tests
architecture tests
plugin discovery tests
package build
project verification planner
```

优先使用：

```text
scripts/verify.py
```

选择仓库当前定义的最窄但充分 lane。

不要为了“保险”每次运行全部最慢 CI。

但是在任务结束前必须跑足以覆盖：

```text
Core contract changes
Market Product
Provider package
Architecture
Plugin discovery
Determinism
```

的 gates。

如果修改 shared Core market contract，验证范围必须相应扩大。

---

# 34. 不要无休止审计

工作方式：

```text
1. bounded repository truth check
2. implement
3. test
4. fix concrete failure
5. rerun affected gates
6. produce evidence
7. stop
```

禁止：

```text
audit
→ report
→ another audit
→ redesign unrelated components
→ no implementation
```

发现真实问题：

```text
fix it
```

发现不属于 P9.1 的问题：

```text
record as bounded follow-up
do not expand current scope
```

---

# 35. 禁止事项

绝对禁止：

- 把 Binance API Key/Secret 放进仓库；
- 让用户在 P9.1 提供 API Key；
- CCXT；
- Freqtrade 运行时依赖；
- NautilusTrader 运行时依赖；
- 复制第三方 GPL/LGPL 代码；
- Binance SDK type 泄漏 Core；
- float 解析价格/数量；
- mutable latest reference 作为 Trading authority；
- runtime 启动时直接 fetch exchangeInfo；
- unknown critical rule silent ignore；
- blind default/fallback；
- symbol hard-code；
- Core market-name dispatch；
- 新建 Binance Engine/Runtime；
- 把 OCO 当普通 OrderType；
- 把 MARKET_LOT_SIZE 覆盖 LOT_SIZE；
- 把 percent-price 动态规则伪装成 static min/max price；
- 把捕获时间加入 semantic fingerprint；
- 把 raw response hash 当 semantic reference identity；
- overwrite immutable snapshot；
- 为 P9.3 提前建设大量数据库 Schema；
- 为 P9.4 提前做 auth/order/account/user-stream；
- 为 Futures 提前扩 scope；
- 通过降低 architecture gate/coverage 使代码通过。

---

# 36. Definition of Done

P9.1 完成必须同时满足：

## A. Provider

```text
public Binance Spot reference acquisition works
no credentials required
BTCUSDT + ETHUSDT
raw evidence preserved
```

## B. Identity

```text
raw fingerprint separated from semantic fingerprint
same semantics = same identity
semantic change = new identity
```

## C. Market Product

```text
Binance Spot exists as real Market Product plugin
no Core Binance branch
exact immutable Reference Authority
deterministic Policy Compiler
deterministic Resolved Binding
```

## D. Rules

```text
price
quantity
notional
status
critical filters
executionRules
order semantics
TIF
STP
permissionSets
order-group venue capabilities
```

均被明确处理、明确分类，未知关键语义 fail closed。

## E. 24×7 Spot semantics

```text
UTC
continuous 24x7
cash T+0/immediate availability
long-only
no margin
```

通过 canonical Core semantics 表达。

## F. Store

```text
immutable
content-addressed
verified load
idempotent reuse
conflict fail closed
corruption fail closed
```

## G. Testing

```text
unit
contract
determinism
architecture
plugin discovery
public online contract
```

具备明确证据。

## H. Scope

没有偷做：

```text
P9.2 realtime/history
P9.3 databases
P9.4 broker
Futures
QMT
```

---

# 37. 最终交付报告

完成代码后输出一个简洁 implementation report，至少包含：

```text
1. implementation summary
2. exact files/packages added/changed
3. authority ownership
4. identity/fingerprint definition
5. Binance filter mapping table
6. capability mapping
7. fail-closed behavior
8. tests executed and results
9. public Binance contract test result
10. remaining bounded P9.2/P9.4 follow-ups
11. final git diff/stat
12. whether P9.1 Definition of Done is satisfied
```

不要用大量 prose 代替证据。

---

# 38. Project State

只有在：

```text
P9.1 implementation complete
+
required task gates pass
```

后，才允许按现有 `project-state.toml` authority protocol 做 progression transition。

不要手改：

```text
README current status
docs/roadmap current status
P9.K projected status
```

使用已有：

```text
scripts/project_state.py
```

机制。

下一阶段应只授权：

```text
P9.2 — Binance Spot Historical & Realtime DataSource
```

不要同时授权 Futures 或 P9.4。

---

# 39. 最终工程判断标准

最终实现应该满足：

```text
Binance changes response ordering
→ OnlyAlpha semantic identity does not drift

Binance serverTime changes
→ semantic identity does not drift

Binance tick/lot/notional/status changes
→ new reference identity

same reference bytes replayed offline
→ exact same reference identity

same exact reference authority
→ exact same Market Product composition identity

network unavailable
+
snapshot already available
→ deterministic offline reference reconstruction still works

unknown critical provider rule
→ capture may exist
→ trading eligibility fails closed

Core
→ remains provider-neutral
```

这就是 P9.1 的完成标准。

**不要把“能调用 Binance API”当作 P9.1 完成。**

P9.1 的真正产物是：

> **一个由 Binance public evidence 驱动、可离线重建、immutable、content-addressed、fail-closed、provider-neutral consumption 的 Binance Spot Market Reference Authority。**
