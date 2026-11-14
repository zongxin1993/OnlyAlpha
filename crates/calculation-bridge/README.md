# onlyalpha-calculation-bridge：计算桥接

## 目的与职责

提供 Gateway 协议绑定、算法通信客户端、Strategy 适配，以及原生算子和谓词的 Calculation 适配。

本库是 `crates/` 下的 Rust 库，供其他库、后端或插件通过 Rust 公开接口复用。
职责依据[仓库架构](../../docs/repository-product-architecture.md)和各语义所属契约；此说明不新增 Authority，也不替代正式契约。

## 边界与依赖

不拥有产品准入或任务调度；进程创建、部署、权限及生命周期策略由后端提供，库通过显式端口使用。

直接依赖的仓内库：[`onlyalpha-operators`](../operators/README.md)、[`onlyalpha-predicates`](../predicates/README.md)、[`onlyalpha-strategy`](../strategy/README.md)、[`onlyalpha-market-data`](../market-data/README.md)、[`onlyalpha-calculation`](../calculation/README.md)、[`onlyalpha-domain`](../domain/README.md)。
完整依赖、特性及编译配置见 [Cargo.toml](Cargo.toml)。调用方只能通过公开接口集成，不直接访问私有模块或修改所属状态。

## 公开接口

Worker::from_stream 接入已有通道并执行握手和请求；WorkerConnector / ProcessControl 提供连接与生命周期端口。StrategyNodes、StrategyPreparation 连接计算与行情准备；ChartInstallation 校验安装资源；native_operators / native_predicates 暴露定义、清单与求值，protocol 提供协议绑定。fingerprint 计算原始字节摘要。

公开入口以 [`src/lib.rs`](src/lib.rs) 为准；以下为当前公开模块和重导出，详细签名、方法和前置条件以源码及 `cargo doc` 为准。Rust 库接口不等同于面向 Web / Agent 的版本化控制 API。

```rust
pub use process::{
    Cancellation, ProcessControl, ProcessState, Result, Worker, WorkerConnector, WorkerError,
    serve_chart,
};
pub use strategy_adapter::StrategyNodes;
pub use strategy_preparation::StrategyPreparation;
pub use chart_installation::ChartInstallation;
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
