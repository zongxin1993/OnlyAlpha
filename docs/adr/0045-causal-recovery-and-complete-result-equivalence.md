# ADR 0045: Causal Recovery and Complete Result Equivalence

- Status: Accepted
- Date: 2026-07-29

## Context

ADR 0044 的恢复先重放行情并跳过 Store 中已存在的 Broker Update，再在 Replay 结束后批量 Rehydrate Ready prefix、批量 Recover unprojected suffix。这样后续 Strategy callback 在原成交因果点仍读取 checkpoint 的旧 Position、Account、Ledger 和 Risk authority。旧 checkpoint barrier 还位于 MarketData `_finish()` 之前，Audit、Result count、quality 和 business failure 前缀没有形成可恢复 authority。Result fingerprint 又由两套不完整字段列表产生，不能证明完整业务结果等价。

## Decision

1. Recovery 使用 `OnlyStoredRuntimeTransaction` 同时读取原始 Prepared contract 与 Committed transaction；Memory 和 SQLite Store 实现相同 Recovery Query Port。
2. `OnlyExecutionRecoveryPlan` 按 execution sequence 建立 Ready prefix 和 Unprojected suffix，`OnlyExecutionRecoverySession` 是唯一 tail 进度、冲突与 resolution authority。
3. 每个恢复 Broker Trade Update 仍进入 `OnlyExecutionProcessor`。Processor 使用与正常运行相同的 Planning Context Builder 和 Planner 重建 Prepared，并要求对象全等，同时重新验证 authority/payload canonical hash。
4. Replay 后批量 Rehydrate 是错误的，因为它让同一 Bar 或后续 Bar 的 Strategy 观察旧 authority；Replay 前预先应用 tail 也错误，因为它让更早的 callback 观察未来 authority。事务只能在原 Broker Update 因果点 resolve。
5. Ready entry 通过真实 Projection Applier 当场 rehydrate，不改变 Store Ready state、不创建 Outbox、不投递历史 Event；Unprojected entry 通过 Coordinator `recover_existing()` 使用原 Committed transaction 当场 forward recover 并标记 Ready，保留原 Outbox row。
6. Missing transaction、Prepared mismatch、codec/hash mismatch 和 causal order mismatch 均立即 fail closed；不缓存乱序 entry，也不把 Ready recovery 当普通 duplicate。
7. 非事务 Broker Update 仍执行 business mutation/audit，但恢复期间 external Direct Event delivery 被抑制。新 Engine bootstrap connection callback 同样经过 Processor，然后由 checkpoint restore 覆盖，不进入历史业务序列。
8. Recovery 必须完成最后一个 tail Update 所属的完整 MarketData boundary。`OnlyMarketDataProcessor._finish()` 先构造 Result、写 Audit、记录 checkpointable `OnlyBacktestResultProgress`、完成内部 Event drain，最后才允许 checkpoint barrier。
9. Result Progress checkpoint 保存 attempted/applied/duplicate/gap/rejected/failed、processed Bar、quality flags、business failures 和 processing sequence head；Result 不再以当前 replay counts、raw Audit history、HistoricalReplayService events 或 EventBus dispatch history作为业务前缀 authority。
10. Cluster 恢复生命周期为 INITIALIZED → RECOVERING → RECOVERED → RUNNING。恢复 callback 可运行 Indicator/Factor/Strategy，但不会重复普通 `on_start()`；首次运行的初始 checkpoint 在普通 Cluster start 完成后的稳定边界写入。
11. Business diagnostics 与 Operational diagnostics 分离。Recovery/checkpoint/outbox attempt 等运维字段不进入业务 projection；failure、warning 和影响业务 status/facts 的诊断进入业务 projection。
12. `only_backtest_business_projection()` 是 determinism fingerprint、result fingerprint、restart equality 和 Artifact manifest business hash 的唯一字段合同。Baseline 与 recovered 必须直接比较该 projection，而非只比较 hash。

## Recovery sequence

```text
Latest complete checkpoint
→ restore participants
→ build strict causal plan/session
→ replay exact MarketData cursor
→ rebuild and validate Prepared at each Broker Update
→ rehydrate Ready or recover Unprojected immediately
→ complete Result/Audit/Progress/Event boundary
→ validate transaction, queue, cursor and Result authority
→ write post-recovery checkpoint
→ Runtime READY
→ deliver pending Outbox
→ resume recovered Clusters without on_start
→ continue ordinary Replay
```

## Consequences

The Runtime no longer owns recovery sets, skips existing transactions, or invokes Ready/Unprojected batch recovery during restart. The old Ready Tail Rehydration service and old tail analyzer are removed. Prepared equality detects code/config/authority drift before any incorrect later decision. A committed-but-unprojected row remains the sole durable recovery authority and is never recommitted.

The formal transaction scope remains the currently routed whole-fill Generic T0 Cash path. Partial/Multi-Fill, SELL/CLOSE paths not routed through that planner, Futures/Margin transactions, non-trade transactions, Paper/Live recovery, exactly-once Outbox, schema migration, distributed checkpointing, full Broker reconciliation, remote stores and Web recovery remain out of scope.
