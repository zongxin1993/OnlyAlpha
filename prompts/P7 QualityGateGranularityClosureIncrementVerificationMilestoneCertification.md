# OnlyAlpha Codex Prompt

## P7 Quality Gate Granularity Closure
### Increment Verification vs Milestone Certification

Repository:

https://github.com/zongxin1993/OnlyAlpha

---

# 0. 任务定位

你正在修改 OnlyAlpha。

本任务不是新的产品功能阶段，也不是 P7.5.3。

本任务是一个极小的 Engineering Governance Closure：

> **P7 Quality Gate Granularity Closure — Increment Verification vs Milestone Certification**

目标是修正当前质量制度中的粒度问题：

```text
当前旧规则：
每个 P7.x 都倾向要求 ACCEPTED
→ ACCEPTED 又要求 Final-SHA Certification
→ 每个小 increment 都重复 full repository certification
```

改为：

```text
P7.x Implementation Increment
→ VERIFIED
→ 可继续下一个 P7.x

P7 Major Milestone Final Closure
→ exact immutable SHA
→ one full Final-SHA Certification
→ ACCEPTED
→ 才允许进入 P8
```

核心目标：

> **保持 Final-SHA Certification 的严格程度完全不变，但把它放到真正有价值的 Milestone boundary，减少 P7.x 之间无意义的重复全量校验、CI 时间、pytest 日志和 Agent token 消耗。**

---

# 1. 第一原则

本 Closure 必须同时满足：

```text
Less redundant verification
≠
Less correctness
```

以及：

```text
Faster development
≠
Weaker certification
```

最终要得到：

```text
Increment Verification
        ↓
fast / impact-aware / evidence-based
        ↓
VERIFIED
        ↓
next P7.x
```

以及：

```text
P7 Final Closure
        ↓
full repository proof
        ↓
Final-SHA Certification
        ↓
ACCEPTED
```

---

# 2. 当前问题的根因

OnlyAlpha 当前已有：

```text
IMPLEMENTED
VERIFIED
CERTIFIED / ACCEPTED
```

以及 Final-SHA Certification authority。

但现有文档中的阶段规则过于粗：

```text
只有 ACCEPTED 才默认允许进入下一阶段
```

没有区分：

```text
Major Milestone
```

和：

```text
Implementation Increment
```

因此出现循环：

```text
P7.5.2
→ 没有 Final-SHA artifact
→ 不能 ACCEPTED
→ P7.6 Entry Gate 阻塞
```

即使 P7.5.2 已经：

```text
implementation complete
tests PASS
Layered Quality PASS
architecture invariants PASS
review complete
```

仍被要求再次 full certification。

这是 governance granularity 问题，不是 Research / Runtime correctness 问题。

---

# 3. 本任务的核心决策

必须正式建立两个层级：

## 3.1 Implementation Increment

例如：

```text
P7.4
P7.5
P7.5.1
P7.5.2
P7.6
P7.7
```

属于：

```text
P7 Implementation Increment
```

默认状态建议：

```text
PLANNED
IMPLEMENTED
VERIFIED
BLOCKED
```

进入下一个同 Milestone increment 的条件：

```text
previous increment = VERIFIED
```

不要求：

```text
previous increment = ACCEPTED
```

不要求每个 increment 独立：

```text
Final-SHA Certification
```

---

## 3.2 Major Milestone

例如：

```text
P6
P7
P8
```

状态建议：

```text
IN_PROGRESS
CONDITIONALLY_ACCEPTED
ACCEPTED
REJECTED
```

跨 Major Milestone：

```text
P7 → P8
```

必须：

```text
P7 Final Closure
+
exact immutable SHA
+
Final-SHA Certification
+
verdict = ACCEPTED
```

---

# 4. 正式质量规则

更新 Repository 后，必须清楚表达：

```text
P6 → P7
requires P6 = ACCEPTED
```

```text
P7.5 → P7.6
requires P7.5 = VERIFIED
```

```text
P7.6 → P7.7
requires P7.6 = VERIFIED
```

```text
P7 → P8
requires P7 = ACCEPTED
```

一句话规则：

> **Major Milestone requires ACCEPTED; increment inside the same Milestone requires VERIFIED.**

---

# 5. Final-SHA Certification 的新默认粒度

Final-SHA Certification 继续是：

> **Repository 唯一正式 exact immutable SHA final certification authority。**

它的 mandatory gates、coverage、Semgrep、CodeQL、build、exact-SHA verification、fail-closed verdict：

```text
全部保持不变
```

但是默认执行时机改成：

```text
Major Milestone Final Closure
```

而不是：

```text
every implementation increment
```

对于 P7：

```text
P7.0
P7.1
P7.2
...
P7.6
P7.7
...
↓
P7 Final Closure
↓
one final immutable SHA
↓
full Final-SHA Certification
↓
P7 = ACCEPTED
```

---

# 6. Explicit Certification Checkpoint 例外

不要把规则写成：

```text
P7 内绝对禁止中间 certification
```

中间 Final-SHA Certification 仍然允许，但必须是：

```text
explicit certification checkpoint
```

只有出现真正高风险或 release boundary 时才建议使用，例如：

```text
release / tag
Live deployment
major persistence migration
major Runtime / Recovery authority refactor
known nondeterminism incident closure
high-risk architecture baseline freeze
long-running milestone intermediate freeze
```

普通：

```text
DTO
Research feature
Parameter Sweep
Statistics
small tooling increment
```

默认不需要。

---

# 7. P7.x VERIFIED 的正式条件

一个 P7.x increment 达到 VERIFIED，至少要求：

```text
implementation complete
required targeted tests PASS
affected canonical lanes PASS
architecture invariants PASS
impact-aware local verification PASS
Layered Quality PASS where applicable
independent review complete
no unresolved Critical / High
documentation current enough to understand the increment
```

注意：

```text
VERIFIED
```

不是：

```text
CERTIFIED
ACCEPTED
```

不得混用。

---

# 8. 本 Closure 自身的 Entry / Exit 规则

这个 Closure 自己属于：

```text
P7 internal engineering-governance increment
```

它不要求先取得：

```text
00f98d2... Final-SHA Certification
```

否则会形成逻辑循环：

```text
要修改“P7.x 不需要 certification”的规则
↓
却要求先为这个规则修改做 certification
```

本 Closure 完成时只需要：

```text
VERIFIED
```

不需要：

```text
standalone Final-SHA Certification
```

---

# 9. Scope

本任务只允许处理：

```text
quality gate granularity
increment vs milestone semantics
Agent verification guidance
roadmap stage-entry wording
current documentation drift directly related to this rule
```

优先只修改：

```text
docs/engineering/quality-system.md
AGENTS.md
docs/roadmap.md
README.md
```

如果当前 Repository 中还有其它直接定义：

```text
P7.x must be ACCEPTED before next P7.x
```

的正式文档，也应同步。

---

# 10. 默认不修改 Production Code

本任务默认不修改：

```text
src/onlyalpha/**
packages/**
Runtime
Research
Calculation
Dataset
Result
Job
Factor
Strategy
```

因为本任务不是产品语义变更。

如果 Repository 审计发现某个 tooling code 明确硬编码了旧的：

```text
increment requires ACCEPTED
```

规则，才允许最小修改对应 tooling。

不要趁机重构。

---

# 11. 默认不修改 Final-SHA Certification Workflow

除非 current workflow 本身错误地：

```text
自动在每个 P7.x 强制触发
```

否则不要修改：

```text
.github/workflows/certification.yml
scripts/certification.py
```

Final-SHA Certification 的：

```text
mandatory gates
coverage
Semgrep
CodeQL
build
exact SHA
verdict
```

全部保持不变。

本任务改变的是：

```text
WHEN certification is required
```

不是：

```text
WHAT certification verifies
```

---

# 12. Repository Truth Refresh

开始前先执行：

```bash
git status --short
git log -1 --oneline
git rev-parse HEAD
git branch --show-current
```

然后只读审计：

```text
docs/engineering/quality-system.md
AGENTS.md
docs/roadmap.md
README.md
```

再搜索 Repository 中与以下关键词相关的正式规则：

```text
ACCEPTED
VERIFIED
Final-SHA Certification
next stage
next increment
P7.6
P7.5.2
Entry Gate
```

目标是找出：

```text
所有会继续导致 P7.x 被 ACCEPTED gate 阻塞的 current-truth 文本
```

不要无目的阅读整个仓库。

---

# 13. 严格限制 Repository Reading Scope

本任务不是架构重审。

除非发现规则冲突，否则不要重新完整阅读：

```text
all Runtime code
all Research code
all tests
all plugins
```

允许读取的最小集合：

```text
quality-system
AGENTS
roadmap
README
verify/test/certification tooling only if necessary
related policy tests only if necessary
```

目标：

> **减少无意义文件读取和 Agent token 消耗。**

---

# 14. Verification Efficiency Contract

这是本任务的硬要求。

不要在 docs/governance-only change 上运行无关 Runtime suites。

验证必须遵循：

```text
smallest correct verification set
```

而不是：

```text
largest available verification set
```

---

# 15. Docs-Only 情况

如果最终只修改：

```text
*.md
```

且没有改：

```text
scripts/**
.github/workflows/**
pyproject.toml
tests/**
src/**
packages/**
```

则默认禁止运行：

```text
core-full
recovery
sim-recovery
research-factor
research-job
research-calculation
research-dataset
calculation
ashare
miniqmt-contract
release
coverage
```

原因：

> 这些 Runtime / Research execution tests 不能为纯治理文档变更增加有效 correctness evidence。

---

# 16. Docs-Only 最低验证

如果是纯 Markdown / governance closure，最低验证应是：

```text
git diff --check
```

加上 Repository 已存在的：

```text
docs lint
policy consistency test
architecture policy test
```

如果这些工具真实存在。

不要为了“看起来更严格”发明新的 full test requirement。

如果没有 docs lint：

```text
do not invent a heavyweight replacement
```

---

# 17. 如果修改了 Policy Tests

如果为了冻结新规则新增/修改：

```text
tests/... quality policy tests
```

则运行：

```text
only targeted policy tests
```

然后必要时：

```text
fast / architecture
```

但不要自动升级到：

```text
core-full
recovery
release
```

除非 test infrastructure 本身被修改。

---

# 18. 如果修改了 `scripts/verify.py`

只有发现 tooling 硬编码旧阶段规则时才允许修改。

若修改：

```text
scripts/verify.py
```

则执行：

```text
targeted verify tests
+
required verification-tooling tests
```

并按 P7.5.2 self-change rules 决定是否需要 broader local proof。

但是：

> 不要因为本 Closure 理论上“和 verification 有关”，就无理由修改 verify.py。

---

# 19. 如果修改了 `scripts/test_suite.py` / Workflow

默认不要修改。

如果 current truth 证明不得不改：

```text
scripts/test_suite.py
.github/workflows/quality.yml
.github/workflows/certification.yml
```

则必须说明：

```text
为什么仅文档无法完成治理 closure
```

并按照 verification-infrastructure self-change 规则扩大验证。

否则这是 scope violation。

---

# 20. 禁止 `release` 作为默认 Closure Gate

本任务默认禁止：

```bash
uv run python scripts/test_suite.py release
```

原因：

```text
governance docs change
≠
full Runtime release candidate
```

只有实际修改了：

```text
test lane authority
certification infrastructure
build configuration
```

且 impact policy 要求时，才运行。

---

# 21. 禁止 Coverage

纯 governance closure 不运行：

```text
coverage
```

Coverage 只证明 executable code line/branch execution，不能证明质量制度文字正确。

如果没有 production/tooling code change：

```text
coverage = meaningless
```

---

# 22. 禁止 Runtime Recovery Tests

本任务默认禁止：

```text
recovery
sim-recovery
core-full
```

因为它不改变：

```text
Runtime
Recovery
Durable Trading
```

运行这些 test 只是增加：

```text
wall-clock
CI cost
Agent token
pytest log
```

而不增加有效 evidence。

---

# 23. 成功日志必须 Compact

所有验证命令默认：

```text
quiet / compact output
```

成功时 Agent 只需要记录：

```text
command
exit code
short summary
```

不要把完整 PASS log 放进 context。

例如：

```text
PASS git diff --check
PASS targeted policy tests: 8 passed
```

足够。

---

# 24. 失败时才读取详细日志

只有失败才读取：

```text
failed node id
short traceback
relevant assertion
```

推荐：

```text
-q
--tb=short
--maxfail=1
```

按适用情况使用。

不要一次加载：

```text
hundreds of unrelated failures
full stdout
large durations report
```

---

# 25. Full Logs 落盘而非进入 Context

如果工具产生长输出：

```text
redirect to test-results/
```

成功只读取 summary。

失败再按需：

```text
tail
grep FAILED
read bounded section
```

目标：

> **保留 evidence，不把 evidence 全部塞入 Agent context。**

---

# 26. 禁止高频 CI Polling

如果 Layered Quality 被触发：

```text
do not repeatedly poll every few seconds
```

本 Closure 默认也不需要等待远端 full CI 才能完成本地治理修改。

如果已有 CI 状态需要引用：

```text
query once when materially necessary
```

不要 token-watch workflow。

---

# 27. Layered Quality 的使用

如果当前 repository policy 对 docs-only push 会自动运行 Layered Quality：

不要为了本任务额外手动重复同样 full checks。

本地只做：

```text
smallest correct evidence
```

远端 CI 是：

```text
development evidence
```

不要把 local + remote 相同 suite 重复跑两遍，除非 failure diagnosis 需要。

---

# 28. Final-SHA Certification 与本 Closure

默认：

```text
Standalone Closure Final-SHA Certification:
NOT REQUIRED
```

理由：

```text
this is an internal P7 governance increment
```

它只需要达到：

```text
VERIFIED
```

整个 P7 最终：

```text
P7 Final Closure
→ one full Final-SHA Certification
```

仍然必须执行。

---

# 29. 必须更新的 Quality System 语义

`docs/engineering/quality-system.md` 应清楚表达：

## Increment

```text
Implementation Increment:
PLANNED
IMPLEMENTED
VERIFIED
BLOCKED
```

进入同一 Major Milestone 下一个 increment：

```text
previous increment must be VERIFIED
```

## Milestone

```text
Major Milestone:
IN_PROGRESS
CONDITIONALLY_ACCEPTED
ACCEPTED
REJECTED
```

进入下一个 Major Milestone：

```text
previous Milestone must be ACCEPTED
```

---

# 30. 修改旧规则

所有类似：

```text
只有 ACCEPTED 才默认允许进入下一阶段
```

必须消除歧义。

推荐改成：

> **只有 ACCEPTED 的 Major Milestone 才默认允许进入下一个 Major Milestone；同一 Major Milestone 内的 implementation increment，在达到 VERIFIED 后即可进入下一个 increment。**

---

# 31. Certification Authority 文字必须保留

不要删掉：

```text
Final-SHA Certification is unique final certification authority
```

而应明确：

```text
unique authority
≠
required after every increment
```

它的 authority 不变，只调整 default cadence。

---

# 32. `VERIFIED` 的权威边界

文档必须避免把 VERIFIED 写成模糊“本地跑过几个测试”。

至少要求：

```text
required implementation complete
targeted / affected tests PASS
architecture invariants PASS
impact-aware verification PASS
Layered Quality where applicable
independent review complete
no Critical / High
```

这样不是降低标准。

---

# 33. `ACCEPTED` 的权威边界

ACCEPTED 继续只能来自：

```text
Major Milestone Final Closure
+
exact immutable SHA
+
Final-SHA Certification artifact
```

或者：

```text
explicit certification checkpoint
```

不能让普通 local/Layered Quality 冒充 ACCEPTED。

---

# 34. Roadmap 更新

`docs/roadmap.md` 必须修复类似：

```text
P7.5.2 没有 Final-SHA artifact，所以不能进入 P7.6
```

这种 current-truth blocker。

改为：

```text
P7.5.2 VERIFIED
→ P7.6 may start
```

如果 P7.5.2 当前证据不足以 VERIFIED，则准确写出缺什么。

不要虚构 PASS。

---

# 35. README 更新

README 只需要同步：

```text
P7 increment vs milestone quality semantics
```

以及当前已有的直接相关 drift。

不要借本任务大规模重写 README。

如果还存在已经明确过期的：

```text
official Factor plugin intentionally empty
Factor Research not implemented
```

且能低成本修正，可以一并关闭。

---

# 36. AGENTS.md 更新

必须明确告诉后续 Codex：

```text
P7.x Entry Gate = previous increment VERIFIED
```

而不是：

```text
previous increment Final-SHA ACCEPTED
```

并加入：

```text
Do not run Final-SHA Certification after every P7.x by default.
```

同时明确：

```text
Final-SHA Certification remains mandatory at P7 Final Closure.
```

---

# 37. Agent Test / Token Efficiency 规则

建议在 AGENTS 或 quality-system 中保留/强化：

```text
Inner loop:
targeted tests only

Increment closure:
affected canonical lanes + impact-aware verification

Milestone closure:
full Final-SHA Certification
```

并明确：

```text
successful long-running logs should remain out of Agent context by default
```

---

# 38. 不新增复杂治理对象

不要新增：

```text
Milestone DB
Stage Registry DB
Certification Scheduler
Policy Engine
YAML state machine
Release database
```

这只是文档/治理规则。

优先：

```text
clear Markdown contract
existing tooling
existing status vocabulary
```

---

# 39. 不要改 Product Version

本 Closure 默认不需要：

```text
version bump
```

除非 Repository 现有 release policy 明确要求任何 commit 都 bump。

不要为治理文档制造无意义 package release。

---

# 40. 不要新增 Runtime Test Lane

本任务不应新增：

```text
quality-granularity runtime lane
```

如果需要长期自动化验证，优先：

```text
small policy/architecture test
```

而不是创建新的 heavyweight canonical lane。

---

# 41. 如果需要 Policy Test

可以增加一个小型 test，验证：

```text
quality-system 中 increment/milestone 关键规则存在
```

或者验证某个 machine-readable contract。

但不要写：

```text
fragile full Markdown exact snapshot
```

也不要测试所有文字标点。

若纯文档 contract 已足够，不强制新增 test。

---

# 42. Verification Plan 输出

Codex 在修改前先输出最小 verification plan：

例如 docs-only：

```text
Change classification: GOVERNANCE_DOCS_ONLY

Required:
- git diff --check
- targeted policy/doc check if present

Not required:
- calculation
- research-*
- core-full
- recovery
- sim-recovery
- coverage
- release
- Final-SHA Certification
```

如果实际修改范围扩大，再动态升级。

---

# 43. 禁止“保险起见全跑”

禁止使用：

```text
to be safe, run full release
```

作为无分析默认。

必须先回答：

```text
这次 change 改变了哪个 executable authority？
```

如果答案是：

```text
none
```

就不应跑 Runtime full suite。

OnlyAlpha 的原则是：

```text
最窄的正确验证集合
```

而不是：

```text
最宽的可运行验证集合
```

---

# 44. Token Consumption Contract

为了减少 test 相关 token：

1. PASS 不展开完整 stdout；
2. 不输出 `--durations=100` 到 Agent context；
3. 不重复读取同一 PASS log；
4. 不高频轮询 CI；
5. 不为 docs-only change 跑 runtime suites；
6. failure-first，先解决第一个确定失败；
7. full raw log 落盘；
8. 只有 failure diagnosis 才读 bounded log；
9. final report 只列 summary，不粘贴大段 pytest 输出；
10. 不重复执行已经有可靠 evidence 且 change 未触及其 authority 的 suite。

---

# 45. Wall-Clock Efficiency Contract

为了减少执行时间：

```text
docs-only
→ no Runtime test
```

```text
policy-test change
→ targeted policy test
```

```text
verification-tooling change
→ targeted tooling tests + self-change escalation
```

```text
certification infrastructure change
→ broader verification
```

验证范围必须随实际 change impact 单调扩大，而不是开局直接 full release。

---

# 46. Independent Review

本 Closure 完成后进行一次小型 independent review，只检查：

```text
规则是否自洽
P7.x 是否真的只需 VERIFIED
P7 → P8 是否仍必须 ACCEPTED
Final-SHA authority 是否保持不变
是否误删 fail-closed certification
是否引入绕过质量门禁的措辞
是否存在旧文档继续阻塞 P7.6
```

不要重新 review 整个 OnlyAlpha 产品架构。

---

# 47. Definition of Done

只有以下全部满足才结束。

## Governance

- [ ] Increment 与 Major Milestone 已正式区分
- [ ] P7.x → next P7.x 只要求 previous increment VERIFIED
- [ ] P7 → P8 仍要求 P7 ACCEPTED
- [ ] Final-SHA Certification authority 未削弱
- [ ] default cadence 改为 Milestone Final Closure
- [ ] explicit certification checkpoint 例外已定义

## Current Truth

- [ ] quality-system 不再要求每个 P7.x ACCEPTED
- [ ] AGENTS 不再要求每个 P7.x Final-SHA
- [ ] roadmap 不再用缺少 P7.5.2 certificate 阻塞 P7.6
- [ ] README 相关状态无明显冲突
- [ ] 无其它正式文档继续表达冲突规则

## Efficiency

- [ ] docs-only change 未运行无关 Runtime suites
- [ ] 未运行无意义 coverage
- [ ] 未运行无意义 recovery/sim-recovery/core-full
- [ ] 未默认运行 release
- [ ] 成功日志使用 compact summary
- [ ] 无高频 CI polling
- [ ] full logs 未无意义进入 Agent context

## Verification

- [ ] `git diff --check` PASS
- [ ] targeted policy/doc tests PASS if such tests exist/are changed
- [ ] broader verification only if actual tooling/workflow changes require it
- [ ] independent governance review complete
- [ ] no unresolved Critical / High

## Closure State

- [ ] P7 Quality Gate Granularity Closure = VERIFIED
- [ ] standalone Final-SHA Certification = NOT REQUIRED
- [ ] P7 Final-SHA Certification remains required at P7 Final Closure
- [ ] P7.6 Entry Gate can now use previous increment VERIFIED

---

# 48. 推荐实施顺序

严格建议：

```text
1. Read current HEAD
2. Read only quality-system / AGENTS / roadmap / README
3. Search old ACCEPTED / Final-SHA entry-gate wording
4. Classify change scope
5. Produce minimal verification plan
6. Update quality-system
7. Update AGENTS
8. Update roadmap
9. Update README only where directly necessary
10. Re-search repository for conflicting rules
11. Run smallest correct verification set
12. Independent governance review
13. Mark Closure VERIFIED
14. Stop
```

不要在本任务结束时自动：

```text
run release
run full coverage
run Final-SHA Certification
```

---

# 49. Codex 最终输出要求

完成后只输出简洁报告。

## Repository

```text
starting SHA
ending working-tree / commit state
```

## Governance Decision

明确写：

```text
P7.x increment requires VERIFIED
P7 Major Milestone requires ACCEPTED
```

## Files Changed

仅列实际修改文件。

## Verification Scope

明确说明：

```text
change classification
what was run
what was intentionally not run
why
```

例如：

```text
Not run:
core-full / recovery / release / coverage

Reason:
governance-docs-only change; no executable Runtime/Research authority changed.
```

## Verification Results

只列：

```text
PASS / FAIL summary
```

不要粘贴大段日志。

## Certification

必须写：

```text
Standalone closure Final-SHA Certification:
NOT REQUIRED

P7 Final-SHA Certification:
REQUIRED AT P7 FINAL CLOSURE
```

## P7.6 Readiness

明确回答：

```text
P7.6 Entry Gate now requires previous P7 increment VERIFIED.
```

如果 current P7.5.2 已满足 VERIFIED，则说明：

```text
P7.6 may proceed
```

如果仍缺真实 evidence，则准确列出缺项。

---

# 50. 最终原则

本 Closure 不是：

> “降低测试标准。”

而是：

> **把验证成本放到正确的工程边界。**

最终模型必须是：

```text
Implementation Edit
→ targeted verification
```

```text
P7.x Increment Closure
→ affected verification
→ VERIFIED
```

```text
P7 Final Closure
→ full exact-SHA Final-SHA Certification
→ ACCEPTED
```

而不是：

```text
every P7.x
→ full repository certification
```

必须保持：

```text
Correctness remains strict
Certification remains authoritative
Increment iteration becomes faster
Test-related token consumption becomes smaller
```

这就是本 Closure 的最终验收标准。
