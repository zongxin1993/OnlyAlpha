# OnlyAlpha P6.4 — Realtime Market Continuity & Same-Process Recovery

## 1. Repository

Repository:

```text
https://github.com/zongxin1993/OnlyAlpha
```

目标阶段：

```text
P6.4 — Realtime Market Continuity & Same-Process Recovery
```

当前 P6 Runtime 路线：

```text
P6.0 — Trading Runtime Kernel Extraction
P6.1 — Runtime Control Boundary & Trading Semantic Neutralization
P6.2 — SIM Runtime Product Identity & Composition Contract
P6.3 — SIM Realtime Virtual Broker Execution Wiring
P6.4 — Realtime Market Continuity & Same-Process Recovery   ← 本任务
P6.5 — Streaming Checkpoint + Restart
P6.6 — Trading Semantic Conformance
P6.7 — Operations / Soak
P6.8 — Delete PAPER / SHADOW
```

---

# 2. 总体任务要求

本任务必须完整实现 P6.4。

不要只：

- 阅读代码；
- 输出审计报告；
- 给出设计建议；
- 添加接口占位；
- 添加 TODO；
- 添加未接线的 Recovery abstraction；
- 写测试但不完成 production wiring。

必须在重新审计当前 HEAD 后，继续完成：

```text
设计
→ 实现
→ 单元测试
→ 集成测试
→ Architecture Gate
→ 文档
→ 本地验证
→ Remote same-SHA CI certification
```

---

# 3. 开始任务前：强制重新审计当前 HEAD

不要假定本提示词记录的 SHA、文件内容或类签名仍然是最新。

第一步必须读取当前：

```text
master HEAD
```

并记录：

```text
starting SHA
branch
working tree state
latest commit
```

然后重新确认：

1. P6.3 当前是否真正完成；
2. SIM normal realtime path 是否仍然成立；
3. 当前 Streaming Runtime 架构；
4. 当前 MarketData Processor 架构；
5. 当前 MiniQMT DataSource connection / subscription contract；
6. 当前 Virtual Broker contract；
7. 当前 test lanes；
8. 当前 GitHub Actions workflow；
9. P6.3 当前 same-SHA CI 状态。

至少重新阅读：

```text
src/onlyalpha/data/enums.py
src/onlyalpha/data/models.py
src/onlyalpha/data/processor.py
src/onlyalpha/data/ports.py
src/onlyalpha/data/queue.py

src/onlyalpha/plugin/capabilities.py
src/onlyalpha/plugin/data_source.py
src/onlyalpha/plugin/lifecycle.py

src/onlyalpha/runtime/runtime.py
src/onlyalpha/runtime/trading_facade.py

src/onlyalpha/runtime/streaming/config.py
src/onlyalpha/runtime/streaming/phase.py
src/onlyalpha/runtime/streaming/health.py
src/onlyalpha/runtime/streaming/live_bar.py
src/onlyalpha/runtime/streaming/worker.py
src/onlyalpha/runtime/streaming/driver.py
src/onlyalpha/runtime/streaming/runtime.py

src/onlyalpha/runtime/sim/runtime.py
src/onlyalpha/runtime/sim/factory.py

src/onlyalpha/core/clock.py
src/onlyalpha/market/session_clock.py

packages/provider/onlyalpha-plugin-miniqmt/
packages/fake/onlyalpha-plugin-broker-virtual/

tests/architecture/
tests/integration/
tests/runtime/
tests/acceptance/

scripts/test_suite.py
.github/workflows/quality.yml

docs/roadmap.md
docs/runtime.md
docs/architecture.md
docs/adr/
```

同时全仓搜索：

```text
GAP_DETECTED
UNEXPECTED_GAP
EXPECTED_SESSION_GAP

sequence_gap
SequenceTracker
GapDetector
Deduplicator

STALE
DISCONNECTED
RECONNECTING
connection_snapshot

CATCH_UP
BOOTSTRAP
historical_watermark
processed_bar_identities
latest_bars

set_live_sequence_floor
LiveBarFinalizer

stop_requested
processing_permission

live_reconnect
```

如果当前源码已经比本文描述进一步演化：

> 以 current HEAD source 为实现事实。

但是本任务定义的：

```text
Architecture Invariants
Product Semantics
P6.4 Scope
Fail-Closed Semantics
Definition of Done
```

仍然必须满足。

---

# 4. P6.3 Baseline 必须先稳定

上一轮已知 P6.3 基线曾为：

```text
bbd8b27bc509066b96462ad1e67ec29e02d63af7
Feat: SIM Realtime Virtual Broker Execution Wiring
```

该版本曾出现一个 integration observation race：

```text
tests/integration/test_engine_sim_virtual_broker_execution.py
```

失败类似：

```python
assert accepted_records[0].projection_ready
```

当时真实顺序为：

```text
Broker Accepted
→ durable commit
→ projection apply
→ Order Manager 可观察到 ACCEPTED
→ mark_projection_ready
→ transaction formally Ready
```

测试只等待：

```text
Order == ACCEPTED
```

随后立刻查询：

```text
transaction.projection_ready
```

因此可能正好落入：

```text
Order projection 已完成
但 projection_ready durable flag 尚未完成
```

的合法短暂窗口。

## 4.1 如果当前 HEAD 尚未修复

只做最小 certification stabilization。

等待条件应类似：

```python
_wait_until(
    lambda: (
        len(runtime.order_snapshots) == 1
        and runtime.order_snapshots[0].status is OnlyOrderStatus.ACCEPTED
        and runtime.ready_execution_query.ready_count(
            OnlyRuntimeId(runtime.runtime_id)
        ) == 1
    ),
    "Accepted transaction did not reach Projection Ready",
)
```

然后再读取 transaction。

禁止使用：

```text
sleep(...)
arbitrary retry delay
修改 TransactionCoordinator ordering
修改 Projection semantics
降低 assertion
```

## 4.2 P6.4 的基线要求

P6.4 正式实现前，应尽可能建立：

```text
P6.3 final certified baseline
```

并确认当前正式 lanes 全绿。

如果当前 HEAD 已经完成此修复，则不要重复修改。

---

# 5. P6.4 唯一产品目标

P6.4 解决：

```text
Realtime Market Continuity
+
Same-Process Forward Recovery
```

含义：

```text
Runtime process remains alive
        ↓
Realtime MarketData suffers:
    unexpected gap
    stale
    disconnect
        ↓
Runtime can no longer prove complete market history
        ↓
revoke new trading input permission
        ↓
recover missing historical Market Facts
        ↓
replay them through the same Market pipeline
        ↓
reconcile buffered realtime suffix
        ↓
verify continuity again
        ↓
restore LIVE
```

---

# 6. P6.4 明确不做什么

P6.4 不实现：

```text
Streaming checkpoint

New-process restart

Virtual Broker checkpoint restore

MarketData queue persistence

LiveBarFinalizer restart restore

Recovery plan persistence

Real Broker reconnect

Real Broker order reconciliation

Real Broker account reconciliation

LIVE Runtime

PAPER removal

SHADOW removal

Exponential retry

Backoff framework

Circuit breaker framework

Long-running production soak
```

这些属于后续阶段。

严格保持：

```text
P6.4 = same-process forward recovery

P6.5 = new-process restart recovery
```

---

# 7. 第一性原理一：Unknown Market History = No Trading Permission

假设已经确认处理：

```text
09:30
09:31
```

随后收到：

```text
09:35
```

并且：

```text
BarType
+
TradingCalendar
+
last confirmed Bar
```

证明：

```text
09:32
09:33
09:34
```

应该存在。

此时：

```text
09:35
```

绝不能先进入：

```text
MarketDataPipeline
Virtual Broker
Strategy
Risk
Order
```

再事后补历史。

正确因果顺序必须是：

```text
09:31 confirmed
        ↓
09:35 arrives
        ↓
unexpected gap detected
        ↓
09:35 NOT admitted
        ↓
DEGRADED
        ↓
RECOVERING
        ↓
09:32
09:33
09:34
        ↓
same Market pipeline
        ↓
CATCH_UP
        ↓
09:35
        ↓
buffered realtime suffix
        ↓
continuity proven
        ↓
LIVE
```

永久公式：

```text
Unknown Market History
=
No New Trading Permission
```

---

# 8. 第一性原理二：Detection != Acceptance

Gap detection 回答：

```text
如果接受这个 Market Fact，
是否仍然可以证明 continuity？
```

它不能在检测的同时把该 Market Fact 变成 accepted history。

必须：

```text
ASSESS
    ↓
ADMISSION DECISION
    ↓
COMMIT ACCEPTED CONTINUITY
```

禁止：

```text
ASSESS + MUTATE ACCEPTED FRONTIER
```

---

# 9. 第一性原理三：Recovery Fact = Normal Market Fact

恢复：

```text
09:32
09:33
09:34
```

后不能：

```text
只修改 watermark

只更新 Indicator

直接调用 VirtualBroker.on_bar()

直接更新 Position

直接更新 Account

调用专门 RecoveryExecutionProcessor
```

必须：

```text
Normalized Recovery Market Fact
        ↓
OnlyMarketDataProcessor
        ↓
same MarketDataPipeline
        ↓
same before_dispatch
        ↓
same Virtual Broker
        ↓
same Strategy pipeline
        ↓
same Trading Kernel
        ↓
same ExecutionProcessor
        ↓
same Durable Transaction
        ↓
same Ordered Projection
```

永久公式：

```text
Recovery Market Fact
=
Normal Market Fact
```

---

# 10. 第一性原理四：Recovery 可以恢复已有订单，但不能补发过去的新订单

如果故障前已经存在：

```text
Order A = ACCEPTED
```

恢复：

```text
09:32
```

时：

```text
Virtual Broker
→ match Order A
→ Trade A
```

必须允许。

因为：

```text
Order A
```

在故障之前已经是既存 Broker state。

但是如果：

```text
Recovered 09:33
→ Strategy generates BUY B
```

则：

```text
BUY B
```

不能 retroactively submit。

必须被 Runtime 拦截。

建议正式错误/诊断：

```text
ORDER_INTENT_SUPPRESSED_DURING_RECOVERY
```

所以：

| Recovery 行为 | 是否允许 |
|---|---:|
| Indicator update | YES |
| Factor update | YES |
| Strategy state update | YES |
| Existing Broker Order progression | YES |
| Existing Broker Order Trade | YES |
| New Strategy Order submit | NO |

永久原则：

```text
Recovery restores already-existing causal state.

Recovery does not create retroactive external trading permission.
```

---

# 11. 第一性原理五：Transport Restored != Trading Permission Restored

Reconnect：

```text
connect success
authenticate success
subscribe success
```

只能证明：

```text
future transport restored
```

不能证明：

```text
past history complete
```

禁止：

```text
Reconnect
→ subscribe accepted
→ LIVE
```

必须：

```text
Reconnect
→ resubscribe
→ historical repair
→ recovery replay
→ realtime catch-up
→ continuity verification
→ LIVE
```

永久公式：

```text
Transport Restored
!=
Trading Permission Restored
```

只有：

```text
Transport Restored
+
Missing Facts Recovered
+
Buffered Suffix Reconciled
+
Continuity Proven
=
LIVE
```

---

# 12. P6.4 不允许建立第二套 Trading System

禁止新增：

```text
OnlySimRecoveryManager
OnlySimGapDetector
OnlySimOrderManager
OnlySimPositionManager
OnlySimAccountManager
OnlySimRiskManager
OnlySimExecutionProcessor
OnlySimTransactionCoordinator
```

禁止新增：

```text
RecoveryTradingKernel
RecoveryExecutionService
RecoveryBrokerGateway
RecoveryPositionService
```

必须继续使用：

```text
OnlyTradingKernel

OnlyTradingRuntimeFacade

OnlyMarketDataProcessor

OnlyExecutionProcessor

OnlyRuntimeTransactionCoordinator

OnlyRuntimeProjectionApplier

Virtual Broker

existing DataSource SPI
```

目标：

```text
Trading Kernel production diff = 0

TradingFacade economic diff ≈ 0

Virtual Broker economic diff = 0
```

如果出现：

```python
if runtime_mode is SIM:
```

进入经济代码：

> 设计错误。

如果出现：

```python
if recovering:
```

进入 Trading Kernel：

> 优先重新审查架构。

---

# 13. Streaming Phase 状态机

当前如果仍然是：

```text
CREATED
SUBSCRIBING
BOOTSTRAP
CATCH_UP
LIVE
STOPPING
STOPPED
FAILED
```

增加两个真正稳定概念：

```text
DEGRADED
RECOVERING
```

目标：

```text
CREATED
   ↓
SUBSCRIBING
   ↓
BOOTSTRAP
   ↓
CATCH_UP
   ↓
LIVE
   │
   │ unexpected gap
   │ stale
   │ disconnect
   ▼
DEGRADED
   ↓
RECOVERING
   ↓
CATCH_UP
   ↓
LIVE
```

错误路径：

```text
DEGRADED
    ↓
FAILED
```

或：

```text
RECOVERING
    ↓
FAILED
```

或：

```text
CATCH_UP
    ↓
FAILED
```

Stop：

```text
any active phase
    ↓
STOPPING
    ↓
STOPPED
```

---

# 14. Streaming Runtime 是 Phase 唯一 authority

不要让：

```text
Worker
DataSource
MiniQMT
recovery.py
```

直接决定：

```text
Streaming Phase
```

Runtime 才拥有：

```text
LIVE
DEGRADED
RECOVERING
CATCH_UP
FAILED
```

的 operational transition。

如果需要，可以增加一个很小 private helper：

```python
_set_streaming_phase(...)
```

但不要增加 State Machine framework。

---

# 15. StreamingPhase 与 StreamingDataState 继续正交

不要合并：

```text
OnlyStreamingPhase
OnlyStreamingDataState
```

Phase：

```text
Runtime processing lifecycle
```

DataState：

```text
MarketData health observation
```

例如：

```text
phase = RECOVERING
data_state = CATCHING_UP
```

合理。

例如：

```text
phase = LIVE
data_state = STALE
```

可作为触发 DEGRADED 前的 observation。

不要建立：

```text
StreamingMegaState
RecoveryMegaState
```

---

# 16. P6.4 最关键底层改造：Assess / Commit Separation

重新检查：

```text
OnlyMarketDataDeduplicator
OnlyMarketDataSequenceTracker
OnlyMarketDataGapDetector
```

当前若存在：

```text
检测的同时推进内部状态
```

必须拆开。

这是 P6.4 的底层正确性基础。

---

# 17. Deduplicator 改造

当前如果类似：

```python
def seen(self, update):
    key = ...
    if key in self._keys:
        return True

    self._keys.add(key)
    return False
```

必须拆为：

```python
def contains(
    self,
    update: OnlyMarketDataInboundUpdate,
) -> bool:
    return self._key(update) in self._keys
```

以及：

```python
def remember(
    self,
    update: OnlyMarketDataInboundUpdate,
) -> None:
    self._keys.add(self._key(update))
```

含义：

```text
contains
=
assessment

remember
=
accepted fact commit
```

不要保留：

```text
seen()
```

compatibility alias。

直接修改正式调用点。

---

# 18. SequenceTracker 改造

建议增加：

```python
@dataclass(frozen=True, slots=True)
class OnlyMarketDataSequenceAssessment:
    stale: bool
    gap: bool
```

然后：

```python
def assess(
    self,
    update: OnlyMarketDataInboundUpdate,
) -> OnlyMarketDataSequenceAssessment:
    ...
```

`assess()` 只读取：

```text
previous accepted sequence
```

不得修改：

```python
self._last
```

增加：

```python
def commit(
    self,
    update: OnlyMarketDataInboundUpdate,
) -> None:
    ...
```

只有正式 admitted Market Fact 才调用。

逻辑类似：

```python
previous = self._last.get(key)
current = int(update.source_sequence)

return OnlyMarketDataSequenceAssessment(
    stale=previous is not None and current <= previous,
    gap=previous is not None and current > previous + 1,
)
```

commit：

```python
self._last[key] = int(update.source_sequence)
```

---

# 19. GapDetector 改造

当前若有：

```python
previous = self._last_bars.get(bar.bar_type)

self._last_bars[bar.bar_type] = bar
```

发生在：

```text
assess
```

内部，则必须拆开。

目标：

```python
assess(...)
```

只读取：

```text
accepted last bar
```

并返回：

```text
quality flags
```

新增：

```python
commit(update)
```

才更新：

```text
_last_bars
```

永久 invariant：

```text
Rejected post-gap candidate
MUST NOT
advance accepted continuity frontier
```

---

# 20. 为什么这个拆分是必须的

例：

```text
accepted last = 09:31

incoming = 09:35
```

检测后如果内部已经变成：

```text
last = 09:35
```

那么之后恢复：

```text
09:32
09:33
09:34
```

会被误判成：

```text
STALE
OUT_OF_ORDER
```

因此必须保持：

```text
09:35 GAP_DETECTED
```

后：

```text
accepted last remains 09:31
```

---

# 21. Processor 正确的新执行顺序

目标：

```text
validate
    ↓
deduplicator.contains
    ↓
sequence_tracker.assess
    ↓
gap_detector.assess
    ↓
classify
```

然后：

```text
if stale:
    return STALE
```

然后：

```text
if UNEXPECTED_GAP:
    return GAP_DETECTED
```

只有可以正式接受后：

```text
deduplicator.remember
sequence_tracker.commit
gap_detector.commit
```

然后：

```text
pipeline.process_bar
    ↓
before_dispatch
    ↓
Strategy dispatch
    ↓
after_dispatch
    ↓
APPLIED
```

---

# 22. 最重要 Processor invariant

以下：

```text
UNEXPECTED_GAP
```

必须在：

```text
pipeline.process_bar()
```

之前返回。

所以 gap update：

```text
MUST NOT call pipeline.process_bar

MUST NOT call before_dispatch

MUST NOT call Strategy dispatcher

MUST NOT call after_dispatch
```

这是 P6.4 最重要 Architecture Gate。

---

# 23. EXPECTED_SESSION_GAP 不能触发 recovery

继续复用：

```text
TradingCalendar
```

区分：

```text
EXPECTED_SESSION_GAP
```

与：

```text
UNEXPECTED_GAP
```

例如：

```text
11:30
→ lunch
→ 13:00
```

应该：

```text
EXPECTED_SESSION_GAP
→ accepted
→ commit continuity
→ normal process
```

同理：

```text
overnight
weekend
holiday
```

如果 Calendar 证明合法，不进入 recovery。

---

# 24. Sequence Gap 不是 Recovery Time Range Authority

Transport sequence：

```text
100
→
104
```

只能证明：

```text
transport continuity suspicious
```

不能直接证明：

```text
exact missing time Bars
```

Recovery time range 必须根据：

```text
last confirmed Bar

trigger Bar

BarType

TradingCalendar
```

计算。

---

# 25. 新增最小 recovery.py

建议：

```text
src/onlyalpha/runtime/streaming/recovery.py
```

只放：

```text
immutable data model
pure calculation helper
```

不要创建：

```text
RecoveryManager
RecoveryCoordinator
RecoveryOrchestrator
RecoveryPolicyEngine
GapResolutionService
```

---

# 26. Recovery Reason

建议：

```python
class OnlyStreamingRecoveryReason(StrEnum):
    GAP = "GAP"
    STALE = "STALE"
    DISCONNECTED = "DISCONNECTED"
```

不要引入：

```text
RuntimeMode
```

---

# 27. Recovery Plan

建议：

```python
@dataclass(frozen=True, slots=True)
class OnlyStreamingRecoveryPlan:
    generation: int
    reason: OnlyStreamingRecoveryReason

    instrument_id: OnlyInstrumentId
    bar_type: OnlyBarType

    confirmed_bar_end: OnlyTimestamp
    recovery_target: OnlyTimestamp

    trigger_update: OnlyMarketDataInboundUpdate | None
```

字段按 current HEAD 实际需要微调。

保持：

```text
small
immutable
evidence only
```

不要把：

```text
Runtime
Queue
DataSource
Manager
Callback
Broker
```

塞进去。

---

# 28. Confirmed Market Frontier

不要增加：

```text
FrontierManager
```

重新审计当前：

```text
_latest_bars
```

如果它只在：

```text
successful MarketData pipeline processing
```

后更新，那么它可以继续作为：

```text
Confirmed Market Frontier
```

定义：

```text
last Market Fact for which
all prior required Market Facts
have been accepted and processed
```

Recovery 起点必须来自：

```text
confirmed frontier
```

不能来自：

```text
last received
last callback
last rejected gap trigger
```

---

# 29. HistoricalWatermark 不扩大职责

当前 startup：

```text
HistoricalWatermark
```

负责：

```text
Historical Bootstrap
→ Realtime handoff
```

保持这个职责。

不要把它改成：

```text
Generic Runtime Recovery Manager
```

Runtime live recovery 使用：

```text
confirmed processed frontier
```

即可。

---

# 30. Worker 继续保持 Single Consumer

保持：

```text
DataSource callback
       ↓
MarketDataInboundQueue
       ↓
Streaming Worker
       ↓
MarketDataProcessor
```

禁止增加：

```text
RecoveryThread
ReconnectThread
Second MarketData Worker
Second Queue Consumer
```

这是保证：

```text
deterministic market causal ordering
```

的关键。

---

# 31. Recovery 期间 queue 就是 realtime buffer

当 Worker 处理：

```text
historical recovery
```

时：

DataSource callback 继续：

```text
put realtime update
```

进入：

```text
MarketDataInboundQueue
```

所以 queue 自然就是：

```text
Buffered Realtime Suffix
```

不要新建：

```text
RecoveryRealtimeQueue
```

---

# 32. Worker 需要知道 update + result

如果当前 callback 是：

```python
on_result(result)
```

导致 Runtime 不知道哪个 input 触发 gap，则修改为：

```python
on_result(update, result)
```

或者增加：

```python
on_gap(update, result)
```

保持简单。

---

# 33. Recovery 不能持有 Processing Permission Lock

当前 processing lock 是：

```text
Stop future-processing cutoff
```

的重要 authority。

禁止：

```python
with processing_permission:
    historical query
    reconnect
    replay 300 bars
```

否则：

```text
engine.stop()
```

会被长时间阻塞。

正确：

```text
process one candidate
↓
detect gap
↓
release lock
↓
Runtime recovery orchestration
```

Replay 每个 normalized Bar 时，重新走 normal processing boundary。

---

# 34. Gap Recovery 完整算法

例：

```text
Confirmed:
09:31

Incoming:
09:35
```

## Step 1

Processor：

```text
09:35
→ assess
→ UNEXPECTED_GAP
→ GAP_DETECTED
```

且：

```text
no Pipeline
no Broker
no Strategy
```

## Step 2

Runtime 保存：

```text
trigger_update = 09:35
confirmed_frontier = 09:31
```

## Step 3

Phase：

```text
LIVE
→ DEGRADED
```

## Step 4

增加：

```text
recovery_generation += 1
```

## Step 5

构造：

```text
RecoveryPlan
```

## Step 6

Phase：

```text
DEGRADED
→ RECOVERING
```

## Step 7

Historical query：

```text
09:32
09:33
09:34
```

## Step 8

Strict validate historical coverage。

## Step 9

Normalize recovery MarketData updates。

## Step 10

依次 replay：

```text
09:32
09:33
09:34
```

通过：

```text
OnlyMarketDataProcessor
```

## Step 11

Phase：

```text
RECOVERING
→ CATCH_UP
```

## Step 12

处理：

```text
original trigger 09:35
```

以及 queue 中：

```text
09:36
09:37
...
```

## Step 13

确定性排序、overlap/dedup。

## Step 14

追到 realtime queue frontier。

## Step 15

显式验证 continuity。

## Step 16

Phase：

```text
CATCH_UP
→ LIVE
```

---

# 35. Recovery Range 必须 Calendar-aware

禁止简单：

```python
while timestamp < end:
    timestamp += timedelta(minutes=step)
```

跨越所有时间。

必须利用：

```text
TradingCalendar
BarType
```

识别：

```text
intraday session
lunch break
overnight
weekend
holiday
```

建议 recovery.py 中增加 pure helper：

```python
only_expected_closed_bar_boundaries(...)
```

或符合项目当前命名风格的 equivalent。

不要创建：

```text
CalendarRecoveryService
```

---

# 36. GAP Recovery Target

例如：

```text
confirmed = 09:31
trigger   = 09:35
```

Historical recovery 只负责：

```text
09:32
09:33
09:34
```

不要 recovery：

```text
09:35
```

09:35 应继续作为：

```text
buffered trigger
```

在 CATCH_UP 中处理。

这样避免两个 authority 同时拥有 trigger Bar。

---

# 37. STALE Recovery Target

例：

```text
last confirmed = 09:31
now            = 09:36:20
```

没有 post-gap trigger。

不能直接：

```text
recover until now
```

因为当前 Bar 可能尚未 closed。

必须使用项目当前已有的：

```text
Completed Bar Boundary Resolver
```

如果存在，例如：

```text
OnlyCompletedBarBoundaryResolver
```

以 current HEAD 为准。

Recovery target：

```text
latest fully completed Bar boundary
```

---

# 38. Historical Recovery 使用现有 Historical Port

优先复用：

```text
OnlyHistoricalDataSource.load_bars(...)
```

不要新增：

```text
recover_gap()
load_missing_bars()
load_recovery_bars()
```

DataSource 职责：

```text
give historical facts
```

Runtime 职责：

```text
why recover
what range
whether complete
when resume
```

---

# 39. Historical Recovery 必须 Strict Validation

至少验证：

```text
instrument identity

BarType

compatible DataVersion

closed Bars

Calendar validity

strict chronological order

expected coverage

no missing required interval
```

例如需要：

```text
09:32
09:33
09:34
```

provider 返回：

```text
09:32
09:34
```

必须：

```text
FAILED
```

禁止：

```text
skip 09:33
→ LIVE
```

---

# 40. Recovery Failure 必须 Fail Closed

第一版保持简单：

```text
one deterministic recovery attempt
```

如果：

```text
historical query fails

coverage incomplete

reconnect fails

auth fails

subscribe fails

replay fails

secondary continuity cannot be proven
```

则：

```text
Streaming Runtime
→ FAILED
```

不要实现：

```text
exponential backoff
jitter
retry manager
circuit breaker
infinite DEGRADED loop
```

这些属于 P6.7。

---

# 41. Recovery MarketData Sequence Normalization

必须认真处理：

```text
Historical provider sequence
Realtime sequence
Runtime sequence
LiveBarFinalizer sequence
set_live_sequence_floor()
```

核心原则：

```text
Provider raw sequence
!=
Runtime processing sequence authority
```

例：

Realtime 已经：

```text
sequence = 100
```

Historical provider 返回：

```text
1
2
3
```

不能导致：

```text
STALE
OUT_OF_ORDER
```

---

# 42. Provider sequence 只是 Evidence

Recovery normalization 可以保留 metadata：

```text
provider_sequence
recovery_generation
recovery_source=historical
```

但 Processor-visible normalized order 必须：

```text
monotonic
```

不要增加：

```text
RuntimeMode.SIM
```

作为 metadata semantic。

---

# 43. 不建立 Sequence Framework

不要创建：

```text
GlobalSequenceAuthority
RecoverySequenceManager
SequenceCoordinator
```

保持 current architecture。

P6.4 只要保证：

```text
Processor-visible recovery sequence
remains monotonic and deterministic
```

即可。

---

# 44. LiveBarFinalizer Recovery Boundary

重新审计：

```text
OnlyLiveBarFinalizer
```

当前可能持有：

```text
_pending
```

即：

```text
mutable, not-yet-closed realtime Bar
```

这不是 accepted Market Fact。

Recovery 开始时建议：

```python
def reset_pending(self) -> None:
    self._pending.clear()
```

不要 reset：

```text
accepted processed identities
historical watermarks
confirmed latest Bars
dedup accepted history
```

---

# 45. Existing Broker Order 在 Recovery 中必须继续推进

例：

```text
09:31
Order A ACCEPTED
```

然后：

```text
09:32~09:34 missing
```

恢复：

```text
09:32
```

必须正常：

```text
MarketDataProcessor
→ TradingFacade before_dispatch
→ Virtual Broker on_bar
→ Trade A
→ BrokerInboundQueue
→ ExecutionProcessor
→ Durable Transaction
→ Projection
```

禁止：

```python
if phase is RECOVERING:
    skip deterministic broker driver
```

---

# 46. Strategy 在 Recovery 中继续观察 Bar

Recovered Bars 仍要恢复：

```text
Indicator state

Factor state

Strategy rolling state
```

所以 Strategy pipeline 继续执行。

但是：

```text
Order submit permission
```

必须由 Runtime 拦截。

---

# 47. Trading Permission Matrix

最终明确冻结：

| Phase | Strategy receives Market Facts | Existing Broker order progression | New Strategy Order submit |
|---|---:|---:|---:|
| BOOTSTRAP | YES | according to current semantics | NO |
| CATCH_UP | YES | YES if normal path requires | NO |
| LIVE | YES | YES | YES |
| DEGRADED | no new untrusted fact processing / implementation-specific diagnostics | NO new untrusted progression | NO |
| RECOVERING | YES for recovered facts | YES | NO |
| STOPPING | NO new processing | NO | NO |

核心：

```text
RECOVERING:
existing Broker progression = YES
new Strategy submit = NO
```

---

# 48. Order Submission Interception

如果当前已有：

```text
ORDER_INTENT_SUPPRESSED_DURING_BOOTSTRAP

ORDER_INTENT_SUPPRESSED_DURING_CATCH_UP
```

增加：

```text
ORDER_INTENT_SUPPRESSED_DURING_DEGRADED

ORDER_INTENT_SUPPRESSED_DURING_RECOVERY
```

不要使用一个模糊：

```text
ORDER_BLOCKED
```

需要可诊断。

---

# 49. 不允许 Retroactive Strategy Order

测试必须明确：

```text
Recovered 09:33
→ Strategy BUY signal
```

结果：

```text
Strategy state advances

but:

canonical Order count unchanged
Reservation unchanged
Broker submit not called
external order id not created
```

直到：

```text
phase == LIVE
```

后的新 realtime Market Fact 才恢复正常 submit。

---

# 50. Startup CATCH_UP 与 Recovery CATCH_UP 必须复用

重新审计：

```text
_drain_catch_up()
```

如果已有：

```text
drain queue

sort

overlap filtering

finalizer

processor
```

那么现在已经有两个真实 use case：

```text
startup catch-up

recovery catch-up
```

此时可以合理抽：

```python
_process_buffered_updates(...)
```

或者当前命名风格 equivalent。

不要创建：

```text
CatchUpManager
RealtimeBufferCoordinator
```

---

# 51. Catch-Up 必须 Deterministic

保持 stable total order，例如：

```text
Bar/event timestamp
source sequence
update id
```

不要依赖：

```text
callback wall-clock arrival time

thread scheduling
```

---

# 52. Catch-Up 必须追到 Queue Frontier

禁止：

```text
drain once
→ process
→ LIVE
```

Recovery processing 过程中 realtime callback 仍然可能继续入 queue。

应该类似：

```python
while not stopping:
    batch = drain_current_queue()

    if not batch:
        break

    process(batch)
```

然后才：

```text
_verify_recovery_complete()
```

---

# 53. Catch-Up 再次发现 Gap

禁止递归：

```text
recover()
→ recover()
→ recover()
```

使用：

```text
recovery_generation
```

和循环式 orchestration。

例如：

```text
generation 1
→ recovery
→ catch-up
→ secondary gap
→ generation 2
→ recovery
```

保持 stack simple。

---

# 54. LIVE Resume 必须经过 Explicit Verification

实现一个清晰 private boundary，例如：

```text
_verify_recovery_complete()
```

至少验证：

```text
no active unresolved recovery plan

no known unexpected gap

historical range completed

buffered queue drained to current frontier

subscription active

source connection acceptable

worker healthy

not STOPPING

not FAILED
```

如果 Market OPEN：

```text
not currently stale
```

才允许：

```text
LIVE
```

---

# 55. STALE Detection 从 Passive Health 变成 Operational Trigger

如果当前 health 已经根据：

```text
last_received_at
last_closed_bar_end
next_expected_bar_end
stale_after_seconds
market session
```

计算：

```text
STALE
```

继续复用。

P6.4 不重新设计 stale semantics。

只增加：

```text
STALE observation
→ DEGRADED trigger
```

---

# 56. Worker Idle Callback

当前若：

```python
update = queue.get()

if update is None:
    continue
```

可增加：

```text
on_idle
```

但不要每 10ms 进行 heavyweight provider/recovery check。

可以使用：

```text
monotonic()
```

做 worker scheduling throttle，例如：

```text
≈ 1 second
```

注意：

```text
monotonic
```

只能用于 worker scheduling。

Market business time 仍使用：

```text
Runtime Clock
Market Session
```

---

# 57. Closed Market 不能误判为 STALE Recovery

如果：

```text
MarketSession != OPEN
```

例如：

```text
lunch
closed
overnight
```

没有 realtime callback：

```text
expected
```

此时应该：

```text
IDLE
```

不要：

```text
STALE
→ DEGRADED
→ RECOVERING
```

---

# 58. Connection Truth

重新审计当前：

```text
source.connection_snapshot()

source.health()

subscription_id
```

不要简单继续认为：

```text
subscription_id is not None
=
transport connected
```

P6.4 要建立尽可能正式的：

```text
connection truth
```

---

# 59. 不增加 Reconnect SPI Hierarchy

优先复用：

```text
connect()

authenticate()

disconnect()

connection_snapshot()

subscribe()

unsubscribe()
```

不要新增：

```text
ReconnectableDataSource

RecoverableMarketDataGateway

ReconnectService
```

除非 current Port 确实无法表达必要动作。

---

# 60. DataSource Capability 增加 Live Reconnect Contract

如果当前：

```python
OnlyDataSourceCapabilities
```

没有 realtime reconnect capability：

建议新增：

```python
live_reconnect: bool = False
```

保持直接。

不要创建：

```text
ReconnectCapability enum hierarchy
```

---

# 61. SIM P6.4 DataSource Contract

P6.4 后 SIM 正式要求：

```python
OnlyDataSourceCapabilities(
    historical_bars=True,
    live_bars=True,
    live_reconnect=True,
)
```

如果：

```text
historical=True
live=True
reconnect=False
```

SIM Factory：

```text
fail closed
```

推荐稳定错误：

```text
SIM_DATA_SOURCE_RECONNECT_CAPABILITY_REQUIRED
```

如果当前命名规范不同，遵循现有规范。

---

# 62. PAPER 不必强制新增这个 Requirement

不要因为：

```text
SIM P6.4
```

就让：

```text
PAPER
RESEARCH
BACKTEST
```

全部要求：

```text
live_reconnect=True
```

Requirement 应由 product contract 决定。

---

# 63. MiniQMT Reconnect Contract

重新审计：

```text
packages/provider/onlyalpha-plugin-miniqmt/
```

当前如果：

```text
connection_snapshot
```

只是通过 plugin lifecycle：

```text
RUNNING → READY
CONNECTED → CONNECTED
other → DISCONNECTED
```

推断 transport state，则 P6.4 需要加强。

---

# 64. MiniQMT 只负责 External Transport

MiniQMT 可以拥有：

```text
connection truth

connect/authenticate

subscribe/unsubscribe

historical fetch

callback normalization/publication
```

不能拥有：

```text
RecoveryPlan

StreamingPhase

Trading Permission

Recovery range calculation

Catch-up lifecycle

Strategy suppression

Virtual Broker recovery semantics
```

---

# 65. stop() != reconnect

如果当前 MiniQMT：

```text
stop()
```

会：

```text
shutdown_started = True

accepting_callbacks = False

unsubscribe all

resource lifecycle STOPPED
```

则禁止：

```text
stop()
start()
```

实现 transient reconnect。

因为：

```text
Resource shutdown
!=
Transport reconnect
```

---

# 66. Reconnect 推荐流程

Runtime：

```text
DEGRADED
```

然后：

```text
best-effort cleanup stale subscription
        ↓
inspect connection
        ↓
connect / reconnect
        ↓
authenticate
        ↓
subscribe
        ↓
RECOVERING
        ↓
historical repair
        ↓
CATCH_UP
        ↓
LIVE
```

是否需要先：

```text
disconnect()
```

根据 current provider contract 决定。

不要机械调用所有方法。

---

# 67. Reconnect Success 绝不能直接恢复 LIVE

必须再次冻结：

```text
connect success
+
subscribe success
```

只等于：

```text
future transport works
```

不等于：

```text
history complete
```

---

# 68. Recovery Failure 不是 Trading Cancel Command

如果 recovery 失败：

```text
Runtime → FAILED
```

禁止：

```text
auto cancel Accepted Orders

auto expire Orders

create synthetic Reject

create synthetic Terminal facts
```

因为：

```text
Runtime Recovery Failure
!=
Trading Command
```

---

# 69. Stop During Recovery

必须明确测试。

例如：

```text
phase = RECOVERING
historical provider blocked
```

用户：

```text
engine.stop()
```

必须立即：

```text
STOPPING
```

撤销：

```text
future processing permission
```

Historical result 之后即使返回：

```text
must not replay
must not advance Broker
must not dispatch Strategy
must not create Trade
must not create Transaction
```

---

# 70. 不要求复杂 I/O Cancellation

如果现有 Historical Port 不支持取消：

P6.4 不需要建立：

```text
cancellable async I/O framework
```

但返回后必须检查：

```text
STOPPING?
```

如果是：

```text
discard result
```

不能进入 business pipeline。

---

# 71. Health Diagnostics

建议在当前：

```text
OnlyStreamingRuntimeHealth
```

增加极少 read-only recovery 信息：

```text
recovery_generation

recovery_reason

recovery_started_at

recovery_from

recovery_to
```

也可根据项目现有 snapshot pattern 做等价设计。

不要暴露：

```text
mutable queue

Runtime object

Manager references

DataSource object
```

---

# 72. Operational Events

建议增加：

```text
STREAMING_DEGRADED

STREAMING_RECOVERY_STARTED

STREAMING_RECOVERY_COMPLETED

STREAMING_RECOVERY_FAILED
```

这些属于：

```text
Runtime operational facts
```

不是：

```text
Trading economic facts
```

禁止加入：

```text
RuntimeOperationKind.RECOVERY_STARTED
```

到 execution transaction store。

---

# 73. 推荐 Production Diff 范围

预计主要修改：

```text
src/onlyalpha/data/processor.py

src/onlyalpha/plugin/capabilities.py

src/onlyalpha/runtime/streaming/phase.py
src/onlyalpha/runtime/streaming/health.py
src/onlyalpha/runtime/streaming/recovery.py
src/onlyalpha/runtime/streaming/live_bar.py
src/onlyalpha/runtime/streaming/worker.py
src/onlyalpha/runtime/streaming/driver.py
src/onlyalpha/runtime/streaming/runtime.py

src/onlyalpha/runtime/sim/factory.py

packages/provider/onlyalpha-plugin-miniqmt/
```

可能少量：

```text
data models/enums
public exports
docs
tests
```

理想：

```text
Trading Kernel production diff = 0

TradingFacade economic diff = 0

Virtual Broker economic diff = 0
```

---

# 74. Architecture Gate：Recovery Module Boundary

新增类似：

```text
tests/architecture/test_streaming_recovery_boundary.py
```

冻结：

```text
runtime/streaming/recovery.py
```

不得 import：

```text
OrderManager

PositionManager

AccountManager

RiskManager / RiskService

ExecutionProcessor

TransactionCoordinator

FeeEngine

SettlementManager / SettlementAuthority

StrategyLedgerManager

RuntimeMode
```

Recovery module 只应依赖：

```text
MarketData model

Calendar

BarType

Timestamp

small streaming types
```

---

# 75. Architecture Gate：Unexpected Gap 不穿透 Processor

直接测试：

```text
Given UNEXPECTED_GAP
```

则：

```text
pipeline.process_bar not called

before_dispatch not called

Strategy dispatcher not called

after_dispatch not called
```

这是 P6.4 最重要行为 Gate。

---

# 76. Architecture Gate：RuntimeMode

继续保持 P6.1 contract：

```text
RuntimeMode
∉
Trading Economic Function
```

禁止：

```text
RuntimeMode.SIM
```

进入：

```text
Strategy Context

Market economic processing

Risk

Order

Position

Fee

Settlement

Account

Execution planning
```

---

# 77. Unit Test：Deduplicator Assess / Commit

测试：

```text
contains(update) == False

remember(update)

contains(update) == True
```

以及：

```text
post-gap rejected candidate

MUST NOT be remembered
```

---

# 78. Unit Test：SequenceTracker Assess / Commit

测试：

```text
commit sequence 100
```

然后：

```text
assess 104
```

得到：

```text
gap=True
```

但：

```text
accepted sequence still 100
```

然后：

```text
assess 101
```

必须仍然可以合法恢复。

---

# 79. Unit Test：GapDetector Assess / Commit

测试：

```text
commit 09:31
```

然后：

```text
assess 09:35
```

得到：

```text
UNEXPECTED_GAP
```

但：

```text
accepted last remains 09:31
```

随后：

```text
assess 09:32
```

应合法。

---

# 80. Unit Test：Calendar Recovery Coverage

至少覆盖：

```text
continuous intraday

lunch break

overnight

weekend

holiday if fixture supports

different BarType steps
```

Calendar logic 尽量集中 pure helper 测试。

---

# 81. Integration Test 1 — Gap Cannot Cross Trading Boundary

Given：

```text
processed:
09:30
09:31

incoming:
09:35
```

When：

```text
unexpected gap detected
```

Before recovery completes：

验证：

```text
Strategy dispatch count unchanged

Virtual Broker progression unchanged

Order count unchanged

Fill count unchanged

Position unchanged

No new durable transaction caused by 09:35
```

---

# 82. Integration Test 2 — Historical Recovery + Buffered Suffix Ordering

Historical source 返回：

```text
09:32
09:33
09:34
```

Realtime queue 已经有：

```text
09:35
09:36
```

最终 formal processing order：

```text
09:32
09:33
09:34
09:35
09:36
```

通过：

```text
formal MarketData audit / processing sequence
```

验证。

不要只用测试 helper list。

---

# 83. Integration Test 3 — Existing Accepted Order Progresses on Recovery Bar

Before gap：

```text
Order A = ACCEPTED
```

Recovered：

```text
09:32
```

应允许：

```text
Virtual Broker Trade A
```

验证：

```text
Broker Fact

ExecutionProcessor

Durable Transaction

projection_ready

Order state

Position

Allocation

Account

Fee

Settlement
```

---

# 84. Integration Test 4 — Recovery Strategy New Order Suppressed

Recovered：

```text
09:33
```

Strategy：

```text
BUY
```

验证：

```text
Strategy state may advance

but:

no new canonical Order
no Reservation
no Broker submit
no external order id
```

并有：

```text
ORDER_INTENT_SUPPRESSED_DURING_RECOVERY
```

---

# 85. Integration Test 5 — CATCH_UP 仍禁止新 Strategy Order

Phase：

```text
CATCH_UP
```

Strategy signal：

```text
suppressed
```

等：

```text
LIVE
```

后的第一根真正 realtime Bar：

```text
normal submit restored
```

---

# 86. Integration Test 6 — Expected Session Gap

例如：

```text
11:30
13:00
```

Calendar：

```text
EXPECTED_SESSION_GAP
```

验证：

```text
no DEGRADED

no RECOVERING

no historical repair

normal processing continues
```

---

# 87. Integration Test 7 — Incomplete Historical Recovery Fail Closed

Expected：

```text
09:32
09:33
09:34
```

Provider：

```text
09:32
09:34
```

结果：

```text
FAILED
```

且：

```text
09:35 never reaches Strategy
```

---

# 88. Integration Test 8 — Historical Overlap / Duplicate

Provider 返回宽范围：

```text
09:31
09:32
09:33
09:34
09:35
```

实际：

```text
09:31 already confirmed
09:35 realtime trigger
```

正确结果：

```text
09:31 ignored as overlap

09:32 processed once

09:33 processed once

09:34 processed once

09:35 processed once during catch-up
```

不得重复：

```text
Strategy dispatch

Virtual Broker progression

Trade

Transaction
```

---

# 89. Integration Test 9 — STALE → Reconnect → Recovery → LIVE

Fake DataSource：

```text
LIVE
↓
callbacks stop
↓
Runtime clock advances
↓
STALE
```

Runtime：

```text
LIVE
→ DEGRADED
→ reconnect
→ RECOVERING
→ historical repair
→ CATCH_UP
→ LIVE
```

期间：

```text
new Strategy trading permission = false
```

---

# 90. Integration Test 10 — Reconnect Failure

Fake provider：

```text
connect fails
```

或：

```text
authenticate fails
```

或：

```text
subscribe fails
```

验证：

```text
Runtime FAILED
```

禁止：

```text
silent LIVE

infinite retry

ambiguous permanent DEGRADED
```

---

# 91. Integration Test 11 — Stop During Recovery

Historical provider 人工 block。

等 Runtime：

```text
RECOVERING
```

然后：

```text
engine.stop()
```

再释放 provider。

验证：

```text
recovery result not replayed

no Broker progression

no Trade

no new transaction

Runtime reaches STOPPED
```

---

# 92. Integration Test 12 — Fault-Free vs Recovery Economic Equivalence

Run A：

```text
09:30
09:31
09:32
09:33
09:34
09:35
```

Run B：

```text
09:30
09:31
09:35 arrives
↓
recover 09:32
09:33
09:34
↓
catch-up 09:35
```

使用：

```text
pre-gap Accepted Order
```

比较最终经济 authority：

```text
Order

Trade

Position

Allocation

Account

Fee

Settlement
```

应该等价。

不要让测试依赖：

```text
new Strategy Orders during recovery
```

因为本阶段明确 suppress。

---

# 93. MiniQMT Contract Tests

P6.4 完成后验证：

```text
descriptor declares live_reconnect=True

connection snapshot reflects actual reconnect lifecycle

transient reconnect does not call resource stop()

resubscribe works after transient reconnect

historical data can be queried for recovery

stop() remains terminal resource shutdown

after terminal stop, new subscription still rejected
```

---

# 94. SIM Factory Tests

Case A：

```text
historical_bars=True
live_bars=True
live_reconnect=False
```

结果：

```text
validation failure
```

Case B：

```text
historical_bars=True
live_bars=True
live_reconnect=True
```

结果：

```text
valid
```

---

# 95. Backtest Regression

由于 P6.4 修改共享：

```text
Deduplicator
SequenceTracker
GapDetector
MarketDataProcessor
```

必须重点验证：

```text
deterministic replay

duplicate behavior

sequence behavior

gap flags

checkpoint codec

existing recovery tests

business fingerprint
```

如果 fingerprint 变化：

```text
DO NOT update golden first.
```

先找 root cause。

---

# 96. PAPER Regression

Existing PAPER tests 必须继续通过。

P6.4 不删除：

```text
PAPER

ShadowExecutionService
```

如果 PAPER 自然复用 shared streaming continuity，可以接受。

不要写：

```text
PaperRecoveryManager
```

第二套 implementation。

---

# 97. Virtual Broker Regression

全部 Virtual Broker tests 保持：

```text
NEXT_BAR

same-bar anti-lookahead

deterministic scheduler

multi-fill

terminal semantics
```

理想：

```text
Virtual Broker production diff = 0
```

---

# 98. 不要过度抽象

禁止：

```text
OnlyStreamingRecoveryManager

OnlyMarketContinuityManager

OnlyRecoveryCoordinator

OnlyReconnectManager

OnlyGapResolutionService

OnlyRecoveryPolicyEngine

OnlyStreamingStateMachineFramework
```

优先：

```text
small immutable dataclass

pure helper function

Runtime private method

existing Port

existing Queue

existing Worker
```

---

# 99. 推荐 Runtime Private Methods

实际名称按项目 style，可参考：

```python
_begin_recovery(...)

_build_recovery_plan(...)

_recover_market_continuity(...)

_load_recovery_bars(...)

_validate_recovery_bars(...)

_normalize_recovery_updates(...)

_replay_recovery_bars(...)

_process_buffered_updates(...)

_reconnect_source(...)

_verify_recovery_complete(...)

_fail_streaming_recovery(...)
```

每个方法：

```text
small
single responsibility
```

不要出现：

```text
_recover_everything()
```

数百行函数。

---

# 100. Concurrency Model

保持：

```text
DataSource callback
=
producer

MarketDataInboundQueue
=
boundary

Streaming Worker
=
sole MarketData semantic consumer
```

Recovery：

```text
same Worker
```

不要增加第二 consumer。

---

# 101. Queue Overflow

如果 Recovery 太慢：

```text
realtime queue overflow
```

遵循现有 formal queue policy。

如果连续性无法证明：

```text
fail closed
```

禁止：

```text
silently drop data
→ resume LIVE
```

---

# 102. Documentation

更新至少：

```text
docs/roadmap.md

docs/runtime.md

docs/architecture.md
```

必要时更新：

```text
ADR implementation status
```

不要重写历史 decision。

---

# 103. Roadmap 文档状态

只有当 P6.3 当前 final baseline same-SHA CI 全绿时：

```text
P6.3 — DONE / CERTIFIED
```

P6.4 完成并 final same-SHA CI 成功后：

```text
P6.4 — Realtime Market Continuity & Same-Process Recovery
DONE / CERTIFIED
```

明确写：

Implemented：

```text
unexpected-gap admission cutoff

DEGRADED / RECOVERING

historical repair

recovery replay

buffered realtime catch-up

STALE/disconnect recovery

same-process reconnect

continuity verification
```

Not implemented：

```text
streaming checkpoint

process restart

Real Broker reconciliation
```

---

# 104. P6.4 完成后的产品状态

## BACKTEST

```text
Historical
Event-driven
Virtual Broker
Finite
Operational
```

## SIM

```text
Realtime
Event-driven
Virtual Broker
Same-process gap/reconnect recovery
Operational
```

但仍：

```text
No streaming checkpoint

No new-process restart
```

## LIVE

```text
Not operational yet
```

---

# 105. 推荐实施顺序

严格建议：

```text
Phase 0
Re-audit HEAD
↓
P6.3 baseline certification

Phase A
Deduplicator assess/commit

Phase B
SequenceTracker assess/commit

Phase C
GapDetector assess/commit

Phase D
Processor unexpected-gap fail closed

Phase E
Processor architecture/unit tests

Phase F
DEGRADED / RECOVERING phase

Phase G
minimal recovery.py

Phase H
Gap Recovery Plan

Phase I
Historical Recovery query

Phase J
Strict coverage validation

Phase K
Recovery sequence normalization

Phase L
Replay through normal Processor

Phase M
Recovery order suppression

Phase N
Startup/Recovery catch-up reuse

Phase O
LiveBarFinalizer pending reset

Phase P
STALE operational trigger

Phase Q
Reconnect

Phase R
DataSource live_reconnect capability

Phase S
MiniQMT reconnect contract

Phase T
Health / diagnostics

Phase U
Integration vertical slices

Phase V
Architecture Gates

Phase W
Docs

Phase X
Full local validation

Phase Y
Remote same-SHA certification
```

---

# 106. Definition of Done

以下必须全部满足。

## Baseline

- [ ] Current HEAD re-audited.
- [ ] Starting SHA recorded.
- [ ] Current P6.3 status understood.
- [ ] P6.3 baseline same-SHA CI is green before final P6.4 certification.

## Phase Model

- [ ] `DEGRADED` exists.
- [ ] `RECOVERING` exists.
- [ ] `OnlyStreamingPhase` and `OnlyStreamingDataState` remain separate.
- [ ] Streaming Runtime remains phase transition authority.

## Continuity Assessment

- [ ] Dedup assessment no longer mutates accepted identity state.
- [ ] Sequence assessment no longer mutates accepted sequence.
- [ ] Gap assessment no longer mutates accepted Bar frontier.
- [ ] Rejected post-gap candidate does not advance accepted frontier.
- [ ] Assess and commit are explicit separate operations.

## Fail-Closed Gap Admission

- [ ] Unexpected gap returns before `MarketDataPipeline`.
- [ ] Unexpected gap does not call `before_dispatch`.
- [ ] Unexpected gap does not advance Virtual Broker.
- [ ] Unexpected gap does not reach Strategy.
- [ ] Unexpected gap does not create Order.
- [ ] Unexpected gap does not mutate Position.
- [ ] Expected session gap remains legal.
- [ ] Calendar remains expected-session-gap authority.

## Recovery Planning

- [ ] Runtime owns Recovery Plan.
- [ ] DataSource does not own recovery policy.
- [ ] Recovery starts from confirmed processed frontier.
- [ ] Recovery target derives from Bar/Calendar authority.
- [ ] Source sequence is not historical time-range authority.
- [ ] Gap-trigger recovery excludes the buffered trigger Bar.
- [ ] STALE recovery stops at latest completed Bar boundary.

## Historical Recovery

- [ ] Existing Historical DataSource Port is reused.
- [ ] No provider-specific `recover_gap()` Runtime API is added.
- [ ] Historical facts are strictly validated.
- [ ] Missing expected Bar fails closed.
- [ ] Wrong instrument fails closed.
- [ ] Wrong BarType fails closed.
- [ ] Invalid DataVersion fails closed.
- [ ] Open/unclosed Bar fails closed.
- [ ] Invalid calendar coverage fails closed.

## Sequence Normalization

- [ ] Provider raw historical sequence is not Processor ordering authority.
- [ ] Recovery update sequence is deterministic.
- [ ] Recovery update sequence is monotonic.
- [ ] Recovery Bars do not become stale merely because provider raw sequence restarts.
- [ ] Provider raw sequence may remain as metadata evidence.

## Recovery Replay

- [ ] Recovery Bars enter the same `OnlyMarketDataProcessor`.
- [ ] Recovery Bars enter the same MarketData Pipeline.
- [ ] Recovery Bars use existing TradingFacade Broker hooks.
- [ ] Existing Accepted Virtual Broker Order can progress during recovery.
- [ ] Recovery Trade enters `BrokerInboundQueue`.
- [ ] Recovery Trade enters `ExecutionProcessor`.
- [ ] Recovery Trade creates durable Transaction.
- [ ] Projection Ready semantics remain unchanged.

## Strategy Permission

- [ ] Strategy receives recovery Bars for state reconstruction.
- [ ] New Strategy Order submit is blocked during `DEGRADED`.
- [ ] New Strategy Order submit is blocked during `RECOVERING`.
- [ ] New Strategy Order submit remains blocked during `CATCH_UP`.
- [ ] Existing Broker Order progression remains allowed during Recovery.
- [ ] No retroactive new Broker Order is created.
- [ ] New Strategy order permission returns only after `LIVE`.

## Catch-Up

- [ ] Original gap trigger is preserved.
- [ ] Realtime suffix continues buffering during Recovery.
- [ ] Startup and Recovery Catch-Up reuse one deterministic algorithm where practical.
- [ ] Buffered updates use deterministic ordering.
- [ ] Overlap is removed.
- [ ] Duplicate facts are processed once.
- [ ] Queue is drained to current frontier.
- [ ] Secondary gap remains fail closed.
- [ ] Recovery recursion is avoided.
- [ ] Recovery generation is deterministic.

## LIVE Resume

- [ ] LIVE resume has explicit verification.
- [ ] No unresolved gap remains.
- [ ] Historical coverage is complete.
- [ ] Buffered suffix is reconciled.
- [ ] Source subscription is active.
- [ ] Worker is healthy.
- [ ] Runtime is not STOPPING.
- [ ] Open-market stream is not currently stale.
- [ ] Reconnect success alone never restores LIVE.

## STALE / Disconnect

- [ ] STALE can trigger DEGRADED.
- [ ] Closed market does not trigger false recovery.
- [ ] Disconnect can trigger DEGRADED.
- [ ] Connection truth is stronger than `subscription_id != None`.
- [ ] Existing connection/subscription Ports are reused.

## DataSource Capability

- [ ] `live_reconnect` or equivalent explicit capability exists.
- [ ] SIM requires reconnect capability.
- [ ] SIM rejects non-reconnect realtime DataSource.
- [ ] PAPER is not unnecessarily forced into the same product requirement.

## MiniQMT

- [ ] MiniQMT declares reconnect capability only after implementing it.
- [ ] MiniQMT transport connection truth is explicit.
- [ ] Transient reconnect does not use terminal resource `stop()`.
- [ ] MiniQMT can resubscribe after transient reconnect.
- [ ] Historical query remains available for recovery.
- [ ] MiniQMT does not own Runtime recovery policy.

## LiveBarFinalizer

- [ ] Untrusted pending mutable live Bar can be reset at recovery boundary.
- [ ] Confirmed history is not reset.
- [ ] Processed identities are not reset.
- [ ] Accepted dedup state is not reset.

## Failure

- [ ] Recovery failure moves Runtime to `FAILED`.
- [ ] Incomplete historical recovery fails closed.
- [ ] Reconnect failure fails closed.
- [ ] Recovery failure does not auto-cancel Order.
- [ ] Recovery failure creates no synthetic terminal Trading Facts.

## Stop

- [ ] Stop during Recovery moves Runtime toward `STOPPING`.
- [ ] Recovery does not hold processing lock around long blocking I/O.
- [ ] Historical result arriving after Stop is not replayed.
- [ ] No Broker progression after processing cutoff.
- [ ] No Strategy dispatch after processing cutoff.
- [ ] No Trade after processing cutoff.
- [ ] No new durable Trading Transaction after processing cutoff.

## Operational Boundary

- [ ] Recovery operational events are not Trading Transactions.
- [ ] Runtime recovery diagnostics are read-only.
- [ ] No economic Manager is introduced into `recovery.py`.

## Architecture Preservation

- [ ] Trading Kernel economic implementation unchanged.
- [ ] Strategy Context remains RuntimeMode-free.
- [ ] TradingFacade economic semantics unchanged.
- [ ] Virtual Broker economic implementation unchanged.
- [ ] No `RuntimeMode.SIM` economic branch.
- [ ] No second SIM Trading System.
- [ ] No Recovery Trading Kernel.

## Tests

- [ ] Dedup assess/commit tests green.
- [ ] Sequence assess/commit tests green.
- [ ] Gap assess/commit tests green.
- [ ] Calendar recovery tests green.
- [ ] Gap cannot cross Trading boundary integration green.
- [ ] Historical recovery ordering integration green.
- [ ] Existing Accepted Order recovery Trade green.
- [ ] Recovery Strategy new-order suppression green.
- [ ] Catch-Up order suppression green.
- [ ] Expected-session-gap green.
- [ ] Incomplete recovery fail-closed green.
- [ ] Historical overlap/dedup green.
- [ ] STALE → Reconnect → Recovery → LIVE green.
- [ ] Reconnect failure green.
- [ ] Stop-during-Recovery green.
- [ ] Fault-free/recovered economic equivalence green.
- [ ] MiniQMT reconnect contract green.
- [ ] SIM Factory reconnect capability tests green.
- [ ] Architecture Gates green.

## Regressions

- [ ] BACKTEST regression green.
- [ ] PAPER regression green.
- [ ] Existing execution recovery regression green.
- [ ] Existing Virtual Broker tests green.
- [ ] Existing P6.3 SIM tests green.

## Static / Build / CI

- [ ] Ruff check green.
- [ ] Ruff format check green.
- [ ] Core mypy green.
- [ ] All current package/plugin mypy lanes green.
- [ ] Workspace build green.
- [ ] `core-full` green.
- [ ] `recovery` green.
- [ ] `ashare` green.
- [ ] `miniqmt-contract` green.
- [ ] Any current additional required lanes green.
- [ ] Final remote `quality-gate` green.
- [ ] Final certification is same-SHA.

---

# 107. Local Verification

先读取：

```text
scripts/test_suite.py

.github/workflows/quality.yml
```

以 current HEAD 作为真正 source of truth。

预计至少执行：

```bash
uv run ruff check src tests examples packages scripts
```

```bash
uv run ruff format --check src tests examples packages scripts
```

```bash
uv run mypy src/onlyalpha
```

以及 current workflow 定义的所有 package/plugin mypy。

Build：

```bash
uv build --all-packages
```

Formal test lanes 以当前 `scripts/test_suite.py` 为准。

预计至少：

```bash
uv run python scripts/test_suite.py core-full
```

```bash
uv run python scripts/test_suite.py recovery
```

```bash
uv run python scripts/test_suite.py ashare
```

```bash
uv run python scripts/test_suite.py miniqmt-contract
```

如果当前仍定义：

```text
fast
integration
```

也必须运行。

---

# 108. Remote Same-SHA CI Certification

最终 push 后获取：

```text
final HEAD SHA
```

必须检查**同一个 SHA**对应的：

```text
static

build

core-full

recovery

ashare

miniqmt-contract

quality-gate
```

以及 current workflow 中任何其他 mandatory independent gate。

全部：

```text
success
```

才可以声明：

```text
P6.4 DONE / CERTIFIED
```

禁止：

```text
SHA A static passed
SHA B recovery passed
SHA C quality-gate passed
```

然后组合声称 P6.4 certified。

必须：

```text
SAME SHA
```

Nightly Exhaustive：

只有确实针对 final SHA 运行并成功后，才能声明 Nightly certified。

---

# 109. 禁止伪完成方案

以下方案明确禁止。

## 禁止 1

```text
Gap detected
→ Strategy already consumed Bar
→ repair later
```

## 禁止 2

```text
Gap detected
→ post-gap Bar already advanced Virtual Broker
```

## 禁止 3

```text
Reconnect success
→ LIVE
```

## 禁止 4

```text
Historical recovery
→ only update watermark
```

## 禁止 5

```text
Historical recovery
→ directly call VirtualBroker.on_bar()
```

## 禁止 6

```text
Historical recovery
→ bypass OnlyMarketDataProcessor
```

## 禁止 7

```text
Recovered historical Strategy signal
→ retroactively submit Broker Order
```

## 禁止 8

```text
source_sequence gap
→ directly convert to missing minute range
```

## 禁止 9

```text
DataSource owns Runtime Recovery Plan
```

## 禁止 10

```text
source.stop()
source.start()
```

作为 transient reconnect。

## 禁止 11

```text
RecoveryThread

ReconnectThread

Second MarketData consumer
```

## 禁止 12

Trading Kernel：

```python
if recovering:
```

## 禁止 13

Economic code：

```python
if RuntimeMode.SIM:
```

## 禁止 14

```text
Recovery failure
→ auto cancel orders
```

## 禁止 15

```text
sleep(...)
```

作为 correctness synchronization。

## 禁止 16

```text
Incomplete Historical Coverage
→ LIVE
```

## 禁止 17

```text
Reconnect failure
→ infinite retry
```

## 禁止 18

P6.4 内实现：

```text
Streaming checkpoint
Process restart
```

---

# 110. P6.4 最终 Architecture

正常路径：

```text
Realtime Market Fact
        ↓
Continuity Assessment
        ↓
CONTIGUOUS
        ↓
Commit Continuity State
        ↓
OnlyMarketDataProcessor
        ↓
MarketDataPipeline
        ↓
Virtual Broker
        ↓
Strategy
        ↓
Trading Kernel
```

Gap 路径：

```text
Post-Gap Realtime Fact
        ↓
Continuity Assessment
        ↓
UNEXPECTED GAP
        ↓
DO NOT COMMIT FRONTIER
        ↓
DO NOT ENTER PIPELINE
        ↓
DEGRADED
        ↓
RECOVERING
        ↓
Historical Missing Market Facts
        ↓
Normalized Recovery Updates
        ↓
Same OnlyMarketDataProcessor
        ↓
Same MarketDataPipeline
        ↓
Existing Broker Progression
        ↓
Strategy State Reconstruction
        │
        └── New Strategy Order Submit Suppressed
        ↓
CATCH_UP
        ↓
Original Trigger
+
Buffered Realtime Suffix
        ↓
Deterministic Reconciliation
        ↓
Continuity Verification
        ↓
LIVE
```

---

# 111. P6.4 永久公式

## Formula 1

```text
Unknown Market History
=
No Trading Permission
```

## Formula 2

```text
Detection
!=
Acceptance
```

## Formula 3

```text
Recovery
=
Missing Market Facts
→ Same Market Pipeline
→ Buffered Realtime Catch-Up
```

## Formula 4

```text
Transport Restored
!=
Trading Permission Restored
```

## Formula 5

```text
Recovery Market Fact
=
Normal Market Fact
```

同时：

```text
New Strategy Order Permission During Recovery
=
False
```

## Formula 6

```text
P6.4
=
Same-Process Forward Recovery
```

而：

```text
P6.5
=
New-Process Restart Recovery
```

---

# 112. 最终实现报告要求

任务完成后不要只输出：

```text
done
```

必须提供以下结构化报告。

## 112.1 Repository State

报告：

```text
starting SHA

final SHA

branch

working tree state
```

---

## 112.2 P6.3 Baseline Certification

说明：

```text
是否仍存在旧 projection_ready observation race

是否修复

如何修复

P6.3 certified baseline SHA

same-SHA CI results
```

---

## 112.3 Architecture Before

说明 P6.4 前：

```text
Gap detection existed

但 GAP_DETECTED update 是否仍可能进入 Pipeline

STALE 是否只是 passive health

connection truth 是否只依赖 subscription/lifecycle
```

---

## 112.4 Architecture After

说明：

```text
Assess / Commit separation

Unexpected Gap admission cutoff

DEGRADED

RECOVERING

Historical repair

Recovery replay

CATCH_UP

Reconnect

LIVE resume proof
```

---

## 112.5 Production Code Changes

逐文件列出：

```text
path

what changed

why
```

特别说明：

```text
Trading Kernel diff

TradingFacade diff

Virtual Broker diff
```

---

## 112.6 Continuity Authority

明确回答：

```text
What is Confirmed Market Frontier?

What can advance it?

What cannot advance it?

How is sequence gap used?

How is time gap used?

How is expected session gap distinguished?
```

---

## 112.7 Recovery Contract

明确：

```text
Recovery range calculation

Calendar treatment

Historical completeness

DataVersion validation

Sequence normalization

Replay path

Trigger preservation

Buffered suffix reconciliation
```

---

## 112.8 Trading Permission Matrix

明确每个 Phase：

```text
BOOTSTRAP
CATCH_UP
LIVE
DEGRADED
RECOVERING
STOPPING
```

是否允许：

```text
Strategy observation

Existing Broker progression

New Strategy Order submit
```

---

## 112.9 Reconnect Contract

明确：

```text
connection source of truth

reconnect lifecycle

subscription lifecycle

historical repair after reconnect

why reconnect success is not LIVE
```

---

## 112.10 Stop Safety

明确：

```text
Stop during Recovery

blocking provider result arriving late

no replay after cutoff

no Broker progression

no synthetic economic facts
```

---

## 112.11 Architecture Preservation

说明：

```text
Trading Kernel

TradingFacade

Virtual Broker

BACKTEST

PAPER

existing transaction/recovery semantics
```

如何保持。

---

## 112.12 Tests

列出：

```text
new tests

modified tests
```

并说明每个 test 冻结了什么 contract。

---

## 112.13 Local Verification

列出真实执行的：

```text
commands

results
```

不能只说：

```text
all tests pass
```

---

## 112.14 Remote CI

列出：

```text
final SHA

workflow run id

static

build

core-full

recovery

ashare

miniqmt-contract

quality-gate

other mandatory lanes
```

确认：

```text
same-SHA
```

---

## 112.15 Remaining P6 Scope

明确：

### P6.5

```text
Streaming Checkpoint + Restart
```

### P6.6

```text
Trading Semantic Conformance
```

### P6.7

```text
Operations / Soak
```

### P6.8

```text
Delete PAPER / SHADOW
```

---

# 113. 最终实现决策原则

如果遇到两个可行方案，优先选择：

```text
Existing Port

Existing MarketDataProcessor

Existing Queue

Single Market Semantic Consumer

Explicit Assess / Commit

Immutable Recovery Plan

Pure Calendar Helper

Runtime Ownership

Same Market Pipeline

Deterministic Ordering

Fail Closed

Small Private Methods
```

不要选择：

```text
New Framework

New Manager Hierarchy

New Background Worker

Second MarketData Consumer

Provider-Specific Runtime Semantics

RuntimeMode Economic Branch

Hidden Retry

Compatibility Alias

Parallel Recovery Trading Path
```

---

# 114. 最终代码复杂度要求

P6.4 的优秀实现应该表现为：

```text
small continuity semantic correction
+
clear Streaming Runtime recovery lifecycle
+
reuse Historical DataSource
+
reuse startup Catch-Up
+
reuse normal Market Pipeline
+
strong fail-closed tests
```

而不是：

```text
large generic recovery framework
```

如果最终 production diff 非常大：

必须重新检查是否把：

```text
Realtime Market Continuity
```

错误实现成了：

```text
第二套 Runtime Recovery System
```

---

# 115. 最终成功标准

P6.4 真正完成时，系统必须能够明确证明：

```text
1. 缺口后的 realtime Market Fact 不会提前进入 Trading Kernel。

2. 缺失事实可以通过 Historical DataSource 被恢复。

3. 恢复事实通过正常 Market Pipeline 被重新处理。

4. 故障前已有 Broker Order 可以按照恢复的 Market Facts 正确推进。

5. Recovery 期间不会 retroactively 创建新的 Strategy Broker Order。

6. Recovery 期间到达的 realtime suffix 被确定性缓存和追平。

7. Reconnect 只恢复 Transport，不直接恢复 Trading Permission。

8. 只有 continuity 被重新证明以后 Runtime 才恢复 LIVE。

9. Stop 在任何 recovery 阶段仍然拥有最高 processing cutoff authority。

10. 整个实现没有创造第二套 Trading Kernel、SIM economic path 或 Recovery trading framework。
```

最终核心验收公式：

```text
Unknown Market History
        ↓
Trading Permission Revoked
        ↓
Missing Facts Recovered
        ↓
Same Market Pipeline
        ↓
Buffered Realtime Catch-Up
        ↓
Continuity Proven
        ↓
LIVE
```