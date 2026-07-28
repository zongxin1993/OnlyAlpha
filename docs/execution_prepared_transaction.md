# Prepared Execution Transaction

当前 canonical transaction schema 为 v4。相较 v3，Projection payload 增加真实 Manager replay 所需的 cycle、record sequence、Strategy valuation line 和 valuation timeline metadata；旧 schema 不隐式解码。真实安装语义见 [Real Manager Projection Targets](execution_projection_targets.md)。

`OnlyPreparedExecutionTransaction` 是 Broker Trade Update 与 durable commit 之间的不可变权威输入，schema version 为 3；v2 不兼容且不隐式迁移。事务 ID 由 Runtime、Gateway、Account、Broker Update 与 Trade ID 的稳定身份确定。

Generic T0 Cash `LIMIT BUY OPEN` 的正式纯构造入口是 `OnlyTradeExecutionTransactionPlanner.prepare(context)`。Planner 从完整
immutable before authority 生成 Fact Draft、12 项 ordered Projection、逐项 Precondition 和 deterministic durable Events；相同
Context 的 canonical encoded payload 字节级一致。`prepared_at` 不进入 business authority hash，但进入完整 payload hash。

`authority_hash` 覆盖业务 scope、Fact Draft、有序完整状态 Projection、强制 Precondition 与确定性 Event 语义。`payload_hash` 额外覆盖完整 Prepared envelope 和 `prepared_at`。Projection payload hash 覆盖 Before/After authority，State hash 只覆盖 State 本身，不包含 Projection envelope。

每个 Precondition 都必须携带 `(component, entity_key, expected_version, expected_state_hash)`，并与同序 Projection Identity 完全一致。Prepared 构造同时执行 Projection 顺序/哈希验证、跨组件经济不变量和确定性 Event ID 验证。

`only_test_generic_t0_cash_buy_open_transaction()` 固定表达 CNY、LIMIT BUY OPEN、LONG/NETTING、T0、无 Margin、无 Position Reservation，并包含完整 Order/Account/Ledger Before、`before=None` 的 Position/Allocation、Account/Strategy Cash Reservation、Risk/Risk Reservation、真实 State Hash 和确定性 Events。

结构覆盖与业务合法性严格分离：`only_test_projection_codec_cases()` 返回 15 个独立 Projection union case，由 `only_encode_execution_projection()` / `only_decode_execution_projection()` 逐类型验证。不存在 all-projections Prepared Transaction；任何 Prepared 构造成功都表示 Fact、Fee、Settlement、Account/Ledger、Reservation、Margin、Risk、Scope 和 Events 经济自洽。

真实 Manager parity harness 使用正式 `OnlyExecutionProcessor`、Broker Trade Update、Market/Fee Instruction、Manager Snapshot 和
converter 建立 before/after 权威，不从 Prepared fixture 反向制造输入。四个受支持场景的 12 项 Projection after state 与真实 Manager
最终状态完整相等。相同真实 Snapshot 得到相同 State Hash，权威字段变化会改变 Hash，Mapping 插入顺序不影响 Hash。

Projection 的 `result_version` 保留 Manager 在一次成交中多次 mutation 后的最终版本，而不强制 `expected_version + 1`。因此 Account
和 Strategy Ledger 可以是 `+4`，现金 Reservation 可以是 `+2`。Prepared 的 Precondition 仍只锁定 before version/hash，原子安装
必须精确安装 Projection 声明的 result version/hash。Settlement/Fee 的记录 sequence 由 Context 中冻结的 head 确定；Planner 不读取
或推进 Manager sequence。

Planner 的 deterministic event 顺序按业务语义构造，而不是依赖字典或 EventBus priority。相同 Context 连续 100 次产生相同
transaction ID、authority/payload/projection/state hash、event count/order/ID/payload；改变 Mapping 插入顺序不改变结果，只有
`prepared_at` 改变时 business authority 不变而 envelope payload hash 改变。

Pure Reducers 与 Generic T0 Transaction Planner 已完成，但仍未完成 Manager Projection Targets、Commit Coordinator、
ExecutionProcessor 主链切换和 Full Replay Runtime；本契约不声称生产主链已经解决 Manager-before-Journal。
