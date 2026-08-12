# OnlyAlpha P6.3 — SIM Realtime Virtual Broker Execution Wiring

Repository:

`https://github.com/zongxin1993/OnlyAlpha`

目标阶段：

# P6.3 — SIM Realtime Virtual Broker Execution Wiring

当前已完成：

```text
P6.0 — Trading Runtime Kernel Extraction
P6.1 — Runtime Control Boundary & Trading Semantic Neutralization
P6.2 — SIM Runtime Product Identity & Composition Contract
```

当前已知 P6.2 baseline：

```text
master
b2f5df9a2c6138b720f8a3a3a54e803d0d7584f0

Feat: SIM Runtime Product Identity & Composition Contract
```

该 SHA 的：

```text
static
build
core-full
recovery
ashare
miniqmt-contract
quality-gate
Nightly Exhaustive
```

均已经成功。

但执行本任务前：

**必须重新读取当前 master HEAD，不得假定上述 SHA 仍然是最新代码。**

---

# 1. 本任务目标

P6.3 只做一件事：

```text
把 P6.2 已经定义并验证的 SIM Product
从：

Recognized
+
Validated
+
Fail Closed

推进到：

Executable
```

完整目标链：

```text
Realtime MarketData
        ↓
Streaming Runtime
        ↓
Shared Trading Kernel
        ↓
Strategy
        ↓
Risk
        ↓
Reservation
        ↓
Order
        ↓
Virtual Broker
        ↓
Accepted / Trade / Terminal Broker Facts
        ↓
BrokerInboundQueue
        ↓
ExecutionProcessor
        ↓
Prepared Transaction
        ↓
Durable Commit
        ↓
Ordered Projection
        ↓
Order / Position / Allocation / Account
Strategy Ledger / Fee / Settlement
```

本任务完成后：

```text
SIM
Enum:        Yes
Config:      Yes
Factory:     Yes
Operational: Yes

Gap Recovery: No
Reconnect:    No
Checkpoint:   No
Restart:      No
```

---

# 2. 第一性原理

不要从“需要新增什么类”开始。

首先冻结产品定义：

```text
SIM
=
Realtime Market Data
+
Live Clock
+
Event-driven Trading Kernel
+
Simulated External Broker
+
Streaming Lifecycle
```

对比：

```text
BACKTEST
=
Historical Market Data
+
Backtest Clock
+
Trading Kernel
+
Virtual Broker
+
Finite Lifecycle

SIM
=
Realtime Market Data
+
Live Clock
+
Trading Kernel
+
Virtual Broker
+
Streaming Lifecycle

LIVE
=
Realtime Market Data
+
Live Clock
+
Trading Kernel
+
Real Broker
+
Streaming Lifecycle
```

因此：

```text
SIM != PAPER
SIM != SHADOW
SIM != BACKTEST
SIM != LIVE
```

---

# 3. P6.3 的核心架构原则

永久保持：

```text
Runtime Product Identity
!=
Trading Economic Semantics
```

Runtime Product 可以决定：

```text
Clock selection
DataSource selection
Broker selection
Driver selection
Lifecycle
Operational identity
Composition constraints
Plugin ownership
Persistence identity
```

Runtime Product 不得决定：

```text
Strategy semantics
Risk semantics
Market-rule semantics
Order semantics
Position semantics
Allocation semantics
Fee semantics
Settlement semantics
Account semantics
Transaction semantics
Projection semantics
```

交易函数仍然应当是：

```text
TradingState(t+1)
=
F(
    TradingState(t),
    MarketFacts,
    BrokerFacts,
    MarketAuthority,
    TradingConfig
)
```

不得出现：

```text
F(..., RuntimeMode.SIM)
```

---

# 4. 最重要的不变量

P6.3 实现完成后必须继续满足：

```text
RuntimeMode.SIM
∉
Trading Kernel economic branches
```

禁止：

```text
context.is_sim
context.runtime_type
context.mode

if runtime_mode == SIM:
    ...

if is_sim:
    ...
```

进入：

```text
Strategy Context
Trading Kernel
Risk
Order
Position
Execution semantics
Fee
Settlement
Account
Strategy Ledger
```

---

# 5. 任务开始前必须重新审计当前 HEAD

首先读取当前仓库 HEAD。

至少检查：

```text
src/onlyalpha/domain/enums.py

src/onlyalpha/config/document.py

src/onlyalpha/runtime/sim/
src/onlyalpha/runtime/streaming/
src/onlyalpha/runtime/paper/
src/onlyalpha/runtime/backtest/

src/onlyalpha/runtime/runtime.py
src/onlyalpha/runtime/trading_facade.py
src/onlyalpha/runtime/defaults.py
src/onlyalpha/runtime/__init__.py

src/onlyalpha/runtime/factory.py
src/onlyalpha/runtime/assembler.py

src/onlyalpha/plugin/broker.py
src/onlyalpha/plugin/data_source.py
src/onlyalpha/plugin/capabilities.py

src/onlyalpha/broker/execution.py
src/onlyalpha/broker/inbound.py
src/onlyalpha/broker/ports.py

src/onlyalpha/order/service.py

src/onlyalpha/execution/
src/onlyalpha/transaction/

packages/fake/onlyalpha-plugin-broker-virtual/
packages/provider/onlyalpha-plugin-miniqmt/

tests/architecture/
tests/runtime/
tests/integration/
tests/acceptance/

docs/roadmap.md
docs/architecture.md
docs/runtime.md
docs/adr/0068-runtime-product-taxonomy-and-trading-semantic-equivalence.md

scripts/test_suite.py
.github/workflows/quality.yml
```

如果源码和本文描述存在差异：

```text
current HEAD source
>
本提示词中的旧路径或旧类名
```

但本文的 architecture invariants 和 product semantics 仍是约束。

---

# 6. 开始前确认 P6.2 baseline

确认当前 master 是否仍包含：

```text
OnlyRuntimeMode.SIM
```

确认配置接受：

```text
runtime.type = SIM
```

确认当前：

```text
OnlySimRuntimeFactory
```

已经验证：

```text
execution_capability == SIMULATED

no runtime.start_time
no runtime.end_time

checkpoint disabled

exactly one enabled DataSource

DataSource:
    historical_bars=True
    live_bars=True

exactly one Account

exactly one enabled Broker

Broker:
    simulated_execution=True
    submit_order=True
    cancel_order=True
    query_orders=True
    query_trades=True
```

确认当前合法组合仍停在：

```text
SIM_EXECUTION_WIRING_PENDING
```

这些是 P6.3 的输入条件。

---

# 7. P6.3 不是架构重构

不要创建：

```text
SimOrderManager
SimPositionManager
SimRiskManager
SimAccountManager
SimExecutionProcessor
SimTransactionCoordinator
SimFeeEngine
SimSettlementManager
```

也不要创建：

```text
SimTradingKernel
```

SIM 必须使用已有：

```text
OnlyTradingKernel
OnlyOrderService
OnlyRiskService
OnlyExecutionProcessor
OnlyRuntimeTransactionCoordinator
OnlyRuntimeProjectionApplier
```

---

# 8. P6.3 最终结构

目标：

```text
OnlyEngine
    │
    ▼
OnlySimRuntimeFactory
    │
    ├── LiveClock
    ├── Realtime/Historical DataSource
    ├── MarketDataInboundQueue
    ├── BrokerInboundQueue
    ├── Virtual Broker Component
    ├── Runtime Persistence
    └── Market Product Authorities
             │
             ▼
      OnlySimRuntime
             │
             ▼
   OnlyStreamingRuntime
             │
             ▼
 OnlyTradingRuntimeFacade
             │
             ▼
   OnlyTradingKernel
```

---

# 9. `OnlySimRuntime`

新增：

```text
src/onlyalpha/runtime/sim/runtime.py
```

推荐保持极薄：

```python
from onlyalpha.domain.enums import OnlyRuntimeMode
from onlyalpha.runtime.streaming.runtime import OnlyStreamingRuntime


class OnlySimRuntime(OnlyStreamingRuntime):
    """Realtime Runtime using simulated Broker execution."""

    _supported_modes = frozenset({
        OnlyRuntimeMode.SIM,
    })
```

除非当前源码要求额外 constructor declaration，否则不要增加逻辑。

---

# 10. 继承关系冻结

必须：

```text
OnlySimRuntime
    ↓
OnlyStreamingRuntime
    ↓
OnlyTradingRuntimeFacade
```

禁止：

```text
OnlySimRuntime
    ↓
OnlyPaperRuntime
```

禁止：

```text
OnlySimRuntime
    ↓
OnlyBacktestRuntime
```

禁止 SIM import：

```text
runtime.paper
runtime.backtest.runtime
runtime.shadow
OnlyShadowExecutionService
```

---

# 11. `OnlyStreamingRuntime` 的职责

当前 Streaming Runtime 应继续只负责：

```text
long-lived Runtime lifecycle
historical bootstrap
historical-to-live handoff
watermark
catch-up
live market processing
observation
stop cutoff
```

P6.3 允许它增加：

```text
Broker composition pass-through
```

但不允许它增加：

```text
Broker economic logic
```

---

# 12. 扩展 Streaming Runtime composition ports

当前 constructor 如果只有：

```python
execution_service: OnlyExecutionService
```

以及 MarketData queue：

扩展为能够传递标准 Broker dependencies。

推荐：

```python
def __init__(
    self,
    config,
    calendar,
    *,
    clock,
    event_bus,
    data_source,
    inbound_queue,
    persistence_store,
    subscription,
    data_version,
    execution_service: OnlyExecutionService | None = None,
    broker_gateway: OnlyBrokerGateway | None = None,
    broker_inbound_queue: OnlyBrokerInboundQueue | None = None,
    deterministic_broker_driver: OnlyDeterministicBrokerDriver | None = None,
    broker_resource: OnlyPluginResource | None = None,
    ...
) -> None:
```

具体参数顺序遵循当前项目 style。

---

# 13. Streaming Runtime 向 TradingFacade 透传

应类似：

```python
super().__init__(
    config,
    calendar,
    clock.now_utc(),
    owned_clock=clock,
    owned_event_bus=event_bus,
    account_created_at=...,

    broker_gateway=broker_gateway,
    execution_service=execution_service,
    deterministic_broker_driver=deterministic_broker_driver,
    broker_inbound_queue=broker_inbound_queue,

    market_data_inbound_queue=inbound_queue,

    runtime_persistence_store=persistence_store,

    plugin_resources=(
        ...
    ),
)
```

这是 P6.3 最关键的 wiring。

---

# 14. 不新增 `OnlySimExecutionService`

当前 TradingFacade 已经具备：

```text
broker_gateway
→ OnlyBrokerExecutionService
```

如果：

```text
execution_service is None
broker_gateway is not None
```

应该继续由共享 TradingFacade 创建：

```text
OnlyBrokerExecutionService
```

因此禁止：

```text
OnlySimExecutionService
VirtualExecutionService
SimBrokerExecutionAdapter
```

---

# 15. PAPER 保持原有组合

PAPER：

```text
execution_service
=
OnlyShadowExecutionService

broker_gateway
=
None

broker_inbound_queue
=
None/default unused

deterministic_broker_driver
=
None
```

确保现有 PAPER 测试继续通过。

P6.3 不改变 PAPER product semantics。

---

# 16. SIM 组合

SIM：

```text
execution_service
=
None

broker_gateway
=
broker_component.gateway

broker_inbound_queue
=
broker_queue

deterministic_broker_driver
=
broker_component.deterministic_driver

broker_resource
=
broker_component.resource
```

这样 Shared TradingFacade 自动完成：

```text
Order
→ OnlyBrokerExecutionService
→ Broker Gateway
```

---

# 17. StreamingMarketDataDriver 必须保持单一职责

重新检查：

```text
src/onlyalpha/runtime/streaming/driver.py
```

当前如果存在：

```python
execution: OnlyExecutionService
```

但只做：

```python
self.execution = execution
```

而 Worker 并未使用：

建议在 P6.3 删除这个 dependency。

目标：

```text
OnlyStreamingMarketDataDriver
=
MarketData external-world driver
```

不是：

```text
MarketData + Broker + Execution driver
```

---

# 18. 不创建 Broker thread

禁止：

```text
BrokerWorker
SimBrokerWorker
ExecutionThread
VirtualBrokerLoop
```

不要因为 SIM 是 realtime 就引入新的异步 execution worker。

当前 Virtual Broker 是 deterministic driver：

```text
on_bar()
run_due()
```

Broker Facts 进入已有 queue。

继续使用这个设计。

---

# 19. 为什么不创建 Broker thread

P6.3 要保持确定因果顺序：

```text
Market Fact
→ Broker progression
→ Broker Facts
→ Transaction
→ Strategy dispatch
```

以及：

```text
Strategy Order
→ Broker acceptance
→ Accepted Fact
```

如果新增异步 Broker thread，会引入：

```text
race
nondeterministic Accepted timing
nondeterministic Trade ordering
shutdown races
checkpoint complexity
```

这些都不属于 P6.3。

---

# 20. P6.3 必须冻结的因果顺序

这是最重要的业务 contract。

假设：

```text
Bar N
```

产生策略订单。

必须：

```text
Bar N finalized
    ↓
MarketDataProcessor
    ↓
before_market_dispatch
    ↓
VirtualBroker.on_bar(N)
    ↓
drain previous BrokerFacts
    ↓
Strategy receives Bar N
    ↓
Strategy creates Order
    ↓
Risk
    ↓
Reservation
    ↓
Local Order CREATED
    ↓
Broker submit
    ↓
Local Order SUBMITTED
    ↓
after_market_dispatch
    ↓
VirtualBroker.run_due()
    ↓
Accepted / Rejected Broker Fact
    ↓
BrokerInboundQueue
    ↓
ExecutionProcessor
    ↓
Durable Transaction
```

---

# 21. 同一 Bar 不允许成交新订单

订单在 Bar N 上产生后：

```text
Order(N)
→ Accepted(N)
```

但不得：

```text
Trade(N)
```

必须：

```text
earliest Trade
=
N+1
```

---

# 22. 下一 Bar 成交流程

```text
Bar N+1 finalized
    ↓
before_market_dispatch
    ↓
VirtualBroker.on_bar(N+1)
    ↓
NEXT_BAR Matching
    ↓
Trade Fact
    ↓
BrokerInboundQueue
    ↓
ExecutionProcessor
    ↓
Trade Transaction
    ↓
Projection
    ↓
Strategy sees Bar N+1
```

这意味着：

```text
Broker state resulting from previously accepted Orders
```

必须在：

```text
Strategy processes current Bar
```

之前完成 projection。

---

# 23. 冻结 anti-lookahead invariant

必须测试：

```text
Observation(N)
→ Decision(N)
→ Order(N)
→ Accepted(N)
→ Trade(N+1 or later)
```

禁止：

```text
Observation(N)
→ Decision(N)
→ Trade using N
```

这是 Trading Semantic Equivalence 的关键基础。

---

# 24. 不修改 Virtual Broker matching semantics

当前 Virtual Broker 的 NEXT_BAR、Fill Plan、Slippage、Latency 等已有实现。

P6.3 理想目标：

```text
packages/fake/onlyalpha-plugin-broker-virtual/
production diff = 0
```

除非当前真实代码存在阻止标准 Runtime composition 的 bug。

不要为了 SIM 增加：

```text
SimMatchingEngine
RealtimeVirtualBrokerGateway
SimVirtualBroker
```

---

# 25. Virtual Broker 继续依赖通用 Clock

必须使用当前：

```text
OnlyClock
```

SPI。

SIM：

```text
VirtualBroker
+
OnlyLiveClock
```

BACKTEST：

```text
VirtualBroker
+
OnlyBacktestClock
```

不要在 Broker 内判断 Runtime product。

---

# 26. SimFactory 从 validator 变成真正 composition root

当前：

```text
src/onlyalpha/runtime/sim/factory.py
```

P6.2 只负责：

```text
validate composition
→ SIM_EXECUTION_WIRING_PENDING
```

P6.3 要保留所有 validation，同时真正实现：

```text
create()
```

---

# 27. P6.2 validation 一条都不要删

继续要求：

```text
runtime.type == SIM

execution_capability == SIMULATED

start_time is None
end_time is None

checkpoint disabled

exactly one enabled DataSource

historical_bars=True
live_bars=True

exactly one Account

exactly one enabled Broker

simulated_execution=True

submit_order=True
cancel_order=True
query_orders=True
query_trades=True
```

---

# 28. `validate()` 行为改变

P6.2：

```text
valid SIM
→ invalid
→ SIM_EXECUTION_WIRING_PENDING
```

P6.3：

```text
valid SIM
→ success
```

最终：

```python
def validate(
    self,
    request: OnlyRuntimeBuildRequest,
) -> OnlyRuntimeBuildResult:
    try:
        self._validate(request)
        # validate plugin requests if current factory style requires
    except Exception as exc:
        return self._failure(exc)

    return OnlyRuntimeBuildResult()
```

不得再让合法 SIM 返回：

```text
SIM_EXECUTION_WIRING_PENDING
```

---

# 29. `SIM_EXECUTION_WIRING_PENDING`

P6.3 完成后：

```text
legal SIM path
```

中删除此错误。

可以删除完全不再使用的错误代码/测试。

但不要删除：

```text
SIM_CHECKPOINT_NOT_SUPPORTED
```

因为 checkpoint 仍然不属于 P6.3。

---

# 30. SimFactory 推荐 composition 顺序

保持确定顺序：

```text
1. validate request

2. resolve common config

3. create LiveClock

4. create EventBus

5. create MarketDataInboundQueue

6. create BrokerInboundQueue

7. create Clusters

8. derive subscription BarTypes

9. build DataSource create request

10. validate DataSource plugin

11. create DataSource

12. build Market Rule Engine

13. resolve Market Fee Pack

14. resolve Broker Fee Contract

15. resolve Fee Reconciliation Policy

16. build OnlyRuntimeAssemblyConfig(mode=SIM)

17. create Runtime Persistence Store

18. build Broker create request

19. validate Broker plugin

20. create Broker component

21. require deterministic driver

22. build MarketData subscription

23. construct OnlySimRuntime

24. register instruments

25. add clusters

26. transfer ownership

27. return Runtime
```

---

# 31. LiveClock

必须：

```python
clock = OnlyLiveClock()
```

禁止生产代码中使用：

```text
OnlyBacktestClock
```

测试可以 monkeypatch `OnlyLiveClock` 为 controllable clock。

这只是测试控制手段，不改变产品语义。

---

# 32. EventBus

创建正式 Runtime-scoped EventBus：

```python
OnlyEventBus(
    runtime_config.event_capacity,
    scope=OnlyEventScope(
        config.engine_id,
        config.runtime_id,
    ),
    ...
)
```

遵循当前 Paper/Backtest style。

---

# 33. MarketDataInboundQueue

使用：

```python
OnlyMarketDataInboundQueue(
    streaming.inbound_queue_capacity
)
```

不要新增：

```text
sim_market_queue_capacity
```

---

# 34. BrokerInboundQueue

使用：

```python
OnlyBoundedBrokerInboundQueue(
    runtime_config.event_capacity
)
```

或者当前项目已经统一的 canonical capacity。

不要新增 SIM-specific queue config。

---

# 35. Cluster composition

继续：

```python
clusters = tuple(
    components.clusters.create(item, config)
    for item in config.clusters
    if item.enabled
)
```

要求至少一个 Cluster。

不要创建：

```text
SimCluster
```

---

# 36. Bar subscription

复用 Streaming Runtime 当前逻辑。

计算：

```text
all_bar_types
```

然后：

```text
base_bar_types
=
EXTERNAL aggregation source
```

内部：

```text
INTERNAL aggregation
```

继续由共享 MarketData pipeline 完成。

---

# 37. DataSource create request

构造标准：

```python
OnlyDataSourceCreateRequest(
    ...,
    runtime_type="SIM",
    requested_capabilities=OnlyDataSourceCapabilities(
        historical_bars=True,
        live_bars=True,
    ),
    clock=clock,
    event_bus=event_bus,
    ...
    market_data_sink=market_inbound.put,
)
```

不要硬编码 MiniQMT。

---

# 38. MiniQMT 理想 diff = 0

当前 MiniQMT 已通过 capability SPI 支持：

```text
Historical Bars
Live Bars
```

P6.3 不应该修改 provider 来理解 SIM product。

目标：

```text
packages/provider/onlyalpha-plugin-miniqmt/
production diff = 0
```

---

# 39. Market Rule Engine

使用同一个：

```text
OnlyMarketRuleEngine
```

不要：

```text
OnlySimMarketRuleEngine
```

按当前 Paper/Backtest composition 方式创建。

如果需要 current trading day validation：

继续使用当前 MarketSession/Calendar 逻辑。

---

# 40. Fee authorities

正式复用：

```text
market_fee_pack

broker_fee_contract

broker_fee_authority_id

fee_basis_providers

fee_reconciliation_policy
```

`broker_fee_authority_id` 应来源于：

```text
selected simulated Broker plugin
```

不是：

```text
"SIM"
```

---

# 41. RuntimeAssemblyConfig

构造正式：

```python
OnlyRuntimeAssemblyConfig(
    config.engine_id,
    config.runtime_id,
    OnlyRuntimeMode.SIM,

    event_capacity=...,

    default_account_id=account.account_id,

    strategy_base_currency=config.runtime.base_currency,

    strategy_capitals=...,

    broker_gateway_id=broker_common.gateway_id,

    account_initial_cash=account.initial_cash,

    market_rule_engine=market_rule_engine,

    market_fee_pack=market_fee_pack,

    broker_fee_contract=broker_fee_contract,

    broker_fee_authority_id=broker_common.plugin_id,

    fee_basis_providers=components.fee_basis_providers,

    fee_reconciliation_policy=reconciliation_policy,
)
```

`OnlyRuntimeMode.SIM` 只能作为 operational composition identity。

---

# 42. Runtime persistence 必须存在

不要因为：

```text
checkpoint disabled
```

就跳过 Runtime persistence。

P6.3 的核心交易事实仍必须：

```text
Commit Fact First
→ Project State Second
```

所以：

```text
Accepted
Trade
Terminal
```

必须继续通过 durable transaction path。

---

# 43. Checkpoint != Durable Transaction

必须明确区分：

```text
Runtime Persistence
=
durable transaction authority
```

和：

```text
Runtime Checkpoint
=
restart snapshot
```

P6.3：

```text
durable transactions = YES
checkpoint/restart = NO
```

---

# 44. Persistence mode

创建：

```python
OnlyRuntimePersistenceStoreCreateRequest(
    ...,
    OnlyRuntimeMode.SIM,
    ...
)
```

不要伪装成：

```text
PAPER
BACKTEST
```

---

# 45. 不改变 persistence schema

除非当前真实代码要求 SIM operational identity 已触发必要兼容修复，否则：

```text
transaction schema
projection schema
checkpoint schema
```

不要 bump。

P6.3 不是 schema migration milestone。

---

# 46. Broker create request

使用正式 Broker SPI：

```python
OnlyBrokerCreateRequest(
    gateway_id=broker_common.gateway_id,

    plugin_config=broker_factory.parse_config(
        broker_common.extensions
    ),

    runtime_type="SIM",

    requested_capabilities=OnlyBrokerPluginCapabilities(
        submit_order=True,
        cancel_order=True,
        query_orders=True,
        query_trades=True,
        simulated_execution=True,
    ),

    clock=clock,

    event_bus=event_bus,

    broker_inbound_queue=broker_queue,

    runtime_id=config.runtime_id,

    account_id=account.account_id,

    initial_cash=account.initial_cash,

    logger=_LOGGER,
)
```

遵循当前实际 constructor order/style。

---

# 47. 不直接 import VirtualBroker 实现

SimFactory 禁止：

```python
from onlyalpha_plugin_broker_virtual.gateway import ...
```

Factory 必须只依赖：

```text
Broker Plugin SPI
```

即：

```text
components.brokers.resolve(...)
```

---

# 48. Broker plugin validation

必须执行：

```python
broker_factory.validate_request(
    broker_request
)
```

任何 issue：

```text
fail closed
```

不要跳过 plugin-specific config validation。

---

# 49. Broker Component

通过：

```python
broker_component = broker_factory.create(
    broker_request
)
```

只依赖标准：

```text
gateway
resource
deterministic_driver
```

---

# 50. deterministic driver 是 SIM operational requirement

P6.3 真正运行需要：

```text
deterministic_broker_driver
```

如果：

```python
broker_component.deterministic_driver is None
```

必须失败。

推荐稳定错误：

```text
SIM_DETERMINISTIC_BROKER_DRIVER_REQUIRED
```

或者遵循当前项目错误风格。

---

# 51. 不要求 gateway == driver

当前 Virtual Broker 可能：

```text
gateway
resource
driver
```

都是同一个对象。

但 SPI 没要求未来必须如此。

禁止：

```python
assert broker_component.gateway is broker_component.deterministic_driver
```

只使用标准接口。

---

# 52. Plugin resource ownership

SIM Runtime 应拥有：

```text
Broker Resource
DataSource Resource
```

推荐 resource order：

```text
broker_resource
data_source
```

原因：

```text
Broker Ready
before
live trading intake
```

但必须结合当前 Base Runtime resource lifecycle 顺序重新确认。

不要只凭本提示词机械排序。

---

# 53. 不在 OnlySimRuntime 手写 Broker lifecycle

禁止：

```python
def start():
    broker.connect()
    broker.authenticate()
```

Broker Resource 已有统一：

```text
initialize
connect
start
stop
close
```

使用 Base Runtime 生命周期。

---

# 54. Runtime construction

最终应接近：

```python
runtime = OnlySimRuntime(
    runtime_config,
    calendar,

    clock=clock,

    event_bus=event_bus,

    data_source=source,

    inbound_queue=market_inbound,

    broker_gateway=broker_component.gateway,

    broker_inbound_queue=broker_queue,

    deterministic_broker_driver=(
        broker_component.deterministic_driver
    ),

    broker_resource=broker_component.resource,

    persistence_store=persistence,

    subscription=subscription,

    data_version=source_common.data_version,

    bootstrap_bars=streaming.bootstrap_bars,

    historical_compatibility_profile=(
        streaming.historical_compatibility_profile
    ),

    historical_timeout_seconds=(
        streaming.historical_timeout_seconds
    ),

    warmup_alignment_steps=...,

    stale_after_seconds=(
        streaming.stale_after_seconds
    ),

    observation_sinks=...,

    observation_queue_capacity=(
        streaming.observation_queue_capacity
    ),
)
```

实际参数根据当前源码调整。

---

# 55. 不传 ShadowExecutionService

这是硬性 gate：

```text
OnlySimRuntime
```

构造路径中：

```text
OnlyShadowExecutionService
```

出现即失败。

---

# 56. Register instruments / clusters

正常：

```python
for instrument in config.reference_data.instruments:
    runtime.register_instrument(instrument)

for cluster in clusters:
    runtime.add_cluster(
        config.engine_id,
        cluster,
    )
```

不要建立 Sim-specific registration path。

---

# 57. Ownership transfer

Factory create 成功后：

```text
Runtime owns:
    clock
    event_bus
    source
    broker resource
    persistence
```

Factory local references 必须按当前项目惯例清空/转移 ownership，避免 exception handler double-close。

---

# 58. Factory rollback

若任何一步失败：

必须清理已经创建的：

```text
persistence
broker resource
data source
event bus
clock
```

不要泄漏：

```text
MiniQMT callback
worker
Virtual Broker
SQLite handle
EventBus
Clock
```

---

# 59. Broker resource cleanup

不要直接清理：

```text
broker_component.gateway
```

应清理：

```text
broker_component.resource
```

即使当前 Virtual Broker 两者相同。

这是 SPI boundary。

---

# 60. SIM subscription identity

当前 PAPER 使用类似：

```text
paper-{runtime_id}
```

SIM 必须：

```text
sim-{runtime_id}
```

不能复用 PAPER identity。

---

# 61. 修复共享 StreamingRuntime 的 PAPER naming leakage

当前如果：

```python
@property
def inspection_run_id(self) -> str:
    return f"paper-{self.runtime_id}"
```

改为 product-neutral：

```python
@property
def inspection_run_id(self) -> str:
    return f"{self.runtime_type.lower()}-{self.runtime_id}"
```

这是 operational identity，允许读取 Runtime type。

---

# 62. 不要因此修改 Trading Kernel

目标：

```text
src/onlyalpha/runtime/trading/**
production diff = 0
```

如果实现 SIM 必须修改 Trading Kernel：

优先判断 wiring 是否方向错误。

---

# 63. TradingFacade 理想 diff = 0

当前 TradingFacade 已有：

```text
broker_gateway
broker_inbound_queue
deterministic_broker_driver
OnlyBrokerExecutionService
ExecutionProcessor
TransactionCoordinator
Projection
before_market_dispatch
after_market_dispatch
```

因此理想：

```text
src/onlyalpha/runtime/trading_facade.py
production diff = 0
```

P6.3 只传入已有 dependencies。

---

# 64. Broker fact path 不创建新实现

必须继续：

```text
BrokerInboundQueue
    ↓
ExecutionProcessor
    ↓
TransactionPlanner
    ↓
RuntimeTransactionCoordinator
    ↓
Projection
```

禁止：

```text
SimExecutionProcessor
SimBrokerFactProcessor
```

---

# 65. OrderService 不修改因果顺序

当前正确：

```text
local Order created
→ reservations
→ Broker submit
→ local Order submitted
```

不要把：

```text
Broker Accepted processing
```

同步塞进：

```text
OnlyBrokerExecutionService.submit_order()
```

否则可能出现：

```text
Accepted
before
Local SUBMITTED
```

错误因果关系。

---

# 66. Broker Accepted 的正确处理点

对 MarketData-originated Strategy order：

```text
Strategy dispatch
    ↓
Broker submit
    ↓
Local SUBMITTED
    ↓
after_market_dispatch
    ↓
driver.run_due()
    ↓
Accepted Fact
```

保持。

---

# 67. Historical bootstrap

SIM 直接复用：

```text
SUBSCRIBING
→ BOOTSTRAP
→ CATCH_UP
→ LIVE
```

不要新增：

```text
SimBootstrap
```

---

# 68. Bootstrap/Catch-up 禁止交易

继续冻结：

```text
BOOTSTRAP
→ strategy intent suppressed

CATCH_UP
→ strategy intent suppressed
```

只有：

```text
LIVE
```

可以提交 SIM Broker order。

---

# 69. 不把 bootstrap 变成历史模拟交易

禁止：

```text
Historical warmup
→ Strategy order
→ Virtual Broker trade
```

SIM 不是：

```text
Backtest followed by realtime
```

SIM 的 historical bootstrap 只是：

```text
state/input warmup
```

不是交易时间。

---

# 70. Broker driver 是否接收 bootstrap bars

不要为了这一点新增复杂 phase policy。

当前如果 TradingFacade 的 deterministic Broker hook 会看到 bootstrap Bar：

只要：

```text
no live Orders
```

则不得产生 trade。

可以允许 Broker 更新：

```text
latest mark
bar sequence
```

不要增加：

```text
OnlySimBrokerPhasePolicy
OnlyBrokerAdmissionManager
```

除非测试证明存在真实 semantic bug。

---

# 71. Stop semantics

P6.1 已冻结：

```text
STOP
=
future processing permission cutoff
```

保持。

P6.3 新增 Virtual Broker 后：

禁止 Stop：

```text
run_due()
flush Broker queue
generate final Trade
cancel all Orders
expire Orders
flush pending live bar
```

---

# 72. Stop 不是交易命令

尤其禁止：

```text
engine.stop()
→ auto cancel Virtual Broker orders
```

因为：

```text
Lifecycle STOP
!=
Trading CANCEL command
```

pending Broker state 的 restart/recovery 属于后续阶段。

---

# 73. Stop 后不得产生新经济事实

新增 integration test：

记录：

```text
committed transaction count
fill count
position state
order state
broker inbound processing count
```

然后：

```text
engine.stop()
```

断言 Stop 后：

```text
no new Trade
no new Terminal
no new transaction
no new projection
```

由 shutdown 本身产生。

---

# 74. `OnlyEngine.run()` 不支持 SIM

继续：

```text
OnlyEngine.run()
=
finite BACKTEST only
```

不要改变。

SIM 正式 lifecycle：

```python
engine.initialize()
engine.start()

try:
    engine.wait()
finally:
    engine.stop()
```

---

# 75. `Engine.validate()` 变化

当前 P6.2 test：

```text
Engine.validate(SIM)
→ invalid
→ SIM_EXECUTION_WIRING_PENDING
```

P6.3 完成后改为：

```text
Engine.validate(valid SIM)
→ valid
```

这是正式产品状态改变。

---

# 76. `Engine.initialize()` / `start()`

新增测试：

```text
Engine.initialize(valid SIM)
→ succeeds

Engine.start(valid SIM)
→ succeeds

Runtime.state
→ RUNNING

StreamingPhase
→ LIVE
```

---

# 77. Public exports

更新：

```text
src/onlyalpha/runtime/sim/__init__.py
```

包含：

```python
from .factory import OnlySimRuntimeFactory
from .runtime import OnlySimRuntime

__all__ = [
    "OnlySimRuntime",
    "OnlySimRuntimeFactory",
]
```

按当前项目 public lazy-export style 更新：

```text
src/onlyalpha/runtime/__init__.py
```

不要破坏现有 public API patterns。

---

# 78. P6.3 最重要的 integration vertical slice

新增：

```text
tests/integration/test_engine_sim_virtual_broker_execution.py
```

目标不是覆盖所有 Virtual Broker feature。

只证明一条最小但完整的产品纵切面。

---

# 79. Integration fixture

优先复用/轻量抽取现有 PAPER fake MiniQMT realtime harness。

需要：

```text
fake realtime DataSource transport
controllable test Clock
historical warmup helper
acceptance Strategy
Virtual Broker plugin
one Account
one Cluster
```

不要依赖真实 MiniQMT 环境完成核心 CI。

---

# 80. 测试初始化

Given：

```text
runtime.type = SIM

execution_capability = SIMULATED

MiniQMT-like fake realtime DataSource

Virtual Broker

one Account

one acceptance Strategy
```

首先：

```python
validation = engine.validate()

assert validation.valid
```

不得：

```text
SIM_EXECUTION_WIRING_PENDING
```

---

# 81. 初始化后的 Runtime

断言：

```text
runtime.runtime_type == SIM

runtime is OnlySimRuntime

runtime.broker_gateway is not None

runtime.execution_service
is broker-backed execution
not Shadow execution
```

不要依赖 private internals过多。

优先通过正式 Runtime management/read-only ports 验证。

---

# 82. Bootstrap 测试

```text
engine.start()
```

后：

```text
StreamingPhase == LIVE

historical watermark exists

historical warmup processed
```

同时：

```text
no simulated historical Trade
```

---

# 83. LIVE Bar N

推送第一根使 acceptance Strategy 创建订单的 finalized Bar。

等待 processing 完成。

断言：

```text
live Strategy intent exists

Order exists

Order reached SUBMITTED/ACCEPTED authoritative state

external/venue order identity exists

reservation exists or has correct post-accept state

Fill count == 0

Position count == 0
```

---

# 84. Same-Bar-No-Fill gate

必须单独冻结：

```text
Order created from Bar N
cannot be filled by Bar N
```

不要只依赖最终结果隐含证明。

测试应显式断言在 Bar N 处理结束时：

```text
fill_count == 0
```

---

# 85. Accepted durable fact

检查：

```text
Accepted Broker Fact
```

已经：

```text
BrokerInboundQueue
→ ExecutionProcessor
→ Durable Transaction
```

优先通过正式 transaction query 或 Runtime diagnostics 验证。

不要只检查 Order 最终 status。

---

# 86. LIVE Bar N+1

再推一根 eligible finalized Bar。

断言：

```text
Virtual Broker produces Trade

fill_count > 0
```

并验证：

```text
Position projection
Allocation projection
Account projection
Strategy Ledger projection
Fee projection
```

已经发生。

---

# 87. Accepted before Trade

必须验证 causal ordering：

```text
Accepted transaction sequence
<
Trade transaction sequence
```

或者通过当前正式 causal sequence/transaction ordering mechanism 验证。

不要只检查：

```text
both exist
```

---

# 88. Reservation lifecycle

至少验证：

```text
Reservation created before Broker completion
```

以及成交后：

```text
consume/release
```

与最终 order status 一致。

不能留下错误 open reservation。

---

# 89. External Broker identity

PAPER 当前 Shadow path：

```text
external_order_id_count == 0
```

SIM 必须：

```text
external Broker / venue Order identity exists
```

这可以成为：

```text
PAPER → SIM
```

迁移的一个清晰证据。

---

# 90. Shadow suppression

SIM integration test 必须证明：

```text
shadow_suppressed_count == 0
```

或者当前正式 equivalent diagnostic。

SIM 不允许走：

```text
SUPPRESSED
```

execution outcome。

---

# 91. Position projection

最小 BUY/OPEN 测试完成后：

```text
position_count > 0
```

并验证 quantity 与 Fill 一致。

不要只检查 count。

---

# 92. Allocation

验证 Cluster attribution 已更新。

不要让：

```text
Runtime Position
```

存在但：

```text
Strategy/Cluster Allocation
```

缺失。

---

# 93. Account

验证：

```text
cash / reserved cash / available cash
```

至少有一个 authoritative expected change。

不要硬编码过多 implementation detail；以正式 Account query为准。

---

# 94. Strategy Ledger

验证策略 Ledger 的经济结果发生正确变化。

至少证明：

```text
execution projection
```

真正进入 Strategy attribution，而不是只有 Runtime Position。

---

# 95. Fee

确认 Trade transaction 使用现有 Fee authority。

禁止：

```text
Virtual Broker simulated fee
```

成为第二个权威 Fee source。

现有设计中 Virtual Broker 外部 fee projection 不应覆盖 Runtime canonical fee。

保持。

---

# 96. SQLite durable smoke

建议增加至少一个：

```text
SIM + SQLite persistence
```

smoke integration。

范围只需要：

```text
Accepted committed
Trade committed
Projection Ready
```

不做 restart。

---

# 97. 不测试 P6.5

SQLite test 不能扩展成：

```text
kill process
restart
restore Virtual Broker
resume live
```

这些属于 P6.5。

---

# 98. Broker rejection path

如果工作量可控，建议增加一个轻量测试：

```text
Virtual Broker reject-before-accepted
```

验证：

```text
Broker Rejected
→ ExecutionProcessor
→ Terminal Transaction
→ Reservation Release
```

但这不是阻塞 P6.3 最小 DoD 的必要条件。

最优先完成：

```text
Accepted + Trade
```

纵切面。

---

# 99. Partial fill 暂不做完整矩阵

Virtual Broker 已有 partial fill。

P6.3 不需要建立：

```text
WHOLE
MAX_PER_BAR
SCHEDULE
one-per-bar
all combinations
```

完整 certification。

已有 Virtual Broker 单测继续负责 Broker component correctness。

P6.3 负责 Runtime composition correctness。

---

# 100. Gap / reconnect 明确 out of scope

不要实现：

```text
HEALTHY
→ DEGRADED
→ RECOVERING
→ replay missing range
→ catch-up
→ HEALTHY
```

属于 P6.4。

当前遇到 gap：

继续使用已有：

```text
GAP_DETECTED
```

语义即可。

---

# 101. Streaming checkpoint/restart out of scope

继续让：

```text
SIM + checkpoint.enabled=true
```

失败。

保持 P6.2：

```text
SIM_CHECKPOINT_NOT_SUPPORTED
```

直到 P6.5。

---

# 102. PAPER 不删除

P6.3 不做：

```text
delete runtime/paper
delete PAPER enum
delete PAPER config
delete paper tests
```

PAPER 仍是 migration comparison baseline。

---

# 103. SHADOW 不删除

同样：

```text
OnlyShadowExecutionService
```

仍然被 legacy PAPER 使用。

本阶段只保证：

```text
SIM never imports/uses Shadow
```

---

# 104. 不修改 Real Broker

P6.3 是 Virtual Broker SIM。

不要实现：

```text
MiniQMT real order submit
broker reconciliation
live outbound reliability
```

这些属于后续 LIVE 路线。

---

# 105. Architecture tests

扩展：

```text
tests/architecture/test_sim_runtime_product_boundary.py
```

至少冻结：

```text
OnlySimRuntime exists

OnlySimRuntime subclasses OnlyStreamingRuntime

runtime/sim does not import runtime/paper

runtime/sim does not import runtime/backtest

runtime/sim does not import runtime/shadow

runtime/sim does not reference OnlyShadowExecutionService
```

---

# 106. Economic authority gate

扫描：

```text
src/onlyalpha/runtime/sim/
```

禁止直接构造/import具体交易 authority：

```text
OnlyOrderManager
OnlyPositionManager
OnlyPositionAllocationManager
OnlyAccountManager
OnlyRiskService
OnlyExecutionProcessor
OnlyRuntimeTransactionCoordinator
OnlyFeeEngine
OnlySettlementAuthority
OnlyStrategyLedgerManager
```

SimFactory 可以解析配置和 external plugin composition。

不能创建第二套经济权威。

---

# 107. RuntimeMode gate

继续执行 P6.1 AST gates。

新增 SIM 后不得出现：

```text
RuntimeMode.SIM
```

进入：

```text
strategy/context.py
runtime/trading_facade.py economic branches
runtime/trading/**
fee/
position/
risk/
order/
execution economics/
settlement/
account/
strategy_ledger/
```

---

# 108. Streaming Runtime gate

允许：

```text
OnlyRuntimeMode.SIM
```

存在于：

```text
OnlySimRuntime._supported_modes
```

这是 operational product compatibility guard。

这是合法边界。

---

# 109. `inspection_run_id`

添加测试：

```text
PAPER → paper-...
SIM   → sim-...
```

不要让 shared Streaming Runtime 暴露错误 PAPER identity。

---

# 110. Stop architecture test / regression

继续冻结 P6.1：

```text
stop after cutoff
does not process pending market work
```

并针对 SIM 增加：

```text
stop does not produce Broker economic work
```

---

# 111. 不创建新 policy abstraction

禁止本任务增加：

```text
SimRuntimeSemanticPolicy
SimExecutionPolicy
RuntimeExecutionModeResolver
ModeNeutralizationService
SimBrokerCoordinator
SimTradingOrchestrator
```

当前现有 ports 已足够。

---

# 112. 不创建 Factory hierarchy

不要：

```text
OnlyStreamingTradingRuntimeFactoryBase

OnlyVirtualBrokerRuntimeFactoryBase

OnlySimulatedRuntimeFactoryBase
```

当前只有第二个正式 composition use case。

先接受少量重复。

---

# 113. 不复用 private PaperFactory helpers

禁止：

```python
OnlyPaperRuntimeFactory._market_rules(...)
OnlyPaperRuntimeFactory._observation_sinks(...)
```

这样会形成：

```text
SIM
→ PAPER implementation dependency
```

少量重复更安全。

---

# 114. 不复用 BacktestRuntime implementation

可以借鉴：

```text
BacktestFactory Broker SPI composition
```

但不要：

```text
OnlySimRuntime
→ OnlyBacktestRuntime
```

也不要让 SimFactory 调用：

```text
BacktestFactory._plugin_plan()
```

这种 private implementation helper。

---

# 115. 如需抽 helper，只允许非常小的纯函数

只有在当前代码中出现明显、稳定、完全 product-neutral 重复时，可以考虑类似：

```text
create market rule engine
calculate runtime config fingerprint
raise first plugin issue
```

这种纯 helper。

但默认：

```text
do not abstract during P6.3
```

---

# 116. 代码风格

目标：

```text
explicit
small
deterministic
fail-closed
```

优先：

```text
plain dataclass
plain Factory
existing Port
existing Registry
existing capability object
```

避免：

```text
reflection
dynamic dispatch magic
service locator expansion
new DI framework
new manager layer
```

---

# 117. Config example

建议新增：

```text
examples/configs/miniqmt_sim_acceptance.yaml
```

基于现有 Paper acceptance config，但：

```yaml
runtime:
  type: SIM
  extensions:
    execution_capability: SIMULATED
```

并正式启用：

```text
Virtual Broker
```

不要通过 alias 兼容 PAPER。

---

# 118. Example config 必须符合真实 product contract

至少：

```text
one DataSource
one Account
one Virtual Broker
one enabled Cluster
checkpoint disabled
no start/end
```

---

# 119. P6.2 test 更新

当前：

```text
test_engine_validation_reports_sim_execution_wiring_pending
```

需要改写/删除。

替换为：

```text
test_engine_validation_accepts_operational_sim
```

或者项目现有命名风格。

---

# 120. Engine lifecycle test

必须继续有：

```text
SIM cannot use engine.run()
```

而新增：

```text
initialize/start/wait/stop
```

正式生命周期测试。

---

# 121. `wait()` 测试

Streaming Runtime `wait(timeout)` 是 long-lived wait。

测试可以：

```python
engine.start()
engine.wait(timeout=small_value)
```

确认 Runtime 仍：

```text
RUNNING
```

然后显式 stop。

不要测试无限 wait。

---

# 122. 不改变 `OnlyEngine.run()`

这是强 gate。

如果为了 SIM 需要改 Engine.run：

任务方向错误。

---

# 123. 文档更新

更新：

```text
docs/roadmap.md
docs/architecture.md
docs/runtime.md
docs/adr/0068-runtime-product-taxonomy-and-trading-semantic-equivalence.md
```

如果 ADR policy 要求 ADR 不可重写历史：

只更新 implementation status 或新增 ADR note。

---

# 124. P6.2 文档状态先修正

如果 roadmap 仍写：

```text
P6.2 完成，待最终同 SHA CI
```

而当前最新事实已经 certified：

改成：

```text
P6.2 DONE / CERTIFIED
```

使用当前真实同 SHA CI 状态。

---

# 125. P6.3 文档完成状态

实现成功后写：

```text
P6.3 — SIM Realtime Virtual Broker Execution Wiring
DONE
```

并明确：

```text
SIM is now operational for realtime simulated execution.
```

但同时明确：

```text
gap recovery not implemented
reconnect not implemented
checkpoint/restart not implemented
```

---

# 126. 文档不要夸大

禁止写：

```text
SIM production ready
SIM fully fault tolerant
SIM restart safe
SIM realtime recovery complete
```

P6.3 只证明：

```text
normal-path realtime simulated trading closure
```

---

# 127. P6.3 后 Runtime taxonomy

文档更新：

```text
BACKTEST
Historical + Event-driven + Virtual Broker
Operational: Yes

SIM
Realtime + Event-driven + Virtual Broker
Operational: Yes
Gap/Restart: Not yet

LIVE
Realtime + Event-driven + Real Broker
Operational: No

RESEARCH
Historical + Vectorized/Batch
Operational: No

PAPER
Legacy migration source

SHADOW
Legacy migration debt
```

---

# 128. P6.3 后 roadmap 接续

下一阶段必须仍是：

```text
P6.4 — Gap + Reconnect Recovery
```

不要在 P6.3 偷做。

---

# 129. 测试执行前先读取正式测试定义

使用：

```text
scripts/test_suite.py
docs/testing.md
.github/workflows/quality.yml
```

作为真正 source of truth。

不要假设 lane 名不会变化。

---

# 130. 静态检查

至少：

```bash
uv run ruff check src tests examples packages scripts

uv run ruff format --check src tests examples packages scripts

uv run mypy src/onlyalpha
```

并执行 workspace 各 plugin/package 当前正式 mypy lanes。

---

# 131. 测试 lanes

至少当前正式：

```bash
uv run python scripts/test_suite.py fast

uv run python scripts/test_suite.py integration

uv run python scripts/test_suite.py recovery

uv run python scripts/test_suite.py ashare

uv run python scripts/test_suite.py miniqmt-contract

uv run python scripts/test_suite.py core-full
```

以最新仓库定义为准。

---

# 132. Build

执行：

```bash
uv build --all-packages
```

---

# 133. Backtest regression

P6.3 必须保证 BACKTEST：

```text
Orders
Trades
Position
Allocation
Account
Ledger
Fee
Settlement
Transaction
Recovery
```

结果不发生非预期变化。

如果 golden/fingerprint 改变：

不要直接更新 fixture。

先查原因。

---

# 134. PAPER regression

现有 PAPER fake-live integration 应继续：

```text
Shadow suppression
no Fill
no Position
```

保持。

P6.3 不能把 PAPER 意外接到 Virtual Broker。

---

# 135. MiniQMT contract regression

当前：

```text
miniqmt-contract
```

必须继续绿色。

P6.3 理想情况下不修改 MiniQMT production code。

---

# 136. Recovery regression

虽然 SIM restart 尚未实现：

现有 Backtest recovery suite 必须继续完整绿色。

不要因为 Streaming/Broker pass-through 改坏 recovery architecture。

---

# 137. Remote CI

如果修改推送远端：

必须检查最终 HEAD SHA 的：

```text
static
build
core-full
recovery
ashare
miniqmt-contract
quality-gate
```

全部属于同一个最终 SHA。

不要用旧 P6.2 CI 证明 P6.3。

---

# 138. Nightly

如果 `Nightly Exhaustive` 会在合理流程内针对当前最终 SHA 运行：

记录结果。

如果没有自动运行：

不要声称已经通过 nightly。

---

# 139. 禁止伪完成方案 1

禁止：

```text
SIM
→ OnlyShadowExecutionService
```

---

# 140. 禁止伪完成方案 2

禁止：

```text
SIM
→ PaperRuntime
```

---

# 141. 禁止伪完成方案 3

禁止：

```text
SIM
→ BacktestRuntime
```

---

# 142. 禁止伪完成方案 4

禁止：

```text
OnlySimRuntime exists
```

但 Factory 仍然：

```text
SIM_EXECUTION_WIRING_PENDING
```

P6.3 完成后 SIM 必须真实可运行。

---

# 143. 禁止伪完成方案 5

禁止：

```text
Virtual Broker returns Accepted
```

但没有进入：

```text
ExecutionProcessor
Durable Transaction
Projection
```

Broker side success 不等于 Trading Runtime closure。

---

# 144. 禁止伪完成方案 6

禁止测试只验证：

```text
Order exists
```

P6.3 必须至少证明：

```text
Accepted
+
Trade
+
Transaction
+
Position
```

---

# 145. 禁止伪完成方案 7

禁止：

```text
Trade
```

直接修改：

```text
PositionManager
```

必须继续：

```text
Broker Fact
→ ExecutionProcessor
→ Transaction
→ Projection
```

---

# 146. 禁止伪完成方案 8

禁止：

```text
RuntimeMode.SIM
```

进入经济组件。

---

# 147. 禁止伪完成方案 9

禁止为了 realtime 增加 Broker background worker。

---

# 148. 禁止伪完成方案 10

禁止 Stop：

```text
auto cancel
auto fill
flush Broker facts
```

---

# 149. 推荐实施 Phase A — Re-audit

输出并记录：

```text
current HEAD

P6.2 CI certification

OnlySimRuntime current state

OnlySimRuntimeFactory current state

StreamingRuntime constructor

TradingFacade Broker ports

TradingFacade on_bar/run_due hooks

Virtual Broker component SPI

MiniQMT streaming capability

current tests
```

然后直接继续实现。

不要只生成审计报告停下来。

---

# 150. Phase B — Create OnlySimRuntime

新增极薄 Runtime class。

补 architecture test。

---

# 151. Phase C — Streaming composition ports

只增加：

```text
broker gateway
broker inbound queue
deterministic driver
broker resource
```

pass-through。

不要改经济代码。

---

# 152. Phase D — Driver cleanup

如果 `StreamingMarketDataDriver.execution` 是无用 dependency：

删除它以及调用方传参。

确保现有 PAPER tests 不变。

---

# 153. Phase E — SimFactory composition

将 P6.2 validator 升级为真正 Factory：

```text
validate success
create Runtime
```

---

# 154. Phase F — Broker SPI wiring

创建：

```text
BrokerInboundQueue
BrokerCreateRequest
BrokerComponent
```

传给 Streaming Runtime。

---

# 155. Phase G — Lifecycle

确认：

```text
broker resource
data source resource
```

均由 Runtime lifecycle 正常管理。

测试 start/stop/rollback。

---

# 156. Phase H — Product contract transition

移除：

```text
SIM_EXECUTION_WIRING_PENDING
```

合法路径。

更新 P6.2 integration tests。

---

# 157. Phase I — Vertical slice

完成：

```text
Live Bar N
→ Order
→ Accepted

Live Bar N+1
→ Trade
→ Transaction
→ Position
```

---

# 158. Phase J — Causal ordering

冻结：

```text
Accepted < Trade
```

以及：

```text
no same-bar fill
```

---

# 159. Phase K — Persistence smoke

验证：

```text
SIM transaction durability
```

不做 restart。

---

# 160. Phase L — Stop boundary

验证 stop 后无新增 market/broker economic processing。

---

# 161. Phase M — Architecture gates

重新扫描：

```text
SIM
OnlyRuntimeMode
Shadow
Paper
Backtest
```

依赖边界。

---

# 162. Phase N — Docs

更新 P6.2 certification 与 P6.3 operational state。

---

# 163. Phase O — Full certification

执行所有正式 local gates。

推送后检查 same-SHA remote quality gate。

---

# 164. Definition of Done

必须全部满足：

```text
[ ] current HEAD was re-audited before implementation

[ ] P6.2 baseline CI state was recorded accurately

[ ] OnlySimRuntime exists

[ ] OnlySimRuntime subclasses OnlyStreamingRuntime

[ ] OnlySimRuntime does not inherit PaperRuntime

[ ] OnlySimRuntime does not inherit BacktestRuntime

[ ] runtime/sim does not import Shadow execution

[ ] StreamingRuntime accepts standard Broker composition ports

[ ] StreamingMarketDataDriver does not own unused Execution dependency

[ ] SimFactory preserves every P6.2 fail-closed validation

[ ] valid SIM Factory validation succeeds

[ ] SIM_EXECUTION_WIRING_PENDING is removed from legal SIM path

[ ] SIM_CHECKPOINT_NOT_SUPPORTED remains

[ ] SimFactory creates OnlyLiveClock

[ ] SimFactory creates one MarketData inbound queue

[ ] SimFactory creates one Broker inbound queue

[ ] SimFactory creates DataSource through plugin SPI

[ ] DataSource requires historical_bars

[ ] DataSource requires live_bars

[ ] SimFactory creates Broker through plugin SPI

[ ] Broker requires simulated_execution=True

[ ] Real Broker remains rejected

[ ] Broker requires submit_order

[ ] Broker requires cancel_order

[ ] Broker requires query_orders

[ ] Broker requires query_trades

[ ] operational SIM Broker requires deterministic_driver

[ ] SimFactory does not directly import Virtual Broker implementation

[ ] SimFactory creates Runtime persistence using SIM identity

[ ] durable transaction path remains enabled

[ ] checkpoint remains disabled

[ ] OnlySimRuntime receives Broker gateway

[ ] OnlySimRuntime receives Broker inbound queue

[ ] OnlySimRuntime receives deterministic Broker driver

[ ] Broker resource lifecycle belongs to Runtime

[ ] DataSource lifecycle belongs to Runtime

[ ] Engine.validate(valid SIM) succeeds

[ ] Engine.initialize(valid SIM) succeeds

[ ] Engine.start(valid SIM) succeeds

[ ] SIM enters StreamingPhase.LIVE

[ ] OnlyEngine.run(SIM) remains forbidden

[ ] historical bootstrap does not create simulated trades

[ ] catch-up does not create simulated trades

[ ] LIVE Strategy intent reaches canonical OrderService

[ ] Order reaches Virtual Broker through OnlyBrokerExecutionService

[ ] no Shadow suppression occurs in SIM

[ ] external/venue Broker Order identity exists

[ ] Accepted Broker Fact enters BrokerInboundQueue

[ ] Accepted Broker Fact enters ExecutionProcessor

[ ] Accepted durable transaction commits

[ ] Order created from Bar N does not fill on Bar N

[ ] Order can fill on Bar N+1 or later

[ ] Trade Broker Fact enters BrokerInboundQueue

[ ] Trade enters ExecutionProcessor

[ ] Trade durable transaction commits

[ ] Accepted transaction precedes Trade transaction

[ ] Position projection is correct

[ ] Allocation projection is correct

[ ] Account projection is correct

[ ] Strategy Ledger projection is correct

[ ] Fee projection is correct

[ ] Reservation lifecycle is correct

[ ] stop does not generate new Broker facts

[ ] stop does not generate Trade

[ ] stop does not auto-cancel Orders

[ ] stop does not create new durable trading transaction

[ ] SIM inspection identity uses sim-

[ ] PAPER inspection identity remains paper-

[ ] Trading Kernel production semantics remain unchanged

[ ] TradingFacade economic semantics remain unchanged

[ ] Strategy Context remains RuntimeMode-free

[ ] Virtual Broker production implementation ideally unchanged

[ ] MiniQMT production implementation ideally unchanged

[ ] PAPER Shadow behavior remains unchanged

[ ] BACKTEST economic behavior remains unchanged

[ ] existing Recovery suite remains unchanged

[ ] gap/reconnect is not implemented

[ ] streaming checkpoint/restart is not implemented

[ ] PAPER is not deleted

[ ] SHADOW is not deleted

[ ] no new Factory inheritance hierarchy was introduced

[ ] no new SIM-specific trading authority was introduced

[ ] ruff check green

[ ] ruff format check green

[ ] mypy green

[ ] fast green

[ ] integration green

[ ] core-full green

[ ] recovery green

[ ] ashare green

[ ] miniqmt-contract green

[ ] build --all-packages green

[ ] final remote same-SHA quality-gate green
```

---

# 165. P6.3 完成后的核心因果模型

最终必须可以用下面一张图解释：

```text
                     Realtime Bar N
                           │
                           ▼
                MarketData Processor
                           │
                           ▼
             Virtual Broker previous work
                           │
                           ▼
                 Broker Facts drain
                           │
                           ▼
                    Strategy(N)
                           │
                           ▼
                       Risk
                           │
                           ▼
                    Reservation
                           │
                           ▼
                     Local Order
                           │
                           ▼
              OnlyBrokerExecutionService
                           │
                           ▼
                   Virtual Broker
                           │
                           ▼
                       Accepted
                           │
                           ▼
                 BrokerInboundQueue
                           │
                           ▼
                ExecutionProcessor
                           │
                           ▼
                 Durable Transaction
                           │
                           ▼
                      Projection


                     Realtime Bar N+1
                           │
                           ▼
              Virtual Broker NEXT_BAR
                           │
                           ▼
                         Trade
                           │
                           ▼
                 BrokerInboundQueue
                           │
                           ▼
                ExecutionProcessor
                           │
                           ▼
                 Durable Transaction
                           │
                           ▼
                      Projection
                           │
             ┌─────────────┼─────────────┐
             ▼             ▼             ▼
          Position       Account       Ledger
             │             │             │
             └────── Fee / Settlement ───┘
```

---

# 166. P6.3 的永久公式

实现结束后应该可以用四个公式概括系统：

```text
SIM
=
Realtime Driver
+
Shared Trading Kernel
+
Virtual Broker
```

```text
Order(N)
→ Accepted(N)
→ Trade(N+1 or later)
```

```text
Broker Fact
→ ExecutionProcessor
→ Durable Commit
→ Ordered Projection
```

```text
RuntimeMode.SIM
∉
Trading Economic Function
```

---

# 167. 最终报告要求

任务完成后不要只回复：

```text
done
```

必须提交结构化实现报告，至少包含：

## Repository State

```text
starting SHA
final SHA
branch
working tree state
```

## Baseline Certification

列出 P6.2 baseline CI 状态。

## Architecture Before

说明 P6.2 时：

```text
SIM recognized
but execution wiring pending
```

## Architecture After

说明：

```text
OnlySimRuntime
→ StreamingRuntime
→ TradingFacade
→ TradingKernel

Realtime Data
→ Virtual Broker
→ Broker Facts
→ ExecutionProcessor
```

## Production Code Changes

逐文件说明：

```text
what changed
why
```

## SIM Composition Contract

说明：

```text
Clock
DataSource
Broker
Queues
Persistence
Lifecycle
```

## Causal Ordering

明确报告并证明：

```text
Bar N
Order
Accepted
Bar N+1
Trade
```

## Safety

说明：

```text
Real Broker remains forbidden
Shadow not used
Bootstrap trading suppressed
Stop does not create economic facts
```

## Behavior Preservation

说明：

```text
BACKTEST
PAPER
Trading Kernel
MiniQMT
Virtual Broker
```

哪些保持不变。

## Tests

列出所有新增/修改测试。

## Local Verification

列出实际执行命令及结果。

## Remote CI

必须写：

```text
final SHA
workflow run
each independent lane
quality-gate
```

不得引用不同 SHA。

## Remaining P6 Scope

明确：

```text
P6.4 Gap + Reconnect

P6.5 Streaming Checkpoint + Restart

P6.6 Trading Semantic Conformance

P6.7 Operations / Soak

P6.8 Delete PAPER / SHADOW
```

---

# 168. 最终决策原则

如果实现过程中遇到选择：

优先选择：

```text
reuse existing Port
reuse existing Trading Kernel
reuse existing Virtual Broker
reuse existing ExecutionProcessor
reuse existing Transaction path
small Runtime composition change
explicit lifecycle ownership
deterministic causal ordering
fail closed
```

不要选择：

```text
new SIM subsystem
new manager
new policy abstraction
new broker worker
RuntimeMode economic branching
Paper inheritance
Backtest inheritance
Shadow fallback
```

P6.3 的优秀实现不应该表现为大量新增代码。

它应该表现为：

```text
少量 Runtime wiring
+
一个极薄 OnlySimRuntime
+
一个真正可工作的 SimFactory
+
一个强完整 integration vertical slice
+
清晰 architecture gates
```

如果最终 diff 很大：

优先重新检查是否错误地重新实现了已经存在的能力。
