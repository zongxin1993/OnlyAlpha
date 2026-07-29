# OnlyAlpha PR4.2.2c：Unified Recovery Event Gate 与外部事件恢复门禁

## 一、任务背景

请基于 OnlyAlpha 当前 `master` 分支的真实源码、测试、ADR、README 和 Roadmap，完成：

```text
PR4.2.2c
Unified Recovery Event Gate
+
Runtime Event Router
+
Direct Publisher Migration
+
Historical Direct Event Suppression
+
Continuation Durable Event Delivery
```

开始工作前必须重新读取当前仓库，不得只依赖本提示词中的描述。

当前预期基线最新提交为：

```text
7ff1fb2bb8f9861f7fb2b343f931545cb8fafda3
Feat: Closure：Post-Recovery Authority Validation 补强
```

如果实际 `master` 已更新，以实际代码为准，并在预实现审计中说明差异。

PR4.2.2a 已完成：

```text
Persisted Transaction Tail Recovery
→ Tail Resolved
→ Exact MarketData Boundary
→ Same-Bar Continuation Transaction
```

PR4.2.2b 及 Closure 已完成：

```text
Recovery Outcome
→ Cluster RECOVERY_FINALIZING
→ Post-Recovery Authority Validation
→ Checkpoint Capture
→ Durable Write
→ Read-Back Verification
→ Cluster RECOVERED
→ Runtime READY
```

PR4.2.2c 不再修改恢复状态正确性，而是解决：

> Recovery Replay 重新执行历史业务逻辑时，内部状态必须继续重建，但历史外部 Direct Event 不能再次被观察；Recovery 中新产生的 Continuation Transaction Event 必须保留在 Durable Outbox 中，并且只能在 Finalization 成功后交付。

---

# 二、当前问题

当前 `ExecutionProcessor.replay()` 会把自己的 Delivery Intent 改成：

```text
NONE
```

这只会抑制 ExecutionProcessor 自己的即时交付。

当前仍存在多条绕过该机制的事件路径：

```text
Order Publisher
→ EventBus.publish()

Risk Publisher
→ EventBus.publish()

MarketData Result Facts
→ EventBus.publish_many()

Account / Position / Ledger / Valuation Direct Batch
→ Direct Execution Publisher
→ EventBus.publish()

Runtime Lifecycle
→ EventBus.publish()

Execution Outbox
→ EventBus.publish()
```

因此，恢复期间可能出现：

```text
历史 MarketData Event 重复
历史 Order Event 重复
历史 Risk Event 重复
历史 Account / Position / Ledger Event 重复
历史 Valuation / Settlement Event 重复
```

当前 EventBus 本身只负责：

```text
Scope
FIFO
Capacity
Priority
Handler Dispatch
Backpressure
```

EventBus 不知道 Runtime State、Recovery Phase 或 Event Route。

本任务不得把 Recovery 判断直接塞进 EventBus。

---

# 三、任务目标

本任务必须将事件发布架构升级为：

```text
业务 Publisher
→ Runtime Event Publication Port
→ OnlyRuntimeEventRouter
→ OnlyRuntimeRecoveryEventGate
→ EventBus
```

实现后必须满足：

```text
Fresh Bootstrap Event
→ 暂存
→ Runtime 正式 OPEN 后按 FIFO 发布

Recovery Bootstrap Event
→ 丢弃

Recovery Historical Direct Event
→ 抑制
→ 永不补发

Recovery Continuation Transaction Event
→ Durable Outbox Pending
→ Finalization 成功
→ Runtime OPEN
→ 正式交付

Finalization Failure
→ 不发布 Direct Event
→ 不交付 Durable Outbox
→ 不发布 RUNTIME_STARTED
```

---

# 四、任务范围

本任务必须完成：

1. 事件 Route 模型；
2. Recovery Event Gate 状态机；
3. Event Publication Disposition；
4. 有界 Bootstrap Staging Buffer；
5. Runtime Event Router；
6. Direct Event Publication Port；
7. Durable Event Publication Port；
8. Lifecycle Event Publication Port；
9. Execution Direct Publisher 迁移；
10. Execution Outbox Publisher 迁移；
11. Order Publisher 迁移；
12. Risk Publisher 迁移；
13. MarketData Facts 迁移；
14. Account / Position / Ledger / Valuation Direct Batch 接入 Router；
15. Runtime Lifecycle Publisher 迁移；
16. Runtime Recovery 生命周期接线；
17. Runtime Start/Open 生命周期接线；
18. Runtime Failure/Close 接线；
19. Runtime 对外 EventBus 只读化；
20. Event Gate Operational Diagnostics；
21. Fresh Start Event 测试；
22. Bootstrap Event Discard 测试；
23. Historical Direct Event Suppression 测试；
24. Same-Bar Continuation Durable Delivery 测试；
25. Finalization Failure Event 测试；
26. Engine Restart Business Projection 等价测试；
27. Architecture Gate；
28. ADR、README、Roadmap 和 Recovery 文档更新。

---

# 五、明确不在本任务范围内

本任务不得实现：

```text
Direct Event Durable Journal
Direct Event Delivery Watermark
Subscriber ACK
Direct Event Replay API
Exactly-once Direct Event
Exactly-once Outbox
Remote EventBus
Kafka
Redis Stream
WebSocket
SSE
Partial / Multi-Fill
SELL / CLOSE
Futures / Margin 正式 Transaction
Non-Trade Durable Transaction
Paper Runtime Recovery
Live Runtime Recovery
Distributed Checkpoint
新的 Checkpoint Schema
新的 Runtime Persistence 表
```

本任务不得修改：

```text
Recovery Outcome
Causal Recovery Session
Exact Boundary State Machine
Post-Recovery Authority Validator
Recovery Finalizer Phase
Checkpoint Header / Component Schema
Execution Transaction Store
Canonical Business Projection
Result Fingerprint
```

---

# 六、开始前必须审计的代码

重点阅读：

```text
src/onlyalpha/event/bus.py
src/onlyalpha/event/model.py

src/onlyalpha/execution/delivery.py
src/onlyalpha/execution/event_buffer.py
src/onlyalpha/execution/processor.py
src/onlyalpha/execution/commit_coordinator.py
src/onlyalpha/execution/persistence_ports.py

src/onlyalpha/order/publisher.py
src/onlyalpha/order/service.py
src/onlyalpha/order/execution/processor.py

src/onlyalpha/risk/publisher.py
src/onlyalpha/risk/service.py

src/onlyalpha/runtime/runtime.py
src/onlyalpha/runtime/backtest/runtime.py
src/onlyalpha/runtime/backtest/factory.py

src/onlyalpha/runtime/recovery/finalizer.py
src/onlyalpha/runtime/recovery/orchestrator.py
src/onlyalpha/runtime/recovery/outcome.py

src/onlyalpha/account/events.py
src/onlyalpha/position/events.py
src/onlyalpha/strategy_ledger/publisher.py

src/onlyalpha/data/processor.py
src/onlyalpha/market_data/pipeline.py
```

重点搜索：

```bash
rg "event_bus.publish"
rg "event_bus.publish_many"
rg "owned_bus.publish"
rg "owned_bus.publish_many"

rg "OnlyEventBusDirectExecutionPublisher"
rg "OnlyExecutionOutboxPublisher"
rg "OnlyExecutionEventDeliveryCoordinator"

rg "OnlyRuntimeOrderEventPublisherAdapter"
rg "OnlyRuntimeRiskEventPublisherAdapter"
rg "OnlyRuntimeAccountEventPublisherAdapter"
rg "OnlyRuntimePositionEventPublisherAdapter"
rg "OnlyRuntimeStrategyLedgerEventPublisherAdapter"

rg "_publish_runtime_fact"
rg "RUNTIME_STARTED"

rg "event_sink = owned_bus"
rg "execution_event_buffer"
rg "delivery_intent"
rg "replay_non_transaction"
rg "_activate_backtest_recovery"
rg "_deactivate_backtest_recovery"

rg "def event_bus"
rg "OnlyRuntimeServices"
```

---

# 七、预实现审计文档

开始生产代码修改前，新增：

```text
docs/reports/pr4_2_2c_recovery_event_gate_pre_implementation_audit.md
```

审计必须回答：

1. 当前所有 EventBus 写入点；
2. 每个写入点的业务组件；
3. 每个 Event 是 Direct、Durable 还是 Lifecycle；
4. 当前哪些 Event 由 Execution Event Buffer 产生；
5. 当前哪些 Event 绕过 Execution Delivery；
6. Recovery Replay 中哪些 Publisher 会被调用；
7. `ExecutionProcessor.replay()` 实际抑制了哪些交付；
8. 哪些历史 Direct Event 仍可能重复；
9. Runtime 构造阶段产生哪些 Event；
10. `add_cluster()` 阶段产生哪些 Event；
11. 为什么 Gate 初始状态不能是 OPEN；
12. 为什么 Fresh Start Bootstrap Event 需要暂存；
13. 为什么 Recovery Bootstrap Event 必须丢弃；
14. 为什么 Recovery Historical Direct Event 不能暂存后补发；
15. Continuation Transaction Event 为什么必须走 Durable Outbox；
16. 当前 Runtime Start 时 Outbox、Cluster Resume 和 Lifecycle 的顺序；
17. 当前 Runtime 对外是否暴露可写 EventBus；
18. 哪些测试直接使用 `runtime.event_bus.publish()`；
19. 哪些测试只需要订阅能力；
20. 哪些组件必须迁移到 Event Publication Port；
21. 哪些组件不应知道 Runtime Event Router；
22. EventBus 应保持哪些职责；
23. 本任务不应修改哪些已有恢复组件；
24. 当前 Direct Event 为什么无法同时保证不重复和不丢失；
25. 本任务的正式事件交付语义是什么。

审计完成前不得修改生产代码。

---

# 八、事件语义边界

## 8.1 Direct Event

Direct Event 是：

```text
非持久
外部可观察
Best-effort
不进入 Transaction Outbox
```

Recovery Replay 期间：

```text
Direct Event
→ SUPPRESSED
→ 不进入 EventBus
→ 不缓存
→ 不在恢复后补发
```

这保证：

```text
Recovery 不主动制造历史 Direct Event 重复
```

但不保证 Direct Event 在崩溃场景下不丢失。

必须在 ADR 中明确：

> 没有 Durable Journal、Delivery Watermark 和 Subscriber ACK 时，Direct Event 无法同时获得不重复和不丢失保证。

## 8.2 Durable Outbox Event

Durable Event 是：

```text
来自正式 Committed Transaction
持久化到 Runtime Outbox
at-least-once
```

Recovery Continuation Transaction：

```text
Commit
→ Projection Ready
→ Durable Outbox Pending
→ Finalization 成功
→ Runtime OPEN
→ 发布
```

## 8.3 Lifecycle Event

Lifecycle Event 例如：

```text
RUNTIME_STARTED
RUNTIME_STOPPED
RUNTIME_FAILED
```

必须通过 Lifecycle Route 发布。

不得继续直接调用 EventBus。

---

# 九、不要新增 Internal EventBus

当前核心业务推进主要依赖同步函数调用：

```text
MarketData Processor
→ Dispatcher
→ Cluster

Execution Processor
→ Commit Coordinator
→ Projection Applier
→ Managers
```

不是依赖 EventBus 驱动业务状态。

因此，本任务必须将当前 EventBus 定义为：

> Runtime 外部可观察事件平面。

不得新增第二个 Internal EventBus。

不得将同步业务流程重构为 Event-Driven Workflow。

---

# 十、事件 Route 模型

建议新增：

```text
src/onlyalpha/event/ports.py
src/onlyalpha/runtime/events/gate.py
src/onlyalpha/runtime/events/router.py
src/onlyalpha/event/subscription_view.py
```

定义：

```python
class OnlyRuntimeEventRoute(StrEnum):
    EXTERNAL_DIRECT = "EXTERNAL_DIRECT"
    DURABLE_OUTBOX = "DURABLE_OUTBOX"
    LIFECYCLE = "LIFECYCLE"
```

本任务不增加 `INTERNAL` Route。

---

# 十一、Gate Phase

定义：

```python
class OnlyRuntimeEventGatePhase(StrEnum):
    BOOTSTRAPPING = "BOOTSTRAPPING"
    RECOVERING = "RECOVERING"
    FINALIZING = "FINALIZING"
    READY_BLOCKED = "READY_BLOCKED"
    OPEN = "OPEN"
    FAILED = "FAILED"
    CLOSED = "CLOSED"
```

---

# 十二、Gate Phase 语义

## 12.1 BOOTSTRAPPING

Runtime 已创建，但尚未确定：

```text
Fresh Start
还是
Checkpoint Recovery
```

此时：

```text
EXTERNAL_DIRECT
→ STAGED

DURABLE_OUTBOX
→ REJECTED

LIFECYCLE
→ REJECTED
```

Runtime 构造、Account 初始化、Cluster 注册阶段产生的 Direct Event 必须暂存。

## 12.2 RECOVERING

确认存在 Checkpoint 后：

```text
丢弃 Bootstrap Staging
→ 进入 RECOVERING
```

此时：

```text
EXTERNAL_DIRECT
→ SUPPRESSED

DURABLE_OUTBOX
→ REJECTED

LIFECYCLE
→ REJECTED
```

## 12.3 FINALIZING

Recovery Replay 完成，开始：

```text
Cluster Recovery Completion
Authority Validation
Checkpoint Verification
```

此时：

```text
EXTERNAL_DIRECT
→ SUPPRESSED

DURABLE_OUTBOX
→ REJECTED

LIFECYCLE
→ REJECTED
```

## 12.4 READY_BLOCKED

表示：

```text
Fresh Bootstrap 已完成
或
Recovery Finalization 已完成
```

但 Runtime 尚未执行 `start()`。

此时：

```text
EXTERNAL_DIRECT
→ STAGED

DURABLE_OUTBOX
→ REJECTED

LIFECYCLE
→ REJECTED
```

Recovery 路径进入 READY_BLOCKED 时，Staging 必须为空。

## 12.5 OPEN

Runtime 已通过正式开放点。

此时：

```text
EXTERNAL_DIRECT
→ PUBLISHED

DURABLE_OUTBOX
→ PUBLISHED

LIFECYCLE
→ PUBLISHED
```

## 12.6 FAILED

所有业务发布拒绝。

## 12.7 CLOSED

所有发布拒绝。

---

# 十三、Publication Disposition

定义：

```python
class OnlyRuntimeEventDisposition(StrEnum):
    PUBLISHED = "PUBLISHED"
    STAGED = "STAGED"
    SUPPRESSED = "SUPPRESSED"
    REJECTED = "REJECTED"
```

定义结果：

```python
@dataclass(frozen=True, slots=True)
class OnlyRuntimeEventPublicationResult:
    route: OnlyRuntimeEventRoute
    disposition: OnlyRuntimeEventDisposition

    attempted: int
    published: int
    staged: int
    suppressed: int
    rejected: int

    error: str | None = None
```

要求：

```text
attempted
=
published + staged + suppressed + rejected
```

Batch Publication 必须返回完整数量。

不得继续只用 `bool` 表示 Gate 结果。

---

# 十四、Gate 状态机合同

建议接口：

```python
class OnlyRuntimeRecoveryEventGate:
    @property
    def phase(self) -> OnlyRuntimeEventGatePhase:
        ...

    def stage_or_route(
        self,
        route: OnlyRuntimeEventRoute,
        events: tuple[OnlyEvent, ...],
    ) -> OnlyRuntimeEventGateDecision:
        ...

    def begin_recovery(self) -> int:
        ...

    def begin_finalization(self) -> None:
        ...

    def complete_fresh_bootstrap(self) -> None:
        ...

    def complete_recovery(self) -> None:
        ...

    def open(self) -> tuple[OnlyEvent, ...]:
        ...

    def fail(self) -> None:
        ...

    def close(self) -> None:
        ...

    def snapshot(self) -> OnlyRuntimeEventGateSnapshot:
        ...
```

---

# 十五、合法状态转换

只允许：

```text
BOOTSTRAPPING
→ READY_BLOCKED
→ OPEN

BOOTSTRAPPING
→ RECOVERING
→ FINALIZING
→ READY_BLOCKED
→ OPEN

BOOTSTRAPPING
→ FAILED

RECOVERING
→ FAILED

FINALIZING
→ FAILED

READY_BLOCKED
→ FAILED

OPEN
→ FAILED

OPEN
→ CLOSED

FAILED
→ CLOSED
```

禁止：

```text
FAILED → OPEN
CLOSED → OPEN
FINALIZING → RECOVERING
OPEN → RECOVERING
READY_BLOCKED → RECOVERING
```

重复调用同一 Transition 必须明确：

* 允许幂等；
* 或抛正式 Lifecycle Error。

建议除 `fail()` 和 `close()` 外，其他 Transition 不允许重复。

---

# 十六、Bootstrap Staging Buffer

## 16.1 作用

Staging Buffer 只保存：

```text
BOOTSTRAPPING
READY_BLOCKED
```

阶段的 `EXTERNAL_DIRECT` Event。

不保存 Recovery Event。

## 16.2 有界

容量使用：

```text
runtime.config.event_capacity
```

或新增独立配置，但默认不得超过 Event Capacity。

溢出时必须：

```text
OnlyRuntimeEventStageCapacityError
→ Runtime Fail Closed
```

不得使用低优先级丢弃策略。

## 16.3 FIFO

所有 Staged Event 必须按生产顺序 Flush。

## 16.4 Batch Atomicity

Batch Publication 在 Staging Capacity 不足时，不允许只 Stage 一部分。

必须：

```text
整批成功
或
整批失败
```

## 16.5 Recovery 丢弃

`begin_recovery()` 必须：

```text
记录 discarded_bootstrap_count
→ 清空所有 Staged Event
→ 进入 RECOVERING
```

被丢弃的 Bootstrap Event 不得在 Recovery 完成后补发。

## 16.6 不持久化

Gate Phase、Staged Event、Counter 和 Sample：

```text
不进入 Checkpoint
不进入 Runtime Persistence Store
不进入 Business Projection
```

---

# 十七、Gate Diagnostics

定义：

```python
@dataclass(frozen=True, slots=True)
class OnlyRuntimeEventGateSnapshot:
    phase: OnlyRuntimeEventGatePhase
    staged_count: int

    published_direct_count: int
    published_durable_count: int
    published_lifecycle_count: int

    suppressed_direct_count: int
    rejected_count: int
    discarded_bootstrap_count: int

    last_suppressed_events: tuple[OnlySuppressedRuntimeEvent, ...]
```

定义：

```python
@dataclass(frozen=True, slots=True)
class OnlySuppressedRuntimeEvent:
    event_type: str
    source: str
    sequence: int
    timestamp_ns: int
    route: OnlyRuntimeEventRoute
    phase: OnlyRuntimeEventGatePhase
    reason: str
```

`last_suppressed_events` 最多保存：

```text
16
```

或一个明确的小型固定容量。

禁止无界保存全部 Suppressed Event。

---

# 十八、Event Publication Port

在：

```text
src/onlyalpha/event/ports.py
```

定义窄接口。

## 18.1 Direct Port

```python
class OnlyDirectEventPublicationPort(Protocol):
    def publish_direct(
        self,
        event: OnlyEvent,
    ) -> OnlyRuntimeEventPublicationResult:
        ...

    def publish_direct_many(
        self,
        events: tuple[OnlyEvent, ...],
    ) -> OnlyRuntimeEventPublicationResult:
        ...
```

## 18.2 Durable Port

```python
class OnlyDurableEventPublicationPort(Protocol):
    def publish_durable(
        self,
        event: OnlyEvent,
    ) -> OnlyRuntimeEventPublicationResult:
        ...
```

## 18.3 Lifecycle Port

```python
class OnlyLifecycleEventPublicationPort(Protocol):
    def publish_lifecycle(
        self,
        event: OnlyEvent,
    ) -> OnlyRuntimeEventPublicationResult:
        ...
```

这些 Port 必须位于低层 Event 包或独立协议包。

Execution、Order、Risk 不得反向导入 Runtime Router 实现。

---

# 十九、Runtime Event Router

建议实现：

```python
class OnlyRuntimeEventRouter:
    def __init__(
        self,
        event_bus: OnlyEventBus,
        gate: OnlyRuntimeRecoveryEventGate,
        runtime_scope: OnlyEventScope,
    ) -> None:
        ...

    def publish_direct(
        self,
        event: OnlyEvent,
    ) -> OnlyRuntimeEventPublicationResult:
        ...

    def publish_direct_many(
        self,
        events: tuple[OnlyEvent, ...],
    ) -> OnlyRuntimeEventPublicationResult:
        ...

    def publish_durable(
        self,
        event: OnlyEvent,
    ) -> OnlyRuntimeEventPublicationResult:
        ...

    def publish_lifecycle(
        self,
        event: OnlyEvent,
    ) -> OnlyRuntimeEventPublicationResult:
        ...

    def begin_recovery(self) -> None:
        ...

    def begin_finalization(self) -> None:
        ...

    def complete_fresh_bootstrap(self) -> None:
        ...

    def complete_recovery(self) -> None:
        ...

    def open(self) -> OnlyRuntimeEventPublicationResult:
        ...

    def fail(self) -> None:
        ...

    def close(self) -> None:
        ...

    def snapshot(self) -> OnlyRuntimeEventGateSnapshot:
        ...
```

---

# 二十、Router Scope 校验

Router 在任何 Gate 判断前，必须验证：

```text
event.scope
属于
runtime_scope
```

Scope 错误继续使用现有 Event Scope 语义或正式 Router Scope Error。

不得 Stage 或 Suppress 错误 Scope Event。

错误 Scope 必须：

```text
REJECT
→ 抛异常
```

---

# 二十一、Router 发布规则

## 21.1 PUBLISHED

调用：

```python
event_bus.publish(event)
```

EventBus 拒绝或抛异常时：

```text
Router 不得吞掉异常
```

## 21.2 STAGED

不调用 EventBus。

## 21.3 SUPPRESSED

不调用 EventBus。

不抛异常。

更新 Diagnostic。

## 21.4 REJECTED

抛正式 Gate Error。

不调用 EventBus。

---

# 二十二、Fresh Start 流程

实现后流程必须为：

```text
Runtime 构造
→ Gate BOOTSTRAPPING

Account 创建
→ Direct Event STAGED

Cluster 添加
→ Ledger / Risk / Cluster Direct Event STAGED

Runtime.initialize()
→ 没有 Checkpoint
→ complete_fresh_bootstrap()
→ Gate READY_BLOCKED

Runtime READY

Runtime.start()
→ Plugin Resources start
→ Router.open()
→ Gate OPEN
→ Flush Staged Events FIFO

→ Drain Pending Outbox
→ Cluster start
→ RUNTIME_STARTED
→ EventBus drain
→ Runtime RUNNING
```

Plugin Start 失败时：

```text
Router 不 OPEN
Staged Event 不发布
Gate FAILED
Runtime FAILED
```

---

# 二十三、Recovery 流程

实现后流程必须为：

```text
Runtime 构造
→ Gate BOOTSTRAPPING

Account / Cluster Bootstrap Event
→ STAGED

Runtime.initialize()
→ 发现 Checkpoint

Router.begin_recovery()
→ 丢弃 Bootstrap Staging
→ Gate RECOVERING

Drain Bootstrap Non-Transaction Broker Update
→ replay_non_transaction()
→ Direct Event SUPPRESSED

Cluster enter_recovery_all()

Orchestrator Recovery Replay
→ Historical MarketData / Order / Risk / Manager Event SUPPRESSED
→ Continuation Transaction 写 Durable Outbox

Exact Boundary Completed

Router.begin_finalization()
→ Gate FINALIZING

Recovery Finalizer
→ on_recovery_complete()
→ Direct Event SUPPRESSED
→ EventBus drain
→ Validation
→ Checkpoint Capture
→ Write
→ Verify
→ Cluster RECOVERED

Router.complete_recovery()
→ Gate READY_BLOCKED

Runtime READY

Runtime.start()
→ Plugin start
→ Router.open()
→ Gate OPEN
→ Durable Outbox Delivery
→ Cluster Resume
→ RUNTIME_STARTED
→ EventBus drain
→ Runtime RUNNING
```

---

# 二十四、Runtime `_recover_runtime()` 接线

根据当前真实代码调整，但必须保证以下顺序：

```python
def _recover_runtime(self) -> None:
    if not checkpoint_enabled:
        self._event_router.complete_fresh_bootstrap()
        return

    register_checkpoint_participants()
    bind_registry_fingerprint()

    has_checkpoint = latest_checkpoint(...) is not None

    if not has_checkpoint:
        outcome = recovery_orchestrator.recover()
        if outcome is not None:
            raise AssertionError(...)
        self._event_router.complete_fresh_bootstrap()
        return

    self._event_router.begin_recovery()

    try:
        drain_bootstrap_non_transaction_updates()
        cluster_manager.enter_recovery_all()

        outcome = recovery_orchestrator.recover()
        if outcome is None:
            raise OnlyRuntimeRecoveryError(...)

        self._event_router.begin_finalization()
        finalization = recovery_finalizer.finalize(outcome)

    except Exception:
        self._event_router.fail()
        raise

    self._event_router.complete_recovery()

    record_diagnostic(...)
    record_validation_report(...)
    self._clusters_recovered = True
```

关键门禁：

```text
begin_recovery()
必须在
replay_non_transaction()
之前
```

否则 Bootstrap Broker Update 仍可能产生外部 Direct Event。

---

# 二十五、Runtime `initialize()` 接线

Base Runtime 的 `initialize()` 当前会：

```text
INITIALIZING
→ RECOVERING
→ _recover_runtime()
→ READY
```

必须保持 Runtime State 语义不变。

如果 `_recover_runtime()` 失败：

```text
event_router.fail()
Runtime FAILED
```

防止 Base Runtime 的通用异常分支漏掉 Gate Failure。

可以在：

```text
_initialize failure cleanup
```

统一调用 Router Fail，但必须避免重复 Cleanup 破坏原始异常。

---

# 二十六、Runtime `start()` 接线

建议顺序：

```text
1. Require Runtime READY

2. Start Plugin Resources

3. event_router.open()
   - Fresh Start：Flush Staged Event
   - Recovery：没有 Staged Event

4. Drain Durable Execution Outbox

5. Resume Recovered Cluster
   或 Start Fresh Cluster

6. _after_clusters_started()

7. Runtime State → RUNNING

8. publish RUNTIME_STARTED through Lifecycle Route

9. EventBus drain
```

如果：

```text
Plugin Start 失败
```

则 Router 不得 OPEN。

如果：

```text
Router Open/Flush 失败
Outbox Delivery 失败
Cluster Resume 失败
```

则：

```text
event_router.fail()
Runtime FAILED
Plugin Rollback
```

---

# 二十七、Runtime Stop 和 Close

## Stop

建议：

```text
Runtime STOPPING
→ Cluster stop
→ 必要时 Outbox drain
→ Lifecycle STOP Event
→ EventBus drain
→ STOPPED
```

根据当前已有 Lifecycle Event 保持兼容。

不要在本 PR 额外扩展大量新的 Lifecycle Event。

## Close

```text
event_router.close()
→ EventBus close()
```

顺序必须避免 Router 在 EventBus 已关闭后 Flush 或发布。

---

# 二十八、Execution Direct Publisher 迁移

当前：

```text
OnlyEventBusDirectExecutionPublisher
```

必须删除或重构为：

```text
OnlyRoutedDirectExecutionPublisher
```

它只依赖：

```text
OnlyDirectEventPublicationPort
```

示意：

```python
class OnlyRoutedDirectExecutionPublisher:
    def __init__(
        self,
        publisher: OnlyDirectEventPublicationPort,
    ) -> None:
        self._publisher = publisher

    def publish(
        self,
        batch: OnlyExecutionEventBatch,
    ) -> OnlyDirectEventDeliveryResult:
        result = self._publisher.publish_direct_many(batch.events)
        ...
```

Direct Delivery Result 必须能区分：

```text
published
staged
suppressed
rejected
```

如果不扩展现有 Result Model，至少必须保证：

```text
STAGED 和 SUPPRESSED
不是 Delivery Failure
```

但 Diagnostic 中必须可见。

建议正式扩展 Delivery Diagnostic，而不是把两者伪装成 `published=0, failed=0` 后无法解释。

---

# 二十九、Execution Delivery Result 调整

建议扩展：

```python
@dataclass(frozen=True, slots=True)
class OnlyDirectEventDeliveryResult:
    attempted: int
    published: int
    staged: int
    suppressed: int
    failed: int
    error: str | None
```

相应扩展：

```python
OnlyExecutionEventDeliveryResult
OnlyExecutionDeliveryDiagnostic
```

但必须保持：

```text
Direct Event Suppression
不进入 Business Projection
不改变 Transaction Status
```

Recovery 中 ExecutionProcessor 本身仍返回 `NONE`。

不要删除现有 `NONE` Mode。

---

# 三十、Execution Outbox Publisher 迁移

当前 Outbox Publisher 直接持有 EventBus。

改为依赖：

```text
OnlyDurableEventPublicationPort
```

流程保持：

```text
pending()
→ begin_attempt()
→ publish_durable()
→ mark_published()
```

只有：

```text
Disposition == PUBLISHED
```

时才能：

```text
mark_published()
```

如果 Durable Route 被 Gate Reject：

```text
mark_failed()
→ Outbox Delivery Failure
→ Runtime Fail Closed
```

不得：

```text
STAGE Durable Event
SUPPRESS Durable Event
```

Durable Event 只能：

```text
OPEN 时发布
其他阶段拒绝
```

继续保持：

```text
at-least-once
```

不得声称 exactly-once。

---

# 三十一、Order Publisher 迁移

修改：

```text
src/onlyalpha/order/publisher.py
```

当前 Adapter 依赖 `OnlyEventBus`。

改为依赖：

```text
OnlyDirectEventPublicationPort
```

删除：

```python
from onlyalpha.event.bus import OnlyEventBus
```

实现：

```python
class OnlyRuntimeOrderEventPublisherAdapter:
    def __init__(
        self,
        publisher: OnlyDirectEventPublicationPort,
    ) -> None:
        self._publisher = publisher

    def publish(self, event: OnlyEvent) -> None:
        self._publisher.publish_direct(event)

    def publish_many(self, events: tuple[OnlyEvent, ...]) -> None:
        self._publisher.publish_direct_many(events)
```

不要让 Order 包导入 Runtime Router。

---

# 三十二、Risk Publisher 迁移

与 Order 相同。

修改：

```text
src/onlyalpha/risk/publisher.py
```

依赖：

```text
OnlyDirectEventPublicationPort
```

删除 EventBus 依赖。

---

# 三十三、Account、Position、Strategy Ledger 迁移

Account、Position、Strategy Ledger 当前通过 Adapter 将 Event 写入：

```text
OnlyExecutionEventBuffer
```

这些 Manager 不需要感知 Router。

只需要保证：

```text
Execution Direct Publisher
→ Direct Event Port
→ Runtime Router
```

即可统一控制：

* Account；
* Position；
* Allocation；
* Strategy Ledger；
* Valuation；
* Settlement Direct Batch。

不要修改 Manager 的业务发布接口，除非当前代码无法正常接入。

---

# 三十四、MarketData Event 迁移

将 Backtest Runtime 中：

```python
owned_bus.publish_many(result.facts)
```

替换为：

```python
event_router.publish_direct_many(result.facts)
```

Recovery Replay 时：

```text
MarketData Pipeline 和 Strategy Dispatch 正常继续
MarketData Facts 被 SUPPRESS
```

Fresh/Normal Runtime 时：

```text
MarketData Facts 正常发布
```

不要停止 MarketData Pipeline。

不要通过跳过 `before_market_dispatch()` 的方式抑制 Event，因为该函数还承担：

* Trading Day Advance；
* Settlement；
* Valuation；
* Broker Driver；
* Execution Update Drain。

---

# 三十五、Runtime Lifecycle 迁移

将：

```python
self._services.event_bus.publish(runtime_event)
```

替换为：

```python
self._services.event_router.publish_lifecycle(runtime_event)
```

至少覆盖：

```text
RUNTIME_STARTED
```

如果当前已有其他 Runtime Lifecycle Event，也统一迁移。

`RUNTIME_STARTED` 必须满足：

```text
Gate OPEN
Outbox Delivery 成功
Cluster Start/Resume 成功
Runtime State 已准备进入 RUNNING
```

不得在 Recovery Finalization 中发布。

---

# 三十六、OnlyRuntimeServices 调整

增加：

```python
event_router: OnlyRuntimeEventRouter
event_bus_view: OnlyEventBusSubscriptionView
```

保留内部原始：

```python
event_bus: OnlyEventBus
```

只供：

* Router；
* Finalizer Drain；
* Runtime Close；
* Runtime Internal Orchestration。

不允许业务 Publisher 继续从 Services 获取原始 EventBus。

---

# 三十七、Runtime EventBus 公开边界

当前：

```python
@property
def event_bus(self) -> OnlyEventBus:
    return self._services.event_bus
```

必须改为只读/订阅视图。

新增：

```python
class OnlyEventBusSubscriptionView:
    def subscribe(...): ...
    def unsubscribe(...): ...

    @property
    def failures(...): ...

    @property
    def dispatch_results(...): ...

    @property
    def dropped_events(...): ...

    def pending_count(self) -> int: ...
```

不得暴露：

```text
publish
publish_many
dispatch
drain
close
```

Runtime API：

```python
@property
def event_bus(self) -> OnlyEventBusSubscriptionView:
    return self._services.event_bus_view
```

如果已有大量测试和示例依赖 `runtime.event_bus.subscribe()`，保持该调用兼容。

任何依赖 `runtime.event_bus.publish()` 的测试必须迁移到正式测试 Publisher 或 Router Fixture。

---

# 三十八、Finalizer 接线

Recovery Finalizer 不负责 Gate 状态转换。

推荐：

```text
Runtime
→ router.begin_finalization()
→ finalizer.finalize()
→ router.complete_recovery()
```

不要把 Router 注入 Authority Validator。

不要把 Router 注入 Checkpoint Service。

Finalizer 仍可以直接持有原始 EventBus 进行：

```text
drain()
pending_count()
```

或者改为专门的内部 Drain Port。

不要求在本 PR 强行重构 Finalizer 的 EventBus Drain，只要外部发布全部经过 Router。

---

# 三十九、Fresh Bootstrap Staged Event 顺序

必须保持原始生产顺序。

示例：

```text
ACCOUNT_CREATED
STRATEGY_LEDGER_CREATED
STRATEGY_LEDGER_ACTIVATED
CLUSTER_REGISTERED
RUNTIME_STARTED
```

前四项在 Bootstrap 阶段暂存。

Runtime Start 时：

```text
先 Flush Bootstrap Event
再启动/恢复 Cluster
再发布 RUNTIME_STARTED
```

最终顺序必须由测试固定。

如果当前业务原始顺序不同，以实际代码为准，但必须稳定且文档化。

---

# 四十、Recovery Bootstrap Event 丢弃

在新 Engine 构造阶段，Account、Ledger、Risk Binding 等会再次发生。

这些是：

```text
当前 Engine 的临时 Bootstrap Event
```

一旦发现 Checkpoint：

```text
这些 Bootstrap Authority 会被 Checkpoint Restore 覆盖
```

因此：

```text
begin_recovery()
→ 丢弃全部 Bootstrap Staged Event
```

不得：

```text
Recovery 完成后 Flush
```

否则会向外部观察者发送虚假的“新建 Account/新建 Ledger”事件。

---

# 四十一、Direct Event 不重复测试的比较键

不要只比较随机 `event_id`。

使用稳定 Event Projection：

```python
@dataclass(frozen=True, slots=True)
class OnlyExternalEventProjection:
    event_type: str
    runtime_id: str
    cluster_id: str | None
    source: str
    sequence: int
    timestamp_ns: int
    payload_hash: str
```

`payload_hash` 使用稳定 JSON Canonicalization。

不要把：

```text
ts_init
随机 UUID Event ID
当前 Engine 创建时间
```

作为跨重启业务比较键，除非这些字段本身是稳定业务合同。

---

# 四十二、测试 Fixture 原则

允许使用：

* Test Event Subscriber；
* Test Runtime Event Router；
* Test EventBus；
* Test Broker Plugin；
* Test Checkpoint Participant；
* 正式 Runtime Factory；
* 正式 Engine Restart Harness。

禁止：

* 修改 Runtime 私有 State；
* 直接修改 Gate 私有 Phase；
* 直接修改 EventBus 私有 Queue；
* 修改 Manager 私有容器；
* 增加生产 Fault Switch；
* 绕过正式 Runtime Lifecycle；
* 手工调用 Router 私有方法制造状态。

故障必须通过正式测试 Adapter、Store Wrapper、Plugin 或 Participant 注入。

---

# 四十三、Gate 单元测试

新增：

```text
tests/runtime/events/test_recovery_event_gate.py
```

至少覆盖：

1. 初始 Phase 为 BOOTSTRAPPING；
2. Bootstrap Direct Event 被 Stage；
3. Bootstrap Direct Batch 被 Stage；
4. Batch Staging 保持原子；
5. Bootstrap Durable Event 被 Reject；
6. Bootstrap Lifecycle Event 被 Reject；
7. `complete_fresh_bootstrap()` 进入 READY_BLOCKED；
8. READY_BLOCKED Direct Event继续 Stage；
9. `open()` Flush Staged Event；
10. Flush 保持 FIFO；
11. `open()` 后 Staging 为空；
12. `begin_recovery()` 清空 Bootstrap Staging；
13. Discarded Count 正确；
14. RECOVERING Direct Event 被 Suppress；
15. RECOVERING Durable Event被 Reject；
16. RECOVERING Lifecycle Event被 Reject；
17. `begin_finalization()` 只能从 RECOVERING；
18. FINALIZING Direct Event被 Suppress；
19. `complete_recovery()` 进入 READY_BLOCKED；
20. Recovery READY_BLOCKED Staging 为空；
21. `open()` 后进入 OPEN；
22. OPEN Direct Event允许；
23. OPEN Durable Event允许；
24. OPEN Lifecycle Event允许；
25. `fail()` 清空 Staging；
26. FAILED 拒绝所有发布；
27. CLOSED 拒绝所有发布；
28. Illegal Transition 抛错；
29. Staging Capacity 溢出；
30. Suppressed Sample 有界。

---

# 四十四、Router 单元测试

新增：

```text
tests/runtime/events/test_runtime_event_router.py
```

至少覆盖：

1. Scope 正确；
2. Scope 错误；
3. Direct Published；
4. Direct Staged；
5. Direct Suppressed；
6. Direct Batch；
7. Durable Published；
8. Durable Gate Reject；
9. Lifecycle Published；
10. Lifecycle Gate Reject；
11. EventBus Capacity Error；
12. EventBus Scope Error；
13. Publication Result Counts；
14. Diagnostic Counters；
15. Fresh `open()` Flush；
16. Recovery `open()` 无 Flush；
17. Router Fail；
18. Router Close。

---

# 四十五、Subscription View 测试

新增：

```text
tests/runtime/events/test_event_subscription_view.py
```

至少证明：

```text
subscribe 可用
unsubscribe 可用
failures 可读
dispatch_results 可读
pending_count 可读
```

并且：

```text
没有 publish
没有 publish_many
没有 dispatch
没有 drain
没有 close
```

---

# 四十六、Publisher 迁移测试

分别增加或更新：

```text
tests/order/test_order_publisher.py
tests/risk/test_risk_publisher.py
tests/execution/test_execution_event_delivery.py
```

证明：

```text
Order Publisher 通过 Direct Port
Risk Publisher 通过 Direct Port
Execution Direct Publisher 通过 Direct Port
Execution Outbox Publisher 通过 Durable Port
```

并检查：

```text
STAGED
SUPPRESSED
PUBLISHED
REJECTED
```

的行为。

---

# 四十七、Fresh Start 集成测试

新增：

```text
tests/integration/test_engine_event_gate_fresh_start.py
```

场景：

```text
Runtime 构造
→ Add Cluster
→ Initialize
→ Start
```

测试 Subscriber 在构造后立即订阅，或者通过 Factory 提供正式订阅时机。

要求：

1. Start 前没有 Bootstrap Event进入 Handler；
2. Gate Phase 在构造期为 BOOTSTRAPPING；
3. Initialize 后为 READY_BLOCKED；
4. Start 后 Gate 为 OPEN；
5. Bootstrap Event 按 FIFO 发布；
6. `RUNTIME_STARTED` 最后发布；
7. Staging 为空；
8. Runtime RUNNING；
9. Business Result 不变。

---

# 四十八、Bootstrap Event Discard 集成测试

新增：

```text
tests/integration/test_engine_recovery_bootstrap_event_discard.py
```

场景：

```text
Engine A
→ 产生 Checkpoint

Engine B 构造
→ Bootstrap Event 已 Stage
→ initialize() 发现 Checkpoint
→ begin_recovery()
```

要求：

1. Bootstrap Staging 在 begin_recovery 时被清空；
2. Account Created / Ledger Created 等 Bootstrap Event 不进入 EventBus；
3. Recovery 完成后不补发；
4. `discarded_bootstrap_count > 0`；
5. Runtime 正常恢复；
6. Business Projection 与 Baseline 相等。

---

# 四十九、Historical Direct Event Suppression 集成测试

新增：

```text
tests/integration/test_engine_recovery_direct_event_suppression.py
```

场景：

```text
Engine A
→ 正常运行
→ Subscriber 记录 Direct Event
→ 在 Execution Tail 中故障

Engine B
→ 订阅 Event
→ Recovery Replay
```

要求：

1. Engine B Recovery 期间没有 Direct Event进入 Subscriber；
2. Gate `suppressed_direct_count > 0`；
3. 至少覆盖：

   * MarketData；
   * Order；
   * Risk；
   * Account；
   * Position；
   * Ledger；
4. Exact Boundary 完成；
5. Authority Validation 通过；
6. Verified Checkpoint 创建成功；
7. Runtime READY；
8. Start 后没有补发历史 Direct Event；
9. Business Projection 与 Baseline 相等。

如果某类 Event 在当前正式场景中不会产生，应在测试报告中说明，并通过更小的正式 Harness 补充覆盖。

---

# 五十、Continuation Durable Delivery 集成测试

新增或扩展：

```text
tests/integration/test_engine_recovery_continuation_event_delivery.py
```

复用 Same-Bar Continuation。

场景：

```text
Engine A
→ 故障

Engine B Recovery
→ Tail Resolved
→ Same-Bar Continuation Commit
→ Durable Outbox Pending
```

Finalization 前断言：

```text
Continuation Outbox exists
published == False
Subscriber 未收到 Continuation Event
Gate Phase == FINALIZING 或 READY_BLOCKED
```

Runtime Start 后断言：

```text
Continuation Outbox published == True
Subscriber 收到 Continuation Event
Event 来自 Durable Route
不是 Direct Route
```

并要求：

```text
没有重复 Continuation Event
Transaction Sequence 连续
Business Projection 与 Baseline 相等
```

注意：Outbox 是 at-least-once。单次无故障 Start 场景可断言一次；不要把这个测试解释为 exactly-once 保证。

---

# 五十一、Finalization Failure Event 测试

新增：

```text
tests/integration/test_engine_recovery_event_gate_failure.py
```

至少覆盖：

1. Authority Validation Failure；
2. Checkpoint Capture Failure；
3. Checkpoint Write Failure；
4. Checkpoint Verify Failure。

每个场景要求：

```text
Gate FAILED
No Direct Event
No Durable Outbox Delivery
No RUNTIME_STARTED
No Cluster Resume
Runtime FAILED
Cluster FAILED
```

After-Commit Exception 场景中：

```text
Checkpoint 保留
Current Engine FAILED
Gate FAILED
Next Engine 可继续
```

---

# 五十二、A→B→C 测试保持

现有：

```text
Engine A
→ Tail Crash

Engine B
→ Recovery Checkpoint Commit 后异常

Engine C
→ 从新 Checkpoint恢复并完成
```

必须继续通过。

新增事件断言：

```text
Engine B 不发布 Historical Direct Event
Engine B 不发布 RUNTIME_STARTED
Engine B 不交付 Pending Outbox
Engine C 只在 OPEN 后交付 Durable Outbox
```

继续比较：

* Canonical Business Projection；
* Result Fingerprint；
* Orders；
* Trades；
* Signals；
* Artifact Manifest。

---

# 五十三、不要建立错误的 Direct Event 等价门禁

禁止断言：

```text
No-Failure Direct Event Stream
==
Crash + Restart Direct Event Stream
```

原因：

```text
Direct Event 非持久
没有 Delivery Watermark
没有 Subscriber ACK
```

正确门禁是：

```text
Recovery 期间 Direct Event不发布
+
已观察历史 Direct Event不主动重复
+
Recovery Bootstrap Event不补发
+
Continuation Durable Event在 OPEN 后交付
+
Business Projection保持等价
```

---

# 五十四、Architecture Gate

新增：

```text
tests/architecture/test_recovery_event_gate_architecture.py
```

至少检查：

1. `OnlyEventBus` 不导入 Runtime；
2. `OnlyEventBus` 不导入 Recovery；
3. EventBus 没有 Gate Phase；
4. EventBus 没有 Runtime State 判断；
5. Backtest Runtime 不调用 `owned_bus.publish()`；
6. Backtest Runtime 不调用 `owned_bus.publish_many()`；
7. Base Runtime Lifecycle 不直接调用 EventBus Publish；
8. Order Publisher 不导入 EventBus；
9. Risk Publisher 不导入 EventBus；
10. Execution Direct Publisher 不持有 EventBus；
11. Execution Outbox Publisher 不持有 EventBus；
12. ExecutionProcessor 不导入 Router；
13. ExecutionProcessor 不导入 Gate；
14. Commit Coordinator 不导入 Router；
15. Commit Coordinator 不导入 Gate；
16. Plugins 不持有 Runtime Event Router；
17. Runtime Event Router 是业务发布的唯一 EventBus Writer；
18. Runtime 对外 EventBus 属性返回 Subscription View；
19. Subscription View 不暴露 Publish；
20. Gate 不注册为 Checkpoint Participant；
21. Gate 不进入 Canonical Business Projection；
22. Gate 不进入 Result Fingerprint；
23. Finalizer 不交付 Durable Outbox；
24. Outbox 仍只在 Runtime Start 交付；
25. 不新增 Direct Event Persistence 表；
26. 不新增 Outbox Exactly-once 标记；
27. 不新增 Internal EventBus；
28. 不修改 Recovery Outcome；
29. 不修改 Checkpoint Schema；
30. 不实现 Partial / Multi-Fill。

源码字符串测试只能作为辅助。

核心正确性必须由行为测试证明。

---

# 五十五、建议错误类型

新增正式错误：

```python
class OnlyRuntimeEventGateError(OnlyRuntimeError):
    ...

class OnlyRuntimeEventGateTransitionError(OnlyRuntimeEventGateError):
    ...

class OnlyRuntimeEventStageCapacityError(OnlyRuntimeEventGateError):
    ...

class OnlyRuntimeEventRouteError(OnlyRuntimeEventGateError):
    ...
```

建议错误码：

```text
RUNTIME_EVENT_GATE_ILLEGAL_TRANSITION
RUNTIME_EVENT_GATE_ROUTE_REJECTED
RUNTIME_EVENT_STAGE_CAPACITY_EXCEEDED
RUNTIME_EVENT_SCOPE_MISMATCH
RUNTIME_EVENT_BUS_REJECTED
```

不得只抛普通：

```text
RuntimeError("event failed")
```

---

# 五十六、建议文件结构

```text
src/onlyalpha/event/
├── bus.py
├── model.py
├── ports.py
└── subscription_view.py

src/onlyalpha/runtime/events/
├── __init__.py
├── gate.py
└── router.py
```

主要修改：

```text
src/onlyalpha/runtime/runtime.py
src/onlyalpha/runtime/backtest/runtime.py

src/onlyalpha/execution/delivery.py
src/onlyalpha/order/publisher.py
src/onlyalpha/risk/publisher.py
```

测试：

```text
tests/runtime/events/
├── test_recovery_event_gate.py
├── test_runtime_event_router.py
└── test_event_subscription_view.py

tests/integration/
├── test_engine_event_gate_fresh_start.py
├── test_engine_recovery_bootstrap_event_discard.py
├── test_engine_recovery_direct_event_suppression.py
├── test_engine_recovery_continuation_event_delivery.py
└── test_engine_recovery_event_gate_failure.py

tests/architecture/
└── test_recovery_event_gate_architecture.py
```

---

# 五十七、推荐实现顺序

## Step 1：预实现审计

完成审计文档。

## Step 2：写 Gate 红色单元测试

覆盖：

```text
BOOTSTRAPPING
RECOVERING
FINALIZING
READY_BLOCKED
OPEN
FAILED
CLOSED
```

## Step 3：实现 Gate

只实现纯状态机、Staging 和 Diagnostics。

暂不迁移业务 Publisher。

## Step 4：实现 Router

接入真实 EventBus。

完成 Scope、Disposition 和 Publication Result。

## Step 5：实现 Subscription View

收缩 Runtime 外部写权限。

## Step 6：迁移 Execution Direct Publisher

保留 Delivery Coordinator。

## Step 7：迁移 Execution Outbox Publisher

保持 at-least-once。

## Step 8：迁移 Order 和 Risk Publisher

删除 EventBus 直接依赖。

## Step 9：迁移 MarketData

替换所有 `owned_bus.publish*`。

## Step 10：迁移 Runtime Lifecycle

统一通过 Lifecycle Route。

## Step 11：接入 Runtime Recovery Lifecycle

实现：

```text
begin_recovery
begin_finalization
complete_recovery
fail
```

## Step 12：接入 Runtime Fresh Start 和 Start Lifecycle

实现：

```text
complete_fresh_bootstrap
open
```

## Step 13：补齐 Engine 行为测试

先 Fresh，再 Recovery，再 Continuation，再 Failure。

## Step 14：增加 Architecture Gate

禁止新绕过路径。

## Step 15：更新 ADR 和文档

---

# 五十八、文档要求

新增：

```text
docs/adr/0048-unified-recovery-event-gate.md
```

ADR 必须说明：

1. 为什么 ExecutionProcessor Delivery Intent 不足；
2. 当前有哪些 Direct Event 绕过路径；
3. 为什么 EventBus 不应感知 Recovery；
4. 为什么 EventBus 被定义为外部观察平面；
5. 为什么不新增 Internal EventBus；
6. Direct Event 和 Durable Event 的差别；
7. 为什么 Direct Event 无法同时不重复且不丢失；
8. 为什么 Recovery Direct Event 选择 Suppress；
9. 为什么 Suppressed Event 不在恢复后补发；
10. 为什么 Continuation Event 必须走 Durable Outbox；
11. 为什么 Gate 初始为 BOOTSTRAPPING；
12. 为什么 Fresh Bootstrap Event 需要 Stage；
13. 为什么 Recovery Bootstrap Event 必须丢弃；
14. Gate Phase 和合法转换；
15. Router Route 和 Disposition；
16. 为什么 Runtime EventBus 必须只读化；
17. 为什么 Gate 不进入 Checkpoint；
18. 为什么 Gate 不进入 Business Projection；
19. 当前 Outbox 仍为 at-least-once；
20. 本任务没有实现哪些可靠消息能力。

更新：

```text
README.md
docs/roadmap.md
docs/architecture.md
docs/execution_runtime_recovery.md
docs/event.md
docs/backtest.md
```

Roadmap 标记：

```text
PR4.2.2c
Unified Recovery Event Gate
已完成
```

同时保留：

```text
Exactly-once Outbox
Direct Event Durable Journal
Paper/Live Recovery
仍未完成
```

---

# 五十九、完整测试命令

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

uv run pytest tests/runtime/events -q
uv run pytest tests/event -q
uv run pytest tests/execution -q
uv run pytest tests/order -q
uv run pytest tests/risk -q
uv run pytest tests/runtime/recovery -q
uv run pytest tests/runtime/checkpoint -q

uv run pytest tests/integration/test_engine_event_gate_fresh_start.py -q
uv run pytest tests/integration/test_engine_recovery_bootstrap_event_discard.py -q
uv run pytest tests/integration/test_engine_recovery_direct_event_suppression.py -q
uv run pytest tests/integration/test_engine_recovery_continuation_event_delivery.py -q
uv run pytest tests/integration/test_engine_recovery_event_gate_failure.py -q

uv run pytest tests/integration/test_engine_recovery_same_bar_continuation.py -q
uv run pytest tests/integration/test_engine_recovery_multi_boundary_tail.py -q
uv run pytest tests/integration/test_engine_recovery_multiple_continuations.py -q
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

# 六十、完成标准

只有全部满足才能声明 PR4.2.2c 完成：

1. EventBus 保持纯 Queue/Dispatch 组件；
2. EventBus 不依赖 Runtime；
3. EventBus 不依赖 Recovery；
4. Runtime 有唯一 Event Router；
5. Router 有正式 Recovery Gate；
6. Gate 初始为 BOOTSTRAPPING；
7. Bootstrap Direct Event 不直接进入 EventBus；
8. Fresh Bootstrap Event 按 FIFO Stage；
9. Fresh Runtime OPEN 后 Flush；
10. Recovery 开始时丢弃 Bootstrap Staging；
11. Recovery Bootstrap Event 不补发；
12. Recovery Historical Direct Event被 Suppress；
13. Finalizing Direct Event被 Suppress；
14. Suppressed Event 永不补发；
15. Recovery Continuation Event写入 Durable Outbox；
16. Continuation Event Finalization 前不可观察；
17. Continuation Event OPEN 后交付；
18. Durable Route 在非 OPEN 阶段被拒绝；
19. Lifecycle Route 在非 OPEN 阶段被拒绝；
20. Order Publisher 不持有 EventBus；
21. Risk Publisher 不持有 EventBus；
22. Execution Direct Publisher 不持有 EventBus；
23. Execution Outbox Publisher 不持有 EventBus；
24. MarketData 不直接调用 EventBus；
25. Runtime Lifecycle 不直接调用 EventBus；
26. Account/Position/Ledger Direct Batch经过 Router；
27. Runtime 对外只暴露 Subscription View；
28. 外部无法通过 Runtime 绕过 Gate；
29. Gate Diagnostics 有界；
30. Gate 不进入 Checkpoint；
31. Gate 不进入 Business Projection；
32. Gate 不进入 Result Fingerprint；
33. Gate 不改变 Transaction 状态；
34. Gate 不改变 Projection；
35. Gate 不改变 Exact Boundary；
36. Gate 不改变 Authority Validation；
37. Gate 不改变 Checkpoint Schema；
38. Finalization Failure 后 Gate FAILED；
39. Finalization Failure 不发布 Direct Event；
40. Finalization Failure 不交付 Outbox；
41. Finalization Failure 不发布 RUNTIME_STARTED；
42. Fresh Start Event 顺序稳定；
43. Historical Direct Event不重复；
44. Same-Bar Continuation 继续通过；
45. A→B→C Restart 继续通过；
46. Business Projection 与 Baseline 相等；
47. Result Fingerprint 相等；
48. Orders、Trades、Signals 相等；
49. Artifact Manifest 相等；
50. Direct Event Stream 不被错误要求全量等价；
51. Outbox 仍为 at-least-once；
52. 不声称 exactly-once；
53. 不新增 Direct Event Persistence；
54. 不新增 Internal EventBus；
55. 不实现 Partial / Multi-Fill；
56. 不实现 SELL / CLOSE；
57. 不实现 Paper / Live Recovery；
58. Ruff、Mypy、Pytest 和 Architecture Gate 全部通过。

---

# 六十一、禁止实现

以下任一情况视为任务失败：

```text
在 OnlyEventBus.publish() 内读取 Runtime State
在 EventBus 内实现 Recovery Gate
在 Recovery 时关闭整个 EventBus
阻断 MarketData Pipeline
阻断 Strategy Dispatch
阻断 Execution Projection
跳过 Recovery on_recovery_complete()
将 Historical Direct Event暂存后补发
将 Durable Outbox Event当作历史 Event丢弃
在非 OPEN 阶段 Stage Durable Event
在 Recovery 期间发布 RUNTIME_STARTED
让 Order Publisher继续持有 EventBus
让 Risk Publisher继续持有 EventBus
让 Execution Direct Publisher继续持有 EventBus
让 Execution Outbox Publisher继续持有 EventBus
让 Runtime 对外暴露 publish()
增加第二个 EventBus 作为 Internal EventBus
把 Gate 加入 Checkpoint Participant
把 Gate Counter 加入 Business Fingerprint
把 Direct Event持久化到新表
宣称 Direct Event exactly-once
宣称 Outbox exactly-once
修改 Recovery Outcome
修改 Finalizer Phase
修改 Cluster Recovery Lifecycle
修改 Checkpoint Schema
修改 Causal Replay
实现 Partial / Multi-Fill
实现 SELL / CLOSE
实现 Paper / Live Recovery
通过测试直接修改 Gate 私有 Phase
通过测试直接修改 EventBus 私有 Queue
增加生产故障开关
```

---

# 六十二、最终交付报告

完成后输出结构化报告。

## 1. 修改前问题

说明：

```text
ExecutionProcessor replay suppression
为何不能覆盖全部 Direct Event
```

## 2. Event Route

列出：

* External Direct；
* Durable Outbox；
* Lifecycle。

## 3. Gate State Machine

说明：

```text
BOOTSTRAPPING
→ RECOVERING / READY_BLOCKED
→ FINALIZING
→ READY_BLOCKED
→ OPEN
→ FAILED / CLOSED
```

## 4. Bootstrap Staging

说明：

* Fresh 为什么 Flush；
* Recovery 为什么 Discard；
* 为什么不能持久化。

## 5. Publisher Migration

分别列出：

* Execution Direct；
* Execution Outbox；
* Order；
* Risk；
* MarketData；
* Manager Direct Batch；
* Runtime Lifecycle。

## 6. Runtime Lifecycle

说明：

* initialize；
* recover；
* finalize；
* ready；
* start；
* fail；
* close。

## 7. Direct Event Contract

明确：

```text
Recovery 不重发 Direct Event
Direct Event 仍可能因故障丢失
```

## 8. Durable Event Contract

明确：

```text
Continuation Event 保留于 Outbox
OPEN 后 at-least-once 交付
```

## 9. EventBus Public Boundary

说明 Runtime 为什么只暴露 Subscription View。

## 10. 测试结果

列出所有真实执行命令和结果。

## 11. 删除的绕过路径

列出所有被删除的直接 EventBus Publish。

## 12. 剩余边界

明确仍未实现：

* Exactly-once；
* Durable Direct Journal；
* Delivery Watermark；
* Subscriber ACK；
* Event Replay API；
* Paper/Live Recovery；
* Partial/Multi-Fill；
* SELL/CLOSE。

---

# 六十三、最终架构结论

完成前：

```text
Order ────────────────┐
Risk ─────────────────┤
MarketData ───────────┤
Execution Direct ─────┤
Execution Outbox ─────┼──→ EventBus
Runtime Lifecycle ────┘
```

完成后：

```text
Order ────────────────┐
Risk ─────────────────┤
MarketData ───────────┤
Execution Direct ─────┤
Manager Direct Batch ─┤
Runtime Lifecycle ────┼──→ Runtime Event Router
                      │           │
Execution Outbox ─────┘           ▼
                           Recovery Event Gate
                                  │
                 ┌────────────────┼────────────────┐
                 │                │                │
               STAGE          SUPPRESS          PUBLISH
                 │                │                │
       Fresh Bootstrap FIFO   Recovery Drop     EventBus
```

最终必须证明：

> OnlyAlpha 在恢复期间可以完整重建 MarketData、Strategy、Order、Risk、Execution、Account、Position、Ledger 和 Result 状态，同时不会再次向外部观察者发布历史非持久 Direct Event；恢复期间新产生的 Continuation Transaction Event 会被持久化到 Durable Outbox，并且只有在 Post-Recovery Authority Validation 和 Checkpoint Durable Verification 全部成功、Runtime 正式 OPEN 后才交付。
