# market-data-construction 性能基准

## 测量职责与入口

`OnlyConstructionGraph::from_record / OnlyConstructionCompilation::compile of actual provider graph`，通过公开接口执行。测量范围是本库操作，不代表产品准入、外部协议或完整 Web 吞吐量。三档规模 [1, 8, 32]，单位 graphs。

## 计时与功能校验

输入解析及固定元数据准备在计时外，状态候选由 iter_batched 在计时外建立，循环体和其必须操作计入测量；输出被 black_box 消费。各 case 的断言先校验实际状态/结果。复用已有集成测试 support 时只使用其公开接口 fixture，不引入私有业务访问。首轮不声称 OS 冷缓存；批量循环的吞吐量不能作为单请求尾延迟。

## 执行方法

`cargo bench --frozen --offline -p onlyalpha-market-data-construction --bench workload`，使用固定工具环境；有外部服务时走 onlyalpha-dev。保留原始 Criterion 样本、输入/结果身份、实际构建和环境；不兼容的输入输出禁止比较。

## 参考基线

2026-11-13，固定 onlyalpha-dev，Linux aarch64，Rust 1.99.1，bench/release优化，单编译任务。源码冻结摘要 `95f65185431cd4be521fe8fff8ced2bf1eba3e528c00908b2b22bf325f5685d4`。首个target输入摘要 `dcbcc54a32e148dff7361d18ae05c2140033dba9b6c83311f4647b3b41ba7b3c`；各target独立的输入、结果与二进制SHA256见原始identity.json，不把历史kernel绑定作为当前构建身份。

Criterion为每case至少10个原始样本；表中使用Criterion的median估计。固定慢样本使用3轮中位数，不据此推断可靠尾延迟。状态准备、缓存和析构边界以本页方法说明及case源码为准；没有清OS缓存，也没有硬件独占。原始结果：`test-results/backtest-observability/reference-01/market-data-construction/`（本轮位于主工作区）；包含build、identity、reference.log、report及Criterion原始样本。

| 场景 | 每次工作量 | 中位耗时 ms | 吞吐 /秒 | 样本数 |
| --- | ---: | ---: | ---: | ---: |
| provider_graph.compile/1 | 1 elements | 0.0130768 | 76471.3 | 10 |
| provider_graph.compile/32 | 32 elements | 0.417505 | 76645.7 | 10 |
| provider_graph.compile/8 | 8 elements | 0.104532 | 76531.5 | 10 |

增长观察（同一case的最大输入/最小输入总耗时比；仅说明这三档输入，不据此证明渐进复杂度）：

- `provider_graph.compile`：31.93 倍（32/1）。

## 限制

仅覆盖上面列出的入口。错误/恢复/复杂度曲线按覆盖矩阵解释；未测功能不能宣称覆盖。无新 CI 性能门槛；p95 的解释受样本数限制。
