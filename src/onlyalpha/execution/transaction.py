"""Immutable prepared and committed execution transaction domain models."""

from __future__ import annotations

from dataclasses import dataclass, fields
from decimal import Decimal

from onlyalpha.broker.identifiers import OnlyBrokerGatewayId, OnlyBrokerUpdateId
from onlyalpha.domain.base import OnlyDomainModel
from onlyalpha.domain.enums import OnlyLiquiditySide, OnlyOffset, OnlyOrderSide, OnlyOrderStatus, OnlyOrderType
from onlyalpha.domain.identifiers import (
    OnlyAccountId,
    OnlyClusterId,
    OnlyInstrumentId,
    OnlyOrderId,
    OnlyRuntimeId,
    OnlyTradeId,
)
from onlyalpha.domain.time import OnlyTimestamp, OnlyTradingDay
from onlyalpha.domain.value import OnlyCurrency, OnlyMoney, OnlyMultiplier, OnlyPrice, OnlyQuantity
from onlyalpha.event.model import OnlyEvent
from onlyalpha.fee.models import OnlyBrokerFeeReportingMode, OnlyFeeBreakdown
from onlyalpha.market.models import OnlyPositionEffect
from onlyalpha.position.enums import OnlyPositionMode, OnlyPositionSide
from onlyalpha.strategy.identifiers import OnlyStrategyId

from .committed import OnlyCommittedExecutionFact
from .projection import (
    OnlyExecutionProjection,
    OnlyExecutionProjectionComponent,
    OnlyExecutionProjectionOrder,
)


@dataclass(frozen=True, slots=True, kw_only=True)
class OnlyCommittedExecutionFactDraft(OnlyDomainModel):
    """Complete committed-fact authority before Store-owned sequence and time are assigned."""

    schema_version = 1

    execution_id: str
    trade_id: OnlyTradeId
    venue_trade_id: str | None
    order_id: OnlyOrderId
    client_order_id: str
    request_id: str
    broker_update_id: OnlyBrokerUpdateId
    runtime_id: OnlyRuntimeId
    gateway_id: OnlyBrokerGatewayId
    account_id: OnlyAccountId
    cluster_id: OnlyClusterId
    strategy_id: OnlyStrategyId
    instrument_id: OnlyInstrumentId
    venue_id: str
    source_sequence: int
    processing_sequence: int
    correlation_id: str
    causation_id: str
    external_event_id: str | None
    ts_event: OnlyTimestamp
    ts_init: OnlyTimestamp
    trading_day: OnlyTradingDay
    order_side: OnlyOrderSide
    order_type: OnlyOrderType
    offset: OnlyOffset
    position_side: OnlyPositionSide
    position_effect: OnlyPositionEffect
    position_mode: OnlyPositionMode
    liquidity_side: OnlyLiquiditySide
    fill_quantity: OnlyQuantity
    fill_price: OnlyPrice
    cumulative_filled_quantity: OnlyQuantity
    remaining_quantity: OnlyQuantity
    order_status_after: OnlyOrderStatus
    currency: OnlyCurrency
    contract_multiplier: OnlyMultiplier
    gross_notional: OnlyMoney
    settled_notional: OnlyMoney
    authoritative_fee_total: OnlyMoney
    market_fee: OnlyMoney
    broker_fee: OnlyMoney
    tax: OnlyMoney
    commission: OnlyMoney
    other_fee: OnlyMoney
    reported_broker_fee: OnlyMoney | None
    fee_reporting_mode: OnlyBrokerFeeReportingMode
    reference_price: OnlyPrice | None
    slippage: OnlyMoney | None
    realized_pnl_delta: OnlyMoney
    cash_delta: OnlyMoney
    fee_instruction_id: str
    fee_authority: str
    fee_status: str
    market_fee_schedule_ids: tuple[str, ...]
    market_fee_schedule_versions: tuple[str, ...]
    broker_fee_schedule_ids: tuple[str, ...]
    broker_fee_schedule_versions: tuple[str, ...]
    fee_breakdown: OnlyFeeBreakdown
    market_profile_id: str
    market_profile_version: str
    compiled_rule_fingerprint: str
    reference_fingerprint: str
    trade_instruction_id: str
    settlement_instruction_id: str
    settlement_status: str
    asset_available_on: OnlyTradingDay
    cash_available_on: OnlyTradingDay
    legal_settlement_date: OnlyTradingDay
    margin_instruction_id: str | None
    margin_action: str | None
    margin_currency: OnlyCurrency | None
    margin_amount: OnlyMoney | None
    reserved_margin_delta: OnlyMoney | None
    occupied_margin_delta: OnlyMoney | None
    released_margin_delta: OnlyMoney | None
    maintenance_margin_after: OnlyMoney | None
    position_quantity_delta: Decimal
    position_realized_pnl_delta: OnlyMoney
    allocation_quantity_delta: Decimal
    account_cash_delta: OnlyMoney
    account_fee_delta: OnlyMoney
    account_realized_pnl_delta: OnlyMoney
    ledger_cash_delta: OnlyMoney
    ledger_fee_delta: OnlyMoney
    ledger_realized_pnl_delta: OnlyMoney

    def __post_init__(self) -> None:
        if not self.execution_id or self.source_sequence < 0 or self.processing_sequence < 0:
            raise ValueError("execution fact draft requires stable identity and non-negative sequences")
        if self.fill_quantity.value <= 0 or self.fill_price.value <= 0:
            raise ValueError("execution fact draft requires positive price and quantity")
        if self.ts_init < self.ts_event:
            raise ValueError("execution fact draft timestamps violate causal ordering")
        if self.authoritative_fee_total != self.fee_breakdown.total:
            raise ValueError("execution fact draft fee total must equal authoritative breakdown")

    @classmethod
    def from_committed(cls, fact: OnlyCommittedExecutionFact) -> OnlyCommittedExecutionFactDraft:
        names = {item.name for item in fields(cls)}
        return cls(**{name: getattr(fact, name) for name in names})

    def finalize(self, execution_sequence: int, committed_at: OnlyTimestamp) -> OnlyCommittedExecutionFact:
        values = {item.name: getattr(self, item.name) for item in fields(self)}
        return OnlyCommittedExecutionFact(
            **values,
            execution_sequence=execution_sequence,
            ts_committed=committed_at,
        )


@dataclass(frozen=True, slots=True)
class OnlyExecutionPrecondition(OnlyDomainModel):
    component: OnlyExecutionProjectionComponent
    entity_key: str
    expected_version: int
    expected_state_hash: str | None = None

    def __post_init__(self) -> None:
        if not self.entity_key.strip() or self.expected_version < 0:
            raise ValueError("execution precondition requires entity and non-negative version")
        if self.expected_state_hash is not None and len(self.expected_state_hash) != 64:
            raise ValueError("expected_state_hash must be a SHA-256 digest")


@dataclass(frozen=True, slots=True)
class OnlyPreparedExecutionTransaction:
    schema_version = 1

    transaction_id: str
    runtime_id: OnlyRuntimeId
    gateway_id: OnlyBrokerGatewayId
    account_id: OnlyAccountId
    broker_update_id: OnlyBrokerUpdateId
    trade_id: OnlyTradeId
    source_sequence: int
    prepared_at: OnlyTimestamp
    fact_draft: OnlyCommittedExecutionFactDraft
    projections: tuple[OnlyExecutionProjection, ...]
    outbox_events: tuple[OnlyEvent, ...]
    preconditions: tuple[OnlyExecutionPrecondition, ...]
    stable_hash: str = ""

    def __post_init__(self) -> None:
        if not self.transaction_id.strip() or self.source_sequence < 0:
            raise ValueError("prepared transaction requires identity and non-negative source sequence")
        scope = self.fact_draft
        if (
            scope.runtime_id != self.runtime_id
            or scope.gateway_id != self.gateway_id
            or scope.account_id != self.account_id
            or scope.broker_update_id != self.broker_update_id
            or scope.trade_id != self.trade_id
            or scope.source_sequence != self.source_sequence
        ):
            raise ValueError("prepared transaction and fact draft scopes disagree")
        self._validate_projections()
        if any(event.runtime_id != self.runtime_id for event in self.outbox_events):
            raise ValueError("prepared transaction event belongs to another Runtime")
        from .codec import only_prepared_execution_transaction_hash

        calculated_hash = only_prepared_execution_transaction_hash(self, verify=False)
        if not self.stable_hash:
            object.__setattr__(self, "stable_hash", calculated_hash)
        elif self.stable_hash != calculated_hash:
            raise ValueError("prepared transaction stable hash mismatch")

    def _validate_projections(self) -> None:
        from .codec import only_execution_projection_payload_hash

        identities = tuple(item.identity for item in self.projections)
        if tuple(item.projection_sequence for item in identities) != tuple(range(1, len(identities) + 1)):
            raise ValueError("projection_sequence must be contiguous from one")
        orders = tuple(OnlyExecutionProjectionOrder[item.component.name] for item in identities)
        if tuple(sorted(orders)) != orders:
            raise ValueError("execution projections violate the fixed component order")
        keys = tuple((item.component, item.entity_key) for item in identities)
        if len(keys) != len(set(keys)):
            raise ValueError("execution transaction contains duplicate component/entity projection")
        if any(item.identity.payload_hash != only_execution_projection_payload_hash(item) for item in self.projections):
            raise ValueError("execution projection payload hash mismatch")


@dataclass(frozen=True, slots=True)
class OnlyCommittedExecutionTransaction:
    schema_version = 1

    runtime_id: OnlyRuntimeId
    execution_sequence: int
    transaction_id: str
    fact: OnlyCommittedExecutionFact
    projections: tuple[OnlyExecutionProjection, ...]
    outbox_events: tuple[OnlyEvent, ...]
    committed_at: OnlyTimestamp
    prepared_hash: str
    committed_hash: str
    projection_ready: bool = False
    projected_at: OnlyTimestamp | None = None
    projection_error: str | None = None
    projection_failed_at: OnlyTimestamp | None = None

    def __post_init__(self) -> None:
        if (
            not self.transaction_id.strip()
            or self.execution_sequence < 1
            or self.fact.execution_sequence != self.execution_sequence
        ):
            raise ValueError("committed transaction and fact sequence must agree and be positive")
        if self.fact.runtime_id != self.runtime_id or self.fact.ts_committed != self.committed_at:
            raise ValueError("committed transaction and fact scope/time disagree")
        if self.projection_ready and (self.projected_at is None or self.projection_error is not None):
            raise ValueError("projection-ready transaction requires projected_at and no error")
        if self.projection_ready and self.projection_failed_at is not None:
            raise ValueError("projection-ready transaction cannot retain failure time")
        if len(self.prepared_hash) != 64 or (self.committed_hash and len(self.committed_hash) != 64):
            raise ValueError("committed transaction hashes must be SHA-256 digests")


@dataclass(frozen=True, slots=True)
class OnlyExecutionTransactionCommitResult:
    transaction: OnlyCommittedExecutionTransaction
    inserted: bool


__all__ = [
    "OnlyCommittedExecutionFactDraft",
    "OnlyCommittedExecutionTransaction",
    "OnlyExecutionPrecondition",
    "OnlyExecutionTransactionCommitResult",
    "OnlyPreparedExecutionTransaction",
]
