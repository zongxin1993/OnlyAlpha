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
from onlyalpha.domain.trading import OnlyExecutionIntent
from onlyalpha.domain.value import OnlyCurrency, OnlyMoney, OnlyPrice, OnlyQuantity
from onlyalpha.position.enums import OnlyPositionSide


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
    schema_version = 2
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
    runtime_intent_transaction_id: str = ""
    runtime_intent_authority_hash: str = ""
    execution_intent: OnlyExecutionIntent | None = None

    def __post_init__(self) -> None:
        if bool(self.runtime_intent_transaction_id) != bool(self.runtime_intent_authority_hash):
            raise ValueError("BROKER_ORDER_INTENT_REFERENCE_INCOMPLETE")
        if self.runtime_intent_authority_hash and len(self.runtime_intent_authority_hash) != 64:
            raise ValueError("BROKER_ORDER_INTENT_AUTHORITY_HASH_INVALID")
        intent = self.execution_intent or OnlyExecutionIntent.from_offset(side=self.side, offset=self.offset)
        if intent.side is not self.side:
            raise ValueError("BROKER_ORDER_CANONICAL_INTENT_CONFLICT")
        object.__setattr__(self, "execution_intent", intent)

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlyBrokerOrderRequest:
        compatible = dict(payload)
        if compatible.get("schema_version") == 1:
            compatible["execution_intent"] = OnlyExecutionIntent.from_offset(
                side=OnlyOrderSide(str(compatible["side"])),
                offset=OnlyOffset(str(compatible["offset"])),
            ).to_dict()
            compatible["schema_version"] = cls.schema_version
        return super(OnlyBrokerOrderRequest, cls).from_dict(compatible)


@dataclass(frozen=True, slots=True)
class OnlyBrokerCancelRequest(OnlyDomainModel):
    gateway_request_id: OnlyBrokerRequestId
    account_id: OnlyAccountId
    order_id: OnlyOrderId
    venue_order_id: OnlyVenueOrderId | None
    requested_at: OnlyTimestamp
    client_order_id: OnlyClientOrderId | None = None


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
    ledger_cash: OnlyMoney
    trade_available_cash: OnlyMoney
    order_reserved_cash: OnlyMoney


@dataclass(frozen=True, slots=True)
class OnlyBrokerAccountSnapshot(OnlyDomainModel):
    gateway_id: OnlyBrokerGatewayId
    account_id: OnlyAccountId
    ledger_cash: OnlyMoney
    trade_available_cash: OnlyMoney
    order_reserved_cash: OnlyMoney
    equity: OnlyMoney
    snapshot_time: OnlyTimestamp
    source_sequence: int


@dataclass(frozen=True, slots=True)
class OnlyBrokerPositionSnapshot(OnlyDomainModel):
    gateway_id: OnlyBrokerGatewayId
    account_id: OnlyAccountId
    instrument_id: OnlyInstrumentId
    position_side: OnlyPositionSide
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
    offset: OnlyOffset
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
