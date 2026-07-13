# OnlyAlpha Clock 子系统设计、实现与验证任务

## 1. 任务目标

现在开始实现 OnlyAlpha 的 Clock 子系统。

本任务只负责建立统一、确定、可测试的时间来源和定时器基础能力，为后续以下模块提供统一时间语义：

* Live Runtime；
* Paper Runtime；
* Backtest Runtime；
* Research Runtime；
* Event Bus；
* Cluster；
* Bar 聚合；
* 订单超时；
* 撤单超时；
* 策略定时任务；
* 交易时段判断；
* 回测事件推进；
* 日志与审计。

Clock 子系统必须遵循以下核心原则：

```text
系统内部绝对时间统一使用 UTC
市场本地时间由 TradingCalendar 解释
业务代码不得直接读取系统时间
回测时间必须由历史事件确定性推进
相同输入必须得到完全一致的时间行为
```

Clock 负责回答：

> 当前 Runtime 认为“现在”是什么时间。

Trading Calendar 负责回答：

> 这个 UTC 时间属于哪个市场交易日和哪个交易时段。

Clock 不负责保存完整交易日历规则，也不负责 UI 时区显示。

---

# 2. 执行前必须阅读

开始实现前，先阅读：

```text
AGENTS.md
docs/architecture.md
docs/domain_model.md
docs/time_model.md
docs/time_model_analysis.md
docs/instrument_model.md
docs/runtime.md
docs/event.md
docs/concurrency.md
docs/coding_style.md
docs/testing.md
docs/adr/
```

如果以下文件尚不存在，先确认当前工程中的等价文档：

```text
docs/time_model.md
docs/time_model_analysis.md
```

同时扫描当前工程中所有直接获取时间的代码：

```text
datetime.now
datetime.utcnow
date.today
time.time
time.time_ns
time.monotonic
time.monotonic_ns
asyncio.get_event_loop().time
```

输出当前时间获取方式和风险清单。

不要在没有分析现有实现前直接全局替换。

---

# 3. 任务范围

本任务需要实现或完善：

```text
OnlyClock
OnlyLiveClock
OnlyBacktestClock
OnlyVirtualClock
OnlyClockState
OnlyClockError
OnlyTimer
OnlyTimerId
OnlyTimerHandle
OnlyTimerEvent
OnlyTimerMode
OnlyTimerState
OnlyTimeAdvanceResult
```

根据当前工程情况，也可以定义：

```text
OnlyClockProtocol
OnlyTimerService
OnlyScheduledCallback
OnlyClockSnapshot
```

所有自定义类型必须以 `Only` 开头。

本任务暂不实现：

* 完整 Runtime；
* 完整 EventBus；
* 完整 Backtest；
* Gateway；
* 真实交易；
* Web UI；
* 完整 Trading Calendar；
* Bar 聚合器；
* 订单撮合器。

可以为测试使用最小 Stub 或 Protocol，但不能让 Clock 依赖上述模块。

---

# 4. Clock 的职责边界

## 4.1 Clock 负责

Clock 负责：

* 提供当前 UTC 时间；
* 提供统一整数时间戳；
* 维护回测或虚拟时间；
* 注册定时器；
* 取消定时器；
* 推进虚拟时间；
* 在时间推进时触发到期定时器；
* 保证定时器触发顺序；
* 提供可测试的时间快照；
* 检测非法时间回退；
* 支持确定性重放。

## 4.2 Clock 不负责

Clock 不负责：

* 判断是否为交易日；
* 判断是否处于交易时段；
* 计算 A 股午休；
* 计算美股夏令时交易时间；
* 计算期货夜盘所属交易日；
* 转换 UI 展示时区；
* 保存 Instrument；
* 分发行情事件；
* 订单状态更新；
* 数据库存储。

上述能力由 Trading Calendar、Runtime、Event Bus 或其他组件负责。

---

# 5. 时间标准

## 5.1 UTC

Clock 对外提供的绝对时间必须统一为 UTC。

禁止返回 naive datetime。

允许返回：

```python
datetime(..., tzinfo=timezone.utc)
```

建议同时提供统一整数时间戳。

优先选择：

```text
Unix nanoseconds
```

即：

```text
int64 nanoseconds since Unix epoch
```

如果当前项目已经明确采用微秒，可以继续使用微秒，但整个工程必须唯一，不允许同时混用：

* 秒；
* 毫秒；
* 微秒；
* 纳秒。

必须在文档中写明时间戳单位。

## 5.2 双时间概念

Clock 应区分：

### Wall Clock

表示真实 UTC 时间点，用于：

* Event 时间；
* Order 创建时间；
* Tick 接收时间；
* 日志审计；
* Runtime 当前时间。

### Monotonic Clock

表示单调递增时间，用于：

* 测量执行耗时；
* 超时等待；
* 性能统计；
* 不受系统时钟回拨影响的间隔计算。

建议接口区分：

```python
clock.now_utc()
clock.timestamp_ns()
clock.monotonic_ns()
```

禁止使用 Wall Clock 测量代码执行耗时。

禁止将 Monotonic 值序列化为跨进程业务时间。

---

# 6. OnlyClock 抽象接口

建议设计为抽象类或 Protocol。

参考接口：

```python
class OnlyClock(ABC):
    @abstractmethod
    def now_utc(self) -> datetime:
        ...

    @abstractmethod
    def timestamp_ns(self) -> int:
        ...

    @abstractmethod
    def monotonic_ns(self) -> int:
        ...

    @abstractmethod
    def schedule_at(
        self,
        timer_id: OnlyTimerId,
        when_ns: int,
        callback: OnlyTimerCallback,
    ) -> OnlyTimerHandle:
        ...

    @abstractmethod
    def schedule_after(
        self,
        timer_id: OnlyTimerId,
        delay_ns: int,
        callback: OnlyTimerCallback,
    ) -> OnlyTimerHandle:
        ...

    @abstractmethod
    def schedule_every(
        self,
        timer_id: OnlyTimerId,
        interval_ns: int,
        callback: OnlyTimerCallback,
        *,
        start_ns: int | None = None,
    ) -> OnlyTimerHandle:
        ...

    @abstractmethod
    def cancel_timer(self, timer_id: OnlyTimerId) -> bool:
        ...

    @abstractmethod
    def has_timer(self, timer_id: OnlyTimerId) -> bool:
        ...

    @abstractmethod
    def close(self) -> None:
        ...
```

具体签名应结合现有 Domain 类型调整。

Clock 接口不得依赖：

```text
OnlyEngine
OnlyRuntime
OnlyCluster
OnlyGateway
OnlyEventBus
```

Timer Callback 可以暂时使用 Callable，后续 Runtime 再负责将 Timer 结果包装为 Event。

---

# 7. OnlyLiveClock

`OnlyLiveClock` 表示真实系统时间。

要求：

* 使用系统 UTC 时间；
* 返回 timezone-aware UTC datetime；
* 使用 `time.time_ns()` 获取 Unix 时间戳；
* 使用 `time.monotonic_ns()` 获取单调时间；
* 不使用 `datetime.utcnow()`；
* 不依赖系统本地时区；
* 支持线程安全的定时器注册和取消；
* 关闭时释放所有资源；
* 定时器不得在关闭后继续触发。

## 7.1 定时器实现

第一版不需要追求极端性能。

可以选择：

* 单独调度线程；
* 最小堆；
* 条件变量；
* 明确锁边界。

不建议每个 Timer 创建一个线程。

推荐结构：

```text
OnlyLiveClock
    Timer Heap
    Condition Variable
    Scheduler Thread
```

定时器按以下顺序排序：

```text
deadline_ns
sequence
timer_id
```

使用 sequence 保证相同 deadline 下稳定顺序。

## 7.2 系统时钟回拨

Live Clock 的绝对时间可能因 NTP 或人工调整发生变化。

要求：

* `timestamp_ns()` 表示实际 UTC；
* `monotonic_ns()` 用于间隔；
* 定时器等待优先基于 monotonic time；
* 不允许因 Wall Clock 回拨导致已触发 Timer 再次触发；
* 文档中明确 Wall Clock 和 Monotonic 的区别。

---

# 8. OnlyBacktestClock

`OnlyBacktestClock` 是回测中的虚拟时间源。

要求：

* 初始时间显式传入；
* 不读取系统当前时间；
* 只能由调用者显式推进；
* 默认禁止时间倒退；
* 推进必须确定性；
* 到期 Timer 按稳定顺序触发；
* 同一输入重复运行结果完全一致；
* 不创建后台线程；
* 不依赖 sleep；
* 不依赖真实时间。

建议接口：

```python
advance_to(timestamp_ns: int) -> OnlyTimeAdvanceResult
advance_by(delta_ns: int) -> OnlyTimeAdvanceResult
set_time(timestamp_ns: int) -> OnlyTimeAdvanceResult
```

其中 `set_time()` 是否允许回退必须非常谨慎。

建议默认：

```text
set_time 只能向前
```

如测试确实需要重置，应重新创建 Clock 或使用显式 restore snapshot，而不是随意回退。

## 8.1 推进语义

当从 T1 推进到 T2 时：

1. 找出所有 `deadline <= T2` 的 Timer；
2. 按 `deadline + sequence` 排序；
3. 将 Clock 当前时间临时推进到每个 Timer 的 deadline；
4. 触发 Timer；
5. 处理 Timer 回调中新注册的、同样在 T2 前到期的 Timer；
6. 最终将 Clock 设置到 T2；
7. 返回触发结果。

必须明确 Timer 回调在执行时看到的 `now` 是：

```text
Timer 自身 deadline
```

而不是最终 T2。

这对于回测确定性非常重要。

## 8.2 同时间 Timer

多个 Timer 在同一时间到期时必须有稳定顺序。

顺序建议：

```text
注册 sequence
```

不要依赖：

* dict 顺序；
* set 顺序；
* 内存地址；
* 随机顺序。

---

# 9. OnlyVirtualClock

`OnlyVirtualClock` 主要用于单元测试和组件测试。

它可以与 Backtest Clock 共享实现，但语义上应明确：

* Backtest Clock：历史事件驱动；
* Virtual Clock：测试任意时间条件。

如果两者实现完全一致，可以：

```text
OnlyBacktestClock
    基于 OnlyVirtualClock
```

但公共语义必须清楚，不要仅定义两个空别名。

Virtual Clock 应支持：

* 固定初始时间；
* 精确推进；
* Timer；
* 快照；
* 恢复；
* 测试时间边界；
* 不读取系统时间。

如果实现 Snapshot，建议定义：

```text
OnlyClockSnapshot
```

快照至少包括：

* current_timestamp_ns；
* sequence；
* 活跃 Timer；
* Timer 状态。

只有可安全序列化的 Timer 描述才可进入 Snapshot。

普通 Python callback 通常不能可靠序列化，因此第一版可以只支持 Clock 时间快照，不支持完整 callback 恢复，并在文档中说明限制。

---

# 10. Timer 模型

## 10.1 Timer 类型

建议定义：

```text
OnlyTimer
OnlyTimerId
OnlyTimerHandle
OnlyTimerState
OnlyTimerMode
```

Timer Mode 至少包括：

```text
ONE_SHOT
FIXED_RATE
FIXED_DELAY
```

### ONE_SHOT

触发一次后结束。

### FIXED_RATE

下一次时间基于原计划时间计算：

```text
next = previous_deadline + interval
```

适合要求固定节拍的任务。

### FIXED_DELAY

下一次时间基于本次执行完成时间计算：

```text
next = callback_completed_at + interval
```

Live Clock 可支持。

Backtest Clock 中 callback 没有真实耗时语义，应明确如何处理。第一版可以只支持：

```text
ONE_SHOT
FIXED_RATE
```

并把 `FIXED_DELAY` 留作后续扩展。

## 10.2 Timer 字段

至少包含：

```text
timer_id
mode
created_at_ns
next_deadline_ns
interval_ns
sequence
state
fire_count
metadata
```

## 10.3 Timer 状态

建议：

```text
SCHEDULED
FIRING
CANCELLED
COMPLETED
FAILED
```

## 10.4 Timer 不变量

必须保证：

* timer_id 非空；
* 同一 Clock 内 timer_id 唯一；
* deadline 不早于允许时间；
* interval 必须大于 0；
* Cancel 幂等；
* Completed Timer 不能再次触发；
* Cancelled Timer 不能触发；
* Callback 异常不能破坏 Clock 内部结构；
* 周期 Timer 必须明确异常后的行为。

---

# 11. Timer 重复 ID 策略

必须明确同一 `timer_id` 重复注册时的行为。

推荐默认：

```text
拒绝重复注册
```

抛出：

```text
OnlyDuplicateTimerError
```

如需要替换，提供显式接口：

```python
replace_timer(...)
```

不要让 `schedule_at()` 静默覆盖旧 Timer。

---

# 12. Callback 异常处理

Timer Callback 可能抛出异常。

Clock 必须：

* 捕获异常；
* 保持调度结构可继续使用；
* 返回或记录结构化失败结果；
* 不吞掉错误上下文；
* 不让调度线程无提示退出；
* 明确周期 Timer 异常后的处理策略。

建议第一版策略：

```text
ONE_SHOT callback 失败 → Timer 状态 FAILED
PERIODIC callback 失败 → 默认停止后续触发
```

后续可通过配置支持继续执行。

不要在 Clock 中直接依赖项目全局 Logger 或 EventBus。

可以使用：

* 标准 logging；
* 注入错误处理回调；
* 返回 `OnlyTimerFireResult`。

---

# 13. Timer 与 Event 的边界

Clock 不应直接要求 EventBus。

推荐关系：

```text
Clock
    产生 Timer 到期事实
        ↓
Runtime Timer Service
    转换为 OnlyTimerEvent
        ↓
Runtime EventBus
        ↓
Cluster
```

第一版可以由 Timer Callback 直接调用受控函数。

后续 Runtime 中建议：

```python
clock.schedule_at(
    timer_id,
    deadline_ns,
    lambda: timer_service.emit_timer_event(...),
)
```

Clock 只负责时间和调度，不负责业务事件路由。

---

# 14. Clock 与 Cluster 的边界

Cluster 不应直接持有 `OnlyLiveClock` 或 `OnlyBacktestClock` 具体实现。

Cluster 通过 `OnlyRuntimeContext` 获取受限 Clock 接口，例如：

```text
OnlyClockView
```

可以只暴露：

```python
now_utc()
timestamp_ns()
schedule_at()
schedule_after()
schedule_every()
cancel_timer()
```

Cluster 不应拥有：

```python
advance_to()
advance_by()
```

只有 Backtest Runtime 或测试代码可以推进时间。

否则策略可能自行修改回测时间，破坏确定性。

建议拆分接口：

```text
OnlyClockView
OnlyControllableClock
```

其中：

```text
OnlyClockView
    Cluster 可见

OnlyControllableClock
    Backtest Runtime 可见
```

---

# 15. Clock 与 Runtime 的关系

推荐：

```text
OnlyRuntime
    owns OnlyClock
```

每个 Runtime 必须拥有独立 Clock。

例如：

```text
OnlyLiveRuntime
    OnlyLiveClock

OnlyPaperRuntime
    OnlyLiveClock 或受控 Live Clock

OnlyBacktestRuntime
    OnlyBacktestClock

OnlyResearchRuntime
    OnlyVirtualClock 或 OnlyBacktestClock
```

禁止：

* Engine 全局共享一个可变当前时间；
* Live Runtime 和 Backtest Runtime 共用同一个 Clock；
* Cluster 使用系统时间绕过 Runtime Clock；
* 测试使用真实 sleep 等待 Timer。

---

# 16. 线程安全

## 16.1 Live Clock

Live Clock 需要线程安全地支持：

* 注册；
* 取消；
* 查询；
* 调度线程触发；
* 关闭。

必须明确锁保护的数据。

不要：

* 在持有 Clock 内部锁时执行用户 Callback；
* Callback 内注册 Timer 时发生死锁；
* 关闭时永久等待 Callback；
* 为每个 Timer 创建线程。

推荐流程：

1. 持锁取出到期 Timer；
2. 更新 Timer 状态；
3. 释放锁；
4. 执行 Callback；
5. 持锁更新最终状态或重新调度；
6. 唤醒调度线程。

## 16.2 Backtest Clock

第一版可以是单线程，并明确：

```text
OnlyBacktestClock 不是线程安全对象
```

如果 Runtime 保证单线程推进，这比增加无意义的锁更清晰。

---

# 17. 精度与溢出

如果采用纳秒：

* 使用 Python `int`；
* 序列化时明确范围；
* 与外部 int64 系统交互时检查溢出；
* 禁止 float 秒乘以 1e9 后直接截断；
* datetime 与纳秒互转时明确 Python datetime 只有微秒精度。

必须处理：

```text
datetime → timestamp_ns
timestamp_ns → datetime
```

中的精度差异。

建议：

* `timestamp_ns` 是内部权威值；
* `datetime` 是展示和兼容视图；
* 纳秒余数不能在无提示情况下丢失；
* 如果当前 Domain 只要求微秒，则明确统一使用微秒，不伪装支持纳秒。

不要声称支持纳秒，但实际通过 datetime 往返后只能保持微秒。

---

# 18. 时间转换工具

建议集中实现：

```text
OnlyTimeConverter
```

或者纯函数模块，用于：

```python
datetime_to_unix_ns(...)
unix_ns_to_datetime_utc(...)
ensure_utc_aware(...)
```

要求：

* naive datetime 拒绝；
* aware datetime 转 UTC；
* 单元测试完整；
* 不在多个模块重复实现转换逻辑。

不要让 `OnlyClock` 同时承担所有格式转换职责。

---

# 19. 状态与关闭

Clock 状态建议：

```text
CREATED
RUNNING
CLOSING
CLOSED
FAILED
```

`close()` 必须幂等。

关闭后：

* 不允许注册新 Timer；
* 活跃 Timer 被取消；
* Live 调度线程退出；
* 不再执行新 Callback；
* 查询当前时间是否允许需明确。

建议关闭后：

```python
now_utc()
timestamp_ns()
monotonic_ns()
```

仍可读取或明确抛错，必须统一。

推荐允许读取，但禁止调度操作。

---

# 20. 必须新增的测试

建议创建：

```text
tests/clock/
├── test_clock_boundaries.py
├── test_time_conversion.py
├── test_live_clock.py
├── test_backtest_clock.py
├── test_virtual_clock.py
├── test_timer_one_shot.py
├── test_timer_periodic.py
├── test_timer_ordering.py
├── test_timer_cancel.py
├── test_timer_reentrancy.py
├── test_timer_errors.py
├── test_clock_close.py
├── test_clock_thread_safety.py
├── test_clock_determinism.py
├── test_clock_no_system_time_in_backtest.py
└── test_forbidden_direct_time_access.py
```

## 20.1 边界测试

验证：

* naive datetime 被拒绝；
* aware 非 UTC 时间可转换；
* UTC 保持；
* timestamp 单位一致；
* 负时间戳行为明确；
* 极大时间戳行为明确；
* 精度不静默丢失。

## 20.2 Live Clock 测试

验证：

* `now_utc()` 是 aware UTC；
* `timestamp_ns()` 接近系统 UTC；
* `monotonic_ns()` 单调；
* Timer 可以触发；
* Cancel 生效；
* Close 后不再触发。

测试中不要依赖很长 sleep。

允许极短等待，但必须设置超时，避免测试永久挂起。

## 20.3 Backtest Clock 测试

验证：

* 不读取系统时间；
* 初始时间正确；
* 向前推进；
* 禁止回退；
* Timer 到期；
* 多 Timer 顺序；
* 同 deadline 顺序稳定；
* Callback 中注册新 Timer；
* Callback 中取消其他 Timer；
* 周期 Timer；
* 最终时间正确。

## 20.4 确定性测试

同一输入运行 100 次：

* 触发顺序一致；
* 时间一致；
* fire_count 一致；
* 周期 Timer 一致；
* 异常结果一致。

## 20.5 重入测试

Timer Callback 内：

* 注册新 Timer；
* 取消当前 Timer；
* 取消其他 Timer；
* 查询时间。

不得死锁或破坏 Heap。

## 20.6 Callback 异常测试

验证：

* 异常被记录；
* Clock 仍可继续工作；
* Timer 状态正确；
* 调度线程不崩溃；
* 周期 Timer 后续策略符合文档。

## 20.7 直接时间访问扫描

增加静态测试，扫描核心模块中的：

```python
datetime.now()
datetime.utcnow()
date.today()
time.time()
time.time_ns()
```

Clock 基础设施实现可以进入白名单。

其他业务模块必须通过 Clock。

不要直接全工程禁止 `time.monotonic_ns()`，性能测量基础设施可以有明确白名单。

---

# 21. Demo

创建：

```text
examples/clock_demo/
├── README.md
├── live_clock_demo.py
├── backtest_clock_demo.py
└── timer_order_demo.py
```

## 21.1 Live Demo

展示：

* UTC 当前时间；
* Unix 时间戳；
* 单调时间；
* 一次性 Timer；
* 周期 Timer；
* Cancel；
* Close。

## 21.2 Backtest Demo

使用固定初始时间：

```text
2026-01-05T01:30:00Z
```

模拟：

```text
09:30 Asia/Shanghai
```

注册：

* 09:31 Timer；
* 09:32 Timer；
* 两个相同 deadline Timer；
* 一个周期 Timer。

逐步推进时间并输出稳定触发顺序。

Demo 不依赖系统当前日期。

## 21.3 示例输出

```text
Initial time: 2026-01-05T01:30:00Z

Advance to 01:31:00Z
[FIRED] market_open_check sequence=1

Advance to 01:32:00Z
[FIRED] strategy_timer_a sequence=2
[FIRED] strategy_timer_b sequence=3
[FIRED] heartbeat sequence=4

Clock state: RUNNING
Active timers: 1
```

---

# 22. 性能要求

第一版优先正确性，不要求极端性能。

但应进行基础性能测试：

* 注册 10,000 个 Timer；
* 取消部分 Timer；
* 推进并触发；
* 不出现明显 O(n²) 实现。

推荐使用最小堆：

```text
heapq
```

期望复杂度：

```text
注册 O(log n)
取出到期 Timer O(log n)
取消可使用惰性删除
```

如果采用惰性删除，需要防止 Heap 长期堆积无效 Timer，并提供清理策略。

---

# 23. 文档输出

创建或更新：

```text
docs/clock.md
docs/time_model.md
docs/runtime.md
docs/testing.md
docs/architecture_principles.md
```

`docs/clock.md` 至少包含：

1. Clock 职责；
2. UTC 与 Monotonic；
3. 时间戳精度；
4. OnlyClock 接口；
5. Live Clock；
6. Backtest Clock；
7. Virtual Clock；
8. Timer 模型；
9. Timer 顺序；
10. Callback 异常；
11. 线程安全；
12. Runtime 集成；
13. Cluster 权限边界；
14. 关闭；
15. 测试；
16. Demo；
17. 已知限制。

---

# 24. ADR

创建：

```text
docs/adr/0005-clock-and-timer-model.md
```

至少记录：

## 背景

实盘、回测和测试需要统一但可替换的时间来源。

## 决策

* Runtime 独占 Clock；
* 内部绝对时间使用 UTC；
* 使用统一整数时间戳；
* Live Clock 使用系统 UTC 和 Monotonic；
* Backtest Clock 显式推进；
* Cluster 只能访问 Clock View；
* 只有 Runtime 能推进 Backtest Clock；
* Timer 使用稳定 deadline/sequence 顺序；
* Clock 不直接依赖 EventBus。

## 备选方案

* 所有模块直接调用系统时间；
* Engine 使用一个全局 Clock；
* Backtest 中使用 sleep；
* Timer 完全由 EventBus 管理；
* 每个 Timer 一个线程。

说明拒绝原因。

---

# 25. Architecture Principles 新增规则

在 `docs/architecture_principles.md` 中加入：

```text
Rule: 所有业务当前时间必须来自 Runtime Clock。

Rule: Domain 和 Cluster 禁止直接读取系统时间。

Rule: 每个 Runtime 拥有独立 Clock。

Rule: Backtest Clock 不读取真实系统时间。

Rule: Cluster 不能推进 Runtime Clock。

Rule: UTC 表示绝对时间，Trading Calendar 解释市场时间。

Rule: Monotonic Time 只用于间隔和性能，不作为业务时间持久化。

Rule: Timer 顺序必须确定且可重放。

Rule: Clock 不负责市场交易规则。

Rule: Clock 不直接依赖 EventBus。
```

---

# 26. 实现顺序

严格按以下顺序：

1. 扫描现有时间访问；
2. 输出 Clock 差距分析；
3. 确定时间戳单位；
4. 实现时间转换工具；
5. 定义 OnlyClock 接口；
6. 实现 OnlyVirtualClock；
7. 完成 Virtual Clock 测试；
8. 基于 Virtual Clock 实现 OnlyBacktestClock；
9. 完成 Backtest Clock 测试；
10. 定义 Timer 模型；
11. 完成 Timer 顺序和取消测试；
12. 实现 OnlyLiveClock；
13. 完成线程安全与关闭测试；
14. 增加直接时间访问扫描；
15. 创建 Demo；
16. 更新文档；
17. 创建 ADR；
18. 运行全部相关测试；
19. 输出评估报告。

优先先实现 Virtual/Backtest Clock，再实现 Live Clock。

因为虚拟时间更容易验证核心语义和确定性。

---

# 27. 验收标准

完成后必须满足：

* `OnlyClock` 接口不依赖 Engine、Runtime、Cluster、Gateway 或 EventBus；
* `OnlyLiveClock` 返回 aware UTC；
* `OnlyBacktestClock` 不读取系统时间；
* `OnlyVirtualClock` 可以精确推进；
* Runtime 可以拥有独立 Clock；
* Cluster 只能看到受限 Clock View；
* 时间戳单位全工程统一；
* Wall Clock 与 Monotonic 明确分离；
* Timer 按 deadline 和 sequence 稳定触发；
* 同一输入重复运行结果一致；
* Timer Cancel 幂等；
* Callback 异常不会破坏 Clock；
* Callback 内注册和取消 Timer 不死锁；
* Live Clock 不为每个 Timer 创建线程；
* Close 幂等并释放资源；
* 测试不依赖长时间 sleep；
* 所有直接系统时间访问都有明确白名单；
* 文档、Demo、ADR 完整。

---

# 28. 一票否决项

存在以下任一项，不得标记为完成：

* Backtest Clock 调用 `datetime.now()`；
* Backtest Clock 调用 `time.time()`；
* Clock 返回 naive datetime；
* Live Clock 使用 `datetime.utcnow()`；
* 每个 Timer 创建一个线程；
* 同 deadline Timer 顺序不确定；
* Timer Callback 在持有内部锁时执行；
* Cluster 可以调用 `advance_to()`；
* Engine 中使用全局可变当前时间；
* Live 和 Backtest 共用一个 Clock 实例；
* Timer 异常导致调度线程静默退出；
* 时间戳单位未明确；
* 业务模块仍大量直接读取系统时间；
* 测试依赖真实日期或本地时区；
* Clock 直接承担 Trading Calendar 规则。

---

# 29. 最终交付报告

完成后输出：

```text
新增文件
修改文件
Clock 接口设计
时间戳精度选择
Live Clock 实现方式
Backtest Clock 推进语义
Timer 顺序规则
Timer 异常策略
线程安全策略
直接时间访问扫描结果
测试通过数
测试失败数
测试跳过数
性能测试结果
已知限制
一票否决项
是否建议进入 EventBus 实现
是否建议进入 Runtime 实现
```

最终结论使用：

```text
ACCEPTED
CONDITIONALLY_ACCEPTED
REJECTED
```

当前任务只实现 Clock、Timer、测试、Demo、文档和 ADR。

不要顺便实现 EventBus、Runtime、Gateway、完整 Backtest 或交易逻辑。
