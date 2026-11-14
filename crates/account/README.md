# onlyalpha-account：账户资金

## 目的与职责

维护作用域内现金、冻结、未结算资金及保证金投影，计算可用、可取资金和账户绩效。

本库是 `crates/` 下的 Rust 库，供其他库、后端或插件通过 Rust 公开接口复用。
职责依据[仓库架构](../../docs/repository-product-architecture.md)和各语义所属契约；此说明不新增 Authority，也不替代正式契约。

## 边界与依赖

不接入银行或券商，不拥有外部余额事实；不负责订单、持仓或产品准入。

直接依赖的仓内库：[`onlyalpha-position`](../position/README.md)、[`onlyalpha-margin`](../margin/README.md)、[`onlyalpha-domain`](../domain/README.md)。
完整依赖、特性及编译配置见 [Cargo.toml](Cargo.toml)。调用方只能通过公开接口集成，不直接访问私有模块或修改所属状态。

## 公开接口

[`Manager::apply_position_trade`](src/manager.rs) 对显式永续 TRADE 核对 Position 已应用原成交的范围、交易关联、金额和账户持仓结果，随后将其完整成交证据身份写入账户原指令。资金费在同一账户、配置和完整原交易前缀上复核。`restore_with_funding` 依原先后顺序验证 TRADE 与 Funding，保留随后成交和原输入重复的结果。

新 Funding 的公开应用核对 Position effect 的完整当前成交 lineage 与本账户已有 position_trades。相同配置的空前缀或过期 Position 不能为已持仓账户签发流水。恢复旧 Funding 使用本账户重放到该处的成交前缀，从原 Position Journal 重新签发 effect；后续成交不会使过去正确的 Funding 失效。已保留的同一规范命令先按原幂等关系处理，不按未来仓位重算旧流水。

新永续路径拒绝公开 apply 中未经证明的 ECONOMIC/FUNDING。apply_funding 消费 Position 的不透明 FundingEffect 并复核所属配置；restore_with_funding 要求真实 Position 与冻结 MarketSourceCut，从原引用重新推导金额。没有该上下文的独立新格式恢复拒绝，现金旧 Reader 保持原行为。

配置 3 的 Margin 效果绑定显式 LINEAR_LONG_NETTING_CROSS_OPEN profile；Account 从原 Margin 历史重推完整效果及投影，不接受调用方给出的 CROSS 汇总额。entry_maintenance 是 Margin 的入场证明，与 Account 当前 Mark 维护额分开；账户现金、权益和可用资金仍由原投影计算。恢复必须保持该配置、历史及关联，旧现金 Margin schema1 Reader 保持。

配置 schema 3 的 LINEAR_PERPETUAL 消费成交费用、Position 的有符号未实现盈亏、Margin 证明及 ECONOMIC/FUNDING。snapshot 给出抵押权益、可用保证金和维护额与正权益之比。资金费可产生负净值并阻止新风险。

Manager::new / apply 接收配置与规范输入，返回资金处理 Outcome；state / snapshot 输出可重放记录。Performance 与 equity_drawdown 提供权益及回撤计算。

公开入口以 [`src/lib.rs`](src/lib.rs) 为准；以下为当前公开模块和重导出，详细签名、方法和前置条件以源码及 `cargo doc` 为准。Rust 库接口不等同于面向 Web / Agent 的版本化控制 API。

```rust
pub use manager::Manager;
pub use model::{Error, Outcome, Status, digest};
pub use performance::{Performance, equity_drawdown};
```

## 状态与生命周期

Manager 持有内存投影；恢复输入与检查点约束由所属实现校验，持久化及多组件原子提交由 Execution / Runtime 协调。

## 使用与验证

在调用方 `Cargo.toml` 声明本库路径依赖，从上述入口选择类型或端口；配置、输入记录与身份必须按对应正式契约构建。

当前没有独立 Cargo 示例目标；可从公开入口和所属测试查看调用方式。

在仓库根目录执行：

```sh
cargo test -p onlyalpha-account
cargo doc -p onlyalpha-account --no-deps
```

集成测试位于 [`tests/`](tests/)，独立单元测试统一集中在 `src/tests/`，仍由原业务模块挂载并保留私有访问；内联测试可保留。 无外部服务依赖的库验证可在宿主机运行并记录平台；数据库或运行中应用验证使用固定 `onlyalpha-dev` 环境。

一级目录仅允许 `src/`、`tests/`、`examples/`、`benches/`，按需创建。编译资源归入 `src/`，专用测试数据随测试组织，共享参考数据使用根目录 `test-data/`。

永续配置 3 使用 new_checkpoint5。账户按 Margin 的真实生产记录投影 maintenance_status；缺少新的维护额时，maintenance_required 和 maintenance_to_equity 为空，last_confirmed_maintenance 保存最近整笔已确认事务的金额、时间及来源。原有成交和 Funding 可继续更新现金、占用和权益。

性能基准入口与口径见 [BENCHMARK.md](BENCHMARK.md)。
