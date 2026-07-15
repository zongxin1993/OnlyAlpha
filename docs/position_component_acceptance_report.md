# Position 组件验收报告

## 结论

`ACCEPTED`

## 交付范围

- 新增 `src/onlyalpha/position/`：ID/Key/Enum、受控实体、不可变 Snapshot、账户 Manager、Allocation Manager、
  Unallocated、T+1 Settlement、Restriction、Reservation、Average Cost、Linear PnL、Valuation、Broker Snapshot、
  AuthorityPolicy、Reconciliation、Repository、Query/Context/Risk View、Event/Publisher。
- 修改 Runtime：所有 Runtime 模式从构造起独占 PositionManager、AllocationManager 和 PositionReservationManager；
  Backtest Context 暴露只读 `ctx.positions.account/cluster`。
- 修改 Order/Risk：卖单同时检查账户与 Cluster 可用归因；Risk ACCEPT 后通过窄 Port 立即建立 Position Reservation，
  标准订单回报推进、消费或释放，不实现完整 ExecutionProcessor。
- 新增分析、Position 文档、ADR-0013、架构原则、测试说明和七个 Demo。

## 设计验收

| 项目 | 结果 |
|---|---|
| Position 组件边界 | Runtime 单写入者；不依赖真实 SDK、AccountManager 或 Web |
| 双层持仓模型 | 账户 Position 与 Cluster Allocation 分离 |
| Unallocated | 未知 Cluster 和归因差额显式进入 Unallocated |
| Position Key/Mode | NETTING/HEDGING 建模；首版执行 NETTING Long-only |
| 生命周期 | 每轮开平仓确定性新 PositionId；OPEN/CLOSED/RECONCILING/ERROR |
| Trade 更新 | 标准化强类型输入；execution/venue/trade ID 幂等；迟到严格处理 |
| Average Cost | 账户与各 Cluster 独立计算 |
| Realized PnL | Linear PnL + multiplier；费用不进入成交均价 |
| Valuation | mark price、来源和时点驱动，不污染 Position 历史 |
| T+1 Bucket | 当日买入 UNSETTLED；Calendar-derived TradingDay 结算 |
| Available | settled/tradable、Restriction、冻结、Reservation 和 broker available 派生 |
| Restriction | 支持停牌、券商冻结、未结算、对账及扩展类型 |
| Reservation | LOCAL/SENT/ACK/RELEASE_PENDING/RELEASED；幂等与部分消费 |
| Broker Snapshot | 标准不可变 DTO，不作为内部 Position |
| AuthorityPolicy | Live 按字段区分 Broker/Local/Reconciled |
| Reconciliation | Difference/Conflict/Severity/Action；关键差异阻断 Instrument |
| Context API | `ctx.positions.account` / `ctx.positions.cluster`，不暴露 Manager |
| Risk Position Port | 同时检查账户与 Cluster effective available |
| Position Event | 成功变更后发布；重复 Trade 不发布 |
| 序列化 | Decimal、Money、ID、Enum、Bucket、UTC 纳秒、version 无损 |
| 并发 | 每 Runtime 单写入者；不允许 SDK callback 直接写入 |

## 验证结果

```text
pytest: 170 passed, 0 failed, 0 skipped
ruff: All checks passed
mypy --strict: Success, 119 source files
determinism: 100 replays identical
demo: 7/7 exited 0
```

关键自动化场景包括：开增减平、超卖、生命周期、Snapshot 不可变、重复/乱序 Trade、多 Cluster 独立成本与收益、
Cluster 越权拒绝、Unallocated、不变量、A 股 T+1 示例、Restriction、Reservation 全阶段、券商冻结去重、Broker
总量/可用/冻结/均价冲突、阻断、Runtime 隔离、Context/Order Reservation Port 和 Event 顺序。

## 已知限制与风险

- HEDGING、Short、FIFO/LIFO、Inverse/Quanto、复杂公司行动、期货今昨仓业务尚未实现，只保留扩展边界。
- Live/Paper/Research 已拥有独立 Position 状态域，但完整行情/执行资源装配仍按 Runtime 路线图后续完成。
- 本阶段没有真实 Broker SDK、数据库 Repository、完整 AccountManager、Strategy Capital Ledger、撮合、自动强平或
  跨策略内部净额化。
- 标准 Order 回报已编排 Position Reservation；Fill→账户 Position→Allocation→Account→Risk 的完整原子事务仍应由
  后续 ExecutionProcessor 实现。

## 一票否决项检查

未发现一票否决项：无 Engine 全局 PositionManager、无 Cluster 私有账户真值、无比例归因、无 float 金融核心值、无
当日买入立即可卖、无 Broker 静默覆盖、无重复 Trade 重复修改、无跨 Runtime 可变共享、无 Event handler 状态机、
无可变查询对象，也未伪造 AccountManager 或无限账户权益。

## 后续建议

- StrategyLedgerManager：建议下一阶段设计，用 Allocation Trade/PnL/Fee 作为输入，不反向修改 Position。
- AccountManager：建议在 StrategyLedger 边界稳定后实现真实现金、余额、保证金和账户权益。
- ExecutionProcessor：建议优先进入下一阶段，把已存在的 Order Fill、Position、Allocation、Reservation、Account/Risk
  更新按单写入者事务顺序编排，并设计失败恢复/重放。
