"""Strongly typed, replay-complete execution projections and apply contracts."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import IntEnum, StrEnum
from typing import Protocol, cast

from onlyalpha.broker.identifiers import OnlyBrokerUpdateId
from onlyalpha.domain.base import OnlyDomainModel
from onlyalpha.domain.enums import OnlyOrderStatus
from onlyalpha.domain.execution import OnlyOrderFill
from onlyalpha.domain.identifiers import OnlyAccountId, OnlyClusterId, OnlyInstrumentId, OnlyOrderId
from onlyalpha.domain.time import OnlyTimestamp, OnlyTradingDay
from onlyalpha.domain.value import OnlyMoney, OnlyQuantity
from onlyalpha.fee.models import OnlyFeeBreakdown
from onlyalpha.risk.enums import OnlyRiskLevel

from .execution_state import (
    OnlyAccountCashReservationExecutionState,
    OnlyAccountExecutionState,
    OnlyAllocationExecutionState,
    OnlyMarginReservationExecutionState,
    OnlyOrderExecutionState,
    OnlyPositionExecutionState,
    OnlyPositionReservationExecutionState,
    OnlyRiskReservationExecutionState,
    OnlyStrategyCashReservationExecutionState,
    OnlyStrategyLedgerExecutionState,
)
from .state_hash import only_execution_state_hash


class OnlyExecutionProjectionComponent(StrEnum):
    ORDER = "ORDER"
    POSITION = "POSITION"
    ALLOCATION = "ALLOCATION"
    SETTLEMENT = "SETTLEMENT"
    MARGIN = "MARGIN"
    FEE = "FEE"
    ACCOUNT = "ACCOUNT"
    STRATEGY_LEDGER = "STRATEGY_LEDGER"
    ACCOUNT_CASH_RESERVATION = "ACCOUNT_CASH_RESERVATION"
    STRATEGY_CASH_RESERVATION = "STRATEGY_CASH_RESERVATION"
    POSITION_RESERVATION = "POSITION_RESERVATION"
    MARGIN_RESERVATION = "MARGIN_RESERVATION"
    RISK_RESERVATION = "RISK_RESERVATION"
    RISK = "RISK"
    VALUATION = "VALUATION"


class OnlyExecutionProjectionOrder(IntEnum):
    ORDER = 1
    POSITION = 2
    ALLOCATION = 3
    SETTLEMENT = 4
    MARGIN = 5
    FEE = 6
    ACCOUNT = 7
    STRATEGY_LEDGER = 8
    ACCOUNT_CASH_RESERVATION = 9
    STRATEGY_CASH_RESERVATION = 10
    POSITION_RESERVATION = 11
    MARGIN_RESERVATION = 12
    RISK_RESERVATION = 13
    RISK = 14
    VALUATION = 15


@dataclass(frozen=True, slots=True)
class OnlyExecutionProjectionIdentity(OnlyDomainModel):
    component: OnlyExecutionProjectionComponent
    entity_key: str
    expected_version: int
    result_version: int
    expected_state_hash: str
    result_state_hash: str
    projection_sequence: int
    payload_hash: str

    def __post_init__(self) -> None:
        if not self.entity_key.strip() or self.expected_version < 0:
            raise ValueError("projection identity requires an entity and non-negative expected version")
        if self.result_version <= self.expected_version or self.projection_sequence < 1:
            raise ValueError("projection result version and sequence must advance")
        _require_digest(self.expected_state_hash, "projection expected_state_hash")
        _require_digest(self.result_state_hash, "projection result_state_hash")
        _require_digest(self.payload_hash, "projection payload_hash")


@dataclass(frozen=True, slots=True)
class OnlyOrderExecutionProjection(OnlyDomainModel):
    identity: OnlyExecutionProjectionIdentity
    before: OnlyOrderExecutionState
    after: OnlyOrderExecutionState
    fill: OnlyOrderFill
    broker_update_id: OnlyBrokerUpdateId

    def __post_init__(self) -> None:
        _require_component(self.identity, OnlyExecutionProjectionComponent.ORDER)
        _require_state_contract(self.identity, self.before, self.after)
        if _order_scope(self.before) != _order_scope(self.after) or self.identity.entity_key != str(
            self.after.order_id
        ):
            raise ValueError("Order projection before/after scope mismatch")
        if self.before.quantity != self.after.quantity:
            raise ValueError("Order projection cannot change original quantity")
        if self.after.filled_quantity.value < self.before.filled_quantity.value:
            raise ValueError("Order projection cannot reduce cumulative fill")
        if self.fill.order_id != self.after.order_id or not str(self.broker_update_id).strip():
            raise ValueError("Order projection fill/update identity mismatch")
        if self.after.filled_quantity.value - self.before.filled_quantity.value != self.fill.quantity.value:
            raise ValueError("Order projection fill delta mismatch")
        if self.after.remaining_quantity.value == 0 and self.after.status is not OnlyOrderStatus.FILLED:
            raise ValueError("fully filled Order projection requires FILLED status")
        if self.after.last_external_sequence is not None and self.before.last_external_sequence is not None:
            if self.after.last_external_sequence < self.before.last_external_sequence:
                raise ValueError("Order projection external sequence cannot regress")


@dataclass(frozen=True, slots=True)
class OnlyPositionExecutionProjection(OnlyDomainModel):
    identity: OnlyExecutionProjectionIdentity
    before: OnlyPositionExecutionState | None
    after: OnlyPositionExecutionState
    realized_pnl_delta: OnlyMoney

    def __post_init__(self) -> None:
        _require_component(self.identity, OnlyExecutionProjectionComponent.POSITION)
        _require_state_contract(self.identity, self.before, self.after)
        if self.identity.entity_key != str(self.after.position_id):
            raise ValueError("Position projection entity key mismatch")
        if self.before is not None:
            if self.before.position_id != self.after.position_id or self.before.key != self.after.key:
                raise ValueError("Position projection before/after scope mismatch")
            if self.after.realized_pnl.amount - self.before.realized_pnl.amount != self.realized_pnl_delta.amount:
                raise ValueError("Position projection realized PnL mismatch")
            _require_last_trade_order(self.before.last_trade_order, self.after.last_trade_order)
        elif self.identity.expected_version != 0 or self.identity.result_version != 1:
            raise ValueError("new Position projection must advance version zero to one")
        if self.realized_pnl_delta.currency != self.after.realized_pnl.currency:
            raise ValueError("Position projection currency mismatch")
        if self.before is not None and self.after.fees.amount < self.before.fees.amount:
            raise ValueError("Position projection cumulative fees cannot regress")


@dataclass(frozen=True, slots=True)
class OnlyAllocationExecutionProjection(OnlyDomainModel):
    identity: OnlyExecutionProjectionIdentity
    before: OnlyAllocationExecutionState | None
    after: OnlyAllocationExecutionState
    realized_pnl_delta: OnlyMoney

    def __post_init__(self) -> None:
        _require_component(self.identity, OnlyExecutionProjectionComponent.ALLOCATION)
        _require_state_contract(self.identity, self.before, self.after)
        if self.identity.entity_key != str(self.after.allocation_id):
            raise ValueError("Allocation projection entity key mismatch")
        if self.before is not None:
            if self.before.allocation_id != self.after.allocation_id or self.before.key != self.after.key:
                raise ValueError("Allocation projection before/after scope mismatch")
            if self.after.realized_pnl.amount - self.before.realized_pnl.amount != self.realized_pnl_delta.amount:
                raise ValueError("Allocation projection realized PnL mismatch")
            _require_last_trade_order(self.before.last_trade_order, self.after.last_trade_order)
        elif self.identity.expected_version != 0 or self.identity.result_version != 1:
            raise ValueError("new Allocation projection must advance version zero to one")
        if self.realized_pnl_delta.currency != self.after.realized_pnl.currency:
            raise ValueError("Allocation projection currency mismatch")
        if self.before is not None and self.after.fees.amount < self.before.fees.amount:
            raise ValueError("Allocation projection cumulative fees cannot regress")


@dataclass(frozen=True, slots=True)
class OnlySettlementExecutionState(OnlyDomainModel):
    instruction_id: str
    account_id: OnlyAccountId
    instrument_id: OnlyInstrumentId
    source_order_id: OnlyOrderId
    source_trade_id: str
    asset_quantity: Decimal
    cash_amount: OnlyMoney
    asset_released: bool
    trade_cash_released: bool
    withdrawable_cash_released: bool
    legal_settled: bool
    asset_available_on: OnlyTradingDay
    cash_trade_available_on: OnlyTradingDay
    cash_withdrawable_on: OnlyTradingDay
    legal_settlement_on: OnlyTradingDay
    version: int

    def __post_init__(self) -> None:
        if not self.instruction_id.strip() or not self.source_trade_id.strip() or self.version < 1:
            raise ValueError("Settlement execution state requires identity and version")
        if self.asset_quantity < 0 or self.cash_amount.amount < 0:
            raise ValueError("Settlement execution values cannot be negative")


@dataclass(frozen=True, slots=True)
class OnlySettlementRecordReplay(OnlyDomainModel):
    instruction_id: str
    account_id: OnlyAccountId
    instrument_id: OnlyInstrumentId
    source_order_id: OnlyOrderId
    source_trade_id: str
    processed_on: OnlyTradingDay
    available_quantity: Decimal
    trade_available_cash: OnlyMoney
    withdrawable_cash: OnlyMoney
    legal_settled: bool
    sequence: int

    def __post_init__(self) -> None:
        if not self.instruction_id.strip() or not self.source_trade_id.strip() or self.sequence < 1:
            raise ValueError("Settlement record requires complete identity and sequence")
        if min(self.available_quantity, self.trade_available_cash.amount, self.withdrawable_cash.amount) < 0:
            raise ValueError("Settlement record values cannot be negative")


@dataclass(frozen=True, slots=True)
class OnlySettlementExecutionProjection(OnlyDomainModel):
    identity: OnlyExecutionProjectionIdentity
    before: OnlySettlementExecutionState | None
    after: OnlySettlementExecutionState
    records: tuple[OnlySettlementRecordReplay, ...]

    def __post_init__(self) -> None:
        _require_component(self.identity, OnlyExecutionProjectionComponent.SETTLEMENT)
        _require_state_contract(self.identity, self.before, self.after)
        if self.identity.entity_key != self.after.instruction_id:
            raise ValueError("Settlement projection entity key mismatch")
        if self.before is not None and _settlement_scope(self.before) != _settlement_scope(self.after):
            raise ValueError("Settlement projection before/after scope mismatch")
        if any(_settlement_record_scope(item) != _settlement_scope(self.after) for item in self.records):
            raise ValueError("Settlement record scope mismatch")


@dataclass(frozen=True, slots=True)
class OnlyMarginExecutionState(OnlyDomainModel):
    instruction_id: str
    account_id: OnlyAccountId
    instrument_id: OnlyInstrumentId
    order_id: OnlyOrderId
    trade_id: str
    currency: str
    action: str
    amount: Decimal
    reserved: Decimal
    occupied: Decimal
    maintenance: Decimal
    updated_at: OnlyTimestamp
    version: int

    def __post_init__(self) -> None:
        if not all((self.instruction_id, self.trade_id, self.currency, self.action)) or self.version < 1:
            raise ValueError("Margin execution state requires complete identity and version")
        if min(self.amount, self.reserved, self.occupied, self.maintenance) < 0:
            raise ValueError("Margin execution state amounts cannot be negative")


@dataclass(frozen=True, slots=True)
class OnlyMarginExecutionProjection(OnlyDomainModel):
    identity: OnlyExecutionProjectionIdentity
    before: OnlyMarginExecutionState | None
    after: OnlyMarginExecutionState

    def __post_init__(self) -> None:
        _require_component(self.identity, OnlyExecutionProjectionComponent.MARGIN)
        _require_state_contract(self.identity, self.before, self.after)


@dataclass(frozen=True, slots=True)
class OnlyFeeInstructionReplay(OnlyDomainModel):
    instruction_id: str
    runtime_id: str
    cluster_id: str | None
    account_id: str
    order_id: str
    trade_id: str
    calculation_source: str
    idempotency_key: str
    created_at: OnlyTimestamp

    def __post_init__(self) -> None:
        if not all(
            (
                self.instruction_id,
                self.runtime_id,
                self.account_id,
                self.order_id,
                self.trade_id,
                self.calculation_source,
                self.idempotency_key,
            )
        ):
            raise ValueError("Fee instruction replay requires complete scope")


@dataclass(frozen=True, slots=True)
class OnlyFeeRecordReplay(OnlyDomainModel):
    record_id: str
    instruction_id: str
    account_id: str
    order_id: str
    trade_id: str
    amount: OnlyMoney
    component_type: str

    def __post_init__(self) -> None:
        if not all(
            (self.record_id, self.instruction_id, self.account_id, self.order_id, self.trade_id, self.component_type)
        ):
            raise ValueError("Fee record replay requires complete scope")
        if self.amount.amount < 0:
            raise ValueError("Fee record amount cannot be negative")


@dataclass(frozen=True, slots=True)
class OnlyFeeExecutionState(OnlyDomainModel):
    instruction: OnlyFeeInstructionReplay
    records: tuple[OnlyFeeRecordReplay, ...]
    authoritative_total: OnlyMoney
    fee_breakdown: OnlyFeeBreakdown
    version: int

    def __post_init__(self) -> None:
        if self.authoritative_total != self.fee_breakdown.total or self.version < 1:
            raise ValueError("Fee execution state total/version mismatch")
        if sum((item.amount.amount for item in self.records), Decimal(0)) != self.authoritative_total.amount:
            raise ValueError("Fee records must equal authoritative total")
        scope = (
            self.instruction.instruction_id,
            self.instruction.account_id,
            self.instruction.order_id,
            self.instruction.trade_id,
        )
        if any(
            item.amount.currency != self.authoritative_total.currency
            or (item.instruction_id, item.account_id, item.order_id, item.trade_id) != scope
            for item in self.records
        ):
            raise ValueError("Fee record currency/scope mismatch")


@dataclass(frozen=True, slots=True)
class OnlyFeeExecutionProjection(OnlyDomainModel):
    identity: OnlyExecutionProjectionIdentity
    before: OnlyFeeExecutionState | None
    after: OnlyFeeExecutionState

    def __post_init__(self) -> None:
        _require_component(self.identity, OnlyExecutionProjectionComponent.FEE)
        _require_state_contract(self.identity, self.before, self.after)
        if self.identity.entity_key != self.after.instruction.instruction_id:
            raise ValueError("Fee projection entity key mismatch")


@dataclass(frozen=True, slots=True)
class OnlyAccountExecutionProjection(OnlyDomainModel):
    identity: OnlyExecutionProjectionIdentity
    before: OnlyAccountExecutionState
    after: OnlyAccountExecutionState

    def __post_init__(self) -> None:
        _require_component(self.identity, OnlyExecutionProjectionComponent.ACCOUNT)
        _require_state_contract(self.identity, self.before, self.after)
        if (self.before.runtime_id, self.before.account_id) != (self.after.runtime_id, self.after.account_id):
            raise ValueError("Account projection scope mismatch")
        if self.before.base_currency != self.after.base_currency or self.identity.entity_key != str(
            self.after.account_id
        ):
            raise ValueError("Account projection currency/entity mismatch")
        _require_external_sequence(self.before.last_external_sequence, self.after.last_external_sequence)


@dataclass(frozen=True, slots=True)
class OnlyStrategyLedgerExecutionProjection(OnlyDomainModel):
    identity: OnlyExecutionProjectionIdentity
    before: OnlyStrategyLedgerExecutionState
    after: OnlyStrategyLedgerExecutionState

    def __post_init__(self) -> None:
        _require_component(self.identity, OnlyExecutionProjectionComponent.STRATEGY_LEDGER)
        _require_state_contract(self.identity, self.before, self.after)
        if self.before.ledger_id != self.after.ledger_id or self.before.key != self.after.key:
            raise ValueError("Strategy Ledger projection scope mismatch")
        if self.identity.entity_key != str(self.after.ledger_id):
            raise ValueError("Strategy Ledger projection entity mismatch")
        _require_last_trade_order(self.before.last_trade_order, self.after.last_trade_order)


@dataclass(frozen=True, slots=True)
class OnlyAccountCashReservationExecutionProjection(OnlyDomainModel):
    identity: OnlyExecutionProjectionIdentity
    before: OnlyAccountCashReservationExecutionState | None
    after: OnlyAccountCashReservationExecutionState

    def __post_init__(self) -> None:
        _require_component(self.identity, OnlyExecutionProjectionComponent.ACCOUNT_CASH_RESERVATION)
        _require_state_contract(self.identity, self.before, self.after)
        _require_reservation_scope(self.identity.entity_key, self.before, self.after)
        if self.before is not None:
            _require_account_cash_reservation_transition(self.before, self.after)


@dataclass(frozen=True, slots=True)
class OnlyStrategyCashReservationExecutionProjection(OnlyDomainModel):
    identity: OnlyExecutionProjectionIdentity
    before: OnlyStrategyCashReservationExecutionState | None
    after: OnlyStrategyCashReservationExecutionState

    def __post_init__(self) -> None:
        _require_component(self.identity, OnlyExecutionProjectionComponent.STRATEGY_CASH_RESERVATION)
        _require_state_contract(self.identity, self.before, self.after)
        _require_reservation_scope(self.identity.entity_key, self.before, self.after)
        if self.before is not None:
            _require_strategy_cash_reservation_transition(self.before, self.after)


@dataclass(frozen=True, slots=True)
class OnlyPositionReservationExecutionProjection(OnlyDomainModel):
    identity: OnlyExecutionProjectionIdentity
    before: OnlyPositionReservationExecutionState | None
    after: OnlyPositionReservationExecutionState

    def __post_init__(self) -> None:
        _require_component(self.identity, OnlyExecutionProjectionComponent.POSITION_RESERVATION)
        _require_state_contract(self.identity, self.before, self.after)
        _require_reservation_scope(self.identity.entity_key, self.before, self.after)
        if self.before is not None:
            _require_position_reservation_transition(self.before, self.after)


@dataclass(frozen=True, slots=True)
class OnlyMarginReservationExecutionProjection(OnlyDomainModel):
    identity: OnlyExecutionProjectionIdentity
    before: OnlyMarginReservationExecutionState | None
    after: OnlyMarginReservationExecutionState

    def __post_init__(self) -> None:
        _require_component(self.identity, OnlyExecutionProjectionComponent.MARGIN_RESERVATION)
        _require_state_contract(self.identity, self.before, self.after)
        _require_reservation_scope(self.identity.entity_key, self.before, self.after)
        if self.before is not None:
            _require_margin_reservation_transition(self.before, self.after)


@dataclass(frozen=True, slots=True)
class OnlyRiskReservationExecutionProjection(OnlyDomainModel):
    identity: OnlyExecutionProjectionIdentity
    before: OnlyRiskReservationExecutionState | None
    after: OnlyRiskReservationExecutionState

    def __post_init__(self) -> None:
        _require_component(self.identity, OnlyExecutionProjectionComponent.RISK_RESERVATION)
        _require_state_contract(self.identity, self.before, self.after)
        _require_reservation_scope(self.identity.entity_key, self.before, self.after)
        if self.before is not None:
            _require_risk_reservation_transition(self.before, self.after)


@dataclass(frozen=True, slots=True)
class OnlyRiskExecutionState(OnlyDomainModel):
    cluster_id: OnlyClusterId
    account_id: OnlyAccountId
    instrument_id: OnlyInstrumentId
    order_id: OnlyOrderId
    quantity_exposure: OnlyQuantity
    notional_exposure: OnlyMoney
    level: OnlyRiskLevel
    updated_at: OnlyTimestamp
    version: int

    def __post_init__(self) -> None:
        if self.quantity_exposure.value < 0 or self.notional_exposure.amount < 0 or self.version < 1:
            raise ValueError("Risk execution state exposure/version is invalid")


@dataclass(frozen=True, slots=True)
class OnlyRiskExecutionProjection(OnlyDomainModel):
    identity: OnlyExecutionProjectionIdentity
    before: OnlyRiskExecutionState | None
    after: OnlyRiskExecutionState

    def __post_init__(self) -> None:
        _require_component(self.identity, OnlyExecutionProjectionComponent.RISK)
        _require_state_contract(self.identity, self.before, self.after)


@dataclass(frozen=True, slots=True)
class OnlyValuationExecutionState(OnlyDomainModel):
    account_id: OnlyAccountId
    valuation_time: OnlyTimestamp
    cash: OnlyMoney
    position_market_value: OnlyMoney
    unrealized_pnl: OnlyMoney
    equity: OnlyMoney
    version: int

    def __post_init__(self) -> None:
        values = (self.cash, self.position_market_value, self.unrealized_pnl, self.equity)
        if len({item.currency for item in values}) != 1 or self.version < 1:
            raise ValueError("Valuation execution state currency/version is invalid")
        if self.equity.amount != self.cash.amount + self.position_market_value.amount:
            raise ValueError("Valuation execution equity formula is invalid")


@dataclass(frozen=True, slots=True)
class OnlyValuationExecutionProjection(OnlyDomainModel):
    identity: OnlyExecutionProjectionIdentity
    before: OnlyValuationExecutionState | None
    after: OnlyValuationExecutionState

    def __post_init__(self) -> None:
        _require_component(self.identity, OnlyExecutionProjectionComponent.VALUATION)
        _require_state_contract(self.identity, self.before, self.after)


type OnlyExecutionProjection = (
    OnlyOrderExecutionProjection
    | OnlyPositionExecutionProjection
    | OnlyAllocationExecutionProjection
    | OnlySettlementExecutionProjection
    | OnlyMarginExecutionProjection
    | OnlyFeeExecutionProjection
    | OnlyAccountExecutionProjection
    | OnlyStrategyLedgerExecutionProjection
    | OnlyAccountCashReservationExecutionProjection
    | OnlyStrategyCashReservationExecutionProjection
    | OnlyPositionReservationExecutionProjection
    | OnlyMarginReservationExecutionProjection
    | OnlyRiskReservationExecutionProjection
    | OnlyRiskExecutionProjection
    | OnlyValuationExecutionProjection
)
type OnlyExecutionReservationProjection = (
    OnlyAccountCashReservationExecutionProjection
    | OnlyStrategyCashReservationExecutionProjection
    | OnlyPositionReservationExecutionProjection
    | OnlyMarginReservationExecutionProjection
    | OnlyRiskReservationExecutionProjection
)


def _require_component(identity: OnlyExecutionProjectionIdentity, expected: OnlyExecutionProjectionComponent) -> None:
    if identity.component is not expected:
        raise ValueError(f"{expected.value} projection requires matching component identity")


def _require_digest(value: str, label: str) -> None:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError(f"{label} must be a lowercase SHA-256 digest")


def _require_state_contract(
    identity: OnlyExecutionProjectionIdentity,
    before: OnlyDomainModel | None,
    after: OnlyDomainModel,
) -> None:
    before_version = 0 if before is None else cast(_OnlyVersionedState, before).version
    after_version = cast(_OnlyVersionedState, after).version
    if before_version != identity.expected_version or after_version != identity.result_version:
        raise ValueError("projection state versions disagree with identity")
    if only_execution_state_hash(before) != identity.expected_state_hash:
        raise ValueError("projection before state hash mismatch")
    if only_execution_state_hash(after) != identity.result_state_hash:
        raise ValueError("projection after state hash mismatch")


def _order_scope(value: OnlyOrderExecutionState) -> tuple[object, ...]:
    return value.order_id, value.runtime_id, value.cluster_id, value.account_id, value.instrument_id


def _settlement_scope(value: OnlySettlementExecutionState) -> tuple[object, ...]:
    return value.instruction_id, value.account_id, value.instrument_id, value.source_order_id, value.source_trade_id


def _settlement_record_scope(value: OnlySettlementRecordReplay) -> tuple[object, ...]:
    return value.instruction_id, value.account_id, value.instrument_id, value.source_order_id, value.source_trade_id


def _require_external_sequence(before: int | None, after: int | None) -> None:
    if before is not None and after is not None and after < before:
        raise ValueError("external sequence cannot regress")


def _require_last_trade_order(before: tuple[int, int, str] | None, after: tuple[int, int, str] | None) -> None:
    if before is not None and after is not None and after < before:
        raise ValueError("last Trade order cannot regress")


def _require_reservation_scope(
    entity_key: str,
    before: OnlyDomainModel | None,
    after: OnlyDomainModel,
) -> None:
    after_reservation = cast(_OnlyReservationState, after)
    if entity_key != str(after_reservation.reservation_id):
        raise ValueError("Reservation projection entity key mismatch")
    if before is not None and cast(_OnlyReservationState, before).reservation_id != after_reservation.reservation_id:
        raise ValueError("Reservation projection before/after scope mismatch")


def _require_account_cash_reservation_transition(
    before: OnlyAccountCashReservationExecutionState,
    after: OnlyAccountCashReservationExecutionState,
) -> None:
    if (
        (before.runtime_id, before.account_id, before.order_id, before.reserved_amount)
        != (after.runtime_id, after.account_id, after.order_id, after.reserved_amount)
        or after.consumed_amount.amount < before.consumed_amount.amount
        or after.remaining_amount.amount > before.remaining_amount.amount
        or after.version != before.version + 1
    ):
        raise ValueError("Account cash Reservation authority changed")
    _require_reservation_lifecycle(before.state.value, after.state.value, before.updated_at, after.updated_at)


def _require_strategy_cash_reservation_transition(
    before: OnlyStrategyCashReservationExecutionState,
    after: OnlyStrategyCashReservationExecutionState,
) -> None:
    if (
        (before.key, before.order_id, before.estimated_notional, before.estimated_fee, before.reserved_amount)
        != (after.key, after.order_id, after.estimated_notional, after.estimated_fee, after.reserved_amount)
        or after.consumed_amount.amount < before.consumed_amount.amount
        or after.remaining_amount.amount > before.remaining_amount.amount
        or after.version != before.version + 1
    ):
        raise ValueError("Strategy cash Reservation authority changed")
    _require_reservation_lifecycle(before.state.value, after.state.value, before.updated_at, after.updated_at)


def _require_position_reservation_transition(
    before: OnlyPositionReservationExecutionState,
    after: OnlyPositionReservationExecutionState,
) -> None:
    if (
        (
            before.runtime_id,
            before.account_id,
            before.cluster_id,
            before.instrument_id,
            before.position_side,
            before.position_mode,
            before.order_id,
            before.quantity,
            before.settlement_bucket,
        )
        != (
            after.runtime_id,
            after.account_id,
            after.cluster_id,
            after.instrument_id,
            after.position_side,
            after.position_mode,
            after.order_id,
            after.quantity,
            after.settlement_bucket,
        )
        or after.remaining_quantity.value > before.remaining_quantity.value
        or after.version != before.version + 1
    ):
        raise ValueError("Position Reservation authority changed")
    _require_reservation_lifecycle(before.state.value, after.state.value, before.updated_at, after.updated_at)


def _require_margin_reservation_transition(
    before: OnlyMarginReservationExecutionState,
    after: OnlyMarginReservationExecutionState,
) -> None:
    if (
        (
            before.runtime_id,
            before.account_id,
            before.instrument_id,
            before.order_id,
            before.currency,
            before.original_reserved_amount,
        )
        != (
            after.runtime_id,
            after.account_id,
            after.instrument_id,
            after.order_id,
            after.currency,
            after.original_reserved_amount,
        )
        or after.remaining_reserved_amount.amount > before.remaining_reserved_amount.amount
        or after.released_amount.amount < before.released_amount.amount
        or after.version != before.version + 1
    ):
        raise ValueError("Margin Reservation authority changed")
    _require_reservation_lifecycle(before.state.value, after.state.value, before.updated_at, after.updated_at)


def _require_risk_reservation_transition(
    before: OnlyRiskReservationExecutionState,
    after: OnlyRiskReservationExecutionState,
) -> None:
    if (
        (
            before.reservation_type,
            before.runtime_id,
            before.cluster_id,
            before.account_id,
            before.instrument_id,
            before.order_id,
            before.reserved_quantity,
            before.reserved_notional,
        )
        != (
            after.reservation_type,
            after.runtime_id,
            after.cluster_id,
            after.account_id,
            after.instrument_id,
            after.order_id,
            after.reserved_quantity,
            after.reserved_notional,
        )
        or after.consumed_quantity.value < before.consumed_quantity.value
        or after.remaining_quantity.value > before.remaining_quantity.value
        or after.version != before.version + 1
    ):
        raise ValueError("Risk Reservation authority changed")
    _require_reservation_lifecycle(before.state.value, after.state.value, before.updated_at, after.updated_at)


def _require_reservation_lifecycle(
    before_state: str,
    after_state: str,
    before_updated_at: OnlyTimestamp,
    after_updated_at: OnlyTimestamp,
) -> None:
    terminal = {"CONSUMED", "RELEASED", "FAILED"}
    if after_updated_at < before_updated_at or (before_state in terminal and after_state != before_state):
        raise ValueError("Reservation lifecycle regressed")


class _OnlyVersionedState(Protocol):
    version: int


class _OnlyReservationState(Protocol):
    reservation_id: object


class OnlyProjectionApplyStatus(StrEnum):
    APPLIED = "APPLIED"
    IDEMPOTENT = "IDEMPOTENT"
    VERSION_CONFLICT = "VERSION_CONFLICT"
    STATE_CONFLICT = "STATE_CONFLICT"
    PAYLOAD_CONFLICT = "PAYLOAD_CONFLICT"
    INVALID_COMPONENT = "INVALID_COMPONENT"


@dataclass(frozen=True, slots=True)
class OnlyProjectionApplyResult:
    status: OnlyProjectionApplyStatus
    component: OnlyExecutionProjectionComponent
    entity_key: str
    execution_sequence: int
    before_version: int
    after_version: int
    before_state_hash: str
    after_state_hash: str
    payload_hash: str


class OnlyExecutionProjectionTarget(Protocol):
    @property
    def component(self) -> OnlyExecutionProjectionComponent: ...

    def apply_execution_projection(
        self, execution_sequence: int, projection: OnlyExecutionProjection
    ) -> OnlyProjectionApplyResult: ...


@dataclass(frozen=True, slots=True)
class _OnlyProjectionEntityState:
    version: int
    state_hash: str
    applied: tuple[tuple[int, str], ...]


class OnlyInMemoryExecutionProjectionState:
    """Reference target implementing version, state-hash and idempotency checks."""

    def __init__(self, component: OnlyExecutionProjectionComponent) -> None:
        self._component = component
        self._entities: dict[str, _OnlyProjectionEntityState] = {}

    @property
    def component(self) -> OnlyExecutionProjectionComponent:
        return self._component

    def seed(self, entity_key: str, version: int, state_hash: str) -> None:
        _require_digest(state_hash, "seed state_hash")
        self._entities[entity_key] = _OnlyProjectionEntityState(version, state_hash, ())

    def apply_execution_projection(
        self, execution_sequence: int, projection: OnlyExecutionProjection
    ) -> OnlyProjectionApplyResult:
        identity = projection.identity
        state = self._entities.get(
            identity.entity_key,
            _OnlyProjectionEntityState(0, only_execution_state_hash(None), ()),
        )
        if identity.component is not self._component:
            return self._result(OnlyProjectionApplyStatus.INVALID_COMPONENT, execution_sequence, identity, state)
        applied = dict(state.applied)
        prior_hash = applied.get(execution_sequence)
        if prior_hash is not None:
            status = (
                OnlyProjectionApplyStatus.IDEMPOTENT
                if prior_hash == identity.payload_hash
                else OnlyProjectionApplyStatus.PAYLOAD_CONFLICT
            )
            return self._result(status, execution_sequence, identity, state)
        if state.version != identity.expected_version:
            return self._result(OnlyProjectionApplyStatus.VERSION_CONFLICT, execution_sequence, identity, state)
        if state.state_hash != identity.expected_state_hash:
            return self._result(OnlyProjectionApplyStatus.STATE_CONFLICT, execution_sequence, identity, state)
        applied[execution_sequence] = identity.payload_hash
        updated = _OnlyProjectionEntityState(
            identity.result_version,
            identity.result_state_hash,
            tuple(sorted(applied.items())),
        )
        self._entities[identity.entity_key] = updated
        return self._result(OnlyProjectionApplyStatus.APPLIED, execution_sequence, identity, state, updated)

    @staticmethod
    def _result(
        status: OnlyProjectionApplyStatus,
        execution_sequence: int,
        identity: OnlyExecutionProjectionIdentity,
        before: _OnlyProjectionEntityState,
        after: _OnlyProjectionEntityState | None = None,
    ) -> OnlyProjectionApplyResult:
        result = before if after is None else after
        return OnlyProjectionApplyResult(
            status,
            identity.component,
            identity.entity_key,
            execution_sequence,
            before.version,
            result.version,
            before.state_hash,
            result.state_hash,
            identity.payload_hash,
        )


__all__ = [name for name in globals() if name.startswith("Only")]
