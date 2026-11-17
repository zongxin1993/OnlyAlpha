# OnlyAlpha Backend

## 目的与职责

后端承接正式API、权限、业务生命周期、持久化和受控作业；不将浏览器或Agent变为交易Authority。

## 边界与依赖

进程和数据库接线归后端，纯计算和交易语义由crates所属库负责。实际依赖见[Cargo.toml](Cargo.toml)；架构见[仓库说明](../../docs/repository-product-architecture.md)。

## 公开接口

入口见[src/lib.rs](src/lib.rs)和[src/main.rs](src/main.rs)。[application::job_contract](src/application/job_contract.rs)提供FrozenJobBinding、FactorExecutionBinding、ResultPlan及状态一致谓词；输入是有界类型化记录，输出规范化值／身份或错误，不授予认证、准入、发布或LIVE权限。持久化原语见[persistence::job_publication](src/persistence/job_publication.rs)和[persistence::factor_build](src/persistence/factor_build.rs)，提供不可变构建内容、精确参数引用、原 Run／Attempt 原子发布、完整读取与未知结果观察。输入为所属 owner 的私有令牌，输出已验证存储内容或明确错误；不接受外部 DTO 作为完成许可。实际角色、事务、预算和阶段边界见[PostgreSQL 发布说明](../../docs/postgresql-job-publication.md)，有限作业完成 owner 尚未接线。因子构建由 [application::factor_build](src/application/factor_build.rs) 和 [后台构建服务](src/workers/factor_build.rs) 持有，完整 Research／Backtest 作业接线属于后续阶段。正式HTTP接口由transport code-first声明及contracts管理。

## 状态与生命周期

[`application::job_input`](src/application/job_input.rs) 提供 `JobInputLoader::load`、`MemoryBudget` 和私有构造的 `PreparedJobInput`，从精确 Revision／Seal／segment 的真实 PostgreSQL／ClickHouse 所属读路径准备有序 Bar，并读取精确 READY 程序。输入必须携带原主体的有效 Source Session，禁止用冻结 JSON 授予读取权限。错误分别表达预算、权限、缺证、不可用、未知、不匹配及未就绪。加载不写行情副本、过程文件或结果，也不创建 Run。当前正式有限作业派发仍按后续阶段接线；旧 Research／回测先共享行情轴校验和现有 Dataset 身份算法。

[`workers::research_environment::prepare_strategy`](src/workers/research_environment.rs) 仅核验实际安装的 Core、原生算子和 Target 库，不接收因子源码、不认证私有因子。后者由 `FactorBuildService` 独立构建认证，`resolve_frozen_binding` 只读核对精确证书，不能隐式构建或换用最新版本。

[`Composer`](src/persistence/strategy_research.rs) 与 [`ResolvedCalculations`](src/application/strategy_research/resolution.rs) 从 PostgreSQL 的精确 READY 程序、每实例参数证书和资产元数据准备原生信号图，不依赖 Runtime 私有因子注册。原生信号和隔离 Target 进程分别记录执行归属。历史授权／验证读取按原 PostgreSQL 构建事实及原工件身份重推节点，不取得当前执行资格。Research Evidence 与 Backtest 原读取器仅从已核验的原 Run／历史 cut 索引私有因子完整实现正文；内置节点继续核对 Runtime inventory，索引本身不授予执行资格。缺证、数据库不可用、UNKNOWN 和确定不匹配分别返回。

Command、Run、Attempt及恢复各有唯一owner；新框架值／事实关系见[有限作业契约](../../docs/job-execution-contract.md)。不能用值解析、hash或日志代替真实执行与正式发布。当前实现状态与目标架构分别说明。

[`application::calculation_build`](src/application/calculation_build.rs) 将精确图的受控证明作为独立构建事实保存在 PostgreSQL；构建绑定固定参数、实际实现与工件，以及固定合成语料，不绑定作业时间或 Target。`PreparedInputs::prepare_strategy` 执行明确的构建准备，`restore_strategy_inputs`／恢复仅加载原证明，缺证不修复。Research 实际观测与手工策略验证引用同一证明；正式读取重新核对 PostgreSQL 原事实、六类案例和逐节点 Witness，证明本身不授予 Run、Freeze 或交易权限。实际行情正文仍归 ClickHouse，合成认证语料不冒充行情事实。

[`application::finite_job`](src/application/finite_job.rs) 提供有限执行 owner：`start_research` 重新核对原 Run、PostgreSQL 构建／组合事实和实际输入；`prepare_backtest` 保留原准入与工件 cut，`PreparedBacktestJob::start` 校验冻结绑定后启动内存交易。内部创建并等待实际执行任务，Research 的 Target 子进程还须正向回收，才能生成私有字段的 `CompletedJobCandidate`。候选保留完整成员、正文轴／计数、原始信号、完整经济结果及实际因果关联，不能用任意 JoinHandle、完成布尔值或 JSON 构造。

`PreparedBacktestJob::factor_bindings` 仅导出原证明中的精确输入描述，用于规划冻结输入；`JobInputLoader` 仍须独立读取 PostgreSQL 核验 READY。重复实例按 revision／参数组合保留证书关联，不能用因子 ID 合并不同参数。候选错误保留 UNKNOWN 的原 Control／回收句柄，并区分取消、预算和内容不匹配。有限 Research 的计算列与统计输入来自实际 native batch 完成对象；共用纯策略的 event 信号参考单独记录 TRADING 来源，两者不互相重标。

`member_schema`、`fact_axis_rule`、`plan_members` 和两类 execution_values 是纯值规划接口，不授予执行或发布权限。行情轴沿既有五列身份；执行事实按实际 sequence／family／正文摘要重算轴，分区为逻辑键排序后的连续均衡切片。计算／信号／统计成员保存实际类型输出和 NULL，报告引用实际成员，因果根引用全部其他成员，避免摘要自引用。未发布候选不是正式完成事实；第五阶段不连接正式 worker／API／ResultReader 或新终态事务，Run／Attempt 的发布与取消竞争由后续阶段接通。

## 使用与验证

数据库／应用验证经固定onlyalpha-dev及scripts/dev_verification.py。第一阶段纯契约定向命令为`cargo test -p onlyalpha-backend --lib job_contract_tests`，使用现有compiler_environment／冻结源码执行；不要求访问数据库。完整回归范围按任务影响选择。

第二阶段真实数据库回归使用独立目标 `cargo test --frozen --offline -p onlyalpha-backend --test application_job_publication -- --test-threads=1`；仅允许固定开发环境中的 `onlyalpha_dev_validation_test`。合成发布性能矩阵须显式 release／ignored 执行，见[BENCHMARK.md](BENCHMARK.md)。它不证明完整回测性能。

### 因子构建连接

后端启动必须显式配置 `ONLYALPHA_FACTOR_BUILD_POSTGRES_DSN`。它与主连接指向相同数据库／传输环境，使用只属于 `onlyalpha_factor_builder` 的普通 LOGIN；不能传迁移管理员再 SET ROLE。迁移完成后，由操作者在固定开发环境显式运行 `python -m scripts.factor_build_database` 建立已确认归属的开发 builder 登录角色。脚本不修改业务数据，不在普通后端启动时自动执行，不覆盖未知角色或轮换已有密码。正式环境由部署方提供独立凭据。测试 fixture 仅在 `_test` 数据库准备自己的角色。

不可变版本创建的默认请求由 PG 触发器记录，现有后端进程自动消费；唤醒和 watch 状态只是提示，READY 必须由 owning reader 完整读取 PG 构建／精确参数证书获得。后台构建的数据库连接、隔离子进程和关闭 join 由 owner 持有；源码编译器不接触数据库凭据。

Runtime 准备的安装复核、发布工件读取、native 清单、子进程创建／握手／准备／回收和结束复核使用既有 `onlyalpha-observability` 阶段事件。受控探针可通过 `ONLYALPHA_RUNTIME_PREPARATION_DIAGNOSTICS=1` 显式选择局部诊断会话，入口计时覆盖 Tokio、建连和请求解析；事件只写诊断 stderr，不进入正式结果、身份或发布记录，原校验与超时不变。
