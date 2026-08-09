"""Immutable authority captured for pure Trade transaction planning."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from onlyalpha.account.performance import OnlyAccountEquityPoint
from onlyalpha.broker.updates import OnlyBrokerTradeUpdate
from onlyalpha.domain.identifiers import OnlyEngineId, OnlyPositionId
from onlyalpha.domain.time import OnlyTimestamp, OnlyTradingDay
from onlyalpha.domain.value import OnlyMoney, OnlyMultiplier, OnlyPrice
from onlyalpha.fee.accrual import OnlyOrderFeeAccrualState
from onlyalpha.fee.models import OnlyFeeAssessment
from onlyalpha.market.runtime_rules import OnlyTradeApplicationInstruction
from onlyalpha.position.identifiers import OnlyPositionAllocationId
from onlyalpha.strategy.identifiers import OnlyStrategyId
from onlyalpha.strategy_ledger.models import OnlyStrategyLedgerEquityPoint
from onlyalpha.transaction.projection import (
    OnlyFeeApplicationState,
    OnlySettlementExecutionState,
    OnlyValuationExecutionState,
)

from .capability import OnlyExecutionSupportDecision
from .execution_state import (
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
from .fill_identity import OnlyExecutionFillAuthority
from .scope import OnlyExecutionPositionScope
from .terminal_identity import OnlyBrokerOrderTerminalUpdate, OnlyExecutionTerminalAuthority


@dataclass(frozen=True, slots=True)
class OnlyPositionCreationAuthority:
    """Manager-compatible identity allocated before a pure Position reduction."""

    position_id: OnlyPositionId
    cycle: int

    def __post_init__(self) -> None:
        if self.cycle < 1:
            raise ValueError("Position creation cycle must be positive")


@dataclass(frozen=True, slots=True)
class OnlyAllocationCreationAuthority:
    """Manager-compatible identity allocated before a pure Allocation reduction."""

    allocation_id: OnlyPositionAllocationId
    cycle: int

    def __post_init__(self) -> None:
        if self.cycle < 1:
            raise ValueError("Allocation creation cycle must be positive")


@dataclass(frozen=True, slots=True, kw_only=True)
class OnlyTradeExecutionPlanningContext:
    """Complete, immutable before-authority for one Broker Trade Update."""

    update: OnlyBrokerTradeUpdate
    prepared_at: OnlyTimestamp
    engine_id: OnlyEngineId
    strategy_id: OnlyStrategyId
    processing_sequence: int
    trading_day: OnlyTradingDay
    contract_multiplier: OnlyMultiplier
    valuation_price: OnlyPrice
    position_scope: OnlyExecutionPositionScope
    trade_instruction: OnlyTradeApplicationInstruction
    support_decision: OnlyExecutionSupportDecision
    fee_assessment: OnlyFeeAssessment
    order_before: OnlyOrderExecutionState
    position_before: OnlyPositionExecutionState | None
    allocation_before: OnlyAllocationExecutionState | None
    aggregate_allocation_quantity_before: Decimal
    aggregate_allocation_cumulative_cost_before: Decimal
    account_ledger_parity: bool
    settlement_before: OnlySettlementExecutionState | None
    fee_before: OnlyFeeApplicationState | None
    account_before: OnlyAccountExecutionState
    strategy_ledger_before: OnlyStrategyLedgerExecutionState
    account_cash_reservation_before: OnlyAccountCashReservationExecutionState | None
    strategy_cash_reservation_before: OnlyStrategyCashReservationExecutionState | None
    risk_reservation_before: OnlyRiskReservationExecutionState
    risk_before: OnlyRiskExecutionState
    valuation_before: OnlyValuationExecutionState
    fill_authority: OnlyExecutionFillAuthority
    position_creation: OnlyPositionCreationAuthority | None
    allocation_creation: OnlyAllocationCreationAuthority | None
    order_fee_accrual_before: OnlyOrderFeeAccrualState | None = None
    position_cycle: int = 0
    allocation_cycle: int = 0
    settlement_record_sequence: int = 0
    fee_record_sequence: int = 0
    account_equity_sequence: int = 0
    ledger_equity_sequence: int = 0
    account_external_cash_flow: OnlyMoney | None = None
    ledger_equity_before: OnlyStrategyLedgerEquityPoint | None = None
    ledger_high_water_mark: OnlyMoney | None = None
    position_reservation_before: OnlyPositionReservationExecutionState | None = None
    margin_reservation_before: OnlyMarginReservationExecutionState | None = None
    account_equity_before: tuple[OnlyAccountEquityPoint, ...] = ()
    strategy_equity_before: tuple[OnlyStrategyLedgerEquityPoint, ...] = ()

    def __post_init__(self) -> None:
        if (
            self.processing_sequence < 0
            or self.position_cycle < 0
            or self.allocation_cycle < 0
            or self.settlement_record_sequence < 0
            or self.fee_record_sequence < 0
            or self.account_equity_sequence < 0
            or self.ledger_equity_sequence < 0
        ):
            raise ValueError("Trade planning sequences cannot be negative")


@dataclass(frozen=True, slots=True, kw_only=True)
class OnlyTerminalExecutionPlanningContext:
    """Complete immutable before-authority for one terminal Broker update."""

    update: OnlyBrokerOrderTerminalUpdate
    prepared_at: OnlyTimestamp
    engine_id: OnlyEngineId
    processing_sequence: int
    position_scope: OnlyExecutionPositionScope
    support_decision: OnlyExecutionSupportDecision
    terminal_authority: OnlyExecutionTerminalAuthority
    order_before: OnlyOrderExecutionState
    position_reservation_before: OnlyPositionReservationExecutionState
    risk_reservation_before: OnlyRiskReservationExecutionState
    risk_before: OnlyRiskExecutionState

    def __post_init__(self) -> None:
        if self.processing_sequence < 0:
            raise ValueError("Terminal planning sequence cannot be negative")
        if self.prepared_at < self.update.ts_event:
            raise ValueError("Terminal prepared_at precedes Broker event")


__all__ = [
    "OnlyAllocationCreationAuthority",
    "OnlyPositionCreationAuthority",
    "OnlyTerminalExecutionPlanningContext",
    "OnlyTradeExecutionPlanningContext",
]
