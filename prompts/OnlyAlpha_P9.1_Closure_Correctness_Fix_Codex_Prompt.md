# OnlyAlpha P9.1 Closure / Correctness Fix — Codex 实现任务提示词

> 任务性质：**P9.1 有界 Closure / Correctness Fix**
>
> 目标：关闭当前 P9.1 已知的 Authority、Identity、Evidence、Temporal Applicability、Market-Legality IR 和 CI 缺口，然后正式结束 P9.1。
>
> 不要重新做 P9.1，不要扩展到 P9.2/P9.3/P9.4，不要无休止审计。
>
> 工程原则：**Correctness > Determinism > Uniqueness > Explicit Authority > Fail-Closed > Recoverability > Maintainability > Performance**
>
> 当前基线（任务开始时必须重新确认）：
>
> ```text
> repository: zongxin1993/OnlyAlpha
> branch: master
> audited HEAD: 0364b423e98d44ed2919db68c3e86a51284c4aec
> commit: Feat: P9.1 — Binance Spot Market Product & Reference Authority
> ```
>
> 如果任务执行时 master 已经前移：以最新 master 为实现基线，但必须确认下面列出的 blocker 是否仍然存在，已被正确修复的不要重复重构。

---

# 1. 任务背景

OnlyAlpha 已经完成 P9.1 的主体实现：

```text
Binance public REST
→ raw reference capture
→ strict normalization
→ Binance Spot semantic reference
→ reference authority
→ Market Product compiler
→ deterministic Market Product binding
```

当前已经存在：

```text
packages/provider/onlyalpha-plugin-binance
packages/market/onlyalpha-market-binance-spot
```

并已经具备：

- `/api/v3/exchangeInfo`
- `/api/v3/executionRules`
- BTCUSDT / ETHUSDT
- raw SHA-256
- semantic reference fingerprint
- immutable Market Product binding
- unknown symbol filter fail-closed
- Spot order/TIF/STP/capability interpretation
- 24×7 UTC cash/long-only/no-margin policy
- configured baseline fee
- public Binance contract test
- Core → concrete Binance plugin architecture boundary

本任务不是扩展功能面，而是关闭以下已知 correctness gaps：

```text
C1 Capture Evidence 与 Semantic Reference Revision 尚未彻底分离
C2 Capture provenance 不完整
C3 semantic artifact 没有独立持久化，load 时依赖当前 normalizer 重解释 raw
C4 exchange-level rules 尚未进入 fail-closed Authority
C5 Market Product Compiler 未完整表达 notional / order-type-specific quantity / dynamic requirements
C6 Reference temporal applicability 仍是 trading_day 粒度，capture 当天无法诚实使用
C7 Permission / Venue Capability / Account Eligibility 边界不够严格
C8 HTTP response acquisition 未真正 bounded
C9 deterministic closure tests 和 CI closure 尚未完成
```

完成这轮以后，P9.1 应正式关闭，不再继续泛化审计，下一阶段直接进入：

```text
P9.2 — Binance Spot Historical & Realtime DataSource
```

---

# 2. 必须先阅读的工程事实

在修改之前做一次**有界 truth check**，只读与本任务直接相关的文件。

至少阅读：

```text
AGENTS.md
project-state.toml

docs/adr/0099-binance-spot-first-golden-vertical-and-provider-sequencing.md
docs/p9_binance_spot_golden_vertical_execution_plan.md
docs/reports/p9_1_binance_spot_market_product_reference_authority.md

src/onlyalpha/market/models.py
src/onlyalpha/market/runtime_rules.py

src/onlyalpha/market/product/ports.py
src/onlyalpha/market/product/models.py
src/onlyalpha/market/product/factory.py
src/onlyalpha/plugin/api.py

packages/market/onlyalpha-market-binance-spot/src/onlyalpha_market_binance_spot/
packages/market/onlyalpha-market-binance-spot/tests/

packages/provider/onlyalpha-plugin-binance/src/onlyalpha_plugin_binance/
packages/provider/onlyalpha-plugin-binance/tests/

packages/market/onlyalpha-market-cn-ashare/
packages/market/onlyalpha-market-generic-t0-cash/

scripts/verify.py
scripts/test_suite.py
scripts/project_state.py
pyproject.toml
```

确认 `project-state.toml` 仍然是工程 progression 唯一 Authority。

不要手工编辑 README / roadmap 中的 current-state projection。

---

# 3. 本任务的核心不变量

## 3.1 Observation != Semantic Identity

这是本任务最重要的不变量。

必须成立：

```text
不同 Capture
可以证明
同一个 Reference Revision
```

例如：

```text
Capture C1
2026-08-28T10:00Z
raw hash A
        │
        ├──────► Reference R1
        │
Capture C2
2026-08-28T11:00Z
raw hash B
        │
        └──────► Reference R1
```

必须同时保存 C1 和 C2。

不能因为 R1 已存在就丢弃 C2。

---

## 3.2 Raw Identity != Capture Identity != Semantic Identity

至少明确区分：

```text
Raw Response Identity
Capture Identity
Semantic Reference Identity
Reference Authority Identity
Market Product Composition Identity
```

### Raw response identity

`SHA256(exact response bytes)`

### Capture identity

表示：

> 在哪个 provider/environment、通过哪个 endpoint/request、什么时候捕获到哪些 exact raw bytes、使用哪个 capture/parser contract。

### Semantic Reference identity

表示：

> OnlyAlpha 对 Binance Spot 市场经济/交易规则的 canonical 解释。

### Reference Authority identity

表示：

> 一组 exact semantic references + exchange-level semantic rules 的唯一组合。

### Market Product Composition identity

继续由现有：

```text
Reference Authority
Policy Compiler
Fee Pack
effective economic config
```

组合产生。

---

## 3.3 Provenance 不得污染 Economic Identity

以下字段属于 Capture provenance：

```text
environment
endpoint
request parameters
captured_at
serverTime
HTTP headers
request latency
raw byte ordering
parser/capture version
```

普通 provenance 不得因为变化就导致 economic Reference fingerprint 变化。

例如：

```text
LIVE capture
TESTNET capture
```

如果 canonical economic semantics 完全相同：

```text
semantic reference fingerprint
可以相同
```

但：

```text
capture fingerprint
必须不同
```

---

## 3.4 Semantic Reference 必须是独立 immutable artifact

禁止继续依赖：

```text
load raw bytes
→ 用当前 normalizer 重新解释
→ 得到“历史 Reference”
```

正确：

```text
Capture Raw Evidence
        ↓
Normalizer version N
        ↓
Canonical Semantic Artifact R1
        ↓
immutable publication
```

以后加载 R1：

```text
load canonical semantic artifact
→ verify fingerprint
→ reconstruct typed Reference
```

raw evidence仍需验证和保留，但不能成为“每次加载时重新决定历史语义”的入口。

---

## 3.5 One immutable Binding does not hot-mutate

当前设计继续保持：

```text
Binding A
→ exact Reference Authority A
```

发现新规则：

```text
Capture
→ Reference Authority B
```

不能：

```text
Binding A.reference_authority = B
```

本任务不实现 runtime hot-rebind。

---

# 4. 冻结范围

只修 P9.1 correctness。

## 本任务允许

```text
Binance Spot public Reference
Capture / semantic storage
Market-neutral Core contract 的最小必要扩展
Market Product Compiler
Market Rule Engine 对新 canonical legality policy 的最小消费
deterministic tests
public contract tests
architecture gates
CI closure
P9.1 project-state transition
```

## 明确禁止扩展

```text
Binance Historical Kline
Binance realtime WebSocket
Trade stream
bookTicker
Depth
ClickHouse
production market PostgreSQL schema
WAL
private API
API key
signing
account
balance
Broker
submit/cancel order
User Data Stream
reconciliation
LIVE Runtime
Futures
QMT
CTP
CCXT
Binance SDK
NautilusTrader runtime dependency
Freqtrade runtime dependency
Kafka
Redis
Kubernetes
```

---

# 5. C1 — Capture / Semantic Revision Identity Separation

## 5.1 新的 conceptual model

实现时遵守仓库命名规范，类名可微调，但语义必须存在。

建议：

```text
OnlyBinanceSpotRawEvidence
OnlyBinanceSpotCaptureProvenance
OnlyBinanceSpotReferenceCapture
OnlyBinanceSpotReferenceAuthority
OnlyBinanceSpotReferencePublication
```

每个 endpoint 一份 raw evidence：

```text
endpoint_id
request_parameters
raw_bytes
raw_sha256
```

不要为了抽象而建立通用 HTTP framework。

---

## 5.2 Capture provenance

至少：

```text
schema_version
provider = BINANCE
product = SPOT
environment = LIVE | SPOT_TESTNET
captured_at_utc
parser_contract_version
requested_symbols
source endpoints
canonical request parameters
raw fingerprints
```

如果一个 Capture 同时包含：

```text
exchangeInfo
executionRules
```

capture identity 必须绑定这两个 evidence。

---

## 5.3 Capture fingerprint

必须使用 OnlyAlpha 现有 canonical identity primitive：

```text
only_identity_fingerprint(...)
```

概念：

```text
capture_fingerprint =
fingerprint(
    capture_schema_version,
    provider,
    product,
    environment,
    captured_at_utc,
    parser_contract_version,
    canonical requested symbols,
    canonical endpoint/request descriptions,
    exact raw SHA256s
)
```

要求：

```text
same capture object replay
→ same capture fingerprint

different captured_at
→ different capture fingerprint

different environment
→ different capture fingerprint

different exact raw bytes
→ different capture fingerprint
```

---

# 6. C2 — Immutable Store 重构

当前 store 同一个 semantic-authority-fingerprint 同时承担 raw evidence 和 semantic reference。

必须拆开。

建议 layout：

```text
root/
├── captures/
│   └── <capture_fingerprint>/
│       ├── manifest.json
│       ├── exchangeInfo.json
│       └── executionRules.json
│
└── references/
    └── <authority_fingerprint>/
        ├── manifest.json
        └── reference.json
```

如果每 instrument 单独 semantic artifact 更符合当前代码，可使用：

```text
references/<instrument-reference-fingerprint>/
authorities/<authority-fingerprint>/
```

但不要为了“更规范”引入不必要层次。

最小可接受方案：

```text
captures/<capture_fp>
references/<authority_fp>
```

### Capture publication

```text
same capture fingerprint + same bytes/provenance
→ idempotent reuse

same capture fingerprint + different content
→ deterministic conflict

corrupt capture manifest/raw
→ fail closed
```

### Semantic publication

```text
same authority fingerprint + same canonical semantic bytes
→ idempotent reuse

same authority fingerprint + different semantic bytes
→ deterministic conflict

corrupt semantic bytes
→ fail closed
```

### 多 Capture 指向同一 Reference

必须实现并测试：

```text
C1 → R1
C2 → R1
```

其中：

```text
C1 != C2
R1 only published once
both captures retained
```

Publication result 建议明确：

```text
capture_fingerprint
semantic_reference_fingerprint
capture_created
reference_created
compatibility_status
symbols
captured_at
```

不要继续只有一个模糊的 `created: bool`。

---

# 7. C3 — Canonical Semantic Artifact

为：

```text
OnlyBinanceSpotReference
OnlyBinanceSpotReferenceAuthority
OnlyBinanceSpotRule
```

建立明确的 canonical serialization/deserialization contract。

不要直接 `dataclasses.asdict()` 并假设永远兼容。

至少有：

```text
semantic_schema_version
authority identity
exchange rules
instrument references
```

所有 Decimal：

```text
serialize as canonical decimal text
```

所有集合：

```text
stable sort
```

所有时间：

```text
UTC ISO8601
```

`observed_at` 是 applicability/provenance metadata，不进入 per-reference economic content fingerprint，但可以存在于 semantic artifact 中作为 known-observation boundary。

### load_verified(reference_fingerprint)

以后必须：

```text
read reference.json
→ strict semantic schema parse
→ reconstruct typed authority
→ recalculate identity
→ compare expected fingerprint
```

而不是：

```text
read raw
→ current normalizer
→ recreate
```

raw evidence仍然有：

```text
load_capture_verified(capture_fingerprint)
```

两种加载语义必须分离。

### Parser version

Capture manifest 保存：

```text
parser_contract_version
```

目的：

```text
解释“哪个版本 parser 从 raw 形成了这个 semantic artifact”
```

不要让 parser version 自动成为 economic identity。

如果未来 parser 修复改变语义：

```text
old semantic artifact remains R1
new processing produces R2
```

不得 rewrite R1。

---

# 8. C4 — Exchange-Level Rule Authority

当前 symbol filters 已经分类。

现在补：

```text
exchangeFilters
```

exchange-level rule 属于：

```text
OnlyBinanceSpotReferenceAuthority
```

不是复制到每一个 symbol reference。

建议：

```text
OnlyBinanceSpotReferenceAuthority:
    exchange_rules
    references
    identity
```

Authority fingerprint：

```text
fingerprint(
    canonical exchange rules,
    sorted instrument semantic fingerprints
)
```

对于 exchange-level discriminator：

```text
filterType / ruleType
```

如果未知且可能影响交易：

```text
capture 保存
semantic authority = INCOMPATIBLE
trade-eligible composition = fail closed
```

不能 silently ignore。

即使当前 Binance 官方 `exchangeFilters` 为空，也必须：

```text
parser knows the field exists
tests cover non-empty known/unknown fixture
```

---

# 9. C5 — Market-Legality Canonical IR

这是本任务允许修改 Core 的主要原因。

原则：

> **只新增 Binance Spot 真正需要、且 market-neutral 的最小语义。**

禁止：

```text
OnlyBinanceNotionalPolicy
OnlyBinanceMarketLotPolicy
BinanceDynamicPriceRule
```

进入 Core。

---

# 10. Notional Policy

新增 market-neutral model，概念：

```text
OnlyCompiledNotionalPolicy
```

至少能表达：

```text
minimum_notional
maximum_notional
minimum_applies_to_market
maximum_applies_to_market
market_reference_window_minutes
```

字段可按现有风格调整。

需要覆盖 Binance：

```text
MIN_NOTIONAL
NOTIONAL
```

注意这两个 filter 的字段不完全一样。

Normalizer 不应只取：

```text
filters["NOTIONAL"] or filters["MIN_NOTIONAL"]
```

然后丢掉潜在差异。

正确：

```text
parse exact provider fields
→ normalize to one unambiguous canonical notional policy
```

如果两个 filter 同时出现且语义冲突：

```text
fail closed / explicit conflict
```

不要随意优先某一个。

### Runtime enforcement

当前 Runtime 已经计算：

```text
notional = price × quantity × contract_multiplier
```

对于 first vertical 当前真正执行的 LIMIT order：

```text
minimum notional
maximum notional
```

应成为正式 evaluation：

```text
NOTIONAL_MINIMUM
NOTIONAL_MAXIMUM
```

不要为了这项提前实现完整 MARKET execution。

---

# 11. Order-Type-Specific Quantity Policy

当前：

```text
LOT_SIZE
MARKET_LOT_SIZE
```

必须保持不同 authority。

允许两种最小实现方案，优先选择对现有代码改动更小且语义更清晰的一种。

## 方案 A

扩展现有：

```text
OnlyCompiledQuantityPolicy
```

增加可选：

```text
market_minimum_quantity
market_quantity_increment
market_maximum_quantity
```

默认 `None`，现有 A-share / Generic T0 不受影响。

## 方案 B

新增 market-neutral：

```text
OnlyCompiledOrderQuantityPolicy
```

包含 limit / market constraint。

但不要和现有 `OnlyCompiledQuantityPolicy` 形成两个都声称是 LIMIT quantity authority 的模型。

**优先最小改动；不要为未来所有 order type 建规则 DSL。**

---

# 12. Dynamic Price Rule Declaration

P9.1 不要求 realtime 求值：

```text
PERCENT_PRICE
PERCENT_PRICE_BY_SIDE
PRICE_RANGE
```

但不能只藏在 Binance-specific `rules` tuple 中。

需要建立 market-neutral compiled requirement。

目标：

```text
Market Product Compiler
明确告诉 Core：
这个 market composition 存在 dynamic price validation requirement
```

建议建立小型 model，例如概念：

```text
OnlyCompiledDynamicPriceRequirement
```

能表达：

```text
rule identity
side-specific / symmetric
reference/lookback semantics
canonical multipliers or bounds
evaluation authority requirement
```

具体字段必须依据当前 Binance 官方文档证明。

**不要猜测 Provider 语义。**

如果某 Binance rule 无法准确映射：

```text
Reference 保留 typed provider semantic
Compiler 标记 unsupported-required dynamic rule
Trade eligibility fail closed for order paths that require it
```

不要伪装成 static lower_limit / upper_limit。

---

# 13. OnlyCompiledMarketPolicy 扩展规则

如果新增：

```text
notional_policy
dynamic_price_requirements
```

必须：

1. 进入 `OnlyCompiledMarketPolicy`；
2. 进入 `policy_payload()`；
3. 进入 `policy_fingerprint`；
4. checkpoint/recovery fingerprint verification 继续成立；
5. Generic T0 / CN A-share 的 default/None semantics 明确；
6. 所有调用构造点被更新；
7. 不引入 provider-specific type。

不能出现：

```text
对象有字段
但 policy_fingerprint 不包含
```

---

# 14. C6 — Temporal Applicability / As-Of

当前 Binance Reference：

```text
resolve(instrument_id, trading_day)
```

只能 day-level。

而一份 snapshot 有 exact：

```text
observed_at
```

P9.1 closure 要补最小 market-neutral as-of query。

## 14.1 设计目标

对于：

```text
Reference R1 observed_at = 2026-08-28T10:00Z
```

必须：

```text
as_of 09:59Z
→ HISTORICAL_REFERENCE_UNPROVEN

as_of 10:00Z / later
→ R1
```

`observed_at` 不是自动声称 provider `effective_from`。

语义只是：

> OnlyAlpha 从这个时间点开始有证据证明该 reference 被观察到。

不要 back-project 到更早。

---

## 14.2 最小 Core contract 扩展

优先考虑在现有：

```text
OnlyMarketPolicyCompilationRequest
```

增加：

```text
as_of: datetime | None
```

并让：

```text
OnlyMarketReferenceAuthority.resolve(...)
```

支持可选 as-of。

具体 API 以当前源码风格为准。

要求：

- timezone-aware；
- canonical UTC；
- day-based market 可以保持已有 trading-day semantics；
- Generic T0 / CN A-share 不应被强迫做无意义 intraday revision；
- Binance 在需要证明 exact applicability 时必须使用 as_of。

---

## 14.3 Runtime cache correctness

当前 `OnlyMarketRuleEngine` 按：

```text
(instrument_id, trading_day)
```

缓存 compiled policy。

加入 as_of 后，绝不能出现：

```text
11:00 首先 cache R1
然后 09:00 query
因为 day cache 已存在而错误复用 R1
```

必须修复 cache identity。

推荐：

```text
compile/resolve exact reference
→ cache by
(instrument_id, trading_day, reference_fingerprint)
```

或者等价、确定且不会产生每-order timestamp cache cardinality 的方案。

不要直接：

```text
cache key = exact timestamp
```

Binding 内仍然只有 exact immutable authority，不实现 hot mutation。

---

# 15. C7 — Permission / Capability Boundary

必须正式区分：

```text
Venue Capability
Market Product Supported Capability
Account Eligibility
```

P9.1 没有 private account。

不能由 public `permissionSets` 宣称：

```text
this account can trade
```

Reference 层至少考虑：

```text
compatibility_status
provider_status
isSpotTradingAllowed
required public venue rules understood
```

`permissionSets`：

- 精确保留 provider 结构；
- 依据 Binance 当前官方语义建立显式 helper；
- 不把 account permission 假装已经满足；
- 不 flatten AND/OR semantics。

真正账户是否满足：

```text
P9.4 Broker private authority
```

继续保持：

```text
Venue supports OCO
!=
OnlyAlpha Broker supports OCO
```

---

# 16. C8 — Bounded HTTP Acquisition

当前 public HTTP 使用：

```python
response.read()
```

改为明确 bounded read。

配置/常量：

```text
max_response_bytes
```

要求：

```text
Content-Length known and > limit
→ reject

Content-Length absent/incorrect
→ read at most max + 1
→ if exceeded reject
```

错误码保持稳定，例如：

```text
BINANCE_PUBLIC_RESPONSE_TOO_LARGE
```

同时验证 response 是 JSON-compatible。

Media-Type 校验要现实，不要因：

```text
application/json; charset=utf-8
```

误拒绝。

不增加无限 retry。

---

# 17. Store API 建议

最终至少有清晰的：

```text
publish(capture)

load_capture_verified(capture_fingerprint)
load_reference_verified(authority_fingerprint)
```

不要引入：

```text
get_latest()
```

作为 Trading authority。

如果提供 operator list/index：

```text
只能是 catalog/query
不能成为 exact composition fallback
```

---

# 18. Reference Resource 接入

Market Product Factory 当前正确要求：

```text
reference_resource_id
expected_reference_fingerprint
```

保持。

Closure 后 exact resource 应指向：

```text
semantic Reference Authority artifact
```

而不是 raw Capture directory。

Factory：

```text
不访问网络
不选择 latest
不根据当前时间自动切换 snapshot
```

继续保持。

---

# 19. 预期代码范围

预期主要修改：

```text
packages/provider/onlyalpha-plugin-binance/src/onlyalpha_plugin_binance/
    common/http.py
    config.py
    spot/reference/capture.py
    spot/reference/dto.py
    spot/reference/normalize.py
    spot/reference/store.py
    + provenance/serialization helper where justified

packages/market/onlyalpha-market-binance-spot/src/onlyalpha_market_binance_spot/
    reference.py
    compiler.py
    capability.py (only if required)

src/onlyalpha/market/models.py
src/onlyalpha/market/product/ports.py
src/onlyalpha/market/runtime_rules.py
src/onlyalpha/plugin/api.py
```

以及对应 tests。

如果能通过更小改动完成，不要为了匹配目录列表强行创建文件。

---

# 20. 禁止的 Core 设计

不得新增：

```text
if venue == BINANCE
if market_product == BINANCE_SPOT
```

到 Core。

不得新增：

```text
OnlyBinanceNotionalPolicy
BinancePriceRangePolicy
BinanceMarketLotRule
```

到 Core。

Core 只能看到：

```text
market-neutral economic/legality semantics
```

---

# 21. C9 — Deterministic Test Matrix

必须补足以下 tests。

## T1 Different captured_at

```text
same raw semantic
different captured_at
→ capture fingerprint differs
→ reference fingerprint same
```

## T2 Different environment

```text
LIVE / TESTNET
same semantic
→ capture fingerprint differs
→ semantic fingerprint may remain same
```

## T3 JSON ordering/serverTime

```text
different exact bytes
→ raw hash differs
→ semantic reference same
```

## T4 Economic changes

至少：

```text
tick
step
min notional
max notional
status
dynamic multiplier
permission/capability semantic
exchange rule
```

任一 relevant semantic change：

```text
reference/authority fingerprint changes
```

---

# 22. Store Tests

## T5 Multiple captures / one semantic revision

```text
C1 → R1
C2 → R1

assert:
C1 exists
C2 exists
R1 exists once
```

## T6 duplicate capture

```text
publish exact C1 twice
→ idempotent
```

## T7 capture corruption

```text
modify raw bytes
→ load_capture_verified fails
```

## T8 semantic corruption

```text
modify reference.json
→ load_reference_verified fails
```

## T9 claimed fingerprint conflict

```text
same claimed semantic fingerprint
different canonical semantic bytes
→ deterministic conflict
```

## T10 parser independence

必须证明：

```text
load_reference_verified()
```

不通过 current normalizer 重新决定历史 semantics。

可以通过行为测试/monkeypatch/fixture 证明，不要用脆弱源码字符串断言代替。

---

# 23. Exchange Rule Tests

## T11 unknown exchange filter

```text
unknown exchange filter
→ authority incompatible / trade-ineligible
```

## T12 known empty exchange filters

```text
[]
→ valid
```

## T13 exchange rule semantic change

```text
exchange rule values change
→ authority fingerprint changes
```

---

# 24. Market-Legality Tests

## T14 LIMIT notional minimum

```text
price * qty < minNotional
→ FAILED
```

## T15 LIMIT notional maximum

when present:

```text
price * qty > maxNotional
→ FAILED
```

## T16 valid notional

```text
within range
→ passes notional evaluations
```

## T17 MARKET_LOT_SIZE does not overwrite LOT_SIZE

```text
limit constraint
!=
market constraint
```

## T18 Dynamic requirement is compiled

```text
PERCENT_PRICE / PRICE_RANGE exists
→ compiled policy carries explicit dynamic requirement
```

不得伪装成 static price band。

---

# 25. Temporal Tests

## T19 before observation

```text
observed_at = 10:00
as_of = 09:59
→ unproven
```

## T20 at observation

```text
as_of = 10:00
→ allowed
```

## T21 same day after observation

```text
as_of = 11:00
→ allowed
```

## T22 cache cannot bypass as-of validation

```text
first evaluate 11:00
then evaluate 09:00
→ second must still fail unproven
```

---

# 26. Architecture Tests

继续证明：

```text
onlyalpha core
does NOT import
onlyalpha_plugin_binance
onlyalpha_market_binance_spot
```

同时：

```text
Binance DTO
不出现在 Core public API
```

新增 market-neutral Core types 可以由 plugin API export。

---

# 27. Public Binance Contract Test

保留已有：

```text
ping
time
exchangeInfo(BTCUSDT, ETHUSDT)
executionRules(BTCUSDT, ETHUSDT)
```

本次补：

```text
current payload can pass new exchange rule / semantic normalization contract
```

不需要 API Key。

继续放：

```text
external
requires_network
requires_binance_public
```

不要成为每次快速 unit test 的强依赖。

---

# 28. CI / Verification

先运行最窄受影响 gates。

建议顺序：

```text
1. Binance provider tests
2. Binance Market Product tests
3. Market Product contract / architecture tests
4. runtime_rules affected tests
5. ruff / format
6. mypy affected packages + Core
7. package builds
8. scripts/verify.py impact plan
```

然后按 impact planner 要求运行/等待必须的 broad CI。

当前已知历史事实：

```text
P9.1 implementation local tests passed
Layered Quality 曾出现 research-postgres coverage < 82%
```

任务开始时重新确认当前 CI，不要假设该 failure 仍存在。

如果仍存在：

```text
行为测试 PASS
coverage gate FAIL
```

则：

- 找真实 coverage delta；
- 增加有意义测试；
- 不降低 threshold；
- 不通过无依据 omit/exclude 逃避。

---

# 29. 不允许为了 CI 通过做的事

禁止：

```text
coverage threshold 82 → 更低
删除 architecture gate
skip P9.1 tests
unknown critical rule → ignore
fail-closed → default allow
大面积 pragma:no-cover
```

---

# 30. P9.1 Closure Report

优先更新：

```text
docs/reports/p9_1_binance_spot_market_product_reference_authority.md
```

让它从：

```text
IMPLEMENTED; targeted/local evidence PASS; broad impact proof CI REQUIRED
```

进入真实 final state。

报告至少包含：

```text
1. final HEAD
2. Capture vs Reference identity model
3. immutable storage layout
4. provenance contract
5. semantic serialization contract
6. exchange-level rule treatment
7. canonical notional/quantity/dynamic IR
8. temporal as-of semantics
9. fail-closed rules
10. exact tests/gates run
11. CI evidence
12. remaining items explicitly deferred to P9.2/P9.4
```

不要再生成一份重复审计报告。

---

# 31. Project State Transition

只有所有 required gates 通过后：

```text
P9.1 = TASK COMPLETE / VERIFIED
```

才允许推进 project state。

使用：

```text
scripts/project_state.py
```

不要手改投影文件。

目标：

```text
last_verified_increment = "P9.1"
last_verified_name = "Crypto Market Product & Binance Reference Authority"
last_verified_state = "TASK COMPLETE / VERIFIED"

next_authorized_increment = "P9.2"
next_authorized_name = "Binance Spot Historical & Realtime DataSource"
next_authorized_state = "IMPLEMENTATION READY"
```

具体字段服从当前 project-state script contract。

不要授权 P9.3/P9.4/Futures。

---

# 32. Definition of Done

P9.1 Closure 只有同时满足以下条件才完成。

## Identity

```text
Raw hash
Capture fingerprint
Reference fingerprint
Authority fingerprint
Composition fingerprint
```

边界明确，无混用。

## Evidence

```text
different captures
→ all retained

same semantics
→ one semantic revision
```

## Replay

```text
semantic Reference
→ independently loadable/verifiable
→ not dependent on current normalizer re-interpreting raw
```

## Provenance

可以确定回答：

```text
provider
environment
endpoint/request
symbols
capture time
raw hashes
parser contract version
semantic revision
```

## Reference completeness

至少：

```text
symbol rules
execution rules
exchange-level rules
```

都在 Authority 范围内。

## Market legality

至少准确表达：

```text
PRICE_FILTER
LOT_SIZE
MARKET_LOT_SIZE
MIN_NOTIONAL / NOTIONAL
dynamic price validation requirement
status
Spot capability
order/TIF/STP/order-group venue capability
```

## Temporal correctness

```text
before observation
→ unproven

same-day after observation
→ exact observed snapshot usable
```

且 cache 不绕过 temporal validation。

## Fail Closed

以下均拒绝继续假装确定：

```text
unknown critical symbol rule
unknown critical exchange rule
corrupt raw evidence
corrupt semantic artifact
fingerprint mismatch
reference missing
historical applicability unproven
semantic conflict
```

## Architecture

```text
Core remains Binance-neutral
```

## Scope

没有提前实现：

```text
P9.2 DataSource
P9.3 database/WAL
P9.4 Broker/private API
```

## Verification

```text
required local gates PASS
required CI PASS
project-state transitioned through official script
```

---

# 33. 执行方式

不要先输出长篇审计报告。

按以下模式执行：

```text
1. bounded truth check
2. identify which listed blockers still exist
3. implement C1-C8
4. add regression tests immediately with each fix
5. run narrow gates
6. fix concrete failures
7. run required impact plan / CI
8. update closure evidence
9. transition project-state if and only if verified
10. stop
```

如果某个 blocker 已在新的 master 中正确解决：

```text
validate
→ do not redesign
```

如果发现与 P9.1 无关的问题：

```text
record one-line bounded follow-up
→ do not expand task
```

---

# 34. 最终输出格式

完成后给出：

```text
P9.1 CLOSURE RESULT
-------------------
HEAD:
VERDICT: VERIFIED / NOT VERIFIED

C1 Capture/Reference separation:
C2 Provenance:
C3 Semantic artifact replay:
C4 Exchange rule authority:
C5 Market-legality IR:
C6 Temporal as-of:
C7 Permission/capability boundary:
C8 Bounded HTTP:
C9 Determinism/CI:

Tests:
CI:
Project-state:

Remaining blockers:
- only genuine blockers

Next authorized:
- P9.2 only if VERIFIED
```

不要用“看起来完成”“基本没问题”作为结论。

---

# 35. 最终工程标准

完成后必须能够证明：

```text
Capture C1 (10:00, LIVE, raw A)
Capture C2 (11:00, LIVE, raw B)
        │
        └──────── both normalize to R1
```

系统得到：

```text
C1 retained
C2 retained
R1 stored once
```

并且：

```text
offline load R1
→ exact canonical semantic authority
→ no network
→ no current normalizer dependency
→ same authority fingerprint
→ same Market Product composition
```

如果 Binance 改变：

```text
tick / step / notional / status / relevant capability / dynamic rule / exchange rule
```

则：

```text
new semantic fingerprint
```

如果只改变：

```text
serverTime / JSON order / capture time
```

则：

```text
same semantic fingerprint
```

最终：

```text
P9.1
“What is Binance Spot BTCUSDT and under what proven rules may OnlyAlpha interpret it?”
```

必须有唯一、确定、可回放、可验证的答案。

当这个条件成立且 required CI 全绿时：

> **关闭 P9.1，不再继续横向审计，正式进入 P9.2。**
