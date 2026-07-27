# OnlyAlpha：实现 Prepared Execution Transaction 与幂等 Projection Contract

## 一、任务目标

以当前 OnlyAlpha `master` 源码和测试为唯一事实源，重新审计成交审计成交处理链，建立下一阶段 Execution 原子提交所需的正式领域模型和接口边界：

```text
Broker Trade Update
→ Pure Prepare
→ Prepared Execution Transaction
→ Durable Commit
→ Idempotent Projection
→ Projection Ready
→ Outbox Delivery
```

本任务重点实现：

1. `OnlyPreparedExecutionTransaction`；
2. 强类型 Execution Projection 模型；
3. Prepared Transaction 稳定序列化与 Hash；
4. Commit Store 新契约；
5. Projection Apply 幂等契约；
6. Memory 与 SQLite Store 的一致实现；
7. 针对新模型重新编写测试和架构门禁。

本任务不得为了旧接口、旧测试、旧示例、旧文档或旧 Mock 保留错误设计。

不考虑向后兼容。

必须直接删除错误接口并修改所有受影响调用方、测试、示例和导出。

---

# 二、第一性原则

## 1. Durable Commit 失败时，Manager 必须保持不变

目标不变量：

```text
Prepared Transaction 构建失败
→ 无 Manager Mutation
→ 无 Committed Fact
→ 无 Outbox

Durable Commit 失败
→ 无 Manager Mutation
→ 无 Committed Fact
→ 无可交付 Event
```

当前 Trade 路径会在 Journal Append 前直接修改多个 Manager。本任务建立的新 Prepared Transaction 体系不得复制这一错误。

## 2. 持久事实必须足以重建全部业务状态

只持久化成交摘要不够。

持久事务必须能够重建：

* Order；
* Position；
* Position Allocation；
* Settlement；
* Margin；
* Fee；
* Account；
* Strategy Ledger；
* Reservation；
* Risk；
* Valuation。

不得依赖：

* Broker SDK 内存对象；
* Python 闭包；
* Manager 实例引用；
* 不可序列化 Callable；
* 进程内临时结果；
* 当前 Runtime 的隐式状态。

## 3. Prepare 阶段必须是纯计算

正确形式：

```text
Before Snapshot
+ Immutable Command
→ After Snapshot
+ Projection
+ Domain Events
```

Prepare 阶段不得调用：

```text
manager.apply_*
manager.create_*
manager.release_*
manager.consume_*
manager.reserve_*
EventBus.publish
OutboxPublisher
```

不得通过对整个 Runtime 或 Manager 做 `deepcopy` 来伪装无副作用事务。

## 4. Projection 必须由 Manager 自身保证幂等

Coordinator 级去重不足以防止崩溃重放。

每个 Manager 的 Projection Apply 入口必须满足：

```text
相同 execution_sequence + 相同 payload_hash
→ IDEMPOTENT，不修改状态

相同 execution_sequence + 不同 payload_hash
→ PAYLOAD_CONFLICT

新 execution_sequence + expected_version 匹配
→ APPLIED

新 execution_sequence + expected_version 不匹配
→ VERSION_CONFLICT
```

## 5. Projection Ready 前，Outbox 不得交付

正确顺序：

```text
Durable Commit
→ Apply Projections
→ Mark Projection Ready
→ Publish Outbox
```

不得出现：

```text
EventBus 已收到 TRADE_APPLIED
但 Position、Account 或 Ledger 尚未完成 Projection
```

## 6. Execution Sequence 只能有一个权威

删除以下两步式权威：

```text
next_sequence()
→ append_transaction()
```

Sequence 必须由 Commit Store 在同一个锁或数据库事务中分配。

---

# 三、修改前审计

实施前执行：

```bash
git status
git log -n 10 --oneline

rg "OnlyExecutionProcessor"
rg "OnlyCommittedExecutionFact"
rg "OnlyDurableExecutionCommit"
rg "OnlyExecutionCommitPort"
rg "next_sequence"
rg "append_transaction"
rg "OnlyExecutionMutationBundle"
rg "apply_trade"
rg "apply_trade_cash_flow"
rg "apply_trade_accounting"
rg "consume_order_fill"
rg "SettlementManager"
rg "MarginManager"
rg "FeeManager"
rg "execution_sequence"
rg "checkpoint"
```

形成简短审计记录：

1. 当前 Trade 的完整 Mutation 顺序；
2. 哪些 Manager 在 Journal 前修改；
3. Committed Fact 当前缺少哪些恢复字段；
4. Sequence 当前由谁分配；
5. 当前 Store 如何处理幂等和 Outbox；
6. 当前 Manager 是否记录 Applied Execution Sequence；
7. 当前哪些测试依赖旧 `next_sequence()` 和 `append_transaction()`；
8. 当前哪些 DTO 包含不可稳定序列化字段；
9. 当前 Event 是由 Manager Mutation 产生还是可纯计算生成；
10. 当前 Runtime 主链在哪些位置依赖旧 Journal Port。

以当前源码为准，不机械假设文件路径和类型仍与历史提示一致。

---

# 四、任务边界

本任务实现完整、可用的 Prepared Transaction Domain 与 Store Contract，但暂不把 Backtest Trade 主链切换到新 Coordinator。

必须交付生产代码，不得只添加文档、Protocol 或空实现。

本任务包含：

```text
Prepared Transaction
Projection Models
Stable Codec
Stable Hash
Store Commit Contract
Memory Store
SQLite Store
Projection Apply Contract
Reference In-Memory Projection State
Contract Tests
Architecture Tests
```

本任务不包含：

```text
替换当前 ExecutionProcessor Trade 主链
完整 Manager Reducer 改造
完整 Runtime Recovery
Paper / Live Runtime
Non-Trade Durable Facts
Manager Durable Snapshot
Exactly-Once Delivery
```

但新接口必须能够被下一任务直接接入，不能是演示性占位。

---

# 五、Prepared Transaction 模型

## 5.1 Prepared Transaction

实现强类型不可变模型，建议：

```python
@dataclass(frozen=True, slots=True)
class OnlyPreparedExecutionTransaction:
    transaction_id: str

    runtime_id: OnlyRuntimeId
    gateway_id: OnlyBrokerGatewayId
    account_id: OnlyAccountId

    broker_update_id: OnlyBrokerUpdateId
    trade_id: OnlyTradeId
    source_sequence: int

    prepared_at: OnlyTimestamp

    fact_draft: OnlyCommittedExecutionFactDraft
    projections: tuple[OnlyExecutionProjection, ...]
    outbox_events: tuple[OnlyEvent, ...]

    preconditions: tuple[OnlyExecutionPrecondition, ...]
    stable_hash: str
```

具体字段可以根据当前领域模型调整，但必须满足：

* immutable；
* 完整 Runtime/Gateway/Account/Trade Scope；
* 不包含最终 `execution_sequence`；
* 不包含 Manager、Runtime、Clock、Callable 或 Broker SDK 对象；
* 可以无损序列化；
* 可以稳定反序列化；
* 相同业务输入生成相同 Stable Hash；
* Projection 顺序明确并持久化。

## 5.2 Fact Draft

新增：

```python
@dataclass(frozen=True, slots=True)
class OnlyCommittedExecutionFactDraft:
    ...
```

Fact Draft 包含完整成交权威字段，但不包含：

```text
execution_sequence
committed_at
```

最终 Fact 必须由 Store 在 Commit 时完成：

```text
Fact Draft
+ Store Assigned Sequence
+ Commit Timestamp
→ OnlyCommittedExecutionFact
```

不得由 Processor 先调用 `next_sequence()` 再构造 Fact。

## 5.3 Preconditions

实现明确的事务前置条件：

```python
@dataclass(frozen=True, slots=True)
class OnlyExecutionPrecondition:
    component: OnlyExecutionProjectionComponent
    entity_key: str
    expected_version: int
    expected_state_hash: str | None
```

用途：

* 防止基于过期 Snapshot 提交；
* 检测 Prepare 与 Projection 之间状态漂移；
* 为未来 Live Runtime 并发控制提供边界。

---

# 六、Projection 类型体系

## 6.1 禁止松散 Payload

禁止使用：

```python
dict[str, object]
Any
object
tuple[object, ...]
```

作为核心 Projection Payload。

实现明确的 Tagged Union：

```python
OnlyExecutionProjection = (
    OnlyOrderExecutionProjection
    | OnlyPositionExecutionProjection
    | OnlyAllocationExecutionProjection
    | OnlySettlementExecutionProjection
    | OnlyMarginExecutionProjection
    | OnlyFeeExecutionProjection
    | OnlyAccountExecutionProjection
    | OnlyStrategyLedgerExecutionProjection
    | OnlyReservationExecutionProjection
    | OnlyRiskExecutionProjection
    | OnlyValuationExecutionProjection
)
```

## 6.2 公共 Projection 元数据

每个 Projection 至少包含：

```python
@dataclass(frozen=True, slots=True)
class OnlyExecutionProjectionIdentity:
    component: OnlyExecutionProjectionComponent
    entity_key: str
    expected_version: int
    result_version: int
    projection_sequence: int
    payload_hash: str
```

约束：

* `projection_sequence` 从 1 连续递增；
* `expected_version >= 0`；
* `result_version > expected_version`，除非该 Projection 明确是幂等状态确认；
* `payload_hash` 由稳定 Payload 生成；
* 相同 Component 和 Entity 不允许出现冲突 Projection；
* Projection 顺序属于事务事实，不能只依赖 Python 调用顺序。

## 6.3 推荐固定顺序

定义明确枚举顺序：

```text
ORDER
POSITION
ALLOCATION
SETTLEMENT
MARGIN
FEE
ACCOUNT
STRATEGY_LEDGER
RESERVATION
RISK
VALUATION
```

验证 Transaction 中 Projection 顺序符合该规则。

不得通过字符串排序偶然决定业务顺序。

---

# 七、Projection Payload 内容

每个 Projection 必须描述可重放的业务变化，不得只保存说明文字。

## 7.1 Order Projection

至少包含：

```text
order_id
before_status
after_status
before_filled_quantity
after_filled_quantity
before_average_fill_price
after_average_fill_price
fill
external_update_id
```

## 7.2 Position Projection

至少包含：

```text
position_key
before_quantity
after_quantity
before_available_quantity
after_available_quantity
before_average_price
after_average_price
realized_pnl_delta
resulting_realized_pnl
```

## 7.3 Allocation Projection

至少包含：

```text
allocation_key
before_quantity
after_quantity
before_cost
after_cost
realized_pnl_delta
```

## 7.4 Settlement Projection

至少包含：

```text
instruction
before_state
after_state
generated_records
```

## 7.5 Margin Projection

至少包含：

```text
instruction
reserved_before
reserved_after
occupied_before
occupied_after
maintenance_before
maintenance_after
```

## 7.6 Fee Projection

至少包含：

```text
fee_instruction
fee_records
authoritative_total
fee_breakdown
```

## 7.7 Account Projection

至少包含：

```text
account_id
cash_before
cash_after
frozen_cash_before
frozen_cash_after
realized_pnl_before
realized_pnl_after
unrealized_pnl_before
unrealized_pnl_after
fees_before
fees_after
position_market_value_before
position_market_value_after
equity_before
equity_after
```

## 7.8 Strategy Ledger Projection

至少包含：

```text
ledger_key
cash_before
cash_after
realized_pnl_before
realized_pnl_after
unrealized_pnl_before
unrealized_pnl_after
fees_before
fees_after
equity_before
equity_after
trade_count_before
trade_count_after
```

## 7.9 Reservation Projection

必须明确区分：

```text
ACCOUNT_CASH
STRATEGY_CASH
POSITION
MARGIN
RISK
```

并记录：

```text
reservation_id
before_state
after_state
consumed_delta
released_delta
remaining
```

## 7.10 Risk Projection

至少包含：

```text
cluster_id
account_id
instrument_id
order_id
exposure_before
exposure_after
reservation_state_before
reservation_state_after
```

不得只保存 `"risk refreshed"` 之类不可重放摘要。

---

# 八、稳定序列化与 Hash

## 8.1 Codec

为以下类型实现正式 Codec：

```text
OnlyPreparedExecutionTransaction
OnlyCommittedExecutionFactDraft
OnlyExecutionProjection
OnlyExecutionPrecondition
OnlyCommittedExecutionTransaction
```

要求：

* JSON 可序列化；
* Decimal 不通过 float；
* Timestamp 使用明确 Unix Nanoseconds；
* Enum 使用稳定 Value；
* Identifier 使用规范字符串；
* Tuple 顺序保持；
* Mapping 必须稳定排序；
* Event 必须保留原始 `event_id`；
* Schema Version 必须显式存在。

禁止：

```text
repr()
pickle
dataclasses.asdict() 后直接 json.dumps()
Python 对象地址
无版本 Payload
```

## 8.2 Stable Hash

实现单一公共函数：

```python
def only_execution_payload_hash(payload: str) -> str:
    ...
```

使用 SHA-256。

Prepared Transaction 的 Hash 必须覆盖：

```text
Scope
Broker Update Identity
Fact Draft
Ordered Projections
Outbox Events
Preconditions
Schema Version
```

不得包含：

* 随机内存地址；
* Runtime 当前对象状态；
* 非确定性的字典遍历顺序；
* Store 分配的 Sequence；
* Commit 时间。

## 8.3 Round-Trip

必须保证：

```text
decode(encode(value)) == value
```

以及：

```text
encode(decode(payload)) == canonical_payload
```

---

# 九、Committed Transaction

新增：

```python
@dataclass(frozen=True, slots=True)
class OnlyCommittedExecutionTransaction:
    runtime_id: OnlyRuntimeId
    execution_sequence: int
    transaction_id: str

    fact: OnlyCommittedExecutionFact
    projections: tuple[OnlyExecutionProjection, ...]
    outbox_events: tuple[OnlyEvent, ...]

    committed_at: OnlyTimestamp
    prepared_hash: str
    committed_hash: str

    projection_ready: bool
    projected_at: OnlyTimestamp | None
    projection_error: str | None
```

约束：

* `execution_sequence > 0`；
* Fact Sequence 与 Transaction Sequence 一致；
* Projection Ready 时 `projected_at` 必须存在；
* Projection Ready 时 `projection_error` 必须为空；
* 未 Ready 时 Outbox 不允许进入 Pending Delivery 查询；
* `prepared_hash` 必须匹配 Prepared Transaction；
* `committed_hash` 覆盖最终 Sequence 与 Commit Timestamp。

---

# 十、Store Port 重构

删除旧的两步式：

```text
next_sequence
append_transaction
```

不保留 Alias、Wrapper 或兼容层。

## 10.1 Commit Port

实现：

```python
class OnlyExecutionTransactionCommitPort(Protocol):
    def commit(
        self,
        prepared: OnlyPreparedExecutionTransaction,
        *,
        committed_at: OnlyTimestamp,
    ) -> OnlyExecutionTransactionCommitResult:
        ...
```

Result：

```python
@dataclass(frozen=True, slots=True)
class OnlyExecutionTransactionCommitResult:
    transaction: OnlyCommittedExecutionTransaction
    inserted: bool
```

幂等规则：

```text
相同 transaction_id + 相同 prepared_hash
→ 返回原 Transaction，inserted=False

相同 Trade Key + 相同 prepared_hash
→ 返回原 Transaction，inserted=False

相同 Update Key + 相同 prepared_hash
→ 返回原 Transaction，inserted=False

相同幂等键 + 不同 prepared_hash
→ Hard Conflict
```

## 10.2 Query Port

实现：

```python
class OnlyExecutionTransactionQueryPort(Protocol):
    def get_by_sequence(...)
    def get_by_transaction_id(...)
    def get_by_trade(...)
    def get_by_update(...)
    def records(...)
```

## 10.3 Projection State Port

实现：

```python
class OnlyExecutionProjectionStatePort(Protocol):
    def mark_projection_ready(
        self,
        runtime_id: OnlyRuntimeId,
        execution_sequence: int,
        *,
        projected_at: OnlyTimestamp,
    ) -> None:
        ...

    def mark_projection_failed(
        self,
        runtime_id: OnlyRuntimeId,
        execution_sequence: int,
        *,
        failed_at: OnlyTimestamp,
        error: str,
    ) -> None:
        ...

    def unprojected(
        self,
        runtime_id: OnlyRuntimeId,
        *,
        after_sequence: int = 0,
    ) -> tuple[OnlyCommittedExecutionTransaction, ...]:
        ...
```

## 10.4 Outbox Port

现有 Outbox Port 改为只返回：

```text
projection_ready = true
published = false
```

的事件。

即使 Transaction 已 Durable Commit，只要 Projection 未 Ready，Outbox Publisher 也不得看到该事件。

---

# 十一、Memory Store

实现 Contract 等价的内存 Store。

必须保存：

```text
Committed Transactions
Trade Index
Update Index
Transaction ID Index
Projection State
Outbox Records
```

要求：

* Sequence 在 Commit 锁内分配；
* Sequence 连续；
* Commit 与 Outbox 创建原子完成；
* Projection Ready 前 Outbox 不 Pending；
* Published Record 保留；
* 所有查询稳定排序；
* 不允许调用方修改内部集合；
* 不因测试方便暴露可变字典。

---

# 十二、SQLite Store

可直接调整当前 SQLite Schema，不考虑旧数据库兼容。

建议表：

## `execution_transactions`

```text
runtime_id
execution_sequence
transaction_id

gateway_id
account_id
trade_id
broker_update_id
source_sequence

prepared_payload
prepared_hash

committed_payload
committed_hash

committed_at
projection_ready
projected_at
projection_error
projection_failed_at
```

约束：

```text
PRIMARY KEY(runtime_id, execution_sequence)
UNIQUE(transaction_id)
UNIQUE(runtime_id, gateway_id, account_id, trade_id)
UNIQUE(runtime_id, gateway_id, account_id, broker_update_id)
```

## `execution_outbox`

```text
runtime_id
execution_sequence
event_sequence
event_id
event_payload

projection_ready
published
attempt_count
last_attempted_at
published_at
last_error
```

Commit 必须在一个 SQLite Transaction 中完成：

```text
分配 Sequence
→ Finalize Fact
→ 写 Committed Transaction
→ 写 Ordered Outbox
```

不得在事务外先查询 Sequence 再 Insert。

SQLite 实现需要：

* `RLock` 或等价线程保护；
* Payload Hash 校验；
* Round-Trip 校验；
* 显式 `close()`；
* 重启后完整读取；
* SQLite 与 Memory 运行同一套 Contract Tests。

---

# 十三、Projection Apply Contract

新增正式接口：

```python
class OnlyExecutionProjectionTarget(Protocol):
    @property
    def component(self) -> OnlyExecutionProjectionComponent:
        ...

    def apply_execution_projection(
        self,
        execution_sequence: int,
        projection: OnlyExecutionProjection,
    ) -> OnlyProjectionApplyResult:
        ...
```

Result：

```python
class OnlyProjectionApplyStatus(StrEnum):
    APPLIED = "APPLIED"
    IDEMPOTENT = "IDEMPOTENT"
    VERSION_CONFLICT = "VERSION_CONFLICT"
    PAYLOAD_CONFLICT = "PAYLOAD_CONFLICT"
    INVALID_COMPONENT = "INVALID_COMPONENT"
```

```python
@dataclass(frozen=True, slots=True)
class OnlyProjectionApplyResult:
    status: OnlyProjectionApplyStatus
    component: OnlyExecutionProjectionComponent
    entity_key: str
    execution_sequence: int
    before_version: int
    after_version: int
    payload_hash: str
```

## 13.1 Reference Projection State

为了验证 Contract，增加一个正式的、非测试专用的轻量实现：

```python
class OnlyInMemoryExecutionProjectionState:
    ...
```

它负责：

* 按 Component + Entity Key 保存 Version；
* 保存最后 Applied Sequence；
* 保存每个 Sequence 的 Payload Hash；
* 检查幂等；
* 检查 Version Conflict；
* 检查 Payload Conflict。

该组件不得承担具体 Order、Position 或 Account 业务状态，只验证公共 Projection Contract。

不要为了测试把幂等逻辑散落在 Fixture 中。

---

# 十四、Projection Applier

实现：

```python
class OnlyExecutionProjectionApplier:
    def __init__(
        self,
        targets: Mapping[
            OnlyExecutionProjectionComponent,
            OnlyExecutionProjectionTarget,
        ],
    ) -> None:
        ...

    def apply(
        self,
        transaction: OnlyCommittedExecutionTransaction,
    ) -> OnlyExecutionProjectionBatchResult:
        ...
```

要求：

* 严格按 `projection_sequence` 执行；
* Component 必须有唯一 Target；
* 重复执行同一 Transaction 必须全部返回 `IDEMPOTENT`；
* 中途失败立即停止；
* 返回已完成 Projection；
* 不执行 Event Delivery；
* 不修改 Store Projection Ready；
* 不吞掉 Conflict；
* 不自行补偿已成功 Projection。

Batch Result 至少包含：

```text
execution_sequence
applied
idempotent
failed_projection
status
error
```

---

# 十五、事件生成边界

Prepared Transaction 的 Outbox Event 必须作为输入持久化。

要求：

* Event ID 原样保留；
* Stable Codec 不重新生成 ID；
* Retry 不重新构建 Event；
* Projection Apply 不再次产生相同 Event；
* Manager Projection Target 不持有 EventBus；
* Projection Applier 不持有 EventBus；
* Store 不发布 Event。

当前旧 Manager Publisher 接口暂时不在本任务中全部删除，但新 Projection Contract 不得依赖它们。

为下一阶段留下明确规则：

```text
Reducer / Planner 生成 Event
Store 持久化 Event
Projection Apply 不再发布 Event
Outbox Publisher 负责交付 Event
```

---

# 十六、删除和迁移

不考虑旧接口兼容。

删除：

```text
OnlyExecutionCommitPort.next_sequence
旧 append_transaction 契约
旧 OnlyDurableExecutionCommit
依赖调用方预先分配 Sequence 的接口
只保存 Fact + Events、但不保存 Projection 的提交模型
旧测试中的兼容 Fixture
旧 Re-export
Alias
Wrapper
Deprecated 标记
```

更新：

* `execution/__init__.py`；
* Collector Query 类型；
* Journal Contract Tests；
* Outbox Tests；
* 类型注解；
* 文档；
* 历史示例中直接调用旧 Commit Port 的代码。

如果当前 Runtime 主链仍依赖旧 Store API，为避免在本任务中切换 Trade 主链，可以提供明确的新 Transaction Store，与当前 Legacy Runtime Store 暂时并存。

但必须满足：

* 两者命名明确；
* 新旧接口不能互相继承；
* 新接口不能包装旧错误语义；
* 新代码不能继续使用 `next_sequence()`；
* 文档明确旧 Runtime 接入将在下一任务删除。

若可以在不扩大风险的情况下直接让当前 Journal Query 读取新 Store，则优先直接迁移，不保留双 Store。

---

# 十七、测试要求

必须针对新接口重新设计测试。

不得为了旧测试保留错误 API。

## 17.1 Prepared Transaction Tests

覆盖：

1. 合法 Transaction；
2. 缺失 Scope；
3. 空 Transaction ID；
4. Projection Sequence 不连续；
5. Projection 顺序错误；
6. 重复 Component + Entity 冲突；
7. Fact Draft 与 Transaction Scope 不一致；
8. Event Runtime Scope 不一致；
9. Stable Hash 正确；
10. Immutable；
11. Round-Trip；
12. Canonical Encode。

## 17.2 Projection Model Tests

每种 Projection 至少覆盖：

* 合法构造；
* Expected/Result Version；
* Payload Hash；
* Scope；
* Decimal 精度；
* Timestamp；
* 序列化；
* 非法状态组合。

## 17.3 Store Contract Tests

Memory 与 SQLite 运行完全相同的测试：

1. Commit 自动分配 Sequence；
2. Sequence 连续；
3. 相同 Transaction 幂等；
4. 相同 Trade 幂等；
5. 相同 Update 幂等；
6. 相同幂等键不同 Hash 冲突；
7. Transaction、Fact、Projection、Outbox 同时写入；
8. Commit 失败无部分数据；
9. Projection Ready 状态；
10. Projection Failed 状态；
11. Unprojected Query；
12. Outbox 在 Ready 前不可见；
13. Ready 后 Outbox 可见；
14. Published Record 保留；
15. SQLite 重启恢复；
16. Event ID 不变；
17. Payload Hash 损坏检测；
18. Transaction 顺序稳定。

## 17.4 Projection State Tests

覆盖：

```text
首次 Apply → APPLIED
相同 Sequence + 相同 Hash → IDEMPOTENT
相同 Sequence + 不同 Hash → PAYLOAD_CONFLICT
Expected Version 错误 → VERSION_CONFLICT
Component 错误 → INVALID_COMPONENT
```

## 17.5 Projection Applier Tests

覆盖：

1. 正确顺序执行；
2. 重复执行全部 Idempotent；
3. 中间 Projection 失败后停止；
4. 已成功 Projection 不自动回滚；
5. 缺少 Target；
6. Component 冲突；
7. Version Conflict；
8. Payload Conflict；
9. 不调用 EventBus；
10. 不调用 Outbox Publisher；
11. 不修改 Store Ready 状态。

## 17.6 故障注入测试

至少覆盖：

### Commit 写 Transaction 后、Outbox 前失败

整个数据库事务必须回滚。

### Commit 后、Projection 前停止

Transaction 存在，Outbox 不可交付。

### Projection 部分完成

重复 Apply 时已完成部分返回 Idempotent，剩余部分继续执行。

### Projection 全部完成、Ready 标记前停止

重复 Apply 全部 Idempotent，然后可以 Mark Ready。

### Ready 后发布失败

Outbox 保持 Pending，Transaction 和 Projection 状态不变。

## 17.7 确定性测试

相同 Prepared 输入执行两次：

```text
Prepared Payload 相同
Prepared Hash 相同
Projection Payload 相同
Event ID 相同
```

Store 分配的 Sequence 和 Commit Timestamp 可以不同，但 Prepared Hash 必须一致。

---

# 十八、架构门禁

增加 AST 或等价静态测试。

验证：

* Prepared Transaction 模块不 import Manager；
* Prepared Transaction 模块不 import Runtime；
* Prepared Transaction 模块不 import EventBus；
* Projection Model 不 import Manager；
* Store 不 import Manager；
* Projection Applier 不 import EventBus；
* Projection Applier 不 import Outbox Publisher；
* Projection Target 不 import Runtime；
* Broker 插件不 import Transaction Store；
* Cluster 不访问 Projection Target；
* `next_sequence()` 不再存在于新 Commit Port；
* 新核心模型中不存在 `Any`；
* 新核心 Payload 中不存在 `dict[str, object]`；
* 新代码不使用 `pickle`；
* 新代码不使用 Manager `deepcopy`。

---

# 十九、文档

更新或新增：

```text
docs/execution_prepared_transaction.md
docs/execution_projection_contract.md
docs/execution_transaction_store.md
docs/adr/xxxx-prepared-execution-transaction.md
```

文档必须说明：

## 当前已完成

```text
Prepared Transaction Domain
Projection Contract
Store Assigned Sequence
Memory/SQLite Durable Transaction
Projection Ready Gate
Projection Idempotency Contract
```

## 当前未完成

```text
ExecutionProcessor 主链切换
具体 Manager Pure Reducer
具体 Manager Projection Target
Full Replay Recovery
Non-Trade Durable Facts
Exactly-Once Delivery
```

不得声称本任务已经解决完整 Manager-before-Journal 问题。

本任务解决的是其正式数据模型、持久契约和幂等接口基础。

---

# 二十、工程门禁

至少运行：

```bash
uv lock --check
uv sync --frozen --all-packages --all-groups

uv run ruff check src tests examples packages
uv run ruff format --check src tests examples packages

uv run mypy src/onlyalpha

uv run pytest tests/execution -q
uv run pytest tests/architecture -q
uv run pytest tests/integration -q

uv run pytest tests -q \
  -m "not external and not requires_network and not requires_tushare and not requires_local_qmt"
```

同时执行：

```bash
uv run pytest packages/fake/onlyalpha-plugin-broker-virtual/tests -q

uv run pytest packages/provider/onlyalpha-plugin-tushare/tests -q \
  -m "not external and not requires_network and not requires_tushare"

uv run pytest packages/provider/onlyalpha-plugin-miniqmt/tests -q \
  -m "not external and not requires_network and not requires_local_qmt"
```

检查：

* Build wheel；
* Build sdist；
* Twine check；
* Clean install；
* Entry Point smoke；
* Scenario tests；
* Conformance tests；
* Product integration tests。

不得使用：

```text
skip
xfail
sleep
宽松断言
平台绕过
测试专用 Production 分支
```

真实外部服务无法执行时必须明确标记未执行。

---

# 二十一、验收标准

任务只有满足以下条件才算完成。

## Prepared Transaction

* 不包含最终 Sequence；
* 不持有 Manager、Runtime、EventBus 或 Callable；
* 完整保存 Fact Draft、Projection、Event 和 Preconditions；
* 稳定序列化；
* 稳定 Hash；
* Round-Trip 无损。

## Projection

* 强类型；
* 顺序明确；
* Payload 可重放；
* Version 明确；
* Hash 明确；
* 不使用松散 Dictionary Payload。

## Store

* Sequence 在 Commit 内分配；
* Memory 与 SQLite 契约一致；
* Transaction、Fact、Projection、Outbox 原子持久化；
* 幂等冲突严格检测；
* Projection Ready 前 Outbox 不可交付；
* SQLite 重启可恢复全部 Payload。

## Projection Contract

* Manager Target 接口整洁；
* 相同 Sequence 和 Hash 幂等；
* 不同 Hash 冲突；
* Version 不一致冲突；
* Projection Applier 不承担 Event Delivery。

## 清理

* 删除新体系中的 `next_sequence()`；
* 删除旧提交契约；
* 删除 Alias 和 Compatibility Wrapper；
* 旧测试迁移到新接口；
* 不为示例保留错误接口；
* 导出和文档与新架构一致。

---

# 二十二、最终交付报告

完成后输出：

## 1. 修改前问题

说明当前 Sequence、Commit、Projection 和恢复边界的问题。

## 2. 新领域模型

列出：

```text
Prepared Transaction
Fact Draft
Projection Union
Committed Transaction
Precondition
Projection Result
```

## 3. 新 Store 契约

说明：

```text
Store Assigned Sequence
Atomic Transaction
Idempotency
Projection Ready Gate
Outbox Visibility
```

## 4. 幂等语义

说明：

```text
APPLIED
IDEMPOTENT
VERSION_CONFLICT
PAYLOAD_CONFLICT
```

## 5. 删除内容

列出删除的旧 API、兼容层、旧测试和旧导出。

## 6. 测试结果

提供真实命令、测试数量和结果。

## 7. 下一阶段

明确下一步是：

```text
Trade Pure Reducers
→ Transaction Planner
→ Commit Coordinator
→ Manager Projection Targets
→ ExecutionProcessor 主链切换
→ Full Replay Recovery
```

不得把下一阶段描述为本任务已完成。

---

# 最终目标

本任务完成后，OnlyAlpha 必须具备清晰的成交事务基础：

```text
Immutable Broker Input
→ Pure Prepared Transaction
→ Store Assigned Sequence
→ Durable Committed Transaction
→ Ordered Idempotent Projections
→ Projection Ready Gate
→ Durable Outbox
```

所有接口必须职责单一、强类型、可序列化、可审计、可重放。

优先保证正确的事务权威、接口隔离和恢复基础，不要为了减少改动、保留旧测试或维持旧示例而继续维护错误边界。
