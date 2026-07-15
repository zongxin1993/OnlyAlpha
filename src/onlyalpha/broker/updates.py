"""Normalized immutable Broker facts delivered to a Runtime inbound queue."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType

from onlyalpha.broker.enums import OnlyBrokerConnectionState
from onlyalpha.broker.identifiers import OnlyBrokerGatewayId, OnlyBrokerUpdateId
from onlyalpha.broker.models import OnlyBrokerAccountSnapshot, OnlyBrokerPositionSnapshot
from onlyalpha.domain.base import OnlyDomainModel
from onlyalpha.domain.execution import OnlyOrderFill, OnlyOrderRejection
from onlyalpha.domain.identifiers import OnlyAccountId, OnlyOrderId, OnlyVenueOrderId
from onlyalpha.domain.time import OnlyTimestamp


@dataclass(frozen=True, slots=True, kw_only=True)
class OnlyBrokerInboundUpdate(OnlyDomainModel):
    gateway_id: OnlyBrokerGatewayId
    account_id: OnlyAccountId
    update_id: OnlyBrokerUpdateId
    source_sequence: int
    ts_event: OnlyTimestamp
    ts_init: OnlyTimestamp
    correlation_id: str
    causation_id: str
    quality_flags: tuple[str, ...] = ()
    metadata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.source_sequence < 0 or self.ts_init < self.ts_event:
            raise ValueError("Broker update requires a non-negative sequence and causal timestamps")
        object.__setattr__(self, "quality_flags", tuple(self.quality_flags))
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))


@dataclass(frozen=True, slots=True, kw_only=True)
class OnlyBrokerConnectionUpdate(OnlyBrokerInboundUpdate):
    state: OnlyBrokerConnectionState


@dataclass(frozen=True, slots=True, kw_only=True)
class OnlyBrokerOrderAcceptedUpdate(OnlyBrokerInboundUpdate):
    order_id: OnlyOrderId
    venue_order_id: OnlyVenueOrderId


@dataclass(frozen=True, slots=True, kw_only=True)
class OnlyBrokerOrderRejectedUpdate(OnlyBrokerInboundUpdate):
    order_id: OnlyOrderId
    rejection: OnlyOrderRejection


@dataclass(frozen=True, slots=True, kw_only=True)
class OnlyBrokerOrderCancelledUpdate(OnlyBrokerInboundUpdate):
    order_id: OnlyOrderId


@dataclass(frozen=True, slots=True, kw_only=True)
class OnlyBrokerTradeUpdate(OnlyBrokerInboundUpdate):
    order_id: OnlyOrderId
    fill: OnlyOrderFill


@dataclass(frozen=True, slots=True, kw_only=True)
class OnlyBrokerAccountUpdate(OnlyBrokerInboundUpdate):
    snapshot: OnlyBrokerAccountSnapshot


@dataclass(frozen=True, slots=True, kw_only=True)
class OnlyBrokerPositionUpdate(OnlyBrokerInboundUpdate):
    snapshot: OnlyBrokerPositionSnapshot
