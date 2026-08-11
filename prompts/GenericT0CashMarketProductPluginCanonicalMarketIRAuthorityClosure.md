# OnlyAlpha P5.2 — Generic T0 Cash Market Product Plugin & Canonical Market IR Authority Closure

Repository:

`https://github.com/zongxin1993/OnlyAlpha`

当前任务属于 OnlyAlpha P5：

> **Market Product Plugin & Composition Authority**

当前执行阶段：

# P5.2 — Generic T0 Cash Market Product Plugin & Canonical Market IR Authority Closure

本任务必须基于当前 `master` 最新实现执行。

当前 P5.1 已完成：

```text
Core Market Product Contract & Composition Authority
```

已经建立：

```text
OnlyMarketProductPluginId
OnlyMarketProductIdentity
OnlyMarketProductConfig
OnlyCanonicalMarketProductConfig

OnlyMarketProductFactory
OnlyMarketProductFactoryRegistry
OnlyMarketProductResolutionContext

OnlyMarketReferenceAuthority
OnlyMarketPolicyCompiler

OnlyResolvedMarketProductBinding
OnlyMarketProductCompositionIdentity
```

以及：

```text
fail-closed Registry
immutable Binding
canonical config identity
contract tests
architecture guards
ADR 0069
```

P5.2 **不得重新设计第二套 Market Product Contract**。

P5.2 的任务是：

> **用第一个真实 Market Product——GENERIC_T0_CASH——验证 P5.1 Contract，并从第一性原理重新审查 Canonical Market IR，彻底剥离 Virtual Broker / Execution Simulation 不应属于 Market Product 的职责。**

---

# 一、必须先重新阅读当前 master

不要机械执行本 Prompt 中的类名。

首先检查当前 HEAD 和最新源码。

至少阅读：

```text
README.md
AGENTS.md

docs/architecture.md
docs/roadmap.md

docs/adr/0068-runtime-product-taxonomy-and-trading-semantic-equivalence.md
docs/adr/0069-*
```

重点重新阅读：

```text
src/onlyalpha/market/product/
src/onlyalpha/market/models.py
src/onlyalpha/market/profiles.py
src/onlyalpha/market/runtime_rules.py
src/onlyalpha/market/registry.py

src/onlyalpha/fee/
src/onlyalpha/settlement/
src/onlyalpha/plugin/
src/onlyalpha/runtime/

packages/fake/onlyalpha-plugin-broker-virtual/
```

特别审查：

```text
OnlyCompiledMarketPolicy

OnlyCompiledMarketRules

OnlyMarketProfile

OnlyLiquidityModel
OnlySlippageModel
OnlyMatchingModel

OnlyMarketRuleEngine.evaluate_match_time()

OnlyVirtualBrokerGateway
OnlyMatchingEngine
OnlySlippageModel
OnlyLatencyModel
Fill Plan
Fill Schedule
```

必须以当前 HEAD 的真实代码为准。

---

# 二、从第一性原理重新定义 P5.2

不要从“哪些文件应该移动”出发。

首先回答：

> Market Product 在 Trading System 中究竟拥有什么 Authority？

Market Product 应回答：

```text
这个 Instrument 是否允许交易？

当前 Session 是否允许下单？

当前价格是否合法？

当前数量是否合法？

Position / Short / Margin 制度是什么？

Settlement 制度是什么？

成交后 Core 应按照什么市场经济规则解释这个 Trade？

该 Market Product 使用什么 Market Fee Authority？
```

这些属于：

```text
Market Economic Semantics
```

而 Market Product 不应该回答：

```text
下一根 Bar 是否成交？

按开盘价还是收盘价成交？

模拟滑点多少？

最大参与成交量是多少？

一个 Bar 最多 Fill 多少？

网络延迟多少？

Broker ACK 延迟多少？

订单分几次部分成交？
```

这些属于：

```text
Virtual Broker / Execution Simulation
```

本任务必须从架构上彻底分离这两个 Authority。

---

# 三、P5.2 的核心原则

整个任务必须遵守：

```text
Market Product defines market economics.

Virtual Broker defines simulated execution.

Core owns mutable trading state.

Plugin compiles semantics.

Core executes mutation.

Product ID is evidence, not behavior selector.

Runtime Type is not market semantics.

Market Product != Broker.

Market Product != DataSource.

Market Product != Risk.

Market Product != Execution Support.

Market Fee != Broker Fee.

No implicit fallback.

No compatibility shim.

No partial Runtime cutover.

No duplicate authority.
```

---

# 四、第一任务不是创建 Generic package

P5.2 的第一件事必须是：

# Canonical Market IR Authority Audit

重新检查 P5.1 当前：

```text
OnlyCompiledMarketPolicy
```

以及 legacy：

```text
OnlyCompiledMarketRules
```

确认哪些字段真正属于：

```text
Market Product Economic Policy
```

哪些字段其实属于：

```text
Virtual Broker / Simulation
```

不要因为旧 `OnlyMarketProfile` 里已有字段就默认其 ownership 正确。

---

# 五、必须重新审计三个字段

当前如果新的 Canonical Market IR 仍包含：

```text
liquidity_policy
slippage_policy
matching_policy
```

必须重点审计。

原则上它们不应该属于 Market Product。

---

# 六、Matching 的正确 Authority

例如：

```text
NEXT_BAR_OPEN
NEXT_BAR_CLOSE
BAR_TOUCH
```

回答的是：

> Backtest/Sim 如何模拟外部市场给订单成交。

它不是：

> 交易所制度本身是什么。

因此：

```text
Matching
→ Virtual Broker / Execution Simulation
```

不属于：

```text
Market Product
```

Market Product Contract 中禁止：

```text
OnlyMatchingModel
matching_policy
next_bar_open
bar_touch
```

等模拟撮合语义。

---

# 七、Slippage 的正确 Authority

例如：

```text
NONE
FIXED_TICKS
BASIS_POINTS
VOLUME_IMPACT
```

属于模拟成交价格模型。

因此：

```text
Slippage
→ Virtual Broker
```

不能属于 Market Product IR。

Generic T0 Product 不应该决定：

```text
成交要加几个 tick 滑点
```

---

# 八、Simulation Liquidity 的正确 Authority

例如：

```text
BAR_VOLUME_PARTICIPATION
maximum_participation_rate
```

如果用于：

```text
限制 Virtual Broker 在某根 Bar 内最多成交多少
```

则属于：

```text
Execution Simulation
```

而不是 Market Product。

不要把：

```text
BAR_VOLUME_PARTICIPATION
```

视为 Generic T0 的市场制度。

---

# 九、P5.2 必须修正 Canonical Market IR

目标结构应接近：

```text
OnlyCompiledMarketPolicy
│
├── identity
│
├── instrument_terms
│
├── session_policy
├── price_policy
├── quantity_policy
├── position_policy
├── short_policy
├── settlement_policy
└── margin_policy
```

根据当前代码实际需求调整。

禁止继续包含：

```text
matching
slippage
latency
fill schedule
fill plan
simulation liquidity
```

---

# 十、不要用 Optional 字段保留错误边界

禁止：

```python
matching_policy: ... | None = None
slippage_policy: ... | None = None
liquidity_policy: ... | None = None
```

如果这些字段不属于 Market Product：

> **直接从新的 Canonical Market IR 删除。**

不要 deprecated。

不要 compatibility alias。

P5.1 目前还没有正式 concrete product consumer，因此现在就是修正 Contract 的最佳窗口。

---

# 十一、重新定义 Core 真正需要的 Instrument Economic Terms

当前 legacy Runtime 会直接读取 Reference：

```text
currency
contract_multiplier
status
suspended
tick_size
...
```

而 P5.1 新设计已经允许 concrete Reference 对 Core opaque。

这是正确方向。

因此必须回答：

> Core 在 Reference opaque 之后，还需要哪些标准经济事实？

建议建立最小的：

```text
OnlyCompiledInstrumentMarketTerms
```

或当前命名风格下等价类型。

至少考虑：

```text
settlement_currency
contract_multiplier
trading_status
```

如果存在其它真实 Core requirement，再增加。

---

# 十二、Trading Status 必须是 canonical

不要让 Core 直接知道：

```text
ST
A-share suspension flag
exchange-specific lifecycle state
```

应该由 Plugin 编译为标准状态，例如：

```text
TRADABLE
SUSPENDED
INACTIVE
...
```

具体 enum 根据现有模型设计。

Core 只判断：

```text
当前 Instrument 是否可进行该市场操作
```

不解释 concrete market 原因。

---

# 十三、不要构造 Universal Reference DTO

禁止创建：

```text
OnlyUniversalInstrumentReference
```

并放入：

```text
board
st_status
hk_board_lot
us_short_sale_flag
futures_delivery_month
crypto_funding
...
```

这不是 Canonical IR。

正确模型：

```text
Concrete Reference
    ↓
Concrete Product Compiler
    ↓
Minimal Canonical Market Terms
```

---

# 十四、Generic T0 是第一个真实 Market Product

完成 Canonical IR 修正后，建立：

```text
onlyalpha-market-generic-t0-cash
```

这是一个真正的 concrete Market Product Plugin。

它不是：

```text
Core default market
```

也不是：

```text
fallback market
```

---

# 十五、建议物理包结构

建议：

```text
packages/
└── market/
    └── onlyalpha-market-generic-t0-cash/
        ├── pyproject.toml
        ├── README.md
        ├── src/
        │   └── onlyalpha_market_generic_t0_cash/
        │       ├── __init__.py
        │       ├── config.py
        │       ├── reference.py
        │       ├── compiler.py
        │       ├── fee_pack.py
        │       └── factory.py
        └── tests/
```

可以根据真实职责微调。

不要为了目录结构制造：

```text
utils.py
manager.py
runtime.py
service.py
hooks.py
```

等无意义模块。

---

# 十六、Generic Product Identity

明确：

```text
Plugin ID:
onlyalpha-market-generic-t0-cash

Product ID:
GENERIC_T0_CASH

Product Version:
1
```

Provider identity 和 Product identity 必须继续分开。

---

# 十七、Generic T0 V1 的经济语义

保持当前 legacy Generic T0 V1 的经济行为。

当前基线应重新从源码确认，大致为：

```text
Asset:
EQUITY / FUND

Session:
Generic Day / UTC

Settlement:
T0 / immediate

Position:
LONG_ONLY

Short:
DISABLED

Margin:
NONE

Price:
instrument/reference tick

Quantity:
instrument/reference minimum + step
fractional allowed

Daily Price Limit:
NONE
```

P5.2 是 ownership migration。

不要顺便修改产品经济定义。

---

# 十八、不要把 Generic T0 设计成 Universal Market DSL

禁止：

```yaml
market:
  product: GENERIC_T0_CASH
  config:
    settlement: T1
    short: true
    margin: true
    matching: NEXT_BAR_OPEN
    price_limit: 0.1
```

如果 Generic Product 可以通过配置变成任意市场：

```text
Product Identity
```

就失去了经济意义。

原则：

```text
Product Version
→ defines product semantics

Reference
→ defines instrument-specific facts

Config
→ resolves resources/composition
```

---

# 十九、Generic typed config 要保持极小

例如：

```python
@dataclass(frozen=True, slots=True)
class OnlyGenericT0CashConfig:
    reference_resource_id: str
```

只有真实 composition requirement 才增加字段。

禁止让 config 决定：

```text
settlement mode
position mode
short semantics
fee rules
matching
slippage
```

---

# 二十、Raw Config 与 Effective Config 要区分

配置：

```text
reference_resource_id
```

可能只是 transport lookup identity。

Composition fingerprint 应基于：

```text
resolved effective authority
```

而不是原始 alias。

正确：

```text
Raw Config
    ↓
Typed Config
    ↓
Resource Resolution
    ↓
Effective Authority
    ↓
Composition Identity
```

如果 V1 没有其它经济配置：

```text
effective_config
```

可以为空。

---

# 二十一、Generic Plugin-own Reference

Generic T0 不应把现有：

```text
OnlyInstrumentReferenceSnapshot
```

作为自己的长期 concrete Reference Contract。

原因是该旧 DTO 已经携带：

```text
board
st_status
suspended
previous_close
```

等历史 concrete-market 内容。

Generic Plugin 应定义自己的最小 Reference，例如：

```python
@dataclass(frozen=True, slots=True)
class OnlyGenericT0CashReference:
    instrument_id: ...
    asset_class: ...
    settlement_currency: ...
    contract_multiplier: ...
    tick_size: ...
    quantity_step: ...
    minimum_quantity: ...
    maximum_quantity: ...
    active: ...
    content_fingerprint: str
```

字段必须以 Generic compiler 真实需求为准。

---

# 二十二、Reference Authority

实现：

```text
OnlyGenericT0CashReferenceAuthority
```

并满足 P5.1：

```text
OnlyMarketReferenceAuthority
```

它必须有：

```text
identity
resolve(...)
```

并且：

```text
immutable
deterministic
fail closed
```

---

# 二十三、Reference Resolution 必须 Fail Closed

给定：

```text
Instrument
Trading Day
```

如果：

```text
0 valid records
→ fail

1 valid record
→ return

>1 valid records
→ fail ambiguity
```

禁止：

```text
first match
latest match
fallback default
```

---

# 二十四、Reference Identity

Reference Authority identity 必须覆盖：

```text
authority id
authority version
effective content fingerprint
```

禁止使用：

```text
repr(object)
memory address
Python object id
```

进入正式 economic identity。

---

# 二十五、Generic Policy Compiler

实现：

```text
OnlyGenericT0CashPolicyCompiler
```

并满足：

```text
OnlyMarketPolicyCompiler
```

流程：

```text
OnlyMarketPolicyCompilationRequest
        ↓
Generic Reference
        ↓
GENERIC_T0_CASH@1 product semantics
        ↓
OnlyCompiledMarketPolicy
```

---

# 二十六、Compiler 必须 pure / deterministic

同样：

```text
Product Version
Reference
Trading Day
```

必须得到同样：

```text
Compiled Policy
Policy Identity
Fingerprint
```

Compiler 不允许：

```text
读 Account

读 Position mutable state

调用 Risk

调用 Broker

修改 Runtime

提交 Order

写 Transaction
```

---

# 二十七、Generic Price Policy

V1：

```text
tick
    来自 Reference

daily price limit
    none

previous close dependency
    none
```

不要调用 A-share compiler。

不要：

```text
if product != CN_A_SHARE
```

使用 Generic branch。

Generic Plugin 自己拥有 implementation。

---

# 二十八、Generic Quantity Policy

V1：

```text
minimum quantity
    Reference minimum
    or quantity step

increment
    Reference quantity step

fractional
    allowed

odd-lot A-share liquidation rule
    none
```

同样完全 Plugin-owned。

---

# 二十九、Position / Short / Margin / Settlement

Generic T0 V1 固定：

```text
Position:
LONG_ONLY

Short:
DISABLED

Margin:
NONE

Settlement:
T0 / Immediate
```

这些是：

```text
GENERIC_T0_CASH@1
```

经济定义。

不能由：

```text
Runtime Mode
Broker
DataSource
```

决定。

---

# 三十、Generic Market Fee ownership

当前 Generic Market Fee concrete definition 仍位于 Core。

P5.2 应把 Generic-specific Fee definition 移到：

```text
onlyalpha-market-generic-t0-cash
```

Plugin 提供：

```text
OnlyMarketFeePack
```

Core 继续拥有：

```text
OnlyFeeEngine
Fee Accrual
Fee Ledger
Fee Application
Fee Reconciliation
```

正式规则：

```text
Plugin defines Fee Authority.
Core applies Fee Authority.
```

---

# 三十一、Broker Fee 必须保持独立

不要把：

```text
Broker commission
```

合进 Generic Market Product。

继续：

```text
Market Fee Pack
!=
Broker Fee Contract
```

---

# 三十二、不要在 P5.2 重构整个 Fee compatibility model

当前：

```text
OnlyMarketFeePack.compatible_market_profiles
```

仍带有 legacy Profile vocabulary。

本阶段不要新增平行：

```text
compatible_market_products
```

造成第二套 compatibility truth。

除非现有类型完全阻塞 P5.2，否则先复用。

完整命名/identity 清理留给 P5.3/P5.4 一次处理。

---

# 三十三、Market Product Discovery

当前项目已有：

```text
onlyalpha.data_sources
onlyalpha.brokers
onlyalpha.broker_fee_contracts
```

entry-point discovery。

优先复用现有机制。

增加：

```text
onlyalpha.market_products
```

而不是设计新的动态插件框架。

---

# 三十四、Generic package Entry Point

概念：

```toml
[project.entry-points."onlyalpha.market_products"]
generic_t0_cash = "onlyalpha_market_generic_t0_cash.factory:..."
```

具体 factory export 根据当前 plugin discovery convention。

---

# 三十五、Core 不允许 import Generic package

严格禁止：

```python
from onlyalpha_market_generic_t0_cash import ...
```

出现在：

```text
src/onlyalpha/
```

尤其禁止：

```text
runtime/defaults.py
runtime/backtest/
market/
```

直接 import concrete product。

必须：

```text
Plugin package
    ↓ Entry Point
Discovery
    ↓
OnlyMarketProductFactoryRegistry
```

---

# 三十六、Composition Root 可以持有 Market Product Registry

P5.2 可以把：

```text
OnlyMarketProductFactoryRegistry
```

正式纳入：

```text
OnlyComponentFactoryRegistries
```

或当前统一 composition infrastructure。

例如：

```text
data_sources
brokers
broker_fee_contracts
market_products
```

这是 Core-neutral infrastructure。

允许。

---

# 三十七、Composition Root 不能硬注册 concrete Generic

禁止：

```python
market_products.register(
    OnlyGenericT0CashMarketProductFactory()
)
```

写在 Core defaults。

如果是外部 package：

通过 discovery 注册。

Core 只能知道：

```text
Registry
Factory Contract
```

---

# 三十八、不要为了统一强改 OnlyPluginDescriptor

当前 Market Product P5.1 已有独立：

```text
OnlyMarketProductPluginId
```

除非现有 discovery 实现确实无法支持，否则不要顺手修改整个：

```text
OnlyPluginType
OnlyPluginDescriptor
```

把 Market Product 强塞进去。

P5.2 要复用 discovery 机制，不代表必须合并所有 Plugin identity model。

---

# 三十九、Generic Plugin Architecture Guard

Generic Plugin 不允许 import：

```text
onlyalpha.runtime
onlyalpha.runtime.backtest
onlyalpha.runtime.paper

onlyalpha.broker
onlyalpha.risk
onlyalpha.order
onlyalpha.position
onlyalpha.account
onlyalpha.execution
onlyalpha.transaction

onlyalpha.market.ashare_rules
onlyalpha.reference.ashare
```

允许依赖的主要是：

```text
OnlyAlpha Market Product public contract

Canonical immutable market policy/value types

Domain value/identifier types

Fee authority definition primitives
```

---

# 四十、Generic Plugin 不得依赖 legacy Market Profile

强烈要求：

```text
onlyalpha_market_generic_t0_cash
```

不得依赖：

```text
OnlyMarketProfile
OnlyMarketProfileRegistry
OnlyMarketProfileRequest
OnlyResolvedMarketProfile
```

否则只是：

```text
Plugin
→ old Profile
→ old compiler
```

并没有证明 P5.1 Contract。

---

# 四十一、Generic Plugin 不得调用 legacy Generic compiler helper

例如当前：

```text
_compile_generic_price_policy
_compile_generic_quantity_policy
```

可以作为测试 Oracle。

但新 Plugin implementation 禁止直接调用。

正确依赖：

```text
legacy implementation
    ↓
tests compare

new plugin implementation
    independent
```

---

# 四十二、不要做 Runtime 半切换

这是本任务最重要的迁移纪律之一。

P5.2 不能：

```text
GENERIC_T0
    → New Binding

CN_A_SHARE
    → Legacy Profile
```

因为这样 Runtime 会新增：

```python
if Generic:
    new path
else:
    old path
```

这就是新的 concrete market dispatch。

---

# 四十三、P5.2 的 Generic Plugin 先作为 Replacement Candidate

正确阶段关系：

```text
P5.2:

Legacy Generic
    current production authority

New Generic Plugin
    replacement candidate
    contract/conformance validated
```

两者不能在同一 Runtime 同时成为 authority。

---

# 四十四、P5.3 再做 Atomic Cutover

P5.3 等：

```text
Generic Plugin ready
A-share Plugin ready
```

然后：

```text
Trading Runtime
    ↓
Market Product Registry
    ↓
Binding
```

一次切换。

再删除：

```text
legacy Generic profile composition
legacy A-share composition
profile-specific Runtime branch
```

P5.2 不提前做。

---

# 四十五、不要新增任何 Compatibility Bridge

禁止：

```text
LegacyGenericAdapter

GenericProfileToProductAdapter

MarketProductCompatibilityFactory

GenericFallbackResolver

LegacyGenericBinding

old→new alias
```

新 Plugin 和旧 production path 暂时平行存在即可。

不要互相包裹。

---

# 四十六、Semantic Conformance 是 P5.2 核心验证

因为本阶段不切 production Runtime，最重要的是：

```text
Legacy Generic Economics
        ==
New Generic Plugin Economics
```

相同：

```text
Instrument
Trading Day
Reference facts
```

比较：

```text
Session
Price Policy
Quantity Policy
Position Policy
Short Policy
Settlement Policy
Margin Policy
Instrument Economic Terms
Market Fee
```

---

# 四十七、明确不比较 Simulation Fields

不要要求新旧：

```text
Matching
Slippage
Simulation Liquidity
```

相等。

因为新架构已经明确：

```text
它们不属于 Market Product
```

应该新增反向 Architecture Test：

```text
OnlyCompiledMarketPolicy
does not contain:
    matching
    slippage
    simulation liquidity
```

---

# 四十八、Fee Conformance

相同输入：

```text
instrument
side
notional
trading day
```

旧 Generic Fee 与新 Generic Plugin Fee Pack 应保持：

```text
same fee items
same fee total
same rounding
same economic authority result
```

如果 fingerprint 因 ownership relocation 合理变化，要区分：

```text
structural identity change
```

与：

```text
economic result change
```

---

# 四十九、Reference Conformance

不要比较 DTO equality。

只比较：

```text
instrument identity
settlement currency
contract multiplier
tick
quantity step
minimum quantity
maximum quantity
trading status
```

等真正进入 Canonical Market IR 的经济事实。

---

# 五十、增加第三 Test Market

为了证明 Contract 不是：

```text
Generic T0 special interface
```

增加 tests-only Market Product。

例如：

```text
TEST_MARKET
```

规则故意不同：

```text
tick = 0.25
quantity step = 7
settlement = T+2
```

要求：

```text
不修改 Core
```

即可：

```text
register
resolve
compile
produce canonical policy
```

---

# 五十一、P5.2 不修改 Trading Kernel

除 wiring/contract 必要改动外，不修改：

```text
OrderManager
PositionManager
AllocationManager
AccountManager
StrategyLedger

Risk economics

ExecutionProcessor

TransactionPlanner
TransactionCoordinator

Projection

Recovery

Settlement Authority

Virtual Broker execution algorithm
```

---

# 五十二、特别禁止修改 PnL/Fill/Reservation

如果任务需要修改：

```text
PnL
fill application
position cost
reservation lifecycle
durable commit
recovery
```

才能实现 Generic Market Product：

说明架构边界错误。

停止并重新检查设计。

---

# 五十三、Settlement 边界

Generic Plugin 只能定义：

```text
T0 Settlement Policy
```

Core：

```text
OnlySettlementAuthority
```

负责执行：

```text
booking
availability
projection
recovery
```

禁止 Plugin：

```text
直接修改 Position
直接修改 Account
```

---

# 五十四、Execution Support 必须完全独立

Generic Product 可以说：

```text
市场允许 LIMIT
市场是 LONG_ONLY
```

但不能说：

```text
OnlyAlpha Kernel 支持什么
```

继续保持：

```text
Market Allowed
AND
Execution Supported
```

两个独立 Authority。

---

# 五十五、Risk 必须独立

Generic Product 不负责：

```text
max position
max order notional
strategy risk budget
account exposure
```

这些继续属于 Risk。

---

# 五十六、Runtime Mode 不能进入新 Generic semantics

Generic Plugin 禁止 import/use：

```text
OnlyRuntimeMode
BACKTEST
PAPER
SIM
LIVE
```

产品语义必须与 Runtime 名称无关。

---

# 五十七、不要顺手修其它 Runtime-mode debt

当前 legacy：

```text
OnlyCompiledMarketRuleIdentity.runtime_mode
```

可以留到 P5.3 Runtime cutover。

当前：

```text
Position Authority LIVE branch
Fee provisional LIVE branch
```

属于以后 Broker Evidence/P8。

不要扩大 P5.2。

---

# 五十八、旧 Generic production path暂时保留

P5.2 结束时，仍可存在：

```text
only_generic_t0_cash_profile()

legacy Generic compiler branch

legacy Generic fee pack
```

因为 production Runtime 尚未 cutover。

它们此时仍有真实职责。

不要为了“代码看起来干净”提前删除当前 Authority。

---

# 五十九、但不要新增旧接口

区别必须明确：

```text
current authoritative legacy implementation
    temporarily retain

new compatibility interface
    forbidden
```

禁止新建：

```text
deprecated alias
bridge
fallback
adapter
```

---

# 六十、代码清洁原则

新增代码必须：

```text
strongly typed

frozen immutable where appropriate

single ownership

no global side effects

no hidden registration side effects

no arbitrary fallback

no circular import hack

no duplicate semantic model

no generic "utils" dumping ground

no unnecessary inheritance

no Runtime-shaped plugin
```

---

# 六十一、公共 API

Generic Market Product 外部 package 应只通过：

```text
onlyalpha.plugin.api
```

或当前正式 stable plugin contract import surface 依赖 Core。

不要从 Core 私有内部路径到处 import。

如果 P5.1 已经建立稳定 plugin API，应优先使用它。

---

# 六十二、不要扩张 Public API

仅 export Generic Plugin 真正需要暴露的：

```text
Factory
Product identity if needed
typed config if intended public
```

内部 compiler/reference implementation 不要全部 export。

---

# 六十三、实现顺序

必须按以下顺序实施。

## Phase 1 — Audit

重新确认：

```text
P5.1 Contract
legacy Generic semantics
Virtual Broker authority
Fee boundary
Settlement boundary
```

输出内部 audit 结论后直接继续实现，不等待确认。

---

## Phase 2 — Canonical Market IR Correction

完成：

```text
remove matching from new Market Product IR

remove slippage

remove simulation liquidity

add minimal canonical instrument economic terms if required

update P5.1 tests

update architecture guards
```

不要改 production Runtime。

---

## Phase 3 — Generic T0 Package

建立：

```text
onlyalpha-market-generic-t0-cash
```

实现：

```text
typed config
reference model
reference authority
policy compiler
market fee pack
factory
binding composition
```

---

## Phase 4 — Discovery

接入：

```text
onlyalpha.market_products
```

复用现有 discovery infrastructure。

Market Product Registry 可以进入 neutral component registries。

Core 不能 concrete import Generic package。

---

## Phase 5 — Conformance

建立：

```text
Legacy Generic
vs
New Generic Plugin
```

比较：

```text
Price
Quantity
Session
Position
Short
Settlement
Margin
Instrument Terms
Market Fee
```

---

## Phase 6 — Test Product

建立一个 tests-only 第三 Market Product。

验证：

```text
zero Core behavioral branch
```

---

## Phase 7 — Static Architecture Guards

验证：

```text
Core does not import Generic plugin

Generic plugin does not import Runtime/Broker/Risk/A-share

Canonical Market IR has no simulation execution policies
```

---

## Phase 8 — Full Regression

运行当前仓库正式质量门禁。

---

## Phase 9 — Docs

准确更新：

```text
AGENTS.md
docs/architecture.md
docs/roadmap.md
```

必要时新增 P5.2 report。

不要声称：

```text
Trading Runtime Market Product cutover completed
```

因为这是 P5.3。

---

# 六十四、P5.2 不允许的实现

严格禁止：

```text
1. 把 only_generic_t0_cash_profile 原样搬进 package

2. Plugin 内创建 OnlyMarketProfile 然后调用旧 Compiler

3. Core import onlyalpha_market_generic_t0_cash

4. Generic T0 作为 missing-plugin fallback

5. Runtime 加 if GENERIC_T0 then new path

6. Generic Plugin 持有 Broker

7. Generic Plugin 持有 Risk

8. Generic Plugin 持有 Trading Manager

9. Market Product IR 包含 matching

10. Market Product IR 包含 slippage

11. Market Product IR 包含 simulation liquidity

12. Generic Config 变成 Universal Market DSL

13. arbitrary override settlement/position/short semantics

14. Compatibility adapter

15. deprecated alias

16. old→new wrapper

17. 修改 Trading economics

18. 修改 Recovery economics

19. 重写 Fee Engine

20. 重写 Settlement Authority
```

---

# 六十五、P5.2 Architecture Guards

至少增加以下自动验证。

## Core boundary

搜索：

```text
onlyalpha_market_generic_t0_cash
```

在：

```text
src/onlyalpha/
```

必须没有 concrete import。

---

## Generic Plugin boundary

禁止：

```text
onlyalpha.runtime
onlyalpha.broker
onlyalpha.risk
onlyalpha.execution
onlyalpha.transaction
onlyalpha.reference.ashare
onlyalpha.market.ashare_rules
```

---

## Simulation vocabulary

Generic Market Product implementation 中禁止：

```text
NEXT_BAR_OPEN
BAR_TOUCH
slippage
fill_schedule
latency
volume_participation
```

作为 Market Product semantics。

---

## Runtime vocabulary

Generic Product 中禁止：

```text
BACKTEST
PAPER
SIM
LIVE
OnlyRuntimeMode
```

---

# 六十六、Contract Tests

至少覆盖：

```text
Generic factory resolves correct product

wrong product id fails

wrong version fails

invalid config fails

missing reference authority fails

ambiguous reference fails

binding immutable

same effective authority → same composition identity

changed reference authority → changed composition identity

changed product version → changed composition identity

raw unused config → no economic identity change

policy compile deterministic
```

---

# 六十七、Generic Semantic Tests

至少覆盖：

```text
session

price tick

no price limit

quantity minimum

quantity increment

fractional quantity

long-only semantics

short disabled

T0 settlement

no margin

instrument status

contract multiplier

settlement currency
```

---

# 六十八、Fee Tests

验证：

```text
Generic plugin Market Fee Pack
```

与当前 legacy Generic fee economics 等价。

同时验证：

```text
Broker Fee Contract
```

没有被 Market Product 吞掉。

---

# 六十九、Discovery Tests

至少：

```text
Market Product entry point discovered

Factory registered

duplicate/conflict fails closed

unknown provider fails

discovery order deterministic

Core does not require concrete import
```

---

# 七十、Third Market Tests

tests-only Product：

```text
TEST_T2_MARKET
```

建议有明显不同：

```text
tick 0.25
quantity step 7
T+2
```

目的：

> 证明 Canonical Market IR 是 market-neutral，而不是 Generic T0 schema。

---

# 七十一、验证命令

先阅读当前：

```text
AGENTS.md
pyproject.toml
.github/workflows/
scripts/test_suite.py
```

使用当前仓库正式命令。

至少执行适用的：

```bash
uv sync --frozen --all-packages --all-groups

uv run ruff check src tests examples packages scripts
uv run ruff format --check src tests examples packages scripts

uv run mypy src/onlyalpha
```

新增 Market package 必须执行其 mypy/static check。

执行：

```bash
uv build --all-packages
```

执行当前正式 lanes：

```bash
uv run python scripts/test_suite.py core-full
uv run python scripts/test_suite.py ashare
uv run python scripts/test_suite.py recovery
```

以及 Generic/Market Product 新增 tests。

最后：

```bash
git diff --check
```

---

# 七十二、静态搜索

至少运行：

```bash
rg -n 'onlyalpha_market_generic_t0_cash' src/onlyalpha
```

结果不允许出现 concrete import。

搜索：

```bash
rg -n 'OnlyMatchingModel|OnlySlippageModel|OnlyLiquidityModel' src/onlyalpha/market/product
```

如果这些表示 simulation execution authority：

必须为 0。

搜索 Generic package：

```bash
rg -n 'OnlyRuntimeMode|BACKTEST|PAPER|SIM|LIVE|Ashare|CN_A_SHARE|XSHG|XSHE' packages/market/onlyalpha-market-generic-t0-cash
```

Concrete behavioral dependency 必须为 0。

---

# 七十三、Definition of Done

只有全部满足才能结束。

## Canonical Market IR

```text
[ ] Market Product IR 不再包含 matching

[ ] 不再包含 slippage

[ ] 不再包含 simulation liquidity

[ ] Instrument economic terms 边界明确

[ ] Reference 对 Core 保持 opaque

[ ] Product IR 不含 Runtime Mode
```

## Generic Product

```text
[ ] onlyalpha-market-generic-t0-cash 独立 package

[ ] Product identity 正确

[ ] typed config

[ ] plugin-owned Reference

[ ] Reference Authority

[ ] Policy Compiler

[ ] Market Fee Pack

[ ] Factory

[ ] Resolved Binding
```

## Authority Boundary

```text
[ ] Matching 属于 Virtual Broker

[ ] Slippage 属于 Virtual Broker

[ ] Simulation Liquidity 属于 Virtual Broker

[ ] Market Product 不拥有 Risk

[ ] 不拥有 Broker

[ ] 不拥有 Execution Support

[ ] 不拥有 mutable Trading State

[ ] Settlement Authority 仍在 Core

[ ] Fee Engine 仍在 Core
```

## Dependency

```text
[ ] Plugin → Core

[ ] Core 不 import Plugin

[ ] Generic Plugin 不 import Runtime

[ ] 不 import A-share

[ ] 不依赖 legacy Market Profile architecture

[ ] 不调用 legacy Generic compiler implementation
```

## Discovery

```text
[ ] onlyalpha.market_products discovery 存在

[ ] Generic Product 可自动发现

[ ] Registry fail closed

[ ] 无 global side-effect registration

[ ] 无 Core concrete registration
```

## Conformance

```text
[ ] Price semantics 等价

[ ] Quantity semantics 等价

[ ] Session semantics 等价

[ ] Position semantics 等价

[ ] Short semantics 等价

[ ] Settlement semantics 等价

[ ] Margin semantics 等价

[ ] Fee economics 等价

[ ] Reference canonical economic facts 等价
```

## Extension Proof

```text
[ ] Third test Market Product 可以无 Core behavioral change 接入
```

## Cleanup

```text
[ ] 无 compatibility adapter

[ ] 无 fallback

[ ] 无 alias

[ ] 无 deprecated API

[ ] 无第二套 Market Product Contract

[ ] 无 Generic Runtime branch

[ ] 无 dead experimental path
```

## Regression

```text
[ ] static PASS

[ ] build PASS

[ ] Market Product contract PASS

[ ] Generic plugin tests PASS

[ ] core-full PASS

[ ] ashare PASS

[ ] recovery PASS
```

---

# 七十四、P5.2 完成后的目标状态

最终应形成：

```text
                         OnlyAlpha Core
                              ▲
                              │
                  Market Product Contract
                              │
             ┌────────────────┴────────────────┐
             │                                 │
             ▼                                 ▼
 onlyalpha-market-                     Test Market
 generic-t0-cash
             │
             ├── Reference Authority
             ├── Policy Compiler
             ├── Market Fee Pack
             └── Product Factory
             │
             ▼
 OnlyResolvedMarketProductBinding
```

同时：

```text
Virtual Broker
├── Matching
├── Slippage
├── Latency
├── Fill Plan
└── Fill Scheduling
```

二者没有 Authority 重叠。

---

# 七十五、P5.2 完成后不要立即删除什么

以下仍可能是当前生产路径：

```text
OnlyMarketProfile

legacy Generic Profile

legacy Generic Compiler branch

legacy Runtime Market composition
```

它们将在 P5.3 one-shot cutover 后删除。

不要在 replacement 尚未进入 production authority 前提前删除仍有职责的代码。

---

# 七十六、P5.3 的明确入口

P5.2 完成以后，下一阶段必须能够直接开始：

```text
P5.3
CN A-share Full Authority Migration
+
Trading Runtime One-shot Cutover
```

P5.3 不应该再需要重新讨论：

```text
Market Product Contract 是什么？

Generic Plugin 怎么加载？

Matching 属于谁？

Reference 是否 opaque？

Market Fee 属于谁？
```

这些问题必须在 P5.2 完成时已经冻结。

---

# 七十七、最终输出要求

完成后输出一份完整 P5.2 Implementation Report。

必须包含：

```text
1. Current implementation audited

2. Canonical Market IR authority problems found

3. Market vs Virtual Broker boundary corrections

4. Final Canonical Market IR

5. Generic T0 package structure

6. Generic typed config

7. Generic Reference Authority

8. Generic Policy Compiler

9. Generic Market Fee ownership

10. Product Factory / Binding implementation

11. Market Product discovery integration

12. Dependency-direction proof

13. Legacy-vs-new semantic conformance

14. Third Market extension proof

15. Architecture guards

16. APIs deliberately removed from new Contract

17. Legacy production code intentionally retained for P5.3

18. Validation commands and results

19. Remaining P5.3 migration debt
```

不要只报告修改了哪些文件。

必须说明：

> **为什么 Generic T0 现在已经只是一个普通 concrete Market Product，而不再是 Core 隐藏默认市场。**

同时说明：

> **为什么 Matching / Slippage / Simulation Liquidity 已经不能重新进入 Market Product Authority。**

---

# 七十八、最终验收问题

P5.2 完成后必须能明确回答：

```text
谁定义 Generic T0 市场经济制度？
→ onlyalpha-market-generic-t0-cash

谁定义模拟撮合？
→ Virtual Broker

谁定义模拟滑点？
→ Virtual Broker

谁拥有订单？
→ Core Order Authority

谁拥有 Position？
→ Core Position Authority

谁拥有 Account？
→ Core Account Authority

谁定义 Market Fee？
→ Market Product

谁应用 Fee？
→ Core Fee Engine

谁定义 Broker Fee？
→ Broker Fee Contract

谁执行 Settlement？
→ Core Settlement Authority

Runtime 是否知道 Generic T0？
→ No

Core 是否 import Generic Plugin？
→ No

Generic Plugin 是否知道 Backtest/Sim/Live？
→ No
```

---

# 最终工程原则

整个 P5.2 必须始终遵守：

```text
Market Product is a market semantics compiler.

It is not a market simulator.

Concrete Reference stays inside the Plugin.

Canonical Market IR contains only Core-required economics.

Simulation execution belongs to Virtual Broker.

Plugin computes.

Core mutates.

Product identity is evidence.

Runtime type is not market semantics.

Generic T0 is not a fallback.

Core never imports concrete market packages.

No compatibility layer.

No partial Runtime migration.

No duplicate authority.

No speculative universal framework.

Economic behavior remains stable.
```

最终判断 P5.2 是否成功，只问两个问题：

> **第一：如果把 Virtual Broker 从 Backtest 换成真实 Broker，GENERIC_T0_CASH Market Product 是否完全不需要变化？**

> **第二：如果下一步实现 `onlyalpha-market-cn-ashare`，是否可以直接复用同一个 Market Product Contract 和 Canonical Market IR，而无需再向 Core 增加 `if A-share`？**

只要任意一个答案不是明确的“是”，P5.2 就还没有完成。
