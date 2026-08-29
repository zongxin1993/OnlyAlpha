# OnlyAlpha Agent 工程指南

本文档适用于在 OnlyAlpha Monorepo 中工作的开发者、Codex、代码生成 Agent、审查 Agent、测试 Agent 和自动化工具。

它定义的是工程执行合同，而不是产品宣传材料。所有修改都必须服从当前源码、正式测试、未被替代的 ADR 和本文件规定的架构不变量。

子目录可以增加局部 `AGENTS.md`，但不得削弱本文件的顶层约束。

---

## 1. 项目身份

OnlyAlpha 是一个独立设计的模块化量化交易系统。

OnlyAlpha 的长期产品身份是多市场量化平台。`onlyalpha.domain` 定义全平台共享的 canonical 基础语言；A 股、港股、
美股、加密货币及后续市场通过 versioned Market Product、DataSource 与 Broker 插件接入，不得反向污染 Core 或复制
Engine/Runtime/Manager。多市场平台目标与产品声明口径由 ADR 0080 冻结。

当前工程形态：

```text
Monorepo
+
模块化单体 Core
+
插件化 DataSource / Broker
+
配置驱动 Engine / Runtime / Cluster
```

项目目标不是快速堆叠交易功能，而是建立：

- 唯一、明确的状态权威；
- 可重复的运行结果；
- 可审计的交易事实；
- 可恢复的执行和账务链；
- 可扩展但不互相污染的市场与插件边界；
- Research 可复用纯数据/计算定义，Backtest、Sim、Live 共享正式交易语义核心。

禁止把 OnlyAlpha 描述为其他工程的重构版本，也禁止为了兼容历史实验代码而长期保留两套正式路径。

---

## 2. Runtime 架构合同与当前产品边界

修改任何功能前，必须先区分目标架构合同与当前实现事实。

### 2.1 目标 Runtime 架构合同

OnlyAlpha 唯一允许的目标 Runtime vocabulary 是：

```text
RESEARCH
BACKTEST
SIM
LIVE
```

| Runtime | 数据 | 执行 | Broker | 正式交易语义 |
|---|---|---|---|---|
| RESEARCH | Historical | Vectorized / Batch | None | 不承担 |
| BACKTEST | Historical | Event-driven | Virtual Broker | 完整承担 |
| SIM | Realtime | Event-driven | Virtual Broker | 完整承担 |
| LIVE | Realtime | Event-driven | Real Broker | 完整承担 |

目标 Engine 必须允许 `RESEARCH/BACKTEST/SIM/LIVE` 四类 Runtime 同时存在并独立运行。一个 Runtime 的完成、停止或失败
不得被解释为另一个 Runtime 的 lifecycle command 或 domain fact。该异构生命周期是目标合同；当前 Engine 尚未完成四类
Runtime 的同时产品组合。

当前 Trading 产品组合遵守：

```text
One Trading Runtime
= One Account authority
= One resolved Market Product
= One Account currency
```

多市场通过一个 Engine 下多个隔离 Runtime 实现。跨市场 Result/Analytics/Artifact/Web 汇总只读，不得成为资金、仓位、
风险或订单 authority。单 Runtime 多市场、多币种账户、FX valuation、跨市场资金共享和组合保证金不属于当前目标合同。

正式原则：

```text
Research optimizes research efficiency.

Backtest / Sim / Live
share one trading semantic core.

Runtime Type
!=
Execution Permission.
```

历史 `PAPER` 和 standalone `SHADOW` 已从 active enum、配置、Factory、Runtime、测试 fixture 与 public contract 删除，且未保留 alias、deprecated spelling 或 wrapper。它们只可出现在明确标记的历史记录或防回流门禁中，不得重新成为产品依赖。

### 2.2 当前正式完成范围

```text
Runtime          : BACKTEST
Market Product   : GENERIC_T0_CASH@1
Account Type     : CASH
Order Type       : LIMIT
Position Side    : LONG
Position Mode    : NETTING
Open             : BUY OPEN
Close            : SELL CLOSE
Fill             : Whole / Partial / Multi-Fill
Terminal         : Cancel / Reject / Expire
Cluster          : Single / Multi-Cluster
Persistence      : Memory / SQLite
Recovery         : Checkpoint / Restart / Forward Recovery
```

该范围已经形成：

```text
配置
→ Engine
→ Runtime
→ 行情回放
→ Indicator
→ Factor
→ Strategy
→ Risk
→ Order
→ Virtual Broker
→ Execution
→ Durable Commit
→ Ordered Projection
→ Result
→ Analytics
→ Artifact / Report
→ Checkpoint / Recovery
```

SIM 已完成 realtime Virtual Broker normal path、continuity/gap/reconnect、streaming checkpoint 与 new-process recovery：

```text
Runtime          : SIM
Market Product   : GENERIC_T0_CASH@1
Account / Order  : CASH / LIMIT / LONG NETTING
Open             : BUY OPEN
Data             : Historical Bootstrap → Realtime Handoff
Execution        : Virtual Broker Accepted → Next-Bar Trade
Durability       : Memory / SQLite Transaction + Ordered Projection
Checkpoint       : Enabled / New-Process Recovery
```

该范围不升级为 Real Broker submission、Broker account/order/trade/position synchronization、完整 reconciliation、长期生产运行能力或广泛 MiniQMT compatibility matrix。

### 2.3 Streaming / SIM 当前边界

历史 PAPER streaming 基础设施已迁移到 product-neutral `runtime/streaming` 与正式 `runtime/sim` 组合。当前 active path 是：

```text
Historical Bootstrap
Open-Market Bootstrap
Historical → Live Handoff
Historical Watermark
1m External Bar
1m → 3m Internal Aggregation
Indicator / Factor Warmup
Strategy Intent
Virtual Broker Accepted / Trade / Terminal
Durable Transaction / Ordered Projection
Continuity / Gap / Reconnect
Streaming Checkpoint / Recovery
Ordered Shutdown
```

SIM 通过 Virtual Broker + 完整 Trading Kernel 产生正式 durable facts；不存在 active PAPER 或 Shadow execution product path。以下能力仍未闭环：

```text
Real Broker Submission
Broker Account Synchronization
Broker Order / Trade / Position Synchronization
Long-running Production Operations
Broad MiniQMT Compatibility Matrix
```

### 2.4 当前不可用或不存在的目标能力

以下目标 Runtime Factory 当前明确不可用：

```text
LIVE
```

`RESEARCH` 已由 P7.11 激活为 programmatic finite Runtime：从 exact verified Dataset Snapshot 编排既有 Job/Sweep/Statistics/Result/Artifact
authority，并以 deterministic re-entry 恢复；它不创建 Trading Cluster、Account、Broker、Market Product、Trading Kernel 或 Runtime
checkpoint。P7.12 已实现只消费 portable Artifact-derived HTTP v2 的 read-only Research Web；Research YAML/CLI、Runtime Web control 与
mixed heterogeneous lifecycle 仍未实现。`SIM` 已有 enum、配置、Factory、realtime Virtual Broker
durable path 与 streaming recovery，但不得扩写为已具备 Real Broker 或长期 production operations。Standalone `SHADOW` 不是 unsupported
target Factory，而是已删除的历史产品 spelling。`LIVE` 生产工作流仍未完成。

### 2.5 领域模型不等于产品能力

以下对象即使存在，也不能据此声明产品已经支持：

- 枚举；
- Domain Model；
- Manager；
- Market Product identity / binding；
- Legacy Execution Path；
- 测试 Fixture；
- Prompt；
- 未接入 Engine 的示例；
- 单组件单元测试。

特别注意：

```text
GENERIC_MARGIN_FUTURES identity 或测试 fixture 存在
≠ Futures Durable Execution 已完成

GENERIC_24X7_CRYPTO_SPOT identity 或测试 fixture 存在
≠ Crypto 产品已完成

CN_A_SHARE_CASH Market Product Plugin 存在
≠ 完整 A 股产品已完成
```

必须区分：

```text
正式、版本化、有限 Runtime 产品合同
!=
OnlyAlpha 正式支持整个市场
```

只有某市场的 `RESEARCH + BACKTEST + SIM + LIVE` 四种产品纵切面均通过唯一正式入口、完整 authority/recovery/result 链和
产品认证后，才能声明“OnlyAlpha 正式支持该市场”。在此之前只能声明已认证的精确有限产品，例如
`CN_A_SHARE_DURABLE_BACKTEST_V1`；不得由该合同推导完整 A 股市场已正式支持。

---

## 3. 事实来源优先级

发现文档、测试和源码不一致时，按以下顺序判断：

```text
1. 当前可执行源码和正式公共接口
2. 当前自动化测试、架构门禁和产品验收
3. 未被替代的 ADR
4. AGENTS.md
5. docs/architecture.md 和当前组件文档
6. README.md
7. docs/roadmap.md
8. 带明确日期和提交基线的 docs/reports/
9. HANDOFF.md
10. prompts/
```

`prompts/` 是历史实施输入，不是当前工程事实。

不得仅根据 Prompt、旧报告或类名推断当前行为。

---

## 4. Agent 开始工作前的固定流程

任何非微小修改开始前，必须完成以下检查：

1. 阅读目标模块当前源码；
2. 阅读相关公共入口和 `__all__`；
3. 阅读目标模块测试；
4. 查找相关 ADR；
5. 查找现有 Port、Protocol、Factory、Registry 和 Query；
6. 确认唯一状态权威；
7. 确认当前产品支持范围；
8. 确认是否涉及持久化 Schema、Checkpoint 或 Result Schema；
9. 选择最窄但足够的测试 Lane；
10. 再实施修改。

必须先回答以下问题：

```text
谁拥有状态？
谁可以修改状态？
谁只能读取状态？
哪个对象是 durable authority？
失败发生在哪个边界？
恢复后必须与什么结果等价？
```

无法回答时，不得直接新增 Manager、Service 或并行路径。

---

## 5. 当前内部执行入口与目标外部产品入口

当前内部执行/Runtime 组合权威仍是 `OnlyEngine`。它是当前源码中唯一合法的内部 Engine 执行入口，但不再被定义为长期外部产品控制合同。

目标唯一外部产品 mutation/control contract 是 versioned OpenAPI Product Control Plane：

```text
External Product Actor
→ OpenAPI Product Contract
→ HTTP Adapter
→ Application Command / Query
→ Stateful Kernel / Application Authority
→ OnlyEngine / Runtime（内部执行与组合）
```

P9.K 迁移期间，已审计的 direct external `OnlyEngine` 使用属于有限 known migration debt；只能按 K6 迁移并在 K8 封口，不得新增等价的 direct Engine/Runtime 产品入口。P9.K.0 只冻结该边界，不实现 Kernel Host。

正式产品调用链：

```text
CLI / Application
→ OnlyEngine
→ OnlyRuntimePlanner
→ OnlyEngineRunAssembler
→ Runtime Factory
→ OnlyRuntime
→ OnlyCluster
```

该调用链描述当前内部 Trading Runtime 执行/组合入口。目标 Research Runtime 仍由 `OnlyEngine` 管理内部产品生命周期，但使用 Research Job / Plan，而不是伪造 Trading Cluster；外部产品 Actor 最终必须经 Product Control Plane 提交 intent/query，不得据此新增 direct Engine/Runtime 生产框架。

允许的主要入口：

```python
engine.add_cluster(config)
engine.add_cluster_from_file(path)
engine.validate()
engine.initialize()
engine.start()
engine.wait()
engine.run()
engine.stop()
engine.close()
engine.snapshot()
```

约束：

- `OnlyEngine.run()` 只用于有限生命周期的 Backtest；
- 长生命周期 Runtime 使用 `initialize/start/wait/stop/close`；
- 目标 Engine 可以同时持有四种 Runtime，且每个 Runtime 生命周期必须独立；
- 目标 Web/Application 可以通过 Engine 单独控制 Runtime，不得直接控制 Runtime Manager；
- 有限 Research/Backtest 完成不得隐式停止 Sim/Live；
- 一个 Engine 实例不得被重复完整运行；
- Engine 终止后不得重新打开；
- CLI 只负责参数、配置路径和 Application 调用。

禁止：

- CLI 直接实例化 Runtime Manager；
- CLI 直接执行回测循环；
- Scenario Runner 绕过 Engine；
- 验收脚本直接驱动 Strategy、Factor 或 Manager；
- 示例手工注入成交并宣称产品链通过；
- 创建市场专用第二套 Engine；
- 创建测试专用生产入口；
- 为单个功能复制一套 Engine Service。

---

## 6. Engine 职责

Engine 负责：

- Cluster Definition 注册；
- 配置和扩展类型验证；
- 配置指纹；
- Runtime 兼容性规划；
- Runtime Session；
- Cluster Session；
- 插件和共享基础设施引用计数；
- Runtime 装配；
- 生命周期；
- 运行结果汇总；
- `user_data` 布局；
- Artifact 和 Report；
- 失败回滚；
- 有序资源释放。

Engine 不负责：

- 策略算法；
- 指标计算；
- 市场数据标准化细节；
- Broker SDK 回调细节；
- 撮合算法；
- 费用公式；
- Position 成本计算；
- SQL 业务决策；
- 市场规则硬编码；
- Web 展示。

新增功能时，先判断它是 Engine 编排问题，还是 Runtime 内部业务问题。不得把业务计算塞入 Engine。

---

## 7. Trading Runtime 所有权与 Research 边界

目标 Trading Runtime 是：

```text
BACKTEST
SIM
LIVE
```

每个 Trading Runtime 是其全部 mutable trading authorities 的唯一所有者，并必须独占：

```text
Clock
Event Bus
MarketData Registry
MarketData Inbound Queue
MarketData Processor
MarketData Audit
MarketData Pipeline
MarketData Cache
Bar Aggregation
Broker Inbound Queue
Order Manager
Position Manager
Position Allocation Manager
Position Reservation Manager
Account Manager
Strategy Ledger Manager
Risk Service
Risk Reservation
Fee Authority
Settlement / Margin Service
ExecutionProcessor
Execution Transaction Store
Applied Projection Ledger
Outbox
Persistence Store
Checkpoint Participants
Recovery State
Runtime Audit
```

每个 Trading Runtime 当前只允许绑定一个 Account authority、一个 resolved Market Product 和一个 Account currency。市场或币种
不兼容的 Cluster 必须由 Planner 拆分到不同 Runtime 或 fail closed；不得为了跨市场组合在 Runtime 内共享 Account、Position、
Risk、Reservation 或 Settlement authority。

Research Runtime 只拥有：

```text
Research execution state
Dataset state
Calculation state
Research Result state
Research Artifact state
```

Research 不得仅为满足共享父类、Manager 数量对称或代码复用而创建 Order、Position、Account、Broker、Reservation、Execution Transaction 等 Trading Authorities。`OnlyResearchRuntime` 通过最小 structural Runtime product boundary 独立实现，不继承 trading-shaped `OnlyRuntime`。

Research Dataset 的正式 authority 是 immutable Dataset Snapshot；Historical Cache 只负责 acquisition optimization，不是
Dataset authority。Provider identity 只进入 provenance，不进入 Dataset semantic identity。`onlyalpha.research` 不得导入
Trading authorities，Dataset Store 不得提供 append、update、overwrite 或 invalidate 语义。

Research 与 Trading Calculation backend 可以采用不同执行模型，但必须共享同一 Calculation semantic identity；Research
backend 不得消费 Definition 未声明的 semantic input，不得 fallback 到 Trading backend。Research Calculation 只能消费完整
verified Dataset Snapshot，不得为了执行 batch calculation 提前创建 Research Runtime 或伪造 Trading authorities。

Research Calculation Result 的 durable authority 是以 `calculation_fingerprint` 为 key 的 immutable Calculation Result Store。
Calculation fingerprint、logical Result Content fingerprint、Calculation Result fingerprint 与 physical partition byte hash 必须
分层；同一 Calculation 的相同 Result 重复提交幂等，不同 Result 必须作为 deterministic conflict fail closed。Store 必须在
staged atomic publication 与正式 load 时验证 Dataset/Graph linkage、完整 partition set、schema、timestamp、logical semantic hash
和 byte hash；不得 overwrite/repair corrupt target，不得提供 cache、fallback、update、delete 或 unverified public load 语义。

Research Job v1 的正式 resolved contract 只引用 exact Dataset Snapshot fingerprint 与 canonical Calculation Graph；其完整
semantic identity 已由现有 `calculation_fingerprint` 表达，不得增加重复 Job/Plan fingerprint。Job orchestration 只能以 Result
Store `load_verified()` 判定复用，只有 `RESULT_NOT_FOUND` 可以进入 P7.2 execution 与 P7.3 immutable commit；corrupt/invalid
authority 必须 fail closed，不得用 `exists()`、recompute、repair、delete 或 overwrite 掩盖。成功 Outcome 显式区分
`EXECUTED/REUSED`，但不得改变 Calculation/Result identity。P7.4 recovery 只采用 deterministic re-entry，不创建 mutable Job
database、scheduler、worker lease 或第二套 recovery authority；P7.11 Runtime 只可编排该既有 authority。

Research Sweep v1 是 multi-job composition，不是第二套 Calculation/Job/Result authority。Graph Template 只使用 template-local
TemplateNodeId、exact type reference、requested parameters 与 template dependency；TemplateNodeId 不等于 node fingerprint 或 alias，且
不得进入 materialized Definition/Graph/Result identity。Definition 必须通过 exact type-owned、backend-neutral resolver 完整重建
parameter-derived warmup/source/default/constraint，禁止替换 resolved Definition.parameters。Finite explicit candidates 与 dimensions 必须
canonicalize，semantic duplicate fail closed；每个 Cell 的唯一 identity 是 existing calculation_fingerprint，不创建 Trial/Cell/Sweep
fingerprint。SweepExecutor 只能 sequential 调用 OnlyResearchJobExecutor；恢复只采用 deterministic re-entry + verified REUSED/EXECUTED，
不得创建 Sweep/Trial Store、mutable progress、checkpoint、scheduler、lease 或 worker pool。P7.11 Runtime 必须保留 SweepExecutor ownership。

Research Factor / Feature / Score 继续使用唯一 Calculation Definition / Graph / Result / Job authority。Feature 只是
`(node_fingerprint, output_name)` output port；Raw `FACTOR_VALUE` 与 `[0,1]` Decimal `FACTOR_SCORE` 是不同 machine-readable
semantic。TIME_SERIES 与 CROSS_SECTION execution shape 由 Definition 决定，executor 按 semantic node、stable instrument 与
exact event-time axis 执行；不得创建 Factor/Feature/Score Store、Graph、Job 或复用 mutable Trading Factor lifecycle。

Research Evaluation Plane 使用非 Factor 的 `TARGET` Calculation kind。Target 与 Feature 必须使用独立 Graph；Target V1 只可直接
消费 Dataset external source，Indicator/Factor 不得消费 Target，Target 也不得依赖任何 Calculation node。Forward Return 只使用
canonical per-instrument bar offset、保留 observation axis、future tail 为 NULL，并复用 Calculation Result / Job authority，不创建
Target/Label Store。Statistics 通过 exact Feature/Target series reference verified-load 同一 Dataset Snapshot 的 Calculation Result，按
instrument + timestamp 做 pairwise complete alignment；IC/Rank IC 与退化 status 使用显式 Decimal semantics。Statistics fingerprint、
Result Content fingerprint 与 Statistics Result fingerprint 分层；immutable Statistics Result Store staged publish、verified load、
idempotent reuse、deterministic conflict 与 corruption fail-closed。不得把 Statistics 伪装成 per-instrument Calculation node，不得创建
Optimizer、Experiment/Trial Store，也不得激活 Research Runtime。

Research Result 是 exact Statistics Result composition authority，Statistics Result 是 rows semantic authority；Research Artifact
只是由 verified Research Result 精确成员确定的 immutable materialized read view。Artifact 可以复制 Statistics rows，但不得扫描
Store 猜测 composition、重新计算 Statistics、反向写回或恢复上游 authority。发布后的 V1 Artifact 只含严格 Manifest 与 canonical
Statistics Parquet，必须在不访问 Dataset/Calculation/Statistics/Research Result Store 时完成 byte、row、Statistics identity、Research
Result identity 与 Artifact logical identity 验证。Artifact 不得新增 Plan/Result semantic identity、Query/API/Web、Analytics、mutable
Experiment state 或 Trading/Research 通用 Artifact framework；P7.11 Runtime 只物化并 verified-load exact Artifact。

Research Query/API 的唯一 upstream read boundary 是 portable Research Artifact。Query Core 只可通过最小 Reader Port 调用
`load_verified(exact_research_result_fingerprint)`，并进行 exact lookup、projection、半开时间范围过滤、稳定排序和 cursor 分页；
不得读取 physical Artifact layout、访问任何 execution Store、重算 Statistics、持久化 Query Result、建立 Catalog/latest/search/cache。
Query Result 是 ephemeral deterministic projection，不是 authority。HTTP transport 位于独立 `onlyalpha-api` workspace package，Core
不得依赖 FastAPI/Pydantic/Uvicorn；Query Core 保持 Decimal/int，HTTP v2 必须把 Decimal、event nanosecond 与 cursor 编码为 canonical
string。Web admission 后 exact time 使用 `bigint`、Decimal 使用 string；chart number/seconds 只是显式可失败 projection，不得成为
authority。corrupt 不得映射为 missing/empty/rebuild。Research Runtime 不得使用 Query/API/Web 作为 execution infrastructure；Live
Runtime Factory 与 Trading/Live Web control 仍未实现。

Research Execution Control Plane 的 durable operational authority 是 PostgreSQL `ResearchRun + ResearchRunAttempt`。Run 表达长期 intent
与总体 outcome；Attempt 表达一次 execution ownership/history，二者 identity 不得合并。每个 Run 最多一个 ACTIVE Attempt；claim 必须在
同一短事务内锁定 Run、创建 Attempt，并在首次 claim 时完成 `QUEUED -> RUNNING`。Lease 只使用 PostgreSQL server clock，heartbeat、
expiry 和所有 finalization 必须验证 exact Attempt ID、Worker Instance ID、ACTIVE state 与未过期 lease；过期 Attempt 永不复活，只能创建
新 Attempt。Retry 有界且只发生在 Attempt 层，Run 在 retry/recovery window 保持 RUNNING，terminal Run 不得重开。

Scheduler 只协调 eligible Run、expiry、claim 与 dispatch；Worker 必须重新 verified-load Dataset、重新解析 canonical Specification、比较
admission evidence，并只通过 `OnlyEngine -> OnlyResearchRuntime` 执行。Result/Artifact verified commit 必须先于 fenced PostgreSQL
`Attempt SUCCEEDED + Run COMPLETED`。Recovery 只采用 immutable semantic authority 的 deterministic re-entry/reuse，不得建立 mutable
Factor/node/progress checkpoint、第二套 Research Result truth 或 in-memory durable queue。Heartbeat/数据库不可用意味着 ownership
uncertain，Worker 不得继续 operational finalization。HTTP command/Web control 仍不属于该执行协议。

外部 Product mutation retry 的唯一 durable authority 是 PostgreSQL `ProductCommandReceipt`。全局 canonical UUID4 Command ID 绑定 exact
Command kind、operational command fingerprint 与当前 authoritative resource reference；Receipt 不是 lifecycle state machine。Create
Research Run 的历史 `{specification: ...}` fingerprint bytes 保持不变，Cancel 只以 exact `run_id` 形成 operational fingerprint，任何
transport/actor/API metadata 均不得进入 semantic identity。Create 的 `ResearchRun + Receipt` 与 keyed Cancel 的 accepted Run effect +
Receipt 必须在一个事务提交；retry 通过 Receipt 重载当前 Run，mismatch、dangling 或 corruption fail closed。v2 Cancel 的
`Idempotency-Key` 仍为 optional，无 key 时保留自然 Run-state idempotency。

Product Kernel 在 production startup verification 后、RECOVERING 前取得专用 PostgreSQL session advisory guard，并在 mutation admission
关闭、draining 完成后释放；第二个 mutation-capable Kernel 必须启动失败。RECOVERING 通过 verified sorted frozen Strategy inventory 调用
既有 Freeze Projection Reconciler，使 immutable Strategy truth 单向收敛 PostgreSQL projection。Research Worker Attempt/Lease/Fencing 恢复
仍由 ADR 0090 的执行协议拥有，不进入 Kernel Host。

Cancellation recovery 必须遵守 semantic-fact-first：lease expiry 只证明 Attempt ownership 丢失，不能自行把
`CANCEL_REQUESTED` 投影为 `CANCELLED`。无 ACTIVE Attempt 后，Application reconciliation 必须从 canonical Specification resolution
推导 exact Research Result Plan，并通过 read-only `load_verified()` 同时证明 exact Research Result 与 exact Artifact。完整证据在
authoritative inspection point 已存在则投影 `COMPLETED`；完整证据 absent 则投影 `CANCELLED`；corrupt/conflicting authority 必须
`FAILED` fail closed。该终态通过 PostgreSQL exact revision/state + no-ACTIVE transaction 原子提交；不得创建新 Attempt、继续缺失的
semantic work、让 Scheduler/PostgreSQL adapter 读取 semantic Store，或让 retry budget 覆盖已完成事实。

当前 Revision-backed Strategy executor 不接收 Runtime Context，也不暴露或读取 Runtime mode；Position、Fee、Market Rule 与 Durable
Execution Capability 的生产经济路径保持 mode-neutral，并由架构门禁冻结。Runtime mode 只可留在 Control Plane 的 identity、planning、
driver 和 lifecycle composition，不得重新进入 Strategy 或经济权限判断。

Backtest / Sim / Live 追求 Trading Semantic Equivalence，而不是 Driver Implementation Equivalence。差异主要限于：

```text
Clock Driver
MarketData Driver
Broker Adapter
Lifecycle Driver
```

进入 Trading Kernel 后只能消费 normalized domain input、normalized broker facts、market instructions 和 economic context，不得消费 Runtime name 作为经济权限或业务规则。

禁止：

- Manager 被多个 Runtime 共享；
- Cluster 持有 Manager；
- Strategy 持有 Manager；
- Factor 持有 Manager；
- DataSource 或 Broker Gateway 持有 Manager；
- 插件直接修改 Runtime 状态；
- 通过全局单例保存 Runtime 交易状态。
- Strategy 根据 Runtime type 分支交易逻辑；
- Trading economics 或 Execution Support 根据 Runtime type 决定权限；
- 新建 `SimOrderManager`、`LivePositionManager`、`BacktestAccountManager` 等 Runtime 专用经济真值；
- SIM 连接或向 Real Broker 提交订单。

跨组件状态修改必须由 Trading Runtime 内正式 Service 或 Processor 编排。

---

## 8. Cluster、Strategy、Factor、Indicator

### 8.1 Cluster

一个 Cluster：

```text
One Strategy
+
Zero or more Factors
+
Indicator Scope
+
Subscription Scope
+
Strategy Ledger Scope
```

Cluster 是 Trading Runtime 的隔离 workload，不是 Strategy 本身，也不是 Research Job。

Cluster 不得：

- 访问其他 Cluster 私有订单；
- 访问其他 Cluster Allocation；
- 访问其他 Cluster Ledger；
- 直接访问 Broker；
- 直接访问 Runtime Event Bus；
- 推进 Runtime Clock；
- 修改账户级 Manager。

### 8.2 LIVE Manual Workload（目标合同）

人工交易只属于 `LIVE`。目标 `MANUAL` workload 与 Strategy Cluster 并列，但不得伪装成 Strategy；它拥有明确的 workload
identity、Allocation scope、Ledger scope、operator provenance、permission 和 audit，其 mutable Manager 仍由 Live Runtime 独占。

人工订单固定经过：

```text
Authenticated Operator Intent
→ Market Rule
→ Risk
→ Reservation
→ Order
→ Real Broker
→ Broker Inbound Queue
→ Durable Transaction
→ Ordered Projection
→ Manual Allocation / Ledger
```

Web/Application 只能通过 `OnlyEngine` 和正式 Command boundary 操作，不能直接访问 Manager、Broker SDK、Position 或 Account。
Backtest、Sim、Research 不接受产品级交互式人工订单；Scenario 中预声明的 deterministic action 不是 Manual workload。

### 8.3 Research Job / Research Plan

Research Job 是研究任务，不得伪装成 Trading Cluster。它可以描述：

```text
Dataset
Universe
Time Range
Indicator / Factor / Feature definitions
Parameter Grid
Statistics specification
Output specification
```

Research 可以复用纯 Indicator / Factor 定义和 canonical data model，但不经过 Strategy、Order、Broker、Risk Reservation、Trading Account、Trading Position 或 Durable Trading Transaction。Web 只能查询 immutable Research Result / Artifact，不得操作 Runtime internal mutable state。

### 8.4 固定计算顺序

同一行情时间片的业务顺序必须显式确定：

```text
MarketData Validate / Process
→ Cache / Aggregation
→ Indicator
→ Time-Series Factor
→ Cross-Section Factor
→ Factor Snapshot / Score
→ Strategy
→ Risk
→ Order
```

不得依赖：

- 字典插入顺序；
- Set 顺序；
- Python 导入顺序；
- Cluster 注册顺序；
- Handler 注册偶然顺序；
- 外部 SDK 回调偶然顺序；
- 线程调度偶然顺序。

需要排序时，必须使用稳定、业务可解释的 Key。

### 8.5 Indicator

Indicator：

- 只能消费已验证的行情；
- 不具有交易权限；
- 必须显式处理 Warmup；
- 必须拒绝乱序输入或按正式合同去重；
- Checkpoint 能力必须显式声明；
- 恢复后输出必须与连续运行一致。

### 8.6 Factor

Factor：

- 可以组合 Indicator；
- 产生 Snapshot 和 Score；
- 不具有下单权限；
- 不直接访问 Account、Position 或 Broker；
- Cross-Section 调度必须由正式 Runtime/Cluster 流程完成。

### 8.7 Strategy

Strategy：

- 唯一生产语义权威是 immutable `StrategyRevision`，唯一身份是 `strategy_fingerprint`；
- 只能通过 `StrategyExecutionResolver → exact TRADING Calculation graph` 执行；
- 每个 admitted final RAW BAR 同步产生显式 `StrategyDecision(ELIGIBILITY/ENTRY/EXIT)`；
- 不接受任意 Python `OnlyStrategy` subclass、callback 或 Cluster strategy object 注入；
- 不读取 Account、Position、Order、Risk、Broker、Execution 或 Runtime type；
- `StrategyDecision` 不是订单、仓位规模、资金分配、风险结论或 Broker command；
- Calculation 状态能力必须在 TRADING registration 显式声明为 `STATELESS/CHECKPOINTABLE`；
- CHECKPOINTABLE Calculation 必须绑定 schema version，并保持连续执行与 checkpoint/restore 等价。
- Research Calculation 在执行前必须一次性冻结 exact per-node RESEARCH implementation plan；Calculation Result 与 Research
  Calculation Execution Evidence 分别拥有 semantic output 与 implementation provenance，二者 identity 不得合并。
- Freeze-eligible completed Research Run 必须显式引用 exact immutable Execution Evidence；legacy Run 缺少 provenance 时不可 Freeze，
  且不得由 current Registry 回填或推断 historical RESEARCH implementation。
- Trading Admission 只从 Run-linked Execution Evidence 读取 historical RESEARCH implementation，并要求 exact-node、system-owned
  profile/corpus、actual RESEARCH/TRADING backend execution 产生的 Equivalence Evidence V2；V1 不可升级或用于 Admission。
- raw `OnlyStrategyRevision` 不可发布到 executable authority；只有 Freeze 内部 publisher 可写 `strategy/frozen-revisions`，Runtime、
  Cluster、Backtest、SIM 与 Promotion 只可持有 `OnlyStrategyRevisionReader`。

旧 `OnlyStrategyId` 仅可作为内部历史交易事实归因类型保留，不是 Strategy identity、authoring 或 execution authority，也不得从
`onlyalpha.strategy` public surface 导出。

---

## 9. Monorepo 包职责

### 9.1 Core

路径：

```text
src/onlyalpha/
```

Core 包含：

- Domain；
- Engine；
- Runtime；
- Cluster；
- Strategy / Factor / Indicator 公共边界；
- DataSource / Broker Port；
- Market Profile 和 Rule Engine；
- Risk / Order / Execution；
- Position / Allocation / Account / Ledger；
- Fee / Settlement；
- Persistence / Checkpoint / Recovery；
- Result / Analytics / Artifact / Report；
- Plugin SPI；
- CLI 和 Application Service。

Core 不得导入具体外部插件：

```text
onlyalpha_plugin_broker_virtual
onlyalpha_plugin_tushare
onlyalpha_plugin_miniqmt
```

Core 可以定义 Port、CreateRequest、Descriptor、Capability 和公共 DTO，但不能依赖插件实现。

### 9.2 Virtual Broker

路径：

```text
packages/fake/onlyalpha-plugin-broker-virtual/
```

职责：

- 实现 Broker SPI；
- 订单接受、拒绝和撤销；
- Next-Bar Matching；
- Slippage；
- Fill Plan；
- Whole / Partial / Multi-Fill；
- 确定性发布；
- Broker Checkpoint；
- 标准 Broker Update。

不得：

- 修改 Account；
- 修改 Position；
- 修改 Risk；
- 成为账务真值；
- 直接决定正式 Account Fee；
- 在插件中复制完整市场规则；
- 绕过 Broker Inbound Queue。

### 9.3 Tushare

路径：

```text
packages/provider/onlyalpha-plugin-tushare/
```

职责：

- 配置解析；
- Token 读取；
- SDK 调用；
- 历史行情请求；
- 数据标准化；
- 严格校验；
- Cache 协作；
- Factory 和 Entry Point；
- 环境诊断。

不得：

- 导入模块时访问网络；
- 修改 Runtime 交易状态；
- 把复权价格隐式当作撮合价格；
- 将 SDK 原始对象泄漏到 Core；
- 持有 Runtime Manager。

### 9.4 MiniQMT

路径：

```text
packages/provider/onlyalpha-plugin-miniqmt/
```

职责：

- Historical Worker；
- DataSource Adapter；
- Live Bar Adapter；
- Broker Adapter；
- SDK 数据到 Domain/Update 的转换；
- 配置和环境能力检查；
- 进程隔离；
- 协议和兼容性诊断。

不得：

- 让 Core 依赖 `xtquant`；
- 在 Core 导入 MiniQMT；
- 绕过 MarketData 或 Broker Inbound Queue；
- 直接修改 Manager；
- 未完成对账和恢复前启用真实资金；
- 把 Fake SDK 验收等同于真实产品验收。

---

## 10. 公共 API 与内部边界

外部 Product actor 使用 `onlyalpha-client` / canonical Product HTTP contract。插件与内部工程组合按职责使用：

```text
onlyalpha.config
onlyalpha.domain.*
onlyalpha.strategy
onlyalpha.factor
onlyalpha.indicator
onlyalpha.plugin.api
```

以下通常属于内部实现：

- Runtime Planner；
- Assembly Plan；
- Runtime/Cluster Session；
- Manager；
- Registry 内部容器；
- ExecutionProcessor 内部步骤；
- Recovery Orchestrator 内部状态；
- Persistence Store 具体 Schema；
- Projection Applier；
- 内部 Audit Store。

P9.K.8 已从根包及 broad `onlyalpha.engine/runtime/cluster` aggregators 移除 mutation constructors。具体 Engine/Runtime/Cluster
implementation modules 只允许内部、测试、scenario、operator 或 composition owner 使用；`onlyalpha.config` 的 Assembly DTO 仍是内部组合值。
不得据此把已删除的 legacy `PAPER/SHADOW` 或内部编排对象升级为长期兼容合同。

规则：

- 公共 API 变更必须同步测试和文档；
- 不得仅因为内部模块可导入，就将其当成稳定 API；
- 插件不得依赖内部 Manager；
- 新公共接口必须有类型、合同测试和版本考虑；
- 删除旧公共接口前必须确认没有正式配置、示例或插件使用。

---

## 11. Market Product 与规则

### 11.0 Market Product Composition Authority

P5.3 已将 Trading Runtime 的生产组合一次性切换到唯一入口：

```text
OnlyMarketProductConfig
→ OnlyMarketProductFactoryRegistry
→ OnlyMarketProductFactory.resolve(...)
→ OnlyResolvedMarketProductBinding
→ Trading Runtime Composition
```

Market Product 属于 Trading Plane。Concrete Market Product Plugin 拥有具体市场知识并只依赖 Core Contract；Core 不得依赖 concrete market package。Research 不要求 Market Product Binding。

必须保持：

- Plugin provider identity 与 Product economic identity 分离；
- Product identity 只能用于 evidence、audit、artifact、fingerprint 和 compatibility proof，不得作为 Core behavior selector；
- Composition identity 只基于 resolution 后的 effective product/reference/policy/fee/config authorities，不得直接使用 raw YAML identity；
- Binding immutable，且不得持有 Order、Position、Account、Risk、Execution 或其他 mutable Runtime authority；
- Factory resolution context 只暴露 composition-time ports，不暴露 Engine/Runtime internals；
- Registry 只负责显式 factory lookup，unknown、duplicate、ambiguous 和 mismatch 必须 fail closed；
- 不得 implicit Generic fallback，不得 import-time global registration；
- Runtime type 不进入 Market Product economic contract；
- Market Product 与 Broker、DataSource、Risk、Execution Support 分离；Plugin 计算市场语义，Core 修改交易状态。
- Canonical Market IR 只包含 instrument economic terms、session、price、quantity、position、short、settlement 与 margin；不得包含 matching、slippage、latency、fill plan/schedule 或 simulation liquidity；
- `onlyalpha-market-generic-t0-cash` 定义 `GENERIC_T0_CASH@1` 的 Reference、Policy Compiler 与 Market Fee Pack，但不是 Core default 或 fallback；
- `onlyalpha-market-cn-ashare` 定义 `CN_A_SHARE_CASH@2025.1/2026.07` 的版本化 Reference、Policy Compiler 与 Market Fee Pack；
- `onlyalpha.market_products` entry-point discovery 是 concrete Market Product 的安装入口，Core composition root 只持有 neutral Registry，不硬注册 concrete product。

Generic 与 CN A-share 已同时完成生产 cutover。旧 Profile Registry、Core A-share Reference/Rules、concrete fee-pack selection 和 Runtime concrete-market branch 已删除；不得恢复 bridge、compatibility adapter、deprecated alias、Core hard registration 或 implicit fallback。

市场规则链固定为：

```text
OnlyMarketProductConfig
→ Market Product Factory Registry
→ Resolved Market Product Binding
→ Plugin-owned Policy Compiler
→ Runtime Rule Engine
→ Restricted Instruction / Decision
```

Market Product Plugin 拥有版本化市场语义；Binding 是一次 resolution 后的不可变组合事实，不是业务 Manager。

规则应由相应组件消费已编译的 Decision 或 Instruction。

禁止：

- Strategy 硬编码税率；
- Strategy 硬编码 T+1；
- Broker 硬编码完整市场规则；
- Risk 和 Broker 分别实现不同涨跌幅；
- Planner 直接猜测 Settlement Date；
- 根据证券代码前缀猜 board，而忽略 Reference；
- 在多个模块复制同一费用规则；
- Product 已配置但 Runtime 仍静默走 Generic 假设；
- 未知市场状态自动放行。

无法确定规则时必须 Fail Closed，并产生可诊断原因。

`OnlyMarketRuleEngine.evaluate_pre_trade()` 是 Runtime 唯一正式 Pre-Trade Market Rule Authority。Plugin-owned Reference 提供证券事实，
Plugin-owned Compiler 提供版本化制度并在 evaluate 前解析最终 Session/Price/Quantity Policy。Order、Risk、Strategy 与
Broker 不得复制交易阶段、价格带、Tick、申报数量或零股规则；主错误码必须来自固定顺序中的首个失败 Evaluation。

`CN_A_SHARE_CASH` 的板块、历史 ST、停牌、交易单位、价格精度和正式前收盘价只能来自版本化
CN A-share Market Product Plugin Reference，并由 plugin-owned authority 按 `Instrument + TradingDay` 解析。Runtime Factory
不得读取自由 `instrument_attributes`，不得以当前状态或上一根 Bar 回填历史 Reference。Registry 指纹必须参与
Runtime 兼容性、Artifact 和 Checkpoint 恢复校验。

Product identity 或插件存在不代表产品范围被升级；正式能力仍以有限产品合同、Conformance 和产品纵切面为准。

---

## 12. MarketData 合同

正式行情路径：

```text
DataSource
→ MarketData Inbound Queue
→ Sequence / Dedup / Gap / Quality
→ Audit
→ Pipeline
→ Cache / Aggregation
→ Indicator / Factor / Strategy
```

历史回放：

```text
Historical DataSource
→ Replay Service
→ Backtest Clock
→ Same MarketData Pipeline
```

约束：

- DataSource 不推进 Backtest Clock；
- 只有 Historical Replay Service 可以推进 Backtest Clock；
- Historical 和 Live 应复用同一 Domain Bar/Tick；
- Bar 必须明确 `[start, end)`；
- 只允许 Closed Bar 进入依赖 Closed Bar 的计算；
- Session 外数据必须显式拒绝并记录原因；
- Watermark 只能由成功进入正式 Pipeline 的数据推进；
- Provider 原始尾部不能直接成为 Processed Watermark；
- Catch-up、Dedup 和 Gap 必须有唯一 Authority；
- 不能通过修改 Bar 时间制造验收通过。

### 12.1 Streaming Bootstrap / SIM 当前基线

当前 product-neutral Streaming + SIM bootstrap 的调用顺序是：

```text
Subscribe and buffer live input
→ Capture / Freeze Bootstrap Boundary
→ Historical Request
→ Worker Validation
→ Parent Validation
→ Historical Replay
→ Indicator / Factor Ready
→ Historical Observation
→ Watermark
→ Live Handoff
```

不变量是 logical bootstrap boundary 明确、订阅与历史回放之间不丢数据、catch-up 顺序确定；这些性质已迁移并由正式 SIM 测试冻结，不能把当前调用顺序臆写成另一种行为。

必须区分：

```text
Provider Raw
Accepted by Worker
Replay Attempted
Replay Processed
Replay Rejected
Pipeline Last Successful Bar
Historical Watermark
```

这些计数和尾部不得互相替代。

这些边界由当前 Streaming/SIM authority 持有；不得恢复 `PAPER` 产品依赖，也不得复制第二套 streaming authority。

Streaming Recovery 的完成必须由 Phase revision、suffix reconciliation 与 continuity proof 验证，不能由固定 wall-clock 时长定义。
Timeout 只允许作为按正式 operation budget 派生的 bounded watchdog；到期必须输出 immutable diagnostics，至少包含 phase/revision、
recovery generation/stage/plan、Semantic Lane cutoff、worker/source、confirmed frontier 与 buffered suffix。Diagnostic stage 只读且不得
参与 Runtime control decision。`OnlyStreamingPhaseController` 仍是唯一 Phase authority，`OnlyStreamingSemanticLane` 仍是唯一
MarketData semantic writer；STOPPING 建立后，迟到 loader facts 与 diagnostic progress 都不得越过 cutoff。

---

## 13. Event 合同

Event 用于通知已发生的事实，不作为核心状态迁移的唯一驱动力。

规则：

```text
Command / Function Call
→ Validate
→ Mutate / Commit
→ Publish Fact Event
```

禁止：

- Event Handler 决定 Manager 核心状态迁移；
- 依赖 EventBus priority 完成业务准备步骤；
- 在状态提交前发布成功事件；
- 失败后发布完整成功事实；
- 用 Event 重建本应来自 Transaction Store 的成交权威。

Recovery Event Gate 必须保证：

- 恢复历史 Direct Event 不重复外发；
- Bootstrap 事件有界；
- Runtime Open 前不泄漏不完整状态；
- Continuation Outbox 只在正式 Open 后交付；
- 失败语义可预测。

当前不得声称具备：

```text
Subscriber ACK
Delivery Watermark
Exactly-once Delivery
Durable Direct Event Journal
```

---

## 14. Broker 合同

Broker Gateway 只负责外部交易适配。

正式路径：

```text
Order Service
→ Broker Execution Service
→ Broker Gateway
→ External System
→ Broker Inbound Update
→ Broker Inbound Queue
→ ExecutionProcessor
```

禁止：

- Gateway 直接修改 Order Manager；
- Gateway 直接修改 Position；
- Gateway 直接修改 Account；
- SDK Callback 直接调用多个 Manager；
- Broker Update 绕过 Runtime Queue；
- Gateway 成为本地账务权威；
- 用 Broker Snapshot 静默覆盖本地历史；
- 用外部回报顺序作为业务确定性顺序。

重复、乱序和迟到 Update 必须通过正式 Identity、Sequence、Dedup 和 Reconciliation 处理。

### 14.1 LIVE Genesis Import（目标合同）

LIVE 首次 Open 前必须从 exact Broker evidence 以 immutable、versioned、idempotent genesis/import transaction 导入当前：

```text
Cash
Position + Cost Basis
Open Order
Pending Settlement
Broker / Account Identity
Evidence Timestamp / Source / Fingerprint
```

导入完成后必须验证 schema、identity、aggregate 与 reconciliation，再允许 Runtime Open。Broker 历史成交和历史资金流水只作为
evidence attachment 保存，不伪造为本地历史 Trade/Cash transaction。已有本地 committed history 时，Snapshot 只能作为 evidence，
不能覆盖；冲突无法解释时 fail closed。

### 14.2 LIVE Liquidation（目标合同）

清仓只支持“单个 LIVE Runtime”和“一个 Engine 当前拥有的全部 LIVE Runtime”两个作用域。全量清仓使用一个 Engine-level
parent request 和每个 Runtime 的独立 durable child request；父请求只编排和聚合，不是跨 Runtime economic transaction。

Runtime 接受清仓请求后必须撤销新的开仓权限，同时继续处理行情、撤单、平仓、Broker facts、对账和恢复。完成、部分完成或
阻断后，未经授权人工显式复位不得重新开仓。清仓不得直接修改 Position；每个 close intent 仍经过 Market Rule、显式
Liquidation Risk Policy、Reservation、Order、Broker、Durable Transaction 和原 Allocation/Ledger 归属。

默认价格升级层级是 `对手一价 → 显式支持的市价执行 → 显式斩仓价`。具体等待时间、重报、滑点、Market Order 表达和斩仓算法
必须在实现前由 versioned policy、Market Product instruction 与 Broker capability 冻结；当前文档不得臆造。真实清仓非原子，
必须报告 `COMPLETED/PARTIALLY_COMPLETED/BLOCKED/ABORTED` 及剩余数量，不得把“已发单”描述为“已清仓”。

---

## 15. Durable Execution 合同

当前正式 Durable Trade Capability：

```text
Market Product : GENERIC_T0_CASH@1
Account        : CASH
Order Type     : LIMIT
Position Side  : LONG
Position Mode  : NETTING
Open           : BUY OPEN
Close          : SELL CLOSE
```

不可破坏的核心合同：

```text
One Fill
=
One Immutable Prepared Transaction
=
One Committed Transaction
```

每个 Fill 必须具有：

```text
Stable Fill Identity
Stable Payload Fingerprint
Per-Order Fill Index
Execution Sequence
Prepared Transaction
Committed Transaction
Ordered Projection
Projection Ready
Durable Outbox Intent
```

禁止：

- 多个 Fill 合并成一个可变事务；
- Commit 后修改 Transaction；
- 使用外部 Source Sequence 代替 Fill Index；
- 正式 Capability 回退到 Legacy Mutation；
- Projection 外跨多个 Manager 手工更新；
- 失败后补写伪事实使结果对齐；
- 通过删除断言放宽经济不变量。

### 15.1 Operation Kind

当前正式 Runtime Operation Kind：

```text
ORDER_ACCEPTED
TRADE_FILL
ORDER_TERMINAL
SETTLEMENT_MATURITY
FEE_RECONCILIATION
```

`ORDER_ACCEPTED`：

- 冻结 Broker Accepted identity 和 payload；
- 投影 Order 与相应 Reservation stage；
- 不伪造成 Trade。

`TRADE_FILL`：

- 必须有真实 Trade Identity；
- 必须进入 Trade Result；
- 必须包含经济事实。

`ORDER_TERMINAL`：

```text
CANCELLED
REJECTED
EXPIRED
```

规则：

- 不得伪造 Trade ID；
- 不计入 Trade Count；
- 不产生 Trade PnL；
- 不产生 Trade Settlement；
- 只投影终态需要的 Order/Reservation/Risk 变化。

`SETTLEMENT_MATURITY` 只按 committed Settlement Instruction 将到期资产/资金投影为可用状态，不重新猜测市场制度。

`FEE_RECONCILIATION` 用新的 durable fact 表达外部 Broker evidence 与历史 Fee Application 的差额；不得覆盖已提交费用历史。

---

## 16. Planner、Transaction 与 Projection

Planner 是纯经济决策边界。

Prepared Transaction 应冻结：

```text
Before State
After State
Economic Fact
Cost Authority
Fee Decision
Settlement Instruction
Reservation Delta
Risk Delta
Ordered Projection
Payload Hash
Authority Hash
```

Projection 应安装或验证 Planner 已决定的结果，不应重新做经济决策。

禁止在 Projection 阶段重新计算：

- Released Cost；
- Realized PnL；
- Fee；
- Settlement；
- Reservation Delta；
- Risk Delta；
- Allocation Attribution。

Projection 顺序属于正式合同。修改顺序时必须：

1. 给出业务原因；
2. 更新 Planner；
3. 更新 Projection Targets；
4. 更新 Recovery；
5. 更新 Checkpoint；
6. 更新 Result/Collector；
7. 增加故障点测试；
8. 更新 ADR。

---

## 17. Position、Allocation 与 Close Cost Authority

正式模型：

```text
Position
=
Account 级聚合仓位权威

Allocation
=
Cluster 级数量和成本归属权威
```

Multi-Cluster Close：

```text
Order Cluster
→ Locate Allocation
→ Validate Position / Allocation Aggregate
→ Calculate Released Cost Once
→ Calculate Realized PnL Once
→ Position / Allocation / Account / Ledger / Fact consume same result
```

必须保持：

```text
Position Quantity
=
sum(Allocation Quantity)

Position Cumulative Cost
=
sum(Allocation Cumulative Cost)

Position Released Cost
=
Allocation Released Cost
=
Committed Fact Released Cost

Position PnL Delta
=
Allocation PnL Delta
=
Account PnL Delta
=
Strategy Ledger PnL Delta
=
Committed Fact PnL Delta
```

禁止：

- Position 和 Allocation 分别计算释放成本；
- Account 重新计算 Close PnL；
- Ledger 重新计算 Close PnL；
- 无法归因时回退到账户平均成本；
- Unallocated Close 静默成功；
- Cross-Cluster Close 未定义时自动调拨；
- 增加 `legacy_close_cost` 一类兼容开关。

无法解释的成本必须在 Commit 前 Fail Closed。

---

## 18. 精度规则

交易、成本和费用计算必须使用 `Decimal`。

正式成本权威优先保存：

```text
cumulative_open_price_quantity
```

平均价格是派生值，不得反向成为精确成本权威。

规则：

- 使用局部 Decimal Context；
- 明确 Precision；
- 明确舍入模式；
- 不修改全局 Decimal Context；
- Money 按 Currency Precision 量化；
- Price 按 Instrument Precision/Tick 量化；
- Quantity 按 Quantity Increment 量化；
- 最终完全平仓时数量和累计成本必须严格归零；
- 不使用 Binary Float 参与正式账务计算；
- 序列化 Decimal 使用字符串。

任何精度修改都必须覆盖：

```text
Whole Fill
Partial Fill
Multi-Fill
Different Fill Price
Fee
Positive PnL
Negative PnL
Zero PnL
Full Close
Checkpoint / Restart
```

---

## 19. Account 与 Strategy Ledger

Account：

```text
Runtime 级账户权威
```

Strategy Ledger：

```text
Cluster 级虚拟资金和收益归因权威
```

两者必须消费同一份 Committed Economic Fact。

不得：

- Account 从 Position Average 重算 PnL；
- Ledger 从 Allocation Average 重算 PnL；
- 为通过对账只修正 Ledger；
- 以某一个 Cluster Ledger 与共享 Account 直接比较；
- Strategy 维护完整独立账户副本；
- Broker Snapshot 静默替换本地 Account。

Multi-Cluster 对账必须比较：

```text
Account
与
所有正式 Strategy Ledger 的聚合
```

---

## 20. Risk 与 Reservation

所有订单必须在创建前经过 Risk。

正式顺序：

```text
Strategy Intent
→ Market Rule Validation
→ Risk Evaluation
→ Reservation
→ Order Creation
→ Broker Submission
```

Reservation 是正式交易权威的一部分。

Partial/Multi-Fill 下必须：

- 按 Fill 增量消费；
- 未完成部分继续保留；
- 最终 Fill 完成后释放剩余；
- Cancel/Reject/Expire 通过 Terminal Transaction 释放；
- Duplicate Update 不重复消费；
- Recovery 后与连续运行一致。

禁止：

- OrderService 绕过 Risk；
- Risk 只记录告警但继续创建订单；
- Manager 之间直接互相释放 Reservation；
- 失败后依赖 cleanup 猜测占用；
- 使用生产 `test_mode` 关闭风控；
- Strategy 直接修改 Risk State。

---

## 21. Fee 与 Settlement

费用权威链：

```text
Market / Broker Fee Config
→ Versioned Schedule Registry
→ Runtime Assembly
→ Fee Resolver
→ Fee Instruction
→ Order Fee Accrual Authority
→ Fee Manager
```

必须区分：

```text
FILL
ORDER_CUMULATIVE
```

跨部分成交最低佣金等订单累计费用必须由独立 Authority 管理，不能让每个 Fill 独立重复收取。

Settlement 必须由 Market Rule / Instruction 驱动。

禁止：

- Strategy 计算正式费用；
- Virtual Broker 直接写 Account Fee；
- Account 再次计算 Fee；
- Settlement Manager 自行猜交易日；
- 把费用差额作为测试补丁写入 Ledger；
- 修改历史 Fee Schedule 而不增加版本。

---

## 22. Persistence、Checkpoint 与 Recovery

### 22.1 Durable Authority

成交的 Durable Authority 是 Transaction Store。

Applied Projection Ledger 是可重建的幂等索引，不是成交真值。

Collector 和 Analytics 必须读取正式 Projection Ready / Committed Fact，不得从最终 Manager Snapshot 反推逐笔成交。

### 22.2 Checkpoint

Checkpoint 必须：

- 在明确完成边界创建；
- 记录精确 MarketData Cursor；
- 记录 Participant Schema Version；
- 原子写入；
- 可读回验证；
- 不包含不稳定对象地址；
- 不包含明文 Secret；
- 支持确定性恢复。

新增有状态组件时，必须明确：

```text
Checkpointable
Stateless
Unsupported
```

不得默认忽略。

### 22.3 Recovery

恢复原则：

```text
Restore Durable State
→ Validate Authority
→ Resolve Transaction Tail
→ Resume Ordered Projection
→ Rebuild Derived Index
→ Validate Aggregate
→ Open Runtime
→ Deliver Continuation Events
```

OnlyAlpha 使用 Forward Recovery，不提供跨 Manager Rollback。

禁止：

- Commit 后通过全局回滚恢复；
- 删除 committed transaction；
- 跳过失败 Projection 并继续；
- Recovery 期间发布重复历史事件；
- 用最终 Snapshot 掩盖中间事务缺失；
- 恢复失败后自动创建空 Runtime；
- 旧 Schema 不兼容时静默迁移。

Persistence Schema 或 Checkpoint Schema 变化必须有显式版本和迁移/拒绝策略。

---

## 23. Result、Analytics、Artifact 与 Observation

Result 的逐笔成交来源必须是：

```text
Projection Ready Committed Fact
```

不得从以下来源重建成交：

- Broker 内部状态；
- Order 最终 Snapshot；
- Position 最终 Snapshot；
- Account 最终余额；
- EventBus 历史；
- 测试手工构造列表。

Result 必须保持：

- 可序列化；
- 稳定字段语义；
- 明确空集合 Schema；
- 稳定 Determinism Fingerprint；
- Cluster Scope 正确；
- Runtime Scope 正确。

Artifact 写入要求：

- 原子写入；
- Manifest；
- 相对路径；
- Fingerprint；
- Decimal 字符串；
- Timestamp UTC ISO-8601 或明确 Unix nanos；
- Enum 使用 value；
- 不泄漏 Secret、Token、账户凭据和用户绝对路径。

Streaming Observation：

- 只读；
- 不成为交易状态权威；
- Latest Store 和 Sink 不得阻塞核心 Runtime；
- Observation 丢弃必须可计数和诊断；
- 停止后不得继续增长。

目标 Web 是正式控制面，但不是状态 authority：只读查询通过 Result/Artifact/Observation Query；生命周期和 LIVE 人工命令通过
authenticated Application/API → `OnlyEngine` → target Runtime command。Web 不直接访问 Manager、Broker SDK 或 Persistence，
所有命令必须具有 authorization、stable request identity、idempotency 和 audit。

---

## 24. 配置规则

一个 Cluster 配置应完整描述：

- Cluster；
- Runtime；
- Market；
- Reference Data；
- Universe；
- DataSource；
- Account；
- Broker；
- Strategy；
- Factor；
- Indicator；
- Output。

规则：

- 配置必须版本化；
- 未知字段不能静默吞掉；
- 类型转换必须显式；
- Secret 通过环境变量或安全注入获取；
- 配置不能直接嵌入 Runtime Manager；
- 配置引用的动态类型必须在 dry-run 校验；
- Market Product、DataSource 和 Broker Capability 必须在装配前验证；
- 不兼容 Cluster 必须拆分 Runtime 或 Fail Closed；
- 配置指纹必须稳定。

修改配置 Schema 时必须同步：

```text
Parser
DTO
Validation
Normalized Payload
Fingerprint
Example Config
Contract Test
CLI dry-run
Documentation
```

---

## 25. 插件规则

插件发现依赖 Entry Point、Descriptor 和 Capability。

插件必须：

- 通过公共 Plugin API；
- 提供稳定 Plugin ID 和 Version；
- 声明 Capability；
- 提供配置 Parser；
- 提供 Validate Request；
- 提供显式 Lifecycle；
- 把外部异常转为可诊断错误；
- 不在 import 阶段执行外部副作用；
- 不泄漏 SDK 原始对象到 Core；
- 不读取未声明的全局状态。

Core 不得提供隐藏的具体插件回退实现。

插件不存在或不兼容时必须产生明确失败，不得静默切换到 Synthetic、Placeholder 或其他插件。

---

## 26. 测试分层

统一入口：

```bash
uv run python scripts/test_suite.py calculation
uv run python scripts/test_suite.py research-calculation
uv run python scripts/test_suite.py research-factor
uv run python scripts/test_suite.py research-job
uv run python scripts/test_suite.py research-sweep
uv run python scripts/test_suite.py research-runtime
uv run python scripts/test_suite.py architecture
uv run python scripts/test_suite.py fast
uv run python scripts/test_suite.py integration
uv run python scripts/test_suite.py ashare
uv run python scripts/test_suite.py recovery
uv run python scripts/test_suite.py miniqmt-contract
uv run python scripts/test_suite.py miniqmt-local
uv run python scripts/test_suite.py core-full
uv run python scripts/test_suite.py release
```

主 Marker：

```text
unit
contract
architecture
integration
scenario
conformance
recovery
external
performance
```

附加 Marker：

```text
slow
miniqmt
requires_network
requires_tushare
requires_local_qmt
requires_broker_account
windows
```

Repository-wide Architecture Gate 的唯一正式调用是 `uv run python scripts/test_suite.py architecture`；不得以会先收集全部 workspace
测试的裸 marker 命令替代。P9.K.0 已审计的 direct Engine/Runtime/mutation debt 不得增长；任何新的 external capability 都必须先显式修改
architecture contract 并重新审计。

### 26.1 Lane 选择

| 修改范围 | 最低验证 |
|---|---|
| 纯值对象、纯函数 | 目标单测 + `fast` |
| 公共 API / Plugin SPI | Contract + `fast` |
| Engine / Runtime / Cluster | 对应 product lane + `integration`；Research 使用 `research-runtime` |
| Market Product / A-share 规则 | `ashare` |
| Transaction / Projection / Checkpoint | `recovery` |
| MiniQMT 转换 | `miniqmt-contract` |
| 本地真实 MiniQMT | `miniqmt-local`，仅显式环境 |
| 跨模块或发布变更 | `full` |
| 发布候选 | `release` |

实际运行最窄的正确集合，但不得用“小测试已通过”替代必须的 Recovery 或 Conformance。

### 26.2 测试原则

禁止：

- 删除覆盖来缩短时间；
- 使用 `skip`/`xfail` 掩盖回归；
- 放宽经济不变量；
- 增加生产 `test_mode`；
- 手工构造成功 Fill 替代 Virtual Broker；
- 通过 sleep 修复确定性问题；
- 让离线测试访问网络；
- 普通测试连接真实账户；
- 多个 Worker 共享可写 SQLite；
- 使用本机时区作为隐含输入；
- 只断言最终余额而忽略逐笔事实。

测试应优先复用：

- 固定 Result Fixture；
- 只读 Recovery Baseline；
- MiniQMT Golden Dataset；
- Exact Scenario Input。

但产品纵切面、故障恢复和确定性专项测试必须保留完整 Engine 运行。

### 26.3 真实环境边界

Fake SDK 通过只能证明 Contract，不等于真实产品通过。

真实 MiniQMT：

- 必须显式 opt-in；
- 必须使用对应 Marker；
- 必须串行；
- 不满足环境时记录 Not Executed；
- 不得伪造 PASS。

真实订单：

- 必须使用独立 Manual Gate；
- 必须显式账户和权限；
- 不进入普通 CI；
- 不进入默认 `miniqmt-local`；
- 未完成安全门禁前不得自动提交。

### 26.4 Agent Impact-Aware Verification

Agent 必须区分 inner loop、implementation increment closure 与 Major Milestone closure：

```text
Inner loop
→ targeted tests

Increment Closure
→ affected canonical lanes
→ impact-aware local gate
→ VERIFIED

Major Milestone Closure
→ composed Phase Gate
→ PHASE COMPLETE
```

同一 Major Milestone 内，前一个 increment 达到 `VERIFIED` 后即可进入下一个 increment。`VERIFIED` 必须有实现完整、required
targeted/affected tests、architecture invariants、impact-aware verification、适用的 Layered Quality、Independent Review 和无未解决
Critical / High 的实际 evidence。跨 Major Milestone 只要求当前 Phase Gate 完整通过并达到 `PHASE COMPLETE`，不再存在 Final-SHA
Certification 或独立 certification checkpoint。

`scripts/verify.py` 只用于本地开发验证。必须显式提供 base revision：

```bash
uv run python scripts/verify.py plan --base <base_sha>
uv run python scripts/verify.py agent --base <base_sha>
```

Change set 必须同时包含 `base..HEAD`、staged、unstaged、untracked、rename 和 delete，dirty worktree 不得静默忽略。Impact rule
只能选择 `scripts/test_suite.py` 拥有的 canonical lane/check；不得复制 lane path、marker、worker、coverage 或 release semantics。
Rule 合并必须单调且确定，未知 path fail closed，verification infrastructure 自改必须升级到最宽本地验证。完整成功日志保存在
`test-results/verification/`，console 默认只显示摘要；失败必须显示 gate、exit code、command、有界诊断和完整日志路径。

固定权威边界：

- Targeted 与 impact-aware 结果只是 local development evidence；
- inner loop 默认不收集 coverage，也不在每次小改动后运行 `release`；
- `release` 的正式重型本地语义不变；
- Impact plan 不得缩窄 Phase Gate 的 required job/lane/coverage evidence；
- 历史 `CERTIFIED / ACCEPTED` artifact 只作为历史记录，不再是当前状态或推进 authority；
- 成功的长时间运行日志默认只保存在 evidence 文件中，Agent context 与最终报告只记录 compact summary；仅在失败诊断时读取有界日志。

### 26.5 Quality Acceptance Contract

OnlyAlpha 只有 `Task Gate / Phase Gate` 两种正式验收层级。普通 implementation task 默认只执行 Task Gate；
Implementation Block 不是 Gate。开始前必须冻结 `TASK_BASE_SHA`、Goal、Modification Scope、Impact Scope、Required Behavior、
Expected Acceptance Tests、Expansion Triggers 与 Out of Scope。上游传播到已有正式 contract 保护的 stable authority boundary 后停止；
底层 public authority 修改则沿正式 consumer rules 扩张，Impact union 不得缩小。Task-level Ruff、Format、Mypy、Import Linter、
version sync 与 build 同样必须 impact-aware。

普通 Task 不得仅为“保险”默认执行 `release`、`core-full --coverage`、repository-wide coverage 或 Nightly；只有真实 Impact Scope、
verification infrastructure 自改或当前 Gate 类型明确要求时才执行。验收语义唯一权威是
`docs/engineering/quality-system.md`，工具执行方式以 `docs/engineering/quality-toolchain.md` 为准；
`docs/engineering/task-gate-template.md` 只用于记录，不建立第二份质量政策。

### 26.6 Task / Increment Release Version Alignment

每个正式编号 Task / Increment 完成时，工程 release version 必须与任务编号对齐：`P8.2 -> 0.8.2`、`P8.3 -> 0.8.3`、
`P8.4 -> 0.8.4`。属于某个正式 Increment 的 correctness/engineering closure 继续使用该 Increment 的三段版本，例如
`P8.2 Cancellation / Recovery Convergence Closure -> 0.8.2`，不得创建 `0.8.2.1` 等四段版本。若未来 Task 编号不能直接映射
标准三段 release version，必须在该 Task Gate 明确冻结映射，不得自行猜测。版本只能通过
`uv run python scripts/version_sync.py set <version>` 同步完整 release graph，并以 `version_sync.py check` 验证。

---

## 27. 静态质量门禁

项目使用：

```text
Python 3.12
uv
Ruff
Ruff Format
mypy strict
pytest
pytest-xdist
```

常用命令：

```bash
uv sync --frozen --all-packages --all-groups
uv run ruff check src tests examples packages scripts
uv run ruff format --check src tests examples packages scripts
uv run mypy src/onlyalpha
uv run python scripts/version_sync.py check
uv build --all-packages
```

规则：

- 不以 `# type: ignore` 掩盖设计错误；
- 新 ignore 必须最小化并注明原因；
- 不使用无类型 `dict` 替代明确 DTO；
- 公共方法必须有完整类型；
- 错误码应稳定、可测试；
- 不吞掉异常；
- cleanup 失败应进入诊断；
- 不使用全局可变状态；
- 不依赖未排序集合产生输出；
- 文件写入必须考虑原子性；
- 资源必须有明确关闭路径。

---

## 28. 代码修改原则

### 28.1 优先修改现有权威路径

新增能力前，先查找：

```text
Existing Domain Type
Existing Port
Existing Factory
Existing Registry
Existing Planner
Existing Projection Target
Existing Query
Existing Result DTO
Existing Checkpoint Participant
```

只有在职责确实不同且无法合理扩展时才新增抽象。

### 28.2 禁止双路径

禁止创建：

```text
new_manager_v2
legacy_or_new
paper_special_execution
close_only_processor
market_specific_engine
compatibility_accounting
temporary_trade_store
```

若新实现替代旧实现，应：

1. 迁移正式调用方；
2. 迁移测试；
3. 删除旧正式路径；
4. 保留必要的数据读取兼容；
5. 更新 ADR 和文档；
6. 增加架构门禁防止回流。

### 28.3 Fail Closed

以下场景必须明确失败：

- 未知 Market Product provider/product/version；
- Capability 不支持；
- Reference 缺失；
- 状态无法归因；
- Fill Identity 冲突；
- 配置不兼容；
- Checkpoint Schema 不兼容；
- Projection 前置状态不匹配；
- Broker/Local Authority 冲突达到阻断级；
- SIM bootstrap 历史数据不足；
- Session 边界无法确认；
- Secret 或外部环境未配置。

不得为了“先跑起来”使用隐式默认值放行资金和交易状态。

### 28.4 Runtime taxonomy 架构门禁

以下规则是未来源码迁移和静态门禁的正式输入：

1. 目标 Runtime 只允许 `RESEARCH`、`BACKTEST`、`SIM`、`LIVE`。
2. 不得新增 `PAPER` Runtime 产品或依赖。
3. 不得新增 standalone `SHADOW` Runtime 产品或依赖。
4. 正式 Backtest 必须保持 event-driven + Virtual Broker + full Trading Kernel。
5. Vectorized execution 只属于 Research，不得命名或实现为 canonical Backtest。
6. Strategy 不得按 Runtime type 分支。
7. Trading economics 和 Execution Support 不得按 Runtime type 决定权限。
8. Backtest、Sim、Live 必须共享一个 trading semantic core。
9. SIM 永远不得向 Real Broker 提交订单。
10. RESEARCH 不得为了共享 Runtime 抽象而实例化 Trading Authorities。
11. Runtime 差异主要限于 Clock、MarketData Driver、Broker Adapter 和 Lifecycle Driver。
12. Runtime Type 不是 Execution Permission；不得创建 Runtime-specific duplicate economic authorities。
13. 不得通过 compatibility alias、deprecated spelling 或 wrapper 长期保留 `PAPER` / `SHADOW` public Runtime vocabulary。
14. 一个 Engine 的目标形态允许四类 Runtime 同时存在，且 Runtime 生命周期相互独立。
15. 一个 Trading Runtime 当前只绑定一个 Account、一个 resolved Market Product 和一个 currency。
16. 跨市场聚合只读，不得成为交易 authority。
17. 未完成某市场四种 Runtime 正式闭环时，不得声称 OnlyAlpha 正式支持整个市场。
18. Manual workload、genesis import 与 liquidation 只属于目标 LIVE 产品，不得回流到 Backtest/SIM/Research 旁路。

---

## 29. 文档规则

代码行为变化时必须同步相关文档。

### README

只描述：

- 产品定位；
- 长期产品模型；
- 当前实现与目标迁移状态；
- 核心工程机制；
- 当前可用能力；
- 快速开始；
- 产品边界；
- 风险声明；
- 文档导航。

不得把 README 重新写成历史实施日志。

### AGENTS

只描述：

- Agent 执行规则；
- 架构不变量；
- 事实来源；
- 验证和交付门禁。

### Architecture

`docs/architecture.md` 描述当前系统如何组织，并明确当前实现与已接受目标架构的差距；不得维护历史阶段、PR 或任务流水账。

### Roadmap

描述：

- 已完成阶段；
- 当前阶段；
- 后续产品优先级；
- 明确非目标。

### ADR

以下变化必须新增或更新 ADR：

- 状态所有权；
- Durable Authority；
- Projection 顺序；
- Recovery Phase；
- Public API；
- Persistence Schema；
- Plugin 边界；
- Market Rule Authority；
- Result Authority；
- 旧路径替换。

### Report

`docs/reports/` 必须带：

- 日期；
- 版本或 Commit；
- 环境；
- 实际执行命令；
- 原始结果；
- 未执行项；
- 限制；
- Artifact 引用。

历史报告不能被当作当前状态自动继承。

---

## 30. 安全与敏感信息

禁止提交或输出：

- Token；
- Password；
- Secret；
- Broker Credential；
- Account Auth；
- 私钥；
- 本地 QMT 用户数据绝对路径；
- 用户主目录绝对路径；
- 未脱敏账户 ID；
- 外部服务完整响应中的敏感字段。

日志、Artifact、Worker Request/Result 和验收 Evidence 必须脱敏。

真实交易相关修改必须默认关闭，并要求显式配置和权限。

---

## 31. Agent 交付格式

完成代码任务时，最终报告至少包含：

```text
1. 修改目标
2. 当前事实和原始问题
3. 修改的正式权威路径
4. 变更文件
5. 不变量如何保持
6. 运行的测试和真实结果
7. 未运行的测试及原因
8. 剩余限制
9. 是否修改 Public API / Schema / ADR
```

不得只说“已完成”或“测试通过”。

测试结果必须区分：

```text
PASS
FAIL
BLOCKED
NOT EXECUTED
```

不得把环境缺失描述为 PASS。

---

## 32. Definition of Done

一项修改只有在满足下列条件时才算完成：

### 业务正确性

- 使用唯一正式入口；
- 未绕过状态权威；
- 未创建第二套正式路径；
- 经济不变量成立；
- 不支持能力 Fail Closed；
- 重复和乱序输入行为明确；
- 失败语义明确。

### 架构正确性

- 依赖方向正确；
- Trading Runtime 仍是 mutable trading authority 唯一所有者；
- Trading Runtime 仍只绑定一个 Account、一个 Market Product 和一个 currency；
- Research Runtime 未因结构对称创建 Trading Authorities；
- 目标 Runtime vocabulary 仍只有 `RESEARCH/BACKTEST/SIM/LIVE`；
- Backtest/Sim/Live 未产生 Runtime-specific economic path；
- 插件未穿透 Core 内部；
- Strategy/Factor 未获得越权能力；
- Market Rule 未复制；
- Result 仍来自正式成交权威；
- 跨市场聚合保持只读；
- LIVE 人工命令、genesis 和清仓未绕过 Engine、Risk、Broker 或 Durable Transaction。

### 恢复正确性

若涉及状态：

- Checkpoint 能力已声明；
- Schema 版本已处理；
- 连续运行和恢复运行等价；
- 事务尾部和 Projection 恢复已覆盖；
- Event 不重复泄漏。

### 测试正确性

- 运行了最窄的正确测试；
- 涉及交易/持久化时运行 Recovery；
- 涉及市场规则时运行 Conformance；
- 没有通过删除测试、skip 或放宽断言完成；
- 测试结果真实记录。

### 工程完整性

- 类型检查通过；
- Lint/Format 通过；
- 示例和配置同步；
- 文档同步；
- 不泄漏敏感信息；
- 无临时文件和调试代码；
- 没有未说明的兼容分支。

---

## 33. 禁止清单

在 OnlyAlpha 中禁止以下做法：

```text
绕过 OnlyEngine 证明产品能力
绕过 Runtime Queue 处理 Broker 回报
Strategy 直接修改订单、仓位或账户
Plugin 持有 Runtime Manager
用 Event Handler 驱动核心状态
用最终 Snapshot 反推逐笔成交
多个 Fill 合并为一个可变 Transaction
Commit 后修改 Transaction
Position、Account、Ledger 分别重算 PnL
多个组件复制市场规则
使用 Float 处理正式账务
未知能力静默降级
Fake SDK PASS 冒充真实产品 PASS
为了测试增加生产 test_mode
通过 skip/xfail 掩盖失败
用 sleep 修复确定性
未排序集合进入结果指纹
不兼容 Schema 静默读取
在 Artifact 中保存 Secret
未运行测试却声称测试通过
根据 prompts/ 创建第二套实现
新增 PAPER 或 standalone SHADOW Runtime 产品依赖
将 PAPER/SHADOW 作为 SIM 长期兼容 alias
把向量化交易近似称为正式 Backtest
Strategy 或 Execution 根据 Runtime type 决定交易语义
为 Backtest/Sim/Live 复制经济 Manager
SIM 向 Real Broker 提交订单
Research 为结构对称实例化 Trading Authorities
```

---

## 34. 最终原则

当实现方案之间存在冲突时，优先选择：

```text
唯一权威
> 多份状态副本

确定性
> 偶然顺序

显式失败
> 隐式降级

不可变事实
> 可变推断

正式产品纵切面
> 单组件演示

Forward Recovery
> 跨 Manager 回滚

公共 Port
> 内部对象穿透

可验证边界
> 功能数量
```

OnlyAlpha 的工程质量不由“存在多少类和模块”衡量，而由以下问题衡量：

```text
同一输入是否产生同一结果？
每个事实是否有唯一来源？
每个状态是否有唯一所有者？
每次失败是否可以解释？
每次恢复是否保持经济等价？
每项产品声明是否有真实验收证据？
```
