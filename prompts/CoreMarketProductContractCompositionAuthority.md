# OnlyAlpha P5.1 — Core Market Product Contract & Composition Authority

Repository:

`https://github.com/zongxin1993/OnlyAlpha`

本任务属于 OnlyAlpha P5：

> **Market Product Plugin & Composition Authority**

当前执行的是：

# P5.1 — Core Market Product Contract & Composition Authority

这是一个完整的架构实现任务。

不要把 P5.1 拆成多个等待确认的小任务。

必须从当前 `master` 的实际代码出发，一次完成：

```text
Current Architecture Audit
        ↓
First-Principles Boundary Definition
        ↓
Core Market Product Contract
        ↓
Market Product Registry
        ↓
Immutable Resolved Binding
        ↓
Composition Identity
        ↓
Configuration Boundary
        ↓
Architecture Guards
        ↓
Tests
        ↓
Documentation Synchronization
```

P5.1 **不负责正式迁移 Generic T0 或 CN A-share 具体实现**。

这些属于后续：

```text
P5.2
Generic T0 Cash Plugin + Canonical Market IR

P5.3
CN A-share Full Authority Migration + Runtime Cutover

P5.4
Identity Hardening + Dead API Deletion + Certification
```

但 P5.1 建立的 Contract 必须足够正确，使 P5.2/P5.3 不需要推翻它重新设计。

---

# 一、必须先从第一性原理理解问题

不要从：

```text
现在有哪些 class
现在有哪些 if
现在有哪些 profile
现在 A 股怎么实现
```

反推出抽象。

首先回答：

> Trading Runtime 为什么需要“市场产品”这个概念？

一笔交易要执行，Trading Core 需要知道：

```text
该 Instrument 当前是否允许交易？

当前时间是否允许交易？

价格是否合法？

数量是否合法？

需要什么 Reference？

需要采用什么市场规则？

成交以后产生什么 Settlement 语义？

应该使用什么 Market Fee Authority？

当前到底使用的是哪一组版本化市场经济 Authority？
```

这些问题不能由：

```text
Strategy
OrderManager
RiskManager
PositionManager
AccountManager
ExecutionProcessor
Broker
DataSource
```

任意一个模块临时回答。

它们共同属于：

> **Market Product Composition Authority**

因此必须建立明确的 ownership：

```text
Market Product Composition Authority
        ↓
resolves
        ↓
Immutable Market Product Binding
        ↓
Trading Runtime
```

核心原则：

> **Concrete Market Knowledge belongs to Market Product Plugin; Core owns only canonical contracts and trading state.**

---

# 二、P5.1 最终要解决的根问题

当前 OnlyAlpha 中 concrete market knowledge 仍可能散布于：

```text
Config
Runtime Environment
Runtime Factory
Reference
Market Rule Compiler
Fee composition
Settlement composition
```

P5.1 不负责立即搬走所有 concrete implementation。

但必须建立新的唯一目标路径：

```text
Market Product Config
        ↓
Market Product Registry
        ↓
Market Product Factory
        ↓
resolve(...)
        ↓
OnlyResolvedMarketProductBinding
        ↓
Trading Runtime Composition
```

未来任何具体市场：

```text
Generic T0
CN A-share
HK Equity
US Equity
CN Futures
Crypto Spot
```

都只能通过这条路径进入 Trading Plane。

禁止以后再增加：

```python
if market == ...
```

作为新的 Core composition mechanism。

---

# 三、P5.1 必须明确的架构边界

最终架构：

```text
                         OnlyAlpha Core
                               │
                               │ defines
                               ▼
                   Market Product Contract
                               ▲
                               │ implements
               ┌───────────────┼────────────────┐
               │               │                │
               ▼               ▼                ▼
          Generic T0       CN A-share        Future Market
            Plugin            Plugin             Plugin
```

依赖方向必须永远是：

```text
Concrete Market Plugin
        ↓
OnlyAlpha Core Contract
```

禁止：

```text
OnlyAlpha Core
        ↓
Concrete Market Plugin
```

Core 不允许依赖具体市场 package。

---

# 四、Market Product 属于 Trading Plane，不属于 Universal Runtime

ADR 0068 已经定义：

```text
RESEARCH
BACKTEST
SIM
LIVE
```

必须继续保持：

```text
Research Plane
        ≠
Trading Plane
```

Market Product Plugin 是：

> **Trading Runtime dependency**

所以：

```text
BACKTEST
SIM
LIVE
    require effective Market Product Binding
```

而：

```text
RESEARCH
    does NOT require Market Product Binding
```

Research 可以使用：

```text
Instrument metadata
Calendar
Dataset metadata
Reference metadata
```

但不得为了形式统一加载：

```text
Market Rule
Settlement
Trading Fee Authority
Trading Account
Broker
Durable Trading Kernel
```

不要让 P5.1 的抽象进入 Research Runtime base contract。

---

# 五、P5.1 必须建立一个非常薄的 Core Contract

不要设计：

```text
UniversalMarketFramework
Market DSL
Market Hook Framework
Universal Exchange Capability Graph
```

P5.1 只建立现实需要的最小 contract。

至少需要表达：

```text
Market Product selection
Market Product identity
Market Product factory
Market Product registry
Market Product resolution
Resolved Market Product Binding
Composition identity
Reference authority port
Market policy compiler port
Market fee authority/binding boundary
Canonical configuration identity
```

具体命名可以根据当前 OnlyAlpha naming convention 调整。

所有新的公开类型继续遵守：

```text
Only*
```

前缀规则。

---

# 六、核心类型 1：OnlyMarketProductPluginId

需要一个明确的 Plugin identity。

例如：

```python
OnlyMarketProductPluginId("onlyalpha-market-cn-ashare")
```

它回答：

> 由哪个 Market Product Provider/Plugin 提供这个产品？

不要用：

```text
module path
class repr
Python object id
```

隐式充当 plugin identity。

Plugin identity 必须：

```text
explicit
stable
immutable
canonical
serializable
```

---

# 七、核心类型 2：OnlyMarketProductIdentity

必须独立表达：

> “这是什么 Market Product？”

建议至少能够表达：

```text
product_id
product_version
```

必要时关联：

```text
plugin_id
```

但必须先判断：

```text
Plugin Provider Identity
```

与：

```text
Product Economic Identity
```

是否属于同一层。

不要为了字段少直接揉在一起。

例如：

```text
CN_A_SHARE_CASH@2025.1
```

这是 Product Identity。

但：

```text
哪个 Python package 提供实现
```

可能是 Provider Identity。

必须根据当前 identity architecture 做清晰建模。

---

# 八、Product Identity 不是行为选择器

正式冻结：

> **Market Product Identity is evidence, not behavior selector.**

允许：

```text
logging
artifact metadata
result metadata
audit
fingerprint
compatibility proof
```

禁止：

```python
if product_id == "CN_A_SHARE_CASH":
    ...
```

禁止：

```python
match product_id:
    case "CN_A_SHARE_CASH":
        ...
```

Core 以后不能重新通过 Product ID 恢复具体市场 dispatch。

---

# 九、核心类型 3：OnlyMarketProductConfig

Core 需要一个市场中立的配置入口。

不要让 Core config 长期拥有：

```text
ashare_instruments
ashare_registry
ST
board
price_limit_mode
```

这类 concrete market semantics。

目标模型类似：

```python
@dataclass(frozen=True, slots=True)
class OnlyMarketProductConfig:
    plugin_id: OnlyMarketProductPluginId
    product_id: OnlyMarketProductId
    product_version: OnlyMarketProductVersion
    config: OnlyCanonicalConfigPayload
```

具体字段名结合现有配置体系。

Core 负责：

```text
选择哪个 Plugin
选择哪个 Product
选择哪个 Product Version
传递 canonical plugin-owned config payload
```

Core 不负责理解 payload 的市场语义。

---

# 十、不要让 dict[str, Any] 成为长期 Domain API

配置入口可能来自：

```text
YAML
JSON
Python Mapping
```

但：

```python
dict[str, Any]
```

不能贯穿到 Runtime。

正确边界：

```text
External Config
    ↓
Core canonical config envelope
    ↓
Selected Market Product Factory
    ↓
Plugin-specific typed config
```

例如未来：

```python
OnlyCnAshareProductConfig
```

应该由：

```text
onlyalpha-market-cn-ashare
```

所有。

Core 不认识该类型。

P5.1 只需要把 Contract 设计到足以支持这种模式。

不要在 Core 提前建立 A-share config class。

---

# 十一、核心类型 4：OnlyMarketProductFactory

必须建立一个单一的 Market Product composition entry point。

概念接口：

```python
class OnlyMarketProductFactory(Protocol):
    @property
    def plugin_id(self) -> OnlyMarketProductPluginId:
        ...

    def resolve(
        self,
        config: OnlyMarketProductConfig,
        context: OnlyMarketProductResolutionContext,
    ) -> OnlyResolvedMarketProductBinding:
        ...
```

名字和签名可根据现有工程调整。

但职责必须保持：

```text
Factory
    parse/validate plugin-owned config
    resolve product implementation
    resolve effective authorities
    validate composition compatibility
    return immutable binding
```

Factory 不拥有 Runtime mutable state。

---

# 十二、Factory 不是 Runtime Factory

必须明确两个不同概念：

```text
Market Product Factory
```

负责：

```text
市场产品组合
```

而：

```text
Backtest / Sim / Live Runtime Factory
```

负责：

```text
Runtime Driver + Lifecycle Composition
```

不能合并。

长期关系：

```text
Market Product Factory
        ↓
Resolved Market Product Binding
        ↓
Runtime Factory
        ↓
Trading Runtime
```

Runtime Factory 不再自己拼 concrete market semantics。

---

# 十三、核心类型 5：OnlyMarketProductResolutionContext

Factory 如果解析 Market Product 需要外部资源，必须通过明确 Context/Ports 获得。

不要：

```text
import global registry
read process global singleton
look up Runtime internals
reach into Engine private state
```

Resolution Context 应只暴露 composition-time 所需的最小 capability。

例如可能包括：

```text
resource resolver
canonical configuration environment
reference source binding
fee authority registry
```

具体内容必须根据当前源码真实需求决定。

原则：

> **Resolution Context must expose composition capabilities, not Runtime mutable authorities.**

禁止放入：

```text
OrderManager
PositionManager
AccountManager
RiskManager
ExecutionProcessor
```

---

# 十四、核心类型 6：OnlyResolvedMarketProductBinding

这是 P5.1 最重要的核心对象。

Trading Runtime 以后不应该消费：

```text
A-share registry
A-share compiler
Generic compiler
profile-specific helpers
```

而应该只消费：

```text
OnlyResolvedMarketProductBinding
```

概念：

```python
@dataclass(frozen=True, slots=True)
class OnlyResolvedMarketProductBinding:
    product_identity: OnlyMarketProductIdentity
    reference_authority: OnlyMarketReferenceAuthority
    policy_compiler: OnlyMarketPolicyCompiler
    market_fee_authority: OnlyMarketFeeAuthority
    composition_identity: OnlyMarketProductCompositionIdentity
```

不要机械照抄字段。

必须先审计当前：

```text
Reference
Market Rule
Fee
Settlement
```

的真实边界。

如果某个 Authority 现在不适合直接成为 Binding 字段，应通过合理的 canonical port 表达。

但最终必须满足：

```text
Runtime does not rediscover market composition.
```

---

# 十五、Binding 是 Authority Bundle，不是 God Object

Binding 的职责是：

```text
把已经解析好的 Market Product Authorities
以 immutable composition contract 提供给 Trading Runtime
```

Binding 不允许变成：

```text
万能 Market Service
```

禁止增加：

```python
binding.submit_order(...)
binding.apply_trade(...)
binding.update_position(...)
binding.on_bar(...)
binding.calculate_pnl(...)
```

Binding 应主要持有：

```text
identity
ports
immutable authorities
composition evidence
```

---

# 十六、Binding 必须 Immutable

这是硬性要求。

所有 Binding 及其 identity 必须：

```text
frozen
immutable
thread-safe for read
deterministic
```

Runtime 创建以后：

```text
Market Product Binding
```

不得偷偷替换：

```text
Reference authority
Policy compiler
Fee authority
Product version
```

如果未来需要动态制度版本：

必须通过显式新 Binding/版本化事实处理。

不能 mutate 当前 binding。

---

# 十七、核心类型 7：OnlyMarketProductCompositionIdentity

必须正式区分：

```text
Product Identity
```

和：

```text
Effective Composition Identity
```

Product Identity：

```text
CN_A_SHARE_CASH@2025.1
```

只回答：

> 是什么产品？

Composition Identity 回答：

> 这次 Trading Runtime 实际使用了哪些 Authority？

至少需要考虑：

```text
product identity
reference authority identity
reference authority version/fingerprint
policy compiler identity/version
market fee authority identity/version
effective market config identity
```

具体字段根据当前 architecture 决定。

---

# 十八、Composition Identity 只能基于 Effective Authorities

不能：

```python
fingerprint(raw_yaml)
```

也不能：

```python
fingerprint(config.__dict__)
```

作为正式 economic identity。

必须：

```text
Raw Configuration
        ↓
Resolution
        ↓
Effective Authorities
        ↓
Composition Identity
        ↓
Fingerprint
```

也就是说：

> **只有真正改变 Market Product economic semantics 的配置才能改变 Composition fingerprint。**

无效字段、未使用字段、与当前 Product 无关的数据：

```text
不得影响 composition fingerprint
```

P5.1 至少把这个合同建立正确。

更全面的 canonical hardening 可留给 P5.4。

---

# 十九、Reference Authority Port

必须从第一性原理定义：

> Trading Market Rule Compiler 到底需要什么 Reference capability？

不要直接拿当前：

```text
OnlyAshareReferenceRegistry
```

抽一个 `Protocol` 就结束。

先检查真正需求。

Core contract 应表达：

```text
“给定 Instrument + Trading Day，获得用于 Market Policy Compilation 的权威 Reference”
```

而不是：

```text
“返回 A-share object”
```

概念：

```python
class OnlyMarketReferenceAuthority(Protocol):
    ...
```

具体方法根据现有 Market Rule compiler 的需求设计。

目标是未来：

```text
Generic T0
CN A-share
HK Equity
US Equity
```

都可以实现相同 contract。

---

# 二十、Reference Contract 不应设计成全球市场巨型 DTO

禁止 P5.1 创建：

```text
OnlyUniversalMarketReference
```

然后放：

```text
st
board
hk_board_lot
us_short_sale_flag
crypto_funding_rate
futures_delivery_month
...
```

这属于错误抽象。

Core Contract 应表达：

```text
Kernel / Market Rule compilation 真正需要的标准能力
```

Product-specific facts 可以留在 Plugin 内部。

---

# 二十一、Market Policy Compiler Port

必须定义一个 market-neutral compiler port。

目标：

```text
OnlyMarketRuleEngine
        ↓
OnlyMarketPolicyCompiler
```

而不是：

```text
OnlyMarketRuleEngine
        ↓
profile id
        ↓
if/else
```

概念：

```python
class OnlyMarketPolicyCompiler(Protocol):
    def compile(...):
        ...
```

输入输出必须基于 Core canonical model。

具体市场 compiler 后续：

```text
Generic T0 compiler
CN A-share compiler
```

实现这个 Port。

P5.1 不需要正式迁走这些 compiler，但必须建立正确的 contract。

---

# 二十二、Market Policy Compiler 只负责 Pure Semantics

Compiler 必须尽可能：

```text
pure
deterministic
side-effect free
```

它不允许：

```text
修改 Position
修改 Account
修改 Reservation
提交 Order
发送 Broker command
```

正确关系：

```text
Product-specific facts
        ↓
Compiler
        ↓
Canonical Policy / Instruction
        ↓
Core
```

---

# 二十三、Market Fee Authority Boundary

必须重新审计 Fee 当前实现。

不要简单做：

```python
class OnlyMarketFeeAuthority(Protocol):
    def calculate_fee(...):
```

如果 Core 已经有成熟：

```text
OnlyFeeEngine
OnlyMarketFeePack
OnlyBrokerFeeContract
```

则应该复用现有 Authority。

原则：

```text
Market Product
    provides market fee authority/policy

Core Fee Engine
    executes fee semantics
```

P5.1 只建立 composition boundary。

不要把 Fee Engine 搬进插件。

---

# 二十四、Settlement 不要在 P5.1 重新发明

审计现有 Settlement architecture。

如果当前已经有：

```text
OnlySettlementInstruction
OnlySettlementAuthority
```

则继续复用。

Market Product Contract 只需要确保未来 Plugin 可以提供/编译：

```text
settlement semantics
```

而不是新建：

```text
MarketSettlementManager
```

明确：

```text
Plugin calculates settlement semantics
Core Settlement Authority owns mutation
```

---

# 二十五、Market Rule Authority 与 Execution Support Authority 必须分开

P5.1 不允许重新合并这两个已经正确分离的 Authority。

```text
Market Rule Authority
    市场允许吗？
```

```text
Execution Support Authority
    OnlyAlpha Kernel 实现了吗？
```

Market Product Contract 只能负责前者。

禁止：

```python
factory.supports_execution(...)
plugin.execution_capabilities(...)
```

如果这意味着判断 Kernel 实现情况。

Market Product 不拥有 Execution Support truth。

---

# 二十六、Market Product 与 Risk 必须分开

Market Product 可以定义：

```text
price legality
quantity legality
session legality
settlement semantics
```

不能定义：

```text
max strategy risk
account exposure
risk budget
max position
```

不要让 P5.1 为了“统一 validation”把 Risk 塞进 Market Product Contract。

---

# 二十七、Market Product 与 Broker 必须分开

必须保持三个正交维度：

```text
Market Product
DataSource
Broker
```

Market Product Contract 中禁止：

```text
broker SDK
submit order
cancel order
query broker
broker callback
```

Market Product 不应该 import：

```text
MiniQMT
IB
Binance
Tushare
```

等 concrete SDK。

---

# 二十八、Market Product 与 DataSource 必须分开

DataSource 提供：

```text
Market Data Facts
```

Market Product 提供：

```text
Trading Semantics
```

不能因为某个 DataSource 提供：

```text
ST
board
calendar
```

就让 DataSource 成为市场规则 Authority。

Resolution Context 可以消费已规范化的数据/reference source，但 ownership 必须清楚。

---

# 二十九、Registry 必须极薄

建立：

```text
OnlyMarketProductFactoryRegistry
```

职责只能是：

```text
register factory
require factory
duplicate detection
identity conflict detection
enumeration if needed
```

禁止 Registry：

```text
解析市场配置
编译市场规则
选择 A-share branch
处理 settlement
构造 Runtime
```

Registry 是：

> **Factory lookup authority**

不是：

> Market semantics authority。

---

# 三十、Registry 必须 Fail Closed

以下必须失败：

```text
unknown plugin id
duplicate plugin id with different factory identity
ambiguous registration
invalid factory identity
unsupported product id
unsupported product version
```

禁止：

```text
unknown → Generic
```

禁止：

```text
missing → first registered plugin
```

禁止 silent fallback。

---

# 三十一、P5.1 暂时不要实现复杂动态 Discovery

除非当前 OnlyAlpha 已经有一个非常成熟且天然可复用的统一 plugin discovery contract，否则 P5.1 先采用：

```text
explicit registration
```

即可。

例如 Composition Root：

```text
MarketProductFactoryRegistry
```

显式注册 factory。

目标是先把 ownership/contract 做正确。

不要加入：

```text
hot reload
plugin marketplace
remote plugin
complex dependency negotiation
```

---

# 三十二、配置与 Registry 的关系

最终 Composition path 应是：

```text
OnlyMarketProductConfig
        ↓
plugin_id
        ↓
OnlyMarketProductFactoryRegistry.require(...)
        ↓
OnlyMarketProductFactory.resolve(...)
        ↓
OnlyResolvedMarketProductBinding
```

不要：

```text
Config
→ giant if/else
```

也不要：

```text
Config
→ importlib by arbitrary module string
```

直接实例化未知类。

所有 provider 都经过 Registry。

---

# 三十三、P5.1 暂时如何处理现有 A-share / Generic 路径

本阶段不是正式 migration。

所以不要为了证明新 Contract 强行把全部现有 Runtime 切换到新 Binding。

但必须遵循：

> **不建立永久双路径。**

允许在 P5.1 implementation branch 中：

```text
新 Contract 存在
旧 production composition 仍作为当前实现
```

但：

1. 不要添加 compatibility wrapper。
2. 不要让旧路径依赖新路径再反向 fallback。
3. 不要把双路径标记成长期 public API。
4. 文档明确 P5.2/P5.3 会完成 cutover。
5. 新代码不得继续新增 concrete market dependency。

P5.1 的主要任务是建立未来唯一 contract，而不是假装 migration 已结束。

---

# 三十四、不要提前删除还被当前正式产品真实依赖的 API

P5.1 要保持 clean，但“clean”不等于在 ownership 尚未迁移前破坏 production path。

原则：

```text
No useless compatibility interface
```

不等于：

```text
delete currently authoritative implementation before replacement exists
```

当前仍是正式 Authority 的 API，在 P5.2/P5.3 cutover 前可以存在。

但是：

```text
已经失去职责
纯粹为了新旧兼容
没有生产 owner
```

的接口不得新增或保留。

---

# 三十五、禁止创建 Transitional Abstraction

不要增加：

```text
LegacyMarketProductAdapter
CompatibleMarketProductFactory
AshareMarketProductBridge
GenericMarketFallbackAdapter
P5MarketCompatibilityLayer
```

如果新 Contract 暂时未接入 production path：

就让它独立存在并通过 contract tests 验证。

不要用 adapter 把错误 ownership 包起来。

---

# 三十六、P5.1 必须建立 Architecture Guards

即使 concrete market 尚未迁移，也要开始防止债务继续扩张。

建议新增静态 guard：

> **New Market Product Core contracts may not import concrete market implementations.**

重点针对新模块。

同时可以建立 baseline-aware guard：

```text
Existing known concrete-market debt
    temporarily allowed
```

但：

```text
new concrete-market dependency
    forbidden
```

如果项目已有 architecture/static test framework，沿用现有机制。

不要新建复杂 linter framework。

---

# 三十七、建议新增 Contract Test Provider

P5.1 不需要真实 Generic/A-share 插件，但应该用 tests 内的 Fake/Test Market Product Factory 证明 Contract。

例如：

```text
OnlyTestMarketProductFactory
```

返回：

```text
OnlyResolvedMarketProductBinding
```

使用 fake immutable：

```text
Reference Authority
Policy Compiler
Fee Authority
Composition Identity
```

测试重点是：

```text
contract
registry
resolution
identity
```

不是市场业务语义。

---

# 三十八、Registry Contract Tests

至少测试：

```text
register one factory
require returns exact authority

unknown id → fail

duplicate identical registration
    根据现有 registry philosophy 决定是否 idempotent，
    必须有明确语义

duplicate conflicting registration → fail closed

factory identity mismatch → fail

registration order does not affect resolution semantics
```

不要使用“最后注册覆盖前一个”的行为。

---

# 三十九、Factory Contract Tests

至少测试：

```text
same config + same context
→ semantically equivalent binding

invalid product id
→ fail

unsupported version
→ fail

invalid plugin-specific config
→ fail

missing required resolution authority
→ fail

ambiguous resolution
→ fail
```

Factory 不能返回：

```text
None and hope Runtime handles it
```

unsupported/invalid 必须通过明确异常。

---

# 四十、Binding Contract Tests

至少测试：

```text
binding immutable

identity immutable

binding cannot mutate authorities

binding has deterministic semantic identity

same effective authorities
→ same composition identity

different effective authority version
→ different composition identity
```

不要只测试：

```text
dataclass equality
```

要测试经济 identity contract。

---

# 四十一、Composition Identity Tests

需要证明：

```text
same product
same effective authorities
same effective config
→ same fingerprint
```

以及：

```text
authority version changes
→ fingerprint changes
```

并区分：

```text
raw config
```

与：

```text
effective composition
```

P5.1 不一定完成所有 canonical hardening，但必须让 API 不依赖：

```text
repr()
object id
memory address
unordered dict iteration
```

---

# 四十二、Canonical Identity 不要产生第二套实现

如果 OnlyAlpha 当前已有 canonical fingerprint/helper：

优先复用。

不要建立：

```text
market_product_canonicalize()
```

和已有 canonical system 平行。

如果已有系统存在明显问题：

```text
arbitrary __str__ fallback
```

本阶段可以只保证新 P5.1 identity 不依赖该 fallback，或者做最小必要修复。

全仓 identity hardening 属于 P5.4，除非不修就无法正确建立 Contract。

---

# 四十三、异常模型必须清晰

不要大量使用：

```python
ValueError("bad")
```

如果当前工程已有 architecture/domain exception 风格，继续遵守。

建议至少能区分：

```text
Unknown Market Product Plugin

Duplicate Market Product Plugin

Unsupported Market Product

Unsupported Product Version

Invalid Market Product Configuration

Market Product Resolution Failure

Market Product Authority Conflict
```

不要为每一种小错误创建几十个 exception class。

但错误语义必须能够 fail closed 和测试。

---

# 四十四、不要在 Contract 里泄漏 Runtime Mode

P5.1 建立的新 Market Product Contract 不应该依赖：

```text
OnlyRuntimeMode
```

来决定经济行为。

禁止：

```python
factory.resolve(config, runtime_mode)
```

仅仅因为：

```text
Backtest
Sim
Live
```

不同就选择不同 Market semantics。

Runtime Driver 差异不属于 Market Product Contract。

如果 Resolution Context 中确实发现某个当前代码需要 Runtime Mode：

必须重新判断：

> 它到底是市场规则输入，还是旧架构泄漏？

默认应视为泄漏。

---

# 四十五、不要让 Binding 暴露 Runtime Mode

Binding 描述：

```text
Market Product economic composition
```

不是：

```text
Runtime environment
```

因此 Binding identity 不应该包含：

```text
BACKTEST
SIM
LIVE
```

后续 P5.3 会处理中立化 Market Rule identity。

P5.1 新设计从一开始就不要引入该耦合。

---

# 四十六、不要把 Research Contract 混入 Binding

禁止：

```text
research indicators
factor engine
research dataset
web artifact
```

进入：

```text
OnlyResolvedMarketProductBinding
```

P5.1 是 Trading Plane composition。

Research 继续完全独立。

---

# 四十七、Public API 原则

新 Contract 哪些应该 public，必须谨慎。

建议 public 的仅是未来具体 Market Plugin 必须依赖的稳定 contract，例如：

```text
Factory Protocol
Config envelope
Identity types
Binding contract
Reference/Policy ports
Registry API if third-party registration needs
```

内部 composition helper 不要全部 export。

遵守：

> **Public API is a contract, not a convenience barrel.**

不要为了测试方便全部放进：

```python
onlyalpha.market.__init__
```

---

# 四十八、模块组织原则

不要把所有东西塞进：

```text
market/product.py
```

一个大文件。

也不要为了“模块化”拆成二十个只有十行的模块。

建议按真实职责组织，例如：

```text
src/onlyalpha/market/product/
    identity.py
    config.py
    contracts.py
    binding.py
    registry.py
    errors.py
```

或者结合现有 `market/` 结构选择更自然的位置。

模块边界应该体现：

```text
Identity
Contract
Binding
Registry
```

而不是具体市场。

---

# 四十九、代码质量要求

所有新增代码必须：

```text
typed
immutable where appropriate
minimal mutable state
no global side effect
no import side effect registration
no hidden fallback
no duplicate authority
no circular dependency hack
no TYPE_CHECKING abuse to hide bad layering
```

如果出现 circular import：

不要通过：

```text
late import everywhere
```

掩盖。

重新检查 ownership/模块方向。

---

# 五十、不要过度抽象

P5.1 只有两个目标消费者：

```text
P5.2 Generic T0
P5.3 CN A-share
```

Contract 必须能够支持它们。

不要提前为：

```text
options
FX
multi-leg derivatives
prediction markets
exotic settlement
```

设计复杂 extension mechanism。

原则：

> **Design for known semantic variation, leave room for extension, do not encode imaginary requirements.**

---

# 五十一、P5.1 不允许修改的核心区域

原则上不要改变：

```text
ExecutionProcessor economic semantics
Transaction Planner
Transaction Coordinator
Projection ordering
Position calculation
Allocation calculation
Account calculation
Strategy Ledger calculation
Risk reservation lifecycle
Virtual Broker matching
Recovery model
```

P5.1 是 Composition Contract。

如果你发现需要修改：

```text
Fill
PnL
Position mutation
Account mutation
```

才能实现 Market Product Contract：

说明抽象边界错了。

重新设计。

---

# 五十二、P5.1 不实现 Generic T0 正式迁移

不要在本任务中把：

```text
GENERIC_T0
```

全面迁出 Core。

那是 P5.2。

可以建立 Test Factory 来验证 Contract。

不要为了提前完成 P5.2 扩大当前任务。

---

# 五十三、P5.1 不实现 CN A-share 正式迁移

不要在本任务中完成：

```text
OnlyAshareReferenceRegistry migration
ashare_rules migration
Backtest A-share routing deletion
Paper A-share routing deletion
```

这些属于 P5.3。

但是：

> **新 Contract 设计时绝对不能依赖这些 concrete A-share 类型。**

---

# 五十四、P5.1 不实现 P6/P7/P8

禁止顺手实现：

```text
SIM
PAPER deletion
SHADOW deletion

Research vectorized runtime

Indicator dual backend

Durable broker outbound

Broker reconciliation

Live Runtime
```

这些全部是后续阶段。

---

# 五十五、文档要求

P5.1 完成后，根据实际实现更新：

```text
AGENTS.md
docs/architecture.md
docs/roadmap.md
```

如果 README 的 Current Implementation Fact 需要更新，做最小修改。

不要宣称：

```text
Market Product Plugin migration completed
```

因为 Generic/A-share 尚未 cutover。

应该准确描述：

```text
P5.1 Core Market Product Contract established

Concrete product migration remains P5.2/P5.3
```

---

# 五十六、是否需要新增 ADR

先检查当前 ADR。

如果：

```text
Market Product Plugin + Resolved Binding
```

属于对现有 ADR 无法自然覆盖的新长期架构决策：

新增一个 ADR。

不要为了完成任务机械创建 ADR。

如果新增，ADR 应回答：

```text
Why Market Product is a plugin/composition authority

Why Core cannot know concrete markets

Why Binding is immutable

Why Product ID is evidence only

Why Research does not require it

Why Plugin cannot mutate trading authorities

Why Registry is explicit/fail-closed
```

不要把实现细节复制成 ADR。

---

# 五十七、Architecture Guard 要明确未来目标

至少在 AGENTS/architecture guard 中冻结：

```text
No new concrete-market branch in Core.

No Core dependency on concrete market packages.

Market Product ID is not a behavior selector.

Market Product Plugin cannot own mutable Trading Authorities.

Research does not require Market Product Plugin.

No implicit Generic Market fallback.

Runtime Type does not belong to Market Product economic contract.
```

当前历史 debt 可以由后续 P5.2/P5.3 消除。

但从 P5.1 开始禁止新增。

---

# 五十八、验证命令

必须先阅读当前：

```text
AGENTS.md
CI
scripts/test_suite.py
pyproject.toml
```

使用仓库真实质量命令。

至少执行适用的：

```bash
uv run ruff check src tests examples packages scripts
uv run ruff format --check src tests examples packages scripts
uv run mypy src/onlyalpha
```

新增 package 时也必须进入相应 lint/type/build 范围。

运行当前适用测试 lane。

至少确保：

```text
existing core tests
new Market Product contract tests
registry tests
binding tests
identity tests
```

PASS。

最后：

```bash
git diff --check
```

---

# 五十九、必须执行静态依赖审计

对 P5.1 新增模块执行：

```bash
rg -n 'Ashare|CN_A_SHARE|XSHG|XSHE|ashare_rules' <new market product core contract paths>
```

结果必须为：

```text
0 concrete-market behavioral dependency
```

同时检查新 Contract 不依赖：

```text
runtime.paper
runtime.backtest
miniqmt
tushare
```

等 concrete runtime/provider。

---

# 六十、测试至少覆盖以下场景

必须包含：

1. 注册一个 Test Market Product Factory。
2. 使用 `plugin_id` 成功解析。
3. 返回 immutable Binding。
4. 相同 effective config 得到相同 identity。
5. 不同 product version 产生不同 product/composition identity。
6. 不同 reference authority identity 导致 composition identity 变化。
7. unknown plugin fail closed。
8. unsupported product fail closed。
9. unsupported version fail closed。
10. duplicate/conflicting registration fail closed。
11. invalid plugin config fail closed。
12. Binding 不持有任何 Runtime mutable manager。
13. Market Product Contract 不依赖 Runtime Mode。
14. Registry registration order 不改变选定 Factory 的语义。
15. 当前已有 Backtest 产品未因新增 Contract 出现回归。

---

# 六十一、P5.1 Definition of Done

只有全部满足才能结束。

## First-principles ownership

```text
[ ] Market Product Composition Authority 的职责已经唯一明确

[ ] Market Product 与 Broker/DataSource/Risk/Execution 的边界清楚

[ ] Market Product 明确属于 Trading Plane

[ ] Research 不依赖 Market Product Contract
```

## Core Contract

```text
[ ] Market Product Plugin/Provider identity 已建立

[ ] Market Product Identity 已建立

[ ] Market Product Config envelope 已建立

[ ] Market Product Factory Contract 已建立

[ ] Market Product Resolution Context 已建立或明确证明不需要

[ ] Resolved Market Product Binding 已建立

[ ] Market Product Composition Identity 已建立

[ ] Reference Authority Port 已建立

[ ] Market Policy Compiler Port 已建立

[ ] Market Fee composition boundary 已明确
```

## Registry

```text
[ ] Market Product Factory Registry 已建立

[ ] Registry 极薄

[ ] unknown plugin fail closed

[ ] conflicting registration fail closed

[ ] 无 implicit fallback
```

## Identity

```text
[ ] Product Identity 与 Composition Identity 分离

[ ] Binding identity deterministic

[ ] Composition identity 基于 effective authorities

[ ] Runtime Mode 未进入新 Market Product economic contract

[ ] Product ID 只能作为 evidence
```

## Architecture

```text
[ ] Core contract 不 import concrete market implementation

[ ] 没有新增 A-share/Generic-specific branch

[ ] 没有万能 hook interface

[ ] 没有 Runtime Manager capability 泄漏进 Factory/Binding

[ ] 没有 Broker/DataSource SDK 泄漏进 Market Product Contract
```

## Clean code

```text
[ ] 没有 compatibility adapter

[ ] 没有 deprecated alias

[ ] 没有 duplicate composition authority

[ ] 没有 hidden fallback

[ ] 没有 global registration side effect

[ ] 没有为了解决循环依赖引入脏 hack
```

## Tests

```text
[ ] Registry contract tests PASS

[ ] Factory contract tests PASS

[ ] Binding tests PASS

[ ] Composition identity tests PASS

[ ] Test Market Product Provider works

[ ] Current production tests remain PASS
```

## Docs

```text
[ ] AGENTS 当前工程合同已更新

[ ] architecture 当前实现边界已更新

[ ] roadmap 正确标记 P5.1 完成边界

[ ] 未错误声明 P5.2/P5.3 已完成
```

---

# 六十二、P5.1 完成后应该得到什么

完成前：

```text
Concrete Market Logic
        scattered
```

完成 P5.1 后：

```text
                Core Market Product Contract
                          │
            ┌─────────────┼─────────────┐
            │             │             │
        Identity       Factory       Binding
                          │
                       Registry
```

此时 concrete product 还没有完全迁移。

这是允许的。

但是未来迁移的方向已经唯一：

```text
Generic T0
        ↓
implement Market Product Contract
        ↓
P5.2

CN A-share
        ↓
implement Market Product Contract
        ↓
P5.3
```

不能再出现第二种 composition architecture。

---

# 六十三、P5.1 完成后禁止留下的设计疑问

任务结束前，代码和文档必须能够明确回答：

```text
谁选择 Market Product？
    → Config + Registry

谁创建 Market Product implementation？
    → Market Product Factory

谁拥有 concrete market knowledge？
    → Concrete Market Product Plugin

谁给 Runtime 提供已经解析好的市场 Authority？
    → Resolved Market Product Binding

谁拥有 mutable Trading State？
    → Trading Runtime Core Authorities

谁决定 Market legality？
    → Market Product Policy Authority

谁决定 Kernel 是否支持？
    → Execution Support Authority

谁决定 Risk？
    → Risk Authority

谁决定 Broker communication？
    → Broker Plugin

Research 是否加载 Market Product？
    → No
```

任何答案如果仍然是：

```text
看 profile 然后 if/else
```

说明 Contract 设计不合格。

---

# 六十四、最终输出要求

完成后输出一个 P5.1 完整实施报告。

必须包括：

```text
1. Current architecture facts inspected

2. First-principles problem definition

3. Final ownership model

4. New Core Market Product contracts

5. Identity model

6. Factory model

7. Registry model

8. Resolved Binding model

9. Reference/Policy/Fee boundaries

10. Research/Trading boundary

11. Dependency direction

12. Architecture guards

13. Tests added

14. Validation commands/results

15. Existing concrete-market debt intentionally retained for P5.2/P5.3

16. APIs deliberately NOT added

17. Remaining risks before P5.2
```

不要只列修改文件。

必须解释：

> **为什么现在的 Contract 足够支持 Generic T0、CN A-share 和未来第三个市场，而不会把 concrete market knowledge重新泄漏到 Core。**

---

# 六十五、最终工程原则

整个 P5.1 必须始终遵守：

```text
Architecture before convenience.

Authority before helper.

One responsibility → one owner.

Core defines contracts.

Plugin owns concrete market semantics.

Binding carries resolved authority.

Registry only resolves factories.

Product identity is evidence.

Runtime type is not market semantics.

Plugin calculates; Core mutates.

Market Rule Authority != Execution Support Authority.

Market Product != Risk.

Market Product != Broker.

Market Product != DataSource.

Research does not depend on Trading Market Product.

Unknown / ambiguous → fail closed.

No implicit fallback.

No compatibility shim.

No duplicate path.

No speculative universal framework.

No concrete-market leakage into new Core Contract.

No changes to durable trading economics.
```

最终判断 P5.1 是否成功，只问一个问题：

> **如果下一步要实现 `onlyalpha-market-generic-t0-cash` 和 `onlyalpha-market-cn-ashare`，它们是否只需要实现这套固定 Contract，而不需要修改这套 Contract 来加入 `if Generic` 或 `if A-share`？**

如果答案不是明确的“是”，说明 P5.1 仍未完成。
