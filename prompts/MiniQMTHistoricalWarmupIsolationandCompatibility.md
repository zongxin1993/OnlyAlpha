你现在位于 OnlyAlpha 仓库根目录。

仓库：

```text
https://github.com/zongxin1993/OnlyAlpha
```

任务名称：

```text
PR5.1.1 MiniQMT Historical Warmup Isolation and Compatibility
```

当前基线提交应包含：

```text
Feat: PaperRead-OnlyMarketObservation
```

但必须先检查当前 `master` 最新提交，不能假设仓库仍停留在某个固定 SHA。

---

# 一、任务背景

当前 Paper Read-Only Market Observation 已经实现并真实验证了部分实时链路：

```text
MiniQMT 实时 1m 订阅
→ Runtime 有界队列
→ 单线程处理
→ Live Bar Finalizer
→ 1m Closed Bar
→ 3m Internal Aggregation
→ Indicator / Factor / Strategy
→ Shadow Execution
```

已取得真实证据：

```text
实时 1m Closed Bar 可连续进入正式 Runtime
同一分钟重复 Callback 不重复驱动 Pipeline
1m → 3m 聚合可工作
MiniQMT Callback 只负责标准化和入队
Paper Shadow Execution 不产生 Fill、Position、Fee、Settlement
```

但正式启动要求的 MiniQMT Historical Warmup 未通过。

当前默认 MiniQMT 客户端执行真实历史 1m 查询时，在 XtQuant 原生 BSON 层直接终止进程：

```text
Assertion failed: u < 1000000
...\libs\thirdparty\bson\src\bsonobj.cpp, line 1388
```

该错误发生在 C++ 原生层，可能调用 `abort()`，因此：

```text
Python try/except 无法捕获
线程隔离无效
finally 和 Runtime 清理可能无法执行
整个 OnlyAlpha 主进程会被终止
```

正式 Runtime 已恢复为启动时强制执行 Historical Warmup，不允许使用不能正式回放历史 Bar 的：

```text
subscribe_quote(count=...)
```

旁路替代 Warmup。

因此当前状态必须保持：

```text
PR5.1 Product Acceptance : FAILED / BLOCKED
```

本任务完成前不得：

```text
跳过 Historical Warmup
把 Warmup 改成 Optional 以通过验收
使用实时订阅历史旁路冒充正式历史查询
声明 Paper 产品链完成
更新 README/Roadmap/AGENTS 为 Paper 已完成
```

---

# 二、任务核心目标

本任务不是简单修改一次 `get_market_data_ex()` 参数。

目标是建立统一的进程级历史数据隔离边界：

```text
OnlyAlpha 主进程
→ Historical Warmup Port
→ MiniQMT Isolated Client
→ 独立 Python Worker Process
→ XtQuant Native Historical API
```

实现以下结果：

```text
XtQuant 正常返回
→ 标准化历史 Bar
→ 校验
→ 写入原子结果
→ 父进程读取
→ 正式 MarketData Pipeline Warmup

XtQuant Python 异常
→ Worker 返回结构化错误
→ 主进程 Fail Closed

XtQuant Native Abort
→ 仅 Worker 进程退出
→ OnlyAlpha 主进程继续存活
→ 转换为 WORKER_ABORTED
→ Runtime Fail Closed

XtQuant 查询超时
→ 终止 Worker
→ 返回 TIMEOUT
→ Runtime Fail Closed
```

最终要把：

```text
不可捕获的第三方原生崩溃
```

转化为：

```text
可诊断
可测试
可监控
可替换
可安全失败
```

的 Historical Warmup 领域结果。

---

# 三、开始前必须重新审计

先阅读当前仓库实际实现，不得只依据本提示词创建重复架构。

重点审计：

```text
AGENTS.md
README.md
docs/roadmap.md
docs/paper_runtime.md
docs/reports/

src/onlyalpha/engine/
src/onlyalpha/runtime/
src/onlyalpha/runtime/paper/
src/onlyalpha/runtime/streaming/
src/onlyalpha/runtime/backtest/

src/onlyalpha/data/
src/onlyalpha/market_data/
src/onlyalpha/cache/historical/
src/onlyalpha/indicator/
src/onlyalpha/cluster/

packages/provider/onlyalpha-plugin-miniqmt/
scripts/
tests/
```

重点确认：

```text
当前 Paper Runtime 的 Historical Warmup 调用路径
当前 MiniQMT Historical Provider
当前 load_bars / get_market_data_ex / download_history_data 使用方式
当前 Historical Cache 接口
当前 OnlyHistoricalBarRequest 和 OnlyHistoricalDataStream
当前数据版本、内容 Fingerprint 和 Cache Manifest
当前 Paper Bootstrap 状态
当前 BOOTSTRAP / CATCH_UP / LIVE 模型
当前用户数据目录结构
当前 MiniQMT Config 和 userdata_mini 路径处理
当前测试 Marker 和 MiniQMT Local Lane
```

事实优先级：

```text
1. 当前源码
2. 当前测试
3. ADR
4. AGENTS.md
5. README / Roadmap
6. 本提示词
```

如本提示词类名和实际仓库不一致，应保持架构目标不变，按当前项目命名和组织调整。

---

# 四、架构原则

## 1. 进程隔离是强制要求

禁止仅使用：

```text
try/except
threading.Thread
concurrent.futures.ThreadPoolExecutor
multiprocessing 中继承主 Runtime 对象的隐式 fork 方案
```

原生 assertion 会终止整个进程，线程无法隔离。

必须使用明确的独立解释器进程，推荐：

```python
subprocess.Popen(
    [
        sys.executable,
        "-m",
        "onlyalpha_plugin_miniqmt.historical_worker.worker",
        "--request",
        str(request_path),
    ],
    ...
)
```

要求：

```text
Worker 独立导入 xtquant
Worker 不继承 Runtime、Clock、EventBus、Cluster、Callback
Worker 只处理一个历史请求
Worker 完成后立即退出
```

首期不要实现常驻 Historical Worker Service。

短生命周期进程优点：

```text
隔离彻底
状态干净
容易复现
容易记录 stdout/stderr
容易识别退出码
不会污染主 Runtime
```

---

## 2. Core 不得依赖 MiniQMT

Core 只能定义通用：

```text
Historical Warmup Request
Historical Warmup Result
Historical Warmup Port
Historical Warmup Error
```

Core 禁止导入：

```text
xtquant
pandas
MiniQMT Config
BSON
券商客户端路径
```

MiniQMT 插件负责：

```text
XtQuant 调用
Symbol 映射
Compatibility Profile
Worker 进程
传输模型
原始数据标准化
```

---

## 3. 失败必须 Fail Closed

PR5.1 当前产品要求：

```text
warmup_policy = REQUIRED
```

Historical Warmup 失败时必须：

```text
Paper Runtime → FAILED
不进入 CATCH_UP
不进入 LIVE
不启动正式实时观察
不继续 Strategy 正式执行
关闭 DataSource 和订阅
关闭 Worker、Clock 和 EventBus
```

进程隔离是为了安全失败，不是为了忽略失败。

---

## 4. 不改变业务语义

本任务不得修改：

```text
Indicator 计算逻辑
Factor 逻辑
Strategy 逻辑
Shadow Execution 语义
Risk / Order 语义
Backtest Historical Replay
Virtual Broker
Durable Transaction
Result Fingerprint
A 股 Market Profile
```

---

# 五、通用 Historical Warmup Port

如当前仓库没有等价接口，应在 Streaming Runtime 边界新增。

建议：

```python
class OnlyHistoricalWarmupPort(Protocol):
    def load(
        self,
        request: OnlyHistoricalWarmupRequest,
    ) -> OnlyHistoricalWarmupResult:
        ...
```

请求模型建议：

```python
@dataclass(frozen=True, slots=True)
class OnlyHistoricalWarmupRequest:
    request_id: str
    runtime_id: OnlyRuntimeId

    instrument_id: OnlyInstrumentId
    bar_type: OnlyBarType

    required_bars: int
    end_time: OnlyTimestamp

    data_version: str
    adjustment_type: OnlyAdjustmentType

    timeout_seconds: int
```

校验：

```text
request_id 非空
required_bars > 0
timeout_seconds > 0
end_time 为 UTC
bar_type 为支持周期
adjustment_type 明确
```

状态枚举建议：

```python
class OnlyHistoricalWarmupStatus(StrEnum):
    SUCCESS = "SUCCESS"
    INVALID_REQUEST = "INVALID_REQUEST"
    PROVIDER_UNAVAILABLE = "PROVIDER_UNAVAILABLE"
    IMPORT_FAILED = "IMPORT_FAILED"
    DOWNLOAD_FAILED = "DOWNLOAD_FAILED"
    QUERY_FAILED = "QUERY_FAILED"
    EMPTY_RESULT = "EMPTY_RESULT"
    INVALID_DATA = "INVALID_DATA"
    WORKER_ABORTED = "WORKER_ABORTED"
    TIMEOUT = "TIMEOUT"
    PROTOCOL_ERROR = "PROTOCOL_ERROR"
```

结果模型建议：

```python
@dataclass(frozen=True, slots=True)
class OnlyHistoricalWarmupResult:
    status: OnlyHistoricalWarmupStatus

    bars: tuple[OnlyBar, ...]

    request_fingerprint: str
    content_fingerprint: str | None

    first_bar_end: OnlyTimestamp | None
    last_bar_end: OnlyTimestamp | None

    provider: str
    provider_version: str | None
    compatibility_profile_id: str | None

    diagnostic: OnlyHistoricalWarmupDiagnostic | None
```

诊断模型至少包括：

```python
@dataclass(frozen=True, slots=True)
class OnlyHistoricalWarmupDiagnostic:
    code: str
    message: str

    worker_exit_code: int | None
    stderr_tail: str | None
    stdout_tail: str | None

    request_fingerprint: str
    working_directory: str | None

    provider_version: str | None
    compatibility_profile_id: str | None
```

不能把整段无限日志直接装入结果，限制 Tail 大小。

---

# 六、MiniQMT 插件目录设计

按当前仓库组织调整，建议新增：

```text
packages/provider/onlyalpha-plugin-miniqmt/
└── src/onlyalpha_plugin_miniqmt/
    └── historical_worker/
        ├── __init__.py
        ├── models.py
        ├── protocol.py
        ├── client.py
        ├── worker.py
        ├── query.py
        ├── validation.py
        ├── compatibility.py
        └── exit_codes.py
```

职责：

## `models.py`

插件内部传输 Request/Result Record。

禁止直接复用不可序列化 Runtime 对象。

## `protocol.py`

负责：

```text
JSON 协议版本
Request 文件
Result Manifest
Bars Transport 文件
Failure 文件
Fingerprint
原子写入
```

## `client.py`

主进程侧：

```text
创建工作目录
写 request.json
启动 Worker
重定向 stdout/stderr
等待退出
处理超时
识别 Native Abort
读取并校验结果
转换为 OnlyHistoricalWarmupResult
```

## `worker.py`

子进程入口：

```text
读取 Request
延迟导入 xtquant
连接默认 MiniQMT
执行查询
校验原始数据
写结果
返回稳定退出码
```

## `query.py`

封装：

```text
download_history_data
get_market_data_ex
参数组合
结果提取
```

## `validation.py`

两级校验的 Worker 侧部分。

## `compatibility.py`

定义显式 Compatibility Profile。

## `exit_codes.py`

定义稳定退出码。

---

# 七、父子进程协议

## 1. 每次请求独立工作目录

建议：

```text
<user_data_root>/
└── runtime_state/
    └── <runtime_id>/
        └── warmup/
            └── request-<uuid>/
                ├── request.json
                ├── stdout.log
                ├── stderr.log
                ├── result.json
                ├── bars.jsonl
                └── failure.json
```

不要写入仓库目录。

测试使用：

```text
tmp_path
```

不要多个请求共享同一工作目录。

---

## 2. Request JSON

建议协议：

```json
{
  "protocol_version": 1,
  "request_id": "warmup-001",

  "userdata_mini_path": "C:/国金证券QMT交易端/userdata_mini",

  "instrument_id": "600000.XSHG",
  "xt_symbol": "600000.SH",
  "period": "1m",

  "required_bars": 50,
  "end_time": "2026-08-03T02:00:00Z",

  "fields": [
    "time",
    "open",
    "high",
    "low",
    "close",
    "volume"
  ],

  "adjustment": "none",
  "fill_data": false,

  "price_precision": 2,
  "quantity_precision": 0,

  "compatibility_profile_id": "miniqmt-history-v1"
}
```

要求：

```text
全部为简单 JSON 类型
路径使用字符串
时间使用 UTC ISO-8601
Decimal 不使用 Float，使用字符串
不传 pandas 对象
不传 Callback
不传 Runtime 对象
不传 OnlyEngine 对象
```

---

## 3. Bars Transport

建议使用 JSONL，Warmup 数量通常只有几十到几百根。

示例：

```json
{
  "instrument_id": "600000.XSHG",
  "bar_type": "1m",

  "bar_start_ns": 1785722280000000000,
  "bar_end_ns": 1785722340000000000,
  "ts_event_ns": 1785722340000000000,

  "open": "10.25",
  "high": "10.29",
  "low": "10.23",
  "close": "10.27",
  "volume": "183400"
}
```

要求：

```text
价格和数量使用字符串
时间使用 Unix ns
不传 pandas Index
不传 NumPy 类型
不传 XtQuant SDK 对象
```

父进程读取后，再转换为正式：

```text
OnlyBar
OnlyMarketDataInboundUpdate
```

---

## 4. Result Manifest

成功结果至少包含：

```json
{
  "protocol_version": 1,
  "request_id": "warmup-001",

  "status": "SUCCESS",

  "provider": "miniqmt",
  "provider_version": "...",
  "compatibility_profile_id": "miniqmt-history-v1",

  "instrument_id": "600000.XSHG",
  "period": "1m",

  "requested_bars": 50,
  "row_count": 50,

  "first_bar_end_ns": 0,
  "last_bar_end_ns": 0,

  "request_fingerprint": "...",
  "content_fingerprint": "...",
  "bars_file_fingerprint": "..."
}
```

---

## 5. Failure Manifest

能够被 Python 捕获的异常写入：

```json
{
  "protocol_version": 1,
  "request_id": "warmup-001",

  "status": "QUERY_FAILED",
  "code": "MINIQMT_HISTORICAL_QUERY_FAILED",

  "exception_type": "RuntimeError",
  "message": "...",
  "traceback": "...",

  "request_fingerprint": "...",
  "provider_version": "...",
  "compatibility_profile_id": "miniqmt-history-v1"
}
```

限制 traceback 大小，避免无限日志。

Native Abort 可能没有机会写 Failure Manifest，因此父进程必须能仅根据：

```text
退出码
result 文件不存在
stderr 内容
```

识别 Worker Abort。

---

# 八、原子输出

Worker 必须使用临时文件：

```text
.result.json.tmp
.bars.jsonl.tmp
.failure.json.tmp
```

完成写入和 flush 后：

```text
fsync
→ atomic rename
```

父进程只有同时满足以下条件才接受成功：

```text
Worker exit code == 0
result.json 存在
bars.jsonl 存在
协议版本正确
Request Fingerprint 一致
Bars 文件 Fingerprint 一致
Content Fingerprint 一致
数据校验通过
```

半写文件不得视为成功。

Worker Abort 后残留 `.tmp` 文件必须被视为无效。

---

# 九、退出码

定义稳定常量，建议：

```text
0   SUCCESS

10  INVALID_REQUEST
11  SDK_IMPORT_FAILED
12  CLIENT_NOT_READY
13  DOWNLOAD_FAILED
14  QUERY_FAILED
15  EMPTY_RESULT
16  DATA_VALIDATION_FAILED
17  RESULT_SERIALIZATION_FAILED
18  PROTOCOL_ERROR

21  TIMEOUT
22  PROTOCOL_VERSION_MISMATCH
```

Native Abort 通常不由 Worker 正常返回。

父进程将所有非正常退出且没有有效 Failure Manifest 的结果转换为：

```text
WORKER_ABORTED
```

诊断必须保留：

```text
实际 worker_exit_code
stderr tail
stdout tail
request fingerprint
compatibility profile
provider version
userdata_mini path
```

不要把 Native Abort 伪造为普通 `QUERY_FAILED`。

---

# 十、父进程 Isolated Client

建议主流程：

```python
def load(request):
    validate_request(request)

    workdir = create_request_directory(request)

    write_request_atomically(workdir, request)

    process = spawn_worker(
        request_path=workdir / "request.json",
        stdout=workdir / "stdout.log",
        stderr=workdir / "stderr.log",
    )

    exit_status = wait_with_timeout(process)

    if timed_out:
        terminate_then_kill(process)
        return timeout_result(...)

    if exit_status != 0:
        return map_failed_worker(...)

    return read_validate_and_convert_result(...)
```

## 超时流程

```text
wait(timeout)
→ terminate
→ 短等待
→ kill
→ 短等待
→ 返回 TIMEOUT
```

必须确认 Worker 不残留。

## 日志读取

只读取日志尾部，例如：

```text
最后 16KB 或 200 行
```

完整日志保留在工作目录，结果对象只带 Tail。

## 清理策略

成功请求可按配置清理临时 Bars 文件。

失败请求应保留诊断目录。

建议：

```text
成功：可删除临时目录或保留最近 N 次
失败：默认保留
```

不要在自动测试中依赖持久化诊断目录。

---

# 十一、双层数据校验

Worker 和父进程都要校验。

## Worker 校验

目的：

```text
尽早识别 SDK 返回异常
避免写出明显非法结果
```

## Parent 校验

目的：

```text
不信任进程边界外数据
避免半写、篡改或协议不一致
```

至少检查：

## 1. Bar 数量

```text
row_count >= required_bars
```

可查询多于所需数量，最终只保留最后 N 根已闭合 Bar。

## 2. 严格时间递增

```text
bar_end[i] < bar_end[i + 1]
```

不允许相等。

## 3. 唯一键

```text
instrument_id
bar_type
bar_start
```

必须唯一。

## 4. OHLC

```text
high >= open
high >= close
low <= open
low <= close
high >= low
```

## 5. 正数和非负

```text
open/high/low/close > 0
volume >= 0
```

## 6. 时间桶

例如 1m：

```text
bar_end - bar_start == 60 seconds
```

按项目实际 Bar Specification 判断。

## 7. Instrument 一致

不得出现：

```text
其他证券
其他周期
```

## 8. 价格精度

必须使用 Instrument：

```text
price_precision
```

不得继续固定四位。

## 9. 闭合状态

Historical Warmup 只能输出已闭合 Bar。

最后一根不能属于当前仍未完成的时间桶。

边界应由统一 Bar Calendar/Specification 计算，不要使用随意的字符串分钟截断。

## 10. Fingerprint

Content Fingerprint 应基于标准化后的稳定 Transport Records。

不得包含：

```text
临时目录
采集时间
进程 PID
日志路径
```

---

# 十二、Compatibility Profile

## 1. 目的

不同版本的：

```text
XtQuant SDK
券商定制 MiniQMT
MiniQMT 客户端
本地历史数据状态
```

可能对参数组合表现不同。

不要在 Runtime 内散布临时判断。

定义显式 Profile，例如：

```python
@dataclass(frozen=True, slots=True)
class OnlyMiniQmtHistoricalCompatibilityProfile:
    profile_id: str

    download_before_query: bool
    query_mode: OnlyMiniQmtHistoricalQueryMode

    explicit_fields: tuple[str, ...]
    fill_data: bool
    adjustment: str

    overlap_bars: int
    maximum_count: int
```

查询模式：

```python
class OnlyMiniQmtHistoricalQueryMode(StrEnum):
    TIME_RANGE = "TIME_RANGE"
    END_TIME_WITH_COUNT = "END_TIME_WITH_COUNT"
    COUNT_ONLY = "COUNT_ONLY"
```

Profile 必须：

```text
不可变
有唯一 ID
可以序列化
参与 Request Fingerprint
记录在 Result Manifest
```

---

## 2. 正式 Runtime 只使用一个明确 Profile

禁止正式 Runtime 自动执行大量参数盲试：

```text
A abort
→ B abort
→ C abort
```

正式配置应明确：

```yaml
runtime:
  extensions:
    streaming:
      historical_compatibility_profile: miniqmt-history-v1
```

如果 Profile 不存在：

```text
Fail Closed
```

参数矩阵只由诊断工具执行。

---

# 十三、Compatibility 诊断工具

新增：

```text
scripts/diagnose_miniqmt_historical.py
```

示例：

```powershell
uv run python scripts/diagnose_miniqmt_historical.py `
  --userdata-mini "C:\国金证券QMT交易端\userdata_mini" `
  --symbol 600000.SH `
  --period 1m `
  --output .diagnostics/miniqmt-history
```

每个测试 Case 必须启动一个独立 Worker 进程。

不能在同一 Worker 中连续执行多个 Case。

测试矩阵至少包括：

```text
Period:
1m
5m
1d

Count:
1
10
50
100
200

Query Mode:
TIME_RANGE
END_TIME_WITH_COUNT
COUNT_ONLY

Download Before Query:
false
true

Fields:
empty/default
explicit OHLCV

fill_data:
false
true

adjustment:
none
```

为控制组合数量，可以先执行分阶段矩阵：

```text
阶段 1：找到不会 Abort 的基本 Query Mode
阶段 2：测试 Count
阶段 3：测试 Download 和 Fields
阶段 4：测试 fill_data
```

输出报告：

```json
{
  "environment": {
    "userdata_mini_path": "...",
    "xtquant_version": "...",
    "python_version": "...",
    "client_ready": true
  },
  "cases": [
    {
      "case_id": "1m-count50-default",
      "status": "PROCESS_ABORT",
      "worker_exit_code": 3,
      "stderr_tail": "Assertion failed..."
    },
    {
      "case_id": "1m-range-explicit-fields",
      "status": "PASS",
      "row_count": 50,
      "content_fingerprint": "..."
    }
  ]
}
```

Case 状态统一：

```text
PASS
PYTHON_EXCEPTION
PROCESS_ABORT
TIMEOUT
EMPTY_DATA
INVALID_DATA
PROTOCOL_ERROR
```

诊断工具不得自动改写正式 Runtime 配置。

最终由工程人员根据报告明确选择 Profile。

---

# 十四、Historical Cache 集成

优先查询现有 Historical Cache。

流程：

```text
请求 Warmup
→ 查询 Cache Coverage
```

若满足：

```text
provider 匹配
data_version 匹配
adjustment 匹配
compatibility_profile 匹配
覆盖 required_bars
coverage_end 达到所需最后闭合 Bar
fingerprint 有效
```

则：

```text
直接使用 Cache
```

否则：

```text
启动 Isolated Worker
→ 成功
→ 写入 Historical Cache
→ 返回 Warmup Bar
```

不能只因为 Cache 中有足够数量，就忽略数据已经过期。

缓存键至少包括：

```text
instrument_id
bar_type
provider
data_version
adjustment
compatibility_profile_id
```

Worker 失败时不能回退使用过期 Cache，除非当前配置明确允许并且产品文档已定义该语义。PR5.1 默认保持严格 Fail Closed。

---

# 十五、接入 Paper Bootstrap

保持正式启动顺序：

```text
Paper Runtime INITIALIZING
→ BOOTSTRAPPING
→ Warmup Port
→ Isolated MiniQMT Worker
→ Historical Bars
→ MarketData Pipeline
→ Indicator / Factor Warmup
→ Historical Watermark
→ CATCH_UP
→ LIVE
```

PR5.1.1 至少必须完成：

```text
Isolated Worker
可信 Historical Result
结构化失败
Warmup Bar 进入正式 Pipeline
Historical Watermark 可建立
```

完整实时 Catch-up Buffer 可在后续 PR5.1.2 实现，但本任务接口必须支持：

```text
last_historical_bar_end
content_fingerprint
provider_version
compatibility_profile
```

失败路径：

```text
Warmup Failure
→ Runtime FAILED
→ 不进入 CATCH_UP/LIVE
→ 关闭实时订阅
→ 关闭 DataSource
→ 停止 Worker
→ 停止 Clock/EventBus
```

不得仅设置日志后继续运行。

---

# 十六、Native Abort 自动测试

这是本任务最重要的测试之一。

创建测试 Worker 模式：

```python
import os
os.abort()
```

测试断言：

```text
子进程异常退出
父进程测试进程继续存活
结果状态为 WORKER_ABORTED
记录真实退出码
记录 stderr/stdout tail
不存在有效 result.json
Runtime 不进入 RUNNING
无残留 Worker 进程
```

禁止使用生产 `test_mode`。

测试 Worker 行为可通过：

```text
测试模块
Fake Worker Executable
测试依赖注入的 Worker Command Builder
```

实现。

不要在生产配置中添加隐藏测试开关。

---

# 十七、其他自动化测试

## Unit

覆盖：

```text
Request 校验
Request 序列化
Request Fingerprint
Result Manifest
Bars Fingerprint
协议版本校验
退出码映射
超时
terminate/kill
日志 Tail
原子文件
半写文件
缺少结果文件
OHLC 校验
排序校验
重复校验
Bar 数量校验
价格精度
时间桶
Compatibility Profile
Cache Coverage
```

## Worker Contract

使用 Fake XtQuant Shape，覆盖：

```text
正常查询
Import Error
客户端未就绪
Download Python Exception
Query Python Exception
空数据
乱序
重复
非法 OHLC
错误 Instrument
错误 Period
半写后异常
长时间阻塞
```

Fake XtQuant 必须模拟原始 SDK 数据形状，不能直接返回 OnlyBar。

## Runtime Integration

正式链路：

```text
OnlyEngine
→ Paper Runtime
→ Historical Warmup Port
→ Isolated Client
→ Fake Worker Process
→ Historical Bars
→ MarketData Pipeline
→ Indicator Warmup
```

断言：

```text
Bar 按顺序回放
Indicator Samples 正确
Warmup Ready 正确
Watermark 正确
Worker 失败时 Runtime Fail Closed
没有实时旁路
无进程泄漏
无非守护线程泄漏
```

## MiniQMT Local

真实环境执行：

```text
诊断矩阵
→ 选择可用 Profile
→ 正式 Warmup
```

正式验收至少要求：

```text
600000.XSHG / 600000.SH
1m
连续至少 50 根已闭合 Bar
Worker exit code = 0
父进程未崩溃
严格递增
无重复
OHLC 合法
价格精度为 Instrument 精度
Historical Watermark 建立
```

若所有组合仍触发 Native Abort：

```text
Isolation Acceptance : PASS
MiniQMT Compatibility : BLOCKED
Paper Product         : FAILED
```

不得把隔离能力通过写成 Paper 产品通过。

---

# 十八、门禁与兼容性

必须运行：

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

真实 MiniQMT 环境可用时执行：

```powershell
uv run python scripts/diagnose_miniqmt_historical.py ...
uv run python scripts/test_suite.py miniqmt-local
```

必须确认：

```text
Backtest 不回归
Virtual Broker 不回归
MiniQMT Historical 原有离线 Contract 不回归
MiniQMT Live 不回归
Paper Shadow Execution 不回归
Recovery 不回归
Result Fingerprint 不回归
```

---

# 十九、明确非目标

本任务不实现：

```text
Observation Snapshot
Console Observation Sink
JSONL Observation Sink
Observation Drop Policy
Streaming Runtime Health
DEGRADED
自动重连
实时 Gap Recovery
完整 CATCH_UP Buffer
Streaming Runtime 架构最终收口
Simulation Runtime
Live Broker
Account Synchronization
Position Synchronization
A 股 Reference Authority
YAML Schema 2.0
```

如当前源码为完成隔离必须做极少量公共接口调整，可以实施，但不得扩大任务范围。

---

# 二十、建议提交拆分

建议至少拆成：

```text
Data: Define historical warmup port and result contracts

MiniQMT: Add isolated historical worker protocol

MiniQMT: Add worker client, timeout and abort handling

MiniQMT: Add historical compatibility profiles

Tool: Add MiniQMT historical diagnostics matrix

Runtime: Integrate isolated warmup into Paper bootstrap

Cache: Persist validated isolated historical results

Test: Add native abort and worker contract coverage

Docs: Record MiniQMT historical isolation and blocked acceptance
```

不要把所有改动压成一个巨大提交。

---

# 二十一、文档更新

新增或更新：

```text
docs/miniqmt_historical_isolation.md
docs/paper_runtime.md
docs/reports/paper_pr5_1_acceptance_2026_08_03.md
```

必须明确记录：

```text
进程隔离解决的是主进程安全性
不等于修复 XtQuant 原生 Bug
Isolation 通过不等于 Paper 产品通过
Warmup 仍然 REQUIRED
```

README、Roadmap、AGENTS 中不得把 Paper 更新为完成。

可以记录为：

```text
Paper Runtime        : PARTIAL
Live Data Path       : PARTIAL PASS
Shadow Execution     : PASS
Historical Warmup    : BLOCKED
Isolation Boundary   : IMPLEMENTED
Product Acceptance   : FAILED
```

---

# 二十二、完成标准

只有以下全部满足，才能声明 PR5.1.1 实现完成：

1. Core 定义通用 Historical Warmup Port；
2. Core 不依赖 MiniQMT 或 XtQuant；
3. MiniQMT 历史查询运行在独立解释器进程；
4. Worker 每次只处理一个请求；
5. Worker 内延迟导入 XtQuant；
6. 父进程保存 stdout/stderr；
7. 原生 Abort 不会终止 OnlyAlpha 主进程；
8. 原生 Abort 转换为 `WORKER_ABORTED`；
9. Python 异常转换为结构化结果；
10. 超时会 terminate/kill Worker；
11. Worker 不残留；
12. Request 和 Result 有稳定协议版本；
13. Request Fingerprint 可重复；
14. Content Fingerprint 可重复；
15. Worker 使用原子文件输出；
16. 半写文件不会被接受；
17. Worker 和 Parent 均校验历史 Bar；
18. 价格精度使用 Instrument `price_precision`；
19. Historical Bar 全部为已闭合 Bar；
20. Historical Cache 可复用验证后的结果；
21. Cache 不会使用过期 Coverage；
22. Compatibility Profile 明确且不可变；
23. 正式 Runtime 不自动盲试 Profile；
24. 诊断工具每个 Case 使用独立 Worker；
25. `os.abort()` 自动化测试通过；
26. Worker 成功结果可进入正式 MarketData Pipeline；
27. Worker 失败时 Paper Runtime Fail Closed；
28. 不再使用 `subscribe_quote(count=...)` 历史旁路；
29. 不修改 `schema_version`；
30. 不声明 Paper 产品验收通过。

---

# 二十三、最终报告要求

任务完成后输出完整报告。

## 1. 审计结果

说明修改前：

```text
Historical Warmup 调用路径
原生崩溃位置
主进程风险
现有 Cache 和 Bootstrap 行为
```

## 2. 架构说明

说明：

```text
为什么线程不够
为什么使用 subprocess
为什么每个请求一个 Worker
为什么正式 Runtime 不自动盲试参数
```

## 3. 协议

列出：

```text
Request Schema
Result Schema
Failure Schema
Exit Codes
Fingerprint
Atomic Output
```

## 4. 修改文件

逐项列出新增、修改和删除文件。

## 5. 测试结果

列出实际命令和真实结果。

## 6. Native Abort 证明

明确证明：

```text
Worker Abort
父进程仍存活
Runtime Fail Closed
```

## 7. MiniQMT 真实环境结果

列出诊断矩阵摘要：

```text
哪些 Case PASS
哪些 Case PROCESS_ABORT
使用了哪个 Compatibility Profile
正式 1m Warmup 是否通过
```

环境不可用时必须写：

```text
NOT EXECUTED
```

不能写为通过。

## 8. 产品状态

最终必须明确区分：

```text
PR5.1.1 Isolation Implementation
MiniQMT Historical Compatibility
Paper Product Acceptance
```

例如：

```text
Isolation Implementation : PASS
Compatibility             : BLOCKED
Paper Product             : FAILED
```

或真实全部通过后：

```text
Isolation Implementation : PASS
Compatibility             : PASS
Paper Product             : 仍需 PR5.1.2～PR5.1.5
```

以当前源码、实际测试、真实进程退出状态和真实 MiniQMT 结果为准完成任务。
