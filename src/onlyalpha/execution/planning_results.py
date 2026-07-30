"""Immutable intermediate results for pure execution planning."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from onlyalpha.event.model import OnlyEventSource, OnlyEventType

from .projection import OnlyExecutionProjection, OnlyExecutionProjectionComponent


class OnlyTradeExecutionPlanningErrorCode(StrEnum):
    UNSUPPORTED_MARKET_PROFILE = "UNSUPPORTED_MARKET_PROFILE"
    UNSUPPORTED_ORDER_TYPE = "UNSUPPORTED_ORDER_TYPE"
    UNSUPPORTED_ORDER_SIDE = "UNSUPPORTED_ORDER_SIDE"
    UNSUPPORTED_OFFSET = "UNSUPPORTED_OFFSET"
    UNSUPPORTED_POSITION_SIDE = "UNSUPPORTED_POSITION_SIDE"
    UNSUPPORTED_POSITION_MODE = "UNSUPPORTED_POSITION_MODE"
    FILL_EXCEEDS_REMAINING_QUANTITY = "FILL_EXCEEDS_REMAINING_QUANTITY"
    FILL_IDENTITY_CONFLICT = "FILL_IDENTITY_CONFLICT"
    DUPLICATE_FILL = "DUPLICATE_FILL"
    INVALID_FILL_INDEX = "INVALID_FILL_INDEX"
    FILL_SEQUENCE_CONFLICT = "FILL_SEQUENCE_CONFLICT"
    PARTIAL_FILL_ACCOUNTING_NOT_READY = "PARTIAL_FILL_ACCOUNTING_NOT_READY"
    MARGIN_UNSUPPORTED = "MARGIN_UNSUPPORTED"
    POSITION_RESERVATION_FORBIDDEN = "POSITION_RESERVATION_FORBIDDEN"
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
    component: OnlyExecutionProjectionComponent
    event_type: OnlyEventType
    payload: object
    source: OnlyEventSource


@dataclass(frozen=True, slots=True)
class OnlyTradeReduction:
    projection: OnlyExecutionProjection
    event_intents: tuple[OnlyExecutionEventIntent, ...] = ()


__all__ = [
    "OnlyExecutionEventIntent",
    "OnlyTradeExecutionPlanningError",
    "OnlyTradeExecutionPlanningErrorCode",
    "OnlyTradeReduction",
]
