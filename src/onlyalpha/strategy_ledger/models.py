"""Immutable Strategy Ledger commands, entries, snapshots and facts."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from types import MappingProxyType

from onlyalpha.domain.base import OnlyDomainModel
from onlyalpha.domain.execution import OnlyOrderSnapshot
from onlyalpha.domain.identifiers import (
    OnlyAccountId,
    OnlyClusterId,
    OnlyInstrumentId,
    OnlyOrderId,
    OnlyRuntimeId,
    OnlyTradeId,
)
from onlyalpha.domain.time import OnlyTimestamp, OnlyTradingDay
from onlyalpha.domain.value import OnlyCurrency, OnlyMoney, OnlyPrice, OnlyRate
from onlyalpha.position.models import OnlyPositionAllocationSnapshot, OnlyPositionTrade
from onlyalpha.strategy_ledger.enums import (
    OnlyStrategyCapitalAllocationMode,
    OnlyStrategyCashEntryType,
    OnlyStrategyCashReservationStage,
    OnlyStrategyCashReservationState,
    OnlyStrategyFeeType,
    OnlyStrategyLedgerMutationStatus,
    OnlyStrategyLedgerReplayOperation,
    OnlyStrategyLedgerStatus,
)
from onlyalpha.strategy_ledger.identifiers import (
    OnlyStrategyCashEntryId,
    OnlyStrategyCashFlowId,
    OnlyStrategyCashReservationId,
    OnlyStrategyFeeEntryId,
    OnlyStrategyLedgerId,
)
from onlyalpha.strategy_ledger.keys import OnlyStrategyLedgerKey


def only_frozen_metadata(value: Mapping[str, str]) -> Mapping[str, str]:
    return MappingProxyType(dict(value))


@dataclass(frozen=True, slots=True)
class OnlyStrategyCapitalConfig(OnlyDomainModel):
    mode: OnlyStrategyCapitalAllocationMode
    amount: OnlyMoney

    def __post_init__(self) -> None:
        if self.mode is not OnlyStrategyCapitalAllocationMode.FIXED_CAPITAL:
            raise ValueError("first-phase Strategy Ledger implements FIXED_CAPITAL only")
        if self.amount.amount < 0:
            raise ValueError("Strategy capital cannot be negative")


@dataclass(frozen=True, slots=True)
class OnlyStrategyCapitalAllocation(OnlyDomainModel):
    ledger_id: OnlyStrategyLedgerId
    mode: OnlyStrategyCapitalAllocationMode
    amount: OnlyMoney
    allocated_at: OnlyTimestamp


@dataclass(frozen=True, slots=True)
class OnlyStrategyCapitalSnapshot(OnlyDomainModel):
    key: OnlyStrategyLedgerKey
    mode: OnlyStrategyCapitalAllocationMode
    initial_capital: OnlyMoney
    external_cash_flow: OnlyMoney
    as_of: OnlyTimestamp
    version: int


@dataclass(frozen=True, slots=True)
class OnlyStrategyCashEntry(OnlyDomainModel):
    entry_id: OnlyStrategyCashEntryId
    runtime_id: OnlyRuntimeId
    account_id: OnlyAccountId
    cluster_id: OnlyClusterId
    currency: OnlyCurrency
    amount: OnlyMoney
    entry_type: OnlyStrategyCashEntryType
    order_id: OnlyOrderId | None
    trade_id: OnlyTradeId | None
    reservation_id: OnlyStrategyCashReservationId | None
    cash_flow_id: OnlyStrategyCashFlowId | None
    ts_event: OnlyTimestamp
    ts_init: OnlyTimestamp
    sequence: int
    correlation_id: str | None = None
    causation_id: str | None = None
    metadata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.amount.currency != self.currency:
            raise ValueError("Cash Entry amount must use entry currency")
        if self.ts_init.unix_nanos < self.ts_event.unix_nanos or self.sequence < 0:
            raise ValueError("Cash Entry time/sequence is invalid")
        object.__setattr__(self, "metadata", only_frozen_metadata(self.metadata))


@dataclass(frozen=True, slots=True)
class OnlyStrategyFeeEntry(OnlyDomainModel):
    entry_id: OnlyStrategyFeeEntryId
    key: OnlyStrategyLedgerKey
    amount: OnlyMoney
    fee_type: OnlyStrategyFeeType
    trade_id: OnlyTradeId | None
    order_id: OnlyOrderId | None
    ts_event: OnlyTimestamp
    ts_init: OnlyTimestamp
    sequence: int
    metadata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.amount.amount < 0 or self.amount.currency != self.key.base_currency:
            raise ValueError("Fee Entry requires non-negative base-currency amount")
        object.__setattr__(self, "metadata", only_frozen_metadata(self.metadata))


@dataclass(frozen=True, slots=True)
class OnlyStrategyCashReservation(OnlyDomainModel):
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
    version: int = 1
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
            raise ValueError("Cash Reservation values require Ledger base currency")
        if self.consumed_amount.amount + self.remaining_amount.amount != self.reserved_amount.amount:
            raise ValueError("Cash Reservation consumed plus remaining must equal reserved")
        object.__setattr__(self, "metadata", only_frozen_metadata(self.metadata))


@dataclass(frozen=True, slots=True)
class OnlyStrategyTradeAccountingInput(OnlyDomainModel):
    trade: OnlyPositionTrade
    order_snapshot: OnlyOrderSnapshot | None
    position_allocation_before: OnlyPositionAllocationSnapshot | None
    position_allocation_after: OnlyPositionAllocationSnapshot | None
    realized_pnl_delta: OnlyMoney
    position_cost_delta: OnlyMoney
    fee_entries: tuple[OnlyStrategyFeeEntry, ...]
    cash_reservation: OnlyStrategyCashReservation | None
    ts_event: OnlyTimestamp
    sequence: int

    def __post_init__(self) -> None:
        if self.trade.cluster_id is None:
            raise ValueError("Strategy Trade Accounting requires cluster_id")
        if self.ts_event != self.trade.ts_event:
            raise ValueError("Accounting timestamp must equal Trade event timestamp")
        after = self.position_allocation_after
        if after is not None and after.key.cluster_id != self.trade.cluster_id:
            raise ValueError("Accounting Allocation belongs to another Cluster")

    @property
    def stable_order(self) -> tuple[int, int, str]:
        return self.trade.stable_order


@dataclass(frozen=True, slots=True)
class OnlyStrategyMarkPrice(OnlyDomainModel):
    instrument_id: OnlyInstrumentId
    mark_price: OnlyPrice
    price_version: int
    source: str


@dataclass(frozen=True, slots=True)
class OnlyStrategyValuationLine(OnlyDomainModel):
    instrument_id: OnlyInstrumentId
    position_cost: OnlyMoney
    position_market_value: OnlyMoney
    unrealized_pnl: OnlyMoney
    mark_price: OnlyPrice
    price_version: int


@dataclass(frozen=True, slots=True)
class OnlyStrategyValuation(OnlyDomainModel):
    key: OnlyStrategyLedgerKey
    ts_event: OnlyTimestamp
    ts_init: OnlyTimestamp
    valuation_version: int
    position_cost: OnlyMoney
    position_market_value: OnlyMoney
    unrealized_pnl: OnlyMoney
    lines: tuple[OnlyStrategyValuationLine, ...]
    quality_flags: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class OnlyStrategyPnLSnapshot(OnlyDomainModel):
    realized_pnl: OnlyMoney
    unrealized_pnl: OnlyMoney
    fees: OnlyMoney
    net_pnl: OnlyMoney


@dataclass(frozen=True, slots=True)
class OnlyStrategyCashSnapshot(OnlyDomainModel):
    cash_balance: OnlyMoney
    cash_reserved: OnlyMoney
    cash_available: OnlyMoney


@dataclass(frozen=True, slots=True)
class OnlyStrategyEquitySnapshot(OnlyDomainModel):
    key: OnlyStrategyLedgerKey
    ts_event: OnlyTimestamp
    ts_init: OnlyTimestamp
    trading_day: OnlyTradingDay | None
    version: int
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
    net_pnl: OnlyMoney
    equity: OnlyMoney
    equity_by_cash_view: OnlyMoney
    equity_by_pnl_view: OnlyMoney
    high_water_mark: OnlyMoney
    drawdown: OnlyRate
    maximum_drawdown: OnlyRate
    return_since_start: OnlyRate | None
    daily_pnl: OnlyMoney
    daily_return: OnlyRate | None
    quality_flags: tuple[str, ...] = ()
    metadata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "metadata", only_frozen_metadata(self.metadata))


@dataclass(frozen=True, slots=True)
class OnlyStrategyPerformanceSnapshot(OnlyDomainModel):
    cluster_id: OnlyClusterId
    ts_event: OnlyTimestamp
    equity: OnlyMoney
    net_pnl: OnlyMoney
    return_since_start: OnlyRate | None
    daily_pnl: OnlyMoney
    daily_return: OnlyRate | None
    drawdown: OnlyRate
    maximum_drawdown: OnlyRate
    trade_count: int
    realized_pnl_delta_count: int
    winning_trade_count: int
    losing_trade_count: int
    win_rate: OnlyRate | None
    gross_profit: OnlyMoney
    gross_loss: OnlyMoney
    profit_factor: OnlyRate | None
    fees: OnlyMoney


@dataclass(frozen=True, slots=True)
class OnlyStrategyLedgerSnapshot(OnlyDomainModel):
    ledger_id: OnlyStrategyLedgerId
    key: OnlyStrategyLedgerKey
    status: OnlyStrategyLedgerStatus
    capital: OnlyStrategyCapitalSnapshot
    cash: OnlyStrategyCashSnapshot
    pnl: OnlyStrategyPnLSnapshot
    equity: OnlyStrategyEquitySnapshot
    performance: OnlyStrategyPerformanceSnapshot
    cash_entries: tuple[OnlyStrategyCashEntry, ...]
    fee_entries: tuple[OnlyStrategyFeeEntry, ...]
    reservations: tuple[OnlyStrategyCashReservation, ...]
    created_at: OnlyTimestamp
    updated_at: OnlyTimestamp
    valuation_time: OnlyTimestamp
    version: int
    last_trade_sequence: int | None
    last_trade_order: tuple[int, int, str] | None
    quality_flags: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class OnlyStrategyLedgerEvent(OnlyDomainModel):
    event_type: str
    key: OnlyStrategyLedgerKey
    timestamp: OnlyTimestamp
    sequence: int
    ledger_version: int
    correlation_id: str | None = None


@dataclass(frozen=True, slots=True)
class OnlyStrategyLedgerMutationResult(OnlyDomainModel):
    status: OnlyStrategyLedgerMutationStatus
    before: OnlyStrategyLedgerSnapshot | None
    after: OnlyStrategyLedgerSnapshot | None
    cash_delta: OnlyMoney
    realized_pnl_delta: OnlyMoney
    fee_delta: OnlyMoney
    events: tuple[OnlyStrategyLedgerEvent, ...] = ()
    reason: str = ""

    @property
    def changed(self) -> bool:
        return self.status is OnlyStrategyLedgerMutationStatus.APPLIED


@dataclass(frozen=True, slots=True)
class OnlyStrategyLedgerRiskSnapshot(OnlyDomainModel):
    key: OnlyStrategyLedgerKey
    status: OnlyStrategyLedgerStatus
    as_of: OnlyTimestamp
    version: int
    equity: OnlyMoney
    cash_available: OnlyMoney
    cash_reserved: OnlyMoney
    net_pnl: OnlyMoney
    daily_pnl: OnlyMoney
    drawdown: OnlyRate
    maximum_drawdown: OnlyRate


def only_zero_money(currency: OnlyCurrency) -> OnlyMoney:
    return OnlyMoney(Decimal(0), currency)


@dataclass(frozen=True, slots=True)
class OnlyStrategyCashReservationCommand(OnlyDomainModel):
    key: OnlyStrategyLedgerKey
    order_id: OnlyOrderId
    estimated_notional: OnlyMoney
    estimated_fee: OnlyMoney
    timestamp: OnlyTimestamp


@dataclass(frozen=True, slots=True)
class OnlyStrategyCashReservationReleaseCommand(OnlyDomainModel):
    key: OnlyStrategyLedgerKey
    order_id: OnlyOrderId
    timestamp: OnlyTimestamp


@dataclass(frozen=True, slots=True)
class OnlyStrategyExternalCashFlowCommand(OnlyDomainModel):
    key: OnlyStrategyLedgerKey
    cash_flow_id: OnlyStrategyCashFlowId
    amount: OnlyMoney
    timestamp: OnlyTimestamp


@dataclass(frozen=True, slots=True)
class OnlyStrategyLedgerLifecycleCommand(OnlyDomainModel):
    key: OnlyStrategyLedgerKey
    timestamp: OnlyTimestamp
    initial_capital: OnlyMoney | None = None


@dataclass(frozen=True, slots=True)
class OnlyStrategyLedgerReplayEntry(OnlyDomainModel):
    sequence: int
    operation: OnlyStrategyLedgerReplayOperation
    payload_json: str

    def __post_init__(self) -> None:
        if self.sequence < 1 or not self.payload_json:
            raise ValueError("Replay Entry requires positive sequence and payload")
