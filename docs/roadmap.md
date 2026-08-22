# OnlyAlpha 路线图

本文件只描述当前实现迁移到下一目标阶段的阶段边界、退出条件与非目标。当前事实以源码、正式测试、未被替代的 ADR 和产品认证为准；历史实现细节保存在 `docs/adr/`、`docs/reports/` 与 Git history，不在 Roadmap 中重复维护任务流水账。

Runtime taxonomy 继续由 [ADR 0068](adr/0068-runtime-product-taxonomy-and-trading-semantic-equivalence.md) 冻结，多市场/异构 Runtime 拓扑由 [ADR 0080](adr/0080-multi-market-platform-and-heterogeneous-runtime-lifecycle.md) 冻结，Live genesis/manual/liquidation 目标合同由 [ADR 0081](adr/0081-live-genesis-manual-workload-and-liquidation-control.md) 冻结。长期 Strategy Product 语义、Research → Backtest → Sim → Live Promotion 与 Web/LLM Agent 参考目标见 [Target Strategy Product Architecture](strategy_product_architecture.md)；该目标存在不等于已经冻结 P8 之后的 milestone。

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
Milestone State: DONE / CERTIFIED
Current Increment: P8.6 — DONE / CERTIFIED
Latest Certified Milestone: P8 — DONE / CERTIFIED
P8 Final Certification Subject: 88e616c52fb6c3085e7c64d73f174257bf2d002e
P8 Final Certification Run: 32581861744
P8 Final Certification Verdict: ACCEPTED
Next Semantic Direction: not frozen; re-plan from current Repository truth
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

> 用户如何不再手工执行本地 Python，而是通过 Web 选择研究对象、组合已注册的 Indicator / Feature / Factor、配置研究条件，提交一个 Research，由服务器可靠、持久、可恢复地执行，并在完成后查看 exact Result / Artifact 与科学可视化？

P8 不建立第二套 Research Semantic Plane。P8 新增的是 Operational Control Plane 与 Web-native Research product surface：

```text
Browser
   ↓
Universe / Research Definition
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
Scientific Research Viewer
```

固定原则：

```text
Research Run / Scheduler State
→ PostgreSQL Operational Authority

Research Semantic Result
→ Existing Immutable Authorities

Web selection / charts
→ client-side control and presentation
→ never semantic authority
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

状态：**IMPLEMENTED / VERIFIED LOCALLY — CANCELLATION / RECOVERY CONVERGENCE CLOSED**。P8.2 已建立独立 Attempt/Worker UUID4 identity、`ACTIVE/SUCCEEDED/FAILED/EXPIRED/CANCELLED`
Attempt history、one-ACTIVE PostgreSQL constraint、`queued_at/run_id` deterministic transactional claim、PostgreSQL
`clock_timestamp()` lease authority、周期 heartbeat、expiry/new-Attempt recovery、exact Attempt/Worker fencing、bounded retry、cooperative
cancellation 与 graceful stop。Worker 重新验证 Dataset 和 admission evidence，并只经 `OnlyEngine → OnlyResearchRuntime` 执行；真实
PostgreSQL 16.10 已证明并发 claim、lease/fencing、M1/M2→M3 与 Artifact-commit crash deterministic re-entry。独立
`research-execution` lane 与 `research-postgres` lane 已进入 impact/CI/certification matrix。本状态不包含 P8.3 HTTP command、Web 或 P8
Final-SHA certification。

P8.2 correctness closure 进一步冻结 semantic-fact-first cancellation recovery：expired Attempt 不再由 PostgreSQL 直接把
`CANCEL_REQUESTED` 终结为 `CANCELLED`。无 ACTIVE Attempt 后，Application reconciliation 只读 verified-load resolved exact Research
Result + Artifact；完整证据收敛 `COMPLETED`，absent/partial 收敛 `CANCELLED` 且不继续 semantic work，corrupt authority 收敛 fail-closed
`FAILED`。终态使用 exact revision/state + no-ACTIVE transaction，max-attempts 与 stale Worker 均不能覆盖该事实。P8.2 已具备进入 P8.3
Research Command API 的本地语义前提，但 P8 整体仍为 `IN_PROGRESS`，未声明 P8 DONE/CERTIFIED。

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

状态：**IMPLEMENTED / VERIFIED LOCALLY**。P8.3 已完成 UUID4 Idempotency Key、canonical command fingerprint、Run + submission
mapping PostgreSQL 原子提交、replay fast path、exact Run read projection、deterministic keyset pagination、取消 CAS 竞争重解释、
稳定 HTTP DTO/error、full/portable 双 App composition、OpenAPI/Web client contract 与 `research-command` canonical lane。Command API
不创建 Attempt、不启动 Worker/Engine、不读取 Artifact content；P8 仍为 `IN_PROGRESS`，下一语义方向是 P8.4。

### 目标

建立正式 write/control HTTP boundary，使外部 Application/Web 可以安全提交、查询和取消 Research Run。

P7 read-only Query API 继续保持 Artifact-backed consumer boundary；P8 Command API 是独立 operational boundary。

正式接口：

```text
POST   /api/v2/research/runs
GET    /api/v2/research/runs/{run_id}
GET    /api/v2/research/runs
POST   /api/v2/research/runs/{run_id}/cancellation
```

URL、幂等、分页与取消竞争由 ADR 0091 冻结。

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

P8.3 应为 P8.4 的 `Runs` 产品面提供稳定 operational read projection；如果实现 Run List，需要 deterministic ordering/pagination，但不得把 Research Result content 搬进 Command API。

---

## P8.4 — Research Studio Web

P8.4.0 已在 Core programmatic boundary 实现并完成本地 affected verification：严格、canonical、authoring-channel-neutral
的 `OnlyResearchDefinition` 可解析 Universe intent、现有 Dataset Definition 与 verified Snapshot，组合全局有限 Candidate
Space，将 typed Eligibility/Entry/Exit AST lowering 为 existing Calculation Graph，并继续生成现有
`OnlyResearchSpecification -> OnlyResearchWorkloadPlan`。该实现只增加 RESEARCH internal `PREDICATE` Calculation backend，未增加
Predicate Runtime/Store，也不代表 P8.4 Web、API、Scientific Result Evidence 或整个 P8 已完成/认证。

P8.4.0.1 已收敛 Definition 语义合同：`definition_fingerprint` 只表示 canonical authoring contract，Resolution 另行持有基于
verified Dataset Snapshot 与 authoritative normalized semantics 的 `resolved_definition_fingerprint`；Candidate identity 不再混入
raw authoring representation。Predicate V1 冻结 nullable three-valued comparison/AND/OR/NOT 与 terminal NULL-preserving 语义，
series comparison 使用既有 data type/dimensions/unit evidence fail closed。Dataset input 只接受 canonical `bar.<field>` source；
诊断在 authoring AST 原始顺序上完成，canonical AST 只用于 identity 与 Graph lowering。Definition lowering 已由独立构造的 Exact
Specification 与 Workload 等价测试证明，并进入正式 `research-definition` verification/CI lane。该 closure 不新增执行 authority，
也不升级 P8 认证状态。

P8.4.1 已实现正式 Research Discovery/Definition HTTP contract：Calculation、Universe、Statistics、Dataset Field Catalog 均只投影
现有 authority，internal PREDICATE 不公开；Definition transport 显式映射到现有 `OnlyResearchDefinitionResolver`，返回 authoritative
fingerprints、exact Dataset、bounded Candidate Space、published variables 与可不经语义转换直接提交 P8.3 Run API 的
`exact_specification`。Command、Artifact、Definition、Discovery 的 route/error ownership 已显式分离，OpenAPI 与 TypeScript
transport/client 已同步。该 increment 不增加 Definition/Resolution Store、Run authority、Runtime 或 React Builder；P8 保持
`IN_PROGRESS`。

P8.4.1.1 已关闭两个公共边界缺口：API composition 从 Definition Resolver 使用的同一 registered Universe authority 投影 Discovery，
且无该 authority 时不再宣称 `REGISTERED_POOL / REGISTERED_UNIVERSE`；Research Definition HTTP/OpenAPI/Web authoring vocabulary
收紧为 `INDICATOR / FACTOR / TARGET`，而 Eligibility/Entry/Exit 的 internal `PREDICATE` lowering、exact Specification 与 P8.3 Run
submission semantics 保持不变。该 closure 不新增 Universe/Calculation authority，也不改变 P8 `IN_PROGRESS` 状态。

P8.4.2 已实现 exact scientific evidence chain：Definition 生成 Specification V2 publication membership，既有 Run/PostgreSQL canonical
payload 可供 fresh Worker 重建同一 Candidate identity 与 internal Predicate workload；Result Plan/Research Result V2 引用 exact
Calculation/Statistics authorities；`RESEARCH_SCIENTIFIC_V2` Artifact 自包含投影 market、typed variables、nullable signals、Statistics 与
canonical Graph，并分离 logical/byte identity；Query/HTTP 只读 Artifact。V1 Specification/Result/Artifact 保持可读，V1 scientific query
显式失败。该 increment 不新增 execution phase 或 Evidence/Candidate/Signal/Graph/Predicate Store；P8 仍为 `IN_PROGRESS`。

P8.4.2.1 已收紧该 evidence chain 的完整性与确定性：Calculation 统一拥有 internal Predicate primitive，Specification/Runtime 不再
依赖 Definition implementation；Definition 只投影 Specification 已构造的 Candidate identity，并统一发布 Indicator、Factor 与 Target
变量；Result Plan 锁定 `(candidate_fingerprint, role)` Signal 唯一性。Scientific Artifact V2 现对 exact Statistics reference/catalog、
Result schema V2、严格 SHA path、并发 immutable publication、逻辑主键、typed scalar canonical form 及 Variable/Signal 完整 market axis
进行 self-contained fail-closed 验证；Query V2 catalog/page 只补 Artifact-only read-model invariant。所有既有 semantic identity 算法与 V1
Specification/Result/Artifact/Query 保持不变；P8 仍为 `IN_PROGRESS`。

P8.4.3 已实现第一个完整 Web-native Research 日常控制闭环。Browser Draft 只通过唯一 transport builder 形成正式 Definition，server
Resolution 独占 Dataset/Calculation/Candidate/Specification 语义；monotonic edit revision 与 AbortController 共同阻止 stale response
成为提交权威。最新 `exact_specification` 经既有 P8.3 Command API 与单一 Idempotency Key 创建 durable Run；Runs 页面只显示、轮询和
取消 PostgreSQL authority 的公开事实，Completed Run 精确导航到既有 Artifact/Query Result consumer。Stage 0 同时 fail closed
non-candidate multi-lineage generic publication 与 internal PREDICATE generic publication，candidate publication、singleton global evidence
及 Eligibility/Entry/Exit Signal evidence 保持合法。Former P8.4.2.3 publication admission concerns 因此在 P8.4.3 Stage 0 内闭环，不再
作为独立最终 milestone。没有新增 endpoint、Schema、Store、Runtime 或 semantic identity formula；P8 仍为 `IN_PROGRESS`，后续
Viewer closure 由 P8.4.4 完成。

P8.4.3.1 关闭 Web submission determinism 与 authoring admission 的剩余缺口。Browser pending submission intent 只绑定权威
Resolution 返回的 `specification_fingerprint` 与一个 UUID4 Idempotency Key；transport、HTTP、decode/contract 等任意 thrown failure
均不消费该 intent，只有合法权威成功响应才按 matching fingerprint 清除，因此重试不会产生第二个 durable Run，而同一 Specification
的显式新 Run 仍使用新 key。唯一 Draft → Definition builder 现在对 FIXED 多值歧义、stale/unknown published output、空 output 与未知
Statistics method 全部 fail closed；Web 同时补齐既有 `price_type` 与 `adjustment_reference` authoring controls。Definition、Dataset、
Specification、Candidate、Calculation、Statistics、Result、Artifact 与 Run identity semantics 均未改变；未新增 endpoint、Store、
Runtime、PostgreSQL schema 或 authority。该 closure 后续由 P8.4.4 完成 Scientific Viewer 与 Graph Inspector。

P8.4.4 已完成 immutable Scientific Result/Artifact 的日常分析工作台。Artifact-only Query read contract 机械投影 canonical
instrument、Candidate typed assignment/Signal membership 与 strict exact Calculation Graph；HTTP/OpenAPI/generated TypeScript/Zod admission
对 Graph node、port、binding、typed scalar、fingerprint、schema 与 linkage fail closed。统一 Result selection 驱动 Market K-line/volume、
Published Variable、Artifact Signal marker、IC/RankIC、Candidate table 与 1D/2D/3+ exact-time comparison、Semantic/Exact Graph Inspector 及
Market/Variable/Signal/Statistics Exact Data。Lightweight Charts、ECharts 与 Graphviz 均位于 OnlyAlpha adapter 后，Decimal/nanosecond
只在 renderer projection 边界有损转换；Browser 不计算 Signal/Statistics/Candidate score，不读取 Parquet，也未新增 Store、Runtime、
PostgreSQL schema、semantic identity 或 authority。P8 保持 `IN_PROGRESS`，下一语义方向进入 P8.5。

P8.4.4.1 关闭 Scientific Viewer 的读合同与展示确定性缺口。唯一 public chain 现在是
`OnlyResearchQueryService → strict Python DTO → generated OpenAPI → generated.ts → strict Zod`；summary/candidate/graph 字段均由
verified Artifact evidence 机械投影，Candidate/Calculation/Graph linkage 不一致按 corrupt fail closed。Graph INTEGER 以 canonical
string 保留无界 Python `int`，React Query identity 包含所有 server selector，Candidate axes 使用 numeric coordinates，external
Dataset source 只成为 deterministic presentation node，Signal role 使用 closed vocabulary 与 exact equality。未修改任何 Definition、
Specification、Candidate、Calculation、Graph、Statistics、Result、Artifact 或 Run identity，未新增 Store、Service、Runtime、DB schema
或 authority。P8.4.4 因此完成 affected Gate，但 P8 仍为 `IN_PROGRESS`，且未获得新的 Final-SHA certification。

### 目标

把 P7.12 的 Research Result Viewer 升级为可以日常使用的 Web-native Research 产品。P8.4 的退出面不是“让用户粘贴一个 Dataset SHA”，而是让用户在浏览器中完成从研究对象选择到结果科学分析的完整闭环，同时所有选择最终仍解析为 exact immutable Research identity。

第一版产品结构：

```text
Research
├── New Research
├── Runs
└── Results
```

### New Research

至少支持：

- 单票、股票池或全市场 Universe selection；
- Universe / 时间范围等用户选择解析为 exact Dataset Snapshot selection/reference；
- 已注册 Indicator / Factor definition selection；
- Indicator / Factor parameters 与 finite Sweep；
- Indicator named Feature selection；
- Factor primary Score 的选择/展示；
- 市值、价格、流动性等 Eligibility / Filter 条件的研究表达；
- 第一阶段有限 `AND / OR / NOT + comparison` 的 Entry / Exit Decision/Signal research expression；
- Target；
- Statistics；
- exact Research Specification preview/validation；
- Run submission。

P8 可以复用统一 Calculation infrastructure 表达 Filter，但 Web/Domain 必须区分 `Eligibility` 与普通 Entry/Exit predicate 的 semantic role。单票可以默认 time-series、多票/全市场可以默认 cross-sectional，但 Universe 与 mathematical Decision Mode 不得在长期 Domain 中硬绑定。

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

### Completed Run / Scientific Research Viewer

完成后只记录/返回 exact `research_result_fingerprint` / Artifact reference，并复用/扩展 P7.12 immutable read plane。Research 结果至少应能够表达并展示：

```text
Artifact Overview
Statistics Catalog
Statistics Series
Exact Table
Historical K-line
Indicator / selected Feature overlay or panel
Factor Score panel
ENTRY / EXIT signal markers
Cross-sectional IC / Rank IC
Distribution / Scatter / Quantile / Heatmap / Candidate comparison
```

具体图表必须由当前 Result/Artifact 能证明的数据驱动；浏览器不得重新计算新的 Factor、Statistics 或 Signal semantic truth。图表中的 lossy number/time conversion 仍只是 presentation projection。

### P8.4 不做的 Strategy Product 能力

P8.4 不要求完整实现：

- embedded IDE 的 production Code Admission；
- LLM Agent 自动生成并注册代码；
- immutable Strategy Revision authority；
- Research → Backtest Promotion；
- Backtest / Sim / Live Web productization。

这些是长期 Strategy Product 参考方向，不应为了“Web 看起来完整”而未经 Domain/ADR 设计提前塞进 P8。

浏览器仍然只是 Control + Presentation client，不承担 Research calculation authority。

---

## P8.5 — Operational Hardening & Database Recovery

状态：`IMPLEMENTED / VERIFIED LOCALLY`。P8 仍为 `IN_PROGRESS`，未获得新的 Final-SHA certification。

正式 Research Worker executable 现只组合既有 Scheduler、fenced Worker、Cancellation Reconciler 与 `OnlyEngine ->
OnlyResearchRuntime` execution path；SIGINT/SIGTERM 进入 drain，停止新 claim 并让 ACTIVE Attempt 保持 heartbeat 安全完成。API
提供数据库无关 liveness 与 fail-closed readiness。Migration 0006 新增 PostgreSQL server-clock 的最小 Worker presence；它只服务
diagnostics，不参与 claim、lease、retry 或 finalization。只读 diagnosis 不新增 `STUCK` Run state、不写 Run/Attempt，operator projection
按明确 key 展示 Run 与 Attempt history。

数据库仍执行 checksummed forward-only migration、advisory lock、transaction 与 startup compatibility-only。operator tooling 现冻结
PostgreSQL server/client major 16，custom-format backup 生成 secret-free metadata 与 SHA-256，isolated restore 在 `pg_restore` 后验证
schema、selected Run 和 ordered Attempt history。完整灾备仍要求 PostgreSQL operational backup 与 immutable `USER_DATA_ROOT` semantic
backup 两者。运行手册见 `docs/operations/research-service.md`。

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

状态：`DONE / CERTIFIED`。Deployment coherence、real Browser product E2E、四个 semantic commit SIGKILL recovery boundaries 与
coherent/wrong restore-pair 已进入 mandatory `research-product-closure` lane 并通过。完整 Phase Gate 通过后冻结 subject
`88e616c52fb6c3085e7c64d73f174257bf2d002e`；Final-SHA Certification run `32581861744` 的 static、build、Web、canonical lanes、
PostgreSQL product closure、coverage、Semgrep、dependency audit、Python/TypeScript CodeQL 与 aggregate verdict 全部成功，认证工件
verdict 为 `ACCEPTED`。

ADR 0096 冻结一项新的 deployment operational compatibility fact：一个 Research PostgreSQL deployment 只绑定一个 immutable
Research semantic-store namespace。显式 operator init 写入 root-level immutable namespace ID 并建立 PostgreSQL singleton binding；
API/Worker startup 只读验证，错/缺失/损坏 identity 在 readiness/claim 前 fail closed。Store ID 不是路径、不是科研 semantic identity，
不进入 Calculation/Specification/Result/Artifact fingerprint，也不建立 central Artifact registry。

### 目标

验证完整 Web-native Research 产品纵切面，而不是分别证明几个组件存在。

至少完成一个真实 end-to-end scenario：

```text
Start PostgreSQL
→ Start API / Scheduler / Worker
→ Browser selects Universe / exact Dataset
→ Browser selects registered Indicator / Feature / Factor / parameters
→ Browser defines limited Eligibility / Decision / Signal research expression
→ Browser creates exact Research Specification
→ Submit
→ durable QUEUED Run
→ Worker claim / RUNNING
→ OnlyResearchRuntime execution
→ Research Result committed
→ Artifact materialized
→ Run COMPLETED with exact result reference
→ Web opens Scientific Research Viewer
→ inspect K-line + Feature/Factor/Signal and Statistics relationship
→ restart API/Worker and verify durable state
→ simulate worker failure and verify recovery/re-entry
```

P8 已按 `Task Complete -> Phase Gate -> exact Final SHA -> Final-SHA Certification -> ACCEPTED` 顺序闭合并标记为
`DONE / CERTIFIED`。P8 之后的 milestone 不在本文预先编号或冻结。

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
- immutable Strategy Revision / formal Strategy Promotion authority；
- Research → Backtest → Sim → Live Promotion workflow；
- Web embedded IDE production Code Admission；
- LLM Agent 自动生成并注册可交易代码；
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

- 用户可以用正式 Web UI 选择单票、股票池或全市场 Research Universe，并解析为 exact Dataset Snapshot；
- 用户可以选择已注册 Indicator / Factor、设置参数/Sweep、选择 named Feature，并表达有限 Eligibility / Decision / Signal research intent；
- 用户可以用正式 Web UI 创建并提交 versioned Research Specification；
- submission 在返回成功前已经 durable commit；
- PostgreSQL 是唯一 Research Run operational write authority；
- Scheduler/Worker 支持 claim、lease、attempt、crash/restart recovery 与 cancellation；
- Worker 只通过 OnlyEngine/OnlyResearchRuntime 执行现有 Research semantic chain；
- Run COMPLETED 只引用 exact existing Research Result / Artifact，不复制结果真值；
- 完成的 Research 可以在 Web 中查看 K-line、selected Feature、Factor Score、Signal/买卖点与 Statistics 的关系，并支持必要的 cross-sectional scientific analysis；
- 所有 Web chart / table 仍只是 exact Artifact-backed presentation projection；
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

### 长期 Strategy Product 参考方向

在不冻结 milestone 编号的前提下，OnlyAlpha 已明确一个长期产品方向：Research 中验证过的候选策略应能通过显式 Freeze 形成 immutable Strategy Revision，并以同一策略语义自然进入 Backtest、Sim、Live。

```text
Draft Indicator / Factor / Decision
        ↓
Research
        ↓
Research Result / Artifact Evidence
        ↓
Freeze immutable Strategy Revision
        ↓
Backtest + Historical Evaluation Profile
        ↓
Promotion Evidence
        ↓
Sim + Realtime Simulated Profile
        ↓
Promotion Evidence
        ↓
Live + Explicit Deployment Permission
```

长期必须保持：

```text
Research Run != Strategy Revision

Strategy Revision
!= Portfolio Profile
!= Execution Profile
!= Runtime Permission

Same Strategy Revision
→ Backtest / Sim / Live
```

目标 Web 可以进一步提供 embedded IDE、Strategy Freeze/Promotion、Backtest/Sim/Live control；LLM / Agent 可以生成 Indicator/Factor/Decision 草稿、选择参数并操作受控 Research/Promotion workflow，但只能作为 Author / Operator Client，必须经过与人工相同的 Code Admission、determinism、identity、evidence 与 authorization gate，绝不能直接成为策略、结果或 Live permission authority。

详细参考架构见 [`docs/strategy_product_architecture.md`](strategy_product_architecture.md)。

目标 Live、多市场、Historical Data Platform 等长期架构方向也可以继续存在于已接受 ADR/Architecture contract 中，但“目标架构存在”不等价于“已经冻结为下一个 milestone”。

---

## Roadmap 门禁

- Repository / current tests / accepted ADR 是当前事实来源；
- 领域对象、Profile、Factory、Manager、Fixture 或单组件测试存在，不代表产品可用；
- Target architecture 与 current implementation 必须分开陈述；
- Backtest 保持 event-driven，Research 才允许 vectorized execution；
- Backtest/Sim/Live 共享一个 trading semantic core；
- Runtime Type 不是 Execution Permission；
- 不创建 Runtime-specific duplicate economic authority；
- 长期 Strategy Promotion 必须执行同一个 immutable Strategy Revision，不允许 Backtest/Sim/Live 复制策略语义；
- Strategy Revision、Portfolio Profile、Execution Profile、Runtime Permission 必须保持分离；
- LLM / Agent 只能作为 Author / Operator Client，不能成为 semantic/evidence/permission authority；
- Research Control Plane 不创建第二 Research Semantic Authority；
- PostgreSQL 只拥有 Operational State；
- Immutable Result/Artifact 继续保持 content-addressed authority；
- 一个 Trading Runtime 只绑定一个 Account、Market Product 和 currency；
- 跨市场汇总只读，不成为交易 authority；
- Web/Manual/Liquidation 不绕过 Engine、Risk、Broker 或 Durable Transaction；
- 不新增 `PAPER` 或 standalone `SHADOW` 产品依赖；
- 不以永久兼容层代替迁移和删除；
- Major Milestone 只有 exact Final-SHA certification artifact 为 `ACCEPTED` 才能声明 `DONE / CERTIFIED`。
