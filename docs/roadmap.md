# OnlyAlpha 路线图

本文件只描述当前实现迁移到下一目标阶段的阶段边界、退出条件与非目标。当前事实以源码、正式测试、未被替代的 ADR 和产品认证为准；历史实现细节保存在 `docs/adr/`、`docs/reports/` 与 Git history，不在 Roadmap 中重复维护任务流水账。

Runtime taxonomy 继续由 [ADR 0068](adr/0068-runtime-product-taxonomy-and-trading-semantic-equivalence.md) 冻结，多市场/异构 Runtime 拓扑由 [ADR 0080](adr/0080-multi-market-platform-and-heterogeneous-runtime-lifecycle.md) 冻结，Live genesis/manual/liquidation 目标合同由 [ADR 0081](adr/0081-live-genesis-manual-workload-and-liquidation-control.md) 冻结。

## 目标 Runtime taxonomy

```text
RESEARCH  Historical + Vectorized/Batch + Research-oriented
BACKTEST  Historical + Event-driven + Virtual Broker + Full Trading Kernel
SIM       Realtime + Event-driven + Virtual Broker + Full Trading Kernel
LIVE      Realtime + Event-driven + Real Broker + Full Trading Kernel
```

目标 `OnlyEngine` 可以同时持有四类 Runtime Session，且各 Runtime 生命周期独立。当前 Trading 产品采用 `One Runtime = One Account = One Market Product = One Currency`；多市场通过 Engine 下多个隔离 Runtime 组合，跨市场汇总只读。

历史 `PAPER` 与 standalone `SHADOW` 不是目标 Runtime，不得重新成为 active product spelling、alias 或兼容 wrapper。

## 当前状态

```text
Current Milestone: P8
Milestone State: IN_PROGRESS
Current Increment: P8.1 — IMPLEMENTED / VERIFIED LOCALLY
Latest Certified Milestone: P7 — DONE / CERTIFIED
P7 Final Certification Subject: 6b051705c7638dc3acb02dde430c3c2348121811
P7 Final Certification Run: 31986131977
P7 Final Certification Verdict: ACCEPTED
Next Semantic Direction: P8.2 — Research Scheduler / Worker / Attempt Authority
```

`VERIFIED` 只表示某个 implementation increment 已完成其 targeted/affected Task Gate；`CERTIFIED` 只表示 exact immutable SHA 的正式 Final-SHA Certification artifact 给出 `ACCEPTED`。Major Milestone 只有在 Phase Gate 完成并对冻结 Final SHA 取得 `ACCEPTED` 后才能宣告 `DONE / CERTIFIED`。

---

## 已完成阶段

### P0–P5 — Trading Authority / Product Foundation

P0–P5 已建立测试基线、Fee Authority、Fee Reconciliation、CN A-share production fee、Durable Execution Capability、Broker-driven Order Lifecycle、有限 CN A-share durable Backtest product conformance，以及 Market Product composition neutralization。

其中 `CN_A_SHARE_DURABLE_BACKTEST_V1` 是精确、有限、已认证的 Backtest 产品合同；它不等价于完整 A 股市场支持。

### P6 — Sim Streaming Runtime Closure（DONE / CERTIFIED）

P6 将 Trading mutable authorities 收敛到共享 `OnlyTradingKernel`，完成 Runtime control/semantic 分离、SIM product identity、realtime Virtual Broker、continuity/gap/reconnect、streaming checkpoint/new-process recovery，并删除 active `PAPER/SHADOW` 产品路径。

P6 的长期不变量继续有效：Backtest/Sim/Live 共享 Trading Semantic Core；Runtime Type 不是 Execution Permission；SIM 永远不向 Real Broker 发单；Recovery 只允许 Forward Recovery。

### P7 — Vectorized Research Runtime（DONE / CERTIFIED）

P7 已完成完整 Research semantic/read vertical slice：

```text
Historical Dataset Snapshot
→ Vectorized Calculation
→ Factor / Feature / Score
→ Parameter Sweep
→ Target / Statistics
→ Research Result
→ Research Artifact
→ Query / API
→ Research Web
```

并完成 programmatic finite Research Runtime：

```text
OnlyEngine
→ add_research_workload(...)
→ initialize / start / run_runtime
→ Job / Sweep / Statistics
→ Research Result
→ Research Artifact
```

P7 的正式退出条件已经满足：

- stable Research Job / Plan contract；
- deterministic Dataset / Calculation identity；
- immutable Calculation / Statistics / Research Result authority；
- portable self-verifying Research Artifact；
- read-only Query/API boundary；
- Web-safe HTTP v2 transport；
- exact browser admission（nanosecond `bigint`、Decimal string）；
- read-only Research Web vertical slice；
- finite Research Runtime product path；
- canonical Research lanes、coverage、Web E2E、architecture/security/build gates 已进入 Final-SHA mandatory matrix。

P7 Final SHA：

```text
6b051705c7638dc3acb02dde430c3c2348121811
```

对应 `Final-SHA Certification` run：

```text
31986131977
```

认证 artifact verdict：

```text
ACCEPTED
```

因此 P7 当前正式状态为：

```text
DONE / CERTIFIED
```

P7 的认证只证明当前 Research 产品边界，不意味着 Research Scheduler、Web execution control、Optimizer、Historical Data Platform、完整 heterogeneous Engine lifecycle 或 LIVE 已完成。

---

# P8 — Research Control Plane & Web-native Execution

## P8 总体目标

P7 回答：

> Research 如何确定地计算、保存、验证和读取？

P8 回答：

> 用户如何不再手工执行本地 Python，而是通过 Web 提交一个 Research，由服务器可靠、持久、可恢复地执行，并在完成后自动消费现有 immutable Research Result / Artifact？

P8 不建立第二套 Research Semantic Plane。P8 新增的是 Operational Control Plane：

```text
Browser
   ↓
Research Studio
   ↓
Research Specification
   ↓
Research Command API
   ↓
Research Run Authority
   ↓
PostgreSQL Operational Store
   ↓
Scheduler / Worker
   ↓
OnlyEngine
   ↓
OnlyResearchRuntime
   ↓
Existing Dataset / Calculation / Statistics / Result / Artifact Authorities
   ↓
Existing Read-only Query API
   ↓
Web Result Viewer
```

固定原则：

```text
Research Run / Scheduler State
→ PostgreSQL Operational Authority

Research Semantic Result
→ Existing Immutable Authorities
```

PostgreSQL 只能回答“这个任务现在处于什么 operational 状态”，不能成为 Dataset、Calculation Result、Statistics Result、Research Result 或 Artifact 的第二真值。

---

## P8.0 — Research Specification & Resolution Boundary

状态：**VERIFIED LOCALLY**。P8.0 已实现 strict Specification V1、canonical request identity、exact Registry/RESEARCH backend
admission、唯一 Graph Template Materializer、symbolic series resolution、`BROADCAST_SINGLETON` Statistics expansion、自动 Result
composition 与 candidate lineage，并保持最终执行合同为现有 `OnlyResearchWorkloadPlan`。本状态是本地 increment evidence，不是 P8
Final-SHA certification。

P8.0.1 已完成该 semantic boundary 的工程闭环：`OnlyResearchSpecificationResolution.workload` 是 exact
`OnlyResearchWorkloadPlan`；`research-specification` canonical lane 独立拥有 schema/identity/resolution/lineage/architecture 与完整 Runtime
equivalence evidence；Specification package 具有 100% line/branch coverage；impact resolver 精确传播 Workload、Sweep、Calculation、Dataset
identity、Evaluation contract 与 Result Plan 变化，同时不从 Query、Artifact physical store 或 Statistics physical store 反向传播。该 lane
已进入 release、普通 CI 与 Final-SHA mandatory matrix。P8.0.1 不改变 P8.0 identity，也不实现 P8.1。

### 目标

建立可序列化、可版本化、可验证、可通过 API/Web 提交的 `Research Specification`，把用户意图确定性解析为现有 `OnlyResearchWorkloadPlan`。

目标链：

```text
User Intent
→ Versioned Research Specification
→ Strict Admission
→ Deterministic Resolution
→ Existing Dataset / Calculation / Job / Sweep / Statistics / Result Plan
```

### 必须完成

- immutable/versioned Research Specification domain contract；
- canonical serialization；
- stable specification fingerprint；
- exact Dataset Snapshot reference；
- exact Calculation/Factor/Target type + semantic version reference；
- parameter/sweep/statistics specification；
- strict unknown-field / invalid-reference fail-closed；
- deterministic `Specification → OnlyResearchWorkloadPlan` resolution；
- Python object construction 不再是唯一 Research submission representation。

### 不允许

- Web-specific Factor/Target identity；
- 第二套 Calculation Definition；
- fuzzy/latest plugin resolution；
- Specification 自己成为 Calculation/Result authority。

---

## P8.1 — Research Run Authority & PostgreSQL Operational Store

状态：**IMPLEMENTED / VERIFIED LOCALLY**。P8.1 已完成独立 Run identity、`QUEUED/RUNNING/CANCEL_REQUESTED` 与三个 immutable
terminal outcomes、revision/CAS、structured failure、canonical Specification payload/fingerprint reload verification、Dataset
verified admission、admission resolution fingerprint、最小 Store Port 与 programmatic admission service。PostgreSQL 16.10 的最小
operational schema、checksummed forward-only migration ledger、compatibility-only startup boundary、显式 operator tooling、真实 CAS
竞争、fresh-process reload 和 backup/isolated restore-test 已通过独立 `research-run` / `research-postgres` lanes。Scheduler、Worker、
Attempt persistence、lease、retry、HTTP 和 Web 仍属于后续 increment；本状态不声明 P8 DONE 或 CERTIFIED。

P8.1 authority hardening closure 已进一步冻结 migration ledger 必须是 Repository canonical history 的 exact ordered prefix；合法
`BEHIND` 只规划该 prefix 后的 ordered suffix，known hole/reorder/prepend 统一以 `HISTORY_DIVERGED` fail closed。新的 forward-only
`0002_research_run_authority_hardening` 在不修改 `0001` bytes、不修复历史数据的前提下，使 PostgreSQL 与 Domain 同时拒绝
ResearchRun 时间倒序、state/timestamp 矛盾以及 Artifact reference 缺失 Result reference。P8.1 仍只是 P8 increment，下一语义方向
保持 P8.2。

### 目标

建立“用户已经提交了一个 Research”这一 durable operational fact，并正式引入 PostgreSQL 作为 Research Control Plane 的事务型状态 authority。

### Domain First

必须先冻结：

```text
ResearchRunId
ResearchRun
ResearchRunState
ResearchRunAttempt
ResearchRunFailure
ResearchRunStore Port
```

再设计数据库 Schema。

候选状态机必须经过正式 ADR 冻结，至少覆盖：

```text
SUBMITTED
→ QUEUED
→ RUNNING
→ COMPLETED / FAILED

QUEUED / RUNNING
→ CANCEL_REQUESTED
→ CANCELLED
```

### PostgreSQL 只允许拥有

- Research submission/run operational state；
- attempt；
- worker ownership / lease；
- cancel request；
- failure/audit metadata；
- completed Research Result / Artifact exact reference。

### PostgreSQL 禁止拥有

- historical bars；
- Dataset rows；
- Calculation rows；
- Factor values；
- Statistics rows；
- Research Result content；
- Research Artifact content。

### Database Constitution

P8.1 必须同时冻结：

1. Domain First, Schema Second；
2. Migration History 是唯一 Schema Authority；
3. 已发布 Migration immutable；
4. Production Forward Migration Only；
5. Application startup never auto-migrates；
6. No manual production DDL；
7. Schema change requires new durable domain fact；
8. Migration 必须有 checksum / ledger；
9. Backup 必须经过 restore verification；
10. Database change 是 architecture event，不是普通 UI/API feature change。

应建立显式 operator tooling，例如：

```text
scripts/database.py status
scripts/database.py plan
scripts/database.py migrate
scripts/database.py backup
scripts/database.py restore-test
```

具体命令名以实现时 current repository 为准，但 startup 只验证 compatibility，不允许隐藏 migration/repair。

---

## P8.2 — Research Scheduler, Worker & Recovery

### 目标

让 durable `QUEUED` Research Run 可以由服务器可靠领取、执行和恢复，而不是依赖进程内 queue 或一次 HTTP request 生命周期。

目标链：

```text
PostgreSQL QUEUED Run
→ Scheduler / Worker Claim
→ Durable Lease / Attempt
→ OnlyEngine
→ OnlyResearchRuntime
→ Existing Immutable Authorities
→ Run COMPLETED / FAILED
```

### 必须完成

- deterministic claim ordering；
- transactional claim；
- lease / heartbeat；
- attempt identity；
- duplicate-execution prevention；
- worker crash detection；
- process/server restart recovery；
- bounded retry policy；
- cancellation semantics；
- graceful shutdown；
- stable operational failure codes；
- existing immutable Result reuse / deterministic re-entry。

P8 Scheduler 不重新发明 Research semantic checkpoint。P7 的 Dataset/Calculation/Statistics/Result/Artifact immutable authority 和 verified reuse 是 Research execution recovery 的基础。

### 不允许

- in-memory queue 作为 durable authority；
- Redis/Kafka/Celery 仅为了“看起来像任务系统”而成为默认依赖；
- Worker 自己维护第二套 Result/Progress semantic truth；
- Scheduler 根据 UI 状态推断业务事实。

---

## P8.3 — Research Command API

### 目标

建立正式 write/control HTTP boundary，使外部 Application/Web 可以安全提交、查询和取消 Research Run。

P7 read-only Query API 继续保持 Artifact-backed consumer boundary；P8 Command API 是独立 operational boundary。

概念接口：

```text
POST   Research Run
GET    Research Run status
POST   Research Run cancellation request
```

具体 URL/version 在实现阶段由 API ADR 冻结。

### 必须保持

```text
HTTP Command
→ validate specification
→ deterministic resolve
→ durable PostgreSQL commit
→ return accepted Run identity
```

只有 durable commit 成功后才能向客户端声明 submission 已成功。

Query API 与 Command API 不得混成一个万能 Service：

```text
Query API
→ immutable Artifact read plane

Command API
→ operational Run control plane
```

---

## P8.4 — Research Studio Web

### 目标

把 P7.12 的 Research Result Viewer 升级为可以日常使用的 Web-native Research 产品。

第一版产品结构：

```text
Research
├── New Research
├── Runs
└── Results
```

### New Research

至少支持：

- exact Dataset Snapshot selection/reference；
- Feature / Factor definition；
- parameters；
- Target；
- Statistics；
- finite Sweep；
- specification preview/validation；
- Run submission。

### Runs

至少支持：

```text
QUEUED
RUNNING
COMPLETED
FAILED
CANCEL_REQUESTED
CANCELLED
```

用户关闭浏览器后，服务器运行不受影响。

### Completed Run

完成后只记录/返回 exact `research_result_fingerprint` / Artifact reference，并复用 P7.12 既有：

```text
Artifact Overview
Statistics Catalog
Statistics Series
Chart
Exact Table
```

浏览器仍然只是 Control + Presentation client，不承担 Research calculation authority。

---

## P8.5 — Operational Hardening & Database Recovery

### 目标

把 P8 从“开发机能跑”收敛成长期可运行、可维护、可恢复的单机/小团队服务。

必须完成：

- API/Scheduler/Worker health/readiness；
- stuck run detection；
- worker diagnostics；
- structured operational logs；
- run/attempt audit；
- graceful stop/restart；
- PostgreSQL schema compatibility verification；
- explicit migration procedure；
- pre/post migration validation；
- logical backup；
- restore test；
- production-ready recovery procedure；
- 必要时设计 WAL/PITR strategy；
- database/server version pinning policy。

V1 优先单机模块化单体，不提前引入 Kubernetes、distributed scheduler、large observability platform 或复杂 rolling-schema deployment。

---

## P8.6 — P8 Product Closure & Final Certification

### 目标

验证完整 Web-native Research 产品纵切面，而不是分别证明几个组件存在。

至少完成一个真实 end-to-end scenario：

```text
Start PostgreSQL
→ Start API / Scheduler / Worker
→ Browser creates Research Specification
→ Submit
→ durable QUEUED Run
→ Worker claim / RUNNING
→ OnlyResearchRuntime execution
→ Research Result committed
→ Artifact materialized
→ Run COMPLETED with exact result reference
→ Web opens existing Result Viewer
→ restart API/Worker and verify durable state
→ simulate worker failure and verify recovery/re-entry
```

P8 所有 Task Complete 后执行一次完整 Phase Gate；Phase Complete 后冻结 exact Final SHA，再执行 Final-SHA Certification。只有 artifact verdict 为 `ACCEPTED` 才可以把 P8 标记为 `DONE / CERTIFIED`。

---

## P8 Storage Boundary

P8 正式引入的数据库只有：

```text
PostgreSQL
→ Operational / Control State
```

当前 immutable file stores 继续保留：

```text
Dataset Snapshot
Calculation Result
Statistics Result
Research Result
Research Artifact
→ content-addressed Parquet / JSON / Manifest
```

长期 Historical / Time-Series Store 可以采用 ClickHouse，但它不属于 P8 Control Plane 的硬前置条件，也不在当前 Roadmap 中分配 P9/P10 等后续编号。未来如启动 Historical Data Platform，必须重新从 current repository truth 设计 Provider Evidence、Raw Archive、Canonical Historical Store、Dataset Materializer 与 Snapshot boundary。

即使未来存在 ClickHouse，Research Runtime 仍应消费 immutable Dataset Snapshot，而不是直接对不断变化的 ClickHouse 查询作为正式 Research 输入。

---

## P8 明确非目标

P8 不实现：

- Historical Data Platform / ClickHouse semantic integration；
- QMT full historical acquisition pipeline；
- Provider reconciliation platform；
- Optimizer / automatic best-parameter authority；
- 新 Statistics 类型作为 P8 主任务；
- Backtest Web productization；
- Sim Web control；
- Live Runtime / real-money control；
- Multi-user SaaS / RBAC platform；
- Distributed Research cluster；
- Kafka / Redis / Kubernetes 基础设施平台；
- 将 immutable Research Result 迁移进 PostgreSQL；
- 完整 heterogeneous Research+Trading Engine lifecycle closure，除非 P8 execution control 的真实依赖证明其不可避免。

---

## P8 退出条件

P8 只有在以下条件同时满足时才能完结：

- 用户可以用正式 Web UI 创建并提交 versioned Research Specification；
- submission 在返回成功前已经 durable commit；
- PostgreSQL 是唯一 Research Run operational write authority；
- Scheduler/Worker 支持 claim、lease、attempt、crash/restart recovery 与 cancellation；
- Worker 只通过 OnlyEngine/OnlyResearchRuntime 执行现有 Research semantic chain；
- Run COMPLETED 只引用 exact existing Research Result / Artifact，不复制结果真值；
- 关闭/刷新浏览器不影响服务器执行；
- API/Worker/PostgreSQL restart 后运行状态可恢复；
- 数据库 migration/backup/restore procedure 可验证；
- Web-native end-to-end product scenario PASS；
- Phase Gate PASS；
- exact Final-SHA Certification artifact verdict = `ACCEPTED`。

---

## P8 以后

**当前不冻结 P8 之后的阶段编号、任务或产品承诺。**

旧 Roadmap 中预先规划的 `P9 Live Runtime Foundation`、`P10 Multi-Market Product Expansion` 与“后续候选”列表已经撤销，不再作为工程任务承诺。P8 完成并取得 exact Final-SHA `ACCEPTED` 后，再重新阅读当时的 Repository、产品需求、运行经验与未解决风险，从第一性原理决定下一阶段。

目标 Live、多市场、Historical Data Platform 等长期架构方向可以继续存在于已接受 ADR/Architecture contract 中，但“目标架构存在”不等价于“已经冻结为下一个 milestone”。

---

## Roadmap 门禁

- Repository / current tests / accepted ADR 是当前事实来源；
- 领域对象、Profile、Factory、Manager、Fixture 或单组件测试存在，不代表产品可用；
- Target architecture 与 current implementation 必须分开陈述；
- Backtest 保持 event-driven，Research 才允许 vectorized execution；
- Backtest/Sim/Live 共享一个 trading semantic core；
- Runtime Type 不是 Execution Permission；
- 不创建 Runtime-specific duplicate economic authority；
- Research Control Plane 不创建第二 Research Semantic Authority；
- PostgreSQL 只拥有 Operational State；
- Immutable Result/Artifact 继续保持 content-addressed authority；
- 一个 Trading Runtime 只绑定一个 Account、Market Product 和 currency；
- 跨市场汇总只读，不成为交易 authority；
- Web/Manual/Liquidation 不绕过 Engine、Risk、Broker 或 Durable Transaction；
- 不新增 `PAPER` 或 standalone `SHADOW` 产品依赖；
- 不以永久兼容层代替迁移和删除；
- Major Milestone 只有 exact Final-SHA certification artifact 为 `ACCEPTED` 才能声明 `DONE / CERTIFIED`。
