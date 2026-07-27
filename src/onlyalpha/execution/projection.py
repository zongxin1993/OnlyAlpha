"""Strongly typed, replayable execution projections and apply contracts."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import IntEnum, StrEnum
from typing import Protocol

from onlyalpha.domain.base import OnlyDomainModel
from onlyalpha.domain.enums import OnlyOrderStatus
from onlyalpha.domain.execution import OnlyOrderFill
from onlyalpha.domain.identifiers import OnlyAccountId, OnlyClusterId, OnlyInstrumentId, OnlyOrderId
from onlyalpha.domain.time import OnlyTimestamp, OnlyTradingDay
from onlyalpha.domain.value import OnlyCurrency, OnlyMoney, OnlyPrice, OnlyQuantity
from onlyalpha.fee.models import OnlyFeeBreakdown
from onlyalpha.risk.enums import OnlyRiskLevel, OnlyRiskReservationState


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


class OnlyReservationStatus(StrEnum):
    ACTIVE = "ACTIVE"
    PARTIALLY_CONSUMED = "PARTIALLY_CONSUMED"
    CONSUMED = "CONSUMED"
    RELEASED = "RELEASED"


@dataclass(frozen=True, slots=True)
class OnlyExecutionProjectionIdentity(OnlyDomainModel):
    component: OnlyExecutionProjectionComponent
    entity_key: str
    expected_version: int
    result_version: int
    projection_sequence: int
    payload_hash: str

    def __post_init__(self) -> None:
        if not self.entity_key.strip() or self.expected_version < 0:
            raise ValueError("projection identity requires an entity and non-negative expected version")
        if self.result_version <= self.expected_version or self.projection_sequence < 1:
            raise ValueError("projection result version and sequence must advance")
        _require_digest(self.payload_hash, "projection payload_hash")


@dataclass(frozen=True, slots=True)
class OnlyOrderExecutionProjection(OnlyDomainModel):
    identity: OnlyExecutionProjectionIdentity
    order_id: OnlyOrderId
    before_status: OnlyOrderStatus
    after_status: OnlyOrderStatus
    before_filled_quantity: OnlyQuantity
    after_filled_quantity: OnlyQuantity
    before_average_fill_price: OnlyPrice | None
    after_average_fill_price: OnlyPrice | None
    fill: OnlyOrderFill
    external_update_id: str

    def __post_init__(self) -> None:
        _require_component(self.identity, OnlyExecutionProjectionComponent.ORDER)
        if self.fill.order_id != self.order_id or not self.external_update_id.strip():
            raise ValueError("order projection fill/update identity mismatch")
        if self.after_filled_quantity.value < self.before_filled_quantity.value:
            raise ValueError("order projection cannot reduce cumulative filled quantity")
        if self.after_filled_quantity.value > 0 and self.after_average_fill_price is None:
            raise ValueError("filled order projection requires resulting average fill price")


@dataclass(frozen=True, slots=True)
class OnlyPositionExecutionProjection(OnlyDomainModel):
    identity: OnlyExecutionProjectionIdentity
    position_key: str
    before_quantity: OnlyQuantity
    after_quantity: OnlyQuantity
    before_available_quantity: OnlyQuantity
    after_available_quantity: OnlyQuantity
    before_average_price: OnlyPrice | None
    after_average_price: OnlyPrice | None
    realized_pnl_delta: OnlyMoney
    resulting_realized_pnl: OnlyMoney

    def __post_init__(self) -> None:
        _require_component(self.identity, OnlyExecutionProjectionComponent.POSITION)
        _require_key(self.position_key, "position")
        _require_one_currency((self.realized_pnl_delta, self.resulting_realized_pnl))


@dataclass(frozen=True, slots=True)
class OnlyAllocationExecutionProjection(OnlyDomainModel):
    identity: OnlyExecutionProjectionIdentity
    allocation_key: str
    before_quantity: OnlyQuantity
    after_quantity: OnlyQuantity
    before_cost: OnlyMoney
    after_cost: OnlyMoney
    realized_pnl_delta: OnlyMoney

    def __post_init__(self) -> None:
        _require_component(self.identity, OnlyExecutionProjectionComponent.ALLOCATION)
        _require_key(self.allocation_key, "allocation")
        _require_one_currency((self.before_cost, self.after_cost, self.realized_pnl_delta))


@dataclass(frozen=True, slots=True)
class OnlySettlementProjectionState(OnlyDomainModel):
    instruction_id: str
    account_id: str
    instrument_id: str
    source_order_id: str
    source_trade_id: str
    asset_quantity: Decimal
    cash_amount: Decimal
    asset_released: bool
    trade_cash_released: bool
    withdrawable_cash_released: bool
    legal_settled: bool
    asset_available_on: OnlyTradingDay
    cash_trade_available_on: OnlyTradingDay
    cash_withdrawable_on: OnlyTradingDay
    legal_settlement_on: OnlyTradingDay

    def __post_init__(self) -> None:
        if not all(
            (self.instruction_id, self.account_id, self.instrument_id, self.source_order_id, self.source_trade_id)
        ):
            raise ValueError("settlement projection state requires complete scope")
        if self.asset_quantity < 0 or self.cash_amount < 0:
            raise ValueError("settlement projection quantities cannot be negative")


@dataclass(frozen=True, slots=True)
class OnlySettlementRecordReplay(OnlyDomainModel):
    instruction_id: str
    account_id: str
    instrument_id: str
    source_order_id: str
    source_trade_id: str
    processed_on: OnlyTradingDay
    available_quantity: Decimal
    trade_available_cash: Decimal
    withdrawable_cash: Decimal
    legal_settled: bool
    sequence: int

    def __post_init__(self) -> None:
        if not all(
            (self.instruction_id, self.account_id, self.instrument_id, self.source_order_id, self.source_trade_id)
        ):
            raise ValueError("settlement record requires complete scope")
        if min(self.available_quantity, self.trade_available_cash, self.withdrawable_cash) < 0 or self.sequence < 1:
            raise ValueError("settlement record values must be non-negative and sequenced")


@dataclass(frozen=True, slots=True)
class OnlySettlementExecutionProjection(OnlyDomainModel):
    identity: OnlyExecutionProjectionIdentity
    before: OnlySettlementProjectionState | None
    after: OnlySettlementProjectionState
    records: tuple[OnlySettlementRecordReplay, ...]

    def __post_init__(self) -> None:
        _require_component(self.identity, OnlyExecutionProjectionComponent.SETTLEMENT)
        if self.before is not None and _settlement_scope(self.before) != _settlement_scope(self.after):
            raise ValueError("settlement before/after scope mismatch")
        scope = _settlement_scope(self.after)
        if any(_settlement_record_scope(item) != scope for item in self.records):
            raise ValueError("settlement record scope mismatch")
        if self.before is not None and _settlement_flags(self.before) & ~_settlement_flags(self.after):
            raise ValueError("settlement state cannot regress")


@dataclass(frozen=True, slots=True)
class OnlyMarginExecutionProjection(OnlyDomainModel):
    identity: OnlyExecutionProjectionIdentity
    instruction: str
    reserved_before: OnlyMoney
    reserved_after: OnlyMoney
    occupied_before: OnlyMoney
    occupied_after: OnlyMoney
    maintenance_before: OnlyMoney
    maintenance_after: OnlyMoney

    def __post_init__(self) -> None:
        _require_component(self.identity, OnlyExecutionProjectionComponent.MARGIN)
        _require_key(self.instruction, "margin instruction")
        _require_one_currency(
            (
                self.reserved_before,
                self.reserved_after,
                self.occupied_before,
                self.occupied_after,
                self.maintenance_before,
                self.maintenance_after,
            )
        )


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
            raise ValueError("fee instruction replay requires complete scope")


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
            raise ValueError("fee record replay requires complete scope")
        if self.amount.amount < 0:
            raise ValueError("fee record amount cannot be negative")


@dataclass(frozen=True, slots=True)
class OnlyFeeExecutionProjection(OnlyDomainModel):
    identity: OnlyExecutionProjectionIdentity
    instruction: OnlyFeeInstructionReplay
    records: tuple[OnlyFeeRecordReplay, ...]
    authoritative_total: OnlyMoney
    fee_breakdown: OnlyFeeBreakdown

    def __post_init__(self) -> None:
        _require_component(self.identity, OnlyExecutionProjectionComponent.FEE)
        if self.authoritative_total != self.fee_breakdown.total:
            raise ValueError("fee projection authoritative total must equal breakdown")
        if any(item.amount.currency != self.authoritative_total.currency for item in self.records):
            raise ValueError("fee projection currency mismatch")
        if sum((item.amount.amount for item in self.records), Decimal(0)) != self.authoritative_total.amount:
            raise ValueError("fee records must equal authoritative total")
        scope = (
            self.instruction.instruction_id,
            self.instruction.account_id,
            self.instruction.order_id,
            self.instruction.trade_id,
        )
        if any((item.instruction_id, item.account_id, item.order_id, item.trade_id) != scope for item in self.records):
            raise ValueError("fee instruction and record scopes disagree")


@dataclass(frozen=True, slots=True)
class OnlyAccountExecutionProjection(OnlyDomainModel):
    identity: OnlyExecutionProjectionIdentity
    account_id: OnlyAccountId
    cash_before: OnlyMoney
    cash_after: OnlyMoney
    frozen_cash_before: OnlyMoney
    frozen_cash_after: OnlyMoney
    realized_pnl_before: OnlyMoney
    realized_pnl_after: OnlyMoney
    unrealized_pnl_before: OnlyMoney
    unrealized_pnl_after: OnlyMoney
    fees_before: OnlyMoney
    fees_after: OnlyMoney
    position_market_value_before: OnlyMoney
    position_market_value_after: OnlyMoney
    equity_before: OnlyMoney
    equity_after: OnlyMoney

    def __post_init__(self) -> None:
        _require_component(self.identity, OnlyExecutionProjectionComponent.ACCOUNT)
        _require_one_currency(
            tuple(
                getattr(self, name)
                for name in (
                    "cash_before",
                    "cash_after",
                    "frozen_cash_before",
                    "frozen_cash_after",
                    "realized_pnl_before",
                    "realized_pnl_after",
                    "unrealized_pnl_before",
                    "unrealized_pnl_after",
                    "fees_before",
                    "fees_after",
                    "position_market_value_before",
                    "position_market_value_after",
                    "equity_before",
                    "equity_after",
                )
            )
        )


@dataclass(frozen=True, slots=True)
class OnlyStrategyLedgerExecutionProjection(OnlyDomainModel):
    identity: OnlyExecutionProjectionIdentity
    ledger_key: str
    cash_before: OnlyMoney
    cash_after: OnlyMoney
    realized_pnl_before: OnlyMoney
    realized_pnl_after: OnlyMoney
    unrealized_pnl_before: OnlyMoney
    unrealized_pnl_after: OnlyMoney
    fees_before: OnlyMoney
    fees_after: OnlyMoney
    equity_before: OnlyMoney
    equity_after: OnlyMoney
    trade_count_before: int
    trade_count_after: int

    def __post_init__(self) -> None:
        _require_component(self.identity, OnlyExecutionProjectionComponent.STRATEGY_LEDGER)
        _require_key(self.ledger_key, "strategy ledger")
        _require_one_currency(
            (
                self.cash_before,
                self.cash_after,
                self.realized_pnl_before,
                self.realized_pnl_after,
                self.unrealized_pnl_before,
                self.unrealized_pnl_after,
                self.fees_before,
                self.fees_after,
                self.equity_before,
                self.equity_after,
            )
        )
        if self.trade_count_before < 0 or self.trade_count_after < self.trade_count_before:
            raise ValueError("strategy ledger trade count cannot decrease")


@dataclass(frozen=True, slots=True)
class OnlyCashReservationExecutionProjection(OnlyDomainModel):
    identity: OnlyExecutionProjectionIdentity
    reservation_id: str
    owner_scope: str
    currency: OnlyCurrency
    before: OnlyMoney
    consumed_delta: OnlyMoney
    released_delta: OnlyMoney
    after: OnlyMoney
    before_status: OnlyReservationStatus
    after_status: OnlyReservationStatus

    def __post_init__(self) -> None:
        if self.identity.component not in {
            OnlyExecutionProjectionComponent.ACCOUNT_CASH_RESERVATION,
            OnlyExecutionProjectionComponent.STRATEGY_CASH_RESERVATION,
        }:
            raise ValueError("cash reservation projection requires a cash component")
        _require_key(self.reservation_id, "cash reservation")
        _require_key(self.owner_scope, "cash reservation owner")
        _require_one_currency((self.before, self.consumed_delta, self.released_delta, self.after))
        if (
            self.before.currency != self.currency
            or min(self.before.amount, self.consumed_delta.amount, self.released_delta.amount, self.after.amount) < 0
        ):
            raise ValueError("cash reservation currency/amount mismatch")
        if self.after.amount != self.before.amount - self.consumed_delta.amount - self.released_delta.amount:
            raise ValueError("cash reservation balance is inconsistent")


@dataclass(frozen=True, slots=True)
class OnlyPositionReservationExecutionProjection(OnlyDomainModel):
    identity: OnlyExecutionProjectionIdentity
    reservation_id: str
    order_id: OnlyOrderId
    instrument_id: OnlyInstrumentId
    before: OnlyQuantity
    consumed_delta: OnlyQuantity
    released_delta: OnlyQuantity
    after: OnlyQuantity
    before_status: OnlyReservationStatus
    after_status: OnlyReservationStatus

    def __post_init__(self) -> None:
        _require_component(self.identity, OnlyExecutionProjectionComponent.POSITION_RESERVATION)
        _require_key(self.reservation_id, "position reservation")
        if min(self.before.value, self.consumed_delta.value, self.released_delta.value, self.after.value) < 0:
            raise ValueError("position reservation quantities cannot be negative")
        if self.after.value != self.before.value - self.consumed_delta.value - self.released_delta.value:
            raise ValueError("position reservation balance is inconsistent")


@dataclass(frozen=True, slots=True)
class OnlyMarginReservationExecutionProjection(OnlyDomainModel):
    identity: OnlyExecutionProjectionIdentity
    reservation_id: str
    account_id: OnlyAccountId
    instrument_id: OnlyInstrumentId
    currency: OnlyCurrency
    reserved_before: OnlyMoney
    reserved_after: OnlyMoney
    occupied_before: OnlyMoney
    occupied_after: OnlyMoney
    released_delta: OnlyMoney
    maintenance_before: OnlyMoney
    maintenance_after: OnlyMoney

    def __post_init__(self) -> None:
        _require_component(self.identity, OnlyExecutionProjectionComponent.MARGIN_RESERVATION)
        _require_key(self.reservation_id, "margin reservation")
        values = (
            self.reserved_before,
            self.reserved_after,
            self.occupied_before,
            self.occupied_after,
            self.released_delta,
            self.maintenance_before,
            self.maintenance_after,
        )
        _require_one_currency(values)
        if self.reserved_before.currency != self.currency or min(item.amount for item in values) < 0:
            raise ValueError("margin reservation currency/amount mismatch")
        if (
            self.reserved_after.amount + self.occupied_after.amount + self.released_delta.amount
            > self.reserved_before.amount + self.occupied_before.amount
        ):
            raise ValueError("margin reservation state creates authority")


@dataclass(frozen=True, slots=True)
class OnlyRiskReservationExecutionProjection(OnlyDomainModel):
    identity: OnlyExecutionProjectionIdentity
    reservation_id: str
    cluster_id: OnlyClusterId
    account_id: OnlyAccountId
    instrument_id: OnlyInstrumentId
    order_id: OnlyOrderId
    quantity_before: OnlyQuantity
    quantity_after: OnlyQuantity
    notional_before: OnlyMoney
    notional_after: OnlyMoney
    consumed_quantity_delta: OnlyQuantity
    consumed_notional_delta: OnlyMoney
    before_status: OnlyRiskReservationState
    after_status: OnlyRiskReservationState

    def __post_init__(self) -> None:
        _require_component(self.identity, OnlyExecutionProjectionComponent.RISK_RESERVATION)
        _require_key(self.reservation_id, "risk reservation")
        _require_one_currency((self.notional_before, self.notional_after, self.consumed_notional_delta))
        if (
            min(
                self.quantity_before.value,
                self.quantity_after.value,
                self.consumed_quantity_delta.value,
                self.notional_before.amount,
                self.notional_after.amount,
                self.consumed_notional_delta.amount,
            )
            < 0
        ):
            raise ValueError("risk reservation exposure cannot be negative")
        if (
            self.quantity_after.value != self.quantity_before.value - self.consumed_quantity_delta.value
            or self.notional_after.amount != self.notional_before.amount - self.consumed_notional_delta.amount
        ):
            raise ValueError("risk reservation remaining exposure is inconsistent")


@dataclass(frozen=True, slots=True)
class OnlyRiskExecutionProjection(OnlyDomainModel):
    identity: OnlyExecutionProjectionIdentity
    cluster_id: OnlyClusterId
    account_id: OnlyAccountId
    instrument_id: OnlyInstrumentId
    order_id: OnlyOrderId
    quantity_exposure_before: OnlyQuantity
    quantity_exposure_after: OnlyQuantity
    notional_exposure_before: OnlyMoney
    notional_exposure_after: OnlyMoney
    level_before: OnlyRiskLevel
    level_after: OnlyRiskLevel

    def __post_init__(self) -> None:
        _require_component(self.identity, OnlyExecutionProjectionComponent.RISK)
        _require_one_currency((self.notional_exposure_before, self.notional_exposure_after))
        if (
            min(
                self.quantity_exposure_before.value,
                self.quantity_exposure_after.value,
                self.notional_exposure_before.amount,
                self.notional_exposure_after.amount,
            )
            < 0
        ):
            raise ValueError("risk exposure cannot be negative")


@dataclass(frozen=True, slots=True)
class OnlyValuationExecutionProjection(OnlyDomainModel):
    identity: OnlyExecutionProjectionIdentity
    account_id: OnlyAccountId
    valued_at: OnlyTimestamp
    position_market_value_before: OnlyMoney
    position_market_value_after: OnlyMoney
    unrealized_pnl_before: OnlyMoney
    unrealized_pnl_after: OnlyMoney

    def __post_init__(self) -> None:
        _require_component(self.identity, OnlyExecutionProjectionComponent.VALUATION)
        _require_one_currency(
            (
                self.position_market_value_before,
                self.position_market_value_after,
                self.unrealized_pnl_before,
                self.unrealized_pnl_after,
            )
        )


type OnlyExecutionProjection = (
    OnlyOrderExecutionProjection
    | OnlyPositionExecutionProjection
    | OnlyAllocationExecutionProjection
    | OnlySettlementExecutionProjection
    | OnlyMarginExecutionProjection
    | OnlyFeeExecutionProjection
    | OnlyAccountExecutionProjection
    | OnlyStrategyLedgerExecutionProjection
    | OnlyCashReservationExecutionProjection
    | OnlyPositionReservationExecutionProjection
    | OnlyMarginReservationExecutionProjection
    | OnlyRiskReservationExecutionProjection
    | OnlyRiskExecutionProjection
    | OnlyValuationExecutionProjection
)
type OnlyExecutionReservationProjection = (
    OnlyCashReservationExecutionProjection
    | OnlyPositionReservationExecutionProjection
    | OnlyMarginReservationExecutionProjection
    | OnlyRiskReservationExecutionProjection
)


def _require_component(identity: OnlyExecutionProjectionIdentity, expected: OnlyExecutionProjectionComponent) -> None:
    if identity.component is not expected:
        raise ValueError(f"{expected.value} projection requires matching component identity")


def _require_key(value: str, label: str) -> None:
    if not value.strip():
        raise ValueError(f"{label} projection key is required")


def _require_digest(value: str, label: str) -> None:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError(f"{label} must be a lowercase SHA-256 digest")


def _require_one_currency(values: tuple[OnlyMoney, ...]) -> None:
    if len({item.currency for item in values}) != 1:
        raise ValueError("execution projection monetary values require one currency")


def _settlement_scope(value: OnlySettlementProjectionState) -> tuple[str, str, str, str, str]:
    return value.instruction_id, value.account_id, value.instrument_id, value.source_order_id, value.source_trade_id


def _settlement_record_scope(value: OnlySettlementRecordReplay) -> tuple[str, str, str, str, str]:
    return value.instruction_id, value.account_id, value.instrument_id, value.source_order_id, value.source_trade_id


def _settlement_flags(value: OnlySettlementProjectionState) -> int:
    return sum(
        1 << index
        for index, flag in enumerate(
            (value.asset_released, value.trade_cash_released, value.withdrawable_cash_released, value.legal_settled)
        )
        if flag
    )


class OnlyProjectionApplyStatus(StrEnum):
    APPLIED = "APPLIED"
    IDEMPOTENT = "IDEMPOTENT"
    VERSION_CONFLICT = "VERSION_CONFLICT"
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
    applied: tuple[tuple[int, str], ...]


class OnlyInMemoryExecutionProjectionState:
    """Reference implementation of the projection idempotency contract."""

    def __init__(self, component: OnlyExecutionProjectionComponent) -> None:
        self._component = component
        self._entities: dict[str, _OnlyProjectionEntityState] = {}

    @property
    def component(self) -> OnlyExecutionProjectionComponent:
        return self._component

    def apply_execution_projection(
        self, execution_sequence: int, projection: OnlyExecutionProjection
    ) -> OnlyProjectionApplyResult:
        identity = projection.identity
        state = self._entities.get(identity.entity_key, _OnlyProjectionEntityState(0, ()))
        applied = dict(state.applied)
        if identity.component is not self._component:
            return self._result(
                OnlyProjectionApplyStatus.INVALID_COMPONENT, execution_sequence, identity, state.version
            )
        prior_hash = applied.get(execution_sequence)
        if prior_hash is not None:
            status = (
                OnlyProjectionApplyStatus.IDEMPOTENT
                if prior_hash == identity.payload_hash
                else OnlyProjectionApplyStatus.PAYLOAD_CONFLICT
            )
            return self._result(status, execution_sequence, identity, state.version)
        if state.version != identity.expected_version:
            return self._result(OnlyProjectionApplyStatus.VERSION_CONFLICT, execution_sequence, identity, state.version)
        applied[execution_sequence] = identity.payload_hash
        self._entities[identity.entity_key] = _OnlyProjectionEntityState(
            identity.result_version, tuple(sorted(applied.items()))
        )
        return self._result(
            OnlyProjectionApplyStatus.APPLIED, execution_sequence, identity, state.version, identity.result_version
        )

    @staticmethod
    def _result(
        status: OnlyProjectionApplyStatus,
        execution_sequence: int,
        identity: OnlyExecutionProjectionIdentity,
        before_version: int,
        after_version: int | None = None,
    ) -> OnlyProjectionApplyResult:
        return OnlyProjectionApplyResult(
            status,
            identity.component,
            identity.entity_key,
            execution_sequence,
            before_version,
            before_version if after_version is None else after_version,
            identity.payload_hash,
        )


__all__ = [name for name in globals() if name.startswith("Only")]
