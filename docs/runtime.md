# Runtime 设计

正式 Trading Runtime 只持有通用 `OnlyBrokerGateway`、`OnlyBrokerInboundQueue` 和可选的
`OnlyDeterministicBrokerDriver`。模拟 Broker 能力在装配阶段验证，禁止具体类型判断、动态属性探测和后置
`bind_market_rules`。每个 Fill 的 durable authority 是 Runtime 独占的 Transaction Store；`OnlyExecutionProcessor` 通过纯
Planner 与 `OnlyRuntimeTransactionCoordinator` 提交 Prepared Transaction，再按 Applied Projection Ledger 幂等投影。
Broker 插件与 Cluster 均不持有或改写该 authority。

Scenario Action/Command DTO 保持 Runtime-neutral。目标 Trading Runtime vocabulary 是 `BACKTEST/SIM/LIVE`。
`BACKTEST` 支持确定性有限生命周期推进；`SIM` 已支持 Engine streaming lifecycle 下的 realtime Virtual Broker、
continuity 与 durable recovery，但当前 Scenario Runner 尚不驱动该长生命周期路径。`LIVE` 规划仍显式不支持；旧
`PAPER/SHADOW` mode 无法解析且不得静默降级。

Runtime Factory 必须先从必填 `market` 配置解析 Profile，再构建 `OnlyMarketRuleEngine`。Runtime 组件只接收
Pre-Trade、Match-Time 或 Instruction Port，不得接收 Profile/Resolved Profile/Registry。引擎按 Trading Day
编译，不假设整个运行区间内市场版本不变。

## Runtime Planning

`OnlyRuntimeEnvironmentBuilder` 是 Runtime shared environment 的唯一语义权威，生成结构化
`OnlyRuntimeEnvironmentIdentity` 与 canonical fingerprint。`OnlyRuntimePlanner` 只按该 Identity 分组并从 fingerprint 派生
Runtime ID；不同环境进入不同 Runtime Session。相同 Account/Broker/DataSource mutable key 若 fingerprint 不同则全局 Fail
Closed，不能借分 Runtime 绕过。`OnlyEngineRunAssembler` 只装配已验证的 `OnlyRuntimePlan`。

当前多 Cluster Trading Runtime 会计模型固定为单 Account、单 Base Currency、`FIXED_CAPITAL`。Assembly 在 Runtime 创建前验证每个 Cluster
资本及其严格总和；Runtime 通过完整 scope Ledger Locator 连接 Order、Risk、Execution、Valuation、Result 与 Reconciliation，
不得依赖 Cluster 或 Ledger 注册顺序。

## 1. 目标分类与当前源码

OnlyAlpha 唯一目标 Runtime product taxonomy 是：

```text
RESEARCH
BACKTEST
SIM
LIVE
```

Research Runtime 使用 Research Job / Plan，只拥有研究执行、Dataset、Calculation、Result 与 Artifact 状态；它不为抽象
对称创建 Order、Position、Account、Broker、Reservation 或 durable trading transaction authority。Backtest、Sim 与 Live
才是拥有 mutable trading authorities 的 Trading Runtime，并追求 Trading Semantic Equivalence。

当前源码的 Runtime product 类型为：

```text
OnlyRuntime
OnlyLiveRuntime
OnlyBacktestRuntime
OnlyResearchRuntime
OnlySimRuntime
```

这些类名不是完整产品完成度声明。当前 `BACKTEST` 与 `SIM` 已实现；`LIVE` 与 `RESEARCH` Factory 仍返回 unsupported。
历史 `PAPER` / standalone `SHADOW` package、Factory 与 public export 已删除，不形成兼容合同。

## 2. 统一上下文

Trading Runtime 的 Cluster 通过受限 `OnlyRuntimeContext` 获取：

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

Research Job 不伪装成 Cluster，也不使用该 Context 获得交易能力。

## 3. 隔离要求

每个 Trading Runtime 必须有独立：

- runtime_id；
- Clock；
- Event Stream；
- Account Context；
- Position Context；
- Order Namespace；
- Cache Namespace；
- Metrics；
- 日志上下文。

Research Runtime 只隔离自身的 research execution、Dataset、Calculation、Result 与 Artifact state，不要求拥有上述交易状态域。

## 4. Live 目标边界

目标 Live Runtime 使用实时行情和 Real Broker，并复用 Backtest/Sim 的完整 Trading Kernel。当前 `LIVE` Factory 仍明确
返回 unsupported；durable Broker outbound command、同步、对账、重连和长期恢复尚未形成生产闭环。

默认禁止在测试环境下启动真实交易。

## 5. Historical Migration Closure

P6.6 已删除历史 `PAPER` 长生命周期产品实现。canonical SIM 使用
`initialize → start → wait → stop`，不调用只适用于有限 Backtest 的 `OnlyEngine.run()`。它允许在盘前、盘中、午休、
收盘后、周末和节假日启动；市场 Session 状态不进入 Runtime Lifecycle。

启动按 `SUBSCRIBING → BOOTSTRAP → CATCH_UP → LIVE` 推进。Calendar 负责 Session，Completed Boundary 负责历史截止，
Historical Watermark 负责 Catch-up 重叠去重，Latest Observation Store 负责 CLI/Console/JSONL/未来 Web 的统一只读节点。
Required Historical Warmup 失败仍然 Fail Closed。旧 execution suppression 已删除；SIM 的完成度只由 canonical
Virtual Broker、durable transaction、continuity 与 recovery 产品链证明。

subscription、bootstrap、handoff、watermark、aggregation、continuity、gap/reconnect、timer 与 recovery 由
product-neutral Streaming control plane 拥有，不是第五种 Runtime。旧配置不自动转换，legacy durable state 也不转换为
SIM state。

## 5.1 SIM Realtime Virtual Broker and Recovery Path

SIM 使用 `initialize → start → wait → stop → close`，不调用仅适用于有限 Backtest 的 `OnlyEngine.run()`。正式组合是：

```text
OnlySimRuntime
→ OnlyStreamingRuntime
→ OnlyTradingRuntimeFacade
→ OnlyTradingKernel
```

Factory 创建 Live Clock、独占 MarketData/Broker Inbound Queue，通过 SPI 创建 historical+live DataSource 和 simulated Broker，
并要求 Broker 显式提供 deterministic driver。Broker Accepted/Trade/Terminal update 只能经 Broker Inbound Queue 进入
Execution Processor；Transaction Store 仍是 durable authority，Projection 只安装 Planner 已冻结的经济结果。

Next-Bar 因果顺序固定为 Bar N Strategy intent 后 Accepted、同 Bar 不成交，Bar N+1 matching 先于 Strategy 并产生 Trade。
停止只切断 future processing permission，不自动取消 Accepted order。SIM Runtime Persistence 可使用 Memory/SQLite；
`SQLITE + checkpoint.enabled=true` 还要求稳定 `user_data` state root，并提供正式 new-process restart 合同。P6.4 已实现 unexpected-gap、STALE 与
disconnect 的 same-process recovery：缺失历史事实经现有 Historical Port 加载、严格验证和归一化后进入同一 Processor/Pipeline，
恢复期既有 Broker order 可继续推进而 Strategy 新订单被抑制，buffered realtime suffix 追平并显式证明 continuity 后才恢复 LIVE。
P6.5 将 Runtime-neutral Checkpoint/Recovery Kernel 接入 SIM：`initialize()` 只恢复本地 durable authorities，`start()` 在资源启动后
先订阅 realtime 并 buffer，再完成 historical repair、transaction tail、Timer occurrence、continuity proof、post-recovery validation
与 verified recovery checkpoint，最后才恢复 Cluster、Timer 和 LIVE admission。Closed-Bar 与 Timer semantic action 在同一 Semantic
Lane exclusivity 内写入并 reread 验证 checkpoint；持续到达的 MarketData queue 不是 quiescence 条件。partial live Bar、transport queue、
subscription、Thread/Lock/Socket 均不 durable。Runtime State Lease 保证同一 state root 只有一个 writer。Real Broker reconciliation 与
long-running production operations 仍未实现。

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

费用不是 Broker 或 Runtime Factory 内部的固定佣金参数。Factory 分别解析 `market.fee_pack` 与
`accounts[].broker_fee_contract`，验证 Market Profile、实际 Broker 与 Account scope 后放入 `OnlyRuntimeAssemblyConfig`；
Runtime 只创建一个 `OnlyFeeResolver`，订单预估和成交应用共用该实例。未知 Authority、Scope 不兼容、零个或多个适用
Schedule 均 fail closed。

必须可配置：

- 撮合模型；
- Market Fee Pack、Account Broker Fee Contract 及版本化 Schedule；
- 滑点模型；
- 延迟模型；
- 交易日历；
- 初始资金；
- Instrument 历史版本；
- 数据缺失策略。

## 7. Research 目标边界

Research Runtime 面向 Historical Dataset 上的 Vectorized / Batch 数据、Indicator、Factor/Feature、参数搜索、统计和研究
Artifact，不产生正式交易状态，不经过 Strategy、Risk、Order、Broker 或 Trading Transaction Projection。当前
`RESEARCH` Factory 仍明确返回 unsupported，正式 Research Job / Plan 产品入口尚未实现。

## 8. 同时运行

同一 Engine 可同时存在多个 Runtime，但任意事件必须明确归属 runtime_id。

## 9. Runtime 时间约束

所有 Runtime Clock 返回 UTC。`OnlyBacktestClock` 拒绝 naive 和非 UTC 时间，并只能
单调推进。目标 Backtest/Sim/Live 必须通过同一 `OnlyTradingCalendar` 判断 Session、午休、夜盘与 TradingDay；当前
SIM 也复用该 Calendar 边界。不得从 UTC date、本地自然 date 或 Runtime 自建规则推导。
Backtest 数据按历史 Calendar 与 Instrument 版本解析。当前已实现最小 Next-Bar Virtual Broker 撮合；完整历史数据驱动与
更复杂撮合仍必须遵守 `docs/time_model.md` 和 `docs/virtual_broker.md`。

Engine 使用 canonical Runtime Environment 按 Runtime 类型、时间范围、Clock/Replay、DataSource、Broker、Account、Market、
Reference 与 Persistence 分组。仅环境 Identity 完全相同的 Cluster 才进入同一 Backtest Runtime；合法的不兼容配置创建独立 Runtime。共享 Runtime
仍保持一个 Order/Position/Account 单写入者状态域，而 Strategy、Factor、Indicator、Allocation 与 Ledger 按 Cluster 隔离。

每个具有 Clock 的 Runtime 独占并在关闭时关闭自己的 `OnlyClock`。Trading Cluster Context 只接收只读
`OnlyClockView`；Timer 必须通过自动命名空间化的 `OnlyTimerService` 注册。只有 Backtest Runtime
的历史事件驱动器可持有 `OnlyBacktestClock` 控制接口。

## 10. MarketData 隔离

每个 Trading Runtime 必须独占 EventBus、`OnlyMarketDataPipeline`、`OnlyMarketDataCache`、
`OnlyBarAggregationManager`、通用 MarketData barrier 和 Dispatcher。Runtime 级 Pipeline 只负责标准化行情、聚合与
不可变 Snapshot，不识别或创建 MACD、RSI 等具体 Indicator。每个 Cluster 独占自己的 Indicator Registry，并在
Cluster Pipeline 内固定执行 `Indicator → Factor → Strategy`；不同 Cluster 不共享可变 Indicator。Backtest、Sim 与 future
Live 使用同一数据准备顺序。Backtest 已实现完整同步数据准备链，SIM 已实现 realtime bootstrap/handoff、continuity 与 recovery。
`OnlyBacktestRuntime.process_bar` 是单记录版本化 Source/Request 的正式 Replay facade；实际顺序由 ReplayService 执行
Clock→MarketDataProcessor→Pipeline→Event facts→Dispatcher→ClusterManager。Live realtime Adapter 装配仍待后续阶段。

## 11. 标准化成交编排

每个 Trading Runtime 独占 `OnlyExecutionProcessor`、Update Deduplicator、Sequence Tracker、Invariant Checker、Audit Store、
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
到 `Runtime.run()`。当前 Scenario schema 中的源码 mode 可以共享同一 Command DTO，但目标 Runtime 差异只能位于 Driver、
Lifecycle 与 capability validation 边界，不能进入 Strategy 或经济语义。
