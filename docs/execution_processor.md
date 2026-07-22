# OnlyExecutionProcessor

ExecutionProcessor 在完整应用 Trade、通过不变量并提交 Event 后，才构造 `OnlyCommittedExecutionFact` 并向
Runtime-owned `OnlyCommittedExecutionJournal` 追加不可变成交事实。
重复、拒绝、乱序对账和部分变更失败不会形成成功成交记录；Result 不从 Broker Query 重建本地交易历史。

## 1. 职责与统一入口

每个可交易 Runtime 独占一个 `OnlyExecutionProcessor`。它是所有 immutable `OnlyBrokerInboundUpdate` 在 Runtime
Inbound Queue 之后的唯一业务处理入口；Gateway、Broker callback、Cluster、Web 和 EventBus 都不能直接调用 Manager
形成成交工作流。统一 API 为 `processor.process(update)`，Runtime 只负责 FIFO drain 和生命周期门禁。

Processor 不拥有 Order、Position、Allocation、Strategy Ledger、Account 或 Risk 真值。它只执行验证、显式分派、Mutation
编排、不变量检查、事实缓冲、Audit 与 Reconciliation。

## 2. Update 分派

```text
Accepted  → Order Accepted + Reservation acknowledged
Rejected  → Order Rejected + remaining Reservation release + Risk refresh
Cancelled → Order Cancelled + remaining Reservation release + Risk refresh
Trade     → ordered cross-component accounting
Position  → Position field-level reconciliation
Account   → Account field-level reconciliation
Connection→ Runtime-owned connection state
```

所有 Update 强制携带 `runtime_id/gateway_id/account_id/update_id/source_sequence/ts_event/ts_init`。Processor 在任何
Mutation 前校验 Runtime、Gateway、Account、Order Scope、UTC/因果时间、ID 和 sequence。

## 3. Trade 固定顺序

```text
Validation / Mutation Plan
→ OrderManager.apply_fill
→ FeeResolver.resolve_trade → immutable FeeInstruction
→ PositionManager.apply_trade
→ PositionAllocationManager.apply_trade
→ StrategyLedgerManager.apply_trade_accounting
→ AccountManager.apply_trade_cash_flow
→ FeeManager.apply
→ Account/Strategy/Position/Risk Reservation consume
→ Risk post-trade refresh
→ cross-component invariant check
→ buffered facts commit
→ committed execution build and journal append
```

Position/Allocation/Ledger/Account 只消费 Order 确认后的有效 Fill。Allocation 成本和 realized delta 是 Strategy Ledger 的
权威输入；Account 使用账户级 Position realized delta 和现金流，绝不读取 Strategy Ledger 虚拟资金。
`reported_fee` 只是 Resolver 输入，Manager 不得直接应用 Broker 字段或自行重算费用。同一 Fee Instruction 的总额同时进入
Position Trade、Account Cash Flow、Strategy Ledger 和 append-only FeeManager，重复 Trade 不会重复收费。

## 4. Mutation Plan 与 Bundle

Processor 在提交前恢复 Order/Cluster/Account/Instrument、检查 sequence、Instrument multiplier、Reservation 与 Ledger Scope。
每个结果保存有序 `OnlyExecutionMutationRecord`，并聚合 Order/Position/Allocation/Ledger/Account/Reservation/Risk
Mutation。第一版没有数据库事务；逻辑事务边界通过预检、单写入者和失败后强制对账实现。

## 5. Reservation 协调

买单按实际成交额与费用部分消费 Account/Strategy Cash Reservation；卖单按实际数量消费 Position Reservation；Risk
Reservation 保存原始 exposure 和累计 consumed exposure，部分成交后只保留剩余 exposure。完全成交进入 CONSUMED；Rejected/
Cancelled 只释放未消费部分。各 Reservation 状态域仍物理独立，不共享内部对象。

卖单 Allocation 在核心 Trade Mutation 中识别“本 Order 已冻结量”，避免把自己的 Reservation 误判为超卖；Reservation 状态
仍在 Account 之后统一推进，且不会二次释放 Allocation hold。

## 6. 幂等、迟到与乱序

每个 Runtime 独占 `OnlyExecutionUpdateDeduplicator` 和 `OnlyExecutionSequenceTracker`。update ID 重复返回 DUPLICATE；不同
update ID 但相同 trade/venue trade ID 仍返回 DUPLICATE，所有版本和事实不变。迟到 Accepted 可补充合法绑定但不得让终态回退，
通常返回 STALE/IGNORED。会改变成本/PnL 历史的乱序 Trade 在任何 Manager Mutation 前进入 Reconciliation。

## 7. 中途失败与 Reconciliation

每个步骤完成后记录 Audit step。若 Position 已完成而 Ledger 失败，Processor 停止后续业务步骤，丢弃本次缓冲的全部成功
事实，标记 Account/Instrument Scope 为 RECONCILING，保存 completed/failed step，并把
`OnlyExecutionReconciliationRequest` 放入 Runtime 默认的内存 Reconciliation Queue。只发布
`EXECUTION_PROCESSING_FAILED` 与 `EXECUTION_RECONCILIATION_REQUIRED`。第一版不做无审计反向补偿或自动历史全量重放。

Broker Account/Position Update 同样只进入字段级 reconciliation，不覆盖本地历史或 Cluster Allocation。

## 8. 不变量

`OnlyExecutionInvariantChecker` 在成功事实提交前检查：

- Account Position = Allocation Sum + Unallocated；
- Position/Allocation/Reservation 非负；
- T+1 unsettled 不增加当日可卖量；
- Strategy Ledger Cash/PnL Equity 双视图一致；
- Account Equity = Cash + Position Market Value；
- 不同 Runtime/Cluster Scope 不串流。

阻断性违反转为 `RECONCILIATION_REQUIRED`。

Event commit 失败时不构造 Fact；Fact 构造或 Journal append 失败时，Processor 不返回 APPLIED，而是记录依赖失败、封锁
作用域并进入显式 Reconciliation。Broker Update/Fill 只是外部输入，只有这一完整事务成功后才成为本地成交历史。

## 9. Event、Audit 与 Snapshot Bundle

Runtime 使用 `OnlyExecutionEventPublisher` 作为受限事务事实缓冲。Manager 仍生成过去式事实，但只有完整处理和不变量检查成功后
才一次性进入 EventBus；EventBus 从不调用 Manager。成功结果包含同一 logical processing sequence 的 immutable Order、
Position、Allocation、Ledger、Account、Risk Snapshot Bundle。内存 Audit Store 保存 Scope、Update、步骤、Mutation 摘要、
不变量、事实类型、失败和 Reconciliation ID，并支持无损序列化。

## 10. 并发、确定性与 Demo

第一版是 Runtime 单线程、单写入者、FIFO。Processor 不开线程、不并行 Manager、不读取系统时间；时间全部来自 Runtime Clock，
processing/audit/reconciliation ID 按 Runtime sequence 生成。Backtest、Virtual Broker、未来 Paper/Live 共用相同 API。

专项 Demo 位于 `examples/execution_processor_demo/`；统一 23 场景位于 `examples/integration_demo/`。

## 11. 已知限制

- 尚无数据库事务、持久 Audit/Reconciliation Queue 和自动恢复 Orchestrator；
- Connection Update 第一版只保存 Runtime-owned 状态，尚未建立完整重连状态机；
- Live/Paper Runtime 资源装配与真实 Broker SDK 尚未实现；
- 当前仍以单币种账户、Average Cost 和 Linear PnL 为主；HEDGING LONG/SHORT 开平仓已进入正式产品场景，但
  Futures Daily MTM 仍待补齐。
