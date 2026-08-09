# Codex Prompt — P4.1 Durable Execution Capability Semantic Authority Closure

## 任务名称

**P4.1 — Durable Execution Capability Semantic Authority Closure**

中文：

**P4.1：Durable Execution 能力语义 Authority 收口**

目标仓库：

```text
https://github.com/zongxin1993/OnlyAlpha
```

规划基线：

```text
7f11092bb5220fdbd35d2631682c03c50255cef0
Feat: Runtime Composition & Execution Hygiene Closure
```

开始实施前必须重新读取最新 `master`。

如果最新 `master` 已经前进：

1. 以最新 `master` 为唯一实现基线；
2. 重新审计本 Prompt 涉及的源码；
3. 已经正确实现的内容不得重复实现；
4. 不得为了套用 Prompt 而恢复已经删除的接口；
5. 如果最新实现存在比本 Prompt 建议更简洁、更正确的结构，应保留更优实现；
6. Implementation Report 必须记录：

   * Prompt baseline；
   * actual implementation baseline；
   * baseline differences；
   * 已提前解决的问题；
   * 因最新代码结构产生的设计调整。

---

# 1. P4.1 的根本目标

当前 OnlyAlpha 已经具有成熟的：

```text
Market Rule Authority
Fee Authority
Settlement Authority
Position Authority
Reservation Authority

        ↓

Immutable Planning
Prepared Transaction
Durable Commit
Ordered Projection
Forward Recovery
```

当前真正没有收口的是：

> **“什么样的交易经济语义有资格进入 Durable Execution Kernel？”**

现在这一判断仍然部分依赖：

```text
market_profile_id == "GENERIC_T0_CASH"
```

这意味着：

```text
Market Product Identity
=
Execution Permission
```

这是错误的 Authority 边界。

P4.1 必须把它改造成：

```text
Market Profile
        ↓
Compiled Market Rules
        ↓
Trade Application Instruction
        ↓
Frozen Execution Semantic Shape
        ↓
Execution Support Authority
        ↓
DURABLE / UNSUPPORTED
        ↓
Canonical Transaction Planner
```

最终必须成立：

> **OnlyAlpha 不支持“某个市场名字”，OnlyAlpha 支持“某种已经实现并验证的经济交易语义”。**

---

# 2. P4.1 是 Authority Correction，不是 Feature Expansion

P4.1 不以新增用户功能为目标。

P4.1 不意味着：

```text
CN_A_SHARE_CASH Product Ready
```

也不意味着：

```text
BUY OPEN terminal durable
```

更不意味着：

```text
Futures
Margin
Short
Hedging
```

已经支持。

P4.1 只解决：

```text
谁有资格决定 Execution 是否被支持？
```

答案必须唯一：

```text
OnlyExecutionCapabilityResolver
```

或等价的唯一纯语义 Authority。

---

# 3. 第一性原则

所有实现必须遵守以下原则。

---

## 3.1 Market Identity is Evidence, Not Permission

以下字段可以继续存在：

```text
profile_id
profile_version
market
venue
compiled_rules_fingerprint
reference_fingerprint
```

它们属于：

```text
Audit
Fact
Artifact
Recovery Proof
Diagnostics
```

但不得用于：

```text
Execution Permission
```

禁止：

```python
if market_profile_id == "GENERIC_T0_CASH":
    durable = True
```

也禁止：

```python
if market_profile_id in {
    "GENERIC_T0_CASH",
    "CN_A_SHARE_CASH",
}:
    durable = True
```

更禁止未来扩展成：

```python
if CN_A_SHARE:
elif US_EQUITY:
elif FUTURES:
elif CRYPTO:
```

---

# 4. Execution Capability 必须由经济语义决定

正确输入应该是：

```text
Operation Kind

Account Type

Order Type

Order Side

Offset

Position Side

Position Effect

Position Mode

Margin Shape

Reservation Shape

Account / Strategy Ledger Authority Parity

Settlement / Instruction Shape
```

这些才是真正决定当前 Durable Kernel 是否能处理该 Operation 的事实。

---

# 5. Market Capability 与 Execution Capability 必须严格区分

当前：

```text
OnlyMarketCapabilitySet
```

表达：

```text
supports_t_plus_n
supports_short_selling
supports_margin
supports_hedging
supports_partial_fill
...
```

它回答的是：

> **市场允许什么？**

P4.1 新的 Execution Support Authority 回答：

> **OnlyAlpha 当前实现了什么？**

必须始终保持：

```text
Market Capability
        ≠
Execution Implementation Capability
```

更准确的是：

```text
Market Semantics
        ↓
Compiled Instructions
        ↓
Execution Implementation Support
        ↓
Durable Decision
```

---

# 6. 禁止直接用 OnlyMarketCapabilitySet 开权限

错误：

```python
if market_capabilities.supports_margin:
    return DURABLE_TRADE
```

因为：

```text
Market supports Margin
```

只说明市场有 Margin。

它完全不能证明：

```text
OnlyAlpha durable margin execution
```

已经实现。

P4.1 不能建立：

```text
Market Feature Flag
→ Automatic Durable Permission
```

这种危险耦合。

---

# 7. Capability Resolver 必须成为唯一支持 Authority

当前需要重新审计：

```text
src/onlyalpha/execution/capability.py
src/onlyalpha/execution/trade_planner.py
src/onlyalpha/execution/terminal_planner.py
src/onlyalpha/execution/processor.py
```

现在存在的根本问题是：

```text
Capability Resolver
    判断一次

Trade Planner
    又根据 GENERIC_T0_CASH 判断一次

Terminal Planner
    可能再次 resolve capability
```

这种结构必须删除。

最终：

```text
Frozen Semantic Context
        ↓
Capability Resolver
        ↓
One Decision
        ↓
Planner
```

Planner 不允许再重新问：

```text
“这个市场/产品支持吗？”
```

---

# 8. Planner 的职责

Capability Resolver：

```text
Can this semantic shape be processed?
```

Planner：

```text
Is this concrete transaction economically valid,
and what immutable projections must be produced?
```

二者必须严格分离。

Capability 可以验证：

```text
CASH
LIMIT
LONG
NETTING
NO MARGIN
correct Reservation Shape
Account/Ledger parity
```

Planner 继续验证：

```text
reservation amount sufficient
fill quantity valid
version/precondition valid
fee increment valid
risk remaining notional valid
economic reducer invariants
```

不要把这些全部塞进 Capability Resolver。

---

# 9. Pre-Implementation Audit

开始修改前，必须先完成只读审计。

重点文件至少包括：

```text
src/onlyalpha/execution/capability.py
src/onlyalpha/execution/processor.py
src/onlyalpha/execution/trade_planner.py
src/onlyalpha/execution/terminal_planner.py
src/onlyalpha/execution/planning_context.py
src/onlyalpha/execution/planning_results.py
src/onlyalpha/execution/execution_state.py
src/onlyalpha/execution/economic_invariants.py

src/onlyalpha/market/runtime_rules.py
src/onlyalpha/market/registry.py
src/onlyalpha/market/models.py

src/onlyalpha/runtime/backtest/runtime.py

tests/execution/
tests/architecture/
tests/integration/
tests/recovery/
tests/conformance/
```

全仓搜索：

```text
only_resolve_execution_capability

OnlyExecutionCapability

market_profile_id

GENERIC_T0_CASH

CN_A_SHARE_CASH

_PROFILE_ID

DURABLE_TRADE

DURABLE_TERMINAL

UNSUPPORTED_MARKET_PROFILE

account_ledger_parity

position_reservation

account_cash_reservation

strategy_cash_reservation

margin_reservation

risk_reservation
```

输出：

```text
docs/reports/
p4_1_execution_capability_pre_implementation_audit.md
```

---

# 10. Audit Report 必须回答

至少：

```text
Current capability call graph

Current capability inputs

Current capability consumers

All profile-name execution gates

All duplicate planner capability checks

Trade reservation shapes

Terminal reservation shapes

Account/Ledger parity semantics

Settlement instruction semantics

Current unsupported semantic shapes

Current generic naming leakage

Current tests encoding GENERIC_T0_CASH as permission
```

并列出：

```text
Interfaces to delete
Interfaces to introduce
Interfaces to keep
Explicit P4.1 non-scope
```

---

# 11. 建立正式 Execution Support Semantic Model

建议增加：

```text
src/onlyalpha/execution/support.py
```

或者与当前项目结构更一致的：

```text
support_context.py
```

不要创建大型 package hierarchy。

核心模型建议如下。

---

# 12. OnlyExecutionReservationShape

建议：

```python
@dataclass(frozen=True, slots=True)
class OnlyExecutionReservationShape:
    account_cash: bool
    strategy_cash: bool
    position: bool
    margin: bool
    risk: bool
```

它描述：

> 当前 Operation 已经冻结了哪些 Reservation Authority。

这不是 Manager Query。

它必须由已经捕获的 immutable state 投影得到。

---

# 13. BUY OPEN Reservation Shape

正式第一版语义：

```text
BUY OPEN

account_cash     = True
strategy_cash    = True
position         = False
margin           = False
risk             = True
```

这是当前 Cash Long BUY OPEN Durable Fill 所要求的结构。

---

# 14. SELL CLOSE Reservation Shape

正式第一版：

```text
SELL CLOSE

account_cash     = False
strategy_cash    = False
position         = True
margin           = False
risk             = True
```

---

# 15. Reservation Shape 必须是 Capability Authority 的正式输入

不能继续通过：

```text
side / offset
```

暗中推断：

```text
应该有哪些 reservation
```

然后等 Planner 才发现实际 Reservation 不存在。

正确：

```text
Order semantics
        +
Actual captured reservation authority
        ↓
Reservation Shape
```

然后：

```text
Resolver
```

判断：

```text
这种 shape 是否是 Kernel 明确支持的 shape
```

---

# 16. OnlyExecutionSupportContext

建议建立：

```python
@dataclass(frozen=True, slots=True)
class OnlyExecutionSupportContext:
    operation_kind: OnlyRuntimeOperationKind

    account_type: OnlyAccountType

    order_type: OnlyOrderType
    order_side: OnlyOrderSide
    offset: OnlyOffset

    position_side: OnlyPositionSide
    position_effect: OnlyPositionEffect
    position_mode: OnlyPositionMode

    has_margin: bool

    account_ledger_parity: bool

    reservations: OnlyExecutionReservationShape
```

根据最新源码，如果还存在其它真正决定 Kernel Shape 的字段，可以加入。

但加入任何字段前必须回答：

> **它改变的是 Execution Implementation Capability，还是仅仅是市场/审计事实？**

如果只是：

```text
market
venue
profile
broker name
```

不能加入。

---

# 17. `market_profile_id` 明确不得进入 Support Context

这是 P4.1 的硬 Architecture Invariant。

禁止：

```python
class OnlyExecutionSupportContext:
    market_profile_id: str
```

也禁止换个名字：

```text
product_id
market_family
profile_family
```

继续实现同一个错误模型。

---

# 18. Settlement 如何处理

P4.1 不能简单：

```text
忽略 Settlement
```

但也不能：

```text
T0 → supported
T1 → supported
```

把 Profile-name gate 换成 Settlement-name gate。

应该审计当前 Durable Trade Planner 实际能表达的 Settlement Shape。

当前 Planner 已经消费：

```text
OnlyTradeApplicationInstruction.settlement_schedule
```

并根据：

```text
asset_trade_available_on
```

决定：

```text
SETTLED / UNSETTLED
```

因此 P4.1 要确认：

> 当前 Transaction Kernel 支持的是“一个明确、可投影、Trading-Day-based 的 settlement schedule”，而不是“GENERIC T0”。

如果现有 Settlement 类型已经足够表达：

不增加新的 capability field。

如果确实必须验证 Settlement Shape：

增加一个 market-neutral：

```text
OnlyExecutionSettlementShape
```

例如只表达：

```text
asset availability is representable
cash availability is representable
settlement instruction exists
```

不要放：

```text
T0
T1
CN_A_SHARE
```

产品名称。

---

# 19. 不要过度设计 Settlement Capability

P4.1 的核心问题不是设计 Universal Settlement Capability DSL。

如果当前 Trade Instruction 已经能完整给 Planner Settlement Authority：

优先继续消费现有 Instruction。

只有在 Capability Resolver 必须提前区分：

```text
Kernel 可以处理
vs
Kernel 无法处理
```

时才增加最小 structural field。

---

# 20. OnlyExecutionSupportReason

当前：

```text
UNSUPPORTED
```

过于粗糙。

建议新增 typed reason：

```python
class OnlyExecutionSupportReason(StrEnum):
    OPERATION_KIND_UNSUPPORTED = ...
    ACCOUNT_TYPE_UNSUPPORTED = ...
    ORDER_TYPE_UNSUPPORTED = ...
    POSITION_SIDE_UNSUPPORTED = ...
    POSITION_MODE_UNSUPPORTED = ...
    POSITION_EFFECT_UNSUPPORTED = ...
    MARGIN_UNSUPPORTED = ...
    ACCOUNT_LEDGER_PARITY_REQUIRED = ...
    RESERVATION_SHAPE_UNSUPPORTED = ...
    TERMINAL_SHAPE_UNSUPPORTED = ...
```

根据最终审计调整。

不要增加：

```text
CN_A_SHARE_UNSUPPORTED
GENERIC_PROFILE_REQUIRED
```

这种 product reason。

---

# 21. OnlyExecutionSupportDecision

建议：

```python
@dataclass(frozen=True, slots=True)
class OnlyExecutionSupportDecision:
    capability: OnlyExecutionCapability
    reason: OnlyExecutionSupportReason | None
    schema_version: str
    fingerprint: str
```

或者保持最小：

```text
capability
reason
```

如果 fingerprint/版本能够自然进入 Fact/Audit，则一开始正式建立更好。

---

# 22. Decision Invariant

必须保证：

```text
DURABLE_TRADE / DURABLE_TERMINAL
→ reason is None
```

而：

```text
UNSUPPORTED
→ reason is not None
```

不要允许：

```text
UNSUPPORTED + no explanation
```

---

# 23. Decision Fingerprint

如果增加 fingerprint：

必须由 canonical semantic payload 生成。

例如：

```text
schema_version
operation_kind
account_type
order_type
order_side
offset
position_side
position_effect
position_mode
has_margin
account_ledger_parity
reservation_shape
decision
reason
```

不包含：

```text
market_profile_id
market name
instrument id
broker id
runtime id
```

除非它们真实影响 Capability。

---

# 24. Resolver 应成为类还是函数

当前是：

```python
only_resolve_execution_capability(...)
```

P4.1 建议收口为：

```python
class OnlyExecutionCapabilityResolver:
    def resolve(
        self,
        context: OnlyExecutionSupportContext,
    ) -> OnlyExecutionSupportDecision:
        ...
```

理由：

```text
输入从散参数收口成一个 domain value

输出从 enum 收口成 typed decision

后续 capability policy schema 更容易管理
```

但 Resolver 必须保持：

```text
stateless
pure
deterministic
```

不要给它 Registry、Manager、Config dependency。

---

# 25. 不保留旧函数 Wrapper

迁移完成后删除：

```python
only_resolve_execution_capability(
    operation_kind,
    market_profile_id,
    ...
)
```

不要：

```python
def only_resolve_execution_capability(...):
    return OnlyExecutionCapabilityResolver().resolve(...)
```

作为兼容层继续存在。

修改所有调用点。

Git 已保存历史。

---

# 26. 第一版 Durable Trade Matrix

P4.1 必须明确当前 Kernel **实际支持**什么。

不要扩大能力。

第一版：

```text
operation:
TRADE_FILL

account:
CASH

order:
LIMIT

position:
LONG
NETTING

margin:
False

account/ledger:
parity required

economic shape:
BUY + OPEN
SELL + CLOSE
```

满足：

```text
correct Reservation Shape
```

后：

```text
DURABLE_TRADE
```

---

# 27. BUY OPEN Trade

要求：

```text
BUY
OPEN
LONG
NETTING
CASH
LIMIT
NO MARGIN

Reservation:
Account Cash = yes
Strategy Cash = yes
Position = no
Margin = no
Risk = yes
```

→

```text
DURABLE_TRADE
```

---

# 28. SELL CLOSE Trade

要求：

```text
SELL
CLOSE
LONG
NETTING
CASH
LIMIT
NO MARGIN

Reservation:
Account Cash = no
Strategy Cash = no
Position = yes
Margin = no
Risk = yes
```

→

```text
DURABLE_TRADE
```

---

# 29. Terminal 第一版 Capability 必须保持真实

当前 Durable Terminal Planner 只真正支持 Long Close terminal。

所以 P4.1 不能为了“语义漂亮”提前声明：

```text
BUY OPEN terminal → DURABLE_TERMINAL
```

当前应继续：

```text
SELL CLOSE
+
Position reservation
+
Risk reservation
→ DURABLE_TERMINAL
```

而：

```text
BUY OPEN
→ UNSUPPORTED / TERMINAL_SHAPE_UNSUPPORTED
```

直到 P4.3 真正实现 BUY OPEN durable terminal。

---

# 30. 不支持的语义必须 Fail Closed

至少：

```text
MARGIN ACCOUNT

MARKET ORDER
如果当前未正式支持

SHORT

HEDGING

SELL OPEN

BUY CLOSE

margin_required = True

account_ledger_parity = False

wrong reservation shape
```

→

```text
UNSUPPORTED
```

不能：

```text
fallback legacy
fallback generic
best effort
```

---

# 31. 不允许 Market Profile 对 Decision 产生影响

必须建立核心测试：

两个完全不同 Market Identity：

```text
GENERIC_T0_CASH
```

和：

```text
CN_A_SHARE_CASH
```

如果最终投影为完全相同的：

```text
OnlyExecutionSupportContext
```

则：

```text
OnlyExecutionSupportDecision
```

必须完全相同。

更准确地说：

> Resolver 根本不应该看到 Market Identity，因此这个不变量最好由类型结构自然保证，而不只是测试保证。

---

# 32. Market Identity 仍然保留在 Fact/Audit 层

不要为了 P4.1 删除：

```text
compiled_identity.profile_id
profile_version
market
venue
reference_fingerprint
resolved_profile_fingerprint
compiled_rules_fingerprint
```

这些继续保留。

P4.1 改变的是：

```text
Permission semantics
```

不是：

```text
Traceability semantics
```

---

# 33. Identity is Evidence, Not Permission

这是 ADR 必须明确写下的一句话：

```text
Market identity is evidence, not permission.
```

含义：

```text
Market Profile
可以证明“这笔交易来自什么市场规则”
```

但不能决定：

```text
“Kernel 是否支持它”
```

---

# 34. Support Context Builder

不要让：

```text
Execution Processor
Trade Planner
Terminal Planner
```

分别手工投影 Capability fields。

应该有唯一 pure projection path。

例如：

```python
def only_trade_execution_support_context(
    context: OnlyTradeExecutionPlanningContext,
) -> OnlyExecutionSupportContext:
    ...
```

以及：

```python
def only_terminal_execution_support_context(
    context: OnlyTerminalExecutionPlanningContext,
) -> OnlyExecutionSupportContext:
    ...
```

---

# 35. Context Builder 必须只投影 immutable authority

不能读取：

```text
OrderManager
PositionManager
AccountManager
RiskManager
Registry
Broker
```

它只能读取已经捕获的 Planning Context。

---

# 36. 为什么不能让 Resolver 访问 Manager

否则会出现：

```text
Capability Decision
```

依赖实时 mutable state。

那么：

```text
same Broker Update
```

在不同执行时刻可能得到不同：

```text
support result
```

这会破坏：

```text
determinism
recovery
auditability
```

所以：

```text
Frozen Authority
→ Pure Capability Decision
```

必须成立。

---

# 37. Trade Planning Context 与 Capability Decision

建议最终：

```text
OnlyTradeExecutionPlanningContext
```

包含：

```text
support_decision: OnlyExecutionSupportDecision
```

如果直接修改当前 Context 影响过大，也可以给 Planner：

```python
prepare(
    context,
    support_decision,
)
```

但只能有一种正式接口。

不要同时保留两种。

---

# 38. 我更推荐 Context 内包含 Decision

目标：

```text
Broker Update
        ↓
Capture all immutable authority
        ↓
Build Planning Context
        ↓
Project Support Context
        ↓
Resolve Support Decision
        ↓
Freeze Decision into Planning Authority
        ↓
Planner
```

这样 Planner 拿到的是：

```text
完整且已经批准的 immutable authority
```

---

# 39. 不允许 Planner 重新调用 Resolver

禁止：

```python
decision = resolver.resolve(...)
```

出现在：

```text
trade_planner.py
terminal_planner.py
```

Planner 只验证：

```text
provided support decision
```

和：

```text
operation kind
```

是否匹配。

---

# 40. Trade Planner 删除 Profile Gate

当前必须删除：

```python
_PROFILE_ID = "GENERIC_T0_CASH"
```

删除所有：

```text
compiled_identity.profile_id == _PROFILE_ID
```

支持判定。

删除：

```text
UNSUPPORTED_MARKET_PROFILE
```

如果该错误只服务这个错误 gate。

如果错误 enum 在其他地方仍有真实职责，则保留真实职责。

---

# 41. Trade Planner Module Documentation 也必须修正

不要继续：

```text
Generic T0 Cash Trade transaction planner
```

如果实现已经是：

```text
Durable Cash-Long semantic planner
```

更新为准确描述。

不要留下：

```text
Generic T0
```

旧概念作为注释墓碑。

---

# 42. Planner 不能变成 A-share Planner

禁止新增：

```text
AshareTradePlanner

CnAshareExecutionPlanner

AshareCapabilityResolver
```

P4.1 的目的恰恰是避免这种结构。

---

# 43. Terminal Planner 也必须删除 Profile-level Support Authority

审计当前 Terminal Planner 是否：

```text
重新调用 only_resolve_execution_capability
```

或者自己判断：

```text
GENERIC_T0_CASH
```

如果存在：

删除。

它只接受：

```text
support_decision == DURABLE_TERMINAL
```

并继续处理当前真实支持的 SELL CLOSE terminal。

---

# 44. P4.1 不实现 BUY OPEN Durable Terminal

这是硬 Scope Boundary。

虽然新的 Reservation Shape 已经可以描述：

```text
BUY OPEN terminal
```

但当前 Planner 尚未原子投影：

```text
Account Cash Reservation
Strategy Cash Reservation
Risk Reservation
Order
```

所以 Decision 必须：

```text
UNSUPPORTED
```

直到 P4.3。

不要为了测试矩阵对称性提前返回：

```text
DURABLE_TERMINAL
```

---

# 45. Processor Routing

P4.1 后 Processor 应尽量形成：

```text
Build/Capture Planning Authority
        ↓
Project Support Context
        ↓
Capability Resolver
        ↓
Support Decision
        ↓
switch capability
```

而不是：

```text
if generic cash
if sell close
if buy open
```

散落路由。

---

# 46. Processor 不应该拥有 Support Matrix

禁止把 Resolver 重构成：

```python
if some_context:
    ...
```

然后 Processor 又重新：

```python
if buy_open:
...
elif sell_close:
...
```

决定是否 durable。

所有：

```text
supported / unsupported
```

必须来自 Decision。

Processor 只负责：

```text
route Decision
```

---

# 47. Capability Decision 与 Committed Fact

建议 P4.1 把 execution support proof 写入：

```text
OnlyCommittedExecutionFact
OnlyCommittedTerminalExecutionFact
```

至少保存：

```text
execution_capability
execution_support_schema_version
execution_support_fingerprint
```

具体字段根据现有 Fact schema 设计。

---

# 48. 为什么值得持久化 Support Proof

未来 Capability Matrix 会演进。

例如将来：

```text
v1:
Cash Long only

v2:
add Margin Long

v3:
add Short
```

历史 Fact 应该能够回答：

> 当时为什么这笔交易被允许进入 Durable Kernel？

而不是只能根据今天代码反推。

---

# 49. Support Proof 不是恢复 Authority 的替代品

不要把整份巨大 Support Context 塞进 Fact。

只需要足够：

```text
schema/policy version
capability
fingerprint
```

并保留原有：

```text
Market Rule Identity
Trade Instruction
Authority facts
```

即可。

---

# 50. Support Policy Version

建议一开始建立明确版本：

```text
execution_support_schema_version = "1"
```

或者：

```text
EXECUTION_SUPPORT_POLICY_VERSION = "1"
```

不需要 Registry。

不需要 Plugin。

不需要 Config。

当前 Execution Support Matrix 是：

```text
trusted product code authority
```

即可。

---

# 51. 不要设计 Capability DSL

P4.1 禁止建立：

```text
YAML capability rules
plugin capability policy
dynamic expression engine
execution capability registry
```

当前支持矩阵很小。

纯 Python typed predicate 最清楚、最安全、最容易测试。

---

# 52. Tests — Core Semantic Matrix

重写：

```text
tests/execution/test_execution_capability.py
```

不要继续围绕：

```text
GENERIC_T0_CASH
```

命名。

例如：

```text
test_cash_long_netting_buy_open_trade_is_durable
test_cash_long_netting_sell_close_trade_is_durable
test_account_ledger_parity_is_required
test_margin_shape_is_unsupported
test_short_shape_is_unsupported
test_hedging_shape_is_unsupported
```

---

# 53. BUY OPEN Trade Matrix

至少：

```text
correct reservation shape
→ DURABLE_TRADE
```

然后逐一缺失：

```text
account cash reservation
strategy cash reservation
risk reservation
```

→

```text
UNSUPPORTED
RESERVATION_SHAPE_UNSUPPORTED
```

---

# 54. SELL CLOSE Trade Matrix

正确：

```text
position reservation
risk reservation
```

→

```text
DURABLE_TRADE
```

缺任意 required reservation：

```text
UNSUPPORTED
```

---

# 55. Extra Reservation 是否允许

必须明确规则。

例如 SELL CLOSE 如果意外存在：

```text
account_cash = True
```

是否仍接受？

我建议第一版：

> **Strict exact shape。**

也就是：

```text
unexpected authority
→ UNSUPPORTED
```

理由：

错误的额外 Reservation 往往意味着上游语义发生了漂移。

Fail Closed 比“反正不用它”更安全。

---

# 56. Terminal Matrix

当前真实支持：

```text
SELL CLOSE
exact Position + Risk reservation shape
→ DURABLE_TERMINAL
```

BUY OPEN：

```text
exact Cash + Strategy Cash + Risk shape
→ UNSUPPORTED
TERMINAL_SHAPE_UNSUPPORTED
```

这个结果必须明确冻结。

---

# 57. Account/Ledger Parity Matrix

```text
account_ledger_parity=True
→ continue

False
→ UNSUPPORTED
ACCOUNT_LEDGER_PARITY_REQUIRED
```

TRADE 和 TERMINAL 根据当前真实要求分别测试。

不要让 Planner 最后才发现双 Authority。

---

# 58. Account Type Matrix

当前：

```text
CASH
```

支持。

任何其它 Account Type：

```text
UNSUPPORTED
ACCOUNT_TYPE_UNSUPPORTED
```

不要因为市场是 Generic Futures 就自动支持。

---

# 59. Position Matrix

当前：

```text
LONG + NETTING
```

支持。

```text
SHORT
```

→ unsupported。

```text
HEDGING
```

→ unsupported。

---

# 60. Order Matrix

当前正式支持：

```text
LIMIT
```

其它：

```text
MARKET
STOP
...
```

如果 Kernel 未有产品化测试：

全部 Fail Closed。

不要根据理论“Reducer 应该也能算”就宣称支持。

---

# 61. Offset / Position Effect Matrix

合法：

```text
BUY + OPEN + OPEN
SELL + CLOSE + CLOSE
```

不合法/未支持：

```text
SELL + OPEN
BUY + CLOSE
AUTO unresolved
CLOSE_TODAY
```

根据当前 enum/规则实际情况精确测试。

---

# 62. Different Market, Same Shape Test

这是 P4.1 最关键的 Architecture Test 之一。

测试不应该通过：

```text
给 Resolver 两个 market IDs
```

因为 Resolver 已经没有 market。

而应该从两个真实 Market Planning Context 出发：

```text
GENERIC_T0_CASH
CN_A_SHARE_CASH
```

最终投影出的：

```text
OnlyExecutionSupportContext
```

在语义相同场景下：

```text
相等
```

或至少 Capability-relevant projection 相等。

最终：

```text
Decision equal
```

这证明：

```text
Market identity
```

已经退出 Permission Authority。

---

# 63. Same Market, Different Shape Counterexample

同样：

```text
CN_A_SHARE_CASH
```

两个场景：

```text
LONG NETTING
```

和：

```text
SHORT
```

必须得到不同 Decision。

证明：

```text
Economic semantics
```

才是真正的变量。

---

# 64. Architecture Guards

新增明确 source guard。

在：

```text
src/onlyalpha/execution/capability.py
```

禁止：

```text
GENERIC_T0_CASH
CN_A_SHARE_CASH
OnlyMarketProfileId
market_profile_id
```

Trade Planner 同样禁止：

```text
GENERIC_T0_CASH
CN_A_SHARE_CASH
OnlyMarketProfileId
```

Terminal Planner 同样。

---

# 65. Guard 不要过度禁止 Audit Identity

不要全局禁止 Execution 包引用：

```text
compiled_identity.profile_id
```

因为 Fact/Audit 仍可能合法需要。

Guard 应针对：

```text
capability routing
planner support gate
```

而不是把所有市场身份从 Execution Fact 中删除。

---

# 66. Architecture Guard：Resolver 唯一性

确保：

```text
OnlyExecutionCapabilityResolver.resolve
```

只有：

```text
processor/context preparation boundary
```

等正式入口调用。

禁止：

```text
trade_planner.py
terminal_planner.py
reducers/
```

重新 resolve。

---

# 67. Architecture Guard：No Legacy Wrapper

禁止：

```text
only_resolve_execution_capability(...)
```

旧接口残留，如果已经被新 Resolver 替代。

禁止：

```text
resolve_legacy_execution_capability
```

禁止 compatibility alias。

---

# 68. Planner Unit Tests

Trade Planner Tests 不再通过：

```text
profile == GENERIC_T0_CASH
```

证明能力。

应该构造：

```text
support_decision = DURABLE_TRADE
```

然后验证：

```text
concrete planner invariants
```

另外增加：

```text
planner rejects non-DURABLE_TRADE decision
```

但 Planner 不能自己 resolve。

---

# 69. Planner 不再返回 Unsupported Product Reason

例如：

```text
UNSUPPORTED_MARKET_PROFILE
```

这种错误不属于 Planner。

Capability Resolver 已经决定：

```text
UNSUPPORTED
```

Processor 根本不应该进入 Planner。

Planner 收到 unsupported decision：

```text
INTERNAL_CAPABILITY_ROUTING_INVARIANT_FAILED
```

或者等价 internal invariant。

这代表调用错误，不代表市场不支持。

---

# 70. P4.1 对 Error Semantics 的要求

不要大规模重构 Error System。

建议明确区分：

```text
Support Reason
```

与：

```text
Planning Error
```

Support：

```text
ACCOUNT_TYPE_UNSUPPORTED
MARGIN_UNSUPPORTED
...
```

Planning：

```text
RESERVATION_INSUFFICIENT
FEE_ACCRUAL_NEGATIVE_INCREMENT
REDUCTION_INVARIANT_FAILED
...
```

不要混用。

---

# 71. Processor Unsupported 行为

P4.1 不应该偷偷改变现有 Unsupported update 的外部产品行为。

当前如何：

```text
reject
reconciliation required
fail closed
```

则继续使用现有正式语义。

本阶段只是让：

```text
why unsupported
```

来源变得干净和 typed。

---

# 72. Recovery

P4.1 修改 Capability Authority 后必须完整运行 Recovery。

重点验证：

```text
historical Generic T0 transaction
```

仍能恢复。

如果 Support Proof 新增到 persisted Fact：

必须验证：

```text
capture
persist
restore
recovery
```

稳定。

---

# 73. 不根据恢复时的最新 Capability Matrix 重新授权历史交易

这是一个重要原则。

历史已提交 Transaction：

```text
已经是 committed fact
```

Recovery 不应该重新运行：

```text
today's capability resolver
```

决定它现在是否支持。

Capability Resolver 用于：

```text
new operation admission
```

不是：

```text
historical fact validity
```

---

# 74. 如果 Support Proof 进入 Persisted Schema

只升级真正受影响的：

```text
Committed Execution Fact
Terminal Fact
Artifact
```

不要机械升级：

```text
generic transaction envelope
```

如果它本身没有变化。

---

# 75. 旧 Schema

如果当前 Alpha 项目策略仍然是：

```text
no implicit compatibility migration
```

则遵循现有策略。

不要为 P4.1 新增：

```text
if missing execution_support:
    assume GENERIC_T0
```

这是绝对禁止的。

---

# 76. P4.1 不允许新增 Profile Compatibility Mapping

禁止这种“看似抽象”的设计：

```python
PROFILE_TO_EXECUTION_SHAPE = {
    "GENERIC_T0_CASH": CASH_LONG,
    "CN_A_SHARE_CASH": CASH_LONG,
}
```

它仍然是：

```text
Profile Name
→ Execution Permission
```

只是换成了 Mapping。

错误本质没有改变。

---

# 77. Execution Shape 必须来自真实 Instruction/Context

不能：

```text
profile → shape
```

必须：

```text
Compiled Rules
→ Trade Instruction
→ Captured Position/Reservation Authority
→ Execution Support Context
```

---

# 78. 不允许 Product-specific Capability Class

禁止：

```text
OnlyAshareExecutionCapability

OnlyGenericT0Capability

OnlyFuturesExecutionCapability
```

当前真正不同的是：

```text
Economic Shape
```

不是产品类名。

---

# 79. 不允许 Capability Provider Plugin

P4.1 不创建：

```text
OnlyExecutionCapabilityProviderRegistry
```

没有必要。

未来如果存在真正不同的 implementation backend，再评估。

当前单一 Canonical Kernel 使用一套 static semantic policy 就足够。

---

# 80. P4.1 与 P4.3 Terminal 的明确边界

P4.1：

```text
能够描述 BUY OPEN terminal shape
但明确判 UNSUPPORTED
```

P4.3：

```text
实现 BUY OPEN Terminal Prepared Transaction

Order
Account Cash Reservation
Strategy Cash Reservation
Risk Reservation
Risk
```

然后再把同一 shape 的 Decision：

```text
UNSUPPORTED
→ DURABLE_TERMINAL
```

这体现正确开发模式：

> **先定义语义，再实现能力，再开放 capability。**

而不是：

> 先开放 capability，再补实现。

---

# 81. P4.1 与 A 股 P4.4 的边界

P4.1 完成后：

```text
CN_A_SHARE_CASH
```

生成的：

```text
Cash + Limit + Long + Netting + Buy/Open
```

语义理论上可被 Resolver 判为：

```text
DURABLE_TRADE
```

但 P4.1 不需要建立完整 A 股 E2E Product Conformance。

P4.4 才正式跑：

```text
Reference
PreTrade
Order
Fee
Broker
Fill
Transaction
Position
Settlement
```

---

# 82. P4.1 不修改 A-share Market Rules

禁止修改：

```text
ashare_rules.py
price limit
lot rules
T+1 rules
reference
fee pack
```

除非发现它们阻止准确构造 Execution Support Semantic，而且问题属于通用接口缺失。

这种情况必须在 Report 中证明。

---

# 83. P4.1 不修改 Fee Kernel

Fee Assessment 已经是 Planning Context 的正式输入。

P4.1 不重构：

```text
FeeResolver
FeeEngine
FeeAccrual
Broker Fee Contract
Market Fee Pack
Reconciliation
```

---

# 84. P4.1 不修改 Runtime Composition

P4-0 已完成：

```text
Runtime Environment Authority
Resource Claims
Registry Ownership
Composition Atomicity
```

P4.1 不回头重构这些东西。

---

# 85. P4.1 不修改 Paper / Live

不做：

```text
Paper recovery
Live runtime
Broker durable command
```

---

# 86. 推荐 Commit 结构

## Commit 1 — ADR + Audit

```text
Docs: Freeze Durable Execution Support Authority
```

完成：

```text
Pre-implementation audit
ADR
Current support matrix
Explicit non-scope
```

---

## Commit 2 — Execution Support Semantic Model

```text
Refactor: Introduce Execution Support Semantic Authority
```

新增：

```text
Reservation Shape
Support Context
Support Reason
Support Decision
canonical fingerprint/version if selected
```

以及 Unit Tests。

暂不迁移所有调用点也可以，但 Commit 必须保持 tests green。

---

## Commit 3 — Capability Resolver Migration

```text
Refactor: Resolve Execution Capability from Semantic Shape
```

完成：

```text
OnlyExecutionCapabilityResolver

remove market_profile_id

remove generic_cash

migrate Processor
```

删除旧 resolver API。

---

## Commit 4 — Planner Authority Cleanup

```text
Refactor: Remove Product Identity from Durable Planners
```

完成：

```text
delete _PROFILE_ID

delete planner-level profile permission checks

remove duplicate resolver calls

Trade/Terminal planners consume frozen decision
```

---

## Commit 5 — Support Proof + Persistence

如果最终设计选择把 Support Proof 写入 Facts：

```text
Feat: Persist Durable Execution Support Proof
```

单独做 schema / recovery tests。

如果现有 Fact 已能自然承担，不强制独立 commit。

---

## Commit 6 — Architecture Guards + Matrix Tests

```text
Test: Freeze Market-Neutral Execution Support Semantics
```

增加：

```text
semantic matrix
different-market same-shape
same-market different-shape
reservation matrix
architecture guards
```

---

## Commit 7 — Docs + Report

```text
Docs: Close P4.1 Execution Capability Authority
```

更新：

```text
roadmap
ADR final state
implementation report
```

---

# 87. ADR

新增：

```text
docs/adr/
<next>-durable-execution-capability-semantic-authority.md
```

必须回答：

```text
What is Market Capability?

What is Execution Implementation Capability?

Why Market Profile identity cannot grant durable permission?

What facts define Execution Support Context?

Why Reservation Shape belongs in support semantics?

Why Resolver is pure?

Why Planner cannot re-resolve support?

Why BUY OPEN terminal remains unsupported in P4.1?

Why Product Certification is separate from Kernel Support?
```

---

# 88. Implementation Report

新增：

```text
docs/reports/
p4_1_durable_execution_capability_semantic_authority.md
```

至少：

```text
Baseline

Before Architecture

Root Cause

New Support Semantic Model

Reservation Shape

Support Matrix

Deleted Interfaces

Planner Authority Cleanup

Market Identity Audit Boundary

Persistence / Fact Changes

Recovery Impact

Architecture Guards

Quality Gates

Explicit P4.1 Unsupported Scope

Next P4.2 / P4.3 / P4.4
```

---

# 89. Deleted Interfaces 必须单列

至少审计并报告：

```text
old only_resolve_execution_capability

market_profile_id capability argument

generic_cash predicate

_PROFILE_ID

UNSUPPORTED_MARKET_PROFILE planner gate

planner-side duplicate resolver call

terminal-side duplicate resolver call

old generic-profile-specific capability tests
```

凡是不再有职责：

```text
直接删除
```

不要 deprecated alias。

---

# 90. Architecture Guard — No Market Permission

必须有类似测试：

```text
execution capability source
does not contain:
    GENERIC_T0_CASH
    CN_A_SHARE_CASH
    market_profile_id
```

Trade Planner 同样。

Terminal Planner 同样。

---

# 91. Architecture Guard — Single Capability Authority

禁止：

```text
trade_planner
terminal_planner
reducers
```

直接 import：

```text
OnlyExecutionCapabilityResolver
```

只有正式 routing / authority-capture boundary 可以 resolve。

---

# 92. Architecture Guard — No Compatibility API

如果旧：

```text
only_resolve_execution_capability
```

被删除：

测试确保生产代码不再使用。

---

# 93. Static Gates

使用最新 `master` 正式命令。

至少：

```bash
uv sync --frozen --all-packages --all-groups

uv run ruff check src tests examples packages scripts

uv run ruff format --check src tests examples packages scripts

uv run mypy src/onlyalpha
```

以及最新正式 provider mypy。

---

# 94. Test Lanes

执行当前正式：

```bash
uv run python scripts/test_suite.py fast

uv run python scripts/test_suite.py integration

uv run python scripts/test_suite.py core-full

uv run python scripts/test_suite.py recovery

uv run python scripts/test_suite.py ashare

uv run python scripts/test_suite.py miniqmt-contract

uv run python scripts/test_suite.py exhaustive
```

如果最新 master 已调整：

以仓库当前正式 Gate 为准。

---

# 95. Build

```bash
uv build --all-packages
```

必须 PASS。

---

# 96. 不允许通过测试的方法

禁止：

```text
skip

xfail

删除 Generic T0 recovery tests

删除 long-close durable tests

降低 assertion

保留 old resolver fallback

profile-name compatibility mapping

unsupported → generic fallback

fake support Decision

BUY OPEN terminal 提前宣称 DURABLE
```

---

# 97. P4.1 Definition of Done — Authority

* [ ] Execution Capability 有唯一 Authority。
* [ ] Resolver pure。
* [ ] Resolver deterministic。
* [ ] Resolver fail closed。
* [ ] Resolver 不访问 Manager。
* [ ] Resolver 不访问 Market Profile Registry。
* [ ] Resolver 不接 Broker。
* [ ] Resolver 输入是 immutable semantic context。
* [ ] Planner 不重新 resolve Capability。

---

# 98. Definition of Done — Market-neutrality

* [ ] Capability input 中没有 `market_profile_id`。
* [ ] Capability source 中没有 `GENERIC_T0_CASH`。
* [ ] Capability source 中没有 `CN_A_SHARE_CASH`。
* [ ] Trade Planner 无 `GENERIC_T0_CASH` gate。
* [ ] Terminal Planner 无 Market Profile permission gate。
* [ ] Market identity 仍可存在于 Audit/Facts。
* [ ] Identity 不再等于 Permission。

---

# 99. Definition of Done — Semantic Model

* [ ] `OnlyExecutionReservationShape` 存在或等价正式模型存在。
* [ ] `OnlyExecutionSupportContext` 存在。
* [ ] `OnlyExecutionSupportDecision` 存在。
* [ ] Unsupported 有 typed reason。
* [ ] Decision schema/version 明确。
* [ ] Fingerprint deterministic，如果采用。
* [ ] Context 不包含 product identity。

---

# 100. Definition of Done — Trade Matrix

* [ ] CASH + LIMIT + LONG + NETTING + BUY OPEN 正确 shape → DURABLE_TRADE。
* [ ] CASH + LIMIT + LONG + NETTING + SELL CLOSE 正确 shape → DURABLE_TRADE。
* [ ] Wrong BUY OPEN reservation shape → UNSUPPORTED。
* [ ] Wrong SELL CLOSE reservation shape → UNSUPPORTED。
* [ ] Margin → UNSUPPORTED。
* [ ] Short → UNSUPPORTED。
* [ ] Hedging → UNSUPPORTED。
* [ ] BUY CLOSE → UNSUPPORTED。
* [ ] SELL OPEN → UNSUPPORTED。
* [ ] Account/Ledger parity failure → UNSUPPORTED。

---

# 101. Definition of Done — Terminal Matrix

* [ ] SELL CLOSE exact supported reservation shape → DURABLE_TERMINAL。
* [ ] BUY OPEN terminal → explicitly UNSUPPORTED。
* [ ] BUY OPEN terminal 不会因为新 semantic model 被误放行。
* [ ] Margin terminal 不会被误放行。
* [ ] Unsupported terminal 不进入 Terminal Planner。

---

# 102. Definition of Done — Planner Boundary

* [ ] Trade Planner 只验证 concrete economic invariants。
* [ ] Trade Planner 不判断 Market Product support。
* [ ] Terminal Planner 不判断 Market Product support。
* [ ] Planner 收到错误 capability decision 时视为 routing/internal invariant 错误。
* [ ] 不存在第二套 Support Matrix。

---

# 103. Definition of Done — Tests

* [ ] Different Market / Same Semantic Shape 得到相同 capability decision。
* [ ] Same Market / Different Semantic Shape 得到不同 capability decision。
* [ ] Registration/product identity 不影响 capability。
* [ ] Reservation presence/absence 会正确改变 capability。
* [ ] Unit matrix 完整。
* [ ] Architecture guards 生效。
* [ ] Existing Generic T0 behavior 不回归。
* [ ] Recovery 不回归。

---

# 104. Definition of Done — Persistence

如果 Support Proof persisted：

* [ ] Schema 明确。
* [ ] Support proof deterministic。
* [ ] Recovery 不使用当前最新 Resolver 重新授权历史 Fact。
* [ ] 旧错误 Schema 不使用隐式 GENERIC fallback。
* [ ] No compatibility migration unless existing project policy explicitly requires it。

---

# 105. Definition of Done — Quality

* [ ] dependency sync PASS。
* [ ] Ruff PASS。
* [ ] Ruff Format PASS。
* [ ] Core mypy PASS。
* [ ] Provider mypy PASS。
* [ ] fast PASS。
* [ ] integration PASS。
* [ ] core-full PASS。
* [ ] recovery PASS。
* [ ] ashare PASS。
* [ ] miniqmt-contract PASS。
* [ ] exhaustive PASS。
* [ ] build PASS。
* [ ] GitHub final quality gate PASS。

---

# 106. P4.1 明确非目标

Implementation Report 必须明确：

```text
NOT IMPLEMENTED IN P4.1
```

至少：

```text
BUY OPEN Durable Terminal

CN A-share full durable product conformance

CN A-share complete E2E BUY OPEN slice

CN A-share SELL CLOSE + T+1 closure

Partial/Multi-Fill production product closure

Partial + terminal closure

Market Product Composition Neutralization

Paper checkpoint/restart

Live Runtime

Durable Broker outbound command

Margin durable execution

Short durable execution

Hedging durable execution

Futures durable product

Crypto durable product

Multi-account product

Vectorized backtest
```

---

# 107. P4.1 完成后的能力声明必须准确

完成后允许声明：

```text
Durable execution permission
is semantic-shape driven,
not market-profile driven.
```

可以声明：

```text
Cash Long Netting LIMIT
BUY OPEN / SELL CLOSE Trade shapes
are supported by the canonical durable Trade kernel.
```

但不能直接声明：

```text
CN A-share durable product complete.
```

因为 Product Conformance 还没完成。

---

# 108. P4.1 后续阶段边界

建议明确：

```text
P4.1
Execution Support Semantic Authority
        ↓

P4.2
Residual Planner Semantic Cleanup
        ↓

P4.3
BUY OPEN Durable Terminal Closure
        ↓

P4.4
CN A-share BUY OPEN Product Slice
        ↓

P4.5
CN A-share SELL CLOSE + T+1
        ↓

P4.6
Partial/Multi-Fill + Production Fee
        ↓

P4.7
Partial + Terminal
        ↓

P4.8
Memory/SQLite + A→B→C Recovery
```

具体阶段编号可以根据实施后的实际复杂度合并，但职责不能重新混合。

---

# 109. 最终工程原则

当：

```text
Market Profile Name
```

与：

```text
Execution Semantic Shape
```

冲突：

> Execution Permission 只能由 Semantic Shape 决定。

当：

```text
Market Capability
```

与：

```text
OnlyAlpha Implementation Capability
```

冲突：

> 不允许自动开放能力。

当：

```text
Resolver
```

与：

```text
Planner
```

都想判断“支持不支持”：

> Resolver 是唯一 Authority，Planner 删除重复判定。

当：

```text
方便兼容旧 API
```

与：

```text
单一 Authority
```

冲突：

> 修改调用点并删除旧 API。

当：

```text
Market Profile ID
```

对审计有价值：

> 保留。

当它试图决定 Permission：

> 禁止。

当：

```text
BUY OPEN terminal semantic shape
```

已经能被描述，但 durable implementation 尚未完成：

> 明确返回 UNSUPPORTED。

不要提前开放。

当：

```text
当前 Reducer 看起来可能也能处理 Margin/Short
```

但没有正式产品证明：

> Fail Closed。

当：

```text
未来扩市场方便
```

与：

```text
现在创建 Capability DSL/Plugin Registry
```

冲突：

> 保持最小 typed pure resolver。

---

# 110. P4.1 的最终定义

P4.1 不是：

> “把 `GENERIC_T0_CASH` 改成 `GENERIC_T0_CASH | CN_A_SHARE_CASH`。”

也不是：

> “删除一个 if。”

P4.1 真正完成的是：

> **把 Execution Product Permission 从 Market Identity 中剥离，建立一套独立、纯函数式、Fail-Closed、可审计的 Durable Execution Support Authority；它只根据已经冻结的经济语义、Position Shape、Reservation Shape 和当前 Kernel 实现能力作出唯一判定。**

P4.1 之后必须形成：

```text
Market
    ↓
Compiled Rules
    ↓
Trade Application Instruction
    ↓
Immutable Planning Authority
    ↓
Execution Support Context
    ↓
Single Capability Resolver
    ↓
Support Decision
    ↓
Canonical Planner
    ↓
Prepared Transaction
```

而绝不能继续：

```text
Market Profile Name
    ↓
Permission
```

最终必须满足：

```text
Identity is evidence, not permission.

Capability is semantic, not product-named.

Resolver is the sole support authority.

Planner does not re-authorize.

Unknown semantic shapes fail closed.

Implemented economic shapes are reusable across markets.

Unsupported features remain explicitly unsupported.

No compatibility layer preserves the old authority model.
```

只有这些原则真正进入：

```text
类型
调用链
Planner
Processor
Facts
Tests
Architecture Guards
Recovery
Documentation
```

P4.1 才算真正完成。

完成 P4.1 后：

> **冻结 Execution Support Authority。后续 P4 不再通过增加 Market Profile 白名单扩展 Execution，而只通过“实现一种新的经济交易语义 → 完成 Conformance → 扩大 Capability Matrix”来增加能力。**
