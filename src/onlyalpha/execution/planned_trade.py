"""Normalized immutable Trade authority shared by all pure reducers."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from onlyalpha.broker.identifiers import OnlyBrokerGatewayId, OnlyBrokerUpdateId
from onlyalpha.domain.enums import OnlyLiquiditySide, OnlyOffset, OnlyOrderSide, OnlyOrderType
from onlyalpha.domain.execution import OnlyOrderFill
from onlyalpha.domain.identifiers import (
    OnlyAccountId,
    OnlyClusterId,
    OnlyInstrumentId,
    OnlyOrderId,
    OnlyRuntimeId,
    OnlyTradeId,
)
from onlyalpha.domain.time import OnlyTimestamp, OnlyTradingDay
from onlyalpha.domain.value import OnlyMoney, OnlyMultiplier, OnlyPrice, OnlyQuantity
from onlyalpha.fee.application import OnlyFeeApplicationInstruction
from onlyalpha.market.models import OnlyPositionEffect
from onlyalpha.position.enums import OnlyPositionMode, OnlyPositionSide, OnlySettlementBucket


@dataclass(frozen=True, slots=True)
class OnlyPlannedTrade:
    runtime_id: OnlyRuntimeId
    gateway_id: OnlyBrokerGatewayId
    account_id: OnlyAccountId
    cluster_id: OnlyClusterId
    order_id: OnlyOrderId
    trade_id: OnlyTradeId
    broker_update_id: OnlyBrokerUpdateId
    instrument_id: OnlyInstrumentId
    side: OnlyOrderSide
    order_type: OnlyOrderType
    offset: OnlyOffset
    position_side: OnlyPositionSide
    position_effect: OnlyPositionEffect
    position_mode: OnlyPositionMode
    settlement_bucket: OnlySettlementBucket
    quantity: OnlyQuantity
    price: OnlyPrice
    multiplier: OnlyMultiplier
    gross_notional: OnlyMoney
    settled_notional: OnlyMoney
    fee_application: OnlyFeeApplicationInstruction | None
    fill: OnlyOrderFill
    liquidity_side: OnlyLiquiditySide
    ts_event: OnlyTimestamp
    ts_init: OnlyTimestamp
    trading_day: OnlyTradingDay
    source_sequence: int
    stable_order: tuple[int, int, str]

    @property
    def fee_charges(self) -> OnlyMoney:
        if self.fee_application is None:
            return OnlyMoney(Decimal(0), self.gross_notional.currency)
        return self.fee_application.total_charges

    @property
    def fee_rebates(self) -> OnlyMoney:
        if self.fee_application is None:
            return OnlyMoney(Decimal(0), self.gross_notional.currency)
        return self.fee_application.total_rebates


__all__ = ["OnlyPlannedTrade"]
