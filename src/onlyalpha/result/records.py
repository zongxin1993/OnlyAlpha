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
from typing import ClassVar

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
    fee_application_id: str | None = None
    market_fee_pack_id: str | None = None
    market_fee_pack_version: str | None = None
    market_fee_pack_fingerprint: str | None = None
    broker_fee_contract_id: str | None = None
    broker_fee_contract_version: str | None = None
    broker_fee_contract_broker_id: str | None = None
    broker_fee_contract_account_scope: str | None = None
    broker_fee_contract_fingerprint: str | None = None
    fee_binding_fingerprint: str | None = None
    fee_scope_fingerprint: str | None = None
    fee_resolution_fingerprint: str | None = None
    fee_total_charges: Decimal = Decimal(0)
    fee_total_rebates: Decimal = Decimal(0)
    fee_signed_cash_effect: Decimal = Decimal(0)
    market_fee_schedule_ids: tuple[str, ...] = ()
    market_fee_schedule_versions: tuple[str, ...] = ()
    market_fee_schedule_fingerprints: tuple[str, ...] = ()
    broker_fee_schedule_ids: tuple[str, ...] = ()
    broker_fee_schedule_versions: tuple[str, ...] = ()
    broker_fee_schedule_fingerprints: tuple[str, ...] = ()
    settlement_instruction_id: str | None = None
    settlement_status: str | None = None
    margin_instruction_id: str | None = None
    margin_action: str | None = None
    margin_amount: Decimal | None = None
    liquidity_side: str = "UNKNOWN"
    fee_breakdown: Mapping[str, Decimal] = field(default_factory=dict)
    liquidity: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        OnlySequencedResultRecord.__post_init__(self)
        only_require_utc(self.ts_event, "execution ts_event")
        if self.quantity <= 0 or self.price <= 0:
            raise ValueError("execution price and quantity must be positive")
        if min(self.turnover, self.commission, self.fees, self.fee_total_charges, self.fee_total_rebates) < 0:
            raise ValueError("execution turnover and fees cannot be negative")
        if self.fee_signed_cash_effect != self.fee_total_rebates - self.fee_total_charges:
            raise ValueError("execution fee signed cash effect is inconsistent")
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
class OnlySettlementInstructionResultRecord(OnlySequencedResultRecord):
    instruction_id: str
    runtime_id: str
    account_id: str
    cluster_id: str
    instrument_id: str
    order_id: str
    trade_id: str
    position_id: str
    position_cycle: int
    allocation_id: str
    allocation_cycle: int
    side: str
    quantity: Decimal
    gross_notional: Decimal
    net_cash_flow: Decimal
    trading_day: date
    asset_trade_available_on: date
    cash_trade_available_on: date
    cash_withdrawable_on: date
    legal_settlement_on: date
    policy_id: str
    compiled_rule_fingerprint: str
    reference_fingerprint: str
    status: str
    version: int


@dataclass(frozen=True, slots=True, kw_only=True)
class OnlySettlementMaturityResultRecord(OnlySequencedResultRecord):
    maturity_identity: str
    instruction_id: str
    runtime_id: str
    account_id: str
    effective_on: date
    transitions_json: str
    asset_quantity_delta: Decimal
    cash_withdrawable_delta: Decimal
    runtime_sequence: int
    transaction_id: str
    projection_ready: bool


@dataclass(frozen=True, slots=True, kw_only=True)
class OnlyRuntimeTransactionResultRecord(OnlySequencedResultRecord):
    runtime_sequence: int
    transaction_id: str
    operation_kind: str
    operation_identity: str
    runtime_id: str
    account_id: str | None
    effective_time: datetime
    projection_ready: bool

    def __post_init__(self) -> None:
        OnlySequencedResultRecord.__post_init__(self)
        only_require_utc(self.effective_time, "Runtime transaction effective_time")


@dataclass(frozen=True, slots=True, kw_only=True)
class OnlyExternalFeeEvidenceResultRecord(OnlySequencedResultRecord):
    evidence_id: str
    broker_id: str
    account_id: str
    scope: str
    mode: str
    external_reference: str
    report_version: str
    revision_sequence: int
    supersedes_evidence_id: str
    scope_fingerprint: str
    content_fingerprint: str
    reported_total: Decimal | None
    currency: str
    effective_at: datetime
    received_at: datetime


@dataclass(frozen=True, slots=True, kw_only=True)
class OnlyFeeReconciliationResultRecord(OnlySequencedResultRecord):
    reconciliation_id: str
    evidence_id: str
    evidence_family_fingerprint: str
    scope: str
    local_model_amount: Decimal | None
    prior_adjustments: Decimal
    current_effective_amount: Decimal | None
    reported_authoritative_amount: Decimal | None
    difference: Decimal | None
    currency: str
    reason: str
    status: str
    adjustment_id: str
    policy_id: str
    policy_version: str
    policy_fingerprint: str
    local_facts_fingerprint: str
    prior_adjustments_fingerprint: str
    component_rows_json: str
    resolves_blocker_id: str


@dataclass(frozen=True, slots=True, kw_only=True)
class OnlyFeeAdjustmentResultRecord(OnlySequencedResultRecord):
    adjustment_id: str
    reconciliation_id: str
    evidence_id: str
    account_id: str
    cluster_id: str
    direction: str
    amount: Decimal
    currency: str
    reason: str
    component_id: str
    component_fee_type: str
    component_authority: str
    policy_fingerprint: str


@dataclass(frozen=True, slots=True, kw_only=True)
class OnlyUnallocatedExternalFeeResultRecord(OnlySequencedResultRecord):
    account_id: str
    cumulative_charges: Decimal
    cumulative_refunds: Decimal
    currency: str
    version: int


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
    trading_day: date | None = None
    profile_version: str | None = None
    side: str | None = None
    quantity: Decimal | None = None
    price: Decimal | None = None
    trading_phase: str | None = None
    previous_close: Decimal | None = None
    tick_size: Decimal | None = None
    limit_rate: Decimal | None = None
    lower_limit: Decimal | None = None
    upper_limit: Decimal | None = None
    quantity_policy: str | None = None
    reference_fingerprint: str | None = None
    evaluations: str = "[]"

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
    order_reserved_cash: Decimal
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
        if self.order_reserved_cash < 0 or self.commission < 0 or self.fees < 0:
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
    schema_version: ClassVar[int] = 5

    signals: tuple[OnlySignalResultRecord, ...] = ()
    order_requests: tuple[OnlyOrderRequestResultRecord, ...] = ()
    orders: tuple[OnlyOrderResultRecord, ...] = ()
    executions: tuple[OnlyExecutionResultRecord, ...] = ()
    positions: tuple[OnlyPositionResultRecord, ...] = ()
    accounts: tuple[OnlyAccountResultRecord, ...] = ()
    equity: tuple[OnlyEquityResultRecord, ...] = ()
    settlements: tuple[OnlySettlementResultRecord, ...] = ()
    settlement_instructions: tuple[OnlySettlementInstructionResultRecord, ...] = ()
    settlement_maturities: tuple[OnlySettlementMaturityResultRecord, ...] = ()
    runtime_transactions: tuple[OnlyRuntimeTransactionResultRecord, ...] = ()
    margin: tuple[OnlyMarginResultRecord, ...] = ()
    fees: tuple[OnlyFeeResultRecord, ...] = ()
    external_fee_evidence: tuple[OnlyExternalFeeEvidenceResultRecord, ...] = ()
    fee_reconciliations: tuple[OnlyFeeReconciliationResultRecord, ...] = ()
    fee_adjustments: tuple[OnlyFeeAdjustmentResultRecord, ...] = ()
    unallocated_external_fees: tuple[OnlyUnallocatedExternalFeeResultRecord, ...] = ()
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
            "settlement_instructions",
            "settlement_maturities",
            "runtime_transactions",
            "margin",
            "fees",
            "external_fee_evidence",
            "fee_reconciliations",
            "fee_adjustments",
            "unallocated_external_fees",
            "market_rule_decisions",
            "profile_timeline",
            "compiled_market_rules",
        ):
            records = tuple(getattr(self, name))
            if tuple(sorted(records, key=lambda item: item.sequence)) != records:
                raise ValueError(f"{name} must be ordered by stable sequence")
            object.__setattr__(self, name, records)
