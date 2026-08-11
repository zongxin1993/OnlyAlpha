# OnlyAlpha P6.0 — Trading Runtime Kernel Extraction

你正在维护 OnlyAlpha 项目：

Repository:
`https://github.com/zongxin1993/OnlyAlpha`

本任务实现 **P6.0 — Trading Runtime Kernel Extraction**。

这是一次架构重构任务，不是功能扩展任务。

你的首要目标不是减少文件行数，而是从第一性原理修复当前 Runtime 架构中的错误依赖关系：

```text
当前：

OnlyBacktestRuntime
        ↑
OnlyStreamingRuntime
        ↑
OnlyPaperRuntime

Backtest Runtime 实际承载大量通用 Trading Kernel 职责，
Streaming 为复用这些交易能力而继承 Backtest。
```

目标架构：

```text
                    OnlyTradingKernel
                    /       |       \
                   /        |        \
             Backtest     Streaming   Future Live/Sim
                 │            │
              Driver        Driver
```

最终原则：

```text
Trading Runtime
=
Trading Kernel
+
Runtime Driver
```

其中：

```text
Trading Kernel
负责：
    Market Rule
    Risk
    Reservation
    Order
    Execution Processing
    Transaction
    Projection
    Position
    Allocation
    Account
    Strategy Ledger
    Fee
    Settlement
    Reconciliation
    Trading Recovery
    Strategy/Cluster shared processing

Runtime Driver
负责：
    Clock driving
    MarketData source
    Historical replay / realtime subscription
    bootstrap / handoff
    reconnect
    streaming worker
    lifecycle-specific driving
    broker deterministic stepping
    run termination
```

---

# 1. 第一原则

开始修改代码前，必须先完整阅读当前实现，不允许根据本提示词机械修改。

至少重点检查：

```text
src/onlyalpha/runtime/runtime.py

src/onlyalpha/runtime/backtest/runtime.py
src/onlyalpha/runtime/backtest/factory.py
src/onlyalpha/runtime/backtest/run_plan.py

src/onlyalpha/runtime/streaming/runtime.py
src/onlyalpha/runtime/streaming/

src/onlyalpha/runtime/paper/runtime.py
src/onlyalpha/runtime/paper/factory.py

src/onlyalpha/runtime/context.py
src/onlyalpha/runtime/factory.py
src/onlyalpha/runtime/assembler.py

src/onlyalpha/order/
src/onlyalpha/risk/
src/onlyalpha/execution/
src/onlyalpha/transaction/
src/onlyalpha/position/
src/onlyalpha/account/
src/onlyalpha/strategy_ledger/
src/onlyalpha/fee/
src/onlyalpha/settlement/
src/onlyalpha/market_data/
src/onlyalpha/cluster/

tests/
docs/architecture.md
docs/roadmap.md
docs/testing.md
```

先确认当前 HEAD 的实际结构。

如果当前实现已经与本提示词描述发生变化：

**以当前代码为事实来源，以本任务的架构原则和最终验收标准为目标，不要机械套用旧路径或旧类名。**

---

# 2. P6.0 要解决的根问题

从第一性原理看：

Backtest、Sim、Live 的交易经济语义应该相同。

对于相同的：

```text
TradingState(t)
MarketFact
BrokerFact
TradingAuthority
EconomicConfig
```

应该得到相同：

```text
TradingState(t+1)
```

也就是说 Trading Kernel 的状态转换逻辑中：

**RuntimeMode 不应该成为交易经济决策输入。**

Kernel 内禁止通过：

```python
if runtime_mode == BACKTEST:
    ...

if runtime_mode == PAPER:
    ...

if runtime_mode == SIM:
    ...

if runtime_mode == LIVE:
    ...
```

改变：

```text
Market legality
Risk
Reservation
Order economics
Position economics
Fee
Settlement
Transaction
Projection
Strategy behavior
```

Runtime Type 只能影响：

```text
Driver
Clock
DataSource
Broker implementation
Lifecycle
Recovery driver policy
Operational behavior
```

---

# 3. 本任务明确不做什么

P6.0 必须保持 scope 克制。

禁止在本任务中：

```text
1. 实现 SIM Runtime
2. 实现 LIVE Runtime
3. 删除 PAPER
4. 删除 Shadow execution
5. 重写 Virtual Broker
6. 修改 Order 生命周期语义
7. 修改 Position accounting
8. 修改 Allocation accounting
9. 修改 Fee 经济语义
10. 修改 Settlement 语义
11. 修改 Risk 业务语义
12. 修改 Transaction schema
13. 修改 Projection ordering
14. 修改 Market Product IR
15. 扩展 A-share 产品能力
16. 增加 Futures / Crypto / Margin / Short 等业务能力
17. 引入 DI framework
18. 引入新的 CommandBus / MessageBus 框架
19. 因“代码不好看”进行无关清理
20. 为未来功能进行没有当前需求支撑的过度抽象
```

核心原则：

```text
Move
Wire
Delegate
Delete duplicate assembly
```

而不是：

```text
Redesign trading economics
```

---

# 4. 最终依赖方向

P6.0 完成后依赖方向必须满足：

```text
runtime/backtest
        │
        ▼
runtime/trading

runtime/streaming
        │
        ▼
runtime/trading
```

严格禁止：

```text
runtime/trading
        ↓
runtime/backtest
```

严格禁止：

```text
runtime/trading
        ↓
runtime/streaming
```

严格禁止：

```text
runtime/streaming
        ↓
runtime/backtest
```

尤其必须消除类似：

```python
class OnlyStreamingRuntime(OnlyBacktestRuntime):
```

这样的继承关系。

---

# 5. 引入 Trading Kernel

建议建立：

```text
src/onlyalpha/runtime/trading/
```

初始结构优先保持简单：

```text
runtime/trading/
├── __init__.py
├── config.py
├── kernel.py
├── builder.py
└── services.py
```

不要为了架构形式一次创建十几个 Facade / Coordinator / Provider。

优先只引入一个真正重要的聚合对象：

```python
class OnlyTradingKernel:
    ...
```

它表示：

**一个 Trading Runtime 内所有共享 mutable trading authorities 和确定性交易状态转换能力的唯一组合根。**

---

# 6. Trading Kernel 的责任

OnlyTradingKernel 应逐步拥有当前属于通用 Trading Runtime 的能力。

包括但不限于：

## Authorities

```text
PositionManager
PositionAllocationManager
PositionReservationManager

AccountReservationManager
AccountManager
AccountPerformanceProjector

StrategyLedgerManager
StrategyLedgerLocator

SettlementAuthority
MarginManager

FeeApplicationLedger
FeeReconciliationAuthority
FeeReconciliationRiskGate
```

## Trading execution

```text
OrderManager
OrderQueryService
OrderService
OrderUpdateProcessor

RiskService

Cash / Position reservations

ExecutionService
BrokerInboundQueue
ExecutionProcessor

Execution audit
Execution deduplication
Execution sequence tracking
Execution reconciliation
```

## Transaction / projection / recovery

```text
RuntimeTransactionCoordinator
Transaction queries
Projection state
Projection-ready query
Outbox
ExecutionEventBuffer
ExecutionDeliveryCoordinator
ExecutionOutboxPublisher
ExecutionRecoveryService
```

## Shared Strategy / Market processing

对于 Backtest / Sim / Live 必须保持交易语义一致的：

```text
MarketDataCache
AggregationManager
IndicatorPipeline
MarketDataPipeline
StrategyBarDispatcher
ClusterManager
Risk snapshot preparation
Strategy context construction
shared market processing
```

应属于 Trading Kernel 或明确的 Kernel-owned service bundle。

---

# 7. Kernel 明确不拥有的能力

禁止把以下 Runtime Driver 职责塞入 Kernel：

```text
Historical DataSource selection
Realtime DataSource selection

Historical replay policy
Realtime subscription

Streaming bootstrap
Historical-to-live handoff
Watermark
Catch-up
Gap recovery driver
Reconnect

Live worker thread
Streaming queue lifecycle
Live bar finalization lifecycle

Backtest finite run loop
Runtime termination condition

Virtual Broker deterministic clock stepping
Real Broker reconnect policy
```

Kernel 处理已经规范化的 Trading Facts。

Driver 负责事实如何到达 Kernel。

---

# 8. Kernel Config 必须 Runtime-neutral

检查现有：

```python
OnlyRuntimeAssemblyConfig
```

当前如果同时混合：

```text
Runtime identity
Runtime mode
Trading economic config
Resolved services
```

需要进行最小必要拆分。

建议形成类似：

```python
@dataclass(frozen=True, slots=True)
class OnlyTradingKernelConfig:
    engine_id: OnlyEngineId
    runtime_id: OnlyRuntimeId

    default_account_id: OnlyAccountId
    base_currency: OnlyCurrency

    strategy_capitals: Mapping[OnlyClusterId, OnlyMoney]
    account_initial_cash: OnlyMoney

    event_capacity: int
    history_limit: int

    cluster_error_policy: OnlyRuntimeErrorPolicy
```

具体字段必须以当前代码真实需求为准。

关键要求：

`OnlyTradingKernelConfig` 中禁止出现：

```python
OnlyRuntimeMode
```

Kernel 不应通过：

```text
BACKTEST
PAPER
SIM
LIVE
```

决定交易行为。

---

# 9. Dependencies 与 Config 分开

不要把已经 resolve 的运行时组件塞进纯配置对象。

概念上应区分：

```text
OnlyTradingKernelConfig
    =
    immutable economic / identity configuration

OnlyTradingKernelDependencies
    =
    already resolved runtime dependencies
```

Dependencies 可包括：

```text
Clock
EventBus
Market Product binding
Market Rule authority
Broker Fee Contract
Fee Basis Provider
Fee Reconciliation Policy
Execution submission port
Broker inbound port
Persistence Store
Calendar / Reference authority
```

具体是否建立单独 dataclass，由当前代码复杂度决定。

不要为了形式而抽象。

---

# 10. Builder 只负责组装 Kernel

可以增加：

```python
OnlyTradingKernelBuilder
```

但必须严格控制职责。

Builder 允许：

```text
create trading authorities
wire managers
wire order/risk/execution
wire transaction/projection
wire shared strategy processing
return OnlyTradingKernel
```

Builder 禁止：

```text
解析 YAML
判断 BACKTEST/PAPER/SIM/LIVE
选择 DataSource plugin
选择 Broker plugin
创建 Historical request
创建 Realtime subscription
决定 Runtime lifecycle
决定 Backtest run termination
```

这些仍由 Runtime Factory / Driver 层负责。

---

# 11. 不允许 Kernel Builder 成为新的 God Factory

如果 builder.py 开始出现大量：

```python
if runtime_type ...
if datasource_type ...
if broker_type ...
if backtest ...
if live ...
```

说明设计方向错误。

正确模型：

```text
BacktestFactory
    ├─ resolve Historical DataSource
    ├─ resolve Virtual Broker
    ├─ create BacktestClock
    ├─ create Persistence
    │
    └─ TradingKernelBuilder.build(...)
```

未来：

```text
SimFactory
    ├─ resolve realtime DataSource
    ├─ resolve Virtual Broker
    ├─ create LiveClock
    │
    └─ TradingKernelBuilder.build(...)
```

Kernel 不知道两者区别。

---

# 12. Service Bundle 要克制

当前如果存在巨大的：

```python
OnlyRuntimeServices
```

不要简单重命名为：

```python
OnlyTradingKernelServices
```

然后继续保留 Service Locator。

建议根据实际代码最多先形成三类内部 bundle：

```text
OnlyTradingAuthorities

OnlyTradingExecutionServices

OnlyTradingMarketServices
```

概念：

```python
@dataclass(slots=True)
class OnlyTradingAuthorities:
    account: ...
    position: ...
    allocation: ...
    ledger: ...
    settlement: ...
    margin: ...
    fee_application: ...
```

```python
@dataclass(slots=True)
class OnlyTradingExecutionServices:
    order_manager: ...
    order_service: ...
    risk_service: ...
    broker_inbound: ...
    execution_processor: ...
    transaction_coordinator: ...
    recovery_service: ...
```

```python
@dataclass(slots=True)
class OnlyTradingMarketServices:
    market_data_pipeline: ...
    aggregation_manager: ...
    indicator_pipeline: ...
    dispatcher: ...
    cluster_manager: ...
```

这是内部实现细节。

不要把这些 bundle 暴露成公共 Service Locator。

---

# 13. Kernel 外部 API 必须小

Runtime Driver 不应该直接操作：

```python
kernel.account_manager
kernel.position_manager
kernel.order_manager
kernel.risk_service
```

否则 Driver 会重新与内部经济 Authority 耦合。

优先形成少量明确入口，例如：

```python
kernel.add_cluster(...)

kernel.initialize()
kernel.start()

kernel.process_market_update(...)
kernel.process_broker_updates()

kernel.recover(...)
kernel.checkpoint(...)

kernel.snapshot()

kernel.stop()
kernel.close()
```

具体命名应服从现有项目风格。

不要强行为了符合本提示词改所有名字。

要求是：

**Driver 与 Kernel 之间的交互边界必须明显小于 Kernel 内部服务数量。**

---

# 14. Driver 只处理外部世界

建立明确概念：

```text
Historical Data
      │
      ▼
Backtest Driver
      │
      ▼
Normalized Market Facts
      │
      ▼
Trading Kernel
```

以及：

```text
Realtime Data
      │
      ▼
Streaming Driver
      │
      ▼
Normalized Market Facts
      │
      ▼
Trading Kernel
```

Broker：

```text
Virtual Broker
    ↓
Broker Facts

Real Broker
    ↓
Broker Facts

        ↓
Trading Kernel
```

Kernel 不关心 Broker Fact 是模拟生成还是外部真实产生。

---

# 15. Backtest Runtime 重构目标

P6.0 后：

```text
OnlyBacktestRuntime
├── OnlyTradingKernel
└── OnlyBacktestDriver
```

Backtest Runtime 应成为较薄的产品 Facade。

真正 Backtest-specific 的能力保留在 Driver：

```text
Historical request
Historical replay
BacktestClock advancement
finite start/end
deterministic broker stepping
Backtest progress / result construction
```

不要追求某个固定行数。

判断标准不是文件大小，而是：

**BacktestRuntime 中不再创建通用 Trading Authority。**

---

# 16. Streaming Runtime 必须拆掉错误继承

当前 Streaming 如果通过继承 Backtest Runtime 获得 Trading 能力：

必须消除。

把 Streaming-specific 内容抽成类似：

```python
OnlyStreamingMarketDataDriver
```

它负责：

```text
subscribe-first bootstrap
Historical warmup
historical-to-live handoff
watermark
overlap filtering
duplicate tracking
sequence gap detection
catch-up
aggregation handoff
live bar finalization
worker lifecycle
health
unsubscribe / shutdown
```

但：

```text
Order
Risk
Account
Position
Transaction
Projection
Fee
Settlement
```

不能属于 Streaming Driver。

---

# 17. PAPER 在 P6.0 暂时保留

本阶段不要急于删除：

```text
OnlyPaperRuntime
OnlyShadowExecutionService
PAPER config
```

P6.0 完成时 legacy Paper 应能表达为：

```text
Trading Kernel
+
Streaming Driver
+
Shadow Execution
```

而不再：

```text
Paper
IS-A
Streaming
IS-A
Backtest
```

PAPER / SHADOW 的真正删除留给后续 P6 阶段。

---

# 18. Runtime 基类也需要去 Trading 污染

检查当前：

```python
OnlyRuntime
```

如果其构造函数直接创建：

```text
PositionManager
AllocationManager
AccountManager
StrategyLedgerManager
Fee authority
Settlement authority
...
```

则说明 Base Runtime 被 Trading 产品语义污染。

P6.0 应逐步把这些 ownership 移入：

```python
OnlyTradingKernel
```

最终 Base Runtime 应尽可能只负责：

```text
Runtime identity
Runtime state
generic lifecycle
plugin resource ownership
diagnostics
basic operational state
```

原因：

未来：

```text
Research Runtime
```

不应该因为继承 Base Runtime 就自动创建：

```text
Account
Position
Order
Broker
Settlement
```

---

# 19. Context 必须避免 Mode 泄漏

检查：

```python
OnlyRuntimeContext
```

如果 Strategy-visible Context 中存在：

```python
mode: OnlyRuntimeMode
```

不要在本任务中贸然进行大规模 public API 破坏，但要评估并开始清除不必要 mode dependency。

目标是最终 Strategy 不应通过：

```python
if context.mode == BACKTEST:
    ...

if context.mode == LIVE:
    ...
```

改变策略经济行为。

如果本次修改该字段风险过大：

1. 不要为了完成形式要求破坏大量稳定 API。
2. 增加 architecture debt note/test。
3. 确保新 Trading Kernel 内绝不依赖 RuntimeMode。
4. 将 Context mode 删除留给紧接 P6.0 的 mode-neutralization 子任务。

重点：

P6.0 首先解决 ownership 和 dependency inversion。

---

# 20. Hot path 保持简单高效

不要因为架构重构引入：

```text
Command Bus
Generic Message Bus
Reflection
Dynamic container lookup
Runtime DI framework
多层 Facade
无价值 Adapter chain
```

对于高频路径优先：

```python
kernel.process_market_update(update)
```

内部使用稳定对象直接调用。

例如：

```text
Market processor
    ↓
Pipeline
    ↓
Dispatcher
    ↓
Strategy
```

不要为了“解耦”全部改成 EventBus。

---

# 21. EventBus 原则

保持：

```text
Commit Fact First
Project State Second
```

EventBus 主要用于：

```text
facts publication
observation
diagnostics
subscriptions
```

不要让 EventBus 重新成为 mutable trading state 的最终写 Authority。

不要修改已有 transaction/projection 正确性模型。

---

# 22. 执行方法：必须小步迁移

严禁一次性重写整个 BacktestRuntime。

按照以下阶段执行。

---

## P6.0-A — Freeze Current Behavior

修改生产代码前补齐必要 characterization tests。

至少确保现有：

```text
BUY OPEN
SELL CLOSE
whole fill
partial fill
multi-fill
cancel
reject
expire
fee
settlement
position
allocation
account
strategy ledger
checkpoint/recovery
```

重要事实可被当前测试覆盖。

Streaming / Paper 至少覆盖：

```text
bootstrap
warmup
handoff
watermark
catch-up
observation
shadow order suppression
shutdown
```

优先复用现有测试，不要无意义重复测试。

如果已有覆盖充分，记录证据即可。

---

## P6.0-B — Introduce Kernel Contracts

新增：

```text
runtime/trading/
```

建立：

```text
OnlyTradingKernel
OnlyTradingKernelConfig
必要的内部 services / builder
```

初期允许 Kernel 包裹部分旧对象。

这一阶段不追求把所有代码立即移动完成。

目标是先建立正确 ownership boundary。

---

## P6.0-C — Move Mutable Trading Authorities

优先移动：

```text
Position
Allocation
PositionReservation

Account
AccountReservation
AccountPerformance

StrategyLedger

Settlement
Margin
Fee application/reconciliation
```

原则：

**先移动 ownership，不改变 implementation。**

例如以前：

```python
runtime._account_manager
```

可以临时 delegate 到：

```python
runtime._trading_kernel...
```

保证外部行为不变。

---

## P6.0-D — Move Execution Kernel

整体迁移：

```text
Order
Risk
Reservation
ExecutionProcessor
Execution state
Transaction
Projection
Outbox
Execution recovery
```

避免形成：

```text
一半 execution 在 Runtime
一半 execution 在 Kernel
```

迁移完成后，Kernel 应成为从 Order Intent / Broker Fact 到 durable trading state 的唯一组合根。

---

## P6.0-E — Move Shared Market / Strategy Processing

迁移：

```text
MarketDataCache
Aggregation
IndicatorPipeline
MarketDataPipeline
Dispatcher
ClusterManager
Trading Context wiring
Risk snapshot preparation
```

前提：

这些属于 Backtest / Sim / Live 应共享的 Trading semantics。

不要把 Historical Replay 或 Streaming bootstrap 一并搬进去。

---

## P6.0-F — Backtest = Kernel + Driver

建立或整理：

```python
OnlyBacktestDriver
```

将：

```text
Historical replay
Backtest clock advancement
deterministic broker stepping
finite loop
```

从 Trading Kernel 责任中彻底隔离。

最终：

```text
OnlyBacktestRuntime
=
OnlyTradingKernel
+
OnlyBacktestDriver
```

并保持所有现有 Backtest 行为一致。

---

## P6.0-G — Streaming = Driver

把 Streaming-specific 行为提取成：

```python
OnlyStreamingMarketDataDriver
```

或符合项目命名约定的等价对象。

最终删除：

```text
Streaming Runtime -> Backtest Runtime
```

的继承/实现依赖。

legacy Paper 暂时使用：

```text
TradingKernel
+
StreamingDriver
+
ShadowExecution
```

---

# 23. 必须新增 Architecture Gates

P6.0 必须有自动化架构测试防止未来回退。

至少验证：

### Gate 1

Streaming 不得依赖 Backtest Runtime：

```text
runtime/streaming
```

不得 import：

```text
onlyalpha.runtime.backtest
```

如果个别纯 DTO 确有合理共享需求，应优先将 DTO 提升到 neutral package，而不是给例外。

---

### Gate 2

Trading Kernel 不得依赖 concrete Runtime：

```text
runtime/trading
```

不得 import：

```text
runtime/backtest
runtime/paper
runtime/streaming
runtime/live
runtime/sim
```

---

### Gate 3

Trading Kernel 不得依赖 Runtime Mode

在：

```text
src/onlyalpha/runtime/trading/
```

中原则上禁止：

```text
OnlyRuntimeMode
BACKTEST
PAPER
SIM
LIVE
```

如果字符串仅存在 documentation/test description，不算生产依赖。

---

### Gate 4

Backtest-specific driver 不得反向进入 Kernel。

保持：

```text
backtest -> trading
```

而不是：

```text
trading -> backtest
```

---

# 24. 保持 API 兼容性

P6.0 是内部架构迁移。

不要为了内部重构无必要破坏：

```text
OnlyEngine
OnlyBacktestRuntime public behavior
Backtest result
query APIs
existing plugin contracts
existing config schema
```

如果旧 Runtime 暴露某些 manager properties，并且测试或用户 API 依赖：

可以暂时 delegate：

```python
@property
def position_manager(self):
    return self._kernel....
```

但新增代码不要继续依赖这种 Service Locator 风格。

兼容 delegate 应标注为迁移债务，而不是新的设计方向。

---

# 25. 测试要求

每个阶段修改后执行合适的最小测试。

最终必须至少执行项目正式质量门禁，包括当前仓库实际存在的：

```text
Ruff check
Ruff format check
strict mypy core
plugin mypy where applicable

fast
integration
recovery
ashare
core-full
```

以及任何 Architecture tests。

如果项目测试入口已经发生变化：

以当前：

```text
docs/testing.md
pyproject.toml
.github/workflows/
```

为准。

不要自行创造与仓库规范冲突的新测试入口。

---

# 26. 行为一致性要求

P6.0 前后必须保持：

```text
same input
+
same configuration
+
same broker facts

=> same trading facts
```

特别关注：

```text
Orders
Accepted
Trades
Terminal state

Reservations

Transactions
transaction ordering
transaction fingerprints

Position
Allocation
Account
Strategy Ledger

Fees
Settlement
PnL

Recovery result
Backtest result fingerprint
```

如果 snapshot / IDs 中有合理的非业务 implementation metadata 差异，需要明确解释。

不得默默修改 golden result。

---

# 27. 性能要求

本任务不是性能优化项目，但重构不得显著恶化 hot path。

避免：

```text
大量临时对象
多层动态 Protocol dispatch
重复 dict lookup
重复 resolve service
重复 serialization
EventBus 替代直接调用
```

Kernel 创建后应保存稳定引用。

hot path 优先简单直接。

---

# 28. 文件与代码风格要求

遵守项目现有风格：

```text
Python 3.12
slots where project convention uses slots
frozen immutable DTO where appropriate
strict mypy
Ruff
explicit ownership
fail closed
no magical fallback
```

不要引入新的第三方依赖。

不要增加不必要抽象。

如果一个新 class 只有转发行为且没有明确 invariant / ownership / boundary 意义：

不要创建。

---

# 29. 文档要求

完成实现后更新：

```text
docs/architecture.md
docs/roadmap.md
```

准确说明：

```text
Trading Kernel ownership
Driver responsibility
Backtest composition
Streaming composition
dependency direction
P6.0 completion boundary
```

不要宣称：

```text
SIM 已完成
LIVE 已完成
PAPER 已删除
Streaming recovery 已完成
```

如果它们实际上不属于 P6.0。

---

# 30. P6.0 完成定义

只有全部满足以下条件才能认为 P6.0 完成：

```text
[ ] Trading Kernel 已成为共享 Trading Authority/semantic ownership root

[ ] Base Runtime 不再直接拥有不必要的 Trading Authorities，
    或至少所有 remaining ownership 均有明确、临时、可解释的迁移原因

[ ] Backtest 通过 composition 使用 Trading Kernel

[ ] Streaming 不再继承 Backtest Runtime

[ ] runtime/streaming 不再依赖 runtime/backtest implementation

[ ] Trading Kernel 不依赖 concrete Runtime

[ ] Trading Kernel 不使用 RuntimeMode 控制交易经济逻辑

[ ] Historical replay / streaming bootstrap 等 Driver-specific
    行为没有进入 Trading Kernel

[ ] Existing Backtest semantics 未改变

[ ] Existing Paper semantics 未改变

[ ] Existing transaction/projection/recovery semantics 未改变

[ ] Architecture gates 已建立

[ ] Ruff 通过

[ ] mypy 通过

[ ] fast 通过

[ ] integration 通过

[ ] recovery 通过

[ ] ashare 通过

[ ] core-full 通过

[ ] CI 对应质量门禁具备通过条件

[ ] architecture.md 已更新

[ ] roadmap.md 已更新
```

---

# 31. 明确禁止的“伪完成”

以下情况不能算 P6.0 完成：

### 1.

仅仅把：

```text
backtest/runtime.py
```

拆成：

```text
backtest/account.py
backtest/order.py
backtest/execution.py
```

但 Streaming 仍然继承 Backtest。

这只是拆文件。

---

### 2.

新增：

```text
OnlyTradingKernel
```

但 Kernel 只是：

```python
self.backtest_runtime = backtest_runtime
```

这种 wrapper。

没有解决 ownership。

---

### 3.

把巨大：

```text
OnlyRuntimeServices
```

改名成：

```text
OnlyTradingKernelServices
```

其他结构完全不变。

没有解决 service locator 与 dependency ownership 问题。

---

### 4.

创建：

```text
OnlyTradingRuntime
```

然后形成：

```text
OnlyTradingRuntime
    ↓
OnlyBacktestRuntime
    ↓
OnlyStreamingRuntime
```

依然使用 inheritance sharing。

没有解决问题。

---

### 5.

为了避免 inheritance，复制一套：

```text
Order
Risk
Position
Account
Execution
```

到 Streaming。

这是严重错误。

---

### 6.

P6.0 顺手实现 SIM。

禁止。

必须先证明新的 Kernel / Driver 边界稳定，再进入 SIM 产品实现。

---

# 32. 开始工作时的执行顺序

开始任务后不要直接修改代码。

首先输出一个简短的 repository audit，说明：

```text
1. 当前 HEAD
2. 当前 Runtime inheritance
3. OnlyRuntime 当前 ownership
4. BacktestRuntime 当前主要职责
5. StreamingRuntime 当前主要职责
6. 哪些职责确定属于 Trading Kernel
7. 哪些职责确定属于 Driver
8. 计划修改哪些文件
9. 哪些现有测试作为 behavior baseline
```

然后立即开始实现，不要只给设计报告。

如果实际代码显示某个原计划不适合：

可以调整实现方式，但必须保持本任务定义的第一原则、依赖方向和验收条件。

---

# 33. 提交策略

优先保持小步、可验证改动。

推荐逻辑提交边界：

```text
1. tests: freeze P6.0 behavior and architecture baseline

2. runtime: introduce runtime-neutral trading kernel

3. runtime: move mutable trading authorities into kernel

4. runtime: move execution/transaction ownership into kernel

5. runtime: move shared strategy/market processing into kernel

6. backtest: compose runtime from trading kernel and backtest driver

7. streaming: remove backtest inheritance and introduce streaming driver

8. tests: enforce architecture dependency gates

9. docs: certify P6.0 architecture
```

如果当前工作环境不要求实际创建多个 Git commit，可以保持同样的逻辑 patch 边界。

---

# 34. 最终报告

完成后给出：

## Architecture Before

简述原来的错误依赖。

## Architecture After

明确展示：

```text
Trading Kernel
Backtest Driver
Streaming Driver
Runtime Facades
```

关系。

## Files Changed

按模块总结，不要逐文件流水账。

## Behavior Preservation

说明哪些已有测试证明交易语义未变化。

## Architecture Gates

列出新增 gate。

## Verification

列出实际执行命令和结果：

```text
Ruff
mypy
pytest lanes
```

不要声称没有实际执行的测试通过。

## Remaining Debt

只列真正属于后续：

```text
P6.1 Mode Neutralization
P6.2 SIM identity
P6.3 Virtual Broker streaming wiring
P6.4 gap/reconnect
P6.5 streaming checkpoint
...
```

的事项。

---

# 35. 最终工程原则

整个任务始终遵守：

```text
Economic state belongs to Trading Kernel.

External world belongs to Driver.

Runtime owns composition and lifecycle.

Shared behavior comes from composition,
not inheritance.

Trading Kernel does not know
whether it is running in Backtest, Sim or Live.
```

P6.0 最终不是为了得到更多抽象。

最终目标恰恰相反：

**删除错误抽象、减少隐式耦合、建立唯一 Trading ownership，使后续 SIM 只需实现实时 Driver + Virtual Broker wiring，而不再复制或继承 Backtest。**
