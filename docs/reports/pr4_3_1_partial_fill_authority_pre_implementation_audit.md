# PR4.3.1 Partial-Fill Authority 预实施审计

- 审计日期：2026-07-30
- 实际 `master` / 任务起始提交：`41b6c220f7956c9ffad7fe5d372bf1184f33e21a`
- Prompt 预期提交：`41b6c220f7956c9ffad7fe5d372bf1184f33e21a`
- 结论：提交基线一致。可执行源码仍是 whole-fill prepared path；ADR 0041 中“多笔连续 Fill”已进入产品主链的描述与源码不一致，本实施以源码、测试和正式公共接口为准并修正文档。

## 1. 当前成交 Authority

1. `OnlyOrder` 内部保存 `_filled_quantity`、`_average_fill_price`、`_filled_at`、`_last_external_sequence`，以及仅驻留实体/Checkpoint 的 external event、trade、venue trade 去重集合；`remaining_quantity` 由请求数量减累计成交量派生。
2. `OnlyOrderSnapshot` 保存 `quantity`、`filled_quantity`、`remaining_quantity`、`average_fill_price`、`filled_at` 和 `last_external_sequence`，没有 fill count、精确累计 `price × quantity` 或最后 Trade ID。
3. `OnlyOrderExecutionState` 保存与 Snapshot 相同的成交字段，没有 fill count、精确累计成交价值或最后 Trade ID。
4. `PARTIALLY_FILLED` 已用于领域枚举、旧 `OnlyOrder.apply_fill()` 状态机、Order Manager 开放订单集合与事件选择、查询视图、Analytics 计数及领域/示例测试；prepared transaction 的纯 Order Reducer 尚未产生该状态。

## 2. Planner、Reducer 与平均价限制

5. `OnlyTradeExecutionTransactionPlanner._validate_context()` 在 `fill.quantity != order.remaining_quantity` 或 `order.filled_quantity != 0` 时返回 `PARTIAL_FILL_UNSUPPORTED`，消息为 `Fill must complete an unfilled Order`。
6. `OnlyExecutionProcessor._uses_prepared_trade_path()` 也只把首次 whole fill 路由到 prepared transaction；符合 Generic T0 其余条件的 partial fill 会落入 `_unmigrated_trade()`，直接修改 Manager。这与本任务要求的产品级 fail-closed 边界冲突。
7. `OnlyOrderTradeReducer` 不检查累计量和终态，直接把 `status` 设为 `FILLED`、`filled_quantity` 设为订单总量、`remaining_quantity` 设为零，并立即设置 `filled_at`，因此任何传入 Fill 都被当作唯一最终 Fill。
8. Reducer 和旧 `OnlyOrder._weighted_average()` 都以 `average_fill_price × filled_quantity` 反推历史名义成交值，再加入本次 `price × quantity`，最后量化平均价。
9. 该算法在多次 Fill 时存在累计舍入风险：已量化平均价不能无损恢复历史 `Σ(price × quantity)`，后续 Fill 会把早期舍入误差再次带入计算。

## 3. Transaction、幂等与 Committed Fact

10. `only_runtime_transaction_id()` 使用 identity schema version、Runtime ID、Gateway ID、Account ID、Broker Update ID 和 Trade ID，经 `\x1f` 连接及 SHA-256 生成 `ETX-...`；本任务必须保留该算法。
11. Memory Store 以 transaction、`(runtime, gateway, account, trade)` 和 `(runtime, gateway, account, update)` 三类索引识别已有事务；SQLite 以对应唯一约束及 `_find_idempotent()` 识别。相同键且 authority/payload hash 相同返回已有事务，不同则冲突。
12. 当前 Store 没有 venue trade / external event 业务身份索引。使用新的 Update ID 和 Trade ID 报告同一 Venue Trade，durable transaction 层可再次提交；Processor 的 venue trade 去重只依赖运行中/Checkpoint deduplicator，不是 transaction Store 的 durable Fill authority。
13. `OnlyCommittedExecutionFact` 已保存 trade/venue trade/update/external event、单次 fill price/quantity、累计 filled、remaining、order status、顺序和时间等审计字段；缺少 canonical fill identity、fill payload fingerprint、per-order fill index、fill count after、terminal fill 和精确累计成交价值。
14. `OnlyRuntimeTransactionQueryPort` 支持按 sequence、transaction ID、trade、update 和 Runtime records 查询；不支持按 Order、Fill Identity 或最新 Order Fill 查询。

## 4. Persistence、Checkpoint 与兼容性

15. Memory/SQLite Store 都持久化完整 prepared/committed canonical JSON；SQLite 当前 schema version 2、transaction codec schema version 4。新增 Fill 字段可复用现有 transaction payload，不需要新表或 Runtime Checkpoint schema version 迁移，但 codec/domain 反序列化必须兼容缺少新增字段的旧 whole-fill payload。
16. Order Manager Checkpoint 保存 `OnlyOrderSnapshot.to_json()`。为了在恢复后继续精确累计，Snapshot/实体必须保存精确累计成交价值；仅保存量化平均价不足够。旧 Snapshot 需要在反序列化边界推导：未成交为 count 0/value 0；已成交 whole-fill 为 count 1/value `average × filled`，且不能伪造 Trade ID。
17. 旧 whole-fill 状态可以安全推导 fill count：未成交为 0，已成交为 1；旧状态无法单独推导最后 Trade ID，需要显式兼容标记或从 durable transaction 重建。

## 5. 已有增量能力与仍存一次完成假设

18. 已天然支持增量的组件：旧 Order Entity 可累计 partial fill；Position/Allocation reducer 按本次 quantity 增量；Settlement/Fee 以 Trade ID 建立独立事实；transaction/outbox 模型本身每次 commit 都不可变且可连续分配 Runtime execution sequence。
19. 仍假设一次完成的组件：prepared path 路由、Planner whole-fill gate、纯 Order Reducer、Committed Fact 缺少 per-order fill authority、Store 的 trade 唯一约束/查询、Account/Strategy/Risk Reservation 与 Risk active-order 归约、部分 Result/Checkpoint authority。

## 6. 产品边界与实施范围

20. PR4.3.1 不能开放完整产品 Partial Fill：Account/Strategy cash reservation、Risk reservation、active order count、Account/Ledger 增量记账和 fee accrual 尚未具备逐 Fill 消费语义。开放会在第一次 partial fill 时错误终结或释放整笔 Authority。
21. 必须保留/强化的 gate：Generic T0 partial fill 必须进入 prepared planner validation 并以 `PARTIAL_FILL_ACCOUNTING_NOT_READY` 失败；不得 commit、projection、outbox 或修改 Account/Reservation/Manager。SELL/CLOSE、Futures/Margin、Virtual Broker partial schedule 和 multi-fill recovery 继续不开放。
22. 预计修改生产文件：Domain Order Snapshot/Order Entity、Execution State/adapter、Order Reducer、Fill Identity/指纹/分类、Planning Context、Planner/error code、Committed Fact/Draft、Transaction/query port、Memory/SQLite Store、Processor prepared route、Runtime planning-context builder、必要公共导出及结果/文档。
23. 原则上不修改：`commit_coordinator.py`、Recovery event gate/router、Recovery finalizer/outcome、`trade_reservations.py`、`trade_accounting.py`、Risk/Account/Ledger reducer、Virtual Broker partial schedule 和 SELL/CLOSE/Futures/Margin 路径。

## 7. 预实施决定

- 一个 Fill 对应一个不可变 Transaction；Transaction ID 与 Fill business identity 并存。
- Canonical Fill Identity 优先 `venue_trade_id`，其次 `external_event_id`，最后 `trade_id`，并包含 Runtime/Gateway/Account/Order scope。
- Payload fingerprint 使用稳定 canonical JSON、Decimal 字符串、Enum value、纳秒时间和 SHA-256。
- 每个 Order 的 fill index 由 durable committed records 计算并在同一 Store commit 冲突边界校验；不使用 source/execution sequence 作为值。
- Order Authority 精确保存 `Σ(price × quantity)`，平均价只在输出步骤量化。
- Legacy whole-fill payload 原地兼容读取，不改写历史记录、不增加新表。
