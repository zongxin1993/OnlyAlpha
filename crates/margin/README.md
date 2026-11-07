# onlyalpha-margin：保证金与抵押状态

## 目的与职责

按显式指令维护市场无关的保证金和抵押状态，生成关联组件可以应用的 Effect。

本库是 `crates/` 下的 Rust 库，供其他库、后端或插件通过 Rust 公开接口复用。
职责依据[仓库架构](../../docs/repository-product-architecture.md)和各语义所属契约；此说明不新增 Authority，也不替代正式契约。

## 边界与依赖

不内置市场费率、券商政策或外部副作用；不负责真实账户资金操作或 Runtime 准入。

直接依赖的仓内库：[`onlyalpha-domain`](../domain/README.md)。
完整依赖、特性及编译配置见 [Cargo.toml](Cargo.toml)。调用方只能通过公开接口集成，不直接访问私有模块或修改所属状态。

## 公开接口

Manager::new 接收配置和容量；apply 接收规范指令并返回 Effect，Effect::replay_input / record 暴露重放与结果记录。snapshot / snapshots 查询状态，release_quote 计算指定数量的释放结果。

公开入口以 [`src/lib.rs`](src/lib.rs) 为准；以下为当前公开模块和重导出，详细签名、方法和前置条件以源码及 `cargo doc` 为准。Rust 库接口不等同于面向 Web / Agent 的版本化控制 API。

```rust
pub use manager::{Effect, Manager};
pub use model::{Error, digest};
```

## 状态与生命周期

Manager 保存内存状态，checkpoint / restore 通过期望摘要核对候选恢复。调用方持久化并协调跨组件提交，拒绝无效指令或错误关联。

## 使用与验证

在调用方 `Cargo.toml` 声明本库路径依赖，从上述入口选择类型或端口；配置、输入记录与身份必须按对应正式契约构建。

现有示例：[`margin_reference`](examples/margin_reference.rs)；可在仓库根目录用 `cargo run -p onlyalpha-margin --example <示例名>` 运行。

在仓库根目录执行：

```sh
cargo test -p onlyalpha-margin
cargo doc -p onlyalpha-margin --no-deps
```

集成测试位于 [`tests/`](tests/)，独立单元测试统一集中在 `src/tests/`，仍由原业务模块挂载并保留私有访问；内联测试可保留。 无外部服务依赖的库验证可在宿主机运行并记录平台；数据库或运行中应用验证使用固定 `onlyalpha-dev` 环境。

一级目录仅允许 `src/`、`tests/`、`examples/`、`benches/`，按需创建。编译资源归入 `src/`，专用测试数据随测试组织，共享参考数据使用根目录 `test-data/`。
