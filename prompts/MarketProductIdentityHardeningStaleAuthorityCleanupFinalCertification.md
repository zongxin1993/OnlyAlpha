# OnlyAlpha P5.4 — Market Product Identity Hardening, Stale Authority Cleanup & Final Certification

Repository:

`https://github.com/zongxin1993/OnlyAlpha`

当前任务属于 OnlyAlpha P5：

> **Market Product Composition Authority Neutralization**

当前执行阶段：

# P5.4 — Market Product Identity Hardening, Stale Authority Cleanup & Final Certification

本任务必须基于当前 `master` 最新实现执行。

当前 P5.1 / P5.2 / P5.3 已经完成核心架构迁移：

```text
P5.1
Core Market Product Contract
& Composition Authority

P5.2
Generic T0 Cash Market Product Plugin
& Canonical Market IR Authority Closure

P5.3
CN A-share Full Authority Migration
& Trading Runtime One-Shot Cutover
```

当前生产架构已经形成：

```text
OnlyMarketProductConfig
        ↓
OnlyMarketProductFactoryRegistry
        ↓
OnlyMarketProductFactory
        ↓
resolve exactly once
        ↓
OnlyResolvedMarketProductBinding
        ↓
RuntimePlan
        ↓
Backtest / Paper
        ↓
OnlyMarketRuleEngine
        ↓
Canonical Market IR
        ↓
Durable Trading Kernel
```

P5.4 **不得重新设计第二套 Market Product 架构**。

本任务的目标不是继续迁移具体市场，而是完成：

```text
Identity Hardening
+
Stale Authority / Surface Cleanup
+
Persistence / Recovery Identity Closure
+
Architecture Guard Closure
+
P5 Final Certification
```

最终使整个 P5 可以正式标记：

```text
P5
Market Product Composition Authority Neutralization
DONE / CERTIFIED
```

---

# 一、必须先重新阅读当前 master

不要机械执行本 Prompt 中的类名。

首先读取当前 HEAD，确认源码实际状态。

至少重新阅读：

```text
README.md
AGENTS.md

docs/architecture.md
docs/roadmap.md

docs/adr/0068-runtime-product-taxonomy-and-trading-semantic-equivalence.md
docs/adr/0069-*
docs/adr/0070-*

docs/reports/p5_2_*
docs/reports/p5_3_*
```

重点阅读：

```text
src/onlyalpha/canonical.py

src/onlyalpha/market/product/
src/onlyalpha/market/runtime_rules.py

src/onlyalpha/runtime/environment.py
src/onlyalpha/runtime/planning.py
src/onlyalpha/runtime/assembler.py
src/onlyalpha/runtime/backtest/
src/onlyalpha/runtime/paper/

src/onlyalpha/persistence/
src/onlyalpha/recovery/

src/onlyalpha/result/
src/onlyalpha/artifact/

src/onlyalpha/plugin/api.py

packages/market/onlyalpha-market-generic-t0-cash/
packages/market/onlyalpha-market-cn-ashare/

tests/architecture/
tests/conformance/
tests/recovery/
tests/runtime/
```

必须以当前真实代码为准。

---

# 二、从第一性原理理解 P5.4

不要从：

```text
“还剩哪些旧类名？”
```

开始。

先回答：

> 一个 Trading Runtime 怎么证明“当前实际使用的市场经济制度”和创建 checkpoint、artifact、result 时是完全同一套？

真正决定 Market Economic Semantics 的不是：

```text
CN_A_SHARE_CASH
```

这个名字本身。

而是：

```text
Market Product Identity
+
Reference Authority
+
Policy Compiler
+
Market Fee Authority
+
Effective Product Configuration
```

所以真正的经济环境是：

```text
Effective Market Product Composition
```

P5.4 必须把这个事实变成：

```text
explicit
canonical
deterministic
immutable
persistable
recoverable
auditable
fail-closed
```

的正式 Identity Contract。

---

# 三、P5.4 的核心问题

当前 P5.3 已经有：

```text
OnlyMarketProductCompositionIdentity
```

包含：

```text
Product Identity
Reference Authority Identity
Policy Compiler Identity
Market Fee Pack Identity
Effective Config Fingerprint
```

这个结构本身是正确方向。

P5.4 不应该重新发明：

```text
OnlyMarketProductCompositionIdentityV2
```

真正要解决的是：

> 这些 Identity 最底层到底如何生成？

如果当前 canonical serialization 仍允许：

```text
arbitrary to_dict()
arbitrary __str__()
arbitrary Mapping key str()
```

进入正式 Authority fingerprint，

那么系统仍然没有真正的 Identity Boundary。

---

# 四、最重要的第一性原理

必须冻结：

> **Serializable ≠ Identifiable**

一个对象：

```text
能够打印
能够 JSON 化
拥有 to_dict()
```

不代表它拥有正式：

```text
Economic Identity
```

因此正式 Authority Identity 不得依赖：

```text
magic reflection
magic stringify
```

必须由 Authority owner 显式声明。

---

# 五、P5.4 最终核心不变量

整个实现必须满足：

```text
1. Formal Authority Identity must be explicit.

2. Unknown identity representation fails closed.

3. Same effective economics → same fingerprint.

4. Different effective economics → different fingerprint.

5. Runtime Type does not affect Market Economic Identity.

6. Transport/location details do not affect Market Economic Identity.

7. Raw config does not directly define economic identity.

8. Effective authorities define composition identity.

9. Recovery validates composition before mutable restore.

10. Product ID is evidence, never behavior selector.

11. No legacy Market Profile authority remains.

12. No compatibility alias or dual identity path remains.
```

---

# 六、P5.4.1 — Formal Canonical Identity Contract

首先审计当前：

```text
src/onlyalpha/canonical.py
```

如果正式 Authority fingerprint 当前依赖一个过于宽松的通用 canonical serializer：

不要直接继续扩张它。

应该明确区分：

```text
General deterministic serialization

vs

Formal economic identity serialization
```

---

# 七、不要粗暴破坏所有普通 canonical serialization

项目可能已经使用：

```text
only_canonical_fingerprint()
```

做普通：

```text
config
resource
environment
test evidence
```

fingerprint。

P5.4 不应该为了 Market Authority Identity 把整个工程所有普通 deterministic serialization 一次性重写。

更合理的分层：

```text
General Canonical Serialization
    ↓
deterministic internal values

Formal Identity Serialization
    ↓
Authority / Composition / Recovery Evidence
```

两者可以共享底层 JSON encoding。

但 Formal Identity 层必须严格。

---

# 八、建议建立显式 Identity Contract

根据现有命名风格，可以实现类似：

```python
class OnlyCanonicalIdentityProvider(Protocol):
    def canonical_identity(self) -> OnlyCanonicalIdentityValue:
        ...
```

具体命名可根据源码调整。

这不是一个新业务 Authority。

它只回答：

```text
“我作为正式 Identity，究竟由哪些字段定义？”
```

不能拥有业务行为。

---

# 九、Formal Identity 支持的值必须有限

建议正式允许：

```text
None
bool
int
str
Decimal
date
UTC datetime

tuple[CanonicalValue, ...]

Mapping[str, CanonicalValue]

Explicit Identity Provider
```

是否允许 Enum，应根据当前 Domain type pattern决定；如果允许，应明确转成其 canonical value。

不要无限扩大类型集合。

---

# 十、正式 Economic Identity 不允许 arbitrary float

如果 Market Authority identity 中出现：

```python
float
```

应 fail closed。

经济数值应该使用：

```text
Decimal
```

原因：

```text
tick
price limit
fee rate
ratio
quantity step
```

这些都是正式经济语义。

不要让二进制 floating-point representation 成为经济 Identity 的一部分。

---

# 十一、Mapping key 必须严格

如果当前 canonical serializer 使用：

```python
str(key)
```

把任意 key 归一成字符串：

正式 Identity 中必须禁止。

要求：

```text
Mapping key must be str
```

否则：

```text
1
"1"
```

可能被隐式压成同一 canonical key。

Formal Identity 中：

```text
non-string key
→ fail closed
```

---

# 十二、禁止 arbitrary `to_dict()` fallback

正式 Authority Identity 不能：

```text
不知道 object 是什么
→ 看它有没有 to_dict()
→ 自动当 identity
```

因为：

```text
Serialization DTO
```

和：

```text
Economic Identity
```

不是一个合同。

因此 Formal Identity 路径：

```text
arbitrary to_dict()
→ forbidden
```

---

# 十三、禁止 arbitrary `__str__()` fallback

正式 Identity 更不能：

```text
unknown object
→ str(object)
→ SHA256
```

只有显式：

```text
canonical_identity()
```

或明确支持的 canonical primitive 才能进入正式 Authority fingerprint。

Unknown object：

```text
→ OnlyCanonicalIdentityError
或 TypeError
```

必须 fail closed。

---

# 十四、Path 不应直接成为 Market Economic Identity

这是重要规则。

例如：

```text
/home/user/reference.csv

/opt/onlyalpha/reference.csv
```

如果内容完全相同：

不应该产生不同 Market Composition Identity。

因此：

```text
filesystem Path
```

不能作为正式 Market Economic Identity。

资源应 resolve 成：

```text
dataset_id
dataset_version
content_fingerprint
```

之后再参与 Identity。

---

# 十五、set/frozenset 不应自动决定业务语义

一个集合：

```text
order does not matter
```

本身就是业务定义。

Canonical identity layer 不应该自动帮业务对象决定：

```text
set
→ sorted
```

如果某个 Authority 语义确实无序：

由 Authority owner 显式：

```text
sort
→ tuple
→ canonical identity
```

Formal Identity 层优先不接受裸 set/frozenset。

---

# 十六、Dataclass reflection 也需要谨慎

当前如果：

```text
dataclass
→ 自动枚举所有 public field
→ fingerprint
```

那么未来增加：

```python
debug_label
source_path
loaded_at
```

就可能意外改变经济 Identity。

因此正式 Authority 类型不应依赖：

```text
automatic dataclass reflection
```

来决定经济 identity。

应显式：

```python
canonical_identity()
```

声明真正参与 identity 的字段。

---

# 十七、P5.4.2 — 迁移正式 Market Identity Types

至少审计：

```text
OnlyMarketProductPluginId
OnlyMarketProductId
OnlyMarketProductVersion

OnlyMarketProductIdentity

OnlyMarketProductAuthorityIdentity

OnlyMarketProductCompositionIdentity

OnlyMarketFeePackIdentity

OnlyCompiledMarketPolicyIdentity
```

以及任何真正进入：

```text
Persistence
Checkpoint
Recovery
Artifact
Result
```

compatibility 判断的 Identity。

---

# 十八、Product Identity 显式定义

`OnlyMarketProductIdentity` 应正式声明：

```text
product_id
product_version
```

就是它的 canonical identity。

不要自动把未来其它字段加入 hash。

例如未来增加：

```python
display_name
```

不应自动改变经济身份。

---

# 十九、Authority Identity 显式定义

`OnlyMarketProductAuthorityIdentity` 应明确：

```text
authority_kind
authority_id
authority_version
authority_fingerprint
```

组成正式 Identity。

并继续校验：

```text
authority_fingerprint
```

是合法 digest。

---

# 二十、Composition Identity 继续使用 Effective Authorities

Composition Identity 必须始终只来自：

```text
product_identity

reference_authority_identity

policy_compiler_identity

market_fee_pack_identity

effective_config_identity
```

不允许：

```text
raw config
local path
runtime type
Python module name
object memory address
```

进入 composition identity。

---

# 二十一、P5.4.3 — Effective Config Identity Audit

重点审计：

```text
Generic T0 plugin config
CN A-share plugin config
```

要求：

```text
Raw Config
    ↓
strict parse
    ↓
Typed Plugin Config
    ↓
resolve resource
    ↓
Effective Product Configuration
    ↓
Formal Identity
```

不能：

```text
raw YAML
→ hash
→ economic identity
```

---

# 二十二、未知 Plugin Config 字段必须失败

例如：

```yaml
market:
  config:
    reference_resource: abc
    unknown_option: 123
```

如果 `unknown_option` 没有正式语义：

不能静默忽略。

应该：

```text
INVALID_MARKET_PRODUCT_CONFIGURATION
```

失败。

原因：

> 配置表面必须等于真实支持能力。

不要让用户以为一个字段有效，但系统实际上不使用它。

---

# 二十三、Raw resource locator 与 Effective Authority Identity 分离

例如 config 里有：

```text
reference_resource_id
```

它只是：

```text
lookup key
```

如果两个 lookup key 最终 resolve 到同一个：

```text
Reference Authority Identity
```

Market Composition fingerprint 应保持一致。

原则：

```text
transport identity
!=
economic identity
```

---

# 二十四、P5.4.4 — Authority Identity Conflict

必须正式冻结：

```text
same authority kind
same authority id
same authority version
```

不允许对应两个不同 semantic fingerprint。

例如：

```text
CN_A_SHARE_RULES@3
fingerprint=A
```

与：

```text
CN_A_SHARE_RULES@3
fingerprint=B
```

同时存在：

必须：

```text
OnlyMarketProductAuthorityConflictError
```

fail closed。

---

# 二十五、Version 必须有意义

如果：

```text
authority_id + version
```

没有稳定语义，那 version 就失去了意义。

P5.4 应用 contract tests 保证：

```text
same id + same version
→ same semantic fingerprint
```

如果内容不同：

必须 version bump 或 identity conflict。

---

# 二十六、Product Version 也一样

例如：

```text
CN_A_SHARE_CASH@2025.1
```

在同一正式产品定义中不能对应不同：

```text
session
price limit
quantity
settlement
```

经济规则。

如果规则变化：

必须：

```text
new Product Version
```

而不是复用旧版本号产生新 fingerprint。

---

# 二十七、P5.4.5 — Runtime Mode Neutrality Final Audit

正式搜索所有：

```text
OnlyRuntimeMode
BACKTEST
PAPER
SIM
LIVE
```

进入 Market Product identity / compiler / reference / fee / canonical policy 的路径。

必须证明：

```text
Market Product Composition Identity
```

完全独立于 Runtime Type。

---

# 二十八、建立跨 Runtime Identity Contract

即使 SIM/LIVE 当前未实现，也可以做纯 identity test：

同样：

```text
Product
Reference
Compiler
Fee
Effective Config
```

假设外层 Runtime label 分别为：

```text
BACKTEST
PAPER
SIM
LIVE
```

Market Composition fingerprint 必须完全相同。

Runtime Type 只能影响：

```text
Runtime Environment Identity
```

不能影响：

```text
Market Economic Identity
```

---

# 二十九、P5.4.6 — 清理 Profile-era stale vocabulary

P5.3 已删除 Market Profile production authority。

P5.4 必须再次全仓审计：

```text
profile
market_profile
profile_id
profile_version
effective_profile
```

但不要机械删除。

必须分类。

---

# 三十、Profile vocabulary 分类规则

分成：

```text
A. Obsolete Market Profile Authority
→ DELETE

B. Historical durable schema field
actually means Market Product
→ RENAME + schema bump

C. Risk Profile
→ KEEP

D. Streaming compatibility profile
→ P6 scope, KEEP if still authoritative there

E. Documentation/history
→ keep only if clearly historical
```

不能因为名字包含 `profile` 就全部删除。

---

# 三十一、重点审计 MarketRuleEngine rule code

如果当前正式 pre-trade rule code 仍有：

```text
EFFECTIVE_PROFILE_RESOLUTION
```

而当前实际 Authority 已经是：

```text
Binding
→ Compiler
→ Effective Market Policy
```

那么这个名称已经语义错误。

建议改为类似：

```text
EFFECTIVE_MARKET_POLICY_RESOLUTION
```

具体名称结合现有 naming convention。

---

# 三十二、不要为了兼容旧 rule code 保留 alias

禁止：

```text
EFFECTIVE_PROFILE_RESOLUTION
→ alias
EFFECTIVE_MARKET_POLICY_RESOLUTION
```

如果该 code 进入 checkpoint/durable schema：

正式 bump schema。

不要永久兼容旧 spelling。

---

# 三十三、Checkpoint schema 应显式升级

如果修改：

```text
rule code
result field
artifact field
identity field
```

等 durable schema：

明确：

```text
schema_version 5
→ schema_version 6
```

旧版本：

```text
CHECKPOINT_SCHEMA_UNSUPPORTED
```

fail closed。

不要创建：

```text
v5_to_v6_compatibility_adapter
```

当前仍是 Alpha 阶段，应利用窗口清理错误 schema。

---

# 三十四、P5.4.7 — Result / Artifact Market Identity Audit

检查：

```text
Runtime Result
Backtest Result
Artifact
Report
Durable metadata
Analytics metadata
```

是否仍有：

```text
market_profile_id
profile_version
profile_fingerprint
```

实际表达 Market Product。

如果有：

改成真正语义：

```text
market_product_provider
market_product_id
market_product_version
market_composition_fingerprint
```

---

# 三十五、不要保留双字段

禁止：

```text
profile_id
+
market_product_id
```

同时存在。

禁止：

```python
@property
def profile_id(self):
    return self.market_product_id
```

这种 compatibility layer。

如果 schema 需要改：

正式改。

更新所有调用者和 fixture。

---

# 三十六、Artifact 应留下足够的 Market Evidence

一个正式 Artifact 至少应能够回答：

```text
这个 Product 是谁？

Product Version 是什么？

由哪个 Provider 提供？

本次有效 Market Composition Fingerprint 是什么？
```

根据当前 Artifact 结构决定是否需要完整保存：

```text
Reference Authority Identity
Compiler Identity
Fee Identity
```

不要为了“信息越多越好”无限 dump。

只保留审计真正需要的 Evidence。

---

# 三十七、P5.4.8 — Persistence / Recovery Identity Closure

P5.3 已经把：

```text
market_composition_fingerprint
```

写入 persistence/checkpoint。

P5.4 要证明：

> mismatch 一定发生在任何 mutable state restore 之前。

---

# 三十八、Recovery 顺序必须正确

正确：

```text
Load Checkpoint
      ↓
Validate schema
      ↓
Validate Market Composition Identity
      ↓
Validate other environment compatibility
      ↓
PASS
      ↓
Restore mutable trading authorities
```

错误：

```text
Restore Position
Restore Account
      ↓
发现 Market mismatch
```

必须用测试证明顺序。

---

# 三十九、Recovery mismatch matrix

至少新增测试：

```text
Reference fingerprint changed
→ FAIL

Compiler fingerprint changed
→ FAIL

Market Fee Pack changed
→ FAIL

Effective config changed
→ FAIL

Product version changed
→ FAIL

Product provider mismatch where relevant
→ FAIL
```

---

# 四十、Runtime Type change 与 Market Identity change 区分

如果只是：

```text
BACKTEST
→ future SIM
```

Market composition 本身不应变化。

如果 recovery contract 不允许跨 Runtime 恢复：

可以由：

```text
Runtime Environment compatibility
```

拒绝。

但不能让：

```text
Market Composition Fingerprint
```

跟 Runtime Type 一起变化。

这两个 Authority 必须分层。

---

# 四十一、P5.4.9 — Plugin API Final Audit

审计：

```text
src/onlyalpha/plugin/api.py
```

问题只有一个：

> 一个未来 `onlyalpha-market-hk-equity` 到底真正需要哪些 Core SPI？

保留最小稳定 contract。

---

# 四十二、Market Product Plugin 应优先只依赖 public SPI

具体 Market package 应避免从：

```text
onlyalpha.market.internal...
onlyalpha.runtime...
```

等 private 路径抓类型。

应主要依赖：

```text
onlyalpha.plugin.api
```

如果当前正式 SPI 缺少一个真正必要的 canonical type：

可以增加。

但不要把整个 Core 变成 public API。

---

# 四十三、不要为了方便扩大 plugin.api

禁止：

```text
“插件里刚好要用，所以 Core 什么都 export”
```

SPI 应围绕：

```text
Market Product Contract
Canonical IR
Domain identity/value primitives
Market Fee definition primitives
Canonical Identity contract
```

保持最小。

---

# 四十四、P5.4.10 — Permanent Architecture Guards

把 P5.1–P5.3 的临时 migration guards 收敛为永久 architecture tests。

必须保证：

```text
Core concrete market import = 0

Core A-share implementation = 0

Runtime market-id behavioral branch = 0

MarketRuleEngine product-id dispatch = 0

Implicit Generic fallback = 0

Legacy Market Profile production authority = 0

Runtime Mode market economic branch = 0
```

---

# 四十五、Formal Identity Guards

新增：

```text
Authority identity arbitrary __str__ fallback = forbidden

Authority identity arbitrary to_dict fallback = forbidden

Authority identity float = rejected

Authority identity non-string mapping key = rejected

Authority identity unknown object = rejected
```

---

# 四十六、Concrete Plugin dependency guard

Generic/A-share Market Product Plugin 不得 import：

```text
onlyalpha.runtime
onlyalpha.order
onlyalpha.position
onlyalpha.account
onlyalpha.risk
onlyalpha.execution
onlyalpha.transaction
```

也不得 import：

```text
Virtual Broker implementation
Real Broker implementation
DataSource implementation
```

Market Product 只定义：

```text
market economics
```

---

# 四十七、Core dependency guard

Core 不得 import：

```text
onlyalpha_market_generic_t0_cash
onlyalpha_market_cn_ashare
```

未来也不能：

```text
onlyalpha_market_hk_equity
```

Concrete product 必须通过 discovery/registry 进入。

---

# 四十八、P5.4.11 — Identity Contract Test Matrix

新增专门 Identity tests。

至少覆盖：

```text
Case 1

same effective config
same authority
different raw key order

→ SAME fingerprint
```

```text
Case 2

same Reference content
different resource locator/path

→ SAME economic fingerprint
```

```text
Case 3

Reference content changed

→ DIFFERENT
```

```text
Case 4

Compiler semantic version changed

→ DIFFERENT
```

```text
Case 5

Fee Pack changed

→ DIFFERENT
```

```text
Case 6

Effective Product Config changed

→ DIFFERENT
```

```text
Case 7

Runtime Type changes

→ Market Composition SAME
```

```text
Case 8

Unknown identity object

→ FAIL
```

```text
Case 9

float enters formal economic identity

→ FAIL
```

```text
Case 10

Mapping key is not string

→ FAIL
```

---

# 四十九、Authority conflict tests

必须测试：

```text
same authority id
same authority version
same fingerprint
→ valid
```

以及：

```text
same authority id
same authority version
different fingerprint
→ FAIL
```

不要：

```text
last registration wins
```

---

# 五十、Composition identity tests

必须验证：

```text
same Product
same Reference
same Compiler
same Fee
same Effective Config

→ same Composition Identity
```

任何一项变化：

```text
→ different Composition Identity
```

---

# 五十一、P5.4.12 — Economic Regression Certification

P5.4 不是经济功能开发。

必须确保：

```text
architecture / identity changes
≠
trading economics changes
```

继续以：

```text
GENERIC_T0_CASH
CN_A_SHARE_DURABLE_BACKTEST_V1
```

作为强 regression oracle。

---

# 五十二、A-share Certified Product 必须保持

相同：

```text
fixtures
bars
strategy
broker facts
```

必须保持：

```text
Orders
Trades
Position
Allocation
Account
Strategy Ledger
Fees
Settlement
Transactions
PnL
```

完全一致。

---

# 五十三、允许 Identity schema change

P5.4 很可能会改变：

```text
checkpoint schema
artifact identity field
result identity field
composition hash implementation
```

因此：

```text
structural fingerprint
```

合理地可能变化。

但是必须明确区分：

```text
Identity schema migration
```

和：

```text
Economic result migration
```

后者不允许。

---

# 五十四、P5.4.13 — Determinism Certification

必须验证：

```text
same inputs
same effective authorities
same code
→ same Result fingerprint

same Artifact fingerprint

same Composition identity

same transaction/result economic facts
```

Memory 和 SQLite 都必须验证。

---

# 五十五、Recovery Certification

必须继续验证：

```text
Uninterrupted execution
==
Checkpoint + Restart
==
Forward Recovery
```

并且：

```text
Market composition mismatch
→ fail closed
```

---

# 五十六、P5.4 Final Certification 不是只看 pytest

必须分成：

## Structural Certification

```text
one Market Product composition authority

Core concrete market = 0

Runtime concrete market branch = 0

Plugin mutable trading authority = 0
```

## Identity Certification

```text
explicit identity

deterministic identity

unknown identity fail closed

authority conflicts fail closed
```

## Economic Certification

```text
Generic economics unchanged

A-share certified economics unchanged
```

## Recovery Certification

```text
same composition restore works

different composition restore rejects
```

## Build / Static Certification

```text
ruff
mypy
package build
architecture guards
same-SHA CI
```

---

# 五十七、P5.4 不实现的内容

严格禁止扩大任务到：

```text
SIM

PAPER → SIM

SHADOW deletion

Streaming reconnect

Realtime gap recovery

Research Runtime

Vectorized Research

Durable Broker outbound command

Broker reconciliation

Live Runtime
```

这些分别属于：

```text
P6
P7
P8
P9
```

---

# 五十八、P5.4 不重新设计 Market Product 架构

禁止新建：

```text
MarketProductBindingV2

MarketProductManager

UniversalMarketAuthority

MarketIdentityGraph

UniversalMarketDSL
```

当前：

```text
Config
→ Registry
→ Factory
→ Binding
→ Runtime
```

架构已经正确。

P5.4 是 hardening，不是 redesign。

---

# 五十九、P5.4 不创建万能 Identity Framework

禁止：

```text
UniversalSemanticIdentityEngine

DistributedIdentityRegistry

SchemaDSL

ReflectionBasedAuthorityGraph
```

只实现当前真实需求：

```text
formal canonical authority identity

composition identity

persistence compatibility

recovery compatibility

artifact/result evidence
```

保持薄、明确、可测试。

---

# 六十、代码整洁要求

所有新增代码必须：

```text
small responsibility

typed

immutable where appropriate

explicit contract

no hidden fallback

no magic reflection for authority identity

no circular import workaround

no compatibility alias

no deprecated wrapper

no dual identity path

no duplicate authority
```

如果出现：

```text
if hasattr(obj, ...)
```

来猜 identity：

优先认为设计错误。

---

# 六十一、模块边界要求

推荐形成：

```text
Identity Layer
    only defines canonical identity

Market Product Layer
    defines market product composition identity

Runtime Layer
    consumes market composition evidence

Persistence Layer
    stores compatibility evidence

Recovery Layer
    validates evidence before restore

Artifact Layer
    publishes evidence
```

不要让：

```text
Persistence
```

自己重新算 Market Product Identity。

不要让：

```text
Artifact
```

自己重新解析 Product config。

全部消费已经 authoritative 的 identity。

---

# 六十二、Identity 必须“算一次、传下去”

不要：

```text
Binding 算一次

Environment 自己再 hash 一次 raw config

Persistence 再 hash 一次

Artifact 再算一次
```

正确：

```text
Effective Authorities
        ↓
Composition Identity
        ↓
Binding
        ├── Environment
        ├── Persistence
        ├── Recovery
        ├── Result
        └── Artifact
```

同一个 authoritative identity 被消费。

---

# 六十三、P5.4 推荐实施顺序

严格建议按以下顺序：

```text
Phase 1
Identity producer/consumer audit

Phase 2
Formal Canonical Identity Contract

Phase 3
Migrate Market Product formal identities

Phase 4
Effective Config identity audit

Phase 5
Authority conflict hardening

Phase 6
Runtime-mode identity neutrality tests

Phase 7
Profile-era stale schema cleanup

Phase 8
Persistence / Recovery identity hardening

Phase 9
Result / Artifact identity migration

Phase 10
Plugin API final audit

Phase 11
Architecture guard closure

Phase 12
Economic / Recovery / Determinism certification

Phase 13
same-SHA remote CI certification

Phase 14
P5 final documentation closure
```

---

# 六十四、不要在实现早期修改 roadmap 为 DONE

必须先：

```text
code
tests
build
remote quality gate
```

全部闭环。

最后再声明：

```text
P5 DONE / CERTIFIED
```

---

# 六十五、推荐 Commit 拆分

建议大约四个逻辑 commit：

```text
Commit 1
Refactor: Harden formal canonical authority identity

Commit 2
Refactor: Close Market Product identity and recovery evidence

Commit 3
Cleanup: Remove stale Market Profile identity surfaces

Commit 4
Test/Docs: Certify P5 Market Product Composition Authority
```

这些是一个连续 P5.4。

不要形成长期并存的中间 compatibility architecture。

---

# 六十六、P5.4 Definition of Done

只有全部满足才能结束。

## Formal Identity

```text
[ ] Formal Authority Identity 有独立严格入口

[ ] arbitrary to_dict fallback 不参与 Authority identity

[ ] arbitrary __str__ fallback 不参与 Authority identity

[ ] unknown object fail closed

[ ] float 不允许进入 economic identity

[ ] Mapping key 必须 str

[ ] local Path 不进入 Market economic identity

[ ] Authority identity 不依赖 dataclass reflection magic
```

---

## Explicit Identity

```text
[ ] Product Identity 显式

[ ] Authority Identity 显式

[ ] Fee Identity 显式

[ ] Compiled Policy Identity 显式

[ ] Composition Identity 显式

[ ] Effective Config Identity 显式
```

---

## Identity Semantics

```text
[ ] same economics → same fingerprint

[ ] changed Reference → changed fingerprint

[ ] changed Compiler → changed fingerprint

[ ] changed Fee → changed fingerprint

[ ] changed Effective Config → changed fingerprint

[ ] Runtime Type change → Market Composition unchanged

[ ] same id/version + different fingerprint → conflict
```

---

## Runtime

```text
[ ] Backtest 不 resolve Market Product

[ ] Paper 不 resolve Market Product

[ ] Runtime 不重新计算 concrete market semantics

[ ] Product ID 不作为 behavior selector

[ ] Runtime Type 不进入 Market economic identity
```

---

## Recovery

```text
[ ] composition fingerprint 持久化

[ ] restore 前验证 composition

[ ] Reference mismatch fail closed

[ ] Compiler mismatch fail closed

[ ] Fee mismatch fail closed

[ ] Effective config mismatch fail closed

[ ] mismatch 发生在任何 mutable restore 之前
```

---

## Stale Surface Cleanup

```text
[ ] obsolete Market Profile Authority = 0

[ ] obsolete Market Profile behavior selectors = 0

[ ] stale result/artifact Market Profile spelling 已处理

[ ] stale checkpoint Market Profile rule code 已处理

[ ] 必要 durable schema 已正式 bump

[ ] 无 compatibility alias

[ ] 无 deprecated wrapper
```

---

## Plugin API

```text
[ ] onlyalpha.plugin.api 保持最小稳定 SPI

[ ] Generic/A-share plugin 主要依赖正式 SPI

[ ] Core 不 import concrete market package

[ ] concrete Market Plugin 不 import Runtime mutable authorities
```

---

## Architecture Guards

```text
[ ] Core concrete market import = 0

[ ] Core A-share semantic implementation = 0

[ ] Runtime product-id behavioral branch = 0

[ ] MarketRuleEngine product-id branch = 0

[ ] implicit Generic fallback = 0

[ ] Runtime-mode market economic branch = 0

[ ] duplicate Market Product composition path = 0
```

---

## Regression

```text
[ ] Generic T0 PASS

[ ] CN A-share PASS

[ ] CN_A_SHARE_DURABLE_BACKTEST_V1 PASS

[ ] Memory PASS

[ ] SQLite PASS

[ ] Checkpoint PASS

[ ] Restart PASS

[ ] Forward Recovery PASS

[ ] Determinism PASS
```

---

## Engineering Quality

```text
[ ] ruff check PASS

[ ] ruff format --check PASS

[ ] Core strict mypy PASS

[ ] Generic market plugin strict mypy PASS

[ ] CN A-share plugin strict mypy PASS

[ ] uv build --all-packages PASS

[ ] git diff --check PASS
```

---

## Remote Certification

```text
[ ] same-SHA GitHub Actions static PASS

[ ] same-SHA build PASS

[ ] same-SHA core-full PASS

[ ] same-SHA ashare PASS

[ ] same-SHA recovery PASS

[ ] same-SHA quality-gate PASS
```

只有同一个最终 P5.4 SHA 的质量门禁全部成功：

才能正式声明：

```text
P5 DONE / CERTIFIED
```

---

# 六十七、建议静态搜索

完成后至少执行：

```bash
rg -n 'onlyalpha_market_cn_ashare|onlyalpha_market_generic_t0_cash' src/onlyalpha
```

目标：

```text
concrete import = 0
```

执行：

```bash
rg -n 'OnlyMarketProfile|MarketProfileRegistry|MarketProfileRequest|ResolvedMarketProfile' src/onlyalpha tests
```

逐个分类。

不允许 active production Market Profile authority。

---

执行：

```bash
rg -n 'EFFECTIVE_PROFILE_RESOLUTION' src tests packages
```

如果该 vocabulary 已正式迁移：

目标：

```text
0 active spelling
```

---

执行：

```bash
rg -n 'CN_A_SHARE_CASH|GENERIC_T0_CASH' src/onlyalpha
```

允许：

```text
identity evidence
artifact evidence
test fixtures where appropriate
```

禁止：

```text
if/match behavioral dispatch
```

---

执行 Formal Identity 相关搜索：

```bash
rg -n '__str__|to_dict' src/onlyalpha/market/product src/onlyalpha/identity
```

逐个确认：

```text
没有 magic identity fallback
```

---

# 六十八、正式验证命令

先读取当前：

```text
AGENTS.md
pyproject.toml
.github/workflows/
scripts/test_suite.py
```

使用仓库正式命令。

至少运行适用的：

```bash
uv sync --frozen --all-packages --all-groups

uv run ruff check src tests examples packages scripts
uv run ruff format --check src tests examples packages scripts

uv run mypy src/onlyalpha
```

Generic plugin：

```bash
uv run mypy \
  --config-file packages/market/onlyalpha-market-generic-t0-cash/pyproject.toml \
  packages/market/onlyalpha-market-generic-t0-cash/src/onlyalpha_market_generic_t0_cash
```

A-share plugin：

```bash
uv run mypy \
  --config-file packages/market/onlyalpha-market-cn-ashare/pyproject.toml \
  packages/market/onlyalpha-market-cn-ashare/src/onlyalpha_market_cn_ashare
```

Build：

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
Formal Identity tests

Composition Identity matrix

Authority conflict tests

Recovery mismatch tests

Architecture guards

Result/Artifact schema tests
```

最后：

```bash
git diff --check
```

---

# 六十九、P5 Final Certification Report

完成后新增或更新一份正式 P5.4/P5 Final Certification Report。

建议：

```text
docs/reports/
p5_4_market_product_identity_hardening_and_final_certification.md
```

必须记录：

```text
1. Starting master SHA

2. P5.3 certified baseline

3. Identity problems found

4. Final formal identity contract

5. Canonical value rules

6. Types deliberately rejected

7. Effective config identity model

8. Authority conflict semantics

9. Market Product identity hierarchy

10. Runtime vs Market identity separation

11. Persistence / Recovery compatibility

12. Result / Artifact schema migration

13. Profile-era stale surfaces removed

14. Plugin API final state

15. Architecture guards

16. Generic regression

17. CN A-share regression

18. CN_A_SHARE_DURABLE_BACKTEST_V1 result

19. Memory/SQLite/Recovery/Determinism

20. local validation

21. same-SHA remote validation

22. Final P5 certification status

23. Remaining work belonging to P6/P7/P8/P9
```

---

# 七十、不要修改历史事实

P5.3 report 如果当时写：

```text
NOT YET ACCEPTED
```

因为当时 build gate 被环境阻塞：

不要把历史记录改成“当时其实已通过”。

P5.4 Final Certification 应记录：

```text
P5.3 local report state
+
later same-SHA remote build/quality evidence
```

最终形成完整审计链。

---

# 七十一、Roadmap 最终状态

只有 P5.4 最终 SHA 全部认证通过后：

更新：

```text
P5.1 DONE
P5.2 DONE
P5.3 DONE
P5.4 DONE / CERTIFIED

P5
Market Product Composition Authority Neutralization
DONE / CERTIFIED
```

然后：

```text
Current Stage → P6
```

---

# 七十二、P5.4 完成后的目标架构

最终：

```text
                     CONFIG
                       │
                       ▼
             Market Product Config
                       │
                       ▼
              Factory Registry
                       │
                       ▼
                    Factory
                       │
                       ▼
         Effective Market Authorities
                       │
                       ▼
        Resolved Market Product Binding
                       │
             ┌─────────┼─────────┐
             │         │         │
             ▼         ▼         ▼
         Runtime   Persistence  Artifact
             │         │         │
             └─────────┴─────────┘
                       │
                       ▼
          Composition Identity Evidence
```

正式 Identity chain：

```text
Product Identity
        +
Reference Authority Identity
        +
Compiler Identity
        +
Market Fee Identity
        +
Effective Config Identity
        ↓
Market Product Composition Identity
        ↓
Composition Fingerprint
        ↓
Environment
Persistence
Checkpoint
Recovery
Result
Artifact
```

---

# 七十三、P5.4 完成后新增 HK 市场应该是什么体验

假设未来增加：

```text
onlyalpha-market-hk-equity
```

只需要：

```text
package

typed config

Reference Authority

Policy Compiler

Market Fee Pack

Factory

Entry Point

Tests
```

不能修改：

```text
Backtest Factory
Paper/Sim Factory
Runtime Environment
MarketRuleEngine
Execution
Transaction
Position
Account
Recovery
```

否则：

```text
P5 final architecture failed
```

---

# 七十四、最终必须回答的四个问题

## Question 1

一个未知 Python object 能否仅因为实现了：

```text
__str__
或
to_dict
```

就进入 Market Authority Identity？

答案必须：

```text
NO
```

---

## Question 2

相同：

```text
CN_A_SHARE_CASH@2025.1
Reference
Compiler
Fee
Effective Config
```

从：

```text
BACKTEST
```

迁移到：

```text
future SIM / LIVE
```

Market Composition Fingerprint 是否保持不变？

答案必须：

```text
YES
```

---

## Question 3

Checkpoint 对应：

```text
Reference fingerprint A
```

当前 Runtime 使用：

```text
Reference fingerprint B
```

系统是否会在恢复任何 mutable trading state 之前失败？

答案必须：

```text
YES
```

---

## Question 4

新增：

```text
onlyalpha-market-hk-equity
```

是否无需修改 Core behavioral code？

答案必须：

```text
YES
```

---

# 七十五、最终工程原则

整个 P5.4 必须始终遵守：

```text
Identity is evidence, not convenience.

Serializable does not mean identifiable.

Authority identity must be explicit.

Unknown identity fails closed.

Economic identity excludes transport details.

Effective authorities define identity.

Raw config does not define identity.

Same economics → same fingerprint.

Different economics → different fingerprint.

Runtime type is not market economics.

Product ID is not behavior selector.

Composition identity is resolved once.

Persistence consumes identity.

Recovery verifies identity.

Artifact publishes identity.

No duplicate identity calculation path.

No Market Profile authority resurrection.

No compatibility alias.

No deprecated wrapper.

No implicit fallback.

No speculative identity framework.

No trading economic behavior change.
```

---

# 最终验收定义

P5.4 真正完成时，OnlyAlpha 必须能够明确证明：

```text
“本次 Runtime 具体使用的 Market Product、
Reference、Compiler、Fee 和 Effective Config
是什么？”
```

并能够通过一个唯一：

```text
Market Product Composition Identity
```

回答。

同时系统必须保证：

```text
不同 Market Economic Authority
绝不能被错误认为是同一个运行环境
```

而：

```text
相同 Market Economic Authority
也不能因为文件路径、Runtime 类型、
配置字段顺序等非经济因素被错误认为不同。
```

只要正式 Authority fingerprint 仍然依赖 arbitrary `__str__()` / `to_dict()`，只要 Recovery 在恢复 mutable state 后才检查 market composition，只要旧 Market Profile identity 仍作为第二套 production truth 存在，或者 Core 仍可能通过 Product ID 恢复 concrete market behavior，P5.4 就还没有完成。

P5.4 完成并通过最终 same-SHA 质量门禁后：

```text
P5 — Market Product Composition Authority Neutralization
DONE / CERTIFIED
```

随后才进入 P6：

```text
PAPER
→ SIM

Realtime
+ Virtual Broker
+ Full Trading Kernel
+ Streaming Recovery
```

P6 不再承担任何 Market Product composition 或 identity migration。
