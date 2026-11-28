# onlyalpha-calculation-bridge：计算桥接

## 目的与职责

提供 Gateway 协议绑定、算法通信客户端、Strategy 适配，以及原生算子和谓词的 Calculation 适配。

本库是 `crates/` 下的 Rust 库，供其他库、后端或插件通过 Rust 公开接口复用。
职责依据[仓库架构](../../docs/repository-product-architecture.md)和各语义所属契约；此说明不新增 Authority，也不替代正式契约。

## 边界与依赖

宿主负责产品准入、任务调度、进程创建、部署和权限校验，通过显式端口接入算法通道。算法安装目录、发行清单以及从安装文件核验实际执行工件的流程均由宿主管理。

直接依赖的仓内库：[`onlyalpha-operators`](../operators/README.md)、[`onlyalpha-predicates`](../predicates/README.md)、[`onlyalpha-strategy`](../strategy/README.md)、[`onlyalpha-market-data`](../market-data/README.md)、[`onlyalpha-calculation`](../calculation/README.md)、[`onlyalpha-domain`](../domain/README.md)。
完整依赖、特性及编译配置见 [Cargo.toml](Cargo.toml)。调用方只能通过公开接口集成，不直接访问私有模块或修改所属状态。

## 公开接口

[`ProgramNodes`、`ProgramFactor`](src/program_nodes.rs)把已绑定的 Rust 因子程序、原生算子和谓词接入原 Strategy `NodePort`。构造时核对精确定义、参数、端口、数值类型、实现与工件绑定；执行使用 `BoundProgram`／`OperatorStream`／`PredicateCalculation`，不解析 Python AST。程序事件序号从零开始，适配层的 Calculation receipt 样本计数从一开始。缺值、输出规范化及窗口语义沿用所属数学 owner。

[`ProgramCalculation`](src/program_definition.rs)从已解码且绑定参数的 `BoundProgram` 和因子元数据生成完整 `Definition`、`TypeDeclaration` 与批量／事件实现清单。校验输入输出类型与角色，参数声明来自原程序，warmup 来自实际绑定窗口，数值规范固定为 Decimal28／Half Even／Q12。实现身份绑定泛化程序容器、API 与实际执行镜像；精确参数及其证书由调用方单独绑定。类型、声明或工件格式不符时拒绝。此纯值适配器不读取 PostgreSQL，不证明 READY、资产权限或实际加载镜像；正式调用方必须保留所属读取器和准入证据。

实例按 scope／商品／节点持有可变状态。恢复采用独立候选，核对完整字段、绑定、游标、receipt 与窗口，错误使当前执行失效。`ProgramFactor::new` 和 `ProgramNodes::new` 只校验传入的数学绑定值，不证明 PostgreSQL 证书存在、READY、私有资产权限或发布资格；这些证明由持有相应事实的宿主读取器提供。

[`ImplementationArtifact::new(relative_path, byte_sha256)`](src/implementation_artifact.rs) 接收宿主已核验的执行工件。路径使用 `/` 分隔，必须是规范相对路径，摘要为 64 位小写十六进制 SHA-256。非法输入返回 `IMPLEMENTATION_ARTIFACT_INVALID`。算子、谓词与因子程序把相同格式的资源记录写入实现清单，路径和字节摘要共同参与实现指纹计算。`native_operators::provider_record(artifact, provider_version, distribution_name, distribution_version)` 将提供方指定的内容版本写入 `manifest.provider_version`，将宿主发行名和发行版本写入 `manifest.source`。工件迁址或字节变化会改变内容指纹，提供方须指定新版本；仅更换发行来源时可沿用提供方版本，内容指纹保持一致。目录在准入时核对历史版本与内容的对应关系。

Worker::from_stream 接入已有通道并执行握手和请求；WorkerConnector / ProcessControl 提供连接与生命周期端口。StrategyNodes、StrategyPreparation 连接计算与行情准备；[`native_operators::OperatorCalculation`](src/native_operators.rs) 和 [`native_predicates`](src/native_predicates.rs) 暴露定义、清单与求值。滚动分位数 `onlyalpha.operator.rolling_quantile` 要求同时传入正整数 `period` 和 `[0,1]` 内的 `DECIMAL` 参数 `quantile`；`resolve` 按声明解析参数并纳入精确定义。递推平滑 `onlyalpha.operator.sma` 绑定两个整数 `period` 和 `weight`，其中 `1 ≤ weight ≤ period`。`protocol` 提供协议绑定。fingerprint 计算原始字节摘要。

[`native_operators::SEMANTIC_VERSION`](src/native_operators.rs) 取自内核注册表。`regression_residual3` 绑定 `response`、`x1`、`x2`、`x3`，窗口至少 5 期。`conditional_beta` 绑定 `response`、`predictor`、`condition`，窗口至少 2 期。`cum_product_if` 绑定 `value` 与 `condition`，按标的保存累计乘积。检查点绑定规范化参数所在的定义指纹。标量交易端口只接受时序算子，截面算子通过完整截面批量输入求值。

公开入口以 [`src/lib.rs`](src/lib.rs) 为准；以下为当前公开模块和重导出，详细签名、方法和前置条件以源码及 `cargo doc` 为准。Rust 库接口不等同于面向 Web / Agent 的版本化控制 API。

```rust
pub use process::{
    Cancellation, ProcessControl, ProcessState, Result, Worker, WorkerConnector, WorkerError,
    serve_chart,
};
pub use strategy_adapter::StrategyNodes;
pub use strategy_preparation::StrategyPreparation;
pub use implementation_artifact::ImplementationArtifact;
pub mod native_predicates;
pub mod protocol;
pub mod native_operators;
```

库根直接声明：`fingerprint`。

## 状态与生命周期

Cancellation 保留同一工作所有者的取消和 drain 路径；WorkerError 区分通信失败。算法检查点绑定实际实现及输入，恢复先校验候选；库不启动另一个产品运行 Authority。

## 使用与验证

在调用方 `Cargo.toml` 声明本库路径依赖，从上述入口选择类型或端口；配置、输入记录与身份必须按对应正式契约构建。

当前没有独立 Cargo 示例目标；可从公开入口和所属测试查看调用方式。

在仓库根目录执行：

```sh
cargo test -p onlyalpha-calculation-bridge
cargo doc -p onlyalpha-calculation-bridge --no-deps
```

集成测试位于 [`tests/`](tests/)，独立单元测试统一集中在 `src/tests/`，仍由原业务模块挂载并保留私有访问；内联测试可保留。 无外部服务依赖的库验证可在宿主机运行并记录平台；数据库或运行中应用验证使用固定 `onlyalpha-dev` 环境。

一级目录仅允许 `src/`、`tests/`、`examples/`、`benches/`，按需创建。编译资源归入 `src/`，专用测试数据随测试组织，共享参考数据使用根目录 `test-data/`。

性能基准入口与口径见 [BENCHMARK.md](BENCHMARK.md)。
