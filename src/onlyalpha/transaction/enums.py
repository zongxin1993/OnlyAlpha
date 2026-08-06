"""Runtime-wide durable transaction enums."""

from enum import StrEnum


class OnlyRuntimeOperationKind(StrEnum):
    TRADE_FILL = "TRADE_FILL"
    ORDER_TERMINAL = "ORDER_TERMINAL"
    SETTLEMENT_MATURITY = "SETTLEMENT_MATURITY"
    FEE_RECONCILIATION = "FEE_RECONCILIATION"


__all__ = ["OnlyRuntimeOperationKind"]
