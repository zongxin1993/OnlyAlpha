# onlyalpha-runtime：执行持久化与恢复

## 目的与职责

在交易内核之外提供可复用的 Execution 会话、SQLite 存储、检查点、回放记录及精确只读快照。

本库是 `crates/` 下的 Rust 库，供其他库、后端或插件通过 Rust 公开接口复用。
职责依据[仓库架构](../../docs/repository-product-architecture.md)和各语义所属契约；此说明不新增 Authority，也不替代正式契约。

## 边界与依赖

不拥有后端 PostgreSQL 产品存储、任务准入、Runtime Generation 选择或 LIVE 权限；不是独立产品运行入口。

直接依赖的仓内库：[`onlyalpha-execution`](../execution/README.md)、[`onlyalpha-broker`](../broker/README.md)、[`onlyalpha-observability`](../observability/README.md)。

观测仅接入存储及只读重建边界，记录原查询、组件恢复和完整性检查的耗时与已有输入计数；不改变事实、恢复结果或状态摘要。公开调用方自行管理诊断 Session，库不读取环境或安装全局订阅器。
完整依赖、特性及编译配置见 [Cargo.toml](Cargo.toml)。调用方只能通过公开接口集成，不直接访问私有模块或修改所属状态。

## 公开接口

[`RunConfiguration`、`RunBinding`、`TradingInput`、`Session`、`AppliedEvent`、`CompletedSession`](src/session.rs)提供有限作业的内存边界。配置使用真实 Components 校验，绑定只含 Kernel 执行所需的内容身份，不授予数据权限或外部派发资格。`Session::apply` 持有当前 typed owner，按输入身份核对重复和冲突；事件须按序 `acknowledge`，未 drain、失败、未满足经济结束条件均不能 `finish`。普通资金／风控拒绝保留未变化的经济状态；其他异常使会话失效。

只保存紧凑输入、事件和幂等索引，限制单输入 64 KiB、事实总编码 128 MiB、最多一百万条事实；该上限不包含分配器开销，RSS 须另测。结束时一次性生成 Account／Ledger 时间线、对账和完整经济结果；不把每步的完整 checkpoint 保存为历史。`CompletedSession` 只证明本会话结束，行情耗尽由 Backtest 证明，Backend 另加作业与发布条件。内存丢失后不能宣称可断点续算。原文件持久化接口在迁移消费者完成前仍保留。

`memory.admission` 和 `memory.apply` 复用 observability 的显式订阅器；诊断字段不进入业务身份、检查点或结果。

[`durability`](src/durability.rs) 提供持续交易的 `DurableFactPort`。`TradingBinding` 从校验过的 SIM／LIVE 配置、内核工件绑定流身份和版本。`RecoveryFacts::from_records` 需要同一快照内的绑定、水位和原事务，按序验证每条原输入、计划及经济投影，重建六个执行组件并对账。绑定冲突、缺行、投影前驱未就绪或经济内容不符时拒绝恢复。仅末条可处于已提交待投影状态；此时可读取恢复后的投影和原记录，必须由仓储确认原事务 Ready，重新读取后才能继续准备。`prepare` 生成的 `PreparedTradingFacts` 绑定原前驱、计划和事件；PG 适配器应在同一事务核对前驱并提交。`DurableCommitReceipt` 核对绑定与完整提交计划，只提供提交观察。数据库暂不可读和提交结果未知分别返回 `Unavailable`、`UnknownCommit`，由驱动继续核对原交易。

场所重复投递时，先用 `RecoveryFacts::observe_input` 按 `input_id` 查询当前已验证水位内的全部原记录，包括已提交待投影的末条事务。输入正文完全一致时返回原 `Record`，保留其 Ready 状态。同一身份对应不同正文时返回 `TRADING_INPUT_CONFLICT`，非法或缺失的身份返回内核校验错误。只有该身份在此快照中确实不存在时才返回 `None`，随后可按正常序列规则调用 `prepare`。

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

性能基准入口与口径见 [BENCHMARK.md](BENCHMARK.md)。
