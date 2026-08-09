"""Immutable intermediate results for pure execution planning."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from onlyalpha.event.model import OnlyEventSource, OnlyEventType
from onlyalpha.transaction.projection import OnlyRuntimeProjection, OnlyRuntimeProjectionComponent


class OnlyTradeExecutionPlanningErrorCode(StrEnum):
    CAPABILITY_ROUTING_INVARIANT_FAILED = "CAPABILITY_ROUTING_INVARIANT_FAILED"
    FILL_EXCEEDS_REMAINING_QUANTITY = "FILL_EXCEEDS_REMAINING_QUANTITY"
    FILL_IDENTITY_CONFLICT = "FILL_IDENTITY_CONFLICT"
    DUPLICATE_FILL = "DUPLICATE_FILL"
    INVALID_FILL_INDEX = "INVALID_FILL_INDEX"
    FILL_SEQUENCE_CONFLICT = "FILL_SEQUENCE_CONFLICT"
    ACCOUNT_RESERVATION_INSUFFICIENT = "ACCOUNT_RESERVATION_INSUFFICIENT"
    STRATEGY_RESERVATION_INSUFFICIENT = "STRATEGY_RESERVATION_INSUFFICIENT"
    RISK_RESERVATION_INSUFFICIENT = "RISK_RESERVATION_INSUFFICIENT"
    FEE_ACCRUAL_CONFLICT = "FEE_ACCRUAL_CONFLICT"
    FEE_ACCRUAL_NEGATIVE_INCREMENT = "FEE_ACCRUAL_NEGATIVE_INCREMENT"
    FEE_SCOPE_UNSUPPORTED = "FEE_SCOPE_UNSUPPORTED"
    RISK_REMAINING_NOTIONAL_UNDERFLOW = "RISK_REMAINING_NOTIONAL_UNDERFLOW"
    CLOSE_POSITION_REQUIRED = "CLOSE_POSITION_REQUIRED"
    CLOSE_ALLOCATION_REQUIRED = "CLOSE_ALLOCATION_REQUIRED"
    CLOSE_POSITION_INSUFFICIENT = "CLOSE_POSITION_INSUFFICIENT"
    CLOSE_ALLOCATION_INSUFFICIENT = "CLOSE_ALLOCATION_INSUFFICIENT"
    CLOSE_POSITION_RESERVATION_REQUIRED = "CLOSE_POSITION_RESERVATION_REQUIRED"
    CLOSE_POSITION_RESERVATION_INSUFFICIENT = "CLOSE_POSITION_RESERVATION_INSUFFICIENT"
    MULTI_CLUSTER_CLOSE_UNALLOCATED_COST_UNSUPPORTED = "MULTI_CLUSTER_CLOSE_UNALLOCATED_COST_UNSUPPORTED"
    SCOPE_MISMATCH = "SCOPE_MISMATCH"
    CURRENCY_MISMATCH = "CURRENCY_MISMATCH"
    MISSING_BEFORE_STATE = "MISSING_BEFORE_STATE"
    MISSING_CREATION_AUTHORITY = "MISSING_CREATION_AUTHORITY"
    UNEXPECTED_CREATION_AUTHORITY = "UNEXPECTED_CREATION_AUTHORITY"
    STALE_EXTERNAL_SEQUENCE = "STALE_EXTERNAL_SEQUENCE"
    INVALID_ORDER_STATE = "INVALID_ORDER_STATE"
    INVALID_RESERVATION_STATE = "INVALID_RESERVATION_STATE"
    REDUCTION_INVARIANT_FAILED = "REDUCTION_INVARIANT_FAILED"


class OnlyTradeExecutionPlanningError(ValueError):
    """Stable domain failure; preparation never returns partial output."""

    def __init__(self, code: OnlyTradeExecutionPlanningErrorCode, message: str) -> None:
        self.code = code
        super().__init__(f"{code.value}: {message}")


@dataclass(frozen=True, slots=True)
class OnlyExecutionEventIntent:
    component: OnlyRuntimeProjectionComponent
    event_type: OnlyEventType
    payload: object
    source: OnlyEventSource


@dataclass(frozen=True, slots=True)
class OnlyTradeReduction:
    projection: OnlyRuntimeProjection
    event_intents: tuple[OnlyExecutionEventIntent, ...] = ()


__all__ = [
    "OnlyExecutionEventIntent",
    "OnlyTradeExecutionPlanningError",
    "OnlyTradeExecutionPlanningErrorCode",
    "OnlyTradeReduction",
]
