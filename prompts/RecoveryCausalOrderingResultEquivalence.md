# OnlyAlpha PR4.2.1：Recovery Causal Ordering 与完整 Result Equivalence

## 一、任务目标

请基于 OnlyAlpha 当前 `master` 分支的真实源码、测试、ADR、README 和 Roadmap，完成：

```text
PR4.2.1
Recovery Causal Ordering
+
Stable Bar Completion
+
Complete Backtest Result Equivalence
```

本任务不是增加几个恢复测试，也不是修改当前 Recovery Replay 中的少量条件判断。

本任务必须从架构上解决：

1. Checkpoint 后的 Execution Transaction 必须在 Recovery Replay 中，按照原始 Broker Update 的因果时点逐笔应用；
2. 后续 Strategy、Factor、Indicator、Risk 和 Broker 逻辑必须立即观察到前一笔恢复事务产生的最新 Authority；
3. Checkpoint 必须位于完整 MarketData Processing、Audit、Result Progress 和 Event Drain 之后；
4. Checkpoint 前的回测统计、业务诊断和结果前缀必须能够恢复；
5. 恢复运行与无故障 Baseline 的完整业务结果必须逐字段等价，而不仅是当前有限范围的 Fingerprint 相同。

最终产品链必须达到：

```text
Latest Complete Checkpoint
→ Restore Runtime Participants
→ Analyze Execution Transaction Tail
→ Create Causal Recovery Session
→ Replay MarketData from Checkpoint Cursor
→ Resolve each persisted Transaction at its original Broker Update point
→ Allow later Strategy callbacks to observe restored Authority
→ Complete the full MarketData boundary
→ Persist complete Result Progress
→ Validate Runtime Authority
→ Write Post-Recovery Checkpoint
→ Deliver Pending Outbox
→ Continue normal Backtest
→ Produce Baseline-equivalent complete business result
```

---

# 二、当前问题

当前 PR4.2 已经完成：

* Runtime Persistence Store；
* SQLite Schema Version 2；
* Runtime Checkpoint；
* Participant Registry；
* 每 Bar Checkpoint；
* Execution Transaction Tail Analyzer；
* Ready Prefix Rehydration；
* Unprojected Suffix Recovery；
* Open Order、Virtual Broker、Strategy、Factor 和 Indicator Checkpoint；
* Engine A / Engine B Restart 测试。

但当前恢复顺序仍然是：

```text
Restore Checkpoint
→ Analyze Tail
→ Replay Checkpoint 后的 MarketData
→ 遇到 Store 中已存在的 Broker Update 时直接跳过
→ Replay 结束后统一 Rehydrate Ready Prefix
→ Replay 结束后统一 Recover Unprojected Suffix
```

当前 Runtime 使用类似以下临时状态：

```python
_in_recovery_replay
_recovery_expected_update_ids
_recovery_seen_update_ids
```

Recovery Broker Drain 中，如果查询到 Existing Transaction，只恢复 Processing Sequence 并跳过该 Broker Update。

这会造成：

```text
恢复 Bar N
→ Broker Fill 本应更新 Position / Account / Ledger
→ Existing Transaction 被跳过
→ Strategy.on_bar 仍看到 Checkpoint 时的旧 Authority
→ Strategy 产生与 Baseline 不同的决策
→ Replay 结束后再恢复 Transaction 已经太晚
```

同时，当前 Checkpoint Barrier 位于 MarketData Processor 完整 `_finish()` 之前，MarketData Audit 和部分 Result Progress 可能尚未完成。

当前 Result 还依赖：

* 当前次 Historical Replay Result；
* 内存中的 MarketData Audit Store；
* Historical Replay Service Events；
* EventBus Dispatch Results。

这些运行历史没有形成完整的 Checkpoint Authority，因此恢复后可能出现：

* Duplicate Count 不同；
* Gap Count 不同；
* Quality Flags 不同；
* Business Diagnostics 不同；
* Data Summary 不同；
* Artifact 内容不同；
* 当前 Fingerprint 相同但完整 Result 不相同。

---

# 三、核心实施原则

## 3.1 不兼容旧恢复实现

本任务不需要保留以下旧实现：

```text
Runtime 中基于 set 的 Recovery Update 跟踪
Replay 完成后的 Batch Ready Rehydration
Replay 完成后的 Batch Unprojected Recovery
OnlyExecutionReadyTailRehydrationService 的批量主链
Runtime 直接跳过 Existing Transaction
依赖 HistoricalReplayService.events 构造完整业务结果
依赖 EventBus.dispatch_results 计算最终 Result Sequence
在 MarketData Audit 之前创建 Checkpoint
恢复前调用正常 Cluster.start_all()
```

如果新架构已替代旧职责，应直接删除旧：

* 类；
* 方法；
* 字段；
  -测试；
* Adapter；
* Compatibility Wrapper；
* Deprecated Alias；
* 文档说明。

不得为了保留旧测试继续维护两套恢复主链。

## 3.2 当前源码是唯一事实源

开始编码前必须重新检查当前 `master`。

判断优先级：

```text
当前生产源码
→ 当前测试
→ 已接受 ADR
→ 架构文档
→ README / Roadmap
→ 本提示词中的建议命名
```

本提示词中的类名和文件名是建议。可以根据当前工程结构调整，但不得削弱目标。

## 3.3 恢复必须重建 Authority 演化路径

Recovery Replay 的目标不是简单重新读取行情，也不是最后得到相同账户余额。

它必须重建：

```text
MarketData
→ Broker Update
→ Execution Mutation
→ Strategy Observation
→ Later Order
→ Later Broker Update
→ Later Transaction
```

同一条因果路径。

Transaction 不能：

* 在 Replay 前全部应用；
* 在 Replay 后全部应用；
* 因为 Store 已 Ready 就跳过；
* 作为普通 Duplicate 处理；
* 通过 Manager 私有字段直接安装。

## 3.4 业务诊断与运维诊断分离

业务结果可以要求与 Baseline 完全一致。

以下运维信息可以不同：

* Recovery Diagnostic；
* Checkpoint Sequence；
* Outbox Attempt Count；
* 本次 Engine 实例；
* SQLite 文件句柄；
* 实际 Artifact 路径；
* Wall-clock Duration。

不能通过在 Fingerprint 中临时删除字段掩盖业务不等价。

---

# 四、编码前强制审计

开始修改前执行：

```bash
git status
git log -n 30 --oneline

rg "_in_recovery_replay"
rg "_recovery_expected_update_ids"
rg "_recovery_seen_update_ids"
rg "ReadyTailRehydration"
rg "recover_unprojected"
rg "_recover_market_data_tail"
rg "get_by_update"
rg "ALREADY_READY"
rg "_checkpoint_barrier"
rg "after_market_dispatch"
rg "MarketDataAuditStore"
rg "HistoricalReplayService.events"
rg "event_bus.dispatch_results"
rg "OnlyBacktestResultCollector"
rg "OnlyBacktestRunPlan"
rg "result_fingerprint"
rg "determinism_fingerprint"
rg "execution_recoveries"
rg "cluster_manager.start_all"
rg "execute_bar"
rg "OnlyClusterState"
```

生成预实现审计文档：

```text
docs/reports/pr4_2_1_recovery_causal_ordering_pre_implementation_audit.md
```

审计必须回答：

1. 当前一个 Bar 的完整阶段顺序；
2. Virtual Broker 在 Strategy 前后分别执行哪些动作；
3. 一个 Bar 内可能产生多少个 Broker Update；
4. 一个 Bar 内是否可能产生多笔正式 Transaction；
5. Checkpoint 当前发生在 MarketData Processor 的哪个阶段；
6. MarketData Audit 当前何时追加；
7. Result Count 当前从哪里获得；
8. Result Collector 当前依赖哪些瞬态内存历史；
9. Existing Transaction 当前在哪里被跳过；
10. Ready Tail 当前何时 Rehydrate；
11. Unprojected Tail 当前何时恢复；
12. Strategy 在恢复 Replay 时处于何种 Cluster State；
13. 恢复时是否重复调用 `on_start()`；
14. Store 是否保存完整 Prepared Payload；
15. Memory Store 是否保留 Prepared Transaction；
16. 如何从 Broker Update 查询 Stored Prepared + Committed；
17. 当前 Result Fingerprint 未包含哪些业务字段；
18. 当前 Artifact Manifest 使用哪个结果投影；
19. 哪些诊断属于业务诊断；
20. 哪些诊断仅属于恢复运维诊断。

审计完成后再开始编码。

---

# 五、目标恢复流程

新的恢复流程固定为：

```text
Runtime INITIALIZING
→ Cluster initialize
→ Register Checkpoint Participants
→ Runtime RECOVERING
→ Load Latest Checkpoint
→ Validate Checkpoint
→ Restore Participants
→ Analyze Transaction Tail
→ Create Recovery Plan
→ Create Recovery Session
→ Activate Clusters in RECOVERING mode
→ Replay from Checkpoint Cursor
    ├── replay Non-Transaction Broker Update
    ├── rehydrate Ready Transaction at original Broker Update point
    ├── recover Unprojected Transaction at original Broker Update point
    ├── suppress historical external event delivery
    └── allow later Strategy callbacks to observe updated Authority
→ Finish complete MarketData boundary
→ Verify Recovery Session complete
→ Validate Runtime Authority
→ Persist Result Progress
→ Write Post-Recovery Checkpoint
→ Runtime READY
→ Deliver Pending Outbox
→ Resume restored Clusters
→ Runtime RUNNING
→ Continue normal Replay
```

---

# 六、Recovery Transaction 模型

## 6.1 Stored Transaction

当前 Store 已保存：

* Prepared Payload；
* Prepared Authority Hash；
* Prepared Payload Hash；
* Committed Payload；
* Committed Payload Hash。

新增正式模型：

```python
@dataclass(frozen=True, slots=True)
class OnlyStoredExecutionTransaction:
    prepared: OnlyPreparedExecutionTransaction
    committed: OnlyCommittedExecutionTransaction
```

不得只向 Recovery 返回 `OnlyCommittedExecutionTransaction`。

## 6.2 Recovery Query Port

新增：

```python
class OnlyExecutionTransactionRecoveryQueryPort(Protocol):
    def recovery_records(
        self,
        runtime_id: OnlyRuntimeId,
        *,
        after_sequence: int,
    ) -> tuple[OnlyStoredExecutionTransaction, ...]:
        ...

    def get_recovery_record_by_update(
        self,
        runtime_id: OnlyRuntimeId,
        gateway_id: OnlyBrokerGatewayId,
        account_id: OnlyAccountId,
        update_id: OnlyBrokerUpdateId,
    ) -> OnlyStoredExecutionTransaction | None:
        ...
```

SQLite Store 和 Memory Store 必须同时实现。

Memory Store 不能只存 Committed Transaction，必须能够返回原始 Prepared Contract。

## 6.3 Recovery Entry

新增：

```python
class OnlyExecutionRecoveryEntryState(StrEnum):
    READY = "READY"
    UNPROJECTED = "UNPROJECTED"
```

```python
@dataclass(frozen=True, slots=True)
class OnlyExecutionRecoveryEntry:
    execution_sequence: int
    broker_update_id: OnlyBrokerUpdateId
    trade_id: OnlyTradeId
    state: OnlyExecutionRecoveryEntryState
    stored: OnlyStoredExecutionTransaction
```

```python
@dataclass(frozen=True, slots=True)
class OnlyExecutionRecoveryPlan:
    runtime_id: OnlyRuntimeId
    checkpoint_sequence: int
    covered_execution_sequence: int
    entries: tuple[OnlyExecutionRecoveryEntry, ...]
```

Entry 顺序必须按照 Execution Sequence 严格排列。

---

# 七、Causal Recovery Session

新增：

```python
class OnlyExecutionRecoverySession:
    ...
```

至少提供：

```python
@property
def complete(self) -> bool:
    ...

@property
def next_entry(self) -> OnlyExecutionRecoveryEntry | None:
    ...

def require_expected(
    self,
    update: OnlyBrokerTradeUpdate,
    prepared: OnlyPreparedExecutionTransaction,
) -> OnlyExecutionRecoveryEntry:
    ...

def resolve(
    self,
    execution_sequence: int,
    resolution: OnlyExecutionRecoveryResolution,
) -> None:
    ...

def require_complete(self) -> None:
    ...
```

Session 必须维护：

* 当前期待的 Execution Sequence；
* 已恢复 Ready Transaction 数量；
* 已恢复 Unprojected Transaction 数量；
* 已处理 Entry；
* 当前是否允许创建新正式 Transaction；
* 当前 MarketData Boundary；
* 冲突诊断；
* Prepared Contract 验证结果。

删除 Runtime 中：

```python
_in_recovery_replay
_recovery_expected_update_ids
_recovery_seen_update_ids
```

不得使用多个集合代替 Recovery Session。

---

# 八、Prepared Transaction 完整一致性验证

Recovery Replay 重新产生 Broker Trade Update 时，必须：

```text
当前 Runtime Authority
→ 调用同一个 Planning Context Builder
→ 调用同一个 Trade Planner
→ 重新生成 OnlyPreparedExecutionTransaction
→ 与 Store 中原始 Prepared Transaction 完整比较
```

必须比较：

* Runtime ID；
* Gateway ID；
* Account ID；
* Broker Update ID；
* Trade ID；
* Transaction ID；
* Prepared Time；
* Execution Fact Draft；
* Projection Identity；
* Projection 顺序；
* Expected Before Payload；
* Expected Before Hash；
* Result After Payload；
* Result After Hash；
* Outbox Event ID；
* Authority Hash；
* Payload Hash。

要求：

```python
replayed_prepared == stored.prepared
```

同时重新验证 Canonical Payload Hash。

失败分类：

```text
对象不一致
→ RECOVERY_PREPARED_TRANSACTION_MISMATCH

对象一致但 Hash 不一致
→ RECOVERY_TRANSACTION_CODEC_OR_HASH_MISMATCH
```

不得只比较：

* Update ID；
* Trade ID；
* Payload Hash；
* Transaction ID。

---

# 九、ExecutionProcessor 恢复入口

## 9.1 所有 Broker Update 继续经过 ExecutionProcessor

删除 Runtime 外层直接查询 Store并跳过 Existing Transaction 的逻辑。

所有 Broker Update 必须继续经过唯一业务入口：

```text
OnlyExecutionProcessor
```

## 9.2 显式 Processing Mode

新增：

```python
class OnlyExecutionProcessingMode(StrEnum):
    NORMAL = "NORMAL"
    RECOVERY = "RECOVERY"
```

推荐接口：

```python
def process(
    self,
    update: OnlyBrokerInboundUpdate,
) -> OnlyExecutionProcessingResult:
    ...

def replay(
    self,
    update: OnlyBrokerInboundUpdate,
    session: OnlyExecutionRecoverySession,
) -> OnlyExecutionProcessingResult:
    ...
```

两者共享私有处理主链，不复制业务逻辑。

禁止使用全局或 Runtime 可变布尔开关隐式切换 Recovery 模式。

## 9.3 Recovery 中的非事务 Update

以下尚未正式事务化的 Update：

* Order Accepted；
* Order Rejected；
* Order Cancelled；
* Broker Account Update；
* Broker Position Update；
* Broker Connection Update。

Recovery Replay 中仍应通过现有业务路径处理，以恢复：

* Order；
* Reservation；
* Risk；
* Connection State；
* Reconciliation；
* Dedup；
* Sequence。

但历史 Direct Event 不得再次对外发布。

恢复模式必须区分：

```text
Business Mutation
Business Audit
External Event Delivery
```

恢复时：

```text
Business Mutation = 执行
Business Audit = 重建
External Event Delivery = 抑制
```

---

# 十、Ready Transaction 的因果 Rehydration

当 Recovery Replay 产生的 Broker Trade Update 对应一个 Store 中已 Ready 的 Transaction：

```text
重新生成 Prepared
→ 验证 Prepared Contract
→ 验证该 Entry 是 Session 下一个 Sequence
→ 使用 Stored Committed Transaction
→ 通过真实 Projection Applier 当场应用全部 Projection
→ 验证 Invariant
→ 不修改 Store Ready State
→ 不创建新 Outbox
→ 标记 Session Entry 已解决
→ 后续 Strategy 立即可见
```

不得返回普通：

```text
DUPLICATE
```

在业务语义上，该恢复处理应重建与 Baseline 相同的：

* Mutation Steps；
* Processing Status；
* Audit；
* Invariant；
* Manager Authority。

“本次处理属于恢复”应记录在 Operational Diagnostic，而不是修改业务状态为 Duplicate。

---

# 十一、Unprojected Transaction 的因果恢复

当 Entry 为 Unprojected：

```text
重新生成 Prepared
→ 与 Stored Prepared 完整比较
→ 验证 Sequence
→ 使用已有 Committed Transaction
→ 通过 Coordinator 当场应用 Projection
→ 标记 Projection Ready
→ 保留原 Outbox Row
→ 标记 Session Entry 已解决
→ 后续 Strategy 立即可见
```

为 Coordinator 增加明确单笔接口：

```python
def recover_existing(
    self,
    transaction: OnlyCommittedExecutionTransaction,
    *,
    projected_at: OnlyTimestamp,
) -> OnlyExecutionCommitCoordinationResult:
    ...
```

Runtime Restart 不再调用批量：

```python
recover_unprojected(runtime_id)
```

可以保留该批量接口供管理工具使用，前提是它不再是 Runtime Restart 产品主链；否则直接删除。

---

# 十二、Recovery Transaction 判定规则

## 12.1 Store 中存在且是下一个 Entry

```text
Prepared 一致
→ READY：当场 Rehydrate
→ UNPROJECTED：当场 Recover
```

## 12.2 Store 中存在但顺序错误

例如：

```text
Expected Sequence = 3
实际先出现 Sequence = 4
```

必须立即失败：

```text
RECOVERY_TRANSACTION_CAUSAL_ORDER_MISMATCH
```

不得缓存后面的 Transaction 等待前面出现。

## 12.3 Store 中不存在且 Tail 尚未完成

如果 Recovery Replay 产生一个符合正式 Transaction Planner 条件的新 Trade，但 Store 中没有对应 Transaction：

```text
RECOVERY_TRANSACTION_MISSING
```

这意味着：

* Strategy State 恢复错误；
* Broker Scheduler 恢复错误；
* MarketData State 恢复错误；
* ID Sequence 错误；
* Planner 行为变化；
* 配置或代码发生不兼容变化。

## 12.4 Tail 已完成后出现新 Transaction

Recovery Session 完成并越过最后一个 Tail Boundary 后：

```text
允许正常 Commit 新 Transaction
```

这表示 Engine 已进入恢复后的正常继续运行阶段。

## 12.5 Unmigrated Trade Path

Partial、SELL/CLOSE、Futures 等当前仍走非正式事务路径。

Recovery Replay 可以确定性重新执行这些路径，但：

* 不得称为正式 Transaction Recovery；
* 不得修改当前边界说明；
* 不得在 PR4.2.1 中顺带迁移这些业务类型。

---

# 十三、Recovery Replay 的停止边界

不能在看到最后一个 Tail Broker Update 后立即停止 Replay。

必须完成其所属的完整 MarketData Boundary：

```text
Broker Update Drain
→ Transaction Recovery
→ Strategy Callback
→ Broker run_due
→ Second Broker Drain
→ Timer Callback
→ MarketData Result Finalization
→ MarketData Audit
→ Result Progress
→ Internal Event Drain
→ Replay Cursor Advance
```

完成该 Boundary 后，再检查：

```text
Recovery Session Complete
```

否则可能遗漏：

* 最后一次成交后的 Strategy Order；
* Strategy Signal；
* Factor / Indicator 最终状态；
* Broker Scheduler 任务；
* Timer；
* Result Progress；
* MarketData Audit。

---

# 十四、MarketData Processing Finalization

## 14.1 当前 Checkpoint Barrier 必须后移

当前大致顺序：

```text
Pipeline
→ before_dispatch
→ Strategy Dispatch
→ after_dispatch
→ Checkpoint
→ MarketDataProcessor._finish
→ Audit
```

必须改为：

```text
Pipeline
→ before_dispatch
→ Strategy Dispatch
→ after_dispatch
→ 构建 Processing Result
→ 追加 MarketData Audit
→ 更新 Result Progress
→ 发布内部 MarketData Event
→ EventBus Drain
→ after_processing
→ Checkpoint Barrier
```

Checkpoint 必须是完整 MarketData Processing 的最后步骤。

## 14.2 Completion Model

新增：

```python
@dataclass(frozen=True, slots=True)
class OnlyBacktestBarCompletion:
    update_id: OnlyMarketDataUpdateId
    source_id: OnlyMarketDataSourceId
    data_version: OnlyDataVersion
    source_sequence: int
    processing_sequence: int
    status: OnlyMarketDataProcessingStatus
    ts_event: OnlyTimestamp
    result_progress_sequence: int
```

Checkpoint Barrier 改为：

```python
def _checkpoint_barrier(
    self,
    completion: OnlyBacktestBarCompletion,
) -> None:
    ...
```

Barrier 必须验证：

* MarketData Processing Result 已完成；
* MarketData Audit 已记录；
* Result Progress 已推进；
* Broker Queue 为空；
* MarketData Queue 为空；
* EventBus 已 Drain；
* Execution Transaction 是连续 Ready Prefix；
* Recovery Session 位于合法 Boundary；
* Completion 与 Replay Cursor Identity 一致。

---

# 十五、Backtest Result Progress

## 15.1 新增持久 Result Progress

新增：

```python
@dataclass(frozen=True, slots=True)
class OnlyBacktestResultProgressSnapshot:
    attempted_count: int
    applied_count: int
    duplicate_count: int
    gap_detected_count: int
    rejected_count: int
    failed_count: int
    processed_bar_count: int
    quality_flags: tuple[str, ...]
    business_failures: tuple[OnlyBacktestFailure, ...]
    last_market_processing_sequence: int
```

```python
class OnlyBacktestResultProgress:
    def observe_market_data_result(
        self,
        result: OnlyMarketDataProcessingResult,
    ) -> None:
        ...

    def capture_checkpoint(self) -> object:
        ...

    def restore_checkpoint(self, payload: object) -> None:
        ...

    def snapshot(self) -> OnlyBacktestResultProgressSnapshot:
        ...
```

注册：

```text
backtest.result-progress
```

为正式 Checkpoint Participant。

## 15.2 业务结果不再依赖瞬态历史

Result Collector 不得再将以下对象作为完整业务结果前缀的唯一来源：

```text
HistoricalReplayService.events
EventBus.dispatch_results
MarketDataAuditStore 内存历史
```

它们可以保留用于：

* Debug；
* Operational Diagnostics；
* 当前 Engine 运行分析。

业务 Result 应读取：

* Backtest Result Progress；
* Strategy Result Recorder；
* Ready Execution Transaction Store；
* Manager Authority；
* Account / Cluster Timelines；
* Market Rule Records；
* Settlement / Fee / Margin Records。

## 15.3 MarketData Audit

区分：

### 必须 Checkpoint 的业务信息

* Duplicate Count；
* Gap Count；
* Quality Flags；
* Rejected / Failed Count；
* Business Failure；
* Processing Sequence Head。

### 可以暂不 Checkpoint 的调试信息

* 全部 Raw Audit 明细；
* 内部调试消息；
* 每次函数调用的运维信息。

不要每 Bar 重复保存无限增长的完整 Raw Audit 历史。

---

# 十六、Cluster Recovery Lifecycle

## 16.1 不得恢复前调用正常 start_all

当前有 Checkpoint 时不应先调用正常：

```python
cluster_manager.start_all()
```

因为正常 `on_start()` 可能：

* 注册 Timer；
* 提交初始 Order；
* 记录 Signal；
* 修改 Strategy State；
* 产生外部副作用。

Checkpoint Restore 无法保证撤销这些副作用。

## 16.2 新生命周期

建议：

```text
CREATED
LOADED
INITIALIZED
RECOVERING
RECOVERED
RUNNING
PAUSED
STOPPED
FAILED
UNLOADED
```

恢复流程：

```text
on_initialize
→ Restore Checkpoint
→ RECOVERING
→ Recovery Replay
→ RECOVERED
→ Runtime READY
→ Resume Restored Cluster
→ RUNNING
```

恢复后不得再次调用普通 `on_start()`。

可以增加：

```python
def on_recovery_enter(self) -> None:
    ...

def on_recovery_complete(self) -> None:
    ...
```

默认实现不得产生业务副作用。

## 16.3 Recovery Callback 权限

`ClusterManager.execute_bar()` 和 Timer Execution 必须允许：

```text
RUNNING
RECOVERING
```

但 RECOVERING 模式下：

* 禁止外部控制命令；
* 禁止 Web/API 操作；
* 抑制历史外部事件；
* 允许 Strategy、Factor、Indicator 确定性计算；
* 允许 Virtual Broker 和 Order 重建；
* 允许正式 Transaction Recovery。

## 16.4 失败清理

Recovery 失败必须：

* Cluster 从 RECOVERING 转 FAILED；
* 停止已激活的 Cluster；
* 逆序清理 Plugin；
* 不进入 READY；
* 不发布 RUNTIME_STARTED；
* 不覆盖旧 Checkpoint；
* 不继续普通 Replay。

---

# 十七、Recovery Orchestrator 重构

当前 Orchestrator 不应继续持有：

```text
catch_up callback
batch ready rehydration
batch unprojected recovery
```

新结构建议：

```python
class OnlyRuntimeRecoveryOrchestrator:
    def recover(self) -> OnlyRuntimeRecoveryDiagnostic | None:
        checkpoint = self._checkpoint_loader.load_latest()
        if checkpoint is None:
            return None

        self._checkpoint_restorer.restore(checkpoint)

        plan = self._recovery_plan_builder.build(checkpoint)
        session = self._recovery_session_factory.create(plan)

        replay_result = self._recovery_replay.run(
            checkpoint.header.replay_cursor,
            session,
        )

        session.require_complete()

        self._authority_validator.validate(
            checkpoint,
            plan,
            replay_result,
        )

        return self._diagnostic_builder.build(...)
```

新增：

```text
OnlyExecutionRecoveryPlanBuilder
OnlyExecutionRecoverySession
OnlyExecutionRecoveryResolver
OnlyBacktestRecoveryReplayService
OnlyPostRecoveryAuthorityValidator
```

将 `_recover_market_data_tail()` 从 Runtime 中移出，避免 Runtime 持有大型恢复算法。

---

# 十八、Post-Recovery Authority Validation

创建新 Checkpoint 前，必须验证：

## 18.1 Transaction

* Recovery Session 已完成；
* Ready Tail 全部 Rehydrate；
* Unprojected Tail 全部恢复；
* Final Ready Sequence 等于 Tail 最后 Sequence；
* 不存在 Unprojected；
* 不存在 Sequence Gap；
* 没有额外正式 Transaction；
* 每个 Stored Prepared 均得到唯一匹配。

## 18.2 Account 与 Ledger

* Account Equity；
* Cash；
* Frozen Cash；
* Position Market Value；
* Account / Ledger 归约；
* Reservation；
* Fees；
* Realized / Unrealized PnL；
* Valuation Timeline Head。

## 18.3 Position 与 Allocation

* Position Quantity；
* Available Quantity；
* Frozen Quantity；
* Settlement Bucket；
* Allocation Total；
* Allocation 与 Position 归约。

## 18.4 Risk 与 Reservation

* Account Cash Reservation；
* Strategy Cash Reservation；
* Position Reservation；
* Margin Reservation；
* Risk Reservation；
* Risk Exposure；
* Order Mapping。

## 18.5 Runtime

* Replay Cursor；
* Clock；
* MarketData Processing Sequence；
* Execution Processing Sequence；
* Broker Queue 为空；
* MarketData Queue 为空；
* EventBus 为空；
* Broker Scheduler 稳定；
* Result Progress 已包含完整恢复 Boundary；
* Strategy / Factor / Indicator 可捕获 Checkpoint。

全部通过后才允许：

```text
Create Post-Recovery Checkpoint
```

---

# 十九、Outbox 与 Event Policy

## 19.1 Ready Transaction

Ready Transaction Rehydrate：

* 不创建新 Outbox；
* 不重置 Published；
* 不增加 Attempt Count；
* 不立即发布历史 Event；
* 不修改 Store Ready State。

## 19.2 Unprojected Transaction

恢复为 Projection Ready 后：

* 使用原 Outbox Row；
* 保持原 Event ID；
* 保持 Published 状态；
* 未发布 Row 保持 Pending；
* Recovery Replay 中不投递。

## 19.3 投递顺序

正式顺序：

```text
Recovery Complete
→ Authority Validation
→ Post-Recovery Checkpoint
→ Runtime READY
→ Drain Pending Outbox
→ Resume Restored Clusters
→ Runtime RUNNING
```

## 19.4 Non-Transaction Direct Event

Recovery Replay 中：

* 允许构造业务 Processing Result；
* 允许重建 Audit；
* 禁止向外部 Consumer 重复发布历史 Direct Event。

增加架构门禁：

> Authority Manager 不得依赖 EventBus Subscriber 修改核心业务状态。

---

# 二十、完整 Result Equivalence

## 20.1 业务与运维诊断分离

新增：

```python
@dataclass(frozen=True, slots=True)
class OnlyBacktestBusinessDiagnostics:
    failures: tuple[OnlyBacktestFailure, ...]
    warnings: tuple[OnlyBacktestWarning, ...]
```

```python
@dataclass(frozen=True, slots=True)
class OnlyBacktestOperationalDiagnostics:
    recoveries: tuple[OnlyRuntimeRecoveryDiagnostic, ...]
    checkpoint_writes: tuple[OnlyCheckpointDiagnostic, ...]
    delivery_attempts: tuple[OnlyExecutionDeliveryDiagnostic, ...]
```

不要再通过：

```python
replace(result.diagnostics, execution_recoveries=())
```

临时删除恢复字段后计算 Fingerprint。

业务 Fingerprint 的输入类型本身就不应包含 Operational Diagnostics。

## 20.2 Canonical Business Projection

新增唯一函数：

```python
def only_backtest_business_projection(
    result: OnlyBacktestResult,
) -> Mapping[str, object]:
    ...
```

以下功能统一使用该 Projection：

* Result Fingerprint；
* Determinism Fingerprint；
* Restart Equivalence Test；
* Scenario Repeatability；
* Artifact Manifest Business Hash；
* Result Comparison。

不得在不同模块手工维护不同字段列表。

## 20.3 必须完全等价的字段

Recovered 与 Baseline 必须逐字段相等：

```text
Status
Run Summary
Data Source ID
Data Version
Generated Count
Processed Count
Duplicate Count
Gap Count
Quality Flags
Execution Summary
Final Account
Final Positions
Final Allocations
Final Ledgers
Orders
Trades
Runtime Performance
Cluster Performance
Account Equity Timeline
Cluster Equity Timelines
Strategy Result Extension
Factor Snapshots
Indicator Snapshots
Reconciliation
Invariant Results
Standard Facts
Business Diagnostics
Determinism Fingerprint
Result Fingerprint
```

## 20.4 允许不同的字段

只允许以下运维字段不同：

```text
Checkpoint Sequence
Recovery Diagnostic
Outbox Attempt Count
Engine Instance Identity
Wall-clock Duration
实际 Artifact 路径
SQLite Connection Identity
```

---

# 二十一、Cursor 与 DataSource

当前 Runtime 已能用：

```text
source_id
data_version
update_id
source_sequence
```

在 Historical Stream 中定位 Cursor 后的第一条记录。

本任务必须保留这一精确语义。

可以新增 Source-level Cursor Pushdown：

```python
source.load_bars(
    request,
    resume_after=cursor,
)
```

但它是性能优化，不应阻塞因果恢复主链。

无论是否实现 Pushdown，都必须保证：

* 不重复业务处理 Checkpoint 前的 Bar；
* Result Progress 包含 Checkpoint 前累计值；
* Data Summary 与 Baseline 等价；
* 同时间戳 Update 不会被错误跳过。

---

# 二十二、故障注入要求

故障注入只能位于测试代码。

允许：

```text
OnlyFailOnceRuntimePersistenceStore
OnlyFailOnceProjectionTarget
OnlyFailOnceCheckpointParticipant
OnlyFailAtMarketDataCompletion
OnlyFailAfterAuditBeforeCheckpoint
OnlyFailAfterCheckpointCommit
```

禁止生产配置出现：

```text
simulate_crash
fail_after_transaction
fail_after_audit
recovery_test_mode
skip_projection
```

测试必须通过正式 Composition Root 注入。

不得：

* 修改 Runtime 私有字段；
* 修改 Cluster 私有状态；
* 从 Engine A 复制对象到 Engine B；
* 手工调用 Recovery Session；
* 手工 Rehydrate Manager；
* 手工设置 Replay Cursor；
* 直接构造 Runtime 绕过 Engine。

---

# 二十三、必须新增的测试

## 23.1 Ready Transaction 在 Strategy 前生效

场景：

```text
Checkpoint 中存在 Accepted Open Order

Recovery Bar:
→ Virtual Broker before Strategy 产生 Fill
→ Fill 对应 Ready Transaction
→ Transaction 当场 Rehydrate
→ Strategy.on_bar 查询 Position
→ Position > 0 时提交第二个 Order
```

验证：

* Strategy 确实看到 Position；
* 第二个 Order 与 Baseline 相同；
* Order ID 相同；
* Signal 相同；
* 后续 Transaction 相同。

当前旧实现应无法通过此测试。

## 23.2 Ready + Unprojected 因果链

```text
Transaction 1 Ready
Transaction 2 Unprojected
```

要求：

```text
Broker Update 1
→ Rehydrate Transaction 1
→ 后续逻辑读取 Transaction 1 After

Broker Update 2
→ Recover Transaction 2
```

不得在 Replay 完成后统一处理。

## 23.3 多 Ready Tail

至少：

```text
Transaction 1 Ready
Transaction 2 Ready
Transaction 3 Ready
```

并让 Transaction 2 的 Expected Before 依赖 Transaction 1 After。

严格验证顺序。

## 23.4 多 Unprojected Tail

至少：

```text
Transaction 1 Ready
Transaction 2 Unprojected
Transaction 3 Unprojected
```

逐笔恢复并验证 Sequence。

## 23.5 Missing Transaction

Recovery Replay 产生 Store 中不存在的正式 Prepared Transaction。

必须失败：

```text
RECOVERY_TRANSACTION_MISSING
```

## 23.6 Prepared Conflict

改变以下任意一项：

* Price；
* Quantity；
* Fee；
* Before Authority；
* Projection；
* Event ID；
* Transaction ID。

必须失败：

```text
RECOVERY_PREPARED_TRANSACTION_MISMATCH
```

## 23.7 Transaction 顺序冲突

Store 期望 Sequence 3，但 Replay 先产生 Sequence 4 对应 Update。

必须失败：

```text
RECOVERY_TRANSACTION_CAUSAL_ORDER_MISMATCH
```

## 23.8 on_start 不重复

Strategy 和 Factor 的 `on_start()` 保存计数器或注册 Timer。

Engine Restart 后：

```text
Recovered on_start count == Baseline on_start count
```

## 23.9 Result Progress 前缀

Checkpoint 前制造：

* Duplicate；
* Gap；
* Quality Flag；
* 可记录的 MarketData Failure。

恢复后比较完整：

* Data Summary；
* Quality；
* Business Diagnostics；
* Facts。

## 23.10 Audit 后、Checkpoint 前故障

故障点：

```text
MarketData Result 完成
→ Audit 已写
→ Result Progress 已更新
→ Checkpoint 尚未开始
→ Crash
```

恢复后该 Bar 的业务结果只能出现一次。

## 23.11 Checkpoint Commit 后故障

```text
Checkpoint COMMIT 成功
→ Runtime 尚未返回
→ Crash
```

Engine B 必须从新 Cursor 继续，不重复该 Bar。

## 23.12 三次 Engine Restart

```text
Engine A
→ Crash

Engine B
→ Recover
→ Continue
→ Crash

Engine C
→ Recover
→ Complete
```

完整业务结果必须等于无故障 Baseline。

## 23.13 完整 Result 比较

测试必须使用：

```python
assert only_backtest_business_projection(recovered) == (
    only_backtest_business_projection(baseline)
)
```

不得只比较 `result_fingerprint`。

## 23.14 Artifact 等价

比较规范化后的：

* JSON Rows；
* Parquet Rows；
* Facts；
* Timelines；
* Manifest Business Hash。

排除：

* 实际目录；
* Recovery Operational Diagnostic；
* Checkpoint Sequence。

---

# 二十四、架构门禁

新增或更新架构测试，至少保证：

1. Runtime 不再包含 `_in_recovery_replay`；
2. Runtime 不再包含 `_recovery_expected_update_ids`；
3. Runtime 不再包含 `_recovery_seen_update_ids`；
4. Runtime 不直接跳过 Existing Transaction；
5. 所有 Broker Update 都经过 ExecutionProcessor；
6. Runtime Restart 不使用 Batch Ready Rehydration；
7. Runtime Restart 不使用 Batch Unprojected Recovery；
8. Recovery 使用 Stored Prepared + Committed；
9. Recovery Prepared Contract 完整比较；
10. Ready Transaction 在原 Broker Update 时点 Rehydrate；
11. Unprojected Transaction 在原 Broker Update 时点 Recover；
12. Ready Rehydrate 不创建 Outbox；
13. Ready Rehydrate 不修改 Ready State；
14. Recovery 不把 Ready Transaction 标记为普通 Duplicate；
15. Tail 未完成时不允许新正式 Transaction；
16. Transaction Sequence 必须严格递增；
17. Checkpoint 在 MarketData Audit 后；
18. Checkpoint 在 Result Progress 更新后；
19. Checkpoint 在 EventBus Drain 后；
20. Backtest Result Progress 是 Checkpoint Participant；
21. Business Result 不依赖 HistoricalReplayService.events 作为唯一前缀；
22. Business Result 不依赖 EventBus.dispatch_results 作为唯一序列源；
23. 恢复前不调用正常 Cluster.start_all；
24. 恢复后不重复 Strategy.on_start；
25. Recovery Failure 正确停止 Cluster；
26. Operational Diagnostics 不进入 Business Fingerprint；
27. 所有 Fingerprint 使用唯一 Canonical Business Projection；
28. Restart Test 不访问 Runtime 私有字段；
29. Restart Test 不直接构造 Runtime；
30. Restart Test 不手工调用 Recovery；
31. 不存在生产故障开关；
32. 不存在旧恢复 Alias；
33. 不为了旧测试保留两套恢复实现。

---

# 二十五、建议目录结构

根据当前工程结构调整，建议：

```text
src/onlyalpha/execution/recovery/
├── model.py
├── plan.py
├── session.py
├── resolver.py
└── errors.py

src/onlyalpha/runtime/backtest/
├── recovery_replay.py
├── result_progress.py
├── completion.py
├── runtime.py
└── run_plan.py

src/onlyalpha/runtime/recovery/
├── orchestrator.py
├── authority_validator.py
└── diagnostics.py

src/onlyalpha/result/
├── business_projection.py
└── diagnostics.py
```

如果文件过小，应按职责合并，不要产生大量空壳模块。

建议删除或停止产品主链使用：

```text
src/onlyalpha/runtime/recovery/ready_tail_rehydration.py
```

---

# 二十六、实施顺序

## Step 1：预实现审计

完成完整 Bar Phase、Recovery Path、Result Source 和 Cluster Lifecycle 审计。

## Step 2：先编写红色因果测试

建立：

```text
Ready Fill before Strategy
→ Strategy depends on restored Position
```

保证当前实现测试失败。

## Step 3：Store Recovery Record

实现：

* Stored Prepared + Committed；
* Recovery Query Port；
* Memory/SQLite Contract；
* Codec 和 Hash 测试。

## Step 4：Recovery Plan / Session

实现：

* Strict Sequence；
* Entry State；
* Update Index；
* Resolution；
* Missing / Conflict；
* Complete。

## Step 5：ExecutionProcessor Recovery Mode

实现：

* Normal / Recovery 显式入口；
* Prepared Rebuild；
* Ready Rehydrate；
* Unprojected Recover；
* Non-Transaction Replay；
* External Event Suppression。

## Step 6：删除旧 Batch 主链

删除：

* Runtime Recovery Sets；
* Runtime Existing Transaction Skip；
* Replay 后 Batch Rehydrate；
* Replay 后 Batch Recover。

## Step 7：MarketData Completion

将 Audit、Result Progress、Event Finalization 放在 Checkpoint 之前。

## Step 8：Backtest Result Progress

实现：

* Count；
* Quality；
* Failure；
* Sequence；
* Checkpoint；
* Restore；
* Collector 接入。

## Step 9：Cluster Recovery Lifecycle

实现：

* RECOVERING；
* RECOVERED；
* Recovery Callback；
* Resume Restored；
* Failure Cleanup。

## Step 10：Canonical Business Projection

统一：

* Fingerprint；
* Restart Equality；
* Scenario；
* Artifact；
* Manifest。

## Step 11：Authority Validation

恢复后执行完整 Transaction、Manager、Runtime 和 Result Progress 验证。

## Step 12：故障矩阵

覆盖：

* Ready；
* Unprojected；
* Multi Tail；
* Missing；
* Conflict；
* Audit/Checkpoint Window；
* Multiple Restart；
* Full Result；
* Artifact。

## Step 13：删除旧代码

彻底删除已失效实现、测试和文档描述。

## Step 14：更新 ADR 和文档

记录新因果恢复模型。

---

# 二十七、文档要求

新增 ADR：

```text
docs/adr/0045-causal-recovery-and-complete-result-equivalence.md
```

更新：

```text
README.md
docs/roadmap.md
docs/execution_runtime_recovery.md
docs/backtest.md
docs/architecture.md
```

ADR 必须说明：

1. 为什么 Replay 后批量 Rehydrate 是错误的；
2. 为什么不能 Replay 前提前应用全部 Tail；
3. Recovery Session 的职责；
4. Stored Prepared Contract 的作用；
5. Ready 和 Unprojected 的处理区别；
6. 为什么 Recovery Broker Update 必须经过 ExecutionProcessor；
7. 为什么 Checkpoint Barrier 必须位于 Audit 和 Result Progress 后；
8. Result Progress 为什么必须 Checkpoint；
9. Business 与 Operational Diagnostics 的区别；
10. Cluster 恢复为什么不能重复 `on_start()`；
11. 完整 Result Equivalence Contract；
12. 当前仍未覆盖的 Transaction 类型。

---

# 二十八、本阶段不实现

本任务不顺带实现：

* Partial / Multi-Fill 正式 Transaction；
* SELL / CLOSE 正式 Transaction；
* Futures / Margin Transaction；
* Non-Trade Transaction；
* Paper Recovery；
* Live Recovery；
* Exactly-once Outbox；
* Schema Migration；
* Distributed Checkpoint；
* Full Broker Reconciliation；
* Remote Store；
* Web State Recovery。

这些能力仍必须在 README、Roadmap 和最终报告中明确列为未完成。

---

# 二十九、测试命令

执行当前项目完整门禁。

至少包括：

```bash
uv lock --check
uv sync --frozen --all-packages --all-groups

uv run ruff check src tests examples packages
uv run ruff format --check src tests examples packages

uv run mypy src/onlyalpha
uv run mypy packages/fake/onlyalpha-plugin-broker-virtual/src
uv run mypy packages/provider/onlyalpha-plugin-tushare/src/onlyalpha_plugin_tushare
uv run mypy packages/provider/onlyalpha-plugin-miniqmt/src/onlyalpha_plugin_miniqmt

uv run pytest tests/runtime/checkpoint -q
uv run pytest tests/runtime/recovery -q
uv run pytest tests/execution -q
uv run pytest tests/result -q

uv run pytest tests/integration/test_engine_recovery_causal_ordering.py -q
uv run pytest tests/integration/test_engine_complete_result_equivalence.py -q
uv run pytest tests/integration/test_engine_multiple_causal_restart.py -q
uv run pytest tests/integration/test_engine_recovery_result_progress.py -q
uv run pytest tests/integration/test_engine_recovery_checkpoint_window.py -q

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

根据项目实际测试目录调整命令。

不得伪造未执行的测试结果。

---

# 三十、完成标准

只有全部满足以下条件，才能声明 PR4.2.1 完成：

1. Recovery Replay 不再跳过 Existing Transaction；
2. Ready Transaction 在原 Broker Update 时点 Rehydrate；
3. Unprojected Transaction 在原 Broker Update 时点恢复；
4. 后续 Strategy Callback 立即看到更新后的 Authority；
5. Recovery 使用 Store 中完整 Prepared Contract；
6. Replay Prepared 与 Stored Prepared 完整一致；
7. Transaction Sequence 严格递增；
8. Missing Transaction 明确失败；
9. Prepared Conflict 明确失败；
10. Causal Order Conflict 明确失败；
11. Ready Rehydrate 不修改 Ready State；
12. Ready Rehydrate 不创建 Outbox；
13. Unprojected Recovery 使用原 Transaction；
14. 所有 Broker Update 仍经过 ExecutionProcessor；
15. Non-Transaction Update 可确定性重放；
16. 历史 Direct Event 不重复对外发布；
17. Recovery Session 替代 Runtime 临时集合；
18. Runtime 不再使用 Batch Ready Rehydration；
19. Runtime 不再使用 Batch Unprojected Recovery；
20. Recovery Replay 完成整个 MarketData Boundary；
21. Checkpoint 在 MarketData Processing Result 后；
22. Checkpoint 在 MarketData Audit 后；
23. Checkpoint 在 Result Progress 后；
24. Checkpoint 在 EventBus Drain 后；
25. Backtest Result Progress 是 Checkpoint Participant；
26. Duplicate Count 可恢复；
27. Gap Count 可恢复；
28. Quality Flags 可恢复；
29. Business Failure 可恢复；
30. Business Result 不依赖瞬态 Event 历史；
31. Cluster Recovery 不调用普通 `on_start()`；
32. Recovery Replay 可执行 Strategy/Factor/Indicator Callback；
33. Recovery 失败时 Cluster 正确清理；
34. Post-Recovery Authority Validation 完成；
35. Post-Recovery Checkpoint 覆盖全部 Tail；
36. Pending Outbox 只在 READY 后投递；
37. Business Diagnostics 与 Operational Diagnostics 分离；
38. 存在唯一 Canonical Business Projection；
39. Fingerprint 使用 Canonical Business Projection；
40. Artifact Business Hash 使用相同 Projection；
41. 完整 Result 与 Baseline 逐字段等价；
42. Artifact Business Content 与 Baseline 等价；
43. Ready + Unprojected 因果测试通过；
44. 三笔以上 Ready Tail 测试通过；
45. 多 Unprojected Tail 测试通过；
46. Missing Transaction 测试通过；
47. Prepared Conflict 测试通过；
48. Audit/Checkpoint Window 测试通过；
49. Checkpoint Commit 后故障测试通过；
50. Engine A → B → C 多次重启测试通过；
51. 不访问 Runtime 私有字段；
52. 不直接构造 Runtime；
53. 不手工调用 Recovery；
54. 不保留旧恢复 Alias；
55. 不保留两套恢复主链；
56. 不增加生产故障开关；
57. Ruff、Mypy、Pytest 和 Architecture Gate 全部通过。

---

# 三十一、禁止的实现

以下任一情况视为任务失败：

```text
继续保留 Runtime Existing Transaction Skip
只把 Recovery Set 换成 dict
Replay 结束后再统一 Rehydrate
Replay 结束后再统一 Recover
Replay 前提前应用全部 Tail
Ready Transaction 当普通 Duplicate
只比较 Broker Update ID
只比较 Transaction ID
只比较 Prepared Hash
不重新运行 Planner
通过 Manager 私有字段安装 After Snapshot
Recovery 绕过 ExecutionProcessor
Recovery 中重新 Commit 已存在 Transaction
Ready Rehydrate 新建 Outbox
Recovery 重复发布历史 Direct Event
Tail 未完成时允许新正式 Transaction
Transaction 顺序错误时缓存等待
Checkpoint 仍位于 MarketData Audit 之前
Result 仍只依赖当前 Replay Count
Result 仍依赖 EventBus.dispatch_results 作为唯一序列
用 Result Fingerprint 掩盖字段不一致
恢复时重复调用 Strategy.on_start
恢复失败后 Cluster 仍处于 RUNNING
为了旧测试保留 Batch Recovery
为了兼容旧代码保留 Deprecated Alias
使用生产配置故障开关
测试修改 Runtime 私有字段
测试复制 Engine A 对象到 Engine B
测试手工设置 Replay Cursor
```

---

# 三十二、最终交付报告

完成后输出结构化报告。

## 1. 修改前根因

说明：

* Replay 后 Batch Recovery；
* Strategy 观察旧 Authority；
* Checkpoint Barrier 过早；
* Result Progress 不完整；
* Cluster 重复 Start；
* Fingerprint 覆盖不足。

## 2. 新因果恢复模型

说明：

```text
Checkpoint
→ Recovery Plan
→ Recovery Session
→ Broker Update-time Resolution
→ Full Boundary Completion
→ Result Progress
→ Post-Recovery Checkpoint
```

## 3. Stored Prepared Contract

说明 Store、Codec、Hash 和完整比较。

## 4. ExecutionProcessor Recovery Mode

说明：

* Ready；
* Unprojected；
* Non-Transaction；
* Missing；
* Conflict；
* New Transaction。

## 5. Stable Bar Completion

说明 Audit、Result Progress、Event Drain 和 Checkpoint 顺序。

## 6. Cluster Lifecycle

说明新 Runtime 与恢复 Runtime 的启动区别。

## 7. Result Equivalence

列出完整业务结果 Projection 和允许排除的 Operational 字段。

## 8. 删除内容

列出删除的：

* 字段；
* 服务；
  -批量恢复路径；
* 旧测试；
* Alias；
* 文档描述。

## 9. 测试结果

给出真实命令和结果。

## 10. 剩余边界

明确仍未实现：

* Partial / Multi-Fill Transaction；
* SELL / CLOSE Transaction；
* Futures / Margin Transaction；
* Non-Trade Transaction；
* Paper / Live Recovery；
* Exactly-once Outbox；
* Schema Migration；
* Distributed Checkpoint；
* Full Broker Reconciliation；
* Remote Store；
* Web Recovery。

---

# 三十三、最终架构结论

完成后，OnlyAlpha 的恢复模型必须从：

```text
Restore Checkpoint
→ Replay and skip Existing Transactions
→ Batch Rehydrate after Replay
```

升级为：

```text
Restore Checkpoint
→ Build Causal Recovery Session
→ Replay exact MarketData sequence
→ Rebuild Prepared Transaction at each Broker Update
→ Validate against durable Stored Prepared
→ Rehydrate or Recover at the original causal point
→ Allow later Strategy decisions to observe restored Authority
→ Complete MarketData Result/Audit/Progress
→ Validate Authority
→ Write Post-Recovery Checkpoint
→ Continue normal Backtest
→ Produce complete Baseline-equivalent business result
```

最终必须证明：

> 新 Engine 仅凭同一配置、同一 user_data、最新完整 Checkpoint 和持久 Execution Transaction Tail，就能按照原运行相同的 MarketData、Broker Update、Transaction 和 Strategy Callback 因果顺序重建 Runtime Authority；恢复过程中的所有后续决策、订单、成交、统计、事实和业务诊断均与无故障 Baseline 完全一致。
