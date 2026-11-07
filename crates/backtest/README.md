# onlyalpha-backtest：回测执行

## 目的与职责

用冻结行情输入驱动有限回放，复用交易组件并产生进度、轨迹、终态和回测结果。

本库是 `crates/` 下的 Rust 库，供其他库、后端或插件通过 Rust 公开接口复用。
职责依据[仓库架构](../../docs/repository-product-architecture.md)和各语义所属契约；此说明不新增 Authority，也不替代正式契约。

## 边界与依赖

不负责产品任务准入、权限、队列或 LIVE 授权；不创建第二套交易语义。

直接依赖的仓内库：[`onlyalpha-runtime`](../runtime/README.md)、[`onlyalpha-calculation-bridge`](../calculation-bridge/README.md)、[`onlyalpha-clock`](../clock/README.md)、[`onlyalpha-domain`](../domain/README.md)、[`onlyalpha-execution`](../execution/README.md)、[`onlyalpha-strategy`](../strategy/README.md)、[`onlyalpha-market-data`](../market-data/README.md)。
完整依赖、特性及编译配置见 [Cargo.toml](Cargo.toml)。调用方只能通过公开接口集成，不直接访问私有模块或修改所属状态。

## 公开接口

Inputs / Source / MarketInput 校验输入及其身份；RunSpec、Participants、NextOpenPolicy 配置运行；RunLoop::create / open / step / run 执行或恢复；TerminalSnapshot::read 读取校验后的终态。Trading 适配 Strategy 节点，validate_configuration 只验证配置。

公开入口以 [`src/lib.rs`](src/lib.rs) 为准；以下为当前公开模块和重导出，详细签名、方法和前置条件以源码及 `cargo doc` 为准。Rust 库接口不等同于面向 Web / Agent 的版本化控制 API。

```rust
pub use inputs::{Inputs, MarketInput, OpeningInput, Source};
pub use next_open::NextOpenPolicy;
pub use onlyalpha_execution::Error;
pub use run::{Candidate, Participants, RunLoop, RunSpec, StepAndDeliverError};
pub use terminal::TerminalSnapshot;
pub use trading::Trading;
```

库根直接声明：`validate_configuration`。

## 状态与生命周期

RunLoop 管理输入关闭、取消、暂停、恢复和终止；Runtime 保存执行事实与回放绑定。读取终态仍校验配置、工件及精确切片，不能用缺证推断成功。

## 使用与验证

在调用方 `Cargo.toml` 声明本库路径依赖，从上述入口选择类型或端口；配置、输入记录与身份必须按对应正式契约构建。

当前没有独立 Cargo 示例目标；可从公开入口和所属测试查看调用方式。

在仓库根目录执行：

```sh
cargo test -p onlyalpha-backtest
cargo doc -p onlyalpha-backtest --no-deps
```

集成测试位于 [`tests/`](tests/)，独立单元测试统一集中在 `src/tests/`，仍由原业务模块挂载并保留私有访问；内联测试可保留。 无外部服务依赖的库验证可在宿主机运行并记录平台；数据库或运行中应用验证使用固定 `onlyalpha-dev` 环境。

一级目录仅允许 `src/`、`tests/`、`examples/`、`benches/`，按需创建。编译资源归入 `src/`，专用测试数据随测试组织，共享参考数据使用根目录 `test-data/`。
