# PR4.2.2b Validation Closure 实施前审计

## 基线与范围

审计基线为 `45b135160fbc378c94f62f36ee2e21a969426e74`，与任务预期一致。审计依据为当前源码、测试与
ADR 0047。本次只补齐 Finalizer quiescence 诊断和现有只读 checker 的跨 Authority 校验，不改变 Recovery Outcome、
Finalizer phase、Cluster lifecycle、Checkpoint schema、causal replay 或 READY/Outbox/resume 顺序。

## 审计结论

1. Finalizer 在 Cluster completion callback 后 drain EventBus，构造 validation context，并在进入 validator 前读取
   `OnlyRuntimeBoundaryAuthorityView` 的 broker、market-data 和 EventBus pending count。
2. 当前三个 count 被一个布尔表达式合并，任一非零都抛出 `POST_RECOVERY_INBOUND_QUEUE_NOT_EMPTY`，因此 EventBus
   pending 被错误归类。
3. Durable Outbox 的正式幂等身份是 `OnlyExecutionTransactionOutboxKey(runtime_id, execution_sequence,
   event_sequence)`。
4. Outbox 不存在也不需要独立字符串 `idempotency_key`；事件自身的 `event_id` 是另一项独立身份检查。
5. Account、Strategy、Position、Risk、Margin Reservation 构造器已经保证各自金额/数量守恒、状态与剩余量、币种
   内部一致性、版本和时间单调等对象内部不变量。
6. 当前 checker 仅校验 Account 的 account id，以及 Risk 的 runtime/account/cluster/instrument；未完整校验 Account
   runtime/order，Strategy 全 scope，Risk order，Position 全 scope/precision/bound，Margin 全 scope，并未与 Account
   base currency 对齐。
7. Fee Record 可与 committed fact 比较 instruction、account、instrument、order、trade、currency；其 charged 汇总可
   与 authoritative fee total 比较，无需重新执行 Fee Resolver。
8. Settlement Record 可比较 instruction、account、instrument、source order、source trade 与 legal settlement date。
9. Committed fact 的 settlement status 是提交时事实，而 Settlement Record 可随 Trading Day 推进；因此不能要求两者
   状态恒等，只能校验 record 的 `legal_settled` 与当前 status 内部一致。
10. Active Margin Reservation 按 `(account_id, currency)` 汇总 reserved、occupied、released，并与配置完整 margin 字段的
    Account Snapshot 对应金额比较；无 margin transaction/record/reservation 且 Account margin 字段为空时保持
    `NOT_APPLICABLE`。
11. 当前仅 Validation report model 有直接测试；默认 validator 中的 Outbox、Order/Reservation、Fee/Settlement/Margin、
    Runtime Boundary 等 checker 均缺少系统性的直接行为测试。
12. 所需生产修改仅为 `runtime/recovery/finalizer.py` 与 `runtime/recovery/validation.py`。测试将新增统一合法 context
    fixture 与精确 checker/finalizer 分支覆盖；文档只更新 recovery 说明和 roadmap。

## 实施约束

Validator 只比较 immutable context 中的 authority，不读取 Manager 私有容器、不调用 mutation API，也不重新执行 Fee、
Settlement、Margin、Position 或 Account 业务计算。Unknown order reservation 与 terminal-order active reservation 分开
诊断；Generic T0 Cash 不强制 Margin Reservation。
