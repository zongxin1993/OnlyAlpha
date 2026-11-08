# onlyalpha-domain：规范领域值

## 目的与职责

提供金融数值、身份、时间、行情、标的、日历、账户及执行相关的规范值与记录表示，是其他库共用的基础语义。

本库是 `crates/` 下的 Rust 库，供其他库、后端或插件通过 Rust 公开接口复用。
职责依据[仓库架构](../../docs/repository-product-architecture.md)和各语义所属契约；此说明不新增 Authority，也不替代正式契约。

## 边界与依赖

不依赖 Runtime、数据库、网络或具体服务商，不拥有运行权限或外部交易事实。市场规则在这里表达通用值，具体政策由插件提供。

没有直接依赖的仓内库。
完整依赖、特性及编译配置见 [Cargo.toml](Cargo.toml)。调用方只能通过公开接口集成，不直接访问私有模块或修改所属状态。

## 公开接口

`OnlyStaticLimitRules::compiled_economics` 从经过原正文指纹校验的市场编译结果提取通用经济投影；`normalize_economics` 对实际配置的相同字段规范化比较。投影覆盖标的、产品身份、合约类型、账户模式、结算币、乘数、完整保证金曲线和 Funding schedule，保留原 schedule 语义版本；不识别具体供应商。

[`market_rules::OnlyStaticLimitRules`](src/market_rules.rs) 从市场编译生产者的原正文及原策略指纹推导完整静态约束，保留公共与账户覆盖交集、编译时点和完整内容身份，针对实际价格、数量与经济时点验证。[`market_source::OnlyMarketSourceCut`](src/market_source.rs) 读取运行配置绑定摘要的冻结原始切片，校验有界原文、规范事实和唯一身份；单条 DTO 不授予来源资格。

numeric / value / base 提供精确数值和金融值；identifiers / enums / errors 定义身份与错误；time / ranges / calendar 处理时间和区间；instrument / catalog / venue / market 表达标的及行情；account / trading / market_rules / fee / execution 提供对应领域记录。公开路径见下方导出清单。

公开入口以 [`src/lib.rs`](src/lib.rs) 为准；以下为当前公开模块和重导出，详细签名、方法和前置条件以源码及 `cargo doc` 为准。Rust 库接口不等同于面向 Web / Agent 的版本化控制 API。

```rust
pub mod enums;
pub mod errors;
pub mod base;
pub mod identifiers;
pub mod numeric;
pub mod value;
pub mod trading;
pub mod ranges;
pub mod time;
pub mod account;
pub mod market_rules;
pub mod fee;
pub mod calendar;
pub mod venue;
pub mod instrument;
pub mod catalog;
pub mod market;
pub mod execution;
```

## 状态与生命周期

领域值通过构造和记录读取进行校验，无数据库或进程生命周期。src/resources/tzdata/2026.3 内嵌固定 TZif 字节、许可和 dataset.json，时区解释不依赖宿主机数据；版本升级与身份变化按正式契约处理。

## 使用与验证

在调用方 `Cargo.toml` 声明本库路径依赖，从上述入口选择类型或端口；配置、输入记录与身份必须按对应正式契约构建。

当前没有独立 Cargo 示例目标；可从公开入口和所属测试查看调用方式。

在仓库根目录执行：

```sh
cargo test -p onlyalpha-domain
cargo doc -p onlyalpha-domain --no-deps
```

集成测试位于 [`tests/`](tests/)，独立单元测试统一集中在 `src/tests/`，仍由原业务模块挂载并保留私有访问；内联测试可保留。 无外部服务依赖的库验证可在宿主机运行并记录平台；数据库或运行中应用验证使用固定 `onlyalpha-dev` 环境。

一级目录仅允许 `src/`、`tests/`、`examples/`、`benches/`，按需创建。编译资源归入 `src/`，专用测试数据随测试组织，共享参考数据使用根目录 `test-data/`。
