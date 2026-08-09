# Codex Prompt — P2 Fee Reconciliation Semantic Closure

## 任务名称

**P2 — Fee Reconciliation Semantic Closure**

中文：

**P2：外部费用事实对账语义闭环**

目标仓库：

```text
https://github.com/zongxin1993/OnlyAlpha
```

当前规划基线：

```text
3a53ebe464d40c2bf77b4f57bdbd4aefde858049
Feat: Fee Authority Integrity Closure
```

开始实现前必须重新读取最新 `master`。

如果仓库已经前进：

1. 以最新 `master` 为唯一实现基线；
2. 重新审计本 Prompt 涉及的模块；
3. 已经正确实现的内容不得重复重写；
4. 新设计必须与最新正式 Authority 模型一致；
5. Implementation Report 中记录 Prompt 基线与实际开发基线差异。

---

# 1. P2 的根本目标

P1 已经解决：

```text
Market Fee Pack
        +
Broker Fee Contract
        ↓
Order Fee Binding v2
        ↓
Fee Policy Resolution Proof
        ↓
Fee Assessment
        ↓
Fee Application
```

即：

> **OnlyAlpha 为什么认为一笔交易“应该”产生这些费用。**

P2 要解决：

> **当真实 Broker / Clearing / Statement 提供“实际费用事实”时，OnlyAlpha 如何确定这些事实覆盖什么、与本地事实哪里不同、差异意味着什么、是否应该调整资金、是否应该阻止风险增加，以及什么证据才有资格解除阻塞。**

最终必须形成完整链路：

```text
Local Fee Authority Facts
          +
External Broker Evidence
          +
Reconciliation Policy Authority
          ↓
Exact Scope Resolution
          ↓
Component-by-Component Reconciliation
          ↓
Reconciliation Decision
          ↓
Adjustment / Blocker / Match
          ↓
Durable FEE_RECONCILIATION Transaction
          ↓
Account / Strategy Ledger / Adjustment Ledger
          ↓
Risk Gate
          ↓
Checkpoint / Restart / Forward Recovery
```

P2 不是：

```text
“比较两个金额”
```

而是：

> **建立真实外部经济事实进入 OnlyAlpha 后的安全治理模型。**

---

# 2. 第一性原则

所有实现必须从以下原则出发。

---

## 2.1 本地事实与外部事实是两个不同 Authority

`OnlyFeeApplicationRecord` 表示：

```text
OnlyAlpha 根据当时冻结的：

Market Fee Pack
Broker Fee Contract
Order Binding
Fill
Policy Resolution

计算并提交的本地经济事实。
```

`OnlyExternalFeeEvidence` 表示：

```text
Broker / Clearing / Statement
对实际费用的外部报告事实。
```

二者不能互相覆盖。

禁止：

```python
local_fee.amount = broker_report.amount
```

禁止：

```text
Broker Evidence
→ rewrite Fee Application
```

正确方式：

```text
Local Fact
+
External Evidence
↓
Reconciliation Decision
↓
Forward Adjustment
```

历史事实永远不可修改。

---

# 3. Correction 必须使用 Forward Correction

如果历史上：

```text
Local Fee = 5.00

Broker Evidence v1 = 5.30

→ Adjustment +0.30
```

之后 Broker 修订：

```text
Evidence v2 = 5.10
```

禁止修改：

```text
旧 Adjustment +0.30
```

正确方式：

```text
旧 Adjustment +0.30
+
新 Correction -0.20
```

最终：

```text
effective external difference = +0.10
```

原则：

> **已提交 Fact 永不回滚，错误通过新的 Fact 向前修正。**

---

# 4. Reconciliation 是 Decision Authority，不是 Fee Calculation Authority

P2 Planner 不重新：

```text
resolve Market Fee Pack
resolve Broker Contract
calculate commission
calculate tax
```

本地 Fee Application 已经是本地 Authority。

Reconciliation Planner 只处理：

```text
Local Facts
External Evidence
Previous Adjustments
Reconciliation Policy
Existing Reconciliation State
```

然后产生：

```text
Decision
```

Fee Formula 不属于 P2。

---

# 5. Reconciliation Policy 本身必须成为正式 Authority

当前调用方能够传：

```text
materiality_threshold
reason
```

这种做法必须结束。

一项差异最终：

```text
MATCH
ADJUST
BLOCK
```

取决于治理规则。

因此治理规则本身必须：

```text
有 identity
有 version
有 fingerprint
可持久化
可恢复
可审计
```

不能是一个 Runtime 临时参数。

---

# 6. P2 最终 Authority 模型

完成后应有三种明确独立 Authority：

```text
Market Fee Authority
        │
        └─ 应收市场费用


Broker Fee Contract Authority
        │
        └─ 应收券商费用


Reconciliation Governance Authority
        │
        └─ 当“应收”和“实收”不同，
           OnlyAlpha 如何处理
```

它们不能互相拥有。

特别禁止：

```text
Market Fee Pack
→ Reconciliation threshold
```

或：

```text
Broker Fee Contract
→ Trading Block Policy
```

---

# 7. 当前必须解决的核心问题

P2 至少彻底解决以下问题：

```text
A. Reconciliation Policy 没有正式 Authority

B. DETAILED 仍然只是 total-vs-total

C. statement_scope 仍然是弱类型字符串

D. Statement 本地 Fact 查询范围不准确

E. Previous Adjustment 只有总额，没有 Component Attribution

F. Evidence Revision / Supersede 语义不完整

G. Risk Gate 只有单个 Account bool/blocker

H. 无关 MATCHED Evidence 可能解除已有 Blocker

I. Risk Gate 硬编码 SELL + CLOSE

J. Evidence Broker Authority 验证不足

K. Broker 没有正式 Fee Evidence Port

L. Runtime API 仍允许调用者传 Policy 参数

M. External Evidence 进入 Runtime 的正式 Ingress 尚未冻结
```

---

# 8. 本任务明确不做什么

P2 不实现：

```text
正式中国 A 股真实费率

真实印花税/过户费参数

真实券商账户佣金合同

真实 MiniQMT Statement 网络查询

真实券商收费接口对接

Paper Streaming Recovery

Live Runtime

Durable outbound Order Command

Multi-Broker Runtime

Multi-Account Runtime

Futures 产品执行

Crypto 产品执行

复杂 Fee Allocation 算法

FX Currency Conversion

Vectorized Backtest

Research / Web
```

如果实现中遇到这些问题：

```text
记录为 P3+ technical debt
```

不要扩 Scope。

---

# 9. 禁止兼容旧错误模型

OnlyAlpha 仍是新工程。

如果正确设计与旧接口冲突：

> **删除旧接口。**

严禁：

```text
LegacyFeeReconciliationPolicy

CompatStatementScope

statement_scope: str | OnlyFeeStatementScope

OldRiskGateAdapter

LegacySingleBlockerGate

materiality_threshold optional fallback

reason compatibility argument

OldReconcileExternalFeeFacade

EvidenceV1Adapter

implicit migration

try new schema
except use old schema
```

如果旧配置不合法：

```text
Fail Closed
```

如果旧测试测试的是错误语义：

```text
删除或重写测试
```

不能污染生产代码。

---

# 10. Pre-Implementation Audit

写代码前必须完成一次正式审计。

重点检查：

```text
src/onlyalpha/fee/
    evidence.py
    reconciliation.py
    reconciliation_authority.py
    adjustment.py
    risk_gate.py
    transaction_planner.py
    facts.py
    application.py
    ledger相关实现

src/onlyalpha/runtime/
    backtest/runtime.py
    runtime.py
    planning.py
    defaults.py

src/onlyalpha/order/
    service.py

src/onlyalpha/risk/
src/onlyalpha/position/
src/onlyalpha/broker/
src/onlyalpha/plugin/
src/onlyalpha/transaction/

tests/fee/
tests/integration/
tests/recovery/
tests/architecture/
tests/conformance/
```

搜索：

```text
materiality_threshold

statement_scope

OnlyFeeReconciliationInput

OnlyFeeReconciliationDecision

OnlyFeeDifferenceReason

OnlyFeeReconciliationRiskGate

blocked

SELL

CLOSE

prior_adjustments

reported_components

reported_total

reconcile_external_fee

ExternalFeeEvidence

FeeAdjustment

FEE_RECONCILIATION
```

输出：

```text
docs/reports/
p2_fee_reconciliation_pre_implementation_audit.md
```

记录：

```text
Current Evidence Model
Current Decision Model
Current Adjustment Model
Current Risk Gate State
Current Runtime Ingress
Current Projection Chain
Current Persistence Schema
Current Recovery Semantics
Current tests
Current schema versions
Legacy interfaces to delete
```

---

# 11. 新增正式 Reconciliation Policy

新增独立模块：

```text
fee/reconciliation_policy.py
```

正式模型例如：

```python
@dataclass(frozen=True, slots=True)
class OnlyFeeReconciliationPolicy:
    policy_id: str
    policy_version: str

    currency: OnlyCurrency

    materiality_threshold: OnlyMoney

    unknown_difference_action:
        OnlyFeeUnknownDifferenceAction

    incomplete_evidence_action:
        OnlyFeeIncompleteEvidenceAction

    component_mismatch_action:
        OnlyFeeComponentMismatchAction

    fingerprint: str
```

根据实际需求可以微调字段，但不得重新设计成任意 Rule DSL。

---

# 12. 第一版 Policy 必须保持小而明确

第一版只需要真正使用的治理语义：

```text
Materiality Threshold

Unknown Difference Action

Incomplete Evidence Action

Component Mismatch Action
```

避免：

```text
用户脚本
表达式 DSL
动态 Python callback
任意 rule chain
```

P2 的目标是：

```text
Authority Closure
```

不是：

```text
Policy Engine 平台
```

---

# 13. Policy Identity

新增：

```python
@dataclass(frozen=True, slots=True)
class OnlyFeeReconciliationPolicyIdentity:
    policy_id: str
    policy_version: str
    fingerprint: str
```

`OnlyFeeReconciliationDecision` 必须保存 Policy Identity。

---

# 14. Policy Registry

建议新增：

```text
OnlyFeeReconciliationPolicyRegistry
```

键：

```text
(policy_id, policy_version)
```

规则：

```text
unknown
→ FEE_RECONCILIATION_POLICY_NOT_INSTALLED

same id/version different fingerprint
→ FEE_RECONCILIATION_POLICY_FINGERPRINT_CONFLICT

duplicate
→ explicit duplicate error
```

保持与当前 Authority Registry 风格一致。

---

# 15. Policy 属于 Runtime / Account Governance

Config 推荐表达：

```yaml
accounts:
  - account_id: ACCOUNT-001

    fee_reconciliation_policy:
      policy_id: STANDARD_FEE_RECONCILIATION
      policy_version: "1"
```

如果当前 Config Architecture 更适合 Runtime-level Policy，可根据实际代码调整。

但必须满足：

> Policy 属于 Reconciliation Governance，而不是 Market 或 Broker Contract。

---

# 16. 不允许缺失 Policy 默认继续

禁止：

```text
没有配置 Policy
→ materiality = 0
```

或：

```text
没有 Policy
→ 不 Block
```

必须：

```text
FEE_RECONCILIATION_POLICY_NOT_INSTALLED
```

Fail Closed。

---

# 17. Materiality Currency

Policy：

```text
currency
```

必须与 Reconciliation Currency 一致。

必须验证：

```text
difference.currency
==
policy.currency
```

否则：

```text
FEE_RECONCILIATION_POLICY_CURRENCY_MISMATCH
```

P2 不实现 FX Conversion。

不同 Currency：

```text
Fail Closed
```

---

# 18. 删除 Runtime API 的 Policy 参数

删除：

```python
runtime.reconcile_external_fee(
    evidence,
    reason=...,
    materiality_threshold=...
)
```

正式 Runtime Ingress 应变成：

```python
runtime.submit_fee_evidence(evidence)
```

或者等价正式命名。

调用方只提交：

```text
External Fact
```

不能提交：

```text
治理决策参数
```

---

# 19. Reason Authority 重新定义

审计现有：

```text
OnlyFeeDifferenceReason
```

明确区分：

```text
External Reported Reason

vs

System Classified Difference Reason
```

不要允许：

```text
UI / Broker caller
```

直接传：

```text
KNOWN / UNKNOWN
```

来改变 Block Policy。

如果 Broker 提供原始原因：

```text
作为 Evidence Metadata / Normalized Evidence Reason
```

Planner 再根据正式规则产生：

```text
OnlyFeeDifferenceReason
```

---

# 20. Typed Statement Scope

删除：

```python
statement_scope: str | None
```

新增正式：

```python
@dataclass(frozen=True, slots=True)
class OnlyFeeStatementScope:
    broker_id: str
    account_id: OnlyAccountId

    period_start: OnlyTimestamp
    period_end: OnlyTimestamp

    currency: OnlyCurrency

    statement_id: str

    fingerprint: str
```

如果源码证明：

```text
effective trading-day scope
```

比 Timestamp Period 更正确，可以使用：

```text
trading_day_start
trading_day_end
```

但必须选择一个正式模型。

不要同时维护模糊多套 Scope。

---

# 21. Statement Period 语义必须明确

必须在 ADR 冻结：

```text
period_start <= effective_time < period_end
```

即：

```text
[start, end)
```

或者选择 trading-day closed interval。

无论选择什么：

```text
必须唯一
必须有测试
必须所有 Query 使用同一规则
```

---

# 22. External Evidence Scope 建模

建议让 `OnlyExternalFeeEvidence` 明确表达三种 Scope：

```text
TRADE

ORDER

STATEMENT
```

不要通过：

```text
trade_id != None
order_id != None
statement_scope != None
```

让多个字段组合产生非法状态。

---

# 23. 应使非法 Scope 无法构造

推荐：

```python
OnlyTradeFeeEvidenceScope
OnlyOrderFeeEvidenceScope
OnlyStatementFeeEvidenceScope
```

或者：

```python
OnlyExternalFeeEvidenceScope
```

内部使用 tagged union。

必须保证：

```text
TRADE
    exactly one trade id

ORDER
    exactly one order id

STATEMENT
    exactly one typed statement scope
```

不能：

```text
trade + statement 同时存在
```

---

# 24. 删除 Runtime 手工扫描 Ledger

当前类似：

```python
for record in fee_ledger.records:
    if ...
```

的 Scope 选择逻辑应退出 Runtime。

新增正式 Query Port：

```python
class OnlyFeeReconciliationLocalFactQuery(Protocol):
    def query(
        self,
        evidence_scope: OnlyExternalFeeEvidenceScope,
    ) -> tuple[OnlyFeeApplicationRecord, ...]:
        ...
```

或者更明确：

```text
query_trade()
query_order()
query_statement()
```

根据现有风格选择。

---

# 25. Local Fact Query 是唯一 Scope Authority

正式路径：

```text
External Evidence
       ↓
Evidence Scope
       ↓
Local Fact Query Authority
       ↓
Exact Local Fee Applications
```

Runtime 不解释：

```text
哪个 Fee Record 属于 Statement
```

---

# 26. TRADE Scope Query

必须精确：

```text
account_id
broker authority
trade_id
currency
```

匹配。

0 条是否允许取决于 Evidence Mode：

```text
需要显式语义
```

不能自动当：

```text
local fee = 0
```

除非 Policy 明确允许。

---

# 27. ORDER Scope Query

必须匹配：

```text
account
order_id
currency
```

并包含：

```text
该 Order 所有 Fill / ORDER_CUMULATIVE 应用事实
```

排序必须 deterministic。

---

# 28. STATEMENT Scope Query

必须按：

```text
broker
account
currency
period
```

精确筛选。

严禁：

```text
statement_scope exists
→ all account fee records
```

---

# 29. Local Fee Record 应有足够时间 Authority

审计 `OnlyFeeApplicationRecord`。

如果 Statement 查询缺少正式：

```text
effective_at
trading_day
```

等字段，必须补充一个最小必要 Authority。

不要根据：

```text
record insertion time
```

猜 Statement Period。

---

# 30. DETAILED 必须变成真正 Component Reconciliation

当前：

```text
sum(local)
vs
sum(external)
```

的 DETAILED 逻辑必须删除。

新增：

```python
@dataclass(frozen=True, slots=True)
class OnlyFeeComponentReconciliation:
    component_identity: OnlyFeeReconciliationComponentIdentity

    local_amount: OnlyMoney | None
    reported_amount: OnlyMoney | None

    prior_adjustment: OnlyMoney

    effective_local_amount: OnlyMoney

    difference: OnlyMoney

    status: OnlyFeeComponentReconciliationStatus

    fingerprint: str
```

---

# 31. Component Identity

不能只使用：

```text
FeeType
```

因为未来可能存在：

```text
两个不同 Authority
使用相同 Fee Type
```

Component Identity 至少考虑：

```text
fee_type
authority
economic_direction
normalized source/component identity
```

必须与当前 `OnlyFeeApplicationRecord.component_identity` 尽量复用。

不要创建另一套重复 Fee Component Vocabulary。

---

# 32. External Component 必须标准化

Broker 原始字段：

```text
commission
tax
transferFee
handlingCharge
```

不能进入 Core。

Broker Adapter 负责：

```text
Broker DTO
        ↓
Normalizer
        ↓
OnlyExternalFeeComponent
```

例如：

```python
@dataclass(frozen=True, slots=True)
class OnlyExternalFeeComponent:
    component_identity: ...
    amount: OnlyMoney
    fingerprint: str
```

---

# 33. Core 禁止认识 MiniQMT 字段

Architecture Guard 必须禁止：

```text
fee/reconciliation.py
```

import：

```text
MiniQMT
xtquant
具体 Broker DTO
```

Broker-specific Mapping 只能存在：

```text
provider plugin / adapter
```

---

# 34. DETAILED Matching

正式算法：

```text
Union(
    Local Component Identities,
    External Component Identities,
    Prior Adjustment Component Identities
)
          ↓
逐 Component 对账
```

每个 Component：

```text
effective_local
=
local_amount
+
prior_adjustments
```

然后：

```text
difference
=
reported_amount
-
effective_local
```

方向语义必须根据现有 Charge/Refund 模型统一。

禁止不同地方使用相反符号约定。

---

# 35. Component Missing 不是自动 0

必须明确区分：

```text
reported component missing
```

和：

```text
reported amount = 0
```

这两个语义不同。

同样：

```text
local component missing
```

不能无条件等价：

```text
local amount = 0
```

Policy 决定是否：

```text
INCOMPLETE_EVIDENCE
UNKNOWN_COMPONENT
```

---

# 36. External Total 与 Detailed Components 内部一致性

如果 Evidence Mode = DETAILED 且同时包含：

```text
reported_total
+
reported_components
```

必须验证：

```text
sum(component signed amounts)
==
reported_total
```

不一致：

```text
EXTERNAL_FEE_EVIDENCE_INTERNAL_CONFLICT
```

Fail Closed。

不能：

```text
优先相信 total
```

或：

```text
优先相信 components
```

---

# 37. Aggregate Reconciliation Decision

最终 Decision 不只是：

```text
difference total
```

必须包含：

```text
component_reconciliations
aggregate_local
aggregate_reported
aggregate_prior_adjustment
aggregate_difference
status
policy_identity
```

---

# 38. Decision Status 重新审计

审计当前：

```text
MATCHED
RECONCILED_WITH_ADJUSTMENT
TRADING_BLOCKED
DUPLICATE_EVIDENCE
EVIDENCE_CONFLICT
```

根据正式语义决定是否增加：

```text
INCOMPLETE_EVIDENCE
UNSUPPORTED_COMPONENT
REVISION_REQUIRED
```

不要无意义增加状态。

但必须避免：

```text
所有非法情况都塞到 TRADING_BLOCKED
```

---

# 39. Duplicate 与 Decision 应区分

Duplicate Evidence：

```text
是 Evidence Ingress Classification
```

并不意味着产生一个新的经济 Reconciliation Decision。

如果现有架构已经将 Duplicate 作为 Decision Fact，需要审计是否合理。

原则：

> 重复输入不应制造新的经济事实。

---

# 40. Prior Adjustment 必须 Component-aware

删除只返回：

```text
OnlyMoney(total prior adjustments)
```

的模型。

新增正式查询：

```text
component identity
→ cumulative prior adjustment
```

例如：

```text
Commission +0.30
```

只能抵消：

```text
Commission difference
```

不能抵消：

```text
Stamp Duty difference
```

---

# 41. Adjustment Component Attribution

`OnlyFeeAdjustment` 必须至少携带：

```text
component_identity
evidence_id
reconciliation_id
policy_identity/fingerprint
direction
amount
cluster attribution
```

一个 Adjustment 必须回答：

```text
调整的是哪一种 Fee？
为什么调整？
依据哪份 Broker Evidence？
依据哪次 Reconciliation？
```

---

# 42. Aggregate Adjustment 如何表达

如果多个 Component 都需要 Adjustment：

不要把所有东西折叠成：

```text
one anonymous +1.30 fee adjustment
```

优先：

```text
每个 Component 独立 Adjustment Fact
```

或者一个 Adjustment Batch 内：

```text
多个 immutable component adjustments
```

根据 Transaction Projection 结构选择。

核心原则：

> Component Attribution 不得丢失。

---

# 43. Evidence Revision / Supersede

P2 必须正式支持 Broker 修订报告。

已有：

```text
external_reference
report_version
content_fingerprint
```

应冻结 Lineage Semantics。

---

# 44. Evidence Family

建议正式定义：

```text
Evidence Family
=
broker_id
+
account_id
+
external_reference
+
scope identity
```

然后：

```text
report_version
```

表示这个 Family 的版本。

---

# 45. Duplicate

同：

```text
family
version
fingerprint
```

再次提交：

```text
DUPLICATE
```

不得再次：

```text
Adjustment
Cash Mutation
Blocker
```

---

# 46. Conflict

同：

```text
family
version
```

不同：

```text
fingerprint
```

必须：

```text
EVIDENCE_CONFLICT
```

禁止：

```text
last write wins
```

---

# 47. Revision

同 Family：

```text
v1
→
v2
```

v2 是：

```text
Revision
```

必须形成正式 lineage。

建议 Evidence 保存：

```text
supersedes_evidence_id
```

或者由 Authority 根据 Family + Version 确定。

不要只靠字符串版本比较而没有正式 predecessor 关系。

---

# 48. Report Version Ordering

如果 `report_version` 当前是任意 string：

需要决定：

```text
是否具有排序语义
```

如果没有：

```text
不要用字符串大小判断新旧
```

推荐引入显式：

```text
revision_sequence
```

或者强类型 version。

不要：

```python
if "10" > "2":
```

这种隐藏业务语义。

---

# 49. Revision 必须 Forward Correct

例如：

```text
v1
Broker = 10
Local = 8
→ +2 Adjustment

v2
Broker = 9
```

新计算必须考虑：

```text
Local = 8
Prior Adjustment = +2
Effective Local = 10
Reported = 9

→ corrective -1
```

不是：

```text
重新算 +1
```

然后重复累计。

---

# 50. Active Blocker Set

删除：

```text
Account
→ one blocked bool + one evidence id
```

模型。

正式新增：

```python
@dataclass(frozen=True, slots=True)
class OnlyFeeReconciliationBlocker:
    blocker_id: str

    account_id: OnlyAccountId

    evidence_family_identity: ...
    evidence_id: str
    reconciliation_id: str

    reason: OnlyFeeDifferenceReason

    scope: OnlyExternalFeeEvidenceScope

    policy_identity: OnlyFeeReconciliationPolicyIdentity

    created_at: OnlyTimestamp

    fingerprint: str
```

---

# 51. Gate State

升级为：

```python
@dataclass(frozen=True, slots=True)
class OnlyFeeReconciliationRiskGateState:
    account_id: OnlyAccountId

    active_blockers:
        tuple[OnlyFeeReconciliationBlocker, ...]

    version: int
```

不要再持久化独立：

```text
blocked: bool
```

---

# 52. blocked 必须派生

```python
@property
def blocked(self) -> bool:
    return bool(self.active_blockers)
```

避免：

```text
blocked=True
active_blockers=[]
```

非法状态。

---

# 53. Blocker Identity

Blocker 必须由造成阻塞的 Authority 构造。

例如：

```text
evidence family
+
reconciliation
+
policy
```

相同 blocker 重试：

```text
same identity
```

---

# 54. 无关 Evidence 不得解除 Blocker

这是 P2 必须有的核心 Architecture/Integration Test。

场景：

```text
Evidence A
→ large unknown discrepancy
→ Blocker A
```

然后：

```text
Evidence B
→ MATCHED
```

结果必须：

```text
Blocker A remains
Account remains blocked
```

---

# 55. Blocker 解除必须有明确 Relation

只有：

```text
Evidence A 的有效 Revision
```

或与 A 明确属于同一解决 Authority 的 Reconciliation：

```text
证明 A 已解决
```

才能解除：

```text
Blocker A
```

不能：

```text
任何 MATCHED Decision
→ clear account
```

---

# 56. 多 Blocker

必须支持：

```text
A → Blocker A
B → Blocker B
```

解决 A：

```text
active = [B]
```

账户：

```text
still blocked
```

解决 B：

```text
active = []
```

才完全解除。

---

# 57. Blocker State 必须 deterministic ordered

内部使用：

```text
tuple
```

时必须按稳定 Identity 排序。

不能依赖：

```text
dict insertion order
Evidence arrival retry order
```

影响 fingerprint。

---

# 58. Market-neutral Risk Reduction

删除：

```python
if side is SELL and offset is CLOSE:
    allow
```

这种 Fee 模块交易语义。

Fee Reconciliation 只表达：

```text
BLOCK_RISK_INCREASE
```

---

# 59. 新增 Risk Change Classification

优先复用现有 Risk / Position 模型。

正式定义例如：

```python
class OnlyOrderRiskChange(StrEnum):
    RISK_INCREASING = "RISK_INCREASING"
    RISK_REDUCING = "RISK_REDUCING"
    RISK_NEUTRAL = "RISK_NEUTRAL"
    UNKNOWN = "UNKNOWN"
```

命名可以根据项目风格调整。

---

# 60. Risk Classification Authority

必须由：

```text
Risk
+
Position
+
Market Position Model
```

判断。

需要考虑：

```text
side
offset
position side
position mode
current position
reservation
quantity
```

Fee 模块不能自己推断。

---

# 61. 示例

Cash Long：

```text
SELL CLOSE
→ RISK_REDUCING
```

Futures Short：

```text
BUY CLOSE
→ RISK_REDUCING
```

未来：

```text
REDUCE_ONLY
```

同样可以：

```text
RISK_REDUCING
```

---

# 62. Unknown 必须 Fail Closed

当 Gate blocked 且：

```text
risk classification = UNKNOWN
```

默认：

```text
deny
```

不要：

```text
不知道就放行
```

---

# 63. OrderService 调整

当前类似：

```text
fee_gate.require_order_allowed(
    account,
    side,
    offset
)
```

应改成：

```text
risk_change = Risk Authority classify(request)

fee_gate.require_order_allowed(
    account,
    risk_change,
)
```

Gate 不再 import：

```text
OnlyOrderSide
OnlyOffset
```

如果不再需要这些类型。

Architecture Guard 应验证。

---

# 64. Evidence Broker / Account Authority

Runtime Ingress 接收到 Evidence 时必须先验证：

```text
evidence.account_id
==
Runtime / bound Account

evidence.broker_id
==
Account actual Broker Authority
```

并验证：

```text
Broker Fee Contract
```

与该 Broker / Account 匹配。

---

# 65. Broker Mismatch

```text
Broker A Evidence
→ Broker B Account
```

必须：

```text
FEE_EVIDENCE_BROKER_AUTHORITY_CONFLICT
```

Fail Closed。

---

# 66. Account Mismatch

```text
Account A Evidence
→ Account B Runtime
```

必须：

```text
FEE_RECONCILIATION_ACCOUNT_SCOPE_CONFLICT
```

或更加正式统一的错误码。

---

# 67. Evidence Currency

必须验证：

```text
Evidence Scope Currency
Local Fee Fact Currency
Reconciliation Policy Currency
Adjustment Currency
```

全部一致。

P2 不实现 FX。

---

# 68. Broker Fee Evidence Port

新增正式 Broker Port。

建议：

```python
class OnlyBrokerFeeEvidencePort(Protocol):
    ...
```

不要直接给它设计网络协议。

职责：

> Broker Adapter 向 Runtime 提供已经标准化的 `OnlyExternalFeeEvidence`。

---

# 69. Port 可以支持 Pull / Push，但 Domain 不应依赖模式

第一版可以根据现有 Broker Gateway 架构选择：

```text
query
```

或：

```text
inbound delivery
```

但 Core Domain 不应区分：

```text
MiniQMT 是查询来的
Broker X 是推送来的
```

最终都是：

```text
OnlyExternalFeeEvidence
```

---

# 70. 推荐 Runtime Ingress

正式建立：

```python
submit_fee_evidence(
    evidence: OnlyExternalFeeEvidence,
) -> ...
```

或：

```text
receive_fee_evidence
```

如果项目统一 inbound 命名。

关键不是名字。

关键是：

```text
外部只提交 Evidence
```

---

# 71. Runtime Ingress Pipeline

正式：

```text
Evidence
↓
Schema / Identity Validation
↓
Broker + Account Authority Validation
↓
Evidence Classification
↓
Resolve Reconciliation Policy
↓
Resolve Exact Local Facts
↓
Resolve Previous Component Adjustments
↓
Pure Reconciliation Planner
↓
Decision
↓
Durable Transaction Planner
↓
Commit
```

---

# 72. Runtime 不得自己计算 Reconciliation Business Logic

`OnlyBacktestRuntime` 当前已有较多业务装配。

P2 不应继续往：

```text
runtime.py
```

加入：

```text
difference calculation
component matching
revision rules
blocker clearing rules
```

这些全部属于：

```text
fee reconciliation domain/services
```

Runtime 只 orchestrate。

---

# 73. Reconciliation Planner 必须保持 Pure

理想输入：

```python
OnlyFeeReconciliationPlanningInput(
    evidence=...,
    local_facts=...,
    previous_adjustments=...,
    policy=...,
    existing_evidence_state=...,
    existing_blockers=...,
)
```

输出：

```text
OnlyFeeReconciliationDecision
```

Planner 不 import：

```text
Runtime
AccountManager
PersistenceStore
Broker Gateway
Plugin
```

---

# 74. Transaction Planner 同样只做 State Transition Planning

现有：

```text
OnlyFeeReconciliationTransactionPlanner
```

继续复用。

P2 只升级：

```text
Decision
Adjustment
Blocker State
```

的结构。

不要重写：

```text
RuntimeTransactionCoordinator
ProjectionBuilder
Commit Port
Forward Recovery Kernel
```

---

# 75. Durable Projection Chain

现有：

```text
EXTERNAL_FEE_EVIDENCE
FEE_RECONCILIATION
FEE_ADJUSTMENT_LEDGER
ACCOUNT
STRATEGY_LEDGER
UNALLOCATED_EXTERNAL_FEE
RECONCILIATION_RISK_GATE
```

继续作为正式链。

P2 可能升级 Payload Schema，但不增加无必要 Projection。

---

# 76. 是否需要 Blocker 独立 Projection

审计现有：

```text
RECONCILIATION_RISK_GATE
```

如果：

```text
Active Blocker Set
```

可以由一个 Account Gate Projection 原子保存：

```text
继续复用
```

不要仅为了“更纯”增加新 Projection。

如果独立 Blocker Fact 对 Recovery/Query 显著更合理，再新增。

必须先说明必要性。

---

# 77. Evidence 与 Decision 应先于经济 Adjustment Projection

Projection 顺序至少保证：

```text
Evidence
↓
Decision
↓
Adjustment Fact
↓
Account / Strategy / Unallocated
↓
Risk Gate
```

这样审计关系清楚。

如果现有 Durable Operation 已定义顺序：

```text
保持确定性
```

---

# 78. Account Adjustment 语义

Supplemental Charge：

```text
cash decreases
fees increases
```

Refund：

```text
cash increases
fees decreases
```

符号约定必须统一。

禁止：

```text
Planner 一套 signed convention
Projection 一套 opposite convention
```

---

# 79. Strategy Attribution

如果 Evidence 可以严格关联：

```text
Trade
Order
Cluster
```

并能唯一证明 Strategy Attribution：

```text
Adjustment → Strategy Ledger
```

如果不能证明：

```text
Adjustment → Account
+
Unallocated External Fee
```

不要猜 Strategy。

---

# 80. Statement Allocation

P2 不实现复杂 Statement-to-Strategy Allocation。

对于无法唯一归因：

```text
UNALLOCATED_EXTERNAL_FEE
```

继续是正确模型。

禁止：

```text
按 Cluster 数量平均分摊
```

等隐式行为。

---

# 81. Cash Insufficient Case

现有 Supplemental Charge 可能：

```text
Account Cash < required Adjustment
```

P2 必须明确语义。

第一版可以继续：

```text
Fail Closed
```

但必须保证：

> Evidence 已进入 Durable Authority 后，不因为 Account Cash Mutation 失败而逻辑上丢失外部事实。

审计 Transaction Atomicity。

如果整个 FEE_RECONCILIATION Transaction 无法 Commit：

```text
Evidence 是否需要独立 Ingress Journal
```

必须分析并记录。

---

# 82. 不要随意引入 Pending Settlement

除非审计证明必须。

P2 不要顺手增加：

```text
Pending Fee Debt
Negative Cash Facility
Margin Loan
```

如果现金不足无法安全处理：

```text
明确 Fail Closed
+
记录 technical debt
```

---

# 83. Evidence Revision 与 Blocker 的关系

例如：

```text
Evidence Family A v1
→ blocker A
```

然后：

```text
A v2
```

Planner 必须判断：

```text
v2 是否 supersede v1
```

如果 v2 已解决原差异：

```text
remove blocker A
```

---

# 84. Revision 未解决差异

A v2 仍然：

```text
unknown material discrepancy
```

则：

```text
更新 / replacement blocker
```

但不能：

```text
先 remove blocker
再产生无 blocker window
```

Transaction Planner 应原子产生：

```text
old blocker → new blocker state
```

---

# 85. Evidence B 永远不能解决 Evidence A

除非 Domain 明确定义：

```text
B supersedes A
```

这种 Lineage Relation。

匹配：

```text
same account
```

远远不够。

---

# 86. Blocker Scope

Blocker 第一版可以仍然作用于：

```text
Account
```

但 Blocker 自身必须保存：

```text
Origin Evidence Scope
```

这样未来可以扩：

```text
Instrument-level
Market-level
Broker-level
```

而不丢历史信息。

不要现在实现多层 Gate。

---

# 87. Risk Gate Policy

第一版：

```text
No Active Blockers
    ALLOW

Has Active Blockers:
    RISK_REDUCING
        ALLOW

    RISK_INCREASING
        DENY

    UNKNOWN
        DENY
```

`RISK_NEUTRAL` 应明确。

我倾向第一版：

```text
RISK_NEUTRAL
→ DENY
```

除非 Risk Authority 能证明它不会增加资金/市场 Exposure。

Fail Closed 优先。

---

# 88. External Evidence Identity

重新审计 Identity Payload。

必须至少包含：

```text
broker
account
scope
external reference
report version/revision
component payload
total payload
effective time
content fingerprint
```

但不要重复：

```text
fingerprint of fingerprint
```

设计保持简洁。

---

# 89. Evidence Fingerprint

Fingerprint 必须由：

```text
canonical sorted normalized domain payload
```

计算。

不能依赖：

```text
dict insertion order
Broker raw JSON order
component arrival order
```

---

# 90. Component Sorting

所有 Component：

```text
按 stable component identity 排序
```

再进入：

```text
Evidence Fingerprint
Decision Fingerprint
Artifact
```

---

# 91. Policy Fingerprint

Policy Fingerprint 必须包含：

```text
threshold amount
threshold currency
all handling actions
versioned authority payload
```

任何治理行为变化：

```text
fingerprint changes
```

---

# 92. Decision Identity

建议：

```text
reconciliation_id
```

由以下 Authority 决定：

```text
Evidence identity
Local fact authority fingerprint
Prior adjustment authority fingerprint
Policy identity
Component reconciliation results
```

不能只包含：

```text
final total difference
```

---

# 93. Local Fact Authority Fingerprint

Local Fact Query 结果必须形成确定性 fingerprint。

例如：

```text
sorted Fee Application identities
+
amounts
+
component identities
```

这样可以证明：

```text
Decision 使用的是哪一批本地事实
```

---

# 94. Prior Adjustment Authority Fingerprint

同理：

```text
sorted prior adjustment identities
```

进入 Decision Authority。

否则：

```text
相同 Evidence
但历史 adjustment 不同
```

可能错误得到同 Decision identity。

---

# 95. Decision Schema Upgrade

如果 `OnlyFeeReconciliationDecision` 变化：

```text
升级 schema_version
```

新增：

```text
policy identity
local facts fingerprint
prior adjustment fingerprint
component decisions
scope identity
revision relation
```

不要兼容旧 Schema。

---

# 96. Evidence Schema Upgrade

Typed Scope 与 Revision Lineage 基本会导致 Evidence Schema Breaking Change。

旧 Evidence：

```text
明确拒绝
```

不要：

```text
statement_scope str 自动包装
```

---

# 97. Adjustment Schema Upgrade

如果新增：

```text
component identity
policy proof
```

则升级 Adjustment Schema。

旧 Adjustment：

```text
Fail Closed
```

---

# 98. Risk Gate Checkpoint Schema

Active Blocker Set 会改变持久化格式。

升级：

```text
fee_reconciliation_risk_gate.authority
```

Checkpoint Schema。

不迁移旧单 blocker state。

---

# 99. Transaction Schema 是否升级

不要机械升级。

检查：

```text
OnlyPreparedRuntimeTransaction
OnlyCommittedRuntimeTransaction
```

如果 Transaction generic envelope 没变化：

```text
不要升级
```

只升级 Projection Payload。

原则：

> Schema Version 只代表真实 Contract 变化。

---

# 100. Runtime API 删除清单

P2 完成后应不存在：

```text
runtime.reconcile_external_fee(
    evidence,
    reason,
    materiality_threshold,
)
```

这种 Caller-owned Policy API。

替换成：

```text
submit_fee_evidence(evidence)
```

或正式等价入口。

---

# 101. Architecture Guard：禁止 Materiality 参数回流

生产代码中：

```text
materiality_threshold
```

只应该属于：

```text
OnlyFeeReconciliationPolicy
```

不能重新出现在：

```text
Runtime method parameters
Broker callback
UI command
```

---

# 102. Broker Evidence Port

新增 Broker/Core Port 时保持：

```text
Broker-specific implementation
        ↓
Normalized Evidence
        ↓
Core
```

Port 不允许返回：

```text
dict
Any
Broker DTO
```

应返回正式 Domain Model。

---

# 103. MiniQMT P2 边界

P2 可以为 MiniQMT 插件增加：

```text
Protocol implementation skeleton
Fake evidence normalization test
```

但禁止：

```text
真实网络账户登录
真实 statement scraping
真实 fee report API
```

这些后续再做。

---

# 104. Broker Fee Contract Provisioning

P2 不重做 P1 Broker Contract Authority。

但是审计并记录：

```text
Plugin Entry Point
```

目前更适合提供：

```text
simulation/static contract definitions
```

真实个性化 Account Contract 的 Provisioning 后续需要：

```text
Contract Provider / Repository
```

P2 不要扩进去。

---

# 105. Reconciliation Result / Artifact

Backtest Result / Artifact 如果已有 Reconciliation 输出：

升级为至少包含：

```text
Evidence identity

Evidence scope

Evidence lineage

Policy identity

Local fact fingerprint

Prior adjustment fingerprint

Component reconciliation rows

Aggregate decision

Adjustment identities

Active blocker changes
```

---

# 106. Artifact 不应复制巨大内部对象

Artifact 目标：

```text
Auditable
```

不是：

```text
serialize entire Runtime
```

输出 Authority Identity/Fingerprint + 关键字段即可。

---

# 107. Recovery

P2 必须覆盖 Durable Failure Matrix。

至少：

```text
Fail after:
    EXTERNAL_FEE_EVIDENCE

    FEE_RECONCILIATION

    FEE_ADJUSTMENT_LEDGER

    ACCOUNT

    STRATEGY_LEDGER

    UNALLOCATED_EXTERNAL_FEE

    RECONCILIATION_RISK_GATE
```

---

# 108. Recovery 结果要求

每个失败点：

```text
A
→ crash
→ B restart
→ crash/continue
→ C restart
```

最终：

```text
same canonical projection
same evidence
same decision
same component adjustments
same account cash
same strategy ledger
same active blockers
```

---

# 109. Exactly-once Economic Effect

重复 Recovery 不得：

```text
重复补扣
重复退款
重复 blocker
重复 evidence
重复 adjustment
```

虽然 transport 可以 at-least-once：

```text
economic projection 必须 idempotent
```

---

# 110. Revision Recovery

必须测试：

```text
v1
→ +5 adjustment
→ blocker

checkpoint

v2 arrives
→ corrective -3
→ blocker resolved

crash during v2 projection

restart
```

最终：

```text
exactly one +5
exactly one -3
no blocker
```

---

# 111. Multi-Blocker Recovery

测试：

```text
A blocks
B blocks
checkpoint
A revision resolves A
crash
restart
```

结果：

```text
B remains
```

---

# 112. Statement Scope Recovery

测试：

```text
Jan local fees
Feb local fees

Jan evidence
checkpoint/restart
```

仍然只选择：

```text
Jan
```

不能因为 restore 顺序变化选择所有历史记录。

---

# 113. Determinism

同样：

```text
Evidence
Local Facts
Policy
Prior Adjustments
```

重复运行必须：

```text
same evidence fingerprint
same local fact fingerprint
same decision fingerprint
same adjustment identity
same blocker identity
```

---

# 114. Registration Ordering

如果：

```text
Policy Registry
Component mapping registry
```

存在多个注册项：

不同注册顺序不得改变：

```text
Resolution
Decision
```

---

# 115. Component Order Determinism

External Evidence Components：

```text
[A, B, C]
```

与：

```text
[C, A, B]
```

如果业务语义相同：

```text
Evidence fingerprint 必须相同
```

---

# 116. Tests — Unit

至少增加：

```text
tests/fee/test_reconciliation_policy.py

tests/fee/test_statement_scope.py

tests/fee/test_component_reconciliation.py

tests/fee/test_external_fee_evidence_revision.py

tests/fee/test_reconciliation_blockers.py

tests/risk/test_reconciliation_risk_change.py
```

名称可按项目结构调整。

---

# 117. Policy Unit Tests

覆盖：

```text
valid policy

empty id/version

currency mismatch

negative threshold

fingerprint conflict

duplicate registry version

unknown policy
```

---

# 118. Statement Tests

覆盖边界：

```text
period start included

period end excluded

wrong account excluded

wrong broker excluded

wrong currency excluded

before period excluded

after period excluded
```

---

# 119. Evidence Scope Illegal State Tests

必须无法构造：

```text
TRADE + ORDER

ORDER + STATEMENT

empty TRADE id

empty Statement id

period_end <= period_start
```

---

# 120. DETAILED Tests

至少：

```text
same totals
same components
→ MATCH

same total
different components
→ NOT MATCH

one missing external component
→ incomplete

one unexpected external component
→ explicit mismatch

multiple components differences
→ multiple component decisions
```

---

# 121. Prior Adjustment Tests

```text
Commission local 5

External v1 6
→ +1 Commission

External v2 5.5
→ -0.5 Commission correction
```

同时：

```text
Stamp Duty adjustment
```

不能抵消 Commission。

---

# 122. Evidence Lineage Tests

覆盖：

```text
same version same fingerprint
→ duplicate

same version different fingerprint
→ conflict

new version same family
→ revision

different external_reference
→ independent evidence family
```

---

# 123. Blocker Tests

覆盖：

```text
A blocks

B matches
→ A remains

A revision matches
→ A removed

A+B block
A resolves
→ B remains

A+B resolve
→ no block
```

---

# 124. Market-neutral Risk Tests

至少：

```text
Cash Long SELL CLOSE
→ reducing

Futures Short BUY CLOSE
→ reducing

OPEN
→ increasing

UNKNOWN
→ deny while blocked
```

不要为了测试 Futures Execution Capability 而开放正式 Futures Runtime。

只测试 Risk Classification Domain。

---

# 125. Broker Authority Tests

```text
Evidence broker correct
→ PASS

wrong broker
→ FAIL

wrong account
→ FAIL

wrong currency
→ FAIL
```

---

# 126. Integration Tests

至少：

```text
Local fee
+
trade evidence
→ match

Local fee
+
order evidence
→ adjustment

Statement
+
multiple local fee records
→ exact period match
```

---

# 127. Multi-Cluster Attribution

同一 Account 多 Cluster：

如果 Order/Trade Scope 可以唯一定位 Cluster：

```text
Adjustment → corresponding Strategy Ledger
```

如果 Statement 不能：

```text
Account adjusted
+
Unallocated External Fee
```

---

# 128. Architecture Tests

必须保证：

```text
Reconciliation Planner
does not import Runtime

Reconciliation Planner
does not import Broker Plugin

Risk Gate
does not import Order Side/Offset
unless strictly required by a generic risk classification type

Runtime API
does not accept materiality_threshold

statement_scope: str
does not exist

single blocker model
does not exist

Broker plugin
cannot import AccountManager mutation surface
```

---

# 129. Legacy Search Guards

扫描：

```text
src/onlyalpha
```

禁止重新出现：

```text
statement_scope: str

materiality_threshold parameter in Runtime API

if side is SELL and offset is CLOSE

single evidence_id on account risk gate state

clear all blockers on MATCHED

sum-only DETAILED reconciliation
```

---

# 130. Error Codes

建议正式收敛：

```text
FEE_RECONCILIATION_POLICY_NOT_INSTALLED

FEE_RECONCILIATION_POLICY_DUPLICATE_VERSION

FEE_RECONCILIATION_POLICY_FINGERPRINT_CONFLICT

FEE_RECONCILIATION_POLICY_CURRENCY_MISMATCH


FEE_EVIDENCE_SCOPE_INVALID

FEE_STATEMENT_SCOPE_INVALID

FEE_EVIDENCE_BROKER_AUTHORITY_CONFLICT

FEE_EVIDENCE_ACCOUNT_AUTHORITY_CONFLICT

FEE_EVIDENCE_CURRENCY_CONFLICT

EXTERNAL_FEE_EVIDENCE_INTERNAL_CONFLICT

EXTERNAL_FEE_EVIDENCE_IDENTITY_CONFLICT


FEE_COMPONENT_MAPPING_AMBIGUOUS

FEE_COMPONENT_INCOMPLETE

FEE_RECONCILIATION_LOCAL_FACT_SCOPE_CONFLICT


FEE_RECONCILIATION_BLOCKER_CONFLICT

FEE_RECONCILIATION_BLOCKER_RESOLUTION_CONFLICT

FEE_RECONCILIATION_RISK_CLASSIFICATION_UNKNOWN
```

结合现有 Exception System 调整。

不要全部裸：

```python
ValueError("something wrong")
```

但不要为了 P2 全面重构整个项目异常体系。

---

# 131. 建议模块结构

P2 后建议：

```text
fee/
├── application.py
├── evidence.py
├── evidence_scope.py
├── statement.py
├── reconciliation_policy.py
├── reconciliation.py
├── reconciliation_query.py
├── reconciliation_authority.py
├── adjustment.py
├── blocker.py
├── risk_gate.py
├── transaction_planner.py
└── facts.py
```

不强制完全按文件名照搬。

核心是职责清晰。

---

# 132. 模块边界

```text
evidence.py
    外部标准事实

statement.py
    Statement typed scope

reconciliation_policy.py
    治理 Authority

reconciliation.py
    Pure decision logic

reconciliation_query.py
    Local facts resolution

adjustment.py
    Forward correction

blocker.py
    Blocker domain

risk_gate.py
    Account risk policy application

transaction_planner.py
    Durable state transition planning
```

不要把所有东西继续塞进：

```text
reconciliation.py
```

---

# 133. 文件整洁要求

完成后：

```text
删除 Dead Code

删除 Old APIs

删除 deprecated aliases

删除 Compat Wrappers

删除 unused imports

删除重复 enums

删除旧 schemas

删除旧 fixtures

重写 docs
```

不要：

```text
注释掉旧实现
```

Git 已经保存历史。

---

# 134. P2 不应该修改的稳定模块

除非确有必要，不重构：

```text
Fee Market Pack
Broker Fee Contract
Order Fee Binding v2
Fee Policy Resolution Proof
Fee Basis Provider
Fee Engine Formula
Order Fee Accrual Authority
Runtime Transaction Coordinator
Projection Framework
Settlement
Market Rule
```

P1 已经稳定的 Authority 输入层不要重新打开。

---

# 135. Schema Migration 原则

P2 是 breaking change。

如果旧 schema 不再合法：

```text
旧数据 Fail Closed
```

当前阶段不要写：

```text
migration v1 → v2
```

除非仓库已有明确必须维护的正式持久化兼容承诺。

目前默认：

```text
no backward migration
```

---

# 136. Documentation

新增 ADR：

```text
docs/adr/
0061-fee-reconciliation-semantic-closure.md
```

具体编号以当前最新 ADR 序列为准。

ADR 必须解释：

```text
为什么 External Evidence 不覆盖 Local Fact

为什么 Reconciliation Policy 是第三种 Authority

为什么 Statement Scope 必须 typed

为什么 DETAILED 必须逐 Component

为什么历史 Adjustment 不修改

为什么 Revision 使用 Forward Correction

为什么 Gate 是 Active Blocker Set

为什么 Blocker 只能被自己的 Evidence Lineage 解决

为什么 Fee Gate 不解释 BUY/SELL

为什么 Broker Adapter 必须先 normalize Evidence
```

---

# 137. Implementation Report

新增：

```text
docs/reports/
p2_fee_reconciliation_semantic_closure.md
```

至少包含：

```text
Baseline

Before Architecture

Root Problems

Deleted Interfaces

New Policy Authority

Typed Scope Model

Component Reconciliation Model

Revision / Supersede Model

Blocker Model

Risk Change Boundary

Broker Evidence Port

Schema Changes

Recovery Semantics

Test Matrix

Exact Gate Results

Remaining Technical Debt
```

---

# 138. Roadmap

更新：

```text
P1
DONE

P2
DONE
```

但明确：

```text
P3 CN A-Share Production Fee Product
NOT DONE
```

不要宣称：

```text
真实券商费用接入完成
```

---

# 139. README / docs 准确性

如果 README 提到：

```text
external reconciliation
```

必须准确区分：

```text
Domain/Durable semantic closure
```

和：

```text
real Broker connectivity
```

P2 完成不等于：

```text
MiniQMT fee statement connected
```

---

# 140. 推荐 Commit 顺序

## Commit 1 — Pre-Implementation Audit + ADR

只做：

```text
audit
domain decisions
boundary freeze
```

不写兼容代码。

---

## Commit 2 — Reconciliation Policy Authority

新增：

```text
OnlyFeeReconciliationPolicy
Identity
Registry
Config selection
Runtime composition
```

删除：

```text
caller materiality threshold
caller decision reason
```

---

## Commit 3 — Typed Evidence Scope / Statement Scope

新增：

```text
Trade Scope
Order Scope
Statement Scope
```

删除：

```text
statement_scope str
ambiguous nullable field combinations
```

---

## Commit 4 — Local Fact Query Authority

把 Local Fee selection 从 Runtime 移出。

实现：

```text
TRADE exact query
ORDER exact query
STATEMENT exact query
```

---

## Commit 5 — Component Reconciliation

实现：

```text
external component normalization model
component identity
component-by-component planner
aggregate invariants
```

删除：

```text
sum-only detailed mode
```

---

## Commit 6 — Component Adjustment / Forward Correction

升级：

```text
Prior Adjustments
Fee Adjustment
Revision correction
```

保留 immutable history。

---

## Commit 7 — Evidence Revision / Lineage

实现：

```text
family
duplicate
conflict
revision
supersede
```

---

## Commit 8 — Active Blocker Authority

将：

```text
single Account blocker
```

升级：

```text
active blocker set
```

修复无关 Evidence 解锁问题。

---

## Commit 9 — Market-neutral Risk Gate

删除：

```text
SELL+CLOSE
```

接入：

```text
Risk Change Classification
```

---

## Commit 10 — Broker Evidence Port + Runtime Ingress

新增：

```text
OnlyBrokerFeeEvidencePort

submit_fee_evidence()
```

先用 Fake / Conformance Adapter。

---

## Commit 11 — Durable Recovery / Schema Closure

完成：

```text
projection schema
checkpoint
failure matrix
revision recovery
multi-blocker recovery
```

---

## Commit 12 — Architecture Guards + Docs + Final Report

删除所有 legacy。

更新：

```text
ADR
roadmap
fee docs
runtime docs
broker docs
implementation report
```

---

# 141. 每个 Commit 必须独立有意义

禁止：

```text
一个 10,000 行 commit
```

每个提交：

```text
逻辑边界清晰
tests correspond
production + test change coherent
```

不要人为切成不能运行的中间提交。

---

# 142. Test Gate

使用当前 P0 正式 Lane。

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

# 143. 功能 Lane

至少：

```bash
uv run python scripts/test_suite.py fast

uv run python scripts/test_suite.py integration

uv run python scripts/test_suite.py core-full

uv run python scripts/test_suite.py recovery

uv run python scripts/test_suite.py ashare

uv run python scripts/test_suite.py miniqmt-contract

uv run python scripts/test_suite.py exhaustive
```

---

# 144. Build

```bash
uv build --all-packages
```

如果最新仓库命令发生变化：

```text
使用最新正式命令
```

不要恢复旧命令。

---

# 145. 不允许通过测试的方法

禁止：

```text
skip

xfail

删 assertion

删除 Recovery cases

降低 duplicate/conflict 检查

missing policy 默认

unknown evidence 默认 0

unknown risk classification 默认 allow

statement scope fallback account-wide

component mismatch fallback total match
```

---

# 146. 性能

P2 不以运行性能优化为主要目标。

但是不能写出明显：

```text
O(all historical fees)
```

的 Statement Query，如果已有索引/查询边界可以更合理实现。

第一优先级：

```text
Correctness
Determinism
Authority
```

---

# 147. Definition of Done — Policy

* [ ] `OnlyFeeReconciliationPolicy` 是版本化 Authority。
* [ ] Policy 有 Identity/Fingerprint。
* [ ] Materiality 只属于 Policy。
* [ ] Runtime Caller 不再传 materiality threshold。
* [ ] Runtime Caller 不再直接决定 reconciliation reason。
* [ ] Currency mismatch Fail Closed。
* [ ] Missing Policy Fail Closed。

---

# 148. Definition of Done — Scope

* [ ] `statement_scope: str` 已删除。
* [ ] Statement Scope 是强类型模型。
* [ ] TRADE / ORDER / STATEMENT Scope 互斥。
* [ ] 非法 Scope 无法构造。
* [ ] Statement Period 语义唯一。
* [ ] Local Fact Query 不再由 Runtime 手写扫描。
* [ ] Statement 只选择真实范围内 Local Facts。

---

# 149. Definition of Done — Components

* [ ] DETAILED 已真正逐 Component 对账。
* [ ] Total 相同但 Component 不同不会 MATCH。
* [ ] External Components 使用标准 OnlyAlpha Domain。
* [ ] Core 不认识 Broker-specific 字段。
* [ ] External total 和 Component total 冲突 Fail Closed。
* [ ] Prior Adjustments 是 Component-aware。
* [ ] Adjustment 保存 Component Attribution。

---

# 150. Definition of Done — Revision

* [ ] Duplicate / Conflict / Revision 正式区分。
* [ ] Evidence Family 有稳定 Identity。
* [ ] Revision Lineage 可证明。
* [ ] History Evidence 不覆盖。
* [ ] History Adjustment 不修改。
* [ ] Revision 使用 Forward Correction。
* [ ] Duplicate 不产生重复经济作用。

---

# 151. Definition of Done — Blocker

* [ ] Risk Gate 不再只有一个 bool/单 blocker。
* [ ] Active Blocker Set 是正式 Authority。
* [ ] `blocked` 是派生属性。
* [ ] Evidence B MATCHED 不能解除 A。
* [ ] 一个 Evidence 只能解决自己的 lineage blocker。
* [ ] 多 Blocker 可并存。
* [ ] 解决其中一个不会清除其他 Blocker。
* [ ] Blocker Identity/Fingerprint deterministic。

---

# 152. Definition of Done — Risk

* [ ] Fee Gate 不再硬编码 `SELL+CLOSE`。
* [ ] Risk Change Classification 是正式边界。
* [ ] Cash long close 可识别 Risk Reducing。
* [ ] Futures short close 可识别 Risk Reducing。
* [ ] Risk Increasing 在 blocked 时拒绝。
* [ ] Unknown Fail Closed。
* [ ] Fee Module 不解释市场方向语义。

---

# 153. Definition of Done — Evidence Authority

* [ ] Evidence Broker ID 严格验证。
* [ ] Evidence Account ID 严格验证。
* [ ] Evidence Currency 严格验证。
* [ ] Evidence 与当前 Broker Contract Authority 可证明一致。
* [ ] Wrong Broker Evidence Fail Closed。
* [ ] Wrong Account Evidence Fail Closed。

---

# 154. Definition of Done — Broker Port

* [ ] Broker Fee Evidence Port 已定义。
* [ ] Port 返回标准化 Domain Evidence。
* [ ] Core 不依赖 Broker DTO。
* [ ] Runtime 有正式 Evidence Ingress。
* [ ] P2 没有引入真实 MiniQMT 网络依赖。

---

# 155. Definition of Done — Durable / Recovery

* [ ] Existing `FEE_RECONCILIATION` transaction 继续复用。
* [ ] Projection 顺序 deterministic。
* [ ] Evidence Projection Recovery exactly-once economic effect。
* [ ] Adjustment Recovery exactly-once。
* [ ] Account Recovery exactly-once。
* [ ] Strategy Ledger Recovery exactly-once。
* [ ] Blocker Recovery exactly-once。
* [ ] Revision Recovery 正确。
* [ ] Multi-blocker Recovery 正确。
* [ ] A→B→C canonical state 等价。

---

# 156. Definition of Done — Clean Architecture

* [ ] 没有 legacy reconciliation API。
* [ ] 没有 compatibility adapters。
* [ ] 没有 deprecated aliases。
* [ ] 没有 `statement_scope: str`。
* [ ] 没有 Runtime-level materiality threshold。
* [ ] 没有 sum-only DETAILED。
* [ ] 没有 single blocker clear-on-match。
* [ ] 没有 Fee Gate BUY/SELL 业务推断。
* [ ] Planner 保持 Pure。
* [ ] Broker Adapter 不修改 Account。
* [ ] Runtime 只负责 orchestration。
* [ ] 模块职责清楚。
* [ ] Architecture Guards 已建立。

---

# 157. Definition of Done — Quality Gates

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
* [ ] Relevant Exhaustive PASS。
* [ ] Build PASS。

---

# 158. 最终报告必须给出精确测试结果

不要写：

```text
all tests passed
```

必须写类似：

```text
core-full:
xxxx passed
x skipped
xx.xx s

recovery:
xxx passed
xx.xx s
```

记录实际结果。

---

# 159. P2 完成后明确仍然没有实现什么

Implementation Report 必须明确：

```text
NOT IMPLEMENTED IN P2
```

至少包括：

```text
Production CN A-share Market Fee Pack

Real Broker Commission Contract

Real MiniQMT fee/statement ingestion

Paper Streaming Recovery

Live Runtime

Durable Outbound Order Commands

Production Futures Execution

Production Crypto Execution

Multi-account Runtime

Multi-broker Runtime

Advanced fee allocation

FX reconciliation

Vectorized Backtest
```

---

# 160. 下一阶段接口

P2 完成后，架构应自然允许 P3：

```text
P3 — CN A-Share Production Fee Product
```

P3 只需要：

```text
真实 Market Fee Pack
+
正式 Broker Contract Provisioning
+
真实 Reference Vectors
```

而不需要再次改变：

```text
Evidence
Reconciliation
Adjustment
Blocker
```

的根结构。

如果 P3 仍然必须大规模修改 P2 根架构：

> P2 没有真正闭环。

---

# 161. 最终工程模型

P2 完成以后，OnlyAlpha 的 Fee Domain 应形成：

```text
              EXPECTED ECONOMICS

Market Fee Pack
       +
Broker Fee Contract
       ↓
Order Binding
       ↓
Assessment
       ↓
Fee Application
       │
       │
       │
       ▼
┌─────────────────────────────┐
│ Local Immutable Fee Facts   │
└─────────────────────────────┘
               │
               │
               │
               ▼
        Reconciliation
               ▲
               │
               │
┌─────────────────────────────┐
│ External Broker Evidence    │
└─────────────────────────────┘
               ▲
               │
        Broker Evidence Port


        + Reconciliation Policy
               │
               ▼
     Component-by-Component
             Decision
               │
      ┌────────┼────────┐
      │        │        │
    Match   Adjustment Blocker
               │        │
               ▼        ▼
         Forward Facts Risk Gate
```

---

# 162. 最终审计能力

任何一笔 External Fee Adjustment 最终必须回答：

```text
Broker 报告了什么？

是哪一个 Broker？

哪个 Account？

覆盖 Trade、Order 还是 Statement？

Statement 覆盖哪个时间范围？

具体有哪些 Fee Components？

本地对应哪些 Fee Application Facts？

本地各 Component 是多少？

以前已经调整过多少？

Broker 各 Component 报了多少？

剩余差异是多少？

依据哪个 Reconciliation Policy？

为什么这个差异被认为 material？

为什么产生 Adjustment？

为什么产生 Blocker？

这个 Blocker 属于哪份 Evidence？

谁有资格解除这个 Blocker？

这个 Adjustment 怎样进入 Account？

是否进入 Strategy Ledger？

如果没有进入 Strategy Ledger，为什么是 Unallocated？

Broker 修订后如何产生 Forward Correction？

Restart 后为什么没有重复扣款？

整个决定的 Fingerprint 如何证明？
```

只要其中任何一个重要问题无法由正式 Domain Facts 回答：

> P2 尚未完成。

---

# 163. 最终原则

当：

```text
旧 API
```

与：

```text
正确 Evidence Authority
```

冲突：

> 删除旧 API。

当：

```text
历史测试
```

与：

```text
正确 Reconciliation Semantics
```

冲突：

> 重写历史测试。

当：

```text
方便
```

与：

```text
Fail Closed
```

冲突：

> 选择 Fail Closed。

当：

```text
覆盖旧事实
```

与：

```text
Forward Correction
```

冲突：

> 选择 Forward Correction。

当：

```text
Account 一个 bool
```

与：

```text
可归因 Active Blocker Set
```

冲突：

> 选择 Active Blocker Set。

当：

```text
总金额相同
```

与：

```text
Component Authority 不一致
```

冲突：

> 认定不一致。

当：

```text
Runtime 快速实现
```

与：

```text
Domain Boundary 清晰
```

冲突：

> 把业务逻辑移出 Runtime。

当：

```text
Broker-specific convenience
```

与：

```text
Core Market/Broker-neutral
```

冲突：

> 在 Adapter 层 Normalize。

---

# 164. P2 最终定义

P2 不是：

> “新增 Broker Fee 对账功能。”

P2 的真正目标是：

> **建立一套从外部 Broker Fee Evidence 到本地不可变 Fee Facts 的正式经济事实协调机制，使任何差异都经过版本化治理 Policy、精确 Scope、逐 Component 比较、Forward Correction 和可归因 Blocker，再通过现有 Durable Transaction 安全修改 Runtime 经济状态。**

最终必须满足：

```text
External facts are immutable.

Local facts are immutable.

Policies are versioned authorities.

Scopes are explicit.

Components are reconciled independently.

Corrections move forward.

Blockers are attributable.

Unrelated evidence cannot unlock them.

Risk reduction is market-neutral.

Broker-specific data ends at adapters.

Economic effects are durable.

Restart changes nothing.

Unknown states fail closed.
```

只有这些原则全部进入正式代码、测试、持久化和恢复边界，P2 才算真正完成。
