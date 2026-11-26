# onlyalpha-runtime：有限内存执行会话与持续交易持久端口

## 目的与职责

在交易内核之外提供可复用的有限作业内存 Execution 会话（`Session`）与持续交易持久事实／恢复端口（`durability`）。业务不使用 SQLite 或文件型 Source；有限作业过程状态常驻内存、终态由后端 PostgreSQL 原子发布，持续交易事实由后端 PostgreSQL 适配 `DurableFactPort`。

本库是 `crates/` 下的 Rust 库，供其他库、后端或插件通过 Rust 公开接口复用。
职责依据[仓库架构](../../docs/repository-product-architecture.md)和各语义所属契约；此说明不新增 Authority，也不替代正式契约。

## 边界与依赖

不拥有后端 PostgreSQL 产品存储、任务准入、Runtime Generation 选择或 LIVE 权限；不是独立产品运行入口。

直接依赖的仓内库：[`onlyalpha-execution`](../execution/README.md)、[`onlyalpha-broker`](../broker/README.md)、[`onlyalpha-observability`](../observability/README.md)。

观测仅接入内存会话及诊断边界（`memory.admission`、`memory.apply`），记录原操作耗时与已有输入计数；不改变事实、恢复结果或状态摘要。公开调用方自行管理诊断 Session，库不读取环境或安装全局订阅器。
完整依赖、特性及编译配置见 [Cargo.toml](Cargo.toml)。调用方只能通过公开接口集成，不直接访问私有模块或修改所属状态。

## 公开接口

[`RunConfiguration`、`RunBinding`、`TradingInput`、`Session`、`AppliedEvent`、`CompletedSession`](src/session.rs)提供有限作业的内存边界。配置使用真实 Components 校验，绑定只含 Kernel 执行所需的内容身份，不授予数据权限或外部派发资格。`Session::apply` 持有当前 typed owner，按输入身份核对重复和冲突；事件须按序 `acknowledge`，未 drain、失败、未满足经济结束条件均不能 `finish`。普通资金／风控拒绝保留未变化的经济状态；其他异常使会话失效。

只保存紧凑输入、事件和幂等索引，限制单输入 64 KiB、事实总编码 128 MiB、最多一百万条事实；该上限不包含分配器开销，RSS 须另测。结束时一次性生成 Account／Ledger 时间线、对账和完整经济结果；不把每步的完整 checkpoint 保存为历史。`CompletedSession` 只证明本会话结束，行情耗尽由 Backtest 证明，Backend 另加作业与发布条件。内存丢失后不能宣称可断点续算，由后端在新 Attempt 上按原冻结输入重算。

`memory.admission` 和 `memory.apply` 复用 observability 的显式订阅器；诊断字段不进入业务身份、检查点或结果。

[`durability`](src/durability.rs) 提供持续交易的 `DurableFactPort`。`TradingBinding` 从校验过的 SIM／LIVE 配置、内核工件绑定流身份和版本。`RecoveryFacts::from_records` 需要同一快照内的绑定、水位和原事务，按序验证每条原输入、计划及经济投影，重建六个执行组件并对账。绑定冲突、缺行、投影前驱未就绪或经济内容不符时拒绝恢复。仅末条可处于已提交待投影状态；此时可读取恢复后的投影和原记录，必须由仓储确认原事务 Ready，重新读取后才能继续准备。`prepare` 生成的 `PreparedTradingFacts` 绑定原前驱、计划和事件；PG 适配器应在同一事务核对前驱并提交。`DurableCommitReceipt` 核对绑定与完整提交计划，只提供提交观察。数据库暂不可读和提交结果未知分别返回 `Unavailable`、`UnknownCommit`，由驱动继续核对原交易。

场所重复投递时，先用 `RecoveryFacts::observe_input` 按 `input_id` 查询当前已验证水位内的全部原记录，包括已提交待投影的末条事务。输入正文完全一致时返回原 `Record`，保留其 Ready 状态。同一身份对应不同正文时返回 `TRADING_INPUT_CONFLICT`，非法或缺失的身份返回内核校验错误。只有该身份在此快照中确实不存在时才返回 `None`，随后可按正常序列规则调用 `prepare`。

技术组合与持久化边界见[持久化契约](../../docs/rust-runtime-persistence.md)。旧 SQLite 存储、文件 journal、codec 及只读快照入口已随 ADR 0151 退役。

公开入口以 [`src/lib.rs`](src/lib.rs) 为准；以下为当前公开模块和重导出，详细签名、方法和前置条件以源码及 `cargo doc` 为准。Rust 库接口不等同于面向 Web / Agent 的版本化控制 API。

```rust
pub mod durability;
pub use session::{
    AppliedEvent, CompletedSession, RunBinding, RunConfiguration, Session, TradingInput,
};
```

## 状态与生命周期

- **有限作业会话（`Session`）**：纯内存运行，不写文件或 SQLite。事件须按序 `acknowledge`，任意异常使会话进入失效状态并拒绝继续推进。
- **持续交易持久端口（`durability`）**：由后端 PostgreSQL 适配实现，维护原绑定、前驱与 committed-unready 投影边界；恢复失败或数据库不可用时拒绝新增风险，保留观察和恢复能力。

## 使用与验证

在调用方 `Cargo.toml` 声明本库路径依赖，从上述入口选择类型或端口；配置、输入记录与身份必须按对应正式契约构建。

当前没有独立 Cargo 示例目标；可从公开入口和所属测试查看调用方式。

在仓库根目录执行：

```sh
cargo test -p onlyalpha-runtime
cargo doc -p onlyalpha-runtime --no-deps
```

集成测试位于 [`tests/`](tests/)，独立单元测试统一集中在 `src/tests/`，仍由原业务模块挂载并保留私有访问；内联测试可保留。无外部服务依赖的库验证可在宿主机运行并记录平台；数据库或运行中应用验证使用固定 `onlyalpha-dev` 环境。

一级目录仅允许 `src/`、`tests/`、`examples/`、`benches/`，按需创建。编译资源归入 `src/`，专用测试数据随测试组织，共享参考数据使用根目录 `test-data/`。

性能基准入口与口径见 [BENCHMARK.md](BENCHMARK.md)。
