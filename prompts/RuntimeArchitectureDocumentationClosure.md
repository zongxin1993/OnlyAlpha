你正在维护 OnlyAlpha：

Repository:
`https://github.com/zongxin1993/OnlyAlpha`

本任务是一个**完整、不可拆分的架构文档收口任务**。

# 任务名称

**Runtime Architecture Documentation Closure**

目标是从第一性原理重新审查当前仓库的 Runtime 架构定义，并将：

* `README.md`
* `AGENTS.md`
* `docs/architecture.md`
* `docs/roadmap.md`
* `docs/adr/`

统一到同一个长期架构模型和工程规则下。

本任务不是简单文字替换，也不是把 `PAPER` 改名成 `SIM`。

必须首先重新阅读当前 `master` 的源码、测试、文档和 ADR，理解当前实现事实与目标架构之间的区别，然后建立明确的：

```text
Current Implementation
        ↓
Target Architecture
        ↓
ADR Decision
        ↓
Engineering Contract
        ↓
Roadmap Migration
```

最终必须消除文档之间互相矛盾、Authority 不明确、Runtime vocabulary 漂移、Research 与 Trading Runtime 边界模糊等问题。

---

# 一、必须从第一性原理出发

不要从：

```text
当前已经有哪些 class
当前 enum 里有哪些值
当前 factory 注册了哪些 runtime
```

反推出未来产品模型。

应该先回答：

```text
OnlyAlpha 为什么需要不同 Runtime？

哪些 Runtime 承担交易语义？

哪些 Runtime 只承担研究计算？

历史数据与实时数据的边界是什么？

Virtual Broker 与 Real Broker 的边界是什么？

什么必须在 Backtest / Sim / Live 中保持一致？

什么允许因 Runtime Driver 不同而变化？

Research 为什么不能被强迫进入 Trading Kernel？

Cluster 到底属于整个 Runtime 抽象，还是 Trading Runtime workload？

哪些东西属于当前实现债务，而不是长期兼容合同？
```

所有文档修改必须建立在这些问题的明确答案上。

---

# 二、正式冻结 OnlyAlpha Runtime Product Taxonomy

OnlyAlpha 长期只允许四种正式 Runtime：

```text
RESEARCH
BACKTEST
SIM
LIVE
```

这是目标产品模型。

禁止继续把以下内容描述为正式长期 Runtime：

```text
PAPER
SHADOW
```

但必须诚实区分：

```text
Target Architecture
```

与：

```text
Current Source Implementation
```

当前源码中仍存在的 `PAPER` / `SHADOW`：

```text
是 migration debt
不是长期兼容合同
不是第五、第六种正式 Runtime
```

本任务不允许为了让文档“看起来一致”而谎称源码已经完成 `SIM`。

必须明确写清：

```text
当前 BACKTEST 已正式实现。

当前 PAPER 保存了一部分未来 SIM 需要的
Realtime / Streaming 基础设施。

PAPER 后续将迁移为 SIM。

Standalone SHADOW 后续退出 Runtime vocabulary。

RESEARCH / LIVE 当前仍处于未完整产品化状态，
具体状态以源码、正式测试和产品认证为准。
```

---

# 三、四种 Runtime 的正式语义

必须在 ADR、README、architecture、AGENTS 中形成一致定义。

## RESEARCH

```text
Data:
Historical

Execution:
Vectorized / Batch

Trading:
No formal trading execution

Broker:
None

Account:
No formal trading Account authority

Purpose:
Fast quantitative research
K-Line analysis
Indicator
Factor
Feature
Parameter Sweep
Statistics
Research Artifact
Web visualization
```

核心原则：

> Research 为研究效率服务。

Research 不承担：

```text
Order lifecycle
Broker lifecycle
Risk reservation
Trading Position authority
Trading Account authority
Durable Broker Fact
Trading Transaction Projection
```

Research 可以复用：

```text
Market Data Domain
Instrument
Reference
Calendar
Indicator definitions
Factor definitions
canonical data model
```

但不能为了“代码复用”被强迫经过：

```text
Order
Broker
ExecutionProcessor
Trading Account
Trading Position
Durable Trading Transaction
```

---

## BACKTEST

```text
Data:
Historical

Execution:
Event Driven

Clock:
Backtest Clock

Broker:
Virtual Broker

Account:
Local Virtual Trading Account

Purpose:
High-fidelity historical trading validation
```

Backtest 的首要目标不是最大吞吐量。

它的首要目标是：

> 与 Sim / Live 保持 Trading Semantic Equivalence。

因此正式 Backtest 不允许被向量化交易近似替代。

以下链路必须继续走正式交易语义：

```text
MarketData
→ Indicator / Factor
→ Strategy
→ Market Rule
→ Risk
→ Order
→ Reservation
→ Virtual Broker
→ Accepted / Trade / Terminal
→ Durable Transaction
→ Position
→ Allocation
→ Account
→ Ledger
→ Fee
→ Settlement
→ Result
```

禁止把类似：

```python
position = signal.shift(1)
returns = position * close.pct_change()
```

称为正式 OnlyAlpha Backtest Trading Engine。

这种计算属于 Research。

---

## SIM

```text
Data:
Realtime

Execution:
Event Driven

Clock:
Live Clock

Broker:
Local Virtual Broker

Account:
Local Virtual Trading Account

Purpose:
Realtime simulated trading
```

SIM 必须：

```text
使用实时行情
运行完整 Strategy
运行完整 Market Rule
运行完整 Risk
产生正式 Order
进入 Virtual Broker
产生 Accepted / Trade / Terminal
运行完整 Durable Trading Kernel
形成 Position / Account / Fee / Settlement / PnL
```

SIM 绝不能：

```text
向真实 Broker 发送订单
依赖真实资金产生交易结果
```

SIM 不是 Shadow。

---

## LIVE

```text
Data:
Realtime

Execution:
Event Driven

Clock:
Live Clock

Broker:
Real Broker

Account:
Real Broker + Local Canonical Trading State

Purpose:
Production live trading
```

LIVE 在 SIM 基础上增加：

```text
Durable Broker Outbound Command
Broker Idempotency
ACK / Reject / Unknown
Reconnect
Broker Query
Broker Synchronization
Order / Trade / Position / Account reconciliation
Long-running recovery
Production operations
```

---

# 四、正式冻结 Trading Runtime 与 Research Runtime 的差异

禁止再使用：

```text
所有 Runtime 都必须拥有相同 Manager
```

这种错误抽象。

正式模型：

```text
OnlyEngine
│
├── Research Runtime
│     └── Research Job / Research Plan
│
└── Trading Runtime
      ├── Backtest
      ├── Sim
      └── Live
            ↓
          Cluster
```

Trading Runtime：

```text
BACKTEST
SIM
LIVE
```

才拥有正式 mutable trading authorities，例如：

```text
Order Authority
Position Authority
Allocation Authority
Account Authority
Strategy Ledger
Risk Authority
Reservation Authorities
Settlement Authority
Fee Authorities
Execution Processor
Runtime Transaction Store
Applied Projection Ledger
Outbox
```

Research Runtime 不得为了满足父类或形式统一而创建没有业务意义的 Trading Manager。

这是必须进入架构文档和 AGENTS 的正式约束。

---

# 五、重新定义 Engine / Runtime / Cluster 边界

长期顶层模型应表达为：

```text
OnlyEngine
│
├── Research Runtime
│     ├── Research Job A
│     └── Research Job B
│
├── Backtest Runtime
│     ├── Cluster A
│     └── Cluster B
│
├── Sim Runtime
│     └── Cluster C
│
└── Live Runtime
      └── Cluster D
```

其中：

## Engine

Engine 负责：

```text
Product lifecycle
Runtime planning
Runtime grouping
Composition
Shared infrastructure
Resource ownership/refcount
Session
Result aggregation
Artifact aggregation
```

Engine 不拥有交易经济状态。

---

## Trading Runtime

Trading Runtime 是：

> mutable trading authority owner

---

## Cluster

Cluster 是：

```text
One Strategy
+
Zero or more Factors
+
Indicators
+
Subscription Scope
+
Strategy Ledger Scope
```

Cluster 不：

```text
拥有 Account Manager
拥有 Position Manager
拥有 Broker
直接推进 Clock
直接修改 Runtime state
```

---

## Research Job

Research Job 是研究任务，不应该伪装成交易 Cluster。

它可以包含：

```text
Dataset
Universe
Time Range
Indicator definitions
Factor definitions
Feature definitions
Parameter Grid
Statistics specification
Output specification
```

不要在本任务中为了 Research Job 提前创建生产代码框架。

本任务只冻结边界。

---

# 六、Backtest / Sim / Live 的核心不变量

必须正式记录：

> Backtest / Sim / Live 追求 Trading Semantic Equivalence，而不是 Driver Implementation Equivalence。

允许不同的只有主要外围 Driver：

```text
                 BACKTEST       SIM             LIVE

Data             Historical     Realtime        Realtime

Clock            Backtest       Live            Live

Broker           Virtual        Virtual         Real

Lifecycle        Finite         Streaming       Streaming
```

必须尽可能共享：

```text
Strategy
Market Rule
Risk
Order
Reservation
Execution Support
Execution Processor
Transaction Kernel
Position
Allocation
Account
Strategy Ledger
Fee
Settlement
Result semantics
Recovery semantics
```

禁止：

```python
if runtime == "BACKTEST":
    economic_logic_a()
elif runtime == "SIM":
    economic_logic_b()
elif runtime == "LIVE":
    economic_logic_c()
```

Runtime Mode 不能成为经济权限或交易业务规则 Authority。

---

# 七、正式冻结 Runtime Type != Execution Permission

必须在 AGENTS / ADR 中增加以下不变量：

```text
Runtime Type
≠
Execution Permission
```

例如：

```text
SIM
```

不应该在 Execution Kernel 内意味着某种特殊经济行为。

Runtime 负责选择：

```text
Clock Driver
MarketData Driver
Broker Adapter
Lifecycle Driver
```

进入 Trading Kernel 后应该消费：

```text
normalized domain input
normalized broker facts
market instructions
economic context
```

而不是：

```text
runtime name
```

---

# 八、正式冻结 PAPER 的处理原则

不要新增：

```text
PAPER + SIM
```

两条长期产品路径。

当前 PAPER 应被定义为：

> 当前源码中的 Legacy Streaming Implementation / SIM Migration Source。

其已有能力可能包括：

```text
LiveClock
Historical Bootstrap
Open-Market Bootstrap
Historical → Live Handoff
Realtime MarketData Queue
Aggregation
Warmup
Observation
Streaming lifecycle
```

这些能力后续迁移给 SIM。

而：

```text
Shadow execution
```

应被 Virtual Broker + Full Trading Kernel 替代。

迁移目标：

```text
Current PAPER
      ↓
retain useful streaming infrastructure
      ↓
replace Shadow execution
      ↓
Virtual Broker
      ↓
Full Trading Kernel
      ↓
SIM
      ↓
delete PAPER Runtime
```

本任务不实施这个源码迁移。

只冻结架构方向。

---

# 九、正式冻结 SHADOW 的处理原则

Standalone SHADOW 不再属于 Runtime Product。

长期禁止：

```text
OnlyShadowRuntime
```

成为正式产品方向。

如果 Shadow 语义未来仍有价值，只允许作为：

```text
internal execution capability
```

而不是 Runtime。

本任务不要求立即删除当前源码中的 Shadow Factory。

当前源码应被准确描述为：

```text
implementation debt pending Runtime migration
```

不能在 README/architecture/roadmap 中继续当长期产品宣传。

---

# 十、Research 与 Vectorization 的正式规则

必须彻底结束：

```text
Vectorized Backtest
```

作为长期架构方向。

向量化属于：

```text
RESEARCH
```

正式 BACKTEST 保持：

```text
Event Driven
+
Full Trading Kernel
```

未来如果需要提高 Backtest 总吞吐量，允许：

```text
Distributed Backtest
=
Parallel execution of multiple complete
event-driven backtest jobs
```

禁止：

```text
Distributed Backtest
=
replace canonical trading semantics
with vectorized approximation
```

---

# 十一、Research → Backtest → Sim → Live 的产品工作流

应在 README / architecture 中形成明确关系：

```text
Historical Data
      ↓
Research Runtime
      ↓
Vectorized Research
      ↓
Parameter / Factor Candidates
      ↓
Backtest Runtime
      ↓
Full Trading Validation
      ↓
Sim Runtime
      ↓
Realtime Validation
      ↓
Live Runtime
```

核心含义：

```text
Research
    快速筛选

Backtest
    精确历史交易验证

Sim
    实时虚拟交易验证

Live
    真实执行
```

不要把它表达成强制发布流程。

这是产品能力关系，而不是所有策略必须经过的工作流状态机。

---

# 十二、本任务必须新增 ADR 0068

如果当前仓库 ADR 最大编号已经超过 0067，则使用**当前下一个可用连续编号**，不要制造编号冲突。

建议名称：

```text
docs/adr/0068-runtime-product-taxonomy-and-trading-semantic-equivalence.md
```

标题：

```text
ADR 0068:
Runtime Product Taxonomy and Trading Semantic Equivalence
```

ADR 状态：

```text
Accepted
```

ADR 必须完整包含：

```text
Context
Decision
Runtime Taxonomy
Research Boundary
Trading Runtime Boundary
Backtest / Sim / Live Semantic Equivalence
Finite vs Streaming Lifecycle
Cluster vs Research Job
Paper Migration
Shadow Boundary
Vectorization Boundary
Rejected Alternatives
Consequences
Migration Notes
Validation / Architecture Guards
Superseded / Clarified ADR references
```

---

# 十三、ADR 0068 必须明确拒绝这些方案

至少明确拒绝：

```text
1. 保留 PAPER 作为第五种长期 Runtime

2. 保留 Standalone SHADOW Runtime

3. PAPER 仅重命名为 SIM 但保留旧语义

4. 新建一套与 Backtest 不共享 Kernel 的 Sim Trading Engine

5. 新建 SimOrderManager / SimPositionManager /
   LiveOrderManager / BacktestAccountManager 等 Runtime 专用经济真值

6. Strategy 根据 Runtime Mode 编写不同交易逻辑

7. Execution 根据 Runtime Mode 决定经济支持

8. Research 为了复用 Trading Runtime 强制创建
   Account / Position / Broker / Transaction Manager

9. 将正式 Backtest 改成 Vectorized Trading Approximation

10. 为旧 PAPER / SHADOW 保留 compatibility aliases
    作为长期 public API
```

---

# 十四、旧 ADR 的处理原则

ADR 是历史决策记录。

禁止为了当前架构好看而重写历史。

采取：

```text
historical content remains immutable
+
small superseded / clarified metadata note
```

原则。

至少审查：

```text
ADR 0001
ADR 0019
ADR 0020
ADR 0021
ADR 0026
ADR 0064
ADR 0067
```

---

## ADR 0001

保留：

```text
Engine → Runtime → workload
```

总体思想。

但增加说明：

```text
Clarified / Superseded in part by ADR 0068

Trading Runtime uses Cluster workload.

Research Runtime is not required
to own trading Cluster workloads.
```

---

## ADR 0019

如果已经被 0021 Superseded：

保持历史。

不要为了 Runtime taxonomy 再重写。

---

## ADR 0020

保留 Cluster / Strategy / Factor / Indicator 决策。

增加 clarification：

```text
ADR 0068 clarifies that this is primarily
the Trading Runtime workload model.

Research may reuse pure Indicator / Factor definitions
without being forced through Strategy / Cluster trading semantics.
```

---

## ADR 0021

产品入口、Engine、Cluster Config 等有效决定继续保留。

Runtime vocabulary 部分增加：

```text
Runtime taxonomy superseded in part by ADR 0068.
```

不要篡改历史正文。

---

## ADR 0026

统一 Market Rule 决策继续保持 Accepted。

它的核心原则：

```text
one unified Market Rule semantic
```

继续有效。

只将：

```text
Backtest / Paper / Live / Shadow
```

这种旧 Runtime vocabulary 标记为被 ADR 0068 部分替代。

新的 Trading Runtime vocabulary：

```text
BACKTEST
SIM
LIVE
```

Research 不承担正式交易 Market Rule lifecycle。

---

## ADR 0064

不要修改历史 Scope 决策。

如果需要，仅添加历史注释，说明后续产品状态由新 ADR 或 ADR 0067 改变。

禁止把当时正确的历史背景重新伪造成今天写的内容。

---

## ADR 0067

CN A-share Durable Backtest Product 认证继续有效。

不得因为 Runtime taxonomy 更新而破坏：

```text
CN_A_SHARE_DURABLE_BACKTEST_V1
```

认证语义。

---

# 十五、README.md 修改要求

README 当前大方向正确，不要重新写成宣传文案。

只做架构精化和 current/target 区分。

至少完成以下修改。

---

## 1. Runtime Authority 表述

不要写：

```text
Runtime 是所有可变交易 Authority 的拥有者
```

改为：

```text
Trading Runtime（Backtest / Sim / Live）
是 mutable trading authorities 的所有者。
```

Research Runtime 单独说明：

```text
Research Runtime owns research execution state,
dataset state, calculation state, result and artifact state.

It does not create formal trading authorities
only for structural symmetry.
```

---

## 2. Engine / Runtime / Cluster 图

更新为 Research Job 与 Trading Cluster 分离的模型。

---

## 3. 当前迁移状态

增加简洁 section：

```text
Current Runtime Migration State
```

明确：

```text
BACKTEST:
implemented / primary product

PAPER:
legacy streaming implementation,
future SIM migration source

SHADOW:
not target Runtime

SIM:
target Runtime, not yet fully migrated

RESEARCH:
target Runtime, current production workflow incomplete

LIVE:
target Runtime, current production runtime incomplete
```

具体措辞必须以当前源码和测试事实校验，不允许夸大。

---

# 十六、AGENTS.md 修改要求

这是本任务最重要的文件之一。

AGENTS 是工程执行合同。

必须让未来 Codex 无法再误判 Runtime 架构。

至少增加/修改：

```text
Allowed target Runtime vocabulary:
RESEARCH
BACKTEST
SIM
LIVE
```

明确：

```text
PAPER and standalone SHADOW
are not target product runtimes.
```

明确：

```text
Existing PAPER/SHADOW source code
is migration debt,
not a compatibility contract.
```

必须增加以下架构门禁规则：

```text
1. Do not introduce new PAPER Runtime dependencies.

2. Do not introduce new standalone SHADOW Runtime dependencies.

3. Formal Backtest remains event-driven.

4. Vectorized execution belongs to Research only.

5. Strategy must not branch on Runtime type.

6. Trading economics must not branch on Runtime type.

7. BACKTEST / SIM / LIVE share one trading semantic core.

8. SIM must never submit to a real Broker.

9. RESEARCH must not instantiate Trading Authorities
   only to satisfy a shared Runtime abstraction.

10. Runtime differences belong primarily to:
    Clock
    MarketData Driver
    Broker Adapter
    Lifecycle Driver

11. Runtime Type is not Execution Permission.

12. Do not create runtime-specific duplicate economic authorities.

13. No compatibility alias should preserve PAPER / SHADOW
    as long-term public runtime vocabulary.
```

---

# 十七、AGENTS 当前产品事实必须更新

必须区分：

```text
Current implementation facts
```

和：

```text
Target architecture contract
```

不能把未来 SIM 写成已经完成。

也不能继续把 PAPER 描述成长期产品。

当前 PAPER 章节应改成类似：

```text
Legacy Streaming / SIM Migration Baseline
```

或者等价的准确名称。

其中保存当前真正实现的 streaming 能力和当前缺口。

---

# 十八、docs/architecture.md 必须重构

architecture.md 必须成为：

> Current Architecture Living Document

而不是：

> 历史阶段总结集合。

删除或迁出明显属于历史阶段叙事的：

```text
M1
PR4.3.2
PR4.3.3
阶段完成记录
历史任务编号
```

除非它们解释当前架构不可替代的原因。

这些历史应由：

```text
ADR
docs/reports
git history
```

负责。

---

# 十九、architecture.md 推荐结构

重构后建议至少包括：

```text
1. Architecture Principles

2. Engine / Runtime Model

3. Runtime Product Taxonomy

4. Research Runtime

5. Trading Runtime

6. Cluster / Strategy / Factor / Indicator

7. Runtime Environment Composition

8. Market Product Composition

9. MarketData Boundary

10. Broker Boundary

11. Order / Risk / Reservation

12. Durable Execution Kernel

13. Transaction / Projection

14. Authority Ownership

15. Persistence / Checkpoint / Recovery

16. Result / Analytics / Artifact

17. Plugin Boundaries

18. Public vs Internal API

19. Dependency Direction

20. Current Product Capability Boundary
```

不要为了追求编号完全一致而保留旧结构。

应以当前架构的清晰度为第一目标。

---

# 二十、architecture.md 状态 Authority 必须更新

旧式：

```text
Trade Repository
Position Manager
Account Manager
...
```

不足以描述当前系统。

应表达正式 Authority：

```text
Runtime Transaction History
→ Transaction Store

Projection Progress
→ Applied Projection Ledger

Order
→ Order Authority

Position
→ Position Authority

Cluster Attribution
→ Allocation Authority

Account
→ Account Authority

Strategy Capital
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

遵守：

```text
One Domain → One Write Authority
```

---

# 二十一、docs/roadmap.md 必须更新

当前 P4.3 已完成的事实保留。

当前 P5：

```text
Market Product Composition Authority Neutralization
```

继续保持。

后续 Roadmap 应调整为类似：

```text
P5
Market Product Composition Authority Neutralization

P6
Sim Streaming Runtime Closure

P7
Vectorized Research Runtime
+ Research Artifact
+ Web Research Boundary

P8
Durable Broker Outbound Command
+ Broker Synchronization

P9
Live Runtime Foundation
```

后续再考虑：

```text
Multi-account
Multi-broker
Multi-data-source
More A-share products
Futures
Crypto
Distributed Research
Distributed Event-driven Backtest
```

---

# 二十二、P6 的语义必须明确

P6 不是新增一套 Sim 系统。

它应该主要完成：

```text
Current PAPER Streaming Infrastructure
        ↓
migrate / clean
        ↓
SIM Runtime
```

包括：

```text
Realtime MarketData
LiveClock
Historical bootstrap where needed
Historical → realtime handoff
Watermark
Gap detection
Gap recovery
Reconnect
Streaming checkpoint
Restart
Virtual Broker
Full Trading Kernel
```

完成后：

```text
delete PAPER Runtime
delete standalone SHADOW Runtime
```

不保兼容 wrapper。

---

# 二十三、P7 Research 的语义必须明确

P7 不叫：

```text
Vectorized Backtest
```

而叫：

```text
Vectorized Research Runtime
```

核心：

```text
Historical Dataset
→ Vectorized Indicator
→ Factor / Feature
→ Parameter Sweep
→ Statistics
→ Research Result
→ Research Artifact
→ Web Query / Visualization
```

Research 与 Web 的边界：

```text
Research Runtime
        ↓
Immutable Research Result / Artifact
        ↓
Query / API
        ↓
Web
```

禁止 Web 直接操纵 Runtime internal mutable managers。

---

# 二十四、必须审查文档中的 Runtime vocabulary

完成修改后，对整个仓库文档搜索：

```text
PAPER
Paper
SHADOW
Shadow Runtime
Vectorized Backtest
Backtest/Paper
Paper/Live
```

逐个判断。

不是机械删除全部历史出现。

分类：

```text
A. Current architecture
   → 必须改

B. Roadmap target
   → 必须改

C. AGENTS engineering contract
   → 必须改

D. Historical ADR
   → 可以保留，但应由 Superseded/Clarified note 解释

E. Historical reports
   → 可保留原文
```

禁止全仓无脑 search-and-replace。

---

# 二十五、源码处理边界

本任务是：

```text
Architecture Documentation Closure
```

不是：

```text
Runtime Source Migration
```

因此默认不要修改：

```text
OnlyRuntimeMode
OnlyPaperRuntimeFactory
OnlyShadowRuntimeFactory
OnlyResearchRuntimeFactory
OnlyLiveRuntimeFactory
Runtime factory registration
production runtime behavior
```

除非发现纯文档引用或静态 metadata 必须同步且不会改变运行行为。

不要提前实现 SIM。

不要提前删除 PAPER 源码。

不要借文档任务重构 Kernel。

真正 Runtime migration 属于后续正式阶段。

---

# 二十六、禁止引入兼容层

即使本任务主要是文档，也必须冻结：

```text
PAPER → SIM alias
SHADOW → SIM alias
deprecated runtime spelling
legacy runtime wrapper
```

不是未来解决方案。

后续迁移时应该：

```text
migrate
update config
update tests
delete obsolete interface
```

而不是长期兼容。

---

# 二十七、必须保护现有核心架构

本任务绝不能推翻已经正确建立的：

```text
One Engine
Multiple Runtime

Runtime-owned mutable trading authority

One Domain → One Write Authority

Market-neutral Execution

Market Identity Is Evidence,
Not Permission

Prepared Transaction

Durable Commit

Ordered Projection

One Projection Component
→ One Mutable Authority

Historical Fact Immutable

Forward Recovery Only

Fail Closed

Virtual Broker as Plugin

Market Rule Authority
!=
Execution Support Authority

Production Product Certification
!=
Whole Market Profile Stability
```

Runtime taxonomy 收口必须建立在这些架构之上。

不是重新设计交易内核。

---

# 二十八、文档 Authority 顺序也要明确

更新后保证：

```text
Current executable source
        ↓
Formal tests / architecture gates
        ↓
Accepted non-superseded ADR
        ↓
AGENTS.md
        ↓
Current architecture docs
        ↓
README
        ↓
Roadmap
        ↓
Historical reports/prompts
```

README 负责：

```text
工程机制
核心规则
长期产品模型
能力说明
```

ADR 负责：

```text
为什么做这个决定
哪些替代方案被拒绝
什么被 supersede
```

AGENTS 负责：

```text
开发时必须遵守什么
```

architecture 负责：

```text
现在系统怎么组织
```

roadmap 负责：

```text
从当前实现如何迁移到目标架构
```

不要让五份文档重复维护不同版本的事实。

---

# 二十九、文档质量要求

所有新增或修改文档必须：

```text
专业
准确
简洁
架构优先
机制优先
规则优先
少宣传
少口号
少历史流水账
```

术语统一。

同一概念只能有一个正式名字。

例如统一：

```text
Research Runtime
Trading Runtime
Backtest Runtime
Sim Runtime
Live Runtime
Trading Semantic Equivalence
Research Job
Cluster
Virtual Broker
Real Broker
```

不要混用：

```text
Paper Trading
Paper Runtime
Sim Mode
Simulation Mode
Shadow Runtime
```

来指代同一个长期概念。

---

# 三十、代码与文档清洁原则

虽然这是文档任务，但仍遵守：

```text
无死文档
无重复规则
无冲突定义
无 misleading current-state claims
无 obsolete active vocabulary
无 legacy compatibility promise
```

删除已经没有职责的重复架构段落。

不要为了保留原文字数而保留历史垃圾。

如果同一规则已经由 ADR 正式定义：

README 可以简述并链接。

architecture 可以描述当前结构。

不要把完整 ADR 原文复制进所有文档。

---

# 三十一、实施流程

必须作为一个完整任务执行到底。

不要拆成：

```text
先改 README
等确认
再改 ADR
等确认
再改 AGENTS
```

正确执行：

```text
1. Inspect current HEAD

2. Read:
   README.md
   AGENTS.md
   docs/architecture.md
   docs/roadmap.md

3. Read relevant source:
   runtime enums
   runtime defaults/composition root
   backtest factory/runtime
   paper factory/runtime
   streaming
   research factory
   live factory
   shadow factory
   engine lifecycle

4. Read relevant tests

5. Read relevant ADR:
   0001
   0019
   0020
   0021
   0026
   0064
   0067
   and any other ADR discovered to materially affect Runtime taxonomy

6. Build a current-vs-target architecture map internally

7. Add the new Runtime Taxonomy ADR

8. Update old ADR metadata/clarification where needed

9. Update AGENTS

10. Refactor architecture.md

11. Update roadmap.md

12. Make only necessary README refinements

13. Search all documentation for stale active Runtime vocabulary

14. Validate document links and terminology

15. Run repository quality checks appropriate for documentation changes

16. Review final diff as one coherent architecture change
```

不要停在分析阶段。

---

# 三十二、验证要求

至少运行：

```bash
git diff --check
```

以及仓库已有适用于 docs/static architecture 的质量检查。

如果 Ruff/Mypy/Test lane 不因纯 Markdown 修改受到影响，可以使用项目现有最小合理质量门禁，但必须查阅当前 CI/AGENTS 后决定，不允许自行发明命令。

必须执行 grep/audit，例如：

```bash
rg -n '\bPAPER\b|\bSHADOW\b|Paper Runtime|Shadow Runtime|Vectorized Backtest' \
    README.md AGENTS.md docs
```

逐项检查。

注意：

Historical ADR / report 中出现旧 vocabulary：

```text
不自动视为错误
```

Active architecture / roadmap / engineering contract 中出现：

```text
必须有明确历史/迁移语义
否则视为失败
```

---

# 三十三、必须增加或更新 Architecture Guards 的文档要求

如果仓库已有文档架构测试，可以扩展。

如果没有，不要为了本任务建立大型新测试框架。

但至少在 AGENTS / ADR 中冻结未来可自动化的规则：

```text
Allowed target runtimes:
RESEARCH
BACKTEST
SIM
LIVE

No new PAPER runtime product

No new standalone SHADOW runtime product

No vectorized canonical backtest

No runtime-specific economic manager duplication

No Strategy runtime branching

No Execution runtime-mode permission branching
```

如果已有简单 AST/static test 很自然可以扩展，而且不会把任务扩大成源码迁移，可以添加最小 guard。

否则保持文档任务边界。

---

# 三十四、Definition of Done

只有全部满足，任务才能结束。

## Runtime Taxonomy

```text
[ ] RESEARCH / BACKTEST / SIM / LIVE 成为唯一目标 Runtime vocabulary

[ ] PAPER 明确定义为 current migration debt / SIM migration source

[ ] Standalone SHADOW 明确定义为非目标 Runtime

[ ] README / ADR / AGENTS / architecture / roadmap 不再互相冲突
```

## Research

```text
[ ] Research = Historical + Vectorized

[ ] Research 不承担 formal Trading Kernel

[ ] Research 不被强制 Cluster/Strategy trading 化

[ ] Research Job / Research Plan 边界明确

[ ] Vectorized Backtest 从长期 Roadmap 删除
```

## Backtest

```text
[ ] Backtest = Historical + Event Driven + Virtual Broker

[ ] Backtest 继续运行完整 Trading Kernel

[ ] Backtest fidelity 优先于 vectorized speed
```

## Sim

```text
[ ] Sim = Realtime + Event Driven + Virtual Broker

[ ] Sim 使用完整 Trading Kernel

[ ] Sim 永远不向真实 Broker 发单

[ ] Current PAPER → future SIM 迁移关系明确
```

## Live

```text
[ ] Live = Realtime + Event Driven + Real Broker

[ ] Durable outbound Broker command / synchronization 被明确识别为 Live 前置能力
```

## Trading Semantic Equivalence

```text
[ ] BACKTEST/SIM/LIVE semantic core 共享原则被 ADR 正式冻结

[ ] Runtime Mode != Execution Permission

[ ] Runtime differences limited primarily to Driver boundary
```

## Architecture

```text
[ ] Trading Runtime 与 Research Runtime ownership 分离

[ ] Cluster 与 Research Job 边界清晰

[ ] One Domain → One Write Authority 保留

[ ] Durable Transaction / Projection / Recovery 原则不被破坏
```

## ADR

```text
[ ] 新 Runtime Taxonomy ADR 完成

[ ] relevant old ADR 正确 Superseded / Clarified

[ ] 历史 ADR 正文没有被篡改成今天的事实
```

## AGENTS

```text
[ ] Future Codex 能明确知道只有四种目标 Runtime

[ ] Future Codex 不会继续新增 PAPER/SHADOW 产品代码

[ ] Future Codex 不会把 Research 强制接入 Trading Kernel

[ ] Future Codex 不会实现 Vectorized canonical Backtest
```

## Documentation

```text
[ ] architecture.md 是 current architecture，而不是历史 PR 日志

[ ] roadmap.md 与目标 Runtime taxonomy 完全一致

[ ] README 同时准确表达长期模型和当前迁移状态

[ ] 无冲突、重复、误导、过期 active architecture 定义
```

## Quality

```text
[ ] git diff --check PASS

[ ] documentation/static checks PASS

[ ] stale Runtime vocabulary audit 完成

[ ] final diff self-review PASS
```

---

# 三十五、最终输出要求

完成后只提交一个整体结果报告。

不要按“小任务 1 / 小任务 2 / 小任务 3”汇报。

报告必须包含：

```text
1. Architecture decision
2. Files changed
3. New ADR
4. Old ADR supersede/clarification
5. Runtime taxonomy before/after
6. Research vs Trading Runtime boundary
7. Paper/Shadow migration policy
8. Roadmap change
9. Validation commands and results
10. Remaining implementation debt
```

必须明确说明：

```text
哪些是本任务已经完成的架构/文档收口

哪些仍只是后续源码迁移，例如：
PAPER → SIM
SHADOW deletion
SIM runtime implementation
Research vectorized engine
Live runtime
```

不得把未来计划写成已经实现。

---

# 最终原则

整个任务必须遵守：

```text
Architecture before compatibility

Semantic correctness before naming convenience

Current facts must be honest

Target architecture must be explicit

Research optimizes speed

Backtest optimizes fidelity

Backtest / Sim / Live
share trading semantics

Runtime difference
belongs primarily to Driver boundary

Runtime Type
is not Execution Permission

One Domain
→ One Write Authority

No duplicate economic truth

No obsolete target Runtime vocabulary

No permanent compatibility layer

No fake implementation claims

No historical ADR rewriting

Fail closed on architectural ambiguity
```

最终目标不是简单让几个 Markdown 文件“看起来一致”。

最终目标是建立一个稳定、唯一、可执行的 OnlyAlpha Runtime 架构合同，使未来任何开发者或 Codex 在读取：

```text
ADR
AGENTS
architecture
README
roadmap
```

后，都只能得出同一个架构结论：

```text
OnlyAlpha has four target Runtime products:

RESEARCH
    Historical
    Vectorized
    Research-oriented

BACKTEST
    Historical
    Event-driven
    Virtual trading
    Full trading semantics

SIM
    Realtime
    Event-driven
    Virtual trading
    Full trading semantics

LIVE
    Realtime
    Event-driven
    Real trading
    Full trading semantics
```

以及：

```text
Research
    optimizes research efficiency

Backtest / Sim / Live
    optimize trading semantic consistency
```

在达到这个结果之前，不允许认为任务完成。
