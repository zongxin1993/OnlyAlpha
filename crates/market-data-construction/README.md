# onlyalpha-market-data-construction：行情构造

## 目的与职责

把显式行情输入与构造配方编译成计划，管理构造实例、时间 Bar 窗口及可恢复状态。

本库是 `crates/` 下的 Rust 库，供其他库、后端或插件通过 Rust 公开接口复用。
职责依据[仓库架构](../../docs/repository-product-architecture.md)和各语义所属契约；此说明不新增 Authority，也不替代正式契约。

## 边界与依赖

不拥有 Source、Runtime 或历史存储 Authority；构造管理器不作为正式交易就绪证明。

直接依赖的仓内库：[`onlyalpha-domain`](../domain/README.md)。
完整依赖、特性及编译配置见 [Cargo.toml](Cargo.toml)。调用方只能通过公开接口集成，不直接访问私有模块或修改所属状态。

## 公开接口

OnlyConstructionGraph / Recipe / Edge 描述构造图，OnlyConstructionPlan::compile 编译。OnlyConstructionResolutionPlan 解析能力与时间网格；OnlyConstructionExecutor / Factory / Registry 提供算法边界；OnlyConstructionManager::register / process 推进实例，OnlyTimeBarExecutor::window_for / preview 处理窗口。

[`OnlyConstructionResolutionPlan::resolve_historical_day`](src/resolution.rs) 仅在来源精确声明同一交易日历和日线语义的历史能力时返回原生计划。调用方按该日历的 Session 确认首开和末收。复权日线的构造身份还要绑定实际复权证据。

公开入口以 [`src/lib.rs`](src/lib.rs) 为准；以下为当前公开模块和重导出，详细签名、方法和前置条件以源码及 `cargo doc` 为准。Rust 库接口不等同于面向 Web / Agent 的版本化控制 API。

```rust
pub use compiler::*;
pub use model::*;
pub use resolution::*;
pub use executor::*;
pub use time_bar::{OnlyConstructionWindow, OnlyTimeBarExecutor};
pub use manager::*;
```

## 状态与生命周期

管理器保持唯一可变所有者，显式注册和取消；capture_checkpoint / restore_checkpoint 校验状态。缺失与不完整策略来自明确配方，错误由 OnlyConstructionError 返回，外部保存检查点。

## 使用与验证

在调用方 `Cargo.toml` 声明本库路径依赖，从上述入口选择类型或端口；配置、输入记录与身份必须按对应正式契约构建。

当前没有独立 Cargo 示例目标；可从公开入口和所属测试查看调用方式。

在仓库根目录执行：

```sh
cargo test -p onlyalpha-market-data-construction
cargo doc -p onlyalpha-market-data-construction --no-deps
```

集成测试位于 [`tests/`](tests/)，独立单元测试统一集中在 `src/tests/`，仍由原业务模块挂载并保留私有访问；内联测试可保留。 无外部服务依赖的库验证可在宿主机运行并记录平台；数据库或运行中应用验证使用固定 `onlyalpha-dev` 环境。

一级目录仅允许 `src/`、`tests/`、`examples/`、`benches/`，按需创建。编译资源归入 `src/`，专用测试数据随测试组织，共享参考数据使用根目录 `test-data/`。
