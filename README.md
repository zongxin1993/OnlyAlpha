# OnlyAlpha

> 面向可验证策略研发的确定性量化交易系统

OnlyAlpha 是一个模块化、配置驱动的量化交易系统内核。它以统一的 `OnlyEngine` 为产品入口，将行情、指标、因子、策略、风控、订单、成交、持仓、账户、结果分析和恢复机制组织在同一条可审计运行链中。

当前版本重点解决三个问题：

1. **同一份输入能否得到可重复的回测结果**
2. **一笔成交能否形成可追踪、可恢复的账务事实**
3. **多个策略能否共享运行环境和账户，同时保持独立归因**

OnlyAlpha 当前处于 **Alpha** 阶段。确定性回测已经形成完整产品纵切面；Paper 模式已经完成真实 MiniQMT 行情下的历史启动、实时切换和只读观察验收，但仍不具备生产级模拟盘或实盘交易能力。

---

## 当前版本

| 项目 | 状态 |
|---|---|
| Version | `0.3.5` |
| Python | `>=3.12, <3.13` |
| Product stage | Alpha |
| Architecture | 模块化单体 |
| Primary runtime | Backtest |
| CN A-share durable contract | `CN_A_SHARE_DURABLE_BACKTEST_V1` / `"1"` — **CERTIFIED** finite product |
| License | MIT |

---

## 产品定位

OnlyAlpha 面向需要长期演进量化系统的研发者和团队，而不是只运行单个脚本的回测工具。

它适合用于：

- 构建可重复、可审计的策略回测；
- 验证订单、部分成交、费用、持仓和账户之间的经济不变量；
- 在一个 Engine 中运行一个或多个隔离的策略 Cluster；
- 使用统一市场规则描述不同市场的交易约束；
- 验证 checkpoint、restart 和故障恢复后结果是否保持一致；
- 接入历史数据插件和实时行情插件；
- 为后续 Paper、Live、Research 和 Web 产品提供统一核心模型。

它目前不适合用于：

- 直接连接真实账户自动交易；
- 生产级无人值守模拟盘或实盘；
- 高频 Tick/OrderBook 撮合；
- 完整期货、融资融券、做空或对冲交易；
- 完整多币种和外汇换算；
- 分布式大规模回测；
- 开箱即用的 Web 交易终端。

---

## 当前可用能力

### 1. 确定性回测

Backtest Runtime 已经形成正式产品链：

```text
Cluster Config
    ↓
OnlyEngine
    ↓
Runtime Planner / Assembler
    ↓
Historical Replay
    ↓
Indicator → Factor → Strategy
    ↓
Risk → Order → Virtual Broker
    ↓
Execution Processor
    ↓
Durable Commit → Ordered Projection
    ↓
Result → Analytics → Artifact → Report
```

当前回测链支持：

- 配置驱动的 Engine、Runtime 和 Cluster 装配；
- 单 Cluster 和多 Cluster 运行；
- 多 Cluster 共享 Runtime 和账户；
- 策略级独立资金、费用和收益归因；
- Calendar-aware Bar 回放和多周期聚合；
- 指标 Warmup、因子快照和受限策略 Context；
- Next-Bar 虚拟撮合；
- 确定性结果指纹；
- JSON、Parquet 和 Markdown 制品；
- Memory 和 SQLite 持久化；
- checkpoint、restart 和故障恢复测试。

### 2. 可恢复成交与账务链

当前正式 Durable Execution 范围为：

| 维度 | 当前支持 |
|---|---|
| Product-certified market profile | `GENERIC_T0_CASH` |
| Account | Cash |
| Order type | Limit |
| Position side | Long |
| Position mode | Netting |
| Open | Buy Open |
| Close | Sell Close |
| Fill | Whole / Partial / Multi-Fill |
| Terminal | Cancel / Reject / Expire |
| Persistence | Memory / SQLite |

Durable admission 本身不再由 Market Profile 名称授权，而由冻结的经济语义决定。P4.1 已完成 Execution Support
Authority；P4.2 已将 Cash + Limit + Long + Netting 的 BUY OPEN / SELL CLOSE Broker `Accepted`、`Trade`、
`Cancelled`、`Rejected`、`Expired` 全部纳入同一 Prepared Transaction → Durable Commit → Ordered Projection →
Forward Recovery 链。Market identity 继续作为审计证据；相同 shape 可复用同一内核不等于对应 Market Product 已完成端到端
Conformance。

每个 Broker 生命周期事实和每个成交 Fill 都形成独立、不可变的事务事实：

```text
Broker Update
    ↓
Prepared Transaction
    ↓
Durable Commit
    ↓
Ordered Projection
    ↓
Projection Ready
    ↓
Result / Analytics / Outbox
```

订单、持仓、Cluster Allocation、费用、账户和 Strategy Ledger 消费同一笔已提交事实。部分成交和跨 Bar 多次成交可在 checkpoint/restart 后继续恢复。

### 3. 多策略 Cluster

一个 Cluster 表示一个独立策略运行单元：

```text
Cluster
├── One Strategy
├── Zero or more Factors
├── Indicator scope
├── Subscription scope
└── Strategy Ledger scope
```

Cluster 只获得受限 Context，不直接持有 Runtime Manager，也不能绕过风控访问 Broker、Event Bus 或其他 Cluster 的私有状态。

多个兼容 Cluster 可以：

- 共享同一 Runtime；
- 共享真实账户级状态；
- 保持独立虚拟资金和收益归因；
- 按确定顺序处理同一行情时间片；
- 独立生成策略结果。

### 4. 市场规则

OnlyAlpha 内置以下 Market Profile：

- `GENERIC_T0_CASH`
- `GENERIC_MARGIN_FUTURES`
- `GENERIC_24X7_CRYPTO_SPOT`
- `CN_A_SHARE_CASH@2025.1`
- `CN_A_SHARE_CASH@2026.07`

这些 Profile 当前均属于 **Experimental**。Profile 存在不等于对应市场已经完成正式交易产品闭环。

`CN_A_SHARE_CASH` 按交易日自动解析 `2025.1` 与 `2026.07` 制度版本。已表达的主要规则包括：

- Long-only；
- 禁止裸卖空；
- 证券 T+1；
- 开盘集合竞价、连续竞价、午休和收盘集合竞价阶段；
- 主板、风险警示、创业板和科创板的版本化涨跌幅矩阵与 Tick 对齐上下限；
- 主板/创业板整手以及科创板最低 200、1 股递增；
- 零股仅允许清仓；
- 覆盖窗口从 2025-06-30 开始的生产级印花税/过户费 Authority，以及静态 Broker Contract Provisioning；
- Bar 成交量参与率；
- Next-Bar Open 撮合模型。

尚未完整覆盖新股特殊阶段、退市整理、北交所、可转债、融资融券、集合竞价、盘中临停以及全部历史税费版本。

A 股版本化 Reference Authority 已完成：板块、历史 ST、停牌、交易单位、价格精度和正式前收盘价可按
Instrument + Trading Day 唯一解析，并参与配置校验、Runtime 兼容性、Artifact 和恢复指纹。

P4.3 有限产品合同 `CN_A_SHARE_DURABLE_BACKTEST_V1`、合同版本 `"1"` 已完成认证。认证边界固定为
`CN_A_SHARE_CASH@2025.1`、普通 XSHG/XSHE CNY Cash-Long、Production Fee、T+1、Memory/SQLite 和 Forward Recovery；
产品 Conformance、恢复/确定性、静态/构建和远端 `Layered Quality / quality-gate` 已在同一认证提交上通过。
该结论仅适用于 [ADR 0067](docs/adr/0067-cn-a-share-production-durable-backtest-product.md) 定义的有限合同，详见
[P4.3 最终认证报告](docs/reports/p4_3_cn_a_share_production_durable_product_conformance.md)。它不表示完整中国 A 股产品、
Paper/Live 就绪，也不把仍为 **Experimental** 的 `CN_A_SHARE_CASH` Profile 家族升级为 Stable。

`CN_A_SHARE_PRODUCTION_MARKET_FEES@2025.06.30` 已提供普通 CNY A 股现金股票在 XSHG/XSHE 的生产印花税和过户费
Authority；窗口外 Fail Closed。真实账户佣金通过严格静态 Contract Snapshot 在 Composition 阶段安装，Account 只选择
Identity。MiniQMT Fee Evidence 查询、Broker 自动佣金发现和完整 A 股 Durable Product Conformance 仍未实现；费用产品完成
不等于交易产品闭环。Execution Capability Resolver 只按经济 shape 判断统一内核是否支持，不能单独证明或认证 A 股产品。

`OnlyMarketRuleEngine.evaluate_pre_trade()` 是 Runtime 唯一申报前市场规则权威。其结构化 Decision 固定记录制度版本、
Reference/编译指纹、交易阶段、数量政策、价格带和有序 Evaluation；Risk 与 Order 只消费该结果，不复制市场制度规则。

### 5. Paper 行情观察

Paper Runtime 当前已经完成以下真实 MiniQMT 验收范围：

- 任意时间启动；
- Historical Bootstrap；
- 开市期间 Historical → Live Handoff；
- Historical Watermark；
- 1 分钟外部 Bar；
- 1 分钟到 3 分钟内部聚合；
- Indicator / Factor Warmup；
- Observation 输出；
- Strategy Intent 生成；
- Shadow Execution 抑制；
- Reservation 创建和释放；
- 有序停止和资源关闭。

当前 Paper 模式是 **只读行情观察 + Shadow Execution**：

- 不启用 Broker；
- 不发送外部订单；
- 不产生真实成交；
- 不修改真实账户和仓位。

仍未完成：

- Reconnect；
- 实时 Gap Recovery；
- Streaming Checkpoint/Recovery；
- 真实 Broker；
- Broker 账户、订单、成交和仓位同步；
- 长时间无人值守运行；
- 生产环境兼容性矩阵。

---

## 产品状态

| 产品能力 | 状态 | 说明 |
|---|---|---|
| Deterministic Backtest | 当前范围完成 | 已形成配置、交易、结果、制品和恢复闭环 |
| Multi-Cluster Backtest | 当前范围完成 | 共享 Runtime/Account，独立 Ledger 与归因 |
| Generic T0 Cash Long Execution | 当前范围完成 | Limit、Long、Netting、Buy Open、Sell Close |
| Partial / Multi-Fill | 当前范围完成 | 支持同 Bar、跨 Bar 和恢复 |
| Result / Analytics / Report | 基础可用 | 已有基础收益、回撤、交易和 Exposure 统计 |
| A-share Cash Profile | 部分完成 | Profile 仍为 Experimental；有限 Durable Backtest V1 产品合同已认证 |
| Tushare Historical Data | 部分完成 | 日线、校验和缓存可用 |
| MiniQMT Historical Data | 部分完成 | 历史 Worker、缓存和兼容性边界已建立 |
| MiniQMT Paper Observation | 预览可用 | 当前验收范围通过，仍非生产级 Paper |
| Live Trading | 不可用 | Runtime Factory 明确返回 Unsupported |
| Standalone Shadow Runtime | 不可用 | Paper 内有 Shadow Execution，但独立 Runtime 未实现 |
| Research Workflow | 不可用 | Factor/Indicator 基础存在，Research Runtime 未实现 |
| Web / API Console | 不可用 | 尚未形成产品 |
| Distributed Backtest | 不可用 | 当前不在产品范围 |

---

## 安装

### 环境要求

- Python 3.12
- Git
- `uv`

```bash
git clone https://github.com/zongxin1993/OnlyAlpha.git
cd OnlyAlpha

uv sync --frozen --all-packages --all-groups
```

检查安装和内置 Market Profile：

```bash
uv run onlyalpha market profiles
```

---

## 快速开始

### 1. 校验配置

`--dry-run` 会执行配置 Schema、动态类型、插件、资源冲突、Runtime 分组和装配计划校验，但不会运行回测。

```bash
uv run onlyalpha run \
  --config examples/configs/tushare_daily_backtest.yaml \
  --dry-run
```

### 2. 运行 Tushare 日线回测

该示例需要 Tushare Token。

Linux / macOS：

```bash
export ONLYALPHA_TUSHARE_TOKEN="<your-token>"

uv run onlyalpha run \
  --config examples/configs/tushare_daily_backtest.yaml \
  --console-report
```

Windows PowerShell：

```powershell
$env:ONLYALPHA_TUSHARE_TOKEN = "<your-token>"

uv run onlyalpha run `
  --config examples/configs/tushare_daily_backtest.yaml `
  --console-report
```

### 3. 运行多个 Cluster

`--config` 可以重复使用。兼容配置会由 Runtime Planner 自动归入共享 Runtime。

```bash
uv run onlyalpha run \
  --config path/to/cluster-a/config.yaml \
  --config path/to/cluster-b/config.yaml
```

也可以从目录或 Glob 收集配置：

```bash
uv run onlyalpha run --config-dir path/to/clusters
uv run onlyalpha run --config-glob "path/to/clusters/**/config.yaml"
```

### 4. MiniQMT Paper 观察

运行前需要：

- Windows；
- 本地 QMT / MiniQMT；
- 可导入的 `xtquant`；
- 正确配置的 `userdata_mini` 环境。

```powershell
uv run onlyalpha run `
  --config examples/configs/miniqmt_paper_macd.yaml `
  --user-data user_data
```

该示例只观察行情并执行 Shadow Intent，不会连接交易 Broker 或发送真实订单。

运行期间按 Ctrl+C 会通过唯一 `OnlyEngine` 生命周期停止全部 Runtime 和 Cluster，并取消订阅、停止 worker/publisher、
关闭插件与 Runtime 资源。SIGINT/控制台中断退出码为 130，SIGTERM 为 143；关闭期间再次中断会强制退出。当前 Paper
没有 Streaming Checkpoint/Recovery，优雅退出不代表能够保存并从全部实时内存状态原位恢复。

### 5. 查看运行快照

```bash
uv run onlyalpha snapshot \
  --config path/to/config.yaml
```

### 6. 市场场景验证

```bash
uv run onlyalpha scenario validate path/to/scenario.yaml
uv run onlyalpha scenario run path/to/scenario.yaml
```

---

## 输出

默认用户数据目录为：

```text
./user_data
```

可以通过以下方式覆盖：

```bash
uv run onlyalpha run --user-data /path/to/user_data ...
```

或设置：

```text
ONLYALPHA_USER_DATA
```

回测运行会生成：

- Engine manifest；
- Runtime 和 Cluster 结果；
- Order / Trade / Position / Account 投影；
- JSON 制品；
- Parquet 数据；
- Markdown 报告；
- Console 报告；
- Determinism fingerprint；
- checkpoint 和 Runtime state。

Paper 模式可按配置输出 Console Observation 和 JSON Lines Observation。

---

## 核心概念

### OnlyEngine

`OnlyEngine` 是唯一产品级入口，负责：

- 注册 Cluster；
- 校验配置；
- 规划和装配 Runtime；
- 管理 Runtime 与 Cluster 生命周期；
- 管理共享插件资源；
- 汇总运行结果；
- 输出 Artifact 和 Report；
- 处理失败和资源释放。

外部应用不应自行创建另一套 Engine 或绕过 Engine 直接拼装交易组件。

### Runtime

Runtime 是全部可变交易状态的所有者：

- Clock；
- Event Bus；
- Market Data；
- Risk；
- Order；
- Position；
- Allocation；
- Account；
- Strategy Ledger；
- Fee；
- Settlement；
- Execution；
- Persistence；
- Checkpoint；
- Recovery。

### Strategy、Factor 与 Indicator

职责关系固定为：

```text
Indicator
    ↓
Factor
    ↓
Strategy
    ↓
Restricted Order Context
```

- Indicator 负责无交易副作用的滚动计算；
- Factor 组合 Indicator 并形成 Snapshot / Score；
- Strategy 读取行情和 Factor，产生交易意图；
- Strategy 不能直接修改订单、持仓、账户或 Broker 状态。

### Account 与 Strategy Ledger

```text
Account
= Runtime 级账户真值

Strategy Ledger
= Cluster 级虚拟资金和收益归因
```

多个 Cluster 可以共享 Account，但每个 Cluster 只读取自己的 Ledger Scope。

---

## 插件

Core 通过 Plugin SPI 与具体数据源和 Broker 解耦。

当前 Workspace 包含：

- Virtual Broker 插件；
- Tushare DataSource 插件；
- MiniQMT DataSource / Broker 插件。

插件应只依赖公开的 `onlyalpha.plugin.api`、Domain 类型和 Port，不应依赖 Runtime 内部 Manager 或装配实现。

---

## 测试

统一测试入口：

```bash
uv run python scripts/test_suite.py fast
uv run python scripts/test_suite.py integration
uv run python scripts/test_suite.py ashare
uv run python scripts/test_suite.py recovery
uv run python scripts/test_suite.py miniqmt-contract
uv run python scripts/test_suite.py miniqmt-local
uv run python scripts/test_suite.py core-full
uv run python scripts/test_suite.py release
```

测试分层包括：

- Unit
- Contract
- Architecture
- Integration
- Scenario
- Conformance
- Recovery
- External
- Performance

`release` 会组合执行静态检查、类型检查、版本一致性、离线完整测试、Recovery、A-share 验证和包构建。

真实 MiniQMT 和真实 Broker Account 测试必须显式启用，不进入默认离线测试通道。

---

## 开发约束

OnlyAlpha 的关键工程约束包括：

- Domain 使用强类型值对象和 UTC 时间；
- Runtime 是可变状态唯一所有者；
- Strategy 不能绕过 Context；
- Broker Update 必须进入 Runtime Queue；
- ExecutionProcessor 是成交更新的唯一业务入口；
- Committed Transaction 是逐笔成交权威；
- Collector 不从最终 Manager 状态反推成交；
- Event 在状态成功改变后发布，不驱动核心状态迁移；
- 不支持的市场能力必须 Fail Closed；
- 不能用测试开关绕过正式产品链；
- 同一输入必须产生稳定业务投影和结果指纹。

---

## 文档

- [总体架构](docs/architecture.md)
- [CLI](docs/cli.md)
- [测试规范](docs/testing.md)
- [路线图](docs/roadmap.md)
- [A 股 Market Profile](docs/a_share_market_profile.md)
- [A 股 Reference Authority](docs/reference_data_authority.md)
- [Paper 产品验收](docs/acceptance/paper_real_product_acceptance.md)
- [Backtest Runtime](docs/backtest.md)
- [Runtime](docs/runtime.md)
- [Virtual Broker](docs/virtual_broker.md)
- [Market Conformance](docs/market_conformance_suite.md)
- [CN A-share Durable Backtest V1 产品合同](docs/adr/0067-cn-a-share-production-durable-backtest-product.md)
- [P4.3 实施前审计](docs/reports/p4_3_cn_a_share_production_durable_product_pre_implementation_audit.md)
- [P4.3 最终认证报告](docs/reports/p4_3_cn_a_share_production_durable_product_conformance.md)

---

## 风险声明

OnlyAlpha 当前为 Alpha 软件，仅用于研发、测试和验证。

它不构成投资建议，也不保证任何策略的收益。Paper 验收不等于真实交易能力，Virtual Broker 的成交结果不代表真实市场成交。将系统连接真实账户前，必须独立完成权限控制、风控、恢复、对账、监控和人工接管机制。

---

## License

MIT License
