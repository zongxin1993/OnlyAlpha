# Audit Boundary / Review Budget Method

本文件定义 OnlyAlpha 对 **代码审查、阶段 closure 审计与高风险 formal audit** 的统一边界确定方法。

它只解释 `AGENTS.md` 中已有的 bounded scope、Impact-Aware Validation、Independent Review 与 Stop Condition 如何执行；**不拥有独立的 Task Acceptance、Architecture、Quality、Progress 或 Certification Authority**。若本文件与 `PROJECT_CONSTITUTION.md`、Architecture / public Contract、Accepted ADR 或 `AGENTS.md` 冲突，以更高层 Authority 为准。

本方法的目标是同时避免两类错误：

```text
审得太窄
→ 漏掉当前 Task Contract 真实依赖的 Critical / High 问题

审得无限
→ 每轮不断增加新的审计维度，导致任务永远无法 CLOSED
```

核心原则：

> **审计必须严格，但审计集合必须先有限化。先冻结边界，再证明边界内的 closure；不得通过不断新增审计维度追求“全仓绝对无 bug”。**

---

## 1. Audit Type 必须先确定

任何正式 review / audit 开始前，必须先声明一种 Audit Type。

### 1.1 Change Review

目的：判断一个 diff / PR 是否引入 regression 或违反当前 Contract。

默认范围：

```text
当前 diff / patch
+ 直接 producer / consumer
+ 证明当前 change 正确所必需的最近稳定 contract boundary
```

Change Review 不负责寻找整个 subsystem 的历史技术债。

### 1.2 Closure Audit

目的：判断一个 Task / Phase 是否满足其冻结 Required Behavior，可以进入下一阶段。

当用户表达以下意图时，默认解释成 Closure Audit：

```text
“审计主线代码，判断是否符合预期”
“能不能开始下一个任务”
“当前阶段是否可以关闭”
“检查这次实现是否完成”
```

Closure Audit **不是 Repository Audit**。

它只回答：

```text
当前冻结 Contract 是否闭合？
当前范围 Critical / High 是否为 0？
当前 Required Behavior 是否有充分 Evidence？
```

### 1.3 Repository Audit

目的：主动寻找 repository-wide architecture、correctness、security、complexity 或 debt 问题。

只有以下情况才能执行：

- 用户显式要求全仓审计；
- Major Milestone contract 明确要求；
- 已接受治理/Architecture 任务本身就是 repository-wide audit。

普通 Change Review / Closure Audit **MUST NOT** 自动升级为 Repository Audit。

---

## 2. 审计前必须冻结 Audit Boundary Contract

在 substantive implementation inspection 之前，当前 review 上下文必须明确：

```text
Audit Type
Audit Target
Baseline
Current Head / semantic fingerprint
Frozen Required Behavior
Modification Scope
Expected Impact Scope
Frozen Audit Dimensions
Negative Scope
Blocking Severity
Review Round Budget
Stop Condition
```

该 Boundary Contract 只存在于当前 review / task 上下文，不提交成仓库质量状态文件。

### 2.1 Audit Target

只能描述当前要做的一个判断，例如：

```text
B3.5.1-C Historical Query Closure
PR #123 compatibility review
Research Run recovery correction closure
```

禁止使用：

```text
“检查项目还有没有其他问题”
“顺便看看整个系统”
“尽可能找更多问题”
```

作为 Closure Audit target。

### 2.2 Baseline

必须明确比较基准，例如：

```text
merge-base
parent commit
accepted previous phase
public contract revision
```

不得在 review 过程中无理由移动 baseline。

---

## 3. Scope 分四层

OnlyAlpha review 使用以下 Scope Levels：

```text
S0 — Patch / Modification Scope
当前任务实际修改的文件、symbol、schema、contract。

S1 — Direct Dependency Scope
直接 producer / consumer、serializer / reader、caller / callee、affected tests。

S2 — Authority / Stable Contract Boundary
为证明当前 Required Behavior 必须检查的 owning Authority、state machine、durable relation、public compatibility boundary。

S3 — Repository Scope
全仓及与当前任务无直接依赖的 subsystem。
```

默认规则：

```text
Lightweight / Ordinary Change Review
→ S0 + 必要 S1

High-risk / Closure / Formal-proof Audit
→ S0 + S1 + 证明 Required Behavior 所必需的 S2

S3
→ 禁止自动进入
```

Scope expansion 最多扩到最近稳定 Authority / Contract boundary。

如果一个问题只有继续进入另一个独立 subsystem 的内部实现才能证明，应默认：

```text
DEFERRED_DEFECT
```

而不是继续扩大当前 audit。

---

## 4. Audit Dimensions 必须在 substantive review 前冻结

Audit Dimension 是当前审计允许回答的问题维度，例如：

```text
state-machine legality
identity / ownership
relation closure
public compatibility
certified absence
recovery determinism
persistence integrity
security boundary
```

Closure Audit 必须从以下来源推导维度：

```text
Frozen Required Behavior
+ directly relevant Architecture / public Contract
+ Accepted ADR
+ directly affected Constitution invariant
```

**不得从当前实现分支、最新发现的 bug 列表或“想到的新角度”无限增加维度。**

Formal-proof Audit 可进一步冻结有限矩阵，例如：

| Predicate | Valid | Complete-different | Malformed | Unavailable |
|---|---:|---:|---:|---:|
| Semantic | REVIEW | REVIEW | REVIEW | REVIEW |
| Evaluation | REVIEW | REVIEW | REVIEW | REVIEW |
| Parameter | REVIEW | REVIEW | REVIEW | REVIEW |
| Failure | REVIEW | REVIEW | REVIEW | REVIEW |

审计结束条件是这张冻结矩阵被完整检查，而不是持续新增列。

---

## 5. Negative Scope 必须显式记录

Boundary Contract 必须写出当前 **不审什么**。

例如：

```text
Out of Audit Scope:
- next-phase Novelty Policy
- unrelated Agent orchestration
- UI polish
- global performance optimization
- repository-wide debt
- pre-existing Medium / Low issues
```

审计过程中遇到 Negative Scope 内问题：

```text
最多记录为 DEFERRED / OBSERVATION
不得沿该路径继续深挖
```

除非它通过第 6 节 Boundary Expansion Test。

---

## 6. Boundary Expansion Test

审计开始后，Audit Dimensions 与 Impact Scope 默认冻结。

新维度只有满足以下至少一项，才能进入当前 audit：

```text
A. Higher Authority Requirement
   Constitution / Architecture / Accepted ADR / frozen Task Contract 明确要求。

B. Direct Change Impact
   当前修改直接改变了该 Contract / Authority / durable relation。

C. Concrete Blocking Dependency
   已有 concrete Critical/High counterexample 能证明原 Impact Scope 漏掉了一个直接依赖。

D. Required Behavior Proof Necessity
   不检查该维度就无法证明当前冻结 Required Behavior。
```

并且必须记录完整因果链：

```text
Current Task
→ changed / required behavior
→ directly affected contract / relation
→ omitted dimension
→ concrete Critical / High consequence
```

若无法给出这条因果链：

```text
BOUNDARY_EXPANSION_REJECTED
→ DEFERRED / OBSERVATION
```

### 6.1 严重度不能自动扩大 Scope

以下推理非法：

```text
“这个问题看起来很严重”
→ 自动扩大当前审计范围
```

正确顺序：

```text
先判断是否在 Frozen Scope
→ 若不在，执行 Boundary Expansion Test
→ 通过后才进入当前 finding 集合
```

---

## 7. Finding Admission Test

一个 finding 只有同时满足以下条件，才能进入当前 Closure Gate：

```text
F1 Concrete
有代码、Contract、测试、trace、可执行 counterexample 或确定 CI regression 支持。

F2 In-Scope
属于 Frozen Audit Dimension，或已通过 Boundary Expansion Test。

F3 Supported
由 Frozen Required Behavior、Architecture、Accepted ADR、Constitution、durable compatibility 或 baseline regression 支持。

F4 Actionable
能指出受影响路径与最小修复边界；不是纯 speculative risk。

F5 Closure-Relevant
能够说明为什么它会阻止当前 Task / Phase 的 Required Behavior 或 closure proof。
```

只有：

```text
F1 + F2 + F3 + F4 + F5
```

全部成立，才允许成为当前 `Critical / High` blocker。

不满足时：

```text
真实但范围外 → DEFERRED
仅猜测/优化 → OBSERVATION 或 DROP
```

---

## 8. Scope 与 Severity 必须独立

`Scope` 回答：

```text
这个问题属于当前 audit 吗？
```

`Severity` 回答：

```text
已进入当前 audit 的问题是否阻塞？
```

二者不得互相替代。

Severity 沿用 `AGENTS.md`：

```text
Critical → 阻塞
High     → 阻塞
Medium   → 默认不阻塞
Low      → 不阻塞
```

一个范围外的严重问题可以是：

```text
DEFERRED_HIGH
```

但它不会自动把当前 Closure Audit 扩成另一个项目。

---

## 9. Pre-existing Defect 规则

Closure Audit 中，pre-existing defect 默认不阻塞当前任务。

只有以下情况例外：

```text
1. 它直接使当前 Frozen Required Behavior 无法成立；

2. 当前修改依赖该 defect 所在路径，并把它纳入自己的 formal proof / contract；

3. 当前修改扩大、重新暴露或使该 defect 变成新的 Critical / High regression。
```

否则：

```text
DEFERRED_DEFECT
```

不得因为发现历史问题就重新启动全 subsystem audit。

---

## 10. Review Round Budget

Review 必须有有限轮次预算。

### 10.1 Semantic Review Round 定义

一轮指：

```text
一个稳定 semantic fingerprint / diff
→ 对当前 Frozen Audit Matrix 完成一次规定范围 review
→ 输出一批 admitted findings
```

Tool retry、CI retry、重新读取同一文件不计入 round。

### 10.2 默认预算

```text
Lightweight review        → 1 round
Ordinary review           → 最多 2 rounds
High-risk review          → 最多 3 rounds
Formal-proof / Authority  → 最多 3 rounds
```

### 10.3 Round 职责

```text
Round 1 — Full Review
完整检查 Frozen Audit Matrix。

Round 2 — Delta Review
只检查 Round 1 修复 + 修复直接影响的 Frozen Dimensions。

Round 3 — Final Closure Review
对同一 Frozen Audit Matrix 做一次最终完整复核。
```

Round 2+ 不得重新从零发明新的 Audit Dimensions。

### 10.4 禁止自动 Round 4

若 Round 3 后仍存在当前范围 Critical / High：

```text
STOP PATCH LOOP
```

进入以下之一：

```text
DESIGN_RESET_REQUIRED
OWNER_DECISION_REQUIRED
PLAN_CONFLICT
```

不得自动创建 C.4/C.5 式无限 correction chain。

---

## 11. Repeated Root Cause → Design Reset

如果同一 root cause 在连续 2 个 semantic review rounds 中再次产生新的 blocker：

```text
PATCHING STOP
→ DESIGN_RESET_REQUIRED
```

典型信号：

- 同一种 `False vs Unknown` 错误不断出现在不同 predicate；
- 同一个 relation ownership 问题不断增加特例；
- 为修一个状态不断增加分支而没有统一 state model；
- 同一 compatibility 问题不断通过 alias / wrapper 转移。

Design Reset 必须重新冻结：

```text
root invariant
state / relation model
proof vocabulary
最小 stable boundary
```

然后在原 Round Budget 内继续；若预算已耗尽，需要 owner-level 新任务，而不是无限 patch。

---

## 12. Finding Disposition

每次 Audit 只能输出以下三类 finding：

### BLOCKER

```text
当前 Frozen Scope 内
+ Finding Admission Test 通过
+ Critical / High
```

必须修复才能 closure。

### DEFERRED

```text
真实问题
但不属于当前 Frozen Contract / Scope
```

可进入后续 issue/task，不扩当前审计。

### OBSERVATION

```text
speculative risk
optimization
style / optional simplification
缺少足够 evidence 的怀疑
```

不进入 closure gate。

不得把所有“发现”都提升成 blocker。

---

## 13. Full Review、Delta Review 与 Final Review

Round 1 后的复审默认是 Delta Review。

Delta Review 只能检查：

```text
上一轮 BLOCKER 的修复
+ 修复直接修改的 behavior
+ Frozen Audit Dimensions 内受影响关系
```

不得：

```text
重新扫全仓
重新定义 Required Behavior
引入 unrelated subsystem
因为“顺便发现”而增长 Audit Matrix
```

Final Review 可以重新遍历整张 Frozen Audit Matrix，但：

```text
Matrix rows / columns 不再增加
```

如果 Final Review 发现一个全新维度，执行第 6 节 Boundary Expansion Test；若确属原 Contract 遗漏，则当前 closure FAIL，但不得无限继续 review round，需按 Round Budget 进入 design/owner decision。

---

## 14. Closure Stop Condition

Closure Audit 的停止条件必须是有限集合：

```text
All Frozen Audit Matrix cells reviewed
+ all admitted Critical = 0
+ all admitted High = 0
+ Frozen Required Behavior proven
+ required validation PASS
+ no unresolved approved Boundary Expansion
+ final semantic fingerprint reviewed
= CLOSED
```

达到后：

```text
STOP AUDIT
```

即使仍存在：

```text
Medium > 0
Low > 0
Deferred > 0
Observation > 0
```

也不得因此继续扩大当前任务。

---

## 15. Closed Phase Reopen Rule

一个已经 CLOSED 的 Task / Phase 默认不重新打开。

只有以下情况允许 reopen：

```text
R1. 新证据证明 closure 时的 Frozen Required Behavior 实际未满足；

R2. 新证据证明当时 Frozen Audit Boundary 内存在遗漏的 Critical / High Constitution / Authority violation；

R3. closure evidence 本身被证明无效、损坏、伪造或并未执行。
```

其它后续发现：

```text
new defect
→ new task / issue
```

而不是重写历史 closure。

---

## 16. Final Review 不允许无限增维

一旦进入 `FINAL CLOSURE REVIEW`：

```text
Frozen Audit Dimensions = immutable
```

如果 reviewer 发现新问题：

```text
A. 能证明属于原 Frozen Contract
→ 当前 closure FAIL
→ 在剩余 Round Budget 内修复或进入 DESIGN_RESET / OWNER_DECISION

B. 不属于原 Frozen Contract
→ DEFERRED
→ 当前 Audit 不扩展
```

不得在 Final Review 中形成：

```text
发现新维度
→ 扩 Matrix
→ 再 review
→ 再发现新维度
→ 无限循环
```

---

## 17. Formal-Proof Audit 的额外约束

Formal-proof / Authority-bound audit 仍必须执行 `docs/engineering/formal_proof_audit_method.md` 的：

```text
Authority State-Space
Proof Matrix
Relation Closure
Predicate Truth Table
Negative Invariants
Structural Mutation
Recovery / Replay
Independent Re-Derivation
```

但上述内容只能覆盖 **Frozen Audit Dimensions**。

Formal-proof 方法不能作为理由自动扩大 Audit Boundary。

正确顺序：

```text
Freeze Audit Boundary
→ Freeze Formal Proof Matrix
→ Review
```

而不是：

```text
Review
→ 不断发现新 proof dimension
→ 无限扩大当前 Phase
```

---

## 18. 最小执行算法

```text
1. READ Constitution / Contract / ADR / Task Contract
2. DECLARE Audit Type
3. FREEZE Audit Target + Baseline + Required Behavior
4. BUILD S0 / S1 / required S2 Scope
5. FREEZE Audit Dimensions
6. FREEZE Negative Scope
7. SET Review Round Budget
8. RUN Round 1 Full Review
9. CLASSIFY findings: BLOCKER / DEFERRED / OBSERVATION
10. FIX blockers as one bounded batch where practical
11. RUN Round 2 Delta Review when needed
12. RUN Round 3 Final Closure Review for high-risk/formal work
13. IF Critical=0 and High=0 and frozen matrix exhausted → CLOSED + STOP
14. IF budget exhausted with blockers → DESIGN_RESET_REQUIRED / OWNER_DECISION_REQUIRED
```

---

## 19. Audit Boundary 示例

一个 B3.5.1-C Closure Audit 可以冻结为：

```text
Audit Type:
Closure Audit

Audit Target:
Historical exact-query closure

Frozen Dimensions:
- Semantic Exact
- Evaluation Exact
- Parameter Observation Exact
- Failure Evidence Exact
- Certified Absence
- Explicit Revision Binding
- Recovery / Replay
- directly affected architecture compatibility

S2 Authority Boundary:
- Search provenance required by exact lineage
- Research Run lifecycle required by Evaluation/Failure proof
- Result/Statistics authorities required by exact evaluation closure

Negative Scope:
- B3.5.2 Novelty Policy
- Novelty Decision
- near-duplicate retrieval
- unrelated Agent orchestration
- whole-repository cleanup
```

审计者可以在这些维度内寻找任何 counterexample；但不能因为看到 Agent/Search 的邻接代码，就自动把其全部内部正确性纳入本次 C closure。

---

## 20. 最终原则

> **Strict review does not mean unbounded review.**

OnlyAlpha 审计必须同时满足：

```text
足够宽
→ 能证明当前 Frozen Contract

足够窄
→ 能在有限时间内达到明确 Stop Condition
```

审计质量不以 finding 数量衡量，也不以审计轮数衡量。

正确完成标准只有：

```text
Frozen Contract 被充分证明
+ 当前 Scope Critical = 0
+ 当前 Scope High = 0
+ Round / Boundary discipline 被遵守
→ STOP
```
