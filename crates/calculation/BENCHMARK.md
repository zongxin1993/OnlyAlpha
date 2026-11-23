# calculation 性能基准

## 测量职责与入口

`ExecutionCursor::prepare / commit / exact ordered receipts`，通过公开接口执行。测量范围是本库操作，不代表产品准入、外部协议或完整 Web 吞吐量。三档规模 [1, 32, 256]，单位 events。

## 计时与功能校验

输入解析及固定元数据准备在计时外，状态候选由 iter_batched 在计时外建立，循环体和其必须操作计入测量；输出被 black_box 消费。各 case 的断言先校验实际状态/结果。复用已有集成测试 support 时只使用其公开接口 fixture，不引入私有业务访问。首轮不声称 OS 冷缓存；批量循环的吞吐量不能作为单请求尾延迟。

## 执行方法

`cargo bench --frozen --offline -p onlyalpha-calculation --bench workload`，使用固定工具环境；有外部服务时走 onlyalpha-dev。保留原始 Criterion 样本、输入/结果身份、实际构建和环境；不兼容的输入输出禁止比较。

## 参考基线

2026-11-13，固定 onlyalpha-dev，Linux aarch64，Rust 1.99.1，bench/release优化，单编译任务。源码冻结摘要 `95f65185431cd4be521fe8fff8ced2bf1eba3e528c00908b2b22bf325f5685d4`。首个target输入摘要 `b979787cce840ba8c298e3295fa32790054c9c15be0c9a240b2c70c58a706561`；各target独立的输入、结果与二进制SHA256见原始identity.json，不把历史kernel绑定作为当前构建身份。

Criterion为每case至少10个原始样本；表中使用Criterion的median估计。固定慢样本使用3轮中位数，不据此推断可靠尾延迟。状态准备、缓存和析构边界以本页方法说明及case源码为准；没有清OS缓存，也没有硬件独占。原始结果：`test-results/backtest-observability/reference-01/calculation/`（本轮位于主工作区）；包含build、identity、reference.log、report及Criterion原始样本。

| 场景 | 每次工作量 | 中位耗时 ms | 吞吐 /秒 | 样本数 |
| --- | ---: | ---: | ---: | ---: |
| cursor.prepare_commit/1 | 1 elements | 0.000329872 | 3.03148e+06 | 10 |
| cursor.prepare_commit/256 | 256 elements | 0.0255282 | 1.00281e+07 | 10 |
| cursor.prepare_commit/32 | 32 elements | 0.00316526 | 1.01098e+07 | 10 |

增长观察（同一case的最大输入/最小输入总耗时比；仅说明这三档输入，不据此证明渐进复杂度）：

- `cursor.prepare_commit`：77.39 倍（256/1）。

## 限制

仅覆盖上面列出的入口。错误/恢复/复杂度曲线按覆盖矩阵解释；未测功能不能宣称覆盖。无新 CI 性能门槛；p95 的解释受样本数限制。

## typed 因子程序基准

`cargo bench --frozen --offline -p onlyalpha-calculation --bench workload -- factor_program`。每 case 使用 1024 行、前 512 行每 97 行一个 null、后 512 行连续有效值，rolling_mean 窗口 2／64／256；decode 与 bind 按次计时，batch 与 event 按行计时，另测四个独立实例。前置断言逐点比较 batch/event，并要求每档实际出现非缺值输出；程序、实际输入、输出摘要随原始日志保留。AST 次数为 0：本库不含 Python 或源码解析。

decode 包含有界 JSON 解析及完整类型／资源校验；bind 包含精确参数与窗口预算；batch 包含实例创建和输出收集；event 的实例创建在 iter_batched 准备阶段，step 的状态候选、完整检查、输出构造均计入计时。四实例按实际四倍行数计算吞吐。窗口实现沿用原语，不改变数值、校验或算法。

原始 Criterion 样本和独立进程 peak RSS 是不同口径：RSS 包含测试程序、Criterion 和结果分析，不是单个窗口的独占内存，也不含 PostgreSQL／ClickHouse。没有清 OS 缓存或硬件独占；不与旧完整交易／取证链路作性能比值，不作为硬性吞吐门槛。

### 2026-11-15 测量记录

固定 onlyalpha-dev，Linux aarch64、Rust 1.99.1、release，单编译任务；冻结源码摘要 `8730b0436556ecb709789aa396220ae36a0a3567561e4a35a12123855e7f091d`。验证投影包含已记录的两处无关 day 文件改动，不能把该二进制等同最终任务提交的完整生产工件。原始样本在主工作区 `test-results/strategy-research-framework-stage3-perf-final/`，任务工作树副本 `test-results/strategy-research-framework/stage3/performance/`；identity.json 记录实际二进制 SHA256，program.log 和 Criterion 目录保留逐 case 身份、10 个样本及估计。

程序为 242–244 字节，1024 行相同输入摘要 `8574accaf6ac8cb88bb2697d90edbc31bac90531ba7d61be6eddabbaa9f8f3e3`；窗口 2／64／256 分别实际产生 1012／640／283 个非缺值输出。各输出摘要在日志中。

| 窗口 | decode 中位 µs/次 | bind 中位 µs/次 |
| ---: | ---: | ---: |
| 2 | 3.486 | 1.774 |
| 64 | 3.439 | 1.717 |
| 256 | 3.487 | 1.710 |

| 场景 | 窗口 | 行数/次 | 中位 ms/次 | ns/行 | 行/秒 |
| --- | ---: | ---: | ---: | ---: | ---: |
| batch | 2 | 1024 | 1.295 | 1264.7 | 790,706 |
| batch | 64 | 1024 | 4.105 | 4008.8 | 249,453 |
| batch | 256 | 1024 | 6.260 | 6113.3 | 163,578 |
| event | 2 | 1024 | 1.249 | 1219.4 | 820,060 |
| event | 64 | 1024 | 3.932 | 3839.7 | 260,434 |
| event | 256 | 1024 | 6.291 | 6143.4 | 162,777 |
| four_instances | 2 | 4096 | 5.045 | 1231.8 | 811,816 |
| four_instances | 64 | 4096 | 15.980 | 3901.3 | 256,327 |
| four_instances | 256 | 4096 | 24.984 | 6099.5 | 163,947 |

独立基准进程 peak RSS 为 14352 KiB（约 14.0 MiB）。这是单因子合成输入的模块结果，不代表完整交易执行、Research 准备或 Web 链路。当前 batch 入口复用同一 event step，未宣称 SIMD／列式优化。

## 有限输入计算需求

`cargo bench --frozen --offline -p onlyalpha-calculation --bench workload -- finite_input` 增加 `finite_input.requirements/two_nodes`。复用既有 `graph-basic` 两节点链，计时前验证累计预热为 2；图解析在计时外，依赖遍历、输入引用收集和检查加法在计时内。该项测量数学前处理元数据，不执行因子，也不读取行情、Target 或账户。

固定 dev Linux aarch64、Rust 1.99.1、release，2026-11-15 两节点依赖准备中位数 10.965 µs，Criterion 10 个样本、200 ms 预热、约 1 秒采样。进程峰值 RSS 15588 KiB 包含其他基准初始化，不能当作本函数独占分配。冻结源码摘要 `fb7ee613caacf34b66886ddbc791512a41e16f7c2fe74b75eb70680aaaa948e8`，基准可执行文件 SHA256 `150eac7ce1ebef3229c53fbd339e77b876b45529824f6063c51b0fb5f8af6b38`；原始样本见任务产物 `test-results/strategy-research-framework-stage4-performance/onlyalpha-calculation-samples.log`。
