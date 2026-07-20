你现在负责 OnlyAlpha Workspace 的一个不可拆分、多阶段组合任务：

# OnlyAlpha Futures Closure, Full Scenario Examples and Architecture Documentation

中文名称：

# OnlyAlpha 期货事务链闭环、全场景示例与全局架构文档

本任务包含三个必须依次完成的阶段：

```text
阶段一：
期货事务链收口与多市场一致性门禁闭环

阶段二：
在 OnlyAlpha-examples 中实现并运行当前全部正式 Scenario 示例

阶段三：
更新交接文档，并基于全局源码生成完整组件思维导图和 UML
```

这三个阶段全部属于本任务的强制范围。

不得只完成阶段一后停止。

不得只增加示例而不真实运行。

不得用 TODO、占位文件、伪造结果或“后续任务”代替阶段三的思维导图和 UML。

遇到内核问题时，应修改问题所属的正式组件，然后继续后续阶段，不得在 Scenario、Examples 或文档层建立旁路。

只有三个阶段全部完成并通过相应门禁，才能宣称本组合任务完成。

如果存在真正无法控制的外部阻塞，必须如实报告任务未完成，但不得把部分结果描述为完成。

---

# 一、工作仓库

应从 OnlyAlpha Workspace 根目录开始工作。

必须审查并根据需要修改：

```text
OnlyAlpha/
OnlyAlpha-examples/
OnlyAlpha-plugins/
OnlyAlpha-workspace/
```

其中：

```text
OnlyAlpha
    核心领域模型、Engine、Runtime、交易链、Scenario、Conformance、
    Result、Artifact、CLI 和 Query

OnlyAlpha-examples
    使用核心公共接口的可运行示例

OnlyAlpha-plugins
    外部 DataSource、Broker 或其他插件实现

OnlyAlpha-workspace
    三仓联合开发、uv workspace、锁文件、子模块版本和全局架构文档
```

不得只审查 Core 而忽略 Examples 和 Plugins 的接口兼容性。

---

# 二、绝对架构原则

## 2.1 不保留旧兼容

本任务不考虑旧接口、旧配置、旧示例或旧测试的兼容性。

如果旧接口与当前正式接口表达相同业务语义：

```text
删除旧接口
迁移调用方
更新测试
更新示例
更新文档
```

禁止：

```python
if legacy:
    ...
else:
    ...
```

禁止增加 Deprecated 适配层继续维持重复语义。

历史 ADR 和审计报告可以保留历史记录，但正式源码和当前工程说明只能描述当前路径。

---

## 2.2 严格执行组件边界

正式交易链保持为：

```text
Strategy / Runtime Command
→ Order Intent
→ Risk
→ Broker Gateway
→ Broker Update
→ ExecutionProcessor
→ Position / Settlement / Margin / Account / Ledger
→ Collector
→ Result / Artifact
```

市场规则链保持为：

```text
OnlyMarketConfig
→ Market Profile Registry
→ Profile Resolver
→ Market Rule Compiler
→ OnlyMarketRuleEngine
→ Restricted Runtime Ports
```

Scenario 链保持为：

```text
Scenario
→ Parser
→ Planner
→ Exact DataSource
→ Action Strategy
→ OnlyEngine
→ Runtime
→ Standard Facts
→ Assertion
→ Artifact
```

Conformance 链保持为：

```text
Conformance Pack
→ Public Scenario Runner
→ Capability Coverage
→ Stability Evaluator
→ Release Gate
```

任何阶段都不得绕过这些链路。

---

## 2.3 多市场目标

所有修改必须同时考虑：

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

禁止在通用组件中写死：

```text
T+1
Long-only
整数股
工作日交易
单币种
单 Session
无保证金
无 Short
固定日涨跌停
股票式 BUY/SELL 语义
```

市场差异只能来自：

```text
Market Profile
Instrument Reference
Venue Reference
Trading Calendar
Runtime Capability
```

---

## 2.4 多运行模式一致性

Backtest、Paper、Live 和 Shadow 应共享相同的：

```text
Strategy Context
Order Intent
Order Command
Position Effect
Risk Decision
Broker Update
Execution Fact
Position Fact
Settlement Fact
Margin Fact
Fee Fact
Scenario Action
Scenario Assertion
Query DTO
```

允许的差异仅包括：

```text
Clock 驱动
Market Data 来源
Broker Gateway
外部状态权威
并发与等待模式
恢复策略
是否允许自动历史推进
```

不得建立 Backtest 专用订单语义或 Example 专用交易语义。

PAPER、LIVE、SHADOW 当前不能自动执行 Scenario 时，必须返回明确 Capability Error，不能隐藏降级为 BACKTEST。

---

# 三、开始前的全局审计

编码前必须重新阅读四个仓库当前主分支。

至少阅读 Core：

```text
AGENTS.md
HANDOFF.md
README.md
pyproject.toml

docs/architecture.md
docs/runtime.md
docs/order.md
docs/risk.md
docs/virtual_broker.md
docs/execution_processor.md
docs/position.md
docs/position_modes.md
docs/account.md
docs/settlement_model.md
docs/margin_model.md
docs/results_framework.md
docs/market_scenario_framework.md
docs/market_scenario_dsl.md
docs/market_scenario_assertions.md
docs/market_scenario_artifacts.md
docs/market_conformance_suite.md
docs/market_conformance_pack_schema.md
docs/market_profile_stability.md
docs/market_capability_coverage.md
docs/market_conformance_cli.md
docs/market_conformance_query.md
docs/market_conformance_artifacts.md

docs/adr/0026-*
docs/adr/0027-*
docs/adr/0028-*
```

完整审计 Core 生产目录：

```text
src/onlyalpha/application/
src/onlyalpha/cli/
src/onlyalpha/config/
src/onlyalpha/engine/
src/onlyalpha/runtime/
src/onlyalpha/clock/
src/onlyalpha/event/
src/onlyalpha/data/
src/onlyalpha/market_data/
src/onlyalpha/cluster/
src/onlyalpha/indicator/
src/onlyalpha/factor/
src/onlyalpha/strategy/
src/onlyalpha/order/
src/onlyalpha/risk/
src/onlyalpha/market/
src/onlyalpha/broker/
src/onlyalpha/execution/
src/onlyalpha/position/
src/onlyalpha/allocation/
src/onlyalpha/ledger/
src/onlyalpha/account/
src/onlyalpha/settlement/
src/onlyalpha/margin/
src/onlyalpha/result/
src/onlyalpha/artifact/
src/onlyalpha/scenario/
```

同时审计：

```text
OnlyAlpha-examples/
OnlyAlpha-plugins/
OnlyAlpha-workspace/pyproject.toml
OnlyAlpha-workspace/uv.lock
OnlyAlpha-workspace/.gitmodules
```

必须先输出新的审计报告：

```text
OnlyAlpha/docs/reports/
futures_closure_examples_and_architecture_audit.md
```

审计报告至少包含：

```text
当前 Futures Order → Position → Margin → Account 链
Risk Reservation 生命周期
ExecutionProcessor 的事务应用顺序
Settlement/Margin/Fee 标准事实来源
当前五个 Pack 的运行状态
当前所有正式 Scenario 定义清单
OnlyAlpha-examples 当前示例清单
Core 与 Examples 的版本约束
Plugins 对 Core 公共接口的依赖
全局组件清单
需要删除的旧接口和重复实现
```

---

# 四、阶段一：期货事务链与一致性门禁闭环

## 4.1 正式期货纵切面

必须通过正式 OnlyEngine 完成：

```text
SELL OPEN
→ Order Intent
→ Pre-Trade Risk
→ Margin Reservation
→ Broker Acceptance
→ Broker Fill
→ ExecutionProcessor
→ SHORT Position
→ Margin Occupied
→ Account Updated
→ Risk Reservation Consumed
→ Standard Facts
```

以及：

```text
BUY CLOSE
→ Order Intent
→ Pre-Trade Risk
→ Broker Fill
→ ExecutionProcessor
→ SHORT Position Reduced
→ Margin Released
→ Account Updated
→ Risk Reservation Closed
→ Standard Facts
```

不得：

```text
使用负 LONG 数量模拟 Short
由 Scenario 直接写 Position
由 Broker 直接写 Runtime Account
由 Assertion 推导 Margin
运行结束后遗留 active risk reservation
```

---

## 4.2 Position 边界

Position Manager 只维护正式持仓状态。

必须支持当前期货场景需要的：

```text
LONG
SHORT
OPEN
CLOSE
HEDGING 或明确的正式 NETTING 语义
```

至少正确处理：

```text
SELL OPEN → SHORT 增加
BUY CLOSE → SHORT 减少
部分成交
多次开仓
部分平仓
全部平仓
```

Position Manager 不决定：

```text
保证金率
是否允许开空
能否平仓
费用
市场规则
```

这些来自正式 Rule Engine 和 Instruction。

---

## 4.3 Margin 生命周期

Margin Manager 必须正式维护：

```text
RESERVED
OCCUPIED
RELEASED
```

至少覆盖：

```text
提交订单时预占
订单拒绝时释放
Broker 拒绝时释放
部分成交时按成交量占用
未成交部分继续预占
撤单时释放剩余预占
平仓时释放占用
重复 Broker Update 不得重复占用或释放
```

运行结束后必须满足：

```text
无无主 Margin Reservation
无负 Margin
无重复占用
无未解释的 active reservation
```

Margin Rule 只产生 Instruction。

Margin Manager 只应用 Instruction 和维护状态。

---

## 4.4 Risk Reservation 生命周期

审计并修复：

```text
Order Risk Reservation
Cash Reservation
Position Reservation
Margin Reservation
```

订单的所有终态必须收口 Reservation：

```text
FILLED
CANCELED
REJECTED
EXPIRED
FAILED
```

部分成交必须准确处理：

```text
已成交部分消耗
未成交部分继续保留
撤销后剩余释放
```

增加正式 Invariant：

```text
Runtime 正常结束时，不允许存在未解释的 active reservation
```

如果策略故意留下活动订单，应由明确的 Runtime Close Policy 处理，不得静默泄漏。

---

## 4.5 Account 事务链

Account Manager 负责正式账户状态。

至少正确维护：

```text
cash balance
available balance
reserved margin
occupied margin
released margin
realized PnL
fees
equity
```

ExecutionProcessor 必须以确定顺序应用：

```text
1. Validate / Deduplicate Broker Update
2. Update Order
3. Apply Position Instruction
4. Apply Settlement Instruction
5. Apply Margin Instruction
6. Apply Fee Instruction
7. Apply Account Cash Flow
8. Apply Strategy Ledger
9. Consume / Release Risk Reservation
10. Check Invariants
11. Publish Standard Facts
```

需要审计失败时的一致性策略。

不得出现：

```text
Position 已更新但 Margin 未更新
Margin 已占用但 Account 未更新
Account 已扣费但 Execution 未封存
Reservation 泄漏
重复 Update 重复记账
```

---

## 4.6 Settlement、Margin、Fee 标准事实

Collector 必须从正式事件、审计记录或 Query View 投影：

```text
Settlement Fact
Margin Fact
Fee Fact
```

至少包含：

### Settlement

```text
settlement_id
instrument_id
account_id
trade_id
trading_day
booked_quantity
available_quantity_delta
trade_available_cash_delta
withdrawable_cash_delta
legal_settlement_date
status
sequence
```

### Margin

```text
margin_record_id
account_id
instrument_id
order_id
trade_id
operation
reserved_delta
occupied_delta
released_delta
currency
amount
sequence
```

### Fee

```text
fee_record_id
account_id
instrument_id
order_id
trade_id
fee_type
accrued
charged
currency
sequence
```

Collector 不得根据 Execution 离线重算市场规则。

---

## 4.7 正式 Futures Scenario

必须新增并真实通过：

```text
GENERIC_MARGIN_FUTURES_ENGINE@1.0
```

至少验证：

```text
SELL OPEN
SHORT Position
Margin Reserved
Margin Occupied
Account Available Balance
BUY CLOSE
Margin Released
SHORT 清零
Risk Reservation 清零
```

还必须增加边界 Scenario：

```text
部分成交后撤单
订单拒绝后 Reservation 释放
重复 Broker Update 幂等
平仓数量超过 Short 时拒绝
```

所有 Scenario 必须经过：

```text
Scenario Runner
→ OnlyEngine
→ Runtime
→ Standard Facts
→ Assertion
→ Artifact
```

---

# 五、Cross-Version 与五 Pack 门禁

## 5.1 Cross-Version Scenario

必须建立并通过：

```text
CROSS_PROFILE_VERSION_ENGINE@1.0
```

验证：

```text
同一个 Runtime 跨越 Profile 生效边界
按 Trading Day 重新 Resolve Profile
Compiled Rules Fingerprint 发生变化
Profile Timeline 正确记录
旧版本规则在旧交易日生效
新版本规则在新交易日生效
```

不得在 Runtime 启动时固定一个版本覆盖全部运行区间。

Cross-Version 测试数据应通过 Registry 的正式公共扩展点注册。

不得由 Scenario 直接修改 Rule Engine 私有状态。

---

## 5.2 五个正式 Conformance Packs

必须全部真实执行：

```text
CN_A_SHARE_CASH
GENERIC_T0_CASH
GENERIC_MARGIN_FUTURES
GENERIC_24X7_CRYPTO_SPOT
CROSS_VERSION
```

每个 Pack 必须：

```text
绑定版本化 Scenario
通过公开 Scenario Runner
生成 Capability Coverage
生成 Pack Summary
生成 Pack Fingerprint
生成 Pack Artifact
重复运行结果一致
```

不得只注册 Pack 而不执行。

不得用 Scenario 名称推断 Coverage。

---

## 5.3 Capability Coverage

Coverage 只能来自：

```text
Required Scenario
→ Formal OnlyEngine Run
→ Scenario PASSED
→ Capability Covered
```

禁止：

```text
手工 covered=true
测试名称推导
Parser 成功即算覆盖
跳过 Scenario 后仍算覆盖
```

输出至少包括：

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

## 5.4 Profile Stability Gate

Profile 只有满足以下全部条件才可升级 STABLE：

```text
对应 Pack PASSED
全部 enabled Capability 已覆盖
Required Scenario 全部 PASSED
Scenario Determinism PASSED
Pack Determinism PASSED
Artifact Complete
Schema Stable
Core Quality Gate PASSED
Examples Gate PASSED
Plugins Compatibility Gate PASSED
```

Stability Evaluator 不能直接修改 Registry。

状态升级必须通过明确源码变更。

对于本任务覆盖的内建 Profile：

```text
如果满足条件，明确升级为 STABLE
如果不满足条件，必须继续补齐缺失能力和 Scenario
不得以“保持 Experimental”代替本阶段完成
```

不得虚构 Capability，亦不得通过删除真实已支持 Capability 来规避门禁。

---

## 5.5 Conformance 产品入口

完成正式：

```text
onlyalpha conformance list
onlyalpha conformance describe PACK_ID
onlyalpha conformance run PACK_ID
onlyalpha conformance run-profile PROFILE_ID
```

支持：

```text
--version
--user-data
--format json
```

CLI 只调用 Application Service。

不得直接访问：

```text
Runtime Manager
Broker
Position Manager
Margin Manager
内部 Registry dict
```

完成：

```text
Conformance Definition Repository
Conformance Run Result Repository
Conformance Query DTO
Profile Stability Query DTO
Artifact Manifest Query DTO
```

Query 必须只读。

---

# 六、阶段二：OnlyAlpha-examples 全场景示例

只有阶段一全部通过后，才能开始阶段二。

## 6.1 版本和 Workspace 对齐

更新 `OnlyAlpha-examples` 的依赖约束，使其与当前 Core 正式版本兼容。

不得继续保留：

```text
onlyalpha>=0.1,<0.2
```

根据最终 Core 版本采用准确约束。

同时更新：

```text
OnlyAlpha-workspace/uv.lock
Workspace 子模块指针
Examples package version
相关 README
```

---

## 6.2 自动枚举全部正式 Scenario

不得手工只选择几个简单场景。

必须通过正式 Scenario Definition Repository 枚举任务完成时全部：

```text
runnable
built-in
required by conformance
```

的 Scenario。

至少包括：

```text
CN_A_SHARE_T1_ENGINE@1.0
GENERIC_T0_CASH_ENGINE@1.0
GENERIC_MARGIN_FUTURES_ENGINE@1.0
GENERIC_CRYPTO_SPOT_ENGINE@1.0
CROSS_PROFILE_VERSION_ENGINE@1.0
```

以及阶段一新增的：

```text
Futures partial-fill/cancel
Futures reject/release
Futures idempotency
Futures over-close rejection
其他正式 Required Scenario
```

如果 Core 中存在更多正式可运行 Scenario，也必须覆盖。

---

## 6.3 Examples 的正确定位

Examples 只能使用 Core 的正式公共接口。

允许使用：

```text
人工 Reference
人工 exact bars
Synthetic DataSource
Virtual Broker
正式 Market Profile
正式 Scenario Runner
正式 Conformance Runner
正式 CLI
```

不得使用：

```text
Core tests fixture
私有 Runtime 属性
Manager concrete class
手工构造 BrokerTradeUpdate
手工写 Position/Account
复制 Market Rule 算法
Examples 专用 Risk/Broker
```

人造数据只代表输入是确定的。

Virtual Broker 只代表 Broker Gateway 是模拟实现。

市场规则必须继续来自正式 Market Profile 和 Market Rule Engine。

---

## 6.4 示例目录

建议建立：

```text
OnlyAlpha-examples/examples/market_scenarios/
    README.md
    run_all.py

    cn_a_share_t1/
    generic_t0_cash/
    generic_margin_futures/
    generic_crypto_spot/
    cross_profile_version/
    futures_partial_fill_cancel/
    futures_reject_release/
    ...
```

每个示例至少包含：

```text
README.md
可执行入口
Scenario 定义或正式 Scenario ID
运行命令
预期 Assertions
预期 Artifact
预期业务结果摘要
```

实际目录结构应符合 Examples 仓现有风格。

---

## 6.5 避免定义漂移

优先通过 Core 的公共 Scenario Repository 按：

```text
scenario_id
scenario_version
```

加载定义。

不得在 Examples 仓复制一份随后可能与 Core 漂移的市场规则或 Expected Facts。

如果必须保存独立 Scenario 文件，应增加同步验证：

```text
Examples Scenario Fingerprint
==
Core Registered Scenario Fingerprint
```

---

## 6.6 单个示例运行

每个示例必须可以独立运行，例如：

```text
uv run onlyalpha scenario run ...
```

或者通过正式 Python Application API。

每个示例必须：

```text
返回成功退出码
Scenario status = PASSED
所有 Assertion PASSED
生成 Artifact
生成稳定 Result Fingerprint
不访问网络
```

---

## 6.7 全量示例入口

实现一个统一入口：

```text
run_all_scenarios
```

可以是：

```text
Python module
CLI wrapper
shell script
```

但必须跨平台，优先使用 Python。

它负责：

```text
枚举全部正式 Scenario
逐个运行
输出状态表
汇总 Assertion
汇总 Artifact 路径
汇总 Fingerprint
失败时返回非零退出码
```

不得随机跳过失败 Scenario。

---

## 6.8 Examples 测试

增加自动化测试：

```text
Definition coverage test
Each example smoke test
All-example integration test
Artifact existence test
Assertion pass test
Fingerprint determinism test
No private Core import test
No network access test
```

必须证明：

```text
Core 每一个 Required Scenario
都在 OnlyAlpha-examples 中有可运行示例
```

建议建立机器可校验的覆盖映射：

```text
scenario_id
scenario_version
example_path
pack_ids
last_verified_fingerprint
```

---

## 6.9 Conformance 示例

除逐 Scenario 示例外，还必须提供：

```text
运行单个 Pack
运行全部 Pack
查看 Capability Coverage
查看 Profile Stability Result
```

示例。

至少演示：

```text
CN_A_SHARE_CASH Pack
GENERIC_T0_CASH Pack
GENERIC_MARGIN_FUTURES Pack
GENERIC_24X7_CRYPTO_SPOT Pack
CROSS_VERSION Pack
```

---

# 七、阶段三：交接文档、思维导图和 UML

阶段三只能在阶段一和阶段二的真实门禁通过后开始。

阶段三三个交付物全部强制完成：

```text
新的交接文档
全组件思维导图
全组件 UML
```

不得省略任意一项。

---

## 7.1 更新交接文档

更新 Core：

```text
OnlyAlpha/HANDOFF.md
```

同时根据实际情况更新：

```text
OnlyAlpha-examples/README.md
OnlyAlpha-workspace/README.md
OnlyAlpha-workspace/uv.lock
```

建议在 Workspace 新增：

```text
OnlyAlpha-workspace/HANDOFF.md
```

用于记录跨仓状态。

交接文档必须基于真实执行结果，至少包含：

```text
本轮完成内容
删除的旧接口
Futures 正式事务链
Reservation 生命周期
五个 Pack 运行结果
Capability Coverage
Profile Stability 状态
Examples 覆盖情况
三仓质量门禁
真实版本和子模块 SHA
已知限制
下一步建议
```

不得保留已经过时的“进行中”结论。

不得把未执行的命令写成通过。

---

## 7.2 全局组件清单

在生成图之前，必须遍历四个仓库的生产源码，生成：

```text
OnlyAlpha-workspace/docs/architecture/
onlyalpha_component_inventory.md
```

组件清单至少包含：

```text
Repository
Package / Module
Component Name
Component Type
Responsibility
Public Entry / Port
Depends On
Consumed By
Supported Runtime Modes
Market Relevance
State Owner
Mutation / Query
Source Path
```

必须覆盖所有生产包。

不得只根据 README 猜测组件。

应结合：

```text
目录树
公开导出
类定义
Protocol / Port
Factory Registry
Composition Root
Import Dependency
Runtime 装配代码
```

建立清单。

测试工具和 Fixture 不作为生产组件，但可以单独列入 Testing Infrastructure。

---

## 7.3 完整组件思维导图

生成：

```text
OnlyAlpha-workspace/docs/architecture/
onlyalpha_system_mindmap.md
```

使用 GitHub 可直接渲染的 Mermaid `mindmap`。

思维导图必须覆盖：

```text
OnlyAlpha Ecosystem

Workspace
Core
Plugins
Examples

CLI
Application Services
Config
Plugin System
Engine
Runtime Modes
Clock
Event Bus

Reference Data
Historical Data
Market Data Pipeline
Snapshot

Cluster
Indicator
Factor
Strategy
Strategy Context

Market Profiles
Profile Registry
Rule Compiler
Market Rule Engine
Rule Ports

Order
Risk
Reservation
Broker Gateway
Virtual Broker
ExecutionProcessor

Position
Allocation
Strategy Ledger
Account
Settlement
Margin
Fee

Collector
Result
Analytics
Artifact
Query

Scenario
Parser
Planner
Exact DataSource
Action Strategy
Runner
Assertion

Conformance
Pack Registry
Runner
Coverage
Stability
Release Gate

OnlyAlpha-plugins
OnlyAlpha-examples
Quality Gates
```

实际组件名称必须来自源码。

不得只给出高层四五个节点。

---

## 7.4 完整组件 UML

生成一个包含所有生产组件的规范 PlantUML 文件：

```text
OnlyAlpha-workspace/docs/architecture/
onlyalpha_system_components.puml
```

并生成配套说明：

```text
OnlyAlpha-workspace/docs/architecture/
onlyalpha_system_component_uml.md
```

完整 UML 必须按 Repository 和 Layer 分包。

至少包含：

```text
Workspace
CLI / Application
Config / Plugin
Engine / Runtime
Clock / Event
Data / Market Data
Cluster / Indicator / Factor / Strategy
Market Profile / Rule Engine
Order / Risk / Reservation
Broker / Execution
Position / Allocation / Ledger
Account / Settlement / Margin / Fee
Collector / Result / Artifact / Query
Scenario
Conformance
Plugins
Examples
```

必须展示：

```text
Dependency
Implements
Uses Port
Creates
Publishes Event
Consumes Event
Reads Query
Owns State
```

使用图例区分关系。

---

## 7.5 UML 边界要求

UML 必须清晰体现：

```text
CLI 不访问 Runtime Manager
Conformance Runner 只调用 Scenario Runner
Scenario Runner 只调用 OnlyEngine
Assertion 只读取标准事实
Collector 不执行业务规则
Broker 不拥有 Runtime 最终状态
ExecutionProcessor 是 Broker Update 正式应用入口
Market Profile 不进入 Runtime 业务组件
Manager 只维护各自状态
Examples 只依赖公共 Core API
Plugins 通过 SPI 接入
```

必须标出 Backtest、Paper、Live、Shadow 共享的接口与不同的 Adapter。

---

## 7.6 UML 完整性证明

建立：

```text
OnlyAlpha-workspace/docs/architecture/
onlyalpha_component_diagram_coverage.md
```

逐项映射：

```text
Component Inventory Entry
→ Mindmap Node
→ UML Alias
```

目标是证明所有生产组件都被图覆盖。

禁止生成一张看起来完整但实际遗漏大量模块的图。

---

## 7.7 图形验证

至少验证：

```text
Mermaid fence 和层级语法
PlantUML @startuml / @enduml
所有 UML alias 唯一
所有关系引用已声明组件
无悬空组件引用
组件清单与图覆盖一致
```

如果环境存在 PlantUML，必须执行语法检查并生成 SVG。

如果环境没有 PlantUML：

```text
PlantUML 源文件仍必须完成
必须执行仓库内结构校验
必须在文档中给出确定的渲染命令
不得因此放弃 UML
不得伪称已生成 SVG
```

可以额外生成分层局部图，但不能用局部图替代完整全局 UML。

---

# 八、组件边界自动门禁

增加或完善架构测试，至少保证：

```text
market profile 不 import scenario/conformance
risk 不 import profile implementation
broker 不 import profile implementation
position 不 import scenario
account 不 import scenario
collector 不 import assertion
assertion 不 import manager
conformance 不 import runtime private
cli 不 import manager concrete
query 不执行 command
examples 不 import onlyalpha 私有模块
plugins 只通过正式 SPI 接入
```

对 Examples 增加禁止导入：

```text
onlyalpha.*._private
onlyalpha.runtime.* concrete internals
onlyalpha.tests
tests.*
```

实际规则应根据当前包结构实现。

---

# 九、确定性和一致性要求

相同输入重复运行至少两次，以下必须一致：

```text
Scenario Input Fingerprint
Scenario Result Fingerprint
Pack Fingerprint
Capability Coverage
Standard Facts
Assertion Result
Artifact Dataset Hash
Stable Business IDs
Row Ordering
```

允许变化：

```text
run_id
wall-clock time
output directory
PID
hostname
```

这些变化不得进入确定性 Fingerprint。

---

# 十、质量门禁

本任务必须真实执行四仓联合门禁。

## 10.1 Core

至少执行：

```text
pytest -q
ruff check .
mypy
ruff format --check .
git diff --check
```

本轮不得继续接受既有：

```text
tests/market_data/test_pipeline_dispatch.py
```

格式失败。

必须修复并使 Core 全仓 format check 通过。

---

## 10.2 Examples

至少执行：

```text
pytest -q
ruff check .
mypy
ruff format --check .
git diff --check
```

以及：

```text
运行全部 Scenario 示例
运行全部 Conformance Pack 示例
重复运行确定性验证
```

---

## 10.3 Plugins

Core 公共接口发生变化时必须执行：

```text
Plugins 全量 pytest
Ruff
Mypy
Format check
git diff --check
```

不得只因为 Plugins 未修改就跳过兼容性验证。

---

## 10.4 Workspace

必须执行：

```text
uv sync --all-packages
workspace import smoke test
三仓联合测试
submodule status
lock file consistency
```

检查：

```text
Core 版本
Examples 依赖约束
Plugins 依赖约束
uv.lock
子模块 SHA
```

全部一致。

---

# 十一、禁止事项

禁止：

```text
为了通过测试复制市场规则到 Scenario
为了通过 Futures 测试直接写 Short Position
由 Broker 直接修改 Runtime Account
由 Examples 使用 Core 私有 API
手工伪造 Capability Coverage
手工伪造 Stable 状态
跳过失败 Scenario
把 Example smoke test 当作 Core Scenario 证据
只生成图的标题而不包含组件
用 README 内容代替源码审计
只生成局部 UML 后宣称全组件 UML 完成
未运行命令却写成通过
保留旧接口兼容分支
```

---

# 十二、本任务明确不要求扩展的内容

除非是完成上述正式场景所必需，本任务不扩展：

```text
US/HK 完整生产规则
Perpetual Funding
Liquidation
Borrow
Portfolio Margin
Options
Level-2 Order Book
Web Server
在线 Tushare
```

但现有相关预留组件仍必须进入组件清单、思维导图和 UML。

---

# 十三、最终完成标准

以下全部满足才可宣称完成：

```text
Futures SELL OPEN 正式链路通过
Futures BUY CLOSE 正式链路通过
SHORT Position 正确
Margin reserve/occupy/release 正确
Account 更新正确
Risk Reservation 无泄漏
部分成交和撤单正确
重复 Broker Update 幂等

Settlement Fact 正式生成
Margin Fact 正式生成
Fee Fact 正式生成

Cross-Version Scenario 正式通过
五个 Conformance Packs 全部执行通过
Capability Coverage 完整
Pack Determinism 通过
Release Gate 通过
满足条件的内建 Profile 正式升级 STABLE

Conformance CLI 完整
Conformance Repository 完整
Conformance Query 完整

OnlyAlpha-examples 覆盖全部正式 Required Scenario
所有 Example 独立可运行
run-all 入口通过
所有 Pack 示例通过
Examples 不使用 Core 私有接口
Examples 与 Core 版本一致

Core 门禁全部通过
Examples 门禁全部通过
Plugins 门禁全部通过
Workspace 联合门禁全部通过
Core 全仓 format check 通过

HANDOFF.md 已更新
Workspace 跨仓交接文档已生成
组件 Inventory 已生成
全组件思维导图已生成
全组件 PlantUML 已生成
图覆盖映射已生成
文档已更新
```

任何一项未完成时，最终报告必须明确：

```text
本组合任务未完成
```

不得使用“基本完成”“主要完成”代替硬门禁。

---

# 十四、最终报告格式

完成后输出中文报告。

## 1. 修改前全局审计

列出 Core、Examples、Plugins 和 Workspace 的真实初始状态。

## 2. 删除与迁移

列出删除的旧接口、重复模型、旧配置和旧示例路径。

## 3. Futures 正式事务链

展示：

```text
Order
→ Risk Reservation
→ Broker
→ ExecutionProcessor
→ Short Position
→ Margin
→ Account
→ Standard Facts
```

## 4. Reservation 与事务一致性

报告：

```text
Reserve
Consume
Occupy
Release
Cancel
Reject
Partial Fill
Runtime Close
```

## 5. 五 Pack 结果

逐个报告：

```text
CN_A_SHARE_CASH
GENERIC_T0_CASH
GENERIC_MARGIN_FUTURES
GENERIC_24X7_CRYPTO_SPOT
CROSS_VERSION
```

## 6. Profile Stability

列出：

```text
Profile
Version
Pack
Capability Coverage
Release Gate
最终状态
```

## 7. Examples

列出全部 Scenario 与对应 Example 路径、运行结果和 Fingerprint。

## 8. 多运行模式一致性

说明 Backtest、Paper、Live、Shadow 共享接口和当前 Adapter 差异。

## 9. 全局组件清单

报告组件数量、仓库分布和分类。

## 10. 思维导图

给出文件位置、覆盖范围和验证结果。

## 11. UML

给出文件位置、组件数量、关系数量和验证结果。

## 12. 文档和交接

列出所有新增和修改文档。

## 13. 四仓质量门禁

列出真实命令、退出码和结果。

## 14. 明确未完成

如果仍有任何硬门禁失败，必须明确任务未完成，不能宣称成功。

---

# 十五、最终原则

> 期货事务链的问题必须在正式 Risk、Execution、Position、Margin、Account 和 Reservation 组件中解决，不能由 Scenario 或 Examples 修补。

> OnlyAlpha-examples 是公共 API 的真实消费者，不是测试 Fixture 仓库。

> 人造数据和 Virtual Broker 可以用于验证，但市场规则仍然只有正式 Market Rule Runtime 一套。

> Conformance Evidence 必须来自正式 Scenario → OnlyEngine 运行结果。

> 思维导图和 UML 必须以全局源码和组件 Inventory 为依据，不得根据旧文档猜测。

> 三个阶段全部完成前，不得宣称本组合任务完成。
