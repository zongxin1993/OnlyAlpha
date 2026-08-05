# Core Projection Replay Baseline Audit

Baseline: `70fdf9a9f21b007602d23e7dbf971ba7f0049cd0` (Historical pre-PR1.1 audit)

1. Order 只保存 status、filled quantity、average price 和外部字符串 update ID，缺少完整订单身份、参数、生命周期时间、版本、外部 sequence、错误、tags/metadata。Position 只保存 quantity/available/average/PnL 摘要；Allocation 只保存字符串 key、quantity/cost/PnL；Account 与 Ledger 仅平铺少量金额差值。它们均不能从空实体恢复 Manager authority。
2. Order 生命周期、Position/Allocation buckets 与成本、Account cash/margin/sequence、Ledger entries、所有 Reservation entity、版本与最后顺序属于权威状态。win rate、profit factor、drawdown、returns 与展示汇总可从权威时间线重算。
3. `OnlyRuntimePrecondition.expected_state_hash` 可选，Projection Identity 没有 expected/result state hash，参考 Apply 只检查 version 与 applied payload；State Hash 未参与安装。
4. `only_test_execution_projections()` 使用摘要字段、虚构 owner scope 与 delta，`only_test_prepared_execution_transaction()` 的 Precondition 不带 state hash，Fixture 只能证明类型/codec，不能证明 Fact 与 Projection 经济一致。
5. SQLite commit 捕获任意 `sqlite3.IntegrityError` 后统一查询幂等事务；无匹配事务时仍抛 `OnlyRuntimeTransactionConflict`，导致 trigger abort、outbox failure 和普通 integrity failure 被误分类。
6. 本变更删除通用 `OnlyCashReservationExecutionProjection`、`owner_scope`、所有核心摘要字段、Optional state hash、无 result state hash 的 Identity，以及旧的非经济自洽 Fixture 语义；不保留 alias、wrapper 或双写。
