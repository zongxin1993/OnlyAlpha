你现在位于 OnlyAlpha 仓库根目录。

仓库：

```text
https://github.com/zongxin1993/OnlyAlpha
```

任务名称：

```text
PR5.1 Paper Read-Only Market Observation
```

本任务要为 OnlyAlpha 建立第一个正式的长生命周期实时运行模式：

```text
MiniQMT 实时行情
→ OnlyAlpha Streaming Runtime
→ MarketData Pipeline
→ Indicator
→ Factor
→ Strategy
→ Risk
→ Order Intent
→ Shadow Execution
→ Observation
```

本任务不是简单地写一个 MiniQMT 行情演示脚本，也不是绕过 OnlyEngine 直接调用 Indicator。

必须通过正式：

```text
OnlyEngine
→ Runtime Planner
→ Runtime Assembler
→ Paper Runtime
→ Cluster
→ Indicator / Factor / Strategy
```

形成产品纵切面。

---

# 一、开始前要求

必须先重新审计当前仓库，不得只根据本提示词假设代码结构。

重点阅读：

```text
AGENTS.md
README.md
docs/roadmap.md

src/onlyalpha/engine/
src/onlyalpha/runtime/
src/onlyalpha/runtime/backtest/
src/onlyalpha/runtime/paper/
src/onlyalpha/runtime/live/
src/onlyalpha/runtime/defaults.py
src/onlyalpha/runtime/runtime.py

src/onlyalpha/data/
src/onlyalpha/market_data/
src/onlyalpha/cluster/
src/onlyalpha/indicator/
src/onlyalpha/factor/
src/onlyalpha/strategy/
src/onlyalpha/risk/
src/onlyalpha/order/
src/onlyalpha/execution/

packages/provider/onlyalpha-plugin-miniqmt/
```

确认当前真实状态：

```text
OnlyPaperRuntimeFactory 是否仍为 Unsupported
OnlyLiveRuntimeFactory 是否存在
OnlyRuntimeServices.clock 的实际类型
MiniQMT 实时订阅和 callback 结构
MarketData inbound queue 和 processor 的正式入口
Cluster Pipeline 的调用顺序
Order Service 与 Broker Gateway 的边界
Risk Reservation 的创建与释放路径
OnlyEngine.run / initialize / start / stop 的生命周期语义
现有 Config Model 和 YAML Schema
```

事实来源优先级：

```text
1. 当前源码
2. 当前测试
3. 当前 ADR
4. AGENTS.md
5. README / Roadmap
6. 本提示词
```

如本提示词中的路径或类名与当前源码不一致，应保持架构目标不变，并按当前实现调整。

---

# 二、模式语义必须先冻结

OnlyAlpha 的四种运行语义应定义为：

```text
BACKTEST
历史行情 + Virtual Broker
有限运行
产生虚拟成交和经济状态

SIMULATION
实时行情 + Virtual Broker
长生命周期
产生虚拟成交和经济状态

PAPER
实时行情 + Shadow Execution
长生命周期
Risk 和 Order Intent 正常执行
不向 Broker 提交
不产生 Fill
不改变 Account / Position / Fee / Settlement

LIVE
实时行情 + Real Broker
长生命周期
产生真实 Broker Order 和真实经济影响
```

PR5.1 只实现：

```text
PAPER
```

但必须建立能够被未来 `SIMULATION` 和 `LIVE` 复用的共享架构。

不得将 Paper 实现为：

```text
禁止调用 Risk
禁止创建 Order
静默忽略 Strategy Order
返回伪造 Broker Accepted
返回伪造 Fill
直接修改 Position
```

正确的 Paper 语义是：

```text
Strategy Order Intent
→ Risk Evaluation
→ Reservation Evaluation
→ Order 创建
→ WOULD_SUBMIT
→ Shadow Execution Suppress
→ Reservation 释放
→ Shadow Terminal
```

---

# 三、核心架构决策

## 1. Paper 和 Live 共用 Streaming Runtime

不得分别实现两套重复的：

```text
OnlyPaperRuntime 业务循环
OnlyLiveRuntime 业务循环
```

应建立共享的长生命周期运行内核，例如：

```text
src/onlyalpha/runtime/streaming/
```

推荐结构：

```text
src/onlyalpha/runtime/streaming/
├── __init__.py
├── config.py
├── runtime.py
├── worker.py
├── bootstrap.py
├── live_bar.py
├── observation.py
├── health.py
└── execution.py
```

Paper 与未来 Live Factory 只负责注入能力差异：

```text
Paper Factory
├── OnlyLiveClock
├── MiniQMT Live DataSource
├── Shadow Execution Port
└── No Broker Gateway

Live Factory
├── OnlyLiveClock
├── MiniQMT Live DataSource
├── Live Execution Port
└── MiniQMT Broker Gateway
```

未来 Simulation 应能复用同一个 Streaming Runtime：

```text
Simulation Factory
├── OnlyLiveClock
├── Live DataSource
├── Simulated Execution Port
└── Virtual Broker
```

---

## 2. Runtime Mode 与 Execution Capability 分离

新增明确执行能力模型。

建议：

```python
class OnlyExecutionCapability(StrEnum):
    SHADOW = "SHADOW"
    SIMULATED = "SIMULATED"
    LIVE = "LIVE"
```

映射：

```text
PAPER      → SHADOW
BACKTEST   → SIMULATED
SIMULATION → SIMULATED
LIVE       → LIVE
```

PR5.1 暂不要求实现完整 `SIMULATION` Runtime，但架构不得阻止未来加入。

禁止在 Indicator、Factor、Strategy、Risk、Order Manager 中散布：

```python
if runtime_type == "PAPER":
    ...
```

模式差异只能存在于：

```text
Composition Root
Runtime Factory
Execution Submission Port
Account Authority Adapter
Broker Adapter
```

---

# 四、同一个 Strategy 必须跨模式复用

同一 Strategy 代码在 Paper 和 Live 中必须一致：

```python
def on_bar(self, context):
    if self.should_buy(context):
        self.ctx.order.buy(...)
```

Strategy 不应知道：

```text
当前是 Paper
当前是 Live
当前是否存在 MiniQMT Broker
```

运行模式通过 Context 内注入的正式 Port 决定。

完整调用链：

```text
Strategy
→ Order API
→ Risk
→ Order Service
→ Execution Submission Port
```

执行出口：

```text
Paper      → Shadow Execution Port
Simulation → Virtual Broker
Live       → Real Broker
```

必须增加兼容性测试，证明相同 Strategy、Factor、Indicator 和参数可以装入：

```text
BACKTEST
PAPER
```

后续能够装入：

```text
SIMULATION
LIVE
```

---

# 五、Paper 的 Shadow Execution 语义

## 1. Risk 正常执行

Paper 中必须执行：

```text
Mandatory Risk Rules
Runtime Risk Rules
Cluster Risk Profile
Market Rules
Account Permission
Instrument Permission
Max Notional
Position Availability
Cash Availability
Risk Audit
```

若 Risk 拒绝：

```text
Order 不进入 Shadow Execution
返回正式 Risk Rejection
保留审计事实
```

若 Risk 接受：

```text
进入 Order Intent 和 Shadow Execution
```

---

## 2. Order 正常创建

Paper 应保留正式 Order Identity 和状态流。

建议状态过程：

```text
CREATED
→ RISK_ACCEPTED
→ WOULD_SUBMIT
→ SHADOW_TERMINAL
```

或在当前状态机不适合扩展时，通过正式 Terminal Reason 表达：

```text
Order Status    : TERMINAL
Terminal Reason : EXECUTION_SUPPRESSED_BY_RUNTIME
```

禁止把 Paper Order 标记为：

```text
BROKER_ACCEPTED
PARTIALLY_FILLED
FILLED
```

因为没有 Broker 事实。

---

## 3. Shadow Execution Port

新增正式 Port，例如：

```python
class OnlyExecutionSubmissionPort(Protocol):
    def submit(
        self,
        order: OnlyOrderSnapshot,
        timestamp: OnlyTimestamp,
    ) -> OnlyExecutionSubmissionResult:
        ...
```

结果模型示例：

```python
class OnlyExecutionSubmissionOutcome(StrEnum):
    SUBMITTED = "SUBMITTED"
    SUPPRESSED = "SUPPRESSED"
    REJECTED = "REJECTED"
```

Paper 实现：

```python
class OnlyShadowExecutionSubmissionPort:
    def submit(
        self,
        order: OnlyOrderSnapshot,
        timestamp: OnlyTimestamp,
    ) -> OnlyExecutionSubmissionResult:
        return OnlyExecutionSubmissionResult(
            outcome=OnlyExecutionSubmissionOutcome.SUPPRESSED,
            reason_code="PAPER_RUNTIME",
            external_order_id=None,
        )
```

Paper 的 Shadow Port 不得：

```text
调用 MiniQMT Trader
写 Broker Inbound Queue
产生 Broker Update
产生 Trade Execution
调用 ExecutionProcessor
调用 Trade Planner
调用 Commit Coordinator
修改 Position
修改 Account
产生 Fee
产生 Settlement
```

---

## 4. Reservation 生命周期

Paper 中 Risk 和 Order Reservation 可以正常计算和创建，但 Shadow Suppression 后必须立即释放。

流程：

```text
Risk Accept
→ Cash / Position / Risk Reservation
→ Order Created
→ Shadow Suppressed
→ Release Reservations
```

新增释放原因，例如：

```text
EXECUTION_SUPPRESSED
```

禁止让 Paper Order 长期占用：

```text
Cash Reservation
Position Reservation
Risk Active Order Count
Strategy Capital Reservation
```

否则因为 Paper 没有成交，后续 Order 会被错误拒绝。

---

## 5. Shadow Order 去重

Paper 不产生 Position 变化，因此以下 Strategy 可能每根 Bar 重复下单：

```python
if position.quantity == 0:
    buy()
```

不能通过伪造 Position 解决。

应保留真实语义：

```text
Position 不变
Account 不变
```

同时增加 Shadow Intent 可查询状态：

```text
当前是否已存在相同 Active Shadow Intent
最近一次 Shadow Intent
Shadow Intent Terminal Reason
```

可复用现有活动订单查询语义。

若完全相同的 Intent 在同一业务窗口重复产生，可返回：

```text
DUPLICATE_ACTIVE_SHADOW_ORDER
```

不要创建虚拟持仓。

---

# 六、共享 Streaming Runtime

## 1. Clock 泛化

检查当前：

```python
OnlyRuntimeServices.clock
```

如果仍写死为：

```python
OnlyBacktestClock
```

应泛化为：

```python
OnlyClock
```

约束：

```text
Backtest Runtime
→ 持有 OnlyBacktestClock
→ 唯一拥有 advance_to / advance_by 权限

Streaming Runtime
→ 持有 OnlyLiveClock
→ 不允许手工推进时间

Cluster
→ 只获得 OnlyClockView
```

不能为了 Paper 修改 Backtest 时间语义。

---

## 2. `OnlyStreamingRuntime`

建议：

```python
class OnlyStreamingRuntime(OnlyRuntime):
    def initialize(self) -> None: ...
    def start(self) -> None: ...
    def wait(self) -> None: ...
    def stop(self) -> None: ...
    def close(self) -> None: ...
```

持有：

```text
OnlyLiveClock
OnlyEventBus
OnlyMarketDataInboundQueue
OnlyMarketDataProcessor
OnlyMarketDataPipeline
OnlyClusterManager
OnlyDataSource
OnlyStreamingMarketDataWorker
OnlyObservationPublisher
OnlyExecutionSubmissionPort
OnlyExecutionCapability
```

不直接依赖：

```text
MiniQMT SDK 类型
MACD 具体实现
Console 实现
JSONL 实现
```

---

# 七、Paper Runtime 生命周期

推荐状态：

```text
CREATED
INITIALIZING
BOOTSTRAPPING
SUBSCRIBING
RUNNING
DEGRADED
STOPPING
STOPPED
FAILED
CLOSED
```

## Initialize

```text
创建 LiveClock
创建 EventBus
创建 MarketData Queue
创建 Processor / Pipeline
创建 Cluster
创建 Observation Publisher
创建 MiniQMT DataSource
绑定 market_data_sink
注入 Shadow Execution Port
初始化 Cluster
```

此阶段不连接 MiniQMT。

## Start

```text
DataSource.initialize()
→ connect()
→ authenticate()
→ start()
→ Historical Warmup
→ Live Subscribe
→ 启动 MarketData Worker
→ 启动 Cluster
→ Runtime RUNNING
```

## Wait

长生命周期阻塞，直到：

```text
Ctrl+C
外部 stop()
DataSource 致命错误
Worker 致命错误
```

## Stop

严格逆序：

```text
停止新订阅
→ unsubscribe
→ 停止接收新 Callback
→ Drain Queue
→ 停止 Worker
→ Cluster.stop()
→ DataSource.stop()
→ Observation Publisher.stop()
→ EventBus.close()
→ LiveClock.close()
```

要求：

```text
幂等
无线程泄漏
无残留订阅
无未关闭文件
无 Callback 在关闭后继续写队列
```

---

# 八、Engine 生命周期调整

当前 `OnlyEngine.run()` 主要服务有限运行的 Backtest，并在结束后自动停止、生成 Artifact 和 Report。

不要让 `run()` 同时承担无限期实时运行语义。

推荐保留：

```text
run()
→ 有限运行
→ Backtest
```

为长生命周期模式正式支持：

```python
engine.initialize()
engine.start()
engine.wait()
engine.stop()
```

或提供应用层方法：

```python
engine.serve()
```

但不得形成第二个绕过 `OnlyEngine` 的启动入口。

推荐 CLI：

```text
onlyalpha run config.yaml
```

根据 Runtime Plan：

```text
BACKTEST
→ engine.run()

PAPER / LIVE / SIMULATION
→ initialize()
→ start()
→ wait()
→ stop()
```

实际分支应位于应用服务层，不要散布在 Runtime 内部。

---

# 九、MiniQMT 实时行情

当前 MiniQMT DataSource 已具备：

```text
连接
订阅 Bar
订阅 Quote
取消订阅
历史 Bar 查询
market_data_sink
```

PR5.1 应复用现有 Adapter，不重写一套 MiniQMT Runtime。

Callback 路径必须是：

```text
XtQuant Callback Thread
→ MiniQMT Normalizer
→ Runtime market_data_sink
→ Bounded Inbound Queue
→ 立即返回
```

Callback Thread 禁止：

```text
执行 Indicator
执行 Factor
调用 Strategy
调用 Risk
创建 Order
打印终端
写 JSONL
等待业务锁
调用 Broker
```

---

# 十、MarketData Worker

每个 Runtime 一个单线程消费者。

示例：

```python
class OnlyStreamingMarketDataWorker:
    def run(self) -> None:
        while not self._stop_event.is_set():
            update = self._queue.take(timeout=0.5)
            self._process(update)
```

处理顺序：

```text
Scope Validation
→ Sequence Validation
→ Deduplication
→ Gap Detection
→ Timestamp Validation
→ Live Bar Finalization
→ MarketData Pipeline
→ Cluster Dispatch
→ Indicator
→ Factor
→ Strategy
→ Risk / Order Intent
→ Observation Projection
→ Event Drain
```

禁止：

```text
每个证券一个业务线程
每个 Cluster 一个数据线程
并发调用同一 Cluster
Indicator 并发写状态
```

Paper 和未来 Live 必须使用相同处理顺序。

---

# 十一、实时 Bar Finalization

当前 MiniQMT 实时周期 Bar 可能在同一时间桶内多次更新。

不能将每次 Callback 都当成最终 Closed Bar，否则会导致：

```text
MACD 重复更新
Factor 重复执行
Strategy 重复下单
```

实现：

```text
OnlyLiveBarFinalizer
```

状态键：

```text
source_id
instrument_id
bar_type
bar_start
```

行为：

```text
收到 T 桶第一条
→ 保存 Pending，不分发

收到 T 桶后续更新
→ Replace Pending，不分发

收到 T+1 桶
→ Finalize T
→ T 只进入一次 Pipeline
→ 保存 T+1

收到旧于 Pending 的桶
→ 审计并按 Fail Closed 策略处理
```

MiniQMT Normalizer 对未确认周期 Bar 应输出：

```text
is_closed = false
```

由 Finalizer 产生：

```text
is_closed = true
```

停止时不能无条件把当前未完成 Bar 伪装成 Closed。

---

# 十二、Historical Warmup 与实时衔接

必须支持指标启动预热。

流程：

```text
汇总 Indicator 最大 Warmup Requirement
→ MiniQMT 查询最近 N 根已闭合 Bar
→ 按时间顺序进入正式 Pipeline
→ Indicator / Factor Warmup
→ 记录历史 Watermark
→ 创建实时订阅
→ 处理历史/实时重叠
→ 进入 LIVE 阶段
```

阶段：

```text
BOOTSTRAP
CATCH_UP
LIVE
```

BOOTSTRAP：

```text
更新 Indicator
更新 Factor
Strategy 可以运行但执行仍为 Shadow
默认不发布正式实时 Observation
```

CATCH_UP：

```text
bar_end <= bootstrap_watermark
→ 丢弃重复 Bar
```

LIVE：

```text
每根新的 Closed Bar
→ 一次 Pipeline
→ 一次 Observation
```

Warmup 数量不能在 Runtime 中硬编码 MACD 参数，应从 Indicator Registry 或配置中汇总。

---

# 十三、Indicator / Factor / Strategy 复用

禁止新增：

```text
PaperIndicatorPipeline
PaperFactor
PaperStrategy
```

必须复用：

```text
OnlyIndicatorRegistry
OnlyFactorRegistry
OnlyClusterPipeline
OnlyStrategy
```

Cluster 的执行顺序保持：

```text
Indicator
→ Factor
→ Strategy
```

Paper 只增加执行能力和观察投影，不修改指标计算逻辑。

---

# 十四、Observation 模型

新增通用实时观察模型，例如：

```python
@dataclass(frozen=True, slots=True)
class OnlyMarketObservationSnapshot:
    runtime_id: OnlyRuntimeId
    cluster_id: OnlyClusterId
    instrument_id: OnlyInstrumentId
    bar_type: OnlyBarType

    phase: OnlyObservationPhase
    execution_capability: OnlyExecutionCapability

    source_id: OnlyMarketDataSourceId
    source_sequence: int

    bar_start: OnlyTimestamp
    bar_end: OnlyTimestamp
    received_at: OnlyTimestamp

    close_price: Decimal
    volume: Decimal

    indicator_snapshots: tuple[Mapping[str, object], ...]
    factor_snapshots: tuple[Mapping[str, object], ...]

    order_intents: tuple[Mapping[str, object], ...]

    warmup_ready: bool
    market_data_lag_ms: int
    stale: bool
```

Indicator 输出必须使用统一：

```python
snapshot.to_dict()
```

Observation 层不得依赖具体：

```python
OnlyMacdSnapshot
```

---

# 十五、Observation Publisher

定义：

```python
class OnlyObservationSink(Protocol):
    def publish(self, snapshot: OnlyMarketObservationSnapshot) -> None:
        ...
```

实现：

```text
OnlyConsoleObservationSink
OnlyJsonLinesObservationSink
OnlyCompositeObservationSink
```

必须使用独立有界队列。

显示层过慢时：

```text
不阻塞 MarketData Worker
允许丢弃旧 Observation
保留最新 Snapshot
增加 observation_drop_count
```

首期终端输出示例：

```text
Runtime    : paper-miniqmt
Mode       : PAPER
Execution  : SHADOW
Source     : miniqmt
State      : RUNNING
Symbol     : 600000.XSHG
Bar        : 1m
Time       : 2026-08-03 09:42:00+08:00
Close      : 10.37
Volume     : 183400
Lag        : 126 ms

MACD
Samples    : 52
Ready      : true
DIF        : 0.023184
DEA        : 0.017502
Histogram  : 0.011364
Cross      : GOLDEN_CROSS

Orders
Risk       : ACCEPT
Intent     : WOULD_SUBMIT
Execution  : SUPPRESSED
```

---

# 十六、Health 模型

新增：

```python
@dataclass(frozen=True, slots=True)
class OnlyStreamingRuntimeHealth:
    runtime_state: str
    source_state: str
    execution_capability: OnlyExecutionCapability

    inbound_queue_size: int
    observation_queue_size: int

    last_update_at: OnlyTimestamp | None
    last_closed_bar_at: OnlyTimestamp | None

    market_data_lag_ms: int | None

    sequence_gap_count: int
    duplicate_count: int
    stale_count: int
    observation_drop_count: int
    shadow_order_count: int
    shadow_rejection_count: int

    subscription_count: int
    worker_alive: bool
```

进入 `DEGRADED` 的条件：

```text
行情源断开
长时间无行情
Sequence Gap
Inbound Queue 接近容量
Worker 异常
持续 Observation Drop
```

PR5.1 可实现有限重连：

```text
断开
→ DEGRADED
→ 有界重试
→ 重新订阅
→ CATCH_UP
→ RUNNING
```

不能因为重连重复处理已完成 Bar。

---

# 十七、配置

不修改：

```yaml
schema_version: "1.0"
```

使用当前 Runtime Extension：

```yaml
runtime:
  type: PAPER

  extensions:
    execution_capability: SHADOW

    streaming:
      bootstrap_bars: auto
      inbound_queue_capacity: 4096
      stale_after_seconds: 10
      reconnect_enabled: true
      reconnect_max_attempts: 5

    observation:
      console: true
      jsonl: true
      jsonl_path: observations/paper-macd.jsonl
      queue_capacity: 1024
```

MiniQMT：

```yaml
data_sources:
  - source_id: miniqmt-live
    plugin_id: miniqmt
    data_version: miniqmt-live

    extensions:
      userdata_mini_path: "C:/..."
      cache_policy: prefer_cache
```

Paper Shadow 模式应允许：

```yaml
accounts: []
brokers: []
```

或者在当前 Config 强制要求 Account 时，提供明确的只读 Shadow Account Config，但不能伪装成 Broker Account。

校验规则应是：

```text
BACKTEST
→ 要求 Simulated Broker
→ 要求 Account

PAPER + SHADOW
→ 禁止 Real Broker
→ 不要求 Broker Account

SIMULATION
→ 要求 Virtual Broker
→ 要求 Virtual Account

LIVE
→ 要求 Real Broker
→ 要求 Real Account
```

不得通过修改 Schema Version 实现。

---

# 十八、建议文件改动

新增：

```text
src/onlyalpha/runtime/streaming/__init__.py
src/onlyalpha/runtime/streaming/config.py
src/onlyalpha/runtime/streaming/runtime.py
src/onlyalpha/runtime/streaming/worker.py
src/onlyalpha/runtime/streaming/bootstrap.py
src/onlyalpha/runtime/streaming/live_bar.py
src/onlyalpha/runtime/streaming/execution.py
src/onlyalpha/runtime/streaming/observation.py
src/onlyalpha/runtime/streaming/health.py

src/onlyalpha/observation/__init__.py
src/onlyalpha/observation/models.py
src/onlyalpha/observation/ports.py
src/onlyalpha/observation/console.py
src/onlyalpha/observation/jsonl.py
```

修改：

```text
src/onlyalpha/runtime/paper/factory.py
src/onlyalpha/runtime/defaults.py
src/onlyalpha/runtime/runtime.py
src/onlyalpha/runtime/factory.py
src/onlyalpha/engine/engine.py
src/onlyalpha/config/document.py
src/onlyalpha/config/models.py

src/onlyalpha/order/
src/onlyalpha/risk/
src/onlyalpha/execution/

packages/provider/onlyalpha-plugin-miniqmt/
  data_source/live.py
  data_source/resource.py
```

示例：

```text
examples/configs/miniqmt_paper_macd.yaml
examples/strategy/observation/
```

实际路径应以审计后的当前仓库为准。

---

# 十九、测试要求

## Unit

覆盖：

```text
Execution Capability 映射
Shadow Submit 返回 SUPPRESSED
Risk Rejected 不进入 Shadow Port
Risk Accepted 进入 WOULD_SUBMIT
Shadow 后 Reservation 释放
Shadow Order 不产生 Fill
Shadow Order 不改变 Position
Shadow Order 不改变 Account
Shadow Order 不产生 Fee
Shadow Order 不产生 Settlement

Live Bar 同桶 Replace
下一桶 Finalize
乱序 Bar 处理
未完成最后 Bar 不伪造 Closed
Bootstrap Watermark
历史/实时重叠去重
Observation Serialization
Observation Drop
Stale Detection
Graceful Stop
```

## Contract

使用 Fake XtData：

```text
MiniQMT connect
subscribe_quote
Bar callback
Quote callback
unsubscribe
重复 callback
空 callback
异常 callback
subscribe 失败
disconnect
reconnect
```

Fake XtData 必须保持 XtQuant 原始数据形状，不能直接返回 OnlyAlpha Domain Object。

## Integration

正式纵切面：

```text
OnlyEngine
→ Paper Factory
→ Streaming Runtime
→ Fake MiniQMT
→ Historical Warmup
→ Live Bar
→ MACD
→ Strategy
→ Risk
→ Order Intent
→ Shadow Suppress
→ Observation
```

断言：

```text
OnlyPaperRuntimeFactory 不再 Unsupported
正式 OnlyEngine 可以 initialize/start/wait/stop
指标经过正式 Cluster Pipeline
每根 Closed Bar 只处理一次
MACD Samples 不重复
相同 Strategy 可以同时装入 Backtest 和 Paper
Risk 正常执行
Order 正常创建
Execution Outcome 为 SUPPRESSED
没有 Broker Gateway
没有 Broker Update
没有 Trade Transaction
没有 Fill
Account 不变
Position 不变
Ledger 不变
Fee 不变
Settlement 不变
Reservation 已释放
停止后无残留线程
停止后无残留 MiniQMT Subscription
```

## Architecture

禁止：

```text
Paper 专用 Strategy
Paper 专用 Indicator
Paper 专用 Factor Pipeline
MiniQMT Callback 直接调用 Strategy
MiniQMT Callback 直接调用 Risk
MiniQMT Callback 直接打印
Paper 直接修改 Position
Paper 直接修改 Account
Paper 产生伪 Broker Accepted
Paper 产生伪 Fill
生产代码出现 test_mode
runtime_type 判断散布在 Manager 内
```

## MiniQMT Local

Windows 本地：

```text
真实 MiniQMT
600000.XSHG
1m
Historical Warmup
Live Subscription
连续观察至少 5 根 Closed Bar
MACD 输出
策略产生至少一个可控 Order Intent
Risk 正常评估
Execution 显示 SUPPRESSED
账户和持仓不发生变化
Ctrl+C
取消订阅
正常退出
```

不要求连接 MiniQMT Trader，不要求 Account ID。

---

# 二十、兼容性要求

必须保证：

```text
Backtest Clock 行为不变
Backtest Virtual Broker 行为不变
Backtest Order/Execution 行为不变
现有 Durable Transaction 不变
现有 Recovery 不变
现有 Result Fingerprint 不变
现有 MiniQMT Historical 不变
现有 MiniQMT Broker 不被 Paper 调用
```

运行：

```text
Fast
Integration
MiniQMT Contract
A-share
Recovery
Full Offline
Release
```

不得通过跳过现有测试完成 PR。

---

# 二十一、明确非目标

PR5.1 不实现：

```text
完整 Simulation Runtime
Virtual Broker 实时仿真
真实 MiniQMT Broker 下单
Broker Account 同步
真实 Position 同步
Paper 虚拟持仓
Paper 虚拟现金
Paper PnL
Paper Fee
Paper Settlement
A 股完整涨跌停闭环
A 股停牌历史
A 股 Reference Authority
Checkpoint/Restart
Web/SSE
Tick-to-Bar
多进程
YAML Schema 2.0
```

但是架构不得妨碍这些能力后续加入。

---

# 二十二、完成标准

只有以下全部满足，才能声明 PR5.1 完成：

1. Paper 不再是 Unsupported Runtime；
2. Paper 使用共享 Streaming Runtime；
3. 架构可被未来 Live 和 Simulation 复用；
4. Runtime 公共 Clock 类型不再写死 Backtest；
5. Paper 使用 OnlyLiveClock；
6. MiniQMT Callback 只标准化并入队；
7. Runtime 单线程处理实时业务；
8. Historical Warmup 使用正式 Pipeline；
9. 历史/实时边界不重复；
10. 实时同桶 Bar 不重复更新指标；
11. 同一 Strategy 在 Backtest/Paper 中无需修改；
12. Risk 在 Paper 中正常执行；
13. Order Intent 在 Paper 中正常创建；
14. 合法订单进入 WOULD_SUBMIT；
15. Shadow Execution 返回 SUPPRESSED；
16. 不创建真实 Broker Gateway；
17. 不产生 Broker Accepted；
18. 不产生 Fill；
19. 不产生 Trade Transaction；
20. 不修改 Position；
21. 不修改 Account；
22. 不产生 Fee；
23. 不产生 Settlement；
24. Shadow 完成后 Reservation 全部释放；
25. Observation 显示 Indicator、Factor 和 Shadow Order；
26. Console/JSONL 不阻塞行情 Worker；
27. Ctrl+C 可以安全退出；
28. 所有订阅和线程被关闭；
29. Backtest 和 Recovery 不回归；
30. 不修改 `schema_version`。

---

# 二十三、文档更新

更新：

```text
README.md
AGENTS.md
docs/roadmap.md
docs/paper_runtime.md
```

必须明确：

```text
PAPER
实时行情 + Shadow Execution
Risk/Order 正常运行
不产生经济影响

SIMULATION
实时行情 + Virtual Broker
产生虚拟经济影响

LIVE
实时行情 + Real Broker
产生真实经济影响
```

禁止将 Paper 描述成：

```text
完全禁用 Order
模拟成交
真实交易
```

---

# 二十四、推荐提交拆分

建议：

```text
Runtime: Introduce shared streaming runtime foundation

Runtime: Add Paper factory and live market-data lifecycle

Data: Add live bar finalization and historical handoff

Execution: Add shadow execution submission capability

Observation: Add indicator and shadow-order projections

Example: Add MiniQMT paper MACD configuration

Test: Add Paper streaming integration and compatibility coverage

Docs: Define Paper, Simulation and Live semantics
```

---

# 二十五、最终报告

完成后输出：

## 1. 当前实现审计

说明修改前：

```text
Paper Factory 状态
Live/Streaming Runtime 状态
MiniQMT Live 数据能力
Risk/Order/Execution 边界
```

## 2. 架构决策

说明：

```text
为什么 Paper 和 Live 共用 Streaming Runtime
为什么 Runtime Mode 与 Execution Capability 分离
为什么 Paper 使用 Shadow Execution
```

## 3. 修改文件

逐项列出新增、修改和删除文件。

## 4. 生命周期

给出：

```text
Initialize
Start
Warmup
Subscribe
Run
Degraded
Stop
Close
```

实际流程。

## 5. Order 行为

明确展示：

```text
Risk Accept
Order Intent
WOULD_SUBMIT
SUPPRESSED
Reservation Release
```

并证明没有 Fill 和经济变化。

## 6. 测试结果

列出实际执行命令和真实结果。

## 7. MiniQMT 本地验收

环境可用时给出真实结果。

环境不可用时写：

```text
NOT EXECUTED
```

不能写成通过。

## 8. 未完成内容

明确列出：

```text
Simulation
Live Broker
Account Sync
Position Sync
Checkpoint
Web
A 股 Reference
```

以当前源码、真实测试和实际运行结果为准完成任务。
