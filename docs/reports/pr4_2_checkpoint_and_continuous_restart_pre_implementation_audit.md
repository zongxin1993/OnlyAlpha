# PR4.2 Runtime Checkpoint 与连续重启修改前审计

- 审计日期：2026-07-29
- 审计基线：`88d4c4d Feat: Execution Transaction Store 正式装配与真实 Engine Restart Recovery`
- 工作树状态：仅用户提供的 `prompts/ExecutionCheckpointv1Multi-TransactionTailRecovery.md` 未跟踪；实现前没有源码改动。

## 结论

当前产品恢复是 `OnlyBacktestRuntimeFactory.bootstrap_execution_transaction_before()` 加
`OnlyRuntime.initialize() -> OnlyExecutionRecoveryService` 的 sequence-one 特例。Factory 从唯一未 Ready Transaction 的
`Projection.before` 逐项安装 Order、Account、Ledger、Reservation、Risk、Settlement、Fee、Position、Allocation 和 Valuation
authority，并把 `Transaction.fact.ts_event` 保存为 `_execution_replay_resume_after`。它不能表达稳定 Bar 边界，也不能恢复 Ready
tail、策略/因子/指标、行情窗口、Broker、Timer、Result 前缀或多次重启。

## 1. Runtime 可变状态及实际所有者

| 所有者 | 当前可变状态 | 恢复来源决策 |
| --- | --- | --- |
| `OnlyBacktestClock` | UTC 当前时间、timer heap、sequence、取消集合 | Checkpoint；callback 由配置装配后按稳定 timer identity 重新绑定 |
| `OnlyMarketDataProcessor` | processing sequence | Checkpoint |
| Deduplicator / SequenceTracker / GapDetector | 已见键、各 stream sequence、最后 Bar | Checkpoint |
| MarketData Cache / Aggregation / Pipeline | closed-bar window、未完成聚合窗口、indicator pipeline versions/values | Checkpoint |
| `OnlyOrderManager` | 全部订单、client/venue 索引、ID generator heads、event sequence | Checkpoint；Checkpoint 后成交变化再由 tail 重建 |
| Position / Allocation Managers | active/closed authority、cycle、trade fingerprint、reservation/reconciliation | Checkpoint；Checkpoint 后成交变化再由 tail 重建 |
| Account / Strategy Ledger Managers | cash/equity/PnL/fee/version、reservation、valuation/equity timeline、dedup | Checkpoint；Checkpoint 后成交 projection 再由 tail 重建 |
| Risk / Settlement / Fee / Margin | profile binding、snapshot、reservation、record/index/sequence | 静态 rule 由配置重建；动态 authority 进入 Checkpoint，成交后部分由 tail 重建 |
| Execution Processor | broker update dedup、external sequence、audit/reconciliation、valuation heads | Checkpoint；transaction sequence 以 Store 为 durable authority校验 |
| Cluster / Strategy / Factor / Indicator | pipeline snapshot、用户可变状态、滚动窗口、warmup、last output | 必须显式 CHECKPOINTABLE 或 STATELESS；不得反射对象属性 |
| Virtual Broker | account/position/order、pending match、scheduler、venue/update/trade sequence | Broker plugin Checkpoint participant |
| Result Collector / Runtime lists | facts、diagnostics、broker/timer/delivery result prefix、determinism counters | Checkpoint 或确定性 recovery replay；不能重复发布历史 direct event |
| Persistence Store / EventBus / locks | SQLite connection、线程、锁、logger、文件句柄 | 不持久化；由 composition root 重建 |

## 2. 可由配置重建的状态

Instrument、Calendar、Market Profile/compiled rules、Fee Schedule、Risk Rule 静态定义、Cluster 结构、Strategy/Factor/Indicator 参数、
DataSource/Broker factory 与 subscription graph 可由同一 normalized product config 重建。重启时必须用 config fingerprint、participant
registry fingerprint、source identity 和 data version 验证它们没有变化。

## 3. 必须进入 Checkpoint 的状态

Clock/cursor/processing heads，所有 Manager 当前 authority 与去重索引，行情 cache/aggregation，Strategy/Factor/Indicator 显式状态，
Virtual Broker 和 pending match/open order，timer schedule，valuation/equity timeline，以及会影响最终业务 facts/fingerprint 的 collector
前缀必须进入同一个完整 Checkpoint。SQLite checkpoint 模式下缺少 capability 声明必须在装配期失败。

## 4. 可由 Checkpoint 后 MarketData Replay 重建的状态

Checkpoint cursor 之后、tail 上界以内的 Strategy callback、Factor/Indicator rolling transition、MarketData cache/aggregation、Broker
matching、非 Transaction Order 状态和内部 direct facts 可以确定性重放。重放必须执行真实 pipeline，但对已有 transaction 只验证并
rehydrate/recover，且抑制外部 direct-event 重发和重复 result fact。

## 5. 可由 Transaction Tail 重建的状态

Generic T0 Trade 的 12 个 ordered projection（Order、Position、Allocation、Settlement、Fee、Account、Ledger、两类 Cash
Reservation、Risk Reservation、Risk、Valuation）可以由 committed tail 重建。Ready tail 也必须从 Checkpoint authority 重新应用；未
Ready suffix 由正式 Coordinator 完成。Transaction 不能重建 Strategy、Indicator、Factor、Broker open-order 或 market window。

## 6. Strategy 状态

`OnlyStrategy` 当前没有 checkpoint contract。具体 Strategy 可以自由保存 counter/pending intent 等属性，框架无法安全猜测；
`on_initialize()` 和 `on_start()` 也允许副作用。因此必须新增显式 capability 与强类型/规范 payload contract，在 Cluster 已 initialize、
尚未 start 的 RECOVERING 阶段 restore。

## 7. Factor / Indicator 滚动状态

Factor 当前自行持有内部状态并通过 `snapshot()/score()` 暴露输出；Indicator 实现直接持有 deque/EMA accumulator 等 rolling state，
Registry/Pipeline 另持有 last snapshot 和 version。`reset()` 不能恢复窗口。它们必须显式 capture/restore 或声明真正 STATELESS。

## 8. Virtual Broker 状态

插件 gateway、order/account/position stores、matching engine、latency scheduler 与 deterministic driver 分别保存已接受/开放订单、
pending next-bar work、broker cash/position、冻结值，以及 venue order/update/trade/source sequence。当前 SPI 只暴露 `on_bar/run_due`，
没有 checkpoint capability；SQLite 装配若不扩展该边界只能产生空 Broker，故必须扩展公共 plugin API。

## 9. Identity 生成

Local Order 与 Client Order ID 由 Runtime-owned sequence generators 生成；Broker venue order/update/trade ID 由 Virtual Broker 自己的
deterministic sequences 生成；Transaction/Event identity 由 prepared payload 和 execution sequence 的稳定规则产生。所有 sequence
heads 必须恢复，原有 tail identity 不得改写。

## 10. Historical Replay 游标与恢复能力

`OnlyHistoricalReplayCursor` 当前只是一次 `prepare()` 生成的内存 tuple、index 和 state，RunPlan 重启则重新创建。正式恢复边界仅用
`Transaction.fact.ts_event + 1 microsecond` 缩小请求，因此不能区分同时间多 source/update，也未验证 data version/update ID。需要
持久化 `(source_id, data_version, source_sequence, update_id, event_time, processed_count)` 并按 identity 跳过精确前缀。

## 11. Bar 稳定边界

完整 Bar 顺序实际位于 `OnlyMarketDataProcessor.process()`：pipeline 后调用 before-dispatch（valuation、Broker on_bar 和即时 inbound
drain），再由 dispatcher 执行 Indicator/Factor/Strategy，after-dispatch 执行 Broker due、再次 drain 并 drain EventBus。Checkpoint
应在 after-dispatch 全部成功、processor 即将形成 APPLIED 结果的末端 capture；此时两个 inbound queue 为空、callback 已返回、
execution 全部 Ready、EventBus 已 drain。初始 checkpoint 应在 plugin/cluster initialize 后、start/replay 前创建。

## 12. Transaction 顺序

一个 Bar 可经多个 Cluster/order/update 产生多笔 transaction。Store commit 以 runtime scope 下最大 sequence + 1 分配 sequence；
Coordinator 的 predecessor-ready gate 使正常成功路径形成连续 Ready 前缀，但 crash/failure 会形成 Ready prefix + unready suffix。Store
schema 并不从数据库层禁止人工损坏导致 gap 或 unready 后 ready，恢复 analyzer 必须显式拒绝。

## 13. Lifecycle、初始化和 Result

Cluster `initialize_all()` 会绑定 Context、创建 Indicator、执行 Factor/Strategy `on_initialize()`、订阅行情并创建 pipeline；`start_all()`
再执行 Factor/Strategy `on_start()`。恢复应位于二者之间。当前 Result Collector 在 run 末期读取 Runtime audit、execution、timeline、
cluster snapshots 等内存前缀；重启等价性要求保存或确定性重建这些前缀。Runtime 当前没有 `RECOVERING`，且 Factory 直接分析并恢复
Manager，违反目标职责边界。

## 实施决策

删除 execution-store 配置/Factory/类名和 sequence-one bootstrap；建立唯一 Runtime Persistence Store schema v2，原子保存
Checkpoint Header/Components 与 transaction/outbox；由 Runtime lifecycle 调用 Recovery Orchestrator。Checkpoint 每完整 Bar 写入，
失败立即使 Runtime FAILED。恢复固定为 latest complete checkpoint、Ready-tail rehydration、unprojected-tail Coordinator recovery、
cursor-based recovery replay、post-recovery checkpoint，然后才进入 READY/start。
