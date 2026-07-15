# Account 与 Virtual Broker 集成报告

- 日期：2026-07-15
- 结论：**ACCEPTED**
- ADR：`docs/adr/0015-account-broker-ports-and-virtual-broker.md`

## 1. 新增与修改文件

新增组件目录：

- `src/onlyalpha/account/`：Account ID、枚举、不可变模型、Manager、Query/Context View、Repository、Event、Reconciliation；
- `src/onlyalpha/broker/`：Capability、Connection/Trading/Query Ports、标准 Request/Result/Snapshot/Update、Execution adapter；
- `src/onlyalpha/virtual_broker/`：配置、独立 Store、Gateway、Matching、Commission、Slippage、Latency、Scheduler/Queue；
- `tests/account/`、`tests/broker/`、`tests/virtual_broker/`：组件单元测试；
- `examples/account_demo/`、`examples/virtual_broker_demo/`：独立 Demo；
- Integration Scenario 013–018：Account、部分成交、撤单、多 Cluster、冲突、重复/乱序；
- `docs/account_broker_component_analysis.md`、`docs/account.md`、`docs/broker_gateway.md`、`docs/virtual_broker.md` 与 ADR 0015。

修改了 Runtime/Context/Risk、统一 Integration Environment、既有 001–012 场景衔接、确定性重放，以及 architecture、runtime、
order、risk、position、strategy ledger、event、testing、integration vertical slice 和 architecture principles 文档。没有删除、
skip 或放宽任何既有测试和场景。

## 2. 组件边界

### Account

每个 Runtime 构造时独占一个 `OnlyAccountManager`。Manager 是本地账户现金、冻结、费用、账户级 PnL、持仓市值、权益、状态与
Reservation 的唯一写入者；外部只获得 frozen `OnlyAccountSnapshot`。现金与权益是强类型 `OnlyMoney`，第一版明确限制为 CNY
现金账户与 Long-only 股票/ETF。

### Strategy Ledger 与 Account

Account 是共享账户合并真值；Strategy Ledger 是 Runtime/Account/Cluster 维度的虚拟策略账。两者分别维护现金 Reservation、
费用和 PnL，不共享 Entity、dict、Repository 或 Manager。Ledger 成本只来自该 Cluster Allocation，Account 估值只来自账户
Position，因此多个 Cluster 共用账户时不会用账户合并成本污染策略归因。

### Broker Ports 与 Capability

Broker 边界拆为 Connection、Trading、Account、Position、Order Query、Trade Query Port，并组合为 `OnlyBrokerGateway`。
Capability 包括连接、认证、下单、撤单、各类查询、推送、Market/Limit 与 Partial Fill。同步 Submit/Cancel Result 只表达
`request_received`，不表达 Accepted/Cancelled；不支持能力返回显式状态/异常，不使用 `NotImplementedError` 继续运行。

## 3. Virtual Broker

`OnlyVirtualBrokerGateway` 独占三套外部真值 Store：Account、Order、Trade。源码依赖审计确认它不导入或持有
OrderManager、PositionManager、AccountManager、AllocationManager 或 StrategyLedgerManager。Broker Snapshot 是复制出的
immutable DTO，本地 Manager 与 Broker Store 没有共享引用。

### Matching Engine

撮合通过可替换 `OnlyMatchingEngine` Port，Gateway 不内嵌成交判断。默认 `OnlyNextBarMatchingEngine` 使用 Bar N+1：BUY LIMIT
检查 low，SELL LIMIT 检查 high，成交价策略固定 LIMIT_PRICE；Market 使用下一 Bar open。最大单次成交量可配置以产生部分成交，
不使用未来 Bar、系统时间或随机数。

### Commission、Slippage、Latency

- Commission：Fixed 与可配置 CN Equity（commission/minimum/stamp duty/transfer fee）；
- Slippage：None 与 Fixed exact-price offset，Limit 最终价格不会劣于限价；
- Latency：Zero 与 Fixed，覆盖 submit/accept/fill/cancel/query nanoseconds；
- Scheduler：稳定 `(due_ns, sequence)` 顺序，只读取 Runtime Clock，不调用 sleep。

### Broker Update Queue

Gateway 只调用 inbound callback，把 immutable Broker Update 放入 Runtime 拥有的有界队列。Runtime 在单写入者线程按 update ID
去重，再调用正式 Manager/Service。Broker Store 不能直接修改本地状态。队列满显式失败，不使用无限队列。

## 4. Account Reconciliation、Risk 与 Context

Account Reconciliation 逐字段比较 Local/Broker Snapshot。cash/equity 冲突进入 `RECONCILING` 并阻断新订单，Broker 值不静默
覆盖本地现金历史；available/frozen 差异保留显式 Difference/Conflict。Position Update 复用现有 Position Authority Policy 与
Reconciliation。

Risk 通过 Risk-owned `OnlyAccountManagerRiskView` 读取 Account immutable Query，BUY 按 Limit 或当前 Snapshot 参考价检查币种与
available cash；Account 非 ACTIVE、数据缺失或额度不足时 Fail Closed。`ctx.accounts` 仅提供绑定账户的 `current/get`，不暴露
Manager、Command、Broker、Queue 或内部容器。

## 5. ExecutionService 与 Vertical Slice

Runtime 可保持明确 Placeholder（未配置 Broker 时），或装配 `OnlyBrokerExecutionService` 与 Virtual Broker。统一主链已变为：

```text
Bar → MarketData Pipeline → Snapshot → Cluster → ctx.orders.submit()
→ Risk → Account/Strategy/Position Reservations → ExecutionService
→ Virtual Broker → Next-Bar Matching → Broker Update → Runtime Inbound Queue
→ Order → Position → Allocation → Strategy Ledger → Account → Risk Update
→ fact Event → Final Local/Broker Snapshot
```

正常买入、部分成交、撤单和卖出不再调用手工 `_accept/_fill`，也不构造 `OnlyPositionTrade` 绕过 Gateway。仅冲突与乱序场景使用
明确的 fault adapter，通过 Runtime 正式 inbound Port 注入标准化 Broker Update。

## 6. Integration Scenarios

保留并通过历史 001–012：Runtime 启动、1m→3m、Order、Risk、买入、Position、Allocation、Ledger、T+1、卖出、已实现收益、
最终 Snapshot。新增并通过：

- 013 Account 初始化与 `ctx.accounts`；
- 014 40/100 部分成交与 Local/Broker Cash Reservation 一致；
- 015 Broker 确认撤单后释放 Risk/Account/Strategy Reservation；
- 016 两个 Cluster 共享一个 Account，同时保持 Allocation/Ledger 隔离；
- 017 Broker/Local 现金冲突显式阻断且不覆盖本地；
- 018 重复 update ID 幂等，乱序 Accepted 不令 FILLED 回退。

## 7. 测试结果

| 验证层 | 结果 |
|---|---:|
| 修改前历史全量基线 | 196 passed |
| Account 单元测试 | 8 passed |
| Broker Ports 单元测试 | 3 passed |
| Virtual Broker 单元测试 | 6 passed |
| Integration 自动化 | 28 passed in 2.91s |
| 完整全量测试 | 219 passed in 3.55s |
| 18 个 Integration Demo 场景 | 全部 PASS |
| 确定性重放 | 100 次与 baseline 完全一致，1 passed in 2.38s |
| Account Demo / Virtual Broker Demo | 均运行成功 |
| Ruff | All checks passed |
| Ruff format check | 338 files already formatted |
| mypy | 164 source files，0 issues |

最终统一命令 `bash scripts/run_component_validation.sh` 再次得到：219 全量、28 Integration、18 Demo、100 次 Replay、ruff、
format 和 mypy 全部通过。

## 8. 关键不变量

- Runtime/Cluster Scope 隔离；各 Runtime 的 AccountManager、Broker、Order/Risk/Position/Ledger 实例不同；
- Context 只暴露 immutable View，所有 Snapshot dataclass frozen；
- Virtual Broker 与所有 Manager 物理分离；
- Submit received != Accepted，Cancel received != Cancelled；
- Broker Update 只经有界 Runtime inbound queue；
- EventBus 无生产状态机订阅者；
- Risk Reject/Error 不创建 Order、不调用 Execution；
- Cash/Position/Strategy Reservation 不重复预占，Fill/Cancel 后正确消费或释放；
- Account Position = Allocation Sum + Unallocated；
- 当日买入 Broker 与 Local 均不可卖，次日分别结算并对账；
- Cluster 不能卖其他 Cluster Allocation；
- Ledger 使用 Cluster Allocation 成本，Account 使用账户 Position；
- 重复 Fill/Update 不重复累计，迟到回报不回退状态；
- Local/Broker 冲突不静默覆盖；
- 相同输入的 ID、Update Sequence、Order、Position、Allocation、Ledger、Account、Broker Snapshot 与 Event Trace 一致；
- 生产 import graph 无循环依赖；新增组件无 system time、sleep 或 random 调用。

## 9. Placeholder 与测试适配器

`OnlyPlaceholderExecutionService` 仅保留给没有配置 Broker 的既有 Runtime/单测，仍不制造 Accepted/Fill/Trade。统一主场景使用
Virtual Broker。017/018 使用明确 fault adapter 通过 Runtime inbound Port 注入标准化冲突/乱序事实；它不访问 Manager 内部状态。

## 10. 发现并修复的问题

- 原集成主链手工接受/成交，无法验证 Broker 边界：已由 Virtual Broker 自动链替换；
- Runtime 缺少 Account 真值、Account Risk View 与 `ctx.accounts`：已装配；
- Broker callback 没有统一受控入口：新增有界 Runtime inbound queue 与 update-id 幂等；
- Strategy Ledger 曾是唯一现金预占：增加独立 Account Reservation，并由 Runtime 协调回滚/消费/释放；
- T+1 只验证本地 Position：Virtual Broker 增加独立 settled quantity 与日切 Snapshot；
- 可用资金 Risk Rule 只检查快照存在：现在检查 Account 状态、币种与金额；Market Order 使用当前 Snapshot 参考价；
- 取消与同一 Clock Bar 的顺序可能先撮合：Scheduler 现在在 matching 前处理到期取消；
- Broker equity 曾按持仓成本估算：改为使用最新 Bar mark；
- Account 反向依赖 Risk DTO：改为 Risk-owned adapter，恢复内向依赖方向。

## 11. 已知限制

- 仅完整支持单 CNY 现金账户、股票/ETF Long-only；保证金、多币种、Short、期货/期权未实现；
- Matching 是确定性最小 OHLC 模型，不模拟盘口、成交量争用、涨跌停、交易所队列或 corporate action；
- Broker reconnect、丢包补偿、持久化 update journal、进程崩溃事务恢复尚未实现；
- Reconciliation 第一版阻断冲突但不自动采用 Broker 权威值；人工/应用层恢复工作流尚未实现；
- Live/Paper Runtime 尚未完成真实异步线程与 Gateway 装配；当前完整链由 Backtest Runtime 验证；
- Account/Position/Ledger 跨 Manager 更新仍是显式顺序而非持久化原子事务；后续 ExecutionProcessor 需要保留当前语义并增加恢复。

## 12. 一票否决项审计

未发现一票否决项：没有 Manager 共享、callback 直写、同步 Accepted/Cancelled、Gateway 内不可替换撮合、系统时间/sleep、SDK
对象泄漏、Account/Ledger 混账、静默覆盖、Risk Account 缺失、历史测试删除/skip/放宽、Demo 内部状态写入或 Replay 差异。

## 13. 下一阶段建议

- ExecutionProcessor：**建议进入**，目标是抽取当前已验证的 Runtime 单写入者顺序并增加失败恢复，禁止改变业务语义；
- Paper Runtime：**建议有条件进入**，需复用相同 Broker Ports/Queue 并补实时 Clock、并发关闭和背压测试；
- 首个真实 Broker Gateway：**建议先做沙箱/只读与仿真接入，不建议直接生产交易**。需先完成 SDK 错误映射、重连、查询补偿、
  update journal、对账恢复和应用层操作审计。

## 14. 最终结论

**ACCEPTED**

本任务的组件单测、直接上下游、完整纵切面、全部历史测试、关键不变量与 100 次确定性重放均通过，允许进入下一阶段；下一阶段
不得绕过本报告确认的 Account/Broker/Runtime 边界。
