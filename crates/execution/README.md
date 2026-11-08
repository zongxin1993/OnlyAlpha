# onlyalpha-execution：交易执行协调

## 目的与职责

组合各交易组件，生成确定性的执行计划，通过存储端口有序提交并从已提交记录恢复精确投影。

本库是 `crates/` 下的 Rust 库，供其他库、后端或插件通过 Rust 公开接口复用。
职责依据[仓库架构](../../docs/repository-product-architecture.md)和各语义所属契约；此说明不新增 Authority，也不替代正式契约。

## 边界与依赖

不实现具体存储驱动或券商规则，不授予正式 Runtime 激活；每类资金、仓位、风险等事实仍由其所属组件管理。

直接依赖的仓内库包括只提供规范事实身份解码的 [onlyalpha-broker](../broker/README.md)、[`onlyalpha-margin`](../margin/README.md)、[`onlyalpha-settlement`](../settlement/README.md)、[`onlyalpha-fee`](../fee/README.md)、[`onlyalpha-domain`](../domain/README.md)、[`onlyalpha-order`](../order/README.md)、[`onlyalpha-position`](../position/README.md)、[`onlyalpha-account`](../account/README.md)、[`onlyalpha-strategy-ledger`](../strategy-ledger/README.md)、[`onlyalpha-risk`](../risk/README.md)。
完整依赖、特性及编译配置见 [Cargo.toml](Cargo.toml)。调用方只能通过公开接口集成，不直接访问私有模块或修改所属状态。

## 公开接口

[`ProjectionData::evaluate_funding`](src/projection_data.rs) 按输入的市场切片、来源步和逐笔应用原文计算 FundingDraft，保留首次闭合的原步。草稿仅公开规范数据。通用 Store 的新提交、已有行恢复、投影安装和 Ready 查询在遇到该操作时要求原 Run 的具体写者。新 ADMIT 要晚于本 Run 已结算的经济边界。`FILL` 将完整 Broker 原文摘要、经济时间和金额决定字段交给 Position，两个经济投影核对同一笔已应用成交。

配置 3 还核对原编译正文的完整通用经济投影：产品/标的、LINEAR、账户模式、结算币、乘数、保证金曲线和完整 Funding schedule，不能保留原策略身份却替换经济参数。Funding 的当前成交 lineage 与经济边界数量分开证明；恢复在旧输入对应的真实连续交易前缀重新签发，不使用最终仓位替代旧前缀。

配置 3 绑定 compiled_policy_json、原 policy_fingerprint、完整 limit_rules 及 limit_rules_fingerprint。构造和每次 ADMIT 从原编译正文重推规则，验证实际请求与经济时点。prepare_perpetual 对普通永续输入读取冻结 MarketSourceCut 与原 Journal 恢复的 Broker。Funding 草稿另需全局闭合与全部边界前原成交的应用证据。

该配置只支持原编译正文声明的 UTC/24×7；compile.as_of 日期为 day_index=1，之后按 UTC 自然日递增。输入日期和序号须对应实际处理时刻，ADMIT 不早于编译时点，实际费用按原成交经济日选档。

入场保证金的累计名义直接读取 Position 的精确成本乘合约乘数，只有确切无仓位可取零，其他读取错误传播；Settlement 舍入后的货币名义不能反推该基数。冻结曲线首档在精确原点的初始及维护要求均须为零。配置 3 显式选择 Margin 的 LINEAR_LONG_NETTING_CROSS_OPEN profile，用累计入场要求证明分笔及跨订单履约。

BACKTEST 配置 schema 3 支持显式线性永续 LIMIT BUY OPEN。ADMIT 绑定原请求及策略，ACCEPT/FILL/TERMINAL 接收 Broker Fact 原记录、身份与指纹。MARK 和 FUNDING 接收 Domain 原始事实。配置与输入形态、未知结果、重复结算和边界检查见[执行契约](../../docs/execution.md#backtest-线性永续开仓)。

Components 接收配置和交易输入，Prepared 表示准备结果；Store、CommitIntent、Record 定义提交边界，coordinate / recover 协调提交与恢复，pending_events 提取待交付事件。LedgerReconciliation、RuntimePerformance、BacktestResult 提供所属组合查询结果。

在被动行上调用 `ProjectionData::transcript` 得到 [TranscriptDraft](src/backtest_result.rs)。它提供来源、统计、明细和诊断，可用 `record()` 取得副本或用 `into_record()` 取走数据。封存、结果指纹和最终身份由持有实际 Ready 来源的结果入口生成。

公开入口以 [`src/lib.rs`](src/lib.rs) 为准；以下为当前公开模块和重导出，详细签名、方法和前置条件以源码及 `cargo doc` 为准。Rust 库接口不等同于面向 Web / Agent 的版本化控制 API。

```rust
pub use components::Components;
pub use model::{Error, Prepared, digest};
pub use coordinator::{CommitIntent, Record, Store, coordinate, pending_events, recover};
pub use reconciliation::LedgerReconciliation;
pub use performance::RuntimePerformance;
pub use backtest_result::{BacktestResult, TranscriptDraft};
```

## 状态与生命周期

准备与提交按显式顺序处理；恢复以已提交记录为依据，不能猜测未知操作。Store 由外部实现，数据库事务和真实外部副作用不隐藏在纯计划内。

## 使用与验证

在调用方 `Cargo.toml` 声明本库路径依赖，从上述入口选择类型或端口；配置、输入记录与身份必须按对应正式契约构建。

当前没有独立 Cargo 示例目标；可从公开入口和所属测试查看调用方式。

在仓库根目录执行：

```sh
cargo test -p onlyalpha-execution
cargo doc -p onlyalpha-execution --no-deps
```

集成测试位于 [`tests/`](tests/)，独立单元测试统一集中在 `src/tests/`，仍由原业务模块挂载并保留私有访问；内联测试可保留。 无外部服务依赖的库验证可在宿主机运行并记录平台；数据库或运行中应用验证使用固定 `onlyalpha-dev` 环境。

一级目录仅允许 `src/`、`tests/`、`examples/`、`benches/`，按需创建。编译资源归入 `src/`，专用测试数据随测试组织，共享参考数据使用根目录 `test-data/`。

显式 BACKTEST 配置 3 的 margin_observation_capacity 默认 512，可冻结为 1 至 512 的整数。达到上界后拒绝新风险；已接纳委托的成交、终态及随后仍发生的标记价、资金费继续由各自所有者记账。账户维护额缺证可从 maintenance_status 以及 last_confirmed_maintenance 查询。
