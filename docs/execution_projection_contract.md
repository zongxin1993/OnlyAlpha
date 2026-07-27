# Execution Projection Contract

Projection 是强类型、不可变、可 canonical 编码并可独立重放的 after-state 变化，不是日志字符串。固定会计顺序为 ORDER、POSITION、ALLOCATION、SETTLEMENT、MARGIN、FEE、ACCOUNT、STRATEGY_LEDGER、ACCOUNT_CASH_RESERVATION、STRATEGY_CASH_RESERVATION、POSITION_RESERVATION、MARGIN_RESERVATION、RISK_RESERVATION、RISK、VALUATION。

Settlement 使用 `OnlySettlementProjectionState` 与 `OnlySettlementRecordReplay` 保存完整 scope、数量、现金、可用日及法律结算状态。Fee 使用 `OnlyFeeInstructionReplay`、完整 `OnlyFeeRecordReplay`、`OnlyFeeBreakdown` 与权威总额，并验证 scope、币种和总额一致。

旧的统一 Money Reservation 已删除。现金、持仓、保证金和 Risk Reservation 分别使用 `OnlyCashReservationExecutionProjection`、`OnlyPositionReservationExecutionProjection`、`OnlyMarginReservationExecutionProjection` 和 `OnlyRiskReservationExecutionProjection`，从而保留 Money/Quantity 的领域单位。普通 Risk Projection 只保存 post-trade exposure 与 risk level，不重复 Reservation authority。

每个 Projection 必须恰好对应一个同序 Precondition；Component、Entity Key 与 Expected Version 必须一致。Projection 自身的 canonical payload hash 排除 hash 字段本身。
