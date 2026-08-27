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

---

## 12. Agent 本地验证执行合同

本节是所有实现、修复、重构和测试任务的默认执行规则。详细机制见：

```text
docs/adr/0078-impact-aware-local-verification.md
docs/engineering/local-verification-execution-policy.md
```

正式质量层级仍只有：

```text
Task Gate
Phase Gate
Certification Gate
```

以下只是执行策略，不是新的 Gate。

### 12.1 默认顺序

Agent 修改代码后必须优先：

```text
1. targeted direct tests
2. targeted Ruff / Mypy / contract checks
3. impact plan
4. budgeted local verification
5. PR / GitHub CI for deferred heavy proof
```

Targeted pytest 默认使用：

```bash
uv run pytest <targets> -q --tb=short --maxfail=1
```

Impact-aware 本地入口统一为：

```bash
uv run python scripts/local_verify.py plan --base <TASK_BASE_SHA>
uv run python scripts/local_verify.py run --base <TASK_BASE_SHA>
```

不得自行维护第二套 changed-file → test-lane 映射；impact authority 仍只来自：

```text
scripts/verify.py
```

canonical lane semantics 仍只来自：

```text
scripts/test_suite.py
```

### 12.2 默认禁止重型本地全套验证

除非用户显式要求、Task Contract 明确要求、需要复现 CI-only failure，或显式使用 `--full-local`，Agent **不得默认本地运行**：

```text
scripts/test_suite.py release
core-full
core-full --coverage
all Research lanes bundle
recovery + sim-recovery routine pair
exhaustive
mutation
performance
full Playwright E2E
Final-SHA Certification
```

这不是降低测试要求，而是把昂贵证明放到 GitHub CI / Nightly / Final-SHA authority boundary。

### 12.3 Local Budget 不能减少 Required Impact

当完整 impact plan 超过本地预算时：

```text
required plan remains unchanged
+
low-cost local preflight may run
+
remaining commands are CI_REQUIRED
```

Agent 必须保留并报告全部 `deferred_to_ci`，不得把它们写成 PASS。

`scripts/local_verify.py run` 返回：

```text
0 = all required local impact commands passed inside budget
1 = local failure
2 = invalid plan/input
3 = CI_REQUIRED
```

Exit code `3` 不是 PASS。

收到 `3` 时，Agent 可以在 targeted/local evidence 已准备好的前提下创建或更新 PR，让 GitHub CI 完成重型证明；在 CI 真正 PASS 前，不得声称这些 gate 已通过。

### 12.4 Full Local 必须显式 Opt-in

完整本地 impact plan 只能显式执行：

```bash
uv run python scripts/local_verify.py run \
  --base <TASK_BASE_SHA> \
  --full-local
```

`--full-local` 不得成为 Codex/Agent 默认命令。

### 12.5 Coverage 与日志

本地 inner loop 默认不运行 whole-repository coverage。生产代码只有在 Task Contract 要求时运行 affected package/lane coverage；`core-full --coverage` 默认交给 CI。

成功测试日志不得大量复制进 Agent 上下文。完整日志写入 `test-results/verification/`；失败时只展示：

```text
gate
command
exit code
short diagnostic
full log path
```

### 12.6 最终报告

Agent 最终报告必须显式区分：

```text
Local PASS
CI PASS
NOT EXECUTED
CI REQUIRED
```

只要存在未由 CI 关闭的 `CI_REQUIRED`，就不得使用：

```text
all tests passed
```

未知 impact 和 verification infrastructure self-change 仍由 `scripts/verify.py` fail closed 到 broad/full **required plan**；本地预算只改变执行位置，不改变 required proof。
