# onlyalpha-event：事件与观察

## 目的与职责

提供不可变事件、规范记录转换和单线程事件总线，支持订阅、排队、派发及诊断。

本库是 `crates/` 下的 Rust 库，供其他库、后端或插件通过 Rust 公开接口复用。
职责依据[仓库架构](../../docs/repository-product-architecture.md)和各语义所属契约；此说明不新增 Authority，也不替代正式契约。

## 边界与依赖

事件总线不是交易执行或持久发布 Authority；持久化与正式生命周期发布通过明确端口交给调用方。

直接依赖的仓内库：[`onlyalpha-domain`](../domain/README.md)。
完整依赖、特性及编译配置见 [Cargo.toml](Cargo.toml)。调用方只能通过公开接口集成，不直接访问私有模块或修改所属状态。

## 公开接口

OnlyEvent::new / from_record / to_record 校验与表示事件；OnlyEventBus::publish / subscribe / dispatch_one / drain 处理观察队列。OnlyEventCallbackContext、订阅句柄和视图限制回调能力；OnlyDirectEventPublicationPort / OnlyDurableEventPublicationPort / OnlyLifecycleEventPublicationPort 定义发布边界。

公开入口以 [`src/lib.rs`](src/lib.rs) 为准；以下为当前公开模块和重导出，详细签名、方法和前置条件以源码及 `cargo doc` 为准。Rust 库接口不等同于面向 Web / Agent 的版本化控制 API。

```rust
pub use model::*;
pub use bus::*;
pub use capabilities::*;
pub use diagnostics::*;
pub use ports::*;
```

## 状态与生命周期

总线有容量、队列政策和 close 生命周期，派发报告与诊断保留失败。内存队列不替代持久日志，跨重启交付由拥有持久发布端口的组件保证。

## 使用与验证

在调用方 `Cargo.toml` 声明本库路径依赖，从上述入口选择类型或端口；配置、输入记录与身份必须按对应正式契约构建。

当前没有独立 Cargo 示例目标；可从公开入口和所属测试查看调用方式。

在仓库根目录执行：

```sh
cargo test -p onlyalpha-event
cargo doc -p onlyalpha-event --no-deps
```

集成测试位于 [`tests/`](tests/)，独立单元测试统一集中在 `src/tests/`，仍由原业务模块挂载并保留私有访问；内联测试可保留。 无外部服务依赖的库验证可在宿主机运行并记录平台；数据库或运行中应用验证使用固定 `onlyalpha-dev` 环境。

一级目录仅允许 `src/`、`tests/`、`examples/`、`benches/`，按需创建。编译资源归入 `src/`，专用测试数据随测试组织，共享参考数据使用根目录 `test-data/`。
