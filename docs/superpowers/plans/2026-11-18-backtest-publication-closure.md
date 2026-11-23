# 正式回测发布与恢复实施计划

> 执行方式：单一 local-worker 使用 `executing-plans`；每项按红灯、最小实现、绿灯顺序执行。以下是同一次交付的步骤，不是分别推送的任务。

**目标：** 用户提交一次回测，得到唯一完整的正式结果，或得到不含部分结果的取消状态；重启和重复查询不改变经济事实。

**架构：** Rust Backend 复用有限作业的冻结输入、认领执行和 PostgreSQL 发布仓储；ClickHouse 提供精确行情。Web 通过正式 API 查询，不自行裁决结果。

**技术：** 现有 Rust workspace、PostgreSQL、ClickHouse、React、pytest、Playwright 和 onlyalpha-dev。

**设计：** [已确认设计](../specs/2026-11-18-backtest-publication-closure-design.md)；[阶段六的接口与故障矩阵](2026-11-14-research-backtest-pg-memory-framework.md#阶段六正式作业原子结果发布重算和取消闭环)。Constitution Impact：NO。

## 全局约束

- 不改经济规则，不迁移持续交易或全库 SQLite；不增加兼容 reader、双写、依赖、服务、生产故障入口或长数据库事务。
- 执行前只读记录 `git status --short --branch`、`git worktree list --porcelain`、HEAD、上游和完整差异（含未跟踪的相关源码）。区分本任务修改、既有阶段六工作和无关修改；不得从旧 HEAD 新建工作树后丢弃已有实现。无法安全分离则停止，不 reset、stash、覆盖或提交他人修改。
- 保存命令、退出码、冻结源码 SHA256、差异范围和日志至 `test-results/backtest-publication-closure/`，作为证据而非第二份验收规范。验证串行使用固定 dev 及独立测试命名空间，不放宽超时、不重置当前版本失败数据。资源异常或同一阻塞三次未解决即停止，不重置已有尝试数。

## 重点审查

| 条件 | 预期 | 对应步骤 |
|---|---|---|
| READY 后精确输入消失或被同范围新版替代 | 明确拒绝，不换最新、不发布 | 1、2 |
| COMMIT 已生效但响应丢失 | 在原身份观察，不建新 Run、不重复发布 | 3 |
| 新 Attempt 已认领，旧执行者晚到 | 拒绝旧执行者，未覆盖经济结果 | 3 |
| 取消和完成竞争 | 仅一个合法终态；查询不可见部分成员 | 3、4 |
| 非归属用户查询或结果少成员、错关联 | 不泄露、不伪造“不存在”或零收益 | 4 |

### 1. 固定目标用例，隔离 Research 前置失败

**已确认修订（2026-11-18）：** 负责人回复「同意，并继续任务」。仅对 `backtest-owner:finite-publication` 的 Research 准备步骤改用现有真实有限作业 worker 的发布路径；不调用旧探针直接完成，也不得直接写入已发布夹具。先核对同一 Research Run 的唯一正式发布、冻结身份及完整因果证据，再由正式 Backtest 调度器消费，分别断言前置与目标结果。保留以前失败的日志，不再次运行原失败路径作为修复尝试。执行者须先核对已有差异，仅撤回本任务引入的 120→300 秒改动；维持原用例 120 秒门槛，超预算记录分段耗时并停止，不以拆分或换入口重置计时。旧生产 `complete_guarded` 的迁移不计入本次修复或验收，以下步骤 2–5 不变。

- [ ] 阅读 `packages/backend/tests/application/test_backtest_worker_publication.py:17–25` 及其调用的 `test_strategy_research_evidence.py`。沿真实场景分别标记 Research 已发布、Backtest 已受理、实际执行者已结束、PG 已发布四个观测点；不可通过注入已完成回测来通过测试。
- [ ] 固定入口运行 `python3 scripts/dev_verification.py run -- python -m pytest -q packages/backend/tests/application/test_backtest_worker_publication.py`。记录首个失败观测点及错误归属。若 Research 前置失败，只修复有证据的直接原因，并分别保留其通过记录和回测断言；旧的 `1 failed, 5 passed` 不能算本轮红灯。
- [ ] 断言 admission 的 Run ID 等于发布的 Run ID、正式发布数为 1、成员集合与冻结计划完全一致，不需要运行目录或文件结果。获知首个旧行为失败后再改对应生产路径。

### 2. 将调度器接入已有内存执行者和事务发布

- [ ] 修改 `packages/backend/src/workers/{backtest_worker,backtest_service}.rs` 的真实调度分支。使用既有 `PreparedBacktestJob::start_claimed(self, input: PreparedJobInput, binding: FrozenJobBinding, claim: &AttemptClaim<'_>) -> Result<FiniteTask, PreparationError>`，不使用无 claim 的 `start` 获得发布资格。参考 `workers/finite_research.rs` 的恢复、heartbeat、结束及观察顺序，不复制 Research 的权限或错误码。
- [ ] 加入精确输入缺失、错误 Run/owner、执行未真正结束的负例：均不能产生发布或 COMPLETED。仅合法 owner 在真实 join、排空和校验后把候选交给 `packages/backend/src/persistence/job_publication/writer.rs`；在同一事务写成员、唯一发布及 Run/Attempt 终态。移除本调用链的 `RunLoop::open/create`、文件先写和分步终结，不触动持续交易消费者。
- [ ] 重跑步骤 1 的命令，核实不是 skip、仅构建或仅跑到 Research。保留成功执行者身份、事务结果、成员及零文件结果依赖的断言。

### 3. 验证恢复和取消竞争

- [ ] 在 `test_backtest_worker_publication.py` 与既有 `packages/backend/tests/application/support/backtest_owner_scenarios.rs` 中扩展真实执行场景；只在测试边界设置确定性故障点。覆盖未执行、加载后、执行中、候选待提交、成员插入回滚、COMMIT 未知、响应丢失、旧租约回归八个窗口。先证旧行为失败，再调整 worker 的恢复分支。
- [ ] 逐例断言：原 Run 不变；已发布只观察；尚不能确定则不执行；确定未发布且取得新 claim 才允许换 Attempt；精确绑定、最终经济成员及内容与无故障对照相等；达到既有重试上限不再认领。
- [ ] 增加准备中取消、计算中取消、同时完成、完成后取消、无 ACTIVE 恢复取消。确定取消断言 `publication_count == 0` 且无成员；完成先成立断言 `publication_count == 1` 且内容不变。使用数据库事务顺序和执行者信号判定，不用 sleep。
- [ ] 运行 `python3 scripts/dev_verification.py run -- python -m pytest -q packages/backend/tests/application/test_backtest_worker_publication.py packages/backend/tests/application/test_research_worker_publication.py`；检查每个目标参数确实被收集并执行。

### 4. 同步结果查询、消费者契约和 Web

- [ ] 在 `packages/backend/src/transport/host_backtest.rs::backtest_result_owners` 及其直接消费者保留 session/owner 检查，以 `transport/job_publication.rs` 和 PG 完整发布读取替代文件 `VerifiedEvidence`。逐一追踪资格与晋级引用；未发布、错归属、错成员、缺成员均不得获得资格。通过真实应用 API 测两次 GET：发布身份和完整结果相同，计算调用增量为零；无权调用不暴露成员。
- [ ] 同步变更实际受影响的 Product／Agent 契约和客户端。在 `packages/frontend/e2e/backtest.spec.ts` 先将旧“取消保留部分结果／恢复文件前缀”断言换成原 Run、取消原因、无指标和完成结果保持不变的用户断言。修改 `BacktestPage.tsx` 消费控制状态；UNKNOWN 提供原 Run 查询路径，不显示失败或完成。不得将业务判断移入前端。
- [ ] 验证生成类型与冻结契约一致，运行 `python3 scripts/dev_verification.py --web run -- npm run typecheck`，随后 `python3 scripts/dev_verification.py --web run -- npm run e2e -- e2e/backtest.spec.ts`。通过正常 Web 入口操作；真实 API 测试单独留证，不以 UI 截图替代权限、未知或重复读取断言。

### 5. 同版验收、独立审查与收尾

- [ ] 汇总同版真实 DB／API／Web 回归与直接影响的质量检查；记录受理、准备、执行、编码、发布、GET 和前端可见耗时（嵌套跨度不累加），不创设新门槛。检查版本发生变化的早期绿灯是否需补跑。缺少环境、命令或实际用户入口则明确对应未验收项。
- [ ] 用完整修改／新增文件清单、源码摘要、测试日志、失败与修复对照交独立审查者。审查重推合法状态、事务边界和读取权限。阻塞发现交原执行者定向修复、复验，再审当前字节。
- [ ] 仅在审查通过后按 AGENTS.md §6 归档原审查结论和被审版本，精确提交任务范围；安全推送前先核实远端主线和其他工作，不强推，不夹带未审改动。推送后重新获取并确认远端包含该提交。不能安全发布则报告阻塞，不声称交付完成。
