# OnlyAlpha PR4.2.2b：Post-Recovery Authority Validation 与 Recovery Finalization Hardening

## 一、任务背景

请基于 OnlyAlpha 当前 `master` 分支的真实源码、测试、ADR、README 和 Roadmap，完成：

```text
PR4.2.2b
Post-Recovery Authority Validator
+
Recovery Finalizer
+
Checkpoint Durable Read-Back Verification
+
Recovery Finalization Failure Cleanup
```

开始工作前必须重新读取当前仓库，不得只依赖本提示词中的描述。

当前预期基线最新提交为：

```text
fa74bdbc1038e5bb5dd6a4edc06395405a11faeb
Feat: Recovery Phase State Machine 与 Exact Replay Boundary
```

如果实际 `master` 已更新，以实际代码为准，并在预实现审计中说明差异。

PR4.2.2a 已建立：

```text
Execution Recovery Phase
→ Persisted Tail Resolution
→ Same-Bar Continuation Transaction
→ Exact Backtest Recovery Boundary
→ Boundary Completion Callback
```

PR4.2.2b 不再修改 4.2.2a 的因果重放算法，而是解决：

```text
Recovery Replay Completed
不等于
Runtime Authority 已完整、自洽、稳定持久化并可重新开放运行
```

当前 Runtime 恢复收尾大致为：

```text
Orchestrator recover
→ Cluster complete_recovery_all()
→ Runtime 私有浅层 Authority Validation
→ 创建 Post-Recovery Checkpoint
```

该实现仍存在以下问题：

1. Post-Recovery Validation 只检查少量事务、队列和进度字段；
2. Validation 逻辑直接位于 Backtest Runtime；
3. Cluster 在 Validation 前已进入 `RECOVERED`；
4. `fail_recovery_all()` 主要只处理 `RECOVERING`；
5. Post-Recovery Checkpoint 写入后没有 read-back verify；
6. SQLite Commit 成功但调用层抛异常时，没有明确的 fail-closed 语义；
7. Validation、Checkpoint、Cluster Lifecycle 和失败清理缺少统一 Finalizer。

本任务必须把恢复收尾升级为：

```text
Recovery Outcome
→ Cluster RECOVERY_FINALIZING
→ Recovery Completion Callback
→ Runtime Quiescence Check
→ Complete Authority Validation
→ Immutable Checkpoint Capture
→ Durable Checkpoint Write
→ Read-Back Verification
→ Cluster RECOVERED
→ Runtime READY
```

任何步骤失败必须：

```text
Runtime FAILED
Cluster FAILED
No Outbox Delivery
No Cluster Resume
No Runtime RUNNING
```

---

# 二、任务范围

本任务必须完成：

1. 正式 `OnlyRuntimeRecoveryOutcome`；
2. 独立 Post-Recovery Authority Validator；
3. 稳定 Validation Check、Report 和 Fingerprint；
4. Transaction Authority 校验；
5. Outbox Authority 校验；
6. Recovery Projection Range 校验；
7. Position / Allocation 校验；
8. Order / Reservation 校验；
9. Account / Strategy Ledger 校验；
10. Fee / Settlement / Margin 校验；
11. Broker / Local Order 基础一致性校验；
12. Runtime Boundary、Cursor、Result Progress 和 Queue 校验；
13. `RECOVERY_FINALIZING` Cluster 生命周期；
14. 独立 `OnlyRuntimeRecoveryFinalizer`；
15. Checkpoint Service 的 Capture / Write / Verify 拆分；
16. Post-Recovery Checkpoint Durable Read-Back Verification；
17. Checkpoint After-Commit Exception 处理；
18. Validation、Capture、Write、Verify 失败时的统一清理；
19. Engine A → B → C 真实连续重启故障矩阵；
20. ADR、README、Roadmap 和 Recovery 文档更新。

---

# 三、明确不在本任务范围内

本任务不得实现：

* Unified Recovery Event Gate；
* 所有 Direct Event Publisher 迁移；
* 历史 Direct Event 完整抑制；
* Exactly-once Outbox；
* Partial / Multi-Fill Transaction；
* SELL / CLOSE Transaction；
* Futures / Margin 正式 Transaction；
* Non-Trade Durable Transaction；
* Paper Runtime Recovery；
* Live Runtime Recovery；
* Full Broker Reconciliation；
* Schema Migration；
* Distributed Checkpoint；
* Remote Persistence Store；
* Web Recovery 控制面。

这些属于后续 PR4.2.2c 或更后续阶段。

---

# 四、开始前必须审计的当前实现

重点阅读：

```text
src/onlyalpha/runtime/backtest/runtime.py
src/onlyalpha/runtime/recovery/orchestrator.py
src/onlyalpha/runtime/backtest/recovery_boundary.py
src/onlyalpha/runtime/backtest/recovery_replay.py

src/onlyalpha/runtime/checkpoint/service.py
src/onlyalpha/runtime/checkpoint/model.py
src/onlyalpha/runtime/checkpoint/codec.py
src/onlyalpha/runtime/checkpoint/registry.py

src/onlyalpha/runtime/persistence/store.py

src/onlyalpha/cluster/manager.py
src/onlyalpha/cluster/base.py

src/onlyalpha/runtime/reconciliation.py
src/onlyalpha/execution/invariants.py
src/onlyalpha/execution/applied_projection.py
src/onlyalpha/execution/persistence_ports.py

src/onlyalpha/order/
src/onlyalpha/account/
src/onlyalpha/position/
src/onlyalpha/strategy_ledger/
src/onlyalpha/fee/
src/onlyalpha/settlement/
src/onlyalpha/margin/

src/onlyalpha/event/bus.py
src/onlyalpha/runtime/runtime.py
```

重点搜索：

```bash
rg "_validate_post_recovery_authority"
rg "complete_recovery_all"
rg "fail_recovery_all"
rg "RECOVERED"
rg "RECOVERING"
rg "OnlyRuntimeCheckpointService"
rg "write_checkpoint"
rg "latest_checkpoint"
rg "pending_outbox"
rg "OnlyRuntimeLedgerReconciliationService"
rg "OnlyExecutionInvariant"
rg "OnlyInMemoryAppliedProjectionLedger"
rg "processed_bar_count"
rg "last_market_processing_sequence"
rg "processing_sequence"
rg "event_bus.drain"
rg "outbox_records"
rg "query_orders"
rg "list_open"
```

---

# 五、预实现审计文档

先新增：

```text
docs/reports/pr4_2_2b_recovery_finalization_pre_implementation_audit.md
```

审计必须回答：

1. 当前 `_recover_runtime()` 的完整调用顺序；
2. 当前 Cluster 在哪个调用点从 `RECOVERING` 进入 `RECOVERED`；
3. 当前 Validation 失败后 Cluster 处于什么状态；
4. 当前 Checkpoint Capture、Seal、Write 的实际顺序；
5. 当前 Checkpoint Store 是否可能出现 Commit 成功后 Wrapper 抛异常；
6. 当前 Checkpoint Header 可用于 Read-Back Verify 的字段；
7. 当前 Runtime 中所有恢复后 Authority Manager；
8. 每个 Manager 已有的公开只读 Query、Snapshot 或 Reconciliation API；
9. 哪些 Manager 缺少 Validator 所需的最小只读 View；
10. 当前 `OnlyRuntimeLedgerReconciliationService` 的能力和调用方式；
11. 当前 Execution Invariant 能检查哪些 Account、Position、Ledger 关系；
12. 当前 Position Reconciliation 能检查哪些关系；
13. 当前 Applied Projection Ledger 的生命周期和权威边界；
14. 为什么 Applied Projection Ledger 不能作为持久业务真相；
15. 当前 Outbox Query 能否读取全部状态和 Event Identity；
16. 当前 Virtual Broker / Broker Query 能提供哪些 Order 状态；
17. 当前 Result Progress 字段和 MarketData Processor Sequence 的实际语义；
18. 当前 EventBus 是否有公开 pending count；
19. `on_recovery_complete()` 是否可能修改状态或发布内部事件；
20. 当前 Runtime 在何处投递 Pending Outbox；
21. 当前 Runtime 在何处 Resume Recovered Cluster；
22. 哪些测试已覆盖 Recovery Finalization；
23. 哪些故障窗口完全没有测试；
24. 本任务应删除哪些 Runtime 私有逻辑；
25. 本任务不能触碰哪些 4.2.2a 接口。

审计完成前不得修改生产代码。

---

# 六、核心架构原则

## 6.1 Orchestrator、Validator、Finalizer 职责必须分离

固定职责：

```text
Orchestrator
    Load / Validate Checkpoint
    Restore Participants
    Build Recovery Plan
    Execute Causal Replay
    Produce Recovery Outcome

Validator
    Read-only inspect Runtime Authority
    Produce deterministic Validation Report

Finalizer
    Coordinate Cluster callback
    Quiescence
    Validation
    Checkpoint capture/write/verify
    Failure cleanup
```

不得让：

* Orchestrator 写 Post-Recovery Checkpoint；
* Validator 修改 Manager；
* Finalizer重新实现业务公式；
* Backtest Runtime继续持有具体 Authority 校验规则。

## 6.2 Validator 只能依赖只读接口

Validator 不得直接访问：

```text
manager._records
manager._positions
manager._orders
manager._reservations
runtime._services.xxx._private_container
```

如果现有 Query 不足，新增最小只读 Snapshot/View Port。

## 6.3 Validator 不得成为第二套业务系统

Validator 必须复用：

```text
OnlyRuntimeLedgerReconciliationService
Execution Invariant Checker
Position Reconciliation
Manager Query / Snapshot
Store Transaction Query
Outbox Query
```

不得在 Validator 中重新实现：

* PnL 计算；
* Fee Resolver；
* Margin Formula；
* Settlement Reducer；
* Position Reducer；
* Account Reducer；
* Risk Decision。

## 6.4 Fail Closed

以下任一异常都必须阻止 READY：

```text
Cluster callback failure
Quiescence failure
Authority validation failure
Checkpoint capture failure
Checkpoint write failure
Checkpoint read-back failure
After-commit exception
```

不得将这些错误降级为 Warning。

## 6.5 Applied Projection Ledger 不是持久真相

`OnlyInMemoryAppliedProjectionLedger` 只是可丢弃的 Projection Application Acceleration Index。

唯一持久事务权威仍是 Runtime Persistence Store。

不得：

* 新增 SQLite Applied Projection Ledger；
* 要求新 Engine 的 Applied Ledger 覆盖全部 Checkpoint 前历史；
* 用 Applied Ledger 决定交易是否存在。

首版只验证：

```text
本次 Recovery Tail
+
本次 Recovery Continuation
```

对应的 Applied Projection Range。

---

# 七、Recovery Outcome

## 7.1 新增模型

建议新增：

```text
src/onlyalpha/runtime/recovery/outcome.py
```

```python
@dataclass(frozen=True, slots=True)
class OnlyRuntimeRecoveryOutcome:
    restored_checkpoint: OnlyRuntimeCheckpoint
    diagnostic: OnlyRuntimeRecoveryDiagnostic

    persisted_tail_start_sequence: int | None
    persisted_tail_end_sequence: int | None

    continuation_start_sequence: int | None
    continuation_end_sequence: int | None

    final_boundary: OnlyBacktestRecoveryBoundary | None
    replay_performed: bool
```

必须满足：

```text
persisted tail empty
→ start/end 都为 None

continuation empty
→ start/end 都为 None

replay_performed == True
→ final_boundary 必须存在

replay_performed == False
→ final_boundary 可以为 None
```

## 7.2 Orchestrator 返回值

将：

```python
recover() -> OnlyRuntimeRecoveryDiagnostic | None
```

调整为：

```python
recover() -> OnlyRuntimeRecoveryOutcome | None
```

Diagnostic 仍保留，用于 Operational Diagnostics。

Orchestrator 返回前必须确认：

```text
Execution Tail Resolved
Exact Replay Boundary Completed when replay occurred
Final Ready Sequence known
```

Orchestrator 不做完整 Authority Validation。

---

# 八、Cluster Recovery Finalization 状态

## 8.1 新增状态

在 `OnlyClusterState` 增加：

```python
RECOVERY_FINALIZING = "RECOVERY_FINALIZING"
```

状态转换：

```text
INITIALIZED
→ RECOVERING
→ RECOVERY_FINALIZING
→ RECOVERED
→ RUNNING
```

## 8.2 拆分当前完成接口

当前 `complete_recovery_all()` 同时：

```text
调用 on_recovery_complete()
→ 转为 RECOVERED
```

必须拆开。

新增：

```python
def begin_recovery_finalization_all(self) -> None:
    ...
```

行为：

```text
RECOVERING
→ RECOVERY_FINALIZING
→ 调用 on_recovery_complete()
```

Callback 成功后仍保持：

```text
RECOVERY_FINALIZING
```

新增：

```python
def mark_recovered_all(self) -> None:
    ...
```

行为：

```text
RECOVERY_FINALIZING
→ RECOVERED
```

只有 Validator 和 Checkpoint Verify 都通过后才调用。

## 8.3 失败清理

新增：

```python
def fail_recovery_finalization_all(
    self,
    error: Exception,
) -> None:
    ...
```

必须处理：

```text
RECOVERING
RECOVERY_FINALIZING
RECOVERED
```

失败后：

```text
Cluster FAILED
执行 Cleanup
不得 Resume
保留原始异常
```

删除或重构旧的：

```python
complete_recovery_all()
fail_recovery_all()
```

不保留弱兼容 Wrapper。

---

# 九、Recovery Finalization 状态机

新增：

```text
src/onlyalpha/runtime/recovery/finalizer.py
```

```python
class OnlyRuntimeRecoveryFinalizationPhase(StrEnum):
    CREATED = "CREATED"
    CLUSTER_COMPLETION = "CLUSTER_COMPLETION"
    QUIESCENCE_CHECK = "QUIESCENCE_CHECK"
    AUTHORITY_VALIDATION = "AUTHORITY_VALIDATION"
    CHECKPOINT_CAPTURE = "CHECKPOINT_CAPTURE"
    CHECKPOINT_WRITE = "CHECKPOINT_WRITE"
    CHECKPOINT_VERIFY = "CHECKPOINT_VERIFY"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
```

Finalizer 内部只能单向转换。

禁止：

* 从 FAILED 恢复；
* 重复 finalize；
* 跳过 Validation；
* 跳过 Verify；
* Verify 前进入 RECOVERED。

---

# 十、Validation 数据模型

建议新增：

```text
src/onlyalpha/runtime/recovery/validation.py
```

或拆分为：

```text
validation_models.py
authority_validator.py
```

不要为了文件数量机械拆分。

## 10.1 Status

```python
class OnlyPostRecoveryCheckStatus(StrEnum):
    PASSED = "PASSED"
    FAILED = "FAILED"
    NOT_APPLICABLE = "NOT_APPLICABLE"
```

## 10.2 Check

```python
@dataclass(frozen=True, slots=True)
class OnlyPostRecoveryValidationCheck:
    code: str
    status: OnlyPostRecoveryCheckStatus
    scope: str
    expected: str | None
    actual: str | None
    detail: str
```

要求：

* `code` 非空；
* `scope` 非空；
* Check Identity 为 `code + scope`；
* Identity 不得重复；
* 字段必须可稳定序列化。

## 10.3 Report

```python
@dataclass(frozen=True, slots=True)
class OnlyPostRecoveryValidationReport:
    runtime_id: OnlyRuntimeId
    checks: tuple[OnlyPostRecoveryValidationCheck, ...]
    authority_fingerprint: str

    @property
    def passed(self) -> bool:
        ...
```

要求：

```text
checks
→ 按 code + scope 规范化排序
→ 计算稳定 SHA-256 fingerprint
```

Report 属于 Operational Diagnostic，不得进入：

```text
Canonical Business Projection
Business Fingerprint
交易结果等价比较
```

---

# 十一、Validation Context

禁止将整个 `OnlyRuntimeServices` 直接交给 Validator。

建议：

```python
@dataclass(frozen=True, slots=True)
class OnlyPostRecoveryValidationContext:
    runtime_id: OnlyRuntimeId
    outcome: OnlyRuntimeRecoveryOutcome

    transaction_query: OnlyExecutionTransactionQueryPort
    ready_transaction_query: OnlyProjectionReadyExecutionQueryPort
    outbox_query: OnlyExecutionTransactionOutboxQueryPort

    order_view: OnlyOrderAuthorityView
    position_view: OnlyPositionAuthorityView
    allocation_view: OnlyAllocationAuthorityView

    account_view: OnlyAccountAuthorityView
    strategy_ledger_view: OnlyStrategyLedgerAuthorityView

    account_reservation_view: OnlyAccountReservationAuthorityView
    position_reservation_view: OnlyPositionReservationAuthorityView
    margin_reservation_view: OnlyMarginReservationAuthorityView
    risk_reservation_view: OnlyRiskReservationAuthorityView

    fee_view: OnlyFeeAuthorityView
    settlement_view: OnlySettlementAuthorityView
    margin_view: OnlyMarginAuthorityView

    applied_projection_view: OnlyAppliedProjectionAuthorityView
    broker_view: OnlyBrokerRecoveryAuthorityView | None
    runtime_boundary_view: OnlyRuntimeBoundaryAuthorityView
```

根据仓库实际接口调整命名。

---

# 十二、Checker 结构

定义统一协议：

```python
class OnlyPostRecoveryAuthorityCheck(Protocol):
    def evaluate(
        self,
        context: OnlyPostRecoveryValidationContext,
    ) -> tuple[OnlyPostRecoveryValidationCheck, ...]:
        ...
```

总 Validator：

```python
class OnlyPostRecoveryAuthorityValidator:
    def __init__(
        self,
        checks: tuple[OnlyPostRecoveryAuthorityCheck, ...],
    ) -> None:
        ...

    def validate(
        self,
        context: OnlyPostRecoveryValidationContext,
    ) -> OnlyPostRecoveryValidationReport:
        ...
```

Checker 推荐拆分：

```text
OnlyTransactionAuthorityCheck
OnlyOutboxAuthorityCheck
OnlyRecoveredProjectionRangeCheck
OnlyPositionAllocationAuthorityCheck
OnlyOrderReservationAuthorityCheck
OnlyAccountLedgerAuthorityCheck
OnlyFeeSettlementMarginAuthorityCheck
OnlyBrokerLocalParityCheck
OnlyRuntimeBoundaryAuthorityCheck
```

---

# 十三、Transaction Authority Checker

必须检查：

## 13.1 Sequence

```text
actual sequences
=
1..N
```

错误：

```text
POST_RECOVERY_TRANSACTION_SEQUENCE_GAP
```

## 13.2 Projection Ready

所有正式 Transaction：

```text
projection_ready == True
```

错误：

```text
POST_RECOVERY_UNPROJECTED_TRANSACTION
```

## 13.3 Final Head

```text
Store Final Sequence
=
Outcome Diagnostic Final Ready Sequence
```

错误：

```text
POST_RECOVERY_READY_SEQUENCE_MISMATCH
```

## 13.4 Identity 唯一

分别检查：

```text
Transaction ID
Execution Sequence
Broker Update ID
Trade ID
```

错误：

```text
POST_RECOVERY_DUPLICATE_TRANSACTION_ID
POST_RECOVERY_DUPLICATE_BROKER_UPDATE_ID
POST_RECOVERY_DUPLICATE_TRADE_ID
```

## 13.5 Ready Query 一致

```text
Ready Query
=
Store 中所有 Projection Ready Transaction
```

错误：

```text
POST_RECOVERY_READY_QUERY_MISMATCH
```

---

# 十四、Outbox Authority Checker

必须检查：

1. 每个 Outbox Row 引用存在的 Transaction；
2. 对应 Transaction 必须 Projection Ready；
3. Event ID 唯一；
4. Sequence + Event Index 唯一；
5. Idempotency Key 唯一；
6. Continuation Transaction 必须存在 Durable Outbox；
7. Recovery Finalization 前 Continuation Outbox 不得被错误提前发布；
8. Pending Count 与 Store Query 一致。

错误：

```text
POST_RECOVERY_OUTBOX_ORPHAN
POST_RECOVERY_OUTBOX_REFERENCES_UNREADY_TRANSACTION
POST_RECOVERY_DUPLICATE_OUTBOX_EVENT
POST_RECOVERY_CONTINUATION_OUTBOX_MISSING
POST_RECOVERY_CONTINUATION_OUTBOX_PREMATURELY_PUBLISHED
POST_RECOVERY_OUTBOX_PENDING_COUNT_MISMATCH
```

不得在本任务中实现 exactly-once。

---

# 十五、Recovered Projection Range Checker

只检查：

```text
persisted_tail_start_sequence
...
continuation_end_sequence
```

对应的 Projection Application Record。

不得检查：

```text
1
...
restored_checkpoint.covered_execution_sequence
```

因为 Checkpoint Prefix 的 Applied Projection Ledger 可能没有在新 Engine 中完整存在。

对 Recovery Range 中每个 Transaction：

```text
每个 Projection
→ 对应 Applied Projection Record 存在
→ Payload Hash 一致
→ Result State Hash 一致
```

错误：

```text
POST_RECOVERY_APPLIED_PROJECTION_RANGE_MISMATCH
POST_RECOVERY_APPLIED_PROJECTION_HASH_MISMATCH
```

不得把 Applied Ledger 改为持久数据库权威。

---

# 十六、Position / Allocation Checker

必须按完整 Position Scope 校验。

Hedging 模式至少按：

```text
Account
Instrument
Position Side
```

区分。

## 16.1 归约

```text
Position.total_quantity
=
所有对应 Cluster Allocation.total_quantity 之和
```

错误：

```text
POST_RECOVERY_POSITION_ALLOCATION_QUANTITY_MISMATCH
```

## 16.2 内部不变量

检查：

```text
total >= 0
available >= 0
frozen >= 0
available + frozen <= total
```

错误：

```text
POST_RECOVERY_POSITION_QUANTITY_INVARIANT_FAILED
```

## 16.3 悬空关系

禁止：

```text
Allocation exists
but Position missing
```

错误：

```text
POST_RECOVERY_ORPHAN_ALLOCATION
```

优先复用现有 Position Reconciliation。

---

# 十七、Order / Reservation Checker

检查所有 Open Order。

## BUY / OPEN

根据当前正式模型检查：

* Account Cash Reservation；
* Strategy Cash Reservation；
* Risk Reservation；
* Margin Reservation（适用时）。

## SELL / CLOSE

如果当前产品范围不正式支持，可返回 `NOT_APPLICABLE`，但不能伪造通过。

检查：

```text
Active Reservation
→ Existing Non-Terminal Order
→ Same Runtime
→ Same Account
→ Same Cluster
→ Same Instrument
```

金额和数量检查：

```text
original >= 0
consumed >= 0
remaining >= 0
consumed + remaining <= original
```

错误：

```text
POST_RECOVERY_OPEN_ORDER_RESERVATION_MISSING
POST_RECOVERY_ORPHAN_RESERVATION
POST_RECOVERY_RESERVATION_SCOPE_MISMATCH
POST_RECOVERY_RESERVATION_AMOUNT_MISMATCH
```

---

# 十八、Account / Strategy Ledger Checker

必须优先复用：

```text
OnlyRuntimeLedgerReconciliationService
```

验证：

* Initial Capital；
* Cash；
* Frozen Cash；
* Position Market Value；
* Realized PnL；
* Unrealized PnL；
* Net PnL；
* Fees；
* Equity。

不能假设单 Cluster。

Runtime 级归约应使用所有 Strategy Ledger。

错误：

```text
POST_RECOVERY_ACCOUNT_LEDGER_MISMATCH
POST_RECOVERY_ACCOUNT_RESERVATION_MISMATCH
POST_RECOVERY_TRADE_FEE_ATTRIBUTION_MISMATCH
```

Validator 不得重新实现完整 PnL 公式。

---

# 十九、Fee / Settlement / Margin Checker

## 19.1 Fee

每个 Ready Transaction 的权威 Fee Projection 必须对应 Fee Manager Record。

检查：

```text
Trade ID
Fee Record Identity
Fee Currency
Fee Amount
Fee Total
```

错误：

```text
POST_RECOVERY_FEE_RECORD_MISSING
POST_RECOVERY_FEE_TOTAL_MISMATCH
POST_RECOVERY_FEE_SCOPE_MISMATCH
```

## 19.2 Settlement

需要 Settlement 的 Transaction 必须有对应 Instruction / Record。

检查：

* Account；
* Instrument；
* Trading Day；
* Quantity / Cash；
* Settlement State；
* 不存在悬空记录。

错误：

```text
POST_RECOVERY_SETTLEMENT_RECORD_MISSING
POST_RECOVERY_SETTLEMENT_STATE_MISMATCH
POST_RECOVERY_ORPHAN_SETTLEMENT_RECORD
```

## 19.3 Margin

启用 Margin 时检查：

```text
reserved >= 0
occupied >= 0
released >= 0
available >= 0
```

并与 Account Margin 状态归约。

Generic T0 Cash 不适用时返回：

```text
NOT_APPLICABLE
```

错误：

```text
POST_RECOVERY_MARGIN_STATE_MISMATCH
POST_RECOVERY_MARGIN_RESERVATION_MISMATCH
```

---

# 二十、Broker Local Parity Checker

这不是 Full Broker Reconciliation。

不得使用：

```python
isinstance(broker, OnlyVirtualBrokerGateway)
```

应通过标准 Query 或新增能力 Port：

```python
class OnlyBrokerRecoveryAuthorityView(Protocol):
    def open_orders(...) -> tuple[...]: ...
```

检查：

```text
Broker Open Order IDs
=
Local Open Order IDs
```

并比较：

* Status；
* Filled Quantity；
* Remaining Quantity；
* Instrument；
* Side；
* Limit Price；
* Account；
* Broker Sequence（可用时）。

错误：

```text
POST_RECOVERY_BROKER_ORDER_MISMATCH
POST_RECOVERY_BROKER_ORDER_SEQUENCE_BEHIND
```

如果 Checkpointable Backtest Broker 不支持必要 Query，应在装配期 Fail Fast。

---

# 二十一、Runtime Boundary Checker

必须检查：

## 21.1 Queue

```text
Broker Inbound Queue empty
MarketData Inbound Queue empty
```

错误：

```text
POST_RECOVERY_INBOUND_QUEUE_NOT_EMPTY
```

## 21.2 EventBus

```text
EventBus pending count == 0
```

错误：

```text
POST_RECOVERY_EVENT_BUS_NOT_DRAINED
```

这里只验证内部稳定状态，不实现 4.2.2c Event Gate。

## 21.3 Cursor / Boundary

发生 Recovery Replay 时：

```text
Replay Cursor
=
Outcome Final Boundary
```

精确比较：

* Source ID；
* Data Version；
* Update ID；
* Source Sequence；
* Event Time。

错误：

```text
POST_RECOVERY_CURSOR_BOUNDARY_MISMATCH
```

## 21.4 Result Progress

禁止继续比较不同维度：

```text
last_market_processing_sequence
<
processed_bar_count
```

必须拆成：

```text
ResultProgress.processed_bar_count
=
ReplayCursor.processed_bar_count
```

以及：

```text
ResultProgress.last_market_processing_sequence
=
MarketDataProcessor.processing_sequence
```

错误：

```text
POST_RECOVERY_RESULT_COUNT_CURSOR_MISMATCH
POST_RECOVERY_PROCESSING_SEQUENCE_MISMATCH
```

## 21.5 Clock

```text
Runtime Clock >= Final Boundary Event Time
```

错误：

```text
POST_RECOVERY_CLOCK_BEHIND_BOUNDARY
```

---

# 二十二、Checkpoint Service 重构

## 22.1 拆分接口

将当前单体 `create()` 重构为：

```python
class OnlyRuntimeCheckpointService:
    def capture(
        self,
        cursor: OnlyBacktestReplayCursor,
        created_at: OnlyTimestamp,
    ) -> OnlyRuntimeCheckpoint:
        ...

    def write(
        self,
        checkpoint: OnlyRuntimeCheckpoint,
    ) -> None:
        ...

    def verify_durable(
        self,
        expected: OnlyRuntimeCheckpoint,
    ) -> OnlyRuntimeCheckpoint:
        ...

    def create(
        self,
        cursor: OnlyBacktestReplayCursor,
        created_at: OnlyTimestamp,
    ) -> OnlyRuntimeCheckpoint:
        ...

    def create_verified(
        self,
        cursor: OnlyBacktestReplayCursor,
        created_at: OnlyTimestamp,
    ) -> OnlyRuntimeCheckpoint:
        ...
```

实现必须共享同一套 Capture / Write 逻辑。

不得复制两套 Checkpoint 创建代码。

## 22.2 普通 Checkpoint

普通每 Bar Checkpoint 可继续：

```text
capture
→ write
```

避免每 Bar增加一次读回开销。

## 22.3 Post-Recovery Checkpoint

Finalizer 必须：

```text
capture
→ write
→ verify_durable
```

---

# 二十三、Durable Read-Back Verification

`verify_durable(expected)` 必须读取：

```python
latest_checkpoint(runtime_id)
```

并检查：

1. Checkpoint 存在；
2. Checkpoint Contract 验证通过；
3. Runtime ID 相等；
4. Checkpoint Sequence 相等；
5. Covered Execution Sequence 相等；
6. Replay Cursor 完全相等；
7. Config Fingerprint 相等；
8. Participant Registry Fingerprint 相等；
9. Aggregate Payload Hash 相等；
10. Pending Outbox Count 相等；
11. Components 完全相等。

错误：

```text
POST_RECOVERY_CHECKPOINT_NOT_DURABLE
POST_RECOVERY_CHECKPOINT_IDENTITY_MISMATCH
POST_RECOVERY_CHECKPOINT_HASH_MISMATCH
POST_RECOVERY_CHECKPOINT_COMPONENT_MISMATCH
```

不能只比较 Checkpoint Sequence。

---

# 二十四、After-Commit Exception

必须覆盖：

```text
SQLite COMMIT succeeded
→ Store wrapper raises
```

Finalizer 捕获 `write()` 异常后必须查询 Latest Checkpoint。

## Latest 等于 Expected

错误分类：

```text
POST_RECOVERY_CHECKPOINT_COMMITTED_BUT_FINALIZATION_INTERRUPTED
```

当前 Engine 必须：

```text
FAILED
No Outbox Delivery
No READY
No RUNNING
```

但不得删除已提交 Checkpoint。

下一个 Engine 必须能从该 Checkpoint继续。

## Latest 不等于 Expected

错误：

```text
POST_RECOVERY_CHECKPOINT_WRITE_FAILED
```

同样 Fail Closed。

不得吞掉 After-Commit Exception 后继续运行。

---

# 二十五、Recovery Finalizer

建议接口：

```python
@dataclass(frozen=True, slots=True)
class OnlyRuntimeRecoveryFinalizationResult:
    outcome: OnlyRuntimeRecoveryOutcome
    validation_report: OnlyPostRecoveryValidationReport
    checkpoint: OnlyRuntimeCheckpoint
```

```python
class OnlyRuntimeRecoveryFinalizer:
    def finalize(
        self,
        outcome: OnlyRuntimeRecoveryOutcome,
    ) -> OnlyRuntimeRecoveryFinalizationResult:
        ...
```

固定顺序：

```text
1. Require Runtime State == RECOVERING

2. Validate Recovery Outcome contract

3. phase = CLUSTER_COMPLETION
   cluster_manager.begin_recovery_finalization_all()

4. Drain internal EventBus

5. phase = QUIESCENCE_CHECK
   require inbound queues empty
   require EventBus empty

6. phase = AUTHORITY_VALIDATION
   report = validator.validate(context)

7. require report.passed

8. phase = CHECKPOINT_CAPTURE
   checkpoint = checkpoint_service.capture(...)

9. phase = CHECKPOINT_WRITE
   checkpoint_service.write(checkpoint)

10. phase = CHECKPOINT_VERIFY
    checkpoint_service.verify_durable(checkpoint)

11. cluster_manager.mark_recovered_all()

12. phase = COMPLETED

13. return FinalizationResult
```

任意失败：

```text
phase = FAILED
cluster_manager.fail_recovery_finalization_all(error)
raise OnlyRuntimeRecoveryFinalizationError
```

Finalizer 不投递 Outbox，不 Resume Cluster。

---

# 二十六、Runtime 接线

将当前 `_recover_runtime()` 收缩为：

```python
def _recover_runtime(self) -> None:
    if not checkpoint_enabled:
        return

    register_cluster_checkpoint_participants()
    bind_participant_registry_fingerprint()

    if latest_checkpoint is None:
        return

    drain_bootstrap_non_transaction_updates()
    cluster_manager.enter_recovery_all()

    try:
        outcome = recovery_orchestrator.recover()
        if outcome is None:
            return

        finalization = recovery_finalizer.finalize(outcome)

    except Exception:
        # 只在 Finalizer 尚未完成清理时兜底，避免双重 cleanup
        raise

    self._runtime_recovery_diagnostics.append(
        finalization.outcome.diagnostic
    )
    self._post_recovery_validation_reports.append(
        finalization.validation_report
    )
    self._clusters_recovered = True
```

删除：

```python
_validate_post_recovery_authority()
```

Runtime 不再知道具体 Authority Check 规则。

只有 Finalizer 成功后，Base Runtime 后续流程才能：

```text
RECOVERING → READY
Deliver Pending Durable Outbox
Resume Recovered Clusters
READY → RUNNING
```

---

# 二十七、错误模型

新增正式错误类型：

```python
class OnlyRuntimeRecoveryFinalizationError(OnlyRuntimeError):
    ...
```

至少保留：

```text
runtime_id
phase
original_error_type
original_error_message
validation_report
expected_checkpoint_sequence
durable_checkpoint_sequence
```

建议错误码：

```text
POST_RECOVERY_TRANSACTION_SEQUENCE_GAP
POST_RECOVERY_UNPROJECTED_TRANSACTION
POST_RECOVERY_READY_SEQUENCE_MISMATCH
POST_RECOVERY_DUPLICATE_TRANSACTION_ID
POST_RECOVERY_DUPLICATE_BROKER_UPDATE_ID
POST_RECOVERY_DUPLICATE_TRADE_ID
POST_RECOVERY_READY_QUERY_MISMATCH

POST_RECOVERY_OUTBOX_ORPHAN
POST_RECOVERY_OUTBOX_REFERENCES_UNREADY_TRANSACTION
POST_RECOVERY_DUPLICATE_OUTBOX_EVENT
POST_RECOVERY_CONTINUATION_OUTBOX_MISSING
POST_RECOVERY_CONTINUATION_OUTBOX_PREMATURELY_PUBLISHED

POST_RECOVERY_APPLIED_PROJECTION_RANGE_MISMATCH
POST_RECOVERY_APPLIED_PROJECTION_HASH_MISMATCH

POST_RECOVERY_POSITION_ALLOCATION_QUANTITY_MISMATCH
POST_RECOVERY_POSITION_QUANTITY_INVARIANT_FAILED
POST_RECOVERY_ORPHAN_ALLOCATION

POST_RECOVERY_OPEN_ORDER_RESERVATION_MISSING
POST_RECOVERY_ORPHAN_RESERVATION
POST_RECOVERY_RESERVATION_SCOPE_MISMATCH
POST_RECOVERY_RESERVATION_AMOUNT_MISMATCH

POST_RECOVERY_ACCOUNT_LEDGER_MISMATCH
POST_RECOVERY_ACCOUNT_RESERVATION_MISMATCH
POST_RECOVERY_TRADE_FEE_ATTRIBUTION_MISMATCH

POST_RECOVERY_FEE_RECORD_MISSING
POST_RECOVERY_FEE_TOTAL_MISMATCH
POST_RECOVERY_SETTLEMENT_RECORD_MISSING
POST_RECOVERY_SETTLEMENT_STATE_MISMATCH
POST_RECOVERY_MARGIN_STATE_MISMATCH

POST_RECOVERY_BROKER_ORDER_MISMATCH

POST_RECOVERY_INBOUND_QUEUE_NOT_EMPTY
POST_RECOVERY_EVENT_BUS_NOT_DRAINED
POST_RECOVERY_CURSOR_BOUNDARY_MISMATCH
POST_RECOVERY_RESULT_COUNT_CURSOR_MISMATCH
POST_RECOVERY_PROCESSING_SEQUENCE_MISMATCH
POST_RECOVERY_CLOCK_BEHIND_BOUNDARY

POST_RECOVERY_CHECKPOINT_NOT_DURABLE
POST_RECOVERY_CHECKPOINT_IDENTITY_MISMATCH
POST_RECOVERY_CHECKPOINT_HASH_MISMATCH
POST_RECOVERY_CHECKPOINT_COMPONENT_MISMATCH
POST_RECOVERY_CHECKPOINT_WRITE_FAILED
POST_RECOVERY_CHECKPOINT_COMMITTED_BUT_FINALIZATION_INTERRUPTED
```

不得将所有错误压缩为普通 `RuntimeError` 字符串。

---

# 二十八、实现步骤

## Step 1：预实现审计

完成审计文档。

## Step 2：先写红色 Engine 测试

至少先建立：

```text
Validation 失败发生在 on_recovery_complete() 之后
→ 当前实现 Cluster 已 RECOVERED
→ 失败清理不完整
```

以及：

```text
Post-Recovery Checkpoint Commit 成功
→ Wrapper 抛异常
→ 当前 Engine 不得继续
→ 新 Engine 从新 Checkpoint继续
```

## Step 3：实现 Recovery Outcome

调整 Orchestrator 返回模型。

## Step 4：增加 Cluster `RECOVERY_FINALIZING`

拆分 Callback 和最终 RECOVERED 转换。

## Step 5：新增最小只读 Authority Views

禁止 Validator 直接读取私有 Manager 容器。

## Step 6：实现 Validation Model

完成：

* Check；
* Report；
* Stable Sorting；
* Fingerprint；
* Duplicate Identity Guard。

## Step 7：实现基础 Checker

优先实现：

```text
Transaction
Outbox
Runtime Boundary
Result Progress
```

## Step 8：实现 Manager Checker

依次实现：

```text
Position / Allocation
Order / Reservation
Account / Ledger
Fee / Settlement / Margin
Broker Parity
```

## Step 9：实现 Recovery Projection Range Checker

只覆盖本次 Recovery Range。

## Step 10：重构 Checkpoint Service

实现：

```text
capture
write
verify_durable
create
create_verified
```

## Step 11：实现 Recovery Finalizer

只负责编排。

## Step 12：接入 Backtest Runtime

删除私有浅 Validator。

## Step 13：补齐故障矩阵

覆盖全部 Finalization Phase。

## Step 14：删除旧接口

删除：

```text
complete_recovery_all()
旧 fail_recovery_all() 弱语义
_validate_post_recovery_authority()
直接 create() 作为 Post-Recovery Finalization 的调用
```

不保留兼容 Wrapper。

## Step 15：更新文档和 ADR

---

# 二十九、测试要求

## 29.1 Validation Model 单元测试

至少：

1. Check Identity 稳定；
2. Check 排序稳定；
3. Duplicate Identity 拒绝；
4. Report Fingerprint 稳定；
5. `NOT_APPLICABLE` 不导致失败；
6. 任一 FAILED 导致 Report failed。

## 29.2 Transaction Checker

至少：

1. Sequence 连续；
2. Sequence Gap；
3. Unprojected Transaction；
4. Final Head Mismatch；
5. Duplicate Transaction ID；
6. Duplicate Broker Update ID；
7. Duplicate Trade ID；
8. Ready Query Mismatch。

## 29.3 Outbox Checker

至少：

1. 正常 Outbox；
2. Orphan Outbox；
3. 引用 Unready Transaction；
4. Duplicate Event ID；
5. Missing Continuation Outbox；
6. Prematurely Published Continuation Outbox；
7. Pending Count Mismatch。

## 29.4 Position / Allocation

至少：

1. 正常归约；
2. Quantity Mismatch；
3. Orphan Allocation；
4. Negative Available；
5. Available + Frozen > Total；
6. Hedging LONG / SHORT 独立 Scope。

## 29.5 Reservation

至少：

1. Open Order 对应完整 Reservation；
2. Missing Reservation；
3. Orphan Reservation；
4. Scope Mismatch；
5. Amount Mismatch；
6. Terminal Order 仍有 Active Reservation。

## 29.6 Account / Ledger

至少：

1. 正常归约；
2. Cash Mismatch；
3. Equity Mismatch；
4. Fee Mismatch；
5. 多 Cluster Ledger 汇总；
6. Frozen Cash / Reservation Mismatch。

## 29.7 Fee / Settlement / Margin

至少：

1. Fee Record Missing；
2. Fee Total Mismatch；
3. Settlement Record Missing；
4. Settlement State Mismatch；
5. Margin Not Applicable；
6. Margin State Mismatch。

## 29.8 Runtime Boundary

至少：

1. Broker Queue 非空；
2. MarketData Queue 非空；
3. EventBus 非空；
4. Cursor / Boundary Update ID 不一致；
5. Source Sequence 不一致；
6. Processed Count 不一致；
7. Processing Sequence 不一致；
8. Clock 落后于 Boundary。

## 29.9 Checkpoint Verify

至少：

1. 完全相等；
2. Latest Missing；
3. Sequence Mismatch；
4. Covered Sequence Mismatch；
5. Cursor Mismatch；
6. Registry Fingerprint Mismatch；
7. Aggregate Hash Mismatch；
8. Pending Outbox Count Mismatch；
9. Component Mismatch；
10. After-Commit Exception。

## 29.10 Cluster Lifecycle

至少：

1. RECOVERING → RECOVERY_FINALIZING；
2. Callback 后仍不是 RECOVERED；
3. Verify 成功后进入 RECOVERED；
4. Validation 失败进入 FAILED；
5. Capture 失败进入 FAILED；
6. Write 失败进入 FAILED；
7. Verify 失败进入 FAILED；
8. RECOVERED Fail-safe 清理；
9. FAILED Cluster 不得 Resume。

---

# 三十、Engine 集成故障矩阵

## 场景 A：正常 Finalization

```text
Engine A Execution Tail Crash
→ Engine B Recovery
→ Validator Passed
→ Verified Checkpoint
→ Pending Outbox Delivery
→ Cluster Resume
→ Engine Completed
```

要求与 Baseline 比较：

* Canonical Business Projection；
* Orders；
* Trades；
* Signals；
* Result Fingerprint；
* Artifact Manifest。

## 场景 B：Validation Failure

在正式 Checkpoint Restore 后构造一个 Authority 不一致。

要求：

```text
Runtime FAILED
Cluster FAILED
No New Verified Checkpoint
No Outbox Delivery
No Resume
No RUNNING
```

测试故障必须通过测试 Store、测试 Participant 或测试 Plugin 正式注入，不得直接修改 Runtime 私有字段。

## 场景 C：Participant Capture Failure

```text
on_recovery_complete passed
→ Validation passed
→ Participant capture raises
```

要求：

```text
Cluster FAILED
No New Checkpoint
No Outbox Delivery
```

## 场景 D：Checkpoint Write Before-Commit Failure

要求：

```text
No New Durable Checkpoint
Current Engine FAILED
```

## 场景 E：Checkpoint After-Commit Exception

```text
Checkpoint committed
→ Wrapper raises
```

要求：

```text
Current Engine FAILED
Expected Checkpoint remains
No Outbox Delivery
No RUNNING
```

## 场景 F：Engine A → B → C

```text
Engine A:
    Execution Tail Crash

Engine B:
    Recover Tail
    Validation Passed
    Checkpoint Commit Succeeded
    Wrapper Throws After Commit
    Engine B FAILED

Engine C:
    Load New Checkpoint
    No duplicate business mutation
    Continue and complete
```

最终与 Baseline 全量等价。

## 场景 G：Read-Back Mismatch

测试 Query 返回错误 Latest Checkpoint。

要求：

```text
Finalizer FAILED
Cluster FAILED
No Outbox Delivery
```

---

# 三十一、测试注入规则

允许：

* Test Persistence Store Wrapper；
* Test Checkpoint Participant；
* Test Broker Plugin；
* Test Authority View；
* Test Query Port；
* 正式 Composition Root 注入。

禁止：

* 修改 Runtime 私有字段；
* 手工设置 Cluster State；
* 直接修改 Manager 私有容器；
* 手工写 `_replay_cursor`；
* 手工调用 Finalizer内部私有方法；
* 增加生产故障开关；
* 为测试改变生产业务语义。

---

# 三十二、架构门禁

增加架构测试，至少保证：

1. Backtest Runtime 不再定义 `_validate_post_recovery_authority()`；
2. Runtime 不包含具体 Validation Error Code；
3. Validator 不导入 Backtest Runtime 实现；
4. Validator 不依赖 `OnlyRuntimeServices`；
5. Validator 不访问 Manager 私有字段；
6. Validator 不调用 Manager Mutation；
7. Finalizer 不实现业务公式；
8. Finalizer 使用 Validator；
9. Finalizer 使用 Checkpoint `capture/write/verify`；
10. Verify 前不能 `mark_recovered_all()`；
11. Cluster 存在 `RECOVERY_FINALIZING`；
12. Callback 与 RECOVERED 转换分离；
13. Failure Cleanup 覆盖 RECOVERING / RECOVERY_FINALIZING / RECOVERED；
14. Post-Recovery Checkpoint 必须 read-back verify；
15. Applied Projection Ledger 未新增 SQLite 持久表；
16. Checker 不依赖具体 Virtual Broker 类型；
17. Runtime READY 前不投递 Outbox；
18. Finalization Success 前不 Resume Cluster；
19. 不实现 Unified Recovery Event Gate；
20. 不保留旧接口兼容层。

源码字符串测试只能作为辅助。

核心正确性必须由行为测试证明。

---

# 三十三、建议文件结构

根据实际仓库调整：

```text
src/onlyalpha/runtime/recovery/
├── orchestrator.py
├── outcome.py
├── finalizer.py
├── validation.py
├── authority_validator.py
└── authority_views.py

src/onlyalpha/runtime/checkpoint/
└── service.py

src/onlyalpha/cluster/
├── base.py
└── manager.py
```

测试建议：

```text
tests/runtime/recovery/
├── test_recovery_outcome.py
├── test_post_recovery_validation_models.py
├── test_post_recovery_transaction_authority.py
├── test_post_recovery_outbox_authority.py
├── test_post_recovery_position_allocation.py
├── test_post_recovery_order_reservation.py
├── test_post_recovery_account_ledger.py
├── test_post_recovery_fee_settlement_margin.py
├── test_post_recovery_runtime_boundary.py
├── test_recovery_finalizer.py
└── test_checkpoint_durable_verification.py

tests/integration/
├── test_engine_recovery_finalization.py
├── test_engine_recovery_validation_failure.py
├── test_engine_recovery_checkpoint_after_commit.py
└── test_engine_recovery_three_stage_restart.py

tests/architecture/
└── test_recovery_finalization_architecture.py
```

---

# 三十四、文档要求

新增 ADR：

```text
docs/adr/0047-post-recovery-authority-validation-and-finalization.md
```

ADR 必须说明：

1. Recovery Replay Completed 为什么不等于 Runtime Stable；
2. 为什么新增 `RECOVERY_FINALIZING`；
3. 为什么 Callback 与 RECOVERED 转换分离；
4. Validator、Finalizer、Orchestrator 的职责；
5. Validator 为什么只依赖只读 Port；
6. Validator 为什么不能重新实现业务公式；
7. Applied Projection Ledger 为什么不是持久真相；
8. 为什么只校验本次 Recovery Projection Range；
9. 为什么 Post-Recovery Checkpoint 必须 read-back verify；
10. After-Commit Exception 为什么当前 Engine 必须 Fail Closed；
11. 为什么已提交 Checkpoint不得删除；
12. 为什么 Outbox 只能在 Finalization 成功后投递；
13. 哪些能力仍属于 4.2.2c；
14. 当前 Outbox 仍是 at-least-once；
15. 当前仍不支持 Paper/Live Recovery。

更新：

```text
README.md
docs/roadmap.md
docs/execution_runtime_recovery.md
docs/backtest.md
docs/architecture.md
```

---

# 三十五、完整测试命令

根据仓库实际结构调整，至少执行：

```bash
uv lock --check
uv sync --frozen --all-packages --all-groups

uv run ruff check src tests examples packages
uv run ruff format --check src tests examples packages

uv run mypy src/onlyalpha

uv run mypy packages/fake/onlyalpha-plugin-broker-virtual/src
uv run mypy packages/provider/onlyalpha-plugin-tushare/src/onlyalpha_plugin_tushare
uv run mypy packages/provider/onlyalpha-plugin-miniqmt/src/onlyalpha_plugin_miniqmt

uv run pytest tests/runtime/recovery -q
uv run pytest tests/runtime/checkpoint -q
uv run pytest tests/cluster -q
uv run pytest tests/execution -q
uv run pytest tests/account -q
uv run pytest tests/position -q
uv run pytest tests/order -q
uv run pytest tests/fee -q
uv run pytest tests/settlement -q
uv run pytest tests/margin -q

uv run pytest tests/integration/test_engine_recovery_finalization.py -q
uv run pytest tests/integration/test_engine_recovery_validation_failure.py -q
uv run pytest tests/integration/test_engine_recovery_checkpoint_after_commit.py -q
uv run pytest tests/integration/test_engine_recovery_three_stage_restart.py -q

uv run pytest tests/integration -q
uv run pytest tests/architecture -q

uv run pytest tests -q \
  -m "not external and not requires_network and not requires_tushare and not requires_local_qmt"

uv run pytest packages/fake/onlyalpha-plugin-broker-virtual/tests -q

uv run pytest packages/provider/onlyalpha-plugin-tushare/tests -q \
  -m "not external and not requires_network and not requires_tushare"

uv run pytest packages/provider/onlyalpha-plugin-miniqmt/tests -q \
  -m "not external and not requires_network and not requires_local_qmt"

git diff --check
```

不得伪造未执行的测试结果。

---

# 三十六、完成标准

只有全部满足才能声明 PR4.2.2b 完成：

1. Orchestrator 返回正式 Recovery Outcome；
2. Recovery Outcome 包含 Checkpoint、Tail、Continuation 和 Boundary 范围；
3. Cluster 有 `RECOVERY_FINALIZING`；
4. `on_recovery_complete()` 后 Cluster 尚未进入 RECOVERED；
5. Validator 和 Checkpoint Verify 成功后才进入 RECOVERED；
6. Runtime 不再包含私有浅 Validator；
7. Validator 只依赖只读 Port；
8. Validator 不复制业务公式；
9. Validation Report 有稳定排序；
10. Validation Report 有稳定 Fingerprint；
11. Duplicate Check Identity 被拒绝；
12. Transaction Sequence 完整验证；
13. 全部 Transaction Projection Ready；
14. Final Head 与 Recovery Outcome 一致；
15. Transaction / Trade / Update Identity 唯一；
16. Ready Query 与 Store 一致；
17. Outbox 无孤立记录；
18. Outbox 不引用 Unready Transaction；
19. Continuation Outbox 存在且未提前发布；
20. 本次 Recovery Projection Range 完整验证；
21. Applied Projection Ledger 未成为持久 Authority；
22. Position 与 Allocation 完整归约；
23. Position 内部数量不变量通过；
24. Open Order 与 Reservation 完整归约；
25. 不存在悬空 Reservation；
26. Account 与所有 Strategy Ledger 完整归约；
27. Fee Record 和 Fee Total 完整验证；
28. Settlement Record 完整验证；
29. Margin 按能力验证；
30. Broker 与 Local Open Order 基础一致；
31. Broker Queue 为空；
32. MarketData Queue 为空；
33. EventBus Queue 为空；
34. Cursor 与 Final Boundary 精确一致；
35. Result Progress Count 与 Cursor 精确一致；
36. Processing Sequence 精确一致；
37. Runtime Clock 不落后于 Boundary；
38. Checkpoint Service 拆分 Capture / Write / Verify；
39. Post-Recovery Checkpoint 使用 Read-Back Verify；
40. Verify 比较完整 Header、Hash 和 Components；
41. After-Commit Exception 当前 Engine Fail Closed；
42. 已提交 Checkpoint被保留；
43. 新 Engine 可以从已提交 Checkpoint继续；
44. Validation 失败时 Cluster FAILED；
45. Capture 失败时 Cluster FAILED；
46. Write 失败时 Cluster FAILED；
47. Verify 失败时 Cluster FAILED；
48. Finalization 成功前不投递 Outbox；
49. Finalization 成功前不 Resume Cluster；
50. Finalization 成功前不进入 READY；
51. Engine A → B → C 故障矩阵通过；
52. Canonical Business Projection 与 Baseline 相等；
53. Orders、Trades、Signals 相等；
54. Result Fingerprint 相等；
55. Artifact Manifest 相等；
56. 不依赖具体 Virtual Broker 实现类型；
57. 不修改 4.2.2a Causal Replay 语义；
58. 不实现 4.2.2c Event Gate；
59. 不增加生产故障开关；
60. Ruff、Mypy、Pytest 和 Architecture Gate 全部通过。

---

# 三十七、禁止实现

以下任一情况视为任务失败：

```text
继续在 Backtest Runtime 内维护具体 Authority 校验规则
Validation 前把 Cluster 标记为 RECOVERED
Checkpoint 写入后不做 read-back verify
After-Commit Exception 后继续进入 READY
删除已经成功提交的 Post-Recovery Checkpoint
Validation 失败后仍投递 Outbox
Validation 失败后仍 Resume Cluster
Validator 直接访问 Manager 私有容器
Validator 直接修改 Manager
Validator 重新实现 PnL / Fee / Margin / Settlement 公式
把 Applied Projection Ledger 变成 SQLite 持久权威
要求 Applied Ledger 覆盖全部 Checkpoint Prefix
Validator 依赖具体 OnlyVirtualBrokerGateway
只比较 Checkpoint Sequence，不比较 Hash 和 Components
继续比较不同维度的 Progress Sequence 和 Processed Bar Count
通过 try/except 吞掉 Finalization 错误
通过 Warning 代替 Fail Closed
保留旧 complete_recovery_all() 兼容 Wrapper
保留旧 _validate_post_recovery_authority()
测试修改 Runtime 私有字段
测试直接修改 Cluster State
测试直接修改 Manager 私有容器
增加生产故障配置
顺带实现 Unified Recovery Event Gate
顺带实现 Partial / Multi-Fill
顺带实现 SELL / CLOSE
顺带实现 Paper / Live Recovery
```

---

# 三十八、最终交付报告

完成后输出结构化报告。

## 1. 修改前问题

说明：

```text
Recovery Replay Completed
为什么不等于
Runtime Stable and Durable
```

## 2. Recovery Outcome

列出字段、来源和边界。

## 3. Cluster Lifecycle

说明：

```text
RECOVERING
→ RECOVERY_FINALIZING
→ RECOVERED
→ RUNNING
```

## 4. Validator 架构

说明：

* Context；
* Checker；
* Report；
* Fingerprint；
* 只读 Port；
* 复用现有 Reconciliation。

## 5. Authority 检查

分别说明：

* Transaction；
* Outbox；
* Projection Range；
* Position / Allocation；
* Order / Reservation；
* Account / Ledger；
* Fee / Settlement / Margin；
* Broker；
* Runtime Boundary。

## 6. Checkpoint Durable Verification

说明：

```text
Capture
→ Write
→ Read Back
→ Compare
```

## 7. After-Commit Exception

说明当前 Engine 和下一个 Engine 的行为。

## 8. 删除内容

列出删除的：

* Runtime 私有 Validator；
* 旧 Cluster Recovery API；
* 弱 Checkpoint 调用；
* Compatibility Wrapper。

## 9. 测试结果

列出实际执行的命令和真实结果。

## 10. 剩余边界

明确仍未实现：

* Unified Recovery Event Gate；
* Exactly-once Outbox；
* Partial / Multi-Fill；
* SELL / CLOSE；
* Futures / Margin 正式 Transaction；
* Non-Trade Transaction；
* Paper / Live Recovery；
* Full Broker Reconciliation；
* Schema Migration；
* Distributed Checkpoint。

---

# 三十九、最终架构结论

完成前：

```text
Exact Recovery Boundary Completed
→ Runtime Private Shallow Validation
→ Checkpoint Write
→ Cluster already RECOVERED
```

完成后必须变为：

```text
Exact Recovery Boundary Completed
→ Recovery Outcome
→ Cluster RECOVERY_FINALIZING
→ Recovery Completion Callback
→ Internal Quiescence
→ Complete Read-Only Authority Validation
→ Immutable Checkpoint Capture
→ Durable Write
→ Read-Back Verification
→ Cluster RECOVERED
→ Runtime READY
→ Pending Durable Outbox Delivery
→ Cluster RUNNING
```

最终必须证明：

> OnlyAlpha 只有在恢复后的 Transaction、Outbox、Position、Allocation、Order、Reservation、Account、Ledger、Fee、Settlement、Margin、Broker Local State、Replay Cursor 和 Result Progress 全部自洽，并且新的 Post-Recovery Checkpoint 已经过持久化读回验证后，才允许 Runtime 重新进入 READY 和 RUNNING。
