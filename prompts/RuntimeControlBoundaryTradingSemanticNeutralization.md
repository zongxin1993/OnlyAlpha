# OnlyAlpha P6.1 — Runtime Control Boundary & Trading Semantic Neutralization

Repository:

`https://github.com/zongxin1993/OnlyAlpha`

本任务基于当前已经完成的 P6.0 Trading Runtime Kernel Extraction，继续实施：

# P6.1 — Runtime Control Boundary & Trading Semantic Neutralization

本任务同时完成两个紧密相关的问题：

1. 修复 Streaming Runtime 在 `stop()` 之后仍然处理剩余行情、进而产生新的 Market Fact 的行为回归。
2. 清除 RuntimeMode 对 Strategy 和 Trading Economic Plane 的残余污染。

这两个问题本质上属于同一个架构问题：

```text
Runtime Control Plane
        !=
Trading Semantic Plane
```

必须从第一性原理建立永久边界：

```text
Control Plane
Runtime Type
Runtime Factory
Driver
Clock
Lifecycle
Start / Stop
Subscription
Reconnect
Operational Status
Persistence Identity
        │
        │ 控制系统如何运行
        │
        ▼
──────────────────────────────────────
          Semantic Boundary
──────────────────────────────────────
        │
        │ 只传递规范化事实
        ▼
Trading Semantic Plane
Market Facts
Strategy
Market Rules
Risk
Reservation
Order
Broker Facts
Execution
Transaction
Projection
Position
Allocation
Fee
Settlement
Account
Strategy Ledger
```

核心原则：

> Lifecycle command 不得创造 Domain Fact。

以及：

> Runtime Type 不得成为 Trading Economic Decision 的输入。

---

# 1. 开始前必须重新审计当前仓库

不要根据本提示词机械修改。

首先重新读取当前 `master` HEAD 和相关实现。

重点至少检查：

```text
src/onlyalpha/runtime/runtime.py
src/onlyalpha/runtime/trading_facade.py

src/onlyalpha/runtime/trading/
    __init__.py
    config.py
    builder.py
    kernel.py
    services.py

src/onlyalpha/runtime/context.py

src/onlyalpha/runtime/backtest/
src/onlyalpha/runtime/streaming/
src/onlyalpha/runtime/paper/

src/onlyalpha/fee/
src/onlyalpha/market/
src/onlyalpha/position/
src/onlyalpha/risk/
src/onlyalpha/order/
src/onlyalpha/execution/
src/onlyalpha/settlement/
src/onlyalpha/account/
src/onlyalpha/strategy_ledger/

tests/architecture/
tests/integration/
tests/runtime/
tests/streaming/
tests/acceptance/

docs/architecture.md
docs/roadmap.md
docs/testing.md
docs/adr/0068-runtime-product-taxonomy-and-trading-semantic-equivalence.md

.github/workflows/quality.yml
scripts/test_suite.py
```

确认当前代码与本任务描述是否一致。

如果路径、类名或实现已经变化：

* 当前源码是事实来源。
* 本任务第一性原理、dependency direction 和验收条件是最终约束。
* 不要因为提示词里的旧类名而强行恢复旧结构。

---

# 2. 当前已知 P6.0 基线

当前 P6.0 已经建立了正确方向：

```text
OnlyBacktestRuntime
        │
        ▼
OnlyTradingRuntimeFacade
        │
        ▼
OnlyTradingKernel

OnlyStreamingRuntime
        │
        ▼
OnlyTradingRuntimeFacade
        │
        ▼
OnlyTradingKernel
```

Streaming 已经不应继承 Backtest。

Trading Kernel 已经应该满足：

```text
No OnlyRuntimeMode
No BACKTEST
No PAPER
No SIM
No LIVE
No concrete Runtime dependency
```

不要破坏这一结构。

---

# 3. 本任务解决的第一个具体问题：Streaming Stop

当前已知问题是：

Streaming Worker 正常消费循环退出后，还可能继续：

```python
while (update := queue.get()) is not None:
    ...
    processor.process(...)
```

导致：

```text
engine.stop()
    ↓
worker receives stop
    ↓
remaining queue gets drained
    ↓
pending live Bar may become finalized
    ↓
MarketDataProcessor.process()
    ↓
new closed Bar
    ↓
new observation / strategy work
```

当前 CI 已出现过类似表现：

```text
before stop:
closed_external_bar_count = N

after stop:
closed_external_bar_count = N + 1
```

这是错误语义。

---

# 4. Streaming Stop 的第一性原理

定义：

```text
STOP
=
revoke future processing permission
```

而不是：

```text
STOP
=
flush pending market state
```

因此：

```text
stop()
```

绝不能隐式产生：

```text
pending Bar -> closed Bar
queued update -> applied Market Fact
new Strategy callback
new Order Intent
new Broker Fact
new Transaction
new Position mutation
```

尤其不能把：

```text
Runtime stopped
```

解释成：

```text
market event time has advanced
```

Runtime lifecycle 和 market time 是两个不同的 authority。

---

# 5. Streaming Stop 正确语义

目标：

```text
RUNNING
   │
stop()
   ▼
STOPPING
   │
   ├─ deny new processing
   ├─ request worker stop
   ├─ unsubscribe external source
   ├─ join worker
   ├─ stop observation publisher
   └─ stop shared Runtime
   ▼
STOPPED
```

关键要求：

```text
STOPPING 之后不允许产生新的 Trading Semantic Fact。
```

---

# 6. 修改 Streaming Worker

重点检查：

```text
src/onlyalpha/runtime/streaming/worker.py
```

删除任何“收到 stop 之后继续 drain market-data queue 并 process”的逻辑。

推荐结构：

```python
def _run(self) -> None:
    try:
        while not self._stop.wait(0.01):
            update = self._queue.get()
            if update is None:
                continue

            if self._stop.is_set():
                break

            self._process_update(update)

    except BaseException as exc:
        self._failure = exc
        self._stop.set()
```

可以抽出一个简单 helper：

```python
def _process_update(
    self,
    update: OnlyMarketDataInboundUpdate,
) -> None:
    if self._stop.is_set():
        return

    if not self._accept_update(update):
        return

    for finalized in self._finalizer.accept(update):
        if self._stop.is_set():
            return

        if not self._accept_finalized(finalized):
            continue

        if not self._await_event_time(finalized):
            return

        if self._stop.is_set():
            return

        self._on_result(
            self._processor.process(finalized)
        )
```

具体实现按照当前代码结构调整。

不要为了形式强制照抄。

核心不变量：

```text
Once stop is observed,
no new call to MarketDataProcessor.process()
may begin.
```

---

# 7. 不允许在 stop 时 flush LiveBarFinalizer

严禁增加：

```python
finalizer.flush()
```

或者：

```python
finalizer.close_pending()
```

或者任何类似：

```text
stop
→ force pending Bar to become closed
```

的操作。

例如：

```text
10:43 - 10:44 Bar
仍然 pending

10:43:58 Runtime.stop()
```

不能因此产生：

```text
10:43 - 10:44 CLOSED Bar
```

因为 Runtime stop 不是 market-time evidence。

---

# 8. Stop 后的 queue 如何处理

本任务不要试图提前解决 Streaming Restart / Recovery。

不要主动：

```python
while queue.get() is not None:
    pass
```

去“清空”队列。

原因：

```text
未处理事实
```

和：

```text
已消费但丢弃事实
```

不是一个语义。

未来 Streaming checkpoint/restart 应通过：

```text
watermark
source sequence
checkpoint
historical query
catch-up
```

决定哪些事实需要恢复。

P6.1 不实现这一套。

所以当前正确行为只是：

```text
STOP
→ stop consuming
→ lifecycle terminates
```

---

# 9. StreamingRuntime.stop() 顺序

检查：

```text
src/onlyalpha/runtime/streaming/runtime.py
```

建议语义顺序：

```python
self._streaming_phase = OnlyStreamingPhase.STOPPING

self._driver.request_stop()

unsubscribe()

worker.stop()

observation_publisher.stop()

super().stop()
```

重点是：

```text
STOPPING
```

必须在停止动作开始时就建立。

不要等 worker 停止之后才设置。

同时保证：

```text
stop()
```

继续是幂等的。

---

# 10. Worker 与 Runtime 的责任边界

Streaming Driver / Worker 负责：

```text
subscription
market-data input
worker lifecycle
event-time wait
live-bar finalization
stop
```

Trading Runtime 负责：

```text
interpret normalized market facts
```

不要让 Worker 开始知道：

```text
Account
Position
Risk
Order
Transaction
Fee
Settlement
```

不要破坏 P6.0 Driver boundary。

---

# 11. 第二个核心任务：删除 Strategy-visible RuntimeMode

重点检查：

```text
src/onlyalpha/runtime/context.py
```

如果当前类似：

```python
@dataclass(frozen=True, slots=True)
class OnlyRuntimeContext:
    engine_id: ...
    runtime_id: ...
    cluster_id: ...
    mode: OnlyRuntimeMode
    ...
```

必须删除：

```python
mode
```

最终 Strategy Context 应类似：

```python
@dataclass(frozen=True, slots=True)
class OnlyRuntimeContext:
    engine_id: OnlyEngineId
    runtime_id: OnlyRuntimeId
    cluster_id: OnlyClusterId

    clock: OnlyClockView
    market_data: OnlyMarketDataView
    instruments: OnlyInstrumentView

    subscriptions: OnlySubscriptionService
    timers: OnlyTimerService

    orders: OnlyOrderServiceView
    positions: OnlyPositionContextView
    accounts: OnlyAccountQueryView
    ledger: OnlyStrategyLedgerContextView
    risk: OnlyRiskSnapshotView

    logger: OnlyRuntimeLogger
```

字段顺序和实际类名根据当前代码调整。

---

# 12. 不保留任何 Strategy RuntimeMode 兼容入口

不要提供：

```python
context.mode
```

deprecated property。

也不要增加：

```python
context.runtime_type
context.execution_mode

context.is_backtest
context.is_paper
context.is_sim
context.is_live
```

也不要通过：

```python
context.capabilities.runtime_type
```

绕回来。

P6.1 的目标就是从类型层面阻止 Strategy：

```python
if context.mode == BACKTEST:
    ...
```

---

# 13. Strategy Semantic Principle

最终必须满足：

```text
StrategyDecision
=
F(
    MarketFacts,
    Clock,
    PositionView,
    AccountView,
    RiskView,
    StrategyState,
    StrategyConfig
)
```

禁止：

```text
StrategyDecision
=
F(
    ...,
    RuntimeMode
)
```

这样未来：

```text
same strategy
same market facts
same economic state
```

才能在：

```text
BACKTEST
SIM
```

下产生相同 Trading Intent。

---

# 14. 清理 OnlyRuntimeLogger

检查当前：

```python
OnlyRuntimeLogger(
    logger,
    runtime_id,
    cluster_id,
    mode,
)
```

如果 Logger 只是为了输出：

```text
runtime=...
cluster=...
mode=...
```

建议从 Strategy Context 层完全去掉 mode。

改成：

```python
OnlyRuntimeLogger(
    logger,
    runtime_id,
    cluster_id,
)
```

prefix：

```text
runtime=<id> cluster=<id>
```

Runtime 产品类型属于 operational diagnostics。

如果其他 Runtime management logger 仍需要输出 mode，可以在 Context 之外完成。

不要为了日志保留 Strategy-visible RuntimeMode dependency。

---

# 15. 修改 TradingFacade._make_context()

重点检查：

```text
src/onlyalpha/runtime/trading_facade.py
```

当前如果存在：

```python
OnlyClusterContext(
    ...
    self.config.mode,
    ...
)
```

删除 mode 参数。

当前如果存在：

```python
OnlyRuntimeLogger(
    ...,
    self.config.mode,
)
```

也删除。

建议本次顺便把 Context 大型构造改为 keyword arguments。

原因不是代码风格，而是当前参数数量已经较多。

推荐：

```python
return OnlyClusterContext(
    engine_id=self.config.engine_id,
    runtime_id=OnlyRuntimeId(str(self.config.runtime_id)),
    cluster_id=cluster_id,

    clock=OnlyClockView(self._services.clock),

    market_data=OnlyMarketDataView(
        allowed_bar_types,
        latest,
        history,
        current_snapshot,
    ),

    instruments=OnlyInstrumentView(
        self._instruments
    ),

    subscriptions=OnlySubscriptionService(
        lambda subscription:
            self._subscribe(cluster_id, subscription)
    ),

    timers=OnlyTimerService(...),

    orders=OnlyOrderServiceView(...),

    positions=OnlyPositionContextView(...),

    accounts=OnlyAccountQueryView(...),

    ledger=OnlyStrategyLedgerContextView(...),

    risk=OnlyRiskSnapshotView(...),

    logger=OnlyRuntimeLogger(
        _LOGGER,
        self.config.runtime_id,
        cluster_id,
    ),
)
```

如果当前 Context 实际类型是 `OnlyClusterContext` 而不是 `OnlyRuntimeContext`：

按照真实代码修改。

核心要求：

```text
Strategy-facing context contains no RuntimeMode.
```

---

# 16. 第三个核心任务：TradingFacade 不再依赖 RuntimeMode

当前如果：

```python
class OnlyTradingRuntimeFacade(OnlyRuntime):
    _supported_modes: frozenset[OnlyRuntimeMode]

    def __init__(...):
        if config.mode not in self._supported_modes:
            ...
```

需要把 Runtime product validation 移到：

```python
OnlyRuntime
```

因为：

```text
supported Runtime product
```

是 Operational Runtime responsibility。

不是 Trading semantic facade responsibility。

---

# 17. 推荐 Runtime product guard 结构

改成类似：

```python
class OnlyRuntime:
    _supported_modes: frozenset[OnlyRuntimeMode] = frozenset()

    def __init__(
        self,
        config: OnlyRuntimeAssemblyConfig,
    ) -> None:
        if config.mode not in self._supported_modes:
            raise ValueError(
                f"{type(self).__name__} does not support "
                f"{config.mode.value} mode"
            )

        self.config = config

        ...
```

具体 Runtime 保留：

```python
class OnlyBacktestRuntime(
    OnlyTradingRuntimeFacade
):
    _supported_modes = frozenset({
        OnlyRuntimeMode.BACKTEST,
    })
```

Streaming 当前可以继续：

```python
class OnlyStreamingRuntime(
    OnlyTradingRuntimeFacade
):
    _supported_modes = frozenset({
        OnlyRuntimeMode.PAPER,
        OnlyRuntimeMode.LIVE,
    })
```

PAPER 是否继续单独 subclass，按当前代码维持。

---

# 18. 最终 RuntimeMode ownership

目标：

```text
OnlyRuntime
    KNOWS RuntimeMode

Concrete Runtime
    KNOWS supported RuntimeMode

Factory / Planner
    KNOWS RuntimeMode

Operational Status
    KNOWS RuntimeMode
```

但：

```text
OnlyTradingRuntimeFacade
    DOES NOT KNOW RuntimeMode

OnlyTradingKernel
    DOES NOT KNOW RuntimeMode

OnlyRuntimeContext
    DOES NOT KNOW RuntimeMode

Strategy
    DOES NOT KNOW RuntimeMode
```

---

# 19. 不要从整个工程删除 RuntimeMode

这是非常重要的 non-goal。

以下位置仍然可以合理使用：

```text
domain enum
config
scenario parser
runtime planning
runtime factory
concrete runtime guard
runtime status
inspection
persistence runtime identity
driver selection
```

所以不要使用：

```text
grep OnlyRuntimeMode
→ remove everything
```

正确判断标准只有一个：

> 这个 RuntimeMode 是否能改变交易经济结果？

---

# 20. RuntimeMode Allowed / Forbidden 分类

对全生产代码进行 audit。

每个 RuntimeMode occurrence 必须归入以下类别。

## ALLOWED

```text
PRODUCT_IDENTITY
FACTORY_SELECTION
DRIVER_SELECTION
LIFECYCLE
RUNTIME_STATUS
OBSERVABILITY
PERSISTENCE_RUNTIME_IDENTITY
CONFIG_PARSING
SCENARIO_PLANNING
```

## FORBIDDEN

```text
STRATEGY_BEHAVIOR
MARKET_RULE_ECONOMICS
POSITION_ECONOMICS
ALLOCATION_ECONOMICS
FEE_ECONOMICS
RISK_ECONOMICS
ORDER_PERMISSION
EXECUTION_CAPABILITY
TRANSACTION_SEMANTICS
SETTLEMENT_ECONOMICS
ACCOUNT_ECONOMICS
STRATEGY_LEDGER_ECONOMICS
```

如果发现 FORBIDDEN usage：

不能简单删逻辑。

必须先识别真正的 authority。

例如：

```text
runtime_mode
→ execution permission
```

应替换为：

```text
explicit execution capability
```

例如：

```text
runtime_mode
→ market legality
```

应替换为：

```text
compiled market policy
```

例如：

```text
runtime_mode
→ fee state
```

应替换为：

```text
explicit fee finality
```

---

# 21. Fee 模块原则

当前 Fee 如果已经：

```text
FeePolicy
+
FeeBasis
+
TradingDay
+
Liquidity
+
Explicit Finality
    ↓
FeeAssessment
```

就不要重构。

尤其不要新增：

```text
BacktestFeePolicy
PaperFeePolicy
SimFeePolicy
LiveFeePolicy

RuntimeFeeResolver
ModeFeeFinalityResolver
```

这些都是错误方向。

P6.1 对已经 mode-neutral 的 Fee path：

```text
Audit
Freeze
Architecture Gate
```

即可。

不要修改 Fee schema、Fee fingerprint、Fee transaction semantics。

---

# 22. Market Rule 模块原则

如果当前：

```text
OnlyCompiledMarketPolicyIdentity
```

已经只由：

```text
instrument
trading_day
reference fingerprint
compiler identity
policy fingerprint
```

组成：

不要修改。

不要把 RuntimeMode 加回来。

也不要为了 P6.1 创建新的 MarketRule wrapper。

Execution durable market evidence 如果已经只存：

```text
market_product_id
market_product_version
compiled_rule_fingerprint
reference_fingerprint
```

保持不变。

---

# 23. Position Authority 原则

如果 P6.0 已经完成：

```python
OnlyPositionAuthorityPolicy.local()
```

并且 Position authority 不再依赖：

```python
runtime_mode
```

则本任务不要重新设计 Position。

只添加/保留 Architecture Gate。

---

# 24. Execution Capability 原则

RuntimeMode 不得决定：

```text
order can submit?
fill can commit?
trade supported?
```

如果当前已经通过：

```text
Execution Capability Resolver
Market Product
Broker capability
```

等显式 authority 决定：

保持现状。

如果 audit 发现：

```python
if mode == LIVE:
    ...
```

参与 execution capability：

应替换为显式 capability，而不是换成另一个 mode 名字。

---

# 25. TradingFacade 不应继续读取 config.mode

最终：

```text
src/onlyalpha/runtime/trading_facade.py
```

应满足：

```text
OnlyRuntimeMode        0
config.mode            0
self.config.mode       0
```

注意：

这不代表：

```text
OnlyRuntimeAssemblyConfig
```

本身不能继续拥有 mode。

只是 TradingFacade 不应该使用它。

---

# 26. Context 模块必须完全 RuntimeMode-neutral

最终：

```text
src/onlyalpha/runtime/context.py
```

应满足：

```text
OnlyRuntimeMode        0
runtime_mode           0
runtime_type           0
is_backtest            0
is_live                0
is_sim                 0
is_paper               0
```

如果其中有自然语言 documentation 提到这些词，可根据 architecture test 实现方式合理处理。

生产 API 不允许这些 capability。

---

# 27. 新增 Architecture Test

建议新建：

```text
tests/architecture/test_runtime_control_semantic_boundary.py
```

不要把所有规则继续塞进 P6.0 的：

```text
test_trading_kernel_extraction.py
```

因为这是新的 architecture invariant。

---

# 28. Architecture Gate 1 — Strategy Context Neutrality

例如：

```python
def test_strategy_context_exposes_no_runtime_product_identity() -> None:
    fields = OnlyRuntimeContext.__dataclass_fields__

    assert "mode" not in fields
    assert "runtime_mode" not in fields
    assert "runtime_type" not in fields
```

如果实际 class 是：

```python
OnlyClusterContext
```

使用实际 Strategy-facing Context 类型。

还要检查：

```python
assert "OnlyRuntimeMode" not in context_source
```

---

# 29. Architecture Gate 2 — TradingFacade Neutrality

检查：

```text
src/onlyalpha/runtime/trading_facade.py
```

不得：

```text
import OnlyRuntimeMode
reference OnlyRuntimeMode
read self.config.mode
read runtime_config.mode
```

优先使用 AST。

不要只做脆弱字符串搜索。

---

# 30. Architecture Gate 3 — Economic Packages Neutrality

至少扫描：

```text
src/onlyalpha/fee/
src/onlyalpha/market/
src/onlyalpha/position/
src/onlyalpha/risk/
src/onlyalpha/order/
src/onlyalpha/execution/
src/onlyalpha/settlement/
src/onlyalpha/account/
src/onlyalpha/strategy_ledger/

src/onlyalpha/runtime/trading/
```

禁止 production code import/reference：

```python
OnlyRuntimeMode
```

不要禁止普通：

```text
mode
```

因为还有：

```text
PositionMode
TimerMode
RiskRuleMode
MarketPositionMode
```

这些完全合法。

---

# 31. Architecture Gate 4 — Runtime Product Identity Must Remain

需要一个正向 Gate 防止未来误删 Runtime product concept。

例如：

```python
def test_runtime_assembly_retains_product_identity() -> None:
    assert "mode" in OnlyRuntimeAssemblyConfig.__dataclass_fields__
```

并验证：

```text
Backtest Runtime accepts BACKTEST
Backtest Runtime rejects PAPER

Streaming Runtime accepts currently supported streaming modes
```

这证明：

```text
RuntimeMode
```

不是被删除了，而是被放到了正确的位置。

---

# 32. Architecture Gate 5 — Trading Kernel Existing Gate Must Stay Green

继续保留并通过 P6.0 已有约束：

```text
streaming package
    does not depend on backtest implementation

trading package
    does not depend on concrete runtime

trading kernel config
    contains no mode

base runtime
    does not directly construct mutable trading authorities

streaming driver
    does not import trading authorities
```

不要为了 P6.1 放宽这些 Gate。

---

# 33. Streaming Stop 单元测试

必须为 Worker 增加直接测试。

不要只依赖 Engine integration test。

至少覆盖以下行为。

## Test A — stop does not drain queue

构造：

```text
queue contains update A
queue contains update B

request stop

worker exits
```

断言：

```text
MarketDataProcessor.process
```

不会因为 stop 而额外调用。

测试关注 processor invocation，不要求固定内部 queue 实现。

---

# 34. Test B — stop does not flush pending bar

构造 LiveBarFinalizer 有 pending bar。

执行：

```text
stop
```

断言：

```text
pending bar
```

没有因为 stop 被：

```text
finalized
processed
observed
dispatched
```

---

# 35. Test C — stop interrupts future event wait

如果 worker 正等待：

```text
update.ts_event > RuntimeClock
```

此时：

```text
request_stop()
```

必须快速退出等待。

不应该：

```text
wait until event time
→ process event
→ then stop
```

---

# 36. Test D — stop is idempotent

连续：

```python
worker.stop()
worker.stop()
```

和：

```python
runtime.stop()
runtime.stop()
```

不能：

```text
raise unexpected error
duplicate unsubscribe
duplicate process
duplicate semantic fact
```

---

# 37. 保持已有 Integration shutdown contract

当前已有类似：

```text
before stop
closed_external_bar_count = N

engine.stop()

after stop
closed_external_bar_count = N
live_observation_count unchanged
latest_observation unchanged
```

的测试。

不要修改成：

```text
N or N+1
```

也不要删除断言。

测试定义的是正确 lifecycle semantics。

应修 production implementation。

---

# 38. Behavior Preservation Tests

P6.1 除 shutdown 修复外，不允许改变 Trading economics。

至少确认现有：

```text
BUY OPEN
SELL CLOSE

whole fill
partial fill
multi-fill

cancel
reject
expire

reservation
risk

transaction
projection

position
allocation

fee
settlement

account
strategy ledger

checkpoint
recovery

A-share product
```

保持一致。

---

# 39. Backtest 结果不能因为 P6.1 改变

如果已有：

```text
business fingerprint
result fingerprint
artifact fingerprint
transaction fingerprint
```

测试：

必须继续通过。

不要因为 P6.1 去更新 golden fixture，除非你能证明 fixture 代表的是错误 RuntimeMode semantic dependency。

默认规则：

```text
P6.1 should change architecture,
not economics.
```

---

# 40. 当前 CI regression 必须关闭

当前 P6.0 基线曾出现：

```text
core-full
1 failed
1276 passed
1 skipped
```

失败集中于 Streaming shutdown。

本任务第一阶段必须修复该 regression。

最终：

```text
core-full
```

必须全绿。

---

# 41. 不允许在本任务实现 SIM

禁止新增：

```text
OnlyRuntimeMode.SIM
OnlySimRuntime
OnlySimRuntimeFactory
SimConfig
```

除非当前仓库在任务开始前已经有这些类型。

如果已经存在：

本任务只做 mode boundary audit，不扩展其功能。

---

# 42. 不接 Virtual Broker Streaming

本任务不实现：

```text
Streaming MarketData
+
Virtual Broker
+
full simulated execution
```

这是后续 P6.2/P6.3。

不要借本任务顺手完成。

---

# 43. 不实现 Gap Recovery

当前 Streaming 如果只是：

```text
gap detected
→ counter + 1
```

保持。

不要实现：

```text
RECOVERING
historical missing-range query
replay
catch-up
```

这是后续阶段。

---

# 44. 不实现 Streaming Checkpoint / Restart

如果当前：

```python
_recover_runtime()
```

仍然只是 fresh bootstrap：

保持。

不要在 P6.1 中增加：

```text
streaming checkpoint
watermark restart
subscription restore
broker synchronization
```

---

# 45. 不删除 PAPER / SHADOW

本任务不处理最终 migration cleanup。

当前 PAPER / Shadow execution 保持已有功能。

只是：

```text
PAPER
```

不能再通过 Strategy Context 影响交易逻辑。

---

# 46. 不继续拆 TradingFacade

如果当前 `OnlyTradingRuntimeFacade` 仍然较大：

本任务不要因为文件大继续架构重构。

除非某段代码是为了清除 RuntimeMode semantic dependency 必须移动。

不要开展：

```text
ExecutionFacade extraction
RecoveryFacade extraction
ValuationFacade extraction
ContextFacade extraction
```

这些属于其他任务。

---

# 47. 不增加新第三方依赖

禁止为了本任务增加：

```text
DI framework
AST dependency library
architecture framework
event framework
```

Architecture test 使用标准库：

```python
ast
pathlib
inspect
```

即可。

---

# 48. 代码简洁性原则

优先：

```text
delete wrong branch
move product guard
remove context field
remove queue drain
add small invariant tests
```

而不是：

```text
add abstraction
add manager
add resolver
add facade
add compatibility layer
```

如果一个新 class 只有：

```text
把 RuntimeMode 转成另一个 enum
```

不要创建。

---

# 49. Hot Path 不增加无意义层级

不要把：

```python
processor.process(update)
```

改成：

```text
CommandBus
→ RuntimeCommand
→ CommandHandler
→ SemanticDispatcher
→ ProcessingFacade
→ Processor
```

P6.1 的目标是边界更清晰，不是调用链更长。

---

# 50. EventBus 原则保持不变

不要利用本任务把 lifecycle 或 RuntimeMode 变成新的 EventBus 控制系统。

保持：

```text
Commit Fact First
Project State Second
```

EventBus 不成为 mutable state write authority。

---

# 51. 具体实施顺序

严格推荐以下顺序。

## Phase A — Baseline Audit

先输出短审计：

```text
HEAD
current CI state

Streaming Worker stop behavior

Strategy Context RuntimeMode exposure

TradingFacade config.mode occurrences

RuntimeMode occurrences in economic packages

already-neutral:
    Position
    Fee
    Market Rule
    Execution Capability
```

不要只输出报告。

审计后立即开始修改。

---

## Phase B — Freeze Shutdown Behavior

先补必要 Worker tests。

不要修改已有正确 integration assertion。

建立：

```text
STOP
does not create new semantic facts
```

baseline。

---

## Phase C — Fix Worker Stop

删除 stop 后 drain。

保证：

```text
request_stop
```

后不再开始新的：

```text
processor.process()
```

---

## Phase D — Fix Runtime Stop Ordering

确保：

```text
STOPPING
→ stop permission
→ unsubscribe
→ worker stop
→ publisher stop
→ runtime stop
```

清晰。

不要 flush pending market state。

---

## Phase E — Remove Context RuntimeMode

删除：

```text
OnlyRuntimeContext.mode
```

和所有 Strategy-facing aliases。

同步修：

```text
context tests
cluster tests
strategy tests
examples
```

不要加 compatibility shim。

---

## Phase F — Remove Logger RuntimeMode

让 Strategy Runtime logger 不再需要 RuntimeMode。

Runtime operational logging 可以在 Context 外保留。

---

## Phase G — Move Product Guard to OnlyRuntime

将：

```text
_supported_modes validation
```

移到 Base Runtime operational boundary。

TradingFacade 删除 `OnlyRuntimeMode` import。

---

## Phase H — RuntimeMode Full Audit

扫描 production packages。

将 occurrence 分类：

```text
ALLOWED
FORBIDDEN
```

修掉所有 FORBIDDEN。

不要修改合理 ALLOWED usage。

---

## Phase I — Architecture Gates

新增：

```text
test_runtime_control_semantic_boundary.py
```

冻结：

```text
Context neutrality
TradingFacade neutrality
economic package neutrality
Runtime operational product identity
existing P6.0 kernel boundary
```

---

## Phase J — Documentation

更新：

```text
docs/architecture.md
docs/roadmap.md
ADR 0068
```

不要新增重复 ADR，除非当前项目 ADR policy 明确要求新 ADR。

---

## Phase K — Full Certification

执行全部正式质量门禁。

---

# 52. 文档需要明确写出的架构原则

P6.1 后 architecture 文档必须明确区分：

```text
Runtime Control Plane

Runtime Type
Factory
Driver
Clock
Lifecycle
Operational status
Persistence identity
```

和：

```text
Trading Semantic Plane

Market facts
Strategy
Market policy
Risk
Order
Execution
Transaction
Position
Fee
Settlement
Account
Ledger
```

并正式写入：

```text
Runtime Type != Execution Permission
```

以及：

```text
Lifecycle Command != Domain Fact
```

以及：

```text
Trading Semantic Plane MUST NOT branch on RuntimeMode.
```

---

# 53. 文档中的历史描述要同步修正

如果 architecture.md 仍说：

```text
Fee finality reads Runtime mode
Market Rule identity reads Runtime mode
Position authority reads Runtime mode
```

但当前代码已经完成中立化：

修正为当前事实。

不要让文档继续描述旧 architecture debt。

---

# 54. RuntimeMode architecture test 的实现要求

优先 AST。

例如：

```python
def _imports_runtime_mode(
    path: Path,
) -> bool:
    tree = ast.parse(
        path.read_text(encoding="utf-8"),
        filename=str(path),
    )

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if any(
                alias.name == "OnlyRuntimeMode"
                for alias in node.names
            ):
                return True

        if isinstance(node, ast.Name):
            if node.id == "OnlyRuntimeMode":
                return True

    return False
```

如果需要检测：

```python
self.config.mode
```

使用 AST Attribute chain。

不要通过：

```python
assert "mode" not in source
```

这种误伤测试。

---

# 55. 可以保留的 Runtime mode usage

示例：

```python
class OnlyBacktestRuntime(...):
    _supported_modes = {
        OnlyRuntimeMode.BACKTEST
    }
```

允许。

Factory：

```python
if config.mode == BACKTEST:
    create BacktestRuntime
```

允许。

Scenario planner：

```text
runtime: BACKTEST
```

允许。

Status：

```text
mode=BACKTEST
```

允许。

---

# 56. 明确禁止的 Runtime mode usage

禁止：

```python
if context.mode == BACKTEST:
    strategy.buy(...)
```

禁止：

```python
if config.mode == LIVE:
    fee = provisional
```

禁止：

```python
if runtime_mode == BACKTEST:
    allow_position(...)
```

禁止：

```python
if runtime_mode == SIM:
    allow_trade(...)
```

禁止：

```python
if mode == LIVE:
    settle(...)
```

如果发现：

必须替换为真正 authority。

---

# 57. Public API 原则

本任务允许删除：

```text
Strategy-visible context.mode
```

因为这是错误 architecture surface。

不要提供 deprecated alias。

但其他无关 public API 不要破坏。

不要修改：

```text
OnlyEngine
Backtest Result
Market Product plugin contract
Broker plugin contract
Persistence schema
Transaction schema
```

除非绝对必要。

---

# 58. Checkpoint / Persistence compatibility

本任务原则上：

```text
no checkpoint schema bump
no transaction schema bump
no market fingerprint change
no fee fingerprint change
```

如果你发现移除 RuntimeMode 会改变某个 persistence fingerprint：

先确认该 RuntimeMode 是否真的属于 operational identity。

如果只是 Runtime instance identity：

可以保留。

如果它错误地参与 economic fingerprint：

必须修正，但要增加 explicit migration/fail-closed validation。

不要静默修改 durable identity。

---

# 59. Shutdown 行为不等于 Recovery 行为

不要因为不 drain queue 就试图：

```text
save queue to checkpoint
```

不要。

正确的长期模型是：

```text
processed watermark
+
source sequence
+
historical recovery
```

但这是未来任务。

P6.1 只建立：

```text
stop does not synthesize facts
```

这个 invariant。

---

# 60. Error handling 原则

Worker failure：

```text
failure
→ record failure
→ stop signal
```

继续保持。

不要吞异常。

Runtime stop：

即使：

```text
unsubscribe fails
```

也应该按当前项目约定继续尝试：

```text
worker stop
publisher stop
super stop
```

并最终报告第一个/聚合 failure。

不要因为这个任务降低 cleanup reliability。

---

# 61. Performance 原则

本任务不能明显增加：

```text
per-Bar allocations
per-Bar dynamic dispatch
runtime mode lookups
reflection
event hops
```

理想上反而减少：

```text
mode field
mode branch
stop drain
```

hot path 应继续是直接 method call。

---

# 62. 完成条件：Streaming

必须全部满足：

```text
[ ] stop 不 drain market queue

[ ] stop 不 flush pending LiveBar

[ ] stop 后不开始新的 MarketDataProcessor.process()

[ ] stop 后 closed_external_bar_count 不增长

[ ] stop 后 live_observation_count 不增长

[ ] stop 后 Strategy 不获得新 callback

[ ] worker stop 幂等

[ ] runtime stop 幂等

[ ] future-event wait 可被 stop 中断
```

---

# 63. 完成条件：RuntimeMode

必须全部满足：

```text
[ ] Strategy-facing Context 不含 mode

[ ] Context 不含 runtime_type alias

[ ] Context 不含 is_backtest/is_live/is_sim/is_paper

[ ] Runtime Context module 不依赖 OnlyRuntimeMode

[ ] TradingFacade 不依赖 OnlyRuntimeMode

[ ] TradingFacade 不读取 config.mode

[ ] TradingKernel 继续完全 RuntimeMode-neutral

[ ] Fee economic code 不依赖 RuntimeMode

[ ] Market economic code 不依赖 RuntimeMode

[ ] Position economic code 不依赖 RuntimeMode

[ ] Risk economic code 不依赖 RuntimeMode

[ ] Order economic code 不依赖 RuntimeMode

[ ] Execution economic code 不依赖 RuntimeMode

[ ] Settlement economic code 不依赖 RuntimeMode

[ ] Account economic code 不依赖 RuntimeMode

[ ] Strategy Ledger economic code 不依赖 RuntimeMode
```

---

# 64. 完成条件：Operational Runtime

同时必须：

```text
[ ] OnlyRuntimeAssemblyConfig 继续拥有 Runtime product identity

[ ] concrete Runtime 继续声明 supported Runtime modes

[ ] wrong Runtime product / concrete Runtime combination fail closed

[ ] Factory 仍能根据 Runtime product 正确选择 Runtime

[ ] Runtime Status/Inspection 可以继续报告 product type
```

P6.1 不是删除 Runtime Type。

是限制它的 authority。

---

# 65. 完成条件：Architecture

必须：

```text
[ ] P6.0 Streaming -> Backtest prohibition 继续通过

[ ] Trading package -> concrete Runtime prohibition 继续通过

[ ] TradingKernelConfig 继续无 mode

[ ] 新 Runtime Control/Semantic Boundary Gate 建立

[ ] architecture tests 不依赖脆弱的简单全文字符串匹配
```

---

# 66. 完成条件：Behavior

必须：

```text
[ ] Backtest business semantics 不变

[ ] Order lifecycle 不变

[ ] Risk semantics 不变

[ ] Reservation semantics 不变

[ ] Transaction semantics 不变

[ ] Projection ordering 不变

[ ] Position semantics 不变

[ ] Allocation semantics 不变

[ ] Fee economics 不变

[ ] Settlement economics 不变

[ ] Account economics 不变

[ ] Strategy Ledger economics 不变

[ ] Recovery semantics 不变

[ ] A-share certified contract 不变
```

---

# 67. 必须执行的质量门禁

以当前仓库：

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

以及当前插件正式 mypy。

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

使用当前正式定义。

最后：

```bash
uv build --all-packages
```

---

# 68. 远程 CI 验收

如果环境允许推送：

必须检查同一最终 HEAD SHA 的：

```text
static
build
core-full
recovery
ashare
miniqmt-contract
quality-gate
```

不能使用旧 SHA 的绿色 CI 作为本任务认证。

如果当前执行环境不能推送：

明确报告：

```text
local verification completed
remote same-SHA certification not performed
```

不要声称 CI 已通过。

---

# 69. 严禁通过修改测试放松语义

特别是当前 Streaming shutdown failure。

不要：

```text
assert N or N + 1
```

不要：

```text
>= N
```

不要删除：

```text
after_stop == before_stop
```

如果测试表达：

```text
stop 后不产生新 closed bar
```

生产实现必须符合测试。

---

# 70. 不允许的伪修复

以下全部禁止。

## 错误方案 1

```python
if stopping:
    self._closed_external_bar_count -= 1
```

这是改统计，不是修语义。

## 错误方案 2

继续 process queue，但不记录 observation。

Trading fact 仍然被创建，错误。

## 错误方案 3

stop 时清空 queue。

这会把未处理 input silently consume。

## 错误方案 4

保留 Context.mode，但在文档里要求 Strategy 不使用。

无法 enforce。

## 错误方案 5

把：

```python
context.mode
```

改名：

```python
context.runtime_type
```

没有解决问题。

## 错误方案 6

增加：

```python
RuntimeSemanticPolicy.from_mode(...)
```

只是隐藏 mode branch。

## 错误方案 7

为了 TradingFacade 不 import OnlyRuntimeMode，再增加新的 duplicate enum。

严重错误。

---

# 71. 提交逻辑

建议逻辑 patch / commit 顺序：

```text
1. tests: freeze streaming stop semantic cutoff

2. streaming: stop worker without draining pending market input

3. runtime: enforce lifecycle cutoff before driver shutdown

4. context: remove runtime product identity from strategy surface

5. runtime: move product-mode guard to operational base runtime

6. architecture: enforce RuntimeMode semantic boundary

7. docs: certify P6.1 control/semantic separation
```

如果不实际创建多个 Git commit：

代码修改也按这个逻辑阶段保持清晰。

---

# 72. 最终报告格式

完成后必须提供：

## 1. Repository State

```text
starting HEAD
ending HEAD
branch
```

## 2. Root Causes

说明：

```text
Streaming shutdown 为什么会产生额外 Bar

RuntimeMode 为什么能泄漏到 Strategy
```

## 3. Architecture Before

展示：

```text
Runtime Control
   ↓
Trading semantic leak
```

## 4. Architecture After

展示：

```text
Control Plane
   ↓
fact boundary
   ↓
Trading Semantic Plane
```

## 5. Code Changes

按职责总结：

```text
Streaming Worker
Streaming Runtime
Context
TradingFacade
Base Runtime
Architecture tests
Docs
```

不要逐文件流水账。

## 6. RuntimeMode Audit

列出：

```text
ALLOWED occurrences
FORBIDDEN occurrences fixed
```

## 7. Behavior Preservation

说明哪些测试证明：

```text
Backtest economics unchanged
Recovery unchanged
A-share unchanged
```

## 8. Shutdown Certification

说明：

```text
stop no longer creates new semantic facts
```

并列出具体测试。

## 9. Verification

列出实际运行：

```text
ruff
format
mypy
fast
integration
recovery
ashare
miniqmt-contract
core-full
build
```

以及实际结果。

## 10. Remote CI

如果检查了同 SHA CI：

列出：

```text
SHA
workflow run
gate results
```

如果没有：

明确写未认证。

## 11. Remaining Scope

仅列真正后续：

```text
P6.2 SIM Runtime product identity

P6.3 Virtual Broker streaming execution wiring

P6.4 gap / reconnect recovery

P6.5 streaming checkpoint / restart

P6.6 Backtest/Sim trading semantic conformance

P6.7 operational soak / telemetry

P6.8 delete PAPER / standalone SHADOW
```

---

# 73. 最终工程不变量

任务完成后，下列公式必须成立。

## Runtime control

```text
RuntimeProduct
=
Driver
+
Clock
+
Lifecycle
+
Operational Identity
```

## Trading semantics

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

这里不允许：

```text
RuntimeMode
```

成为 `F()` 的输入。

---

# 74. Stop 不变量

```text
STOP
=
revoke processing permission
```

而不是：

```text
STOP
=
generate final facts
```

---

# 75. Strategy 不变量

```text
Strategy
```

可以知道：

```text
what happened
what is tradable
what do I own
how much risk is available
what time is it
```

但不能知道：

```text
am I backtesting?
am I simulating?
am I live?
```

如果 Strategy 真正需要某种业务能力：

提供明确业务 capability。

不要提供 Runtime product identity。

---

# 76. 本任务最终目标

完成后系统应具备：

```text
OnlyRuntime
    owns operational product identity

Concrete Runtime
    owns Driver/lifecycle specialization

OnlyTradingRuntimeFacade
    composes trading capabilities
    without RuntimeMode

OnlyTradingKernel
    owns mutable trading authorities
    without RuntimeMode

Strategy Context
    exposes trading capabilities
    without RuntimeMode

Streaming Driver
    delivers external market facts
    and stops without inventing new facts
```

最终必须做到：

> Runtime controls execution environment.

> Trading Kernel interprets facts.

> Strategy reacts to facts.

> Lifecycle never manufactures economics.

P6.1 的目标不是增加新的抽象。

它的目标是删除两类错误能力：

```text
stop() 生成新的 Market Fact
```

以及：

```text
Strategy / Trading semantics 读取 RuntimeMode
```

当这两项被彻底消除、Architecture Gate 固化且完整质量门禁重新全绿后，本任务才算完成。

之后才进入 P6.2 SIM Runtime Product Identity。
