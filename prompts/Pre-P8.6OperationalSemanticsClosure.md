# OnlyAlpha — Pre-P8.6 Operational Semantics Closure
## Codex Implementation Prompt

> 目标：在进入 P8.6 Product Closure & Final Certification 之前，关闭当前主线中已经确认存在的运行语义缺口。
>
> 本任务不是增加产品能力，不是重构 Plugin Framework，也不是提前做 P8.6。
>
> 核心原则：
>
> **唯一性（Uniqueness）**
>
> **确定性（Determinism）**
>
> **可复现性（Reproducibility）**
>
> **Fail Closed**
>
> **One Domain → One Authority**
>
> **Fix the semantic root cause, not the symptom**

---

# 0. Repository Truth 高于本 Prompt

Repository:

```text
https://github.com/zongxin1993/OnlyAlpha
branch: master
```

本 Prompt 创建时审计到的基线是：

```text
f8b956a7d97862f44e8e7dbc91e465c100dc29b1
Feat: P8.5 Post-Closure — Composition Authority & Architecture Gate Closure
```

但是：

> **执行 Codex 任务时，当前 HEAD 才是唯一 Current Truth。**

开始修改前必须执行并记录：

```bash
git status
git rev-parse HEAD
git log -1 --oneline
```

然后重新阅读当前代码。

不要因为本 Prompt 写了某个类名、文件名或代码路径，就假设它在执行时仍然完全相同。

优先级必须遵循：

```text
1. 当前可执行源码
2. 当前正式测试 / Architecture Gate
3. 当前未被替代 ADR
4. AGENTS.md
5. docs/architecture.md
6. 当前 Roadmap / Operations docs
7. 历史 reports
8. prompts/
```

`prompts/` 是实现输入，不是 Current Truth。

如果当前 HEAD 已经解决本 Prompt 中某个问题：

- 不要重复实现；
- 先证明已经解决；
- 只处理仍然存在的缺口。

---

# 1. 任务定位

本任务定义为：

```text
Pre-P8.6 Operational Semantics Closure
```

它不是：

```text
P8.6 Product Closure
```

也不是新的 Research 功能。

它解决的是：

```text
当前正式设计已经声明的运行语义
        ↓
当前代码是否真的结构化保证这些语义
        ↓
如果不完全一致
        ↓
用最小生产修改关闭根因
```

当前 P8.5 的大架构已经成立：

```text
PostgreSQL
→ sole operational mutable authority

Immutable Dataset / Calculation / Statistics /
Research Result / Artifact Stores
→ sole semantic authorities

Worker
→ OnlyEngine
→ OnlyResearchRuntime

One Worker Process
→ One EngineServices composition
→ One Calculation Registry

Each claim
→ fresh OnlyEngine
→ fresh Runtime mutable execution state
```

本任务必须保持这些不变量。

---

# 2. 第一性原理

## 2.1 Operational Truth 与 Semantic Truth 必须分离

```text
PostgreSQL
→ Run
→ Attempt
→ Lease
→ Cancellation intent
→ Worker presence
→ operational projection
```

回答：

```text
系统现在处于什么运行状态？
谁拥有当前 Attempt？
是否还能 finalization？
```

Immutable stores：

```text
Dataset Snapshot
Calculation Result
Statistics Result
Research Result
Artifact
```

回答：

```text
Research 实际算出了什么？
```

禁止：

```text
为了修 Worker lifecycle
→ 新增 semantic state 到 PostgreSQL

为了修 retry
→ 新增第二个 retry manager

为了修 shutdown
→ 新增 second Worker lifecycle authority

为了修 plugin coupling
→ 新增第二套 Research composition root
```

---

## 2.2 Retry 的第一性原理

Retry 不是“发生异常就再试一次”。

Retry 只能用于：

```text
同样的语义输入
+
同样的有效 composition
+
外部暂态条件恢复后
有合理可能成功
```

例如：

```text
temporarily unavailable PostgreSQL
lease expiry
明确的 transient infrastructure failure
```

不能 retry：

```text
unknown Calculation type
unknown semantic version
canonical Specification 重新解析失败
semantic evidence drift
corrupt immutable Dataset
corrupt Result / Artifact
确定性的 contract mismatch
unsupported semantic input
```

正式原则：

```text
Deterministic failure
!=
Transient failure
```

如果错误在同样 durable facts 下必然再次发生：

```text
retry
=
重复消耗 Attempt budget
+
污染 failure history
+
掩盖根因
```

这是错误行为。

---

## 2.3 Shutdown 的第一性原理

必须区分：

```text
process stop request
```

与：

```text
Research semantic failure
```

二者不等价。

正确模型：

```text
SIGINT / SIGTERM
        ↓
Application stop request
        ↓
Worker enters draining
        ↓
NO NEW CLAIM
        ↓
Already ACTIVE claim
continues heartbeat
        ↓
safe completion / cancellation / ownership loss
        ↓
process exit
```

核心不变量不是：

```text
signal 到达后的绝对纳秒级零代码执行
```

而是必须建立一个明确线性化点：

```text
stop request observed before claim transaction begins
→ claim is forbidden

claim transaction already began before stop observation
→ claim is in-flight
→ drain it safely
```

这必须能用 deterministic interleaving test 证明。

---

## 2.4 Bounded Shutdown 的第一性原理

```text
thread.join(timeout=N)
```

不等于：

```text
process shutdown is bounded
```

如果 background non-daemon thread 正卡在：

```text
network connect
SQL execution
database lock
half-open connection
```

则：

```text
join timeout
→ main thread returns/raises
→ non-daemon thread still alive
→ Python process may still not exit
```

因此真正的 bounded shutdown 必须从 I/O 边界开始：

```text
bounded network connect
+
bounded SQL execution
+
bounded lock wait where required
+
bounded thread join
```

不能只在最后一层 `join()` 上制造“看起来有 timeout”的假象。

---

# 3. 本任务必须先回答的 Authority Questions

修改任何代码前，先输出下面问题的答案：

```text
1. 谁拥有进程 stop request？
2. 谁拥有 Worker draining lifecycle？
3. 谁可以开始一个新的 claim？
4. claim 的线性化边界在哪里？
5. ACTIVE Attempt ownership 的唯一 authority 是什么？
6. Retry policy 的唯一 authority 是什么？
7. Specification resolution failure 的正式 error contract 在哪里？
8. 哪些 failure code 是 retryable？
9. PostgreSQL operational I/O 当前有哪些 timeout？
10. timeout 是 Repository contract，还是依赖部署者 DSN 偶然配置？
11. heartbeat / presence thread 是 daemon 还是 non-daemon？
12. Worker signal exit code 的正式 authority 在哪里？
13. 当前 Research API 和 Worker composition 是否共享同一个 composition mechanism？
14. 哪些问题属于本次 correctness closure？
15. 哪些问题只是 future architecture hardening，必须明确不做？
```

如果无法明确回答：

> 不允许直接新增 Manager、Service、Store、Coordinator 或 Registry abstraction。

---

# 4. 必须重新阅读的代码

至少重新阅读：

```text
AGENTS.md
README.md
docs/roadmap.md
docs/architecture.md

docs/adr/0090-research-execution-attempt-lease-fencing-and-recovery.md
docs/operations/research-service.md

src/onlyalpha/application/stop_controller.py
src/onlyalpha/application/engine_runner.py

src/onlyalpha/research/worker_main.py

src/onlyalpha/research/execution/worker.py
src/onlyalpha/research/execution/policy.py
src/onlyalpha/research/execution/errors.py
src/onlyalpha/research/execution/model.py
src/onlyalpha/research/execution/scheduler.py
src/onlyalpha/research/execution/reconciliation.py

src/onlyalpha/research/run/admission.py
src/onlyalpha/research/run/errors.py
src/onlyalpha/research/run/model.py

src/onlyalpha/research/specification/errors.py
src/onlyalpha/research/specification/resolver.py

src/onlyalpha/persistence/postgres/config.py
src/onlyalpha/persistence/postgres/research_run_store.py
src/onlyalpha/persistence/postgres/research_execution_store.py
src/onlyalpha/persistence/postgres/research_operations_store.py

src/onlyalpha/research/operations/presence.py
src/onlyalpha/research/operations/model.py

src/onlyalpha/runtime/defaults.py
src/onlyalpha/plugin/discovery.py

tests/research/execution/
tests/research/postgres/
tests/architecture/test_research_execution_boundaries.py
tests/architecture/test_postgres_operational_authority.py
tests/architecture/test_graceful_shutdown_boundaries.py
```

如果当前 HEAD 文件路径发生变化，以当前 Repository 为准。

---

# 5. Stage 0 — Reproduce Before Fix

不要先写代码。

先证明当前问题是否仍然存在。

需要至少验证四个问题：

```text
C1 — deterministic re-resolution failure retry classification
C2 — external stop → claim race
C3 — PostgreSQL operational I/O boundedness
C4 — Worker signal exit-code consistency
```

每个问题必须给：

```text
Current Code Path:
Observed / Proven Behavior:
Expected Contract:
Root Cause:
Minimal Fix Boundary:
```

不要仅引用旧报告。

---

# 6. C1 — Deterministic Re-resolution Failure Must Not Retry

## 6.1 当前需要验证的代码路径

审计：

```text
Worker execute_claim()
→ load Run
→ verified-load Dataset
→ resolver.resolve(run.specification)
→ recompute admission evidence
→ compare
→ runtime execute
```

确认：

```text
OnlyResearchSpecificationResolver.resolve()
```

是否会抛：

```text
OnlyResearchSpecificationError
```

并带有：

```text
phase
code
detail
```

同时确认 Worker 是否精确 catch 它。

当前审计基线中存在的问题是：

```text
OnlyResearchSpecificationError
        ↓
falls through generic Exception
        ↓
UNEXPECTED_WORKER_FAILURE
        ↓
RetryPolicy marks it retryable
```

必须重新验证当前 HEAD。

---

## 6.2 问题本质

一个已经 durable QUEUED 的 Run：

```text
Admission-time composition C1
```

如果到 execution 时：

```text
Worker composition C2
```

已经不能重新解析 exact Specification：

```text
unknown type
unknown semantic version
semantic contract mismatch
```

那么：

```text
Resolve(S, C2)
```

已经确定性失败。

再创建 Attempt #2：

```text
Resolve(S, C2)
```

仍然失败。

因此：

```text
retry
```

没有任何信息增益。

这是：

```text
semantic/composition incompatibility
```

而不是：

```text
transient worker failure
```

---

## 6.3 正确目标

必须形成：

```text
Known deterministic Specification / Admission revalidation failure
        ↓
stable structured failure
        ↓
FINAL_FAIL
```

而不是：

```text
generic UNEXPECTED_WORKER_FAILURE
        ↓
RETRY
```

---

## 6.4 Error Mapping 原则

优先复用已经存在的正式错误 taxonomy。

不要创建：

```text
WorkerSpecificationResolverError
WorkerRetrySemanticError
RetryMappingManager
```

如果当前已有：

```text
OnlyResearchSpecificationError
OnlyResearchRunAdmissionError
OnlyResearchRunFailure
```

就复用。

建议语义之一：

```text
OnlyResearchSpecificationError
→ OnlyResearchRunFailure(
    phase=ADMISSION or EXECUTION,
    code=EXECUTION_SEMANTIC_DRIFT
)
```

或者使用一个更精确的稳定 code：

```text
EXECUTION_SPECIFICATION_RESOLUTION_FAILED
```

但只有在当前 failure taxonomy 确实需要区分时才新增。

不要因为“更清晰”就无限增加 code。

必须保证这个 failure：

```text
non-retryable
```

---

## 6.5 同时检查正式错误是否被 generic collapse

审计 Worker 当前所有：

```text
except Exception
```

前的 known boundaries。

至少检查：

```text
OnlyResearchSpecificationError
OnlyResearchRunAdmissionError
OnlyResearchRunStoreUnavailableError
OnlyResearchExecutionStoreUnavailableError
OnlyResearchCalculationError
Dataset verification errors
Runtime structured failure
```

原则：

```text
Known error with stable machine-readable semantics
→ preserve it

Unknown truly unexpected error
→ UNEXPECTED_WORKER_FAILURE
```

不要让正式错误全部坍缩到：

```text
UNEXPECTED_WORKER_FAILURE
```

---

## 6.6 RetryPolicy 不要扩大

禁止通过：

```text
把更多 failure 加入 retryable list
```

来修问题。

真正应该做的是：

```text
classification correct
→ existing RetryPolicy works correctly
```

除非重新审计证明 RetryPolicy 本身有错误，否则不要改其设计。

---

## 6.7 C1 必须新增测试

至少：

### Test A — deterministic specification failure final-fails

构造：

```text
Run admitted with valid exact Specification
```

然后让 execution-time resolver：

```text
raise OnlyResearchSpecificationError(
    TYPE_RESOLUTION,
    RESEARCH_SPEC_CALCULATION_TYPE_UNKNOWN,
    ...
)
```

证明：

```text
Attempt #1
→ FAILED terminal

Run
→ FAILED

No RETRY_PENDING
```

---

### Test B — deterministic semantic drift still final-fails

保留/确认：

```text
admission_resolution_fingerprint mismatch
→ EXECUTION_SEMANTIC_DRIFT
→ FINAL_FAIL
```

---

### Test C — true unexpected worker exception still retryable

例如：

```text
Runtime adapter raises RuntimeError("boom")
```

必须继续：

```text
UNEXPECTED_WORKER_FAILURE
→ RETRY
```

这样证明：

```text
不是把所有失败都改成 final
```

---

### Test D — known transient infrastructure error keeps stable code

如果当前 Worker 有明确：

```text
RESEARCH_RUN_STORE_UNAVAILABLE
```

应证明不会错误映射成：

```text
UNEXPECTED_WORKER_FAILURE
```

同时 retry behavior 与 policy 一致。

---

# 7. C2 — Shutdown / Drain Must Have an Explicit Claim Barrier

## 7.1 当前需要验证的问题

审计：

```text
OnlyApplicationStopController
OnlyResearchWorkerService.run_forever
OnlyResearchWorkerService.run_once
```

确认是否存在：

```text
outer loop checks external stop = False
→ signal arrives
→ external stop = True
→ already entered run_once()
→ housekeeping
→ claim_once()
```

如果存在，必须修。

---

## 7.2 设计目标

建立唯一明确的：

```text
Claim Admission Barrier
```

注意：

这不是新 authority。

真正 authority 仍然是：

```text
ApplicationStopController
→ process stop request authority

ResearchWorkerService
→ claim-loop lifecycle owner

PostgreSQL Execution Store
→ actual claim/Attempt authority
```

Barrier 只负责：

```text
在调用 claim transaction 之前
重新观察已有 stop authority
```

---

## 7.3 正确时序

目标：

```text
Loop iteration
    ↓
expire stale attempt
    ↓
cancellation reconciliation
    ↓
observe stop request
    ├── stop requested
    │      ↓
    │   mark draining
    │      ↓
    │   DO NOT claim
    │
    └── no stop
           ↓
       claim_next()
```

为什么可以让 expire/reconcile 在 stop 后仍运行？

因为它们是：

```text
forward recovery / cleanup of durable operational truth
```

不是：

```text
new semantic workload admission
```

但是如果当前设计认为 stop 后连 housekeeping 也不应继续，则必须根据已有 ADR/Runbook 选择唯一语义。

不要凭直觉。

---

## 7.4 Linearization Rule 必须写清楚

推荐正式合同：

```text
If a stop request is observed before the claim transaction begins,
the Worker MUST NOT start a new claim.

If the claim transaction already began before stop observation,
that claim is treated as in-flight and is drained normally.
```

这个定义：

- 可实现；
- 可测试；
- 不要求不可能的“signal 到达瞬间原子停止所有代码”。

---

## 7.5 Draining presence

确认：

```text
stop request observed
→ worker presence draining_since
```

是否及时更新。

理想语义：

```text
进入 no-new-claim 状态
与
presence 标记 draining
```

应属于同一个 lifecycle transition。

不要出现：

```text
Worker 已决定退出
但 presence 仍长期宣称 READY
```

但要注意：

Presence 仍然只是 diagnostics。

禁止让：

```text
presence.draining_since
```

进入：

```text
claim correctness
lease correctness
completion fencing
```

Presence 永远不能成为第二 execution ownership authority。

---

## 7.6 C2 必须新增 deterministic interleaving test

不能只写：

```python
service.stop()
assert service.run_once() is None
```

必须测试真实 race。

例如 test double：

```text
expire_once()
→ allowed

reconcile_once()
→ trigger external stop = True

claim_once()
→ MUST NOT be called
```

断言：

```text
claim_count == 0
draining transition observed
```

再加：

### Already claimed case

```text
claim transaction already returns claim
→ external stop then becomes true
→ current claim still executes/drains
→ no second claim
```

如果当前 service 一次只处理一个 claim，则按真实结构设计。

---

# 8. C3 — PostgreSQL Operational I/O Must Be Truly Bounded

## 8.1 先审计，不要直接加 timeout

列出所有 runtime operational PostgreSQL paths：

```text
Run load
Run command transition
claim
heartbeat
expiry
finalization
cancellation reconciliation
presence announce
presence heartbeat
presence draining
operations snapshot
readiness
```

分别标记：

```text
connect timeout
statement timeout
lock timeout
transaction timeout
```

来源：

```text
Repository enforced
or
DSN optional
or
none
```

---

## 8.2 重点检查 background non-daemon thread

至少：

```text
Attempt heartbeat thread
Worker presence thread
```

回答：

```text
如果 psycopg.connect() 卡住，多久返回？
如果 SQL 卡住，多久返回？
如果 lock wait 卡住，多久返回？
join timeout 后 thread 仍活着怎么办？
```

如果答案依赖：

```text
OS 默认 TCP timeout
deployment accidentally adds connect_timeout
```

则不属于可复现的 Repository contract。

---

## 8.3 设计原则

必须区分两类 PostgreSQL workload：

### A. Runtime Control Plane

要求：

```text
short
bounded
fail-fast/fail-closed
```

包括：

```text
claim
heartbeat
finalization
presence
readiness
operator snapshot
```

### B. Explicit Operator Database Work

可能允许更长时间：

```text
migration
backup
restore
validation
```

不能为了 Runtime Worker 的 timeout，把：

```text
pg_dump
migration
restore-test
```

也粗暴限制到几秒。

---

## 8.4 不要引入第二 DSN authority

禁止：

```text
ONLYALPHA_WORKER_POSTGRES_DSN
ONLYALPHA_HEARTBEAT_POSTGRES_DSN
ONLYALPHA_PRESENCE_POSTGRES_DSN
```

如果只是 timeout 不同，不应该复制连接身份。

应该基于同一 DSN：

```text
base PostgreSQL identity
+
explicit operational connection options
```

---

## 8.5 推荐最小设计方向

如果当前工程没有合适抽象，可以设计一个很薄的：

```text
Operational PostgreSQL connection/session options
```

它只表达：

```text
connect_timeout
statement_timeout
必要时 lock_timeout
```

不要变成：

```text
DatabaseManager
PostgresSessionManager
ConnectionPoolPlatform
Generic Persistence Framework
```

如果 psycopg 支持在连接参数 / options 中直接表达：

```text
connect_timeout=...
options='-c statement_timeout=...'
```

优先使用最薄实现。

---

## 8.6 Timeout 必须与 lease policy 有数学关系

不能随便写：

```text
5 秒，因为看起来合理
```

至少要验证：

```text
heartbeat operation worst-case timeout
<
heartbeat interval or
<
remaining lease safety budget
```

目标是：

```text
DB operation timeout
→ Worker 能在 lease 仍有明确安全含义时
判断 ownership uncertainty
```

不要让：

```text
heartbeat call itself能卡超过 lease_duration
```

---

## 8.7 Lock timeout

只对真正可能等待 lock 的 runtime control transaction 判断是否需要。

不要无脑全局加：

```text
lock_timeout=1s
```

因为：

```text
正常短事务 contention
```

和：

```text
dead / pathological lock wait
```

不是一回事。

需要根据：

```text
claim
finalize
reconcile
```

当前 SQL 锁语义决定。

---

## 8.8 Statement timeout failure semantics

数据库 timeout 必须进入：

```text
StoreUnavailable / ownership uncertainty
```

不能：

```text
statement timeout
→ semantic failure
```

Heartbeat timeout：

```text
ownership uncertain
→ Worker MUST NOT operationally finalize
```

这必须保持 ADR 0090 的 fencing semantics。

---

## 8.9 C3 测试要求

至少选择可靠、低脆弱性的真实 PostgreSQL integration tests：

### Test A — statement timeout is effective

例如：

```text
SELECT pg_sleep(...)
```

证明：

```text
Repository configured timeout
→ bounded failure
```

不要依赖 wall-clock 极精确数值。

使用：

```text
明显大于 timeout 的 pg_sleep
+
合理宽松上界
```

---

### Test B — heartbeat DB timeout becomes ownership uncertainty

证明：

```text
DB operational call timeout
→ Worker outcome OWNERSHIP_LOST / equivalent
→ no finalization
```

---

### Test C — shutdown cannot remain indefinitely blocked by background DB I/O

设计可重复测试。

不要写依赖真实网络 blackhole 的 flaky CI。

可以：

- 使用 PostgreSQL `pg_sleep`;
- 使用明确 timeout；
- 或测试 adapter injected blocking call 的边界。

目标是证明 Repository contract，而不是模拟所有网络故障。

---

# 9. C4 — Worker Exit Code Must Match Existing Application Lifecycle Contract

## 9.1 当前需要验证

检查：

```text
OnlyApplicationStopController.exit_code
```

已有语义是否为：

```text
normal = 0
SIGINT = 130
SIGTERM = 143
KeyboardInterrupt = 130
```

再检查：

```text
OnlyEngineApplicationRunner
```

是否：

```python
return controller.exit_code
```

最后检查 Research Worker main 是否固定：

```python
return 0
```

---

## 9.2 正确目标

同一个：

```text
OnlyApplicationStopController
```

不应该被两个 application executable 解释成两套 exit-code contract。

如果 StopController 已经是正式 authority：

```text
Research Worker
→ use controller.exit_code
```

而不是复制/重新计算。

---

## 9.3 不要影响 Run state

必须继续：

```text
SIGTERM
!=
Run FAILED
```

Exit code 是：

```text
process lifecycle fact
```

不是：

```text
Research semantic outcome
```

---

## 9.4 测试

至少：

```text
normal stop path → 0
SIGINT/request_stop → 130
SIGTERM/request_stop → 143
```

如果 Worker main 难以直接做 signal integration test，可以在 application boundary 测试。

不要写真实 `os.kill()` 导致 flaky test，除非 current test framework 已有稳定模式。

---

# 10. Presence Failure Semantics — 必须审计，但不要误改

审计：

```text
OnlyResearchWorkerPresenceReporter.start()
heartbeat()
draining()
```

确认：

```text
presence 写失败
```

是否会：

```text
阻止 Worker claim
```

必须区分：

### Startup readiness fact

如果 P8.5 当前正式设计要求：

```text
Worker startup
→ PostgreSQL writable / operational composition valid
```

那么首次 presence announce 失败可能只是更早暴露：

```text
DB 不可用
```

不一定是 bug。

### Runtime diagnostic failure

Worker 已运行后：

```text
presence heartbeat failure
```

不应该成为：

```text
Attempt ownership loss
```

因为 Presence != Lease。

原则：

```text
Attempt heartbeat failure
→ ownership uncertainty

Presence heartbeat failure
→ diagnostics degraded only
```

不要因为“让 presence 更可靠”把它升级成 execution authority。

如果当前已经正确，只记录，不修改。

---

# 11. Plugin Discovery Coupling — 本次明确不是主修复项

当前已知风险：

```text
Research Worker
→ only_default_engine_services()
→ discovers DataSource / Broker / BrokerFee /
   MarketProduct / Calculation plugin groups
```

因此：

```text
unrelated Trading plugin startup failure
→ may block Research Worker startup
```

这是真实 coupling。

但它当前属于：

```text
availability / fault-isolation issue
```

不是：

```text
semantic authority violation
```

因为 Research Runtime 仍然：

```text
不创建 Trading authorities
不走 Broker
不走 Account
不走 Order
```

---

## 11.1 本次禁止顺手创建

禁止：

```text
only_research_engine_services()
ResearchPluginManager
ResearchRegistryManager
SelectiveDiscoveryFramework
WorkerCapabilityRouter
PluginHotReloadManager
```

除非重新审计发现：

```text
没有这些就无法完成 C1-C4 correctness fix
```

正常情况下不成立。

---

## 11.2 未来正确方向

如果 P8.6 E2E 实际证明 plugin coupling 阻碍部署：

设计应是：

```text
One composition mechanism
+
explicit capability scope
```

而不是：

```text
default composition
+
research composition
+
api composition
```

三套平行 truth。

本任务只允许：

```text
记录风险
```

不允许大规模重构 Plugin Framework。

---

# 12. RESEARCH Backend Provider Lifecycle Contract

Post-Closure 后：

```text
Worker process
→ one EngineServices
→ one CalculationRegistry
→ provider objects may be process-lived
```

所以必须审计当前官方：

```text
Indicator Research backend
Factor Research backend
Target Research backend
Predicate backend
```

确认：

```text
per-execution mutable state
```

是否只在：

```text
execute() local variables
```

中存在。

---

## 12.1 如果内置 provider 都是 stateless

则本次不要改生产 backend architecture。

可以仅：

1. 在正式 ADR / architecture wording 中补充合同；
2. 增加一个最小 conformance test。

正式合同建议：

```text
A RESEARCH Calculation backend provider may be reused for the
lifetime of a Worker process.

execute(definition, inputs) MUST be deterministic from the
declared semantic inputs and MUST NOT depend on mutable state
left by previous executions.

Per-execution mutable state MUST be local to execute() or to
objects created exclusively for that execution.
```

---

## 12.2 禁止提前设计 backend factory

不要为了理论上的第三方 stateful backend 添加：

```text
BackendFactory
BackendSession
ProviderLifecycleManager
CalculationBackendPool
```

只有未来出现真实 stateful backend requirement 时再设计。

---

# 13. Calculation Registry Freeze — 本次非目标

当前 Registry 可能仍有：

```python
register(...)
```

这不代表 production composition 运行期真的动态变化。

如果现有 Architecture Gate 已保证：

```text
claim path cannot rediscover/register composition
```

则本次不要新增：

```text
registry.freeze()
FrozenRegistry
RegistrySnapshot
CompositionVersionStore
```

除非发现真实运行时 mutation path。

第一性原理：

```text
Do not solve a hypothetical capability
with a new framework.
```

---

# 14. 绝对禁止的实现

本任务严禁：

```text
新增 PostgreSQL migration
新增 Run state
新增 Attempt state
新增 retry table
新增 recovery queue
新增 Worker registry platform
新增 semantic progress table
新增 mutable Research checkpoint
新增 shutdown state table
新增 Composition Store
新增 plugin fingerprint 到 semantic identity
新增 provider class/module/package identity 到 Calculation fingerprint
新增第二 Scheduler
新增第二 Recovery Manager
新增 Worker semantic executor 绕过 OnlyEngine
复用一个 mutable OnlyEngine 处理多个 Run
复制 only_default_engine_services() 形成 Research 专用平行 root
全局捕获异常然后一律 retry
为了测试通过扩大 allowlist / ignore path
```

特别禁止：

```text
P8.6 顺便开始做
```

本任务只做 closure。

---

# 15. 生产修改的预期范围

优先限制在：

```text
src/onlyalpha/research/execution/worker.py
src/onlyalpha/research/worker_main.py
src/onlyalpha/research/execution/policy.py   # only if proven necessary
src/onlyalpha/persistence/postgres/...       # bounded I/O minimal boundary
src/onlyalpha/persistence/postgres/config.py # only if this is correct owner
src/onlyalpha/research/operations/presence.py
```

以及：

```text
focused tests
architecture tests if needed
operations docs
closure report
```

不要因为方便移动大量代码。

---

# 16. 测试哲学

每个 test 必须证明：

```text
architecture invariant
or
behavioral invariant
```

而不是：

```text
实现细节刚好长这样
```

---

## 16.1 C1 tests prove failure classification

测试的是：

```text
deterministic known failure
→ no retry
```

不是：

```text
某个 private helper 被调用一次
```

---

## 16.2 C2 tests prove temporal semantics

测试的是：

```text
stop observed before claim
→ no claim
```

不是：

```text
stop flag 最终是 True
```

---

## 16.3 C3 tests prove bounded I/O contract

测试的是：

```text
runtime PostgreSQL operation
→ repository-defined upper bound
```

不是：

```text
某字符串包含 connect_timeout=5
```

如果可能，必须有真实 PostgreSQL behavior test。

---

## 16.4 C4 tests prove lifecycle consistency

测试：

```text
same StopController
→ same signal exit semantics
```

---

# 17. Architecture Tests 必须保持

重新运行并确保没有削弱：

```text
Worker semantics only through OnlyEngine

No direct Job executor
No direct Statistics executor
No direct Result assembler
No direct Artifact materializer

Scheduler remains semantic-store blind
PostgreSQL execution adapter remains semantic-store blind

Presence remains diagnostics-only
Diagnostics remain read-only

Startup does not migrate
Migration remains explicit operator authority

One Worker startup composition
No per-claim plugin rediscovery
Fresh Engine per claim
```

---

# 18. PostgreSQL Authority 必须保持

以下不能改变：

```text
Claim:
ORDER BY queued_at ASC, run_id ASC

Attempt:
max one ACTIVE per Run

Heartbeat:
exact Attempt ID
+
exact Worker ID
+
ACTIVE
+
valid lease

Finalization:
exact Attempt ID
+
exact Worker ID
+
ACTIVE
+
valid lease

Expired Attempt:
never revived

Retry:
Attempt layer only

Terminal Run:
never reopened
```

任何 timeout 改动不得破坏这些条件。

---

# 19. Recovery 必须保持

继续：

```text
semantic commits
→ verified Result/Artifact
→ fenced operational finalization
```

并继续：

```text
crash after semantic commit
→ Run may remain RUNNING
→ lease expiry
→ fresh Attempt
→ verified deterministic reuse
→ finalize exact same semantics
```

禁止：

```text
timeout
→ delete partial semantic files
timeout
→ reset Run
timeout
→ reopen terminal Run
```

---

# 20. P8.5 Recovery Pair Contract 不允许被本次破坏

正式恢复不变量：

```text
PostgreSQL consistent backup @ Tdb
→ immutable USER_DATA_ROOT snapshot @ Tfs

Tfs >= Tdb
```

必须满足：

```text
DB-referenced semantic objects
⊆
restored immutable semantic objects
```

本任务不创建第二 backup authority。

---

# 21. 推荐实现顺序

严格按下面顺序：

```text
Step 1
Re-audit current HEAD

Step 2
Reproduce C1 deterministic failure retry bug

Step 3
Fix C1 with minimal stable error mapping

Step 4
Add C1 focused tests

Step 5
Reproduce C2 stop→claim interleaving

Step 6
Add explicit claim barrier

Step 7
Align draining presence timing if needed

Step 8
Align Worker exit code with StopController

Step 9
Audit PostgreSQL runtime I/O timeout behavior

Step 10
Design minimal bounded operational DB policy

Step 11
Implement only the narrowest necessary timeout boundary

Step 12
Add real PostgreSQL bounded-I/O tests

Step 13
Audit provider lifecycle / statelessness

Step 14
Only if needed, add contract wording + conformance test

Step 15
Run focused lanes

Step 16
Run full Architecture Gate

Step 17
Write closure report
```

---

# 22. 推荐验证命令

具体命令以当前 repository scripts 为准。

至少：

```bash
uv run python scripts/test_suite.py research-execution
uv run python scripts/test_suite.py research-run
uv run python scripts/test_suite.py research-postgres
uv run python scripts/test_suite.py research-runtime
```

如果 lane 名在当前 HEAD 不存在，使用当前 repo 对应 lane。

必须：

```bash
uv run python -m pytest tests/architecture -q
```

以及：

```bash
uv run mypy src/onlyalpha
uv run ruff check src tests packages scripts
uv run ruff format --check src tests packages scripts
git diff --check
```

如修改 API/public schema 才运行：

```bash
scripts/export_research_openapi.py check
web static/build
```

不要为了“看起来全面”运行完全无关、耗时巨大的任务。

遵循项目既有 quality lane。

---

# 23. 必须新增的最小 Test Matrix

最终至少证明：

| Scenario | Expected |
|---|---|
| execution-time Specification type/version resolution failure | FINAL_FAIL, no retry |
| admission evidence mismatch | deterministic final fail |
| unknown truly unexpected exception | retry according to policy |
| transient Run Store unavailable | stable transient code / retry |
| external stop observed before claim | claim not called |
| stop arrives after claim already began | current claim drains, no next claim |
| draining Worker presence | not reported ready |
| SIGTERM Worker exit | existing application exit semantics |
| SIGINT Worker exit | existing application exit semantics |
| operational SQL exceeds timeout | bounded failure |
| heartbeat DB timeout | ownership uncertain, no finalization |
| timeout/failure does not create semantic state | PASS |
| same Worker services reused | PASS |
| fresh Engine per claim | PASS |
| architecture suite | 100% PASS |

---

# 24. Failure Classification Table

在 report 中最终给出真实表格。

至少覆盖：

```text
Failure
Classification
Retry?
Run phase/code
Why
```

示例结构：

| Failure | Class | Retry | Stable mapping |
|---|---|---:|---|
| Calculation type missing at execution re-resolve | Deterministic semantic mismatch | NO | EXECUTION_SEMANTIC_DRIFT or exact current contract |
| Admission fingerprint mismatch | Deterministic semantic drift | NO | EXECUTION_SEMANTIC_DRIFT |
| Dataset corrupt | Deterministic authority failure | NO | DATASET_VERIFICATION_FAILED |
| PostgreSQL heartbeat unavailable | Ownership uncertainty | no local finalization; recovery via lease | operational |
| Unexpected RuntimeError without known taxonomy | Unknown operational failure | policy-controlled | UNEXPECTED_WORKER_FAILURE |
| Lease expired | Transient ownership recovery | bounded retry | LEASE_EXPIRED |

不要直接照抄示例，必须基于 current HEAD。

---

# 25. Shutdown State Machine 必须在文档中明确

最终文档至少表达：

```text
RUNNING/IDLE
    ↓ stop request observed
DRAINING
    ↓
no new claim
    ↓
if ACTIVE claim:
    keep heartbeat
    finish at safe boundaries
    or ownership lost
    ↓
STOPPED
```

注意：

```text
DRAINING
```

可以是 process lifecycle notion。

不代表：

```text
新增 Run state
新增 Attempt state
新增 DB authority
```

---

# 26. 不要错误地把 signal 当 semantic cancellation

必须继续：

```text
SIGTERM Worker
!=
Cancel Run
```

当前 ACTIVE Run：

```text
可以继续完成
```

如果进程最终被强杀：

```text
heartbeat stops
→ lease expiry
→ deterministic recovery
```

不要：

```text
SIGTERM
→ CANCEL_REQUESTED
```

也不要：

```text
SIGTERM
→ FAILED
```

---

# 27. Error Detail 必须稳定且 secret-safe

新增或调整 failure mapping 时：

禁止把：

```text
DSN
password
token
full raw exception
local filesystem secret path
```

直接放入：

```text
Run failure_detail
structured operator event
public API
```

保留：

```text
stable phase
stable machine-readable code
bounded diagnostic detail
```

---

# 28. 不要污染 Semantic Identity

本任务绝对不能把：

```text
Worker version
plugin package version
Python class name
provider module path
process ID
hostname
exit code
timeout values
```

放进：

```text
Calculation fingerprint
Candidate fingerprint
Specification fingerprint
Result fingerprint
Artifact logical identity
```

这些属于：

```text
deployment / operational provenance
```

不是：

```text
Research semantic identity
```

---

# 29. Selective Plugin Discovery 的处理方式

最终 report 必须保留这条风险，但不要假装已经修：

```text
Default Engine composition currently discovers plugin groups
not required by Research execution.

An unrelated Trading-only plugin discovery failure may therefore
prevent Research API/Worker startup.

This is an availability/fault-isolation coupling, not a semantic
authority violation.
```

如果本任务没有真实证据要求修改：

```text
selective discovery
```

就保持非目标。

---

# 30. Hot Reload 明确非目标

当前正确的 determinism 更接近：

```text
process startup
→ compose once
→ stable process lifetime composition
```

而不是：

```text
runtime hot reload plugins
```

因此本任务不实现：

```text
hot reload
dynamic backend replacement
runtime registry mutation
```

未来若需要：

```text
restart process
```

优先于不透明动态替换。

---

# 31. Heterogeneous Worker Routing 明确非目标

当前不要设计：

```text
GPU Worker
CPU Worker
Vendor Plugin Worker
Capability Match Scheduler
```

这只有未来：

```text
不同 Worker 拥有不同 execution capability
```

成为明确产品需求时才设计。

P8 仍是：

```text
single-host / small-team
```

优先保持简单。

---

# 32. Definition of Done

只有以下全部成立，本任务才能 PASS。

## Correctness

```text
[ ] deterministic Specification re-resolution failure 不再 retry
[ ] known stable errors 不再无意义坍缩为 UNEXPECTED_WORKER_FAILURE
[ ] true unknown failure 仍按 policy bounded retry
```

## Shutdown

```text
[ ] stop observed before claim → no claim
[ ] active claim drains safely
[ ] heartbeat keeps ownership while draining
[ ] draining presence 不宣称 READY
[ ] signal 不修改 Run semantic state
[ ] Worker exit code 使用 existing StopController contract
```

## PostgreSQL operational I/O

```text
[ ] runtime operational DB calls 有明确 Repository-owned timeout contract
[ ] background heartbeat/presence 不依赖无限 OS timeout
[ ] DB timeout → operational uncertainty/fail closed
[ ] no timeout path bypasses fencing
```

## Architecture

```text
[ ] PostgreSQL remains sole operational mutable authority
[ ] immutable semantic Stores remain sole semantic authority
[ ] Worker still executes only through OnlyEngine
[ ] one Worker process still has one EngineServices composition
[ ] each claim still gets fresh Engine
[ ] no second retry/lifecycle/plugin authority introduced
```

## Verification

```text
[ ] focused behavior tests PASS
[ ] research-execution PASS
[ ] research-run PASS
[ ] research-postgres PASS
[ ] relevant runtime lane PASS
[ ] full architecture suite 100% PASS
[ ] mypy PASS
[ ] ruff PASS
[ ] format PASS
[ ] git diff --check PASS
```

---

# 33. Closure Report

新增一个 concise report，例如：

```text
docs/reports/p8_5_pre_p8_6_operational_semantics_closure.md
```

最终文件名以当前 repository naming convention 为准。

必须包含：

```text
Baseline SHA
Final Working Tree / Final SHA
Problems Reproduced
Root Causes
Minimal Production Changes
Authority Review
Failure Classification Matrix
Shutdown Linearization Contract
PostgreSQL Timeout Contract
Tests
Architecture Gate
Remaining Risks
Verdict
```

---

# 34. Report 中必须明确 Remaining Risks

至少重新评估：

```text
1. Research still discovers unrelated Trading plugin groups?
2. RESEARCH provider process-lifetime stateless contract now documented/tested?
3. Registry remains mutable by API but no production runtime mutation path?
4. Restore-pair exact semantic validation still requires P8.6 real E2E?
5. Remote exact-SHA CI / Final-SHA certification still not complete?
```

不要为了让 report 好看写：

```text
No remaining risks.
```

除非真的有证据。

---

# 35. 本任务完成后的项目状态

即使本任务全部 PASS：

```text
P8
仍然 IN_PROGRESS
```

下一正式阶段才是：

```text
P8.6 — P8 Product Closure & Final Certification
```

本任务不能：

```text
标记 P8 DONE
标记 P8 CERTIFIED
创建 Final-SHA certification ACCEPTED
```

P8.6 仍必须完成真实 vertical：

```text
PostgreSQL
→ API
→ Browser authoring
→ exact Dataset
→ exact Specification
→ durable QUEUED
→ Worker claim
→ OnlyEngine
→ OnlyResearchRuntime
→ semantic Result/Artifact
→ fenced COMPLETED
→ Browser Scientific Viewer
→ restart
→ Worker failure/recovery
→ coherent DB+immutable restore
→ Phase Gate
→ freeze exact Final SHA
→ Final-SHA Certification
```

---

# 36. Codex 最终输出格式

完成任务后，不要只说：

```text
Done
```

必须输出：

```text
Current HEAD:
Final HEAD / Working Tree:

Issues reproduced:
1.
2.
3.
4.

Root causes:

Production changes:

Why no new authority was introduced:

Failure classification changes:

Shutdown linearization rule:

PostgreSQL operational timeout contract:

Tests added:

Verification:
- research-execution:
- research-run:
- research-postgres:
- runtime:
- architecture:
- mypy:
- ruff:
- format:
- git diff --check:

Remaining risks:

P8 status:
P8.6 readiness:
```

---

# 37. 最后的工程原则

本任务最重要的不是“让测试通过”。

而是让系统满足：

```text
Same durable facts
+
Same semantic composition
+
Same explicit policy

→ Same operational decision
→ Same retry decision
→ Same execution semantics
→ Same recovery result
```

必须坚持：

```text
One fact
→ One authority

One lifecycle decision
→ One owner

One semantic failure
→ One stable classification

One claim
→ One explicit linearization boundary

One process composition
→ One stable object graph

One semantic input
→ Reproducible semantic output
```

不要：

```text
用 retry 掩盖确定性错误
用 sleep 掩盖时序 race
用 join(timeout) 假装 I/O bounded
用第二套 composition 修第一套 composition
用 provider implementation metadata 污染 semantic identity
用 Manager/Store/Coordinator 掩盖缺少明确 owner 的设计问题
```

最终实现应该让代码比修改前：

```text
更少歧义
更少隐含假设
更少平行权威
更容易证明
更容易恢复
更容易复现
```

如果某个改动不能解释：

```text
它关闭了哪一个真实不变量缺口？
```

就不要做。

---

# Final Target

本任务最终要证明：

```text
Deterministic semantic mismatch
→ deterministic final failure
→ no meaningless retry

Stop request observed
→ explicit draining
→ no new claim

Active claim
→ heartbeat
→ fenced safe completion

Operational PostgreSQL I/O
→ explicit bounded behavior
→ fail closed

Process signal
→ one existing lifecycle authority
→ deterministic exit semantics
```

最终形成：

```text
Correctness
+
Uniqueness
+
Determinism
+
Reproducibility
+
Operational Boundedness
```

然后再进入：

```text
P8.6 Product Closure & Final Certification
```
