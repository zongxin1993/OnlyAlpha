# ADR 0079 — Deterministic Research Sweep Is Multi-Job Composition

- 状态：Accepted
- 日期：2026-08-14
- 关联模块：`onlyalpha.calculation`、`onlyalpha.research.sweep`、`onlyalpha.research.job`

## 背景

P7.4 已建立 exact Dataset Snapshot + canonical Calculation Graph 的单 Job authority，P7.5 已让 Factor/Score 复用同一
Calculation/Result/Job 链。参数扫描必须把有限参数问题确定性编译为多个现有 Job，而不能成为第二套 Calculation Engine、Result
Store 或 mutable Trial lifecycle。已有 resolved Definition 包含 parameter-derived warmup、source binding 和跨参数约束，因此仅替换
`parameters` 会制造新旧语义混合的非法 Definition。

## 决策

Calculation Registry 增加 backend-neutral Definition re-materialization contract。Exact semantic type 自有 resolver 接收 requested
parameters 与 composition input bindings，重新执行 ParameterSchema normalization、完整 warmup/source/default/constraint resolution，
最终仍只产生现有 `OnlyCalculationDefinition`。Resolver class/module/provider identity 不进入任何 semantic fingerprint；同一
`type_id@semantic_version` 在不升级版本时改变 resolver 行为属于 contract violation。

Research Sweep 使用 serializable Graph Template。`TemplateNodeId` 是 template-local topology/target key，不是 Calculation node
fingerprint，也不是 presentation alias。Template dependency 在物化时解析为实际 upstream fingerprint 的
`OnlyCalculationReference`；TemplateNodeId 不写入 Definition extension 或 materialized Graph identity。

Parameter space v1 只接受 finite explicit candidates。Candidate 通过对应 `OnlyParameterDefinition` normalization，按 typed canonical
scalar 排序；dimension 按 `(TemplateNodeId, parameter_name)` 排序，重复 normalized candidate、重复 target 和不同 assignment 物化为相同
`calculation_fingerprint` 均 fail closed。Workload 是有限 Cartesian product；`max_cells` 仅为 operational policy，不是 semantic identity。

Planner 按 canonical template topology 完整物化每个现有 `OnlyCalculationGraphDefinition` 和 `OnlyResearchJobPlan`。Cell ordinal 只用于
顺序与诊断；Cell identity 继续是现有 `calculation_fingerprint`，不新增 Cell/Trial/Sweep Job fingerprint。SweepDefinition v1 没有 durable
consumer，因此不新增 fingerprint。

Executor v1 按 canonical ordinal sequential fail-fast，并且只能调用 `OnlyResearchJobExecutor.execute()`。它不直接访问 Calculation
Executor 或 Result Store。恢复采用 deterministic re-entry：相同 Sweep 重新 planning，已有 verified Result 返回 `REUSED`，缺失 Result
返回 `EXECUTED`，corrupt authority fail closed。Outcome 是 immutable、ephemeral invocation evidence，不创建 Sweep Store、Trial DB、
checkpoint、scheduler、lease 或 worker pool。

Research Runtime Factory 继续 unsupported；P7.6 不激活 `Engine.run(RESEARCH)`。

## 备选方案

### 替换 resolved Definition.parameters

会保留旧 warmup/source binding，破坏完整 semantic resolution，因此拒绝。

### 使用 node fingerprint 或 alias 作为参数 target

Fingerprint 随参数变化，不能稳定定位；alias 已冻结为 presentation-neutral，不能升级为 semantic key，因此均拒绝。

### 新增 Trial/Sweep identity 与 Store

每个 Cell 已有完整 Calculation identity，P7.6 也没有 durable Experiment consumer；重复 identity/store 会制造第二 authority，因此拒绝。

### 并行或 adaptive execution

会把 scheduling/optimization 混入 workload semantic closure。v1 先冻结 deterministic sequential composition，未来执行器可以复用同一
immutable Plan，而不改变 Cell identity。

## 结果

未来 Experiment、Workbench、Web Preview、LLM/ML research client 可以先纯 planning 审查 ordered Cells，再在不复制
Dataset/Calculation/Result/Job authority 的前提下执行。未来 parallel executor 或 Experiment authority 必须保持本 ADR 的 identity、
verified reuse、corruption 和 fail-fast/re-entry 边界。

## 不变量

- Sweep = composition，不是第二 Calculation Engine。
- TemplateNodeId != node fingerprint != alias。
- Resolved Definition 必须完整 re-materialize。
- One Cell = one existing calculation_fingerprint。
- No Cell/Trial fingerprint；SweepDefinition v1 无 fingerprint。
- No Sweep/Trial Store、mutable progress、scheduler 或 worker pool。
- SweepExecutor 只调用 JobExecutor。
- Recovery = same deterministic plan + verified Result reuse。
