"""Immutable, auditable fee domain models.

These types deliberately do not depend on Runtime managers.  A fee report is
external evidence; a fee instruction is the sole local accounting command.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from types import MappingProxyType

from onlyalpha.domain.time import only_require_utc
from onlyalpha.domain.value import OnlyCurrency, OnlyMoney


class OnlyFeeAuthority(StrEnum):
    MARKET = "MARKET"
    VENUE = "VENUE"
    REGULATOR = "REGULATOR"
    CLEARING = "CLEARING"
    BROKER = "BROKER"
    PLATFORM = "PLATFORM"
    FINANCING = "FINANCING"
    BORROW = "BORROW"
    FUNDING = "FUNDING"
    OTHER = "OTHER"


class OnlyFeeType(StrEnum):
    STAMP_DUTY = "STAMP_DUTY"
    TRANSFER_FEE = "TRANSFER_FEE"
    EXCHANGE_FEE = "EXCHANGE_FEE"
    CLEARING_FEE = "CLEARING_FEE"
    REGULATORY_FEE = "REGULATORY_FEE"
    BROKER_COMMISSION = "BROKER_COMMISSION"
    PLATFORM_FEE = "PLATFORM_FEE"
    CONTRACT_FEE = "CONTRACT_FEE"
    OPEN_FEE = "OPEN_FEE"
    CLOSE_FEE = "CLOSE_FEE"
    CLOSE_TODAY_FEE = "CLOSE_TODAY_FEE"
    MAKER_FEE = "MAKER_FEE"
    TAKER_FEE = "TAKER_FEE"
    BORROW_FEE = "BORROW_FEE"
    FINANCING_FEE = "FINANCING_FEE"
    FUNDING = "FUNDING"
    FX_CONVERSION_FEE = "FX_CONVERSION_FEE"
    OTHER = "OTHER"


class OnlyFeeStatus(StrEnum):
    ESTIMATED = "ESTIMATED"
    PROVISIONAL = "PROVISIONAL"
    CONFIRMED = "CONFIRMED"
    ADJUSTED = "ADJUSTED"
    REVERSED = "REVERSED"


class OnlyFeeConfigurationMode(StrEnum):
    NONE = "NONE"
    MODEL = "MODEL"
    DEFAULT = "DEFAULT"
    REPORTED = "REPORTED"


class OnlyBrokerFeeReportingMode(StrEnum):
    NONE = "NONE"
    COMMISSION_ONLY = "COMMISSION_ONLY"
    DETAILED = "DETAILED"
    ALL_IN = "ALL_IN"
    DEFERRED_STATEMENT = "DEFERRED_STATEMENT"


@dataclass(frozen=True, slots=True)
class OnlyFeeComponent:
    fee_type: OnlyFeeType
    authority: OnlyFeeAuthority
    amount: OnlyMoney
    status: OnlyFeeStatus
    source_id: str
    schedule_id: str | None = None
    schedule_version: str | None = None
    effective_date: date | None = None
    metadata: Mapping[str, object] = field(default_factory=lambda: MappingProxyType({}))

    def __post_init__(self) -> None:
        if not self.source_id:
            raise ValueError("fee component source_id cannot be empty")
        if self.amount.amount < 0:
            raise ValueError("fee component amount cannot be negative")
        if (self.schedule_id is None) != (self.schedule_version is None):
            raise ValueError("fee component schedule identity requires both id and version")
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))

    @property
    def unique_key(self) -> tuple[OnlyFeeType, OnlyFeeAuthority, str, str | None, str | None]:
        return self.fee_type, self.authority, self.source_id, self.schedule_id, self.schedule_version


@dataclass(frozen=True, slots=True)
class OnlyFeeBreakdown:
    currency: OnlyCurrency
    components: tuple[OnlyFeeComponent, ...]
    total: OnlyMoney
    status: OnlyFeeStatus

    def __post_init__(self) -> None:
        if self.total.currency != self.currency:
            raise ValueError("fee breakdown total currency mismatch")
        if any(item.amount.currency != self.currency for item in self.components):
            raise ValueError("fee breakdown component currency mismatch")
        if len({item.unique_key for item in self.components}) != len(self.components):
            raise ValueError("fee breakdown contains duplicate component identity")
        summed = sum((item.amount.amount for item in self.components), Decimal(0))
        if summed != self.total.amount:
            raise ValueError("fee breakdown total must equal components")
        if any(item.status is not self.status for item in self.components):
            raise ValueError("fee breakdown component statuses must match breakdown status")

    @classmethod
    def empty(cls, currency: OnlyCurrency, status: OnlyFeeStatus) -> OnlyFeeBreakdown:
        return cls(currency, (), OnlyMoney(Decimal(0), currency), status)


@dataclass(frozen=True, slots=True)
class OnlyFeeCalculationRequest:
    runtime_id: str
    cluster_id: str | None
    account_id: str
    order_id: str
    trade_id: str
    instrument_id: str
    market_profile_id: str
    market_profile_version: str
    trading_day: date
    side: str
    offset: str
    liquidity_role: str | None
    price: Decimal
    quantity: Decimal
    notional: OnlyMoney
    contract_multiplier: Decimal
    currency: OnlyCurrency
    broker_id: str
    broker_fee_reporting_mode: OnlyBrokerFeeReportingMode
    reported_fee: OnlyMoney | None = None
    reported_breakdown: OnlyFeeBreakdown | None = None

    def __post_init__(self) -> None:
        if not all(
            (self.runtime_id, self.account_id, self.order_id, self.trade_id, self.instrument_id, self.broker_id)
        ):
            raise ValueError("fee calculation request contains an empty identity")
        if self.price <= 0 or self.quantity <= 0 or self.contract_multiplier <= 0:
            raise ValueError("fee calculation request price, quantity and multiplier must be positive")
        if self.notional.currency != self.currency:
            raise ValueError("fee calculation request notional currency mismatch")
        if self.reported_fee is not None and self.reported_fee.currency != self.currency:
            raise ValueError("reported fee currency mismatch")
        if self.reported_breakdown is not None and self.reported_breakdown.currency != self.currency:
            raise ValueError("reported fee breakdown currency mismatch")


@dataclass(frozen=True, slots=True)
class OnlyFeeInstruction:
    instruction_id: str
    runtime_id: str
    cluster_id: str | None
    account_id: str
    order_id: str
    trade_id: str
    fee_breakdown: OnlyFeeBreakdown
    calculation_source: str
    created_at: datetime
    idempotency_key: str

    def __post_init__(self) -> None:
        if not all(
            (self.instruction_id, self.runtime_id, self.account_id, self.order_id, self.trade_id, self.idempotency_key)
        ):
            raise ValueError("fee instruction contains an empty identity")
        only_require_utc(self.created_at, "fee instruction created_at")


@dataclass(frozen=True, slots=True)
class OnlyFeeAdjustmentInstruction:
    adjustment_id: str
    related_trade_id: str | None
    settlement_scope: str | None
    account_id: str
    cluster_id: str | None
    currency: OnlyCurrency
    previous_amount: OnlyMoney
    reported_amount: OnlyMoney
    adjustment_amount: OnlyMoney
    reason: str
    external_reference: str | None
    created_at: datetime
    idempotency_key: str

    def __post_init__(self) -> None:
        if (self.related_trade_id is None) == (self.settlement_scope is None):
            raise ValueError("fee adjustment requires exactly one trade or settlement scope")
        if not all((self.adjustment_id, self.account_id, self.reason, self.idempotency_key)):
            raise ValueError("fee adjustment contains an empty identity")
        if any(
            item.currency != self.currency
            for item in (self.previous_amount, self.reported_amount, self.adjustment_amount)
        ):
            raise ValueError("fee adjustment currency mismatch")
        if self.adjustment_amount.amount != self.reported_amount.amount - self.previous_amount.amount:
            raise ValueError("fee adjustment amount must equal reported minus previous")
        only_require_utc(self.created_at, "fee adjustment created_at")
