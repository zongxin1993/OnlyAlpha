# 观测基础设施性能基准

## 方法与边界

Cargo target为 `overhead`，通过公开 Session/Operation、tracing event 和真实 tokio task 测量 Off/Basic/Detail。每档分别测 no-op、显式操作、摘要事件和跨任务传播，工作量为1/32/256项。

每次迭代在计时外创建独立 Session 和容量1024的队列；最大批次513条事件，不靠队列丢失取得速度。计时包含 Dispatch 切换、操作/事件编码与入队、或 task 创建/调度/join；输出对象析构、flush、关闭和线程启动在外。每轮关闭断言无丢失、无 I/O 错误。输出使用 `io::sink`，不代表磁盘持久化速度。跨任务场景使用 current-thread runtime，不代表多核吞吐。

no-op 包含同样的 Dispatch 切换和迭代框架；不能把不同场景直接相除并称为回测性能变化。完整链路还需同输入 Off/Detail 实测。

## 参考基线

2026-11-14，固定 onlyalpha-dev，Linux aarch64，Rust1.99.1，Cargo bench/release。冻结源码摘要 `e59f106730da49f3400106a56cb1657312e324da1b60a07b05661eb2776bb1f3`；bench输入摘要 `d492dca539eaa698ffc5233e9426032a37ef2c76252cd6f3ae5a3a317d8c6e73`；可执行文件摘要 `7895818dc29d1d903a9e49c03a2c4421e82c52db5d79c75112a9bcd21a787dbb`。本轮串行采样，未独占宿主硬件、未清OS缓存。

原始结果位于主工作区 `test-results/backtest-observability/reference-observability-03/observability/overhead/`，保留环境、构建、预检、原始Criterion样本、官方估计和统一报告。表中使用Criterion的median估计，每项至少10个样本。

| 场景 | 每批项数 | 每批中位耗时 ns | 吞吐 项/秒 | 样本数 |
| --- | ---: | ---: | ---: | ---: |
| basic.cross_task/1 | 1 | 2809.82 | 355895 | 10 |
| basic.cross_task/256 | 256 | 397780 | 643572 | 10 |
| basic.cross_task/32 | 32 | 52916.7 | 604724 | 10 |
| basic.event/1 | 1 | 1186.77 | 842624 | 10 |
| basic.event/256 | 256 | 293996 | 870761 | 10 |
| basic.event/32 | 32 | 37758.7 | 847487 | 10 |
| basic.noop/1 | 1 | 56.6444 | 1.7654e+07 | 10 |
| basic.noop/256 | 256 | 126.317 | 2.02665e+09 | 10 |
| basic.noop/32 | 32 | 50.2521 | 6.36789e+08 | 10 |
| basic.operation/1 | 1 | 2301 | 434594 | 10 |
| basic.operation/256 | 256 | 362050 | 707086 | 10 |
| basic.operation/32 | 32 | 48456.2 | 660390 | 10 |
| detail.cross_task/1 | 1 | 4693.41 | 213065 | 10 |
| detail.cross_task/256 | 256 | 925172 | 276705 | 10 |
| detail.cross_task/32 | 32 | 116119 | 275578 | 10 |
| detail.event/1 | 1 | 1108.17 | 902388 | 10 |
| detail.event/256 | 256 | 313374 | 816915 | 10 |
| detail.event/32 | 32 | 38060.5 | 840768 | 10 |
| detail.noop/1 | 1 | 49.7462 | 2.0102e+07 | 10 |
| detail.noop/256 | 256 | 129.448 | 1.97763e+09 | 10 |
| detail.noop/32 | 32 | 52.6163 | 6.08176e+08 | 10 |
| detail.operation/1 | 1 | 4411.78 | 226666 | 10 |
| detail.operation/256 | 256 | 905981 | 282567 | 10 |
| detail.operation/32 | 32 | 113170 | 282760 | 10 |
| off.cross_task/1 | 1 | 320.494 | 3.12018e+06 | 10 |
| off.cross_task/256 | 256 | 35508.3 | 7.20957e+06 | 10 |
| off.cross_task/32 | 32 | 4831.75 | 6.62286e+06 | 10 |
| off.event/1 | 1 | 31.5912 | 3.16543e+07 | 10 |
| off.event/256 | 256 | 127.37 | 2.0099e+09 | 10 |
| off.event/32 | 32 | 34.0091 | 9.40925e+08 | 10 |
| off.noop/1 | 1 | 31.6651 | 3.15805e+07 | 10 |
| off.noop/256 | 256 | 101.212 | 2.52935e+09 | 10 |
| off.noop/32 | 32 | 31.8758 | 1.0039e+09 | 10 |
| off.operation/1 | 1 | 38.6161 | 2.5896e+07 | 10 |
| off.operation/256 | 256 | 3308.84 | 7.73686e+07 | 10 |
| off.operation/32 | 32 | 435.124 | 7.35423e+07 | 10 |

单项同步operation中位耗时：Off约38.6ns、Basic约2.30µs、Detail约4.41µs。这里只描述该构建与sink输出，不据此推断实际回测开销比例或声明性能门槛通过。

用于后续比较的补证报告位于主工作区 `test-results/backtest-observability/storage-verified/` 对应参考目录；只从原 identity 的 mountinfo 和本轮原始命令路径导出 storage v1，保留原 report/identity SHA、命令日志与迁移记录，未改原样本、结果或构建身份。Runtime 配对结果为该目录下 `runtime-observation-overhead-02.json`。其余缺少可证明存储条件的历史报告只作原测量展示，拒绝用于同条件比较。
