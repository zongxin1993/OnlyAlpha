# OnlyAlpha：Execution Transaction Store 正式装配与真实 Engine Restart Recovery

## 一、任务背景

请基于 OnlyAlpha 当前 `master` 分支的真实源码、测试、ADR 和产品入口，完成以下工程任务：

```text
Execution Transaction Store Factory Assembly
+
True Engine Restart Recovery Test
```

当前工程已经完成 PR4.1：

```text
Projection Ready Business Query
Runtime initialize() Transaction-Tail Recovery Hook
Recovered Outbox 在 Cluster 启动前发布
In-memory / SQLite Store Recovery Contract
12 个真实 Manager Projection Target 故障矩阵
```

但当前仍存在一个产品化缺口：

```text
OnlyEngine
→ OnlyBacktestRuntimeFactory
→ OnlyBacktestRuntime
```

这条正式产品装配链默认没有从配置创建和管理持久化 Execution Transaction Store。

`OnlyBacktestRuntime` 虽然允许注入 `execution_transaction_store`，但正常 Factory 创建 Runtime 时没有注入，因此默认使用新的 `OnlyInMemoryExecutionTransactionStore`。

现有 SQLite Restart 测试主要通过测试 Harness 和直接修改：

```text
runtime._services
runtime._state
cluster_manager._clusters
```

完成恢复验证。

这能够证明组件支持恢复，但不能证明：

> 一个 Engine 进程结束后，新的 Engine 仅依靠相同配置和 `user_data` 目录，就能由正式 Factory 自动重新打开旧 Store、执行 Runtime Recovery、发布 Outbox，并继续运行。

本任务要补齐该产品边界。

---

# 二、最终目标

完成后必须支持以下正式产品流程：

```text
Engine A
→ Runtime Factory 根据配置创建 SQLite Execution Store
→ Runtime 处理成交
→ Transaction 已 Commit，但 Projection 或 Outbox 在故障点中断
→ Engine A 关闭

Engine B
→ 使用相同产品配置和相同 user_data 根目录
→ Runtime Factory 自动定位并打开原 SQLite Store
→ Runtime 构建正确 Bootstrap Authority
→ initialize()
→ 自动 recover_unprojected()
→ READY
→ start()
→ 自动发布 recovered Outbox
→ Cluster start
→ RUNNING
```

整个测试不得：

* 直接构造测试专用 Coordinator 替换 Runtime Coordinator；
* 修改 `runtime._services`；
* 修改 `runtime._state`；
* 清空或修改 `cluster_manager._clusters`；
* 手工调用 `recover_unprojected()`；
* 手工替换 Outbox Publisher；
* 手工打开 Store 后塞入 Runtime；
* 绕过 `OnlyEngine`；
* 绕过 `OnlyBacktestRuntimeFactory`；
* 使用测试专用 Runtime 子类代替正式 Runtime；
* 为旧接口增加兼容层。

---

# 三、任务范围

本任务只做：

```text
1. Execution Store 配置模型
2. Execution Store Factory / Composition Root
3. Runtime Store 生命周期所有权
4. user_data 中稳定 Store 路径
5. OnlyEngine 正式重启恢复测试
6. Store 配置、恢复和路径相关架构门禁
7. 相关文档和 ADR 更新
```

本任务不做：

* Full Bootstrap Snapshot；
* Empty Runtime Recovery；
* Partial Fill Transaction；
* Multi-Fill；
* SELL/CLOSE；
* Futures/Margin Transaction；
* Non-Trade Transaction；
* Paper Runtime；
* Live Runtime；
* Web；
* 新 Broker；
* 新 DataSource；
* 分布式恢复；
* Exactly-once Event Delivery。

当前恢复仍允许依赖由产品配置确定性重建的正确 Bootstrap/Before Authority。

---

# 四、工作原则

## 1. 当前源码是唯一事实源

开始编码前，必须重新读取当前 `master`。

判断优先级：

```text
当前生产源码和真实调用图
→ 当前测试
→ 已接受 ADR
→ 架构文档
→ README / Roadmap
→ 历史 Prompt
```

不得根据本提示词猜测当前文件路径或构造参数。

如果当前实现已经发生变化，应以当前代码为准调整设计，但不能偏离本任务目标。

## 2. 不保留模糊旧边界

本任务不要求旧接口兼容。

禁止：

* Legacy Alias；
* Deprecated Wrapper；
* 双 Store 装配路径；
* Factory 创建一个 Store、Runtime 内又创建另一个 Store；
* 测试路径和产品路径使用不同 Composition Root；
* 使用环境变量隐式控制 Store 类型；
* Runtime 自己猜测磁盘路径；
* SQLite 打开失败后静默降级为 In-memory；
* Store 恢复失败后创建空 Store 继续运行；
* Store Schema 不兼容时自动删除数据库；
* 为了通过旧测试保留无归属的可选参数。

---

# 五、编码前审计

编码前执行并记录：

```bash
git status
git log -n 20 --oneline

rg "execution_transaction_store"
rg "OnlyExecutionTransactionStorePort"
rg "OnlyInMemoryExecutionTransactionStore"
rg "OnlySqliteExecutionTransactionStore"
rg "OnlyBacktestRuntimeFactory"
rg "OnlyRuntimeAssemblyConfig"
rg "OnlyRuntimeAssemblyPlan"
rg "OnlyUserDataLayout"
rg "user_data"
rg "execution.sqlite"
rg "recover_unprojected"
rg "OnlyExecutionRecoveryService"
rg "OnlyRuntimeServices"
rg "OnlyEngine"
rg "OnlyRuntimeSession"
rg "def create"
rg "def close"
rg "_services"
rg "_state"
rg "_clusters"
```

必须明确回答：

1. 正式 `OnlyEngine` 如何生成 `user_data` 路径；
2. Runtime Factory 当前能否获得 Runtime 专属输出目录；
3. Runtime 配置中是否已有 Storage 配置；
4. Core 是否已有通用 Storage Backend 枚举；
5. SQLite Execution Store 当前如何初始化和关闭；
6. Store 是否有 Schema Version；
7. Runtime 是否拥有 Store 生命周期；
8. 当前 Runtime close 是否会关闭 Store；
9. 当前 Factory 校验阶段是否会创建副作用文件；
10. 当前 Engine 失败清理是否能关闭已创建的 Store；
11. 当前测试有哪些直接修改 Runtime 私有字段；
12. 正确 Bootstrap Authority 当前由哪些配置和装配步骤构造；
13. Account、Ledger、Order、Reservation 的哪些状态无法仅靠配置重建；
14. 当前可设计哪一种真实重启场景，在不实现 Full Snapshot 的情况下仍能合法恢复；
15. 当前 `OnlyEngine` 是否允许相同 Run ID 重启；
16. Artifact Run Directory 和可恢复 Runtime State Directory 是否应分离。

将审计结果写入：

```text
docs/reports/execution_store_factory_engine_restart_pre_implementation_audit.md
```

文档必须引用真实类、方法、文件和调用链。

---

# 六、首先确定恢复场景边界

当前尚未实现 Full Bootstrap Snapshot，因此真实 Engine Restart Test 不能选择一个依赖无法重建中间状态的场景。

必须选择一个符合当前恢复边界的场景：

```text
新 Engine 能根据相同配置确定性重建 Transaction 的 Expected/Before Authority
```

推荐场景：

```text
初始 Account
初始 Cluster Ledger
已存在并可由确定性测试配置重新建立的 Order / Reservation Bootstrap
Transaction Store 中存在 committed but unprojected Transaction
```

如果正式 Engine 产品链当前无法从配置重建所需 Order/Reservation Before Authority，则必须先增加一个正式、明确、非测试私有修改的 Bootstrap 输入边界。

可接受方式：

```text
Scenario / Backtest 恢复 Fixture 通过正式公开产品配置描述初始执行 Bootstrap
```

或者：

```text
Store 中断点选择在 Transaction Commit 后、所有动态 Before Authority 仍能由相同确定性 Replay 重建的位置
```

不可接受方式：

* 测试中直接调用 Manager restore；
* 修改 Runtime 内部字段；
* 从旧 Runtime 对象复制 Manager；
* 使用 Harness 构造完成后的 Runtime；
* 通过 pickle 复制 Runtime；
* 将测试特例写入生产 Runtime。

如果当前架构确实无法在不实现 Snapshot 的情况下完成完整 Engine Restart，应：

1. 实现最小正式 Bootstrap Port；
2. 明确标注它不是 Full Snapshot；
3. 保持该边界只承载恢复所需的初始 Authority；
4. 不将任意 Manager 内部对象直接序列化。

---

# 七、Execution Store 配置模型

## 1. 新增明确配置

为 Runtime 增加 Execution Transaction Store 配置。

建议模型：

```python
class OnlyExecutionStoreBackend(StrEnum):
    MEMORY = "MEMORY"
    SQLITE = "SQLITE"
```

```python
@dataclass(frozen=True, slots=True)
class OnlyExecutionStoreConfig:
    backend: OnlyExecutionStoreBackend
    path: str | None = None
```

具体位置应遵循当前配置结构，可能位于：

```text
runtime.execution_store
storage.execution
runtime.extensions.execution_store
```

必须优先复用已有正式配置层次，不要把通用字段塞进自由 Mapping。

## 2. 配置语义

### Memory

```yaml
runtime:
  execution_store:
    backend: MEMORY
```

语义：

* 仅进程内；
* Runtime 关闭后不可恢复；
* 适合普通确定性短回测；
* 不允许配置 SQLite path。

### SQLite

```yaml
runtime:
  execution_store:
    backend: SQLITE
```

默认使用 Runtime 稳定状态目录。

如允许显式路径：

```yaml
runtime:
  execution_store:
    backend: SQLITE
    path: state/execution.sqlite3
```

必须限定：

* 相对路径相对于明确的 Runtime State Root；
* 禁止 `..` 路径逃逸；
* 禁止目录路径当文件；
* 禁止空字符串；
* 不允许 Memory 配置 path；
* 是否允许绝对路径必须明确决定；
* 默认优先禁止绝对路径，除非当前配置系统已有正式外部路径语义。

## 3. 默认策略

不得改变当前普通 Backtest 的轻量默认行为。

推荐：

```text
未配置 → MEMORY
显式 SQLITE → 持久恢复
```

如果项目当前设计要求所有产品运行都写 SQLite，可以选择默认 SQLite，但必须评估：

* 单元测试数量；
* 临时目录管理；
* Artifact 污染；
* 并发运行；
* 清理语义；
* 性能。

优先采用显式配置，避免无意改变所有测试行为。

---

# 八、稳定目录设计

## 1. 区分 Run Artifact 和 Runtime State

不要把可恢复数据库放在每次运行都新建的随机结果目录中。

需要区分：

```text
user_data/
├── runs/
│   └── <run-id>/...
└── state/
    └── runtimes/
        └── <runtime-id>/
            └── execution.sqlite3
```

实际路径应适配现有 `OnlyUserDataLayout`。

核心要求：

```text
相同 Runtime Identity
+ 相同 user_data root
→ 定位到相同 Execution Store
```

新的结果 Artifact 可以生成新 Run Directory，但恢复状态目录必须稳定。

## 2. 路径身份

Store 路径至少应受以下身份约束：

* Engine 产品或 Project Scope；
* Runtime ID；
* Account Scope，如有必要；
* Schema Version 不应直接写入路径；
* 不应使用当前时间；
* 不应使用随机 UUID；
* 不应使用本次 Run ID；
* 不应使用 Cluster ID 作为 Store 主隔离键。

Transaction Store 本身已经按 Runtime ID 隔离，因此通常一 Runtime 一 Store 最清楚。

## 3. 配置指纹保护

重新打开持久 Store 时，必须防止错误配置复用旧数据库。

至少持久化并验证：

```text
runtime_id
engine/product identity
runtime mode
base currency
account identity
market profile identity
reference/config fingerprint
execution store schema version
```

可以使用 Store Metadata Table。

打开时如果不匹配：

```text
明确失败
→ Runtime Assembly Failed 或 Recovery Failed
```

禁止：

```text
忽略旧数据
删除数据库
创建新数据库覆盖
降级 Memory
```

如果当前 Store 尚无 Metadata Table，应增加最小 Schema Metadata。

---

# 九、Execution Store Factory

## 1. 新增正式 Factory Port

建议：

```python
class OnlyExecutionTransactionStoreFactory(Protocol):
    def create(
        self,
        request: OnlyExecutionTransactionStoreCreateRequest,
    ) -> OnlyExecutionTransactionStorePort:
        ...
```

请求对象至少包含：

```python
@dataclass(frozen=True, slots=True)
class OnlyExecutionTransactionStoreCreateRequest:
    runtime_id: OnlyRuntimeId
    runtime_mode: OnlyRuntimeMode
    config: OnlyExecutionStoreConfig
    state_root: Path
    config_fingerprint: str
```

根据当前架构可简化，但不要传入整个 Engine 或 Runtime。

## 2. 默认实现

实现：

```text
OnlyDefaultExecutionTransactionStoreFactory
```

行为：

```text
MEMORY
→ OnlyInMemoryExecutionTransactionStore

SQLITE
→ resolve stable path
→ create parent directory
→ open OnlySqliteExecutionTransactionStore
→ initialize/validate metadata
```

## 3. Factory 注册位置

优先与现有 Component Factory Registry 整合。

可选方案：

```text
OnlyComponentFactoryRegistries.execution_transaction_stores
```

或者作为 Core Runtime Infrastructure Factory。

不能：

* 在 `OnlyBacktestRuntime.__init__` 内解析 YAML；
* 在 Runtime 中创建磁盘目录；
* 在 Processor 中创建 Store；
* 在 Engine 中硬编码 SQLite 类型；
* 在测试中单独走另一个 Store Factory。

## 4. Validate 阶段无副作用

`OnlyBacktestRuntimeFactory.validate()` 不得创建正式 SQLite 数据库。

Validate 可以：

* 解析配置；
* 验证 Backend；
* 验证路径；
* 验证父目录策略；
* 验证 Capability。

但不能：

* 创建数据库；
* 创建 Metadata；
* 修改旧 Store；
* 执行 Migration；
* 创建 State Directory。

真正资源创建只发生在 `create()`。

---

# 十、Runtime Factory 正式装配

在 `OnlyBacktestRuntimeFactory.create()` 中：

```text
解析 Store Config
→ Execution Store Factory.create()
→ 将 Store 注入 OnlyBacktestRuntime
```

伪代码：

```python
execution_store = components.execution_transaction_stores.create(
    OnlyExecutionTransactionStoreCreateRequest(
        runtime_id=config.runtime_id,
        runtime_mode=OnlyRuntimeMode.BACKTEST,
        config=config.runtime.execution_store,
        state_root=user_data_layout.runtime_state_root(config.runtime_id),
        config_fingerprint=config.fingerprint,
    )
)

runtime = OnlyBacktestRuntime(
    ...,
    execution_transaction_store=execution_store,
)
```

必须确保：

* Processor；
* Coordinator；
* Recovery Service；
* Admin Query；
* Ready Query；
* Projection State；
* Outbox Publisher；

全部使用同一个 Store 实例。

不得在 Runtime 内再执行：

```python
execution_transaction_store or OnlyInMemoryExecutionTransactionStore()
```

而让已明确配置的 Store 丢失。

可以保留低层 Runtime 构造时的默认值供独立单元测试使用，但正式 Factory 必须总是显式传入 Store。

更推荐让正式 Runtime 构造要求 Store 必填，并更新测试 Fixture；如果改动规模可控，应删除 Runtime 内隐式创建 Store 的责任。

---

# 十一、Store 生命周期所有权

## 1. 明确 Store 是 Runtime-owned Resource

当前 SQLite Store 需要 `close()`。

不要依赖 Python GC。

为 Store 增加统一生命周期边界，例如：

```python
class OnlyExecutionTransactionStoreResource(Protocol):
    def close(self) -> None:
        ...
```

或者让完整 Store Port 支持 `close()`。

Memory Store 的 `close()` 可以是明确 no-op。

## 2. Runtime close

Runtime 关闭顺序应保证：

```text
停止 Cluster
→ drain Outbox
→ 停止 Plugin
→ 关闭 EventBus
→ 关闭 Execution Store
→ 关闭 Clock
```

或者根据现有资源依赖调整，但必须确保：

* 不在 Store 关闭后 drain Outbox；
* 不在 Store 关闭后执行 Recovery；
* Engine 失败清理会关闭 Store；
* Factory 在 Runtime 创建失败时关闭已创建 Store；
* 多次 close 幂等；
* Store close 失败会保留第一个错误并继续清理其他资源。

## 3. 避免重复关闭

如果 Store 同时作为 Plugin Resource 或 Runtime Resource 注册，只能有一个所有者。

不要：

* Factory 关闭一次；
* Runtime close 再关闭一次；
* Engine cleanup 第三次关闭。

可以允许 `close()` 幂等，但职责仍必须唯一。

---

# 十二、SQLite Schema 与 Metadata

## 1. Schema Version

增加明确的 Store Schema Version，例如：

```text
execution_store_schema_version = 1
```

不得仅依赖 SQLite 表是否存在。

## 2. Metadata Table

建议：

```sql
CREATE TABLE execution_store_metadata (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
)
```

至少写入：

```text
schema_version
runtime_id
runtime_mode
config_fingerprint
created_at
```

可根据当前稳定身份增加：

```text
account_id
market_profile_id
base_currency
```

## 3. 打开规则

### 新文件

```text
创建 Schema
→ 写 Metadata
→ 开始使用
```

### 已存在且匹配

```text
验证 Schema
→ 验证 Metadata
→ 保留原 Transaction / Outbox
→ 开始 Recovery
```

### 已存在但不匹配

抛出明确错误，例如：

```text
EXECUTION_STORE_IDENTITY_MISMATCH
EXECUTION_STORE_SCHEMA_UNSUPPORTED
EXECUTION_STORE_METADATA_CORRUPT
```

禁止自动覆盖。

## 4. Migration

本任务不要求实现多版本 Migration Framework。

但必须：

* 明确当前 Version；
* 对未知 Version fail fast；
* 保留后续 Migration 边界。

---

# 十三、真正的 Engine Restart Test

## 1. 测试必须走完整产品入口

测试必须使用：

```text
OnlyEngine
→ Config Parser
→ Runtime Planner
→ Runtime Assembler
→ OnlyBacktestRuntimeFactory
→ OnlyBacktestRuntime
```

不得直接调用：

```text
OnlyRealExecutionRecoveryHarness
OnlyBacktestRuntime(...)
OnlyExecutionCommitCoordinator(...)
```

作为最终产品重启验收路径。

Harness 可以继续用于低层故障测试，但不能用于本测试的主要装配。

## 2. 测试目录

建议新增：

```text
tests/integration/test_engine_execution_store_restart.py
```

或者：

```text
tests/runtime/test_engine_execution_store_restart.py
```

应归类为产品集成测试，而不是纯 Execution 单元测试。

## 3. 测试配置

使用临时 `user_data` 根目录：

```python
user_data = tmp_path / "user_data"
```

配置明确指定：

```yaml
runtime:
  runtime_id: restart-runtime
  execution_store:
    backend: SQLITE
```

Engine A 和 Engine B：

* 使用相同 Runtime ID；
* 使用相同 user_data；
* 使用相同配置指纹；
* 可以使用不同 Run ID；
* 不复用 Engine 对象；
* 不复用 Runtime 对象；
* 不复用 Store 对象；
* 不复用 EventBus；
* 不复用 Manager；
* 不复用 Cluster；
* 不复用 Broker；
* 不复用 DataSource。

## 4. 故障注入

需要在正式产品链中制造：

```text
Transaction Commit 成功
Projection Ready 尚未完成
```

或：

```text
Projection Ready 成功
Outbox 尚未发布完成
```

故障注入不能通过修改 Runtime 私有字段。

推荐增加测试专用 Dependency Injection Factory：

```text
OnlyFaultInjectingExecutionTransactionStoreFactory
```

它实现正式 Store Factory Port，并包装真实 SQLite Store。

允许在测试组件注册表中替换 Factory，但 Runtime、Engine 和 Factory 调用链保持不变。

允许的故障点：

```text
MARK_PROJECTION_READY 第一次失败
MARK_PROJECTION_FAILED 第一次失败
OUTBOX_MARK_PUBLISHED 第一次失败
```

优先选择 `MARK_PROJECTION_READY`：

```text
12 个真实 Manager 已安装
Applied Ledger 已完成
Store mark ready 失败
Engine A 失败
```

但这里存在重要限制：

```text
Applied Projection Ledger 当前是 In-memory
Manager Authority 当前没有 Full Snapshot
```

因此新 Engine B 无法直接继承 Engine A 已安装后的 Manager Result Authority。

对于真实 Engine Restart，优先选择：

```text
Commit 成功后、第一项 Projection 执行前中断
```

这样 Engine B 只需要重建 Expected/Before Authority。

如果正式产品链无法在该点注入，应使用 Store Commit Wrapper：

```text
commit() 成功后返回/上抛受控进程中断
```

要求：

* Transaction 和 Outbox 已写入 SQLite；
* Projection 尚未开始；
* Engine A 失败；
* Engine B 可从正确初始 Authority 恢复。

禁止为了测试方便选择一个 Engine B 无法重建 Before Authority 的故障点。

## 5. Engine A 验证

Engine A 失败后验证磁盘 Store：

* SQLite 文件存在；
* Transaction 数量为 1；
* `projection_ready=False`；
* Ready Query 为空；
* Outbox 存在但 Pending Query 为空；
* Transaction ID 稳定；
* execution sequence 稳定；
* payload hash 非空；
* Engine A 资源已经关闭；
* SQLite 可由新连接打开。

可以使用独立 Store Admin Reader 检查磁盘，但不能将该 Store 对象注入 Engine B。

## 6. Engine B 验证

创建全新的 Engine B。

调用正式入口：

```python
engine_b.run(...)
```

或当前 Engine 生命周期对应的方法。

验证：

```text
Factory 自动打开同一路径
Runtime initialize 自动执行 Recovery
Recovery Diagnostic == RECOVERED
Runtime 进入 READY/RUNNING
Ready Query 包含原 Transaction
Outbox 在 Cluster start 前发布
Pending Outbox 最终为 0
```

还必须验证：

* Transaction ID 与 Engine A 相同；
* execution sequence 相同；
* Event ID 相同；
* committed payload hash 有效；
* 不生成第二笔 Transaction；
* 不重复扣减现金；
* 不重复增加 Position；
* 不重复收费；
* 不重复追加 Ledger Trade；
* 正式 Result 中 Trade 只出现一次；
* Artifact 中 Execution Fact 只出现一次；
* Result fingerprint 在对应恢复基准下稳定。

## 7. 无故障基准

增加 Baseline Engine：

```text
Engine Baseline
→ 相同配置和行情
→ 无故障执行完成
```

比较：

```text
Recovered Engine B Final Authority
==
Baseline Engine Final Authority
```

至少比较：

* Final Account；
* Position；
* Allocation；
* Ledger；
* Orders；
* Trades；
* Fees；
* Settlement；
* Risk；
* Equity Timeline；
* Result Facts；
* Determinism Fingerprint；
* Result Fingerprint。

如果某些运行元数据因重启必然不同，应明确排除，不得简单删除大部分字段。

---

# 十四、真实 Outbox Restart Test

除 committed-but-unprojected 测试外，再增加一个独立场景：

```text
Transaction Projection Ready
→ EventBus 接收 Event
→ mark_published 失败
→ Engine A 结束
→ Engine B 打开同一 Store
→ 重试相同 Event ID
```

验证：

* Transaction 仍 Ready；
* Engine B 不重放 Projection；
* Ready Transaction 数量仍为 1；
* Manager 经济状态不重复；
* Outbox attempt count 增加；
* Event ID 不变；
* 最终 published；
* 语义明确为 at-least-once。

如果当前新 Engine 无法重建 Result Authority，测试可以针对纯 Store + Outbox 产品 Resource 完成，但应优先通过 Engine 路径。

不得混淆：

```text
Projection Recovery
和
Outbox Delivery Retry
```

---

# 十五、Factory 与 Store 测试矩阵

## 1. Memory Backend

验证：

* Factory 返回 In-memory Store；
* 不创建 state 目录或 SQLite 文件；
* Runtime 正常运行；
* 新 Engine 不恢复旧事务；
* 文档明确不可恢复。

## 2. SQLite Backend 新建

验证：

* 创建稳定目录；
* 创建数据库；
* 写 Metadata；
* Runtime 正常运行；
* close 后文件有效。

## 3. SQLite Backend 重开

验证：

* 不清空表；
* Metadata 匹配；
* Transaction 保留；
* Outbox 保留；
* sequence 继续递增。

## 4. Identity Mismatch

同一路径但修改：

* Runtime ID；
* Config Fingerprint；
* Account；
* Market Profile；
* Runtime Mode。

必须失败，不能创建新 Store 覆盖旧 Store。

## 5. Schema Mismatch

修改 Metadata Schema Version。

必须返回稳定错误。

## 6. Corrupt Database

无效 SQLite 文件、缺表或 Metadata 缺失。

必须明确失败。

## 7. Factory Create Failure

验证已经创建的：

* DataSource；
* Broker Resource；
* Clock；
* EventBus；

被正确回滚。

## 8. Runtime Construction Failure

Store 已打开，但 Runtime 后续装配失败。

必须关闭 Store。

## 9. Engine Close

正常、失败和重复 close 均正确释放 Store。

---

# 十六、架构门禁

新增架构测试，确保：

1. `OnlyBacktestRuntimeFactory` 显式创建 Execution Store；
2. 正式 Factory 总是向 Runtime 注入 Store；
3. Runtime 产品装配不存在隐式第二 Store；
4. Runtime Processor、Coordinator、Query、Outbox 使用同一 Store；
5. Runtime close 拥有 Store 生命周期；
6. Config Parser 不创建 Store；
7. Validate 不创建 SQLite 文件；
8. Store Factory 不依赖 Runtime 对象；
9. Store 不依赖 Engine；
10. Execution Store 路径由 Layout/Factory 决定，不由 Processor 决定；
11. Result/Collector 不直接打开 Store；
12. Cluster Context 不暴露 Store；
13. Strategy 不可访问 Store；
14. Engine Restart Test 不包含 `._services`；
15. Engine Restart Test 不包含 `._state`；
16. Engine Restart Test 不包含 `._clusters`；
17. Engine Restart Test 不调用 `recover_unprojected()`；
18. Engine Restart Test 不直接构造 Runtime；
19. Engine Restart Test 不直接替换 Coordinator；
20. SQLite 打开失败不存在 Memory fallback；
21. Identity mismatch 不删除数据库；
22. State Directory 不依赖 Run ID；
23. Store Factory 的测试替换通过正式 Registry/Port，而不是 monkeypatch Runtime 私有字段。

---

# 十七、现有测试迁移

检查现有：

```text
test_execution_runtime_recovery_sqlite_restart.py
```

如果该测试直接修改 Runtime 私有字段：

* 不要仅删除；
* 将其降级为组件级测试，名称和说明必须准确；
* 新增真正 Engine Restart Test；
* 避免两个测试都声称是 Product Restart。

可以将旧测试重命名为：

```text
test_runtime_hook_recovers_reopened_store_with_prebuilt_bootstrap_authority
```

其职责是验证 Runtime Hook。

新测试职责是：

```text
test_engine_factory_reopens_store_and_recovers_without_private_mutation
```

---

# 十八、文档更新

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
docs/adr/0043-execution-store-factory-and-runtime-state-directory.md
```

ADR 必须说明：

1. Store 是 Runtime-owned Resource；
2. Memory 与 SQLite 的产品语义；
3. 稳定 State Directory 与 Run Artifact Directory 分离；
4. Factory 是唯一 Store 创建位置；
5. Runtime 不解析 Store Config；
6. SQLite Identity Metadata；
7. 配置不匹配时 fail fast；
8. Runtime initialize 自动恢复；
9. Store close 生命周期；
10. 当前仍依赖正确 Bootstrap Authority；
11. 当前不是 Full Runtime Recovery；
12. 当前 Engine Restart Test 的故障点为何选择在 Projection 前；
13. Applied Ledger 仍为 In-memory rebuildable index；
14. Outbox 为 at-least-once。

新增或更新配置文档：

```yaml
runtime:
  execution_store:
    backend: SQLITE
```

说明数据库实际路径。

---

# 十九、建议文件结构

根据当前工程结构调整，建议：

```text
src/onlyalpha/execution/
├── transaction_store.py
├── transaction_store_factory.py
└── store_metadata.py

src/onlyalpha/config/
└── execution_store.py

src/onlyalpha/output/
└── layout.py

tests/execution/
├── test_execution_store_factory.py
├── test_execution_store_metadata.py
└── test_execution_store_identity.py

tests/integration/
├── test_engine_execution_store_restart.py
└── test_engine_execution_outbox_restart.py

tests/architecture/
└── test_execution_store_factory_boundaries.py
```

不要强行创建过多小文件；遵循当前模块组织。

---

# 二十、建议实施顺序

## 步骤 1：审计和设计冻结

输出预实现审计。

确定：

* Config 位置；
* State Root；
* Factory Port；
* Store 生命周期；
* Engine Restart 可重建的故障点。

## 步骤 2：配置模型

实现：

* Backend Enum；
* Config Parser；
* Validation；
* Serialization；
* Fingerprint 参与规则。

修改 Store 配置必须影响 Config Fingerprint。

## 步骤 3：State Directory

扩展 `OnlyUserDataLayout`：

```text
runtime_state_root(runtime_id)
execution_store_path(runtime_id)
```

确保路径稳定且与 Run Artifact 分离。

## 步骤 4：Store Metadata

实现 Schema Version 和 Identity Validation。

补齐 SQLite 新建、重开、不匹配测试。

## 步骤 5：Store Factory

实现 Memory / SQLite 创建。

保证 validate 无副作用。

## 步骤 6：Backtest Factory 装配

正式 Factory 创建 Store 并注入 Runtime。

确保异常清理。

## 步骤 7：Runtime 生命周期

Store 作为 Runtime-owned Resource 正式关闭。

清理重复所有权。

## 步骤 8：测试用 Fault Factory

通过正式 Factory Port 包装 SQLite Store，注入 commit 后、Projection 前故障。

不得修改 Runtime 私有状态。

## 步骤 9：真实 Engine Restart Test

完成 Engine A / Engine B / Baseline 三路径比较。

## 步骤 10：Outbox Restart Test

验证稳定 Event ID 和 at-least-once。

## 步骤 11：架构测试和文档

禁止私有字段恢复测试重新出现。

---

# 二十一、测试命令

执行当前项目真实门禁。

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

uv run pytest tests/execution/test_execution_store_factory.py -q
uv run pytest tests/execution/test_execution_store_metadata.py -q
uv run pytest tests/execution/test_execution_store_identity.py -q
uv run pytest tests/integration/test_engine_execution_store_restart.py -q
uv run pytest tests/integration/test_engine_execution_outbox_restart.py -q
uv run pytest tests/architecture/test_execution_store_factory_boundaries.py -q

uv run pytest tests -q \
  -m "not external and not requires_network and not requires_tushare and not requires_local_qmt"

uv run pytest packages/fake/onlyalpha-plugin-broker-virtual/tests -q

uv run pytest packages/provider/onlyalpha-plugin-tushare/tests -q \
  -m "not external and not requires_network and not requires_tushare"

uv run pytest packages/provider/onlyalpha-plugin-miniqmt/tests -q \
  -m "not external and not requires_network and not requires_local_qmt"

git diff --check
```

如果实际文件名不同，使用实际文件名。

不得伪造未执行测试。

---

# 二十二、完成标准

只有全部满足以下条件，才能声明任务完成：

1. Runtime 配置存在正式 Execution Store Config；
2. 支持 Memory 和 SQLite Backend；
3. SQLite 路径由稳定 Runtime State Layout 决定；
4. State Directory 与 Run Artifact Directory 分离；
5. Store 配置参与 Config Fingerprint；
6. SQLite Store 有 Schema Version；
7. SQLite Store 有 Runtime Identity Metadata；
8. Identity 不匹配时 fail fast；
9. 未知 Schema Version 时 fail fast；
10. Validate 阶段不创建数据库；
11. Backtest Runtime Factory 正式创建 Store；
12. Factory 显式向 Runtime 注入 Store；
13. Runtime 不创建第二 Store；
14. Coordinator、Recovery、Query 和 Outbox 使用同一 Store；
15. Store 是 Runtime-owned Resource；
16. Runtime close 正式关闭 Store；
17. Factory 创建失败时关闭 Store；
18. Engine 失败清理关闭 Store；
19. Memory Backend 不创建 SQLite 文件；
20. SQLite Backend 重开不清空 Transaction；
21. Runtime execution sequence 在重开后继续；
22. Engine A 和 Engine B 是两个完全独立对象；
23. Engine B 不复用 Engine A Runtime；
24. Engine B 不复用 Engine A Store；
25. Engine Restart Test 使用正式 Engine 入口；
26. Engine Restart Test 使用正式 Runtime Factory；
27. Engine Restart Test 不访问 `runtime._services`；
28. Engine Restart Test 不访问 `runtime._state`；
29. Engine Restart Test 不访问 `_clusters`；
30. Engine Restart Test 不手工调用 Recovery；
31. Engine Restart Test 不手工替换 Coordinator；
32. Engine Restart Test 不手工替换 Outbox Publisher；
33. Factory 自动打开旧 SQLite Store；
34. Runtime initialize 自动恢复未 Ready Transaction；
35. Runtime start 自动发布 recovered Outbox；
36. Cluster 在 Outbox 之后启动；
37. Transaction ID 保持稳定；
38. execution sequence 保持稳定；
39. Event ID 保持稳定；
40. Ready Transaction 只出现一次；
41. Result Execution Fact 只出现一次；
42. Cash、Position、Fee、Ledger 不重复；
43. 恢复结果与无故障 Baseline 经济 Authority 一致；
44. Outbox Retry 保持 at-least-once 语义；
45. 没有 SQLite 失败后 Memory fallback；
46. 没有自动删除或覆盖旧数据库；
47. 没有为测试加入生产故障开关；
48. 原私有字段 Restart Test 已准确重命名或迁移；
49. 文档明确当前仍不是 Full Runtime Recovery；
50. Ruff、Mypy、Pytest 和架构门禁通过。

---

# 二十三、禁止的实现

以下任一情况视为失败：

```text
Factory 没有创建 Store，仍由 Runtime 默认创建
配置写了 SQLITE，但实际仍使用 Memory
SQLite 打开失败后静默使用 Memory
每次 Run 创建新的随机 SQLite 文件
数据库路径包含当前时间或 Run ID
Engine B 手工注入旧 Store
测试修改 runtime._services
测试修改 runtime._state
测试清空 cluster_manager._clusters
测试手工调用 recover_unprojected
测试直接构造 OnlyBacktestRuntime
测试使用 Harness 代替 OnlyEngine
测试复制 Engine A Manager 到 Engine B
测试通过 pickle 恢复 Runtime
生产代码加入 fail_after_commit 配置
Validate 阶段创建或修改 SQLite
配置不匹配时自动清空数据库
Schema 不匹配时忽略旧数据
Store 没有明确 close 所有者
Store 被重复创建
Coordinator 和 Ready Query 使用不同 Store
Outbox Publisher 使用另一个 Store
恢复后产生第二个 Transaction
恢复后重复扣现金或重复加仓
把本任务包装成 Full Bootstrap Recovery
顺带实现 Partial Fill、SELL/CLOSE 或 Futures
```

---

# 二十四、最终交付报告

完成后输出结构化报告。

## 1. 修改前审计

列出：

* 当前 Store 创建位置；
* Factory 原缺口；
* 原 SQLite Restart Test 的私有字段依赖；
* 可重建 Bootstrap 边界；
* 选定故障点及原因。

## 2. 配置和路径

说明：

* 配置 Schema；
* Backend；
* 默认值；
* State Directory；
* SQLite 路径；
* Fingerprint 规则。

## 3. Factory 装配

说明：

* Store Factory；
* Backtest Runtime Factory；
* Runtime 注入；
* 单 Store 实例证明；
* Validate 无副作用。

## 4. 生命周期

说明：

* Store 所有者；
* 创建；
* Recovery；
* Outbox；
* close；
* 异常回滚。

## 5. Metadata

说明：

* Schema Version；
* Identity 字段；
* Mismatch 行为；
* Corruption 行为。

## 6. Engine Restart Test

详细描述：

```text
Engine A
故障点
磁盘状态
Engine B
自动恢复
最终 Authority
与 Baseline 对比
```

明确证明没有修改 Runtime 私有字段。

## 7. Outbox Restart

说明：

* Event ID；
* attempt count；
* at-least-once；
* Projection 不重放。

## 8. 删除和迁移

列出：

* 删除的隐式 Store 创建；
* 删除的私有字段测试操作；
* 重命名的旧测试；
* 删除的兼容接口；
* 修正的文档。

## 9. 测试结果

给出真实命令和结果。

## 10. 剩余边界

必须明确仍未实现：

* Full Bootstrap Snapshot；
* Empty Runtime Recovery；
* Partial/Multi Fill；
* SELL/CLOSE；
* Futures/Margin Transaction；
* Non-Trade Transaction；
* Paper/Live Recovery；
* Exactly-once Delivery。

---

# 二十五、最终架构结论

完成后，OnlyAlpha 应从：

```text
Runtime 可以被手工注入一个可恢复 Store
```

升级为：

```text
OnlyEngine
→ Runtime Factory
→ 正式 Store Factory
→ 稳定 Runtime State Directory
→ SQLite Transaction Store
→ Runtime initialize Recovery
→ recovered Outbox
→ Cluster start
```

最终必须证明：

> 不访问 Runtime 私有字段、不复用旧 Runtime、不手工注入旧 Store，仅凭相同产品配置和相同 user_data 状态目录，一个全新的 OnlyEngine 可以自动打开原 Execution Store 并完成 committed transaction tail 的恢复。
