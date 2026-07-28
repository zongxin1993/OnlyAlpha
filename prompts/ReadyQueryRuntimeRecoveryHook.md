# OnlyAlpha PR4.1：Ready Query、Runtime Recovery Hook 与真实故障矩阵

## 一、任务目标

以当前 OnlyAlpha 仓库 `master` 分支的真实源码、测试和已接受 ADR 为唯一事实源，从第一性原理出发，完成 PR4.1：

```text
1. Projection Ready 业务查询边界
2. Runtime 自动恢复 Hook
3. 基于真实 Manager / Target / Store 的完整故障矩阵
```

当前 PR4 已实现：

```text
Broker Trade Update
→ Pure Planner
→ Prepared Transaction
→ Transaction Store Commit
→ Runtime Sequence Gate
→ Ordered Projection Targets
→ Projection Ready
→ Durable Outbox
```

但当前仍存在三个问题：

```text
A. 普通 records() 查询会返回未 Projection Ready 的事务
B. Runtime 启动时不会自动 recover_unprojected()
C. Coordinator 故障测试主要使用 Reference Target，尚未充分验证真实 Manager 前向恢复
```

本任务必须解决以上问题。

本任务不扩展新的成交业务范围，不实现 Partial Fill、SELL、CLOSE、Futures 或完整 Bootstrap Snapshot。

最终目标是形成以下可靠边界：

```text
Committed Transaction
    │
    ├── projection_ready = false
    │       只能被 Coordinator、Recovery、Admin、Diagnostic 查询
    │
    └── projection_ready = true
            才能被 Result、Collector、Analytics、Artifact、Report、
            Scenario、Application Query 和 Outbox Publisher 使用
```

以及：

```text
Runtime Bootstrap Authority Ready
→ 自动恢复最早的未完成 Transaction
→ 严格按 execution_sequence 前向恢复
→ 全部 Projection Ready
→ 发布 Durable Outbox
→ Runtime 才允许进入 RUNNING
```

---

# 二、工作原则

## 1. 当前源码优先

判断工程真实行为时，使用以下优先级：

```text
当前生产源码和实际调用关系
→ 当前测试
→ 已接受 ADR
→ 当前架构文档
→ README / AGENTS
→ reports / prompts / 历史说明
```

不得机械复制历史 Prompt。

编码前必须重新检查当前 `master`，确认 PR4 后是否又发生修改。

## 2. 从第一性原理出发

首先回答：

1. Durable Commit 和 Projection Ready 分别代表什么？
2. 哪些调用方需要读取全部 committed transaction？
3. 哪些调用方只允许读取完整业务成交？
4. Runtime 在哪个生命周期阶段拥有正确 Bootstrap Authority？
5. Recovery 失败时 Runtime 是否允许开始处理新行情和 Broker Update？
6. Projection Recovery 和 Outbox Delivery Failure 是否属于同一种失败？
7. Manager Authority 已安装但 Applied Ledger 未记录时，如何判断是恢复而不是重复执行？
8. 如何证明真实 Manager 不会重复扣款、重复加仓、重复收费或重复追加 Timeline？
9. 哪些恢复能力属于 PR4.1，哪些属于后续 Full Runtime Recovery？
10. 如何保证测试故障注入不会污染生产代码？

实现必须基于这些问题确定边界。

## 3. 不考虑旧接口兼容

本任务不需要保留旧接口兼容性。

不得为了旧测试、旧 Fixture、旧调用方或旧公开导出保留模糊边界。

如果现有：

```text
committed_execution_query
records()
```

同时承担管理查询和业务查询，应直接拆分并迁移调用方。

禁止增加：

* Legacy alias；
* Deprecated wrapper；
* 新旧 Query 双路径；
* `ready_only: bool = False` 之类容易误用的默认参数；
* Feature flag；
* Runtime 可选 Recovery；
* Recovery 失败后继续启动；
* 测试专用生产代码分支；
* 通过环境变量开启故障；
* 兼容旧 RuntimeServices 构造参数。

测试和示例必须迁移到正确接口。

## 4. 不扩展业务范围

PR4.1 不实现：

* BUY Partial Fill；
* Multi Fill；
* SELL；
* CLOSE；
* Position Reservation Transaction；
* Futures；
* Margin Transaction；
* 多 Cluster Transaction；
* Non-Trade Transaction；
* Bootstrap Snapshot；
* Paper Runtime；
* Live Runtime；
* Web。

当前 Generic T0 Cash、LIMIT、BUY、OPEN、整单成交的事务范围保持不变。

---

# 三、修改前必须完成的源码审计

编码前执行：

```bash
git status
git log -n 20 --oneline

rg "OnlyExecutionTransactionQueryPort"
rg "committed_execution_query"
rg "\\.records\\("
rg "projection_ready"
rg "ready_records"
rg "OnlyExecutionCommitCoordinator"
rg "recover_unprojected"
rg "OnlyRuntimeServices"
rg "def initialize"
rg "def start"
rg "_drain_execution_outbox"
rg "OnlyExecutionProjectionTarget"
rg "OnlyInMemoryAppliedProjectionLedger"
rg "only_create_generic_t0_execution_projection_targets"
rg "OnlyReferenceExecutionProjectionTarget"
rg "OnlySqliteExecutionTransactionStore"
rg "OnlyBacktestResultCollector"
rg "committed_trade_fees"
rg "OnlyScenarioFactType.EXECUTION"
```

必须明确记录：

1. 哪些调用方直接调用 `records()`；
2. 哪些调用方属于业务读取；
3. 哪些调用方属于管理、恢复或诊断读取；
4. 当前 Runtime 在哪里构造 Coordinator；
5. Coordinator 是否只作为局部变量存在；
6. Runtime 当前在哪一步 drain Outbox；
7. Runtime 是否在 Cluster 启动前恢复；
8. 当前故障测试使用 Reference Target 还是 Real Target；
9. 哪些真实 Target 有“Manager 安装后、Applied Ledger 记录前”的故障窗口；
10. In-memory 和 SQLite Store 当前 Query 语义是否一致；
11. Result、Analytics、Artifact、Report、Scenario 是否可能读取未 Ready 事务；
12. Runtime 失败后是否仍可能构建部分 Result。

将审计结果写入：

```text
docs/reports/pr4_1_ready_query_runtime_recovery_pre_implementation_audit.md
```

内容应引用真实文件、类、方法和调用点，不写泛化描述。

---

# 四、目标架构

## 1. 查询边界

目标拆分为：

```text
OnlyExecutionTransactionQueryPort
    管理和恢复查询
    可以读取全部 committed transaction

OnlyProjectionReadyExecutionQueryPort
    业务结果查询
    只能读取 projection_ready = true 的 transaction

OnlyExecutionProjectionStatePort
    mark ready / mark failed / unprojected

OnlyExecutionTransactionOutboxPort
    pending / attempt / published / failed
```

业务读取链：

```text
Projection Ready Query
→ Collector
→ Backtest Result
→ Analytics
→ Scenario Facts
→ Artifact
→ Report
→ Application Query
```

恢复链：

```text
Transaction Query + Projection State
→ Execution Recovery Service
→ Commit Coordinator
→ Projection Targets
```

## 2. Runtime 生命周期

目标生命周期：

```text
CREATED
→ Runtime / Manager / Cluster Bootstrap Authority 构建
→ Plugin Resource initialize/connect
→ Cluster initialize
→ Execution Recovery
→ READY
→ Plugin Resource start
→ Recovered Outbox Delivery
→ Cluster start
→ RUNNING
```

恢复失败：

```text
Execution Recovery Failed
→ Runtime FAILED
→ Cluster 不启动
→ 不发布 RUNTIME_STARTED
→ 不处理新行情
→ 不处理新 Broker Update
```

## 3. 恢复语义

```text
Transaction Store
    唯一 durable Trade authority

Manager
    Runtime 当前业务 Authority

Applied Projection Ledger
    可重建幂等索引，不是持久业务真值

Recovery
    committed transaction tail 的 deterministic forward recovery
```

本任务仍不声称：

```text
Empty Runtime
+ Transaction Store
→ Full Runtime Recovery
```

---

# 五、实现 Projection Ready Query

## 1. 新增正式业务查询 Port

实现：

```python
class OnlyProjectionReadyExecutionQueryPort(Protocol):
    def ready_records(
        self,
        runtime_id: OnlyRuntimeId | None = None,
        *,
        after_sequence: int = 0,
    ) -> tuple[OnlyCommittedExecutionTransaction, ...]:
        ...

    def ready_count(
        self,
        runtime_id: OnlyRuntimeId | None = None,
    ) -> int:
        ...
```

接口命名可以根据现有风格调整，但必须明确表达：

```text
这里只返回 Projection Ready Transaction
```

不得使用：

```python
records(ready_only: bool = False)
```

不得让业务调用方通过参数自行决定是否过滤。

## 2. 保留 Admin Transaction Query

现有：

```python
OnlyExecutionTransactionQueryPort.records()
```

继续表示全部 committed transaction。

它只允许被以下组件使用：

* Coordinator；
* Recovery；
* Admin；
* Diagnostic；
* Store Contract Test；
* 运维查询。

不要让 Collector、Result、Analytics、Scenario、Artifact 或 Report 使用它。

## 3. In-memory 实现

`OnlyInMemoryExecutionTransactionStore.ready_records()` 必须：

* 在锁内执行；
* 过滤 `projection_ready=True`；
* 支持 Runtime Scope；
* 支持 `after_sequence`；
* 保证排序稳定；
* 不返回浅层临时状态；
* 与 `records()` 语义明确分离。

排序必须为：

```text
runtime_id
→ execution_sequence
```

当指定 Runtime 时按：

```text
execution_sequence
```

## 4. SQLite 实现

使用 SQL 过滤：

```sql
WHERE projection_ready = 1
```

不要加载所有事务后在 Python 中过滤。

必须验证：

* 重启后 ready 状态保持；
* failed/unprojected 不进入 ready query；
* Ready Transaction 的 payload 和 hash 无损；
* In-memory 与 SQLite 返回顺序一致。

## 5. 调用方迁移

必须审计并迁移：

```text
OnlyBacktestResultCollector
OnlyBacktestRunPlan
OnlyBacktestResult
OnlyScenario Fact Collector
OnlyAnalytics
OnlyArtifact Writer
OnlyReport Builder
OnlyRuntimeLedgerReconciliationService 的 Trade Fee 输入
Application Execution Query
所有正式 trade_count 统计
所有 committed execution fingerprint
```

所有正式业务成交读取必须从 Ready Query 获取。

不得在调用方中自行写：

```python
tuple(item for item in records() if item.projection_ready)
```

过滤必须由 Query Port 保证。

## 6. RuntimeServices 命名收口

当前模糊字段如：

```python
committed_execution_query
```

应拆成明确职责，例如：

```python
execution_transaction_query
ready_execution_query
execution_projection_state
execution_transaction_outbox
```

如果 Store 实例同时实现多个 Port，RuntimeServices 仍应使用不同类型字段表达不同职责。

不得继续让调用方通过一个 Store 对象随意调用任何方法。

## 7. Ready Query 测试

对 In-memory 和 SQLite 运行相同 Contract：

准备：

```text
sequence 1 = ready
sequence 2 = projection failed
sequence 3 = committed but never projected
sequence 4 = ready
```

验证：

```text
records()       → 1,2,3,4
unprojected()   → 2,3
ready_records() → 1,4
ready_count()   → 2
pending()       → 只返回 1、4 的未发布事件
```

再验证 Runtime Scope 和 `after_sequence`。

---

# 六、实现 Execution Recovery Service

## 1. 不让 Runtime 直接解释 Coordinator 结果

新增正式组件，建议：

```text
src/onlyalpha/execution/recovery.py
```

实现：

```python
class OnlyExecutionRecoveryService:
    def __init__(
        self,
        *,
        coordinator: OnlyExecutionCommitCoordinator,
        transaction_query: OnlyExecutionTransactionQueryPort,
        projection_state: OnlyExecutionProjectionStatePort,
    ) -> None:
        ...

    def recover(
        self,
        runtime_id: OnlyRuntimeId,
        *,
        limit: int | None = None,
    ) -> OnlyExecutionRecoveryResult:
        ...
```

如果 `transaction_query` 或 `projection_state` 不需要单独注入，不要为了形式增加无用依赖。

Recovery Service 应封装：

* 获取未完成事务；
* 按 sequence 恢复；
* 判断完成、阻断和失败；
* 生成稳定诊断；
* 返回 Runtime 可直接判断的结果。

## 2. Recovery Result

实现不可变强类型结果：

```python
class OnlyExecutionRecoveryStatus(StrEnum):
    NO_WORK = "NO_WORK"
    RECOVERED = "RECOVERED"
    FAILED = "FAILED"
    SEQUENCE_BLOCKED = "SEQUENCE_BLOCKED"
    STORE_FAILURE = "STORE_FAILURE"
```

```python
@dataclass(frozen=True, slots=True)
class OnlyExecutionRecoveryResult:
    runtime_id: OnlyRuntimeId
    status: OnlyExecutionRecoveryStatus
    attempted_transactions: int
    completed_transactions: int
    recovered_transactions: int
    idempotent_transactions: int
    failed_sequence: int | None
    blocked_sequence: int | None
    failure_component: OnlyExecutionProjectionComponent | None
    error: str | None
```

具体字段可根据当前模型调整，但禁止只有：

```python
success: bool
message: str
```

增加：

```python
@property
def succeeded(self) -> bool:
    ...
```

成功状态应只有：

```text
NO_WORK
RECOVERED
```

## 3. Recovery 固定规则

Recovery 必须：

1. 只读取 Store 中 committed transaction；
2. 只处理 `projection_ready=False`；
3. 按 `execution_sequence` 升序；
4. 从最早未完成事务开始；
5. 调用 Coordinator 的正式恢复能力；
6. 前一事务失败时立即停止；
7. 不跳过 sequence；
8. 不重新运行 Planner；
9. 不重新调用 Broker；
10. 不重新调用 Market Rule；
11. 不重新计算 Fee；
12. 不重新生成 Event；
13. 不覆盖冲突 Manager Authority；
14. 不自动标记 Ready；
15. 不删除失败事务；
16. 不回滚已完成 Projection；
17. 不启动并发线程。

## 4. Recovery 结果分类

### 无事务

```text
NO_WORK
```

### 全部恢复成功

```text
RECOVERED
```

### Coordinator 返回 PROJECTION_FAILED

```text
FAILED
```

### Coordinator 返回 SEQUENCE_BLOCKED

```text
SEQUENCE_BLOCKED
```

### Coordinator 返回 STORE_FAILURE

```text
STORE_FAILURE
```

### ALREADY_READY

如果 unprojected 查询和实际状态之间存在竞态，允许记录为幂等完成，但不能将其当作错误。

---

# 七、接入 Runtime 生命周期

## 1. RuntimeServices 增加正式依赖

增加：

```python
execution_commit_coordinator: OnlyExecutionCommitCoordinator
execution_recovery_service: OnlyExecutionRecoveryService
execution_transaction_query: OnlyExecutionTransactionQueryPort
ready_execution_query: OnlyProjectionReadyExecutionQueryPort
execution_projection_state: OnlyExecutionProjectionStatePort
execution_transaction_outbox: OnlyExecutionTransactionOutboxPort
```

根据当前结构可适当合并字段，但必须保证：

* Runtime 可以调用 Recovery；
* Collector 只能看到 Ready Query；
* Coordinator 不被隐藏在 Processor 内；
* Store 管理接口不会被业务层滥用。

## 2. Backtest Composition Root

Backtest Runtime 当前已经构造：

* Store；
* Applied Ledger；
* Real Targets；
* Projection Applier；
* Coordinator；
* Outbox Publisher。

需要继续构造：

```python
execution_recovery_service = OnlyExecutionRecoveryService(...)
```

然后将：

* Coordinator；
* Recovery Service；
* Transaction Query；
* Ready Query；
* Projection State；
* Outbox Port；

正式保存到 RuntimeServices。

不要创建第二个 Coordinator 或第二个 Store。

## 3. Runtime initialize() 修改

当前 initialize 过程必须变为：

```text
检查 CREATED
→ initialize/connect Plugin Resource
→ initialize Cluster
→ 执行 Execution Recovery
→ 验证 Recovery 成功
→ 设置 READY
```

伪代码：

```python
def initialize(self) -> None:
    if self._state is not OnlyRuntimeState.CREATED:
        raise OnlyLifecycleError(...)

    try:
        initialize_resources()
        cluster_manager.initialize_all()

        recovery = self._services.execution_recovery_service.recover(
            self.config.runtime_id
        )
        self._execution_recovery_diagnostics.append(recovery)

        if not recovery.succeeded:
            raise OnlyRuntimeRecoveryError.from_result(recovery)

        self._state = OnlyRuntimeState.READY
    except Exception:
        rollback_resources()
        self._state = OnlyRuntimeState.FAILED
        raise
```

不要在 Recovery 前进入 READY。

## 4. Runtime start() 修改

目标顺序：

```text
READY
→ start Plugin Resource
→ drain recovered durable Outbox
→ 检查 Delivery 结果
→ start Cluster
→ RUNNING
→ publish RUNTIME_STARTED
```

当前若是：

```text
start cluster
→ drain outbox
```

必须调整。

旧事务事件必须在新策略开始产生订单前进入 EventBus。

## 5. Recovery Failure

恢复失败时必须：

* Runtime 进入 FAILED；
* Cluster 不启动；
* 不进入 RUNNING；
* 不发布 `RUNTIME_STARTED`；
* 不允许 `receive_market_data_update()`；
* 不允许 `receive_broker_update()`；
* 不执行历史 Replay；
* 不继续处理 Outbox；
* 保存 Recovery Diagnostic。

新增：

```python
class OnlyRuntimeRecoveryError(OnlyRuntimeError):
    ...
```

错误至少包含：

* Runtime ID；
* execution sequence；
* transaction ID，如可获得；
* failed component；
* Coordinator status；
* error；
* projection state。

## 6. Outbox Failure 与 Recovery Failure 分离

Projection Recovery 失败：

```text
业务 Authority 不完整
→ 必须阻止启动
```

Outbox 发布失败：

```text
业务 Authority 已完整
→ Transaction 已 Ready
→ Delivery 尚未完成
```

Backtest 第一版采用严格启动语义：

```text
Recovered Outbox 未成功处理
→ Runtime 启动失败
```

或者保持现有 Delivery Diagnostic 语义，但必须保证：

* 结果状态明确；
* 不把 Delivery Failure 当成 Projection Failure；
* Transaction 不回滚；
* Manager 不重放；
* Event ID 稳定。

不要在本任务中设计复杂可配置策略，除非当前配置模型已经存在合适的错误策略。

优先采用简单、确定、可验证的 Backtest 严格行为。

## 7. Runtime 诊断

新增 Runtime-owned：

```python
execution_recovery_diagnostics
```

可以是：

```python
tuple[OnlyExecutionRecoveryResult, ...]
```

必须可被：

* Runtime Status；
* Backtest Result Diagnostics；
* Artifact；
* Report；

读取。

不要把完整内部 Store 对象暴露给 Cluster。

---

# 八、Ready Query 与 Result 收口

## 1. Collector

`OnlyBacktestResultCollector` 只能依赖 Ready Query。

不得再调用：

```python
runtime.execution_transaction_query.records()
```

## 2. RunPlan

以下全部使用 Ready Query：

* `trades`；
* `trade_count`；
* fee attribution；
* final reconciliation；
* execution fingerprint；
* result execution records。

## 3. Failed Runtime Result

增加测试：

```text
Transaction committed
Projection failed
Backtest 最终 FAILED
```

即使产生 Result，也必须满足：

```text
trade_count = 0
execution facts = ()
committed fee attribution = ()
artifact 不包含该 transaction 的正式成交
```

Admin Diagnostic 可以记录该未完成事务，但不能混入业务成交事实。

---

# 九、构建真实 Manager 故障测试 Harness

## 1. 目标

建立可复用测试基础设施，使用：

* 真实 OrderManager；
* 真实 PositionManager；
* 真实 AllocationManager；
* 真实 SettlementManager；
* 真实 FeeManager；
* 真实 AccountManager；
* 真实 StrategyLedgerManager；
* 真实 RiskService；
* 真实 Valuation Authority；
* 真实 Applied Projection Ledger；
* 真实 Projection Target；
* 真实 Projection Applier；
* In-memory / SQLite Store；
* 正式 Coordinator；
* 正式 Recovery Service。

禁止在主要故障矩阵中使用：

```text
OnlyReferenceExecutionProjectionTarget
Fake Manager
字典模拟账户
手工修改 Result Snapshot
```

Reference Target 测试可以保留作为 Coordinator 快速单测，但不能作为真实故障验收。

## 2. Harness 建议结构

新增测试支持模块，例如：

```text
tests/execution/support/real_execution_recovery_harness.py
```

实现：

```python
class OnlyRealExecutionRecoveryHarness:
    def prepare_transaction(self) -> OnlyPreparedExecutionTransaction:
        ...

    def commit(self) -> OnlyExecutionCommitCoordinationResult:
        ...

    def recover(self) -> OnlyExecutionRecoveryResult:
        ...

    def authority_digest(self) -> OnlyExecutionAuthorityDigest:
        ...

    def applied_ledger_digest(self) -> tuple[...]:
        ...

    def store_digest(self) -> tuple[...]:
        ...

    def outbox_digest(self) -> tuple[...]:
        ...
```

## 3. Authority Digest

实现不可变 Digest，至少包含：

```text
Order Snapshot / Version
Position Snapshot / Version
Allocation Snapshot / Version
Settlement Authority / Records / Sequence
Fee Authority / Records
Account Snapshot / Version
Strategy Ledger Snapshot / Version
Account Cash Reservation
Strategy Cash Reservation
Risk Reservation
Risk Snapshot / Version
Valuation State / Version
Account Equity Timeline
Strategy Equity Timeline
Manager Event Sequence
Applied Ledger Records
Transaction projection state
Outbox Records
```

比较恢复前后时不能只比较对象身份。

必须验证经济数据：

* Cash；
* Frozen Cash；
* Quantity；
* Available Quantity；
* Cost；
* Fee；
* PnL；
* Equity；
* Reservation consumed/remaining；
* Timeline count；
* Event sequence。

---

# 十、故障注入设计

## 1. 不污染生产代码

禁止在生产代码中增加：

```python
if fail_after_position:
    raise ...
```

禁止增加测试环境变量或 Runtime Config 故障开关。

使用测试装饰器、Wrapper 或 Faulting Port。

## 2. Target Wrapper

实现测试专用包装器：

```python
class OnlyFailOnceExecutionProjectionTarget:
    def __init__(
        self,
        delegate: OnlyExecutionProjectionTarget,
        *,
        fail_before: bool = False,
        fail_after: bool = False,
    ) -> None:
        ...
```

用于：

```text
BEFORE_TARGET
AFTER_TARGET_RETURN
```

## 3. Manager Install 后故障

为了测试：

```text
Manager Authority 已安装
Applied Ledger 尚未记录
```

不要修改生产 Target。

可使用以下方式之一：

### 方式 A：Failing Applied Ledger

```python
class OnlyFailOnceAppliedProjectionLedger:
    def record(self, record):
        raise ...
```

由于 Target 在 Manager 安装后调用 `record()`，可以真实触发该窗口。

### 方式 B：Manager restore wrapper

对于需要更细粒度的场景，可包装 Manager Repository 或 restore port，但不要复制整个 Manager 实现。

优先使用 Failing Applied Ledger。

## 4. Store 故障包装

实现测试专用 Store Decorator：

```python
class OnlyFailOnceExecutionTransactionStore:
    ...
```

支持：

```text
COMMIT
MARK_READY
MARK_FAILED
OUTBOX_BEGIN_ATTEMPT
OUTBOX_MARK_PUBLISHED
OUTBOX_MARK_FAILED
QUERY
```

SQLite 原子故障应尽可能使用真实数据库异常或事务中断验证，而不是只 Mock 返回值。

---

# 十一、真实故障矩阵

对以下 12 个组件执行：

```text
1. ORDER
2. POSITION
3. ALLOCATION
4. SETTLEMENT
5. FEE
6. ACCOUNT
7. STRATEGY_LEDGER
8. ACCOUNT_CASH_RESERVATION
9. STRATEGY_CASH_RESERVATION
10. RISK_RESERVATION
11. RISK
12. VALUATION
```

每个组件至少覆盖以下场景。

## 1. Target 前失败

状态：

```text
前缀组件已完成
当前组件未执行
后续组件未执行
```

验证：

* transaction committed；
* projection_ready=False；
* outbox hidden；
* 前缀 Authority 已安装；
* 当前和后续 Authority 未改变；
* recovery 时前缀为 IDEMPOTENT；
* 当前和后续为 APPLIED；
* 最终 Ready；
* 最终 Authority 等于一次正常执行结果。

## 2. Manager 安装后、Applied Ledger 前失败

通过 Applied Ledger `record()` 注入失败。

验证：

* Manager 已是 Result Authority；
* Applied Ledger 当前组件无记录；
* Transaction not ready；
* Outbox hidden；
* Recovery 当前组件返回 RECOVERED；
* 不重复经济变化；
* Applied Ledger 被补齐；
* Timeline 不重复；
* Manager version 不重复推进；
* Event sequence 不重复推进。

## 3. Applied Ledger 已记录、Coordinator 未完成

通过 Target return 后或 Applier 后注入。

验证：

* Recovery 返回 IDEMPOTENT；
* 不调用业务 mutation API；
* 不追加重复 Fee；
* 不追加重复 Settlement；
* 不追加重复 Valuation Timeline。

## 4. Result State + Ledger 缺失

手工只清空 Applied Ledger，不改变 Manager。

恢复全部 Transaction：

```text
所有已安装组件应返回 RECOVERED
```

经济 Authority Digest 必须完全不变。

## 5. Ledger 已有不同 Payload

注入同 sequence/component、不同 payload hash 的 Applied Record。

预期：

```text
PAYLOAD_CONFLICT
Transaction not ready
Runtime Recovery FAILED
Manager 不被覆盖
```

## 6. Version Conflict

将某 Manager Authority 推进到非 expected/non-result version。

预期：

```text
VERSION_CONFLICT
```

## 7. State Conflict

保持 version 相同但修改 authority state，使 hash 不匹配。

预期：

```text
STATE_CONFLICT
```

---

# 十二、Store 故障矩阵

对 In-memory 和 SQLite 执行相同 Contract。

## 1. Commit 失败

验证：

```text
Store 无 Transaction
Store 无 Outbox
Manager 完全不变
Applied Ledger 无记录
```

## 2. Commit 成功后、Projection 前中断

验证：

```text
Transaction 存在
projection_ready=False
Manager Before Authority 不变
Outbox hidden
Recovery 可完成
```

## 3. mark_projection_ready 失败

使用真实 12 Target：

```text
所有 Manager 已安装
Applied Ledger 已完整
Transaction 仍 not ready
Outbox hidden
```

重试：

```text
12 个组件全部 IDEMPOTENT
mark ready 成功
Outbox 可见
Manager Digest 不变
```

## 4. mark_projection_failed 失败

验证：

* 原始 Projection Failure 不丢失；
* 返回明确 Store Failure；
* Transaction 仍可查询；
* Outbox hidden；
* 后续 Recovery 不会跳过该事务。

## 5. Query 失败

Runtime Recovery 必须失败，不能假设没有未完成事务。

## 6. SQLite 重启

流程：

```text
打开 Store A
→ commit transaction
→ 部分 Projection
→ 关闭 Store A
→ 打开 Store B
→ 重建 Runtime Bootstrap Authority
→ initialize()
→ 自动恢复
```

验证 Transaction、Outbox、Hash、Event ID 无损。

---

# 十三、Outbox 故障矩阵

## 1. Projection Ready 前

```text
pending() == ()
begin_attempt() 拒绝
```

## 2. EventBus 发布失败

验证：

* Transaction 保持 Ready；
* Manager 不回滚；
* attempt_count 增加；
* last_error 记录；
* Event 仍 Pending；
* 重试 Event ID 不变。

## 3. EventBus 成功、mark_published 失败

验证：

* 下一次重试会重复投递；
* Event ID 稳定；
* 不重新 Projection；
* 不重复经济状态；
* 最终 Outbox published。

明确文档：

```text
At-Least-Once
不是 Exactly-Once
```

---

# 十四、Runtime 生命周期测试

## 1. 无恢复工作

```text
initialize()
→ NO_WORK
→ READY
```

## 2. 存在未完成事务，恢复成功

```text
initialize()
→ RECOVERED
→ READY

start()
→ drain outbox
→ cluster start
→ RUNNING
```

## 3. Recovery 失败

验证：

```text
Runtime FAILED
Cluster 未 STARTED
RUNTIME_STARTED 未发布
MarketData 不可接收
Broker Update 不可接收
```

## 4. 前序失败、后序存在

Store：

```text
sequence N     not ready
sequence N + 1 not ready
```

N 恢复失败：

```text
N + 1 不执行
Runtime FAILED
```

## 5. Outbox 顺序

恢复 Event 必须先于 Cluster 新产生的 Event。

验证 EventBus dispatch order。

## 6. Runtime Restart 产品测试

使用 SQLite：

```text
Runtime A
→ 正常 Bootstrap
→ Commit
→ 中间故障
→ close

Runtime B
→ 同一配置
→ 同一 SQLite Store
→ 重建正确 Bootstrap Authority
→ initialize 自动 recovery
→ start 发布 outbox
→ 运行后续 Bar
```

验证：

* 最终 Authority 与无故障基准一致；
* Transaction sequence 不重复；
* Trade Fact 只出现一次；
* Event ID 稳定；
* Cash、Position、Fee、Ledger 不重复；
* Result fingerprint 在等价恢复场景下稳定。

---

# 十五、架构测试

新增或更新架构测试，证明：

1. Collector 不导入或调用 Admin Transaction Query；
2. RunPlan 不调用全部 `records()`；
3. Result / Analytics / Artifact / Report 只依赖 Ready Query；
4. Runtime Services 持有 Recovery Service；
5. Runtime initialize 调用 Recovery；
6. Runtime start 在 Cluster start 前处理恢复 Outbox；
7. Coordinator 不导入 Runtime；
8. Recovery Service 不导入 Manager；
9. Recovery Service 不调用 Planner；
10. Projection Target 不调用 Transaction Store；
11. Applied Ledger 仍只有 In-memory rebuildable index；
12. 生产代码没有故障注入开关；
13. 没有 `ready_only=False` 模糊接口；
14. 没有兼容旧 `committed_execution_query` 的 Alias；
15. 不存在 Recovery 失败后继续 RUNNING 的分支；
16. 不存在未 Ready Transaction 进入正式 Collector 的路径。

架构测试应检查 AST、依赖或公开签名，不只检查字符串文档。

---

# 十六、文档更新

更新：

```text
README.md
docs/architecture.md
docs/backtest.md
docs/execution_processor.md
docs/execution_prepared_transaction.md
docs/execution_projection_contract.md
docs/execution_projection_targets.md
docs/execution_trade_planning.md
docs/roadmap.md
```

新增 ADR，建议：

```text
docs/adr/0042-projection-ready-query-and-runtime-recovery.md
```

ADR 必须说明：

1. Committed 与 Projection Ready 的区别；
2. Admin Query 和 Business Query 的区别；
3. Result 只读取 Ready Transaction；
4. Runtime Recovery Hook 的生命周期位置；
5. Recovery 失败阻止 Runtime 启动；
6. Recovery 与 Outbox Delivery Failure 的区别；
7. Applied Ledger 仍是可重建索引；
8. Forward Recovery；
9. At-least-once Outbox；
10. 当前仍不是 Full Runtime Recovery；
11. 当前仍依赖正确 Bootstrap Authority；
12. PR4.1 不扩展成交场景。

新增文档：

```text
docs/execution_runtime_recovery.md
```

内容包括：

* 生命周期；
* 恢复顺序；
* 状态机；
* 故障分类；
* 运维诊断；
* 当前限制。

---

# 十七、测试文件建议

建议新增：

```text
tests/execution/test_projection_ready_query.py
tests/execution/test_execution_recovery_service.py
tests/execution/test_real_projection_failure_matrix.py
tests/execution/test_real_projection_applied_ledger_recovery.py
tests/execution/test_execution_store_recovery_contract.py
tests/execution/test_execution_outbox_recovery.py
tests/runtime/test_execution_runtime_recovery_hook.py
tests/runtime/test_execution_runtime_recovery_sqlite_restart.py
tests/architecture/test_projection_ready_query_boundaries.py
tests/architecture/test_execution_runtime_recovery_boundaries.py
```

测试支持：

```text
tests/execution/support/real_execution_recovery_harness.py
tests/execution/support/execution_fault_injection.py
tests/execution/support/execution_authority_digest.py
```

避免把一个文件写成数千行。

---

# 十八、验收命令

执行：

```bash
uv lock --check
uv sync --frozen --all-packages --all-groups

uv run ruff check src tests examples packages
uv run ruff format --check src tests examples packages

uv run mypy src/onlyalpha
uv run mypy packages/fake/onlyalpha-plugin-broker-virtual/src
uv run mypy packages/provider/onlyalpha-plugin-tushare/src/onlyalpha_plugin_tushare
uv run mypy packages/provider/onlyalpha-plugin-miniqmt/src/onlyalpha_plugin_miniqmt

uv run pytest tests/execution/test_projection_ready_query.py -q
uv run pytest tests/execution/test_execution_recovery_service.py -q
uv run pytest tests/execution/test_real_projection_failure_matrix.py -q
uv run pytest tests/execution/test_real_projection_applied_ledger_recovery.py -q
uv run pytest tests/execution/test_execution_store_recovery_contract.py -q
uv run pytest tests/execution/test_execution_outbox_recovery.py -q
uv run pytest tests/runtime/test_execution_runtime_recovery_hook.py -q
uv run pytest tests/runtime/test_execution_runtime_recovery_sqlite_restart.py -q

uv run pytest tests -q \
  -m "not external and not requires_network and not requires_tushare and not requires_local_qmt"

uv run pytest packages/fake/onlyalpha-plugin-broker-virtual/tests -q

uv run pytest packages/provider/onlyalpha-plugin-tushare/tests -q \
  -m "not external and not requires_network and not requires_tushare"

uv run pytest packages/provider/onlyalpha-plugin-miniqmt/tests -q \
  -m "not external and not requires_network and not requires_local_qmt"

git diff --check
```

如无法执行 Windows、MiniQMT、网络或外部服务测试，必须明确列出：

* 未执行命令；
* 真实原因；
* 已执行的替代验证；
* 不能宣称通过的门禁。

不得伪造结果。

---

# 十九、完成标准

只有同时满足以下条件，才可声明 PR4.1 完成：

1. 存在正式 Projection Ready Business Query；
2. Admin Query 和 Business Query 完全分离；
3. Collector 只读取 Ready Transaction；
4. RunPlan 只读取 Ready Transaction；
5. Analytics、Artifact、Report、Scenario 只读取 Ready Transaction；
6. 未 Ready Transaction 不进入 trade count；
7. 未 Ready Transaction 不进入 fee attribution；
8. Runtime Services 正式持有 Coordinator；
9. Runtime Services 正式持有 Recovery Service；
10. Runtime initialize 自动执行 Recovery；
11. Recovery 完成前 Runtime 不进入 READY；
12. Recovery 失败时 Runtime 进入 FAILED；
13. Recovery 失败时 Cluster 不启动；
14. Recovery 失败时不发布 RUNTIME_STARTED；
15. Recovery 后才处理 Durable Outbox；
16. 恢复 Outbox 先于 Cluster 新业务 Event；
17. 12 个真实 Projection Target 全部经过故障矩阵；
18. Manager 已安装、Ledger 缺失时返回 RECOVERED；
19. Ledger 已存在时返回 IDEMPOTENT；
20. Version Conflict 和 State Conflict 不覆盖 Manager；
21. mark Ready 失败后可以幂等恢复；
22. In-memory 与 SQLite Ready Query 语义一致；
23. In-memory 与 SQLite Recovery Contract 一致；
24. SQLite 关闭重开后可恢复未完成事务；
25. EventBus 成功但 mark published 失败时 Event ID 稳定；
26. 经济状态不重复；
27. Timeline 不重复；
28. Manager version 不重复推进；
29. 没有生产故障开关；
30. 没有兼容旧 Query 的 Alias；
31. 没有 `ready_only` 模糊默认参数；
32. 没有把 Applied Ledger 提升为第二持久权威；
33. 没有声称实现 Full Runtime Recovery；
34. Ruff、Mypy、Pytest 和架构门禁通过。

---

# 二十、禁止的实现形态

以下任何一种情况都视为任务失败：

```text
只在 Collector 中手工过滤 projection_ready
只增加 ready_only 参数
仍让 Result 调用 records()
Recovery Service 只存在但 Runtime 不调用
Runtime 在 Cluster 启动后才 Recovery
Recovery 失败后继续 RUNNING
Recovery 重新运行 Planner
Recovery 重新查询 Broker
Recovery 重新计算 Fee
Recovery 跳过失败 sequence
Recovery 删除失败 Transaction
Recovery 自动覆盖冲突 Manager
通过 Fake Manager 代替真实故障矩阵
只使用 Reference Projection Target
在生产代码中增加 fail_* 配置
为旧测试保留 committed_execution_query Alias
Outbox 失败导致事务回滚
未 Ready Transaction 进入 Artifact
Applied Ledger 被实现成第二业务账本
只修改文档和测试，没有迁移生产调用方
```

---

# 二十一、最终交付报告

完成后输出以下内容。

## 1. 修改前审计

列出：

* 所有原 `records()` 调用方；
* 读取权限分类；
* Runtime 生命周期原有缺口；
* 当前 Reference Test 覆盖不足。

## 2. Ready Query 实现

说明：

* 新 Port；
* In-memory 实现；
* SQLite 实现；
* 迁移调用方；
* 删除的模糊接口和字段。

## 3. Runtime Recovery

说明：

* Recovery Service；
* RuntimeServices 装配；
* initialize/start 顺序；
* 失败状态；
* Outbox 顺序。

## 4. 真实故障矩阵

按 12 个 Component 列出：

```text
Before Target
After Manager Install / Before Ledger
After Ledger / Before Coordinator Completion
Version Conflict
State Conflict
Payload Conflict
```

说明真实测试结果。

## 5. Store 和 Outbox

分别说明：

* In-memory；
* SQLite；
* Restart；
* mark Ready Failure；
* EventBus Failure；
* mark Published Failure。

## 6. 删除内容

明确列出：

* 旧 Query 字段；
* Alias；
* 手工过滤；
* 旧 Fixture；
* 无效测试；
* 错误文档。

## 7. 测试结果

给出实际命令和真实输出摘要。

## 8. 当前剩余边界

明确声明尚未实现：

* Full Bootstrap Snapshot；
* Empty Runtime Recovery；
* Partial/Multi Fill；
* SELL/CLOSE；
* Futures/Margin；
* Non-Trade Transaction；
* Paper/Live Recovery。

不得将这些能力包装成已经完成。

---

# 二十二、核心验收结论

PR4.1 完成后，系统必须真正满足：

```text
PR4：
一笔成交如何先持久提交，再安全安装 Manager Authority。

PR4.1：
哪些成交允许被业务读取，以及 Runtime 崩溃后如何自动继续完成已提交但未完成的成交。
```

最终系统应具备唯一、清晰的语义：

```text
Committed
    表示不可丢失、必须恢复

Projection Ready
    表示可以成为正式业务成交

Runtime Recovery
    表示启动前完成所有 committed transaction tail

Outbox
    表示 Projection Ready 后的 at-least-once 事件交付
```
