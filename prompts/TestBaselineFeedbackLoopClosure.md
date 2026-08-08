# P0 — Test Baseline & Feedback Loop Closure

## 1. P0 的目的

P0 不增加 OnlyAlpha 的任何业务能力。

P0 的目标只有两个：

```text
目标 A
建立可信的绿色 master

目标 B
建立分层、并行、可观测的测试反馈体系
```

最终应该达到：

```text
代码修改
    ↓
几分钟内
    ↓
Static / Fast / Integration / Recovery Smoke / A-share Smoke
    ↓
明确反馈

Master
    ↓
Core Full / Recovery / A-share / Build
    ↓
独立并行验证

Nightly
    ↓
Exhaustive Recovery
Determinism 100-run
大规模组合矩阵
性能观测
```

P0 不解决：

```text
Fee Authority 重构
Broker Fee Contract
正式 A 股费率
Live Runtime
Paper Recovery
向量化回测
交易算法性能
```

---

# 2. 为什么 P0 必须现在做

当前 `full` 测试的选择条件基本是：

```text
not external
not network
not Tushare
not local QMT
not broker account
not performance
```

它没有排除：

```text
recovery
conformance
exhaustive-like determinism
```

因此大量 Recovery Integration Test 实际已经进入 `full`。

然后 Release / Main Gate 又继续运行：

```text
full
↓
recovery
↓
ashare
↓
build
```

形成重复验证。

这产生三个问题：

```text
1. 普通修改反馈时间越来越长。

2. Full 中一个无关失败，
   Recovery / A-share / Build 全部看不到结果。

3. 新增任何 Recovery Matrix，
   都会进一步恶化普通 Full 的时间。
```

如果不先治理测试体系，后续：

```text
Fee Authority
A 股 Fee Pack
A 股 Durable Execution
Paper Recovery
```

都会继续增加大量故障矩阵测试。

所以现在是治理的最佳时间。

---

# 3. 第一性原则

P0 的设计必须遵循以下原则。

## 原则 1：测试层级和测试关注点不是同一个概念

当前 `pytest_layering.py` 将：

```text
unit
contract
architecture
integration
scenario

recovery
conformance
external
performance
```

全部混在 `PRIMARY_MARKERS` 中。

这是一个分类模型问题。

例如：

```text
一个测试可以同时是：

integration
+
recovery
```

Recovery 不是 Integration 的替代品。

正确模型应该是：

```text
Test Layer
    unit
    contract
    architecture
    integration
    scenario

Concern
    recovery
    conformance
    external
    performance
    exhaustive
    miniqmt
```

每个测试：

```text
Exactly One Layer

+

Zero or More Concerns
```

---

## 原则 2：快速反馈不意味着降低测试覆盖

不能通过：

```text
skip
xfail
删 Recovery Test
降低 assertion
```

让测试变快。

应该：

```text
普通 Correctness
和
Exhaustive Verification
```

分层执行。

例如：

```text
3 次 deterministic replay
    → Core correctness

100 次 deterministic replay
    → Nightly exhaustive
```

两者都保留。

---

## 原则 3：任何关键质量 Gate 都不能因为其他 Gate 失败而完全不可见

错误：

```text
Full FAIL
↓
Recovery SKIPPED
↓
A-share SKIPPED
↓
Build SKIPPED
```

正确：

```text
          Static

Core Full Recovery A-share Build
    │       │       │      │
    └───────┴───────┴──────┘
                ↓
           Quality Gate
```

---

## 原则 4：测试失败时也必须产生 Metrics

现在 Metrics Infrastructure 已经能够记录：

```text
total_seconds
setup_seconds
call_seconds
teardown_seconds

engine_run_count
sqlite_database_count
parquet_write_count

slowest_tests
marker_counts
path_counts
```

这是很好的基础。

但是失败时仍必须：

```text
写出 Metrics
上传 Artifact
```

否则最需要性能数据的时候反而没有数据。

---

# 4. P0.1 — 修复当前唯一真实 Full Failure

## 当前原因

失败测试：

```text
test_snapshot_cli_publishes_historical_node_and_exits
```

直接调用：

```text
main([
    "snapshot",
    "--config",
    "examples/configs/miniqmt_paper_macd.yaml",
    ...
])
```

因此正式示例中的 Windows：

```text
C:\国金证券QMT交易端\userdata_mini
```

进入 Plugin Lifecycle Validation。

但同文件已经有：

```python
_config(tmp_path)
```

它会：

```text
创建 tmp_path / userdata_mini

并覆盖：

data_sources[0]
.extensions
.userdata_mini_path
```

所以根因是：

> CLI 测试绕开了当前测试自己的隔离配置。

## 正确修改

不要修改：

```text
MiniQMT Path Validation
```

不要：

```text
允许 path 不存在
```

不要：

```text
CI 创建假的 C:\...
```

而是在测试中创建一个真实临时配置：

```text
examples/configs/miniqmt_paper_macd.yaml
        ↓
OnlyClusterRunConfig.load()
        ↓
normalized_payload
        ↓
userdata_mini_path = tmp_path/userdata_mini
        ↓
tmp_path/miniqmt_paper_test.yaml
        ↓
CLI snapshot --config temp_yaml
```

建议增加 Test Helper：

```python
def _write_cli_config(
    tmp_path: Path,
    config: OnlyClusterRunConfig,
) -> Path:
    ...
```

CLI 测试仍然走：

```text
真实 Config Parser
真实 CLI
真实 Plugin Factory
真实 Plugin Lifecycle
```

只是：

```text
外部环境
```

被正确隔离。

## 验收

单独运行：

```bash
uv run pytest \
  tests/integration/test_engine_paper_historical_warmup.py::test_snapshot_cli_publishes_historical_node_and_exits \
  -q
```

要求：

```text
PASS
```

并新增断言：

```text
配置中的 userdata_mini_path
位于 tmp_path
```

---

# 5. P0.2 — 重构 Test Classification

修改：

```text
scripts/pytest_layering.py
```

当前：

```python
PRIMARY_MARKERS = {
    unit,
    contract,
    architecture,
    integration,
    scenario,
    conformance,
    recovery,
    external,
    performance,
}
```

改成：

```python
LAYER_MARKERS = {
    "unit",
    "contract",
    "architecture",
    "integration",
    "scenario",
}

CONCERN_MARKERS = {
    "recovery",
    "conformance",
    "external",
    "performance",
    "exhaustive",
    "miniqmt",
}
```

## Layer 判定

必须：

```text
每个测试 exactly one layer
```

路径规则：

```text
/architecture/
    → architecture

/scenario/
    → scenario

/integration/
    → integration

/packages/
    → contract

otherwise
    → unit
```

如果测试已经显式声明 Layer：

```text
保留显式声明
```

如果有两个 Layer：

```text
pytest UsageError
```

---

# 6. Concern 必须独立附加

即使：

```python
pytestmark = pytest.mark.integration
```

文件名：

```text
test_engine_recovery_xxx.py
```

仍然必须得到：

```text
integration
+
recovery
```

不能因为已经拥有 Integration Marker 就停止分类。

建议规则：

```text
path/name 包含：

recovery
checkpoint
restart
outbox

→ recovery
```

```text
/conformance/
→ conformance
```

```text
requires_network
requires_tushare
requires_local_qmt
requires_broker_account

→ external
```

现有 External Validation 继续保留：

```text
external
但没有明确 Requirement Marker

→ UsageError
```

---

# 7. 增加 `exhaustive` Concern

正式增加：

```text
pytest.mark.exhaustive
```

更新：

```text
pyproject.toml
scripts/pytest_layering.py
scripts/pytest_metrics.py
```

`pytest_metrics.py` 当前已经认识：

```text
unit
integration
recovery
slow
performance
...
```

需要增加：

```text
exhaustive
```

---

# 8. 什么测试应该标记 Exhaustive

不是简单按“执行时间长”分类。

只有以下语义属于 Exhaustive：

```text
100 次 deterministic replay

所有 Projection Component 的完整故障矩阵

所有 failpoint × state × mode 组合

完整 A→B→C combinatorial matrix

大规模 registration-order permutations

完整 multi-fill failure-point matrix
```

不能因为测试慢就标记 exhaustive。

例如：

```text
一次关键 SQLite reopen
一次关键 checkpoint recovery
一次基本 A→B→C restart
```

仍然属于普通 Recovery Correctness。

---

# 9. Smoke 与 Exhaustive 的关系

例如现在有：

```text
100 fresh instances
验证 reducer byte deterministic
```

应该拆成：

```text
Core:
    3~5 次
    验证 deterministic invariant

Nightly:
    100 次
    exhaustive confidence
```

不能只把原测试移走而导致普通 Gate 完全没有 Determinism Coverage。

正确结构：

```text
Determinism Contract
├── smoke
└── exhaustive
```

---

# 10. P0.3 — 重构 Test Lane

删除现在语义模糊的：

```text
FULL
```

改成明确：

```text
CORE_FULL
```

不保留 `full` Alias。

这是开发工具内部接口，不需要为了历史兼容保留旧名称。

## FAST

```text
(unit or contract or architecture)

and not recovery
and not conformance
and not external
and not performance
and not exhaustive
and not slow
```

用途：

```text
最快的领域和架构反馈
```

---

## INTEGRATION

```text
(integration or scenario)

and not recovery
and not conformance
and not external
and not performance
and not exhaustive
and not slow
```

用途：

```text
普通产品纵切面
```

---

## CORE_FULL

```text
not recovery
not conformance
not external
not performance
not exhaustive
not slow

以及排除所有 external requirement
```

即：

```text
所有普通 correctness tests
```

它不能再包含：

```text
Recovery Matrix
A-share Conformance
100-run Determinism
```

---

## RECOVERY

```text
recovery
and not external
and not exhaustive
```

用途：

```text
核心 Recovery correctness
```

至少验证：

```text
Before Commit failure

After Commit failure

Partial Projection failure

Checkpoint reopen

Outbox retry

A→B→C representative restart
```

---

## ASHARE

```text
conformance
and not external
and not exhaustive
```

用于：

```text
A-share Product Conformance
```

---

## EXHAUSTIVE

```text
exhaustive
and not external
```

用途：

```text
Nightly
```

---

## MINIQMT_CONTRACT

保持当前：

```text
contract
+
miniqmt
+
not external
```

---

## MINIQMT_LOCAL

保持：

```text
miniqmt
+
external
+
requires_local_qmt
+
windows
+
not requires_broker_account
```

它才允许真正读取：

```text
userdata_mini
xtquant
```

---

# 11. P0.4 — 一个 Lane 只启动一个 Pytest Session

当前 `test_suite.py` 对：

```python
WORKSPACE_TESTS = (
    "tests",
    "packages/fake/...",
    "packages/provider/tushare/...",
    "packages/provider/miniqmt/...",
)
```

实际会逐个 Path 建立 Pytest Session。

也就是类似：

```text
pytest tests
结束

pytest broker-plugin/tests
结束

pytest tushare/tests
结束

pytest miniqmt/tests
```

这带来：

```text
重复 collection
重复 xdist worker startup
重复 plugin loading
重复 Python bootstrap
```

而且：

```text
第一组失败
→ 后面路径不运行
```

## 建议改成

同一个 Lane：

```bash
pytest \
  tests \
  packages/fake/.../tests \
  packages/provider/.../tests \
  ...
```

一次完成。

只有确实需要特殊 Python 环境的 Lane：

```text
MINIQMT_LOCAL
```

才单独运行。

这样：

```text
一个 Lane
=
一个 pytest session
=
一组 xdist workers
=
一个 Metrics Artifact
```

---

# 12. P0.5 — 失败时也必须生成 Metrics

当前 `execute()` 如果 pytest 返回非 0：

```python
if code not in (0, 5):
    return code
```

会提前退出后续聚合逻辑。

应该调整成：

```text
run pytest
↓
保存 exit_code
↓
读取/合并 metrics
↓
打印 metrics summary
↓
最后 return exit_code
```

即：

```python
code = run(...)

merge_metrics(...)

return code
```

不能：

```text
失败
→ Metrics 消失
```

---

# 13. Metrics 输出目录不要再使用隐藏目录

当前：

```text
.test-metrics/
```

而 GitHub `upload-artifact` 默认：

```text
include-hidden-files = false
```

所以即使产生文件，也存在 Artifact Upload 不可见的问题。

建议直接改成：

```text
test-results/
    metrics/
```

例如：

```text
test-results/metrics/core-full.json
test-results/metrics/recovery.json
test-results/metrics/ashare.json
```

而不是通过：

```text
include-hidden-files: true
```

继续依赖隐藏目录。

这是 CI Artifact，不应该是隐藏状态目录。

---

# 14. Metrics 必须至少输出

每个 Lane：

```text
commit
lane

collected
passed
failed
skipped

total_seconds
setup_seconds
call_seconds
teardown_seconds

engine_run_count
sqlite_database_count
parquet_write_count

slowest_tests

marker_counts
path_counts
```

这些当前 Metrics Infrastructure 已基本支持。

额外增加：

```text
exhaustive_test_count
recovery_test_count
conformance_test_count
```

用于检查 Lane 是否错误重叠。

---

# 15. 增加 Lane Contract Test

这一步很重要。

测试 Test Framework 本身。

新增：

```text
tests/architecture/test_test_lane_contract.py
```

验证：

```text
CORE_FULL
不得包含 recovery

CORE_FULL
不得包含 conformance

CORE_FULL
不得包含 exhaustive

RECOVERY
必须只包含 recovery concern

ASHARE
必须只包含 conformance concern

EXHAUSTIVE
必须只包含 exhaustive concern
```

以及：

```text
每个测试
Exactly One Layer
```

这样以后新增测试时不会重新污染 Full。

---

# 16. P0.6 — CI 从串行改成并行

## 当前

```text
main-gate
    full
      ↓
    recovery
      ↓
    ashare
      ↓
    build
```

改成：

```text
                   ┌─ Static
                   │
                   ├─ Core Full
Push / PR ─────────┼─ Recovery
                   │
                   ├─ A-share
                   │
                   ├─ MiniQMT Contract
                   │
                   └─ Build
```

所有 Job：

```text
fail-fast: false
```

最终增加：

```text
quality-gate
```

依赖全部 Job。

---

# 17. PR Gate

PR 建议执行：

```text
Static

Fast
Integration
Recovery
A-share
MiniQMT Contract
Build
```

并行。

原因：

```text
Recovery 仍然是 OnlyAlpha 核心架构能力，
不能完全等到 merge 后才知道是否坏掉。
```

但这里运行的是：

```text
Recovery Correctness
```

不是 Exhaustive Recovery。

---

# 18. Master Gate

Master Push：

```text
Static
Core Full
Recovery
A-share
MiniQMT Contract
Build
```

全部并行。

最终：

```text
quality-gate
```

要求全部成功。

任何一个失败：

```text
master = RED
```

但是其他 Job 仍继续完成。

---

# 19. Nightly

Nightly 执行：

```text
Core Full

Recovery

A-share

Exhaustive

Determinism Exhaustive

Benchmark / Metrics

Build
```

其中：

```text
100-run determinism
全 Projection failure matrix
大组合 restart matrix
```

进入：

```text
EXHAUSTIVE
```

而不是普通 `CORE_FULL`。

Nightly 仍然可以慢。

因为它的职责不是：

```text
开发反馈
```

而是：

```text
深度置信度
```

---

# 20. Recovery Smoke 不能过度削弱

P0 不能把所有慢 Recovery 都扔进 Nightly。

普通 PR Recovery 必须至少保留一个代表：

```text
Commit boundary

Projection boundary

Checkpoint reopen

Pending outbox

A→B→C

Multi-fill

Long close
```

这确保：

```text
开发者改 Transaction Kernel
```

仍然会在 PR 阶段看到关键错误。

---

# 21. 性能治理目标

P0 的目的不是承诺：

```text
所有测试 < 1 秒
```

这不现实，也没有必要。

当前 `pytest_metrics.py` 的：

```text
unit > 1s
integration > 10s
recovery > 30s
```

只是 Observation Warning。

继续保持：

```text
Warning
```

不要直接变成失败 Gate。

P0 应关注：

```text
Lane Wall Time
```

而不是强迫单测试预算。

---

# 22. 建议初始目标

这些是工程目标，不是硬编码测试阈值：

```text
FAST
    ≤ 2 min

INTEGRATION
    ≤ 3 min

CORE_FULL
    ≤ 5 min

RECOVERY
    ≤ 5~8 min

ASHARE
    ≤ 5 min
```

因为 Job 并行：

```text
PR/Main Wall Time
≈ 最慢一个 Lane

而不是所有 Lane 时间相加
```

Nightly：

```text
允许几十分钟甚至更长
```

只要不阻塞日常开发。

如果第一次治理后达不到这些数字：

```text
记录真实基线
```

不要为了数字删除测试。

---

# 23. P0 不优化 Runtime 业务代码性能

当前有很多慢测试，例如：

```text
Recovery A→B→C
Multi-fill
Checkpoint
Artifact
```

P0 不应该为了让测试变快而：

```text
修改 Runtime Transaction
减少 Durable Write
绕开 SQLite
禁用 Artifact
```

除非明确证明是：

```text
测试 Fixture 重复构造
```

导致。

P0 优先优化：

```text
Test Selection

Test Classification

Pytest Session Count

Worker Startup

CI Parallelism

Duplicate Matrix

Metrics
```

不是：

```text
Production correctness path
```

---

# 24. 允许做的 Test Infrastructure 性能优化

例如：

```text
复用 immutable test reference data

复用只读 config fixture

避免每个参数 case 都重新 parse 大型 YAML

减少重复 plugin discovery

同一 lane 只启动一次 pytest

只把真正 exhaustive 的 100-run 放 Nightly
```

但是禁止跨测试共享：

```text
Runtime mutable state

SQLite mutable state

Order authority

Checkpoint state
```

以免造成测试串扰。

---

# 25. 修改文件建议

核心修改：

```text
tests/integration/
    test_engine_paper_historical_warmup.py

scripts/
    pytest_layering.py
    pytest_metrics.py
    test_suite.py
    benchmark_test_lanes.py

.github/workflows/
    quality.yml
    nightly.yml

pyproject.toml

tests/architecture/
    test_test_lane_contract.py

docs/
    testing.md

docs/reports/
    p0-test-baseline-feedback-loop-closure.md
```

如果还有：

```text
README
AGENTS
```

引用旧 `full` 命令，也同步更新。

---

# 26. Commit 顺序

## Commit 1 — Fix MiniQMT Test Isolation

只修：

```text
当前唯一 Full Failure
```

不做 Lane 改造。

先证明：

```text
原始 Full
```

在功能上能通过。

这样能够区分：

```text
测试功能缺陷
```

和：

```text
测试基础设施改造
```

---

## Commit 2 — Orthogonal Test Classification

重构：

```text
Layer
Concern
Exhaustive
```

增加 Architecture Contract。

不修改 CI。

---

## Commit 3 — Test Lane Redesign

增加：

```text
FAST
INTEGRATION
CORE_FULL
RECOVERY
ASHARE
EXHAUSTIVE
MINIQMT_CONTRACT
MINIQMT_LOCAL
```

删除旧：

```text
FULL
```

更新所有调用者。

---

## Commit 4 — Runner & Metrics Closure

完成：

```text
one lane → one pytest process

failure still writes metrics

test-results/metrics/

lane summaries
```

---

## Commit 5 — CI Parallelization

修改：

```text
quality.yml
nightly.yml
```

形成：

```text
independent jobs
+
final quality gate
```

---

## Commit 6 — Exhaustive Migration

根据 Metrics：

```text
识别 combinatorial / 100-run tests
```

拆成：

```text
smoke
+
exhaustive
```

不能只移动测试。

---

## Commit 7 — Documentation & Final Baseline

记录：

```text
Before
After

Lane counts
Lane times
Slowest tests
CI wall time
```

---

# 27. 最终测试命令

完成后本地应有：

```bash
uv run python scripts/test_suite.py fast

uv run python scripts/test_suite.py integration

uv run python scripts/test_suite.py core-full

uv run python scripts/test_suite.py recovery

uv run python scripts/test_suite.py ashare

uv run python scripts/test_suite.py miniqmt-contract

uv run python scripts/test_suite.py exhaustive
```

Release：

```bash
uv run python scripts/test_suite.py release
```

其逻辑：

```text
Static

Core Full

Recovery

A-share

MiniQMT Contract

Build
```

本地 Release 可以串行。

CI 不需要复制这个串行逻辑。

CI 应并行。

---

# 28. Definition of Done

P0 完成必须满足：

```text
[ ] MiniQMT snapshot CI test 不依赖真实 Windows path

[ ] Static PASS

[ ] Core Full PASS

[ ] Recovery PASS

[ ] A-share PASS

[ ] MiniQMT Contract PASS

[ ] Build PASS

[ ] Exactly one layer per test

[ ] recovery 是独立 concern

[ ] conformance 是独立 concern

[ ] exhaustive 是独立 concern

[ ] Core Full 不包含 Recovery

[ ] Core Full 不包含 A-share Conformance

[ ] Core Full 不包含 Exhaustive tests

[ ] Recovery 保留关键 smoke coverage

[ ] Exhaustive coverage 没有删除

[ ] 100-run Determinism 仍存在 Nightly

[ ] 一个 Lane 不重复启动多个 pytest session

[ ] Test failure 仍产生 Metrics

[ ] Metrics Artifact 可上传

[ ] CI 各核心 Gate 并行

[ ] 一个 Gate 失败不会隐藏其他 Gate 结果

[ ] Nightly 承担 exhaustive verification

[ ] 没有 skip / xfail / assertion weakening

[ ] 没有为了测试速度修改交易业务语义
```

---

# 29. P0 完成后的工程状态

P0 完成后，我们希望得到：

```text
                     OnlyAlpha CI

                         Static
                           │
        ┌──────────────────┼──────────────────┐
        │                  │                  │
     Core Full          Recovery           A-share
        │                  │                  │
        ├──────── MiniQMT Contract ───────────┤
        │                  │                  │
        └─────────────── Build ───────────────┘
                           │
                           ▼
                     Quality Gate


Nightly
    │
    ├── Exhaustive Recovery
    ├── 100-run Determinism
    ├── Full Matrices
    └── Performance Metrics
```

开发阶段得到的是：

```text
快速
+
有代表性
+
能发现真实回归
```

Nightly 得到的是：

```text
完整
+
穷举
+
高置信度
```

---

# 30. 为什么 P0 完成后才开始 P1

P1 是：

```text
Fee Authority Integrity Closure
```

它将修改：

```text
Market Fee Pack
Broker Fee Contract
Schedule Applicability
Order Fee Binding
Reconciliation Policy
```

这些都必然增加：

```text
Unit
Integration
Recovery
A-share
```

测试。

如果当前测试体系不治理：

```text
每增加一个正确性矩阵
=
进一步降低开发效率
```

所以 P0 不是“顺手优化 CI”。

它实际上是在建设：

> **OnlyAlpha 后续复杂架构能够持续迭代的工程基础设施。**

P0 完成之后，再进入 P1，后面的 Fee、A 股、Paper、Live 才不会因为测试反馈周期越来越长而失控。
