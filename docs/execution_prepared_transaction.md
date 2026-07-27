# Prepared Execution Transaction

`OnlyPreparedExecutionTransaction` 是 Broker Trade Update 与 durable commit 之间的不可变权威输入，schema version 为 3；v2 不兼容且不隐式迁移。事务 ID 由 Runtime、Gateway、Account、Broker Update 与 Trade ID 的稳定身份确定。

Generic T0 Cash `LIMIT BUY OPEN` 的正式纯构造入口是 `OnlyTradeExecutionTransactionPlanner.prepare(context)`。Planner 从完整
immutable before authority 生成 Fact Draft、12 项 ordered Projection、逐项 Precondition 和 deterministic durable Events；相同
Context 的 canonical encoded payload 字节级一致。`prepared_at` 不进入 business authority hash，但进入完整 payload hash。

`authority_hash` 覆盖业务 scope、Fact Draft、有序完整状态 Projection、强制 Precondition 与确定性 Event 语义。`payload_hash` 额外覆盖完整 Prepared envelope 和 `prepared_at`。Projection payload hash 覆盖 Before/After authority，State hash 只覆盖 State 本身，不包含 Projection envelope。

每个 Precondition 都必须携带 `(component, entity_key, expected_version, expected_state_hash)`，并与同序 Projection Identity 完全一致。Prepared 构造同时执行 Projection 顺序/哈希验证、跨组件经济不变量和确定性 Event ID 验证。

`only_test_generic_t0_cash_buy_open_transaction()` 固定表达 CNY、LIMIT BUY OPEN、LONG/NETTING、T0、无 Margin、无 Position Reservation，并包含完整 Order/Account/Ledger Before、`before=None` 的 Position/Allocation、Account/Strategy Cash Reservation、Risk/Risk Reservation、真实 State Hash 和确定性 Events。

结构覆盖与业务合法性严格分离：`only_test_projection_codec_cases()` 返回 15 个独立 Projection union case，由 `only_encode_execution_projection()` / `only_decode_execution_projection()` 逐类型验证。不存在 all-projections Prepared Transaction；任何 Prepared 构造成功都表示 Fact、Fee、Settlement、Account/Ledger、Reservation、Margin、Risk、Scope 和 Events 经济自洽。

真实 Manager/Entity snapshot parity 测试证明 Order、Position、Allocation、Account、Ledger 和五类 Reservation 均可无损转换；相同真实 Snapshot 得到相同 State Hash，权威字段变化会改变 Hash，Mapping 插入顺序不影响 Hash。Generic T0 baseline 的 Before/After authority 与合法 Prepared fixture 使用相同 Contract，因此 PR2 只需迁移纯 Before→After 计算。

Pure Reducers 与 Generic T0 Transaction Planner 已完成，但仍未完成 Manager Projection Targets、Commit Coordinator、
ExecutionProcessor 主链切换和 Full Replay Runtime；本契约不声称生产主链已经解决 Manager-before-Journal。
