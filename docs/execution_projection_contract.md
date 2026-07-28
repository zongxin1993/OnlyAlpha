# Execution Projection Contract

Execution Projection 是可持久化、可校验、可独立安装的领域权威状态变换，不是 mutation delta。固定顺序为 ORDER、POSITION、ALLOCATION、SETTLEMENT、MARGIN、FEE、ACCOUNT、STRATEGY_LEDGER、ACCOUNT_CASH_RESERVATION、STRATEGY_CASH_RESERVATION、POSITION_RESERVATION、MARGIN_RESERVATION、RISK_RESERVATION、RISK、VALUATION。

Order、Position、Allocation、Account 与 Strategy Ledger 分别使用对应的 `Only*ExecutionState` 保存完整身份、数量/现金/成本、生命周期、时间、版本、最后外部或成交顺序和质量标志。Account State 不嵌入 Account Reservation；Ledger State 不嵌入 Strategy Cash Reservation，也不持久化 win rate、profit factor、drawdown 和 return 等可由权威时间线重算的分析值。Ledger 的 cash entries 与 fee entries 保留，因为它们是会计权威。

Reservation 不使用通用 owner scope。Account Cash、Strategy Cash、Position、Margin 与 Risk 各自拥有独立 State 和 Projection，字段与各领域实体的身份、金额/数量、消费、剩余、生命周期、时间和版本对齐。

每个 Projection Identity 包含 expected/result version、expected/result state hash、projection sequence 与 payload hash。构造时必须满足：

```text
hash(before) == expected_state_hash
hash(after)  == result_state_hash
before.version == expected_version
after.version  == result_version
```

新实体使用 `before=None`、expected version 0 和固定 null-state hash。Payload hash 覆盖 Before/After State，但排除 payload hash 自身。

正式 Apply Target 的检查顺序是 component、Applied Ledger payload、真实 Manager Current Authority、Expected/Result version/hash。Expected path 安装 result 后返回 APPLIED；Result path 只 repair replay authority 并重建 ledger record，返回 RECOVERED。结果完整区分 APPLIED、IDEMPOTENT、RECOVERED、PAYLOAD_CONFLICT、VERSION_CONFLICT、STATE_CONFLICT 和 INVALID_COMPONENT。

`OnlyPreparedExecutionEconomicInvariantValidator` 在 Prepared 构造期间交叉验证 Order Fill、Position/Allocation 数量、Fee、Account/Ledger Cash/Fee/PnL、Settlement、Margin presence、Reservation consumption 与完整 scope，禁止 Fact 与 Projection 分别形成不同经济真相。

权威公式为：

```text
Account available cash   = cash balance - frozen cash - unsettled cash
Account available margin = cash balance - frozen cash - unsettled cash - reserved margin - occupied margin
Account equity           = cash balance + position market value
Ledger cash available    = cash balance - cash reserved
Ledger equity            = cash balance + position market value
```

Account/Strategy Cash Reservation 在非 RELEASED 状态满足 `consumed + remaining = reserved`，RELEASED 状态允许小于等于以表达已释放差额。Margin Reservation 满足 `remaining + occupied + released = original`。Position 和 Risk Reservation 的 remaining/consumed authority 与原始 quantity/notional 守恒。Projection 还强制原始 authority 与 scope 不变、消费单调增加、剩余单调减少、version 每次推进一、时间不回退和终态不可恢复。

`only_expected_execution_reservations()` 是方向性 Presence Matrix。Generic T0 Cash BUY OPEN（无 Margin）只允许 Account Cash、Strategy Cash 和 Risk Reservation；SELL CLOSE 只允许 Position、Risk 以及由明确 Margin instruction 要求的 Margin Reservation。Fee instruction/records、Settlement state/records、Risk state/reservation 和所有 Reservation 都与 Fact 的 runtime/account/cluster/instrument/order/trade/currency scope 对账。Margin Fact delta 还必须与 Account Margin delta、Margin State 和 Margin Reservation 对账。

所有真实 Snapshot converter 保留字段原值，包括可选 Margin authority、metadata、quality flags、外部 sequence、时间和会计 entries；不得自行重算或伪造缺失字段。

Pure Reducers、Generic T0 Cash Transaction Planner、真实 Manager Projection Targets、Commit Coordinator 与受支持 Processor 路径均已实现。Projection Ready 是 Outbox 可见性门禁；Target 失败保留已完成前缀并由 Coordinator forward recovery。该能力不是跨 Manager rollback 或 Full Runtime Recovery，见 `execution_projection_targets.md` 与 ADR 0038–0042。

Projection Ready 同时是正式业务查询门禁。`records()` 保留为全部 committed transaction 的 Admin/Recovery query；业务链只能调用
`ready_records()`。Runtime 在 READY 前恢复未完成 Projection，任一 payload/version/state conflict 或 Store failure 都阻止启动。详细状态机
见 ADR 0042 与 `execution_runtime_recovery.md`。
