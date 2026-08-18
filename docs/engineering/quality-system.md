# OnlyAlpha Engineering Quality System

> 本文定义 OnlyAlpha 的工程质量、架构约束、代码强度、验证机制与演进规则。  
> 目标不是增加流程负担，而是让正确设计成为默认路径，让错误设计更难进入主干。

---

## 1. 目标

OnlyAlpha 的长期目标不是“功能可以运行”，而是建立一个：

- 可长期演进；
- 可验证；
- 可回放；
- 可恢复；
- 回测 / 模拟 / 实盘语义尽可能一致；
- 核心状态具有唯一权威来源；
- 架构边界清晰；
- 失败模式可解释；
- AI Agent 与人工开发都不容易破坏核心设计；

的量化交易基础设施。

工程质量优先级：

1. 正确性；
2. 架构一致性；
3. 可验证性；
4. 可恢复性；
5. 可维护性；
6. 性能；
7. 自动化程度。

任何自动化都不能以削弱前五项为代价。

---

## 2. 核心原则

Calculation Foundation 使用 `python scripts/test_suite.py calculation` 作为 canonical lane；它覆盖 Core definition/schema/
DAG/registry/discovery/architecture tests 和 official Indicator package characterization。`calculation --coverage` 独立统计
官方 Indicator plugin，Core `core-full --coverage` 的既有 82% gate 保持不变。Core、Indicator plugin 与 Factor plugin
均须进入 mypy；P7.5 official Factor provider 的 RESEARCH-only registrations 同样进入 discovery、类型和构建门禁。

Research Calculation 使用 `python scripts/test_suite.py research-calculation` 作为 canonical lane；它覆盖 exact backend/source
contracts、verified Dataset admission、instrument/DAG determinism、Result logical identity、immutable Store admission/atomicity、
idempotency/deterministic conflict、manifest/partition corruption、fresh-process verified reload、architecture firewall 和官方
Indicator Trading↔Research characterization。`research-calculation --coverage` 对 Core Research Calculation package 执行独立
branch coverage gate；P7.3 沿用该 mandatory lane，Final-SHA Certification 已消费该 lane 与 coverage gate。

Research Job 使用 `python scripts/test_suite.py research-job` 作为独立 canonical application lane；它覆盖 exact resolved Plan、
verified reuse-or-execute、corruption fail-closed、re-entry recovery、same-job concurrency、fresh-process reuse、显式 Outcome 与
Research/Trading architecture firewall。`research-job --coverage` 独立统计 `onlyalpha.research.job`，并进入 PR、master、release
与 Final-SHA Certification mandatory gates。

Research Factor 使用 `python scripts/test_suite.py research-factor` 作为 semantic/execution closure lane；它覆盖 official
Momentum/Percentile backends、canonical Factor Graph、semantic-node-first TIME_SERIES/CROSS_SECTION execution、physical
order/partition/fresh-process determinism、旧 Indicator identity regression、Calculation Result/Research Job integration 与
Research/Trading architecture firewall。`research-factor --coverage` 对 P7.5 execution module 与 official Factor plugin 执行
100% line/branch coverage gate，并进入 PR、master、release 与 Final-SHA Certification mandatory gates。

Research Sweep 使用 `python scripts/test_suite.py research-sweep` 作为 canonical composition lane；它覆盖 backend-neutral Definition
re-materialization、Template/schema、typed candidate/dimension ordering、Cartesian planning、topological Graph materialization、identity
propagation、fresh-process/hash-seed determinism、JobExecutor-only sequential execution、reuse/partial re-entry/corruption/fail-fast 和
Research/Trading firewall。`research-sweep --coverage` 独立统计 `onlyalpha.research.sweep`，要求至少 90% line 与 85% branch，并进入 PR、
master、release 与未来 P7 Final-SHA Certification mandatory gates。

Research Specification 使用 `python scripts/test_suite.py research-specification` 作为 canonical compiler lane；它覆盖 strict
schema/serialization/request identity、exact type/backend admission、candidate/Statistics lineage、Specification architecture boundary，以及
manual P7 Workload 与 Specification-resolved Workload 的完整 Runtime semantic equivalence。`research-specification --coverage` 只统计
`onlyalpha.research.specification`，要求 100% line 与 100% branch；Sweep Materializer 继续由 `research-sweep` coverage 拥有。该 lane 进入
PR、master、release 与 Final-SHA Certification mandatory gates。

Finite Research Runtime 使用 `python scripts/test_suite.py research-runtime` 作为 canonical product-orchestration lane；它覆盖 Runtime
product/capability boundary、完整 workload closure、Research-only Engine lifecycle、Dataset→Job/Sweep→Statistics→Result→Artifact 产品链、
fresh-process deterministic re-entry、corruption fail-closed 与 Trading authority firewall。`research-runtime --coverage` 对新 Runtime product
package 执行至少 95% line / 90% branch 门禁，并进入 PR、master、release 与 Final-SHA Certification mandatory gates。

Research Execution 使用 `python scripts/test_suite.py research-execution` 作为 canonical operational application lane；它覆盖 Attempt/
Worker identity、lease/retry policy、finite Scheduler、周期 heartbeat、fenced Worker outcome、cooperative cancellation、graceful stop、
Engine-only Runtime entry 与 execution architecture firewall。`research-execution --coverage` 只统计
`onlyalpha.research.execution`，要求至少 95% line / 85% branch。真实 PostgreSQL migration、row-lock claim、lease CAS、stale fencing、
concurrency 与 Artifact-commit crash recovery 继续由串行 `research-postgres` lane 拥有；两条 lane 均进入 release、普通 CI 与
Final-SHA mandatory matrix。

### 2.1 Repository Is the Source of Truth

每个阶段开始前必须重新读取当前仓库状态。

历史方案、旧 Prompt、旧讨论只能作为背景，不得覆盖当前代码、测试、文档与 ADR 所表达的事实。

### 2.2 Single Authority

任何核心状态只能存在一个 authoritative owner。

禁止为了方便新增第二套：

- Runtime state；
- Position state；
- Order state；
- Account state；
- Execution state；
- Result state；
- Checkpoint state。

派生视图必须从权威状态投影，不得重新维护平行状态。

### 2.3 Backtest / Sim / Live Trading Semantic Equivalence

Domain、Strategy、Risk、Execution 的核心语义应尽可能共享。

环境差异应限制在 adapter / infrastructure boundary 中。

禁止通过复制业务逻辑形成独立的：

- backtest implementation；
- live implementation；
- sim implementation。

### 2.4 Determinism First

对于给定：

- 数据快照；
- 配置；
- 代码版本；
- 日历版本；
- 随机种子；
- 策略版本；

系统应尽量产生可重复结果。

无法确定性的部分必须显式记录。

### 2.5 Failure Must Produce a Known State

失败不应等价于“状态未知”。

任何关键失败都应进入：

- 可恢复状态；
- 明确终止状态；
- 明确待确认状态；

之一。

### 2.6 Prefer Constraints Over Instructions

能通过以下机制自动约束的问题：

- 类型系统；
- architecture tests；
- schema validation；
- static analysis；
- scenario tests；
- replay；
- CI；

不应长期依赖 Prompt 或开发者记忆。

### 2.7 Quality Acceptance Model

OnlyAlpha 的工程验证只定义三个正式质量层级：

1. Task Gate
2. Phase Gate
3. Certification Gate

三个层级回答不同的问题，不得相互混用。

Task Gate 回答：

> 本次明确范围内的修改及其工程影响是否正确？

Phase Gate 回答：

> 本阶段所有 Task 组合后，OnlyAlpha 整体功能、架构与关键不变量是否仍然正确？

Certification Gate 回答：

> 某个不可变 Final SHA 是否已经通过正式、可追溯的工程认证？

不得因为某个 Task 需要额外验证而创造新的正式 Gate 层级。

Integration、coverage、security scan、build smoke、cross-platform smoke 等均是
上述 Gate 内的验证手段，不是新的完成状态。

---

### 2.8 Task Gate

普通 P7.x / P8.x / Pn.x 实现任务默认属于 Task Gate。

Task 必须在设计阶段明确：

- `TASK_BASE_SHA`；
- Goal；
- Modification Scope；
- Impact Scope；
- Required Behavior；
- Expected Acceptance Tests；
- Expansion Triggers；
- Out of Scope。

该 Task Contract 必须在实现前冻结。Implementation Block 只是工作分解，不是第四种 Gate；Prompt 或 Agent 不得建立与本文
冲突的验收层级。

Task Gate 的验证范围必须由 Impact Scope 决定，而不是由仓库总体规模决定。

当：

- 任务要求已经实现；
- 修改保持在声明的 Modification Scope 内；
- Impact Scope 内需要新增或修改的测试已经建立；
- 声明的 Acceptance Tests 全部通过；
- 必要的局部 contract / architecture / typing / package checks 通过；

即可标记：

`Task Complete`

Task Complete 表示当前修改已经获得足够的局部工程证据。

Task Complete 不表示整个 Repository 已经完成 Phase Certification。

普通 Task Gate 默认不要求：

- repository-wide pytest；
- `core-full --coverage`；
- repository-wide branch coverage；
- 全部 Research lanes；
- 全部 recovery / sim-recovery；
- 全部插件和 Market Product 测试；
- repository-wide build certification；
- Semgrep 全仓扫描；
- dependency audit；
- CodeQL；
- cross-platform distribution certification；
- Final-SHA Certification；
- 等待 GitHub 全量 CI 完成。

---

### 2.9 Impact Scope

Task Gate 不得仅根据：

- 修改了哪个文件；
- 新增了哪个 test；
- 哪个 test 名称与修改函数相同；

判断测试范围。

Impact Scope 应从实际工程依赖关系推导。

至少考虑：

1. changed symbol 的直接调用方；
2. changed symbol 的间接调用方；
3. import / module dependency；
4. Protocol / interface / model consumer；
5. runtime composition；
6. plugin / registry / Entry Point consumer；
7. persistence / serialization consumer；
8. existing regression / contract / architecture tests；
9. 已知跨模块不变量。

例如：

`test_func_b -> B -> C -> A`

即使 `test_func_b` 没有直接引用 `A`，当 `A` 的行为变化可能传播到该路径时，
`test_func_b` 仍属于候选 Impact Scope。

验证范围的目标不是执行最少数量的测试，而是：

> 用最小但充分的验证集合覆盖实际 Impact Scope。

---

### 2.10 Conservative Impact Expansion

“没有找到依赖”不得自动解释为“没有影响”。

当影响范围能够可靠确定为局部时，使用局部 Acceptance Tests。

当影响范围无法可靠确定时，应逐级扩大：

`function -> class/module -> subsystem -> existing canonical lane`

默认扩大到最近的稳定工程边界。

当高层 consumer 只消费已经由正式 contract test 保护的 immutable authority 时，反向传播到该稳定 authority boundary 后停止；
不得仅因概念链更长就继续扩到 provider 或整个 Repository。反之，底层 public authority 变化必须沿已编码的正式 consumer
dependency 扩张，Impact union 只能增加、不能缩小。

不得因为存在不确定性直接无条件升级到 repository-wide validation，
除非修改本身确实影响 repository-wide contract。

Task-level Ruff、Format、Mypy、Import Linter、version sync 与 build 同样必须按 Impact Scope 选择。未知路径和 verification
infrastructure 自改继续 fail closed 到完整本地验证；这类 Task-level firewall 不等于 Phase Gate。

如果实现过程中发现任务定义遗漏了一个明确依赖：

- 将该依赖加入 Impact Scope；
- 增加对应验证；
- 只扩大到该依赖所属的最近稳定 subsystem/lane。

不得因为发现一个额外依赖而顺手重新设计整个质量体系。

---

### 2.11 High-Risk Task Gate Expansion

以下变化虽然可能 diff 很小，但其 Impact Scope 天然可能跨模块，因此 Task Gate
必须执行相应的现有专项验证。

#### Public / Architecture Contract

包括：

- Protocol；
- ABC；
- public model；
- public Enum；
- Runtime interface；
- Core / Runtime / Plugin dependency direction。

应增加相关：

- contract tests；
- architecture tests；
- mypy；
- Import Linter；

但不自动要求 repository-wide certification。

#### State / Persistence / Recovery Contract

包括：

- state machine；
- checkpoint；
- serialization；
- persistence schema；
- resume；
- replay；
- recovery；
- idempotency semantics。

应增加对应 state / recovery regression tests，必要时执行现有：

- `recovery` lane；
- `sim-recovery` lane；

具体范围由实际 Impact Scope 决定。

#### Package / Plugin Contract

包括：

- Entry Point；
- plugin discovery；
- `pyproject.toml`；
- package metadata；
- distribution dependency；
- workspace dependency。

应增加对应：

- plugin contract tests；
- discovery tests；
- version synchronization；
- targeted package/build smoke；

但普通 package change 不自动要求完整 cross-platform certification。

---

### 2.12 Phase Gate

一个完整开发阶段，例如 P7、P8，在所有 Task Complete 后执行一次 Phase Gate。

Phase Gate 用于验证所有 Task 组合后的系统完整性。

Phase Gate 应根据当前 Repository 的正式质量工具链执行：

- repository-wide static quality；
- canonical regression lanes；
- architecture verification；
- recovery / conformance verification；
- full branch coverage；
- build verification；
- 本阶段新增功能的端到端 functional scenarios。

`--coverage` 类型的完整覆盖率验证默认属于 Phase Gate。

例如：

`uv run python scripts/test_suite.py core-full --coverage`

不属于普通 Task Gate。

Phase Gate 可以发现不同 Task 组合后产生的 integration regression。

Phase Gate 失败时：

1. 修复真实 regression；
2. 重新执行受影响验证；
3. 最终重新得到完整 Phase Gate PASS。

只有通过 Phase Gate 后，阶段才可标记：

`Phase Complete`

---

### 2.13 Certification Gate

Certification Gate 面向一个不可变 Final SHA。

它的目标不是开发反馈，而是留下正式、可追溯的版本质量证据。

Certification 应消费当前 Repository 定义的正式认证能力，包括适用的：

- static verification；
- canonical lanes；
- mandatory coverage；
- build；
- semantic guardrails；
- dependency audit；
- CodeQL；
- certification evidence。

Certification Gate 不应在每个普通 Task 后运行。

流程应为：

`Task Complete x N`
`-> Phase Gate`
`-> Phase Complete`
`-> Freeze Final SHA`
`-> Final-SHA Certification`
`-> Certified`

只有 Certification Gate 通过的 immutable SHA 才标记：

`Certified`

---

### 2.14 GitHub CI Semantics

GitHub 自动 CI 与 Task Gate 是两个不同概念。

普通 Task 在声明的 Task Gate 通过后即可标记 Task Complete，
不需要因为 GitHub CI 仍处于 pending 状态而等待。

GitHub CI 是持续质量信号，可以比 Task Gate 覆盖更大的范围。

规则如下：

`CI pending != Task blocked`

但：

`known real CI regression = must fix`

如果 GitHub CI 已经明确发现由当前 HEAD 引入的真实 regression，
不得长期继续叠加新的工程债务。

该 regression 最迟必须在 Phase Complete 前解决。

GitHub CI 自动运行哪些 jobs，不直接决定单 Task 的 Acceptance Boundary。

---

### 2.15 Coverage Placement

完整 branch coverage 是系统级质量证明，不是普通局部开发反馈。

因此所有：

`scripts/test_suite.py <lane> --coverage`

默认属于：

- Phase Gate；或
- Certification Gate。

普通 Task 可以新增、维护和执行测试，
但无需在每个 Task 后重新计算 repository-wide coverage。

只有以下情况可以在 Task Gate 中显式使用 coverage：

- Task 本身修改 coverage infrastructure；
- Task 的 acceptance objective 本身就是 coverage closure；
- 无法通过更小的验证可靠证明某个明确的局部路径。

即使如此，也应优先执行最小适用 coverage scope，
而不是默认运行全部 repository coverage。

---

### 2.16 Quality Framework Stability

质量体系属于长期基础设施，不属于普通功能 Task 的可自由修改范围。

除非出现明确证据证明现有体系存在：

- false negative；
- false positive；
- 无法验证新的关键系统不变量；
- 新架构边界无法由现有机制表达；
- certification evidence 本身不可靠；

否则不得因为单次任务开发便利性修改：

- Gate 层级；
- Task Complete 定义；
- Phase Complete 定义；
- Certification 定义；
- CI architecture；
- coverage architecture；
- test layering architecture。

新增功能优先增加对应测试和现有 lane 覆盖。

不要优先增加新的 Gate、workflow 或质量框架层。

---

### 2.17 Codex Task Contract

面向 Codex 的普通实现任务应尽量在 Prompt 中明确：

`Goal`

`Modification Scope`

`Impact Scope`

`Required Behavior`

`Acceptance Tests`

`Out of Scope`

`Validation Boundary`

其中 Validation Boundary 应明确：

- 当前任务是 Task Gate 还是 Phase/Certification task；
- 哪些测试是 Task Complete 的必要证据；
- 哪些 repository-wide checks 明确不属于本次任务；
- 当发现额外真实依赖时最多扩大到哪个 subsystem/lane。

Codex 不应在任务完成阶段重新发明验收标准。

任务设计阶段应尽可能完成影响分析；
实现阶段只有在发现新的具体工程事实时才调整 Impact Scope。

这样可以减少重复 repository exploration、重复完整测试、
重复 CI 分析以及无关质量基础设施修改。

---

## 3. Architecture Invariants

建议将本节作为 OnlyAlpha 的核心架构不变量，并在工程演进中持续补充。

### INV-001 Runtime Authority

OnlyEngine / Runtime 的正式生命周期路径必须保持唯一。

禁止新建绕过正式 Runtime 的平行执行入口。

### INV-002 Strategy Isolation

Strategy 不应直接依赖具体 Broker、数据库、网络或文件系统实现。

### INV-003 Broker Boundary

订单提交、撤单、成交与 Broker 交互必须经过正式 execution / adapter boundary。

### INV-004 Domain Independence

Domain 层不得依赖：

- MiniQMT；
- MongoDB；
- 文件系统；
- 网络；
- GUI；
- 具体 Broker SDK。

### INV-005 State Ownership

Position、Account、Order、Execution 等核心状态必须有唯一 owner。

任何缓存、Artifact、Report、Projection 只能是派生结果。

### INV-006 Replay Independence

历史 replay 不得依赖 wall clock 或不可控外部状态。

### INV-007 Stable Identity

核心实体和事件应具有稳定 identity，例如：

- run_id；
- signal_id；
- order_id；
- execution_id；
- event_id；
- correlation_id。

### INV-008 Explicit Persistence Version

任何持久化数据必须具有显式 schema version 或兼容性边界。

重点包括：

- Checkpoint；
- Artifact；
- Execution Event；
- Order Event；
- Result；
- Config snapshot。

### INV-009 Traceable State Transition

资金、持仓、订单状态的变化必须可追溯到权威事件。

### INV-010 No Hidden Global State

核心业务逻辑不得隐式读取未声明的全局可变状态。

### INV-011 Idempotency Where Required

涉及：

- retry；
- reconnect；
- replay；
- recovery；
- callback duplication；

的关键操作必须明确幂等语义。

### INV-012 Ordered Lifecycle

Order / Execution 生命周期必须具有合法状态转换，非法转换应被拒绝或显式报错。

---

## 4. 分层与依赖规则

推荐逻辑依赖方向：

```text
Infrastructure / Adapters
          ↓
Application / Runtime
          ↓
Domain
```

Domain 应尽可能纯净。

建议逐步形成：

```text
onlyalpha/
├── domain/
├── application/
├── runtime/
├── strategy/
├── risk/
├── execution/
├── adapters/
│   ├── miniqmt/
│   ├── mongo/
│   └── filesystem/
└── reporting/
```

实际目录可以不同，但依赖方向必须清晰。

建议使用 architecture test / import-linter 自动阻止：

- domain -> miniqmt；
- domain -> mongo；
- strategy -> broker implementation；
- core runtime -> GUI；
- 低层模块反向依赖高层实现。

---

## 5. Contract-Driven Design

核心 API 不应只描述参数和返回值，还应描述 Contract。

每个关键 Contract 至少考虑：

### Preconditions

调用前必须满足什么。

### Postconditions

调用成功后必须保证什么。

### Invariants

调用过程中绝对不能破坏什么。

### Failure Semantics

失败意味着：

- rejected；
- timeout；
- unknown；
- retryable；
- terminal；

中的哪一种。

### Idempotency

重复调用是否安全。

### Ordering

事件和状态是否有先后约束。

### Side Effects

允许修改哪些状态、调用哪些外部系统。

### Recovery

进程中断后如何恢复。

重点模块：

- Runtime；
- Strategy；
- Risk；
- Order；
- Execution；
- Broker Adapter；
- Position；
- Account；
- Checkpoint；
- Artifact。

---

## 6. 类型与数据模型

目标：尽可能让非法状态难以表达。

优先使用：

- `dataclass(frozen=True)`；
- `Enum`；
- `Literal`；
- `Protocol`；
- `TypedDict`；
- `NewType`；
- 明确的 domain value object；
- pyright / mypy。

避免核心状态使用无约束字符串，例如：

```python
status: str
```

优先使用显式状态类型。

核心对象应避免：

- 任意动态字段；
- 模糊 Optional；
- 大量 `dict[str, Any]`；
- 隐式单位；
- 隐式时区；
- 隐式价格精度；
- 隐式 side effect。

---

## 7. ADR：Architecture Decision Record

重大设计决策必须记录 ADR。

建议目录：

```text
docs/adr/
```

命名：

```text
ADR-0001-xxx.md
ADR-0002-xxx.md
```

每份 ADR 至少包含：

```text
# Context
# Decision
# Alternatives
# Why
# Consequences
# Invariants Introduced
```

必须记录：

- 最终选择；
- 为什么这样选择；
- 为什么没有采用其它主要方案；
- 该决定引入哪些长期约束。

当架构决策发生实质变化时，应新增 ADR，而不是静默覆盖历史原因。

---

## 8. Definition of Done 与阶段粒度

任何 P6.x / P7.x 等阶段任务不得仅以“代码写完 + 测试通过”作为完成标准。

必须至少检查：

- [ ] Acceptance Criteria 全部满足
- [ ] Architecture Invariants 未被破坏
- [ ] 未新增重复 authoritative state
- [ ] 未出现不必要的平行执行路径
- [ ] 必要 unit tests 已补充
- [ ] 必要 integration / scenario tests 已补充
- [ ] 必要 replay regression 已执行
- [ ] Failure semantics 已验证
- [ ] Retry / recovery 语义已考虑
- [ ] Static analysis / type check 通过
- [ ] API 变化已记录
- [ ] Schema / persistence compatibility 已考虑
- [ ] Architecture 变化已补 ADR
- [ ] 文档与真实实现一致
- [ ] Independent Review 已完成
- [ ] 无已知 Critical / High 未处理问题

质量状态必须按工程粒度区分，不得把 implementation increment 与 major milestone 混为同一 gate：

- P7.x 等同一 Major Milestone 内的 **Implementation Increment** 只使用 `PLANNED / IMPLEMENTED / VERIFIED / BLOCKED`；
- P6、P7、P8 等 **Major Milestone** 使用 `IN_PROGRESS / CONDITIONALLY_ACCEPTED / ACCEPTED / REJECTED`。

同一 Major Milestone 内，前一个 increment 达到 `VERIFIED` 后即可进入下一个 increment。`VERIFIED` 至少要求实现完整、required
targeted tests 与 affected canonical lanes 通过、architecture invariants 通过、impact-aware local verification 通过、适用时
Layered Quality 通过、Independent Review 完成、无未解决 Critical / High，且相关文档足以解释当前实现。

只有 `ACCEPTED` 的 Major Milestone 才默认允许进入下一个 Major Milestone。因此 P7.x → 下一个 P7.x 要求前一个 increment
`VERIFIED`；P7 → P8 仍要求 P7 Final Closure 对 exact immutable SHA 完成 Final-SHA Certification 并取得 `ACCEPTED` artifact。

### 8.1 Certification Cadence

Final-SHA Certification 是 Repository 唯一正式 exact immutable SHA final certification authority，但它不要求在每个
implementation increment 后执行。默认 cadence 是 Major Milestone Final Closure；普通 increment 通过 affected verification
取得 `VERIFIED`。Release/tag、Live deployment、重大 persistence migration、Runtime/Recovery authority 重构、已知 nondeterminism
incident closure、高风险架构 baseline freeze 或长周期 milestone 中间冻结，可以显式建立 certification checkpoint。显式 checkpoint
仍必须执行完整且未裁剪的 Final-SHA mandatory gates。

### 8.2 Development Gate 与 Certification Gate

普通 `Layered Quality` 是 Development Quality Gate，用于 PR 与主干反馈；事件条件允许某些互斥 lane 被显式跳过，因此它的绿色结果不能单独证明 Final-SHA Certification。

Repository 的唯一 Final-SHA Certification Authority 是手工触发的 `Final-SHA Certification` workflow。触发者必须提供不可变的 40 字符 `subject_sha`，每个 job 都 checkout 并验证该 SHA。Static、all-package build、当前 canonical lanes（包括 `research-specification`、`research-run`、`research-execution`、`research-postgres`、`research-runtime`、`research-sweep`、`research-factor`、`research-job`、`research-calculation`、`calculation`、`research-dataset`、`core-full`、`recovery`、`sim-recovery`、`ashare`、`miniqmt-contract`）、branch coverage、Semgrep 与 CodeQL 都是 mandatory；任何 missing、skipped、cancelled 或 failure 都产生 `REJECTED`。最终 verdict 由 `scripts/certification.py` 生成结构化 workflow artifact，因而不要求被认证 commit 保存尚未发生的未来 CI 结果。

Streaming/async certification test 必须等待正式 state/revision/continuity evidence；bounded timeout 只能是统一、可解释的
deadlock watchdog。watchdog failure 必须输出 immutable diagnostics，至少覆盖 phase/revision、recovery generation/stage/plan、
Semantic Lane cutoff、worker/source、continuity frontier 与 buffered suffix。禁止用 sleep、rerun、flaky marker、lane removal 或散落的
timeout inflation 改变 verdict。

状态含义固定为：

- `IMPLEMENTED`：代码实现完成；
- `VERIFIED`：指定本地或远端门禁已有实际证据；
- `CERTIFIED / ACCEPTED`：外部 certification artifact 对同一个 immutable subject SHA 给出接受结论。

Implementation Increment 可以依据上述实际 development evidence 达到 `VERIFIED`，但不得据此声明 `CERTIFIED / ACCEPTED`。在
Major Milestone Final Closure 或显式 certification checkpoint 中，没有 exact-SHA remote artifact 时只能是
`CONDITIONALLY_ACCEPTED` 或 `REJECTED`，不得预判远端 PASS。

### 8.3 Impact-Aware Local Verification

Agent 的默认开发验证顺序是 targeted test、affected canonical lane、impact-aware local gate；increment closure 以这些实际 evidence
取得 `VERIFIED`。只有 Major Milestone Final Closure 或显式 certification checkpoint 在形成 immutable final SHA 后进入完整
Final-SHA Certification。`scripts/verify.py plan --base <sha>` 以显式 base、HEAD 和完整 dirty worktree 解析 change set，
用 typed explicit rules 产生可解释的 deterministic union。Unknown impact 必须 fail closed；verification infrastructure change 必须
执行完整 local release check/lane/build 集合，不能用新工具自证一个狭窄子集。

Impact planner 不是 test semantics authority。Canonical lane paths、marker expressions、worker strategy、coverage 和 release 顺序仍只由
`scripts/test_suite.py` 管理；planner 只能引用 lane/check identity。Local runner 顺序执行所选 gate，将完整输出和 machine-readable
manifest 保存到 `test-results/verification/<verification-id>/`，成功 console 只输出 gate summary，失败输出有界诊断和完整日志路径。
Manifest 的 authority 固定为 `LOCAL_DEVELOPMENT_VERIFICATION_ONLY`，`VERIFICATION_PASSED` 不等于 `CERTIFIED` 或 `ACCEPTED`。

Coverage 不属于默认 inner loop。Final-SHA workflow 仍完整执行 exact-SHA static、build、canonical lanes、mandatory coverage、Semgrep、
CodeQL、Web static/unit/build/E2E 和 fail-closed verdict；changed-file impact plan 永不参与该 mandatory matrix。Web evidence 使用 Node 24、
`npm ci`、strict TypeScript/ESLint/Prettier/Vitest/Playwright；它是现有 Task/Phase/Certification Gate 中的 evidence，不创建第四种 Gate。

成功的长时间运行日志默认保存在 evidence 文件中，不重复加载进 Agent context；console 与最终报告只保留 gate、exit code 和简短摘要，
仅在失败诊断时读取有界的相关日志。

---

## 9. AI / Codex 开发工作流

推荐固定流程：

```text
Architecture Review
        ↓
Execution Contract
        ↓
Implementation
        ↓
Independent Verification
        ↓
Acceptance Gate
        ↓
Repository State Refresh
```

### 9.1 Architecture Review

开始任务前：

1. 读取当前 HEAD；
2. 阅读相关架构文档；
3. 阅读相关 ADR；
4. 阅读相关源码；
5. 阅读相关测试；
6. 判断前置条件是否满足；
7. 明确 Scope / Non-goals；
8. 明确 Architecture Invariants；
9. 定义 Acceptance Criteria。

### 9.2 Execution Contract

Codex Prompt 应明确：

- Current State；
- Goal；
- Scope；
- Non-goals；
- Invariants；
- Authoritative Paths；
- Implementation Requirements；
- Forbidden Shortcuts；
- Required Tests；
- Acceptance Criteria；
- Final Report Format。

Prompt 应规定“边界和原则”，避免过度指定内部实现细节。

### 9.3 Implementation

Implementation Agent 负责：

- 阅读真实工程；
- 按 Contract 实现；
- 最小化无关修改；
- 执行必要测试；
- 汇报真实结果。

### 9.4 Independent Verification

Reviewer 不应默认实现是正确的。

Reviewer 的目标是寻找足以拒绝实现的证据。

重点检查：

- architecture invariant violation；
- hidden state；
- duplicate source of truth；
- boundary bypass；
- retry / recovery；
- edge case；
- API / schema compatibility；
- 无效测试；
- 过度抽象；
- scope creep。

### 9.5 Repository State Refresh

阶段完成后，下一阶段必须重新读取当前工程。

不得把上一阶段设计文档直接当作下一阶段 current truth。

---

## 10. 测试体系

### 10.1 Unit Test

用于验证：

- pure function；
- value object；
- state transition；
- validation；
- calculation。

### 10.2 Integration Test

验证正式组件组合与边界。

### 10.3 Golden Scenario

建立完整交易场景作为 Executable Specification。

建议覆盖：

```text
simple_buy_sell
partial_fill
cancel_after_partial_fill
reject
broker_timeout
duplicate_callback
out_of_order_event
reconnect
restart_recovery
end_of_day
```

每个场景可包含：

- market input；
- config；
- expected signals；
- expected orders；
- expected fills；
- expected positions；
- expected account；
- expected artifacts。

### 10.4 Historical Replay Corpus

逐步建立真实市场 replay 数据集，包括：

- 正常交易日；
- 极端涨跌；
- 涨跌停；
- 停牌；
- 集合竞价；
- 午休；
- 跨日；
- 数据缺失；
- 异常成交量；
- 乱序数据；
- 节假日边界；
- 除权除息等特殊情况。

### 10.5 Property-Based Testing

重点用于：

- Order state machine；
- Position；
- Account；
- PnL；
- Serialization；
- Checkpoint；
- Replay。

典型 property：

```text
filled_qty <= order_qty

FILLED => filled_qty == order_qty

equity == cash + market_value

重复处理同一幂等事件不得重复改变最终状态
```

建议使用 Hypothesis。

### 10.6 Mutation Testing

成熟阶段引入 mutation testing，检测测试是否真正能捕获逻辑错误。

重点模块：

- Risk；
- Execution；
- Position；
- PnL；
- Recovery。

### 10.7 Differential Testing

重构关键组件时，对新旧实现输入相同数据，比较：

- signals；
- orders；
- fills；
- position；
- PnL；
- events；
- artifacts。

非预期差异应为 0。

---

## 11. Failure Injection

核心系统必须主动测试失败路径。

建议逐步覆盖：

- Broker timeout；
- Broker response lost；
- duplicate callback；
- out-of-order callback；
- reconnect；
- network interruption；
- database write failure；
- checkpoint partial write；
- process crash；
- missing bar；
- malformed data；
- disk full；
- invalid schema；
- restart recovery。

验证目标：

```text
failure -> known state -> deterministic recovery / explicit terminal state
```

---

## 12. Static Analysis

建议逐步建立：

- Ruff；
- Pyright 或 Mypy；
- Import Linter；
- 必要时 Bandit。

采用渐进式策略：

```text
核心新代码：严格
历史代码：逐步收紧
```

不要为了形式上的全局严格度，制造大量与业务无关的改动。

---

## 13. Schema 与兼容性

所有持久化边界应考虑：

- schema_version；
- backward compatibility；
- migration；
- unsupported version；
- corruption detection。

尤其关注：

- Checkpoint；
- Artifact；
- Order Event；
- Execution Event；
- Runtime snapshot；
- Config snapshot。

禁止静默改变长期存储格式。

---

## 14. Observability Contract

系统必须能够回答：

- 为什么产生某个 Signal？
- 为什么 Risk 允许 / 拒绝？
- 为什么提交某个 Order？
- Broker 收到了什么？
- 为什么订单成为当前状态？
- Position 为什么是当前值？
- PnL 如何形成？
- Recovery 做了什么？

建议贯穿：

- run_id；
- strategy_id；
- signal_id；
- order_id；
- execution_id；
- broker_order_id；
- event_id；
- correlation_id。

形成完整因果链：

```text
Market
  ↓
Signal
  ↓
RiskDecision
  ↓
OrderIntent
  ↓
Order
  ↓
BrokerRequest
  ↓
Execution / Fill
  ↓
Position / Account
```

---

## 15. Performance Regression

核心路径逐步建立固定 benchmark。

建议至少包含：

- 单日；
- 单月；
- 一年；
- 多 symbol；
- 大规模 replay。

记录：

- runtime；
- peak memory；
- bars/sec；
- events/sec。

性能变化可以接受，但必须可见、可解释。

---

## 16. Complexity Budget

任何任务都应考虑新增复杂度。

Review 时关注：

- 新增 abstraction 数量；
- 新增 public API 数量；
- 新增 mutable state 数量；
- 新增 state owner 数量；
- 新增 cross-layer dependency；
- 新增长期概念数量。

原则：

> 增加功能不等于增加概念。

如果能通过删除、合并或复用现有概念实现，应优先于增加新的 Manager / Factory / Registry / Coordinator / Provider 等抽象。

---

## 17. Technical Debt Ledger

允许技术债存在，但禁止无记录技术债。

建议维护：

```text
docs/debt/
```

或：

```text
DEBT.md
```

每条至少记录：

```text
ID
Current State
Why Accepted
Risk
Removal Trigger
Must Not Become
```

技术债必须具有：

- 明确范围；
- 明确风险；
- 明确清理触发条件。

---

## 18. Review Model

建议核心任务至少经过四类 Review：

### Correctness Review

是否真正实现需求。

### Architecture Review

是否破坏架构不变量。

### Failure Review

异常、重试、恢复、重复、乱序是否正确。

### Simplification Review

是否存在：

- 不必要抽象；
- 不必要状态；
- 重复逻辑；
- 过度工程；
- 可以删除的代码。

---

## 19. 优先实施顺序

### 第一阶段：立即执行

1. Architecture Invariants；
2. Definition of Done；
3. Independent Verification Gate；
4. ADR；
5. Core Contracts；
6. Dependency Architecture Tests。

### 第二阶段：核心架构稳定后

7. Golden Scenarios；
8. Historical Replay Corpus；
9. Property-Based Testing；
10. Core Domain Strict Typing；
11. Failure Injection；
12. Schema Versioning。

### 第三阶段：工程成熟后

13. Mutation Testing；
14. Differential Testing at Scale；
15. Performance Regression Gate；
16. 完整 Observability；
17. Automated Multi-Agent Verification；
18. Control Plane Hooks。

---

## 20. 最终目标

OnlyAlpha 的工程质量不应依赖开发者或 AI Agent“记得遵守规则”。

目标是：

```text
Architecture Invariants
        +
Type System
        +
Contracts
        +
Architecture Tests
        +
Golden Scenarios
        +
Replay
        +
CI
        +
Independent Review
        =
错误设计难以进入主干
```

最终标准：

> 正确设计成为阻力最小的路径，错误设计成为难以通过工程系统的路径。
