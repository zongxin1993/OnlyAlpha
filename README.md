# OnlyAlpha

**OnlyAlpha** 是一个面向个人与小型团队的模块化量化交易工程，核心目标是在保持工程结构清晰、运行结果确定、状态可恢复的前提下，为 **Research、Backtest、Sim、Live** 四种 Runtime 提供统一的量化基础设施。

OnlyAlpha 不把回测、实时模拟和实盘设计成三套独立交易系统。

其核心设计原则是：

> **Research 为研究效率服务；Backtest、Sim、Live 为交易语义一致性服务。**

Backtest、Sim 和 Live 应尽可能复用相同的 Strategy、Market Rule、Risk、Order、Execution、Fee、Position、Account、Settlement 与 Durable Transaction Kernel，仅在 **Clock、MarketData Driver、Broker Adapter 和 Lifecycle Driver** 等外部驱动层存在差异。

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

# 1. 工程定位

OnlyAlpha 不是单文件策略回测工具，也不是以高频交易为目标的超低延迟系统。

工程主要面向：

* 分钟级及以上周期的量化策略；
* 历史数据研究与参数探索；
* 确定性事件驱动回测；
* 实时虚拟交易；
* 真实 Broker 实盘交易；
* 多市场、多资产类别扩展；
* 数据、指标、因子和研究结果的长期沉淀；
* Web 投研与结果展示；
* 可恢复、可审计的长期运行环境。

工程当前采用 **模块化单体（Modular Monolith）**，优先解决领域边界、状态权威、确定性和可恢复性，而不是过早拆分微服务。

---

# 2. 核心设计目标

OnlyAlpha 的长期目标包括：

1. **统一 Engine**

   * 一个 `OnlyEngine` 作为产品级唯一运行入口；
   * 一个 Engine 可以管理多个 Runtime；
   * Trading Runtime 内可以承载多个相互隔离的 Cluster；
   * Research Runtime 承载 Research Job / Plan，不被强制包装成交易 Cluster。

2. **四种明确的 Runtime**

   * Research
   * Backtest
   * Sim
   * Live

3. **交易语义一致**

   * Backtest、Sim、Live 共用正式交易内核；
   * Strategy 不根据 Runtime 编写不同交易逻辑；
   * Runtime 差异尽量限制在 Driver 层。

4. **确定性**

   * 相同输入、相同 Authority Version、相同 Broker Facts 应产生相同经济历史和结果；
   * Backtest 与 Recovery 必须具有可重复结果。

5. **单一状态权威**

   * 每个状态域只有一个写入 Authority；
   * 不允许 Strategy、Broker Adapter 或多个 Manager 同时维护同一份业务真值。

6. **Durable Trading**

   * 关键经济事实先 Durable Commit，再更新 Projection；
   * Crash 后通过 Forward Recovery 恢复，而不是跨 Manager 回滚。

7. **市场中立**

   * Execution Kernel 不根据市场名称做业务分支；
   * 市场差异通过 Reference、Market Rule、Fee、Settlement 等 Authority 表达。

8. **Fail Closed**

   * 无法证明合法性、兼容性、Authority 或状态一致性时拒绝继续；
   * 不使用静默 fallback 修复未知状态。

---

# 3. Runtime 模型

OnlyAlpha 的目标产品架构只保留四种 Runtime。这里定义长期语义，不代表当前源码已经全部实现：

```text
OnlyEngine
│
├── Research Runtime
│   └── Research Job / Plan
├── Backtest Runtime
│   └── Cluster workload(s)
├── Sim Runtime
│   └── Cluster workload(s)
└── Live Runtime
    └── Cluster workload(s)
```

## 3.1 Research

Research 面向高速历史研究，不承担正式交易执行语义。

```text
Historical Data
      ↓
Research Dataset
      ↓
Vectorized Indicator
      ↓
Factor / Feature
      ↓
Parameter Sweep
      ↓
Statistics
      ↓
Research Result
      ↓
Web Visualization
```

主要特征：

* 使用历史数据；
* 支持向量化计算；
* 面向 K 线、指标、因子、特征和参数研究；
* 支持批量参数搜索；
* 支持 IC、Rank IC、Forward Return、分组收益等统计；
* 生成标准化 Research Result / Artifact；
* 面向 Web、Notebook、CLI 等研究界面；
* 不要求经过完整 Order / Broker / Transaction Kernel。

Research 的目标是：

> **快速发现值得进一步验证的策略、因子和参数。**

Research Runtime 只拥有 research execution、dataset、calculation、Research Result 和 Artifact state。它不会仅为结构对称而创建正式 Order、Position、Account、Broker、Reservation 或 Trading Transaction authority；Research Job 也不伪装成 Trading Cluster。

---

## 3.2 Backtest

Backtest 使用历史数据，但采用完整事件驱动交易链。

```text
Historical Data
      ↓
Historical Replay
      ↓
Backtest Clock
      ↓
MarketData Pipeline
      ↓
Indicator / Factor
      ↓
Strategy
      ↓
Market Rule
      ↓
Risk
      ↓
Order
      ↓
Virtual Broker
      ↓
Accepted / Trade / Terminal
      ↓
Durable Transaction
      ↓
Account / Position / Fee / Settlement
```

Backtest 的主要目标不是获得最高计算吞吐，而是：

> **尽可能复现 Sim / Live 的交易运行语义。**

因此正式 Backtest 不使用向量化方式替代：

* Order；
* Risk；
* Reservation；
* Broker lifecycle；
* Partial Fill；
* Fee；
* Position；
* Settlement；
* Durable Transaction。

Research 负责快速筛选，Backtest 负责精确交易验证。

---

## 3.3 Sim

Sim 使用实时市场数据，但所有订单只进入本地 Virtual Broker。

```text
Realtime Market Data
        ↓
Live Clock
        ↓
MarketData Pipeline
        ↓
Indicator / Factor
        ↓
Strategy
        ↓
Market Rule
        ↓
Risk
        ↓
Order
        ↓
Virtual Broker
        ↓
Accepted / Trade / Terminal
        ↓
Durable Transaction
        ↓
Virtual Account / Position
        ↓
PnL / Analytics
```

Sim：

* 使用实时行情；
* 不向真实 Broker 发送订单；
* 使用本地虚拟账户；
* 使用本地 Virtual Broker；
* 产生完整模拟 Accepted / Fill / Cancel / Reject / Expire；
* 使用正式 Position、Account、Fee、Settlement 和 Transaction Kernel；
* 用于在真实时间环境中验证策略行为。

Sim 是 Backtest 与 Live 之间的重要验证层。

---

## 3.4 Live

Live 使用实时行情和真实 Broker。

```text
Realtime Market Data
        ↓
Live Clock
        ↓
MarketData Pipeline
        ↓
Indicator / Factor
        ↓
Strategy
        ↓
Market Rule
        ↓
Risk
        ↓
Order
        ↓
Durable Broker Command
        ↓
Real Broker
        ↓
Broker Facts
        ↓
Durable Execution Kernel
        ↓
Local Canonical Trading State
        ↓
Broker Reconciliation
```

Live 与 Sim 应尽可能共用全部交易核心。

Live 特有职责主要包括：

* Durable Broker outbound command；
* Broker idempotency；
* Broker ACK / Reject / Unknown；
* Account / Order / Trade / Position synchronization；
* reconnect；
* reconciliation；
* long-running recovery；
* 生产运维。

---

# 4. Backtest / Sim / Live 一致性原则

三种 Runtime 不要求 Driver 代码完全相同。

它们必须保证的是：

> **Trading Semantic Equivalence，而不是 Driver Implementation Equivalence。**

允许不同：

| 能力     | Backtest      | Sim          | Live         |
| ------ | ------------- | ------------ | ------------ |
| 数据     | Historical    | Realtime     | Realtime     |
| Clock  | BacktestClock | LiveClock    | LiveClock    |
| Broker | Virtual       | Virtual      | Real         |
| 生命周期   | Finite        | Long-running | Long-running |

必须尽量相同：

```text
Strategy
Market Rule
Risk
Order
Reservation
Execution Support
Execution Processor
Fee
Position
Allocation
Account
Strategy Ledger
Settlement
Transaction
Recovery semantics
```

理想目标：

```text
Same Normalized Market Events
+
Same Strategy
+
Same Broker Facts
        ↓

Backtest / Sim / Live
        ↓

Same Economic Result
```

未来应建立正式的 **Runtime Trading Semantic Conformance** 测试证明这一性质。

`Runtime Type != Execution Permission`：Runtime type 可以参与 Driver 选择、Runtime identity、planning/grouping 和生命周期组合，但不能成为经济能力、市场合法性或 Execution Support authority。Strategy 与 Trading Kernel 不得按 Runtime type 改变交易语义。

---

# 5. Engine / Runtime / Cluster 关系

长期顶层关系：

```text
OnlyEngine
├── Research Runtime
│   ├── Research Job A
│   └── Research Job B
├── Backtest Runtime
│   ├── Cluster A
│   └── Cluster B
├── Sim Runtime
│   └── Cluster C
└── Live Runtime
    └── Cluster D
```

职责：

## OnlyEngine

负责：

* 产品级生命周期；
* 当前 Trading product 的 Cluster Definition；
* Runtime Planning；
* Runtime grouping；
* Runtime Session；
* Cluster Session；
* 基础设施引用；
* Runtime 创建、启动、停止和关闭；
* Result / Artifact 聚合。

Engine 不直接拥有交易状态。

---

## Trading Runtime

Trading Runtime（Backtest / Sim / Live）是 mutable trading authorities 的所有者。

每个 Trading Runtime 独占：

* Order Manager；
* Position Manager；
* Allocation Manager；
* Account Manager；
* Strategy Ledger Manager；
* Reservation Manager；
* Risk Manager；
* Settlement Manager；
* Execution Processor；
* Runtime Transaction Store；
* Applied Projection Ledger；
* Transaction Coordinator / Outbox；
* Broker inbound queue；
* MarketData processing state。

---

## Research Runtime

Research Runtime 拥有 research execution、dataset、calculation、result 与 artifact state。它不承担 formal Trading Kernel，也不为共享父类或形式统一创建没有业务意义的 Trading Manager。

当前源码的公共 Runtime 基类仍是 trading-shaped，Research Factory 也尚未实现；这是后续源码迁移边界，不是目标 Research ownership。

---

## Cluster

Cluster 是 Trading Runtime 的策略隔离 workload，不是 Research Job。

```text
Cluster
├── one Strategy
├── zero-or-more Factors
└── Indicators
```

Cluster：

* 不拥有 Runtime Manager；
* 不维护账户完整副本；
* 不能直接修改 Position / Account；
* 通过受限 Context 读取 immutable Snapshot；
* 通过正式 Order API 请求交易。

---

# 6. Strategy / Factor / Indicator 边界

## Indicator

Indicator：

* 只负责底层滚动计算；
* 不产生交易副作用；
* 不拥有 Position 或 Account；
* 输入确定时输出应确定。

---

## Factor

Factor：

* 可以组合多个 Indicator；
* 负责特征、评分或信号计算；
* 不拥有交易权限；
* 不直接创建 Order。

---

## Strategy

Strategy：

* 读取 Market Data；
* 读取 Factor Snapshot；
* 读取账户、持仓等受限 Snapshot；
* 生成 Order Intent；
* 不直接修改交易 Authority。

固定关系：

```text
Market Data
    ↓
Indicator
    ↓
Factor
    ↓
Strategy
    ↓
Order Intent
```

---

# 7. 状态权威原则

OnlyAlpha 采用：

> **One Domain → One Write Authority**

主要状态域：

```text
Runtime Transaction History
    → Transaction Store

Projection Progress
    → Applied Projection Ledger

Order
    → Order Authority

Position
    → Position Authority

Cluster Position Attribution
    → Allocation Authority

Account
    → Account Authority

Strategy Virtual Capital
    → Strategy Ledger Authority

Risk
    → Risk Authority

Risk Reservation
    → Risk Reservation Authority

Cash Reservation
    → Cash Reservation Authority

Position Reservation
    → Position Reservation Authority

Settlement
    → Settlement Authority

Market Fee / Broker Fee Application
    → Fee Authorities / Ledgers
```

这些 mutable trading authorities 由各自的 Trading Runtime 独占。Research Runtime 不为结构对称创建它们。

禁止：

```text
Strategy 自己维护完整账户

Broker Gateway 持有本地 Position Manager

两个 Manager 同时拥有一个 balance

Projection Target 修改其它 Domain

Recovery 重新创造已经 Commit 的历史事实
```

---

# 8. Account 与 Strategy Ledger

Account 和 Strategy Ledger 是两个不同 Authority。

```text
Runtime
├── Account
└── Strategy Ledger
```

## Account

Account 表示：

* Runtime 账户级经济状态；
* Cash；
* Position；
* Fees；
* Margin；
* Equity；
* Broker reconciliation basis。

## Strategy Ledger

Strategy Ledger 表示：

* Cluster 的虚拟资金；
* Cluster reserved cash；
* Cluster position attribution；
* Cluster realized/unrealized PnL；
* Cluster equity。

两者：

```text
不共享 mutable state
```

但必须维护正式经济一致性。

---

# 9. Position 与 Allocation

OnlyAlpha 将账户级持仓和 Cluster 归因分离：

```text
Account Position
       ↓
Position Authority

Cluster Ownership
       ↓
Allocation Authority
```

例如：

```text
Account:
AAPL = 1000

Cluster A:
600

Cluster B:
400
```

则：

```text
Position = 1000
Allocation A = 600
Allocation B = 400
```

这使 Multi-Cluster 可以共享 Account，同时保持策略归因独立。

---

# 10. Market Authority

OnlyAlpha 不允许 Execution Kernel 直接判断：

```text
A-share
Futures
Crypto
US Equity
...
```

市场差异应该通过：

```text
Market Profile
Reference Authority
Compiled Market Rules
Fee Authority
Settlement Instruction
```

进入正式 Runtime。

目标链：

```text
Market Product
      ↓
Reference Authority
      ↓
Market Profile
      ↓
Rule Compilation
      ↓
Compiled Market Rules
      ↓
Runtime
```

最终：

```text
Execution Core
```

只消费已经规范化的经济 Instruction。

P5.1 已建立 `onlyalpha.market.product` Core Contract：具体市场以后通过显式 Factory Registry 解析为 immutable `OnlyResolvedMarketProductBinding`。Binding 组合 Reference Authority、pure Policy Compiler 与现有 Market Fee Pack，且其 fingerprint 只基于 effective authorities。当前 Generic T0 与 CN A-share 的生产 cutover 分别属于 P5.2/P5.3；现有 Profile/A-share 路径仍是当前实现事实，不代表迁移已完成。

---

# 11. Reference Authority

Reference 与行情不是同一概念。

例如：

```text
previous_close
tick_size
lot_size
board
ST status
suspension
instrument lifecycle
```

属于 Reference Authority。

不能默认：

```text
Market Bar
→ 推导全部 Reference
```

Reference 应：

* 版本化；
* 带 effective range；
* 可 fingerprint；
* 可追踪数据来源；
* 被 Product / Transaction proof 引用。

---

# 12. Market Rule

Market Rule 回答：

> **当前市场状态下，这笔订单是否合法？**

典型规则包括：

* Trading Session；
* Suspension；
* Supported Order Type；
* Side / Position Effect；
* Price Tick；
* Price Limit；
* Quantity Increment；
* Lot；
* Sellable Position；
* Available Cash；
* Margin；
* Settlement Schedule。

Market Rule 与 Execution Support 是两个 Authority。

```text
Market Rule
    → 是否允许交易

Execution Support
    → Kernel 是否实现这个 economic shape
```

二者不得混合。

---

# 13. Execution Support Authority

Execution Support 不根据市场名字判断能力。

它基于规范化经济语义：

```text
Operation Kind

Account Type

Order Type

Side

Offset

Position Side

Position Effect

Position Mode

Margin

Account/Ledger Parity

Reservation Shape
```

然后返回：

```text
DURABLE_...
或
UNSUPPORTED
```

如果 Kernel 没有正式支持某个经济 shape：

> **Fail Closed。**

不能 fallback 到 direct Manager mutation。

---

# 14. Broker Boundary

Broker 是外部事实来源，不是本地状态权威。

Broker Gateway：

* 不持有 Runtime Manager；
* 不直接修改 Account；
* 不直接修改 Position；
* 只负责发送命令、接收外部事实并标准化。

Inbound 方向：

```text
Broker
    ↓
Normalized Broker Update
    ↓
Runtime Inbound Queue
    ↓
Execution Processor
```

---

# 15. Durable Trading Kernel

正式经济生命周期使用：

```text
Broker Fact
      ↓
Immutable Planning Context
      ↓
Pure Planner
      ↓
Prepared Runtime Transaction
      ↓
Transaction Store Commit
      ↓
Runtime Sequence Gate
      ↓
Ordered Projection
      ↓
Projection Ready
      ↓
Durable Outbox
```

核心原则：

> **Commit Fact First, Project State Second.**

Transaction Store 是 durable operation authority。

Manager snapshot 是当前状态 Projection，而不是历史交易事实本身。

---

# 16. Projection 规则

Projection 必须：

```text
One Projection Component
        ↓
One Mutable Authority
```

Projection Target 只负责：

1. 读取当前状态；
2. 验证 expected version/hash；
3. 安装 Planner 已经计算完成的 after-state；
4. 验证 result hash。

Projection Target 不允许：

* 重新计算经济规则；
* 调用跨 Authority orchestration；
* 修改另一个 Manager；
* 隐式 reserve/release/consume；
* 创建新的业务事实。

---

# 17. Forward Recovery

OnlyAlpha 不使用跨 Manager rollback 恢复交易状态。

Recovery 模型：

```text
Committed Transaction
        ↓
检查 Projection progress
        ↓
找到第一个未完成 Projection
        ↓
继续向前安装
        ↓
Projection Ready
```

原则：

> **Historical Fact Immutable.**

已经 Durable Commit 的：

* Accepted；
* Trade；
* Terminal；
* Settlement；
* Fee Correction；

不能因为 Crash 被重新定义。

Recovery 只允许：

```text
Forward Recovery
```

---

# 18. Broker Lifecycle

规范化 Broker 生命周期至少包含：

```text
ACCEPTED
TRADE
CANCELLED
REJECTED
EXPIRED
```

正式支持的 economic shape 必须全部走 Durable Transaction。

例如：

```text
Broker ACCEPTED
    ↓
ORDER_ACCEPTED Transaction

Broker TRADE
    ↓
TRADE_FILL Transaction

Broker CANCELLED / REJECTED / EXPIRED
    ↓
ORDER_TERMINAL Transaction
```

不允许 direct multi-manager mutation fallback。

---

# 19. Partial / Multi-Fill

一个 Order 可以有：

```text
Fill #1
Fill #2
Fill #3
...
```

每个 Fill：

* 是独立 immutable Fact；
* 独立 Durable Commit；
* 消耗剩余 Reservation；
* 增量修改 Position / Allocation；
* 增量计算 Fee；
* 不修改历史 Fill。

例如：

```text
Order 1000

Fill 300
Fill 400
Fill 300
```

必须得到：

```text
Order filled:
300 → 700 → 1000

Remaining:
700 → 300 → 0
```

而不是等待最终 Fill 后一次性修改状态。

---

# 20. Terminal 语义

Partial Fill 后：

```text
Cancel / Reject / Expire
```

只能释放：

```text
remaining authority
```

不能 rollback 已成交部分。

例如：

```text
BUY 1000
Fill 300
Cancel 700
```

最终：

```text
300 Position
保留

700 Reservation
释放
```

这是整个交易内核的重要不变量。

---

# 21. Fee Authority

交易费用分为两个独立 Authority：

```text
Market Fee Pack
+
Broker Fee Contract
```

Market Fee 负责：

* Stamp Duty；
* Transfer Fee；
* Exchange-specific fee；
* Market rule based fee。

Broker Fee Contract 负责：

* Commission；
* Minimum Commission；
* Broker-specific charging rules。

二者不合并成一个市场专用 Fee Calculator。

完整链：

```text
Market Fee Pack
        +
Broker Fee Contract
        ↓
Order Binding
        ↓
Policy Resolution Proof
        ↓
Fee Assessment
        ↓
Order Fee Accrual
        ↓
Fee Application Ledger
```

---

# 22. Fee Reconciliation

本地 Fee Application 与外部 Broker Evidence 分离。

如果真实 Broker 返回：

```text
actual fee
```

与本地历史应用不一致：

不能修改历史 Fee Fact。

正确模型：

```text
Historical Fee
      ↓
Broker Evidence
      ↓
Reconciliation
      ↓
FEE_RECONCILIATION
Durable Operation
```

所有差额以新 Fact 表达。

---

# 23. Settlement

Settlement 是独立 Authority。

交易成交后，资产和资金何时变为：

```text
Trade Available
Withdrawable
Sellable
```

由 Market Rule 产生的 Settlement Instruction 决定。

例如 T+1：

```text
Day D BUY
    ↓
Position exists
but unsettled
    ↓
Day D+1
SETTLEMENT_MATURITY
    ↓
sellable
```

不能在 Execution 中：

```text
if A-share:
    T+1
```

---

# 24. MarketData

MarketData 与 Broker Execution 完全分离。

统一数据模型：

```text
Provider
    ↓
Normalized Bar / Tick
    ↓
Envelope Metadata
    ↓
MarketData Queue
    ↓
Processor
    ↓
Runtime Consumers
```

Realtime 与 Historical 应尽量使用相同 Domain Bar / Tick。

---

# 25. Historical 与 Realtime

Historical：

```text
Historical Provider
      ↓
Replay Service
      ↓
Backtest Clock
```

Realtime：

```text
Realtime Provider
      ↓
Inbound Queue
      ↓
Live Clock
```

只有 Historical Replay 可以主动推进 Backtest Clock。

外部 Provider 不能直接修改 Runtime 时间。

---

# 26. DataSource Plugin

DataSource 通过标准 Plugin API 接入。

Provider 可以实现：

```text
Historical Bars
Historical Ticks

Live Bars
Live Ticks

Reference Data
```

长期支持：

```text
Multiple Providers
Coverage Routing
Failover
Historical Recording
Realtime Recording
```

但 Runtime 不应直接依赖具体 SDK。

---

# 27. Broker Plugin

Broker Plugin 负责：

```text
Order submission
Cancel request
Broker query
Inbound update normalization
```

核心代码只能依赖：

```text
Broker Port / Plugin API
```

不能：

```text
import xtquant
```

到 Trading Core。

Virtual Broker 同样作为 Broker Plugin 使用，而不是 Core 特殊分支。

---

# 28. Virtual Broker

Virtual Broker 用于：

```text
Backtest
Sim
```

负责：

* deterministic matching；
* whole fill；
* partial fill；
* multi-fill；
* liquidity；
* slippage；
* Accepted；
* Reject；
* Cancel；
* Expire；
* checkpointable execution state。

Backtest 和 Sim 应尽可能共用 Virtual Broker 核心语义。

---

# 29. Determinism

OnlyAlpha 将确定性视为产品能力。

同一：

```text
Configuration
Dataset
Reference
Market Rule Version
Fee Authority
Broker Simulation
```

必须产生相同：

```text
Transaction Identity

Broker Fact Identity

Economic State

Result Fingerprint

Artifact Fingerprint
```

任何进入 Runtime Identity 的 Authority 必须具有稳定 canonical representation。

未知 canonical type 应：

```text
Fail Closed
```

不能依赖不稳定的对象字符串表示。

---

# 30. Persistence

Persistence 是 Runtime 基础设施，不是经济语义 Authority。

目标：

```text
Memory
SQLite
Future Storage
```

在同一经济输入下产生一致结果。

持久化至少覆盖：

* Runtime transaction；
* Projection progress；
* Broker execution state；
* Position；
* Account；
* Ledger；
* Settlement；
* Reservation；
* Recovery checkpoint；
* deterministic cursor。

---

# 31. Checkpoint / Restart

Long-running 与复杂 Backtest Runtime 必须支持：

```text
Checkpoint
    ↓
Process Exit
    ↓
New Process / New Engine
    ↓
Restore
    ↓
Forward Recovery
    ↓
Continue
```

禁止把：

```text
同一个 Python Runtime Object
```

重新拿回来称为 Recovery。

真正 Recovery 必须能够由新 Runtime 实例完成。

---

# 32. Result / Analytics / Artifact

业务 Runtime 结束后：

```text
Runtime
    ↓
Canonical Result
    ↓
Analytics
    ↓
Artifact
    ↓
Report / Web
```

Collector 只能读取正式 Query/Audit。

Collector：

* 不执行 Command；
* 不修改 Manager；
* 不访问 Broker 重新构造历史；
* 不拼接 mutable final state 假装逐笔交易历史。

---

# 33. Research Artifact 与 Web

Research Runtime 应生成面向分析的标准结果：

```text
Research Result
├── Dataset Metadata
├── Instrument
├── Time Range
├── K-Line Series
├── Indicator Series
├── Factor Series
├── Feature Series
├── Signal Series
├── Forward Return
├── Parameter Grid
├── Statistics
└── Fingerprint
```

Web：

```text
Research Artifact
        ↓
Query / API
        ↓
Browser
```

Web 不直接访问 Runtime Manager。

---

# 34. 推荐研究工作流

```text
Historical Data
      ↓
Research
      ↓
Vectorized Parameter Search
      ↓
Web Analysis
      ↓
Candidate Parameters
      ↓
Backtest
      ↓
Full Trading Validation
      ↓
Sim
      ↓
Realtime Validation
      ↓
Live
```

即：

```text
Research
    快速筛选

Backtest
    精确验证

Sim
    实时验证

Live
    真实执行
```

这是产品能力关系和推荐验证路径，不是要求所有策略依次经过每个 Runtime 的强制发布状态机。

---

# 35. 时间模型

绝对时间统一使用：

```text
UTC
```

市场语义由：

```text
Venue
TimeZone
TradingCalendar
TradingDay
TradingSession
```

解释。

原则：

```text
Storage
Domain
Runtime Facts
Transaction
    → UTC

Market presentation
    → Market TimeZone

User display
    → User Local Time
```

Domain 不依赖 UI 时区。

---

# 36. 公共 API 边界

外部使用者应通过稳定入口：

```text
OnlyEngine
Config Models
Domain Models
Strategy / Factor / Indicator interfaces
Plugin API
Result DTO
```

内部实现包括：

```text
Runtime Planner
Runtime Assembly Plan
Assembler
Session
Infrastructure Registry
Manager
Execution Processor
Transaction Coordinator internals
```

不作为外部兼容 API。

Alpha 阶段：

> **架构正确性优先于旧接口兼容性。**

无职责旧接口直接删除，不保留 deprecated alias 或 compatibility wrapper。

---

# 37. 扩展规则

## 新增 Strategy

增加：

```text
Strategy / Factor / Indicator plugin
```

不修改 Runtime Core。

---

## 新增 Data Provider

实现：

```text
DataSource Plugin API
```

不修改 Strategy。

---

## 新增 Broker

实现：

```text
Broker Plugin API
```

不修改 Execution Core。

---

## 新增市场

增加：

```text
Market Product Composition
Reference Authority
Market Rule Compiler
Fee Authority
```

不修改：

```text
Engine
Strategy Framework
Execution Kernel
Transaction Kernel
```

---

## 新增资产类别

增加：

```text
Instrument type
Market semantics
Valuation
Risk semantics
Execution capability
```

不能通过全局 `if FUTURES` 扩散实现。

---

# 38. 明确禁止的架构模式

OnlyAlpha 不接受以下长期模式：

```text
if market == CN_A_SHARE in Execution

if runtime == LIVE in Strategy

AshareTradePlanner

SimOrderManager

BacktestPositionManager

LiveAccountManager

Strategy 自己维护账户副本

Broker 直接写 Position

Projection Target 修改多个 Authority

Recovery rollback 多个 Manager

未知经济 shape 走 direct fallback

Test-only production compatibility API

legacy / old / deprecated wrapper 长期保留
```

---

# 39. Runtime Vocabulary

目标 Runtime 只保留：

```text
RESEARCH
BACKTEST
SIM
LIVE
```

不保留：

```text
PAPER
SHADOW Runtime
```

其中 Shadow 如果仍有价值，只能作为内部：

```text
Execution Capability
```

而不是正式 Runtime Product。

当前源码仍含 `PAPER` 和 standalone `SHADOW` spelling：前者是 Sim 的 streaming migration source，后者是待删除的 unsupported Factory。它们是实现债务，不是 public compatibility promise；迁移不保留 alias 或 wrapper。

---

# 40. Finite 与 Streaming Runtime

目标 Runtime 生命周期进一步分成两个族：

## Finite

```text
RESEARCH
BACKTEST
```

典型：

```text
engine.run()
```

存在明确结束条件。

当前 `OnlyEngine.run()` 仍只支持有限 `BACKTEST`；Research Job 的正式产品入口尚未实现，不能由上述目标生命周期推断为可用。

---

## Streaming

```text
SIM
LIVE
```

典型：

```text
engine.initialize()
engine.start()
engine.wait()
engine.stop()
engine.close()
```

需要处理：

* reconnect；
* gap recovery；
* watermark；
* checkpoint；
* restart；
* long-running operation。

---

# 41. Current Runtime Migration State

| Runtime / source spelling | 当前事实 | 目标处理 |
|---|---|---|
| `BACKTEST` | 已实现，是当前 primary Runtime | 保留 event-driven + Virtual Broker + full Trading Kernel |
| `PAPER` | 已实现受限 streaming/observation + Shadow execution | 迁移 useful streaming infrastructure 到 Sim 后删除 |
| standalone `SHADOW` | Factory unsupported | 非目标 Runtime，迁移后删除 |
| `SIM` | 当前 enum、配置和 Factory 均不存在 | P6 接入 Virtual Broker 与完整 Trading Kernel |
| `RESEARCH` | Factory unsupported | P7 实现 vectorized Research Job/Result/Artifact workflow |
| `LIVE` | Factory unsupported | P8/P9 补齐 Broker durability、同步、恢复和运维 |

当前 `PAPER` 已具备 Historical/Open-Market Bootstrap、Historical-to-Live handoff、watermark、realtime queue、aggregation、warmup/observation、Strategy intent、Shadow suppression、Reservation create/release 和 ordered shutdown，并完成当前 Profile 下的真实 MiniQMT 验收。它仍只是 read-only market observation + Shadow execution，不具备 reconnect、realtime gap recovery、streaming checkpoint/recovery、Real Broker submission/synchronization 或长期生产闭环。

Runtime mode 中立化也尚未全仓完成：当前 Position authority、Fee finality 和 compiled Market Rule identity 仍有历史 mode 分支，`OnlyRuntimeContext` 也仍暴露 `mode`。Durable Execution Capability Resolver 已 mode-neutral；其余分支和暴露面是后续迁移债务，不能作为新增 Runtime-specific economics 的先例。

## 当前 Alpha 产品能力

OnlyAlpha 当前处于 **Alpha** 阶段。

当前重点不是扩大功能数量，而是持续收紧：

```text
Authority
Determinism
Runtime Boundary
Market Neutrality
Recovery
Product Conformance
```

已经建立的核心能力包括：

* 模块化单体架构；
* Engine / Runtime / Cluster 生命周期；
* Strategy / Factor / Indicator 分层；
* Trading Runtime-owned authority；
* Market Rule；
* Risk；
* Order / Reservation；
* Position / Allocation；
* Account / Strategy Ledger；
* Market Fee / Broker Fee；
* Durable Accepted / Trade / Terminal；
* Partial / Multi-Fill；
* Settlement；
* Prepared Transaction；
* Ordered Projection；
* Forward Recovery；
* Memory / SQLite；
* Checkpoint / Restart；
* Result / Analytics / Artifact；
* Plugin DataSource / Broker；
* CN A-share 有限 Durable Backtest Product Conformance。

---

# 42. 当前认证产品

当前已经认证的有限产品合同：

```text
CN_A_SHARE_DURABLE_BACKTEST_V1
```

覆盖有限的普通中国 A 股 Cash-Long Backtest surface。

认证不意味着：

```text
完整 CN_A_SHARE_CASH Profile 已稳定

所有中国股票规则已支持

ETF / Convertible Bond / BSE 已支持

Margin / Short 已支持

Sim 已生产完成

Live 已生产完成
```

产品认证范围必须等于实际 Conformance 范围。

---

# 43. 当前主要工程演进方向

后续阶段按同一 taxonomy 迁移：

```text
P5  Market Product Composition Authority Neutralization

P6  Sim Streaming Runtime Closure
    PAPER streaming infrastructure
    → Virtual Broker + Full Trading Kernel
    → gap/reconnect/checkpoint/restart
    → delete PAPER and standalone SHADOW

P7  Vectorized Research Runtime
    + Research Artifact
    + Web Research Boundary

P8  Durable Broker Outbound Command
    + Broker Synchronization / Reconciliation

P9  Live Runtime Foundation
```

详细迁移范围和非目标见 [Roadmap](docs/roadmap.md)。

---

# 44. 项目原则总结

OnlyAlpha 长期坚持以下规则：

```text
One Engine

Multiple Runtime

Trading Runtime
→ Multiple Isolated Cluster

Research Runtime
→ Research Job / Plan

One Domain
→ One Write Authority

Planner Calculates
Projection Installs

Commit Fact First
Project State Second

Historical Fact Immutable

Forward Recovery Only

Market Identity Is Evidence
Not Execution Permission

Research Optimizes Speed

Backtest Optimizes Trading Fidelity

Backtest / Sim / Live
Share Trading Semantics

Runtime Difference
Belongs to Driver Layer

Runtime Type
Is Not Execution Permission

Unsupported
→ Fail Closed

No Obsolete Compatibility Layer
```

最终目标不是构造一个拥有最多功能的量化框架，而是构造一个：

> **行为可解释、状态有唯一真值、交易历史可审计、故障后可恢复、回测与实时交易语义一致，并能够持续扩展到不同市场和运行环境的量化交易工程。**
