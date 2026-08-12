你正在实现 OnlyAlpha 工程的 P6.5。

Repository:
https://github.com/zongxin1993/OnlyAlpha

============================================================
任务名称
============================================================

P6.5 — SIM Streaming Durable Checkpoint & New-Process Recovery

目标：
为 OnlyAlpha 的 SIM Runtime 建立真正可证明的 Streaming durable checkpoint 与 new-process restart/recovery 能力。

这不是“删除 SIM_CHECKPOINT_NOT_SUPPORTED”或“把 Backtest checkpoint 搬给 SIM”。
本阶段必须从架构根部解决当前 Runtime checkpoint/recovery 对 Backtest 的历史耦合，并建立：

1. Runtime-neutral Checkpoint Kernel
2. Runtime-neutral Recovery Kernel
3. Streaming Semantic Mutation Authority
4. Streaming Continuity Authority
5. Streaming Timer durable/recovery semantics
6. SIM new-process recovery lifecycle
7. Runtime state single-writer lease
8. 完整 fault/restart/determinism certification

最终必须证明：

一个 SIM Runtime 在任意合法 crash window 后，由一个全新的 OnlyAlpha 进程，以相同 Runtime identity 和 durable state root 重建后：

- 已提交交易历史不改变；
- Order / Trade / Transaction identity 不改变；
- 不重复 Accepted；
- 不重复 Fill；
- 不丢 Projection；
- Position / Allocation / Account / Strategy Ledger / Reservation / Fee / Settlement 一致；
- Strategy / Factor / Indicator future decision state 正确；
- Virtual Broker 未完成工作正确恢复；
- MarketData continuity 正确；
- recovery 期间不允许 Strategy 创建新订单；
- continuity proof 后才重新获得 LIVE trading permission；
- Runtime lifecycle 不制造任何 synthetic trading fact；
- SIM 永远不会触碰 Real Broker。

============================================================
0. 强制工作方式
============================================================

不要直接开始写代码。

第一步必须重新读取当前 master 的真实实现和测试，不得基于旧印象修改代码。

至少重新检查：

- AGENTS.md
- README.md
- docs/roadmap.md
- docs/architecture.md
- docs/runtime.md
- docs/runtime_persistence.md
- docs/adr/0068-runtime-product-taxonomy-and-trading-semantic-equivalence.md

核心源码：

- src/onlyalpha/runtime/runtime.py
- src/onlyalpha/runtime/trading_facade.py

- src/onlyalpha/runtime/checkpoint/model.py
- src/onlyalpha/runtime/checkpoint/codec.py
- src/onlyalpha/runtime/checkpoint/participant.py
- src/onlyalpha/runtime/checkpoint/registry.py
- src/onlyalpha/runtime/checkpoint/service.py

- src/onlyalpha/runtime/persistence/store.py

- src/onlyalpha/runtime/recovery/*
- src/onlyalpha/runtime/backtest/*
- src/onlyalpha/runtime/streaming/*
- src/onlyalpha/runtime/sim/*

- src/onlyalpha/core/clock.py
- src/onlyalpha/cluster/manager.py
- src/onlyalpha/runtime/context.py

Broker / execution / transaction：

- src/onlyalpha/plugin/broker.py
- src/onlyalpha/broker/*
- src/onlyalpha/execution/*
- src/onlyalpha/transaction/*
- Virtual Broker plugin implementation

相关测试：

- tests/runtime/checkpoint/*
- tests/runtime/recovery/*
- tests/integration/*checkpoint*
- tests/integration/*recovery*
- tests/integration/*sim*
- tests/runtime/streaming/*
- tests/architecture/*recovery*
- tests/architecture/*runtime*
- tests/architecture/*streaming*
- scripts/test_suite.py
- .github/workflows/quality.yml

必须先确认当前 master 的实际实现，然后再制定最终 patch。

禁止根据下面提示词机械实现与当前源码已经不匹配的细节。
如果当前 master 已经实现某项要求，保留并验证，不得重复创建 parallel abstraction。

============================================================
1. 第一性原理
============================================================

P6.5 必须遵循下面的根本定义：

Checkpoint 不保存“正在运行的进程”。

Checkpoint 保存：

“在一个已经证明完整的 causal / semantic boundary 上，
最后一个 canonical trading world。”

必须区分：

A. Durable canonical state
B. Reconstructible operational state
C. Ephemeral process state

Durable / checkpointable：

- Trading authorities
- Strategy / Factor / Indicator state
- MarketData semantic state
- closed-Bar frontier
- execution sequencing / dedup
- Transaction causal frontier
- Reservations
- Virtual Broker deterministic state
- fee / settlement / margin state
- deterministic Result state
- logical Timer authority
- identity/fingerprint information

不得 checkpoint：

- Thread
- Lock
- Condition
- Event
- Socket
- SQLite connection
- Plugin connection
- Subscription ID
- MarketData inbound queue contents
- Broker inbound queue contents
- Observation worker
- LiveClock wall time
- current OS monotonic time
- STOPPING / RECOVERING thread stack
- in-flight Python callback stack
- mutable unfinished realtime Bar
- process-local runtime instance identity

Recovery 的目标不是重建旧进程，而是：

Durable state
+ durable transaction tail
+ immutable market evidence
→ reconstruct same canonical trading world
→ regain external continuity
→ prove readiness
→ LIVE

============================================================
2. 必须冻结的架构原则
============================================================

必须满足以下原则。

------------------------------------------------------------
2.1 Runtime-neutral Checkpoint Kernel
------------------------------------------------------------

当前 common checkpoint model/service 不得依赖：

- OnlyBacktestReplayCursor
- Backtest historical replay semantics
- Backtest Clock semantics
- Backtest result progress

当前类似：

OnlyRuntimeCheckpointHeader.replay_cursor

这样的 Backtest-specific field 必须从 common checkpoint Header 移除。

不要改名为：

OnlyRuntimeReplayCursor

然后继续保存相同 Backtest 字段。

正确模型：

OnlyRuntimeCheckpointHeader 只拥有 Runtime-wide durability metadata，例如：

- runtime_id
- checkpoint_sequence
- covered_execution_sequence
- checkpoint_schema_version
- created_at
- config_fingerprint
- market_composition_fingerprint
- participant_registry_fingerprint
- pending_outbox_count
- aggregate_payload_hash

Driver-specific frontier 必须成为 checkpoint participant。

Backtest：

backtest.replay-frontier

Streaming：

streaming.continuity

Checkpoint core 不得知道 BACKTEST/SIM/LIVE。

------------------------------------------------------------
2.2 Runtime-neutral Recovery Kernel
------------------------------------------------------------

Common recovery 不得 import：

onlyalpha.runtime.backtest.*

尤其不能存在：

common recovery orchestrator
    → OnlyBacktestRecoveryReplayResult

必须将 Recovery 拆成：

1. Local durable recovery/bootstrap
2. Driver-specific continuity recovery
3. Common finalization

推荐概念：

OnlyRuntimeRecoveryBootstrapper
OnlyRuntimeRecoverySession
OnlyRuntimeRecoveryFinalizer

Recovery bootstrap 只负责：

- load latest checkpoint
- validate checkpoint integrity
- validate Runtime identity
- validate config fingerprint
- validate Market Product composition fingerprint
- validate participant registry fingerprint
- restore participants
- build execution transaction tail recovery plan
- establish execution recovery session

它不得：

- query historical market data
- subscribe realtime
- know Backtest/SIM
- know wall clock semantics

Driver recovery：

Backtest：
Historical causal replay

Streaming：
Subscribe-first + historical repair + buffered realtime catch-up

Finalizer：
common authority validation + durable checkpoint verification。

------------------------------------------------------------
2.3 Shared Trading Facade 不能继续承担 Backtest recovery implementation
------------------------------------------------------------

OnlyTradingRuntimeFacade 最终只应该拥有：

- common Trading composition
- common trading checkpoint participants
- common cluster checkpoint participant registration
- common transaction-tail recovery primitives
- common post-recovery validation

以下逻辑必须移到 Backtest boundary：

- Backtest virtual clock checkpoint state
- Backtest replay cursor
- Backtest result progress
- Backtest recovery replay
- Backtest historical causal replay lifecycle

不要为 Streaming 在 TradingFacade 内增加：

if runtime.mode == SIM

不要引入 Runtime type branching 来修复现有耦合。

============================================================
3. Checkpoint / Persistence Schema
============================================================

P6.5 应采用明确 schema break。

如果当前 schema 仍是：

Runtime Checkpoint Schema = 4
Runtime Persistence Schema = 6

则 P6.5 推荐升级：

Checkpoint Schema = 5
Persistence Schema = 7

如果 master 已有更新，以当前实际版本 + 1 为准。

Alpha 阶段不要做 implicit migration/fallback。

旧 schema：

→ explicit unsupported schema error
→ fail closed

禁止：

- silently ignore fields
- automatically fallback to memory
- silently create a new empty runtime state
- compatibility alias

------------------------------------------------------------
3.1 Checkpoint aggregate hash
------------------------------------------------------------

检查当前 checkpoint aggregate hash 是否覆盖所有 semantic Header fields。

必须保证：

Every semantically relevant Header field
+
Every component:
    id
    schema_version
    payload
    payload_hash
→ canonical aggregate SHA-256

如果当前 market_composition_fingerprint 或其他 authority metadata 没进入 aggregate projection/hash，必须修正。

Checkpoint identity/integrity 必须不可部分篡改。

============================================================
4. Streaming Semantic Mutation Authority
============================================================

当前 OnlyStreamingProcessingLane 如果只序列化：

MarketDataProcessor.process()

不足以形成真正 checkpoint barrier。

因为 OnlyLiveClock Timer callback 运行在独立 scheduler thread，并可进入：

Cluster.on_timer()
→ Strategy state mutation
→ Order submit
→ economic state mutation

因此 P6.5 必须建立 Streaming Runtime 唯一 semantic mutation authority。

建议：

OnlyStreamingSemanticLane

或者在现有 ProcessingLane 上合理演化，但名称、职责必须反映真实边界。

它只负责 concurrency/control，不拥有经济语义。

必须串行化：

- finalized MarketData semantic action
- Strategy on_bar invocation
- Timer semantic action
- Virtual Broker due work triggered by semantic action
- Broker inbound processing belonging to that action
- Transaction commit / Projection completion
- Event delivery/drain required for stable action boundary
- checkpoint capture/write/verify
- recovery-exclusive semantic execution
- STOP cutoff

Trading Kernel 不得依赖 StreamingSemanticLane。

依赖方向必须是：

Streaming Runtime
→ Semantic Lane
→ Trading Facade / Trading Kernel

禁止：

Trading Kernel
→ Streaming Runtime

------------------------------------------------------------
4.1 STOP invariant
------------------------------------------------------------

保留 P6.4 已建立的 STOP 原则：

STOP 是 future processing permission cutoff。

STOP 不能：

- flush pending partial Bar
- drain queue into new domain facts
- execute new Strategy callbacks
- synthesize Broker facts
- synthesize Order terminal facts

已经进入 Semantic Lane 的一个 action：

必须完整完成。

尚未进入：

必须禁止开始。

============================================================
5. Stable Streaming Checkpoint Boundary
============================================================

Streaming checkpoint 不能要求 MarketData inbound queue 为空。

实时流可能持续到达。

MarketData inbound queue 不是 authority。

Checkpoint boundary 要求：

- 当前 semantic action 已完整结束
- 不存在另一个 concurrent semantic mutation
- Broker inbound 中不存在属于当前 action 尚未处理的事实
- EventBus required semantic delivery 已达到稳定边界
- execution durable sequence contiguous
- 对 checkpoint covered_execution_sequence 以内的 transaction projection 已 Ready
- recovery 不处于中间不可证明状态
- participant state self-consistent
- Virtual Broker checkpoint state 与 trading authorities 一致

允许：

- MarketData inbound queue 非空
- observation queue 非空
- future realtime updates 尚未处理
- mutable partial live Bar 存在于 process memory

但是 mutable partial live Bar 不进入 durable checkpoint。

============================================================
6. Checkpoint cadence：Correctness-first
============================================================

P6.5 V1 不要引入：

- arbitrary 10-minute checkpoint
- background asynchronous checkpoint
- stop-only checkpoint
- heuristic batching

Checkpoint-enabled SIM V1 采用：

Semantic Action
→ stable semantic world
→ checkpoint
→ atomic durable write
→ durable verify
→ release semantic permission

至少：

LIVE closed-Bar semantic action
→ verified checkpoint

Timer semantic action
→ verified checkpoint

如果 recovery 正在进行：

不要对每个 recovery historical Bar 写 checkpoint。

只在完整：

Historical repair
+
Execution-tail resolution
+
Buffered realtime catch-up
+
Continuity proof
+
Post-recovery validation

之后写新的 verified recovery checkpoint。

这样保证：

最后一个 advertised durable checkpoint 永远是一个完整可恢复世界。

============================================================
7. Streaming Continuity Authority
============================================================

不要继续让 StreamingRuntime 本身散落维护大量：

_historical_watermarks
_processed_bar_identities
_accepted_market_sequences
_latest_bars
_last_closed_bar_end
...

将真正描述 continuity 的状态收敛到：

OnlyStreamingContinuityTracker

或等价单一 authority。

建议模型包含：

OnlyStreamingStreamKey：
- source_id
- data_version
- instrument_id
- data_type
- bar_type

OnlyStreamingStreamFrontier：
- last_closed_bar_start
- last_closed_bar_end
- last_update_id
- canonical_sequence
- provider_sequence if meaningful
- processed_count

Tracker 负责：

- advance canonical frontier
- monotonicity validation
- duplicate / stale / old update rejection
- normalized canonical sequence
- recovery origin
- recovery target validation
- checkpoint capture
- checkpoint restore
- continuity proof

------------------------------------------------------------
7.1 禁止 unbounded full-history identity set
------------------------------------------------------------

如果当前 `_processed_bar_identities` 是长期增长 set，不得把它作为 long-running durability 设计。

应演化为：

frontier
+
bounded dedup state

而不是：

all bars ever seen

恢复需要的是可证明 frontier 和有限 overlap protection，不需要永久保存每根历史 Bar identity。

============================================================
8. Live Bar Finalization
============================================================

不要 checkpoint：

OnlyLiveBarFinalizer._pending

partial realtime Bar 不是 canonical market fact。

Crash 后 partial Bar 可以丢弃。

New process 通过：

subscribe-first
+ historical repair
+ realtime suffix

重新获得正式 closed Bar。

OnlyLiveBarFinalizer 中用于 closed/canonical sequencing 的 durable semantic information，如果已经由 StreamingContinuityTracker 正式拥有，应去除重复 authority。

避免两个组件同时拥有：

“最后 closed sequence 是多少”

必须确定唯一 authority。

============================================================
9. Timer Recovery：必须完整解决
============================================================

P6.5 不能忽略 Timer。

原因：

Timer callback 可以修改 arbitrary Strategy state，并可以 submit Order。

如果：

checkpoint
→ timer callback executes
→ strategy state changes
→ Accepted transaction committed
→ crash

仅依赖 transaction tail 无法恢复 arbitrary Strategy state。

因此 Timer 必须进入 P6.5 durability model。

------------------------------------------------------------
9.1 Timer authority / Clock driver 分离
------------------------------------------------------------

建立 Runtime-level logical Timer authority，例如：

OnlyRuntimeTimerRegistry

结构：

Strategy
→ OnlyTimerService
→ RuntimeTimerRegistry
→ Clock driver

TimerRegistry 是 authority。

LiveClock 只是 wall-clock wake-up mechanism。

TimerRegistry 保存 logical state：

- runtime/cluster/timer identity
- timer mode
- next deadline
- interval
- logical sequence
- fire_count
- logical state

LiveClock 当前时间、scheduler Thread、monotonic_deadline 不持久化。

Backtest 可以继续有 VirtualClock-specific restore adapter，但这不能成为 common Timer model。

------------------------------------------------------------
9.2 Durable admitted Timer occurrence
------------------------------------------------------------

为解决：

Timer callback 已开始
但 checkpoint 尚未完成
时发生 crash，

引入最小 durable Timer occurrence journal。

可使用 Runtime Persistence 中独立窄表，例如：

timer_occurrences

记录类似：

runtime_id
occurrence_sequence
timer_id
cluster_id
deadline_ns
fire_count
admitted_at
covered_checkpoint_sequence nullable/implicit by frontier

语义：

Timer 到期
→ durable admit occurrence
→ enter semantic action
→ Strategy callback
→ execution/broker consequences
→ checkpoint
→ checkpoint 覆盖 occurrence

Crash recovery：

A. occurrence 未 durable admit：
说明 callback 没有正式开始。
不得 synthetic replay。

B. occurrence 已 durable admit，但 checkpoint 未覆盖：
这是 incomplete semantic action。
必须 replay exactly this occurrence，通过 existing execution recovery/idempotency 机制恢复相同 trading/strategy state。

------------------------------------------------------------
9.3 Downtime missed Timer semantics
------------------------------------------------------------

Runtime 停机期间没有被 durable admitted 的 Timer 不得在 restart 时 retroactively execute。

例如：

crash 10:30
restart 11:00

10:35 / 10:40 / 10:45 的 callback 没有真实发生。

不得：

11:00 replay 三次 historical callback
→ 产生 hindsight Strategy orders

规则：

- 只 replay crash 前已经 durable-admitted 的 in-flight Timer occurrence；
- downtime 内未 admitted 的 callback 不产生 Strategy domain action；
- recurring timer 恢复其 schedule phase，推进到第一个 future deadline；
- expired one-shot timer 标记为 missed/completed（具体 enum 合理设计），但不执行 Strategy callback。

不要制造 counterfactual trading history。

============================================================
10. Runtime State Single-Writer Lease
============================================================

P6.5 必须解决 split-brain。

同一个：

runtime_id
+
runtime persistence path

只能有一个 active process writer。

SQLite transaction locking 不等于 Runtime ownership locking。

建立：

OnlyRuntimeStateLease

使用 OS-level exclusive file lock 或当前项目适合的跨进程锁方案。

建议 state root：

<user_data_root>/state/engines/<engine_id>/runtimes/<runtime_id>/

其中有：

runtime.lock
runtime.sqlite3
...

流程：

Factory/Runtime creation
→ acquire lease
→ open Runtime persistence
→ initialize Runtime

lease 生命周期覆盖整个 Runtime process ownership。

进程死亡时由 OS 自动释放。

如果另一个活跃进程持有：

RUNTIME_STATE_LEASE_ALREADY_HELD

fail closed。

不得：

- steal active lease
- silently create another Runtime directory
- append process id to runtime_id
- allow two processes simultaneously trade same Runtime identity

============================================================
11. Runtime identity 与 process identity
============================================================

保持：

runtime_id

作为 stable canonical state identity。

New process restart 必须复用同一个 runtime_id。

如果需要诊断，新增 ephemeral：

runtime_instance_id

仅允许用于：

- logs
- diagnostics
- lease owner metadata
- restart provenance

禁止 runtime_instance_id 进入：

- Order IDs
- Trade IDs
- Transaction IDs
- checkpoint semantic identity
- Market Product identity
- deterministic result fingerprint
- Strategy-visible semantics

============================================================
12. Broker checkpoint contract cleanup
============================================================

当前 deterministic Broker driver 如果已有：

capture_checkpoint()
restore_checkpoint()

继续复用。

但 checkpoint capability/schema authority 应属于 Broker component/driver 自己，而不应由 TradingFacade constructor 额外接收一个裸 schema version。

合理演化：

OnlyDeterministicBrokerDriver:

@property
checkpoint_schema_version -> int

capture_checkpoint()
restore_checkpoint()

如果项目已有通用 OnlyCheckpointCapability，也可以合理复用，但不要制造重复 capability model。

SIM checkpoint enabled 时：

- deterministic driver 必须存在
- checkpoint schema version 必须有效
- capture/restore 必须完整
- Real Broker 必须拒绝

注册：

broker.virtual

不要创建 SimBroker-specific persistence system。

============================================================
13. Common Checkpoint Participant Registry
============================================================

最大程度复用已有成熟 participants。

Common Trading participants 应继续覆盖：

- market-data.cache
- market-data.aggregation
- market-data.dedup
- market-data.sequence
- market-data.gap
- market-data.processor

- market.rules

- account.authority
- account.valuation-timeline

- order.authority

- position-reservation.authority
- position.authority
- allocation.authority

- settlement.authority
- margin.authority

- fee.authority
- order_fee_accrual.authority
- fee_reconciliation.authority
- fee_reconciliation_risk_gate.authority

- risk.authority

- execution.dedup
- execution.sequence
- execution.processor
- execution.audit
- execution.reconciliation

- strategy-ledger.authority

- cluster Strategy
- cluster Factors
- cluster Indicators
- cluster Result Recorder

- broker.virtual

具体名称以当前 master 为准，不要无理由破坏现有 component IDs。

Streaming-specific：

- streaming.continuity
- streaming.timer-authority
- streaming.result-progress（若需要）
- streaming diagnostics（只有其属于正式 deterministic result 时）

Backtest-specific：

- backtest.replay-frontier
- backtest.result-progress
- backtest clock state adapter（若仍需要）

禁止把：

streaming.phase
worker
subscription id
queue
LiveClock wall time

注册成 participant。

============================================================
14. Recovery 生命周期必须支持 Streaming 两阶段恢复
============================================================

当前 Base Runtime 生命周期如果无法表达：

initialize:
    local durable restore

start:
    transport operational
    subscribe-first
    external continuity recovery

则需要增加一个 neutral lifecycle hook。

例如：

_prepare_start()

或其他更合理名称。

不要使用 mode branching。

目标生命周期：

NEW PROCESS
↓
acquire Runtime state lease
↓
compose fresh Runtime
↓
fresh LiveClock
fresh DataSource resource
fresh Virtual Broker resource
same Runtime persistence
↓
initialize()
    resource initialize/connect
    cluster initialize
    register checkpoint participants
    local checkpoint restore
    transaction-tail plan
↓
Runtime RECOVERING / READY-for-start
↓
start()
    resources start
    streaming recovery preparation
    subscribe realtime FIRST
    buffer realtime updates
    historical repair
    execution tail recovery
    buffered realtime catch-up
    continuity proof
    post-recovery authority validation
    verified checkpoint
    event recovery gate complete
    cluster recovered/resumed
    normal worker
↓
Streaming LIVE
↓
Strategy new orders enabled

Fresh bootstrap 与 recovered bootstrap 必须明确区分。

============================================================
15. Subscribe-first Recovery
============================================================

Streaming restart 必须：

subscribe realtime
BEFORE
historical recovery query

原因：

防止 historical query 与 realtime subscription 之间出现 race gap。

流程：

1. restore durable local frontier
2. subscribe realtime
3. incoming updates进入 volatile buffer
4. determine latest completed historical recovery boundary
5. load immutable historical closed Bars:
   checkpoint frontier → completed target
6. replay through SAME normalized MarketData Processor/Pipeline
7. recovery期间 Strategy new order suppressed
8. existing Broker open orders可以根据 recovered market facts正常推进
9. process durable transaction tail through recovery session
10. enter CATCH_UP
11. reconcile buffered realtime suffix
12. dedup overlap
13. normalize canonical sequence
14. verify continuity
15. post-recovery validation
16. verified checkpoint
17. LIVE

不得建立：

RestartHistoricalRecoveryService

与 P6.4 gap recovery 并行存在。

============================================================
16. P6.4 same-process recovery 与 P6.5 restart 必须共享算法
============================================================

把当前 StreamingRuntime 中类似：

_recover_gap
_recover_market_continuity
_drain_buffered_updates
_process_buffered_updates
_verify_recovery_complete

的核心逻辑抽成：

OnlyStreamingContinuityRecoveryService

或等价模块。

Recovery reason：

- GAP
- STALE
- DISCONNECTED
- NEW_PROCESS_RESTART

可以不同。

算法必须共享：

historical repair
→ buffered suffix
→ overlap/dedup
→ canonical sequence
→ continuity proof

不要复制。

============================================================
17. Recovery 期间 Strategy 新订单权限
============================================================

必须明确：

BOOTSTRAP
CATCH_UP
DEGRADED
RECOVERING

均禁止 Strategy 新订单。

Fresh bootstrap 的既有产品语义继续保持。

Restart recovery 时：

历史 MarketData 可以驱动：

- Indicator
- Factor
- Strategy state reconstruction

但 order submit 必须被 deterministic suppression。

Existing accepted/open Virtual Broker orders不是“新 Strategy intent”。

它们必须允许沿历史 evidence 正常演化。

换言之：

Strategy intent authority
≠ Existing Broker work authority

不要为了禁新单而冻结整个 Execution system。

============================================================
18. Accepted/Open Orders restart semantics
============================================================

Process crash / Runtime restart 不是 Broker terminal fact。

不得：

- auto cancel Accepted order
- synthesize Cancelled
- synthesize Rejected
- resubmit as new Order
- change Order identity

正确行为：

restore Order authority
restore Reservations
restore Virtual Broker deterministic pending work
historical repair
→ matching conditions满足
→ existing order继续形成标准 Trade/Terminal facts

必须测试：

Bar N:
Strategy submits order
→ Accepted

crash

new process restore

Bar N+1:
Virtual Broker matches same order
→ same canonical Trade semantics

============================================================
19. Post-Recovery Validation
============================================================

继续复用当前成熟 validator/finalizer。

Streaming recovery完成前至少验证：

- checkpoint identity integrity
- transaction sequence continuity
- no unresolved prepared/committed inconsistency
- all required projection prefix Ready
- Order / Position / Allocation consistency
- Account / Strategy Ledger reconciliation
- Account reservation consistency
- Position reservation consistency
- Strategy reservation consistency
- Risk reservation consistency
- Margin reservation consistency
- Fee state consistency
- Settlement state consistency
- Virtual Broker authority consistency
- Streaming continuity frontier consistency
- inbound semantic quiescence as required
- EventBus stable boundary
- no unresolved admitted Timer occurrence
- no pending recovery plan
- source/data-version continuity compatibility

只有全部 PASS：

→ write post-recovery checkpoint
→ verify durable
→ mark recovered
→ allow LIVE

Fail：

→ Runtime FAILED
→ no Strategy permission
→ no silent fresh bootstrap

============================================================
20. Streaming Phase 不持久化
============================================================

不要 checkpoint：

OnlyStreamingPhase.LIVE
OnlyStreamingPhase.RECOVERING
OnlyStreamingPhase.STOPPING
...

New process 永远重新建立 control state。

Recovered runtime 应经历类似：

CREATED
→ SUBSCRIBING
→ RECOVERING
→ CATCH_UP
→ LIVE

不能 restore checkpoint 后：

phase = LIVE

LIVE 是经过当前进程 connectivity/continuity proof 后重新获得的 permission，不是过去的 durable事实。

============================================================
21. LiveClock recovery semantics
============================================================

绝不能：

restore old wall clock timestamp

新的进程使用新的真实 wall clock。

Backtest virtual clock 与 Streaming LiveClock 必须有不同 driver-specific checkpoint semantics。

Common runtime progress 不应再：

cast(OnlyBacktestClock, self._services.clock)

Streaming Timer 的 logical schedule由 TimerRegistry 恢复。

实际 LiveClock registration：

根据当前真实 now 重建 future scheduler wakeups。

============================================================
22. SIM Factory product contract
============================================================

在真正实现完成前保留：

SIM_CHECKPOINT_NOT_SUPPORTED

不要在前期 patch 提前删掉。

最终 P6.5 产品支持矩阵：

checkpoint=false + MEMORY:
    supported

checkpoint=false + SQLITE:
    supported

checkpoint=true + MEMORY:
    reject

checkpoint=true + SQLITE:
    supported

checkpoint=true + unstable/temporary state root:
    reject

checkpoint=true + non-checkpointable Broker:
    reject

checkpoint=true + Strategy/Factor/Indicator undeclared checkpoint capability:
    reject/fail closed

checkpoint=true + Real Broker:
    reject

SIM 继续：

- Live Clock
- Realtime Data
- Virtual Broker
- Full Trading Kernel
- no finite historical range

Checkpoint enabled 时必须要求：

explicit stable user_data_root

不要使用 temp fallback 作为 restart durability root。

============================================================
23. 修复 P6.4 当前潜在 result double-record
============================================================

重新检查最新 Streaming worker 正常路径。

如果当前存在：

processing_lane.process(update, _record_processing_result)

随后：

_on_processed(update, result)

而 _on_processed / _handle_worker_result 内再次调用：

_record_processing_result(update, result)

则必须修复。

正确 ownership：

commit_result:
    记录 processing result 与 Runtime state

on_processed:
    仅处理 reaction
    例如 GAP_DETECTED → start recovery

不得二次推进：

- processing_results
- closed_external_bar_count
- derived count
- duplicate count
- gap count
- frontier
- observation state

为这个问题增加 regression test。

============================================================
24. Architecture cleanliness
============================================================

目标目录可以类似：

runtime/
├── checkpoint/
│   ├── model.py
│   ├── codec.py
│   ├── participant.py
│   ├── registry.py
│   └── service.py
│
├── recovery/
│   ├── session.py
│   ├── bootstrap.py
│   ├── finalizer.py
│   └── validation.py
│
├── backtest/
│   ├── checkpoint.py
│   ├── recovery_driver.py
│   └── ...
│
├── streaming/
│   ├── semantic_lane.py
│   ├── continuity.py
│   ├── checkpoint.py
│   ├── recovery.py
│   ├── recovery_driver.py
│   ├── timer_registry.py
│   ├── live_bar.py
│   ├── phase_controller.py
│   ├── driver.py
│   ├── worker.py
│   └── runtime.py
│
└── sim/
    ├── factory.py
    └── runtime.py

不要为了匹配这个示意强制创建无意义小文件。

模块边界优先于文件数量。

强制依赖：

SIM
→ Streaming
→ Trading Runtime Facade
→ Trading Kernel

Checkpoint Core
← Backtest participant
← Streaming participant

Recovery Core
← Backtest recovery driver
← Streaming recovery driver

禁止依赖：

checkpoint → backtest
recovery core → backtest
trading kernel → streaming
trading kernel → Runtime type
streaming → sim
broker → Runtime concrete type

增加 architecture tests 防止未来回退。

============================================================
25. Fault Matrix
============================================================

必须构建 deterministic fault-injection tests。

至少覆盖：

--------------------------------------------------
Checkpoint / action boundary
--------------------------------------------------

1. crash before semantic action
2. crash during MarketData processing
3. crash after Strategy callback
4. crash after Order Accepted transaction commit
5. crash after Trade transaction commit
6. crash after durable commit but before Projection Ready
7. crash after Projection Ready but before checkpoint
8. crash during checkpoint write
9. checkpoint committed but process dies before LIVE/next action
10. checkpoint hash corruption
11. checkpoint component corruption

--------------------------------------------------
Execution tail
--------------------------------------------------

12. one Ready tail transaction
13. one committed-but-unprojected transaction
14. multiple Ready + unprojected mixed tail
15. Accepted + Trade multi-transaction tail
16. outbox pending at crash
17. duplicate broker update after restart
18. broker sequence continuity

--------------------------------------------------
Virtual Broker
--------------------------------------------------

19. open accepted order before crash
20. pending fill timing state
21. partial fill if supported
22. terminal order state
23. broker checkpoint schema mismatch

--------------------------------------------------
Streaming
--------------------------------------------------

24. crash with realtime queue non-empty
25. crash with partial live Bar pending
26. crash then historical/live overlap
27. restart with gap
28. restart while source was disconnected
29. restart followed by secondary gap
30. same-process gap recovery remains unchanged
31. repeated restart
32. crash during new-process recovery
33. crash during catch-up
34. second process restart after recovery checkpoint

--------------------------------------------------
Timer
--------------------------------------------------

35. crash before Timer occurrence durable admit
36. crash after Timer occurrence admit, before callback
37. crash during Strategy Timer callback
38. crash after Timer-created Accepted transaction
39. recurring Timer restart
40. downtime missed recurring Timer
41. expired one-shot Timer during downtime
42. no hindsight Timer-generated orders

--------------------------------------------------
Identity / fail closed
--------------------------------------------------

43. config fingerprint mismatch
44. Market Product composition fingerprint mismatch
45. participant registry fingerprint mismatch
46. DataSource identity mismatch
47. DataVersion mismatch
48. runtime_id mismatch
49. Runtime state lease already held
50. SQLite metadata corruption
51. unsupported persistence schema
52. unsupported checkpoint schema

所有 fail-closed case 必须有稳定 error code/message contract，
不要只 assert generic Exception。

============================================================
26. Deterministic equivalence tests
============================================================

为相同 market facts 与 strategy：

Run A:
continuous SIM

Run B:
same run with one crash/restart

Run C:
same run with multiple crash/restarts

最终比较：

- Order snapshots
- Trade identities
- committed transactions
- execution sequences
- projection states
- positions
- allocations
- account
- account valuation timeline where semantically deterministic
- Strategy Ledger
- reservations
- fee
- settlement
- risk state where appropriate
- Strategy state
- Factor state
- Indicator state
- Virtual Broker remaining state
- result recorder
- canonical market frontier

如果 wall-clock diagnostic fields 天然不同，不应该进入 semantic equality。

必须明确：

semantic equality
vs
process diagnostic equality

============================================================
27. CI / Test suite
============================================================

根据现有 scripts/test_suite.py 结构合理新增 P6.5 lane。

推荐：

sim-recovery

PR lane 应包含合理快版：

- architecture
- checkpoint/recovery unit
- representative new-process restart
- SIM integration

master/main：

完整 sim-recovery

Nightly / exhaustive：

- multi-crash fault matrix
- repeated restart
- 100-run deterministic recovery
- larger combinatorial crash windows

不要把需要几十分钟的 exhaustive matrix 全塞进 PR fast lane。

但 main 的正式 P6.5 certification 必须覆盖核心 crash windows。

============================================================
28. 文档
============================================================

P6.5 实现完成时同步更新：

- docs/roadmap.md
- docs/architecture.md
- docs/runtime.md
- docs/runtime_persistence.md
- SIM 相关正式文档
- ADR 0068 implementation update

建议增加：

docs/adr/<next>-streaming-durable-checkpoint-and-new-process-recovery.md

ADR 必须记录：

- checkpoint = canonical semantic world，不是 process snapshot
- runtime-neutral checkpoint
- runtime-neutral recovery
- two-stage Streaming recovery
- subscribe-first
- Semantic Lane
- Timer admission/recovery semantics
- partial live Bar not durable
- Runtime lease
- missed Timer semantics
- no synthetic lifecycle trading facts
- fail-closed rules

同时修复当前文档与源码 checkpoint/persistence schema version 漂移。

P6.5 不应在本阶段顺便删除 PAPER/SHADOW，
除非当前 Roadmap 已明确把该工作纳入 P6.5。

否则 legacy Runtime removal 留给后续 P6 final migration closure。

============================================================
29. 非目标
============================================================

P6.5 明确不实现：

- Real Broker durable outbound command
- Real Broker ACK/Unknown synchronization
- Real Broker reconciliation
- Live Runtime product
- distributed Runtime
- HA active-active
- automatic leader election
- remote checkpoint backend
- cloud object storage checkpoint
- periodic optimized journal compaction
- Research Runtime
- PAPER/SHADOW removal，除非 Roadmap 当前已明确调整
- arbitrary backwards persistence migration
- persistent partial live Bar
- process memory serialization

不要扩大 scope。

============================================================
30. 禁止的实现方式
============================================================

明确禁止：

1. pickle 整个 Runtime。
2. checkpoint Thread/Lock/socket/subscription ID。
3. 将 OnlyBacktestReplayCursor 简单改名成 RuntimeReplayCursor。
4. 创建 StreamingCheckpointService 与现有 RuntimeCheckpointService 平行。
5. 创建 Sim-specific trading economic authorities。
6. Runtime type branching进入 Strategy/Risk/Execution semantics。
7. restart 自动 cancel existing Orders。
8. restart resubmit existing order as new order。
9. recovery期间允许 Strategy 创建新 intent。
10. recovery期间关闭整个 Execution 导致 existing open broker work无法推进。
11. restore old Streaming phase=LIVE。
12. restore old wall-clock time。
13. flush partial live Bar on stop/checkpoint。
14. checkpoint MarketData inbound queue。
15. checkpoint partial Live Bar。
16. silently fallback from corrupted SQLite/checkpoint。
17. silently start fresh runtime when checkpoint restore fails。
18. allow two processes concurrently own same runtime state。
19. duplicated same-process/new-process streaming recovery algorithms。
20. 为了迁移方便保留长期 compatibility wrapper / alias。
21. 大规模无关重构。
22. 牺牲现有 Backtest determinism。

============================================================
31. 实施阶段
============================================================

不要一次巨大改完。

按以下阶段执行，每阶段必须独立测试。

------------------------------------------------------------
P6.5.0
Contract / Audit / Existing Bug Closure
------------------------------------------------------------

- 重新审计 current master
- 形成 ADR / pre-implementation audit
- 冻结 P6.5 scope
- 冻结 durable/reconstructible/ephemeral state
- 冻结 crash model
- 冻结 Timer semantics
- 冻结 lease semantics
- 修复 Streaming processing result double-record（如果当前确实存在）
- 添加 regression test
- 不开放 checkpoint-enabled SIM

------------------------------------------------------------
P6.5.1
Runtime-neutral Checkpoint / Recovery Extraction
------------------------------------------------------------

- common checkpoint Header 移除 Backtest cursor
- common capture/restore context 移除 Backtest cursor
- codec/persistence schema 更新
- Backtest replay frontier成为 participant
- Backtest clock progress移出 common progress
- Backtest result progress移出 common checkpoint setup
- common Recovery不再 import Backtest-specific result/type
- 引入 local recovery bootstrap/session
- Backtest recovery通过 driver adapter继续保持完全等价

必须证明：

Backtest continuous/restart/determinism tests 全部零行为回归。

------------------------------------------------------------
P6.5.2
Streaming Semantic Authorities
------------------------------------------------------------

- Semantic Lane
- TimerRegistry
- durable Timer occurrence journal
- StreamingContinuityTracker
- Runtime state lease
- Broker checkpoint contract cleanup
- architecture guards

仍不开放 SIM checkpoint产品能力。

------------------------------------------------------------
P6.5.3
Streaming Checkpoint Capture
------------------------------------------------------------

- streaming participants
- stable semantic barrier
- closed-Bar checkpoint
- Timer action checkpoint
- atomic write + durable verify
- checkpoint failure fail closed
- partial Bar/queue not checkpointed
- initial stable checkpoint policy

测试 capture/restore primitives。

------------------------------------------------------------
P6.5.4
New-Process SIM Recovery
------------------------------------------------------------

- same stable state root
- new Engine/process composition
- local restore
- subscribe-first
- historical repair
- execution tail recovery
- buffered catch-up
- continuity proof
- post-recovery validation
- post-recovery verified checkpoint
- recovered cluster resume
- LIVE permission
- remove SIM_CHECKPOINT_NOT_SUPPORTED
- enforce final Factory capabilities

------------------------------------------------------------
P6.5.5
Fault Matrix / Certification
------------------------------------------------------------

- deterministic fault injection
- repeated restart
- Timer crashes
- transaction tail crashes
- checkpoint write crash
- continuity recovery crash
- identity mismatch failures
- lease test
- architecture tests
- CI lane
- documentation
- final P6.5 certification report

============================================================
32. 代码质量要求
============================================================

必须保持：

- Python 3.12
- mypy strict
- Ruff clean
- deterministic ordering
- immutable dataclasses where appropriate
- explicit enums/value objects
- canonical JSON
- stable error codes
- fail closed
- no hidden global mutable state
- no unnecessary singleton
- no unbounded growth without justification
- no Runtime mode branches进入 economic semantics
- no duplicate authorities
- no compatibility debt

优先：

small explicit modules
clear ownership
single source of truth
narrow ports
composition-root wiring

避免：

manager/service/coordinator 名称泛滥而职责重叠。

每新增 abstraction 都要能够回答：

“它拥有哪一个唯一 authority？”

如果回答不出来，就不要创建。

============================================================
33. 测试命令
============================================================

实现过程中至少执行：

uv sync --frozen --all-packages --all-groups

uv run ruff check src tests examples packages scripts
uv run ruff format --check src tests examples packages scripts

uv run mypy src/onlyalpha

以及 workspace packages 已有的 mypy gates。

执行现有：

uv run python scripts/test_suite.py fast
uv run python scripts/test_suite.py integration
uv run python scripts/test_suite.py recovery
uv run python scripts/test_suite.py core-full
uv run python scripts/test_suite.py ashare
uv run python scripts/test_suite.py miniqmt-contract

如果增加：

sim-recovery

则执行：

uv run python scripts/test_suite.py sim-recovery

以及所有新增 targeted tests。

不要通过降低 test coverage、删除 assertion、扩大 ignore、标记 xfail 来让测试通过。

============================================================
34. 最终验收
============================================================

P6.5 只有满足以下全部条件才能标 DONE：

Architecture:

[ ] Common checkpoint 不依赖 Backtest。
[ ] Common recovery 不依赖 Backtest。
[ ] TradingFacade 不再拥有 Backtest-specific recovery implementation。
[ ] Streaming continuity只有一个 authority。
[ ] Streaming semantic mutation只有一个 serialization authority。
[ ] Timer logical authority与 LiveClock driver分离。
[ ] Runtime state有single-writer lease。
[ ] Same-process/new-process Streaming recovery使用同一 continuity算法。

Checkpoint:

[ ] Header runtime-neutral。
[ ] Aggregate hash覆盖完整 semantic identity。
[ ] Component registry deterministic。
[ ] SQLite atomic durable write。
[ ] Durable verification。
[ ] Partial live Bars不持久化。
[ ] Queue/thread/socket不持久化。
[ ] Live wall-clock不持久化。

Recovery:

[ ] Fresh bootstrap正常。
[ ] New-process restart正常。
[ ] Subscribe-first。
[ ] Historical repair。
[ ] Buffered catch-up。
[ ] Transaction tail recovery。
[ ] Open Virtual Broker order恢复。
[ ] Post-recovery validation。
[ ] Verified recovery checkpoint。
[ ] LIVE permission只能在 proof 后获得。

Timer:

[ ] Timer callback进入Semantic Lane。
[ ] admitted occurrence durable。
[ ] crash-in-callback可恢复。
[ ] downtime missed Timer不retroactive trading。
[ ] recurring schedule合理恢复。

Safety:

[ ] No duplicated Accepted。
[ ] No duplicated Trade。
[ ] No skipped Projection。
[ ] No synthetic Cancel on restart。
[ ] No Strategy new intent during recovery。
[ ] No Real Broker path。
[ ] No silent fallback。
[ ] No split-brain runtime ownership。

Determinism:

[ ] Continuous == one-restart semantic result。
[ ] Continuous == multi-restart semantic result。
[ ] Strategy state equivalent。
[ ] Factor state equivalent。
[ ] Indicator state equivalent。
[ ] Trading authorities equivalent。
[ ] Result state equivalent。

Quality:

[ ] Ruff pass。
[ ] Format pass。
[ ] mypy pass。
[ ] core-full pass。
[ ] recovery pass。
[ ] sim-recovery pass。
[ ] ashare pass。
[ ] miniqmt-contract pass。
[ ] build pass。
[ ] quality-gate pass。
[ ] Final same-SHA CI green。

============================================================
35. 最终输出要求
============================================================

完成实现后，不要只回复“P6.5 implemented”。

必须输出一份工程总结，至少包含：

1. Current master baseline
2. Root problems identified
3. Architectural decisions
4. Files/modules added/changed
5. Checkpoint schema changes
6. Persistence schema changes
7. Recovery lifecycle before/after
8. Semantic Lane implementation
9. Streaming continuity ownership
10. Timer durability/recovery semantics
11. Runtime lease design
12. Broker checkpoint contract changes
13. New-process SIM restart flow
14. Fault matrix coverage
15. Determinism/equivalence evidence
16. Backtest regression evidence
17. CI/test evidence
18. Known remaining limitations
19. Explicit P6.5 PASS/FAIL assessment
20. Remaining work before P6 final closure

如果任何核心 invariant 尚未证明：

必须明确标记 P6.5 NOT CERTIFIED。

不要用“基本完成”“应该没问题”代替证据。

============================================================
36. 最重要的最终原则
============================================================

整个 P6.5 实现过程中始终用以下模型判断设计是否正确：

Trading Kernel 回答：

“一个交易事实在经济上意味着什么？”

Driver 回答：

“外部事实怎样进入 Runtime？”

Checkpoint Kernel 回答：

“最后一个完整 canonical world 是什么？”

Recovery Kernel 回答：

“进程死亡以后怎样重新建立同一个 canonical world？”

Runtime Persistence 回答：

“哪些过去已经不可撤销？”

Streaming Continuity Authority 回答：

“我已经证明市场事实连续到了哪里？”

Semantic Lane 回答：

“谁现在有权限修改这个 Streaming trading world？”

Timer Registry 回答：

“哪些逻辑时间触发行为属于 Runtime authority？”

Runtime State Lease 回答：

“哪个进程现在唯一拥有这个 Runtime state？”

不要让这些职责重新互相污染。

P6.5 的目标不是让 SIM “能重启”。

目标是让：

Backtest / SIM / future LIVE

第一次真正共享一个干净、可证明、Runtime-neutral 的 durability/recovery foundation。

现在开始：
先审计 current master，
给出 P6.5.0 pre-implementation findings，
然后按阶段实施，
每个阶段完成后立即运行相应质量门禁，
直到完整 P6.5 certification。