# OnlyAlpha

**OnlyAlpha** 是一个面向个人与小型团队的模块化量化交易工程，目标是在保持工程结构清晰、运行结果确定、状态可恢复的前提下，为 **Research、Backtest、Sim、Live** 四种 Runtime 提供统一的量化基础设施。

OnlyAlpha 的长期产品身份是多市场量化平台。`onlyalpha.domain` 定义跨市场 canonical 基础语言；具体市场通过 versioned Market Product、DataSource 与 Broker 插件接入。Core 与 Trading Kernel 不根据市场名称复制 Engine、Runtime 或经济 Manager。

核心原则：

> **Research 为研究效率服务；Backtest、Sim、Live 为交易语义一致性服务。**

> **Correctness > Architecture Consistency > Verifiability > Recoverability > Maintainability > Performance > Automation.**

长期策略产品目标：

```text
Human / LLM Agent
→ Research Draft / Experiment
→ Research Evidence
→ Freeze immutable Strategy Revision
→ Backtest
→ Sim
→ Live
```

OnlyAlpha 的目标不是维护四套 Runtime-specific 策略，而是让同一个 immutable Strategy Revision 在 Backtest、Sim、Live 中保持同一策略语义；Runtime 只改变数据时态、Portfolio/Execution Profile、Broker、Lifecycle 与 Execution Permission。Research Run 不是 Strategy Revision，Strategy Revision 也不包含资金规模或真实执行权限。详细目标见 [`docs/strategy_product_architecture.md`](docs/strategy_product_architecture.md)。

---

## 当前状态

| 项目 | 状态 |
|---|---|
| Version | `0.8.4` |
| Python | `>=3.12, <3.13` |
| Product stage | Alpha |
| Architecture | Modular Monolith |
| Primary trading runtime | Backtest |
| P6 | **DONE / CERTIFIED** |
| P7 | **DONE / CERTIFIED** — Vectorized Research Runtime |
| P7 Final SHA | `6b051705c7638dc3acb02dde430c3c2348121811` |
| P7 Final-SHA Certification | run `31986131977` — **ACCEPTED** |
| Current milestone | **P8 — Research Control Plane & Web-native Execution** |
| Current increment | **P8.4.3.1 — IMPLEMENTED / VERIFIED locally** — Web Submission Determinism & Authoring Admission Closure |
| Next semantic direction | P8.4.4 — Scientific Viewer & Graph Inspector Closure |
| License | MIT |

P7 的 exact Final-SHA Certification 已完成。认证 subject `6b051705c7638dc3acb02dde430c3c2348121811` 的 mandatory static、build、Web、canonical lanes、coverage、Semgrep、dependency audit 与 Python/TypeScript CodeQL 全部成功，最终 certification artifact verdict 为 `ACCEPTED`。详细证据见 [`docs/reports/p7_final_certification.md`](docs/reports/p7_final_certification.md)。

P8 之后的 milestone **当前不预先编号或冻结**。P8 完成并取得 exact Final-SHA `ACCEPTED` 后，再基于当时 Repository truth 重新规划。Strategy Revision、Research → Backtest → Sim → Live Promotion、Web embedded IDE 与 LLM Agent strategy authoring 是长期目标方向，不因为本文记录而自动成为下一个 milestone。

---

## Runtime 模型

OnlyAlpha 唯一允许的目标 Runtime vocabulary：

```text
RESEARCH
BACKTEST
SIM
LIVE
```

目标产品架构：

```text
OnlyEngine
│
├── Research Runtime
│   └── Research Job / Plan
├── Backtest Runtime
│   └── Cluster workload(s)
├── Sim Runtime
│   └── Cluster workload(s)
└── Live Runtime
    ├── Cluster workload(s)
    └── Manual workload(s)
```

正式原则：

```text
Research optimizes research efficiency.

Backtest / Sim / Live
share one trading semantic core.

Runtime Type
!=
Execution Permission.
```

历史 `PAPER` 与 standalone `SHADOW` 已从 active product vocabulary 删除，不保留 alias、deprecated spelling 或 compatibility wrapper。

---

## 当前 Runtime 产品边界

| Runtime | 当前事实 |
|---|---|
| `BACKTEST` | 已实现，是 primary trading Runtime；event-driven + Virtual Broker + Full Trading Kernel |
| `SIM` | 已实现 realtime Virtual Broker normal path、continuity/gap/reconnect、checkpoint 与 new-process recovery |
| `RESEARCH` | 已实现 finite programmatic Engine product、immutable Result/Artifact、read-only Query/API 与 Research Web |
| `LIVE` | Factory unsupported；真实 Broker outbound durability、同步、reconciliation、长期恢复尚未实现 |

当前 Trading 产品继续遵守：

```text
One Trading Runtime
= One Account
= One resolved Market Product
= One Account currency
```

多市场通过一个 Engine 下多个隔离 Runtime 组合；跨市场 Result/Analytics/Artifact/Web 聚合只读，不成为资金、仓位、订单或风险 authority。

---

## P7 已完成的 Research 产品链

P7 已建立完整 Research semantic/read vertical slice：

```text
Historical Dataset Snapshot
      ↓
Vectorized Calculation
      ↓
Factor / Feature / Score
      ↓
Parameter Sweep
      ↓
Target / Statistics
      ↓
Research Result
      ↓
Research Artifact
      ↓
Query / HTTP API
      ↓
Research Web
```

### Calculation Identity

Indicator、Factor 与 Target 的正式身份来自 immutable、Runtime-independent Calculation Definition：

```text
type_id + semantic_version + resolved parameters + input bindings
+ output/warmup/missing/timestamp/numeric semantics
→ canonical representation
→ SHA-256 fingerprint
```

Research 与 Trading backend 可以使用不同执行模型，但必须共享同一 Calculation semantic identity。Research backend 不得消费 Definition 未声明的 semantic input，也不得 fallback 到 Trading backend。

### Immutable Research Authorities

P7 建立并保持分离的 durable authorities：

```text
Dataset Snapshot
Calculation Result
Statistics Result
Research Result
Research Artifact
```

其中：

- Dataset Snapshot 是 Research 输入 authority；
- Calculation Result 是 exact Calculation 输出 authority；
- Statistics Result 是统计 rows semantic authority；
- Research Result 是 exact Statistics composition authority；
- Research Artifact 是 portable immutable materialized read view，不是第二 semantic authority。

这些 authority 使用 content-addressed Parquet/JSON/Manifest、stable fingerprint、verified load、atomic publication、idempotent reuse、deterministic conflict 和 corruption fail-closed。

### Finite Research Runtime

正式 programmatic product path：

```text
OnlyEngine
→ add_research_workload(...)
→ validate / initialize / start
→ run_runtime(runtime_id)
→ stop / close
```

`OnlyResearchRuntime` 编排既有 Dataset、Job、Sweep、Statistics、Result 与 Artifact authority，不创建 Trading Cluster、Account、Position、Order、Broker、Reservation 或 durable Trading Transaction authority。

### Research Query/API/Web

Research consumer plane：

```text
Research Artifact
→ read-only Query Service
→ onlyalpha-api
→ HTTP v2
→ onlyalpha-web
```

HTTP transport 中 Decimal、event nanosecond 与 cursor 使用 canonical string；Web runtime admission 后 exact nanosecond 使用 `bigint`、Decimal 保持 string。Chart 中的 `number/seconds` 只是显式可失败的 presentation projection，不能反向成为 Research truth。

Web 只消费 exact Artifact identity，不读取 Artifact filesystem/Parquet、不访问 Dataset/Calculation/Statistics/Result execution Store，也不控制 Research Runtime mutable state。

---

## 长期 Strategy Product 模型

Research 可以是单票、股票池或全市场；Universe 与 Decision Mode 是两个独立语义。产品可以默认“单票 → time-series、多票 → cross-sectional”，但 Domain 不把股票数量硬编码成策略类型。

目标策略链：

```text
Universe
→ Eligibility
→ Indicator → Named Feature
→ Factor → Score
→ Ranking / Selection
→ Entry / Exit Decision Expression
→ Signal
```

第一阶段 Decision Expression 优先使用有限、结构化、可序列化的 `AND / OR / NOT + comparison`，而不是把最终买卖规则隐藏在任意 Python callback 中。Indicator 可以输出多个 named Feature，Factor 提供稳定 primary score；市值、价格、流动性等 Filter 可以复用 Calculation infrastructure，但在策略语义中属于独立 Eligibility role。

Research 中选定的候选只有经过显式 Freeze 才成为 immutable Strategy Revision。Strategy Revision 固定 exact code/version、parameters、selected features、Factor/Eligibility/Decision semantics 与 origin Research evidence；修改任何策略语义都产生新 Revision。

Trading 组合保持：

```text
Strategy Revision
+
Portfolio Profile
+
Execution Profile
+
Runtime-specific Data/Broker/Lifecycle
+
Explicit Execution Permission
```

所以仓位、账户资金和 Live deployment permission 不是 Strategy Revision 本身。Backtest、Sim、Live 目标上执行同一 Strategy Revision，禁止为 Runtime 差异复制 Strategy semantic truth。

---

## Trading Semantic Core

Backtest、Sim、目标 Live 共用正式 Trading Kernel。允许的差异主要位于：

```text
Clock Driver
MarketData Driver
Broker Adapter
Lifecycle Driver
```

进入 Trading Semantic Plane 后，共享：

```text
Strategy
Market Rule
Risk
Reservation
Order
Execution
Fee
Position
Allocation
Account
Strategy Ledger
Settlement
Durable Transaction
Recovery semantics
```

固定不变量：

```text
One Domain
→ One Write Authority

Planner Calculates
→ Projection Installs

Commit Fact First
→ Project State Second

Historical Fact Immutable
→ Forward Recovery Only

Market Identity Is Evidence
→ Not Execution Permission

Unsupported / Ambiguous
→ Fail Closed
```

Broker Gateway 是外部命令/事实适配边界，不是本地 Account、Position 或 Order authority。SDK callback 不得直接修改 Runtime Manager。

---

## 当前有限认证产品

当前已经认证的有限 A 股 Backtest 合同：

```text
CN_A_SHARE_DURABLE_BACKTEST_V1
```

它覆盖有限普通中国 A 股 Cash-Long Backtest surface，并不意味着：

- 完整 A 股市场范围已支持；
- ETF / Convertible Bond / BSE 已支持；
- Margin / Short 已支持；
- Sim 已达到长期生产运行；
- Live 已可用于真实资金。

只有某市场的 Research、Backtest、Sim、Live 四种正式产品纵切面均通过正式入口、恢复/确定性和产品认证后，才能声明 OnlyAlpha 正式支持整个市场。

---

## P8 — Research Control Plane & Web-native Execution

P8 的核心目标是把 P7 的 programmatic Research 变成可长期使用的 Web-native Research product，并为未来 Strategy Freeze/Promotion 留下无损、结构化的研究输入与证据边界：

```text
Browser
→ Universe / Research Definition
→ Research Specification
→ Command API
→ Research Run
→ PostgreSQL Operational Store
→ Scheduler / Worker
→ OnlyEngine / OnlyResearchRuntime
→ Existing immutable Research authorities
→ Existing Query API
→ Scientific Research Viewer
```

P8 分为：

```text
P8.0  Research Specification & Resolution Boundary
P8.1  Research Run Authority & PostgreSQL Operational Store
P8.2  Research Scheduler, Worker & Recovery
P8.3  Research Command API
P8.4  Research Studio Web
P8.5  Operational Hardening & Database Recovery
P8.6  P8 Product Closure & Final Certification
```

P8 的关键边界：

```text
PostgreSQL
→ mutable Operational / Control State

Immutable Research Stores
→ Dataset / Calculation / Statistics / Result / Artifact semantic facts
```

PostgreSQL 不保存第二份 Research semantic result。

P8.0 已建立 strict `OnlyResearchSpecification` V1、canonical request fingerprint、exact type/RESEARCH-backend admission、
Direct/Sweep 共享 Graph Template Materializer、symbolic Feature/Target selector、singleton-only Statistics broadcast，以及到现有
`OnlyResearchWorkloadPlan` 的 deterministic resolution。Candidate lineage 保留 runtime-neutral Graph identity；Dataset-bound Research
Calculation identity 不承担未来 promotion identity。该 increment 已通过本地 affected/FULL_LOCAL verification，但不构成 P8 certification。
P8.0.1 进一步把 Resolver 输出收紧为 exact `OnlyResearchWorkloadPlan`，并建立 `research-specification` canonical lane、
100% line/branch coverage、impact-aware transitive verification、普通 CI 与 Final-SHA mandatory evidence；它不改变任何 P8.0 semantic
identity，也不进入 P8.1 operational control scope。

P8.1 已建立 opaque UUID4 `OnlyResearchRunId`、集中式 Run 状态机、revision/CAS、Dataset verified admission、canonical
Specification durable evidence 与 admission resolution drift guard。PostgreSQL 16.10 只拥有 Run operational state 和现有
Result/Artifact exact SHA references；checksummed forward-only migration、startup compatibility-only、显式
`status/plan/migrate/backup/restore-test` 运维入口以及真实 PostgreSQL 并发/重启/恢复验证已进入独立 canonical lanes。P8.1 不执行
QUEUED Run，也不包含 Scheduler、Worker、Attempt persistence、HTTP 或 Web。

P8.2 已建立独立 UUID4 Attempt/Worker identity、PostgreSQL transactional deterministic claim、server-clock lease/heartbeat、one-ACTIVE
约束与 exact Attempt/Worker fencing。Scheduler 只协调 operational facts；Worker 重新 verified-load Dataset、复核 admission evidence，
并只经 `OnlyEngine → OnlyResearchRuntime` 执行。失败重试有界，过期 Attempt 不复活，Artifact 已提交但 operational finalization 未完成
时由新 Attempt deterministic re-entry/verified reuse 后收敛。PostgreSQL 仍不保存 Research semantic progress 或 Result content；P8.2
不包含 HTTP/Web control。

P8.3 已建立 transport-neutral Research Command/Application boundary、UUID4 `Idempotency-Key`、同事务 Run + submission mapping、
`queued_at DESC, run_id DESC` keyset pagination 与有界 cancellation CAS re-interpretation。完整 `/api/v2/research/runs` API 只在
PostgreSQL durable commit 后返回 accepted Run；portable `onlyalpha-artifact-api` 继续只依赖 Artifact Reader。OpenAPI、Web generated
contract/Zod admission 与 exact `bigint` revision 已同步，但没有新增 P8.4 页面、Worker 启动或 Artifact content response。

P8.4.0 已实现 programmatic Research Definition foundation：Universe/Data intent、registered Calculation Instance、全局有限 Sweep、typed Eligibility/Entry/Exit AST、internal RESEARCH Predicate lowering，以及现有 Specification/Workload 闭环。P8.4.3 已让用户从 Web 选择并提交这些正式语义；K-line、Feature、Factor Score、Signal/买卖点、cross-sectional statistics 的完整科学可视化仍属于 P8.4.4。完整 embedded IDE、LLM Agent code authoring 与 immutable Strategy Revision Promotion 默认仍属于 P8 之后重新规划的长期方向。

P8.4.1 已把 Calculation Registry、Dataset source contract、registered Universe authority 与共享 Statistics capability 作为确定性只读
Catalog 暴露，并增加 `POST /api/v2/research/definitions/resolve`。该 endpoint 严格执行
`HTTP DTO → OnlyResearchDefinition → OnlyResearchDefinitionResolver`，返回 exact Dataset/Candidate/Specification evidence；其中
`exact_specification` 原样复用 P8.3 Run submission transport。它不创建 Run、不执行 Runtime，也不保存 Definition/Resolution。

P8.4.1.1 已关闭 Public Authoring 与 Universe authority 边界：Research API 的 registered Universe Discovery 与 Definition Resolution
只能复用同一实例；没有 registered authority 时只公开 explicit Universe capability。Definition authoring transport 只接受
`INDICATOR / FACTOR / TARGET`，internal `PREDICATE` 仍由既有 Calculation Registry 与 exact Graph 语义拥有。

P8.4.2 已把 publication membership 与 Candidate identity 穿过 Specification V2、Run canonical payload、fresh Worker、Runtime、Result V2、
Scientific Artifact V2 和 Artifact-only Query/HTTP。Artifact 自包含 exact market、typed Published Variables、nullable Signals、Statistics 与
canonical Graph；V1 contracts 保持可读，且未新增 Evidence/Candidate/Signal/Graph/Predicate Store 或 execution phase。

P8.4.2.1 已关闭 Scientific Artifact 的并发发布、exact membership、logical key、typed scalar、完整 series axis 与 portable verified-load
缺口，并把 internal Predicate implementation ownership 收敛到 Research Calculation。Candidate 与既有 Specification/Result/Artifact
semantic identity 算法不变；V1 contracts 与 P8.3 exact Specification submission 保持兼容，P8 仍为 `IN_PROGRESS`。

P8.4.3 已实现 Web-native 日常 Research 控制闭环：持久 workstation shell、catalog-driven structured Builder、唯一 Draft → Definition
transport、权威 Definition Resolution、edit revision + stale response fencing、exact Specification idempotent Run submission、Run
list/detail/poll/cancel，以及 Completed Run → exact Result 跳转。Stage 0 同时关闭 non-candidate multi-lineage publication ambiguity 与
generic PREDICATE publication 准入缺口；未改变 Definition/Specification/Candidate/Calculation/Result/Artifact identity，未新增 endpoint、
PostgreSQL authority 或 Runtime path。P8 仍为 `IN_PROGRESS`；完整 Scientific Viewer/Graph Inspector 属于 P8.4.4。

P8.4.3.1 关闭 Web submission 与 authoring admission 的剩余正确性缺口：pending submission intent 绑定 server Resolution 返回的
`specification_fingerprint`，所有不确定失败均保留同一 Idempotency Key，只有权威成功响应才消费该 intent；同一 Specification 的显式
Run Again 仍创建新 key/new Run。唯一 Draft → Definition transport 对 FIXED scalar、published output 与 Statistics method 全部 fail
closed，并在 Builder 中显式暴露既有 Price Type 与 Adjustment Reference。该 closure 不改变任何 Research semantic identity 公式，
不新增 endpoint、Store、Runtime、PostgreSQL schema 或 authority；P8 仍为 `IN_PROGRESS`。

Historical/Time-Series 数据长期可以由 ClickHouse 等 analytical store 承担，但 Historical Data Platform **不是 P8 的硬前置条件**；当前 Roadmap 不为 P8 之后预先创建 P9/P10 任务。即使未来存在 ClickHouse，正式 Research 输入仍应通过 immutable Dataset Snapshot 冻结，而不是直接查询不断变化的数据库。

完整范围、非目标和退出条件见 [`docs/roadmap.md`](docs/roadmap.md)。长期 Strategy Product 参考架构见 [`docs/strategy_product_architecture.md`](docs/strategy_product_architecture.md)。

---

## P8 Database Constitution

P8 引入 PostgreSQL 时必须坚持：

1. Domain First, Schema Second；
2. PostgreSQL 只拥有 Operational State；
3. Migration History 是 Schema Authority；
4. 已发布 Migration immutable；
5. Production Forward Migration Only；
6. Application startup never auto-migrates；
7. No manual production DDL；
8. Schema change requires a real durable-domain requirement；
9. Backup 必须进行 restore verification；
10. Database change 是 architecture event，不是普通 UI/API change。

数据库的目标维护状态应当是：**结构很少变化、事实持续增长、迁移显式发生、恢复定期验证。**

---

## Storage Boundary

OnlyAlpha 长期不采用“一种数据库装所有东西”的模型。

当前/目标职责分离：

```text
Raw Provider Evidence
→ Raw Archive / file storage

Historical / large time-series facts
→ future analytical store such as ClickHouse

Immutable Research semantic facts
→ content-addressed Parquet / JSON / Manifest

Operational mutable state
→ PostgreSQL in P8
```

存储选择由 Authority 性质、可变性和访问模式决定，而不是仅按“看起来是不是时间序列”决定。

OnlyAlpha 自己计算得到的 exact Indicator/Factor Result 首先仍属于 immutable Calculation Result authority；未来即使为分析性能 materialize 到 ClickHouse，也只能作为可重建 projection/cache，不能成为第二 semantic truth。

---

## 工程质量体系

OnlyAlpha 只有三种正式质量层级：

```text
Task Gate
Phase Gate
Certification Gate
```

普通任务先冻结：

```text
TASK_BASE_SHA
Goal
Modification Scope
Impact Scope
Required Behavior
Expected Acceptance Tests
Expansion Triggers
Out of Scope
```

Task Gate 运行最小但充分的 impact-aware verification；`core-full --coverage`、repository-wide coverage、全部 canonical lanes 和 Final-SHA Certification 不属于每个普通小节的默认验收。

完整 Major Milestone 的顺序：

```text
Task Complete x N
→ Phase Gate
→ Phase Complete
→ Freeze Final SHA
→ Final-SHA Certification
→ ACCEPTED
→ DONE / CERTIFIED
```

质量制度见：

- [`docs/engineering/quality-system.md`](docs/engineering/quality-system.md)
- [`docs/engineering/quality-toolchain.md`](docs/engineering/quality-toolchain.md)
- [`docs/engineering/task-gate-template.md`](docs/engineering/task-gate-template.md)

---

## 常用开发入口

安装 Python workspace：

```bash
uv sync --frozen --all-packages --all-groups
```

常用 canonical lanes：

```bash
uv run python scripts/test_suite.py calculation
uv run python scripts/test_suite.py research-calculation
uv run python scripts/test_suite.py research-factor
uv run python scripts/test_suite.py research-job
uv run python scripts/test_suite.py research-sweep
uv run python scripts/test_suite.py research-specification
uv run python scripts/test_suite.py research-runtime
uv run python scripts/test_suite.py research-query
uv run python scripts/test_suite.py research-artifact
uv run python scripts/test_suite.py recovery
uv run python scripts/test_suite.py sim-recovery
uv run python scripts/test_suite.py ashare
uv run python scripts/test_suite.py core-full
```

Impact-aware Task Gate：

```bash
uv run python scripts/verify.py plan --base <TASK_BASE_SHA>
uv run python scripts/verify.py agent --base <TASK_BASE_SHA>
```

Research Web：

```bash
cd apps/onlyalpha-web
npm ci
npm run dev
```

Research API：

```bash
ONLYALPHA_POSTGRES_DSN='postgresql://...' uv run onlyalpha-api --user-data-root <USER_DATA_ROOT>
uv run onlyalpha-artifact-api --artifact-root <USER_DATA_ROOT>/research/artifacts
```

Research Web 已支持 `New Research / Runs / Results`：浏览器只保存临时 Draft 和 presentation state，exact Specification 只来自最新权威
Resolution；pending Run submission 在不确定重试间复用该 Resolution identity 对应的 Idempotency Key，Run state 只来自 PostgreSQL
operational authority，Result 页面只消费 Artifact/Query evidence。P8.4.4 的高级科学可视化与 Graph Inspector 尚未实现。

---

## 文档导航

- [Current Architecture](docs/architecture.md)
- [Target Strategy Product Architecture](docs/strategy_product_architecture.md)
- [Roadmap](docs/roadmap.md)
- [P7 Final Certification Closure](docs/reports/p7_final_certification.md)
- [Engineering Quality System](docs/engineering/quality-system.md)
- [Engineering Quality Toolchain](docs/engineering/quality-toolchain.md)
- [ADR](docs/adr/)
- [Reports](docs/reports/)

---

## 最终原则

OnlyAlpha 不以功能数量衡量工程质量，而以这些问题衡量：

```text
同一输入是否产生同一结果？
每个事实是否有唯一来源？
每个状态是否有唯一所有者？
同一个 Strategy Revision 是否跨 Backtest / Sim / Live 保持同一语义？
失败是否进入已知状态？
恢复是否保持语义等价？
产品声明是否有真实认证证据？
```

最终目标是构造一个行为可解释、状态有唯一真值、历史可审计、故障后可恢复，并能够让 Research Evidence 冻结成 immutable Strategy Revision、再自然晋升到 Backtest、Sim、Live 的多市场量化交易工程。LLM / Agent 可以成为策略作者和受控操作客户端，但不能成为 semantic、evidence 或 execution permission authority。
