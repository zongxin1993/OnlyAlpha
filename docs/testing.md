# 测试规范

## 正式测试分层与统一入口

测试层级为 `unit`、`contract`、`architecture`、`integration`、`scenario`，每个测试必须恰好属于一个层级。
`recovery`、`conformance`、`external`、`performance`、`exhaustive`、`miniqmt` 是可正交附加的关注点；`slow`、`requires_network`、`requires_tushare`、
`requires_local_qmt`、`requires_broker_account`、`windows` 是附加属性。根 `conftest.py` 根据明确目录和文件语义
补充缺失的主 Marker，并在收集期拒绝不完整的 External/Broker Account 标记。显式 Marker 始终优先。

统一入口如下：

```powershell
uv run python scripts/test_suite.py fast
uv run python scripts/test_suite.py integration
uv run python scripts/test_suite.py ashare
uv run python scripts/test_suite.py recovery
uv run python scripts/test_suite.py miniqmt-contract
uv run python scripts/test_suite.py miniqmt-local
uv run python scripts/test_suite.py core-full
uv run python scripts/test_suite.py exhaustive
uv run python scripts/test_suite.py release
```

所有通道打印实际 pytest 参数、返回真实退出码，并将计数、耗时、最慢测试、Marker 和路径分布写入
`test-results/metrics/<lane>.json`。即使测试失败，指标仍会写出并保留真实 pytest 退出码。可用 `--workers N`、`--dist worksteal`、`--durations N` 或 `--no-parallel`
覆盖并行策略；定位进程级、SQLite 锁、顺序敏感或调试器问题时关闭 xdist。

`fast` 证明纯组件、公共合同和架构边界；`integration` 证明最短离线纵切面与 scenario smoke；`ashare` 只运行
离线 A 股 conformance；`recovery` 独立运行普通 checkpoint/restart/fault correctness；`core-full` 覆盖全部普通 Workspace 离线 correctness；`exhaustive` 保留 100-run 和完整组合矩阵。
长测试必须标记 `slow` 或 `recovery`。产品纵切面必须经过 `OnlyEngine`；Analytics、Report、Artifact、Collector
应优先复用固定 Result/Snapshot fixture。

A 股申报前规则测试必须覆盖 2026-07-06 制度切换、主板/创业板/科创板风险警示矩阵、Tick 舍入上下限、五类交易阶段、
停牌/Inactive 分离、科创板最低数量与递增、零股全量清仓、固定 Evaluation 顺序、100 次确定性、Checkpoint 权威变化
拒绝以及结构化 Artifact。Risk/Order 测试不得另建 Session、Price 或 Quantity Validator。

MiniQMT Contract 使用 Fake XtData/XtTrader，验证原始 SDK 形状到领域对象的转换，不导入真实 `xtquant`；
Golden Dataset 是只读冻结输入。`miniqmt-local` 仅串行运行，要求 Windows、`userdata_mini_path`（或
`ONLYALPHA_MINIQMT_PATH`）和可导入的 `xtquant`。真实查询必须显式 opt-in；真实下单还必须具有
`requires_broker_account`，且永不进入普通 pytest、离线或 `miniqmt-local` 通道。

`release` 依次运行 Ruff、Ruff format check、Core/Provider mypy、版本一致性、Core Full、Recovery、A-share、MiniQMT Contract 和包构建。
日常修改运行最窄的正确通道；执行交易/恢复变更时必须运行 Recovery；发布前运行 Release。外部环境不满足时应记录
“未执行”，不得记为通过。当前人工基线见 `docs/reports/test_suite_performance_baseline.md`。

### 固定测试数据与重生成

标准 Result Fixture 位于 `tests/fixtures/results/`，由正式 `OnlyEngine` 场景生成；Analytics、Report、Artifact、
Collector 等纯下游测试应读取该不可变结果，不应为了验证渲染或序列化而重复运行 Engine。正式结果合同变化后，先确认不是
业务回归，再显式执行：

```powershell
uv run python scripts/regenerate_result_fixtures.py
```

Recovery Baseline 位于 `tests/fixtures/recovery/`。提交的是规范投影、Manifest 和内容寻址的只读 SQLite 压缩源；测试运行时
在 `.test-cache/recovery/` 原子物化并校验完整性，再复制到各自的 `tmp_path`。不得提交 `.test-cache/`，也不得让 Worker
共享可写数据库。需要维护基线时显式执行：

```powershell
uv run python scripts/regenerate_recovery_baselines.py
```

MiniQMT 冻结数据位于 `tests/fixtures/miniqmt/cn_a_share_v1/`。第一版只承诺未复权历史日 Bar；历史 ST、停牌和 effective
reference 明确缺失。离线 Reader 校验文件指纹后，经标准 MarketData Inbound/Pipeline 进入 `OnlyEngine`，不导入
`xtquant`、不访问网络。仅在本地 QMT 可用时重新采集：

```powershell
uv run python scripts/capture_miniqmt_golden.py --userdata-mini "C:\path\userdata_mini" `
  --instrument 600000.XSHG --bar 1d --start 2025-01-02 --end 2025-01-10 `
  --adjustment none --output tests/fixtures/miniqmt/cn_a_share_v1
```

### 性能测量与比较

Lane metrics 写入 `test-results/metrics/`，包括阶段耗时、Worker/分发模式、机器与 Git 信息，以及测试侧观测到的缓存命中、
Engine Run、SQLite 创建和 Parquet 写入计数。完整 Worker 矩阵使用三次运行中位数：

```powershell
uv run python scripts/benchmark_test_lanes.py --lanes fast integration recovery core-full `
  --workers 4 6 8 auto --dist load worksteal --repeat 3
uv run python scripts/compare_test_metrics.py `
  docs/reports/test_suite_performance_targets.json test-results/metrics/recovery.json --lane recovery
```

性能阈值当前是软警告，不得自动覆盖人工确认的目标文件。PR/Main 的 Static、各测试 lane 和 Build 独立并行，最终由
Quality Gate 汇总；Nightly 额外运行 Exhaustive 和指标采集。真实 MiniQMT 查询仅在自托管 Windows
Runner 串行运行；真实订单属于独立手动工作流，P0 不自动提交订单。原跨平台 distribution/install Smoke 保留在
`ci.yml`，但只允许手动触发，避免在 PR 重复运行三平台 Full/Recovery。

以下旧章节保留为具体组件覆盖要求；如命令或层级描述冲突，以本节为准。

## Product-style backtest acceptance

成品式 Demo 还必须覆盖配置加载、正式 Runtime API、Calendar-aware synthetic source、指标精确值、Warmup、Context 权限、
VirtualBroker/ExecutionProcessor 成交、T+1、固定 Seed 噪声、结果导出和至少 100 次完整确定性重放。指纹比较必须覆盖 MarketData
Audit、Clock、指标序列、策略信号、Order/Trade ID、Execution Audit、稳定 Event 序列及最终 Snapshot。

Strategy Ledger 必测固定资金、连续 Cash Reservation、买卖成交、Fee、Allocation 收益归因、多 Cluster/Runtime Scope、不可变
Snapshot、双视图、Risk Fail Closed、幂等、无损序列化、Replay、HWM/Drawdown 与固定时钟确定性。

Risk 测试必须使用固定 Clock 和精确 Decimal 输入，覆盖 Rule 顺序、Mandatory Profile、防绕过、Scope、Fail Closed、
Reservation 即时可见与幂等释放、OrderService 零副作用拒绝、Runtime/Cluster 隔离、Snapshot 不可变和重放确定性。
Demo 必须使用明确命名的 Placeholder 或 Virtual Broker，禁止连接真实 SDK；统一主场景禁止伪造成交。

## 1. 层次

```text
tests/unit
tests/integration
tests/regression
tests/property
```

## 2. 单元测试

覆盖：

- 值对象；
- 配置；
- 生命周期；
- Registry；
- Loader；
- Event Bus；
- Cache；
- Repository；
- 风控；
- Clock；
- 撮合；
- 因子；
- 统计。

## 3. 集成测试

覆盖：

- Engine 启停；
- 多 Runtime；
- 多 Cluster；
- 静态和动态加载；
- 订单到成交到持仓；
- Cache 落盘恢复；
- Paper；
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
单次回调、多 Cluster 共享/隔离、Live/Backtest 同语义和序列化 Event 重放。多周期业务测试不得以 EventBus
priority 或订阅注册顺序作为准备步骤。

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
