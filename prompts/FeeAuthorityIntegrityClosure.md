# Codex Prompt — P1 Fee Authority Integrity Closure

## 任务名称

**P1 — Fee Authority Integrity Closure**

中文：

**P1：费用权威完整性闭环**

目标仓库：

```text
https://github.com/zongxin1993/OnlyAlpha
```

开始工作前必须重新读取最新 `master`，不得假设下面记录的 SHA 仍然是最新提交。

当前规划基线：

```text
39272f9a7201222c83433ce9b1933f02b31985fc
Feat: Test Baseline & Feedback Loop Closure
```

如果 `master` 已前进：

1. 以最新 `master` 为唯一实现基线；
2. 重新审计本 Prompt 涉及的模块；
3. 如果当前代码已经解决部分问题，不重复实现；
4. 在实施报告中明确记录 Prompt 基线与实际实现基线的差异。

---

# 1. 任务背景

OnlyAlpha 已经完成了较成熟的：

```text
Fee Formula
Fee Rule
Fee Estimate
Fee Assessment
Fee Accrual
Fee Application
Fee Ledger
Durable Runtime Transaction
Projection
Checkpoint
Forward Recovery
External Fee Reconciliation Foundation
```

当前主要问题已经不是：

> “系统是否会计算费用。”

而是：

> **系统是否能够严格证明每一笔费用来自哪个经济 Authority、为什么适用于这个订单、何时被冻结、成交时解析的是哪个制度版本，以及 Restart/Replay 后为什么仍得到完全相同的结论。**

当前 Fee 实现存在以下核心结构问题：

```text
1. Market Fee 与 Broker Fee 仍被组合在一个 OnlyFeePolicyPack 中。

2. Broker/Account 没有独立的 Broker Fee Contract Authority。

3. Fee Schedule 已声明：
   market
   venue
   instrument_class
   broker_id
   account_scope

   但正式 Resolution 主要仍按 trading_day 选择，
   Scope 并没有成为真正的 Applicability Authority。

4. Market Schedule / Broker Schedule 仍共用裸字符串 schedule_id，
   Resolution 存在“先查 Market，失败再查 Broker”的隐式 Namespace。

5. OnlyOrderFeePolicyBinding 没有完整记录：
   Market Fee Pack Identity
   Broker Fee Contract Identity
   Applicability Scope Identity。

6. Fee Engine 收到 binding fingerprint，
   但当前 Authority Validation 没有真正证明
   Resolved Policy Set 来源于该 Binding。

7. Fee Resolver 当前直接把：
   contracts = quantity

   Fee 层自己解释了 Instrument Quantity 的经济意义。

8. OnlyMarketProfile 中仍残留 market_fee_schedule_id，
   与正式 Fee Pack Authority 重复。

9. 当前 Generic Fee Pack 结构会妨碍未来正式：
   CN A-share
   Futures
   Crypto
   多 Broker / 多账户

   费用 Authority 的准确表达。
```

P1 必须从根本上解决这些问题。

---

# 2. 第一性原则

开始写代码之前，必须先从以下原则重新推导设计。

## 2.1 一项费用必须有唯一 Authority

一项费用不是：

```text
一个 rate
```

而是：

```text
Authority
+
Policy Identity
+
Applicability Scope
+
Effective Version
+
Formula
+
Basis
+
Resolution Timing
+
Rounding
+
Currency
```

任何 Fee Component 必须能够回答：

```text
谁定义了它？

为什么适用于这个订单？

哪个版本生效？

版本是在 Order Accepted 时冻结，
还是在 Fill 时重新按生效日解析？

该决定如何被持久化和恢复？
```

---

# 3. Market Fee 与 Broker Fee 是两个不同 Authority

必须明确：

```text
Market Fee Authority
```

负责：

```text
MARKET
VENUE
REGULATOR
CLEARING
```

例如：

```text
印花税
交易所费用
过户费用
清算费用
监管费用
```

而：

```text
Broker Fee Contract Authority
```

负责：

```text
BROKER
PLATFORM
```

例如：

```text
券商佣金
最低佣金
账户折扣
VIP 合同费率
平台服务费
```

两者：

```text
生命周期不同
来源不同
版本不同
适用 Scope 不同
变更权限不同
```

因此绝不能继续由一个模糊 Pack 同时拥有。

---

# 4. 最终目标架构

最终架构必须收敛成：

```text
                    Market Profile
                         │
                         ▼
                  Market Fee Pack
                         │
                         │
                         ├──────────────────────┐
                                                │
Broker ───── Account ───── Broker Fee Contract │
                         │                      │
                         └──────────┬───────────┘
                                    ▼
                       Applicability Resolution
                                    │
                                    ▼
                        Order Fee Policy Binding
                                    │
                        ┌───────────┴───────────┐
                        │                       │
                   ORDER_FIXED             FILL_EFFECTIVE
                   exact version           authority family
                        │                       │
                        └───────────┬───────────┘
                                    ▼
                         Fee Policy Resolution
                                    │
                             Authority Proof
                                    │
                                    ▼
                               Fee Engine
                                    │
                                    ▼
                             Fee Assessment
                                    │
                                    ▼
                              Fee Accrual
                                    │
                                    ▼
                             Fee Application
                                    │
                                    ▼
                        Durable Runtime Transaction
```

---

# 5. 本任务的核心目标

P1 必须完成：

```text
A. Market Fee Pack 与 Broker Fee Contract 完全拆分

B. Fee Schedule Scope 真正参与 Applicability Resolution

C. Market/Broker Schedule Identity 强类型 Namespace

D. ORDER_FIXED / FILL_EFFECTIVE Authority 语义冻结

E. Order Fee Binding v2

F. Binding → Resolution → Policy Set Authority Proof

G. Fee Basis Authority 从 Fee Resolver 中抽离

H. 删除 Market Profile 重复 Fee Authority

I. Persistence / Recovery / Determinism 闭环

J. 删除所有被新架构取代的旧接口、Alias、兼容代码和旧测试
```

---

# 6. 明确非目标

本 PR 不实现：

```text
真实 A 股印花税具体费率
真实 A 股过户费具体费率

真实 MiniQMT / 国金证券佣金合同

正式 Broker Statement 接入

Fee Reconciliation DETAILED Component-by-Component 改造

Statement Period Scope

Paper Recovery

Live Runtime

Durable Broker Command

正式 Futures Execution

正式 Crypto Execution

向量化回测

Web / Research UI
```

P1 只解决：

> **Fee Authority 输入侧的完整性。**

不要因为实现过程中发现后续问题而扩 Scope。

---

# 7. 禁止兼容性设计

本项目当前是新工程。

如果旧接口与正确架构冲突：

> 删除旧接口。

严禁新增：

```text
LegacyFeePolicyPack
CompatFeePack
OldFeeResolver
BrokerScheduleFallback
MarketScheduleFallback
LegacyScheduleId
LegacyFeeBinding
FeeBindingV1Adapter
FeePackCompatibilityLayer
OldMarketFeeScheduleAlias
DefaultBrokerFeeContract
ImplicitZeroBrokerFees
```

严禁：

```text
try:
    new_path
except:
    old_path
```

严禁：

```text
if binding.schema_version == 1:
    inject defaults
```

严禁：

```text
旧 YAML 没有 Broker Contract
→ 自动假定 0 佣金
```

如果旧配置不符合新正式 Schema：

```text
直接拒绝
```

如果历史测试验证旧设计：

```text
删除或重写测试
```

不能修改生产代码去满足历史测试。

---

# 8. Pre-Implementation Audit

开始修改前必须先完成一次只读审计。

至少检查：

```text
src/onlyalpha/fee/
src/onlyalpha/market/
src/onlyalpha/order/
src/onlyalpha/config/
src/onlyalpha/runtime/
src/onlyalpha/account/
src/onlyalpha/broker/

tests/fee/
tests/order/
tests/runtime/
tests/recovery/
tests/domain_conformance/
tests/architecture/

examples/
docs/
```

重点搜索：

```text
OnlyFeePolicyPack
OnlyFeePolicyPackRegistry

OnlyMarketFeeSchedule
OnlyBrokerFeeSchedule

OnlyFeeScheduleIdentity

OnlyOrderFeePolicyBinding

fill_effective_schedule_ids
order_fixed_schedules

market_fee_schedule_id

OnlyFeeBasis
OnlyFeeCalculationBasis

contracts = quantity

_try market
_try broker

broker_schedules
market_schedules

FEE_PACK_NOT_INSTALLED

binding_fingerprint
del binding_fingerprint
```

输出：

```text
docs/reports/p1_fee_authority_pre_implementation_audit.md
```

至少记录：

```text
当前类型关系
当前 Config 入口
当前 Runtime Assembly
当前 Binding Payload
当前 Resolver 流程
当前 Persistence Schema
当前 Recovery 使用方式
需要删除的旧接口
需要修改的测试
```

不要先写代码再倒推审计结果。

---

# 9. 新增 Market Fee Pack

删除旧的：

```text
OnlyFeePolicyPack
```

替换为：

```python
@dataclass(frozen=True, slots=True)
class OnlyMarketFeePack:
    pack_id: str
    pack_version: str

    compatible_market_profiles: tuple[str, ...]

    schedules: tuple[OnlyMarketFeeSchedule, ...]

    fingerprint: str
```

职责只能包含：

```text
市场制度相关 Fee Schedule
```

禁止包含：

```text
Broker Fee Schedule
```

构造时必须验证：

```text
pack_id 非空
version 非空
compatible profile 非空
schedule 全部是 Market Schedule
fingerprint 与 Authority Payload 一致
```

---

# 10. 新增 Market Fee Pack Identity

正式建立：

```python
@dataclass(frozen=True, slots=True)
class OnlyMarketFeePackIdentity:
    pack_id: str
    pack_version: str
    fingerprint: str
```

该对象必须进入：

```text
Order Fee Binding
Artifact / Result authority fields
Persistence
Recovery
```

不能只把：

```text
pack_id
```

作为字符串保存。

---

# 11. 新增 Broker Fee Contract

建立：

```python
@dataclass(frozen=True, slots=True)
class OnlyBrokerFeeContract:
    contract_id: str
    contract_version: str

    broker_id: str

    account_scope: ...
    
    schedules: tuple[OnlyBrokerFeeSchedule, ...]

    fingerprint: str
```

Broker Contract 表达：

> 一个 Broker 对某个 Account Scope 的经济收费合同。

它不是：

```text
Market Pack
```

也不是：

```text
Broker Plugin Runtime Config
```

是独立 Domain Authority。

---

# 12. Account Scope 不允许长期使用任意字符串

当前：

```text
account_scope: str | None
```

必须重新设计。

推荐使用显式强类型，例如：

```python
class OnlyBrokerFeeAccountScopeType(StrEnum):
    ALL_ACCOUNTS = "ALL_ACCOUNTS"
    EXACT_ACCOUNT = "EXACT_ACCOUNT"
```

以及：

```python
@dataclass(frozen=True, slots=True)
class OnlyBrokerFeeAccountScope:
    scope_type: OnlyBrokerFeeAccountScopeType
    account_id: OnlyAccountId | None
```

规则：

```text
ALL_ACCOUNTS
    account_id 必须 None

EXACT_ACCOUNT
    account_id 必须存在
```

不要设计自由文本：

```text
"account-a,account-b"
```

如果未来需要复杂 Account Group：

```text
后续增加新的显式类型
```

不要提前引入 DSL。

---

# 13. 新增 Broker Fee Contract Identity

```python
@dataclass(frozen=True, slots=True)
class OnlyBrokerFeeContractIdentity:
    contract_id: str
    contract_version: str

    broker_id: str

    fingerprint: str
```

如果是 Exact Account Contract：

Identity/Authority Payload 必须包含 Account Scope。

---

# 14. Registry 拆分

删除：

```text
OnlyFeePolicyPackRegistry
```

新增：

```text
OnlyMarketFeePackRegistry
OnlyBrokerFeeContractRegistry
```

## Market Registry

键：

```text
(pack_id, pack_version)
```

规则：

```text
同 identity + 同 fingerprint
    duplicate error 或严格幂等，选择一个规则并固定测试

同 identity + 不同 fingerprint
    MARKET_FEE_PACK_FINGERPRINT_CONFLICT

unknown
    MARKET_FEE_PACK_NOT_INSTALLED
```

项目目前 Registry 更偏严格重复错误，优先保持：

```text
duplicate version = explicit error
```

除非审计发现整个 Authority Registry 已统一采用幂等注册。

---

# 15. Broker Contract Registry

键：

```text
(contract_id, contract_version)
```

规则：

```text
BROKER_FEE_CONTRACT_DUPLICATE_VERSION

BROKER_FEE_CONTRACT_FINGERPRINT_CONFLICT

BROKER_FEE_CONTRACT_NOT_INSTALLED
```

不能把 Broker Contract 放回 Market Pack Registry。

---

# 16. Runtime Built-in Registry

更新：

```text
onlyalpha.runtime.defaults
OnlyComponentFactoryRegistries
OnlyEngineRunAssembler
```

正式组件 Registry 应变成类似：

```text
market_fee_packs
broker_fee_contracts
```

而不是：

```text
fee_policy_packs
```

所有 Runtime Factory 必须通过：

```text
Component Registry
```

解析 Authority。

Test 可以注入 Test Pack / Contract。

Production Runtime 不得从 Test Registry 获取默认值。

---

# 17. Config Schema 重构

当前类似：

```yaml
market:
  fees:
    pack_id: ...
    pack_version: ...
```

P1 后建议正式修改为：

```yaml
market:
  profile: GENERIC_T0_CASH

  fee_pack:
    pack_id: GENERIC_T0_MARKET_FEES
    pack_version: "1"
```

Account：

```yaml
accounts:
  - account_id: ACCOUNT-001
    gateway_id: BROKER-001

    broker_fee_contract:
      contract_id: GENERIC_ZERO_BROKER_FEES
      contract_version: "1"
```

名称可以根据项目现有 Config Style 调整，但必须满足：

```text
Market Fee Authority
属于 market

Broker Fee Contract Authority
属于 account/broker relationship
```

绝不能继续把 Broker Contract 放到：

```text
market
```

下面。

---

# 18. 是否允许无 Broker Contract

不要通过：

```text
missing config == no fees
```

表达。

需要一个显式零 Broker Fee Contract，例如：

```text
GENERIC_ZERO_BROKER_FEES
```

其 Authority 仍必须有：

```text
contract_id
version
broker scope
fingerprint
```

可以选择：

```text
zero-rule schedule
```

或者：

```text
显式 Empty Contract Semantics
```

但必须只有一种正式表达。

推荐：

> 允许 Broker Contract schedules 为空，Contract 本身仍是显式 Authority。

Market Fee Pack 是否允许 schedules 为空，需要根据当前测试市场需求决定。

但不要为了兼容旧测试隐式生成零费率。

---

# 19. Broker Contract Compatibility

Runtime Assembly 必须验证：

```text
Account
    ↓
gateway/broker
    ↓
Broker Fee Contract
```

满足：

```text
contract.broker_id
==
实际 Broker Authority
```

以及 Account Scope 匹配。

否则：

```text
BROKER_FEE_CONTRACT_BROKER_INCOMPATIBLE
```

或：

```text
BROKER_FEE_CONTRACT_ACCOUNT_INCOMPATIBLE
```

Fail Closed。

禁止：

```text
Broker A Contract
+
Broker B Account
```

继续运行。

---

# 20. Market Pack Compatibility

Market Pack 必须验证：

```text
Market Profile ID
```

兼容。

但这还不够。

最终 Schedule Applicability 还必须进一步验证：

```text
market
venue
instrument_class
```

不能把：

```text
compatible_market_profiles
```

当成全部 Scope Validation。

---

# 21. Schedule Namespace 强类型化

当前：

```text
OnlyFeeScheduleIdentity(
    schedule_id,
    version,
    fingerprint,
)
```

不足。

新增：

```python
class OnlyFeeScheduleAuthority(StrEnum):
    MARKET = "MARKET"
    BROKER = "BROKER"
```

修改：

```python
@dataclass(frozen=True, slots=True)
class OnlyFeeScheduleIdentity:
    authority: OnlyFeeScheduleAuthority

    schedule_id: str
    version: str
    fingerprint: str
```

以后：

```text
MARKET / STANDARD / 1
```

与：

```text
BROKER / STANDARD / 1
```

是不同 Authority Identity。

---

# 22. 删除 fallback Registry Resolution

彻底删除：

```python
try:
    return market.resolve(...)
except ValueError:
    return broker.resolve(...)
```

Resolution 必须依据：

```text
identity.authority
```

准确进入：

```text
Market Registry
```

或：

```text
Broker Registry
```

错误 Namespace：

```text
Fail Closed
```

---

# 23. Schedule Applicability Context

新增：

```python
@dataclass(frozen=True, slots=True)
class OnlyMarketFeeApplicabilityContext:
    trading_day: OnlyTradingDay

    market_profile_id: str
    market: str
    venue: str

    instrument_class: str

    instrument_id: OnlyInstrumentId
```

和：

```python
@dataclass(frozen=True, slots=True)
class OnlyBrokerFeeApplicabilityContext:
    trading_day: OnlyTradingDay

    broker_id: str
    account_id: OnlyAccountId

    instrument_id: OnlyInstrumentId
```

如果需要 Gateway ID，只在 Broker ID 不足以唯一解释 Broker Authority 时加入。

不要无意义复制 Config 字段。

---

# 24. Schedule 自己负责 Scope Match

新增：

```python
OnlyMarketFeeSchedule.matches(
    context: OnlyMarketFeeApplicabilityContext,
) -> bool
```

判断：

```text
effective date
market
venue
instrument class
```

规则：

```text
venue=None
```

只能明确表示：

```text
all venues under this market
```

不能既表示 wildcard 又表示 unknown。

同理：

```text
instrument_class=None
```

只能是明确 wildcard。

---

# 25. Broker Schedule Match

```python
OnlyBrokerFeeSchedule.matches(
    context: OnlyBrokerFeeApplicabilityContext,
) -> bool
```

必须验证：

```text
effective date
broker_id
account_scope
```

任何 Scope 不匹配：

```text
不适用
```

而不是报错。

最终 Resolver 对“预期 Schedule Family”统计 Match 数量。

---

# 26. Exactly-One Resolution

Authority Resolution 必须遵守：

```text
0 match
→ FEE_SCHEDULE_NOT_FOUND

1 match
→ PASS

>1 match
→ FEE_SCHEDULE_AMBIGUOUS
```

禁止：

```text
sorted(...)[0]
```

禁止：

```text
first registered wins
```

禁止：

```text
latest version wins
```

除非“latest effective version”是在同一个稳定 Family 内经过明确生效日期规则得到。

---

# 27. Schedule Family

正式引入 Schedule Family Identity。

特别用于：

```text
FILL_EFFECTIVE
```

例如：

```python
@dataclass(frozen=True, slots=True)
class OnlyFeeScheduleFamilyIdentity:
    authority: OnlyFeeScheduleAuthority
    schedule_id: str
    scope_fingerprint: str
```

其含义：

> 订单接受时绑定的是一个制度 Family，而不是未来具体版本。

---

# 28. Schedule Scope Fingerprint

Market Schedule Family Scope 至少包含：

```text
authority = MARKET
market
venue
instrument_class
currency
```

Broker Schedule Family Scope 至少包含：

```text
authority = BROKER
broker_id
account_scope
currency
```

根据当前 Domain 判断：

```text
currency
```

应属于 Scope 还是 Schedule Economics。

无论放在哪里，都必须保证跨版本 Currency Change 不会静默改变经济语义。

---

# 29. 禁止 Schedule Family Scope Drift

同一个：

```text
(authority, schedule_id)
```

的不同版本不得改变 Applicability Scope。

例如：

```text
MARKET/CN_STAMP_DUTY v1
    venue = SSE

MARKET/CN_STAMP_DUTY v2
    venue = SZSE
```

必须：

```text
FEE_SCHEDULE_SCOPE_DRIFT
```

如果 Scope 改变：

```text
创建新的 schedule_id
```

版本应该表达：

```text
同一 Authority Family 的经济规则变化
```

而不是：

```text
Authority Scope 变化
```

---

# 30. Registry 注册时检查 Scope Drift

该检查应尽量在：

```text
Registry.register()
```

发生。

这样非法系统状态无法进入 Runtime。

不要等：

```text
订单提交
```

才发现同 Schedule Family 的 Scope 已漂移。

---

# 31. ORDER_FIXED 语义

如果 Rule：

```text
resolution_policy = ORDER_FIXED
```

订单绑定时必须冻结：

```text
authority
schedule_id
version
fingerprint
```

以后成交：

```text
必须使用 exact schedule
```

即使 Registry 后续安装了新版本：

```text
不能改变该订单
```

---

# 32. FILL_EFFECTIVE 语义

如果 Rule：

```text
resolution_policy = FILL_EFFECTIVE
```

订单绑定时必须冻结：

```text
Schedule Family Identity
+
Scope Fingerprint
```

而不是冻结：

```text
裸 schedule_id
```

成交时：

```text
Bound Family
+
Fill Trading Day
+
Bound Scope
↓
Resolve exact effective version
```

新版本可以影响后续 Fill。

但：

```text
Family / Scope
```

不能改变。

---

# 33. Binding v2

删除旧 Binding v1。

新增正式：

```python
@dataclass(frozen=True, slots=True)
class OnlyOrderFeePolicyBinding:
    schema_version = 2

    runtime_id: OnlyRuntimeId
    account_id: OnlyAccountId
    cluster_id: OnlyClusterId
    order_id: OnlyOrderId
    instrument_id: OnlyInstrumentId

    market_profile_id: str
    market_profile_version: str

    market_fee_pack:
        OnlyMarketFeePackIdentity

    broker_fee_contract:
        OnlyBrokerFeeContractIdentity

    applicability_scope:
        OnlyOrderFeeApplicabilityScopeIdentity

    order_fixed_schedules:
        tuple[OnlyFeeScheduleIdentity, ...]

    fill_effective_families:
        tuple[OnlyFeeScheduleFamilyIdentity, ...]

    charge_currency: OnlyCurrency

    bound_at: OnlyTimestamp

    fingerprint: str
```

不要保留：

```text
fill_effective_schedule_ids: tuple[str, ...]
```

Alias。

---

# 34. Order Fee Applicability Scope Identity

建立一个 Binding 级 Scope：

```python
@dataclass(frozen=True, slots=True)
class OnlyOrderFeeApplicabilityScopeIdentity:
    market_profile_id: str
    market: str
    venue: str
    instrument_class: str

    broker_id: str
    account_id: OnlyAccountId

    instrument_id: OnlyInstrumentId

    charge_currency: OnlyCurrency

    fingerprint: str
```

可以根据最终 Domain 模型做轻微调整。

核心要求：

> Fill 时重新解析 FILL_EFFECTIVE Policy 时，必须证明当前 Scope 仍是订单绑定时的那个 Scope。

---

# 35. Binding Fingerprint

Binding Fingerprint 必须由完整 Authority Payload 构造：

```text
runtime
account
cluster
order
instrument

market profile identity

market fee pack identity

broker fee contract identity

applicability scope

ORDER_FIXED exact schedule identities

FILL_EFFECTIVE family identities

currency

bound_at
```

任何变化：

```text
fingerprint 必须变化
```

---

# 36. Binding 构造 Authority

`OnlyFeeResolver.bind_order()` 当前同时做了太多事情。

P1 可以将它拆分为：

```text
OnlyOrderFeeBinder
```

或者保持 Resolver 类，但内部必须清晰分层：

```text
build applicability context
↓
resolve market authority
↓
resolve broker authority
↓
classify ORDER_FIXED / FILL_EFFECTIVE
↓
construct binding
```

不要让 Binder 执行 Fee Formula。

---

# 37. Resolved Policy Authority

新增正式：

```python
@dataclass(frozen=True, slots=True)
class OnlyFeePolicyResolution:
    binding_fingerprint: str

    market_fee_pack:
        OnlyMarketFeePackIdentity

    broker_fee_contract:
        OnlyBrokerFeeContractIdentity

    scope_fingerprint: str

    resolved_schedules:
        tuple[OnlyFeeScheduleIdentity, ...]

    policies:
        tuple[OnlyResolvedFeePolicy, ...]

    trading_day:
        OnlyTradingDay

    policy_fingerprint: str
    resolution_fingerprint: str
```

它是：

> Binding 到 Fee Engine 之间的 Authority Proof。

---

# 38. Policy Resolution Proof

必须验证：

```text
resolution.binding_fingerprint
==
binding.fingerprint
```

验证：

```text
resolution.market_fee_pack
==
binding.market_fee_pack
```

验证：

```text
resolution.broker_fee_contract
==
binding.broker_fee_contract
```

验证：

```text
resolution.scope_fingerprint
==
binding.applicability_scope.fingerprint
```

所有 Resolved Schedule：

```text
必须属于 Bound Market Pack
或
Bound Broker Contract
```

否则：

```text
ORDER_FEE_POLICY_AUTHORITY_CONFLICT
```

---

# 39. Fee Engine 必须保持 Pure

严禁让：

```text
OnlyFeeEngine
```

import：

```text
Runtime
Broker
Registry
Market Pack Registry
Account Manager
Persistence
```

Fee Engine 只允许消费：

```text
validated request
+
resolved policies
```

P1 不应该把 Authority Resolution 塞入计算器。

---

# 40. 删除无效 Binding Validation

彻底删除当前类似：

```python
del binding_fingerprint
```

的逻辑。

如果一个参数不参与 Authority：

```text
就不应该存在
```

如果它应该参与 Authority：

```text
必须真正验证
```

不允许保留形式化参数但实际忽略。

---

# 41. Engine Request 设计

推荐从：

```text
Request:
    binding
    policies
```

升级为：

```text
Request:
    binding
    policy_resolution
```

或者：

```text
Request:
    validated resolution
```

避免调用方能够组合：

```text
Binding A
+
Policies B
```

构造非法请求。

目标：

> Illegal Authority Combination 应尽量无法构造。

---

# 42. Resolved Policy Set Fingerprint

`OnlyResolvedFeePolicySet` 必须具备稳定：

```text
policy_fingerprint
```

它必须是：

```text
所有 Policy Identity
+
排序
```

的确定性结果。

不能依赖：

```text
Registry Registration Order
```

或：

```text
dict insertion order
```

---

# 43. Assessment Authority

`OnlyFeeAssessment` 应明确保存：

```text
binding fingerprint
policy resolution fingerprint
```

如果已有：

```text
binding
policy_fingerprint
```

则重新判断是否足够证明 Resolution。

若不足，增加：

```text
resolution_fingerprint
```

Assessment Identity 应把 Authority Proof 纳入。

同金额不同 Authority：

```text
Assessment ID 不应该相同
```

---

# 44. Fee Basis Authority

当前 Fee Resolver 不允许继续：

```python
contracts = quantity
```

正式新增：

```python
class OnlyFeeBasisProvider(Protocol):
    def resolve(
        self,
        *,
        instrument: OnlyInstrument,
        price: OnlyPrice,
        quantity: Decimal,
        market_rules: ...,
    ) -> OnlyFeeBasisValues:
        ...
```

---

# 45. Fee Basis 的职责边界

Basis Provider 负责将：

```text
Instrument Economics
+
Trade Price
+
Trade Quantity
+
Market Rule
```

标准化成：

```text
notional
quantity
contracts
```

Fee Engine 只消费这些值。

Fee Engine 不需要知道：

```text
Cash Equity
Futures
Crypto
```

---

# 46. 不要制造第二套 Market Logic

`OnlyFeeBasisProvider` 不允许：

```python
if profile == "CN_A_SHARE":
...
elif profile == "FUTURES":
...
```

这种无限分支长期存在。

优先从：

```text
Instrument Reference
Market Rule / Compiled Rules
```

读取经济属性。

如果必须暂时提供 Generic Provider：

```text
通过注册/策略选择
```

不要让 Fee Core 直接依赖市场名称。

---

# 47. Cash Basis

Generic Cash 应明确定义：

```text
notional =
price
× quantity
× contract_multiplier
```

如果 Cash `contract_multiplier` 应严格为 1：

```text
在 Instrument/Market Authority 验证
```

而不是 Fee Engine 假设。

---

# 48. Contracts Basis

对于当前还没有正式产品能力的 Futures：

P1 只需要定义合法边界。

如果当前 Instrument 无法确定：

```text
contracts
```

则：

```text
FEE_BASIS_UNSUPPORTED
```

Fail Closed。

不要继续用：

```text
contracts = quantity
```

掩盖未建模事实。

如果当前 Generic Futures Conformance 已明确 Quantity 表示 Contracts，则：

```text
由 Generic Futures FeeBasisProvider 显式声明
```

并测试。

---

# 49. 删除 Market Profile 重复 Fee Authority

从：

```text
OnlyMarketProfile
```

删除：

```text
market_fee_schedule_id
```

如果它已经不再参与正式 Authority。

同步删除：

```text
built-in profile 中的对应字段

Config Mapper

Artifact

Tests

Docs
```

不要保留 deprecated property。

---

# 50. Fee Vocabulary 收敛

审计：

```text
OnlyFeeBasis
OnlyFeeCalculationBasis
```

以及其他 Market/Fee 重复 Enum。

原则：

```text
Fee Formula 使用的 Calculation Basis
```

必须只存在一套正式定义：

```text
onlyalpha.fee
```

Market Domain 可以描述：

```text
Instrument Economics
```

但不要维护第二套 Fee Formula Vocabulary。

删除所有重复、未使用、模糊类型。

---

# 51. Built-in Generic Packs 重构

当前：

```text
GENERIC_T0_CASH_CONFORMANCE
```

需要拆成：

```text
GENERIC_T0_MARKET_FEE_PACK
```

以及：

```text
GENERIC_ZERO_BROKER_FEE_CONTRACT
```

或者一个明确测试 Broker Contract。

目的：

> Generic Conformance 也必须使用正式新 Authority 模型。

不能让生产架构是：

```text
Market Pack + Broker Contract
```

但测试架构继续：

```text
旧 FeePolicyPack
```

---

# 52. 当前 Generic T0 暂时对 A 股的兼容

P1 不负责正式 A 股 Fee Pack。

可以选择：

### 方案 A

P1 直接禁止 Generic T0 Market Pack 与：

```text
CN_A_SHARE_CASH
```

兼容。

然后为当前 A-share Conformance 建一个：

```text
CN_A_SHARE_TEST_MARKET_FEE_PACK
```

明确命名为测试/Conformance Authority。

这是更干净的方案，优先推荐。

不要继续让：

```text
GENERIC_T0
```

看起来像正式 A 股费用。

---

# 53. Test/Conformance Pack 命名

所有非生产费率必须明确：

```text
CONFORMANCE
TEST
SIMULATION
```

不能叫：

```text
CN_A_SHARE_STANDARD_FEES
```

却实际上只是假的测试费率。

名称必须传达 Authority 可信程度。

---

# 54. Persistence

检查：

```text
Order Snapshot
Runtime Transaction
Checkpoint
Artifact
Scenario Result
```

哪些真正序列化：

```text
OnlyOrderFeePolicyBinding
```

Binding v1 → v2 是破坏性持久化 Contract 变化。

旧 Binding：

```text
直接拒绝
```

错误：

```text
UNSUPPORTED_ORDER_FEE_BINDING_SCHEMA
```

不要 migration。

---

# 55. Runtime Persistence Schema

只有当正式 Runtime Persistence Payload Contract 因 P1 发生变化时才升级。

不要：

```text
因为这是 P1
→ 所有 Schema +1
```

逐项审计：

```text
Order Snapshot schema
Transaction schema
Checkpoint schema
Artifact schema
Result schema
```

哪一个实际变化：

```text
就升级哪一个
```

旧版本：

```text
Fail Closed
```

---

# 56. Recovery Semantics

P1 必须验证以下核心场景。

## ORDER_FIXED

```text
Day 1
Order Bound
Schedule v1

Checkpoint

安装 Schedule v2

Restart

Day 2 Fill
```

必须：

```text
仍使用 v1
```

---

# 57. FILL_EFFECTIVE

```text
Day 1
Order Bound to Family A

Checkpoint

Family A 安装 v2，Day 2 生效

Restart

Day 2 Fill
```

必须：

```text
解析 v2
```

但同时证明：

```text
Family Scope 与订单绑定时完全相同
```

---

# 58. Scope Drift after Restart

如果 Registry 中：

```text
Family A
```

发生非法 Scope Drift：

```text
Restart/Fill
```

必须：

```text
Fail Closed
```

不能静默应用新 Scope。

---

# 59. Registry Ordering Determinism

必须测试：

```text
注册 A,B,C
```

和：

```text
注册 C,A,B
```

得到：

```text
same Binding fingerprint

same Policy Resolution fingerprint

same Assessment ID

same Fee Application
```

---

# 60. Config Ordering Determinism

如果 YAML 中无语义差异，只是列表顺序不同：

```text
不能改变 Authority Fingerprint
```

前提是该列表业务上是 Set。

如果业务上顺序有意义：

```text
保留顺序并明确测试
```

不要随意 sort 所有字段。

---

# 61. Recovery 不得重新 Binding 已存在订单

这是重要不变量：

```text
Order Fee Binding
```

是：

```text
Order Authority Fact
```

Restart 后：

```text
恢复 Binding
```

而不是：

```text
用当前 Config 重新 bind
```

否则 ORDER_FIXED 的历史 Authority 会被改变。

Architecture Test 必须保证：

```text
restored order
does not rebuild fee binding
```

---

# 62. Runtime Assembly

Backtest/Paper Runtime Factory 应分别解析：

```text
Market Fee Pack

Broker Fee Contract
```

对于 Paper SHADOW：

如果没有启用真实 Broker：

```text
仍必须绑定显式 Simulation Broker Fee Contract
```

或者配置中明确选择：

```text
ZERO_BROKER_FEE_CONTRACT
```

不要因为：

```text
Paper 无 Broker
```

就跳过 Broker Fee Authority。

因为策略的模拟经济结果仍需要确定 Fee Contract。

---

# 63. Broker Config 与 Account Config 关系

Broker Fee Contract 应绑定：

```text
Broker
+
Account
```

不要只绑定：

```text
gateway_id
```

如果多个 Account 共用 Gateway：

```text
仍可以拥有不同 Contract
```

因此 Contract Reference 更适合属于：

```text
Account Runtime Config
```

而不是仅属于：

```text
Broker Runtime Config
```

---

# 64. Multi-Cluster

同一 Runtime：

```text
多个 Cluster
```

共享同一个 Account 时：

```text
Broker Fee Contract
```

应来自 Account Authority。

Cluster 不能选择自己的 Broker Fee Contract。

否则：

```text
同一个真实账户
```

会被不同策略模拟成不同券商合同。

禁止这种设计。

---

# 65. Cluster Boundary

Cluster 可以读取：

```text
绑定后的 Fee Estimate / Funding Plan
```

但不能：

```text
安装 Market Fee Pack
安装 Broker Fee Contract
修改 Fee Schedule
选择 Broker Commission
```

Authority 仍属于 Runtime Composition。

---

# 66. Fee Estimate

Order Estimate 必须消费：

```text
Binding
+
Validated Policy Resolution
+
Basis
```

并验证：

```text
Estimate Authority
==
Binding Authority
```

不能直接通过 Pack 临时重新计算一套没有 Binding Proof 的 Estimate。

---

# 67. Funding Plan

`OnlyOrderFundingPlan` 必须继续使用：

```text
Binding fingerprint
Estimate assumptions fingerprint
```

如果 Binding v2 改变：

```text
Funding Plan 应自然携带新 fingerprint
```

不要为了旧测试维护 v1 fingerprint 计算。

---

# 68. Fee Accrual / Application

P1 不修改其经济语义。

但必须验证它们接受的：

```text
Assessment
```

已经具有完整 Authority Proof。

不要让：

```text
Fee Application
```

自行重新 resolve Policy。

一个 Fee 经济事实的 Authority 应从：

```text
Assessment
```

向后传递，而不是下游重算。

---

# 69. Error Codes

正式收敛错误码：

```text
MARKET_FEE_PACK_NOT_INSTALLED

MARKET_FEE_PACK_DUPLICATE_VERSION

MARKET_FEE_PACK_FINGERPRINT_CONFLICT

MARKET_FEE_PACK_PROFILE_INCOMPATIBLE


BROKER_FEE_CONTRACT_NOT_INSTALLED

BROKER_FEE_CONTRACT_DUPLICATE_VERSION

BROKER_FEE_CONTRACT_FINGERPRINT_CONFLICT

BROKER_FEE_CONTRACT_BROKER_INCOMPATIBLE

BROKER_FEE_CONTRACT_ACCOUNT_INCOMPATIBLE


FEE_SCHEDULE_NOT_FOUND

FEE_SCHEDULE_AMBIGUOUS

FEE_SCHEDULE_SCOPE_DRIFT

FEE_SCHEDULE_EXACT_VERSION_NOT_FOUND

FEE_SCHEDULE_FINGERPRINT_CONFLICT


ORDER_FEE_BINDING_CONFLICT

ORDER_FEE_SCOPE_AUTHORITY_CHANGED

ORDER_FEE_POLICY_AUTHORITY_CONFLICT


FEE_BASIS_UNSUPPORTED

FEE_CURRENCY_CONVERSION_UNSUPPORTED
```

如果当前项目使用统一 Exception Model：

```text
使用正式 typed exception / error code
```

不要到处裸：

```python
raise ValueError("...")
```

但不要为了 P1 额外重写整个异常体系。

---

# 70. 删除清单

完成 P1 后，应彻底删除或替换：

```text
OnlyFeePolicyPack

OnlyFeePolicyPackRegistry

broker_schedules inside fee policy pack

裸 schedule ID namespace

fill_effective_schedule_ids: tuple[str, ...]

market→broker fallback resolve

del binding_fingerprint

FeeResolver._basis() 中 contracts = quantity

OnlyMarketProfile.market_fee_schedule_id

旧 Fee Config:
market.fees.pack_id
market.fees.pack_version
如果已被新 market.fee_pack 替代

所有旧 Binding v1 reader/writer

所有 compat aliases

所有验证旧 Authority 模型的 tests
```

是否删除：

```text
OnlyBrokerFeeScheduleRegistry
OnlyMarketFeeScheduleRegistry
```

取决于新 Registry 设计。

可以保留类型职责正确的独立 Schedule Registry。

---

# 71. Architecture Guards

增加测试，禁止旧设计重新出现。

至少扫描生产代码：

```text
src/onlyalpha/
```

禁止：

```text
class OnlyFeePolicyPack

class OnlyFeePolicyPackRegistry

market_fee_schedule_id

fill_effective_schedule_ids

contracts = quantity

except ValueError:
    broker.resolve
```

以及：

```text
Market Fee Pack
import Broker Fee Schedule
```

和：

```text
Fee Engine
import Runtime/Broker/Persistence
```

---

# 72. Dependency Boundary

推荐依赖：

```text
fee.market_pack
    ↓
fee.schedule / fee.policy

fee.broker_contract
    ↓
fee.schedule / fee.policy

fee.applicability
    ↓
domain identifiers / instrument facts

fee.binding
    ↓
pack/contract identities

fee.resolution
    ↓
binding + registries

fee.engine
    ↓
formula + validated resolution
```

禁止：

```text
fee.engine
→ runtime

fee.engine
→ broker

fee.engine
→ account manager

market profile
→ broker fee contract
```

---

# 73. 测试矩阵：Pack / Contract

必须覆盖：

```text
Market Pack
+ compatible profile
→ PASS

Market Pack
+ incompatible profile
→ FAIL

Unknown Market Pack
→ FAIL

Same Pack identity
same fingerprint
→ defined duplicate semantics

Same Pack identity
different fingerprint
→ conflict


Broker A Contract
+ Broker A Account
→ PASS

Broker A Contract
+ Broker B
→ FAIL

Exact Account Contract
+ another account
→ FAIL

Unknown Contract
→ FAIL
```

---

# 74. 测试矩阵：Applicability

覆盖：

```text
SSE Market Schedule
+ SSE instrument
→ match

SSE Schedule
+ SZSE instrument
→ no match


Cash Schedule
+ Cash instrument
→ match

Cash Schedule
+ Futures instrument
→ no match


Broker A
+ Broker A Contract
→ match

Broker A
+ Broker B Contract
→ no match
```

---

# 75. Exactly-One Tests

必须有：

```text
zero applicable schedule
→ FEE_SCHEDULE_NOT_FOUND

two applicable schedules
→ FEE_SCHEDULE_AMBIGUOUS
```

不能只测试 happy path。

---

# 76. Namespace Tests

构造：

```text
MARKET:
    schedule_id = STANDARD

BROKER:
    schedule_id = STANDARD
```

两者：

```text
必须能够合法共存
```

并分别进入最终 Assessment。

不能产生：

```text
namespace conflict
```

---

# 77. Scope Drift Tests

Market：

```text
same schedule_id
v1 SSE
v2 SZSE
→ FEE_SCHEDULE_SCOPE_DRIFT
```

Broker：

```text
same schedule_id
v1 Broker A
v2 Broker B
→ FEE_SCHEDULE_SCOPE_DRIFT
```

Account Scope Change：

```text
same family
ALL_ACCOUNTS
→ EXACT_ACCOUNT

如果定义为 Scope Change
→ drift
```

---

# 78. ORDER_FIXED Tests

测试：

```text
v1 effective Day1

Order accepted Day1

v2 effective Day2

Fill Day2

→ still v1
```

包括：

```text
Restart before Fill
```

结果必须一致。

---

# 79. FILL_EFFECTIVE Tests

```text
Family A v1 effective Day1
Family A v2 effective Day2

Order accepted Day1

Fill Day2

→ v2
```

但：

```text
Binding family fingerprint
```

仍保持订单创建时的稳定 Scope Authority。

---

# 80. Binding Tamper Tests

分别篡改：

```text
Market Pack fingerprint

Broker Contract fingerprint

Account

Instrument

Scope fingerprint

Schedule Authority Namespace

ORDER_FIXED version

FILL_EFFECTIVE family
```

全部必须：

```text
Fail Closed
```

---

# 81. Cross-Binding Tests

构造：

```text
Binding A

Resolution B
```

即使两者最后 Fee Amount 一样：

```text
必须 FAIL
```

不能只比较金额。

---

# 82. Basis Tests

至少：

```text
Generic Cash
notional 正确

Generic Futures Conformance
contracts 由 Provider 明确提供

unsupported market
→ FEE_BASIS_UNSUPPORTED
```

测试：

```text
Fee Resolver 不再自己推断 contracts
```

---

# 83. Determinism Tests

至少验证：

```text
100 次或 exhaustive lane 中多次

same input
same registration contents
different registration order
```

得到：

```text
same Binding JSON

same Binding fingerprint

same Resolution fingerprint

same Policy fingerprint

same Assessment ID
```

普通 Core Gate 可以执行少量次数。

大量 permutation 放：

```text
exhaustive
```

Lane。

---

# 84. Recovery Tests

至少验证：

```text
Order Bound
Checkpoint
Restart
Fill
```

以及：

```text
before/after registry version addition
```

要求：

```text
ORDER_FIXED exact

FILL_EFFECTIVE family-based
```

完全正确。

不得因为 Restart：

```text
重新 bind order
```

---

# 85. Artifact / Result

如果当前 Artifact 已输出 Fee Authority：

升级为：

```text
Market Fee Pack Identity

Broker Fee Contract Identity

Binding fingerprint

Resolution fingerprint

Schedule identities
```

不要输出巨大完整 Rule Payload，除非项目已有此设计。

Artifact 需要：

```text
可审计
```

但不要：

```text
重复存整个 Runtime 内部对象树
```

---

# 86. 配置示例迁移

修改所有：

```text
examples/
tests/fixtures/
scenario configs
```

使用新正式 Schema。

不要保留：

```text
old_fee_config.yaml
```

除非明确放到：

```text
tests/invalid_config/
```

用于证明旧 Schema 被拒绝。

---

# 87. 旧 Schema 拒绝测试

必须明确测试：

```yaml
market:
  fees:
    pack_id: ...
```

如果该 Schema 已删除：

```text
Config Error
```

而不是：

```text
自动映射到新 fee_pack
```

---

# 88. Documentation

新增 ADR：

```text
docs/adr/
P1 Fee Authority Integrity Closure
```

ADR 必须解释：

```text
为什么 Market Fee 和 Broker Fee 是两个 Authority

为什么 Schedule Scope 是 Resolution Condition

为什么需要 Schedule Namespace

ORDER_FIXED vs FILL_EFFECTIVE

为什么 Order Binding 必须记录 Pack/Contract Identity

为什么 Fee Engine 保持 Pure

为什么 Basis Provider 不属于 Fee Formula
```

---

# 89. Implementation Report

新增：

```text
docs/reports/
p1_fee_authority_integrity_closure.md
```

必须包括：

```text
Before Architecture

Root Problems

Deleted Interfaces

New Authority Model

Config Changes

Schema Changes

Recovery Semantics

Test Matrix

Gate Results

Remaining Technical Debt
```

---

# 90. Roadmap

更新 Roadmap：

```text
P1
CURRENT → DONE
```

并明确：

```text
P2 Fee Reconciliation Semantic Closure
```

仍未完成。

不要在 Roadmap 中把 P1 声称为：

```text
正式 A 股费用完成
```

---

# 91. 推荐提交顺序

## Commit 1 — Audit + ADR

只做：

```text
pre-implementation audit
ADR
设计冻结
```

---

## Commit 2 — Split Market/Broker Authorities

新增：

```text
OnlyMarketFeePack
OnlyMarketFeePackIdentity

OnlyBrokerFeeContract
OnlyBrokerFeeContractIdentity

两个 Registry
```

删除：

```text
OnlyFeePolicyPack
```

---

## Commit 3 — Config + Runtime Assembly

迁移：

```text
Market Fee Pack Config

Broker Fee Contract Config

Component Registries

Backtest Factory

Paper Factory

Scenario/Test factories
```

所有旧 Config 删除。

---

## Commit 4 — Applicability + Namespace

新增：

```text
typed schedule authority

applicability contexts

matches()

exactly-one resolution

scope drift validation
```

删除 fallback resolution。

---

## Commit 5 — Binding v2

加入：

```text
Market Pack Identity

Broker Contract Identity

Scope Identity

ORDER_FIXED exact identity

FILL_EFFECTIVE family identity
```

升级相关 persistence contract。

---

## Commit 6 — Policy Resolution Proof

新增：

```text
OnlyFeePolicyResolution
```

让 Fee Engine 消费已经验证的 Authority Resolution。

删除：

```text
ignored binding fingerprint
```

---

## Commit 7 — Fee Basis Provider

新增：

```text
OnlyFeeBasisProvider
```

删除 Fee Resolver 隐式：

```text
contracts = quantity
```

---

## Commit 8 — Legacy Deletion + Architecture Guards

删除：

```text
old classes
old config
old aliases
old tests
old docs
```

增加架构扫描。

---

## Commit 9 — Recovery / Artifact / Final Report

完成：

```text
Restart
Determinism
Artifact
Report
Roadmap
```

---

# 92. Gate 要求

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

以及插件 mypy。

---

# 93. P0 新 Test Lane

使用当前正式 Lane：

```bash
uv run python scripts/test_suite.py fast

uv run python scripts/test_suite.py integration

uv run python scripts/test_suite.py core-full

uv run python scripts/test_suite.py recovery

uv run python scripts/test_suite.py ashare

uv run python scripts/test_suite.py miniqmt-contract
```

相关 exhaustive：

```bash
uv run python scripts/test_suite.py exhaustive
```

Build：

```bash
uv build --all-packages
```

如果 latest master 已修改 Lane 名称：

```text
使用最新正式命令
```

不要为了 Prompt 恢复旧命令。

---

# 94. 不允许通过测试的方法

禁止：

```text
skip
xfail
降低 assertion
删除 Recovery coverage
让 unknown authority fallback
放宽 schema
默认填充 Broker Contract
默认填充 Market Fee Pack
```

测试失败如果暴露旧测试：

```text
重写测试
```

如果暴露真实架构问题：

```text
修生产代码
```

---

# 95. Completion Architecture

P1 完成后，系统必须能够对任意 Fee Application 追溯：

```text
Fee Application
        ↑
Assessment
        ↑
Policy Resolution
        ↑
Order Fee Binding
        ↑
├── Market Fee Pack
│
└── Broker Fee Contract
```

并回答：

```text
Market Fee Pack:
    id/version/fingerprint

Broker Fee Contract:
    id/version/fingerprint

Applicable Scope:
    market/venue/instrument
    broker/account

Schedule:
    authority namespace
    family
    version
    fingerprint

Binding:
    when / what / why

Resolution:
    ORDER_FIXED or FILL_EFFECTIVE

Basis:
    where quantities came from

Assessment:
    resulting economic target
```

---

# 96. Definition of Done

只有以下全部成立，P1 才算完成：

* [ ] `OnlyFeePolicyPack` 已删除。
* [ ] `OnlyFeePolicyPackRegistry` 已删除。
* [ ] Market Fee 与 Broker Fee 成为不同 Authority。
* [ ] `OnlyMarketFeePack` 存在。
* [ ] `OnlyBrokerFeeContract` 存在。
* [ ] Broker Contract 与 Account/Broker 强绑定。
* [ ] 不存在隐式 Broker Fee 默认值。
* [ ] Schedule Identity 有显式 Authority Namespace。
* [ ] Market/Broker 同名 Schedule 可以合法共存。
* [ ] Schedule Scope 真正参与 Applicability。
* [ ] 0 match Fail Closed。
* [ ] >1 match Fail Closed。
* [ ] 同 Schedule Family Scope Drift 被拒绝。
* [ ] ORDER_FIXED 冻结 exact version。
* [ ] FILL_EFFECTIVE 冻结 authority family。
* [ ] Binding schema 升级。
* [ ] Binding 保存 Market Pack Identity。
* [ ] Binding 保存 Broker Contract Identity。
* [ ] Binding 保存 Applicability Scope。
* [ ] Binding fingerprint 真正参与 Authority Proof。
* [ ] 不再存在 `del binding_fingerprint`。
* [ ] 不允许 Binding A + Policy B。
* [ ] `OnlyFeePolicyResolution` 或等价正式模型存在。
* [ ] Fee Engine 保持 Pure。
* [ ] Fee Resolver 不再隐式 `contracts = quantity`。
* [ ] Fee Basis 由正式 Provider 产生。
* [ ] `OnlyMarketProfile.market_fee_schedule_id` 已删除。
* [ ] Fee Vocabulary 重复项已清理。
* [ ] Restart 不会重新绑定历史订单。
* [ ] ORDER_FIXED Restart 语义正确。
* [ ] FILL_EFFECTIVE Restart 语义正确。
* [ ] Registration Order 不影响 Authority Fingerprint。
* [ ] Old Config 被明确拒绝。
* [ ] 不存在 Compatibility Layer。
* [ ] Architecture Guards 已加入。
* [ ] ADR 完成。
* [ ] Implementation Report 完成。
* [ ] Fast PASS。
* [ ] Integration PASS。
* [ ] Core Full PASS。
* [ ] Recovery PASS。
* [ ] A-share PASS。
* [ ] MiniQMT Contract PASS。
* [ ] Exhaustive relevant tests PASS。
* [ ] Static PASS。
* [ ] Build PASS。

---

# 97. P1 完成后仍然明确未完成

Implementation Report 必须明确写：

```text
NOT IMPLEMENTED IN P1
```

包括：

```text
正式 CN A-share production market fee pack

真实 Broker commission contract

Detailed component fee reconciliation

Typed statement reconciliation period

Market-neutral reconciliation risk-reduction authority

Broker fee evidence port

Paper restart/reconnect

Live runtime

Durable outbound broker command

Multi-market production execution

Vectorized backtest
```

---

# 98. 最终工程原则

这个 PR 不优化：

```text
最小 diff

历史 API 可以继续调用

旧 YAML 还能运行

测试尽量不改

短期兼容方便
```

这个 PR 优化：

```text
唯一 Authority

显式 Authority

稳定 Scope

确定性 Resolution

可证明 Binding

纯计算 Engine

强类型 Domain

Fail Closed

Recoverable

Auditable

Clean Module Boundary
```

---

# 99. 代码质量要求

最终代码必须做到：

```text
一个模块只拥有一种主要职责

类名能够表达真实 Domain 意义

禁止仅为转发旧接口存在的 Wrapper

禁止无意义 Alias

禁止 Dead Code

禁止 Deprecated Compatibility

禁止重复 Vocabulary

禁止循环依赖

禁止 Runtime Business Logic 泄漏到 Fee Engine

禁止 Fee Economics 泄漏到 Runtime Factory

禁止 Broker Contract 泄漏到 Market Profile
```

如果一个旧类删除后：

```text
测试变得更难写
```

优先：

```text
改善新的 Test Factory
```

而不是恢复旧类。

---

# 100. 最终原则

当：

```text
旧接口
```

与：

```text
正确 Authority Boundary
```

冲突时：

**删除旧接口。**

当：

```text
历史测试
```

与：

```text
正式 Domain Invariant
```

冲突时：

**重写历史测试。**

当：

```text
兼容性
```

与：

```text
Fail Closed
```

冲突时：

**选择 Fail Closed。**

当：

```text
减少代码修改量
```

与：

```text
模块边界清晰
```

冲突时：

**选择模块边界清晰。**

当：

```text
暂时能跑
```

与：

```text
Authority 可证明
```

冲突时：

**选择 Authority 可证明。**

P1 的最终目的不是：

> “重构 Fee 文件结构。”

而是：

> **建立一条从 Market Authority 和 Broker Contract，到 Order Binding，到 Fill-time Policy Resolution，再到 Fee Assessment 的完整、强类型、可证明、可恢复且无歧义的经济权威链。**

任何一分钱的本地费用，都必须能够由系统回答：

```text
是谁定义的？

为什么适用于这个订单？

绑定的是什么？

什么时候绑定的？

成交时用了哪个版本？

为什么用了这个版本？

这个结论怎样被 Fingerprint 证明？

Restart 后为什么仍然一致？
```

只有这些问题都可以由正式 Domain Fact 回答，P1 才算完成。
