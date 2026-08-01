# OnlyAlpha 路线图

## 当前状态（2026-07-30）

OnlyAlpha 已完成模块化单体的确定性回测内核纵切面，但尚未完成真实 A 股回测产品。完成标记仅代表现有源码、测试和公开边界覆盖的能力。

Scenario Framework 已完成 exact DataSource、Action Strategy、正式 Engine Runner、标准事实 Assertion、Artifact 和重复运行
fingerprint。Runtime Committed Execution 已成为 Result/Analytics/Artifact 的逐笔成交权威；Generic T0、期货 LONG/SHORT
开平仓已有产品纵切面。Futures Daily MTM、完整五 Pack 与 Cross-Version 仍是后续门禁。

## Phase 0：分析与架构基线（已完成）

- MyQuant 行为分析与 NautilusTrader 领域模型研究；
- Engine / Runtime / Cluster、Event、Clock、Cache / Storage 架构与 ADR；
- 三仓职责和核心仓独立依赖方向。

## Phase 1：核心运行骨架（已完成）

- Engine / Runtime / Cluster 生命周期；
- Cluster Definition、Session 与 Runtime Session；
- Runtime 兼容性分组和多 Cluster 隔离；
- 有界 Event Bus、确定性 Clock、配置、Cache 与 Storage；
- Strategy / Factor / Indicator 分层及受限 Context；
- DataSource / Broker Plugin SPI 与 Entry Point 发现。

## Phase 2A：确定性回测内核（基本完成）

- Synthetic Historical Replay；
- Virtual Broker 与基础 Next-Bar 撮合；
- Risk / Order / ExecutionProcessor；
- Position / Allocation、Strategy Ledger / Account；
- 单 Cluster、多 Cluster与共享 Runtime 分组；
- user_data 输出、完整纵切面和确定性重放。

“基本完成”不表示具备完整市场仿真：当前实现用于验证正式产品链和交易不变量。

## Phase 2B：真实历史数据（部分完成）

- 已有 Tushare 日线 DataSource、严格校验、Parquet Cache 与 CACHE_ONLY 正式示例；
- 数据版本、质量、缺口和交易日历治理；
- 复权、公司行为与参考数据；
- 大规模数据读取和回放验证。

## Phase 2C：A 股市场规则（部分完成）

已完成版本化 `CN_A_SHARE_CASH@2025.1` 基础领域 Profile：T+1 instruction、Long-only、禁止裸卖空、
多 Session、Reference 驱动的主板/ST/创业板/科创板涨跌幅、整手/零股清仓和基础税费。尚缺正式 Runtime 纵切面：

- 完整涨跌停、停牌、交易单位与申报规则；
- 跨部分成交最低佣金累计；
- Profile 驱动的 Broker/ExecutionProcessor 状态更新；
- 历史规则版本化验证。

## Unified Market Runtime Foundation（进行中）

- 已完成 Market Profile、Settlement、Position Mode/Effect、Short、Margin、Session、Price、Quantity、Fee、
  Liquidity、Slippage、Matching 的核心不可变抽象；
- 已完成 Generic T0 Cash、Generic Margin Futures、Generic 24×7 Crypto Spot 的领域级确定性验证；
- 已完成必填 `market`、Profile Registry → Compiler → Rule Engine 的 Backtest Composition Root 装配；
- Risk 已使用 Pre-Trade Port，旧 Market Rule Mapping 已删除；Virtual Broker 不再写死 T+1 日切；
- 已新增 Instruction-driven Settlement/Margin Manager；
- 已扩展 Settlement、Margin、Market Rule Decision 的 Result 与零行稳定 Parquet Schema；
- 已完成 HEDGING LONG/SHORT 生产写入、显式 Risk/Reservation scope 与 Committed Execution 投影；
- 尚未完成 Futures Daily MTM、Collector 的全部 Market timeline 事实以及 Tushare 对照验收。

## Phase 2D：回测分析与报告（基础阶段已完成）

- 已完成标准事实、结构化诊断、FIFO Trade、基础收益/回撤/交易/Exposure 统计；
- 已完成原子 JSON/Parquet Artifact、Manifest、CLI/Console/Markdown Report 和稳定指纹；
- 未完成高级风险、归因、图表、批量参数实验和结果比较。

## Phase 3：Paper 产品循环（未完成）

实时行情、模拟成交、状态恢复和可操作产品入口尚未闭环。

## Phase 4：Live 产品循环（未完成）

真实行情/交易 Gateway、重连、同步和生产级对账尚未闭环。本阶段开始前继续保持真实交易禁用。

## Phase 5：Research 工作流（未完成）

因子接口已有基础边界；数据探索、IC/分组分析、实验管理、统计和绘图工作流尚未形成产品循环。

## Phase 6：Web（未完成）

Application Service、REST、WebSocket/SSE、权限和控制台尚未实现。

## Phase 7：多市场（基础边界已开始）

核心 Profile/规则边界与三个 Generic Profile 已建立；港股、美股、中国期货、数字资产衍生品、外汇和期权正式产品适配尚未开始。
版本化 Registry、Auto/Pinned 解析、Capability、受限 Override 和 Conformance coverage gate 已建立；正式 Engine Scenario
Runner 与四个完整 Pack 未完成，因此内建版本仍为 Experimental。

## Phase 8：性能与分布式（未完成）

多进程回测、大规模因子、远程 Worker 和分布式任务不在当前阶段。在真实 A 股回测闭环和性能基线建立前不提前引入。
## PR4.2 Runtime Checkpoint 与连续 Engine Restart

已完成统一 Runtime Persistence MEMORY/SQLITE 配置、schema version 2、完整 Bar completion 后原子 checkpoint、checkpointable Result Progress、完整 Participant Registry、精确 MarketData cursor、Broker Update 因果点 Ready rehydration/未投影 Coordinator recovery、Stored Prepared 全量验证、Open Order/Virtual Broker/Strategy/Factor/Indicator 恢复，以及独立 Engine 连续重启和 canonical business projection 基线等价测试。PR4.2.2a 分离 persisted tail resolved 与 exact MarketData boundary completed，并支持正式 continuation transaction。PR4.2.2b 已增加 Recovery Outcome、`RECOVERY_FINALIZING`、完整只读 Authority Validator、fail-closed Finalizer、checkpoint durable read-back 以及 Engine A→B→C after-commit 故障矩阵。PR4.2.2c Unified Recovery Event Gate 已完成：Direct、Durable Outbox 与 Lifecycle 统一经 Runtime Router，恢复历史 Direct Event 被抑制，fresh bootstrap 有界暂存，recovery bootstrap 丢弃，continuation Outbox 仅在 OPEN 后交付，Runtime EventBus 对外只读。Paper/Live recovery、Partial/Multi-Close、Futures/Margin、Non-Trade Transaction、exactly-once Outbox、Direct Durable Journal、Delivery Watermark、Subscriber ACK、schema migration 与分布式 checkpoint 仍未完成。

## PR4.1 Projection Ready Query 与 Runtime Recovery（Historical）

本节记录此前只覆盖 transaction-tail forward recovery 的历史阶段；其单笔 bootstrap、旧 Store 命名与 schema 已由 PR4.2/ADR 0044
整体替代，不再是当前产品边界。

## PR4.2.2c Failure Semantics Test Hardening

PR4.2.2c 已通过 Failure Semantics Test Hardening 冻结：OPEN 前失败完全静默，OPEN 后保留 EventBus 已接受事件
并允许 cleanup 单次 drain；Bootstrap flush 使用原子批量入队；Outbox 保持 at-least-once，Direct Event 保持
best-effort。没有实现 Subscriber ACK、Delivery Watermark、Direct Durable Journal 或 exactly-once。下一阶段直接进入
PR4.3 Partial / Multi-Fill Durable Transaction，不新增 4.2.2d 架构阶段。

## PR4.3.1 Partial-Fill Order Authority 与 Durable Fill Identity（完成）

已完成纯 Order Partial-Fill Authority、精确累计成交价值、Fill Count/Last Trade ID、canonical Fill Identity、稳定 Payload
Fingerprint、durable per-Order Fill Index、Committed Fact 审计字段以及 Memory/SQLite Fill/Order Query。旧 whole-fill Snapshot
和 committed payload 可兼容读取，不新增表或 Checkpoint schema migration。该阶段的 Runtime Product Partial Fill gate
已由后续 PR4.3.2 在完整增量记账接线后移除。

## PR4.3.2 Incremental Reservation and Accounting for Multi-Fill（完成）

已完成 Position/Allocation 精确累计开仓价值、FILL/ORDER_CUMULATIVE Fee Scope、独立 Order Fee Accrual Authority、
Account/Strategy/Risk Reservation 分段消费，以及 Account/Ledger/Risk 的显式增量记账。Generic T0 Cash LIMIT BUY OPEN
的外部 Partial Fill 现按一个 Fill 一个 Projection Ready Transaction 正式提交；duplicate/conflict 仍由 durable Fill
identity fail closed。Virtual Broker Partial Fill Schedule 与完整 Multi-Fill Recovery 仍由 PR4.3.3 完成。

## PR4.3.3 Virtual Broker Partial Fill Plan 与 End-to-End Multi-Fill Recovery（完成）

已完成 WHOLE/MAX_PER_BAR/SCHEDULE、ONE_PER_BAR/ALL_DUE、quantity/ratio 精确归一化、稳定 Plan ID/Fingerprint、
Plan Store/Cursor、确定性 Order/Trade 排序、部分成交后撤单，以及 Gateway checkpoint/participant schema version 2。
正式 Engine 已证明跨 Bar与同 Bar多 Fill 每笔形成独立 transaction，并覆盖 Broker execute/publish、Commit、Projection、
Outbox、部分 Plan checkpoint 和 A→B→C restart 等价性。没有新增 Recovery Phase，Commit Coordinator、Event Gate、
Fill Identity/Index 与 PR4.3.2 accounting 保持不变。

## PR4.4.1 Generic T0 Cash Long Close Durable Transaction（完成）

`LIMIT SELL CLOSE LONG NETTING` 的首个 whole Fill 已复用统一 Planner、Transaction Store、Projection Targets、Recovery 与
durable Outbox。Position 可部分保留或完全关闭；Position 是 Realized PnL 唯一权威，Allocation、Account、Strategy Ledger
和 Committed Fact 消费同一增量；Position Reservation 在同一事务内消费。未修改 Fill Identity/Index、Commit Coordinator、
Recovery Phase、Event Gate 或 Outbox 语义。Partial/Multi-Close、Short、Hedging、CloseToday/CloseYesterday、Futures/Margin
与 Paper/Live 仍未实现；下一阶段 PR4.4.2 为 Partial / Multi-Fill CLOSE Incremental Accounting。

## PR4.4.2 Complete Durable Long Close Lifecycle（完成）

Generic T0 Cash `LIMIT SELL CLOSE LONG NETTING` 已支持任意合法多 Fill，每个 Fill 独立 durable commit。Position 与
Allocation 共用 Exact Close Cost Reducer，最终成本严格归零；Position/Risk Reservation 分段消费，Risk Active Count 只在
Final Fill 减少。Virtual Broker 已验证同 Bar和跨 Bar `300 → 400 → 300`、execute-before-publish、Commit、Projection、
Outbox、Fill 1/2 checkpoint 与 A→B→C 等价恢复。Partial Fill 后 Cancel/Reject/Expire 使用无伪 Trade ID 的
`ORDER_TERMINAL` Transaction。Runtime Persistence schema 升至 3 并明确拒绝旧 schema 2；Commit Coordinator、Recovery
Phase、Event Gate、Fill Identity/Index 与 Virtual Broker checkpoint schema 2 保持不变。下一阶段为 PR4.5 CN A-share Cash
Product Closure；Short、Hedging、CloseToday/CloseYesterday、Futures/Margin 和 Paper/Live 仍未实现。
# 已完成：Multi-Cluster Close Cost Authority

Generic T0 Cash 的不同成本 Multi-Cluster Long Close 已进入正式 durable transaction 路径，覆盖 whole/partial/multi-fill、注册顺序确定性与 checkpoint/restart。Unallocated Close、Cross-Cluster Close、FIFO/LIFO、Short、Hedging、Futures、Margin 和 FX 仍不在支持范围。
