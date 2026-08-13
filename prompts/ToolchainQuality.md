# OnlyAlpha 工程质量工具链建设任务

你正在修改：

```text
https://github.com/zongxin1993/OnlyAlpha
```

本任务要在 **不破坏现有架构、不显著增加 Codex Token 消耗、不让本地开发流程变慢、不制造重复验证** 的前提下，为 OnlyAlpha 建立完整的工程质量工具链。

需要引入：

1. Import Linter
2. Hypothesis
3. Semgrep
4. CrossHair
5. mutmut
6. Branch Coverage
7. CodeQL
8. Dependabot + Dependency Review
9. pytest-benchmark + ASV

---

# 0. 最高优先级原则

本任务除了提高工程质量，还必须优化：

```text
开发等待时间
+
Codex Token 消耗
+
重复测试成本
+
GitHub CI 资源消耗
```

核心原则：

> **快速、确定性、低成本的检查放在本地和 PR 前置阶段。**
>
> **耗时、计算密集、重复价值低的检查放到 GitHub CI / Nightly / Release。**
>
> **任何验证只在最合适的层级执行一次，不要为了“保险”在多个地方重复运行。**

最终目标不是：

```text
每次 Codex 修改
→ 跑所有工具
→ 跑所有测试
→ 再跑 CI 等价检查
```

而应该是：

```text
Codex 本地
    ↓
最小必要验证
    ↓
GitHub PR CI
    ↓
完整自动验证
    ↓
Nightly / Release
    ↓
重型验证
```

---

# 1. Token 与执行成本是正式工程约束

本任务必须把以下原则作为设计要求。

## 1.1 Codex 不重复做 CI 已经负责的重型工作

如果某项验证：

* 耗时长；
* 输出巨大；
* 会产生大量测试日志；
* 需要扫描大量文件；
* 会导致 Codex 等待并解析大量结果；
* GitHub CI 能稳定执行；

则优先放到：

```text
GitHub CI
Nightly
Release
workflow_dispatch
```

不要让 Codex 每个任务本地重复执行。

---

## 1.2 本地只运行与当前修改相关的最小验证集

例如：

修改：

```text
src/onlyalpha/domain/value.py
```

优先执行：

```text
ruff relevant files
mypy relevant/core package
relevant unit/property tests
lint-imports
```

而不是立即：

```text
core-full
recovery
ashare
miniqmt-contract
CrossHair all
mutmut all
ASV
CodeQL
```

---

## 1.3 避免重复读取和重复输出

不要：

```text
连续多次 cat 同一个大文件
连续多次跑相同测试
完整输出数千行 pytest log
完整打印 coverage HTML
反复 git diff 全仓库
```

优先：

```text
针对性读取
-q
--tb=short
只看失败
只看摘要
只看 changed files
```

---

## 1.4 GitHub CI 是完整验证主阵地

Codex 本地环境负责：

```text
快速反馈
+
局部正确性
+
配置语法验证
```

GitHub CI 负责：

```text
完整 regression
+
跨模块验证
+
重型静态分析
+
安全分析
+
mutation
+
formal verification
+
performance regression
```

---

# 2. 先读取当前 Repository

在修改前重新确认 current HEAD。

必须读取：

```text
README.md
AGENTS.md
pyproject.toml
uv.lock
.pre-commit-config.yaml

.github/workflows/ci.yml
.github/workflows/quality.yml
.github/workflows/nightly.yml

scripts/test_suite.py
scripts/pytest_layering.py
scripts/pytest_metrics.py

相关 src/
相关 tests/
相关 packages/
相关 docs/
```

但是：

> **不要无差别读取整个仓库所有文件。**

先读取：

```text
repo root
→ quality infrastructure
→ architecture docs
→ 本任务相关模块
```

只有发现需要进一步理解时再展开。

---

# 3. Current-State Audit

开始修改前确认：

```bash
git status --short
git branch --show-current
git rev-parse HEAD
```

并调查是否已经存在：

```text
Import Linter
Hypothesis
Semgrep
CrossHair
mutmut
branch coverage
CodeQL
Dependabot
Dependency Review
pytest-benchmark
ASV
```

不要重复建设。

---

# 4. 工具执行层级

必须按照以下原则设计。

## Level A — Local Fast

适合 Codex 和开发者频繁运行：

```text
Ruff
Ruff format check
Mypy
Import Linter
针对性 pytest
少量 Hypothesis
快速 Semgrep rules
uv lock check
version check
```

目标：

```text
秒级～低分钟级
```

---

# Level B — Pull Request CI

由 GitHub 自动执行：

```text
完整 Ruff
完整 mypy
Import Linter
Semgrep
fast
integration
recovery
ashare
miniqmt-contract
Branch Coverage
Dependency Review
CodeQL
build
```

Codex本地不必重复全部执行。

---

# Level C — Nightly

适合：

```text
Hypothesis exhaustive
CrossHair
mutmut
exhaustive tests
大规模 recovery
performance
```

---

# Level D — Release

适合：

```text
core-full
recovery
ashare
miniqmt-contract
formal checks
mutation critical subset
replay
performance baseline
build
```

---

# 5. Import Linter

## 目标

把 Architecture Dependency Rules 变成机器约束。

安装：

```bash
uv add --dev import-linter
```

优先使用：

```text
pyproject.toml
```

配置。

第一阶段至少建立：

```text
Domain Boundary
Domain Acyclic Dependency
Adapter / Plugin Boundary
```

但必须基于真实 import graph。

不要因为已有违规就：

```text
ignore everything
```

---

## 执行策略

Import Linter 通常较快，因此：

```text
Local Fast: YES
PR CI: YES
Nightly: 不重复
Release: 如果 PR Gate 已可靠，可不单独重复
```

Codex修改架构相关代码时执行：

```bash
uv run lint-imports
```

非架构修改无需机械重复执行多次。

---

# 6. Hypothesis

安装：

```bash
uv add --dev hypothesis
```

建立：

```text
dev
ci
exhaustive
```

三个 profile。

建议：

```text
dev:
50~100 examples

ci:
200~300 examples

exhaustive:
1000~2000 examples
```

实际数值根据运行时间调整。

---

## 必须新增真实 Property Tests

至少覆盖 3~5 个 OnlyAlpha invariant。

例如：

```text
serialization round-trip
canonicalization idempotency
quantity invariants
account/value invariants
execution state invariants
```

如果适合，再加入：

```text
RuleBasedStateMachine
```

---

## 执行策略

```text
Codex Local:
dev profile
只跑相关 property tests

PR CI:
ci profile

Nightly:
exhaustive profile

Release:
不再额外重复 exhaustive，
除非 Release 特别需要
```

避免：

```text
Codex 本地跑 2000 examples
+
PR 再跑
+
Nightly 再跑
```

---

# 7. Semgrep

建立：

```text
semgrep/
    onlyalpha.yml
```

至少考虑：

```text
Domain 禁止 wall clock
Domain 禁止隐式 random
Domain 禁止 os.getenv/os.environ
MiniQMT / xtquant 边界
```

必须：

```text
先扫描真实工程
→ 调整规则
→ 避免误报
```

同时增加 Semgrep rule tests。

---

## 执行策略

如果规则集很小：

```text
Local Fast:
只扫描 changed/relevant paths

PR CI:
完整扫描 src + packages

Nightly:
无需重复

Release:
无需再次重复
```

不要让 Codex每次：

```bash
semgrep 整仓库扫描
```

如果只修改了 docs。

---

# 8. CrossHair

安装：

```bash
uv add --dev crosshair-tool
```

只用于：

```text
纯 Domain
Value Object
pure calculation
deterministic state transition
```

不用于：

```text
MiniQMT
网络
文件系统
DB
Broker
```

建立：

```text
tests/formal/
```

至少实现 2~4 个真实 contract。

---

## 执行策略

CrossHair属于 **重型验证**。

因此：

```text
Codex Local:
默认不运行

PR CI:
默认不运行

Nightly:
运行

workflow_dispatch:
允许人工触发

Release:
只运行 critical contracts
```

如果某次任务专门修改 formal contract 对应核心函数：

Codex可以只运行：

```text
该 contract
```

而不是整个 CrossHair suite。

---

# 9. mutmut

安装：

```bash
uv add --dev mutmut
```

初始范围严格限制：

```text
src/onlyalpha/domain/
```

或进一步缩小。

只使用：

```text
unit
contract
```

作为 mutation 验证测试。

---

## 执行策略

Mutation Testing计算成本高。

必须：

```text
Codex Local:
NO

PR CI:
NO

Nightly:
YES

workflow_dispatch:
YES

Release:
critical subset only
```

第一阶段只建立 baseline：

```text
generated
killed
survived
timeout
```

不要立刻：

```text
mutation score < X
→ fail PR
```

---

# 10. Branch Coverage

配置：

```toml
[tool.coverage.run]
branch = true
```

统一输出：

```text
test-results/coverage/
```

扩展：

```text
scripts/test_suite.py
```

支持：

```bash
uv run python scripts/test_suite.py core-full --coverage
```

不要另建第二套测试 runner。

---

## 执行策略

Coverage 相比普通测试会增加一定开销。

所以：

```text
Codex Local:
默认不跑 full coverage

只在修改测试体系或 coverage 本身时运行

PR CI:
运行一次 branch coverage

Nightly:
不重复

Release:
如果 PR coverage 是完整基线，
无需再次重复
```

重要：

> 同一个 pytest suite 不应该为了普通测试和 coverage 无意义完整执行两遍。

如果可以合理合并：

```text
某个 PR lane
+
coverage
```

优先合并。

但不要让所有并行 lane 同时生成重复 coverage。

---

# 11. CodeQL

创建：

```text
.github/workflows/codeql.yml
```

使用当前 GitHub 官方推荐版本。

执行：

```text
pull_request
push master
schedule
workflow_dispatch
```

---

## 执行策略

CodeQL：

```text
Codex Local:
绝不执行

GitHub PR:
执行

Scheduled:
执行

Release:
不重复
```

Codex只负责：

```text
检查 workflow 配置
```

不尝试在本地安装完整 CodeQL CLI 来证明配置。

---

# 12. Dependabot + Dependency Review

建立：

```text
.github/dependabot.yml
```

确认当前 GitHub 对：

```text
uv
github-actions
pre-commit
```

的 ecosystem 支持。

更新频率：

```text
weekly
```

不要制造每日大量 dependency PR。

---

创建：

```text
.github/workflows/dependency-review.yml
```

初始：

```text
fail-on-severity: high
```

---

## 执行策略

```text
Codex Local:
NO

GitHub PR:
Dependency Review

GitHub scheduled:
Dependabot

Nightly:
NO

Release:
NO
```

---

# 13. pytest-benchmark

安装：

```bash
uv add --dev pytest-benchmark
```

复用：

```python
@pytest.mark.performance
```

至少建立 2~4 个真实 benchmark。

优先：

```text
canonical serialization
Domain event processing
execution projection
checkpoint encode/decode
```

要求：

```text
无网络
无真实 Broker
无外部状态
可重复
```

---

## 执行策略

```text
Codex Local:
只有修改性能关键路径时运行相关 benchmark

PR CI:
默认不跑完整 benchmark
可对 performance-critical PR 使用 workflow_dispatch / label

Nightly:
YES

Release:
YES 或 baseline compare
```

---

# 14. ASV

建立：

```text
asv.conf.json
benchmarks/
```

只保留：

```text
长期稳定
跨 commit 有意义
核心性能指标
```

的 benchmark。

不要把所有 pytest benchmark 原样复制到 ASV。

---

## 执行策略

ASV属于非常典型的重型工具：

```text
Codex Local:
只运行 asv check

PR:
默认不跑

Nightly:
运行代表性 benchmark

workflow_dispatch:
运行

Release:
运行关键 baseline compare
```

Codex完成配置后：

```bash
asv check
```

即可验证配置基本有效。

除非当前任务明确是 Performance 工作，否则不要：

```bash
asv run 大量历史 commit
```

---

# 15. GitHub Actions 重新分层

最终推荐：

```text
.github/workflows/

quality.yml
    ↓
PR 核心质量

codeql.yml
    ↓
GitHub static/security

dependency-review.yml
    ↓
供应链 Gate

nightly.yml
    ↓
重型质量检查

performance.yml（如确有必要）
    ↓
benchmark / ASV
```

不要为了每个工具新建一个 workflow。

优先按照职责合并。

---

# 16. quality.yml 推荐职责

```text
static
├── ruff
├── format
├── mypy
└── import-linter

semantic
└── semgrep

tests
├── fast + Hypothesis CI
├── integration
├── recovery
├── ashare
└── miniqmt-contract

coverage
└── branch coverage

build
└── package build

quality-gate
└── 汇总 blocking jobs
```

---

# 17. nightly.yml 推荐职责

```text
nightly

├── exhaustive
├── Hypothesis exhaustive
├── CrossHair
├── mutmut
└── performance
```

要求：

> 同一个测试不要因为不同工具被毫无必要地完整运行多次。

例如 mutmut自己会运行相关 tests，就不要在 mutation job 前再完整跑一次同样测试。

---

# 18. Codex 本地执行预算

这是本任务新增的重要要求。

Codex工作时分三种模式。

---

## Mode A：普通代码修改

只运行：

```text
Ruff changed files
mypy relevant module / core
relevant pytest
```

必要时：

```text
lint-imports
Semgrep relevant paths
```

不要运行：

```text
core-full
CrossHair all
mutmut
ASV
full coverage
CodeQL
```

---

# Mode B：质量基础设施修改

例如本任务本身。

允许执行：

```text
ruff
mypy
lint-imports
Semgrep
fast
selected integration
coverage once
CrossHair selected contracts
asv check
```

但：

```text
mutmut full
ASV historical run
CodeQL
Dependency Review
Nightly exhaustive
```

不需要本地完整执行。

配置正确后交给 GitHub。

---

# Mode C：Release / 专项验证任务

只有用户明确要求：

```text
release validation
performance regression
mutation audit
formal verification
```

时才执行对应重型任务。

---

# 19. Token 输出控制

执行命令时优先使用：

```text
-q
--tb=short
--maxfail=1
```

在合适场景减少无意义输出。

pytest：

```bash
pytest -q --tb=short
```

不要默认：

```text
-vv
-s
完整 traceback
```

除非 debugging 必须。

---

## Coverage

优先：

```text
摘要
```

不要把完整 HTML/JSON 输出给 Codex 阅读。

---

## mutmut

先看：

```text
summary
survivor count
```

只有需要分析 survivor 时，再查看具体 mutation。

---

## Git diff

开发中：

```bash
git diff --stat
git diff -- <changed-files>
```

最终才执行一次完整：

```bash
git diff
```

---

# 20. 不要重复运行成功的重型验证

如果：

```text
某命令已经在当前代码状态下成功
```

且之后没有修改相关文件：

不要再次运行。

例如：

```text
lint-imports PASS

之后只修改 docs
```

不要再：

```text
lint-imports
```

---

# 21. 缓存与增量能力

合理利用：

```text
uv cache
Ruff cache
mypy cache
pytest cache
mutmut cache
ASV result cache
GitHub Actions cache
```

如果当前 GitHub Actions / setup-uv 已经提供 cache：

不要再建立重复 cache。

不要提交：

```text
.coverage
htmlcov
.mutmut-cache
.benchmarks
.asv/env
.asv/results
```

除非项目明确需要版本化结果。

更新 `.gitignore`。

---

# 22. Pre-commit

Pre-commit 必须保持快速。

可以考虑：

```text
Import Linter
轻量 Semgrep
```

但只有在实际测量执行成本足够低时。

禁止加入：

```text
CrossHair
mutmut
full coverage
ASV
CodeQL
Hypothesis exhaustive
```

原则：

```text
git commit
```

不应该因为重型质量工具变成几分钟操作。

---

# 23. 文档

建立：

```text
docs/engineering/quality-toolchain.md
```

必须解释：

| Tool              | Purpose          |     Local | PR |    Nightly |  Release |
| ----------------- | ---------------- | --------: | -: | ---------: | -------: |
| Import Linter     | Architecture     |         ✓ |  ✓ |            |          |
| Hypothesis        | Properties       |       dev | ci | exhaustive |          |
| Semgrep           | Project rules    | selective |  ✓ |            |          |
| CrossHair         | Formal contracts | selective |    |          ✓ | critical |
| mutmut            | Test strength    |           |    |          ✓ | critical |
| Branch Coverage   | Test paths       |  optional |  ✓ |            |          |
| CodeQL            | Static/security  |           |  ✓ |  scheduled |          |
| Dependency Review | Supply chain     |           |  ✓ |            |          |
| pytest-benchmark  | Performance      | selective |    |          ✓ |        ✓ |
| ASV               | Historical perf  |     check |    |          ✓ |        ✓ |

明确告诉开发者：

```text
什么应该本地跑
什么不要本地跑
```

---

# 24. 本任务自己的验证策略

由于本任务修改质量基础设施，本次 Codex必须验证：

## 本地必须执行

```text
uv sync --all-packages --all-groups

ruff
mypy

lint-imports

Semgrep rule tests
Semgrep scan

新增 Hypothesis property tests

fast

至少相关 integration

Branch Coverage
仅执行一次完整 coverage baseline

CrossHair
仅执行新建/修改的 contract

pytest-benchmark
仅验证新增 benchmark 可执行

asv check

uv build --all-packages
```

---

## 本地不要求完整执行

```text
mutmut full mutation campaign

ASV historical benchmark suite

CodeQL

Dependency Review

Dependabot

Hypothesis exhaustive 全量

Nightly exhaustive

所有 GitHub Action 全量模拟
```

这些交给 GitHub。

---

# 25. mutmut 本次特殊处理

本任务必须确保：

```text
mutmut config 正确
command 可启动
target scope 正确
```

允许执行一个：

```text
非常小的 mutation target
```

验证集成。

不要为了证明 mutmut 可用，对整个 Domain 做完整 mutation campaign。

完整 baseline：

```text
GitHub Nightly
```

负责。

---

# 26. ASV 本次特殊处理

必须：

```bash
asv check
```

必要时运行一个：

```text
HEAD benchmark
```

确认环境正确。

不要：

```text
跑历史几十/几百 commit
```

---

# 27. Coverage 本次特殊处理

本次只运行：

```text
一次完整 baseline
```

记录：

```text
line coverage
branch coverage
```

如果后续只修改：

```text
workflow
docs
Semgrep rules
```

不要重新跑完整 coverage。

只有修改：

```text
Python production/test code
```

影响 baseline 时才重新运行。

---

# 28. CI 时间预算原则

设计 GitHub Actions 时注意：

```text
快速任务并行
重型任务 Nightly
避免同一 suite 重复执行
```

建议：

```text
PR 目标：
尽可能保持合理分钟级反馈

Nightly：
允许更长
```

不要因为工具数量从 5 个增加到 14 个，就让：

```text
PR total compute
```

无意义增长数倍。

---

# 29. Acceptance Criteria

## Architecture

* [ ] Import Linter 已安装
* [ ] 真实 architecture contracts
* [ ] 没有大量 ignore

## Property Testing

* [ ] Hypothesis profiles
* [ ] 3~5 个真实 property tests
* [ ] PR 使用 ci profile
* [ ] Nightly 使用 exhaustive profile

## Semantic Rules

* [ ] Semgrep rules
* [ ] rule tests
* [ ] PR blocking

## Formal Verification

* [ ] CrossHair contracts
* [ ] Nightly execution
* [ ] 不进入普通本地/PR重型路径

## Mutation

* [ ] mutmut 配置
* [ ] critical scope
* [ ] Nightly
* [ ] 不阻塞普通 PR

## Coverage

* [ ] branch coverage
* [ ] 一次真实 baseline
* [ ] PR regression protection
* [ ] 不重复完整 test suite

## Security

* [ ] CodeQL
* [ ] Dependency Review
* [ ] Dependabot

## Performance

* [ ] pytest-benchmark
* [ ] ASV
* [ ] Nightly/Release
* [ ] 不进入普通 PR 重型路径

## Efficiency

* [ ] pre-commit 未明显变慢
* [ ] Codex默认不运行重型工具
* [ ] Nightly承担 mutation/formal/performance
* [ ] 没有明显重复 CI
* [ ] GitHub workflow 职责清晰
* [ ] 文档明确 Local/PR/Nightly/Release 边界

---

# 30. 最终报告

任务结束后提供：

## A. Current State

说明原工程已有：

```text
Ruff
Mypy
pytest
CI lanes
pre-commit
```

---

## B. Changed Files

逐文件：

```text
path
purpose
change
```

---

## C. Tool Execution Matrix

必须输出：

| Tool | Local | PR | Nightly | Release |
| ---- | ----- | -- | ------- | ------- |

---

## D. Cost / Redundancy Decisions

专门说明：

```text
哪些重型任务没有进入 PR
为什么

哪些测试没有重复执行
为什么

哪些任务交给 Nightly
为什么
```

---

## E. Commands Actually Run

标记：

```text
PASS
FAIL
NOT RUN
CI ONLY
```

---

## F. Coverage Baseline

真实：

```text
line
branch
```

---

## G. Heavy Verification Status

例如：

```text
CrossHair selected contract: PASS
mutmut full: CI ONLY
CodeQL: CI ONLY
Dependency Review: CI ONLY
ASV historical: CI ONLY
```

---

## H. Remaining Issues

分：

```text
Critical
High
Medium
Low
Follow-up
```

---

## I. Final Verdict

只能：

```text
ACCEPTED
CONDITIONALLY_ACCEPTED
REJECTED
```

---

# 31. 最后 Diff Review

最终只执行一次：

```bash
git status --short
git diff --stat
git diff
```

确认：

```text
没有业务 scope creep
没有大规模 ignore
没有缓存文件
没有 coverage 生成物
没有 mutation 生成物
没有 benchmark cache
没有机器绝对路径
没有降低 strict mypy
没有降低现有测试 Gate
没有重复质量框架
```

---

# 32. 最终目标

本任务最终形成的不是：

```text
更多工具
+
更多测试
+
更多 CI
+
更多 Token
```

而应该形成：

```text
更强 Architecture
+
更强 Property Verification
+
更强 Static Rules
+
更强 Test Strength
+
更强 Security
+
更强 Performance Regression Protection

同时：

更少人工重复检查
+
更少 Codex 无意义执行
+
更少重复 CI
+
更低 Token 消耗
```

核心原则：

> **Fast checks close to the developer. Heavy checks belong to CI.**

> **Run the cheapest test that can disprove correctness first.**

> **Do not run the same expensive verification twice unless the relevant code changed.**

> **Codex 的 Token 应优先用于理解、设计、实现和分析失败，而不是等待并阅读重复测试输出。**

现在开始：先完成 Current-State Audit，然后按照：

```text
Phase A
Import Linter
Branch Coverage
Hypothesis

Phase B
Semgrep
Dependabot
Dependency Review
CodeQL

Phase C
CrossHair
mutmut

Phase D
pytest-benchmark
ASV

Phase E
CI 分层
Nightly 分层
Pre-commit
Documentation
Final Verification
```

逐阶段实施。

每完成一个 Phase，只运行该 Phase 所需的最小验证集。

不要在每个 Phase 后执行整个 Release Suite。

完整回归交给最终必要验证和 GitHub CI。
