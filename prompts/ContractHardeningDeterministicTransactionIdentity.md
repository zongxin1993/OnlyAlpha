# OnlyAlpha PR1：收紧 Prepared Execution Transaction Contract 与确定性事务身份

## 一、任务目标

以当前 OnlyAlpha `master` 源码、测试和已接受 ADR 为唯一事实源，完成 Prepared Execution Transaction 的第一轮正式收紧。

本任务必须解决以下根本问题：

````text
相同 Broker Trade Update
+ 相同业务 Before State
→ 相同 Transaction Identity
→ 相同 Authority Payload
→ 相同 Authority Hash
→ 相同 Durable Event Identity
 Payload
→ 相同 Authority Hash
→ 相同 Durable Event```

当前 Prepared Transaction、Projection Contract、Memory/SQLite Transaction Store、Projection Ready Gate 和参考幂等状态已经存在，但尚未接入真实 ExecutionProcessor 主链。

本 PR 不负责切换 ExecutionProcessor，不实现真实 Manager Reducer，不实现完整 Recovery。

本 PR 的目标是：

1. 分离业务权威哈希与完整载荷哈希；
2. 建立确定性的 Transaction ID；
3. 建立确定性的 Durable Execution Event ID；
4. 明确 `prepared_at` 的审计语义；
5. 修正无法无损重放的 Projection Payload；
6. 拆分语义错误的统一 Reservation Projection；
7. 强化 Preconditions 与 Projections 的对应关系；
8. 重建独立、完整的新事务测试夹具；
9. 增加完整 Projection Codec、Store 和故障契约测试；
10. 删除本次新体系中被替代的错误接口，不保留兼容层。

目标流程：

```text
Immutable Business Authority
→ Deterministic Transaction Identity
→ Deterministic Durable Events
→ Strongly Typed Replayable Projections
→ Canonical Authority Hash
→ Canonical Payload Hash
→ Atomic Transaction Store
````

---

# 二、基本原则

## 2.1 从业务权威出发，而不是从当前代码结构出发

首先回答：

> 在不同进程、不同机器、不同处理时间中，什么条件表示“这是同一笔成交事务”？

相同事务必须由业务身份决定，不得由以下内容决定：

* 系统当前时间；
* Python 对象实例；
* 随机 UUID；
* 当前进程内 Processing Sequence；
* Manager 对象地址；
* 字典遍历顺序；
* 测试 Fixture 顺序；
* Store 分配的 Execution Sequence；
* Outbox Attempt 状态。

## 2.2 业务幂等与数据完整性是两个不同问题

不得继续让一个 `stable_hash` 同时承担：

* 业务幂等判断；
* Canonical Payload 完整性校验；
* SQLite 数据损坏检测；
* 序列化一致性验证。

必须拆分为两个清晰概念：

```text
authority_hash
payload_hash
```

### `authority_hash`

表示：

> 这笔事务在业务上是什么。

用于：

* Transaction ID、Trade ID、Update ID 幂等；
* Store 冲突判断；
* 重放一致性；
* 相同业务输入确定性验证。

### `payload_hash`

表示：

> 当前完整序列化载荷是否被修改。

用于：

* Canonical Codec 完整性；
* SQLite 损坏检测；
* Round-Trip 校验；
* 存储内容审计。

## 2.3 Durable Event ID 必须确定性

持久化 Execution Event 不得使用随机 UUID4。

相同事务中的相同事件必须始终得到相同 Event ID。

## 2.4 Projection 必须可以独立重放

Projection 不是审计说明，不是日志文本。

Projection 必须包含足够数据，使未来 Runtime 在没有以下对象的情况下重建状态：

* Broker SDK 对象；
* 原始 Manager；
* 进程内临时对象；
* Callable；
* Closure；
* 当前 Runtime 隐式状态。

## 2.5 不兼容旧错误接口

不要为了：

* 旧测试；
* 示例；
* Mock；
* Fixture；
* 历史 Prompt；
* 旧导出；
* 减少改动；

保留错误接口。

删除旧接口后，直接修改所有调用方、测试、示例、文档和公共导出。

禁止增加：

```text
Deprecated Alias
Compatibility Wrapper
Legacy Adapter
旧字段 Property Alias
双写
无期限过渡接口
```

---

# 三、实施前审计

开始修改前执行：

```bash
git status
git log -n 10 --oneline
git rev-parse HEAD

rg "OnlyPreparedExecutionTransaction"
rg "stable_hash"
rg "prepared_hash"
rg "committed_hash"
rg "payload_hash"
rg "prepared_at"
rg "OnlyEventId.new"
rg "uuid4"
rg "outbox_events"
rg "OnlyExecutionPrecondition"
rg "OnlySettlementExecutionProjection"
rg "OnlyFeeExecutionProjection"
rg "OnlyReservationExecutionProjection"
rg "OnlyRiskExecutionProjection"
rg "OnlyExecutionTransactionStore"
rg "OnlyInMemoryExecutionTransactionStore"
rg "OnlySqliteExecutionTransactionStore"
rg "test_prepared_execution_transaction"
rg "test_execution_projection_contract"
rg "test_committed_execution_journal"
rg "test_execution_outbox"
```

形成简短审计记录，至少说明：

1. 当前 Prepared Transaction Hash 覆盖哪些字段；
2. 当前 `prepared_at` 是否进入 Hash；
3. 当前 Outbox Event ID 如何生成；
4. 当前 Store 用哪个 Hash 做幂等判断；
5. 当前 SQLite 用哪个 Hash 做损坏检测；
6. 哪些 Projection 仍保存字符串而非可重放 DTO；
7. 当前 Reservation Projection 是否错误混合 Money 与 Quantity；
8. Preconditions 与 Projections 当前如何关联；
9. 新测试是否依赖 Legacy Journal 测试 Fixture；
10. 当前 Public API 是否同时暴露被本 PR 替换的新体系接口。

不得只根据历史 Prompt 推断当前实现，必须读取当前源码。

---

# 四、任务范围

## 4.1 本 PR 必须完成

```text
Authority Hash / Payload Hash 分离
Deterministic Transaction ID
Deterministic Durable Event ID
Prepared Time 语义收紧
Strongly Typed Settlement Projection
Strongly Typed Fee Projection
Reservation Projection 分型
Risk Projection 可重放性收紧
Projection / Precondition 一一对应
Canonical Codec 更新
Memory / SQLite Store 更新
独立完整 Transaction Fixture
完整 Projection Round-Trip 测试
Store Contract 测试
损坏检测测试
架构边界测试
文档和 ADR 更新
旧接口删除
```

## 4.2 本 PR 不包含

```text
ExecutionProcessor 主链切换
Trade Transaction Planner
真实业务 Pure Reducer
真实 Manager Projection Target
Execution Commit Coordinator
Runtime Transaction Store 装配
Full Replay Recovery
Non-Trade Durable Facts
Paper Runtime
Live Runtime
Exactly-Once Delivery
```

不得在本 PR 中部分实现这些功能，形成新的半成品边界。

---

# 五、拆分 Authority Hash 与 Payload Hash

## 5.1 Prepared Transaction 模型调整

将当前单一：

```python
stable_hash: str
```

替换为职责明确的字段：

```python
@dataclass(frozen=True, slots=True)
class OnlyPreparedExecutionTransaction:
    schema_version: ClassVar[int]

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

    authority_hash: str = ""
    payload_hash: str = ""
```

具体字段顺序可根据当前代码风格调整，但语义不得改变。

删除：

```text
stable_hash
prepared_hash
```

中表达不清晰的旧语义。

如果 Committed Transaction 仍需保存 Prepared Authority，应使用明确名称：

```python
prepared_authority_hash: str
prepared_payload_hash: str
```

不要保留模糊的 `prepared_hash`。

## 5.2 Authority Payload

建立唯一公共函数：

```python
def only_execution_transaction_authority_payload(
    prepared: OnlyPreparedExecutionTransaction,
) -> Mapping[str, object]:
    ...
```

Authority Payload 必须覆盖：

```text
Schema Version
Transaction ID
Runtime ID
Gateway ID
Account ID
Broker Update ID
Trade ID
Source Sequence
Fact Draft 的业务权威字段
Ordered Projection Payload
Projection Identity
Preconditions
Outbox Event 的业务语义
```

Authority Payload 不得覆盖：

```text
prepared_at
committed_at
execution_sequence
projection_ready
projected_at
projection_error
projection_failed_at
attempt_count
last_attempted_at
published
published_at
last_error
```

## 5.3 Event 在 Authority Payload 中的表达

Authority Hash 必须覆盖 Event 的业务语义，但不能因为 Event 封装审计时间变化而改变业务身份。

建议使用明确的 Event Authority DTO：

```python
@dataclass(frozen=True, slots=True)
class OnlyExecutionEventAuthority:
    event_sequence: int
    event_type: OnlyEventType
    source: OnlyEventSource
    runtime_id: OnlyRuntimeId
    cluster_id: OnlyClusterId | None
    payload: object
    correlation_id: OnlyCorrelationId | None
    causation_id: OnlyCausationId | None
    priority: OnlyEventPriority
```

Authority Hash 中应包含确定性 Event ID，或包含足以确定性推导 Event ID 的字段。

不要直接把所有 Event Envelope 审计字段无差别塞入 Authority Hash。

## 5.4 Payload Hash

Payload Hash 必须覆盖完整 Canonical Prepared Payload，包括：

```text
prepared_at
authority_hash
完整 Event Envelope
Event ID
Event Timestamp
Event Init Timestamp
Metadata
Preconditions
完整 Projection
```

Payload Hash 本身不得递归包含自身。

实现：

```python
def only_prepared_execution_transaction_authority_hash(
    prepared: OnlyPreparedExecutionTransaction,
    *,
    verify: bool = True,
) -> str:
    ...
```

```python
def only_prepared_execution_transaction_payload_hash(
    prepared: OnlyPreparedExecutionTransaction,
    *,
    verify: bool = True,
) -> str:
    ...
```

删除或替换当前含义模糊的：

```text
only_prepared_execution_transaction_hash
stable_hash
prepared_hash
```

不保留兼容别名。

## 5.5 Committed Hash

Committed Transaction 需要明确区分：

```text
prepared_authority_hash
prepared_payload_hash
committed_payload_hash
```

`committed_payload_hash` 覆盖完整 Committed Payload，但不包含自身。

不得把 Projection Ready 状态变化当成原始成交 Authority 变化。

如果 Ready 状态变化需要重新计算完整 Committed Payload Hash，可以重新计算 `committed_payload_hash`，但原始：

```text
prepared_authority_hash
```

必须保持不变。

---

# 六、确定性 Transaction ID

## 6.1 建立唯一工厂

实现：

```python
def only_execution_transaction_id(
    *,
    runtime_id: OnlyRuntimeId,
    gateway_id: OnlyBrokerGatewayId,
    account_id: OnlyAccountId,
    broker_update_id: OnlyBrokerUpdateId,
    trade_id: OnlyTradeId,
) -> str:
    ...
```

建议输出：

```text
ETX-<lowercase sha256>
```

或者使用固定 Namespace 的 UUID5。

项目中只能有一个正式生成算法。

## 6.2 Transaction ID 权威字段

Transaction ID 必须由以下字段确定：

```text
runtime_id
gateway_id
account_id
broker_update_id
trade_id
transaction identity schema version
```

不得包含：

```text
prepared_at
processing_sequence
source_sequence 之外的本地计数器
manager version
execution_sequence
随机数
系统时间
```

`source_sequence` 是否进入 Transaction ID，需要根据当前 Broker Update ID 契约判断。

如果 `broker_update_id` 已经是 Gateway Scope 内稳定唯一 ID，则 Transaction ID 不需要额外加入 `source_sequence`。

必须在 ADR 中记录最终选择。

## 6.3 Prepared Transaction 构造校验

`OnlyPreparedExecutionTransaction.__post_init__()` 必须验证：

```text
transaction_id
=
only_execution_transaction_id(...)
```

调用方不得随意传入任意字符串。

如果希望避免重复计算，可以提供：

```python
@classmethod
def create(...)
```

但最终模型仍必须验证身份一致。

## 6.4 冲突语义

相同：

```text
transaction_id
trade key
update key
```

且相同 `authority_hash`：

```text
→ 幂等返回原 Transaction
```

相同任一业务幂等键但不同 `authority_hash`：

```text
→ OnlyExecutionTransactionConflict
```

`payload_hash` 不同但 `authority_hash` 相同的处理必须明确。

推荐：

```text
相同 Authority
+ 不同 Prepared Audit Envelope
→ 返回原已提交 Transaction
```

因为 Store 的幂等权威是业务 Authority，而不是本次重试时重新生成的审计封装。

不得因为 `prepared_at` 不同把同一交易判为业务冲突。

---

# 七、确定性 Durable Event ID

## 7.1 新增 Durable Event Identity 工厂

实现：

```python
def only_execution_transaction_event_id(
    *,
    transaction_id: str,
    event_sequence: int,
    event_type: OnlyEventType,
) -> OnlyEventId:
    ...
```

使用固定 Namespace UUID5 或固定 SHA-256 映射。

必须满足：

```text
相同 transaction_id
+ 相同 event_sequence
+ 相同 event_type
→ 相同 Event ID
```

## 7.2 新增 Event Factory

实现：

```python
class OnlyExecutionTransactionEventFactory:
    def create(
        self,
        *,
        transaction_id: str,
        event_sequence: int,
        event_type: OnlyEventType,
        timestamp: datetime,
        engine_id: OnlyEngineId,
        runtime_id: OnlyRuntimeId,
        source: OnlyEventSource,
        payload: object,
        cluster_id: OnlyClusterId | None = None,
        metadata: Mapping[str, str] = ...,
        ts_init: datetime | None = None,
        correlation_id: OnlyCorrelationId | None = None,
        causation_id: OnlyCausationId | None = None,
        priority: OnlyEventPriority = OnlyEventPriority.NORMAL,
    ) -> OnlyEvent:
        ...
```

Factory 必须显式安装确定性 Event ID。

## 7.3 Prepared Transaction Event 校验

Prepared Transaction 必须验证：

```text
outbox_events 中第 N 个 Event 的 event_id
=
only_execution_transaction_event_id(
    transaction_id,
    N,
    event_type,
)
```

同时验证：

* Event Runtime Scope 与 Transaction 一致；
* Event Sequence 连续；
* Event 顺序确定；
* Event ID 不重复；
* Event Type 不为空；
* Event Payload 可 Canonical 编码。

## 7.4 禁止的行为

在新 Prepared Transaction 和测试 Fixture 中禁止：

```python
OnlyEventId.new()
uuid4()
default_factory=OnlyEventId.new
```

普通非持久 Event 可以继续使用随机 ID，但 Durable Execution Event 必须通过专用 Factory 创建。

架构测试应验证 Transaction Fixture 和新事务构造路径没有调用随机 Event ID。

---

# 八、`prepared_at` 语义

保留 `prepared_at` 作为审计字段，语义为：

> Runtime 完成 Prepared Transaction 计算的时间。

要求：

* 必须为 UTC；
* 不得早于 Broker Update `ts_event`；
* 不得进入 `authority_hash`；
* 必须进入 `payload_hash`；
* 不得被伪装成 Broker Event Time；
* 不得用于 Transaction ID；
* 不得用于 Durable Event ID。

添加测试：

```text
相同 Authority
+ 不同 prepared_at
→ authority_hash 相同
→ payload_hash 不同
```

---

# 九、Projection Payload 强类型收紧

## 9.1 总原则

Projection 必须描述真实可应用状态变化。

禁止核心恢复字段继续使用：

```text
str
tuple[str, ...]
dict[str, object]
object
Any
```

如果当前领域对象无法安全复用，应创建不可变 Replay DTO。

不得为了少改代码保留无法恢复的字符串 Payload。

---

## 9.2 Settlement Projection

删除当前类似：

```python
instruction: str
before_state: str
after_state: str
generated_records: tuple[str, ...]
```

改为强类型 DTO。

建议：

```python
@dataclass(frozen=True, slots=True)
class OnlySettlementProjectionState:
    instruction_id: str
    account_id: str
    instrument_id: str
    source_order_id: str
    source_trade_id: str

    asset_quantity: Decimal
    cash_amount: Decimal

    asset_released: bool
    trade_cash_released: bool
    withdrawable_cash_released: bool
    legal_settled: bool

    asset_available_on: OnlyTradingDay
    cash_trade_available_on: OnlyTradingDay
    cash_withdrawable_on: OnlyTradingDay
    legal_settlement_on: OnlyTradingDay
```

```python
@dataclass(frozen=True, slots=True)
class OnlySettlementExecutionProjection:
    identity: OnlyExecutionProjectionIdentity
    instruction: OnlySettlementRuntimeInstruction
    before: OnlySettlementProjectionState | None
    after: OnlySettlementProjectionState
    records: tuple[OnlySettlementRecord, ...]
```

如果当前 `OnlySettlementRuntimeInstruction` 和 `OnlySettlementRecord` 已是不可变、可稳定序列化领域 DTO，可直接复用。

否则创建专用 Replay DTO。

Projection 必须足以重建：

* Pending Settlement；
* Availability State；
* Legal Settlement State；
* Settlement Records。

---

## 9.3 Fee Projection

删除当前类似：

```python
fee_instruction: str
fee_records: tuple[str, ...]
```

改为：

```python
@dataclass(frozen=True, slots=True)
class OnlyFeeExecutionProjection:
    identity: OnlyExecutionProjectionIdentity
    instruction: OnlyFeeInstruction
    records: tuple[OnlyFeeRecord, ...]
    authoritative_total: OnlyMoney
    fee_breakdown: OnlyFeeBreakdown
```

要求：

* Instruction 与 Records Scope 一致；
* Records 总额与 Breakdown 一致；
* Breakdown Total 与 `authoritative_total` 一致；
* Currency 一致；
* Trade ID、Order ID、Account ID 一致；
* Codec 可无损 Round-Trip。

不得只保存 Fee Record ID。

---

## 9.4 Reservation Projection 分型

删除统一的：

```text
OnlyReservationExecutionProjection
OnlyExecutionReservationKind
```

除非其仅作为 Union Alias，而不是包含统一 Money Payload 的实体。

建立明确类型：

```python
OnlyExecutionReservationProjection = (
    OnlyCashReservationExecutionProjection
    | OnlyPositionReservationExecutionProjection
    | OnlyMarginReservationExecutionProjection
    | OnlyRiskReservationExecutionProjection
)
```

### Cash Reservation

```python
@dataclass(frozen=True, slots=True)
class OnlyCashReservationExecutionProjection:
    identity: OnlyExecutionProjectionIdentity
    reservation_id: str
    owner_scope: str
    currency: OnlyCurrency
    before: OnlyMoney
    consumed_delta: OnlyMoney
    released_delta: OnlyMoney
    after: OnlyMoney
    before_status: OnlyReservationStatus
    after_status: OnlyReservationStatus
```

### Position Reservation

```python
@dataclass(frozen=True, slots=True)
class OnlyPositionReservationExecutionProjection:
    identity: OnlyExecutionProjectionIdentity
    reservation_id: str
    order_id: OnlyOrderId
    instrument_id: OnlyInstrumentId
    before: OnlyQuantity
    consumed_delta: OnlyQuantity
    released_delta: OnlyQuantity
    after: OnlyQuantity
    before_status: OnlyReservationStatus
    after_status: OnlyReservationStatus
```

### Margin Reservation

```python
@dataclass(frozen=True, slots=True)
class OnlyMarginReservationExecutionProjection:
    identity: OnlyExecutionProjectionIdentity
    reservation_id: str
    account_id: OnlyAccountId
    instrument_id: OnlyInstrumentId
    currency: OnlyCurrency

    reserved_before: OnlyMoney
    reserved_after: OnlyMoney
    occupied_before: OnlyMoney
    occupied_after: OnlyMoney
    released_delta: OnlyMoney
    maintenance_before: OnlyMoney
    maintenance_after: OnlyMoney
```

### Risk Reservation

```python
@dataclass(frozen=True, slots=True)
class OnlyRiskReservationExecutionProjection:
    identity: OnlyExecutionProjectionIdentity
    reservation_id: str
    cluster_id: OnlyClusterId
    account_id: OnlyAccountId
    instrument_id: OnlyInstrumentId
    order_id: OnlyOrderId

    quantity_before: OnlyQuantity
    quantity_after: OnlyQuantity

    notional_before: OnlyMoney
    notional_after: OnlyMoney

    consumed_quantity_delta: OnlyQuantity
    consumed_notional_delta: OnlyMoney

    before_status: OnlyRiskReservationStatus
    after_status: OnlyRiskReservationStatus
```

具体字段应与当前领域 Manager 真正拥有的状态一致，不得凭空制造无用字段。

---

## 9.5 Risk Projection

当前 Risk Projection 仍以：

```text
reservation_state_before: str
reservation_state_after: str
```

表达状态。

改为明确 Enum 或不可变 Snapshot DTO。

Risk Projection 必须足以恢复：

* Cluster Scope；
* Account Scope；
* Instrument Scope；
* Order Scope；
* Quantity Exposure；
* Notional Exposure；
* Reservation Status；
* Consumed Exposure；
* Remaining Exposure。

如果 Risk Reservation 已由专门 Projection 表达，则普通 `OnlyRiskExecutionProjection` 只保存 Post-Trade Risk State，不得重复保存同一 Authority。

避免：

```text
Risk Projection
+
Risk Reservation Projection
```

对同一字段双写。

---

# 十、Projection Union 与固定顺序

更新正式 Projection Union：

```python
type OnlyExecutionProjection = (
    OnlyOrderExecutionProjection
    | OnlyPositionExecutionProjection
    | OnlyAllocationExecutionProjection
    | OnlySettlementExecutionProjection
    | OnlyMarginExecutionProjection
    | OnlyFeeExecutionProjection
    | OnlyAccountExecutionProjection
    | OnlyStrategyLedgerExecutionProjection
    | OnlyCashReservationExecutionProjection
    | OnlyPositionReservationExecutionProjection
    | OnlyMarginReservationExecutionProjection
    | OnlyRiskReservationExecutionProjection
    | OnlyRiskExecutionProjection
    | OnlyValuationExecutionProjection
)
```

需要重新评估固定 Component 枚举。

如果 Reservation 已拆分，不要通过一个粗粒度：

```text
RESERVATION
```

隐藏多个独立 Projection 顺序。

建议固定顺序调整为：

```text
ORDER
POSITION
ALLOCATION
SETTLEMENT
MARGIN
FEE
ACCOUNT
STRATEGY_LEDGER
ACCOUNT_CASH_RESERVATION
STRATEGY_CASH_RESERVATION
POSITION_RESERVATION
MARGIN_RESERVATION
RISK_RESERVATION
RISK
VALUATION
```

具体顺序必须由当前 Trade 会计依赖决定，并写入 ADR。

禁止依赖类名、字符串字典序或导入顺序。

---

# 十一、Precondition 与 Projection 一一对应

## 11.1 构造校验

Prepared Transaction 必须验证：

```text
每个 Projection 恰好有一个 Precondition
每个 Precondition 恰好对应一个 Projection
```

匹配键：

```text
(component, entity_key)
```

并验证：

```text
precondition.expected_version
=
projection.identity.expected_version
```

如果 Precondition 包含：

```text
expected_state_hash
```

必须验证其格式为小写 SHA-256。

## 11.2 禁止情况

必须拒绝：

* 缺失 Precondition；
* 多余 Precondition；
* 重复 Precondition；
* Component 不一致；
* Entity Key 不一致；
* Expected Version 不一致；
* 空 State Hash；
* 大写或非法 SHA-256；
* Projection 无状态权威但声明虚假 Precondition。

## 11.3 顺序

Preconditions 的 Canonical 编码必须按照 Projection 顺序排列。

不要依赖调用方传入的任意顺序。

可以在构造时要求顺序一致，或在 Codec 中规范化，但必须只有一种权威行为。

---

# 十二、Codec 更新

## 12.1 Canonical 编码

更新 Codec 支持：

* 新 Hash 字段；
* 新 Transaction ID 校验；
* 确定性 Event ID；
* 新 Projection 类型；
* 强类型 Settlement DTO；
* 强类型 Fee DTO；
* Reservation Projection Union；
* Risk 状态 DTO；
* Preconditions 对应关系；
* Schema Version。

## 12.2 禁止编码方式

不得使用：

```text
pickle
repr
float(Decimal)
默认 Python UUID repr
默认 datetime str
未排序 Mapping
依赖 dataclasses.asdict 的隐式行为
```

要求：

* Decimal 使用字符串；
* Timestamp 使用 Unix Nanoseconds；
* Enum 使用 `.value`；
* Identifier 使用规范字符串；
* Tuple 保持顺序；
* Mapping 排序；
* UUID 使用规范小写字符串；
* Projection 使用显式 Type Envelope。

## 12.3 Schema Version

由于 Payload Contract 已发生不兼容变化，提升 Transaction Schema Version。

例如：

```python
schema_version = 2
```

不兼容旧 Schema，不提供自动迁移。

读取旧 Schema 时必须明确拒绝：

```text
unsupported execution transaction schema version
```

不要默默补字段或推断旧语义。

---

# 十三、Store Contract 更新

## 13.1 幂等权威

Memory 和 SQLite Store 必须以：

```text
authority_hash
```

判断业务幂等。

不得继续以完整 Payload Hash 判断业务冲突。

规则：

```text
相同幂等键 + 相同 authority_hash
→ inserted=False，返回原 Transaction

相同幂等键 + 不同 authority_hash
→ OnlyExecutionTransactionConflict
```

## 13.2 Payload 完整性

Store 必须保存并验证：

```text
prepared_payload
prepared_payload_hash
prepared_authority_hash
committed_payload
committed_payload_hash
```

SQLite 读取时：

1. 重新计算 Prepared Payload Hash；
2. 验证 Prepared Authority Hash；
3. Decode Prepared Transaction；
4. 验证 Committed Payload Hash；
5. Decode Committed Transaction；
6. 验证 Prepared 与 Committed Authority 一致。

## 13.3 SQLite Schema

直接修改 Schema，不考虑旧数据库兼容。

建议字段：

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
prepared_authority_hash
prepared_payload_hash

committed_payload
committed_payload_hash

committed_at

projection_ready
projected_at
projection_error
projection_failed_at
```

Outbox 保持：

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

增加必要唯一约束：

```text
PRIMARY KEY(runtime_id, execution_sequence)
UNIQUE(transaction_id)
UNIQUE(runtime_id, gateway_id, account_id, trade_id)
UNIQUE(runtime_id, gateway_id, account_id, broker_update_id)
UNIQUE(event_id)
```

如果跨 Runtime 允许相同 Event ID，则重新评估最后一项；Durable Event ID 算法正常情况下应全局唯一。

## 13.4 Memory Store 原子性

当前 Memory Store 在字典中逐步写入。

必须保证 Commit 中任意步骤失败时：

```text
_records 不变
_by_transaction 不变
_by_trade 不变
_by_update 不变
_outbox 不变
sequence head 不变
```

不要先修改正式集合再验证剩余步骤。

推荐：

```text
在局部变量中完成：
Sequence 分配
Transaction Finalize
Codec Round-Trip
所有 Index Key
所有 Outbox Record
冲突检查

全部成功后：
一次性更新正式集合
```

增加故障注入测试证明内存 Store 不产生部分写入。

---

# 十四、独立测试 Fixture Factory

新 Prepared Transaction 测试不得继续从 Legacy 测试导入：

```text
tests.execution.test_committed_execution_journal._fact
tests.execution.test_execution_outbox._events
```

新增独立 Factory，例如：

```text
tests/execution/factories/transaction_factory.py
```

或符合当前测试目录结构的等价位置。

提供：

```python
only_test_execution_fact_draft()
only_test_execution_projections()
only_test_execution_preconditions()
only_test_execution_events()
only_test_prepared_execution_transaction()
```

Fixture Factory 必须：

* 不依赖 Legacy Journal；
* 不依赖 Legacy Outbox；
* 不依赖 Runtime Manager；
* 不使用随机 UUID；
* 生成完整确定性数据；
* 支持按字段覆盖；
* 支持 Memory/SQLite Contract Test 复用。

不要把测试 Factory 放入生产包。

---

# 十五、完整 Projection 测试事务

建立至少一个包含完整合法 Projection 序列的 Prepared Transaction。

该事务应覆盖当前全部正式 Projection 类型，而不是只构造 Settlement Projection。

测试必须验证：

```text
完整 Projection Tuple
→ Prepared Encode
→ Prepared Decode
→ 完全相等
```

```text
Prepared
→ Store Commit
→ Committed Encode
→ Committed Decode
→ 完全相等
```

```text
SQLite Close
→ Reopen
→ 完整 Transaction 相等
```

每种 Projection 至少验证：

* Component；
* Entity Key；
* Expected Version；
* Result Version；
* Projection Sequence；
* Payload Hash；
* Currency；
* Quantity Precision；
* Timestamp；
* Identifier；
* Enum；
* Nested DTO；
* Round-Trip。

---

# 十六、测试要求

## 16.1 Identity Tests

覆盖：

1. 相同业务字段生成相同 Transaction ID；
2. Runtime 不同生成不同 ID；
3. Gateway 不同生成不同 ID；
4. Account 不同生成不同 ID；
5. Update ID 不同生成不同 ID；
6. Trade ID 不同生成不同 ID；
7. 任意 Transaction ID 被模型拒绝；
8. Transaction ID 不受 `prepared_at` 影响；
9. Transaction ID 不受 Store Sequence 影响。

## 16.2 Event Identity Tests

覆盖：

1. 相同 Transaction/Event Sequence/Event Type 生成相同 Event ID；
2. Event Sequence 不同生成不同 ID；
3. Event Type 不同生成不同 ID；
4. Transaction ID 不同生成不同 ID；
5. Prepared Transaction 拒绝随机 Event ID；
6. Codec Round-Trip 保持 Event ID；
7. SQLite 重启保持 Event ID；
8. Retry 不重新生成 Event ID。

## 16.3 Hash Tests

覆盖：

### Authority Hash 不变

仅改变：

```text
prepared_at
```

Authority Hash 不变。

### Payload Hash 变化

改变：

```text
prepared_at
```

Payload Hash 必须变化。

### Authority Hash 变化

改变任一业务权威字段：

```text
Fact Draft
Projection Payload
Projection Order
Precondition
Event Type
Event Payload
Trade ID
Update ID
```

Authority Hash 必须变化。

### Hash 损坏

手工修改：

* Prepared Payload；
* Prepared Authority Hash；
* Prepared Payload Hash；
* Committed Payload；
* Committed Payload Hash；
* Event Payload；
* Event ID；

读取必须失败。

## 16.4 Projection Validation Tests

覆盖：

* Settlement Scope 冲突；
* Settlement Before/After 非法；
* Fee Total 不一致；
* Fee Currency 不一致；
* Cash Reservation 负数；
* Position Reservation Quantity 非法；
* Margin Reservation 状态非法；
* Risk Reservation Scope 冲突；
* Risk Exposure Currency 不一致；
* Projection Component 错误；
* Projection Sequence 不连续；
* Projection 固定顺序错误；
* 重复 Component/Entity；
* Payload Hash 错误。

## 16.5 Precondition Tests

覆盖：

* 每个 Projection 都有匹配 Precondition；
* 缺失；
* 多余；
* 重复；
* Expected Version 不一致；
* Entity Key 不一致；
* Component 不一致；
* State Hash 非法；
* 顺序不一致。

## 16.6 Store Contract Tests

Memory 和 SQLite 必须运行同一套 Contract Tests：

1. 自动分配连续 Sequence；
2. 相同 Authority 幂等；
3. 相同 Transaction ID 不同 Authority 冲突；
4. 相同 Trade Key 不同 Authority 冲突；
5. 相同 Update Key 不同 Authority 冲突；
6. 相同 Authority、不同 Prepared Time 返回原事务；
7. Projection Ready 前 Outbox 不可见；
8. Ready 后 Outbox 可见；
9. Event ID 保持；
10. Published Record 保留；
11. Attempt Count 正确；
12. Failure 后可重试；
13. SQLite 重启完整恢复；
14. Payload 损坏检测；
15. Authority 损坏检测；
16. Event Payload 损坏检测；
17. Transaction 顺序稳定；
18. Memory Commit 故障无部分写入；
19. SQLite Commit 故障完整回滚。

## 16.7 Architecture Tests

增加 AST 或等价测试，验证：

* Transaction Identity 模块不 import Runtime；
* Transaction Identity 模块不 import Manager；
* Event Identity Factory 不 import EventBus；
* Projection 模型不 import Manager；
* Codec 不 import Manager；
* Store 不 import Manager；
* 新 Transaction Fixture 不 import Legacy Journal 测试；
* 新 Transaction Fixture 不 import Legacy Outbox 测试；
* 新事务路径不使用 `uuid4`；
* 新事务路径不调用 `OnlyEventId.new()`；
* 新核心 Projection 不包含 `Any`；
* 新核心 Projection 不包含 `dict[str, object]` 作为恢复权威；
* 新 Settlement Projection 不使用字符串 Instruction；
* 新 Fee Projection 不使用字符串 Record；
* 不存在被删除的旧 Hash 字段；
* 不存在兼容 Alias。

---

# 十七、删除和迁移

删除：

```text
OnlyPreparedExecutionTransaction.stable_hash
OnlyCommittedExecutionTransaction.prepared_hash
only_prepared_execution_transaction_hash
旧 OnlyReservationExecutionProjection
旧 OnlyExecutionReservationKind
旧字符串 Settlement Projection 字段
旧字符串 Fee Projection 字段
依赖 Legacy Journal Fixture 的新测试
依赖 Legacy Outbox Fixture 的新测试
旧 Re-export
兼容 Property
兼容 Wrapper
```

根据新模型更新：

* `src/onlyalpha/execution/__init__.py`
* Codec；
* Transaction Store；
* Projection Applier 类型；
* Tests；
* Docs；
* ADR；
* Prompt 中仍被当前文档引用的接口名称；
* 所有导入方。

不要删除当前 ExecutionProcessor 使用的 Legacy Journal，除非本 PR 的改动已经使其完全无引用。

本 PR 不负责 Processor 切换，因此不要误删现有产品主链仍然依赖的 Legacy Runtime 组件。

但新 Prepared Transaction 体系内部不得继续暴露本 PR 已替换的错误接口。

---

# 十八、文档和 ADR

更新或新增：

```text
docs/execution_prepared_transaction.md
docs/execution_projection_contract.md
docs/execution_transaction_store.md
docs/adr/0035-prepared-execution-transaction-and-projection-contract.md
```

也可以新增独立 ADR，若当前 ADR 0035 应保持原始决策历史。

文档必须明确说明：

## Authority Hash

```text
用于业务幂等和冲突判断
不包含 prepared_at 和 Store 状态
```

## Payload Hash

```text
用于完整序列化载荷校验
包含 prepared_at 和完整 Event Envelope
```

## Durable Event ID

```text
由 Transaction ID、Event Sequence 和 Event Type 确定性推导
```

## Projection Payload

```text
必须是强类型、可序列化、可重放的状态变化
```

## 当前仍未完成

```text
真实 Trade Planner
真实 Manager Reducer
真实 Projection Target
Commit Coordinator
ExecutionProcessor 主链切换
Full Replay Recovery
```

不得声称本 PR 已解决 Manager-before-Journal。

---

# 十九、工程质量要求

代码要求：

* 类型明确；
* 命名与职责一致；
* 每个模块边界清晰；
* 不出现超大工具类；
* 不复制 Hash 算法；
* 不复制 Transaction ID 算法；
* 不复制 Event ID 算法；
* 不出现隐藏全局状态；
* 不读取系统时间；
* 不在模型中做外部 I/O；
* 不使用反射式魔法恢复核心 Projection；
* 不为了测试增加生产分支；
* 不增加无用抽象；
* 不留下 TODO 占位实现。

避免把所有功能堆进：

```text
transaction.py
codec.py
transaction_store.py
```

如职责过大，应拆分为：

```text
execution/identity.py
execution/event_identity.py
execution/transaction.py
execution/projection.py
execution/codec.py
execution/transaction_store.py
```

但不要为了目录美观拆分大量只有数行的无意义文件。

---

# 二十、工程门禁

至少执行：

```bash
uv lock --check
uv sync --frozen --all-packages --all-groups

uv run ruff check src tests examples packages
uv run ruff format --check src tests examples packages

uv run mypy src/onlyalpha

uv run pytest tests/execution/test_prepared_execution_transaction.py -q
uv run pytest tests/execution/test_execution_projection_contract.py -q
uv run pytest tests/architecture/test_prepared_execution_boundaries.py -q

uv run pytest tests/execution -q
uv run pytest tests/architecture -q
uv run pytest tests/integration -q

uv run pytest tests -q \
  -m "not external and not requires_network and not requires_tushare and not requires_local_qmt"
```

同时运行插件离线测试：

```bash
uv run pytest packages/fake/onlyalpha-plugin-broker-virtual/tests -q

uv run pytest packages/provider/onlyalpha-plugin-tushare/tests -q \
  -m "not external and not requires_network and not requires_tushare"

uv run pytest packages/provider/onlyalpha-plugin-miniqmt/tests -q \
  -m "not external and not requires_network and not requires_local_qmt"
```

并执行：

* Wheel Build；
* Sdist Build；
* Twine Check；
* Clean Install；
* Entry Point Smoke；
* Scenario Tests；
* Conformance Tests；
* Integration Demo Suite。

禁止通过以下方式制造绿色结果：

```text
skip
xfail
sleep
放宽断言
删除重要测试
平台绕过
异常吞噬
兼容 Wrapper
测试专用 Production 分支
```

外部网络或真实 Broker 测试无法执行时，必须明确说明未执行原因。

---

# 二十一、验收标准

PR 只有同时满足以下条件才算完成。

## Identity

* Transaction ID 完全确定性；
* Durable Event ID 完全确定性；
* Prepared Transaction 验证 Transaction ID；
* Prepared Transaction 验证 Event ID；
* 不依赖随机 UUID；
* 不依赖处理时间。

## Hash

* Authority Hash 与 Payload Hash 职责分离；
* Authority Hash 不包含 `prepared_at`；
* Payload Hash 包含完整 Payload；
* Store 幂等只比较 Authority Hash；
* Store 损坏检测比较 Payload Hash；
* 旧模糊 Hash API 已删除。

## Projection

* Settlement Projection 可独立重放；
* Fee Projection 可独立重放；
* Reservation 按领域单位拆分；
* Risk Projection 不使用说明字符串作为恢复权威；
* Projection Union 与顺序明确；
* Preconditions 与 Projections 一一对应。

## Store

* Memory 与 SQLite 契约一致；
* Store Sequence 在 Commit 内分配；
* 相同 Authority 幂等；
* 不同 Authority 冲突；
* Ready 前 Outbox 不可见；
* Event ID 和 Payload 可恢复；
* Memory Commit 无部分写入；
* SQLite Commit 完整回滚。

## 测试

* 新测试不依赖 Legacy Journal Fixture；
* 新测试不依赖 Legacy Outbox Fixture；
* 完整 Projection Transaction 可 Round-Trip；
* Memory/SQLite 共用 Contract Tests；
* 故障注入测试真实有效；
* 全部静态检查与离线测试通过。

## 清理

* 不保留旧字段 Alias；
* 不保留兼容构造函数；
* 不保留旧 Projection Wrapper；
* 不为示例保留旧接口；
* Public Export 只暴露当前清晰接口；
* 文档与源码一致。

---

# 二十二、最终交付报告

完成后输出以下报告。

## 1. 修改前问题

说明：

* 单一 Hash 职责混乱；
* `prepared_at` 影响业务幂等；
* 随机 Event ID 影响重放；
* 字符串 Projection 无法恢复；
* Reservation 单位混乱；
* Preconditions 约束不足。

## 2. 新 Identity 语义

列出：

```text
Transaction ID
Durable Event ID
Authority Hash
Payload Hash
Committed Payload Hash
```

说明每一个字段的输入和用途。

## 3. Projection 调整

列出删除和新增的 Projection 类型及其恢复语义。

## 4. Store 行为

说明：

```text
业务幂等
Payload 完整性
Projection Ready Gate
Memory 原子性
SQLite 原子性
```

## 5. 删除内容

列出所有删除的旧字段、旧类型、Alias、Fixture 依赖和 Re-export。

## 6. 测试结果

提供真实命令、测试数量、通过结果和未执行项目。

## 7. 下一阶段

明确下一阶段为：

```text
Generic T0 Cash Trade Planning Context
→ Pure Trade Reducers
→ OnlyTradeExecutionTransactionPlanner
→ 完整 Prepared Transaction 生成
```

不得声称本 PR 已完成：

```text
ExecutionProcessor 主链切换
Commit Coordinator
Manager Projection Apply
Runtime Recovery
```

---

# 最终目标

本 PR 完成后，OnlyAlpha 的 Prepared Execution Transaction 必须满足：

```text
相同业务成交输入
→ 相同 Transaction ID
→ 相同 Authority Hash
→ 相同 Durable Event IDs
```

同时：

```text
完整审计封装变化
→ Payload Hash 可以变化
→ 不影响业务幂等
```

并且所有 Projection 都必须成为：

```text
强类型
可序列化
可验证
可重放
职责隔离
```

优先保证业务权威、事务身份、数据完整性和恢复语义正确。

不要为了旧示例、旧测试或减少代码改动保留错误接口。
