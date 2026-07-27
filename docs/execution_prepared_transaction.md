# Prepared Execution Transaction

`OnlyPreparedExecutionTransaction` 是 Broker Trade Update 与 durable commit 之间的不可变权威输入，schema version 为 3；v2 不兼容且不隐式迁移。事务 ID 由 Runtime、Gateway、Account、Broker Update 与 Trade ID 的稳定身份确定。

`authority_hash` 覆盖业务 scope、Fact Draft、有序完整状态 Projection、强制 Precondition 与确定性 Event 语义。`payload_hash` 额外覆盖完整 Prepared envelope 和 `prepared_at`。Projection payload hash 覆盖 Before/After authority，State hash 只覆盖 State 本身，不包含 Projection envelope。

每个 Precondition 都必须携带 `(component, entity_key, expected_version, expected_state_hash)`，并与同序 Projection Identity 完全一致。Prepared 构造同时执行 Projection 顺序/哈希验证、跨组件经济不变量和确定性 Event ID 验证。

`only_test_generic_t0_cash_buy_open_transaction()` 固定表达 CNY、LIMIT BUY OPEN、LONG/NETTING、T0、无 Margin、无 Position Reservation，并包含完整 Order/Account/Ledger Before、`before=None` 的 Position/Allocation、两种 Cash Reservation、真实 State Hash 和确定性 Events。`only_test_all_projection_types_transaction()` 独立用于全部 15 种 Projection 的 union/codec/schema 覆盖，不用来证明 Generic T0 经济语义。

仍未完成 Pure Reducers、Transaction Planner、Manager Projection Targets、Commit Coordinator、ExecutionProcessor 主链切换和 Full Replay Runtime；本契约不声称解决 Manager-before-Journal。
