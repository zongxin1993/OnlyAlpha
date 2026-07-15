# Position 组件差距分析

## 1. 当前持仓模型

| 类型 | 当前职责 | 当前问题 | 目标类型 |
|---|---|---|---|
| `domain.account.OnlyPosition` | 不可变账户持仓传输快照 | 无 Runtime/Cluster 作用域、无受控实体、无结算 Bucket、无幂等更新和对账状态 | `position.OnlyPosition` + `OnlyPositionSnapshot` |
| `domain.account.OnlyAccount` | 账户与持仓的不可变集合 | 不是运行时状态管理器，不能承担成交编排 | 后续 `OnlyAccountManager`，本阶段不实现 |
| `OnlyOrderManager` | Runtime 内订单真值 | Fill 尚未编排到持仓；订单虽保留 Cluster，但没有策略归因账 | 后续 ExecutionProcessor 编排 Position 两层账 |
| Risk Position Port | 可用数量只读占位 | 默认 unavailable；未区分账户可用与 Cluster 可用 | 账户/Cluster/Reservation 三种只读 View |
| MyQuant `PositionManager` | 每个 Strategy 持有仓位、账户、Broker 和风控引用 | 策略与券商状态耦合，多个策略无法共享同一账户真值 | 每 Runtime 独占 PositionManager/AllocationManager |
| MyQuant `PositionData` | 同时保存 volume、can_use、frozen、均价和 PnL | float、字段可变、T+1/冻结压在单个结构中、来源不明确 | 强类型 Bucket、Restriction、Reservation 和派生 Availability |

## 2. 当前更新链

```text
MyQuant:
Trade/Order callback
  -> BrokerSim/BrokerXT 直接修改或重建 PositionData
  -> PositionManager.holding_positions 被 query_position 替换
  -> Account/Risk/Strategy 读取同一可变对象

OnlyAlpha 当前:
Gateway Update -> OrderUpdateProcessor -> OrderManager
Trade -/-> Position -/-> Account -/-> Risk -/-> Cluster
```

MyQuant 的模拟 Broker 在挂卖单时直接扣减 `can_use_volume`，T+1 买入通过
`can_use_volume=0/frozen_volume=quantity` 表达；下一交易日恢复逻辑与 Broker 状态混合。XT 查询回调把 SDK
仓位映射为 `PositionData` 后直接替换 `holding_positions`，没有 Difference、AuthorityPolicy、冲突等级或审计。
收益既可能从账户持仓均价估算，也可能写入订单 PnL；策略归因依赖“一个策略一个 PositionManager”，不能解释多个
Cluster 共享账户。旧实现还大量使用 float，且人工/外部交易没有 Unallocated 账。

## 3. 风险清单

- Position 被 Broker、策略流程和回测成交逻辑共同修改；公共状态没有单一写入入口。
- 券商原始字段进入核心可变对象；查询快照可覆盖本地历史。
- 账户仓位与策略仓位混淆，只适合一个策略绑定一个账户视图。
- T+1、订单冻结和券商冻结共用 `can_use_volume/frozen_volume`，容易重复扣减。
- 无 settled/unsettled Bucket、Position Reservation 和 Restriction 来源。
- 无 Trade ID/venue ID 幂等账和严格乱序处理。
- 无法从总账户均价可靠恢复 Cluster 成本与收益。

## 4. 数据来源与复用边界

| 数据 | 当前状态 | 复用方式 / 本次 Port |
|---|---|---|
| Order | 已有 Runtime `OnlyOrderManager`，保留 cluster_id | 后续由 ExecutionProcessor 解析归属；本次 PositionTrade 显式携带 cluster_id |
| Trade/Fill | 有不可变 Domain Trade/OrderFill | 新增标准化 `OnlyPositionTrade`，拒绝 SDK 对象和裸字典 |
| Instrument | 已有强类型、Multiplier、币种和精度 | PnL/Valuation 输入，不把 A 股规则写入 Instrument |
| MarketRule | 已有组合规则 | SettlementRule 扩展点；第一版显式 T+1 Rule |
| TradingCalendar/Day | 已有 | SettlementService 接受明确 TradingDay，不按 UTC 零点结算 |
| Broker Position Snapshot | 不存在 | 新增标准化不可变 Snapshot 和 Reconciliation 入口 |
| Risk Reservation | 已有资金/名义金额预占 | 保持分离；新增专用 Position Reservation |
| Position Reservation | 不存在 | Runtime 独占 Manager，区分本地与券商已确认冻结 |
| Account Snapshot | 只有纯 Domain 快照 | 只读输入；不伪造 AccountManager 或无限权益 |

## 5. 本次变更边界

建立 Runtime 账户 Position 与 Cluster Allocation 双层状态域；普通 Cluster 仅获得只读、自动绑定作用域的查询
View。第一版实现 NETTING Long-only、Average Cost、Linear PnL、T+1、Restriction、Reservation、估值和
Reconciliation。HEDGING/FIFO/LIFO/Inverse/Quanto 仅保留类型边界，不伪装已实现。真实券商 SDK、完整
AccountManager、Strategy Capital Ledger、撮合、自动强平和跨策略净额化均不在本阶段。
