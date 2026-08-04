# OnlyAlpha Ctrl+C 优雅退出设计与实现

请认真阅读并修改 OnlyAlpha 工程：

```text
https://github.com/zongxin1993/OnlyAlpha
```

## 一、任务目标

为 OnlyAlpha 的长生命周期 CLI 建立正式、统一、跨平台、可测试的中断退出机制。

当前需要支持：

```text
Windows:
- Ctrl+C
- CTRL_C_EVENT
- CTRL_BREAK_EVENT

Linux / macOS:
- SIGINT
- SIGTERM
```

本任务的核心目标是：

```text
终端中断
→ Application 层接收停止请求
→ 唤醒主线程
→ 退出等待循环
→ 调用 OnlyEngine.stop()/close()
→ 停止所有 Runtime
→ 停止所有 Cluster
→ 取消行情订阅
→ 停止 Streaming Worker
→ 停止 Observation Publisher
→ 关闭插件、EventBus、Persistence、Clock
→ Python 进程退出
```

必须明确：

```text
Ctrl+C = 优雅退出整个 OnlyEngine
```

不是：

```text
Ctrl+C = 停止某一个 Cluster
```

单 Cluster 停止属于独立的 Engine Control Plane 能力，不在本任务中实现。

---

## 二、当前问题背景

当前长生命周期 CLI 调用链大致为：

```text
onlyalpha.cli.main()
→ OnlyEngineApplicationRunner.execute()
→ engine.initialize()
→ engine.start()
→ engine.wait()
→ Streaming Runtime.wait(timeout=None)
→ threading.Event.wait(None)
```

Application Runner 虽然捕获了：

```python
except KeyboardInterrupt:
    return 0
finally:
    engine.stop()
```

但这不代表真实终端 Ctrl+C 一定能够退出。

需要重点检查：

1. 主线程是否阻塞在无限期 `Event.wait(None)`；
2. Windows + Python 3.12 下，该阻塞是否能及时转化为 `KeyboardInterrupt`；
3. `KeyboardInterrupt` 是否能真正进入 `finally`；
4. `engine.stop()` 是否会因为线程、插件或 SDK 阻塞而无法完成；
5. 第二次 Ctrl+C 时是否会重复进入关闭链或形成死锁；
6. CLI 退出后是否仍残留非 daemon 线程。

现有测试如果只是：

```python
engine.wait.side_effect = KeyboardInterrupt
```

只能证明异常已经抛出后 `finally` 会执行，不能证明真实操作系统信号能够中断主等待线程。

---

## 三、开始修改前的审计要求

修改前必须认真阅读：

```text
AGENTS.md
README.md

src/onlyalpha/cli.py
src/onlyalpha/application/engine_runner.py
src/onlyalpha/engine/engine.py

src/onlyalpha/runtime/runtime.py
src/onlyalpha/runtime/streaming/runtime.py
src/onlyalpha/runtime/streaming/worker.py

src/onlyalpha/observation/publisher.py

packages/provider/onlyalpha-plugin-miniqmt/
tests/application/test_engine_runner.py
tests/cli/test_engine_cli.py
相关 Runtime、Paper、Thread、Lifecycle 测试
```

全仓库搜索：

```text
KeyboardInterrupt
SIGINT
SIGTERM
signal.signal
Event.wait
Thread.join
daemon=
wait(
stop(
close(
unsubscribe
stop_cluster
```

实施前先给出简短审计结论，明确回答：

1. 当前主线程实际阻塞点；
2. 当前 Ctrl+C 不能退出的直接根因；
3. Application、Engine、Runtime、Cluster 的生命周期职责；
4. 操作系统信号处理权威应该位于哪一层；
5. 哪些线程和插件资源可能阻止进程退出；
6. 当前停止链是否具备幂等性；
7. 是否存在重复停止 Cluster 的问题。

不要仅根据本提示词直接修改。

---

## 四、架构原则

### 4.1 唯一产品入口

OnlyEngine 是唯一产品生命周期入口。

正式退出链必须保持：

```text
CLI / Application
→ OnlyEngine
→ Runtime
→ Cluster / Runtime-owned Services
→ Plugin Resources
```

禁止：

```text
CLI 直接停止 ClusterManager
CLI 直接停止 Streaming Worker
CLI 直接关闭 MiniQMT DataSource
CLI 直接关闭 Observation Publisher
Signal Handler 直接调用 Runtime.close()
新增第二套 Engine Service
```

### 4.2 操作系统信号属于 Application 边界

信号处理只能存在于最外层 Application/CLI。

推荐增加一个轻量内部组件，例如：

```text
OnlyApplicationStopController
```

或同等职责明确的实现。

它可以负责：

```text
stop_requested
interrupt_count
shutdown_reason
requested_exit_code
signal handler 安装
signal handler 恢复
首次中断状态
二次中断状态
```

Runtime、Cluster、DataSource 和 Worker 不得各自安装进程级信号处理器。

### 4.3 Signal Handler 必须轻量

信号处理函数中只能执行：

```text
设置 threading.Event
记录信号类型
增加中断计数
设置简单状态
```

不得直接执行：

```text
engine.stop()
engine.close()
runtime.close()
thread.join()
unsubscribe()
SQLite close
Artifact 写入
等待网络或 SDK
```

复杂关闭操作必须在正常主线程控制流中执行。

---

## 五、Ctrl+C 的正式语义

### 5.1 第一次 Ctrl+C

第一次收到 SIGINT/控制台中断时：

```text
RUNNING
→ STOP_REQUESTED
→ SHUTTING_DOWN
→ Engine.stop()
→ Engine.STOPPED
→ Process Exit
```

要求：

1. 不再继续无限等待；
2. 不再接收新的业务运行请求；
3. 只启动一次 Engine 关闭流程；
4. 关闭流程必须有界；
5. 输出简短中断信息；
6. 不打印无意义 traceback；
7. 不把操作员中断记录为 Engine 运行失败；
8. 退出码使用统一 CLI 约定。

建议退出码：

```text
正常结束       : 0
SIGINT/Ctrl+C : 130
SIGTERM       : 143
运行错误       : 保持现有错误码
```

若工程已有正式退出码合同，以当前正式合同为准，但代码、测试和文档必须统一。

### 5.2 第二次 Ctrl+C

如果优雅关闭期间再次按下 Ctrl+C：

```text
第一次中断 → graceful shutdown
第二次中断 → force termination
```

第二次中断不得：

* 再次执行完整 `engine.stop()`；
* 再次停止同一 Runtime；
* 再次重复停止所有 Cluster；
* 再次等待相同 Thread.join；
* 因重复关闭形成死锁。

强制退出只能位于 Application/CLI 最外层边界。

为了可测试性，不要在普通单元测试路径中直接硬编码真实 `os._exit()`。

建议通过可注入接口，例如：

```python
class OnlyForcedExitPort(Protocol):
    def exit(self, code: int) -> NoReturn: ...
```

生产实现可以使用合适的强制退出方式，测试实现只记录调用。

---

## 六、等待模型修复

### 6.1 禁止永久阻塞等待

长生命周期 CLI 不得继续只调用：

```python
engine.wait(timeout=None)
```

建议改为有限时间轮询：

```python
while not stop_controller.stop_requested:
    engine.wait(timeout=poll_interval)
```

建议：

```text
poll_interval = 0.1 ~ 0.5 秒
```

必须避免：

* busy loop；
* 无限 Lock/Event wait；
* 高 CPU 空转；
* 平台专属死循环；
* 为了 Ctrl+C 吞掉 Runtime Worker Failure。

主线程需要周期性重新获得 Python 执行权，以便处理待处理信号和异常。

### 6.2 Engine.wait 的 timeout 是总预算

审计当前实现是否为：

```python
for runtime in runtimes:
    runtime.wait(timeout)
```

若是，则多个 Runtime 会分别消耗完整 timeout。

应改为：

```text
OnlyEngine.wait(timeout=X)
```

表示整个 Engine wait 调用的总时间预算。

建议使用：

```python
deadline = monotonic() + timeout
```

然后每个 Runtime 使用：

```python
remaining = max(0, deadline - monotonic())
```

要求：

* 使用单调时钟；
* `None` 仍表示无限等待，但 CLI 不应对长生命周期直接使用 `None`；
* `timeout=0` 行为明确；
* 多 Runtime 总等待时间不能线性放大；
* 测试允许合理调度误差。

---

## 七、Engine 优雅关闭顺序

收到停止请求后，必须通过：

```python
engine.stop()
```

或：

```python
engine.close()
```

统一关闭。

推荐正式关闭顺序：

```text
1. Application 标记 shutdown requested
2. 停止主等待循环
3. Engine 进入 STOPPING
4. 反向遍历 Runtime
5. Runtime 阻止新的业务输入
6. 停止各 Cluster
7. 调用 Cluster.on_stop()
8. 清理 Cluster Timer、Subscription、Snapshot Context
9. Drain 已提交 Execution Outbox
10. Drain EventBus
11. 取消外部 DataSource Subscription
12. 停止 Streaming Worker
13. 停止并有界刷新 Observation Publisher
14. 关闭 Plugin Resource
15. 卸载 Cluster
16. 关闭 Event Router
17. 关闭 EventBus
18. 关闭 Runtime Persistence Store
19. 关闭 Clock
20. Runtime = CLOSED
21. 释放 Engine Infrastructure 引用
22. 关闭 Engine Storage
23. Engine = STOPPED
24. CLI 返回退出码
```

具体顺序必须以当前资源所有权和现有代码为准。

不要为了匹配本提示词破坏现有 Ordered Shutdown 合同。

---

## 八、Cluster 与 Engine 退出的关系

### 8.1 Ctrl+C 必须停止整个 Engine

当前一个 Engine 中可能存在：

```text
Runtime A
├── Cluster A1
└── Cluster A2

Runtime B
└── Cluster B1
```

Ctrl+C 必须表示：

```text
停止 A1、A2、B1
关闭 Runtime A、Runtime B
关闭 Engine
退出进程
```

不能只停止最后执行回调的 Cluster。

### 8.2 不在本任务实现单 Cluster 动态停止

当前 Runtime/ClusterManager 可能已有：

```python
runtime.stop_cluster(cluster_id)
cluster_manager.stop(cluster_id)
```

但本任务不得因此绕过 Engine 对外开放动态 Cluster 控制。

以下能力不在本任务中实现：

```text
engine.stop_cluster()
engine.pause_cluster()
engine.resume_cluster()
动态 Cluster Remove
跨进程 Cluster Control API
Web/HTTP Control Plane
Unix Socket / Named Pipe 控制
```

如果审计发现 Engine.stop() 当前先逐个 `runtime.stop_cluster()`，然后 `runtime.close()` 内部又执行 `cluster_manager.stop_all()`，需要验证其幂等性，但不要在本任务中扩展动态 Cluster 产品能力。

---

## 九、关于退出时状态保存

本任务的目标是：

```text
资源有序关闭
进程可靠退出
```

不是：

```text
保证保存 Ctrl+C 瞬间所有 Runtime 内存状态
```

必须准确区分：

### 已提交 Durable State

已经通过 durable commit 写入 Persistence Store 的事务事实，仍应保持可恢复。

### Runtime 内存状态

例如：

```text
Pending Live Bar
MarketData Cache
Aggregation Window
Indicator State
Factor State
Strategy State
Historical Watermark
Sequence/Dedup State
Latest Observation
Streaming Phase
```

如果 Paper 当前没有 Streaming Checkpoint/Recovery，则 Ctrl+C 退出不能声称保存全部状态。

本任务不得顺带实现完整 Streaming Checkpoint。

可以在关闭日志或文档中明确：

```text
Graceful shutdown completed.
Streaming restart checkpoint is not available in the current Paper scope.
```

不要错误宣传“Ctrl+C 后可从原位置完全恢复”。

---

## 十、线程退出要求

重点检查：

```text
OnlyStreamingMarketDataWorker
OnlyObservationPublisher
MiniQMT/xtquant 线程
其他 OnlyAlpha 非 daemon 线程
```

正式要求：

1. 所有 OnlyAlpha 自建线程必须有明确 Owner；
2. 所有线程必须有停止事件；
3. 所有阻塞等待必须可被唤醒；
4. 所有 `join()` 必须有超时；
5. 超时必须形成明确错误；
6. 不得通过改成 `daemon=True` 掩盖泄漏；
7. 停止后不允许新 Callback 继续进入 Runtime；
8. Observation Sink 阻塞不得永久阻止退出；
9. Queue drain 必须有边界；
10. 第二次 Ctrl+C 必须能脱离卡住的 graceful shutdown。

对于 Worker：

```text
取消订阅或关闭输入入口
→ 阻止新数据进入
→ Drain 明确边界内的数据
→ 设置 stop Event
→ join
```

不能：

```text
持续有新行情进入
同时无限 drain queue
导致永远无法退出
```

---

## 十一、MiniQMT 特殊要求

当前主要实时环境是 Windows + MiniQMT。

需要确认：

```text
unsubscribe_quote()
subscription callback
xtdata 内部线程
MiniQMT SDK 生命周期
```

要求：

1. 退出时取消全部已登记订阅；
2. 清空本地 Subscription Registry；
3. shutdown 开始后忽略晚到 Callback；
4. Callback 不得向已关闭 Queue 发布；
5. 不调用未确认存在的私有 xtquant shutdown 接口；
6. Fake XtData 测试不能代替真实 MiniQMT 进程退出测试；
7. 若 SDK 内部线程无法由公开 API 关闭，必须留下明确诊断。

本任务不得：

```text
启用 MiniQMT Broker
连接真实交易账户
发送真实订单
修改账户和持仓
```

---

## 十二、幂等性要求

需要审计并修复：

```text
OnlyEngine.stop()
OnlyEngine.close()
OnlyRuntime.stop()
OnlyRuntime.close()
OnlyStreamingMarketDataWorker.stop()
OnlyObservationPublisher.stop()
MiniQMT DataSource.stop()
MiniQMT DataSource.close()
```

必须覆盖：

```text
stop 调用两次
close 调用两次
stop 后 close
close 后 stop
初始化部分失败后 stop
start 过程中 Ctrl+C
wait 过程中 Ctrl+C
stop 过程中第二次 Ctrl+C
Runtime 自身失败与 Ctrl+C 同时发生
```

要求：

* 同一个资源只执行一次有效关闭；
* 重复调用不得抛出无意义异常；
* 不得吞掉真正的首次失败；
* 清理异常不得覆盖最初异常；
* 最终状态必须明确；
* Engine、Runtime、Cluster Session 和 Handle 状态不能互相矛盾。

---

## 十三、建议代码结构

可以形成类似结构，但必须根据当前代码最小化实现：

```python
class OnlyApplicationShutdownReason(StrEnum):
    SIGINT = "SIGINT"
    SIGTERM = "SIGTERM"
    KEYBOARD_INTERRUPT = "KEYBOARD_INTERRUPT"


class OnlyApplicationStopController:
    @property
    def stop_requested(self) -> bool: ...

    @property
    def interruption_count(self) -> int: ...

    @property
    def exit_code(self) -> int: ...

    def request_stop(
        self,
        reason: OnlyApplicationShutdownReason,
    ) -> None: ...

    def install(self) -> None: ...

    def restore(self) -> None: ...
```

Application Runner 逻辑建议类似：

```python
def execute(self, engine: OnlyEngine) -> int:
    if only_engine_lifecycle_kind(engine) is FINITE:
        return engine.run().exit_code

    controller.install()
    try:
        engine.initialize()
        engine.start()

        while not controller.stop_requested:
            engine.wait(timeout=self._poll_interval)
            self._raise_runtime_failure_if_present(engine)

    except KeyboardInterrupt:
        controller.request_stop(KEYBOARD_INTERRUPT)

    finally:
        try:
            engine.stop()
        finally:
            controller.restore()

    return controller.exit_code
```

这只是设计方向，不要机械复制。

需要根据当前 Runtime Failure、wait() 语义和生命周期状态调整。

---

## 十四、测试要求

### 14.1 Application Runner 单元测试

至少覆盖：

```text
Backtest 仍只调用 engine.run()
Paper 使用有限 timeout wait
第一次 Ctrl+C 只调用一次 engine.stop()
SIGINT 返回 130
SIGTERM 返回 143
第二次 Ctrl+C 调用强制退出 Port
Signal Handler 最终恢复
初始化失败仍执行必要清理
start 失败仍执行必要清理
Runtime Worker Failure 不被轮询隐藏
```

保留 Mock KeyboardInterrupt 测试，但不能把它作为唯一中断验证。

### 14.2 Engine.wait 测试

覆盖：

```text
单 Runtime timeout
多 Runtime 总 timeout
timeout=0
timeout=None
Runtime 提前结束
Runtime wait 抛异常
```

验证 timeout 是 Engine 总预算。

### 14.3 POSIX subprocess 测试

Linux/macOS：

```text
启动最小长生命周期 CLI 子进程
等待 READY/RUNNING 标记
发送 SIGINT
限定时间等待退出
断言退出码
断言 Engine STOPPED
断言无 traceback
断言没有残留 OnlyAlpha 线程
```

再执行 SIGTERM 测试。

测试不得依赖真实网络、Tushare、MiniQMT 或 Broker。

### 14.4 Windows subprocess 测试

Windows 下使用正确的进程组机制：

```text
CREATE_NEW_PROCESS_GROUP
CTRL_BREAK_EVENT 或可稳定测试的控制台事件
```

测试流程：

```text
启动最小长生命周期 CLI
等待 READY
发送控制台事件
限定时间等待进程退出
检查退出码
检查 shutdown marker
检查无残留子进程
```

需要在测试注释中解释为什么选择该事件，而不是错误复用 POSIX API。

### 14.5 第二次 Ctrl+C 测试

使用可控的阻塞清理组件：

```text
第一次中断进入 graceful shutdown
故意让 fake plugin stop 阻塞
第二次中断
断言 forced exit port 被调用
断言没有再次调用 engine.stop()
```

不要在单元测试中真实杀死 pytest 进程。

### 14.6 MiniQMT 本地验收

新增显式本地 Gate：

```text
Windows only
requires_local_qmt
不进入默认 CI
不启用 Broker
不发送订单
```

测试：

```text
运行 examples/configs/miniqmt_paper_macd.yaml
等待进入 LIVE
发送 Ctrl+C 或控制台事件
检查全部 subscription 被取消
检查 Worker 停止
检查 Observation Publisher 停止
检查 Runtime CLOSED
检查 Engine STOPPED
检查 Python 进程退出
```

没有真实执行必须标记：

```text
NOT EXECUTED
```

不能写成 PASS。

---

## 十五、日志与诊断

正常中断建议输出简洁日志：

```text
OnlyAlpha shutdown requested: reason=SIGINT
Stopping Engine: engine_id=...
Stopping Runtime: runtime_id=...
Stopping Cluster: cluster_id=...
Closing market-data subscriptions
Stopping streaming worker
Closing persistence store
OnlyAlpha shutdown completed
```

不要输出大段 traceback。

如果关闭失败，需要包含：

```text
component
operation
timeout
resource_id
plugin_id
original shutdown reason
first failure
```

例如：

```text
Shutdown failed:
component=streaming-worker
operation=join
timeout_seconds=5
runtime_id=paper-main
```

第二次中断应输出：

```text
Second interrupt received; forcing process termination.
```

---

## 十六、验收标准

必须全部满足：

```text
[ ] Ctrl+C 表示退出整个 OnlyEngine
[ ] 不把 Ctrl+C 映射为单 Cluster stop
[ ] Backtest CLI 无回归
[ ] Paper CLI 使用有限时间等待
[ ] Windows Ctrl+C/控制台事件可退出
[ ] Linux SIGINT 可退出
[ ] Linux SIGTERM 可退出
[ ] macOS 使用统一 POSIX 路径
[ ] 第一次中断只启动一次 graceful shutdown
[ ] 第二次中断不会重复 stop
[ ] Engine.wait timeout 是总预算
[ ] OnlyEngine.stop/close 幂等
[ ] Runtime.stop/close 幂等
[ ] Cluster.on_stop 不会重复执行有效关闭
[ ] 所有 OnlyAlpha 自建非 daemon 线程能够退出
[ ] 所有 join 有上限
[ ] 所有外部订阅被取消
[ ] shutdown 后 Callback 不再进入 Runtime
[ ] 没有用 daemon=True 掩盖问题
[ ] 没有吞掉 Runtime Worker Failure
[ ] 没有启用真实 Broker
[ ] 没有发送真实订单
[ ] 文档不宣称保存完整 Streaming 状态
[ ] 静态检查和相关测试通过
```

响应时间目标：

```text
Ctrl+C 到开始 shutdown       < 1 秒
离线测试 Runtime 完全退出     < 3 秒
单个线程 join                 有明确上限
第二次 Ctrl+C 到强制退出       尽快完成
```

如果平台限制导致无法达到，必须提供实测数据和原因。

---

## 十七、非目标

本任务不实现：

```text
单 Cluster 动态 stop/pause/resume 产品接口
Engine Control Plane
Web API
Unix Socket
Windows Named Pipe
Streaming Checkpoint
Paper Restart Recovery
Reconnect
Realtime Gap Recovery
Live Runtime
真实 Broker
账户同步
仓位同步
真实下单
CN_A_SHARE Durable Execution
Research Runtime
```

发现相关现有代码时，只审计其对退出链的影响，不扩展产品范围。

---

## 十八、最终交付内容

完成后输出以下内容。

### 1. 根因

说明为什么现有 `except KeyboardInterrupt` 不足，以及真实阻塞点。

### 2. 架构设计

说明：

```text
信号权威
Stop Controller
等待模型
第一次中断
第二次中断
Engine/Runtime/Cluster 责任边界
```

### 3. 修改文件

逐文件说明修改内容。

### 4. 生命周期时序

提供完整时序：

```text
SIGINT/SIGTERM
→ Application Stop Controller
→ Engine wait loop exits
→ OnlyEngine.stop
→ Runtime stop/close
→ Cluster stop
→ Subscription cancel
→ Worker stop
→ Observation stop
→ Plugin close
→ Persistence/EventBus/Clock close
→ Process exit
```

### 5. 测试结果

分别列出：

```text
Unit
CLI
Engine
Runtime
POSIX subprocess
Windows subprocess
MiniQMT contract
Real MiniQMT local gate
```

未执行项目必须标记 `NOT EXECUTED`。

### 6. 剩余风险

说明：

```text
第三方 SDK 线程
第二次强制退出可能丢失的数据
Paper 当前没有 Streaming Checkpoint
未执行的真实平台验收
```

最终目标：

```text
OnlyAlpha 长生命周期 CLI
能够在 Windows、Linux 和 macOS 上响应 Ctrl+C/SIGTERM，
通过唯一 OnlyEngine 生命周期完成有界、幂等、可诊断的优雅退出，
停止全部 Runtime 和 Cluster，
释放所有 OnlyAlpha 自有资源，
并保证 Python 进程最终退出。
```
