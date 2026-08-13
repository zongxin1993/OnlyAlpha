# OnlyAlpha Agent 工程指南

本文档适用于在 OnlyAlpha Monorepo 中工作的开发者、Codex、代码生成 Agent、审查 Agent、测试 Agent 和自动化工具。

它定义的是工程执行合同，而不是产品宣传材料。所有修改都必须服从当前源码、正式测试、未被替代的 ADR 和本文件规定的架构不变量。

子目录可以增加局部 `AGENTS.md`，但不得削弱本文件的顶层约束。

---

## 1. 项目身份

OnlyAlpha 是一个独立设计的模块化量化交易系统。

当前工程形态：

```text
Monorepo
+
模块化单体 Core
+
插件化 DataSource / Broker
+
配置驱动 Engine / Runtime / Cluster
```

项目目标不是快速堆叠交易功能，而是建立：

- 唯一、明确的状态权威；
- 可重复的运行结果；
- 可审计的交易事实；
- 可恢复的执行和账务链；
- 可扩展但不互相污染的市场与插件边界；
- Research 可复用纯数据/计算定义，Backtest、Sim、Live 共享正式交易语义核心。

禁止把 OnlyAlpha 描述为其他工程的重构版本，也禁止为了兼容历史实验代码而长期保留两套正式路径。

---

## 2. Runtime 架构合同与当前产品边界

修改任何功能前，必须先区分目标架构合同与当前实现事实。

### 2.1 目标 Runtime 架构合同

OnlyAlpha 唯一允许的目标 Runtime vocabulary 是：

```text
RESEARCH
BACKTEST
SIM
LIVE
```

| Runtime | 数据 | 执行 | Broker | 正式交易语义 |
|---|---|---|---|---|
| RESEARCH | Historical | Vectorized / Batch | None | 不承担 |
| BACKTEST | Historical | Event-driven | Virtual Broker | 完整承担 |
| SIM | Realtime | Event-driven | Virtual Broker | 完整承担 |
| LIVE | Realtime | Event-driven | Real Broker | 完整承担 |

正式原则：

```text
Research optimizes research efficiency.

Backtest / Sim / Live
share one trading semantic core.

Runtime Type
!=
Execution Permission.
```

`PAPER` 和 standalone `SHADOW` 不是目标产品 Runtime。当前源码中的相关 enum、配置、Factory、Runtime 和测试是迁移债务，不是长期兼容合同；不得新增依赖，也不得通过 alias、deprecated spelling 或 wrapper 长期保留。

### 2.2 当前正式完成范围

```text
Runtime          : BACKTEST
Market Product   : GENERIC_T0_CASH@1
Account Type     : CASH
Order Type       : LIMIT
Position Side    : LONG
Position Mode    : NETTING
Open             : BUY OPEN
Close            : SELL CLOSE
Fill             : Whole / Partial / Multi-Fill
Terminal         : Cancel / Reject / Expire
Cluster          : Single / Multi-Cluster
Persistence      : Memory / SQLite
Recovery         : Checkpoint / Restart / Forward Recovery
```

该范围已经形成：

```text
配置
→ Engine
→ Runtime
→ 行情回放
→ Indicator
→ Factor
→ Strategy
→ Risk
→ Order
→ Virtual Broker
→ Execution
→ Durable Commit
→ Ordered Projection
→ Result
→ Analytics
→ Artifact / Report
→ Checkpoint / Recovery
```

P6.3 另已完成 SIM 的 realtime Virtual Broker normal path：

```text
Runtime          : SIM
Market Product   : GENERIC_T0_CASH@1
Account / Order  : CASH / LIMIT / LONG NETTING
Open             : BUY OPEN
Data             : Historical Bootstrap → Realtime Handoff
Execution        : Virtual Broker Accepted → Next-Bar Trade
Durability       : Memory / SQLite Transaction + Ordered Projection
Checkpoint       : Disabled
```

该范围只证明正常因果链和 durable projection，不升级为 gap/reconnect/checkpoint/restart 或长期生产运行能力。

### 2.3 Legacy Streaming / SIM 迁移基线

当前源码 spelling `PAPER` 已实现并完成当前 Market Product 下的真实 MiniQMT 验收。它只表示 Sim 所需的一部分 streaming 基础设施已经存在：

```text
Historical Bootstrap
Open-Market Bootstrap
Historical → Live Handoff
Historical Watermark
1m External Bar
1m → 3m Internal Aggregation
Indicator / Factor Warmup
Observation
Strategy Intent
Shadow Execution Suppression
Reservation Create / Release
Ordered Shutdown
```

当前 `PAPER` 路径仍是：

```text
Read-only Market Observation
+
Shadow Execution
```

P6.3 已在独立 `OnlySimRuntime` 中以 Virtual Broker + 完整 Trading Kernel 替换 Shadow execution，关闭 realtime normal path。
`PAPER` 仍不是目标产品 Runtime，且不得据此声称 Production Sim 已完成。以下能力仍未闭环：

```text
Reconnect
Realtime Gap Recovery
Streaming Checkpoint / Recovery
Real Broker Submission
Broker Account Synchronization
Broker Order / Trade / Position Synchronization
Long-running Production Operations
Broad MiniQMT Compatibility Matrix
```

后续 P6 必须补齐 gap/reconnect/checkpoint/restart，迁移剩余基础设施和测试，然后删除 `PAPER` spelling/implementation；不保留 compatibility wrapper。

### 2.4 当前不可用或不存在的目标能力

以下 Runtime Factory 当前明确不可用：

```text
LIVE
Standalone SHADOW
RESEARCH
```

目标 `SIM` 已有 enum、配置、Factory 与 realtime Virtual Broker normal path；不得把它扩写为已具备 gap/reconnect、streaming checkpoint/restart 或 production operations。

注意：

```text
Paper 内有 Shadow Execution
≠
Standalone Shadow Runtime 已实现
```

当前 unsupported `SHADOW` Factory 也是待删除的实现债务；standalone Shadow 不得成为产品方向。`RESEARCH` 和 `LIVE` 虽是目标 Runtime，但当前生产工作流仍未完成。

### 2.5 领域模型不等于产品能力

以下对象即使存在，也不能据此声明产品已经支持：

- 枚举；
- Domain Model；
- Manager；
- Market Product identity / binding；
- Legacy Execution Path；
- 测试 Fixture；
- Prompt；
- 未接入 Engine 的示例；
- 单组件单元测试。

特别注意：

```text
GENERIC_MARGIN_FUTURES identity 或测试 fixture 存在
≠ Futures Durable Execution 已完成

GENERIC_24X7_CRYPTO_SPOT identity 或测试 fixture 存在
≠ Crypto 产品已完成

CN_A_SHARE_CASH Market Product Plugin 存在
≠ 完整 A 股产品已完成
```

---

## 3. 事实来源优先级

发现文档、测试和源码不一致时，按以下顺序判断：

```text
1. 当前可执行源码和正式公共接口
2. 当前自动化测试、架构门禁和产品验收
3. 未被替代的 ADR
4. AGENTS.md
5. docs/architecture.md 和当前组件文档
6. README.md
7. docs/roadmap.md
8. 带明确日期和提交基线的 docs/reports/
9. HANDOFF.md
10. prompts/
```

`prompts/` 是历史实施输入，不是当前工程事实。

不得仅根据 Prompt、旧报告或类名推断当前行为。

---

## 4. Agent 开始工作前的固定流程

任何非微小修改开始前，必须完成以下检查：

1. 阅读目标模块当前源码；
2. 阅读相关公共入口和 `__all__`；
3. 阅读目标模块测试；
4. 查找相关 ADR；
5. 查找现有 Port、Protocol、Factory、Registry 和 Query；
6. 确认唯一状态权威；
7. 确认当前产品支持范围；
8. 确认是否涉及持久化 Schema、Checkpoint 或 Result Schema；
9. 选择最窄但足够的测试 Lane；
10. 再实施修改。

必须先回答以下问题：

```text
谁拥有状态？
谁可以修改状态？
谁只能读取状态？
哪个对象是 durable authority？
失败发生在哪个边界？
恢复后必须与什么结果等价？
```

无法回答时，不得直接新增 Manager、Service 或并行路径。

---

## 5. 唯一产品入口

`OnlyEngine` 是唯一产品级运行入口。

正式产品调用链：

```text
CLI / Application
→ OnlyEngine
→ OnlyRuntimePlanner
→ OnlyEngineRunAssembler
→ Runtime Factory
→ OnlyRuntime
→ OnlyCluster
```

该调用链描述当前 Trading Runtime 产品入口。目标 Research Runtime 仍由 `OnlyEngine` 管理产品生命周期，但使用 Research Job / Plan，而不是伪造 Trading Cluster；在 Research 产品入口正式实现前不得据此新增生产框架。

允许的主要入口：

```python
engine.add_cluster(config)
engine.add_cluster_from_file(path)
engine.validate()
engine.initialize()
engine.start()
engine.wait()
engine.run()
engine.stop()
engine.close()
engine.snapshot()
```

约束：

- `OnlyEngine.run()` 只用于有限生命周期的 Backtest；
- 长生命周期 Runtime 使用 `initialize/start/wait/stop/close`；
- 一个 Engine 实例不得被重复完整运行；
- Engine 终止后不得重新打开；
- CLI 只负责参数、配置路径和 Application 调用。

禁止：

- CLI 直接实例化 Runtime Manager；
- CLI 直接执行回测循环；
- Scenario Runner 绕过 Engine；
- 验收脚本直接驱动 Strategy、Factor 或 Manager；
- 示例手工注入成交并宣称产品链通过；
- 创建市场专用第二套 Engine；
- 创建测试专用生产入口；
- 为单个功能复制一套 Engine Service。

---

## 6. Engine 职责

Engine 负责：

- Cluster Definition 注册；
- 配置和扩展类型验证；
- 配置指纹；
- Runtime 兼容性规划；
- Runtime Session；
- Cluster Session；
- 插件和共享基础设施引用计数；
- Runtime 装配；
- 生命周期；
- 运行结果汇总；
- `user_data` 布局；
- Artifact 和 Report；
- 失败回滚；
- 有序资源释放。

Engine 不负责：

- 策略算法；
- 指标计算；
- 市场数据标准化细节；
- Broker SDK 回调细节；
- 撮合算法；
- 费用公式；
- Position 成本计算；
- SQL 业务决策；
- 市场规则硬编码；
- Web 展示。

新增功能时，先判断它是 Engine 编排问题，还是 Runtime 内部业务问题。不得把业务计算塞入 Engine。

---

## 7. Trading Runtime 所有权与 Research 边界

目标 Trading Runtime 是：

```text
BACKTEST
SIM
LIVE
```

每个 Trading Runtime 是其全部 mutable trading authorities 的唯一所有者，并必须独占：

```text
Clock
Event Bus
MarketData Registry
MarketData Inbound Queue
MarketData Processor
MarketData Audit
MarketData Pipeline
MarketData Cache
Bar Aggregation
Broker Inbound Queue
Order Manager
Position Manager
Position Allocation Manager
Position Reservation Manager
Account Manager
Strategy Ledger Manager
Risk Service
Risk Reservation
Fee Authority
Settlement / Margin Service
ExecutionProcessor
Execution Transaction Store
Applied Projection Ledger
Outbox
Persistence Store
Checkpoint Participants
Recovery State
Runtime Audit
```

Research Runtime 只拥有：

```text
Research execution state
Dataset state
Calculation state
Research Result state
Research Artifact state
```

Research 不得仅为满足共享父类、Manager 数量对称或代码复用而创建 Order、Position、Account、Broker、Reservation、Execution Transaction 等 Trading Authorities。当前 `OnlyRuntime` 基类和 `PAPER`/`SHADOW` 源码呈现的 trading-shaped 结构属于待迁移实现事实，不得反向定义 Research 目标模型。

Research Dataset 的正式 authority 是 immutable Dataset Snapshot；Historical Cache 只负责 acquisition optimization，不是
Dataset authority。Provider identity 只进入 provenance，不进入 Dataset semantic identity。`onlyalpha.research` 不得导入
Trading authorities，Dataset Store 不得提供 append、update、overwrite 或 invalidate 语义。

当前源码仍存在 Position authority、Fee finality 和 compiled Market Rule identity 读取 Runtime mode 的历史分支，`OnlyRuntimeContext` 也仍暴露 `mode`。Durable Execution Capability Resolver 已保持 mode-neutral，但全系统尚未完成该中立化；这些分支和暴露面是必须审计/迁移的实现债务，不得复制、扩散或被 Strategy 消费，也不得写成目标经济合同。

Backtest / Sim / Live 追求 Trading Semantic Equivalence，而不是 Driver Implementation Equivalence。差异主要限于：

```text
Clock Driver
MarketData Driver
Broker Adapter
Lifecycle Driver
```

进入 Trading Kernel 后只能消费 normalized domain input、normalized broker facts、market instructions 和 economic context，不得消费 Runtime name 作为经济权限或业务规则。

禁止：

- Manager 被多个 Runtime 共享；
- Cluster 持有 Manager；
- Strategy 持有 Manager；
- Factor 持有 Manager；
- DataSource 或 Broker Gateway 持有 Manager；
- 插件直接修改 Runtime 状态；
- 通过全局单例保存 Runtime 交易状态。
- Strategy 根据 Runtime type 分支交易逻辑；
- Trading economics 或 Execution Support 根据 Runtime type 决定权限；
- 新建 `SimOrderManager`、`LivePositionManager`、`BacktestAccountManager` 等 Runtime 专用经济真值；
- SIM 连接或向 Real Broker 提交订单。

跨组件状态修改必须由 Trading Runtime 内正式 Service 或 Processor 编排。

---

## 8. Cluster、Strategy、Factor、Indicator

### 8.1 Cluster

一个 Cluster：

```text
One Strategy
+
Zero or more Factors
+
Indicator Scope
+
Subscription Scope
+
Strategy Ledger Scope
```

Cluster 是 Trading Runtime 的隔离 workload，不是 Strategy 本身，也不是 Research Job。

Cluster 不得：

- 访问其他 Cluster 私有订单；
- 访问其他 Cluster Allocation；
- 访问其他 Cluster Ledger；
- 直接访问 Broker；
- 直接访问 Runtime Event Bus；
- 推进 Runtime Clock；
- 修改账户级 Manager。

### 8.2 Research Job / Research Plan

Research Job 是研究任务，不得伪装成 Trading Cluster。它可以描述：

```text
Dataset
Universe
Time Range
Indicator / Factor / Feature definitions
Parameter Grid
Statistics specification
Output specification
```

Research 可以复用纯 Indicator / Factor 定义和 canonical data model，但不经过 Strategy、Order、Broker、Risk Reservation、Trading Account、Trading Position 或 Durable Trading Transaction。Web 只能查询 immutable Research Result / Artifact，不得操作 Runtime internal mutable state。

### 8.3 固定计算顺序

同一行情时间片的业务顺序必须显式确定：

```text
MarketData Validate / Process
→ Cache / Aggregation
→ Indicator
→ Time-Series Factor
→ Cross-Section Factor
→ Factor Snapshot / Score
→ Strategy
→ Risk
→ Order
```

不得依赖：

- 字典插入顺序；
- Set 顺序；
- Python 导入顺序；
- Cluster 注册顺序；
- Handler 注册偶然顺序；
- 外部 SDK 回调偶然顺序；
- 线程调度偶然顺序。

需要排序时，必须使用稳定、业务可解释的 Key。

### 8.4 Indicator

Indicator：

- 只能消费已验证的行情；
- 不具有交易权限；
- 必须显式处理 Warmup；
- 必须拒绝乱序输入或按正式合同去重；
- Checkpoint 能力必须显式声明；
- 恢复后输出必须与连续运行一致。

### 8.5 Factor

Factor：

- 可以组合 Indicator；
- 产生 Snapshot 和 Score；
- 不具有下单权限；
- 不直接访问 Account、Position 或 Broker；
- Cross-Section 调度必须由正式 Runtime/Cluster 流程完成。

### 8.6 Strategy

Strategy：

- 只能通过受限 Context 读取系统状态；
- 只能通过正式订单接口表达交易意图；
- 不得维护与 Runtime 真值并行的完整账户、订单或持仓副本；
- 不得绕过 Risk；
- 不得直接创建 Fill；
- 不得自行模拟 Broker 回报；
- Checkpoint 能力必须显式声明。
- 不得读取 Runtime type 后改变交易意图或经济逻辑。

---

## 9. Monorepo 包职责

### 9.1 Core

路径：

```text
src/onlyalpha/
```

Core 包含：

- Domain；
- Engine；
- Runtime；
- Cluster；
- Strategy / Factor / Indicator 公共边界；
- DataSource / Broker Port；
- Market Profile 和 Rule Engine；
- Risk / Order / Execution；
- Position / Allocation / Account / Ledger；
- Fee / Settlement；
- Persistence / Checkpoint / Recovery；
- Result / Analytics / Artifact / Report；
- Plugin SPI；
- CLI 和 Application Service。

Core 不得导入具体外部插件：

```text
onlyalpha_plugin_broker_virtual
onlyalpha_plugin_tushare
onlyalpha_plugin_miniqmt
```

Core 可以定义 Port、CreateRequest、Descriptor、Capability 和公共 DTO，但不能依赖插件实现。

### 9.2 Virtual Broker

路径：

```text
packages/fake/onlyalpha-plugin-broker-virtual/
```

职责：

- 实现 Broker SPI；
- 订单接受、拒绝和撤销；
- Next-Bar Matching；
- Slippage；
- Fill Plan；
- Whole / Partial / Multi-Fill；
- 确定性发布；
- Broker Checkpoint；
- 标准 Broker Update。

不得：

- 修改 Account；
- 修改 Position；
- 修改 Risk；
- 成为账务真值；
- 直接决定正式 Account Fee；
- 在插件中复制完整市场规则；
- 绕过 Broker Inbound Queue。

### 9.3 Tushare

路径：

```text
packages/provider/onlyalpha-plugin-tushare/
```

职责：

- 配置解析；
- Token 读取；
- SDK 调用；
- 历史行情请求；
- 数据标准化；
- 严格校验；
- Cache 协作；
- Factory 和 Entry Point；
- 环境诊断。

不得：

- 导入模块时访问网络；
- 修改 Runtime 交易状态；
- 把复权价格隐式当作撮合价格；
- 将 SDK 原始对象泄漏到 Core；
- 持有 Runtime Manager。

### 9.4 MiniQMT

路径：

```text
packages/provider/onlyalpha-plugin-miniqmt/
```

职责：

- Historical Worker；
- DataSource Adapter；
- Live Bar Adapter；
- Broker Adapter；
- SDK 数据到 Domain/Update 的转换；
- 配置和环境能力检查；
- 进程隔离；
- 协议和兼容性诊断。

不得：

- 让 Core 依赖 `xtquant`；
- 在 Core 导入 MiniQMT；
- 绕过 MarketData 或 Broker Inbound Queue；
- 直接修改 Manager；
- 未完成对账和恢复前启用真实资金；
- 把 Fake SDK 验收等同于真实产品验收。

---

## 10. 公共 API 与内部边界

外部用户和插件应优先使用：

```text
onlyalpha.engine
onlyalpha.config
onlyalpha.domain.*
onlyalpha.strategy
onlyalpha.factor
onlyalpha.indicator
onlyalpha.plugin.api
```

以下通常属于内部实现：

- Runtime Planner；
- Assembly Plan；
- Runtime/Cluster Session；
- Manager；
- Registry 内部容器；
- ExecutionProcessor 内部步骤；
- Recovery Orchestrator 内部状态；
- Persistence Store 具体 Schema；
- Projection Applier；
- 内部 Audit Store。

当前根包/`onlyalpha.runtime` 仍导出部分具体 Runtime 类，`onlyalpha.config` 仍导出 Assembly DTO，`onlyalpha.cluster` 仍导出 `OnlyClusterManager`。这是当前可导入事实和 API 收紧债务；不得谎称已经不可导入，也不得据此把 legacy `PAPER/SHADOW` 或内部编排对象升级为长期兼容合同。

规则：

- 公共 API 变更必须同步测试和文档；
- 不得仅因为内部模块可导入，就将其当成稳定 API；
- 插件不得依赖内部 Manager；
- 新公共接口必须有类型、合同测试和版本考虑；
- 删除旧公共接口前必须确认没有正式配置、示例或插件使用。

---

## 11. Market Product 与规则

### 11.0 Market Product Composition Authority

P5.3 已将 Trading Runtime 的生产组合一次性切换到唯一入口：

```text
OnlyMarketProductConfig
→ OnlyMarketProductFactoryRegistry
→ OnlyMarketProductFactory.resolve(...)
→ OnlyResolvedMarketProductBinding
→ Trading Runtime Composition
```

Market Product 属于 Trading Plane。Concrete Market Product Plugin 拥有具体市场知识并只依赖 Core Contract；Core 不得依赖 concrete market package。Research 不要求 Market Product Binding。

必须保持：

- Plugin provider identity 与 Product economic identity 分离；
- Product identity 只能用于 evidence、audit、artifact、fingerprint 和 compatibility proof，不得作为 Core behavior selector；
- Composition identity 只基于 resolution 后的 effective product/reference/policy/fee/config authorities，不得直接使用 raw YAML identity；
- Binding immutable，且不得持有 Order、Position、Account、Risk、Execution 或其他 mutable Runtime authority；
- Factory resolution context 只暴露 composition-time ports，不暴露 Engine/Runtime internals；
- Registry 只负责显式 factory lookup，unknown、duplicate、ambiguous 和 mismatch 必须 fail closed；
- 不得 implicit Generic fallback，不得 import-time global registration；
- Runtime type 不进入 Market Product economic contract；
- Market Product 与 Broker、DataSource、Risk、Execution Support 分离；Plugin 计算市场语义，Core 修改交易状态。
- Canonical Market IR 只包含 instrument economic terms、session、price、quantity、position、short、settlement 与 margin；不得包含 matching、slippage、latency、fill plan/schedule 或 simulation liquidity；
- `onlyalpha-market-generic-t0-cash` 定义 `GENERIC_T0_CASH@1` 的 Reference、Policy Compiler 与 Market Fee Pack，但不是 Core default 或 fallback；
- `onlyalpha-market-cn-ashare` 定义 `CN_A_SHARE_CASH@2025.1/2026.07` 的版本化 Reference、Policy Compiler 与 Market Fee Pack；
- `onlyalpha.market_products` entry-point discovery 是 concrete Market Product 的安装入口，Core composition root 只持有 neutral Registry，不硬注册 concrete product。

Generic 与 CN A-share 已同时完成生产 cutover。旧 Profile Registry、Core A-share Reference/Rules、concrete fee-pack selection 和 Runtime concrete-market branch 已删除；不得恢复 bridge、compatibility adapter、deprecated alias、Core hard registration 或 implicit fallback。

市场规则链固定为：

```text
OnlyMarketProductConfig
→ Market Product Factory Registry
→ Resolved Market Product Binding
→ Plugin-owned Policy Compiler
→ Runtime Rule Engine
→ Restricted Instruction / Decision
```

Market Product Plugin 拥有版本化市场语义；Binding 是一次 resolution 后的不可变组合事实，不是业务 Manager。

规则应由相应组件消费已编译的 Decision 或 Instruction。

禁止：

- Strategy 硬编码税率；
- Strategy 硬编码 T+1；
- Broker 硬编码完整市场规则；
- Risk 和 Broker 分别实现不同涨跌幅；
- Planner 直接猜测 Settlement Date；
- 根据证券代码前缀猜 board，而忽略 Reference；
- 在多个模块复制同一费用规则；
- Product 已配置但 Runtime 仍静默走 Generic 假设；
- 未知市场状态自动放行。

无法确定规则时必须 Fail Closed，并产生可诊断原因。

`OnlyMarketRuleEngine.evaluate_pre_trade()` 是 Runtime 唯一正式 Pre-Trade Market Rule Authority。Plugin-owned Reference 提供证券事实，
Plugin-owned Compiler 提供版本化制度并在 evaluate 前解析最终 Session/Price/Quantity Policy。Order、Risk、Strategy 与
Broker 不得复制交易阶段、价格带、Tick、申报数量或零股规则；主错误码必须来自固定顺序中的首个失败 Evaluation。

`CN_A_SHARE_CASH` 的板块、历史 ST、停牌、交易单位、价格精度和正式前收盘价只能来自版本化
CN A-share Market Product Plugin Reference，并由 plugin-owned authority 按 `Instrument + TradingDay` 解析。Runtime Factory
不得读取自由 `instrument_attributes`，不得以当前状态或上一根 Bar 回填历史 Reference。Registry 指纹必须参与
Runtime 兼容性、Artifact 和 Checkpoint 恢复校验。

Product identity 或插件存在不代表产品范围被升级；正式能力仍以有限产品合同、Conformance 和产品纵切面为准。

---

## 12. MarketData 合同

正式行情路径：

```text
DataSource
→ MarketData Inbound Queue
→ Sequence / Dedup / Gap / Quality
→ Audit
→ Pipeline
→ Cache / Aggregation
→ Indicator / Factor / Strategy
```

历史回放：

```text
Historical DataSource
→ Replay Service
→ Backtest Clock
→ Same MarketData Pipeline
```

约束：

- DataSource 不推进 Backtest Clock；
- 只有 Historical Replay Service 可以推进 Backtest Clock；
- Historical 和 Live 应复用同一 Domain Bar/Tick；
- Bar 必须明确 `[start, end)`；
- 只允许 Closed Bar 进入依赖 Closed Bar 的计算；
- Session 外数据必须显式拒绝并记录原因；
- Watermark 只能由成功进入正式 Pipeline 的数据推进；
- Provider 原始尾部不能直接成为 Processed Watermark；
- Catch-up、Dedup 和 Gap 必须有唯一 Authority；
- 不能通过修改 Bar 时间制造验收通过。

### 12.1 Legacy PAPER Bootstrap / SIM 迁移基线

当前 `PAPER` streaming 实现的调用顺序是：

```text
Subscribe and buffer live input
→ Capture / Freeze Bootstrap Boundary
→ Historical Request
→ Worker Validation
→ Parent Validation
→ Historical Replay
→ Indicator / Factor Ready
→ Historical Observation
→ Watermark
→ Live Handoff
```

目标不变量是 logical bootstrap boundary 明确、订阅与历史回放之间不丢数据、catch-up 顺序确定；P6 迁移到 Sim 时必须保留这些性质并由正式测试冻结，不能把当前调用顺序臆写成另一种已实现行为。

必须区分：

```text
Provider Raw
Accepted by Worker
Replay Attempted
Replay Processed
Replay Rejected
Pipeline Last Successful Bar
Historical Watermark
```

这些计数和尾部不得互相替代。

这些边界应在 P6 迁移到 `SIM`；不得为 `PAPER` 新增长期产品依赖，也不得复制第二套 streaming authority。

---

## 13. Event 合同

Event 用于通知已发生的事实，不作为核心状态迁移的唯一驱动力。

规则：

```text
Command / Function Call
→ Validate
→ Mutate / Commit
→ Publish Fact Event
```

禁止：

- Event Handler 决定 Manager 核心状态迁移；
- 依赖 EventBus priority 完成业务准备步骤；
- 在状态提交前发布成功事件；
- 失败后发布完整成功事实；
- 用 Event 重建本应来自 Transaction Store 的成交权威。

Recovery Event Gate 必须保证：

- 恢复历史 Direct Event 不重复外发；
- Bootstrap 事件有界；
- Runtime Open 前不泄漏不完整状态；
- Continuation Outbox 只在正式 Open 后交付；
- 失败语义可预测。

当前不得声称具备：

```text
Subscriber ACK
Delivery Watermark
Exactly-once Delivery
Durable Direct Event Journal
```

---

## 14. Broker 合同

Broker Gateway 只负责外部交易适配。

正式路径：

```text
Order Service
→ Broker Execution Service
→ Broker Gateway
→ External System
→ Broker Inbound Update
→ Broker Inbound Queue
→ ExecutionProcessor
```

禁止：

- Gateway 直接修改 Order Manager；
- Gateway 直接修改 Position；
- Gateway 直接修改 Account；
- SDK Callback 直接调用多个 Manager；
- Broker Update 绕过 Runtime Queue；
- Gateway 成为本地账务权威；
- 用 Broker Snapshot 静默覆盖本地历史；
- 用外部回报顺序作为业务确定性顺序。

重复、乱序和迟到 Update 必须通过正式 Identity、Sequence、Dedup 和 Reconciliation 处理。

---

## 15. Durable Execution 合同

当前正式 Durable Trade Capability：

```text
Market Product : GENERIC_T0_CASH@1
Account        : CASH
Order Type     : LIMIT
Position Side  : LONG
Position Mode  : NETTING
Open           : BUY OPEN
Close          : SELL CLOSE
```

不可破坏的核心合同：

```text
One Fill
=
One Immutable Prepared Transaction
=
One Committed Transaction
```

每个 Fill 必须具有：

```text
Stable Fill Identity
Stable Payload Fingerprint
Per-Order Fill Index
Execution Sequence
Prepared Transaction
Committed Transaction
Ordered Projection
Projection Ready
Durable Outbox Intent
```

禁止：

- 多个 Fill 合并成一个可变事务；
- Commit 后修改 Transaction；
- 使用外部 Source Sequence 代替 Fill Index；
- 正式 Capability 回退到 Legacy Mutation；
- Projection 外跨多个 Manager 手工更新；
- 失败后补写伪事实使结果对齐；
- 通过删除断言放宽经济不变量。

### 15.1 Operation Kind

当前正式 Runtime Operation Kind：

```text
ORDER_ACCEPTED
TRADE_FILL
ORDER_TERMINAL
SETTLEMENT_MATURITY
FEE_RECONCILIATION
```

`ORDER_ACCEPTED`：

- 冻结 Broker Accepted identity 和 payload；
- 投影 Order 与相应 Reservation stage；
- 不伪造成 Trade。

`TRADE_FILL`：

- 必须有真实 Trade Identity；
- 必须进入 Trade Result；
- 必须包含经济事实。

`ORDER_TERMINAL`：

```text
CANCELLED
REJECTED
EXPIRED
```

规则：

- 不得伪造 Trade ID；
- 不计入 Trade Count；
- 不产生 Trade PnL；
- 不产生 Trade Settlement；
- 只投影终态需要的 Order/Reservation/Risk 变化。

`SETTLEMENT_MATURITY` 只按 committed Settlement Instruction 将到期资产/资金投影为可用状态，不重新猜测市场制度。

`FEE_RECONCILIATION` 用新的 durable fact 表达外部 Broker evidence 与历史 Fee Application 的差额；不得覆盖已提交费用历史。

---

## 16. Planner、Transaction 与 Projection

Planner 是纯经济决策边界。

Prepared Transaction 应冻结：

```text
Before State
After State
Economic Fact
Cost Authority
Fee Decision
Settlement Instruction
Reservation Delta
Risk Delta
Ordered Projection
Payload Hash
Authority Hash
```

Projection 应安装或验证 Planner 已决定的结果，不应重新做经济决策。

禁止在 Projection 阶段重新计算：

- Released Cost；
- Realized PnL；
- Fee；
- Settlement；
- Reservation Delta；
- Risk Delta；
- Allocation Attribution。

Projection 顺序属于正式合同。修改顺序时必须：

1. 给出业务原因；
2. 更新 Planner；
3. 更新 Projection Targets；
4. 更新 Recovery；
5. 更新 Checkpoint；
6. 更新 Result/Collector；
7. 增加故障点测试；
8. 更新 ADR。

---

## 17. Position、Allocation 与 Close Cost Authority

正式模型：

```text
Position
=
Account 级聚合仓位权威

Allocation
=
Cluster 级数量和成本归属权威
```

Multi-Cluster Close：

```text
Order Cluster
→ Locate Allocation
→ Validate Position / Allocation Aggregate
→ Calculate Released Cost Once
→ Calculate Realized PnL Once
→ Position / Allocation / Account / Ledger / Fact consume same result
```

必须保持：

```text
Position Quantity
=
sum(Allocation Quantity)

Position Cumulative Cost
=
sum(Allocation Cumulative Cost)

Position Released Cost
=
Allocation Released Cost
=
Committed Fact Released Cost

Position PnL Delta
=
Allocation PnL Delta
=
Account PnL Delta
=
Strategy Ledger PnL Delta
=
Committed Fact PnL Delta
```

禁止：

- Position 和 Allocation 分别计算释放成本；
- Account 重新计算 Close PnL；
- Ledger 重新计算 Close PnL；
- 无法归因时回退到账户平均成本；
- Unallocated Close 静默成功；
- Cross-Cluster Close 未定义时自动调拨；
- 增加 `legacy_close_cost` 一类兼容开关。

无法解释的成本必须在 Commit 前 Fail Closed。

---

## 18. 精度规则

交易、成本和费用计算必须使用 `Decimal`。

正式成本权威优先保存：

```text
cumulative_open_price_quantity
```

平均价格是派生值，不得反向成为精确成本权威。

规则：

- 使用局部 Decimal Context；
- 明确 Precision；
- 明确舍入模式；
- 不修改全局 Decimal Context；
- Money 按 Currency Precision 量化；
- Price 按 Instrument Precision/Tick 量化；
- Quantity 按 Quantity Increment 量化；
- 最终完全平仓时数量和累计成本必须严格归零；
- 不使用 Binary Float 参与正式账务计算；
- 序列化 Decimal 使用字符串。

任何精度修改都必须覆盖：

```text
Whole Fill
Partial Fill
Multi-Fill
Different Fill Price
Fee
Positive PnL
Negative PnL
Zero PnL
Full Close
Checkpoint / Restart
```

---

## 19. Account 与 Strategy Ledger

Account：

```text
Runtime 级账户权威
```

Strategy Ledger：

```text
Cluster 级虚拟资金和收益归因权威
```

两者必须消费同一份 Committed Economic Fact。

不得：

- Account 从 Position Average 重算 PnL；
- Ledger 从 Allocation Average 重算 PnL；
- 为通过对账只修正 Ledger；
- 以某一个 Cluster Ledger 与共享 Account 直接比较；
- Strategy 维护完整独立账户副本；
- Broker Snapshot 静默替换本地 Account。

Multi-Cluster 对账必须比较：

```text
Account
与
所有正式 Strategy Ledger 的聚合
```

---

## 20. Risk 与 Reservation

所有订单必须在创建前经过 Risk。

正式顺序：

```text
Strategy Intent
→ Market Rule Validation
→ Risk Evaluation
→ Reservation
→ Order Creation
→ Broker Submission
```

Reservation 是正式交易权威的一部分。

Partial/Multi-Fill 下必须：

- 按 Fill 增量消费；
- 未完成部分继续保留；
- 最终 Fill 完成后释放剩余；
- Cancel/Reject/Expire 通过 Terminal Transaction 释放；
- Duplicate Update 不重复消费；
- Recovery 后与连续运行一致。

禁止：

- OrderService 绕过 Risk；
- Risk 只记录告警但继续创建订单；
- Manager 之间直接互相释放 Reservation；
- 失败后依赖 cleanup 猜测占用；
- 使用生产 `test_mode` 关闭风控；
- Strategy 直接修改 Risk State。

---

## 21. Fee 与 Settlement

费用权威链：

```text
Market / Broker Fee Config
→ Versioned Schedule Registry
→ Runtime Assembly
→ Fee Resolver
→ Fee Instruction
→ Order Fee Accrual Authority
→ Fee Manager
```

必须区分：

```text
FILL
ORDER_CUMULATIVE
```

跨部分成交最低佣金等订单累计费用必须由独立 Authority 管理，不能让每个 Fill 独立重复收取。

Settlement 必须由 Market Rule / Instruction 驱动。

禁止：

- Strategy 计算正式费用；
- Virtual Broker 直接写 Account Fee；
- Account 再次计算 Fee；
- Settlement Manager 自行猜交易日；
- 把费用差额作为测试补丁写入 Ledger；
- 修改历史 Fee Schedule 而不增加版本。

---

## 22. Persistence、Checkpoint 与 Recovery

### 22.1 Durable Authority

成交的 Durable Authority 是 Transaction Store。

Applied Projection Ledger 是可重建的幂等索引，不是成交真值。

Collector 和 Analytics 必须读取正式 Projection Ready / Committed Fact，不得从最终 Manager Snapshot 反推逐笔成交。

### 22.2 Checkpoint

Checkpoint 必须：

- 在明确完成边界创建；
- 记录精确 MarketData Cursor；
- 记录 Participant Schema Version；
- 原子写入；
- 可读回验证；
- 不包含不稳定对象地址；
- 不包含明文 Secret；
- 支持确定性恢复。

新增有状态组件时，必须明确：

```text
Checkpointable
Stateless
Unsupported
```

不得默认忽略。

### 22.3 Recovery

恢复原则：

```text
Restore Durable State
→ Validate Authority
→ Resolve Transaction Tail
→ Resume Ordered Projection
→ Rebuild Derived Index
→ Validate Aggregate
→ Open Runtime
→ Deliver Continuation Events
```

OnlyAlpha 使用 Forward Recovery，不提供跨 Manager Rollback。

禁止：

- Commit 后通过全局回滚恢复；
- 删除 committed transaction；
- 跳过失败 Projection 并继续；
- Recovery 期间发布重复历史事件；
- 用最终 Snapshot 掩盖中间事务缺失；
- 恢复失败后自动创建空 Runtime；
- 旧 Schema 不兼容时静默迁移。

Persistence Schema 或 Checkpoint Schema 变化必须有显式版本和迁移/拒绝策略。

---

## 23. Result、Analytics、Artifact 与 Observation

Result 的逐笔成交来源必须是：

```text
Projection Ready Committed Fact
```

不得从以下来源重建成交：

- Broker 内部状态；
- Order 最终 Snapshot；
- Position 最终 Snapshot；
- Account 最终余额；
- EventBus 历史；
- 测试手工构造列表。

Result 必须保持：

- 可序列化；
- 稳定字段语义；
- 明确空集合 Schema；
- 稳定 Determinism Fingerprint；
- Cluster Scope 正确；
- Runtime Scope 正确。

Artifact 写入要求：

- 原子写入；
- Manifest；
- 相对路径；
- Fingerprint；
- Decimal 字符串；
- Timestamp UTC ISO-8601 或明确 Unix nanos；
- Enum 使用 value；
- 不泄漏 Secret、Token、账户凭据和用户绝对路径。

Legacy `PAPER` Observation（未来迁移到 `SIM`）：

- 只读；
- 不成为交易状态权威；
- Latest Store 和 Sink 不得阻塞核心 Runtime；
- Observation 丢弃必须可计数和诊断；
- 停止后不得继续增长。

---

## 24. 配置规则

一个 Cluster 配置应完整描述：

- Cluster；
- Runtime；
- Market；
- Reference Data；
- Universe；
- DataSource；
- Account；
- Broker；
- Strategy；
- Factor；
- Indicator；
- Output。

规则：

- 配置必须版本化；
- 未知字段不能静默吞掉；
- 类型转换必须显式；
- Secret 通过环境变量或安全注入获取；
- 配置不能直接嵌入 Runtime Manager；
- 配置引用的动态类型必须在 dry-run 校验；
- Market Product、DataSource 和 Broker Capability 必须在装配前验证；
- 不兼容 Cluster 必须拆分 Runtime 或 Fail Closed；
- 配置指纹必须稳定。

修改配置 Schema 时必须同步：

```text
Parser
DTO
Validation
Normalized Payload
Fingerprint
Example Config
Contract Test
CLI dry-run
Documentation
```

---

## 25. 插件规则

插件发现依赖 Entry Point、Descriptor 和 Capability。

插件必须：

- 通过公共 Plugin API；
- 提供稳定 Plugin ID 和 Version；
- 声明 Capability；
- 提供配置 Parser；
- 提供 Validate Request；
- 提供显式 Lifecycle；
- 把外部异常转为可诊断错误；
- 不在 import 阶段执行外部副作用；
- 不泄漏 SDK 原始对象到 Core；
- 不读取未声明的全局状态。

Core 不得提供隐藏的具体插件回退实现。

插件不存在或不兼容时必须产生明确失败，不得静默切换到 Synthetic、Placeholder 或其他插件。

---

## 26. 测试分层

统一入口：

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

主 Marker：

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

附加 Marker：

```text
slow
miniqmt
requires_network
requires_tushare
requires_local_qmt
requires_broker_account
windows
```

### 26.1 Lane 选择

| 修改范围 | 最低验证 |
|---|---|
| 纯值对象、纯函数 | 目标单测 + `fast` |
| 公共 API / Plugin SPI | Contract + `fast` |
| Engine / Runtime / Cluster | `integration` |
| Market Product / A-share 规则 | `ashare` |
| Transaction / Projection / Checkpoint | `recovery` |
| MiniQMT 转换 | `miniqmt-contract` |
| 本地真实 MiniQMT | `miniqmt-local`，仅显式环境 |
| 跨模块或发布变更 | `full` |
| 发布候选 | `release` |

实际运行最窄的正确集合，但不得用“小测试已通过”替代必须的 Recovery 或 Conformance。

### 26.2 测试原则

禁止：

- 删除覆盖来缩短时间；
- 使用 `skip`/`xfail` 掩盖回归；
- 放宽经济不变量；
- 增加生产 `test_mode`；
- 手工构造成功 Fill 替代 Virtual Broker；
- 通过 sleep 修复确定性问题；
- 让离线测试访问网络；
- 普通测试连接真实账户；
- 多个 Worker 共享可写 SQLite；
- 使用本机时区作为隐含输入；
- 只断言最终余额而忽略逐笔事实。

测试应优先复用：

- 固定 Result Fixture；
- 只读 Recovery Baseline；
- MiniQMT Golden Dataset；
- Exact Scenario Input。

但产品纵切面、故障恢复和确定性专项测试必须保留完整 Engine 运行。

### 26.3 真实环境边界

Fake SDK 通过只能证明 Contract，不等于真实产品通过。

真实 MiniQMT：

- 必须显式 opt-in；
- 必须使用对应 Marker；
- 必须串行；
- 不满足环境时记录 Not Executed；
- 不得伪造 PASS。

真实订单：

- 必须使用独立 Manual Gate；
- 必须显式账户和权限；
- 不进入普通 CI；
- 不进入默认 `miniqmt-local`；
- 未完成安全门禁前不得自动提交。

---

## 27. 静态质量门禁

项目使用：

```text
Python 3.12
uv
Ruff
Ruff Format
mypy strict
pytest
pytest-xdist
```

常用命令：

```bash
uv sync --frozen --all-packages --all-groups
uv run ruff check src tests examples packages scripts
uv run ruff format --check src tests examples packages scripts
uv run mypy src/onlyalpha
uv run python scripts/version_sync.py check
uv build --all-packages
```

规则：

- 不以 `# type: ignore` 掩盖设计错误；
- 新 ignore 必须最小化并注明原因；
- 不使用无类型 `dict` 替代明确 DTO；
- 公共方法必须有完整类型；
- 错误码应稳定、可测试；
- 不吞掉异常；
- cleanup 失败应进入诊断；
- 不使用全局可变状态；
- 不依赖未排序集合产生输出；
- 文件写入必须考虑原子性；
- 资源必须有明确关闭路径。

---

## 28. 代码修改原则

### 28.1 优先修改现有权威路径

新增能力前，先查找：

```text
Existing Domain Type
Existing Port
Existing Factory
Existing Registry
Existing Planner
Existing Projection Target
Existing Query
Existing Result DTO
Existing Checkpoint Participant
```

只有在职责确实不同且无法合理扩展时才新增抽象。

### 28.2 禁止双路径

禁止创建：

```text
new_manager_v2
legacy_or_new
paper_special_execution
close_only_processor
market_specific_engine
compatibility_accounting
temporary_trade_store
```

若新实现替代旧实现，应：

1. 迁移正式调用方；
2. 迁移测试；
3. 删除旧正式路径；
4. 保留必要的数据读取兼容；
5. 更新 ADR 和文档；
6. 增加架构门禁防止回流。

### 28.3 Fail Closed

以下场景必须明确失败：

- 未知 Market Product provider/product/version；
- Capability 不支持；
- Reference 缺失；
- 状态无法归因；
- Fill Identity 冲突；
- 配置不兼容；
- Checkpoint Schema 不兼容；
- Projection 前置状态不匹配；
- Broker/Local Authority 冲突达到阻断级；
- Paper 启动历史数据不足；
- Session 边界无法确认；
- Secret 或外部环境未配置。

不得为了“先跑起来”使用隐式默认值放行资金和交易状态。

### 28.4 Runtime taxonomy 架构门禁

以下规则是未来源码迁移和静态门禁的正式输入：

1. 目标 Runtime 只允许 `RESEARCH`、`BACKTEST`、`SIM`、`LIVE`。
2. 不得新增 `PAPER` Runtime 产品或依赖。
3. 不得新增 standalone `SHADOW` Runtime 产品或依赖。
4. 正式 Backtest 必须保持 event-driven + Virtual Broker + full Trading Kernel。
5. Vectorized execution 只属于 Research，不得命名或实现为 canonical Backtest。
6. Strategy 不得按 Runtime type 分支。
7. Trading economics 和 Execution Support 不得按 Runtime type 决定权限。
8. Backtest、Sim、Live 必须共享一个 trading semantic core。
9. SIM 永远不得向 Real Broker 提交订单。
10. RESEARCH 不得为了共享 Runtime 抽象而实例化 Trading Authorities。
11. Runtime 差异主要限于 Clock、MarketData Driver、Broker Adapter 和 Lifecycle Driver。
12. Runtime Type 不是 Execution Permission；不得创建 Runtime-specific duplicate economic authorities。
13. 不得通过 compatibility alias、deprecated spelling 或 wrapper 长期保留 `PAPER` / `SHADOW` public Runtime vocabulary。

---

## 29. 文档规则

代码行为变化时必须同步相关文档。

### README

只描述：

- 产品定位；
- 长期产品模型；
- 当前实现与目标迁移状态；
- 核心工程机制；
- 当前可用能力；
- 快速开始；
- 产品边界；
- 风险声明；
- 文档导航。

不得把 README 重新写成历史实施日志。

### AGENTS

只描述：

- Agent 执行规则；
- 架构不变量；
- 事实来源；
- 验证和交付门禁。

### Architecture

`docs/architecture.md` 描述当前系统如何组织，并明确当前实现与已接受目标架构的差距；不得维护历史阶段、PR 或任务流水账。

### Roadmap

描述：

- 已完成阶段；
- 当前阶段；
- 后续产品优先级；
- 明确非目标。

### ADR

以下变化必须新增或更新 ADR：

- 状态所有权；
- Durable Authority；
- Projection 顺序；
- Recovery Phase；
- Public API；
- Persistence Schema；
- Plugin 边界；
- Market Rule Authority；
- Result Authority；
- 旧路径替换。

### Report

`docs/reports/` 必须带：

- 日期；
- 版本或 Commit；
- 环境；
- 实际执行命令；
- 原始结果；
- 未执行项；
- 限制；
- Artifact 引用。

历史报告不能被当作当前状态自动继承。

---

## 30. 安全与敏感信息

禁止提交或输出：

- Token；
- Password；
- Secret；
- Broker Credential；
- Account Auth；
- 私钥；
- 本地 QMT 用户数据绝对路径；
- 用户主目录绝对路径；
- 未脱敏账户 ID；
- 外部服务完整响应中的敏感字段。

日志、Artifact、Worker Request/Result 和验收 Evidence 必须脱敏。

真实交易相关修改必须默认关闭，并要求显式配置和权限。

---

## 31. Agent 交付格式

完成代码任务时，最终报告至少包含：

```text
1. 修改目标
2. 当前事实和原始问题
3. 修改的正式权威路径
4. 变更文件
5. 不变量如何保持
6. 运行的测试和真实结果
7. 未运行的测试及原因
8. 剩余限制
9. 是否修改 Public API / Schema / ADR
```

不得只说“已完成”或“测试通过”。

测试结果必须区分：

```text
PASS
FAIL
BLOCKED
NOT EXECUTED
```

不得把环境缺失描述为 PASS。

---

## 32. Definition of Done

一项修改只有在满足下列条件时才算完成：

### 业务正确性

- 使用唯一正式入口；
- 未绕过状态权威；
- 未创建第二套正式路径；
- 经济不变量成立；
- 不支持能力 Fail Closed；
- 重复和乱序输入行为明确；
- 失败语义明确。

### 架构正确性

- 依赖方向正确；
- Trading Runtime 仍是 mutable trading authority 唯一所有者；
- Research Runtime 未因结构对称创建 Trading Authorities；
- 目标 Runtime vocabulary 仍只有 `RESEARCH/BACKTEST/SIM/LIVE`；
- Backtest/Sim/Live 未产生 Runtime-specific economic path；
- 插件未穿透 Core 内部；
- Strategy/Factor 未获得越权能力；
- Market Rule 未复制；
- Result 仍来自正式成交权威。

### 恢复正确性

若涉及状态：

- Checkpoint 能力已声明；
- Schema 版本已处理；
- 连续运行和恢复运行等价；
- 事务尾部和 Projection 恢复已覆盖；
- Event 不重复泄漏。

### 测试正确性

- 运行了最窄的正确测试；
- 涉及交易/持久化时运行 Recovery；
- 涉及市场规则时运行 Conformance；
- 没有通过删除测试、skip 或放宽断言完成；
- 测试结果真实记录。

### 工程完整性

- 类型检查通过；
- Lint/Format 通过；
- 示例和配置同步；
- 文档同步；
- 不泄漏敏感信息；
- 无临时文件和调试代码；
- 没有未说明的兼容分支。

---

## 33. 禁止清单

在 OnlyAlpha 中禁止以下做法：

```text
绕过 OnlyEngine 证明产品能力
绕过 Runtime Queue 处理 Broker 回报
Strategy 直接修改订单、仓位或账户
Plugin 持有 Runtime Manager
用 Event Handler 驱动核心状态
用最终 Snapshot 反推逐笔成交
多个 Fill 合并为一个可变 Transaction
Commit 后修改 Transaction
Position、Account、Ledger 分别重算 PnL
多个组件复制市场规则
使用 Float 处理正式账务
未知能力静默降级
Fake SDK PASS 冒充真实产品 PASS
为了测试增加生产 test_mode
通过 skip/xfail 掩盖失败
用 sleep 修复确定性
未排序集合进入结果指纹
不兼容 Schema 静默读取
在 Artifact 中保存 Secret
未运行测试却声称测试通过
根据 prompts/ 创建第二套实现
新增 PAPER 或 standalone SHADOW Runtime 产品依赖
将 PAPER/SHADOW 作为 SIM 长期兼容 alias
把向量化交易近似称为正式 Backtest
Strategy 或 Execution 根据 Runtime type 决定交易语义
为 Backtest/Sim/Live 复制经济 Manager
SIM 向 Real Broker 提交订单
Research 为结构对称实例化 Trading Authorities
```

---

## 34. 最终原则

当实现方案之间存在冲突时，优先选择：

```text
唯一权威
> 多份状态副本

确定性
> 偶然顺序

显式失败
> 隐式降级

不可变事实
> 可变推断

正式产品纵切面
> 单组件演示

Forward Recovery
> 跨 Manager 回滚

公共 Port
> 内部对象穿透

可验证边界
> 功能数量
```

OnlyAlpha 的工程质量不由“存在多少类和模块”衡量，而由以下问题衡量：

```text
同一输入是否产生同一结果？
每个事实是否有唯一来源？
每个状态是否有唯一所有者？
每次失败是否可以解释？
每次恢复是否保持经济等价？
每项产品声明是否有真实验收证据？
```
