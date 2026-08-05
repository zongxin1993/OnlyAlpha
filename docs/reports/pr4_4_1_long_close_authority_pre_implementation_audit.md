# PR4.4.1 Long Position CLOSE Authority 预实施审计

- 审计日期：2026-07-30
- 分支：`master`
- 实际起始提交：`12bfd77ecd212daf6ae8437ccbd839eaf95b67e2`
- 当前版本：`0.3.1`
- Prompt 预期差异：无。PR4.3.1～PR4.3.3 已合入；现有源码已经具备 Fill Identity、逐 Fill Transaction、增量费用/现金/Risk、Virtual Broker Fill Plan 与恢复主链。
- 工作树基线：仅有用户提供的未跟踪 `prompts/LongPositionCLOSEAuthority.md`，实施不修改该文件。

## 双轨现状

1. `_uses_prepared_trade_path()` 的精确条件是：Trade Instruction 已缓存且 Profile 为 `GENERIC_T0_CASH`；Order、Account、Ledger 均存在；Account 与 Ledger 的现金和持仓市值相等；Order 为 `LIMIT + BUY + OPEN`。当前判定尚未显式核对 Position Effect/Side/Mode，而是依赖随后 Planner 的严格校验。
2. SELL/CLOSE 因 `order.side is BUY` 与 `order.offset is OPEN` 不成立而绕过 `_prepared_trade()`，由 `_dispatch()` 进入 `_unmigrated_trade()`。
3. `_unmigrated_trade()` 直接调用 Order Update Processor、Position Manager、Allocation Manager、Settlement Manager、可选 Margin Manager、Fee Manager、Account Manager、Strategy Ledger Manager、Position/Account/Strategy/Margin Reservation 端口、Risk Service，并在末尾运行不变量检查。
4. 直接变更顺序为：Order → Position → Allocation → Settlement → Margin（若有）→ Fee → Account → Strategy Ledger → Position/Account/Strategy/Margin Reservation → Risk → Invariant → Event。
5. 该路径没有事务回滚。异常时仅中止尚未封口的 Event Buffer，按已记录步骤创建 Reconciliation Request，将 Position/Account 标记为 RECONCILING，记忆 Update/Trade 并返回 `PARTIAL_MUTATION`；已经完成的 Manager 修改会保留。

## Position 与 Allocation

6. Position Close 在 `OnlyPosition.apply_trade()` 中以 `total -= fill`、`settled -= fill` 处理，并允许本订单自己的 Reservation 量加入有效可卖量；归零后关闭 Position。
7. Allocation Close 在 `_OnlyAllocationState` 上同样以 `total -= fill`、`settled -= fill` 处理，只允许使用当前 Cluster Allocation；本订单 Allocation hold 可在成交归约时扣除。
8. 两者当前都通过 `OnlyPnLModel.realized(side, average_open_price, fill_price, quantity, multiplier, currency)` 计算毛 Realized PnL。它们各自计算，尚不是 Durable Close 的单一 Delta 权威。
9. 部分平仓时平均开仓价保持不变；全平时置 `None`。
10. 当前旧 Close 路径在部分平仓时没有减少 `cumulative_open_price_quantity`，只在全平时归零。这正是本实施必须修复且不能延续的精确成本缺口。

## Reservation 与 Risk

11. SELL/CLOSE Order 在 Order Service 提交阶段经 `OnlyOrderPositionReservationAdapter.reserve()` 创建 Position Reservation。Manager 同时冻结账户 Position 的 risk-reserved quantity 与当前 Cluster Allocation，且先校验二者有效可卖量。
12. State 为 `ACTIVE / PARTIALLY_CONSUMED / CONSUMED / RELEASED / FAILED`；Stage 为 `LOCAL_ONLY / SENT_TO_BROKER / BROKER_ACKNOWLEDGED / RELEASE_PENDING / RELEASED`。
13. 当前消费由旧路径在 Position/Allocation 已变更后调用 Adapter；Manager 按剩余量消费，必要时释放本地 Account hold 与 Allocation hold，更新 State/version。该消费位于 Transaction 外。
14. Account hold 是 Position 的 `risk_reserved_quantity`；Allocation hold 是 Allocation 的 `risk_reserved_quantity`。Broker Acknowledged 时释放本地 Account hold，避免与 Broker available/frozen 双扣，但保留 Cluster Allocation hold；成交后根据 Stage 与 `allocation_hold_already_released` 精确处理两种 hold。
15. SELL Risk 同时经过 Market Rule 的可卖校验与 `OnlyAvailablePositionRiskRule`；后者取账户 Position Snapshot 和当前 Cluster Allocation Snapshot，以二者 available quantity 的最小值作为上限，任一数据缺失均 fail closed。
16. Risk Reservation 当前由 `consume_order_fill()`/`consume_fill_for_order()` 按 Fill quantity/notional 增量消费；terminal fill 后进入 `CONSUMED`，Risk active order count 由 Risk Service 刷新。Prepared BUY 路径已有对应纯 Reducer。

## Fee、Settlement、Account 与 Ledger

17. SELL Fee/Tax 由 Runtime 唯一 `OnlyFeeResolver.resolve_trade()` 根据 Market/Broker schedule、side、累计 quantity/notional 与 Broker reporting mode 解析；Stamp Duty 等仅是 Fee Component，Planner/Manager 不硬编码税率。`OnlyOrderFeeAccrualTradeReducer` 已支持 `FILL` 与 `ORDER_CUMULATIVE`。
18. Market Rule Engine 生成 `OnlyTradeApplicationInstruction`。SELL 的 `cash_instruction.amount` 为正 notional；Settlement Instruction 保存 asset quantity、正 cash amount、asset/cash availability day 与 legal settlement day，日期来自 Profile/Calendar。
19. Account 旧路径在 `settle_notional=True` 时以 `notional - fee` 增加现金，并累加 Position 返回的 Realized PnL 与费用；随后单独估值。
20. Strategy Ledger 旧路径同样以 `notional - fee` 增加现金，Realized PnL 取 Allocation before/after Delta，并写 `SELL_SETTLEMENT` 和 `FEE` entries；随后单独估值。
21. `OnlyCommittedExecutionFact` 已有 `realized_pnl_delta`、Position/Account/Ledger PnL Delta 字段，但当前 SELL/CLOSE 不生成 Committed Fact；现有 BUY/OPEN Durable Fact 中这些字段为零。因此 schema 有承载能力，Close 权威尚未接入。

## Projection、Checkpoint 与 Recovery

22. `OnlyRuntimeProjectionComponent.POSITION_RESERVATION`、State、Projection、Codec union 与 transition validation 已存在；但正式 Generic T0 Projection Target Registry 尚未注册 Position Reservation Target，Planner 也不生成该 Projection。
23. Runtime checkpoint 已注册 `position-reservation.authority` Participant，并完整 capture/restore Position Reservation Manager。
24. Recovery 能恢复 checkpoint 中的 Position Reservation，也能反序列化存储的 Position Reservation Projection；但由于缺少正式 Target，当前无法安装一笔尚未投影的 Position Reservation Projection。PR4.4.1 必须补齐 Target 和恢复安装，而不新增 Recovery Phase。
25. Virtual Broker 已能接收 `LIMIT SELL CLOSE`，匹配 SELL limit，生成 Whole Fill `OnlyBrokerTradeUpdate`，并维护 SELL cash/position 投影；无需修改其 Fill Identity、Fill Index 或 Fill Plan 语义。

## 冻结后的实施范围

26. 预计修改生产文件：Execution Planner/validation/fact/invariants、planning results、Position/Allocation/Account/Ledger/Reservation Reducers、Projection Target Registry、Runtime Planning Context Builder/Target wiring、Committed Fact 字段与兼容解码、必要的公共导出。可能不需要改 Projection enum/codec，因为已有 Position Reservation union。
27. 明确不修改：`commit_coordinator.py`、`fill_identity.py`、Runtime Event Gate/Router、Recovery Finalizer/Outcome、Transaction ID、Fill Index 语义、Outbox 语义；不新增 Close Store/Coordinator/Recovery Phase，不实现 Partial/Multi-Close、Short、Hedging、Futures/Margin、Paper/Live。
28. 当前过时文档包括：`README.md` 与 `docs/roadmap.md` 仍把 Partial/Multi-Fill 列为未完成；`docs/backtest.md` 仍称 Virtual Broker Partial Fill Schedule 与完整 Multi-Fill Recovery 未完成；`docs/execution_prepared_transaction.md` 仍称这些能力未支持。`docs/execution.md`、README、Roadmap 以及多个旧 ADR 对 SELL/CLOSE 尚未 Durable 的描述在本实施完成后需要按历史/当前边界更新，而不是改写历史决策事实。

## 实施调整

真实代码已经提前提供 Position Reservation State、Projection Component、Codec、presence matrix、checkpoint participant 与 recovery validation view。因此实施不新增同义模型，只补纯 Reducer、正式 Target、Planner 分支及经济不变量。Close 的 Projection 顺序冻结为：

```text
ORDER → POSITION → ALLOCATION → SETTLEMENT → ORDER_FEE_ACCRUAL → FEE
→ ACCOUNT → STRATEGY_LEDGER → POSITION_RESERVATION
→ RISK_RESERVATION → RISK → VALUATION
```

Realized PnL 唯一由 Position Close Reduction 产生，Allocation、Account、Ledger 和 Committed Fact 只接收该 Delta。
