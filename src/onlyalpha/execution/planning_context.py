"""Immutable authority captured for pure Trade transaction planning."""

from __future__ import annotations

from dataclasses import dataclass

from onlyalpha.broker.updates import OnlyBrokerTradeUpdate
from onlyalpha.domain.identifiers import OnlyEngineId, OnlyPositionId
from onlyalpha.domain.time import OnlyTimestamp, OnlyTradingDay
from onlyalpha.domain.value import OnlyMultiplier, OnlyPrice
from onlyalpha.fee.models import OnlyFeeInstruction
from onlyalpha.market.runtime_rules import OnlyTradeApplicationInstruction
from onlyalpha.position.identifiers import OnlyPositionAllocationId
from onlyalpha.strategy.identifiers import OnlyStrategyId

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
from .projection import (
    OnlyFeeExecutionState,
    OnlySettlementExecutionState,
    OnlyValuationExecutionState,
)
from .scope import OnlyExecutionPositionScope


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
    fee_instruction: OnlyFeeInstruction
    order_before: OnlyOrderExecutionState
    position_before: OnlyPositionExecutionState | None
    allocation_before: OnlyAllocationExecutionState | None
    settlement_before: OnlySettlementExecutionState | None
    fee_before: OnlyFeeExecutionState | None
    account_before: OnlyAccountExecutionState
    strategy_ledger_before: OnlyStrategyLedgerExecutionState
    account_cash_reservation_before: OnlyAccountCashReservationExecutionState
    strategy_cash_reservation_before: OnlyStrategyCashReservationExecutionState
    risk_reservation_before: OnlyRiskReservationExecutionState
    risk_before: OnlyRiskExecutionState
    valuation_before: OnlyValuationExecutionState
    position_creation: OnlyPositionCreationAuthority | None
    allocation_creation: OnlyAllocationCreationAuthority | None
    settlement_record_sequence: int = 0
    fee_record_sequence: int = 0
    position_reservation_before: OnlyPositionReservationExecutionState | None = None
    margin_reservation_before: OnlyMarginReservationExecutionState | None = None

    def __post_init__(self) -> None:
        if self.processing_sequence < 0 or self.settlement_record_sequence < 0 or self.fee_record_sequence < 0:
            raise ValueError("Trade planning sequences cannot be negative")


__all__ = [
    "OnlyAllocationCreationAuthority",
    "OnlyPositionCreationAuthority",
    "OnlyTradeExecutionPlanningContext",
]
