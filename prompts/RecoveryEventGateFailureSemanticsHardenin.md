# OnlyAlpha PR4.2.2c 测试加固：Recovery Event Gate Failure Semantics Hardening

## 一、任务背景

请基于 OnlyAlpha 当前 `master` 分支的真实源码、测试、ADR 和文档，完成一个小范围测试加固提交：

```text
PR4.2.2c Test Hardening
Recovery Event Gate Failure Semantics Hardening
```

当前预期基线提交为：

```text
1cccfc40ed912d1d2b977919f4e2e16cd6c48ddd
Feat: Unified Recovery Event Gate 与外部事件恢复门禁
```

开始工作前必须检查实际 `master`。如果仓库已经更新，以实际代码为准，并在审计报告中说明差异。

当前 PR4.2.2c 已经实现：

```text
Runtime Event Router
Recovery Event Gate
Bootstrap Direct Event Staging
Recovery Bootstrap Event Discard
Historical Direct Event Suppression
Durable Outbox OPEN 后交付
Lifecycle Route
Runtime EventBus 只读 Subscription View
```

本任务不再增加 Event Gate 功能，而是：

```text
冻结失败语义
+
补齐故障矩阵
+
覆盖所有主要 Direct Event 路径
+
明确 OPEN 前后事件清理行为
```

---

# 二、核心目标

本任务必须回答并通过测试固定以下问题：

1. Recovery Finalization 各阶段失败时，是否完全禁止外部事件交付；
2. MarketData、Order、Risk、Account、Position、Allocation、Ledger、Fee、Settlement、Valuation 等事件是否全部经过 Runtime Event Router；
3. Historical Direct Event 是否在 Recovery 和 Finalizing 阶段被永久抑制；
4. Bootstrap Event 在 Fresh Runtime 和 Recovery Runtime 中是否行为不同；
5. Router Flush 中途失败时是否可能产生未定义的部分入队；
6. Runtime 已经 OPEN 后发生 Outbox、Cluster Resume 或 Lifecycle Failure 时，已接受事件如何处理；
7. Runtime FAILED 后执行 Stop/Close 是否可能意外 Dispatch 或重复 Dispatch；
8. Engine A→B→C Restart 是否继续保持业务结果等价；
9. 当前 Outbox 的 `published` 是否仍只表示 EventBus 接受，而不是 Subscriber ACK；
10. 是否避免错误宣称 exactly-once。

---

# 三、任务边界

## 3.1 必须完成

本任务必须完成：

1. 现有 PR4.2.2c 测试覆盖审计；
2. Recovery Finalization Failure 测试矩阵；
3. Direct Event 分类抑制测试；
4. Runtime Event Router 故障测试；
5. Runtime Start Failure 测试矩阵；
6. Runtime FAILED 后 Stop/Close Cleanup 测试；
7. Engine A→B→C Event Gate 断言；
8. Architecture Gate 补强；
9. ADR 0048 失败语义补充；
10. 完整 Ruff、Mypy、Pytest 门禁。

## 3.2 默认不修改生产代码

优先只修改：

```text
tests/
docs/
```

只有红色测试证明存在真实缺陷时，才允许局部修改：

```text
src/onlyalpha/event/bus.py
src/onlyalpha/runtime/events/router.py
src/onlyalpha/runtime/runtime.py
```

## 3.3 明确禁止

本任务不得：

```text
增加 Gate Phase
增加 Event Route
修改 Gate 状态转换
修改 Recovery Outcome
修改 Recovery Finalizer Phase
修改 Cluster Recovery Lifecycle
修改 Checkpoint Schema
修改 Transaction Store Schema
修改 Durable Outbox 数据模型
修改 Execution Planner
实现 Partial / Multi-Fill
实现 SELL / CLOSE
实现 Paper / Live Recovery
实现 Direct Durable Journal
实现 Delivery Watermark
实现 Subscriber ACK
实现 Exactly-once
引入远程 EventBus
引入 Kafka、Redis Stream、WebSocket 或 SSE
```

---

# 四、开始前必须完成的审计

开始修改前重新阅读至少以下文件：

```text
src/onlyalpha/event/bus.py
src/onlyalpha/event/model.py
src/onlyalpha/event/ports.py
src/onlyalpha/event/subscription_view.py

src/onlyalpha/runtime/events/gate.py
src/onlyalpha/runtime/events/router.py
src/onlyalpha/runtime/runtime.py
src/onlyalpha/runtime/backtest/runtime.py

src/onlyalpha/runtime/recovery/finalizer.py
src/onlyalpha/runtime/recovery/orchestrator.py
src/onlyalpha/runtime/recovery/validation.py

src/onlyalpha/execution/delivery.py
src/onlyalpha/execution/processor.py
src/onlyalpha/execution/commit_coordinator.py
src/onlyalpha/execution/persistence_ports.py

src/onlyalpha/order/publisher.py
src/onlyalpha/risk/publisher.py

tests/runtime/events/
tests/runtime/recovery/
tests/runtime/checkpoint/
tests/integration/
tests/architecture/

docs/adr/0048-unified-recovery-event-gate.md
docs/execution_runtime_recovery.md
docs/roadmap.md
```

重点搜索：

```bash
rg "event_router"
rg "event_gate_snapshot"
rg "OnlyRuntimeEventGatePhase"
rg "OnlyRuntimeEventDisposition"

rg "publish_direct"
rg "publish_direct_many"
rg "publish_durable"
rg "publish_lifecycle"

rg "event_bus.publish"
rg "owned_bus.publish"
rg "owned_bus.publish_many"
rg "event_bus.drain"

rg "RUNTIME_STARTED"
rg "_drain_execution_outbox"
rg "resume_recovered_all"
rg "start_all"
rg "fail_recovery_finalization_all"

rg "OnlyAfterCommitCheckpointStore"
rg "OnlyValidationMismatchStore"
rg "write_checkpoint"
rg "verify_durable"

rg "suppressed_direct_count"
rg "discarded_bootstrap_count"
rg "last_suppressed_events"
```

---

# 五、预实现审计文档

新增：

```text
docs/reports/pr4_2_2c_event_gate_test_hardening_audit.md
```

审计必须回答：

1. 当前 Gate 已有哪些单元测试；
2. 当前 Router 已有哪些单元测试；
3. Fresh Bootstrap 已覆盖哪些行为；
4. Recovery Bootstrap Discard 已覆盖哪些行为；
5. Historical Direct Event Suppression 当前只检查了什么；
6. 哪些 Direct Event 类型没有单独验证；
7. 当前有哪些 Finalization Failure 测试；
8. 哪些 Finalization Phase 失败没有 Event Gate 断言；
9. Router `open()` 当前如何 Flush Staged Event；
10. Router Flush 是否具有批量原子性；
11. EventBus `publish_many()` 是否具有批量原子性；
12. EventBus Queue 在 Runtime Start 期间何时被 Drain；
13. Plugin Start Failure 是否发生在 Router OPEN 前；
14. Outbox Failure 是否发生在 Router OPEN 后；
15. Cluster Resume Failure 是否发生在 Router OPEN 后；
16. `RUNTIME_STARTED` 在什么条件下发布；
17. Runtime FAILED 后 `stop()` 是否 Drain EventBus；
18. EventBus `close()` 是否 Drain Queue；
19. Outbox Record 的 `published` 当前表示什么；
20. 当前是否存在 Subscriber ACK；
21. 当前是否存在 Event Delivery Watermark；
22. 当前 Direct Event 是否可以保证不重复和不丢失；
23. OPEN 前 Failure 与 OPEN 后 Failure 应采用什么不同合同；
24. 哪些测试支持类可以复用；
25. 是否需要局部生产修复。

完成审计前不得修改生产代码。

---

# 六、正式失败合同

本任务必须通过测试固定三层合同。

## 6.1 合同 A：OPEN 前失败完全静默

适用于：

```text
Recovery Replay Failure
Recovery Completion Callback Failure
Quiescence Failure
Authority Validation Failure
Checkpoint Capture Failure
Checkpoint Pre-Write Failure
Checkpoint Verify Failure
Plugin Start Failure
Router Open 之前的失败
```

必须满足：

```text
Gate == FAILED
Runtime == FAILED
相关 Cluster == FAILED 或未启动
EventBus dispatch_results == ()
EventBus pending_count == 0
RUNTIME_STARTED 不存在
Durable Outbox 不交付
Cluster 不 Start/Resume
Bootstrap Staging 不 Flush
Historical Direct Event 不补发
```

## 6.2 合同 B：Recovery Direct Event 永久抑制

Recovery 或 Finalizing 阶段产生的 Direct Event：

```text
→ SUPPRESSED
→ 不进入 EventBus
→ 不进入 Staging
→ 不在 OPEN 后补发
```

同时业务状态恢复必须继续完成。

## 6.3 合同 C：OPEN 后失败不等于“从未开放”

一旦 `router.open()` 成功：

```text
Bootstrap Event 已获得进入 EventBus 的资格
Durable Outbox 可以开始投递
```

后续 Outbox 或 Cluster Resume 失败时：

```text
Runtime 必须 FAILED
Gate 必须 FAILED
RUNTIME_STARTED 不得发布
Cluster 不得错误标记为 RUNNING
```

但已经被 EventBus 接受的事件不能被错误描述为“从未发布”。

本任务不得通过新增 ACK 或 Exactly-once 机制改变这一事实。

---

# 七、工作包一：Finalization Failure 测试矩阵

新增：

```text
tests/integration/test_engine_recovery_event_gate_finalization_failures.py
```

建议复用和扩展：

```text
tests/integration/recovery_finalization_support.py
```

## 7.1 Authority Validation Failure

复用现有 Validation Mismatch Store。

必须断言：

```python
assert result.status == "FAILED"
assert runtime.event_gate_snapshot.phase is OnlyRuntimeEventGatePhase.FAILED
assert runtime.event_bus.dispatch_results == ()
assert runtime.event_bus.pending_count() == 0
assert no_event_type(runtime, "RUNTIME_STARTED")
assert all(not record.published for record in outbox_records)
assert cluster_is_failed_or_not_resumed(runtime)
```

还必须确认：

* 原 Checkpoint 保留；
* 没有产生新的 Verified Post-Recovery Checkpoint；
* Suppressed Event 没有被 Flush。

## 7.2 Checkpoint Capture Failure

通过测试 Checkpoint Participant 注入：

```python
class OnlyPostRecoveryCaptureFailureParticipant:
    def capture_checkpoint(self) -> object:
        raise RuntimeError("TEST_POST_RECOVERY_CAPTURE_FAILURE")
```

要求：

* 只在 Engine B 的 Post-Recovery Capture 阶段失败；
* 不影响 Engine A 创建基础恢复状态；
* 不增加生产故障开关。

断言：

```text
Finalizer FAILED
Gate FAILED
Runtime FAILED
No Dispatch
No Outbox Delivery
No Cluster Resume
Old Checkpoint Preserved
```

## 7.3 Checkpoint Pre-Write Failure

新增 Test Store Wrapper：

```python
class OnlyBeforeWriteCheckpointStore:
    def write_checkpoint(self, checkpoint, *, retain_last):
        raise RuntimeError("TEST_POST_RECOVERY_PRE_WRITE")
```

断言：

* 新 Checkpoint 没有提交；
* 原 Checkpoint 保留；
* Gate FAILED；
* EventBus 静默；
* Outbox 未交付；
* Cluster 未 Resume。

## 7.4 After-Commit Failure

复用已有 Commit-Then-Raise Store。

断言：

```text
新 Checkpoint 已持久化
当前 Engine FAILED
Gate FAILED
No RUNTIME_STARTED
当前 Engine 不交付 Pending Outbox
当前 Engine 不 Resume Cluster
Engine C 可以继续恢复
```

## 7.5 Durable Read-Back Verify Failure

新增 Test Store Wrapper：

```python
class OnlyCheckpointReadBackMismatchStore:
    def write_checkpoint(...):
        delegate.write_checkpoint(...)

    def latest_checkpoint(...):
        if post_recovery_write_completed:
            return altered_read_view
        return delegate.latest_checkpoint(...)
```

要求：

* 修改测试读取视图，不修改真实持久数据；
* Verify 失败；
* Gate FAILED；
* Runtime FAILED；
* Outbox 未交付；
* Cluster 未 Resume；
* 下一 Engine 可根据真实 Store 状态继续。

## 7.6 Quiescence Failure

至少覆盖：

```text
Broker Inbound Queue 非空
MarketData Inbound Queue 非空
EventBus Pending 非零
```

每种情况断言：

```text
Gate FAILED
Finalizer 停止在 QUIESCENCE_CHECK
Validator 未执行
Checkpoint Capture 未执行
No Dispatch
No Outbox Delivery
```

---

# 八、工作包二：逐类 Direct Event 抑制

新增：

```text
tests/integration/test_engine_recovery_direct_event_categories.py
```

## 8.1 稳定观察投影

定义测试专用结构：

```python
@dataclass(frozen=True, slots=True)
class OnlyObservedEventProjection:
    event_type: str
    source: str
    runtime_id: str
    cluster_id: str | None
    sequence: int
    payload_hash: str
```

Payload Hash 使用：

```text
稳定 JSON 排序
稳定 Decimal/String 序列化
SHA-256
```

不要将以下字段作为主要业务比较键：

```text
随机 event_id
当前 Engine 创建时间
不稳定 ts_init
对象 repr
```

## 8.2 必须检查的事件族

以仓库真实 Event Type 为准，至少覆盖：

### MarketData

```text
MarketData Applied
Bar Accepted
Gap 或 Audit Fact
```

### Order

```text
Order Submitted
Order Accepted
Order Filled
```

### Risk

```text
Risk Accepted
Risk Reservation Created
Risk Reservation Consumed
```

### Account

```text
Account Updated
Cash Reservation Created
Cash Reservation Consumed
```

### Position / Allocation

```text
Position Opened/Updated
Allocation Updated
```

### Strategy Ledger

```text
Ledger Updated
Strategy Cash Reservation Updated
```

### Fee / Settlement / Valuation

选择当前正式 Transaction 实际产生的事件。

## 8.3 每类测试必须证明

```text
业务正式链路真实产生该事件
Gate suppressed_direct_count 增加
目标 Event 出现在 Suppressed Diagnostic 或专门 Test Observer 中
目标 Event 不出现在 EventBus Dispatch Result
Runtime OPEN 后仍不出现
对应 Authority 恢复正确
Post-Recovery Validation 通过
Business Projection 与 Baseline 相等
```

## 8.4 不依赖 16 条 Suppressed Sample 覆盖全部事件

当前 Sample 是有界诊断。

测试应：

* 每个场景只聚焦一至两类 Event；
* 不用一个大场景要求全部事件同时留在 Sample；
* Counter 用于总量判断；
* 目标事件使用小场景固定。

不得为了测试直接调用 Router 产生业务事件。

---

# 九、工作包三：Router Failure Semantics

新增或扩展：

```text
tests/runtime/events/test_runtime_event_router_failure_semantics.py
```

## 9.1 Scope 错误发生在 Gate 前

构造三条 Batch Event，其中最后一条 Runtime Scope 错误。

断言：

```text
整批未 Stage
整批未 Publish
Gate Counter 不变
Staging 不变
EventBus Queue 不变
```

## 9.2 Empty Batch

在以下 Phase 分别测试：

```text
BOOTSTRAPPING
RECOVERING
FINALIZING
READY_BLOCKED
OPEN
FAILED
```

要求：

```text
attempted == 0
published == 0
staged == 0
suppressed == 0
rejected == 0
不改变 Phase
不改变 Counter
```

如果 FAILED Phase 的空 Batch 当前返回 REJECTED，应根据现有正式合同记录并测试，不要随意改变语义。

## 9.3 Open Flush 第一个 Event 失败

使用测试 EventBus 或测试 Publication Transport：

```python
class OnlyFailNthPublishEventBus:
    fail_on = 1
```

断言：

```text
Gate FAILED
Router 不可重新 OPEN
Outbox 未开始
Cluster 未启动
No RUNTIME_STARTED
```

## 9.4 Open Flush 中间 Event 失败

例如三个 Staged Event，在第二条失败。

首先写红色测试，记录当前实际行为：

```text
第一条是否已进入 EventBus
第二条失败后 Gate 是否 FAILED
第三条是否未尝试
```

随后决定是否需要微型生产修复。

---

# 十、可选微型修复：EventBus 原子批量入队

只有上述红色测试证明 Bootstrap Flush 存在不可接受的部分入队时，才允许实现。

建议在 EventBus 增加通用传输能力：

```python
def publish_many_atomic(
    self,
    events: tuple[OnlyEvent, ...],
) -> int:
    ...
```

必须满足：

```text
验证 EventBus 未关闭
预检查全部 Scope
预检查 Batch Capacity
全部 Append
或全部不 Append
```

要求：

* EventBus 仍不知道 Runtime；
* EventBus 仍不知道 Recovery；
* 不导入 Gate；
* 不导入 Router；
* 不改变单条 `publish()`；
* 不改变业务事件语义；
* 不修改 Drop Low Priority 的已有语义，除非明确禁止 Atomic API 在该 Policy 下使用；
* Router `open()` 使用 Atomic API Flush Bootstrap Batch。

建议合同：

```text
REJECT / FAIL_RUNTIME Policy
→ 支持 Atomic Batch

DROP_LOW_PRIORITY Policy
→ 要么提供明确原子替换算法
→ 要么 Atomic API 明确拒绝该 Policy
```

不得实现模糊的半原子行为。

---

# 十一、工作包四：Runtime Start Failure 矩阵

新增：

```text
tests/integration/test_engine_event_gate_start_failures.py
```

## 11.1 Plugin Start Failure

通过测试 Plugin Resource：

```python
class OnlyStartFailurePluginResource:
    def start(self) -> None:
        raise RuntimeError("TEST_PLUGIN_START_FAILURE")
```

断言：

```text
Router 尚未 OPEN
Gate FAILED
Bootstrap Staged Event 未 Dispatch
EventBus Queue 为空
No Outbox Attempt
No Cluster Start/Resume
No RUNTIME_STARTED
Runtime FAILED
```

## 11.2 Router Open Failure

通过 Test EventBus 或 Atomic Batch Failure 注入。

断言：

```text
Gate FAILED
Runtime FAILED
No Outbox Attempt
No Cluster Start/Resume
No RUNTIME_STARTED
```

采用 Atomic Batch 后还必须断言 EventBus Queue 为空。

## 11.3 Outbox 第一条失败

构造 Pending Outbox，并让第一条 Durable Publication 失败。

断言：

```text
Gate FAILED
Runtime FAILED
No Cluster Resume
No RUNTIME_STARTED
第一条 Outbox mark_failed 或保持可重试
后续 Outbox 未尝试
remaining 正确
```

## 11.4 Outbox 中间失败

构造至少三条 Pending Outbox：

```text
Record 1 → PUBLISHED
Record 2 → FAILURE
Record 3 → NOT ATTEMPTED
```

断言：

```text
Record 1 marked published
Record 2 mark_failed 或 pending，符合当前 Store 合同
Record 3 untouched
stopped_on_error == True
remaining 正确
Cluster 不 Resume
No RUNTIME_STARTED
Gate FAILED
Runtime FAILED
```

明确记录：

> Outbox 的 `published` 当前表示 Event 已被 EventBus 接受，不表示 Subscriber 已处理。

## 11.5 Cluster Resume Failure

通过正式 Test Cluster Callback：

```python
def on_resume(self) -> None:
    raise RuntimeError("TEST_CLUSTER_RESUME_FAILURE")
```

断言：

```text
Router 已 OPEN
Outbox 已完成或为空
Cluster Resume 失败
Runtime FAILED
Gate FAILED
No RUNTIME_STARTED
Cluster 不得处于 RUNNING
```

同时检查 EventBus Queue 和 Dispatch Result，固定 OPEN 后 Failure 合同。

## 11.6 Fresh Cluster Start Failure

构造 Fresh Runtime Cluster `on_start()` 失败。

断言：

```text
Bootstrap Event 已通过 Router OPEN 进入合法发布窗口
Cluster Start 失败
Runtime FAILED
Gate FAILED
No RUNTIME_STARTED
```

必须区分该行为与 Plugin Start Failure。

## 11.7 Lifecycle Publication Failure

让 `RUNTIME_STARTED` 发布时发生 EventBus Capacity 或 Publication Error。

断言：

```text
Cluster 已 Start/Resume
Runtime 最终 FAILED
Gate FAILED
RUNTIME_STARTED 不在 Dispatch Result
Plugin 和 Cluster Cleanup 执行
原始 Failure 被保留
```

---

# 十二、工作包五：FAILED 后 Stop/Close 行为

新增：

```text
tests/integration/test_engine_event_gate_failed_cleanup.py
```

## 12.1 Finalization Failure 后 Close

要求：

```text
EventBus Queue == 0
Close 不产生 Event Dispatch
Gate FAILED → CLOSED
重复 Close 幂等
```

## 12.2 Plugin Start Failure 后 Close

要求完全静默：

```text
No Dispatch
No RUNTIME_STARTED
No Outbox Delivery
Gate 最终 CLOSED
```

## 12.3 Router Open Failure 后 Close

若实现 Atomic Batch：

```text
Queue == 0
No Dispatch
```

若暂不实现 Atomic Batch，则必须明确并测试已入队前缀的处理方式。

## 12.4 Outbox Failure 后 Stop/Close

必须固定：

```text
已被 EventBus 接受的成功前缀是否在 Cleanup 中 Drain
失败 Record 是否不会被错误标记为 Published
未尝试 Record 是否保持 Pending
```

## 12.5 Cluster Resume Failure 后 Stop/Close

推荐正式合同：

```text
OPEN 前 Failure
→ 完全静默

OPEN 后 Failure
→ 已被 EventBus 接受的 Event 可以在 Cleanup Drain
→ 不得产生 RUNTIME_STARTED
→ 不得重复 Dispatch
```

原因：

* OPEN 已是正式发布边界；
* Direct Event 是 Best-effort；
* Outbox 是 at-least-once；
* 没有 Subscriber ACK。

## 12.6 重复 Cleanup

执行：

```python
engine.stop()
engine.stop()
engine.close()
engine.close()
```

或根据 Engine 当前公开生命周期使用等价调用。

断言：

```text
Gate 最终 CLOSED
同一 Event 不重复 Dispatch
Outbox 状态不重复变化
Plugin Cleanup 不重复破坏状态
首个异常保持为主错误
```

---

# 十三、工作包六：A→B→C 测试扩展

扩展现有三阶段 Restart 测试，或新增：

```text
tests/integration/test_engine_recovery_event_gate_three_stage_restart.py
```

## Engine A

```text
执行到 Transaction Tail
→ Crash
```

记录：

* 已提交 Transaction；
* Pending Outbox；
* Canonical Business Projection；
* 可观察 Direct Event 投影。

## Engine B

```text
Recovery
→ Post-Recovery Checkpoint Commit
→ After-Commit Exception
```

必须断言：

```text
Gate FAILED
No RUNTIME_STARTED
No Historical Direct Event Dispatch
No Pending Outbox Delivery
No Cluster Resume
Committed Checkpoint 保留
```

## Engine C

```text
从 Engine B Checkpoint 恢复
→ READY_BLOCKED
→ OPEN
→ Outbox Delivery
→ Cluster Resume
→ RUNTIME_STARTED
```

必须断言：

```text
Gate OPEN
Outbox 已投递
RUNTIME_STARTED 最后发布
Suppressed Historical Direct Event 未补发
```

最终继续比较：

```text
Canonical Business Projection
Result Fingerprint
Orders
Trades
Positions
Allocations
Account
Strategy Ledger
Signals
Artifact Manifest
```

禁止比较完整 Direct Event Stream 与无故障 Baseline 完全相等。

---

# 十四、测试支持代码

建议新增：

```text
tests/integration/recovery_event_gate_hardening_support.py
```

包含：

```python
class OnlyBeforeWriteCheckpointStore
class OnlyReadBackMismatchCheckpointStore
class OnlyPostRecoveryCaptureFailureParticipant
class OnlyFailNthPublishEventBus
class OnlyFailNthDurablePublicationPort
class OnlyStartFailurePluginResource
class OnlyStartFailureCluster
class OnlyResumeFailureCluster
class OnlyObservedEventRecorder
```

要求：

1. 全部位于测试目录；
2. 通过正式 Port、Store、Plugin、Participant 和 Cluster Callback 注入；
3. 不修改 Runtime 私有 State；
4. 不修改 Gate 私有 Phase；
5. 不修改 EventBus 私有 Queue；
6. 不修改 Manager 私有容器；
7. 不增加生产 Fault Switch；
8. 不依赖 `object.__setattr__()` 篡改生产对象；
9. 不直接调用 Router 私有方法；
10. 不绕过 Runtime Lifecycle。

---

# 十五、Architecture Gate 补强

更新：

```text
tests/architecture/test_recovery_event_gate_architecture.py
```

至少增加：

1. 新测试支持代码不进入 `src/`；
2. EventBus Atomic Batch 如存在，不导入 Runtime；
3. EventBus Atomic Batch 如存在，不导入 Recovery；
4. EventBus Atomic Batch 不读取 Gate Phase；
5. Router 仍是唯一业务 EventBus Writer；
6. Runtime 业务代码不重新出现 `event_bus.publish()`；
7. Order Publisher 不持有 EventBus；
8. Risk Publisher 不持有 EventBus；
9. Execution Direct Publisher 不持有 EventBus；
10. Execution Outbox Publisher 不持有 EventBus；
11. Gate 不成为 Checkpoint Participant；
12. Gate Diagnostic 不进入 Business Projection；
13. Gate Diagnostic 不进入 Result Fingerprint；
14. Finalizer 不投递 Outbox；
15. Outbox 仍只由 Runtime Start 调度；
16. 不新增 Event Delivery ACK；
17. 不新增 Exactly-once 状态；
18. 不新增 Direct Event Persistence 表；
19. 不新增 Internal EventBus；
20. 不修改 Recovery Outcome；
21. 不修改 Checkpoint Schema；
22. 不实现 Partial/Multi-Fill；
23. 不实现 SELL/CLOSE。

源码字符串测试只能作为辅助，核心行为必须由运行测试证明。

---

# 十六、文档更新

不新增 ADR。

更新：

```text
docs/adr/0048-unified-recovery-event-gate.md
docs/execution_runtime_recovery.md
docs/roadmap.md
```

ADR 0048 增加“失败边界”章节，明确：

## 16.1 OPEN 前 Failure

```text
完全静默
不 Dispatch
不交付 Outbox
不发布 RUNTIME_STARTED
```

## 16.2 OPEN 后 Failure

```text
已经被 EventBus 接受的 Event 可能在 Cleanup 中被 Drain
但不得产生 RUNTIME_STARTED
不得重复 Dispatch
```

## 16.3 Outbox Published 含义

明确：

```text
Outbox published
=
EventBus 接受成功并完成本地 mark_published
```

不表示：

```text
Subscriber 已确认
远程消费者已处理
Exactly-once
```

## 16.4 Direct Event 合同

明确：

```text
Direct Event 是 Best-effort
Recovery 历史 Direct Event 被抑制
Direct Event 可能在故障窗口丢失
```

## 16.5 不实现的能力

继续明确：

```text
Subscriber ACK
Delivery Watermark
Direct Durable Journal
Exactly-once
Remote EventBus
```

Roadmap 增加：

```text
PR4.2.2c 已通过 Failure Semantics Test Hardening 冻结。
```

不要新增新的 4.2.2d 架构阶段。

---

# 十七、建议文件范围

预期新增或修改：

```text
tests/runtime/events/test_runtime_event_router_failure_semantics.py

tests/integration/recovery_event_gate_hardening_support.py
tests/integration/test_engine_recovery_event_gate_finalization_failures.py
tests/integration/test_engine_recovery_direct_event_categories.py
tests/integration/test_engine_event_gate_start_failures.py
tests/integration/test_engine_event_gate_failed_cleanup.py
tests/integration/test_engine_recovery_event_gate_three_stage_restart.py

tests/architecture/test_recovery_event_gate_architecture.py

docs/reports/pr4_2_2c_event_gate_test_hardening_audit.md
docs/adr/0048-unified-recovery-event-gate.md
docs/execution_runtime_recovery.md
docs/roadmap.md
```

只有测试证明需要时，才允许修改：

```text
src/onlyalpha/event/bus.py
src/onlyalpha/runtime/events/router.py
src/onlyalpha/runtime/runtime.py
```

如果修改其他生产文件，最终报告必须说明不可避免的原因。

---

# 十八、实施顺序

## Step 1

完成预实现审计文档。

## Step 2

补 Finalization Failure 测试矩阵：

```text
Validation
Capture
Pre-Write
After-Commit
Read-Back Verify
Quiescence
```

## Step 3

补 Direct Event 分类抑制测试。

## Step 4

补 Router Failure 单元测试。

重点先写：

```text
Open Flush 中间失败
Batch Scope Mismatch
Empty Batch
```

## Step 5

根据红色测试判断是否需要 `publish_many_atomic()`。

不得先改生产代码再补测试。

## Step 6

补 Runtime Start Failure 测试：

```text
Plugin Start
Router Open
Outbox First Failure
Outbox Prefix Failure
Fresh Cluster Start
Recovered Cluster Resume
Lifecycle Publish
```

## Step 7

补 FAILED 后 Stop/Close 测试。

## Step 8

扩展 A→B→C Restart 测试。

## Step 9

补 Architecture Gate。

## Step 10

更新 ADR 和 Recovery 文档。

## Step 11

运行完整质量门禁。

---

# 十九、必须执行的测试

根据仓库实际测试文件名调整，至少执行：

```bash
uv run pytest tests/runtime/events -q
uv run pytest tests/runtime/recovery -q
uv run pytest tests/runtime/checkpoint -q

uv run pytest tests/integration/test_engine_event_gate_fresh_start.py -q
uv run pytest tests/integration/test_engine_recovery_bootstrap_event_discard.py -q
uv run pytest tests/integration/test_engine_recovery_direct_event_suppression.py -q
uv run pytest tests/integration/test_engine_recovery_continuation_event_delivery.py -q

uv run pytest tests/integration/test_engine_recovery_event_gate_finalization_failures.py -q
uv run pytest tests/integration/test_engine_recovery_direct_event_categories.py -q
uv run pytest tests/integration/test_engine_event_gate_start_failures.py -q
uv run pytest tests/integration/test_engine_event_gate_failed_cleanup.py -q
uv run pytest tests/integration/test_engine_recovery_event_gate_three_stage_restart.py -q

uv run pytest tests/integration/test_engine_recovery_same_bar_continuation.py -q
uv run pytest tests/integration/test_engine_recovery_multi_boundary_tail.py -q
uv run pytest tests/integration/test_engine_recovery_multiple_continuations.py -q
uv run pytest tests/integration/test_engine_recovery_finalization.py -q
uv run pytest tests/integration/test_engine_recovery_validation_failure.py -q
uv run pytest tests/integration/test_engine_recovery_checkpoint_after_commit.py -q
uv run pytest tests/integration/test_engine_recovery_three_stage_restart.py -q

uv run pytest tests/architecture/test_recovery_event_gate_architecture.py -q
```

---

# 二十、完整质量门禁

至少执行：

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
uv run pytest tests/runtime/recovery -q
uv run pytest tests/runtime/checkpoint -q
uv run pytest tests/execution -q
uv run pytest tests/order -q
uv run pytest tests/risk -q
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

不得伪造未执行的结果。

---

# 二十一、完成标准

只有全部满足才能声明测试加固完成：

1. Validation Failure 后 Gate FAILED；
2. Capture Failure 后 Gate FAILED；
3. Pre-Write Failure 后 Gate FAILED；
4. After-Commit Failure 后 Gate FAILED；
5. Verify Failure 后 Gate FAILED；
6. Quiescence Failure 后 Gate FAILED；
7. 所有 OPEN 前 Failure 均无 Event Dispatch；
8. 所有 OPEN 前 Failure 均无 RUNTIME_STARTED；
9. 所有 OPEN 前 Failure 均不交付 Outbox；
10. 所有 OPEN 前 Failure 均不 Start/Resume Cluster；
11. MarketData Direct Event 有独立抑制测试；
12. Order Direct Event 有独立抑制测试；
13. Risk Direct Event 有独立抑制测试；
14. Account Direct Event 有独立抑制测试；
15. Position/Allocation Event 有独立抑制测试；
16. Strategy Ledger Event 有独立抑制测试；
17. Fee/Settlement/Valuation Event 有独立抑制测试；
18. Suppressed Event 不在 OPEN 后补发；
19. Batch Scope Failure 不污染 Gate 或 Queue；
20. Empty Batch 行为固定；
21. Router Open Failure 行为固定；
22. Router 中间 Flush Failure 行为固定；
23. 必要时 Bootstrap Flush 使用原子批量入队；
24. Plugin Start Failure 完全静默；
25. Outbox First Failure 行为固定；
26. Outbox Prefix Failure 行为固定；
27. Cluster Start Failure 不发布 RUNTIME_STARTED；
28. Cluster Resume Failure 不发布 RUNTIME_STARTED；
29. Lifecycle Publish Failure 行为固定；
30. OPEN 前与 OPEN 后 Failure 合同明确区分；
31. FAILED 后 Stop/Close 不重复 Dispatch；
32. FAILED 后重复 Close 幂等；
33. A→B→C Business Projection 继续等价；
34. A→B→C Result Fingerprint 继续等价；
35. A→B→C Orders、Trades、Positions、Account、Ledger 相等；
36. Artifact Manifest 继续相等；
37. Gate 不进入 Checkpoint；
38. Gate 不进入 Business Projection；
39. Gate 不进入 Result Fingerprint；
40. Outbox 仍为 at-least-once；
41. 不声称 Subscriber ACK；
42. 不声称 Exactly-once；
43. 不新增 Direct Event Persistence；
44. 不增加 Gate Phase；
45. 不增加 Event Route；
46. 不修改 Recovery Outcome；
47. 不修改 Checkpoint Schema；
48. 不实现 Partial/Multi-Fill；
49. 不实现 SELL/CLOSE；
50. Ruff、Mypy、Pytest 和 Architecture Gate 全部通过。

---

# 二十二、禁止实现

以下任一情况视为任务失败：

```text
为测试增加生产 fault_injection 配置
直接修改 Runtime 私有 State
直接修改 Gate 私有 Phase
直接修改 EventBus 私有 Queue
直接修改 Manager 私有容器
绕过 Runtime Lifecycle
手工调用 Router 私有方法制造 Recovery 状态
在 EventBus 内读取 Runtime State
在 EventBus 内读取 Gate Phase
增加新的 Gate Phase
增加新的 Event Route
增加 Internal EventBus
增加 Direct Event 持久表
增加 Subscriber ACK
增加 Delivery Watermark
增加 Exactly-once 标记
修改 Outbox Schema
修改 Checkpoint Schema
修改 Recovery Outcome
修改 Finalizer Phase
修改 Cluster Recovery State
实现 Partial/Multi-Fill
实现 SELL/CLOSE
实现 Paper/Live Recovery
将完整 Direct Event Stream 与无故障 Baseline 强制等价
将 Outbox published 解释为 Subscriber 已处理
吞掉真实测试失败
伪造质量门禁结果
```

---

# 二十三、最终交付报告

完成后输出结构化报告。

## 1. 基线信息

列出：

```text
实际 master commit
本任务起始 commit
最终 commit
```

## 2. 原有覆盖

说明已有 Fresh、Bootstrap Discard、Suppression、Continuation、Architecture 测试。

## 3. 新增故障矩阵

列出：

```text
Validation
Capture
Pre-Write
After-Commit
Verify
Quiescence
Plugin Start
Router Open
Outbox
Cluster Start/Resume
Lifecycle
Cleanup
```

## 4. OPEN 前失败合同

说明为何完全静默。

## 5. OPEN 后失败合同

说明已接受 Event 的处理方式。

## 6. Direct Event 分类覆盖

逐类列出：

```text
MarketData
Order
Risk
Account
Position
Allocation
Ledger
Fee
Settlement
Valuation
```

## 7. Router Batch 语义

说明：

* 是否存在部分入队；
* 是否新增 Atomic Batch；
* EventBus 基础职责是否保持不变。

## 8. Outbox 语义

明确：

```text
at-least-once
published 表示 EventBus 接受
无 Subscriber ACK
```

## 9. 修改文件

逐文件说明职责。

## 10. 生产代码修改

如果没有修改，明确说明。

如果修改，只说明红色测试暴露的真实问题和最小修复。

## 11. 测试结果

列出真实命令和结果。

## 12. 未实现范围

明确：

```text
Exactly-once
Direct Durable Journal
Delivery Watermark
Subscriber ACK
Partial/Multi-Fill
SELL/CLOSE
Paper/Live Recovery
```

## 13. 下一步

明确：

```text
PR4.2.2c 已冻结
下一步进入 PR4.3 Partial / Multi-Fill Durable Transaction
```

---

# 二十四、最终要求

本任务完成后必须能够证明：

> OnlyAlpha 的 Recovery Event Gate 不仅在正常恢复路径中抑制历史 Direct Event，还在 Validation、Checkpoint、Plugin、Router、Outbox、Cluster Resume 和 Cleanup 等故障窗口中保持明确、可重复、可测试的事件交付合同。

最终状态：

```text
PR4.2.2a
Exact Causal Replay
已冻结

PR4.2.2b
Authority Validation 与 Durable Finalization
已冻结

PR4.2.2c
Unified Recovery Event Gate 与 Failure Semantics
已冻结
```

随后直接进入：

```text
PR4.3
Partial / Multi-Fill Durable Transaction
```
