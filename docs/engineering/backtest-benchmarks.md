# 回测链路性能测量

这套测量覆盖当前 BTC next-open 回测的输入重建、Runtime 读取、Execution 恢复、终态核验、结果投影，以及正式应用中的证据发布和请求响应。结果留在 `test-results/` 或调用方指定位置，不新增验收 Authority，不改变已有 120 秒、300 秒门槛。

## 离线模块基准

终态与结果组合入口为 [后端组合bench](../../packages/backend/benches/backtest_chain.rs)，由Cargo bench显式运行。逐库入口及限制见 [覆盖矩阵](backtest-performance-coverage.md) 与各库BENCHMARK.md；组件恢复由Execution自己的 [recovery bench](../../crates/execution/benches/recovery.rs) 测量。原忽略测试中的基准职责已迁入benches，功能断言保留在新入口。

在固定onlyalpha-dev冻结验证环境执行：

```sh
python3 scripts/dev_verification.py run -- \
  python -m scripts.run_rust_benchmarks reference \
  --runtime-root /workspace/test-results/.../runtime/<run-id> \
  --trace /workspace/test-results/.../replay-trace.json \
  --output /workspace/test-results/backtest-observability/<new-directory>
```

`--crate account`等参数可选择模块；check仅编译，smoke预检短目标，reference采集正式样本。缺少外部输入时慢目标明确标为未运行，不能视作完整基线。输入摘要绑定当前冻结的bench入口、辅助代码与fixture；保留目标额外绑定SQLite文件摘要，后端必须提供对应的完整原始trace，不能用binding/inputs提取文件代替。采样前后核对源文件摘要，不产生正式发布证明。使用当前实现解释历史输入只用于技术比较，正式历史读取仍由应用的原工件绑定检查负责。

运行器使用既有compiler_environment准备离线Cargo环境。短操作采用Criterion，慢目标默认固定三轮、逐轮完整断言；源数据库计时前hash会预热文件缓存，不声称OS冷缓存。直接Cargo入口供已配置等效工具环境调用，不新增第二套应用拓扑。

阶段名与口径：

| 阶段 | 内容 |
| --- | --- |
| `inputs.decode` | 正式 Inputs 解码、身份和排序检查 |
| `preparation.rebuild` | 原策略、规则、输入和固定样本窗口重建 |
| `runtime.snapshot.read` | SQLite 只读快照、原始执行记录及 checkpoint 核验 |
| `runtime.steps.read` | 读取全部回放 step |
| `runtime.verify_cut` | 再次完整核验来源切面 |
| `execution.checkpoint.digest` | 完整组件 checkpoint 编码和摘要 |
| `execution.components.new/restore` | 独立组件恢复基准中的组件创建、全量恢复和内部完整性校验；额外的恢复后完整 checkpoint 断言计入总耗时 |
| `terminal.read/verify_cut/trace.verify` | 终态、原始执行语义及保留轨迹核验 |
| `result.from_terminal` | 从完整终态产生正式结果投影，包括其来源复核 |
| `result.serialize_digest` | 结果编码与摘要 |
| `chain.total` | 截至结果摘要输出前的步骤与阶段间准备、析构等开销；不含循环末尾仍持有对象的最终析构 |

Execution模块基准分别记录Components创建、模型捕获、编码、digest、完整restore及准入成功/拒绝的cold/reused路径，完整checkpoint相等是前置条件。它与后端只读组合使用不同scope与work unit，不把不同场景直接相除。

各基准内的阶段依次执行，各阶段内部仍可能重复读同一来源。`chain.total` 是该只读基准总耗时，不是一次正式 Web 回测总耗时，也不包含行情获取、策略运行、数据库准入或正式发布。当前准入基准见Execution的BENCHMARK.md。旧 [保留终态准入调试探针](../../crates/backtest/tests/admission_preview_profile.rs) 仅用于阶段一67个技术拒绝输入的历史复现，不属于统一可比较基线；其错误结果不可当成真实容量拒绝或整体提速证据。

## 正式流程的分段观测

后端服务角色默认 Basic，只保留摘要和异常。`ONLYALPHA_DIAGNOSTICS=off|basic|detail` 显式选择模式；`ONLYALPHA_DIAGNOSTICS_PATH` 指定一个尚不存在的独立 JSONL 文件（0600），未指定时写 stderr。库不读取环境或安装全局 subscriber。纯导出、运维及算法协议角色不初始化诊断。

定向 Web 验证的 `--backtest-profile` 兼容入口仍传递 `ONLYALPHA_BACKTEST_PROFILE=1`，现在选择统一 Detail，而非旧私有计时器。显式模式优先。新事件使用 `schema_version=1`，按 process_instance、trace/span、request/command/run 关联。进程结束的 `ONLYALPHA_DIAGNOSTIC` 关闭收据需与 JSONL 一同保留。

观测覆盖准备后台任务、原 Work 恢复/回放、证据发布、from_proof、writer 等待/持有、finalize 原三次 proof 检查、SQL 事务/提交、终态清理，以及 GET 的 read_context/read_verified、投影/编码、handler、响应体和 socket 写出。Runtime Source 记录实际 rows、checkpoint 原字节和原校验阶段，不为打桩再读或编码全量源。无计数阶段的零值不证明工作量为零。

future 使用 Instrument/WithSubscriber，阻塞闭包显式传播原 Dispatch。父未覆盖时间按直接子区间的并集扣除，包含 await 与排队，不解释为 CPU 或算法独占。锁持有作为独立资源根，通过 links 和原 device/inode 关联；只认覆盖整个争用尝试的可证明持有区间，缺证及跨进程持有者保持未知。

响应体观测只到上层消费者（受保护读会由 ingress capture 先完整读取），socket 成功只证明底层接受相应字节；客户端是否收到 200 由浏览器响应证据确认。固定连接关闭策略使同一物理 connection 关联请求与写出，但关联号不进入正式业务身份。诊断错误、丢失和截断不替代业务错误或 CompletionProof。文件存在不能替代来源核验或 SQL 终态提交。

## 汇总与前后比较

```sh
python3 -m scripts.backtest_benchmark \
  --log test-results/.../profile.log \
  --trace test-results/.../trace.zip \
  --output test-results/.../report.json

python3 -m scripts.backtest_benchmark \
  --log test-results/.../new-profile.log \
  --baseline test-results/.../baseline.json \
  --output test-results/.../comparison.json
```

报告包含每个阶段的调用次数、累计时间、中位数和 p95，分别保留失败和不完整调用。Playwright 请求只摘出方法、路径、状态码、耗时和流程状态/错误码，去掉查询参数和正文敏感内容。`BLOCKED/STOPPED` 与长期等待中的命令必须分别分析。

性能比较要求所有轮次和阶段完整、每轮结果摘要一致，并核对相同输入摘要、配置、构建模式、编译器、操作系统、架构、缓存口径和存储标签。本次测试程序的二进制摘要单独记录，不能把历史 trace 的 `kernel_artifact` 当成被测构建身份。还需保留本次冻结源码摘要、编译器、CPU/内存、容器配置、存储挂载及并发任务情况；这些信息随固定验证日志和环境记录保存。切换硬件、存储或缓存条件后重新建立基线，不把不同条件的比值当作代码收益。默认只报告变化，不自动新增或放宽 CI 性能门槛。出现连续异常超时、资源压力或 Docker 异常时停止该轮验证，保留原始日志。

模块报告的 `environment.storage` 采用独立的 v1 描述：按实际临时目录、保留数据库及 trace 路径选择最长匹配挂载点，保留文件系统、挂载来源/根和选项，排除 overlay 临时层目录及挂载序号。缺少实际输入所在存储、缺少此描述或存储不同，均拒绝比较。历史报告仍可展示原测量；只有从原始 identity 和确切路径证据补证、保留原记录及迁移来源后，才可重新用于比较，不能从当前环境猜填历史环境。

## 固定开发镜像的同版本浏览器缓存

已有固定 validation 镜像但官方浏览器下载不可用时，可显式运行 `python3 scripts/dev_verification.py --rebuild --reuse-browser-cache prepare`。这个选项仅用于镜像准备；普通 run 不下载、不重建。它要求当前工具镜像与已归属 validation 容器的镜像身份一致，前端 package.json/package-lock.json 摘要与镜像原记录一致，Playwright 版本与锁文件一致，浏览器安装完成且必需文件可执行。

准备流程只读、无网络地核对原镜像的浏览器树，按内容与权限计算 SHA256，绑定不可变镜像身份；构建中再次核对同一摘要，仅复用浏览器缓存。新源码、Rust 依赖和原镜像准备步骤仍来自当前输入，不用旧应用二进制代替当前构建。输入不匹配直接拒绝，不自动回退到另一版本。缓存接收记录保存到 test-results/dev-verification/browser-cache-<operation>.json，不进入正式 Run、checkpoint 或证据摘要。

模块报告可经同一汇总入口合并：为 `scripts/backtest_benchmark.py` 增加多个 `--module-report <report.json>`；使用对应 `--module-baseline` 比较同一组case。缺样本、重复case及输入/结果/环境不相容直接拒绝。模块参考成本与真实链路时间保持各自口径，汇总不自动推导跨场景速度收益。

## 单次 Web 实战诊断

原 `e2e/backtest.spec.ts` 的 300/120 秒门槛保持。独立入口为 `e2e/backtest-diagnostics.spec.ts`，只能配合 `--backtest-diagnostic --controlled-source-https --retained-market-input --backtest-market-input` 单独运行；禁止同时选其他场景、grep、重启验收或 fuzz。它通过普通 Web 新建一个 Run，在已观察到原 Run 共享 Generation cut 后发起一次独立准备，再从普通回测记录触发一次终态 GET。不会反复提交 BLOCKED 命令，也不将争用准备等同于取消成功。

总预算1200秒从普通 Web 操作开始（编译不计）；浏览器协调器最多1160秒，为原20秒 Host 排空和进程清理留余量。客户端超时保持，响应/失败后正常离开该浏览器上下文，继续只读观察原服务端阶段。日志探针只增量读取新增完整行；SQL 探针采用只读事务、固定 `_test` 数据库及 namespace/原 Run 核对，所得状态仅供协调，不构造完成证明。

`diagnostic-browser.json` 记录原门槛观测、原 Run、一次争用准备和客户端结果。收到响应头不证明完整响应体已收到。应用 handler 返回状态与 ingress 最终返回状态、响应体交接和底层 socket 写入应分别分析，不能把内部200写成用户成功。`diagnostic-budget.json` 记录实际预算和中断，输出故障/缺 end/强杀仍标不完整。首次取证到期或资源压力停止后保留数据，后续完整取证需重新确认预算。

正常排空并取得独立关闭收据后，协调器还会生成 `diagnostic-completion.json`：核对唯一 session、原 Host PID/process instance、关闭时钟、零丢失/零 I/O 错误和完整关闭，再经严格 JSONL reader 检查起止关联与覆盖。缺证或协议异常会否决浏览器的零退出结果。这个结果只描述诊断采集，不是业务完成证明；中断或生命周期异常仍保留原失败，不能视作采集成功。

统一 JSONL 汇总中的 `runs` 包含阶段根、调用热点、实际工作量、包含成本和父未覆盖 wall time。阶段树通过原 process/span/parent 索引展开，资源根通过 links 关联；并发阶段的包含成本不能相加冒充整体延迟。仅有 wall 区间不能证明 await 依赖关键路径，需结合原调用点分析，缺证保持未知。

## Witness 完整性失败诊断

`evidence.witness.failure` 在原失败分支记录具体 `file_path`、静态失败谓词 `error_code`、`expected_value`、`actual_value`，以及存在时的原始数字 `errno`。字段长度和隐私限制见 [日志库](../../crates/observability/README.md)。inode/device/size/digest 按原短路顺序检查，只报告首个失败；不增加业务文件读取或摘要计算，不改变原业务错误码。日志写入故障与业务返回值分开。

隔离文件回归见 [Witness 测试](../../packages/backend/src/tests/research_evidence_witness.rs)，覆盖原失败分支及 Off/Basic/Detail 一致性。显式忽略的保留文件诊断只能通过固定验证入口启用，输出是技术观测，不构成历史工件或完成证明。未复现、缺失原 Witness 期望值或缺少完整关闭收据时，根因保持未确定。不得据此放宽校验或重置原证据。
