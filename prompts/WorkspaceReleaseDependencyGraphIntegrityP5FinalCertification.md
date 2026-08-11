# OnlyAlpha P0 Closure — Workspace Release Dependency Graph Integrity & P5 Final Certification

Repository:

`https://github.com/zongxin1993/OnlyAlpha`

当前任务不是新的产品阶段，也不是 Runtime 架构重构。

这是进入 P6 前必须完成的：

# P0 Closure

目标只有两个：

```text
P0.1
Workspace Release Dependency Graph Integrity

P0.2
P5 Final Closure & Certification
```

本任务必须基于当前 `master` 最新源码执行。

---

# 1. 当前已知问题

当前仓库版本已经升级到：

```text
OnlyAlpha 0.3.7
```

正式 workspace packages 也已经是：

```text
onlyalpha-plugin-broker-virtual      0.3.7
onlyalpha-market-generic-t0-cash    0.3.7
onlyalpha-market-cn-ashare          0.3.7
onlyalpha-plugin-tushare            0.3.7
onlyalpha-plugin-miniqmt            0.3.7
```

但是当前 Provider package 仍存在错误内部依赖：

```text
onlyalpha-plugin-miniqmt@0.3.7
    → onlyalpha-market-cn-ashare==0.3.6

onlyalpha-plugin-tushare@0.3.7
    → onlyalpha-market-cn-ashare==0.3.6
```

这意味着：

```text
Distribution node version
!=
Internal dependency edge version
```

当前 CI 没有发现该问题。

---

# 2. 根因

当前：

```text
scripts/version_sync.py
```

实际上只验证：

```text
project.version == root version

and

onlyalpha==root version
```

它只知道：

```text
onlyalpha
```

是需要同步的 dependency。

它不知道整个正式 workspace distribution graph。

所以：

```text
provider → market plugin
```

这样的内部 dependency edge 不受检查。

这才是本任务真正要解决的问题。

---

# 3. 第一性原理

不要只做：

```text
0.3.6 → 0.3.7
```

这种局部修复。

必须建立下面的不变量：

> **正式 workspace distribution graph 是 release version consistency 的唯一 Authority。**

即：

```text
Root Release Version
        │
        ▼
Formal Workspace Distributions
        │
        ├── node versions
        │
        └── internal dependency edges
                 │
                 ▼
           Release Integrity
```

必须满足：

```text
Every formal workspace distribution version
=
root release version
```

并且：

```text
Every dependency from one formal workspace distribution
to another formal workspace distribution
=
exactly == root release version
```

---

# 4. 不允许继续维护第二套 Formal Package Registry

当前如果存在：

```python
FORMAL_PACKAGES = (
    ...
)
```

这种手工列表：

删除。

正式 workspace membership 已经存在于：

```toml
[tool.uv.workspace]
members = [...]
```

因此：

```text
root pyproject.toml
→ tool.uv.workspace.members
```

必须成为正式 distribution membership 的唯一 Authority。

不要同时维护：

```text
uv workspace members
+
FORMAL_PACKAGES
```

两套 truth。

---

# 5. Formal Distribution Model

建议建立一个很小的内部 model，例如：

```python
@dataclass(frozen=True, slots=True)
class WorkspaceDistribution:
    path: Path
    name: str
    canonical_name: str
    version: Version
    dependencies: tuple[Requirement, ...]
    optional_dependencies: tuple[Requirement, ...]
```

具体结构根据当前代码最小化。

不要建立 package-management framework。

这个类型只用于：

```text
version_sync
```

内部检查和 rewrite。

---

# 6. 使用 Python Packaging 标准解析

必须使用：

```python
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name
from packaging.version import Version
```

不要继续使用：

```python
startswith("onlyalpha==")
```

或者其它 dependency 字符串匹配。

Dependency identity 必须按照 Python packaging semantics 处理。

---

# 7. 加载正式 Workspace Distributions

实现类似：

```python
def load_workspace_distributions(root: Path) -> tuple[WorkspaceDistribution, ...]:
    ...
```

流程：

```text
root pyproject
    ↓
project
    ↓
root distribution

tool.uv.workspace.members
    ↓
member pyproject.toml
    ↓
workspace distributions
```

Fail closed：

```text
missing member pyproject
missing project.name
missing project.version
invalid Version
duplicate canonical distribution name
invalid Requirement
```

全部报错。

不要 silently skip。

---

# 8. Formal Distribution Index

建立：

```python
def distribution_index(
    distributions: Sequence[WorkspaceDistribution],
) -> Mapping[str, WorkspaceDistribution]:
    ...
```

key：

```text
canonicalize_name(project.name)
```

例如：

```text
onlyalpha-market-cn-ashare
```

统一 canonical identity。

不要自己 lower/replace `_` 等。

---

# 9. 内部 Dependency Edge 判定

对于每个正式 distribution：

```text
project.dependencies
```

逐个解析：

```python
requirement = Requirement(value)
```

然后：

```python
dependency_name = canonicalize_name(requirement.name)
```

如果：

```text
dependency_name in formal_distribution_index
```

则该 dependency 是：

```text
formal internal edge
```

必须检查版本。

其它：

```text
tushare
xtquant
tzdata
pyarrow
...
```

全部视为 external dependencies，不修改其版本语义。

---

# 10. Optional Dependencies 也必须检查

正式 release metadata 不只有：

```text
project.dependencies
```

还可能包括：

```toml
[project.optional-dependencies]
...
```

因此检查和 rewrite 必须覆盖：

```text
project.dependencies

project.optional-dependencies.*
```

不要只修当前出现问题的位置。

---

# 11. dependency-groups 不属于正式 release graph

例如：

```toml
[dependency-groups]
dev = [...]
```

属于开发环境。

不要把 dev dependencies 当成正式 distribution runtime dependency graph。

边界必须明确：

```text
project.dependencies
project.optional-dependencies
→ release graph

dependency-groups
→ development graph
```

---

# 12. Internal Edge 版本规则

当前 OnlyAlpha 采用 lockstep release。

因此正式 internal dependency 必须是：

```text
exactly == root release version
```

例如：

```text
onlyalpha==0.3.7
```

正确。

```text
onlyalpha-market-cn-ashare==0.3.7
```

正确。

下面全部错误：

```text
onlyalpha>=0.3.7

onlyalpha~=0.3.7

onlyalpha>=0.3.7,<0.4

onlyalpha

onlyalpha-market-cn-ashare==0.3.6
```

当前 release graph 不允许 range dependency。

---

# 13. 不要用字符串判断 Specifier

建议解析：

```python
Requirement
```

后严格判断：

```text
specifier
=
exactly one ==<release_version>
```

如果：

```text
direct URL dependency
```

指向正式 workspace distribution：

fail closed。

不要允许：

```text
onlyalpha @ file://...
```

作为正式 release metadata。

Workspace resolution 应依赖：

```text
tool.uv.sources
```

而不是发布 metadata direct URL。

---

# 14. `check` 的最终行为

当前：

```bash
uv run python scripts/version_sync.py check
```

必须升级为：

# Workspace Release Graph Integrity Gate

检查：

```text
root project version

README version

all formal workspace node versions

all formal internal dependency edges

test fixture references to formal distributions
```

任何错误：

```text
exit != 0
```

并打印具体：

```text
package
dependency
expected
actual
```

例如：

```text
packages/provider/onlyalpha-plugin-miniqmt/pyproject.toml:
internal dependency 'onlyalpha-market-cn-ashare'
expected '==0.3.7'
found '==0.3.6'
```

错误信息必须可直接定位。

---

# 15. `set` 的行为必须同步整个 Graph

当前：

```bash
uv run python scripts/version_sync.py set 0.3.8
```

最终必须：

```text
1. validate target version

2. update root project.version

3. update every formal workspace project.version

4. update every internal dependency edge

5. update README version

6. update test fixture references to formal distributions

7. run uv lock --python 3.12

8. run complete graph check
```

不能再只改：

```text
onlyalpha==...
```

---

# 16. Internal Requirement Rewrite

建议实现纯函数，例如：

```python
def rewrite_internal_requirement(
    raw_requirement: str,
    *,
    formal_distribution_names: frozenset[str],
    version: str,
) -> str:
    ...
```

要求：

```text
external dependency
→ unchanged

formal internal dependency
→ ==target version
```

必须保留：

```text
extras
environment marker
```

例如：

```text
some-internal-package[foo]==0.3.7; python_version >= "3.12"
```

升级后仍保留：

```text
[foo]
marker
```

---

# 17. Test Fixture Distribution 与 Formal Distribution 分开

当前测试 fixture：

```text
tests/fixtures/external_plugins/onlyalpha_test_plugin
```

不是正式 release distribution。

不要要求：

```text
its project.version
==
root release version
```

但是：

如果 fixture 依赖：

```text
onlyalpha
或其它 formal distribution
```

这些 dependency pin 应指向当前 release version。

因此：

```text
Formal Distribution
    node version synchronized
    internal edges synchronized

Test Distribution
    own version independent
    formal dependency references synchronized
```

---

# 18. 为 version_sync 增加正式 Unit Tests

新增：

```text
tests/tools/test_version_sync.py
```

如果当前测试目录 convention 不同，以仓库实际结构为准。

测试必须使用：

```python
tmp_path
```

创建最小 temporary workspace。

不要修改真实 repo。

---

# 19. 必须覆盖的 Version Graph Test Matrix

至少测试：

### Valid graph

```text
root = 0.3.7

A = 0.3.7
B = 0.3.7

B → A==0.3.7

PASS
```

### Stale internal edge

```text
B@0.3.7
→ A==0.3.6

FAIL
```

### Wrong node version

```text
A@0.3.6
root@0.3.7

FAIL
```

### Range internal dependency

```text
B → A>=0.3.7

FAIL
```

### Missing specifier

```text
B → A

FAIL
```

### External dependency

```text
B → pandas>=2

PASS / unchanged
```

### Optional internal dependency stale pin

```text
project.optional-dependencies

A==0.3.6

FAIL
```

### Duplicate distribution name

```text
OnlyAlpha-Market-X
onlyalpha_market_x

FAIL
```

### Missing workspace member pyproject

```text
FAIL
```

### Invalid requirement syntax

```text
FAIL
```

### Test fixture own version differs

```text
PASS
```

### Test fixture references stale Core

```text
FAIL
```

### `set 0.3.8`

必须验证：

```text
all formal node versions → 0.3.8

all internal edges → ==0.3.8

external dependencies unchanged
```

---

# 20. Pure Core + CLI Shell

为了让脚本可测试：

不要让所有逻辑集中在：

```python
main()
set_versions()
```

中。

建议分成：

```text
read/model functions
validation functions
rewrite functions
filesystem write
CLI shell
```

例如：

```python
load_workspace(...)
validate_workspace(...)
rewrite_workspace(...)
check_versions(...)
set_versions(...)
```

核心 graph validation/rewrite 应可在：

```text
temporary root
```

上独立运行。

---

# 21. 当前 stale pin 必须修复

完成脚本重构后：

MiniQMT：

```toml
onlyalpha-market-cn-ashare==0.3.7
```

Tushare：

```toml
onlyalpha-market-cn-ashare==0.3.7
```

如果当前 `0.3.7` 尚未上传正式 package registry，可以直接修复当前版本。

---

# 22. 如果 0.3.7 已发布

执行前先确认当前 release 状态。

如果错误版本的：

```text
onlyalpha-plugin-miniqmt 0.3.7
onlyalpha-plugin-tushare 0.3.7
```

已经正式发布：

不要尝试重新上传相同版本修正版。

改为：

```text
0.3.8
```

然后必须使用：

```bash
uv run python scripts/version_sync.py set 0.3.8
```

通过新的 graph-aware version sync 一次性升级所有正式 distribution 和 internal dependency edge。

不要手工逐包修改。

如果仓库当前没有发布状态检查工具，仅记录这一事实，不要为本任务建立 release registry framework。

---

# 23. uv.lock 必须重新生成

任何 package metadata dependency 修改后：

```bash
uv lock --python 3.12
```

并提交：

```text
uv.lock
```

要求：

```text
pyproject metadata
==
lock file
```

---

# 24. CI 不增加新 lane

当前 GitHub Actions 已经在 static job 中执行：

```bash
uv run python scripts/version_sync.py check
```

继续复用这个 gate。

不要新增：

```text
workspace-version-gate
release-version-gate
internal-dependency-gate
```

等重复 CI。

只增强：

```text
version_sync.py check
```

的实际语义。

---

# 25. P0.2 — P5 Final Closure

P5.1–P5.4 当前代码已经完成。

本任务不要继续修改 Market Product architecture。

只同步：

```text
code fact
CI fact
roadmap fact
certification fact
```

---

# 26. Roadmap 更新

当前 roadmap 如果仍然写：

```text
Current Stage: P5

P5.4:
Identity hardening and certification
```

必须更新。

最终：

```text
P5
Market Product Composition Authority Neutralization
DONE / CERTIFIED
```

并将：

```text
Current Stage
```

切换为：

```text
P6 — Sim Streaming Runtime Closure
```

---

# 27. Roadmap 不重新设计 P6

当前 roadmap 已经定义：

```text
Current PAPER streaming infrastructure
→ Realtime MarketData + LiveClock
→ Bootstrap / Handoff / Watermark
→ Gap / Reconnect / Checkpoint
→ Virtual Broker
→ Full Trading Kernel
→ SIM
```

本任务不要修改 P6 的架构语义。

只改变：

```text
stage status
```

从：

```text
future
```

变为：

```text
current
```

---

# 28. 新增 P5 Final Certification Report

建议新增：

```text
docs/reports/p5_market_product_composition_final_certification.md
```

具体路径结合当前 docs convention。

报告不是新的设计文档。

只记录最终审计事实。

---

# 29. Certification Report 至少包含

```text
1. P5 scope

2. P5.1 completion evidence
   Core Market Product Contract

3. P5.2 completion evidence
   Generic T0 + Canonical IR

4. P5.3 completion evidence
   CN A-share migration + Runtime cutover

5. P5.4 completion evidence
   strict formal identity + recovery identity

6. Final Authority map

7. Final Architecture invariants

8. Core concrete-market leakage result

9. Product-id behavioral dispatch result

10. Runtime-mode economic identity result

11. Generic fallback result

12. Recovery composition validation

13. Generic T0 regression

14. CN_A_SHARE_DURABLE_BACKTEST_V1 certification

15. Local validation results

16. same-SHA GitHub quality results

17. Final status:
    P5 DONE / CERTIFIED

18. Next:
    P6
```

---

# 30. 不要篡改历史报告

如果历史 P5.3 报告在当时写：

```text
NOT YET ACCEPTED
```

因为那个时刻某 gate 尚未完成：

不要回头修改成：

```text
当时已经成功
```

Final Certification Report 应记录：

```text
historical implementation report state
+
later same-SHA CI evidence
```

保持审计历史真实。

---

# 31. 本任务严格禁止修改 Runtime

不要实现：

```text
OnlyRuntimeMode.SIM

OnlySimRuntime

OnlySimRuntimeFactory

PAPER deletion

SHADOW deletion

Streaming Runtime inheritance refactor

Streaming checkpoint

Reconnect

Gap recovery

Virtual Broker SIM wiring

Strategy context.mode removal
```

全部属于 P6。

---

# 32. 不进行大规模命名清理

虽然当前还可能存在：

```text
generic_t0
profile
shadow
paper
```

等历史命名：

本 P0 不做无边界全文清理。

只修：

```text
Release graph correctness
P5 documentation state
```

如果某个命名不影响这两个目标：

留给后续对应阶段处理。

---

# 33. 不修改 Market Product Architecture

禁止：

```text
MarketProductBindingV2
MarketProductManager
new Market Registry
new Identity framework
new Reference framework
```

P5 已冻结。

除发现明确 regression bug 外：

Market Product architecture 不再变化。

---

# 34. 不修改 Trading Economics

绝对不能改变：

```text
Order semantics
Risk semantics
Position
Allocation
Account
Fee
Settlement
Transaction
PnL
Virtual Broker matching
Recovery economics
```

P0 的：

```text
Economic Behavior Change
=
ZERO
```

---

# 35. 推荐实现顺序

严格建议：

```text
Phase 1
Audit current workspace/release graph

Phase 2
Refactor version_sync to derive workspace membership

Phase 3
Build formal distribution graph

Phase 4
Validate every formal internal edge

Phase 5
Rewrite every internal edge during `set`

Phase 6
Add version_sync unit tests

Phase 7
Fix current stale A-share pins

Phase 8
Regenerate uv.lock

Phase 9
Run static/build/regression gates

Phase 10
Write P5 final certification report

Phase 11
Update roadmap to P6 current stage

Phase 12
Run final same-SHA CI
```

---

# 36. 推荐 Commit 拆分

建议两个逻辑 commit。

## Commit 1

```text
Fix: Enforce workspace release dependency graph integrity
```

包含：

```text
scripts/version_sync.py

tests/tools/test_version_sync.py

MiniQMT pyproject

Tushare pyproject

uv.lock
```

不要夹带 roadmap。

---

## Commit 2

```text
Docs: Close P5 certification and enter P6
```

包含：

```text
docs/roadmap.md

docs/reports/p5_market_product_composition_final_certification.md
```

不改 Runtime。

---

# 37. P0 Architecture Invariants

冻结：

```text
Workspace membership
→ root pyproject only

Formal distribution name
→ project.name

Formal distribution version
→ root release version

Formal internal dependency edge
→ exact root release version

External dependency
→ untouched

Test fixture own version
→ independent

Test fixture dependency on formal package
→ root release version
```

---

# 38. P0 Definition of Done

只有全部满足才能结束。

## Release Graph

```text
[ ] FORMAL_PACKAGES manual registry removed

[ ] formal workspace nodes derived from tool.uv.workspace.members

[ ] duplicate distribution names fail closed

[ ] all formal distribution versions == root version

[ ] all formal internal dependency pins == root version

[ ] project.dependencies covered

[ ] project.optional-dependencies covered

[ ] external dependencies untouched

[ ] test fixture references validated

[ ] stale CN A-share 0.3.6 dependency = 0
```

## Version Set

```text
[ ] `set VERSION` updates root

[ ] updates all formal package versions

[ ] updates all internal formal dependency edges

[ ] updates README

[ ] preserves external requirements

[ ] preserves markers/extras

[ ] regenerates lock

[ ] performs final check
```

## Tests

```text
[ ] valid graph PASS

[ ] stale internal edge FAIL

[ ] wrong node version FAIL

[ ] range internal dependency FAIL

[ ] missing internal specifier FAIL

[ ] optional internal stale edge FAIL

[ ] duplicate name FAIL

[ ] missing member project FAIL

[ ] external dependency unaffected

[ ] set-version graph rewrite PASS
```

## P5 Closure

```text
[ ] roadmap marks P5 DONE / CERTIFIED

[ ] roadmap current stage = P6

[ ] P5 final certification report added

[ ] historical reports not rewritten

[ ] no Runtime behavior changed
```

---

# 39. Validation Commands

先读取：

```text
AGENTS.md
pyproject.toml
scripts/test_suite.py
.github/workflows/quality.yml
```

以当前仓库正式命令为准。

至少执行：

```bash
uv sync --frozen --all-packages --all-groups
```

然后：

```bash
uv run python scripts/version_sync.py check
```

Unit tests：

```bash
uv run pytest tests/tools/test_version_sync.py -q
```

如果路径不同，使用真实新增测试路径。

Static：

```bash
uv run ruff check src tests examples packages scripts
uv run ruff format --check src tests examples packages scripts

uv run mypy src/onlyalpha
```

Provider/plugin mypy 使用当前 CI 中正式命令。

Build：

```bash
uv build --all-packages
```

Regression：

```bash
uv run python scripts/test_suite.py core-full
uv run python scripts/test_suite.py recovery
uv run python scripts/test_suite.py ashare
uv run python scripts/test_suite.py miniqmt-contract
```

最后：

```bash
git diff --check
```

---

# 40. 必须执行的静态检查

检查 stale pin：

```bash
rg -n 'onlyalpha-market-cn-ashare==0\.3\.6' .
```

目标：

```text
0
```

检查 internal workspace dependency：

不要简单只搜：

```text
onlyalpha==
```

使用新的：

```bash
uv run python scripts/version_sync.py check
```

作为最终 Authority。

---

# 41. CI 要求

最终 commit SHA 必须通过现有：

```text
Layered Quality
```

至少：

```text
static PASS

build PASS

core-full PASS

recovery PASS

ashare PASS

miniqmt-contract PASS

quality-gate PASS
```

不要因为本地测试通过就提前写：

```text
P5 DONE / CERTIFIED
```

Final certification 应以最终 same-SHA CI 为准。

如果当前 Codex 环境无法等待远端 CI：

Implementation Report 中必须明确：

```text
local implementation complete

remote same-SHA certification pending
```

不能伪造远端成功。

---

# 42. 最终 Implementation Report

完成后输出：

```text
1. Starting SHA

2. Root cause of stale dependency pin

3. Old version_sync authority model

4. New workspace graph authority model

5. Formal distribution discovery

6. Internal dependency validation

7. Internal dependency rewriting

8. Optional dependency handling

9. Test fixture handling

10. Current stale pin fix

11. uv.lock result

12. New version_sync tests

13. Local static/build/regression results

14. P5 final certification document

15. Roadmap stage transition

16. same-SHA CI status

17. Final P0 status

18. Next stage = P6
```

---

# 43. 最终必须回答的问题

## Question 1

如果未来新增：

```text
onlyalpha-market-hk-equity
```

并加入：

```toml
tool.uv.workspace.members
```

version_sync 是否自动把它识别成正式 distribution，而无需再修改：

```python
FORMAL_PACKAGES
```

答案必须：

```text
YES
```

---

## Question 2

如果未来：

```text
onlyalpha-plugin-ib
```

依赖：

```text
onlyalpha-market-hk-equity==old-version
```

CI 是否自动失败？

答案必须：

```text
YES
```

---

## Question 3

外部依赖：

```text
pandas
tushare
xtquant
tzdata
```

是否完全不受 internal release pin rewrite 影响？

答案必须：

```text
YES
```

---

## Question 4

完成本任务后是否实现了：

```text
SIM
```

答案必须：

```text
NO
```

P6 才实现。

---

# 44. 最终工程原则

整个任务必须遵守：

```text
Fix the invariant, not the symptom.

Workspace membership has one authority.

Release version has one authority.

Internal dependency graph has one validation path.

No package-name-specific dependency hacks.

No startswith-based requirement parsing.

Use Python packaging semantics.

Formal release graph is fail closed.

External dependencies remain external.

Do not mix release hygiene with Runtime refactor.

Do not reopen P5 architecture.

Do not change trading economics.

Close P5, then move forward.
```

---

# 最终验收状态

本任务完成后必须形成：

```text
OnlyAlpha Release Graph
        │
        ├── node versions consistent
        ├── internal edges consistent
        └── CI enforced
```

同时：

```text
P5
Market Product Composition Authority Neutralization
DONE / CERTIFIED
```

然后正式进入：

```text
P6
Sim Streaming Runtime Closure
```

P0 完成以后，不再创建 P5.5/P5.6。

除非发现真实 P5 regression bug，否则 Market Product Architecture 应冻结，下一阶段工程重点转移到：

```text
Trading Runtime boundary
SIM
Streaming Recovery
PAPER / SHADOW deletion
```
