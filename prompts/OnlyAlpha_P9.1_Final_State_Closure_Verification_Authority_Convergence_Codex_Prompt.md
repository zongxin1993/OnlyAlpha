# OnlyAlpha P9.1 Final State Closure — Verification Authority Convergence

> 任务性质：**P9.1 Final State Closure / Verification Control-Plane Correctness Fix**
>
> 目标：从第一性原理出发，彻底解决当前 OnlyAlpha 工程质量验证体系中出现的 **Gate Policy 多权威、历史证据隐式依赖、验证动作未进入最终 Verdict、P9.1 Binance 测试/类型检查未完整进入 canonical verification surface** 等问题。
>
> 本任务不是为了“让 CI 变绿”，而是为了从根本上建立一个长期稳定、唯一、确定、可验证、可演进的工程验证控制面。
>
> 工程原则：
>
> ```text
> Correctness
> > Determinism
> > Uniqueness
> > Explicit Authority
> > Fail-Closed
> > Reproducibility
> > Maintainability
> > Performance
> > Convenience
> ```
>
> **禁止用降低门禁、skip/xfail、隐藏失败、删除关键测试、扩大 ignore/exclude 等方式换取 CI 绿色。**
>
> 任务完成后：
>
> ```text
> P9.1 = TASK COMPLETE / VERIFIED
> P9.2 = IMPLEMENTATION READY
> ```
>
> 在所有 required gates 和 Final-SHA Certification 通过之前，不得推进 project-state。

---

# 1. 当前背景

当前 OnlyAlpha 已完成 P9.1 Binance Spot Market Product & Reference Authority 主体实现与 correctness closure。

P9.1 已经解决：

```text
Capture != Semantic Reference
immutable raw evidence
immutable semantic reference
provenance
exchange-level rules
notional policy
MARKET_LOT_SIZE
dynamic price requirement
as-of temporal applicability
permission / capability boundary
bounded public HTTP
```

当前问题不再是 Binance Spot 业务语义实现问题。

当前问题发生在：

```text
Engineering Verification Control Plane
```

即：

```text
“什么测试必须运行”
“什么 gate 必须成功”
“什么 evidence 属于 certification”
“什么测试需要历史 Git”
“哪些 package 属于 canonical verification surface”
```

这些事实目前存在多个平行 Authority，并已产生实际 CI 漂移。

---

# 2. 当前基线

任务开始时必须重新读取当前 `master`。

审计时已知基线：

```text
repository: zongxin1993/OnlyAlpha
branch: master

audited master:
d4b5d3b021e0b70f676fcd68ec661b33a4d21f08
```

如果 master 已前移：

```text
以最新 master 为准
```

但必须先验证本文列出的根因是否仍存在。

已正确解决的问题：

```text
validate only
do not redesign
```

---

# 3. 第一性原理：最终工程验证是什么

最终工程验证应当等价于一个确定函数：

```text
Verdict =
F(
    Immutable Subject SHA,
    Quality Policy,
    Required Evidence
)
```

必须满足：

```text
same Subject SHA
+ same Quality Policy
+ same Required Evidence

→ same Verdict
```

不能额外隐式依赖：

```text
clone depth
commented YAML
developer memory
哪个脚本恰好先运行
旧 Prompt
本地工作树状态
网络偶发状态
```

如果存在隐藏变量：

```text
Verdict =
F(SHA, Policy, Evidence, Hidden Environment)
```

则验证系统违反确定性原则。

---

# 4. 唯一性原则

每一个关键工程事实只能存在一个 Authority。

例如：

```text
Project progression
→ project-state.toml

Repository pytest discovery
→ pyproject.toml [tool.pytest.ini_options].testpaths

Root mypy target surface
→ pyproject.toml [tool.mypy].files

Quality mandatory gate membership
→ one machine-readable Quality Policy Authority

Historical Git evidence ownership
→ one explicit history-capable lane
```

禁止：

```text
quality.yml 定义一套
certification.yml 定义一套
certification.py 再定义一套
architecture test 再定义一套
quality-system.md 再定义一套
```

---

# 5. 当前已确认的根本问题

本任务必须整体解决下面四类问题。

## 5.1 Problem A — Gate Policy 多权威

当前 GitHub Workflow 已经关闭 Coverage mandatory gate。

但：

```text
scripts/certification.py
```

仍然：

```python
REQUIRED_GATES = {
    ...
    "coverage",
    ...
}
```

Architecture Contract 仍要求：

```text
coverage mandatory
```

Quality System 文档仍大量声明：

```text
coverage mandatory
```

结果：

```text
Workflow Truth
!=
Certification Truth
!=
Architecture Truth
!=
Documentation Truth
```

这是直接违反 Single Authority。

## 5.2 Problem B — Architecture Contract 验证文本，不验证语义

当前测试存在类似：

```python
assert "research-definition --coverage" in quality_text
```

即使 workflow 中：

```yaml
# research-definition --coverage
```

已经被注释掉，字符串依然存在。

因此 Architecture Test 可能得到：

```text
PASS
```

但 GitHub Actions 实际语义是：

```text
disabled
```

这属于：

```text
false positive
```

测试对象错误。

Architecture Contract 必须验证：

```text
parsed active YAML semantics
```

不能验证：

```text
raw text substring
```

## 5.3 Problem C — Historical Git Evidence 隐式依赖

P9.K.7 已经明确冻结：

```text
current-tree architecture invariants
→ Architecture lane
→ shallow checkout allowed

historical K7 scope preservation
→ dedicated gateway-protocol lane
→ full Git history required
```

但：

```text
tests/contracts/test_p9_k7_task_delta.py
```

目前可能被 `core-full` 收集。

`core-full` 默认 shallow checkout。

于是：

```text
same SHA
same test

gateway-protocol
→ PASS

core-full
→ FAIL
```

原因只是：

```text
Git history availability differs
```

这违反确定性。

正确解决方向不是：

```text
把所有 CI 都 fetch-depth: 0
```

而是：

```text
明确 Historical Evidence Ownership
```

## 5.4 Problem D — Verification Surface 漏接 P9.1 Binance

当前：

```text
pyproject.toml
[tool.pytest.ini_options]
testpaths = [...]
```

已经包含：

```text
packages/market/onlyalpha-market-binance-spot/tests
packages/provider/onlyalpha-plugin-binance/tests
```

但是：

```text
scripts/test_suite.py::WORKSPACE_TESTS
```

没有包含这两个 package。

因此：

```text
core-full PASS
```

不能机械证明：

```text
Binance Market Product offline tests PASS
Binance Provider offline tests PASS
```

同类问题还存在于 static mypy：

root `pyproject.toml [tool.mypy].files` 已包含 Binance packages，

但 workflow 使用大量显式 mypy path command，导致新 package 可能没有真正进入 CI static gate。

根因仍然是：

```text
parallel list drift
```

---

# 6. 本任务最终目标架构

目标不是增加更多配置。

目标是把验证体系改成：

```text
                     ┌─────────────────────────┐
                     │ Quality Policy Authority │
                     └────────────┬────────────┘
                                  │
                    ┌─────────────┼─────────────┐
                    ↓             ↓             ↓
               quality.yml  certification.py  architecture tests
                    │             │
                    ↓             ↓
               Quality Gate   Final-SHA Verdict


                     ┌─────────────────────┐
                     │   pyproject.toml    │
                     └──────────┬──────────┘
                                │
                 ┌──────────────┴──────────────┐
                 ↓                             ↓
         pytest testpaths                 mypy.files
                 │                             │
                 ↓                             ↓
        canonical test surface          canonical type surface


historical_git marker
        │
        ├── generic current-tree lanes: EXCLUDE
        │
        └── gateway-protocol: INCLUDE + full history
```

核心关系：

```text
Authority
→ Projection
→ Validation
```

不是：

```text
Projection A
Projection B
Test Expectation
Documentation

all independently author the same truth
```

---

# 7. Implementation Block A — 建立 Machine-Readable Quality Policy Authority

新增一个最小的 machine-readable policy。

建议：

```text
quality-policy.toml
```

如果仓库已有更合适的 canonical config 位置，可以选择更符合当前结构的位置。

不要建立复杂 CI DSL。

只解决：

```text
mandatory gate membership
coverage mode
historical evidence ownership
```

建议最小结构：

```toml
schema_version = 1

coverage_mode = "manual"

[quality]
required_gates = [
  "static",
  "architecture",
  "openapi-contract",
  "gateway-protocol",
  "semgrep",
  "dependency-audit",
  "research-postgres",
  "build",
  "web",
]

event_lane_gates = [
  "pr-lanes",
  "main-lanes",
]

[certification]
required_gates = [
  "subject",
  "static",
  "build",
  "web",
  "lanes",
  "research-postgres",
  "gateway-protocol",
  "semgrep",
  "dependency-audit",
  "codeql",
]

[historical_evidence]
exclusive_owner = "gateway-protocol"
```

字段名可以按现有风格微调。

必须满足：

```text
one machine-readable source
```

---

# 8. Coverage Policy 最终冻结

本阶段正式定义：

```text
Coverage Mode = MANUAL
```

语义：

```text
Coverage implementation:
SUPPORTED

Coverage thresholds:
PRESERVED

Local/manual --coverage:
SUPPORTED

Coverage run below configured threshold:
FAIL

Regular GitHub CI:
NOT MANDATORY

Final-SHA Certification:
NOT MANDATORY
```

因此：

```text
coverage
```

必须从：

```text
quality mandatory gate set
certification mandatory gate set
certification.py REQUIRED_GATES
architecture mandatory expectations
```

移除。

但是必须保留：

```text
scripts/test_suite.py --coverage
coverage thresholds
coverage json/xml output
pytest-cov dependency
```

不要降低 threshold。

不要删除本地 coverage 能力。

---

# 9. 删除 workflow 中被注释的 Coverage Dead Config

当前 workflow 中整段：

```yaml
# coverage:
# ...
```

建议删除。

原因：

```text
inactive comments
!=
configuration
```

保留这些历史注释会：

```text
误导开发者
误导 Agent
污染 grep
制造 architecture false positive
```

Coverage 如何使用，应由：

```text
quality-system.md
scripts/test_suite.py
quality-policy.toml
```

表达。

不要把禁用 workflow 当注释长期保存。

---

# 10. Implementation Block B — Certification Contract 从 Policy Authority 读取

修改：

```text
scripts/certification.py
```

禁止继续手写独立：

```python
REQUIRED_GATES = frozenset({...})
```

它应该从：

```text
quality-policy.toml
```

读取：

```text
certification.required_gates
```

或者由一个小型 canonical quality-policy module 读取并导出。

要求：

```text
missing mandatory gate
→ FAIL CLOSED

unexpected gate
→ FAIL CLOSED

duplicate gate
→ FAIL CLOSED

non-success mandatory gate
→ REJECTED

invalid subject SHA
→ FAIL CLOSED
```

这些现有正确行为继续保留。

---

# 11. Certification Schema Version

检查：

```text
certification-evidence.json
schema_version
```

当前 gate semantics 改变后：

```text
coverage mandatory
→ coverage manual/non-blocking
```

是否构成 certification evidence schema semantic change。

如果：

```text
schema_version = 1
```

过去代表：

```text
coverage mandatory
```

那么不要静默让同一个 version 现在代表另一套 required gate identity。

优先：

```text
bump certification schema version
```

或加入明确：

```text
quality_policy_schema_version
```

使历史 evidence 可解释。

原则：

```text
Policy changes
must not rewrite historical semantics.
```

---

# 12. Implementation Block C — Architecture Contract 改成解析 Active YAML

修改：

```text
tests/architecture/test_certification_contract.py
```

禁止：

```python
workflow_text = Path(...).read_text()
assert "coverage" in workflow_text
```

应使用：

```python
yaml.safe_load(...)
```

读取：

```text
jobs
needs
steps
active run
matrix
```

Architecture test 验证：

```text
Workflow Projection
==
Quality Policy Authority
```

例如：

```text
quality-gate active needs
==
policy quality required gates
+
event-scoped lane gates
```

以及：

```text
certification verdict active needs
==
policy certification required_gates
```

不得让 architecture test 自己维护一份第二 gate set。

---

# 13. Architecture Contract 必须验证 Coverage 当前是 NON-MANDATORY

明确测试：

```text
policy.coverage_mode == manual

quality workflow has no active coverage job

quality-gate active needs
does not contain coverage

certification workflow has no active coverage job

certification verdict active needs
does not contain coverage

certification.py required gates
does not contain coverage
```

同时验证：

```text
scripts/test_suite.py still accepts --coverage
```

覆盖能力仍存在。

---

# 14. Implementation Block D — 建立 Explicit Historical Git Marker

在：

```text
pyproject.toml
```

注册：

```text
historical_git
```

定义：

```text
requires immutable Git history and may only run in an explicitly history-capable verification lane
```

在：

```text
tests/contracts/test_p9_k7_task_delta.py
```

标记：

```python
pytestmark = (
    pytest.mark.contract,
    pytest.mark.historical_git,
)
```

或者与现有 marker style 等价的实现。

---

# 15. Historical Test 内部继续 Fail-Closed

不得改成：

```python
if commit missing:
    pytest.skip()
```

不得：

```text
xfail
warning
best effort
```

正确：

```text
required commit missing
→ FAIL CLOSED
```

因为在正确的 owner lane 中：

```text
Git history is required evidence
```

没有 evidence 就不能声称 PASS。

---

# 16. Generic Current-Tree Lanes 排除 historical_git

修改：

```text
CORE_FULL
FAST
```

以及其他会广泛收集 contract tests、但不承诺 full Git history 的 lane。

明确：

```text
not historical_git
```

目标：

```text
core-full
=
current-tree repository correctness
```

不是：

```text
historical audit reconstruction
```

不要通过：

```text
all core-full checkout fetch-depth: 0
```

掩盖 ownership 错误。

---

# 17. Gateway Protocol 成为唯一 Historical Evidence Owner

继续保持/确认：

```text
gateway-protocol
```

使用：

```yaml
fetch-depth: 0
```

执行：

```text
gateway generation/check
gateway compatibility
K7 historical delta
remote gateway contract
```

如果当前 dedicated lane 已有正确命令：

```text
reuse
```

不要另造第二套。

---

# 18. Gateway Protocol 必须进入 Quality Verdict

当前不能只是：

```text
job exists
```

必须：

```text
job result
→ consumed by quality-gate
```

要求：

```text
gateway-protocol = success
```

否则：

```text
quality-gate = failure
```

不能允许：

```text
skipped
cancelled
failure
```

被当成成功。

---

# 19. Gateway Protocol 必须进入 Final-SHA Certification

在：

```text
.github/workflows/certification.yml
```

加入一个正式：

```text
gateway-protocol
```

job。

必须：

```text
needs: subject
checkout exact immutable subject SHA
fetch-depth: 0
```

执行与 regular quality workflow 同一个 canonical Gateway verification path。

Final verdict：

```text
--gate "gateway-protocol=$GATEWAY_PROTOCOL_RESULT"
```

并由 policy authority 声明：

```text
gateway-protocol is mandatory
```

---

# 20. 禁止 Duplicate Gateway Command Set

如果 regular quality workflow 与 Final-SHA workflow 当前需要复制相同 Gateway command：

优先提取成：

```text
canonical script / test_suite lane
```

两个 workflow 都调用。

不要：

```text
quality.yml 一套 command
certification.yml 另一套 command
```

否则未来再次 drift。

---

# 21. Implementation Block E — 消灭 WORKSPACE_TESTS 第二 Authority

当前：

```text
pyproject.toml
[tool.pytest.ini_options]
testpaths = [...]
```

已经是 pytest canonical test discovery surface。

因此：

```text
scripts/test_suite.py
WORKSPACE_TESTS
```

不要继续手写第二份。

使用 Python 3.12：

```python
tomllib
```

读取 root：

```text
pyproject.toml
→ tool.pytest.ini_options.testpaths
```

得到：

```text
canonical workspace test paths
```

所有使用 `WORKSPACE_TESTS` 的 lane 自动消费该 Authority。

---

# 22. P9.1 Binance Tests 必须因此自动进入 core-full

必须机械证明：

```text
packages/market/onlyalpha-market-binance-spot/tests
```

进入：

```text
core-full
```

以及：

```text
packages/provider/onlyalpha-plugin-binance/tests
```

进入：

```text
core-full
```

无需在 `test_suite.py` 再手写 Binance path。

未来新 package 加入 pytest testpaths 后：

```text
canonical broad lanes
```

应自动包含。

---

# 23. Binance Public Network Contract 不进入 Deterministic Final-SHA Gate

当前：

```text
test_current_binance_public_reference_contract
```

带：

```text
external
requires_network
requires_binance_public
```

这些 marker 应继续保留。

Regular deterministic CI / Final-SHA Certification：

```text
exclude
```

不要把：

```text
Binance service availability
DNS
provider maintenance
rate limit
```

变成：

```text
OnlyAlpha source SHA correctness
```

的一部分。

可以保留：

```text
manual/nightly/provider drift contract
```

但它不是 Final-SHA correctness gate。

---

# 24. Implementation Block F — Root Mypy Surface 成为 Typecheck Authority

当前 root：

```text
pyproject.toml
[tool.mypy]
files = [...]
```

已经包含：

```text
Core
Indicator
Factor
Target
API
Client
Gateway
Binance Market Product
Binance Provider
```

所以 regular static gate 应优先使用：

```bash
uv run mypy
```

而不是：

```bash
uv run mypy src/onlyalpha
```

再手工复制大量 package path。

这样：

```text
new root-configured package
→ automatically enters canonical typecheck
```

---

# 25. 保留必要 Package-Local Mypy

对于不属于 root mypy target、确实需要 package-local config 的 package：

```text
generic-t0-cash
cn-ashare
tushare
miniqmt
virtual broker
```

等，

继续：

```text
mypy --config-file package/pyproject.toml package/src
```

是否纳入 root mypy 可以单独评估。

不要为本次任务强制迁移全部 package mypy config。

---

# 26. RELEASE_STATIC_COMMANDS 也必须同步

当前：

```text
scripts/test_suite.py::RELEASE_STATIC_COMMANDS
```

又维护了一套 static command set。

最终要求：

```text
local release static
quality CI static
Final-SHA static
```

三者语义一致。

优先设计：

```text
one canonical static command owner
```

然后：

```text
quality workflow
certification workflow
release
```

复用。

可以是：

```text
scripts/test_suite.py release-static
```

或现有最小可复用结构。

不要创建复杂 shell abstraction。

---

# 27. Static Architecture Contract

增加测试证明：

```text
root mypy authority includes Binance packages

quality static invokes canonical root mypy authority

certification static invokes same canonical root mypy authority

release static uses same semantics
```

不要用：

```text
raw substring
```

判断。

尽量验证 active command structure 或 canonical runner。

---

# 28. Implementation Block G — Quality Documentation 降级为 Projection

更新：

```text
docs/engineering/quality-system.md
```

当前大量：

```text
coverage mandatory
PR/master/release/Final-SHA mandatory
```

描述必须同步。

新规则明确：

```text
functional canonical lane
→ mandatory according to machine policy

coverage command
→ supported
→ local/manual evidence
→ thresholds preserved
→ not a mandatory regular GitHub CI gate
→ not a mandatory Final-SHA Certification gate
```

文档应明确：

```text
Machine Authority:
quality-policy.toml

Executable Projections:
quality.yml
certification.yml

Narrative Projection:
quality-system.md
```

不要让文档继续成为平行 machine authority。

---

# 29. 历史 Prompt / 历史 Report 不要重写

不要批量修改：

```text
prompts/
historical P7/P8/P9 reports
```

旧文档中记录的：

```text
当时 coverage mandatory
```

属于历史事实。

新 Policy 不得 back-project 到过去。

只修改：

```text
current normative quality documentation
```

以及：

```text
P9.1 final closure evidence
```

---

# 30. Project State Authority

保持：

```text
project-state.toml
```

是 progression 唯一 Authority。

不要：

```text
手改 README
手改 roadmap current state
```

如果项目已有：

```text
scripts/project_state.py
```

必须使用它推进并生成 projection。

---

# 31. 必须新增/更新的 Regression Tests

至少建立以下机械证明。

## T1 Coverage policy convergence

```text
policy says manual

quality workflow:
no active coverage job

quality-gate:
coverage absent

certification:
coverage absent

certification.py:
coverage absent

Result:
consistent
```

## T2 Comment cannot satisfy contract

workflow 中即使存在：

```yaml
# coverage
```

Architecture contract 也必须：

```text
ignore
```

验证 parsed active YAML。

## T3 Certification gate identity

```text
missing mandatory gate
→ ValueError

unexpected gate
→ ValueError

duplicate gate
→ ValueError

mandatory gate failure/skipped/cancelled
→ REJECTED
```

## T4 Gateway is mandatory

如果：

```text
quality-gate
```

不消费 gateway-protocol：

```text
architecture FAIL
```

如果：

```text
certification verdict
```

不消费 gateway-protocol：

```text
architecture FAIL
```

## T5 Gateway failure rejects verdict

```text
gateway-protocol=failure
→ certification REJECTED
```

## T6 Historical ownership

```text
historical_git test
→ core-full not collected
```

## T7 Historical owner full history

```text
gateway-protocol
→ fetch-depth: 0
→ historical K7 tests collected
```

## T8 Historical evidence fail-closed

在 history-capable lane：

```text
required immutable commit unavailable
→ FAIL
```

不允许 skip。

## T9 Test discovery authority

给：

```text
pyproject.toml testpaths
```

增加一个临时 fixture test path 或构造解析测试，

证明：

```text
canonical workspace test paths
```

自动包含。

不要依赖另一个手写列表。

## T10 P9.1 Binance Market Product in core-full

确认：

```text
packages/market/onlyalpha-market-binance-spot/tests/test_product.py
```

被 `core-full` 收集执行。

## T11 P9.1 Binance Provider offline tests in core-full

确认：

```text
test_http.py
test_reference.py
```

被 `core-full` 收集执行。

## T12 Binance public network test excluded

确认：

```text
test_public_contract.py
```

由于：

```text
external/requires_network
```

不进入 deterministic core-full。

## T13 Root mypy authority

确认：

```text
uv run mypy
```

覆盖：

```text
onlyalpha_market_binance_spot
onlyalpha_plugin_binance
```

## T14 Static projection equivalence

```text
quality static
certification static
release static
```

必须使用同一 canonical semantic set。

---

# 32. Targeted Verification 顺序

不要一上来跑全部仓库。

先：

```text
1. Quality Policy parser/tests
2. certification.py unit tests
3. architecture contract tests
4. P9.K.7 historical test
5. gateway-protocol lane
6. core-full collection / targeted collection proof
7. Binance Market Product tests
8. Binance Provider offline tests
9. root mypy
10. package-local required mypy
```

确认根因修复。

---

# 33. Canonical Verification

Targeted PASS 后执行：

```text
architecture
gateway-protocol
core-full
static
build
```

再按当前 impact / quality policy 运行完整 required CI。

---

# 34. Required GitHub CI Final State

新的 closure SHA 必须：

```text
static                  PASS
architecture            PASS
openapi-contract        PASS
gateway-protocol        PASS
pr-lanes/main-lanes     PASS or event-valid skipped
core-full               PASS
research-postgres       PASS
build                   PASS
web                     PASS
semgrep                  PASS
dependency-audit        PASS
quality-gate            PASS
CodeQL                  PASS
```

Coverage：

```text
NOT REQUIRED
```

不是：

```text
mandatory but skipped
```

语义必须清楚。

---

# 35. Final-SHA Certification

普通 CI 全绿后，对同一个 immutable SHA 执行：

```text
Final-SHA Certification
```

必须：

```text
subject                 success
static                  success
build                   success
web                     success
lanes                   success
research-postgres       success
gateway-protocol        success
semgrep                 success
dependency-audit        success
codeql                  success
```

最终：

```text
verdict = ACCEPTED
```

不得使用其他 SHA 的旧证据拼接。

---

# 36. P9.1 Final Evidence

更新：

```text
docs/reports/p9_1_binance_spot_market_product_reference_authority.md
```

或当前 canonical P9.1 closure report。

记录：

```text
Final SHA
Quality Policy version
Coverage mode
Required gate set
Gateway historical evidence result
Binance offline package test evidence
Binance mypy/static evidence
Layered Quality run
CodeQL run
Final-SHA Certification run
Final verdict
```

不要再做一份新的泛化审计报告。

---

# 37. Project State Transition

只有：

```text
regular required CI = PASS

AND

Final-SHA Certification = ACCEPTED
```

才允许推进：

```text
project-state.toml
```

使用官方 script。

目标：

```text
last_verified_increment = "P9.1"
last_verified_name = "Crypto Market Product & Binance Reference Authority"
last_verified_state = "TASK COMPLETE / VERIFIED"

next_authorized_increment = "P9.2"
next_authorized_name = "Binance Spot Historical & Realtime DataSource"
next_authorized_state = "IMPLEMENTATION READY"
```

具体字段服从当前 project-state schema。

---

# 38. 明确禁止的错误修复

禁止：

```text
降低 coverage threshold

删掉 P9.K.7 historical tests

commit 不存在就 pytest.skip

core-full 全部改 fetch-depth:0 来掩盖 ownership 错误

gateway-protocol 继续只是“运行但不进入 verdict”

把 external Binance public API test 放进 Final-SHA mandatory

手工把 Binance tests 再复制进 WORKSPACE_TESTS

手工把 Binance mypy command 再复制进两个 workflow

继续使用 raw text substring 验证 YAML

大规模重写整个 CI framework

引入复杂 DSL / CI generator

修改 Binance market/reference correctness code

提前实现 P9.2

优化无关 performance warnings

为了绿灯添加大面积 ignore/xfail/no-cover
```

---

# 39. Modification Scope

主要允许修改：

```text
quality-policy.toml                 # or equivalent canonical machine policy

.github/workflows/quality.yml
.github/workflows/certification.yml

scripts/certification.py
scripts/test_suite.py

tests/architecture/test_certification_contract.py
tests/contracts/test_p9_k7_task_delta.py

pyproject.toml

docs/engineering/quality-system.md

P9.1 final closure report
project-state through official script
```

如果需要很小的：

```text
scripts/quality_policy.py
```

作为 policy parser，可以增加。

不要建立大型 framework。

---

# 40. Out of Scope

明确禁止进入：

```text
P9.2 Binance Historical DataSource
P9.2 Binance Realtime WebSocket
P9.3 database foundation
P9.4 Broker/private API
API keys/signing
LIVE runtime
Futures
QMT
CTP
Trading Kernel business semantics
Strategy semantics
Performance optimization
Coverage redesign
```

---

# 41. Definition of Done — Authority

以下事实只有一个 machine-readable答案：

```text
Coverage mandatory?
→ NO

Coverage supported?
→ YES

Gateway protocol mandatory?
→ YES

Historical K7 owner?
→ gateway-protocol

Repository canonical testpaths?
→ pyproject.toml

Root canonical mypy surface?
→ pyproject.toml

Project stage?
→ project-state.toml
```

---

# 42. Definition of Done — Determinism

必须满足：

```text
same immutable SHA
+
same Quality Policy
+
same repository evidence

→ same verdict
```

`core-full` 不得因：

```text
shallow Git history
```

随机失败。

Historical tests 只在声明拥有历史证据的 lane 中执行。

---

# 43. Definition of Done — P9.1 Verification Surface

必须证明：

```text
Binance Market Product offline tests
→ canonical broad CI

Binance Provider offline tests
→ canonical broad CI

Binance Market Product source
→ static mypy authority

Binance Provider source
→ static mypy authority
```

同时：

```text
requires_binance_public
→ not mandatory deterministic Final-SHA
```

---

# 44. Definition of Done — Fail Closed

以下均必须拒绝：

```text
missing required gate
unexpected required gate
duplicate gate evidence
gateway failure
architecture inconsistency
missing historical Git evidence in owner lane
invalid subject SHA
Binance offline test regression
static type regression
```

不得 silent pass。

---

# 45. Stop Condition

本任务完成以后：

```text
不要继续重新审计 P9.1
不要继续寻找边缘优化
不要继续重构质量系统
```

一旦：

```text
new immutable SHA

regular required CI = ALL PASS

Final-SHA Certification = ACCEPTED

project-state:
P9.1 VERIFIED
P9.2 IMPLEMENTATION READY
```

立即停止。

下一任务：

```text
P9.2 Binance Spot Historical & Realtime DataSource
```

---

# 46. Codex 执行要求

Codex 不要先生成长篇审计。

执行顺序：

```text
1. Read current master truth
2. Bounded root-cause validation
3. Freeze final Quality Policy
4. Implement one machine Authority
5. Remove duplicate policy authors
6. Fix active YAML semantic validation
7. Fix historical evidence ownership
8. Make gateway-protocol a real mandatory gate
9. Derive workspace tests from canonical pytest testpaths
10. Restore canonical mypy verification surface
11. Add regression tests with each fix
12. Run targeted verification
13. Fix actual failures
14. Run required CI
15. Run Final-SHA Certification
16. Update final evidence
17. Advance project-state
18. STOP
```

如果发现与本任务无关的问题：

```text
record one concise follow-up
do not expand scope
```

---

# 47. 最终输出格式

Codex 完成后只需要给出：

```text
P9.1 FINAL STATE CLOSURE RESULT
===============================

Final HEAD:
Quality Policy Version:
Coverage Mode:

Authority Convergence:
- Gate policy:
- Test discovery:
- Typecheck surface:
- Historical evidence:
- Project state:

Verification:
- static:
- architecture:
- gateway-protocol:
- core-full:
- Binance market tests:
- Binance provider tests:
- research-postgres:
- build:
- web:
- semgrep:
- dependency-audit:
- CodeQL:
- quality-gate:

Final-SHA Certification:
- subject:
- verdict:

Project State:
- last_verified_increment:
- next_authorized_increment:

Remaining blockers:
- NONE / exact blockers only

VERDICT:
P9.1 VERIFIED / NOT VERIFIED

NEXT:
P9.2 only if VERIFIED
```

不要输出：

```text
“基本完成”
“看起来没问题”
“建议继续观察”
```

必须由证据给唯一结论。

---

# 48. 最终工程目标

完成后，OnlyAlpha 的工程验证控制面必须满足：

```text
                Immutable SHA
                     │
                     ▼
          One Quality Policy Authority
                     │
        ┌────────────┼────────────┐
        ▼            ▼            ▼
   Quality CI   Final-SHA Cert   Architecture
        │            │            │
        └────────────┼────────────┘
                     ▼
               Same Verdict
```

同时：

```text
Repository test discovery
→ one authority

Root typecheck discovery
→ one authority

Historical Git audit
→ one explicit owner

Project progression
→ one authority
```

最终目标不是“修好这一次 CI”。

而是：

> **以后新增 P9.2、P9.3、P9.4 package、lane、gate 或 verification evidence 时，不需要人工记住五六个平行列表；新增一个真实工程事实后，canonical authority 能让所有投影自动或机械一致。**

这才是从根本上解决问题。

当：

```text
P9.1 correctness
+
verification authority convergence
+
regular CI PASS
+
Final-SHA ACCEPTED
+
project-state transition
```

全部成立时：

> **封存 P9.1，停止审计，正式进入 P9.2。**
