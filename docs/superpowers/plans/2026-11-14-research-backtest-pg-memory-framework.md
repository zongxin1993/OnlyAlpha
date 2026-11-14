# Research／回测框架重构详细实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将当前 Research／回测改为同源信号、构建认证复用、ClickHouse 精确行情输入、内存执行和 PostgreSQL 原子业务发布，并完整退役业务 SQLite，取得回归、真实性能和独立审查证据。

**Architecture:** 计算与交易语义留在现有 Rust 库，受限 Python 仅承担因子编写和构建前端；Backend 负责权限、数据库适配、作业控制和发布。有限作业保留 Run 与冻结绑定，未发布工作丢失后由新 Attempt 重算；持续交易依靠 PostgreSQL 正式事实与外部对账恢复。

**Tech Stack:** 现有 Rust workspace、受限 Python 编写入口、bigdecimal、tokio-postgres、ClickHouse 客户端、Criterion、现有 observability、固定 onlyalpha-dev Docker Compose。默认不新增依赖、crate、数据库或服务。

**Spec:** [已确认设计](../specs/2026-11-14-research-backtest-pg-memory-framework-design.md)、[ADR 0151](../../adr/0151-postgresql-business-publication-and-memory-work.md)。最高约束仍为 PROJECT_CONSTITUTION.md；本计划不是第二份验收 Authority。

**授权状态：** 负责人已确认总体设计并授权编写计划。本计划编写时仅修改文档；后续实施范围以负责人逐次启动指令为准，计划本身不是完成记录。日期：2026-11-14。

## Global Constraints

- 项目业务实现不使用SQLite，不建立文件型事实数据库、封闭发布日志、fs-verity依赖或额外Source服务。
- PostgreSQL拥有需要发布、控制、审计及留存的业务数据；ClickHouse拥有K线实体；有限作业的计算与未发布过程数据在内存。
- Research和回测共享同一策略版本和纯信号逻辑，输入限行情、因子及显式参数。仓位、资金、风控、订单和成交在后续交易环节处理。
- 新因子与Rust原生算子统一precision28、HALF_EVEN、q12和明确的缺值/错误语义。
- 精确参数组合分别认证；不凭有限样例声称覆盖全参数域。
- 不保留旧接口/格式兼容、转换器、fallback；不覆盖已发布迁移字节。Constitution及其指纹不改。
- 发布前中断保留原 Run、冻结身份及输入；先观察原发布状态，确认未发布并取得新 Claim 后重算。Attempt/PID/耗时不进入经济身份。
- 首版终态 CANCELLED 不发布部分结果；已完成结果不被迟到取消撤销。UNKNOWN 不当作失败或未提交。
- Sim/Live 正式订单、成交和资金事实逐步持久化；内存候选不能授予真实派单资格。
- 本机固定 onlyalpha-dev；数据库／OpenAPI／Web 验证经 scripts/dev_verification.py，不另起拓扑。不重复已完成的开发数据清理。
- 不设新的硬吞吐门槛；既有300/120秒Web门槛不修改。信号与收益关系设计在框架工作完成后另做。
- 不在本计划执行旧正式 Web 长取证；新增长时专项预算另明确。正常受影响功能回归属于将来实施范围。
- 资源压力、Docker 无响应、连续异常超时停止验证；同一问题三次失败后停止并报告，不通过换执行者重置次数。

## Review Focus

以下五类风险均有下文测试归属，审查者须独立推导合法状态，不只复述测试结论。

1. COMMIT 已到服务端但客户端断开：先观察同一 Run 的锁与正式发布，不能无锁查空后重算（阶段二、六）。
2. 完成、取消与 lease 过期同时发生：只有合法持有者可发布，取消不伪造结果，完成不被撤销（阶段六）。
3. 参数精确值、数值边界和多实例状态：认证不能跨参数复用，窗口状态不能跨 Run/instrument 泄漏（阶段三）。
4. ClickHouse 同范围修订、缺行或错关联：不得悄悄换最新数据，也不能仅比较行数（阶段四）。
5. 持续交易在提交未知／已提交未投影处重启：不能重复真实派单，内存 Driver 不能伪造持久提交许可（阶段七）。

## 执行组织、依赖与阶段交付

这是一个相互依赖的框架迁移，采用一份总计划约束接口；不将其拆成互不相认的存储、因子和 Source 方案。各阶段有可单测交付，只有完整接线后才具备产品可用性。实施由当前执行者逐阶段完成；高风险阶段交付由实现者之外的审查者检查，最后另做整体验收审查。设计检查不能替代实施审查。

| 阶段 | 可审查交付 | 依赖 | 放行条件 |
|---|---|---|---|
| 一 | 契约、身份、结果成员及调用迁移清单 | 已确认设计 | 无上位冲突，接口和故障分类可验证 |
| 二 | PostgreSQL 类型化仓储、权限与原子发布 | 一 | 真实数据库事务／并发／未知结果测试与独立审查 |
| 三 | 因子构建、Rust 程序、精确参数认证 | 一；状态留存依赖二 | 数值和同前缀 batch/event 一致，构建不落入逐行热路径 |
| 四 | 共用精确行情输入和有界内存准备 | 一、二、三的绑定类型 | 错输入拒绝，重算输入相同，预算明确 |
| 五 | 内存 Runtime、完整回测和虚拟券商 | 一、三、四 | 经济 golden、确定性及完整交易路径回归 |
| 六 | Research／Backtest 发布、查询、重算与取消 | 二至五 | 故障矩阵闭合，正式 API 接线与独立审查 |
| 七 | 持续交易 PostgreSQL 持久化／恢复基础 | 二、五 | 提交前持久化、未知观察、恢复不重复派单 |
| 八 | SQLite／文件 Source 完整退役与工具同步 | 二至七 | 无实际依赖／旧业务入口，正反门禁成立 |
| 九 | 正式产品回归、性能实战与整体独立审查 | 前八阶段 | 证据完整；未满足项明确保持未完成 |

不允许在阶段八前将新生产接线回退到旧 Source。中间提交可保留尚未迁移的旧实现以便编译，但不得新增双写／自动 fallback；阶段八结束必须删除。每阶段使用确定文件范围的提交，不把既有 181 个源文件改动全量暂存。

## 文件职责与接口约定

下列新路径是计划目标，不表示文件已存在；已有同责实现优先扩展，禁止平行新增第二套 Authority。公开接口应使用现有领域 ID、错误与事实类型；以下签名固定职责，类型在各阶段给出的文件定义或复用，不以 serde_json::Value 代替内部所有模型。

| 位置 | 责任 |
|---|---|
| crates/calculation/src/program.rs（新） | 不可变 typed 程序、指令、输入／输出类型及数值规范 |
| crates/calculation/src/program_execution.rs（新） | batch/event 执行、实例窗口状态和确定性输出 |
| crates/strategy/src/model.rs、execution.rs | 同一信号图绑定和执行；不加入资金／仓位输入 |
| crates/runtime/src/session.rs（新） | 当前交易 owner 与临时计算会话；无数据库客户端 |
| crates/runtime/src/durability.rs（新） | 持续交易的类型化持久化／恢复 port 与提交凭证 |
| crates/backtest/src/run.rs、next_open.rs | 事件协调、真实交易结束与不可伪造完成候选 |
| plugs/onlyalpha-broker-virtual/src/source_host.rs | 迁移旧存储宿主；撮合语义保留，持久接线退出插件 |
| packages/backend/src/application/factor_build.rs（新） | 构建／认证任务、参数绑定、版本可用状态 |
| packages/backend/src/application/job_input.rs（新） | 作业绑定解析、CH 精确加载和预算；不承接所有通用前处理 |
| packages/backend/src/persistence/job_publication.rs（新） | 正式结果成员、唯一发布、终态原子事务与观察 |
| packages/backend/src/persistence/factor_build.rs（新） | 构建程序和参数证书的 PostgreSQL 适配 |
| packages/backend/src/persistence/trading_facts.rs（新） | 持续交易正式事实、outbox 和恢复适配 |
| database/postgres/migrations/0077_factor_program_bindings.sql（新） | 不可变构建程序和精确认证绑定 |
| database/postgres/migrations/0078_job_publication.sql（新） | 正式结果成员／发布与控制关联、权限 |
| database/postgres/migrations/0079_trading_facts.sql（新） | 持续交易事实／投影／派单关联及权限 |

实施开始核对迁移尾号；若主线已有新迁移，顺延以上三个编号，保持其内容职责与顺序，不改已发布字节。新增 Rust 单元测试统一放各库 src/tests/；公开集成测试留各库 tests/；Backend 非默认深层测试必须显式登记 Cargo target。

## 阶段一：收敛公开契约和事实模型

**修改范围**

- docs/runtime_persistence.md、docs/rust-runtime-persistence.md、docs/rust-backtest-replay.md、docs/backtest_result.md、docs/private-factor-authoring.md、docs/manual-backtest-strategy-validation.md。
- crates/calculation、strategy、runtime、backtest 的公开入口与 README；Backend 的 private_assets、strategy_research、backtest_run 模型；相关 Product／Agent API 声明及生成流程。
- ADR 0089／0090／0091 保留历史正文，以 ADR 0151 明确替代条款；不修改 Constitution。

**接口与数据决定**

- `FrozenJobBinding`：Run scope、策略／因子不可变版本、ProgramId／ParameterBindingId、实现工件、初始状态、费用／日历／规则、MarketSliceBinding、ResultPlan；由正式提交 owner 构造，客户端不能自行证明有效。
- `ResultPlan`：正式结果成员种类、类型、逻辑键、轴与成员计数要求；分别列出当前 Research 和 Backtest 的真实消费者需求，不扩大研究统计设计。
- `AttemptClaim` 复用现有 Run／Attempt／Worker／lease／fence；不增加一套并行租约协议。
- 明确 BUILDING／READY／FAILED 属于构建绑定状态，不偷换作业状态。错误分类至少区分缺证、不可读、不匹配、匹配、预算拒绝和提交未知。
- 完成候选只由实际 execution owner 构造；构造函数不公开给传输 DTO。所有阶段以同一冻结绑定计算内容身份。

**步骤与回归**

- [ ] 盘点当前 Result／Freeze／Qualification／Promotion、API、恢复和示例调用方，形成准确迁移映射；临时盘点留任务产物。
- [ ] 先写契约用例：未认证参数不能准入、错误输入绑定不能发布、未发布候选不能定版／晋升、CANCELLED 没有结果。
- [ ] 执行定向测试确认旧实现不能满足新用例，再定义领域类型和更新活动契约；不在测试中伪造 owner 权限。
- [ ] 更新受影响 README／示例／公开类型，检查引用和 Constitution 一致性；按本阶段明确路径提交。

**性能验证**：只确定各 stage 名称、计量边界及分母，盘点已有 bench；不跑旧长取证、不宣称改善。

**独立审查**：核对 ADR 替代范围、身份组成、结果成员清单、纯信号边界和停止条件；若上位契约冲突未闭合，停止受影响实现。

## 阶段二：PostgreSQL 存储、权限和发布原语

**修改范围**：新增 0077／0078 迁移，扩展 persistence/schema.rs、backtest_run.rs、research_runtime.rs；新增 persistence/job_publication.rs、factor_build.rs 及 mod.rs 接线。复用 tokio-postgres，不引入 ORM。

**接口**（Backend 内部，不给纯库带入 PostgreSQL）

- `PublicationRepository::publish(&mut self, claim: &AttemptClaim, candidate: &CompletedJobCandidate) -> Result<PublishOutcome, PublicationError>`（async）。
- `PublicationRepository::observe(&mut self, run: &RunId) -> Result<PublicationObservation, PublicationError>`（async）。
- `PublicationObservation` 区分 Published、ConfirmedUnpublished、Unresolved；ConfirmedUnpublished 必须在相关事务解决后经同一 Run 锁／合法状态检查得到，不能从普通 SELECT 查空构造。
- `PublishOutcome` 区分 Committed、AlreadyPublished（全绑定相同）；冲突或未知不得包装成功。
- `CompletedJobCandidate` 在本阶段使用私有测试 owner 的受控 fixture；生产构造权在阶段五／六真实 owner，仓储不得暴露 bool/hash 绕过入口。
- 结果成员按规范化类型和轴存储，成员 ID／摘要可验证；ResultPlan 与全部成员、唯一发布、Run／Attempt 终态在一事务提交。计算及预编码在事务前，实际插入／校验／锁等待仍计时。
- 普通角色不能 UPDATE／DELETE 正式内容；构建程序不可变。控制状态只走所属领域 CAS；迁移管理员与应用角色分离。

**步骤与回归**

- [ ] 新建 `packages/backend/tests/application/job_publication.rs` 并登记 `application_job_publication` target；对真实测试 PostgreSQL 写原子回滚、同 Run 并发发布、冲突绑定、过期 fence、角色权限测试。
- [ ] 为断连前未发送 COMMIT、服务端提交成功客户端丢响应、事务仍进行中的查询建立受控断点；断言 Unresolved 不能触发重算，事务解决后观察同一发布。
- [ ] 先运行并确认新接口／权限用例失败，再实现仓储和前向迁移；保留现有迁移 checksum／history 检查。
- [ ] 在固定 dev 的 `_test` 数据库执行 `cargo test -p onlyalpha-backend --test application_job_publication`，断言所有测试执行且 PASS；迁移重复执行不改变已发布内容，错误角色仍被拒绝。
- [ ] 记录本阶段变更与受影响权限专项证据，审查通过后按范围提交。

**性能验证**：测预编码、数据库锁等待、成员写入、COMMIT、完整读取；覆盖正常小结果和较多交易／曲线成员。记录行数、字节、事务时间与峰值内存，避免称“大事务必然很短”。若有过大结果，先报告实际预算问题，不隐式拆成多次正式发布。

**独立审查**：重点推导已发布／未发布／未知、唯一约束、不可变角色和 fence 的数据库保证，检查故障注入确实到达目标窗口。

## 阶段三：构建一次的因子程序与精确参数认证

**修改范围**：calculation 新增 program.rs／program_execution.rs，按实际原语依赖接入 operators／indicators；受限 Python 的 private_factor.py、private_factor_execution.py；Backend private_assets/authoring.rs、private_factor_postgres.rs、application/factor_build.rs、persistence/factor_build.rs、workers/trading_program.rs。同步 examples/private-assets/ 真实示例和私有因子文档。

**接口**

- `Program::decode(canonical: &[u8]) -> calculation::Result<Program>`：校验指令、类型、资源界限和 NumericPolicyId，不执行 Python。
- `Program::bind(&self, parameters: &ResolvedParameters) -> calculation::Result<BoundProgram>`：只消费类型已解析的精确参数。
- `ProgramInstance::new(program: Arc<BoundProgram>) -> calculation::Result<ProgramInstance>`；`step(&mut self, input: &ProgramInput) -> calculation::Result<ProgramOutput>`。
- `evaluate_batch(program: &BoundProgram, inputs: &[ProgramInput]) -> calculation::Result<Vec<ProgramOutput>>`；与 step 共享原语、顺序及缺值规则。ProgramInput／Output 和 ResolvedParameters 定义于 calculation，不持有交易账户。
- Python `compile_factor_source(source, interface_version)` 产出严格 canonical typed program；不执行用户字节码。构建身份绑定源码／接口／构建器／数值规范／原语工件；参数证书另绑定 exact 参数。
- `FactorBuildService::request(version, resolved_parameters)` 与 `resolve_ready_binding(version, resolved_parameters)`：前者建立幂等构建／认证作业，后者只读取确切 READY 绑定。版本创建自动请求默认参数；Research 不隐式启动认证。

**步骤与回归**

- [ ] 新建 calculation/src/tests/program_tests.rs、program_execution_tests.rs；Python 对应构建用例；Backend `factor_build` 集成 target。
- [ ] 先写失败用例：precision28/HALF_EVEN/q12、零归一、负数半值、除零、溢出／非法指数、null、warmup、窗口边界；显式区分计算输出规范和资金／数量精度。
- [ ] 增加同前缀 batch/event 逐点相等、后缀不影响前缀、多 Run／instrument 状态隔离、参数 A 证书不能认证 B、程序版本不匹配及恢复状态版本校验。
- [ ] 写 AST 构建计数用例：一次源码构建可供多次运行／参数绑定复用；逐行 step 和作业加载不能触发源码 AST 解析。拒绝 while、可变容器、外部 IO／隐藏状态和未来 Target 输入。
- [ ] 实现 typed 程序和隔离构建接线，迁移正式示例并经过同一导入／校验／执行入口；不扩展任意策略 callback API。
- [ ] 运行 `cargo test -p onlyalpha-calculation`、`cargo test -p onlyalpha-strategy`；数据库认证和隔离 Python 用例经 dev 入口运行；确认真实测试数量及错误断言后提交。

**性能验证**：分别测首次解析／降级、程序 decode／bind、默认与新参数认证、batch／event 执行、滚动窗口状态。bench 输入含 null、长窗口和多实例；记录解析次数、rows/s、ns/row、峰值内存，不用关闭数值校验换速度。

**独立审查**：程序可伪造输入、循环／内存预算、数值 golden、精确认证身份、Python 隔离与示例路径。独立审查至少完成后才向正式 Research 入口开放 READY 绑定。

## 阶段四：共用行情输入准备和前处理职责拆分

**修改范围**：Backend strategy_research/preparation.rs、resolution.rs、execution.rs、workers/research.rs、backtest_service.rs，新增 application/job_input.rs；复用 market-data／market-data-construction 的既有输入身份。数学准备进入 calculation，市场轴规则进入市场模块，权限／数据库仍在 Backend。

**接口**

- `MarketSliceBinding` 复用／组合现有来源、商品、Bar 语义、版本／Seal／segment、轴、行数及规范化内容摘要，不能仅时间范围加行数。
- `JobInputLoader::load(binding: &FrozenJobBinding, budget: &MemoryBudget) -> Result<PreparedJobInput, InputError>`（async）；`PreparedJobInput` 含验证后的有序行情视图和精确程序绑定，只能由 loader 构造。
- `MemoryBudget` 由现有受控配置和声明规模推导；使用检查过的计数／字节计算并在分配前及加载中执行上限；超限结构化拒绝，不 spill 文件／SQLite。
- Research／Backtest 复用同一输入准备；Target 准备独立于信号图。每 Attempt 加载一次正确切片，不在每 Bar 重取全历史。

**步骤与回归**

- [ ] 增补 research_dataset／market_data_storage／source_access 测试：错商品、错版本、同轴内容变更、缺行、重复轴、摘要不符、权限错误、行情不可用均拒绝，不转用最新数据。
- [ ] 对同一 FrozenJobBinding 两次 load 断言规范化内容相等；不同 Attempt 不改变业务身份；内存预算边界和整数溢出均有测试。
- [ ] 先让以上断言在旧接线失败，再按职责迁移真实公共准备，不创建“大基础模块”。消除 Research 中认证／受控案例重复执行，保留实际作业必需输入与输出检查。
- [ ] 经固定 dev 运行相关 PostgreSQL／ClickHouse 集成测试；纯库的轴／规范化测试宿主执行。断言无行情实体重复写 PostgreSQL 后提交。

**性能验证**：单独测 CH 查询、网络读取、解码、排序／轴验证、摘要、程序加载、内存分配。记录 source rows、warmup/sample 分母和峰值；冷／热分别标识，不将 CH 耗时算进交易引擎 rows/s。

**独立审查**：完整性证明是缺失、不可读还是确定不匹配；摘要与事实引用是否来自真实 owner；预算拒绝不产生半受理结果。

## 阶段五：内存 Runtime、完整交易路径和完成候选

**修改范围**：runtime/src/lib.rs、store.rs、readonly.rs、broker_source_store.rs、perpetual_sources.rs及新 session.rs／durability.rs；backtest/src/run.rs、next_open.rs、native_read.rs；virtual broker/source_host.rs；execution 仅修改必要的 owner／port 接口，不为速度改经济规则。

**接口**

- `Session::new(configuration: &RunConfiguration, binding: &RunBinding) -> Result<Session, RuntimeError>`；`Session::apply(&mut self, input: &TradingInput) -> Result<AppliedEvent, RuntimeError>`。配置和输入逐步替换当前宽泛 Value，经济领域类型复用。
- `RunConfiguration`、`RunBinding`、`TradingInput`、`AppliedEvent` 定义／复用于 runtime 的纯领域接口；Backend 将 `FrozenJobBinding` 校验后映射为 `RunBinding`（只含 Kernel 所需的 scope、初始状态和精确执行身份），不让纯库依赖 Backend 类型。共享程序使用 `std::sync::Arc`，不引入新的运行时。
- 当前 typed Components 和 broker owner 常驻；只保留所需紧凑事件／结果投影／幂等键。不再每步读完整持久源或恢复整套组件；不将 SQLite rows 原样换为 Vec<Value>。
- `BacktestRun::finish(self) -> Result<CompletedBacktest, BacktestError>`：验证输入消费、事件和 broker drain、经济不变量、全部 ResultPlan 成员。CompletedBacktest 字段私有，无公开 deserialize／任意构造通道。
- Research 由实际信号执行 owner 产生 `CompletedResearch`；共同纯信号边界沿 strategy 类型。Backend 只能经真实结束和资源回收把它们组装成阶段二的 `CompletedJobCandidate`。
- `AppliedEvent` 内部连接必要幂等身份与紧凑结果，不持有逐 Bar 完整账户 checkpoint。持续 Driver 的提交协议由阶段七接通，阶段五不可据内存状态准许外部提交。

**步骤与回归**

- [ ] 新建 runtime/tests/memory_session.rs、backtest/tests/memory_run.rs；迁移 open_phases／replay 的经济断言为新接口用例，而非只删除旧测试。
- [ ] 先写买卖、拒单、费用、资金／仓位／风险／结算、重复输入一致与冲突输入、OPEN／BAR、drain、失败后不可继续发布用例；沿用可信手算 golden，不以旧文件 bytes 为新格式 oracle。
- [ ] 使用同一程序和输入，对 Research 信号与回测进入资金／风险之前的原始信号逐点比较；交易过滤后的 NO_SIGNAL 不作为比较对象。
- [ ] 实现会话与虚拟券商内存 owner；对 N／2N／4N 输入测每步工作和保存对象数量，验证不存在每步完整历史重建／全量 checkpoint 副本。
- [ ] 运行 runtime、backtest、virtual broker 及实际受影响 execution/account/risk 库回归；缺失完成条件、伪造候选均拒绝，审查后提交。

**性能验证**：release bench 分开报告 signal、admission、apply 分支、撮合／成交／费用／资金／仓位、结果整理；另测包含完整交易流程的总体 bars/s。至少包括无成交、活跃交易、拒单和长输入；经济输出必须相等。观测开关做对照，识别测量开销。

**独立审查**：检查省去的是重复机械恢复而非幂等／风控／经济验证；完成候选不可伪造、内存增长合理、状态丢失不被宣称可续算。

## 阶段六：正式作业、原子结果发布、重算和取消闭环

**修改范围**：workers/research.rs、backtest_worker.rs、backtest_service.rs、backtest_result.rs；persistence/backtest_evidence 和 research_evidence 的活动调用改由 PostgreSQL 内容读取；application/backtest_run.rs、strategy_research.rs；正式 transport 与消费者。

**接口**

- Worker 固定为 claim → resolve READY binding → load exact input → execute → drain/reap → create candidate → publish；中间不持长数据库事务。
- `JobRecovery::resolve(run) -> RecoveryDecision`：AlreadyPublished、RecomputeWithNewClaim、FinishCancellation、WaitForResolution、Refused；必须调用阶段二 observe 并遵循既有重试政策，不能无限重启。
- `ResultReader::read(run, principal) -> Result<PublishedJobResult, ReadError>`：正式权限、成员及 canonical 身份校验；只读 PostgreSQL 结果，不再次执行整段回测。
- 保持既有正式 API 路径的合理职责，直接演进 DTO／状态，生成 Product／Agent 契约和 TypeScript；不增加旧格式读取兼容层。

**步骤与回归**

- [ ] 新建 Backend application/job_recovery.rs、transport/job_publication.rs 并登记 target；在旧 worker接线上先复现缺少结果／错误恢复语义。
- [ ] 故障矩阵覆盖：受理后未运行、加载后、执行中、候选完成后未提交、插入中回滚、COMMIT 未知、已发布但响应丢失、旧 Worker lease 过期后回来。
- [ ] 每个窗口断言原 Run 不变；合法重算的新 Attempt 改变但全部正式经济结果身份／内容相等；缺失旧程序或精确行情明确拒绝。
- [ ] 取消矩阵覆盖准备中、计算中、完成竞争、已完成后取消、无 ACTIVE 恢复取消：CANCELLED 无结果成员／发布，无伪零收益；已发布完成不撤销；未知保持观察路径。
- [ ] 验证多次 GET 返回同一发布、不触发执行；权限隔离、错误归属、错成员／少成员被拒绝；Freeze／Qualification／Promotion 只能引用正式完整发布。
- [ ] 在固定 dev 运行上述真实服务／API 测试及既有研究、准备、回测 owner 场景；控制注入只在内部测试边界，不添加生产绕过 API。完成后提交。

**性能验证**：闭合受理、准备、执行、候选整理、编码、PG 发布、终态观察、GET、后端响应与前端可见耗时。嵌套 span 不相加；明确并行等待，无法归属时间单列。重复 GET 测出内容读取成本且计算调用计数为零。

**独立审查**：逐状态独立推导上述故障窗口和取消线性化；检查完整成员、publication/Run 同事务及 API UNKNOWN 表达。严重／高风险未闭合不得进入正式产品验收。

## 阶段七：持续交易所需持久化和恢复基础

**修改范围**：runtime/durability.rs，backend/persistence/trading_facts.rs及0079迁移、workers/trading_program.rs 和当前实际持续交易 Driver；virtual broker 的持久化接线。仅补退役 SQLite 所必需的共用基础，不宣称交付完整模拟／实盘产品。

**接口**

- `DurableFactPort::commit(&mut self, prepared: &PreparedTradingFacts) -> Result<DurableCommitReceipt, DurabilityError>` 和 `load_recovery(&mut self, binding: &TradingBinding) -> Result<RecoveryFacts, DurabilityError>` 均为 async 方法。PreparedTradingFacts／TradingBinding／RecoveryFacts／DurabilityError 定义于 runtime/durability.rs，组合现有事实类型；port 使用 Rust 原生异步能力，Backend Driver 等待数据库完成，不在纯库引入客户端或 tokio，内存 Session::apply 保持纯同步经济计算。
- `DurableCommitReceipt` 绑定事实身份、计划、版本和提交状态；它本身不是实盘权限。Backend 实际派单入口额外要求私有 `DispatchPermit`，仅由已注册 PostgreSQL 仓储确认正式提交及现有准入授权后构造，不能从任意 port 实现、调用方布尔值／DTO／MemorySession 自动转换。纯库回执与后端正式派单许可分型。
- 正式意图和 outbox 先提交；外部响应／未知／成交按稳定身份幂等记录；committed-unready 恢复原投影。Driver 按 prepare → await commit → 原计划投影／提交资格检查 → dispatch 的顺序接线；不能在同步经济计算中阻塞等待包裹 IO。

**步骤与回归**

- [ ] 新建 Backend `tests/application/trading_facts.rs`，登记 `application_trading_facts` target；Runtime port 的纯状态用例放 src/tests/durability_tests.rs。
- [ ] 先写持久化失败不准派单、提交成功未投影、外部提交结果丢失、重复场所事件、资金事实关联错误、恢复中服务不可用等故障用例。
- [ ] 实现 PG 正式事实与恢复；受控虚拟场所证明重启后原订单被观察而非重新提交，资金／仓位一致；记录实际进程重启与纯对象重建的不同证明范围。
- [ ] 验证内存 backtest receipt 无法进入真实提交授权路径；真实资金／成交事实不能仅留日志或缓存。固定 dev PostgreSQL 回归和独立审查通过后提交。

**性能验证**：分别测正式事实提交、投影、outbox／响应、恢复读取和 typed owner 重建；不将这条逐步持久路径的成本混入内存回测吞吐，也不据虚拟场所测试宣称真实券商通过。

**独立审查**：正式事实归属、不可伪造许可、事务边界、外部未知观察和稳定幂等身份；如现有实际消费者遗漏，SQLite 退役不能放行。

## 阶段八：完整退役和工程工具接线

**修改范围**

- runtime 的 SqliteStore／codec／dictionary_codec／文件 journal／旧 VerifiedReplaySnapshot；backtest 的路径 create/open／旧 Source／native_read 中被替代接口；virtual broker 的 broker.sqlite3。
- crates/runtime/Cargo.toml、plugs/onlyalpha-broker-virtual/Cargo.toml 的生产 rusqlite；crates/backtest/Cargo.toml 的 dev rusqlite；Cargo.lock。
- 当前存储／replay／codec 测试、Backend native host／startup测试，scripts/native_web_e2e.py、rust_kernel_check.py、run_rust_benchmarks.py及其正反测试；Dockerfile.dev、实际 CI 构建调用、活动契约／README／BENCHMARK.md。

**接口**：新测试／bench 消费已完成阶段的 Session、精确输入、正式 PG 发布／恢复接口；彻底移除文件路径作为业务事实读写入口。历史 ADR／调查材料不是执行入口，无需篡改历史描述。

**步骤与回归**

- [ ] 逐项迁移调用方后删除旧实现，不保留 alias／旧 reader／静默 fallback；检查 flate2/base64/zstd 的实际消费者，只删除确已无用的依赖。
- [ ] 对原 SQLite／journal 测试逐项标注由哪个新经济、PG 发布或持续恢复用例承接，不用跳过测试消除失败。
- [ ] 门禁增加 alias 和传递 SQLite 依赖拒绝用例、合法纯 Rust／PG 接线通过用例；只移除 SQLite 旧豁免，不弱化无关 C／Zstd 隔离规则。
- [ ] 执行 `cargo tree --workspace --all-targets`，结构化检查 rusqlite／libsqlite3-sys 不可达；并搜索 sqlite／broker.jsonl／旧 Source API 的活动消费者，逐条区分历史文本与实际接线。
- [ ] 运行 `python3.12 scripts/rust_kernel_check.py --source-check`、相关 scripts/tests，固定 dev 编译实际后端／虚拟券商／镜像入口；文档引用和 benchmark inventory 一致后提交。

**性能验证**：旧 retained／recovery／backtest_chain 样本改为新内存、PG正式事实恢复和结果读取三种明确口径；旧SQLite产物不作新 bench 隐含输入，不使用其测量条件声称改进。

**独立审查**：全产品搜索与依赖树双重检查；确保不是只删 runtime 而遗漏虚拟券商、dev依赖、脚本或部署路径。

## 阶段九：正式回归、性能实战和最终审查

**修改范围**：受影响 Product／Agent契约与生成类型、正常 Web 页面／状态处理；frontend/e2e/private-factor-authoring.spec.ts、research.spec.ts、backtest.spec.ts、backtest-diagnostics.spec.ts；各库 benches／BENCHMARK.md，Backend benches/backtest_chain，test-data/backtest-benchmarks/inventory.json 和工程观测工具。

**步骤与回归**

- [ ] 冻结最终源码、有效配置、依赖与镜像身份到固定 dev 验证；先核对磁盘、内存、服务健康、生命周期锁与无并行共享测试。
- [ ] 分层执行纯 Rust、Python 构建／脚本、真实 PostgreSQL／ClickHouse、正式 API 及正常 Web 流程；每层报告实际场景／数量与未覆盖项。
- [ ] Web 经正常导航完成：导入／编写因子→版本构建→READY参数→Research→策略定版→回测→结果；另验证新参数未就绪、取消无部分结果、失败／未知可继续观察和刷新后状态。不得用直接请求／数据库改写代替这些用户步骤。
- [ ] Product OpenAPI code-first 导出并运行 `python3.12 scripts/openapi_contract.py check`；同步 Agent schema／TypeScript 调用方并验证实际服务响应，不以生成通过替代权限／流程测试。
- [ ] 正常 Playwright 用固定入口执行：`python3.12 scripts/dev_verification.py --web run -- npm run e2e -- e2e/private-factor-authoring.spec.ts e2e/research.spec.ts e2e/backtest.spec.ts e2e/backtest-diagnostics.spec.ts`。前置 prepare 和源码投影按现有 dev_verification 流程显式完成；不盲目重复清库。
- [ ] 执行下述性能矩阵并生成原始样本／完整链路报告；将原回测慢点逐一对应为已去除机制、新机制实际成本或仍未解释项，不重复宣称旧 Witness 唯一物理根因已证实。
- [ ] 由未实现相应代码的审查者检查最终固定 diff、正式规范与原始证据；严重／高风险项修复后重跑直接相关回归，再交付最终结论。

**性能矩阵**

| 层级 | 样本与计量 | 必需记录 |
|---|---|---|
| 数学／因子／信号 | 现有受影响库 workload；新程序首次构建、加载、batch、event | 参数／原语版本、解析次数、ns/row、rows/s、null／warmup |
| 完整交易 | 无成交、活跃交易、拒单、多商品和 N／2N／4N | bars/s、订单／成交数、各组件耗时、结果摘要、峰值内存 |
| 输入准备 | 精确 CH 切片，冷／热标明 | 查询／解码／轴验证／摘要／加载耗时、行数／字节 |
| PostgreSQL | 多结果规模，发布、读取、持续事实恢复 | 编码／锁等待／插入／COMMIT／查询分时及总耗时 |
| 产品全链路 | 正式 API／正常 Web 工作流及响应 | 受理→准备→执行→候选→发布→终态→浏览器可见 |
| 观测影响 | 同一 release 工件 detail off/on | 数据损失、IO失败、span父子完整性及开关开销 |

每组记录代码SHA／工作树摘要、机器／OS／容器资源、rustc与release配置、数据身份、缓存条件、内存预算和样本数。首次预热单列，常规测量至少三次并报告中位数和范围；长作业次数不得突破已授权预算，预算不足报告证据缺口，不扩展运行。N／2N／4N 选择在已有受控输入和资源预算内，不凭空提高数据量。

各模块 BENCHMARK.md 维护职责、命令、输入、分母、环境、最近有效样本和解释限制；原始样本留 test-results，不把 CI 快照写成规范。全链路报告用排他耗时／等待解释总墙钟时间，嵌套 span 不累加；未闭合时间明确列出。不新增100根/秒硬门槛，也不放宽既有300/120秒验收门槛。

**最终独立审查交付**：范围与固定 diff 身份、规范推导、问题分级、已验证／未验证证据、正式事实与恢复审查、性能结论有效范围。审查通过不能替代没跑的 Web／真实服务场景，启动成功不能替代终态发布与恢复通过。

## 统一验证命令与使用规则

以下是实施时的命令约定，本计划编写期间没有执行这些业务验证。

```bash
# 无外部服务的库：按阶段只跑受影响集合；阶段九汇总
cargo test -p onlyalpha-calculation -p onlyalpha-strategy
cargo test -p onlyalpha-runtime -p onlyalpha-backtest -p onlyalpha-broker-virtual

# 数据库／应用：新增 targets 在其阶段先登记到 Cargo.toml
python3.12 scripts/dev_verification.py run -- cargo test -p onlyalpha-backend --test application_job_publication
python3.12 scripts/dev_verification.py run -- cargo test -p onlyalpha-backend --test application_trading_facts

# 结构与受影响契约
python3.12 scripts/rust_kernel_check.py --source-check
python3.12 scripts/dev_verification.py run -- python3 scripts/openapi_contract.py check

# 模块 bench：先同步阶段八的新 inventory；输出目录必须为未存在的新目录
python3.12 scripts/dev_verification.py run -- python3 scripts/run_rust_benchmarks.py check --crate calculation --output test-results/framework-bench-calculation-check
python3.12 scripts/dev_verification.py run -- python3 scripts/run_rust_benchmarks.py reference --crate calculation --output test-results/framework-bench-calculation-reference
```

Python 旧测试若依赖已退役实现，按上述新 Rust／真实API用例迁移，不机械跑不存在的旧路径。命令失败先看明确失败，不用 sleep／重试循环／吞异常制造通过。Clippy、格式、依赖／边界检查按实际修改范围执行；公开API变更必须补相应正式入口场景。

## 收尾、阶段审查和范围控制

- 每阶段结束：列明实际修改、接口变化、已运行回归、性能证据、独立审查状态和剩余问题；这些记录留当前任务或 test-results，不新增进度 Authority。
- 阶段二／三／五／六／七／八的高风险接口或权限变更取得独立审查后才开放下一条正式生产接线。相邻阶段可合并一次明确覆盖的审查，不能以“最后会看”跳过当前风险。
- 最终再进行一次全差异独立审查，重点找跨阶段身份／状态遗漏。当前默认由本会话执行者实现，审查任务只读委托独立审查者；不自动启动多个修改同一工作树的实现代理。
- 已有未提交代码为受保护基线；先核对 checkpoint 和本次差异，定向暂存；不随计划编写提交／推送既有181个源文件，也不删除调查原始材料。
- 性能实战用于检验本框架设计及定位剩余成本；额外优化、数值重排、降低完整性、缓存正式判断、原任务第二阶段优化均不自动纳入。
- 不做新的信号—收益方法、任意策略编程接口、完整模拟／实盘产品、真实券商实盘验收、历史兼容和全局Docker清理。
- 若新依赖／部署能力确有必要，先提交需求覆盖、复用替代、维护许可安全成本对比，等待负责人确认该增量；其余已授权工作继续。
- 只有实际代码、受影响回归、性能样本和独立审查全部满足已确认设计，才能声明框架完成；缺失的正式 Web、恢复或服务证据单列未完成。

## 计划自检

已对照设计核对：存储归属（二／四／七）、纯信号与前处理（三／四／五）、构建与精确认证（三）、内存经济执行（五）、同Run重算／取消／未知与原子发布（二／六）、SQLite全退役（八）、固定环境／真实产品／性能与独立审查（九）。Review Focus 五项均有明确用例。新接口名在消费阶段沿用；新签名中的领域数据类型由对应阶段负责定义，现有身份／错误优先复用，不创建并行Authority。

此处是计划覆盖检查，不是已执行的测试或独立审查结论。
