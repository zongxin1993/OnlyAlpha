你现在位于 OnlyAlpha 仓库根目录。

# 任务名称

```text
PR5.1.3b Open-Market Bootstrap and Live Handoff Closure
```

# 一、任务目标

在不扩大产品范围、不绕过正式 `OnlyEngine`、不伪造行情数据的前提下，完整解决当前 **开市期间 Paper Runtime 启动失败和 Live Handoff 无法完成验收**的问题。

本任务必须形成一个完整闭环：

```text
分析真实失败 Artifact
→ 定位开市 Bootstrap 异常
→ 修复 Historical Boundary / Replay / Watermark
→ 修复 Live Gate 时间预算
→ 改进验收失败分类和证据
→ 完成自动化测试
→ 在真实 MiniQMT 开市环境重新执行验收
→ 输出准确产品状态
```

当前时间处于 A 股开市窗口，应优先利用真实行情验证：

```text
OPEN 状态 Historical Bootstrap
Historical → Catch-up → Live Handoff
实时 1m Finalization
实时 1m → 3m Aggregation
LIVE Shadow Intent
有序停止
```

不得只修改代码而不执行当前可执行的真实 Gate。

---

# 二、开始前先审计当前源码

当前基线提交：

```text
028a31b750b8f8b8b8d11520c39afc85dd36aa07
Feat: Paper Real Product Acceptance Report
```

先执行：

```powershell
git status --short
git rev-parse HEAD
```

确认当前源码状态。

重点阅读：

```text
AGENTS.md
README.md

docs/acceptance/paper_real_product_acceptance.md
docs/acceptance/paper_acceptance_artifact_schema.md
docs/reports/paper_pr5_1_3_real_product_acceptance_2026_08_03.md

examples/acceptance/miniqmt_paper_v2.yaml
examples/configs/miniqmt_paper_acceptance.yaml
examples/strategy/acceptance/strategy.py

scripts/run_paper_real_acceptance.py

src/onlyalpha/application/engine_inspection.py
src/onlyalpha/application/runtime_inspection.py

src/onlyalpha/operations/acceptance/
src/onlyalpha/operations/acceptance/paper_runner.py
src/onlyalpha/operations/acceptance/assertions.py
src/onlyalpha/operations/acceptance/models.py
src/onlyalpha/operations/acceptance/verdict.py
src/onlyalpha/operations/acceptance/artifacts.py

src/onlyalpha/runtime/streaming/runtime.py
src/onlyalpha/runtime/streaming/worker.py
src/onlyalpha/runtime/streaming/health.py
src/onlyalpha/runtime/streaming/phase.py

src/onlyalpha/market/session_clock.py
src/onlyalpha/market_data/completed_boundary.py
src/onlyalpha/market_data/watermark.py
src/onlyalpha/market_data/pipeline.py

src/onlyalpha/data/warmup.py

packages/provider/onlyalpha-plugin-miniqmt/
packages/provider/onlyalpha-plugin-miniqmt/src/onlyalpha_plugin_miniqmt/data_source/historical.py
packages/provider/onlyalpha-plugin-miniqmt/src/onlyalpha_plugin_miniqmt/historical_worker/
packages/provider/onlyalpha-plugin-miniqmt/src/onlyalpha_plugin_miniqmt/historical_worker/query.py
packages/provider/onlyalpha-plugin-miniqmt/src/onlyalpha_plugin_miniqmt/historical_worker/validation.py
packages/provider/onlyalpha-plugin-miniqmt/src/onlyalpha_plugin_miniqmt/historical_worker/protocol.py

tests/acceptance/
tests/integration/test_engine_paper_historical_warmup.py
tests/observation/
tests/runtime/
```

事实优先级：

```text
1. 当前源码
2. 当前失败 Artifact
3. 当前测试
4. 正式文档
5. 本提示词
```

如本提示词中的函数名与当前代码不完全一致，保持目标和不变量不变，按当前结构实现。

---

# 三、真实失败证据

必须读取并分析以下 Artifact：

```text
user_data/acceptance/paper/
paper-acceptance-20260804T013617Z-90b86b3a7b1e/
```

重点读取：

```text
manifest.json
environment.json
assertions.json
lifecycle.jsonl
inspections.jsonl
observations.jsonl
health.jsonl
report.md
worker/
```

当前已知事实：

```text
Manifest Verdict                   : FAIL
real_historical_snapshot           : FAIL
stop_with_pending_bar              : PASS
real_live_handoff                  : 未生成
```

Inspection 已知数据：

```text
market_session_state               : OPEN
runtime_state                      : CLOSED
streaming_phase                    : STOPPED

Historical Worker Status           : SUCCESS
Historical Worker bar_count        : 53
Historical Pipeline bar_count      : 45
Historical Observation Count       : 0
Historical Watermark Count         : 1

Worker Last Bar End                : 2026-08-04T01:36:00Z
Watermark Last Bar End             : 2026-08-04T01:36:00Z

bootstrap_suppressed_intent_count  : 45
catch_up_suppressed_intent_count   : 0

received_update_count              : 0
live_observation_count             : 0
live_order_intent_count            : 0
shadow_suppressed_count            : 0

source_connected                   : false
worker_alive                       : false
active subscriptions               : 0
publisher_pending                  : 0
```

这些事实说明：

```text
Historical Worker 本身成功
但正式 Historical Replay 未完整完成
Historical Observation 未发布
正式 Live Collection 未开始
异常后有序 Shutdown 成功
```

必须从 Artifact 中提取真实：

```text
exception_type
exception_message
execution stage
最后成功处理的 Bar
第一根失败或被拒绝的 Bar
```

不得只根据计数猜测根因。

---

# 四、已确认的独立验收缺陷

当前 `paper_runner.py` 的 Live 等待时间使用：

```python
startup_timeout_seconds + live_grace_seconds
```

当前值为：

```text
60 + 10 = 70 秒
```

但验收目标是：

```text
实时闭合 1m Bar >= 6
实时生成 3m Bar >= 2
Live Observation >= 6
```

70 秒不可能稳定完成该目标。

当前执行前 Session 窗口检查与实际等待逻辑使用了不同时间公式，属于确定性缺陷。

本任务必须修复。

---

# 五、第一性原则和冻结不变量

## 5.1 Historical 截止时间只能有一个 Authority

开市启动时必须冻结一次：

```text
bootstrap_observed_at
historical_requested_end
```

该截止时间必须贯穿：

```text
Completed Boundary Resolver
→ Historical Request
→ MiniQMT Worker
→ Worker Validation
→ Parent Validation
→ Historical Replay
→ Historical Watermark
```

禁止在查询过程中重新用新的 `now()` 扩大 Historical 范围。

---

## 5.2 Historical 与实时职责必须明确分离

在启动时：

```text
Historical
负责 <= frozen historical_requested_end

Live Subscription Buffer
负责 > frozen historical_requested_end
```

同一 Bar 不得同时由 Historical 和 Live 两次进入 Pipeline。

---

## 5.3 Provider 返回成功不等于 Pipeline 处理成功

Historical Watermark 必须来自：

```text
最后一根成功进入正式 MarketData Pipeline 的 Historical Bar
```

禁止来自：

```text
Provider 返回列表最后一项
Worker result last_bar_end
未验证的原始数据尾部
```

冻结不变量：

```text
watermark.last_bar_end
=
last_successfully_processed_historical_bar.bar_end
```

---

## 5.4 当前未闭合 Bar 不得进入 Historical Warmup

假设当前时间是 09:36:17：

```text
09:35–09:36
可以是已完成 Bar

09:36–09:37
仍是 Pending Bar
不得进入 Historical Warmup
```

具体边界由正式 `OnlyCompletedBarBoundaryResolver` 决定，不得硬编码当前分钟。

---

## 5.5 Acceptance Runner 只能观察正式产品

Runner 必须继续：

```text
OnlyEngine.initialize()
→ OnlyEngine.start()
→ OnlyEngine.wait()
→ OnlyEngine.stop()
→ OnlyEngine.close()
```

禁止：

```text
直接调用 Runtime
直接调用 Worker
直接塞 Inbound Queue
手工构造 Live Bar
手工调用 Finalizer
手工调用 Strategy
为了通过验收修改证券、周期或目标数量
```

---

## 5.6 真实失败和验收工具失败必须区分

本次产品状态不能在验收 Runner 自身存在错误时直接判定为 Paper Product FAIL。

必须区分：

```text
PRODUCT_CONTRACT_FAILURE
ACCEPTANCE_HARNESS_FAILURE
EXTERNAL_PROVIDER_BLOCKED
NOT_EXECUTED
```

---

# 六、任务一：提取并修复开市 Bootstrap 异常

## 6.1 增加明确执行阶段

Acceptance Runner 增加：

```python
class OnlyAcceptanceExecutionStage(StrEnum):
    PREFLIGHT = "PREFLIGHT"
    ENGINE_ASSEMBLY = "ENGINE_ASSEMBLY"
    ENGINE_INITIALIZE = "ENGINE_INITIALIZE"
    ENGINE_START = "ENGINE_START"
    HISTORICAL_WORKER = "HISTORICAL_WORKER"
    HISTORICAL_PARENT_VALIDATION = "HISTORICAL_PARENT_VALIDATION"
    HISTORICAL_REPLAY = "HISTORICAL_REPLAY"
    HISTORICAL_WATERMARK = "HISTORICAL_WATERMARK"
    HISTORICAL_OBSERVATION = "HISTORICAL_OBSERVATION"
    CATCH_UP = "CATCH_UP"
    LIVE_COLLECTION = "LIVE_COLLECTION"
    LIVE_ASSERTION = "LIVE_ASSERTION"
    SHUTDOWN = "SHUTDOWN"
```

异常 Evidence 必须包含：

```text
execution_stage
exception_type
exception_message
```

不得再把所有 `engine.start()` 异常统一标记为：

```text
HISTORICAL_WORKER
```

---

## 6.2 Historical Request 冻结截止时间

Streaming Runtime 在 Bootstrap 开始时只计算一次：

```python
bootstrap_observed_at = OnlyTimestamp.from_datetime(
    clock.now_utc()
)

historical_requested_end = boundary_resolver.latest_completed_bar_end(
    calendar=calendar,
    bar_type=external_bar_type,
    observed_at=bootstrap_observed_at,
)
```

此后不得重新计算。

Historical Request 和 Warmup Result 必须保留：

```text
requested_start
requested_end
bootstrap_observed_at
```

---

## 6.3 Worker 严格执行请求边界

MiniQMT Worker 在标准化供应商数据后，必须验证每根 Bar：

```python
bar.bar_end <= request.end_time
```

同时验证：

```text
bar.bar_start < bar.bar_end
bar duration == requested period
bar timestamps strictly increase
bar identity unique
```

对于超出请求边界的数据：

优先方案：

```text
明确过滤掉
记录 provider_out_of_range_count
记录 provider_last_raw_bar_end
记录 accepted_last_bar_end
```

如果当前 Historical 合同要求 Provider 必须严格遵守请求边界，也可以 Fail Closed：

```text
HISTORICAL_RESULT_EXCEEDS_REQUESTED_BOUNDARY
```

但行为必须明确、可测试、可观测，不能静默接受。

不得依赖 XtQuant 一定严格执行 `end_time`。

---

## 6.4 Parent Process 再次验证

即使 Worker 已经校验，Parent 仍必须验证：

```python
for bar in result.bars:
    if bar.bar_end > request.end_time:
        raise OnlyHistoricalValidationError(
            "HISTORICAL_BAR_EXCEEDS_REQUESTED_BOUNDARY"
        )
```

这是跨进程协议的第二层防线。

Worker Result 增加或明确暴露：

```text
provider_raw_bar_count
accepted_bar_count
rejected_out_of_range_count
requested_end
provider_raw_last_bar_end
accepted_last_bar_end
```

---

## 6.5 Historical Replay 逐根记录处理结果

Historical Replay 不能只统计 Worker Bar 数。

必须记录：

```text
historical_provider_bar_count
historical_replay_attempted_count
historical_processed_bar_count
historical_rejected_bar_count
historical_duplicate_count
historical_last_attempted_bar_end
historical_last_processed_bar_end
historical_first_rejection_reason
```

伪代码：

```python
last_processed_bar: OnlyBar | None = None

for bar in historical_bars:
    replay_attempted_count += 1

    result = market_data_processor.process(...)

    if result is accepted:
        processed_count += 1
        last_processed_bar = result.pipeline_result.base_bar
    else:
        rejected_count += 1
        record rejection reason
```

必须确认当前 Pipeline 返回模型中“成功处理”的准确语义，不得凭 `result is not None` 猜测。

---

## 6.6 Watermark 只能基于成功 Replay

创建 Watermark 前：

```python
if last_processed_bar is None:
    raise OnlyHistoricalValidationError(
        "NO_HISTORICAL_BAR_PROCESSED"
    )
```

Watermark：

```python
OnlyHistoricalWatermark(
    source_id=...,
    instrument_id=...,
    bar_type=...,
    last_bar_start=last_processed_bar.bar_start,
    last_bar_end=last_processed_bar.bar_end,
    data_version=...,
    content_fingerprint=...,
)
```

必须增加断言：

```text
watermark.last_bar_end
=
historical_last_processed_bar_end
```

如果：

```text
provider_last_bar_end
>
processed_last_bar_end
```

必须有清晰 Evidence 说明原因。

---

## 6.7 Historical Observation 发布条件

Historical Observation 只能在：

```text
Historical Replay 成功
Watermark 建立成功
Indicator/Factor 状态已更新
```

之后发布。

必须确保：

```text
historical_observation_count >= 1
latest_observations 非空
observation_source = HISTORICAL_BOOTSTRAP
latest_bar_end = watermark.last_bar_end
```

如果 Observation 发布失败，应明确标记：

```text
execution_stage = HISTORICAL_OBSERVATION
```

---

# 七、任务二：修复 Live Gate 时间预算

## 7.1 独立 Live Collection Timeout

实现单一权威函数：

```python
@staticmethod
def _live_collection_timeout_seconds(
    plan: OnlyPaperAcceptancePlan,
) -> int:
    external_required_seconds = (
        plan.target_live_closed_bars
        * plan.external_bar_step_minutes
        * 60
    )

    derived_required_seconds = (
        plan.target_live_derived_bars
        * plan.derived_bar_step_minutes
        * 60
    )

    alignment_allowance_seconds = (
        plan.external_bar_step_minutes * 60
    )

    return (
        max(
            external_required_seconds,
            derived_required_seconds,
        )
        + alignment_allowance_seconds
        + plan.live_grace_seconds
    )
```

当前冻结 Profile 应计算为：

```text
external requirement = 6 × 1m = 360 秒
derived requirement  = 2 × 3m = 360 秒
alignment allowance  = 60 秒
grace                = 10 秒

collection timeout   = 430 秒
```

不得再使用：

```python
startup_timeout_seconds + live_grace_seconds
```

作为实时采集窗口。

---

## 7.2 Session Required Window 与实际等待统一

实现：

```python
@classmethod
def _required_live_window_seconds(
    cls,
    plan: OnlyPaperAcceptancePlan,
) -> int:
    return (
        plan.startup_timeout_seconds
        + cls._live_collection_timeout_seconds(plan)
        + plan.shutdown_timeout_seconds
    )
```

当前约：

```text
60 + 430 + 15 = 505 秒
```

执行前窗口检查和实际运行必须复用同一个 Authority。

---

## 7.3 Live Collection 等待逻辑

进入正式 LIVE 后记录基线：

```text
before_live inspection
live_collection_started_at
```

循环等待：

```text
closed external delta >= 6
derived internal delta >= 2
live observation delta >= 6
```

每次循环不得高频写大量 Artifact，但应定期或状态变化时记录 Inspection。

达到目标立即停止等待。

超过 Collection Timeout 时，不得直接统一写：

```text
LIVE_HANDOFF_VIOLATED
```

而应生成：

```text
LIVE_COLLECTION_TIMEOUT
```

actual 至少包含：

```text
elapsed_seconds
collection_timeout_seconds

received_update_delta
closed_external_bar_delta
derived_internal_bar_delta
live_observation_delta

source_connected
worker_alive
market_session_state
data_state

last_received_at
last_closed_bar_end
next_expected_bar_end
```

---

## 7.4 超时结果分类

按照真实事实分类：

```text
市场已离开 OPEN
→ NOT_EXECUTED 或明确 SESSION_ENDED_DURING_GATE
  具体按当前合同合理实现

Source 断开
→ BLOCKED / PROVIDER_DISCONNECTED

OPEN 期间 received_update_delta = 0
且 Provider/SDK 无数据
→ BLOCKED / PROVIDER_NO_LIVE_DATA

received_update_delta > 0
但 closed_external_bar_delta = 0
→ FAIL / LIVE_FINALIZER_NOT_ADVANCING

closed Bar 有增长
但 Observation 不增长
→ FAIL / LIVE_OBSERVATION_NOT_ADVANCING

目标 Bar 达到
但 Shadow/Reservation 不符合合同
→ FAIL / LIVE_SHADOW_CONTRACT_VIOLATED
```

不要把外部数据源阻断和 OnlyAlpha 内部处理缺陷混为一个错误。

---

# 八、任务三：完善开市验收 Inspection

`OnlyStreamingRuntimeInspectionSnapshot` 增加必要的只读字段：

```text
bootstrap_observed_at
historical_requested_end

historical_provider_bar_count
historical_replay_attempted_count
historical_processed_bar_count
historical_rejected_bar_count
historical_duplicate_count

historical_provider_last_bar_end
historical_last_attempted_bar_end
historical_last_processed_bar_end
historical_watermark_last_bar_end
historical_first_rejection_reason

last_received_at
last_closed_bar_end
next_expected_bar_end
```

保持：

```python
@dataclass(frozen=True, slots=True)
```

不得暴露：

```text
Runtime Manager
Queue 对象
Worker 对象
Strategy 对象
可变内部容器
```

---

# 九、任务四：修正验收 Case 归属

当前 Live Gate 在启动失败时，Manifest 只出现：

```text
real_historical_snapshot = FAIL
```

这会掩盖“这是执行 Live Handoff 时发生的启动失败”。

当用户选择：

```text
--case live-handoff
```

则：

```text
Preflight/Bootstrap 失败
```

仍应在 Evidence 中记录：

```text
requested_case = REAL_LIVE_HANDOFF
execution_stage = HISTORICAL_REPLAY 或具体阶段
```

可以保留 Historical 子证据，但总体 Case 必须让人看出：

```text
Live Handoff 未进入
因为前置 Bootstrap 失败
```

建议 Manifest 包含：

```text
real_live_handoff = FAIL
```

或：

```text
real_live_handoff = BLOCKED
```

并在 reason 中保留真实前置阶段。

---

# 十、任务五：改进 Shutdown Case 命名

当前 `STOP_WITH_PENDING_BAR` Evidence 实际只验证：

```text
Runtime CLOSED
Streaming Phase STOPPED
Worker stopped
Subscriptions = 0
Publisher pending = 0
```

它并未证明停止时确实存在 Pending Bar，也未证明 Stop 没有伪闭合该 Bar。

本任务中执行以下合理方案之一：

## 推荐方案

将当前通用 Case 重命名为：

```text
ORDERED_SHUTDOWN
```

另外保留专门自动化 Case：

```text
STOP_WITH_PENDING_BAR
```

该自动化 Case 必须明确断言：

```text
停止前存在 Pending Bar
停止后 closed_external_bar_count 不增加
停止后 live_observation_count 不增加
Pending Bar Identity 未发布
```

不得让 Case 名称超过实际证据范围。

---

# 十一、任务六：Artifact 证据关联

当前 Evidence 的：

```json
"artifact_paths": []
```

应补齐相对路径。

至少：

```text
Historical Worker
→ worker/request.json
→ worker/result.json
→ worker/failure.json（如存在）

Historical Replay
→ inspections.jsonl
→ observations.jsonl

Live Collection
→ inspections.jsonl
→ observations.jsonl
→ health.jsonl

Economic Isolation
→ inspections.jsonl
→ orders.jsonl
→ reservations.jsonl

Shutdown
→ lifecycle.jsonl
→ inspections.jsonl
→ health.jsonl
```

只能使用相对路径，不得泄露绝对用户路径。

---

# 十二、自动化测试要求

## 12.1 Historical Boundary

覆盖：

```text
请求截止 09:28
Provider 原始数据返回到 09:36
Worker 输出不得包含 > 09:28 的 Bar
```

断言：

```text
provider_raw_count > accepted_count
rejected_out_of_range_count 正确
accepted_last_bar_end <= requested_end
```

---

## 12.2 Parent 双层校验

构造 Worker 错误返回超界 Bar：

```text
Parent 必须 Fail Closed
reason = HISTORICAL_BAR_EXCEEDS_REQUESTED_BOUNDARY
```

---

## 12.3 Watermark Authority

构造：

```text
Provider 返回 53 根
Pipeline 只成功处理 45 根
```

断言：

```text
Watermark 指向第 45 根成功处理 Bar
不是第 53 根 Provider Bar
```

---

## 12.4 Historical Observation

断言：

```text
Watermark 建立后发布 Historical Observation
Observation latest_bar_end = watermark.last_bar_end
```

---

## 12.5 Live Timeout

冻结 Profile：

```text
6 根 1m
2 根 3m
```

断言：

```text
live collection timeout >= 430 秒
required session window >= 505 秒
```

---

## 12.6 不得使用 Startup Timeout 代替 Collection Timeout

增加架构或行为测试，确保：

```text
70 秒到达时 Runner 不会因为目标 Bar 尚未满足而提前结束
```

---

## 12.7 完整 Fake Live 推进

使用可控 Clock 和 Fake Provider：

```text
进入 LIVE
→ 推进 6 个 1m 边界
→ 形成 6 根外部闭合 Bar
→ 形成 2 根内部 3m Bar
→ 产生 Live Observation
→ 产生 LIVE Intent
→ Shadow Suppressed
→ Reservation Released
→ Gate PASS
```

---

## 12.8 PRE_OPEN

当 Session 为 PRE_OPEN：

```text
Live Gate = NOT_EXECUTED
Engine 不启动
MiniQMT 不连接
```

---

## 12.9 OPEN Bootstrap

构造 OPEN 启动：

```text
Historical 请求截止冻结
Provider 在查询中继续产生新 Bar
Historical 只处理截止前 Bar
新 Bar 由 Catch-up/Live 负责
```

---

## 12.10 Failure Stage

分别模拟：

```text
Worker failure
Parent validation failure
Replay failure
Observation failure
Live collection timeout
Shutdown failure
```

断言 Evidence 中 `execution_stage` 准确。

---

# 十三、测试命令

至少执行：

```powershell
uv run ruff check src tests examples packages scripts
uv run ruff format --check src tests examples packages scripts
uv run mypy src/onlyalpha
```

Acceptance：

```powershell
uv run pytest tests/acceptance -q
```

Streaming/Historical：

```powershell
uv run pytest `
  tests/integration/test_engine_paper_historical_warmup.py `
  tests/observation/test_observation_authority.py `
  tests/runtime/test_streaming_health.py `
  -q
```

MiniQMT：

```powershell
uv run pytest `
  packages/provider/onlyalpha-plugin-miniqmt/tests/test_historical.py `
  packages/provider/onlyalpha-plugin-miniqmt/tests/test_historical_worker.py `
  packages/provider/onlyalpha-plugin-miniqmt/tests/test_live_data.py `
  -q
```

随后执行当前仓库规定的完整离线 Gate。

不得通过删除测试、降低目标 Bar 数、跳过失败 Case 或放宽断言完成任务。

---

# 十四、真实开市验证顺序

代码和快速测试通过后，当前仍处于有效 OPEN Session 且剩余窗口足够时，立即执行。

## 14.1 OPEN Historical Snapshot

```powershell
uv run python scripts/run_paper_real_acceptance.py `
  --plan examples/acceptance/miniqmt_paper_v2.yaml `
  --case historical-snapshot `
  --output user_data/acceptance/paper
```

该次与关市 Historical Gate 的目标不同，必须证明：

```text
Market Session                    = OPEN
Historical Requested End          冻结且合法
Provider 超界数据                 不进入正式 Historical
Historical Replay                 完整成功或拒绝有明确原因
Historical Watermark              = Last Processed Bar
Historical Observation            >= 1
MACD Ready                        true
Required Factor                   present
Runtime Final State               CLOSED
```

---

## 14.2 Open-Market Live Handoff

OPEN Historical 通过后执行：

```powershell
uv run python scripts/run_paper_real_acceptance.py `
  --plan examples/acceptance/miniqmt_paper_v2.yaml `
  --case live-handoff `
  --target-live-bars 6 `
  --output user_data/acceptance/paper
```

必须取得：

```text
Historical Worker                PASS
Historical Replay                PASS
Historical Observation           PASS

Historical → Catch-up            PASS
Catch-up Duplicate               0 或有明确合法统计
First Live Bar                   未丢失

Live Closed External 1m          >= 6
Live Derived Internal 3m         >= 2
Live Observations                >= 6

LIVE Strategy Intent             >= 1
Risk Audit                       >= 1
Shadow Suppression               >= 1

Reservation Created              >= 1
Reservation Released             >= Created
Open Reservations                = 0

External Order ID                = 0
Fill                             = 0
Position Mutation                = 0
Cash Mutation                    = 0
Fee                              = 0
Settlement                       = 0

Observation Drop                 = 0
Market Session                   = OPEN
Data State                       != STALE
Source Connected during run      = true
Worker Alive during run          = true

Active Subscription after stop   = 0
Worker Alive after stop          = false
Publisher Pending after stop     = 0
Runtime Final State              = CLOSED
```

---

# 十五、市场窗口不足时的处理

如果代码修复完成时当前已不是 OPEN，或者剩余 Session 时间不足：

```text
不得缩短目标 Bar 数
不得切换证券
不得人工注入行情
不得修改 Clock 冒充真实结果
```

应：

```text
完成所有代码和自动化测试
执行当前仍可执行的 OPEN Historical 或 Closed Historical Gate
将 Real Live Handoff 标记为 NOT_EXECUTED
reason = MARKET_SESSION_NOT_OPEN 或 INSUFFICIENT_LIVE_WINDOW
```

不能将其写为 PASS。

---

# 十六、明确非目标

本任务不实现：

```text
Streaming Reconnect
Gap Recovery
Streaming Checkpoint/Recovery
MiniQMT 广泛证券兼容矩阵
Simulation Runtime
Live Broker
账户同步
仓位同步
A 股 Effective Reference
Web
Research Workflow
```

不得借本任务大范围重构其他组件。

---

# 十七、建议提交拆分

## Commit 1

```text
Fix: Freeze open-market historical boundary
```

包含：

```text
Frozen requested end
Worker range enforcement
Parent range validation
```

## Commit 2

```text
Fix: Build historical watermark from processed Bars
```

包含：

```text
Replay metrics
Last processed Bar
Watermark authority
Historical Observation consistency
```

## Commit 3

```text
Fix: Correct Paper live acceptance timing
```

包含：

```text
Live collection timeout
Required session window
Timeout classification
```

## Commit 4

```text
Acceptance: Add execution stages and evidence links
```

包含：

```text
Failure stage
Case attribution
Artifact paths
Ordered shutdown naming
```

## Commit 5

```text
Test: Close open-market Paper handoff contracts
```

包含全部自动化回归。

## Commit 6

```text
Docs: Record open-market Paper acceptance result
```

只在真实执行完成后提交。

---

# 十八、完成标准

只有以下全部满足，本任务才可以声明完成：

1. 已读取并解释失败 Artifact 的真实异常；
2. 不再将所有启动异常错误归类为 Historical Worker；
3. Historical Request 截止时间在 Bootstrap 开始时冻结；
4. Worker 不输出超出 requested end 的正式 Bar；
5. Parent 对 Worker Result 再次验证；
6. Provider Raw Count 与 Accepted Count 可观察；
7. Historical Replay Attempted/Processed/Rejected 可观察；
8. Historical Watermark 来自最后成功处理 Bar；
9. Watermark 不再来自 Provider 尾部；
10. Historical Observation 的 Bar End 等于 Watermark；
11. OPEN 状态 Historical Snapshot 可以成功；
12. Live Collection Timeout 不再是 70 秒；
13. 当前冻结 Profile Collection Timeout 不少于约 430 秒；
14. Session Required Window 与实际运行预算一致；
15. Live Timeout 有独立 reason code；
16. 外部 Provider 无数据与内部处理失败正确区分；
17. Live Gate Case 能准确表达前置 Bootstrap 失败；
18. 通用 Shutdown Case 不再冒充 Pending Bar 行为；
19. Evidence 包含相对 Artifact Paths；
20. 自动化 Acceptance 测试全部通过；
21. Historical/Streaming/MiniQMT 相关测试全部通过；
22. Ruff、Format、Mypy 通过；
23. 完整离线 Gate 不回归；
24. 当前市场窗口允许时完成真实 OPEN Historical Gate；
25. 当前市场窗口允许时完成真实 Live Handoff Gate；
26. 未达到真实条件的 Case 标记为 NOT_EXECUTED，不得伪造 PASS；
27. Artifact 不泄露账号、绝对用户目录或认证信息；
28. Backtest Determinism 不回归；
29. Paper 经济状态保持不变；
30. 停止后无 OnlyAlpha 管理资源泄漏。

---

# 十九、最终报告要求

完成后输出：

## 1. 原始失败根因

说明：

```text
为什么 Worker SUCCESS 但 Pipeline 只处理 45/53
为什么 Historical Observation 为 0
异常实际发生在哪个 execution stage
```

不得只写“修复历史问题”。

## 2. Historical Boundary

列出：

```text
bootstrap_observed_at
requested_end
provider_raw_last_bar_end
accepted_last_bar_end
processed_last_bar_end
watermark_last_bar_end
```

说明各自 Authority。

## 3. Live Timing

列出：

```text
旧等待时间
新等待时间
Session Required Window
实际 Live Collection Elapsed
```

## 4. 修改文件

逐项列出新增、修改、删除文件。

## 5. 自动化结果

列出真实命令和真实结果。

## 6. 真实环境结果

分别报告：

```text
OPEN Historical Snapshot
Open-Market Live Handoff
Economic Isolation
Ordered Shutdown
```

未执行必须写 `NOT_EXECUTED`。

## 7. 产品状态

严格使用：

```text
Paper Closed-Market Historical Path : PASS
Paper Open-Market Historical Path   : PASS / FAIL / BLOCKED / NOT_EXECUTED
Paper Real Live Handoff             : PASS / FAIL / BLOCKED / NOT_EXECUTED
PR5.1 Current Scope                 : 对应真实总体结果
Production Paper Runtime            : PARTIAL
```

即使本任务通过，也不得把 Production Paper Runtime 标记为完成，因为 Reconnect、Gap Recovery 和 Streaming Recovery 仍未实现。
