"""Immutable Order requests, snapshots, fill inputs and Trade facts."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from types import MappingProxyType

from onlyalpha.domain.base import OnlyDomainModel
from onlyalpha.domain.enums import (
    OnlyLiquiditySide,
    OnlyOffset,
    OnlyOrderSide,
    OnlyOrderStatus,
    OnlyOrderType,
    OnlyTimeInForce,
)
from onlyalpha.domain.errors import OnlyValidationError
from onlyalpha.domain.identifiers import (
    OnlyAccountId,
    OnlyClientOrderId,
    OnlyClusterId,
    OnlyInstrumentId,
    OnlyOrderId,
    OnlyOrderRequestId,
    OnlyRuntimeId,
    OnlyTradeId,
    OnlyVenueOrderId,
    OnlyVenueTradeId,
)
from onlyalpha.domain.time import OnlyTimestamp, only_require_utc
from onlyalpha.domain.value import OnlyMoney, OnlyPrice, OnlyQuantity
from onlyalpha.fee.models import OnlyBrokerFeeReportingMode


def _freeze_metadata(metadata: Mapping[str, str]) -> Mapping[str, str]:
    return MappingProxyType(dict(metadata))


@dataclass(frozen=True, slots=True)
class OnlyOrderRequest(OnlyDomainModel):
    """Strategy intent without Runtime, Cluster or generated Order identity."""

    request_id: OnlyOrderRequestId
    instrument_id: OnlyInstrumentId
    side: OnlyOrderSide
    order_type: OnlyOrderType
    quantity: OnlyQuantity
    time_in_force: OnlyTimeInForce = OnlyTimeInForce.DAY
    account_id: OnlyAccountId | None = None
    offset: OnlyOffset = OnlyOffset.NONE
    price: OnlyPrice | None = None
    stop_price: OnlyPrice | None = None
    expire_time: OnlyTimestamp | None = None
    tags: tuple[str, ...] = ()
    metadata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.quantity.value <= 0:
            raise OnlyValidationError("order quantity must be positive")
        if self.order_type is OnlyOrderType.LIMIT:
            if self.price is None or self.price.value <= 0:
                raise OnlyValidationError("LIMIT order requires a positive price")
        elif self.order_type is OnlyOrderType.MARKET:
            if self.price is not None:
                raise OnlyValidationError("MARKET order cannot contain a price")
        else:
            raise OnlyValidationError(f"unsupported first-phase order type: {self.order_type.value}")
        if self.stop_price is not None:
            raise OnlyValidationError("stop orders are not implemented in the first Order phase")
        if self.time_in_force is OnlyTimeInForce.GTD and self.expire_time is None:
            raise OnlyValidationError("GTD order requires expire_time")
        object.__setattr__(self, "tags", tuple(self.tags))
        object.__setattr__(self, "metadata", _freeze_metadata(self.metadata))

    @property
    def limit_price(self) -> OnlyPrice | None:
        """Compatibility query used by MarketRule validation."""

        return self.price


@dataclass(frozen=True, slots=True)
class OnlyCancelOrderRequest(OnlyDomainModel):
    request_id: OnlyOrderRequestId
    order_id: OnlyOrderId
    reason: str = ""
    metadata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "reason", self.reason.strip())
        object.__setattr__(self, "metadata", _freeze_metadata(self.metadata))


OnlyCancelRequest = OnlyCancelOrderRequest


@dataclass(frozen=True, slots=True)
class OnlyOrderRejection(OnlyDomainModel):
    code: str
    message: str


@dataclass(frozen=True, slots=True)
class OnlyOrderFailure(OnlyDomainModel):
    code: str
    message: str


@dataclass(frozen=True, slots=True)
class OnlyOrderFill(OnlyDomainModel):
    trade_id: OnlyTradeId
    order_id: OnlyOrderId
    price: OnlyPrice
    quantity: OnlyQuantity
    ts_event: OnlyTimestamp
    ts_init: OnlyTimestamp
    venue_trade_id: OnlyVenueTradeId | None = None
    venue_order_id: OnlyVenueOrderId | None = None
    reported_fee: OnlyMoney | None = None
    fee_reporting_mode: OnlyBrokerFeeReportingMode = OnlyBrokerFeeReportingMode.NONE
    fee_external_reference: str | None = None
    liquidity_side: OnlyLiquiditySide = OnlyLiquiditySide.UNKNOWN
    external_sequence: int | None = None
    external_event_id: str | None = None
    metadata: Mapping[str, str] = field(default_factory=dict)
    reference_price: OnlyPrice | None = None

    def __post_init__(self) -> None:
        if self.quantity.value <= 0:
            raise OnlyValidationError("fill quantity must be positive")
        if self.price.value <= 0:
            raise OnlyValidationError("fill price must be positive")
        if self.ts_init.unix_nanos < self.ts_event.unix_nanos:
            raise OnlyValidationError("fill ts_init cannot precede ts_event")
        if self.external_sequence is not None and self.external_sequence < 0:
            raise OnlyValidationError("external_sequence cannot be negative")
        object.__setattr__(self, "metadata", _freeze_metadata(self.metadata))


@dataclass(frozen=True, slots=True)
class OnlyOrderSnapshot(OnlyDomainModel):
    order_id: OnlyOrderId
    request_id: OnlyOrderRequestId
    client_order_id: OnlyClientOrderId
    venue_order_id: OnlyVenueOrderId | None
    runtime_id: OnlyRuntimeId
    cluster_id: OnlyClusterId
    account_id: OnlyAccountId
    instrument_id: OnlyInstrumentId
    side: OnlyOrderSide
    offset: OnlyOffset
    order_type: OnlyOrderType
    time_in_force: OnlyTimeInForce
    quantity: OnlyQuantity
    price: OnlyPrice | None
    stop_price: OnlyPrice | None
    expire_time: OnlyTimestamp | None
    status: OnlyOrderStatus
    filled_quantity: OnlyQuantity
    remaining_quantity: OnlyQuantity
    average_fill_price: OnlyPrice | None
    created_at: OnlyTimestamp
    updated_at: OnlyTimestamp
    submitted_at: OnlyTimestamp | None
    accepted_at: OnlyTimestamp | None
    cancel_requested_at: OnlyTimestamp | None
    cancelled_at: OnlyTimestamp | None
    filled_at: OnlyTimestamp | None
    rejected_at: OnlyTimestamp | None
    expired_at: OnlyTimestamp | None
    failed_at: OnlyTimestamp | None
    version: int
    last_external_sequence: int | None
    rejection: OnlyOrderRejection | None
    failure: OnlyOrderFailure | None
    tags: tuple[str, ...] = ()
    metadata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.version < 1:
            raise OnlyValidationError("order snapshot version must be positive")
        if self.filled_quantity.value > self.quantity.value:
            raise OnlyValidationError("filled quantity exceeds order quantity")
        if self.filled_quantity.value > 0 and self.average_fill_price is None:
            raise OnlyValidationError("filled quantity requires average_fill_price")
        if self.status is OnlyOrderStatus.FILLED and self.filled_quantity != self.quantity:
            raise OnlyValidationError("FILLED order requires full quantity")
        object.__setattr__(self, "tags", tuple(self.tags))
        object.__setattr__(self, "metadata", _freeze_metadata(self.metadata))


@dataclass(frozen=True, slots=True)
class OnlyOrderRef(OnlyDomainModel):
    runtime_id: OnlyRuntimeId
    order_id: OnlyOrderId


@dataclass(frozen=True, slots=True)
class OnlyTrade(OnlyDomainModel):
    """Immutable execution fact; OrderFill does not create this component."""

    trade_id: OnlyTradeId
    order_id: OnlyOrderId
    account_id: OnlyAccountId
    instrument_id: OnlyInstrumentId
    side: OnlyOrderSide
    offset: OnlyOffset
    price: OnlyPrice
    quantity: OnlyQuantity
    commission: OnlyMoney
    liquidity_side: OnlyLiquiditySide
    executed_at: datetime
    initialized_at: datetime | None = None

    def __post_init__(self) -> None:
        only_require_utc(self.executed_at, "executed_at")
        if self.initialized_at is not None:
            only_require_utc(self.initialized_at, "initialized_at")
            if self.initialized_at < self.executed_at:
                raise OnlyValidationError("trade initialized_at cannot precede executed_at")
        if self.quantity.value <= 0:
            raise OnlyValidationError("trade quantity must be positive")
        if self.commission.amount < 0:
            raise OnlyValidationError("trade commission cannot be negative")

    @property
    def fee(self) -> OnlyMoney:
        return self.commission

    @property
    def ts_event(self) -> datetime:
        return self.executed_at

    @property
    def ts_init(self) -> datetime:
        return self.initialized_at or self.executed_at
