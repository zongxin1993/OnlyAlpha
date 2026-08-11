# OnlyAlpha P6.2 — SIM Runtime Product Identity & Composition Contract

Repository:

`https://github.com/zongxin1993/OnlyAlpha`

当前目标阶段：

# P6.2 — SIM Runtime Product Identity & Composition Contract

本任务基于已经完成的：

```text
P6.0 — Trading Runtime Kernel Extraction
P6.1 — Runtime Control Boundary & Trading Semantic Neutralization
```

继续推进 P6。

本任务只建立：

```text
SIM Runtime Product Identity
+
SIM Configuration Contract
+
SIM Planning / Environment Identity
+
SIM Factory Composition Validation
+
SIM Safety Boundary
```

本任务**不实现完整可运行 SIM**。

完整的：

```text
Realtime MarketData
→ Trading Kernel
→ Order
→ Virtual Broker
→ Accepted / Trade / Terminal
→ Broker Inbound
→ Execution Processor
→ Transaction
→ Projection
```

留给后续 P6.3。

---

# 1. 第一性原理

不要从“新增哪些类”开始。

先冻结 SIM 产品定义：

```text
SIM
=
Realtime Market Data
+
Live Clock
+
Event-driven Trading Kernel
+
Local Simulated Broker
+
Local Virtual Account
+
Streaming Lifecycle
```

与其他 Runtime 的差异：

```text
BACKTEST
Historical Data
Backtest Clock
Virtual Broker
Trading Kernel
Finite Lifecycle

SIM
Realtime Data
Live Clock
Virtual Broker
Trading Kernel
Streaming Lifecycle

LIVE
Realtime Data
Live Clock
Real Broker
Trading Kernel
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

# 2. 最重要的架构原则

P6.2 必须继续遵守 P6.1 已经建立的边界：

```text
Runtime Control Plane
        !=
Trading Semantic Plane
```

Runtime Product 可以决定：

```text
Factory selection
Driver selection
Clock selection
Lifecycle
Operational identity
Persistence identity
Composition constraints
```

Runtime Product 不得决定：

```text
Strategy behavior
Market legality
Risk semantics
Order semantics
Position semantics
Allocation semantics
Fee semantics
Execution economic permission
Transaction semantics
Settlement semantics
Account semantics
Strategy Ledger semantics
```

核心公式：

```text
Runtime Product
=
Execution Environment Composition
```

而：

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

这里不能出现：

```text
RuntimeMode
```

---

# 3. 开始前必须重新审计当前仓库

不要机械按照本提示词修改。

首先读取当前 `master` HEAD。

至少检查：

```text
src/onlyalpha/domain/enums.py

src/onlyalpha/config/document.py
src/onlyalpha/config/models.py

src/onlyalpha/runtime/runtime.py
src/onlyalpha/runtime/factory.py
src/onlyalpha/runtime/defaults.py
src/onlyalpha/runtime/environment.py
src/onlyalpha/runtime/planning.py
src/onlyalpha/runtime/assembler.py
src/onlyalpha/runtime/__init__.py

src/onlyalpha/runtime/trading_facade.py
src/onlyalpha/runtime/trading/

src/onlyalpha/runtime/streaming/
src/onlyalpha/runtime/paper/
src/onlyalpha/runtime/backtest/
src/onlyalpha/runtime/live/
src/onlyalpha/runtime/shadow/
src/onlyalpha/runtime/research/

src/onlyalpha/plugin/broker.py
src/onlyalpha/plugin/data_source.py
src/onlyalpha/plugin/capabilities.py

packages/fake/onlyalpha-plugin-broker-virtual/
packages/provider/onlyalpha-plugin-miniqmt/

src/onlyalpha/runtime/persistence/

src/onlyalpha/engine/engine.py

tests/architecture/
tests/runtime/
tests/config/
tests/integration/

docs/roadmap.md
docs/architecture.md
docs/adr/0068-runtime-product-taxonomy-and-trading-semantic-equivalence.md

.github/workflows/quality.yml
scripts/test_suite.py
```

确认当前源码与本任务描述是否一致。

如果代码已经变化：

```text
current source code
>
旧提示词中的路径/类名
```

但以下 architecture invariants 不得改变。

---

# 4. 基线确认

任务开始前确认：

```text
P6.1 current HEAD
```

是否已经通过同 SHA：

```text
static
build
core-full
recovery
ashare
miniqmt-contract
quality-gate
```

如果仍有正在执行或失败的 lane：

记录当前状态。

不要把未完成的 CI 写成：

```text
P6.1 certified
```

但只要没有发现新的架构 blocker，可以继续本任务实现。

最终 P6.2 认证必须基于新的最终 HEAD。

---

# 5. P6.2 的明确产品边界

本任务目标是让系统正式理解：

```text
SIM is a valid target Runtime product
```

但同时明确：

```text
SIM is NOT executable until P6.3
```

因此 P6.2 的结束状态是：

```text
Recognized
+
Parsed
+
Planned
+
Composition Contract Validated
+
Safety Contract Validated
+
Fail Closed Before Execution
```

不是：

```text
Operational SIM
```

---

# 6. 当前阶段不要创建假的可运行 SIM

非常重要。

不要做：

```text
OnlySimRuntime
+
OnlyShadowExecutionService
```

这只是：

```text
PAPER renamed to SIM
```

禁止。

不要做：

```text
OnlySimRuntime.start()
→ NotImplementedError
```

这种空壳 Runtime 也没有价值。

不要为了“代码里存在 OnlySimRuntime”而创建没有正确 execution path 的类型。

本任务推荐：

```text
runtime/sim/
    __init__.py
    factory.py
```

暂时不需要：

```text
runtime.py
driver.py
config.py
services.py
```

除非当前代码结构变化后存在真实独立职责。

---

# 7. 新增正式 SIM Runtime identity

检查：

```text
src/onlyalpha/domain/enums.py
```

当前：

```python
class OnlyRuntimeMode(StrEnum):
    LIVE = "LIVE"
    PAPER = "PAPER"
    BACKTEST = "BACKTEST"
    SHADOW = "SHADOW"
    RESEARCH = "RESEARCH"
```

增加：

```python
SIM = "SIM"
```

不要删除：

```text
PAPER
SHADOW
```

它们当前仍是 migration debt。

其删除属于后续 P6。

---

# 8. 不增加 Runtime alias

只允许 canonical spelling：

```text
SIM
```

禁止新增：

```text
SIMULATION
PAPER_SIM
PAPER_TRADING
VIRTUAL
VIRTUAL_TRADING
```

也禁止：

```text
PAPER -> SIM compatibility alias
```

目标 taxonomy 是：

```text
RESEARCH
BACKTEST
SIM
LIVE
```

PAPER/SHADOW 当前保留只是 migration source。

---

# 9. 配置 parser 正式接受 SIM

检查：

```text
src/onlyalpha/config/document.py
```

当前如果存在：

```python
if self.runtime_type not in {
    "BACKTEST",
    "PAPER",
    "LIVE",
    "SHADOW",
    "RESEARCH",
}:
```

加入：

```python
"SIM"
```

保持当前 parser 设计。

不要借 P6.2 顺手重构整个配置层。

如果当前 parser 使用：

```python
.upper()
```

继续允许：

```text
sim
```

输入 canonicalize 成：

```text
SIM
```

但输出 identity 必须始终是：

```text
SIM
```

---

# 10. SIM 生命周期语义

正式定义：

```text
SIM is Streaming Runtime
```

因此：

```text
Finite Runtime:
BACKTEST

Streaming Runtime:
SIM
LIVE
```

PAPER 当前作为 migration implementation 暂时保留。

SIM 不能通过：

```text
OnlyEngine.run()
```

执行。

当前如果 Engine 中存在：

```python
if runtime_types != {"BACKTEST"}:
    raise OnlyLifecycleError(
        "OnlyEngine.run() is restricted to finite BACKTEST execution"
    )
```

必须保持。

不要把：

```text
SIM
```

加入 `run()`。

未来 SIM 生命周期应是：

```python
engine.initialize()
engine.start()
engine.wait()
engine.stop()
```

---

# 11. SIM 不支持有限时间范围

本阶段明确：

```text
SIM uses LiveClock
```

所以：

```text
runtime.start_time
runtime.end_time
```

不应定义 SIM 的有限运行区间。

在 SIM Factory validation 中要求：

```python
if config.start_time is not None:
    ...
```

失败。

以及：

```python
if config.end_time is not None:
    ...
```

失败。

推荐错误：

```text
SIM_FINITE_RANGE_NOT_SUPPORTED
```

或者分别：

```text
SIM_START_TIME_NOT_SUPPORTED
SIM_END_TIME_NOT_SUPPORTED
```

优先使用一个简单稳定错误码即可。

不要让 SIM 出现语义不明确的：

```text
start_time 是 bootstrap 边界？
行情过滤边界？
Runtime lifecycle？
```

---

# 12. Environment 不创建 SIM 特有实现

检查：

```text
src/onlyalpha/runtime/environment.py
```

当前如果：

```python
"HISTORICAL_REPLAY"
if config.runtime_type == "BACKTEST"
else
"LIVE_CLOCK"
```

则 SIM 加入后天然：

```text
SIM
→ LIVE_CLOCK
```

保持。

不要创建：

```text
OnlySimEnvironment
OnlySimEnvironmentBuilder
OnlyRealtimeSimulationEnvironment
```

新增测试即可。

---

# 13. SIM Environment identity 必须包含 SIM

当前：

```text
OnlyRuntimeEnvironmentIdentity.runtime_type
```

已经属于 fingerprint 输入。

保持。

测试：

```text
SIM environment
!=
PAPER environment

SIM environment
!=
BACKTEST environment
```

即便其他配置完全一致。

不要让 SIM 与 legacy PAPER 错误共享 Runtime grouping。

---

# 14. 继续复用 OnlyStreamingRuntimeConfig

当前如果存在：

```python
class OnlyExecutionSubmissionCapability(StrEnum):
    SHADOW = "SHADOW"
    SIMULATED = "SIMULATED"
    LIVE = "LIVE"
```

不要新增另一个 enum。

SIM 正式合同：

```text
runtime.type
=
SIM
```

要求：

```text
runtime.extensions.execution_capability
=
SIMULATED
```

这是：

```text
Product identity
+
Execution capability requirement
```

而不是：

```text
RuntimeMode decides execution semantics
```

---

# 15. Runtime Type != Execution Capability

不要实现：

```python
if runtime_type == "SIM":
    capability = SIMULATED
```

作为隐藏默认。

用户配置必须明确。

SIM Factory 验证：

```python
if streaming.execution_capability is not OnlyExecutionSubmissionCapability.SIMULATED:
    raise ...
```

必须 fail closed。

因此：

```text
SIM + SHADOW
→ invalid
```

```text
SIM + LIVE
→ invalid
```

```text
SIM + SIMULATED
→ continue validation
```

---

# 16. 推荐新增目录

新增：

```text
src/onlyalpha/runtime/sim/
    __init__.py
    factory.py
```

`__init__.py` 保持简单：

```python
from .factory import OnlySimRuntimeFactory

__all__ = ["OnlySimRuntimeFactory"]
```

不要增加无意义 re-export。

---

# 17. `OnlySimRuntimeFactory`

建议实现：

```python
class OnlySimRuntimeFactory:
    @property
    def runtime_type(self) -> str:
        return "SIM"
```

它现在只拥有：

```text
SIM composition contract validation
```

而不是 Runtime execution。

---

# 18. validate() 必须 fail closed

推荐结构：

```python
def validate(
    self,
    request: OnlyRuntimeBuildRequest,
) -> OnlyRuntimeBuildResult:
    try:
        self._validate(request)
    except Exception as exc:
        return self._failure(exc)

    return OnlyRuntimeBuildResult(
        failure_code="SIM_EXECUTION_WIRING_PENDING",
        failure_message=(
            "SIM composition is valid, but realtime "
            "Virtual Broker execution wiring is not "
            "implemented until P6.3"
        ),
    )
```

`create()` 当前也不要创建 Runtime：

```python
def create(
    self,
    request: OnlyRuntimeBuildRequest,
) -> OnlyRuntimeBuildResult:
    return self.validate(request)
```

如果当前 Factory contract 对 `validate()` 的失败语义有更适合的结构：

可以按现有风格调整。

但核心必须满足：

```text
Engine.validate()
must NOT claim SIM is executable.
```

---

# 19. 为什么 valid SIM 仍然返回失败

P6.2 只建立产品合同。

如果：

```text
Engine.validate()
→ success
```

但：

```text
Engine.initialize()
→ cannot create SIM Runtime
```

会造成错误产品语义。

因此当前阶段应该明确：

```text
SIM recognized
SIM config understood
SIM composition valid
SIM execution unavailable
```

通过：

```text
SIM_EXECUTION_WIRING_PENDING
```

表达。

等 P6.3 完成后：

```text
validate()
→ success
create()
→ OnlySimRuntime
```

再正式开放。

---

# 20. 不使用 Generic Unsupported Runtime Factory

不要注册：

```python
OnlyUnsupportedRuntimeFactory("SIM")
```

原因：

它只能表达：

```text
SIM unsupported
```

不能表达：

```text
SIM contract exists
SIM requires SIMULATED
SIM requires realtime source
SIM requires simulated Broker
SIM forbids real Broker
SIM forbids checkpoint
```

所以需要真正：

```text
OnlySimRuntimeFactory
```

但职责只限于 validation。

---

# 21. Factory validation 顺序

保持 deterministic validation ordering。

推荐：

```text
1. component registry type

2. config.runtime.runtime_type == SIM

3. streaming config parse

4. execution capability == SIMULATED

5. no finite start/end range

6. checkpoint disabled

7. exactly one enabled DataSource

8. DataSource capability validation

9. exactly one Account

10. exactly one enabled Broker

11. Broker simulated_execution capability

12. minimum Broker capability validation

13. existing generic Account/Broker reference integrity

14. return SIM_EXECUTION_WIRING_PENDING
```

不要让错误顺序依赖：

```text
dict iteration
plugin discovery order
filesystem order
```

---

# 22. Component Registry type validation

保持现有 Factory 风格。

例如：

```python
components = request.components

if not isinstance(
    components,
    OnlyComponentFactoryRegistries,
):
    raise TypeError(
        "Sim factory requires OnlyComponentFactoryRegistries"
    )
```

不要新增：

```text
OnlySimComponentRegistry
```

---

# 23. DataSource contract

P6.2 当前只支持：

```text
exactly one enabled realtime DataSource
```

原因：

这是现有 PAPER streaming baseline。

不要提前实现：

```text
multiple live feeds
fallback provider
active/passive feed
multi-source merge
```

验证：

```python
sources = tuple(
    item
    for item in config.data_sources
    if item.enabled
)

if len(sources) != 1:
    raise ...
```

推荐 code：

```text
SIM_DATA_SOURCE_COUNT_INVALID
```

---

# 24. DataSource 要求 historical + live capability

当前 streaming bootstrap 需要：

```text
Historical/Open-Market Bootstrap
+
Realtime handoff
```

所以当前 SIM 第一阶段要求：

```python
OnlyDataSourceCapabilities(
    historical_bars=True,
    live_bars=True,
)
```

不要硬编码：

```text
MiniQMT
```

Factory 必须通过 DataSource descriptor capability 校验。

正确：

```text
SIM requires capability
```

错误：

```text
SIM requires plugin_id == miniqmt
```

---

# 25. 不修改 MiniQMT

当前 MiniQMT DataSource 如果已经：

```text
validate_request()
→ requested capabilities
```

则无需改 provider。

明确目标：

```text
packages/provider/onlyalpha-plugin-miniqmt/
production diff = 0
```

除非当前源码发生新的真实兼容性问题。

---

# 26. SIM 必须恰好一个 Broker

与 PAPER 相反。

PAPER 当前：

```text
enabled Broker count = 0
```

SIM 必须：

```text
enabled Broker count = 1
```

第一阶段不要支持：

```text
multi-broker
broker routing
primary/secondary broker
```

验证：

```python
brokers = tuple(
    item
    for item in config.brokers
    if item.enabled
)

if len(brokers) != 1:
    raise ...
```

推荐：

```text
SIM_BROKER_COUNT_INVALID
```

---

# 27. Broker 必须明确支持 simulated_execution

最重要安全规则：

```text
SIM MUST NOT compose Real Broker execution
```

不要判断：

```text
plugin_id == virtual
```

而要判断：

```text
capabilities.simulated_execution == True
```

即：

```python
broker_factory = components.brokers.resolve(
    broker.plugin_id
)

capabilities = broker_factory.descriptor.capabilities

if not capabilities.simulated_execution:
    raise ...
```

推荐：

```text
SIM_SIMULATED_BROKER_REQUIRED
```

---

# 28. 不硬编码 Virtual Broker plugin

不要：

```python
if broker.plugin_id != "virtual":
    reject
```

因为：

```text
Broker identity
!=
Broker capability
```

未来另一个 simulated Broker 只要满足正式 SPI contract，也应该可以作为 SIM execution adapter。

---

# 29. SIM 必须拒绝 Real Broker

重点测试：

```text
SIM
+
Broker:
    submit_order=True
    cancel_order=True
    simulated_execution=False
```

必须失败。

即使这个 Broker 功能更多也不允许。

`simulated_execution` 是决定性能力。

---

# 30. Broker minimum capabilities

第一阶段建议要求：

```text
submit_order
cancel_order
query_orders
query_trades
simulated_execution
```

不要过度要求：

```text
query_positions
query_account
query_fee_evidence
```

除非当前 Trading Kernel/P6.3 已明确需要它们。

P6.2 不提前设计后续 reconciliation contract。

---

# 31. 不修改 Virtual Broker

当前 Virtual Broker 如果已经支持：

```text
submit_order
cancel_order
query_orders
query_trades
simulated_execution
checkpoint
deterministic driver
```

保持。

明确目标：

```text
packages/fake/onlyalpha-plugin-broker-virtual/
production diff = 0
```

P6.2 只验证能力。

---

# 32. Account contract

当前 Runtime schema 已经要求：

```text
exactly one shared Account per Runtime
```

不要新增：

```text
OnlySimAccount
SimAccountConfig
SimAccountManager
```

继续复用 canonical Account authority。

如果通用 Config 已保证：

```text
Account.gateway_id
references configured Broker
```

不要在 SimFactory 重复复杂验证。

只补 SIM-specific requirement。

---

# 33. 当前禁止 SIM checkpoint

虽然 Virtual Broker 本身可能 checkpointable：

也不能因此开放 SIM checkpoint。

完整 streaming checkpoint/restart 还需要：

```text
MarketData watermark
subscription identity
LiveBar finalizer state
aggregation state
Streaming lifecycle state
Trading Kernel checkpoint
Broker inbound progress
Virtual Broker state
transaction tail
projection progress
```

当前没有闭环。

因此：

```python
if config.runtime.persistence.checkpoint.enabled:
    raise ...
```

推荐：

```text
SIM_CHECKPOINT_NOT_SUPPORTED
```

Roadmap 可标注：

```text
until P6.5
```

但生产错误消息不要硬绑定阶段号，除非项目惯例如此。

---

# 34. Persistence identity 不需要重构

当前如果：

```text
OnlyRuntimePersistenceStoreCreateRequest
```

已经有：

```text
runtime_mode
```

作为 operational identity：

保持。

新增：

```text
OnlyRuntimeMode.SIM
```

后未来自然支持。

本任务不要：

```text
bump persistence schema
bump checkpoint schema
change transaction schema
change economic fingerprint
```

---

# 35. Register SIM Factory

检查：

```text
src/onlyalpha/runtime/defaults.py
```

增加：

```python
from onlyalpha.runtime.sim.factory import (
    OnlySimRuntimeFactory,
)
```

然后：

```python
runtimes.register(
    OnlySimRuntimeFactory()
)
```

完成后：

```python
registry.require("SIM")
```

必须返回正式 SIM Factory。

---

# 36. Public Runtime export

本阶段没有：

```text
OnlySimRuntime
```

所以不要在：

```text
runtime/__init__.py
```

虚构 export。

可以不 export SIM Runtime class。

如果项目 public API 需要暴露 Factory：

按当前 Factory export 风格处理。

不要为了对称增加无意义 Runtime class。

---

# 37. Architecture Gate：SIM 不依赖 PAPER

新增：

```text
tests/architecture/test_sim_runtime_product_boundary.py
```

必须冻结：

```text
runtime/sim
MUST NOT import
runtime/paper
```

迁移方向是：

```text
PAPER infrastructure
→ migrated into shared Streaming boundary
→ SIM
```

不是：

```text
SIM wraps PAPER
```

---

# 38. Architecture Gate：SIM 不依赖 Backtest Runtime

禁止：

```text
runtime/sim
→ runtime/backtest/runtime.py
```

SIM 和 Backtest 共享：

```text
Trading Kernel
Virtual Broker SPI
economic semantics
```

而不是继承彼此 Runtime implementation。

---

# 39. Architecture Gate：SIM 不使用 Shadow execution

禁止：

```text
runtime/sim
→ OnlyShadowExecutionService
```

也禁止：

```text
SHADOW capability
```

作为合法 SIM fallback。

SIM 不是 Shadow。

---

# 40. Architecture Gate：SIM 不创建经济 authority

扫描：

```text
src/onlyalpha/runtime/sim/
```

禁止直接创建/import concrete：

```text
AccountManager
PositionManager
RiskManager
OrderManager
FeeEngine
SettlementManager
TransactionCoordinator
StrategyLedgerManager
```

SIM Runtime 产品不拥有另一套经济实现。

---

# 41. 保持现有 P6.1 Gate

必须继续通过：

```text
Strategy Context has no RuntimeMode

TradingFacade has no RuntimeMode

Trading Kernel has no RuntimeMode

economic packages have no RuntimeMode
```

新增：

```text
OnlyRuntimeMode.SIM
```

后这些 Gate 仍应完全绿色。

如果新增 SIM 导致这些模块需要改：

优先认为设计错误。

---

# 42. `OnlyStreamingRuntime` 暂时不要支持 SIM

当前如果：

```python
_supported_modes = frozenset({
    OnlyRuntimeMode.PAPER,
    OnlyRuntimeMode.LIVE,
})
```

P6.2 建议保持。

不要提前：

```python
OnlyRuntimeMode.SIM
```

加入。

因为当前 Streaming Runtime 尚未拥有：

```text
broker gateway
broker inbound queue
deterministic broker driver
```

完整 SIM composition wiring。

等 P6.3 创建真正：

```text
OnlySimRuntime
```

时再：

```text
OnlySimRuntime
    ↓
OnlyStreamingRuntime
```

---

# 43. 不修改 `OnlyTradingRuntimeFacade`

明确目标：

```text
src/onlyalpha/runtime/trading_facade.py
production diff = 0
```

P6.2 是产品 identity/composition。

如果必须修改 TradingFacade 才能“支持 SIM”：

说明在提前做 P6.3。

停止扩张任务。

---

# 44. 不修改 Trading Kernel

明确：

```text
src/onlyalpha/runtime/trading/**
production diff = 0
```

新增 SIM 应该只影响 operational composition plane。

---

# 45. 不修改 Strategy Context

禁止新增：

```text
mode
runtime_type
is_sim
execution_mode
```

Strategy 不需要知道 SIM 存在。

---

# 46. 不修改 Fee / Position / Risk / Order / Settlement

P6.2 不涉及经济逻辑。

推荐保持：

```text
fee/
position/
risk/
order/
execution economic logic
settlement/
account/
strategy_ledger/
```

生产 diff 为 0。

---

# 47. 不实现 Streaming Broker wiring

明确禁止修改：

```text
OnlyStreamingRuntime
```

去新增完整：

```text
broker_gateway
broker_inbound_queue
deterministic_broker_driver
```

除非只是不可避免的非常小 contract preparation，但默认不做。

真正 wiring 属于 P6.3。

---

# 48. 不实现 Virtual Broker streaming drive

禁止：

```text
market bar
→ VirtualBroker.on_bar()
→ BrokerFacts
```

这一条本任务不实现。

不要通过测试 fixture 假装它已经存在。

---

# 49. 不实现 gap/reconnect

P6.2 不处理：

```text
sequence gap
historical gap recovery
reconnect
catch-up
watermark verification
```

属于 P6.4。

---

# 50. 不实现 streaming checkpoint/restart

属于 P6.5。

不要因为 SIM Factory 已经知道 Virtual Broker checkpoint capability 就提前做。

---

# 51. 不删除 PAPER

当前 PAPER 仍是 legacy streaming migration source。

保持：

```text
runtime/paper/
```

以及当前测试。

不要新增 PAPER 功能。

---

# 52. 不删除 SHADOW

当前 PAPER 仍依赖 Shadow execution。

保持。

只确保：

```text
SIM never depends on SHADOW
```

---

# 53. 不实现 SIM Result/Artifact

不要创建：

```text
OnlySimResult
OnlySimArtifact
OnlySimReport
```

没有 executable SIM 就没有正式 Runtime result contract。

后续再定义。

---

# 54. Config tests

至少新增：

```text
runtime.type = SIM
→ parse success
```

并断言 canonical：

```text
SIM
```

禁止 alias。

---

# 55. Environment tests

至少覆盖：

```text
SIM
→ runtime_type == SIM
→ clock_policy == LIVE_CLOCK
```

以及：

```text
SIM fingerprint != PAPER fingerprint
SIM fingerprint != BACKTEST fingerprint
```

当其他配置相同。

---

# 56. Factory Registry tests

验证：

```python
factory = registry.require("SIM")

assert factory.runtime_type == "SIM"
```

并确保错误从：

```text
RUNTIME_FACTORY_NOT_AVAILABLE
```

变成：

```text
SIM-specific validation
```

---

# 57. Valid SIM contract test

构造：

```text
runtime.type = SIM

execution_capability = SIMULATED

one Account

one enabled DataSource
with:
    historical_bars
    live_bars

one enabled Broker
with:
    simulated_execution
    submit_order
    cancel_order
    query_orders
    query_trades

checkpoint disabled

no start_time
no end_time
```

最终必须：

```text
SIM_EXECUTION_WIRING_PENDING
```

不是：

```text
RUNTIME_FACTORY_NOT_AVAILABLE
```

不是：

```text
success
```

---

# 58. Invalid execution capability tests

必须：

```text
SIM + SHADOW
→ reject
```

```text
SIM + LIVE
→ reject
```

错误应发生在：

```text
SIM execution capability validation
```

而不是更晚才失败。

---

# 59. Invalid Broker tests

至少：

```text
SIM + no enabled Broker
→ reject

SIM + two enabled Brokers
→ reject

SIM + real Broker
→ reject

SIM + simulated Broker
→ continue
```

---

# 60. Invalid DataSource tests

至少：

```text
SIM + no DataSource
→ reject

SIM + two DataSources
→ reject

SIM + historical-only DataSource
→ reject

SIM + live-only DataSource
→ reject
    if bootstrap contract currently requires historical bars

SIM + historical+live DataSource
→ continue
```

---

# 61. Finite range tests

```text
SIM + start_time
→ reject

SIM + end_time
→ reject
```

不要接受它们然后忽略。

---

# 62. Checkpoint test

```text
SIM + checkpoint.enabled = true
→ reject
```

明确表明：

```text
SIM checkpoint/restart is not yet supported
```

---

# 63. Engine validation behavior

当前阶段：

```text
Engine.validate()
```

对于完整合法 SIM composition：

应该返回：

```text
invalid
```

并包含：

```text
SIM_EXECUTION_WIRING_PENDING
```

这是预期产品行为。

不要为了让测试漂亮而返回 valid。

---

# 64. `OnlyEngine.run()` test

继续确保：

```text
SIM
```

不能通过：

```python
engine.run()
```

执行。

它应该继续得到 finite execution lifecycle error。

不要改变 BACKTEST-only contract。

---

# 65. Architecture tests

新增或扩展正式 architecture tests，至少冻结：

```text
runtime/sim does not import runtime/paper

runtime/sim does not import runtime/backtest runtime

runtime/sim does not import ShadowExecutionService

runtime/sim does not create economic authorities

SIM does not appear in Trading Kernel branches

SIM does not appear in Strategy Context

SIM does not appear in TradingFacade economic branches
```

优先 AST。

不要使用：

```python
assert "SIM" not in entire_file
```

这种过宽测试。

---

# 66. Runtime mode audit

新增 `SIM` 后重新扫描所有：

```text
OnlyRuntimeMode
```

usage。

新增合法 occurrence 应主要在：

```text
domain enum
config/runtime operational layer
SIM factory
tests
docs
```

不应新增到：

```text
trading_facade
runtime/trading
strategy context
fee
market economics
position
risk
order
execution economics
settlement
account
strategy ledger
```

---

# 67. Error code设计原则

不要把所有失败都塞进：

```text
RUNTIME_ASSEMBLY_FAILED
```

至少以下应该可区分：

```text
SIM_EXECUTION_CAPABILITY_REQUIRED
SIM_FINITE_RANGE_NOT_SUPPORTED
SIM_CHECKPOINT_NOT_SUPPORTED
SIM_DATA_SOURCE_COUNT_INVALID
SIM_DATA_SOURCE_CAPABILITY_REQUIRED
SIM_BROKER_COUNT_INVALID
SIM_SIMULATED_BROKER_REQUIRED
SIM_EXECUTION_WIRING_PENDING
```

如果现有项目错误码风格不同：

遵循当前命名风格。

不要过度增加几十个 code。

原则：

```text
不同用户修复动作
→ 不同 error code
```

---

# 68. Factory helper 不要过度抽象

不要新增：

```text
OnlySimCompositionPlan
OnlySimExecutionPolicy
OnlySimCapabilityResolver
OnlySimBrokerValidator
OnlySimDataSourceValidator
```

一个 `_validate()` 足够。

保持代码直接。

---

# 69. 不抽取 Backtest Factory 基类

即使 SimFactory 与 BacktestFactory 都验证 simulated Broker：

不要现在创建：

```text
OnlyTradingRuntimeFactoryBase
OnlyVirtualBrokerRuntimeFactoryBase
```

目前复用证据不足。

少量重复比错误抽象更简单。

P6.3 后如果重复稳定，再考虑纯 helper。

---

# 70. 不增加新依赖

禁止新增第三方包。

不需要：

```text
DI framework
validation framework
architecture framework
```

使用当前标准库和既有工具。

---

# 71. 代码风格

优先：

```text
small explicit Factory
explicit validation
existing capability structs
existing registries
existing environment identity
```

避免：

```text
dynamic magic
reflection-based product composition
generic service container expansion
new command bus
new manager
new resolver
```

---

# 72. 文档更新

更新：

```text
docs/roadmap.md
docs/architecture.md
docs/adr/0068-runtime-product-taxonomy-and-trading-semantic-equivalence.md
```

如果 ADR 0068 是 immutable historical ADR：

按项目当前 ADR policy 使用 implementation update，而不是重写 Decision history。

---

# 73. Roadmap 中 P6.2 状态

完成后应该写清：

```text
P6.2 — SIM Runtime Product Identity & Composition Contract
DONE
```

但必须明确：

```text
SIM is recognized and composition-validatable,
but is not yet executable.
```

不要写：

```text
SIM Runtime available
```

不要写：

```text
SIM product complete
```

---

# 74. 文档中的 Runtime taxonomy

应明确：

```text
RESEARCH
Historical + Vectorized/Batch

BACKTEST
Historical + Event-driven + Virtual Broker

SIM
Realtime + Event-driven + Virtual Broker

LIVE
Realtime + Event-driven + Real Broker
```

同时：

```text
PAPER
legacy migration source

SHADOW
legacy execution/migration debt
```

---

# 75. P6.2 后的实现状态表

文档建议更新为：

```text
BACKTEST
Enum: Yes
Config: Yes
Factory: Yes
Operational: Yes

SIM
Enum: Yes
Config: Yes
Factory: Yes
Operational: No — execution wiring pending

LIVE
Enum: Yes
Config: Yes
Factory: Unsupported
Operational: No

RESEARCH
Enum: Yes
Config: Yes
Factory: Unsupported
Operational: No

PAPER
Legacy implementation

SHADOW
Legacy migration debt
```

---

# 76. 不改变 Backtest economics

P6.2 必须完全保持：

```text
Order
Accepted
Trade
Terminal
Risk
Reservation
Transaction
Projection
Position
Allocation
Fee
Settlement
Account
Strategy Ledger
PnL
Result
Recovery
```

Backtest output 不应变化。

---

# 77. 不更新经济 golden fixture

如果 P6.2 导致：

```text
Backtest business fingerprint
transaction fingerprint
artifact fingerprint
result fingerprint
```

变化：

默认视为 bug。

不要直接更新 fixture。

先找出为什么一个 SIM product identity patch 改变了 Backtest economics。

---

# 78. Quality gates

以当前：

```text
docs/testing.md
scripts/test_suite.py
.github/workflows/quality.yml
```

为最终来源。

至少执行：

```bash
uv run ruff check src tests examples packages scripts

uv run ruff format --check src tests examples packages scripts

uv run mypy src/onlyalpha
```

以及当前 workspace/plugin 正式 mypy lanes。

然后：

```bash
uv run python scripts/test_suite.py fast

uv run python scripts/test_suite.py integration

uv run python scripts/test_suite.py recovery

uv run python scripts/test_suite.py ashare

uv run python scripts/test_suite.py miniqmt-contract

uv run python scripts/test_suite.py core-full
```

如果当前 lane 名已变化：

以仓库正式定义为准。

最后：

```bash
uv build --all-packages
```

---

# 79. Remote CI

如果推送：

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

全部来自同一 SHA。

不要引用 P6.1 的绿色 CI 作为 P6.2 认证。

---

# 80. 禁止伪完成方案

以下全部禁止。

## 错误 1

```text
SIM
→ ShadowExecutionService
```

## 错误 2

```text
SIM
→ PaperRuntime
```

## 错误 3

```text
SIM
→ BacktestRuntime
```

## 错误 4

```text
OnlySimRuntime
```

存在，但没有 Virtual Broker 标准 fact path。

## 错误 5

```text
Engine.validate(SIM)
→ success
```

但 initialize 无法执行。

## 错误 6

通过：

```text
plugin_id == virtual
```

判断模拟执行。

## 错误 7

RuntimeMode.SIM 进入 Trading Kernel。

## 错误 8

Context 新增：

```text
is_sim
```

## 错误 9

为了 SIM 修改 Fee / Position / Risk economic behavior。

## 错误 10

提前实现 P6.3/P6.4/P6.5。

---

# 81. 推荐实施阶段

## Phase A — Baseline Audit

输出：

```text
starting HEAD
P6.1 CI state
SIM current enum/config/factory state
Streaming current composition
Virtual Broker current capabilities
MiniQMT current capabilities
```

然后继续执行，不要只停在审计。

---

## Phase B — SIM Lexical Identity

实现：

```text
OnlyRuntimeMode.SIM
config parser accepts SIM
```

补配置测试。

---

## Phase C — SIM Environment Identity

冻结：

```text
SIM -> LIVE_CLOCK
```

以及 fingerprint/grouping identity。

---

## Phase D — SIM Factory Contract

新增：

```text
runtime/sim/factory.py
```

实现 composition validation。

---

## Phase E — Safety Validation

实现：

```text
SIM requires SIMULATED

SIM requires one realtime DataSource

SIM requires historical + live capabilities

SIM requires one simulated Broker

SIM rejects real Broker

SIM rejects checkpoint

SIM rejects finite range
```

---

## Phase F — Factory Registry

注册：

```text
OnlySimRuntimeFactory
```

让：

```text
registry.require("SIM")
```

成立。

---

## Phase G — Architecture Gates

冻结：

```text
SIM X PAPER dependency
SIM X Backtest Runtime dependency
SIM X ShadowExecutionService
SIM X economic authorities
```

---

## Phase H — Product Tests

验证：

```text
valid SIM composition
→ SIM_EXECUTION_WIRING_PENDING
```

以及所有 fail-closed 错误。

---

## Phase I — Documentation

更新 roadmap/architecture/ADR implementation status。

---

## Phase J — Full Certification

执行所有正式测试和 build。

检查同 SHA remote quality gate。

---

# 82. Definition of Done

必须全部满足：

```text
[ ] OnlyRuntimeMode.SIM exists

[ ] runtime.type=SIM parses

[ ] SIM is canonical spelling

[ ] no PAPER->SIM alias

[ ] SIM environment uses LIVE_CLOCK

[ ] SIM environment identity differs from PAPER/BACKTEST

[ ] OnlySimRuntimeFactory exists

[ ] default Runtime registry registers SIM

[ ] SIM Factory does not create a Runtime yet

[ ] valid SIM config returns SIM_EXECUTION_WIRING_PENDING

[ ] Engine.validate does not claim SIM is executable

[ ] SIM requires SIMULATED execution capability

[ ] SIM rejects SHADOW

[ ] SIM rejects LIVE capability

[ ] SIM requires exactly one enabled DataSource

[ ] DataSource must support historical bars

[ ] DataSource must support live bars

[ ] SIM requires exactly one enabled Broker

[ ] Broker must support simulated_execution

[ ] SIM rejects Real Broker

[ ] SIM rejects checkpoint

[ ] SIM rejects finite start/end range

[ ] SIM does not depend on PAPER

[ ] SIM does not depend on Backtest Runtime

[ ] SIM does not depend on ShadowExecutionService

[ ] SIM does not create economic authorities

[ ] Trading Kernel unchanged

[ ] TradingFacade unchanged

[ ] Strategy Context unchanged

[ ] Virtual Broker implementation unchanged

[ ] MiniQMT implementation unchanged

[ ] OnlyEngine.run remains BACKTEST-only

[ ] P6.1 architecture gates remain green

[ ] Backtest economics unchanged

[ ] Recovery unchanged

[ ] A-share certification tests unchanged

[ ] MiniQMT contract tests unchanged

[ ] static green

[ ] build green

[ ] core-full green

[ ] recovery green

[ ] ashare green

[ ] miniqmt-contract green

[ ] final same-SHA quality-gate green
```

---

# 83. P6.2 完成后的目标结构

```text
OnlyEngine
    │
    ▼
Runtime Planner
    │
    ├── BACKTEST
    ├── SIM
    ├── LIVE
    └── RESEARCH
         │
         ▼
Runtime Factory Registry
         │
         ▼
OnlySimRuntimeFactory
         │
         ├── Runtime identity
         ├── LiveClock contract
         ├── Streaming lifecycle contract
         ├── Realtime DataSource contract
         ├── Simulated Broker contract
         ├── Safety validation
         └── Fail Closed
                 │
                 ▼
      SIM_EXECUTION_WIRING_PENDING
```

Trading path remains untouched:

```text
Trading Kernel
Market Rule
Risk
Reservation
Order
Execution
Transaction
Projection
Position
Allocation
Fee
Settlement
Account
Ledger
```

全部不知道 SIM 存在。

---

# 84. P6.3 的明确接续点

P6.2 完成后，P6.3 只处理：

```text
OnlySimRuntime
    ↓
OnlyStreamingRuntime
    ↓
Realtime MarketData
    ↓
Trading Kernel
    ↓
Order
    ↓
Virtual Broker
    ↓
Accepted
Trade
Terminal
    ↓
Broker Inbound Queue
    ↓
Execution Processor
    ↓
Durable Transaction
    ↓
Ordered Projection
```

P6.3 再把：

```text
SIM_EXECUTION_WIRING_PENDING
```

替换为真正 Factory create success。

不要在 P6.2 提前完成这一条。

---

# 85. 最终任务原则

P6.2 不追求增加大量代码。

最佳结果应该是：

```text
少量 enum/config change
+
一个很小的 SIM Factory
+
清晰的 capability validation
+
architecture gates
+
tests
+
docs
```

而不是：

```text
新的 Runtime hierarchy
新的 Manager
新的 Policy
新的 Resolver
新的 Broker
新的 Trading semantics
```

最终建立三个永久不变量：

```text
SIM Product
=
Realtime
+
Streaming
+
Simulated Execution Requirement
```

```text
SIM Execution Safety
=
Explicit Simulated Broker Capability
```

以及：

```text
P6.2
=
Recognized
+
Validated
+
Fail Closed

P6.3
=
Executable
```

完成全部实现、测试、文档和同 SHA 质量门禁后，再将 P6.2 标记为 DONE。
