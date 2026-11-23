# OnlyAlpha Backend

## 目的与职责

后端承接正式API、权限、业务生命周期、持久化和受控作业；不将浏览器或Agent变为交易Authority。

## 边界与依赖

进程和数据库接线归后端，纯计算和交易语义由crates所属库负责。实际依赖见[Cargo.toml](Cargo.toml)；架构见[仓库说明](../../docs/repository-product-architecture.md)。

## 公开接口

入口见[src/lib.rs](src/lib.rs)和[src/main.rs](src/main.rs)。[application::job_contract](src/application/job_contract.rs)提供FrozenJobBinding、FactorExecutionBinding、ResultPlan及状态一致谓词；输入是有界类型化记录，输出规范化值／身份或错误，不授予认证、准入、发布或LIVE权限。持久化原语见[persistence::job_publication](src/persistence/job_publication.rs)和[persistence::factor_build](src/persistence/factor_build.rs)，提供不可变构建内容、精确参数引用、原 Run／Attempt 原子发布、完整读取与未知结果观察。输入为所属 owner 的私有令牌，输出已验证存储内容或明确错误；不接受外部 DTO 作为完成许可。实际角色、事务、预算和阶段边界见[PostgreSQL 发布说明](../../docs/postgresql-job-publication.md)，有限 Research 的单 Run 协调见 [finite_research](src/workers/finite_research.rs)。因子构建由 [application::factor_build](src/application/factor_build.rs) 和 [后台构建服务](src/workers/factor_build.rs) 持有，Research 调度经精确输入、实际 join 和同会话 PG 发布；Backtest 的旧生产者与结果读取仍有文件 owner，不能视为同一条有限内存链路。正式HTTP接口由transport code-first声明及contracts管理。

## 状态与生命周期

[`JobRecovery`](src/application/job_recovery.rs) 从原 Run 的真实发布观察区分已发布、等待、无发布重算、取消和拒绝。它不创建 Claim；拒绝分支仍保留原未发布证明，供原 Run 的终结 CAS 复核。`Backtests::claim_recompute` 在原 Run 锁内复核冻结绑定、版本、状态、发布不存在、Attempt 与 ACTIVE 数量；[`ResearchExecution::claim_recompute`](src/persistence/research_execution.rs) 持有原 `AuthoritySession`，先在同一物理连接上观察发布，再在原 Run 锁内复核该观察、精确绑定与 Attempt，执行延迟约束和完整读回后提交；有限 Research／Backtest 自动恢复最多 3 次 Attempt，预算不进入经济身份。旧观察及取消状态不能授予新内存重算。

[`application::job_input`](src/application/job_input.rs) 提供 `JobInputLoader::load`、`MemoryBudget` 和私有构造的 `PreparedJobInput`，从精确 Revision／Seal／segment 的真实 PostgreSQL／ClickHouse 所属读路径准备有序 Bar，并读取精确 READY 程序。输入必须携带原主体的有效 Source Session，禁止用冻结 JSON 授予读取权限。错误分别表达预算、权限、缺证、不可用、未知、不匹配及未就绪。加载不写行情副本、过程文件或结果，也不创建 Run。正式策略 Research 通过准备任务持有这些输入，再交给有限执行 owner；行情轴校验和 Dataset 身份算法沿用共用实现。

[`workers::research_environment::prepare_strategy`](src/workers/research_environment.rs) 仅核验实际安装的 Core、原生算子和 Target 库，不接收因子源码、不认证私有因子。后者由 `FactorBuildService` 独立构建认证，`resolve_frozen_binding` 只读核对精确证书，不能隐式构建或换用最新版本。 精确参数证书的 `execution_metadata` 仅保存执行所需的身份、版本、API 与输入输出声明，绑定同一不可变因子版本和程序；不携带源码或作者注释。执行 reader 无须读取源码表，声明字节计入原有证书读取预算；缺失或错误声明直接拒绝，不兼容补读。

[`Composer`](src/persistence/strategy_research.rs) 与 [`ResolvedCalculations`](src/application/strategy_research/resolution.rs) 从 PostgreSQL 的精确 READY 程序、每实例参数证书和资产元数据准备原生信号图，不依赖 Runtime 私有因子注册。原生信号和隔离 Target 进程分别记录执行归属。历史授权／验证读取按原 PostgreSQL 构建事实及原工件身份重推节点，不取得当前执行资格。Research Evidence 与 Backtest 原读取器仅从已核验的原 Run／历史 cut 索引私有因子完整实现正文；内置节点继续核对 Runtime inventory，索引本身不授予执行资格。缺证、数据库不可用、UNKNOWN 和确定不匹配分别返回。

Command、Run、Attempt及恢复各有唯一owner；新框架值／事实关系见[有限作业契约](../../docs/job-execution-contract.md)。不能用值解析、hash或日志代替真实执行与正式发布。当前实现状态与目标架构分别说明。

[`application::calculation_build`](src/application/calculation_build.rs) 将精确图的受控证明作为独立构建事实保存在 PostgreSQL；构建绑定固定参数、实际实现与工件，以及固定合成语料，不绑定作业时间或 Target。`PreparedInputs::prepare_strategy` 执行明确的构建准备，`restore_strategy_inputs`／恢复仅加载原证明，缺证不修复。Research 实际观测与手工策略验证引用同一证明；正式读取重新核对 PostgreSQL 原事实、六类案例和逐节点 Witness，证明本身不授予 Run、Freeze 或交易权限。实际行情正文仍归 ClickHouse，合成认证语料不冒充行情事实。

[`application::finite_job`](src/application/finite_job.rs) 提供有限执行 owner：`start_research` 重新核对原 Run、PostgreSQL 构建／组合事实和实际输入；`prepare_backtest` 保留原准入与工件 cut，`PreparedBacktestJob::start` 校验冻结绑定后启动内存交易。内部创建并等待实际执行任务，Research 的 Target 子进程还须正向回收，才能生成私有字段的 `CompletedJobCandidate`。候选保留完整成员、正文轴／计数、原始信号、完整经济结果及实际因果关联，不能用任意 JoinHandle、完成布尔值或 JSON 构造。

`PreparedBacktestJob::factor_bindings` 仅导出原证明中的精确输入描述，用于规划冻结输入；`JobInputLoader` 仍须独立读取 PostgreSQL 核验 READY。重复实例按 revision／参数组合保留证书关联，不能用因子 ID 合并不同参数。候选错误保留 UNKNOWN 的原 Control／回收句柄，并区分取消、预算和内容不匹配。有限 Research 的计算列与统计输入来自实际 native batch 完成对象；共用纯策略的 event 信号参考单独记录 TRADING 来源，两者不互相重标。

`member_schema`、`fact_axis_rule`、`plan_members` 和两类 execution_values 是纯值规划接口，不授予执行或发布权限。行情轴沿既有五列身份；执行事实按实际 sequence／family／正文摘要重算轴，分区为逻辑键排序后的连续均衡切片。计算／信号／统计成员保存实际类型输出和 NULL，报告引用实际成员，因果根引用全部其他成员，避免摘要自引用。未发布候选不是正式完成事实；第五阶段不连接正式 worker／API／ResultReader 或新终态事务，Run／Attempt 的发布与取消竞争由后续阶段接通。

## 使用与验证

数据库／应用验证经固定onlyalpha-dev及scripts/dev_verification.py。第一阶段纯契约定向命令为`cargo test -p onlyalpha-backend --lib job_contract_tests`，使用现有compiler_environment／冻结源码执行；不要求访问数据库。完整回归范围按任务影响选择。

真实数据库回归使用独立目标 `cargo test --release --frozen --offline -p onlyalpha-backend --test application_job_publication -- --test-threads=1`；仅允许固定开发环境中的 `onlyalpha_dev_validation_test`。实际构建场景校验当前 ELF 的原有大小等准入条件，不能用超限 debug 工件代替。合成发布性能矩阵须显式 release／ignored 执行，见[BENCHMARK.md](BENCHMARK.md)。它不证明完整回测性能。

### Node 控制连接

有限输入由 `JobInputLoader` 保留实际签发的 Source Session 与精确 Selection；`PreparedJobInput::require_source_access` 只复核同一读取授权，不刷新会话，也不授予交易执行权限。Research 与 Backtest 的有限计算 owner 在创建实际执行任务前再次复核，避免准备阶段的异步等待跨过撤销；会话不进入冻结绑定或结果内容。

正式 Host 的 `ONLYALPHA_POSTGRES_DSN` 必须是普通 Node LOGIN，`ONLYALPHA_NATIVE_POSTGRES_USER` 与实际用户一致。迁移后由操作者显式运行 `python -m scripts.node_database` 准备已确认归属的开发账户；测试使用 `--test` 和受控数据库。Node 仅默认继承控制权限，在原物理 AuthoritySession 内切换 reader／publisher，不能另开发布写连接。启动与显式运维共用 [只读权限策略](src/persistence/node_access.sql)，不自动授权或修复污染；取消和角色恢复失败撤销原连接。迁移管理员不作为正式 Host 账户。

### 因子构建连接

后端启动必须显式配置 `ONLYALPHA_FACTOR_BUILD_POSTGRES_DSN`。它与主连接指向相同数据库／传输环境，使用只属于 `onlyalpha_factor_builder` 的普通 LOGIN；不能传迁移管理员再 SET ROLE。迁移完成后，由操作者在固定开发环境显式运行 `python -m scripts.factor_build_database` 建立已确认归属的开发 builder 登录角色。脚本不修改业务数据，不在普通后端启动时自动执行，不覆盖未知角色或轮换已有密码。正式环境由部署方提供独立凭据。测试 fixture 仅在 `_test` 数据库准备自己的角色。

不可变版本创建的默认请求由 PG 触发器记录，现有后端进程自动消费；唤醒和 watch 状态只是提示，READY 必须由 owning reader 完整读取 PG 构建／精确参数证书获得。后台构建的数据库连接、隔离子进程和关闭 join 由 owner 持有；源码编译器不接触数据库凭据。

Research 的原受理 authorization 同时保留真实 `Context.selection` 的 integration、revision、type、Source 和 environment；单因子、策略 Research 和不经过 preparation 的正式受理入口使用相同规则。它与原 actor、Command、Run 和 authorization 指纹一起读取，不作为当前访问授权。旧记录缺少该选择时明确拒绝，不查询最新 preparation、不从配置猜测或补写。幂等重放仍先读取原受理事实，不用新选择覆盖原记录。

正式 Research／Backtest worker 的 Source 会话由原 Host 的弱引用提供器取得，不创建第二个 issuer。已发布／取消的恢复观察先于新的输入访问；每次新加载固定使用一次取得的真实会话，并在实际计算交接前重新检查同一会话。Host 消失或原会话撤销时拒绝新输入访问，不回退到冻结 JSON 或默认权限。

`AttemptExecutionBinding::capture` 只从真实 `AttemptClaim` 复制操作关联，在异步输入准备前完成；字段私有且不能从 JSON 构造，不授予新 Claim、Source 或发布权限。`finite_job::start_research_claimed` 接收该关联与真实输入 owner，避免准备期间借用 Claim 而阻塞心跳；`PublicationRepository::publish_guarded` 只在原 AuthoritySession 的临时 publisher 作用域中发布真实 joined 候选，失败或未知撤销原连接，不创建第二条写连接。

Research 完成态的计算执行引用绑定同次 PG 发布的真实因果证据成员，不引用临时文件或伪造的旧报告。publisher 在原终态事务中写入排序后的成员摘要；SQL 延迟约束和完整读取器共同核对该精确集合，控制连接不能写这列。

`research_admission::restore_finite` 消费原 `VerifiedRun`、实际 Runtime hold／SDK 安装和 `JobInputLoader` 签发的真实行情与 READY 输入，恢复完全相同的准备记录及实际程序 owner，不读取旧 Dataset 过程文件、不补建认证。它不授予执行；有限执行 owner 仍在计算交接前核对原 PostgreSQL 组合、构建证明、输入与同一 Source 会话。

有限 Research 创建执行任务前，Composer 除核对原 Run、准入与准备记录，还必须读取原 PG 冻结绑定并逐字段比较完整绑定，结果计划也在其中。纯值描述、实际行情可读或相同 Claim 不能替代这次核对；缺证、不可读、未知和确定偏移分别拒绝。

精确参数证书中的 `execution_metadata` 只保存执行必需的因子身份、语义版本、API 和输入／参数／输出声明，不包含源码和编写说明。构建者先验证完整不可变版本；执行 reader 验证原证书及声明与程序的绑定，不读取源码表，也不重复解析 AST。

Runtime 准备的安装复核、发布工件读取、native 清单、子进程创建／握手／准备／回收和结束复核使用既有 `onlyalpha-observability` 阶段事件。受控探针可通过 `ONLYALPHA_RUNTIME_PREPARATION_DIAGNOSTICS=1` 显式选择局部诊断会话，入口计时覆盖 Tokio、建连和请求解析；事件只写诊断 stderr，不进入正式结果、身份或发布记录，原校验与超时不变。

[`FiniteTask::drain`](src/application/finite_job/owners.rs) 保留并等待同一个实际执行任务，只有子进程已确认回收时才能生成 `DrainedFiniteJob`；凭据保留原输入 owner、冻结绑定和执行 Attempt 关联。停止失败或回收未知时保留原错误及回收 owner。`ResearchExecution::cancel_finite_guarded` 消费该凭据，在原 AuthoritySession／Run 锁下核对完整关联和未发布状态，再完成健康 ACTIVE Claim 的取消。

[`ResearchExecution`](src/persistence/research_execution.rs) 的 `heartbeat_guarded` 在原连接确认完成前保持 Claim 不确定，提交前执行 deferred constraints 并复核 guard。`recover_finite_guarded` 先观察 PostgreSQL 发布；过期只结束原 Attempt 的操作所有权，随后以新的无发布证明处理无 ACTIVE 的取消或三次 Attempt 耗尽。该恢复入口无需 Source 会话、行情加载或算法准备；不可读与未知不会授权重算，重复观察保留原 Run 和终态。

正式策略 Research 报告由 [`transport::job_publication`](src/transport/job_publication.rs) 在现有只读连接中读取完整 PostgreSQL 发布，核对原 Run、主体、规格、准入、报告正文、绑定和输入窗口后投影。读取不恢复行情、执行策略或访问旧结果目录；缺证、不可读、确定不匹配和未知保留不同错误码。`result.research.read` 与 `result.research.project` 分别记录读取和投影耗时。

[`PreparationTask`](src/application/finite_job/research_preparation.rs) 持有同一准备任务及取消通道；只有实际任务结束且没有创建执行任务，才能产生私有 `AbortedPreparation`。准备完成后，协调器持续等待同一个执行任务并保留原 reaper；取消或控制所有权丢失不会丢弃 join future，也不会借用长事务包围计算。

[`ResearchPublication`](src/persistence/research_evidence/publication.rs) 从完整 PG 发布、原 `VerifiedRun`、报告和因果证据重建只读的策略研究 owner。它核对 Source／信号图、原构建证书、实际 join 标记、执行镜像和成员精确引用；不接受原始 JSON、重新构建证明或访问文件 Evidence。报告投影与后续 Freeze 消费者共用这层核验，写入消费者仍需在自己的原事务中复核当前正式事实。
