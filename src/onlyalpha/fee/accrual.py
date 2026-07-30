"""Immutable per-Order fee accrual authority for incremental Fill accounting."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from onlyalpha.domain.base import OnlyDomainModel
from onlyalpha.domain.identifiers import OnlyAccountId, OnlyClusterId, OnlyOrderId, OnlyRuntimeId, OnlyTradeId
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.domain.value import OnlyCurrency, OnlyMoney, OnlyQuantity
from onlyalpha.fee.models import OnlyFeeAuthority, OnlyFeeCalculationScope, OnlyFeeType


@dataclass(frozen=True, slots=True)
class OnlyOrderFeeComponentAccrual(OnlyDomainModel):
    fee_type: OnlyFeeType
    authority: OnlyFeeAuthority
    source_id: str
    schedule_id: str | None
    schedule_version: str | None
    calculation_scope: OnlyFeeCalculationScope
    cumulative_raw_amount: OnlyMoney
    cumulative_target_amount: OnlyMoney
    cumulative_charged_amount: OnlyMoney

    def __post_init__(self) -> None:
        values = (self.cumulative_raw_amount, self.cumulative_target_amount, self.cumulative_charged_amount)
        if len({item.currency for item in values}) != 1 or min(item.amount for item in values) < 0:
            raise ValueError("Order fee component currency/amount is invalid")
        if not self.source_id:
            raise ValueError("Order fee component source cannot be empty")

    @property
    def key(self) -> tuple[object, ...]:
        return (
            self.fee_type,
            self.authority,
            self.source_id,
            self.schedule_id,
            self.schedule_version,
            self.calculation_scope,
        )


@dataclass(frozen=True, slots=True)
class OnlyOrderFeeAccrualExecutionState(OnlyDomainModel):
    runtime_id: OnlyRuntimeId
    account_id: OnlyAccountId
    cluster_id: OnlyClusterId
    order_id: OnlyOrderId
    currency: OnlyCurrency
    cumulative_fill_quantity: OnlyQuantity
    cumulative_fill_notional: OnlyMoney
    cumulative_charged_fee: OnlyMoney
    components: tuple[OnlyOrderFeeComponentAccrual, ...]
    fill_count: int
    last_trade_id: OnlyTradeId
    updated_at: OnlyTimestamp
    version: int

    def __post_init__(self) -> None:
        if self.fill_count < 1 or self.version < 1 or self.cumulative_fill_quantity.value <= 0:
            raise ValueError("Order fee accrual fill/version authority is invalid")
        monies = (self.cumulative_fill_notional, self.cumulative_charged_fee) + tuple(
            value
            for component in self.components
            for value in (
                component.cumulative_raw_amount,
                component.cumulative_target_amount,
                component.cumulative_charged_amount,
            )
        )
        if any(item.currency != self.currency for item in monies) or min(item.amount for item in monies) < 0:
            raise ValueError("Order fee accrual currency/amount is invalid")
        if len({item.key for item in self.components}) != len(self.components):
            raise ValueError("Order fee accrual component key must be unique")
        if sum((item.cumulative_charged_amount.amount for item in self.components), Decimal(0)) != (
            self.cumulative_charged_fee.amount
        ):
            raise ValueError("Order fee accrual total disagrees with components")


__all__ = ["OnlyOrderFeeAccrualExecutionState", "OnlyOrderFeeComponentAccrual"]
