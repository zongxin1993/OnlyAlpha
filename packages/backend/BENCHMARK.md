# 后端回测组合基准

## 职责与入口

`cargo bench --frozen --offline -p onlyalpha-backend --bench backtest_chain` 按三种显式口径测量后端核心链路，不再依赖旧 SQLite 保留目录或 `replay-trace.json`：

1. `memory.execution`（默认）：`PreparedNextOpen` 与 `onlyalpha-runtime::Session` 有限内存执行链路。
2. `pg.recovery`：真实 PostgreSQL 持续交易正式事实恢复链路（须显式提供 `ONLYALPHA_POSTGRES_DSN`）。
3. `result.read`：有限回测终态结果读取与完整性验证（`verify_finite_backtest` 及规范摘要）。

本基准不发布 Product 证据，不替代 Web/API 验收。Rust 库自己的基准见各 crates 下的 `BENCHMARK.md`。

## 输入、边界与运行

通过统一运行器 `python -m scripts.run_rust_benchmarks reference --crate backend --scope <memory.execution|pg.recovery|result.read> --output <新结果目录>` 执行（默认 3 轮）。源码、配置、数据和当前实际可执行文件摘要独立记录；原 SQLite 产物已退役，不作隐含输入，也不与旧 SQLite 样本跨口径比较声称改进。

## 比较与限制

各阶段按一次完整组合工作量报告，不能与纯库每条记录吞吐量直接相除。每轮结果摘要必须相同；统计读取器核对当前已编译 binary 的 SHA256，拒绝用历史工件摘要替代当前二进制。原始样本由结果目录保存；不设新 CI 阈值。

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

## 共用有限作业输入

固定 dev 的 `tests/application/test_job_input_postgres_clickhouse.py` 使用真实 PostgreSQL／ClickHouse owner，规模 1／128／740 行，warmup 0、sample 等于 source rows；每档通过真实编写 owner 发布一个 close 因子，由实际隔离编译器和原生认证 owner 构建一次，再按冻结证书进行 10 次重复加载。不用假 READY 或合成证书，不写行情副本或过程文件。

`JOB_INPUT_PROFILE` 记录当前 release 探针的实际 SHA256、输入快照／绑定／因子引用、每次加载耗时和 `/proc/self/status` VmHWM。首个 loader 为进程内冷调用，随后为热调用；ClickHouse 存储已被准备／封存读取，全部标记 storage warm，没有清 OS 缓存。`setup_us` 单列连接、SDK 和构建 reader 初始化，不能混入逐 Bar 吞吐。

`total_us` 是 loader 整体墙钟。`source_us` 包含 PG 元数据与原物理完整性证明；其内 `headers_us`、`body_us`、`decode_us` 分别为 HTTP 响应头等待、正文读取及 JSONEachRow 解码。ClickHouse 的 `server_us` 只采用实际响应头，并附 `server_samples`，与 HTTP 时间重叠，不相加。流式正文读取也可能包含服务端生产时间，不能当成独占网络耗时。

`dataset_prepare_us` 内分规范化、排序、内容／快照摘要和向量槽位预留；`allocation_ns` 只测向量预留，字符串／节点分配仍在各所属阶段中。`axis_us` 包含还原 typed Bar 与连续轴校验，`identity_us` 核对全部冻结引用，`program_preflight_us` 单列精确构建内容的声明规模计费，`programs_us` 读取并绑定精确 READY 程序；`budget_meter_us` 与 `final_guard_us` 分别记录加载后预算计费和最终权限／命名空间核对。组件中位数不保证可加。VmHWM 包含测试调用方保留样本和 JSON 输出，不是某个向量独占内存，也不包含数据库服务进程。

2026-11-15 固定 dev Linux aarch64、Rust 1.99.1、release 初测（冻结摘要 `fb7ee613caacf34b66886ddbc791512a41e16f7c2fe74b75eb70680aaaa948e8`，探针 SHA256 `2032a579257fd1bdec13f19ed0826098ddbf21ab21e2d06810bdbae30ef6a338`）：

| source/sample 行数 | 首次 loader ms | 后 9 次中位总耗时 ms | source ms | Dataset 准备 ms | 轴还原/校验 ms | 精确程序加载 ms | 进程 VmHWM KiB |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 68.917 | 31.821 | 27.417 | 0.201 | 0.052 | 2.240 | 72572 |
| 128 | 99.407 | 86.519 | 72.088 | 4.200 | 4.235 | 2.876 | 72704 |
| 740 | 427.223 | 372.832 | 302.710 | 24.277 | 27.435 | 3.284 | 176344 |

上述 total 的逐样本扣除全部非重叠阶段后，剩余中位数分别 7／9／12 µs；source 内还有 PG 元数据、物理证明和归属核对，不能只用 HTTP 分量解释它。740 行的 HTTP 头等待／正文／解码中位数为 30.151／2.872／35.266 ms，规范化／排序／摘要为 15.082／0.291／5.397 ms，程序声明规模预检为 1.767 ms。准备链路主要耗时在 source owner 读取和完整性证明，不据此推断完整交易执行吞吐。原始 30 个样本、冻结绑定、程序／证书摘要与存储实际响应指标位于任务产物 `test-results/strategy-research-framework-stage4-suite-r3.log`；这是分类修复前的初测，不能代替后续修复版本的功能验证。

同日分类修复后的复测采用相同方法，冻结摘要 `38136cccb0e84c2083ce86634ffb61be93af37b01780d5289ac20f3ef3a3ad55`，探针 SHA256 `4623c9cf8ac4b874c6736d5f73755adf44b7d11b43072f92a97a0fb070b5f8f3`，原始 30 个样本见 `test-results/strategy-research-framework-stage4-final-checks-r1.log`：

| source/sample 行数 | 首次 loader ms | 后 9 次中位总耗时 ms | source ms | Dataset 准备 ms | 轴还原/校验 ms | 精确程序加载 ms | 进程 VmHWM KiB |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 63.085 | 41.942 | 36.665 | 0.227 | 0.059 | 2.705 | 72584 |
| 128 | 109.211 | 88.928 | 73.601 | 4.143 | 4.311 | 2.941 | 72576 |
| 740 | 526.564 | 420.338 | 320.078 | 25.086 | 29.635 | 3.259 | 176552 |

复测逐样本闭合后的剩余中位数为 10／8／12 µs；740 行 HTTP 头等待／正文／解码中位数为 32.608／9.117／35.183 ms，规范化／排序／摘要为 15.839／0.367／5.433 ms。各列独立取中位数，不相加解释总中位数，也不将两轮环境波动归因于某一项代码修改。上述冻结投影保留两份既有用户改动，实际构建输入以冻结清单为准。

## 精确图构建证明

`tests/application/test_calculation_build_postgres.py` 通过实际手工策略准备 owner、真实 PostgreSQL／ClickHouse 和已安装原生算子构建公共算子信号图。首次明确的构建准备执行六类图案例和逐节点 profile，第二个独立准备复用原证明；`proof-read` 调用与 READY／Run 读取共用的原事实验证方法，不构建。场景不伪造 READY、Run 或证书，也不放宽既有 Research 统计规格只接受 FACTOR 的规则；正式 Research 新因子派单整链属于后续接线验证，不能用本场景代替。

`CALCULATION_BUILD_PROFILE` 单列实际受控图行数、逐节点输入行数、证明编码字节数、构建／复用 owner 微秒耗时、原事实读取微秒耗时和父进程 VmHWM；上下文行情是 740 行、预热 20 行、样本 720 行。构建计时包括 Runtime／工件核验、PG 锁和提交；复用计时包括完整证明读取和校验。这里只报告该模块耗时，不能将固定合成语料当作行情执行吞吐。父进程峰值包含 JSON／证明和测试调用方保留值，不含隔离算法子进程与数据库，也不是操作系统内存限制。

2026-11-15 固定 dev、Linux aarch64／Rust 1.99.1／release 单轮记录：受控图 252 行、逐节点输入 1864 行、证明正文 477948 字节；首次构建 6433.832 ms，重复准备读取并核验 247.256 ms，原事实只读核验 59.131 ms。首次／重复准备父进程 VmHWM 分别 265872／248144 KiB。两次分别观测受控执行开始／回收 1／1 和 0／0；这些是执行次数，不是由耗时推断的缓存命中。原始日志为 `test-results/strategy-research-framework-stage4-build-proof-checks-r3.log`，完整证明和构建身份随受控场景保留；单轮结果不估计 p95 或加速比。缺证测试直接覆盖共用仓储门禁，不代表已执行 Host READY 确认整链。
