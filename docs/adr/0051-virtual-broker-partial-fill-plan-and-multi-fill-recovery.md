# ADR 0051: Virtual Broker Partial-Fill Plan and Multi-Fill Recovery

- Status: Accepted
- Date: 2026-07-30

## Context

Virtual Broker 原有 `maximum_fill_quantity` 能在每个触价 Bar 隐式执行 `min(remaining, maximum)`，但没有订单级显式
计划、cursor、稳定 identity 或独立 checkpoint authority；同一订单每个 Bar 最多一个 Fill，也无法表达同 Bar 多 Fill。
Order/Trade 查询依赖 dict 插入顺序，Gateway checkpoint 没有自身 schema version。ADR 0049、0050 已保证每个外部 Fill
对应一笔 immutable transaction，并完成增量 Reservation、Fee、Account、Ledger 与 Risk accounting，因此本阶段不重新
设计 Runtime transaction path。

## Decision

Virtual Broker 将所有部分成交统一归一化为订单级 `OnlyVirtualOrderFillPlan`：

- `WHOLE`：一个 Step 成交全部数量；
- `MAX_PER_BAR`：兼容 `maximum_fill_quantity`，归一化为连续 Bar Step；
- `SCHEDULE`：显式 quantity 或 ratio Step；
- `ONE_PER_BAR`：每个订单每 Bar 最多执行一个到期 Step；
- `ALL_DUE`：按 Step Index 在同 Bar执行全部到期 Step。

Schedule 的 offset 非递减；ONE_PER_BAR 拒绝重复 offset。Quantity steps 的总量必须精确等于订单量。Ratio steps 的总和
必须为 1；前 N-1 项按 quantity precision 向下量化，最后一项接收全部 remainder，因此不存在独立 rounding 导致的
overfill/underfill。

Plan 保存原始数量、acceptance bar sequence、归一化 steps、cursor、status 与严格递增 version。Plan ID 是
`VPLAN-<sha256>`；fingerprint 与 ID 使用 schema、Gateway/Account/Order/Venue Order、精确数量和 precision、模式、dispatch
模式及归一化 steps 的 canonical JSON。禁止 Python `hash()`、时间或随机 identity。Plan 是外部模拟 Broker authority，
不替代 Runtime 的 Transaction ID、Fill Identity/Fingerprint 或 Fill Index。

Plan 在 Broker acceptance 冻结资金前完成归一化和校验，随后按固定顺序保存 ACCEPTED Order 与 Plan。触价时由 Plan
选择 due step；Matching 只决定价格资格，不再拥有独立成交量链。每个 Step 独立生成 Trade/Venue Trade/Update/Source
identity，并依次更新 Broker Account、Order、Trade、Plan cursor，再 schedule `PUBLISH_FILL`。因此 Broker execute 与 Runtime
publish 是明确两阶段；checkpoint 可以保存已成交但尚未发布的事实，恢复后只执行 pending publish。

Open Order/Order Query 明确按 `(venue_order_id, order_id)` 排序；Trade Query 按 `(source_sequence, trade_id)` 排序。撤销
`ACCEPTED/PARTIALLY_FILLED` Order 会释放剩余 Broker reservation、将 Order 与 Plan 同时置为 CANCELLED，并保留已经 execute
但尚未 publish 的成交事实。

## Checkpoint V2 and recovery

Gateway payload 增加 `schema_version=2` 与完整 Fill Plan Store；官方插件 descriptor 和 Runtime 的 `broker.virtual`
participant 都升级为 version 2。Registry fingerprint 使 version 1 checkpoint fail fast，不为旧订单推测 Plan。

Restore 顺序为 Account → Order → Trade → Plan → accepted/bar/plugin/sequence state → Scheduler，最后验证 Plan/Order
数量和状态、executed steps/Trades、pending `PUBLISH_FILL` 与 sequence head 的一致性。

Runtime 继续使用既有 checkpoint restore、exact replay、ready rehydration、unprojected recovery、continuation、authority
validation、durable finalization 与 Event Gate。阻塞性 Execution 结果会冻结后续 deterministic Broker work 和 checkpoint
barrier，避免把不一致 Broker/Runtime authority 写成新稳定 checkpoint。恢复校验允许 checkpointable deterministic Broker
因已验证的 pending publish 而短暂领先本地 Order；本地 authority 不得领先 Broker。没有新增 Recovery Phase，也没有修改
Commit Coordinator、Fill Identity、Fill Index、Event Gate、Outbox 或 ADR 0050 accounting。

## Consequences and limits

跨 Bar `300/400/300`、同 Bar多 Fill、部分成交后撤单、execute-before-publish、Commit/Projection/Outbox tail、部分 Plan
checkpoint continuation 和 A→B→C restart 均使用同一正式产品链。每个 Fill 仍是一笔独立 immutable transaction，Outbox
仍为 at-least-once，Direct Event 仍为 best-effort。

本 ADR 只开放 Generic T0 Cash、LIMIT BUY OPEN、LONG NETTING、单币种、无 Margin。SELL/CLOSE、Position Reservation
正式消费、Futures/Margin、Paper/Live recovery、订单簿、Exactly-once 与 Subscriber ACK 不在范围内；PR4.4 继续实现
SELL/CLOSE Durable Transaction。
