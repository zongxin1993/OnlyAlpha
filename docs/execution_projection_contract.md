# Execution Projection Contract

Projection 使用固定顺序：ORDER、POSITION、ALLOCATION、SETTLEMENT、MARGIN、FEE、ACCOUNT、STRATEGY_LEDGER、RESERVATION、RISK、VALUATION。每项均保存 `component/entity_key/expected_version/result_version/projection_sequence/payload_hash` 和可重放的 before/after 业务值；核心模型不接受松散 dictionary payload。

Target 对每个 entity 实施以下规则：

- 新 sequence 且 expected version 匹配：`APPLIED`；
- 同 sequence、同 hash：`IDEMPOTENT`，状态不变；
- 同 sequence、不同 hash：`PAYLOAD_CONFLICT`；
- 新 sequence、expected version 不匹配：`VERSION_CONFLICT`；
- 投影与 Target component 不匹配：`INVALID_COMPONENT`。

`OnlyInMemoryExecutionProjectionState` 是正式轻量参考实现，只维护 version 与 applied sequence/hash，不承载 Order、Position、Account 等业务状态。`OnlyExecutionProjectionApplier` 严格按 projection sequence 执行，中途冲突立即停止，不回滚已成功项，不发布 Event，也不修改 Store Projection Ready。

当前已完成强类型 Projection union、公共幂等合同、参考状态和批量 Applier。当前未完成具体 Manager pure reducer 与 Manager Projection Target。
