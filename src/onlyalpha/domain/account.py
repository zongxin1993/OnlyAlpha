"""Immutable financial results, positions, accounts and portfolios."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from onlyalpha.domain.base import OnlyDomainModel
from onlyalpha.domain.enums import OnlyContractType, OnlyMarginMode, OnlyPositionDirection
from onlyalpha.domain.errors import OnlyCurrencyMismatchError, OnlyValidationError
from onlyalpha.domain.identifiers import OnlyAccountId, OnlyInstrumentId, OnlyPositionId, OnlyTradeId
from onlyalpha.domain.instrument import OnlyCryptoPerpetual, OnlyFuture, OnlyInstrument
from onlyalpha.domain.time import only_require_utc
from onlyalpha.domain.value import OnlyCurrency, OnlyMoney, OnlyPrice, OnlyQuantity, OnlyRate


@dataclass(frozen=True, slots=True)
class OnlyFee(OnlyDomainModel):
    amount: OnlyMoney
    description: str = "fee"

    def __post_init__(self) -> None:
        if self.amount.amount < 0:
            raise OnlyValidationError("fee cannot be negative")


@dataclass(frozen=True, slots=True)
class OnlyCommission(OnlyDomainModel):
    amount: OnlyMoney

    def __post_init__(self) -> None:
        if self.amount.amount < 0:
            raise OnlyValidationError("commission cannot be negative")


@dataclass(frozen=True, slots=True)
class OnlyMargin(OnlyDomainModel):
    initial: OnlyMoney
    maintenance: OnlyMoney

    def __post_init__(self) -> None:
        if self.initial.currency != self.maintenance.currency:
            raise OnlyCurrencyMismatchError("margin components must use the same currency")
        if self.initial.amount < 0 or self.maintenance.amount < 0:
            raise OnlyValidationError("margin cannot be negative")


@dataclass(frozen=True, slots=True)
class OnlyPnL(OnlyDomainModel):
    realized: OnlyMoney
    unrealized: OnlyMoney

    def __post_init__(self) -> None:
        if self.realized.currency != self.unrealized.currency:
            raise OnlyCurrencyMismatchError("PnL components must use the same currency")

    @property
    def total(self) -> OnlyMoney:
        return self.realized + self.unrealized


@dataclass(frozen=True, slots=True)
class OnlySlippage(OnlyDomainModel):
    amount: OnlyMoney
    rate: OnlyRate | None = None


@dataclass(frozen=True, slots=True)
class OnlyBalance(OnlyDomainModel):
    currency: OnlyCurrency
    total: OnlyMoney
    available: OnlyMoney
    locked: OnlyMoney

    def __post_init__(self) -> None:
        if {self.total.currency, self.available.currency, self.locked.currency} != {self.currency}:
            raise OnlyCurrencyMismatchError("balance components must use balance currency")
        if min(self.total.amount, self.available.amount, self.locked.amount) < 0:
            raise OnlyValidationError("balance components cannot be negative")
        if self.available.amount + self.locked.amount != self.total.amount:
            raise OnlyValidationError("balance total must equal available plus locked")


@dataclass(frozen=True, slots=True)
class OnlyAccountEquity(OnlyDomainModel):
    total: OnlyMoney
    available: OnlyMoney
    locked: OnlyMoney
    position_value: OnlyMoney
    unrealized_pnl: OnlyMoney

    def __post_init__(self) -> None:
        currencies = {
            self.total.currency,
            self.available.currency,
            self.locked.currency,
            self.position_value.currency,
            self.unrealized_pnl.currency,
        }
        if len(currencies) != 1:
            raise OnlyCurrencyMismatchError("account equity components require one reporting currency")


@dataclass(frozen=True, slots=True)
class OnlyPosition(OnlyDomainModel):
    position_id: OnlyPositionId
    account_id: OnlyAccountId
    instrument_id: OnlyInstrumentId
    direction: OnlyPositionDirection
    quantity: OnlyQuantity
    available_quantity: OnlyQuantity
    average_open_price: OnlyPrice | None
    pnl: OnlyPnL
    opened_at: datetime | None
    updated_at: datetime
    closed_at: datetime | None = None
    trade_ids: tuple[OnlyTradeId, ...] = ()
    frozen_quantity: OnlyQuantity | None = None
    today_quantity: OnlyQuantity | None = None
    yesterday_quantity: OnlyQuantity | None = None
    settlement_currency: OnlyCurrency | None = None
    margin_mode: OnlyMarginMode | None = None

    def __post_init__(self) -> None:
        only_require_utc(self.updated_at, "position updated_at")
        if self.quantity.precision != self.available_quantity.precision:
            raise OnlyValidationError("position quantity precision mismatch")
        if self.available_quantity.value > self.quantity.value:
            raise OnlyValidationError("available position quantity exceeds total quantity")
        if self.frozen_quantity is not None:
            if self.frozen_quantity.precision != self.quantity.precision:
                raise OnlyValidationError("frozen position quantity precision mismatch")
            if self.available_quantity.value + self.frozen_quantity.value > self.quantity.value:
                raise OnlyValidationError("available plus frozen quantity exceeds total")
        if self.today_quantity is not None and self.yesterday_quantity is not None:
            if self.today_quantity.value + self.yesterday_quantity.value != self.quantity.value:
                raise OnlyValidationError("today plus yesterday quantity must equal total")
        if self.direction is OnlyPositionDirection.FLAT:
            if self.quantity.value != 0 or self.average_open_price is not None:
                raise OnlyValidationError("flat position must have zero quantity and no open price")
        elif self.quantity.value <= 0 or self.average_open_price is None:
            raise OnlyValidationError("open position requires positive quantity and average price")
        for timestamp in (self.opened_at, self.closed_at):
            if timestamp is not None:
                only_require_utc(timestamp, "position timestamp")
        if self.opened_at is not None and self.updated_at < self.opened_at:
            raise OnlyValidationError("position updated_at cannot precede opened_at")
        if self.closed_at is not None and self.closed_at < self.updated_at:
            raise OnlyValidationError("position closed_at cannot precede updated_at")


@dataclass(frozen=True, slots=True)
class OnlyAccount(OnlyDomainModel):
    account_id: OnlyAccountId
    base_currency: OnlyCurrency | None
    margin_mode: OnlyMarginMode
    balances: tuple[OnlyBalance, ...]
    positions: tuple[OnlyPosition, ...]
    equity: OnlyAccountEquity | None
    updated_at: datetime

    def __post_init__(self) -> None:
        only_require_utc(self.updated_at, "account updated_at")
        balance_currencies = [balance.currency for balance in self.balances]
        if len(balance_currencies) != len(set(balance_currencies)):
            raise OnlyValidationError("account cannot contain duplicate currency balances")
        if self.equity is not None and self.base_currency is None:
            raise OnlyValidationError("reported account equity requires base_currency")
        if self.equity is not None and self.equity.total.currency != self.base_currency:
            raise OnlyCurrencyMismatchError("account equity must use base_currency")


@dataclass(frozen=True, slots=True)
class OnlyPortfolio(OnlyDomainModel):
    accounts: tuple[OnlyAccount, ...]
    reporting_currency: OnlyCurrency | None
    total_equity: OnlyMoney | None
    as_of: datetime

    def __post_init__(self) -> None:
        only_require_utc(self.as_of, "portfolio as_of")
        account_ids = [account.account_id for account in self.accounts]
        if len(account_ids) != len(set(account_ids)):
            raise OnlyValidationError("portfolio cannot contain duplicate accounts")
        if self.total_equity is not None:
            if self.reporting_currency is None or self.total_equity.currency != self.reporting_currency:
                raise OnlyCurrencyMismatchError("portfolio total requires an explicit reporting currency")


class OnlyPnLCalculator:
    """Pure settlement-currency PnL formulas for linear and inverse contracts."""

    @staticmethod
    def unrealized(
        instrument: OnlyInstrument,
        direction: OnlyPositionDirection,
        quantity: OnlyQuantity,
        entry_price: OnlyPrice,
        current_price: OnlyPrice,
    ) -> OnlyMoney:
        sign = Decimal("1") if direction is OnlyPositionDirection.LONG else Decimal("-1")
        multiplier = instrument.contract_multiplier.value
        contract_type = OnlyContractType.LINEAR
        if isinstance(instrument, (OnlyFuture, OnlyCryptoPerpetual)):
            contract_type = instrument.contract_type
        if contract_type is OnlyContractType.INVERSE:
            amount = (
                sign
                * quantity.value
                * multiplier
                * (Decimal("1") / entry_price.value - Decimal("1") / current_price.value)
            )
        elif contract_type is OnlyContractType.QUANTO:
            raise OnlyValidationError("quanto PnL requires an explicit conversion model")
        else:
            amount = sign * quantity.value * multiplier * (current_price.value - entry_price.value)
        quantum = Decimal(1).scaleb(-instrument.settlement_currency.precision)
        return OnlyMoney(amount.quantize(quantum), instrument.settlement_currency)
