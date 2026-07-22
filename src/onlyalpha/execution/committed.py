"""Immutable Runtime-local authority for successfully committed executions."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from decimal import Decimal

from onlyalpha.account.models import OnlyAccountMutationResult
from onlyalpha.broker.identifiers import OnlyBrokerGatewayId, OnlyBrokerUpdateId
from onlyalpha.broker.updates import OnlyBrokerTradeUpdate
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
from onlyalpha.fee.manager import OnlyFeeRecord
from onlyalpha.fee.models import (
    OnlyBrokerFeeReportingMode,
    OnlyFeeBreakdown,
    OnlyFeeComponent,
    OnlyFeeInstruction,
    OnlyFeeType,
)
from onlyalpha.margin.manager import OnlyMarginRecord
from onlyalpha.market.models import OnlyPositionEffect
from onlyalpha.market.runtime_rules import OnlyMarginInstruction, OnlyTradeApplicationInstruction
from onlyalpha.order.results import OnlyOrderMutationResult
from onlyalpha.position.enums import OnlyPositionMode, OnlyPositionSide
from onlyalpha.position.models import (
    OnlyPositionAllocationSnapshot,
    OnlyPositionMutationResult,
    OnlyPositionTrade,
)
from onlyalpha.settlement.manager import OnlySettlementRecord
from onlyalpha.strategy.identifiers import OnlyStrategyId
from onlyalpha.strategy_ledger.models import OnlyStrategyLedgerMutationResult

from .scope import OnlyExecutionPositionScope


@dataclass(frozen=True, slots=True, kw_only=True)
class OnlyCommittedExecutionFact(OnlyDomainModel):
    """Self-contained result of one fully committed local execution transaction."""

    schema_version = 2

    execution_id: str
    execution_sequence: int
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
    ts_committed: OnlyTimestamp
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
        if not self.execution_id or self.execution_sequence < 1:
            raise ValueError("committed execution requires a stable identity and positive sequence")
        if self.fill_quantity.value <= 0 or self.fill_price.value <= 0:
            raise ValueError("committed execution requires positive price and quantity")
        expected = _money(
            self.fill_price.value * self.fill_quantity.value * self.contract_multiplier.value,
            self.currency,
        )
        if self.gross_notional != expected:
            raise ValueError("committed execution gross notional must include contract multiplier")
        if self.authoritative_fee_total != self.fee_breakdown.total:
            raise ValueError("committed execution fee total must equal authoritative breakdown")
        if self.ts_committed < self.ts_init or self.ts_init < self.ts_event:
            raise ValueError("committed execution timestamps violate causal ordering")
        if self.position_realized_pnl_delta != self.realized_pnl_delta:
            raise ValueError("position and execution realized PnL deltas disagree")

    @property
    def stable_order(self) -> tuple[int, int, int, str]:
        return self.execution_sequence, self.source_sequence, self.ts_event.unix_nanos, self.execution_id

    @property
    def stable_hash(self) -> str:
        return hashlib.sha256(self.to_json().encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class OnlyExecutionCommitContext:
    update: OnlyBrokerTradeUpdate
    processing_sequence: int
    trading_day: OnlyTradingDay
    order_mutation: OnlyOrderMutationResult
    position_scope: OnlyExecutionPositionScope
    position_trade: OnlyPositionTrade
    position_mutation: OnlyPositionMutationResult
    allocation_before: OnlyPositionAllocationSnapshot | None
    allocation_after: OnlyPositionAllocationSnapshot | None
    account_mutation: OnlyAccountMutationResult
    ledger_mutation: OnlyStrategyLedgerMutationResult
    fee_instruction: OnlyFeeInstruction
    fee_records: tuple[OnlyFeeRecord, ...]
    trade_instruction: OnlyTradeApplicationInstruction
    settlement_record: OnlySettlementRecord | None
    margin_record: OnlyMarginRecord | None
    margin_occupied_before: Decimal | None


class OnlyCommittedExecutionBuilder:
    """Projects already-applied transaction values; it never resolves rules or mutates state."""

    def build(
        self,
        context: OnlyExecutionCommitContext,
        *,
        execution_sequence: int,
        strategy_id: OnlyStrategyId,
        ts_committed: OnlyTimestamp,
    ) -> OnlyCommittedExecutionFact:
        update = context.update
        fill = update.fill
        order = context.order_mutation.snapshot
        trade = context.position_trade
        fee = context.fee_instruction
        rule = context.trade_instruction
        identity = rule.compiled_identity
        currency = fee.fee_breakdown.currency
        notional = _money(fill.price.value * fill.quantity.value * trade.multiplier.value, currency)
        zero = OnlyMoney(Decimal(0), currency)
        components = fee.fee_breakdown.components
        market_fee = _sum_fee(
            currency,
            tuple(item for item in components if item.authority.value != "BROKER"),
        )
        broker_fee = _sum_fee(currency, tuple(item for item in components if item.authority.value == "BROKER"))
        tax = _sum_fee(currency, tuple(item for item in components if item.fee_type is OnlyFeeType.STAMP_DUTY))
        commission = _sum_fee(
            currency,
            tuple(item for item in components if item.fee_type is OnlyFeeType.BROKER_COMMISSION),
        )
        classified = tax.amount + commission.amount
        other_fee = OnlyMoney(max(fee.fee_breakdown.total.amount - classified, Decimal(0)), currency)
        account_before = context.account_mutation.before
        account_after = context.account_mutation.after
        if account_before is None:
            raise ValueError("committed execution requires Account before/after mutation snapshots")
        position_before = context.position_mutation.before
        position_after = context.position_mutation.after
        allocation_before = context.allocation_before
        allocation_after = context.allocation_after
        position_delta = _quantity(position_after) - _quantity(position_before)
        allocation_delta = _allocation_quantity(allocation_after) - _allocation_quantity(allocation_before)
        slippage = None
        if fill.reference_price is not None:
            direction = Decimal(1) if order.side is OnlyOrderSide.BUY else Decimal(-1)
            slippage = _money(
                direction
                * (fill.price.value - fill.reference_price.value)
                * fill.quantity.value
                * trade.multiplier.value,
                currency,
            )
        settlement = rule.settlement_instruction
        margin = rule.margin_instruction
        margin_record = context.margin_record
        reserved_delta: OnlyMoney | None = None
        occupied_delta: OnlyMoney | None = None
        released_delta: OnlyMoney | None = None
        maintenance_after: OnlyMoney | None = None
        margin_amount: OnlyMoney | None = None
        margin_currency: OnlyCurrency | None = None
        if margin is not None:
            if currency.code != margin.currency:
                raise ValueError("margin and execution currencies disagree")
            margin_currency = currency
            margin_amount = _money(margin.amount, margin_currency)
            before_occupied = context.margin_occupied_before or Decimal(0)
            if margin.action == "OCCUPY":
                reserved_delta = _money(-margin.amount, margin_currency)
                occupied_delta = _money(margin.amount, margin_currency)
                released_delta = _money(Decimal(0), margin_currency)
            else:
                released = before_occupied - (Decimal(0) if margin_record is None else margin_record.occupied_after)
                reserved_delta = _money(Decimal(0), margin_currency)
                occupied_delta = _money(-released, margin_currency)
                released_delta = _money(released, margin_currency)
            maintenance_after = _money(
                Decimal(0) if margin_record is None else margin_record.maintenance_required_after,
                margin_currency,
            )
        execution_id = _execution_id(update)
        market_components = tuple(item for item in components if item.authority.value != "BROKER")
        broker_components = tuple(item for item in components if item.authority.value == "BROKER")
        market_schedule_ids = tuple(sorted({item.schedule_id for item in market_components if item.schedule_id}))
        market_schedule_versions = tuple(
            sorted({item.schedule_version for item in market_components if item.schedule_version})
        )
        broker_schedule_ids = tuple(sorted({item.schedule_id for item in broker_components if item.schedule_id}))
        broker_schedule_versions = tuple(
            sorted({item.schedule_version for item in broker_components if item.schedule_version})
        )
        fee_authority = "+".join(sorted({item.authority.value for item in components})) or "NONE"
        settled_notional = notional if rule.cash_instruction.settle_notional else zero
        return OnlyCommittedExecutionFact(
            execution_id=execution_id,
            execution_sequence=execution_sequence,
            trade_id=fill.trade_id,
            venue_trade_id=None if fill.venue_trade_id is None else str(fill.venue_trade_id),
            order_id=order.order_id,
            client_order_id=str(order.client_order_id),
            request_id=str(order.request_id),
            broker_update_id=update.update_id,
            runtime_id=update.runtime_id,
            gateway_id=update.gateway_id,
            account_id=update.account_id,
            cluster_id=order.cluster_id,
            strategy_id=strategy_id,
            instrument_id=order.instrument_id,
            venue_id=identity.venue,
            source_sequence=update.source_sequence,
            processing_sequence=context.processing_sequence,
            correlation_id=update.correlation_id,
            causation_id=update.causation_id,
            external_event_id=fill.external_event_id,
            ts_event=update.ts_event,
            ts_init=update.ts_init,
            ts_committed=ts_committed,
            trading_day=context.trading_day,
            order_side=order.side,
            order_type=order.order_type,
            offset=order.offset,
            position_side=context.position_scope.position_side,
            position_effect=context.position_scope.position_effect,
            position_mode=context.position_scope.position_mode,
            liquidity_side=fill.liquidity_side,
            fill_quantity=fill.quantity,
            fill_price=fill.price,
            cumulative_filled_quantity=order.filled_quantity,
            remaining_quantity=order.remaining_quantity,
            order_status_after=order.status,
            currency=currency,
            contract_multiplier=trade.multiplier,
            gross_notional=notional,
            settled_notional=settled_notional,
            authoritative_fee_total=fee.fee_breakdown.total,
            market_fee=market_fee,
            broker_fee=broker_fee,
            tax=tax,
            commission=commission,
            other_fee=other_fee,
            reported_broker_fee=fill.reported_fee,
            fee_reporting_mode=fill.fee_reporting_mode,
            reference_price=fill.reference_price,
            slippage=slippage,
            realized_pnl_delta=context.position_mutation.realized_pnl_delta,
            cash_delta=account_after.cash.cash_balance - account_before.cash.cash_balance,
            fee_instruction_id=fee.instruction_id,
            fee_authority=fee_authority,
            fee_status=fee.fee_breakdown.status.value,
            market_fee_schedule_ids=market_schedule_ids,
            market_fee_schedule_versions=market_schedule_versions,
            broker_fee_schedule_ids=broker_schedule_ids,
            broker_fee_schedule_versions=broker_schedule_versions,
            fee_breakdown=fee.fee_breakdown,
            market_profile_id=identity.profile_id,
            market_profile_version=identity.profile_version,
            compiled_rule_fingerprint=identity.compiled_rules_fingerprint,
            reference_fingerprint=identity.reference_fingerprint,
            trade_instruction_id=_trade_instruction_id(rule),
            settlement_instruction_id=settlement.instruction_id,
            settlement_status="REGISTERED" if context.settlement_record is None else context.settlement_record.status,
            asset_available_on=settlement.asset_available_on,
            cash_available_on=settlement.cash_trade_available_on,
            legal_settlement_date=settlement.legal_settlement_on,
            margin_instruction_id=None if margin is None else _margin_instruction_id(margin),
            margin_action=None if margin is None else margin.action,
            margin_currency=margin_currency,
            margin_amount=margin_amount,
            reserved_margin_delta=reserved_delta,
            occupied_margin_delta=occupied_delta,
            released_margin_delta=released_delta,
            maintenance_margin_after=maintenance_after,
            position_quantity_delta=position_delta,
            position_realized_pnl_delta=context.position_mutation.realized_pnl_delta,
            allocation_quantity_delta=allocation_delta,
            account_cash_delta=account_after.cash.cash_balance - account_before.cash.cash_balance,
            account_fee_delta=account_after.fees - account_before.fees,
            account_realized_pnl_delta=account_after.realized_pnl - account_before.realized_pnl,
            ledger_cash_delta=context.ledger_mutation.cash_delta,
            ledger_fee_delta=context.ledger_mutation.fee_delta,
            ledger_realized_pnl_delta=context.ledger_mutation.realized_pnl_delta,
        )


def _execution_id(update: OnlyBrokerTradeUpdate) -> str:
    identity = "|".join(
        (
            str(update.runtime_id),
            str(update.gateway_id),
            str(update.account_id),
            str(update.fill.trade_id),
            "" if update.fill.venue_trade_id is None else str(update.fill.venue_trade_id),
        )
    )
    return f"EXEC-{hashlib.sha256(identity.encode('utf-8')).hexdigest()}"


def _trade_instruction_id(instruction: OnlyTradeApplicationInstruction) -> str:
    identity = "|".join(
        (
            instruction.settlement_instruction.instruction_id,
            instruction.compiled_identity.compiled_rules_fingerprint,
            instruction.position_instruction.position_side,
            instruction.position_instruction.position_effect.value,
        )
    )
    return f"TINSTR-{hashlib.sha256(identity.encode('utf-8')).hexdigest()}"


def _margin_instruction_id(instruction: OnlyMarginInstruction) -> str:
    identity = "|".join(
        (
            instruction.action,
            instruction.account_id,
            instruction.instrument_id,
            instruction.currency,
            str(instruction.amount),
            instruction.source_order_id,
            instruction.source_trade_id,
        )
    )
    return f"MINSTR-{hashlib.sha256(identity.encode('utf-8')).hexdigest()}"


def _money(amount: Decimal, currency: OnlyCurrency) -> OnlyMoney:
    quantum = Decimal(1).scaleb(-currency.precision)
    return OnlyMoney(amount.quantize(quantum), currency)


def _sum_fee(currency: OnlyCurrency, components: tuple[OnlyFeeComponent, ...]) -> OnlyMoney:
    return _money(sum((item.amount.amount for item in components), Decimal(0)), currency)


def _quantity(snapshot: object | None) -> Decimal:
    return Decimal(0) if snapshot is None else snapshot.total_quantity.value  # type: ignore[attr-defined]


def _allocation_quantity(snapshot: OnlyPositionAllocationSnapshot | None) -> Decimal:
    return Decimal(0) if snapshot is None else snapshot.total_quantity.value


__all__ = ["OnlyCommittedExecutionBuilder", "OnlyCommittedExecutionFact", "OnlyExecutionCommitContext"]
