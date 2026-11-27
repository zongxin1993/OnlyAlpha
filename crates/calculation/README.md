# onlyalpha-calculation：计算契约与状态

## 目的与职责

定义计算类型、参数解析、图拓扑、实现注册、执行绑定和游标，维护计算输出状态及 readiness 证据。

本库是 `crates/` 下的 Rust 库，供其他库、后端或插件通过 Rust 公开接口复用。
职责依据[仓库架构](../../docs/repository-product-architecture.md)和各语义所属契约；此说明不新增 Authority，也不替代正式契约。

## 边界与依赖

不实现具体算法、不管理进程传输、不授予正式 Runtime 准入；内部 Definition 与 product 线协议读取模型分别管理。

依赖 `onlyalpha-operators` 的纯 Rust 数值原语；不依赖 Python、数据库或后端权限。
完整依赖、特性及编译配置见 [Cargo.toml](Cargo.toml)。调用方只能通过公开接口集成，不直接访问私有模块或修改所属状态。

## 公开接口

[`finite_input::requirements`](src/finite_input.rs) 以及同模块的 `node_execution_starts` 分别计算图的累计预热长度、外部输入引用和每节点首次执行前的上游阻塞长度，不处理行情时间轴、权限、Target 未来窗口，也不执行受控案例。

TypeReference / TypeDefinition / Definition 和 Graph 构造可指纹化定义；Registry 注册解析 Provider。ExecutionBinding、ExecutionCursor、CalculationState 通过 prepare / commit / capture / restore 管理执行位置及输出；ReadinessPlan 评估明确要求。[`product`](src/product.rs) 模块读取当前产品计算记录。`product::Graph::from_record_with_work` 返回已校验的图和扫描、小数展开实际计入的工作量，便于调用方在多份记录间共享上限。

公开入口以 [`src/lib.rs`](src/lib.rs) 为准；以下为当前公开模块和重导出，详细签名、方法和前置条件以源码及 `cargo doc` 为准。Rust 库接口不等同于面向 Web / Agent 的版本化控制 API。

```rust
pub use definition::{Definition, TypeDefinition, TypeReference};
pub use execution::{ExecutionBinding, ExecutionCursor, MAX_BATCH, PreparedBatch};
pub use graph::Graph;
pub use registry::{Backend, Registration, Registry};
pub use readiness::{ReadinessBarrier, ReadinessPlan, ReadinessRequirement, ReadinessStatus};
pub use state::{
    CalculationSnapshot, CalculationState, InputPosition, StateOutcome, normalize_result_outputs,
};
pub mod product;
pub mod program;
pub mod factor_expr;
```

库根直接声明：`CalculationError`、`Result`。

### 声明式因子表达式与双模式执行器

[`factor_expr`](src/factor_expr/mod.rs) 实现 ADR 0152 规定的声明式因子表达式解析、静态因果校验与双模式 DAG／指令流执行器，全部算子语义直接复用 [`onlyalpha-operators`](../operators/README.md) 已认证双内核：

- 顶层类型静态区分 `FactorExpr` 与 `TargetExpr`：`FactorExpr` 在编译期强制拒绝一切前视偏移（如 `Ref($x, -n)`、`Lead($x, n)`、负窗口期）与账户／持仓／资金／成交／时钟／随机数／未来标签输入，并支持单序列 `evaluate_vector`、`event_executor` 以及对齐多标的面板 `evaluate_panel`、`panel_event_executor`；`TargetExpr` 仅限 Research 评估标签，允许显式有界前瞻偏移，类型系统禁止其构造事件执行器或进入交易引擎。
- `CSScale(x)` 用当日有效截面的绝对值之和归一化，`GroupDemean(x, group)` 按当日数值分组去均值，两者通过面板执行。`Product(x, n)` 计算完整窗口的连乘，`SMA(x, n, m)` 从首个有效值按整数权重 `m/n` 递推，`Pow(x, y)` 逐点计算幂。窗口和权重须为编译期常量，递推权重随 DAG 指纹绑定。
- `RegressionResidual3(y, x1, x2, x3, n)` 求滚动三元回归的末点残差，`ConditionalBeta(y, x, cond, n)` 在最近 `n` 个事件内按条件求回归斜率，`CumProductIf(value, cond)` 从 1 开始按条件累乘。后二者以条件值等于 1 为真。回归窗口下限分别是 5 和 2，窗口计算预算累计每个输入列的访问量。
- 编译阶段完成公共子表达式去重（CSE）、静态预热长度与资源预算计算、规范表达与 SHA-256 指纹绑定；`EventExecutor` 与 `PanelEventExecutor` 支持事务化 `step` 与 `DagState`／`PanelDagState` 检查点恢复（含规范 JSON 编解码与指纹绑定校验）。
- [`factor_expr_dag`](tests/factor_expr_dag.rs) 覆盖编译期前视拒绝、禁区输入拒绝、独立 golden、`Vector == Event` 与面板逐点等价、多前缀因果、warmup/null 边界、检查点恢复与解析预算边界。[`alpha158`](tests/alpha158.rs) 从[示例清单](../../examples/factor/qlib/alpha158/manifest.json)读取 158 份表达式，核对定义摘要，并将面板批量、逐事件和检查点恢复后的输出与冻结的十进制预期值逐点比较。

## 状态与生命周期

批次提交绑定 revision、输入摘要及显式时间；恢复检查绑定一致性。状态由调用方持久化，注册或单次读取成功不能被当作正式可交易证明。

## 使用与验证

在调用方 `Cargo.toml` 声明本库路径依赖，从上述入口选择类型或端口；配置、输入记录与身份必须按对应正式契约构建。

当前没有独立 Cargo 示例目标；可从公开入口和所属测试查看调用方式。

在仓库根目录执行：

```sh
cargo test -p onlyalpha-calculation
cargo doc -p onlyalpha-calculation --no-deps
```

集成测试位于 [`tests/`](tests/)，独立单元测试统一集中在 `src/tests/`，仍由原业务模块挂载并保留私有访问；内联测试可保留。 无外部服务依赖的库验证可在宿主机运行并记录平台；数据库或运行中应用验证使用固定 `onlyalpha-dev` 环境。

一级目录仅允许 `src/`、`tests/`、`examples/`、`benches/`，按需创建。编译资源归入 `src/`，专用测试数据随测试组织，共享参考数据使用根目录 `test-data/`。

性能基准入口与口径见 [BENCHMARK.md](BENCHMARK.md)。

### 新框架的接口边界

[有限作业契约](../../docs/job-execution-contract.md)规定本库后续与因子构建、共同信号、typed会话或完成owner的接口关系。本库已提供上述 program 接口，完整作业、输入与发布接线由所属后端 owner 负责。后端冻结身份不反向进入纯库依赖，数据库／权限接线留在Backend。

### 一次构建的因子程序

[`program`](src/program.rs) 接收有界 canonical JSON，`Program::decode` 检查类型、反向引用、指令和数值预算；`resolve_parameters` 解析精确值，`bind` 在创建窗口前校验参数与总状态预算。输出 `BoundProgram` 可共享，其身份包含程序和规范化参数。以上步骤不授予 READY 或交易权限。

`ProgramValue` 区分精确 Integer、Decimal、Boolean 与 Missing；整数保持操作不丢失类型，普通数学和窗口输出 Decimal。

`ProgramInput` 只含明确 instrument、从零连续的 sequence 和行情／上游因子值。`ProgramInstance` 每实例独占窗口，`step` 失败不推进任何窗口或游标。`evaluate_batch` 使用同一 step／原语／顺序，保持 Decimal28、HALF_EVEN、q12 和缺值规则。`capture/restore` 校验 schema、精确绑定、instrument、cursor 和窗口长度，恢复失败不改变原实例。恢复值由调用方持久化，本库不拥有正式事实。

细节见[因子程序说明](../../docs/factor-program.md)，基准覆盖 decode、bind、batch、event、null、长窗口和四实例。
