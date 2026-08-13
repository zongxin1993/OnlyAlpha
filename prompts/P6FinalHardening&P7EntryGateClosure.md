# OnlyAlpha — P6 Final Hardening & P7 Entry Gate Closure

Repository:
https://github.com/zongxin1993/OnlyAlpha

你现在负责 OnlyAlpha 的 P6 最终工程收口。

本任务不是开始实现 P7，也不是增加新的交易产品功能，而是在正式进入 P7 Vectorized Research Runtime 前，对 P0–P6 已经形成的 Trading 基础设施做最后一次完整的 correctness、lifecycle、certification、recovery、long-running boundedness 和 maintainability 收口。

最终目标：

P6 Final Hardening
→ P6 正式达到 ACCEPTED / CERTIFIED
→ P7 Readiness = YES

如果证据不足，则不得为了“完成任务”强行把 P6 标记为 ACCEPTED。

==================================================
1. 工程基本原则
==================================================

OnlyAlpha 是一个面向个人与小型团队的模块化量化交易工程。

核心目标是在：

- 工程结构清晰
- 运行结果确定
- 状态可恢复
- 权威状态唯一
- 生命周期失败可收敛
- 长期可维护

的前提下，为：

- RESEARCH
- BACKTEST
- SIM
- LIVE

四类 Runtime 提供统一的基础设施。

本项目工程优先级：

正确性
>
架构一致性
>
可验证性
>
可恢复性
>
可维护性
>
性能
>
自动化程度

禁止为了更快完成编码而牺牲：

- correctness
- deterministic behavior
- single authority
- recovery semantics
- public contract
- durability
- architecture boundary

==================================================
2. Repository Is the Source of Truth
==================================================

任何实现开始前，必须重新完整检查当前仓库。

不得假定本 Prompt 中描述的历史 SHA、历史报告或之前讨论仍然是当前事实。

Current Repository HEAD 是唯一事实来源。

首先执行：

git status
git branch --show-current
git rev-parse HEAD
git log -10 --oneline

记录：

- 当前 branch
- 当前 HEAD
- working tree 是否 clean
- 最近主要提交

然后重新阅读至少：

README.md

docs/roadmap.md
docs/architecture.md
docs/architecture_principles.md
docs/runtime.md
docs/engineering/quality-system.md

docs/adr/
docs/reports/

.github/workflows/

scripts/test_suite.py

src/onlyalpha/engine/

src/onlyalpha/runtime/
src/onlyalpha/runtime/trading/
src/onlyalpha/runtime/backtest/
src/onlyalpha/runtime/streaming/
src/onlyalpha/runtime/sim/
src/onlyalpha/runtime/research/
src/onlyalpha/runtime/live/

tests/architecture/
tests/contract/
tests/integration/
tests/scenario/
tests/recovery/

以及所有：

- Engine lifecycle
- SIM
- Streaming
- checkpoint
- restart
- recovery
- Runtime State Lease
- plugin rollback
- quality/certification

相关代码和测试。

历史上曾观察到一个 P6 final candidate：

910bce3eb08cd9728a0226e6ee4dce4438de278f

但这只是历史参考。

如果当前 HEAD 已变化，必须完全以当前 HEAD 重新判断，不得机械执行本 Prompt 中已经失效的假设。

==================================================
3. 当前目标 Runtime Architecture
==================================================

OnlyAlpha active Runtime taxonomy 必须是：

RESEARCH
BACKTEST
SIM
LIVE

历史 Runtime：

PAPER
SHADOW

不得重新成为 active Runtime product。

不得增加：

- PAPER alias
- SHADOW alias
- deprecated Runtime spelling
- compatibility Runtime wrapper

目标 Trading Runtime 结构保持：

Backtest -------------------+
                            |
SIM -> Streaming -----------+-> OnlyTradingRuntimeFacade
                            |
future LIVE -> Streaming ---+
                            |
                            v
                     OnlyTradingKernel
                            |
                     Trading Authorities

其中：

Backtest / SIM / future LIVE

共享正式 Trading Semantic Core。

Runtime 之间的差异应主要存在于：

- Clock
- MarketData Driver
- Broker Adapter
- Lifecycle Driver
- product-level composition

以下经济语义不得按 Runtime Type 分叉：

- Strategy
- Market Rule
- Risk
- Reservation
- Order
- Execution
- Transaction
- Position
- Allocation
- Account
- Strategy Ledger
- Fee
- Settlement

==================================================
4. P7 边界
==================================================

P7 是：

Vectorized Research Runtime

目标 pipeline：

Historical Dataset
→ Vectorized Indicator
→ Factor / Feature
→ Parameter Sweep
→ Statistics
→ Research Result
→ Research Artifact
→ Query / API
→ Web Visualization

但本任务禁止实现 P7。

禁止新增：

- Research Job implementation
- Research Plan implementation
- Research Dataset pipeline
- Vectorized execution engine
- Factor runtime
- Parameter Sweep
- Statistics engine
- Research Result implementation
- Research Artifact implementation
- Research API
- Research Web UI

本任务只能使 P7 “可以安全开始”。

==================================================
5. 核心架构不变量
==================================================

所有实现都必须保护以下不变量。

-------------------------
INV-01 — Single Authority
-------------------------

禁止创建第二套 authoritative state。

不得因为重构而复制：

- Runtime state
- Cluster state
- Order state
- Execution state
- Position state
- Account state
- Reservation state
- Settlement state
- Transaction state
- Checkpoint state
- Continuity state
- Broker state
- Result authority

Coordinator 可以协调 Authority。

Coordinator 不能成为第二 Authority。

-------------------------
INV-02 — Trading Kernel Runtime Neutrality
-------------------------

runtime/trading 不得依赖：

runtime/backtest
runtime/streaming
runtime/sim
runtime/live

Trading Kernel 不得根据：

OnlyRuntimeMode
BACKTEST
SIM
LIVE
RESEARCH

执行经济语义分支。

Strategy-facing context 不得暴露 Runtime Product Identity 供 Strategy 决策。

-------------------------
INV-03 — SIM Cannot Reach Real Broker
-------------------------

SIM 必须继续是：

Realtime MarketData
+ LiveClock
+ Virtual Broker
+ Full Trading Kernel

SIM 不允许获得向 Real Broker 提交真实订单的路径。

-------------------------
INV-04 — Failure Produces Known State
-------------------------

任何关键生命周期失败后必须收敛到：

- recoverable known state
- FAILED
- STOPPED
- CLOSED

中的明确状态。

禁止：

部分 Runtime 已经运行
+
部分 Runtime 启动失败
+
Engine 自身状态不明确

这种 partially-started world。

-------------------------
INV-05 — Durable Compatibility
-------------------------

本任务原则上不得修改：

- checkpoint schema
- persistence schema
- participant identity
- transaction identity
- runtime identity derivation
- durable transaction semantics
- recovery canonical identity

除非当前仓库已经存在明确批准的 contract change。

如果确实必须改变：

必须单独说明：

- 为什么
- compatibility impact
- migration policy
- tests
- ADR

默认应采取 behavior-preserving hardening。

-------------------------
INV-06 — No Fake Rollback
-------------------------

已经发生并提交的经济事实不能被“rollback”。

Engine startup rollback 的含义只能是：

compensating cleanup
+
deterministic lifecycle convergence

不是撤销已 committed trading facts。

==================================================
6. Workstream A — P6 Certification Authority Closure
==================================================

首先重新检查当前：

docs/reports/p6_runtime_architecture_final_certification.md
docs/roadmap.md
docs/engineering/quality-system.md
.github/workflows/

重点确认当前是否仍存在以下 certification self-reference 问题：

假设被认证 commit A 中：

certification report 写：

CI 尚未运行
P6 CONDITIONALLY_ACCEPTED

commit A push 后：

CI PASS

然后为了把 report 改为：

P6 ACCEPTED

必须生成 commit B。

但 commit B 又没有 same-SHA remote CI evidence。

这样会形成：

A
→ CI pass
→ 修改 report
→ B
→ CI pending
→ 修改 report
→ C
→ ...

如果当前工程仍然存在这一设计，必须解决。

最终 certification model 应明确分成：

Certification Subject
→ Certification Workflow
→ Certification Evidence
→ Certification Verdict

其中：

subject_sha

是不可变的被认证对象。

最终 certification verdict 是对 subject_sha 的外部证明。

不得要求 subject_sha 本身提前保存尚未发生的未来 CI 结果。

优先使用当前 GitHub 基础设施可以自然支持的简单方案，例如：

- GitHub Actions workflow result
- workflow artifact
- certification manifest
- GitHub Release
- Git tag
- GitHub check
- attestation

不要引入不必要的独立基础设施。

必须明确区分：

IMPLEMENTED

表示代码实现已经完成。

VERIFIED

表示规定测试和质量门禁已有实际证据。

CERTIFIED / ACCEPTED

表示正式 certification policy 对指定 subject SHA 给出最终接受结论。

这三个状态不能混用。

==================================================
7. Workstream B — Final-SHA Certification Quality Gate
==================================================

重新阅读：

.github/workflows/quality.yml
以及所有相关 workflow。

重新阅读：

scripts/test_suite.py

确认 Development CI 和 Final Certification 是否真正满足项目要求。

尤其检查：

branch coverage 是否只在 pull_request 上执行。

如果：

coverage job 只在 PR 上运行

而：

master push 可以 coverage skipped

则普通 CI 可以接受，但不能作为严格的 Final-SHA Certification Evidence。

建立清楚的两个概念：

Development Quality Gate

和：

Certification Quality Gate

Development Gate：

用于普通 PR / 开发反馈。

可以优化速度。

Certification Gate：

用于正式阶段认证。

必须优化 evidence completeness。

Certification Gate 必须对同一个：

subject_sha

运行所有 mandatory gates。

根据当前仓库真实 lane 名称调整，但原则至少包括：

Static:

- ruff check
- ruff format --check
- mypy core
- package mypy
- import contracts
- version sync

Build:

- all-package build

Tests:

- core-full
- branch coverage
- recovery
- sim-recovery
- A-share conformance
- MiniQMT contract

Security:

- Semgrep
- CodeQL 或当前仓库正式 security gate

以及 docs/engineering/quality-system.md 当前定义的所有 P6 mandatory gates。

Certification PASS 必须意味着：

所有 required gate
对同一个 subject SHA
真实 PASS。

禁止：

required gate 被 skipped
但 certification 仍 PASS。

除非某个 gate 本身明确属于：

optional / environment-dependent

并且 quality policy 正式记录了这种情况。

不要为了 certification 机械重复完全等价的 suite。

目标是 evidence 完整，而不是制造更多 CI job。

==================================================
8. Workstream C — OnlyEngine.start() Transactional Lifecycle
==================================================

完整检查：

src/onlyalpha/engine/engine.py

特别比较：

initialize()

和：

start()

initialize() 如果已经具备 staged construction + reverse cleanup，则保留该设计思想。

重点解决：

Engine.start()

是否存在：

Runtime A.start() PASS
Runtime B.start() FAIL

后：

Runtime A 仍然运行

的问题。

Engine start 必须满足：

ALL STARTED

或者：

KNOWN FAILED STATE

禁止 partial-start world。

至少设计并实现以下 failure scenario：

Runtime A
start PASS

Runtime B
start FAIL

失败后必须保证：

- Runtime A 不再继续 RUNNING
- Runtime A worker 不再存活
- Runtime A subscription 被释放
- Runtime A owned resources 被正确关闭
- Runtime B 状态明确
- Runtime sessions 状态一致
- Cluster sessions 状态一致
- Cluster handles 状态一致
- Engine 最终进入 FAILED
- Runtime State Lease 无泄漏
- Broker resource 无泄漏
- DataSource resource 无泄漏
- EventBus/Clock 等 owned resource 无泄漏
- Infrastructure reference 无泄漏

如果：

Runtime B.start()

失败，同时：

Runtime A cleanup

也失败：

必须：

1. 保留 original startup failure 作为主失败；
2. 记录 cleanup failure；
3. 继续尝试剩余 cleanup；
4. 不因第一个 cleanup error 停止清理；
5. 最终 Engine 进入 FAILED。

可以使用：

Exception.add_note()

或项目当前一致的 failure aggregation mechanism。

不要静默吞掉 cleanup failure。

不要用：

except Exception:
    pass

隐藏生命周期问题。

为此增加明确的 fault-injection tests。

测试应通过正式：

OnlyEngine

public lifecycle 触发。

不要只测试 private helper。

至少覆盖：

- first Runtime start failure
- later Runtime start failure
- previous Runtime cleanup failure
- repeated stop/close behavior
- final Engine state
- final Cluster state
- resource release

==================================================
9. Workstream D — Streaming Long-Running Boundedness
==================================================

完整检查：

src/onlyalpha/runtime/streaming/runtime.py

以及所有 Streaming：

- diagnostics
- observation
- processing history
- recovery history
- warmup history
- timer history
- checkpoint diagnostics

相关对象。

寻找所有：

append-only in-memory list
dict keyed by ever-growing identity
unbounded history

特别检查历史上曾经存在的：

_processing_results

以及类似结构。

必须明确区分：

Authoritative State

和：

Diagnostic State

Authoritative State 示例：

- checkpoint state
- transaction state
- continuity frontier
- order state
- execution state
- position state
- account state
- durable timer state

这些不能简单截断。

Diagnostic State 示例：

- recent processing results
- recent recovery failures
- recent diagnostic events
- counters
- latest observation
- latest failure
- recent health samples

这些不得无限增长。

对于 diagnostics，优先采用：

Counters
+
Current Snapshot
+
Bounded Recent History

例如：

collections.deque(maxlen=N)

或者一个非常小且职责明确的：

OnlyStreamingDiagnostics

component。

不要为了这个问题引入：

- 新数据库
- 新 telemetry platform
- 新 distributed service

如果完整历史真的需要保留：

应该交给现有 durable log / observation sink / external diagnostics mechanism，

而不是永久保存在 Runtime 内存中。

增加测试证明：

大量 streaming processing 后：

diagnostic history size <= bound

同时：

- counters 正确增长
- latest/current snapshot 正确
- normal trading behavior 不变
- checkpoint behavior 不变
- recovery behavior 不变
- authoritative state 不被裁剪

==================================================
10. Workstream E — Recovery Test Determinism
==================================================

完整搜索：

sleep(
time.sleep
wait(...)
timeout=
3
3.0

以及所有 recovery / checkpoint / restart test。

重点检查：

- sim-recovery
- checkpoint
- new-process restart
- repeated restart
- streaming recovery
- continuity repair
- worker stop
- state lease
- recovery finalization

不要简单删除所有 timeout。

必须区分：

Semantic Condition

与：

Test Safety Deadline

正确测试应等待：

- checkpoint sequence advanced
- phase == LIVE
- phase == FAILED
- recovery generation advanced
- worker stopped
- subscription removed
- lease released
- continuity frontier reached
- expected transaction appeared
- expected durable state persisted

而不是：

sleep(1)
assert ...

或者：

3 秒内没有完成
=
semantic failure

除非这个时间本身是明确的 product SLA。

允许保留一个较宽松的 deadline：

只是为了防止测试永久挂起。

例如概念上：

wait_until(
    semantic_condition,
    timeout=reasonable_safety_deadline,
)

如果当前测试框架已有：

event
condition variable
latch
eventually helper

优先复用。

不要重复发明等待框架。

目标：

当 sim-recovery lane 红灯时，

应尽量意味着：

真实 semantic regression

而不是：

CI runner 当时较慢。

==================================================
11. Workstream F — Streaming Runtime Structural Hardening
==================================================

重新分析：

src/onlyalpha/runtime/streaming/runtime.py

不要预设一定要拆。

先检查当前文件：

- size
- responsibilities
- state ownership
- lifecycle complexity
- recovery complexity
- checkpoint coordination
- bootstrap coordination
- diagnostics coordination

如果 OnlyStreamingRuntime 已经同时承担过多 coordination responsibility，则进行 behavior-preserving decomposition。

核心原则：

拆 responsibility

不拆 authority。

OnlyStreamingRuntime 应继续作为：

product-neutral long-lived streaming Runtime orchestration root。

可以根据当前代码真实 seam 考虑：

- Lifecycle Coordinator
- Bootstrap Coordinator
- Continuity / Recovery Coordinator
- Checkpoint Coordinator
- Diagnostics

但这些名称只是设计方向。

不得为了匹配 Prompt 人工拆出大量空壳类。

要求：

Coordinator 只协调。

Coordinator 不复制：

- continuity state
- checkpoint state
- timer authority
- trading state
- transaction authority

例如：

RecoveryCoordinator

可以调用现有：

ContinuityTracker
RecoveryLoader
SemanticLane
Checkpoint service

但不能维护第二份 canonical recovery truth。

本重构禁止：

- 重写整个 Streaming Runtime
- 改变 normal path causality
- 改变 recovery sequence
- 改变 checkpoint identity
- 改变 durable schema
- 改变 SIM public lifecycle
- 创造 SIM-specific economic semantics

重构前先建立 characterization tests。

然后逐步移动 responsibility。

每一阶段运行 targeted regression。

==================================================
12. Workstream G — SIM Factory Composition Hardening
==================================================

重新完整检查：

src/onlyalpha/runtime/sim/factory.py

如果当前 Factory 已经同时承担：

- config validation
- capability validation
- DataSource resolution
- Broker resolution
- Market Product resolution
- Account validation
- persistence validation
- state-root resolution
- Runtime State Lease
- Clock creation
- EventBus creation
- inbound queues
- plugin resource creation
- Market Rule construction
- Broker fee contract construction
- Runtime construction
- Runtime registration
- rollback

则应进行适度结构化。

目标 architecture shape：

Config
↓
Validation
↓
Resolved Composition Plan
↓
Resource Acquisition
↓
Runtime Composition
↓
Ownership Transfer

关键是把：

pure validation / resolution

与：

side-effectful resource acquisition

分开。

可以考虑建立类似：

OnlySimCompositionPlan

这样的 immutable resolved plan。

但必须先看当前代码是否值得。

不要为了 Prompt 强行建立复杂 class hierarchy。

Resolved Composition Plan 可以包含例如：

- resolved DataSource plugin/factory
- resolved Broker plugin/factory
- resolved Market Product
- resolved Account
- resolved Persistence config
- resolved state root
- resolved Subscription
- validated capability set
- fee contract inputs
- Runtime assembly information

但不得提前创建有副作用的 resource。

必须明确 ownership transfer contract：

Ownership transfer 之前：

Factory / Resource Builder 负责 rollback。

Ownership transfer 之后：

Runtime / Engine lifecycle 负责 close。

禁止：

resource 没人负责关闭

或者：

两个 owner 都认为自己应该 close。

必须增加 failure tests：

Acquire A PASS
Acquire B PASS
Acquire C FAIL

最终：

reverse cleanup B
reverse cleanup A

且无泄漏。

这个结构最终应能让未来：

OnlyLiveRuntimeFactory

复用相同 composition discipline，

而不是复制一个更大的 SIM Factory。

但本任务禁止实现 Live。

==================================================
13. Workstream H — Internal Migration Residue
==================================================

重新搜索以下类型的残留：

Legacy
Deprecated
compatibility
old spelling
acceptance_
streaming_subscription
RuntimeServices

以及：

PAPER
SHADOW

在 active source 中的使用。

需要区分：

1. 真实 active compatibility residue
2. internal migration naming residue
3. historical documentation / prompt
4. legitimate unrelated compatibility alias

不要机械删除所有包含：

legacy
deprecated

的内容。

如果存在仅用于内部迁移、已经没有实际价值的 alias，例如：

旧 internal type alias
旧 internal property spelling

可以在不破坏 public API 和 persistence compatibility 的前提下清理。

但优先级低于：

- correctness
- lifecycle
- certification
- recovery
- boundedness

不要为了清理命名制造大范围 diff。

==================================================
14. Workstream I — Historical Prompt Boundary
==================================================

检查：

prompts/

以及旧 P6/PAPER/SHADOW 历史资料。

历史 Prompt 可以保留。

不要大规模删除工程历史。

但是必须避免 AI Agent 或后续开发者把历史 Prompt 当成 current architecture source of truth。

优先考虑添加：

prompts/README.md

或者现有 index 中明确说明：

Prompts are historical implementation records.

They are not authoritative current-state architecture documentation.

Current source of truth is:

- current source code
- current tests
- current architecture docs
- accepted ADRs
- current roadmap
- current certification evidence

如果没有实际混淆风险，也不要为了形式移动大量 Prompt 文件。

==================================================
15. Workstream J — Repository Truth Reconciliation
==================================================

完成代码、测试和 CI 设计以后，对所有 authoritative documentation 做一次 reconciliation。

至少检查：

README.md

docs/roadmap.md
docs/architecture.md
docs/architecture_principles.md
docs/runtime.md
docs/engineering/quality-system.md

相关 ADR

docs/reports/p6_runtime_architecture_final_certification.md

必须明确区分：

Target Architecture

Current Implementation

Certified Scope

Known Limitations

Future Work

例如 Runtime 状态应准确表达：

RESEARCH
目标 Runtime
如果尚未实现则明确 unsupported / future

BACKTEST
当前实现状态和 certified scope

SIM
当前实现状态和 certified scope

LIVE
目标 Runtime
如果尚未实现则明确 unsupported / future

禁止把：

“已经设计”

写成：

“已经实现”。

禁止把：

“已经实现”

直接写成：

“已经认证”。

Certification verdict 必须来自实际 evidence。

==================================================
16. 当前 P6 已知设计范围不得扩大
==================================================

P6 Final Hardening 不得顺手扩展为：

- 24h production soak platform
- Real Broker reconciliation
- durable outbound real broker command
- multi-account
- multi-broker
- multi-market-data-source
- futures
- margin product expansion
- crypto
- new A-share product scope
- distributed execution
- distributed backtest
- production Live operations

这些属于：

P8
P9
或以后阶段。

如果发现相关需求：

记录为 Future Work。

不要实现。

==================================================
17. P8 / P9 边界必须继续保持
==================================================

P8 未来负责：

Durable Broker Outbound Command and Synchronization

包括：

- durable outbound Broker command
- submission idempotency
- retry policy
- ACK / Reject / Unknown
- Broker query
- Account synchronization
- Order synchronization
- Trade synchronization
- Position synchronization
- local canonical state vs Broker evidence reconciliation
- reconnect gap recovery
- command/fact/checkpoint/recovery identity

P9 未来负责：

Live Runtime Foundation

包括：

Realtime MarketData
+ LiveClock
+ Real Broker Adapter
+ Durable Broker Command
+ Broker Facts
+ Synchronization
+ Reconciliation
+ Long-running checkpoint/recovery
+ Production Operations

本任务禁止提前实现 P8/P9。

==================================================
18. 测试要求
==================================================

所有修改必须有对应测试。

不要只依赖现有测试碰巧覆盖。

至少确保以下 contract 有明确测试证据。

-------------------------
Architecture
-------------------------

验证：

- Trading Kernel remains Runtime-neutral
- Strategy Context remains Runtime-neutral
- economic packages 不按 Runtime Type 分叉
- SIM cannot use Real Broker
- PAPER / SHADOW active runtime spelling fail closed
- no duplicate trading authority

-------------------------
Engine Lifecycle
-------------------------

验证：

- multi-runtime start happy path
- first runtime start failure
- later runtime start failure
- partial-start reverse cleanup
- cleanup error aggregation
- Engine final FAILED
- session state convergence
- Cluster state convergence
- resource release
- repeated stop/close safety

-------------------------
Streaming
-------------------------

验证：

- normal realtime path unchanged
- no same-bar unexpected fill semantics unchanged
- existing accepted/trade ordering unchanged
- processing cutoff after stop unchanged
- gap recovery unchanged
- reconnect recovery unchanged
- recovery admission suppression unchanged
- bounded diagnostics

-------------------------
Durable Recovery
-------------------------

验证：

- checkpoint
- checkpoint verification
- restart
- repeated restart
- new Runtime instance recovery
- canonical-world comparison
- corrupted durable state fail closed
- Runtime State Lease
- timer recovery
- transaction tail recovery

-------------------------
Recovery Determinism
-------------------------

验证测试不依赖无业务意义的短 sleep。

应基于 semantic condition。

-------------------------
Factory
-------------------------

验证：

- validation failure before resource acquisition
- acquisition failure reverse cleanup
- ownership transfer
- no double-close
- no leaked plugin resource
- no leaked state lease

-------------------------
Certification
-------------------------

如果可合理实现，增加结构化检查确认：

- certification subject SHA 有明确 identity
- required certification gates 不能 silent skip
- certification verdict 依赖 mandatory gates

不要写极度脆弱的：

assert "coverage" in yaml_text

这类文本测试。

优先：

- Python config validator
- reusable certification script
- structured manifest validation

如果当前工程没有必要，也可以让 workflow 自身保持简单。

==================================================
19. Refactoring Discipline
==================================================

所有结构性修改必须：

1. 先阅读和理解现有行为；
2. 建立 characterization test；
3. 小步移动责任；
4. 每步运行 targeted tests；
5. 最后运行 full regression。

避免一个 commit 同时进行：

- 架构重构
- schema change
- public API change
- semantic change
- compatibility change

如果不可避免：

必须明确拆分并解释。

不要大规模机械重命名。

不要顺手整理与任务无关的代码。

保持 diff focused。

==================================================
20. No False Green
==================================================

严禁为了得到绿色 CI 而：

- 删除失败测试
- skip 新失败测试
- 扩大 skip 范围
- 降低 coverage threshold
- 删除 architecture guard
- 弱化 Semgrep rule
- 吞异常
- silent fallback
- 将 failure 改成 warning
- 增加 sleep 让测试“看起来稳定”
- 修改 expected value 适配错误行为
- 隐藏 resource leak
- 伪造 remote PASS
- 伪造 security evidence

如果存在无法安全解决的问题：

保持失败。

报告真实 blocker。

正确性优先于任务完成。

==================================================
21. Local Validation
==================================================

所有代码修改完成后，基于当前仓库真实命令运行完整验证。

首先：

uv sync --frozen --all-packages --all-groups

Static：

uv run ruff check src tests examples packages scripts

uv run ruff format --check src tests examples packages scripts

uv run mypy src/onlyalpha

然后运行当前仓库定义的所有 package mypy。

运行：

uv run lint-imports

运行：

uv run python scripts/version_sync.py check

Tests：

使用当前 scripts/test_suite.py 定义的 canonical lane。

至少运行：

uv run python scripts/test_suite.py core-full

uv run python scripts/test_suite.py recovery

uv run python scripts/test_suite.py sim-recovery

uv run python scripts/test_suite.py ashare

uv run python scripts/test_suite.py miniqmt-contract

如果 lane 名称已经改变：

使用当前真实 canonical lane。

Branch coverage：

uv run python scripts/test_suite.py core-full --coverage

Build：

uv build --all-packages

如果当前 release lane 已经是完整 certification local suite，也应运行：

uv run python scripts/test_suite.py release

前提是该命令是当前仓库真实定义且不会调用不可用外部环境。

==================================================
22. Remote Validation
==================================================

本地无法真实运行的：

- GitHub Actions
- CodeQL
- remote Semgrep
- environment-specific external check

不得伪造 PASS。

本地报告只能写：

LOCAL PASS
REMOTE REQUIRED

正式 P6 certification 必须由：

final subject SHA

上的 remote certification workflow 给出真实结果。

如果你能够访问 GitHub workflow 状态：

必须检查实际 run。

如果不能：

明确记录 remote pending。

不得预判。

==================================================
23. P6 Final Entry Gate
==================================================

P7 只有在以下条件全部满足时才能正式 OPEN。

-------------------------
Certification
-------------------------

[ ] Certification subject SHA 模型明确

[ ] 不存在 self-referential certification cycle

[ ] Certification verdict 对 immutable subject SHA 生效

[ ] mandatory gates 对同一 subject SHA 运行

[ ] branch coverage 在 certification 中真实执行

[ ] security evidence 有明确 authority

-------------------------
Lifecycle
-------------------------

[ ] Engine start partial failure 可确定收敛

[ ] 已启动 Runtime 会正确停止/关闭

[ ] cleanup failure 不阻止其余 cleanup

[ ] original startup failure 保留

[ ] Engine 最终 FAILED

[ ] Runtime session state 一致

[ ] Cluster session state 一致

[ ] Runtime State Lease 无泄漏

[ ] Plugin resource 无泄漏

-------------------------
Streaming
-------------------------

[ ] diagnostics bounded

[ ] authoritative state 未被错误截断

[ ] realtime normal path 无 semantic regression

[ ] continuity 无 regression

[ ] gap/reconnect 无 regression

[ ] durable recovery 无 regression

-------------------------
Recovery
-------------------------

[ ] tests 使用 semantic condition

[ ] 不依赖无意义短 fixed timing

[ ] sim-recovery stable

-------------------------
Architecture
-------------------------

[ ] Trading Kernel Runtime-neutral

[ ] Strategy Context Runtime-neutral

[ ] no duplicated authority

[ ] no parallel trading semantic implementation

[ ] SIM remains Virtual Broker only

[ ] PAPER / SHADOW 未重新激活

-------------------------
Quality
-------------------------

[ ] static PASS

[ ] build PASS

[ ] core-full PASS

[ ] branch coverage PASS

[ ] recovery PASS

[ ] sim-recovery PASS

[ ] A-share PASS

[ ] MiniQMT contract PASS

[ ] Semgrep PASS where required

[ ] CodeQL/security PASS where required

-------------------------
Documentation
-------------------------

[ ] README accurate

[ ] roadmap accurate

[ ] architecture docs accurate

[ ] runtime docs accurate

[ ] quality system accurate

[ ] certification docs accurate

[ ] known limitations explicit

[ ] P7 scope clear but not implemented

==================================================
24. P6 Final Decision
==================================================

最终只能给以下三种状态之一：

ACCEPTED

CONDITIONALLY_ACCEPTED

REJECTED

规则：

ACCEPTED

表示所有 mandatory P7 Entry Gate 均具有真实证据。

CONDITIONALLY_ACCEPTED

表示核心实现正确，但仍缺少明确、有限、不会破坏现有架构的认证条件，例如 remote final-SHA evidence 尚未返回。

REJECTED

表示存在 correctness、lifecycle、durability、architecture 或 mandatory gate failure。

不要预设最终一定是 ACCEPTED。

==================================================
25. Git / Commit Discipline
==================================================

先检查 working tree。

不要覆盖用户已有未提交修改。

如果发现 unrelated dirty changes：

不得擅自删除或 reset。

只修改本任务需要的文件。

推荐按逻辑拆分 commit，例如：

1. P6 certification authority / quality workflow
2. Engine lifecycle atomicity
3. Streaming bounded diagnostics / recovery test hardening
4. behavior-preserving structural cleanup
5. documentation reconciliation

但应根据实际改动规模决定。

不要为了“好看”拆出大量无价值 commit。

如果当前工作环境要求只交付 working tree diff，则遵循当前环境约束。

==================================================
26. Final Report Format
==================================================

完成后必须输出：

# P6 Final Hardening Report

## 1. Repository State

列出：

- branch
- initial HEAD
- final HEAD / working tree
- clean / dirty
- 当前 P6 status before change

## 2. Reassessment Findings

重新评估后列出真实发现。

至少分为：

### Certification

### Engine Lifecycle

### Streaming Long-Running

### Recovery Determinism

### Runtime Maintainability

### Documentation / Repository Truth

不要机械复制 Prompt。

如果某个历史问题已经被当前 HEAD 修复：

明确写：

ALREADY RESOLVED

不要重复修改。

## 3. Architecture Decisions

说明最终采用的：

- certification authority model
- certification subject identity
- Engine start failure convergence model
- resource ownership model
- diagnostics retention model
- Streaming decomposition model
- SIM factory composition model

如果某项经评估不值得修改：

说明为什么保留现状。

## 4. Changes Made

逐文件列出。

格式类似：

path/to/file.py
- change
- reason
- affected invariant

## 5. Behavior Preserved

明确说明没有改变：

- Trading Kernel semantics
- Strategy Runtime neutrality
- order lifecycle
- execution lifecycle
- transaction ordering
- position semantics
- account semantics
- fee semantics
- settlement semantics
- checkpoint schema
- persistence schema
- recovery identity

只列真实保持不变的内容。

## 6. Tests Added / Modified

逐项说明：

测试名称
→ 证明什么 contract

不要只写：

“added tests”。

## 7. Local Validation Evidence

列出实际运行命令和真实结果。

例如：

ruff: PASS
mypy core: PASS
package mypy: PASS
lint-imports: PASS
core-full: XXXX passed
recovery: XXXX passed
sim-recovery: XXXX passed
ashare: XXXX passed
miniqmt-contract: XXXX passed
coverage: XX.XX%
build: PASS

必须填写真实值。

不得猜测。

## 8. Remote Certification Evidence

列出：

subject SHA

workflow

required jobs

actual status

如果尚不可用：

写：

REMOTE EVIDENCE PENDING

不要假定 PASS。

## 9. Remaining Known Limitations

只列当前真实限制。

例如仍可能包括：

- Research Runtime not implemented
- Live Runtime not implemented
- Real Broker reconciliation not implemented
- production soak not certified
- broader provider matrix not certified

但必须基于当前仓库重新判断。

## 10. P6 Final Decision

只允许：

ACCEPTED

CONDITIONALLY_ACCEPTED

REJECTED

并说明依据。

## 11. P7 Readiness

明确写：

P7 Readiness = YES

或者：

P7 Readiness = NO

如果 NO：

只列真实 blocker。

## 12. Recommended Next Step

如果：

P6 = ACCEPTED

则下一阶段只能建议：

P7.0 — Research Domain Contract & Deterministic Identity

不要在本任务中直接实现。

如果：

P6 != ACCEPTED

则给出最小 blocker closure list。

==================================================
27. P7 之后的设计预留
==================================================

如果 P6 最终 ACCEPTED，后续 P7 应遵循：

Research != Trading Runtime clone

Research Job / Plan 不得伪装成 Trading Cluster。

Research 不应为了结构对称创建：

- Account
- Position
- Order
- Broker
- Reservation
- Trading Transaction Manager

未来 P7 的核心应围绕：

- ResearchJobId
- DatasetIdentity
- CalculationIdentity
- ResearchPlan
- ResearchJob
- ResearchStatus
- ResearchResultIdentity
- ArtifactIdentity

以及：

deterministic dataset identity

deterministic calculation identity

immutable result

immutable artifact

read-only Query/API/Web boundary

这些只是下一阶段设计约束。

本任务不要实现。

==================================================
28. Execution Rule
==================================================

整个任务必须遵循以下执行顺序：

Step 1
重新读取当前 HEAD。

Step 2
重新判断本 Prompt 中每个历史问题是否仍存在。

Step 3
输出内部实施计划。

Step 4
先解决 P0 correctness/certification/lifecycle 问题。

Step 5
再解决 boundedness 和 test determinism。

Step 6
只有在风险低且 characterization tests 完整时，才进行 structural refactor。

Step 7
运行 targeted tests。

Step 8
运行完整 local certification suite。

Step 9
更新 authoritative docs。

Step 10
检查 final diff。

Step 11
获取或记录 remote same-SHA evidence。

Step 12
根据证据给出 P6 Final Decision。

==================================================
29. 最终原则
==================================================

本任务不是为了让代码更“漂亮”。

本任务的真正目标是：

把 P0–P6 已经实现的 Trading infrastructure

从：

功能上基本完成

提升到：

correct
deterministic
recoverable
bounded
lifecycle-safe
certifiable
maintainable

的稳定工程基线。

只有在这个基线真正成立后，

P7 才应该开始。

如果发现当前 Repository 已经解决了某项问题：

不要重复实现。

如果发现新的更严重问题：

优先处理新的 correctness blocker。

Repository HEAD、测试和实际证据始终高于本 Prompt 的历史假设。

现在开始。