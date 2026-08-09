# Codex Prompt — P2.1 Reconciliation Composition Stabilization

## 任务名称

**P2.1 — Reconciliation Composition Stabilization**

中文：

**P2.1：费用对账治理 Authority 组合层收口**

目标仓库：

```text
https://github.com/zongxin1993/OnlyAlpha
```

当前规划基线：

```text
f57664d9236cb97bbcf81f0e8a4a795f795c62f8
Feat: Fee Reconciliation Semantic Closure
```

开始实现前必须重新读取最新 `master`。

如果最新 `master` 已经前进：

1. 以最新 `master` 为唯一实现基线；
2. 重新审计本 Prompt 涉及的代码；
3. 已经被正确解决的问题不得重复实现；
4. 不得为了套用本 Prompt 而恢复已经删除的旧接口；
5. 最终 Implementation Report 必须记录：

   * Prompt baseline；
   * actual implementation baseline；
   * baseline difference；
   * 哪些工作已由后续提交提前完成。

---

# 1. 任务定位

P2 已经完成：

```text
Versioned Reconciliation Policy
Typed Evidence Scope
Typed Statement Scope
Component-by-Component Reconciliation
Component-aware Adjustment
Evidence Revision / Lineage
Forward Correction
Active Blocker Set
Market-neutral Risk Change Classification
Broker Fee Evidence Port
Durable Recovery
```

因此 P2.1 **不是 P2 的第二次业务重构**。

P2.1 只处理 P2 完成后暴露出来的 Composition / Provisioning 不一致。

核心问题是：

```text
Domain Authority 已经正确

但

Authority 安装、选择、能力声明和文档暴露
还没有完全统一
```

---

# 2. 第一性原则

本任务必须从以下原则出发。

## 2.1 Runtime 只能选择 Authority，不能创造 Authority

如果一个对象会影响：

```text
资金
费用
交易权限
风险阻塞
经济决策
```

并且它拥有：

```text
ID
Version
Fingerprint
```

那么它就是正式 Authority。

正式 Authority 应由：

```text
Composition Root
        ↓
Registry
        ↓
Runtime exact selection
```

安装。

不能：

```text
Backtest Factory
    临时创建 Authority

Paper Factory
    再创建一份 Authority

Live Factory
    将来再复制一次
```

因此：

> **Runtime Factory 负责 resolve，不负责 define/register economic authority。**

---

# 3. Authority Definition 与 Authority Selection 必须分离

正确结构：

```text
Authority Definition
        ↓
Composition Root Installation
        ↓
Registry
        ↓
Config Reference
        ↓
Runtime Selection
```

错误结构：

```text
Config
        ↓
Runtime Factory
        ↓
Factory 临时构造一份刚好满足 Config 的 Authority
```

后者会导致：

```text
配置看起来支持任意 policy_id/version

但实际上 Runtime 只能创建源码硬编码的 Policy
```

这是必须消除的假能力。

---

# 4. 相同 Identity 必须对应唯一经济 Authority

当前 Reconciliation Policy 包含：

```text
policy_id
policy_version
currency
materiality_threshold
actions
fingerprint
```

如果：

```text
STANDARD@1 / CNY
```

与：

```text
STANDARD@1 / USD
```

拥有不同：

```text
currency
threshold economic meaning
fingerprint
```

那么它们不能继续共享模糊：

```text
(policy_id, policy_version)
```

Registry Identity。

原则：

> **Authority Key 必须包含所有决定 Authority 唯一性的维度。**

---

# 5. Capability Declaration 与实际 Port 必须一致

Broker 声明：

```text
我支持 QUERY_FEE_EVIDENCE
```

意味着：

```text
对应的正式 Fee Evidence Port
必须真实存在并满足 Contract
```

反过来：

```text
对象上碰巧存在 query_fee_evidence()
```

不意味着 Runtime 可以偷偷使用它。

原则：

```text
Capability
+
Port Contract
=
可用产品能力
```

两者必须同时成立。

---

# 6. 文档也是产品 Contract

README / Roadmap 不允许描述：

```text
源码实际上不支持的能力
```

例如：

```text
测试 Fee Pack
```

不能写成：

```text
正式 A 股税费已完成
```

Conformance / Domain Foundation 不能写成：

```text
正式 Futures Durable Product
```

P2.1 必须校准这些能力声明。

---

# 7. P2.1 的核心目标

本任务只完成以下内容：

```text
A. Reconciliation Policy Registry 进入统一 Composition Root

B. Backtest/Paper Factory 删除临时 Policy Registry 和 Policy 注册逻辑

C. Reconciliation Policy Identity / Registry Key 纳入 Currency

D. Config 真正能够选择 Registry 中安装的 Policy

E. Custom Policy 可以通过 Component Registry 注入而无需修改 Runtime Factory

F. Broker Fee Evidence Port 与 Broker Capability 模型闭合

G. Capability 与实际 Optional Port Contract 可验证

H. MiniQMT 未实现 Fee Evidence 时准确声明“不支持”

I. README / Roadmap / Version / Product Capability 描述与源码一致

J. 增加 Architecture Guards，防止 Factory-owned Authority 再次出现
```

---

# 8. 明确非目标

P2.1 严禁实现：

```text
正式中国 A 股 Market Fee Pack

真实印花税参数

真实过户费参数

真实券商佣金 Contract

真实 MiniQMT Fee Evidence Query

真实 Statement 拉取

Broker 网络轮询

Broker Fee Evidence Push

Paper Reconnect

Paper Streaming Checkpoint

Paper Recovery

A-share Durable Execution Capability

Live Runtime

Durable Outbound Broker Command

Account Cash Deficit / Fee Debt

Multi-Account Runtime

Multi-Broker Runtime

FX Conversion

Futures Product

Crypto Product

Vectorized Backtest
```

发现这些问题：

```text
记录 technical debt
```

不要扩 Scope。

---

# 9. 禁止重新设计 P2 Domain

以下 P2 已完成的边界原则上必须冻结：

```text
OnlyExternalFeeEvidence

Typed Trade / Order / Statement Scope

OnlyFeeReconciliationPlanner

Component Reconciliation

Evidence Revision / Lineage

Forward Correction

OnlyFeeAdjustment

Active Blocker Set

Risk Change Classification

FEE_RECONCILIATION Durable Transaction

Recovery semantics
```

除非测试发现真实 correctness bug，否则不要改。

尤其禁止：

```text
重新设计 Evidence
重新设计 Blocker
重新设计 Component Identity
重新设计 Forward Correction
重新设计 Transaction Coordinator
```

---

# 10. 禁止兼容旧错误结构

OnlyAlpha 当前仍处 Alpha。

如果正确结构要求删除旧接口：

> **直接删除。**

禁止新增：

```text
LegacyReconciliationPolicyRegistry

CompatReconciliationPolicyIdentity

PolicyIdentityV1Adapter

OldPolicyKey

RuntimeLocalPolicyRegistry

DefaultPolicyFallback

ImplicitCurrencyPolicy

LegacyBrokerCapabilityAdapter

FeeEvidencePortCompat

DeprecatedPolicyResolver
```

禁止：

```python
try:
    new_registry.require(...)
except:
    create_standard_policy(...)
```

禁止：

```text
Custom Policy 找不到
→ 自动 STANDARD
```

禁止：

```text
Currency-specific Policy 找不到
→ 使用相同 id/version 的其他币种
```

全部 Fail Closed。

---

# 11. Pre-Implementation Audit

开始修改前必须完成一次正式只读审计。

至少检查：

```text
src/onlyalpha/fee/reconciliation_policy.py

src/onlyalpha/config/models.py

src/onlyalpha/runtime/assembler.py
src/onlyalpha/runtime/defaults.py

src/onlyalpha/runtime/backtest/factory.py
src/onlyalpha/runtime/paper/factory.py
src/onlyalpha/runtime/live/factory.py

src/onlyalpha/broker/ports.py
src/onlyalpha/broker/capabilities.py
src/onlyalpha/broker/enums.py
src/onlyalpha/broker/factory.py

src/onlyalpha/plugin/
packages/fake/
packages/provider/onlyalpha-plugin-miniqmt/

tests/fee/
tests/runtime/
tests/plugin/
tests/architecture/

README.md
docs/roadmap.md
pyproject.toml
```

搜索：

```text
OnlyFeeReconciliationPolicyRegistry

only_standard_fee_reconciliation_policy

fee_reconciliation_policy

OnlyComponentFactoryRegistries

OnlyBrokerFeeEvidencePort

OnlyBrokerCapability

query_fee_evidence

STANDARD_FEE_RECONCILIATION

Version 0.3.3

基础佣金

印花税

过户费

期货 LONG/SHORT
```

输出：

```text
docs/reports/
p2_1_reconciliation_composition_pre_implementation_audit.md
```

报告至少说明：

```text
当前 Policy 安装路径

Backtest Policy Resolve Path

Paper Policy Resolve Path

Current Registry ownership

Policy Identity fields

Current Registry key

Policy persistence locations

Broker Fee Evidence Port location

Broker capability model

MiniQMT current capabilities

README / Roadmap factual mismatches

需要删除的临时 Composition 代码
```

---

# 12. 第一项改造：统一 Reconciliation Policy Registry

当前：

```text
Market Fee Pack
    → central registry

Broker Fee Contract
    → central registry

Fee Basis Provider
    → central registry

Reconciliation Policy
    → Runtime Factory local registry
```

必须改成：

```text
Market Fee Pack
Broker Fee Contract
Fee Basis Provider
Reconciliation Policy

全部
        ↓
Composition Root
```

---

# 13. 修改 OnlyComponentFactoryRegistries

新增正式字段：

```python
@dataclass(frozen=True, slots=True)
class OnlyComponentFactoryRegistries:
    data_sources: OnlyDataSourceFactoryRegistry
    brokers: OnlyBrokerFactoryRegistry
    clusters: OnlyClusterFactory

    market_profiles: OnlyMarketProfileRegistry
    market_rule_compiler: OnlyMarketRuleCompiler

    market_fee_packs: OnlyMarketFeePackRegistry
    broker_fee_contracts: OnlyBrokerFeeContractRegistry
    fee_basis_providers: OnlyFeeBasisProviderRegistry
    fee_reconciliation_policies: OnlyFeeReconciliationPolicyRegistry

    runtime_persistence_stores: OnlyRuntimePersistenceStoreFactory
```

字段顺序根据项目风格调整。

重点是：

```text
Reconciliation Policy Registry
```

成为正式 Component Registry。

---

# 14. Central Composition Root 安装 Policy

修改：

```text
src/onlyalpha/runtime/defaults.py
```

在：

```python
only_default_engine_services()
```

中创建：

```python
reconciliation_policies = OnlyFeeReconciliationPolicyRegistry()
```

然后注册正式 built-in policies。

最终：

```text
OnlyComponentFactoryRegistries(
    ...
    fee_reconciliation_policies=reconciliation_policies,
)
```

---

# 15. Runtime Default 才是 built-in Authority 安装位置

Built-in Authority 定义可以存在：

```text
fee/reconciliation_policy.py
```

但：

```text
谁被正式安装进默认 Engine
```

必须由：

```text
runtime/defaults.py
```

Composition Root 决定。

Runtime Factory 不得自行注册。

---

# 16. 删除 Backtest Factory 本地 Registry

彻底删除类似：

```python
reconciliation_policies = OnlyFeeReconciliationPolicyRegistry()

reconciliation_policies.register(
    only_standard_fee_reconciliation_policy(
        account.initial_cash.currency
    )
)
```

以及对应 import。

Backtest Factory 只能：

```text
读取 Config

从 Component Registry require

验证 compatibility

inject Runtime
```

---

# 17. 删除 Paper Factory 本地 Registry

Paper Factory 同样处理。

最终：

```text
Backtest
Paper
Future Live
```

不得分别拥有不同 Policy installation logic。

---

# 18. Factory 不允许 import Built-in Policy Constructor

Architecture Guard 应禁止：

```text
runtime/backtest/factory.py
runtime/paper/factory.py
runtime/live/factory.py
```

直接 import：

```text
only_standard_fee_reconciliation_policy
```

Factory 不需要知道哪个 Policy 是：

```text
STANDARD
STRICT
SIMULATION
```

它只知道：

```text
Config 指向哪个 identity
```

---

# 19. 第二项改造：Policy Identity Currency Closure

当前：

```python
OnlyFeeReconciliationPolicyIdentity:
    policy_id
    policy_version
    fingerprint
```

应重新评估并正式升级为：

```python
@dataclass(frozen=True, slots=True)
class OnlyFeeReconciliationPolicyIdentity:
    policy_id: str
    policy_version: str
    currency: OnlyCurrency
    fingerprint: str
```

---

# 20. 为什么 Currency 必须进入 Identity

以下两个 Policy：

```text
STANDARD@1
threshold = 0.10 CNY
```

和：

```text
STANDARD@1
threshold = 0.10 USD
```

不是同一个经济 Authority。

即使：

```text
policy_id 相同
version 相同
threshold numeric 相同
```

经济含义不同。

所以：

```text
Currency
```

不是普通 Payload Metadata。

它属于：

```text
Authority Identity Dimension
```

---

# 21. Registry Key 必须修改

当前：

```python
(policy_id, policy_version)
```

升级成：

```python
(
    policy_id,
    policy_version,
    currency,
)
```

或者使用强类型 key model。

例如：

```python
@dataclass(frozen=True, slots=True)
class OnlyFeeReconciliationPolicyKey:
    policy_id: str
    policy_version: str
    currency: OnlyCurrency
```

优先选择和当前项目 Registry 风格最一致的方式。

不要为这一项过度抽象。

---

# 22. require() API

建议：

```python
require(
    policy_id: str,
    policy_version: str,
    currency: OnlyCurrency,
) -> OnlyFeeReconciliationPolicy
```

必须 exact match。

禁止：

```text
找不到 CNY
→ 找 STANDARD@1 任意 Currency
```

---

# 23. Policy Fingerprint

继续包含：

```text
policy_id
policy_version
currency
threshold
actions
```

确保：

```text
same identity
+
different payload
```

产生：

```text
FEE_RECONCILIATION_POLICY_FINGERPRINT_CONFLICT
```

---

# 24. Identity Fingerprint Invariant

必须验证：

```text
identity.currency == policy.currency
```

并确保：

```text
identity.fingerprint == policy.fingerprint
```

不要允许构造：

```text
Identity CNY
+
Policy USD
```

---

# 25. Config 不需要重复 Currency

当前 Account 已有：

```text
initial_cash.currency
```

且当前产品仍是 Single-currency Account。

所以 Config 可以继续：

```yaml
fee_reconciliation_policy:
  policy_id: STANDARD_FEE_RECONCILIATION
  policy_version: "1"
```

Runtime Resolution Key：

```text
policy_id
+
policy_version
+
account currency
```

---

# 26. 不要新增冗余 Config Currency

禁止：

```yaml
fee_reconciliation_policy:
  policy_id: ...
  policy_version: ...
  currency: CNY
```

如果 Currency 已经由 Account Authority 唯一确定。

否则会出现两个 Currency Authority：

```text
Account Currency
vs
Policy Config Currency
```

不必要。

---

# 27. Current Single-Currency Assumption

P2.1 应明确：

```text
Policy Currency
==
Account Currency
```

这是当前产品 invariant。

未来 Multi-currency Account：

```text
另行设计
```

不要提前复杂化。

---

# 28. Built-in Standard Policy

重新设计：

```python
only_standard_fee_reconciliation_policy(currency)
```

的使用方式。

该函数可以继续作为：

```text
Authority Definition Factory
```

但不能由 Runtime Factory 调用。

例如中央 Composition Root：

```python
reconciliation_policies.register(
    only_standard_fee_reconciliation_policy(
        OnlyCurrency("CNY")
    )
)
```

---

# 29. 当前只注册经过验证的 Currency

如果当前系统产品化只验证了：

```text
CNY
```

那么默认 Registry 只注册：

```text
STANDARD_FEE_RECONCILIATION@1/CNY
```

不要：

```python
for currency in every ISO currency:
    ...
```

一个 Authority 被安装就代表：

> 默认 Engine 正式声明它是受支持配置。

不要虚假扩展 Capability。

---

# 30. USD 等未安装 Policy 必须 Fail Closed

测试：

```text
Account:
USD

Config:
STANDARD@1

Default Registry:
only CNY
```

必须：

```text
FEE_RECONCILIATION_POLICY_NOT_INSTALLED
```

不能动态生成 USD Policy。

---

# 31. Custom Policy 必须真正可注入

这是 P2.1 判断 Composition 是否正确的关键测试。

创建 Test Registry：

```text
CUSTOM_STRICT@1/CNY
```

配置：

```text
policy_id = CUSTOM_STRICT
policy_version = 1
```

Backtest Factory 必须：

```text
resolve custom policy
```

而无需：

```text
修改 Backtest Factory 源码
```

Paper 同样。

这证明 Config 的：

```text
policy_id/version
```

是真的 Dependency Selection，而不是装饰字段。

---

# 32. Backtest/Paper Policy Parity

对于相同：

```text
Component Registry
Account
Policy Config
```

Backtest 和 Paper 必须解析到：

```text
same OnlyFeeReconciliationPolicyIdentity
same fingerprint
```

Runtime Mode 不应该改变 Governance Authority。

---

# 33. Persistence / Schema Audit

由于：

```text
OnlyFeeReconciliationPolicyIdentity
```

已经进入：

```text
OnlyFeeReconciliationDecision
```

并参与持久化，因此增加 Currency 是 breaking serialized-contract change。

必须审计：

```text
Decision Codec
Runtime Transaction Projection Payload
Checkpoint
Artifact
Result
Tests
```

---

# 34. 该升级 Schema 就升级

如果：

```text
OnlyFeeReconciliationDecision
```

serialized payload 因 Currency Identity 发生变化：

```text
schema_version++
```

旧 schema：

```text
Fail Closed
```

不要 compatibility migration。

---

# 35. 不要无意义升级 Transaction Envelope

如果：

```text
PreparedRuntimeTransaction
CommittedRuntimeTransaction
```

generic envelope 未改变：

```text
不要升级
```

只升级真实变化的：

```text
Projection payload
Decision schema
Artifact schema
```

---

# 36. 第三项改造：Broker Fee Evidence Capability Alignment

P2 已建立：

```python
OnlyBrokerFeeEvidencePort
```

该 Port 返回：

```text
tuple[OnlyExternalFeeEvidence, ...]
```

这是正确 Domain Boundary。

P2.1 不重新设计。

---

# 37. 增加 QUERY_FEE_EVIDENCE Capability

在：

```text
OnlyBrokerCapability
```

增加：

```python
QUERY_FEE_EVIDENCE = "QUERY_FEE_EVIDENCE"
```

只增加目前已经有 Port 对应的 Pull 能力。

不要提前增加：

```text
PUSH_FEE_EVIDENCE
```

除非当前代码已有真实 Push Boundary。

---

# 38. Fee Evidence 应保持 Optional Capability

不要简单修改：

```python
class OnlyBrokerGateway(
    ...
    OnlyBrokerFeeEvidencePort,
)
```

如果这样会强迫：

```text
所有 Broker
```

必须实现 Fee Evidence。

这不符合 Capability 模型。

推荐结构：

```text
OnlyBrokerGateway
    ├── mandatory core ports
    │
    └── optional capability ports
             └── OnlyBrokerFeeEvidencePort
```

---

# 39. Optional Port 的使用必须类型安全

禁止生产代码散布：

```python
if hasattr(gateway, "query_fee_evidence"):
```

建议建立一个统一 resolver，例如：

```python
def only_require_broker_fee_evidence_port(
    gateway: OnlyBrokerGateway,
) -> OnlyBrokerFeeEvidencePort:
    ...
```

或按照现有 Broker Architecture 使用等价设计。

---

# 40. Optional Port Resolver 必须验证两件事

第一：

```text
Broker capabilities
包含 QUERY_FEE_EVIDENCE
```

第二：

```text
Gateway object
真实满足 Fee Evidence Port
```

二者缺一不可。

---

# 41. Capability 声明但没有实现

场景：

```text
Broker capabilities:
QUERY_FEE_EVIDENCE
```

但是：

```text
gateway.query_fee_evidence
不存在
```

必须：

```text
BROKER_CAPABILITY_CONTRACT_INVALID
```

或项目现有同义 typed error。

Fail Closed。

---

# 42. 有方法但没声明 Capability

场景：

```text
gateway
碰巧存在 query_fee_evidence()
```

但：

```text
capabilities
没有 QUERY_FEE_EVIDENCE
```

Runtime 不得使用。

正式 Product Capability 来源是：

```text
Capability Declaration
```

不是反射猜测。

---

# 43. MiniQMT 当前不需要实现 Fee Evidence

如果 MiniQMT 目前没有正式真实 Fee Evidence：

```text
不要声明 QUERY_FEE_EVIDENCE
```

这是正确产品状态。

不要为了让新 Capability 测试通过而：

```text
返回空 tuple
```

假装支持。

---

# 44. 返回空 tuple 不是“不支持”

必须严格区分：

```text
Unsupported capability
```

和：

```text
Supported query
but currently no evidence
```

前者：

```text
Capability absent
```

后者：

```text
Capability present
query returns ()
```

不要混淆。

---

# 45. Fake Broker 可以提供 Contract Test 实现

为了验证：

```text
OnlyBrokerFeeEvidencePort
```

可以扩：

```text
Fake/Test Broker
```

实现 normalized fake evidence。

但生产 MiniQMT：

```text
不接网络
```

---

# 46. Broker Plugin Contract

如果 Broker Plugin 描述器/Factory 已经检查 Capability：

扩展测试确保：

```text
descriptor capabilities
factory gateway surface
```

一致。

不要创建第二套 Capability Registry。

---

# 47. 第四项改造：文档准确性

P2.1 是 Stabilization PR，因此应修正当前确认的文档漂移。

---

# 48. README Version

README 当前版本必须与：

```text
pyproject.toml
```

保持一致。

当前实际版本为：

```text
0.3.4
```

不要手工保留：

```text
0.3.3
```

如果项目已有 version sync script：

确保该脚本覆盖 README 或记录为什么不覆盖。

---

# 49. README A-share Fee 能力声明

不要再写成：

```text
A 股已经具备基础佣金、印花税、过户费
```

如果当前实际安装的是：

```text
CN_A_SHARE_TEST_MARKET_FEE_PACK
```

且只是 Conformance Fee。

应明确：

```text
A-share Fee Authority / Binding / Reconciliation
architecture is available.

Current built-in A-share fee pack
is test/conformance-only.

Production market fee schedules
are not yet implemented.
```

中文按 README 当前风格表达即可。

---

# 50. Roadmap Futures Capability 修正

如果当前正式 Execution Capability 对：

```text
margin
SHORT
HEDGING
non-CASH
```

仍为：

```text
LEGACY_UNMIGRATED
UNSUPPORTED
```

Roadmap 不得写：

```text
期货已有正式产品纵切面
```

应该明确：

```text
Futures Domain / Conformance foundation exists.

Formal Durable Futures Product Execution
is not enabled.
```

---

# 51. 不要重写整个 README

P2.1 文档任务只处理：

```text
version drift

fee capability overclaim

futures capability overclaim

P2/P2.1 status
```

不要做无关排版或 marketing 重写。

---

# 52. Architecture Guard：Policy Registry Ownership

新增测试禁止：

```text
OnlyFeeReconciliationPolicyRegistry()
```

直接出现在：

```text
runtime/backtest/factory.py
runtime/paper/factory.py
runtime/live/factory.py
```

允许：

```text
runtime/defaults.py
tests
```

根据真实 Composition 需求使用。

---

# 53. Architecture Guard：Built-in Policy Factory Import

禁止 Runtime Factory import：

```text
only_standard_fee_reconciliation_policy
```

Factory 必须只依赖 Registry。

---

# 54. Architecture Guard：No Fallback

扫描生产代码，禁止：

```text
Policy not installed
→ standard fallback
```

或：

```text
currency mismatch
→ recreate policy
```

---

# 55. Architecture Guard：Broker Optional Capability

避免出现：

```text
hasattr(gateway, "query_fee_evidence")
```

在 Runtime / Product 代码中成为正式 Capability 判断。

正式逻辑必须经过 Capability Contract。

---

# 56. Architecture Guard：P2 Domain Stability

P2.1 不得重新引入：

```text
materiality_threshold Runtime parameter

statement_scope: str

SELL+CLOSE Fee Gate

single blocker model

sum-only DETAILED
```

已有 P2 Guard 必须继续通过。

---

# 57. 推荐代码结构

P2.1 不需要新增大量模块。

可能涉及：

```text
fee/reconciliation_policy.py

runtime/assembler.py
runtime/defaults.py

runtime/backtest/factory.py
runtime/paper/factory.py

broker/enums.py
broker/ports.py
broker/capabilities.py

broker optional-port helper/resolver
```

如果需要新增 helper：

```text
broker/optional_ports.py
```

或当前架构最匹配的位置。

避免新建：

```text
broker/fee_framework/
```

这种过度目录。

---

# 58. Policy Registry API 应保持小

目标：

```python
register(policy)

require(
    policy_id,
    policy_version,
    currency,
)
```

最多再提供：

```text
identities/list
```

如果已有测试需要。

不要构造通用：

```text
Query Language
Policy Search DSL
Best Match Resolver
Wildcard Currency
```

Authority 必须 exact match。

---

# 59. Error Codes

继续复用：

```text
FEE_RECONCILIATION_POLICY_NOT_INSTALLED

FEE_RECONCILIATION_POLICY_DUPLICATE_VERSION

FEE_RECONCILIATION_POLICY_FINGERPRINT_CONFLICT

FEE_RECONCILIATION_POLICY_CURRENCY_MISMATCH
```

Broker Optional Capability 使用现有：

```text
OnlyUnsupportedBrokerCapabilityError
```

必要时增加：

```text
BROKER_CAPABILITY_CONTRACT_INVALID
```

不要为了 P2.1 重构整个 Error System。

---

# 60. Test — Registry Identity

至少测试：

```text
STANDARD@1/CNY
register
→ PASS

STANDARD@1/CNY
same instance second registration
→ duplicate semantics

STANDARD@1/CNY
different payload
→ fingerprint conflict

STANDARD@1/USD
→ independent authority
```

---

# 61. Test — require exact Currency

```text
Registry:
STANDARD@1/CNY

require:
STANDARD@1/CNY
→ PASS
```

```text
require:
STANDARD@1/USD
→ POLICY_NOT_INSTALLED
```

不能返回 CNY。

---

# 62. Test — Policy Identity Serialization

确保：

```text
policy_id
policy_version
currency
fingerprint
```

round-trip 后完全相同。

旧 identity schema：

```text
reject
```

如果当前项目 Persistence Policy 要求如此。

---

# 63. Test — Central Composition

默认 Engine Services 创建后：

```text
components.fee_reconciliation_policies
```

必须存在。

并且：

```text
STANDARD@1/CNY
```

可 resolve。

---

# 64. Test — Factory Does Not Register

可以通过 Architecture Test：

```text
AST
source search
dependency guard
```

证明：

```text
Backtest Factory
Paper Factory
```

不创建：

```text
OnlyFeeReconciliationPolicyRegistry
```

---

# 65. Test — Custom Policy Backtest

注入：

```text
CUSTOM_STRICT@1/CNY
```

配置选择 Custom。

Backtest Factory 创建 Runtime 后：

```text
runtime.config.fee_reconciliation_policy.identity
==
CUSTOM identity
```

---

# 66. Test — Custom Policy Paper

同一 Custom Policy：

Paper 解析结果必须相同。

不能：

```text
Paper 自动使用 Standard
```

---

# 67. Test — Missing Policy

配置：

```text
CUSTOM@1
```

Registry 无。

Backtest：

```text
FAIL
```

Paper：

```text
FAIL
```

错误语义一致。

---

# 68. Test — Currency-specific Runtime Resolution

例如：

```text
Account Currency CNY
```

必须 require：

```text
CNY Policy
```

不能：

```text
USD
```

---

# 69. Test — Broker Fee Evidence Capability Success

Fake Broker：

```text
capability = QUERY_FEE_EVIDENCE
```

并真实实现：

```text
OnlyBrokerFeeEvidencePort
```

Resolver：

```text
returns typed port
```

---

# 70. Test — Capability Contract Invalid

Fake Broker：

```text
declares QUERY_FEE_EVIDENCE
```

但没有：

```text
query_fee_evidence
```

必须 Fail Closed。

---

# 71. Test — Method Without Capability

Fake Broker 有：

```text
query_fee_evidence
```

但不声明 Capability。

正式 resolver：

```text
UnsupportedBrokerCapability
```

---

# 72. Test — MiniQMT Contract

现有 MiniQMT：

如果没有真实 Fee Evidence：

```text
QUERY_FEE_EVIDENCE
not declared
```

现有：

```text
miniqmt-contract
```

必须继续全绿。

---

# 73. Test — P2 Regression

至少保留：

```text
Component reconciliation

Revision forward correction

Multi-blocker

Risk change

Evidence ingress

Recovery
```

现有 P2 Tests 全部继续通过。

P2.1 不得削弱。

---

# 74. Determinism

Policy Registry 安装顺序变化：

```text
A, B, C
```

vs：

```text
C, B, A
```

对 exact selected Policy：

```text
Identity
Fingerprint
Runtime Config
```

不得产生差异。

---

# 75. Built-in Policy Installation Determinism

`only_default_engine_services()` 多次创建：

```text
fresh registries
```

但相同 built-in Policy：

```text
same identity
same fingerprint
```

---

# 76. Recovery

P2.1 不增加新的 Recovery Domain。

但是由于：

```text
Policy Identity
```

进入 Decision Persistence，因此已有 Reconciliation Recovery 测试必须继续通过。

至少覆盖：

```text
Evidence
Decision
Adjustment
Blocker
Checkpoint
Restart
```

Policy Identity Currency 在恢复后保持一致。

---

# 77. Old Persisted Policy Identity

如果旧：

```text
policy identity
```

没有 Currency：

```text
明确拒绝
```

不要：

```text
从 Account Currency 自动补上
```

这是隐式 migration。

---

# 78. Commit 规划

P2.1 建议只拆 4 个逻辑 Commit。

---

# 79. Commit 1 — Central Reconciliation Policy Composition

完成：

```text
OnlyComponentFactoryRegistries
+ fee_reconciliation_policies

runtime/defaults
central registration

Backtest Factory
consume registry

Paper Factory
consume registry

remove local registries
```

测试：

```text
central composition
custom injection
missing policy
backtest/paper parity
```

---

# 80. Commit 2 — Policy Identity Currency Closure

完成：

```text
Identity + currency

Registry key + currency

require exact currency

serialization/schema upgrade

Decision/Artifact updates if required
```

不要增加 compatibility。

---

# 81. Commit 3 — Broker Fee Evidence Capability Alignment

完成：

```text
QUERY_FEE_EVIDENCE

Optional capability port resolver

capability/implementation contract validation

Fake Broker tests

MiniQMT remains unsupported unless truly implemented
```

---

# 82. Commit 4 — Architecture Guards + Documentation Accuracy

完成：

```text
README version

A-share fee capability wording

Futures capability wording

P2.1 report

architecture guards

roadmap update
```

---

# 83. 不需要更多 Commit 的原因

P2.1 是 Stabilization。

不要把它扩大成：

```text
10+ commit
数千行业务开发
```

如果工作量突然明显超出上述四个主题：

> 停止扩 Scope，记录后续任务。

---

# 84. Documentation

新增：

```text
docs/reports/
p2_1_reconciliation_composition_stabilization.md
```

至少记录：

```text
Baseline

Why P2.1 exists

Current composition asymmetry

Policy registry ownership before/after

Policy identity currency change

Schema changes

Broker optional capability model

Deleted factory-local composition

Documentation corrections

Tests

Remaining debt
```

---

# 85. 是否需要 ADR

如果 P2 ADR 已经定义：

```text
Reconciliation Policy is versioned authority
```

可以新增一个小 ADR：

```text
Authority Composition and Currency Identity
```

如果当前项目 ADR 已充分覆盖 Composition 原则，可以更新现有 ADR。

但不要隐藏重要决策。

至少必须正式记录：

```text
Runtime selects authorities; it never creates them.

Currency is part of reconciliation policy identity.

Broker optional ports require explicit capability declaration.
```

---

# 86. Roadmap 更新

P2：

```text
DONE
```

P2.1：

```text
DONE
Reconciliation Composition Stabilization
```

下一项：

```text
P3 — CN A-Share Production Fee Product
```

不要把 P2.1 描述成：

```text
real broker fee integration
```

---

# 87. README 最终状态

README 应准确表达：

```text
Fee authority architecture:
READY

External reconciliation semantics:
READY

Reconciliation composition:
READY

A-share production fee pack:
NOT READY

Real Broker fee evidence ingestion:
NOT READY

Futures durable execution:
NOT READY
```

不一定按表格原样写，但语义必须如此。

---

# 88. 代码质量要求

最终必须：

```text
Runtime Factory 不拥有 Authority Registration

一个 Authority 一个 Registry

Registry exact selection

Config 不隐式造 Authority

无 fallback

无 duplicate composition code

无 compatibility wrappers

无 deprecated aliases

无 dead imports

无 test-only production branches

Broker capability 与 port 一致

文档与源码一致
```

---

# 89. 禁止的具体代码模式

生产代码中禁止：

```python
OnlyFeeReconciliationPolicyRegistry()
```

出现在 Runtime Factory。

禁止：

```python
only_standard_fee_reconciliation_policy(
    account.initial_cash.currency
)
```

出现在 Runtime Factory。

禁止：

```python
try:
    policy = registry.require(...)
except:
    policy = only_standard_fee_reconciliation_policy(...)
```

禁止：

```python
hasattr(gateway, "query_fee_evidence")
```

成为正式 Broker Capability 检测逻辑。

禁止：

```text
README claims production fee
while using TEST/CONFORMANCE pack
```

---

# 90. Gate 要求

开始：

```bash
uv sync --frozen --all-packages --all-groups
```

Static：

```bash
uv run ruff check src tests examples packages scripts

uv run ruff format --check src tests examples packages scripts

uv run mypy src/onlyalpha
```

以及当前正式 provider mypy。

---

# 91. Test Lanes

运行：

```bash
uv run python scripts/test_suite.py fast

uv run python scripts/test_suite.py integration

uv run python scripts/test_suite.py core-full

uv run python scripts/test_suite.py recovery

uv run python scripts/test_suite.py ashare

uv run python scripts/test_suite.py miniqmt-contract

uv run python scripts/test_suite.py exhaustive
```

如果最新 `master` Lane 有变化：

```text
使用最新正式命令
```

不要恢复旧 Lane。

---

# 92. Build

```bash
uv build --all-packages
```

必须成功。

---

# 93. 不允许通过测试的方法

禁止：

```text
skip

xfail

降低 assertion

删 P2 tests

删 recovery coverage

default policy fallback

currency fallback

MiniQMT fake capability

返回空数据假装实现 Fee Evidence
```

---

# 94. Definition of Done — Composition

* [ ] `OnlyFeeReconciliationPolicyRegistry` 已进入 `OnlyComponentFactoryRegistries`。
* [ ] Default Composition Root 安装 built-in Reconciliation Policies。
* [ ] Backtest Factory 不再创建 Policy Registry。
* [ ] Paper Factory 不再创建 Policy Registry。
* [ ] Future Live Factory 不需要安装 Reconciliation Policy。
* [ ] Runtime Factory 不 import built-in Policy constructor。
* [ ] Runtime Factory 只 resolve exact Authority。
* [ ] Custom Registry Policy 可以被 Runtime 使用。
* [ ] Missing Policy Fail Closed。

---

# 95. Definition of Done — Policy Identity

* [ ] Currency 是 `OnlyFeeReconciliationPolicyIdentity` 的正式维度。
* [ ] Registry Key 包含 Currency。
* [ ] `require()` 精确匹配 Currency。
* [ ] CNY 与 USD 不共享模糊 identity。
* [ ] Same id/version/currency different payload Fail Closed。
* [ ] Policy fingerprint 仍包含所有治理参数。
* [ ] Account Currency 是当前 Policy Resolution Currency Authority。
* [ ] Config 没有新增冗余 Currency。
* [ ] 未安装 Currency-specific Policy Fail Closed。
* [ ] Old identity schema 明确拒绝。

---

# 96. Definition of Done — Broker Capability

* [ ] `QUERY_FEE_EVIDENCE` Broker Capability 存在。
* [ ] `OnlyBrokerFeeEvidencePort` 保持 Optional Port。
* [ ] 不支持 Fee Evidence 的 Broker 无需实现该 Port。
* [ ] Capability + actual Port 同时成立才可使用。
* [ ] 声明 Capability 但没有实现 Port Fail Closed。
* [ ] 有 Port 方法但未声明 Capability 不可使用。
* [ ] Runtime 不通过 `hasattr()` 猜 Broker Capability。
* [ ] MiniQMT 未真实实现时不声明支持。
* [ ] Fake/Contract Broker 覆盖 Capability contract tests。

---

# 97. Definition of Done — Documentation

* [ ] README Version 与 `pyproject.toml` 一致。
* [ ] README 不再把测试 A-share Fee Pack 描述成 production fee。
* [ ] README 不再虚假宣称真实印花税/过户费产品化完成。
* [ ] Roadmap 不再把 Futures Domain/Conformance 描述成 Durable Product。
* [ ] P2 / P2.1 状态准确。
* [ ] P3 明确是下一阶段 Production Fee Product。
* [ ] 文档不宣称真实 MiniQMT Fee Evidence 已接入。

---

# 98. Definition of Done — Architecture Cleanliness

* [ ] 没有 Factory-local Reconciliation Policy Registry。
* [ ] 没有 Policy fallback。
* [ ] 没有 Currency fallback。
* [ ] 没有 Compat Policy Identity。
* [ ] 没有 Legacy Registry。
* [ ] 没有 Optional Port reflection hack。
* [ ] 没有 Dead Code。
* [ ] 没有 Deprecated Alias。
* [ ] 没有无意义 Wrapper。
* [ ] P2 Domain Semantics 未重新设计。
* [ ] Runtime Composition Boundary 更简单，而不是更复杂。
* [ ] Architecture Guards 已加入。

---

# 99. Definition of Done — Quality

* [ ] Ruff PASS。
* [ ] Ruff Format PASS。
* [ ] Core mypy PASS。
* [ ] Provider mypy PASS。
* [ ] Fast PASS。
* [ ] Integration PASS。
* [ ] Core Full PASS。
* [ ] Recovery PASS。
* [ ] A-share PASS。
* [ ] MiniQMT Contract PASS。
* [ ] Exhaustive PASS。
* [ ] Build PASS。
* [ ] Quality Gate PASS。

---

# 100. 最终报告必须提供实际结果

不要只写：

```text
all tests pass
```

必须写：

```text
commit SHA

static result

fast:
xxx passed
xx.xx s

integration:
xxx passed
xx.xx s

core-full:
xxxx passed
x skipped
xx.xx s

recovery:
xxx passed
xx.xx s

ashare:
...

miniqmt-contract:
...

exhaustive:
...

build:
PASS
```

---

# 101. P2.1 完成后明确仍未实现

Implementation Report 必须有：

```text
NOT IMPLEMENTED IN P2.1
```

至少：

```text
Production CN A-share fee schedules

Production stamp duty rules

Production transfer fee rules

Real Broker commission provisioning

Real MiniQMT fee evidence query

Broker statement ingestion

Fee debt / negative cash handling

Paper streaming recovery

CN A-share durable execution product

Live runtime

Durable outbound broker command

Multi-account runtime

Multi-broker runtime

Vectorized backtest
```

---

# 102. P2.1 完成后的最终架构

最终：

```text
                    Composition Root
                           │
        ┌──────────────────┼──────────────────┐
        │                  │                  │
        ▼                  ▼                  ▼
 Market Fee Pack    Broker Fee Contract  Reconciliation
    Registry             Registry        Policy Registry
        │                  │                  │
        └──────────────────┼──────────────────┘
                           │
                    Account Config
                           │
                           ▼
                     Runtime Factory
                           │
                      exact require
                           │
                           ▼
                        Runtime
```

其中：

```text
Runtime Factory:
    selects authority

Composition Root:
    installs authority
```

绝不能反过来。

---

# 103. Broker Evidence 最终结构

```text
Broker
   │
   ├─ Capability:
   │      QUERY_FEE_EVIDENCE
   │
   └─ Optional Port:
          OnlyBrokerFeeEvidencePort
                 │
                 ▼
        OnlyExternalFeeEvidence
                 │
                 ▼
        Runtime.submit_fee_evidence()
                 │
                 ▼
            P2 Domain
```

如果 Broker 不支持：

```text
Capability absent
```

即可。

---

# 104. P2.1 的成功标准

P2.1 的成功不是：

```text
新增了更多 Fee 功能
```

而是：

```text
Authority 安装只有一个地方

Runtime 不再制造经济 Policy

Config 真的能选择 Authority

Policy identity 不再有 Currency 歧义

Broker Fee Evidence Capability 不再是孤立 Protocol

文档不再高估产品能力
```

---

# 105. 最终工程原则

当：

```text
Runtime Factory convenience
```

与：

```text
Authority ownership
```

冲突：

> 选择 Authority ownership。

当：

```text
相同 policy_id/version
```

与：

```text
不同 Currency economic meaning
```

冲突：

> Currency 进入 Identity。

当：

```text
自动 fallback
```

与：

```text
Exact Authority Resolution
```

冲突：

> Exact Resolution。

当：

```text
方法碰巧存在
```

与：

```text
Capability 未声明
```

冲突：

> Capability 未声明即不可用。

当：

```text
兼容旧 persisted schema
```

与：

```text
正确 Authority Identity
```

冲突：

> 当前 Alpha 阶段选择正确 Identity，旧 Schema Fail Closed。

当：

```text
少改几行代码
```

与：

```text
Composition Boundary 清晰
```

冲突：

> 选择清晰边界。

---

# 106. P2.1 最终定义

P2.1 不是：

> “把 Policy Registry 移一个文件。”

它真正要解决的是：

> **让 Reconciliation Governance Authority 从 Domain 正确进一步变成 Composition 正确：所有 Policy 由统一 Composition Root 安装，以完整且无歧义的 Currency-aware Identity 存在，Runtime Mode 只负责精确选择；同时 Broker Fee Evidence 从孤立 Port 升级为由 Capability 明确声明的 Optional SPI。**

最终必须满足：

```text
Authorities are installed centrally.

Runtime factories do not manufacture policy.

Selection is exact.

Currency participates in authority identity.

No implicit fallback exists.

Capabilities are explicit.

Optional ports are contract-checked.

Unsupported means unsupported.

Documentation matches executable capability.

P2 semantics remain untouched.

The codebase becomes smaller and clearer,
not more compatible and more complicated.
```

只有这些原则全部进入正式代码、测试、Composition Root、Schema 和文档后，P2.1 才算完成。

完成 P2.1 后：

> **冻结 Fee / Reconciliation 根架构，下一阶段直接进入 P3 — CN A-Share Production Fee Product，不再继续设计 Fee 基础设施。**
