# PostgreSQL 构建内容与有限作业发布

本说明落实 [ADR 0151](adr/0151-postgresql-business-publication-and-memory-work.md) 与[有限作业契约](job-execution-contract.md)。源码入口是 Backend 的 [`factor_build`](../packages/backend/src/persistence/factor_build.rs) 和 [`job_publication`](../packages/backend/src/persistence/job_publication.rs)。这里只负责存储边界，不实现因子编译、认证算法、行情加载或交易执行，不新增正式状态机。

## 表与事实归属

迁移 [0077](../database/postgres/migrations/0077_factor_program_bindings.sql) 保存不可变程序容器、精确参数证书，引用原 `private_factor_revision` 的版本与源码摘要。程序和证书分别按规范正文计算身份；参数正文有自己的摘要。同一程序可对应多个精确参数证书。`StoredProgram`／`StoredCertificate` 只表示经仓储核对的内容，不能作为可执行程序或认证许可。

迁移 [0078](../database/postgres/migrations/0078_job_publication.sql) 增加 `job_frozen_binding`、`job_result_member`、`job_publication`，直接关联原 Research／Backtest Run。没有第二套 Run、Attempt、lease 或 fence。原 Run 完成状态和结果引用、原 Attempt 成功状态、完整成员正文及唯一发布在一个事务中提交。三张内容表和两张构建内容表拒绝 UPDATE、DELETE、TRUNCATE；同一 Run 最多一个发布。未发布作业可有冻结绑定，不可有遗留结果成员；COMPLETED 不能没有发布。已绑定作业的终态和 Attempt 终态不可被回写。

成员保存实际正文，而非文件路径或只存摘要。清单 `PG_JOB_RESULT_V1` 绑定完整冻结身份、成员键、描述符摘要、正文摘要。它不冒充旧文件证据协议；旧结果消费者接入新仓储属于后续迁移。K 线仍归 ClickHouse，未发布的逐事件过程不写这组表。

## 权限和连接

三个 NOLOGIN、NOINHERIT、无管理权限的组角色分别为 `onlyalpha_factor_builder`、`onlyalpha_job_reader`、`onlyalpha_job_publisher`。构建组仅能读取与插入构建内容；读取组只读；发布组插入结果及更新原 Run／Attempt 的必要终态列，没有认领、心跳或任意 Source 历史写权限。PUBLIC 无新表和辅助函数权限。迁移发现同名角色带有超出约定的权限时拒绝接纳。

仓储要求真实认证的 `session_user` 是无管理权限 LOGIN，`current_user` 是获准的组；管理员连接 SET ROLE 不能伪装普通运行连接，RESET ROLE 也不得升为管理员。部署应给各服务 LOGIN 分配所需组，并使用原固定拓扑；本阶段不新增服务、凭据文件或自动改写现有生产连接。权限是受信 Backend 服务边界，不是允许客户端任意选择 owner 的租户 API。Repository 构造参数中的 owner 必须来自后续正式授权入口，不能取未鉴权请求字段。

每个仓储借用同一条物理连接，核对原语义数据库 namespace；不自行重连或切库。构建记录的版本／源码外键也必须匹配。Research 原有控制历史继续通过仅绑定真实 Run／Attempt 行的 SECURITY DEFINER 触发器记录；固定 `pg_catalog` search_path、显式 public 引用，调用原转换逻辑。发布角色不能直接调用历史写函数或注入事件。这是业务控制历史，不是逐 Bar 持久化过程。

## 接口与原子性

- `FactorBuildRepository::put` 接收私有 `BuildPublication`，原子保存程序与精确参数证书；重复写入核对完整内容，冲突拒绝。`read_program`／`read_certificate` 按确切身份读取并核对正文、关联与摘要。
- `PublicationRepository::register` 接收私有 `FrozenBindingRegistration`，锁定原 Run，核对 namespace、owner、原 specification／admission 和合法状态，冻结完整绑定。重复注册必须内容完全相同。
- `AttemptClaim::from_research`／`from_backtest` 借用原不可伪造 Claim，保留本地所有权确定性；Research 沿用 attempt_number，Backtest 沿用 fencing_token，不自建租约协议。
- `publish` 接收私有 `CompletedJobCandidate`，核对完整候选、原 Run 锁与修订、真实 Attempt／worker／number／fence／Generation、有效租约，再写全部正文和清单、完成原 Attempt 和 Run。结束更新重新检查租约，提交前立即执行约束与完整读回。同一完整结果返回 AlreadyPublished，不同结果冲突；不使用忽略冲突作为成功依据。
- `read` 在只读 Repeatable Read 事务中核对全体成员正文和清单、绑定、原 Run 完成状态与结果引用、原成功 Attempt。缺失与损坏分别报错，不缺省空结果，也不重跑交易引擎。
- `observe` 必须持有写角色，以原 Run 的 FOR UPDATE NOWAIT 区分原事务尚未解决与已解决。锁忙返回 Unresolved；已完整发布返回 Published；确认无发布时返回含绑定、Run 修订和状态的私有 ConfirmedUnpublished。普通 SELECT 查空不能证明事务未提交。该观察不授予新认领或重算许可，后续恢复仍必须按原状态／修订／fence 重新 CAS。

提交链路丢失响应时返回 OutcomeUnknown，继续查询原 Run。不能将网络失败转成 FAILED 或直接重发。真实数据库回归包含拦截实际 COMMIT 前后的网络代理，分别证明未提交回滚、提交结果未传达、未决事务锁和唯一发布。

注册、构建保存和正式发布在事务内要求 fsync、full_page_writes 开启，并将 synchronous_commit 至少设置为 on，保留更强的 remote_apply；调用方 off 不会使正式结果异步确认。设置只在当前事务有效。依据 PostgreSQL [WAL 配置](https://www.postgresql.org/docs/18/runtime-config-wal.html)、[行锁](https://www.postgresql.org/docs/18/explicit-locking.html)和[权限](https://www.postgresql.org/docs/18/sql-grant.html)语义；这些设置不能替代部署的实际磁盘可靠性。

## 预算与错误

复用原 PostgreSQL statement_timeout／lock_timeout 预算，保留调用方更小值，系统设置查询限定 pg_catalog，避免临时同名表扩大预算。冻结绑定至多 256 KiB、成员至多 1024 项、单描述符至多 8 KiB、发布清单至多 1 MiB、所有正文合计至多 128 MiB。构建程序／证书各至多 8 MiB，解析后参数至多 256 KiB。读取结果前先检查 SQL 聚合大小，超限不先传输完整正文。这些是明确拒绝预算，不是吞吐验收门槛。

PublicationError 区分 Denied、MissingEvidence、Unavailable、Integrity、Mismatch、Conflict、OwnershipLost、OutcomeUnknown、BudgetExceeded。服务不可用、锁或语句超时、操作性数据库错误不能被解释成内容不匹配。接口未新增公开 HTTP 错误码，不能据此绕过正式 API 授权。

## 验证与阶段边界

专用 Cargo 测试目标 `application_job_publication` 挂载同一生产源码，私有测试生产器仅在测试工件中存在。它使用真实 PostgreSQL、真实无管理权限 LOGIN，限定 `onlyalpha_dev_validation_test`，每个测试进程显式准备受控 schema；不得在开发业务库运行。测试程序正文和证书标为 STORAGE_FIXTURE_ONLY，不证明真实因子认证或回测完成。

经固定 onlyalpha-dev 的冻结源码执行：

```text
cargo test --frozen --offline -p onlyalpha-backend --test application_job_publication -- --test-threads=1
cargo test --release --frozen --offline -p onlyalpha-backend --test application_job_publication tests::postgres_publication_performance_matrix -- --ignored --exact --nocapture
cargo clippy --frozen --offline -p onlyalpha-backend --lib --test application_job_publication -- -D warnings
```

实际命令须使用 scripts/dev_verification.py 与现有 compiler_environment，不另建数据库拓扑。性能矩阵记录固定合成正文的准备、锁等待、成员 SQL、终态与读回、COMMIT、未归因部分和独立读取；每档预热一轮、记录三轮，原始内容摘要保持一致，报告缓存与进程累计峰值局限。方法与结果见 [BENCHMARK.md](../packages/backend/BENCHMARK.md)，不能冒充完整回测 bars/s 或相对旧链路的加速比。

本阶段没有生产版 BuildPublication／FrozenBindingRegistration／CompletedJobCandidate 构造入口，不接受外部 JSON、布尔值或任意 hash 获取完成许可。真实构建 owner 在第三阶段实现，真实结束／joined 证明及派单、查询与恢复接线按第五、六阶段实施。没有迁移旧 SQLite、运行 Web 取证或修改性能优化逻辑。
