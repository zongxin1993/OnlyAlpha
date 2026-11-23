# onlyalpha-clock：时钟与定时调度

## 目的与职责

提供显式时间驱动的调度器、虚拟时钟和原生实时钟，管理定时器、回调派发及失败记录。

本库是 `crates/` 下的 Rust 库，供其他库、后端或插件通过 Rust 公开接口复用。
职责依据[仓库架构](../../docs/repository-product-architecture.md)和各语义所属契约；此说明不新增 Authority，也不替代正式契约。

## 边界与依赖

不授予 Runtime 准入，也不决定交易事件是否已正式发生；原生时钟效应与确定性调度分开。

直接依赖的仓内库：[`onlyalpha-domain`](../domain/README.md)。
完整依赖、特性及编译配置见 [Cargo.toml](Cargo.toml)。调用方只能通过公开接口集成，不直接访问私有模块或修改所属状态。

## 公开接口

OnlyTimerScheduler 接收 BigInt 纳秒及调度请求，dispatch_next / complete_dispatch 推进派发；OnlyVirtualClock::advance_to / advance_by 驱动可重复回调。OnlyLiveClock 封装原生调度，ClockView / TimerHandle 提供受限查询与取消，ClockSnapshot / ClockError 描述快照和失败。

公开入口以 [`src/lib.rs`](src/lib.rs) 为准；以下为当前公开模块和重导出，详细签名、方法和前置条件以源码及 `cargo doc` 为准。Rust 库接口不等同于面向 Web / Agent 的版本化控制 API。

```rust
pub use model::*;
pub use native::{LiveClockControl, NativeCallback, OnlyLiveClock};
pub use num_bigint::{BigInt, BigUint};
pub use scheduler::{DispatchToken, OnlyTimerScheduler};
pub use view::{ClockView, TimerHandle};
pub use virtual_clock::{OnlyVirtualClock, VirtualCallback, VirtualClockContext};
```

## 状态与生命周期

显式 schedule / cancel / close 管理生命周期；虚拟时钟支持 snapshot / restore。回调失败保留诊断，不伪造成功；调用方保存需要重放的时间输入与快照。

## 使用与验证

在调用方 `Cargo.toml` 声明本库路径依赖，从上述入口选择类型或端口；配置、输入记录与身份必须按对应正式契约构建。

当前没有独立 Cargo 示例目标；可从公开入口和所属测试查看调用方式。

在仓库根目录执行：

```sh
cargo test -p onlyalpha-clock
cargo doc -p onlyalpha-clock --no-deps
```

集成测试位于 [`tests/`](tests/)，独立单元测试统一集中在 `src/tests/`，仍由原业务模块挂载并保留私有访问；内联测试可保留。 无外部服务依赖的库验证可在宿主机运行并记录平台；数据库或运行中应用验证使用固定 `onlyalpha-dev` 环境。

一级目录仅允许 `src/`、`tests/`、`examples/`、`benches/`，按需创建。编译资源归入 `src/`，专用测试数据随测试组织，共享参考数据使用根目录 `test-data/`。

性能基准入口与口径见 [BENCHMARK.md](BENCHMARK.md)。
