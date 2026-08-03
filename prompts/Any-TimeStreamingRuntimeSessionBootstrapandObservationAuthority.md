你现在位于 OnlyAlpha 仓库根目录。

任务名称：

```text
PR5.1.2 Any-Time Streaming Runtime
Session, Bootstrap and Observation Authority
```

任务背景：

在 2026-08-03 午间休市期间执行：

```powershell
uv run onlyalpha run --config .\examples\configs\miniqmt_paper_macd.yaml
```

当前出现：

```text
RUNTIME_ASSEMBLY_FAILED:
OnlyValidationError: timestamp is outside a trading session
```

已知直接原因是 Paper Runtime 装配阶段使用当前时间调用：

```python
calendar.trading_day_at(clock.now_utc())
```

而 `trading_day_at()` 的正式合同要求时间戳必须位于交易 Session 内。

本任务不能只通过捕获异常、特殊判断午休或者把当前日期当作交易日来绕过问题。

必须从第一性原则重新收口长生命周期 Runtime 的时间、市场状态、历史节点和展示语义。

---

# 一、开始前要求

先重新审计当前仓库，不得仅根据本提示词假设代码状态。

重点阅读：

```text
AGENTS.md
README.md
docs/runtime.md
docs/paper_runtime.md
docs/roadmap.md

src/onlyalpha/engine/
src/onlyalpha/cli.py

src/onlyalpha/runtime/
src/onlyalpha/runtime/runtime.py
src/onlyalpha/runtime/paper/
src/onlyalpha/runtime/streaming/
src/onlyalpha/runtime/backtest/

src/onlyalpha/domain/calendar.py
src/onlyalpha/domain/time.py

src/onlyalpha/market/
src/onlyalpha/market/runtime_rules.py

src/onlyalpha/data/
src/onlyalpha/market_data/
src/onlyalpha/cluster/
src/onlyalpha/indicator/
src/onlyalpha/factor/
src/onlyalpha/strategy/
src/onlyalpha/order/
src/onlyalpha/risk/

packages/provider/onlyalpha-plugin-miniqmt/

examples/configs/miniqmt_paper_macd.yaml
tests/
```

确认当前真实实现：

```text
OnlyPaperRuntimeFactory 的装配过程
OnlyStreamingRuntime 的继承关系和生命周期
OnlyEngine.run / initialize / start / wait / stop
CLI 当前如何调用 Engine
Historical Warmup 调用时机
MiniQMT 实时订阅调用时机
Inbound Queue 和 Streaming Worker 启动时机
Live Bar Finalizer
MarketData Pipeline
Indicator / Factor / Strategy 调用顺序
Shadow Execution
Calendar Session API
Market Rule Engine 的编译缓存维度
```

事实优先级：

```text
1. 当前源码
2. 当前测试
3. ADR 和正式技术文档
4. AGENTS.md
5. README / Roadmap
6. 本提示词
```

如提示词中的路径或类名与当前代码不一致，应保持目标和不变量不变，按当前仓库结构实现。

---

# 二、第一性原则

必须冻结以下不变量。

## 1. Runtime 生命周期与市场是否开盘无关

```text
Runtime 是否能够启动
≠
市场当前是否处于交易 Session
```

Paper、Simulation 和 Live 必须允许在以下任意时间启动：

```text
开盘前
连续交易中
午间休市
收盘后
周末
节假日
```

休市只能表示：

```text
暂时没有新的实时市场数据
或当前订单不允许交易
```

不能表示：

```text
Runtime 无法装配
Engine 无法启动
历史数据无法加载
指标无法计算
CLI/Web 无法查看最新节点
```

---

## 2. Runtime 可以运行，不代表订单一定允许执行

例如午休期间：

```text
Runtime = RUNNING
Market = BREAK
Data = IDLE
```

如果 Strategy 因 Timer 或其他事件产生订单：

```text
Strategy
→ Risk
→ Market Rule
→ OUTSIDE_TRADING_SESSION
```

应拒绝订单行为，而不是终止 Runtime。

---

## 3. 没有新数据不等于异常

以下状态均为正常：

```text
开盘前无数据
午休无数据
收盘后无数据
周末无数据
节假日无数据
```

只有当：

```text
市场当前应产生该类行情
并且超过预期时间仍未收到行情
```

才能标记为：

```text
STALE
```

---

## 4. 历史数据必须形成可展示的当前节点

Historical Warmup 不只是让 Indicator Ready。

它必须建立：

```text
最新已完成 Bar
最新 Indicator Snapshot
最新 Factor Snapshot
策略计算状态
Historical Watermark
最新 Observation
```

即使当前市场没有新数据，CLI 和未来 Web 也必须能够查询这个最近节点。

---

## 5. 状态和事实必须有唯一 Authority

禁止让以下组件分别推导一套不同状态：

```text
Paper Factory
Streaming Runtime
CLI
Web
Console Sink
Health Service
```

需要建立统一的：

```text
Market Session Authority
Completed Bar Boundary Authority
Streaming Phase Authority
Latest Observation Authority
```

---

# 三、明确状态模型

不得继续将全部状态塞入 `OnlyRuntimeState`。

必须区分以下四个维度。

## 1. Runtime Lifecycle

继续表达系统生命周期：

```python
class OnlyRuntimeState(StrEnum):
    CREATED = "CREATED"
    INITIALIZING = "INITIALIZING"
    READY = "READY"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    STOPPING = "STOPPING"
    STOPPED = "STOPPED"
    FAILED = "FAILED"
    CLOSED = "CLOSED"
```

不要为了午休加入：

```text
BREAK
CLOSED_DAY
POST_CLOSE
```

这些不是 Runtime 生命周期。

---

## 2. Streaming Phase

新增通用实时阶段：

```python
class OnlyStreamingPhase(StrEnum):
    CREATED = "CREATED"
    SUBSCRIBING = "SUBSCRIBING"
    BOOTSTRAP = "BOOTSTRAP"
    CATCH_UP = "CATCH_UP"
    LIVE = "LIVE"
    STOPPING = "STOPPING"
    STOPPED = "STOPPED"
    FAILED = "FAILED"
```

语义：

```text
SUBSCRIBING
建立实时订阅，Callback 开始进入缓冲边界

BOOTSTRAP
历史数据回放和计算状态重建

CATCH_UP
处理历史查询期间到达的实时数据

LIVE
正常处理新的实时闭合 Bar
```

---

## 3. Market Session State

新增：

```python
class OnlyMarketSessionState(StrEnum):
    PRE_OPEN = "PRE_OPEN"
    OPEN = "OPEN"
    BREAK = "BREAK"
    POST_CLOSE = "POST_CLOSE"
    CLOSED_DAY = "CLOSED_DAY"
```

状态定义必须由 Trading Calendar 和 Session Schedule 推导，不能使用硬编码小时。

---

## 4. Streaming Data State

新增：

```python
class OnlyStreamingDataState(StrEnum):
    BOOTSTRAPPING = "BOOTSTRAPPING"
    CATCHING_UP = "CATCHING_UP"
    LIVE = "LIVE"
    IDLE = "IDLE"
    STALE = "STALE"
    DISCONNECTED = "DISCONNECTED"
    FAILED = "FAILED"
```

示例：

```text
午休：
RuntimeState       = RUNNING
StreamingPhase     = LIVE
MarketSessionState = BREAK
StreamingDataState = IDLE
```

---

# 四、保持 Calendar API 职责清晰

`OnlyTradingCalendar.trading_day_at(timestamp)` 当前严格要求时间位于某个 Session 内。

保留这个合同，不要修改成模糊的“猜一个交易日”。

它继续用于：

```text
行情时间戳属于哪个交易日
订单时间戳属于哪个交易日
成交时间戳属于哪个交易日
```

不得用于：

```text
Runtime 启动时强行选择当前交易日
```

不要通过以下方式修改：

```python
try:
    return trading_day_at(timestamp)
except:
    return local_date
```

这会在周末和节假日返回非法交易日。

---

# 五、实现 Market Session Authority

建议新增：

```text
src/onlyalpha/market/session_clock.py
```

定义不可变快照：

```python
@dataclass(frozen=True, slots=True)
class OnlyMarketSessionSnapshot:
    observed_at: OnlyTimestamp
    calendar_id: OnlyCalendarId

    state: OnlyMarketSessionState

    local_date: date
    local_time: time

    active_session: OnlyTradingSession | None

    current_trading_day: OnlyTradingDay | None
    previous_trading_day: OnlyTradingDay | None
    next_trading_day: OnlyTradingDay

    previous_market_close: OnlyTimestamp | None
    next_market_open: OnlyTimestamp
    next_market_close: OnlyTimestamp
```

定义服务：

```python
class OnlyMarketSessionResolver:
    def __init__(self, calendar: OnlyTradingCalendar) -> None:
        self._calendar = calendar

    def resolve(
        self,
        timestamp: OnlyTimestamp,
    ) -> OnlyMarketSessionSnapshot:
        ...
```

## 状态解析规则

### 当前位于某个 Session

```text
state               = OPEN
active_session      = calendar.session_at(now)
current_trading_day = calendar.trading_day_at(now)
```

### 当前日期是交易日，位于首场 Session 前

```text
state               = PRE_OPEN
current_trading_day = 当日
next_market_open    = 当日第一场 Session Open
```

### 当前日期是交易日，位于两个 Session 之间

```text
state               = BREAK
current_trading_day = 当日
next_market_open    = 当日下一场 Session Open
```

### 当前日期是交易日，所有 Session 已结束

```text
state               = POST_CLOSE
current_trading_day = 当日
next_trading_day    = 下一个有效交易日
```

### 当前日期不是交易日

```text
state               = CLOSED_DAY
current_trading_day = None
next_trading_day    = next_open 所属交易日
```

必须复用现有 Calendar：

```text
is_trading_day
sessions_for_trading_day
session_intervals_for_trading_day
session_at
next_open
next_close
previous_close
```

不要复制周末、Holiday 或 Special Schedule 判断。

---

# 六、修复 Paper Factory 装配错误

当前 Factory 中不能再调用：

```python
calendar.trading_day_at(clock.now_utc())
```

作为 Runtime 是否能够装配的条件。

## 推荐实现

```python
startup_snapshot = market_session_resolver.resolve(
    OnlyTimestamp.from_datetime(clock.now_utc())
)

validation_day = (
    startup_snapshot.current_trading_day
    or startup_snapshot.next_trading_day
)
```

`validation_day` 只用于启动期校验：

```text
Profile 能否解析
Reference 是否存在
Instrument 与 Profile 是否兼容
规则是否能够编译
```

不得保存为 Runtime 永久的“当前交易日”。

真实业务规则继续按每个：

```text
Bar.trading_day
Order Context.trading_day
Trade.trading_day
```

进行惰性编译。

如果启动期预编译没有实际价值或会引入错误职责，可以将其替换为不依赖具体业务时间戳的静态验证。

优先原则：

```text
Factory 负责装配和静态兼容性验证
Runtime/Market Rule 负责实际业务交易日
```

---

# 七、实现 Completed Bar Boundary Authority

当前不能再使用：

```python
now.replace(second=0, microsecond=0)
```

作为 Historical Warmup 截止时间。

建议新增：

```text
src/onlyalpha/market_data/completed_boundary.py
```

接口：

```python
class OnlyCompletedBarBoundaryResolver:
    def latest_completed_bar_end(
        self,
        *,
        calendar: OnlyTradingCalendar,
        bar_type: OnlyBarType,
        observed_at: OnlyTimestamp,
    ) -> OnlyTimestamp:
        ...
```

## 必须支持

```text
交易中
开盘前
午休
收盘后
周末
节假日
Special Schedule
跨午夜 Session
```

## 1m 示例

```text
2026-08-03 09:00 Asia/Shanghai
→ 上一个交易日 15:00

2026-08-03 10:21:37
→ 10:21:00

2026-08-03 12:44
→ 11:30:00

2026-08-03 16:00
→ 15:00:00

周六 10:00
→ 上一个交易日最后 Session Close
```

## 规则

1. 取得不晚于 `observed_at` 的最近有效 Session；
2. 当前位于 Session 内时，按 Session Open 和 Bar Step 对齐；
3. 当前位于 Session 外时，使用最近一个已完成 Session Close；
4. 不允许 Bar 跨越午休；
5. 不允许 Bar 跨越不同 Session；
6. 返回值必须是 UTC；
7. 返回值表示允许 Historical Provider 返回的最大 `bar_end`；
8. 当前正在形成的 Bar 不得进入 Warmup。

不要为 09:30、11:30、13:00、15:00 写 A 股硬编码。

---

# 八、Streaming 启动顺序必须调整

当前若是：

```text
Historical Warmup
→ Live Subscribe
```

则历史查询期间可能丢失新的实时 Bar。

目标顺序：

```text
1. Runtime Initialize
2. DataSource Initialize
3. DataSource Connect / Authenticate
4. StreamingPhase → SUBSCRIBING
5. 建立实时订阅
6. Callback 仅标准化并写入有界 Inbound Queue
7. StreamingPhase → BOOTSTRAP
8. 计算 Completed Bar Boundary
9. 执行 Required Historical Warmup
10. 按时间顺序回放历史 Bar
11. 建立 Historical Watermark
12. StreamingPhase → CATCH_UP
13. 处理订阅期间缓存的实时数据
14. 删除与 Historical Watermark 重叠的数据
15. 建立 Live Finalizer Pending State
16. StreamingPhase → LIVE
17. RuntimeState → RUNNING
18. 发布最新 Observation
```

要求：

```text
Historical Warmup 失败
→ Fail Closed
→ 不进入 CATCH_UP/LIVE
→ 取消订阅
→ 关闭 DataSource
→ 关闭线程和 Clock
```

不允许因为已经先订阅就绕过 Required Warmup。

---

# 九、Historical Watermark

定义不可变模型：

```python
@dataclass(frozen=True, slots=True)
class OnlyHistoricalWatermark:
    source_id: OnlyMarketDataSourceId
    instrument_id: OnlyInstrumentId
    bar_type: OnlyBarType

    last_bar_start: OnlyTimestamp
    last_bar_end: OnlyTimestamp

    data_version: OnlyDataVersion
    content_fingerprint: str
```

Catch-up 规则：

```text
live.bar_end <= watermark.last_bar_end
→ 丢弃
→ 记录 HISTORICAL_OVERLAP

live.bar_end > watermark.last_bar_end
→ 进入 Live Bar Finalizer
```

唯一 Bar Identity：

```text
instrument_id
bar_type
bar_start
```

历史和实时不能让同一个 Bar 两次进入：

```text
Indicator
Factor
Strategy
```

---

# 十、Streaming Phase 与 Strategy 行为

Indicator 和 Factor 必须在：

```text
BOOTSTRAP
CATCH_UP
LIVE
```

全部执行，以重建完整计算状态。

Strategy callback 也应执行，以便重建策略内部状态机。

但订单副作用必须按阶段控制。

## BOOTSTRAP

```text
Indicator 更新
Factor 更新
Strategy 状态更新
ctx.order 不创建正式 Order
不执行 Risk Reservation
不写 Shadow Order Audit
不产生 WOULD_SUBMIT
```

返回明确结果：

```text
ORDER_INTENT_SUPPRESSED_DURING_BOOTSTRAP
```

## CATCH_UP

默认行为：

```text
更新计算状态
不创建已经过期的正式 Shadow Order
```

返回：

```text
ORDER_INTENT_SUPPRESSED_DURING_CATCH_UP
```

## LIVE

保持 Paper 正式语义：

```text
Strategy
→ Risk
→ Order
→ Reservation
→ WOULD_SUBMIT
→ Shadow SUPPRESSED
→ Reservation Release
```

不得通过 Strategy 自己判断：

```python
if runtime_mode == PAPER:
```

应由 Runtime 注入的 Order Side-Effect Policy 决定。

建议定义：

```python
class OnlyOrderIntentPhasePolicy(Protocol):
    def submit(
        self,
        request: OnlyOrderRequest,
        phase: OnlyStreamingPhase,
    ) -> OnlyOrderSubmitResult:
        ...
```

或者使用现有 Port 结构完成等价行为。

不要在 `OnlyOrderService` 中散布大量 Streaming Runtime 条件。

---

# 十一、Observation Read Model

必须建立统一、只读、可供 CLI 和 Web 使用的最新节点。

建议新增：

```text
src/onlyalpha/observation/
├── __init__.py
├── models.py
├── store.py
├── publisher.py
├── console.py
└── jsonl.py
```

模型示例：

```python
@dataclass(frozen=True, slots=True)
class OnlyMarketObservationSnapshot:
    runtime_id: OnlyRuntimeId
    cluster_id: OnlyClusterId
    instrument_id: OnlyInstrumentId
    bar_type: OnlyBarType

    observed_at: OnlyTimestamp

    runtime_state: OnlyRuntimeState
    streaming_phase: OnlyStreamingPhase
    market_session_state: OnlyMarketSessionState
    data_state: OnlyStreamingDataState

    observation_source: OnlyObservationSource

    latest_bar_start: OnlyTimestamp
    latest_bar_end: OnlyTimestamp
    latest_close: Decimal
    latest_volume: Decimal

    historical_watermark: OnlyTimestamp | None

    previous_market_close: OnlyTimestamp | None
    next_market_open: OnlyTimestamp

    indicator_snapshots: tuple[Mapping[str, object], ...]
    factor_snapshots: tuple[Mapping[str, object], ...]

    latest_order_intents: tuple[Mapping[str, object], ...]

    market_data_lag_ms: int
    stale: bool
```

Observation Source：

```python
class OnlyObservationSource(StrEnum):
    HISTORICAL_BOOTSTRAP = "HISTORICAL_BOOTSTRAP"
    CATCH_UP = "CATCH_UP"
    LIVE = "LIVE"
```

---

# 十二、Latest Observation Store

定义：

```python
class OnlyLatestObservationStore:
    def put(
        self,
        snapshot: OnlyMarketObservationSnapshot,
    ) -> None:
        ...

    def latest(
        self,
        runtime_id: OnlyRuntimeId,
        cluster_id: OnlyClusterId,
        instrument_id: OnlyInstrumentId,
        bar_type: OnlyBarType,
    ) -> OnlyMarketObservationSnapshot | None:
        ...

    def list_runtime(
        self,
        runtime_id: OnlyRuntimeId,
    ) -> tuple[OnlyMarketObservationSnapshot, ...]:
        ...
```

要求：

```text
Runtime 写入
CLI 读取
未来 Web 读取
Console Sink 读取
JSONL Sink 读取
```

禁止每个显示层直接读取不同 Manager 并重新拼装状态。

必须保证：

```text
CLI Snapshot
=
Web Snapshot
=
Console Snapshot
=
JSONL Snapshot
```

---

# 十三、Observation 发布时机

## Historical Bootstrap 完成

无论市场是否开盘，必须发布一次：

```text
observation_source = HISTORICAL_BOOTSTRAP
```

这样午休、收盘后和周末均可立即查看历史节点。

## Catch-up 产生更新节点

```text
observation_source = CATCH_UP
```

## 新实时 Bar 闭合

```text
observation_source = LIVE
```

同一闭合 Bar 只能发布一次正式节点。

---

# 十四、Console 和 JSONL

实现：

```text
OnlyConsoleObservationSink
OnlyJsonLinesObservationSink
OnlyCompositeObservationSink
```

必须使用独立有界 Publisher Queue。

显示和磁盘写入不能阻塞 MarketData Worker。

慢 Consumer 时：

```text
允许丢弃旧 Snapshot
保留最新 Snapshot
增加 observation_drop_count
```

不得丢弃唯一的最新状态。

午休启动后的输出示例：

```text
Runtime      : paper-miniqmt
Mode         : PAPER
Execution    : SHADOW

Runtime      : RUNNING
Streaming    : LIVE
Market       : BREAK
Data         : IDLE

Instrument   : 600000.XSHG
Bar          : 1m
Node Source  : HISTORICAL_BOOTSTRAP
Last Bar     : 2026-08-03 11:30:00+08:00
Next Open    : 2026-08-03 13:00:00+08:00

Close        : 10.37
Volume       : 183400

MACD
Ready        : true
DIF          : ...
DEA          : ...
Histogram    : ...

Status       : waiting for next market Bar
```

---

# 十五、CLI 生命周期必须收口

当前 `onlyalpha run` 不能继续无条件调用 `engine.run()`。

`engine.run()` 应保持有限运行语义：

```text
BACKTEST
→ FINITE
```

Paper、Simulation 和 Live 使用：

```text
initialize
→ start
→ wait
→ stop
```

建议定义：

```python
class OnlyRuntimeLifecycleKind(StrEnum):
    FINITE = "FINITE"
    LONG_LIVED = "LONG_LIVED"
```

映射：

```text
BACKTEST   → FINITE
PAPER      → LONG_LIVED
SIMULATION → LONG_LIVED
LIVE       → LONG_LIVED
```

增加应用服务：

```python
class OnlyEngineApplicationRunner:
    def execute(
        self,
        engine: OnlyEngine,
    ) -> int:
        ...
```

有限模式：

```python
engine.run()
```

长生命周期：

```python
try:
    engine.initialize()
    engine.start()
    engine.wait()
except KeyboardInterrupt:
    pass
finally:
    engine.stop()
    engine.close()
```

禁止 CLI 绕过 `OnlyEngine` 直接启动 Runtime。

---

# 十六、Snapshot 命令

增加一次性状态命令：

```powershell
uv run onlyalpha snapshot \
  --config examples/configs/miniqmt_paper_macd.yaml
```

语义：

```text
装配 Engine
→ Historical Warmup
→ 建立最新 Observation
→ 可选完成当前 Catch-up
→ 输出一次 Snapshot
→ 安全退出
```

该命令在：

```text
午休
收盘后
周末
节假日
```

都必须能够输出最近历史节点。

不能通过 Snapshot 命令绕过 Required Warmup。

---

# 十七、Health 语义

实现统一 Health：

```python
@dataclass(frozen=True, slots=True)
class OnlyStreamingRuntimeHealth:
    runtime_state: OnlyRuntimeState
    streaming_phase: OnlyStreamingPhase

    market_session_state: OnlyMarketSessionState
    data_state: OnlyStreamingDataState

    source_connected: bool
    worker_alive: bool

    last_received_at: OnlyTimestamp | None
    last_closed_bar_end: OnlyTimestamp | None
    next_expected_bar_end: OnlyTimestamp | None
    next_market_open: OnlyTimestamp

    inbound_queue_size: int
    observation_queue_size: int

    duplicate_count: int
    overlap_count: int
    sequence_gap_count: int
    stale_count: int
    observation_drop_count: int
```

## STALE 判断

只有：

```text
MarketSessionState = OPEN
```

并且：

```text
now > next_expected_bar_end + allowed_grace
```

仍未收到对应行情时，才能：

```text
DataState = STALE
```

以下全部应是：

```text
DataState = IDLE
```

而不是 STALE：

```text
PRE_OPEN
BREAK
POST_CLOSE
CLOSED_DAY
```

---

# 十八、代码整洁要求

## 1. 禁止时间特例

禁止：

```python
if 11:30 <= now <= 13:00:
```

禁止硬编码 A 股 Session 时间。

所有判断必须来自 Calendar。

---

## 2. 禁止散布模式判断

禁止在以下组件中散布：

```python
if runtime_mode == PAPER:
```

```text
Indicator
Factor
Strategy
Risk Manager
Order Manager
MarketData Pipeline
```

模式差异只能存在于：

```text
Composition Root
Runtime Factory
Execution Port
Order Side-Effect Policy
Account Authority
```

---

## 3. 禁止宽泛吞异常

不得通过：

```python
except Exception:
    pass
```

让 Runtime 假装成功。

预期状态使用明确分支；异常表示真正失败。

---

## 4. 不复制权威逻辑

禁止复制：

```text
周末判断
Holiday 判断
Session 判断
交易日推进
Bar 对齐
```

必须复用正式 Calendar 和 Boundary Authority。

---

## 5. 使用不可变模型

状态快照、Watermark、Observation 和 Health 使用：

```python
@dataclass(frozen=True, slots=True)
```

避免共享可变字典成为公共合同。

---

## 6. 不增加生产 test_mode

测试通过依赖注入：

```text
Clock
Calendar
DataSource
Worker Command
Observation Sink
```

不得增加：

```python
if test_mode:
```

---

## 7. 不修改 Schema Version

继续保持：

```yaml
schema_version: "1.0"
```

首期新增参数使用当前 `extensions` 机制。

---

## 8. 不重写已工作的组件

继续复用：

```text
OnlyEngine
OnlyLiveClock
MarketData Inbound Queue
OnlyStreamingMarketDataWorker
OnlyLiveBarFinalizer
MarketData Pipeline
Indicator Registry
Factor Pipeline
Strategy
Shadow Execution
Historical Warmup Port
MiniQMT Isolated Historical Worker
```

只修正职责、生命周期和状态边界。

---

# 十九、建议文件结构

实际路径以当前仓库为准。

新增：

```text
src/onlyalpha/market/session_clock.py

src/onlyalpha/market_data/completed_boundary.py
src/onlyalpha/market_data/watermark.py

src/onlyalpha/runtime/streaming/phase.py
src/onlyalpha/runtime/streaming/health.py
src/onlyalpha/runtime/streaming/order_policy.py

src/onlyalpha/observation/__init__.py
src/onlyalpha/observation/models.py
src/onlyalpha/observation/store.py
src/onlyalpha/observation/publisher.py
src/onlyalpha/observation/console.py
src/onlyalpha/observation/jsonl.py

src/onlyalpha/application/engine_runner.py
```

修改：

```text
src/onlyalpha/runtime/paper/factory.py
src/onlyalpha/runtime/streaming/runtime.py
src/onlyalpha/runtime/streaming/worker.py
src/onlyalpha/runtime/streaming/config.py

src/onlyalpha/domain/calendar.py
src/onlyalpha/engine/engine.py
src/onlyalpha/cli.py

src/onlyalpha/cluster/
src/onlyalpha/strategy/context.py
src/onlyalpha/order/
```

不要仅为了匹配此列表移动大量已有文件。

---

# 二十、实施顺序

按以下顺序实现，每一步保持测试可运行。

## Commit 1

```text
Market: Add session-state resolver
```

完成：

```text
PRE_OPEN
OPEN
BREAK
POST_CLOSE
CLOSED_DAY
```

---

## Commit 2

```text
Runtime: Allow streaming assembly outside market sessions
```

完成：

```text
删除 trading_day_at(now) 装配阻断
Factory 可在任意时间装配
规则预检查使用合法 Validation Day
```

---

## Commit 3

```text
Data: Add calendar-aware completed Bar boundary
```

完成：

```text
交易中
午休
收盘后
开盘前
周末
节假日
```

历史截止边界。

---

## Commit 4

```text
Runtime: Add subscribe-bootstrap-catch-up-live phases
```

完成：

```text
先订阅
再 Warmup
Historical Watermark
Catch-up Overlap Dedup
Live Phase
```

---

## Commit 5

```text
Runtime: Suppress non-live order side effects
```

完成：

```text
BOOTSTRAP/CATCH_UP 重建策略状态
不创建过期 Shadow Order
LIVE 保持正式 Shadow 语义
```

---

## Commit 6

```text
Observation: Add latest market observation authority
```

完成：

```text
Snapshot
Store
Publisher
Console
JSONL
```

---

## Commit 7

```text
CLI: Separate finite, long-lived and snapshot execution
```

完成：

```text
Backtest run
Paper serve
snapshot
Ctrl+C
```

---

## Commit 8

```text
Runtime: Add session-aware health
```

完成：

```text
IDLE
STALE
DISCONNECTED
Next Open
Next Expected Bar
Queue Metrics
```

---

# 二十一、测试要求

## 1. Calendar Session Resolver

固定 Asia/Shanghai 时间：

```text
2026-08-03 09:00 → PRE_OPEN
2026-08-03 10:00 → OPEN
2026-08-03 12:44 → BREAK
2026-08-03 16:00 → POST_CLOSE
2026-08-08 10:00 → CLOSED_DAY
```

增加 Holiday 和 Special Schedule。

---

## 2. Completed Bar Boundary

1m：

```text
09:00 → 上一个交易日 15:00
10:21:37 → 10:21
12:44 → 11:30
16:00 → 15:00
周六 → 上一个交易日 15:00
```

3m：

```text
Session 内合法对齐
不跨午休
下午从下午 Session Open 重新对齐
```

---

## 3. Paper Factory

在：

```text
PRE_OPEN
OPEN
BREAK
POST_CLOSE
CLOSED_DAY
```

装配。

全部必须越过：

```text
timestamp is outside a trading session
```

---

## 4. Bootstrap/Catch-up

覆盖：

```text
无重叠
完全重叠
部分重叠
Warmup 期间到达实时 Bar
重复实时 Callback
乱序 Callback
Warmup 失败
```

断言同一个 Bar 只进入一次正式 Pipeline。

---

## 5. Strategy 和 Order Phase

BOOTSTRAP：

```text
Indicator 更新
Factor 更新
Strategy 状态更新
无正式 Order
无 Risk Reservation
无 Shadow Audit
```

CATCH_UP：

```text
无过期 Shadow Order
```

LIVE：

```text
Risk 执行
Order 创建
WOULD_SUBMIT
SUPPRESSED
Reservation 释放
```

---

## 6. Observation

断言：

```text
午休启动后立即有历史 Observation
无实时数据时 Latest Snapshot 可查询
新实时 Bar 到达后 Snapshot 前进
Console/JSONL 来自同一个 Snapshot
慢 Sink 不阻塞 Worker
```

---

## 7. Health

断言：

```text
BREAK 无数据 → IDLE
POST_CLOSE 无数据 → IDLE
CLOSED_DAY 无数据 → IDLE
OPEN 超时无数据 → STALE
Source 断开 → DISCONNECTED
```

---

## 8. CLI

覆盖：

```text
Backtest 使用 engine.run()
Paper 使用 initialize/start/wait/stop
Ctrl+C 安全退出
snapshot 输出后退出
混合 FINITE/LONG_LIVED 配置 Fail Closed
```

---

# 二十二、真实验收

## 午间休市启动

目标状态：

```text
Runtime      = RUNNING
Streaming    = LIVE
Market       = BREAK
Data         = IDLE
Node Source  = HISTORICAL_BOOTSTRAP
Last Bar     = 11:30
Next Open    = 13:00
```

## 收盘后启动

```text
Runtime      = RUNNING
Market       = POST_CLOSE
Data         = IDLE
Last Bar     = 15:00
Next Open    = 下一个交易日开盘
```

## 周末启动

```text
Runtime      = RUNNING
Market       = CLOSED_DAY
Data         = IDLE
Last Bar     = 上一个交易日收盘节点
Next Open    = 下一个有效交易日
```

## 交易中启动

```text
Historical Bootstrap
→ Catch-up
→ Live Closed Bar
→ Observation 前进
```

---

# 二十三、与 MiniQMT Historical 阻断的关系

本任务必须消除：

```text
timestamp is outside a trading session
```

但不能声称自动修复 XtQuant Historical BSON assertion。

真实运行可能变成：

```text
Paper Factory 装配成功
→ Historical Warmup
→ MiniQMT Worker WORKER_ABORTED
→ Runtime Fail Closed
```

应明确区分：

```text
Any-Time Assembly       : PASS
Historical Compatibility: BLOCKED
Paper Product            : FAILED
```

只有 Historical Warmup 成功或使用明确、验证过的 Historical Provider，才能产生真实历史 Observation。

禁止为了显示节点而跳过 Required Warmup。

---

# 二十四、明确非目标

本任务不实现：

```text
MiniQMT Historical BSON 根因修复
真实 MiniQMT Broker
Live Account Sync
Live Position Sync
Simulation Runtime
Streaming Checkpoint
A 股 Effective Reference Authority
完整重连和 Gap Recovery
Web Server
YAML Schema 2.0
```

但 Observation Store 和 Health Contract 必须适合未来 Web 使用。

---

# 二十五、完成标准

只有以下全部满足，才可以声明完成：

1. Runtime 可在任意市场时间装配；
2. 不再用 `trading_day_at(now)` 决定启动成功；
3. `trading_day_at()` 严格合同保持不变；
4. Runtime Lifecycle 与 Market Session State 分离；
5. Streaming Phase 与 Data State 分离；
6. 午休、收盘后、周末无数据均为 IDLE；
7. 只有 OPEN 期间缺数据才是 STALE；
8. Historical Cutoff 使用 Calendar-aware Boundary；
9. 午休 Cutoff 为最近 Session Close；
10. 周末 Cutoff 为上一个有效交易日 Session Close；
11. 先订阅再执行 Warmup；
12. Historical Watermark 正确建立；
13. Catch-up 重叠 Bar 不重复处理；
14. BOOTSTRAP/CATCH_UP 不产生过期 Shadow Order；
15. LIVE 正常执行 Risk/Order/Shadow；
16. Historical Bootstrap 完成后立即发布 Observation；
17. 无实时 Bar 时 Latest Observation 仍可查询；
18. 新实时 Bar 到达后 Observation 正常推进；
19. Console 和 JSONL 使用同一 Read Model；
20. CLI 对长生命周期模式不再调用有限 `engine.run()`；
21. Snapshot 命令可以输出一次当前节点；
22. Ctrl+C 后无残留订阅、线程或进程；
23. Backtest 行为和 Determinism 不回归；
24. Historical Warmup 失败仍然 Fail Closed；
25. 不修改 `schema_version`；
26. 不加入午休硬编码；
27. 不散布 Runtime Mode 判断；
28. 不引入生产 `test_mode`；
29. 不吞异常冒充成功；
30. 文档准确区分实现、自动化和真实产品状态。

---

# 二十六、门禁

执行当前仓库规定的完整门禁，至少包括：

```powershell
uv lock
uv sync --frozen --all-packages --all-groups

uv run ruff check src tests examples packages scripts
uv run ruff format --check src tests examples packages scripts
uv run mypy src/onlyalpha
```

测试：

```powershell
uv run python scripts/test_suite.py fast
uv run python scripts/test_suite.py integration
uv run python scripts/test_suite.py miniqmt-contract
uv run python scripts/test_suite.py ashare
uv run python scripts/test_suite.py recovery
uv run python scripts/test_suite.py full
```

不得通过删除、跳过或放宽已有测试完成任务。

---

# 二十七、最终报告

完成后输出：

## 1. 原问题根因

说明：

```text
为什么午休会导致 Runtime Assembly 失败
为什么这是 Calendar API 使用错误
```

## 2. 架构变化

说明：

```text
Runtime Lifecycle
Streaming Phase
Market Session State
Data State
Completed Boundary
Historical Watermark
Observation Authority
```

## 3. 生命周期

给出实际：

```text
Initialize
Subscribe
Bootstrap
Catch-up
Live
Stop
```

执行顺序。

## 4. 修改文件

逐项列出新增、修改、删除文件。

## 5. 测试结果

列出真实执行命令和真实结果。

## 6. 真实环境结果

分别报告：

```text
PRE_OPEN
OPEN
BREAK
POST_CLOSE
CLOSED_DAY
```

无法执行的场景写：

```text
NOT EXECUTED
```

不能写为通过。

## 7. 产品状态

必须区分：

```text
Any-Time Assembly
Historical Warmup
Observation
Paper Product Acceptance
```

例如：

```text
Any-Time Assembly       : PASS
Observation Infrastructure: PASS
MiniQMT Historical      : BLOCKED
Paper Product           : FAILED
```

以当前源码、实际测试和真实环境结果为准完成任务。
