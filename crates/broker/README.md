# onlyalpha-broker：券商协议

## 目的与职责

定义市场无关的券商命令、事实、能力端口及命令日志协议，协调发送、事实接收、确认和对账。

本库是 `crates/` 下的 Rust 库，供其他库、后端或插件通过 Rust 公开接口复用。
职责依据[仓库架构](../../docs/repository-product-architecture.md)和各语义所属契约；此说明不新增 Authority，也不替代正式契约。

## 边界与依赖

不实现具体券商协议，不直接更新交易经济投影；外部成交事实属于交易场所，内部应用交给 Runtime 端口。

直接依赖的仓内库：[`onlyalpha-domain`](../domain/README.md)。
完整依赖、特性及编译配置见 [Cargo.toml](Cargo.toml)。调用方只能通过公开接口集成，不直接访问私有模块或修改所属状态。

## 公开接口

BrokerCommand / Fact / Scope 解码规范记录；Broker::recover 从 Journal 重建协议状态，dispatch、ingest、acknowledge、reconcile、resolve 推进原命令。TradingPort、RuntimeReader、Journal 及查询端口由调用方实现。

公开入口以 [`src/lib.rs`](src/lib.rs) 为准；以下为当前公开模块和重导出，详细签名、方法和前置条件以源码及 `cargo doc` 为准。Rust 库接口不等同于面向 Web / Agent 的版本化控制 API。

```rust
pub use model::*;
pub use ports::*;
pub use protocol::*;
```

## 状态与生命周期

CommandState 表达命令状态；日志端口是可信持久化边界。未知提交结果保留原命令继续查询及对账，不能盲目重发；摘要仅证明完整性，不授予权限。

## 使用与验证

在调用方 `Cargo.toml` 声明本库路径依赖，从上述入口选择类型或端口；配置、输入记录与身份必须按对应正式契约构建。

现有示例：[`identity`](examples/identity.rs)、[`restart`](examples/restart.rs)；可在仓库根目录用 `cargo run -p onlyalpha-broker --example <示例名>` 运行。

在仓库根目录执行：

```sh
cargo test -p onlyalpha-broker
cargo doc -p onlyalpha-broker --no-deps
```

集成测试位于 [`tests/`](tests/)，独立单元测试统一集中在 `src/tests/`，仍由原业务模块挂载并保留私有访问；内联测试可保留。 无外部服务依赖的库验证可在宿主机运行并记录平台；数据库或运行中应用验证使用固定 `onlyalpha-dev` 环境。

一级目录仅允许 `src/`、`tests/`、`examples/`、`benches/`，按需创建。编译资源归入 `src/`，专用测试数据随测试组织，共享参考数据使用根目录 `test-data/`。
