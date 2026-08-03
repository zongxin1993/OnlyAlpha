# P0.2 + P0.3：Test Fixture、MiniQMT Golden Dataset、并行策略与 CI Closure

## 1. 任务定位

任务名称：

```text
P0 Test Suite Performance & Layering Closure
```

包含两个原阶段：

```text
P0.2
Fixture、Recovery Baseline、MiniQMT Golden Dataset 与重复执行治理

P0.3
Worker 基准、性能监控、CI Lane 与 MiniQMT 外部验收门禁
```

本任务完成后，OnlyAlpha 的测试体系应从：

```text
已经能够分类和分通道运行
```

提升为：

```text
减少重复 Engine 执行
+
减少重复 SQLite/Parquet I/O
+
使用真实 MiniQMT 冻结数据离线验收
+
根据实测选择并行参数
+
在 CI 中形成稳定质量门禁
```

---

# 2. 当前基线

当前已实现：

```text
scripts/test_suite.py
scripts/pytest_layering.py
scripts/pytest_metrics.py
fast / integration / ashare / recovery
miniqmt-contract / miniqmt-local / full / release
Workspace 插件测试统一收集
Marker 合法性检查
JSON Metrics
```

当前实测：

| Lane             |  测试数 |      耗时 |
| ---------------- | ---: | ------: |
| fast             |  886 |  45.68s |
| integration      |  103 |  78.44s |
| ashare           |   17 |   7.11s |
| recovery         |  238 | 378.51s |
| miniqmt-contract |   10 |   6.81s |
| full             | 1247 | 691.37s |

当前主要问题：

```text
Recovery 测试重复构建无故障 Baseline
Analytics/Report/Artifact 重复运行 Engine
多个测试重复写入 Parquet、JSON、Markdown 和 SQLite
MiniQMT A 股离线 Golden Dataset 尚不存在
ashare Lane 只有规则测试，没有真实 MiniQMT 数据纵切面
Worker 数和 xdist 模式未经过完整矩阵实测
Metrics 没有历史趋势比较
GitHub CI 尚未建立对应 Lane
```

---

# 3. 总体目标

## 3.1 功能目标

完成以下能力：

```text
不可变标准 Result Fixture
Recovery Baseline Fixture
只读 SQLite Baseline Template
MiniQMT Golden Dataset Capture
MiniQMT Golden Dataset Offline Reader
A 股 MiniQMT 离线 Engine Smoke
Worker Matrix Benchmark
Metrics Baseline Comparison
PR / Nightly / Release CI Lane
Windows MiniQMT Local Gate
```

## 3.2 性能目标

性能数据必须在同一机器、相同代码和相同依赖条件下比较。

目标值：

| Lane             |      当前 |                  第一目标 |
| ---------------- | ------: | --------------------: |
| fast             |  45.68s |               不高于 60s |
| integration      |  78.44s |               不高于 90s |
| recovery         | 378.51s |           目标下降 20% 以上 |
| full             | 691.37s |           目标下降 15% 以上 |
| miniqmt-contract |   6.81s |               不高于 30s |
| ashare           |   7.11s | 增加 Golden 测试后不高于 120s |

性能目标在首次实施中作为验收目标和回归警告，不直接作为不稳定机器上的硬失败阈值。

## 3.3 质量目标

不得通过以下方式提速：

```text
删除关键测试
将失败测试改成 skip 或 xfail
降低经济状态对账
减少 Recovery 故障点
绕过 OnlyEngine
在生产代码增加 test_mode
省略 Durable Commit 或 Projection
共享可变 SQLite
合并独立 Fill
隐藏正式 Close Execution
默认跳过插件测试
```

---

# 4. 明确非目标

本任务不实现：

```text
CN A-share Reference Provider
A 股完整涨跌停产品链
完整停牌数据
A 股最低佣金业务实现
Paper Runtime
Live Runtime
真实 Broker 自动交易
YAML schema_version 修改
配置 Schema 2.0
公司行为
复权产品闭环
```

本任务可以为上述功能提供测试基础设施，但不得提前引入半完成业务路径。

---

# 5. 最终测试结构

建议形成以下结构：

```text
tests/
├── support/
│   ├── engine_results.py
│   ├── canonical.py
│   ├── recovery_baselines.py
│   ├── sqlite_templates.py
│   └── golden_data.py
├── fixtures/
│   ├── results/
│   ├── recovery/
│   └── miniqmt/
│       └── cn_a_share_v1/
├── unit/
├── contract/
├── architecture/
├── integration/
├── scenario/
├── conformance/
│   └── cn_a_share_cash/
└── recovery/
```

若当前目录结构无法一次迁移，不强制移动全部现有测试。可以先建立 `tests/support/` 和标准 Fixture，逐步迁移调用点。

测试辅助代码不得放入 `src/onlyalpha/` 正式产品包。

---

# 6. 工作包 A：标准不可变 Result Fixture

## 6.1 目的

减少以下模块重复执行完整 Engine：

```text
Analytics
Report
Artifact
Result Query
Result Collector
CLI Formatting
Schema Serialization
Fingerprint
```

## 6.2 新增模型

建议新增：

```python
@dataclass(frozen=True, slots=True)
class OnlyEngineTestResultFixture:
    fixture_id: str
    result: OnlyEngineResult
    canonical_projection: Mapping[str, object]
    result_fingerprint: str
    expected_trade_count: int
    expected_fill_count: int
    expected_terminal_count: int
    source_manifest: Mapping[str, object]
```

如部分测试需要文件目录，单独使用：

```python
@dataclass(frozen=True, slots=True)
class OnlyEngineArtifactFixture:
    result_fixture: OnlyEngineTestResultFixture
    output_directory: Path
```

不要把临时目录永久保存到不可变业务 Fixture 中。

## 6.3 标准场景

至少提供：

### `minimal_round_trip`

```text
一个 Instrument
一个 Cluster
BUY OPEN
SELL CLOSE
Whole Fill
Memory Store
最少 Bar
```

用途：

```text
Analytics
Report
Artifact
Collector
CLI
Result Schema
```

### `multi_fill_round_trip`

```text
BUY OPEN
Partial / Multi-Fill
SELL CLOSE
Partial / Multi-Fill
```

用途：

```text
Fill Result
Fee Accrual
Trade Aggregation
Result Fingerprint
```

### `multi_cluster_close`

```text
两个 Cluster
不同开仓成本
共享 Account
分别平仓
```

用途：

```text
Allocation
Strategy Ledger
Multi-Cluster Analytics
Result Aggregation
```

## 6.4 Fixture 生成方式

推荐优先级：

```text
1. 从正式 Engine 运行一次生成
2. 转换成稳定序列化 Fixture
3. 下游测试读取不可变 Fixture
```

不得手工拼装一个不符合正式结果合同的简化对象。

可以提供维护工具：

```text
scripts/regenerate_result_fixtures.py
```

但默认测试不得每次执行该工具。

## 6.5 Fixture 文件

建议保存：

```text
tests/fixtures/results/minimal_round_trip/result.json
tests/fixtures/results/minimal_round_trip/canonical_projection.json
tests/fixtures/results/minimal_round_trip/manifest.json
```

Manifest 包含：

```text
fixture_schema_version
OnlyAlpha version
生成场景
生成命令
Market Profile
Runtime Type
数据指纹
配置指纹
Result Fingerprint
生成时间
```

生成时间不参与业务 Fingerprint。

## 6.6 下游迁移

逐个审计并修改：

```text
tests/analytics/
tests/report/
tests/artifact/
tests/result/
tests/collector/
tests/cli/
```

规则：

```text
纯 Analytics 测试
→ 固定 Result

Report Renderer
→ 固定 Result 或固定 Analysis

Artifact Writer
→ 固定 Result + tmp_path

Collector
→ 固定 Fact/Snapshot

CLI Format
→ 固定 Result DTO

端到端集成
→ 保留一条完整 Engine 纵切面
```

## 6.7 验收

必须记录：

```text
迁移前 OnlyEngine 构造次数
迁移后 OnlyEngine 构造次数
迁移前 Engine.run 次数
迁移后 Engine.run 次数
迁移前 Parquet 写入次数
迁移后 Parquet 写入次数
```

至少应满足：

```text
下游纯组件测试不再重复运行相同 Engine 场景
每类产品结果保留至少一条正式 OnlyEngine 纵切面
```

---

# 7. 工作包 B：Recovery Baseline 复用

## 7.1 目的

当前最慢 Recovery 测试通常对每个故障点重复执行：

```text
Baseline Engine
+
Fault Engine
+
Restart Engine
```

目标结构：

```text
一次 Baseline
+
多个独立 Fault/Restart Case
```

## 7.2 Baseline 类型

至少建立：

```text
long_close_whole_baseline
long_close_multi_fill_baseline
multi_cluster_close_baseline
terminal_after_partial_fill_baseline
```

每个 Baseline 保存：

```text
Canonical Business Projection
Result Fingerprint
Committed Transaction IDs
Committed Fact IDs
Order/Fill Index
Position Snapshot
Allocation Snapshot
Account Snapshot
Ledger Snapshot
Risk Snapshot
Checkpoint Manifest
Broker Checkpoint
```

## 7.3 SQLite 模板

建议增加：

```python
@dataclass(frozen=True, slots=True)
class OnlyRecoveryBaseline:
    baseline_id: str
    database_template: Path
    checkpoint_id: str
    canonical_projection: Mapping[str, object]
    result_fingerprint: str
    manifest: Mapping[str, object]
```

执行流程：

```text
生成一次 Baseline SQLite
        ↓
关闭所有连接
        ↓
验证数据库完整
        ↓
标记为只读模板
        ↓
每个测试复制到独立 tmp_path
        ↓
故障注入
        ↓
Restart
        ↓
与 Canonical Baseline 对比
```

## 7.4 并行安全

必须保证：

```text
每个测试独立数据库
每个 Worker 独立目录
模板生成时有文件锁
模板只写一次
模板完成后不再修改
模板文件名包含内容 Fingerprint
```

禁止：

```text
多个 Worker 共享一个可写 SQLite
Session Fixture 假设跨 Worker 唯一
多个测试共享打开的数据库连接
```

## 7.5 Baseline 缓存策略

建议缓存键：

```text
baseline_id
+
scenario fingerprint
+
configuration fingerprint
+
persistence schema version
+
OnlyAlpha version
```

示例：

```text
.test-cache/recovery/
  long-close-multifill-<fingerprint>.sqlite3
```

`.test-cache/` 不提交 Git。

若缓存不存在：

```text
生成 → 校验 → 原子 rename
```

若缓存存在：

```text
验证 manifest 和 schema → 使用
```

## 7.6 故障测试保持完整

必须继续覆盖：

```text
before commit
after commit
mid projection
projection ready
outbox accepted
execute before publish
fill 1 checkpoint
fill 2 checkpoint
terminal transaction
A→B→C restart
registration order determinism
```

Baseline 复用不得删除故障点。

## 7.7 对账函数

建立统一比较器：

```python
def assert_recovery_equivalent(
    baseline: OnlyRecoveryBaseline,
    recovered: OnlyEngineResult,
) -> None:
    ...
```

比较范围至少包括：

```text
Orders
Fills
Terminal Facts
Committed Transactions
Position
Allocation
Account
Strategy Ledger
Risk Reservation
Fee Accrual
Result Fingerprint
Broker Checkpoint
MarketData Cursor
Outbox Business Facts
```

不要只比较最终现金和持仓。

## 7.8 验收

必须满足：

```text
Recovery 业务覆盖不减少
Recovery Fault 数量不减少
所有数据库独立
无跨 Worker 写冲突
所有经济 Projection 与 Baseline 等价
```

性能目标：

```text
Recovery Lane 中位耗时下降至少 20%
```

如未达到，必须提供最慢测试的新分析，不得伪造达标。

---

# 8. 工作包 C：MiniQMT Golden Dataset

## 8.1 目的

使 MiniQMT 成为 A 股默认真实数据来源，同时保持默认 CI：

```text
离线
确定性
可重复
不要求 Windows
不要求 xtquant
不要求 QMT 客户端
```

## 8.2 采集工具

新增：

```text
scripts/capture_miniqmt_golden.py
```

建议接口：

```powershell
uv run python scripts/capture_miniqmt_golden.py `
  --userdata-mini "C:\...\userdata_mini" `
  --instrument 600000.XSHG `
  --bar 1d `
  --start 2025-01-02 `
  --end 2025-01-10 `
  --adjustment none `
  --output tests/fixtures/miniqmt/cn_a_share_v1
```

支持后续扩展：

```text
多个 Instrument
1m/5m/1d
Reference
Calendar
Security Status
```

## 8.3 第一阶段数据范围

P0 阶段必须完成：

```text
历史 Bar
数据版本
采集 Manifest
内容 Fingerprint
离线读取
```

可以暂时不承诺 MiniQMT 已提供：

```text
完整 ST 历史
完整停牌历史
精确历史 Board 变化
完整 Calendar Provider
完整 previous_close Reference
```

未获取的字段必须明确记录为缺失。

## 8.4 数据目录

建议：

```text
tests/fixtures/miniqmt/cn_a_share_v1/
├── bars.parquet
├── instruments.json
├── calendar.json
├── reference.json
└── capture_manifest.json
```

第一阶段如果只有 Bar：

```text
bars.parquet
capture_manifest.json
```

也可以完成，但 Manifest 必须明确：

```json
{
  "available_resources": ["bars"],
  "missing_resources": [
    "historical_st_status",
    "historical_suspension",
    "effective_reference"
  ]
}
```

## 8.5 Manifest

必须包含：

```text
dataset_id
dataset_schema_version
provider
plugin_version
xtquant_version
capture_timestamp
instrument_ids
bar_types
start
end
timezone
adjustment
data_version
content_fingerprint
file_fingerprints
available_resources
missing_resources
```

`capture_timestamp` 不得影响内容 Fingerprint。

## 8.6 离线 DataSource

建议新增测试侧：

```python
class OnlyMiniQmtGoldenDataSource:
    ...
```

或复用 Scenario Exact DataSource：

```text
MiniQMT Golden Reader
→ 标准 OnlyMarketDataInboundUpdate
→ 正式 MarketData Pipeline
→ OnlyEngine
```

Golden Reader 不得绕过 MarketData Pipeline 直接向 Strategy 发送 Bar。

## 8.7 测试

增加：

### Contract

```text
Manifest Schema
File Fingerprint
Bar UTC 转换
Instrument Mapping
Data Range
无重复
稳定排序
OHLC 合法性
```

### Integration

```text
Golden Dataset
→ OnlyEngine
→ Virtual Broker
→ Result
```

### Determinism

```text
同一 Dataset 重复运行
→ Result Fingerprint 相同
```

### Tamper Detection

```text
修改 bars.parquet
→ Fingerprint 校验失败
```

## 8.8 A 股 Lane

`ashare` Lane 完成后至少包含：

```text
纯规则 Conformance
MiniQMT Golden Contract
MiniQMT Golden Engine Smoke
MiniQMT Golden Determinism
```

不能再出现：

```text
MiniQMT Golden 分片 0 tests
```

---

# 9. 工作包 D：Worker Matrix Benchmark

## 9.1 目的

根据真实机器和测试负载选择：

```text
Worker 数
xdist distribution mode
测试路径分片策略
```

而不是固定使用 `-n auto`。

## 9.2 新增工具

建议新增：

```text
scripts/benchmark_test_lanes.py
```

支持：

```powershell
uv run python scripts/benchmark_test_lanes.py `
  --lanes fast integration recovery full `
  --workers 4 6 8 auto `
  --dist load worksteal `
  --repeat 3
```

## 9.3 测量方法

每组至少执行 3 次，使用中位数。

记录：

```text
Lane
Worker
Dist
Run Number
Collected
Passed
Duration
CPU Count
OS
Python Version
Commit
```

不要使用第一次执行作为唯一基准，因为第一次可能受：

```text
Python bytecode
文件系统缓存
Windows Defender
Parquet import
SQLite cache
```

影响。

## 9.4 选择规则

不是单纯选择最快值，还要考虑稳定性。

推荐评分：

```text
Median Duration
+
P95/P50 抖动
+
失败率
+
资源竞争
```

如果：

```text
auto 比 6 Worker 只快 2%，但抖动高 30%
```

则选择 6 Worker。

## 9.5 Runner 调整

根据实测修改：

```text
scripts/test_suite.py
```

可能的目标配置：

```text
fast             auto / worksteal
integration      6 / worksteal
ashare           4 / worksteal
recovery         4 / worksteal
miniqmt-contract auto / worksteal
full             实测最优 / worksteal 或 load
miniqmt-local    serial
```

最终参数只能根据真实结果决定。

---

# 10. 工作包 E：Metrics 趋势与性能回归

## 10.1 扩展现有 Metrics

当前已有：

```text
collected
passed
failed
skipped
total_seconds
slowest_tests
marker_counts
path_counts
```

建议增加：

```text
setup_seconds
call_seconds
teardown_seconds
worker_count
dist
machine_id
git_commit
git_branch
baseline_commit
cache_hit_count
engine_run_count
sqlite_database_count
parquet_write_count
```

后四项可以通过测试 Hook 或显式计数器实现，但不得修改生产代码。

## 10.2 Baseline 文件

提交稳定基线：

```text
tests/performance/baselines/windows-py312.json
```

或：

```text
docs/reports/test_suite_performance_targets.json
```

基线只记录人工确认后的稳定结果，不应由每次 CI 自动覆盖。

## 10.3 比较工具

新增：

```text
scripts/compare_test_metrics.py
```

输出：

```text
总耗时变化
测试数量变化
最慢测试变化
新增长测试
消失测试
Marker 分布变化
```

示例：

```text
recovery: 378.51s → 292.20s，-22.8%
full: 691.37s → 565.40s，-18.2%
```

只允许输出真实数据。

## 10.4 门禁策略

初始采用软警告：

```text
总耗时增加 > 10%
单测试增加 > 20%
新增 Unit > 1s
新增 Integration > 10s
新增 Recovery > 30s
```

连续多次稳定后，再考虑硬失败。

---

# 11. 工作包 F：CI 工作流

## 11.1 PR Gate

建议新增或修改：

```text
.github/workflows/quality.yml
```

执行：

```text
Ruff
Ruff Format Check
Mypy Core
Mypy Tushare
Mypy MiniQMT
Version Sync
Fast
Integration
MiniQMT Contract
```

PR 默认不运行：

```text
External
MiniQMT Local
Recovery Exhaustive
真实网络
真实 Broker
```

涉及以下目录时，可增加 Recovery Smoke：

```text
src/onlyalpha/execution/
src/onlyalpha/persistence/
src/onlyalpha/runtime/
src/onlyalpha/position/
src/onlyalpha/allocation/
src/onlyalpha/account/
src/onlyalpha/strategy_ledger/
packages/fake/onlyalpha-plugin-broker-virtual/
```

不要仅依赖路径过滤跳过所有 Recovery；PR 仍可手动运行完整 Recovery。

## 11.2 Main Gate

推送到 `master` 后执行：

```text
Full Offline
Recovery Smoke
A-share Offline
Package Build
```

## 11.3 Nightly Gate

执行：

```text
Full Offline
Recovery Exhaustive
A-share Complete Conformance
Determinism Double Run
Worker Metrics
Package Build
```

保存：

```text
.test-metrics/*.json
失败日志
最慢测试报告
```

作为 Workflow Artifact。

## 11.4 Windows MiniQMT Gate

需要自托管 Windows Runner。

执行：

```text
MiniQMT Doctor
SDK Import
userdata_mini Check
Historical Data Query
Cache Round Trip
Account Query
Position Query
Order Query
Trade Query
```

必须串行。

默认不提交订单。

## 11.5 MiniQMT Order Gate

单独工作流：

```text
workflow_dispatch
```

要求：

```text
专用测试账户
明确确认参数
requires_broker_account
最小订单
明确交易标的
明确交易价格
提交后撤单策略
```

P0 可以只建立 Marker 和工作流边界，不要求立即启用真实下单。

---

# 12. 工作包 G：架构门禁

新增或扩展：

```text
tests/architecture/test_test_suite_layering.py
```

检查：

```text
所有测试都有主要 Marker
External 有明确 Requirement Marker
requires_broker_account 同时要求 Windows 和 Local QMT
离线 Lane 不选择 External
MiniQMT Contract 不导入真实 xtquant
Golden Dataset 不访问网络
测试辅助代码不进入 src/onlyalpha
生产代码无 test_mode
不存在 skip_recovery_for_test
不存在 skip_artifact_for_test
不存在 fake_engine_path
```

增加 Runner 自检：

```text
每条 Lane 至少收集一个测试
release 包含 full/recovery/ashare
miniqmt-local 永远串行
miniqmt-local 不包含 requires_broker_account
```

---

# 13. 详细实施顺序

## 阶段 1：测试重复路径审计

修改前先生成：

```text
docs/reports/p0_fixture_reuse_audit.md
```

内容：

```text
Engine.run 调用点
Result Fixture 候选
Recovery Baseline 候选
SQLite 创建点
Parquet 写入点
重复场景
当前耗时
```

完成后冻结本轮改造范围。

## 阶段 2：标准 Result Fixture

实现：

```text
tests/support/engine_results.py
tests/fixtures/results/
scripts/regenerate_result_fixtures.py
```

先迁移：

```text
Analytics
Report
Artifact
Collector
```

运行：

```text
fast
integration
full
```

## 阶段 3：Recovery Baseline

实现：

```text
tests/support/recovery_baselines.py
tests/support/sqlite_templates.py
```

优先迁移最慢的：

```text
Long Close Recovery
Multi-Fill Recovery
Multi-Cluster Recovery
```

运行：

```text
定向 Recovery
完整 Recovery
Full
```

## 阶段 4：MiniQMT Golden Dataset

实现：

```text
scripts/capture_miniqmt_golden.py
tests/support/golden_data.py
tests/fixtures/miniqmt/cn_a_share_v1/
```

增加：

```text
Contract
Integration
Determinism
Tamper Detection
```

运行：

```text
miniqmt-contract
ashare
integration
full
```

## 阶段 5：Worker Matrix

实现：

```text
scripts/benchmark_test_lanes.py
scripts/compare_test_metrics.py
```

执行完整矩阵，修改 `test_suite.py` 默认参数。

## 阶段 6：CI 和文档

实现：

```text
.github/workflows/quality.yml
.github/workflows/nightly.yml
.github/workflows/miniqmt-local.yml
docs/testing.md
AGENTS.md
README.md
docs/reports/test_suite_performance_baseline.md
```

---

# 14. 推荐提交拆分

建议至少拆成六个提交：

```text
Test: Audit repeated Engine and I/O costs

Test: Add immutable engine result fixtures

Test: Reuse recovery baselines and SQLite templates

Test: Add MiniQMT golden dataset capture and offline reader

Test: Benchmark xdist workers and extend metrics

CI: Add layered offline and MiniQMT test gates
```

不要把大规模 Fixture 重构、Golden Dataset 和 CI 混成一个不可审查提交。

---

# 15. 必须执行的验证

## 静态检查

```powershell
uv lock
uv sync --frozen --all-packages --all-groups

uv run ruff check src tests examples packages scripts
uv run ruff format --check src tests examples packages scripts
uv run mypy src/onlyalpha
```

## 分层测试

```powershell
uv run python scripts/test_suite.py fast
uv run python scripts/test_suite.py integration
uv run python scripts/test_suite.py miniqmt-contract
uv run python scripts/test_suite.py ashare
uv run python scripts/test_suite.py recovery
uv run python scripts/test_suite.py full
uv run python scripts/test_suite.py release
```

## Worker Matrix

```powershell
uv run python scripts/benchmark_test_lanes.py `
  --lanes fast integration recovery full `
  --workers 4 6 8 auto `
  --dist load worksteal `
  --repeat 3
```

## MiniQMT Local

只在环境可用时运行：

```powershell
uv run python scripts/test_suite.py miniqmt-local
```

环境不可用时必须记录：

```text
NOT EXECUTED
```

不能记录为通过。

---

# 16. 验收标准

## 16.1 功能验收

必须全部满足：

```text
标准 Result Fixture 已建立
Analytics 不再重复运行相同 Engine
Report 不再重复运行相同 Engine
Artifact 只测试必要文件 I/O
Recovery Baseline 可安全复用
每个 Recovery 测试使用独立 SQLite
MiniQMT Golden Dataset 可离线读取
ashare Lane 包含 MiniQMT Golden Engine 测试
同一 Golden Dataset 重复运行指纹一致
Worker Matrix 有真实数据
test_suite.py 使用实测并行配置
PR/Main/Nightly CI 已建立
MiniQMT Local 与 Order Gate 分离
```

## 16.2 业务验收

必须全部满足：

```text
交易结果不变
Position 结果不变
Allocation 结果不变
Account 结果不变
Strategy Ledger 结果不变
Fee 结果不变
Recovery 结果不变
Result Fingerprint 不变
Multi-Cluster 注册顺序确定性不变
```

Fixture 迁移后，如果正式结果发生变化，必须先判断是：

```text
Fixture 过时
```

还是：

```text
生产业务回归
```

不得直接更新 Golden 文件掩盖回归。

## 16.3 性能验收

采用同一机器 3 次运行中位数：

```text
Recovery 目标下降 ≥ 20%
Full 目标下降 ≥ 15%
Fast 不显著回退
Integration 不显著回退
MiniQMT Contract 保持快速
```

若目标未达到但功能改造正确，必须提供：

```text
实际提升
未达标原因
剩余最慢测试
下一轮优化建议
```

## 16.4 架构验收

必须确认：

```text
没有生产 test_mode
没有第二套 Engine
没有测试专用 Runtime
没有跳过 Durable Transaction
没有共享可变 SQLite
没有让 Golden Reader 绕过 MarketData Pipeline
没有把 MiniQMT External 加入离线 Lane
没有自动提交真实订单
没有修改 YAML schema_version
```

---

# 17. 完成后的测试通道语义

## fast

证明：

```text
领域对象
纯规划
Reducer
公共合同
插件映射
架构门禁
```

## integration

证明：

```text
最短正式 OnlyEngine 纵切面
```

## ashare

证明：

```text
A 股规则
MiniQMT 冻结数据
A 股离线 Engine Smoke
```

## recovery

证明：

```text
Durable Commit
Checkpoint
Restart
Projection
Outbox
业务等价
```

## miniqmt-contract

证明：

```text
MiniQMT SDK 形状到 OnlyAlpha 标准对象的转换
```

## miniqmt-local

证明：

```text
真实 Windows QMT 环境与查询能力
```

## full

证明：

```text
整个 Workspace 的全部离线能力
```

## release

证明：

```text
静态质量
完整离线功能
恢复
A 股
构建
```

---

# 18. P0 完成门槛

只有以下内容全部完成，才可以关闭 P0：

```text
测试分层存在
统一 Runner 存在
Metrics 存在
Result Fixture 复用完成
Recovery Baseline 复用完成
MiniQMT Golden Dataset 完成
Worker Matrix 完成
CI Lane 完成
文档与真实命令一致
性能结果有真实对比
关键覆盖没有下降
```

当前已经完成前三项，剩余内容属于本实施计划。

---

# 19. P0 完成后的下一步

P0 完成后，立即进入：

```text
PR4.5.1 MiniQMT Effective A-share Reference Authority
```

其目标是建立：

```text
MiniQMT / Frozen Reference
→ instrument_id + trading_day
→ Effective Instrument Reference
→ previous_close
→ board
→ ST status
→ suspended
→ tick size
→ lot size
→ version
→ fingerprint
```

随后进入：

```text
PR4.5.2
A 股 Pre-Trade / Match-Time / Fee / T+1 Closure

PR4.5.3
A 股 Conformance / Recovery / STABLE Promotion
```

P0 的最终价值不是单纯减少测试时间，而是为 A 股正式产品闭环建立：

```text
快速反馈
真实 MiniQMT 数据
离线确定性
完整恢复验证
稳定 CI 门禁
```
