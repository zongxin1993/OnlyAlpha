"""Immutable Order mutation and strategy-command results."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING

from onlyalpha.domain.base import OnlyDomainModel
from onlyalpha.domain.enums import OnlyOrderStatus
from onlyalpha.domain.execution import OnlyOrderSnapshot
from onlyalpha.domain.identifiers import OnlyClientOrderId, OnlyOrderId
from onlyalpha.event.model import OnlyEvent
from onlyalpha.order.enums import OnlyOrderApplyResult, OnlyOrderMutationType
from onlyalpha.order.events import (
    OnlyOrderAcceptedEvent,
    OnlyOrderCancelledEvent,
    OnlyOrderCancelRequestedEvent,
    OnlyOrderCreatedEvent,
    OnlyOrderExpiredEvent,
    OnlyOrderFailedEvent,
    OnlyOrderFilledEvent,
    OnlyOrderPartiallyFilledEvent,
    OnlyOrderRejectedEvent,
    OnlyOrderSubmittedEvent,
)

if TYPE_CHECKING:
    from onlyalpha.risk.decisions import OnlyRiskDecision, OnlyRiskErrorInfo, OnlyRiskRejection

_ONLY_ORDER_EVENT_TYPES: dict[str, type[OnlyEvent]] = {
    "ORDER_CREATED": OnlyOrderCreatedEvent,
    "ORDER_SUBMITTED": OnlyOrderSubmittedEvent,
    "ORDER_ACCEPTED": OnlyOrderAcceptedEvent,
    "ORDER_PARTIALLY_FILLED": OnlyOrderPartiallyFilledEvent,
    "ORDER_FILLED": OnlyOrderFilledEvent,
    "ORDER_CANCEL_REQUESTED": OnlyOrderCancelRequestedEvent,
    "ORDER_CANCELLED": OnlyOrderCancelledEvent,
    "ORDER_REJECTED": OnlyOrderRejectedEvent,
    "ORDER_EXPIRED": OnlyOrderExpiredEvent,
    "ORDER_FAILED": OnlyOrderFailedEvent,
}


@dataclass(frozen=True, slots=True)
class OnlyOrderMutationResult(OnlyDomainModel):
    order_id: OnlyOrderId
    mutation_type: OnlyOrderMutationType
    previous_status: OnlyOrderStatus | None
    current_status: OnlyOrderStatus
    apply_result: OnlyOrderApplyResult
    changed: bool
    duplicate: bool
    stale: bool
    version: int
    snapshot: OnlyOrderSnapshot
    events: tuple[OnlyEvent, ...] = ()
    error: str | None = None
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "order_id": str(self.order_id),
            "mutation_type": self.mutation_type.value,
            "previous_status": None if self.previous_status is None else self.previous_status.value,
            "current_status": self.current_status.value,
            "apply_result": self.apply_result.value,
            "changed": self.changed,
            "duplicate": self.duplicate,
            "stale": self.stale,
            "version": self.version,
            "snapshot": self.snapshot.to_dict(),
            "events": [event.to_dict() for event in self.events],
            "error": self.error,
            "warnings": list(self.warnings),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlyOrderMutationResult:
        snapshot = payload["snapshot"]
        events = payload["events"]
        warnings = payload["warnings"]
        if not isinstance(snapshot, Mapping) or not isinstance(events, list) or not isinstance(warnings, list):
            raise ValueError("invalid mutation result payload")
        previous = payload.get("previous_status")
        return cls(
            OnlyOrderId(str(payload["order_id"])),
            OnlyOrderMutationType(str(payload["mutation_type"])),
            None if previous is None else OnlyOrderStatus(str(previous)),
            OnlyOrderStatus(str(payload["current_status"])),
            OnlyOrderApplyResult(str(payload["apply_result"])),
            bool(payload["changed"]),
            bool(payload["duplicate"]),
            bool(payload["stale"]),
            int(str(payload["version"])),
            OnlyOrderSnapshot.from_dict(snapshot),
            tuple(
                _ONLY_ORDER_EVENT_TYPES.get(str(item.get("event_type")), OnlyEvent).from_dict(item)
                for item in events
                if isinstance(item, Mapping)
            ),
            None if payload.get("error") is None else str(payload["error"]),
            tuple(str(item) for item in warnings),
        )


@dataclass(frozen=True, slots=True)
class OnlyOrderSubmitResult:
    created: bool
    submitted: bool
    venue_accepted: bool | None
    order_id: OnlyOrderId | None
    client_order_id: OnlyClientOrderId | None
    snapshot: OnlyOrderSnapshot | None
    events: tuple[OnlyEvent, ...]
    error: str | None = None
    risk_decision: OnlyRiskDecision | None = None

    @property
    def risk_rejection(self) -> OnlyRiskRejection | None:
        return None if self.risk_decision is None else self.risk_decision.rejection

    @property
    def risk_error(self) -> OnlyRiskErrorInfo | None:
        return None if self.risk_decision is None else self.risk_decision.error


@dataclass(frozen=True, slots=True)
class OnlyOrderCancelResult:
    requested: bool
    cancelled: bool
    snapshot: OnlyOrderSnapshot
    events: tuple[OnlyEvent, ...]
    error: str | None = None
