# onlyalpha-market-data：行情准备流水线

## 目的与职责

组合行情状态、构造和计算准备，再把准备结果交付消费端；统一管理流水线程序及检查点恢复。

本库是 `crates/` 下的 Rust 库，供其他库、后端或插件通过 Rust 公开接口复用。
职责依据[仓库架构](../../docs/repository-product-architecture.md)和各语义所属契约；此说明不新增 Authority，也不替代正式契约。

## 边界与依赖

不拥有 Source 准入、外部数据采集或经济执行；行情可读或准备完成不等于获准交易。

直接依赖的仓内库：[`onlyalpha-domain`](../domain/README.md)、[`onlyalpha-calculation`](../calculation/README.md)、[`onlyalpha-market-data-construction`](../market-data-construction/README.md)。
完整依赖、特性及编译配置见 [Cargo.toml](Cargo.toml)。调用方只能通过公开接口集成，不直接访问私有模块或修改所属状态。

## 公开接口

PipelineProgram / SourceProgram / ClusterProgram 定义配置；MarketDataPipeline<C,D>::process 接收 PipelineInput，返回 PreparedMarketData；CalculationPort 和 PreparationConsumer 连接计算与消费者。state / delivery 暴露状态与交付契约，construction 重导出行情构造库。

公开入口以 [`src/lib.rs`](src/lib.rs) 为准；以下为当前公开模块和重导出，详细签名、方法和前置条件以源码及 `cargo doc` 为准。Rust 库接口不等同于面向 Web / Agent 的版本化控制 API。

```rust
pub use model::*;
pub use pipeline::*;
pub use onlyalpha_market_data_construction as construction;
pub mod delivery;
pub mod state;
```

## 状态与生命周期

流水线持有最新行情、计算及交付状态，capture_checkpoint / restore_checkpoint 校验关联后恢复；PipelineError 报告失败。持久化和正式准入由调用方管理。

## 使用与验证

在调用方 `Cargo.toml` 声明本库路径依赖，从上述入口选择类型或端口；配置、输入记录与身份必须按对应正式契约构建。

当前没有独立 Cargo 示例目标；可从公开入口和所属测试查看调用方式。

在仓库根目录执行：

```sh
cargo test -p onlyalpha-market-data
cargo doc -p onlyalpha-market-data --no-deps
```

集成测试位于 [`tests/`](tests/)，独立单元测试统一集中在 `src/tests/`，仍由原业务模块挂载并保留私有访问；内联测试可保留。 无外部服务依赖的库验证可在宿主机运行并记录平台；数据库或运行中应用验证使用固定 `onlyalpha-dev` 环境。

一级目录仅允许 `src/`、`tests/`、`examples/`、`benches/`，按需创建。编译资源归入 `src/`，专用测试数据随测试组织，共享参考数据使用根目录 `test-data/`。

性能基准入口与口径见 [BENCHMARK.md](BENCHMARK.md)。
