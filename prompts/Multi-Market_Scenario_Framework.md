你现在负责 OnlyAlpha 核心仓的任务 2：

# OnlyAlpha Deterministic Multi-Market Scenario Framework

中文名称：

# OnlyAlpha 确定性多市场场景验证框架

本任务基于已经完成的 Unified Market Runtime Rules 架构继续开发。

任务目标是：

> 建立一套使用人工 Reference、人工 Market Data 和确定性 Action 驱动正式 OnlyEngine 的场景验证框架，用于验证 Backtest、Paper、Live、Shadow 等运行模式共享的市场规则、订单语义、成交语义、持仓语义、结算语义、保证金语义、费用语义和标准事实。

本任务不是创建第二套交易引擎。

本任务不是创建“仿真市场规则”。

本任务不是通过测试专用捷径直接操作 Runtime 内部 Manager。

所有场景必须尽可能通过正式产品入口和正式组件链执行。

---

# 一、长期架构原则

整个任务期间必须时刻遵守以下原则。

## 1. OnlyAlpha 是多市场项目

任何新增类型、字段、枚举、接口和测试都必须从以下市场审查：

```text
中国 A 股
港股
美股
中国期货
海外期货
Crypto Spot
Crypto Perpetual
未来的期权和其他衍生品
```

禁止把以下假设写入通用 Scenario Core：

```text
所有市场都是整数股
所有市场都有交易日
所有市场按自然日切换
所有市场都有午休
所有市场是 T+1
所有市场都使用 Cash Account
所有市场只有 LONG
所有市场都是单币种
所有订单都是 BUY/SELL 两种含义
所有成交都能用 Bar 完整表达
所有市场都有涨跌停
所有市场都没有隔夜 Session
所有市场都能用同一种 Close 语义
```

A 股只是首个正式验证市场，不是核心模型模板。

---

## 2. 多运行模式接口动作一致

Backtest、Paper、Live、Shadow 应尽量共享相同的：

```text
Strategy Action
Order Intent
Runtime Command
Market Rule Decision
Broker Update
Execution Application
Position Update
Settlement Instruction
Margin Instruction
Fee Instruction
Result Fact
Query DTO
```

允许不同 Runtime Mode 存在的差异只有：

```text
Clock 驱动方式
Market Data 来源
Broker Gateway 类型
外部状态权威
等待和并发模型
失败恢复模式
是否允许历史时间推进
```

禁止在 Scenario Action 中定义 Backtest 专用下单语义。

错误：

```python
scenario_runtime.force_fill(...)
scenario_runtime.set_position(...)
scenario_runtime.advance_backtest_bar_and_buy(...)
```

正确方向：

```python
strategy_context.orders.submit(...)
runtime_command_port.submit(...)
broker_gateway 接收正式订单
```

同一个 Scenario Action 应能够映射成正式 Runtime Command，而不是直接调用 Backtest 私有实现。

---

## 3. 严格执行模块边界

任务中不得因为测试方便破坏任务 1 建立的边界。

正式依赖链必须保持：

```text
OnlyMarketConfig
→ Profile Registry
→ Profile Resolver
→ Market Rule Compiler
→ OnlyMarketRuleEngine
→ Restricted Runtime Ports
→ Risk / Broker / Execution
→ Position / Settlement / Margin / Account
→ Collector / Result / Artifact
```

Scenario Framework 位于外层：

```text
Scenario Document
→ Scenario Parser
→ Scenario Planner
→ 正式 Runtime Config
→ OnlyEngine
→ 正式 Runtime
→ Standard Facts
→ Assertion Engine
```

Scenario Framework 不属于：

```text
Risk
Broker
Execution
Position
Settlement
Margin
Account
Market Rule Engine
```

---

## 4. 不允许复制业务规则

Scenario Parser、Runner、Assertion Engine 不得重新实现：

```text
T+1
T+0
涨跌停
Tick Size
Board Lot
Odd Lot
最低佣金
印花税
做空
开平仓
保证金
Session
Minimum Notional
Maker/Taker
Settlement Date
```

这些规则只能由正式 Market Rule Runtime 产生。

Scenario 只描述：

```text
输入
动作
预期事实
```

Assertion Engine 只比较：

```text
Expected Facts
vs
Actual Facts
```

不能根据 Profile 自己算一遍正确答案。

---

# 二、开始修改前必须重新审计工程

不得直接根据旧提示词开始编码。

首先重新阅读当前主分支。

至少完整阅读：

```text
AGENTS.md
HANDOFF.md
README.md
docs/architecture.md
docs/runtime.md
docs/backtest.md
docs/order.md
docs/risk.md
docs/virtual_broker.md
docs/execution_processor.md
docs/position.md
docs/position_modes.md
docs/account.md
docs/settlement_model.md
docs/margin_model.md
docs/market_simulation_framework.md
docs/versioned_market_profile_registry.md
docs/market_profile_configuration.md
docs/market_scenario_dsl.md
docs/market_conformance_suite.md
docs/results_framework.md
docs/artifact.md
docs/plugin_system.md
docs/plugin_testing.md
docs/adr/0024-*
docs/adr/0025-*
docs/adr/0026-*
```

阅读源码目录：

```text
src/onlyalpha/config/
src/onlyalpha/engine/
src/onlyalpha/runtime/
src/onlyalpha/cluster/
src/onlyalpha/strategy/
src/onlyalpha/order/
src/onlyalpha/risk/
src/onlyalpha/broker/
src/onlyalpha/execution/
src/onlyalpha/position/
src/onlyalpha/account/
src/onlyalpha/settlement/
src/onlyalpha/margin/
src/onlyalpha/market/
src/onlyalpha/data/
src/onlyalpha/market_data/
src/onlyalpha/result/
src/onlyalpha/output/
src/onlyalpha/artifact/
src/onlyalpha/plugin/
tests/
```

重点确认：

```text
OnlyEngine 正式构建和运行入口
OnlyRuntimePlanner / Session / Factory 的边界
OnlyBacktestRuntime.run() 和 process_bar() 的区别
Paper/Live/Shadow 当前 Factory 和 Runtime 实现状态
Strategy Context 的正式下单接口
Strategy 生命周期和 Bar 回调顺序
Synthetic Data Source 当前已有能力
Reference Data 当前如何进入 Runtime
OnlyMarketRuleEngine 当前对 Trading Day 的解析方式
当前 Broker Match-Time 输入
ExecutionProcessor 当前 Trade Instruction 应用流程
SettlementManager 当前正式状态接口
MarginManager 当前正式状态接口
Collector 当前如何获得标准事实
OnlyBacktestFacts 和 Artifact Writer 当前支持的表
现有 Conformance 类型是否只是身份模型
现有 Scenario 文档是否仍含过时 simulation/legacy 语义
```

---

# 三、先输出修改前审计报告

新增：

```text
docs/reports/deterministic_market_scenario_framework_audit.md
```

报告必须包含：

## 3.1 当前正式执行链

绘制实际代码链：

```text
Config
→ Engine
→ Planner
→ Assembler
→ Runtime Factory
→ Runtime
→ Strategy
→ Risk
→ Broker
→ ExecutionProcessor
→ Managers
→ Collector
→ Result
```

不能只复制文档，要以源码为准。

## 3.2 可复用能力

列出可以直接复用的：

```text
Synthetic Data Source
In-Memory Historical Source
Reference Source
Trading Calendar
Strategy Factory
Cluster Factory
Runtime Factory
Result Models
Artifact Writer
Market Profile Registry
Market Rule Engine
Conformance Identity Models
```

## 3.3 缺失能力

明确指出：

```text
Scenario Domain
Scenario Parser
Scenario Planner
Action Driver
Runtime-neutral Action Port
Scenario Runner
Assertion Engine
Scenario Artifact
Scenario Fingerprint
Profile Timeline Projection
Compiled Rule Identity Projection
Market Decision Projection
Settlement/Margin/Fee Projection
```

## 3.4 错误或重复设计

如果发现现有文档、类或测试仍使用：

```text
simulation market
legacy market
direct manager mutation
test-only broker fill
backtest-only action
profile fields in assertion
```

必须列出并给出处置方案。

## 3.5 任务 1 未收口内容

重点核实：

```text
Futures HEDGING 双向 Position
Margin 与 Account 事务链
Collector 全量事实
Fee Accumulator 正式投影
Profile Timeline
Compiled Identity
Market Decisions
```

Scenario Framework 不得掩盖这些问题。

---

# 四、任务 2 的正确模块划分

建议新增独立包：

```text
src/onlyalpha/scenario/
```

不要把整个 Scenario Framework 放入：

```text
market/
runtime/backtest/
tests/helpers/
```

推荐子模块：

```text
scenario/
    __init__.py
    identifiers.py
    enums.py
    models.py
    document.py
    parser.py
    validation.py
    planning.py
    actions.py
    strategy.py
    runner.py
    assertions.py
    facts.py
    fingerprint.py
    artifact.py
    errors.py
    ports.py
```

具体文件名可根据现有工程风格调整，但职责必须分开。

---

# 五、Scenario Domain

建立稳定、不可变、可版本化的领域模型。

建议核心类型：

```text
OnlyMarketScenarioId
OnlyMarketScenarioVersion
OnlyMarketScenario
OnlyScenarioMetadata
OnlyScenarioRuntimeSpec
OnlyScenarioMarketSpec
OnlyScenarioReferenceSpec
OnlyScenarioInstrumentSpec
OnlyScenarioCalendarSpec
OnlyScenarioDataSpec
OnlyScenarioAction
OnlyScenarioExpectation
OnlyScenarioAssertion
```

所有核心类型继续使用：

```text
Only*
```

前缀。

---

## 5.1 Scenario 不是市场规则容器

Scenario 可以指定：

```yaml
market:
  profile: CN_A_SHARE_CASH
  version: "2025.1"
```

Scenario 不得指定：

```yaml
t_plus_days: 1
short_selling: false
daily_price_limit: "0.10"
stamp_duty: "0.001"
```

除非字段属于正式允许的 Market Override Policy。

Scenario Parser 必须复用正式 `OnlyMarketConfig` 和正式 Config Parser，不要建立不同的 Profile 配置语义。

---

## 5.2 Scenario Runtime Spec

Scenario 应显式声明目标运行模式：

```yaml
runtime:
  mode: BACKTEST
```

模型必须支持：

```text
BACKTEST
PAPER
LIVE
SHADOW
```

但任务 2 首期实际执行可以只正式支持：

```text
BACKTEST
```

对于尚未支持 Scenario 自动执行的其他模式，应：

```text
解析成功
规划时明确返回 UNSUPPORTED_RUNTIME_MODE_FOR_SCENARIO
```

不得静默降级成 Backtest。

设计时必须保证未来 Paper/Live/Shadow 可以复用：

```text
Action
Expectation
Fact
Assertion
```

而不是重写 Scenario Domain。

---

## 5.3 Scenario 时间模型

时间必须使用：

```text
UTC Timestamp
Trading Day
Calendar ID
Venue Time Zone
```

明确区分：

```text
event time
initialization time
action trigger time
trading day
calendar date
session phase
```

禁止用本地无时区字符串作为核心时间。

DSL 可以接受带时区 ISO-8601，但 Parser 必须转换为现有正式时间类型。

---

## 5.4 多市场数量和价格

所有价格、数量、金额、费率必须沿用现有：

```text
OnlyPrice
OnlyQuantity
OnlyMoney
Decimal
```

禁止 Scenario Domain 使用 float。

DSL 中所有可能失真的 Decimal 必须使用字符串：

```yaml
price: "10.25"
quantity: "100"
minimum_notional: "5.00"
```

Quantity 不得假设整数。

---

## 5.5 Instrument Reference

Scenario Instrument 只能提供 Reference Data。

例如：

```text
instrument_id
symbol
venue_id
asset_class
currency
price_precision
quantity_precision
tick_size
quantity_step
lot_size
minimum_notional
contract_multiplier
board
ST status
trading status
calendar_id
metadata
```

必须尽量复用正式 `OnlyInstrument` 和正式 Reference 模型。

不得创建与 `OnlyInstrument` 内容重复但互不兼容的 Scenario Instrument 实体。

建议：

```text
Scenario Document DTO
→ 正式 OnlyInstrument
```

---

# 六、Scenario DSL Parser

实现：

```text
OnlyMarketScenarioParser
OnlyMarketScenarioDocument
OnlyMarketScenarioValidationResult
OnlyScenarioValidationIssue
```

Parser 职责：

```text
读取 YAML/JSON
Schema Version 校验
字段类型校验
Decimal 校验
时间校验
ID 唯一性校验
引用完整性校验
Action 顺序校验
Expectation 引用校验
转换为不可变 Domain
```

Parser 不负责：

```text
解析 Market Profile 规则内容
判断订单是否合法
判断是否成交
计算费用
计算结算日
计算保证金
推导 Position Effect
```

---

## 6.1 DSL Schema Version

Scenario 文件必须包含：

```yaml
schema_version: "1"
```

还应包含：

```yaml
scenario:
  id: CN_T1_BASIC
  version: "1.0"
```

Schema Version 和 Scenario Version 是不同概念。

---

## 6.2 未知字段策略

默认严格拒绝未知字段。

可以保留：

```yaml
extensions:
```

作为受控扩展点。

禁止 Parser 默默忽略拼写错误。

---

## 6.3 示例结构

建议：

```yaml
schema_version: "1"

scenario:
  id: CN_T1_BASIC
  version: "1.0"
  description: A 股买入后同日不可卖，下一交易日可卖

runtime:
  mode: BACKTEST
  start_time: "2026-01-05T01:30:00Z"
  end_time: "2026-01-06T07:00:00Z"
  base_currency: CNY

market:
  profile: CN_A_SHARE_CASH
  version: "2025.1"

reference:
  calendars:
    - ...

  instruments:
    - instrument_id: TEST.600000.XSHG
      venue_id: XSHG
      asset_class: EQUITY
      currency: CNY
      price_precision: 2
      quantity_precision: 0
      board: SSE_MAIN
      st_status: false
      trading_status: ACTIVE
      tick_size: "0.01"
      lot_size: "100"
      calendar_id: XSHG

data:
  bars:
    - ...

actions:
  - action_id: BUY_1
    trigger:
      type: ON_BAR
      sequence: 1
    command:
      type: SUBMIT_ORDER
      instrument_id: TEST.600000.XSHG
      side: BUY
      order_type: MARKET
      quantity: "100"

expectations:
  - assertion_id: BUY_FILLED
    fact: ORDER
    selector:
      action_id: BUY_1
    field: status
    operator: EQUALS
    expected: FILLED
```

实际字段必须服从当前正式类型，不能照抄示例而制造重复概念。

---

# 七、Synthetic Reference Provider

实现正式的场景 Reference Provider。

建议类型：

```text
OnlyScenarioReferenceProvider
OnlySyntheticReferenceDataSource
```

优先复用当前：

```text
OnlyInMemoryReferenceDataSource
OnlyInstrument
OnlyTradingCalendar
```

Scenario Reference Provider 只负责：

```text
把 Scenario Reference DTO 转换成正式 Reference Domain
向 Runtime Factory 或 Data Source SPI 提供 Reference
提供稳定 Reference Fingerprint
```

不得：

```text
编译市场规则
决定 Profile
执行 Risk
产生 Settlement
```

---

## 7.1 Reference Fingerprint

至少包含：

```text
Instrument Identity
Venue
Calendar
Asset Class
Currency
Tick
Quantity Step
Lot
Minimum Notional
Multiplier
Board
ST
Trading Status
Metadata 中参与规则的字段
Schema Version
```

排除无业务意义的：

```text
对象地址
临时路径
加载时间
字典插入顺序
```

---

# 八、Synthetic Market Data

优先扩展和复用已有 Synthetic Data Source，不得建立第二套 Data Source SPI。

场景数据至少支持：

```text
Bar
```

领域和接口应为未来保留：

```text
Quote
Trade Tick
Order Book
Trading Status Update
Reference Update
Corporate Action
Funding Rate
```

但本任务不要求全部实现。

---

## 8.1 数据进入正式 Pipeline

所有 Bar 必须经过：

```text
Data Source
→ Historical Replay / Inbound Queue
→ Market Data Processor
→ Market Data Pipeline
→ Snapshot
→ Strategy Dispatch
→ Broker
```

禁止 Scenario Runner 直接调用：

```python
broker.on_bar(bar)
strategy.on_bar(bar)
runtime._services.market_cache...
```

除非现有正式 `OnlyBacktestRuntime.run()` 内部本来如此组织。

---

## 8.2 数据顺序

Parser 或 Planner 必须验证：

```text
ts_event 单调性
ts_init >= ts_event
source sequence 唯一且单调
instrument 已定义
bar type 已订阅
trading day 与 calendar 可解释
```

是否允许同一 Timestamp 多标的事件，必须采用现有 Replay 的稳定排序语义。

不要凭 Scenario 文件顺序偶然决定结果。

---

# 九、Deterministic Action Model

实现运行模式无关的 Action Domain。

建议类型：

```text
OnlyScenarioAction
OnlyScenarioActionId
OnlyScenarioTrigger
OnlyScenarioCommand
OnlyScenarioActionResult
```

支持的首批 Command：

```text
SUBMIT_ORDER
CANCEL_ORDER
```

可以根据现有正式接口补充：

```text
REPLACE_ORDER
STOP_RUNTIME
```

但不要过度扩张。

---

## 9.1 Action 不直接调用 Manager

Action 必须通过正式 Port 映射成：

```text
Strategy Context Order API
或 Runtime Command Port
```

禁止 Action 直接依赖：

```text
OnlyOrderManager
OnlyPositionManager
OnlyAccountManager
OnlySettlementManager
OnlyMarginManager
OnlyVirtualBrokerGateway
OnlyExecutionProcessor
```

---

## 9.2 Position Effect

Action 必须能够表达多市场订单意图。

首批至少考虑：

```text
AUTO
OPEN
CLOSE
CLOSE_TODAY
CLOSE_YESTERDAY
```

如果现有正式 Order Intent 已有对应类型，必须复用。

不要在 Scenario 中创造不同的字符串语义。

对于 Cash Equity：

```text
AUTO
```

可以由正式规则决定。

对于 Futures：

场景应能显式指定 OPEN/CLOSE。

---

## 9.3 Trigger

首期推荐支持最小、确定性的 Trigger：

```text
ON_BAR_SEQUENCE
ON_TIMESTAMP
ON_TRADING_DAY_START
AFTER_ACTION
AFTER_ORDER_STATUS
```

不要用自然语言。

Trigger 必须在正式事件边界执行。

明确订单提交相对于：

```text
当前 Bar Strategy Dispatch
Broker Acceptance
当前 Bar Matching
下一 Bar Matching
```

的顺序。

顺序必须来自当前 Runtime 的正式语义，并写入文档和测试。

---

# 十、Scenario Action Strategy

实现：

```text
OnlyScenarioActionStrategy
OnlyScenarioActionStrategyConfig
```

它必须是正式 Strategy。

通过正式：

```text
OnlyStrategyFactory
OnlyClusterFactory
OnlyClusterContext
```

创建和运行。

职责：

```text
接收 Runtime 回调
检查当前确定性 Trigger
通过正式 Context 提交或取消订单
记录 Action Dispatch Fact
```

不负责：

```text
指标
信号计算
市场规则判断
撮合
断言
直接状态读取后修改行为
```

可以读取订单状态以实现显式 `AFTER_ORDER_STATUS` Trigger，但必须通过正式 Query View。

---

## 10.1 Strategy 与 Scenario Core 解耦

Scenario Domain 不应依赖 Strategy 实现细节。

建议：

```text
Scenario Planner
→ Action Schedule
→ ScenarioActionStrategyConfig
```

Strategy 只消费编译后的 Action Schedule。

---

# 十一、Scenario Planner

实现：

```text
OnlyMarketScenarioPlanner
OnlyMarketScenarioPlan
OnlyScenarioPlanValidationResult
```

职责：

```text
将 Scenario Domain 转换为正式 Runtime/Cluster/DataSource/Broker 配置
构建临时但正式的运行计划
选择 Runtime Factory
选择 Synthetic Data Source
选择 Virtual Broker
装配 Scenario Action Strategy
建立 Result Output 位置
```

Planner 不执行 Runtime。

---

## 11.1 不写临时产品配置旁路

优先直接构建正式 Config Domain。

如果必须生成 YAML 文件，也必须通过正式 Config Loader 再加载一次，以验证产品配置路径。

至少应有一条集成测试证明：

```text
Scenario
→ 正式 OnlyClusterRunConfig / OnlyRuntimeAssemblyPlan
→ OnlyRuntimePlanner
```

---

## 11.2 运行模式一致性

Planner 应基于 Runtime Mode 选择正式 Factory。

不能：

```python
if scenario:
    always_create_backtest_runtime_directly()
```

应使用：

```text
OnlyRuntimeFactoryRegistry
OnlyEngineRunAssembler
```

对于当前不支持的 Mode 返回明确 Validation Issue。

---

# 十二、Scenario Runner

实现：

```text
OnlyMarketScenarioRunner
OnlyMarketScenarioRunRequest
OnlyMarketScenarioRunResult
```

Runner 职责：

```text
解析或接收已解析 Scenario
调用 Planner
调用正式 Engine / Assembler
执行 Runtime
收集正式 Result
运行 Assertion Engine
写 Scenario Artifact
返回统一 Run Result
```

Runner 不拥有：

```text
Risk
Broker
Position
Account
Settlement
Margin
Fee
```

---

## 12.1 必须经过正式 Engine

正式场景集成测试必须经过：

```text
OnlyEngine
→ OnlyRuntimePlanner
→ OnlyEngineRunAssembler
→ Runtime Factory
→ Runtime.run()
```

禁止只通过：

```text
new OnlyBacktestRuntime(...)
process_bar(...)
```

来宣称 Scenario Framework 已完成。

允许保留组件测试，但不能代替产品纵切面。

---

## 12.2 生命周期

Runner 必须正确处理：

```text
build
validate
start
run
stop
close
failure cleanup
artifact finalization
```

失败时不得泄漏：

```text
Clock
Event Bus
Data Source
Broker Gateway
Runtime Session
临时文件
```

---

# 十三、Assertion Engine

实现：

```text
OnlyScenarioAssertionEngine
OnlyScenarioAssertionResult
OnlyScenarioAssertionFailure
OnlyScenarioAssertionSummary
```

Assertion Engine 输入：

```text
Scenario Expectations
Standard Result Facts / Query Ports
```

输出：

```text
PASSED
FAILED
ERROR
SKIPPED
```

---

## 13.1 Assertion 只读事实

Assertion Engine 不得直接访问 Runtime 私有 Manager。

优先读取：

```text
OnlyBacktestResult
Standard Facts
Result Query Port
Artifact Dataset
```

如果 Collector 当前没有所需事实，应修复正式 Collector，而不是让 Assertion 读取：

```python
runtime._services.position_manager
```

---

## 13.2 首批 Fact Types

至少支持：

```text
ORDER
EXECUTION
POSITION
ACCOUNT
MARKET_RULE_DECISION
SETTLEMENT
MARGIN
FEE
ACTION
DIAGNOSTIC
PROFILE_TIMELINE
COMPILED_RULE
```

---

## 13.3 Operators

首批支持：

```text
EQUALS
NOT_EQUALS
GREATER_THAN
GREATER_THAN_OR_EQUAL
LESS_THAN
LESS_THAN_OR_EQUAL
CONTAINS
EXISTS
NOT_EXISTS
COUNT_EQUALS
SEQUENCE_EQUALS
DECIMAL_EQUALS
```

Decimal 比较必须精确。

不要默认浮点容差。

如需要容差，显式支持：

```text
DECIMAL_APPROX
```

并要求 Scenario 提供 tolerance。

---

## 13.4 Selector

Selector 必须使用稳定业务 ID：

```text
action_id
order_id
client_order_id
trade_id
instrument_id
account_id
cluster_id
trading_day
rule_code
stage
```

禁止依赖表中偶然的行号。

---

## 13.5 不允许规则重算

例如验证 A 股 T+1：

正确：

```text
断言同日卖单产生 MARKET_RULE_DECISION 拒绝
断言 reason_code
断言 available_quantity
断言下一交易日 Settlement Record
```

错误：

```text
Assertion Engine 根据 Profile 算 T+1 后再检查
```

---

# 十四、Collector 和标准事实收口

当前任务 1 尚未完全收口 Collector。

任务 2 必须完成 Scenario 所需的正式事实投影。

至少确保 Collector 能输出：

```text
Profile Resolution Timeline
Compiled Market Rule Identity
Market Rule Decisions
Settlement Records
Margin Records
Fee Breakdown
Scenario Action Records
Orders
Executions
Positions
Accounts
Diagnostics
```

---

## 14.1 Collector 边界

Collector 只：

```text
订阅正式事件
读取正式 Query View
投影标准事实
稳定排序
生成 Schema
```

Collector 不：

```text
重算 Fee
重算 Margin
推导 T+1
解释 Profile
判断订单是否合法
```

---

## 14.2 Profile Timeline

跨 Profile 版本有效期的场景必须能够输出：

```text
profile_id
profile_version
effective_from
effective_to
trading_day
resolved_at
compiled_rules_fingerprint
reference_fingerprint
override_fingerprint
runtime_mode
```

如果同一版本跨多个交易日产生相同 Compiled Rules，也要明确采用：

```text
逐日记录
或区间压缩
```

选择一种确定性语义并写入文档。

---

## 14.3 Market Decision

必须输出稳定字段：

```text
decision_id
sequence
runtime_id
account_id
cluster_id
instrument_id
order_id
trade_id
stage
rule_code
accepted
reason_code
message
trading_day
profile_id
profile_version
compiled_rules_fingerprint
details
schema_version
```

---

## 14.4 Settlement、Margin 和 Fee

这些事实必须来自正式 Manager 或正式 Instruction 应用结果。

不得从 Trade 表离线推算。

---

# 十五、Scenario Artifact

不要创建与现有 Artifact Writer 平行的独立存储体系。

应扩展现有 Result/Artifact 系统。

建议输出：

```text
scenario_definition.json
scenario_plan.json
scenario_summary.json
scenario_assertions.parquet
scenario_actions.parquet
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

文件名以现有工程命名为准。

零行表必须有稳定 Schema。

---

## 15.1 Scenario Summary

至少包含：

```text
scenario_id
scenario_version
schema_version
runtime_mode
status
assertion_total
assertion_passed
assertion_failed
assertion_error
input_fingerprint
result_fingerprint
market_profile_id
resolved_versions
started_at
completed_at
```

确定性 Fingerprint 中不得包含墙钟时间。

---

# 十六、Fingerprint

实现：

```text
OnlyScenarioInputFingerprint
OnlyScenarioResultFingerprint
```

或符合现有命名风格的类型。

---

## 16.1 输入 Fingerprint

至少包含：

```text
Scenario Domain
Schema Version
Scenario Version
Runtime Mode
Market Config
Resolved Profile Version
Profile Content Fingerprint
Compiled Rule Fingerprints
Reference Data
Calendar
Synthetic Market Data
Action Schedule
Expectations
相关插件身份和版本
```

---

## 16.2 结果 Fingerprint

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
Assertions
Diagnostics 中确定性的业务字段
```

排除：

```text
wall clock
run directory
PID
hostname
absolute path
memory address
随机 UUID
异常 traceback 文本中的路径
```

---

## 16.3 稳定 ID

Scenario Runner 不得使用随机 UUID 作为业务事实主键。

应使用稳定组合：

```text
scenario_id
action_id
sequence
runtime_id
order sequence
trade sequence
```

如果正式 Runtime 当前使用随机 ID，需要审计是否影响确定性，并采用现有可注入 ID Generator 解决。

---

# 十七、任务 1 剩余缺口的处理规则

任务 2 场景可能暴露任务 1 未完成能力。

处理原则：

## 17.1 必须修复正式组件

例如 Futures 场景失败是因为：

```text
Position Manager 不支持 HEDGING 双向仓
Margin 没有进入 Account
```

应修改：

```text
Position
Margin
Account
ExecutionProcessor
```

不能在 Scenario 中伪造结果。

## 17.2 不得扩大到全部衍生品

任务 2 只完成支持首批验收场景所需的最小正式能力：

```text
SELL OPEN
BUY CLOSE
Short Position
Initial Margin
Margin Occupy
Margin Release
```

以下仍可不做：

```text
Close Today Fee
Exchange-specific close priority
Maintenance Margin Call
Forced Liquidation
Funding
Options Greeks
Portfolio Margin
Cross Margin
Isolated Margin
```

但未实现时必须显式标记。

---

# 十八、首批正式场景

任务 2 必须实现下列 Scenario 文件，并通过正式 Engine。

建议目录：

```text
tests/scenarios/
```

或者：

```text
scenarios/validation/
```

以工程当前测试资源规范为准。

---

## 18.1 CN_A_SHARE_CASH：T+1

场景：

```text
T 日 BUY 100
→ 成交
→ total_quantity = 100
→ available_quantity = 0

T 日 SELL 100
→ Pre-Trade 拒绝
→ reason_code = ASSET_NOT_AVAILABLE_T1

下一 Trading Day
→ Settlement Record
→ available_quantity = 100

SELL 100
→ 成交
```

同时断言：

```text
整手规则
手续费 Breakdown
Profile Timeline
Compiled Rule Identity
Market Decision
```

---

## 18.2 GENERIC_T0_CASH

场景：

```text
BUY
→ 成交
→ 当日 available_quantity 增加

SELL
→ 同日成交

卖出现金
→ 当日 trade-available
```

必须证明 Core 没有 T+1 硬编码。

---

## 18.3 GENERIC_MARGIN_FUTURES

场景：

```text
SELL OPEN
→ Short Position 增加
→ Margin Reserved
→ Fill 后 Margin Occupied

BUY CLOSE
→ Short Position 减少
→ Margin Released
```

必须检查：

```text
Position Side
Position Effect
Margin Record
Account Available Balance
Execution Instruction
```

不允许用负 LONG 数量代替 Short Position，除非当前 NETTING 领域模型明确如此定义并有文档支持。

---

## 18.4 GENERIC_24X7_CRYPTO_SPOT

场景：

```text
周末 Timestamp
小数 Quantity
Quantity Step
Minimum Notional
T0
无日涨跌停
```

至少包括：

```text
一笔合法小数订单
一笔 Quantity Step 非法订单
一笔 Minimum Notional 不足订单
```

---

## 18.5 跨 Profile 版本场景

新增一个最小版本切换场景。

目的不是模拟现实历史规则，而是验证：

```text
同一 Runtime 跨 Trading Day
Profile Resolver 按有效期切换
Compiled Fingerprint 变化
Profile Timeline 正确记录
```

不得在 Runtime 启动时固定一个版本覆盖整个区间。

---

# 十九、多运行模式契约测试

虽然任务 2 首批 Runner 只需要正式执行 Backtest，但必须增加 Runtime Mode Contract Tests。

定义统一契约：

```text
Scenario Action
→ Runtime-neutral Command
→ Order Intent
```

验证：

```text
Backtest Runtime Factory
Paper Runtime Factory
Live Runtime Factory
Shadow Runtime Factory
```

对相同 Config 和 Action Domain 的：

```text
解析
规划
能力校验
错误模型
命令 DTO
```

保持一致。

---

## 19.1 允许的差异

例如：

```text
BACKTEST 支持历史自动推进
PAPER/LIVE 不支持 Scenario 自动推进
```

应返回：

```text
SCENARIO_RUNTIME_MODE_NOT_EXECUTABLE
```

而不是修改 Action 语义。

---

## 19.2 Strategy Context 一致性

Scenario Action Strategy 使用的下单接口必须是正式 Strategy 在各 Runtime Mode 中共同拥有的接口。

禁止引用：

```text
OnlyBacktestContext
OnlyBacktestOrderService
```

若当前 Strategy Context 存在 Mode 分裂，需要先抽象正式公共 Port。

---

# 二十、错误模型

建立稳定错误代码。

至少覆盖：

```text
SCENARIO_SCHEMA_UNSUPPORTED
SCENARIO_FIELD_UNKNOWN
SCENARIO_DECIMAL_INVALID
SCENARIO_TIMESTAMP_INVALID
SCENARIO_REFERENCE_MISSING
SCENARIO_ACTION_DUPLICATE
SCENARIO_TRIGGER_INVALID
SCENARIO_EXPECTATION_INVALID
SCENARIO_RUNTIME_MODE_UNSUPPORTED
SCENARIO_PLAN_FAILED
SCENARIO_RUNTIME_BUILD_FAILED
SCENARIO_RUNTIME_EXECUTION_FAILED
SCENARIO_ASSERTION_FAILED
SCENARIO_ARTIFACT_FAILED
```

不要只抛裸 `ValueError`。

内部错误可以包装，但对外必须有稳定错误码。

---

# 二十一、测试层级

必须分层测试。

## 21.1 Domain Tests

验证：

```text
ID
Decimal
Time
不可变性
稳定排序
Schema Version
Action Identity
Expectation Identity
```

## 21.2 Parser Tests

验证：

```text
合法 YAML
未知字段
缺失引用
重复 ID
错误 Decimal
错误 Timestamp
错误 Runtime Mode
```

## 21.3 Planner Tests

验证：

```text
Scenario → 正式 Runtime Config
Synthetic Source
Virtual Broker
Scenario Strategy
Market Config
Reference
```

## 21.4 Action Strategy Tests

验证：

```text
Trigger 顺序
同一 Action 只执行一次
Order Command 映射
Cancel Command 映射
```

## 21.5 Assertion Tests

验证：

```text
Selector
Operator
Decimal
Count
Sequence
Missing Fact
Stable Failure Message
```

## 21.6 Runner Integration Tests

必须使用正式 Engine。

## 21.7 Determinism Tests

同一 Scenario 连续执行至少两次，比较：

```text
Input Fingerprint
Result Fingerprint
标准事实内容
稳定 ID
排序
```

## 21.8 Architecture Boundary Tests

至少检查：

```text
scenario 不 import runtime 私有实现
scenario 不 import manager concrete classes
assertion 不 import market profile rules
parser 不 import broker
synthetic data 不 import risk
collector 不 import scenario assertion
```

允许 Runner/Planner 依赖正式公共 Engine、Config 和 Factory Port。

---

# 二十二、禁止事项

本任务明确禁止：

```text
创建第二套 Market Rule Engine
创建 Scenario 专用 Risk
创建 Scenario 专用 Broker
直接制造 BrokerTradeUpdate
直接写 PositionManager
直接写 AccountManager
直接写 SettlementManager
直接写 MarginManager
通过 Assertion Engine 推导预期业务规则
用随机睡眠等待订单状态
用真实墙钟控制 Backtest Scenario
用 float 保存价格或金额
通过 Profile ID 在 Scenario Core 分支
为 A 股修改通用 Quantity 类型
为 Futures 使用测试专用订单类型
把所有 Scenario 代码塞入 tests/helpers.py
```

---

# 二十三、本任务明确不做

不实现：

```text
完整 Conformance Packs
Profile STABLE 状态升级
US Equity Pack
HK Equity Pack
完整 Futures Exchange Pack
Perpetual Funding
Liquidation
Borrow
Options
Tick/Order Book 全量撮合
Tushare Profile 自动加载
Web Query API
产品级 Scenario CLI
OnlyAlpha-examples 全部示例
Plugins 仓修改
Examples 仓修改
```

可以实现最小内部测试入口，但不要把它宣称为产品 CLI。

---

# 二十四、文档更新

任务完成后必须更新工程文档。

## 24.1 新增 ADR

新增：

```text
docs/adr/0027-deterministic-multi-market-scenario-framework.md
```

ADR 至少说明：

```text
Scenario 是外层验证设施
Market Rules 仍只有一套
Scenario 必须经过正式 Engine
Assertion 不重算规则
Action 运行模式无关
Synthetic 只描述输入
多市场和多 Runtime Mode 的边界
```

## 24.2 新增框架说明

新增或重写：

```text
docs/market_scenario_framework.md
docs/market_scenario_dsl.md
docs/market_scenario_assertions.md
docs/market_scenario_artifacts.md
```

## 24.3 更新现有文档

至少更新：

```text
README.md
docs/architecture.md
docs/runtime.md
docs/backtest.md
docs/market_conformance_suite.md
docs/results_framework.md
docs/roadmap.md
AGENTS.md
```

删除或修正文档中仍然存在的：

```text
Market Simulation Config
Legacy Market Path
Scenario 直接运行 Broker
Assertion 重算市场规则
```

## 24.4 更新 HANDOFF.md

将当前任务改为：

```text
Deterministic Multi-Market Scenario Framework
```

记录：

```text
本轮完成
明确未完成
真实测试命令
真实测试结果
已知限制
下一步建议
```

不得把未执行的门禁写成通过。

---

# 二十五、完成标准

只有以下全部满足，任务 2 才算完成。

```text
Scenario Domain 已实现
Scenario YAML/JSON Parser 已实现
Scenario Validation 已实现
Synthetic Reference Provider 已实现
Synthetic Market Data 已接入正式 Pipeline
Runtime-neutral Action Domain 已实现
Scenario Action Strategy 已实现
Scenario Planner 已实现
Scenario Runner 已实现
Assertion Engine 已实现
Scenario Artifact 已实现
Input/Result Fingerprint 已实现

Scenario Runner 经过正式：
    OnlyEngine
    OnlyRuntimePlanner
    OnlyEngineRunAssembler
    Runtime Factory
    Runtime.run()

Assertion 只读取正式标准事实
Collector 已补齐 Scenario 所需正式投影

CN_A_SHARE_CASH 场景通过
GENERIC_T0_CASH 场景通过
GENERIC_MARGIN_FUTURES 场景通过
GENERIC_24X7_CRYPTO_SPOT 场景通过
跨 Profile 版本场景通过

重复运行确定性通过
稳定 ID 通过
稳定排序通过
零行 Schema 通过
模块依赖边界测试通过
Runtime Mode Contract Tests 通过

核心全量 pytest 通过
Ruff check 通过
Mypy 通过
git diff --check 通过
格式检查结果真实记录

README 已更新
Architecture 已更新
Scenario 文档已更新
ADR 0027 已新增
AGENTS.md 已更新
HANDOFF.md 已更新
```

---

# 二十六、最终报告格式

完成后输出中文报告。

## 1. 修改前审计

说明当前已有能力和缺失能力。

## 2. Scenario 架构

展示：

```text
Scenario Document
→ Parser
→ Planner
→ OnlyEngine
→ Runtime
→ Standard Facts
→ Assertion
→ Artifact
```

## 3. 模块边界

逐项说明：

```text
Scenario Domain
Parser
Reference Provider
Synthetic Data
Action Strategy
Planner
Runner
Collector
Assertion
Artifact
```

并说明每个模块“不负责什么”。

## 4. 多市场审查

分别说明：

```text
A 股
T0 Cash
Futures
Crypto Spot
```

证明没有通用层硬编码。

## 5. 多运行模式审查

说明：

```text
Backtest
Paper
Live
Shadow
```

共享了哪些接口，哪些能力暂未执行。

## 6. 正式执行链

提供实际调用链和关键文件。

## 7. 场景结果

逐个报告五个首批场景。

## 8. Collector 与 Artifact

列出新增事实、Schema 和文件。

## 9. 确定性

报告重复运行比较结果。

## 10. 质量门禁

列出真实执行命令与结果。

## 11. 文档更新

列出修改的工程说明和交接文档。

## 12. 明确未完成

不得把 Conformance Packs、US/HK、Tushare、Web/CLI 或其他运行模式自动执行写成已完成。

---

# 二十七、最终原则

最终实现必须满足：

> Scenario Framework 是正式 OnlyEngine 的外层验证设施，不是第二套 Runtime。

> Synthetic 只代表输入数据由人工构造，不代表市场规则是仿真的。

> 市场规则、订单语义、成交语义、持仓语义、结算语义、保证金语义和费用语义在 Backtest、Paper、Live、Shadow 中保持统一。

> Scenario Action 使用运行模式无关的正式命令和 Strategy Context。

> Assertion Engine 只验证正式事实，不重新实现市场制度。

> 为通过场景发现的交易内核缺口，必须修复正式组件，不能在 Scenario 中建立旁路。

> 所有新增设计必须同时审查多市场扩展性、多运行模式一致性、确定性、审计性和未来 Web Query 兼容性。
