# ADR 0078 — Impact-Aware Local Verification Is Not Certification Authority

- 状态：Accepted
- 日期：2026-08-14
- 修订：2026-08-27 — 增加 Local Verification Budget / CI Delegation
- 关联模块：`scripts/test_suite.py`、`scripts/verify.py`、`scripts/local_verify.py`、Engineering Quality System

## 背景

Agent 在小改动后反复执行完整 `release`，会重复运行与 change 无关的重型 lane，并把大量成功输出送入有限的开发上下文。局部实现
反馈、development proof 与 immutable final repository proof 是不同 authority boundary。优化反馈不能降低 canonical lane、coverage、
build、Semgrep、CodeQL 或 exact-SHA certification 的严格度。

P7.5.2 已建立 impact-aware planning，但实践中仍存在第二类浪费：

```text
impact planner correctly selects a broad/full required set
→ agent immediately executes all of it locally
→ core-full / coverage / recovery / PostgreSQL / Web E2E are repeated before CI
```

这不是 impact selection 错误，而是“required proof”和“local execution placement”没有分开。

## 决策

正式质量层级仍只有：

```text
Task Gate
Phase Gate
Certification Gate
```

本 ADR 只规定验证执行位置，不创建第四种 Gate。

建立以下执行链：

```text
Targeted Inner Loop
→ Impact-Aware Local Verification
→ PR/Main CI
→ Nightly Heavy Quality
→ Final-SHA Certification
```

其中：

- `scripts/test_suite.py` 继续唯一拥有 canonical lane/check semantics；
- `scripts/verify.py` 继续唯一拥有 impact selection 和完整 required impact set；
- `scripts/local_verify.py` 只拥有 local execution budget / defer policy；
- local budget 不得复制 pytest path、marker、worker、coverage threshold 或 dependency map。

`scripts/verify.py` 继续使用显式 base，合并 `base..HEAD`、staged、unstaged、untracked、rename 和 delete，按 typed explicit rules 产生
deterministic monotonic plan。Unknown path 和 verification infrastructure self-change 仍 fail closed 到 broad/full required set。

新的关键规则是：

```text
required impact set
!=
must execute every required command in the agent's local loop
```

当完整 required plan 超过默认 local budget 时，`scripts/local_verify.py` 允许把昂贵 proof 显式标记为 `CI_REQUIRED` 并交给 GitHub CI。
这不是 skip：

- deferred command 继续保留在 required plan；
- local manifest 必须列出 `deferred_to_ci`；
- local command 不能把 deferred proof 声称为 PASS；
- `scripts/local_verify.py run` 在存在 defer 时返回专用 exit code `3`；
- Task 最终报告必须把 Local PASS、CI PASS、NOT EXECUTED、CI REQUIRED 分开。

默认 deterministic local budget 为 `10` cost units。Cost unit 只是 scheduling policy，不是 correctness threshold，也不承诺固定秒数。

当 required plan 在预算内时，本地完整执行。超过预算时，只允许运行预算内的低成本 preflight/static proof；重型 canonical proof 交给
CI。完整本地执行只允许显式 opt-in：

```bash
uv run python scripts/local_verify.py run --base <TASK_BASE_SHA> --full-local
```

Agent 日常默认不得自行运行：

```text
release
core-full
core-full --coverage
all Research lanes bundle
recovery + sim-recovery routine pair
exhaustive
mutation
performance
full Web E2E
Final-SHA Certification
```

除非用户、Task Contract、CI failure reproduction 或显式 `--full-local` 要求。

Local runner 继续采用 concise failure-first output；完整成功日志落盘，不进入 Agent 上下文。

Final-SHA Certification workflow 不读取 impact plan 或 local budget，也不按 changed files 跳过 mandatory gate。

更完整的执行规则见：

```text
docs/engineering/local-verification-execution-policy.md
```

## 备选方案

### 每次修改运行完整 release

能够提供宽验证，但把昂贵 proof 放在错误的反馈边界，造成重复 wall-clock 和日志上下文成本。

### 让 impact planner 自己删除重型 lane

拒绝。Impact planner 的职责是证明“需要什么”，不是决定“在哪里执行”。删除 lane 会把执行优化变成 correctness 缩窄。

### Opaque 或历史相关性 test selection

无法解释和审计，未知路径可能产生空计划，不满足 fail-closed 与确定性要求。

### Final-SHA changed-file skipping

会让最终 repository proof 依赖不完整 impact map，直接削弱 certification authority，因此拒绝。

### Failure 自动 rerun

可能掩盖 nondeterminism，不能替代根因诊断，因此拒绝。

## 结果

Agent inner loop 不再默认收集 full coverage 或反复执行 `release`。稳定后先运行 targeted tests，再由
`scripts/local_verify.py` 消费 `scripts/verify.py` 的完整 impact plan。

小型 component change 可以在本地完成 affected proof；broad/full/heavy change 会明确进入：

```text
LOCAL_PASS_CI_REQUIRED
```

或：

```text
LOCAL_DEFERRED_TO_CI
```

而不是把几十分钟测试强制塞进每次 Agent 迭代。

规则需要随新 subsystem 显式维护，但未分类 path 仍升级 required plan，而不是漏测。CI、Nightly、完整 release 和 Final-SHA workflow
的既有质量语义保持不变。

## 验证

Architecture tests 固化：

- impact input-order / fresh-process determinism；
- rule union；
- unknown fallback；
- self-change escalation；
- docs-only；
- shared core/test fixture；
- dirty worktree；
- rename/delete；
- canonical lane reuse；
- compact success/failure logs；
- budget determinism；
- broad/full plan heavy defer；
- explicit `--full-local`；
- zero budget 不得静默丢失 required proof；
- local policy vocabulary 不得声称 Certification authority。

## 不变量

- No match 不等于 no impact。
- 高风险 rule 不得被低风险 rule 降级。
- Verification tooling 不能缩窄自身 required proof boundary。
- Local budget 只能改变执行位置，不能改变 required impact set。
- CI_REQUIRED 不等于 PASS。
- Local impact verification 永远不是 Final-SHA Certification authority。
- Missing、skipped、cancelled 或 failed mandatory final gate 仍只能得到 `REJECTED`。
