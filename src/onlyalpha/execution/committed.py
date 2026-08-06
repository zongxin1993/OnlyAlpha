"""Immutable Runtime-local authority for successfully committed executions."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Self

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
from onlyalpha.fee.application import OnlyFeeApplicationInstruction
from onlyalpha.market.models import OnlyPositionEffect
from onlyalpha.position.enums import OnlyPositionMode, OnlyPositionSide
from onlyalpha.strategy.identifiers import OnlyStrategyId


@dataclass(frozen=True, slots=True, kw_only=True)
class OnlyCommittedExecutionFact(OnlyDomainModel):
    """Self-contained result of one fully committed local execution transaction."""

    schema_version = 3

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
    fill_identity: str
    fill_payload_fingerprint: str
    fill_index: int
    fill_count_after: int
    terminal_fill: bool
    cumulative_price_quantity_after: Decimal
    currency: OnlyCurrency
    contract_multiplier: OnlyMultiplier
    gross_notional: OnlyMoney
    settled_notional: OnlyMoney
    fee_total_charges: OnlyMoney
    fee_total_rebates: OnlyMoney
    fee_signed_cash_effect: Decimal
    market_fee: OnlyMoney
    broker_fee: OnlyMoney
    tax: OnlyMoney
    commission: OnlyMoney
    other_fee: OnlyMoney
    reference_price: OnlyPrice | None
    slippage: OnlyMoney | None
    realized_pnl_delta: OnlyMoney
    cash_delta: OnlyMoney
    fee_application_id: str
    fee_authority: str
    fee_status: str
    market_fee_schedule_ids: tuple[str, ...]
    market_fee_schedule_versions: tuple[str, ...]
    broker_fee_schedule_ids: tuple[str, ...]
    broker_fee_schedule_versions: tuple[str, ...]
    fee_application: OnlyFeeApplicationInstruction
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
    incremental_fee_charges: OnlyMoney
    incremental_fee_rebates: OnlyMoney
    order_cumulative_fee_charges_after: OnlyMoney
    order_cumulative_fee_rebates_after: OnlyMoney
    account_reservation_consumed_delta: OnlyMoney
    account_reservation_released_delta: OnlyMoney
    strategy_reservation_consumed_delta: OnlyMoney
    strategy_reservation_released_delta: OnlyMoney
    risk_reservation_quantity_consumed_delta: OnlyQuantity
    risk_reservation_notional_consumed_delta: OnlyMoney
    position_cumulative_open_price_quantity_after: Decimal
    allocation_cumulative_open_price_quantity_after: Decimal
    position_quantity_before: Decimal
    position_quantity_after: Decimal
    allocation_quantity_before: Decimal
    allocation_quantity_after: Decimal
    position_cumulative_open_price_quantity_before: Decimal
    allocation_cumulative_open_price_quantity_before: Decimal
    released_open_price_quantity: Decimal
    gross_cash_inflow: OnlyMoney
    net_cash_inflow: OnlyMoney
    allocation_realized_pnl_delta: OnlyMoney
    position_reservation_consumed_delta: OnlyQuantity
    position_closed: bool
    allocation_closed: bool

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
        if (
            self.fee_total_charges != self.fee_application.total_charges
            or self.fee_total_rebates != self.fee_application.total_rebates
            or self.fee_signed_cash_effect != self.fee_application.signed_cash_effect
        ):
            raise ValueError("committed execution Fee Application totals disagree")
        if self.ts_committed < self.ts_init or self.ts_init < self.ts_event:
            raise ValueError("committed execution timestamps violate causal ordering")
        if self.position_realized_pnl_delta != self.realized_pnl_delta:
            raise ValueError("position and execution realized PnL deltas disagree")
        if self.fill_index < 1 or self.fill_count_after != self.fill_index:
            raise ValueError("committed execution requires a contiguous per-Order fill index")
        if self.terminal_fill != (self.remaining_quantity.value == 0):
            raise ValueError("terminal fill must agree with remaining quantity")
        if self.terminal_fill and self.order_status_after is not OnlyOrderStatus.FILLED:
            raise ValueError("terminal fill requires FILLED Order status")
        if not self.terminal_fill and self.order_status_after not in {
            OnlyOrderStatus.PARTIALLY_FILLED,
            OnlyOrderStatus.PENDING_CANCEL,
        }:
            raise ValueError("non-terminal fill requires an open partial Order status")
        if self.cumulative_price_quantity_after <= 0:
            raise ValueError("committed execution requires positive cumulative price quantity")
        if not self.fill_identity.startswith("EFILL-") or len(self.fill_payload_fingerprint) != 64:
            raise ValueError("committed execution requires durable Fill identity authority")
        if (
            min(
                self.incremental_fee_charges.amount,
                self.incremental_fee_rebates.amount,
                self.account_reservation_consumed_delta.amount,
                self.account_reservation_released_delta.amount,
                self.strategy_reservation_consumed_delta.amount,
                self.strategy_reservation_released_delta.amount,
                self.risk_reservation_quantity_consumed_delta.value,
                self.risk_reservation_notional_consumed_delta.amount,
            )
            < 0
        ):
            raise ValueError("committed execution incremental accounting deltas cannot be negative")
        if not self.terminal_fill and (
            self.account_reservation_released_delta.amount or self.strategy_reservation_released_delta.amount
        ):
            raise ValueError("non-terminal committed execution cannot release cash Reservation")
        if (
            self.position_quantity_after - self.position_quantity_before != self.position_quantity_delta
            or self.allocation_quantity_after - self.allocation_quantity_before != self.allocation_quantity_delta
            or self.allocation_realized_pnl_delta != self.realized_pnl_delta
            or self.position_closed != (self.position_quantity_after == 0)
            or self.allocation_closed != (self.allocation_quantity_after == 0)
        ):
            raise ValueError("committed execution Close authority is inconsistent")

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> Self:
        return super(OnlyCommittedExecutionFact, cls).from_dict(payload)

    @property
    def stable_order(self) -> tuple[int, int, int, str]:
        return self.execution_sequence, self.source_sequence, self.ts_event.unix_nanos, self.execution_id

    @property
    def stable_hash(self) -> str:
        return hashlib.sha256(self.to_json().encode("utf-8")).hexdigest()


def _money(amount: Decimal, currency: OnlyCurrency) -> OnlyMoney:
    quantum = Decimal(1).scaleb(-currency.precision)
    return OnlyMoney(amount.quantize(quantum), currency)


__all__ = ["OnlyCommittedExecutionFact"]
