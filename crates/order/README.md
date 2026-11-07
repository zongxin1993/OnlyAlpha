# onlyalpha-order：订单状态

## 目的与职责

维护作用域内规范订单状态，校验输入、身份和状态迁移，提供应用结果及恢复能力。

本库是 `crates/` 下的 Rust 库，供其他库、后端或插件通过 Rust 公开接口复用。
职责依据[仓库架构](../../docs/repository-product-architecture.md)和各语义所属契约；此说明不新增 Authority，也不替代正式契约。

## 边界与依赖

不负责网络发送、执行权限或资金仓位投影；外部订单观察由 Broker 协议接入，经济影响由所属组件管理。

直接依赖的仓内库：[`onlyalpha-domain`](../domain/README.md)。
完整依赖、特性及编译配置见 [Cargo.toml](Cargo.toml)。调用方只能通过公开接口集成，不直接访问私有模块或修改所属状态。

## 公开接口

Manager::new 接收配置；apply 接收规范订单输入并返回 Outcome，ApplyResult 描述应用结果；get / snapshots / open / recent 查询订单投影，恢复方法见 Manager 实现。Error 与 digest 提供失败表示及规范摘要。

公开入口以 [`src/lib.rs`](src/lib.rs) 为准；以下为当前公开模块和重导出，详细签名、方法和前置条件以源码及 `cargo doc` 为准。Rust 库接口不等同于面向 Web / Agent 的版本化控制 API。

```rust
pub use manager::Manager;
pub use model::{ApplyResult, Error, Outcome, digest};
```

## 状态与生命周期

同一订单沿原身份处理重复输入、取消及未知结果；恢复依赖验证后的快照和记录，由 Execution / Runtime 持久化与协调，不重建第二份订单事实。

## 使用与验证

在调用方 `Cargo.toml` 声明本库路径依赖，从上述入口选择类型或端口；配置、输入记录与身份必须按对应正式契约构建。

当前没有独立 Cargo 示例目标；可从公开入口和所属测试查看调用方式。

在仓库根目录执行：

```sh
cargo test -p onlyalpha-order
cargo doc -p onlyalpha-order --no-deps
```

集成测试位于 [`tests/`](tests/)，独立单元测试统一集中在 `src/tests/`，仍由原业务模块挂载并保留私有访问；内联测试可保留。 无外部服务依赖的库验证可在宿主机运行并记录平台；数据库或运行中应用验证使用固定 `onlyalpha-dev` 环境。

一级目录仅允许 `src/`、`tests/`、`examples/`、`benches/`，按需创建。编译资源归入 `src/`，专用测试数据随测试组织，共享参考数据使用根目录 `test-data/`。
