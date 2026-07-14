"""Standardized execution and Gateway boundary DTOs."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType

from onlyalpha.domain.base import OnlyDomainModel
from onlyalpha.domain.enums import OnlyOffset, OnlyOrderSide, OnlyOrderStatus, OnlyOrderType, OnlyTimeInForce
from onlyalpha.domain.execution import OnlyOrderFailure, OnlyOrderFill, OnlyOrderRejection
from onlyalpha.domain.identifiers import (
    OnlyAccountId,
    OnlyClientOrderId,
    OnlyInstrumentId,
    OnlyOrderId,
    OnlyRuntimeId,
    OnlyVenueOrderId,
)
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.domain.value import OnlyPrice, OnlyQuantity


@dataclass(frozen=True, slots=True)
class OnlyExecutionCancelRequest(OnlyDomainModel):
    runtime_id: OnlyRuntimeId
    order_id: OnlyOrderId
    client_order_id: OnlyClientOrderId
    venue_order_id: OnlyVenueOrderId | None
    account_id: OnlyAccountId
    requested_at: OnlyTimestamp
    reason: str = ""


@dataclass(frozen=True, slots=True)
class OnlyExecutionSubmitResult(OnlyDomainModel):
    received: bool
    message: str


@dataclass(frozen=True, slots=True)
class OnlyExecutionCancelResult(OnlyDomainModel):
    received: bool
    message: str


@dataclass(frozen=True, slots=True)
class OnlyGatewayOrderRequest(OnlyDomainModel):
    runtime_id: OnlyRuntimeId
    order_id: OnlyOrderId
    client_order_id: OnlyClientOrderId
    account_id: OnlyAccountId
    instrument_id: OnlyInstrumentId
    side: OnlyOrderSide
    offset: OnlyOffset
    order_type: OnlyOrderType
    time_in_force: OnlyTimeInForce
    quantity: OnlyQuantity
    price: OnlyPrice | None


@dataclass(frozen=True, slots=True)
class OnlyGatewayCancelRequest(OnlyDomainModel):
    runtime_id: OnlyRuntimeId
    order_id: OnlyOrderId
    client_order_id: OnlyClientOrderId
    venue_order_id: OnlyVenueOrderId | None
    account_id: OnlyAccountId


@dataclass(frozen=True, slots=True)
class OnlyGatewaySubmitResult(OnlyDomainModel):
    received: bool
    message: str
    venue_order_id: OnlyVenueOrderId | None = None


@dataclass(frozen=True, slots=True)
class OnlyGatewayCancelResult(OnlyDomainModel):
    received: bool
    message: str


@dataclass(frozen=True, slots=True)
class OnlyGatewayOrderSnapshot(OnlyDomainModel):
    order_id: OnlyOrderId
    venue_order_id: OnlyVenueOrderId | None
    status: OnlyOrderStatus
    updated_at: OnlyTimestamp


@dataclass(frozen=True, slots=True)
class OnlyGatewayTradeSnapshot(OnlyDomainModel):
    fill: OnlyOrderFill


@dataclass(frozen=True, slots=True, kw_only=True)
class OnlyGatewayOrderUpdate(OnlyDomainModel):
    runtime_id: OnlyRuntimeId
    order_id: OnlyOrderId
    ts_event: OnlyTimestamp
    ts_init: OnlyTimestamp
    external_sequence: int | None = None
    external_event_id: str | None = None
    metadata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.ts_init.unix_nanos < self.ts_event.unix_nanos:
            raise ValueError("Gateway update ts_init cannot precede ts_event")
        if self.external_sequence is not None and self.external_sequence < 0:
            raise ValueError("external_sequence cannot be negative")
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))


@dataclass(frozen=True, slots=True, kw_only=True)
class OnlyGatewayOrderAcceptedUpdate(OnlyGatewayOrderUpdate):
    venue_order_id: OnlyVenueOrderId


@dataclass(frozen=True, slots=True, kw_only=True)
class OnlyGatewayOrderRejectedUpdate(OnlyGatewayOrderUpdate):
    rejection: OnlyOrderRejection


@dataclass(frozen=True, slots=True, kw_only=True)
class OnlyGatewayOrderCancelledUpdate(OnlyGatewayOrderUpdate):
    pass


@dataclass(frozen=True, slots=True, kw_only=True)
class OnlyGatewayOrderExpiredUpdate(OnlyGatewayOrderUpdate):
    pass


@dataclass(frozen=True, slots=True, kw_only=True)
class OnlyGatewayOrderFillUpdate(OnlyGatewayOrderUpdate):
    fill: OnlyOrderFill

    def __post_init__(self) -> None:
        OnlyGatewayOrderUpdate.__post_init__(self)
        if self.fill.order_id != self.order_id:
            raise ValueError("Fill update requires matching OnlyOrderFill")


@dataclass(frozen=True, slots=True, kw_only=True)
class OnlyGatewayOrderFailedUpdate(OnlyGatewayOrderUpdate):
    failure: OnlyOrderFailure
