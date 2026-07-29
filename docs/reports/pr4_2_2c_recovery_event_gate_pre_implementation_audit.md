# PR4.2.2c Recovery Event Gate 预实现审计

- 审计日期：2026-07-29
- 实际基线：`7ff1fb2bb8f9861f7fb2b343f931545cb8fafda3`（`Feat: Closure：Post-Recovery Authority Validation 补强`）
- 与任务预期基线的差异：无。
- 事实来源：当前源码、测试、ADR 0044～0047、README、architecture、event、backtest、recovery 与 roadmap 文档。

## 1. EventBus 写入点、组件与 Route

当前生产代码对 Runtime EventBus 的直接写入如下：

| 写入点 | 业务组件与事件 | Route 判定 | 是否经过 Execution Delivery |
| --- | --- | --- | --- |
| `execution/delivery.py::OnlyEventBusDirectExecutionPublisher.publish()` | Account、Position、Allocation、Strategy Ledger、Valuation、Settlement 等 Execution Event Buffer 批次 | External Direct | 是 |
| `execution/delivery.py::OnlyExecutionOutboxPublisher.publish_pending()` | Projection Ready committed transaction 的持久 Outbox event | Durable Outbox | 是 |
| `order/publisher.py::OnlyRuntimeOrderEventPublisherAdapter` | Order 创建、提交、拒绝、状态变化 | External Direct | 否 |
| `risk/publisher.py::OnlyRuntimeRiskEventPublisherAdapter` | Risk decision、snapshot、reservation 变化 | External Direct | 否 |
| `runtime/backtest/runtime.py::before_market_dispatch()` | `OnlyMarketDataPipeline` 产生的 `result.facts` | External Direct | 否 |
| `runtime/runtime.py::_publish_runtime_fact()` | 当前为 `RUNTIME_STARTED` | Lifecycle | 否 |

`event/bus.py::publish_many()` 对 `publish()` 的调用只是队列组件内部实现，不是额外业务写入点。`OnlyMarketDataEventPublisher` 仅保留 Processor audit facts，不写 EventBus。

## 2. Execution Event Buffer 与绕过路径

Execution Event Buffer 当前收集 Runtime adapter 转换后的 Account、Position、Allocation、Strategy Ledger 事件，以及由同一同步边界产生的 Valuation、Settlement 等 manager facts。构造 Account、`add_cluster()` 的 Ledger 创建/激活和执行处理中的 manager mutation 都可进入该 buffer。

绕过 Execution Delivery 的路径是 Order Publisher、Risk Publisher、MarketData pipeline result facts 和 Runtime lifecycle。Execution Outbox 虽由 Delivery Coordinator 调度，但 publisher 自身仍直接持有 EventBus。因而统一恢复门禁不能只依赖 Execution Delivery Intent。

## 3. Recovery Replay 的实际 Publisher 行为

恢复会继续运行 MarketData Processor/Pipeline/Dispatcher、Strategy、Order、Risk、Broker Update Processor 与各 manager projection：

- MarketData `result.facts` 仍直接写 EventBus；
- Strategy 在历史 callback 中下单会调用 Order 与 Risk publisher；
- 非事务 Broker Update 的 order/risk direct events 仍产生；
- Ready rehydrate、unprojected recovery 与 continuation 会重建 Account、Position、Allocation、Ledger、Valuation 等状态及 event buffer facts；
- recovery finalization callback 也可能产生 direct facts。

`ExecutionProcessor.replay()` 强制返回 `OnlyExecutionEventDeliveryMode.NONE`。它只抑制调用方针对该 processing result 的即时 Execution Delivery：历史 direct batch 不交给 direct publisher，continuation committed transaction 不立即 drain durable Outbox。它不抑制上述绕过路径，也不控制 Runtime lifecycle。因此历史 MarketData、Order、Risk、Account、Position、Ledger、Valuation、Settlement direct events 仍可能被重复观察。

## 4. Bootstrap 与 start 的当前事实

Runtime 基类先创建 managers；Backtest Runtime 组装时绑定 manager publishers，创建初始 Account，并立即把 Account direct batch 发布到 EventBus。`add_cluster()` 创建并激活 Strategy Ledger、绑定 Risk profile、注册 Cluster，随后立即交付 buffer batch。具体可观察 bootstrap facts 以这些正式 manager 产生的 Account/Ledger facts 为准；Cluster Manager 本身当前没有独立 EventBus publisher。

当前 start 顺序是：plugin resources start → pending Outbox delivery → recovered Cluster resume 或 fresh Cluster start → `_after_clusters_started()` → Runtime `RUNNING` → 直接发布 `RUNTIME_STARTED` → EventBus drain。

Gate 初始状态不能是 OPEN：构造和 `add_cluster()` 时尚未判定 fresh start 或 checkpoint recovery。如果立即发布，恢复 Engine 的临时 Account/Ledger bootstrap authority 会在 checkpoint restore 覆盖前泄露。Fresh start 又必须保留这些真实创建事实，所以先按生产顺序有界暂存，在正式 start/open 后 FIFO flush；发现 checkpoint 时，临时 bootstrap authority 将被 restore 覆盖，必须整批丢弃且永不补发。

Historical direct event 不能在恢复后补发，因为它是已发生历史逻辑的非持久外部观察，补发会主动制造重复。Continuation transaction event 则属于正式 committed transaction，其唯一可靠意图已经写入 durable Outbox，必须保留 pending，并只在 finalization、durable checkpoint verification 与 Runtime OPEN 成功后按 at-least-once 语义交付。

## 5. Runtime EventBus 公共边界与测试依赖

当前 `runtime.event_bus` 返回完整 `OnlyEventBus`，外部可调用 publish、publish_many、dispatch、drain 和 close，因而可以绕过未来 Gate。现有测试大量使用 `runtime.event_bus.dispatch_results`、`failures`、`dropped_events`、`pending_count()` 和 `subscribe()` 进行只读观察/订阅；审计未发现测试直接调用 `runtime.event_bus.publish()` 或 `publish_many()`。这些调用只需要 Subscription View。直接测试 EventBus 本身或 execution publisher 的测试应继续显式构造 EventBus/测试 publication port，而非从 Runtime 取得写权限。

## 6. 必须迁移与必须保持解耦的组件

必须迁移到 Event Publication Port 的是 Execution direct publisher、Execution Outbox publisher、Order Runtime adapter、Risk Runtime adapter、Backtest MarketData result-fact publication、manager direct batch 的最终出口和 Runtime lifecycle publisher。Runtime assembly 负责创建唯一 Router/Gate 并将窄 port 注入这些 adapter。

Order、Risk、ExecutionProcessor、Commit Coordinator、Account/Position/Ledger managers、插件、Recovery Orchestrator、Finalizer validator 与 checkpoint service 都不应知道 Router 或 Gate 实现。Managers 继续写 Execution Event Buffer；Processor/Coordinator 保持现有业务与持久化职责。Finalizer 可继续持有原始 EventBus，仅用于 drain/quiescence；它不做 route 转换或 durable delivery。

EventBus 继续只负责 scope、FIFO queue、capacity/policy、handler priority/dispatch、backpressure、failure diagnostics 与关闭。它不得导入 Runtime/Recovery，不判断 Gate phase，也不新增第二个 internal EventBus。

## 7. 不得修改的恢复权威

本任务不修改 Recovery Outcome、Causal Recovery Session、Exact Boundary state machine、Post-Recovery Authority Validator、Recovery Finalizer phase、Cluster recovery lifecycle、Checkpoint header/component schema、Execution Transaction Store、Canonical Business Projection 或 Result Fingerprint。Gate 不是 checkpoint participant，不进入 persistence、business projection 或 fingerprint，也不改变 transaction/projection authority。

## 8. 正式交付语义与可靠性边界

External Direct 是非持久、best-effort 外部观察：fresh bootstrap/ready-blocked 时暂存，OPEN 时发布，RECOVERING/FINALIZING 时抑制且永不补发。没有 Durable Journal、delivery watermark 与 subscriber ACK，它无法同时保证不重复和不丢失；本任务只保证恢复不主动重放 historical direct events。

Durable Outbox 来自 Projection Ready committed transaction：事件先持久化，只有 OPEN 才能发布并在成功后标记 published；其他 phase 拒绝，不 stage、不 suppress。它保持 at-least-once，不声称 exactly-once。Lifecycle 仅在 OPEN 通过独立 route 发布。

正式开放顺序为：fresh/recovery completion → READY_BLOCKED → plugin start → Router OPEN/flush fresh staged direct events → drain pending durable Outbox → start/resume Cluster → Runtime RUNNING → publish `RUNTIME_STARTED` through Lifecycle route → EventBus drain。任一 finalization 或 start/open 后续步骤失败都使 Gate/Runtime fail closed；不交付 pending Outbox、不发布 `RUNTIME_STARTED`、不 resume Cluster。Recovery bootstrap events 和 suppressed historical direct events 永不补发。
