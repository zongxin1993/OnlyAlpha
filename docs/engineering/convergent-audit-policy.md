# OnlyAlpha Convergent Audit Policy

> 本文定义 OnlyAlpha 的统一工程审计协议。它适用于 Codex、其他 AI Agent、人工 Reviewer、阶段复审、修复后复审和架构一致性审计。
>
> 审计目标不是持续寻找“还能怎么优化”，而是基于冻结设计与可验证证据判断：当前实现是否满足已经定义的系统约束，是否具备进入下一工程阶段的条件。

---

## 1. 规范地位与边界

本政策是审计执行协议，不创建第四种工程质量 Gate。

OnlyAlpha 正式质量层级仍然只有：

```text
Task Gate
Phase Gate
Certification Gate
```

其验收语义继续由 `docs/engineering/quality-system.md` 定义。本政策只规定 Reviewer / Agent 如何进行一致、可收敛、可追踪的审计，并为现有 Gate 提供 review evidence。

审计必须服从：

```text
Frozen contract
> reviewer preference

Evidence
> speculation

Invariant
> abstraction preference

Correctness
> elegance

Minimum sufficient mechanism
> architectural expansion
```

---

## 2. 审计的唯一目标

每次审计只回答：

> 当前实现是否正确落实了已经冻结的设计、ADR、架构边界、领域不变量、唯一性与确定性要求？

审计不得自动升级为重新设计任务。

必须严格区分：

1. correctness / invariant violation；
2. frozen design / ADR / architecture violation；
3. engineering quality debt；
4. optional improvement。

存在更优雅、更通用或更未来化的实现，不等于当前实现存在 blocking defect。

---

## 3. 审计事实基线

审计开始前必须冻结并记录：

```text
AUDIT_BASE_SHA
AUDIT_HEAD_SHA
Audit Scope
Target Task / Increment / Milestone
Applicable frozen design / ADR
Applicable acceptance criteria
Applicable architecture rules
Previous audit findings（若存在）
```

必须审计一个明确代码基线；不得把不同 commit、不同工作树或旧报告混成同一次结论。

事实来源优先级遵守仓库顶层 `AGENTS.md`。Prompt、旧对话和历史审计报告只可作为线索，不得覆盖当前源码、正式测试、未被替代 ADR 与当前工程合同。

---

## 4. 先建立 Invariant Matrix，再阅读实现结论

Reviewer 在产生 Finding 前必须先从当前设计中提取本次审计适用的 invariant。

建议格式：

```text
INV-XXX
Name:
Rule:
Scope:
Authority:
Evidence source:
Verification method:
```

至少按实际影响范围考虑：

- identity uniqueness；
- deterministic canonicalization / fingerprint；
- state ownership；
- durable authority；
- immutability；
- architecture dependency direction；
- Runtime / Research / Trading boundary；
- persistence uniqueness / transactionality；
- retry / replay / recovery idempotency；
- public contract / schema；
- fail-closed semantics；
- result / artifact provenance。

不得先产生“看起来有问题”的结论，再倒推一个不存在的规则为其背书。

---

## 5. 唯一性审计

对于每个具有领域身份的对象，必须验证：

```text
Same semantic object
→ same canonical identity

Different semantic object
→ no accidental identity sharing
```

审计不能停留在 hash 函数本身，必须按实际链路检查：

```text
Input
→ normalization
→ canonical representation
→ serialization
→ fingerprint / identity
→ persistence constraint
→ concurrent create
→ retry / replay / import / recovery
```

若领域唯一性需要跨进程或跨并发请求成立，application-level `exists()` 不足以证明唯一性；必须检查最终 authority 是否真正 enforce 约束。

---

## 6. 确定性审计

对于要求可重复的路径，验证：

```text
Same semantic input
+ same explicit configuration
+ same code / schema / authority version
= same semantic output
```

按影响范围检查但不限于：

- unordered dict / set / filesystem iteration；
- database query ordering；
- timestamps；
- UUID；
- random seed / unseeded randomness；
- float / Decimal normalization；
- timezone；
- canonical JSON / serialization；
- provider physical order；
- process / machine dependent value；
- environment-dependent implicit default。

允许的随机性必须显式成为 contract input；身份、复现和 durable authority 不得依赖未声明随机源。

---

## 7. Finding 严重度

所有 Finding 只能使用以下四级：

### BLOCKER

满足任一：

- 核心 invariant 被破坏；
- 数据或 durable authority 正确性被破坏；
- identity uniqueness 被破坏；
- required determinism 被破坏；
- 产生不可安全恢复或不可解释状态；
- 当前 Gate 无法安全通过。

对应现有质量体系中的 Critical 级阻塞问题。

### MAJOR

存在明确代码证据，且实际违反：

- frozen design；
- active ADR；
- architecture boundary；
- task / phase acceptance criteria；

并具有真实工程影响。

对应现有质量体系中的 High 级阻塞问题。

### MINOR

存在真实工程质量问题，但不破坏当前正确性与核心 contract，例如局部可维护性、非关键异常诊断、合理但非必要的测试补强。

MINOR 不阻塞进入下一阶段。

### SUGGESTION

更优雅的命名、额外抽象、未来扩展、可选测试、替代 library 或非必要重构。

SUGGESTION 不是 defect，不得转换为 Gate blocker。

---

## 8. Finding 的证据门槛

每个 BLOCKER / MAJOR 必须同时具备：

```text
Concrete code / schema / test evidence
+
Explicit violated rule
+
Actual impact
+
Reproducible reasoning path
```

Finding 必须使用：

```text
F-XXX — title
Severity:
Status:
Evidence:
Violated Rule:
Actual Behavior:
Expected Behavior:
Impact:
Reproduction / Reasoning:
Minimum Required Fix:
Blocking: YES / NO
```

Evidence 至少应包含文件路径与 symbol；可以可靠定位时应给出行号或测试名。

以下表述本身不能成为 BLOCKER / MAJOR：

```text
可能存在……
理论上……
似乎……
最好……
建议考虑……
未来可能……
```

若不能证明违反当前 contract，应降级为 MINOR / SUGGESTION 或不报告。

---

## 9. 修复后复审必须追踪原 Finding

如果存在上一轮审计，本轮必须先逐项复核已有 Finding，状态只能是：

```text
RESOLVED
PARTIALLY_RESOLVED
NOT_RESOLVED
REGRESSED
```

禁止通过改名制造新的 Finding 数量。

例如上一轮：

```text
F-004 Strategy duplicate creation
```

如果本轮只是发现 persistence 层仍未完全闭环，应继续报告：

```text
F-004 PARTIALLY_RESOLVED
```

而不是创建语义相同的 `F-019 persistence uniqueness issue`。

---

## 10. 新 Finding 规则

复审中只有满足以下条件才能新增 BLOCKER / MAJOR：

```text
new concrete evidence
+
violation of an existing applicable rule
+
actual engineering impact
```

同时必须说明为什么上一轮没有报告，并分类为：

```text
PREVIOUSLY_HIDDEN
INTRODUCED_BY_FIX
PREVIOUSLY_OUT_OF_SCOPE
NEW_REGRESSION
```

如果无法说明新增原因，Reviewer 必须优先检查是否属于：

- 原 Finding 的未闭环部分；
- reviewer preference drift；
- scope creep；
- speculative architecture。

---

## 11. 禁止审计漂移

冻结设计未变化时，Reviewer 不得因为新的个人偏好把已经满足 contract 的实现从 PASS 改为 FAIL。

禁止：

- 用新的“最佳实践”替换已经接受的设计；
- 为未来可能需求引入当前不需要的 interface / factory / registry / manager / adapter；
- 仅为了 DRY 合并语义不同的领域路径；
- 因目录或命名不够理想把正确实现升级为 MAJOR；
- 把 optional hardening 当成当前 acceptance criterion；
- 为了“找到问题”扩大审计范围；
- 在没有 design defect 证据时重新设计冻结架构。

如果 Reviewer 认为 frozen design 本身需要改变，必须单独提出 `DESIGN CHANGE PROPOSAL`，说明其与当前 invariant 的冲突；在设计正式变更前，不得用该 proposal 判当前实现失败。

---

## 12. 修复建议必须最小化

BLOCKER / MAJOR 的修复优先级：

```text
fix invariant
→ fix authority / boundary
→ fix persistence guarantee
→ add proving test
```

默认禁止把一个局部 correctness fix 扩大为：

- repository restructure；
- framework migration；
- unrelated rename；
- generic abstraction；
- compatibility layer；
- second implementation path。

目标是最小机制正确 enforce 当前 invariant，而不是最大化架构复杂度。

---

## 13. 审计与测试的关系

测试数量不是审计结论。

Reviewer 必须判断测试是否真正证明 invariant，特别关注：

```text
same semantic input → same identity
semantic change → identity changes
unordered physical order → same semantic result
concurrent same-create → one logical authority
retry / replay → idempotent
continuous run ≡ recovery run
corrupt authority → fail closed
```

关键 persistence / concurrency invariant 不能只由 mock repository 单元测试证明。

测试范围必须遵守现有 impact-aware Task / Phase / Certification Gate，不得因为“审计更严格”自动要求 repository-wide release 或 Final-SHA Certification。

---

## 14. GO / NO-GO 结论

每次完整审计必须明确给出：

```text
GO
```

或：

```text
NO-GO
```

### GO

在当前审计 Scope 对应的现有 Gate 语义下，至少满足：

```text
BLOCKER == 0
MAJOR == 0
Applicable core invariants == PASS
No known frozen-design / ADR violation
Required verification evidence is sufficient
```

MINOR 与 SUGGESTION 不阻塞 GO，应进入 technical debt / follow-up backlog。

### NO-GO

存在至少一个未解决 BLOCKER / MAJOR，或关键 invariant 因缺失必要证据无法验证且该证据属于当前 Gate 必须项。

NO-GO 必须只列真正阻塞项，不得把 MINOR / SUGGESTION 混入 blocking list。

`GO / NO-GO` 是本次审计对现有 Gate 的 review verdict，不创建新的质量层级，也不能替代 Final-SHA Certification 的 `ACCEPTED / REJECTED`。

---

## 15. Invariant Matrix 输出

最终报告必须包含：

| Invariant | Status | Evidence |
|---|---|---|
| INV-... | PASS | ... |
| INV-... | FAIL | F-... |
| INV-... | NOT_VERIFIED | missing evidence |

状态只能是：

```text
PASS
FAIL
NOT_VERIFIED
```

`NOT_VERIFIED` 不自动等于 defect。只有当该 invariant 的验证证据属于当前 Gate 必须项时，它才会造成 NO-GO。

---

## 16. 标准最终报告

完整审计至少输出：

```text
1. Audit Base / Head / Scope
2. Executive Summary
   BLOCKER: N
   MAJOR: N
   MINOR: N
   SUGGESTION: N
3. Previous Findings Status
4. Invariant Matrix
5. New Findings
6. Verification Evidence
7. Technical Debt / Suggestions
8. GO / NO-GO
9. Blocking Reasons（仅 NO-GO）
```

并明确回答：

```text
设计是否被正确实现？ YES / NO
是否违反唯一性？     YES / NO
是否违反确定性？     YES / NO
是否违反 ADR/架构？  YES / NO
是否可进入下一阶段？ GO / NO-GO
```

---

## 17. 审计停止条件

当当前 Scope 满足：

```text
BLOCKER = 0
MAJOR = 0
Applicable core invariants = PASS
Required current-Gate evidence = sufficient
```

本轮审计必须停止并给出 `GO`。

不得为了清零 MINOR / SUGGESTION 无限延迟下一 Task / Increment / Milestone。

如果后续获得真正的新证据，可以在新的明确基线上重新审计；不能通过无限扩大同一轮 scope 来追求“绝对没有任何可改进之处”。

---

## 18. 最终原则

所有 Reviewer 与 Agent 必须遵守：

```text
Audit proves conformance; it does not continuously redesign the system.

Evidence before opinion.
Frozen design before reviewer preference.
Invariant before abstraction.
Correctness before elegance.
Minimum sufficient mechanism before architectural complexity.
Blocking severity is determined by impact, not by number of suggestions.
A completed audit must converge.
```
