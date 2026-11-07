# onlyalpha-risk：风险决策与预留

## 目的与职责

维护市场无关的风险决策、预留及对应状态，按显式配置和输入判定风险操作。

本库是 `crates/` 下的 Rust 库，供其他库、后端或插件通过 Rust 公开接口复用。
职责依据[仓库架构](../../docs/repository-product-architecture.md)和各语义所属契约；此说明不新增 Authority，也不替代正式契约。

## 边界与依赖

不定义具体市场政策、不发送订单、不拥有产品激活或 LIVE 授权；不能绕过订单、资金和持仓所属组件。

直接依赖的仓内库：[`onlyalpha-domain`](../domain/README.md)。
完整依赖、特性及编译配置见 [Cargo.toml](Cargo.toml)。调用方只能通过公开接口集成，不直接访问私有模块或修改所属状态。

## 公开接口

Manager::new / apply 接收配置与规范输入，返回带 Status 的 Outcome；state / snapshot 及预留相关方法提供可核对投影。Error / digest 用于失败与摘要，具体恢复方法由 Manager 暴露。

公开入口以 [`src/lib.rs`](src/lib.rs) 为准；以下为当前公开模块和重导出，详细签名、方法和前置条件以源码及 `cargo doc` 为准。Rust 库接口不等同于面向 Web / Agent 的版本化控制 API。

```rust
pub use manager::Manager;
pub use model::{Error, Outcome, Status, digest};
```

## 状态与生命周期

Manager 保存可恢复内存投影；错误或证据不足时不能视为通过风险检查。Execution / Runtime 负责记录及跨组件提交，恢复继续保留观察、撤销和降低风险的路径。

## 使用与验证

在调用方 `Cargo.toml` 声明本库路径依赖，从上述入口选择类型或端口；配置、输入记录与身份必须按对应正式契约构建。

当前没有独立 Cargo 示例目标；可从公开入口和所属测试查看调用方式。

在仓库根目录执行：

```sh
cargo test -p onlyalpha-risk
cargo doc -p onlyalpha-risk --no-deps
```

集成测试位于 [`tests/`](tests/)，独立单元测试统一集中在 `src/tests/`，仍由原业务模块挂载并保留私有访问；内联测试可保留。 无外部服务依赖的库验证可在宿主机运行并记录平台；数据库或运行中应用验证使用固定 `onlyalpha-dev` 环境。

一级目录仅允许 `src/`、`tests/`、`examples/`、`benches/`，按需创建。编译资源归入 `src/`，专用测试数据随测试组织，共享参考数据使用根目录 `test-data/`。
