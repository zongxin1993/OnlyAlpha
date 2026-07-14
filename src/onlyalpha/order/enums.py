"""Order-component result and mutation enumerations."""

from enum import StrEnum


class OnlyOrderMutationType(StrEnum):
    CREATED = "CREATED"
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    FILLED = "FILLED"
    CANCEL_REQUESTED = "CANCEL_REQUESTED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    FAILED = "FAILED"


class OnlyOrderApplyResult(StrEnum):
    APPLIED = "APPLIED"
    DUPLICATE = "DUPLICATE"
    STALE = "STALE"
    INVALID = "INVALID"
    CONFLICT = "CONFLICT"


class OnlyOrderRejectionCode(StrEnum):
    LOCAL_VALIDATION = "LOCAL_VALIDATION"
    EXECUTION_REJECTED = "EXECUTION_REJECTED"
    VENUE_REJECTED = "VENUE_REJECTED"


class OnlyOrderFailureCode(StrEnum):
    INTERNAL = "INTERNAL"
    EXECUTION = "EXECUTION"
    RECONCILIATION_REQUIRED = "RECONCILIATION_REQUIRED"
