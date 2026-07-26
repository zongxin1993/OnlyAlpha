# OnlyAlpha：实现 Execution 原子提交与 Durable Committed Journal

## 任务目标

重新阅读当前 OnlyAlpha `master` 源码、测试、ADR 和插件边界，重构 Execution 成交提交链，解决当前存在的根本问题：

```text
Manager 状态已经修改
→ Event 已经提交
→ Committed Execution Fact 才开始构建和写入内存 Journal
```

当前顺序会导致：

* Fact 构建失败时，本地会计状态已经发生变化；
* Journal Append 失败时，Event 可能已经发布；
* 异常只能标记为 `PARTIAL_MUTATION` 并进入 Reconciliation；
* 进程退出后，Committed Execution Journal 全部丢失；
* 无法可靠恢复 Execution Sequence、Trade/Update 幂等状态；
* 无法证明一笔成交是“全部提交”或“完全未提交”。

本任务必须建立清晰的原子提交边界，使 `OnlyCommittedExecutionFact` 成为 Runtime 已成功提交成交的持久权威。

不考虑历史兼容。

不得为了旧测试、旧示例、旧构造函数或旧接口保留错误设计。

---

# 一、第一性原则

## 1. Committed Execution 的定义

Broker Trade Update 只是外部输入。

只有以下内容全部成功后，才能产生 Committed Execution：

```text
Order Mutation
Position Mutation
Allocation Mutation
Settlement Mutation
Margin Mutation
Fee Mutation
Account Mutation
Strategy Ledger Mutation
Risk / Reservation Mutation
Invariant Validation
```

`OnlyCommittedExecutionFact` 表达的是：

> Runtime 已接受并完整提交的一笔本地成交事务。

它不是：

* Broker Fill 副本；
* EventBus Event；
* Result Collector 临时投影；
* Manager Snapshot 拼接结果；
* 异常补偿记录。

## 2. 原子性

一笔成交必须满足：

```text
全部提交
或
完全不对外可见
```

禁止继续接受：

```text
部分 Manager 已修改
Journal 未写入
Event 已发布
然后进入 Reconciliation
```

作为正常事务模型。

## 3. Durable Journal 是提交权威

成功成交必须先进入持久 Journal，才能被视为已提交。

必须保证：

```text
Journal 中存在 Fact
⇒ 该成交可以恢复、重放和审计

Journal 中不存在 Fact
⇒ 该成交不能被外部观察为已成功提交
```

## 4. Event 不是事务权威

Event 只能在事实提交后发布。

正确顺序：

```text
验证
→ 准备事务
→ 构建 Fact
→ 持久提交
→ 发布 Event
```

禁止：

```text
先发布 Event
→ 再构建或持久化 Fact
```

Event 发布失败不得造成已提交成交丢失，应允许通过 Outbox 重试。

---

# 二、修改前审计

修改前必须执行：

```bash
git status
git log -n 10 --oneline

rg "OnlyExecutionProcessor"
rg "OnlyCommittedExecutionJournal"
rg "OnlyCommittedExecutionFact"
rg "OnlyCommittedExecutionBuilder"
rg "PARTIAL_MUTATION"
rg "committed_execution_journal"
rg "events.commit"
rg "events.rollback"
rg "OnlyExecutionUpdateDeduplicator"
rg "OnlyExecutionSequenceTracker"
rg "OnlySqliteStorage"
rg "OnlyStorage"
rg "checkpoint"
rg "replay"
rg "reconciliation"
```

形成简短审计结论：

1. 当前每个 Manager 的修改顺序；
2. 哪些 Manager 支持 prepare/commit/rollback；
3. 哪些 Manager 直接原地修改；
4. EventBus 的 begin/commit/rollback 实际语义；
5. Fact 当前何时构建；
6. Journal 当前何时 append；
7. Deduplicator 和 SequenceTracker 当前何时推进；
8. 异常后哪些状态无法回滚；
9. 当前 Storage 能力为何不足以承载顺序 Journal；
10. 哪些 Result、Analytics、测试依赖内存 Journal。

以当前源码为唯一事实源，不要机械套用旧路径。

---

# 三、目标架构

实现以下边界：

```text
Broker Update
    │
    ▼
OnlyExecutionProcessor
    │
    ├── Validate / Deduplicate / Resolve Scope
    │
    ▼
OnlyExecutionTransactionBuilder
    │
    ├── 生成所有领域 Mutation Plan
    ├── 生成 Committed Execution Fact
    └── 不修改任何正式 Manager 状态
    │
    ▼
OnlyExecutionCommitCoordinator
    │
    ├── Durable Journal Append
    ├── Apply Prepared Mutations
    ├── Persist Checkpoint
    └── Persist Outbox Events
    │
    ▼
OnlyExecutionOutboxPublisher
    │
    └── 发布 Event，可失败重试
```

职责必须明确。

---

# 四、核心模块设计

## 4.1 OnlyExecutionTransaction

新增不可变事务对象，例如：

```python
@dataclass(frozen=True, slots=True)
class OnlyExecutionTransaction:
    transaction_id: str
    runtime_id: OnlyRuntimeId
    gateway_id: OnlyBrokerGatewayId
    account_id: OnlyAccountId
    cluster_id: OnlyClusterId
    broker_update_id: OnlyBrokerUpdateId
    trade_id: OnlyTradeId

    committed_fact: OnlyCommittedExecutionFact

    order_mutation: OnlyPreparedOrderMutation
    position_mutation: OnlyPreparedPositionMutation
    allocation_mutation: OnlyPreparedAllocationMutation
    settlement_mutation: OnlyPreparedSettlementMutation | None
    margin_mutation: OnlyPreparedMarginMutation | None
    fee_mutations: tuple[OnlyPreparedFeeMutation, ...]
    account_mutation: OnlyPreparedAccountMutation
    ledger_mutations: tuple[OnlyPreparedLedgerMutation, ...]
    reservation_mutations: tuple[OnlyPreparedReservationMutation, ...]
    risk_mutations: tuple[OnlyPreparedRiskMutation, ...]

    outbox_events: tuple[OnlyEvent, ...]
```

具体字段应依据现有领域对象调整，但必须满足：

* immutable；
* 可序列化；
* 确定性；
* 不持有 Manager；
* 不持有可调用闭包；
* 不依赖具体 Broker 插件；
* 包含恢复所需的稳定身份；
* 能在正式状态修改前完成完整校验。

不要把事务对象实现为：

```python
list[Callable[[], None]]
```

这无法持久化、审计和恢复。

---

## 4.2 Prepare 与 Apply 分离

为涉及成交的 Manager 建立明确的 Prepare/Apply 边界。

推荐形式：

```python
mutation = manager.prepare_xxx(command, current_snapshot)
manager.apply_prepared(mutation)
```

Prepare 必须：

* 执行业务校验；
* 计算 before/after；
* 不修改 Manager；
* 返回不可变 Mutation；
* 包含期望的当前版本；
* 包含目标版本；
* 可确定性序列化；
* 可重复校验。

Apply 必须：

* 验证当前版本等于 Mutation 的 expected version；
* 只应用已准备的结果；
* 不重新计算费用、市场规则、PnL 或保证金；
* 不调用 Broker；
* 不产生新的业务决策。

优先覆盖成交事务实际涉及的 Manager，不要为整个工程建立过度抽象的通用事务框架。

---

## 4.3 OnlyExecutionTransactionBuilder

新增明确的 Builder/Assembler：

```python
class OnlyExecutionTransactionBuilder:
    def prepare(
        self,
        update: OnlyBrokerTradeUpdate,
        context: OnlyExecutionProcessingContext,
    ) -> OnlyExecutionTransaction:
        ...
```

职责：

1. 验证 Broker Update；
2. 解析 Order、Cluster、Position Scope；
3. 解析 Market Trade Instruction；
4. 解析 Fee Instruction；
5. 准备 Order Mutation；
6. 准备 Position 和 Allocation Mutation；
7. 准备 Settlement、Margin、Fee Mutation；
8. 准备 Account 和 Ledger Mutation；
9. 准备 Reservation 和 Risk Mutation；
10. 检查跨模块不变量；
11. 构建完整 `OnlyCommittedExecutionFact`；
12. 构建 Outbox Events。

Builder 不得：

* 修改 Manager；
* Append Journal；
* 发布 Event；
* 推进 Deduplicator；
* 推进 SequenceTracker；
* 请求外部 Broker；
* 使用测试专用分支。

---

## 4.4 OnlyCommittedExecutionJournalPort

将当前具体内存类替换为正式 Port：

```python
class OnlyCommittedExecutionJournalPort(Protocol):
    def next_sequence(self, runtime_id: OnlyRuntimeId) -> int:
        ...

    def append_transaction(
        self,
        transaction: OnlyDurableExecutionCommit,
    ) -> OnlyJournalAppendResult:
        ...

    def get_by_trade(
        self,
        runtime_id: OnlyRuntimeId,
        gateway_id: OnlyBrokerGatewayId,
        trade_id: OnlyTradeId,
    ) -> OnlyCommittedExecutionFact | None:
        ...

    def get_by_update(
        self,
        runtime_id: OnlyRuntimeId,
        gateway_id: OnlyBrokerGatewayId,
        update_id: OnlyBrokerUpdateId,
    ) -> OnlyCommittedExecutionFact | None:
        ...

    def records(
        self,
        runtime_id: OnlyRuntimeId,
        *,
        after_sequence: int = 0,
    ) -> tuple[OnlyCommittedExecutionFact, ...]:
        ...
```

接口可根据实现调整，但必须包含：

* 连续 Execution Sequence；
* Runtime Scope；
* Gateway Scope；
* Account Scope；
* Trade 幂等；
* Broker Update 幂等；
* 顺序读取；
* 重启恢复；
* 原子 Append。

幂等键至少包含：

```text
runtime_id
gateway_id
account_id
trade_id
```

以及：

```text
runtime_id
gateway_id
account_id
broker_update_id
```

不要继续忽略 `account_id`。

---

## 4.5 Durable 实现

新增专用 SQLite 实现，例如：

```text
src/onlyalpha/execution/journal/
    port.py
    models.py
    memory.py
    sqlite.py
    codec.py
```

不要将现有 namespace/key/blob KV 直接包装成 Journal。

SQLite Journal 应使用正式表结构，例如：

```sql
execution_commits
-----------------
runtime_id
execution_sequence
transaction_id
gateway_id
account_id
trade_id
broker_update_id
fact_schema_version
fact_payload
fact_hash
committed_at
PRIMARY KEY(runtime_id, execution_sequence)
UNIQUE(runtime_id, gateway_id, account_id, trade_id)
UNIQUE(runtime_id, gateway_id, account_id, broker_update_id)
UNIQUE(transaction_id)
```

Outbox 使用独立表：

```sql
execution_outbox
----------------
runtime_id
execution_sequence
event_sequence
event_type
event_payload
published
published_at
attempt_count
last_error
PRIMARY KEY(runtime_id, execution_sequence, event_sequence)
```

Checkpoint 可以使用独立表：

```sql
runtime_execution_checkpoint
----------------------------
runtime_id
last_execution_sequence
state_version
checkpoint_payload
checkpoint_hash
updated_at
PRIMARY KEY(runtime_id)
```

要求：

* SQLite transaction 内一次性写入 Fact、Outbox 和 Checkpoint；
* 唯一约束负责幂等；
* 不能依赖“先查询、再插入”保证唯一性；
* payload 使用稳定版本化序列化；
* Decimal、Identifier、Timestamp 和 Enum 不得丢失类型语义；
* 禁止 pickle；
* 禁止存储测试对象；
* schema_version 必须明确。

---

# 五、提交协调器

新增：

```python
class OnlyExecutionCommitCoordinator:
    def commit(
        self,
        transaction: OnlyExecutionTransaction,
    ) -> OnlyExecutionCommitResult:
        ...
```

建议执行顺序：

```text
1. 检查 Journal 是否已有 Trade/Update
2. 检查所有 Prepared Mutation 的 expected version
3. 在内存中验证完整事务不变量
4. 开启 Durable Journal 事务
5. 写入 Committed Fact
6. 写入 Outbox
7. 写入 Runtime Checkpoint
8. 提交 Durable Transaction
9. Apply Prepared Manager Mutations
10. 推进 Deduplicator 和 SequenceTracker
11. 将结果标记为 COMMITTED
12. 尝试发布 Outbox Event
```

但必须认真处理步骤 8 与步骤 9 之间的崩溃问题。

推荐采用以下权威模型：

> Durable Journal 是源事实，Manager 是可恢复投影。

因此：

* Durable Commit 成功后，即使 Manager Apply 中断，重启时也必须可从 Journal 重放；
* Manager Apply 必须幂等；
* Manager 当前版本必须记录在 Checkpoint；
* 重放时跳过已应用 Execution Sequence；
* Event 发布由 Outbox 驱动，不参与成交原子提交成败。

不要尝试在多个普通 Python Manager 和 SQLite 之间伪造不可实现的分布式 ACID。

---

# 六、ExecutionProcessor 重构

重构后 `OnlyExecutionProcessor` 只负责流程编排：

```text
Validate Input
→ Check Durable Idempotency
→ Prepare Transaction
→ Commit Transaction
→ Return Processing Result
```

它不得继续内联处理：

* 费用明细构造；
* Ledger Entry 构造；
* Account Cash Flow 计算；
* Margin 数值推导；
* Settlement 推导；
* Committed Fact 字段拼接；
* Journal 数据库逻辑；
* Outbox 发布细节。

删除当前：

```text
Event commit 后再 Build Fact
Event commit 后再 Append Journal
异常后调用 Event rollback 假装回滚已提交 Event
```

的流程。

`PARTIAL_MUTATION` 不得再作为正常成交事务失败结果。

确有无法自动恢复的投影异常时，使用明确状态，例如：

```text
COMMITTED_REPLAY_REQUIRED
```

它表示：

* Durable Fact 已成功；
* Runtime Projection 未完整追上；
* 可通过 Replay 修复；
* 不等同于成交未提交。

---

# 七、Event Outbox

实现 Runtime-owned Outbox Publisher：

```python
class OnlyExecutionOutboxPublisher:
    def publish_pending(self, runtime_id: OnlyRuntimeId) -> OnlyOutboxPublishResult:
        ...
```

要求：

* 只读取已持久提交的 Outbox；
* Event 发布成功后幂等标记；
* 发布失败保留 Pending；
* 重启后继续发布；
* 同一 Event 不因重试导致核心状态重复修改；
* Event 订阅方不得承担成交记账；
* Event 顺序与 Execution Sequence 稳定一致。

EventBus 仍然是运行时分发设施，不升级为数据库。

---

# 八、恢复与重放

新增最小可用恢复服务：

```python
class OnlyExecutionRecoveryService:
    def recover(
        self,
        runtime_id: OnlyRuntimeId,
        checkpoint: OnlyRuntimeExecutionCheckpoint | None,
    ) -> OnlyExecutionRecoveryResult:
        ...
```

恢复过程：

```text
加载 Checkpoint
→ 读取 checkpoint 后的 Committed Facts
→ 按 execution_sequence 重放 Prepared/Committed Mutation
→ 恢复 Manager Projection
→ 恢复 Deduplicator
→ 恢复 SequenceTracker
→ 恢复 Journal next sequence
→ 发布 Pending Outbox
```

如果当前 Fact 不足以完全重建 Manager 状态，应：

1. 扩充 Fact 或 Checkpoint；
2. 明确哪些状态由 Checkpoint 提供；
3. 不得静默查询 Broker 猜测本地历史；
4. 不得依赖旧内存对象仍存在。

本任务至少要实现 Execution 主链的恢复，不要求一次完成整个 Runtime 所有模块的长期运行恢复。

---

# 九、内存实现

保留一个正式的：

```text
OnlyInMemoryCommittedExecutionJournal
```

用于快速 Backtest 和单元测试，但它必须实现同一个 Journal Port，具备：

* 与 SQLite 相同的幂等规则；
* 与 SQLite 相同的 Sequence 规则；
* 与 SQLite 相同的 Codec 验证；
* 与 SQLite 相同的 Append Result 语义。

它不是旧类兼容层。

旧的：

```text
OnlyCommittedExecutionJournal
```

如果职责和命名不再准确，应直接删除或重命名，不保留 Alias。

---

# 十、Composition Root

由 Runtime Assembler 根据配置注入 Journal 实现。

建议配置：

```yaml
execution_journal:
  backend: MEMORY
```

或：

```yaml
execution_journal:
  backend: SQLITE
  path: runtime/execution-journal.sqlite3
```

规则：

* Backtest 默认可使用 MEMORY；
* Paper/Live 将来必须使用 Durable Backend；
* backend 选择只发生在 Composition Root；
* ExecutionProcessor 不识别 SQLite；
* Domain 不依赖 Storage；
* 插件不能访问 Journal；
* Result Collector 只依赖 Journal Query Port。

不要为了配置兼容保留旧字段。

---

# 十一、Result 与 Analytics

Result Collector 必须继续只从 Committed Journal 读取成功成交。

要求：

* 不读取未提交 Transaction；
* 不从 Broker Fill 重建成交；
* 不从 Manager 最终状态猜测历史；
* 重启后结果与未重启运行一致；
* SQLite Journal 和 Memory Journal 产生相同结果指纹；
* Outbox 发布状态不影响交易结果；
* Recovery 不产生重复 Execution Result。

---

# 十二、失败语义

必须明确区分：

```text
REJECTED
    输入或业务校验失败，未提交

DUPLICATE
    Trade/Update 已存在，未重复提交

COMMITTED
    Durable Fact 已提交，Projection 已应用

COMMITTED_REPLAY_REQUIRED
    Durable Fact 已提交，但内存 Projection 需要恢复

FAILED_BEFORE_COMMIT
    Durable Journal 未写入，成交未提交

RECONCILIATION_REQUIRED
    Broker 与本地事实存在业务差异，不是数据库事务失败
```

禁止继续用一个宽泛的：

```text
PARTIAL_MUTATION
```

混合表达所有失败。

---

# 十三、删除旧结构

本任务不考虑兼容性。

完成后删除：

* Event Commit 后构建 Fact 的流程；
* Event Commit 后 Append Journal 的流程；
* 旧内存 Journal 具体依赖；
* Processor 内直接实例化 `OnlyCommittedExecutionBuilder`；
* Processor 内直接操作 Journal List；
* 旧 Trade/Update 幂等 Set；
* 测试专用 Journal 分支；
* 旧构造函数兼容参数；
* 旧 Alias、Wrapper 和 Re-export；
* 为旧示例保留的 fallback；
* 无法恢复的闭包式 Mutation；
* 仅靠 `PARTIAL_MUTATION` 掩盖事务不完整的逻辑。

更新所有生产调用方、测试、Scenario、示例和文档。

---

# 十四、测试要求

## 1. Journal Contract

Memory 和 SQLite 实现运行同一套 Contract Test：

* 顺序 Append；
* Sequence 连续；
* Trade 幂等；
* Update 幂等；
* Account Scope；
* Runtime Scope；
* Gateway Scope；
* 冲突 Fact 拒绝；
* 重启后 Sequence 恢复；
* 重启后幂等恢复；
* Payload Hash 校验；
* Schema Version 校验。

## 2. 原子提交

注入失败点：

```text
Fact 构建失败
Journal Append 失败
Checkpoint 写入失败
Outbox 写入失败
Manager Apply 失败
Event 发布失败
```

验证：

* Fact 构建失败：Journal 无记录，Manager 无变化，Event 无发布；
* Durable Transaction 失败：Journal、Outbox、Checkpoint 均无部分记录；
* Manager Apply 失败：Journal 已有 Fact，状态为 Replay Required；
* Event 发布失败：成交仍为 Committed，Outbox 保持 Pending；
* 重启后 Replay 能恢复 Manager；
* 重试不重复记账。

## 3. Crash Recovery

至少模拟：

```text
Durable Commit 前崩溃
Durable Commit 后、Manager Apply 前崩溃
Manager Apply 中途崩溃
Manager Apply 后、Event Publish 前崩溃
Event Publish 后、Outbox Mark 前崩溃
```

重启后验证：

* 每笔成交只出现一次；
* Account、Position、Ledger、Fee 状态正确；
* Execution Sequence 连续；
* Event 最终发布；
* Result Fingerprint 稳定。

## 4. Multi-Cluster

验证两个 Cluster：

* 每笔 Fact 进入正确 Cluster；
* Journal 幂等包含 Account/Cluster 作用域；
* Recovery 不串 Ledger；
* Runtime Reconciliation 仍匹配；
* 注册顺序不影响结果。

## 5. Fee / Margin / Settlement

验证恢复后：

```text
Committed Fee
= Account Fee
= Ledger Fee
= FeeManager Records

Committed Margin Delta
= Account Margin
= MarginManager State

Committed Settlement
= SettlementManager State
```

## 6. 架构门禁

增加静态门禁：

* ExecutionProcessor 不导入 SQLite 实现；
* Domain 不依赖 Journal Infrastructure；
* Broker 插件不访问 Committed Journal；
* Result Collector 不访问 Broker Gateway；
* Event Handler 不修改核心成交状态；
* Processor 不在 Event Commit 后构建 Fact；
* Processor 不直接构造具体 Journal。

---

# 十五、Scenario

新增正式产品场景：

```text
Config
→ Engine
→ Runtime
→ Broker Fill
→ Prepare Transaction
→ Durable Commit
→ Manager Projection
→ Outbox Event
→ Result
→ Shutdown
→ Restart
→ Recovery
→ Result Comparison
```

至少覆盖：

1. 单笔成交正常提交；
2. 部分成交多次提交；
3. 重复 Broker Update；
4. Journal 写入失败；
5. Event 发布失败；
6. Durable Commit 后崩溃恢复；
7. 两个 Cluster 同一标的；
8. Fee、Margin、Settlement 恢复；
9. 重启前后 Result Fingerprint 一致；
10. Memory 与 SQLite Backend 结果一致。

---

# 十六、文档

新增 ADR：

```text
Durable Committed Execution as Runtime Transaction Authority
```

ADR 必须说明：

* 为什么 Broker Update 不是本地成交权威；
* 为什么 EventBus 不是事务日志；
* 为什么 Durable Journal 是提交权威；
* 为什么 Manager 是可恢复 Projection；
* 为什么不尝试跨 Python 内存和 SQLite 实现伪分布式 ACID；
* Outbox 的职责；
* Checkpoint 与 Replay 的职责；
* Backtest、Paper、Live 的 Journal Backend 策略。

更新：

* README；
* AGENTS；
* Execution 组件文档；
* Storage 组件文档；
* Runtime 生命周期文档；
* Result/Recovery 文档。

不要创建与源码重复的超长设计文档。

---

# 十七、实施顺序

严格按以下顺序实施：

```text
1. 审计当前 Execution Mutation 和失败边界
2. 定义 Transaction、Prepared Mutation 和 Commit Result
3. 定义 Journal Port、Codec 和持久模型
4. 实现 Memory Journal Contract
5. 实现 SQLite Durable Journal
6. 实现 Outbox 和 Checkpoint
7. 实现 Commit Coordinator
8. 重构 ExecutionProcessor
9. 实现 Recovery Service
10. 迁移 Result Collector
11. 重写测试与 Scenario
12. 删除旧 Journal 和兼容接口
13. 更新 ADR 与文档
14. 执行完整工程门禁
```

不要一开始大范围重构所有 Manager。

先覆盖真实成交事务所需最小边界，再逐步迁移。

---

# 十八、验收标准

任务只有满足以下条件才算完成。

## 提交正确性

* Fact 在 Event 发布前已经 Durable Commit；
* 未写入 Journal 的成交不可被视为成功；
* Journal 中的成交可以重放；
* Manager Apply 幂等；
* Event 发布失败不丢成交；
* 重启不重复记账；
* Trade/Update/Account Scope 幂等完整；
* Execution Sequence 重启后连续。

## 架构

* ExecutionProcessor 只负责流程编排；
* Transaction Builder 不修改状态；
* Commit Coordinator 不计算业务规则；
* Journal 不依赖 Manager；
* EventBus 不承担交易状态迁移；
* Broker 插件不知道 Committed Journal；
* Result 只读取成功提交的事实；
* 不存在新旧 Journal 双写。

## 持久化

* SQLite 写入 Fact、Outbox、Checkpoint 为一个数据库事务；
* 唯一约束负责幂等；
* 使用版本化稳定 Codec；
* 不使用 pickle；
* 重启恢复通过正式测试。

## 清理

* 删除旧 `OnlyCommittedExecutionJournal` 具体接口或将其彻底替换；
* 删除 Event Commit 后 Build/Append Fact；
* 删除旧 `PARTIAL_MUTATION` 通用补救语义；
* 删除兼容 Alias、Wrapper 和 Fallback；
* 测试和示例全部使用正式接口。

## 工程门禁

至少执行并记录：

```text
ruff check .
ruff format --check .

mypy src/onlyalpha
mypy Virtual Broker
mypy Tushare
mypy MiniQMT

Core tests
Virtual Broker tests
Tushare offline tests
MiniQMT offline tests
Integration tests
Scenario tests
Conformance tests
Integration demo tests

Wheel / sdist build
Twine check
Clean install
Entry Point smoke
```

无法执行的外部网络、真实 MiniQMT 或平台测试必须明确说明，不得声称通过。

---

# 十九、禁止事项

禁止：

1. 只给现有内存 Journal 增加一次 `storage.put()`。
2. 将整个 Transaction pickle 后写入数据库。
3. 使用闭包列表模拟持久 Mutation。
4. 先修改 Manager，再尝试写 Journal。
5. 先发布 Event，再写 Journal。
6. 用 Event Replay 代替 Committed Execution Replay。
7. 用 Broker 查询结果替代本地 Journal。
8. Manager Apply 失败后删除已经 Durable Commit 的 Fact。
9. 用 `PARTIAL_MUTATION` 掩盖所有失败。
10. 为旧测试保留旧 Journal 接口。
11. 新旧 Journal 双写。
12. Memory 和 SQLite 使用不同幂等规则。
13. 在 ExecutionProcessor 中写 SQL。
14. 让插件访问 Runtime Journal。
15. 构建一个与当前业务无关的通用分布式事务框架。
16. 只增加测试，不改变当前错误提交顺序。

---

# 二十、最终交付报告

完成后输出：

## 1. 修改前问题

列出当前 Event、Fact、Journal、Manager 和异常顺序。

## 2. 新提交模型

说明：

```text
Prepare
→ Durable Commit
→ Projection Apply
→ Outbox Publish
```

## 3. 模块边界

列出 Transaction Builder、Commit Coordinator、Journal、Outbox、Checkpoint、Recovery 的职责。

## 4. 持久模型

说明 SQLite 表、唯一键、Sequence、Codec 和事务边界。

## 5. 恢复语义

说明每个崩溃点如何恢复。

## 6. 删除内容

列出删除的旧接口、兼容层和错误流程。

## 7. 测试结果

提供真实命令和结果。

## 8. 未完成能力

明确说明本任务不自动完成：

```text
完整 Runtime 全状态恢复
Paper Runtime
Live Runtime
Broker 启动全量对账
Futures Daily MTM
分布式 Journal
多节点一致性
```

不得把这些描述为已完成。

---

# 最终目标

重构完成后，OnlyAlpha 必须满足：

```text
Broker Update
→ Prepare Deterministic Transaction
→ Build Complete Committed Fact
→ Durable Journal Commit
→ Apply Recoverable Runtime Projections
→ Persist Outbox
→ Publish Event
```

并满足：

```text
Committed Journal 是成交权威
Manager 是可恢复投影
Event 是已提交事实通知
Broker Update 是外部输入
```

优先解决真实事务一致性、崩溃恢复和事实权威问题。不要为了抽象完整、减少改动、保持旧测试或保留旧接口而偏离这一目标。
