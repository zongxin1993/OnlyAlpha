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
