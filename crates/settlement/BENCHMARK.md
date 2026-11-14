# settlement 性能基准

## 测量职责

实际入口：`Authority::new / restore / checkpoint (spot authority state)`。只测本库公开操作，不产生 Product Run、准入或正式事实。场景清单见 [覆盖矩阵](../../docs/engineering/backtest-performance-coverage.md)。

## 输入与计时边界

使用 [受控回测样本](../../test-data/backtest-benchmarks/provenance.json) 中 64/129/326 前缀。输入读取、JSON解析及功能预检在计时外。Criterion 的 `iter_batched` 将候选创建和输出析构放在恢复计时外，`new` 场景单独测构造；吞吐单位为 bytes。所有输入/输出都被消费，恢复必须完整匹配原 checkpoint。首轮不声称操作系统冷缓存。

## 使用方法

`cargo bench --frozen --offline -p onlyalpha-settlement --bench recovery`。使用项目固定工具环境；依赖服务的场景经 dev_verification 运行。原始 Criterion 样本与构建/硬件/存储信息保存在本次结果目录，不将缺少样本或不兼容输入输出用于速度比较。

## 参考基线

2026-11-13，固定 onlyalpha-dev，Linux aarch64，Rust 1.99.1，bench/release优化，单编译任务。源码冻结摘要 `95f65185431cd4be521fe8fff8ced2bf1eba3e528c00908b2b22bf325f5685d4`。首个target输入摘要 `afa076896c1e992a9b836428f32732549ab90179509e4920f0d3c012c29bf424`；各target独立的输入、结果与二进制SHA256见原始identity.json，不把历史kernel绑定作为当前构建身份。

Criterion为每case至少10个原始样本；表中使用Criterion的median估计。固定慢样本使用3轮中位数，不据此推断可靠尾延迟。状态准备、缓存和析构边界以本页方法说明及case源码为准；没有清OS缓存，也没有硬件独占。原始结果：`test-results/backtest-observability/reference-01/settlement/`（本轮位于主工作区）；包含build、identity、reference.log、report及Criterion原始样本。

| 场景 | 每次工作量 | 中位耗时 ms | 吞吐 /秒 | 样本数 |
| --- | ---: | ---: | ---: | ---: |
| checkpoint/admit_whole_fill/large | 1 elements | 0.0138961 | 71962.8 | 10 |
| checkpoint/admit_whole_fill/medium | 1 elements | 0.014062 | 71113.9 | 10 |
| checkpoint/admit_whole_fill/small | 1 elements | 0.0137845 | 72545.1 | 10 |
| checkpoint/capture_warm/large | 40441 bytes | 0.0767107 | 5.27188e+08 | 10 |
| checkpoint/capture_warm/medium | 20417 bytes | 0.0374951 | 5.44524e+08 | 10 |
| checkpoint/capture_warm/small | 12408 bytes | 0.0226207 | 5.48523e+08 | 10 |
| checkpoint/duplicate_admission/large | 1 elements | 0.00775782 | 128902 | 10 |
| checkpoint/duplicate_admission/medium | 1 elements | 0.00757931 | 131938 | 10 |
| checkpoint/duplicate_admission/small | 1 elements | 0.00760859 | 131430 | 10 |
| checkpoint/new/large | 1 elements | 0.000866269 | 1.15438e+06 | 10 |
| checkpoint/new/medium | 1 elements | 0.000864736 | 1.15642e+06 | 10 |
| checkpoint/new/small | 1 elements | 0.000862505 | 1.15941e+06 | 10 |
| checkpoint/restore/large | 40441 bytes | 3.31265 | 1.2208e+07 | 10 |
| checkpoint/restore/medium | 20417 bytes | 1.08725 | 1.87786e+07 | 10 |
| checkpoint/restore/small | 12408 bytes | 0.516372 | 2.40292e+07 | 10 |

增长观察（同一case的最大输入/最小输入总耗时比；仅说明这三档输入，不据此证明渐进复杂度）：

- `checkpoint/capture_warm`：3.391 倍（前缀326/64）。
- `checkpoint/duplicate_admission`：1.02 倍（前缀326/64）。
- `checkpoint/restore`：6.415 倍（前缀326/64）。

## 限制与正确性

本基准不代表完整 Web 回测吞吐量，不设 CI 性能阈值。小样本的 p95 不代表稳定尾延迟。业务语义有意变化需独立审查并建立新基线，不能删改正确性断言换取性能数字。

增加原始fill_contract对应的admit_whole_fill_order：首次准入与已恢复authority的重复准入分开计时，校验原订单绑定完全一致。

创建使用iter_batched的单位准备，计时包含构造所需参数复制，返回owner析构在计时外。capture_warm的warm指同一已构建状态，不承诺各库都有编码缓存；该iter用例包含返回值析构。更新返回的小Outcome在被测调用内析构，候选owner在外。
