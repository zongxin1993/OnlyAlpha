# 后端回测组合基准

## 职责与入口

`cargo bench --frozen --offline -p onlyalpha-backend --bench backtest_chain` 测当前公开的准备、Source、终态验证与结果投影组合。它只读受控保留样本，不发布Product证据，不替代Web/API验收。Rust库自己的基准见各crates下的BENCHMARK.md。

## 输入、边界与运行

通过统一运行器 `python -m scripts.run_rust_benchmarks reference --crate backend --runtime-root <test-results内绝对runtime目录> --trace <原始完整replay-trace.json> --output <新结果目录>` 执行。默认3轮，绑定740bars/326执行记录/1482回放记录（1481推进步加初始记录）/6checkpoints。源码、配置、数据和当前实际可执行文件摘要独立记录；源数据库计时前hash，不能称OS冷缓存。12阶段包括整体chain.total，父子包含耗时不叠加；构造/读取是否计时以源代码measure边界为准。

## 参考基线

2026-11-13，固定 onlyalpha-dev，Linux aarch64，Rust 1.99.1，bench/release优化，单编译任务。源码冻结摘要 `231de76e92685fc5e311c602c6626fe8c21ffd6dfdaa14c995b13938ba0f855f`。首个target输入摘要 `c67ba79921b746cda30545537cbddfe6aa8380d87702044ab3ab02ed45c0d181`；各target独立的输入、结果与二进制SHA256见原始identity.json，不把历史kernel绑定作为当前构建身份。

Criterion为每case至少10个原始样本；表中使用Criterion的median估计。固定慢样本使用3轮中位数，不据此推断可靠尾延迟。状态准备、缓存和析构边界以本页方法说明及case源码为准；没有清OS缓存，也没有硬件独占。原始结果：`test-results/backtest-observability/reference-backend-02/backend/`（本轮位于主工作区）；包含build、identity、reference.log、report及Criterion原始样本。

| 场景 | 每次工作量 | 中位耗时 ms | 吞吐 /秒 | 样本数 |
| --- | ---: | ---: | ---: | ---: |
| chain.total | 1 chains | 135711 | 0.00736858 | 3 |
| execution.checkpoint.digest | 1 chains | 4.25704 | 234.905 | 3 |
| inputs.decode | 1 chains | 48.8555 | 20.4685 | 3 |
| preparation.rebuild | 1 chains | 14.4976 | 68.977 | 3 |
| result.from_terminal | 1 chains | 38477 | 0.0259896 | 3 |
| result.serialize_digest | 1 chains | 7.04354 | 141.974 | 3 |
| runtime.snapshot.read | 1 chains | 10525.8 | 0.0950049 | 3 |
| runtime.steps.read | 1 chains | 1653.47 | 0.604789 | 3 |
| runtime.verify_cut | 1 chains | 10040.7 | 0.0995947 | 3 |
| terminal.read | 1 chains | 47260.1 | 0.0211595 | 3 |
| terminal.trace.verify | 1 chains | 18437.4 | 0.0542377 | 3 |
| terminal.verify_cut | 1 chains | 9782.44 | 0.102224 | 3 |

## 比较与限制

各阶段按一次完整组合工作量报告，不能与纯库每条记录吞吐量直接相除。每轮结果摘要必须相同，历史kernel_artifact仅是输入绑定；统计读取器核对当前已编译binary的SHA256，拒绝用历史工件摘要替代当前二进制。原始样本由结果目录保存；不设新CI阈值。

## PostgreSQL 原子发布基准

2026-11-14 UTC，固定 onlyalpha-dev，Linux aarch64、Rust 1.99.1、PostgreSQL 18.6，release 优化。入口是显式测试目标 `cargo test --release --frozen --offline -p onlyalpha-backend --test application_job_publication tests::postgres_publication_performance_matrix -- --ignored --exact --nocapture`，经 dev_verification 和现有 compiler_environment 执行。源码冻结摘要 `b9dc752cc1a9f388b3375415ce2ed923bf1eea5773734d322f15a872998fad47`，operation `55bca046-816b-4430-9744-4b05384bbdc3`。原始样本与完整冻结输入清单：`test-results/strategy-research-framework/stage2/pg-publication-benchmark.json`；运行日志：同目录 `final-performance-schema-checks.log`。

这是存储原语基准：真实普通 LOGIN／服务角色、原 Run／Attempt、真实 PostgreSQL 事务、全部成员正文／约束／完整读回和同步 COMMIT。每档预热一次、采样三次，逐轮核对排除 Run 绑定后的成员正文摘要相同。原 Run／Attempt 的 SQL 准备、连接建立及 register 不计入 publish；准备列只计受控候选的内存构造、规范编码与摘要。没有清除 OS 或 PostgreSQL 缓存，没有硬件独占。

| 合成场景 | 成员 | 正文字节 | 描述符声明行数 | 准备编码 ms | publish 中位 ms（范围） | 独立完整读取中位 ms（范围） |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| small | 4 | 300 | 5 | 0.084 | 6.747（6.742–6.978） | 1.542（1.462–1.883） |
| large | 35 | 4,589,025 | 67 | 6.289 | 57.193（56.980–86.501） | 10.435（10.242–12.623） |

| publish 分项中位数（ms） | small | large |
| --- | ---: | ---: |
| 原 Run 锁获取（含 SQL 往返） | 0.076 | 0.130 |
| 成员与清单 SQL 写入 | 0.498 | 16.514 |
| 原 Attempt／Run 终态、约束与完整读回核对 | 3.735 | 30.663 |
| COMMIT 往返 | 0.957 | 1.867 |
| 其余调用内耗时 | 1.463 | 8.123 |

分项在每个原始样本中闭合 publish 总耗时；各列独立取中位数，不能相加后要求等于总中位数。其余耗时包括候选正文核对、事务／预算设置、冻结关联和 Attempt 查询，不称为全部数据库锁等待。large 的三次 COMMIT 范围为 1.764–31.127 ms，不用三次样本宣称尾延迟。当前合成工作量中，终态／约束／读回占用最大；这只是存储成本观察，不是性能优化结论。

small 的进程累计 VmHWM 为 4,324 kB，large 最高 23,440 kB（/proc 原值）。这是同进程累计峰值，不是单次分配量，未测 PostgreSQL 后端峰值。正文为含大量重复 x 填充的 canonical JSON，压缩性很高；声明行数是测试描述符，不是真实交易事实数。不能据此推断真实订单／曲线的存储吞吐、完整回测 bars/s、旧链路加速比或 Web 超时已解决。

冻结验证投影保留主工作区两份无关用户改动（market_product/day.rs、transport/host_day.rs），不纳入本任务提交；所有本阶段修改文件与待提交内容逐文件核对一致。完整实际构建输入以原始清单为准，不把 Git HEAD 当作二进制身份。没有新增依赖、吞吐门槛或拆分正式发布事务。

## 因子构建与精确认证

固定开发环境运行 `cargo test --release --frozen --offline -p onlyalpha-backend --test application_job_publication factor_build_tests::factor_build_performance_matrix -- --ignored --exact --nocapture --test-threads=1`。明确使用 `_test` 数据库，测试前准备真实 schema 和普通登录角色；schema／安装 SDK／owner 创建不在下列作业计时内，不能据此声称整个启动耗时。

默认 period=2 冷构建包括真实隔离进程握手、单次 AST 解析／降级、native 类型检查、精确认证和数据库提交；period=3／64／256 复用同一程序，只认证新组合。request 单列请求读写；read/decode/bind 单列 owning READY 读取、全部内容检查、JSON decode 和参数绑定。每组保留程序、参数证书、实际解析计数；READY 来源于真实 owner，不接受测试 JSON 充当证书。所有组必须同程序、不同参数证书。

VmHWM 是 Linux 后端测试进程高水位，不含 PG 服务和编译子进程，不是增量内存。独立 supervisor 的子进程 max RSS 另列，包括测试执行期间所派生进程的最大值；排除 cargo 编译阶段。单轮样本不作尾延迟／复杂度证明。本矩阵与旧 Source／SQLite 链路和正式 Web 回测不具有相同输入、职责或结果，不能算优化加速比。

源码解析与校验／降级可另运行 `python3 scripts/benchmark_factor_compiler.py --samples 20 --output <新JSON路径>`：使用实际安装的同一编译函数和公开示例，观测 `ast.parse` 的实际调用／耗时，分别记录 AST 解析与其余校验／降级的原始样本和中位数。它是已加载模块的函数基准，未执行 OS 隔离；真实隔离进程开销由 PG 冷构建项覆盖。不能把这个观测脚本或其输出作为 READY 认证。

### 2026-11-15 构建与认证测量

固定 Linux aarch64／Rust 1.99.1／release；最终 SDK 复测冻结摘要 `3c617d6a74a0dadbb556797e5d7b24931c4ec0f5b9b5f62f1237e4ca650aaecf`。原始结果 `test-results/strategy-research-framework-stage3-perf-final/build-final-sdk.log`，任务工作树副本同 calculation 基准；程序／证书／二进制摘要均保留。单轮数据，不能作 p95。

| period | 请求 ms | 构建／认证／提交 ms | 完整读取／decode／bind ms | AST 次数 |
| ---: | ---: | ---: | ---: | ---: |
| 2 | 3.736 | 851.005 | 1.448 | 1 |
| 3 | 3.149 | 4.617 | 1.373 | 0 |
| 64 | 3.357 | 7.103 | 1.187 | 0 |
| 256 | 3.336 | 29.285 | 1.275 | 0 |

四组共用构建程序 `8b3a32132f43ed55bd537d7166a4bdec9372e35628f3cd4b9fc9ea0e43df9063`，四份证书分别绑定参数；读取不重新解析源码。period=2 为真实隔离冷构建，其余只认证新参数。最终 SDK 复测后端测试进程 VmHWM 为 78848 KiB；该次未单独采集子进程 max RSS。

前端纯函数另测公开动量示例，20 个样本每次实际调用一次 ast.parse；源码 SHA256 `10172a747caa5a4839d56b4374a519ee560ea00f92250926177d9b1013d68410`，该输入和编译函数在最终导入空行调整中未变。中位 AST 解析 20.000 µs，其余校验／降级 31.396 µs，总计 50.979 µs；进程 peak RSS 29044 KiB。各分量中位数不能直接相加；该输入与 PG rolling_mean 场景不同，不用两者相减推断进程开销。
