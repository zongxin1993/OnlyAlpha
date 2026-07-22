# SHORT Execution Scope Audit

审计日期：2026-07-22。审计范围：`execution`、`position`、`broker`、`market`、`runtime`、插件和测试。

## 结论

此前成交转换已能从 `Order Side + Offset` 推导 SHORT，但同一 Update 的 Snapshot、失败阻断和公共 Broker
Position 转换仍写死 `OnlyPositionSide.LONG`。这是通用 Core 的语义缺陷，不是 MiniQMT 股票现货 LONG-only 能力边界。

现已建立 `OnlyExecutionPositionScope` 与唯一的 `OnlyExecutionPositionScopeResolver`：订单、市场成交指令和 Broker
持仓分别产生不可变 Scope；执行处理、Snapshot、Audit、失败 Reconciliation Request 与阻断均消费该 Scope。

## 映射与入口

| 输入 | Position Side | Effect | 入口 |
|---|---|---|---|
| BUY + OPEN | LONG | OPEN | `OnlyExecutionPositionScopeResolver.resolve_order` |
| SELL + OPEN | SHORT | OPEN | 同上 |
| SELL + CLOSE/CLOSE_TODAY/CLOSE_YESTERDAY | LONG | CLOSE | 同上 |
| BUY + CLOSE/CLOSE_TODAY/CLOSE_YESTERDAY | SHORT | CLOSE | 同上 |
| Market Trade Instruction | 指令显式值 | 指令显式值 | `resolve_trade`，优先级最高且与 Order 冲突即失败 |
| Broker Position Snapshot | DTO 显式值 | AUTO | `resolve_broker_position`，不从数量符号推断 |

`Offset.NONE` 仅在已规范化的现金 LONG-only 订单边界作为 `NORMALIZED_CASH_ORDER` 解释；通用成交规则以 Market
Instruction 为准。

## Position/Allocation Key 与 Snapshot

Position Key 的构造位于 Scope Resolver；Allocation Key 与其一起构造且强制 side 一致。`OnlyExecutionSnapshotBundle`
保存完整 Scope，读取 Position/Allocation 时使用 Scope 的 Key，不再构造固定 LONG Key。Audit 与 Reconciliation
Request 同样保存 Scope，因此消费者无需重复推导方向。

## Broker 与阻断

公共 `OnlyBrokerPositionSnapshot` 现要求显式 `position_side`。Virtual Broker 输出实际 LONG Snapshot；MiniQMT 股票
Adapter 显式输出 LONG，限定在其当前股票现货能力，不把这一假设泄漏到 Core。Broker 的 SHORT Snapshot 直接进入
同 side 的本地 reconciliation。

失败阻断使用 Scope 的 Position Key；因此 SHORT 部分 mutation 只阻断 SHORT，绝不会误阻断无关 LONG。当前实体不存在
时 Position Manager 无法设置 RECONCILING，账户仍进入 reconciliation；持久化、独立于实体的 Block Registry 是后续恢复
编排能力，尚未实现。

## 默认 LONG 审计

`OnlyPositionKey`、查询视图和 Reservation Manager 仍有 LONG 默认值，服务于现有现金现货查询/兼容 API；它们不参与
Execution Processor 的 Scope 解析。执行快照、失败阻断、Broker DTO 转换和成交 Side 推断中的错误默认 LONG 已删除。
Reservation Adapter 仍有独立 Side+Offset 推断，需在后续下单预检接入 Resolver，不能将其误称为已完成的全链路迁移。

## 测试缺口

已运行现有 Execution/Position 回归（20 项）。尚未具备完整的 futures SHORT Engine Scenario、独立 Block Registry、
SHORT Reservation 生命周期、HEDGING/NETTING conformance 和 MiniQMT futures 实盘语义；这些不能以当前股票 Virtual
Broker 覆盖率宣称完成。
