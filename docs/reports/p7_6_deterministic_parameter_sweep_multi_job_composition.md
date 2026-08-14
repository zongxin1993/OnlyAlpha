# P7.6 Deterministic Parameter Sweep & Multi-Job Composition Implementation Report

## Baseline

- Starting SHA: `13d095b9a69985015c43f0842fd42643314303a9`
- Starting commit: `Feat: P7 Quality Gate Granularity Closure`
- Ending state: implementation working tree on `master`（未创建 ending commit）
- Version: `0.4.4`
- Date: 2026-08-14

开始时工作树已有用户修改的
`prompts/P7.6DeterministicParameterSweep&Multi-JobComposition.md`；实施保留该修改，没有把 Prompt 当作源码 authority 覆盖。

## Entry Gate

Current README、roadmap、AGENTS 与 Engineering Quality System 均记录 P7.5.2 和 P7 Quality Gate Granularity Closure 为
`VERIFIED`，并明确同一 P7 milestone 的前一 increment 达到 `VERIFIED` 即可开始 P7.6。P7.6 不属于 release/tag、Live deployment、
重大 persistence migration、Runtime/Recovery authority refactor 或 nondeterminism incident closure，因此不要求 standalone Final-SHA
Certification。

## Current Authorities

- Dataset：verified immutable Dataset Snapshot。
- Calculation：resolved `OnlyCalculationDefinition` 与 canonical `OnlyCalculationGraphDefinition`。
- Result：以 `calculation_fingerprint` 为 durable key 的 immutable Parquet Result Store。
- Job：exact Dataset Snapshot + canonical Graph 的 `OnlyResearchJobPlan`，由 `OnlyResearchJobExecutor` 执行 verified reuse-or-execute。
- Factor：复用 Calculation Definition/Graph/Result/Job，不创建 Factor-specific Store/Job。

Sweep 只新增 composition authority，不修改以上 durable authority。

## Definition Re-materialization

Parameter-only replacement 不正确，因为 period、price_field、MACD period/default 等参数会派生 warmup、source binding 与跨参数约束。
Core Calculation Registry 新增 backend-neutral exact-type Definition resolver contract；官方 Indicator 与 Factor plugin 各自拥有完整
type resolution，并把同一 resolver 绑定到 exact semantic registration。Sweep 只向 Registry 提交 exact type reference、requested
parameters 和 composition bindings，不复制 EMA/MACD/ATR/Momentum/Percentile 规则。

Resolver/provider class path、module path 和 object identity 不进入 Definition、Graph、Calculation 或 Result fingerprint。Base candidate
regression 证明 Sweep materialized official Factor Graph 与 P7.5 existing resolution path 保持相同 Graph/Calculation identity。

## Graph Template

Serializable Graph Template 使用 `TemplateNodeId` 表达 template-local topology、parameter target 与 dependency reference。
TemplateNodeId 不等于 Calculation node fingerprint，也不等于 presentation alias；物化时 template reference 转换为 actual upstream
fingerprint 的 existing `OnlyCalculationReference`，最终对象仍是 existing `OnlyCalculationGraphDefinition`。Template ID 不写入 Definition
extension 或任何 Calculation identity。

## Parameter Space

P7.6 v1 只接受 finite explicit candidates。每个 candidate 复用 exact type 的 `OnlyParameterDefinition.normalize()`，并按 typed scalar
canonical key 排序；dimension 按 `(TemplateNodeId, parameter_name)` 排序。Planner 执行 deterministic finite Cartesian product并在执行前
暴露 `cell_count`。Duplicate target、duplicate normalized candidate、invalid candidate、unknown target/type/version/parameter 与 duplicate
materialized Calculation identity 均 fail closed。`max_cells` 是 operational limit，不进入 semantic identity。

## Materialization and Identity

Planner 按 canonical topological template order：应用 cell assignment、解析已物化 upstream reference、调用 exact resolver、构建完整
Definition、构建 existing Graph，再创建 existing `OnlyResearchJobPlan`。上游参数变化自然传播到 downstream Definition/Graph/Calculation
fingerprint；独立节点保持稳定。

Cell ordinal 只用于顺序与诊断。Cell 的正式 identity 是 `OnlyResearchJobPlan.calculation_fingerprint`；没有 Trial/Cell/Sweep Job
fingerprint。SweepDefinition v1 没有 durable consumer，因此不创建 fingerprint。

## Execution and Recovery

`OnlyResearchSweepExecutor` 只接受 `OnlyResearchJobExecutor`，按 canonical ordinal sequential fail-fast。它不调用 Calculation Executor，
不调用或持有 Result Store。Outcome 是 immutable ephemeral invocation evidence，只记录 ordered assignment、Calculation/Result identity 与
`EXECUTED/REUSED` disposition，不复制 Result payload。

Recovery 是 deterministic re-entry：同一 Definition 重新得到相同 Plan，verified Result 返回 `REUSED`，missing Result 返回
`EXECUTED`。Partial completion 与 clean run 收敛到相同 Result identity set；corrupt Result 在对应 Cell 保留 Job phase/code 并 fail
closed，不重算、不删除、不覆盖、不修复。没有 Sweep/Trial DB、checkpoint、lease、scheduler、worker pool 或 mutable progress。

## Verification

实际证据：

- Targeted Sweep contract/materialization/execution/architecture：PASS，27 tests（coverage run）。
- `research-sweep --coverage`：PASS，96.47% line / 92.06% branch。
- Targeted Definition re-materialization：PASS，4 tests。
- Targeted verification/lane/certification contracts：PASS，33 tests。
- Final impact-aware broad/full local verification：执行 1 次；9 static checks 与 11 canonical lanes 全部 PASS，共 2,339 tests。
- Final all-package build：impact runner 内首次因 sandbox 禁止访问 PyPI 而失败；仅对同一 build gate 使用批准的网络边界重跑，8 个
  workspace packages 的 sdist/wheel 全部 PASS。没有重复已经 PASS 的 static/lanes。

完整成功日志由 canonical lane/impact-aware runner 保存在 `test-results/`；本报告不粘贴 raw stdout。

## Verification Efficiency

Inner loop 只执行 Sweep/resolver 和受影响 architecture tests，并使用 `-q --tb=short --maxfail=1`。Production 与 tests 稳定后才集中修改
`test_suite.py`、`verify.py` 和 workflows。Final tree 只计划执行一次 impact-aware broad/full proof；若该 runner 已覆盖 static、全部 required
lanes 与 build，不再重复运行 `test_suite.py release`。

## Architecture Review

Architecture gate 禁止 Sweep import Trading authorities、直接使用 Calculation Executor/Result Store、创建 parallel Graph/identity/durable
lifecycle 或激活 Research Runtime。Review checklist 已检查 warmup/source drift、MACD derived semantics、plugin rule copying、backend coupling、
TemplateNodeId/alias identity leakage、duplicate authority、Job bypass、corrupt-as-miss、mutable progress、ordering与 float range drift。

## State

P7.6 Increment State: `VERIFIED`。

Standalone P7.6 Final-SHA Certification: `NOT REQUIRED`。

P7 Final-SHA Certification: `REQUIRED AT P7 FINAL CLOSURE`。

## Remaining Risks

- v1 是 sequential execution；未来 parallel executor 必须复用相同 immutable Plan 和 Cell identity。
- Experiment/Statistics/Optimization 尚未建立，未来 durable Experiment authority 不得替代 Calculation Result authority。
- Layered Quality 在 master push 仍运行较重完整 matrix；dynamic changed-file CI 是独立 engineering efficiency work。
- Research Runtime Factory 继续 intentionally unsupported。
