# runtime 性能基准

## 职责与范围

直接测本模块的正式公开入口；具体操作见共享 [inventory.json](../../test-data/backtest-benchmarks/inventory.json)。不产生 Product 准入或完成事实，不以组件计时替代 Web 验收。

## 输入与口径

使用 `test-data/execution/domain-inputs.json` 与 `test-data/settlement/common-v1.json` 构造真实经济输入与估值序列，配置/数据摘要见 `provenance.json`。不再使用旧 SQLite 文件或外部 `OA_BENCH_RUNTIME` 保留目录。

- `retained`（固定 3 轮）：分别测量 `memory.execute`（`Session` 内存执行）、`result.read`（终态经济结果读取）与 `durability.recovery`（`RecoveryFacts::from_records` 持续交易事实校验与组件重建），显式支持 `OA_BENCH_DIAGNOSTICS=off|detail` 观测开销对照。
- `recovery`（Criterion，8/32/128 档）：测量 `Session` 内存执行与 `RecoveryFacts::from_records` 持续交易恢复。

## 执行

- `cargo bench --frozen --offline -p onlyalpha-runtime --bench retained`（`OA_BENCH_ROUNDS` 默认 3，`OA_BENCH_DIAGNOSTICS=off|detail`）。
- `cargo bench --frozen --offline -p onlyalpha-runtime --bench recovery`。
- 统一运行器：`python -m scripts.run_rust_benchmarks reference --crate runtime --target retained --diagnostics off --output <新结果目录>`。

输入/元数据准备在计时外；各阶段含其内部复核，每轮核对完整结果摘要一致。原 SQLite 产物已退役，不再作为新基准的隐含输入，也不与旧 SQLite 样本直接比较声称优化。

## 限制

原始样本与环境/构建身份外存；输入/结果不匹配或样本不完整禁止比较。历史工件值仅用于技术输入绑定，不赋予当前可执行文件历史读取 Authority。原 300/120 秒门槛不变，无新 CI 性能阈值。

## 观测开销对照口径

`retained` harness 显式支持 `OA_BENCH_DIAGNOSTICS=off|detail`（默认 off）。计时只包含 `memory.execute`、`result.read` 与 `durability.recovery`；Session 创建、线程启动及关闭/flush 在计时外，sink 使用标准库空 writer，队列容量 65536，关闭时必须无丢失及 I/O 错误。每轮核对相同结果摘要。该对照测量 JSON 编码、关联与队列提交成本，不代表真实磁盘写入开销。

统一运行器可选择 `--crate runtime --target retained --diagnostics off` 或 `detail`；两种模式使用同一冻结源码和同一编译工件。身份文件与报告记录模式及关闭收据。普通代码回归比较拒绝跨模式；`compare_observation_overhead` 仅允许模式不同，并要求输入、结果、工作量、完整样本、环境、二进制和源码完全相同。

## 内存会话口径

`cargo bench -p onlyalpha-runtime --bench recovery -- memory.runtime` 分别量化实际 Session 创建、准入成功、成交 apply、最终对账／结果整理，并比较完整买卖流程在 observability Off／Detail 下的开销。计时外建立前置状态，各观测模式先断言完整经济结果相同；日志关闭收据必须完整且没有丢弃或 I/O 错误。这里的吞吐是经济输入／秒，不能冒充回测 K 线／秒。逐 Bar 的整体执行样本及输入规模增长见 [Backtest 基准](../backtest/BENCHMARK.md)。

2026-11-15 固定 onlyalpha-dev、Linux aarch64、Rust 1.99.1、release，冻结源码 `b34f9f2b5663634be469cd43048e448e35774a16a129c906079a2733a9ed98a2`，工件 SHA256 `e7b9d6952eb12ffd1ded1a9668cb542735c8caac3b665a6021f3bed924f09a66`。Criterion 各 10 个样本，原日志与独立进程监控保留在主工作区 `test-results/strategy-research-framework-stage5-performance-final/`。

| 场景 | 中心估计 | 95% 区间 |
|---|---:|---:|
| 创建 Session | 75.675 µs | 75.314–76.200 µs |
| 准入成功 | 1.6692 ms | 1.6269–1.7173 ms |
| 成交 apply | 1.0070 ms | 0.99831–1.0121 ms |
| 最终对账与整理 | 4.8107 ms | 4.1952–5.4387 ms |
| 完整流程 Off | 13.450 ms | 13.266–13.729 ms |
| 完整流程 Detail | 14.023 ms | 13.950–14.155 ms |

完整流程是同一八步实际经济输入，Off／Detail 结果一致；中心估计开销约 4.26%，少量样本存在异常值，不承诺固定比例。单独基准进程最大 RSS 为 23892 KiB，排除编译及未选中的旧 SQLite 场景初始化，仍包含 Criterion、样本准备、结果与观测器，不能当作单个 Session 内存。之前未带 `--bench` 的运行只证明测试模式 smoke 成功，不是计时样本。
