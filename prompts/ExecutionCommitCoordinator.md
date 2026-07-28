# OnlyAlpha PR4：实现 Execution Commit Coordinator 与正式事务提交主链

## 一、任务目标

以当前 OnlyAlpha 仓库 `master` 分支的真实源码和测试为唯一事实源，从第一性原理出发，实现正式的：

```text
Prepared Execution Transaction
→ Durable Transaction Commit
→ Ordered Projection Apply
→ Projection Ready
→ Durable Outbox Delivery
```

本任务的核心目标是彻底解决当前 Execution 产品路径中的：

```text
Manager Mutation
→ Journal Commit
```

即 `Manager-before-Journal` 问题，将正式成交路径改造成：

```text
Durable Commit
→ Manager Projection Apply
```

必须实现真正进入 Runtime 产品调用链的 `Execution Commit Coordinator`，不能只增加接口、抽象类、测试替身、参考实现或孤立组件。

本任务不考虑旧接口兼容。

不得为了保留旧测试、旧示例、旧构造函数、旧导出、旧调用关系或旧文档描述而保留错误架构。

测试和示例必须迁移到正确架构，而不是让生产代码迁就测试和示例。

---

# 二、工作原则

## 1. 当前源码优先

判断当前工程行为时使用以下优先级：

```text
当前生产源码和实际调用关系
→ 当前测试
→ 已接受 ADR
→ 当前架构文档
→ README / AGENTS
→ reports / prompts / 历史文档
```

历史 Prompt、审计报告和旧文档只能作为背景，不能机械照搬。

如果文档与当前源码冲突，以当前源码为准，并在实现后修正文档。

## 2. 从第一性原理出发

不要先假设当前类名、接口和模块划分必须保留。

首先回答以下问题：

1. 一次成交事务的唯一持久权威是什么？
2. Manager 状态在什么条件下允许改变？
3. 一笔事务在什么条件下可以对 Event Consumer 可见？
4. 同一成交重复进入时，哪个组件负责识别幂等？
5. 进程在任意步骤崩溃后，系统如何确定下一步动作？
6. 同一个 Runtime 中，后续事务是否依赖前序事务的 Result Authority？
7. Applied Projection Ledger 是业务真值，还是可重建索引？
8. Outbox 可以提供何种交付保证？
9. 哪些组件负责业务计算，哪些组件只负责状态安装？
10. 哪个组件拥有完整事务编排责任？

基于这些问题确定代码结构，不要基于现有测试形状倒推设计。

## 3. 不保留错误兼容层

禁止为了兼容旧路径增加：

* Legacy wrapper；
* Alias；
* 双实现；
* 同义 Coordinator；
* 新旧构造函数并存；
* 可选的新事务路径；
* Feature flag 双路径；
* Shadow write；
* 双写对比模式；
* 新路径失败后回退旧路径；
* 旧 Journal 与新 Transaction Store 同时作为成交事务权威；
* 旧 ExecutionProcessor Trade mutation 与新 Projection 同时执行。

对于已经迁移到新事务路径的成交场景，旧直接 Manager mutation 路径必须删除。

## 4. 测试服务于架构

不得因为旧测试依赖私有字段、旧构造函数或旧调用顺序而保留错误设计。

正确处理方式是：

```text
先确定正确生产架构
→ 修改生产调用方
→ 重写测试 Fixture
→ 更新 Scenario
→ 更新示例
→ 更新文档
```

禁止通过以下方式使测试表面通过：

* monkeypatch 私有状态绕过真实流程；
* 在测试中手工修改 Manager；
* 为测试添加生产代码专用分支；
* 通过 Mock 跳过 Transaction Store；
* 直接构造 Projection Ready 状态；
* 手工发布 Outbox Event；
* 降低或删除关键断言；
* 将冲突统一吞掉并返回成功；
* 捕获所有异常后继续处理下一事务。

---

# 三、修改前必须完成的源码审计

在编码前执行并记录简短审计结果：

```bash
git status
git log -n 20 --oneline

rg "OnlyExecutionProcessor"
rg "OnlyTradeExecutionTransactionPlanner"
rg "OnlyPreparedExecutionTransaction"
rg "OnlyCommittedExecutionTransaction"
rg "OnlyExecutionTransactionStore"
rg "OnlyExecutionTransactionCommitPort"
rg "OnlyExecutionProjectionApplier"
rg "OnlyExecutionProjectionTarget"
rg "OnlyAppliedProjectionLedger"
rg "OnlyInMemoryAppliedProjectionLedger"
rg "mark_projection_ready"
rg "mark_projection_failed"
rg "unprojected"
rg "projection_ready"
rg "OnlyExecutionOutbox"
rg "OnlyExecutionEventDeliveryCoordinator"
rg "OnlyInMemoryCommittedExecutionJournal"
rg "OnlyExecutionCommitPort"
rg "append_transaction"
rg "apply_trade"
rg "_trade\\("
```

必须明确回答：

1. 当前正式 Runtime 在哪里构造 `OnlyExecutionProcessor`；
2. 当前 Trade 路径在哪些位置直接修改 Manager；
3. 当前 Journal 在 Manager mutation 之前还是之后写入；
4. 当前 Prepared Transaction Planner 的正式支持范围；
5. Transaction Store 的 In-memory 和 SQLite 语义；
6. Projection Applier 的顺序和失败结果；
7. 12 个 Real Manager Projection Target 的注册位置；
8. Applied Projection Ledger 的真实权威边界；
9. Outbox 是否已受 `projection_ready` 门禁控制；
10. 当前 Runtime 是否存在 Transaction Store、Applier、Target Registry 和 Coordinator 装配；
11. 旧 Committed Journal 和新 Transaction Store 是否存在功能重叠；
12. 哪些测试仍然依赖旧 Manager-before-Journal 路径。

审计结果写入：

```text
docs/reports/pr4_execution_commit_coordinator_pre_implementation_audit.md
```

内容应简洁、具体、引用真实文件和调用点，不得写泛化架构描述。

---

# 四、目标架构

正式产品链必须调整为：

```text
Broker Trade Update
    │
    ▼
Execution Validation / Scope Resolution
    │
    ▼
Immutable Planning Context Builder
    │
    ▼
OnlyTradeExecutionTransactionPlanner
    │
    ▼
OnlyPreparedExecutionTransaction
    │
    ▼
OnlyExecutionCommitCoordinator
    │
    ├── Durable Transaction Commit
    ├── Runtime Sequence Gate
    ├── Ordered Projection Apply
    ├── Projection Result Validation
    ├── Mark Projection Ready
    └── Return Durable Outbox Delivery Intent
            │
            ▼
OnlyExecution Event Delivery Coordinator
            │
            ▼
Durable Outbox Publisher
            │
            ▼
EventBus
```

职责必须严格分离。

## Planner

只负责：

* 根据 immutable Planning Context 计算业务结果；
* 生成 Fact Draft；
* 生成 ordered Projections；
* 生成 Preconditions；
* 生成 deterministic Events；
* 生成 Prepared Transaction。

Planner 不得：

* 读取 Manager；
* 读取 Runtime；
* 读取 Store；
* 读取 EventBus；
* 分配 durable execution sequence；
* 修改任何状态；
* 发布 Event；
* 调用 Broker；
* 调用 Clock；
* 在内部重新读取可变配置。

## Transaction Store

只负责：

* 原子持久化 Prepared → Committed Transaction；
* 分配 Runtime 内 execution sequence；
* 保存 Transaction、Trade、Update 幂等索引；
* 保存 Outbox；
* 保存 Projection Ready / Failed 状态；
* 查询 unprojected transaction；
* 记录 Outbox 发布状态。

Transaction Store 是唯一持久成交事务权威。

## Projection Target

只负责：

* 验证 Projection Component；
* 验证 Scope、Version、State Hash 和 Payload Hash；
* 将 committed Result Authority 安装到真实 Manager；
* 修复 Manager-owned replay index；
* 返回 APPLIED、IDEMPOTENT、RECOVERED 或冲突结果。

Target 不得：

* 重新运行 Reducer；
* 重新计算 Fee；
* 重新运行 Market Rule；
* 调用 Broker；
* 调用普通 Manager mutation API；
* 写 Transaction Store；
* 标记 Projection Ready；
* 发布 Event；
* 写 Outbox；
* 决定下一事务是否可执行。

## Applied Projection Ledger

只作为：

```text
Runtime Projection Application Acceleration Index
```

它是：

* 可丢弃；
* 可重建；
* 非业务真值；
* 非 durable transaction authority。

不要把 Applied Ledger 改造成第二份持久业务账本。

## Execution Commit Coordinator

负责完整协调：

```text
Commit
→ Sequence Gate
→ Apply
→ Ready
→ Delivery Intent
```

它是 PR4 的核心产品组件。

---

# 五、实现 Execution Commit Coordinator

实现正式类，建议命名：

```python
OnlyExecutionCommitCoordinator
```

具体文件位置应服从当前模块边界，推荐位于：

```text
src/onlyalpha/execution/commit_coordinator.py
```

不要放入 Runtime、Processor、Transaction Store 或 Projection Target 文件中。

## 1. Coordinator 依赖

Coordinator 应依赖抽象 Port，而不是具体 SQLite 或 In-memory 实现：

```text
OnlyExecutionTransactionCommitPort
OnlyExecutionTransactionQueryPort
OnlyExecutionProjectionStatePort
OnlyExecutionTransactionOutboxPort
OnlyExecutionProjectionApplier
OnlyClock 或明确 Timestamp Provider
```

如这些 Port 的职责分割不合理，可以重构，但不要创建大量只有一个实现、没有边界价值的空接口。

Coordinator 不得直接依赖：

* OrderManager；
* PositionManager；
* AllocationManager；
* AccountManager；
* StrategyLedgerManager；
* FeeManager；
* SettlementManager；
* RiskService；
* EventBus；
* Broker Gateway。

真实 Manager 应由 Projection Target 持有。

## 2. Coordinator 输入

输入应是已经完成纯业务规划的：

```python
OnlyPreparedExecutionTransaction
```

Coordinator 不应接收松散的：

```python
dict[str, object]
```

也不应重新接收 Broker Update 后自行重复规划。

建议接口：

```python
class OnlyExecutionCommitCoordinator:
    def commit(
        self,
        prepared: OnlyPreparedExecutionTransaction,
        *,
        committed_at: OnlyTimestamp,
        projected_at: OnlyTimestamp,
    ) -> OnlyExecutionCommitCoordinationResult:
        ...
```

时间接口可根据当前 Clock 边界调整，但必须：

* 明确；
* 可测试；
* 不在多个步骤隐式读取不同时间；
* 不让 Projection Target 自行读取当前时间。

## 3. Coordinator 结果

实现强类型不可变结果，例如：

```python
@dataclass(frozen=True, slots=True)
class OnlyExecutionCommitCoordinationResult:
    transaction: OnlyCommittedExecutionTransaction
    transaction_inserted: bool
    status: OnlyExecutionCommitCoordinationStatus
    projection_result: OnlyExecutionProjectionBatchResult | None
    delivery_intent: OnlyExecutionEventDeliveryIntent
    failure_component: OnlyExecutionProjectionComponent | None
    error: str | None
```

状态建议明确区分：

```text
COMMITTED_AND_PROJECTED
ALREADY_READY
PROJECTION_FAILED
SEQUENCE_BLOCKED
TRANSACTION_CONFLICT
STORE_FAILURE
```

具体命名可调整，但禁止将所有结果折叠为：

```python
success: bool
message: str
```

## 4. Commit 流程

固定流程：

```text
1. 验证 Prepared Transaction 基础身份
2. Transaction Store commit
3. 获取 Committed Transaction
4. 检查前序 execution sequence
5. 如果当前 Transaction 已 Projection Ready，返回幂等成功
6. 调用 Projection Applier
7. 检查 Batch Result
8. 成功则 mark_projection_ready
9. 返回 DURABLE_OUTBOX Delivery Intent
10. 失败则 mark_projection_failed
11. 返回明确失败结果
```

不得在 Store commit 前调用 Projection。

不得在 Projection Ready 前返回可发布 Outbox 的成功意图。

---

# 六、Runtime Sequence Gate

同一个 Runtime 的 transaction 必须严格按 `execution_sequence` 应用。

固定规则：

```text
当前 sequence = N
前序 sequence = N - 1

N == 1
→ 可执行

N > 1 且 N - 1 projection_ready=True
→ 可执行

N > 1 且 N - 1 projection_ready=False
→ N 必须 SEQUENCE_BLOCKED
```

不能仅检查 Store 中是否存在前序 Transaction，必须检查前序已经 Projection Ready。

不得：

* 跳过失败事务；
* 自动删除失败事务；
* 将失败事务标记为 ready；
* 先执行后序，再回来修复前序；
* 用当前 Manager version 猜测前序已经完成。

如果 Transaction Store 现有 Query Port 不支持高效获取前序状态，应增加正确查询能力。

不要在 Coordinator 内通过遍历所有记录和字符串判断来模拟正式接口。

---

# 七、Projection Apply 结果处理

成功结果集合：

```text
APPLIED
IDEMPOTENT
RECOVERED
```

失败结果集合：

```text
PAYLOAD_CONFLICT
VERSION_CONFLICT
STATE_CONFLICT
INVALID_COMPONENT
TARGET_MISSING
```

如果 Batch 中任何 Component 失败：

```text
不得 mark_projection_ready
不得发布 Outbox
不得继续下一 Transaction
必须 mark_projection_failed
必须保留 committed transaction
必须返回失败 Component 和诊断
```

不要捕获冲突后重新运行 Planner。

不要在冲突时覆盖 Manager Current Authority。

不要把 `STATE_CONFLICT` 自动解释成“当前已经成功”。

---

# 八、恢复能力

实现正式恢复入口，建议为：

```python
def recover_unprojected(
    self,
    runtime_id: OnlyRuntimeId,
    *,
    limit: int | None = None,
) -> tuple[OnlyExecutionCommitCoordinationResult, ...]:
    ...
```

恢复必须：

1. 按 execution sequence 排序；
2. 从第一个未 ready Transaction 开始；
3. 前一条未完成时停止后续；
4. 对已安装 Component 接受 `IDEMPOTENT`；
5. 对 Manager 已是 Result、Ledger 缺失接受 `RECOVERED`；
6. 对真正冲突停止恢复；
7. 不重新运行 Planner；
8. 不重新读取 Broker；
9. 不重新计算 Fee、Settlement、Risk 或 Valuation；
10. 不重新生成 Event ID。

当前恢复边界必须明确保持为：

```text
Correct Bootstrap / Before Authority
+ Ordered Committed Transaction Tail
→ Runtime Authority Recovery
```

本 PR 不虚构：

```text
Empty Runtime
+ Trade Transactions
→ Full Runtime Recovery
```

不要在 PR4 中实现伪 Bootstrap Snapshot。

---

# 九、Outbox 门禁

确认并强化以下不变量：

```text
projection_ready=False
→ Outbox record 不允许进入 pending publish 结果

projection_ready=True
→ Outbox record 才允许发布
```

如果当前 `pending()` 已经实现此过滤，增加架构测试证明。

如果没有，应修复 Store，而不是在 Publisher 中临时过滤。

业务层只返回：

```text
DURABLE_OUTBOX Delivery Intent
```

Coordinator 不直接调用 EventBus。

Coordinator 也不应把 Event 发布失败解释成业务事务失败。

事务状态和交付状态必须分离：

```text
Transaction = COMMITTED_AND_PROJECTED
Event Delivery = PENDING / PUBLISHED / FAILED
```

Outbox 保证：

```text
At-Least-Once
```

不得在代码、文档或测试中声称 Exactly-Once。

---

# 十、正式产品路径切换

## 1. Runtime 装配

Backtest Runtime 必须正式装配：

```text
OnlyExecutionTransactionStore
OnlyTradeExecutionTransactionPlanner
OnlyExecutionProjectionApplier
Real Manager Projection Target Registry
OnlyAppliedProjectionLedger
OnlyExecutionCommitCoordinator
Transaction Outbox Publisher
```

优先使用 In-memory Store 作为 Backtest Runtime 默认实现。

SQLite Store 应通过相同 Port 验证，不得拥有不同业务语义。

## 2. ExecutionProcessor Trade 路径

对于当前 Pure Planner 已正式支持的场景：

```text
Generic T0 Cash
LIMIT
BUY
OPEN
整单成交
```

必须切换为：

```text
Broker Trade Update
→ Validate / Deduplicate / Scope
→ Build Planning Context
→ Planner.prepare()
→ Commit Coordinator.commit()
```

旧 `_trade()` 中针对该场景的直接 Manager mutation 必须删除。

不得同时执行：

```text
Legacy Manager Mutation
+
Prepared Transaction Projection
```

不得添加：

```python
if use_new_execution_transaction:
    ...
else:
    legacy_trade(...)
```

## 3. 非支持场景

当前 Planner 尚未支持的：

* SELL；
* CLOSE；
* Partial Fill；
* Multiple Fill；
* Futures；
* Margin；
* Short；
* FX；
* 多币种；

必须采用明确且稳定的 unsupported 结果或继续由未迁移的独立产品路径处理。

但要确保：

* 不假装这些场景已经由新 Coordinator 支持；
* 不通过隐式 fallback 混淆事务权威；
* 不让同一场景存在新旧两种可选路径；
* 文档明确描述迁移边界。

如果保留未迁移场景的旧 Trade 路径，其代码必须与已迁移路径清晰分离，并标记为待迁移业务范围，而不是兼容层。

---

# 十一、旧组件清理

完成产品切换后审计并删除无效或重叠组件。

重点检查：

```text
OnlyInMemoryCommittedExecutionJournal
OnlyExecutionCommitPort
OnlyDurableExecutionCommit
append_transaction
旧 Committed Builder
旧 Trade Journal 路径
旧 Trade Outbox 路径
旧 Trade Event Delivery Intent 生成
旧 ExecutionProcessor Trade Commit Context
```

原则：

* 同一成交不能有两个 durable authority；
* 新 Transaction Store 进入产品路径后，旧 Journal 不得继续承担该场景事务权威；
* 不保留只为旧测试存在的 Adapter；
* 不保留未被生产路径使用的 Export；
* 不保留“以后可能有用”的重复抽象；
* 删除死代码、死字段、死配置和死测试 Fixture。

如果旧 Journal 仍被 Non-Trade 路径使用，应重新审视其职责，并确保命名不继续暗示它是 Trade Transaction Authority。

---

# 十二、模块边界要求

必须保持以下依赖方向：

```text
Transaction Model
    ↑
Planner / Codec / Hash
    ↑
Transaction Store / Projection
    ↑
Commit Coordinator
    ↑
Runtime Assembly / Execution Entry
```

禁止：

```text
Transaction Store → Runtime
Transaction Store → Manager
Projection Target → Coordinator
Projection Target → Transaction Store
Planner → Manager
Planner → Runtime
Coordinator → Concrete Broker
Coordinator → EventBus
Core → Concrete Plugin
```

避免循环依赖。

所有公共导出必须经过审计。

内部实现不应因为新增 Coordinator 被随意导出到顶层公共 API。

只有稳定的、确实需要外部使用的接口才可以进入公开 `__all__`。

---

# 十三、代码质量要求

## 1. 类型

* 保持 Python 3.12；
* 保持 strict mypy；
* 使用不可变 dataclass；
* 使用明确 Enum；
* 避免 `Any`；
* 避免无约束 `object`；
* 避免 `dict[str, object]` 表达核心事务；
* 不用字符串判断业务状态；
* 不用反射调用核心事务流程；
* 不通过 `getattr()` 静默兼容旧对象。

## 2. 错误处理

区分：

```text
Business Conflict
Store Failure
Projection Conflict
Sequence Block
Invalid Transaction
Delivery Failure
```

不得：

* `except Exception: pass`；
* 统一转换为 `False`；
* 记录日志后继续下一事务；
* 冲突时自动覆盖；
* Store 失败时执行 Manager Projection；
* Projection 失败时发布 Event。

## 3. 原子边界

不要声称 Coordinator 提供跨 Manager rollback。

正式语义是：

```text
Durable Commit
+ Deterministic Projection
+ Forward Recovery
```

单个 Projection Target 保持现有预验证、copy-on-write 和 authority swap 边界。

Coordinator 只协调顺序，不重新实现 Target 内部安装逻辑。

## 4. 命名

所有新增正式类、枚举、DTO 使用 `Only` 前缀。

命名必须表达真实职责。

避免：

```text
Manager
Handler
Helper
Utils
Common
Base
Impl
New
V2
Legacy
```

除非确实具有明确领域意义。

---

# 十四、测试要求

## 1. Coordinator Unit Tests

覆盖：

```text
首次成功 Commit
重复相同 Prepared Commit
相同 ID 不同 Payload Conflict
前序未 Ready 导致 Sequence Blocked
已 Ready Transaction 重试
Projection 全部 APPLIED
Projection 混合 APPLIED/IDEMPOTENT/RECOVERED
Projection VERSION_CONFLICT
Projection STATE_CONFLICT
Projection PAYLOAD_CONFLICT
Projection Target Missing
Store Commit Failure
Mark Ready Failure
Mark Failed Failure
```

## 2. 故障矩阵

至少注入以下故障点：

```text
Prepare 完成后
Store commit 前
Store commit 中
Store commit 后
第 1 个 Projection 前
第 1 个 Projection 后
中间 Projection 后
最后 Projection 后
mark_projection_ready 前
mark_projection_ready 中
Ready 后、Outbox 发布前
EventBus 收到后、mark published 前
```

分别验证：

* Manager 是否被错误修改；
* Transaction 是否存在；
* Projection Ready 是否正确；
* Outbox 是否可见；
* 重试是否重复推进经济状态；
* 后序 Transaction 是否被阻断。

## 3. 幂等性

同一 Prepared Transaction 连续执行多次，必须保证：

```text
Order version 不重复推进
Position quantity 不重复增加
Allocation quantity 不重复增加
Fee record 不重复
Settlement record 不重复
Account cash 不重复扣除
Ledger cash 不重复扣除
Reservation 不重复消费
Risk version 不重复推进
Valuation timeline 不重复追加
Event ID 不变化
```

## 4. 产品纵切面测试

必须从正式产品入口验证：

```text
OnlyEngine
→ Backtest Runtime
→ Virtual Broker
→ Broker Queue
→ Execution Entry
→ Planner
→ Commit Coordinator
→ Transaction Store
→ Projection Targets
→ Result Collector
```

禁止在产品验收测试中直接：

* 调用 Manager mutation；
* 手工构建 After Snapshot；
* 手工标记 Projection Ready；
* 直接向 EventBus 发布成交事件；
* 绕过 Broker Queue；
* 绕过 Engine。

## 5. Store Parity

对 In-memory 和 SQLite Store 执行同一组 contract tests，保证：

* Sequence 相同；
* Idempotency 相同；
* Conflict 相同；
* Projection Ready 相同；
* unprojected 查询相同；
* Outbox pending 相同；
* attempt count 相同；
* published/failed 状态相同。

---

# 十五、架构测试

新增或更新架构测试，至少证明：

1. Coordinator 不导入任何 Manager；
2. Planner 不导入 Runtime、Manager、Store、EventBus；
3. Transaction Store 不导入 Runtime 和 Manager；
4. Projection Target 不调用普通业务 mutation API；
5. Runtime 的支持场景不再调用旧 `_trade()` Manager mutation；
6. Transaction Store 是唯一 durable Trade transaction authority；
7. Applied Ledger 只有 In-memory rebuildable index 语义；
8. Outbox pending 只返回 Projection Ready 记录；
9. Core 不导入具体插件；
10. 不存在新旧 Trade 双路径 Feature Flag；
11. 不存在为旧测试保留的兼容构造函数；
12. 不存在 `legacy_*` 新增生产路径。

架构测试应检查真实依赖或源码边界，不要只检查文档字符串。

---

# 十六、文档更新

更新：

```text
docs/architecture.md
docs/execution_processor.md
docs/execution_prepared_transaction.md
docs/execution_projection_contract.md
docs/execution_projection_targets.md
docs/execution_trade_planning.md
docs/backtest.md
README.md
```

新增 ADR，建议：

```text
docs/adr/0041-execution-commit-coordinator.md
```

ADR 必须说明：

1. Transaction Store 是唯一 durable Trade authority；
2. Applied Ledger 是可重建索引；
3. Commit-before-mutation；
4. Runtime sequence gate；
5. Projection Ready gate；
6. Forward recovery；
7. At-least-once Outbox；
8. 当前支持的成交范围；
9. 不等于 Full Runtime Recovery；
10. 旧 Manager-before-Journal 路径的删除范围。

删除已经与源码冲突的文档表述。

不要保留“尚未实现 Coordinator”之类过时内容。

---

# 十七、验收命令

实现完成后执行：

```bash
uv lock --check
uv sync --frozen --all-packages --all-groups

uv run ruff check src tests examples packages
uv run ruff format --check src tests examples packages

uv run mypy src/onlyalpha
uv run mypy packages/fake/onlyalpha-plugin-broker-virtual/src
uv run mypy packages/provider/onlyalpha-plugin-tushare/src/onlyalpha_plugin_tushare
uv run mypy packages/provider/onlyalpha-plugin-miniqmt/src/onlyalpha_plugin_miniqmt

uv run pytest tests -q \
  -m "not external and not requires_network and not requires_tushare and not requires_local_qmt"

uv run pytest packages/fake/onlyalpha-plugin-broker-virtual/tests -q

uv run pytest packages/provider/onlyalpha-plugin-tushare/tests -q \
  -m "not external and not requires_network and not requires_tushare"

uv run pytest packages/provider/onlyalpha-plugin-miniqmt/tests -q \
  -m "not external and not requires_network and not requires_local_qmt"

git diff --check
```

如果当前环境无法执行某个平台或外部 SDK 测试，必须明确记录：

* 未执行命令；
* 原因；
* 已执行替代验证；
* 不能宣称通过的门禁。

不得伪造测试结果。

---

# 十八、完成标准

只有同时满足以下条件，才可以声明 PR4 完成：

1. 存在正式 `OnlyExecutionCommitCoordinator`；
2. Coordinator 已进入 Backtest Runtime 产品装配；
3. 支持场景先 Commit Transaction，再修改 Manager；
4. 支持场景不再执行旧 Manager-before-Journal Trade 路径；
5. Transaction Store 是唯一 durable Trade transaction authority；
6. 同一 Runtime 严格按 execution sequence Apply；
7. 前序未 Ready 时后序不能 Apply；
8. 全部 Projection 成功后才标记 Ready；
9. 未 Ready Transaction 的 Outbox 不可发布；
10. Projection 失败可以通过 forward recovery 重试；
11. Applied Ledger 丢失时可以返回 RECOVERED；
12. 重复事务不会重复改变经济状态；
13. In-memory 与 SQLite Store 语义一致；
14. 产品纵切面经过 OnlyEngine 和 Broker Queue；
15. 旧接口、旧调用关系和无效兼容层已删除；
16. 测试、示例和文档已经迁移；
17. Ruff、Mypy、Pytest 和架构门禁通过；
18. 没有隐藏的双写、回退或 Feature Flag 路径。

---

# 十九、最终交付内容

完成后输出：

## 1. 修改前审计

列出旧产品路径、事务风险和重叠权威。

## 2. 实现摘要

按以下组件说明：

```text
Commit Coordinator
Sequence Gate
Transaction Store
Projection Apply
Projection Ready
Outbox Delivery
Runtime Assembly
Execution Entry Migration
```

## 3. 删除内容

明确列出：

* 删除的旧接口；
* 删除的旧调用路径；
* 删除的兼容层；
* 删除的无效测试 Fixture；
* 删除或修正的错误文档。

## 4. 故障矩阵结果

逐项说明每个崩溃点的：

* durable 状态；
* Manager 状态；
* Projection 状态；
* Outbox 状态；
* 恢复动作。

## 5. 测试结果

给出实际执行的命令和真实结果。

## 6. 当前剩余边界

明确说明当前尚未迁移的：

* SELL/CLOSE；
* Partial/Multi Fill；
* Futures/Margin；
* Non-Trade Transaction；
* Bootstrap Snapshot；
* Full Runtime Recovery。

不得把这些未完成能力包装成已完成。

---

# 二十、禁止的最终实现形态

以下任何一种情况都视为任务失败：

```text
只新增 Coordinator Protocol，没有产品实现
只新增 Coordinator 类，没有 Runtime 调用
Coordinator 内仍直接调用所有 Manager mutation
Store commit 发生在 Manager mutation 之后
支持场景同时执行 Legacy 和 Projection
Projection 失败后发布 Event
前序未 Ready 仍执行后序
Outbox 不检查 Projection Ready
通过 Mock 绕过真实 Transaction Store
为旧测试保留 Legacy Constructor
使用 Feature Flag 在新旧路径间切换
用 Applied Ledger 作为第二持久业务真值
将所有失败吞掉并返回 Reconciliation Required
只修改文档和测试，没有切换生产调用链
```

本任务的最终目标不是增加更多代码，而是形成一条清晰、唯一、可恢复的正式 Execution Transaction 主链，并删除与该主链冲突的旧设计。
