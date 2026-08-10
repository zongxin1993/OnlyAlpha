# Codex Prompt — P4.3 CN A-Share Production Durable Product Conformance

## 唯一任务

**P4.3 — CN A-Share Production Durable Product Conformance**

中文：

**P4.3：中国 A 股生产级 Durable Backtest 产品纵切闭环与一致性认证**

目标仓库：

```text
https://github.com/zongxin1993/OnlyAlpha
```

规划基线：

```text
5d84bff253e4ca5f2905b1e022e84309b02697df
Feat: Durable Broker-Driven Order Lifecycle Closure
```

---

# 0. 本 Prompt 只有一个任务

本 Prompt 不包含多个可独立完成的子任务。

唯一任务是：

> **让 OnlyAlpha 的 `CN_A_SHARE_CASH` 在一个严格冻结的普通 A 股 Cash-Long 产品边界内，使用 Production Reference / Market Rules / Market Fee / Broker Fee Contract，完整经过 BUY OPEN、Broker Accepted、Fill、Partial/Multi-Fill、T+1 Settlement、SELL CLOSE、Cancel/Reject/Expire、Memory/SQLite Persistence、Checkpoint/Restart/Forward Recovery，并最终形成确定、可审计、可重复的 Result / Artifact，从而完成第一个真实市场 Production Durable Backtest Product Conformance。**

以下所有工作：

```text
Production Dataset
Product Contract
BUY OPEN
T+1
SELL CLOSE
Production Fee
Partial Fill
Multi-Fill
Terminal
Recovery
Determinism
Documentation
Architecture Guards
```

全部服务于这一个任务。

不要把它们重新拆成：

```text
P4.3-0
P4.3-1
P4.3-2
...
```

不要在中途宣称某个局部完成就是 P4.3 完成。

只有整个 Product Conformance 通过，P4.3 才完成。

---

# 1. 开始实施前必须重新读取最新 master

不要机械依赖 Prompt 中的基线 commit。

开始前必须：

```text
git fetch
git checkout master
git pull --ff-only
```

或使用当前环境中等价的只读确认方式。

必须确认：

```text
latest master SHA
latest commit message
latest Layered Quality status
```

如果最新 `master` 已前进：

1. 最新 `master` 是唯一事实来源；
2. 重新审计 P4.3 涉及的源码；
3. 已经完成的正确实现不得重复实现；
4. 不得为了符合本 Prompt 恢复已经删除的旧接口；
5. 不得倒退 P4-0 / P4.1 / P4.2 已经建立的 Architecture Invariants；
6. 如果最新代码已有更简单、更正确的实现，应保留；
7. 最终 Implementation Report 必须记录：

   * prompt baseline；
   * actual baseline；
   * baseline differences；
   * already completed items；
   * design adjustments。

---

# 2. 当前工程阶段

P4.3 开始时，应把以下能力视为已经建立并原则上冻结：

```text
Runtime Composition Authority

Canonical Runtime Environment Identity

Component Registry Ownership

Atomic Cluster Composition

Durable Runtime Transaction

Ordered Projection

Forward Recovery

Execution Support Semantic Authority

Execution Support Policy v2

Broker ORDER_ACCEPTED Durable Transaction

Broker TRADE_FILL Durable Transaction

Broker ORDER_TERMINAL Durable Transaction

Projection Target Authority Purity

BUY OPEN Cash-Long Durable Lifecycle

SELL CLOSE Cash-Long Durable Lifecycle

Production CN A-share Market Fee Authority
```

P4.3 不是重新设计这些能力。

P4.3 是：

> **第一次把这些能力组合成一个真实市场产品，并用 Production semantics 证明它们整体成立。**

---

# 3. P4.3 的本质

P4.3 不是：

```text
“新增 A 股支持”
```

因为 A 股 Reference、Market Rules、Fee Authority 已经存在。

P4.3 也不是：

```text
“写几个 A 股集成测试”
```

P4.3 真正要证明的是：

```text
Component Correctness
        ↓
Composition Correctness
        ↓
Economic Lifecycle Correctness
        ↓
Durability Correctness
        ↓
Recovery Correctness
        ↓
Deterministic Product Correctness
```

最终：

```text
CN_A_SHARE_CASH
        ↓
Production Durable Backtest Product
```

成为一个可以明确声明支持范围、明确声明不支持范围、能够重复验证的真实产品。

---

# 4. 第一性原则一：Product Correctness ≠ Component Correctness

以下事实即使全部成立：

```text
A-share Reference 单测通过

A-share price limit 单测通过

T+1 settlement 单测通过

Production Fee Pack 单测通过

Trade Planner 单测通过

Terminal Planner 单测通过

Recovery 单测通过
```

也不能推出：

```text
CN A-share Product 正确
```

真正的 Product Correctness 必须证明：

```text
Reference
+
Market Rule
+
Risk
+
Order
+
Reservation
+
Broker Lifecycle
+
Execution
+
Fee
+
Settlement
+
Persistence
+
Recovery
+
Result
```

在同一真实产品纵切面上同时成立。

---

# 5. 第一性原则二：Production Product 只能使用 Production Authority

P4.3 正式 Product Gate 禁止使用：

```text
CN_A_SHARE_TEST_MARKET_FEE_PACK
```

禁止使用为了测试方便而人为缩短的：

```text
fake fee
zero fee
generic fee
test-only A-share economic authority
```

正式 Product Conformance 必须使用：

```text
CN_A_SHARE_PRODUCTION_MARKET_FEES
```

以及明确版本的：

```text
Broker Fee Contract
```

Market Fee 与 Broker Fee 必须继续保持独立 Authority。

---

# 6. 第一性原则三：Product Test 必须经过真实产品调用链

P4.3 Product Conformance 不能主要靠：

```text
直接调用 Trade Planner
直接构造 Prepared Transaction
直接修改 Settlement
直接写 Position Manager
直接构造 FeeAssessment
```

然后证明组件正确。

正式产品认证必须从真实产品入口运行：

```text
Cluster Config
        ↓
OnlyEngine
        ↓
Runtime Planning / Assembly
        ↓
Backtest Runtime
        ↓
Market Rules
        ↓
Strategy / Order
        ↓
Risk
        ↓
Reservation
        ↓
Virtual Broker
        ↓
Normalized Broker Fact
        ↓
Execution Processor
        ↓
Execution Support Authority
        ↓
Accepted / Trade / Terminal Planner
        ↓
Prepared Transaction
        ↓
Durable Commit
        ↓
Projection
        ↓
Settlement
        ↓
Result / Artifact
```

Component unit tests 可以存在。

但：

> **Product Certification 必须走 Production Composition Root。**

---

# 7. 第一性原则四：Market Rule 决定是否合法，Execution Support 决定 Kernel 是否实现

必须继续严格区分：

```text
Market Rule Authority
```

回答：

```text
这笔交易在这个市场、这个交易日、这个标的、
这个账户状态下是否允许？
```

Execution Support Authority 回答：

```text
OnlyAlpha Durable Kernel
是否实现这种经济交易 shape？
```

禁止重新混合。

例如：

```text
Day D BUY 后同日 SELL
```

应该：

```text
Market Rule
→ SELLABLE_POSITION reject
```

不能：

```text
Execution Capability
→ UNSUPPORTED because A-share T+1
```

---

# 8. 第一性原则五：T+1 必须来自 Settlement Authority

禁止：

```python
if market_profile == "CN_A_SHARE_CASH":
    position.sellable = 0
```

禁止：

```python
if ashare:
    reject_same_day_sell()
```

正确路径必须继续是：

```text
Market Profile / Reference
        ↓
Compiled Market Rules
        ↓
Trade Application Instruction
        ↓
Settlement Schedule
        ↓
TRADE_FILL Transaction
        ↓
UNSETTLED asset
        ↓
SETTLEMENT_MATURITY Transaction
        ↓
Trade Available / Sellable
```

P4.3 是验证这条链。

不是重新实现这条链。

---

# 9. 第一性原则六：Execution Core 不认识 A 股名字

P4.3 实施过程中：

```text
src/onlyalpha/execution/
```

不得新增：

```text
CN_A_SHARE_CASH
Ashare
Shanghai
Shenzhen
XSHG
XSHE
T_PLUS_ONE
```

用于 execution business routing。

如果 P4.3 暴露 Generic Cash Kernel 缺失某种语义：

必须找到真正缺失的：

```text
compiled instruction
settlement instruction
reservation shape
fee instruction
position instruction
```

进行 market-neutral 修复。

禁止：

```python
if CN_A_SHARE_CASH:
    special_case()
```

---

# 10. 第一性原则七：Production Fact 必须可审计

对于最终任意一笔交易，系统必须能够回答：

```text
为什么允许下单？

为什么这个价格合法？

为什么这个数量合法？

为什么这一天不能卖？

为什么下一交易日可以卖？

为什么收了这些 Market Fee？

为什么收了这些 Broker Fee？

为什么 partial fill 只增加这些费用？

为什么 crash/restart 后结果不变？

这笔交易使用了哪个 Reference？

使用了哪个 Market Profile？

使用了哪个 Fee Authority？

使用了哪个 Broker Contract？

使用了哪个 Execution Support Policy？
```

答案必须来自：

```text
versioned immutable authority
```

而不是：

```text
“现在代码大概是这样算的”
```

---

# 11. 第一性原则八：Recovery 结果必须等价于从未 crash

必须成立：

```text
Same Economic Input
        ↓
Uninterrupted Execution
```

与：

```text
Same Economic Input
        ↓
Crash
Restart
Forward Recovery
Continue
```

最终得到完全相同的：

```text
Economic State
Committed Facts
Transactions
Artifacts
Result Fingerprints
```

Recovery 不是：

```text
“程序还能继续跑”
```

而是：

```text
Recovered History
=
Canonical History
```

---

# 12. 产品支持边界必须显式冻结

P4.3 只认证以下产品：

```text
Product:
CN A-share Cash Durable Backtest V1

Market Profile:
CN_A_SHARE_CASH

Currency:
CNY

Venues:
XSHG
XSHE

Security Type:
ordinary COMMON_STOCK

Account:
CASH

Position:
LONG
NETTING

Order:
LIMIT

Order semantics:
BUY OPEN
SELL CLOSE

Broker lifecycle:
ACCEPTED
TRADE
CANCELLED
REJECTED
EXPIRED

Execution:
Whole Fill
Partial Fill
Multi-Fill

Settlement:
ordinary T+1 sellability semantics

Persistence:
MEMORY
SQLITE

Recovery:
Checkpoint
Restart
Forward Recovery

Output:
Deterministic Result
Deterministic Artifact
```

---

# 13. 明确不认证的范围

P4.3 不得默认为整个中国股票市场认证。

明确不包含：

```text
BSE

Margin Trading

Short Selling

Hedging

ETF special trading semantics

Convertible Bonds

Options

Futures

Stock Connect

IPO / first-day special price regimes

Delisting special regimes

after-hours fixed-price trading

block trading

auction-specific advanced order behavior

special corporate-action processing

real broker command durability

Paper trading

Live trading
```

如果现有 Profile 对某些内容有模型：

也不自动等于本产品已经认证。

---

# 14. Pre-Implementation Audit

开始写产品实现/测试前，必须完成一次代码级审计。

重点至少包括：

```text
src/onlyalpha/runtime/backtest/
src/onlyalpha/runtime/environment.py

src/onlyalpha/market/
src/onlyalpha/reference/

src/onlyalpha/fee/
src/onlyalpha/settlement/

src/onlyalpha/order/
src/onlyalpha/risk/

src/onlyalpha/execution/
src/onlyalpha/transaction/

src/onlyalpha/account/
src/onlyalpha/strategy_ledger/
src/onlyalpha/position/

tests/conformance/cn_a_share_cash/
tests/integration/
tests/execution/
tests/recovery/
tests/fixtures/
```

---

# 15. Audit 必须回答

至少回答：

```text
Current A-share Product composition path

Current Reference source

Current effective Reference semantics

Current Market Profile versions

Current Production Fee Pack identity

Current Production Fee coverage window

Current Broker Contract path

Current BUY OPEN path

Current SELL CLOSE path

Current T+1 settlement path

Current whole-fill path

Current partial-fill path

Current multi-fill path

Current terminal path

Current Memory/SQLite recovery path

Current Result / Artifact path

Current cn_a_share conformance tests

Current use of test-only fee authority

Current production conformance gaps

Current generic/T0 naming residue

Any hidden product-specific branch in Execution
```

---

# 16. Pre-Implementation Audit Report

新增：

```text
docs/reports/
p4_3_cn_a_share_production_durable_product_pre_implementation_audit.md
```

必须包含：

```text
Prompt baseline

Actual baseline

Current product surface

Current production authorities

Current test-only authorities

Current product lifecycle

Missing product proofs

Interfaces to remove

Interfaces to keep

Explicit non-scope
```

---

# 17. ADR：冻结 Production Product Contract

新增一个 ADR，例如：

```text
docs/adr/
<next>-cn-a-share-production-durable-backtest-product.md
```

必须回答：

```text
What exactly is CN A-share Durable Backtest Product V1?

What market/profile versions does it claim?

What instruments does it cover?

What order shapes does it cover?

What settlement semantics does it cover?

What fee authorities does it require?

What persistence/recovery guarantees does it provide?

What does “Production” mean here?

What is explicitly unsupported?

What does product certification prove?

What does it NOT prove?
```

---

# 18. 不建立新的 Product Framework

P4.3 禁止创建：

```text
OnlyProductFramework
OnlyMarketProductRegistry
OnlyProductCapabilityDSL
OnlyConformancePluginRegistry
OnlyProductProviderSPI
```

这些属于未来 P5 是否需要解决的问题。

P4.3 只建立：

```text
一个真实 A 股 Product Contract
+
一个真实 Product Conformance Harness
```

不要提前抽象第二个市场。

---

# 19. Production Conformance Dataset

必须建立独立的 Product Conformance fixture。

不要继续把 Production Product Certification 塞进旧：

```text
MiniQMT golden
```

Provider fixture。

建议目录：

```text
tests/fixtures/conformance/
cn_a_share_production_v1/
```

或符合当前仓库结构的等价路径。

---

# 20. Dataset 日期必须落在 Production Fee Coverage 内

当前 Production Fee Authority 如果覆盖始于：

```text
2025-06-30
```

则正式 Product Dataset：

```text
trading_day >= 2025-06-30
```

必须作为测试硬约束。

增加 guard：

```text
production conformance trading date
must be within production fee authority effective range
```

禁止未来 fixture 漂回 coverage 前。

---

# 21. Dataset 必须携带 provenance

至少：

```text
dataset_id

source

source_version

data_version

coverage

content fingerprint

instrument identity

trading calendar

trading dates

bar data

reference snapshot / reference records
```

如果数据是测试生成的 deterministic synthetic fixture：

必须明确声明：

```text
synthetic market-data fixture
```

不能假装来自真实交易所历史数据。

但：

```text
Reference / Rule / Fee semantics
```

必须使用 Production Authority。

---

# 22. Reference 不得从 Bar 推导

不能：

```text
bar.close yesterday
→ previous_close
```

作为 Product Reference Authority 的隐式替代。

必须提供正式：

```text
OnlyAshareInstrumentReference
```

或当前 master 等价 Reference Authority。

至少包括：

```text
instrument
exchange
security type
board
lot
tick
ST
suspension
previous close
effective period
source/version/fingerprint
```

---

# 23. 推荐至少覆盖一个 XSHG 和一个 XSHE 标的

如果测试成本可控，Production V1 建议至少：

```text
one XSHG ordinary common stock
one XSHE ordinary common stock
```

这样可以同时验证：

```text
exchange-specific fee rule selection
reference venue identity
```

但如果当前 product harness 首次纵切为了降低复杂度只使用一个标的：

至少必须通过专门 fee/reference tests 证明 XSHG/XSHE 两套 Production rules 均可 resolve。

不能声明双市场覆盖却只验证一个 venue。

---

# 24. Production Broker Fee Contract

建立一个明确、版本化的 Conformance Broker Contract。

例如：

```text
contract id
contract version
currency CNY
broker compatibility
account compatibility
commission rate
minimum commission
effective semantics
```

不要在测试 expected value 中暗中写：

```text
commission = 0.0003
minimum = 5
```

却没有正式 Authority。

必须：

```text
Broker Fee Contract
→ Fee Binding
→ Fee Assessment
```

---

# 25. 不允许 Test Fee Pack 进入 Product Gate

增加 architecture/conformance guard：

正式：

```text
cn_a_share_production_product
```

测试路径不得引用：

```text
CN_A_SHARE_TEST_MARKET_FEE_PACK
only_cn_a_share_conformance_fee_pack
```

旧 Golden Data tests 如果还有真实 Provider/Reference 价值：

继续保留。

不要删除有价值的测试。

但必须清楚区分：

```text
Provider/Data Golden Conformance
```

与：

```text
Production Trading Product Conformance
```

---

# 26. 建立 Product Conformance Harness

建议建立专用 helper/harness。

职责：

```text
Build standard Engine

Build standard Runtime

Install production Market Fee Pack

Install explicit Broker Fee Contract

Install Reference Authority

Select Persistence Backend

Load production conformance dataset

Run exact Product scenario

Capture canonical outputs
```

它不是新的 production framework。

它只属于：

```text
tests/conformance
```

---

# 27. Harness 不得 bypass Composition Root

Harness 不能：

```text
directly instantiate TradePlanner

directly inject FeeAssessment

directly mutate Position

directly mature Settlement

directly invoke ProjectionTarget
```

必须通过当前正式 Engine/Runtime 接口。

---

# 28. BUY OPEN 是第一条必须成立的 Product Slice

正式路径：

```text
Reference
        ↓
Resolved Market Profile
        ↓
Compiled Market Rules
        ↓
Pre-Trade
        ↓
Risk Evaluation
        ↓
Order Creation
        ↓
Cash Reservations
        ↓
Broker Submission
        ↓
Virtual Broker Accepted
        ↓
ORDER_ACCEPTED Durable Transaction
        ↓
Virtual Broker Trade
        ↓
TRADE_FILL Durable Transaction
```

最终必须产生正确：

```text
Order
Position
Allocation
Account
Strategy Ledger
Fee
Settlement
Risk
Valuation
```

---

# 29. BUY OPEN Product Assertions

不能只：

```text
order FILLED
```

必须逐 Authority 验证。

## Order

```text
status
original quantity
filled quantity
remaining quantity
average fill price
broker identity
```

## Position

```text
quantity
cost basis
settlement bucket
sellable/trade-available quantity
```

## Allocation

```text
cluster ownership
quantity
cost attribution
```

## Account

```text
cash before
trade available cash
reserved cash
fee deductions
equity
```

## Strategy Ledger

```text
cash
reserved cash
position attribution
fees
equity
```

## Risk

```text
reservation state
remaining quantity
remaining notional
active order count
```

## Settlement

```text
asset leg
cash leg
availability date
status
```

---

# 30. Same-Day Sell 必须正式拒绝

必须有 Product scenario：

```text
Day D

BUY OPEN
→ FILLED

then

SELL CLOSE same quantity
```

应被：

```text
Pre-Trade Market Rule
```

拒绝。

必须证明 reason 来自：

```text
SELLABLE_POSITION
```

或当前正式等价 Market Rule reason。

不能来自：

```text
Execution Unsupported
```

---

# 31. Same-Day Sell Reject 不应产生 Broker Lifecycle

如果 Pre-Trade 已拒绝：

不应：

```text
submit to Virtual Broker
```

不应产生：

```text
ORDER_ACCEPTED
TRADE_FILL
ORDER_TERMINAL
```

除非当前 Order architecture 明确定义了 local rejected order fact。

测试应按当前正式 contract 验证。

---

# 32. Settlement Maturity 必须走正式 Transaction

推进到下一个合法 Trading Day。

必须通过当前：

```text
SETTLEMENT_MATURITY
```

Durable Transaction。

禁止 fixture/helper 直接改：

```text
sellable_quantity
```

或直接改 Settlement Manager。

---

# 33. T+1 后必须验证 Sellable Authority

Settlement maturity 后：

```text
Position quantity
```

保持正确。

```text
sellable / trade_available quantity
```

按 Settlement Authority 增加。

如果存在其它未结算 lot：

只能成熟到期部分。

不要写测试专用 shortcut。

---

# 34. SELL CLOSE Product Slice

T+1 maturity 后执行：

```text
SELL CLOSE
```

必须经过：

```text
Pre-Trade
        ↓
Risk
        ↓
Position Reservation
        ↓
Broker Accepted
        ↓
ORDER_ACCEPTED Transaction
        ↓
Broker Trade
        ↓
TRADE_FILL Transaction
```

最终：

```text
Position decreases

Allocation decreases

Close cost attribution consumed

Fee applied

Account cash updated

Strategy Ledger updated

Settlement created

Risk released
```

---

# 35. BUY/SELL 必须使用同一个 Execution Kernel

Architecture Guard：

不得新增：

```text
AshareTradePlanner
AshareTerminalPlanner
AshareAcceptedPlanner
```

也不得：

```python
if CN_A_SHARE_CASH:
```

进入 Execution route。

A 股区别必须已经被：

```text
Compiled Market Rules
Trade Application Instruction
Fee Authority
Settlement Schedule
```

表达。

---

# 36. Production Fee Component Conformance

必须逐 component 验证真实 Production resolved fee。

至少包括当前适用的：

```text
Stamp Duty

Transfer Fee

Broker Commission
```

以 resolved Authority 为唯一事实来源。

不能在 Prompt/测试里假定未来具体费率永远不变。

测试应从正式 Schedule Authority 验证期望值。

---

# 37. SELL Stamp Duty

必须证明：

```text
SELL
```

适用 Production Stamp Duty。

BUY 不应错误应用 SELL-only Stamp Duty。

测试应检查：

```text
fee type
rule identity
schedule identity
schedule version
basis
rate
raw amount
rounded amount
applied amount
```

如果当前 Fact 提供这些 proof。

---

# 38. Transfer Fee

必须对：

```text
XSHG
XSHE
```

正式 Production Schedule 适用性做验证。

不能只检查一个 total amount。

---

# 39. Broker Commission

Broker Commission 必须来自：

```text
OnlyBrokerFeeContract
```

或最新 master 等价正式 Authority。

不来自 Market Fee Pack。

必须证明：

```text
Market Authority
≠
Broker Authority
```

仍然保持独立。

---

# 40. Multi-Fill Product Scenario

至少创建一个：

```text
BUY OPEN 1000
```

然后：

```text
Fill 300
Fill 400
Fill 300
```

每个 Fill 必须经过真实：

```text
Broker Trade Update
→ Execution Processor
→ TRADE_FILL Transaction
```

禁止一次 Fill 后手工修改最终状态模拟多 Fill。

---

# 41. Multi-Fill 每一步都必须检查增量状态

Fill #1 后：

```text
Order 300 / 1000

Reservation remaining 700

Position +300

Allocation +300

Risk remaining 700

Fee accrual updated
```

Fill #2：

```text
Order 700 / 1000

Reservation remaining 300

Position +400 incremental

Fee incremental
```

Fill #3：

```text
Order FILLED

remaining reservation = 0

risk finalized
```

---

# 42. Minimum Broker Commission 必须做专门 Product Scenario

这是 P4.3 必测项。

选择成交金额，让：

```text
commission_rate × notional
<
minimum commission
```

并进行多次 Fill。

验证：

```text
Order cumulative broker fee
```

符合 Contract。

不能：

```text
每一个 Fill 都重新收一次最低佣金
```

---

# 43. Fee 测试必须验证 incremental 与 cumulative

对于每个 Fill：

```text
current assessment

previous cumulative accrual

incremental applied fee

new cumulative accrual
```

都要验证。

最终：

```text
sum(incremental application)
=
final cumulative contractual fee
```

---

# 44. SELL Multi-Fill 也必须存在

不能只测试 BUY multi-fill。

至少一个 SELL CLOSE multi-fill 场景，证明：

```text
partial close cost

partial allocation consumption

partial position reduction

SELL fee components

risk/reservation remaining
```

都正确。

---

# 45. BUY OPEN Partial + Cancel

Canonical scenario：

```text
BUY OPEN 1000

ACCEPTED

FILL 300

CANCELLED remaining 700
```

必须验证：

```text
300 committed Position preserved

300 Allocation preserved

300 fees preserved

remaining Account Cash Reservation released

remaining Strategy Cash Reservation released

remaining Risk Reservation released

Order CANCELLED
```

---

# 46. SELL CLOSE Partial + Cancel

Canonical scenario：

```text
SELL CLOSE 1000

ACCEPTED

FILL 300

CANCELLED remaining 700
```

必须验证：

```text
300 sold Position remains sold

300 Allocation consumed

300 close cost consumed

700 remaining Allocation hold released

700 Position Reservation released

700 Risk released
```

不能 rollback 已成交部分。

---

# 47. Reject 必须独立验证

至少：

```text
BUY OPEN
SUBMITTED
→ Broker REJECTED
```

验证：

```text
cash reservation
strategy cash reservation
risk
order terminal
```

都通过 P4.2 Durable Terminal protocol 释放。

---

# 48. SELL Reject Before Accepted

至少：

```text
SELL CLOSE
SUBMITTED
→ REJECTED
```

验证：

```text
pre-ACK Position hold

Allocation hold

Position Reservation

Risk
```

全部按正确 Authority 明确释放。

---

# 49. Expire 必须独立验证

不能只测试 Cancel/Reject，然后认为 Expired 自动正确。

至少一条：

```text
Accepted
→ Expired
```

验证：

```text
terminal fact identity
status
release reason
projections
risk result
```

---

# 50. Product Scenario 不应该使用内部 Fake Mutation

Virtual Broker 如果需要精确产生：

```text
Accepted
Fill
Partial Fill
Cancel
Reject
Expire
```

应通过已有 Broker simulation contract。

如果当前 Virtual Broker 缺一种必要的 deterministic scenario control：

可以扩展：

```text
test/simulation control surface
```

但不得绕过：

```text
Normalized Broker Update
```

直接调用 Execution Processor 私有方法。

---

# 51. Persistence Matrix

P4.3 Product Conformance 必须覆盖：

```text
MEMORY
SQLITE
```

Memory：

证明：

```text
Product semantics
```

不依赖 SQLite。

SQLite：

证明：

```text
durability
restart
forward recovery
```

---

# 52. Checkpoint / Restart

必须使用正式 Runtime Persistence API。

不能：

```text
pickling arbitrary managers
```

不能测试里直接复制 runtime object。

需要模拟真正：

```text
Engine A close

new Engine B

same persistent state root

restore
```

---

# 53. A → B → C Recovery Scenario

必须至少建立一个完整 scenario：

```text
Engine A

Day D
BUY OPEN
ACCEPTED
Partial Fill
Checkpoint / Stop

        ↓

Engine B

Restore
Continue remaining Fill
Commit
Stop / Inject crash

        ↓

Engine C

Restore
Settlement Maturity
SELL CLOSE
Accepted
Partial Fill
Terminal
Complete
```

可以根据当前 fixture 能力调整 crash 点，但必须真正经历多个 Runtime instance。

---

# 54. Uninterrupted Baseline

同样输入必须运行一个：

```text
Engine U
```

完全不 crash。

然后比较：

```text
Recovered A→B→C
```

与：

```text
Uninterrupted U
```

---

# 55. Recovery Equality 必须是 Authority-Level

至少比较：

```text
Order snapshots

Position snapshots

Allocation snapshots

Account snapshots

Strategy Ledger snapshots

Fee authority / application ledger

Order Fee Accrual

Cash Reservations

Position Reservations

Risk Reservations

Risk Snapshot

Settlement Authority

Runtime Transactions

Committed Facts

Applied Projection Ledger

Outbox state

Result

Artifact
```

---

# 56. Recovery 不允许“经济结果一样但事实历史不同”

例如：

```text
最终 cash 一样
```

但：

```text
transaction sequence different

fee application duplicated

projection history different

outbox repeated
```

不能通过。

Product Conformance 要求：

```text
Canonical Economic History
```

也一致。

---

# 57. Determinism

使用完全相同：

```text
Product Config
Dataset
Reference
Authority Versions
Broker simulation
```

至少重复运行两次。

必须：

```text
same result fingerprint

same artifact fingerprint

same transaction identities

same committed fact identities
```

除非某字段被明确设计为 non-deterministic diagnostic metadata，并已排除在 canonical fingerprint 之外。

---

# 58. Artifact 必须成为 Product Gate 一部分

P4.3 不能停在内部 manager state。

最终 Product Artifact 至少必须能够追踪：

```text
Product identity

Market Profile identity/version

Reference fingerprint

Market Fee Pack identity/version

Broker Fee Contract identity/version

Execution Support Policy

Runtime identity

Result fingerprint
```

如果当前 Artifact 已包含大部分：

不要重复设计一套 Artifact。

只补真实缺失且具有产品审计意义的 proof。

---

# 59. 不要扩大 Result/Artifact Schema 只为测试方便

如果某个 proof 已经在：

```text
Transaction
Committed Fact
Manifest
```

中存在，

不要全部复制到最终 Result。

Product Harness 可以横向验证多种 artifacts。

保持：

```text
One Fact → One Authority
```

---

# 60. Residual Planner Cleanup

P4.3 可以顺手删除仍然明显误导的历史命名，例如：

```text
Generic T0
Generic Cash
Long Close only
```

如果实际实现已经不再只代表这些范围。

但是：

不要为此重新设计 Planner。

仅：

```text
rename misleading documentation

delete dead error codes

delete dead imports/helpers

delete obsolete tests/names
```

保持小范围。

---

# 61. 如果发现新的 Generic T0 Assumption

不要打补丁。

必须先回答：

```text
这个差异真正属于哪个 Authority？
```

例如：

## 如果是 Settlement 差异

补：

```text
Settlement Instruction
```

## 如果是 Market Price Rule

补：

```text
Compiled Price Policy
```

## 如果是 Quantity Rule

补：

```text
Compiled Quantity Policy
```

## 如果是 Fee

补：

```text
Fee Authority
```

## 如果是 Execution Implementation Shape

只有确实是新的 economic kernel semantic，才扩：

```text
Execution Support Policy
```

---

# 62. 禁止 P4.3 中新增 A 股 Execution Branch

绝对禁止：

```python
if market_profile_id == "CN_A_SHARE_CASH":
```

进入：

```text
execution/capability.py
execution/processor.py
execution/trade_planner.py
execution/accepted_planner.py
execution/terminal_planner.py
execution/reducers.py
```

---

# 63. Architecture Guard：No A-share Execution Knowledge

新增 source guard。

正式 Execution Kernel 不得 import：

```text
onlyalpha.reference.ashare*
onlyalpha.market.ashare_rules*
```

也不得包含：

```text
CN_A_SHARE_CASH
XSHG
XSHE
```

用于 business routing。

---

# 64. Architecture Guard：Production Gate 不允许 Test Fee

正式：

```text
CN A-share Production Product Conformance
```

文件/fixture/harness 不得 import：

```text
CN_A_SHARE_TEST_MARKET_FEE_PACK
```

---

# 65. Architecture Guard：Production Date

正式 Production Product Dataset：

```text
minimum trading date
>= production fee coverage from
```

增加自动测试。

---

# 66. Architecture Guard：No Direct Economic Mutation

Product Conformance 路径不得绕开：

```text
Order Service
Broker Update
Execution Processor
Transaction Coordinator
```

直接操作：

```text
PositionManager
AccountManager
LedgerManager
ReservationManager
```

来制造 expected state。

---

# 67. Architecture Guard：No Product Compatibility Layer

P4.3 不增加：

```text
legacy_ashare
ashare_v1_compat
generic_t0_compat
fallback_fee_pack
fallback_reference
```

如果旧测试需要旧接口：

迁移测试。

不要保存无职责生产 API。

---

# 68. Production Product Conformance 测试组织

建议：

```text
tests/conformance/
cn_a_share_production/
```

包含多个 scenario 文件没有问题。

但它们共同属于：

```text
一个 Product Gate
```

不要把每个测试文件包装成独立产品阶段。

---

# 69. 建议 Scenario Set

至少包含：

```text
whole_buy_open

same_day_sell_rejection

settlement_maturity

whole_sell_close

buy_multi_fill

sell_multi_fill

minimum_commission_multi_fill

buy_partial_cancel

sell_partial_cancel

buy_rejected

sell_rejected_before_ack

expired

sqlite_restart_recovery

abc_recovery_equivalence

determinism
```

实际命名按仓库规范。

---

# 70. 不要求每个 Scenario 一份重复 Config

使用共享 Product Harness / Product Fixture。

但每个 scenario 的：

```text
economic intent
expected authority transition
```

必须清楚。

避免一份 3000 行 integration test。

---

# 71. Product Conformance 必须 Fail Closed

如果 Product Harness：

```text
reference missing

reference out of effective range

fee pack out of coverage

broker contract incompatible

market profile unresolved

settlement unavailable

unsupported order shape
```

必须直接失败。

不能：

```text
fallback generic
fallback zero fee
fallback T0
```

---

# 72. Product Contract Version

建议正式声明：

```text
CN_A_SHARE_DURABLE_BACKTEST_V1
```

或符合项目命名规范的等价 Product Conformance identity。

它代表：

```text
一个明确支持边界
```

不一定要求加入 production registry。

可以首先存在于：

```text
ADR
conformance manifest
artifact
```

---

# 73. Product Conformance Manifest

建议 fixture 或测试输出有：

```text
product_id

product_contract_version

market_profile

market_profile_version

fee_pack

fee_pack_version

broker_contract

broker_contract_version

dataset_id

dataset_fingerprint

supported_surface

result_fingerprint
```

这能让以后回归时知道到底认证了什么。

---

# 74. 不要混淆 Product Contract Version 与各 Authority Version

必须保持：

```text
Product Contract Version
≠
Market Profile Version
≠
Reference Data Version
≠
Fee Pack Version
≠
Broker Contract Version
≠
Execution Support Policy Version
≠
Transaction Schema Version
```

它们都是独立 Authority。

---

# 75. Production Product Promotion

P4.3 不自动要求：

```text
CN_A_SHARE_CASH status = STABLE
```

是否提升 Profile 状态必须取决于 Profile 承诺范围。

P4.3 能明确声明的是：

```text
CN_A_SHARE_DURABLE_BACKTEST_V1
conformance PASS
```

如果 Profile 仍然包含未认证的更大范围：

继续保持：

```text
EXPERIMENTAL
```

是可以接受的。

---

# 76. Test Assertions 应使用 Domain Authority

不要测试：

```python
assert private_list[3] == ...
```

优先通过：

```text
public query
snapshot
fact
transaction query
artifact
```

验证。

如果为了测试被迫访问大量 private mutable internals：

先检查是不是缺正式 read/query surface。

只在真正需要、且 read-only 的情况下增加最小 query API。

---

# 77. 不为测试建立新的 Write API

禁止为了方便：

```text
set_position()
set_settlement()
set_fee()
force_order_state()
```

增加 production write接口。

测试控制只能进入：

```text
input side
```

例如：

```text
market data
broker simulation
clock
persistence restart
```

---

# 78. Fee Expected Values

对于固定 Production authority 可以使用 golden expected values。

但 expected value 必须注明来自：

```text
resolved fee rule
```

并同时验证：

```text
rule identity/version
```

防止未来 rule 升版后：

```text
只改 expected number
```

而不知道 Authority 变化。

---

# 79. Same-Day Sell Rejection Assertion

至少验证：

```text
rejected before broker submission

specific market-rule reason

no sell reservation created

no broker Accepted/Trade Transaction

no Position mutation

no Fee application
```

---

# 80. Settlement Maturity Assertion

至少：

```text
maturity transaction exists

only eligible unsettled asset becomes available

no duplicate maturity on replay

same maturity fact replay idempotent

Position/Settlement parity preserved
```

---

# 81. SELL CLOSE Assertion

至少：

```text
close quantity <= sellable quantity

Position Reservation exact

Accepted releases only ACK-related local freeze

Fill consumes Allocation/Position quantity

Close cost attribution exact

Fee exact

Terminal only releases remaining holds
```

---

# 82. Multi-Cluster 不进入本阶段扩展

如果当前产品已有 Multi-Cluster shared account regression：

必须保持不回归。

但 P4.3 不新增：

```text
A-share Multi-Cluster Product Certification
```

除非当前正式 supported surface 已经明确要求。

本任务优先一个清晰普通产品纵切。

---

# 83. Failure Injection

针对 SQLite Product Recovery 至少注入：

```text
after transaction stored

after first projection

mid projections

after projection ready before delivery
```

选择已有 fault injection infrastructure。

不要创建第二套 crash framework。

---

# 84. Broker Fact Duplicate

在 Product Scenario 中至少验证：

```text
duplicate Accepted

duplicate Fill

duplicate Terminal
```

不会：

```text
double position

double fee

double release

double event
```

---

# 85. Same Identity Different Payload

至少一个 Product-level conflict case：

```text
same Broker fact identity
different payload
```

必须：

```text
Fail Closed / conflict
```

不能覆盖已有 committed fact。

---

# 86. Recovery 使用 Committed Fact，不重新执行今天的 Market Rule

历史已经 committed：

```text
Trade
Terminal
Settlement
```

恢复时不能：

```text
重新跑今天的 Market Profile
```

再决定过去是否有效。

Historical Fact Immutable。

---

# 87. Historical Fee 也不能按最新 Fee Rule 重算

Recovery 必须使用 persisted：

```text
Fee authority identity
Fee assessment/application facts
```

不能：

```text
current production fee pack
```

重新计算历史交易。

P4.3 Recovery Test 应间接证明这一点。

---

# 88. Output Determinism

至少验证：

```text
transaction ordering

event ordering

artifact serialization

fingerprint
```

不受：

```text
dict insertion order
test execution order
process restart
```

影响。

---

# 89. Product Conformance Report

新增：

```text
docs/reports/
p4_3_cn_a_share_production_durable_product_conformance.md
```

必须包含：

```text
Prompt baseline

Actual baseline

Product contract

Supported surface

Unsupported surface

Dataset provenance

Reference authority

Market rule authority

Market fee authority

Broker fee authority

BUY OPEN result

Same-day sell rejection

T+1 result

SELL CLOSE result

Multi-fill result

Minimum commission result

Terminal result

Recovery result

Memory/SQLite result

Determinism result

Architecture guards

Deleted interfaces

Production code changes

Test-only changes

Quality gates

Known limitations

Next phase
```

---

# 90. 报告必须明确区分“生产代码修复”和“产品证明”

如果 P4.3 主要新增测试：

明确说明。

如果发现 production bug：

每个 bug 必须写：

```text
root cause

violated invariant

why it was generic

why the fix is market-neutral

regression guard
```

禁止：

```text
“为了让 A 股测试通过做了以下修改”
```

这种解释。

必须解释为什么之前 Kernel 在第一性原则上不完整。

---

# 91. 删除旧接口

P4.3 中发现任何只为早期 Generic/T0/Test A-share 路径存在、现在无职责的接口：

直接删除。

例如可能包括：

```text
obsolete Generic T0 aliases

old test fee helpers accidentally exposed as production

dead A-share compatibility wrappers

old product-specific planner naming

unused private branch
```

是否删除必须以最新源码审计为准。

---

# 92. 不删除仍有独立价值的 Provider Golden Tests

现有 MiniQMT golden test 如果仍然负责：

```text
Provider normalized contract
Reference snapshot stability
dataset provenance
```

继续保留。

不要因为新 Product Conformance 取代了“产品认证”职责，就把 Provider Contract tests 删除。

正确：

```text
Provider Conformance
        ≠
Product Conformance
```

---

# 93. Module Boundary

P4.3 完成后理想边界保持：

```text
reference/
    market reference facts

market/
    market semantics

fee/
    economic fee authorities

order/
    order command semantics

execution/
    market-neutral durable execution

settlement/
    availability/maturity semantics

transaction/
    durability protocol

runtime/
    composition/orchestration

tests/conformance/
    product proof
```

不要把产品测试逻辑移进 production package。

---

# 94. P4.3 预期 production code change 应该有限

理想情况：

```text
tests / fixtures / docs
```

占主要变化。

如果 production code 变化非常大：

暂停并重新审计根因。

尤其：

```text
execution/
transaction/
```

出现大量 A 股改动是强烈架构警报。

---

# 95. Commit 组织原则

虽然本 Prompt 只有一个任务，但允许为了 reviewability 使用多个 commit。

所有 commit 都属于：

```text
P4.3 CN A-Share Production Durable Product Conformance
```

不得把其中任何一个单独视为 P4.3 completion。

建议概念顺序：

```text
Product Contract + Audit

Production Conformance Dataset/Harness

BUY + T+1 + SELL Product Slice

Partial/Multi-Fill + Production Fee

Terminal Product Scenarios

Memory/SQLite Recovery + Determinism

Docs + Final Certification
```

具体 commit 数量由实现决定。

---

# 96. 每个 commit 必须保持仓库可运行

不要提交：

```text
capability 已开放
但 test 还没写

schema 已变
codec 没变

fixture 已换
golden 未更新
```

每个 commit 应概念完整。

---

# 97. 不允许通过测试的方式

禁止：

```text
skip

xfail

删现有 regression test

降低 assertion

只比较最终 Order status

mock 掉 Fee

mock 掉 Settlement

mock 掉 Execution Processor

直接注入 Position

直接修改 sellable quantity

用 test fee pack 伪装 production

生产日期落在 fee coverage 外

通过 if CN_A_SHARE 修 Execution

关闭 --frozen

删除 Recovery gate
```

---

# 98. Static Gates

以最新 `master` CI 为准。

至少运行：

```bash
uv sync --frozen --all-packages --all-groups

uv run ruff check src tests examples packages scripts

uv run ruff format --check src tests examples packages scripts

uv run mypy src/onlyalpha
```

以及当前正式 Provider mypy gates。

---

# 99. Test Gates

至少运行：

```bash
uv run python scripts/test_suite.py fast

uv run python scripts/test_suite.py integration

uv run python scripts/test_suite.py core-full

uv run python scripts/test_suite.py recovery

uv run python scripts/test_suite.py ashare

uv run python scripts/test_suite.py miniqmt-contract

uv run python scripts/test_suite.py exhaustive
```

若最新 master 已修改正式 lane：

使用最新仓库命令。

---

# 100. Build Gate

必须：

```bash
uv build --all-packages
```

通过。

---

# 101. Remote Gate

P4.3 只有在最新 commit 的：

```text
Layered Quality
```

最终：

```text
quality-gate = success
```

后才能宣告完成。

本地 PASS 不够。

---

# 102. Product Conformance Gate 最好进入正式 CI

如果当前：

```text
ashare
```

lane 适合作为正式 Product Gate：

把新的 Production Product Conformance 纳入该 lane。

如果语义差异明显：

可以给现有 ashare suite 增加明确分类。

不要为了 P4.3 新造一整套重复 CI framework。

---

# 103. Definition of Done — Product Contract

* [ ] `CN_A_SHARE_DURABLE_BACKTEST_V1` 或等价 Product Contract 明确。
* [ ] Supported surface 明确。
* [ ] Unsupported surface 明确。
* [ ] XSHG/XSHE coverage 声明与测试一致。
* [ ] COMMON_STOCK scope 明确。
* [ ] CASH/LONG/NETTING/LIMIT scope 明确。
* [ ] Product Contract 不夸大为“完整中国股票市场”。

---

# 104. Definition of Done — Production Authority

* [ ] 使用 Production A-share Reference Authority。
* [ ] 使用正式 CN_A_SHARE_CASH Market Profile。
* [ ] 使用 Production Market Fee Pack。
* [ ] 使用 explicit versioned Broker Fee Contract。
* [ ] Product Gate 不使用 Test Fee Pack。
* [ ] Dataset 日期在所有 required Authority effective range 内。
* [ ] Authority identity/version/fingerprint 可追踪。

---

# 105. Definition of Done — BUY OPEN

* [ ] Pre-Trade 正确。
* [ ] Risk 正确。
* [ ] Order 正确。
* [ ] Cash Reservation 正确。
* [ ] Strategy Cash Reservation 正确。
* [ ] Broker Accepted Durable。
* [ ] Fill Durable。
* [ ] Position 正确。
* [ ] Allocation 正确。
* [ ] Account 正确。
* [ ] Strategy Ledger 正确。
* [ ] Fee 正确。
* [ ] Settlement 正确。
* [ ] Risk Reservation 正确。

---

# 106. Definition of Done — T+1

* [ ] Day D BUY 后 Position 存在。
* [ ] Day D BUY 后对应资产不可同日卖出。
* [ ] Same-day SELL 被 Market Rule 拒绝。
* [ ] Same-day SELL 不到 Broker。
* [ ] Settlement maturity 使用 Durable Transaction。
* [ ] Day D+1 sellable/trade-available 正确增加。
* [ ] Replay maturity idempotent。
* [ ] 无 A-share execution hardcode。

---

# 107. Definition of Done — SELL CLOSE

* [ ] T+1 后 SELL pre-trade 通过。
* [ ] Position Reservation 正确。
* [ ] Broker Accepted Durable。
* [ ] Fill Durable。
* [ ] Position 减少正确。
* [ ] Allocation 减少正确。
* [ ] Close cost attribution 正确。
* [ ] Account 正确。
* [ ] Strategy Ledger 正确。
* [ ] Settlement 正确。
* [ ] Risk 正确。
* [ ] Fee components 正确。

---

# 108. Definition of Done — Production Fee

* [ ] BUY Market Fee component 正确。
* [ ] SELL Market Fee component 正确。
* [ ] SELL-only Stamp Duty 正确。
* [ ] Transfer Fee 正确。
* [ ] Broker Commission 独立于 Market Fee。
* [ ] Fee rule/schedule identity 可追踪。
* [ ] Round semantics 正确。
* [ ] Component-level assertions 存在。
* [ ] 不只验证 total fee。

---

# 109. Definition of Done — Multi-Fill

* [ ] BUY multi-fill。
* [ ] SELL multi-fill。
* [ ] Order cumulative quantity 正确。
* [ ] Position incremental 正确。
* [ ] Allocation incremental 正确。
* [ ] Reservation remaining 正确。
* [ ] Risk remaining 正确。
* [ ] Fee incremental 正确。
* [ ] Fee cumulative 正确。
* [ ] Minimum Broker Commission 正确。
* [ ] 最低佣金不会每 Fill 重复应用。

---

# 110. Definition of Done — Terminal

* [ ] BUY partial + Cancel。
* [ ] SELL partial + Cancel。
* [ ] BUY Reject。
* [ ] SELL Reject before Accepted。
* [ ] Expire。
* [ ] 已提交 Fill 永不 rollback。
* [ ] 只释放 remaining reservation。
* [ ] Account/Ledger parity 保持。
* [ ] Risk active-order semantics 正确。
* [ ] Broker terminal facts 全部 Durable。

---

# 111. Definition of Done — Persistence

* [ ] Memory product scenario PASS。
* [ ] SQLite product scenario PASS。
* [ ] SQLite state 可以关闭/重新实例化。
* [ ] 不依赖同一 Runtime object 才能恢复。

---

# 112. Definition of Done — Recovery

* [ ] Accepted crash recovery。
* [ ] Trade crash recovery。
* [ ] Partial-fill recovery。
* [ ] Terminal recovery。
* [ ] Settlement recovery。
* [ ] A→B→C restart scenario。
* [ ] Forward-only recovery。
* [ ] Duplicate Broker Fact idempotent。
* [ ] Same identity different payload conflict。
* [ ] Recovered final authority == uninterrupted。
* [ ] Recovered committed history == uninterrupted canonical history。

---

# 113. Definition of Done — Determinism

* [ ] Same input repeated run yields same result fingerprint。
* [ ] Same input repeated run yields same artifact fingerprint。
* [ ] Same transaction identities。
* [ ] Same economic event ordering。
* [ ] Same fee facts。
* [ ] Same settlement facts。
* [ ] Restart does not alter canonical result。

---

# 114. Definition of Done — Architecture

* [ ] Execution Core 无 `CN_A_SHARE_CASH` branch。
* [ ] 无 `AshareTradePlanner`。
* [ ] 无 `AshareTerminalPlanner`。
* [ ] 无 product-specific Execution Reducer。
* [ ] T+1 不在 Execution 重写。
* [ ] Fee 不在 Execution 重写。
* [ ] Market Rules 仍由 Market Authority 产生。
* [ ] Product Harness 不绕开 Composition Root。
* [ ] 无 direct Manager write shortcut。
* [ ] 无旧 compatibility fallback。

---

# 115. Definition of Done — Clean Code

* [ ] 删除无职责旧接口。
* [ ] 删除误导性 Generic/T0 历史命名。
* [ ] 删除 dead helper/import。
* [ ] 删除不再使用的 test-only production exposure。
* [ ] 无 deprecated alias。
* [ ] 无 compatibility wrapper。
* [ ] 无 commented-out historical implementation。
* [ ] 无大型 TODO 表示“以后再删”。

Git 保存历史。

生产代码只保留当前真实语义。

---

# 116. Definition of Done — Documentation

* [ ] Pre-implementation audit 完成。
* [ ] Product ADR 完成。
* [ ] P4.3 implementation/conformance report 完成。
* [ ] README 更新真实产品状态。
* [ ] Roadmap 更新 P4.3 完成状态。
* [ ] Documentation 不再把旧 MiniQMT test fee conformance 描述成 Production Product。
* [ ] Product limitations 明确。

---

# 117. Definition of Done — Quality

* [ ] dependency sync PASS。
* [ ] Ruff PASS。
* [ ] Ruff Format PASS。
* [ ] Core mypy PASS。
* [ ] Provider mypy PASS。
* [ ] fast PASS。
* [ ] integration PASS。
* [ ] core-full PASS。
* [ ] recovery PASS。
* [ ] ashare PASS。
* [ ] miniqmt-contract PASS。
* [ ] exhaustive PASS。
* [ ] build PASS。
* [ ] GitHub final quality-gate PASS。

---

# 118. P4.3 明确非目标

本任务不实现：

```text
Market Product Composition Neutralization

Reference Provider generic SPI

Market compiler provider SPI

Paper Streaming Recovery

Live Runtime

Durable Broker Outbound Command

Broker command retry

Broker outbound idempotency

Real Broker synchronization

Margin

Short

Hedging

Futures

Crypto

Options

Multi-account product

Multi-broker product

Multi-data-source product

Vectorized Backtest

Distributed Runtime

Web/API product
```

这些都不能因为“顺便比较容易”混入 P4.3。

---

# 119. 什么时候允许修改 Production Kernel

只有 Product Conformance 暴露真实 kernel bug 时。

每次修改前必须先明确：

```text
Violating invariant

Correct owner

Market-specific or market-neutral

Why current instruction/authority is insufficient

Why proposed fix belongs in this module
```

---

# 120. 如果修复需要出现 A 股名字

先暂停。

重新判断：

```text
是不是错误地把 Market Authority 泄漏进 Core？
```

除以下合法位置：

```text
market/ashare_rules
reference/ashare
fee/packs/cn_a_share
product conformance tests/docs
```

Core Execution 一般不应该需要 A 股名字。

---

# 121. 不做“为了 Conformance 而 Conformance”

不要写：

```text
assert run completed
```

就结束。

Product Gate 必须证明：

```text
economic semantics

authority provenance

durability

recovery

determinism
```

---

# 122. P4.3 最终结果必须可以回答

完成后，Implementation Report 必须能明确回答：

### 交易合法性

```text
为什么 BUY 被接受？
为什么 Day D SELL 被拒绝？
为什么 D+1 SELL 被接受？
```

### 费用

```text
为什么 BUY 收这些费用？
为什么 SELL 收这些费用？
为什么 minimum commission 是这个结果？
```

### Authority

```text
用了哪个 Reference？
哪个 Market Profile？
哪个 Market Fee Pack？
哪个 Broker Contract？
哪个 Execution Support Policy？
```

### Durability

```text
Accepted 如何 durable？
Fill 如何 durable？
Terminal 如何 durable？
Settlement 如何 durable？
```

### Recovery

```text
在哪些 crash point 做过验证？
为什么恢复后与 uninterrupted 完全一致？
```

---

# 123. P4.3 成功后的正式能力声明

可以声明：

> **OnlyAlpha has a conformance-verified CN A-share Cash-Long Durable Backtest Product for the explicitly certified ordinary-common-stock surface.**

可以声明：

```text
Production Reference semantics

Production Market Rules

Production Fee Authority

Durable Accepted/Trade/Terminal lifecycle

T+1 Settlement

Partial/Multi-Fill economics

Memory/SQLite

Forward Recovery

Deterministic Result/Artifact
```

全部在同一产品纵切面被验证。

---

# 124. P4.3 完成后不能声明

不能直接声明：

```text
OnlyAlpha supports all China A-shares

CN_A_SHARE_CASH fully models every exchange rule

Paper is production ready

Live is production ready

Margin is supported

Short is supported
```

Product certification 必须等于实际测试边界。

---

# 125. P4.3 后的下一阶段

完成本任务后：

```text
P4.3
CN A-share Production Durable Product Conformance
        ↓
DONE
```

下一阶段才进入：

```text
P5
Market Product Composition Neutralization
```

P5 再处理：

```text
Backtest/Paper factory A-share branch

Reference provider abstraction

Market-specific compiler registration

Market Product composition authority
```

不要在本任务提前做。

---

# 126. 最终工程判断标准

当：

```text
“组件已经存在”
```

与：

```text
“产品已经证明”
```

冲突时：

> 只有完整 Product Conformance 才算完成。

当：

```text
Testing Convenience
```

与：

```text
Production Authority
```

冲突时：

> 使用 Production Authority。

当：

```text
Market-specific shortcut
```

与：

```text
Market-neutral Kernel
```

冲突时：

> 修正 Authority/Instruction，禁止 shortcut。

当：

```text
最终状态一致
```

与：

```text
Committed History 不一致
```

冲突时：

> Recovery 不通过。

当：

```text
旧接口方便旧测试
```

与：

```text
Clean Single Authority
```

冲突时：

> 修改测试并删除旧接口。

当：

```text
更多抽象
```

与：

```text
完成第一个真实产品
```

冲突时：

> 优先完成真实产品。

---

# 127. P4.3 的最终定义

P4.3 不是：

> “写一个 A 股 E2E test。”

不是：

> “让 `CN_A_SHARE_CASH` 能跑。”

不是：

> “把 TEST Fee Pack 换成 Production Fee Pack。”

P4.3 真正完成的是：

> **在一个严格冻结且明确有限的普通 A 股 Cash-Long 产品边界内，使用 Production Reference、Production Market Rules、Production Fee Authority 和 Explicit Broker Contract，通过 OnlyAlpha 正式 Composition Root 和 Canonical Durable Transaction Kernel，完整证明 BUY OPEN、Broker Accepted、Whole/Partial/Multi-Fill、T+1、SELL CLOSE、Cancel/Reject/Expire、Memory/SQLite、Checkpoint/Restart/Forward Recovery 与 Deterministic Artifact 全链路成立。**

最终必须得到：

```text
                    CN A-Share
                 Production Product
                         │
                         ▼
                 Reference Authority
                         │
                         ▼
                  Market Rule Engine
                         │
                         ▼
                   Order / Risk
                         │
                         ▼
               Reservation Authorities
                         │
                         ▼
                   Virtual Broker
                         │
          ┌──────────────┼──────────────┐
          ▼              ▼              ▼
       ACCEPTED         TRADE         TERMINAL
          │              │              │
          └──────────────┼──────────────┘
                         ▼
               Durable Transaction
                         │
                         ▼
         Explicit Ordered Projections
                         │
          ┌──────────────┼──────────────┐
          ▼              ▼              ▼
       Position       Account       Settlement
       Allocation     Ledger          Fee/Risk
          └──────────────┼──────────────┘
                         ▼
                    T+1 Maturity
                         │
                         ▼
                    SELL CLOSE
                         │
                         ▼
               Persistence / Recovery
                         │
                         ▼
              Result / Artifact / Proof
```

并严格满足：

```text
Production Authorities Only

Market Rules Decide Legality

Execution Support Decides Implementation

Execution Core Remains Market-Neutral

Historical Facts Are Immutable

One Domain → One Write Authority

Broker Lifecycle Remains Durable

Settlement Remains Durable

Recovery Is Forward-Only

Recovered History = Canonical History

Same Input = Same Product Result

Unsupported Surface Fails Closed

No Obsolete Compatibility Interfaces

No New Framework Without a Real Need
```

只有当这些原则全部落实到：

```text
product contract
dataset
composition
market rules
fees
execution
settlement
persistence
recovery
tests
artifacts
architecture guards
documentation
```

并且最新远端 Quality Gate 完整绿色时：

> **P4.3 才算完成。**
