"""Strongly typed, replay-complete execution projections and apply contracts."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import IntEnum, StrEnum
from typing import TYPE_CHECKING, Protocol, cast

from onlyalpha.account.performance import OnlyAccountEquityPoint
from onlyalpha.broker.identifiers import OnlyBrokerUpdateId
from onlyalpha.domain.base import OnlyDomainModel
from onlyalpha.domain.enums import OnlyOrderStatus
from onlyalpha.domain.execution import OnlyOrderFill
from onlyalpha.domain.identifiers import OnlyAccountId, OnlyInstrumentId, OnlyOrderId
from onlyalpha.domain.time import OnlyTimestamp, OnlyTradingDay
from onlyalpha.domain.value import OnlyMoney
from onlyalpha.execution.execution_state import (
    OnlyAccountCashReservationExecutionState,
    OnlyAccountExecutionState,
    OnlyAllocationExecutionState,
    OnlyMarginReservationExecutionState,
    OnlyOrderExecutionState,
    OnlyPositionExecutionState,
    OnlyPositionReservationExecutionState,
    OnlyRiskExecutionState,
    OnlyRiskReservationExecutionState,
    OnlyStrategyCashReservationExecutionState,
    OnlyStrategyLedgerExecutionState,
)
from onlyalpha.fee.accrual import OnlyOrderFeeAccrualState
from onlyalpha.fee.adjustment import OnlyUnallocatedExternalFeeState
from onlyalpha.fee.application import OnlyFeeApplicationInstruction
from onlyalpha.fee.ledger import OnlyFeeApplicationRecord
from onlyalpha.fee.reconciliation_authority import (
    OnlyExternalFeeEvidenceState,
    OnlyFeeAdjustmentState,
    OnlyFeeReconciliationDecisionState,
)
from onlyalpha.fee.risk_gate import OnlyFeeReconciliationRiskGateState
from onlyalpha.settlement.models import OnlySettlementInstruction
from onlyalpha.strategy_ledger.models import OnlyStrategyLedgerEquityPoint, OnlyStrategyValuationLine
from onlyalpha.transaction.state_hash import only_execution_state_hash

if TYPE_CHECKING:
    from .applied_projection import OnlyRuntimeProjectionApplyContext


class OnlyRuntimeProjectionComponent(StrEnum):
    ORDER = "ORDER"
    POSITION = "POSITION"
    ALLOCATION = "ALLOCATION"
    SETTLEMENT = "SETTLEMENT"
    MARGIN = "MARGIN"
    ORDER_FEE_ACCRUAL = "ORDER_FEE_ACCRUAL"
    FEE_LEDGER = "FEE_LEDGER"
    ACCOUNT = "ACCOUNT"
    STRATEGY_LEDGER = "STRATEGY_LEDGER"
    ACCOUNT_CASH_RESERVATION = "ACCOUNT_CASH_RESERVATION"
    STRATEGY_CASH_RESERVATION = "STRATEGY_CASH_RESERVATION"
    POSITION_RESERVATION = "POSITION_RESERVATION"
    MARGIN_RESERVATION = "MARGIN_RESERVATION"
    RISK_RESERVATION = "RISK_RESERVATION"
    RISK = "RISK"
    VALUATION = "VALUATION"
    EXTERNAL_FEE_EVIDENCE = "EXTERNAL_FEE_EVIDENCE"
    FEE_RECONCILIATION = "FEE_RECONCILIATION"
    FEE_ADJUSTMENT_LEDGER = "FEE_ADJUSTMENT_LEDGER"
    UNALLOCATED_EXTERNAL_FEE = "UNALLOCATED_EXTERNAL_FEE"
    RECONCILIATION_RISK_GATE = "RECONCILIATION_RISK_GATE"


class OnlyRuntimeProjectionOrder(IntEnum):
    ORDER = 1
    POSITION = 2
    ALLOCATION = 3
    SETTLEMENT = 4
    MARGIN = 5
    ORDER_FEE_ACCRUAL = 6
    FEE_LEDGER = 7
    ACCOUNT = 8
    STRATEGY_LEDGER = 9
    ACCOUNT_CASH_RESERVATION = 10
    STRATEGY_CASH_RESERVATION = 11
    POSITION_RESERVATION = 12
    MARGIN_RESERVATION = 13
    RISK_RESERVATION = 14
    RISK = 15
    VALUATION = 16
    EXTERNAL_FEE_EVIDENCE = 6
    FEE_RECONCILIATION = 7
    FEE_ADJUSTMENT_LEDGER = 8
    UNALLOCATED_EXTERNAL_FEE = 10
    RECONCILIATION_RISK_GATE = 11


@dataclass(frozen=True, slots=True)
class OnlyRuntimeProjectionIdentity(OnlyDomainModel):
    component: OnlyRuntimeProjectionComponent
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
    identity: OnlyRuntimeProjectionIdentity
    before: OnlyOrderExecutionState
    after: OnlyOrderExecutionState
    fill: OnlyOrderFill
    broker_update_id: OnlyBrokerUpdateId

    def __post_init__(self) -> None:
        _require_component(self.identity, OnlyRuntimeProjectionComponent.ORDER)
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
        if self.after.fill_count != self.before.fill_count + 1:
            raise ValueError("Order projection fill count must advance once")
        if self.after.last_trade_id != self.fill.trade_id:
            raise ValueError("Order projection last Trade identity mismatch")
        if (
            self.after.cumulative_price_quantity - self.before.cumulative_price_quantity
            != self.fill.price.value * self.fill.quantity.value
        ):
            raise ValueError("Order projection cumulative price quantity delta mismatch")
        if self.after.remaining_quantity.value == 0 and self.after.status is not OnlyOrderStatus.FILLED:
            raise ValueError("fully filled Order projection requires FILLED status")
        if self.after.last_external_sequence is not None and self.before.last_external_sequence is not None:
            if self.after.last_external_sequence < self.before.last_external_sequence:
                raise ValueError("Order projection external sequence cannot regress")


@dataclass(frozen=True, slots=True)
class OnlyOrderIntentExecutionProjection(OnlyDomainModel):
    identity: OnlyRuntimeProjectionIdentity
    before: None
    after: OnlyOrderExecutionState

    def __post_init__(self) -> None:
        _require_component(self.identity, OnlyRuntimeProjectionComponent.ORDER)
        _require_state_contract(self.identity, self.before, self.after)
        if self.identity.entity_key != str(self.after.order_id):
            raise ValueError("Order Intent projection entity mismatch")
        if self.after.status is not OnlyOrderStatus.CREATED or self.after.version < 1:
            raise ValueError("Order Intent projection requires a newly created Order")


@dataclass(frozen=True, slots=True)
class OnlyOrderAcceptedExecutionProjection(OnlyDomainModel):
    identity: OnlyRuntimeProjectionIdentity
    before: OnlyOrderExecutionState
    after: OnlyOrderExecutionState
    broker_update_id: OnlyBrokerUpdateId
    accepted_identity: str

    def __post_init__(self) -> None:
        _require_component(self.identity, OnlyRuntimeProjectionComponent.ORDER)
        _require_state_contract(self.identity, self.before, self.after)
        if _order_scope(self.before) != _order_scope(self.after) or self.identity.entity_key != str(
            self.after.order_id
        ):
            raise ValueError("Order Accepted projection before/after scope mismatch")
        if not self.accepted_identity.startswith("EACK-") or not str(self.broker_update_id).strip():
            raise ValueError("Order Accepted projection requires accepted/update identity")
        if self.after.venue_order_id is None:
            raise ValueError("Order Accepted projection requires Venue Order identity")
        unchanged = (
            self.before.quantity == self.after.quantity,
            self.before.filled_quantity == self.after.filled_quantity,
            self.before.remaining_quantity == self.after.remaining_quantity,
            self.before.average_fill_price == self.after.average_fill_price,
            self.before.fill_count == self.after.fill_count,
            self.before.cumulative_price_quantity == self.after.cumulative_price_quantity,
            self.before.last_trade_id == self.after.last_trade_id,
        )
        if not all(unchanged):
            raise ValueError("Order Accepted projection cannot create or alter Fill authority")
        _require_external_sequence(self.before.last_external_sequence, self.after.last_external_sequence)


@dataclass(frozen=True, slots=True)
class OnlyOrderTerminalExecutionProjection(OnlyDomainModel):
    identity: OnlyRuntimeProjectionIdentity
    before: OnlyOrderExecutionState
    after: OnlyOrderExecutionState
    broker_update_id: OnlyBrokerUpdateId
    terminal_identity: str
    terminal_status: OnlyOrderStatus
    terminal_reason: str

    def __post_init__(self) -> None:
        _require_component(self.identity, OnlyRuntimeProjectionComponent.ORDER)
        _require_state_contract(self.identity, self.before, self.after)
        if _order_scope(self.before) != _order_scope(self.after) or self.identity.entity_key != str(
            self.after.order_id
        ):
            raise ValueError("Order terminal projection before/after scope mismatch")
        if not self.terminal_identity.startswith("ETERM-") or not str(self.broker_update_id).strip():
            raise ValueError("Order terminal projection requires terminal/update identity")
        if self.after.status is not self.terminal_status or self.terminal_status not in {
            OnlyOrderStatus.CANCELLED,
            OnlyOrderStatus.REJECTED,
            OnlyOrderStatus.EXPIRED,
        }:
            raise ValueError("Order terminal projection status is invalid")
        unchanged = (
            self.before.quantity == self.after.quantity,
            self.before.filled_quantity == self.after.filled_quantity,
            self.before.remaining_quantity == self.after.remaining_quantity,
            self.before.average_fill_price == self.after.average_fill_price,
            self.before.fill_count == self.after.fill_count,
            self.before.cumulative_price_quantity == self.after.cumulative_price_quantity,
            self.before.last_trade_id == self.after.last_trade_id,
        )
        if not all(unchanged):
            raise ValueError("Order terminal projection cannot create or alter Fill authority")
        _require_external_sequence(self.before.last_external_sequence, self.after.last_external_sequence)


@dataclass(frozen=True, slots=True)
class OnlyPositionExecutionReplayMetadata(OnlyDomainModel):
    cycle: int

    def __post_init__(self) -> None:
        if self.cycle < 1:
            raise ValueError("Position replay cycle must be positive")


@dataclass(frozen=True, slots=True)
class OnlyAllocationExecutionReplayMetadata(OnlyDomainModel):
    cycle: int

    def __post_init__(self) -> None:
        if self.cycle < 1:
            raise ValueError("Allocation replay cycle must be positive")


@dataclass(frozen=True, slots=True)
class OnlyPositionExecutionProjection(OnlyDomainModel):
    identity: OnlyRuntimeProjectionIdentity
    before: OnlyPositionExecutionState | None
    after: OnlyPositionExecutionState
    realized_pnl_delta: OnlyMoney
    replay: OnlyPositionExecutionReplayMetadata

    def __post_init__(self) -> None:
        _require_component(self.identity, OnlyRuntimeProjectionComponent.POSITION)
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
    identity: OnlyRuntimeProjectionIdentity
    before: OnlyAllocationExecutionState | None
    after: OnlyAllocationExecutionState
    realized_pnl_delta: OnlyMoney
    replay: OnlyAllocationExecutionReplayMetadata

    def __post_init__(self) -> None:
        _require_component(self.identity, OnlyRuntimeProjectionComponent.ALLOCATION)
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
    record_sequence_head: int
    instruction: OnlySettlementInstruction | None = None

    def __post_init__(self) -> None:
        if (
            not self.instruction_id.strip()
            or not self.source_trade_id.strip()
            or self.version < 1
            or self.record_sequence_head < 0
        ):
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
    identity: OnlyRuntimeProjectionIdentity
    before: OnlySettlementExecutionState | None
    after: OnlySettlementExecutionState
    records: tuple[OnlySettlementRecordReplay, ...]

    def __post_init__(self) -> None:
        _require_component(self.identity, OnlyRuntimeProjectionComponent.SETTLEMENT)
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
    identity: OnlyRuntimeProjectionIdentity
    before: OnlyMarginExecutionState | None
    after: OnlyMarginExecutionState

    def __post_init__(self) -> None:
        _require_component(self.identity, OnlyRuntimeProjectionComponent.MARGIN)
        _require_state_contract(self.identity, self.before, self.after)


@dataclass(frozen=True, slots=True)
class OnlyFeeApplicationState(OnlyDomainModel):
    application: OnlyFeeApplicationInstruction
    records: tuple[OnlyFeeApplicationRecord, ...]
    total_charges: OnlyMoney
    total_rebates: OnlyMoney
    version: int
    record_sequence_head: int

    def __post_init__(self) -> None:
        if self.total_charges != self.application.total_charges or self.total_rebates != self.application.total_rebates:
            raise ValueError("Fee Application state total mismatch")
        if self.version < 1 or self.record_sequence_head < 0:
            raise ValueError("Fee Application state version/sequence is invalid")
        if any(item.application_id != self.application.application_id for item in self.records):
            raise ValueError("Fee Application record scope mismatch")


@dataclass(frozen=True, slots=True)
class OnlyFeeApplicationProjection(OnlyDomainModel):
    identity: OnlyRuntimeProjectionIdentity
    before: OnlyFeeApplicationState | None
    after: OnlyFeeApplicationState

    def __post_init__(self) -> None:
        _require_component(self.identity, OnlyRuntimeProjectionComponent.FEE_LEDGER)
        _require_state_contract(self.identity, self.before, self.after)
        if self.identity.entity_key != self.after.application.application_id:
            raise ValueError("Fee Application projection entity key mismatch")


@dataclass(frozen=True, slots=True)
class OnlyOrderFeeAccrualProjection(OnlyDomainModel):
    identity: OnlyRuntimeProjectionIdentity
    before: OnlyOrderFeeAccrualState | None
    after: OnlyOrderFeeAccrualState

    def __post_init__(self) -> None:
        _require_component(self.identity, OnlyRuntimeProjectionComponent.ORDER_FEE_ACCRUAL)
        _require_state_contract(self.identity, self.before, self.after)
        if self.identity.entity_key != str(self.after.order_id):
            raise ValueError("Order fee accrual projection entity key mismatch")
        if self.before is not None and (
            self.before.order_id != self.after.order_id
            or self.after.fill_count != self.before.fill_count + 1
            or self.after.version != self.before.version + 1
        ):
            raise ValueError("Order fee accrual projection authority changed")


@dataclass(frozen=True, slots=True)
class OnlyAccountExecutionProjection(OnlyDomainModel):
    identity: OnlyRuntimeProjectionIdentity
    before: OnlyAccountExecutionState
    after: OnlyAccountExecutionState

    def __post_init__(self) -> None:
        _require_component(self.identity, OnlyRuntimeProjectionComponent.ACCOUNT)
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
    identity: OnlyRuntimeProjectionIdentity
    before: OnlyStrategyLedgerExecutionState
    after: OnlyStrategyLedgerExecutionState
    valuation_lines: tuple[OnlyStrategyValuationLine, ...] = ()

    def __post_init__(self) -> None:
        _require_component(self.identity, OnlyRuntimeProjectionComponent.STRATEGY_LEDGER)
        _require_state_contract(self.identity, self.before, self.after)
        if self.before.ledger_id != self.after.ledger_id or self.before.key != self.after.key:
            raise ValueError("Strategy Ledger projection scope mismatch")
        if self.identity.entity_key != str(self.after.ledger_id):
            raise ValueError("Strategy Ledger projection entity mismatch")
        _require_last_trade_order(self.before.last_trade_order, self.after.last_trade_order)


@dataclass(frozen=True, slots=True)
class OnlyAccountCashReservationExecutionProjection(OnlyDomainModel):
    identity: OnlyRuntimeProjectionIdentity
    before: OnlyAccountCashReservationExecutionState | None
    after: OnlyAccountCashReservationExecutionState

    def __post_init__(self) -> None:
        _require_component(self.identity, OnlyRuntimeProjectionComponent.ACCOUNT_CASH_RESERVATION)
        _require_state_contract(self.identity, self.before, self.after)
        _require_reservation_scope(self.identity.entity_key, self.before, self.after)
        if self.before is not None:
            _require_account_cash_reservation_transition(self.before, self.after)


@dataclass(frozen=True, slots=True)
class OnlyStrategyCashReservationExecutionProjection(OnlyDomainModel):
    identity: OnlyRuntimeProjectionIdentity
    before: OnlyStrategyCashReservationExecutionState | None
    after: OnlyStrategyCashReservationExecutionState

    def __post_init__(self) -> None:
        _require_component(self.identity, OnlyRuntimeProjectionComponent.STRATEGY_CASH_RESERVATION)
        _require_state_contract(self.identity, self.before, self.after)
        _require_reservation_scope(self.identity.entity_key, self.before, self.after)
        if self.before is not None:
            _require_strategy_cash_reservation_transition(self.before, self.after)


@dataclass(frozen=True, slots=True)
class OnlyPositionReservationExecutionProjection(OnlyDomainModel):
    identity: OnlyRuntimeProjectionIdentity
    before: OnlyPositionReservationExecutionState | None
    after: OnlyPositionReservationExecutionState

    def __post_init__(self) -> None:
        _require_component(self.identity, OnlyRuntimeProjectionComponent.POSITION_RESERVATION)
        _require_state_contract(self.identity, self.before, self.after)
        _require_reservation_scope(self.identity.entity_key, self.before, self.after)
        if self.before is not None:
            _require_position_reservation_transition(self.before, self.after)


@dataclass(frozen=True, slots=True)
class OnlyMarginReservationExecutionProjection(OnlyDomainModel):
    identity: OnlyRuntimeProjectionIdentity
    before: OnlyMarginReservationExecutionState | None
    after: OnlyMarginReservationExecutionState

    def __post_init__(self) -> None:
        _require_component(self.identity, OnlyRuntimeProjectionComponent.MARGIN_RESERVATION)
        _require_state_contract(self.identity, self.before, self.after)
        _require_reservation_scope(self.identity.entity_key, self.before, self.after)
        if self.before is not None:
            _require_margin_reservation_transition(self.before, self.after)


@dataclass(frozen=True, slots=True)
class OnlyRiskReservationExecutionProjection(OnlyDomainModel):
    identity: OnlyRuntimeProjectionIdentity
    before: OnlyRiskReservationExecutionState | None
    after: OnlyRiskReservationExecutionState

    def __post_init__(self) -> None:
        _require_component(self.identity, OnlyRuntimeProjectionComponent.RISK_RESERVATION)
        _require_state_contract(self.identity, self.before, self.after)
        _require_reservation_scope(self.identity.entity_key, self.before, self.after)
        if self.before is not None:
            _require_risk_reservation_transition(self.before, self.after)


@dataclass(frozen=True, slots=True)
class OnlyRiskExecutionProjection(OnlyDomainModel):
    identity: OnlyRuntimeProjectionIdentity
    before: OnlyRiskExecutionState
    after: OnlyRiskExecutionState

    def __post_init__(self) -> None:
        _require_component(self.identity, OnlyRuntimeProjectionComponent.RISK)
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
    identity: OnlyRuntimeProjectionIdentity
    before: OnlyValuationExecutionState | None
    after: OnlyValuationExecutionState
    account_equity_points: tuple[OnlyAccountEquityPoint, ...] = ()
    strategy_equity_points: tuple[OnlyStrategyLedgerEquityPoint, ...] = ()
    account_equity_before: tuple[OnlyAccountEquityPoint, ...] = ()
    strategy_equity_before: tuple[OnlyStrategyLedgerEquityPoint, ...] = ()

    def __post_init__(self) -> None:
        _require_component(self.identity, OnlyRuntimeProjectionComponent.VALUATION)
        _require_state_contract(self.identity, self.before, self.after)


@dataclass(frozen=True, slots=True)
class OnlyExternalFeeEvidenceProjection(OnlyDomainModel):
    identity: OnlyRuntimeProjectionIdentity
    before: OnlyExternalFeeEvidenceState | None
    after: OnlyExternalFeeEvidenceState

    def __post_init__(self) -> None:
        _require_component(self.identity, OnlyRuntimeProjectionComponent.EXTERNAL_FEE_EVIDENCE)
        _require_state_contract(self.identity, self.before, self.after)
        if self.identity.entity_key != self.after.evidence.evidence_id:
            raise ValueError("external fee evidence projection entity mismatch")


@dataclass(frozen=True, slots=True)
class OnlyFeeReconciliationProjection(OnlyDomainModel):
    schema_version = 2

    identity: OnlyRuntimeProjectionIdentity
    before: OnlyFeeReconciliationDecisionState | None
    after: OnlyFeeReconciliationDecisionState

    def __post_init__(self) -> None:
        _require_component(self.identity, OnlyRuntimeProjectionComponent.FEE_RECONCILIATION)
        _require_state_contract(self.identity, self.before, self.after)
        if self.identity.entity_key != self.after.decision.reconciliation_id:
            raise ValueError("fee reconciliation projection entity mismatch")


@dataclass(frozen=True, slots=True)
class OnlyFeeAdjustmentProjection(OnlyDomainModel):
    schema_version = 2

    identity: OnlyRuntimeProjectionIdentity
    before: OnlyFeeAdjustmentState | None
    after: OnlyFeeAdjustmentState

    def __post_init__(self) -> None:
        _require_component(self.identity, OnlyRuntimeProjectionComponent.FEE_ADJUSTMENT_LEDGER)
        _require_state_contract(self.identity, self.before, self.after)
        if self.identity.entity_key != self.after.adjustment.adjustment_id:
            raise ValueError("fee adjustment projection entity mismatch")


@dataclass(frozen=True, slots=True)
class OnlyUnallocatedExternalFeeProjection(OnlyDomainModel):
    identity: OnlyRuntimeProjectionIdentity
    before: OnlyUnallocatedExternalFeeState | None
    after: OnlyUnallocatedExternalFeeState

    def __post_init__(self) -> None:
        _require_component(self.identity, OnlyRuntimeProjectionComponent.UNALLOCATED_EXTERNAL_FEE)
        _require_state_contract(self.identity, self.before, self.after)
        if self.identity.entity_key != str(self.after.account_id):
            raise ValueError("unallocated external fee projection entity mismatch")


@dataclass(frozen=True, slots=True)
class OnlyFeeReconciliationRiskGateProjection(OnlyDomainModel):
    schema_version = 2

    identity: OnlyRuntimeProjectionIdentity
    before: OnlyFeeReconciliationRiskGateState | None
    after: OnlyFeeReconciliationRiskGateState

    def __post_init__(self) -> None:
        _require_component(self.identity, OnlyRuntimeProjectionComponent.RECONCILIATION_RISK_GATE)
        _require_state_contract(self.identity, self.before, self.after)
        if self.identity.entity_key != str(self.after.account_id):
            raise ValueError("fee reconciliation risk gate projection entity mismatch")


type OnlyRuntimeProjection = (
    OnlyOrderIntentExecutionProjection
    | OnlyOrderExecutionProjection
    | OnlyOrderAcceptedExecutionProjection
    | OnlyOrderTerminalExecutionProjection
    | OnlyPositionExecutionProjection
    | OnlyAllocationExecutionProjection
    | OnlySettlementExecutionProjection
    | OnlyMarginExecutionProjection
    | OnlyFeeApplicationProjection
    | OnlyOrderFeeAccrualProjection
    | OnlyAccountExecutionProjection
    | OnlyStrategyLedgerExecutionProjection
    | OnlyAccountCashReservationExecutionProjection
    | OnlyStrategyCashReservationExecutionProjection
    | OnlyPositionReservationExecutionProjection
    | OnlyMarginReservationExecutionProjection
    | OnlyRiskReservationExecutionProjection
    | OnlyRiskExecutionProjection
    | OnlyValuationExecutionProjection
    | OnlyExternalFeeEvidenceProjection
    | OnlyFeeReconciliationProjection
    | OnlyFeeAdjustmentProjection
    | OnlyUnallocatedExternalFeeProjection
    | OnlyFeeReconciliationRiskGateProjection
)
type OnlyExecutionReservationProjection = (
    OnlyAccountCashReservationExecutionProjection
    | OnlyStrategyCashReservationExecutionProjection
    | OnlyPositionReservationExecutionProjection
    | OnlyMarginReservationExecutionProjection
    | OnlyRiskReservationExecutionProjection
)


def _require_component(identity: OnlyRuntimeProjectionIdentity, expected: OnlyRuntimeProjectionComponent) -> None:
    if identity.component is not expected:
        raise ValueError(f"{expected.value} projection requires matching component identity")


def _require_digest(value: str, label: str) -> None:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError(f"{label} must be a lowercase SHA-256 digest")


def _require_state_contract(
    identity: OnlyRuntimeProjectionIdentity,
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
        or after.version
        != before.version + 1 + int(after.state.value == "RELEASED" and after.consumed_amount != before.consumed_amount)
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
        or after.version
        != before.version + 1 + int(after.state.value == "RELEASED" and after.consumed_amount != before.consumed_amount)
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
            before.margin_mode,
            before.isolation_key,
            before.position_side,
        )
        != (
            after.runtime_id,
            after.account_id,
            after.instrument_id,
            after.order_id,
            after.currency,
            after.original_reserved_amount,
            after.margin_mode,
            after.isolation_key,
            after.position_side,
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
    RECOVERED = "RECOVERED"
    VERSION_CONFLICT = "VERSION_CONFLICT"
    STATE_CONFLICT = "STATE_CONFLICT"
    PAYLOAD_CONFLICT = "PAYLOAD_CONFLICT"
    INVALID_COMPONENT = "INVALID_COMPONENT"


@dataclass(frozen=True, slots=True)
class OnlyProjectionApplyResult:
    status: OnlyProjectionApplyStatus
    component: OnlyRuntimeProjectionComponent
    entity_key: str
    execution_sequence: int
    before_version: int
    after_version: int
    before_state_hash: str
    after_state_hash: str
    payload_hash: str


class OnlyRuntimeProjectionTarget(Protocol):
    @property
    def component(self) -> OnlyRuntimeProjectionComponent: ...

    def apply_execution_projection(self, context: OnlyRuntimeProjectionApplyContext) -> OnlyProjectionApplyResult: ...


@dataclass(frozen=True, slots=True)
class _OnlyProjectionEntityState:
    version: int
    state_hash: str
    applied: tuple[tuple[int, str], ...]


class OnlyReferenceRuntimeProjectionTarget:
    """Reference target implementing version, state-hash and idempotency checks."""

    def __init__(self, component: OnlyRuntimeProjectionComponent) -> None:
        self._component = component
        self._entities: dict[str, _OnlyProjectionEntityState] = {}

    @property
    def component(self) -> OnlyRuntimeProjectionComponent:
        return self._component

    def seed(self, entity_key: str, version: int, state_hash: str) -> None:
        _require_digest(state_hash, "seed state_hash")
        self._entities[entity_key] = _OnlyProjectionEntityState(version, state_hash, ())

    def apply_execution_projection(self, context: OnlyRuntimeProjectionApplyContext) -> OnlyProjectionApplyResult:
        execution_sequence = context.execution_sequence
        projection = context.projection
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
        identity: OnlyRuntimeProjectionIdentity,
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
