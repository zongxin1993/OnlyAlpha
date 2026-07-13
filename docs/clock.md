# Clock 与 Timer 模型

## 1. 职责与边界

Clock 回答一个 Runtime 认为的当前 UTC 时间，并负责 Timer 注册、取消、确定顺序、关闭和虚拟时间推进。
Clock 不判断交易日、Session、午休、夜盘或 DST，也不依赖 Engine、Runtime、Cluster、Gateway 或 EventBus。
市场本地含义统一由 `OnlyTradingCalendar` 解释。

## 2. UTC、Unix 纳秒与 Monotonic

业务绝对时间使用 UTC，权威整数为 Unix nanoseconds。`timestamp_ns()` 可持久化和跨进程传输；
`now_utc()` 是 aware UTC datetime 兼容视图，最多保留微秒。通用纳秒转 datetime 默认拒绝精度损失。
`monotonic_ns()` 只测量间隔、等待和性能，不能序列化为业务时间。Live Timer 用 Monotonic 等待，
避免 Wall Clock 回拨导致已触发 Timer 重复；Timer 的业务 deadline 仍是 Unix 纳秒。

## 3. 接口

`OnlyClock` 提供读取、`schedule_at/after/every`、取消、查询和幂等关闭。旧 `now()` 是
`now_utc()` 的兼容别名。`OnlyClockView` 只代理读取和调度，不提供推进或关闭权限，供 Cluster 使用。

## 4. Virtual 与 Backtest

`OnlyVirtualClock` 不读取系统时间、不创建线程、不 sleep。它支持纳秒精确初始值、`advance_to`、
`advance_by`、只前进的 `set_time`、Timer、快照和恢复。回调执行时 Clock 临时位于 Timer 自身
deadline，完成所有 `deadline <= target` 的 Timer（包括回调中新建者）后才到达 target。

`OnlyBacktestClock` 复用 Virtual 的确定性实现，但语义是历史事件驱动；只有 Backtest Runtime
持有它的控制接口。它是单线程对象，不承诺并发推进安全。

快照描述时间、sequence 和 Timer 状态，但 Python callback 不可可靠序列化。当前只允许恢复不含
活跃 callback 的 time-only snapshot；含活跃 Timer 时明确失败。

## 5. Timer 模型与顺序

Timer ID 在一个 Clock 的整个生命周期内唯一，重复注册抛 `OnlyDuplicateTimerError`。deadline 不得
早于注册时当前时间；interval 必须为正。取消操作可重复调用，只有第一次从活跃状态取消返回 true。

```text
deadline_ns → registration sequence → timer_id
```

sequence 在 Clock 内单调增加且唯一，timer_id 是防御性最终键。`ONE_SHOT` 触发后完成；
`FIXED_RATE` 下一 deadline 等于上一计划 deadline 加 interval，因此回放不受 callback 耗时影响。
第一版公共 `schedule_every` 只建立 FIXED_RATE；FIXED_DELAY 枚举为后续 Live 扩展保留。

## 6. Callback 异常与重入

Clock 在不持有内部锁时执行用户 callback。callback 可以查询时间、注册 Timer、取消自己或其他 Timer。
异常保存为包含 `OnlyTimerEvent` 和原异常的 `OnlyTimerFailure`：一次性或周期 Timer 均进入 FAILED，
周期后续停止。Virtual advancement 返回本轮 failures；Live scheduler 使用标准 logging 记录上下文，
调度线程继续处理其他 Timer。Clock 不直接产生 EventBus envelope。

## 7. Live 线程安全与关闭

`OnlyLiveClock` 只有一个 scheduler thread，所有 Timer 共用最小堆和 Condition。锁保护 heap、Timer 状态、
sequence、failures 与 Clock state；callback 在锁外运行。绝对时间来自 `time.time_ns()`，等待来自
`time.monotonic_ns()`。同 deadline 仍按业务 deadline 和 sequence 排序。

`close()` 幂等：禁止后续调度、取消活跃 Timer、唤醒并回收 scheduler。读取当前 UTC/纳秒/Monotonic
在关闭后仍允许。若 callback 自己关闭 Clock，不会等待当前线程自身。

## 8. Runtime 与 Cluster

每个 Runtime 独占 Clock，Runtime stop 负责 close。Live/Paper 可使用 Live Clock，Backtest 使用
Backtest Clock，Research 可使用 Virtual Clock。不同 Runtime 不能共享可变 Clock。Cluster 只获得
`OnlyClockView`，无法推进或关闭 Runtime Clock。

## 9. 测试、Demo 与限制

`tests/clock` 覆盖转换、UTC、纳秒、Virtual/Backtest 推进、同 deadline 顺序、100 次重放、周期 Timer、
取消、callback 重入/失败、Live 触发/线程/关闭和 AST 禁止访问。Demo 位于 `examples/clock_demo`。

已知限制：Virtual/Backtest 单线程；callback 不可随快照恢复；未公开 FIXED_DELAY 注册 API；Live callback
在 scheduler thread 串行执行，长 callback 会延迟后续 Timer；惰性删除项在 pop 时清理，尚无主动 heap
压缩指标；未实现跨进程 Timer 持久化或 EventBus 适配。
