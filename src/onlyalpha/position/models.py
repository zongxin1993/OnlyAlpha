"""Immutable Position commands, snapshots and broker/reconciliation DTOs."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from types import MappingProxyType

from onlyalpha.domain.base import OnlyDomainModel
from onlyalpha.domain.enums import OnlyDirection, OnlyOffset, OnlyOrderSide
from onlyalpha.domain.identifiers import (
    OnlyAccountId,
    OnlyClusterId,
    OnlyInstrumentId,
    OnlyOrderId,
    OnlyPositionId,
    OnlyRuntimeId,
    OnlyTradeId,
    OnlyVenueTradeId,
)
from onlyalpha.domain.time import OnlyTimestamp, OnlyTradingDay
from onlyalpha.domain.value import OnlyCurrency, OnlyMoney, OnlyMultiplier, OnlyPrice, OnlyQuantity
from onlyalpha.position.enums import (
    OnlyAvailabilityState,
    OnlyPositionAuthority,
    OnlyPositionMode,
    OnlyPositionMutationStatus,
    OnlyPositionRestrictionSource,
    OnlyPositionRestrictionType,
    OnlyPositionSide,
    OnlyPositionStatus,
    OnlyReconciliationAction,
    OnlyReconciliationSeverity,
    OnlySettlementBucket,
)
from onlyalpha.position.identifiers import (
    OnlyGatewayId,
    OnlyPositionAllocationId,
    OnlyPositionRestrictionId,
)
from onlyalpha.position.keys import OnlyPositionAllocationKey, OnlyPositionKey


def only_frozen_metadata(value: Mapping[str, str]) -> Mapping[str, str]:
    return MappingProxyType(dict(value))


def only_zero_quantity(precision: int) -> OnlyQuantity:
    return OnlyQuantity(Decimal(0), precision)


@dataclass(frozen=True, slots=True)
class OnlyPositionBucket(OnlyDomainModel):
    settlement: OnlySettlementBucket
    availability: OnlyAvailabilityState
    quantity: OnlyQuantity


@dataclass(frozen=True, slots=True)
class OnlyPositionRestriction(OnlyDomainModel):
    restriction_id: OnlyPositionRestrictionId
    key: OnlyPositionKey
    quantity: OnlyQuantity
    restriction_type: OnlyPositionRestrictionType
    source: OnlyPositionRestrictionSource
    effective_from: OnlyTimestamp
    effective_to: OnlyTimestamp | None
    reason: str
    version: int = 1
    metadata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.quantity.value <= 0 or self.version < 1:
            raise ValueError("Position Restriction requires positive quantity and version")
        if self.effective_to is not None and self.effective_to.unix_nanos < self.effective_from.unix_nanos:
            raise ValueError("restriction effective_to precedes effective_from")
        object.__setattr__(self, "metadata", only_frozen_metadata(self.metadata))


@dataclass(frozen=True, slots=True)
class OnlyPositionTrade(OnlyDomainModel):
    trade_id: OnlyTradeId
    venue_trade_id: OnlyVenueTradeId | None
    order_id: OnlyOrderId
    cluster_id: OnlyClusterId | None
    runtime_id: OnlyRuntimeId
    account_id: OnlyAccountId
    instrument_id: OnlyInstrumentId
    side: OnlyOrderSide
    direction: OnlyDirection
    offset: OnlyOffset
    position_side: OnlyPositionSide
    price: OnlyPrice
    quantity: OnlyQuantity
    fee: OnlyMoney
    ts_event: OnlyTimestamp
    ts_init: OnlyTimestamp
    external_sequence: int | None = None
    execution_id: str | None = None
    settlement_bucket: OnlySettlementBucket = OnlySettlementBucket.UNSETTLED
    multiplier: OnlyMultiplier = field(default_factory=lambda: OnlyMultiplier(Decimal(1), 0))
    position_mode: OnlyPositionMode = OnlyPositionMode.NETTING
    metadata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.quantity.value <= 0 or self.price.value <= 0:
            raise ValueError("Position Trade requires positive price and quantity")
        if self.fee.amount < 0:
            raise ValueError("Position Trade fee cannot be negative")
        if self.ts_init.unix_nanos < self.ts_event.unix_nanos:
            raise ValueError("Position Trade ts_init cannot precede ts_event")
        if self.external_sequence is not None and self.external_sequence < 0:
            raise ValueError("external_sequence cannot be negative")
        if self.side is OnlyOrderSide.BUY and self.direction is not OnlyDirection.BUY:
            raise ValueError("side and direction disagree")
        if self.side is OnlyOrderSide.SELL and self.direction is not OnlyDirection.SELL:
            raise ValueError("side and direction disagree")
        object.__setattr__(self, "metadata", only_frozen_metadata(self.metadata))

    @property
    def opens_position(self) -> bool:
        return self.offset in {OnlyOffset.NONE, OnlyOffset.OPEN}

    @property
    def closes_position(self) -> bool:
        return self.offset in {OnlyOffset.CLOSE, OnlyOffset.CLOSE_TODAY, OnlyOffset.CLOSE_YESTERDAY}

    @property
    def stable_order(self) -> tuple[int, int, str]:
        sequence = self.external_sequence if self.external_sequence is not None else 2**63 - 1
        return sequence, self.ts_event.unix_nanos, str(self.trade_id)


@dataclass(frozen=True, slots=True)
class OnlyPositionSnapshot(OnlyDomainModel):
    position_id: OnlyPositionId
    key: OnlyPositionKey
    status: OnlyPositionStatus
    total_quantity: OnlyQuantity
    settled_quantity: OnlyQuantity
    unsettled_quantity: OnlyQuantity
    order_frozen_quantity: OnlyQuantity
    risk_reserved_quantity: OnlyQuantity
    restricted_quantity: OnlyQuantity
    average_open_price: OnlyPrice | None
    realized_pnl: OnlyMoney
    fees: OnlyMoney
    opened_at: OnlyTimestamp
    updated_at: OnlyTimestamp
    closed_at: OnlyTimestamp | None
    version: int
    last_trade_sequence: int | None
    last_trade_order: tuple[int, int, str] | None
    quality_flags: tuple[str, ...] = ()
    broker_available_quantity: OnlyQuantity | None = None

    def __post_init__(self) -> None:
        quantities = (
            self.total_quantity,
            self.settled_quantity,
            self.unsettled_quantity,
            self.order_frozen_quantity,
            self.risk_reserved_quantity,
            self.restricted_quantity,
        )
        if len({item.precision for item in quantities}) != 1:
            raise ValueError("Position quantities require one precision")
        if self.settled_quantity.value + self.unsettled_quantity.value != self.total_quantity.value:
            raise ValueError("settled plus unsettled must equal total")
        if self.version < 1:
            raise ValueError("Position Snapshot version must be positive")

    @property
    def position_side(self) -> OnlyPositionSide:
        return self.key.position_side

    @property
    def tradable_quantity(self) -> OnlyQuantity:
        return self.settled_quantity

    @property
    def available_quantity(self) -> OnlyQuantity:
        unavailable = (
            self.order_frozen_quantity.value + self.risk_reserved_quantity.value + self.restricted_quantity.value
        )
        local_value = max(self.tradable_quantity.value - unavailable, Decimal(0))
        if self.broker_available_quantity is not None:
            local_value = min(local_value, self.broker_available_quantity.value)
        if self.status is OnlyPositionStatus.RECONCILING:
            local_value = Decimal(0)
        return OnlyQuantity(local_value, self.total_quantity.precision)

    @property
    def frozen_quantity(self) -> OnlyQuantity:
        return OnlyQuantity(
            self.order_frozen_quantity.value + self.risk_reserved_quantity.value,
            self.total_quantity.precision,
        )


@dataclass(frozen=True, slots=True)
class OnlyPositionAllocationSnapshot(OnlyDomainModel):
    allocation_id: OnlyPositionAllocationId
    key: OnlyPositionAllocationKey
    total_quantity: OnlyQuantity
    settled_quantity: OnlyQuantity
    unsettled_quantity: OnlyQuantity
    order_frozen_quantity: OnlyQuantity
    risk_reserved_quantity: OnlyQuantity
    restricted_quantity: OnlyQuantity
    average_open_price: OnlyPrice | None
    realized_pnl: OnlyMoney
    fees: OnlyMoney
    opened_at: OnlyTimestamp
    updated_at: OnlyTimestamp
    closed_at: OnlyTimestamp | None
    version: int
    last_trade_sequence: int | None
    last_trade_order: tuple[int, int, str] | None

    @property
    def available_quantity(self) -> OnlyQuantity:
        unavailable = (
            self.order_frozen_quantity.value + self.risk_reserved_quantity.value + self.restricted_quantity.value
        )
        return OnlyQuantity(
            max(self.settled_quantity.value - unavailable, Decimal(0)),
            self.total_quantity.precision,
        )


@dataclass(frozen=True, slots=True)
class OnlyUnallocatedPosition(OnlyDomainModel):
    runtime_id: OnlyRuntimeId
    account_id: OnlyAccountId
    instrument_id: OnlyInstrumentId
    position_side: OnlyPositionSide
    total_quantity: OnlyQuantity
    settled_quantity: OnlyQuantity
    unsettled_quantity: OnlyQuantity
    reason: str
    source: str
    created_at: OnlyTimestamp
    updated_at: OnlyTimestamp
    version: int = 1
    metadata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.settled_quantity.value + self.unsettled_quantity.value != self.total_quantity.value:
            raise ValueError("Unallocated buckets must equal total")
        object.__setattr__(self, "metadata", only_frozen_metadata(self.metadata))


@dataclass(frozen=True, slots=True)
class OnlyPositionMutationResult(OnlyDomainModel):
    status: OnlyPositionMutationStatus
    before: OnlyPositionSnapshot | None
    after: OnlyPositionSnapshot | None
    realized_pnl_delta: OnlyMoney
    fee: OnlyMoney
    reason: str = ""

    @property
    def changed(self) -> bool:
        return self.status is OnlyPositionMutationStatus.APPLIED


@dataclass(frozen=True, slots=True)
class OnlySettlementResult(OnlyDomainModel):
    trading_day: OnlyTradingDay
    moved_quantity: OnlyQuantity
    before_version: int
    after_version: int
    changed: bool


@dataclass(frozen=True, slots=True)
class OnlyBrokerPositionSnapshot(OnlyDomainModel):
    gateway_id: OnlyGatewayId
    account_id: OnlyAccountId
    instrument_id: OnlyInstrumentId
    position_side: OnlyPositionSide
    total_quantity: OnlyQuantity
    available_quantity: OnlyQuantity
    frozen_quantity: OnlyQuantity
    settled_quantity: OnlyQuantity
    unsettled_quantity: OnlyQuantity
    today_quantity: OnlyQuantity
    yesterday_quantity: OnlyQuantity
    broker_average_price: OnlyPrice | None
    broker_market_value: OnlyMoney | None
    snapshot_time: OnlyTimestamp
    source_sequence: int | None
    quality_flags: tuple[str, ...] = ()
    metadata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.available_quantity.value > self.total_quantity.value:
            raise ValueError("broker available exceeds total")
        object.__setattr__(self, "metadata", only_frozen_metadata(self.metadata))


@dataclass(frozen=True, slots=True)
class OnlyPositionDifference(OnlyDomainModel):
    field_name: str
    local_value: str
    broker_value: str
    authority: OnlyPositionAuthority
    severity: OnlyReconciliationSeverity


@dataclass(frozen=True, slots=True)
class OnlyPositionConflict(OnlyDomainModel):
    account_id: OnlyAccountId
    instrument_id: OnlyInstrumentId
    severity: OnlyReconciliationSeverity
    reason: str
    blocking: bool


@dataclass(frozen=True, slots=True)
class OnlyPositionReconciliationResult(OnlyDomainModel):
    local: OnlyPositionSnapshot | None
    broker: OnlyBrokerPositionSnapshot
    differences: tuple[OnlyPositionDifference, ...]
    conflicts: tuple[OnlyPositionConflict, ...]
    severity: OnlyReconciliationSeverity
    actions: tuple[OnlyReconciliationAction, ...]
    effective_available_quantity: OnlyQuantity
    reconciled: bool


@dataclass(frozen=True, slots=True)
class OnlyPositionValuation(OnlyDomainModel):
    position_id: OnlyPositionId
    mark_price: OnlyPrice
    market_value: OnlyMoney
    unrealized_pnl: OnlyMoney
    valuation_time: OnlyTimestamp
    price_source: str
    currency: OnlyCurrency
    quality_flags: tuple[str, ...] = ()
