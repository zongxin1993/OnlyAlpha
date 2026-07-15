# ADR-0013：Position、Allocation、结算与券商对账

- 状态：Accepted
- 日期：2026-07-15
- 关联模块：position、runtime、risk、order、event

## 背景

多个 Cluster 共用同一券商账户时，券商只提供账户总仓位，不能表达策略归因、策略成本、策略收益或本地订单预占。
旧 MyQuant 通过每策略一个 PositionManager 和可变 Broker PositionData 工作，券商查询可直接替换本地持仓，T+1、
冻结、可用量和收益的来源无法独立审计。

## 决策

- 每个 Runtime 独占一个账户 `OnlyPositionManager` 和一个 `OnlyPositionAllocationManager`。
- 账户 Position 是 Runtime 内账户真实仓位；Allocation 是按 Cluster/Instrument/Side 分隔的内部归因账。
- 每笔 Order/Trade 从创建起保留 Cluster 来源；无法解析来源的成交进入 Unallocated，不猜测、不均分。
- 普通 Cluster 只通过 `ctx.positions` 读取不可变 Snapshot，只能操作自身 Allocation。
- Position 使用 Settlement Bucket；A 股当日买入进入 UNSETTLED，新交易日经 Calendar/TradingDay 驱动迁移到 SETTLED。
- Available Quantity 由 settled/tradable、Restriction、订单冻结、Position Reservation 及券商保守可用量派生。
- 本地 Reservation 与券商冻结分开；BROKER_ACKNOWLEDGED 后不在账户层重复扣减，但 Cluster 归因预占持续到成交或释放。
- Broker Snapshot 是外部事实 DTO，不是内部实体；AuthorityPolicy 按字段决定 LOCAL/BROKER/DERIVED/RECONCILED。
- Reconciliation 生成 Difference、Conflict、Severity 和 Action。关键数量冲突把 Instrument 置为 RECONCILING 并阻断。
- 每轮 FLAT→OPEN 使用确定性新 PositionId；第一版实现 NETTING Long-only、Average Cost、Linear PnL 和 REJECT flip。
- 状态通过同步函数修改，成功后发布事实 Event；EventBus 不驱动状态机。

## 拒绝方案

- 只维护账户总仓位：不能解释 Cluster 成本和收益。
- 每个 Cluster 自建账户真实仓位：多个真值会漂移，无法安全共享券商账户。
- 从账户总仓位按比例归因：会伪造策略成本和收益。
- T+1 只保存 available_quantity：无法解释结算、冻结和限制来源。
- Broker Snapshot 直接覆盖本地 Position：丢失成交历史、冲突和审计证据。
- 无归属仓位自动均分：将人工/外部交易错误归因给策略。
- Cluster 默认卖出其他策略仓位：破坏隔离和绩效真实性。
- Event handler 修改 Position：业务顺序依赖订阅配置，无法原子化。

## 结果

账户真值与策略归因可独立计算和对账，T+1 与冻结语义可解释，回测重放确定。代价是未来 ExecutionProcessor 必须按
固定顺序原子编排 Order Fill、Position、Allocation、Reservation、Account 与 Risk；启动恢复也必须完成 Broker 对账后
才能放行 Cluster。HEDGING、FIFO/LIFO、复杂公司行动和真实券商适配仍需后续 ADR。

## 验证

Position 测试覆盖 Average Cost、Linear PnL、生命周期、超卖、重复/乱序 Trade、双层归因、Unallocated、T+1、
Restriction/Reservation、券商对账、不可变序列化、Runtime 隔离及 100 次确定性重放。
