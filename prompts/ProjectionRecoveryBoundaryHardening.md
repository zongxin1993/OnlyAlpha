# OnlyAlpha PR3.1：Projection Recovery Boundary Hardening

## 一、任务目标

以 OnlyAlpha 当前 `master` 最新源码、测试、已接受 ADR 和正式领域模型为唯一事实源，对 PR3 已实现的：

```text
Committed Execution Transaction
→ Projection Applier
→ Real Manager Projection Targets
→ Manager Restore API
→ Applied Projection Ledger
```

进行恢复边界收口。

本 PR 不扩展交易类型，不实现 Commit Coordinator，不切换正式 ExecutionProcessor。

本 PR 必须解决四类问题：

```text
1. Fee / Settlement Target 没有读取真实 Current Authority
2. Manager 已安装、Applied Ledger 未记录时无法安全恢复
3. 单 Target Restore 与 Applied Record 之间的原子边界不清晰
4. 当前 Trade Projection 不能单独从空 Runtime 重建完整系统
```

完成后必须形成稳定契约：

```text
Durable Transaction Store
= 唯一持久事务权威

Manager Authority
= Transaction Projection 的运行时投影

Applied Projection Ledger
= 可通过有序 Replay 重建的派生索引
```

并支持以下恢复场景：

```text
Store Commit 已成功
Manager 尚未安装
→ 正常 APPLIED

Manager 已安装
Applied Ledger 已记录
→ IDEMPOTENT

Manager 已安装
Applied Ledger 因崩溃未记录
→ RECOVERED

Manager Current Authority 与 Expected/Result 均不一致
→ 明确冲突，Manager 不变
```

本 PR 完成后，下一阶段应可以安全进入：

```text
PR4：Execution Commit Coordinator
```

---

# 二、当前基线

历史审计基线为：

```text
d9bfc7e322adbbf6e5d5938a2383faa287023824
Feat: Real Manager Projection Targets 与完整 Authority Replay
```

开始实施时必须重新执行：

```bash
git status
git rev-parse HEAD
git log -n 15 --oneline
```

如果 `master` 已发生变化，以实际源码为准，不得机械依赖本提示词中的历史文件位置。

当前 PR3 已具备：

```text
OnlyExecutionProjectionApplyContext
OnlyAppliedProjectionRecord
OnlyAppliedProjectionLedger
OnlyInMemoryAppliedProjectionLedger
OnlyExecutionProjectionApplier
12 个 Generic T0 Cash Real Targets
Manager restore_execution_authority()
Position / Allocation Cycle Replay
Trade Fingerprint Replay
Fee / Settlement Sequence Replay
Account / Strategy Valuation Timeline Replay
Manager Authority Parity
Sequential Replay
Forward Recovery
```

但当前仍存在以下问题。

## 2.1 Fee Current State 不是真实读取

当前 Fee Target 在发现 Manager 已存在相同 Instruction Key 时，直接使用：

```python
current = projection.after
```

这等于用“期望结果”代替“真实当前状态”。

因此无法发现：

* Fee Records 被修改；
* Global Sequence Head 不一致；
* Instruction 内容冲突；
* Instrument、Trade、Order、Schedule 信息冲突；
* Applied Ledger 丢失后的真实状态差异。

## 2.2 Settlement Current State 不是真实读取

Settlement Target 同样在 Manager 已存在 Instruction 时，将 `projection.after` 当作 Current State。

它无法真实校验：

* Release Flags；
* Pending Instruction；
* Records；
* Record Sequence；
* Legal Settlement State；
* Instruction Scope。

## 2.3 Applied Ledger 只有进程内状态

当前只有：

```text
OnlyInMemoryAppliedProjectionLedger
```

它可以支持同一进程中的重复调用，但不能单独解决：

```text
Manager 已安装
→ 进程在 Applied Ledger record 前退出
```

重启后 Ledger 为空，而 Manager 可能已经处于 Result Authority。

当前逻辑会把这种情况错误识别为：

```text
VERSION_CONFLICT
```

## 2.4 Manager Restore 和 Ledger Record 之间存在窗口

当前基本顺序是：

```text
Manager Restore
→ Post-install State Hash Check
→ Applied Ledger Record
```

如果在 Manager Restore 后、Ledger Record 前失败：

```text
Manager = Result Authority
Applied Ledger = Missing
```

重复执行不能正确恢复 Ledger。

## 2.5 当前 PR3 不是 Empty Runtime Full Replay

当前 Projection Target 测试基于已经存在的 Before Authority：

```text
Account 已创建
Ledger 已创建
Order 已创建并 Accepted
Risk Reservation 已创建
Cash Reservation 已创建
Market / Fee Instruction 已存在于 Planning Context
```

因此 PR3 证明的是：

```text
Correct Before Authority
+ Committed Trade Projection
→ Correct After Authority
```

而不是：

```text
Empty Runtime
+ Trade Transaction Log
→ Complete Runtime
```

当前 Trade Transaction 不包含全部初始化和非 Trade Authority。

---

# 三、第一性原则

## 3.1 唯一持久权威原则

系统不能同时存在两个独立的持久事务权威：

```text
Transaction Store
Applied Projection Ledger
```

否则二者可能发生永久分叉。

本 PR 必须正式确定：

> `OnlyExecutionTransactionStore` 是唯一持久业务事务权威。

`OnlyAppliedProjectionLedger` 是：

```text
Runtime Projection Application Index
```

它可以持久化作为优化，但其内容必须能够由：

```text
Bootstrap Authority
+ Ordered Committed Transactions
```

确定性重建。

不得把 Applied Ledger 设计为无法重建的第二份业务真相。

## 3.2 Projection Result 是历史权威

Target 不得重新计算：

* Fee；
* Settlement；
* Average Price；
* PnL；
* Cash；
* Reservation；
* Risk；
* Valuation。

恢复只能安装已提交的 Projection Authority。

## 3.3 Expected 和 Result 都有明确含义

对某个 Projection：

```text
Expected Authority
= Projection 应用前的合法状态

Result Authority
= Projection 已完整应用后的合法状态
```

Target 在 Applied Ledger 缺失时必须区分：

```text
Current == Expected
→ 尚未应用

Current == Result
→ 已应用但 Ledger 缺失

Current != Expected 且 Current != Result
→ Authority Conflict
```

## 3.4 恢复不能只比较公开 State

判断 `Current == Result` 时，不能只比较公开 State Hash。

还必须确认 Manager-owned Replay Authority：

* Cycle；
* Trade Fingerprint；
* Record Sequence；
* Dedup Index；
* Reservation Order Index；
* Valuation Version；
* Timeline Point；
* Repository；
* Scope Index。

如果公开 Snapshot 正确但内部索引缺失，必须通过受控 Restore API 修复这些派生 Authority。

## 3.5 单 Target 必须原子

一个 Target 的边界必须是：

```text
完整验证
→ 构造完整 Install Plan
→ 一次性安装 Manager-owned Authority
→ 验证 Result Authority
→ 记录 Applied Projection
```

所有可能失败的业务验证必须发生在 Manager Mutation 之前。

对于 In-memory Manager，应优先使用：

```text
Copy-on-write
→ Atomic Container Swap
```

避免逐字段修改产生部分状态。

## 3.6 不做跨 Target 回滚

PR3.1 继续采用：

```text
Forward Recovery
```

不实现跨 Manager Rollback。

但必须保证单个 Target 自己不会产生不可恢复的半安装状态。

---

# 四、严格范围

## 4.1 本 PR 必须完成

```text
Fee Manager 真实 Execution Authority Query
Settlement Manager 真实 Execution Authority Query
Fee / Settlement Current State Converter
RECOVERED Apply Status
Lost Applied Ledger Recovery
Applied Ledger 派生权威 ADR
单 Target Restore 原子性强化
恢复边界和 Bootstrap ADR
相关测试、文档和 CI 修正
```

## 4.2 本 PR 不实现

```text
Commit Coordinator
Transaction Store Runtime Assembly
Projection Ready Coordinator
Durable Outbox Delivery
ExecutionProcessor Cutover
Legacy Journal 删除
Runtime Startup Full Replay
Bootstrap Snapshot 实现
非 Trade Transaction 实现
SQLite Applied Projection Ledger
SELL
CLOSE
Partial Fill
Margin / Futures
Paper / Live Runtime
```

不得提前把 PR4 或 PR6 混入本 PR。

---

# 五、修改前审计

修改前执行：

```bash
rg "OnlyAppliedProjectionLedger"
rg "OnlyInMemoryAppliedProjectionLedger"
rg "OnlyAppliedProjectionRecord"

rg "class OnlyExecutionProjectionApplier"
rg "class _OnlyProjectionTargetBase"
rg "def _prepare"
rg "def _complete"

rg "class OnlyFeeExecutionProjectionTarget"
rg "class OnlySettlementExecutionProjectionTarget"

rg "class OnlyFeeManager"
rg "class OnlySettlementManager"
rg "has_instruction_key"
rg "has_instruction"
rg "restore_execution_authority"

rg "OnlyProjectionApplyStatus"
rg "VERSION_CONFLICT"
rg "STATE_CONFLICT"
rg "PAYLOAD_CONFLICT"

rg "schema version"
rg "schema_version ="
rg "uv lock --check"
rg "Mypy MiniQMT"
```

形成修改前审计报告，至少回答：

1. Fee Manager 当前保存哪些 Authority；
2. Fee Manager 是否保存原始 Fee Instruction；
3. Fee Projection 的 Before/After State 包含哪些字段；
4. Settlement Manager 当前如何表示 Pending Authority；
5. Settlement 是否有真实 per-instruction Version；
6. Fee/Settlement Sequence 是 Component State 还是 Manager Global State；
7. Target 当前如何判断 Current State；
8. 哪些 Restore API 在验证完成前已修改 Repository；
9. Applied Ledger Record 失败时 Manager 处于什么状态；
10. Runtime 是否允许前一 Transaction 未 Projection Ready 时处理后一 Transaction；
11. 当前 Trade Projection 的 Before Authority 从哪里产生；
12. 空 Runtime 恢复还缺哪些非 Trade Authority。

审计完成前不得直接修改逻辑。

---

# 六、增加 RECOVERED 状态

扩展：

```python
class OnlyProjectionApplyStatus(StrEnum):
    APPLIED = "APPLIED"
    IDEMPOTENT = "IDEMPOTENT"
    RECOVERED = "RECOVERED"
    VERSION_CONFLICT = "VERSION_CONFLICT"
    STATE_CONFLICT = "STATE_CONFLICT"
    PAYLOAD_CONFLICT = "PAYLOAD_CONFLICT"
    INVALID_COMPONENT = "INVALID_COMPONENT"
```

语义必须明确。

## APPLIED

```text
Applied Ledger 无记录
Current Authority == Expected Authority
Target 安装 Result Authority
Applied Record 成功建立
```

## IDEMPOTENT

```text
Applied Ledger 已存在完全相同记录
Manager 不修改
```

## RECOVERED

```text
Applied Ledger 无记录
Current Authority 已等于 Result Authority
Target 验证或修复完整 Manager-owned Replay Authority
重新建立 Applied Record
不重新执行业务计算
```

## VERSION_CONFLICT

```text
Current Version
既不等于 Expected Version
也不等于 Result Version
```

或 Current Version 与可接受状态不匹配。

## STATE_CONFLICT

以下任一情况：

```text
Current Version == Expected Version
但 Current State Hash != Expected State Hash

Current Version == Result Version
但 Current State Hash != Result State Hash

公开 Result State 正确
但 Manager-owned Authority 存在不可安全修复的冲突
```

## PAYLOAD_CONFLICT

```text
Applied Ledger 已有相同 sequence/component
但 transaction、entity、payload 或 result hash 不一致
```

## INVALID_COMPONENT

Target Component 与 Projection Component 不一致。

---

# 七、重构统一 Apply 状态机

将 `_OnlyProjectionTargetBase._prepare()` 重构为明确状态机。

建议返回内部 Decision：

```python
class _OnlyProjectionApplyDecision(StrEnum):
    APPLY = "APPLY"
    RECOVER = "RECOVER"
```

或使用内部不可变模型：

```python
@dataclass(frozen=True, slots=True)
class _OnlyProjectionApplyPreparation:
    decision: _OnlyProjectionApplyDecision
    record: OnlyAppliedProjectionRecord
    current: OnlyDomainModel | None
```

统一算法如下。

## 7.1 检查 Component

不一致：

```text
INVALID_COMPONENT
```

## 7.2 检查 Applied Ledger

有记录且完全一致：

```text
IDEMPOTENT
```

有记录但不一致：

```text
PAYLOAD_CONFLICT
```

## 7.3 读取真实 Current State

每个 Target 必须通过真实 Manager Authority Query 和正式 Converter 获取 Current State。

不得使用：

```python
current = projection.after
```

## 7.4 判断 Expected Path

```text
Current Version == Expected Version
且 Current State Hash == Expected State Hash
→ APPLY
```

## 7.5 判断 Lost-ledger Recovery Path

```text
Current Version == Result Version
且 Current State Hash == Result State Hash
→ RECOVER
```

RECOVER Path 必须：

1. 使用 Projection Result 和 Replay Metadata；
2. 调用幂等的 Manager Restore/Repair API；
3. 确保 Manager-owned Index 完整；
4. 再次验证完整 Result Authority；
5. 重建 Applied Record；
6. 返回 `RECOVERED`。

不得重新运行普通 Mutation API。

## 7.6 冲突分类

```text
Version 既不是 Expected 也不是 Result
→ VERSION_CONFLICT
```

```text
Version 等于 Expected 或 Result
但对应 State Hash 不匹配
→ STATE_CONFLICT
```

不得把 Result Authority + Missing Ledger 误报为 Version Conflict。

---

# 八、Fee Manager 真实 Authority

## 8.1 保存 Instruction Authority

Fee Manager 当前不能只保存：

```text
_instruction_keys
_records
_sequence
```

它必须保存足以重建 Fee Execution State 的正式 Instruction Authority。

建议新增：

```python
self._instructions_by_key: dict[str, OnlyFeeInstruction]
```

或等价的不可变 Fee Authority 模型。

普通 `apply()` 和 `restore_execution_authority()` 都必须维护该映射。

如果相同 Idempotency Key 对应不同 Instruction，必须明确拒绝：

```text
FEE_INSTRUCTION_AUTHORITY_CONFLICT
```

不得仅根据 Key 返回空结果。

## 8.2 增加正式 Query

建议：

```python
def get_execution_authority(
    self,
    idempotency_key: str,
) -> OnlyFeeExecutionAuthoritySnapshot | None:
    ...
```

Snapshot 至少包含：

```text
Instruction
与该 Instruction 关联的 Records
Instruction Version
Global Record Sequence Head
```

具体模型以现有 Projection State 为准。

## 8.3 真实 Converter

实现正式：

```python
def only_fee_execution_state(
    authority: OnlyFeeExecutionAuthoritySnapshot,
) -> OnlyFeeExecutionState:
    ...
```

不得在 Target 内复制转换公式。

## 8.4 Version 语义

必须明确 Fee Instruction 的 Version。

首期 Immutable Fee Instruction 可以采用：

```text
不存在 → version 0
已应用 → version 1
```

如果未来支持 Fee Adjustment，应预留正式版本演进语义，但不得在本 PR 实现 Adjustment。

## 8.5 Fee Target

Fee Target 必须：

```text
Manager Query
→ Real Current Fee State
→ Expected / Result 判断
→ Apply 或 Recover
```

不得再使用 `projection.after` 作为 Current State。

---

# 九、Settlement Manager 真实 Authority

## 9.1 增加 per-instruction Version

当前 `_OnlyPendingSettlement` 应明确维护：

```python
version: int
```

建议语义：

```text
register
→ version 1

每次产生实际 Settlement State Change
→ version +1
```

如果当前 Projection Contract 使用不同版本规则，应以真实 Legacy 行为和 PR2.1 Contract 为准，但必须有真实 Manager Version Authority。

## 9.2 增加正式 Query

建议：

```python
def get_execution_authority(
    self,
    instruction_id: str,
) -> OnlySettlementExecutionAuthoritySnapshot | None:
    ...
```

必须返回：

```text
Instruction
Asset Released
Trade Cash Released
Withdrawable Cash Released
Legal Settled
Version
与该 Instruction 相关的 Records
Global Record Sequence Head
```

## 9.3 Converter

实现：

```python
def only_settlement_execution_state(
    authority: OnlySettlementExecutionAuthoritySnapshot,
) -> OnlySettlementExecutionState:
    ...
```

## 9.4 Settlement Target

必须读取真实 Manager Current State。

以下场景必须能识别冲突：

* 相同 Instruction ID、不同 Account；
* 相同 Instruction ID、不同 Trade；
* Release Flag 被修改；
* Record 缺失；
* Record 内容不同；
* Sequence Head 不一致；
* Legal Settlement 状态不一致。

---

# 十、Applied Projection Ledger 正式语义

新增 ADR，建议：

```text
docs/adr/0039-applied-projection-ledger-recovery-authority.md
```

ADR 必须明确：

## 10.1 Durable Authority

```text
OnlyExecutionTransactionStore
```

是唯一持久事务权威。

## 10.2 Applied Ledger

Applied Ledger 是：

```text
Projection Application Acceleration Index
```

它的用途是：

* 快速识别同一进程内重复 Apply；
* 避免每次重复检查完整 Manager Authority；
* 支持 Batch Forward Recovery；
* 在恢复完成后提供运行时幂等索引。

## 10.3 可重建性

Applied Ledger 必须能通过：

```text
Bootstrap Authority
→ Ordered Transaction Replay
```

重新产生。

## 10.4 不实现第二持久真相

本 PR 不新增独立 SQLite Applied Ledger。

后续若为了性能持久化 Applied Ledger，它必须被视为：

```text
可丢弃、可重建的 Checkpoint / Cache
```

不能成为独立业务真相。

---

# 十一、Manager 已安装、Ledger 未记录的恢复

新增明确测试场景。

## 11.1 Failure Ledger

实现测试专用 Ledger：

```python
class _OnlyTestFailOnceAppliedProjectionLedger:
    ...
```

它在第一次 `record()` 时抛出异常。

## 11.2 第一次执行

```text
Target 读取 Expected Authority
→ Manager 安装 Result Authority
→ Applied Ledger record 失败
```

预期：

```text
Batch FAILED
Manager = Result Authority
Applied Ledger = Missing
```

## 11.3 第二次执行

使用正常空 Ledger 和同一 Manager：

```text
Current Authority == Result Authority
Applied Ledger Missing
→ RECOVERED
→ Applied Record 被重建
```

必须验证：

* Manager Snapshot 不发生二次经济变化；
* Version 不再次推进；
* Fee/Settlement Record 不重复；
* Timeline 不重复；
* Reservation 不重复消费；
* Event 不发布；
* Applied Record 正确建立。

## 11.4 Batch 语义

扩展：

```python
@dataclass(frozen=True, slots=True)
class OnlyExecutionProjectionBatchResult:
    applied: tuple[OnlyProjectionApplyResult, ...]
    idempotent: tuple[OnlyProjectionApplyResult, ...]
    recovered: tuple[OnlyProjectionApplyResult, ...]
    ...
```

`RECOVERED` 必须被 Batch 视为成功状态。

---

# 十二、单 Target 原子性强化

## 12.1 所有验证先于修改

每个 `restore_execution_authority()` 必须先验证：

* Scope；
* Entity Identity；
* Cycle；
* Sequence；
* Fingerprint；
* Record ID；
* Reservation Key；
* Timeline Sequence；
* Repository Constraints。

验证过程中不得修改 Manager。

## 12.2 Copy-on-write

对于拥有多个内部容器的 Manager，建议：

```text
复制当前容器
→ 在副本中应用变化
→ 完整校验
→ 一次替换
```

至少审计：

```text
OrderManager
PositionManager
AllocationManager
AccountManager
StrategyLedgerManager
RiskReservationManager
FeeManager
SettlementManager
```

## 12.3 Repository

如果 Repository 写入可能失败，必须避免：

```text
Repository 已更新
Manager 内存未更新
```

建议方案之一：

### 方案 A：Repository Snapshot Replace

Manager 构造完整新 Authority 后，通过 Repository 原子替换。

### 方案 B：Manager-owned In-memory Repository Commit

对当前 In-memory 实现使用同一不可失败提交段。

### 方案 C：正式 Repository Transaction Port

仅当现有架构确有必要时增加，不得提前实现复杂数据库事务系统。

必须在 ADR 中说明首期单 Target 原子边界。

## 12.4 Restore API 幂等

对完全相同 Result Authority 重复调用：

```text
Manager Authority 不变
Version 不推进
Record 不重复
Timeline 不重复
Cycle 不推进
```

---

# 十三、Bootstrap Recovery Boundary

新增 ADR，建议：

```text
docs/adr/0040-runtime-bootstrap-and-transaction-tail-boundary.md
```

必须明确当前 Committed Trade Transaction 依赖的 Before Authority。

至少包括：

```text
Runtime Config
Account
Strategy Ledger
Instrument
Market Profile / Compiled Rule Reference
Order Submit / Accepted State
Risk Reservation
Account Cash Reservation
Strategy Cash Reservation
Initial Valuation State
```

## 13.1 明确当前能力

```text
PR3 / PR3.1
≠ Empty Runtime Full Replay
```

当前能力是：

```text
Correct Bootstrap / Before Authority
+ Committed Transaction Tail
→ Runtime Authority Recovery
```

## 13.2 推荐后续模型

推荐后续采用：

```text
Durable Bootstrap Snapshot
+ Ordered Transaction Tail
```

而不是要求 Trade Transaction 重建所有初始状态。

## 13.3 非 Trade Authority

ADR 必须列出未来需要事务化或进入 Bootstrap 的状态：

```text
Account Creation
Ledger Creation
Order Submit / Accepted / Rejected / Cancelled
Reservation Creation
External Cash Flow
Broker Account / Position Updates
Market Valuation
Trading-day Settlement
Fee Adjustment
Broker Connection State
```

## 13.4 与 PR4 的分工

PR4 只解决：

```text
一个已经具备正确 Before Authority 的 Runtime
如何安全提交和安装新 Trade Transaction
```

PR4 不解决 Runtime 启动恢复。

---

# 十四、测试要求

## 14.1 Fee Actual State

测试：

```text
Fee Manager Current == Expected
→ APPLIED

Fee Manager Current == Result 且 Ledger Missing
→ RECOVERED

相同 Key 但不同 Instruction
→ STATE_CONFLICT

Record 内容不同
→ STATE_CONFLICT

Sequence Head 不同
→ STATE_CONFLICT
```

## 14.2 Settlement Actual State

测试：

```text
Settlement Current == Expected
→ APPLIED

Settlement Current == Result 且 Ledger Missing
→ RECOVERED

Release Flag 不同
→ STATE_CONFLICT

Record 缺失
→ STATE_CONFLICT

Instruction Scope 不同
→ STATE_CONFLICT

Version 不匹配
→ VERSION_CONFLICT
```

## 14.3 所有 12 个 Target Lost-ledger Recovery

对每个 Target：

1. 正常应用到 Manager；
2. 不保留 Applied Ledger；
3. 使用新空 Ledger 和新 Target；
4. 重新 Apply；
5. 返回 `RECOVERED`；
6. Manager Authority Digest 不发生二次业务变化。

## 14.4 Applied Record Failure Window

对每个 Target 或至少复杂代表组件覆盖：

```text
POSITION
FEE
ACCOUNT
STRATEGY_LEDGER
VALUATION
```

注入 Ledger Record Failure，验证第二次可恢复。

## 14.5 Restore Failure Atomicity

使用失败注入 Repository 或测试 Port，验证：

```text
Restore 验证失败
→ Manager 完整 Authority Digest 不变
→ Applied Ledger 不变
```

至少覆盖：

```text
Position
Allocation
Account
Strategy Ledger
Fee
Settlement
```

## 14.6 Existing Forward Recovery

现有 12 个 Component Forward Recovery 测试必须继续通过。

## 14.7 Sequential Replay

现有三笔连续 BUY OPEN 必须继续与 Legacy Authority 完全一致。

## 14.8 无副作用

RECOVERED 路径同样必须保证：

```text
EventBus 不变
Event Buffer 不变
Transaction Store 不变
Legacy Journal 不变
Audit 不变
Reconciliation 不变
Broker Queue 不变
```

---

# 十五、架构边界测试

新增或扩展：

```text
tests/architecture/test_execution_projection_recovery_boundaries.py
```

必须确保：

* Applied Ledger 不被定义为业务事实 Store；
* Target 不写 Transaction Store；
* Target 不读取 Broker；
* Target 不运行 Reducer；
* Target 不运行 Fee Resolver；
* Target 不运行 Market Rule；
* Target 不发布 Event；
* Target 不标记 Projection Ready；
* Target 不调用普通 Manager Mutation API；
* Fee/Settlement Target 不使用 `projection.after` 伪装 Current；
* RECOVERED 不推进业务 Version；
* RECOVERED 不重复 Record；
* RECOVERED 不重复 Timeline；
* Restore API 所有校验先于 Mutation；
* 不存在独立持久 Applied Ledger 实现；
* 不存在 Bootstrap Full Replay 的虚假声明；
* 不存在 Compatibility Alias；
* 不存在 Validation Bypass；
* 不存在 Test-only Production Branch。

---

# 十六、文档修正

更新：

```text
docs/execution_projection_targets.md
docs/execution_prepared_transaction.md
docs/execution_projection_contract.md
docs/architecture.md
docs/adr/0038-real-manager-projection-targets.md
```

新增：

```text
docs/adr/0039-applied-projection-ledger-recovery-authority.md
docs/adr/0040-runtime-bootstrap-and-transaction-tail-boundary.md
docs/reports/pr3_1_recovery_boundary_audit.md
```

## 16.1 修正 Schema 矛盾

当前文档中不能同时存在：

```text
canonical schema v4
```

和：

```text
schema version v3
```

统一以当前实际代码为准。

旧 Schema 不保留隐式兼容解码。

## 16.2 明确当前完成状态

文档必须准确写为：

```text
Pure Planner：完成
Real Manager Targets：完成
Recovery Boundary Hardening：完成
Commit Coordinator：未完成
Processor Cutover：未完成
Runtime Full Recovery：未完成
```

不得提前声称：

```text
Commit-before-Mutation 已进入 Runtime
Full Replay 已完成
Applied Ledger 已持久化
Bootstrap Snapshot 已实现
```

---

# 十七、CI 清理

## 17.1 删除重复 Lock Check

当前 CI 中重复的：

```yaml
- name: Validate lock file
  run: uv lock --check
```

只保留一次。

## 17.2 MiniQMT Mypy

优先恢复：

```yaml
uv run mypy packages/provider/onlyalpha-plugin-miniqmt/src/onlyalpha_plugin_miniqmt
```

如果当前确实不能通过：

1. 实际执行命令；
2. 记录准确错误；
3. 修正能在本 PR 合理解决的问题；
4. 如果属于第三方无类型依赖，使用最小明确配置；
5. 不得继续以无说明注释形式长期保留。

禁止全局关闭严格检查。

## 17.3 最新 CI

确保本 PR 提交可以触发完整 GitHub Actions。

最终报告必须提供：

* Workflow Run；
* Job 状态；
* 失败 Job 原因；
* 不得只引用本地测试报告。

---

# 十八、工程门禁

执行：

```bash
uv lock --check
uv sync --frozen --all-packages --all-groups

uv run ruff check src tests examples packages
uv run ruff format --check src tests examples packages

uv run mypy src/onlyalpha
```

新增定向测试建议：

```bash
uv run pytest tests/execution/test_fee_projection_recovery.py -q
uv run pytest tests/execution/test_settlement_projection_recovery.py -q
uv run pytest tests/execution/test_projection_target_lost_ledger_recovery.py -q
uv run pytest tests/execution/test_projection_target_record_failure_recovery.py -q
uv run pytest tests/execution/test_projection_target_restore_atomicity.py -q
uv run pytest tests/execution/test_real_projection_target_forward_recovery.py -q
uv run pytest tests/execution/test_real_projection_target_sequential_replay.py -q
uv run pytest tests/architecture/test_execution_projection_recovery_boundaries.py -q
```

完整测试：

```bash
uv run pytest tests/execution -q
uv run pytest tests/architecture -q
uv run pytest tests/integration -q
uv run pytest tests/scenario -q
uv run pytest tests/conformance -q

uv run pytest tests -q \
  -m "not external and not requires_network and not requires_tushare and not requires_local_qmt"
```

插件：

```bash
uv run pytest packages/fake/onlyalpha-plugin-broker-virtual/tests -q

uv run pytest packages/provider/onlyalpha-plugin-tushare/tests -q \
  -m "not external and not requires_network and not requires_tushare"

uv run pytest packages/provider/onlyalpha-plugin-miniqmt/tests -q \
  -m "not external and not requires_network and not requires_local_qmt"
```

分发验证：

```text
Wheel Build
Sdist Build
Twine Check
Clean Install
Entry Point Smoke
Generic T0 Scenario
```

不得通过以下方式制造绿色：

```text
skip
xfail
删除冲突测试
忽略 Fee / Settlement Current State
异常吞噬
放宽 Authority Digest
关闭 Mypy
兼容 Wrapper
测试专用生产分支
```

---

# 十九、验收标准

PR3.1 只有同时满足以下条件才算完成。

## 19.1 Fee / Settlement Current Authority

* Target 读取真实 Manager Current State；
* 不再使用 `projection.after` 代替 Current；
* Version、State Hash、Records、Sequence 和 Scope 可以真实验证。

## 19.2 Lost-ledger Recovery

所有 12 个 Target 支持：

```text
Manager == Result
Applied Ledger Missing
→ RECOVERED
```

并重建 Applied Record。

## 19.3 RECOVERED 无二次业务变化

RECOVERED 时：

* Version 不推进；
* Record 不重复；
* Timeline 不重复；
* Reservation 不重复消费；
* Fingerprint 不产生冲突；
* Event 不发布。

## 19.4 Applied Ledger 语义明确

ADR 明确：

```text
Applied Ledger 是派生索引
Transaction Store 是唯一持久事务权威
```

## 19.5 单 Target 原子

Restore 验证失败时：

```text
Manager Authority Digest 不变
Applied Ledger 不变
```

Manager 安装成功、Ledger 记录失败后可以通过 RECOVERED 恢复。

## 19.6 Bootstrap Boundary 明确

文档明确：

```text
PR3.1 不是 Empty Runtime Full Replay
```

并给出：

```text
Bootstrap Authority
+ Transaction Tail
```

的后续恢复方向。

## 19.7 PR4 不再需要修改核心 Recovery Contract

PR4 不应再需要重新设计：

* Apply Status；
* Lost-ledger Recovery；
* Applied Ledger Authority；
* Fee/Settlement Current State；
* Target Restore Atomicity；
* Bootstrap Boundary。

---

# 二十、最终交付报告

完成后输出：

## 1. 修改前审计

列出：

* HEAD；
* Fee/Settlement 原 Current State 问题；
* Applied Ledger 原语义；
* Restore/Ledger 窗口；
* Bootstrap 缺口。

## 2. Apply 状态机

列出：

```text
APPLIED
IDEMPOTENT
RECOVERED
VERSION_CONFLICT
STATE_CONFLICT
PAYLOAD_CONFLICT
INVALID_COMPONENT
```

的最终判定表。

## 3. Fee Authority

说明：

* Instruction 保存；
* Current State Query；
* Version；
* Records；
* Sequence；
* Conflict。

## 4. Settlement Authority

说明：

* Pending State；
* Version；
* Release Flags；
* Records；
* Sequence；
* Conflict。

## 5. Applied Ledger

说明：

* 为什么是派生索引；
* 如何重建；
* 为什么不是第二持久权威。

## 6. Lost-ledger Recovery

提供：

```text
Manager Restore 成功
Ledger Record 失败
Retry → RECOVERED
```

的真实测试结果。

## 7. Target Atomicity

说明：

* 验证阶段；
* Install Plan；
* Container Swap；
* Repository 边界；
* Failure Tests。

## 8. Bootstrap Boundary

列出 Trade Transaction 无法重建的 Authority。

## 9. CI 和文档

列出：

* Schema 修正；
* 重复 CI Step 删除；
* MiniQMT Mypy 状态；
* Workflow Run 状态。

## 10. 测试结果

提供真实命令和通过数量。

不得伪造未执行结果。

## 11. PR4 Readiness

明确回答：

```text
PR4：Execution Commit Coordinator
```

是否可以开始。

只有全部验收条件满足时回答：

```text
GO
```

否则回答：

```text
NO-GO
```

并列出阻塞项。

---

# 最终目标

PR3.1 完成后，OnlyAlpha 的 Projection Apply 必须具备：

```text
Expected Authority
→ APPLIED

Applied Record Exists
→ IDEMPOTENT

Result Authority Exists but Ledger Missing
→ RECOVERED

Authority Diverged
→ Explicit Conflict
```

并形成稳定恢复边界：

```text
Transaction Store
→ 唯一持久事务权威

Projection Targets
→ 安装 Runtime Manager Authority

Applied Projection Ledger
→ 可重建的应用索引

Bootstrap Authority
+ Transaction Tail
→ 未来 Runtime Recovery 基础
```

完成这一步后，PR4 只需要解决：

```text
Prepared Transaction
→ Durable Commit
→ Projection Apply
→ Projection Ready
→ Durable Outbox
```

不得再重新解释 Target Recovery 和持久权威边界。
