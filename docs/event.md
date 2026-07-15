# Event Model 与 EventBus

Strategy Ledger 使用函数调用完成单写入者修改，成功保存后才发布 Ledger/Reservation/Trade/Fee/Valuation/Reconciliation
事实。EventBus 不承担 Ledger 状态机，也不允许 Handler 并行改账。

Risk Event 与 Order Event 一样只表达已经发生的事实。Risk Rule 和 Pre-Trade Pipeline 由同步函数调用执行，不能
通过 EventBus priority、订阅注册顺序或 Risk Event handler 驱动。Risk Accepted/Rejected/RuleFailed、
Reservation Created/Released 和 State Updated 事件用于审计和监控，不提供策略 Risk 回调。

## Event 是事实

Command 和 Query 使用明确接口调用；Event 只表达已经发生的事实。Bar 聚合、Cache 更新、指标计算和
策略调用由同步 MarketData Pipeline/Dispatcher 编排，不通过 EventBus handler 注册顺序或 priority 串联。
Runtime 在 Pipeline 完成后发布事实；Cluster 不持有 Runtime EventBus，不能伪造其他 Scope。

`OnlyEvent` 是不可变 envelope，包含强类型 Event ID/Type/Source/Sequence、Engine/Runtime/Cluster Scope、
correlation/causation、priority、metadata 和 payload。`timestamp`/`ts_init` 保留 aware UTC datetime 兼容
视图，`timestamp_ns`/`ts_init_ns` 是无损 Unix 纳秒真值。schema v2 DTO 优先保存纳秒并兼容读取旧 UTC ISO。

本组件定义 Bar received/validated、derived created、cache/indicator updated、snapshot ready、pipeline failed、
cluster handled/failed 等稳定事实类型；并非每个内部步骤都必须发布到公共 Bus。

## Scope

`OnlyEventScope(engine_id, runtime_id?, cluster_id?)` 由强 ID 组成。Runtime Bus 使用 Engine+Runtime Scope，
只接受该 Runtime 或其 Cluster 的 Event；回测与实盘各自拥有独立 Bus、队列和 Pipeline。Cluster 不能持有
全局 Engine Bus。

## 同步有界 EventBus

第一版为同步、单线程 dispatch、FIFO、有界 deque。`publish/publish_many` 只入队，`dispatch/drain` 执行
观察者。Subscription 可取消。同一 Event 的 handler 顺序为显式 priority 后 registration sequence；这只
定义观察者顺序，不允许承担 MarketData 或订单事务。

队列策略：REJECT 拒绝满载；FAIL_RUNTIME 抛出 Runtime failure；DROP_LOW_PRIORITY 仅在新事件 priority
更高时显式替换最低 priority 项，否则拒绝。核心事件不得静默丢弃。handler 异常形成包含 event ID、
subscription ID、handler 和原异常的结构化结果，不阻断其他 handler，也不无限重试。close 幂等，先停止
接收再 drain 已有事件。

## Order facts

Order Event 是 `CREATED/SUBMITTED/ACCEPTED/PARTIALLY_FILLED/FILLED/CANCEL_REQUESTED/CANCELLED/
REJECTED/EXPIRED/FAILED` 已发生的事实。Manager 先完成状态机、幂等与 Scope 校验，成功变更后才创建事件；
重复、过期、冲突或非法更新不发布。EventBus 只负责观察与投递，任何 handler 都不承担订单迁移。

## Position facts

Position、Allocation、Settlement、Restriction、Reservation 和 Reconciliation 状态通过同步函数修改，成功更新实体、
索引、Repository 与版本后才发布过去式 Fact。EventBus 不驱动 Position 状态机；重复 Trade 不产生 Event，迟到 Trade
进入严格 Reconciliation 流程。
## Broker inbound 与事实 Event

Broker 回调不是 EventBus 订阅者。Gateway 先将标准化 Broker Update 放入 Runtime 的有界 inbound queue，Runtime 调用 Manager
完成状态修改后才发布 Order/Position/StrategyLedger/Account 过去式事实。EventBus 不决定 Broker Update 顺序，也不驱动状态机。

Runtime-owned `OnlyExecutionEventPublisher` 在一次 Processor 逻辑事务内缓冲 Manager 事实。只有固定 Trade 链和跨组件不变量
全部成功后才按产生顺序批量提交；中途失败丢弃成功事实，只允许 Execution Processing Failed/Reconciliation Required 事实。
