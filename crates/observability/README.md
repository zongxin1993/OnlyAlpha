# onlyalpha-observability

## 目的与职责

提供版本化 JSONL 诊断、显式操作生命周期和跨任务关联，帮助分析调用次数、存续时间和日志覆盖。诊断不是正式回测证据，不拥有交易、权限、恢复或状态更新 Authority。

## 边界与依赖

依赖 tracing 传播上下文、tracing-subscriber Registry/Layer、tracing-appender 有界非阻塞 writer 和 serde_json 编码。生产依赖不含业务 crate。库不读取环境、不打开输出文件、不安装全局 subscriber；后端入口负责配置、输出、进程实例身份和唯一初始化。纯内核不依赖本库。

## 公开接口

[Config/Mode](src/lib.rs) 显式指定 off/basic/detail、进程实例 ID 和队列容量；空 ID、过长 ID 或零容量返回 OBSERVABILITY_CONFIG_INVALID。

[Session](src/output.rs) 接收调用方提供的 Write，返回本地 tracing Dispatch。Off 不创建 writer 线程。Basic 保留摘要/异常，Detail 保留目标链路操作。输出只接收白名单原生字段；动态 Debug 不格式化，不记录任意正文。高基数关联 ID 仅进入日志。 Witness 失败摘要 `evidence.witness.failure` 使用 `file_path`（最多4096 UTF-8字节）、`error_code`（失败谓词）、`expected_value` 和 `actual_value`（各最多256字节），可附原始数字 errno。只记录路径、元数据、摘要和固定分类，不记录文件正文或异常正文；无法取得实际值时记录明确的不可用分类。超限字段被丢弃，离线解析器会拒绝不完整的 Witness 摘要。

[Operation/Correlation](src/context.rs) 创建当前父操作或独立根操作。后台根任务以 links、command_id、run_id 关联请求，不伪造活跃 HTTP 父操作。finish 记录明确结果、工作项数与字节；未 finish 的 drop 记录 incomplete，不冒充成功。

[measure/measure_counted](src/lib.rs) 只测量一次原同步闭包，保留原结果、错误和 panic；计数采用调用方已有的输入规模，不重新读取或编码业务输入。未提供计数的零值不表示证明没有工作。

[Marker](src/context.rs) 提供固定的锁等待、获得、释放前、释放后、争用和失败事件。`Correlation::linked_current()` 复制当前诊断关联，供独立资源根使用；它不创建业务身份。文件锁身份采用原文件描述符验证过的 device/inode，获得后到关闭前的保守区间用于离线关联。缺少完整事件、存在丢失或跨进程时归属保持未知，不能断言不存在外部持有者。

## 状态与生命周期

每次进程启动必须使用新 process_instance_id。操作时间采用进程内单调时钟，表示包括 await/排队的存续时间，不表示 CPU 或 poll-active 时间。future 使用 tracing Instrument/WithSubscriber；阻塞线程显式携带 Dispatch/Span，不跨 await 持有 enter guard。

每个 Session 使用递增的诊断 span_id，并从父操作复制其诊断 ID；不直接暴露会循环复用的 Registry 槽位 ID。span_id、parent_span_id 与 links 仅用于诊断关联，不进入业务身份或正式摘要。

生产者必须在 Session.close 前停止并 join。close 使用上游 WorkerGuard 的有界关闭（入队最多100ms，flush 协商最多1000ms），返回 Receipt。调用方将 receipt.record() 保留在独立诊断 stderr 或协调器收据，并与 JSONL 一同分析。缺少关闭收据、丢失、I/O 错误或未闭合操作时不能宣称完整计数。堵塞 writer 不无限等待；上游关闭入队超时可能向服务进程 stdout 输出故障信息，因此本库不得在算法协议/纯导出角色初始化。

Writer 故障不改变业务返回值。调用方提供的 Write 不应 panic；本库不捕获或恢复任意用户 writer 的 panic。Span handle 的释放时间不决定操作结束时间。

## 使用与验证

在正式开发环境运行 `cargo test -p onlyalpha-observability` 和对应 Clippy；[上下文测试](tests/context.rs) 覆盖并发、阻塞交接、独立根和重启关联，[输出测试](tests/output.rs) 覆盖队列丢失、存储错误、有界关闭和隐私。临时纯库快照仅用于 RED/GREEN，不代替完整冻结工作树回归。

离线时间归因见 [observation_report.py](../../scripts/observation_report.py)：直接子阶段按区间并集计算，锁持有区间独立展示；缺证不会被换算为无调用。观测自身成本见 [BENCHMARK.md](BENCHMARK.md)。
