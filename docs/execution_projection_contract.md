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

参考 Apply Target 的检查顺序是 component、同 execution sequence 的 payload、expected version、expected state hash；之后才安装 result version/hash。结果明确区分 APPLIED、IDEMPOTENT、PAYLOAD_CONFLICT、VERSION_CONFLICT、STATE_CONFLICT 和 INVALID_COMPONENT。

`OnlyPreparedExecutionEconomicInvariantValidator` 在 Prepared 构造期间交叉验证 Order Fill、Position/Allocation 数量、Fee、Account/Ledger Cash/Fee/PnL、Settlement、Margin presence、Reservation consumption 与完整 scope，禁止 Fact 与 Projection 分别形成不同经济真相。

本契约尚未实现 Pure Reducers、Transaction Planner、真实 Manager Projection Targets、Commit Coordinator、Processor Switch 或 Full Replay Runtime。
