# OnlyAlpha Agent Override — Mandatory Audit Entry Contract

本文件是 OnlyAlpha 根目录 Agent 的高优先级入口约束。它**补充而不削弱** `AGENTS.md`。

`AGENTS.md` 仍是完整工程执行合同；任何 Agent、Codex、Reviewer 或自动化工具在进行非微小工作时，都必须按任务范围显式读取其中相关章节、当前源码、正式测试和未被替代 ADR，不得仅依赖本文件的摘要。

---

## 1. 审计 / Review / Certification 的强制入口

当用户任务包含以下任一意图时：

```text
audit
review
re-audit
architecture review
correctness review
regression review
milestone review
phase review
certification review
检查是否可以进入下一阶段
检查是否符合设计/架构
检查唯一性/确定性
修复后的再次审计
```

在产生任何 Finding、Severity、GO / NO-GO、PASS / FAIL 或“是否可以进入下一阶段”的结论前，**必须完整读取并遵守**：

```text
docs/engineering/convergent-audit-policy.md
```

并按任务需要继续读取：

```text
AGENTS.md
docs/engineering/quality-system.md
相关 active ADR
相关 architecture / component docs
相关 acceptance criteria
当前实现与测试
上一轮 audit findings（若为复审）
```

不得只根据 Prompt、旧对话、历史报告或 reviewer 记忆审计当前代码。

---

## 2. 审计不是重新设计

审计唯一目标是证明当前实现是否满足已经冻结的系统约束。

强制优先级：

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

存在“更优雅、更通用、更未来化”的方案，不代表当前实现失败。

如果 frozen design 本身可能存在问题，必须单独形成 `DESIGN CHANGE PROPOSAL`；在设计正式变更前，不得用 reviewer 的替代设计判当前实现失败。

---

## 3. Finding 必须可证明

BLOCKER / MAJOR 必须同时具有：

```text
具体代码 / Schema / Test 证据
+
明确违反的 invariant / ADR / frozen design / acceptance criterion
+
真实工程影响
+
可复现的推理链
```

无证据的：

```text
可能……
理论上……
似乎……
最好……
未来可以……
建议考虑……
```

不得升级为 BLOCKER / MAJOR。

---

## 4. 固定严重度

审计 Finding 只允许：

```text
BLOCKER
MAJOR
MINOR
SUGGESTION
```

含义：

- `BLOCKER`：核心 invariant、durable correctness、唯一性、必要确定性、可恢复状态或当前 Gate 被破坏；对应质量体系 Critical 阻塞级。
- `MAJOR`：有明确证据违反 frozen design、active ADR、architecture boundary 或当前 acceptance criteria，且具有真实影响；对应质量体系 High 阻塞级。
- `MINOR`：真实工程质量问题，但不破坏当前 correctness / contract；不阻塞下一阶段。
- `SUGGESTION`：可选优化、命名、额外抽象、未来扩展或 non-required hardening；不是 defect，不阻塞下一阶段。

不得为了让审计“看起来严格”提升严重度。

---

## 5. 复审必须收敛

存在上一轮 Finding 时，必须先复核原 Finding，状态只能是：

```text
RESOLVED
PARTIALLY_RESOLVED
NOT_RESOLVED
REGRESSED
```

不得把同一问题重新命名后作为“新问题”重复计数。

新增 BLOCKER / MAJOR 必须说明为何上一轮没有报告，并分类为：

```text
PREVIOUSLY_HIDDEN
INTRODUCED_BY_FIX
PREVIOUSLY_OUT_OF_SCOPE
NEW_REGRESSION
```

无法说明时，优先检查是否属于 reviewer preference drift、scope creep、speculative architecture 或原 Finding 的未闭环部分。

---

## 6. 审计必须先建立 Invariant Matrix

完整审计产生 Finding 前，先建立当前 scope 的 invariant matrix，至少按实际影响检查：

```text
identity uniqueness
deterministic canonicalization / fingerprint
single authority / state ownership
immutability
durable authority
architecture dependency direction
Research / Trading / Runtime boundary
persistence uniqueness / transactionality
retry / replay / recovery idempotency
public contract / schema
fail-closed semantics
result / artifact provenance
```

不得先认定代码“有问题”，再倒推一个不存在的 invariant。

---

## 7. 唯一性与确定性是正式审计轴

唯一性检查必须覆盖完整链路，而不是只看 hash：

```text
semantic input
→ normalization
→ canonical representation
→ serialization
→ fingerprint / identity
→ persistence constraint
→ concurrent create
→ retry / replay / import / recovery
```

确定性必须验证：

```text
Same semantic input
+ same explicit configuration
+ same code/schema/authority version
= same semantic output
```

特别检查 unordered iteration、DB ordering、timestamp、UUID、random、float/Decimal、timezone、serialization、provider physical order、process/machine/environment implicit input。

---

## 8. 不得创建第四种 Gate

OnlyAlpha 正式质量层级仍只有：

```text
Task Gate
Phase Gate
Certification Gate
```

其验收语义由：

```text
docs/engineering/quality-system.md
```

定义。

审计的 `GO / NO-GO` 只是对当前既有 Gate 的 review verdict，不是新的 Gate，也不能替代 Final-SHA Certification 的正式 verdict。

不得因为“审计更严格”自动要求 repository-wide release、全量 coverage 或 Final-SHA Certification；验证范围必须继续遵守 impact-aware Gate contract。

---

## 9. GO / NO-GO 与停止条件

完整审计必须明确输出：

```text
GO
```

或：

```text
NO-GO
```

满足以下条件时必须 `GO` 并停止当前审计：

```text
BLOCKER == 0
MAJOR == 0
Applicable core invariants == PASS
No known frozen-design / ADR violation
Required current-Gate evidence is sufficient
```

`MINOR` 和 `SUGGESTION` 进入 technical debt / follow-up backlog，不得阻塞当前 Task / Increment / Milestone。

不得为了清零非阻塞项无限扩大同一轮审计。

---

## 10. 标准审计输出

完整审计至少包含：

```text
1. AUDIT_BASE_SHA / AUDIT_HEAD_SHA / Scope
2. Executive Summary
   BLOCKER: N
   MAJOR: N
   MINOR: N
   SUGGESTION: N
3. Previous Findings Status
4. Invariant Matrix
5. Findings with concrete evidence
6. Verification Evidence
7. Non-blocking Technical Debt / Suggestions
8. GO / NO-GO
9. Blocking Reasons（仅 NO-GO）
```

最后必须明确回答：

```text
设计是否被正确实现？ YES / NO
是否违反唯一性？     YES / NO
是否违反确定性？     YES / NO
是否违反 ADR/架构？  YES / NO
是否可进入下一阶段？ GO / NO-GO
```

---

## 11. 最终原则

```text
Audit proves conformance; it does not continuously redesign the system.
Evidence before opinion.
Frozen design before reviewer preference.
Invariant before abstraction.
Correctness before elegance.
Minimum sufficient mechanism before architectural complexity.
A completed audit must converge.
```
