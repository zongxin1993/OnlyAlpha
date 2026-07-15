# AccountManager、Broker Ports 与 Virtual Broker 差距分析

- 日期：2026-07-15
- 范围：OnlyAlpha 当前 Account/Execution/Broker 边界与 MyQuant 迁移行为
- 结论：当前 Domain 有不可变账户 DTO，但没有 Runtime-owned 账户真实账、统一 Broker Ports、Inbound Queue 或自动成交链。

## 1. 当前账户模型

| 当前类型 | 职责 | 问题 | 目标类型 |
|---|---|---|---|
| `domain.account.OnlyBalance` | 不可变币种余额 DTO | 只表达 `total=available+locked`，没有 Runtime Scope、预占或状态机 | `OnlyAccountCashBalance`、`OnlyAccountSnapshot` |
| `domain.account.OnlyAccountEquity` | 不可变账户权益 DTO | 没有版本、来源、质量或对账语义 | `OnlyAccountValuation`、`OnlyAccountSnapshot` |
| `domain.account.OnlyAccount` | 不可变聚合 DTO | 不是 Runtime 单写入者实体，不能处理 Cash Change/Fee/Reservation/Trade | Runtime-owned `OnlyAccountManager` |
| `OnlyStrategyLedgerManager` | Cluster 虚拟资金、费用和收益归因 | 不是券商真实账户；不能替代 Account | 保持独立，不共享实体或 Reservation |
| `OnlyPositionManager` | Runtime 账户级持仓真值 | 不拥有现金、账户权益或 Broker Account Snapshot | Account 估值只读取其不可变 Position Snapshot |
| Risk Account Port | 账户风险输入占位 | 无真实 Account 状态、可用资金或对账阻断 | `OnlyAccountRiskView` |

## 2. 当前 OnlyAlpha 调用链

```text
Cluster
→ ctx.orders.submit
→ Risk
→ OrderManager
→ PlaceholderExecutionService
→ SUBMITTED
→ Integration Demo 手工构造 Accepted/Fill/PositionTrade
→ Runtime.process_trade
→ Order → Position → Allocation → StrategyLedger → Event
```

现状结论：

- Cluster 不直接调用券商 SDK；
- OrderManager 不依赖 SDK；
- Placeholder submit 成功没有错误地标记 Accepted；
- Runtime 已有同步交易编排，但没有 Broker Update Queue；
- 正常 Integration Demo 仍手工制造 Accepted/Fill，尚未经过 Broker/Matching；
- 没有本地 AccountManager，因此成交后没有账户真实现金与权益更新；
- 没有 Account/Strategy Ledger 混用，但 Risk 仍缺账户真实账输入；
- 没有 Virtual Broker 独立状态，也无法测试 Broker/Local 冲突。

## 3. MyQuant 行为分析

MyQuant 的 `BrokerBase`、`BrokerSim`、`BrokerXT`、`PositionManager` 与相关测试显示：

- `BrokerBase.position_manager` 由 PositionManager 反向注入，Broker 可直接改 Manager；
- `BrokerSim` 同时维护券商模拟账户、订单、持仓，并在 `query_account/query_position` 中直接回写 PositionManager；
- `BrokerSim.cancel_order()` 在同步方法内直接把订单设为 CANCELLED 并释放资金/仓位，混淆请求接收与异步结果；
- `BrokerSim.check_orders()` 把撮合、手续费、滑点、账户现金、持仓和 T+1 写在同一类中；
- `BrokerXT` 同步逻辑可以用 Broker Snapshot 直接替换本地 Position；
- PositionManager 直接访问 `broker.orders_dict`、`account.available` 并调用 `broker.send_order()`；
- 账户、价格、费用与数量大量使用无约束 `float`；
- UUID 和 `datetime.now()` 进入 Broker 标识/时间路径，不能保证回测重放。

这些行为只能作为迁移回归来源，不能复制到 OnlyAlpha。

## 4. 当前依赖关系审计

当前生产代码未发现以下错误依赖：

```text
Account → StrategyLedger
Broker → AccountManager
Broker → PositionManager
Broker → OrderManager
```

原因是 Account/Broker 组件尚未实现。新增实现必须保持：

```text
account      依赖 domain 与自身 Ports
broker       依赖 domain DTO 与 broker Ports
virtual_broker 依赖 broker Ports、Clock View、独立 Store 与 Matching/费用/滑点/延迟模型
runtime      组合 account、broker、order、position、ledger
```

Virtual Broker 不得导入 AccountManager、OrderManager、PositionManager 或 StrategyLedgerManager。

## 5. 需要补齐的架构边界

1. Runtime-owned `OnlyAccountManager`：本地账户现金、费用、估值、状态和 Reservation 唯一真值；
2. Cluster-scoped `ctx.accounts`：只返回 frozen Snapshot；
3. `OnlyAccountRiskView`：Account 非 ACTIVE 或关键对账冲突时 Fail Closed；
4. 拆分 Broker Connection/Trading/Account/Position/Order/Trade Query Ports 与 Capability；
5. 标准 `OnlyBrokerInboundUpdate`，禁止 SDK/Virtual Broker 对象传播到 Manager；
6. Runtime-owned 有界 Inbound Queue：Gateway 只入队，Runtime 单写入者 drain 后调用 Manager；
7. Virtual Broker 独立 Account/Order/Trade/Position Store；
8. 独立 Matching、Commission、Slippage、Latency；
9. Broker Snapshot 与 Local Account 的字段级 Reconciliation，不静默覆盖；
10. 正常 Vertical Slice 必须由 Bar 驱动 Virtual Broker 自动产生 Accepted/Trade/Account/Position Update。

## 6. 目标调用链

```text
Cluster
→ OrderService
→ Risk (Account + Position + Ledger read views)
→ ExecutionService adapter
→ BrokerTradingPort
→ VirtualBroker independent stores
→ MatchingEngine on Bar N+1
→ VirtualBrokerScheduler / UpdateQueue
→ Runtime Inbound Queue
→ Runtime single-writer processors
→ Order → Position → Allocation → StrategyLedger → Account
→ Risk Snapshot refresh
→ fact Events → Final Snapshot
```

Submit/Cancel 的同步返回只表示 Broker 接口收到请求。Accepted、Cancelled、Trade、Account 和 Position 均由后续标准化
Inbound Update 表达。

## 7. 风险与实施约束

- Order Fill、Position、Allocation、Ledger 与 Account 是多状态域同步写入；第一版必须先做完整前置校验、幂等与稳定顺序，
  并在报告中明确尚无持久化事务恢复；
- Virtual Broker 必须使用 Runtime Clock 和确定性 ID/sequence，不得调用系统时间、sleep 或随机 UUID；
- Broker 资金冻结、本地 Account Reservation、Risk Reservation、Position Reservation 和 Strategy Cash Reservation 是五个
  不同不变量，不能共享对象；
- Account 账户级估值必须读取账户 Position，不得读取 Cluster Allocation；
- 现有 12 个历史 Integration Scenario 的业务断言不得删除或放宽，只能将正常成交来源改为正式 Virtual Broker 链路。
