# ADR-0055：Application 中断权威与有界关闭

- 状态：Accepted
- 日期：2026-08-05
- 关联模块：application、cli、engine、runtime、streaming、miniqmt

## 背景

长生命周期 CLI 曾在 `StreamingRuntime.wait(None)` 中无限等待。外层捕获 `KeyboardInterrupt` 只能证明异常已经
产生后的清理路径，不能保证 Windows 控制台事件或 POSIX 信号及时唤醒主线程；多 Runtime 的
`OnlyEngine.wait(timeout)` 还会为每个 Runtime 重复消耗完整 timeout。二次中断、退出码和强制退出也没有统一权威。

## 决策

- OS 信号只由 Application 层的 `OnlyApplicationStopController` 安装、记录和恢复；Runtime、Cluster、插件和 worker
  不安装进程级处理器。
- SIGINT、Windows SIGBREAK/控制台 Break 和回退的 `KeyboardInterrupt` 返回 130；SIGTERM 返回 143。
- 长生命周期 Application 以 0.25 秒有限预算轮询 `OnlyEngine.wait()`；`OnlyEngine.wait(timeout)` 的 timeout 是所有
  Runtime 共享的总预算，使用单调时钟计算剩余时间。
- 第一次中断只设置停止事件，正常主线程随后唯一调用一次 `OnlyEngine.stop()`；第二次中断通过可注入的
  `OnlyForcedExitPort` 立即终止进程，不重入 Engine/Runtime 关闭链。
- Engine 只调用各 Runtime 的统一 `close()`；Cluster 停止、订阅取消、worker/publisher、插件、EventBus、Persistence
  和 Clock 的关闭仍由 Runtime 按所有权执行。清理继续遍历全部资源并保留第一个失败。
- OnlyAlpha 自建线程使用可唤醒停止条件和有界 join；MiniQMT shutdown 开始后清空订阅登记并拒绝迟到 callback。

## 结果

Ctrl+C 的含义固定为退出整个 Engine，而不是停止单个 Cluster。真实控制台信号可通过跨平台子进程测试，强制退出通过
注入 Port 测试，不会杀死 pytest。强制退出可能丢失未提交内存状态；当前 Paper 仍不提供 Streaming
Checkpoint/Recovery。第三方 xtquant 内部线程只能通过公开的取消订阅接口协作，无法声明由 OnlyAlpha 完全拥有。

## 验证

- Application 信号、退出码、handler 恢复、启动失败、worker failure 和二次中断单测；
- Engine 单/多 Runtime 总等待预算测试；
- POSIX SIGINT/SIGTERM 与 Windows CTRL_BREAK_EVENT 离线子进程测试；
- Streaming worker、Observation Publisher、Live Clock 和 MiniQMT 迟到 callback 合同测试；
- 显式 opt-in、只读且禁用 Broker 的真实 MiniQMT Windows shutdown gate；
- fast、integration、miniqmt-contract、full、Ruff 和 strict mypy。
