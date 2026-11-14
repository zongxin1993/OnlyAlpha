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
