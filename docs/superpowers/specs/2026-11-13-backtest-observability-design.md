# 回测模块基准与后端可观测性设计

状态：方案草案，待负责人确认；本文件不授权实施，不构成新的业务事实或验收 Authority。

## 目标与边界

建立可长期使用的逐库 Rust 基准、逐库 BENCHMARK.md，以及统一后端结构化日志/链路追踪库。第一个实际交付是利用这些能力分析当前回测慢、发布长尾、准备锁冲突和终态请求响应，提供能复核的归因报告。

本轮实施仅包含基准、诊断设施、观测接入、测试与说明。原 Account/估值重放优化的第二阶段不启动；不删减完整性核验，不更改交易、恢复、事实身份、权限、租约或存储格式，不放宽 Web 300/120 秒和退出 20 秒预算。速度优化根据分析结果另行提出。

Constitution Impact：NO。遵守确定性、单一 Authority、边界和可恢复性；日志是可丢失的诊断副本，不能作为成交、准入、恢复或完成状态的事实来源。普通日志失败不改变原业务 Result，不通过吞掉业务异常取得成功。

## 当前实现与实战依据

现有代码包含两组真实输入的 ignored Rust 测试基准、后端同步 backtest_profile 计时器及 Python 汇总器。后端计时器采用线程局部父子关系，仅适用于同步嵌套，不能直接推广到跨 await/线程的完整链路。

上一轮固定环境实测：单个末尾 checkpoint 恢复中位 0.587 秒，Runtime 完整读取约 11 秒；终态读取约 54 秒，结果投影入口约 44 秒，内部均包含来源复核。正式 Web 中 commit 已观察至少 256.544 秒未返回，文件写入仅 72 ms；实际出现非阻塞独占锁 errno 11，准备进入 BLOCKED。此前日志没有锁对象及命令关联，持锁者归属依赖调用链与时间推导。

成功路径静态计数为 commit 24 次 Source::read、发布后确认及清理再 17 次；终态 GET 自身还会读 11 次。这些是需要实战核实的假设，不能作为真实失败现场的调用次数或用乘法冒充实测时间。

## 选型与替代方案

| 选择 | 能覆盖的需求 | 代价与结论 |
| --- | --- | --- |
| 保留并扩写现有自制同步计时器 | 小范围同步调用成本 | 跨任务关联、并发统计、输出生命周期都需自研；不作为统一设施 |
| tracing + tracing-subscriber，OnlyAlpha 封装字段/采集/报告 | 结构化事件、异步 span、过滤、上下文传播 | 推荐；复用现有锁文件中的 tracing 0.1.44，新增订阅器需审批及锁版本 |
| 首轮同时部署 OpenTelemetry Collector/日志检索服务 | 多进程集中检索 | 引入服务、存储及运维成本；本轮不部署，保留未来适配空间但不预建接口 |

短操作基准建议使用 Criterion；多秒或多分钟的恢复/整链路使用固定次数的 Cargo bench 慢场景，避免自动采样使运行成本失控。两类都进入 benches/，由统一运行器收集成同一报告格式。Criterion 仅作开发依赖，不进入纯内核生产依赖。

依赖变更拟包含 tracing 直接使用、tracing-subscriber、Criterion；若非阻塞输出确需 tracing-appender，应在依赖审查中一并确定，不自研轮转/日志队列框架。全部只选正式发布版本，核对许可、MSRV、依赖闭包、现有 Tokio/Serde 及冻结离线镜像；固定精确版本及 Cargo.lock，禁止跟随上游主分支。方案批准后才实施依赖与固定开发镜像更新，不新增部署服务。

官方依据：
- https://docs.rs/tracing/latest/tracing/trait.Instrument.html — future 的正确 span 传播。
- https://docs.rs/tracing/latest/tracing/span/index.html — 不跨 await 持有 enter guard。
- https://docs.rs/tracing-subscriber/latest/tracing_subscriber/fmt/index.html — 订阅器由应用初始化，库只发事件。
- https://bheisler.github.io/criterion.rs/book/user_guide/benchmarking_with_inputs.html — 输入规模与 throughput。

## 覆盖清单

先核对真实调用入口，再冻结“模块—操作—输入—基准—链路 span”矩阵。Cargo 依赖闭包是候选范围，不等于每种算法均实际执行。

当前 backtest 的本地依赖闭包包含 21 个 crate：account、backtest、broker、calculation、calculation-bridge、clock、domain、execution、fee、margin、market-data、market-data-construction、operators、order、position、predicates、risk、runtime、settlement、strategy、strategy-ledger。

另核对后端回测准备/校验路径中的 indicators、metadata-json、integration-contract。只做注册/元数据读取的模块按实际调用能力测量，不宣称覆盖了未执行的计算算法。event 等未证明使用的库不补空目录或虚假用例。插件与后端组合成本另列，不能靠 crates 基准宣称已覆盖行情来源、规则插件或 HTTP/数据库全流程。

| 分组 | 必须覆盖的实际能力 |
| --- | --- |
| domain / clock / predicates | 回测消费的解析、比较、时间转换、判定与边界输入 |
| operators / indicators / calculation / strategy | 实际节点的单步/批量更新、窗口、图推进、状态捕获/恢复；区分注册与执行 |
| account / position / order / strategy-ledger | 实际状态更新、估值、查询、checkpoint 编解码、冷恢复、历史长度增长 |
| risk / fee / margin / settlement / broker | 实际检查/计算、成功与拒绝路径、被调用的状态重建 |
| execution | 组件创建、apply/准入路径、冷恢复、前缀复用、检查点及不同拒绝原因 |
| runtime | 日志追加/读取、Source::read、各 checkpoint restore/prefix compare、verify_cut、恢复 |
| backtest / calculation-bridge / market-data 及 construction | 输入准备、节点调用、事件推进、终态核验、真实样本只读与计算/进程边界 |
| 后端及插件 | 准备、行情装配、任务排队、规则、发布、SQL 状态提交、清理、请求响应与锁 |

## 逐库基准与 BENCHMARK.md

每个实际涉及的库拥有 benches/ 和 BENCHMARK.md，README 链接其使用入口。单独列明：目标函数、功能断言、吞吐单位、计时范围、是否含准备/析构/I/O、输入规模、冷暖状态、失败路径、运行命令、参考基线、限制。

- 短操作：Criterion 分组，使用真实公开接口、black_box，正确处理每轮状态初始化，避免只测热循环或累积状态混入不同工作量。
- 慢操作：至少三次原始完整样本；预算/次数在运行前明确。显式区分首轮、预热轮和测量轮；无清缓存操作时不能声称 OS 冷缓存。样本不足时不输出可信尾延迟结论。
- 每个状态规模取小/中/大三档；具体档位由真实样本确定并固化在矩阵，包含当前 740-bar 和约 326 条执行记录的场景。报告增长曲线，不能仅有一个吞吐量数字。
- 功能正确性是前提：输入/输出摘要、状态和错误原因必须匹配预期。成功与拒绝、创建与恢复、原始对照与复用分别报告。
- 公共接口不足时不为基准扩大业务公开接口；先按公开操作测量，保留现有私有功能回归测试。不能用成本近似实现替代正式路径。
- 单处 fixture 归所属库 benches/；跨库共享的确定性数据放 test-data/。真实数据须隔离、无凭据，并保留配置/工件/数据来源约束；历史输入的技术比较不伪装成当前镜像的正式历史读取证明。

BENCHMARK.md 保留方法及一份有来源的参考基线。原始样本、历史跑分、环境、二进制及源码摘要保存在结果目录，由文档引用；不不断追加临时进度。不同代码构建允许比较，但输入、场景、预期结果、环境及缓存口径必须相容。语义有意变化时独立审查并建立新基线，不能为了比较修改结果断言。

## 新基础设施库

目录为 crates/observability，Cargo 包名 onlyalpha-observability。作为可复用基础设施库，使用 workspace 版本，不独立部署或新增发行服务。

依赖方向：backend 初始化订阅器并管理生命周期；runtime/backtest 等实际基础设施部分发事件；纯内核生产依赖不引入时钟、环境、文件输出或订阅器。纯内核的 bench 使用 Criterion 等开发依赖，不统一强制依赖观测库。第一版不在纯 Account/Order/Position 算法内部增加环境驱动计时钩子，先用模块基准和调用边界定位；需要更深的内部观测时单独设计显式接口。

库不依赖 backend 或业务 crate，职责如下：

1. 版本化诊断事件格式、span 生命周期与关联标识。
2. 基于 tracing 的上下文与后端配置/输出组合，不自研另一套通用 tracing 调度机制。
3. 有界采集、状态统计、丢失与截断标记、关闭/刷新生命周期。

逐库基准先落地，统一执行和比较由现有 scripts/backtest_benchmark.py 扩展。日志库不兼任基准运行器，报告层关联模块基线与实际调用成本。

建议文件：src/lib.rs、context.rs、layer.rs、output.rs、schema.rs；tests/ 放协议、异步传播和故障测试；benches/ 测观测开销。README 包含规定的五个章节，BENCHMARK.md 记录自身成本。

配置只有 off/basic/detail 三档：basic 为应用摘要/错误日志；detail 用于本次隔离诊断，目标链路完整采样；off 用于开销对照。后端 bootstrap 解析配置并初始化一次，库不得自行安装全局 subscriber 或读取环境。已有诊断开关在迁移期映射到 detail，迁移完成后移除重复计时实现。

## 事件、关联与时间口径

字段白名单：schema_version、event_kind、process_instance_id、pid、trace_id、span_id、parent_span_id、links、request_id、command_id、run_id、attempt、module、operation、outcome、mono_ns、start_mono_ns、end_mono_ns、duration_ns、wall_time_unix_ns、work_items、bytes、error_code；锁事件附锁类型、设备/inode 等对象身份和原始 errno。关联标识仅供诊断，不参与业务身份计算。

- 请求接受命令后结束，后台任务以 command_id/run_id 关联并建立因果 link；不伪造仍然活跃的 HTTP 父 span。
- 跨 tokio task 用 Instrument 传播；spawn_blocking 显式传递 span；跨进程以已有生命周期边界的诊断字段/父子进程记录关联，不改变数值 IPC 或正式 API 请求契约。
- 不跨 await 持有 Span::enter guard。不能沿用现有线程局部栈追踪异步父子关系。
- 每个 process_instance 记录自己的单调时钟原点；start/end 事件带相对原点的 mono_ns，闭合操作带 start_mono_ns/end_mono_ns/duration_ns。墙钟用于跨日志排序，不能据此计算精确跨进程独占时间。
- 第一版测量显式 operation_start 到 operation_end 的操作存续时间，包含 await/排队，不以最后一个 span handle 被丢弃的时刻代替操作结束；不采集 poll-active 或 CPU 时间。异步活跃 poll 与 CPU 归因另行扩展，不从 enter 次数推断。
- 并发子阶段计算父跨度的区间并集，禁止简单相减得到负独占耗时；跨进程只有时钟证据足够时才合并区间，否则单独报告。嵌套累计成本与关键路径 wall time 分开。
- 拿锁前记录 wait，成功后记录 hold/释放；非阻塞失败记录 contention 与 errno。使用原锁 fd 的已有身份信息，关联当前持锁操作/Run 和争用 command；诊断关联表不控制锁或授权。
- 异常/取消使用已知语义；进程强杀或缺失结束记录标记 incomplete，不伪造成功/完成耗时；数据丢失时报告覆盖不足。

输出首版为独立 JSONL 和离线报告，不占用算法协议 stdout。复用成熟 writer，生产路径有界非阻塞，普通日志丢失可见；不能承诺队列满时日志既绝不丢失又绝不阻塞。发生 I/O 故障或队列溢出不修改业务返回值，报告 diagnostic_loss，不把缺日志推断为无调用。受控诊断需要无丢失才能作完整计数。

不记录凭据、完整策略正文、账户持仓/订单正文、原始请求体或动态任意 Debug。指标标签使用低基数的模块/操作/结果类型，run_id/command_id 留在日志/span，不作为指标标签。首轮只汇总本地指标，不另建 Prometheus/OTel 服务。

## 当前回测的首轮接入

完整覆盖：HTTP 准备/确认 → 行情与策略准备 → 命令排队/认领 → Work 恢复 → 回放 → 终态/结果 → commit → from_proof → finalize/SQL 提交 → terminal 清理 → 终态 GET 响应。

重点文件：
- packages/backend/src/transport/host_backtest_preparation.rs、host_backtest_environment.rs、host_backtest.rs。
- packages/backend/src/workers/backtest_worker.rs、backtest_service.rs、backtest_result.rs。
- packages/backend/src/persistence/backtest_evidence/context.rs、store.rs、backtest_run.rs、research_runtime.rs。
- crates/runtime/src/readonly.rs、store.rs：Source::read、schema/records/checkpoints、各 restore/compare、源切面比较。
- crates/backtest 的终态入口与基础设施组合边界；pure native_read 通过外侧入口测量，不借 helper 绕过纯性检查。

为每次 Source 读取记录入口原因、记录数、checkpoint 数/序号、总字节数、调用次数与子阶段成本，区分真正 I/O、解码、恢复、前缀核对、最终比较。I/O span 的 wall time 仍不等于纯磁盘时间。不能为采集数量再做一次全量 JSON 编码或来源读取。

## 首次实战产物与验收

必须交付：逐库覆盖矩阵与基线、统一 JSONL、按 Run 的阶段树/时间线、热点表（次数/总成本/单次分布/工作量）、锁争用关联、异常与截断表、构建/输入/环境及诊断模式开销对照。

报告必须回答：
1. 实际 Source::read 各调用方是谁，执行多少次，每次恢复/比较哪些 checkpoint？
2. 单次模块慢、调用放大、排队、锁等待各贡献多少？主要未知差额在哪里？
3. 文件落盘前后分别用时多少，from_proof、writer 等待/持有、SQL 提交、清理和终态 GET 分别用时多少？
4. 哪个 Run/持锁操作阻止哪个 preparation command，原始 errno 和状态如何对应？
5. 日志/采样/并发/编译与测试准备是否干扰结论；数据是否完整？

### 独立完整取证运行

完整发布尾段及至少一次终态 HTTP handler 的实测是首轮实战的硬交付。新建 packages/frontend/e2e/backtest-diagnostics.spec.ts 及对应原拓扑协调入口；使用已有普通 Web 资产准备/启动步骤，不做浏览器注入、直接数据库改状态或旁路准入。

该入口是单次受控诊断，建议整体观测预算 20 分钟（从正常 Web 操作开始计，编译不计入），用于当前约十余分钟的长尾取证；这是本方案需要负责人确认的新增预算，不替代原 Web 300/120 秒通过标准。记录跨越原性能预算的事实并标记未达标，不能因为取证完成把功能失败改成通过。原测试文件的超时和断言不改；不把两个原场景连续超时后继续等待作为取证入口。

取证使用新代码真实 Shipping 工件、隔离命名空间和固定 740-bar 输入，通过普通 Web 明确创建一次诊断 Run；它是受控复现，不替换之前未完成的 Run，不重写历史工件身份。运行内唯一的 run_id 保持到发布、数据库终态、清理和请求观察结束。若需要重启只允许原工件/原 Run，不能自动创建另一个 Run 代替 UNKNOWN；首次运行不强制做恢复场景。

协调器通过已记录 trace 的 stage 观察控制采集时机，业务动作仍经 Web/API：
1. 从正常 UI 启动一个 Run，完整观察准备/运行/commit/from_proof/finalize/cleanup。
2. 在已确认首 Run 持有 Runtime 共享 cut 的期间，普通 UI 发起一次独立准备命令，观察其正常错误反馈及正式响应，关联锁对象、持锁 Run 和争用 command。不会反复提交或等待已 BLOCKED 的命令变 READY，也不将此当作实际取消成功。
3. 通过正常回测记录/结果入口发起一次终态 GET，记录服务器读取、编码、响应写入及客户端断开。保留原客户端请求超时；若浏览器超时，记录失败，停止重复触发同一重读取（关闭该测试浏览器上下文是正常用户离开），继续观察原 handler 完成/取消直至它的 span 明确结束。采到服务端结束不等于客户端收到结果。

诊断完成条件是发布、SQL 状态及 Runtime 工作清理均有结束证据，终态请求有闭合的服务端 span/明确失败状态，所需事件无丢失。HTTP 超时/断开允许作为本次慢问题的结果，但必须有服务端阶段成本证据，不能伪称 200 或用户看到结果。

20 分钟到期、资源压力、非预期的连续异常、采集失真或三次失败规则触发时停止、保留数据和实际清理状态；不自动延长或换名重跑。若完整阶段仍未采到，首轮实战验收保持未完成，先与负责人商议下一次取证，不以静态乘法补齐。SIGTERM/20 秒排空规则保持，强杀如实标记。

最终可以判定诊断设施与基准交付完成，但不能因此宣称回测速度已修复或第一阶段产品验收通过。热点确认后另提最小修复计划。
