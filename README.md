# OnlyAlpha

> Backtest installation: `pip install onlyalpha onlyalpha-plugin-broker-virtual`.
> Core no longer contains a concrete Virtual Broker. `plugin: virtual` is resolved exclusively through the
> `onlyalpha.brokers` entry point provided by `onlyalpha-plugin-broker-virtual`.

OnlyAlpha 是一个面向量化交易系统的模块化、确定性 Python 框架。项目以 `OnlyEngine` 作为唯一产品级运行入口，通过相互隔离的 Runtime 和 Cluster 组织行情、策略、风控、订单、成交、持仓、账户、结果分析与运行制品。

OnlyAlpha 当前采用 **Monorepo + 模块化单体** 架构，优先保证：

* 运行结果可重放、可审计、可比较；
* 回测、模拟盘、实盘和研究模式共享核心领域模型；
* Strategy、Factor、Indicator、DataSource 和 Broker 通过明确边界扩展；
* 不同 Runtime、Cluster、账户和插件资源之间保持状态隔离；
* 金额、价格、数量、时间和市场规则具有明确且可验证的语义。

> **项目状态：Alpha**
>
> 当前已经形成确定性回测和 Scenario 产品纵切面，但尚未形成生产级实盘交易产品。MiniQMT Broker、Paper、Live、Shadow、Research、多市场规则和 Web 控制面仍处于不同阶段的开发或验证状态。请勿在未经独立验证、风控审查和券商仿真测试的情况下用于真实资金交易。

---

## 1. 核心设计

OnlyAlpha 的产品运行关系为：

```text
CLI / Application
        │
        ▼
OnlyEngine
        │
        ├── OnlyRuntimeSession A
        │     ├── OnlyCluster A1
        │     └── OnlyCluster A2
        │
        └── OnlyRuntimeSession B
              └── OnlyCluster B1
```

完整回测链路为：

```text
Cluster Config
→ OnlyEngine
→ Runtime Planner
→ Runtime Assembler
→ Historical DataSource
→ Historical Replay
→ Backtest Clock
→ MarketData Processor
→ MarketData Pipeline
→ Indicator
→ Factor
→ Strategy
→ Pre-Trade Risk
→ Order
→ Broker Execution Service
→ Virtual Broker
→ Matching Engine
→ Broker Inbound Queue
→ ExecutionProcessor
→ Position / Allocation
→ Strategy Ledger
→ Account
→ Result / Analytics
→ Artifact / Report
```

### Engine

`OnlyEngine` 是唯一产品级运行入口，负责：

* 加载和验证 Cluster 配置；
* 计算配置指纹；
* 根据兼容性对 Cluster 进行 Runtime 分组；
* 装配 Runtime、Cluster 和共享基础设施；
* 管理完整生命周期；
* 执行 Runtime；
* 汇总 Cluster 和 Runtime 结果；
* 写出 `user_data` 运行目录；
* 生成确定性指纹、Artifact 和 Report；
* 在失败时按逆序释放资源。

一个 Engine 实例只执行一次。进入 `STOPPED` 或 `FAILED` 后，应创建新的 Engine 实例。

### Runtime

Runtime 是可变运行状态的所有者。每个 Runtime 独占或管理自己的：

* Clock；
* Event Bus；
* MarketData Pipeline；
* MarketData Cache；
* Bar Aggregation；
* Broker Inbound Queue；
* ExecutionProcessor；
* Order、Position、Account 和 Risk 状态域；
* Runtime 级资源与生命周期。

当前注册的 Runtime 类型包括：

```text
BACKTEST
PAPER
LIVE
SHADOW
RESEARCH
```

其中，当前只有 `BACKTEST` 已形成确定性自动执行的完整产品链。其他模式不得隐式降级为 Backtest。

### Cluster

`OnlyCluster` 是 Runtime 内的隔离容器，不是策略基类。

每个 Cluster：

* 必须持有且只持有一个 Strategy；
* 可以持有零个或多个 Factor；
* 每个计算型 Factor 可以创建一个或多个 Indicator；
* 拥有独立的 Strategy、Factor、Indicator 和 Ledger Scope；
* 只能通过受限 Context 使用 Runtime 能力；
* 不直接访问 Broker、DataSource、EventBus、Manager 或可变 Cache。

固定计算顺序为：

```text
MarketData Snapshot
→ Indicator
→ Time-Series Factor
→ Cross-Section Factor
→ Factor Snapshot / Score
→ Strategy
→ ctx.orders
```

---

## 2. 当前能力

### 已形成正式产品链的能力

* `OnlyEngine` 生命周期、配置注册、Runtime 规划和运行；
* 一文件一 Cluster 的 YAML/JSON 配置模型；
* 多 Cluster 和 Runtime 兼容性分组；
* Synthetic Historical DataSource；
* Tushare Historical DataSource；
* Virtual Broker；
* 基础 Next-Bar 撮合；
* Risk、Order、ExecutionProcessor；
* Position、Allocation、Strategy Ledger 和 Account；
* T+1、Settlement 和 Market Rule 基础边界；
* Strategy、Factor、Indicator 分层；
* DataSource/Broker Plugin SPI；
* Python Entry Point 插件发现；
* 版本化 Market Profile、Compiler 和 Rule Engine；
* Scenario Parser、Planner、Engine Runner、Assertion 和 Artifact；
* JSON、Parquet、Markdown 和 Console 报告；
* 配置指纹、运行指纹和确定性重放基础；
* `user_data` 运行目录和历史数据缓存。

### 官方 Workspace 插件

| Distribution               | Python 包                   | 作用                                  | 平台                      |
| -------------------------- | -------------------------- | ----------------------------------- | ----------------------- |
| `onlyalpha`                | `onlyalpha`                | 核心领域模型、Engine、Runtime 和基础设施         | Windows / Linux / macOS |
| `onlyalpha-plugin-broker-virtual` | `onlyalpha_plugin_broker_virtual` | 确定性模拟 Broker | 跨平台 |
| `onlyalpha-plugin-tushare` | `onlyalpha_plugin_tushare` | Tushare 历史行情 DataSource             | 跨平台                     |
| `onlyalpha-plugin-miniqmt` | `onlyalpha_plugin_miniqmt` | MiniQMT DataSource 和 Broker Adapter | Windows                 |

### 尚未完成的能力

* 生产级 Live Runtime；
* 完整 Paper 产品循环；
* Shadow Runtime 产品闭环；
* Research 实验管理和研究工作流；
* Web、REST、WebSocket/SSE 和权限控制；
* 生产级断线恢复和状态持久恢复；
* 完整中国期货双向持仓和保证金事务链；
* 港股、美股、外汇、期权和数字资产衍生品产品适配；
* 公司行为、复权和完整参考数据治理；
* 订单簿级撮合；
* 高级绩效归因和组合分析；
* 分布式回测和远程 Worker。

---

## 3. Monorepo 结构

```text
OnlyAlpha/
├── src/onlyalpha/                         核心发行包
│   ├── analytics/                         回测分析
│   ├── application/                       应用查询服务
│   ├── artifact/                          运行制品
│   ├── broker/                            Broker Port、Virtual Broker
│   ├── cache/                             内存与历史行情缓存
│   ├── cluster/                           Cluster 容器与生命周期
│   ├── collector/                         标准事实收集
│   ├── config/                            Cluster 配置模型与解析
│   ├── data/                              DataSource、Replay 数据模型
│   ├── domain/                            金融领域模型和值对象
│   ├── engine/                            产品级 Engine
│   ├── event/                             Event 与 EventBus
│   ├── execution/                         标准成交处理
│   ├── factor/                            Factor 模型与依赖图
│   ├── fee/                               费用模型
│   ├── indicator/                         通用指标实现
│   ├── market/                            Market Profile 与规则
│   ├── market_data/                       行情处理、聚合与 Snapshot
│   ├── order/                             订单状态域
│   ├── output/                            user_data 布局和导出
│   ├── plugin/                            插件 SPI、发现和生命周期
│   ├── position/                          持仓、分配和对账
│   ├── report/                            Console/JSON/Markdown Report
│   ├── result/                            标准运行结果
│   ├── risk/                              风控与 Reservation
│   ├── runtime/                           Backtest/Paper/Live/Shadow/Research
│   ├── scenario/                          确定性市场 Scenario
│   ├── settlement/                        结算
│   ├── storage/                           Storage Port 和 SQLite
│   ├── strategy/                          Strategy API
│   └── strategy_ledger/                   Cluster 虚拟账本
│
├── packages/provider/
│   ├── onlyalpha-plugin-tushare/           Tushare 官方插件
│   └── onlyalpha-plugin-miniqmt/           MiniQMT 官方插件
│
├── examples/
│   ├── configs/                            可运行配置
│   ├── factor/                             示例 Factor
│   └── strategy/                           示例 Strategy
│
├── tests/                                  Core 测试和产品纵切面
├── scripts/                                工程自动化脚本
├── docs/                                   当前架构、组件和 ADR
├── prompts/                                历史实施任务和设计输入
├── .github/workflows/                      CI/CD 工作流
├── pyproject.toml                          根项目和 Workspace 配置
├── uv.lock                                 Monorepo 统一锁文件
└── AGENTS.md                               工程实施约束
```

`docs/reports/`、`prompts/` 和 `HANDOFF.md` 中可能包含特定阶段的历史描述。判断当前行为时，优先级为：

```text
当前源码和测试
→ 已接受 ADR
→ 当前架构文档
→ README / AGENTS
→ HANDOFF / reports / prompts
```

---

## 4. 环境要求

OnlyAlpha 当前统一使用：

```text
Python 3.12
uv
```

不支持 Python 3.13。

安装 uv 后，在仓库根目录执行：

```bash
uv sync --python 3.12 --all-packages --all-groups
```

安装 Git Hook：

```bash
uv run pre-commit install
```

确认命令入口：

```bash
uv run onlyalpha --help
```

查看内建 Market Profile：

```bash
uv run onlyalpha market profiles
```

---

## 5. 快速开始

### 5.1 验证配置但不运行

```bash
uv run onlyalpha run \
  --config examples/configs/tushare_daily_backtest.yaml \
  --user-data user_data \
  --dry-run
```

`--dry-run` 会执行：

* 配置解析；
* Strategy/Factor 类型加载；
* Runtime 兼容性规划；
* 插件发现；
* Capability 校验；
* 输出路径检查。

### 5.2 运行 Tushare 历史回测

Linux/macOS：

```bash
export ONLYALPHA_TUSHARE_TOKEN="<your-token>"

uv run onlyalpha run \
  --config examples/configs/tushare_daily_backtest.yaml \
  --user-data user_data \
  --console-report
```

PowerShell：

```powershell
$env:ONLYALPHA_TUSHARE_TOKEN = "<your-token>"

uv run onlyalpha run `
  --config examples/configs/tushare_daily_backtest.yaml `
  --user-data user_data `
  --console-report
```

Tushare 示例包含：

* A 股 Market Profile；
* 上海交易所日历；
* 静态 Universe；
* Tushare Historical DataSource；
* Parquet 历史数据缓存；
* Virtual Broker；
* MACD Factor；
* MACD Strategy；
* JSON 运行输出。

### 5.3 加载多个 Cluster

每个配置文件只能定义一个 Cluster。多个 Cluster 通过多个参数加载：

```bash
uv run onlyalpha run \
  --config path/to/cluster-a.yaml \
  --config path/to/cluster-b.yaml \
  --user-data user_data
```

也可以扫描目录：

```bash
uv run onlyalpha run \
  --config-dir examples/configs \
  --user-data user_data
```

或者使用 Glob：

```bash
uv run onlyalpha run \
  --config-glob "configs/**/*.yaml" \
  --user-data user_data
```

---

## 6. CLI

### 运行 Cluster

```text
onlyalpha run
```

主要参数：

```text
--config PATH           添加一个 Cluster 配置，可重复
--config-dir DIRECTORY  递归发现 config.yaml/config.yml/config.json
--config-glob PATTERN   使用 Glob 发现配置
--user-data DIRECTORY   指定运行数据目录
--engine-id ID          指定 Engine ID
--log-level LEVEL       DEBUG/INFO/WARNING/ERROR
--dry-run               只验证，不运行
--fail-fast             首个失败后停止
--no-fail-fast          允许其他 Runtime 继续执行
--console-report        输出回测报告
```

### Scenario

验证 Scenario：

```bash
uv run onlyalpha scenario validate path/to/scenario.yaml
```

运行 Scenario：

```bash
uv run onlyalpha scenario run \
  path/to/scenario.yaml \
  --user-data user_data
```

JSON 输出：

```bash
uv run onlyalpha scenario run \
  path/to/scenario.yaml \
  --format json
```

### Market Profile

列出 Profile：

```bash
uv run onlyalpha market profiles
```

查看指定 Profile：

```bash
uv run onlyalpha market profile CN_A_SHARE_CASH
```

查看固定版本：

```bash
uv run onlyalpha market profile CN_A_SHARE_CASH \
  --version 2025.1
```

---

## 7. Cluster 配置

一个 YAML 或 JSON 文档只能定义一个 Cluster，禁止使用顶层 `clusters[]`。

主要顶层区段：

```yaml
schema_version: "1.0"

cluster: {}
market: {}
runtime: {}
reference_data: {}
universes: []
data_sources: []
accounts: []
brokers: []
strategy: {}
factors: []
output: {}
```

关键规则：

* `cluster.runtime_type` 选择 Runtime；
* `market` 为必填区段；
* Strategy 和 Factor 使用 `python.module:OnlyClass`；
* DataSource 和 Broker 使用 `plugin` 字段；
* 插件专用参数放入 `extensions`；
* Runtime、插件和组件 Factory 分别解析自己的扩展字段；
* 所有业务时间必须为带时区的 UTC 时间；
* 金额、价格和数量在配置中应使用字符串表示精确十进制；
* 同一资源 ID 对应不同配置时必须拒绝；
* 配置标准化后参与稳定指纹计算。

配置模型入口：

```python
from onlyalpha.config import OnlyClusterRunConfig

config = OnlyClusterRunConfig.load("config.yaml")
```

产品运行入口：

```python
from pathlib import Path

from onlyalpha.domain.identifiers import OnlyEngineId
from onlyalpha.engine import OnlyEngine, OnlyEngineConfig

engine = OnlyEngine(
    OnlyEngineConfig(
        engine_id=OnlyEngineId("onlyalpha"),
        user_data_root=Path("user_data"),
    )
)

engine.add_cluster(config)
result = engine.run()
```

---

## 8. 插件系统

OnlyAlpha 使用 Python Entry Point 发现外部插件。

DataSource Entry Point：

```text
onlyalpha.data_sources
```

Broker Entry Point：

```text
onlyalpha.brokers
```

插件创建链：

```text
Entry Point
→ Plugin Descriptor
→ Factory Registry
→ parse_config()
→ Capability Validation
→ create()
→ Runtime Lifecycle
```

外部插件应优先从以下稳定入口导入 SPI：

```python
from onlyalpha.plugin.api import ...
```

插件不得依赖：

* Engine 内部装配器；
* Runtime Manager；
* Order/Position/Account Manager；
* Runtime 内部 Service Container；
* 测试模块；
* 其他具体插件实现。

内建插件：

```text
DataSource:
- synthetic
- scenario-exact

Broker:
- virtual
```

Workspace 官方插件：

```text
DataSource:
- tushare
- miniqmt

Broker:
- miniqmt
```

---

## 9. 运行输出

默认输出根目录为：

```text
./user_data
```

也可以通过以下方式覆盖：

```text
--user-data DIRECTORY
ONLYALPHA_USER_DATA
```

运行目录结构：

```text
user_data/
├── cache/
│   └── market_data/
└── runs/
    └── <engine_id>/
        └── <run_id>/
            ├── manifest.json
            ├── engine/
            │   ├── config.json
            │   └── summary.json
            ├── runtimes/
            │   └── <runtime_id>/
            │       ├── summary.json
            │       ├── result.json
            │       └── artifacts/
            ├── clusters/
            │   └── <cluster_id>/
            │       ├── normalized_config.json
            │       ├── source_config.yaml
            │       ├── fingerprint.txt
            │       ├── summary.json
            │       ├── report.md
            │       ├── orders/
            │       └── portfolio/
            ├── shared/
            └── logs/
```

Engine Result 提供：

* Engine ID；
* Run ID；
* 状态；
* Cluster 结果；
* 失败诊断；
* Manifest 路径；
* 确定性指纹；
* Backtest Report；
* Console Report；
* Runtime Result。

---

## 10. 开发和测试

### Ruff

```bash
uv run ruff check src tests examples packages scripts
uv run ruff format --check src tests examples packages scripts
```

自动修复和格式化：

```bash
uv run ruff check --fix src tests examples packages scripts
uv run ruff format src tests examples packages scripts
```

### Mypy

Core：

```bash
uv run mypy src/onlyalpha
```

Tushare：

```bash
uv run mypy \
  --config-file packages/provider/onlyalpha-plugin-tushare/pyproject.toml \
  packages/provider/onlyalpha-plugin-tushare/src/onlyalpha_plugin_tushare
```

MiniQMT：

```bash
uv run mypy \
  --config-file packages/provider/onlyalpha-plugin-miniqmt/pyproject.toml \
  packages/provider/onlyalpha-plugin-miniqmt/src/onlyalpha_plugin_miniqmt
```

### Pytest

不同 distribution 的测试应在独立 Pytest 进程中运行：

```bash
uv run pytest tests -q

uv run pytest \
  packages/provider/onlyalpha-plugin-tushare/tests \
  -q

uv run pytest \
  packages/provider/onlyalpha-plugin-miniqmt/tests \
  -q
```

默认测试不得连接真实网络、Tushare 或本地 MiniQMT。

Tushare 外部测试需要：

```text
ONLYALPHA_TUSHARE_TOKEN
```

MiniQMT 真实只读历史测试需要：

```text
ONLYALPHA_MINIQMT_REAL_HISTORY=1
```

并要求本机已经安装和运行可用的 MiniQMT/xtquant 环境。

### Pre-commit

运行全部 Hook：

```bash
uv run pre-commit run --all-files
```

### 版本一致性

检查 Core 和官方插件版本：

```bash
uv run python scripts/version_sync.py check
```

设置统一版本：

```bash
uv run python scripts/version_sync.py set 0.2.7
```

正式 Workspace 包采用 Lockstep Versioning：

```text
onlyalpha == X.Y.Z
onlyalpha-plugin-broker-virtual == X.Y.Z
onlyalpha-plugin-tushare == X.Y.Z
onlyalpha-plugin-miniqmt == X.Y.Z
```

插件对 Core 使用精确依赖：

```text
onlyalpha==X.Y.Z
```

---

## 11. 工程约束

* 所有公开 OnlyAlpha 类型使用 `Only` 前缀；
* 金额、价格、数量、费用和 PnL 使用 Decimal 语义；
* `market.fees` 与 `brokers[].fees` 经 Runtime Factory 显式注入唯一 `OnlyFeeResolver`；Broker 不作为本地费用真值；
* 业务绝对时间统一使用 UTC；
* 交易日和 Session 由 TradingCalendar 解释；
* Domain 不依赖 Runtime、Plugin、CLI 或外部 SDK；
* Event 只表达已经发生的事实；
* EventBus 不承担核心状态迁移；
* Strategy 只能通过受限 Context 下单；
* Factor 不具有交易权限；
* Broker 回报必须先进入 Runtime Inbound Queue；
* ExecutionProcessor 是 Broker Update 的唯一业务入口；
* Broker Snapshot 不得静默覆盖本地历史；
* Runtime 和 Result 不直接写文件；
* 所有非源码运行产物写入 `user_data`；
* 新能力必须接入正式 Engine 产品纵切面。

更完整的工程规则见 [AGENTS.md](AGENTS.md)。

---

## 12. 文档入口

* [总体架构](docs/architecture.md)
* [架构原则](docs/architecture_principles.md)
* [Engine](docs/engine.md)
* [Runtime](docs/runtime.md)
* [Runtime Context](docs/runtime_context.md)
* [Cluster](docs/cluster.md)
* [Cluster 配置](docs/cluster_configuration.md)
* [Strategy](docs/strategy.md)
* [Plugin System](docs/plugin_system.md)
* [DataSource Plugin](docs/data_source_plugin.md)
* [Broker Plugin](docs/broker_plugin.md)
* [Backtest](docs/backtest.md)
* [Market Profile](docs/versioned_market_profile_registry.md)
* [测试规范](docs/testing.md)
* [结果框架](docs/results_framework.md)
* [路线图](docs/roadmap.md)
* [架构决策](docs/adr/)

---

## 13. 贡献

提交代码前至少执行：

```bash
uv run pre-commit run --all-files

uv run pytest tests -q

uv run pytest \
  packages/provider/onlyalpha-plugin-tushare/tests \
  -q

uv run pytest \
  packages/provider/onlyalpha-plugin-miniqmt/tests \
  -q
```

Pull Request 应说明：

* 变更目标；
* 架构边界影响；
* 配置和公共 API 影响；
* 已执行的测试；
* 确定性影响；
* 外部 SDK 或网络依赖；
* 已知限制；
* 文档更新情况。

---

## 14. 许可证

OnlyAlpha 使用 MIT License。

本项目及其示例不构成投资建议、收益承诺或交易授权。使用者应自行承担数据、策略、软件故障、市场波动、券商接口和真实交易产生的全部风险。
