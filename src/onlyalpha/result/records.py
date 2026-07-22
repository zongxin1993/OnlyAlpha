"""Immutable provider-neutral result records.

These DTOs deliberately contain no Runtime, plugin, dataframe, or file handles.
Decimal values remain Decimal until an output adapter serializes them.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from types import MappingProxyType

from onlyalpha.domain.time import only_require_utc


def _freeze(value: Mapping[str, object]) -> Mapping[str, object]:
    return MappingProxyType(dict(value))


@dataclass(frozen=True, slots=True, kw_only=True)
class OnlySequencedResultRecord:
    sequence: int

    def __post_init__(self) -> None:
        if isinstance(self.sequence, bool) or self.sequence < 0:
            raise ValueError("result sequence cannot be negative")


@dataclass(frozen=True, slots=True, kw_only=True)
class OnlySignalResultRecord(OnlySequencedResultRecord):
    signal_id: str
    cluster_id: str
    strategy_id: str
    instrument_id: str
    signal_type: str
    ts_event: datetime
    trading_day: date
    factor_id: str | None = None
    score: Decimal | None = None
    confidence: Decimal | None = None
    related_order_request_id: str | None = None
    payload: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        OnlySequencedResultRecord.__post_init__(self)
        only_require_utc(self.ts_event, "signal ts_event")
        if not all((self.signal_id, self.cluster_id, self.strategy_id, self.instrument_id, self.signal_type)):
            raise ValueError("signal identity and type are required")
        object.__setattr__(self, "payload", _freeze(self.payload))


@dataclass(frozen=True, slots=True, kw_only=True)
class OnlyOrderRequestResultRecord(OnlySequencedResultRecord):
    request_id: str
    runtime_id: str
    cluster_id: str
    strategy_id: str
    account_id: str
    instrument_id: str
    side: str
    offset: str
    order_type: str
    quantity: Decimal
    submitted_at: datetime
    limit_price: Decimal | None = None
    stop_price: Decimal | None = None
    tags: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        OnlySequencedResultRecord.__post_init__(self)
        only_require_utc(self.submitted_at, "order request submitted_at")
        if self.quantity <= 0:
            raise ValueError("order request quantity must be positive")
        object.__setattr__(self, "tags", tuple(self.tags))


@dataclass(frozen=True, slots=True, kw_only=True)
class OnlyOrderResultRecord(OnlySequencedResultRecord):
    order_id: str
    request_id: str
    runtime_id: str
    cluster_id: str
    strategy_id: str
    account_id: str
    instrument_id: str
    side: str
    offset: str
    order_type: str
    requested_quantity: Decimal
    filled_quantity: Decimal
    remaining_quantity: Decimal
    status: str
    submitted_at: datetime
    accepted_at: datetime | None = None
    completed_at: datetime | None = None
    rejection_code: str | None = None
    rejection_message: str | None = None
    tags: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        OnlySequencedResultRecord.__post_init__(self)
        only_require_utc(self.submitted_at, "order submitted_at")
        for name, value in (("accepted_at", self.accepted_at), ("completed_at", self.completed_at)):
            if value is not None:
                only_require_utc(value, name)
        if min(self.requested_quantity, self.filled_quantity, self.remaining_quantity) < 0:
            raise ValueError("order quantities cannot be negative")
        if self.filled_quantity + self.remaining_quantity != self.requested_quantity:
            raise ValueError("filled plus remaining quantity must equal requested quantity")
        object.__setattr__(self, "tags", tuple(self.tags))


@dataclass(frozen=True, slots=True, kw_only=True)
class OnlyExecutionResultRecord(OnlySequencedResultRecord):
    execution_id: str
    order_id: str
    request_id: str
    runtime_id: str
    cluster_id: str
    strategy_id: str
    account_id: str
    instrument_id: str
    side: str
    offset: str
    quantity: Decimal
    price: Decimal
    turnover: Decimal
    commission: Decimal
    fees: Decimal
    slippage: Decimal | None
    ts_event: datetime
    trading_day: date
    venue: str
    position_side: str | None = None
    position_effect: str | None = None
    position_mode: str | None = None
    realized_pnl_delta: Decimal = Decimal(0)
    reference_price: Decimal | None = None
    contract_multiplier: Decimal = Decimal(1)
    market_profile_id: str | None = None
    market_profile_version: str | None = None
    compiled_rule_fingerprint: str | None = None
    reference_fingerprint: str | None = None
    trade_instruction_id: str | None = None
    fee_instruction_id: str | None = None
    market_fee_schedule_ids: tuple[str, ...] = ()
    market_fee_schedule_versions: tuple[str, ...] = ()
    broker_fee_schedule_ids: tuple[str, ...] = ()
    broker_fee_schedule_versions: tuple[str, ...] = ()
    settlement_instruction_id: str | None = None
    settlement_status: str | None = None
    margin_instruction_id: str | None = None
    margin_action: str | None = None
    margin_amount: Decimal | None = None
    reported_broker_fee: Decimal | None = None
    fee_reporting_mode: str = "NONE"
    liquidity_side: str = "UNKNOWN"
    fee_breakdown: Mapping[str, Decimal] = field(default_factory=dict)
    liquidity: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        OnlySequencedResultRecord.__post_init__(self)
        only_require_utc(self.ts_event, "execution ts_event")
        if self.quantity <= 0 or self.price <= 0:
            raise ValueError("execution price and quantity must be positive")
        if min(self.turnover, self.commission, self.fees) < 0:
            raise ValueError("execution turnover and fees cannot be negative")
        if self.contract_multiplier <= 0:
            raise ValueError("execution contract multiplier must be positive")
        object.__setattr__(self, "fee_breakdown", MappingProxyType(dict(self.fee_breakdown)))
        object.__setattr__(self, "liquidity", _freeze(self.liquidity))


@dataclass(frozen=True, slots=True, kw_only=True)
class OnlySettlementResultRecord(OnlySequencedResultRecord):
    account_id: str
    instrument_id: str
    execution_id: str
    asset_quantity: Decimal
    cash_amount: Decimal
    trade_time: datetime
    asset_available_time: datetime
    cash_available_time: datetime
    settlement_time: datetime
    status: str
    settlement_model_id: str

    def __post_init__(self) -> None:
        OnlySequencedResultRecord.__post_init__(self)
        for name in ("trade_time", "asset_available_time", "cash_available_time", "settlement_time"):
            only_require_utc(getattr(self, name), name)


@dataclass(frozen=True, slots=True, kw_only=True)
class OnlyMarginResultRecord(OnlySequencedResultRecord):
    account_id: str
    instrument_id: str
    position_side: str
    initial_margin: Decimal
    maintenance_margin: Decimal
    used_margin: Decimal
    available_margin: Decimal
    margin_ratio: Decimal | None
    margin_record_id: str = ""
    order_id: str = ""
    trade_id: str = ""
    operation: str = ""
    reserved_delta: Decimal = Decimal(0)
    occupied_delta: Decimal = Decimal(0)
    released_delta: Decimal = Decimal(0)
    currency: str = ""
    amount: Decimal = Decimal(0)


@dataclass(frozen=True, slots=True, kw_only=True)
class OnlyFeeResultRecord(OnlySequencedResultRecord):
    fee_record_id: str
    instruction_id: str
    idempotency_key: str
    account_id: str
    instrument_id: str
    order_id: str
    trade_id: str
    fee_type: str
    authority: str
    status: str
    accrued: Decimal
    charged: Decimal
    currency: str
    schedule_id: str | None
    schedule_version: str | None


@dataclass(frozen=True, slots=True, kw_only=True)
class OnlyMarketRuleDecisionResultRecord(OnlySequencedResultRecord):
    account_id: str
    instrument_id: str
    market_profile_id: str
    rule_set_id: str
    rule_type: str
    decision: str
    reason: str | None
    ts_event: datetime

    def __post_init__(self) -> None:
        OnlySequencedResultRecord.__post_init__(self)
        only_require_utc(self.ts_event, "market rule decision ts_event")


@dataclass(frozen=True, slots=True, kw_only=True)
class OnlyProfileTimelineResultRecord(OnlySequencedResultRecord):
    runtime_id: str
    profile_id: str
    profile_version: str
    trading_day: date
    effective_from: datetime | None
    effective_to: datetime | None
    resolved_rules_fingerprint: str
    reference_fingerprint: str
    override_fingerprint: str
    runtime_mode: str


@dataclass(frozen=True, slots=True, kw_only=True)
class OnlyCompiledMarketRuleResultRecord(OnlySequencedResultRecord):
    instrument_id: str
    venue_id: str
    trading_day: date
    profile_id: str
    profile_version: str
    compiled_rules_fingerprint: str
    reference_fingerprint: str
    runtime_mode: str
    schema_version: str = "1"


@dataclass(frozen=True, slots=True, kw_only=True)
class OnlyPositionResultRecord(OnlySequencedResultRecord):
    ts_event: datetime
    trading_day: date
    runtime_id: str
    cluster_id: str | None
    strategy_id: str | None
    account_id: str
    instrument_id: str
    total_quantity: Decimal
    available_quantity: Decimal
    frozen_quantity: Decimal
    average_price: Decimal | None
    mark_price: Decimal | None
    market_value: Decimal | None
    realized_pnl: Decimal
    unrealized_pnl: Decimal | None
    position_side: str = "LONG"

    def __post_init__(self) -> None:
        OnlySequencedResultRecord.__post_init__(self)
        only_require_utc(self.ts_event, "position ts_event")
        if min(self.total_quantity, self.available_quantity, self.frozen_quantity) < 0:
            raise ValueError("position quantities cannot be negative")


@dataclass(frozen=True, slots=True, kw_only=True)
class OnlyAccountResultRecord(OnlySequencedResultRecord):
    ts_event: datetime
    trading_day: date
    runtime_id: str
    account_id: str
    currency: str
    cash: Decimal
    frozen_cash: Decimal
    market_value: Decimal | None
    equity: Decimal | None
    realized_pnl: Decimal
    unrealized_pnl: Decimal | None
    commission: Decimal
    fees: Decimal
    reserved_margin: Decimal = Decimal(0)
    occupied_margin: Decimal = Decimal(0)
    released_margin: Decimal = Decimal(0)
    available_margin: Decimal = Decimal(0)

    def __post_init__(self) -> None:
        OnlySequencedResultRecord.__post_init__(self)
        only_require_utc(self.ts_event, "account ts_event")
        if self.frozen_cash < 0 or self.commission < 0 or self.fees < 0:
            raise ValueError("account frozen cash and fees cannot be negative")


@dataclass(frozen=True, slots=True, kw_only=True)
class OnlyEquityResultRecord(OnlySequencedResultRecord):
    ts_event: datetime
    trading_day: date
    runtime_id: str
    account_id: str
    cluster_id: str | None
    currency: str
    cash: Decimal
    market_value: Decimal | None
    equity: Decimal | None
    realized_pnl: Decimal
    unrealized_pnl: Decimal | None
    commission: Decimal
    fees: Decimal
    gross_exposure: Decimal | None
    net_exposure: Decimal | None
    position_count: int
    complete: bool
    snapshot_phase: str = "POST_BAR_PROCESSING"

    def __post_init__(self) -> None:
        OnlySequencedResultRecord.__post_init__(self)
        only_require_utc(self.ts_event, "equity ts_event")
        if self.position_count < 0:
            raise ValueError("position_count cannot be negative")
        if self.complete and (self.market_value is None or self.equity is None):
            raise ValueError("complete equity record requires market value and equity")


@dataclass(frozen=True, slots=True)
class OnlyBacktestFacts:
    signals: tuple[OnlySignalResultRecord, ...] = ()
    order_requests: tuple[OnlyOrderRequestResultRecord, ...] = ()
    orders: tuple[OnlyOrderResultRecord, ...] = ()
    executions: tuple[OnlyExecutionResultRecord, ...] = ()
    positions: tuple[OnlyPositionResultRecord, ...] = ()
    accounts: tuple[OnlyAccountResultRecord, ...] = ()
    equity: tuple[OnlyEquityResultRecord, ...] = ()
    settlements: tuple[OnlySettlementResultRecord, ...] = ()
    margin: tuple[OnlyMarginResultRecord, ...] = ()
    fees: tuple[OnlyFeeResultRecord, ...] = ()
    market_rule_decisions: tuple[OnlyMarketRuleDecisionResultRecord, ...] = ()
    profile_timeline: tuple[OnlyProfileTimelineResultRecord, ...] = ()
    compiled_market_rules: tuple[OnlyCompiledMarketRuleResultRecord, ...] = ()

    def __post_init__(self) -> None:
        for name in (
            "signals",
            "order_requests",
            "orders",
            "executions",
            "positions",
            "accounts",
            "equity",
            "settlements",
            "margin",
            "fees",
            "market_rule_decisions",
            "profile_timeline",
            "compiled_market_rules",
        ):
            records = tuple(getattr(self, name))
            if tuple(sorted(records, key=lambda item: item.sequence)) != records:
                raise ValueError(f"{name} must be ordered by stable sequence")
            object.__setattr__(self, name, records)
