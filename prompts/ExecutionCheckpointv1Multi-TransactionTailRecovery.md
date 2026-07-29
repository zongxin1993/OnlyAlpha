# OnlyAlpha PR4.2：Execution Checkpoint v1、Multi-Transaction Tail Recovery 与真实连续 Engine Restart

## 一、任务背景

请基于 OnlyAlpha 当前 `master` 分支的真实源码、测试、ADR、配置模型和产品调用链，完成：

```text
PR4.2
Execution Checkpoint v1
+
Multi-Transaction Tail Recovery
+
True Continuous Engine Restart
```

当前工程已经完成：

```text
OnlyEngine
→ OnlyBacktestRuntimeFactory
→ Runtime Persistence Store Factory
→ SQLite Execution Transaction Store
→ Prepared Transaction Commit
→ Ordered Manager Projection
→ Projection Ready
→ Durable Outbox
→ Runtime Recovery Hook
→ 独立 Engine A / Engine B Restart Test
```

但当前所谓 Engine Restart 仍然只支持：

```text
Store 中只有一笔未 Ready Transaction
execution_sequence == 1
ready_count == 0
从 Transaction Projection.before 手工重建 Before Authority
```

当前正式恢复边界依赖：

```python
bootstrap_execution_transaction_before()
```

并通过：

```python
_execution_replay_resume_after
```

根据成交时间跳过历史 Replay。

该实现只解决了：

> 第一笔正式事务在 Commit 后、首个 Projection 前中断时，新的 Engine 可以恢复这一笔事务。

它没有解决：

* Store 中已有多笔 Ready Transaction；
* Checkpoint 之后存在多笔 Ready Tail；
* Ready Tail 后还有 Unprojected Tail；
* Engine 重启后继续处理后续 Bar；
* Strategy 内部状态恢复；
* Factor / Indicator 滚动状态恢复；
* MarketData Cache 和聚合状态恢复；
* Virtual Broker 状态恢复；
* Open Order 恢复；
* Replay Cursor 恢复；
* Execution Dedup / Sequence Head 恢复；
* Account / Ledger Equity Timeline 连续性；
* 多次重启；
* Checkpoint 损坏和不完整写入；
* Checkpoint 与 Transaction Tail 的一致性验证。

本任务必须从根本上替换当前 sequence-one bootstrap，不得继续在旧实现上增加条件分支。

---

# 二、最终目标

完成后，OnlyAlpha 必须支持如下正式产品流程：

```text
Engine A
→ 从初始状态运行多个 Bar
→ 产生 Transaction 1
→ Transaction 1 Ready
→ 产生 Transaction 2
→ Transaction 2 Ready
→ 写入 Runtime Checkpoint
→ 继续处理后续 Bar
→ Transaction 3 Ready，但尚未进入新 Checkpoint
→ Transaction 4 Commit 成功，但 Projection 中断
→ Engine A 失败并关闭

Engine B
→ 使用相同产品配置
→ 使用相同 user_data
→ Factory 自动打开同一 Runtime Persistence Store
→ 自动加载最新完整 Checkpoint
→ 恢复所有 Checkpoint Participants
→ 重建 Checkpoint 后的 Ready Transaction Tail
→ 恢复未完成 Transaction Tail
→ 重建 Strategy / Factor / Indicator / Broker 状态
→ 恢复准确 MarketData Replay Cursor
→ 发布仍未完成的 Durable Outbox
→ 继续运行后续 Bar
→ 产生 Transaction 5、6……
→ 完成回测

Recovered Result
==
无故障 Baseline Result
```

必须证明：

```text
Engine B 不是只恢复历史结果
而是能够从 Checkpoint 后继续执行策略并产生新的正确交易
```

---

# 三、核心原则

## 1. 不考虑旧版本兼容

本任务不需要兼容：

* `runtime.execution_store` 旧配置；
* `OnlyExecutionStoreConfig`；
* `OnlyExecutionStoreBackend`；
* `OnlyExecutionTransactionStoreFactory`；
* `OnlySqliteExecutionTransactionStore`；
* `OnlyInMemoryExecutionTransactionStore`；
* `bootstrap_execution_transaction_before()`；
* `_execution_replay_resume_after`；
* sequence-one Bootstrap；
* 旧 SQLite Schema Version 1；
* 旧测试 Fixture；
* 旧文档示例。

如果新的架构已经超出“Execution Transaction Store”的职责，必须直接重新命名和重构，不得保留：

* Alias；
* Deprecated Wrapper；
* Compatibility Parser；
* 双配置字段；
* 旧类继承新类；
* 旧接口转发；
* 旧数据库自动迁移；
* 测试专用旧入口。

旧接口和旧实现应直接删除，并同步修改所有生产代码、测试、示例和文档。

## 2. 当前源码是唯一事实源

开始编码前必须重新审计当前 `master`。

判断优先级：

```text
当前生产源码
→ 当前测试
→ 已接受 ADR
→ 架构文档
→ README / Roadmap
→ 本提示词中的建议命名
```

本提示词给出的类名和文件名是目标结构建议。若当前工程结构不同，应按当前代码组织调整，但不得削弱任务目标。

## 3. 不使用对象序列化捷径

严禁：

* pickle；
* cloudpickle；
* dill；
* 直接序列化 Runtime；
* 直接序列化 Manager；
* 复制 `__dict__`；
* `deepcopy()` Runtime；
* Python 对象地址；
* 任意反射字段扫描；
* 将不可控 Mapping 当正式 Checkpoint Contract。

Checkpoint 必须使用：

* 强类型不可变 Snapshot；
* 显式 Schema Version；
* 显式 Codec；
* 规范化序列化；
* 稳定 Hash；
* 明确 Component Identity。

## 4. Checkpoint 不是 Transaction 的替代品

权威关系必须保持：

```text
Checkpoint
=
某个稳定 Bar Boundary 上的 Runtime Authority 快照

Transaction Store
=
Checkpoint 之后的 Durable Execution Tail

Outbox
=
Projection Ready Event Delivery Intent
```

恢复关系固定为：

```text
Latest Complete Checkpoint
+
Checkpoint 后的 Transaction Tail
+
确定性 Recovery Replay
=
当前 Runtime Authority
```

不能：

* 用 Checkpoint 覆盖或删除 Transaction；
* 用 Transaction 推测完整 Strategy 状态；
* 用 Result Artifact 代替 Checkpoint；
* 用 Outbox Event 重建 Manager；
* 用最新 Manager Snapshot 绕过 Transaction Tail；
* 把 Checkpoint 当作每笔 Transaction Commit。

---

# 四、编码前强制审计

开始修改前执行：

```bash
git status
git log -n 30 --oneline

rg "bootstrap_execution_transaction_before"
rg "_execution_replay_resume_after"
rg "execution_store"
rg "ExecutionTransactionStore"
rg "SqliteExecutionTransactionStore"
rg "RuntimeState"
rg "recover_unprojected"
rg "execution_recovery"
rg "replay_resume"
rg "checkpoint"
rg "snapshot"
rg "restore_execution_authority"
rg "OnlyBacktestRuntimeFactory"
rg "OnlyBacktestRunPlan"
rg "OnlyHistoricalReplayService"
rg "OnlyMarketDataProcessor"
rg "OnlyClusterManager"
rg "OnlyIndicatorPipeline"
rg "OnlyFactor"
rg "OnlyStrategy"
rg "OnlyDeterministicBrokerDriver"
rg "OnlyPluginResource"
rg "deduplicator"
rg "sequence_tracker"
rg "id_generator"
rg "equity_timeline"
rg "valuation"
rg "timer"
```

必须形成预实现审计文档：

```text
docs/reports/pr4_2_checkpoint_and_continuous_restart_pre_implementation_audit.md
```

审计必须回答：

1. 当前 Runtime 中所有可变状态的实际所有者；
2. 哪些状态可以由配置重建；
3. 哪些状态必须进入 Checkpoint；
4. 哪些状态可以由 Checkpoint 后的 MarketData Replay 重建；
5. 哪些状态可以由 Transaction Tail 重建；
6. 当前 Strategy 是否存在内部可变状态；
7. 当前 Factor / Indicator 如何保存滚动窗口；
8. 当前 Virtual Broker 保存哪些 Order、Account、Position、Sequence 和 Matching 状态；
9. 当前 Order ID、Broker Update ID、Trade ID 如何生成；
10. 当前 Historical Replay 的精确游标是什么；
11. 当前 Replay 是否支持从某个 MarketData Update 后恢复；
12. 当前一个 Bar 的完整处理边界在哪里；
13. 何时 Broker Inbound、EventBus 和 Outbox 才达到稳定状态；
14. 当前一个 Bar 中是否可能产生多笔 Transaction；
15. 当前 Transaction Ready 顺序是否一定形成连续前缀；
16. 当前 Store 是否允许 Ready 后再次出现更早的 Unready；
17. 当前 Cluster initialize/start 的副作用；
18. Strategy 在 Cluster 未 start 时能否执行恢复 Replay；
19. 当前 Result Collector 保存哪些运行中间状态；
20. 当前 Checkpoint 应在哪里捕获，才能保证 Bar Boundary 一致性。

审计完成后再开始编码。

---

# 五、总体架构决策

## 1. 将 Execution Store 升级为 Runtime Persistence Store

当前 Store 已经不再只保存 Execution Transaction。本任务加入 Runtime Checkpoint 后，必须使用准确命名。

建议删除：

```text
OnlyExecutionStoreConfig
OnlyExecutionStoreBackend
OnlyExecutionTransactionStoreFactory
OnlyInMemoryExecutionTransactionStore
OnlySqliteExecutionTransactionStore
```

替换为：

```python
class OnlyRuntimePersistenceBackend(StrEnum):
    MEMORY = "MEMORY"
    SQLITE = "SQLITE"
```

```python
@dataclass(frozen=True, slots=True)
class OnlyRuntimeCheckpointConfig:
    enabled: bool
    retain_last: int = 2
```

```python
@dataclass(frozen=True, slots=True)
class OnlyRuntimePersistenceConfig:
    backend: OnlyRuntimePersistenceBackend
    path: str | None
    checkpoint: OnlyRuntimeCheckpointConfig
```

正式配置改为：

```yaml
runtime:
  persistence:
    backend: SQLITE
    checkpoint:
      enabled: true
      retain_last: 2
```

普通不可恢复回测：

```yaml
runtime:
  persistence:
    backend: MEMORY
    checkpoint:
      enabled: false
```

约束：

```text
MEMORY
→ checkpoint.enabled 必须为 false

SQLITE
→ checkpoint.enabled 必须为 true
```

本阶段不保留“SQLite 只保存 Transaction 但不保存 Checkpoint”的模糊产品模式。

## 2. 统一数据库

Runtime Checkpoint、Execution Transaction 和 Outbox 必须使用同一 Runtime Persistence Store 和同一 SQLite 文件：

```text
user_data/state/engines/<engine-id>/runtimes/<runtime-id>/runtime.sqlite3
```

不得：

* 单独创建 checkpoint.sqlite3；
* Transaction 和 Checkpoint 使用两个 Factory；
* Checkpoint Store 与 Transaction Store 使用不同 Identity；
* Runtime 中打开第二个 SQLite Connection 作为另一个权威；
* Cluster 各自创建 Checkpoint 数据库。

## 3. Narrow Port 仍然保留

完整 Store 只存在于 Composition Root。

建议：

```python
class OnlyRuntimePersistenceStorePort(
    OnlyExecutionTransactionCommitPort,
    OnlyExecutionTransactionQueryPort,
    OnlyProjectionReadyExecutionQueryPort,
    OnlyExecutionProjectionStatePort,
    OnlyExecutionTransactionOutboxPort,
    OnlyRuntimeCheckpointWritePort,
    OnlyRuntimeCheckpointQueryPort,
    Protocol,
):
    def close(self) -> None: ...
```

业务组件只接收所需窄 Port：

```text
Coordinator
→ Transaction Commit / Query / Projection State

Result
→ Ready Query

Outbox Publisher
→ Outbox Port

Runtime Checkpoint Service
→ Checkpoint Write / Query

Runtime Recovery Orchestrator
→ Checkpoint Query + Transaction Query
```

Strategy、Factor、Indicator 和 Cluster Context 不得访问 Store。

---

# 六、Checkpoint v1 模型

## 1. Checkpoint Header

新增强类型模型：

```python
@dataclass(frozen=True, slots=True)
class OnlyRuntimeCheckpointHeader:
    runtime_id: OnlyRuntimeId
    checkpoint_sequence: int
    covered_execution_sequence: int
    checkpoint_schema_version: int
    created_at: OnlyTimestamp
    replay_cursor: OnlyBacktestReplayCursor
    config_fingerprint: str
    participant_registry_fingerprint: str
    aggregate_payload_hash: str
```

含义：

```text
checkpoint_sequence
→ Runtime Checkpoint 自身单调递增序列

covered_execution_sequence
→ Checkpoint 已完整包含的最高连续 Projection Ready Transaction Sequence

replay_cursor
→ Checkpoint 已完整处理并持久化的最后一个 MarketData Boundary
```

## 2. Replay Cursor

不得继续使用：

```text
Transaction.fact.ts_event
```

作为 Replay Resume Boundary。

新增正式模型，例如：

```python
@dataclass(frozen=True, slots=True)
class OnlyBacktestReplayCursor:
    source_id: OnlyMarketDataSourceId
    data_version: OnlyDataVersion
    last_update_id: OnlyMarketDataUpdateId | None
    last_source_sequence: int
    last_event_time: OnlyTimestamp | None
    processed_bar_count: int
```

如果支持多 Source，则使用：

```python
@dataclass(frozen=True, slots=True)
class OnlyBacktestReplayCursorSet:
    cursors: tuple[OnlyBacktestReplayCursor, ...]
```

恢复必须按：

```text
source_id
data_version
source_sequence
update_id
```

进行，而不是只比较时间。

必须验证：

* DataSource Identity 未改变；
* Data Version 未改变；
* Cursor 不超过配置结束范围；
* Source Sequence 单调；
* Update ID 与 Source Sequence 一致；
* Cursor 对应的 Bar 已完整完成 Checkpoint Barrier。

## 3. Checkpoint Component

定义稳定组件 Envelope：

```python
@dataclass(frozen=True, slots=True)
class OnlyRuntimeCheckpointComponent:
    component_id: str
    component_schema_version: int
    payload: str
    payload_hash: str
```

`payload` 必须是规范化编码后的文本或 bytes，不是任意 Python Mapping。

每个组件必须：

* 有稳定 `component_id`；
* 有独立 Schema Version；
* 有独立 Codec；
* 有稳定 Payload Hash；
* 捕获和恢复均使用强类型 Snapshot。

## 4. Checkpoint Aggregate

```python
@dataclass(frozen=True, slots=True)
class OnlyRuntimeCheckpoint:
    header: OnlyRuntimeCheckpointHeader
    components: tuple[OnlyRuntimeCheckpointComponent, ...]
```

要求：

* Component ID 唯一；
* Component 按 ID 稳定排序；
* Aggregate Hash 覆盖 Header 和全部 Component；
* 不允许未知必需组件；
* 不允许缺少必需组件；
* 不允许重复组件；
* 不允许 Component Hash 不匹配；
* 不允许非规范序列化。

---

# 七、Checkpoint Participant 架构

## 1. Participant Port

新增：

```python
class OnlyRuntimeCheckpointParticipant(Protocol):
    @property
    def checkpoint_component_id(self) -> str: ...

    @property
    def checkpoint_schema_version(self) -> int: ...

    def capture_checkpoint(
        self,
        context: OnlyCheckpointCaptureContext,
    ) -> OnlyRuntimeCheckpointComponent: ...

    def restore_checkpoint(
        self,
        component: OnlyRuntimeCheckpointComponent,
        context: OnlyCheckpointRestoreContext,
    ) -> None: ...
```

捕获与恢复顺序必须由正式 Registry 决定：

```python
class OnlyRuntimeCheckpointParticipantRegistry:
    ...
```

不得在 Runtime 中写几十个：

```python
if component_id == ...
elif component_id == ...
```

Participant Registry 必须：

* 注册时拒绝重复 ID；
* 固定 Capture Order；
* 固定 Restore Order；
* 生成 Registry Fingerprint；
* 验证 Checkpoint 中的参与者集合；
* 区分必需 Participant 和显式 Stateless Participant。

## 2. Stateless 声明

Strategy、Factor、Indicator 和 Plugin 不能因为“当前似乎没有状态”就被静默忽略。

必须显式实现二选一：

```text
CHECKPOINTABLE
STATELESS
```

例如：

```python
class OnlyCheckpointCapability(StrEnum):
    STATELESS = "STATELESS"
    CHECKPOINTABLE = "CHECKPOINTABLE"
```

任何没有声明能力的组件，在启用 SQLite Checkpoint 时必须装配失败。

禁止：

* 通过是否存在 `__dict__` 判断；
* 猜测对象是否无状态；
* 对未知插件静默跳过；
* 把无法恢复的插件标记成 Stateless。

---

# 八、Checkpoint 必须覆盖的状态

Checkpoint v1 是 Backtest 连续恢复 Checkpoint，不是仅保存 Account 和 Position。

必须覆盖所有影响后续确定性运行的状态。

## 1. Runtime 基础状态

至少包括：

* Clock 当前时间；
* 当前 TradingDay；
* Runtime Replay Cursor；
* Runtime Processing Sequence；
* Execution Processing Sequence；
* MarketData Processing Sequence；
* 当前 Valuation Version；
* Account Valuation Version；
* ID Generator Sequence Heads；
* Timer 注册和下一次触发时间；
* Runtime 级确定性计数器。

不应保存：

* Runtime Lifecycle 枚举本身；
* EventBus Thread；
* Python Lock；
* SQLite Connection；
* Logger；
* 临时 Callback；
* 文件句柄。

恢复后 Runtime 生命周期重新从：

```text
CREATED
→ INITIALIZING
→ RECOVERING
→ READY
```

推进。

## 2. Order

必须保存和恢复：

* 全部 Active Order；
* 全部 Terminal Order，如后续查询和去重需要；
* Order Version；
* Filled Quantity；
* Remaining Quantity；
* Venue Order ID；
* External Sequence；
* External Event ID Index；
* Trade ID Index；
* Venue Trade ID Index；
* Client Order ID Generator Head；
* Order ID Generator Head；
* Order Update Dedup State。

必须使用正式：

```text
OnlyOrderCheckpointSnapshot
```

不得把 `OnlyOrderManager._orders` 直接转成字典。

## 3. Position

必须保存和恢复：

* Active Position；
* Closed Position；
* Position Version；
* Position Side；
* Settlement Bucket；
* Average Open Price；
* Realized / Unrealized PnL；
* Fees；
* Position Trade Replay Index；
* Position Cycle；
* Position Creation Sequence。

## 4. Allocation

必须保存和恢复：

* Active Allocation；
* Closed Allocation；
* Cluster Attribution；
* Allocation Cycle；
* Trade Replay Index；
* Fees；
* Realized PnL；
* Cost Basis。

## 5. Reservations

必须保存：

* Account Cash Reservation；
* Strategy Cash Reservation；
* Position Reservation；
* Margin Reservation；
* Risk Reservation；
* Reservation Version；
* Consumed / Remaining Amount；
* Consumed / Remaining Quantity；
* Reservation State；
* Order Mapping Index。

即使当前正式 Generic T0 Transaction 尚未使用 Position/Margin Reservation Projection，Checkpoint 仍必须准确保存现有 Runtime 状态。

## 6. Account

必须保存：

* Account Snapshot；
* Cash Balance；
* Frozen Cash；
* Position Market Value；
* Realized / Unrealized PnL；
* Fees；
* Equity；
* Version；
* Account Status；
* Account Performance Timeline；
* Equity Point Sequence Head；
* Cash Reservation Manager State；
* Account Reconciliation State，如影响继续运行。

## 7. Strategy Ledger

必须保存：

* 每个 Cluster Ledger；
* Capital；
* Cash；
* Frozen Cash；
* Position Cost；
* Market Value；
* Realized / Unrealized PnL；
* Fees；
* Equity；
* Drawdown；
* Trade Count；
* Cash Reservations；
* Trade Fingerprints；
* Valuation Lines；
* Equity Timeline；
* Valuation Sequence Head；
* Ledger Version 和状态。

## 8. Risk

必须保存：

* Cluster Profile Binding；
* Risk Snapshot；
* Risk Version；
* Active Reservation；
* Released Reservation 去重信息；
* Order Risk Mapping；
* Account / Instrument Permissions；
* Exposure；
* Rule Sequence Head；
* Risk Event Dedup State。

Risk Rule 的静态配置可以由配置重建，但动态状态必须进入 Checkpoint。

## 9. Settlement、Fee、Margin

必须保存：

### Settlement

* Settlement Instruction Registry；
* Settlement Record；
* Current TradingDay；
* Pending Settlement；
* Settled Position / Cash；
* Record Sequence Head。

### Fee

* Fee Authority；
* Fee Record；
* Trade Fee Index；
* Accrual；
* Record Sequence Head。

### Margin

* Margin Account State；
* Margin Requirement；
* Margin Reservation；
* Position Margin；
* Margin Record Sequence；
* 动态 Risk / Margin 状态。

即使当前 Generic T0 正式事务不使用 Margin，Checkpoint Registry 也必须正确处理空状态，不得省略组件。

## 10. MarketData

必须保存：

* MarketData Cache；
* 每个 Instrument / BarType 的窗口；
* Deduplicator；
* Sequence Tracker；
* Gap Detector State；
* Last Processed Update；
* Aggregation Manager 未完成窗口；
* Derived Bar Aggregation State；
* Current Snapshot；
* Data Quality Head；
* Audit Sequence，如影响 Result。

不得仅保存最后一个 Bar 时间。

## 11. Indicator

必须保存：

* 每个 Indicator Instance Identity；
* Input Window；
* Internal Rolling State；
* Warmup Count；
* Last Value；
* Output Sequence；
* Parameter Fingerprint。

所有 Indicator 必须明确：

```text
STATELESS
或
CHECKPOINTABLE
```

## 12. Factor

必须保存：

* Factor Identity；
* Factor Version；
* Factor Internal State；
* Last Snapshot；
* Dependency State；
* Score State；
* Warmup State；
* Cross-Section Coordination State。

## 13. Strategy

必须保存：

* Strategy Identity；
* Strategy Schema Version；
* 用户定义的可变策略状态；
* 已处理 Bar Sequence；
* 自定义计数器；
* Pending Intent；
* 定时器状态；
* Strategy 自己声明的 Checkpoint Snapshot。

新增明确 Strategy Port，例如：

```python
class OnlyCheckpointableStrategy(Protocol):
    def checkpoint_state(self) -> OnlyStrategyCheckpointState: ...
    def restore_checkpoint_state(self, state: OnlyStrategyCheckpointState) -> None: ...
```

不得自动保存 Strategy 任意属性。

现有内建 Strategy 和测试 Strategy 必须全部：

* 实现 Checkpoint；
* 或明确声明 Stateless。

## 14. Virtual Broker

官方 Virtual Broker 必须成为正式 Checkpoint Participant。

至少保存：

* Broker Account；
* Broker Position；
* Accepted / Open Order；
* Pending Match Order；
* Matching Engine State；
* Next-Bar Queue；
* Broker Source Sequence；
* Update ID Sequence；
* Trade ID Sequence；
* Venue Order ID Sequence；
* Frozen Cash；
* Broker Fees；
* Slippage / Liquidity 模型动态状态；
* Deterministic Driver Cursor。

如果启用 SQLite Checkpoint，但 Broker Plugin 不支持 Checkpoint：

```text
Runtime Assembly 必须失败
```

不能退化为只恢复 Local Manager。

## 15. Result / Fact State

为保证恢复后 Result 与 Baseline 一致，必须保存或可确定性重建：

* Standard Facts 已完成前缀；
* Collector Sequence；
* Account / Cluster Timeline；
* Scenario Action Progress；
* Scenario Assertion 输入状态；
* Runtime Diagnostics 前缀；
* Determinism 相关计数器。

运行恢复诊断可以作为 Operational Metadata 排除出业务指纹，但不能删除业务 Fact。

---

# 九、Checkpoint Barrier

## 1. Checkpoint 只能在完整 Bar Boundary 创建

Checkpoint v1 固定采用：

> 每个完整处理完成的 Bar 创建一个 Checkpoint。

本阶段不要实现可配置的多 Bar 间隔。

原因：

* Strategy、Factor、Indicator 和 Cache 状态随每个 Bar 变化；
* 如果允许跨多个 Bar 不保存 Checkpoint，则必须额外实现 Durable Market Processing Journal；
* 当前任务优先保证正确性，不提前优化写入频率。

因此：

```text
SQLite + Checkpoint
→ 每个完整 Bar 必须持久化 Checkpoint
```

后续若需要降低频率，应单独设计 Durable Market Journal，不得在本任务中通过跳过状态解决。

## 2. 初始 Checkpoint

新 Runtime 第一次启动时，在处理任何 MarketData 前必须创建：

```text
checkpoint_sequence = 1
covered_execution_sequence = 0
replay_cursor = EMPTY
```

初始 Checkpoint 必须在以下状态完成后创建：

* Runtime 和 Plugin 已装配；
* Instrument 已注册；
* Cluster 已创建；
* Ledger 已创建；
* Risk Profile 已绑定；
* Strategy / Factor / Indicator 已初始化；
* Broker 已初始化；
* 尚未处理第一个 Bar；
* EventBus 已清空；
* Inbound Queue 为空。

这样任何 Transaction Tail 都必然存在一个可恢复 Checkpoint 前缀。

## 3. Bar 完成条件

只有以下全部满足，才能写入 Checkpoint：

```text
当前 Bar 的 MarketData Pipeline 完成
Indicator 完成
Factor 完成
Strategy Callback 完成
Order Command 完成
Virtual Broker Matching 完成
Broker Inbound 全部 Drain
Execution Transaction 全部达到 Ready 或明确失败
Execution Projection 无未完成任务
Event Buffer 已 Seal 或 Abort
EventBus 已 Drain
Broker Inbound Queue 为空
MarketData Inbound Queue 为空
Runtime 当前没有执行中的 Callback
Checkpoint Capture Registry 全部成功
```

正常运行下，如果存在 Unprojected Transaction：

```text
不允许创建 Checkpoint
Runtime 必须失败
```

Outbox 必须遵循当前产品语义：

* Projection Ready 与 Outbox Delivery 分离；
* 可以在 Checkpoint 后重试 Outbox；
* 但 Checkpoint Header 必须记录 Outbox Pending Count；
* Checkpoint 不能把 Pending Outbox 当成已发布。

## 4. Checkpoint 写入失败

Checkpoint 是连续恢复产品能力的一部分。

如果 Checkpoint 写入失败：

```text
Runtime 立即 FAILED
停止处理后续 Bar
不允许继续运行形成多个未 Checkpoint Bar
```

不得：

* 记录 Warning 后继续；
* 延迟到下一个 Bar 再尝试；
* 退化为 Memory；
* 关闭 Checkpoint；
* 忽略部分 Participant；
* 删除旧 Checkpoint。

旧的完整 Checkpoint 必须保持有效。

---

# 十、Checkpoint Store Schema

SQLite Schema Version 直接升级，不兼容 Version 1。

建议：

```text
runtime_store_schema_version = 2
```

旧 Version 1 数据库必须：

```text
RUNTIME_PERSISTENCE_SCHEMA_UNSUPPORTED
```

不得自动迁移。

## 1. Checkpoint Header Table

建议：

```sql
CREATE TABLE runtime_checkpoints (
    runtime_id TEXT NOT NULL,
    checkpoint_sequence INTEGER NOT NULL,
    covered_execution_sequence INTEGER NOT NULL,
    checkpoint_schema_version INTEGER NOT NULL,
    replay_cursor_payload TEXT NOT NULL,
    config_fingerprint TEXT NOT NULL,
    participant_registry_fingerprint TEXT NOT NULL,
    aggregate_payload_hash TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    PRIMARY KEY(runtime_id, checkpoint_sequence)
);
```

## 2. Checkpoint Component Table

```sql
CREATE TABLE runtime_checkpoint_components (
    runtime_id TEXT NOT NULL,
    checkpoint_sequence INTEGER NOT NULL,
    component_id TEXT NOT NULL,
    component_schema_version INTEGER NOT NULL,
    payload TEXT NOT NULL,
    payload_hash TEXT NOT NULL,
    PRIMARY KEY(runtime_id, checkpoint_sequence, component_id),
    FOREIGN KEY(runtime_id, checkpoint_sequence)
        REFERENCES runtime_checkpoints(runtime_id, checkpoint_sequence)
);
```

## 3. 原子写入

Checkpoint Header 和全部 Components 必须在同一个：

```sql
BEGIN IMMEDIATE
...
COMMIT
```

中完成。

写入顺序：

```text
验证 Barrier
→ Capture 全部 Participant 到内存中的不可变 Snapshot
→ 验证 Component Hash
→ 计算 Aggregate Hash
→ BEGIN IMMEDIATE
→ 写 Header
→ 写全部 Component
→ 验证 Component Count
→ COMMIT
```

禁止边 Capture Manager 边写 SQLite。

如果任何 Capture 失败：

```text
不开始数据库事务
```

如果数据库写入失败：

```text
ROLLBACK
旧 Checkpoint 保持完整
```

## 4. Retention

只在新 Checkpoint 成功提交后执行 Retention。

默认：

```text
保留最新 2 个完整 Checkpoint
```

Retention 失败：

* 不影响刚提交 Checkpoint 的完整性；
* 但必须记录明确 Diagnostic；
* 根据当前错误策略决定是否阻止继续运行；
* 默认应阻止继续运行，避免状态存储无限异常。

不得先删除旧 Checkpoint 再写新 Checkpoint。

---

# 十一、恢复生命周期

删除现有：

```python
bootstrap_execution_transaction_before()
```

删除：

```python
_execution_replay_resume_after
```

删除 Runtime Factory 中对旧 Bootstrap 的调用。

新增正式生命周期状态：

```text
CREATED
INITIALIZING
RECOVERING
READY
RUNNING
PAUSED
STOPPING
STOPPED
FAILED
CLOSED
```

建议恢复顺序：

```text
Runtime CREATED
→ Plugin initialize/connect
→ Cluster initialize
→ Runtime RECOVERING
→ 加载并验证最新完整 Checkpoint
→ 恢复所有 Checkpoint Participants
→ 验证 Checkpoint Authority
→ 分析 Checkpoint 后 Transaction Tail
→ 执行 Recovery Catch-up
→ 验证 Tail Authority
→ 创建恢复后的稳定 Checkpoint
→ Runtime READY
→ Plugin start
→ 发布 Pending Durable Outbox
→ Cluster start
→ Runtime RUNNING
→ 从恢复后的 Replay Cursor 继续正常运行
```

恢复失败：

```text
Runtime FAILED
Cluster 不得 start
RUNTIME_STARTED 不得发布
不得处理新 Bar
不得覆盖 Checkpoint
不得删除 Transaction
```

---

# 十二、Multi-Transaction Tail Recovery

## 1. Tail 定义

设：

```text
C = Checkpoint.covered_execution_sequence
```

查询：

```text
Transaction.execution_sequence > C
```

得到 Tail。

Tail 必须满足：

* Sequence 从 `C + 1` 开始；
* Sequence 连续；
* Runtime ID 一致；
* Payload Hash 有效；
* Projection Sequence 有效；
* Ready Transaction 必须形成前缀；
* Unready Transaction 必须形成后缀；
* 不允许 Unready 后出现 Ready；
* 不允许 Sequence Gap；
* 不允许重复 Sequence；
* 不允许 Checkpoint 覆盖不存在的 Transaction。

例如：

```text
Checkpoint C=10

允许：
11 Ready
12 Ready
13 Unready
14 Unready

禁止：
11 Unready
12 Ready
```

## 2. Tail 分类

新增正式模型：

```python
@dataclass(frozen=True, slots=True)
class OnlyExecutionTransactionTail:
    checkpoint_sequence: int
    ready_prefix: tuple[OnlyCommittedExecutionTransaction, ...]
    unprojected_suffix: tuple[OnlyCommittedExecutionTransaction, ...]
```

新增：

```text
OnlyExecutionTransactionTailAnalyzer
```

职责仅包括：

* 查询；
* 排序；
* 连续性验证；
* Ready Prefix 验证；
* Hash 验证；
* 生成 Tail Plan。

不执行 Manager Mutation。

## 3. Ready Tail 不能被忽略

Checkpoint 后的 Ready Transaction 虽然 Store 中已经 Ready，但其 Manager After State 已随 Engine A 内存丢失。

Engine B 必须重新建立这些状态。

不能因为：

```text
transaction.projection_ready == True
```

就跳过 Projection。

新增：

```text
OnlyExecutionReadyTailRehydrationService
```

或者统一的：

```text
OnlyExecutionTailReplayService
```

它必须：

* 从 Checkpoint Authority 开始；
* 按 Sequence 顺序；
* 按 Projection Order 顺序；
* 使用真实 Manager Target；
* 不修改 Transaction Ready State；
* 不创建新 Outbox；
* 不生成新 Event ID；
* 重建 Applied Projection Ledger；
* 验证 Expected Hash；
* 验证 Result Hash；
* 遇到冲突立即失败。

Ready Tail Rehydration 不是普通 Coordinator Duplicate 路径。

## 4. Unprojected Tail

Ready Prefix 重建完成后，再调用正式 Coordinator 恢复 Unprojected Suffix。

顺序：

```text
Checkpoint Authority
→ Rehydrate Ready Transaction C+1
→ Rehydrate Ready Transaction C+2
→ Recover Unready Transaction C+3
→ Recover Unready Transaction C+4
```

每一笔必须以前一笔 Result Authority 为下一笔 Expected Authority。

不得：

* 并行 Projection；
* 跳过失败 Sequence；
* 先恢复后面的 Transaction；
* 把全部 Transaction 合并成一个 Snapshot；
* 修改原 Transaction ID；
* 修改原 Event ID；
* 修改原 Execution Sequence。

## 5. Applied Projection Ledger

Applied Projection Ledger 仍然可以是可重建 Index，不必成为独立持久权威。

恢复规则：

```text
Checkpoint 覆盖范围内
→ 不要求保存全部历史 Applied Ledger

Checkpoint 后 Ready Tail
→ Rehydration 时重新写 Applied Ledger

Unprojected Tail
→ Coordinator 正常写 Applied Ledger
```

Checkpoint 可以保存：

```text
covered_projection_sequence_head
```

但不能把 Applied Ledger 当作 Manager Authority。

---

# 十三、Recovery Catch-up Replay

仅恢复 Execution Manager 不足以恢复 Strategy、Indicator、Factor、Broker 和 MarketData State。

因此必须实现正式：

```text
OnlyBacktestRecoveryReplayService
```

## 1. 恢复 Replay 范围

恢复开始位置：

```text
Checkpoint.replay_cursor 后的第一个 MarketData Update
```

恢复上界至少覆盖：

```text
Checkpoint 后 Transaction Tail 的最大 Broker/Trade Event 所属 MarketData Boundary
```

如果 Checkpoint 后没有 Transaction Tail：

```text
不执行 Catch-up
正常运行从 Cursor 后继续
```

## 2. Recovery Replay Mode

新增明确模式：

```python
class OnlyBacktestReplayMode(StrEnum):
    NORMAL = "NORMAL"
    RECOVERY = "RECOVERY"
```

Recovery 模式必须：

* 执行 MarketData Pipeline；
* 执行 Indicator；
* 执行 Factor；
* 执行 Strategy；
* 执行 Order Command；
* 执行 Virtual Broker Matching；
* 执行 Broker Inbound；
* 使用已有 Transaction Tail；
* 恢复 Manager Authority；
* 重建 Strategy 和 Broker 状态；
* 不向外部重复发布历史 Direct Event；
* 不创建重复 Transaction；
* 不生成新的随机 Identity；
* 不将历史恢复动作计入新的业务交易；
* 不产生第二份 Result Fact。

禁止通过以下方式恢复：

```text
只把 Replay Cursor 设置到最后一笔 Transaction 后
直接跳过中间 Bar
```

## 3. Existing Transaction Resolution

Recovery Replay 中，如果生成的 Trade 对应 Store 已有 Transaction：

### 已 Ready

```text
验证 Prepared Payload 与 Existing Transaction 一致
→ 使用 Existing Transaction
→ Rehydrate Projection
→ 不 Commit 新 Transaction
→ 不创建新 Outbox
```

### 未 Ready

```text
验证 Prepared Payload 一致
→ 使用 Existing Transaction
→ Coordinator 恢复 Projection
```

### 不存在

如果该 MarketData Boundary 位于已知 Tail Recovery 上界内，但生成了 Store 中不存在的 Transaction：

```text
RECOVERY_TRANSACTION_MISSING
```

如果已越过 Tail Recovery 上界并进入正常继续运行：

```text
允许 Commit 新 Transaction
```

### Payload 不一致

```text
RECOVERY_DETERMINISM_CONFLICT
```

必须失败，不能使用旧 Transaction 强行覆盖新 Strategy 行为。

## 4. 非 Transaction Order 状态

当前 Accepted、Rejected、Cancelled 等尚未事务化。

Recovery Replay 必须通过确定性重放重建这些状态。

这也是 Recovery Replay 必须执行：

* Strategy；
* Order；
* Virtual Broker；
* Broker Update；

而不能只重放 Transaction Projection 的原因。

恢复过程中生成的 Direct Event：

* 可以进入内部恢复 Fact Buffer；
* 不得重新发送给外部 EventBus Consumer；
* 必须保持最终 Result 与 Baseline 一致；
* 必须避免重复标准 Fact。

---

# 十四、Checkpoint 恢复顺序

Participant Restore 必须使用固定依赖顺序。

建议：

```text
1. Runtime Clock / Replay Cursor
2. Market Reference Runtime State
3. Account
4. Account Reservation
5. Position
6. Allocation
7. Position Reservation
8. Strategy Ledger
9. Settlement
10. Fee
11. Margin
12. Risk
13. Execution Dedup / Sequence / ID Generators
14. MarketData Processor / Cache / Aggregation
15. Indicator
16. Factor
17. Strategy
18. Virtual Broker
19. Timer
20. Collector / Fact State
```

恢复后必须执行完整一致性检查：

* Account Equity；
* Account Cash；
* Position Market Value；
* Ledger Equity；
* Allocation 与 Position；
* Reservation；
* Risk Exposure；
* Settlement；
* Margin；
* Fee；
* Timeline Head；
* ID Sequence；
* Broker / Local Account；
* Broker / Local Open Order；
* Replay Cursor；
* Strategy / Indicator / Factor Schema。

Checkpoint 恢复完成但不一致：

```text
CHECKPOINT_AUTHORITY_MISMATCH
```

不得继续 Tail Recovery。

---

# 十五、Plugin Checkpoint Capability

## 1. Plugin Descriptor

扩展正式 Plugin Capability：

```text
supports_runtime_checkpoint
checkpoint_schema_version
```

SQLite Persistence 装配时必须校验：

```text
DataSource
Broker
Strategy
Factor
Indicator
```

当前 Backtest 所有参与者是否支持：

* CHECKPOINTABLE；
* 或 STATELESS。

## 2. Virtual Broker

官方 Virtual Broker 必须实现：

```text
OnlyCheckpointableBrokerComponent
```

恢复后必须保证：

* 同一 Open Order；
* 同一 Venue Order ID；
* 同一 Broker Sequence；
* 同一 Trade ID；
* 同一 Account；
* 同一 Position；
* 同一 Frozen Cash；
* 同一 Pending Match Queue。

不得在 Engine B 中创建一个空 Broker 后只恢复 Local Runtime。

## 3. DataSource

Historical DataSource 可以声明 Stateless，但必须验证：

* Source ID；
* Data Version；
* Coverage；
* Replay Cursor；
* 数据内容 Fingerprint，如当前已有。

DataSource 不能因为状态不持久化而改变历史数据。

---

# 十六、Runtime Persistence Factory

删除旧：

```text
OnlyExecutionTransactionStoreFactory
```

新增：

```text
OnlyRuntimePersistenceStoreFactory
```

请求建议：

```python
@dataclass(frozen=True, slots=True)
class OnlyRuntimePersistenceStoreCreateRequest:
    engine_id: OnlyEngineId
    runtime_id: OnlyRuntimeId
    runtime_mode: OnlyRuntimeMode
    config: OnlyRuntimePersistenceConfig
    state_root: Path
    config_fingerprint: str
    participant_registry_fingerprint: str
    base_currency: str
    account_id: OnlyAccountId
    market_profile_id: str
```

Factory：

```text
MEMORY
→ OnlyInMemoryRuntimePersistenceStore

SQLITE
→ OnlySqliteRuntimePersistenceStore
```

SQLite 文件：

```text
runtime.sqlite3
```

Factory 是唯一创建位置。

Runtime 不解析配置，不创建目录，不选择 Backend。

Validate 不得：

* 创建 state 目录；
* 创建数据库；
* 创建 metadata；
* 加载 Checkpoint；
* 修改旧数据库。

---

# 十七、Runtime Composition Root

`OnlyBacktestRuntimeFactory.create()` 新顺序建议：

```text
解析并验证 Product Config
→ 创建 DataSource
→ 创建 Broker
→ 创建 Runtime Persistence Store
→ 创建 Cluster
→ 创建 Runtime
→ 注册 Instrument
→ 注册 Cluster
→ 注册 Checkpoint Participants
→ 将 Persistence Store 所有权移交 Runtime
→ 返回 Runtime
```

不得在 Factory 中直接恢复 Manager。

恢复必须由 Runtime 生命周期中的正式：

```text
OnlyRuntimeRecoveryOrchestrator
```

完成。

Factory 不允许：

* 检查 Transaction 数量后直接 restore；
* 调用 Manager restore；
* 分析 Ready Tail；
* 调用 `recover_unprojected()`；
* 设置 Replay Cursor。

---

# 十八、Runtime Recovery Orchestrator

新增：

```text
OnlyRuntimeRecoveryOrchestrator
```

职责：

```text
load checkpoint
→ validate checkpoint
→ restore participants
→ analyze transaction tail
→ execute recovery catch-up
→ rehydrate ready tail
→ recover unprojected tail
→ validate authority
→ create post-recovery checkpoint
→ return typed diagnostic
```

建议状态：

```python
class OnlyRuntimeRecoveryStatus(StrEnum):
    NEW_RUNTIME_INITIALIZED = "NEW_RUNTIME_INITIALIZED"
    RESTORED = "RESTORED"
    RESTORED_AND_REHYDRATED = "RESTORED_AND_REHYDRATED"
    RESTORED_AND_RECOVERED = "RESTORED_AND_RECOVERED"
    CHECKPOINT_NOT_FOUND = "CHECKPOINT_NOT_FOUND"
    CHECKPOINT_CORRUPT = "CHECKPOINT_CORRUPT"
    CHECKPOINT_SCHEMA_UNSUPPORTED = "CHECKPOINT_SCHEMA_UNSUPPORTED"
    CHECKPOINT_COMPONENT_MISSING = "CHECKPOINT_COMPONENT_MISSING"
    CHECKPOINT_COMPONENT_UNSUPPORTED = "CHECKPOINT_COMPONENT_UNSUPPORTED"
    CHECKPOINT_AUTHORITY_MISMATCH = "CHECKPOINT_AUTHORITY_MISMATCH"
    TRANSACTION_TAIL_GAP = "TRANSACTION_TAIL_GAP"
    TRANSACTION_TAIL_ORDER_INVALID = "TRANSACTION_TAIL_ORDER_INVALID"
    READY_TAIL_REHYDRATION_FAILED = "READY_TAIL_REHYDRATION_FAILED"
    UNPROJECTED_TAIL_RECOVERY_FAILED = "UNPROJECTED_TAIL_RECOVERY_FAILED"
    RECOVERY_DETERMINISM_CONFLICT = "RECOVERY_DETERMINISM_CONFLICT"
    STORE_FAILURE = "STORE_FAILURE"
```

Diagnostic 至少包含：

* Checkpoint Sequence；
* Covered Execution Sequence；
* Replay Cursor；
* Restored Participant Count；
* Ready Tail Count；
* Rehydrated Transaction Count；
* Unprojected Tail Count；
* Recovered Transaction Count；
* Final Ready Sequence；
* Pending Outbox Count；
* Catch-up Bar Count；
* Failed Component；
* Failed Transaction；
* Error；
* Authority Hash Before / After。

Runtime 只依赖 Orchestrator，不再直接调用旧的单一 `OnlyExecutionRecoveryService`。

窄的 Execution Recovery Service 可以继续作为 Orchestrator 内部组件，但 Runtime 生命周期不再直接调用它。

---

# 十九、真实连续 Engine Restart 测试

新增正式产品集成测试，建议：

```text
tests/integration/test_engine_continuous_restart.py
tests/integration/test_engine_multi_transaction_tail_recovery.py
tests/integration/test_engine_checkpoint_corruption.py
tests/integration/test_engine_checkpoint_open_order_restart.py
tests/integration/test_engine_stateful_strategy_restart.py
```

所有集成测试必须经过：

```text
OnlyEngine
→ Config Parser
→ Runtime Planner
→ Runtime Assembler
→ Runtime Persistence Factory
→ OnlyBacktestRuntime
```

不得直接构造 Runtime。

## 1. 主场景

Engine A：

```text
处理 Bar 1
→ Initial Checkpoint

处理 Bar 2
→ Order A
→ Transaction 1 Ready
→ Checkpoint covers 1

处理 Bar 3
→ Order B
→ Transaction 2 Ready
→ Checkpoint covers 2

处理 Bar 4
→ Order C
→ Transaction 3 Ready
→ 尚未写入 Checkpoint

同一 Bar 或后续恢复边界
→ Order D
→ Transaction 4 Commit
→ Projection 中断
→ Engine A FAILED
```

Engine B：

```text
加载 Checkpoint covers 2
→ Recovery Replay Bar 4
→ Rehydrate Transaction 3
→ Recover Transaction 4
→ 创建新 Checkpoint covers 4
→ 发布 Pending Outbox
→ 继续 Bar 5、6、7
→ 产生 Transaction 5、6
→ 正常完成
```

Baseline Engine：

```text
相同配置
相同行情
无故障
完整运行
```

比较：

* Final Account；
* Final Position；
* Final Allocation；
* Final Ledger；
* Orders；
* Ready Transactions；
* Transaction ID；
* Execution Sequence；
* Event ID；
* Fees；
* Settlement；
* Risk；
* Equity Timeline；
* Strategy State；
* Indicator State；
* Factor State；
* Broker Account；
* Broker Position；
* Open Order；
* Facts；
* Reconciliation；
* Determinism Fingerprint；
* Result Fingerprint。

## 2. 多 Ready Tail

测试：

```text
Checkpoint covers 2
Store:
3 Ready
4 Ready
5 Ready
Engine Crash
```

Engine B 必须：

```text
从 Checkpoint Authority
依次 Rehydrate 3、4、5
```

不能因为它们已经 Ready 就跳过。

## 3. Ready + Unprojected Tail

测试：

```text
Checkpoint covers 2
3 Ready
4 Ready
5 Unready
6 Unready
```

恢复顺序必须严格为：

```text
Rehydrate 3
Rehydrate 4
Recover 5
Recover 6
```

## 4. Sequence Gap

测试：

```text
Checkpoint covers 2
Store 中存在 3、5
```

必须失败：

```text
TRANSACTION_TAIL_GAP
```

## 5. Ready/Unready 顺序异常

测试：

```text
3 Unready
4 Ready
```

必须失败。

## 6. Stateful Strategy

创建正式测试 Strategy：

```text
连续处理 N 个 Bar 后才提交 Order
内部保存 counter / rolling decision state
```

在 N 之前重启。

Engine B 继续后：

* Order 产生 Bar 与 Baseline 相同；
* Order ID 相同；
* Transaction ID 相同；
* 不提前、不延后、不重复交易。

不得通过测试外部变量保存 Counter。

## 7. Indicator / Factor

使用真正滚动 Indicator，例如 MACD、EMA 或窗口 Factor。

重启后：

* Indicator Window；
* Warmup；
* Last Value；
* Factor Snapshot；
* Strategy Decision；

必须与 Baseline 相同。

## 8. Open Order Restart

Engine A：

```text
提交 Limit Order
Broker Accepted
尚未成交
Checkpoint
Crash
```

Engine B：

```text
恢复 Local Order
恢复 Reservation
恢复 Risk
恢复 Virtual Broker Open Order
继续后续 Bar
在与 Baseline 相同 Bar 成交
```

验证：

* Venue Order ID 相同；
* Broker Sequence 连续；
* Frozen Cash 相同；
* 只成交一次。

## 9. Checkpoint Write Failure

注入：

* Component Capture Failure；
* Header Insert Failure；
* Component Insert Failure；
* Commit Failure；
* Retention Failure。

验证：

* Runtime FAILED；
* 不处理后续 Bar；
* 旧 Checkpoint 可用；
* 新 Checkpoint 不可见；
* Transaction 不被删除。

## 10. Checkpoint Corruption

覆盖：

* Header 缺失；
* Component 缺失；
* Component 重复；
* Component Hash 错误；
* Aggregate Hash 错误；
* Replay Cursor 损坏；
* Participant Registry Fingerprint 不匹配；
* Config Fingerprint 不匹配；
* Component Schema Unsupported；
* SQLite Schema Version 1。

全部必须 fail fast。

## 11. Multiple Restart

测试：

```text
Engine A
→ Checkpoint 1
→ Crash

Engine B
→ Restore
→ Continue
→ Checkpoint 2
→ Crash

Engine C
→ Restore
→ Continue
→ Complete
```

最终与一次无故障 Baseline 完全一致。

---

# 二十、故障注入要求

故障注入只能存在于测试代码。

允许：

```text
OnlyFaultInjectingRuntimePersistenceStoreFactory
OnlyFailOnceCheckpointParticipant
OnlyFailOnceProjectionTarget
OnlyFailOnceRuntimePersistenceStore
```

禁止在生产配置加入：

```text
fail_after_checkpoint
fail_after_commit
fail_before_projection
test_mode
simulate_crash
```

测试 Factory 必须实现正式 Port，通过 Composition Root 注入。

不得：

* monkeypatch Runtime 私有字段；
* 修改 `_services`；
* 修改 `_state`；
* 修改 `_clusters`；
* 从 Engine A 复制对象到 Engine B；
* 在 Engine B 中手工 restore Manager；
* 手工调用 Recovery Orchestrator；
* 手工设置 Replay Cursor。

---

# 二十一、删除要求

本任务必须删除：

```text
bootstrap_execution_transaction_before()
_execution_replay_resume_after
sequence-one transaction-before bootstrap
旧 Engine Restart 特例
旧 Execution Store Config
旧 Execution Store Factory
旧 SqliteExecutionTransactionStore 命名
旧 execution.sqlite3 默认路径
旧 Schema Version 1 支持
旧配置解析兼容
```

现有测试应：

* 重写为新 Checkpoint / Tail Recovery 测试；
* 不保留旧行为测试；
* 不为了保留测试而增加旧接口；
* 不使用别名让旧测试继续通过。

若旧测试验证的底层 Store Contract 仍有价值，应改写为新 Runtime Persistence Store Contract。

---

# 二十二、架构门禁

新增架构测试，至少验证：

1. 正式配置中不存在 `execution_store`；
2. 不存在 `OnlyExecutionStoreConfig`；
3. 不存在 `OnlyExecutionTransactionStoreFactory`；
4. 不存在 `bootstrap_execution_transaction_before`；
5. 不存在 `_execution_replay_resume_after`；
6. Runtime Factory 不调用 Manager restore；
7. Runtime Factory 不分析 Transaction Tail；
8. Runtime Factory 只创建 Persistence Store；
9. Runtime Recovery 只通过 Orchestrator；
10. Strategy Context 不暴露 Persistence Store；
11. Cluster 不访问 SQLite；
12. Result 不直接读取 Checkpoint；
13. Checkpoint Codec 不使用 pickle；
14. Checkpoint Capture 不访问对象 `__dict__`；
15. 每个 Participant ID 唯一；
16. SQLite Checkpoint 装配要求全部 Participant 声明 Capability；
17. Virtual Broker 必须声明 Checkpoint Capability；
18. Runtime Checkpoint Store 与 Transaction Store 是同一实例；
19. Checkpoint 和 Transaction 使用相同 Runtime Identity；
20. Validate 阶段不创建数据库；
21. Checkpoint Header 和 Component 在同一事务写入；
22. Checkpoint 失败不删除旧 Checkpoint；
23. Product Restart Test 不访问 Runtime 私有字段；
24. Product Restart Test 不手工调用 Recovery；
25. Product Restart Test 不直接构造 Runtime；
26. Product Restart Test 不复用 Engine A 对象；
27. Product Restart Test 不复制 Manager；
28. Recovery 不根据 Transaction 时间直接跳过 Replay；
29. Ready Tail 必须经过 Rehydration；
30. Unprojected Tail 必须经过 Coordinator；
31. Recovery Replay 不创建重复 Transaction；
32. Recovery Replay 不重复发布历史 Direct Event；
33. Checkpoint 每个完整 Bar 创建；
34. Checkpoint 失败阻止后续 Bar；
35. Store Schema Version 1 明确失败；
36. 不存在旧接口 Alias 或 Deprecated Wrapper。

---

# 二十三、建议目录结构

根据当前项目结构调整，建议：

```text
src/onlyalpha/runtime/persistence/
├── config.py
├── store.py
├── sqlite_store.py
├── factory.py
├── metadata.py
└── errors.py

src/onlyalpha/runtime/checkpoint/
├── model.py
├── codec.py
├── participant.py
├── registry.py
├── service.py
├── barrier.py
└── diagnostics.py

src/onlyalpha/runtime/recovery/
├── orchestrator.py
├── tail.py
├── ready_tail_rehydration.py
└── backtest_recovery_replay.py

src/onlyalpha/order/checkpoint.py
src/onlyalpha/position/checkpoint.py
src/onlyalpha/account/checkpoint.py
src/onlyalpha/strategy_ledger/checkpoint.py
src/onlyalpha/risk/checkpoint.py
src/onlyalpha/settlement/checkpoint.py
src/onlyalpha/fee/checkpoint.py
src/onlyalpha/margin/checkpoint.py
src/onlyalpha/market_data/checkpoint.py
src/onlyalpha/indicator/checkpoint.py
src/onlyalpha/factor/checkpoint.py
src/onlyalpha/strategy/checkpoint.py
```

不要为了形式拆成大量空文件。应以明确模块职责为准。

---

# 二十四、实施顺序

## 第 1 步：预实现审计

完成完整 State Inventory、Bar Boundary 和 Replay 语义分析。

## 第 2 步：Persistence 配置重构

删除旧 `execution_store`，建立 `runtime.persistence`。

同步修改：

* Config；
* Normalized Payload；
* Fingerprint；
* Fixture；
* Example；
* README；
* Scenario；
* Factory。

## 第 3 步：Runtime Persistence Store

重命名并重构 Store：

* Transaction；
* Ready Query；
* Outbox；
* Checkpoint；
* Metadata；
* Schema Version 2；
* Runtime-owned close。

## 第 4 步：Checkpoint Model 和 Codec

实现：

* Header；
* Cursor；
* Component；
* Aggregate；
* Hash；
* Canonical Codec。

## 第 5 步：Participant Registry

实现注册、排序、Fingerprint、Capability 和完整性验证。

## 第 6 步：核心 Manager Checkpoint

依次实现：

* Account；
* Order；
* Position；
* Allocation；
* Reservation；
* Ledger；
* Risk；
* Settlement；
* Fee；
* Margin；
* Valuation；
* Dedup / Sequence / ID Generator。

每完成一个组件，增加：

```text
capture
→ mutate
→ restore
→ equality
```

Contract Test。

## 第 7 步：Market / Strategy / Broker Checkpoint

实现：

* Clock；
* Replay Cursor；
* MarketData；
* Cache；
* Aggregation；
* Indicator；
* Factor；
* Strategy；
* Timer；
* Virtual Broker；
* Result Collector。

## 第 8 步：Checkpoint Barrier

在正式 Backtest 单 Bar 产品链中加入原子 Barrier。

禁止测试单独调用。

## 第 9 步：Tail Analyzer

实现连续性、Ready Prefix 和 Hash 验证。

## 第 10 步：Ready Tail Rehydration

通过真实 Manager Target 重建 Ready Tail。

## 第 11 步：Unprojected Tail Recovery

复用正式 Coordinator，但删除 sequence-one 限制。

## 第 12 步：Recovery Replay

实现恢复模式、已有 Transaction Resolution 和 Replay Cursor。

## 第 13 步：Runtime Lifecycle

加入 RECOVERING，接入 Orchestrator。

## 第 14 步：真实 Engine Restart

完成 Engine A / Engine B / Baseline 和 Multiple Restart。

## 第 15 步：删除旧实现

彻底删除旧 Bootstrap、旧 Store 命名、旧配置和旧测试。

## 第 16 步：文档和 ADR

新增 ADR，并更新所有产品文档。

---

# 二十五、文档要求

更新：

```text
README.md
docs/architecture.md
docs/backtest.md
docs/execution_runtime_recovery.md
docs/roadmap.md
```

新增 ADR，建议：

```text
docs/adr/0044-runtime-checkpoint-and-continuous-engine-restart.md
```

ADR 必须说明：

1. 为什么 sequence-one Bootstrap 被删除；
2. Checkpoint、Transaction Tail 和 Outbox 的权威关系；
3. 为什么 Checkpoint 采用每 Bar Barrier；
4. 为什么不使用 Transaction 时间作为 Replay Cursor；
5. 为什么需要 Ready Tail Rehydration；
6. 为什么需要 Recovery Replay；
7. 为什么 Strategy、Indicator、Factor 和 Broker 必须参与；
8. 为什么 Store 重命名为 Runtime Persistence Store；
9. Schema Version 2；
10. 不兼容 Version 1；
11. Participant Capability；
12. Checkpoint 原子写入；
13. Checkpoint Retention；
14. Runtime RECOVERING 生命周期；
15. Direct Event 在 Recovery Replay 中的处理；
16. 当前仍不包含的业务范围。

---

# 二十六、本任务不扩展的业务范围

本任务只解决恢复基础设施，不顺带迁移新的交易业务。

不实现：

* Partial Fill 正式 Transaction；
* Multi-Fill Accounting；
* SELL/CLOSE 正式 Transaction；
* Futures Transaction；
* Margin Transaction；
* Non-Trade Transaction；
* Paper Runtime；
* Live Runtime；
* Full Broker Reconciliation；
* Exactly-once Outbox；
* Schema Migration；
* 分布式 Checkpoint；
* Remote Store；
* Web。

但 Checkpoint 必须能够保存这些 Manager 当前已有的空状态或旧路径状态，不能破坏现有 Backtest。

---

# 二十七、测试命令

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
uv run pytest tests/integration/test_engine_continuous_restart.py -q
uv run pytest tests/integration/test_engine_multi_transaction_tail_recovery.py -q
uv run pytest tests/integration/test_engine_checkpoint_corruption.py -q
uv run pytest tests/integration/test_engine_checkpoint_open_order_restart.py -q
uv run pytest tests/integration/test_engine_stateful_strategy_restart.py -q
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

不得伪造未执行测试。

---

# 二十八、完成标准

只有全部满足以下条件，才能声明 PR4.2 完成：

1. 旧 `runtime.execution_store` 已删除；
2. 新 `runtime.persistence` 已成为正式配置；
3. 旧 Execution Store Factory 已删除；
4. Runtime Persistence Store 是唯一产品 Store；
5. SQLite 文件改为 `runtime.sqlite3`；
6. Schema Version 升级；
7. Version 1 明确不兼容；
8. Checkpoint Header 已实现；
9. Checkpoint Component 已实现；
10. Replay Cursor 已实现；
11. Component Hash 已实现；
12. Aggregate Hash 已实现；
13. Checkpoint 原子写入；
14. Checkpoint Retention 安全；
15. 初始 Checkpoint 自动创建；
16. 每个完整 Bar 自动创建 Checkpoint；
17. Checkpoint 写入失败阻止后续运行；
18. Checkpoint Participant Registry 已实现；
19. Participant Registry Fingerprint 已实现；
20. 未声明 Capability 的组件装配失败；
21. Account Checkpoint 完成；
22. Order Checkpoint 完成；
23. Position Checkpoint 完成；
24. Allocation Checkpoint 完成；
25. Reservation Checkpoint 完成；
26. Strategy Ledger Checkpoint 完成；
27. Risk Checkpoint 完成；
28. Settlement Checkpoint 完成；
29. Fee Checkpoint 完成；
30. Margin Checkpoint 完成；
31. Valuation Timeline Checkpoint 完成；
32. MarketData Checkpoint 完成；
33. Aggregation Checkpoint 完成；
34. Indicator Checkpoint 完成；
35. Factor Checkpoint 完成；
36. Strategy Checkpoint 完成；
37. Virtual Broker Checkpoint 完成；
38. Timer Checkpoint 完成；
39. Result / Fact State Checkpoint 完成；
40. `bootstrap_execution_transaction_before()` 已删除；
41. `_execution_replay_resume_after` 已删除；
42. sequence-one 限制已删除；
43. Ready Tail Analyzer 已实现；
44. Ready Tail Rehydration 已实现；
45. Multi-Unprojected Tail Recovery 已实现；
46. Tail Sequence Gap 明确失败；
47. Ready/Unready 顺序异常明确失败；
48. Runtime RECOVERING 状态已实现；
49. Recovery Replay 已实现；
50. Recovery Replay 使用 MarketData Cursor；
51. Recovery Replay 不使用 Transaction 时间跳过历史；
52. Recovery Replay 不创建重复 Transaction；
53. Recovery Replay 不重复发布历史 Direct Event；
54. Engine B 能继续处理新 Bar；
55. Engine B 能产生新 Transaction；
56. 新 Transaction Sequence 接续旧 Tail；
57. 新 ID Generator 不回退；
58. Open Order 可恢复；
59. Virtual Broker 状态可恢复；
60. Stateful Strategy 可恢复；
61. Indicator / Factor 状态可恢复；
62. 多 Ready Tail 可重建；
63. Ready + Unprojected Tail 可恢复；
64. Multiple Restart 可运行；
65. Checkpoint Corruption 全部 fail fast；
66. Engine B 与 Baseline Final Authority 一致；
67. Engine B 与 Baseline Strategy Decision 一致；
68. Engine B 与 Baseline Transaction ID 一致；
69. Engine B 与 Baseline Event ID 一致；
70. Engine B 与 Baseline Result Fingerprint 一致；
71. Product Restart Test 不修改 Runtime 私有字段；
72. 不保留旧接口 Alias；
73. 不保留旧配置兼容；
74. 不保留旧 SQLite 自动迁移；
75. 不存在生产故障开关；
76. 文档准确描述当前边界；
77. Ruff、Mypy、Pytest 和架构门禁全部通过。

---

# 二十九、禁止的实现

以下任一情况视为任务失败：

```text
保留 bootstrap_execution_transaction_before
只把 sequence-one 改成 for 循环
继续使用 Transaction.ts_event 作为 Replay Cursor
只恢复 Account / Position / Ledger
不恢复 Strategy
不恢复 Indicator / Factor
不恢复 Virtual Broker
Ready Transaction 因为已 Ready 而跳过 Projection
直接把 Manager.__dict__ 写入 SQLite
使用 pickle
复制 Engine A Runtime 到 Engine B
测试手工 restore Manager
测试修改 runtime._services
测试修改 runtime._state
测试修改 cluster_manager._clusters
测试手工设置 Replay Cursor
测试直接调用 Recovery Orchestrator
测试直接构造 Runtime
生产配置加入故障开关
Checkpoint 和 Transaction 使用两个 SQLite 文件
Checkpoint 写到 Run Artifact 目录
Checkpoint 路径使用随机 Run ID
Checkpoint 写入失败后继续处理 Bar
Checkpoint 删除旧数据后再写新数据
Checkpoint 只保存最新 Manager Snapshot，不验证 Transaction Tail
恢复时删除旧 Transaction
恢复时修改 Transaction ID
恢复时修改 Event ID
恢复时重新 Commit 已有 Ready Transaction
恢复时重复发布历史 Direct Event
恢复时跳过 Strategy Callback
恢复时把所有 Transaction 合并成一个 Snapshot
未知 Participant 静默忽略
无法恢复的 Plugin 静默标记 Stateless
SQLite Version 1 自动迁移
为了旧测试保留旧接口
为了示例保留旧配置
为了减少改动引入 Adapter 包装旧架构
```

---

# 三十、最终交付报告

完成后输出结构化报告。

## 1. 修改前问题

说明：

* sequence-one Bootstrap；
* Replay Cursor 缺陷；
* Ready Tail 缺陷；
* Strategy / Broker 状态缺失；
* Store 命名和职责问题。

## 2. 新架构

说明：

```text
Checkpoint
Transaction Tail
Recovery Replay
Outbox
```

四者关系。

## 3. 配置和 Store

说明：

* 新配置；
* 新路径；
* Schema Version；
* Metadata；
* 删除的旧配置和旧类。

## 4. Participant Inventory

逐项列出：

* Component ID；
* Schema Version；
* Snapshot 类型；
* Capture；
* Restore；
* Capability。

## 5. Checkpoint Barrier

说明一个 Bar 如何达到稳定 Checkpoint Boundary。

## 6. Tail Recovery

说明：

* Ready Prefix；
* Unprojected Suffix；
* Rehydration；
* Coordinator Recovery；
* Conflict Handling。

## 7. Recovery Replay

说明：

* Replay Cursor；
* Recovery Mode；
* Existing Transaction Resolution；
* Direct Event Policy；
* Strategy / Broker State 重建。

## 8. Engine Restart

详细说明：

```text
Engine A
Checkpoint
Ready Tail
Unprojected Tail
Engine B
继续运行
Baseline
```

## 9. 删除内容

列出所有删除的：

* 类；
* 方法；
* 配置；
* 测试；
* 文档；
* Alias；
* Bootstrap 特例。

## 10. 测试结果

给出真实命令和结果。

## 11. 剩余边界

必须明确仍未完成：

* Partial/Multi Fill 正式 Transaction；
* SELL/CLOSE；
* Futures/Margin Transaction；
* Non-Trade Transaction；
* Paper/Live Recovery；
* Exactly-once Outbox；
* Schema Migration；
* 分布式 Checkpoint。

---

# 三十一、最终架构结论

完成后，OnlyAlpha 必须从：

```text
一笔 sequence-one Transaction
通过 Projection.before 临时恢复
```

升级为：

```text
OnlyEngine
→ Runtime Persistence Factory
→ Latest Complete Runtime Checkpoint
→ Restore All Checkpoint Participants
→ Analyze Multi-Transaction Tail
→ Rehydrate Ready Tail
→ Recover Unprojected Tail
→ Recovery MarketData Replay
→ Restore Strategy / Indicator / Factor / Broker
→ Durable Outbox Delivery
→ Continue Normal Replay
→ Commit New Transactions
→ Baseline-equivalent Result
```

最终必须证明：

> 新 Engine 不复用旧 Runtime、不访问私有字段、不依赖单笔事务特例，仅凭同一产品配置、同一 user_data、最新完整 Checkpoint 和持久 Transaction Tail，就能恢复完整 Backtest 执行上下文，继续处理后续行情，并产生与无故障运行完全一致的后续策略决策、交易和结果。
