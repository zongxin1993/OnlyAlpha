# ADR-0008：Runtime Clock 与确定性 Timer 模型

- 状态：Accepted
- 日期：2026-07-13
- 关联模块：core.clock、runtime、cluster
- 编号说明：任务建议文件名为 0005，但 ADR-0005 已是 Accepted 的纯金融 Domain 决策；为保持编号唯一顺延为 0008。

## 背景

实盘、回测和测试需要统一但可替换的时间来源。业务直接读取系统时间、全局共享 Clock 或通过 sleep
推进回测都会破坏 Runtime 隔离与确定性。Timer 还必须在同 deadline、callback 重入和异常情况下保持
可重放顺序，并限制 Cluster 修改回测时间的能力。

## 决策

- 每个 Runtime 独占并负责关闭一个 Clock；Engine 不保存全局可变当前时间。
- 绝对时间统一为 UTC，权威整数单位为 Unix nanoseconds；datetime 只是微秒精度兼容视图。
- Live Clock 使用 `time.time_ns()` 表达 Wall Clock，使用 `time.monotonic_ns()` 等待和测量间隔。
- Virtual/Backtest Clock 只显式单调推进，不读取真实时间、创建线程或 sleep。
- Cluster 只获得 `OnlyClockView`；只有 Runtime/测试持有 Backtest 控制接口。
- Timer 最小堆按 `deadline_ns + registration sequence + timer_id` 稳定排序。
- callback 在 Timer deadline 执行且不持 Clock 锁；callback 新建/取消 Timer 是受支持的重入操作。
- callback 失败生成结构化 failure；周期 Timer 默认停止，Clock 与 Live scheduler 继续工作。
- Clock 不依赖 EventBus；Runtime Timer Service 后续负责把到期事实转换为事件。
- 第一版周期语义为 FIXED_RATE；FIXED_DELAY 暂不通过公共 API 创建。

## 备选方案

- 所有模块直接调用系统时间：无法固定测试输入，系统回拨与本地时区会扩散到业务。
- Engine 使用一个全局 Clock：Live、Paper、Backtest 与 Research 无法隔离。
- Backtest 使用 sleep：慢且不确定，callback 看到的时间无法重放。
- Timer 完全由 EventBus 管理：混淆时间调度与路由、背压职责并形成反向依赖。
- 每个 Timer 一个线程：资源不可控，同 deadline 顺序和关闭难以保证。

## 结果

Runtime 时间和 Timer 行为可独立测试、稳定重放；Cluster 不能推进或关闭 Clock。代价是 Live callback
当前串行，长 callback 会造成延迟；完整 Timer 持久化、FIXED_DELAY 和 EventBus 适配留待后续边界实现。

## 验证

Clock 专项测试验证 UTC/纳秒、推进、deadline/sequence 顺序、100 次重放、重入、异常、关闭、单调等待、
单 scheduler thread、Runtime 权限隔离和直接时间访问白名单。ruff、mypy strict 与全量 pytest 必须通过。
