# Runtime 设计

Runtime 只持有通用 `OnlyBrokerGateway`、`OnlyBrokerInboundQueue` 和可选的
`OnlyDeterministicBrokerDriver`。模拟 Broker 能力在装配阶段验证，禁止具体类型判断、动态属性探测和后置
`bind_market_rules`。本地成功成交由 Runtime 独占的 `OnlyCommittedExecutionJournal` 记录；Broker 插件与 Cluster 不持有该
Journal，`OnlyExecutionProcessor` 是唯一写入者。

Scenario Action/Command 在 BACKTEST/PAPER/LIVE/SHADOW 间一致；当前仅 BACKTEST 支持确定性自动推进，其他模式不降级。

Runtime Factory 必须先从必填 `market` 配置解析 Profile，再构建 `OnlyMarketRuleEngine`。Runtime 组件只接收
Pre-Trade、Match-Time 或 Instruction Port，不得接收 Profile/Resolved Profile/Registry。引擎按 Trading Day
编译，不假设整个运行区间内市场版本不变。

## Runtime Planning

`OnlyRuntimePlanner` 使用 Runtime 类型、起止时间、Clock/Replay policy、Data Version、Broker Environment 和 Account
Environment 生成 `OnlyRuntimeCompatibilityKey`。兼容 Cluster 进入同一个 `OnlyRuntimePlan`，不兼容 Cluster 必须进入不同
Runtime Session。`OnlyEngineRunAssembler` 只接受明确的 `OnlyRuntimePlan` 并负责对象装配，不读取配置文件、不执行生命周期、
不汇总或导出结果。

当前多 Cluster 会计模型固定为单 Account、单 Base Currency、`FIXED_CAPITAL`。Assembly 在 Runtime 创建前验证每个 Cluster
资本及其严格总和；Runtime 通过完整 scope Ledger Locator 连接 Order、Risk、Execution、Valuation、Result 与 Reconciliation，
不得依赖 Cluster 或 Ledger 注册顺序。

## 1. Runtime 类型

```text
OnlyRuntime
OnlyLiveRuntime
OnlyPaperRuntime
OnlyBacktestRuntime
OnlyResearchRuntime
```

## 2. 统一上下文

Cluster 通过受限 `OnlyRuntimeContext` 获取：

- Clock；
- 只读 MarketData View；
- 不可变回调 Snapshot；
- Logger；
- Timer；
- Instrument Registry；
- Account 只读 View；
- Cluster 命名空间化 Subscription/Timer Service。

Cluster 不接触具体 Gateway、撮合器、EventBus、可变 Cache、Aggregator 或 Runtime 内部 Service Container。
完整权限和生命周期见 `docs/runtime_context.md`。

## 3. 隔离要求

每个 Runtime 必须有独立：

- runtime_id；
- Clock；
- Event Stream；
- Account Context；
- Position Context；
- Order Namespace；
- Cache Namespace；
- Metrics；
- 日志上下文。

## 4. Live

实盘 Runtime 使用真实行情和真实交易 Gateway。

默认禁止在测试环境下启动真实交易。

## 5. Paper

实时行情 + 模拟成交。

用于策略验证和 Web 操作演示。

## 6. Backtest

正式成品式入口为 `CLI → OnlyEngine.add_cluster(OnlyClusterRunConfig) → OnlyEngine.run()`。Engine 内部通用 Assembler 仅从 Runtime Registry
取得 `OnlyRuntime`；Backtest Factory 再通过 DataSource、Broker 与 Strategy Registry 装配抽象组件。调用方只使用
`initialize/run/pause/resume/stop/close/snapshot` 父接口，Replay、Broker drain、最终不变量、Result 与资源关闭封装在
`OnlyBacktestRuntime.run()` 内。闭合 Bar 在 Broker 对账与 Cluster 回调前更新 Account/Strategy 估值；Calendar-derived
TradingDay 切换驱动本地 SettlementService。

DataSource/Broker 的内建与外部实现均由 Factory Registry 解析。组合根注册内建 Factory 并扫描 Entry Point；Runtime Factory
负责 `parse_config -> Capability Validation -> create`，Runtime 只管理创建后的资源生命周期。启动顺序为 DataSource、Broker
的 initialize/connect/start 后启动 Cluster；停止与关闭按 Broker、DataSource 逆序执行，单个资源清理失败不会跳过其余资源。

历史数据驱动虚拟时钟。

Runtime portfolio performance 只由 Runtime-owned `OnlyAccountPerformanceProjector` 从不可变 Account Snapshot 序列派生。
Projector 在 Account 创建、成交、估值、结算、保证金、费用、外部现金流和最终 seal 后记录带显式 sequence 的权益点，并计算
Account return、高水位和最大回撤。Cluster performance 则只来自相应 Strategy Ledger timeline；任何 Cluster 的 return 或
drawdown 都不能代表 Runtime。

费用不是 Broker 或 Runtime Factory 内部的固定佣金参数。Factory 将 `market.fees`、`brokers[].fees` 和两个版本化
Schedule Registry 显式放入 `OnlyRuntimeAssemblyConfig`；Runtime 只创建一个 `OnlyFeeResolver`，订单预估和成交应用共用
该实例。未知 Schedule、重叠版本或 Broker `DEFAULT` 在组装阶段失败。

必须可配置：

- 撮合模型；
- 市场与 Broker 费用模式及版本化 Schedule；
- 滑点模型；
- 延迟模型；
- 交易日历；
- 初始资金；
- Instrument 历史版本；
- 数据缺失策略。

## 7. Research

只做数据、因子、统计和绘图，不产生真实交易状态。

## 8. 同时运行

同一 Engine 可同时存在多个 Runtime，但任意事件必须明确归属 runtime_id。

## 9. Runtime 时间约束

所有 Runtime Clock 返回 UTC。`OnlyBacktestClock` 拒绝 naive 和非 UTC 时间，并只能
单调推进。Backtest/Paper/Live 必须通过同一 `OnlyTradingCalendar` 判断 Session、午休、
夜盘与 TradingDay；不得从 UTC date、本地自然 date 或 Runtime 自建规则推导。
Backtest 数据按历史 Calendar 与 Instrument 版本解析。当前已实现最小 Next-Bar Virtual Broker 撮合；完整历史数据驱动与
更复杂撮合仍必须遵守 `docs/time_model.md` 和 `docs/virtual_broker.md`。

Engine 使用 `OnlyRuntimeCompatibilityKey` 按 Runtime 类型、时间范围、Clock/Replay、数据版本、Broker 与 Account 环境分组。
仅环境兼容且资源 Fingerprint 一致的 Cluster 才进入同一 Backtest Runtime；不兼容配置创建独立 Runtime。共享 Runtime
仍保持一个 Order/Position/Account 单写入者状态域，而 Strategy、Factor、Indicator、Allocation 与 Ledger 按 Cluster 隔离。

每个 Runtime 独占并在关闭时关闭自己的 `OnlyClock`。Cluster Context 只接收只读
`OnlyClockView`；Timer 必须通过自动命名空间化的 `OnlyTimerService` 注册。只有 Backtest Runtime
的历史事件驱动器可持有 `OnlyBacktestClock` 控制接口。

## 10. MarketData 隔离

每个 Runtime 必须独占 EventBus、`OnlyMarketDataPipeline`、`OnlyMarketDataCache`、
`OnlyBarAggregationManager`、通用 MarketData barrier 和 Dispatcher。Runtime 级 Pipeline 只负责标准化行情、聚合与
不可变 Snapshot，不识别或创建 MACD、RSI 等具体 Indicator。每个 Cluster 独占自己的 Indicator Registry，并在
Cluster Pipeline 内固定执行 `Indicator → Factor → Strategy`；不同 Cluster 不共享可变 Indicator。Live 与 Backtest 使用同一数据准备顺序。当前组件已实现这些独立
对象。`OnlyBacktestRuntime.process_bar` 是单记录版本化 Source/Request 的正式 Replay facade；实际顺序由
ReplayService 执行 Clock→MarketDataProcessor→Pipeline→Event facts→Dispatcher→ClusterManager。Live/Paper 真实 Adapter
资源装配仍在后续阶段。

## 11. 标准化成交编排

每个可交易 Runtime 独占 `OnlyExecutionProcessor`、Update Deduplicator、Sequence Tracker、Invariant Checker、Audit Store、
Reconciliation Queue 与事务事实 Publisher。Runtime `drain_broker_inbound()` 只做生命周期门禁和 FIFO 消费，所有
`OnlyBrokerInboundUpdate` 统一调用 `processor.process(update)`。`process_trade(update)` 只是仍强制 Queue 的便捷 ingress，
不存在 Fill/PositionTrade 双参数旁路。

Processor 同步执行 Order、Position、Allocation、Strategy Ledger、Account、Valuation、Reservation、Risk、不变量与事实提交。
配置 Virtual Broker 时，ExecutionService 只提交标准 Broker Request；Matching Engine 产生的 Update 必须先进入 Runtime
Inbound Queue。无 Broker 配置的 Runtime 仍使用明确 Placeholder。`settle_positions()` 只接受 Calendar 推导的 TradingDay。

## 12. Market Data Source 装配

Backtest Runtime 还独占 MarketData Source Registry、Reference Source、历史 Source、MarketData Queue、InMemory Gateway、
Processor、Deduplicator、SequenceTracker、GapDetector、AuditStore 和 ReplayService。实时 Queue 与 Broker Queue 物理分离。
历史链为 `Source → ReplayService → BacktestClock → Processor → Pipeline`；实时链为
`Gateway → Queue → Processor → Pipeline`。`process_bar()` 仅保留正式单记录 Replay facade。

Scenario Runner 不得用该 facade 代替产品纵切面；验收必须从 `OnlyEngine.run()` 经 Planner、Assembler、Runtime Factory
到 `Runtime.run()`。Scenario Action 在各 Runtime mode 共享同一 Command DTO，模式差异只能表现为 capability validation。
