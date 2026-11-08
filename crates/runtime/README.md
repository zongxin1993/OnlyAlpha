# onlyalpha-runtime：执行持久化与恢复

## 目的与职责

在交易内核之外提供可复用的 Execution 会话、SQLite 存储、检查点、回放记录及精确只读快照。

本库是 `crates/` 下的 Rust 库，供其他库、后端或插件通过 Rust 公开接口复用。
职责依据[仓库架构](../../docs/repository-product-architecture.md)和各语义所属契约；此说明不新增 Authority，也不替代正式契约。

## 边界与依赖

不拥有后端 PostgreSQL 产品存储、任务准入、Runtime Generation 选择或 LIVE 权限；不是独立产品运行入口。

直接依赖的仓内库：[`onlyalpha-execution`](../execution/README.md)、[`onlyalpha-broker`](../broker/README.md)。
完整依赖、特性及编译配置见 [Cargo.toml](Cargo.toml)。调用方只能通过公开接口集成，不直接访问私有模块或修改所属状态。

## 公开接口

[`BoundBrokerJournal`](src/broker_source_store.rs) 读取配置 3 原 Run 的 broker.sqlite3，按序读取来源步和该步的原事实子行。Broker 协议沿用原 record 和 32 MiB 总观察预算，来源步、逐事实原文和准入时刻分别保存。Runtime 以原 market-source-cut.json、原来源/协议库和 runtime.sqlite3 重建并核对每个 Prepared，具体撮合在绑定场所宿主重放。新代际使用 BoundBrokerJournal::dispatch，并在同目录真实 Runtime 的 Ready 前缀上取得原命令资格。

新 Broker RuntimeReader 的派发资格和订单读回都读取本 Run 原 Ready ADMIT 的范围和规范请求。SUBMIT 要求请求完全一致；CANCEL 查询要求正确的本地订单及 client，并返回原 SUBMIT 请求对应的 OrderView。返回 scope 来自原 Run，不回显未证明的来件。order_view 只读不授予取消派发资格，ready_intent 的操作限制保持。

Runtime::open 和 SqliteStore 的只读证据检查对显式永续配置逐笔重推原始完整输入。工件、配置或任意中间投影不符时拒绝恢复。技术组合的边界见[持久化契约](../../docs/rust-runtime-persistence.md)。

Runtime::create / open 接收路径、配置和工件身份；apply / apply_prepared 提交输入，save_checkpoint / recover 保存和恢复。SqliteStore 实现 Execution 存储端口；ReplayEntryRef / ReplayCompletion 标识回放；VerifiedReplaySnapshot::read / read_step / verify_cut 提供精确只读查询。

公开入口以 [`src/lib.rs`](src/lib.rs) 为准；以下为当前公开模块和重导出，详细签名、方法和前置条件以源码及 `cargo doc` 为准。Rust 库接口不等同于面向 Web / Agent 的版本化控制 API。

```rust
pub use references::{ReplayCompletion, ReplayEntryRef};
pub use readonly::VerifiedReplaySnapshot;
pub use store::{RunFundingPlan, RunPlan, SqliteStore};
pub use transcript::RunBacktestResult;
```

库根直接声明：`Runtime`。

## 状态与生命周期


持久事实和绑定在 SQLite 及所属文件中保存；恢复失败保留不健康状态并拒绝新增执行。待交付事件通过 pending_events / acknowledge 管理，格式迁移由 SqliteStore::migrate 显式执行，不在文档整理时改变旧事实。

## 使用与验证

在调用方 `Cargo.toml` 声明本库路径依赖，从上述入口选择类型或端口；配置、输入记录与身份必须按对应正式契约构建。

当前没有独立 Cargo 示例目标；可从公开入口和所属测试查看调用方式。

在仓库根目录执行：

```sh
cargo test -p onlyalpha-runtime
cargo doc -p onlyalpha-runtime --no-deps
```

集成测试位于 [`tests/`](tests/)，独立单元测试统一集中在 `src/tests/`，仍由原业务模块挂载并保留私有访问；内联测试可保留。 无外部服务依赖的库验证可在宿主机运行并记录平台；数据库或运行中应用验证使用固定 `onlyalpha-dev` 环境。

一级目录仅允许 `src/`、`tests/`、`examples/`、`benches/`，按需创建。编译资源归入 `src/`，专用测试数据随测试组织，共享参考数据使用根目录 `test-data/`。

配置 3 的 Funding 及其后的所有新输入都通过 [RunPlan](src/store.rs) 提交。`Runtime::apply` 直接处理原输入。分步调用时，先用 `prepare_run_plan` 从当前 Run 的原件准备，再用同一持锁会话的 `apply_run_plan` 提交。专用入口 `prepare_original_funding` 和 `apply_original_funding` 额外检查操作为 Funding。重开会话后按原输入重新准备。前缀含 Funding 时，`apply_prepared` 对普通输入只能确认已经存在且完整匹配的 Ready 原行。

`Runtime::backtest_result` 和 `VerifiedReplaySnapshot::backtest_result` 核验原 SQL 与六组投影后返回 [RunBacktestResult](src/transcript.rs)。`record()` 和 `encode()` 提供已有 BACKTEST_RESULT@1 记录和规范字节。
