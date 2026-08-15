# OnlyAlpha 工程质量工具链

OnlyAlpha 的质量验证按**反馈速度、影响范围和计算成本**分层。

工程目标不是让每个开发任务都重复执行完整仓库验证，而是：

* 开发阶段尽快否定错误修改；
* Task Gate 对明确的 Impact Scope 提供充分局部证据；
* Phase Gate 对阶段内所有修改组合后的系统完整性提供仓库级证据；
* Certification Gate 对不可变 Final SHA 提供正式、可追溯的认证证据。

本文主要描述：

> **OnlyAlpha 使用哪些质量工具，以及这些工具在哪些自动化层级运行。**

本文**不单独定义普通开发任务的完成条件**。

Task Gate / Phase Gate / Certification Gate 的正式验收语义、Impact Scope 原则和任务完成定义，以：

`docs/engineering/quality-system.md`

为权威来源。

GitHub workflow 自动执行某项检查，不代表该检查必须成为普通 Task Gate 的同步完成条件。

---

## 1. 质量工具链原则

OnlyAlpha 的质量工具链遵循以下原则。

### 1.1 最小充分验证

开发者或 Agent 应优先运行：

> 能以最低成本可靠验证当前 Impact Scope 的最小充分检查集合。

不得仅因为完整检查已经存在，就在每个普通 Task 中重复执行完整仓库验证。

---

### 1.2 验证范围由 Impact Scope 决定

普通 Task 的验证范围不由：

* Repository 总体大小；
* CI 中存在多少 Job；
* 当前已有多少 Test Lane；
* 是否方便直接运行 full suite；

决定。

验证范围应由本次修改的实际 Impact Scope 决定。

如果影响能够可靠限定在局部，则使用局部验证。

如果影响无法可靠确定，应扩大到最近的稳定：

`module -> subsystem -> canonical lane`

而不是默认直接扩大到整个 Repository。

---

### 1.3 CI Execution 不等于 Task Acceptance

GitHub CI 是持续质量信号。

普通 Task 的完成标准由 Task Prompt 中声明的：

* Modification Scope；
* Impact Scope；
* Acceptance Tests；
* Validation Boundary；

决定。

因此：

`CI pending != Task blocked`

普通 Task 在其 Task Gate 通过后即可标记 `Task Complete`。

但：

`known real CI regression = must fix`

如果 GitHub CI 已经明确发现当前 HEAD 引入了真实 regression，该问题不得被长期忽略，并必须在最终 `Phase Complete` 前解决。

---

### 1.4 重型验证低频执行

以下验证默认属于 Phase Gate、Certification Gate、Nightly 或 Release：

* repository-wide branch coverage；
* full repository regression；
* exhaustive Hypothesis；
* CrossHair 全量检查；
* mutation testing；
* CodeQL；
* dependency vulnerability audit；
* cross-platform distribution smoke；
* release build certification；
* Final-SHA Certification。

普通 Task 不应机械执行这些验证。

---

## 2. 执行矩阵

| Tool               | Purpose                    |                   Local / Task |                 PR / Master |                  Nightly | Phase / Certification / Release |
| ------------------ | -------------------------- | -----------------------------: | --------------------------: | -----------------------: | ------------------------------: |
| pytest             | Unit / Contract / Scenario |                 affected scope |              selected lanes | heavy/exhaustive subsets |             full required lanes |
| Ruff               | Lint                       |       changed / affected scope |                        full |                          |                            full |
| Ruff Format        | Formatting                 |       changed / affected scope |                        full |                          |                            full |
| Mypy               | Type safety                |           affected typed scope |    full configured packages |                          |                            full |
| Import Linter      | Architecture               |     when architecture affected |                           ✓ |                          |                               ✓ |
| Architecture Tests | Dependency invariants      |              affected boundary |              selected lanes |                          |               full relevant set |
| Hypothesis         | Properties                 |                    dev profile | ci profile where applicable |               exhaustive |                        critical |
| Semgrep            | Project semantic rules     |                      selective |                           ✓ |                          |                               ✓ |
| Branch Coverage    | Test path completeness     |         exceptional/local only |    automated quality signal |                          |         mandatory full coverage |
| CrossHair          | Formal contracts           |                      selective |                             |                        ✓ |                        critical |
| mutmut             | Test strength              |                                |                             |                        ✓ |                 critical subset |
| CodeQL             | Static/security            |                                |         automated/scheduled |                scheduled |                   certification |
| Dependency Audit   | Supply chain               |                                |                   automated |                          |                   certification |
| pytest-benchmark   | Micro performance          |                      selective |                             |                        ✓ |                release-critical |
| ASV                | Historical performance     |        `asv check` when needed |                             |                        ✓ |                         release |
| Build              | Packaging correctness      | targeted when package affected |                           ✓ |                          |                            full |
| Distribution Smoke | Clean-install correctness  |                  targeted only |             optional/manual |                          |     phase/release when required |

Dependabot independently检查 `uv`、GitHub Actions 和 pre-commit 等依赖更新。

它属于依赖维护机制，不是 Test Gate 或 Test Lane。

---

## 3. Local Development / Task Gate

普通修改只运行本次 Task 的最小充分验证。

正式顺序是：冻结含 `TASK_BASE_SHA`、Goal、Modification/Impact Scope、Required Behavior、Expected Acceptance Tests、Expansion
Triggers 与 Out of Scope 的 Task Contract；实施并运行 expected tests；根据实际 changed set 由 `scripts/verify.py` 校验 Impact；
只有具体证据触发时才扩大；最后给出一个 Task Gate verdict。模板见 `docs/engineering/task-gate-template.md`，它不是新的规范 authority。

典型组合包括：

```bash
uv run pytest <affected-tests> -q
uv run ruff check <affected-paths>
```

涉及 typed production code 时：

```bash
uv run mypy <affected-module-or-package>
```

如果当前 Impact Scope 已经有稳定 canonical lane，则可以直接运行对应 lane：

```bash
uv run python scripts/test_suite.py <lane>
```

是否运行整个 lane 由 Task 的 Impact Scope 决定，而不是固定要求。

`scripts/verify.py` 的 component plan 对 Ruff、Format 和 Mypy 使用 affected targets；architecture boundary 才要求 Import Linter，
package/build metadata 才要求 version sync 与 targeted build。Unknown impact 和 verification infrastructure 仍 fail closed 到
FULL_LOCAL。Coverage 默认属于 Phase/Certification，不因 lane 已注册就自动进入普通 Task Gate。

---

### 3.1 普通局部修改

例如：

* private helper；
* 单模块内部算法；
* 明确局部的数据转换；
* 无公共契约变化的实现修复；

通常只需要：

* 本任务新增或修改测试；
* 直接受影响 regression tests；
* affected Ruff；
* 必要的 affected Mypy。

验收通过后即可 `Task Complete`。

---

### 3.2 Architecture Boundary 变化

如果修改影响：

* Core / Plugin 依赖方向；
* Domain isolation；
* Runtime boundary；
* Research / Trading firewall；
* package layering；

则增加：

```bash
uv run lint-imports
```

以及对应 architecture tests。

不得仅因为执行 architecture tests 就自动升级到 repository-wide validation。

---

### 3.3 Property / Domain Invariant 变化

如果修改 Domain invariant、identity、determinism 或其他 property-level contract，应运行对应 property tests。

默认本地 profile 使用 `dev`：

```bash
uv run pytest tests/property/test_domain_properties.py -q --tb=short
```

Task Gate 中只执行受影响 property scope。

Exhaustive profile 默认不属于普通 Task Gate。

---

### 3.4 State / Persistence / Recovery 变化

如果修改涉及：

* state machine；
* checkpoint；
* persistence；
* serialization；
* resume；
* replay；
* recovery；
* idempotency；

则必须执行对应 state/recovery regression tests。

必要时使用已有：

```bash
uv run python scripts/test_suite.py recovery
```

或：

```bash
uv run python scripts/test_suite.py sim-recovery
```

是否运行整个 lane，应根据实际 Impact Scope 判断。

---

### 3.5 Public Contract 变化

如果修改：

* Protocol；
* ABC；
* public model；
* public Enum；
* Runtime interface；
* provider/broker contract；

则 Task Gate 应覆盖：

* direct contract tests；
* known consumers；
* relevant Mypy；
* architecture tests；
* affected canonical lane where appropriate。

公共接口 diff 很小，不代表 Impact Scope 很小。

---

### 3.6 Package / Plugin 变化

如果修改：

* `pyproject.toml`；
* Entry Point；
* plugin discovery；
* distribution metadata；
* dependency definitions；
* workspace package structure；

应增加对应：

* plugin/discovery tests；
* version synchronization；
* targeted package build；
* 必要的 clean-install smoke。

不应默认因此运行整个 cross-platform distribution certification。

---

## 4. 不属于普通 Task Gate 的检查

普通开发默认不要执行：

```bash
uv run python scripts/test_suite.py core-full --coverage
```

也不要机械执行：

```bash
uv run python scripts/test_suite.py <lane> --coverage
```

所有 `--coverage` 类型完整覆盖率验证，默认属于：

* Phase Gate；
* Certification Gate；

而不是普通 Task Gate。

普通 Task 可以在以下情况下显式使用局部 coverage：

* Task 本身是 coverage closure；
* Task 修改 coverage infrastructure；
* 某个明确局部路径无法通过更轻量验证可靠证明。

即使如此，也应优先选择最小适用 scope。

---

## 5. Canonical Test Lanes

OnlyAlpha 当前通过 `scripts/test_suite.py` 管理稳定测试 lane。

这些 lane 是：

* Task Impact Scope 扩大的稳定边界；
* Phase Gate 的主要组成部分；
* Certification 的正式验证输入。

当前主要 lane 包括：

```text
calculation
research-calculation
research-factor
research-job
research-sweep
research-dataset
fast
integration
ashare
recovery
sim-recovery
miniqmt-contract
miniqmt-local
core-full
exhaustive
release
```

普通 Task 不要求全部运行这些 lane。

当 Impact Scope 无法可靠保持在单模块级别时，应优先扩大到对应 canonical lane，而不是直接运行整个 Repository。

---

## 6. Pull Request / Master Continuous Quality

GitHub `quality.yml` 负责提供比单个 Task 更广的持续质量信号。

当前自动质量检查包括适用的：

* Ruff；
* Ruff format；
* Mypy；
* Import Linter；
* version synchronization；
* Semgrep；
* selected product / research lanes；
* branch coverage；
* build；
* dependency audit。

这些自动检查的存在，不改变普通 Task Gate 的局部验收边界。

普通 Task：

```text
Task Acceptance Tests PASS
        ↓
Task Complete
```

不需要因为所有 GitHub workflow 尚处于 pending 状态而停止后续开发。

GitHub workflow 可以继续自动运行。

如果其后发现当前 HEAD 引入真实 regression：

```text
CI FAILED
+
failure belongs to current HEAD
        ↓
must fix
```

真实 regression 必须在 Phase Complete 前清除。

---

## 7. Branch Coverage

Branch Coverage 属于系统级验证能力。

完整 coverage 的目标不是提供每次代码编辑后的即时反馈，而是发现：

* branch path 缺失；
* regression coverage 下降；
* critical behavior 没有充分测试；
* 多个 Task 组合后出现测试覆盖空洞。

Coverage 输出统一写入：

```text
test-results/coverage/
```

本地产生的 coverage 文件不应提交。

完整：

```bash
uv run python scripts/test_suite.py core-full --coverage
```

默认只在 Phase Gate 或 Certification Gate 执行。

各专项：

```bash
uv run python scripts/test_suite.py calculation --coverage
uv run python scripts/test_suite.py research-calculation --coverage
uv run python scripts/test_suite.py research-factor --coverage
uv run python scripts/test_suite.py research-job --coverage
uv run python scripts/test_suite.py research-sweep --coverage
uv run python scripts/test_suite.py research-dataset --coverage
```

同样默认属于系统级质量验证。

不得在每个普通 P7.x / P8.x Task 后重复运行。

---

## 8. Phase Gate

当一个完整阶段，例如 P7 或 P8，所有 Task 均达到 `Task Complete` 后，执行一次完整 Phase Gate。

Phase Gate 用于回答：

> 所有 Task 组合后，Repository 是否仍满足整体功能、架构和关键工程不变量？

Phase Gate 通常应包含：

### Static Quality

* full Ruff；
* full format check；
* full configured Mypy；
* Import Linter；
* version synchronization；
* semantic architecture guardrails。

### Regression

运行当前阶段要求的 canonical lanes，包括适用的：

```text
core-full
calculation
research-calculation
research-factor
research-job
research-sweep
research-dataset
recovery
sim-recovery
ashare
miniqmt-contract
```

具体 canonical set 以当前 Repository 为准。

### Coverage

执行完整 branch coverage，包括适用的：

```bash
uv run python scripts/test_suite.py core-full --coverage
```

以及阶段内存在独立 coverage requirement 的正式模块。

### Functional Scenario

必须验证本阶段真正新增的纵向功能链。

不能只依赖大量 Unit Test 的数量。

例如 Runtime 类型阶段，应验证类似：

```text
create
-> execute
-> state transition
-> persist
-> restart
-> recover
-> continue
```

这种用户或 Runtime 可观察的真实工作流。

### Build

运行正式 workspace/package build。

Phase Gate 的作用是发现：

> 单个 Task 均正确，但组合之后产生的 integration regression。

---

## 9. Certification Gate

Phase Gate 通过后，冻结最终 commit SHA。

Final-SHA Certification 只针对这个不可变 SHA。

Certification 的作用不是开发反馈，而是留下正式版本证据。

当前 Certification 应消费适用的：

* static verification；
* canonical lanes；
* mandatory branch coverage；
* build；
* Semgrep；
* dependency audit；
* CodeQL；
* certification evidence；
* final verdict。

流程：

```text
Task Complete x N
        ↓
Phase Gate
        ↓
Phase Complete
        ↓
Freeze Final SHA
        ↓
Final-SHA Certification
        ↓
Certified
```

普通 Task 不运行 Final-SHA Certification。

---

## 10. Hypothesis

Hypothesis 按验证层级使用不同 profile。

开发阶段使用较低成本 profile，例如：

```text
dev
```

PR / automated quality signal 可使用：

```text
ci
```

Nightly 使用：

```text
exhaustive
```

普通 Task 只运行与当前 Domain invariant 直接相关的 property tests。

不得为了普通实现任务机械执行全仓 exhaustive Hypothesis。

---

## 11. Semgrep

Semgrep 用于表达 Python 类型系统、Unit Test 和 Import Linter 难以表达的语义 guardrail。

本地 Task Gate 仅在修改明确涉及相应语义边界时执行 selective scan。

例如 Domain deterministic boundary：

```bash
semgrep scan --config semgrep/onlyalpha.yml src/onlyalpha/domain
```

PR / Certification 可以执行完整：

```text
src
packages
```

普通 Task 不应无条件全仓扫描。

---

## 12. CrossHair

CrossHair 用于验证适合形式化分析的纯函数或 contract。

普通 Task 只有在修改对应正式 contract 时才运行指定 target。

例如：

```bash
uv run crosshair check tests/formal/contracts.py
```

CrossHair 全量验证属于 Nightly / critical certification scope。

---

## 13. Mutation Testing

Mutation testing 用于验证：

> 测试是否真的能够杀死错误实现。

它不是普通开发反馈工具。

mutation 默认属于 Nightly。

Release / critical validation 可以运行稳定 subset。

普通 Task 不要求运行 `mutmut`。

mutation 初期主要关注：

* generated；
* killed；
* survived；
* timeout；

不因为任意全局 mutation score 阻塞普通开发。

---

## 14. CodeQL

CodeQL 属于仓库级静态与安全分析。

它不属于普通 Task Gate。

CodeQL 应由：

* GitHub automated workflow；
* scheduled analysis；
* Final-SHA Certification；

承担。

普通 Task 不需要本地模拟 CodeQL。

---

## 15. Dependency Audit

依赖安全分析以 authoritative lockfile 为输入。

普通 Task 修改 dependency 时，应确保：

* dependency declaration 正确；
* lockfile 同步；
* package/build 可用。

完整 vulnerability audit 由 GitHub 自动化和 Certification 负责。

普通 Task 不需要等待完整 dependency audit 才能 `Task Complete`。

如果自动 audit 后续发现当前 HEAD 新引入真实高风险漏洞，则属于必须修复的真实 CI regression。

---

## 16. Performance

性能验证分为两类。

### pytest-benchmark

用于局部性能关键路径。

修改性能敏感代码时可以选择运行：

```bash
uv run pytest tests/performance/test_quality_benchmarks.py -q --benchmark-only
```

### ASV

用于历史性能趋势。

修改 ASV 配置时：

```bash
asv check
```

完整 historical benchmark 属于 Nightly / Release。

普通功能 Task 不应因为代码发生变化就机械执行完整性能体系。

---

## 17. Build 与 Distribution Verification

Package build 属于重要质量证据，但验证强度需要分层。

### Task Gate

仅在 package/plugin metadata 或 distribution behavior 被修改时进行 targeted build/smoke。

### PR / Continuous Quality

自动执行 workspace build，发现明显 packaging regression。

### Phase / Certification

执行正式 build，并在需要时进行：

* wheel；
* sdist；
* metadata validation；
* clean environment installation；
* import smoke；
* Entry Point discovery；
* cross-platform verification。

Cross-platform distribution smoke 是阶段或发布级验证能力，不是普通 Task 默认验收项。

---

## 18. Nightly

Nightly 只承担不适合作为普通 Task 或高频 PR 同步验收的重型工作。

主要包括：

* exhaustive Hypothesis；
* CrossHair contracts；
* mutation testing；
* pytest-benchmark；
* ASV performance history；
* 其他高成本专项分析。

Nightly 不应无意义重复所有已经由其他层级充分验证的工作。

---

## 19. Release

Release 验证针对正式发布要求。

它可以包括：

* critical formal checks；
* critical mutation subset；
* stable performance metrics；
* distribution build；
* clean install；
* release-specific smoke；
* required certification evidence。

Release 不是普通开发 Task 的验收层。

---

## 20. Agent / Codex Validation Rule

普通 Codex Task 的 Prompt 应明确：

```text
Goal

Modification Scope

Impact Scope

Required Behavior

Acceptance Tests

Out of Scope

Validation Boundary
```

Codex 应按声明范围实现和验证。

实现前还必须记录 `TASK_BASE_SHA`、Expected Acceptance Tests 与 Expansion Triggers；完成时记录 actual changed/impact scope、
实际执行的检查、扩张理由以及明确未执行的 Phase/Certification 项。

不得在任务完成阶段自行把：

```text
Task Gate
```

扩大成：

```text
full repository certification
```

如果实现过程中发现新的真实依赖：

```text
Declared Impact Scope
        +
New concrete dependency
        ↓
Extend to nearest affected subsystem/lane
```

不得因为发现一个额外依赖而自动：

* 跑全部 coverage；
* 跑全部 lane；
* 修改 CI；
* 修改 test layering；
* 修改 quality framework；
* 运行 Final-SHA Certification。

质量体系变更必须作为独立工程问题处理。

---

## 21. 常用命令

### Local / Task Gate

```bash
uv run pytest <affected-tests> -q
uv run ruff check <affected-paths>
uv run mypy <affected-module-or-package>
```

### Canonical Lane

```bash
uv run python scripts/test_suite.py fast
uv run python scripts/test_suite.py research-dataset
uv run python scripts/test_suite.py research-calculation
uv run python scripts/test_suite.py research-job
uv run python scripts/test_suite.py research-factor
uv run python scripts/test_suite.py research-sweep
uv run python scripts/test_suite.py recovery
uv run python scripts/test_suite.py sim-recovery
```

### Phase / Certification Coverage

```bash
uv run python scripts/test_suite.py core-full --coverage
uv run python scripts/test_suite.py calculation --coverage
uv run python scripts/test_suite.py research-calculation --coverage
uv run python scripts/test_suite.py research-factor --coverage
uv run python scripts/test_suite.py research-job --coverage
uv run python scripts/test_suite.py research-sweep --coverage
uv run python scripts/test_suite.py research-dataset --coverage
```

### Architecture

```bash
uv run lint-imports
```

### Property

```bash
HYPOTHESIS_PROFILE=ci uv run pytest tests/property -q --tb=short
```

### Formal

```bash
uv run crosshair check tests/formal/contracts.py
```

### Mutation

```bash
uv run mutmut results
```

### Performance

```bash
uv run pytest tests/performance/test_quality_benchmarks.py -q --benchmark-only
asv check
```

---

## 22. Generated Evidence

生成的以下内容默认属于机器验证产物：

* coverage；
* mutation；
* pytest metrics；
* benchmark；
* ASV；
* security scan evidence；
* certification evidence。

机器相关 cache、临时虚拟环境、绝对路径和本地执行中间文件不得提交。

正式 Certification evidence 是否需要作为 GitHub Artifact 或其他长期证据保存，由对应 Certification workflow 定义。

---

## 23. 最终执行原则

OnlyAlpha 的质量工具链最终遵循：

```text
Local Development
    ↓
最小快速反馈

Task Gate
    ↓
Impact Scope 内充分验证

Phase Gate
    ↓
阶段级完整回归、coverage、build、functional scenario

Certification Gate
    ↓
不可变 Final SHA 正式认证
```

因此：

> **普通 Task 不证明整个 Repository 正确。**

它只需要可靠证明：

> **本次修改以及其实际 Impact Scope 正确。**

而 Repository 级完整性由 Phase Gate 验证。

最终不可变版本的正式可信度由 Certification Gate 验证。

通过这种分层，OnlyAlpha 在不降低最终正确性、架构一致性、可验证性和可恢复性的前提下，避免在每个小任务上重复消耗完整仓库验证成本。
