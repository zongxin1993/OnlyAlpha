"""Immutable normalized Broker requests, results and snapshots."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType

from onlyalpha.broker.enums import OnlyBrokerConnectionState, OnlyBrokerOperationStatus
from onlyalpha.broker.identifiers import OnlyBrokerGatewayId, OnlyBrokerRequestId
from onlyalpha.domain.base import OnlyDomainModel
from onlyalpha.domain.enums import OnlyOffset, OnlyOrderSide, OnlyOrderStatus, OnlyOrderType, OnlyTimeInForce
from onlyalpha.domain.execution import OnlyOrderFill
from onlyalpha.domain.identifiers import (
    OnlyAccountId,
    OnlyClientOrderId,
    OnlyInstrumentId,
    OnlyOrderId,
    OnlyTradeId,
    OnlyVenueOrderId,
)
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.domain.value import OnlyCurrency, OnlyMoney, OnlyPrice, OnlyQuantity


def only_broker_metadata(value: Mapping[str, str]) -> Mapping[str, str]:
    return MappingProxyType(dict(value))


@dataclass(frozen=True, slots=True)
class OnlyBrokerConnectionSnapshot(OnlyDomainModel):
    gateway_id: OnlyBrokerGatewayId
    state: OnlyBrokerConnectionState
    updated_at: OnlyTimestamp
    reason: str = ""


@dataclass(frozen=True, slots=True)
class OnlyBrokerConnectionResult(OnlyDomainModel):
    status: OnlyBrokerOperationStatus
    snapshot: OnlyBrokerConnectionSnapshot


OnlyBrokerAuthenticationResult = OnlyBrokerConnectionResult
OnlyBrokerDisconnectResult = OnlyBrokerConnectionResult


@dataclass(frozen=True, slots=True)
class OnlyBrokerOrderRequest(OnlyDomainModel):
    gateway_request_id: OnlyBrokerRequestId
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
    submitted_at: OnlyTimestamp


@dataclass(frozen=True, slots=True)
class OnlyBrokerCancelRequest(OnlyDomainModel):
    gateway_request_id: OnlyBrokerRequestId
    account_id: OnlyAccountId
    order_id: OnlyOrderId
    venue_order_id: OnlyVenueOrderId | None
    requested_at: OnlyTimestamp


@dataclass(frozen=True, slots=True)
class OnlyBrokerOrderSubmitResult(OnlyDomainModel):
    request_received: bool
    status: OnlyBrokerOperationStatus
    gateway_request_id: OnlyBrokerRequestId
    client_order_id: OnlyClientOrderId
    immediate_error: str = ""


@dataclass(frozen=True, slots=True)
class OnlyBrokerCancelResult(OnlyDomainModel):
    request_received: bool
    status: OnlyBrokerOperationStatus
    gateway_request_id: OnlyBrokerRequestId
    immediate_error: str = ""


@dataclass(frozen=True, slots=True)
class OnlyBrokerBalanceSnapshot(OnlyDomainModel):
    currency: OnlyCurrency
    cash_balance: OnlyMoney
    available_cash: OnlyMoney
    frozen_cash: OnlyMoney


@dataclass(frozen=True, slots=True)
class OnlyBrokerAccountSnapshot(OnlyDomainModel):
    gateway_id: OnlyBrokerGatewayId
    account_id: OnlyAccountId
    cash_balance: OnlyMoney
    available_cash: OnlyMoney
    frozen_cash: OnlyMoney
    equity: OnlyMoney
    snapshot_time: OnlyTimestamp
    source_sequence: int


@dataclass(frozen=True, slots=True)
class OnlyBrokerPositionSnapshot(OnlyDomainModel):
    gateway_id: OnlyBrokerGatewayId
    account_id: OnlyAccountId
    instrument_id: OnlyInstrumentId
    quantity: OnlyQuantity
    available_quantity: OnlyQuantity
    frozen_quantity: OnlyQuantity
    average_price: OnlyPrice | None
    snapshot_time: OnlyTimestamp
    source_sequence: int


@dataclass(frozen=True, slots=True)
class OnlyBrokerOrderSnapshot(OnlyDomainModel):
    gateway_id: OnlyBrokerGatewayId
    account_id: OnlyAccountId
    order_id: OnlyOrderId
    client_order_id: OnlyClientOrderId
    venue_order_id: OnlyVenueOrderId
    instrument_id: OnlyInstrumentId
    side: OnlyOrderSide
    order_type: OnlyOrderType
    quantity: OnlyQuantity
    filled_quantity: OnlyQuantity
    price: OnlyPrice | None
    status: OnlyOrderStatus
    submitted_at: OnlyTimestamp
    updated_at: OnlyTimestamp
    source_sequence: int

    @property
    def remaining_quantity(self) -> OnlyQuantity:
        return OnlyQuantity(self.quantity.value - self.filled_quantity.value, self.quantity.precision)


@dataclass(frozen=True, slots=True)
class OnlyBrokerTradeSnapshot(OnlyDomainModel):
    gateway_id: OnlyBrokerGatewayId
    account_id: OnlyAccountId
    trade_id: OnlyTradeId
    fill: OnlyOrderFill
    source_sequence: int


@dataclass(frozen=True, slots=True)
class OnlyBrokerQuery(OnlyDomainModel):
    since_sequence: int | None = None
    metadata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "metadata", only_broker_metadata(self.metadata))
