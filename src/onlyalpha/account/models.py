"""Immutable Account commands, snapshots, reservations and results."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType

from onlyalpha.account.enums import (
    OnlyAccountCashChangeType,
    OnlyAccountMutationStatus,
    OnlyAccountReservationState,
    OnlyAccountStatus,
    OnlyAccountType,
)
from onlyalpha.account.identifiers import OnlyAccountCashChangeId, OnlyAccountFeeId, OnlyAccountReservationId
from onlyalpha.domain.base import OnlyDomainModel
from onlyalpha.domain.enums import OnlyOrderSide
from onlyalpha.domain.identifiers import (
    OnlyAccountId,
    OnlyOrderId,
    OnlyRuntimeId,
    OnlyTradeId,
)
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.domain.value import OnlyCurrency, OnlyMoney


def only_account_metadata(value: Mapping[str, str]) -> Mapping[str, str]:
    return MappingProxyType(dict(value))


@dataclass(frozen=True, slots=True)
class OnlyAccountConfig(OnlyDomainModel):
    runtime_id: OnlyRuntimeId
    account_id: OnlyAccountId
    gateway_id: str
    account_type: OnlyAccountType
    base_currency: OnlyCurrency
    initial_cash: OnlyMoney

    def __post_init__(self) -> None:
        if not self.gateway_id.strip() or self.initial_cash.currency != self.base_currency:
            raise ValueError("Account config requires gateway and base-currency initial cash")
        if self.initial_cash.amount < 0:
            raise ValueError("Account initial cash cannot be negative")


@dataclass(frozen=True, slots=True)
class OnlyAccountCashBalance(OnlyDomainModel):
    cash_balance: OnlyMoney
    available_cash: OnlyMoney
    frozen_cash: OnlyMoney
    unsettled_cash: OnlyMoney

    def __post_init__(self) -> None:
        currencies = {
            self.cash_balance.currency,
            self.available_cash.currency,
            self.frozen_cash.currency,
            self.unsettled_cash.currency,
        }
        if (
            len(currencies) != 1
            or min(
                self.cash_balance.amount,
                self.available_cash.amount,
                self.frozen_cash.amount,
                self.unsettled_cash.amount,
            )
            < 0
        ):
            raise ValueError("Account cash balances require one currency and non-negative amounts")
        expected = self.cash_balance.amount - self.frozen_cash.amount - self.unsettled_cash.amount
        if self.available_cash.amount != expected:
            raise ValueError("available cash must be derived from cash minus frozen and unsettled")


OnlyAccountBalance = OnlyAccountCashBalance


@dataclass(frozen=True, slots=True)
class OnlyAccountReservation(OnlyDomainModel):
    reservation_id: OnlyAccountReservationId
    runtime_id: OnlyRuntimeId
    account_id: OnlyAccountId
    order_id: OnlyOrderId
    reserved_amount: OnlyMoney
    consumed_amount: OnlyMoney
    remaining_amount: OnlyMoney
    state: OnlyAccountReservationState
    created_at: OnlyTimestamp
    updated_at: OnlyTimestamp
    version: int = 1

    def __post_init__(self) -> None:
        values = (self.reserved_amount, self.consumed_amount, self.remaining_amount)
        if len({item.currency for item in values}) != 1:
            raise ValueError("Account Reservation requires one currency")
        accounted = self.consumed_amount.amount + self.remaining_amount.amount
        if self.state is OnlyAccountReservationState.RELEASED:
            if accounted > self.reserved_amount.amount:
                raise ValueError("released Account Reservation cannot exceed its original amount")
        elif accounted != self.reserved_amount.amount:
            raise ValueError("Account Reservation consumed plus remaining must equal reserved")
        if min(item.amount for item in values) < 0 or self.version < 1:
            raise ValueError("Account Reservation amounts must be non-negative and version positive")


@dataclass(frozen=True, slots=True)
class OnlyAccountCashChange(OnlyDomainModel):
    change_id: OnlyAccountCashChangeId
    runtime_id: OnlyRuntimeId
    account_id: OnlyAccountId
    amount: OnlyMoney
    change_type: OnlyAccountCashChangeType
    timestamp: OnlyTimestamp
    sequence: int

    def __post_init__(self) -> None:
        if self.sequence < 0 or self.amount.amount < 0:
            raise ValueError("Account cash-change amount and sequence cannot be negative")


@dataclass(frozen=True, slots=True)
class OnlyAccountFee(OnlyDomainModel):
    fee_id: OnlyAccountFeeId
    runtime_id: OnlyRuntimeId
    account_id: OnlyAccountId
    amount: OnlyMoney
    timestamp: OnlyTimestamp
    trade_id: OnlyTradeId | None = None
    order_id: OnlyOrderId | None = None

    def __post_init__(self) -> None:
        if self.amount.amount < 0:
            raise ValueError("Account fee cannot be negative")


@dataclass(frozen=True, slots=True)
class OnlyAccountTradeCashFlow(OnlyDomainModel):
    runtime_id: OnlyRuntimeId
    account_id: OnlyAccountId
    order_id: OnlyOrderId
    trade_id: OnlyTradeId
    side: OnlyOrderSide
    notional: OnlyMoney
    fee: OnlyMoney
    realized_pnl_delta: OnlyMoney
    timestamp: OnlyTimestamp
    external_sequence: int
    settle_notional: bool = True

    def __post_init__(self) -> None:
        values = (self.notional, self.fee, self.realized_pnl_delta)
        if len({item.currency for item in values}) != 1:
            raise ValueError("Account Trade cash flow requires one currency")
        if self.notional.amount < 0 or self.fee.amount < 0 or self.external_sequence < 0:
            raise ValueError("Account Trade notional, fee and sequence cannot be negative")


@dataclass(frozen=True, slots=True)
class OnlyAccountValuation(OnlyDomainModel):
    runtime_id: OnlyRuntimeId
    account_id: OnlyAccountId
    position_market_value: OnlyMoney
    unrealized_pnl: OnlyMoney
    timestamp: OnlyTimestamp
    valuation_version: int

    def __post_init__(self) -> None:
        if self.position_market_value.currency != self.unrealized_pnl.currency:
            raise ValueError("Account valuation requires one currency")
        if self.valuation_version < 1:
            raise ValueError("Account valuation version must be positive")


@dataclass(frozen=True, slots=True)
class OnlyAccountSnapshot(OnlyDomainModel):
    runtime_id: OnlyRuntimeId
    account_id: OnlyAccountId
    gateway_id: str
    account_type: OnlyAccountType
    base_currency: OnlyCurrency
    status: OnlyAccountStatus
    cash: OnlyAccountCashBalance
    position_market_value: OnlyMoney
    realized_pnl: OnlyMoney
    unrealized_pnl: OnlyMoney
    fees: OnlyMoney
    equity: OnlyMoney
    reservations: tuple[OnlyAccountReservation, ...]
    created_at: OnlyTimestamp
    updated_at: OnlyTimestamp
    valuation_time: OnlyTimestamp | None
    version: int
    last_external_sequence: int | None = None
    quality_flags: tuple[str, ...] = ()
    metadata: Mapping[str, str] = field(default_factory=dict)
    reserved_margin: OnlyMoney | None = None
    occupied_margin: OnlyMoney | None = None
    released_margin: OnlyMoney | None = None
    available_margin: OnlyMoney | None = None

    def __post_init__(self) -> None:
        values = (
            self.cash.cash_balance,
            self.position_market_value,
            self.realized_pnl,
            self.unrealized_pnl,
            self.fees,
            self.equity,
        )
        if any(item.currency != self.base_currency for item in values):
            raise ValueError("Account Snapshot values require base currency")
        margin_values = tuple(
            item
            for item in (
                self.reserved_margin,
                self.occupied_margin,
                self.released_margin,
                self.available_margin,
            )
            if item is not None
        )
        if any(item.currency != self.base_currency or item.amount < 0 for item in margin_values):
            raise ValueError("Account margin values require base currency and non-negative amounts")
        if self.equity.amount != self.cash.cash_balance.amount + self.position_market_value.amount:
            raise ValueError("cash plus position market value must equal Account equity")
        object.__setattr__(self, "quality_flags", tuple(self.quality_flags))
        object.__setattr__(self, "metadata", only_account_metadata(self.metadata))


@dataclass(frozen=True, slots=True)
class OnlyAccountMutationResult(OnlyDomainModel):
    status: OnlyAccountMutationStatus
    before: OnlyAccountSnapshot | None
    after: OnlyAccountSnapshot
    changed: bool
    reason: str = ""
