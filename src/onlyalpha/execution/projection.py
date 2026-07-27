"""Strongly typed, replayable execution projections and apply contracts."""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum, StrEnum
from typing import Protocol

from onlyalpha.domain.base import OnlyDomainModel
from onlyalpha.domain.enums import OnlyOrderStatus
from onlyalpha.domain.execution import OnlyOrderFill
from onlyalpha.domain.identifiers import OnlyAccountId, OnlyClusterId, OnlyInstrumentId, OnlyOrderId
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.domain.value import OnlyMoney, OnlyPrice, OnlyQuantity


class OnlyExecutionProjectionComponent(StrEnum):
    ORDER = "ORDER"
    POSITION = "POSITION"
    ALLOCATION = "ALLOCATION"
    SETTLEMENT = "SETTLEMENT"
    MARGIN = "MARGIN"
    FEE = "FEE"
    ACCOUNT = "ACCOUNT"
    STRATEGY_LEDGER = "STRATEGY_LEDGER"
    RESERVATION = "RESERVATION"
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
    RESERVATION = 9
    RISK = 10
    VALUATION = 11


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
        if len(self.payload_hash) != 64 or any(character not in "0123456789abcdef" for character in self.payload_hash):
            raise ValueError("projection payload_hash must be a lowercase SHA-256 digest")


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
class OnlySettlementExecutionProjection(OnlyDomainModel):
    identity: OnlyExecutionProjectionIdentity
    instruction: str
    before_state: str
    after_state: str
    generated_records: tuple[str, ...]

    def __post_init__(self) -> None:
        _require_component(self.identity, OnlyExecutionProjectionComponent.SETTLEMENT)
        if not self.instruction.strip() or not self.before_state.strip() or not self.after_state.strip():
            raise ValueError("settlement projection requires instruction and states")


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
class OnlyFeeExecutionProjection(OnlyDomainModel):
    identity: OnlyExecutionProjectionIdentity
    fee_instruction: str
    fee_records: tuple[str, ...]
    authoritative_total: OnlyMoney
    fee_breakdown: tuple[OnlyMoney, ...]

    def __post_init__(self) -> None:
        _require_component(self.identity, OnlyExecutionProjectionComponent.FEE)
        _require_key(self.fee_instruction, "fee instruction")
        _require_one_currency((self.authoritative_total, *self.fee_breakdown))
        total = sum((item.amount for item in self.fee_breakdown), start=self.authoritative_total.amount * 0)
        if total != self.authoritative_total.amount:
            raise ValueError("fee projection breakdown must equal authoritative total")


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
            (
                self.cash_before,
                self.cash_after,
                self.frozen_cash_before,
                self.frozen_cash_after,
                self.realized_pnl_before,
                self.realized_pnl_after,
                self.unrealized_pnl_before,
                self.unrealized_pnl_after,
                self.fees_before,
                self.fees_after,
                self.position_market_value_before,
                self.position_market_value_after,
                self.equity_before,
                self.equity_after,
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


class OnlyExecutionReservationKind(StrEnum):
    ACCOUNT_CASH = "ACCOUNT_CASH"
    STRATEGY_CASH = "STRATEGY_CASH"
    POSITION = "POSITION"
    MARGIN = "MARGIN"
    RISK = "RISK"


@dataclass(frozen=True, slots=True)
class OnlyReservationExecutionProjection(OnlyDomainModel):
    identity: OnlyExecutionProjectionIdentity
    reservation_kind: OnlyExecutionReservationKind
    reservation_id: str
    before_state: str
    after_state: str
    consumed_delta: OnlyMoney
    released_delta: OnlyMoney
    remaining: OnlyMoney

    def __post_init__(self) -> None:
        _require_component(self.identity, OnlyExecutionProjectionComponent.RESERVATION)
        _require_key(self.reservation_id, "reservation")
        _require_one_currency((self.consumed_delta, self.released_delta, self.remaining))
        if min(self.consumed_delta.amount, self.released_delta.amount, self.remaining.amount) < 0:
            raise ValueError("reservation projection amounts cannot be negative")


@dataclass(frozen=True, slots=True)
class OnlyRiskExecutionProjection(OnlyDomainModel):
    identity: OnlyExecutionProjectionIdentity
    cluster_id: OnlyClusterId
    account_id: OnlyAccountId
    instrument_id: OnlyInstrumentId
    order_id: OnlyOrderId
    exposure_before: OnlyMoney
    exposure_after: OnlyMoney
    reservation_state_before: str
    reservation_state_after: str

    def __post_init__(self) -> None:
        _require_component(self.identity, OnlyExecutionProjectionComponent.RISK)
        _require_one_currency((self.exposure_before, self.exposure_after))
        if not self.reservation_state_before.strip() or not self.reservation_state_after.strip():
            raise ValueError("risk projection requires reservation states")


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
    | OnlyReservationExecutionProjection
    | OnlyRiskExecutionProjection
    | OnlyValuationExecutionProjection
)


def _require_component(identity: OnlyExecutionProjectionIdentity, expected: OnlyExecutionProjectionComponent) -> None:
    if identity.component is not expected:
        raise ValueError(f"{expected.value} projection requires matching component identity")


def _require_key(value: str, label: str) -> None:
    if not value.strip():
        raise ValueError(f"{label} projection key is required")


def _require_one_currency(values: tuple[OnlyMoney, ...]) -> None:
    if len({item.currency for item in values}) != 1:
        raise ValueError("execution projection monetary values require one currency")


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
