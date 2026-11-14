# backtest 性能基准

## 职责与范围

直接测本模块的正式公开入口；具体操作见共享 [inventory.json](../../test-data/backtest-benchmarks/inventory.json)。不产生 Product 准入或完成事实，不以组件计时替代 Web 验收。

## 输入与口径

使用受控 740-bar 回测派生的原始值及 64/129/326 前缀，配置/数据摘要见 provenance.json。Execution 为三种完整组件恢复与受控内存 Store 的同前缀 ADMIT 规划。Runtime/Backtest 为原始保留 runtime 的固定次数慢基准，不自动扩增迭代，不把小骨架解释为真实终态成本。

## 执行

`cargo bench --frozen --offline -p onlyalpha-backtest --bench retained`（Cargo bench 默认 release，不需要额外切换 profile）。慢基准需显式 OA_BENCH_RUNTIME 指向与 replay.json 绑定一致的保留目录，OA_BENCH_ROUNDS 默认3；缺输入明确失败。输入/元数据准备在计时外；各阶段含其内部复核、输出未使用的作用域末析构不计入阶段。当前完整引用样本不会冒充三个不同 runtime 历史规模；三档 Runtime 增长用例需要独立生成有效持久化样本后运行，不能截断 SQLite 冒造前缀。

## 参考基线

2026-11-13，固定 onlyalpha-dev，Linux aarch64，Rust 1.99.1，bench/release优化，单编译任务。源码冻结摘要 `95f65185431cd4be521fe8fff8ced2bf1eba3e528c00908b2b22bf325f5685d4`。首个target输入摘要 `411b14cf80976d0ff9e65a69d4d668f3e2227d75b427419047fe41fe669b4813`；各target独立的输入、结果与二进制SHA256见原始identity.json，不把历史kernel绑定作为当前构建身份。

Criterion为每case至少10个原始样本；表中使用Criterion的median估计。固定慢样本使用3轮中位数，不据此推断可靠尾延迟。状态准备、缓存和析构边界以本页方法说明及case源码为准；没有清OS缓存，也没有硬件独占。原始结果：`test-results/backtest-observability/reference-01/backtest/`（本轮位于主工作区）；包含build、identity、reference.log、report及Criterion原始样本。

| 场景 | 每次工作量 | 中位耗时 ms | 吞吐 /秒 | 样本数 |
| --- | ---: | ---: | ---: | ---: |
| terminal.read | 1482 replay_entries | 47475 | 31.2164 | 3 |
| terminal.verify_cut | 1482 replay_entries | 8881.79 | 166.858 | 3 |

## 限制

原始样本与环境/构建身份外存；输入/结果不匹配或样本不完整禁止比较。历史工件值仅用于技术输入绑定，不赋予当前可执行文件历史读取 Authority。原 300/120 秒门槛不变，无新 CI 性能阈值。
