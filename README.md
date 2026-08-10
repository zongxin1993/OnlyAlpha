# OnlyAlpha

> 面向可验证策略研发的确定性量化交易系统

OnlyAlpha 是一个模块化、配置驱动的量化交易系统内核。它以统一的 `OnlyEngine` 为唯一产品入口，将行情、指标、因子、策略、风控、订单、成交、持仓、账户、结果分析和恢复机制组织在同一条可审计运行链中。

当前版本重点解决三个问题：

1. **同一份输入能否得到可重复的回测结果**
2. **一笔成交能否形成可追踪、可恢复的账务事实**
3. **多个策略能否共享运行环境和账户，同时保持独立归因**

OnlyAlpha 当前处于 **Alpha** 阶段。确定性回测已经形成完整产品纵切面；Paper 模式已经完成真实 MiniQMT 行情下的历史启动、实时切换和只读观察验收，但仍不具备生产级模拟盘或实盘交易能力。

---

## 当前版本

| 项目 | 状态 |
|---|---|
| Version | `0.3.6` |
| Python | `>=3.12, <3.13` |
| Product stage | Alpha |
| Architecture | 模块化单体 |
| Primary runtime | Backtest |
| CN A-share durable contract | `CN_A_SHARE_DURABLE_BACKTEST_V1` / `"1"` — **CERTIFIED** finite product |
| License | MIT |

---

## 工程定位

OnlyAlpha 面向个人的量化工程，以确定性和易用性为主要目标，以多平台、多市场、多币种为基本开发基准，主要针对分钟级别量化程序，不考虑高频量化范围，且不是只运行单个脚本的回测工具。

关键指标：

- 构建可重复、可审计的策略；
- 策略回测与策略真实执行时，流程及代码高度一致；
- 验证订单、部分成交、费用、持仓和账户之间的经济不变量；
- 在一个 Engine 中运行一个或多个隔离的策略 Cluster；
- 使用统一市场规则描述不同市场的交易约束；
- 验证 checkpoint、restart 和故障恢复后结果是否保持一致；
- 支持接入多个历史数据插件和多个实时行情插件，并融合数据源给策略使用；
- 支持Web进行操作；
- 支持行情录制，外部因子录制等功能；
- 支持分布式回测及docker容器化部署；
- 多策略(**Cluster**)隔离式独立运行；
- 多种运行模式(**Live Backtest Paper Sim**)在一个Engine下同时运行；

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

支持4种Runtime，分别是：
- Live      : 真实账户交易环境
- Backtest  : 策略回测仿真环境
- Paper     ：策略投研环境，无任何券商及市场内容，核心任务是生成整理历史数据、生产指标、探索指标、因子和k线的关系。
- Sim       ：接入实时数据，使用仿真账户本地模拟交易。

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


## 风险声明

OnlyAlpha 当前为 Alpha 软件，仅用于研发、测试和验证。

它不构成投资建议，也不保证任何策略的收益。Paper 验收不等于真实交易能力，Virtual Broker 的成交结果不代表真实市场成交。将系统连接真实账户前，必须独立完成权限控制、风控、恢复、对账、监控和人工接管机制。

---

## License

MIT License
