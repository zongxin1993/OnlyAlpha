# OnlyAlpha：收敛 Event Buffer、Direct Publisher 与 Outbox Publisher 边界

## 任务目标

以当前 OnlyAlpha `master` 为唯一事实源，重新审计 Execution Event 的产生、暂存、持久化和交付链，完成以下边界收敛：

```text
EventBuffer 只负责收集事件
ExecutionProcessor 只负责业务处理与生成交付意图
Commit Store 只负责持久化 Fact 与 Outbox
Direct Publisher 只负责非持久事件投递
Outbox Publisher 只负责持久事件重试投递
Runtime Delivery Coordinator 负责调度交付
EventBus 只负责事件分发
```

当前代码虽然已消除 Trade Event 的确定性双发布，但仍存在：

* `OnlyExecutionEventBuffer` 持有 `OnlyEventBus`；
* Buffer 非 Active 时会隐式直接发布；
* Processor 同时依赖 Buffer、Direct Publisher、Outbox Publisher 和 Journal；
* Processor 自己决定并执行事件交付；
* Outbox 失败未完整记录尝试次数、错误和发布时间；
* Memory 与 SQLite Outbox 行为不完全一致；
* Runtime 启动和停止阶段没有正式的 Pending Outbox Drain；
* Direct Delivery 失败与 Execution Business Status 混合；
* Event 产生、提交与交付的所有权仍不清晰。

本任务必须切实解决这些问题。

不考虑旧接口兼容。

不得为了旧测试、旧示例、旧构造函数或旧导出保留错误设计。

必须直接修改所有生产调用方、测试、示例和文档。

---

# 一、第一性原则

## 1. Event 产生与 Event 交付是两个阶段

Manager 和 ExecutionProcessor 只产生 Event。

它们不能决定 Event 最终通过：

* Direct Delivery；
* Durable Outbox；
* EventBus；
* 重试机制；

中的哪一条路径交付。

正确模型：

```text
Business Processing
→ Event Production
→ Event Batch
→ Delivery Intent
→ Runtime Delivery
```

## 2. EventBuffer 不是 Publisher

EventBuffer 只保存本次 Execution Processing 产生的事件。

它不得：

* 持有 EventBus；
* 持有 Journal；
* 持有 Runtime；
* 直接发布事件；
* 在未激活时静默绕过 Buffer；
* 判断事件是否需要持久化。

## 3. Processor 不负责交付

ExecutionProcessor 负责：

* 验证 Broker Update；
* 编排业务 Mutation；
* 检查 Invariant；
* 构建 Committed Execution Fact；
* 提交 Trade Fact 与 Outbox；
* 返回业务处理结果和交付意图。

ExecutionProcessor 不得：

* 调用 EventBus；
* 调用 Direct Publisher；
* 调用 Outbox Publisher；
* 执行 Pending Outbox 重试；
* 将事件发布失败解释为 Broker Reconciliation。

## 4. Trade 和 Non-Trade 使用不同交付权威

当前阶段保持：

```text
Committed Trade Event
→ Durable Outbox
→ EventBus

Non-Trade Execution Event
→ Direct Publisher
→ EventBus
```

原因：

* Trade 已有正式 Committed Execution Fact 和 Durable Commit Authority；
* Accepted、Rejected、Cancelled、Account、Position、Connection 尚无统一持久业务事实；
* 不得只持久化 Event，却无法恢复产生该 Event 的业务状态。

## 5. Outbox 只能保证 At-Least-Once

存在无法完全消除的窗口：

```text
EventBus 已接收 Event
→ 进程崩溃
→ Outbox 尚未标记 Published
→ 重启后再次发布
```

因此必须采用：

```text
Durable Outbox
+ Stable Event ID
+ Consumer Idempotency
= At-Least-Once Delivery
```

不得声称实现 Exactly-Once。

---

# 二、修改前审计

修改前必须执行：

```bash
git status
git log -n 10 --oneline

rg "OnlyExecutionEventBuffer"
rg "OnlyDirectExecutionEventPublisher"
rg "OnlyExecutionOutboxPublisher"
rg "OnlyCommittedExecutionJournalPort"
rg "pending_outbox"
rg "mark_outbox_published"
rg "event_bus"
rg "publish_many"
rg "publish_pending"
rg "OnlyExecutionProcessor"
rg "OnlyExecutionProcessingResult"
rg "OnlyRuntimeServices"
```

形成简短审计结论：

1. EventBuffer 当前所有调用点；
2. 哪些调用依赖 Buffer 非 Active 时直接发布；
3. Processor 当前如何区分 Trade 与 Non-Trade；
4. Processor 当前何时调用 Direct Publisher；
5. Processor 当前何时调用 Outbox Publisher；
6. Runtime 当前如何保存 Processor Result；
7. Outbox 成功、失败和 Pending 状态当前如何记录；
8. Memory 与 SQLite Outbox 语义差异；
9. Runtime 启动、Update 后和停止前是否 Drain Outbox；
10. 哪些测试直接依赖旧 Publisher 接口。

以当前源码为事实，不机械套用旧路径。

---

# 三、目标架构

实现以下结构：

```text
Broker Update
    │
    ▼
OnlyExecutionProcessor
    │
    ├── EventBuffer.begin()
    ├── Business Processing
    ├── EventBuffer.seal()
    ├── Trade：Durable Commit(Fact + Event Batch)
    └── Non-Trade：返回 Direct Delivery Intent
    │
    ▼
OnlyExecutionProcessingResult
    │
    └── delivery_intent
            │
            ▼
OnlyExecutionEventDeliveryCoordinator
    │
    ├── DIRECT          → Direct Publisher
    ├── DURABLE_OUTBOX  → Outbox Publisher
    └── NONE            → No-op
            │
            ▼
         EventBus
```

---

# 四、EventBuffer 重构

## 4.1 新增不可变 Event Batch

实现：

```python
@dataclass(frozen=True, slots=True)
class OnlyExecutionEventBatch:
    events: tuple[OnlyEvent, ...]

    @property
    def empty(self) -> bool:
        return not self.events
```

具体命名可调整，但必须是：

* immutable；
* 不持有 EventBus；
* 不持有 Journal；
* 不包含 Callable；
* 可安全传递给 Commit Store 或 Direct Publisher。

## 4.2 EventBuffer 只负责暂存

目标接口：

```python
class OnlyExecutionEventBuffer:
    def begin(self) -> None:
        ...

    def add(self, event: OnlyEvent) -> None:
        ...

    def extend(self, events: tuple[OnlyEvent, ...]) -> None:
        ...

    def seal(self) -> OnlyExecutionEventBatch:
        ...

    def abort(self) -> OnlyExecutionEventBatch:
        ...
```

语义：

### `begin()`

* 开启一次新的 Processing Buffer；
* 已激活时再次调用必须报错；
* 清空旧状态。

### `add()` / `extend()`

* 仅在 Active 状态允许调用；
* 未 Active 时必须报错；
* 不允许隐式直接发布。

### `seal()`

* 返回不可变 Event Batch；
* 清空 Buffer；
* 结束 Active 状态；
* 不发布事件。

### `abort()`

* 返回已丢弃 Event Batch，用于 Audit；
* 清空 Buffer；
* 结束 Active 状态；
* 不发布事件。

删除旧接口：

```text
publish
publish_many
snapshot
drain
discard
commit
rollback
```

不保留 Alias、Wrapper 或兼容分支。

EventBuffer 构造函数不得再接收 EventBus。

---

# 五、Delivery Intent

新增显式交付意图：

```python
class OnlyExecutionEventDeliveryMode(StrEnum):
    NONE = "NONE"
    DIRECT = "DIRECT"
    DURABLE_OUTBOX = "DURABLE_OUTBOX"
```

```python
@dataclass(frozen=True, slots=True)
class OnlyExecutionEventDeliveryIntent:
    mode: OnlyExecutionEventDeliveryMode
    direct_batch: OnlyExecutionEventBatch | None = None
    committed_execution_sequence: int | None = None
```

必须在 `__post_init__` 中验证：

```text
NONE
→ direct_batch 必须为空
→ committed_execution_sequence 必须为空

DIRECT
→ direct_batch 必须存在
→ committed_execution_sequence 必须为空

DURABLE_OUTBOX
→ direct_batch 必须为空
→ committed_execution_sequence 必须存在
```

禁止使用松散的：

```python
dict[str, object]
```

或多个可同时为空的无约束字段。

---

# 六、ExecutionProcessingResult 调整

在 `OnlyExecutionProcessingResult` 中增加：

```python
delivery_intent: OnlyExecutionEventDeliveryIntent
```

业务状态与交付状态必须分离。

例如：

```text
Execution Status = APPLIED
Delivery Intent  = DURABLE_OUTBOX
```

或：

```text
Execution Status = APPLIED
Delivery Intent  = DIRECT
```

Processor 返回结果时不执行实际 Delivery。

不要在 Processing Result 中提前填入 EventBus 发布成功与否，因为交付发生在 Processor 返回之后。

---

# 七、ExecutionProcessor 重构

## 7.1 Processor 依赖收敛

删除 Processor 对以下组件的依赖：

```text
OnlyDirectExecutionEventPublisher
OnlyExecutionOutboxPublisher
OnlyEventBus
```

Processor 只保留：

```text
OnlyExecutionEventBuffer
OnlyExecutionCommitPort
```

以及当前必要的业务 Manager 和领域服务。

## 7.2 Trade 成功路径

目标顺序：

```text
1. EventBuffer.begin()
2. 执行业务处理
3. 检查 Invariant
4. EventBuffer.seal()
5. 构建 Committed Execution Fact
6. Durable Append(Fact + Event Batch)
7. 返回 APPLIED + DURABLE_OUTBOX Intent
```

示意：

```python
batch = self._event_buffer.seal()

append_result = self._execution_commit_port.append_transaction(
    OnlyDurableExecutionCommit(
        transaction_id=fact.execution_id,
        fact=fact,
        outbox_events=batch.events,
    )
)

intent = OnlyExecutionEventDeliveryIntent(
    mode=OnlyExecutionEventDeliveryMode.DURABLE_OUTBOX,
    committed_execution_sequence=append_result.fact.execution_sequence,
)
```

要求：

* Journal Append 前 Event 不可见；
* Journal Append 后 Processor 不调用 Publisher；
* Journal Append 失败时返回现有业务失败/Reconciliation；
* Journal Append 成功后 EventBus 是否成功不影响 Trade Commit；
* 重试 Delivery 不重新执行 Trade。

## 7.3 Non-Trade 成功路径

目标顺序：

```text
1. EventBuffer.begin()
2. 执行业务处理
3. 检查 Invariant
4. EventBuffer.seal()
5. 返回业务结果 + DIRECT Intent
```

示意：

```python
batch = self._event_buffer.seal()

intent = (
    OnlyExecutionEventDeliveryIntent(
        mode=OnlyExecutionEventDeliveryMode.NONE,
    )
    if batch.empty
    else OnlyExecutionEventDeliveryIntent(
        mode=OnlyExecutionEventDeliveryMode.DIRECT,
        direct_batch=batch,
    )
)
```

Non-Trade 不创建 Trade Outbox Row。

## 7.4 失败路径

异常时：

```python
discarded = self._event_buffer.abort()
```

失败 Audit 可以记录 `discarded.events`，但不得通过 EventBuffer 发布失败事件。

需要发布：

```text
EXECUTION_PROCESSING_FAILED
EXECUTION_RECONCILIATION_REQUIRED
```

时，应构建单独的 Direct Delivery Batch，并通过 Delivery Intent 返回。

Processor 仍不得调用 EventBus。

---

# 八、Direct Publisher

定义窄接口：

```python
class OnlyDirectExecutionEventPublisher(Protocol):
    def publish(
        self,
        batch: OnlyExecutionEventBatch,
    ) -> OnlyDirectEventDeliveryResult:
        ...
```

EventBus 实现：

```python
class OnlyEventBusDirectExecutionPublisher:
    def __init__(self, event_bus: OnlyEventBus) -> None:
        self._event_bus = event_bus

    def publish(
        self,
        batch: OnlyExecutionEventBatch,
    ) -> OnlyDirectEventDeliveryResult:
        ...
```

Result 至少包含：

```python
@dataclass(frozen=True, slots=True)
class OnlyDirectEventDeliveryResult:
    attempted: int
    published: int
    failed: int
    error: str | None
```

Direct Publisher 不得：

* 访问 Journal；
* 判断 Update 类型；
* 修改业务 Manager；
* 触发 Reconciliation；
* 吞掉异常而不返回失败结果。

Direct Delivery 失败必须表达为交付失败，而不是把业务 Processing Status 改成 FAILED。

---

# 九、拆分 Journal Port

当前大型 Journal Port 应拆分为窄能力接口。

## 9.1 Commit Port

```python
class OnlyExecutionCommitPort(Protocol):
    def next_sequence(
        self,
        runtime_id: OnlyRuntimeId,
    ) -> int:
        ...

    def append_transaction(
        self,
        transaction: OnlyDurableExecutionCommit,
    ) -> OnlyJournalAppendResult:
        ...
```

## 9.2 Query Port

```python
class OnlyCommittedExecutionQueryPort(Protocol):
    def get_by_trade(...):
        ...

    def get_by_update(...):
        ...

    def records(...):
        ...
```

## 9.3 Outbox Port

```python
class OnlyExecutionOutboxPort(Protocol):
    def pending(
        self,
        runtime_id: OnlyRuntimeId,
        *,
        limit: int,
    ) -> tuple[OnlyExecutionOutboxRecord, ...]:
        ...

    def begin_attempt(
        self,
        key: OnlyExecutionOutboxKey,
        attempted_at: OnlyTimestamp,
    ) -> OnlyExecutionOutboxRecord:
        ...

    def mark_published(
        self,
        key: OnlyExecutionOutboxKey,
        published_at: OnlyTimestamp,
    ) -> None:
        ...

    def mark_failed(
        self,
        key: OnlyExecutionOutboxKey,
        failed_at: OnlyTimestamp,
        error: str,
    ) -> None:
        ...

    def pending_count(
        self,
        runtime_id: OnlyRuntimeId,
    ) -> int:
        ...
```

同一个 Memory/SQLite Store 可以同时实现三个 Port。

调用方只注入所需能力：

```text
ExecutionProcessor → Commit Port
Result Collector   → Query Port
Outbox Publisher   → Outbox Port
```

删除旧大型 Port，不保留兼容继承层。

---

# 十、Outbox Record

扩充 `OnlyExecutionOutboxRecord`：

```python
@dataclass(frozen=True, slots=True)
class OnlyExecutionOutboxRecord:
    key: OnlyExecutionOutboxKey
    event: OnlyEvent
    published: bool
    attempt_count: int
    last_attempted_at: OnlyTimestamp | None
    published_at: OnlyTimestamp | None
    last_error: str | None
```

Key：

```python
@dataclass(frozen=True, slots=True)
class OnlyExecutionOutboxKey:
    runtime_id: OnlyRuntimeId
    execution_sequence: int
    event_sequence: int
```

要求：

* Memory 和 SQLite 使用相同模型；
* Published Record 不从 Memory Store 直接删除；
* Pending 查询只返回 `published=False`；
* Outbox 历史可审计；
* 事件重试使用原始持久 Event，不重新构建；
* Event ID 在重试过程中保持不变。

---

# 十一、Outbox Publisher

目标接口：

```python
class OnlyExecutionOutboxPublisher:
    def publish_pending(
        self,
        runtime_id: OnlyRuntimeId,
        *,
        limit: int = 100,
    ) -> OnlyOutboxPublishResult:
        ...
```

Result：

```python
@dataclass(frozen=True, slots=True)
class OnlyOutboxPublishResult:
    attempted: int
    published: int
    failed: int
    remaining: int
    stopped_on_error: bool
    last_error: str | None
```

发布算法：

```text
读取 Pending
→ begin_attempt
→ EventBus.publish
→ 成功：mark_published
→ 失败：mark_failed
→ 停止后续交付，保持顺序
```

要求：

* `attempt_count` 每次真实尝试前增加；
* 成功记录 `published_at`；
* 失败记录标准化 `last_error`；
* 使用 Runtime Clock；
* 严格按 `execution_sequence,event_sequence` 排序；
* 一个失败后默认停止，防止后续 Event 越序；
* 不修改任何业务 Manager；
* 不触发 Execution Reconciliation；
* 不删除已提交 Fact。

---

# 十二、Delivery Coordinator

新增 Runtime-owned：

```python
class OnlyExecutionEventDeliveryCoordinator:
    def __init__(
        self,
        direct_publisher: OnlyDirectExecutionEventPublisher,
        outbox_publisher: OnlyExecutionOutboxPublisher,
    ) -> None:
        ...

    def deliver(
        self,
        runtime_id: OnlyRuntimeId,
        intent: OnlyExecutionEventDeliveryIntent,
    ) -> OnlyExecutionEventDeliveryResult:
        ...
```

行为：

```text
NONE
→ 返回空结果

DIRECT
→ 调用 Direct Publisher

DURABLE_OUTBOX
→ 调用 Outbox Publisher
```

Coordinator 不得：

* 修改 Manager；
* 构建 Fact；
* 写 Journal Commit；
* 判断 Broker Update 类型；
* 修改 Execution Processing Status。

---

# 十三、Runtime 接入

Runtime 处理 Broker Update 的顺序调整为：

```python
processing_result = execution_processor.process(update)

delivery_result = delivery_coordinator.deliver(
    runtime_id,
    processing_result.delivery_intent,
)

runtime.record_execution_result(processing_result)
runtime.record_delivery_result(delivery_result)
```

Runtime 应在以下时点调用 Outbox Drain。

## 13.1 启动时

```text
STARTING
→ publish_pending()
→ 再接受新的 Broker Update
```

## 13.2 每次 Broker Update 后

根据 Delivery Intent 交付。

## 13.3 停止前

```text
STOPPING
→ best-effort publish_pending()
→ close resources
```

Backtest 不增加线程。

未来 Paper/Live 可增加 Timer 驱动重试，但不在本任务中实现后台线程。

---

# 十四、Delivery Diagnostic

新增独立交付诊断记录，不混入 Broker Reconciliation。

至少记录：

```text
runtime_id
processing_sequence
delivery_mode
attempted
published
failed
remaining
last_error
timestamp
```

必须区分：

```text
Business Processing Status
Event Delivery Status
```

例如：

```text
Business = APPLIED
Delivery = FAILED_PENDING_RETRY
```

不能将 EventBus 暂时失败解释为：

```text
Broker State Mismatch
Execution Reconciliation Required
```

---

# 十五、Event Identity

检查 `OnlyEvent` 当前序列化是否完整保留 `event_id`。

必须保证：

* Outbox 写入原始 Event；
* 重试读取原始 Event；
* 重试不重新生成 Event ID；
* Event ID 可由 Consumer 用于幂等；
* Result Fingerprint 不依赖随机 Event ID，除非当前产品明确要求。

本任务不强制将所有 Event ID 改为确定性 UUID5。

若发现当前 Codec 在反序列化时重新生成 Event ID，必须修复。

---

# 十六、模块组织

建议整理为：

```text
src/onlyalpha/execution/
├── event_buffer.py
│   ├── OnlyExecutionEventBatch
│   └── OnlyExecutionEventBuffer
│
├── delivery.py
│   ├── Delivery Mode
│   ├── Delivery Intent
│   ├── Delivery Results
│   ├── Direct Publisher
│   ├── Outbox Publisher
│   └── Delivery Coordinator
│
├── journal.py
│   ├── Commit Port
│   ├── Query Port
│   ├── Outbox Port
│   ├── Memory Store
│   └── SQLite Store
│
└── processor.py
```

不要引入：

```text
EventRouter
DeliveryStrategyRegistry
PublisherFactory
OutboxManager
EventDispatcherManager
```

当前只有两条明确交付路径，不需要过度抽象。

---

# 十七、删除旧结构

本任务不考虑兼容性。

完成后删除：

* EventBuffer 中的 EventBus 字段；
* EventBuffer 非 Active 时直接发布的行为；
* `publish()`；
* `publish_many()`；
* `snapshot()`；
* `drain()`；
* `discard()`；
* Processor 对 Direct Publisher 的依赖；
* Processor 对 Outbox Publisher 的依赖；
* Processor 内的 `publish_pending()` 调用；
* Processor 内的 Direct Publish；
* 旧大型 Journal Port；
* Memory Outbox 发布后直接删除记录的行为；
* 旧构造参数；
* 旧 Re-export；
* Alias、Wrapper、Fallback；
* 为旧测试或示例保留的兼容代码。

更新全部生产调用方、测试、示例和文档。

---

# 十八、测试要求

必须针对新边界重新编写测试，不迁就旧测试。

## 18.1 EventBuffer Unit Tests

覆盖：

1. `begin()` 后可以 `add()`；
2. 未 `begin()` 调用 `add()` 必须失败；
3. 未 `begin()` 调用 `extend()` 必须失败；
4. 重复 `begin()` 必须失败；
5. `seal()` 返回不可变 Batch；
6. `seal()` 后 Buffer 不再 Active；
7. `abort()` 返回丢弃事件；
8. `abort()` 不发布事件；
9. Buffer 不需要 EventBus；
10. Buffer 不 import Journal 或 Runtime。

## 18.2 Delivery Intent Tests

覆盖：

* NONE 的字段约束；
* DIRECT 必须有 Batch；
* DIRECT 不允许 Execution Sequence；
* DURABLE_OUTBOX 必须有 Execution Sequence；
* DURABLE_OUTBOX 不允许 Direct Batch；
* 非法组合必须构造失败。

## 18.3 Processor Trade Tests

验证：

```text
Trade APPLIED
Journal 有 Fact
Outbox 有 Event
Processor 不调用 EventBus
Processor 不调用 Outbox Publisher
Result Intent = DURABLE_OUTBOX
```

同时验证：

* Event 在 Journal Append 前不可见；
* Journal Append 失败时没有 Delivery Intent；
* Journal Append 失败时 Event 未进入 EventBus；
* 重复 Trade 不创建新 Fact 或新 Outbox。

## 18.4 Processor Non-Trade Tests

分别覆盖：

```text
Accepted
Rejected
Cancelled
Position
Account
Connection
```

验证：

* 不产生 Committed Trade Fact；
* 不产生 Trade Outbox；
* 返回 DIRECT 或 NONE Intent；
* Processor 不直接调用 EventBus。

## 18.5 Direct Publisher Tests

覆盖：

* 正常发布；
* 空 Batch；
* EventBus 异常；
* 返回独立 Delivery Failure；
* 不修改业务 Processing Result；
* 不触发 Reconciliation。

## 18.6 Outbox Contract Tests

Memory 与 SQLite 执行同一套测试：

* Pending 顺序；
* `begin_attempt()` 增加 Attempt Count；
* Failed 状态；
* Last Error；
* Last Attempt Time；
* Published 状态；
* Published Time；
* Published Record 保留；
* Pending Query 排除 Published；
* Pending Count；
* 重启后 Pending 保留；
* 重启后 Event ID 不变；
* 重启后 Event Payload 不变。

## 18.7 Outbox Publisher Tests

覆盖：

1. 全部发布成功；
2. 第一条失败后停止；
3. 后续 Event 不越过失败 Event；
4. 失败记录持久化；
5. 第二次重试成功；
6. Attempt Count 正确；
7. Event ID 重试不变；
8. 不新增 Fact；
9. 不重新执行业务 Mutation；
10. Outbox Mark Published 失败时仍保持 At-Least-Once 语义。

## 18.8 Delivery Coordinator Tests

覆盖：

* NONE；
* DIRECT；
* DURABLE_OUTBOX；
* Direct Failure；
* Outbox Failure；
* Coordinator 不修改 Processing Status；
* Coordinator 不读取 Manager。

## 18.9 Runtime Integration Tests

覆盖：

```text
Runtime Start
→ Drain Old Pending Outbox

Broker Update
→ Processor
→ Delivery Coordinator

Runtime Stop
→ Final Best-Effort Drain
```

验证：

* Trade Event 只有 Outbox 路径；
* Non-Trade Event 只有 Direct 路径；
* Outbox 失败后 Runtime 保存 Delivery Diagnostic；
* 下次 Drain 可恢复发布；
* Backtest 不启动后台线程。

## 18.10 架构门禁

增加 AST 或等价静态测试：

* `event_buffer.py` 不 import EventBus；
* `event_buffer.py` 不 import Journal；
* `processor.py` 不 import EventBus；
* `processor.py` 不 import Direct Publisher；
* `processor.py` 不 import Outbox Publisher；
* Direct Publisher 不 import Journal；
* Outbox Publisher 不 import Manager；
* Result Collector 不读取 Outbox Delivery 状态；
* Broker 插件不访问 Journal 或 Delivery Coordinator。

---

# 十九、测试迁移原则

本任务不保留旧接口。

对于因新边界而失败的旧测试：

* 若测试验证的是正确业务行为，迁移到新接口；
* 若测试验证的是旧实现细节，删除并用新测试替换；
* 不添加旧接口 Alias；
* 不在 Production Code 中增加测试专用分支；
* 不为了旧 Mock 构造函数保留无用参数；
* 不通过放宽断言让测试通过；
* 不使用 `skip`、`xfail` 或平台判断绕过。

示例和 Demo 同样必须直接使用新接口。

---

# 二十、实施顺序

严格按以下顺序实施：

```text
1. 审计当前 Event 和 Delivery 调用链
2. 新增 Event Batch
3. 将 EventBuffer 改为纯内存组件
4. 新增 Delivery Mode、Intent 和 Result
5. 调整 Processing Result
6. 重构 Processor，只返回 Delivery Intent
7. 拆分 Commit、Query、Outbox Ports
8. 统一 Memory/SQLite Outbox 模型
9. 补齐 Attempt、Failure、Published 审计
10. 实现 Direct Publisher
11. 完成 Outbox Publisher
12. 实现 Delivery Coordinator
13. 将 Delivery 调度移动到 Runtime
14. 增加启动、处理后、停止前 Drain
15. 重写单元、Contract、Integration 和架构测试
16. 删除旧接口和兼容代码
17. 更新示例和文档
18. 运行完整工程门禁
```

---

# 二十一、不在本任务范围内

本任务不实现：

```text
Prepared Execution Transaction
Manager Prepare/Apply
Manager Rollback
Projection Checkpoint Replay
完整 Runtime Recovery
Paper Runtime
Live Runtime
通用 Runtime Event Journal
所有 Non-Trade Event 持久化
Exactly-Once Delivery
分布式 Outbox Worker
```

但新边界必须为这些后续能力保留正确接口。

特别是：

> 当前 Manager 仍可能在 Journal 前原地修改，本任务不得声称已完成完整 Execution 原子事务。

---

# 二十二、验收标准

任务只有满足以下条件才算完成。

## EventBuffer

* 不持有 EventBus；
* 不持有 Journal；
* 不直接发布；
* 未 Active 时写入立即失败；
* Seal 后产生不可变 Event Batch。

## Processor

* 不依赖 EventBus；
* 不依赖 Direct Publisher；
* 不依赖 Outbox Publisher；
* 只返回 Delivery Intent；
* Trade 提交与 Event Delivery 解耦。

## Trade Delivery

* Fact 与 Outbox Event 同时写入 Commit Store；
* Event 只通过 Outbox Publisher 进入 EventBus；
* Outbox 失败不改变 Trade APPLIED 状态；
* Delivery 重试不重新执行业务 Mutation。

## Non-Trade Delivery

* 不进入 Trade Outbox；
* 只通过 Direct Publisher 发布；
* Direct Failure 与业务状态分开记录。

## Outbox

* Memory 与 SQLite 语义一致；
* Published Record 可审计；
* Attempt Count 正确；
* Failure Error 正确；
* Published Time 正确；
* Pending 顺序稳定；
* 重启后可继续投递；
* Event ID 重试时不变。

## Runtime

* 启动时 Drain；
* 每次 Processing 后按 Intent Delivery；
* 停止前 Best-Effort Drain；
* 保存 Delivery Diagnostic。

## 清理

* 删除旧 Publisher API；
* 删除旧大型 Journal Port；
* 删除兼容层；
* 删除旧测试实现依赖；
* 示例和文档全部使用新边界。

---

# 二十三、工程门禁

至少执行并记录真实结果：

```bash
uv lock --check
uv sync --frozen --all-packages --all-groups

uv run ruff check src tests examples packages
uv run ruff format --check src tests examples packages

uv run mypy src/onlyalpha
uv run mypy --config-file packages/fake/onlyalpha-plugin-broker-virtual/pyproject.toml \
  packages/fake/onlyalpha-plugin-broker-virtual/src/onlyalpha_plugin_broker_virtual
uv run mypy --config-file packages/provider/onlyalpha-plugin-tushare/pyproject.toml \
  packages/provider/onlyalpha-plugin-tushare/src/onlyalpha_plugin_tushare
uv run mypy packages/provider/onlyalpha-plugin-miniqmt/src/onlyalpha_plugin_miniqmt

uv run pytest tests -q \
  -m "not external and not requires_network and not requires_tushare and not requires_local_qmt"

uv run pytest packages/fake/onlyalpha-plugin-broker-virtual/tests -q
uv run pytest packages/provider/onlyalpha-plugin-tushare/tests -q \
  -m "not external and not requires_network and not requires_tushare"
uv run pytest packages/provider/onlyalpha-plugin-miniqmt/tests -q \
  -m "not external and not requires_network and not requires_local_qmt"

uv run pytest tests/integration -q
```

同时运行：

* Scenario Tests；
* Conformance Tests；
* Integration Demo Tests；
* Wheel/sdist Build；
* Twine Check；
* Clean Install；
* Entry Point Smoke。

必须确认 GitHub Actions：

```text
Core / Ubuntu
Core / Windows
Core / macOS
Virtual Broker Matrix
Tushare Matrix
MiniQMT Offline
Product Gates
Build and Smoke
```

全部通过。

真实外部 Tushare、真实 MiniQMT 和不可用平台环境必须明确记录为未执行，不得伪称通过。

---

# 二十四、文档更新

更新：

* Execution Processor 文档；
* EventBus 文档；
* Runtime 生命周期文档；
* Committed Journal 文档；
* Outbox 文档；
* README；
* AGENTS；
* 架构 ADR。

文档必须明确：

```text
EventBuffer = Event Production Buffer
Delivery Intent = Processing 与 Delivery 的边界
Direct Publisher = Non-Durable Best-Effort Delivery
Outbox Publisher = Durable At-Least-Once Delivery
Runtime Coordinator = Delivery Owner
EventBus = In-Process Distribution
```

同时明确：

* Trade Event 走 Durable Outbox；
* Non-Trade Event 当前走 Direct Delivery；
* Delivery Failure 不等于 Broker Reconciliation；
* 当前不提供 Exactly-Once；
* 完整 Execution Atomic Commit 仍是后续任务。

---

# 二十五、最终交付报告

完成后输出：

## 1. 修改前问题

列出 Buffer、Processor、Direct Publisher、Outbox Publisher 当前职责重叠。

## 2. 新边界

说明每个组件唯一职责。

## 3. 新调用链

说明：

```text
Processor
→ Delivery Intent
→ Runtime Coordinator
→ Direct / Outbox Publisher
→ EventBus
```

## 4. Outbox 语义

说明：

* At-Least-Once；
* Attempt；
* Failure；
* Published；
* Stable Event ID；
* Runtime Retry 时点。

## 5. 删除内容

列出删除的旧接口、构造参数、兼容层和旧测试。

## 6. 测试结果

提供真实命令、通过数量和 CI Matrix 结果。

## 7. 剩余问题

明确说明尚未完成：

```text
Manager-before-Journal 原子性
Prepared Execution Transaction
Projection Replay
完整 Runtime Recovery
Non-Trade Durable Facts
Exactly-Once Delivery
```

不得将这些描述为已解决。

---

# 最终目标

完成后必须满足：

```text
EventBuffer 只收集
Processor 只产生交付意图
Commit Store 只持久化
Direct Publisher 只直接投递
Outbox Publisher 只投递持久事件
Runtime Coordinator 只调度
EventBus 只分发
```

并形成以下稳定运行链：

```text
Trade:
Business Processing
→ Event Batch
→ Fact + Outbox Durable Commit
→ DURABLE_OUTBOX Intent
→ Runtime Coordinator
→ Outbox Publisher
→ EventBus

Non-Trade:
Business Processing
→ Event Batch
→ DIRECT Intent
→ Runtime Coordinator
→ Direct Publisher
→ EventBus
```

优先解决职责所有权、失败语义、可测试性和后续恢复能力，不要为了改动量小、旧测试通过或兼容旧接口而保留错误边界。
