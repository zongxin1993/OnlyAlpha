# onlyalpha-operators：通用数学算子

## 目的与职责

提供与市场无关的数学、滚动窗口、固定精度比率和代数运算，为指标及计算适配提供数值内核。

同一份数值实现在两种执行形态下对外提供：`VectorKernel` 一次接收完整列，`EventKernel` 逐事件推进并可捕获、恢复状态。算子身份、输入元数、参数种类、执行形态、warmup 规则和状态能力统一由 `registry` 声明；指标、Calculation 适配和插件只能引用该注册表，不各自维护算子名单。

本库是 `crates/` 下的 Rust 库，供其他库、后端或插件通过 Rust 公开接口复用。
职责依据[仓库架构](../../docs/repository-product-architecture.md)和各语义所属契约；此说明不新增 Authority，也不替代正式契约。

## 边界与依赖

纯 Rust 库，无 Python 接口；不定义金融指标含义、Calculation 清单、图调度、策略或运行准入。

没有直接依赖的仓内库。
完整依赖、特性及编译配置见 [Cargo.toml](Cargo.toml)。调用方只能通过公开接口集成，不直接访问私有模块或修改所属状态。

## 公开接口

`algebra` 提供十进制代数、滚动窗口、递推与截面数值内核（精度 28、半偶数舍入、q12 输出、规范正零）。滚动回归的决定系数与末点残差以窗口内的位置为自变量，少于两个点均为空，常量窗口的决定系数为空、残差为零。`RollingQuantile` 接收 `period` 与精确十进制 `quantile`（含端点的 `[0,1]`），以 `(period−1)×quantile` 精确定位。位置含小数时，先取相邻次序统计量之差，再乘位置的小数部分，最后加回较小的次序统计量；三个运算各按 28 位有效数字半偶舍入，输出取 12 位小数。`RollingArgMax`、`RollingArgMin` 返回从窗口最旧观测起、以 1 为基的首次极值位置。五项都要求完整非缺值窗口。

[`registry`](src/registry.rs) 声明算子身份、参数、形态与预热规则。五项滚动算子的注册名为 `rolling_r_squared`、`rolling_residual`、`rolling_quantile`、`rolling_arg_max`、`rolling_arg_min`，调用方以 `onlyalpha.operator.` 加注册名经 `lookup` 查询。`ParameterKind::PeriodQuantile` 同时要求 `period` 和 `quantile`。`OpSpec::minimum_observations` 给出首次可能产生有效值所需的观测数，实际输出仍取决于缺值及数值定义域。

`cross_section_scale` 用当日所有有效输入的绝对值之和作分母，零分母返回全空。`group_demean` 只将数值与分组编码均有效的标的计入对应组，输出组内离均差，单成员组输出零。`rolling_product` 按时间从旧到新连乘完整窗口。`sma` 通过 `ParameterKind::PeriodWeight` 绑定正整数 `period` 和 `weight`，要求 `weight ≤ period`，按 `(weight × 当前值 + (period − weight) × 前值) / period` 递推，由首个有效值初始化，缺值当步输出空并保留前值。`pow` 接收底数、指数两列，逐点求幂。零的非正次幂和负底数的非整数次幂输出空，数值超出输出范围或达不到舍入精度时返回 `Error::NumericFailure`。

`regression_residual3(y, x1, x2, x3)` 要求 `period ≥ 5`，用带截距的三元线性回归求完整窗口最后一行的残差；窗口含缺值或设计矩阵秩不足时输出空。`conditional_beta(y, x, cond)` 要求 `period ≥ 2`，先取完整日历窗口，再选出 `cond = 1` 且 `x`、`y` 均有效的行，返回带截距的一元斜率；不足两对或 `x` 无变动时输出空。`cum_product_if(value, cond)` 从 1 开始，仅 `cond = 1` 时乘入当前值，其他有效条件返回前值。任一输入缺失时输出空并保留状态，其检查点的第一列存累计值，第二列为空。

[`VectorKernel::evaluate`](src/execution.rs) 由 `algebra::Kernel` 实现。`EventKernel` 通过关联类型 `Input`、`Output` 区分两种事件输入。36 个时序算子使用 `algebra::Stream`，每步接收一个标的的字段值并返回一个值。7 个截面算子（百分位、排名、标准分、去均值、相关系数、L1 归一化、组内去均值）使用 `CrossSectionStream::new(kernel, instrument_count)`，每步接收同一事件中按固定标的顺序排列的字段列，返回对应标的的一列结果。输入列宽与绑定的标的数不符时返回 `Error::InvalidInputs`。

公开入口以 [`src/lib.rs`](src/lib.rs) 为准；以下为当前公开模块和重导出，详细签名、方法和前置条件以源码及 `cargo doc` 为准。Rust 库接口不等同于面向 Web / Agent 的版本化控制 API。

```rust
pub mod algebra;
pub mod execution;
pub mod registry;
```

## 状态与生命周期

截面算子只依赖当前事件的完整截面，`CrossSectionStream` 捕获空检查点，恢复时拒绝非空状态；通过单标的 `Stream::new` 构造截面算子会返回 `Error::CrossSectionRequired`。时序算子按注册表声明分为无状态和可检查点。窗口与递推状态通过 `EventKernel::capture_state`、`restore_state` 捕获和恢复，非法检查点不会改动现有实例。状态由调用方持久化。

## 使用与验证

在调用方 `Cargo.toml` 声明本库路径依赖，从上述入口选择类型或端口；配置、输入记录与身份必须按对应正式契约构建。

当前没有独立 Cargo 示例目标；可从公开入口和所属测试查看调用方式。

在仓库根目录执行：

```sh
python3 scripts/unit_tests.py
cargo doc -p onlyalpha-operators --no-deps
```

[`registry`](tests/registry.rs) 核对每个算子的身份唯一性、输入元数、参数及执行形态。[`certification`](tests/certification.rs) 使用独立数值 golden 核对输出，并比较向量和逐事件结果、多个事件前缀及检查点恢复后的后缀。时序用例包含预热、缺值、常量窗口和非默认缩放系数；截面用例按完整事件核对标的输出。

独立单元测试统一集中在 `src/tests/`，仍由原业务模块挂载并保留私有访问；内联测试可保留，不为占位创建空的 Cargo 集成测试目录。 无外部服务依赖的库验证可在宿主机运行并记录平台；数据库或运行中应用验证使用固定 `onlyalpha-dev` 环境。

一级目录仅允许 `src/`、`tests/`、`examples/`、`benches/`，按需创建。编译资源归入 `src/`，专用测试数据随测试组织，共享参考数据使用根目录 `test-data/`。

性能基准入口与口径见 [BENCHMARK.md](BENCHMARK.md)。
