# OnlyAlpha 会话交接说明

> 更新时间：2026-07-15（Asia/Shanghai）
>
> 当前分支：`master`
>
> 当前提交：`eea0d60 Merge pull request #11 from zongxin1993/zong_ledger`
>
> 交接前状态：除本文件外工作区原本干净；Position 与 Strategy Ledger 已合并到 `origin/master`。

## 1. 新会话先读什么

按以下顺序建立上下文：

1. `AGENTS.md`：项目强制边界、Only 命名、文档和测试要求。
2. `docs/architecture_principles.md`：已经稳定的架构不变量。
3. `docs/integration_vertical_slice.md`：新加入的持续集成/纵切面强制要求；当前尚未真正落地，见第 10 节。
4. 当前任务对应 Prompt（Position 为 `prompts/position_component_implementation.md`，Ledger 为
   `prompts/strategy_ledger_component_implementation.md`）。
5. 组件文档：`docs/order.md`、`docs/risk.md`、`docs/position.md`、`docs/strategy_ledger.md`。
6. ADR 0011～0014，了解 Order、Risk、Position、Strategy Ledger 的边界和决定。

不要只读 `docs/roadmap.md` 判断现状。该文档的“当前状态”仍停留在 2026-07-13，未完整反映后来合并的 Order、Risk、
Position 和 Strategy Ledger。

## 2. 项目总体认知

OnlyAlpha 是 MyQuant 的领域化重构，不是目录搬迁或兼容层。当前方向是模块化单体、Pure Financial Domain、强类型金融值、
Runtime 单写入者和不可变 Snapshot。

长期不变量：

- Engine 可以管理多个彼此隔离的 Runtime。
- Runtime 隔离 Clock、EventBus、Order、Risk、Position、Allocation、Strategy Ledger 等可变状态。
- Cluster 是策略运行单元，只能通过受限 `ctx` 能力访问 Runtime，不得直接获取 Manager、Gateway、数据库或可变 Cache。
- 外部 SDK 数据必须标准化后进入领域/应用边界；SDK callback 不得直接修改 Manager。
- Domain 不依赖 Runtime、Cluster、Gateway、DB、Web、Cache、EventBus 或 Backtest。
- 所有金融数值都应具有精度、单位、币种和合法范围；核心交易逻辑禁止裸 `float`。
- UTC 是绝对时间真值；市场日期、TradingDay 和 Session 由 IANA 时区与 TradingCalendar 解释。
- Event 只表达已经发生的事实，不承担 Order/Risk/Position/Ledger 状态机。
- 目前接受早期破坏性改进；不要为了 MyQuant 兼容牺牲未来多市场抽象。

## 3. 已实现的基础设施

当前已经存在并有测试的主要部分：

- 强类型 Domain：Currency、Money、Price、Quantity、Rate、Multiplier、各类 ID、Instrument、MarketRule、Bar/Tick、
  Order/Fill/Trade DTO、UTC Timestamp、TradingDay、TradingCalendar。
- Clock：Live/Backtest Clock、Timer、固定时钟和确定性测试。
- Event：不可变纳秒安全 Envelope、有界同步 EventBus、Scope 和顺序语义。
- Engine/Runtime/Cluster：生命周期、多个 Runtime、多个 Cluster、受限 Context、Timer/Bar 分发和异常隔离。
- Market Data：Bar subscription、聚合、Cache、Pipeline、Snapshot、Indicator pipeline 基础。
- Cache/Storage：Memory Cache 与 SQLite Storage 基础边界。
- Order、Risk、Position、Strategy Ledger 四个交易状态域（详见后续章节）。

Live/Paper/Research Runtime 目前仍主要是类型标记，完整资源装配集中在 Backtest Runtime。没有真实行情、真实券商连接、完整
回测历史驱动或撮合器。

## 4. Order 当前实现

真值与边界：

- 每个 Runtime 一个 `OnlyOrderManager`，Cluster 通过 `ctx.orders` 使用 Cluster-scoped Query/Command View。
- OrderRequest 与内部 Order 分离；外部只能获得 frozen `OnlyOrderSnapshot`。
- 已实现 CREATED/SUBMITTED/ACCEPTED/PARTIALLY_FILLED/FILLED/PENDING_CANCEL/CANCELLED/REJECTED/EXPIRED/FAILED
  等状态及乱序/重复回报处理。
- Order、ClientOrder、VenueOrder、Trade/VenueTrade 标识和外部 sequence 都有幂等约束。
- `OnlyExecutionService`/`OnlyTradeGateway` 是窄 Port；目前 Runtime 使用 `OnlyPlaceholderExecutionService`，它只表示传输层收到，
  不会产生真实 Venue Accepted、Fill 或 Trade。
- 标准化 Gateway Update 由 `OnlyOrderUpdateProcessor` 在 Runtime 线程处理。

提交顺序目前为：

```text
ctx.orders.submit
→ Risk 同步审批
→ 创建 Order
→ Risk Reservation
→ Position Reservation（卖单）
→ Strategy Cash Reservation（买单）
→ Placeholder Execution
→ Order 标记 SUBMITTED
```

重要限制：Fill 更新目前只修改 Order 并消费 Reservation；它不会自动生成 `OnlyPositionTrade`，也不会自动依次更新 Account
Position、Cluster Allocation 和 Strategy Ledger。这个缺口属于缺失的完整 `ExecutionProcessor`/纵切面编排，不要误认为已经
端到端完成。

关键文件：

- `src/onlyalpha/order/service.py`
- `src/onlyalpha/order/manager.py`
- `src/onlyalpha/order/execution/processor.py`
- `src/onlyalpha/order/position_port.py`
- `src/onlyalpha/order/cash_port.py`

## 5. Risk 当前实现

- 每个 Runtime 独占 `OnlyRiskService`、Pipeline、Profile、State、Reservation、Kill Switch 与审计。
- Rule Scope、强制 System Rule、Cluster Profile、权限、Instrument/MarketRule 检查和 Fail Closed 已实现。
- 每次 submit 都重新执行最终 Pre-Trade Risk；同一回调内 Risk Reservation 立即可见。
- 卖单读取 Account Position 和 Cluster Allocation 的有效可用量，取更保守结果。
- Risk Context 已接入 `OnlyStrategyLedgerRiskViewPort`；Ledger 非 ACTIVE 时新订单 Fail Closed。
- Cluster 只能读取 `ctx.risk` Snapshot，不能执行 evaluate/reserve/release 或修改规则。

限制：

- 没有完整 Account Risk 数据源。
- Strategy Ledger Risk 目前主要执行状态阻断；可用资金的最终底层保护由 Cash Reservation 完成，尚未形成完整的策略资金 Rule
  家族。
- Risk Reservation 没有持久化恢复，部分成交的完整名义金额转换仍待 ExecutionProcessor。

关键文件：`src/onlyalpha/risk/`、ADR 0012、`docs/risk.md`。

## 6. Position 与 Allocation 当前实现

每个 Runtime 从构造起独占：

```text
OnlyPositionManager                 Account 真实仓位状态
OnlyPositionAllocationManager       Cluster 归因仓位 + Unallocated
OnlyPositionReservationManager      卖单本地仓位预占
OnlyPositionReconciliationService   Broker Snapshot 差异和阻断
```

第一版已实现：

- NETTING Long-only。
- Average Cost。
- Linear PnL。
- A 股 T+1 Settlement Bucket（SETTLED/UNSETTLED）。
- Available Quantity 从结算、冻结、Restriction、Risk Reservation 和 broker available 保守派生。
- Cluster 只能卖出自己的 Allocation；账户有总仓位并不授权 A 使用 B 的归因仓位。
- 无法归因的成交/差额进入 `OnlyUnallocatedPosition`，不会被猜测分配。
- Trade 按 trade/execution/venue trade ID 幂等，稳定顺序为 external sequence → ts_event → trade ID。
- Broker Position Snapshot 不覆盖本地历史；AuthorityPolicy 与 ReconciliationService 产生 Difference、Conflict、Severity、
  Action，严重冲突进入 RECONCILING 并阻断。
- Snapshot、DTO、Reservation、Difference/Reconciliation 均不可变、可序列化、确定。

没有实现 HEDGING、Short、FIFO/LIFO、Inverse/Quanto、公司行动、真实 Gateway 或数据库 Repository。

关键文件：`src/onlyalpha/position/`、ADR 0013、`docs/position.md`、`tests/position/test_position_component.py`。

文档漂移提醒：`docs/position.md` 的“已知限制”仍写着没有 `StrategyLedgerManager`，这在 Ledger 合并后已经过时，应在下一轮
文档清理中修正。

## 7. Strategy Ledger 当前实现

每个 Runtime 独占 `OnlyStrategyLedgerManager`；每个 Cluster 按以下 Key 拥有独立虚拟账：

```text
RuntimeId / AccountId / ClusterId / BaseCurrency
```

券商真实账户账和策略虚拟账严格分离。策略收益只接受自身 Trade、Fee 和 Position Allocation before/after，不使用账户合并
均价，也不按账户总收益比例分摊。

第一版已实现：

- Fixed Capital；Runtime 默认 `1,000,000.00 CNY`，可用 `OnlyRuntimeConfig.strategy_initial_capital` 配置，Cluster 可用同名
  value 覆盖。
- 单币种、Long-only 股票/ETF、Linear PnL。
- Cash Entry、Fee Entry、买单 Cash Reservation 和 Reservation 生命周期。
- 买入 `cash -= notional + fee`，卖出 `cash += notional - fee`。
- Realized PnL 从 Allocation realized before/after 差值验证；Position Cost Delta 同样从 Allocation 验证。
- Allocation × Mark Price × Multiplier 生成 Position Cost、Market Value 与 Unrealized PnL。
- Cash View：`cash + market_value`。
- PnL View：`initial + external_cash_flow + realized + unrealized - fees`。
- 两个 Equity View 不一致时进入 RECONCILING 并设置质量标记；Risk 阻断新订单。
- Net PnL、Simple Return、Daily PnL/Return、High Water Mark、Drawdown、Maximum Drawdown。
- `ctx.ledger` 是绑定 Runtime/Account/Cluster 的只读 View，没有 apply/reserve/deposit/reset 方法。
- Trade/Fee/CashFlow/Reservation/Valuation 幂等、迟到 Trade 阻断、内存 Repository、Event Publisher、无损 JSON 和显式 Command
  Replay。

重要实现细节/限制：

- 发生 External Cash Flow 后，第一版 Simple Return 返回 `None`，没有伪装 TWR/MWR。
- Cash Reservation Adapter 对 LIMIT BUY 使用订单价格；MARKET BUY 必须能从当前 Cluster MarketData Snapshot 得到确定参考价，
  否则 Fail Closed。
- Adapter 初始预计费用为零，Fill 的实际费用在消费预占时计入；超出预占仅在剩余现金仍足够时允许。
- Order Fill 消费 Cash Reservation，但完整 Ledger Trade Accounting 仍必须在 Allocation 更新后显式调用，当前缺少统一
  ExecutionProcessor。
- Replay 第一版按 Account+Cluster 查找单币种 Ledger；在当前单币种范围成立，多币种前必须重新设计消歧。
- 没有完整 AccountManager、真实券商现金同步、多币种、保证金、融资融券、Funding、分红、自动再平衡、策略间转账、自动
  强平或策略内部净额化。

关键文件：

- `src/onlyalpha/strategy_ledger/manager.py`
- `src/onlyalpha/strategy_ledger/entities.py`
- `src/onlyalpha/strategy_ledger/models.py`
- `src/onlyalpha/strategy_ledger/reservations.py`
- `src/onlyalpha/strategy_ledger/valuation.py`
- `src/onlyalpha/strategy_ledger/replay.py`
- `src/onlyalpha/strategy_ledger/views.py`
- ADR 0014、`docs/strategy_ledger.md`、`docs/strategy_ledger_acceptance_report.md`

ADR 使用 0014 是因为 Prompt 建议的 0011 已经被 Order ADR 占用。

## 8. 当前实际可运行链路

目前 Backtest Runtime 的真实链路可以到达：

```text
Bar
→ MarketData Pipeline / Aggregation / Indicator
→ immutable Snapshot
→ Cluster on_bar
→ ctx.orders.submit
→ Risk
→ Order + Risk/Position/Cash Reservations
→ Placeholder Execution
→ SUBMITTED Order Event
```

外部测试可以再显式注入 Gateway Accepted/Fill Update，但当前没有一个正式应用服务把 Fill 原子编排成：

```text
Fill
→ normalized PositionTrade
→ Order Update
→ Account Position
→ Cluster Allocation / Unallocated
→ Strategy Ledger Trade Accounting
→ Valuation
→ Final Snapshot
```

因此，Order/Risk/Position/Ledger 各组件单独正确，不等于完整交易 Vertical Slice 已经完成。

## 9. 当前验证基线

在 2026-07-15、提交 `eea0d60` 上重新执行：

```text
UV_CACHE_DIR=/tmp/onlyalpha-uv-cache uv run pytest -q
UV_CACHE_DIR=/tmp/onlyalpha-uv-cache uv run ruff check .
UV_CACHE_DIR=/tmp/onlyalpha-uv-cache uv run ruff format --check .
UV_CACHE_DIR=/tmp/onlyalpha-uv-cache uv run mypy src/onlyalpha
```

结果：

- Pytest：`175 passed in 0.72s`。
- Ruff check：通过。
- Ruff format check：275 files already formatted。
- Mypy：137 source files，无问题。
- Strategy Ledger 九个 Demo 在上一实现会话中逐个运行，均退出码 0。

运行 `uv` 时建议始终设置 `UV_CACHE_DIR=/tmp/onlyalpha-uv-cache`，避免缓存目录权限问题。

## 10. 最高优先级缺口：Integration Vertical Slice

`docs/integration_vertical_slice.md` 已在 Ledger 提交中加入并声明为所有新组件的强制要求，但当前仓库没有与该文档匹配的实现：

- 未找到 `OnlyIntegrationEnvironment`。
- 未找到 `examples/integration_demo/`。
- 未找到 `tests/integration/test_vertical_slice_replay.py`。
- 未找到 `docs/reports/<component>_integration_report.md`。
- `tests/integration/` 目前只有基础 `test_engine_runtime.py`，没有 Order→Risk→Execution→Position→Allocation→Ledger 完整链路。
- `scripts/run_component_validation.sh` 只有四行命令模板，其中 `tests/<component>` 是占位符；引用的 integration demo 和 replay
  test 也不存在，因此不是可直接执行的脚本。

这意味着：`docs/strategy_ledger_acceptance_report.md` 中的 `ACCEPTED` 对 Ledger 组件自身是成立的，但若按后来写入的 Vertical
Slice 强制标准重新审计，整体集成验收仍未完成。新会话不应继续宣称完整端到端已验收，直到上述基础设施、场景、历史回归和
报告补齐。

## 11. 建议下一步执行顺序

建议把“统一 Vertical Slice”作为下一项独立、边界清晰的任务：

1. 先设计 `OnlyIntegrationEnvironment`，只组装现有正式 Manager/Service/Context，不复制组件逻辑。
2. 提供明确命名的 deterministic Execution Test Adapter/Placeholder，把标准化 Fill 转为 `OnlyPositionTrade`；不要实现真实券商
   SDK 或完整撮合器。
3. 建立单写入者 Execution 编排：Order Update → Position → Allocation/Unallocated → Strategy Ledger Accounting。
4. 明确失败原子性和重试语义，尤其是 Position 已更新但 Ledger 失败的恢复策略；重大决定需要 ADR。
5. 在 `examples/integration_demo/scenarios/` 建立至少：买入 T+1、卖出收益、双 Cluster 独立归因、Reservation、重复/迟到 Fill、
   Reconciliation 阻断、Replay。
6. 在 `tests/integration/` 固定 Clock 和 ID，验证跨组件数量、现金、费用、PnL、Equity、Scope、Event 顺序和最终 Snapshot。
7. 实现 deterministic replay，比较完整 Final Snapshot/Event 序列。
8. 将 `scripts/run_component_validation.sh` 改为有 shebang、`set -euo pipefail`、无占位符、可直接运行的真实验证脚本。
9. 生成 `docs/reports/strategy_ledger_integration_report.md`，并补 Position/Risk/Order 的集成报告或明确历史组件豁免策略。
10. 更新 `docs/roadmap.md`、`docs/architecture.md` 状态真值清单和 `docs/position.md` 的过时限制。

不要在这个纵切面任务中顺便实现完整 AccountManager、真实 Broker SDK、自动强平、复杂撮合或多币种；这些会显著扩大授权和
设计范围。

## 12. 容易踩坑的地方

- 不要用账户平均成本计算 Cluster PnL；必须以该 Cluster Allocation before/after 为权威。
- 不要让 Strategy Ledger 再维护独立 Position Cost Basis；它只验证和消费 Allocation 结果。
- 不要把 Broker Snapshot 直接写入 Position；必须经过 AuthorityPolicy/ReconciliationService。
- 不要把 A 股 T+1 写死到通用 Instrument/Engine；通过 Market/Settlement 规则表达。
- 不要用 UTC `date()` 推导 TradingDay；通过 Calendar。
- 不要在 Event handler 中驱动业务状态修改；函数调用先成功，Event 后发布。
- 不要把 Placeholder Execution 的 “received” 当成 Venue Accepted 或 Fill。
- 不要让 Cluster 获得 Manager；`ctx.orders`、`ctx.positions`、`ctx.risk`、`ctx.ledger` 都必须是 Scope 受限只读/命令 View。
- 不要把 Risk Reservation、Position Reservation 和 Strategy Cash Reservation 合并成一种 Reservation；它们保护不同不变量。
- 不要为了测试通过降低 Fail Closed、幂等、Scope 或不可变性断言。
- 新增测试后立即跑相关测试，再跑全量 pytest、Ruff、Mypy；不要等到最后一次性验证。

## 13. Git 与工作区说明

- Position 已通过 PR #10 合并，merge commit `5d64625`，实现 commit `1f88822`。
- Strategy Ledger 已通过 PR #11 合并，merge commit `eea0d60`，实现 commit `294c4c8`。
- 关闭本会话前，仓库与 `origin/master` 同步；写入本交接文件后，预期唯一未提交变更是 `HANDOFF.md`。
- 不要修改 MyQuant，不要启动真实交易，不要使用真实账户验证。

## 14. 快速检查清单

新会话开始后先执行：

```bash
git status --short
git log -5 --oneline --decorate
UV_CACHE_DIR=/tmp/onlyalpha-uv-cache uv run pytest -q
UV_CACHE_DIR=/tmp/onlyalpha-uv-cache uv run ruff check .
UV_CACHE_DIR=/tmp/onlyalpha-uv-cache uv run ruff format --check .
UV_CACHE_DIR=/tmp/onlyalpha-uv-cache uv run mypy src/onlyalpha
```

然后确认当前用户请求是否要求落实 Vertical Slice。如果是，先以第 10、11 节为工作边界，不要从头重写已经通过单元测试的
Order/Risk/Position/Strategy Ledger。
