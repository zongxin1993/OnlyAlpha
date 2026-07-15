# Position、策略归因、T+1 与券商对账

## 1. 组件边界与双层模型

Position 是 Runtime 所有的单写入者状态域，不连接真实券商 SDK，不承担现金账户、完整策略资金账、撮合或强平。

```text
OnlyRuntime
├── OnlyPositionManager               账户真实仓位
├── OnlyPositionAllocationManager     Cluster 归因账 + Unallocated
├── OnlyPositionReservationManager    卖出仓位预占
└── OnlyPositionReconciliationService 券商快照对账
```

核心不变量是：`Account Position = sum(Cluster Allocation) + Unallocated`。普通 Cluster 不能读取可变实体、修改
Position、操作其他 Cluster 或 Unallocated。

## 2. Key、Mode、Side 与生命周期

NETTING 键是 Runtime/Account/Instrument；模型仍显式保存 PositionSide，给 HEDGING 的
Runtime/Account/Instrument/Side 键预留边界。第一版只执行 NETTING Long-only；HEDGING 类型存在但未伪装实现。

每次 FLAT→OPEN 以 Runtime、Account、Instrument、Side 和递增 cycle 生成确定性 PositionId；OPEN→FLAT 后快照进入
closed 历史，下一轮使用新 ID。状态为 OPEN、CLOSED、RECONCILING、ERROR。内部 `OnlyPosition` 受控可变，所有外部
查询只返回 frozen dataclass Snapshot。

## 3. Trade、成本与 PnL

`OnlyPositionTrade` 是标准化输入，显式包含 Runtime/Account/Cluster/Order/Trade/VenueTrade、Side、Direction、
Offset、PositionSide、Price、Quantity、Fee、UTC 纳秒时刻和 external sequence。Manager 拒绝其他 Runtime、裸 float、
不明确的方向和 Long-only 反手。

第一版 Average Cost：增仓按成交量加权，减仓不改变剩余均价。账户 Position 和每个 Cluster Allocation 分别计算成本。
Linear PnL 由 `OnlyLinearPnLModel` 计算 `(exit-entry) × quantity × multiplier`；费用单独累计，不进入成交均价。
市值和未实现 PnL 由 `OnlyPositionValuationService` 基于带时间和来源的 mark price 生成，不在每个 Tick 修改核心历史。

Trade 按 execution_id、venue_trade_id、trade_id 优先级去重；重复输入不改数量、PnL、版本或 Event。稳定顺序为
external_sequence→ts_event→trade_id；迟到输入返回 STALE 并进入 Reconciliation，不自动重算历史。

## 4. Allocation 与 Unallocated

Allocation 键包含 Runtime/Account/Cluster/Instrument/Side，独立保存数量、结算 Bucket、均价、已实现 PnL、费用、冻结和
Reservation。Cluster A 的卖出只能减少 A 的 Allocation；账户总量充足不能授权 A 使用 B 的归因仓位。

缺少 cluster_id 的成交、人工/外部交易、启动恢复缺失账本和对账差额进入 `OnlyUnallocatedPosition`。它不暴露给普通
策略，也不会被自动分配。对账可以用账户总量减去已知 Allocation 显式建立差额。

## 5. T+1、Bucket、Availability 与 Restriction

账户与 Allocation 同时保存 SETTLED/UNSETTLED Bucket。A 股买入默认进入 UNSETTLED；卖出只减少 SETTLED。
`OnlySettlementService` 必须由 Calendar 推导的 TradingDay 驱动，不能用 UTC 00:00 猜测新交易日。

```text
tradable = settled
available = max(tradable - order_frozen - risk_reserved - restricted, 0)
```

实盘再与 broker available 做保守组合；RECONCILING 时对 Cluster 暴露零可用。Restriction 显式保存 ID、数量、类型、
来源、生效区间和原因。第一版支持未结算、停牌、券商冻结和对账限制；其他枚举仅为扩展边界。

## 6. Position Reservation

OrderService 通过窄 Port 在卖单通过 Risk 后建立 LOCAL_ONLY Reservation，同时预占账户和本 Cluster Allocation。状态可推进到 SENT_TO_BROKER、
BROKER_ACKNOWLEDGED、RELEASE_PENDING、RELEASED；成交可部分或全部 CONSUME。

券商确认冻结后，账户本地预占释放，避免与 broker available/frozen 重复扣减；Cluster Allocation 仍保持预占，防止同一
Cluster 再次卖出。撤单已确认但券商尚未恢复可用量时保持 RELEASE_PENDING，不乐观释放归因预占。创建、推进、消费和
释放均幂等。

## 7. Broker Snapshot、Authority 与 Reconciliation

`OnlyBrokerPositionSnapshot` 是强类型、不可变、可序列化的 Gateway 标准 DTO。它保存总量、可用、冻结、结算/未结算、
今/昨仓、券商均价、市值、快照时间、来源序列和质量标记，但从不充当内部 Position。

Live 字段权威：账户总量和 Side 以 Broker 为外部权威；账户可用/冻结/结算量以 RECONCILED 为权威；Cluster Allocation、
策略 PnL 和本地成交成本永远 LOCAL；券商成本与本地成本同时保留。

Reconciliation 比较 total、available、frozen、settled、unsettled、side 和 average price，输出 Difference、Conflict、
Severity 与 Action。均价差通常为 INFO，可用/冻结延迟为 WARNING，总量、Side 或结算 Bucket 冲突为 BLOCK_INSTRUMENT。
阻断时本地历史不被覆盖，Position 进入 RECONCILING，查询订单/成交并重放缺失事实；无法归因部分进入 Unallocated。

## 8. Context、Risk、Event 与并发

策略接口明确分为 `ctx.positions.account.get(instrument_id)` 与
`ctx.positions.cluster.get(instrument_id)`。两个 View 都只返回不可变 Snapshot，不暴露 Manager、Settlement、对账或
Unallocated 操作。

Risk 使用账户 Position View 与 Cluster Allocation View，卖出量必须同时不超过两者有效可用量；底层 Manager 仍执行
超卖保护。Position 成功修改并更新索引/版本后才发布过去式事实，重复 Trade 不发布。第一版每 Runtime 单写入者串行
修改；未来 SDK callback 必须先标准化并进入 Runtime inbound queue，不能直接写 Manager。

## 9. Repository、序列化与 Demo

第一版 InMemory Repository 只保存 Snapshot，不暴露实体。Position/Allocation/Trade/Mutation/Reservation/
Restriction/Broker/Difference/Reconciliation/Unallocated 均以 Decimal 字符串、强 ID、Enum、UTC 纳秒和 version 无损
序列化。

`examples/position_demo` 展示账户合并仓位、多 Cluster 独立成本、T+1、Reservation、Broker conflict、Unallocated 和
确定性重放。

## 10. 已知限制

- 业务执行仅实现 NETTING Long-only、Average Cost、Linear PnL 和 T+1。
- HEDGING、Short、FIFO/LIFO、Inverse/Quanto、公司行动和今昨仓平仓尚未实现。
- 尚无真实 Gateway、数据库 Position Repository、完整 AccountManager、StrategyLedgerManager 或 ExecutionProcessor。
- Live/Paper 的完整资源装配仍按 Runtime 路线图推进，但每种 Runtime 从构造起已独占 Position/Allocation 状态域。
