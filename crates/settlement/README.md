# onlyalpha-settlement：现金证券结算

## 目的与职责

编译规范结算指令，管理结算注册、到期与成熟结果，提供确定性现金证券结算语义。

本库是 `crates/` 下的 Rust 库，供其他库、后端或插件通过 Rust 公开接口复用。
职责依据[仓库架构](../../docs/repository-product-architecture.md)和各语义所属契约；此说明不新增 Authority，也不替代正式契约。

## 边界与依赖

市场政策、日历配置与产品准入由外部提供；不直接转移真实资金或证券，不实现数据库驱动。

直接依赖的仓内库：[`onlyalpha-domain`](../domain/README.md)。
完整依赖、特性及编译配置见 [Cargo.toml](Cargo.toml)。调用方只能通过公开接口集成，不直接访问私有模块或修改所属状态。

## 公开接口

compile 的指令输入 schema 2 选择 BACKTEST 线性永续即时开仓。指令保存原交易与名义，现金腿只包含成交费用及返佣。明确的策略版本和各项拒绝条件见[结算契约](../../docs/settlement_model.md#线性永续开仓的即时结算)。

compile 将规范记录校验为 Instruction；resolve_schedule 解析明确日程。Authority::admit_order / register 登记指令，due 查询指定时间前到期项，mature 返回 Maturity；snapshot / snapshots 查询状态。

公开入口以 [`src/lib.rs`](src/lib.rs) 为准；以下为当前公开模块和重导出，详细签名、方法和前置条件以源码及 `cargo doc` 为准。Rust 库接口不等同于面向 Web / Agent 的版本化控制 API。

```rust
pub use authority::Authority;
pub use model::{Error, Instruction, Maturity, compile, digest, resolve_schedule};
```

## 状态与生命周期

Authority 管理作用域内序列和结算投影，通过 checkpoint / restore 校验恢复。调用方负责持久化和跨组件应用，时间与政策作为明确输入，不能从宿主时钟隐式推进结算。

## 使用与验证

在调用方 `Cargo.toml` 声明本库路径依赖，从上述入口选择类型或端口；配置、输入记录与身份必须按对应正式契约构建。

现有示例：[`reference`](examples/reference.rs)；可在仓库根目录用 `cargo run -p onlyalpha-settlement --example <示例名>` 运行。

在仓库根目录执行：

```sh
cargo test -p onlyalpha-settlement
cargo doc -p onlyalpha-settlement --no-deps
```

集成测试位于 [`tests/`](tests/)，独立单元测试统一集中在 `src/tests/`，仍由原业务模块挂载并保留私有访问；内联测试可保留。 无外部服务依赖的库验证可在宿主机运行并记录平台；数据库或运行中应用验证使用固定 `onlyalpha-dev` 环境。

一级目录仅允许 `src/`、`tests/`、`examples/`、`benches/`，按需创建。编译资源归入 `src/`，专用测试数据随测试组织，共享参考数据使用根目录 `test-data/`。
