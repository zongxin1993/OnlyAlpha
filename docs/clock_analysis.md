# Clock 差距与直接时间访问分析

状态：2026-07-13 Clock 实现前基线扫描

## 扫描范围

扫描 `src/`、`tests/`、`examples/` 中的 `datetime.now`、`datetime.utcnow`、
`date.today`、`time.time/time_ns`、`time.monotonic/monotonic_ns` 和 asyncio loop time。

| 位置 | 访问方式 | 用途 | 风险与处理 |
|---|---|---|---|
| `src/onlyalpha/core/clock.py` | `datetime.now(UTC)` | Live 当前时间 | 原实现只有 datetime，无纳秒与 Monotonic；已改为 Clock 白名单内的 `time.time_ns()` 与 `time.monotonic_ns()` |
| `tests/unit/test_clock_event.py` | `datetime.now(UTC)` | Event Bus 测试数据 | 测试结果不依赖该值，但会弱化固定输入原则；改为固定 UTC 时间 |
| `tests/time_model/test_00_no_naive_datetime.py` | 字符串扫描 | 禁止 naive API | 不是运行时访问，无风险 |

生产业务模块、Domain、Event、Runtime、Cluster、Cache 与 Storage 未发现其他直接系统时间读取。
新增 AST 测试只允许 `core/clock.py` 读取系统 Wall/Monotonic 时间。

## 差距

- 原 `OnlyClock` 只有 `now()`，没有 Unix 纳秒、Monotonic、Timer 或关闭协议。
- 原 `OnlyBacktestClock` 只能推进 datetime，无 Timer deadline 语义、结果和确定性重入。
- 缺少 `OnlyVirtualClock`、Timer 模型、失败结果、快照与线程安全 Live scheduler。
- Cluster 上下文直接持有 `OnlyClock`；实际对象可能是 Backtest Clock，策略可下转并推进时间。
- Runtime 停止时没有关闭自己拥有的 Clock。

## 精度决策

ADR-0007 与 `OnlyTimestamp` 已采用 Unix nanoseconds。Clock 继续以 Python `int` 纳秒作为权威值；
不使用 float 转换。Python datetime 只有微秒精度，因此它只是兼容视图：通用转换默认拒绝
sub-microsecond 丢失，Clock 的 `now_utc()` 显式截断显示，但 `timestamp_ns()` 始终保留真值。
