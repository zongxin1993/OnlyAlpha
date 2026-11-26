# 测试规范

[工程指南第 4 节](../AGENTS.md#4-测试与验收)定义两种测试：单元测试与功能测试。

## 单元测试

在仓库根目录执行唯一的单元测试脚本：

```bash
python3 scripts/unit_tests.py
```

脚本从 Cargo 工作区选取 `crates/` 下的包，只运行 Cargo `--lib` 测试目标。测试由库内 Rust 模块挂载，
不运行 Cargo 集成目标、文档测试、后端、插件或其他语言测试，不需要启动应用或数据库。
[持续 CI](../.github/workflows/quality.yml) 中唯一的测试作业运行这个脚本。
按 [ADR 0103](adr/0103-public-api-contract-governance.md) 和 [ADR 0101](adr/0101-verification-authority-convergence.md)
保留 OpenAPI、Gateway 历史兼容性检查，[宪法防篡改检查](../.github/workflows/governance.yml)独立运行。这些门禁不执行功能测试。
其他功能测试及专项验证按实际影响在本地执行，不由 GitHub Actions 自动运行。

## 功能测试与专项验证

Rust 库的功能测试随库组织，不依赖外部服务时可以直接在宿主机用 `cargo test -p <Cargo 包名> --test <目标名>` 运行。
Web 整体测试归属 `packages/frontend`，OpenAPI 整体功能测试归属 `packages/backend`。两者以及依赖数据库或运行中应用的验证
使用唯一 `onlyalpha-dev` Compose 项目及隔离数据，入口是 `python3 scripts/dev_verification.py run -- <验证命令>`，
在前端目录执行时加 `--web`。具体场景和命令以当前源码与配置为准。外部环境的专项验证单独记录。

### 存量执行通道

`contract`、`architecture`、`integration`、`scenario` 是 pytest 的选择标签，不是工程的测试分类。
`recovery`、`conformance`、`external` 等是场景选择条件。收集插件 `scripts/pytest_layering.py` 按明确目录补充选择标签，
不再给未分类用例默认添加单元测试标签。显式标签优先；外部用例仍需声明对应的运行要求。

以下是存量通道命令。运行前核对场景与实际入口：

```bash
python scripts/dev_verification.py run -- python scripts/test_suite.py fast
python scripts/dev_verification.py run -- python scripts/test_suite.py integration
python scripts/dev_verification.py run -- python scripts/test_suite.py ashare
python scripts/dev_verification.py run -- python scripts/test_suite.py recovery
python scripts/dev_verification.py run -- python scripts/test_suite.py core-full
python scripts/dev_verification.py run -- python scripts/test_suite.py exhaustive
python scripts/dev_verification.py run -- python scripts/test_suite.py release
```

所有通道打印实际 pytest 参数、返回真实退出码，并将计数、耗时、最慢测试、Marker 和路径分布写入
`test-results/metrics/<lane>.json`。即使测试失败，指标仍会写出并保留真实 pytest 退出码。可用 `--workers N`、`--dist worksteal`、`--durations N` 或 `--no-parallel`
覆盖并行策略；定位进程级、SQLite 锁、顺序敏感或调试器问题时关闭 xdist。

pytest-timeout 由 `scripts/test_suite.py` 按通道配置，只用于发现测试卡死，不是性能预算。pytest 覆盖率测量只允许串行。

本地 `research-evaluation` 执行通道仍支持按只读 `test-data/test-durations.json` 分片。验证分片时仍须证明与原用例集合等价且不重叠；CI 不执行分片，也不定期刷新耗时数据。

数据库 acceptance 的 PostgreSQL 与 ClickHouse 独立 lane 在同一 Compose acceptance 容器中并行；它们使用不同数据库资源，不共享 destructive state。跨数据库
`database-acceptance` 始终在两者完成后串行执行。`pytest-testmon` 不进入 canonical CI，也没有第二套 impact-aware selector。

`fast` 选择离线工具检查、公共契约和架构边界检查；`integration` 证明最短离线纵切面与 scenario smoke；`ashare` 只运行
离线 A 股 conformance；`recovery` 独立运行普通 checkpoint/restart/fault correctness；`core-full` 覆盖全部普通 Workspace 离线 correctness；`exhaustive` 保留 100-run 和完整组合矩阵。
长测试必须标记 `slow` 或 `recovery`。产品纵切面必须经过 `OnlyEngine`；Analytics、Report、Artifact、Collector
应优先复用固定 Result/Snapshot fixture。

A 股申报前规则测试必须覆盖 2026-07-06 制度切换、主板/创业板/科创板风险警示矩阵、Tick 舍入上下限、五类交易阶段、
停牌/Inactive 分离、科创板最低数量与递增、零股全量清仓、固定 Evaluation 顺序、100 次确定性、Checkpoint 权威变化
拒绝以及结构化 Artifact。Risk/Order 测试不得另建 Session、Price 或 Quantity Validator。

当前不可用的 MiniQMT SDK adapter、SDK-only 测试及本机执行工作流已按 ADR 0139 下线。原先借用该 adapter
提供假行情的 SIM、交易 Authority 和恢复测试改用中立受控 Source；通用断言不删除。冻结 Golden Dataset
继续作为只读 provenance/conformance 输入，不需要 xtquant 或本机 QMT。

`release` 是本地发布验证聚合入口，按源码定义运行静态检查、Rust 和 Python 专项、真实 Web 功能场景和包构建。
日常修改运行最窄的正确通道；执行交易/恢复变更时执行受影响的 Recovery；发布验证按 AGENTS.md 的真实 Impact Scope 选择。外部环境不满足时应记录
“未执行”，不得记为通过。性能数据保留为当前运行产物，不提交历史 PASS/基线报告作为 Authority。

### PostgreSQL cluster-scoped Role isolation

`postgres_dsn` resets only the current database's public schema, not cluster roles
or other databases' dependencies. Tests of fresh role creation use the canonical
test image's pinned PostgreSQL 18 server tools and `isolated_postgres_cluster`:
non-root `initdb`, private temporary data/socket directories, no TCP listener,
and `pg_ctl -w` startup/shutdown. Only this fixture's data is removed; its server
log remains in `test-results/`. It temporarily uses the sole existing
`ONLYALPHA_POSTGRES_DSN` configuration, retaining the `_test` database check.
Private-socket trust is restricted to this container's fixture owner; actual
low-permission credential tests still use the canonical shared PostgreSQL service.

Preexisting-role rollback tests keep a separate, test-owned database alive in that
shared cluster, inventory its complete dependencies/facts and preserve them through
failure and retry. Cleanup drops only that newly created database, never shared
groups or other databases' grants. Both paths execute the unchanged official SQL;
creating another database alone cannot prove cluster-scoped roles are fresh.

### Exact installed-host test resources

Chart host fixtures build and validate real artifacts in a clean environment. A
separate read-only installed-code template is frozen under that exact Runtime
Generation fingerprint before a scenario provisions its schema reference. Cases
copy it into new, case-owned host caches; they never share workers, interpreters,
registries, Work, SQL state, Source facts or credentials. Existing destinations
are rejected, not merged. Symlinks may address the template itself or the approved
base interpreter, never another mutable environment/package tree. Permission
changes skip symlinks and are limited to fixture-owned copies.

This only avoids repeated construction of identical installed code. Each real
host still loads its own owning manifest/evidence, starts a fresh isolated Python
process, verifies installed seal/wheels/RECORD and checks the exact handshake.
Directory names/copies grant no Authority. Different generations remain separate;
their cold construction and corruption/rebuild coverage is not replaced. Template
cleanup restores its own directories even when setup fails before yielding. The
native Python module entrypoint is checked at its destination prefix; copying is
not a general promise that virtualenv entrypoint scripts are relocatable.

### 固定测试数据与重生成

标准 Result Fixture 位于 `test-data/results/`，由正式 `OnlyEngine` 场景生成；Analytics、Report、Artifact、
Collector 等纯下游测试应读取该不可变结果，不应为了验证渲染或序列化而重复运行 Engine。正式结果合同变化后，先确认不是
业务回归，再显式执行：

```powershell
uv run python scripts/regenerate_result_fixtures.py
```

持续交易与有限作业恢复测试采用 Rust 内存会话、PostgreSQL 正式事实恢复（`packages/backend/tests/application/trading_facts.rs`）与有限回测原子发布用例（`packages/backend/tests/application/job_publication.rs`）；旧 Python SQLite `test-data/recovery/*/*.sqlite3.gz` 及 `scripts/regenerate_recovery_baselines.py` 已随业务 SQLite 一并退役；该退役的 re-certification 记录见 `docs/audits/recovery_baseline_recertification.md` 末节。

Golden Evidence 治理（永久规则）：Golden Snapshot、已认证 Canonical Projection
或期望历史 Fingerprint 的任何变更，都必须附带显式书面 justification，并落成 `docs/audits/` 下的
独立 re-certification 记录（例如 `docs/audits/recovery_baseline_recertification.md`），说明旧/新
身份、语义原因、迁移理由、受影响工件与可复现的证明方式。仅为让 CI 变绿而重生成 golden 证据是被
禁止的（FORBIDDEN）；CI green 本身永远不能认证一次 baseline 变更。重生成脚本只允许作为只读复现
证明使用，其输出不得在未附 re-certification 记录的情况下提交；任何 lane 或 CI 工作流都不得自动
调用重生成脚本。

MiniQMT 冻结数据位于 `test-data/miniqmt/cn_a_share_v1/`。第一版只承诺未复权历史日 Bar；历史 ST、停牌和 effective
reference 明确缺失。离线 Reader 校验文件指纹后，经标准 MarketData Inbound/Pipeline 进入 `OnlyEngine`，不导入
`xtquant`、不访问网络。原采集命令随 SDK adapter 一并下线；不得重采集覆盖既有冻结文件、改变原 provider
身份或借移除 adapter 删除已存在 Evidence。

存量执行通道仅用于本地定向验证和专项取证。真实订单仍受独立人工授权边界约束。

以下是具体组件的覆盖要求；历史目录与命令不定义新的测试分类或运行入口。

## Product-style backtest acceptance

成品式 Demo 还必须覆盖配置加载、正式 Runtime API、Calendar-aware synthetic source、指标精确值、Warmup、Context 权限、
VirtualBroker/ExecutionProcessor 成交、T+1、固定 Seed 噪声、结果导出和至少 100 次完整确定性重放。指纹比较必须覆盖 MarketData
Audit、Clock、指标序列、策略信号、Order/Trade ID、Execution Audit、稳定 Event 序列及最终 Snapshot。

Strategy Ledger 必测固定资金、连续 Cash Reservation、买卖成交、Fee、Allocation 收益归因、多 Cluster/Runtime Scope、不可变
Snapshot、双视图、Risk Fail Closed、幂等、无损序列化、Replay、HWM/Drawdown 与固定时钟确定性。

Risk 测试必须使用固定 Clock 和精确 Decimal 输入，覆盖 Rule 顺序、Mandatory Profile、防绕过、Scope、Fail Closed、
Reservation 即时可见与幂等释放、OrderService 零副作用拒绝、Runtime/Cluster 隔离、Snapshot 不可变和重放确定性。
Demo 必须使用明确命名的 Placeholder 或 Virtual Broker，禁止连接真实 SDK；统一主场景禁止伪造成交。

## 组件与系统行为覆盖

按职责覆盖值对象、配置、生命周期、Registry、Loader、Event Bus、Cache、Repository、风控、Clock、撮合、因子和统计。
Rust 库的内部不变量用模块自测验证；经公开接口可观察的行为用功能测试验证。

系统功能覆盖：

- Engine 启停；
- 多 Runtime；
- 多 Cluster；
- 静态和动态加载；
- 订单到成交到持仓；
- Cache 落盘恢复；
- SIM streaming、continuity 与 durable recovery；
- Backtest；
- Web Service 调用。

## 4. 回归测试

使用 MyQuant 固定策略和固定数据。

比较：

- 信号；
- 订单；
- 成交；
- 持仓；
- 费用；
- 滑点；
- 收益；
- 回撤。

## 5. 资产模型测试

覆盖：

- 精度；
- Tick；
- Step；
- Currency；
- Money；
- A 股手数；
- 港股手数；
- 美股碎股；
- 期货乘数；
- 线性合约；
- 反向合约；
- 期权；
- Instrument 版本。

## 6. 确定性

测试应使用：

- 固定时钟；
- 固定随机种子；
- 固定数据；
- 固定配置；
- 明确舍入。

## 7. 时间模型测试

`tests/time_model` 固定覆盖 naive 拒绝、UTC 同瞬间、纳秒单位、IANA 时区、Venue 引用、
A 股午休、中国期货跨午夜夜盘、美股冬夏 DST、不存在/重复本地时间、提前收盘、Bar
`[start,end)`、历史 Calendar、Event/Domain 序列化、UTC/MARKET/USER_LOCAL 显示、
旧数据迁移和不同进程 `TZ` 的确定性。CI 应至少在 `UTC`、`Asia/Shanghai`、
`America/New_York` 环境运行关键测试；测试本身不得依赖机器本地时区。

## 8. Clock 测试

`tests/clock` 固定覆盖 Unix 纳秒转换和精度边界、Virtual/Backtest 单调推进、Timer deadline/sequence
顺序、100 次确定性重放、周期与取消、callback 重入和异常、Live 单调等待/单调读取/单 scheduler
thread/关闭，以及 Cluster 无推进权限。核心源码的直接系统时间读取由 AST 测试限制到
`core/clock.py` 白名单；测试不得使用长 sleep。

## 9. Event 与 MarketData Pipeline 测试

`tests/event` 覆盖强类型/纳秒 Event、Scope、FIFO、Subscription、显式 handler priority、满载策略、异常和
关闭。`tests/market_data` 覆盖默认/显式主周期、1m→3m/5m/15m Calendar 聚合、午休 Session 锚定、缺失和
不完整窗口、Cache/version、Required/Optional Indicator barrier、Snapshot 不可变与 closed-only、每时间片
单次回调、多 Cluster 共享/隔离、Backtest 与目标 Sim/Live 同语义和序列化 Event 重放。SIM realtime Virtual Broker
normal path、continuity 与 durable recovery 由独立 integration/recovery tests 证明。
多周期业务测试不得以 EventBus priority 或订阅注册顺序作为准备步骤。

## 10. RuntimeContext 测试

`tests/runtime` 覆盖 Runtime/Cluster 状态机、Context 禁止能力、Subscription 生命周期、Clock 所有权、
1m→3m 默认与显式主周期、同时间 Timer 先于 Bar、Cluster 失败隔离、多 Runtime 隔离、状态 DTO 和 100 次
确定性重放。测试必须确认停止/失败 Cluster 不再接收 Bar，Timer 与 Subscription 自动释放。

## 11. Order 测试

`tests/order` 覆盖 Request 校验、受控状态机、全部终态、部分成交均价、Overfill、request/trade/external
sequence 幂等、迟到 Accepted/Fill、Manager 索引、open order、Runtime 隔离、Cluster Scope、Context 禁止
能力、Placeholder、事件变更后发布、序列化和 100 次确定性重放。测试不得通过 EventBus handler 驱动
状态，不得由 Placeholder 生成 Accepted、Cancelled 或 Fill。

## 12. Position 测试

`tests/position` 覆盖 NETTING Long-only 开增减平、每轮新 PositionId、Average Cost、Linear PnL、账户/Cluster 独立
成本、T+1 Bucket、Restriction、Reservation 全阶段和券商冻结去重、Unallocated、不变量、Broker Difference/Severity/
阻断、不可变 Snapshot、序列化、重复与迟到 Trade、Runtime 隔离、Event 顺序及 100 次确定性重放。券商对账测试必须
断言本地总量没有被静默覆盖。
## Account / Virtual Broker 门禁

除组件单测外，统一环境必须覆盖账户初始化、完整买入、部分成交、Broker 确认撤单、T+1、多 Cluster 共享账户、Broker/Local
冲突以及重复/乱序回报。正常成交不得手工构造 Fill。完整 projection 包含 Local Account 与 Broker Account/Order Snapshot，
同一输入至少重放 100 次并比较全部结果。

## Execution Processor 门禁

必须覆盖 Runtime/Gateway/Account Scope、显式分派、Accepted/Rejected/Cancelled、部分/完全成交、部分成交后撤单、四类
Reservation、重复 Update、重复 Trade、迟到 Accepted、乱序 Trade、中途失败、字段级 Reconciliation、固定 Mutation Step、
Audit/Snapshot 序列化、Runtime 隔离和 100 次完整重放。中途失败断言不得出现 Order/Position/Ledger/Account 完整成功事实。
所有正常成交必须由 Virtual Broker 产生并通过 Queue；Fault/Test Adapter 也只能注入标准 Broker Update。

PR4.4.2 Long Close 验收还必须覆盖共享 Exact Cost Reducer、非整数/高精度 Decimal、`1000 → 700 → 300 → 0`、
`1000 → 750 → 500 → 250 → 0`、不同 Fill Price/Fee、正负零 realized PnL、订单累计费用、`PENDING_CANCEL` 下成交、
Partial Fill 后 Cancel/Reject/Expire、Fill/Terminal duplicate 与 conflict、Overfill/Reservation 不足，以及最终累计成本严格
归零。正式 OnlyEngine + Virtual Broker 必须分别覆盖 ONE_PER_BAR 跨 Bar和 ALL_DUE 同 Bar Close Fill Plan；Recovery 必须
覆盖 execute-before-publish、Commit 前后、mid-Projection、Outbox、Fill 1/2 checkpoint 与 A→B→C，并与无故障业务投影、
Broker checkpoint 和 result fingerprint 比较。Terminal Fact 不得进入 Trade Result。

## Market Data Source 门禁

必须覆盖 Source Capability、Envelope 序列化、UTC 半开范围、InMemory/CSV/Parquet、下推过滤、Queue 背压、Processor Scope、
重复/乱序、Session-aware Gap、Lookahead、稳定多流归并、Clock 唯一推进、Snapshot Quality、Runtime 隔离、完整交易闭环和至少
100 次 Replay。正常历史场景不得直接调用 Pipeline，实时场景不得绕过 MarketData Queue。
