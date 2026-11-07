# onlyalpha-strategy：策略执行契约

## 目的与职责

定义策略修订、作用域、程序和节点端口，按行情驱动计算节点并输出策略决策及检查点。

本库是 `crates/` 下的 Rust 库，供其他库、后端或插件通过 Rust 公开接口复用。
职责依据[仓库架构](../../docs/repository-product-architecture.md)和各语义所属契约；此说明不新增 Authority，也不替代正式契约。

## 边界与依赖

不发送真实买卖、不拥有账户仓位更新或产品准入；SourceRevision 一致不等于冻结发布或正式 Runtime 准入。

直接依赖的仓内库：[`onlyalpha-domain`](../domain/README.md)、[`onlyalpha-calculation`](../calculation/README.md)、[`onlyalpha-market-data-construction`](../market-data-construction/README.md)。
完整依赖、特性及编译配置见 [Cargo.toml](Cargo.toml)。调用方只能通过公开接口集成，不直接访问私有模块或修改所属状态。

## 公开接口

Revision / Scope / Program 绑定图、策略和执行上下文；NodePort / NodeRequest 定义节点执行边界。Executor::new / process 接收程序与行情并返回 Outcome；capture_checkpoint / restored_candidate / restore_checkpoint 处理恢复；SourceRevision::from_json 读取公开源记录和身份。

公开入口以 [`src/lib.rs`](src/lib.rs) 为准；以下为当前公开模块和重导出，详细签名、方法和前置条件以源码及 `cargo doc` 为准。Rust 库接口不等同于面向 Web / Agent 的版本化控制 API。

```rust
pub use execution::Executor;
pub use model::*;
pub use source::{SourceError, SourceRevision};
```

## 状态与生命周期

Executor 保留每个标的的结果和失败状态，恢复先核对候选及绑定；调用方持久化并负责正式准入。相同策略版本在回测、模拟与实盘中的决策含义保持一致。

## 使用与验证

在调用方 `Cargo.toml` 声明本库路径依赖，从上述入口选择类型或端口；配置、输入记录与身份必须按对应正式契约构建。

当前没有独立 Cargo 示例目标；可从公开入口和所属测试查看调用方式。

在仓库根目录执行：

```sh
cargo test -p onlyalpha-strategy
cargo doc -p onlyalpha-strategy --no-deps
```

集成测试位于 [`tests/`](tests/)，独立单元测试统一集中在 `src/tests/`，仍由原业务模块挂载并保留私有访问；内联测试可保留。 无外部服务依赖的库验证可在宿主机运行并记录平台；数据库或运行中应用验证使用固定 `onlyalpha-dev` 环境。

一级目录仅允许 `src/`、`tests/`、`examples/`、`benches/`，按需创建。编译资源归入 `src/`，专用测试数据随测试组织，共享参考数据使用根目录 `test-data/`。
