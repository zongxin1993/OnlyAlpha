"""Immutable execution authority states used by projection replay."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum
from types import MappingProxyType

from onlyalpha.account.enums import OnlyAccountReservationState, OnlyAccountStatus, OnlyAccountType
from onlyalpha.account.models import OnlyAccountReservation, OnlyAccountSnapshot
from onlyalpha.domain.base import OnlyDomainModel
from onlyalpha.domain.enums import OnlyOffset, OnlyOrderSide, OnlyOrderStatus, OnlyOrderType, OnlyTimeInForce
from onlyalpha.domain.execution import OnlyOrderFailure, OnlyOrderRejection, OnlyOrderSnapshot
from onlyalpha.domain.identifiers import (
    OnlyAccountId,
    OnlyClientOrderId,
    OnlyClusterId,
    OnlyInstrumentId,
    OnlyOrderId,
    OnlyOrderRequestId,
    OnlyPositionId,
    OnlyRuntimeId,
    OnlyVenueOrderId,
)
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.domain.value import OnlyCurrency, OnlyMoney, OnlyPrice, OnlyQuantity
from onlyalpha.margin.models import OnlyMarginReservation
from onlyalpha.position.enums import (
    OnlyPositionMode,
    OnlyPositionReservationStage,
    OnlyPositionReservationState,
    OnlyPositionSide,
    OnlyPositionStatus,
    OnlySettlementBucket,
)
from onlyalpha.position.identifiers import OnlyPositionAllocationId, OnlyPositionReservationId
from onlyalpha.position.keys import OnlyPositionAllocationKey, OnlyPositionKey
from onlyalpha.position.models import OnlyPositionAllocationSnapshot, OnlyPositionSnapshot
from onlyalpha.position.reservations import OnlyPositionReservation
from onlyalpha.risk.enums import OnlyRiskReleaseReason, OnlyRiskReservationState, OnlyRiskReservationType
from onlyalpha.risk.identifiers import OnlyRiskReservationId
from onlyalpha.risk.reservations import OnlyRiskReservation
from onlyalpha.strategy_ledger.enums import (
    OnlyStrategyCashReservationStage,
    OnlyStrategyCashReservationState,
    OnlyStrategyLedgerStatus,
)
from onlyalpha.strategy_ledger.identifiers import OnlyStrategyCashReservationId, OnlyStrategyLedgerId
from onlyalpha.strategy_ledger.keys import OnlyStrategyLedgerKey
from onlyalpha.strategy_ledger.models import (
    OnlyStrategyCashEntry,
    OnlyStrategyCashReservation,
    OnlyStrategyFeeEntry,
    OnlyStrategyLedgerSnapshot,
)


def _metadata(value: Mapping[str, str]) -> Mapping[str, str]:
    return MappingProxyType(dict(value))


@dataclass(frozen=True, slots=True)
class OnlyOrderExecutionState(OnlyDomainModel):
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
        if self.version < 1 or self.quantity.value != self.filled_quantity.value + self.remaining_quantity.value:
            raise ValueError("Order execution state has invalid version or quantity authority")
        if self.filled_quantity.value > 0 and self.average_fill_price is None:
            raise ValueError("filled Order execution state requires average price")
        object.__setattr__(self, "tags", tuple(self.tags))
        object.__setattr__(self, "metadata", _metadata(self.metadata))


@dataclass(frozen=True, slots=True)
class OnlyPositionExecutionState(OnlyDomainModel):
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
            raise ValueError("Position execution quantities require one precision")
        if self.settled_quantity.value + self.unsettled_quantity.value != self.total_quantity.value:
            raise ValueError("Position execution buckets must equal total quantity")
        if self.version < 1 or (self.status is OnlyPositionStatus.CLOSED) != (self.total_quantity.value == 0):
            raise ValueError("Position execution status/version is invalid")
        object.__setattr__(self, "quality_flags", tuple(self.quality_flags))


@dataclass(frozen=True, slots=True)
class OnlyAllocationExecutionState(OnlyDomainModel):
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
            raise ValueError("Allocation execution quantities require one precision")
        if self.settled_quantity.value + self.unsettled_quantity.value != self.total_quantity.value:
            raise ValueError("Allocation execution buckets must equal total quantity")
        if self.version < 1 or (self.closed_at is not None and self.total_quantity.value != 0):
            raise ValueError("Allocation execution status/version is invalid")


@dataclass(frozen=True, slots=True)
class OnlyAccountExecutionState(OnlyDomainModel):
    runtime_id: OnlyRuntimeId
    account_id: OnlyAccountId
    gateway_id: str
    account_type: OnlyAccountType
    base_currency: OnlyCurrency
    status: OnlyAccountStatus
    cash_balance: OnlyMoney
    available_cash: OnlyMoney
    frozen_cash: OnlyMoney
    unsettled_cash: OnlyMoney
    position_market_value: OnlyMoney
    realized_pnl: OnlyMoney
    unrealized_pnl: OnlyMoney
    fees: OnlyMoney
    equity: OnlyMoney
    created_at: OnlyTimestamp
    updated_at: OnlyTimestamp
    valuation_time: OnlyTimestamp | None
    version: int
    last_external_sequence: int | None
    quality_flags: tuple[str, ...]
    reserved_margin: OnlyMoney | None
    occupied_margin: OnlyMoney | None
    released_margin: OnlyMoney | None
    available_margin: OnlyMoney | None
    metadata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        values = (
            self.cash_balance,
            self.available_cash,
            self.frozen_cash,
            self.unsettled_cash,
            self.position_market_value,
            self.realized_pnl,
            self.unrealized_pnl,
            self.fees,
            self.equity,
        )
        if any(item.currency != self.base_currency for item in values):
            raise ValueError("Account execution state requires one base currency")
        margin_values = (
            self.reserved_margin,
            self.occupied_margin,
            self.released_margin,
            self.available_margin,
        )
        if any(item is None for item in margin_values) and any(item is not None for item in margin_values):
            raise ValueError("Account execution Margin state must be complete or absent")
        present_margins = tuple(item for item in margin_values if item is not None)
        if any(item.currency != self.base_currency for item in present_margins):
            raise ValueError("Account execution Margin state requires base currency")
        if (
            min(
                self.cash_balance.amount,
                self.available_cash.amount,
                self.frozen_cash.amount,
                self.unsettled_cash.amount,
                *(item.amount for item in present_margins),
            )
            < 0
            or self.version < 1
            or self.updated_at < self.created_at
        ):
            raise ValueError("Account execution cash/version is invalid")
        if (
            self.available_cash.amount
            != self.cash_balance.amount - self.frozen_cash.amount - self.unsettled_cash.amount
        ):
            raise ValueError("Account available cash formula is invalid")
        if self.equity.amount != self.cash_balance.amount + self.position_market_value.amount:
            raise ValueError("Account equity formula is invalid")
        if self.available_margin is not None:
            assert self.reserved_margin is not None and self.occupied_margin is not None
            if self.available_margin.amount != (
                self.cash_balance.amount
                - self.frozen_cash.amount
                - self.unsettled_cash.amount
                - self.reserved_margin.amount
                - self.occupied_margin.amount
            ):
                raise ValueError("Account available margin formula is invalid")
        object.__setattr__(self, "quality_flags", tuple(self.quality_flags))
        object.__setattr__(self, "metadata", _metadata(self.metadata))


@dataclass(frozen=True, slots=True)
class OnlyStrategyLedgerExecutionState(OnlyDomainModel):
    ledger_id: OnlyStrategyLedgerId
    key: OnlyStrategyLedgerKey
    status: OnlyStrategyLedgerStatus
    initial_capital: OnlyMoney
    external_cash_flow: OnlyMoney
    cash_balance: OnlyMoney
    cash_reserved: OnlyMoney
    cash_available: OnlyMoney
    position_cost: OnlyMoney
    position_market_value: OnlyMoney
    realized_pnl: OnlyMoney
    unrealized_pnl: OnlyMoney
    fees: OnlyMoney
    equity: OnlyMoney
    cash_entries: tuple[OnlyStrategyCashEntry, ...]
    fee_entries: tuple[OnlyStrategyFeeEntry, ...]
    created_at: OnlyTimestamp
    updated_at: OnlyTimestamp
    valuation_time: OnlyTimestamp
    version: int
    last_trade_sequence: int | None
    last_trade_order: tuple[int, int, str] | None
    quality_flags: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        values = (
            self.initial_capital,
            self.external_cash_flow,
            self.cash_balance,
            self.cash_reserved,
            self.cash_available,
            self.position_cost,
            self.position_market_value,
            self.realized_pnl,
            self.unrealized_pnl,
            self.fees,
            self.equity,
        )
        if any(item.currency != self.key.base_currency for item in values):
            raise ValueError("Ledger execution state requires one base currency")
        if (
            self.cash_available.amount != self.cash_balance.amount - self.cash_reserved.amount
            or self.equity.amount != self.cash_balance.amount + self.position_market_value.amount
            or self.version < 1
            or self.updated_at < self.created_at
        ):
            raise ValueError("Ledger execution cash/version is invalid")
        object.__setattr__(self, "quality_flags", tuple(self.quality_flags))


@dataclass(frozen=True, slots=True)
class OnlyAccountCashReservationExecutionState(OnlyDomainModel):
    reservation_id: str
    runtime_id: OnlyRuntimeId
    account_id: OnlyAccountId
    order_id: OnlyOrderId
    reserved_amount: OnlyMoney
    consumed_amount: OnlyMoney
    remaining_amount: OnlyMoney
    state: OnlyAccountReservationState
    created_at: OnlyTimestamp
    updated_at: OnlyTimestamp
    version: int

    def __post_init__(self) -> None:
        values = (self.reserved_amount, self.consumed_amount, self.remaining_amount)
        if len({item.currency for item in values}) != 1 or min(item.amount for item in values) < 0:
            raise ValueError("Account cash reservation currency/amount is invalid")
        accounted = self.consumed_amount.amount + self.remaining_amount.amount
        if (
            (self.state is OnlyAccountReservationState.RELEASED and accounted > self.reserved_amount.amount)
            or (self.state is not OnlyAccountReservationState.RELEASED and accounted != self.reserved_amount.amount)
            or (self.state is OnlyAccountReservationState.CONSUMED and self.remaining_amount.amount != 0)
            or (
                self.state is OnlyAccountReservationState.ACTIVE
                and (self.consumed_amount.amount != 0 or self.remaining_amount != self.reserved_amount)
            )
            or (
                self.state is OnlyAccountReservationState.PARTIALLY_CONSUMED
                and (self.consumed_amount.amount == 0 or self.remaining_amount.amount == 0)
            )
            or (self.state is OnlyAccountReservationState.RELEASED and self.remaining_amount.amount != 0)
            or self.version < 1
            or self.updated_at < self.created_at
        ):
            raise ValueError("Account cash reservation authority is invalid")


@dataclass(frozen=True, slots=True)
class OnlyStrategyCashReservationExecutionState(OnlyDomainModel):
    reservation_id: OnlyStrategyCashReservationId
    key: OnlyStrategyLedgerKey
    order_id: OnlyOrderId
    estimated_notional: OnlyMoney
    estimated_fee: OnlyMoney
    reserved_amount: OnlyMoney
    consumed_amount: OnlyMoney
    remaining_amount: OnlyMoney
    state: OnlyStrategyCashReservationState
    stage: OnlyStrategyCashReservationStage
    created_at: OnlyTimestamp
    updated_at: OnlyTimestamp
    version: int
    metadata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        values = (
            self.estimated_notional,
            self.estimated_fee,
            self.reserved_amount,
            self.consumed_amount,
            self.remaining_amount,
        )
        if any(item.currency != self.key.base_currency for item in values):
            raise ValueError("Strategy cash reservation currency is invalid")
        accounted = self.consumed_amount.amount + self.remaining_amount.amount
        released = self.state is OnlyStrategyCashReservationState.RELEASED
        if (
            (released and accounted > self.reserved_amount.amount)
            or (not released and accounted != self.reserved_amount.amount)
            or (self.state is OnlyStrategyCashReservationState.CONSUMED and self.remaining_amount.amount != 0)
            or (
                self.state is OnlyStrategyCashReservationState.ACTIVE
                and (self.consumed_amount.amount != 0 or self.remaining_amount != self.reserved_amount)
            )
            or (
                self.state is OnlyStrategyCashReservationState.PARTIALLY_CONSUMED
                and (self.consumed_amount.amount == 0 or self.remaining_amount.amount == 0)
            )
            or (
                self.state is OnlyStrategyCashReservationState.RELEASED
                and (self.remaining_amount.amount != 0 or self.stage is not OnlyStrategyCashReservationStage.RELEASED)
            )
            or self.version < 1
            or self.updated_at < self.created_at
        ):
            raise ValueError("Strategy cash reservation authority is invalid")
        object.__setattr__(self, "metadata", _metadata(self.metadata))


@dataclass(frozen=True, slots=True)
class OnlyPositionReservationExecutionState(OnlyDomainModel):
    reservation_id: OnlyPositionReservationId
    runtime_id: OnlyRuntimeId
    account_id: OnlyAccountId
    cluster_id: OnlyClusterId
    instrument_id: OnlyInstrumentId
    position_side: OnlyPositionSide
    position_mode: OnlyPositionMode
    order_id: OnlyOrderId
    quantity: OnlyQuantity
    remaining_quantity: OnlyQuantity
    settlement_bucket: OnlySettlementBucket
    stage: OnlyPositionReservationStage
    state: OnlyPositionReservationState
    created_at: OnlyTimestamp
    updated_at: OnlyTimestamp
    version: int

    def __post_init__(self) -> None:
        if self.quantity.precision != self.remaining_quantity.precision:
            raise ValueError("Position reservation quantity precision mismatch")
        if (
            not 0 <= self.remaining_quantity.value <= self.quantity.value
            or (self.state is OnlyPositionReservationState.CONSUMED and self.remaining_quantity.value != 0)
            or (self.state is OnlyPositionReservationState.ACTIVE and self.remaining_quantity != self.quantity)
            or (
                self.state is OnlyPositionReservationState.PARTIALLY_CONSUMED
                and not 0 < self.remaining_quantity.value < self.quantity.value
            )
            or (
                self.state is OnlyPositionReservationState.RELEASED
                and (self.remaining_quantity.value != 0 or self.stage is not OnlyPositionReservationStage.RELEASED)
            )
            or self.version < 1
            or self.updated_at < self.created_at
        ):
            raise ValueError("Position reservation authority is invalid")


@dataclass(frozen=True, slots=True)
class OnlyMarginReservationExecutionState(OnlyDomainModel):
    reservation_id: str
    runtime_id: OnlyRuntimeId
    account_id: OnlyAccountId
    instrument_id: OnlyInstrumentId
    order_id: OnlyOrderId
    currency: OnlyCurrency
    original_reserved_amount: OnlyMoney
    remaining_reserved_amount: OnlyMoney
    occupied_amount: OnlyMoney
    released_amount: OnlyMoney
    maintenance_amount: OnlyMoney
    state: OnlyMarginReservationExecutionStatus
    stage: OnlyMarginReservationExecutionStage
    created_at: OnlyTimestamp
    updated_at: OnlyTimestamp
    version: int

    def __post_init__(self) -> None:
        values = (
            self.original_reserved_amount,
            self.remaining_reserved_amount,
            self.occupied_amount,
            self.released_amount,
            self.maintenance_amount,
        )
        if any(item.currency != self.currency or item.amount < 0 for item in values):
            raise ValueError("Margin reservation currency/amount is invalid")
        if (
            self.remaining_reserved_amount.amount + self.occupied_amount.amount + self.released_amount.amount
            != self.original_reserved_amount.amount
        ):
            raise ValueError("Margin reservation creates authority")
        if self.version < 1 or self.updated_at < self.created_at:
            raise ValueError("Margin reservation lifecycle is invalid")
        if (
            (self.state is OnlyMarginReservationExecutionStatus.ACTIVE and self.remaining_reserved_amount.amount <= 0)
            or (self.state is OnlyMarginReservationExecutionStatus.OCCUPIED and self.occupied_amount.amount <= 0)
            or (
                self.state is OnlyMarginReservationExecutionStatus.RELEASED
                and (
                    self.remaining_reserved_amount.amount != 0
                    or self.occupied_amount.amount != 0
                    or self.stage is not OnlyMarginReservationExecutionStage.RELEASED
                )
            )
        ):
            raise ValueError("Margin reservation state/stage is invalid")


class OnlyMarginReservationExecutionStatus(StrEnum):
    ACTIVE = "ACTIVE"
    OCCUPIED = "OCCUPIED"
    RELEASED = "RELEASED"


class OnlyMarginReservationExecutionStage(StrEnum):
    RESERVED = "RESERVED"
    OCCUPIED = "OCCUPIED"
    RELEASED = "RELEASED"


@dataclass(frozen=True, slots=True)
class OnlyRiskReservationExecutionState(OnlyDomainModel):
    reservation_id: OnlyRiskReservationId
    reservation_type: OnlyRiskReservationType
    runtime_id: OnlyRuntimeId
    cluster_id: OnlyClusterId
    account_id: OnlyAccountId
    instrument_id: OnlyInstrumentId
    order_id: OnlyOrderId
    reserved_quantity: OnlyQuantity
    reserved_notional: OnlyMoney | None
    consumed_quantity: OnlyQuantity
    consumed_notional: OnlyMoney | None
    remaining_quantity: OnlyQuantity
    remaining_notional: OnlyMoney | None
    state: OnlyRiskReservationState
    release_reason: OnlyRiskReleaseReason | None
    created_at: OnlyTimestamp
    updated_at: OnlyTimestamp
    version: int

    def __post_init__(self) -> None:
        if (
            len(
                {
                    self.reserved_quantity.precision,
                    self.consumed_quantity.precision,
                    self.remaining_quantity.precision,
                }
            )
            != 1
        ):
            raise ValueError("Risk reservation quantity precision mismatch")
        if self.consumed_quantity.value + self.remaining_quantity.value != self.reserved_quantity.value:
            raise ValueError("Risk reservation quantity authority is invalid")
        if self.reserved_notional is None:
            if self.consumed_notional is not None or self.remaining_notional is not None:
                raise ValueError("Risk reservation optional notionals disagree")
        elif (
            self.consumed_notional is None
            or self.remaining_notional is None
            or (self.consumed_notional.amount + self.remaining_notional.amount != self.reserved_notional.amount)
        ):
            raise ValueError("Risk reservation notional authority is invalid")
        if (
            self.version < 1
            or self.updated_at < self.created_at
            or (self.state is OnlyRiskReservationState.CONSUMED and self.remaining_quantity.value != 0)
            or (self.state is OnlyRiskReservationState.RELEASED and self.release_reason is None)
            or (self.state is not OnlyRiskReservationState.RELEASED and self.release_reason is not None)
        ):
            raise ValueError("Risk reservation version must be positive")


def only_order_execution_state(snapshot: OnlyOrderSnapshot) -> OnlyOrderExecutionState:
    return OnlyOrderExecutionState(
        **{name: getattr(snapshot, name) for name in OnlyOrderExecutionState.__dataclass_fields__}
    )


def only_position_execution_state(snapshot: OnlyPositionSnapshot) -> OnlyPositionExecutionState:
    return OnlyPositionExecutionState(
        **{name: getattr(snapshot, name) for name in OnlyPositionExecutionState.__dataclass_fields__}
    )


def only_allocation_execution_state(snapshot: OnlyPositionAllocationSnapshot) -> OnlyAllocationExecutionState:
    return OnlyAllocationExecutionState(
        **{name: getattr(snapshot, name) for name in OnlyAllocationExecutionState.__dataclass_fields__}
    )


def only_account_execution_state(snapshot: OnlyAccountSnapshot) -> OnlyAccountExecutionState:
    return OnlyAccountExecutionState(
        snapshot.runtime_id,
        snapshot.account_id,
        snapshot.gateway_id,
        snapshot.account_type,
        snapshot.base_currency,
        snapshot.status,
        snapshot.cash.cash_balance,
        snapshot.cash.available_cash,
        snapshot.cash.frozen_cash,
        snapshot.cash.unsettled_cash,
        snapshot.position_market_value,
        snapshot.realized_pnl,
        snapshot.unrealized_pnl,
        snapshot.fees,
        snapshot.equity,
        snapshot.created_at,
        snapshot.updated_at,
        snapshot.valuation_time,
        snapshot.version,
        snapshot.last_external_sequence,
        snapshot.quality_flags,
        snapshot.reserved_margin,
        snapshot.occupied_margin,
        snapshot.released_margin,
        snapshot.available_margin,
        snapshot.metadata,
    )


def only_strategy_ledger_execution_state(snapshot: OnlyStrategyLedgerSnapshot) -> OnlyStrategyLedgerExecutionState:
    return OnlyStrategyLedgerExecutionState(
        snapshot.ledger_id,
        snapshot.key,
        snapshot.status,
        snapshot.capital.initial_capital,
        snapshot.capital.external_cash_flow,
        snapshot.cash.cash_balance,
        snapshot.cash.cash_reserved,
        snapshot.cash.cash_available,
        snapshot.equity.position_cost,
        snapshot.equity.position_market_value,
        snapshot.pnl.realized_pnl,
        snapshot.pnl.unrealized_pnl,
        snapshot.pnl.fees,
        snapshot.equity.equity,
        snapshot.cash_entries,
        snapshot.fee_entries,
        snapshot.created_at,
        snapshot.updated_at,
        snapshot.valuation_time,
        snapshot.version,
        snapshot.last_trade_sequence,
        snapshot.last_trade_order,
        snapshot.quality_flags,
    )


def only_account_cash_reservation_execution_state(
    reservation: OnlyAccountReservation,
) -> OnlyAccountCashReservationExecutionState:
    return OnlyAccountCashReservationExecutionState(
        str(reservation.reservation_id),
        reservation.runtime_id,
        reservation.account_id,
        reservation.order_id,
        reservation.reserved_amount,
        reservation.consumed_amount,
        reservation.remaining_amount,
        reservation.state,
        reservation.created_at,
        reservation.updated_at,
        reservation.version,
    )


def only_strategy_cash_reservation_execution_state(
    reservation: OnlyStrategyCashReservation,
) -> OnlyStrategyCashReservationExecutionState:
    return OnlyStrategyCashReservationExecutionState(
        **{name: getattr(reservation, name) for name in OnlyStrategyCashReservationExecutionState.__dataclass_fields__}
    )


def only_position_reservation_execution_state(
    reservation: OnlyPositionReservation,
) -> OnlyPositionReservationExecutionState:
    return OnlyPositionReservationExecutionState(
        **{name: getattr(reservation, name) for name in OnlyPositionReservationExecutionState.__dataclass_fields__}
    )


def only_margin_reservation_execution_state(
    reservation: OnlyMarginReservation,
) -> OnlyMarginReservationExecutionState:
    if reservation.reserved > 0:
        status = OnlyMarginReservationExecutionStatus.ACTIVE
        stage = OnlyMarginReservationExecutionStage.RESERVED
    elif reservation.occupied > 0:
        status = OnlyMarginReservationExecutionStatus.OCCUPIED
        stage = OnlyMarginReservationExecutionStage.OCCUPIED
    else:
        status = OnlyMarginReservationExecutionStatus.RELEASED
        stage = OnlyMarginReservationExecutionStage.RELEASED
    return OnlyMarginReservationExecutionState(
        reservation.reservation_id,
        reservation.runtime_id,
        reservation.account_id,
        reservation.instrument_id,
        reservation.source_order_id,
        reservation.currency,
        OnlyMoney(reservation.original_reserved, reservation.currency),
        OnlyMoney(reservation.reserved, reservation.currency),
        OnlyMoney(reservation.occupied, reservation.currency),
        OnlyMoney(reservation.released, reservation.currency),
        OnlyMoney(reservation.maintenance_required, reservation.currency),
        status,
        stage,
        reservation.created_at,
        reservation.updated_at,
        reservation.version,
    )


def only_risk_reservation_execution_state(
    reservation: OnlyRiskReservation,
) -> OnlyRiskReservationExecutionState:
    consumed_quantity = reservation.consumed_quantity or OnlyQuantity(
        Decimal(0), reservation.reserved_quantity.precision
    )
    return OnlyRiskReservationExecutionState(
        reservation.reservation_id,
        reservation.reservation_type,
        reservation.runtime_id,
        reservation.cluster_id,
        reservation.account_id,
        reservation.instrument_id,
        reservation.order_id,
        reservation.reserved_quantity,
        reservation.reserved_notional,
        consumed_quantity,
        reservation.consumed_notional,
        reservation.remaining_quantity,
        reservation.remaining_notional,
        reservation.state,
        reservation.release_reason,
        reservation.created_at,
        reservation.updated_at,
        reservation.version,
    )


__all__ = [name for name in globals() if name.startswith("Only") or name.startswith("only_")]
