# onlyalpha-runtime：统一量化 Runtime、纯因子研究与共享事件主循环

## 目的与职责

[`OnlyAlphaRuntime`](src/lib.rs) 是 [ADR 0152](../../docs/adr/0152-unified-runtime-dual-kernel-operators-qlib-dag-and-wasm-plugins.md) §2.1 定义的量化计算与交易语义唯一门面。它从同一份已编译的因子表达式、同一数值政策（`DECIMAL28_HALF_EVEN_Q12_V1`）出发，提供两条共用底座的能力：

- **Research（`research`）**：在冻结对齐面板上批量求值因子与标签 DAG，给出逐事件横截面 IC／RankIC 以及全样本统计证据。只读，不产出任何可发布事实。
- **Trading（`trading`）**：Backtest／SIM／LIVE 共用的统一事件主循环。逐事件求值因子、读取只读账户、调用策略、提交规范化 `OrderIntent`。引擎不含模式字段，模式差异全部落在调用方注入的端口实现上。

同一因子经向量内核与事件内核求值时逐点一致，不靠容差掩盖差异；这是 ADR 0152 双内核要求在本库的直接体现。

本库同时保留两个既有职责：

- 有限作业的内存 Execution 会话（`Session`）。业务不使用 SQLite 或文件型 Source；有限作业过程状态常驻内存、终态由后端 PostgreSQL 原子发布。
- 持续交易持久事实／恢复端口（`durability`）。由后端 PostgreSQL 适配 `DurableFactPort`。

本库是 `crates/` 下的 Rust 库，供其他库、后端或插件通过 Rust 公开接口复用。职责依据[仓库架构](../../docs/repository-product-architecture.md)和各语义所属契约；此说明不新增 Authority，也不替代正式契约。

## 边界与依赖

不拥有行情采集与使用授权、券商协议与外部派单、风控与准入的具体实现、持久化驱动、任务准入、Runtime Generation 选择或 LIVE 权限；不是独立产品运行入口，也不提供 Web／Agent 控制 API。

**派单权限属于执行端口。** 主循环只产出规范化意图并交给调用方注入的 `ExecutionPort`；本库不产出任何外部发单能力，也不绕过风控、准入与持久化。

直接依赖的仓内库：[`onlyalpha-domain`](../domain/README.md)（标的、时间、数值与 `OrderIntent`／只读账户等交易值对象）、[`onlyalpha-operators`](../operators/README.md)（已认证算子与精确十进制）、[`onlyalpha-calculation`](../calculation/README.md)（声明式因子表达式编译、向量与事件内核、快照）、[`onlyalpha-execution`](../execution/README.md)、[`onlyalpha-broker`](../broker/README.md)、[`onlyalpha-observability`](../observability/README.md)。

观测仅接入内存会话及诊断边界（`memory.admission`、`memory.apply`），记录原操作耗时与已有输入计数；不改变事实、恢复结果或状态摘要。公开调用方自行管理诊断 Session，库不读取环境或安装全局订阅器。

完整依赖、特性及编译配置见 [Cargo.toml](Cargo.toml)。调用方只能通过公开接口集成，不直接访问私有模块或修改所属状态。

## 公开接口

公开入口以 [`src/lib.rs`](src/lib.rs) 为准；详细签名、方法和前置条件以源码及 `cargo doc` 为准。Rust 库接口不等同于面向 Web / Agent 的版本化控制 API。

```rust
pub mod durability;
pub mod research;
mod session;
pub mod trading;

pub use research::{Cohort, ResearchEngine, ResearchPanel, ResearchReport, SeriesStatistics};
pub use session::{
    AppliedEvent, CompletedSession, RunBinding, RunConfiguration, Session, TradingInput,
};
pub use trading::{
    BarOutcome, ExecutionPort, MarketBar, MarketPort, NamedFactorExpr, StrategyDecision,
    StrategyPort, TradingEngine,
};

pub struct OnlyAlphaRuntime;
impl OnlyAlphaRuntime {
    pub fn new() -> Result<Self, Error>;
    pub fn run_research(&self, panel: &ResearchPanel, factor: &FactorExpr, target: &TargetExpr)
        -> Result<ResearchReport, Error>;
    pub fn trading_engine(&self, instruments: Vec<OnlyInstrumentId>, factors: Vec<NamedFactorExpr>)
        -> Result<TradingEngine, Error>;
}
```

**研究（[src/research.rs](src/research.rs)）**：`ResearchPanel::new` 接收每只标的一组等长列，要求所有标的字段集合一致（`RESEARCH_PANEL_SCHEMA`）且列等长（`RESEARCH_PANEL_LENGTH`）；空面板与无字段面板分别以 `RESEARCH_PANEL_EMPTY`、`RESEARCH_PANEL_NO_FIELDS` 拒绝。`ResearchEngine::run` 只读求值，返回的因子矩阵按 `[标的][事件]` 索引；IC 由研究专用的横截面相关系数算子逐个事件计算，RankIC 先做横截面排名再求相关系数，均值、标准差与 IR 复用 `RollingMean`／`RollingStd`／`Divide`，全程 `Decimal`，不引入浮点实现。缺失事件不参与统计，也不被当作零；`SeriesStatistics::observations` 说明实际参与的数量。研究结果只说明本次切片上的观察，不构成认证或可发布事实。

**主循环（[src/trading.rs](src/trading.rs)）**：

- `MarketBar` 承载一个事件时间的完整横截面：构造时按标的身份排序并拒绝重复（`TRADING_DUPLICATE_INSTRUMENT`），缺失字段保持 `None` 而不当作零。
- `NamedFactorExpr` 把一个名字与一份已编译表达式绑定。名字是策略绑定身份，1..128 字符，重名以 `TRADING_FACTOR_NAME` 拒绝。`compile_with_allowed_fields` 声明扩展算子的派生字段集合，只有列在其中的 `$<field>` 才能进入表达式。
- `TradingEngine::new` 排序并校验标的集合与因子定义；`advance` 先核对横截面形状（`TRADING_SCHEMA_MISMATCH`）与事件时间严格递增（`TRADING_EVENT_ORDER`），再按标的逐个调用 `StrategyPort::decide`，拒绝把意图下给其他标的（`TRADING_INTENT_INSTRUMENT_MISMATCH`），随后交 `ExecutionPort::submit`。
- `MarketPort`、`StrategyPort`、`ExecutionPort` 是仅有的三个边界端口。券商、风控、准入与持久化事实都在执行端口内部完成；策略端口只读取已绑定因子与只读账户快照。

本库刻意不提供第四套能力：派单授权（属执行端口）、独立 `BrokerPort`（券商由执行端口封装）、执行端口上的 `reconcile` 方法（对账由 `durability::RecoveryFacts` 对 `MATCHED` 的强制要求保证）。主循环不复制后端已有的准入、风控与持久化语义。

**内存会话（[src/session.rs](src/session.rs)）**：[`RunConfiguration`、`RunBinding`、`TradingInput`、`Session`、`AppliedEvent`、`CompletedSession`](src/session.rs) 提供有限作业的内存边界。配置使用真实 Components 校验，绑定只含 Kernel 执行所需的内容身份，不授予数据权限或外部派发资格。`Session::apply` 持有当前 typed owner，按输入身份核对重复和冲突；事件须按序 `acknowledge`，未 drain、失败、未满足经济结束条件均不能 `finish`。普通资金／风控拒绝保留未变化的经济状态；其他异常使会话失效。

只保存紧凑输入、事件和幂等索引，限制单输入 64 KiB、事实总编码 128 MiB、最多一百万条事实；该上限不包含分配器开销，RSS 须另测。结束时一次性生成 Account／Ledger 时间线、对账和完整经济结果；不把每步的完整 checkpoint 保存为历史。`CompletedSession` 只证明本会话结束，行情耗尽由 Backtest 证明，Backend 另加作业与发布条件。内存丢失后不能宣称可断点续算，由后端在新 Attempt 上按原冻结输入重算。

**持续交易持久端口（[src/durability.rs](src/durability.rs)）**：`DurableFactPort` 提供提交与恢复。`TradingBinding` 从校验过的 SIM／LIVE 配置、内核工件绑定流身份和版本。`RecoveryFacts::from_records` 需要同一快照内的绑定、水位和原事务，按序验证每条原输入、计划及经济投影，重建六个执行组件并对账；投影状态不是 `MATCHED` 时以 `TRADING_RECONCILIATION_MISMATCH` 拒绝恢复。绑定冲突、缺行、投影前驱未就绪或经济内容不符时同样拒绝。仅末条可处于已提交待投影状态；此时可读取恢复后的投影和原记录，必须由仓储确认原事务 Ready，重新读取后才能继续准备。`prepare` 生成的 `PreparedTradingFacts` 绑定原前驱、计划和事件；PG 适配器应在同一事务核对前驱并提交。`DurableCommitReceipt` 核对绑定与完整提交计划，只提供提交观察。数据库暂不可读和提交结果未知分别返回 `Unavailable`、`UnknownCommit`，由驱动继续核对原交易。

场所重复投递时，先用 `RecoveryFacts::observe_input` 按 `input_id` 查询当前已验证水位内的全部原记录，包括已提交待投影的末条事务。输入正文完全一致时返回原 `Record`，保留其 Ready 状态。同一身份对应不同正文时返回 `TRADING_INPUT_CONFLICT`，非法或缺失的身份返回内核校验错误。只有该身份在此快照中确实不存在时才返回 `None`，随后可按正常序列规则调用 `prepare`。

技术组合与持久化边界见[持久化契约](../../docs/rust-runtime-persistence.md)。旧 SQLite 存储、文件 journal、codec 及只读快照入口已随 ADR 0151 退役。

## 状态与生命周期

- **统一门面（`OnlyAlphaRuntime`）**：只持有已认证算子 Kernel，不缓存面板、因子结果或运行状态，可克隆共享；`new` 的失败来自算子注册表本身。
- **研究（`ResearchEngine`）**：完全只读，不改变输入面板、因子或标签，也不推进任何事件状态；同一输入重复运行结果逐位相同。
- **主循环（`TradingEngine`）**：持有各因子的算子滚动状态、最后事件时间与标的声明。任一事件失败都会把因子状态回滚到该事件之前，`TRADING_ROLLBACK_FAILED:<code>` 表示回滚本身失败；已提交的外部事实不回滚，交给执行端口按 `input_id` 幂等对账，引擎不重发已建立的意图。
- **检查点（`checkpoint`／`restore_checkpoint`）**：只保存恢复内核所需的最小状态——标的集合、最后事件时间、事件数与每个因子的名字、表达式指纹、内核布局和算子状态。恢复时核对 schema、数量、标的、指纹与布局（`TRADING_CHECKPOINT_INVALID`、`TRADING_CHECKPOINT_BINDING`、`TRADING_CHECKPOINT_LAYOUT`）。账户与外部成交事实的恢复和对账由执行端口的持久化事实负责，不进入内核检查点。
- **有限作业会话（`Session`）**：纯内存运行，不写文件或 SQLite。事件须按序 `acknowledge`，任意异常使会话进入失效状态并拒绝继续推进。
- **持续交易持久端口（`durability`）**：由后端 PostgreSQL 适配实现，维护原绑定、前驱与 committed-unready 投影边界；恢复失败或数据库不可用时拒绝新增风险，保留观察和恢复能力。

## 使用与验证

在调用方 `Cargo.toml` 声明本库路径依赖，从上述入口选择类型或端口；配置、输入记录与身份必须按对应正式契约构建。研究、回测与实盘使用同一份因子定义：研究与回测结果的逐点一致性由 `trading` 的单元测试直接断言。

当前没有独立 Cargo 示例目标；可从公开入口和所属测试查看调用方式。

在仓库根目录执行：

```sh
python3 scripts/unit_tests.py
cargo test -p onlyalpha-runtime --test memory_session --test memory_perpetual --test perpetual_economics
cargo doc -p onlyalpha-runtime --no-deps
```

集成测试位于 [`tests/`](tests/)，独立单元测试统一集中在 `src/tests/`，仍由原业务模块挂载并保留私有访问；内联测试可保留。无外部服务依赖的库验证可在宿主机运行并记录平台；数据库或运行中应用验证使用固定 `onlyalpha-dev` 环境。

一级目录仅允许 `src/`、`tests/`、`examples/`、`benches/`，按需创建。编译资源归入 `src/`，专用测试数据随测试组织，共享参考数据使用根目录 `test-data/`。

性能基准入口与口径见 [BENCHMARK.md](BENCHMARK.md)。
