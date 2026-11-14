# onlyalpha-position：持仓状态

## 目的与职责

维护规范持仓、可用数量、预留、估值和对账投影，处理显式成交及持仓相关输入。

本库是 `crates/` 下的 Rust 库，供其他库、后端或插件通过 Rust 公开接口复用。
职责依据[仓库架构](../../docs/repository-product-architecture.md)和各语义所属契约；此说明不新增 Authority，也不替代正式契约。

## 边界与依赖

不访问券商、不授予交易权限，不替代账户资金或策略账本；外部持仓观察与内部投影分清归属。

直接依赖的仓内库：[`onlyalpha-domain`](../domain/README.md)。
完整依赖、特性及编译配置见 [Cargo.toml](Cargo.toml)。调用方只能通过公开接口集成，不直接访问私有模块或修改所属状态。

## 公开接口

[`TradeEvidence`](src/trade_evidence.rs) 由 `Manager::trade_evidence` 从首次已应用的原 TRADE 重放取得。其身份绑定原 Broker 成交摘要、经济时间、价格、数量、费用、相关订单和配置，另带该成交的实际投影结果供 Account 和 Ledger 核对。`trade_input_digest` 生成原命令身份。恢复发现经济字段变化而身份未随之变化时返回 `POSITION_TRADE_EVIDENCE_CONFLICT`。

FundingEffect 除配置和来源外，还携带由 Position 原指令重放得到的紧凑成交 lineage，供 Account 与 Ledger 从各自真实交易记录独立核对；effect 及 Funding 命令不复制整套交易历史。`funding_at_trade_prefix(cut, reference, trades)` 供这两个真实恢复消费者重推旧 Funding：输入是接收方重放到该条时已有的成交 ID，只允许本 Position 原 Journal 的完整连续成交前缀，未知、缺失或非前缀报 `POSITION_FUNDING_TRADE_PREFIX`。它不接收金额或调用方摘要；金额仍按该前缀中经济时间不晚于边界的成交推导。

[`Manager::funding`](src/funding.rs) 是线性永续 FundingEffect 的唯一生产者。它读取冻结 MarketSourceCut 的原 Mark/Funding，核对账户、标的、来源、边界及 lineage，从本 Position 原始交易经济时间重建边界数量，按精确乘数与费率求金额后舍入。FundingEffect 没有公开金额构造器，Account 和 Ledger 消费同一 effect；处理时持仓不能替代边界持仓。

估值配置 schema 2 采用 MARK。value 依据原始开仓价成本、实际持仓、合约乘数推导未实现盈亏，作为线性永续持仓的权益贡献；同一检查点历史可重建 ValuationEffect。

Manager::new / apply 接收配置及规范输入并返回 Outcome；state 输出整体状态，account / cluster / reservation 查询对应投影，估值入口返回 ValuationEffect；预留与恢复能力通过 Manager 方法暴露。Status / Error 描述状态与失败。

公开入口以 [`src/lib.rs`](src/lib.rs) 为准；以下为当前公开模块和重导出，详细签名、方法和前置条件以源码及 `cargo doc` 为准。Rust 库接口不等同于面向 Web / Agent 的版本化控制 API。

```rust
pub use valuation::ValuationEffect;
pub use manager::Manager;
pub use model::{Error, Outcome, Status, digest};
```

## 状态与生命周期

Manager 持有内存状态并校验恢复引用；持久化、跨组件一致性和交易提交由 Execution / Runtime 负责。不可用或对账缺证不能推断持仓已匹配。

## 使用与验证

在调用方 `Cargo.toml` 声明本库路径依赖，从上述入口选择类型或端口；配置、输入记录与身份必须按对应正式契约构建。

现有示例：[`valuation`](examples/valuation.rs)；可在仓库根目录用 `cargo run -p onlyalpha-position --example <示例名>` 运行。

在仓库根目录执行：

```sh
cargo test -p onlyalpha-position
cargo doc -p onlyalpha-position --no-deps
```

集成测试位于 [`tests/`](tests/)，独立单元测试统一集中在 `src/tests/`，仍由原业务模块挂载并保留私有访问；内联测试可保留。 无外部服务依赖的库验证可在宿主机运行并记录平台；数据库或运行中应用验证使用固定 `onlyalpha-dev` 环境。

一级目录仅允许 `src/`、`tests/`、`examples/`、`benches/`，按需创建。编译资源归入 `src/`，专用测试数据随测试组织，共享参考数据使用根目录 `test-data/`。

永续估值意图的 MARK 带有来源价格的 precision。Position 按该精度校验标记价，独立使用合约乘数和持仓成本推导盈亏；成交价和现金模式 CLOSED_BAR 仍验证冻结的委托价格规格。

性能基准入口与口径见 [BENCHMARK.md](BENCHMARK.md)。
