# OnlyAlpha 工程实施指南

本文档面向在 OnlyAlpha 仓库中工作的开发者、Codex、代码生成 Agent、审查 Agent 和自动化工具。

它规定：

```text
事实来源
架构边界
模块职责
经济不变量
实现流程
接口清理要求
测试分层
质量门禁
交付标准
```

本文档作用于整个 Monorepo。子目录中的 `AGENTS.md` 可以补充局部规则，但不得破坏本文件规定的顶层架构、依赖方向和业务不变量。

---

## 1. 项目身份

OnlyAlpha 是一个独立、从零设计的量化交易系统。

必须遵守：

* 从第一性原则分析问题；
* 不把 OnlyAlpha 描述为其他项目的重构版本；
* 不复制外部工程的内部实现形成隐式依赖；
* 不因历史 Prompt、示例或测试保留错误架构；
* 不以兼容旧代码为理由维持两套正式路径；
* 当前源码、正式测试和未被替代的 ADR 是主要事实来源。

OnlyAlpha 当前采用：

```text
Monorepo
+
模块化单体
+
插件化外部适配
```

---

## 2. 事实来源优先级

发生冲突时，按以下顺序判断：

```text
1. 当前可执行源码和正式公共接口
2. 当前自动化测试和架构门禁
3. 已接受且未被替代的 ADR
4. 当前组件文档
5. README.md 和 AGENTS.md
6. HANDOFF.md
7. docs/reports/
8. prompts/
```

`prompts/` 是历史实施材料，不是当前工程事实。

修改组件前必须：

1. 阅读目标源码；
2. 阅读目标测试；
3. 查找相关 ADR；
4. 查找公共接口、Port、Factory 和 Registry；
5. 确认是否已有同类能力；
6. 明确当前支持范围和非目标；
7. 再决定修改、替换或删除。

禁止仅根据 Prompt 创建第二套实现。

---

## 3. 当前产品边界

当前正式完成的主要产品范围：

```text
Runtime         : BACKTEST
Market Profile  : GENERIC_T0_CASH
Account Type    : CASH
Order Type      : LIMIT
Position Side   : LONG
Position Mode   : NETTING
Open            : BUY OPEN
Close           : SELL CLOSE
Fill            : Whole / Partial / Multi-Fill
Terminal        : Cancel / Reject / Expire
Cluster         : Single / Multi-Cluster
Persistence     : Memory / SQLite
```

当前未形成正式产品闭环：

```text
Paper
Live
Shadow
Research Workflow
Web
Short/Hedging Durable Lifecycle
Futures/Margin Durable Lifecycle
Unallocated Close
Cross-Cluster Close
FIFO/LIFO Lot Selection
Corporate Action
Multi-Currency/FX
OrderBook Matching
Distributed Backtest
```

存在枚举、模型、Manager 或 Legacy 路径，不等于正式能力完成。

---

## 4. 唯一产品入口

`OnlyEngine` 是唯一产品级运行入口。

正式产品链必须经过：

```text
CLI / Application
→ OnlyEngine
→ OnlyRuntimePlanner
→ OnlyEngineRunAssembler
→ Runtime Factory
→ OnlyRuntime
→ OnlyCluster
```

禁止：

* CLI 直接实例化 Manager；
* CLI 直接执行 Backtest 内部循环；
* Scenario Runner 绕过 Engine；
* 示例手工装配 Manager 伪造产品运行；
* 新建第二套 Engine Service；
* 创建市场专用平行 Engine；
* 创建仅供测试使用的生产产品入口。

核心配置入口：

```python
engine.add_cluster(config)
```

文件适配入口：

```python
engine.add_cluster_from_file(path)
```

一个 Engine 实例只能完整运行一次。

---

## 5. Engine 职责

Engine 负责：

* Cluster Definition 注册；
* 配置和扩展类型验证；
* 配置指纹；
* Runtime 兼容性规划；
* Runtime/Cluster Session；
* 共享基础设施引用计数；
* 生命周期；
* Runtime 执行；
* 结果汇总；
* `user_data` 输出；
* Artifact 和 Report；
* 失败回滚和资源释放。

Engine 不负责：

* 策略算法；
* 指标计算；
* 券商 SDK 细节；
* 撮合算法细节；
* 费用公式；
* SQL 业务逻辑；
* 市场规则硬编码；
* Web 展示。

---

## 6. Runtime 所有权

Runtime 是全部可变交易状态的唯一所有者。

每个 Runtime 必须拥有或独占：

```text
Clock
Event Bus
MarketData Pipeline
MarketData Cache
Bar Aggregation
MarketData Inbound Queue
Broker Inbound Queue
Order Manager
Position Manager
Allocation Manager
Strategy Ledger Manager
Account Manager
Risk Service
ExecutionProcessor
Settlement/Margin Service
Persistence Store
Checkpoint Participants
Recovery State
Runtime Audit
```

Cluster、Strategy、Factor、Plugin 和 Broker Gateway 不得持有 Runtime Manager。

Manager 不得被多个 Runtime 共享。

---

## 7. Cluster 隔离

一个 Cluster：

* 只持有一个 Strategy；
* 可以持有多个 Factor；
* 每个 Factor 可以创建多个 Indicator；
* 拥有独立 Strategy、Factor、Indicator 和 Ledger Scope；
* 只能通过受限 Context 使用 Runtime 能力；
* 不得读取其他 Cluster 的订单、Allocation、Ledger 或私有状态。

固定调度顺序：

```text
MarketData
→ Indicator
→ Time-Series Factor
→ Cross-Section Factor
→ Factor Snapshot / Score
→ Strategy
→ Order
```

结果不得依赖：

* 字典插入顺序；
* Cluster 注册顺序；
* Python 导入顺序；
* 对象创建顺序；
* EventBus Handler 偶然顺序；
* 外部 SDK 回调偶然顺序。

---

## 8. Monorepo 包职责

### 8.1 Core

路径：

```text
src/onlyalpha/
```

Core 承载：

* 公共领域模型；
* Engine、Runtime、Cluster；
* 公共 Port 和 Protocol；
* 配置；
* Synthetic DataSource；
* Scenario Exact DataSource；
* Broker SPI 和 Inbound Queue；
* Execution、Position、Account、Risk；
* Result、Analytics、Artifact、Report；
* Plugin SPI；
* Market Profile 和规则基础设施。

Core 不得导入：

```text
onlyalpha_plugin_broker_virtual
onlyalpha_plugin_tushare
onlyalpha_plugin_miniqmt
```

### 8.2 Virtual Broker

路径：

```text
packages/fake/onlyalpha-plugin-broker-virtual/
```

职责：

* 标准 Broker SPI；
* Order Accept/Reject/Cancel；
* Next-Bar Matching；
* Slippage；
* Fill Plan；
* 确定性调度；
* Broker Checkpoint；
* 标准 Broker Update。

不得：

* 持有 Runtime Manager；
* 修改 Account、Position 或 Risk；
* 成为 Runtime Accounting Truth；
* 硬编码完整 Market Rule；
* 直接计算正式 Account Fee。

### 8.3 Tushare

路径：

```text
packages/provider/onlyalpha-plugin-tushare/
```

职责：

* SDK 加载；
* 配置解析；
* 历史行情请求；
* 数据标准化；
* Cache 协作；
* DataSource Factory；
* Entry Point；
* Doctor。

不得：

* 模块导入阶段访问网络；
* 持有 Runtime Manager；
* 修改交易状态；
* 把复权价格自动当作撮合价格。

### 8.4 MiniQMT

路径：

```text
packages/provider/onlyalpha-plugin-miniqmt/
```

职责：

* MiniQMT DataSource Adapter；
* Broker Adapter；
* 标准 Update 转换；
* 插件配置；
* 平台能力检查。

不得：

* 让 Core 依赖 MiniQMT；
* 绕过 Broker Inbound Queue；
* 直接修改 Manager；
* 在未完成对账前开放真实资金。

---

## 9. 市场规则

市场规则必须经过：

```text
Market Profile
→ Registry
→ Resolver
→ Compiler
→ Runtime Rule Engine
→ Instruction
```

Planner、Risk、Virtual Broker、Settlement 和 Fee 应消费编译后的 Instruction。

禁止：

* Strategy 硬编码市场税率；
* Planner 硬编码 Settlement Date；
* Broker 硬编码 T+1；
* Risk 和 Broker 各自实现不同涨跌幅规则；
* 使用 Profile 名称后仍走 Generic 假设；
* 在多个组件中复制同一市场规则。

---

## 10. Durable Execution 合同

当前正式 Durable 范围：

```text
GENERIC_T0_CASH
CASH
LIMIT
LONG
NETTING
BUY OPEN
SELL CLOSE
```

不可破坏：

```text
One Fill
=
One Immutable Prepared Transaction
=
One Committed Transaction
```

一个 Fill 必须具有：

```text
Stable Fill Identity
Payload Fingerprint
Per-Order Fill Index
Execution Sequence
Prepared Transaction
Committed Transaction
Ordered Projection
Projection Ready
Durable Outbox Intent
```

不得：

* 多个 Fill 合并成一个可变 Transaction；
* 修改已有 Fill Identity 语义；
* 使用 Source Sequence 代替 Fill Index；
* Commit 后修改 Transaction；
* 在 Projection 外直接修改多个 Manager；
* 对正式 Durable Scope 回退到 Legacy Mutation。

---

## 11. Operation Kind

正式 Operation：

```text
TRADE_FILL
ORDER_TERMINAL
```

### TRADE_FILL

必须具有 Trade ID。

### ORDER_TERMINAL

用于：

```text
CANCELLED
REJECTED
EXPIRED
```

不得伪造 Trade ID。

Terminal Fact 不得计入：

```text
Trade Count
Trade PnL
Trade Fee
Trade Settlement
```

---

## 12. Projection 和 Authority

Prepared Transaction 包含完整的：

```text
Before State
After State
Economic Fact
Ordered Projection
Authority Hash
Payload Hash
```

Projection 顺序是正式合同。

任何组件不得在应用 Projection 时重新决策：

* 成本；
* PnL；
* Fee；
* Settlement；
* Reservation Delta；
* Risk Delta。

Manager 应安装或验证 Planner 已决定的权威结果，而不是重新计算另一套答案。

---

## 13. Close Cost Authority

Multi-Cluster Close 使用：

```text
Allocation
=
Close Attribution Authority

Position
=
Account Aggregate Authority
```

Planner 在纯规划阶段创建一份不可变的：

```text
OnlyAttributedCloseCostAuthority
```

流程：

```text
Order Cluster
→ 定位 Allocation
→ 校验 Position/Allocation 聚合
→ 计算一次 released cost
→ 计算一次 realized PnL
→ Position/Allocation/Account/Ledger/Fact 共同消费
```

必须保持：

```text
Position Quantity
=
sum(Allocation Quantity)

Position Cost
=
sum(Allocation Cost)

Position Released Cost
=
Allocation Released Cost
=
Fact Released Cost

Position PnL
=
Allocation PnL
=
Account PnL
=
Ledger PnL
=
Fact PnL
```

Position 和 Allocation Reducer 不得分别调用成本释放函数。

Account 和 Ledger 不得重新计算 Close PnL。

无法解释的 Unallocated Cost 必须在 Commit 前 Fail Closed。

禁止添加：

```text
legacy_close_cost
compatibility_close_cost
use_position_average_cost
fallback_to_account_average
```

之类的兼容开关。

---

## 14. 精度规则

正式成本权威：

```text
cumulative_open_price_quantity
```

平均开仓价：

```text
average_open_price
```

只是派生值。

禁止使用量化后的平均价格反向决定精确累计成本。

所有关键 Decimal 运算应：

* 使用局部 Decimal Context；
* 明确 Precision；
* 明确 `ROUND_HALF_EVEN`；
* 避免修改全局 Decimal Context；
* 最终平仓强制数量和成本归零；
* 金额按 Currency Precision 量化；
* 价格按 Instrument Price Precision 量化。

---

## 15. Account 和 Strategy Ledger

Account 是账户级权威。

Strategy Ledger 是 Cluster 级归因权威。

两者必须使用同一个 Planner 经济结论。

不得：

* Account 重算 Realized PnL；
* Ledger 重算 Realized PnL；
* Account 用 Position Average 代替 Fact；
* Ledger 用 Allocation Average 产生另一套 PnL；
* 单独修正 Ledger 以通过对账。

Runtime 最终对账必须比较：

```text
Account
与
所有 Strategy Ledger 的正式聚合
```

不能用 Account 与当前单个 Ledger 比较 Multi-Cluster Capability。

---

## 16. Risk 和 Reservation

Reservation 是正式交易权威的一部分。

支持：

```text
Cash Reservation
Position Reservation
Risk Reservation
Incremental Consumption
Terminal Release
```

Multi-Fill 中：

```text
中间 Fill
→ 分段消费
→ Active Order Count 保持

最终 Fill
→ Reservation Consumed
→ Active Order Count 减少一次
```

Terminal Operation：

```text
保留已成交部分
释放未成交部分
Active Order Count 只减少一次
```

不得在 Transaction 外重复调用 Release 或 Consume。

---

## 17. Fee 和 Settlement

Fee 必须经过：

```text
Fee Configuration
→ Fee Schedule
→ Fee Resolver
→ Fee Instruction
→ Order Fee Accrual
→ Fee Projection
```

FeeManager 不计算 Fee，只安装正式结果。

支持：

```text
FILL
ORDER_CUMULATIVE
```

订单级最低佣金不得在每个 Fill 重复收取。

Settlement Date、Cash Availability 和 Asset Bucket 必须来自 Market Instruction，不得由 Planner 硬编码。

---

## 18. Persistence 和 Recovery

当前 Backtest 支持：

```text
Memory Store
SQLite Store
Prepared Transaction
Committed Transaction
Projection State
Projection Ready
Durable Outbox
Runtime Checkpoint
Restart Recovery
```

Recovery 必须遵守：

* 不重新选择成本；
* 不重新生成 Identity；
* 不重复 Commit 已持久化 Transaction；
* 不修改已提交 Fact；
* 不依赖当前 Manager 状态重算历史结果；
* 只重建相同 Prepared Transaction或应用持久化 Projection；
* 恢复完成后执行只读 Authority Validation。

不得新增：

```text
Close Store
Close Coordinator
Close Recovery Phase
Market-Specific Recovery Phase
```

除非现有通用基础设施无法表达正式需求，并有明确 ADR。

---

## 19. Event 语义

当前语义：

```text
Durable Outbox : at-least-once
Direct Event   : best-effort
```

Outbox Published 表示 EventBus 已接受，不表示 Subscriber 已确认。

当前未实现：

```text
Subscriber ACK
Delivery Watermark
Exactly-once
Direct Durable Journal
Remote EventBus
```

不得在文档或代码中声称已经实现。

---

## 20. API 演进与旧接口清理

从第一性原则修复问题时，应选择一条正式路径。

不得因为以下原因保留错误接口：

* 旧测试仍调用；
* 示例仍调用；
* Prompt 中出现；
* 历史代码使用；
* 修改调用点工作量较大；
* 可能有未声明的内部用户。

当旧接口失去业务意义时：

1. 修改所有正式调用点；
2. 修改测试；
3. 修改示例；
4. 修改文档；
5. 删除旧接口；
6. 删除 Adapter；
7. 删除无用参数；
8. 删除过时错误码；
9. 增加 Architecture Gate 防止恢复。

禁止创建只做转发的兼容层。

公共发布兼容必须是明确产品决策，不能由测试偶然决定。

---

## 21. 测试原则

测试应验证正式边界，而不是保护历史实现。

测试不得：

* 直接篡改对象私有状态；
* 依赖字典顺序；
* 依赖随机时间；
* 绕过 OnlyEngine 声称验证产品链；
* 用手工 Broker Update 声称完成 Virtual Broker 产品；
* 降低经济不变量；
* 隐藏正式 Execution；
* 使用 `skip` 或 `xfail` 掩盖回归；
* 添加生产 `test_mode`；
* 为测试保留废弃生产接口。

---

## 22. 测试分层

测试应划分为：

### Fast

```text
unit
contract
architecture
```

特点：

* 纯函数；
* Value Object；
* Planner；
* Reducer；
* Codec；
* Registry；
* Architecture Gate。

### Integration Smoke

最短正式纵切面：

```text
OnlyEngine
→ 一个 Runtime
→ 一个或两个 Cluster
→ 最少 Bar
→ 一个 Open
→ 一个 Close
→ Result
```

### Full Integration

```text
Multi-Fill
Multi-Cluster
Artifact
Report
Scenario
SQLite
```

### Recovery / Exhaustive

```text
Commit Fault
Mid-Projection
Outbox
Checkpoint
A→B→C
Registration Order
Fault Matrix
```

### External

```text
Network
Tushare Token
Local QMT
Platform SDK
```

External Test 不得进入默认离线测试。

---

## 23. 测试性能规则

新增测试必须选择成本最低但仍能证明业务语义的正式层级。产品纵切面必须经过 `OnlyEngine`；Analytics、Report、Artifact、
Collector 和 CLI formatting 优先复用不可变 Result/Snapshot Fixture。长测试必须标记 `slow` 或 `recovery`，External 测试不得
进入默认离线门禁，MiniQMT 真实下单必须由人工显式触发并标记 `requires_broker_account`。禁止向生产代码加入测试开关。

OnlyAlpha 的 Integration Test 成本较高。新增测试必须控制重复工作。

必须：

* 使用满足业务场景的最短数据；
* 下游组件优先消费固定 Result Fixture；
* Analytics 不应反复运行完整 Engine；
* Report Renderer 不应反复运行完整 Engine；
* Collector 单元测试不应生成全部 Artifact；
* 每类业务只保留必要的双运行 Determinism 测试；
* Recovery Fault Matrix 可以复用模块级 Baseline；
* 使用 `tmp_path` 隔离文件；
* 需要共享 Module Fixture 时评估 `--dist=loadscope`；
* 时长差异明显时评估 `--dist=worksteal`；
* 新增长测试必须标记 `slow` 或 `recovery`。

不得通过生产快捷路径提速。

---

## 24. 测试命令

依赖：

```bash
uv sync --frozen --all-packages --all-groups
```

静态检查：

```bash
uv run ruff check src tests examples packages
uv run ruff format --check src tests examples packages
uv run mypy src/onlyalpha
```

快速核心：

```bash
uv run pytest \
  tests/execution \
  tests/order \
  tests/position \
  tests/account \
  tests/strategy_ledger \
  tests/risk \
  tests/architecture \
  -q
```

Integration：

```bash
uv run pytest -n 6 --dist=worksteal tests/integration -q
```

完整 Core：

```bash
uv run pytest -n auto tests -q
```

离线门禁：

```bash
uv run pytest -n auto tests -q \
  -m "not external and not requires_network and not requires_tushare and not requires_local_qmt"
```

失败定位：

```bash
uv run pytest path/to/test.py::test_name -vv --tb=long
```

性能分析：

```bash
uv run pytest tests/integration -q \
  --durations=100 \
  --durations-min=0.5
```

---

## 25. 实现工作流

每个非平凡任务按以下顺序执行。

### 25.1 审计

确认：

```text
当前源码
当前测试
当前 ADR
当前公共 API
当前 Capability
当前非目标
```

### 25.2 复现

增加最小失败测试，稳定暴露真实问题。

不得先大规模修改代码再猜测根因。

### 25.3 设计

明确：

```text
唯一 Authority
模块职责
输入
输出
不变量
持久化边界
恢复边界
非目标
```

### 25.4 实现

优先：

* 纯函数；
* 不可变 Dataclass；
* 显式 Port；
* 单一数据来源；
* 小而明确的模块；
* 现有通用基础设施。

### 25.5 清理

删除：

* 旧路径；
* 旧参数；
* Compatibility Wrapper；
* 无调用 Helper；
* 过时 Error Code；
* 过时 Fixture；
* 过时文档。

### 25.6 验证

依次运行：

```text
定向单元测试
相关组件测试
Integration
Recovery
Architecture
全量门禁
```

### 25.7 文档

同步更新：

```text
ADR
README
组件文档
Roadmap
AGENTS
```

只有实际产品边界发生变化时才更新“完成状态”。

---

## 26. 架构门禁

重大功能应增加 Architecture Test，检查：

* Core 不导入具体插件；
* 产品入口只有 OnlyEngine；
* Strategy 不持有 Manager；
* Account 不重算 PnL；
* Ledger 不重算 PnL；
* Position/Allocation 不产生两套 Close Cost；
* 支持范围不进入 Legacy Mutation；
* Recovery 不重新决策历史业务；
* 不新增平行 Store；
* 不新增平行 Coordinator；
* 不新增市场专用 Recovery Phase；
* 不存在生产 Fault Switch；
* 不存在兼容模式开关；
* 不存在测试专用生产入口。

---

## 27. 代码质量

Python：

```text
Python 3.12
Strict Mypy
Ruff
Dataclass
Decimal
Explicit Typing
```

必须：

* 公共接口有类型；
* 避免 `Any`；
* 避免隐式全局状态；
* 避免模块导入副作用；
* 使用明确的 Domain Type；
* 使用稳定 ID；
* 使用 UTC 内部时间；
* 用 Instrument/Calendar 表达本地市场时间；
* 使用结构化错误码；
* Fail Closed。

禁止：

* 裸 `dict` 在领域层长期传播；
* Float 表示金额、价格和数量；
* Manager 互相直接写状态；
* Plugin 反向依赖 Core 内部实现；
* SQL 中隐藏业务规则；
* 生产代码中隐藏测试开关。

---

## 28. 文档规则

文档必须区分：

```text
已形成正式产品链
基础模型存在
Legacy 路径存在
计划实现
明确不支持
```

禁止把：

```text
有 Enum
有 Manager
有单元测试
有旧执行路径
```

描述成产品完成。

README 应面向使用者。

AGENTS 应面向工程实施者。

ADR 应记录不可逆或重要架构决策。

Roadmap 应表达产品状态，不应堆叠历史提交日志。

`docs/reports/` 和 `prompts/` 不得覆盖当前源码事实。

---

## 29. 当前优先级

### P0：Test Suite Performance and Layering

目标：

```text
缩短开发反馈
减少重复 Engine Run
建立 Fast / Integration / Recovery 分层
保持覆盖不下降
```

### P1：CN A-share Cash Product Closure

目标：

```text
T+1
停牌
涨跌停
板块/ST
整手和零股
费用
真实离线样本
完整 Scenario Pack
```

### P2：Data and Corporate Action

目标：

```text
复权
公司行为
证券状态
参考数据版本
大规模回放
```

### P3：Research Workflow

### P4：Paper / Live

Futures/Margin、Short/Hedging 和更多市场应在当前 Cash 产品闭环后再扩展。

---

## 30. PR 完成标准

一个 PR 只有在以下条件满足后才能声明完成：

1. 根因已明确；
2. 正式 Authority 唯一；
3. 模块职责清晰；
4. 旧路径已删除；
5. 无无意义兼容层；
6. 单元测试通过；
7. Integration 通过；
8. Recovery 不回归；
9. Architecture Gate 通过；
10. Ruff 通过；
11. Mypy 通过；
12. 文档与源码一致；
13. 非目标明确；
14. 未伪造测试结果；
15. 未把未完成内容转移为隐性后续债务。

---

## 31. 最终原则

OnlyAlpha 的实现应优先满足：

```text
业务正确
>
架构清晰
>
确定性
>
可恢复
>
可审计
>
性能
>
兼容历史内部接口
```

性能优化不得破坏业务正确性。

兼容旧测试不得破坏正式模型。

新增功能不得建立第二套 Authority。

任何无法解释的经济状态都必须 Fail Closed。
