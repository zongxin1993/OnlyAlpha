# OnlyAlpha PR4.2.2a：Recovery Phase State Machine 与 Exact Replay Boundary

## 一、任务目标

请基于 OnlyAlpha 当前 `master` 分支的真实源码、测试、ADR、README 和 Roadmap，完成：

```text
PR4.2.2a
Recovery Phase State Machine
+
Exact Backtest Replay Boundary
+
Same-Bar Continuation Transaction
```

本任务必须解决 PR4.2.1 之后仍然存在的一个核心边界问题：

```text
持久 Transaction Tail 已全部恢复
≠
当前 MarketData Boundary 已完成
≠
整个 Runtime Recovery 已完成
```

当前实现中，`OnlyExecutionRecoverySession.complete` 主要表示持久 Tail Entry 已全部消费。Recovery Replay 在单条 MarketData Record 返回后，将其解释为 Boundary 完成。

如果最后一笔持久 Tail Transaction 在 Strategy Callback 前完成恢复，而 Strategy 在同一个 Bar 内基于最新 Position、Account 或 Ledger 提交新订单，并进一步产生新的正式 Transaction，当前实现可能因为 Recovery Session 已无 Expected Entry，将该新 Transaction 错误判断为：

```text
RECOVERY_TRANSACTION_MISSING
```

本任务必须建立以下正式语义：

```text
恢复持久 Transaction Tail
→ Tail Resolved
→ 当前 Bar 继续执行
→ 允许同 Bar 产生新的正常 Durable Transaction
→ 完成完整 MarketData Boundary
→ Recovery Replay 才可以停止
```

最终产品链应达到：

```text
Restore Checkpoint
→ Build Persisted Transaction Tail Plan
→ Enter Exact MarketData Replay Boundary
→ Match and resolve persisted Ready / Unprojected Transactions
→ Transition Tail Phase to TAIL_RESOLVED
→ Continue Strategy and Broker execution in the same Bar
→ Commit newly generated continuation Transactions normally
→ Finish Processing Result / Audit / Result Progress / Event Drain
→ Confirm exact Boundary Completion
→ Exit causal replay
→ Existing PR4.2.1 finalization path continues
```

---

# 二、本任务范围

本任务只实现以下内容：

1. Execution Recovery Phase 状态机；
2. Recovery Decision 模型；
3. Tail Resolved 后的新 Transaction 正常 Commit；
4. Continuation Transaction Sequence 验证；
5. Backtest Recovery Boundary Identity；
6. MarketData Boundary 的正式进入和完成；
7. Recovery Replay 只能在完整 Boundary 后停止；
8. Runtime、ExecutionProcessor、Recovery Replay 和 Orchestrator 的接口调整；
9. 对应单元测试、集成测试、架构测试和文档。

本任务明确不实现：

* Unified Recovery Event Gate；
* Post-Recovery Authority Validator；
* Recovery Finalizer；
* Checkpoint Read-back Verify；
* RECOVERED 状态失败清理重构；
* Partial / Multi-Fill 正式 Transaction；
* SELL / CLOSE 正式 Transaction；
* Futures / Margin Transaction；
* Non-Trade Transaction；
* Paper / Live Recovery；
* Exactly-once Outbox；
* Full Broker Reconciliation；
* Schema Migration；
* Distributed Checkpoint。

不要在本 PR 中顺带实现 PR4.2.2b 或 PR4.2.2c。

---

# 三、当前实现基线

开始编码前，必须重新阅读当前 `master`，不得仅依赖本提示词。

当前预期基线已经包含 PR4.2.1：

```text
Stored Prepared + Committed Recovery Record
OnlyExecutionRecoveryPlan
OnlyExecutionRecoverySession
Strict Ready Prefix / Unprojected Suffix
ExecutionProcessor.replay()
Prepared Contract 完整比较
rehydrate_existing()
recover_existing()
Checkpointable Result Progress
Checkpoint Barrier 后移
Cluster RECOVERING / RECOVERED 生命周期
Canonical Business Projection
```

重点检查以下文件和符号：

```text
src/onlyalpha/execution/causal_recovery.py
src/onlyalpha/execution/processor.py
src/onlyalpha/execution/commit_coordinator.py
src/onlyalpha/runtime/backtest/recovery_replay.py
src/onlyalpha/runtime/backtest/runtime.py
src/onlyalpha/runtime/backtest/result_progress.py
src/onlyalpha/runtime/recovery/orchestrator.py
src/onlyalpha/data/processor.py
src/onlyalpha/cluster/manager.py
```

重点搜索：

```bash
rg "OnlyExecutionRecoverySession"
rg "require_expected"
rg "complete_boundary"
rg "boundary_complete"
rg "session.complete"
rg "_execution_recovery_session"
rg "execution_processor.replay"
rg "OnlyBacktestRecoveryReplayService"
rg "after_market_processing"
rg "_checkpoint_barrier"
rg "COMMITTED_AND_PROJECTED"
rg "RECOVERY_TRANSACTION_MISSING"
```

---

# 四、编码前强制审计

先新增：

```text
docs/reports/pr4_2_2a_recovery_phase_boundary_pre_implementation_audit.md
```

审计必须回答：

1. `OnlyExecutionRecoverySession.complete` 当前准确表示什么；
2. `boundary_complete` 当前由谁设置；
3. Recovery Replay 当前在哪个调用点决定停止；
4. 一个 `HistoricalReplayService.run(single_record)` 内会执行哪些阶段；
5. Broker 在 Strategy 前和 Strategy 后分别何时产生 Update；
6. 当前 Virtual Broker 是否能够在 Strategy 提交订单后的同一个 Bar 成交；
7. 如果默认 Broker 不能同 Bar 成交，测试应如何通过测试专用 Broker Driver 构造该场景；
8. 当前 Recovery Session 活跃时，所有 Broker Update 如何进入 `ExecutionProcessor.replay()`；
9. 当前 Tail Entry 全部消费后，再出现正式 Trade 会走哪条错误路径；
10. Coordinator 在 Recovery 期间是否能够正常 Commit 新 Transaction；
11. Recovery 模式下新 Transaction 的 Outbox 是否会保持 Pending；
12. Execution Deduplicator 和 Sequence Tracker 在 Tail Rehydrate 后是否已推进；
13. Replay Cursor 当前在哪个阶段更新；
14. Result Progress 和 MarketData Audit 当前何时完成；
15. 普通每 Bar Checkpoint 为什么必须继续在 Recovery Session 活跃期间禁用；
16. 当前 Orchestrator 对 `session.require_complete()` 的使用如何调整；
17. 当前恢复诊断是否需要增加 Continuation Transaction 信息；
18. 哪些现有测试只验证 Session，不验证真实 Engine；
19. 哪些现有 Architecture Test 只是源码字符串检查；
20. 本任务实施后应删除哪些旧布尔状态和旧方法。

审计完成后再修改生产代码。

---

# 五、核心架构原则

## 5.1 Tail Resolved 不等于 Boundary Completed

必须形成三个明确概念：

```text
Persisted Tail Matching
Persisted Tail Resolved
Current Replay Boundary Completed
```

不得继续使用一个 `complete` 布尔值同时表达这三个概念。

## 5.2 Execution 层不得依赖 Backtest 层

`onlyalpha.execution` 不得导入：

```text
onlyalpha.runtime
onlyalpha.runtime.backtest
OnlyBacktestBarCompletion
MarketData Replay Boundary
```

Execution Recovery Session 只负责：

* 持久 Transaction Tail；
* Recovery Decision；
* Persisted Resolution；
* Continuation Transaction Sequence。

Backtest Recovery Boundary 由 `runtime/backtest` 层负责。

依赖方向必须是：

```text
runtime.backtest
→ execution
```

不能反向依赖。

## 5.3 新 Transaction 必须走正常 Durable Commit

Tail Resolved 后产生的新正式 Transaction 必须：

```text
使用同一个 Planner
→ 使用同一个 Coordinator.commit()
→ 分配新的连续 Execution Sequence
→ 写入原 Runtime Persistence Store
→ 应用正式 Projection
→ 标记 Projection Ready
→ 写入 Durable Outbox
```

不得：

* 伪装成 Ready Rehydrate；
* 伪装成 Unprojected Recovery；
* 绕过 Coordinator；
* 直接修改 Manager；
* 手工指定 Execution Sequence；
* 通过测试私有字段注入 Transaction。

## 5.4 Recovery 期间不立即交付新 Outbox

PR4.2.1 已经通过 `ExecutionProcessor.replay()` 抑制即时 Delivery。

PR4.2.2a 必须保持：

```text
Recovery Continuation Transaction
→ Durable Commit
→ Projection Ready
→ Outbox Pending
→ 当前 Recovery 中不交付
```

不要在本 PR 中实现完整 Event Gate。

## 5.5 Boundary 完成必须由 MarketData 完成路径确认

Recovery Replay Service 不得根据：

```text
session.tail_resolved
```

自行推断：

```text
当前 Bar 已完成
```

Boundary Completion 必须来自：

```text
MarketDataProcessor._finish()
→ Audit Append
→ Result Progress Observe
→ EventBus Drain
→ Runtime after_market_processing()
```

---

# 六、Execution Recovery Phase 状态机

## 6.1 新增 Phase

在 Execution Recovery 模型中新增：

```python
class OnlyExecutionRecoveryPhase(StrEnum):
    MATCHING_PERSISTED_TAIL = "MATCHING_PERSISTED_TAIL"
    TAIL_RESOLVED = "TAIL_RESOLVED"
    FAILED = "FAILED"
```

语义：

### MATCHING_PERSISTED_TAIL

仍有持久 Transaction Tail Entry 未解决。

正式 Trade 必须匹配下一个 Stored Entry。

Store 中不存在的新正式 Transaction必须失败：

```text
RECOVERY_TRANSACTION_MISSING
```

乱序必须失败：

```text
RECOVERY_TRANSACTION_CAUSAL_ORDER_MISMATCH
```

Prepared 不一致必须失败：

```text
RECOVERY_PREPARED_TRANSACTION_MISMATCH
```

### TAIL_RESOLVED

所有持久 Tail Entry 已按顺序解决。

此时：

* Recovery Replay 仍在进行；
* 当前 MarketData Boundary 可能尚未完成；
* Strategy、Broker、Timer 和 Event Drain 可以继续；
* 新正式 Transaction 可以正常 Commit；
* 新 Transaction 不再尝试匹配 Stored Tail；
* 新 Transaction 必须保持连续 Execution Sequence。

### FAILED

Session 已发生不可恢复错误。

之后任何 Decision、Resolve 或 Continuation Record 都必须拒绝。

---

## 6.2 删除弱状态

删除或替代：

```python
complete
boundary_complete
_boundary_complete
complete_boundary()
require_complete()
```

如果 `complete` 在其他代码中仍有必要，应重命名为：

```python
tail_resolved
```

并且语义必须只表示持久 Tail 已解决。

Execution Session 不得再保存任何 MarketData Boundary 布尔值。

---

# 七、Recovery Decision 模型

## 7.1 新增 Decision Kind

新增：

```python
class OnlyExecutionRecoveryDecisionKind(StrEnum):
    REHYDRATE_READY = "REHYDRATE_READY"
    RECOVER_UNPROJECTED = "RECOVER_UNPROJECTED"
    COMMIT_CONTINUATION = "COMMIT_CONTINUATION"
```

新增：

```python
@dataclass(frozen=True, slots=True)
class OnlyExecutionRecoveryDecision:
    kind: OnlyExecutionRecoveryDecisionKind
    entry: OnlyExecutionRecoveryEntry | None
```

约束：

```text
REHYDRATE_READY
→ entry 必须存在且 state == READY

RECOVER_UNPROJECTED
→ entry 必须存在且 state == UNPROJECTED

COMMIT_CONTINUATION
→ entry 必须为 None
```

---

## 7.2 Session 决策接口

将当前：

```python
require_expected(update, prepared)
```

替换为正式接口：

```python
def decide(
    self,
    update: OnlyBrokerTradeUpdate,
    prepared: OnlyPreparedExecutionTransaction,
) -> OnlyExecutionRecoveryDecision:
    ...
```

逻辑：

```text
Phase = MATCHING_PERSISTED_TAIL
    → 验证下一个 Stored Entry
    → 完整比较 Prepared
    → 返回 REHYDRATE_READY 或 RECOVER_UNPROJECTED

Phase = TAIL_RESOLVED
    → 返回 COMMIT_CONTINUATION

Phase = FAILED
    → 抛出 RECOVERY_SESSION_FAILED
```

当 Phase 为 `MATCHING_PERSISTED_TAIL` 且 Store Tail 尚未完成时，不允许通过 `COMMIT_CONTINUATION` 绕过 Missing 检查。

---

## 7.3 Persisted Resolution

保留或重构现有 Resolution：

```python
class OnlyExecutionRecoveryResolution(StrEnum):
    READY_REHYDRATED = "READY_REHYDRATED"
    UNPROJECTED_RECOVERED = "UNPROJECTED_RECOVERED"
```

新增明确接口：

```python
def resolve_persisted(
    self,
    execution_sequence: int,
    resolution: OnlyExecutionRecoveryResolution,
) -> None:
    ...
```

要求：

1. 只能解决当前 Expected Entry；
2. Resolution 必须与 Entry State 匹配；
3. Sequence 必须严格递增；
4. 解决最后一个 Entry 后，Phase 自动从：

```text
MATCHING_PERSISTED_TAIL
→ TAIL_RESOLVED
```

5. 不允许重复 Resolve；
6. 不允许 Resolve Continuation Transaction。

---

## 7.4 Continuation Transaction 记录

新增：

```python
@dataclass(frozen=True, slots=True)
class OnlyExecutionRecoveryContinuation:
    execution_sequence: int
    transaction_id: OnlyExecutionTransactionId
    broker_update_id: OnlyBrokerUpdateId
    trade_id: OnlyTradeId
```

Session 保存：

```python
continuations: tuple[OnlyExecutionRecoveryContinuation, ...]
```

提供：

```python
def record_continuation(
    self,
    transaction: OnlyCommittedExecutionTransaction,
) -> None:
    ...
```

要求：

1. 只有 `TAIL_RESOLVED` 允许调用；
2. 第一个 Continuation Sequence 必须等于：

```text
persisted_tail_final_sequence + 1
```

3. 后续 Continuation Sequence 必须等于前一个加一；
4. Transaction 必须 Projection Ready；
5. Transaction Runtime ID 必须与 Plan Runtime ID 一致；
6. Broker Update ID、Trade ID 和 Transaction ID 不得重复；
7. Session 记录只用于验证，不成为新的持久 Authority；
8. 持久 Authority仍是 Runtime Persistence Store。

新增错误：

```text
RECOVERY_CONTINUATION_BEFORE_TAIL_RESOLVED
RECOVERY_CONTINUATION_SEQUENCE_MISMATCH
RECOVERY_CONTINUATION_TRANSACTION_NOT_READY
RECOVERY_CONTINUATION_SCOPE_MISMATCH
```

---

# 八、ExecutionProcessor 改造

## 8.1 Recovery Prepared Trade 分支

当前 Recovery 分支大致为：

```text
require_expected
→ READY: rehydrate_existing
→ UNPROJECTED: recover_existing
```

改为：

```python
decision = recovery_session.decide(update, prepared)

if decision.kind is REHYDRATE_READY:
    coordination = coordinator.rehydrate_existing(...)

elif decision.kind is RECOVER_UNPROJECTED:
    coordination = coordinator.recover_existing(...)

elif decision.kind is COMMIT_CONTINUATION:
    coordination = coordinator.commit(
        prepared,
        committed_at=coordinated_at,
        projected_at=coordinated_at,
    )
```

不得复制正常 Commit 的实现。

---

## 8.2 Coordination 成功后的处理

### Persisted Ready / Unprojected

成功后：

```python
recovery_session.resolve_persisted(
    transaction.execution_sequence,
    resolution,
)
```

### Continuation Transaction

成功后：

```python
recovery_session.record_continuation(transaction)
```

Continuation Transaction 的业务 Processing Result 应与普通正常 Commit 一致：

```text
Processing Status = APPLIED
Mutation Steps = APPLIED
Invariant = PASSED
```

它不是：

```text
DUPLICATE
RECOVERED
REHYDRATED
```

“该 Transaction 在 Recovery Continuation 阶段产生”只能记录在内部 Recovery Diagnostic，不应改变业务 Processing Status。

---

## 8.3 Delivery 行为

`ExecutionProcessor.replay()` 必须继续将：

```text
delivery_intent = NONE
```

应用于：

* Ready Rehydrate；
* Unprojected Recover；
* Continuation Commit；
* Non-Transaction Replay。

Continuation Commit 已写入 Durable Outbox，但 Runtime 在 Recovery Replay 中不得立即投递。

不要在本任务中重构全部 Event Publisher。

---

# 九、Backtest Recovery Boundary

## 9.1 新增 Boundary Identity

建议新增：

```text
src/onlyalpha/runtime/backtest/recovery_boundary.py
```

新增：

```python
@dataclass(frozen=True, slots=True)
class OnlyBacktestRecoveryBoundary:
    source_id: OnlyMarketDataSourceId
    data_version: OnlyDataVersion
    update_id: OnlyMarketDataUpdateId
    source_sequence: int
    ts_event: OnlyTimestamp
```

必须能够从 Historical Stream Record 构建。

Identity 必须使用：

```text
source_id
data_version
update_id
source_sequence
```

不能只使用 Timestamp。

同一 Timestamp 可以存在多个合法 Update。

---

## 9.2 新增 Backtest Recovery Session

新增：

```python
class OnlyBacktestRecoveryPhase(StrEnum):
    MATCHING_PERSISTED_TAIL = "MATCHING_PERSISTED_TAIL"
    TAIL_RESOLVED_BOUNDARY_OPEN = "TAIL_RESOLVED_BOUNDARY_OPEN"
    BOUNDARY_COMPLETED = "BOUNDARY_COMPLETED"
    FAILED = "FAILED"
```

新增：

```python
class OnlyBacktestRecoverySession:
    ...
```

该对象组合：

```python
execution_session: OnlyExecutionRecoverySession
```

并负责：

* 当前 Replay Boundary；
* 当前 Boundary Completion；
* Runtime 级 Recovery Phase；
* Boundary Identity 验证；
* 完整 Bar 后停止条件。

不要让 Execution Session 导入 Backtest 类型。

---

## 9.3 Phase 计算

Backtest Session 的 Phase 必须满足：

```text
Execution Phase = MATCHING_PERSISTED_TAIL
→ Backtest Phase = MATCHING_PERSISTED_TAIL

Execution Phase = TAIL_RESOLVED
且当前 Boundary 尚未完成
→ Backtest Phase = TAIL_RESOLVED_BOUNDARY_OPEN

当前 Boundary 已正式完成
且 Execution Tail 已 Resolved
→ Backtest Phase = BOUNDARY_COMPLETED
```

不得使用多个无关联 Bool 推断 Phase。

可以保存最少必要状态，但必须提供唯一公开 `phase` 属性。

---

## 9.4 Boundary 进入

新增：

```python
def enter_boundary(
    self,
    boundary: OnlyBacktestRecoveryBoundary,
) -> None:
    ...
```

要求：

1. 当前不能已有未完成 Boundary；
2. Phase 不能是 `BOUNDARY_COMPLETED`；
3. Phase 不能是 `FAILED`；
4. Boundary Identity 不得重复；
5. Source ID / Data Version 必须与 Checkpoint Cursor Scope 一致；
6. Source Sequence 必须向前推进；
7. 同一 Timestamp 的不同 Update 必须允许。

如果上一个 Boundary 已完整执行但 Tail 尚未完成，允许进入下一个 Boundary。

---

## 9.5 Boundary 完成

新增：

```python
def observe_completion(
    self,
    completion: OnlyBacktestBarCompletion,
) -> None:
    ...
```

验证：

```text
completion.source_id == current.source_id
completion.data_version == current.data_version
completion.update_id == current.update_id
completion.source_sequence == current.source_sequence
completion.ts_event == current.ts_event
```

如果 Identity 不匹配：

```text
RECOVERY_BOUNDARY_IDENTITY_MISMATCH
```

如果没有先 `enter_boundary()`：

```text
RECOVERY_BOUNDARY_NOT_ENTERED
```

处理规则：

### Tail 尚未 Resolved

当前 Bar 可以正常完成，但 Recovery 继续：

```text
完成当前 Boundary
→ 清空 current boundary
→ Phase 仍为 MATCHING_PERSISTED_TAIL
→ Replay 下一条 MarketData Record
```

### Tail 已 Resolved

完成当前 Bar 后：

```text
TAIL_RESOLVED_BOUNDARY_OPEN
→ BOUNDARY_COMPLETED
```

Recovery Replay 此时才可以停止。

---

# 十、Runtime 接入

## 10.1 Runtime 只保存 Backtest Recovery Session

将当前类似：

```python
_execution_recovery_session
```

替换为：

```python
_backtest_recovery_session: OnlyBacktestRecoverySession | None
```

Runtime 需要 Execution Session 时，通过：

```python
session.execution_session
```

访问。

不要同时长期保存两套独立 Session 引用。

---

## 10.2 Broker Update Drain

修改为：

```python
session = self._backtest_recovery_session

processing = (
    execution_processor.process(update)
    if session is None
    else execution_processor.replay(
        update,
        session.execution_session,
    )
)
```

Recovery 期间仍不调用正常 Delivery Coordinator。

---

## 10.3 after_market_processing

当前顺序必须保留：

```text
Result Progress Observe
→ EventBus Drain
→ Checkpoint Barrier
```

接入 Boundary Completion 后调整为：

```text
Result Progress Observe
→ EventBus Drain
→ Recovery Session observe_completion
→ Checkpoint Barrier
```

示意：

```python
completion = result_progress.observe_market_data_result(result, update)
owned_bus.drain()

recovery_session = self._backtest_recovery_session
if recovery_session is not None:
    recovery_session.observe_completion(completion)

checkpoint_barrier(completion)
```

Boundary Completion 必须发生在：

* MarketData Audit 已追加后；
* Result Progress 已更新后；
* EventBus 已 Drain 后。

---

## 10.4 Checkpoint Barrier

当前 Recovery Session 活跃期间：

```text
更新内存 Replay Cursor
但不创建普通每 Bar Checkpoint
```

这一语义必须保留。

即使 Recovery Session 已进入 `BOUNDARY_COMPLETED`，在其正式 Deactivate 前也不能由普通 Barrier 写 Checkpoint。

Post-Recovery Checkpoint 仍由当前 PR4.2.1 的 `_recover_runtime()` 收尾路径创建。

不要在本 PR 中引入新的 Finalizer。

---

# 十一、Recovery Replay Service 改造

## 11.1 不再调用 Execution Session complete_boundary

删除：

```text
if session.complete:
    session.complete_boundary()
    break
```

Recovery Replay Service 不得直接设置 Boundary Complete。

---

## 11.2 新流程

建议：

```python
backtest_session = OnlyBacktestRecoverySession(
    execution_session,
    checkpoint.header.replay_cursor,
)

activate(backtest_session)

for record in remaining:
    boundary = OnlyBacktestRecoveryBoundary.from_record(record)
    backtest_session.enter_boundary(boundary)

    replay.run(single_record_cursor)

    if backtest_session.phase is BOUNDARY_COMPLETED:
        break

deactivate()
backtest_session.require_boundary_completed()
```

如果数据耗尽但持久 Tail 未解决：

```text
RECOVERY_TRANSACTION_TAIL_INCOMPLETE
```

如果 Tail 已解决但对应 Boundary 未完成：

```text
RECOVERY_BOUNDARY_INCOMPLETE
```

如果 Replay 返回而 Runtime 未调用 `observe_completion()`：

```text
RECOVERY_BOUNDARY_CALLBACK_MISSING
```

---

## 11.3 多 Boundary Tail

实现必须支持：

```text
Boundary A
→ 未解决全部 Tail
→ A 完成
→ 继续 Boundary B

Boundary B
→ 最后一笔 Tail 完成
→ Strategy 继续执行
→ 可能产生 Continuation Transaction
→ B 完成
→ Recovery Replay 停止
```

虽然当前每 Bar Checkpoint 下，Transaction Tail 通常集中在一个 Bar，但架构不能写死单 Bar。

---

# 十二、Orchestrator 调整

当前 Orchestrator 创建：

```python
OnlyExecutionRecoverySession(plan)
```

并调用 Causal Replay。

可以保持这一职责，也可以让 Replay Service 创建 Backtest Session。

要求：

1. Orchestrator 仍是 Checkpoint Restore 和 Execution Plan 的所有者；
2. Replay Service 负责 Backtest Boundary；
3. Orchestrator 返回前必须确认：

   * Execution Tail Resolved；
   * Backtest Boundary Completed；
4. 不得恢复 Replay 后批量 Rehydrate / Recover；
5. 不得在 Orchestrator 中重新实现 Boundary 判断。

建议 Causal Replay 返回：

```python
@dataclass(frozen=True, slots=True)
class OnlyBacktestRecoveryReplayResult:
    catch_up_bar_count: int
    final_boundary: OnlyBacktestRecoveryBoundary
    continuation_transaction_count: int
```

如果修改现有 Diagnostic，新增字段必须有明确语义，例如：

```text
continuation_transaction_count
final_boundary_update_id
```

不要将 Continuation Transaction 计入：

```text
rehydrated_transaction_count
recovered_transaction_count
```

---

# 十三、测试要求

## 13.1 先写红色集成测试

编码前先新增一个当前实现会失败的测试。

场景必须真实经过：

```text
OnlyEngine
→ Runtime Planner
→ Runtime Factory
→ Checkpoint
→ Virtual/Test Broker Driver
→ Broker Inbound Queue
→ ExecutionProcessor
→ Runtime Persistence Store
→ Engine Restart
```

不得直接构造 Runtime 或手工调用 Session。

场景：

```text
Checkpoint 中存在一个待成交 Open Order

Engine A:
→ 恢复目标 Bar 到来
→ Broker 在 Strategy 前产生 Fill
→ Transaction Durable Commit
→ 在故障点中断
→ Store 中形成 Ready 或 Unprojected Tail

Engine B:
→ Restore Checkpoint
→ Replay 同一个 Bar
→ 在 Broker Update 因果点恢复最后一笔 Tail Transaction
→ Strategy.on_bar 读取刚恢复后的 Position / Allocation
→ Strategy 根据该 Position 提交一个新订单
→ Test Broker 在同一个 Bar 的后续阶段产生新 Fill
→ 新 Fill 形成 Continuation Transaction
→ 完整 Bar 结束
→ Recovery Replay 停止
→ Engine 正常继续
```

测试必须断言：

1. Strategy 在同 Bar 读取到了恢复后的 Position；
2. 新订单确实由该 Position 条件触发；
3. 不出现 `RECOVERY_TRANSACTION_MISSING`；
4. 原 Tail Transaction ID 保持不变；
5. Continuation Transaction 使用新的连续 Sequence；
6. Continuation Transaction Projection Ready；
7. Continuation Outbox 在 Recovery Finalization 前没有被即时投递；
8. Engine 最终完成；
9. 与无故障 Baseline 的 Canonical Business Projection 完全相等；
10. Trades、Orders、Signals 和 Fingerprint 完全相等。

如果官方 Virtual Broker 当前不支持同 Bar 新订单成交：

* 创建测试专用确定性 Broker Plugin/Driver；
* 通过正式 Composition Root 注入；
* 不修改生产 Virtual Broker 的市场语义；
* 不访问 Runtime 私有字段；
* 不直接向 Queue 手工塞入绕过 Broker 的 Trade。

---

## 13.2 Execution Session 单元测试

至少增加：

### Test A：Persisted Tail 状态转换

```text
MATCHING_PERSISTED_TAIL
→ Resolve Ready
→ Resolve Unprojected
→ TAIL_RESOLVED
```

### Test B：Tail 未完成时 Missing

Store 中不存在的新 Trade 必须：

```text
RECOVERY_TRANSACTION_MISSING
```

### Test C：Tail Resolved 后 Continuation Decision

```text
Phase = TAIL_RESOLVED
→ decide(new prepared)
→ COMMIT_CONTINUATION
```

### Test D：Continuation Sequence

验证：

```text
persisted final = 5
continuation = 6, 7, 8
```

接受。

以下必须拒绝：

```text
5
7
重复 6
其他 Runtime
未 Projection Ready
```

### Test E：Failed Session

进入 FAILED 后，所有 Decision 和 Record 均拒绝。

---

## 13.3 Boundary Session 单元测试

至少增加：

1. 没有 `enter_boundary()` 就 Completion；
2. Update ID 不匹配；
3. Source Sequence 不匹配；
4. Data Version 不匹配；
5. 同一 Timestamp 不同 Update 合法；
6. Tail 未完成时，一个 Boundary 完成后继续下一个；
7. Tail 在 Boundary 中间完成；
8. Tail 完成后 Boundary 仍保持 Open；
9. `observe_completion()` 后进入 `BOUNDARY_COMPLETED`；
10. Boundary 完成后不允许进入新 Boundary。

---

## 13.4 Processor 测试

至少验证：

1. READY Decision 调用 `rehydrate_existing()`；
2. UNPROJECTED Decision 调用 `recover_existing()`；
3. CONTINUATION Decision 调用正常 `commit()`；
4. Continuation 不调用 Rehydrate；
5. Continuation 不调用 Recover；
6. Continuation Processing Status 为 APPLIED；
7. Continuation Delivery Intent 为 NONE；
8. Continuation Outbox 已持久化；
9. Continuation Session Sequence 已记录；
10. Tail 未完成时不会错误 Commit。

---

## 13.5 多 Boundary 集成测试

场景：

```text
Checkpoint
→ Boundary A 产生 Tail Entry 1
→ Boundary A 完成但 Tail 未结束
→ Boundary B 产生 Tail Entry 2
→ Tail Resolved
→ Boundary B 完整完成
→ Replay 停止
```

验证：

* 不在 Boundary A 后提前停止；
* Cursor 最终指向 Boundary B；
* Result Progress 包含 A 和 B；
* Post-Recovery Checkpoint 指向 B；
* Baseline Business Projection 相等。

---

## 13.6 三笔以上 Continuation

同一个恢复 Boundary 中形成：

```text
Persisted Tail Final Sequence = N
Continuation = N+1
Continuation = N+2
Continuation = N+3
```

验证 Sequence、Order、Trade、Position、Ledger 和 Result 等价。

如果生产 Matching 语义不支持，使用测试专用确定性 Broker Driver。

---

# 十四、架构门禁

新增或更新架构测试，至少保证：

1. `onlyalpha.execution` 不导入 `onlyalpha.runtime`；
2. Execution Session 不保存 MarketData Boundary；
3. 不再存在 `_boundary_complete`；
4. 不再存在 Execution Session `complete_boundary()`；
5. 不再通过 `session.complete` 推断 Replay Boundary；
6. Recovery Replay Service 不主动设置 Boundary Complete；
7. Runtime 保存唯一 Backtest Recovery Session；
8. Processor 通过 Recovery Decision 选择三种路径；
9. Continuation 使用 `coordinator.commit()`；
10. Continuation 不调用 `rehydrate_existing()`；
11. Continuation 不调用 `recover_existing()`；
12. Tail 未完成时不允许 Continuation；
13. Boundary Completion 来自 `after_market_processing()`；
14. Boundary Completion 位于 Result Progress 和 Event Drain 后；
15. Recovery Session 活跃时普通 Checkpoint 仍被抑制；
16. 不引入生产故障配置；
17. 测试不修改 Runtime 私有字段；
18. 测试不直接构造 Runtime；
19. 测试不手工设置 Replay Cursor；
20. 不保留旧 Session API 兼容层。

源码字符串 Architecture Test 只能作为辅助门禁。

核心正确性必须由行为测试证明。

---

# 十五、错误模型

建议增加或规范以下错误代码：

```text
RECOVERY_SESSION_FAILED
RECOVERY_TRANSACTION_MISSING
RECOVERY_TRANSACTION_CAUSAL_ORDER_MISMATCH
RECOVERY_PREPARED_TRANSACTION_MISMATCH
RECOVERY_TRANSACTION_CODEC_OR_HASH_MISMATCH
RECOVERY_CONTINUATION_BEFORE_TAIL_RESOLVED
RECOVERY_CONTINUATION_SEQUENCE_MISMATCH
RECOVERY_CONTINUATION_TRANSACTION_NOT_READY
RECOVERY_CONTINUATION_SCOPE_MISMATCH
RECOVERY_BOUNDARY_NOT_ENTERED
RECOVERY_BOUNDARY_ALREADY_OPEN
RECOVERY_BOUNDARY_IDENTITY_MISMATCH
RECOVERY_BOUNDARY_INCOMPLETE
RECOVERY_BOUNDARY_CALLBACK_MISSING
RECOVERY_PROCESS_AFTER_BOUNDARY_COMPLETE
```

错误必须 Fail Closed。

不得捕获后降级为普通 Duplicate 或普通 Processing Failure。

---

# 十六、建议文件变化

根据当前工程结构调整，建议：

```text
src/onlyalpha/execution/
├── causal_recovery.py
├── processor.py
└── __init__.py

src/onlyalpha/runtime/backtest/
├── recovery_boundary.py
├── recovery_replay.py
├── runtime.py
└── result_progress.py

src/onlyalpha/runtime/recovery/
└── orchestrator.py
```

测试建议：

```text
tests/execution/test_causal_execution_recovery.py
tests/execution/test_execution_recovery_continuation.py

tests/runtime/recovery/test_backtest_recovery_boundary.py

tests/integration/test_engine_recovery_same_bar_continuation.py
tests/integration/test_engine_recovery_multi_boundary_tail.py
tests/integration/test_engine_recovery_multiple_continuations.py

tests/architecture/test_recovery_phase_boundary_architecture.py
```

不要为了目录形式创建无实质职责的空壳模块。

---

# 十七、实施顺序

## Step 1：完成预实现审计

输出真实调用链和当前失败原因。

## Step 2：先提交红色测试

建立 Same-Bar Continuation Engine 测试，并证明当前实现失败于：

```text
RECOVERY_TRANSACTION_MISSING
```

## Step 3：重构 Execution Recovery Session

实现：

* Phase；
* Decision；
* Persisted Resolution；
* Continuation Record；
* Sequence Validation；
* Failure State。

## Step 4：改造 ExecutionProcessor

接入：

```text
REHYDRATE_READY
RECOVER_UNPROJECTED
COMMIT_CONTINUATION
```

## Step 5：实现 Backtest Recovery Boundary Session

建立精确 Boundary Identity 和 Completion Contract。

## Step 6：接入 Runtime

修改：

* Broker Drain；
* after_market_processing；
* Checkpoint Barrier；
* Recovery Session Activation。

## Step 7：改造 Recovery Replay Service

删除 Replay Service 主动完成 Boundary 的逻辑。

## Step 8：调整 Orchestrator 和 Diagnostic

确保返回前 Tail 与 Boundary 都已完成。

## Step 9：补齐单元和集成测试

覆盖 Same-Bar、Multi-Boundary 和 Multiple Continuation。

## Step 10：删除旧 API

删除：

* `complete_boundary()`；
* `boundary_complete`；
* 弱 `complete` 语义；
* 兼容 Wrapper；
* 旧测试假设。

## Step 11：更新文档

新增 ADR 并更新 Recovery 文档。

---

# 十八、文档要求

新增 ADR：

```text
docs/adr/0046-recovery-tail-resolution-and-exact-replay-boundary.md
```

ADR 必须说明：

1. 为什么 Tail Resolved 不等于 Boundary Completed；
2. 当前 Same-Bar Continuation 为什么会被误判 Missing；
3. 为什么 Tail 未完成时仍必须拒绝新 Transaction；
4. 为什么 Tail 完成后允许正常 Continuation Commit；
5. Continuation Transaction 为什么必须走正式 Coordinator；
6. Continuation Outbox 为什么在 Recovery 中保持 Pending；
7. Execution Session 与 Backtest Boundary Session 的职责边界；
8. 为什么 Execution 层不能依赖 Backtest 类型；
9. Boundary Identity 为什么不能只使用 Timestamp；
10. Recovery Replay 为什么必须由 `after_market_processing()` 确认停止；
11. 当前仍未实现的 Event Gate、Validator 和 Finalizer。

更新：

```text
README.md
docs/roadmap.md
docs/execution_runtime_recovery.md
docs/backtest.md
docs/architecture.md
```

文档必须明确：

```text
PR4.2.2a 只解决 Phase、Boundary 和 Continuation Transaction。
统一事件门禁与恢复收尾校验仍属于后续 PR4.2.2b / PR4.2.2c。
```

---

# 十九、测试命令

根据项目当前结构执行完整门禁，至少包括：

```bash
uv lock --check
uv sync --frozen --all-packages --all-groups

uv run ruff check src tests examples packages
uv run ruff format --check src tests examples packages

uv run mypy src/onlyalpha
uv run mypy packages/fake/onlyalpha-plugin-broker-virtual/src
uv run mypy packages/provider/onlyalpha-plugin-tushare/src/onlyalpha_plugin_tushare
uv run mypy packages/provider/onlyalpha-plugin-miniqmt/src/onlyalpha_plugin_miniqmt

uv run pytest tests/execution/test_causal_execution_recovery.py -q
uv run pytest tests/execution/test_execution_recovery_continuation.py -q
uv run pytest tests/runtime/recovery/test_backtest_recovery_boundary.py -q

uv run pytest tests/integration/test_engine_recovery_same_bar_continuation.py -q
uv run pytest tests/integration/test_engine_recovery_multi_boundary_tail.py -q
uv run pytest tests/integration/test_engine_recovery_multiple_continuations.py -q

uv run pytest tests/runtime/recovery -q
uv run pytest tests/execution -q
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

根据仓库实际文件名调整命令。

不得伪造未执行的测试结果。

---

# 二十、完成标准

只有全部满足以下条件，才能声明 PR4.2.2a 完成：

1. Execution Recovery 有正式 Phase；
2. Tail Resolved 与 Boundary Completed 明确分离；
3. Execution Session 不再保存 MarketData Boundary；
4. Backtest Runtime 有独立 Boundary Session；
5. Boundary 使用完整 Identity；
6. 同 Timestamp 不同 Update 可正确区分；
7. Tail 未完成时 Missing Transaction 仍然失败；
8. Tail 未完成时不能 Commit Continuation；
9. Tail 完成后可以产生 Continuation Transaction；
10. Continuation 使用正式 Planner；
11. Continuation 使用正式 Coordinator Commit；
12. Continuation 分配连续 Execution Sequence；
13. Continuation Projection Ready；
14. Continuation Outbox Durable；
15. Continuation Outbox 在 Recovery 中不立即投递；
16. Continuation Processing Status 为 APPLIED；
17. Continuation 不伪装成 Rehydrate；
18. Continuation 不伪装成 Recover；
19. Recovery Replay 不再调用 Execution `complete_boundary()`；
20. Boundary Completion 由 Runtime `after_market_processing()` 确认；
21. Boundary Completion 位于 Audit 后；
22. Boundary Completion 位于 Result Progress 后；
23. Boundary Completion 位于 EventBus Drain 后；
24. Recovery Replay 只在完整 Boundary 后停止；
25. Tail 可跨多个 Boundary；
26. Recovery Session 活跃时普通 Checkpoint 不写入；
27. Replay Cursor 仍推进到完整 Boundary；
28. Post-Recovery Checkpoint 仍由现有收尾路径创建；
29. Same-Bar Continuation Engine 测试通过；
30. Multi-Boundary Tail Engine 测试通过；
31. Multiple Continuation 测试通过；
32. 与 Baseline Canonical Business Projection 完全相等；
33. Orders、Trades、Signals 和 Fingerprint 相等；
34. 不修改生产 Virtual Broker 语义来迎合测试；
35. 不访问 Runtime 私有字段；
36. 不直接构造 Runtime；
37. 不手工设置 Replay Cursor；
38. 不增加生产故障开关；
39. 不保留旧 Session API 兼容层；
40. Ruff、Mypy、Pytest 和 Architecture Gate 全部通过。

---

# 二十一、禁止的实现

以下任一情况视为任务失败：

```text
继续用 session.complete 表示 Boundary 完成
继续保留 Execution Session boundary_complete
Tail 完成后立即退出 Replay，不完成当前 Bar
Tail 完成后仍把所有新 Transaction 判定 Missing
Tail 未完成时直接允许新 Transaction Commit
通过 try/except 吞掉 RECOVERY_TRANSACTION_MISSING
把 Continuation 当 Duplicate
把 Continuation 当 Ready Rehydrate
把 Continuation 当 Unprojected Recover
绕过 Planner 构造 Continuation
绕过 Coordinator 修改 Manager
手工指定 Execution Sequence
恢复期间立即交付 Continuation Outbox
Execution 层导入 Backtest Runtime 类型
Boundary 只比较 Timestamp
修改生产 Virtual Broker 以方便测试
测试直接向 Broker Queue 注入绕过 Broker 的 Trade
测试修改 Runtime 私有字段
测试手工调用 Recovery Session
测试手工设置 Cursor
为旧测试保留 deprecated complete_boundary()
在本 PR 中顺带实现完整 Event Gate
在本 PR 中顺带实现完整 Authority Validator
在本 PR 中顺带实现 Recovery Finalizer
```

---

# 二十二、最终交付报告

完成后输出结构化报告。

## 1. 修改前根因

说明：

```text
Persisted Tail Complete
被错误等同于
Recovery Boundary Complete
```

以及 Same-Bar Continuation 为什么被误判 Missing。

## 2. 新状态机

列出：

```text
Execution Recovery Phase
Backtest Recovery Phase
合法转换
非法转换
```

## 3. Recovery Decision

说明：

```text
REHYDRATE_READY
RECOVER_UNPROJECTED
COMMIT_CONTINUATION
```

三种路径的区别。

## 4. Boundary Contract

说明：

* Boundary Identity；
* enter；
* completion；
* Multi-Boundary；
* Cursor；
* Result Progress；
* Checkpoint Barrier。

## 5. Continuation Transaction

说明：

* Planner；
* Commit；
* Sequence；
* Projection；
* Outbox；
* Processing Status。

## 6. 删除内容

列出删除的：

* Bool；
* 方法；
* Compatibility Wrapper；
* 旧测试假设。

## 7. 测试结果

提供真实命令和结果。

## 8. 剩余边界

明确仍未实现：

* Unified Recovery Event Gate；
* Post-Recovery Authority Validator；
* Recovery Finalizer；
* Partial / Multi-Fill；
* SELL / CLOSE；
* Futures / Margin；
* Non-Trade Transaction；
* Paper / Live Recovery；
* Exactly-once Outbox；
* Full Broker Reconciliation；
* Schema Migration；
* Distributed Checkpoint。

---

# 二十三、最终架构结论

完成后，恢复模型必须从：

```text
Resolve last persisted Tail Transaction
→ Session complete
→ Recovery Replay stops
```

升级为：

```text
Resolve last persisted Tail Transaction
→ Execution Phase becomes TAIL_RESOLVED
→ Current MarketData Boundary remains open
→ Strategy and Broker continue
→ New Transactions commit normally as Continuations
→ Processing Result completes
→ Audit completes
→ Result Progress completes
→ EventBus drains
→ Exact Boundary identity is confirmed
→ Backtest Recovery Phase becomes BOUNDARY_COMPLETED
→ Recovery Replay stops
```

最终必须证明：

> OnlyAlpha 可以在恢复最后一笔持久 Transaction 后，继续执行同一个 MarketData Bar 中剩余的 Strategy 和 Broker 因果链，并将新产生的 Transaction 作为连续、正式、可持久的业务 Transaction 提交；Recovery Replay 只有在该 Bar 的完整处理边界结束后才能退出。
