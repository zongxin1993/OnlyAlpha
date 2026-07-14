# Order 组件验收报告

- 日期：2026-07-14
- 结论：**ACCEPTED**
- ADR：`docs/adr/0011-order-component-and-execution-port.md`

## 新增文件

- `src/onlyalpha/order/`：实体、状态结果、Manager、Query/Command Service、受限 View、ID Generator、事件、
  Publisher、Repository Port、Execution/Gateway Port、标准化 Update 与 Placeholder。
- `tests/order/`：18 项组件验收测试。
- `examples/order_demo/`：创建提交、部分成交、撤单、重复成交、乱序、Context 六个 Demo。
- `docs/order.md`、订单差距分析、ADR-0011 与本报告。

## 修改文件

- Domain：补充强类型订单标识、状态、Request/Cancel/Fill/Snapshot/Ref DTO，并迁移旧可变订单模型。
- Runtime/Context：每 Runtime 装配独立 Manager 与服务；Context 增加 Scope 受限 `ctx.orders`。
- Architecture、RuntimeContext、Cluster、Event、Testing 与 Architecture Principles 文档同步更新。
- 旧 Domain conformance 测试和 Demo 迁移到 Request → Manager → Snapshot 调用链。

## 组件与状态机验收

- Order 组件只负责订单意图、受控生命周期、Fill 聚合、查询、Scope、事件和执行端口。
- `OnlyOrderRequest` 不携带 Runtime/Cluster/Order/Venue/状态/成交字段；内部 `OnlyOrder` 不向外暴露。
- 状态集中支持 CREATED、SUBMITTED、ACCEPTED、PARTIALLY_FILLED、PENDING_CANCEL、CANCELLED、FILLED、
  REJECTED、EXPIRED、FAILED 的合法迁移；非法迁移返回结构化 INVALID。
- 终态不回退；迟到 Accepted 可补 Venue ID；取消后迟到 Fill 保留状态与历史警告。
- Decimal 加权均价正确，Overfill 拒绝，取消保留已成交数量且 active remainder 为零。
- request ID、trade ID、venue trade ID、external event ID/sequence 幂等；结果区分 APPLIED、DUPLICATE、
  STALE、INVALID、CONFLICT，未应用结果不增 version、不发 Event。

## 所有权、索引与权限验收

- 每个 Runtime 仅创建一个 Manager；不同 Runtime 的 Clock、订单、ID 序列、索引和 Event Scope 隔离。
- 同 Runtime 多 Cluster 共用 Manager；request/client/venue ID 与 Cluster/Account/Instrument/open/recent 索引一致。
- `ctx.orders` 仅暴露 submit、cancel、get、require、list_open、list_recent，自动绑定 Runtime/Cluster。
- Cluster 不能取得 Manager、Gateway、Repository，不能调用 apply_fill/set_status，不能查询或撤销其他 Cluster 订单。
- Query 只返回 frozen `OnlyOrderSnapshot`。

## 调用链、执行端口与 Event 验收

- Command、Query、State Mutation 均为函数调用；EventBus 不驱动订单迁移。
- Event 只在 Manager 成功更新后生成并发布，payload 包含变更后的 Snapshot；重复/过期/非法/冲突无事件。
- submit 的 Placeholder transport 成功只到 SUBMITTED；cancel 只到 PENDING_CANCEL。
- `OnlyExecutionService`、`OnlyTradeGateway` 与标准化 Update 已定义；Placeholder 只记录请求，不连接 SDK，
  不生成 Venue ID、Accepted、Cancelled、Fill 或 Trade。
- 未实现 RiskPipeline、PositionManager、AccountManager、ExecutionSimulator、撮合或真实交易。

## 序列化与确定性

- Request、Fill、Snapshot、Update、Event 与 MutationResult 使用版本化 DTO；Decimal 与 Unix 纳秒无损。
- 相同 Runtime ID、初始 sequence、Request 和更新序列连续运行 100 次，Order ID、Snapshot、version 和
  Event 类型顺序完全一致。
- EventBus 与 Runtime 隔离重放专项：9 项通过。

## 验证结果

```text
ruff format --check src tests examples       PASS（173 files）
ruff check src tests examples                PASS
mypy src/onlyalpha                           PASS（73 source files）
pytest -q                                    PASS（136 passed）
pytest tests/order -q                        PASS（18 passed）
确定性/重放专项                              PASS（9 passed，含 100 次订单循环）
Demo                                         PASS（19 个入口，其中 Order Demo 6/6）
失败                                         0
跳过                                         0
```

## 已知限制与后续建议

- 当前只有同步单线程 Backtest 装配；Live/Paper 的 callback queue、reconciliation 和持久化恢复未实现。
- Placeholder 不产生场所事实，因此没有显式 Update 时订单保持 SUBMITTED/PENDING_CANCEL。
- 第一阶段只支持 MARKET/LIMIT，未实现 stop/replace/amend、复杂 TIF、组合订单或券商错误映射。
- `FAILED` 当前作为非活动终态；未来 reconciliation 需要单独 ADR。

在进入后续组件前应保持独立边界：

- RiskPipeline：可以进入独立设计，但不得嵌入 Order 实体或本次 Placeholder。
- ExecutionSimulator：可以进入独立设计，成交必须由明确输入和独立 ADR 产生。
- PositionManager：可以进入独立设计，只消费成功成交事实，不反向修改 Order 状态。

## 一票否决项审计

未发现 Engine 全局 Manager、每 Cluster Manager、策略直连 Gateway、外部可变 Order、裸 float、重复累计、
迟到回退、transport 假 Accepted/Cancelled、Placeholder 假成交、变更前发 Event、Event handler 状态机、
跨 Runtime/Cluster 串流或序列化精度丢失。

最终结论：`ACCEPTED`。
