# onlyalpha-strategy-ledger：策略虚拟账本

## 目的与职责

维护 Runtime 作用域内的策略虚拟资金与持仓账本、记账和估值投影，为归因和策略视图提供记录。

本库是 `crates/` 下的 Rust 库，供其他库、后端或插件通过 Rust 公开接口复用。
职责依据[仓库架构](../../docs/repository-product-architecture.md)和各语义所属契约；此说明不新增 Authority，也不替代正式契约。

## 边界与依赖

不替代真实账户或交易场所事实，不做外部 I/O，不授予 Runtime 准入；不拥有其他组件的私有状态。

直接依赖的仓内库：[`onlyalpha-domain`](../domain/README.md)、[`onlyalpha-position`](../position/README.md)。
完整依赖、特性及编译配置见 [Cargo.toml](Cargo.toml)。调用方只能通过公开接口集成，不直接访问私有模块或修改所属状态。

## 公开接口

[`Manager::apply_position_trade`](src/manager.rs) 核对实际 Position 原成交的策略簇、标的、交易序号、金额及真实分配结果，把完整成交证据身份写入 Ledger 原 TRADE。Funding 在此有序原前缀复核，恢复时即使已有后续成交，也以该笔 Funding 入账时的前缀重建。

Funding effect 的紧凑 lineage 必须与本 Ledger 已记账的 TRADE、cluster、order、execution、原处理序列和 allocation_evidence 独立重推一致；配置相同不等于成交前缀相同。恢复在旧 Funding 处用当时已重放的交易 ID 选择 Position 原 Journal 的连续前缀，不把最终完整仓位误用作旧时点证明。原规范 Funding 重复仍走已保留命令的幂等路径。

BACKTEST 配置 schema 2 支持线性永续开仓。apply_funding 消费 Position 的不透明 FundingEffect，按策略归属记录内部损益与现金，外部资金流保持不变。公开 apply 拒绝 raw FUNDING；restore_with_funding 必须从真实 Position 和冻结 MarketSourceCut 重推原引用与金额。缺来源或重算摘要后的篡改金额仍拒绝，旧现金 Reader 保持原行为。

Manager::new / apply 接收配置和规范记账输入并返回 Outcome；state / snapshot 查询账本，估值和恢复入口通过 Manager 暴露。Status / Error 表达处理状态与失败，digest 提供记录摘要。

公开入口以 [`src/lib.rs`](src/lib.rs) 为准；以下为当前公开模块和重导出，详细签名、方法和前置条件以源码及 `cargo doc` 为准。Rust 库接口不等同于面向 Web / Agent 的版本化控制 API。

```rust
pub use manager::Manager;
pub use model::{Error, Outcome, Status, digest};
```

## 状态与生命周期

账本由内存状态和经过校验的恢复记录构成；Execution / Runtime 协调持久化和账户、持仓的关联提交。策略归属与执行身份必须保留，不能以汇总值代替原始引用。

## 使用与验证

在调用方 `Cargo.toml` 声明本库路径依赖，从上述入口选择类型或端口；配置、输入记录与身份必须按对应正式契约构建。

当前没有独立 Cargo 示例目标；可从公开入口和所属测试查看调用方式。

在仓库根目录执行：

```sh
cargo test -p onlyalpha-strategy-ledger
cargo doc -p onlyalpha-strategy-ledger --no-deps
```

集成测试位于 [`tests/`](tests/)，独立单元测试统一集中在 `src/tests/`，仍由原业务模块挂载并保留私有访问；内联测试可保留。 无外部服务依赖的库验证可在宿主机运行并记录平台；数据库或运行中应用验证使用固定 `onlyalpha-dev` 环境。

一级目录仅允许 `src/`、`tests/`、`examples/`、`benches/`，按需创建。编译资源归入 `src/`，专用测试数据随测试组织，共享参考数据使用根目录 `test-data/`。

性能基准入口与口径见 [BENCHMARK.md](BENCHMARK.md)。
