# OnlyAlpha — Project State Authority Static Closure

## 0. 任务性质

这是一次 **focused correctness / engineering closure**。

当前主线已经完成 P9.K.5 核心功能修复以及 Project State Authority 的架构收敛，但最新收敛审计发现：

```text
scripts/project_state.py

from typing import Mapping, Sequence
```

违反当前 Ruff 规则：

```text
UP035
Import from collections.abc instead:
Mapping, Sequence
```

导致 canonical static job 在：

```bash
uv run ruff check src tests examples packages scripts
```

阶段失败。

当前已知 CI 事实：

```text
architecture                PASS
build                       PASS
openapi-contract            PASS
web                         PASS
research-command            PASS
research-product-closure    PASS
research-postgres functional tests = 98 PASS
CodeQL                      PASS
Semgrep                     PASS
dependency audit            PASS

static                      FAIL
    └── Ruff UP035

research-postgres coverage
    functional tests = PASS
    coverage = 80.62% < 82%
```

必须严格区分：

```text
Ruff static failure
=
当前 Task Gate 真实工程缺口

Coverage threshold failure
=
higher-level coverage evidence OPEN / FAIL
!= 当前 Task functional correctness failure
```

不要重新打开已经冻结的 Functional Correctness / Coverage Evidence Separation 规则。

---

# 1. 第一性原理目标

不要把任务理解成：

```text
把 typing 改成 collections.abc
```

这只是直接症状。

需要回答两个问题。

## 1.1 代码层

为什么当前代码不满足仓库自己的 Python static contract？

应恢复：

```text
Changed Python code
→ satisfies repository canonical static rules
```

---

## 1.2 工程闭环层

Project State Authority Closure 的目的本身是：

```text
One engineering fact
→ One authority
→ deterministic projections
→ fail closed
```

但一个工程任务只有在它自己的 required Task Gate evidence 完成后，才应该被认为真正闭环。

因此还要确认：

```text
新增/修改 Python engineering tooling
→ Task Impact Scope 包含对应 static verification
→ Task closure 前 static evidence 必须 PASS
```

如果仓库现有质量体系已经能够表达并机械检查这一规则：

**不要创建第二套规则。**

只需要补齐遗漏的实现/验证。

如果现有机制确实存在一个明确缺口，使得类似 Python engineering script 可以持续绕过对应 Task-level static verification，才允许进行最小修复。

---

# 2. 当前基线

首先重新读取仓库，禁止假设历史 SHA 仍是当前 HEAD。

执行：

```bash
git status --short
git rev-parse HEAD
git log -1 --oneline
```

记录：

```text
TASK_BASE_SHA=<current exact master SHA>
```

历史审计时 master 曾为：

```text
85a944933017e4c4e740c7ddc2588b4752ee0263
```

但这只是历史线索。

**以执行时当前仓库事实为准。**

---

# 3. 必须优先阅读

开始修改前读取：

```text
AGENTS.md

docs/engineering/quality-system.md
docs/engineering/convergent-audit-policy.md
docs/engineering/project-state-authority.md

project-state.toml

scripts/project_state.py
tests/architecture/test_project_state_authority.py

scripts/test_suite.py
scripts/verify.py          # 如果存在
pyproject.toml

.github/workflows/*
```

只读取与本任务相关的部分即可，不要无条件展开整个仓库。

特别确认：

1. Task Gate 对 Ruff / Format / Mypy / Import Linter 的现有要求；
2. `scripts/` 是否已经属于 canonical Ruff scope；
3. Project State Authority 是否已经有独立 check；
4. 当前 static workflow 如何执行；
5. 是否已经存在本地快速验证入口；
6. 是否真的存在 verification infrastructure 缺口。

---

# 4. 冻结本次 Invariants

修改前先写出并遵守以下 invariant。

## INV-PSA-001 — Single Project State Authority

```text
Current engineering state
→ project-state.toml
→ sole authoring authority
```

不得新增第二个状态文件。

---

## INV-PSA-002 — Deterministic Projection

```text
project-state.toml
→ deterministic render
→ README / roadmap / P9.K plan
```

同一 authority 输入必须产生完全相同投影。

---

## INV-PSA-003 — Projection Drift Fail Closed

```text
projection != render(authority)
→ check FAIL
```

不得弱化现有 architecture guard。

---

## INV-PSA-004 — Guarded Transition

```text
only authorized next increment may start

only active increment may be verified
```

非法 transition 必须 fail closed。

---

## INV-QUALITY-001 — Changed Python Code Must Satisfy Static Contract

对于本任务 Impact Scope：

```text
changed Python source/test/script
→ applicable Ruff / Format / typing checks PASS
```

不能在已知 static failure 的情况下声明 Task Closure 完成。

---

## INV-QUALITY-002 — Functional Evidence != Coverage Evidence

继续保持：

```text
functional test PASS
+
coverage threshold FAIL

=

functional correctness PASS
+
coverage evidence FAIL / OPEN
```

禁止为了本任务：

- 降低 coverage threshold；
- 增加 `pragma: no cover`；
- 删除测试；
- 缩小 coverage source；
- 修改 Coverage / Task / Phase / Certification Gate 语义。

---

## INV-QUALITY-003 — Minimum Sufficient Mechanism

根因修复优先顺序：

```text
fix concrete defect
→ prove with existing mechanism
→ only if a real verification gap exists, minimally close that gap
```

禁止：

```text
new quality framework
new Gate
new generic workflow engine
large CI rewrite
repository restructure
```

---

# 5. Phase A — 修复直接静态缺陷

当前已知错误：

```python
from typing import Mapping, Sequence
```

应使用 Python 3.12 / Ruff 当前要求的：

```python
from collections.abc import Mapping, Sequence
```

只修改必要 import。

不要因为这一行：

- 重构整个 `project_state.py`；
- 改 dataclass；
- 改 transition API；
- 改 TOML schema；
- 改 projection format；
- 改 CLI contract。

---

# 6. Phase B — 验证真正根因

不要直接假设还需要修改 CI。

检查以下链路：

```text
new scripts/project_state.py
        ↓
repository static scope
        ↓
ruff check src tests examples packages scripts
        ↓
Ruff correctly detected defect
```

如果这条链已经成立，则说明：

```text
static detection mechanism本身没有缺失
```

此时真正的问题是：

```text
Task Closure / merge 发生在 required static evidence 未确认 PASS 之前
```

这种情况下：

**不要复制一套新的 static checker。**

优先确认仓库是否已经有快速本地入口，可以在 Task Closure 前执行：

```text
Ruff
Format
relevant tests
project-state check
```

如果已有，例如：

```text
scripts/verify.py
现有 Task Gate helper
pre-commit
```

则只需要使用并在适当工程文档中明确 Project State Authority 修改必须消费现有 Task-level static evidence。

不要创建平行机制。

---

# 7. 只有存在真实机制缺口时才允许新增修改

只有在代码证据证明：

```text
Project State Authority changes
无法通过现有快速 Task Gate tooling
机械触发 project-state check / applicable static check
```

时，才允许进行最小补充。

优先顺序：

## Option A — 复用现有验证入口

如果已有 `scripts/verify.py` / Task Gate verification planner：

把：

```text
project-state.toml
scripts/project_state.py
README project-state projection
roadmap project-state projection
P9.K progress projection
tests/architecture/test_project_state_authority.py
```

纳入其现有 Impact Scope 规则。

期望：

```text
Project State Authority touched
→ fast project-state consistency check
→ relevant Ruff/Format
→ targeted architecture test
```

不要自动触发 full repository CI。

---

## Option B — 若现有入口完全不适用

只允许增加一个非常薄的 reuse layer，例如让现有 verification script 调用：

```bash
uv run python scripts/project_state.py check
```

而不是创建：

```text
scripts/project_state_verify_v2.py
new Task Gate
new workflow
new framework
```

---

# 8. 不要错误解决“PR 被合并”问题

本任务是 repository engineering closure。

不要擅自通过代码：

```text
实现 GitHub branch protection manager
实现 GitHub API workflow controller
新增 bot
新增 merge queue framework
```

GitHub branch protection / repository settings 属于仓库托管策略，不应因为一个 Ruff defect在源码层过度设计。

如果你确认：

```text
Repository currently permits merge despite failing static checks
```

可以在最终报告中单独记录：

```text
Operational repository-setting recommendation
```

但除非仓库已有声明式 ruleset 配置并且本 Task 明确属于其维护范围，否则不要修改外部 GitHub repository settings。

---

# 9. Project State 当前语义不得被错误推进

本次任务不是开始 P9.K.6。

因此不要执行：

```bash
python scripts/project_state.py transition start P9.K.6
```

本次任务完成后仍应保持：

```text
last_verified_increment = P9.K.5
active_increment = ""
next_authorized_increment = P9.K.6
next_authorized_state = IMPLEMENTATION READY
```

除非当前 repository truth 已经被其他正式提交改变。

如果执行时主线已经合法开始 K6，则尊重当前 authority，不要回退状态。

---

# 10. Tests

至少验证 Project State Authority 当前已有测试仍成立：

```bash
uv run pytest tests/architecture/test_project_state_authority.py -q
```

必须证明：

```text
authority valid
projection exact
render idempotent
unauthorized start fails
non-active verify fails
legal transition deterministic
```

不要为了提高 Coverage 百分比增加无语义测试。

---

# 11. Task-level Static Verification

本次修复的核心 acceptance 必须包含：

```bash
uv run ruff check \
  scripts/project_state.py \
  tests/architecture/test_project_state_authority.py
```

然后：

```bash
uv run ruff format --check \
  scripts/project_state.py \
  tests/architecture/test_project_state_authority.py
```

如果仓库现有 Task-level规则要求扩大到 canonical static scope，则执行：

```bash
uv run ruff check src tests examples packages scripts
```

以及相应 format check。

不要仅运行：

```text
ruff check scripts/project_state.py
```

然后在 canonical static 仍然失败时声称完成。

---

# 12. Project State Verification

必须执行：

```bash
uv run python scripts/project_state.py check
```

预期：

```text
Project state authority and projections are consistent.
```

如果失败：

```text
不要手改 projection 使测试通过
```

必须：

```text
修改 authority
或修复 renderer
→ render
→ check
```

遵守 single-authority 原则。

---

# 13. Architecture Verification

执行：

```bash
uv run python scripts/test_suite.py architecture
```

当前上一轮证据显示该 lane 已经恢复 PASS。

本任务不得引入新的 architecture regression。

---

# 14. Version / Diff Integrity

执行：

```bash
uv run python scripts/version_sync.py check
git diff --check
```

本 Task 不创建新产品 Increment，因此通常：

```text
version remains 0.9.5
```

不要因为一次 engineering closure 擅自升版本，除非当前正式工程规则明确要求。

---

# 15. 不需要重新执行的重型验证

如果本次实际 production diff 仅限：

```text
scripts/project_state.py
相关 engineering verification/docs/tests
```

则默认不要求：

```text
research-postgres
research-product-closure
full Web E2E
full recovery
full release
full coverage
Final-SHA Certification
```

因为这些并不属于本次代码 Impact Scope。

上一轮真实 PostgreSQL functional tests 已经 PASS，本 Task 没有修改 persistence semantics。

不要浪费时间和 token 重跑无关重型验证。

---

# 16. Coverage 处理要求

如果远程 CI 仍报告：

```text
research-postgres functional tests: PASS
coverage: 80.62% < 82%
```

最终报告必须写成：

```text
PostgreSQL functional correctness: PASS
Coverage evidence: FAIL / OPEN at applicable higher-level gate
```

不得写成：

```text
Task functional correctness failed
```

也不得为了让 CI 变绿修改 Coverage policy。

---

# 17. Finding Closure

上一轮 finding：

```text
F-PSA-001
Project State script Ruff violation

Severity: MAJOR
Classification: INTRODUCED_BY_FIX
```

只有满足：

```text
Ruff PASS
+
Format PASS
+
Project State check PASS
+
targeted architecture tests PASS
+
canonical architecture lane PASS
```

才能标记：

```text
F-PSA-001 = RESOLVED
```

如果任何必要 Task-level static evidence仍失败：

```text
F-PSA-001 = NOT_RESOLVED
```

不要通过修改文档状态规避 finding。

---

# 18. 重新进行 focused convergent audit

修改完成后，严格按照：

```text
docs/engineering/convergent-audit-policy.md
```

做一次 focused re-audit。

Scope 只包括：

```text
Project State Authority Closure
+
本次 static closure
```

不要无理由重新扫描未来 P9.K.6 功能。

重新确认：

```text
BLOCKER
MAJOR
MINOR
SUGGESTION
```

停止条件：

```text
BLOCKER = 0
MAJOR = 0
Applicable invariants = PASS
Required Task Gate evidence sufficient
```

满足后必须停止继续找 optional improvement。

---

# 19. GO / NO-GO

如果：

```text
F-PSA-001 RESOLVED

BLOCKER = 0
MAJOR = 0

Project State authority PASS
Projection determinism PASS
Transition fail-closed PASS
Task static PASS
Architecture PASS
```

则结论必须：

```text
GO
```

并明确：

```text
P9.K.5 Task Closure complete
Project State Authority Closure complete
P9.K.6 External Client Migration may begin
```

注意：

```text
GO
!= Final-SHA Certified
```

不要声称 P9.K.5 或当前 master 已完成 Final-SHA Certification，除非正式 Certification workflow 真的完成。

---

# 20. 最终报告格式

完成后输出：

## 1. Exact Baseline

```text
TASK_BASE_SHA
FINAL_HEAD_SHA
```

## 2. Root Cause

区分：

```text
direct defect
process/verification cause
whether existing guard already detected it
```

## 3. Files Changed

逐文件说明为什么修改。

## 4. Invariant Matrix

| Invariant | Status | Evidence |
|---|---|---|
| Project State single authority | PASS/FAIL | ... |
| deterministic projection | PASS/FAIL | ... |
| transition fail closed | PASS/FAIL | ... |
| Task static contract | PASS/FAIL | ... |
| architecture consistency | PASS/FAIL | ... |

## 5. Verification

列出实际执行命令和结果。

## 6. Finding Status

```text
F-PSA-001 = RESOLVED / NOT_RESOLVED
```

## 7. Coverage Status

明确：

```text
functional correctness
!=
coverage evidence
```

## 8. Verdict

只允许：

```text
GO
```

或：

```text
NO-GO
```

---

# 21. 禁止事项

禁止：

- 为一个 Ruff 错误重构整个 `project_state.py`；
- 新增第四种 Gate；
- 新建平行质量框架；
- 修改 coverage threshold；
- 加 `pragma: no cover`；
- 删除现有 static rule；
- Ruff ignore `UP035`；
- 把 `scripts/` 从 lint scope 排除；
- 删除 architecture test；
- 弱化 Project State projection consistency；
- 新增第二 Project State authority；
- 提前开始 P9.K.6；
- 修改 Product Command / ResearchRun / Strategy / Worker semantics；
- 修改 PostgreSQL schema；
- 修改 OpenAPI contract；
- 无理由运行完整 Final-SHA Certification。

---

# 22. 最终原则

这次任务真正要关闭的是：

```text
代码正确
但没有完成它自己必须通过的 Task-level engineering evidence
```

正确闭环应是：

```text
Change
↓
Impact-aware functional / invariant verification
↓
Applicable static verification
↓
Architecture verification
↓
Task Gate complete
↓
Project State may truthfully advance
```

而不是：

```text
Change
↓
文档先写 COMPLETE
↓
远程 CI 后来发现基础 static defect
```

必须从第一性原理保证：

> **Engineering state 只能描述已经被现有工程证据证明的事实。**

但同时坚持：

> **不要因为一次流程遗漏重新发明整个工程质量体系；优先复用现有 Gate、现有 static tooling 和现有 Project State Authority，用最小充分机制关闭真实缺口。**