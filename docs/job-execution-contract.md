# 有限作业的冻结身份、结果计划与接口

本契约落实[ADR 0151](adr/0151-postgresql-business-publication-and-memory-work.md)，约束 Research／Backtest 的新框架。实现入口为 Backend [`application::job_contract`](../packages/backend/src/application/job_contract.rs)。纯值模型之外，第二阶段已提供 PostgreSQL 类型化内容仓储与原子发布原语，见[存储接口说明](postgresql-job-publication.md)；真实构建／结束 owner 和外部 API 尚未接线。旧 worker 尚未迁移，不以其行为推翻本契约，也不宣称目标已经运行。

## 事实归属和权限

PostgreSQL 拥有资产版本、构建程序／认证、Command／Run／Attempt／租约／取消及正式结果。ClickHouse 拥有 K 线及其精确版本。有限作业内存保存计算状态和未发布过程；持续交易正式意图、场所观察、成交、资金及因果事实逐步写 PostgreSQL。

数据模型只能表达引用和检查值。`FrozenJobBinding::from_record`、`FactorExecutionBinding::check_certificate` 和 `ResultPlan::check_inventory` 均不产生认证、数据源访问、发布、定版、晋升或实盘许可。调用方提供的 READY、boolean、hash 和 JSON 不能代替所属 owner 的真实证明。运行角色不能直接通过写数据库绕过正式命令。

## 冻结身份

`FrozenJobBinding` schema1 使用现有 canonical JSON fingerprint 算法，身份字段包括：

| 字段 | 含义 |
|---|---|
| kind | RESEARCH／BACKTEST 有限作业类别，不是新的 Runtime 经济模式 |
| scope.namespace／owner／run_id | 原语义数据库 UUID4、原所有者、原 Run UUID4；复用既有身份语言 |
| strategy_revision／signal_graph | 不可变策略版本及共同纯信号图 |
| factor_bindings | 各版本、程序、解析后精确参数、数值规范及精确认证引用 |
| kernel_artifact／runtime_generation | 实际 Kernel 工件和既有 Generation 绑定 |
| initial_state／execution_configuration | 完整初始状态及执行配置的确切内容引用 |
| calendar／fees／market_rules | 影响结果的日历、费用、规则绑定；不从当前最新环境推断 |
| market | 原 Dataset snapshot、source revision、Bar 语义、商品集合、时间范围、版本／Seal／segment、轴、行数和内容摘要 |
| result_plan | 下文完整正式结果成员的声明 |

已有 Dataset／Source／策略版本指纹保持其所属算法，本模型只组合引用，不重新铸造这些事实身份。除已有 UUID4 身份外，摘要采用64位小写十六进制。引用完整性、真实内容和访问权限仍须 owning reader 验证，格式正确不是真实性证明。

每份绑定最多256 KiB；成员／引用列表各至多1024项，超限明确拒绝。版本、Seal、segment、商品以及成员集合按规范顺序编码，重复键拒绝；行情内容的时间顺序由 axis／content 精确绑定，不用集合排序重新排列事件。时间为 i64 纳秒，start < end；row_count = warmup_rows + sample_rows，使用检查加法，首版 sample_rows > 0。

Run 属业务 scope，不能随重试替换。Attempt、lease、fence、PID、主机、耗时和审计时间属于控制／观察；它们不进入该经济绑定。新 Attempt 必须加载原绑定引用的确切工件及输入，不能升级版本或替换 K 线。未知字段拒绝，不能借扩展 JSON 偷带隐藏输入。

## 构建身份和参数认证

共同信号只依赖行情、因子、显式参数；不读仓位／资金／风控／成交。后续交易环节消费信号并负责这些状态。Research batch 与 event 使用同一语义程序，不比较经过交易过滤后的 NO_SIGNAL。

构建身份绑定源码、编写接口、构建器、类型程序、原语实现和数值规范；精确参数绑定身份独立。`FactorExecutionBinding` 引用 revision／program／parameters／numeric_policy／certificate。parameters 指向现有参数解析器按类型、默认值和约束解析后的完整规范化内容，不能把未解析的用户 JSON 或展示格式当成精确参数。

BUILDING／READY／FAILED 仅表示这个精确认证绑定的状态，不是整个参数域或作业状态。READY 且所有绑定相同才满足值一致谓词；真实证书存在、签发 owner、程序内容、关联和状态由 PostgreSQL owning reader 在准入时验证。版本创建自动构建并认证默认参数；新参数只做绑定和受影响认证，同一程序不逐行解析 AST。未就绪作业明确拒绝，不在 Research 热路径补跑认证。

数值规范 `DECIMAL28_HALF_EVEN_Q12_V1`：28位有效数字、HALF_EVEN、输出量化12位小数、统一正零；null／warmup／错误／除零由原语和输出类型显式定义。不能用二进制浮点或运算重排改变值；不能据此修改资金、数量或 Ledger 的所属精度。第一阶段只定义该绑定标识，程序执行和数值认证由第三阶段实现。

## 正式结果成员和消费者

`ResultPlan` 使用逻辑键、MemberKind、schema 指纹、axis（适用时）和行数约束，身份与物理文件名无关。

| 作业 | 必需角色 | 必须留存的实际内容／消费者 |
|---|---|---|
| Research | CALCULATION_VALUES | 当前完整图各节点／商品的类型输出、轴和缺失值；计算结果、复现和图验证 |
| Research | SIGNAL_VALUES | eligibility／entry／exit 及原始信号序列和节点绑定；Strategy Freeze／验证 |
| Research | STATISTICS | 现有统计计划的实际值、NULL／INSUFFICIENT和样本／方法绑定；Research报告／Qualification；不新增收益关系方法 |
| Research | RESEARCH_REPORT | 当前研究结果计划、报告、candidate／执行绑定及各结果成员引用；结果读取和定版溯源 |
| 两类 | CAUSAL_EVIDENCE | 输入、版本、实际执行者结束／资源回收、信号与交易因果关联和结果清单；完成／读取／恢复核查 |
| Backtest | EXECUTION_FACTS | 真实有序意图、拒绝、订单、成交、费用及资金／仓位因果事实；经济复核和审计 |
| Backtest | ECONOMIC_RESULT | 既有 owning Account／Ledger 结果、完整订单／交易、最终仓位／Allocation、账户及Ledger时间线、诊断；回测报告及Qualification |
| Backtest | CLOSE_CURVE | 实际 sample Bar 对应的NAV／高水位／回撤／account sequence，原同数量buy-and-hold比较及样本边界关联；Web结果和图表 |

冻结时已知的序列采用精确rows；EXECUTION_FACTS允许rows=null，表示由真实执行owner产生最终计数，而非预知成交数。其实际事实轴也可能执行后才知道：这时axis=null，并必须冻结axis_rule（规范排序、事件身份和分区规则的确切内容摘要）；其他序列仍冻结已知精确axis。最终inventory必须保留相同axis_rule，并由实际owner从全部真实事实计算具体axis、给出实际rows；缺失轴／计数或错规则拒绝。check_inventory只能核对这些描述符，后续完成／发布owner还必须按冻结规则重算实际正文的轴并核对摘要，不能用任意hash代替。不得将“动态计数”误解为可以删事实。经济／报告／因果根各为一条完整结构化内容；带逐行序列的角色必须绑定轴。允许一个角色按逻辑键拆出多成员，但成员全集必须在计划中声明，不能在读取时以缺省空表补齐。轴、schema、行数、逻辑键不同都不能作为相同成员接受。

最终成员的内容摘要、唯一发布身份和终态由正式发布事务负责，计划不是完成证据。`check_inventory` 只能检查描述符全集，不证明正文、数值、因果或真实完成。Freeze／Qualification／Promotion 只能消费 owning reader 已验证的正式发布，不能消费构建证书、Command回执、内存候选或诊断日志。

## 生命周期和失败分类

沿用各所属模块现有 Run／Attempt、租约时钟、领域生命周期时钟及 fencing，不另建状态机。`validate_terminal_result` 目前复用既有 Backtest `RunState`，只表达完整发布与状态的一致谓词；Research 接线时同样遵循此规则，不将 Backtest 类型硬塞成其持久化状态。

COMPLETED 必须同事务拥有完整正式结果；CANCELLED／FAILED 不发布部分结果或假零结果；活动状态不对外暴露正式候选。CANCEL_REQUESTED 是取消意图，不能自行撤销已完成发布。完成／取消竞争由正式 owner 在受控事务中裁定，不能靠本模块的值谓词改变状态。

ContractError 分开表达 Invalid、MissingEvidence、Unavailable、Mismatch、NotReady、OutcomeUnknown、BudgetExceeded、UnexpectedResult。缺证、读失败和确定不匹配不是同一件事；OutcomeUnknown不是新的失败终态。它们是内部错误分类，尚未注册为新的公开HTTP错误码。

## 分阶段接口和权限约束

以下是实现者必须遵守的接口约定。第二阶段提供仓储 publish／observe／read 原语；read 直接由 PublicationRepository 实现，不另加空壳 ResultReader。其他接口按后续阶段落实，没有返回伪成功或 todo 的生产 stub。

| 所属模块／接口 | 输入和输出 | 必需的真实检查 |
|---|---|---|
| 构建 owner：request／resolve_ready_binding | 精确版本＋解析参数 → 构建请求／确切就绪绑定 | 真实程序与证书、权限、版本和参数；不发明全域认证 |
| 输入 owner：JobInputLoader::load | FrozenJobBinding＋MemoryBudget → PreparedJobInput | CH切片正文、引用、轴／行数／摘要及权限，内存分配预算 |
| 交易 owner：Session::new／apply | 纯RunBinding＋RunConfiguration／TradingInput → 当前typed会话／AppliedEvent | 不依赖Backend或DB；信号后执行完整经济规则 |
| 结束 owner：BacktestRun::finish／Research结束 | 实际输入耗尽、经济状态、drain → 私有CompletedBacktest／CompletedResearch | 不公开DTO反序列化构造；真实子进程回收由Backend owner补足 |
| 仓储：PublicationRepository::publish | 既有AttemptClaim＋私有CompletedJobCandidate → Committed／AlreadyPublished／明确错误或未知 | 当前Run锁、修订、有效lease/fence、全成员与冻结绑定、唯一发布、终态同事务 |
| 仓储：PublicationRepository::observe | 原Run → Published／ConfirmedUnpublished／Unresolved | 原事务已解决的锁和合法状态；普通SELECT查空不等于ConfirmedUnpublished |
| 恢复：JobRecovery::resolve | 原Run观察 → 已发布复用／新Claim重算／完成取消／等待／拒绝 | 保留Run、遵循现有重试规则；缺工件／数据不能换最新 |
| 查询：ResultReader::read | 原Run＋主体 → 验证后正式结果 | 权限、完整类型、正文摘要、成员关联；不得整段重跑回测 |
| 持续交易：DurableFactPort | 原PreparedTradingFacts／TradingBinding → durable receipt／恢复事实 | PG正式事实、committed-unready投影、外部未知对账；receipt不是LIVE权限 |

AttemptClaim 继续由现有认领模块私有构造，不新增可由客户端反序列化的 claim。CompletedJobCandidate 只由真实 owner 和 joined 证明构造。Backend 派单还要求正式仓储确认提交及既有准入后产生的私有 DispatchPermit；内存结果、任意port实现及外部布尔值不可转换。第一阶段不新增这些权限对象的伪构造器。

## 实际调用迁移对应

| 当前入口／消费者 | 迁移目的地 | 实施阶段 |
|---|---|---|
| private_assets/authoring、private_factor_postgres、Python private_factor_execution | 独立构建／精确认证；同一正式示例路径 | 三 |
| strategy_research/execution::observe_graph／run_case、workers/research | 构建认证消费；实际输入／输出约束与真实Research执行 | 三、四、六 |
| workers/trading_program、strategy::Executor、backtest::next_open | 同一信号程序；账户访问仅在信号后的交易环节 | 三、五 |
| backtest_service／backtest_worker、RunLoop、Runtime::create/open | 精确输入＋内存会话；新Attempt冻结重算 | 四至六 |
| research_evidence::strategy、backtest_evidence::store、backtest_result | PostgreSQL全成员和唯一发布；GET只读结果 | 二、六 |
| strategy_validation、frozen_strategy、qualification、strategy_promotion | 读取真实构建与输入验证／正式发布关系；保留各自Authority | 三、六 |
| runtime::SqliteStore、broker_source_store、perpetual_sources、virtual broker/source_host | 有限内存／持续PG事实适配；退役文件业务journal | 五、七、八 |
| native host/startup测试、benches、镜像、依赖门禁 | 消费新接口并移除旧Source文件假设 | 八、九 |
| Product／Agent API、Web与生成类型 | 沿正式入口暴露实际构建／作业状态，不添加特供绕过入口 | 三、六、九 |

第一阶段未改变HTTP响应，因此不生成声称已上线的新端点或schema。涉及接口更新的后续阶段必须同时更新真实 serving 声明、OpenAPI、Agent描述、生成TypeScript与实际入口测试，不能仅改静态JSON。正常人操作和Agent权限边界保持不变。

## 性能计量边界和现有bench迁移

以下名称是后续观测接线的统一口径；第一阶段没有新增已生效span，也不以契约测试耗时宣称引擎性能。

| 口径 | 起止和分母 | 所属后续阶段 |
|---|---|---|
| factor.build／factor.certify | 源码解析降级／精确参数认证，各自总耗时；不计入每Bar执行 | 三 |
| job.input | READY绑定解析至CH实际内容／轴／摘要验证和加载完成；实际输入rows／bytes | 四 |
| signal.batch／signal.event | 相同程序和输入的原始信号计算；注明warmup与sample | 三、五 |
| trading.execute | 已准备输入至完整交易输入消费与drain，不含CH准备／PG发布；实际K线数，不是OPEN／BAR step数 | 五 |
| result.prepare | owner结束检查、成员整理、canonical编码和子进程正向回收；分别记子项和墙钟 | 五、六 |
| result.publish | 原Run锁等待、全成员插入／校验、终态和COMMIT确认；不能漏SQL写入 | 二、六 |
| result.read／response | 正式GET读取／校验至后端响应，再至浏览器可见；不触发回测执行 | 六、九 |
| trading.restore | 持续PG事实读取、typed状态重建、投影与对账；与有限作业重算分开 | 七 |

现有[inventory](../test-data/backtest-benchmarks/inventory.json)有25个crate/工程名字：原23库闭包、Backend和observability。operators／calculation／strategy及原组件bench保留语义基准；新typed程序数值执行接入第三阶段bench，若indicators进入实际闭包须同步补其bench与BENCHMARK.md。runtime retained／recovery及backtest／backend链路中依赖旧SQLite文件的样本由第五、七、八阶段分别迁为内存执行、PG正式事实恢复、结果发布／读取；不能借旧Source产物隐式保留业务SQLite。

总墙钟按排他阶段及真实并行等待解释，嵌套span不相加；准备、交易、收尾各单列，未闭合耗时明确列出。冻结代码／工件、机器／资源、输入／版本、样本数、缓存、内存预算和观测开关。既有300/120秒门槛不放宽，不新增硬吞吐阈值；新长时专项须有单独预算。

## 验证边界

当前纯契约回归证明规范化身份、精确绑定比较、错误分类和结果计划规则；不证明数据库原子性、证书真实性、CH正文、进程恢复、回测性能或Web产品通过。这些证据分别由[实施计划](superpowers/plans/2026-11-14-research-backtest-pg-memory-framework.md)各阶段取得。
