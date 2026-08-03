# PR5.1.3 Paper Real Product Acceptance 实现方案

## 一、PR 的准确定位

PR5.1.3 不是继续新增一套 Paper Runtime，也不是重写 Streaming Runtime。

它的目标是：

```text
把 PR5.1、PR5.1.1、PR5.1.2 已经实现的能力
组织成一条可重复执行、可自动判定、可归档证据的真实产品验收链。
```

需要验收的当前产品范围是：

```text
Paper Read-Only Market Observation
+
Shadow Order Safety
```

不是：

```text
生产级完整 Paper Trading Runtime
```

因此 PR5.1.3 通过后，允许声明：

```text
Paper Read-Only Observation Current Scope : PASS
```

但仍应保持：

```text
Production Paper Runtime : PARTIAL
```

因为以下内容仍属于后续 PR：

```text
运行期间断线重连
实时 Gap Recovery
Streaming Checkpoint/Recovery
多数据源容灾
多证券真实兼容矩阵
生产级长期运行
```

---

# 二、验收范围冻结

## 2.1 正式验收配置

使用一个固定、不可随意变化的验收 Profile：

```text
Platform              : Windows
Runtime               : PAPER
Execution Capability  : SHADOW
Historical Provider   : MiniQMT isolated worker
Historical Protocol   : v2
Instrument            : 000001.XSHE
Provider Symbol       : 000001.SZ
External Bar          : 1m
Internal Bar          : 3m
Cluster Count         : 1
Strategy              : Paper acceptance intent strategy
Indicator             : MACD
Factor                : 至少一个正式 Factor
Persistence           : MEMORY
Real Broker           : DISABLED
```

之所以固定使用 `000001.XSHE`，是因为当前真实证据表明该证券的 1m Historical Worker 可以通过，而部分沪市证券在同一 MiniQMT 服务上仍会触发 XtQuant BSON 原生断言。

固定 Profile 的意义是避免出现：

```text
这次换证券
下次换指标
再下次换时间周期
最终每次通过的都不是同一个产品合同
```

## 2.2 当前范围的成功定义

完整成功链路：

```text
OnlyEngine
→ Paper Factory
→ Streaming Runtime
→ MiniQMT Connect
→ Live Subscribe
→ Historical Worker v2
→ Historical Validation
→ Historical Pipeline Replay
→ Historical Watermark
→ Catch-up Dedup
→ Live Bar Finalizer
→ 1m Closed Bar
→ Internal 3m Aggregation
→ Indicator
→ Factor
→ Strategy
→ Risk
→ Order Intent
→ Shadow Execution Suppressed
→ Reservation Released
→ Observation
→ Health
→ Ordered Shutdown
```

---

# 三、第一性原则

## 3.1 验收不能成为另一套业务实现

Acceptance Harness 只能：

```text
启动正式 OnlyEngine
查询正式只读状态
等待正式事件发生
验证产品不变量
收集和归档证据
```

禁止：

```text
直接调用 Strategy
手工构造 Shadow Order
绕过 Engine 调用 Runtime
直接修改 Position/Account
向 Inbound Queue 塞伪造真实数据
手工调用 Finalizer
手工调用 Indicator
通过修改内部字段制造 PASS
```

真实验收必须经过正式 Composition Root。

## 3.2 自动化通过不等于真实产品通过

必须分别记录：

```text
AUTOMATED
REAL_ENVIRONMENT
```

自动化测试负责证明：

```text
逻辑、边界、失败语义和断言器正确
```

真实验收负责证明：

```text
当前 MiniQMT 客户端、SDK、数据路径、证券和周期的实际纵切面可以工作
```

总体产品状态不能因为 Fake SDK 测试通过而变成 PASS。

## 3.3 验收程序不能改变产品行为

Acceptance Runner 不得：

```text
改变 Bar 时间戳
调整 Historical 结果
重试并吞掉错误
绕过 Required Warmup
自动切换证券
自动使用旧 Cache
把 BLOCKED 写成 PASS
```

它只能观察并判断。

## 3.4 预期失败与代码失败必须区分

必须使用明确结果：

```python
class OnlyAcceptanceVerdict(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    BLOCKED = "BLOCKED"
    NOT_EXECUTED = "NOT_EXECUTED"
```

语义：

```text
PASS
产品合同满足

FAIL
OnlyAlpha 自身违反产品不变量

BLOCKED
外部环境阻断，例如 XtQuant Native Abort

NOT_EXECUTED
当前没有满足执行条件，例如非交易时间无法执行 Live Window
```

禁止使用含糊的：

```text
PARTIAL_SUCCESS
MOSTLY_PASS
WARNING_PASS
```

---

# 四、架构设计

## 4.1 保持正式产品链不变

```text
OnlyEngine
    │
    ▼
OnlyPaperRuntime
    │
    ▼
OnlyStreamingRuntime
    │
    ├── MarketData
    ├── Indicator / Factor / Strategy
    ├── Shadow Execution
    ├── Observation
    └── Health
```

PR5.1.3 在外部增加：

```text
OnlyPaperAcceptanceRunner
    │
    ├── OnlyEngineInspectionService
    ├── Evidence Collector
    ├── Acceptance Assertions
    ├── Verdict Reducer
    └── Artifact Writer
```

## 4.2 推荐文件布局

```text
src/onlyalpha/application/
├── runtime_inspection.py
└── engine_inspection.py

src/onlyalpha/operations/acceptance/
├── __init__.py
├── models.py
├── paper_plan.py
├── paper_runner.py
├── assertions.py
├── verdict.py
├── evidence.py
├── artifacts.py
└── redaction.py

scripts/
└── run_paper_real_acceptance.py

examples/acceptance/
└── miniqmt_paper_v2.yaml

tests/acceptance/
├── test_acceptance_verdict.py
├── test_acceptance_assertions.py
├── test_acceptance_artifacts.py
├── test_paper_acceptance_fake.py
├── test_paper_acceptance_fail_closed.py
└── test_paper_acceptance_shutdown.py

docs/acceptance/
├── paper_real_product_acceptance.md
└── paper_acceptance_artifact_schema.md
```

职责划分：

```text
application/
正式的产品只读查询接口，未来 Web 也能复用

operations/acceptance/
产品验收编排，不进入 Domain 和 Runtime 业务逻辑

scripts/
命令入口，只解析参数和调用 Runner
```

---

# 五、增加统一 Runtime Inspection Authority

当前已有 Observation Store、Historical Watermark 和 Streaming Health，但验收程序不能直接访问大量私有字段。

需要建立正式只读接口。

## 5.1 Inspection Snapshot

```python
@dataclass(frozen=True, slots=True)
class OnlyStreamingRuntimeInspectionSnapshot:
    captured_at: OnlyTimestamp

    engine_id: str
    run_id: str
    runtime_id: str
    cluster_ids: tuple[str, ...]

    runtime_state: OnlyRuntimeState
    streaming_phase: OnlyStreamingPhase
    market_session_state: OnlyMarketSessionState
    data_state: OnlyStreamingDataState

    source_connected: bool
    worker_alive: bool

    historical_watermarks: tuple[OnlyHistoricalWatermark, ...]
    latest_observations: tuple[OnlyMarketObservationSnapshot, ...]

    subscriptions: tuple[OnlySubscriptionInspection, ...]

    received_update_count: int
    closed_external_bar_count: int
    derived_internal_bar_count: int

    duplicate_count: int
    historical_overlap_count: int
    out_of_order_count: int
    gap_count: int
    stale_count: int
    observation_drop_count: int

    bootstrap_suppressed_intent_count: int
    catch_up_suppressed_intent_count: int

    live_order_intent_count: int
    risk_rejected_count: int
    shadow_suppressed_count: int

    external_order_id_count: int
    fill_count: int

    open_reservation_count: int
    cash_reservation_count: int
    position_reservation_count: int
    margin_reservation_count: int

    position_count: int
    fee_count: int
    settlement_count: int
```

该模型只能包含：

```text
不可变值
正式 Read Model
聚合统计
```

不能返回：

```text
Runtime 对象
Manager 对象
Queue 对象
DataSource 对象
Strategy 对象
可变 dict 引用
```

## 5.2 Engine Inspection Service

```python
class OnlyEngineInspectionService:
    def capture(
        self,
        engine: OnlyEngine,
    ) -> tuple[OnlyStreamingRuntimeInspectionSnapshot, ...]:
        ...
```

Engine 提供只读聚合，不暴露具体 Runtime 私有实现。

未来 Web 可以直接复用：

```text
GET /runtimes
GET /runtimes/{id}/health
GET /runtimes/{id}/observations/latest
```

但 PR5.1.3 不实现 Web。

---

# 六、Acceptance Plan 模型

```python
@dataclass(frozen=True, slots=True)
class OnlyPaperAcceptancePlan:
    plan_id: str
    runtime_config_path: Path
    output_root: Path

    expected_instrument_id: str
    expected_provider_symbol: str

    external_bar_step_minutes: int
    derived_bar_step_minutes: int

    minimum_historical_bars: int
    target_live_closed_bars: int
    target_live_derived_bars: int

    require_indicator_ready: bool
    require_factor_snapshot: bool
    require_live_shadow_intent: bool

    live_grace_seconds: int
    startup_timeout_seconds: int
    shutdown_timeout_seconds: int
```

推荐固定值：

```text
minimum_historical_bars  : 50
target_live_closed_bars  : 6
target_live_derived_bars : 2
startup_timeout_seconds  : 60
shutdown_timeout_seconds : 15
```

使用 6 根实时 1m Bar，而不是 1 根，是为了同时验证：

```text
持续实时更新
Finalizer 连续闭合
序号连续性
至少两个 3m 聚合节点
Observation 连续推进
Health 不误报
```

---

# 七、验收 Case 设计

## Case A：AUTOMATED_CONTRACT

运行环境：

```text
Fake MiniQMT
Deterministic Clock
Controlled Historical Worker
```

验证所有产品逻辑和 Acceptance Harness 自身。

该 Case 可以进入普通 CI。

必须覆盖：

```text
Historical Success
Historical Native Abort Classification
Historical Timeout
Catch-up Overlap
Duplicate Callback
Out-of-order Callback
Live Finalization
Internal Aggregation
Shadow Suppression
Reservation Release
Observation
Health
Shutdown
```

结果：

```text
AUTOMATED_CONTRACT = PASS
```

不能直接推导真实产品 PASS。

---

## Case B：REAL_HISTORICAL_SNAPSHOT

该 Case 可以在任意时间执行。

流程：

```text
Engine Initialize
→ Live Subscribe
→ Required Historical Warmup
→ Historical Replay
→ Historical Watermark
→ Catch-up
→ Latest Observation
→ Stop
```

必须验证：

```text
Historical Worker Protocol = 2
Historical Bars >= 50
Historical Bars 严格递增
Historical Bar Identity 唯一
最后 Bar 不晚于 Completed Boundary
Historical Watermark 存在
Historical Observation 存在
Indicator Ready
Factor Snapshot 存在
Runtime 未产生真实经济状态变化
```

市场关闭时允许：

```text
Market = PRE_OPEN / BREAK / POST_CLOSE / CLOSED_DAY
Data = IDLE
```

不能要求一定收到新的 Live Bar。

---

## Case C：REAL_LIVE_HANDOFF

只在：

```text
MarketSessionState = OPEN
```

时执行。

启动前必须检查：

```text
当前 Session 剩余时间
>=
目标 Bar 数量 + 启动预算 + 停机预算
```

例如目标是 6 根 1m Bar，应至少预留：

```text
8～10 分钟
```

不足时：

```text
REAL_LIVE_HANDOFF = NOT_EXECUTED
reason = INSUFFICIENT_LIVE_WINDOW
```

不能因为接近午休或收盘而产生 FAIL。

### Live 验收目标

```text
closed live external 1m >= 6
derived live internal 3m >= 2
live observations >= 6
live shadow intents >= 1
```

---

## Case D：STOP_WITH_PENDING_BAR

在收到当前未闭合分钟 Bar 后主动停止。

验证：

```text
Pending Bar 不因 Stop 被伪造为 Closed
没有额外 Indicator Update
没有额外 Strategy Callback
没有额外 Observation
```

这可以使用 Fake SDK 自动化，也可以在真实 Live Case 停止时顺带验证。

---

## Case E：KNOWN_BAD_NATIVE_ABORT

可选诊断 Case，不作为当前范围成功的必要条件。

例如对当前已知不兼容证券运行：

```text
600000.SH / 1m
```

期望：

```text
Worker = NATIVE_BSON_ABORT
Parent Process = ALIVE
Runtime = FAIL CLOSED
No Position Mutation
No Account Mutation
No Residual Worker
```

该 Case 的价值是证明隔离层有效，不是要求已知不兼容证券成功。

如果未来该证券恢复成功，验收程序也应接受真实成功结果，而不是硬编码它必须失败。

---

# 八、真实验收执行流程

## 8.1 Preflight

Runner 先执行只读检查：

```text
操作系统是 Windows
Python 版本符合要求
OnlyAlpha 版本符合要求
MiniQMT 插件版本与 Core 一致
xtquant 可导入
userdata_mini 路径存在
Runtime 配置可解析
Runtime Mode = PAPER
Execution Capability = SHADOW
Broker 配置未启用
Instrument = 000001.XSHE
Historical Compatibility Profile = miniqmt-history-v2
Historical Protocol = 2
```

还应收集：

```text
OnlyAlpha Commit SHA
OnlyAlpha Version
Plugin Version
Python Version
OS Version
XtQuant Version
MiniQMT Path Fingerprint
Runtime Config Fingerprint
Acceptance Plan Fingerprint
```

禁止在报告中写入：

```text
Broker 账号
认证信息
绝对用户目录
隐私配置
```

---

## 8.2 捕获经济状态基线

Engine 启动前保存：

```python
@dataclass(frozen=True, slots=True)
class OnlyEconomicBaseline:
    cash_balance: Decimal
    position_count: int
    total_position_quantity: Decimal

    order_count: int
    fill_count: int
    fee_count: int
    settlement_count: int

    cash_reservation_count: int
    position_reservation_count: int
    margin_reservation_count: int
```

Paper 验收结束后必须与基线比较。

---

## 8.3 正式启动

必须调用：

```python
engine.initialize()
engine.start()
```

禁止调用：

```python
runtime.initialize()
runtime.start()
```

禁止为验收直接调用 Paper Factory。

Runner 捕获正式生命周期：

```text
CREATED
INITIALIZING
READY
RUNNING
STOPPING
STOPPED
CLOSED
```

Streaming Phase：

```text
CREATED
SUBSCRIBING
BOOTSTRAP
CATCH_UP
LIVE
STOPPING
STOPPED
```

每次状态变化写入：

```text
lifecycle.jsonl
```

---

## 8.4 Historical 验收

记录 Worker 证据：

```text
protocol_version
request_fingerprint
content_fingerprint
bars_file_fingerprint
compatibility_profile
time_semantics_version
process_exit_code
cache_hit
query_start
query_end
bar_count
first_bar_start
last_bar_end
diagnostic_directory
```

必须验证：

```text
time_semantics_version = 2

bar_end = XtQuant event timestamp
bar_start = bar_end - period

所有时间进入 Core 前已转换为 UTC
trading_day 依据 Asia/Shanghai 推导
```

Historical Worker 成功后：

```text
Historical Bars
→ 正式 MarketData Pipeline
→ Indicator
→ Factor
→ Strategy State
```

不能使用专用的“只更新 MACD”旁路。

---

## 8.5 Historical Watermark 验收

每个：

```text
source_id
instrument_id
bar_type
```

必须有独立 Watermark。

断言：

```text
watermark.last_bar_end
=
Historical Pipeline 实际成功处理的最后一根 Bar End
```

不能使用：

```text
Provider 返回的最后一行
```

因为最后一行可能在正式 Pipeline 中被拒绝。

---

## 8.6 Catch-up 验收

Live Subscription 在 Historical Worker 之前建立，因此 Historical 查询期间的实时 Tail 会进入 Inbound Queue。

Catch-up 断言：

```text
live.bar_end <= historical_watermark
→ 不再次进入 Pipeline

live.bar_end > historical_watermark
→ 进入 Finalizer
```

需要记录：

```text
buffered_before_bootstrap_count
historical_overlap_count
catch_up_accepted_count
catch_up_duplicate_count
```

重要不变量：

```text
Historical + Catch-up 处理后
同一个 Bar Identity 只进入一次 Indicator/Factor/Strategy
```

Bar Identity：

```text
instrument_id
bar_type
bar_start
```

---

## 8.7 实时 Bar 验收

### 时间语义

对每个 1m Bar：

```text
bar_end - bar_start = 1 minute
```

供应商在 13:01 给出的分钟 K 线表示：

```text
13:00–13:01
```

而不是：

```text
13:01–13:02
```

### Finalizer

必须验证：

```text
同一分钟多次 Callback
→ 更新 Pending Revision

下一分钟首次 Callback
→ 前一分钟正式闭合一次

相同 Bar
→ 不重复闭合
```

### 连续性

同一 Session 内：

```text
next.bar_start = previous.bar_end
```

允许的合法断点：

```text
Session Break
Session Close
Trading Day Boundary
```

不允许无解释缺口。

---

## 8.8 Internal 3m 聚合验收

必须验证：

```text
3m Bar 只由正式闭合 1m Bar 组成
3m Bar 不使用未闭合 Pending Bar
3m Bar 不跨午间休市
3m Bar 按 Session Open 对齐
```

每根 3m Bar：

```text
open   = 第一根 1m open
high   = 三根 1m high 最大值
low    = 三根 1m low 最小值
close  = 第三根 1m close
volume = 三根 1m volume 之和
```

至少取得：

```text
2 根实时产生的 3m Bar
```

Historical Bootstrap 中已有的 3m Bar不能代替实时验收计数。

---

# 九、Indicator、Factor 和 Strategy 验收

## 9.1 Indicator

至少验证 MACD：

```text
Snapshot 存在
Ready = true
ts_event = 对应最新正式闭合 Bar
DIF / DEA / Histogram 可序列化
无 NaN
无 Infinity
```

不能把：

```text
MACD 对象创建成功
```

当作 Indicator 验收通过。

## 9.2 Factor

至少有一个正式 Factor Snapshot：

```text
factor_id
ready
ts_event
value
```

断言：

```text
factor.ts_event
<=
latest_processed_bar_end
```

不能读取未来节点。

## 9.3 Strategy

验收策略必须保证真实 LIVE 阶段可以产生至少一个 Order Intent。

推荐使用专门的示例策略：

```text
OnlyPaperAcceptanceIntentStrategy
```

它应使用普通策略 API：

```python
self.ctx.order.buy(...)
```

不得读取：

```python
runtime_mode
streaming_phase
execution_capability
```

验收所需的阶段差异由 Runtime 的 Order Side-Effect Policy 控制。

策略可以采用：

```text
每根满足条件的正式闭合 1m Bar产生 Intent
```

并通过内部普通业务状态避免无限重复。

不要使用一个在 BOOTSTRAP 第一根 Bar 就永久消耗信号、导致 LIVE 阶段再也不产生 Intent 的策略。

---

# 十、阶段化订单副作用验收

## 10.1 BOOTSTRAP

允许：

```text
Strategy callback
Strategy internal state update
```

禁止：

```text
正式 Order Creation
Risk Reservation
Shadow WOULD_SUBMIT
Venue Submission
```

记录：

```text
bootstrap_suppressed_intent_count
```

## 10.2 CATCH_UP

允许：

```text
计算状态推进
```

禁止：

```text
对已经发生的旧 Bar 创建新的 Shadow Order
```

记录：

```text
catch_up_suppressed_intent_count
```

## 10.3 LIVE

完整链必须发生：

```text
Strategy Intent
→ Market Rule
→ Risk
→ Order Creation
→ Reservation
→ WOULD_SUBMIT
→ Shadow SUPPRESSED
→ Reservation Release
```

至少取得一个真实证据：

```text
live_order_intent_count >= 1
shadow_suppressed_count >= 1
```

---

# 十一、Shadow Execution 安全不变量

每个通过 Risk 的 Live Intent 必须满足：

```text
external_order_id = None
venue_order_id = None
fill_count = 0
trade_count = 0
```

终态必须明确表示：

```text
Execution Outcome = SUPPRESSED
Reason = PAPER_RUNTIME / SHADOW_EXECUTION
```

不建议把正常 Shadow 行为作为普通技术失败统计。

如果当前 Order State 仍只能使用终态失败，需要至少保证：

```text
reason_code = EXECUTION_SUPPRESSED_BY_RUNTIME
```

并在 Acceptance Report 中归类为：

```text
EXPECTED_SHADOW_TERMINAL
```

而不是产品失败。

---

# 十二、Reservation Release 验收

执行 Shadow Suppression 后，必须验证：

```text
Cash Reservation     = 0
Position Reservation = 0
Margin Reservation   = 0
```

或者与启动前基线完全一致。

需要捕获状态转换：

```text
Risk Accepted
→ Provisional Reservation
→ Shadow Suppressed
→ Reservation Released
```

不能只检查最终为零，还应有释放事件或审计记录，证明不是从未创建 Reservation。

---

# 十三、经济状态隔离验收

运行前后比较：

```text
Cash
Position
Allocation
Ledger
Fee
Settlement
Fill
```

必须满足：

```text
fills               = 0
positions_mutated   = 0
cash_mutated        = 0
fees                = 0
settlements         = 0
external_order_ids  = 0
```

Paper 可以产生：

```text
Order Intent Audit
Risk Decision Audit
Shadow Suppression Audit
```

但不能产生真实经济状态。

---

# 十四、Observation 验收

## 14.1 Historical Observation

Historical Bootstrap 完成后，即使当前休市，也必须存在：

```text
observation_source = HISTORICAL_BOOTSTRAP
latest_bar_end     = Historical Watermark
```

Snapshot 包含：

```text
Runtime State
Streaming Phase
Market Session State
Data State
Bar
Indicator
Factor
Next Market Open
```

## 14.2 Live Observation

每根正式闭合的实时主 Bar：

```text
只发布一次正式 Observation
```

必须验证：

```text
Observation Bar Identity 唯一
Observation 时间严格递增
Indicator Snapshot 对应该 Bar
Factor Snapshot 不晚于该 Bar
```

## 14.3 Publisher

正常验收负载下要求：

```text
observation_drop_count = 0
```

如果发生 Drop：

```text
Acceptance = FAIL
reason = OBSERVATION_DROPPED_UNDER_ACCEPTANCE_LOAD
```

虽然生产设计允许慢 Sink 丢弃旧 Snapshot，但标准验收负载不应触发丢弃。

---

# 十五、Health 验收

## 非交易 Session

```text
PRE_OPEN
BREAK
POST_CLOSE
CLOSED_DAY
```

没有新数据时：

```text
Data State = IDLE
stale = false
```

## 交易 Session

在正常接收实时 Bar 时：

```text
Market = OPEN
Data = LIVE
stale = false
```

如果超过：

```text
next_expected_bar_end + grace
```

没有数据：

```text
Data = STALE
```

真实验收过程中出现 STALE，应判定：

```text
BLOCKED
```

还是：

```text
FAIL
```

需要根据连接状态区分：

```text
Source disconnected / provider no data
→ BLOCKED

Source 有数据但 Runtime 丢失或未处理
→ FAIL
```

---

# 十六、停止和资源清理验收

Runner 必须在 `finally` 中执行：

```python
engine.stop()
engine.close()
```

无论成功、失败或 KeyboardInterrupt。

停止后断言：

```text
active subscriptions     = 0
streaming worker alive   = false
historical worker child  = 0
observation publisher    = stopped
pending publisher items  = 0
runtime state            = STOPPED / CLOSED
```

进程级检查：

```python
threading.enumerate()
multiprocessing.active_children()
```

验收前后比较 OnlyAlpha 创建的线程和子进程。

禁止简单要求整个 Python 进程只剩一个线程，因为 XtQuant SDK 可能拥有自己的线程。应比较：

```text
OnlyAlpha-managed resources before/after
```

---

# 十七、Acceptance Evidence 模型

```python
@dataclass(frozen=True, slots=True)
class OnlyAcceptanceEvidence:
    evidence_id: str
    case_id: str
    category: str

    verdict: OnlyAcceptanceVerdict
    reason_code: str

    started_at: OnlyTimestamp
    completed_at: OnlyTimestamp

    expected: Mapping[str, object]
    actual: Mapping[str, object]

    artifact_paths: tuple[str, ...]
```

类别建议：

```text
ENVIRONMENT
CONFIGURATION
HISTORICAL_WORKER
HISTORICAL_DATA
WATERMARK
CATCH_UP
LIVE_BAR
DERIVED_BAR
INDICATOR
FACTOR
STRATEGY
RISK
SHADOW_EXECUTION
ECONOMIC_ISOLATION
OBSERVATION
HEALTH
SHUTDOWN
```

---

# 十八、总体 Verdict Reducer

总体结果不能由 Runner 随意拼接字符串。

```python
class OnlyAcceptanceVerdictReducer:
    def reduce(
        self,
        evidences: Sequence[OnlyAcceptanceEvidence],
    ) -> OnlyAcceptanceVerdict:
        ...
```

规则：

```text
任何 REQUIRED Evidence = FAIL
→ Overall FAIL

没有 FAIL，但有 REQUIRED Evidence = BLOCKED
→ Overall BLOCKED

没有 FAIL/BLOCKED，但有 REQUIRED Evidence = NOT_EXECUTED
→ Overall NOT_EXECUTED

全部 REQUIRED Evidence = PASS
→ Overall PASS
```

Optional Case 不参与总体 PASS 判定。

---

# 十九、验收产物

每次运行创建独立目录：

```text
user_data/acceptance/paper/
└── paper-acceptance-<UTC>-<run-id>/
    ├── manifest.json
    ├── environment.json
    ├── sanitized_config.json
    ├── lifecycle.jsonl
    ├── inspections.jsonl
    ├── observations.jsonl
    ├── health.jsonl
    ├── orders.jsonl
    ├── reservations.jsonl
    ├── worker/
    │   ├── request.json
    │   ├── result.json
    │   ├── failure.json
    │   ├── stdout.log
    │   └── stderr.log
    ├── assertions.json
    ├── report.md
    └── COMPLETE
```

写入规则：

```text
所有文件先写临时文件
flush
fsync
atomic replace
最后创建 COMPLETE
```

没有 `COMPLETE` 的目录不得作为正式验收结果。

---

# 二十、Manifest

```json
{
  "schema_version": 1,
  "acceptance_scope": "PR5.1_PAPER_READ_ONLY_OBSERVATION",
  "verdict": "PASS",
  "commit_sha": "...",
  "onlyalpha_version": "0.3.3",
  "runtime_mode": "PAPER",
  "execution_capability": "SHADOW",
  "instrument_id": "000001.XSHE",
  "external_bar_type": "1m",
  "internal_bar_type": "3m",
  "historical_protocol": 2,
  "historical_profile": "miniqmt-history-v2",
  "cases": {
    "automated_contract": "PASS",
    "real_historical_snapshot": "PASS",
    "real_live_handoff": "PASS",
    "shutdown": "PASS"
  }
}
```

Manifest 不能只写总体 PASS，必须保留每个 Case 的独立结果。

---

# 二十一、命令设计

## 自动化 Gate

```powershell
uv run python scripts/run_paper_real_acceptance.py `
  --plan examples/acceptance/miniqmt_paper_v2.yaml `
  --case automated `
  --output user_data/acceptance/paper
```

## 任意时间 Historical Snapshot

```powershell
uv run python scripts/run_paper_real_acceptance.py `
  --plan examples/acceptance/miniqmt_paper_v2.yaml `
  --case historical-snapshot `
  --output user_data/acceptance/paper
```

## 交易时间完整 Live Gate

```powershell
uv run python scripts/run_paper_real_acceptance.py `
  --plan examples/acceptance/miniqmt_paper_v2.yaml `
  --case live-handoff `
  --target-live-bars 6 `
  --output user_data/acceptance/paper
```

## 全部可执行 Case

```powershell
uv run python scripts/run_paper_real_acceptance.py `
  --plan examples/acceptance/miniqmt_paper_v2.yaml `
  --case all `
  --output user_data/acceptance/paper
```

如果当前不是 OPEN：

```text
Historical Snapshot = PASS
Live Handoff         = NOT_EXECUTED
Overall              = NOT_EXECUTED
```

不能把 Historical PASS 自动升级成 Overall PASS。

---

# 二十二、自动化测试

## 22.1 Verdict 测试

覆盖：

```text
全部 PASS
一个 FAIL
一个 BLOCKED
一个 NOT_EXECUTED
Optional Case FAIL
```

## 22.2 Evidence Schema

覆盖：

```text
JSON round-trip
Decimal 序列化
Timestamp UTC
Enum 序列化
Artifact 相对路径
敏感字段脱敏
```

## 22.3 Historical 成功

Fake Worker 返回：

```text
50 根合法 1m Bar
```

断言：

```text
Watermark
Historical Observation
MACD Ready
Factor Snapshot
```

## 22.4 Native Abort

Fake Worker 模拟：

```text
process exit without result
stderr contains BSON assertion
```

断言：

```text
BLOCKED
reason = MINIQMT_HISTORICAL_NATIVE_BSON_ABORT
Parent alive
No resource leak
```

## 22.5 Catch-up

构造：

```text
Historical 到 10:20
Buffered Live 包含 10:19、10:20、10:21
```

结果：

```text
10:19 drop
10:20 drop
10:21 accept
```

## 22.6 Live Finalizer

同一分钟多次 Revision：

```text
10:21 revision 0
10:21 revision 1
10:22 revision 0
```

结果：

```text
10:21 只闭合一次
使用 revision 1
```

## 22.7 Shadow Safety

断言：

```text
Risk executed
Reservation created
Shadow suppressed
Reservation released
No Fill
No Position
No Fee
```

## 22.8 Observation

断言：

```text
Historical Observation
Live Observation
唯一 Identity
单调时间
Drop = 0
```

## 22.9 Shutdown

覆盖：

```text
正常停止
Warmup 失败停止
Live 等待期间 KeyboardInterrupt
Pending Bar 停止
Publisher Queue 非空停止
```

全部要求无 OnlyAlpha 资源泄漏。

---

# 二十三、真实验收报告

生成：

```text
docs/reports/
paper_pr5_1_3_real_product_acceptance_<date>.md
```

报告必须区分：

```text
AUTOMATED RESULTS
REAL ENVIRONMENT RESULTS
NOT EXECUTED RESULTS
KNOWN EXTERNAL LIMITATIONS
```

示例：

```text
Automated Contract        : PASS
Any-Time Assembly         : PASS
Historical Isolation      : PASS
Historical Compatibility  : PASS for 000001.SZ / 1m
Historical Snapshot       : PASS
Live Handoff              : PASS
Shadow Safety             : PASS
Economic Isolation        : PASS
Observation               : PASS
Health                    : PASS
Shutdown                  : PASS

PR5.1 Scope Acceptance     : PASS
Production Paper Runtime  : PARTIAL
```

禁止写：

```text
MiniQMT Historical universally supported
Paper Runtime production-ready
Live Runtime completed
```

---

# 二十四、文档状态更新规则

只有真实总体结果为 PASS 后，才修改：

```text
README.md
docs/paper_runtime.md
docs/roadmap.md
AGENTS.md
```

建议状态：

```text
Paper Read-Only Observation:
CURRENT SCOPE ACCEPTED

Supported acceptance profile:
Windows + MiniQMT + 000001.XSHE + 1m/3m + SHADOW

Paper Runtime:
PARTIAL

Missing:
Reconnect
Gap Recovery
Checkpoint/Recovery
Broad MiniQMT compatibility
```

如果真实结果为 BLOCKED 或 NOT_EXECUTED：

```text
不得更新为完成
```

只提交验收基础设施和失败报告。

---

# 二十五、明确非目标

PR5.1.3 不实现：

```text
MiniQMT SDK Native BSON 修复
自动切换可用证券
Streaming Reconnect
Runtime Gap Recovery
Streaming Checkpoint
Simulation Runtime
Live Broker
真实账户同步
A 股 Effective Reference
Web Server
多 Cluster 真实 Paper
多证券真实 Paper
长时间稳定性测试
```

其中断线、Gap Recovery 和恢复进入 PR5.2。

---

# 二十六、建议提交拆分

## Commit 1

```text
Application: Add runtime inspection authority
```

实现：

```text
Runtime Inspection Snapshot
Engine Inspection Service
只读统计接口
```

## Commit 2

```text
Acceptance: Add paper acceptance evidence model
```

实现：

```text
Plan
Evidence
Verdict
Reducer
Redaction
```

## Commit 3

```text
Acceptance: Add paper real-product runner
```

实现：

```text
Preflight
Engine lifecycle
Polling/wait
Evidence collection
Ordered shutdown
```

## Commit 4

```text
Acceptance: Add paper product assertions
```

实现：

```text
Historical
Watermark
Catch-up
Live Bar
Derived Bar
Indicator/Factor
Shadow
Economic Isolation
Observation
Health
Shutdown
```

## Commit 5

```text
Acceptance: Add atomic artifacts and reports
```

实现：

```text
Manifest
JSONL
Markdown Report
COMPLETE marker
```

## Commit 6

```text
Test: Close paper acceptance automation gate
```

实现全部 Fake SDK、失败语义和资源清理测试。

## Commit 7

```text
Docs: Record PR5.1.3 real acceptance
```

只有真实环境执行结束后提交。

---

# 二十七、完整完成标准

只有以下全部满足，PR5.1.3 当前范围才能声明 PASS：

1. 使用当前 `master` 正式代码；
2. Core 和 MiniQMT 插件版本一致；
3. 真实 Runtime Mode 为 PAPER；
4. Execution Capability 为 SHADOW；
5. Broker 未启用；
6. 使用 `000001.XSHE / 000001.SZ`；
7. Historical Protocol 为 v2；
8. Required Historical Worker 成功；
9. Historical Bars 数量满足 Warmup；
10. Historical 数据通过双层校验；
11. Historical Watermark 正确；
12. Historical Observation 存在；
13. Historical Indicator Ready；
14. Historical Factor Snapshot 存在；
15. Live Subscription 先于 Historical Query；
16. Historical/Live 重叠正确去重；
17. 同一 Bar 不重复进入 Pipeline；
18. 真实闭合 1m Bar 至少 6 根；
19. 实时 1m Bar 时间语义正确；
20. Finalizer 每根只闭合一次；
21. 实时内部 3m Bar 至少 2 根；
22. 3m Bar 不跨 Session；
23. 实时 Observation 单调且唯一；
24. LIVE Strategy Intent 至少一个；
25. Market Rule 和 Risk 正式执行；
26. Shadow Execution 正式抑制；
27. 无 Venue Identity；
28. Fill 数量为零；
29. Position 不变化；
30. Cash 不变化；
31. Fee 为零；
32. Settlement 为零；
33. 所有 Reservation 已释放；
34. Observation Drop 为零；
35. 正常休市不标记 STALE；
36. 正常交易期间 Health 不为 STALE；
37. Stop 不伪造 Pending Bar；
38. 所有订阅已取消；
39. Streaming Worker 已停止；
40. Historical Worker 无残留；
41. Observation Publisher 已 Flush；
42. OnlyAlpha 管理线程无泄漏；
43. Artifact 原子完成；
44. Manifest、Assertions 和 Report 一致；
45. 自动化 Gate 全部通过；
46. 真实 Historical Snapshot 通过；
47. 真实 Live Handoff 通过；
48. 真实 Shutdown 通过；
49. 报告没有泄露隐私配置；
50. 文档没有扩大当前产品支持范围。

---

# 二十八、PR5.1.3 完成后的状态

正确状态应为：

```text
Backtest Product                  : CURRENT SCOPE COMPLETE

Paper Any-Time Assembly           : PASS
Paper Historical Isolation        : PASS
Paper Historical v2 on 000001.SZ  : PASS
Paper Historical Observation      : PASS
Paper Live Handoff                : PASS
Paper Shadow Safety               : PASS
Paper Economic Isolation          : PASS
Paper Ordered Shutdown            : PASS

PR5.1 Read-Only Observation Scope : PASS
Production Paper Runtime          : PARTIAL

Streaming Reconnect               : NOT IMPLEMENTED
Gap Recovery                      : NOT IMPLEMENTED
Streaming Recovery                : NOT IMPLEMENTED
Broad MiniQMT Compatibility       : PARTIAL
Live Runtime                      : NOT IMPLEMENTED
```

PR5.1.3 的核心价值不是再增加一批抽象，而是把现有 Paper 能力变成：

```text
有明确合同
有真实证据
有自动判断
有失败分类
有安全边界
有可重复执行方式
```

完成该 PR 后，再进入 PR5.2 Streaming Reconnect and Gap Recovery。
