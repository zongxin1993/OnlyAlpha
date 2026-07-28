# OnlyAlpha PR3：Real Manager Projection Targets 与完整 Authority Replay

## 一、任务目标

以当前 OnlyAlpha `master` 最新源码、测试、已接受 ADR 和正式领域模型为唯一事实源，实现真实 Manager Projection Targets。

本 PR 必须完成以下确定性状态安装链：

```text
OnlyCommittedExecutionTransaction
        ↓
OnlyExecutionProjectionApplier
        ↓
OnlyExecutionProjectionApplyContext
        ↓
Real Manager Projection Target
        ↓
校验 Before Authority
        ↓
幂等安装 Projection.after
        ↓
恢复 Manager-owned Index / Dedup / Sequence
```

PR3 的目标不是重新计算成交结果。

PR2 和 PR2.1 已经负责：

```text
真实 Manager Before Authority
+ Broker Trade Update
+ Market / Fee / Settlement Instruction
→ Pure Reducers
→ 完整 Prepared Transaction
```

PR3 只负责：

```text
已提交的 Projection
→ 真实 Manager Authority
```

完成后，系统必须证明：

```text
Projection.after
=
Manager 公开 Snapshot
+
Manager 内部索引
+
Manager 去重状态
+
Manager 序列状态
+
Manager Repository 状态
```

并且支持：

```text
第一次应用
→ APPLIED

重复应用同一 Projection
→ IDEMPOTENT

Before Version 不匹配
→ VERSION_CONFLICT

Before State Hash 不匹配
→ STATE_CONFLICT

同一 Execution Sequence 被不同 Payload 占用
→ PAYLOAD_CONFLICT
```

本 PR 完成后，下一阶段必须可以直接开展：

```text
PR4：Execution Commit Coordinator
```

---

# 二、当前基线与背景

开始实施前必须重新读取实际 `HEAD`。

历史审计基线为：

```text
12e0cdc4d316c00d4160d5fdec10b71d0229de91
Feat: Generic T0 Cash Pure Planner 真实性、业务等价性与故障矩阵收口
```

实际开发时若 `master` 已变化，以最新源码为准。

当前已经具备：

```text
Prepared Transaction Schema v3
Deterministic Transaction ID
Deterministic Durable Event ID
Authority Hash
Payload Hash
Replay-complete Execution State
Expected / Result State Hash
Projection Preconditions
Economic Invariant Validator
Memory / SQLite Transaction Store
Pure Generic T0 Cash Reducers
Trade Transaction Planner
真实 Manager Parity Harness
Planner 无副作用证明
Planner 故障矩阵
通用 Projection Applier
```

当前尚未具备：

```text
真实 Manager Projection Targets
Commit Coordinator
Projection Ready Coordinator
正式 Runtime Transaction Store 装配
ExecutionProcessor Trade Cutover
Full Runtime Replay
Legacy Journal 删除
```

当前通用 Applier 只能按 Component 找到 Target，但尚无真实 Order、Position、Account、Ledger 等 Target。

正式 Backtest Runtime 仍使用旧：

```text
OnlyInMemoryCommittedExecutionJournal
OnlyExecutionCommitPort
OnlyCommittedExecutionBuilder
OnlyExecutionProcessor 直接 Manager Mutation
```

本 PR 不切换该主链。

---

# 三、第一性原则

## 3.1 Projection 是历史业务结果权威

Projection 已经保存：

```text
完整 Before State
完整 After State
Expected Version
Result Version
Expected State Hash
Result State Hash
Projection Sequence
Payload Hash
```

Target 不得重新执行成交业务逻辑。

禁止通过以下方法应用 Projection：

```text
apply_trade()
apply_trade_cash_flow()
apply_trade_accounting()
apply_fee()
apply_valuation()
reserve()
consume()
release()
settle()
```

这些方法会：

* 重新计算业务结果；
* 再次推进 Version；
* 再次生成 ID；
* 再次发布领域 Event；
* 受当前版本业务规则影响。

Target 必须直接安装已经提交的权威 After State。

## 3.2 Replay 不运行 Reducer

历史恢复必须是：

```text
Committed Projection
→ Install After State
```

不得是：

```text
历史 Trade
→ 当前 Reducer
→ 重新计算 After State
```

否则市场规则、费用、舍入、风险和结算规则升级后，历史结果可能发生变化。

## 3.3 Manager Authority 不等于 Snapshot

Manager 的真实权威包括：

```text
公开 Entity / Snapshot
Repository
Active / Closed Index
Scope Index
Trade Fingerprints
Fee IDs
Cash Flow IDs
Valuation Versions
Entity Cycles
Record Sequences
Order Mappings
Reservation Indexes
Equity Timelines
Performance Timelines
Applied Projection Records
```

只恢复公开 Snapshot 是不完整的。

如果内部索引没有恢复，后续业务会出现：

* 重复 Trade 被再次接受；
* Position/Allocation ID Cycle 回退；
* Fee/Settlement Record ID 重复；
* Reservation 再次消费；
* Valuation Version 回退；
* Query 与 Snapshot 不一致；
* Runtime Replay 后行为不同。

## 3.4 Target 是 Manager 领域所有者的正式入口

禁止创建一个通用反射式 Target，通过：

```python
setattr(manager, private_field, value)
```

修改所有 Manager。

每个领域必须拥有明确的 Projection 安装入口。

推荐形式：

```python
class OnlyPositionManager:
    def apply_execution_projection(
        self,
        context: OnlyExecutionProjectionApplyContext,
        projection: OnlyPositionExecutionProjection,
    ) -> OnlyProjectionApplyResult:
        ...
```

也可以使用独立 Target 类，但必须由对应 Manager 的正式 Replay API 完成内部安装：

```python
class OnlyPositionExecutionProjectionTarget:
    def __init__(self, manager: OnlyPositionManager) -> None:
        self._manager = manager
```

Target 不得绕开 Manager 领域边界直接随意修改其私有状态。

## 3.5 Target 不发布业务 Event

Prepared Transaction 已包含 Durable Events。

Projection Target 只能恢复状态，不能发布：

```text
ORDER_FILLED
POSITION_OPENED
ACCOUNT_TRADE_APPLIED
STRATEGY_TRADE_APPLIED
```

否则正式切换后会出现双事件。

正确职责是：

```text
Target
→ 安装状态
→ 不发布 Event

PR4 Commit Coordinator
→ 所有 Projection 成功
→ mark_projection_ready()
→ Outbox 发布 Durable Event
```

## 3.6 PR3 采用前向恢复，不做跨 Manager 回滚

批量 Apply 可能出现：

```text
ORDER       APPLIED
POSITION    APPLIED
ALLOCATION  APPLIED
SETTLEMENT  FAILED
```

PR3 不尝试回滚前三个 Manager。

正确恢复方式：

```text
再次执行同一 Committed Transaction

ORDER       IDEMPOTENT
POSITION    IDEMPOTENT
ALLOCATION  IDEMPOTENT
SETTLEMENT  APPLIED
FEE         APPLIED
...
```

跨组件原子边界由未来 PR4 的 Durable Commit 提供。

---

# 四、正式范围

## 4.1 本 PR 必须实现的 Component

只实现当前 Generic T0 Cash Planner 产生的 12 个 Projection：

```text
ORDER
POSITION
ALLOCATION
SETTLEMENT
FEE
ACCOUNT
STRATEGY_LEDGER
ACCOUNT_CASH_RESERVATION
STRATEGY_CASH_RESERVATION
RISK_RESERVATION
RISK
VALUATION
```

## 4.2 本 PR 不实现

```text
POSITION_RESERVATION
MARGIN
MARGIN_RESERVATION
SELL
CLOSE
Partial Fill
Futures
Daily MTM
Transaction Store Commit Coordinator
Projection Ready Coordinator
ExecutionProcessor Cutover
Legacy Journal Removal
Runtime Startup Replay
Snapshot Checkpoint
Paper Runtime
Live Runtime
```

不支持的 Projection Component 必须明确返回：

```text
INVALID_COMPONENT
```

或在 Target Registry 装配时明确缺失。

不得伪造空 Target。

---

# 五、实施前重新审计

修改前执行：

```bash
git status
git rev-parse HEAD
git log -n 15 --oneline

rg "OnlyExecutionProjectionTarget"
rg "OnlyExecutionProjectionApplier"
rg "OnlyProjectionApplyResult"
rg "OnlyProjectionApplyStatus"

rg "OnlyCommittedExecutionTransaction"
rg "OnlyCommittedExecutionFact"
rg "OnlyExecutionProjectionIdentity"

rg "class OnlyOrderManager"
rg "class OnlyPositionManager"
rg "class OnlyPositionAllocationManager"
rg "class OnlyAccountManager"
rg "class OnlyStrategyLedgerManager"
rg "class OnlySettlementManager"
rg "class OnlyFeeManager"
rg "class OnlyRiskService"

rg "_trade_fingerprints"
rg "_cycles"
rg "_scope_index"
rg "_fee_ids"
rg "_trade_ids"
rg "_cash_change_ids"
rg "_cash_flow_ids"
rg "_valuation_versions"
rg "_equity_timelines"
rg "_event_sequence"
rg "_records"
rg "_sequence"

rg "only_*_execution_state"
rg "test_trade_planner_manager_parity"
rg "authority_digest"
```

必须形成修改前审计记录，至少回答：

1. 每个 Manager 的公开实体状态是什么；
2. 每个 Manager 的内部权威索引是什么；
3. 每个 Manager 的 Repository 如何写入；
4. 每个 Manager 如何识别重复 Trade、Fee、Cash Flow；
5. Position 和 Allocation Cycle 如何维护；
6. Fee 和 Settlement Record Sequence 如何维护；
7. Reservation Manager 如何按 Order 查找 Reservation；
8. Account 和 Ledger Valuation Version 如何维护；
9. Account Performance Timeline 如何维护；
10. Strategy Ledger Equity Timeline 如何维护；
11. 当前 Projection 是否包含恢复这些权威所需的全部信息；
12. 哪些信息必须从 Committed Fact 获取；
13. 哪些信息必须增加到 Projection Replay Metadata；
14. 哪些 Contract 必须在 PR3 内扩展。

不得在审计前直接编写 12 个 Adapter。

---

# 六、调整 Projection Apply Contract

## 6.1 当前 Contract 问题

当前 Target 只接收：

```python
execution_sequence
projection
```

但完整 Manager Authority 的恢复还需要：

* Transaction ID；
* Broker Update ID；
* Trade ID；
* Execution ID；
* Venue Trade ID；
* Stable Trade Order；
* Processing Sequence；
* Fact Scope；
* Projection Payload Hash。

因此必须新增不可变 Apply Context。

## 6.2 新增 OnlyExecutionProjectionApplyContext

建议：

```python
@dataclass(frozen=True, slots=True)
class OnlyExecutionProjectionApplyContext(OnlyDomainModel):
    transaction_id: str
    execution_sequence: int
    fact: OnlyCommittedExecutionFact
    projection: OnlyExecutionProjection

    def __post_init__(self) -> None:
        if not self.transaction_id.strip():
            raise ValueError("Projection apply context requires transaction_id")
        if self.execution_sequence < 1:
            raise ValueError("Projection apply context requires positive execution_sequence")
```

如果当前正式 Transaction ID 有强类型，必须使用强类型。

Apply Context 必须允许 Target 获取：

```text
transaction_id
execution_sequence
runtime_id
gateway_id
account_id
cluster_id
instrument_id
order_id
trade_id
broker_update_id
execution_id
venue_trade_id
source_sequence
processing_sequence
stable_order
```

具体字段以当前 `OnlyCommittedExecutionFact` 为准。

不得在 Target 内查询 Broker 或 Runtime 补充这些字段。

## 6.3 修改 Target Protocol

建议：

```python
class OnlyExecutionProjectionTarget(Protocol):
    @property
    def component(self) -> OnlyExecutionProjectionComponent:
        ...

    def apply_execution_projection(
        self,
        context: OnlyExecutionProjectionApplyContext,
    ) -> OnlyProjectionApplyResult:
        ...
```

## 6.4 修改通用 Applier

通用 Applier 应：

1. 接收完整 `OnlyCommittedExecutionTransaction`；
2. 按 Projection Sequence 排序；
3. 为每个 Projection 构造 Apply Context；
4. 调用对应 Target；
5. 汇总 APPLIED、IDEMPOTENT 和失败；
6. 遇到第一个失败立即停止；
7. 不发布 Event；
8. 不写 Store；
9. 不标记 Projection Ready；
10. 不执行回滚。

---

# 七、Applied Projection Ledger

## 7.1 作用

每个 Target 必须知道：

```text
某个 execution_sequence
是否已经应用到该 Component
```

否则无法区分：

```text
重复执行
```

与：

```text
状态刚好已经等于 After State
```

因此需要正式 Applied Projection Ledger。

## 7.2 数据模型

建议：

```python
@dataclass(frozen=True, slots=True)
class OnlyAppliedProjectionRecord(OnlyDomainModel):
    transaction_id: str
    execution_sequence: int
    component: OnlyExecutionProjectionComponent
    entity_key: str
    payload_hash: str
    result_state_hash: str
```

校验：

```text
execution_sequence > 0
transaction_id 非空
entity_key 非空
payload_hash 为 SHA-256
result_state_hash 为 SHA-256
```

## 7.3 Ledger Port

建议：

```python
class OnlyAppliedProjectionLedger(Protocol):
    def get(
        self,
        execution_sequence: int,
        component: OnlyExecutionProjectionComponent,
    ) -> OnlyAppliedProjectionRecord | None:
        ...

    def record(self, record: OnlyAppliedProjectionRecord) -> None:
        ...
```

PR3 第一阶段可以提供：

```text
OnlyInMemoryAppliedProjectionLedger
```

但接口必须可由后续 Runtime Recovery 使用。

不要在本 PR 实现 SQLite 持久化，除非现有 Storage 结构可以无范围扩张地复用。

## 7.4 幂等判定

已存在 Applied Record 时：

### 完全一致

```text
transaction_id 相同
entity_key 相同
payload_hash 相同
result_state_hash 相同
```

返回：

```text
IDEMPOTENT
```

Manager 不得改变。

### 同一 Sequence 不同 Payload

返回：

```text
PAYLOAD_CONFLICT
```

Manager 不得改变。

### 同一 Sequence 不同 Entity Key

同样返回：

```text
PAYLOAD_CONFLICT
```

不得将其解释为另一个合法 Projection。

---

# 八、统一 Target Apply 算法

每个 Target 必须遵循以下固定算法。

## 8.1 Component 校验

Target Component 与 Projection Component 不一致：

```text
INVALID_COMPONENT
```

Manager 不变。

## 8.2 Applied Ledger 校验

先检查 Applied Projection Record。

若已应用：

```text
完全一致 → IDEMPOTENT
存在冲突 → PAYLOAD_CONFLICT
```

不得继续检查 Manager 当前状态后再次安装。

## 8.3 读取当前 Execution State

Target 必须：

```text
Manager 当前 Snapshot
→ 正式 Snapshot Converter
→ Only*ExecutionState
```

不得自行复制 Converter 逻辑。

新实体不存在时，当前 State 为：

```text
None
```

## 8.4 Version 校验

```text
current_version != expected_version
→ VERSION_CONFLICT
```

新实体：

```text
Current State = None
Expected Version = 0
```

已有实体：

```text
Current State != None
Current Version = Expected Version
```

## 8.5 State Hash 校验

```text
only_execution_state_hash(current_state)
!= expected_state_hash
→ STATE_CONFLICT
```

Version 相同但内容不同时，必须是 `STATE_CONFLICT`，不能误报 Version Conflict。

## 8.6 Result State 自校验

应用前重新验证：

```text
only_execution_state_hash(projection.after)
==
projection.identity.result_state_hash
```

虽然 Projection 构造时已验证，但 Target 边界仍应防止不可信对象或未来反序列化错误。

## 8.7 构造 Install Plan

所有可能失败的步骤必须在修改 Manager 前完成：

* 类型转换；
* Entity Rehydrate；
* Repository Snapshot；
* Index 更新；
* Fingerprint 构造；
* Cycle 计算；
* Record Sequence 计算；
* Timeline Point 构造；
* Applied Record 构造。

## 8.8 原子安装单个 Target

最终提交阶段只允许执行确定性内存和 Repository 更新。

提交过程中不得：

* 再做业务校验；
* 调用外部服务；
* 发布 Event；
* 查询 Broker；
* 读取 Clock；
* 生成随机 ID；
* 调用可能失败的业务 Resolver。

## 8.9 安装后校验

安装后通过正式 Converter重新读取 Execution State，并验证：

```text
Current State Hash
==
Projection Result State Hash
```

失败必须作为严重内部错误。

在这种情况下不得记录 Applied Projection Record。

由于单 Target 已经发生部分修改，需要在 Target 内部恢复到 Apply 前状态，或者确保安装阶段本身完全不可失败。

推荐通过完整 Install Plan 和可替换容器实现无失败提交。

## 8.10 记录 Applied Projection

只有完整安装成功后，才能写 Applied Projection Record。

返回：

```text
APPLIED
```

---

# 九、Replay Metadata Contract 补全

在实现 Target 前，必须解决当前 Projection 中不足以恢复 Manager Authority 的信息。

## 9.1 Position Cycle

Position Manager 新实体 ID 依赖：

```text
Position Key
+ Cycle
```

Cycle 决定下一次新建 Position 的 ID。

禁止从：

```text
POS-...-00000001
```

字符串中解析 Cycle。

推荐增加：

```python
@dataclass(frozen=True, slots=True)
class OnlyPositionExecutionReplayMetadata(OnlyDomainModel):
    cycle: int
    trade_fingerprints: tuple[str, ...]
```

并在 Position Projection 中加入：

```python
replay: OnlyPositionExecutionReplayMetadata
```

也可以将 `cycle` 加入 `OnlyPositionExecutionState`，但必须明确：

* Cycle 是实体状态还是 Manager Metadata；
* State Hash 是否应包含 Cycle；
* 新实体和已有实体如何验证 Cycle 不回退。

推荐将 Cycle 作为 Manager Replay Metadata，并纳入 Projection Payload Hash。

## 9.2 Allocation Cycle

建立等价：

```python
@dataclass(frozen=True, slots=True)
class OnlyAllocationExecutionReplayMetadata(OnlyDomainModel):
    cycle: int
    trade_fingerprints: tuple[str, ...]
```

## 9.3 Trade Fingerprints

Position、Allocation 和 Strategy Ledger 需要恢复：

```text
trade:<trade_id>
execution:<execution_id>
venue:<venue_trade_id>
```

具体规则必须与真实 Manager 当前 `_fingerprints()` 完全一致。

不得在多个 Target 中分别手写不同规则。

提取共享纯函数，例如：

```python
def only_execution_trade_fingerprints(
    fact: OnlyCommittedExecutionFact,
) -> tuple[str, ...]:
    ...
```

该函数必须被：

* Planner/PR2 Fixture；
* Position Target；
* Allocation Target；
* Ledger Target；
* Recovery Tests；

共同使用。

## 9.4 Fee 与 Settlement Sequence Metadata

Fee 和 Settlement Execution State 必须明确包含：

```text
Before Record Sequence Head
After Record Sequence Head
```

若当前 State 已包含完整 Records 但没有显式 Sequence Head，必须确认：

```text
max(record.sequence)
```

是否永远等于内部 Manager Sequence。

如果存在删除、过滤或归档可能，不能依赖 `max(records)`。

应显式增加 Sequence Head。

## 9.5 Valuation Replay Metadata

当前 Valuation State 只有：

```text
Account ID
Valuation Time
Cash
Position Market Value
Unrealized PnL
Equity
Version
```

必须审计是否足以恢复：

```text
Account Valuation Version
Account Performance Timeline
Ledger Valuation Version
Ledger Equity Timeline
Equity Sequence
Trading Day
Valuation Source
Realized PnL
Fees
Snapshot Phase
```

如果不足，必须扩展 Valuation Projection。

建议：

```python
@dataclass(frozen=True, slots=True)
class OnlyAccountEquityPointReplay(OnlyDomainModel):
    ...
```

```python
@dataclass(frozen=True, slots=True)
class OnlyStrategyLedgerEquityPointReplay(OnlyDomainModel):
    ...
```

并让 Valuation Projection 包含本事务新增的 Timeline Points。

不能仅恢复最终 Equity，而丢失 Performance Timeline。

---

# 十、Entity Rehydration

## 10.1 原则

Projection After State 是权威，但 Manager 通常存储可变 Entity。

必须提供正式、受控的 Rehydration 方法。

推荐：

```python
class OnlyPosition:
    @classmethod
    def restore(
        cls,
        state: OnlyPositionExecutionState,
    ) -> OnlyPosition:
        ...
```

或者：

```python
def only_restore_position_entity(
    state: OnlyPositionExecutionState,
) -> OnlyPosition:
    ...
```

要求：

* 不重新执行业务行为；
* 不发布 Event；
* 不推进 Version；
* 不读取 Clock；
* 不生成 ID；
* 恢复后 Snapshot 与 Execution State 完全一致。

每个可变 Entity 都应有对应 Restore 路径：

```text
Order
Position
Allocation
Account
Strategy Ledger
Reservation
Risk Aggregate
```

## 10.2 禁止通过构造后反复赋私有字段

错误方式：

```python
entity = OnlyPosition(...)
entity._quantity = ...
entity._version = ...
```

正确方式是提供领域所有者控制的 Restore Constructor。

---

# 十一、各 Target 详细要求

## 11.1 Order Target

必须恢复：

```text
Order Entity
Order Repository
Order ID Index
Client Order ID Index
Venue Order ID Index
Order Status Index
Last External Sequence
```

必须保持：

* Request ID；
* Client Order ID；
* Venue Order ID；
* Original Quantity；
* Price；
* TIF；
* Tags；
* Metadata；
* Failure/Rejection；
* Lifecycle Timestamps。

不得调用 Order Fill Processor。

应用后正式 Order Query 必须返回与 Projection.after 一致的 Snapshot。

---

## 11.2 Position Target

必须恢复：

```text
Position Entity
_active
_closed
_repository
_trade_fingerprints
_cycles
```

### 新 Position

```text
before = None
```

必须：

* 创建与 Projection.after 相同的 Position ID；
* 将 Entity 放入 Active 或 Closed；
* 设置 Cycle；
* 写 Repository；
* 添加 Trade Fingerprints。

### 已有 Position

必须：

* Position ID 不变；
* Key 不变；
* 替换 Entity Authority；
* 更新 Active/Closed 所属；
* 更新 Repository；
* 添加 Trade Fingerprints；
* Cycle 不回退。

### 关闭 Position

如果 After 为 CLOSED：

* 从 Active 删除；
* 加入 Closed；
* Repository 保留最终 Snapshot；
* Cycle 保留；
* 重复 Replay 不得重复追加 Closed Snapshot。

---

## 11.3 Allocation Target

必须恢复：

```text
Allocation Entity
_active
_closed
_repository
_trade_fingerprints
_cycles
```

不得修改 `_unallocated`，除非 Projection 明确包含 Unallocated Authority。

Generic T0 Planner 当前具有明确 Cluster，不应产生 Unallocated State。

应用后：

```text
snapshot_all()
closed()
list_by_cluster()
list_by_account()
```

必须与 Legacy Manager 一致。

---

## 11.4 Settlement Target

必须恢复：

```text
Settlement State
Pending Instruction
Settlement Records
Instruction Idempotency
Global Record Sequence
```

不得重新调用 Market Rule Engine。

不得重新计算日期。

应用后下一条 Settlement Record 的 Sequence 和 ID 必须正确。

---

## 11.5 Fee Target

必须恢复：

```text
Fee State
Fee Records
Instruction Idempotency Key
Fee Record Sequence
Authoritative Total
```

不得调用 Fee Resolver 或 Fee Engine。

应用后：

* 重复 Fee Instruction 必须识别为 Duplicate；
* 下一条 Fee Record ID 必须正确；
* Record 顺序必须稳定。

---

## 11.6 Account Target

必须恢复：

```text
Account Entity
Account Repository
Trade ID Index
Fee ID Index
Cash Change ID Index
Last External Sequence
Quality Flags
Margin State
Valuation Version
```

但 Account Cash Reservation 由独立 Target 负责。

Account Target 不得再次消费或释放 Reservation。

### Trade ID

从 Committed Fact 获取 Trade ID，并加入 Account `_trade_ids`。

### Fee ID

必须审计当前 Legacy Trade 是否通过独立 `apply_fee()` 或仅在 Trade Cash Flow 中累计 Fee。

只恢复 Legacy 实际拥有的 Fee ID Authority，不得凭空增加索引。

### Valuation

Account Projection 和 Valuation Projection 的职责必须明确：

```text
ACCOUNT
→ 恢复最终 Account 经济状态

VALUATION
→ 恢复 Valuation Version 和 Performance Timeline
```

不得重复改变 Account Version 或经济字段。

---

## 11.7 Account Cash Reservation Target

只恢复：

```text
OnlyAccountReservation
Reservation Manager ID Index
Order ID Index
Reservation Version
State
Consumed
Remaining
```

不修改：

```text
Account Cash Balance
Account Frozen Cash
Account Version
```

这些属于 Account Projection。

重复应用不得再次减少 Remaining。

---

## 11.8 Strategy Ledger Target

必须恢复：

```text
Ledger Entity
Ledger Repository
_scope_index
_trade_fingerprints
_fee_ids
_cash_flow_ids
Cash Entries
Fee Entries
Last Trade
Quality Flags
```

Strategy Reservation 和 Valuation Timeline 分别由对应 Target 恢复。

必须从 After State 中恢复完整：

* Cash Entries；
* Fee Entries；
* Initial Capital；
* External Cash Flow；
* Position Cost；
* Position Market Value；
* PnL；
* Equity；
* Version；
* Last Trade。

### Fee ID Index

从 After State 的 Fee Entries 恢复新增 Fee ID。

### Trade Fingerprint

从 Committed Fact 生成。

### Scope Index

必须确保：

```text
(runtime, account, cluster, currency)
→ ledger key
```

恢复正确。

---

## 11.9 Strategy Cash Reservation Target

只恢复：

```text
Strategy Cash Reservation Manager
Order ID Index
Reservation State
Stage
Consumed
Remaining
Version
Metadata
```

不修改：

```text
Ledger Cash Reserved
Ledger Cash Available
Cash Entries
Ledger Version
```

这些属于 Strategy Ledger Projection。

---

## 11.10 Risk Reservation Target

必须恢复：

```text
Risk Reservation Entity
Reservation ID Index
Order ID Index
Reservation Sequence
Quantity/Notional Consumption
State
Release Reason
Version
```

不得重新运行 Pre-trade Risk。

不得重新计算 Exposure。

---

## 11.11 Risk Target

必须恢复 Cluster 聚合风险快照。

正式语义必须保持：

```text
OnlyRiskExecutionState
=
Runtime / Cluster / Account 聚合风险快照
```

它不是：

```text
单订单 Risk Reservation
持仓风险
账户保证金风险
```

Target 必须恢复：

* Scope；
* Active Order Count；
* Reserved Quantity；
* Reserved Notional；
* Remaining Order Notional；
* Snapshot Version；
* Risk Level；
* Trading Block State；
* 相关聚合 Index。

不得调用 Risk Rule Pipeline。

---

## 11.12 Valuation Target

必须恢复：

```text
Account Valuation Version
Strategy Ledger Valuation Version
Account Performance Timeline
Strategy Ledger Equity Timeline
Account Equity Sequence
Ledger Equity Sequence
Runtime Valuation Authority
```

不应再次改变 Account/Ledger 的最终经济字段。

Valuation Target 必须做到：

```text
Target Apply 后
Account Snapshot 不因 Valuation Target 再推进 Version
Ledger Snapshot 不因 Valuation Target 再推进 Version
Performance Timeline 与 Legacy 完全一致
```

---

# 十二、Projection Target Registry

建立正式 Target Registry Factory，例如：

```python
def only_create_generic_t0_execution_projection_targets(
    *,
    order_manager: OnlyOrderManager,
    position_manager: OnlyPositionManager,
    allocation_manager: OnlyPositionAllocationManager,
    settlement_manager: OnlySettlementManager,
    fee_manager: OnlyFeeManager,
    account_manager: OnlyAccountManager,
    ledger_manager: OnlyStrategyLedgerManager,
    risk_service: OnlyRiskService,
    applied_ledger: OnlyAppliedProjectionLedger,
) -> Mapping[
    OnlyExecutionProjectionComponent,
    OnlyExecutionProjectionTarget,
]:
    ...
```

要求：

* Component 唯一；
* Target Component 与 Mapping Key 一致；
* 缺失 Target 明确失败；
* 不依赖 Runtime Service Locator；
* 不从全局变量查询 Manager；
* 不进入 Backtest Runtime 正式装配。

该 Factory 主要供 PR3 测试和未来 PR4 装配使用。

---

# 十三、Target 内部原子性

## 13.1 单 Target 失败时必须 Manager 不变

每个 Target 必须对以下失败证明：

```text
INVALID_COMPONENT
VERSION_CONFLICT
STATE_CONFLICT
PAYLOAD_CONFLICT
Entity Restore Failure
Repository Validation Failure
Replay Metadata Failure
```

Authority Digest 完全不变。

## 13.2 安装计划

建议每个复杂 Target 使用 Install Plan。

例如：

```python
@dataclass(frozen=True, slots=True)
class OnlyPositionProjectionInstallPlan:
    entity: OnlyPosition
    active_operation: ...
    closed_operation: ...
    repository_snapshot: OnlyPositionSnapshot
    fingerprints_to_add: tuple[str, ...]
    cycle: int
    applied_record: OnlyAppliedProjectionRecord
```

Install Plan 构造阶段可以失败。

Commit 阶段不得失败。

## 13.3 Repository 事务问题

如果 Repository 接口的 `save()` 可能失败，则必须定义顺序。

第一阶段 In-memory Repository 中，推荐：

1. 构造所有内存状态；
2. 写 Repository；
3. 安装 Manager 内部状态；
4. 记录 Applied Record。

但如果 Repository 写成功、Manager 安装失败会不一致。

更可靠方式是：

* 为 Manager 提供原子 `restore_authority()`；
* In-memory Repository 支持完整替换；
* Manager 与 Repository 使用同一个不可失败提交段。

不要通过异常补偿掩盖不确定行为。

PR3 必须在 ADR 中明确单 Target 原子边界。

---

# 十四、批量 Apply 与前向恢复

扩展 `OnlyExecutionProjectionBatchResult`，必要时加入：

```text
last_successful_projection_sequence
replay_required
failed_status
```

但不要加入 Store 或 Ready 状态。

通用 Applier 应返回：

```python
@dataclass(frozen=True, slots=True)
class OnlyExecutionProjectionBatchResult:
    execution_sequence: int
    applied: tuple[OnlyProjectionApplyResult, ...]
    idempotent: tuple[OnlyProjectionApplyResult, ...]
    failed_projection: OnlyExecutionProjection | None
    status: OnlyExecutionProjectionBatchStatus
    error: str | None
```

现有结构可复用。

需要新增测试：

```text
第一次：

ORDER       APPLIED
POSITION    APPLIED
ALLOCATION  FAILED

第二次：

ORDER       IDEMPOTENT
POSITION    IDEMPOTENT
ALLOCATION  APPLIED
SETTLEMENT  APPLIED
...
```

最终必须：

```text
Authority Digest
==
一次成功完成全部 Target 的 Authority Digest
```

---

# 十五、测试 Harness

复用 PR2.1 的真实 Manager Harness。

建立三个独立环境：

```text
Environment A：Legacy Processor Environment
Environment B：Projection Apply Environment
Environment C：Expected Replay Control Environment
```

## Environment A

```text
真实 OnlyExecutionProcessor
→ Legacy Manager After Authority
```

## Environment B

```text
真实 Before Manager
→ Planner
→ Prepared Transaction
→ 测试 Commit Sequence 分配
→ Committed Transaction
→ Real Projection Targets
```

## Environment C

用于：

* 重复 Replay；
* 中间失败恢复；
* 顺序多事务 Replay；
* 后续行为测试。

不得从 Environment A 的 After State 构造 Environment B。

三者必须从同一不可变 Scenario Definition 独立创建。

---

# 十六、每个 Target 的测试矩阵

每个 Target 至少覆盖：

## 正常应用

```text
Before Authority
+ Projection
→ APPLIED
→ Current State == After State
```

## 重复应用

```text
同一 Transaction / Sequence / Payload
→ IDEMPOTENT
→ Authority Digest 不变
```

## Version Conflict

```text
Current Version 被提前推进
→ VERSION_CONFLICT
→ Authority Digest 不变
```

## State Conflict

```text
Current Version 相同
但 Current State 内容被修改
→ STATE_CONFLICT
→ Authority Digest 不变
```

## Payload Conflict

```text
同一 Sequence 已应用
再使用不同 Payload
→ PAYLOAD_CONFLICT
→ Authority Digest 不变
```

## Invalid Component

错误 Projection 交给 Target：

```text
→ INVALID_COMPONENT
→ Authority Digest 不变
```

## Restore Failure

构造非法 Replay Metadata 或无效 After State：

```text
→ 失败
→ Authority Digest 不变
```

---

# 十七、完整真实 Manager Parity

必须继续覆盖 PR2.1 的四个场景：

## 场景 1

```text
新 Position
新 Allocation
零费用
Reservation 精确匹配
```

## 场景 2

```text
新 Position
新 Allocation
非零费用
```

## 场景 3

```text
Limit Price 高于 Fill Price
产生超额 Cash Reservation Release
```

## 场景 4

```text
已有 Position
已有 Allocation
第二笔 BUY OPEN
```

比较：

```text
Legacy Environment After Digest
==
Projection Apply Environment After Digest
```

必须包含：

```text
Order
Position
Allocation
Settlement
Fee
Account
Strategy Ledger
Account Reservation
Strategy Reservation
Risk Reservation
Risk
Valuation
Repository
Cycles
Fingerprints
Indexes
Record Sequences
Valuation Versions
Performance Timelines
Equity Timelines
```

不得只比较公开 Snapshot。

---

# 十八、查询行为等价

应用 Projection 后，必须通过正式查询接口比较：

```text
Order Query
Position Query
Allocation Query
Account Query
Strategy Ledger Query
Reservation Query
Risk Snapshot Query
Settlement Records
Fee Records
Performance Timeline
Equity Timeline
```

结果必须与 Legacy 环境一致。

不得只读取私有字段。

---

# 十九、后续行为等价

这是验证内部索引是否完整恢复的关键。

Projection Apply 后继续执行以下操作。

## 19.1 重复 Trade

相同 Trade 再进入 Manager 业务 API：

```text
必须被识别为 Duplicate
```

不得重复修改 Position、Allocation、Account 或 Ledger。

## 19.2 下一 Position Cycle

关闭当前 Position 后重新开仓：

```text
新的 Position ID
必须使用正确的下一 Cycle
```

## 19.3 下一 Allocation Cycle

同样验证 Allocation ID。

## 19.4 下一 Fee Record

新增下一条 Fee：

```text
Record Sequence / ID 不重复
```

## 19.5 下一 Settlement Record

同样验证。

## 19.6 下一 Valuation Version

新增下一次估值：

```text
必须被接受
旧版本必须被识别为 Duplicate / Stale
```

## 19.7 Reservation 终态

已消费并释放的 Reservation：

```text
不得再次消费
不得再次释放形成版本推进
```

## 19.8 Query Index

按 Account、Cluster、Instrument 查询必须返回正确对象。

---

# 二十、连续多事务 Replay

不能只测试单笔 Transaction。

至少建立：

```text
Transaction 1：首次 BUY OPEN
Transaction 2：第二笔 BUY OPEN 增仓
Transaction 3：第三笔 BUY OPEN 增仓
```

依次：

```text
Apply T1
Apply T2
Apply T3
```

验证：

* Version 连续；
* State Hash 连续；
* Position/Allocation ID 保持；
* Stable Order 连续；
* Fee/Settlement Sequence 连续；
* Reservation 独立；
* Account/Ledger Cash 连续；
* Risk 聚合连续；
* Valuation Timeline 连续。

最终 Digest 必须等于 Legacy 环境连续执行三笔 Trade 的结果。

---

# 二十一、中间失败恢复测试

对 12 个 Component 逐一注入一次失败。

流程：

```text
第一次 Batch Apply
→ 在 Component N 返回失败
→ Component 1..N-1 已 APPLIED

第二次 Batch Apply
→ Component 1..N-1 返回 IDEMPOTENT
→ Component N 及后续成功
```

每个失败点都必须验证：

```text
最终 Digest
=
一次成功完整 Apply 的 Digest
```

不得通过清空 Runtime 重试。

这是真正的 Forward Recovery 验证。

---

# 二十二、事件和外部副作用测试

PR3 Target Apply 前后必须验证：

```text
EventBus 不变
Execution Event Buffer 不变
Durable Outbox 不变
Transaction Store 不变
Legacy Journal 不变
Audit Store 不变
Reconciliation Queue 不变
Broker Queue 不变
```

Applied Projection Ledger 是 PR3 唯一允许新增的副作用。

Target 不得发布任何领域 Event。

---

# 二十三、确定性测试

同一个 Committed Transaction 和同一个 Before Authority：

```text
新建 Target Registry
重复 Apply
```

结果必须稳定。

至少验证：

```text
Applied Result 相等
Applied Record 相等
Authority Digest 相等
Query Result 相等
```

不同 Python 对象实例不能影响结果。

禁止依赖：

* Object ID；
* Set 遍历；
* Dict 非规范顺序；
* 当前时间；
* 本地时区；
* UUID4；
* Manager 实例地址；
* Repository 插入顺序。

---

# 二十四、架构边界测试

新增或扩展：

```text
tests/architecture/test_execution_projection_target_boundaries.py
```

必须确保：

* Target 不 import Planner Reducer；
* Target 不调用 Reducer；
* Target 不调用 Market Rule Engine；
* Target 不调用 Fee Resolver；
* Target 不调用 Broker；
* Target 不读取 Clock；
* Target 不发布 Event；
* Target 不写 Transaction Store；
* Target 不标记 Projection Ready；
* Target 不调用 Legacy Journal；
* Target 不调用 Manager 普通 Mutation API；
* Target 不使用 UUID4；
* Target 不解析 Position/Allocation ID 字符串获取 Cycle；
* Target 不通过反射修改任意 Manager；
* Target 不依赖 Runtime Service Locator；
* Target 不执行跨 Manager 回滚；
* Production 不存在 Test Hook；
* Production 不存在 Validation Bypass；
* 不存在 Compatibility Target；
* 不存在重复 Target 实现；
* 不存在空 Target 伪装支持。

---

# 二十五、公共 API

正式导出：

```text
OnlyExecutionProjectionApplyContext
OnlyAppliedProjectionRecord
OnlyAppliedProjectionLedger
OnlyInMemoryAppliedProjectionLedger

OnlyOrderExecutionProjectionTarget
OnlyPositionExecutionProjectionTarget
OnlyAllocationExecutionProjectionTarget
OnlySettlementExecutionProjectionTarget
OnlyFeeExecutionProjectionTarget
OnlyAccountExecutionProjectionTarget
OnlyStrategyLedgerExecutionProjectionTarget
OnlyAccountCashReservationExecutionProjectionTarget
OnlyStrategyCashReservationExecutionProjectionTarget
OnlyRiskReservationExecutionProjectionTarget
OnlyRiskExecutionProjectionTarget
OnlyValuationExecutionProjectionTarget

only_create_generic_t0_execution_projection_targets
```

具体导出层级以当前包结构为准。

不要暴露内部 Install Plan。

删除所有被替代的 Reference Target Alias 或 PR3 原型。

保留现有 Reference In-memory Target，仅当它仍用于独立 Contract Test；必须改名明确为：

```text
OnlyReferenceExecutionProjectionTarget
```

不得让它与真实 Manager Target 混淆。

---

# 二十六、文档与 ADR

新增：

```text
docs/execution_projection_targets.md
docs/adr/0038-real-manager-projection-targets.md
```

更新：

```text
docs/execution_prepared_transaction.md
docs/execution_trade_planning.md
docs/architecture.md
```

ADR 必须说明：

1. 为什么 Projection Replay 不重新运行 Reducer；
2. 为什么 Snapshot 不等于 Manager Authority；
3. Apply Context 为什么需要完整 Fact；
4. Applied Projection Ledger 的作用；
5. APPLIED、IDEMPOTENT、VERSION_CONFLICT、STATE_CONFLICT、PAYLOAD_CONFLICT 的语义；
6. Position/Allocation Cycle 如何持久化；
7. Trade Fingerprint 如何恢复；
8. Fee/Settlement Sequence 如何恢复；
9. Reservation Target 与 Account/Ledger Target 的职责分离；
10. Risk Aggregate 与 Risk Reservation 的职责分离；
11. Valuation Timeline 如何恢复；
12. 为什么 Target 不发布 Event；
13. 为什么使用 Forward Recovery 而不是 Rollback；
14. 单 Target 原子边界；
15. PR3 与 PR4 的职责分工；
16. 当前不支持的 Projection Component。

不得声称：

```text
Commit-before-Mutation 已进入 Runtime
Transaction Store 已进入正式装配
Projection Ready 已完成
ExecutionProcessor 已切换
Full Replay 已完成
Legacy Journal 已删除
```

---

# 二十七、删除与清理

删除：

* 未完成的 Real Target 原型；
* 通过普通 Manager Mutation API 模拟 Replay 的代码；
* 解析 ID 字符串恢复 Cycle 的代码；
* Target 内直接发布 Event 的代码；
* 通用反射式 Manager Target；
* Target 内重新计算 Fee/Settlement/Risk 的代码；
* Validation Bypass；
* Compatibility Target；
* 测试专用生产分支；
* 重复的 Applied Record 实现。

更新：

* Projection Contract；
* Codec；
* Planner Fixture；
* PR2/PR2.1 Tests；
* Public Export；
* Docs；
* ADR；
* Type Hints。

如果增加 Replay Metadata，必须升级 Schema。

不保留旧 Schema 兼容层。

当前项目仍为 Alpha，应直接迁移所有使用方。

---

# 二十八、工程门禁

至少执行：

```bash
uv lock --check
uv sync --frozen --all-packages --all-groups

uv run ruff check src tests examples packages
uv run ruff format --check src tests examples packages

uv run mypy src/onlyalpha
```

定向测试：

```bash
uv run pytest tests/execution/targets/test_order_projection_target.py -q
uv run pytest tests/execution/targets/test_position_projection_target.py -q
uv run pytest tests/execution/targets/test_allocation_projection_target.py -q
uv run pytest tests/execution/targets/test_settlement_projection_target.py -q
uv run pytest tests/execution/targets/test_fee_projection_target.py -q
uv run pytest tests/execution/targets/test_account_projection_target.py -q
uv run pytest tests/execution/targets/test_strategy_ledger_projection_target.py -q
uv run pytest tests/execution/targets/test_reservation_projection_targets.py -q
uv run pytest tests/execution/targets/test_risk_projection_targets.py -q
uv run pytest tests/execution/targets/test_valuation_projection_target.py -q

uv run pytest tests/execution/test_real_projection_target_manager_parity.py -q
uv run pytest tests/execution/test_real_projection_target_forward_recovery.py -q
uv run pytest tests/execution/test_real_projection_target_followup_behavior.py -q
uv run pytest tests/execution/test_real_projection_target_side_effects.py -q
uv run pytest tests/architecture/test_execution_projection_target_boundaries.py -q
```

完整回归：

```bash
uv run pytest tests/execution -q
uv run pytest tests/architecture -q
uv run pytest tests/integration -q
uv run pytest tests/scenario -q
uv run pytest tests/conformance -q

uv run pytest tests -q \
  -m "not external and not requires_network and not requires_tushare and not requires_local_qmt"
```

插件离线测试：

```bash
uv run pytest packages/fake/onlyalpha-plugin-broker-virtual/tests -q

uv run pytest packages/provider/onlyalpha-plugin-tushare/tests -q \
  -m "not external and not requires_network and not requires_tushare"

uv run pytest packages/provider/onlyalpha-plugin-miniqmt/tests -q \
  -m "not external and not requires_network and not requires_local_qmt"
```

还必须执行：

```text
Wheel Build
Sdist Build
Twine Check
Clean Install
Entry Point Smoke
Generic T0 Scenario
```

禁止通过以下方式制造绿色：

```text
skip
xfail
删除关键测试
仅比较公开 Snapshot
忽略内部 Index
忽略 Version
忽略 State Hash
忽略 Timeline
忽略后续行为
放宽冲突断言
异常吞噬
Compatibility Wrapper
测试专用 Production Hook
```

---

# 二十九、验收标准

PR3 只有同时满足以下条件才算完成。

## 29.1 Apply Contract

* Target 能访问完整 Transaction Fact；
* 每个 Projection 使用统一 Apply Context；
* Applied Projection Ledger 正确工作；
* 通用 Applier 支持批量前向恢复。

## 29.2 12 个 Real Target

以下全部实现：

```text
ORDER
POSITION
ALLOCATION
SETTLEMENT
FEE
ACCOUNT
STRATEGY_LEDGER
ACCOUNT_CASH_RESERVATION
STRATEGY_CASH_RESERVATION
RISK_RESERVATION
RISK
VALUATION
```

## 29.3 完整 Authority

恢复后：

```text
公开 Snapshot
Repository
Index
Fingerprint
Cycle
Sequence
Reservation
Timeline
Applied Record
```

全部正确。

## 29.4 冲突语义

所有 Target 都正确区分：

```text
APPLIED
IDEMPOTENT
VERSION_CONFLICT
STATE_CONFLICT
PAYLOAD_CONFLICT
INVALID_COMPONENT
```

所有冲突下 Manager 必须不变。

## 29.5 真实 Manager Parity

四个 Generic T0 场景中：

```text
Legacy Manager After Digest
=
Projection Target After Digest
```

## 29.6 后续行为等价

Projection Apply 后：

* 重复 Trade 可识别；
* 下一 Position/Allocation Cycle 正确；
* 下一 Fee/Settlement Sequence 正确；
* 下一 Valuation Version 正确；
* Reservation 终态正确；
* Query 结果正确。

## 29.7 Forward Recovery

对每个 Component 注入一次失败后：

```text
再次 Apply
→ 已成功组件 IDEMPOTENT
→ 失败组件及后续继续 APPLIED
→ 最终 Digest 正确
```

## 29.8 无外部副作用

Target Apply 不改变：

```text
EventBus
Event Buffer
Outbox
Transaction Store
Legacy Journal
Audit
Reconciliation Queue
Broker Queue
```

## 29.9 PR4 Ready

PR4 不应再需要修改：

```text
Projection Apply Context
Target Protocol
Applied Projection Ledger
Manager Restore API
Cycle Replay Contract
Fingerprint Replay Contract
Valuation Replay Contract
Conflict Status
```

---

# 三十、最终交付报告

完成后输出以下报告。

## 1. 修改前审计

列出：

* HEAD；
* 当前通用 Applier；
* 每个 Manager 的内部 Authority；
* Contract 缺口。

## 2. Apply Context

列出完整字段及用途。

## 3. Replay Metadata

说明：

* Position Cycle；
* Allocation Cycle；
* Trade Fingerprints；
* Fee Sequence；
* Settlement Sequence；
* Valuation Timeline。

## 4. Applied Projection Ledger

说明 Key、幂等规则和 Payload Conflict。

## 5. 各 Target

逐项列出：

```text
恢复的公开状态
恢复的内部索引
恢复的去重状态
恢复的序列
禁止调用的方法
```

## 6. 单 Target 原子性

说明 Install Plan 和失败不变性。

## 7. Manager Parity

列出四个场景的完整 Digest 对比结果。

## 8. Follow-up Behavior

列出：

* Duplicate Trade；
* Cycle；
* Fee Sequence；
* Settlement Sequence；
* Valuation Version；
* Reservation Terminal State。

## 9. Forward Recovery

列出 12 个失败点的恢复结果。

## 10. 无副作用

证明 Event、Store、Journal、Audit 和 Reconciliation 不变。

## 11. 删除内容

列出旧原型、Alias、错误 Replay 和绕过接口。

## 12. 测试结果

提供真实执行命令、通过数量和未执行原因。

不得伪造结果。

## 13. PR4 Readiness

明确回答：

```text
PR4：Execution Commit Coordinator
```

是否可以开始。

只有全部验收条件完成时才回答：

```text
GO
```

否则回答：

```text
NO-GO
```

并列出真实阻塞项。

---

# 最终目标

PR3 完成后，OnlyAlpha 必须第一次具备：

```text
Committed Execution Projection
→ Real Manager Authority
```

并且：

```text
第一次应用
→ 完整安装

重复应用
→ 幂等

状态冲突
→ 明确拒绝且不修改 Manager

中途失败
→ 可以通过重复 Batch 前向恢复
```

完整职责边界必须成为：

```text
Planner
→ 计算业务结果

Transaction Store
→ 保存 Durable Authority

Projection Target
→ 安装真实 Manager Authority

Commit Coordinator
→ 组织 Commit / Apply / Ready / Outbox

ExecutionProcessor
→ 接入 Broker Runtime
```

PR3 不得重新计算交易业务，也不得提前承担 PR4 的事务编排职责。
