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

RollingMean::new / push 维护固定小数位系数均值；LinearWeightedMean 在完整窗口后输出加权均值。fractional_change 返回指定量化尺度的变化率或溢出无值；round_ratio 对正分母做半偶数舍入；algebra 提供十进制代数及窗口能力。

`registry` 是算子正式契约的唯一声明处：`TYPE_ID_PREFIX`、`SEMANTIC_VERSION`、`NUMERIC_POLICY`、`OpSpec`、`ParameterKind`、`ExecutionShape`、`WarmupRule`、`StateCapability`，以及 `all`、`lookup`、`Operator::spec`、`Operator::type_id`、`Operator::from_type_id`。`minimum_observations` 把 warmup 规则换算成“第几个观测开始有输出”，避免逐算子重复判断差一错误。

`execution` 声明 `VectorKernel::evaluate` 与 `EventKernel::step`、`capture_state`、`restore_state`，由 `algebra::Kernel` 和 `algebra::Stream` 分别实现。二者共享同一数值实现，等价性、因果性和状态恢复由 `tests/certification.rs` 逐点认证。

公开入口以 [`src/lib.rs`](src/lib.rs) 为准；以下为当前公开模块和重导出，详细签名、方法和前置条件以源码及 `cargo doc` 为准。Rust 库接口不等同于面向 Web / Agent 的版本化控制 API。

```rust
pub mod algebra;
pub mod execution;
pub mod registry;
```

库根直接声明：`RollingMean`、`LinearWeightedMean`、`fractional_change`、`round_ratio`。

## 状态与生命周期

窗口实例依次接收输入，内部保存样本，无持久化服务。调用方负责保持尺度一致与输入顺序；round_ratio 的非正分母属于显式 panic 前置条件，不能用浮点近似替代规范舍入。

事件形态的状态能力由注册表声明：截面算子只在研究批处理中有意义，`Stream::new` 对其返回 `Error::ResearchOnly`；时间序列算子按 warmup 规则区分为无状态或可检查点。检查点只包含算子窗口内实际读取的列，恢复必须与同一参数下的新实例等价，非法检查点不得改动现有实例。

## 使用与验证

在调用方 `Cargo.toml` 声明本库路径依赖，从上述入口选择类型或端口；配置、输入记录与身份必须按对应正式契约构建。

当前没有独立 Cargo 示例目标；可从公开入口和所属测试查看调用方式。

在仓库根目录执行：

```sh
python3 scripts/unit_tests.py
python3 scripts/dev_verification.py run -- python scripts/rust_kernel_check.py --package onlyalpha-operators
python3 scripts/rust_kernel_check.py
cargo doc -p onlyalpha-operators --no-deps
```

`tests/registry.rs` 核对注册表每个算子恰有一行、身份唯一且与数值内核的元数、参数和形态一致；`tests/certification.rs` 为每个算子独立推导 golden，并逐点认证 Vector 与 Event 等价、多前缀因果、warmup 边界、全缺失输入和检查点恢复。

独立单元测试统一集中在 `src/tests/`，仍由原业务模块挂载并保留私有访问；内联测试可保留，不为占位创建空的 Cargo 集成测试目录。 无外部服务依赖的库验证可在宿主机运行并记录平台；数据库或运行中应用验证使用固定 `onlyalpha-dev` 环境。

一级目录仅允许 `src/`、`tests/`、`examples/`、`benches/`，按需创建。编译资源归入 `src/`，专用测试数据随测试组织，共享参考数据使用根目录 `test-data/`。

性能基准入口与口径见 [BENCHMARK.md](BENCHMARK.md)。
