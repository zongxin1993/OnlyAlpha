# Formal Proof / Authority-Bound Audit Method

本文件定义 OnlyAlpha 对 **Authority-sensitive / proof-bearing** 工程改动的详细审计方法。

它是 `AGENTS.md` 的执行方法说明，不拥有独立的 Task Acceptance、Architecture、Quality、Progress 或 Certification Authority。若本文件与 `PROJECT_CONSTITUTION.md`、Architecture / public Contract、Accepted ADR 或 `AGENTS.md` 冲突，以更高层 Authority 为准。

---

## 1. 适用范围

当任务涉及以下任一性质时，应按本方法执行强化审计：

- Authority / ownership / canonical identity；
- immutable fact / revision / source cut / projection；
- exact query / certified absence / historical proof；
- Evidence / provenance / lineage；
- state machine / terminal state / recovery / replay；
- fail-closed / UNKNOWN / retry / reconciliation；
- admission / reuse / suppression / promotion / decision witness；
- persistence / migration 中会影响正式事实解释的语义；
- 任何“缺失、未知、部分可用、历史不可读”可能被错误解释为正式结论的路径。

本方法不把普通 CRUD、UI 调整、纯展示、无 Authority 含义的内部重构自动升级为 formal-proof 审计。

---

## 2. 核心原则

Formal proof 审计不是“确认这次已知 bug 修了没有”，而是证明当前 bounded scope 内的契约闭包成立。

必须区分：

```text
Entity Completeness
→ 必要实体是否存在且身份明确？

Relation Closure
→ 这些实体之间的 exact occurrence / ownership / lineage 关系是否被证明？

Proof Sufficiency
→ 当前 predicate / decision 是否真的有资格得出 MATCH / NO_MATCH / ADMIT / REUSE / SUPPRESS 等正式结论？
```

以下推理默认非法，除非 owning Authority / accepted Contract 明确证明：

```text
absence of evidence
!= evidence of absence

shared identity / shared Result
!= shared ownership / causality / lineage

optional downstream fact missing
!= occurrence did not exist

source ref present
!= source is the owner

same logical definition
!= same result occurrence

current readable state
!= historical proof completeness
```

### 2.1 Derived Authority Fact Rule

对于任何 derived formal fact，caller 提供的结构合法值不等于 Authority 可接纳事实。公开权威写入路径必须接收 source intent / input facts，由 canonical producer 推导结果；raw persistence primitive 必须保持 internal，不能成为第二条 authoring API。Independent Review 必须构造语义伪造但 fingerprint 正确的 derived result，并证明它不能绕过 canonical producer 进入 Authority。

---

## 3. Authority State-Space Audit

实现前先从 owning Authority 枚举完整合法状态空间，而不是从当前代码分支或本次 bug 列表反推测试。

最小步骤：

1. 找到 owning Authority / canonical state model；
2. 枚举所有合法 state / outcome / revision；
3. 标记 terminal / non-terminal；
4. 标记每个状态下 required / forbidden / optional facts；
5. 明确每个状态在当前 projection/query/decision 中的合法解释；
6. 若存在未覆盖状态，先修 Contract 或 STOP，不直接编码猜测。

示例结构：

| Authority state | Terminal | Required facts | Forbidden facts | Historical meaning | Query/Decision semantics |
|---|---:|---|---|---|---|
| state A | ... | ... | ... | ... | ... |

状态表必须来自 Authority contract，而不是 implementation branch coverage。

---

## 4. Proof Matrix

对每个 formal predicate / projection / decision 建立 Proof Matrix。

至少包含：

| Dimension | Owning Authority | Canonical identity | Projection / representation | Required? | Consumer check | Missing behavior |
|---|---|---|---|---:|---|---|
| ... | ... | ... | ... | YES/NO | ... | INCOMPLETE / UNAVAILABLE / N/A |

任何 mandatory dimension 没有明确：

```text
Authority
Identity
Representation
Validation
Missing semantics
```

都不能声称 proof closure 完整。

Proof Matrix 必须区分：

```text
selector-bound identity
returned exact occurrence identity
optional provenance
advisory metadata
```

不得因为字段“存在”就默认它已经进入 formal predicate。

---

## 5. Relation Closure Matrix

当一个结论依赖多个 Authority 时，单纯验证各实体都存在不够。

必须明确 exact relation chain，例如：

```text
A occurrence
→ admission / receipt
→ B occurrence
→ result / evidence
```

对每条 relation 记录：

- relation owner；
- source occurrence identity；
- destination occurrence identity；
- cardinality（1:1、1:N、N:1）；
- 是否允许 absent / optional；
- relation proof 的 authoritative reader / source ref；
- relation 缺失时的 fail-closed 行为。

禁止用以下替代 exact relation：

```text
same Result
same timestamp
same candidate name
same Dataset
same graph
same source-ref family
same mutable row state
```

除非 owning Contract 明确规定这些就是 relation identity。

---

## 6. Predicate Truth Table

Formal predicate 必须显式定义知识状态。

若内部使用三值逻辑：

```text
True
→ 已完整证明 exact match

False
→ 已完整证明 exact non-match

None
→ 缺少完成判断所需的 mandatory proof
```

若对外使用 typed status，应保持同等区分，例如：

```text
MATCH
CERTIFIED_NO_MATCH
PROOF_INCOMPLETE
PROOF_UNAVAILABLE
```

核心规则：

> **每一个 `False` 都必须有“凭什么证明不是目标”的完整证据。缺失证据不能返回 False。**

推荐对 typed owner / predicate 使用三阶段结构：

```text
1. Applicability
   这个 record 是否属于当前 predicate / owner family？

2. Completeness
   如果适用，mandatory proof 是否完整？

3. Equality
   在 proof 完整后，exact identity / context 是否相等？
```

通用真值表：

| Condition | Internal result |
|---|---|
| Provably another owner/predicate family | `False` |
| Applicable / plausibly applicable but mandatory proof missing | `None` |
| Complete proof, exact identity differs | `False` |
| Complete proof, identity same, required predicate differs | `False` |
| Complete proof and all exact dimensions match | `True` |

---

## 7. Negative Invariants

每个 proof-bearing Task Contract 除 Required Behavior 外，必须至少列出直接相关的 negative invariants：什么结论 **绝不能** 从当前证据推导。

典型模式：

```text
missing proof
!= certified absence

UNKNOWN submission
!= safe retry

CANCELLED / STOP / incomplete
!= scientific rejection

same Result
!= same Search ownership

source ref
!= owner unless Contract says so

semantic match
!= evaluation exact match

operational failure
!= negative alpha Evidence
```

Negative invariant 能 deterministic reproduction 时，应转成 executable regression / mutation test，而不是只留文档提醒。

---

## 8. Structural Mutation Testing

不能只测试 leaf field 的正常/异常值。对于 proof-bearing record，应按结构层级做 mutation。

最小层级：

```text
Layer 1 — whole context removed
Layer 2 — owner / occurrence identity removed
Layer 3 — nested relation removed
Layer 4 — authoritative source ref removed / malformed
Layer 5 — leaf fingerprint / version malformed
Layer 6 — duplicate owner / duplicate relation
Layer 7 — wrong owner family / wrong relation target
Layer 8 — complete but different exact identity
```

对每个 mutation，明确期望：

```text
MATCH
NO_MATCH
INCOMPLETE
UNAVAILABLE
```

或对应模块的正式状态。

特别要求：

> 对完整 relevant record 删除任一 mandatory proof element 后，结果不得静默变成 MATCH 或 CERTIFIED_NO_MATCH。

可用参数化/property-style tests 降低重复代码，但不要为此建立无当前价值的测试框架。

---

## 9. Lifecycle / Optionality Audit

对状态机和历史 projection，必须显式区分：

```text
occurrence existence
context existence
optional outcome
terminal result
structured failure
cancellation / stop
```

检查：

- optional downstream fact 缺失是否导致整个 occurrence context 消失；
- success path 与 failure/cancel path 是否使用同一套必要 identity closure；
- failed-with-result 与 failed-without-result 是否被错误折叠；
- cancellation 是否被伪造成 structured failure；
- running / incomplete / UNKNOWN 是否被误解释成 terminal negative result。

---

## 10. Certified Absence Audit

任何正式 absence 结论必须满足：

```text
closed authoritative source cut
+ complete applicable projection / reader
+ every relevant record can evaluate the full predicate
+ zero exact match
```

以下都不得证明 absence：

```text
timestamp
row count
current index snapshot
missing reader
partial family
corrupt record
unresolved relation
malformed relevant owner proof
```

若 relevant proof 不完整：

```text
PROOF_INCOMPLETE / FAIL_CLOSED
```

若历史 reader/fact 不可用：

```text
PROOF_UNAVAILABLE / HISTORICAL_PROOF_UNAVAILABLE
```

不得 reinterpret 成 NO_MATCH。

---

## 11. Recovery / Replay Matrix

proof-bearing immutable history 需验证：

```text
same authoritative source cut
+ same schema/algorithm versions
→ same logical projection / query result / witness identity
```

至少检查：

- fresh rebuild；
- source discovery order independence；
- duplicate replay；
- old revision unaffected by later source growth；
- partial/corrupt new revision 不取代 old verified revision；
- source truth 不因 projection/query rebuild 被改写；
- historical schema/reader missing 时 fail closed。

---

## 12. Independent Re-Derivation Review

高风险 proof-bearing 任务的 bounded Independent Review 不能只重复 Implementation Task 的 checklist。

Reviewer 必须先从：

```text
Constitution
→ Architecture / Contract
→ Accepted ADR
→ owning Authority state machine
```

独立重新推导：

```text
legal state space
mandatory identities
relation closure
negative invariants
predicate truth table
adversarial mutations
```

再与实现比较。

独立审查至少回答：

1. 是否存在合法 Authority state 当前没有明确语义？
2. 是否存在 mandatory proof 缺失却返回 formal non-match / success？
3. 是否存在共享 identity 被误当 ownership/relation？
4. 是否存在 optional outcome 被误当 occurrence 存在条件？
5. 是否存在 failure/cancel/incomplete 被误解释成 scientific outcome？
6. 是否有 malformed relevant record 能制造 certified absence？
7. 是否有 unrelated valid record 会污染另一个 exact query？
8. fresh rebuild / historical replay 是否保持 exact identity？

Review 仍受 `AGENTS.md` 的 bounded scope 约束，不能扩展成无关全仓审计。

---

## 13. Closure Gate

当 `AGENTS.md` 判定当前高风险任务属于 proof-bearing / Authority-bound 任务时，在普通 Stop Condition 与 bounded Independent Review 之外，相关项必须证明：

```text
Authority State-Space       PASS
Entity Completeness         PASS
Relation Closure            PASS
Predicate Proof Sufficiency PASS
Negative Invariants         PASS
Structural Mutation         PASS
Recovery / Replay           PASS（若涉及 durable history / recovery）
Independent Re-Derivation   PASS
```

并保持：

```text
Critical = 0
High = 0
```

未适用项应说明为什么 N/A；不得用 N/A 跳过真实 Impact Scope 内的 proof obligation。

这些 PASS/N/A 只存在于当前任务上下文，不提交为仓库状态、认证报告或进度 Authority。

---

## 14. 审计产物与仓库卫生

允许长期保留：

- 本方法文档；
- Architecture / Contract / ADR 中本来就属于长期语义的状态机和不变量；
- deterministic regression / mutation / recovery tests。

不得长期提交：

- 某次任务的 Proof Matrix 实例；
- 某次 PR 的 PASS 表；
- closure 报告；
- CI 快照；
- Final SHA / certified SHA；
- 历史 Prompt。

Task-specific matrix 应存在于当前开发上下文 / PR discussion / review 过程；只有其中具有长期产品语义的部分才进入 Architecture / Contract / ADR。

---

## 15. 最小执行模板

对适用任务，开发顺序应为：

```text
READ owning Authorities
→ derive complete legal state space
→ freeze Proof Matrix + Relation Matrix
→ freeze predicate truth table + negative invariants
→ implement smallest correct change
→ targeted deterministic tests
→ structural mutation tests
→ recovery/replay tests when applicable
→ bounded Simplicity Review
→ Independent Re-Derivation Review
→ Critical = 0 / High = 0
→ STOP
```

核心原则：

> Formal proof 系统中，“不知道”不是“否定”；“存在字段”不是“关系被证明”；“共享事实”不是“共享 ownership”。

---

## 16. Audit Boundary / Review Budget 前置约束

所有使用本方法的 formal-proof / Authority-bound audit，**MUST 在 substantive review 前先执行 `docs/engineering/audit_boundary_method.md`**。

顺序固定为：

```text
Freeze Audit Type
→ Freeze Audit Target / Baseline / Required Behavior
→ Freeze S0 / S1 / required S2 Scope
→ Freeze Audit Dimensions + Negative Scope
→ Set Review Round Budget
→ Freeze Formal Proof Matrix / Relation Matrix / Truth Table
→ Review
```

不得反向执行：

```text
Review
→ 发现新角度
→ 自动增加 Proof Matrix 维度
→ 再 Review
→ 无限扩大当前 Phase
```

Formal-proof 审计中的 State-Space、Proof Matrix、Relation Closure、Negative Invariants 与 Structural Mutation **只能覆盖 Frozen Audit Dimensions**。新增维度必须通过 `audit_boundary_method.md` 的 Boundary Expansion Test。

Review round 也受该方法限制：

```text
Round 1 — Full Review
Round 2 — Delta Review
Round 3 — Final Closure Review
```

Formal-proof / Authority-bound audit 默认最多 3 个 semantic review rounds。Round 3 后仍有 Critical / High 时，不得自动进入 Round 4；必须报告：

```text
DESIGN_RESET_REQUIRED
或
OWNER_DECISION_REQUIRED
```

若同一 root cause 连续 2 轮产生新的 blocker，应停止局部 patch，并执行 Design Reset。

达到 Frozen Audit Matrix 全部检查完成且当前范围 `Critical = 0 / High = 0` 后，**MUST STOP AUDIT**；Medium / Low / Deferred / Observation 不得继续扩大当前 closure。
