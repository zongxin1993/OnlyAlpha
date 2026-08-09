# Codex Prompt — P4.2 Durable Broker-Driven Order Lifecycle Closure

## 任务名称

**P4.2 — Durable Broker-Driven Order Lifecycle Closure**

中文：

**P4.2：Broker 驱动订单生命周期 Durable 语义闭环**

目标仓库：

```text
https://github.com/zongxin1993/OnlyAlpha
```

规划基线：

```text
8ec5359470de3b7853a78e63c1a6fb88d9e227dd
Feat: Durable Execution Capability Semantic Authority Closure
```

---

# 0. 开始前要求

开始实施前，必须重新读取最新 `master`。

不要假定上述 commit 仍然是最新实现。

如果 `master` 已前进：

1. 以最新 `master` 为唯一事实基线；
2. 重新审计本 Prompt 涉及的所有模块；
3. 已经正确完成的内容不得重复实现；
4. 已删除的旧接口不得为了套 Prompt 而恢复；
5. 如果最新代码已有比本 Prompt 更合理的设计，保留更合理方案；
6. 但不得违反本 Prompt 定义的 First Principles 和 Architecture Invariants；
7. 最终 Implementation Report 必须记录：

   * Prompt baseline；
   * actual implementation baseline；
   * baseline differences；
   * 哪些问题已提前解决；
   * 哪些实现因最新代码结构而调整。

---

# 1. P4.2 的根本问题

P4.1 已经解决：

```text
“What economic execution shape
is allowed into the Durable Kernel?”
```

形成：

```text
Immutable Semantic Context
        ↓
Execution Capability Resolver
        ↓
Single Support Decision
```

这部分 Authority 原则上应冻结。

P4.2 不重新设计 Execution Capability。

P4.2 要解决另一个问题：

> **Broker 已经产生一个订单生命周期事实以后，OnlyAlpha 如何保证这个事实影响的所有本地经济 Authority 都通过同一个 Durable Transaction Protocol 原子、显式、可恢复地提交？**

当前系统仍存在：

```text
Broker TRADE
    → Durable Transaction

Broker SELL CLOSE Terminal
    → Durable Transaction

Broker BUY OPEN Terminal
    → Direct multi-manager mutation

Broker ACCEPTED
    → Direct multi-manager mutation
```

同时还存在更深层问题：

```text
POSITION_RESERVATION Projection
        ↓
Projection Target
        ↓
PositionReservationManager.release()
        ↓
implicitly mutates:
    Position
    Allocation
    Position Reservation
```

即：

```text
Declared Projection Authority
!=
Actual Mutable Authority
```

P4.2 必须从根本上消除这些不一致。

---

# 2. P4.2 的最终目标

Broker 驱动的正式订单生命周期：

```text
ACCEPTED

TRADE / PARTIAL TRADE

CANCELLED

REJECTED

EXPIRED
```

对于 OnlyAlpha 当前正式支持的：

```text
CASH
LIMIT
LONG
NETTING
NO MARGIN

BUY OPEN
SELL CLOSE
```

全部必须成为：

```text
Normalized Broker Fact
        ↓
Stable Operation Identity
        ↓
Immutable Before Authority Capture
        ↓
Execution Support Decision
        ↓
Pure Planner
        ↓
Explicit Projections
        ↓
Prepared Runtime Transaction
        ↓
Durable Commit
        ↓
Ordered Projection
        ↓
Forward Recovery
```

正式支持范围内，不得存在第二套 direct mutation protocol。

---

# 3. 第一性原则

所有实现必须服从以下原则。

## 3.1 Broker Fact 一旦影响多个经济 Authority，就必须 Transactional

如果一个 Broker Update 同时改变：

```text
Order
Position
Allocation
Account
Strategy Ledger
Reservation
Risk
```

中的两个或以上 Authority，

不得：

```python
manager_a.change()
manager_b.change()
manager_c.change()
```

然后依靠异常补偿。

必须：

```text
Capture
→ Plan
→ Prepare
→ Commit
→ Project
```

---

# 4. One Domain → One Write Authority

每种 Domain State 必须拥有唯一 mutation authority。

例如：

```text
ORDER
POSITION
ALLOCATION
ACCOUNT
STRATEGY_LEDGER
ACCOUNT_CASH_RESERVATION
STRATEGY_CASH_RESERVATION
POSITION_RESERVATION
RISK_RESERVATION
RISK
```

每一个 Projection 都必须明确对应一个 Authority。

禁止：

```text
POSITION_RESERVATION Projection
    secretly changes Position
```

禁止：

```text
ACCOUNT_CASH_RESERVATION Projection
    secretly recalculates unrelated Ledger state
```

---

# 5. One Projection Component → One Mutable Authority

P4.2 必须冻结：

> **一个 Projection Target 只能安装自己声明的 Component Authority。**

例如：

```text
POSITION_RESERVATION Projection Target
```

只能：

```text
validate current Position Reservation
restore after Position Reservation
verify final state/hash
```

不得调用：

```text
release()
consume()
acknowledged()
reserve()
```

这种带业务 orchestration side effect 的 command API。

---

# 6. Planner calculates; Projection Target installs

正确模型：

```text
Planner
    calculates before → after

Projection
    declares before → after

Projection Target
    verifies precondition
    installs exact after
    verifies result
```

禁止：

```text
Projection Target
    recalculates business semantics
```

禁止：

```text
Projection Target
    coordinates another Manager
```

禁止：

```text
Projection Target
    executes hidden lifecycle transition
```

---

# 7. Forward Recovery Only

如果：

```text
Transaction STORED
```

后：

```text
projection 1 success
projection 2 success
projection 3 crash
```

恢复必须：

```text
read committed transaction
verify existing projections
resume projection 3+
```

不做：

```text
rollback projection 1
rollback projection 2
```

不要引入跨 Manager rollback framework。

---

# 8. P4.2 只处理 Broker → OnlyAlpha

本阶段是：

```text
Broker-driven lifecycle
```

即：

```text
Broker Accepted
Broker Trade
Broker Cancelled
Broker Rejected
Broker Expired
```

明确不处理：

```text
OnlyAlpha → Broker
```

例如：

```text
Order Intent
Local Reserve
submit_order()
cancel_order()
Broker command retry
Broker idempotency key
```

Command Side durability 属于未来 P7。

不要把两个阶段混合。

---

# 9. Pre-Implementation Audit

任何代码修改前先完成代码级审计。

重点文件至少包括：

```text
src/onlyalpha/execution/capability.py
src/onlyalpha/execution/support.py
src/onlyalpha/execution/processor.py

src/onlyalpha/execution/trade_planner.py
src/onlyalpha/execution/terminal_planner.py
src/onlyalpha/execution/planning_context.py

src/onlyalpha/execution/execution_state.py
src/onlyalpha/execution/projection_targets.py
src/onlyalpha/execution/economic_invariants.py

src/onlyalpha/execution/terminal_identity.py
src/onlyalpha/execution/terminal_fact.py
src/onlyalpha/execution/committed.py

src/onlyalpha/order/execution/processor.py
src/onlyalpha/order/manager.py
src/onlyalpha/order/cash_port.py
src/onlyalpha/order/position_port.py

src/onlyalpha/position/reservations.py
src/onlyalpha/position/manager.py
src/onlyalpha/position/allocation_manager.py

src/onlyalpha/account/manager.py
src/onlyalpha/strategy_ledger/manager.py

src/onlyalpha/risk/service.py
src/onlyalpha/risk/reservations.py

src/onlyalpha/transaction/enums.py
src/onlyalpha/transaction/projection.py
src/onlyalpha/transaction/coordinator.py
src/onlyalpha/transaction/persistence_ports.py
```

同时检查所有：

```text
tests/execution/
tests/transaction/
tests/recovery/
tests/integration/
tests/architecture/
```

---

# 10. 全仓搜索

必须搜索至少：

```text
_accepted

_terminal_order

acknowledged(

release(

OnlyBrokerOrderAcceptedUpdate

OnlyBrokerOrderCancelledUpdate
OnlyBrokerOrderRejectedUpdate
OnlyBrokerOrderExpiredUpdate

OnlyGatewayOrderAcceptedUpdate

ORDER_TERMINAL
TRADE_FILL

PositionReservationExecutionProjection

OnlyPositionReservationExecutionProjectionTarget

execution_support_schema_version
schema_version
ONLY_EXECUTION_SUPPORT_POLICY_VERSION

replay_non_transaction

coordinate_reservations
```

---

# 11. Pre-Implementation Audit Report

新增：

```text
docs/reports/
p4_2_broker_driven_order_lifecycle_pre_implementation_audit.md
```

必须明确列出每个 Broker lifecycle fact：

```text
ACCEPTED
TRADE
CANCELLED
REJECTED
EXPIRED
```

实际修改哪些 Authority。

建议生成矩阵：

```text
                  BUY OPEN          SELL CLOSE

ACCEPTED          ...
TRADE             ...
CANCELLED         ...
REJECTED          ...
EXPIRED           ...
```

并进一步区分：

```text
before Broker ACK

after Broker ACK

after Partial Fill
```

不能靠猜测。

必须从现有 Manager semantics 推导。

---

# 12. Audit 必须找出所有 Hidden Mutation

重点检查：

```text
Manager.command()
```

调用是否会偷偷修改其它 Manager。

例如当前：

```text
PositionReservationManager.release()
```

是否同时改变：

```text
Position
Allocation
Reservation
```

以及：

```text
acknowledged()
consume()
```

类似行为。

全部必须记录。

---

# 13. P4.2 Architecture Decision

新增 ADR，例如：

```text
docs/adr/
00xx-durable-broker-driven-order-lifecycle.md
```

必须冻结以下不变量：

```text
1. Broker-driven economic lifecycle facts are durable.
2. One Projection Component mutates exactly one Authority.
3. Projection Targets install; they do not orchestrate.
4. Planners calculate complete economic transitions.
5. Supported lifecycle shapes have no direct mutation fallback.
6. Unsupported economic shapes fail closed.
7. Recovery is forward-only.
8. Broker command durability is outside P4.2.
```

---

# 14. Execution Support Version Authority 必须先修正

P4.1 当前概念上存在：

```text
ONLY_EXECUTION_SUPPORT_POLICY_VERSION
```

但 Decision / Fact 使用：

```text
schema_version
execution_support_schema_version
```

这混淆了：

```text
data structure version
```

和：

```text
capability policy version
```

必须修正。

---

# 15. Policy Version ≠ Schema Version

最终：

```python
OnlyExecutionSupportDecision:
    policy_version: str
```

不要：

```python
schema_version
```

Committed Fact：

```text
execution_support_policy_version
```

Fact 本身：

```text
schema_version
```

继续表达 serialized Fact schema。

必须明确：

```text
Execution Support Policy Version
!=
Fact Schema Version
```

---

# 16. 不保留旧名字 alias

删除：

```text
execution_support_schema_version
```

如果它实际表达的是 Policy Version。

不要：

```python
@property
def execution_support_schema_version(...):
    return execution_support_policy_version
```

不要兼容 alias。

这是 Alpha 项目内部 Authority correction。

直接迁移。

---

# 17. Execution Support Policy v2

P4.2 完成正式能力实现以后，Support Policy 升级。

概念上：

```text
Policy v1

TRADE_FILL:
    BUY OPEN     DURABLE
    SELL CLOSE   DURABLE

ORDER_TERMINAL:
    SELL CLOSE   DURABLE
    BUY OPEN     UNSUPPORTED
```

P4.2：

```text
Policy v2

ORDER_ACCEPTED:
    BUY OPEN     DURABLE
    SELL CLOSE   DURABLE

TRADE_FILL:
    BUY OPEN     DURABLE
    SELL CLOSE   DURABLE

ORDER_TERMINAL:
    BUY OPEN     DURABLE
    SELL CLOSE   DURABLE
```

不能只改 capability 返回值却仍称 v1。

---

# 18. 增加 ORDER_ACCEPTED Operation Kind

建议：

```python
OnlyRuntimeOperationKind.ORDER_ACCEPTED
```

不要把 Accepted 混入：

```text
ORDER_TERMINAL
```

也不要建立过于模糊的：

```text
ORDER_LIFECYCLE
```

不同 Operation 应拥有明确事实语义。

---

# 19. 增加 Accepted Capability

建议：

```python
OnlyExecutionCapability.DURABLE_ORDER_ACCEPTED
```

最终：

```text
DURABLE_ORDER_ACCEPTED
DURABLE_TRADE
DURABLE_TERMINAL
UNSUPPORTED
```

命名根据项目现有风格调整，但必须明确。

---

# 20. Capability Resolver 仍然是唯一 Authority

P4.2 不能破坏 P4.1。

禁止：

```text
Accepted Planner 自己判断 support
Terminal Planner 自己判断 support
Processor 自己 hardcode BUY/SELL support
```

必须：

```text
Support Context
        ↓
Resolver
        ↓
Frozen Decision
        ↓
Planner
```

---

# 21. 不允许 Capability Resolver 看 Market Profile

继续禁止：

```text
GENERIC_T0_CASH
CN_A_SHARE_CASH
market_profile_id
market name
venue
```

决定 lifecycle durability。

P4.2 是 Broker lifecycle closure，不是市场白名单阶段。

---

# 22. Accepted Stable Identity

新增稳定 Accepted Fact Identity。

建议类似：

```text
OnlyExecutionOrderAcceptedAuthority
```

包含：

```text
accepted_identity
payload_fingerprint
venue_order_id
```

Identity 可以使用：

```text
EACK-<sha256>
```

具体 prefix 可根据项目命名规范决定。

---

# 23. Accepted Identity 输入

至少考虑：

```text
runtime_id
gateway_id
account_id
order_id
broker_update_id
accepted operation semantic
```

不能使用：

```text
processing_sequence
current wall clock
mutable local state
```

作为身份组成。

---

# 24. Payload Fingerprint

必须基于完整 normalized：

```text
OnlyBrokerOrderAcceptedUpdate
```

canonical payload 计算。

Same identity + different payload：

```text
→ conflict
```

不能：

```text
last write wins
```

---

# 25. 不为每一种 Broker 生命周期增加 Query API

不要继续无限扩：

```text
get_by_accepted_identity()
get_by_cancelled_identity()
get_by_rejected_identity()
get_by_expired_identity()
```

Accepted 如果：

```text
transaction_id == accepted_identity
```

优先直接：

```text
get_by_transaction_id()
```

---

# 26. 顺手审计 Terminal-specific Query

当前：

```text
get_by_terminal_identity()
```

如果唯一用途只是：

```text
transaction_id == terminal_identity
```

则评估迁移到：

```text
get_by_transaction_id()
```

然后删除专用接口。

如果它有真实额外索引/业务查询职责，则保留。

不要为了“清理”强删有价值接口。

---

# 27. Accepted Planning Context

新增一个不可变：

```text
OnlyOrderAcceptedExecutionPlanningContext
```

建议包含：

```text
update

accepted_authority

prepared_at
engine_id
processing_sequence

position_scope

support_decision

order_before

position_before
    optional

position_reservation_before
    optional

account_cash_reservation_before
    optional

strategy_cash_reservation_before
    optional
```

最终字段必须基于实际 Authority audit。

---

# 28. Planning Context 只能包含 Frozen Before Authority

不能包含：

```text
Manager
Service
Registry
Broker
mutable callback
```

Planner 必须 side-effect-free。

---

# 29. Accepted Planner

新增：

```text
OnlyOrderAcceptedExecutionTransactionPlanner
```

职责只有：

```text
validate immutable context

calculate Order After

calculate changed Reservation After

calculate changed Position After

build projections

build fact

build preconditions

build events

return Prepared Runtime Transaction
```

---

# 30. Accepted Planner 禁止调用 Manager

禁止：

```python
order_manager.apply_accepted()
position_reservation.acknowledged()
position.release()
```

Planner 只能操作 immutable execution state。

---

# 31. BUY OPEN Accepted

必须首先审计当前 cash reservation ACK semantics。

如果 BUY OPEN Accepted 实际只改变：

```text
ORDER
```

那么只投影：

```text
ORDER
```

如果 Strategy Cash Reservation 的 stage 会从：

```text
SENT
→ ACKNOWLEDGED
```

则显式增加：

```text
STRATEGY_CASH_RESERVATION
```

如果 Account Cash Reservation 也有实际 Authority Change：

显式投影。

禁止创建“为了结构对称而没有真实变化”的 Projection。

原则：

> **No economic change → no Projection.**

---

# 32. SELL CLOSE Accepted

当前重点语义通常是：

```text
Order:
SUBMITTED → ACCEPTED

Position Reservation:
SENT_TO_BROKER
→ BROKER_ACKNOWLEDGED

Position:
remove local duplicate broker freeze
```

因此正常可能为：

```text
1 ORDER
2 POSITION
3 POSITION_RESERVATION
```

实际以 audit 为准。

---

# 33. Accepted 时不要错误释放 Allocation Hold

SELL CLOSE 的 Cluster Allocation hold 必须继续防止：

```text
多个 Cluster 共享 Account 时超卖
```

Broker ACK 通常只意味着：

```text
Account-level duplicate Position freeze
```

可以释放，

但：

```text
Cluster Allocation hold
```

还必须保留到：

```text
Fill consume
```

或者：

```text
Terminal release
```

不要在 Accepted 时误释放。

---

# 34. Terminal Planner 必须真正泛化

当前：

```text
OnlyTerminalExecutionTransactionPlanner
```

不能再是：

```text
Cash-Long SELL CLOSE-only
```

P4.2 后必须支持：

```text
BUY OPEN terminal
SELL CLOSE terminal
```

但不要创建：

```text
OnlyBuyTerminalPlanner
OnlySellTerminalPlanner
OnlyAshareTerminalPlanner
```

使用同一个 semantic planner。

---

# 35. Terminal 由 Authority Shape 决定 Projections

Planner 可以根据：

```text
BUY OPEN / SELL CLOSE
Reservation Shape
Reservation Stage
Partial Fill State
```

选择明确的 Projection Set。

不要根据：

```text
Market Profile
```

决定。

---

# 36. BUY OPEN Terminal 的真正 Authority

Terminal：

```text
CANCELLED
REJECTED
EXPIRED
```

会释放尚未消费的资金 Reservation。

因此不仅是：

```text
ACCOUNT_CASH_RESERVATION
STRATEGY_CASH_RESERVATION
```

还会改变 aggregate：

```text
ACCOUNT
STRATEGY_LEDGER
```

以及：

```text
RISK_RESERVATION
RISK
ORDER
```

---

# 37. BUY OPEN Terminal 推荐 Projection Set

正式全量场景：

```text
1 ORDER

2 ACCOUNT

3 STRATEGY_LEDGER

4 ACCOUNT_CASH_RESERVATION

5 STRATEGY_CASH_RESERVATION

6 RISK_RESERVATION

7 RISK
```

具体 ProjectionOrder 使用项目 canonical ordering，不要人为硬用上述数字。

---

# 38. BUY OPEN Terminal Invariants

必须验证：

```text
Order remaining quantity unchanged by terminal fact itself

Order filled quantity unchanged

Previously committed fills preserved

Account reservation remaining → 0

Strategy reservation remaining → 0

Account reserved cash decreases exactly by release delta

Strategy cash_reserved decreases exactly

Cash available increases exactly

Risk remaining quantity/notional → 0

Risk active order count -1

No cash created

No fee changed by pure terminal fact
```

---

# 39. SELL CLOSE Terminal 必须修正 Hidden Authority

现有：

```text
POSITION_RESERVATION projection
```

不能再通过：

```text
PositionReservationManager.release()
```

偷偷修改：

```text
Position
Allocation
```

必须显式拆开。

---

# 40. SELL CLOSE Terminal Before ACK

例如：

```text
SUBMITTED
Position Reservation stage = SENT_TO_BROKER
```

此时可能仍有：

```text
Position hold
Allocation hold
```

Terminal：

```text
REJECTED / CANCELLED
```

应显式产生：

```text
ORDER

POSITION

ALLOCATION

POSITION_RESERVATION

RISK_RESERVATION

RISK
```

每一个都有独立：

```text
before
after
expected version
expected hash
result version
result hash
```

---

# 41. SELL CLOSE Terminal After ACK

如果：

```text
Position Reservation stage
= BROKER_ACKNOWLEDGED
```

Position duplicate freeze 已被 Accepted transaction 消除。

Terminal 通常只需：

```text
ORDER

ALLOCATION

POSITION_RESERVATION

RISK_RESERVATION

RISK
```

不能再次释放 Position。

---

# 42. SELL CLOSE Partial Fill + Terminal

例如：

```text
SELL 1000

Fill 300

Cancel remaining 700
```

必须保持：

```text
300 filled economic facts
```

完全不可逆。

只释放：

```text
remaining Allocation hold 700

remaining Position Reservation 700

remaining Risk 700
```

不能：

```text
release original 1000
```

不能影响已经成交 300。

---

# 43. BUY OPEN Partial Fill + Terminal

例如：

```text
BUY 1000

Fill 300

Cancel 700
```

此前 300 已形成：

```text
Position
Allocation
Fee
Account cash consumption
Strategy cash consumption
Settlement
```

Terminal 只能释放：

```text
remaining cash reservation
remaining strategy cash reservation
remaining risk
```

不能回退：

```text
300 fill
```

---

# 44. Reject Before ACK

必须支持：

```text
SUBMITTED
→ REJECTED
```

这是正常 Broker lifecycle。

不能要求：

```text
必须先 ACCEPTED
```

才能 Terminal。

---

# 45. Expire / Cancel Transition

根据当前 Order state machine，分别验证允许的：

```text
SUBMITTED
ACCEPTED
PARTIALLY_FILLED
PENDING_CANCEL
```

等状态。

不要为了 P4.2 擅自扩大 Order State Machine。

---

# 46. Pure Reducers

为避免 Manager command path 和 Planner 各自实现一套 lifecycle 算法，建议抽取最小 pure reducers。

例如：

```text
only_reduce_order_accepted

only_reduce_position_reservation_acknowledged

only_reduce_position_hold_acknowledged

only_reduce_cash_reservation_terminal

only_reduce_strategy_cash_reservation_terminal

only_reduce_position_reservation_terminal

only_reduce_risk_reservation_terminal

only_reduce_terminal_risk_snapshot
```

具体拆分根据现有代码语义。

---

# 47. Reducer 的输入输出

输入：

```text
immutable before state
normalized broker fact
timestamp
```

输出：

```text
immutable after state
```

禁止 Reducer：

```text
access Manager
publish Event
write persistence
call another Reducer through hidden side effects
```

---

# 48. Manager 应复用 Reducer，而不是重复算法

如果 Direct command API 仍有其它合法用途：

```text
Manager.command()
```

内部应使用同一 pure reducer。

不要：

```text
Planner one implementation
Manager another implementation
```

---

# 49. 不构建 Generic Reducer Framework

禁止：

```text
ReducerRegistry
GenericLifecycleStateMachine
Dynamic Reducer Plugin
```

当前只需要抽出真实重复的 economic transition。

保持简单、typed、明确。

---

# 50. Projection Target Purity Closure

重点修改：

```text
OnlyPositionReservationExecutionProjectionTarget
```

删除：

```python
self._manager.release(...)
```

类似 hidden command。

Target 应只：

```text
current = get()

_prepare(current)

restore_execution_authority(after)

_complete(...)
```

---

# 51. 全仓检查所有 Projection Target

不是只修 Position Reservation。

检查：

```text
ORDER
POSITION
ALLOCATION
SETTLEMENT
FEE
ACCOUNT
LEDGER
ALL RESERVATIONS
RISK
```

是否调用会产生其它 Domain side effect 的业务 command。

发现后按同一原则修。

---

# 52. Architecture Guard

增加 source-level architecture tests：

> Projection Target 不允许调用 orchestration lifecycle methods。

至少重点禁止：

```text
.release(
.acknowledged(
.consume(
.reserve(
```

但 guard 要准确，不能误伤纯 storage restore API。

推荐允许：

```text
restore_*
install_*
validate_*
get*
require*
```

具体按代码命名做精确检查。

---

# 53. Projection Target 不应该 Publish Event

Events 必须在：

```text
Planner
→ Prepared Transaction Outbox
```

阶段形成。

Target 只负责安装 committed projections。

---

# 54. Accepted Fact

建议新增：

```text
OnlyCommittedOrderAcceptedFact
```

或符合项目命名规范的等价 Domain Fact。

包含：

```text
operation identity
accepted payload fingerprint

runtime
gateway
account
cluster
instrument
order

venue_order_id

broker_update_id
source_sequence
processing_sequence

support capability
support policy version
support fingerprint

timestamps
```

---

# 55. Terminal Fact 不要无限增加 nullable 字段

现有 Terminal Fact 偏 SELL CLOSE。

P4.2 扩 BUY OPEN 时，不要形成：

```text
position_* optional
cash_* optional
account_* optional
ledger_* optional
...
```

无限膨胀。

Fact 应表达：

```text
发生了什么业务事实
```

Projection 表达：

```text
哪些 Authority 如何变化
```

---

# 56. Terminal Fact 可以保留最小经济摘要

例如：

```text
terminal_status
terminal_reason

filled_quantity_before
remaining_quantity

release_shape
```

甚至：

```text
economic_release_kind:
    CASH_RESERVATION
    POSITION_RESERVATION
```

如果确有审计价值。

详细 Authority before/after 已由 Projections 保存。

---

# 57. 不重复存完整 Projection Data

不要让 Fact 又重复保存：

```text
account before
account after
ledger before
ledger after
reservation before
reservation after
...
```

避免 Fact schema 与 Projection schema 双重增长。

---

# 58. Accepted Projection Type

Order Accepted 不应该滥用：

```text
OnlyOrderTerminalExecutionProjection
```

建议新增明确：

```text
OnlyOrderAcceptedExecutionProjection
```

或者更通用但准确的：

```text
OnlyOrderLifecycleExecutionProjection
```

是否通用化取决于是否能真正表达 Accepted/Terminal 且不丢失类型安全。

优先类型清晰。

---

# 59. Projection Component 不需要新 ORDER_ACCEPTED Component

`OnlyRuntimeProjectionComponent.ORDER`

仍然表示：

```text
Order Authority
```

Accepted/Trade/Terminal 的差异属于 Projection type / Fact / Operation Kind。

不要创建：

```text
ORDER_ACCEPTED_COMPONENT
ORDER_TERMINAL_COMPONENT
```

Component 是 Authority，不是事件类型。

---

# 60. Projection Ordering

继续复用当前：

```text
OnlyRuntimeProjectionOrder
```

canonical order。

如果新 lifecycle 需要：

```text
ORDER
POSITION
ALLOCATION
ACCOUNT
LEDGER
RESERVATIONS
RISK
```

按整个 Runtime 现有 canonical projection ordering 执行。

不要每个 Planner 自己发明 ordering。

---

# 61. Preconditions 必须覆盖所有实际修改 Authority

这是 P4.2 最重要的验收点之一。

如果 Terminal 实际修改：

```text
Order
Allocation
Position Reservation
Risk Reservation
Risk
```

则 Prepared Transaction 必须包含这五个 Entity 的：

```text
expected_version
expected_state_hash
```

不能有第六个 hidden mutation。

---

# 62. Economic Invariant Validator 必须扩展

当前：

```text
OnlyPreparedExecutionEconomicInvariantValidator
```

需要支持：

```text
ORDER_ACCEPTED
```

以及新的：

```text
BUY OPEN ORDER_TERMINAL
```

但不要将 lifecycle planning 逻辑再复制到 invariant validator。

Validator 只验证：

```text
projection set consistency
value conservation
cross-authority equality
no underflow
no authority creation
```

---

# 63. Accepted Economic Invariants

至少：

```text
Order quantity unchanged
Fill authority unchanged
Fee unchanged
Risk quantity unchanged

Position quantity unchanged

SELL CLOSE:
Position order freeze decreases only by exact ACK delta
Allocation hold unchanged
Position Reservation stage advances
```

根据现有真实语义补充。

---

# 64. Terminal Economic Invariants

至少：

```text
terminal cannot create Fill

terminal cannot change cumulative fill

remaining reservation release <= remaining authority

released + consumed + remaining
= original reservation

cash release cannot create cash

risk active order count decrements exactly once

partial committed fill remains immutable

no negative Position/Allocation freeze

no negative cash reservation
```

---

# 65. Processor Cutover

当前 Processor：

```text
_prepared_trade

_prepared_terminal

_accepted

_terminal_order
```

P4.2 后应形成：

```text
_prepared_accepted

_prepared_trade

_prepared_terminal
```

共同使用：

```text
_coordinate_prepared_operation()
```

---

# 66. 正式 supported lifecycle 不再进入 `_dispatch` mutation

Broker：

```text
Accepted
Trade
Cancelled
Rejected
Expired
```

在正式 supported shape 下，都应该在进入 legacy/direct `_dispatch` 之前完成 durable routing。

---

# 67. 删除 `_accepted()` direct mutation path

如果 P4.2 已覆盖正式支持范围：

```python
def _accepted(...)
```

不再有真实职责：

直接删除。

不要保留：

```text
legacy accepted
generic accepted
fallback accepted
```

---

# 68. 删除 `_terminal_order()` direct economic fallback

P4.2 后：

```text
BUY OPEN
SELL CLOSE
```

Terminal 全 Durable。

其它 unsupported shape：

```text
FAIL CLOSED
```

不要：

```text
unsupported by capability
→ direct terminal mutation anyway
```

这是双 Authority。

如果 `_terminal_order()` 无其它合法非-economic用途：

删除函数。

---

# 69. 不保留 compatibility fallback

禁止：

```python
try:
    durable()
except Unsupported:
    direct_mutation()
```

禁止：

```text
legacy_terminal
old_terminal
terminal_v1
```

禁止 feature flag 双路径。

---

# 70. Unsupported 必须 Fail Closed

例如：

```text
Margin

Short

Hedging

unsupported Account type

unsupported Order type
```

收到 Broker lifecycle update 时：

不能进入 Direct mutation。

应：

```text
UNSUPPORTED
→ rejected/reconciliation/fail closed
```

根据现有 Processor contract选择准确行为。

---

# 71. Recovery Classification

当前：

```text
replay_non_transaction()
```

需要重新定义。

P4.2 后：

```text
Broker Accepted
Trade
Cancelled
Rejected
Expired
```

都属于 Durable Transaction Facts。

全部不得走：

```text
replay_non_transaction()
```

---

# 72. Durable Operation Deduplication

Accepted：

```text
Stable accepted identity
+
payload fingerprint
```

Terminal：

继续：

```text
stable terminal identity
+
payload fingerprint
```

Trade：

继续：

```text
fill identity
+
payload fingerprint
```

统一原则：

```text
same identity + same payload
→ duplicate/idempotent

same identity + different payload
→ conflict
```

---

# 73. Recovery 不重新授权历史事实

已经 stored/committed：

```text
ORDER_ACCEPTED
TRADE_FILL
ORDER_TERMINAL
```

恢复时不能使用当前最新：

```text
Execution Support Policy
```

重新判断历史操作“今天还支不支持”。

历史 Committed Fact 已经是 Authority。

Support Policy 用于：

```text
new operation admission
```

而不是：

```text
historical fact revalidation
```

---

# 74. Recovery Crash Windows

至少测试：

### Accepted

```text
prepared
→ stored
→ crash
```

恢复后 projections 完成。

```text
ORDER applied
→ crash before POSITION
```

恢复继续剩余 Projection。

---

# 75. Terminal Crash Windows

至少：

```text
stored
→ crash before any projection

ORDER projected
→ crash

ACCOUNT projected
→ crash

reservation projected
→ crash

RISK projected
→ ready
```

分别针对 BUY OPEN / SELL CLOSE 适用 Projection Set。

---

# 76. Recovery 必须保持 Projection Idempotency

已经安装的 Projection：

```text
current == result state
```

恢复：

```text
RECOVER / IDEMPOTENT
```

而不是再次执行业务 command。

这也是为什么 Target 不能调用：

```text
release()
```

这种相对 mutation。

必须安装：

```text
absolute committed after authority
```

---

# 77. Broker Accepted → Trade

Canonical scenario：

```text
SUBMITTED
↓
ACCEPTED
↓
PARTIALLY_FILLED
↓
FILLED
```

Memory/SQLite 均必须通过。

---

# 78. Trade Without Explicit Accepted

必须审计 Broker normalized contract 是否可能：

```text
SUBMITTED
↓
TRADE
```

如果允许：

当前 Durable Trade path 必须继续支持。

不能在 P4.2 无依据增加：

```text
TRADE requires ACCEPTED first
```

---

# 79. Terminal Before Accepted

必须测试：

```text
SUBMITTED
↓
REJECTED
```

以及当前允许时：

```text
SUBMITTED
↓
CANCELLED
```

确保未 ACK reservation 正确释放。

---

# 80. Terminal After Accepted

测试：

```text
SUBMITTED
↓
ACCEPTED
↓
CANCELLED
```

确保：

```text
already released ACK-related Position freeze
```

不会重复释放。

---

# 81. Partial Fill + Terminal

BUY：

```text
BUY 1000
Accepted
Fill 300
Cancel 700
```

SELL：

```text
SELL 1000
Accepted
Fill 300
Cancel 700
```

必须分别验证每个 Authority。

---

# 82. Cancel / Reject / Expire 必须分别测试

不要只测试 Cancel 然后假设其它 Terminal 相同。

分别：

```text
CANCELLED
REJECTED
EXPIRED
```

测试：

```text
Order status
timestamp
reason
Risk release reason
identity/fingerprint
events
```

---

# 83. Account / Strategy Ledger Parity

BUY OPEN terminal：

```text
Account cash release
```

和：

```text
Strategy Ledger cash release
```

必须保持 parity。

任何一侧不一致：

```text
fail closed
```

不要“修一边”。

---

# 84. Risk

每一个 terminal transaction：

```text
Risk Reservation
Risk Snapshot
```

必须显式同时投影。

保证：

```text
active_order_count
cluster_active_order_count
reserved_quantity
reserved_notional
remaining_order_notional
```

准确变化。

---

# 85. Position / Allocation Authority

SELL CLOSE lifecycle 必须明确区分：

```text
Account-level Position availability/freeze
```

和：

```text
Cluster-level Allocation hold
```

不要因为两者都表示“冻结数量”而合并。

它们解决的是不同 Authority scope。

---

# 86. 不修改 A-share 规则

P4.2 是 market-neutral Execution lifecycle closure。

禁止增加：

```text
if CN_A_SHARE_CASH
```

禁止修改：

```text
A-share T+1
price limit
board lot
fee pack
reference provider
```

除非代码审计证明存在一个真正通用的 Execution API 缺口。

---

# 87. 不做 Production A-share E2E

P4.2 完成后只是：

```text
Broker-driven lifecycle canonical durability
```

下一阶段才是：

```text
CN A-share Durable Product Conformance
```

不要提前混合。

---

# 88. 不修改 Fee Kernel

Terminal 不产生新的 Trade Fee。

不要重构：

```text
Fee Resolver
Fee Engine
Fee Reconciliation
Broker Fee Contract
Market Fee Pack
```

---

# 89. 不做 Broker Command Durability

明确禁止实现：

```text
Durable submit command
Durable cancel command
Broker retry
Broker idempotency token
ACK correlation command log
```

属于 P7。

---

# 90. Architecture Guards

至少新增以下 guards。

## Guard A

Production lifecycle Planner 不允许 import Market Profile identity。

---

## Guard B

Projection Targets 不允许调用会跨 Authority 的 orchestration command。

---

## Guard C

Trade / Accepted / Terminal Planner 不允许访问 Manager。

---

## Guard D

正式 Broker lifecycle shape 不允许调用 direct `_accepted()` / `_terminal_order()`。

---

## Guard E

不允许旧：

```text
execution_support_schema_version
```

重新出现。

---

## Guard F

不允许：

```text
legacy lifecycle
fallback terminal
compatibility accepted
```

类似生产接口。

---

# 91. Unit Tests — Reducers

每个 pure reducer 测：

```text
valid transition

invalid stage

wrong scope

underflow

duplicate/repeated transition

partial quantity

exact remaining release
```

---

# 92. Unit Tests — Accepted Planner

BUY OPEN：

```text
SUBMITTED → ACCEPTED
```

SELL CLOSE：

```text
SUBMITTED → ACCEPTED
```

检查：

```text
Projection set exactly correct
No hidden Authority
Fact correct
Events deterministic
Preconditions complete
```

---

# 93. Unit Tests — Terminal Planner

至少：

```text
BUY OPEN / Cancel
BUY OPEN / Reject
BUY OPEN / Expire

SELL CLOSE before ACK / Reject
SELL CLOSE after ACK / Cancel
SELL CLOSE partial / Cancel
SELL CLOSE partial / Expire
```

---

# 94. Exact Projection Set Tests

测试不能只：

```text
assert transaction succeeded
```

必须验证：

```text
tuple(projection.component)
```

精确等于预期。

这是防止 hidden mutation 重新出现的关键。

---

# 95. Projection Target Tests

重点证明：

```text
apply POSITION_RESERVATION projection
```

不会修改：

```text
Position
Allocation
```

除非 transaction 中另有对应 projections。

可在测试中 snapshot before/after unrelated managers。

---

# 96. Atomicity Tests

故意制造：

```text
POSITION projection conflict
```

Transaction 不能在 Planner 阶段直接修改任何 Manager。

如果 Store 未成功：

```text
no mutation
```

如果 Store 成功、Projection 后失败：

```text
forward recovery
```

能够最终到 committed after state。

---

# 97. Duplicate Tests

Accepted：

```text
same update replay twice
→ one economic transition
```

Terminal：

```text
same update replay twice
→ one release
```

不能出现：

```text
cash released twice
risk active order count -2
allocation hold underflow
```

---

# 98. Payload Conflict Tests

同一：

```text
accepted_identity
```

不同 payload：

```text
conflict
```

同一：

```text
terminal_identity
```

不同 payload：

```text
conflict
```

不能 silent ignore。

---

# 99. Persistence Tests

Memory 和 SQLite 都必须：

```text
commit
query
restart
recovery
idempotency
conflict
```

一致。

---

# 100. A→B→C Recovery

至少建立一条复杂 Broker lifecycle：

```text
Engine A

BUY OPEN
Accepted
Partial Fill
checkpoint/crash

Engine B

recover
remaining Fill
Cancel another order
crash

Engine C

recover
```

以及 SELL CLOSE 生命周期。

最终与 uninterrupted baseline 对比。

---

# 101. Recovery Equality

至少比较：

```text
Orders

Positions

Allocations

Account

Strategy Ledger

Cash Reservations

Position Reservations

Risk Reservations

Risk Snapshot

Transaction records

Applied Projection ledger

Outbox

Execution sequence

Artifacts if relevant
```

---

# 102. Events

Accepted / Terminal events 必须来自：

```text
Prepared Transaction outbox
```

不再依赖 direct event buffer 先 mutation 后 publish。

事件必须：

```text
stable identity
deterministic sequence
deterministic payload
```

---

# 103. Event Replay

Recovery：

```text
rehydrate_existing
```

不能重复产生外部事件。

继续遵循现有 outbox delivery semantics。

---

# 104. Processor Cleanup

P4.2 完成后重新审查 `processor.py`。

删除：

```text
dead helper
obsolete branch
legacy direct lifecycle path
duplicate capability routing
historical comments
```

不要保留：

```text
“old path kept for now”
```

Git 是历史。

源码不是历史博物馆。

---

# 105. OrderUpdateProcessor Boundary

当前：

```text
OnlyOrderUpdateProcessor
```

同时支持：

```text
coordinate_reservations=True
```

并在 Accepted/Terminal 中协调 Reservation。

P4.2 后必须重新定义这个类的边界。

对于 Durable Broker lifecycle：

不得再作为跨 Authority orchestrator 使用。

---

# 106. 如果 `coordinate_reservations` 已无合理职责

直接删除：

```text
coordinate_reservations
```

以及：

```text
risk_service
position_reservations
cash_reservations
```

这些依赖，如果它们只服务旧 orchestration path。

不要因为其它测试还调用旧接口就保留。

修改调用者。

---

# 107. 如果 OrderUpdateProcessor 仍用于非-Durable本地路径

则必须收窄职责：

```text
Order state transition only
```

不要继续拥有：

```text
Risk
Position Reservation
Cash Reservation
```

write authority。

---

# 108. Ports Cleanup

重新审计：

```text
OnlyOrderCashReservationPort
OnlyOrderPositionReservationPort
```

中的：

```text
acknowledged()
release()
```

如果这些接口存在只是为了让 Order Update Processor 跨 Domain orchestration：

P4.2 后删除无用接口。

如果它们还有其它真实 command-side职责：

保留最小必要部分。

---

# 109. Clean Code Requirement

最终不允许：

```text
deprecated
compat
legacy
old
v1 fallback
temporary
TODO remove later
```

作为旧 Authority path 留在生产代码。

无职责接口直接删除。

---

# 110. Module Boundary

推荐最终边界：

```text
execution/
    capability.py
        support admission only

    support.py
        immutable support projection

    accepted_identity.py
        Accepted stable identity

    terminal_identity.py
        Terminal stable identity

    planning_context.py
        immutable before-authority

    accepted_planner.py
        Accepted pure planner

    trade_planner.py
        Trade pure planner

    terminal_planner.py
        Terminal pure planner

    lifecycle_reducers.py
        only if shared reducers justify a file

    projection_targets.py
        install committed authority only

    processor.py
        orchestration/routing only
```

不要机械照抄文件名。

目标是职责清晰。

---

# 111. Processor 的理想职责

Processor 最终只负责：

```text
validate normalized Broker Update

deduplicate / sequence

resolve Position Scope

capture semantic support

capture immutable planning authority

route to Planner

coordinate Prepared Transaction

translate result
```

不应该自己：

```text
calculate cash release

calculate Position freeze

calculate Risk release

mutate Order Manager
```

---

# 112. Planner 的理想职责

Planner：

```text
before authority
+
broker fact
+
support decision
→
complete after authority
```

纯函数。

---

# 113. Manager 的理想职责

Manager：

```text
own current mutable state
```

提供：

```text
query
restore committed authority
local command operations when appropriate
```

但不能在 Projection Target 中被用作跨 Authority orchestration工具。

---

# 114. Projection Target 的理想职责

```text
current state
+
committed projection
→
validate
→
install exact after state
```

只有这个职责。

---

# 115. Transaction 的理想职责

Transaction 必须完整声明：

```text
Every mutable Authority
that this Broker Fact changes
```

少一个都不接受。

---

# 116. Documentation

更新：

```text
README.md
docs/roadmap.md
相关 ADR
```

必须准确声明：

```text
P4.1
Execution Support Authority complete

P4.2
Broker-driven order lifecycle durable
```

不要继续写：

```text
BUY OPEN terminal direct
```

等旧事实。

---

# 117. Implementation Report

新增：

```text
docs/reports/
p4_2_durable_broker_driven_order_lifecycle_closure.md
```

至少包含：

```text
Baseline

Root Cause

Before Architecture

Hidden Mutation Audit

Policy Version Correction

ORDER_ACCEPTED Architecture

Accepted Fact / Identity

Terminal Genericization

BUY OPEN Terminal

SELL CLOSE Terminal

Partial Fill + Terminal

Projection Purity

Deleted Interfaces

Recovery

Architecture Guards

Test Matrix

Quality Gates

Explicit Non-Scope

Next Phase
```

---

# 118. Deleted Interfaces 单独列出

必须明确报告哪些接口被删除。

至少审计：

```text
direct _accepted

direct _terminal_order

coordinate_reservations

Order Update Processor Reservation dependencies

Position Reservation Projection Target release orchestration

execution_support_schema_version

legacy lifecycle wrapper

terminal-specific query if redundant
```

---

# 119. Commit Plan

推荐：

## Commit 1

```text
Docs: Freeze Broker-Driven Lifecycle Authority
```

Audit + ADR。

---

## Commit 2

```text
Refactor: Separate Execution Policy Version from Schema Version
```

完成：

```text
policy_version
Fact fields
tests
```

---

## Commit 3

```text
Refactor: Make Projection Targets Authority-Pure
```

移除跨 Authority hidden side effects。

增加 architecture tests。

---

## Commit 4

```text
Feat: Add Durable Order Accepted Operation
```

包括：

```text
operation kind
identity
fact
context
planner
projection support
recovery
```

---

## Commit 5

```text
Feat: Close Cash-Long Durable Terminal Lifecycle
```

包括：

```text
BUY OPEN terminal
SELL CLOSE explicit authority
partial terminal
```

---

## Commit 6

```text
Refactor: Remove Direct Broker Lifecycle Mutation
```

删除：

```text
_accepted
_terminal_order
obsolete coordination APIs
```

---

## Commit 7

```text
Test: Freeze Durable Broker Lifecycle Semantics
```

完整 unit/integration/recovery/architecture tests。

---

## Commit 8

```text
Docs: Close P4.2 Durable Broker Lifecycle
```

Report + roadmap。

实际 commit 数量可调整，但每个 commit 必须概念完整且 tests green。

---

# 120. Static Gates

使用当前仓库正式命令。

至少：

```bash
uv sync --frozen --all-packages --all-groups

uv run ruff check src tests examples packages scripts

uv run ruff format --check src tests examples packages scripts

uv run mypy src/onlyalpha
```

以及当前正式 provider mypy gates。

---

# 121. Test Gates

至少执行：

```bash
uv run python scripts/test_suite.py fast

uv run python scripts/test_suite.py integration

uv run python scripts/test_suite.py core-full

uv run python scripts/test_suite.py recovery

uv run python scripts/test_suite.py ashare

uv run python scripts/test_suite.py miniqmt-contract

uv run python scripts/test_suite.py exhaustive
```

如果最新 master 已调整 lane：

以最新正式 CI 为准。

---

# 122. Build

必须：

```bash
uv build --all-packages
```

PASS。

---

# 123. GitHub Remote Gate

本地 PASS 不等于结束。

必须确认最新 commit 的：

```text
Layered Quality / final quality gate
```

全部绿色。

若远端失败：

必须分析根因。

不能：

```text
skip
xfail
loosen assertion
```

绕过。

---

# 124. 禁止通过测试的方法

绝对禁止：

```text
skip failing lifecycle tests

xfail recovery

保留 direct fallback

try durable then fallback direct

mock away Manager side effects

只验证最终状态、不验证 Projection set

删除旧 recovery tests

降低 state hash checks

把 Projection conflict 改成 warning

Accepted 继续 replay_non_transaction

用 compatibility alias 保留旧 API
```

---

# 125. Definition of Done — Authority

* [ ] Broker ACCEPTED 是正式 Durable operation。
* [ ] Broker TRADE 保持 Durable。
* [ ] Broker CANCELLED 是 Durable。
* [ ] Broker REJECTED 是 Durable。
* [ ] Broker EXPIRED 是 Durable。
* [ ] Resolver 仍是唯一 capability Authority。
* [ ] Planner 不重新授权。
* [ ] Processor 不拥有 economic transition algorithm。

---

# 126. Definition of Done — Projection Purity

* [ ] One Projection Component → One Mutable Authority。
* [ ] Position Reservation Projection 不隐式修改 Position。
* [ ] Position Reservation Projection 不隐式修改 Allocation。
* [ ] 其它 Projection Targets 也无隐藏跨 Domain side effect。
* [ ] Projection Target 不调用 lifecycle orchestration command。
* [ ] 所有实际 mutation 都有显式 Projection。
* [ ] 所有实际 mutation 都有 precondition/hash。

---

# 127. Definition of Done — Accepted

* [ ] `ORDER_ACCEPTED` operation kind 存在。
* [ ] Accepted stable identity 存在。
* [ ] Accepted payload fingerprint 存在。
* [ ] Accepted committed fact 存在。
* [ ] BUY OPEN Accepted Durable。
* [ ] SELL CLOSE Accepted Durable。
* [ ] SELL CLOSE ACK-related Position freeze 正确释放。
* [ ] Allocation hold 不被错误释放。
* [ ] Accepted 支持 duplicate/idempotency。
* [ ] Accepted 支持 forward recovery。

---

# 128. Definition of Done — BUY OPEN Terminal

* [ ] Cancel Durable。
* [ ] Reject Durable。
* [ ] Expire Durable。
* [ ] Account cash reservation release 显式。
* [ ] Strategy cash reservation release 显式。
* [ ] Account aggregate cash state 显式。
* [ ] Strategy Ledger aggregate cash state 显式。
* [ ] Risk Reservation 显式。
* [ ] Risk Snapshot 显式。
* [ ] Partial Fill 后只释放 remaining authority。

---

# 129. Definition of Done — SELL CLOSE Terminal

* [ ] Reject before ACK Durable。
* [ ] Cancel after ACK Durable。
* [ ] Expire Durable。
* [ ] Position change显式投影（需要时）。
* [ ] Allocation release显式投影（需要时）。
* [ ] Position Reservation release显式。
* [ ] Risk Reservation release显式。
* [ ] Risk Snapshot显式。
* [ ] Partial Fill 后 committed fill 不受影响。
* [ ] 不重复释放已在 Accepted 阶段释放的 Position freeze。

---

# 130. Definition of Done — Direct Paths

* [ ] 正式 lifecycle 不使用 `_accepted()` direct mutation。
* [ ] 正式 lifecycle 不使用 `_terminal_order()` direct mutation。
* [ ] 无 legacy fallback。
* [ ] Unsupported semantic shape Fail Closed。
* [ ] 不保留废弃 compatibility API。

---

# 131. Definition of Done — Version Authority

* [ ] Execution Support 使用 `policy_version`。
* [ ] Fact 使用 `execution_support_policy_version`。
* [ ] Fact `schema_version` 与 Policy Version 概念明确分离。
* [ ] P4.2 capability evolution 正确升版。
* [ ] 无旧 `execution_support_schema_version` alias。

---

# 132. Definition of Done — Recovery

* [ ] Accepted stored-before-project recovery。
* [ ] Accepted mid-projection recovery。
* [ ] Terminal stored-before-project recovery。
* [ ] Terminal mid-projection recovery。
* [ ] Duplicate replay idempotent。
* [ ] Same identity different payload conflict。
* [ ] Memory PASS。
* [ ] SQLite PASS。
* [ ] A→B→C restart PASS。
* [ ] uninterrupted / recovered final authority identical。

---

# 133. Definition of Done — Clean Architecture

最终代码中不得出现：

```text
Projection Target doing business orchestration

Planner accessing Managers

Market-profile lifecycle branch

direct economic fallback

duplicate support authority

compatibility wrapper for removed interfaces

dead historical implementation
```

---

# 134. P4.2 明确非目标

Implementation Report 必须明确：

```text
NOT IMPLEMENTED IN P4.2
```

至少：

```text
CN A-share Production Product Conformance

A-share production-date full dataset

A-share T+1 E2E product certification

Paper Streaming Recovery

Live Runtime

Durable Broker Outbound Command

Broker command retry / idempotency

Broker state synchronization product

Margin execution

Short execution

Hedging execution

Futures product

Crypto product

Market Product Composition Neutralization

Multi-account

Multi-broker

Vectorized Backtest
```

---

# 135. P4.2 后下一阶段

P4.2 完成后，应直接进入：

```text
P4.3
CN A-Share Durable Product Conformance
```

目标是：

```text
Production Reference
+
Production Market Rules
+
Production Market Fee
+
Explicit Broker Contract
+
Durable Broker Lifecycle
+
T+1 Settlement
+
Partial/Multi Fill
+
Terminal
+
Memory/SQLite Recovery
```

形成第一个真实市场完整产品证明。

---

# 136. 最终工程原则

当：

```text
Broker Fact
```

会改变多个 Authority：

> 必须 Transactional。

当：

```text
Projection Component 名称
```

与：

```text
实际修改的 Authority
```

不一致：

> 拆成显式 Projections。

当：

```text
Projection Target
```

与：

```text
Business Orchestration
```

发生职责冲突：

> Planner 计算，Target 安装。

当：

```text
旧 direct path
```

与：

```text
Canonical Durable path
```

并存：

> 删除旧 direct path。

当：

```text
Unsupported shape
```

与：

```text
方便直接 mutation
```

冲突：

> Fail Closed。

当：

```text
历史兼容
```

与：

```text
Single Authority
```

冲突：

> 修改调用者，删除旧接口。

当：

```text
一个 Manager command
```

偷偷修改其它 Domain：

> 不得从 Projection Target 调用。

当：

```text
Policy Version
```

与：

```text
Schema Version
```

混淆：

> 明确拆开。

当：

```text
Stored transaction
```

部分 Projection 已执行后 crash：

> Forward Recovery，不 rollback。

---

# 137. P4.2 最终定义

P4.2 不是：

> “让 BUY OPEN cancel 也走 terminal planner。”

P4.2 也不是：

> “增加一个 ORDER_ACCEPTED enum。”

P4.2 真正要完成的是：

> **把所有 Broker 驱动、会改变正式订单经济生命周期的事实统一纳入 Canonical Durable Transaction Protocol，同时彻底消除 Projection Target 中未声明的跨 Authority side effect，使 Transaction 声明的 Projections 与实际 mutable authority 一一对应。**

完成后必须形成：

```text
                Broker
                  │
        ┌─────────┼─────────┐
        │         │         │
     ACCEPTED    TRADE    TERMINAL
        │         │         │
        ▼         ▼         ▼
   Stable Fact Identity / Fingerprint
                  │
                  ▼
       Immutable Authority Capture
                  │
                  ▼
       Execution Support Decision
                  │
                  ▼
             Pure Planner
                  │
                  ▼
         Explicit Projections
                  │
                  ▼
       Prepared Runtime Transaction
                  │
                  ▼
            Durable Store
                  │
                  ▼
        Ordered Projection Apply
                  │
                  ▼
            Forward Recovery
```

并严格满足：

```text
One Domain → One Write Authority

One Projection → One Mutable Authority

Planner Calculates

Projection Target Installs

Broker Lifecycle Facts Are Durable

Unsupported Shapes Fail Closed

No Direct Economic Fallback

No Hidden Manager Side Effects

No Obsolete Compatibility Interfaces
```

只有当这些原则同时落实到：

```text
types
planners
facts
projection targets
processor routing
recovery
tests
architecture guards
documentation
```

P4.2 才算完成。

完成后冻结：

> **Broker-driven Order Lifecycle Authority**

后续任何新的 Broker-driven economic lifecycle 能力，都必须通过：

```text
Define Semantic Shape
→ Implement Pure Transition
→ Add Explicit Projections
→ Add Recovery
→ Add Conformance
→ Open Capability
```

扩展。

绝不允许重新增加：

```text
direct Manager mutation fallback
```

或：

```text
product-specific lifecycle branch
```
