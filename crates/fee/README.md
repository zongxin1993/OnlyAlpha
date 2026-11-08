# onlyalpha-fee：费用语义

## 目的与职责

维护市场无关的费用目录绑定、估算、评估、应用与证据对账，保留费用决策和风险阻塞。

本库是 `crates/` 下的 Rust 库，供其他库、后端或插件通过 Rust 公开接口复用。
职责依据[仓库架构](../../docs/repository-product-architecture.md)和各语义所属契约；此说明不新增 Authority，也不替代正式契约。

## 边界与依赖

费率与具体市场收费规则由外部政策提供；不实现存储驱动或产品准入，不把估计值当作外部成交收费事实。

直接依赖的仓内库：[`onlyalpha-domain`](../domain/README.md)。
完整依赖、特性及编译配置见 [Cargo.toml](Cargo.toml)。调用方只能通过公开接口集成，不直接访问私有模块或修改所属状态。

## 公开接口

显式永续 GTC 费用上界覆盖冻结 FILL_EFFECTIVE 合同中可达的未来生效档和 MAKER/TAKER 角色；未来覆盖有缺口时拒绝新准入。实际费用仍按原成交经济日选档，迟到投递不改费日。

Catalog::selected_schedules(binding, day) 返回订单绑定在该交易日实际解析到的费表副本。Execution 需要表的版本或适用范围构造 Domain 的 order-fixed 与 fill-effective 身份；assess 和 estimate 仅提供计算输出。查阅该副本不产生费用流水，实际成交仍由同一 Catalog::assess 与 Manager::apply 处理。

Catalog::new / bind / estimate / assess / quote_one_fill 从目录和主题生成 Binding、Assessment 或 FeeQuote；Manager::apply 返回 Application，query / reconcile 查询与核对证据，permits 判断指定风险变化是否获准。

公开入口以 [`src/lib.rs`](src/lib.rs) 为准；以下为当前公开模块和重导出，详细签名、方法和前置条件以源码及 `cargo doc` 为准。Rust 库接口不等同于面向 Web / Agent 的版本化控制 API。

```rust
pub use manager::{Application, Manager};
pub use model::{Error, digest};
pub use policy::{Assessment, Binding, Catalog, FeeQuote};
```

## 状态与生命周期

Manager 保存内存费用决策、调整与 blockers，通过 checkpoint / restore 校验恢复。调用方负责保存记录和应用关联投影，失败不得被当作费用匹配。

## 使用与验证

在调用方 `Cargo.toml` 声明本库路径依赖，从上述入口选择类型或端口；配置、输入记录与身份必须按对应正式契约构建。

现有示例：[`reference`](examples/reference.rs)；可在仓库根目录用 `cargo run -p onlyalpha-fee --example <示例名>` 运行。

在仓库根目录执行：

```sh
cargo test -p onlyalpha-fee
cargo doc -p onlyalpha-fee --no-deps
```

集成测试位于 [`tests/`](tests/)，独立单元测试统一集中在 `src/tests/`，仍由原业务模块挂载并保留私有访问；内联测试可保留。 无外部服务依赖的库验证可在宿主机运行并记录平台；数据库或运行中应用验证使用固定 `onlyalpha-dev` 环境。

一级目录仅允许 `src/`、`tests/`、`examples/`、`benches/`，按需创建。编译资源归入 `src/`，专用测试数据随测试组织，共享参考数据使用根目录 `test-data/`。
