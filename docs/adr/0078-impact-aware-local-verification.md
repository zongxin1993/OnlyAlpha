# ADR 0078 — Impact-Aware Local Verification Is Not Certification Authority

- 状态：Accepted
- 日期：2026-08-14
- 关联模块：`scripts/test_suite.py`、`scripts/verify.py`、Engineering Quality System

## 背景

Agent 在小改动后反复执行完整 `release`，会重复运行与 change 无关的重型 lane，并把大量成功输出送入有限的开发上下文。局部实现
反馈、development proof 与 immutable final repository proof 是不同 authority boundary。优化反馈不能降低 canonical lane、coverage、
build、Semgrep、CodeQL 或 exact-SHA certification 的严格度。

## 决策

建立四级验证模型：targeted tests、affected canonical lanes、impact-aware local gate、full Final-SHA Certification。
`scripts/verify.py` 使用显式 base，合并 `base..HEAD`、staged、unstaged、untracked、rename 和 delete，按 typed explicit rules 产生
deterministic monotonic plan。Unknown path fail closed 到完整 local release gates；verification infrastructure self-change 自动升级到最宽
本地验证。

Canonical lane/check semantics 继续只由 `scripts/test_suite.py` 拥有。Impact planner 只能引用 canonical identity，不拥有 pytest path、
marker、worker、coverage 或 release matrix。Runner 默认压缩 console output，完整日志和 local manifest 落盘。Local verdict 只能是
`VERIFICATION_PASSED/FAILED`，不能使用 `CERTIFIED/ACCEPTED`。

Final-SHA Certification workflow 不读取 impact plan，也不按 changed files 跳过任何 mandatory gate。

## 备选方案

### 每次修改运行完整 release

能够提供宽验证，但把昂贵 proof 放在错误的反馈边界，造成重复 wall-clock 和日志上下文成本。

### Opaque 或历史相关性 test selection

无法解释和审计，未知路径可能产生空计划，不满足 fail-closed 与确定性要求。

### Final-SHA changed-file skipping

会让最终 repository proof 依赖不完整 impact map，直接削弱 certification authority，因此拒绝。

### Failure 自动 rerun

可能掩盖 nondeterminism，不能替代根因诊断，因此拒绝。

## 结果

Agent inner loop 不再默认收集 coverage 或反复执行 `release`；稳定后运行受影响 canonical lanes 和保守 local gate。规则需要随新 subsystem
显式维护，但未分类 path 会升级而不是漏测。完整 release 和 Final-SHA workflow 的既有语义保持不变。

## 验证

Architecture tests 固化 input-order/fresh-process determinism、rule union、unknown fallback、self-change escalation、docs-only、shared
core/test fixture、dirty worktree、rename/delete、canonical reuse、compact success、failure diagnostics 和 manifest authority。

## 不变量

- No match 不等于 no impact。
- 高风险 rule 不得被低风险 rule 降级。
- Verification tooling 不能缩窄自身 proof boundary。
- Local impact verification 永远不是 Final-SHA Certification authority。
- Missing、skipped、cancelled 或 failed mandatory final gate 仍只能得到 `REJECTED`。
