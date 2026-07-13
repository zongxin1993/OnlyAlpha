# Clock 子系统验收报告

- 日期：2026-07-13
- 结论：**ACCEPTED**

## 新增文件

- `src/onlyalpha/core/time.py`
- `tests/clock/`：20 项 Clock 专项测试与 10,000 Timer 手工基准
- `examples/clock_demo/`：Live、Backtest 与稳定顺序 Demo
- `docs/clock.md`
- `docs/clock_analysis.md`
- `docs/architecture_principles.md`
- `docs/adr/0008-clock-and-timer-model.md`
- `docs/clock_acceptance_report.md`

ADR 任务建议编号 0005 已被 Accepted 的纯金融 Domain ADR 占用，未覆盖或制造重复编号，使用下一个
连续编号 0008；决策内容满足 Clock/Timer ADR 要求。

## 修改文件

- `src/onlyalpha/core/clock.py`：统一接口、Virtual/Backtest/Live、Timer、状态、快照、失败结果。
- `src/onlyalpha/core/__init__.py`、`src/onlyalpha/__init__.py`：导出公共 Clock 类型。
- `src/onlyalpha/cluster/base.py`：Cluster Context 仅接受 `OnlyClockView`。
- `src/onlyalpha/runtime/runtime.py`：注入受限 Clock View，Runtime stop 关闭自有 Clock。
- `tests/unit/test_clock_event.py`：系统当前时间改为固定 UTC 输入。
- `docs/time_model.md`、`docs/runtime.md`、`docs/testing.md`：精度、权限与验证规则同步。

## Clock 接口设计

`OnlyClock` 提供 `now_utc/timestamp_ns/monotonic_ns`、Timer 注册/取消/查询和幂等关闭；`now()`
仅作兼容别名。`OnlyVirtualClock` 提供控制接口，`OnlyBacktestClock` 继承其确定推进语义。
`OnlyClockView` 是 Cluster 的运行时 facade，不暴露推进、恢复或关闭。Clock 模块未导入 Engine、
Runtime、Cluster、Gateway 或 EventBus。

## 时间戳精度选择

权威单位是 Unix nanoseconds，沿用 ADR-0007 和 `OnlyTimestamp`。转换使用整数 timedelta 分解，
不经过 float。Python datetime 只作为微秒精度兼容视图；通用转换默认拒绝 sub-microsecond 丢失，
Clock 显式截断视图但保留纳秒真值。

## Live Clock 实现方式

Wall Clock 使用 `time.time_ns()`，Monotonic 使用 `time.monotonic_ns()`。一个 daemon scheduler thread、
一个 Condition 与一个 heap 服务全部 Timer，不为每个 Timer 创建线程。heap 按业务 deadline、注册
sequence、timer_id 排序，等待使用 Timer 对应的 monotonic deadline。callback 在锁外串行执行。

## Backtest Clock 推进语义

不读取系统时间、不 sleep、无线程且默认禁止回退。推进到 target 时逐个把当前时间置为到期 Timer
的 deadline，执行包含 callback 新注册 Timer 在内的所有 `deadline <= target` 项，最后才置为 target。
同一输入的 100 次测试得到相同顺序、时间和 fire count。

## Timer 顺序与异常策略

顺序为 `deadline_ns → registration sequence → timer_id`。周期采用 FIXED_RATE：下一 deadline 基于
上一计划时间。重复 ID 拒绝；取消可重复；一次性或周期 callback 失败均进入 FAILED，周期后续停止。
失败保留 Event 与原异常；Virtual 返回本轮 failure，Live 同时记录标准日志，调度继续。

## 线程安全与关闭

Live 的 heap、Timer 状态、sequence、failure 和 Clock state 均由 Condition lock 保护；callback 不持锁，
测试覆盖 callback 重入以及四线程并发注册/取消 200 个 Timer。close 取消活跃项、唤醒并回收 scheduler，
可重复调用；关闭后仍可读时间，但禁止新调度。Virtual/Backtest 明确为单线程推进对象。

## 直接时间访问扫描结果

生产源码运行时调用只剩 `src/onlyalpha/core/clock.py` 中的 `time.time_ns()` 与
`time.monotonic_ns()`，属于明确基础设施白名单。Domain、Event、Runtime、Cluster、Cache、Storage
没有直接系统时间读取。AST 回归测试扫描规定 API，并拒绝白名单外调用。

## 测试与静态检查

- Clock 专项：20 passed，0 failed，0 skipped，0.09s。
- 全量测试：75 passed，0 failed，0 skipped，0.25s。
- Ruff：通过。
- mypy strict：39 个 source files，无问题。
- Demo：Backtest、Timer order、Live 全部运行通过。
- `git diff --check`：通过。

## 性能测试结果

`OnlyVirtualClock` 注册 10,000 个 Timer，取消每三个中的一个，并推进触发其余 6,666 个：

```text
register_ms=16.328
cancel_ms=1.233
advance_ms=9.047
```

该结果是当前开发机单次正确性 smoke benchmark，不是稳定性能承诺。实现使用 heapq：注册和取出到期项
为 O(log n)，取消为状态标记；未观察到 O(n²) 行为。

## 已知限制

- Virtual/Backtest 不支持并发推进。
- callback 不进入可序列化快照，含活跃 callback 的快照不能恢复。
- `OnlyTimerMode.FIXED_DELAY` 已建模但第一版无公共注册入口。
- Live callback 在唯一 scheduler thread 串行运行，长 callback 会延迟后续 Timer。
- 取消项采用 pop 时惰性清理，尚无主动 heap 压缩指标。
- 尚未实现 Timer 持久化、Runtime Timer Service 或 EventBus envelope 适配。

## 一票否决项

逐项检查均未触发：Backtest 无系统时间调用；Clock 只返回 aware UTC；Live 不使用 utcnow；无每 Timer
线程；同 deadline 顺序确定；callback 不持锁；Cluster 无推进权限；无 Engine 全局时间；Runtime 各自
持有 Clock；异常不终止 scheduler；纳秒单位已明确；业务源码无绕过；Clock 无 Trading Calendar 或
EventBus 依赖。

## 后续建议

- 是否建议进入 EventBus 实现：**是**。仅建议新增 Runtime Timer Service，把 `OnlyTimerEvent` 转为
  Runtime 归属的 Event envelope；不把调度职责移入 EventBus。
- 是否建议进入 Runtime 实现：**是**。Backtest 历史事件驱动器应持有控制接口，Cluster 继续只接收
  `OnlyClockView`，并补多 Runtime 独立推进集成测试。
