# risk 性能基准

## 测量职责

实际入口：`Manager::new / restore / checkpoint / damaged checkpoint rejection`。只测本库公开操作，不产生 Product Run、准入或正式事实。场景清单见 [覆盖矩阵](../../docs/engineering/backtest-performance-coverage.md)。

## 输入与计时边界

使用 [受控回测样本](../../test-data/backtest-benchmarks/provenance.json) 中 64/129/326 前缀。输入读取、JSON解析及功能预检在计时外。Criterion 的 `iter_batched` 将候选创建和输出析构放在恢复计时外，`new` 场景单独测构造；吞吐单位为 bytes。所有输入/输出都被消费，恢复必须完整匹配原 checkpoint。首轮不声称操作系统冷缓存。

## 使用方法

`cargo bench --frozen --offline -p onlyalpha-risk --bench recovery`。使用项目固定工具环境；依赖服务的场景经 dev_verification 运行。原始 Criterion 样本与构建/硬件/存储信息保存在本次结果目录，不将缺少样本或不兼容输入输出用于速度比较。

## 参考基线

2026-11-13，固定 onlyalpha-dev，Linux aarch64，Rust 1.99.1，bench/release优化，单编译任务。源码冻结摘要 `95f65185431cd4be521fe8fff8ced2bf1eba3e528c00908b2b22bf325f5685d4`。首个target输入摘要 `22183c09277eaf0c179b00664f214bac3f0651eb29ce1f2937ef4f4e16eb5bb3`；各target独立的输入、结果与二进制SHA256见原始identity.json，不把历史kernel绑定作为当前构建身份。

Criterion为每case至少10个原始样本；表中使用Criterion的median估计。固定慢样本使用3轮中位数，不据此推断可靠尾延迟。状态准备、缓存和析构边界以本页方法说明及case源码为准；没有清OS缓存，也没有硬件独占。原始结果：`test-results/backtest-observability/reference-01/risk/`（本轮位于主工作区）；包含build、identity、reference.log、report及Criterion原始样本。

| 场景 | 每次工作量 | 中位耗时 ms | 吞吐 /秒 | 样本数 |
| --- | ---: | ---: | ---: | ---: |
| checkpoint/capture_warm/large | 141845 bytes | 0.00281557 | 5.03789e+10 | 10 |
| checkpoint/capture_warm/medium | 71268 bytes | 0.00116333 | 6.12623e+10 | 10 |
| checkpoint/capture_warm/small | 43088 bytes | 0.000499845 | 8.62028e+10 | 10 |
| checkpoint/duplicate_apply/large | 1 elements | 0.0210507 | 47504.3 | 10 |
| checkpoint/duplicate_apply/medium | 1 elements | 0.0211979 | 47174.6 | 10 |
| checkpoint/duplicate_apply/small | 1 elements | 0.0215248 | 46458 | 10 |
| checkpoint/first_apply/large | 1 elements | 0.094479 | 10584.4 | 10 |
| checkpoint/first_apply/medium | 1 elements | 0.0956765 | 10451.9 | 10 |
| checkpoint/first_apply/small | 1 elements | 0.0958421 | 10433.8 | 10 |
| checkpoint/new/large | 1 elements | 0.0015746 | 635083 | 10 |
| checkpoint/new/medium | 1 elements | 0.00167029 | 598699 | 10 |
| checkpoint/new/small | 1 elements | 0.00184663 | 541528 | 10 |
| checkpoint/reject_digest/large | 141845 bytes | 0.0505765 | 2.80456e+09 | 10 |
| checkpoint/reject_digest/medium | 71268 bytes | 0.0258231 | 2.75985e+09 | 10 |
| checkpoint/reject_digest/small | 43088 bytes | 0.0160262 | 2.6886e+09 | 10 |
| checkpoint/restore/large | 141845 bytes | 9.65643 | 1.46892e+07 | 10 |
| checkpoint/restore/medium | 71268 bytes | 3.30996 | 2.15314e+07 | 10 |
| checkpoint/restore/small | 43088 bytes | 1.54497 | 2.78891e+07 | 10 |

增长观察（同一case的最大输入/最小输入总耗时比；仅说明这三档输入，不据此证明渐进复杂度）：

- `checkpoint/capture_warm`：5.633 倍（前缀326/64）。
- `checkpoint/duplicate_apply`：0.978 倍（前缀326/64）。
- `checkpoint/reject_digest`：3.156 倍（前缀326/64）。
- `checkpoint/restore`：6.25 倍（前缀326/64）。

## 限制与正确性

本基准不代表完整 Web 回测吞吐量，不设 CI 性能阈值。小样本的 p95 不代表稳定尾延迟。业务语义有意变化需独立审查并建立新基线，不能删改正确性断言换取性能数字。

创建使用iter_batched的单位准备，计时包含构造所需参数复制，返回owner析构在计时外。capture_warm的warm指同一已构建状态，不承诺各库都有编码缓存；该iter用例包含返回值析构。更新返回的小Outcome在被测调用内析构，候选owner在外。
