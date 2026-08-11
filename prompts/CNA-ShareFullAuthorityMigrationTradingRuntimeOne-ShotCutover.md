# OnlyAlpha P5.3 — CN A-Share Full Authority Migration & Trading Runtime One-Shot Cutover

Repository:

`https://github.com/zongxin1993/OnlyAlpha`

当前任务属于 OnlyAlpha P5：

> **Market Product Plugin & Composition Authority**

当前执行阶段：

# P5.3 — CN A-Share Full Authority Migration & Trading Runtime One-Shot Cutover

本任务必须基于当前 `master` 最新实现执行。

当前已完成：

```text
P5.1
Core Market Product Contract
& Composition Authority

P5.2
Generic T0 Cash Market Product Plugin
& Canonical Market IR Authority Closure
```

当前已经具备：

```text
OnlyMarketProductPluginId
OnlyMarketProductIdentity
OnlyMarketProductConfig
OnlyCanonicalMarketProductConfig

OnlyMarketProductFactory
OnlyMarketProductFactoryRegistry
OnlyMarketProductResolutionContext
OnlyMarketProductResourceResolver

OnlyMarketReferenceAuthority
OnlyMarketPolicyCompiler

OnlyResolvedMarketProductBinding
OnlyMarketProductCompositionIdentity

Canonical Market IR

onlyalpha.market_products discovery

onlyalpha-market-generic-t0-cash
```

P5.3 **不得重新设计第二套 Market Product Contract**。

本任务的核心目标是：

> **把 CN A-share concrete market knowledge 全部迁移到独立 Market Product Plugin，并让生产 Trading Runtime 从 legacy MarketProfile/concrete-market composition 一次性切换到 `OnlyResolvedMarketProductBinding`。切换完成后，删除已经失去职责的旧 production Authority，不保留 compatibility adapter、fallback、alias 或 parallel path。**

---

# 一、必须先重新审计当前 master

不要机械执行本 Prompt 中的类名和路径。

首先读取当前 HEAD，并重新审计：

```text
README.md
AGENTS.md

docs/architecture.md
docs/roadmap.md

docs/adr/0068-runtime-product-taxonomy-and-trading-semantic-equivalence.md
docs/adr/0069-*
docs/adr/0070-*
```

重点读取：

```text
src/onlyalpha/config/
src/onlyalpha/runtime/
src/onlyalpha/market/
src/onlyalpha/reference/
src/onlyalpha/fee/
src/onlyalpha/settlement/
src/onlyalpha/execution/

src/onlyalpha/runtime/backtest/factory.py
src/onlyalpha/runtime/paper/factory.py
src/onlyalpha/runtime/environment.py

src/onlyalpha/market/runtime_rules.py
src/onlyalpha/market/profiles.py
src/onlyalpha/market/ashare_rules.py

src/onlyalpha/reference/ashare.py

src/onlyalpha/runtime/defaults.py
src/onlyalpha/runtime/assembler.py

packages/market/onlyalpha-market-generic-t0-cash/
```

同时检查：

```text
tests/conformance/
tests/market/
tests/market_product/
tests/architecture/
tests/recovery/
tests/runtime/
```

以当前 HEAD 的真实实现为准。

---

# 二、P5.3 必须从第一性原理理解

不要从：

```text
“把 ashare_rules.py 搬出去”
```

开始。

首先回答：

> 为什么 Trading Runtime 当前还需要知道 A-share？

当前 legacy Runtime 通常仍然自己处理：

```text
Market Profile
A-share detection
A-share Reference
Generic Reference
Market Rule Compiler
Market Fee Pack selection
```

这意味着：

> **Runtime Factory 仍然拥有 Market Product Composition Authority。**

这才是 P5.3 必须根治的问题。

最终 Runtime 应只知道：

```text
OnlyResolvedMarketProductBinding
```

不能再知道：

```text
A-share
Generic T0
ST
STAR
SSE
SZSE
Profile
A-share Reference Registry
Concrete Market Fee Pack
```

---

# 三、P5.3 的最终目标架构

最终必须形成：

```text
Market Config
      ↓
Market Product Factory Registry
      ↓
Concrete Market Product Factory
      ↓
resolve()
      ↓
OnlyResolvedMarketProductBinding
      │
      ├── Product Identity
      ├── Reference Authority
      ├── Policy Compiler
      ├── Market Fee Pack
      └── Composition Identity
      ↓
Runtime-owned Market Rule Service
      ↓
Trading Kernel
```

Backtest / Paper 当前以及未来 Sim / Live：

```text
只消费 Binding
```

不能：

```text
根据 Product ID 再次 dispatch
```

---

# 四、必须冻结依赖方向

最终依赖只能是：

```text
onlyalpha-market-cn-ashare
        ↓
OnlyAlpha Core Contract
```

禁止：

```text
OnlyAlpha Core
        ↓
onlyalpha-market-cn-ashare
```

Core 不得直接 import：

```text
onlyalpha_market_cn_ashare
onlyalpha_market_generic_t0_cash
```

Concrete Market Product 必须通过：

```text
entry point
→ discovery
→ registry
```

进入 composition。

---

# 五、P5.3 第一阶段：建立 CN A-share Market Product Plugin

新增正式 package，例如：

```text
packages/
└── market/
    └── onlyalpha-market-cn-ashare/
        ├── pyproject.toml
        ├── README.md
        ├── src/
        │   └── onlyalpha_market_cn_ashare/
        │       ├── __init__.py
        │       ├── config.py
        │       ├── reference.py
        │       ├── compiler.py
        │       ├── fee_pack.py
        │       └── factory.py
        └── tests/
```

可以根据真实职责进一步拆：

```text
price_rules.py
quantity_rules.py
sessions.py
```

但不要制造没有职责的：

```text
manager.py
service.py
runtime.py
hooks.py
utils.py
```

---

# 六、CN A-share Plugin 必须成为唯一 concrete semantic owner

A-share Plugin 应拥有：

```text
SSE / SZSE interpretation

COMMON_STOCK semantics

MAIN / STAR / CHINEXT board semantics

ST semantics

suspension interpretation

previous_close reference

price limit regime

tick / lot / quantity regime

A-share trading sessions

T+1 semantics

A-share Market Fee definition

Product Version semantics
```

Plugin 不得拥有：

```text
Order Manager
Position Manager
Account Manager
Allocation Manager
Risk Manager
Reservation Manager
Execution Processor
Transaction Coordinator
Recovery
Broker execution state
```

---

# 七、A-share Plugin 不得成为 Market Simulator

严格禁止把下面这些迁入 A-share Plugin：

```text
NEXT_BAR_OPEN

NEXT_BAR_CLOSE

BAR_TOUCH

Matching Engine

Slippage Model

Latency

Fill Plan

Fill Schedule

BAR_VOLUME_PARTICIPATION
作为模拟成交限制
```

这些已经在 P5.2 明确属于：

```text
Virtual Broker / Execution Simulation
```

A-share Market Product 只定义：

```text
市场制度
```

不定义：

```text
Backtest 如何模拟成交
```

---

# 八、迁移 A-share Reference ownership

当前 Core 中如果仍存在：

```text
OnlyAshareInstrumentReference
OnlyAshareReferenceRegistry
OnlyAshareReferenceQuery
OnlyAshareBoard
OnlyAshareExchange
OnlyAshareSecurityType
```

等 concrete A-share reference 类型：

迁入：

```text
onlyalpha-market-cn-ashare
```

不要在 Core 留：

```text
re-export
deprecated class
compatibility alias
wrapper
```

迁移后正确关系：

```text
A-share Reference
    ↓
A-share Reference Authority
    ↓
A-share Policy Compiler
    ↓
Canonical Market IR
    ↓
Core
```

---

# 九、不要重写已有成熟 Reference 算法

如果当前 A-share Reference 已具备：

```text
effective range

fingerprint validation

overlap detection

missing detection

ambiguity detection

source version

data version

exchange/board validation
```

优先迁移和收敛 ownership。

不要为了“插件化”重写一套等价但不同的 Reference Engine。

原则：

```text
move authority
not reinvent behavior
```

---

# 十、A-share Reference 对 Core 必须 opaque

Core 以后不得：

```python
reference.board
reference.st_status
reference.previous_close
```

所有 concrete A-share facts 必须由：

```text
OnlyCnAsharePolicyCompiler
```

解释。

例如：

```text
board = STAR
st_status = false
previous_close = 10.00
tick = 0.01
```

在插件内部编译为：

```text
Canonical Price Policy
Canonical Quantity Policy
Canonical Trading Status
```

Core 只消费 canonical result。

---

# 十一、不要把 A-share 字段加入 Canonical IR

禁止新增：

```text
board
st_status
exchange_type
is_star
is_chinext
```

到 Core：

```text
OnlyCompiledMarketPolicy
OnlyCompiledInstrumentMarketTerms
```

如果实现 A-share 需要 Core 知道这些字段：

说明 Compiler boundary 设计错误。

重新设计 plugin compiler，而不是扩展 Core concrete vocabulary。

---

# 十二、A-share Product Identity

正式 Provider：

```text
onlyalpha-market-cn-ashare
```

正式 Product：

```text
CN_A_SHARE_CASH
```

Product Version 应表达真实经济制度版本，例如当前已有：

```text
2025.1
2026.07
```

因此：

```text
CN_A_SHARE_CASH@2025.1
CN_A_SHARE_CASH@2026.07
```

应成为正式经济 identity。

不要再另外增加：

```text
product_version = 1
rules_version = 2025.1
```

这种重复版本 Authority，除非当前事实证明它们确实是不同维度。

---

# 十三、Product Config 不能成为 A-share Rule DSL

禁止：

```yaml
market:
  config:
    t_plus_one: true
    main_price_limit: 0.10
    st_price_limit: 0.05
    star_price_limit: 0.20
    buy_lot: 100
```

如果配置可以任意改变这些规则：

```text
CN_A_SHARE_CASH@2025.1
```

就失去意义。

原则：

```text
Product Version
→ defines market institution semantics

Reference
→ instrument/day-specific facts

Config
→ composition resources
```

---

# 十四、A-share Compiler

实现：

```text
OnlyCnAsharePolicyCompiler
```

满足：

```text
OnlyMarketPolicyCompiler
```

它应独立完成：

```text
A-share Reference
+
Product Version
+
Trading Day
    ↓
Canonical Market Policy
```

不允许：

```text
调用 legacy OnlyMarketRuleCompiler
创建 legacy OnlyMarketProfile
调用 Core A-share branch
```

旧实现可以作为迁移期 semantic oracle。

不能作为新插件 implementation dependency。

---

# 十五、A-share Price Policy

迁移当前 A-share：

```text
previous close

tick

board

ST

versioned price-limit regime

rounding
```

最终产生现有 canonical：

```text
OnlyCompiledPriceBandPolicy
```

保持经济结果完全一致。

---

# 十六、A-share Quantity Policy

迁移当前：

```text
MAIN:
minimum buy 100
increment 100

STAR:
minimum buy 200
increment 1

sell quantity
odd-lot liquidation
lot semantics
```

输出：

```text
OnlyCompiledQuantityPolicy
```

不增加 A-share-specific Core type。

---

# 十七、Trading Status

A-share：

```text
suspended
inactive
```

必须编译成 P5.2 已建立的：

```text
OnlyInstrumentTradingStatus
```

Core 不应该解释 A-share suspension model。

---

# 十八、Session Policy

迁移当前：

```text
Asia/Shanghai

opening auction
pre-open
morning continuous
midday break
afternoon continuous
closing auction
```

输出 Core canonical session model。

Session 属于 A-share Market Product。

Runtime Factory 不知道中国交易时间。

---

# 十九、Settlement

A-share Plugin 定义：

```text
T+1 economic semantics
```

但：

```text
OnlySettlementAuthority
```

继续属于 Core。

严格保持：

```text
Plugin
→ settlement policy

Core
→ settlement mutation
```

禁止：

```text
OnlyCnAshareSettlementManager
```

直接修改：

```text
Position
Account
Availability
```

---

# 二十、A-share Market Fee ownership

迁移当前 concrete A-share Market Fee definition：

```text
src/onlyalpha/fee/packs/cn_a_share/
```

到：

```text
onlyalpha-market-cn-ashare
```

Plugin 提供：

```text
OnlyMarketFeePack
```

Core 继续负责：

```text
OnlyFeeEngine
Fee Basis
Fee Accrual
Fee Ledger
Fee Application
Fee Reconciliation
```

---

# 二十一、Market Fee 与 Broker Fee 必须继续分离

不允许 A-share Plugin 接管：

```text
Broker commission
MiniQMT commission
broker account contract
```

保持：

```text
Market Product
→ Market Fee Pack

Broker
→ Broker Fee Contract
```

---

# 二十二、A-share Factory

实现：

```text
OnlyCnAshareMarketProductFactory
```

满足：

```text
OnlyMarketProductFactory
```

职责：

```text
validate provider
validate product id
validate product version

parse typed config

resolve/build Reference Authority

provide A-share Policy Compiler

provide A-share Market Fee Pack

build Composition Identity

return OnlyResolvedMarketProductBinding
```

---

# 二十三、Factory 不得持有 Runtime state

禁止：

```text
clock
event bus
order manager
position manager
account manager
risk manager
broker
transaction coordinator
```

进入 Market Product Factory。

Factory 是：

```text
composition-time authority
```

不是 Runtime participant。

---

# 二十四、Reference Resource provisioning 必须从根上做对

当前 P5.1/P5.2 已经有：

```text
OnlyMarketProductResolutionContext
OnlyMarketProductResourceResolver
```

P5.3 必须建立真正 production resource composition。

但 Core 不能：

```python
if product_id == CN_A_SHARE_CASH:
    build_ashare_reference()
```

也不能：

```python
from onlyalpha_market_cn_ashare.reference import ...
```

---

# 二十五、Reference Authority 的构造 Owner 必须还是插件

允许两种模式，根据当前实现选择更干净的一种：

## 模式 A

```text
plugin config
    ↓
plugin factory
    ↓
plugin-owned Reference Authority
```

## 模式 B

```text
neutral resource provider
    ↓
ResolutionContext
    ↓
plugin factory
    ↓
plugin-owned Reference Authority
```

无论选哪种：

```text
Core 不解释 board / ST / SSE / SZSE
```

---

# 二十六、不要建立 Universal Reference Framework

不要为了未来所有市场立即设计：

```text
UniversalMarketReferenceStore
UniversalMarketMetadataDSL
UniversalReferenceCapabilityGraph
```

只增加当前 Generic + A-share 所必需的最小 neutral composition capability。

如果现有 Resolution Context 足够：

优先复用。

---

# 二十七、第二大任务：正式 Config Market-neutralization

当前 production Config 如果仍然是：

```text
market.profile
market.fee_pack
market.version
market.overrides
```

必须迁移为：

```text
market.plugin_id
market.product_id
market.product_version
market.config
```

优先复用：

```text
OnlyMarketProductConfig
```

不要建立意义重复的新 config type。

---

# 二十八、删除旧 Profile 配置

完成 cutover 后：

```text
profile
fee_pack
version
overrides
```

不能继续作为 Trading Market configuration API。

禁止：

```text
deprecated profile
```

禁止：

```text
profile → product auto conversion
```

禁止：

```text
if new market config missing:
    parse legacy profile
```

所有 tests/examples/config fixtures 直接迁移。

---

# 二十九、Generic Config 必须移除 A-share concrete fields

如果当前：

```text
OnlyReferenceDataConfig
```

仍有：

```text
ashare_instruments
ashare_registry
reference_registry_fingerprint
```

在 cutover 后删除。

Core Generic Config 不得持有：

```text
OnlyAshareInstrumentReference
```

A-share-specific data 必须进入 plugin-owned resource/config boundary。

---

# 三十、不要保留 A-share Config Adapter

禁止：

```text
AshareReferenceDataConfigAdapter
LegacyAshareConfigBridge
ProfileMarketConfigAdapter
```

Alpha 阶段直接迁所有调用者。

---

# 三十一、第三大任务：Market Product Resolution exactly once

P5.3 必须建立一个唯一 composition point：

```text
Runtime Config
      ↓
Market Product Registry
      ↓
Factory.resolve()
      ↓
OnlyResolvedMarketProductBinding
```

一个 Runtime build：

```text
只 resolve 一次
```

---

# 三十二、禁止重复 resolve

错误：

```text
EnvironmentBuilder.resolve()

BacktestFactory.resolve()

MarketRuleEngine.resolve()
```

即使 deterministic 也不允许。

正确：

```text
Composition Authority
       ↓
resolve once
       ↓
Binding
       ├── Environment
       └── Runtime Factory
```

---

# 三十三、建议建立非常薄的 Resolved Trading Composition

如果当前架构需要，可以增加：

```python
@dataclass(frozen=True, slots=True)
class OnlyResolvedTradingComposition:
    market_product: OnlyResolvedMarketProductBinding
```

不要扩成：

```text
所有 Runtime Manager 大集合
```

P5.3 只需要解决 Market Product composition ownership。

---

# 三十四、Runtime Factory 不应该自己选择 Market Product

Backtest Factory 不应该：

```python
components.market_products.resolve(...)
```

Paper Factory 也不应该重复 resolve。

优先把：

```text
Market Product resolution
```

放到更高层：

```text
Engine / Trading composition root
```

然后 Factory 只消费已经 resolved 的 Binding。

---

# 三十五、第四大任务：Environment Identity 切换

当前如果还存在：

```text
CN_A_SHARE_REFERENCE
GENERIC_REFERENCE
profile_id
profile_version
overrides_fingerprint
market_fee_pack_id
```

等 Market Environment identity：

全部迁移。

目标：

```text
OnlyMarketEnvironmentIdentity
├── provider_plugin_id
├── product_id
├── product_version
└── composition_fingerprint
```

或者直接嵌入：

```text
OnlyMarketProductCompositionIdentity
```

如果更符合现有 identity 体系。

---

# 三十六、Environment 不得重新解释 Product

禁止：

```python
if binding.product_identity.product_id == ...
```

Environment 只接受：

```text
binding.composition_identity
```

作为 effective market evidence。

---

# 三十七、Runtime Environment 与 Market Economic Identity 分离

正式保持：

```text
Market Product Composition Identity
    independent of Runtime Type
```

而：

```text
Runtime Environment Identity
```

可以包含：

```text
BACKTEST
PAPER
future SIM
future LIVE
```

不能混淆。

---

# 三十八、Persistence / Checkpoint Identity 同步迁移

检查：

```text
OnlyRuntimePersistenceStoreCreateRequest
checkpoint metadata
recovery compatibility
artifact environment identity
```

如果仍写入：

```text
market.profile
```

必须迁移为：

```text
Market Product Identity
+
Composition Identity
```

---

# 三十九、Recovery 必须验证 effective market composition

恢复不能只判断：

```text
CN_A_SHARE_CASH
```

必须至少验证：

```text
composition fingerprint
```

因为：

```text
same product
different reference authority
```

可能产生不同经济历史。

正式原则：

```text
checkpoint market composition
==
current market composition

otherwise fail closed
```

---

# 四十、第五大任务：重构 OnlyMarketRuleEngine

不要创建：

```text
OnlyMarketProductRuleEngine
```

然后保留旧：

```text
OnlyMarketRuleEngine
```

双 Engine。

优先直接把：

```text
OnlyMarketRuleEngine
```

重构成新的正确 Authority。

---

# 四十一、新 MarketRuleEngine 只消费 Binding

目标接口概念：

```python
OnlyMarketRuleEngine(
    binding=...,
    advance_trading_day=...,
)
```

而不是：

```text
Profile Registry
Legacy Compiler
Profile Request
Runtime Mode
Concrete Reference Provider
```

---

# 四十二、MarketRuleEngine 的正确职责

它属于：

```text
Runtime operational service
```

可以拥有：

```text
compiled policy cache
runtime validation state
checkpointable operational state
```

但不能拥有：

```text
Product selection
Plugin discovery
Concrete market knowledge
Profile version resolution
Market Fee selection
```

---

# 四十三、MarketRuleEngine 不得自己 resolve Binding

错误：

```python
OnlyMarketRuleEngine(
    market_product_registry,
    config
)
```

正确：

```text
Composition Root
→ Binding

MarketRuleEngine
→ consumes Binding
```

Authority 必须唯一。

---

# 四十四、生产 Market Policy 使用 P5.2 Canonical IR

切换后生产 Runtime 应真正使用：

```text
OnlyCompiledMarketPolicy
```

而不是旧：

```text
OnlyCompiledMarketRules
```

如果旧类型已经失去 production 职责：

删除。

不要 adapter。

---

# 四十五、Runtime Mode 必须退出 Market Economic Identity

旧：

```text
OnlyCompiledMarketRuleIdentity.runtime_mode
```

在 production cutover 后应消失。

必须证明：

```text
same Binding
same Instrument
same Trading Day
same Reference

BACKTEST / PAPER / future SIM / LIVE

→ same Market Policy Identity
```

---

# 四十六、旧 match-time logic 要退出 Market Rule Authority

如果旧 Market Rule Engine 仍负责：

```text
matching
slippage
liquidity simulation
```

production cutover 后删除这些职责。

这些行为只能由：

```text
Virtual Broker
```

提供。

不要修改 Virtual Broker 的实际 matching economics，除非只是删除错误依赖。

---

# 四十七、第六大任务：Backtest one-shot cutover

Backtest Factory 最终只负责：

```text
Historical DataSource

Backtest Clock

Virtual Broker

Persistence

Finite Runtime Driver

Cluster assembly
```

市场方面只接受：

```text
resolved Market Product Binding
```

---

# 四十八、Backtest Factory 必须删除

删除：

```text
if CN_A_SHARE_CASH

A-share Reference assembly

Generic Reference assembly

MarketProfileRegistry usage

legacy Market compiler selection

Market Fee Pack Registry selection
```

---

# 四十九、第七大任务：Paper one-shot cutover

虽然 PAPER 后续 P6 删除，但 P5.3 必须同时把它的 Market Product composition 切换到 Binding。

删除 Paper Factory 中：

```text
if CN_A_SHARE_CASH

A-share Reference assembly

Generic Reference assembly

legacy profile-based rule composition
```

原因：

> P6 应只处理 PAPER → SIM streaming migration，不应该再次迁 Market Product architecture。

---

# 五十、绝对禁止半切

禁止：

```text
Generic → new Binding
A-share → legacy Profile
```

也禁止：

```text
A-share → new Binding
Generic → legacy Profile
```

Runtime 中不得出现：

```python
if product_supports_new_market_architecture:
    ...
else:
    ...
```

---

# 五十一、Cutover 前必须满足

必须先证明：

```text
Generic T0 Binding READY

CN A-share Binding READY
```

然后一次性：

```text
Runtime Profile path
        ↓
REMOVE

Runtime Binding path
        ↓
ONLY
```

---

# 五十二、Experimental Generic Futures/Crypto 不得阻止 cutover

当前如仍有：

```text
GENERIC_MARGIN_FUTURES
GENERIC_24X7_CRYPTO_SPOT
```

legacy experimental Profile：

不能成为保留 production Profile architecture 的理由。

如果它们没有正式产品职责：

```text
删除 production spelling
或降为 test-only fixture
```

后续正式支持时通过：

```text
Market Product Plugin
```

重新实现。

禁止：

```text
unknown / futures / crypto
→ legacy profile fallback
```

---

# 五十三、第八大任务：Market Fee production selection 删除

切换后 Runtime 直接：

```text
binding.market_fee_pack
```

不能：

```text
config.market.fee_pack
→ components.market_fee_packs.require(...)
```

继续选择 concrete market fee。

---

# 五十四、重新审计 MarketFeePackRegistry

如果 Generic + A-share concrete Fee 都已由插件拥有，production Market Product composition 不再需要：

```text
OnlyMarketFeePackRegistry
```

则删除其 production ownership。

如果仍有其它真实独立用途：

只保留真正用途。

不要为了旧实验 Profile 保留错误架构。

---

# 五十五、第九大任务：删除失去职责的旧接口

P5.3 cutover 后已经没有 Authority 的接口：

**必须在 P5.3 删除。**

不要推到 P5.4。

至少重新审计并删除适用的：

```text
src/onlyalpha/reference/ashare.py

src/onlyalpha/market/ashare_rules.py

legacy Generic compiler helpers

legacy Runtime A-share branch

legacy Runtime Generic branch

OnlyReferenceDataConfig.ashare_instruments

ashare_registry

reference_registry_fingerprint

profile-based Runtime market config

Environment concrete reference branch

Runtime concrete Market Fee selection
```

---

# 五十六、Profile Framework 的最终处理

重新搜索：

```text
OnlyMarketProfile
OnlyMarketProfileRegistry
OnlyMarketProfileRequest
OnlyResolvedMarketProfile
```

如果 cutover 后已经没有正式 production Authority：

> **直接删除。**

不要因为：

```text
旧 tests
旧 examples
旧 docs
```

继续保留。

修改测试和示例。

---

# 五十七、禁止 Compatibility Layer

整个 P5.3 禁止新增：

```text
ProfileToMarketProductAdapter

LegacyMarketProfileBinding

AshareReferenceAdapter

GenericMarketFallback

DeprecatedMarketProfileConfig

market_product_from_profile()

legacy_profile property

old market config alias
```

迁移调用者。

删除旧 API。

---

# 五十八、不要保持“两套正确答案”

最终每个 Domain 只能一个 Authority：

```text
Market Product Factory Registry
→ factory lookup authority

Market Product Plugin
→ concrete market semantic authority

Binding
→ resolved composition authority

Market Rule Engine
→ runtime market policy operational authority

Fee Engine
→ fee application authority

Settlement Authority
→ settlement mutation authority
```

不能再有：

```text
Profile Registry
+
Product Registry
```

同时决定 production market semantics。

---

# 五十九、A-share Legacy vs Plugin Conformance

在删除 legacy implementation 前，必须建立对照测试。

相同：

```text
Instrument
Trading Day
Reference
Product Version
```

比较：

```text
Session

Price Policy

Quantity Policy

Trading Status

Position Mode

Short Policy

Settlement Policy

Margin Policy

Instrument Terms

Market Fee
```

---

# 六十、A-share price conformance

必须覆盖至少：

```text
SSE Main normal

SSE Main ST

SZSE Main normal

SZSE Main ST

ChiNext

STAR

2025.1

2026.07
```

验证：

```text
tick
previous close
price limit rate
lower
upper
rounding
```

经济结果一致。

---

# 六十一、A-share quantity conformance

至少验证：

```text
Main minimum buy

Main buy increment

STAR minimum 200

STAR increment 1

sell increment

odd-lot liquidation semantics
```

保持当前 certified economics。

---

# 六十二、Reference conformance

比较经济 facts：

```text
instrument

exchange compatibility

security type

board

lot

tick

ST

suspension

previous close

effective range

source/version

fingerprint determinism
```

但最终 Core 不再看到 concrete DTO。

---

# 六十三、Fee conformance

相同：

```text
Trade basis

side

notional

date
```

旧 A-share Market Fee 与新 Plugin Market Fee：

```text
same fee items
same rates
same rounding
same total
```

---

# 六十四、Certified A-share V1 必须作为黑盒 Oracle

当前：

```text
CN_A_SHARE_DURABLE_BACKTEST_V1
```

必须继续作为 P5.3 最强 regression gate。

原则：

```text
Architecture changes significantly

Trading economics change = ZERO
```

---

# 六十五、A-share certified output 必须保持

相同：

```text
fixtures
strategy
bars
broker facts
```

必须得到相同：

```text
Orders

Accepted lifecycle

Trades

Position

Allocation

Account

Strategy Ledger

Fees

Settlement

Transactions

PnL

Recovery result
```

---

# 六十六、Generic T0 production cutover 同样要验证

P5.2 虽然已经做 Plugin semantic conformance，但 P5.3 是 production Runtime 真正切换。

必须验证：

```text
Legacy Generic Runtime economics
==
Binding-based Generic Runtime economics
```

尤其：

```text
Price
Quantity
Settlement
Fee
Position
Transaction
Recovery
```

---

# 六十七、允许 structural identity 变化

由于：

```text
MarketProfile identity
```

被：

```text
Market Product Composition Identity
```

替换：

某些：

```text
environment fingerprint
checkpoint metadata
artifact identity
```

可能合理变化。

必须明确测试：

```text
Structural identity migration
!=
Economic result change
```

---

# 六十八、Recovery 必须重点验证

至少验证：

```text
Memory

SQLite

Checkpoint

Restart

Forward Recovery

A → B → C recovery

same market composition restore

different market composition reject
```

---

# 六十九、Recovery mismatch 必须 Fail Closed

例如：

```text
checkpoint:
CN_A_SHARE_CASH@2025.1
reference fingerprint A

restart:
CN_A_SHARE_CASH@2025.1
reference fingerprint B
```

必须：

```text
FAIL
```

不能只看到：

```text
product id 一样
```

就恢复。

---

# 七十、Architecture Guards

P5.3 必须强化静态架构门禁。

## Core concrete plugin imports

搜索：

```text
onlyalpha_market_cn_ashare
onlyalpha_market_generic_t0_cash
```

在：

```text
src/onlyalpha/
```

不得出现 concrete import。

---

# 七十一、A-share vocabulary leakage

重点检查：

```text
src/onlyalpha/config/
src/onlyalpha/runtime/
src/onlyalpha/market/product/
src/onlyalpha/execution/
src/onlyalpha/transaction/
src/onlyalpha/position/
src/onlyalpha/account/
```

禁止 active behavioral usage：

```text
OnlyAshare
ashare_rules
ST
STAR
CHINEXT
XSHG
XSHE
CN_A_SHARE_CASH
```

Product ID 作为：

```text
evidence/test identity
```

可有非常有限例外。

Behavioral branch 必须为 0。

---

# 七十二、Product ID non-dispatch guard

必须禁止 Core：

```python
if product_id == ...
```

或者：

```python
match product_id:
```

来决定市场行为。

Product ID 只能用于：

```text
logging
audit
artifact
identity
```

---

# 七十三、Runtime mode guard

Market Product：

```text
Factory
Compiler
Reference
Binding
Composition Identity
Canonical Policy
```

都不能依赖：

```text
OnlyRuntimeMode
BACKTEST
PAPER
SIM
LIVE
```

---

# 七十四、Plugin mutable authority guard

A-share Plugin 不得 import：

```text
OrderManager
PositionManager
AccountManager
RiskManager
ExecutionProcessor
TransactionCoordinator
Runtime
```

---

# 七十五、Simulation leakage guard

A-share Market Product 中禁止：

```text
Matching
Slippage
Latency
Fill Plan
BAR_VOLUME_PARTICIPATION
```

作为 Market Product semantics。

---

# 七十六、P5.3 不实现 P6/P7/P8

禁止顺手实现：

```text
SIM

PAPER deletion

SHADOW deletion

Research vectorization

Live Broker submission

Durable outbound command

Broker reconciliation

Live Runtime
```

PAPER 当前只做 Market Product composition 中立化。

P6 再正式迁移并删除。

---

# 七十七、P5.3 不处理中立化所有 Runtime Mode

只处理：

```text
Market Product / Market Rule economic identity
```

相关 Runtime Mode leakage。

其它：

```text
Position LIVE authority

Fee provisional LIVE branch
```

如果属于 Broker evidence/reconciliation：

留给 P8。

---

# 七十八、P5.3 不修改 Trading Kernel economics

原则上不要修改：

```text
Execution Processor

Transaction Planner

Transaction Coordinator

Position economics

Allocation economics

Account economics

Strategy Ledger economics

Risk reservation lifecycle

Virtual Broker matching behavior
```

---

# 七十九、如果需要修改这些说明边界走错

如果实现中发现必须修改：

```text
PnL

Trade application

Position cost

Reservation

Durable commit

Recovery algorithm
```

才能完成 Market Product migration：

停止并重新审计设计。

P5.3 是 composition migration，不是 Durable Kernel rewrite。

---

# 八十、推荐实现顺序

严格建议：

```text
Phase 1
Audit current production Market ownership

Phase 2
Create onlyalpha-market-cn-ashare

Phase 3
Move A-share Reference ownership

Phase 4
Implement A-share Policy Compiler

Phase 5
Move A-share Market Fee ownership

Phase 6
Implement A-share Factory + Binding

Phase 7
A-share semantic conformance

Phase 8
Market-neutral Config migration

Phase 9
Production Reference Resource composition

Phase 10
Resolve Market Product exactly once

Phase 11
Environment / Persistence identity migration

Phase 12
Refactor OnlyMarketRuleEngine

Phase 13
Generic + A-share both ready

Phase 14
Backtest atomic cutover

Phase 15
Paper atomic cutover

Phase 16
Delete legacy production composition

Phase 17
Static guards + full regression

Phase 18
Documentation + P5.3 report
```

不要在 Generic/A-share bindings 尚未 ready 时先切 Runtime。

---

# 八十一、P5.3 Definition of Done

只有全部满足才算完成。

## CN A-share Plugin

```text
[ ] 独立 package

[ ] plugin-owned typed config

[ ] plugin-owned Reference

[ ] plugin-owned Reference Authority

[ ] plugin-owned Policy Compiler

[ ] plugin-owned Market Fee Pack

[ ] plugin-owned Factory

[ ] 返回 OnlyResolvedMarketProductBinding
```

---

## Config neutrality

```text
[ ] Runtime Market Config 使用 Market Product envelope

[ ] Generic Config 无 A-share concrete type

[ ] ashare_instruments 删除

[ ] ashare_registry 删除

[ ] reference_registry_fingerprint concrete API 删除

[ ] profile-based market config 删除
```

---

## Runtime Composition

```text
[ ] Market Product resolve exactly once

[ ] Backtest 不 resolve concrete market

[ ] Paper 不 resolve concrete market

[ ] Runtime Factory 只消费 Binding

[ ] 无 Generic/A-share branch

[ ] 无 implicit fallback
```

---

## Market Rule Engine

```text
[ ] 只消费 Binding

[ ] 不消费 Profile Registry

[ ] 不消费 legacy Profile Request

[ ] 不含 Runtime Mode economic identity

[ ] 不负责 matching/slippage/simulation liquidity

[ ] production 使用 Canonical Market IR
```

---

## Environment / Persistence

```text
[ ] Environment 使用 Market Product Composition Identity

[ ] 不再使用 CN_A_SHARE_REFERENCE / GENERIC_REFERENCE branch

[ ] Persistence 保存 effective Market composition evidence

[ ] Recovery 检查 composition compatibility
```

---

## Fee

```text
[ ] Generic Market Fee 由 Generic Plugin owned

[ ] A-share Market Fee 由 A-share Plugin owned

[ ] Runtime 不再通过 concrete Fee Registry 选择 Market Fee

[ ] Broker Fee 仍独立

[ ] Fee Engine 仍属于 Core
```

---

## Cleanup

```text
[ ] Core A-share Reference implementation 删除

[ ] Core A-share Rules implementation 删除

[ ] legacy Generic compiler production branch 删除

[ ] legacy A-share compiler production branch 删除

[ ] Runtime concrete market branches 删除

[ ] Profile production composition 删除

[ ] 无 compatibility adapter

[ ] 无 alias

[ ] 无 deprecated market API

[ ] 无 fallback
```

---

## Architecture

```text
[ ] Core 不 import concrete Market Product packages

[ ] Product ID 不是 behavior selector

[ ] Runtime Type 不属于 market economic contract

[ ] Market Product 不拥有 mutable Trading Authority

[ ] Market Product 与 Broker/DataSource/Risk/Execution Support 正交
```

---

## Regression

```text
[ ] Generic production semantics PASS

[ ] A-share semantic conformance PASS

[ ] CN_A_SHARE_DURABLE_BACKTEST_V1 PASS

[ ] Memory PASS

[ ] SQLite PASS

[ ] Checkpoint PASS

[ ] Restart PASS

[ ] Forward Recovery PASS

[ ] Determinism PASS

[ ] static PASS

[ ] build PASS
```

---

# 八十二、必须执行的静态搜索

完成后至少执行：

```bash
rg -n 'OnlyAshare|ashare_rules' src/onlyalpha
```

目标：

```text
active Core implementation = 0
```

执行：

```bash
rg -n 'CN_A_SHARE_CASH' src/onlyalpha
```

逐个检查。

允许：

```text
opaque identity
audit metadata
tests
```

禁止：

```text
behavioral branch
```

执行：

```bash
rg -n 'onlyalpha_market_cn_ashare|onlyalpha_market_generic_t0_cash' src/onlyalpha
```

目标：

```text
concrete import = 0
```

执行：

```bash
rg -n 'OnlyMarketProfile|OnlyMarketProfileRegistry|OnlyMarketProfileRequest|OnlyResolvedMarketProfile' src/onlyalpha
```

如果 production authority 已完全失去：

目标：

```text
0
```

或只存在明确、仍有真实职责的非-production contract；必须解释。

---

# 八十三、禁止搜索结果通过注释规避

不能：

```text
把旧代码注释掉
```

来通过 Architecture Guard。

失去职责：

```text
删除。
```

---

# 八十四、验证命令

先读取当前：

```text
AGENTS.md
pyproject.toml
.github/workflows/
scripts/test_suite.py
```

使用仓库正式命令。

至少执行适用的：

```bash
uv sync --frozen --all-packages --all-groups

uv run ruff check src tests examples packages scripts
uv run ruff format --check src tests examples packages scripts

uv run mypy src/onlyalpha
```

新增 A-share package：

```bash
uv run mypy --config-file \
packages/market/onlyalpha-market-cn-ashare/pyproject.toml \
packages/market/onlyalpha-market-cn-ashare/src/onlyalpha_market_cn_ashare
```

构建：

```bash
uv build --all-packages
```

正式 lanes：

```bash
uv run python scripts/test_suite.py core-full
uv run python scripts/test_suite.py ashare
uv run python scripts/test_suite.py recovery
```

以及新增：

```text
Market Product contract tests
A-share plugin tests
A-share semantic conformance
Generic runtime cutover tests
architecture guards
```

最后：

```bash
git diff --check
```

---

# 八十五、Documentation

完成后准确更新：

```text
AGENTS.md
docs/architecture.md
docs/roadmap.md
```

必要时新增：

```text
docs/reports/p5_3_...
```

报告必须明确：

```text
P5.3 Runtime Market Product cutover completed
```

但不要错误声明：

```text
PAPER → SIM completed
SIM completed
Live completed
Research completed
```

---

# 八十六、如果需要新增 ADR

重新检查 P5.1/P5.2 ADR。

如果：

```text
Trading Runtime one-shot cutover
Profile production authority retirement
```

已经由现有 ADR 自然覆盖：

不要机械新增 ADR。

如果存在新的长期不可逆决策：

可以新增 ADR。

不要修改历史 ADR 来伪造过去事实。

---

# 八十七、最终实施报告

完成后输出完整 P5.3 Implementation Report。

必须包括：

```text
1. Current production authority audit

2. CN A-share Plugin architecture

3. A-share Reference ownership migration

4. A-share Compiler migration

5. Session / Price / Quantity / Settlement semantics

6. A-share Market Fee ownership

7. Product Factory / Binding

8. Config migration

9. Reference Resource composition

10. Resolve-exactly-once design

11. Runtime Environment migration

12. Persistence / Recovery identity migration

13. MarketRuleEngine refactor

14. Backtest cutover

15. Paper cutover

16. Legacy production APIs deleted

17. Profile framework final disposition

18. Experimental Futures/Crypto disposition

19. Generic runtime semantic regression

20. CN A-share semantic regression

21. CN_A_SHARE_DURABLE_BACKTEST_V1 result

22. Recovery / determinism result

23. Architecture guards

24. Validation commands/results

25. Remaining work explicitly belonging to P5.4/P6/P8
```

不要只列修改文件。

---

# 八十八、最终必须回答的三个问题

P5.3 结束时必须可以明确回答：

## Question 1

如果新增：

```text
onlyalpha-market-hk-equity
```

是否只需要：

```text
新 package
Reference
Compiler
Fee
Factory
Entry Point
Tests
```

而不修改：

```text
Backtest Factory
Paper/Sim Factory
Environment
MarketRuleEngine
Execution
Transaction
Position
Account
```

答案必须：

```text
YES
```

---

## Question 2

同一个：

```text
CN_A_SHARE_CASH@2025.1
```

同一个：

```text
Reference Authority
```

在：

```text
Backtest
Paper / future Sim
future Live
```

是否得到相同：

```text
Market Economic Identity
```

答案必须：

```text
YES
```

---

## Question 3

删除 Core concrete：

```text
A-share Reference
A-share Rules
Generic/A-share Profile composition
```

以后，Generic/A-share Runtime 是否仍然正常运行？

答案必须：

```text
YES
```

---

# 八十九、最终工程原则

整个 P5.3 必须始终遵守：

```text
Move Authority, not files.

One Market Product → one concrete semantic owner.

One Runtime build → one Market Product resolution.

Runtime consumes Binding.

Runtime does not infer market identity.

Product ID is evidence, not behavior selector.

Concrete Reference stays inside Plugin.

Plugin compiles semantics.

Core mutates trading state.

Market Product != Broker.

Market Product != DataSource.

Market Product != Risk.

Market Product != Execution Support.

Market Fee != Broker Fee.

Runtime Type != Market Economic Identity.

No partial cutover.

No compatibility bridge.

No implicit Generic fallback.

No legacy production path after cutover.

No concrete-market import from Core.

No duplicate authority.

Economic semantics remain stable.
```

---

# 最终验收定义

P5.3 真正完成时，OnlyAlpha 应从：

```text
Runtime
├── Market Profile
├── A-share knowledge
├── Generic knowledge
├── Reference selection
├── Compiler selection
└── Fee selection
```

变成：

```text
Runtime
└── OnlyResolvedMarketProductBinding
```

并且：

```text
Generic T0
→ onlyalpha-market-generic-t0-cash

CN A-share
→ onlyalpha-market-cn-ashare

Future Markets
→ their own Market Product Plugins
```

OnlyAlpha Core 最终只回答：

> **“我支持标准 Market Product Contract。”**

而不再回答：

> **“我内部知道怎么处理 A 股。”**

只要 Core 中仍存在一个为了具体市场而存在的 active behavioral branch，或者 Trading Runtime 仍然需要理解 Profile/A-share/Generic 才能完成市场组合，P5.3 就还没有完成。
