# Codex Prompt — P4.3-close Production Product Certification Closure

## 任务名称

**P4.3-close — CN A-Share Production Durable Product Certification Closure**

中文：

**P4.3-close：中国 A 股 Production Durable Backtest 产品认证收口**

目标仓库：

```text
https://github.com/zongxin1993/OnlyAlpha
```

当前规划基线：

```text
f8ef7859a077ea72ca1a972ee60f1161add24b58
Feat: CN A-Share Production Durable Product Conformance
```

当前已知远端 Workflow：

```text
Layered Quality #26
run_id = 31351149179
```

---

# 0. 本 Prompt 只有一个任务

唯一任务：

> **从第一性原理修复阻止 `CN_A_SHARE_DURABLE_BACKTEST_V1` 正式认证的 Quality Gate 不确定性，在不改变已经通过验证的 P4.3 产品经济语义、不降低任何测试强度、不绕过任何正式 Gate 的前提下，让最终 `master` commit 的全部 Layered Quality Gates 稳定通过，并形成最终 P4.3 Conformance Report，使该有限产品合同真正满足其自身定义的 Certification Rule。**

本任务不是：

```text
新的 P4.4
新的架构阶段
新的产品 Feature
新的 A-share 实现
新的 Execution 重构
新的 CI Framework
```

它只是：

```text
P4.3 Implementation
        ↓
Certification Evidence Closure
        ↓
P4.3 DONE
```

---

# 1. 开始前必须重新读取最新 master

任何修改前：

```text
git fetch
git checkout master
git pull --ff-only
```

或使用当前 Codex/GitHub 环境等价方式确认：

```text
latest master SHA
latest commit message
latest Layered Quality run
latest failing jobs
latest failing logs
```

不要假定本 Prompt 编写时的：

```text
f8ef7859...
```

仍然是 HEAD。

如果 master 已经前进：

1. 最新 master 是唯一事实基线；
2. 重新检查当前 Quality Gate；
3. 如果失败已修复，不重复修改；
4. 如果又出现新的真实失败，以新的根因为准；
5. 不为了执行本 Prompt 恢复任何已经删除的旧接口；
6. 最终报告记录：

   * prompt baseline；
   * actual baseline；
   * baseline differences；
   * actual failure evidence；
   * final certification SHA。

---

# 2. 当前已知事实

在本 Prompt 编写时：

```text
master =
f8ef7859a077ea72ca1a972ee60f1161add24b58
```

P4.3 Product Implementation 已经包含：

```text
CN_A_SHARE_DURABLE_BACKTEST_V1

Production Reference binding

CN_A_SHARE_CASH@2025.1

Production Market Fee Pack

Explicit Broker Fee Contract

BUY OPEN

Same-day SELL rejection

T+1 Settlement Maturity

SELL CLOSE

Whole Fill

Partial Fill

Multi-Fill

Minimum Broker Commission

Cancel

Reject

Expire

Memory semantics

SQLite durability

A→B→C Forward Recovery

Result Determinism

Artifact Determinism

Architecture Guards
```

这些不是 P4.3-close 要重新实现的内容。

---

# 3. 当前 Certification 状态

当前产品合同仍然：

```text
NOT CERTIFIED
```

原因不是已知的 A-share economic conformance failure。

当前最新远端 run：

```text
Layered Quality #26
```

结果：

```text
build             PASS
static            PASS
ashare             PASS
miniqmt-contract   PASS
recovery           PASS

core-full          FAIL

quality-gate       FAIL
```

因此根据 ADR 0067 的 Certification Rule：

```text
CN_A_SHARE_DURABLE_BACKTEST_V1
```

不能正式声明 Certified。

这是正确的 fail-closed 状态。

---

# 4. 当前唯一已知失败

当前失败：

```text
packages/provider/onlyalpha-plugin-miniqmt/tests/
test_historical_worker.py

test_actual_worker_contract_normalizes_a_fake_xtquant_shape
```

期待：

```text
OnlyHistoricalWarmupStatus.SUCCESS
```

实际：

```text
OnlyHistoricalWarmupStatus.TIMEOUT
```

当前 helper：

```python
def _request(*, timeout: int = 5) -> OnlyHistoricalWarmupRequest:
    ...
```

正常 fake xtquant contract test 使用：

```python
_worker_with_fake_xtquant(...).load_warmup(_request())
```

因此继承：

```text
timeout = 5 seconds
```

本次 GitHub runner：

```text
该测试 duration ≈ 5.08 seconds
```

于是 Worker 正确按照业务 contract 返回：

```text
TIMEOUT
```

测试却要求：

```text
SUCCESS
```

---

# 5. 当前测试中 timeout semantic 本来已经有独立测试

同一个文件已经有：

```python
test_timeout_terminates_worker_and_returns_structured_result
```

并显式：

```python
_request(timeout=1)
```

用于验证真正的 Timeout Contract。

另外 native abort 等 subprocess tests 已经使用更宽的：

```text
timeout = 15
```

因此目前存在一个明显的测试职责混淆：

```text
Functional Success Contract
        +
Arbitrary 5-second wall-clock deadline
```

被绑定在了一起。

---

# 6. 第一性原则：Timeout 是业务语义，不是测试调度器

`OnlyHistoricalWarmupRequest.timeout` 是：

```text
worker execution deadline
```

属于真实业务/Provider Contract。

它应该决定：

```text
Worker 是否已经超过允许执行窗口
```

它不应该被普通 SUCCESS contract test 隐式拿来衡量：

```text
GitHub Actions runner
在 8 个 xdist workers 并发时
是否恰好在 5 秒以内完成 subprocess startup
```

这两件事完全不同。

---

# 7. 第一性原则：Functional Correctness ≠ Performance Contract

正常功能测试回答：

```text
fake xtquant response
能否被 worker 正确：
    query
    normalize
    validate
    convert
    return SUCCESS
```

Timeout 测试回答：

```text
worker 超过 explicit deadline 时
能否：
    terminate child
    return TIMEOUT
    preserve diagnostics
```

Performance 测试回答：

```text
worker 正常完成需要多久
```

这是三个不同问题。

禁止用同一个：

```text
timeout=5
```

同时承担全部职责。

---

# 8. 当前失败的根因假设

当前证据强烈表明：

```text
success-path functional test
```

错误地依赖了一个过窄的 wall-clock deadline。

但：

> **不要直接接受这个结论。**

Codex 必须先完成实际 root-cause audit。

---

# 9. Pre-Fix Audit

修改前至少检查：

```text
packages/provider/onlyalpha-plugin-miniqmt/tests/
    test_historical_worker.py

packages/provider/onlyalpha-plugin-miniqmt/src/
    onlyalpha_plugin_miniqmt/historical_worker/

scripts/test_suite.py

.github/workflows/quality.yml

pyproject.toml
```

并检查：

```text
OnlyHistoricalWarmupRequest.timeout

OnlyMiniQmtHistoricalIsolatedClient.load_warmup()

subprocess timeout handling

worker termination

fake xtquant startup

contract markers

miniqmt markers

xdist behavior
```

---

# 10. 全仓搜索

必须搜索：

```text
_request(timeout

timeout=1
timeout=5
timeout=15

OnlyHistoricalWarmupStatus.TIMEOUT

subprocess.TimeoutExpired

load_warmup

test_actual_worker_contract_normalizes_a_fake_xtquant_shape

test_actual_worker_contract_maps_python_query_exception

test_timeout_terminates_worker_and_returns_structured_result

pytest.mark.miniqmt

pytest.mark.contract
```

确认是否还有其它：

```text
SUCCESS-path test
```

隐式依赖不合理的 narrow deadline。

---

# 11. 必须先尝试复现当前失败

至少运行：

```bash
uv sync --frozen --all-packages --all-groups
```

然后：

```bash
uv run python scripts/test_suite.py core-full
```

并单独运行：

```bash
uv run python -m pytest \
  packages/provider/onlyalpha-plugin-miniqmt/tests/test_historical_worker.py \
  -k actual_worker_contract_normalizes_a_fake_xtquant_shape \
  -vv
```

还应运行：

```bash
uv run python scripts/test_suite.py miniqmt-contract
```

比较：

```text
standalone
miniqmt-contract
core-full
```

三种环境的 timing 与结果。

---

# 12. 不要把“本地没复现”当作不存在

已知 GitHub Actions 已经产生真实证据：

```text
duration ≈ 5.08s
timeout = 5s
→ TIMEOUT
```

因此即使高速开发机：

```text
1.5s PASS
```

也不能证明当前测试稳定。

P4.3-close 必须消除：

```text
runner performance fluctuation
→ functional semantic change
```

这个错误耦合。

---

# 13. 正确修复方向

如果 audit 证实当前根因：

应该把：

```text
Functional Success Deadline
```

与：

```text
Timeout Behavior Deadline
```

明确分开。

例如建立测试内部常量：

```python
_FUNCTIONAL_WORKER_TIMEOUT_SECONDS = ...
_TIMEOUT_TEST_SECONDS = 1
```

或者其它更简洁的等价结构。

---

# 14. 更推荐显式 timeout，而不是隐藏默认值

重新审计：

```python
def _request(*, timeout: int = 5)
```

是否仍然合理。

对于这个测试模块，一个更干净的设计可能是：

```python
def _request(*, timeout: int) -> OnlyHistoricalWarmupRequest:
    ...
```

让每一个测试显式声明：

```text
它测试的是 functional execution
还是 timeout boundary
```

例如：

```text
SUCCESS / protocol / query tests
→ explicit generous functional deadline

TIMEOUT test
→ explicit short deadline
```

这样以后不会再有测试无意继承：

```text
5 秒 hidden semantic
```

如果审计后存在更简洁的等价方案，可以使用。

核心不变量：

> **Timeout intent 必须显式。**

---

# 15. Functional deadline 必须宽松，但不能成为性能证明

正常 subprocess contract test 的 timeout 应只是：

```text
防止真实 worker 永久 hang
```

而不是：

```text
性能 SLA
```

因此它应该有足够 runner scheduling margin。

如果需要选择：

```text
15s
20s
30s
```

必须根据：

```text
当前 CI observed timing
现有 subprocess tests
worker startup mechanism
```

选择合理值。

不要随意：

```text
9999 seconds
```

也不要继续卡在：

```text
5.1 seconds
```

这种边缘值。

---

# 16. 不要修改 Production timeout 默认值来修测试

这是硬约束。

如果问题只存在于 test fixture：

禁止修改：

```text
production MiniQMT timeout default
runtime warmup timeout semantics
user-facing config timeout
OnlyHistoricalWarmupRequest production behavior
```

来迎合测试。

正确：

```text
test contract
```

修正自己错误的 deadline assumption。

---

# 17. 只有发现真实 Production bug 时才改 Production

如果 audit 证明：

```text
client timeout implementation
```

存在真正 race、wrong clock、process join bug、termination bug 等：

可以修改 production code。

但必须在 report 中写清楚：

```text
root cause

violated invariant

why this is production behavior

why test-only timeout adjustment is insufficient

new regression proof
```

禁止为了“看起来更根本”强行修改 production code。

---

# 18. 不允许简单 rerun CI 解决

禁止：

```text
GitHub re-run failed job
```

直到碰巧绿色以后就关闭 P4.3。

如果代码没有变化，当前：

```text
TIMEOUT vs SUCCESS
```

仍然由 runner load 决定。

这不是 certification。

---

# 19. 不允许 retry 机制掩盖失败

禁止在测试里：

```python
for _ in range(3):
    result = load_warmup(...)
    if result.success:
        break
```

禁止：

```text
pytest-rerunfailures
CI auto-retry
retry on TIMEOUT
```

来制造绿色。

Worker timeout 是真实语义。

不能通过 retry 消除真实 TIMEOUT Fact。

---

# 20. 不允许 sleep 稳定测试

禁止：

```python
time.sleep(...)
```

作为修复。

问题不是“需要多等一会再检查”。

问题是：

```text
functional test 的 deadline semantic
```

定义错误。

---

# 21. 不允许降低 assertion

禁止：

```python
assert result.status in {
    SUCCESS,
    TIMEOUT,
}
```

正常 functional test 必须仍然明确：

```text
SUCCESS
```

因为它测试的就是正常 fake xtquant Contract。

---

# 22. 不允许把失败测试 skip / xfail

禁止：

```text
@pytest.mark.skip

@pytest.mark.xfail

-m not miniqmt
```

绕过。

---

# 23. 不允许直接把测试从 core-full 排除作为主修复

当前：

```text
core-full
```

会运行 workspace 非 recovery/conformance/external tests。

MiniQMT contract tests 同时也有：

```text
miniqmt-contract
```

独立 lane。

这确实存在 lane overlap。

但：

> **P4.3-close 不允许简单通过“从 core-full 排除 MiniQMT”解决当前失败。**

因为这只是：

```text
removing evidence
```

不是：

```text
fixing nondeterminism
```

---

# 24. Lane ownership 可以审计，但不是当前逃生路径

可以检查：

```text
core-full
+
miniqmt-contract
```

是否存在不必要的 duplicate coverage。

但只有当：

```text
coverage ownership
release gate semantics
PR gate semantics
main gate semantics
```

全部重新证明以后，才允许单独设计 lane ownership。

如果没有明确必要：

保持现有 lane。

P4.3-close 优先修：

```text
test semantic stability
```

而不是测试分区。

---

# 25. 当前 core-full 是重要证据

当前 core-full：

```text
8 workers
--dist worksteal
```

会产生更真实的并行资源压力。

Functional contract 在这种环境仍应该：

```text
SUCCESS
```

只要 worker 没有超过真正合理的 functional guard deadline。

因此 P4.3-close 必须保留：

```text
core-full
```

作为最终 certification gate。

---

# 26. Timeout 专项测试必须保持严格

当前：

```python
test_timeout_terminates_worker_and_returns_structured_result
```

必须继续使用：

```text
明确短 timeout
```

并继续验证：

```text
status == TIMEOUT

diagnostic exists

worker pid terminated
```

不能因为 functional deadline 放宽，而削弱 Timeout Contract。

---

# 27. Query failure test 也必须明确自己的 deadline

例如：

```python
test_actual_worker_contract_maps_python_query_exception
```

它测试：

```text
fake xtquant query throws Python exception
→ QUERY_FAILED
```

不测试 timeout。

因此也应拥有足够宽松的 functional deadline。

不能因为 runner delay 返回：

```text
TIMEOUT
```

而掩盖：

```text
QUERY_FAILED
```

contract。

---

# 28. Native abort tests 同理

测试：

```text
native abort
→ WORKER_ABORTED
```

必须有足够 deadline，让：

```text
native abort classification
```

成为被验证的变量。

不能：

```text
process startup slow
→ TIMEOUT
```

取代真正的 abort classification。

---

# 29. Protocol error tests 同理

例如：

```text
half-written output
→ PROTOCOL_ERROR
```

functional/protocol test 必须拥有：

```text
adequate functional timeout
```

否则：

```text
TIMEOUT
```

会把真正要测试的 protocol semantic 遮掉。

---

# 30. 建议建立测试 timeout taxonomy

只在测试模块内部即可。

概念上：

```text
FUNCTIONAL_WORKER_DEADLINE
    防止正常 functional contract 永久挂死

SHORT_TIMEOUT_DEADLINE
    专门验证 timeout semantics
```

不要创建 production：

```text
TimeoutPolicyRegistry
```

不要做 Framework。

---

# 31. 不建立 Test Timeout Framework

禁止：

```text
OnlyTestTimeoutManager
OnlyTestDeadlinePolicy
GenericSubprocessTestFramework
```

这次只修一个明确的测试语义错误。

保持：

```text
small
local
explicit
```

---

# 32. Test helper 清理

如果 `_request()` 原来的默认：

```text
timeout=5
```

在职责拆分后已经没有意义：

删除默认值。

不要保留：

```python
def _request(... timeout=5):
```

然后另外增加：

```python
def _request_stable(...):
```

形成两套模糊接口。

---

# 33. 不保留 Legacy Test Helper

禁止：

```text
_request_legacy
_request_old
_request_v1
```

Git 保存历史。

测试代码也要干净。

---

# 34. 重复稳定性验证

修复后不能只运行一次：

```text
failing test PASS
```

至少对相关 MiniQMT contract 进行多次执行。

例如：

```bash
for i in 1 2 3 4 5; do
    uv run python -m pytest \
      packages/provider/onlyalpha-plugin-miniqmt/tests/test_historical_worker.py \
      -q
done
```

或者使用仓库现有工具实现等价重复验证。

不要新增依赖只为重复测试。

---

# 35. 必须重新运行 exact core-full lane

修复后至少：

```bash
uv run python scripts/test_suite.py core-full
```

完整通过。

如果资源允许：

再运行一次完整：

```text
core-full
```

以证明不是再次恰好落在 deadline 内。

---

# 36. 必须重新运行 MiniQMT Contract

```bash
uv run python scripts/test_suite.py miniqmt-contract
```

必须 PASS。

需要证明：

```text
functional tests
timeout tests
native abort tests
protocol tests
cache tests
```

没有被 timeout cleanup 破坏。

---

# 37. P4.3 Product tests 不允许变化语义

P4.3-close 默认禁止修改：

```text
tests/conformance/cn_a_share_production/
```

里的 economic expected values。

包括：

```text
Fee amount
T+1 result
Position
Allocation
PnL
Terminal releases
Recovery fingerprints
```

如果没有真实产品 bug：

这些结果不能变化。

---

# 38. P4.3 Production Authorities 不允许变化

不要修改：

```text
CN_A_SHARE_DURABLE_BACKTEST_V1

CN_A_SHARE_CASH@2025.1

CN_A_SHARE_PRODUCTION_MARKET_FEES

Production fixture dates

Reference records

Broker Fee Contract

Execution Support Policy 2
```

P4.3-close 是 certification closure。

不是 Product Contract v2。

---

# 39. 不升 Product Contract Version

CI/test determinism fix：

```text
不改变经济产品语义
```

因此：

```text
product_contract_version
```

不得因为 P4.3-close 从：

```text
1 → 2
```

变化。

---

# 40. 不升 Execution Support Policy

没有新的 execution shape。

禁止：

```text
Execution Support Policy 2 → 3
```

---

# 41. 不升 Transaction Schema

除非 audit 意外发现真正持久化 bug。

正常 P4.3-close 不应该改：

```text
Runtime Transaction Schema
Committed Fact Schema
Projection Schema
```

---

# 42. 不重新设计 P4.3 Product Harness

当前 Harness 已经遵守：

```text
OnlyEngine
Composition Root
Virtual Broker
public product path
```

不要因为 P4.3-close 又重构 Product Harness。

---

# 43. 不修改 Execution Kernel

默认禁止修改：

```text
src/onlyalpha/execution/
```

如果当前失败只是 MiniQMT test deadline：

Execution 与问题无关。

不要顺手 cleanup Execution。

---

# 44. 不修改 Settlement Kernel

P4.3 已经完成 settlement maturity 的真实 market-neutral closure。

不要在 close 阶段继续改。

---

# 45. 不修改 Fee Kernel

Production A-share Fee 产品场景已经 PASS。

不要碰：

```text
Fee Resolver
Fee Accrual
Market Fee Pack
Broker Contract
```

---

# 46. 不修改 A-share Market Rules

当前 `ashare` lane 已经通过。

不要用 P4.3-close 顺手做：

```text
2026.07 Profile
ETF
BSE
新规则
```

---

# 47. 不进入 P5

本任务禁止：

```text
Market Product Composition Neutralization
```

即使当前代码仍然有：

```text
if CN_A_SHARE_CASH
```

存在于：

```text
Runtime Environment
Backtest Factory
Paper Factory
Market Rule Composition
```

这些属于 P5。

先完成 Certification。

---

# 48. 不进入 P6/P7/P8

禁止：

```text
Paper Streaming Recovery

Durable Broker Outbound Command

Live Runtime
```

---

# 49. CI Performance Warnings 不等于本任务全部范围

当前 core-full 日志还有很多：

```text
PERFORMANCE WARNING
```

包括大量 integration tests 超过 metrics budget。

这些值得未来治理，但不是当前认证失败原因。

P4.3-close 不应变成：

```text
全仓 Performance Optimization
```

---

# 50. 只有真正阻止 Certification 的问题进入 Scope

优先级：

```text
1. deterministic correctness gate failure
2. current product certification evidence
3. documentation closure
```

不是：

```text
general performance cleanup
general CI optimization
general test taxonomy rewrite
```

---

# 51. 必须检查这是不是唯一 failure

从最新 GitHub Actions 获取：

```text
all jobs
all conclusions
failing test logs
```

如果最新 master 已出现多个失败：

逐个判断。

如果发现新的真实 correctness regression：

必须修真实 root cause。

不能仍然只修旧 MiniQMT timeout。

---

# 52. Certification 不能依赖“已知失败无关产品”

即使 MiniQMT historical worker：

```text
和 A-share Backtest Product 没有直接经济耦合
```

ADR 0067 已明确要求：

```text
required repository gates
```

全部绿。

所以：

```text
“这个失败和 A 股没关系”
```

不是跳过 Gate 的理由。

这是 repository-wide release hygiene。

---

# 53. 为什么必须修这个失败

Certification 的含义不是：

```text
A-share tests pass
```

而是：

```text
A-share Product
在一个完整、没有已知 repository regression 的 commit
上获得认证
```

否则 Certified commit 同时包含：

```text
known failing core contract
```

是不合理的。

---

# 54. 推荐代码修改原则

如果根因仍是当前已知 timeout coupling：

推荐修改范围尽量限定在：

```text
packages/provider/onlyalpha-plugin-miniqmt/tests/
test_historical_worker.py
```

必要时加最小：

```text
test documentation
```

生产代码零修改是完全合理的结果。

---

# 55. 不以“改代码越多越根本”为目标

根本解决问题的标准是：

```text
正确 Authority
正确职责
正确边界
正确 test semantic
```

不是：

```text
production diff 越大越好
```

如果 bug 在测试：

就修测试。

---

# 56. Clean Test Boundary

理想结构：

```text
Worker Production Code
    owns:
        timeout behavior
        child lifecycle
        protocol

Contract Tests
    own:
        explicit scenario deadline
        expected semantic

CI
    owns:
        scheduling/resources
```

不能：

```text
CI scheduling jitter
→ change contract result expected by functional test
```

---

# 57. P4.3 Certification Report

当前必须新增最终报告：

```text
docs/reports/
p4_3_cn_a_share_production_durable_product_conformance.md
```

注意这不是：

```text
pre_implementation_audit
```

而是最终：

```text
Conformance / Certification Report
```

---

# 58. Final Report 必须包含

至少：

```text
Prompt baseline

Actual final baseline

Product ID

Product Contract Version

Certified supported surface

Explicit unsupported surface

Production Dataset

Reference Authority

Market Profile

Market Fee Pack

Broker Fee Contract

Execution Support Policy

BUY OPEN evidence

Same-day SELL rejection evidence

T+1 Settlement evidence

SELL CLOSE evidence

Whole/Partial/Multi-Fill evidence

Minimum Commission evidence

Cancel/Reject/Expire evidence

Memory evidence

SQLite evidence

A→B→C Recovery evidence

Determinism evidence

Architecture Guard evidence

P4.3-close CI root cause

CI fix

Local Quality Gates

Final remote Layered Quality evidence

Final certification verdict
```

---

# 59. Report 中必须解释本次失败

明确写：

```text
P4.3 initial implementation commit
was not certified
```

原因：

```text
same-commit final Layered Quality gate failed
```

然后解释：

```text
core-full MiniQMT functional contract
coupled SUCCESS semantics to an overly narrow worker deadline
```

如果最终 audit 得到不同 root cause：

按实际结果写。

---

# 60. 不要伪造 Certification Evidence

Report 不允许提前写：

```text
quality-gate: PASS
```

如果实际还没通过。

最终证据必须来自：

```text
实际 GitHub Actions run
```

---

# 61. Certification 建议使用两步提交

为避免产品代码修复与 certification 文档混杂，推荐：

## Commit A

```text
Test: Stabilize MiniQMT Historical Worker Contract
```

或根据真实 root cause 使用更准确名字。

这个 commit：

```text
只修 root cause
保持 P4.3 product semantics 不变
```

先本地全部 Gate。

推送后远端：

```text
Layered Quality
```

必须完整绿色。

---

# 62. Commit A 绿色后再做最终认证文档

然后：

## Commit B

```text
Docs: Certify CN A-Share Durable Backtest V1
```

包含：

```text
final P4.3 conformance report

README current product status

roadmap P4.3 status
```

不要修改 Product economics。

---

# 63. Commit B 也必须跑完整远端 Gate

因为 ADR 0067 要求：

```text
same final commit
```

全部通过。

因此 Docs-only final commit：

```text
也必须等待 Layered Quality 完整绿色
```

才能正式关闭任务。

---

# 64. 如果 Commit B 又失败

不能说：

```text
Commit A 已经绿了
所以算 Certified
```

因为：

```text
HEAD
```

已经是 Commit B。

必须修复：

```text
当前 final commit
```

上的真实失败。

---

# 65. README Certification 表述

完成后应该明确：

```text
CN_A_SHARE_DURABLE_BACKTEST_V1
CERTIFIED
```

但必须同时写清：

```text
有限产品合同
```

不是：

```text
全部中国 A 股
```

---

# 66. 不改变 Profile Stability

即使 Product V1 Certified：

```text
CN_A_SHARE_CASH profile
```

仍可保持：

```text
EXPERIMENTAL
```

因为：

```text
Product Contract Certification
≠
Whole Profile Family Stability
```

不要顺手把 Profile：

```text
EXPERIMENTAL → STABLE
```

---

# 67. ADR 0067 的历史基线不能篡改

ADR 中：

```text
Conformance status at decision baseline:
NOT CERTIFIED
```

是历史事实。

不要改成：

```text
CERTIFIED
```

仿佛当时已经认证。

正确做法：

```text
ADR
    保留 decision-time historical fact

Final Conformance Report
    记录最终 certification
```

这保持 ADR 的时间语义。

---

# 68. 如果 ADR 需要补充后续状态

只能增加清晰的：

```text
Post-decision certification note
```

说明：

```text
最终认证见哪个 report
```

但不要重写历史。

如果 README + report 已足够：

ADR 可以不改。

---

# 69. Roadmap

P4.3-close 成功后 Roadmap 应变成：

```text
P4.3
CN A-Share Production Durable Product Conformance
DONE / CERTIFIED
```

然后：

```text
Next:
P5 Market Product Composition Authority Neutralization
```

---

# 70. 不新增永久的 P4.3-close 架构阶段

Roadmap 不需要长期增加：

```text
P4.3-close
```

作为和 P4.3/P5 并列的产品阶段。

它只是：

```text
P4.3 certification closure work
```

最终应该体现在：

```text
P4.3 = DONE
```

---

# 71. Architecture Guard

本任务至少保证原有 Guards 仍然 PASS：

```text
Execution Core no A-share routing

Production Product no Test Fee authority

Product Harness no Manager/direct Execution internals

No Product Framework

No A-share compatibility layer
```

不要削弱这些测试。

---

# 72. 不允许为了 CI 绿色删除 Architecture Guard

当前 Architecture Guard 即使比较耗时：

也不能删除。

P4.3 Certification 必须包括：

```text
Product Boundary Proof
```

---

# 73. Test Lane Configuration

当前正式 lanes：

```text
FAST
INTEGRATION
ASHARE
RECOVERY
MINIQMT_CONTRACT
CORE_FULL
EXHAUSTIVE
```

Release gate 正式执行：

```text
CORE_FULL
RECOVERY
ASHARE
MINIQMT_CONTRACT
```

不要无理由改变这个 release contract。

---

# 74. Core-full 当前命令必须继续成立

当前：

```text
WORKSPACE_TESTS

not (
    recovery
    or conformance
    or external
    or requires_network
    or requires_tushare
    or requires_local_qmt
    or requires_broker_account
    or performance
    or exhaustive
    or slow
)
```

P4.3-close 不应该靠：

```text
增加 "or miniqmt"
```

来绿。

---

# 75. Full Local Gates

Root cause 修复后必须执行：

```bash
uv sync --frozen --all-packages --all-groups
```

然后：

```bash
uv run ruff check src tests examples packages scripts
```

```bash
uv run ruff format --check src tests examples packages scripts
```

```bash
uv run mypy src/onlyalpha
```

```bash
uv run mypy \
  --config-file packages/provider/onlyalpha-plugin-tushare/pyproject.toml \
  packages/provider/onlyalpha-plugin-tushare/src/onlyalpha_plugin_tushare
```

```bash
uv run mypy \
  --config-file packages/provider/onlyalpha-plugin-miniqmt/pyproject.toml \
  packages/provider/onlyalpha-plugin-miniqmt/src/onlyalpha_plugin_miniqmt
```

```bash
uv run python scripts/version_sync.py check
```

---

# 76. Required Product / Release Lanes

必须：

```bash
uv run python scripts/test_suite.py core-full
```

PASS。

```bash
uv run python scripts/test_suite.py recovery
```

PASS。

```bash
uv run python scripts/test_suite.py ashare
```

PASS。

```bash
uv run python scripts/test_suite.py miniqmt-contract
```

PASS。

---

# 77. Additional Regression Lanes

建议同时：

```bash
uv run python scripts/test_suite.py fast
```

```bash
uv run python scripts/test_suite.py integration
```

如果项目当前约定 P4 close 还需要：

```bash
uv run python scripts/test_suite.py exhaustive
```

则继续执行。

不要降低当前仓库既有 closure 标准。

---

# 78. Build

必须：

```bash
uv build --all-packages
```

PASS。

---

# 79. Release Command

最终最好再执行：

```bash
uv run python scripts/test_suite.py release
```

如果它和当前 CI release contract一致。

这能作为一次整体本地闭环。

---

# 80. Remote Quality Gate

最终 commit 必须在 GitHub 上：

```text
Layered Quality
```

完整：

```text
static             success
build              success
core-full          success
recovery           success
ashare             success
miniqmt-contract   success
quality-gate       success
```

---

# 81. 远端绿色必须来自 final SHA

报告最终必须记录：

```text
final SHA

Layered Quality run ID

quality-gate conclusion
```

并确认：

```text
workflow.head_sha == final SHA
```

不能拿前一个 commit 的 green run 给后一个 commit 认证。

---

# 82. 不通过手工 Status 伪造

禁止：

```text
manual status API
```

把：

```text
quality-gate
```

设绿色。

必须是真实：

```text
.github/workflows/quality.yml
```

执行结果。

---

# 83. 远端失败时如何处理

如果 final remote gate 失败：

1. 获取真实 job logs；
2. 定位第一个真实 root cause；
3. 判断：

   * deterministic correctness；
   * infrastructure timing；
   * test semantics；
   * actual regression；
4. 根治；
5. 新 commit；
6. 重新跑所有 Gate。

不要盲目 re-run。

---

# 84. 允许重新 rerun 的唯一情况

只有在已经有充分证据证明：

```text
GitHub infrastructure outage
network service failure
runner provisioning failure
```

而不是测试本身 flaky，

才可以 rerun infrastructure failure。

对于：

```text
test returned TIMEOUT
```

不属于这种情况。

---

# 85. Code Cleanliness

最终不允许新增：

```text
legacy timeout

old_timeout

timeout_compat

ci_timeout

github_actions_timeout

retry_timeout

flake_workaround
```

这种语义不清的 API。

测试常量应表达：

```text
FUNCTIONAL CONTRACT
```

而不是某个 CI 平台名字。

---

# 86. 不把 GitHub Actions 细节写入 Domain Code

禁止 production code 出现：

```text
GITHUB_ACTIONS
CI
xdist
core-full
```

判断。

生产代码不应该知道测试执行器。

---

# 87. Test Constant Naming

如果建立测试常量，应表达：

```text
功能意图
```

例如：

```text
FUNCTIONAL_WORKER_DEADLINE_SECONDS
TIMEOUT_SCENARIO_DEADLINE_SECONDS
```

而不是：

```text
CI_TIMEOUT
GITHUB_TIMEOUT
```

---

# 88. 不依赖机器性能阈值断言 SUCCESS

普通功能测试应避免：

```text
assert elapsed < 5
```

除非它明确是 performance test。

当前功能测试只需要验证：

```text
Worker 在合理 guard deadline 内完成后，
语义结果正确
```

---

# 89. 如果真正要测性能

另建：

```text
performance marker
```

使用明确 benchmark/SLO。

不要塞进 P4.3-close。

---

# 90. Quality Metrics Warning 暂不作为 blocker

当前：

```text
scripts.pytest_metrics
```

会报告很多 performance warnings。

只要它们不是：

```text
quality gate failure condition
```

P4.3-close 记录但不扩 Scope。

未来可以单独做：

```text
Test/CI Performance Governance
```

---

# 91. 为什么这是根因修复

错误模型：

```text
functional test

fake worker
    ↓
5 second arbitrary timeout
    ↓
runner load slightly high
    ↓
TIMEOUT
    ↓
test failure
```

正确模型：

```text
functional test

fake worker
    ↓
explicit generous hang-guard
    ↓
actual functional result
    ↓
SUCCESS / QUERY_FAILED / PROTOCOL_ERROR
```

而：

```text
timeout-specific test

worker intentionally hangs
    ↓
explicit short deadline
    ↓
TIMEOUT
```

职责完全分开。

---

# 92. P4.3 Product Economics 必须保持 byte/economic stable

P4.3-close 前后：

```text
same product fixture
```

应该继续得到同样：

```text
result_fingerprint

determinism_fingerprint

artifact_content_fingerprint
```

除非本次 bug 实际涉及 product semantics。

如果这些变化：

必须停止，找根因。

---

# 93. Product Conformance Tests 必须全部继续 PASS

特别：

```text
production round trip

XSHG

XSHE

same-day sell reject

production fee components

minimum commission

multi-fill

reject

expire

sell reject

partial cancel

Memory/SQLite equivalence

determinism

A→B→C recovery
```

全部继续成立。

---

# 94. P4.3-close 不增加新的 Product Scenario

当前 Product Contract 已经足够完成 V1 Certification。

不要顺手新增：

```text
ETF
ST
2026.07
BSE
```

Certification closure 要保持范围有限。

---

# 95. P4.3-close 完成后的 Certification 语义

只有最终 commit 的：

```text
same-commit Product Conformance
+
same-commit repository Quality Gates
+
same-commit Build
+
same-commit remote quality-gate
```

全部绿色以后：

才能声明：

```text
CN_A_SHARE_DURABLE_BACKTEST_V1
CERTIFIED
```

---

# 96. Certified 代表什么

代表：

```text
有限的普通 A-share Cash-Long V1 surface
```

在：

```text
Production Reference semantics

Production Market Rules

Production Fee Authority

Explicit Broker Contract

Durable Broker Lifecycle

T+1 Settlement

Partial/Multi-Fill

Terminal

Persistence

Forward Recovery

Deterministic Result/Artifact
```

上已经形成统一产品证明。

---

# 97. Certified 不代表什么

不代表：

```text
完整中国 A 股

所有 Profile version

2026.07 Profile

ETF

Convertible Bond

BSE

Margin

Short

Paper ready

Live ready
```

---

# 98. Final Report 的认证结论

如果最终 remote gate 成功：

写：

```text
Certification Verdict:
CERTIFIED
```

并记录：

```text
Product:
CN_A_SHARE_DURABLE_BACKTEST_V1

Product Contract Version:
1

Final Commit:
<sha>

Layered Quality:
<run-id>

quality-gate:
success
```

---

# 99. 如果最终 Gate 没成功

报告不得写：

```text
CERTIFIED
```

保持：

```text
NOT CERTIFIED
```

任务不得宣告完成。

---

# 100. README

最终 Certified 后更新：

```text
CN_A_SHARE_DURABLE_BACKTEST_V1
```

产品状态。

明确链接/引用：

```text
ADR 0067
P4.3 final conformance report
```

保持：

```text
CN_A_SHARE_CASH Profile status
```

与 Product Certification 分离。

---

# 101. Roadmap

最终：

```text
P4.3
CN A-Share Production Durable Product Conformance
DONE
```

下一阶段：

```text
P5
Market Product Composition Authority Neutralization
```

不要在 P4.3-close 中开始 P5。

---

# 102. 删除无用接口

本任务如果修改 MiniQMT test helper 后：

原：

```text
implicit timeout=5
```

不再有职责：

删除。

不要保留：

```text
deprecated helper behavior
```

测试调用点全部迁移。

---

# 103. 如果发现重复 timeout constants

统一为最小清晰语义。

不要出现：

```text
DEFAULT_TIMEOUT
NORMAL_TIMEOUT
SUCCESS_TIMEOUT
CI_TIMEOUT
LONG_TIMEOUT
```

五套类似值。

目标：

```text
少量
明确
按职责命名
```

---

# 104. 模块边界

最终必须保持：

```text
MiniQMT Worker
    owns subprocess/timeout protocol

MiniQMT Contract Tests
    own scenario-specific deadlines

test_suite.py
    owns lane orchestration

quality.yml
    owns remote gate orchestration

A-share Product Conformance
    owns product certification proof
```

不要跨层污染。

---

# 105. 不让 test_suite.py 认识某个具体 flaky test

禁止：

```python
if test == "test_actual_worker...":
    ...
```

CI orchestration 不应认识单个 case。

---

# 106. 不让 quality.yml 增加 sleep/retry

禁止：

```yaml
- run: sleep 5
- run: pytest ...
  continue-on-error: true
```

禁止：

```text
rerun failed tests
```

---

# 107. 不降低 xdist worker 数量只为了当前测试

不能简单：

```text
core-full workers:
8 → 1
```

来隐藏测试 deadline flaw。

除非 profiling 证明整个 suite 的并行模型本身不安全。

那将是另一个架构问题，需要独立证据。

当前优先修测试 semantic。

---

# 108. 不增加 global subprocess serialization lock

禁止为了这一个 test：

```text
global lock
file lock
xdist_group
```

强制所有 MiniQMT worker serial。

除非真实 SDK contract 明确不允许并行。

当前 fake xtquant 测试没有这种证据。

---

# 109. Regression Guard

修改后应增加/调整测试，使未来有人重新把 functional deadline 改成过窄值时容易暴露。

可以通过：

```text
explicit timeout intent
```

本身实现。

不需要建立脆弱的：

```text
assert timeout >= 15
```

Architecture test。

代码清晰即可。

---

# 110. 代码注释原则

如果 timeout 常量需要注释：

说明：

```text
它是 functional hang guard，
不是 performance SLA。
```

不要写：

```text
GitHub is slow so use 15s
```

因为这会再次把语义绑定某个环境。

---

# 111. Root-Cause Report

P4.3 final conformance report 中应包含：

```text
Initial Certification Blocker

Observed Failure

Root Cause

Why It Was Nondeterministic

Why It Was Not an A-share Economic Regression

Correct Authority Boundary

Fix

Regression Evidence
```

---

# 112. 最终 Commit 计划

推荐最多两类 commit。

## Commit A

```text
Test: Stabilize MiniQMT Historical Worker Contract
```

或者根据实际根因：

```text
Fix: Separate MiniQMT Functional and Timeout Deadlines
```

只解决 certification blocker。

---

## Commit B

```text
Docs: Certify CN A-Share Durable Backtest V1
```

完成：

```text
final conformance report
README
roadmap
```

不要再混入功能修改。

---

# 113. 不制造很多“close”提交

不要：

```text
Fix timeout 1
Fix timeout 2
Try CI again
Increase timeout
Retry again
```

先在本地完整证明方案稳定。

再形成清晰 commit。

---

# 114. 如果首次修复仍远端失败

不要继续机械：

```text
15 → 30 → 60
```

必须重新分析。

可能存在：

```text
subprocess startup race
filesystem visibility
xdist tempdir contention
process cleanup
cache locking
```

等真正问题。

只有证据支持才能继续调整。

---

# 115. Definition of Done — Root Cause

* [ ] 最新失败日志已读取。
* [ ] failure 可解释。
* [ ] functional correctness 与 timeout contract 已分离。
* [ ] 没有通过 rerun/skip/xfail 绕过。
* [ ] 没有无依据修改 production timeout。
* [ ] 没有通过删除 core-full coverage 绕过。
* [ ] 没有通过降低 assertion 绕过。

---

# 116. Definition of Done — MiniQMT

* [ ] fake xtquant SUCCESS contract 稳定。
* [ ] query exception → QUERY_FAILED。
* [ ] native abort → WORKER_ABORTED。
* [ ] timeout → TIMEOUT。
* [ ] timeout worker 被正确终止。
* [ ] protocol error 保持正确。
* [ ] cache contract 不回归。
* [ ] miniqmt-contract lane PASS。
* [ ] core-full 中 MiniQMT tests PASS。

---

# 117. Definition of Done — P4.3 Product

* [ ] A-share round-trip PASS。
* [ ] XSHG PASS。
* [ ] XSHE PASS。
* [ ] same-day SELL reject PASS。
* [ ] T+1 maturity PASS。
* [ ] Production Fee PASS。
* [ ] Multi-Fill PASS。
* [ ] minimum commission PASS。
* [ ] Reject PASS。
* [ ] Expire PASS。
* [ ] Partial + Cancel PASS。
* [ ] Memory/SQLite equivalence PASS。
* [ ] A→B→C recovery PASS。
* [ ] Determinism PASS。
* [ ] Artifact determinism PASS。
* [ ] Architecture Guards PASS。

---

# 118. Definition of Done — Local Quality

* [ ] uv sync --frozen PASS。
* [ ] Ruff PASS。
* [ ] Ruff Format PASS。
* [ ] Core mypy PASS。
* [ ] Tushare mypy PASS。
* [ ] MiniQMT mypy PASS。
* [ ] version sync PASS。
* [ ] fast PASS。
* [ ] integration PASS。
* [ ] core-full PASS。
* [ ] recovery PASS。
* [ ] ashare PASS。
* [ ] miniqmt-contract PASS。
* [ ] exhaustive PASS，如果当前 closure policy 要求。
* [ ] build PASS。
* [ ] release PASS，若当前 release command适用。

---

# 119. Definition of Done — Remote Certification

最终 HEAD：

```text
Layered Quality
```

必须：

* [ ] static success。
* [ ] build success。
* [ ] core-full success。
* [ ] recovery success。
* [ ] ashare success。
* [ ] miniqmt-contract success。
* [ ] quality-gate success。
* [ ] workflow head SHA == final repository HEAD。

---

# 120. Definition of Done — Documentation

* [ ] Final P4.3 Conformance Report 存在。
* [ ] Report 有 final SHA。
* [ ] Report 有真实 Layered Quality evidence。
* [ ] README 准确描述 Certified finite product。
* [ ] Roadmap 标记 P4.3 DONE。
* [ ] ADR 0067 historical NOT CERTIFIED baseline 没被篡改。
* [ ] Product Profile 没被错误 Promotion。
* [ ] P5 被标记为 next，而不是提前实现。

---

# 121. Definition of Done — Clean Code

最终不允许：

```text
legacy timeout helper

compatibility timeout alias

CI-specific production branch

retry workaround

sleep workaround

flaky marker

temporary xfail

old unused test helper

dead certification workaround

commented-out previous implementation
```

---

# 122. 本任务明确非目标

不要实现：

```text
P5 Market Product Composition Neutralization

Runtime Environment product abstraction

Market Product Registry

Market compiler SPI

Reference provider SPI

Paper Streaming Recovery

Durable Broker Outbound Command

Broker synchronization

Live Runtime

A-share Profile 2026.07 certification

ETF

BSE

Convertible Bond

Margin

Short

Futures

Crypto

Vectorized Backtest

Distributed Backtest

general CI performance optimization
```

---

# 123. 不要把 P4.3-close 变成 Test Infrastructure 重写

当前：

```text
scripts/test_suite.py
quality.yml
```

总体结构是明确的：

```text
lane definitions
+
Layered Quality
+
independent final gate
```

除非当前根因证明这些文件本身错误：

不要大规模重构。

---

# 124. Certification Closure 的第一性原理

P4.3-close 不是：

> “让 CI 变绿。”

真正目标是：

> **让相同代码在相同语义输入下产生稳定、可重复的 Quality Evidence，使 Certification Verdict 不再依赖 runner 调度偶然性。**

也就是：

```text
Correct Code
        +
Correct Test Semantics
        +
Deterministic Quality Gates
        ↓
Trustworthy Certification
```

---

# 125. 错误的关闭方式

以下都不算完成：

```text
re-run 之后碰巧绿了

timeout 从 5 改到 6

删除 failing test

把 failing test 标 slow

从 core-full 排除 MiniQMT

assert SUCCESS or TIMEOUT

continue-on-error

quality-gate 忽略 core-full

README 手工改 CERTIFIED
但 final SHA CI 是红的
```

---

# 126. 正确的关闭方式

应该得到：

```text
Functional SUCCESS test
    有明确且合理的 hang guard

Timeout test
    有明确 short deadline

两者职责不混淆

MiniQMT contract stable

core-full stable

A-share conformance unchanged

Recovery unchanged

Build/static unchanged

final same-SHA Layered Quality green
```

然后：

```text
CN_A_SHARE_DURABLE_BACKTEST_V1
        ↓
CERTIFIED
```

---

# 127. 最终工程原则

当：

```text
Test Deadline
```

与：

```text
Functional Contract
```

冲突：

> Deadline 只负责防 hang；功能测试验证功能。

当：

```text
Timeout Behavior
```

需要测试：

> 使用专门的 short-deadline scenario。

当：

```text
Runner scheduling jitter
```

能够改变功能测试 semantic result：

> Test contract 设计错误。

当：

```text
重新跑一次可能会绿
```

与：

```text
root cause fix
```

冲突：

> 修 root cause。

当：

```text
排除测试可以让 core-full 绿
```

与：

```text
保持证据完整
```

冲突：

> 保留测试，修语义。

当：

```text
修改 production timeout
```

与：

```text
问题只存在测试 fixture
```

冲突：

> 不修改 production。

当：

```text
旧 helper 方便
```

与：

```text
明确 timeout intent
```

冲突：

> 删除旧 helper/default，迁移调用者。

当：

```text
P4.3 product 已经实现
```

与：

```text
same-commit final quality-gate 失败
```

冲突：

> NOT CERTIFIED。

当：

```text
所有 final gates 同 SHA 绿色
```

时：

> 才能 CERTIFIED。

---

# 128. P4.3-close 的最终定义

P4.3-close 不是：

> **“把 timeout 调大，然后再跑一次 CI。”**

它真正完成的是：

> **从根本上分离 MiniQMT Worker 的 Functional Contract 与 Timeout Contract，消除 success-path 测试对 CI 调度性能的隐式依赖，使 repository-wide Quality Evidence 稳定、确定、可信；随后在同一个最终 commit 上重新验证 P4.3 已建立的 Production A-share Product Conformance、Recovery、Static、Build 和全部正式 Release Gates，并形成最终认证报告。**

最终必须形成：

```text
P4.3 Product Implementation
        │
        ▼
Production Product Conformance
        │
        ▼
Deterministic Test Semantics
        │
        ▼
core-full PASS
        │
        ├──────────┐
        ▼          ▼
recovery PASS   ashare PASS
        │          │
        ├──────────┤
        ▼          ▼
miniqmt PASS    static/build PASS
        │          │
        └────┬─────┘
             ▼
      final quality-gate
             │
             ▼
           PASS
             │
             ▼
CN_A_SHARE_DURABLE_BACKTEST_V1
          CERTIFIED
```

并严格满足：

```text
No Rerun-Based Certification

No Skip/Xfail

No Assertion Weakening

No Coverage Removal

No Production Timeout Hack

No Compatibility Interface

No Product Semantic Change

No New Framework

Root Cause First

Clean Test Boundary

Same Final SHA

All Gates Green
```

只有这些条件全部成立：

> **P4.3 才正式关闭。**
