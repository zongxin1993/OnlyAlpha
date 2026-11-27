# onlyalpha-research-statistics

## 目的与职责

本库在同一冻结面板上回答三个研究问题：因子与标签在每个时点的横截面相关性有多大，有多少时点和标的配对支持这个结论，以及更换时段或与另一个因子比较时结果怎样变化。数学程序可直接读取 `FactorReport`，AI 可通过同一报告的 JSON 视图读取摘要、分期和观测明细。统计口径见 [ADR 0082](../../docs/adr/0082-research-target-statistics-evaluation-authority.md) 和 [ADR 0119](../../docs/adr/0119-rich-research-statistics-authority-and-factor-quality-evidence-contract.md)。

## 边界与依赖

[Runtime](../runtime/README.md) 负责冻结面板和表达式求值，本库借用求值后的矩阵。快照授权由行情读取方核对，正式结果及证据关联归 Research Result，因子准入判断归 Qualification。本库返回具有来源绑定的内存统计结果。

直接使用 `onlyalpha-domain` 的标的身份和时间、`onlyalpha-operators` 的 Decimal 和输入预算、`onlyalpha-execution` 的错误类型。`bigdecimal` 提供精确十进制运算，`sha2` 计算内容摘要，`serde_json` 构造机器视图。[依赖清单](Cargo.toml)

## 公开接口

- `EvaluationAxis` 指定快照、冻结面板内容摘要、标的顺序、完整时间轴和预热行数。每个 `SeriesRef` 借用一份 `[标的][时间]` 矩阵，并携带该轴、名称及表达式指纹。通过 `FactorSeriesRef`、`TargetSeriesRef` 指明序列的角色。`column_digest` 对列内的缺值及规范化 Decimal 编码计算 SHA-256。[输入绑定](src/input.rs)
- `StatisticsPlan::new(slices, pairs)` 接收升序且互不重叠的 `TimeSlice` 半开区间及指定因子名称对。默认计划只比较所有因子与所有标签。分期允许使用 `i64::MAX + 1` 作为排他右界。`check_budget` 依据面板维度、定义数、比较数及分期数在计算前检查预算。[统计计划](src/plan.rs)
- `evaluate(input, plan)` 接收 `EvaluationInput` 与统计计划，最小配对数至少为 2。它核对序列的来源、轴、形状、名称、指纹及数值，返回 `Result<FactorReport, Error>`。不同来源或形状、非法分期、无效因子对、超预算分别返回对应错误；样本不足与零方差则体现在报告的统计状态中。[计算入口与结果类型](src/lib.rs)
- `FactorReport::comparisons()` 按因子和标签的声明顺序返回 `ResearchComparison`，包含逐时点 Pearson IC 和平均秩 Spearman RankIC、样本摘要、观测覆盖及可选的分期结果。`pairs()` 返回 `FactorPairComparison`，其索引指向实际因子，顺序由表达式指纹确定。`factors()`、`targets()` 提供名称、表达式指纹和实际值摘要。[报告访问器](src/lib.rs)
- `summary_view()` 导出全局摘要，`comparison_view(ComparisonRef)` 独立导出一组比较，`slice_view(comparison_index, slice_index)` 取一组因子与标签在某段的结果，`detail_view(reference, start_ns, end_ns)` 按半开区间读取行。视图保留状态、指标标识和规范 Decimal 字符串，纳秒时间使用十进制字符串。一次读取超限可按比较、分期或时间区间分别读取；未知比较和分期返回错误。[机器读取视图](src/view.rs)

## 状态与生命周期

每次计算只读取输入，报告持有来源、两条轴、计划分期、序列绑定与统计结果。统计从 `timestamps[warmup]` 开始，对每个时点仅使用两侧都有有效值的标的。同一时点的 Pearson 和 Spearman 共享这一批标的，缺值保留在原位置。行记录实际配对数及有效、样本不足或哪一侧零方差等状态。有效相关系数为零时仍进入统计。

均值、正负零比例、样本标准差和非年化 IR 使用有效的 Q12 行值。标准差分母为 `n−1`，IR 使用尚未量化为 Q12 的标准差。统计采用 38 位十进制上下文，最终数值以 half-even 舍入至 Q12。观测覆盖包含全部样本时点及其配对数；分期保留空区间，跨期摘要只汇总具有有效均值的分期。历史成分股资格需要由数据源另行提供。[数值实现](src/math.rs) · [覆盖与分期](src/summary.rs)

## 使用与验证

通过 `OnlyAlphaRuntime::run_research` 调用时，`ResearchReport::factor_report()` 可取回统计报告。可以先读比较摘要，再以同一 `ComparisonRef` 读取日期明细，核对某个时点的零值或缺测原因。若已有依照相同约定冻结、求值的矩阵，也可直接构造 `EvaluationInput` 调用 `evaluate`。[Runtime 调用示例](../runtime/README.md#公开接口)

在仓库根目录通过主机单测入口运行本库及 Runtime 门面用例：

```bash
python3 scripts/unit_tests.py
```
