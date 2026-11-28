# PostgreSQL 构建内容与有限作业发布

本说明落实 [ADR 0151](adr/0151-postgresql-business-publication-and-memory-work.md) 与[有限作业契约](job-execution-contract.md)，约束产品存储边界。原仓储实现随 Backend 退役。因子编译、行情加载、交易执行及内存结果核验各归所属组件。

## 表与事实归属

迁移 [0077](../database/postgres/migrations/0077_factor_program_bindings.sql) 保存不可变程序容器、精确参数证书，引用原 `private_factor_revision` 的版本与源码摘要。程序和证书分别按规范正文计算身份；参数正文有自己的摘要。同一程序可对应多个精确参数证书。`StoredProgram`／`StoredCertificate` 只表示经仓储核对的内容，不能作为可执行程序或认证许可。

迁移 [0078](../database/postgres/migrations/0078_job_publication.sql) 增加 `job_frozen_binding`、`job_result_member`、`job_publication`，直接关联原 Research／Backtest Run。没有第二套 Run、Attempt、lease 或 fence。原 Run 完成状态和结果引用、原 Attempt 成功状态、完整成员正文及唯一发布在一个事务中提交。三张内容表和两张构建内容表拒绝 UPDATE、DELETE、TRUNCATE；同一 Run 最多一个发布。未发布作业可有冻结绑定，遗留结果成员和孤立的成功 Attempt 均违反发布约束。[0085](../database/postgres/migrations/0085_job_successful_attempt_publication.sql) 要求已冻结作业的每条 `SUCCEEDED` Attempt 对应唯一发布记录中的获胜 Attempt。`COMPLETED` 必须有完整发布。已绑定作业的终态和 Attempt 终态不可被回写。冻结登记和仍看不到冻结绑定的成功 Attempt 写入共同更新原 Run 的物理行版本。持锁冲突以及 Repeatable Read 的旧快照会令其中一笔事务失败。此更新保留原 revision 及所有逻辑字段，不记入 Research Source 历史。正式读回只接受唯一一条成功 Attempt，并核对它与发布记录一致。

成员保存实际正文，而非文件路径或只存摘要。清单 `PG_JOB_RESULT_V1` 绑定完整冻结身份、成员键、描述符摘要、正文摘要。结果消费者必须使用这组表签发的完整读取证明，不能用文件协议包装或伪造新结果。K 线仍归 ClickHouse，未发布的逐事件过程不写这组表。

## 权限和连接

构建、读取、发布和 Node 控制分别使用 `onlyalpha_factor_builder`、`onlyalpha_job_reader`、`onlyalpha_job_publisher`、`onlyalpha_node_control`，均为 NOLOGIN、NOINHERIT、无管理权限的组。构建组追加程序和证书，并推进构建请求；读取组只读；发布组插入结果及更新原 Run／Attempt 的必要终态列，没有认领、心跳或任意 Source 历史写权限。Node 控制组的确切表与列由 [0081](../database/postgres/migrations/0081_node_control_permissions.sql) 定义，不直接获得构建／发布内容权限，不更新结果指纹。PUBLIC 无新表和封闭辅助函数权限。

仓储要求真实认证的 `session_user` 是无管理权限 LOGIN，`current_user` 是获准的组；管理员连接 SET ROLE 不能伪装普通运行连接，RESET ROLE 也不得升为管理员。Node LOGIN 仅继承控制组，不能 SET 到该组；reader／publisher 成员关系为 INHERIT FALSE、SET TRUE、ADMIN FALSE，不获得 builder 成员关系。迁移管理员和独立 builder 账户继续分离。权限是受信 Backend 服务边界，不是允许客户端任意选择 owner 的租户 API；owner 不能取未鉴权请求字段。

正式宿主持有实际连接及其 driver 时，须只读核对 `session_user`、配置用户、默认角色、成员关系、列 ACL、PUBLIC 的有效权限、GRANT OPTION、对象所有权、角色配置、源码读取和封闭 Chart 入口。失败、取消或超时应撤销连接。启动不得自动授权，未知角色和权限污染须拒绝。

发布和观察复用原 `AuthoritySession` 物理连接，不另开业务写连接。角色作用域在首个 await 前取得连接与 driver 的独占所有权，操作结束后确认默认角色及原锁；取消、未知提交、恢复角色失败或锁失效均不能复用连接。认领事务需要暂时读取发布内容时，原 Run 锁贯穿临时角色、恢复普通 LOGIN 和控制 CAS。

嵌套在原控制事务中的事实查询，显式携带实际 `AuthoritySession` 签发的私有连接作用域句柄，核对原 driver、PID、backend_start 和原锁。作用域在首个 await 前建立撤销守卫；完整恢复确认前发生失败、取消或丢弃，均将共享撤销状态置为不可恢复并中止原 driver。外层事务回滚、错误码转换或后续锁检查不能清除此状态。该句柄只管理原连接资源，不授予 Run、READY 或业务权限。纯只读消费者使用独立持有 driver 的固定 reader，将元数据事务和不可变构建事实事务显式传给共享校验，不能从普通 Transaction 推定控制连接所有权。

每个仓储借用同一条物理连接，核对原语义数据库 namespace；不自行重连或切库。构建记录的版本／源码外键也必须匹配。Research 原有控制历史继续通过仅绑定真实 Run／Attempt 行的 SECURITY DEFINER 触发器记录；固定 `pg_catalog` search_path、显式 public 引用，调用原转换逻辑。发布角色不能直接调用历史写函数或注入事件。这是业务控制历史，不是逐 Bar 持久化过程。

## 接口与原子性

- `FactorBuildRepository::put` 接收私有 `BuildPublication`，原子保存程序与精确参数证书；重复写入核对完整内容，冲突拒绝。`read_program`／`read_certificate` 按确切身份读取并核对正文、关联与摘要。
- `PublicationRepository::register` 接收私有 `FrozenBindingRegistration`，锁定原 Run，核对 namespace、owner、原 specification／admission 和合法状态，冻结完整绑定。重复注册必须内容完全相同。
- `AttemptClaim::from_research`／`from_backtest` 借用原不可伪造 Claim，保留本地所有权确定性；Research 沿用 attempt_number，Backtest 沿用 fencing_token，不自建租约协议。
- `publish` 接收私有 `CompletedJobCandidate`，核对完整候选、原 Run 锁与修订、真实 Attempt／worker／number／fence／Generation、有效租约，再写全部正文和清单、完成原 Attempt 和 Run。结束更新重新检查租约，提交前立即执行约束与完整读回。已发布时，先核对 Claim 的 Attempt、Worker、序号和 fence 与原获胜记录一致，其他 Claim 返回 OwnershipLost。原获胜 Claim 重放相同结果返回 AlreadyPublished，正文不同则返回 Conflict。
- `read` 在只读 Repeatable Read 事务中核对全体成员正文和清单、绑定、原 Run 完成状态与结果引用、原成功 Attempt。缺失与损坏分别报错，不缺省空结果，也不重跑交易引擎。
- `observe` 必须持有写角色，以原 Run 的 FOR UPDATE NOWAIT 区分原事务尚未解决与已解决。锁忙返回 Unresolved；已完整发布返回 Published；确认无发布时返回含绑定、Run 修订和状态的私有 ConfirmedUnpublished。普通 SELECT 查空不能证明事务未提交。该观察不授予新认领或重算许可，后续恢复仍必须按原状态／修订／fence 重新 CAS。

提交链路丢失响应时返回 OutcomeUnknown，继续查询原 Run。不能将网络失败转成 FAILED 或直接重发。真实数据库回归包含拦截实际 COMMIT 前后的网络代理，分别证明未提交回滚、提交结果未传达、未决事务锁和唯一发布。

注册、构建保存和正式发布在事务内要求 fsync、full_page_writes 开启，并将 synchronous_commit 至少设置为 on，保留更强的 remote_apply；调用方 off 不会使正式结果异步确认。设置只在当前事务有效。依据 PostgreSQL [WAL 配置](https://www.postgresql.org/docs/18/runtime-config-wal.html)、[行锁](https://www.postgresql.org/docs/18/explicit-locking.html)和[权限](https://www.postgresql.org/docs/18/sql-grant.html)语义；这些设置不能替代部署的实际磁盘可靠性。

## 预算与错误

复用原 PostgreSQL statement_timeout／lock_timeout 预算，保留调用方更小值，系统设置查询限定 pg_catalog，避免临时同名表扩大预算。冻结绑定至多 256 KiB、成员至多 1024 项、单描述符至多 8 KiB、发布清单至多 1 MiB、所有正文合计至多 128 MiB。构建程序／证书各至多 8 MiB，解析后参数至多 256 KiB。读取结果前先检查 SQL 聚合大小，超限不先传输完整正文。这些是明确拒绝预算，不是吞吐验收门槛。

PublicationError 区分 Denied、MissingEvidence、Unavailable、Integrity、Mismatch、Conflict、OwnershipLost、OutcomeUnknown、BudgetExceeded。服务不可用、锁或语句超时、操作性数据库错误不能被解释成内容不匹配。Research 受理将缺证、权限拒绝和预算超限分别映射为 `RESEARCH_INPUT_BINDING_MISSING`、`RESEARCH_INPUT_BINDING_ACCESS_DENIED` 和 `RESEARCH_INPUT_BINDING_BUDGET_EXCEEDED`；存储不可用与 owner 失效保留不可用语义，未知保留原 Command 的未知语义，完整读取后确定不匹配才报告损坏。这些诊断不能绕过正式 API 授权。

## 验证与阶段边界

原 Backend 的 PostgreSQL 发布测试与组合基准已退役。恢复验证须使用隔离测试数据库、真实低权限 LOGIN 和实际事务。分别验证准备、锁、终态与成员、COMMIT、独立读取和不确定结果，不得用 Rust 内存完成或存储夹具替代正式发布证据。

BuildPublication、FrozenBindingRegistration 和 CompletedJobCandidate 必须由其真实构建、受理和结束 owner 签发，不接受外部 JSON、布尔值或任意 hash 获取许可。Research 原受理消费已验证的策略 Run、PreparedInputs、实际保留 Dataset 与 PostgreSQL 封闭行情元数据，核对 Source、Runtime、输入轴和精确执行绑定，再在原 Run、授权与回执的同一事务中登记。重复受理只读取原登记；缺证或不匹配不能从当前准备输入补写。冻结输入登记不证明物理行情已加载、交易执行已结束或结果已发布。

恢复决策的拒绝分支保留原 `ConfirmedUnpublished`，终结控制必须重新核对该原 Run、状态和修订，不能把拒绝原因当作不存在结果的证明。 `ResearchExecution::claim_recompute` 自行在原 AuthoritySession 的 publisher 作用域取得发布观察，然后恢复控制角色，在原 Run 锁内重新检查同一证明；仅有效、未发布、无 ACTIVE 且未耗尽的策略 Research 可以取得新 Claim。认领不加载行情、不认证程序，也不授予 Source 权限；提交丢失响应时不返回 Claim。

有限回测用尽三次 Attempt 后，由原 Node 控制会话将同一 Run 明确结为 `FAILED`；取消收尾同样不产生结果。两者须在原 Run 锁内重新核对已确认未发布、没有 ACTIVE owner 的证明，拒绝旧观察。迁移 [0082](../database/postgres/migrations/0082_backtest_failure_control.sql) 只补齐既有失败控制职责所需的三个失败字段 UPDATE 权限，不授予结果指纹或发布权限，普通启动仍不自动授权。

Research Run 的 `calculation_execution_evidence_fingerprints` 引用当前 PG 发布中的 `CAUSAL_EVIDENCE` 成员正文摘要，按字典序去重；它不包装旧文件协议。成员保留实际计算完成、真实 join 和其他结果成员的精确关联，引用列表不能独立授予完成许可。[0083](../database/postgres/migrations/0083_research_publication_causal_references.sql) 将已批准的 publisher 结果写职责补齐到该引用列，并以延迟约束要求引用精确等于原发布的全部因果成员。Node 控制角色仍无该列 UPDATE 权限。发布写入、完整读取、原 Run 与 Source history 必须一致，缺失、外来引用和非完成态提前写入均拒绝。

执行侧 READY 因子的声明元数据由构建者写入精确参数证书 `execution_metadata`，纳入证书 canonical 身份和原有读取预算。执行 reader 不读取私有因子源码表，不获得额外列权限；读取时仍验证元数据版本、源码摘要、接口和程序签名。开发阶段直接要求当前证书形状，旧证书缺失该字段时明确拒绝，不做兼容补读或执行时构建。
