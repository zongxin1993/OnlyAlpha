你现在位于 OnlyAlpha 仓库根目录。

仓库：

```text
https://github.com/zongxin1993/OnlyAlpha
```

当前默认分支：

```text
master
```

当前已知基线：

```text
项目版本：0.3.2
Python：>=3.12,<3.13

Windows 本地：
uv run pytest -n auto tests
约 8 分钟

uv run pytest tests
约 30 分钟
```

本任务名称：

```text
P0 Test Suite Performance & Layering
```

这是一个测试工程治理任务。目标不是删除测试，而是在不改变生产业务语义、不降低覆盖强度、不放宽经济不变量的前提下，建立清晰的测试分层、统一执行入口、可重复的测试数据和合理的并行策略，并显著减少重复运行完整 Engine、重复写入 Parquet/SQLite 和重复构造 Recovery Baseline 的成本。

---

# 一、工作原则

必须先审计当前工程，再修改。

不要仅根据本提示词假设代码结构。以当前源码、测试、`pyproject.toml`、`AGENTS.md`、ADR 和实际测试结果为准。

事实来源优先级：

```text
1. 当前源码
2. 当前自动化测试
3. 当前 ADR
4. 当前 AGENTS.md
5. 当前 README 和测试文档
6. 历史 Prompt
```

本任务不得修改 YAML `schema_version`。

本任务不得改变以下正式业务语义：

```text
OnlyEngine 唯一产品入口
Runtime 状态所有权
Cluster 隔离
Durable Transaction
Fill Identity
Projection 顺序
Position / Allocation / Account / Ledger Authority
Multi-Cluster Close Cost Authority
Fee Authority
Reservation 语义
Checkpoint / Recovery 语义
Result / Artifact 业务事实
```

---

# 二、总体目标

完成后必须提供以下稳定测试通道：

```text
fast
integration
ashare
recovery
miniqmt-contract
miniqmt-local
full
release
```

建议统一通过：

```powershell
uv run python scripts/test_suite.py fast
uv run python scripts/test_suite.py integration
uv run python scripts/test_suite.py ashare
uv run python scripts/test_suite.py recovery
uv run python scripts/test_suite.py miniqmt-contract
uv run python scripts/test_suite.py miniqmt-local
uv run python scripts/test_suite.py full
uv run python scripts/test_suite.py release
```

所有命令必须：

* 支持 Windows；
* 返回 pytest 的真实退出码；
* 打印实际 pytest 参数；
* 输出测试数量和总耗时；
* 输出最慢测试；
* 不依赖 Bash；
* 不隐藏失败；
* 不默认访问网络；
* 不默认连接真实 MiniQMT；
* 不默认提交真实订单。

---

# 三、先执行完整审计

在修改代码前，完成并保存测试审计报告：

```text
docs/reports/test_suite_performance_baseline.md
```

审计内容至少包括：

## 1. 测试收集范围

检查：

```text
pyproject.toml
tests/
packages/fake/onlyalpha-plugin-broker-virtual/tests/
packages/provider/onlyalpha-plugin-tushare/tests/
packages/provider/onlyalpha-plugin-miniqmt/tests/
scripts/
```

确认以下问题：

* `pytest tests` 实际收集哪些测试；
* 根 `testpaths` 实际收集哪些 Workspace 插件测试；
* Virtual Broker 测试是否被根命令遗漏；
* Tushare 和 MiniQMT 测试是否被根命令收集；
* External 测试是否可能意外进入默认测试；
* Marker 是否被广泛使用，还是仅在 `pyproject.toml` 中声明；
* 未标记测试的数量；
* 重复 Marker、含义模糊 Marker 和错误 Marker。

## 2. 当前性能基线

至少运行：

```powershell
uv run pytest tests -q --durations=100 --durations-min=0.2

uv run pytest -n auto --dist=load tests -q `
  --durations=100 `
  --durations-min=0.2
```

若机器资源允许，再比较：

```powershell
uv run pytest -n 4 --dist=worksteal tests -q
uv run pytest -n 6 --dist=worksteal tests -q
uv run pytest -n 8 --dist=worksteal tests -q
```

分别记录：

```text
收集时间
执行时间
串行时间
并行时间
Worker 数
最慢 100 个测试
最慢 20 个 Setup
最慢 20 个 Call
最慢 20 个 Teardown
各目录测试数量
各 Marker 测试数量
```

不要因基线耗时长而跳过。若完整命令在当前环境无法完成，应记录已经完成的范围、失败原因和现有数据，不得伪造时间。

## 3. 重复成本审计

搜索并统计：

```text
OnlyEngine.run
OnlyEngine(
OnlyBacktestRuntime
OnlyRuntimeAssembler
Parquet
pyarrow
SQLite
runtime.sqlite3
checkpoint
fault
artifact
report
analytics
result collector
```

识别：

* 同一个业务场景被哪些模块重复运行；
* 哪些 Analytics 测试重新运行完整 Engine；
* 哪些 Report 测试重新运行完整 Engine；
* 哪些 Artifact 测试重复运行 Engine；
* 哪些 Determinism 测试运行相同场景两次以上；
* 哪些 Recovery 测试每个故障点都重新生成无故障 Baseline；
* 哪些测试使用远超场景需要的 Bar 数；
* 哪些测试默认写 Parquet、Markdown、JSON 或 SQLite；
* 哪些测试可以下沉到纯 Unit 或 Contract；
* 哪些测试应继续保留完整产品纵切面。

输出一张表：

```text
测试/Fixture
当前耗时
主要成本
重复来源
建议层级
建议改造
是否保留完整 Engine
```

---

# 四、建立正式测试分层

使用以下主要层级：

```text
unit
contract
architecture
integration
scenario
conformance
recovery
external
performance
```

附加属性：

```text
slow
miniqmt
requires_network
requires_tushare
requires_local_qmt
requires_broker_account
windows
```

更新 `pyproject.toml` Marker 声明。

推荐语义：

```text
unit
单个纯函数、Value Object、Reducer、Planner Helper、Formula、Codec。

contract
公共接口、Port、Plugin SPI、Adapter Mapping、Config Parser、Schema。

architecture
依赖方向、产品入口、Authority、模块所有权和禁止模式。

integration
多个正式组件组成的本地离线纵切面。

scenario
由业务步骤和结果断言组成的正式 Engine 场景。

conformance
验证 Market Profile 声明的能力真实成立。

recovery
Checkpoint、Restart、Fault Injection、Projection Recovery。

external
依赖外部进程、SDK、网络、Token 或真实客户端。

performance
显式性能或规模测试，不进入默认快速回归。
```

## 自动标记

可以使用：

```text
tests/conftest.py
```

或专用 pytest 插件，根据路径增加默认 Marker。

但必须遵守：

* 显式 Marker 优先；
* 不覆盖测试已有的准确 Marker；
* 每个测试至少属于一个主要层级；
* 一个测试可以同时属于多个属性；
* External 测试必须显式标记；
* MiniQMT Fake SDK 测试属于 `contract + miniqmt`，不是 `external`；
* 真实 MiniQMT 测试属于 `external + miniqmt + requires_local_qmt + windows`；
* 真实 Broker 下单测试还必须有 `requires_broker_account`；
* 不允许通过自动标记把所有未知测试都错误归类为 Unit。

增加架构测试，验证所有测试的 Marker 合法性。

---

# 五、建立统一测试执行器

新增：

```text
scripts/test_suite.py
```

不要在多个 Shell 脚本、README 和 CI 中复制测试选择逻辑。

建议结构：

```python
class OnlyTestLane(StrEnum):
    FAST = "fast"
    INTEGRATION = "integration"
    ASHARE = "ashare"
    RECOVERY = "recovery"
    MINIQMT_CONTRACT = "miniqmt-contract"
    MINIQMT_LOCAL = "miniqmt-local"
    FULL = "full"
    RELEASE = "release"
```

每条 Lane 必须明确定义：

```text
测试路径
Marker 表达式
Worker 数
xdist distribution mode
durations 数量
是否允许 External
是否要求 Windows
是否要求 MiniQMT Path
是否要求 Broker Account
```

建议行为：

## fast

包括：

```text
unit
contract
architecture
```

排除：

```text
external
slow
performance
recovery
```

建议：

```text
-n auto
--dist=worksteal
```

## integration

包括：

```text
integration
scenario smoke
```

排除：

```text
recovery
external
slow
performance
完整 conformance matrix
```

## ashare

包括：

```text
CN_A_SHARE_CASH conformance
A 股 scenario
MiniQMT Golden Dataset 离线验收
```

排除真实 MiniQMT 环境。

## recovery

包括：

```text
recovery
```

默认：

```text
-n 4
--dist=worksteal
```

实际 Worker 数应根据基准调整。

## miniqmt-contract

包括：

```text
packages/provider/onlyalpha-plugin-miniqmt/tests
contract
miniqmt
not external
```

不允许导入真实 `xtquant` 作为测试前置条件。

## miniqmt-local

包括：

```text
miniqmt
external
requires_local_qmt
windows
not requires_broker_account
```

必须：

* 串行运行；
* 检查 Windows；
* 检查 `userdata_mini_path`；
* 检查 `xtquant` 可导入；
* 不提交真实订单；
* 环境不满足时给出明确错误，不要伪装测试通过。

## full

运行所有离线测试：

```text
not external
not requires_network
not requires_tushare
not requires_local_qmt
not requires_broker_account
not performance
```

必须覆盖全部 Workspace 包，而不只是根 `tests/`。

## release

至少依次执行：

```text
Ruff
Ruff format check
Mypy Core
Mypy Plugin Packages（若当前配置支持）
Version Sync
Full Offline
Recovery
A-share Conformance
Package Build 或现有 Release Gate
```

若仓库已有 `scripts/pre_commit_quality.py` 或其他质量入口，应审计后复用或调用，不得无意义创建第二套质量执行器。

---

# 六、建立测试耗时报告

新增 pytest 性能统计能力。

建议：

```text
tests/plugins/test_metrics.py
```

或：

```text
src/onlyalpha/testing/
```

但测试辅助代码不得进入正式运行产品包，除非仓库已有明确测试工具包边界。

输出目录：

```text
.test-metrics/
```

每次 Lane 执行输出 JSON：

```text
.test-metrics/fast.json
.test-metrics/integration.json
.test-metrics/ashare.json
.test-metrics/recovery.json
.test-metrics/full.json
```

每份报告至少包含：

```json
{
  "commit": "...",
  "lane": "fast",
  "platform": "...",
  "python_version": "...",
  "cpu_count": 0,
  "worker_count": 0,
  "distribution_mode": "...",
  "collected": 0,
  "passed": 0,
  "failed": 0,
  "skipped": 0,
  "total_seconds": 0,
  "slowest_tests": [],
  "marker_counts": {},
  "path_counts": {}
}
```

不要把 `.test-metrics/` 提交为持续变化的运行产物；更新 `.gitignore`。

可以提交一份人工整理的基线报告。

---

# 七、重构高成本 Fixture

## 1. 最短 Engine Smoke Fixture

新增一个只包含完成以下业务所需最少 Bar 的 Fixture：

```text
Warmup
BUY OPEN
SELL CLOSE
Result Ready
```

目标：

```text
3～20 个 Bar
Memory Persistence
一个 Instrument
一个 Cluster
不写 Parquet
不写 Markdown
```

不要继续使用包含数百根 Bar 的 Legacy MACD 场景验证所有下游模块。

保留较长数据集用于：

```text
完整 Equity Timeline
规模测试
真实策略行为
确定性压力
性能测试
```

## 2. 标准 Result Fixture

建立不可变 Result Fixture，供以下组件复用：

```text
Analytics
Report
Artifact Writer
Result Query
Collector
CLI formatting
```

推荐结构：

```python
@dataclass(frozen=True, slots=True)
class OnlyEngineTestResultFixture:
    result: OnlyEngineResult
    canonical_projection: Mapping[str, object]
    result_fingerprint: str
    runtime_directory: Path | None = None
```

模块内多个测试不得各自重新运行相同 Engine。

## 3. 下游组件测试下沉

### Analytics

输入固定 Result，只验证统计计算。

### Report

输入固定 Analytics/Result，只验证报告内容。

### Artifact

输入固定 Result，只验证：

```text
JSON
Parquet
Manifest
Schema
Fingerprint
Atomic Write
Overwrite Policy
```

### Collector

使用正式 Snapshot/Fact Fixture，不需要重新跑完整 Strategy。

保留一条完整：

```text
OnlyEngine → Result → Analytics → Artifact → Report
```

产品纵切面即可，不要每个模块都重复证明 Engine 能运行。

---

# 八、清理重复 Determinism 测试

审计所有执行同一业务场景两次或更多次的测试。

原则：

```text
一个业务能力保留一个明确的双运行 Determinism Test
```

其他组件的幂等性使用相同输入重复调用即可。

例如：

```text
Analytics determinism
使用同一个 Result 调用两次 Analytics

Report determinism
使用同一个 Analysis 渲染两次

Artifact determinism
使用同一个 Result 写入两个独立目录

Engine determinism
只有专门测试才运行两次完整 Engine
```

不得删除：

* 注册顺序确定性；
* Multi-Cluster 确定性；
* Checkpoint/Restart 等价性；
* Result Fingerprint 等价性。

只消除重复证明。

---

# 九、Recovery 测试性能治理

恢复测试不得削弱。

## 1. Baseline 复用

同一业务场景的多个故障点：

```text
after_commit
mid_projection
projection_ready
outbox
checkpoint
```

应复用同一个不可变 Baseline 结果。

不能让每个 Fault Test 都重新运行：

```text
无故障 Engine
故障 Engine
恢复 Engine
```

建议改为：

```text
一次 Baseline
+
每个故障点运行故障和恢复
```

如果 SQLite 初始状态可以安全复制，则使用：

```text
只读模板数据库
→ 每个测试复制到独立 tmp_path
```

不得让多个 Worker 共享同一个可变 SQLite 文件。

## 2. xdist 注意事项

pytest Session Fixture 在每个 Worker 中会各自创建，不能假设跨 Worker 全局复用。

跨 Worker 复用只能使用：

* 提交到仓库的不可变 Golden Fixture；
* 预生成只读数据库；
* 基于内容 Fingerprint 的缓存；
* 文件锁保护的只写一次缓存。

## 3. Recovery 层级

拆分为：

```text
Recovery Smoke
每次相关 PR 运行最关键故障点

Recovery Exhaustive
Nightly/Release 运行完整 Fault Matrix
```

不能把 Exhaustive 删除或改为 `xfail`。

---

# 十、MiniQMT 测试分层

OnlyAlpha A 股默认接入和验收源为 MiniQMT。

但测试必须分为三层。

## 1. MiniQMT Contract

完全离线，使用 Fake XtData、Fake XtTrader 和原始 SDK 形状对象。

验证：

```text
Symbol Mapping
Order Mapping
Status Mapping
Time Mapping
Historical Bar Mapping
OHLC Validation
Deduplication
Callback Mapping
Broker Update Enqueue
Config Validation
SDK Lazy Import
Cache Round Trip
```

Fake SDK 只能替代外部 SDK I/O。

Fake SDK 不得直接返回：

```text
OnlyOrder
OnlyPosition
OnlyAccount
OnlyTradeExecutionTransaction
OnlyEngineResult
```

否则会绕过 Adapter 的真实转换职责。

## 2. MiniQMT Golden Dataset

增加采集脚本，例如：

```text
scripts/capture_miniqmt_golden.py
```

输入示例：

```powershell
uv run python scripts/capture_miniqmt_golden.py `
  --instrument 600000.XSHG `
  --start 2025-01-02 `
  --end 2025-01-10 `
  --output tests/fixtures/miniqmt/cn_a_share_v1
```

Golden Dataset 至少包含：

```text
bars
instrument reference
calendar/trading dates
previous close
security status
capture manifest
```

若当前 MiniQMT API 尚不能提供全部 Reference 字段，则：

* 明确记录当前可采集字段；
* 为缺失字段设计稳定的 Fixture Schema；
* 不伪造“已经从 MiniQMT 获取”；
* 为后续 PR4.5 Reference Provider 留出接口；
* P0 阶段可以先完成 Bar 和现有 Adapter 数据的 Golden Capture。

Manifest 至少包含：

```text
provider
plugin version
xtquant version
capture timestamp
instrument IDs
date range
adjustment mode
data version
schema version
content fingerprint
```

默认 CI 只读取冻结后的 Golden Dataset，不调用真实 MiniQMT。

## 3. MiniQMT Local

真实外部测试分为：

```text
data
query
order
```

### data

允许自动：

```text
SDK Doctor
历史下载
行情查询
Bar 转换
Cache
```

### query

允许自动：

```text
连接
账户查询
持仓查询
订单查询
成交查询
```

### order

不得进入默认 Lane。

必须满足：

```text
requires_broker_account
专用测试账户
明确环境变量
显式人工触发
最小订单
清晰风险提示
```

本 P0 不需要自动实现真实下单验收，但必须建立独立 Marker 和执行边界，确保它永远不会被普通 `pytest` 误执行。

---

# 十一、文件 I/O 优化

默认测试优先：

```text
Memory Persistence
不生成完整 Artifact
不生成 Markdown
不写 Parquet
不写 SQLite
```

只有对应专项测试可以使用：

```text
Artifact → JSON/Parquet/Manifest
Recovery → SQLite
Report → Markdown
Cache → Parquet Historical Cache
```

所有文件测试必须使用：

```python
tmp_path
```

禁止：

* 固定输出目录；
* 测试之间复用可变文件；
* 多 Worker 写同一个路径；
* 依赖测试执行顺序；
* 依赖前一个测试生成 Artifact；
* 在仓库目录留下数据库或 Parquet 文件。

---

# 十二、并行策略

通过基准测试选择 Worker，而不是假设 `-n auto` 永远最快。

至少比较：

```text
-n 4 --dist=worksteal
-n 6 --dist=worksteal
-n 8 --dist=worksteal
-n auto --dist=worksteal
```

建议初始策略：

```text
fast
-n auto --dist=worksteal

integration
-n 6 --dist=worksteal

ashare
-n 4 或 6 --dist=worksteal

recovery
-n 4 --dist=worksteal

miniqmt-contract
-n auto --dist=worksteal

miniqmt-local
-n 0
```

最终值必须以实际基准为准。

脚本应支持：

```text
--workers
--dist
--durations
--no-parallel
```

覆盖默认设置。

---

# 十三、性能目标

先采集基线，再设置目标。

本任务目标参考：

```text
Fast Suite
≤ 90 秒

Core Integration Smoke
≤ 2 分钟

MiniQMT Contract
≤ 60 秒

A-share Offline Conformance Smoke
≤ 2 分钟

完整 Offline 并行
≤ 5～6 分钟

Recovery Exhaustive
独立执行
```

如果当前机器无法达到目标：

* 不得删除覆盖；
* 说明剩余主要耗时；
* 给出实际优化前后数据；
* 列出下一轮最有价值的优化项。

增加软性能门禁：

```text
Unit 单测试 > 1 秒 → 报告警告
Integration 单测试 > 10 秒 → 报告警告
Recovery 单测试 > 30 秒 → 报告警告
```

第一阶段不要因为普通机器略有抖动直接令 CI 失败。先输出警告和趋势数据。

---

# 十四、架构门禁

新增或更新 Architecture Test，禁止以下提速方式：

```text
生产代码出现 test_mode
生产代码出现 skip_artifact_for_test
生产代码出现 skip_recovery_for_test
生产代码出现 fake_engine_path
测试绕过 OnlyEngine 却声称验证产品链
删除经济不变量
隐藏 Close Execution
合并 Fill 以减少测试数量
将失败测试改为 xfail
外部测试进入默认离线 Lane
MiniQMT Contract 直接依赖真实 xtquant
真实 MiniQMT 下单进入普通 pytest
多个 Worker 共享可变 SQLite
```

同时检查：

```text
Core 不导入 MiniQMT/Tushare/Virtual Broker 具体插件
OnlyEngine 仍是唯一产品入口
测试辅助模块未反向污染生产模块
```

---

# 十五、依赖清理

当前 `pytest-xdist` 若仍位于正式 `[project].dependencies`，将它移动到 Dev Dependency Group。

测试工具不应成为 OnlyAlpha 最终用户的运行时依赖。

修改后运行：

```powershell
uv lock
uv sync --frozen --all-packages --all-groups
```

确认 Workspace 包仍可安装。

---

# 十六、文档

新增：

```text
docs/testing.md
```

内容必须包括：

```text
测试层级定义
各 Lane 命令
Marker 说明
MiniQMT Contract 与 Local 的区别
External 测试前置条件
Golden Dataset 更新方式
性能报告位置
失败定位方法
何时关闭 xdist
何时运行 Recovery
何时运行 Release
```

更新：

```text
README.md
AGENTS.md
```

但不要把测试细节全部堆进 README。

AGENTS 必须加入：

* 新测试应选择最低成本但正确的层级；
* 产品纵切面必须经过 OnlyEngine；
* 下游组件优先复用 Result Fixture；
* 长测试必须标记；
* External 测试不得进入默认离线门禁；
* MiniQMT 真实下单必须人工显式触发；
* 不允许生产测试开关。

---

# 十七、建议实施阶段

## P0.1 测试基线与分层治理

完成：

```text
基线报告
Marker 体系
自动标记或标记校验
test_suite.py
docs/testing.md
统一 Workspace 测试入口
```

此阶段尽量不修改业务测试内容。

## P0.2 Fixture 与重复执行治理

完成：

```text
短 Engine Smoke Fixture
标准 Result Fixture
Analytics/Report/Artifact 解耦
重复 Determinism 清理
Recovery Baseline 复用
MiniQMT Golden Dataset 基础
I/O 范围收缩
```

## P0.3 并行与质量门禁

完成：

```text
Worker 基准
Lane 默认并行策略
JSON Metrics
软性能预算
Architecture Gate
MiniQMT Local 串行边界
Release Lane
```

可以在一个 PR 中完成，但提交记录和代码结构必须能看出三个阶段。

---

# 十八、必须运行的验证

完成后至少运行：

```powershell
uv lock
uv sync --frozen --all-packages --all-groups

uv run ruff check src tests examples packages scripts
uv run ruff format --check src tests examples packages scripts
uv run mypy src/onlyalpha

uv run python scripts/test_suite.py fast
uv run python scripts/test_suite.py integration
uv run python scripts/test_suite.py miniqmt-contract
uv run python scripts/test_suite.py ashare
uv run python scripts/test_suite.py recovery
uv run python scripts/test_suite.py full
```

若插件包含独立 Mypy 配置或当前已有类型检查命令，也要执行。

`miniqmt-local` 只在当前环境具备真实 MiniQMT 时执行。环境不具备时，记录为未执行，不要把它算作通过。

对比优化前后：

```text
串行总时间
并行总时间
Fast 时间
Integration 时间
Recovery 时间
Engine Run 数量
Parquet 写入次数
SQLite 创建次数
最慢 20 个测试
```

---

# 十九、禁止事项

严禁：

```text
修改 YAML schema_version
修改正式交易结果以适配旧测试
删除关键 Integration/Recovery 覆盖
降低 Position/Allocation/Account/Ledger 对账
将失败测试改为 skip/xfail
在生产代码加入 test_mode
保留两套测试执行器
让 External 测试默认运行
让 MiniQMT Contract 依赖真实 SDK
自动向真实账户提交订单
伪造性能数据
仅修改 pytest 命令而不处理重复 Engine/I/O 成本
```

---

# 二十、最终交付

最终回答必须包含：

## 1. 审计结论

```text
原始测试规模
原始耗时
主要耗时来源
主要重复路径
```

## 2. 修改文件

逐项说明新增、修改和删除的文件。

## 3. 测试分层

说明每个 Lane 证明什么、运行什么、排除什么。

## 4. 性能结果

以表格给出：

```text
Lane
优化前
优化后
Worker
测试数量
结果
```

不得提供未实际测量的数字。

## 5. MiniQMT 边界

说明：

```text
哪些测试完全离线
哪些使用 Golden Dataset
哪些需要本地 MiniQMT
哪些可能访问真实账户
```

## 6. 未完成事项

如仍有慢测试或环境限制，明确列出。

## 7. 最终状态

必须确认：

```text
生产业务语义未改变
YAML Schema 未改变
关键业务覆盖未减少
Recovery 覆盖未被隐藏
MiniQMT 外部测试未进入默认离线 Suite
```

以真实代码、真实测试结果和真实性能数据为准完成任务。
