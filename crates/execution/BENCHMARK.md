# execution 性能基准

## 职责与范围

直接测本模块的正式公开入口；具体操作见共享 [inventory.json](../../test-data/backtest-benchmarks/inventory.json)。不产生 Product 准入或完成事实，不以组件计时替代 Web 验收。

## 输入与口径

使用受控 740-bar 回测派生的原始值及 64/129/326 前缀，配置/数据摘要见 provenance.json。Execution 为三种完整组件恢复与受控内存 Store 的同前缀 ADMIT 规划。Runtime/Backtest 为原始保留 runtime 的固定次数慢基准，不自动扩增迭代，不把小骨架解释为真实终态成本。

## 执行

`cargo bench --frozen --offline -p onlyalpha-execution --bench recovery`（Cargo bench 默认 release，不需要额外切换 profile）。慢基准需显式 OA_BENCH_RUNTIME 指向与 replay.json 绑定一致的保留目录，OA_BENCH_ROUNDS 默认3；缺输入明确失败。输入/元数据准备在计时外；各阶段含其内部复核、输出未使用的作用域末析构不计入阶段。当前完整引用样本不会冒充三个不同 runtime 历史规模；三档 Runtime 增长用例需要独立生成有效持久化样本后运行，不能截断 SQLite 冒造前缀。

## 参考基线

2026-11-13，固定 onlyalpha-dev，Linux aarch64，Rust 1.99.1，bench/release优化，单编译任务。源码冻结摘要 `95f65185431cd4be521fe8fff8ced2bf1eba3e528c00908b2b22bf325f5685d4`。首个target输入摘要 `b7bb3ba4b96cf9096b74e831222c1bcbca95454a431975452a3774407c8c7ca7`；各target独立的输入、结果与二进制SHA256见原始identity.json，不把历史kernel绑定作为当前构建身份。

Criterion为每case至少10个原始样本；表中使用Criterion的median估计。固定慢样本使用3轮中位数，不据此推断可靠尾延迟。状态准备、缓存和析构边界以本页方法说明及case源码为准；没有清OS缓存，也没有硬件独占。原始结果：`test-results/backtest-observability/reference-01/execution/`（本轮位于主工作区）；包含build、identity、reference.log、report及Criterion原始样本。

| 场景 | 每次工作量 | 中位耗时 ms | 吞吐 /秒 | 样本数 |
| --- | ---: | ---: | ---: | ---: |
| admission.accept/cold/1 | 1 elements | 1.70681 | 585.89 | 10 |
| admission.accept/cold/32 | 32 elements | 54.9183 | 582.684 | 10 |
| admission.accept/cold/8 | 8 elements | 13.6465 | 586.233 | 10 |
| admission.accept/reused/1 | 1 elements | 1.36449 | 732.875 | 10 |
| admission.accept/reused/32 | 32 elements | 44.0381 | 726.644 | 10 |
| admission.accept/reused/8 | 8 elements | 11.1181 | 719.547 | 10 |
| admission.reject/cold/1 | 1 elements | 0.670361 | 1491.73 | 10 |
| admission.reject/cold/32 | 32 elements | 21.3934 | 1495.79 | 10 |
| admission.reject/cold/8 | 8 elements | 5.3759 | 1488.12 | 10 |
| admission.reject/reused/1 | 1 elements | 0.36277 | 2756.57 | 10 |
| admission.reject/reused/32 | 32 elements | 11.588 | 2761.47 | 10 |
| admission.reject/reused/8 | 8 elements | 2.88745 | 2770.62 | 10 |
| components/capture_warm/large | 2207580 bytes | 3.06968 | 7.19156e+08 | 10 |
| components/capture_warm/medium | 938581 bytes | 1.49121 | 6.29408e+08 | 10 |
| components/capture_warm/small | 516680 bytes | 0.853715 | 6.05214e+08 | 10 |
| components/digest/large | 2207580 bytes | 0.775797 | 2.84556e+09 | 10 |
| components/digest/medium | 938581 bytes | 0.330336 | 2.84129e+09 | 10 |
| components/digest/small | 516680 bytes | 0.18184 | 2.8414e+09 | 10 |
| components/encode/large | 2207580 bytes | 1.14345 | 1.93062e+09 | 10 |
| components/encode/medium | 938581 bytes | 0.479631 | 1.95688e+09 | 10 |
| components/encode/small | 516680 bytes | 0.259704 | 1.9895e+09 | 10 |
| components/new/large | 1 elements | 0.0280431 | 35659.4 | 10 |
| components/new/medium | 1 elements | 0.0280714 | 35623.5 | 10 |
| components/new/small | 1 elements | 0.0285713 | 35000.2 | 10 |
| components/restore/large | 2207580 bytes | 544.004 | 4.05802e+06 | 10 |
| components/restore/medium | 938581 bytes | 99.5882 | 9.42462e+06 | 10 |
| components/restore/small | 516680 bytes | 36.2357 | 1.42589e+07 | 10 |
| prepare_admit.same_prefix/1 | 1 elements | 2.84052 | 352.048 | 10 |
| prepare_admit.same_prefix/32 | 32 elements | 90.9583 | 351.81 | 10 |
| prepare_admit.same_prefix/8 | 8 elements | 22.89 | 349.497 | 10 |

增长观察（同一case的最大输入/最小输入总耗时比；仅说明这三档输入，不据此证明渐进复杂度）：

- `admission.accept/cold`：32.18 倍（32/1）。
- `admission.accept/reused`：32.27 倍（32/1）。
- `admission.reject/cold`：31.91 倍（32/1）。
- `admission.reject/reused`：31.94 倍（32/1）。
- `components/capture_warm`：3.596 倍（前缀326/64）。
- `components/digest`：4.266 倍（前缀326/64）。
- `components/encode`：4.403 倍（前缀326/64）。
- `components/restore`：15.01 倍（前缀326/64）。
- `prepare_admit.same_prefix`：32.02 倍（32/1）。

## 限制

原始样本与环境/构建身份外存；输入/结果不匹配或样本不完整禁止比较。历史工件值仅用于技术输入绑定，不赋予当前可执行文件历史读取 Authority。原 300/120 秒门槛不变，无新 CI 性能阈值。

准入另测受控空前缀的成功/资金不足拒绝，各自对比 cold admission_rejection 与已恢复 AdmissionPreview 的逐输入检查，1/8/32次。两个入口先逐项断言相同结果，再计时；不把重复输入变成已提交许可。

创建使用iter_batched的单位准备，计时包含构造所需参数复制，返回owner析构在计时外。capture_warm的warm指同一已构建状态，不承诺各库都有编码缓存；该iter用例包含返回值析构。更新返回的小Outcome在被测调用内析构，候选owner在外。

Components另将创建、warm checkpoint模型捕获、规范JSON编码、字节digest及完整恢复分开报告；字节吞吐以规范checkpoint长度为分母，捕获模型不冒充磁盘写入。
