# onlyalpha-execution：交易执行协调

## 目的与职责

组合各交易组件，生成确定性的执行计划，通过存储端口有序提交并从已提交记录恢复精确投影。

本库是 `crates/` 下的 Rust 库，供其他库、后端或插件通过 Rust 公开接口复用。
职责依据[仓库架构](../../docs/repository-product-architecture.md)和各语义所属契约；此说明不新增 Authority，也不替代正式契约。

## 边界与依赖

不实现具体存储驱动或券商规则，不授予正式 Runtime 激活；每类资金、仓位、风险等事实仍由其所属组件管理。

直接依赖的仓内库：[`onlyalpha-margin`](../margin/README.md)、[`onlyalpha-settlement`](../settlement/README.md)、[`onlyalpha-fee`](../fee/README.md)、[`onlyalpha-domain`](../domain/README.md)、[`onlyalpha-order`](../order/README.md)、[`onlyalpha-position`](../position/README.md)、[`onlyalpha-account`](../account/README.md)、[`onlyalpha-strategy-ledger`](../strategy-ledger/README.md)、[`onlyalpha-risk`](../risk/README.md)。
完整依赖、特性及编译配置见 [Cargo.toml](Cargo.toml)。调用方只能通过公开接口集成，不直接访问私有模块或修改所属状态。

## 公开接口

Components 接收配置和交易输入，Prepared 表示准备结果；Store、CommitIntent、Record 定义提交边界，coordinate / recover 协调提交与恢复，pending_events 提取待交付事件。LedgerReconciliation、RuntimePerformance、BacktestResult 提供所属组合查询结果。

公开入口以 [`src/lib.rs`](src/lib.rs) 为准；以下为当前公开模块和重导出，详细签名、方法和前置条件以源码及 `cargo doc` 为准。Rust 库接口不等同于面向 Web / Agent 的版本化控制 API。

```rust
pub use components::Components;
pub use model::{Error, Prepared, digest};
pub use coordinator::{CommitIntent, Record, Store, coordinate, pending_events, recover};
pub use reconciliation::LedgerReconciliation;
pub use performance::RuntimePerformance;
pub use backtest_result::BacktestResult;
```

## 状态与生命周期

准备与提交按显式顺序处理；恢复以已提交记录为依据，不能猜测未知操作。Store 由外部实现，数据库事务和真实外部副作用不隐藏在纯计划内。

## 使用与验证

在调用方 `Cargo.toml` 声明本库路径依赖，从上述入口选择类型或端口；配置、输入记录与身份必须按对应正式契约构建。

当前没有独立 Cargo 示例目标；可从公开入口和所属测试查看调用方式。

在仓库根目录执行：

```sh
cargo test -p onlyalpha-execution
cargo doc -p onlyalpha-execution --no-deps
```

集成测试位于 [`tests/`](tests/)，独立单元测试统一集中在 `src/tests/`，仍由原业务模块挂载并保留私有访问；内联测试可保留。 无外部服务依赖的库验证可在宿主机运行并记录平台；数据库或运行中应用验证使用固定 `onlyalpha-dev` 环境。

一级目录仅允许 `src/`、`tests/`、`examples/`、`benches/`，按需创建。编译资源归入 `src/`，专用测试数据随测试组织，共享参考数据使用根目录 `test-data/`。
