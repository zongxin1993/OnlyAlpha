你现在负责 OnlyAlpha 核心仓的任务 3：

# OnlyAlpha Multi-Market Conformance Packs and Product Integration

中文名称：

# OnlyAlpha 多市场一致性验证包与产品化集成

本任务建立在以下两项架构之上：

```text
任务 1：
Unified Market Runtime Rules

任务 2：
Deterministic Multi-Market Scenario Framework
```

本任务的最终目标是：

> 使用正式 OnlyEngine、统一 Market Rule Runtime 和确定性 Scenario Framework，为多个市场建立可执行、可审计、可版本化的 Conformance Packs；通过真实场景结果决定 Market Profile 的能力覆盖和稳定性状态，并提供统一的 CLI、查询模型、Artifact 和示例入口。

本任务不是单纯增加几份 YAML。

本任务不是为每个市场建立独立 Runtime。

本任务不是通过测试标签把 Profile 人工标记为 Stable。

本任务必须严格遵守模块边界、多市场通用性、多运行模式动作一致性和确定性要求。

---

# 一、开始前必须确认当前真实状态

当前主分支已完成：

```text
OnlyMarketConfig
Profile Registry / Resolver
Market Rule Compiler
OnlyMarketRuleEngine
Risk / Broker / Execution 初步接入
SettlementManager
MarginManager 初步实现

Scenario Domain
Scenario Parser
Runtime-neutral Command Planning
Assertion Core
Canonical Input Fingerprint
```

当前明确未完成：

```text
Scenario Action Strategy
Exact-bar Scenario Data Provider
正式 OnlyEngine Scenario Runner
Scenario Artifact
Result Fingerprint
完整 Collector 投影
A 股/T0/Futures/Crypto/跨版本 Engine 场景
Futures HEDGING 正式纵切面
Margin 与 Account 完整事务链
Futures/Crypto 产品 Config 装配
可运行 Conformance Packs
Profile Stable 升级
产品级 CLI / Query
```

不得把 Parser 已完成解释为 Scenario Framework 已经可运行。

不得把 Conformance Pack 身份模型已存在解释为 Conformance Pack 已经通过。

---

# 二、总原则

## 2.1 只有一套正式执行链

所有 Conformance Scenario 必须经过：

```text
Scenario Document
→ Scenario Parser
→ Scenario Planner
→ OnlyEngine
→ OnlyRuntimePlanner
→ OnlyEngineRunAssembler
→ Runtime Factory
→ Runtime.run()
→ Market Data Pipeline
→ Strategy Context
→ Risk
→ Broker
→ ExecutionProcessor
→ Position / Settlement / Margin / Account
→ Collector
→ Standard Result Facts
→ Assertion Engine
→ Scenario Artifact
→ Conformance Evaluation
```

禁止：

```text
直接调用 Broker.on_bar()
直接构造 BrokerTradeUpdate
直接调用 ExecutionProcessor.process()
直接修改 PositionManager
直接修改 AccountManager
直接修改 SettlementManager
直接修改 MarginManager
通过测试 Fixture 手工生成通过事实
```

---

## 2.2 不考虑旧兼容

本任务不为旧测试、旧配置、旧 Pack Schema、旧 CLI 或旧内部接口保留兼容分支。

如果旧类型与新设计重复：

```text
删除旧类型
迁移所有调用方
更新测试
更新文档
```

禁止：

```python
if legacy_pack:
    ...
else:
    ...
```

禁止保留：

```text
deprecated but still active
legacy scenario runner
old conformance schema
old profile stability path
```

历史 ADR 和报告可保留历史记录，但正式代码和正式文档只能描述当前路径。

---

## 2.3 多市场是核心目标

所有新增能力必须同时审查：

```text
中国 A 股
港股
美股
中国期货
海外期货
Crypto Spot
Crypto Perpetual
未来期权及其他衍生品
```

禁止在 Conformance Core 中写入：

```text
T+1
整数股
Long-only
工作日市场
单币种
单 Session
固定日涨跌停
股票式 BUY/SELL 语义
无保证金
无 Funding
无 Borrow
无 Corporate Action
```

市场差异只能来自：

```text
Profile
Instrument Reference
Venue Reference
Calendar
正式 Runtime Capability
```

---

## 2.4 多运行模式动作接口一致

Conformance Scenario 的：

```text
Action
Command
Order Intent
Expectation
Fact Selector
Assertion
```

必须保持运行模式无关。

Backtest、Paper、Live、Shadow 共享相同动作模型。

允许区别：

```text
自动时间推进能力
Data Source
Broker Gateway
外部状态权威
并发和等待模型
失败恢复能力
```

不允许区别：

```text
下单字段含义
Position Effect 含义
订单生命周期语义
Market Decision 字段
Execution Fact 字段
Settlement/Margin/Fee 事实语义
```

当前不能自动执行的模式必须返回明确 Capability Error，不得隐藏降级为 Backtest。

---

# 三、修改前重新审计

编码前必须重新阅读当前主分支。

至少阅读：

```text
AGENTS.md
HANDOFF.md
README.md

docs/architecture.md
docs/runtime.md
docs/backtest.md
docs/market_scenario_framework.md
docs/market_scenario_dsl.md
docs/market_scenario_assertions.md
docs/market_scenario_artifacts.md
docs/market_conformance_suite.md
docs/versioned_market_profile_registry.md
docs/market_profile_capabilities.md
docs/market_profile_configuration.md
docs/results_framework.md
docs/plugin_system.md
docs/roadmap.md

docs/adr/0024-*
docs/adr/0025-*
docs/adr/0026-*
docs/adr/0027-*

docs/reports/deterministic_market_scenario_framework_audit.md
```

完整阅读：

```text
src/onlyalpha/scenario/
src/onlyalpha/market/
src/onlyalpha/config/
src/onlyalpha/engine/
src/onlyalpha/runtime/
src/onlyalpha/strategy/
src/onlyalpha/cluster/
src/onlyalpha/data/
src/onlyalpha/market_data/
src/onlyalpha/order/
src/onlyalpha/risk/
src/onlyalpha/broker/
src/onlyalpha/execution/
src/onlyalpha/position/
src/onlyalpha/settlement/
src/onlyalpha/margin/
src/onlyalpha/account/
src/onlyalpha/result/
src/onlyalpha/artifact/
src/onlyalpha/output/
src/onlyalpha/cli/
tests/
```

重点核实：

```text
Scenario Parser 实际 Schema
Scenario Planner 当前输出
Scenario Assertion 当前 Fact 输入格式
Conformance Pack/Scenario Identity 模型
Capability coverage gate 当前逻辑
Profile STABLE 注册约束
OnlyEngine 正式运行入口
Strategy Factory 如何加载内建 Strategy
Synthetic Data Source 当前 Bar 能力
Reference Config 当前支持哪些 Instrument 类型
Backtest Collector 当前拥有的事实
Artifact Writer 当前 Dataset Schema
CLI 当前命令组织方式
Query DTO 当前是否存在通用 Result Query
Paper/Live/Shadow Factory 当前能力
```

---

# 四、先生成新的审计报告

新增：

```text
docs/reports/multi_market_conformance_product_integration_audit.md
```

必须包含：

## 4.1 任务 2 实际完成度

逐项标记：

```text
已完成
部分完成
未完成
```

覆盖：

```text
Domain
Parser
Planner
Action Strategy
Synthetic Data
Runner
Collector
Assertion
Artifact
Input Fingerprint
Result Fingerprint
Runtime Mode Contract
```

## 4.2 Conformance 当前状态

列出：

```text
Pack Identity
Scenario Identity
Pack Registry
Capability Coverage
Profile Status Gate
Pack Execution
Pack Artifact
Pack Summary
Release Gate
```

分别说明是否真实存在。

## 4.3 产品入口现状

审计：

```text
CLI
Query DTO
Result Query Port
Web compatibility
Examples
Profile inspection
Scenario run
Pack run
Artifact location
Exit codes
```

## 4.4 边界风险

明确列出：

```text
Conformance 是否重算规则
CLI 是否直接访问 Manager
Pack 是否直接调用 Runtime
Profile 是否直接被测试代码修改状态
Collector 是否缺事实
Scenario 是否存在 Backtest 私有接口
Futures/Crypto 是否仍需要特殊旁路
```

---

# 五、任务执行顺序

任务必须按以下顺序执行：

```text
Stage 1：补齐任务 2 正式纵切面
Stage 2：收口 Collector 和 Artifact
Stage 3：完成 Conformance Pack Runtime
Stage 4：建立首批 Pack
Stage 5：建立 Stable Profile Gate
Stage 6：产品 CLI 与 Query
Stage 7：示例和发布门禁
Stage 8：文档和交接
```

不能先做 CLI，再补底层执行链。

不能先把 Profile 标为 Stable，再补 Scenario。

---

# 六、Stage 1：补齐任务 2 正式纵切面

虽然本任务名为任务 3，但当前主分支的任务 2 尚未完成。

本阶段必须先完成以下内容。

## 6.1 Exact Scenario Data Provider

在现有 Data Source SPI 上实现确定性场景数据源。

建议：

```text
OnlyScenarioHistoricalDataSource
OnlyScenarioDataSourceFactory
OnlyScenarioBarProvider
```

优先复用：

```text
OnlyHistoricalDataSource
OnlySyntheticDataSourceFactory
OnlyInMemoryHistoricalDataSource
OnlyHistoricalReplayService
```

不得创建第二套 Replay。

必须支持：

```text
精确 Bar 内容
精确事件顺序
精确 source sequence
多 Instrument
相同 Timestamp 稳定排序
跨 Trading Day
跨 Profile Version
```

---

## 6.2 Scenario Action Strategy

实现正式：

```text
OnlyScenarioActionStrategy
OnlyScenarioActionStrategyConfig
```

必须通过：

```text
OnlyStrategyFactory
OnlyClusterFactory
OnlyClusterContext
ctx.orders
```

运行。

不得直接引用：

```text
OnlyOrderManager
OnlyBrokerGateway
OnlyExecutionProcessor
OnlyPositionManager
OnlyAccountManager
```

支持首批动作：

```text
SUBMIT_ORDER
CANCEL_ORDER
```

动作模型必须支持：

```text
AUTO
OPEN
CLOSE
CLOSE_TODAY
CLOSE_YESTERDAY
```

实际枚举复用正式 Order Intent。

---

## 6.3 Scenario Runner

实现：

```text
OnlyMarketScenarioRunner
OnlyMarketScenarioRunRequest
OnlyMarketScenarioRunResult
```

Runner 只能：

```text
Parser
→ Planner
→ OnlyEngine
→ Result
→ Assertion
→ Artifact
```

Runner 不得创建或持有业务 Manager。

Runner 必须处理：

```text
validate
build
start
run
stop
close
cleanup
failure artifact
```

---

## 6.4 Result Fingerprint

实现确定性结果指纹。

至少包含：

```text
Actions
Orders
Executions
Positions
Accounts
Market Decisions
Settlement
Margin
Fees
Profile Timeline
Compiled Rule Identity
Assertions
确定性 Diagnostics
```

排除：

```text
墙钟时间
绝对路径
PID
hostname
随机 UUID
内存地址
Traceback 中的本地路径
```

---

## 6.5 Runtime Mode Contract

为：

```text
BACKTEST
PAPER
LIVE
SHADOW
```

建立统一 Scenario Command Contract。

当前只要求 BACKTEST 自动执行。

其余模式必须：

```text
使用同一 Action Domain
使用同一 Command DTO
使用同一 Validation
返回明确 Capability Result
```

不得将其转换为 Backtest。

---

# 七、Stage 2：Collector 与 Artifact 收口

Conformance 只能消费正式事实。

必须补齐正式 Collector。

## 7.1 标准事实

至少提供：

```text
Scenario Action
Order
Execution
Position
Account
Market Rule Decision
Settlement
Margin
Fee
Profile Timeline
Compiled Market Rule Identity
Diagnostic
Assertion
```

---

## 7.2 Profile Timeline

记录：

```text
runtime_id
profile_id
profile_version
trading_day
effective_from
effective_to
resolved_rules_fingerprint
reference_fingerprint
override_fingerprint
runtime_mode
sequence
```

必须支持跨版本场景。

---

## 7.3 Compiled Rule Identity

记录：

```text
instrument_id
venue_id
trading_day
profile_id
profile_version
compiled_rules_fingerprint
reference_fingerprint
runtime_mode
schema_version
```

不得输出整个内部 Rule Engine 对象。

---

## 7.4 Collector 边界

Collector 只能：

```text
订阅正式事件
调用正式 Query View
稳定排序
投影 DTO
```

不得：

```text
计算 Settlement
计算 Margin
计算 Fee
判断 T+1
解释 Profile
重放订单
```

---

## 7.5 Artifact

扩展现有 Artifact Writer。

不得建立平行存储系统。

至少输出：

```text
scenario_definition.json
scenario_plan.json
scenario_summary.json
scenario_actions.parquet
scenario_assertions.parquet
profile_timeline.parquet
compiled_market_rules.parquet
market_rule_decisions.parquet
orders.parquet
executions.parquet
positions.parquet
accounts.parquet
settlements.parquet
margin.parquet
fees.parquet
diagnostics.json
manifest.json
```

零行表必须有稳定 Schema。

---

# 八、Conformance Pack 领域设计

## 8.1 Pack 是版本化验证集合

建议正式类型：

```text
OnlyMarketConformancePackId
OnlyMarketConformancePackVersion
OnlyMarketConformancePack
OnlyMarketConformanceScenarioBinding
OnlyMarketConformanceRequirement
OnlyMarketConformanceRunRequest
OnlyMarketConformanceRunResult
OnlyMarketConformanceSummary
```

Pack 包含：

```text
Pack Identity
Profile Family
适用 Profile Version 范围
Scenario Bindings
Capability Requirements
Required / Optional 标记
Pack Schema Version
Pack Source
```

---

## 8.2 Pack 不包含市场实现

Pack 不能定义：

```text
T+1 算法
Fee 算法
Margin Rate 算法
Price Limit 算法
Matching 算法
Settlement 算法
```

Pack 只绑定：

```text
Scenario
Expected Facts
Capability Coverage
```

---

## 8.3 Pack 与 Scenario 的关系

一个 Scenario 可以被多个 Pack 复用。

例如：

```text
Generic lot-size scenario
Generic minimum-notional scenario
Generic partial-fill scenario
```

可以被多个市场 Profile 绑定。

禁止复制同一 Scenario 后只修改名称。

---

## 8.4 Pack Registry

实现：

```text
OnlyMarketConformancePackRegistry
```

职责：

```text
注册 Pack
校验 Pack Identity
校验 Scenario Binding
校验版本范围
校验重复 Requirement
查找 Profile 对应 Pack
稳定排序
```

不负责执行 Scenario。

---

# 九、Conformance Runner

实现：

```text
OnlyMarketConformanceRunner
OnlyMarketConformanceRunRequest
OnlyMarketConformanceRunResult
```

执行链：

```text
Pack
→ Scenario Bindings
→ Scenario Runner
→ Scenario Result
→ Capability Evaluation
→ Pack Summary
→ Pack Artifact
```

不得直接调用 Runtime。

必须复用：

```text
OnlyMarketScenarioRunner
```

---

## 9.1 执行策略

默认按稳定顺序串行运行。

以后可以并行，但必须保证：

```text
结果排序稳定
Artifact 内容稳定
失败汇总稳定
Fingerprint 稳定
```

首期不需要并行。

---

## 9.2 Pack 状态

建议：

```text
PASSED
FAILED
ERROR
INCOMPLETE
SKIPPED
```

含义必须明确：

```text
FAILED：
Scenario 正式运行完成，但断言失败

ERROR：
构建、运行、Artifact 或基础设施错误

INCOMPLETE：
必需 Capability 没有 Scenario 覆盖

SKIPPED：
显式跳过的非必需 Scenario
```

不得把 ERROR 当作 FAILED。

---

# 十、Capability Coverage Gate

当前已有 Capability Set 和初步 coverage gate，需要重新审查并收口。

## 10.1 Coverage 来源

Capability 只能通过：

```text
Pack Requirement
→ Required Scenario
→ Scenario 正式运行 PASSED
```

获得覆盖。

禁止：

```text
测试函数名包含 capability
手工配置 covered=true
只解析 Scenario 即算覆盖
Parser Test 通过即算覆盖
```

---

## 10.2 Capability Requirement

建议类型：

```text
OnlyMarketCapabilityRequirement
```

包含：

```text
capability
required_scenario_ids
minimum_pass_count
notes
```

通常一个 Capability 应至少绑定一个 Required Scenario。

复杂 Capability 可绑定多个 Scenario。

---

## 10.3 Capability Coverage Result

输出：

```text
capability
declared
required
covered
scenario_ids
passed_scenario_ids
failed_scenario_ids
missing_scenario_ids
```

---

# 十一、Profile 状态门禁

## 11.1 状态转换

正式状态：

```text
EXPERIMENTAL
STABLE
DEPRECATED
REMOVED
```

STABLE 必须满足：

```text
存在绑定 Conformance Pack
Pack 正式执行 PASSED
所有 enabled Capability 已覆盖
所有 Required Scenario 已通过
Profile/Reference/Scenario Fingerprint 已记录
核心质量门禁通过
没有未声明的关键限制
```

---

## 11.2 禁止运行时自动修改 Registry

Conformance Runner 不应直接修改全局 Registry 内 Profile 状态。

正确方式：

```text
Conformance Result
→ Stability Evaluation
→ Release Manifest / Registry Definition Update
```

源码内建 Profile 状态的变更必须是明确代码修改并经过测试。

不要在普通运行中把 Profile 自动持久化为 Stable。

---

## 11.3 Stability Evaluator

实现：

```text
OnlyMarketProfileStabilityEvaluator
OnlyMarketProfileStabilityResult
```

它只读取：

```text
Profile Version
Capability Set
Pack Definition
Pack Run Result
Quality Gate Result
```

不执行 Scenario。

---

# 十二、首批 Conformance Packs

## 12.1 CN_A_SHARE_CASH Pack

必须覆盖基础能力：

```text
Session
Long-only
T+1 Asset Availability
Same-day Cash Reuse 语义
Board Lot Buy
Odd-lot Full Liquidation
Tick Size
Main Board Price Limit
ST Price Limit
ChiNext / STAR Price Limit
Suspension
Minimum Commission
Sell-side Stamp Duty
Transfer Fee
Partial Fill
Order Reservation
Settlement Timeline
Profile Version Timeline
```

只覆盖当前正式实现支持的规则。

未实现的真实市场复杂规则必须明确列为限制。

不得为了 Pack 通过虚构支持：

```text
IPO 首日特殊涨跌幅
盘后定价
科创板特殊申报数量
融资融券
退市整理期全部细则
```

---

## 12.2 GENERIC_T0_CASH Pack

覆盖：

```text
T0 Asset Availability
Same-day Buy/Sell
Same-day Cash Reuse
No T+1 hardcoding
Decimal-independent Cash Model
Long-only
```

该 Pack 用于证明核心不硬编码 A 股。

---

## 12.3 GENERIC_MARGIN_FUTURES Pack

覆盖：

```text
SELL OPEN
BUY CLOSE
Long / Short Position
Position Effect
Initial Margin Reserve
Margin Occupy
Partial Fill Margin Adjustment
Cancel Release
Close Release
Contract Multiplier
Integer Contract Quantity
Account Available Balance
```

必须修复正式内核缺口。

禁止用 Scenario 特殊逻辑伪造 Short 和 Margin。

---

## 12.4 GENERIC_24X7_CRYPTO_SPOT Pack

覆盖：

```text
24x7 Session
Weekend Trading
Fractional Quantity
Quantity Step
Minimum Notional
T0 Asset
Maker/Taker Fee 基础语义
No Daily Price Limit
Base/Quote Asset 语义的最小正式模型
```

如果当前 Account/Instrument 还不能正确表达 Base/Quote Asset，应修复正式领域模型，不能在 Scenario 中用股票语义冒充。

---

## 12.5 Cross-Version Pack

覆盖：

```text
同一 Runtime 跨 Profile 有效期
按 Trading Day 重新 Resolve
Compiled Fingerprint 变化
Profile Timeline 正确
旧版本和新版本规则分别生效
```

---

## 12.6 US/HK Experimental Packs

只在底层正式模型足够时新增。

可建立：

```text
US_EQUITY_CASH_EXPERIMENTAL
HK_EQUITY_CASH_EXPERIMENTAL
```

但必须保持：

```text
EXPERIMENTAL
```

除非真实 Scenario、Capability 和门禁全部完成。

不得为了任务数量强行创建空 Pack。

---

# 十三、多市场领域约束

## 13.1 Instrument 类型

正式 Config/Reference 必须支持：

```text
Equity
ETF
Futures
Crypto Spot
```

不能只解析 Equity/ETF。

必须尽量复用正式 Instrument Domain。

禁止为 Scenario 创建独立 Futures/Crypto Instrument。

---

## 13.2 Position

通用 Position 必须支持：

```text
LONG
SHORT
NETTING
HEDGING
OPEN
CLOSE
CLOSE_TODAY
CLOSE_YESTERDAY
```

未支持模式必须明确拒绝。

---

## 13.3 Account

不要假设所有市场都是单现金余额。

本任务至少应明确支持当前 Pack 所需的：

```text
Cash Equity
Margin Futures
Crypto Spot 最小账户语义
```

如果完整多资产钱包不在本任务范围，必须在 Capability 和限制中明确。

---

## 13.4 Session

必须支持：

```text
单 Session
多 Session
午休
跨午夜 Session
24x7
```

通用 Pack Core 不得把 Trading Day 等同于 UTC 日期。

---

# 十四、产品级 CLI

在底层执行链和 Pack 完成后，增加 CLI。

建议命令：

```text
onlyalpha scenario validate <file>
onlyalpha scenario run <file>

onlyalpha conformance list
onlyalpha conformance describe <pack-id>
onlyalpha conformance run <pack-id>
onlyalpha conformance run-profile <profile-id> [--version ...]

onlyalpha market profiles
onlyalpha market profile <profile-id>
onlyalpha market capabilities <profile-id>
```

实际命令风格必须服从现有 CLI 架构。

---

## 14.1 CLI 边界

CLI 只能调用 Application Service：

```text
Scenario Service
Conformance Service
Market Query Service
```

不得直接：

```text
访问 Registry 内部 dict
读取 Runtime Manager
构建 Broker
执行 Assertion
修改 Profile 状态
```

---

## 14.2 Exit Code

至少定义：

```text
0：成功 / Pack Passed
1：Scenario 或 Pack 断言失败
2：配置或校验错误
3：Runtime 构建或执行错误
4：Artifact 错误
5：Capability 不完整
```

与现有 CLI 错误框架保持一致。

---

## 14.3 CLI 输出

默认提供人类可读摘要。

支持结构化输出：

```text
--format json
```

不要让 Web 未来依赖 CLI 文本解析。

---

# 十五、Query DTO 和应用服务

建立稳定的只读查询边界。

建议：

```text
OnlyMarketProfileQueryService
OnlyMarketConformanceQueryService
OnlyScenarioQueryService
```

DTO：

```text
OnlyMarketProfileSummary
OnlyMarketProfileDetail
OnlyMarketCapabilityCoverageView
OnlyConformancePackSummary
OnlyConformancePackDetail
OnlyConformanceRunSummary
OnlyScenarioRunSummary
OnlyScenarioAssertionView
OnlyArtifactManifestView
```

---

## 15.1 Query 边界

Query Service 可以读取：

```text
Registry
Pack Registry
Scenario Registry
Run Result Repository
Artifact Manifest
```

不得：

```text
执行规则
运行 Scenario
修改状态
访问 Runtime Manager
```

Command 与 Query 分开。

---

## 15.2 Web 兼容性

DTO 必须：

```text
稳定
可 JSON 序列化
使用字符串 Decimal
使用 ISO-8601 UTC
不暴露内部对象
不暴露 Path 对象
不暴露 Enum 实现细节
```

本任务不实现 Web Server，但 DTO 应可直接供未来 Web 使用。

---

# 十六、Scenario 和 Pack Repository

建立只读或受控的定义仓库。

建议：

```text
OnlyScenarioDefinitionRepository
OnlyConformancePackDefinitionRepository
```

首期可以读取工程内置资源。

职责：

```text
按 ID 查询
按 Version 查询
列出定义
验证唯一性
返回不可变 Domain
```

不得混入：

```text
运行结果
Profile Registry 状态
Runtime 对象
```

定义与结果仓库分开。

---

# 十七、Examples

本任务应提供最小但真实的示例。

如果仅修改核心仓：

```text
examples/scenarios/
examples/conformance/
```

至少包括：

```text
cn_a_share_t1.yaml
generic_t0_cash.yaml
generic_margin_futures.yaml
generic_crypto_spot.yaml
cross_profile_version.yaml
```

示例必须可以由正式 CLI 或 Application Service 执行。

不得提供无法运行的伪配置。

如果 OnlyAlpha-examples 是独立仓且本任务不修改该仓，则在 HANDOFF 中明确列为后续工作，不要宣称已完成三仓示例。

---

# 十八、Release Gate

建立：

```text
OnlyMarketConformanceReleaseGate
OnlyMarketConformanceReleaseGateResult
```

检查：

```text
Pack PASSED
Capability Complete
Required Scenario Complete
Determinism Passed
Artifact Complete
Schema Stable
No Boundary Violation
Core Test Passed
Ruff Passed
Mypy Passed
```

---

## 18.1 Release Gate 不运行底层规则

它只聚合已有结果。

执行由：

```text
Conformance Runner
Quality Gate Runner
```

完成。

---

## 18.2 三仓门禁

如果当前只连接核心仓，只执行核心仓真实门禁。

不要伪造：

```text
OnlyAlpha-plugins passed
OnlyAlpha-examples passed
```

只有实际访问并执行后才可记录通过。

---

# 十九、确定性要求

相同：

```text
Profile
Profile Version
Pack Version
Scenario Definitions
Reference
Market Data
Actions
Runtime Mode
Plugin Versions
```

重复运行必须得到相同：

```text
Scenario Input Fingerprint
Scenario Result Fingerprint
Pack Fingerprint
Capability Coverage
Assertions
Artifact Dataset Hash
Stable IDs
Row Ordering
```

---

## 19.1 Pack Fingerprint

至少包含：

```text
Pack ID
Pack Version
Profile ID
Profile Version
Scenario IDs / Versions
Scenario Input Fingerprints
Scenario Result Fingerprints
Capability Requirements
Pack Schema Version
```

排除：

```text
运行目录
墙钟
机器信息
随机 ID
```

---

# 二十、架构边界测试

增加自动化依赖门禁。

至少保证：

```text
conformance 不 import broker concrete
conformance 不 import risk concrete
conformance 不 import runtime private
conformance 不 import position/account manager
conformance 不 import profile rule implementation

cli 不 import broker/runtime manager
query 不 import execution mutation service
scenario assertion 不 import market rule engine
collector 不 import conformance assertion
market profile 不 import scenario/conformance
```

允许：

```text
Conformance Runner → Scenario Runner public port
CLI → Application Service
Query → Registry / Repository public port
```

---

# 二十一、删除旧设计

主动搜索并处理：

```text
旧 Conformance DTO
仅身份但命名成可运行 Pack 的类型
旧 Scenario 未使用字段
旧 Legacy CLI
旧 simulation 命名
测试专用 production helper
直接 manager mutation helper
直接 broker fill helper
旧 Profile Stable 手工 gate
```

如果与新设计重复，应删除。

不保留兼容适配层。

---

# 二十二、错误模型

建立稳定错误码。

至少包括：

```text
CONFORMANCE_PACK_NOT_FOUND
CONFORMANCE_PACK_VERSION_NOT_FOUND
CONFORMANCE_PACK_INVALID
CONFORMANCE_SCENARIO_MISSING
CONFORMANCE_SCENARIO_FAILED
CONFORMANCE_SCENARIO_ERROR
CONFORMANCE_CAPABILITY_INCOMPLETE
CONFORMANCE_DETERMINISM_FAILED
CONFORMANCE_ARTIFACT_FAILED
CONFORMANCE_RELEASE_GATE_FAILED
PROFILE_NOT_ELIGIBLE_FOR_STABLE
PROFILE_CONFORMANCE_PACK_MISSING
QUERY_RESOURCE_NOT_FOUND
CLI_INVALID_ARGUMENT
```

不能只抛裸 `ValueError`。

---

# 二十三、测试要求

## 23.1 Pack Domain

测试：

```text
Identity
Version
Scenario Binding
Capability Requirement
稳定排序
不可变性
重复检测
```

## 23.2 Pack Registry

测试：

```text
注册
查询
重复
版本范围
缺失 Scenario
```

## 23.3 Conformance Runner

测试：

```text
全通过
断言失败
Runtime Error
Artifact Error
Incomplete Capability
稳定执行顺序
```

## 23.4 Stability Evaluator

测试：

```text
Experimental 保持
满足条件可 Stable
缺 Scenario 不可 Stable
缺 Capability 不可 Stable
Pack Error 不可 Stable
```

## 23.5 CLI

测试：

```text
list
describe
validate
run
JSON output
exit code
错误信息
```

## 23.6 Query

测试：

```text
Profile Summary
Pack Detail
Capability Coverage
Run Summary
JSON normalization
```

## 23.7 多市场 Pack

正式运行：

```text
CN_A_SHARE_CASH
GENERIC_T0_CASH
GENERIC_MARGIN_FUTURES
GENERIC_24X7_CRYPTO_SPOT
Cross-Version
```

## 23.8 Determinism

每个 Pack 至少重复运行两次。

## 23.9 全量门禁

真实执行：

```text
pytest
ruff check
mypy
ruff format --check
git diff --check
```

失败必须如实记录。

---

# 二十四、本任务明确不做

除非是完成首批 Pack 必需，不实现：

```text
完整 US Equity 生产支持
完整 HK Equity 生产支持
交易所级 Futures 全规则
Perpetual Funding
Liquidation
Borrow
Portfolio Margin
Options
Level-2 Order Book
Corporate Action 全体系
Web Server
远程 Pack Registry
在线 Tushare Reference 自动同步
自动修改源码 Profile Status
```

可提供接口和 Experimental 定义，但不能宣称正式支持。

---

# 二十五、文档更新

## 25.1 新增 ADR

新增：

```text
docs/adr/0028-multi-market-conformance-and-profile-stability.md
```

说明：

```text
Pack 与 Scenario 边界
Pack 与 Profile 边界
Capability Coverage
Stable Gate
Conformance Runner 只复用 Scenario Runner
CLI / Query 分层
多市场和多 Runtime Mode 原则
无旧兼容策略
```

---

## 25.2 新增或重写文档

至少包括：

```text
docs/market_conformance_suite.md
docs/market_conformance_pack_schema.md
docs/market_profile_stability.md
docs/market_capability_coverage.md
docs/market_conformance_cli.md
docs/market_conformance_query.md
docs/market_conformance_artifacts.md
```

---

## 25.3 更新工程说明

更新：

```text
README.md
docs/architecture.md
docs/runtime.md
docs/backtest.md
docs/market_scenario_framework.md
docs/results_framework.md
docs/roadmap.md
docs/plugin_system.md
AGENTS.md
```

必须说明：

```text
Scenario Framework 当前真实能力
Conformance Packs 当前真实能力
哪些 Profile 是 Experimental
哪些 Profile 是 Stable
哪些 Runtime Mode 可自动执行
哪些市场仍未正式支持
```

---

## 25.4 更新 HANDOFF.md

把当前任务改为：

```text
Multi-Market Conformance Packs and Product Integration
```

记录：

```text
本轮完成
本轮删除
正式通过的 Packs
Profile 状态
真实运行模式支持
Collector / Artifact 状态
CLI / Query 状态
真实测试命令和结果
明确未完成
下一步顺序
```

不得把未运行 Pack 写成通过。

不得把未执行的三仓门禁写成通过。

---

# 二十六、完成标准

以下全部满足才算完成：

```text
任务 2 的 Action Strategy 已完成
Exact Scenario Data Provider 已完成
正式 OnlyEngine Scenario Runner 已完成
Scenario Artifact 已完成
Scenario Result Fingerprint 已完成
Collector 标准事实已收口
五个正式 Engine Scenario 已通过

Conformance Pack Domain 已完成
Pack Registry 已完成
Conformance Runner 已完成
Capability Coverage Gate 已完成
Profile Stability Evaluator 已完成
Conformance Artifact 已完成
Pack Fingerprint 已完成
Release Gate 已完成

CN_A_SHARE_CASH Pack 已正式执行
GENERIC_T0_CASH Pack 已正式执行
GENERIC_MARGIN_FUTURES Pack 已正式执行
GENERIC_24X7_CRYPTO_SPOT Pack 已正式执行
Cross-Version Pack 已正式执行

Pack 只通过 Scenario Runner
Scenario 只通过正式 OnlyEngine
Assertion 只读标准事实
Collector 不重算规则
CLI 不访问 Manager
Query 不执行 Command
Profile 不依赖 Scenario/Conformance

多运行模式 Action/Command 契约一致
PAPER/LIVE/SHADOW 不隐藏降级为 BACKTEST
不保留旧兼容路径

CLI 已完成
Query DTO / Service 已完成
可运行示例已完成
README 已更新
Architecture 已更新
ADR 0028 已新增
AGENTS.md 已更新
HANDOFF.md 已更新

pytest 真实通过
ruff check 真实通过
mypy 真实通过
git diff --check 真实通过
format check 结果真实记录
```

---

# 二十七、最终报告格式

完成后输出中文报告。

## 1. 修改前审计

说明任务 2 和 Conformance 当前真实状态。

## 2. 删除与迁移

列出删除的旧接口、旧命名和旧测试路径。

## 3. 正式 Scenario 纵切面

展示：

```text
Scenario
→ OnlyEngine
→ Runtime
→ Result
→ Assertion
→ Artifact
```

## 4. Conformance 架构

展示：

```text
Pack
→ Scenario Runner
→ Capability Coverage
→ Stability Evaluation
→ Release Gate
```

## 5. 模块边界

逐项说明：

```text
Pack Domain
Registry
Runner
Coverage
Stability
CLI
Query
Artifact
```

以及各模块不负责什么。

## 6. 多市场结果

报告：

```text
A 股
T0 Cash
Futures
Crypto Spot
Cross-Version
```

## 7. 多运行模式一致性

说明共享接口和当前能力差异。

## 8. Profile 状态

列出：

```text
Profile
Version
Status
Pack
Coverage
限制
```

## 9. CLI 和 Query

列出命令、DTO 和错误码。

## 10. 确定性

报告 Scenario 和 Pack 重复运行结果。

## 11. Artifact

列出数据集、Schema、Hash 和 Manifest。

## 12. 质量门禁

列出真实执行命令与结果。

## 13. 文档更新

列出工程说明、ADR 和交接文档修改。

## 14. 明确未完成

不得把 US/HK、Perpetual、Tushare、Web Server、Plugins/Examples 三仓门禁等未执行内容写成完成。

---

# 二十八、最终架构原则

最终实现必须满足：

> OnlyAlpha 的 Conformance Pack 是正式 Runtime 行为的版本化验证集合，不是市场规则实现。

> Pack 不直接运行 Runtime，只通过 Scenario Runner。

> Scenario Runner 不直接操作交易组件，只通过 OnlyEngine。

> Capability 只有在正式 Scenario 运行并通过后才算覆盖。

> Profile 只有在 Pack、Capability、确定性、Artifact 和质量门禁全部满足后才有资格标记为 Stable。

> Backtest、Paper、Live、Shadow 使用相同的 Action、Command、Order Intent、Fact 和 Assertion 语义。

> 多市场差异来自 Profile、Reference 和正式 Runtime Capability，不来自 Conformance Core 中的市场分支。

> 不为旧接口、旧 Schema、旧测试或旧 CLI 保留兼容路径；重复概念直接删除并迁移。

> CLI 是应用层入口，Query 是只读边界，Collector 是事实投影，Artifact 是结果封存；任何一层都不得越权执行市场业务规则。
