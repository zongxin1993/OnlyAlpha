# onlyalpha-runtime：统一量化 Runtime、纯因子研究与共享事件主循环

## 目的与职责

[`OnlyAlphaRuntime`](src/lib.rs) 是 [ADR 0152](../../docs/adr/0152-unified-runtime-dual-kernel-operators-qlib-dag-and-wasm-plugins.md) §2.1 定义的量化计算与交易语义唯一门面。它从同一份已编译的因子表达式、同一数值政策（`DECIMAL28_HALF_EVEN_Q12_V1`）出发，提供两条共用底座的能力：

- **Research（`research`）**：在冻结对齐面板上批量求值因子与标签 DAG，将同轴矩阵交给研究统计库，返回预测效果、观测覆盖、分期稳定性和指定因子对的内存报告。只读，不产出任何可发布事实。
- **Trading（`trading`）**：Backtest／SIM／LIVE 共用的统一事件主循环。逐事件求值因子、读取只读账户、调用策略、提交规范化 `OrderIntent`。引擎不含模式字段，模式差异全部落在调用方注入的端口实现上。

同一因子经向量内核与事件内核求值时逐点一致，不靠容差掩盖差异；这是 ADR 0152 双内核要求在本库的直接体现。

本库同时保留两个既有职责：

- 有限作业的内存 Execution 会话（`Session`）。业务不使用 SQLite 或文件型 Source；有限作业过程状态常驻内存、终态由后端 PostgreSQL 原子发布。
- 持续交易持久事实／恢复端口（`durability`）。由后端 PostgreSQL 适配 `DurableFactPort`。

本库是 `crates/` 下的 Rust 库，供其他库、后端或插件通过 Rust 公开接口复用。职责依据[仓库架构](../../docs/repository-product-architecture.md)和各语义所属契约；此说明不新增 Authority，也不替代正式契约。

## 边界与依赖

不拥有行情采集与使用授权、券商协议与外部派单、风控与准入的具体实现、持久化驱动、任务准入、Runtime Generation 选择或 LIVE 权限；不是独立产品运行入口，也不提供 Web／Agent 控制 API。

**派单权限属于执行端口。** 主循环只产出规范化意图并交给调用方注入的 `ExecutionPort`；本库不产出任何外部发单能力，也不绕过风控、准入与持久化。

直接依赖的仓内库：[`onlyalpha-domain`](../domain/README.md)（标的、时间、数值与 `OrderIntent`／只读账户等交易值对象）、[`onlyalpha-operators`](../operators/README.md)（已认证算子与精确十进制）、[`onlyalpha-calculation`](../calculation/README.md)（声明式因子表达式编译、向量与事件内核、快照）、[`onlyalpha-research-statistics`](../research-statistics/README.md)（已求值矩阵的截面统计与报告）、[`onlyalpha-execution`](../execution/README.md)、[`onlyalpha-broker`](../broker/README.md)、[`onlyalpha-observability`](../observability/README.md)。

观测仅接入内存会话及诊断边界（`memory.admission`、`memory.apply`），记录原操作耗时与已有输入计数；不改变事实、恢复结果或状态摘要。公开调用方自行管理诊断 Session，库不读取环境或安装全局订阅器。

完整依赖、特性及编译配置见 [Cargo.toml](Cargo.toml)。调用方只能通过公开接口集成，不直接访问私有模块或修改所属状态。

## 公开接口

公开入口以 [`src/lib.rs`](src/lib.rs) 为准；详细签名、方法和前置条件以源码及 `cargo doc` 为准。Rust 库接口不等同于面向 Web / Agent 的版本化控制 API。

```rust
pub mod durability;
pub mod research;
mod session;
pub mod trading;

pub use research::{
    Cohort, ComparisonRef, FactorReport, ResearchComparison, ResearchEngine, ResearchPanel, ResearchPlan,
    ResearchReport, ResearchSeries, SeriesStatistics, StatisticRow, StatisticStatus, StatisticsPlan,
    TimeSlice,
};
pub use session::{
    AppliedEvent, CompletedSession, RunBinding, RunConfiguration, Session, TradingInput,
};
pub use trading::{
    BarOutcome, EventOutcome, ExecutionPort, MarketBar, NamedFactorExpr, StrategyDecision,
    StrategyPort, TradingEngine, TradingEvent, TradingEventPort, TradingRunError,
};

pub struct OnlyAlphaRuntime;
impl OnlyAlphaRuntime {
    pub fn new() -> Result<Self, Error>;
    pub fn run_research(&self, panel: &ResearchPanel, plan: &ResearchPlan)
        -> Result<ResearchReport, Error>;
    pub fn trading_engine(&self, instruments: Vec<OnlyInstrumentId>, factors: Vec<NamedFactorExpr>)
        -> Result<TradingEngine, Error>;
}
```

**纯因子研究**

1. `ResearchPanel::new(snapshot, instruments, warmup)` 接受读取方提供的冻结快照引用，以及逐标的的 `(OnlyInstrumentId, Vec<OnlyTimestamp>, Cohort)`。`Cohort` 按字段存放 `Option<Decimal>` 列。构造器排序标的，拒绝重复标的，核对各标的严格递增的 i64 纳秒时间轴、字段集合和列长，并在计算摘要前限制输入总格数和字段名字节长度。字段名上限沿用表达式解析器的 `MAX_IDENT_LEN`。预热行参与因子求值；从 `warmup` 下标开始计入统计。重放时，用 `verify_content` 将实际面板摘要与原先留存的预期值核对。快照授权与原始行情封印由读取方负责。[面板实现](src/research_panel.rs)
2. `ResearchPlan::new(factors, targets, minimum_observations)` 按声明顺序接收 `(String, FactorExpr)` 因子和 `(String, TargetExpr)` 标签；同一角色内名字唯一。最小有效配对数至少为 2。窗口等精确参数在编译表达式时固定，报告沿用包含实参、算子语义版本与数值政策的 DAG 指纹。因子执行器拒绝前视。研究计划只接受逐标的时间序列标签，横截面标签返回 `RESEARCH_TARGET_SHAPE`。标签可以向前读取同一标的在冻结切片内的值，尾部不足保留 NULL。[表达式接口](../calculation/src/factor_expr/mod.rs)
3. `run_research` 对每个声明分别求值一次。`ResearchReport` 保留快照引用、面板摘要、排序后的标的、完整事件时间、预热行数和最小配对数。报告通过只读访问器提供轴和结果。`factors()` 和 `targets()` 分别返回名字、指纹和 `[标的][事件]` 值矩阵。`comparisons()` 按因子优先、标签其次的声明顺序返回统计，每组保存两侧在报告内的固定索引。结果矩阵和统计行在分配前按算子库的 `MAX_CELLS` 核对。全部表达式的累计向量求值开销、横截面配对槽位分别按 `MAX_WINDOW_WORK` 核对，超限返回 `RESEARCH_RESOURCE_BUDGET`。统计行 `rows[i]` 对应 `timestamps[warmup + i]`。[研究门面](src/lib.rs) · [研究结果](src/research.rs)
4. 每行对同一时点的完整配对计算等权 Pearson IC 和精确平均秩的 RankIC，保留配对数和状态。配对不足、因子或标签零方差时返回有明确原因的空值。样本摘要只消费已输出的有效 Q12 值，样本标准差分母为 `n−1`，IR 为均值除以样本标准差，不年化。因子 DAG 使用注册表的 28 位政策；研究统计使用 38 位 Decimal 上下文，输出按 half-even 舍入到 Q12。[统计实现](../research-statistics/src/math.rs) · [统计定义](../../docs/adr/0082-research-target-statistics-evaluation-authority.md) · [摘要定义](../../docs/adr/0119-rich-research-statistics-authority-and-factor-quality-evidence-contract.md)
5. `ResearchPlan::with_statistics` 附加按事件时间排列且互不重叠的半开分期，以及按因子名指定的比较对。`run_research` 在表达式求值前核算报告中比较与分期摘要的分配预算。`factor_report()` 提供只读类型化数据和 JSON 视图。`comparisons()` 与其中的因子对标签结果共用同一份数据。正式结果发布和 Qualification 准入各由所属模块负责。[统计计划](../research-statistics/src/plan.rs) · [报告视图](../research-statistics/src/view.rs)

只比较因子时，调用 `ResearchPlan::for_factor_pairs(factors, pairs, minimum_observations)`，传入至少一对指定因子，再从 `factor_report().pairs()` 读取结果。分期适用于因子与标签的比较。各分期按因子观测时间归组，标签先在完整冻结面板上求值，因此期末观测可使用下一期行情。`ResearchReport::target_lookahead_steps()` 按标签声明顺序返回最大前视步数。`ResearchSeries::target_lookahead_steps(&TargetExpr)` 以指纹核对标签表达式，错配返回 `RESEARCH_STATISTICS_BINDING`。`ResearchReport` 的 `summary_view()`、`comparison_view()`、`slice_view()`、`detail_view()` 在各自的标签定位信息中输出对应步数。例如 `Lead($close, 1)` 使用同一标的的下一条观测，`$close` 的前视步数为 0。`factor_report()` 提供只基于矩阵的原始统计，其视图中该字段为 `null`。

因子与标签的每行 `sample_count` 记录双方有值的标的数，`missing_counts` 分开记录仅因子缺值、仅标签缺值和双侧缺值。四项合计等于该时点面板标的数；覆盖摘要按样本期内的标的与时点累计。

例如，在已有 `snapshot` 和同轴行情 `instruments` 上，用五期均价检验下一期简单收益，同时比较均价因子与成交量因子。面板每个标的均提供 `close`、`volume` 两列，至少包含 5 个时点。`start_ns` 和 `end_ns` 是调用方选定的样本区间，每行至少需要 3 个完整配对。

```rust
use onlyalpha_calculation::factor_expr::{FactorExpr, TargetExpr};
use onlyalpha_runtime::{
    ComparisonRef, OnlyAlphaRuntime, ResearchPanel, ResearchPlan, StatisticsPlan, TimeSlice,
};

let panel = ResearchPanel::new(snapshot, instruments, 4)?;
let statistics = StatisticsPlan::new(
    vec![TimeSlice { start_ns, end_ns }],
    vec![("mean5".into(), "quantity".into())],
)?;
let plan = ResearchPlan::new(
    vec![
        ("mean5".into(), FactorExpr::compile("Mean($close, 5)")?),
        ("quantity".into(), FactorExpr::compile("$volume")?),
    ],
    vec![("next_return".into(), TargetExpr::compile("Lead($close, 1) / $close - 1")?)],
    3,
)?.with_statistics(statistics)?;
let report = OnlyAlphaRuntime::new()?.run_research(&panel, &plan)?;
let observations = &report.comparisons()[0].coverage;
let factor_pair = report.comparison_view(ComparisonRef::FactorPair(0))?;
let slice = report.slice_view(0, 0)?;
```

**主循环（[src/trading.rs](src/trading.rs)）**：

- `MarketBar` 承载一个事件时间的完整横截面：构造时按标的身份排序并拒绝重复（`TRADING_DUPLICATE_INSTRUMENT`），缺失字段保持 `None` 而不当作零。
- `NamedFactorExpr` 把一个名字与一份已编译表达式绑定。名字是策略绑定身份，1..128 字符，重名以 `TRADING_FACTOR_NAME` 拒绝。`compile_with_allowed_fields` 声明扩展算子的派生字段集合，只有列在其中的 `$<field>` 才能进入表达式。
- `TradingEngine::handle_event` 按调用顺序处理一个 `TradingEvent`。`Market` 核对截面形状和行情时间严格递增，推进因子，并用同一份账户快照逐标的调用策略；`ExecutionPort::submit` 接收通过标的检查的意图。`EventOutcome::Market` 包含本次行情观测。
- `Venue` 携带券商库已经解码的 `Fact`，调用 `ExecutionPort::observe_venue`。端口负责关联原命令、校验范围与重复、处理冲突，并通过所属经济模块应用成交。`VenueObserved` 只表示端口完成了本次观察。回报可在两根 bar 之间或与行情同一时刻到达，保持交付顺序，无需等下一根 bar，也不推进因子。
- `TradingEventPort::next_event` 逐条交付输入，`Ok(None)` 表示来源结束。`TradingEngine::run` 在 `handle_event` 成功后将原输入和结果交给 `consume(&TradingEvent, EventOutcome) -> Result<()>`。回调返回 `Ok(())` 后才读取下一条事件。读取来源失败时返回 `TradingRunError::Source`。`Processing` 和 `Consumption` 都保留底层错误并归还已取出的原事件，后续事件仍留在来源中。`Processing` 表示处理报错，执行方可能已产生事实，调用方须按原身份查询并对账。`Consumption` 表示当前事件已处理，消费方因预算不足等原因拒绝了结果；因子状态和已提交命令不会回滚。两类错误都不授权重发命令。

**内存会话（[src/session.rs](src/session.rs)）**：[`RunConfiguration`、`RunBinding`、`TradingInput`、`Session`、`AppliedEvent`、`CompletedSession`](src/session.rs) 提供有限作业的内存边界。配置使用真实 Components 校验，绑定只含 Kernel 执行所需的内容身份，不授予数据权限或外部派发资格。`Session::apply` 持有当前 typed owner，按输入身份核对重复和冲突；事件须按序 `acknowledge`，未 drain、失败、未满足经济结束条件均不能 `finish`。普通资金／风控拒绝保留未变化的经济状态；其他异常使会话失效。

只保存紧凑输入、事件和幂等索引，限制单输入 64 KiB、事实总编码 128 MiB、最多一百万条事实；该上限不包含分配器开销，RSS 须另测。结束时一次性生成 Account／Ledger 时间线、对账和完整经济结果；不把每步的完整 checkpoint 保存为历史。`CompletedSession` 只证明本会话结束，行情耗尽由 Backtest 证明，Backend 另加作业与发布条件。内存丢失后不能宣称可断点续算，由后端在新 Attempt 上按原冻结输入重算。

**持续交易持久端口（[src/durability.rs](src/durability.rs)）**：`DurableFactPort` 提供提交与恢复。`TradingBinding` 从校验过的 SIM／LIVE 配置、内核工件绑定流身份和版本。`RecoveryFacts::from_records` 需要同一快照内的绑定、水位和原事务，按序验证每条原输入、计划及经济投影，重建六个执行组件并对账；投影状态不是 `MATCHED` 时以 `TRADING_RECONCILIATION_MISMATCH` 拒绝恢复。绑定冲突、缺行、投影前驱未就绪或经济内容不符时同样拒绝。仅末条可处于已提交待投影状态；此时可读取恢复后的投影和原记录，必须由仓储确认原事务 Ready，重新读取后才能继续准备。`prepare` 生成的 `PreparedTradingFacts` 绑定原前驱、计划和事件；PG 适配器应在同一事务核对前驱并提交。`DurableCommitReceipt` 核对绑定与完整提交计划，只提供提交观察。数据库暂不可读和提交结果未知分别返回 `Unavailable`、`UnknownCommit`，由驱动继续核对原交易。

场所重复投递时，先用 `RecoveryFacts::observe_input` 按 `input_id` 查询当前已验证水位内的全部原记录，包括已提交待投影的末条事务。输入正文完全一致时返回原 `Record`，保留其 Ready 状态。同一身份对应不同正文时返回 `TRADING_INPUT_CONFLICT`，非法或缺失的身份返回内核校验错误。只有该身份在此快照中确实不存在时才返回 `None`，随后可按正常序列规则调用 `prepare`。

技术组合与持久化边界见[持久化契约](../../docs/rust-runtime-persistence.md)。旧 SQLite 存储、文件 journal、codec 及只读快照入口已随 ADR 0151 退役。

## 状态与生命周期

- **统一门面（`OnlyAlphaRuntime`）**：持有无状态研究引擎。研究计划和面板按调用借入，报告由调用方持有。
- **研究（`ResearchEngine`）**：完全只读，不改变输入面板、因子或标签，也不推进任何事件状态；同一输入重复运行结果逐位相同。
- **主循环（`TradingEngine`）**：持有各因子的滚动状态、最后行情时间与标的声明，`events()` 表示已处理的行情截面数。行情处理失败时回滚本次因子推进；已提交的外部事实仍有效。同一截面有多条意图而中途失败时，调用方须先核对原命令及已提交前缀，再决定如何恢复。
- **检查点（`checkpoint`／`restore_checkpoint`）**：只保存恢复内核所需的最小状态——标的集合、最后事件时间、事件数与每个因子的名字、表达式指纹、内核布局和算子状态。恢复时先核对版本、数量、标的、时间与行情计数的组合，再在临时副本中恢复各因子，校验绑定、布局及各自的步数。整份检查点通过后才一起替换因子状态与最后行情时间。任一校验或恢复失败，调用前的引擎状态完整保留。账户与外部成交事实的恢复和对账由执行端口的持久化事实负责，不进入内核检查点。
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
