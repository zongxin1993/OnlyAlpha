"""Versioned market and broker fee schedules plus deterministic registries."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import date
from decimal import ROUND_HALF_EVEN, Decimal
from enum import StrEnum

from onlyalpha.domain.value import OnlyCurrency, OnlyMoney
from onlyalpha.fee.models import (
    OnlyFeeAuthority,
    OnlyFeeCalculationScope,
    OnlyFeeComponent,
    OnlyFeeStatus,
    OnlyFeeType,
)


@dataclass(frozen=True, slots=True)
class OnlyFeeRateRule:
    fee_type: OnlyFeeType
    authority: OnlyFeeAuthority
    percent_rate: Decimal = Decimal(0)
    per_unit: Decimal = Decimal(0)
    minimum: Decimal = Decimal(0)
    maximum: Decimal | None = None
    side: str | None = None
    offset: str | None = None
    liquidity_role: str | None = None
    calculation_scope: OnlyFeeCalculationScope = OnlyFeeCalculationScope.FILL

    def calculate(
        self, *, notional: Decimal, quantity: Decimal, side: str, offset: str, liquidity_role: str | None
    ) -> Decimal:
        if (self.side is not None and self.side != side) or (self.offset is not None and self.offset != offset):
            return Decimal(0)
        if self.liquidity_role is not None and self.liquidity_role != liquidity_role:
            return Decimal(0)
        amount = max(self.raw_amount(notional=notional, quantity=quantity), self.minimum)
        return min(amount, self.maximum) if self.maximum is not None else amount

    def raw_amount(self, *, notional: Decimal, quantity: Decimal) -> Decimal:
        return notional * self.percent_rate + quantity * self.per_unit


@dataclass(frozen=True, slots=True)
class _OnlyBaseFeeSchedule:
    schedule_id: str
    version: str
    effective_from: date
    effective_to: date | None
    currency: OnlyCurrency
    source: str
    rules: tuple[OnlyFeeRateRule, ...]

    def __post_init__(self) -> None:
        if not self.schedule_id or not self.version or not self.source:
            raise ValueError("fee schedule identity and source cannot be empty")
        if self.effective_to is not None and self.effective_to <= self.effective_from:
            raise ValueError("fee schedule effective range must increase")

    @property
    def fingerprint(self) -> str:
        payload = _normalize(asdict(self))
        return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

    def applies_on(self, trading_day: date) -> bool:
        return self.effective_from <= trading_day and (self.effective_to is None or trading_day < self.effective_to)

    def calculate(
        self,
        *,
        notional: Decimal,
        quantity: Decimal,
        side: str,
        offset: str,
        liquidity_role: str | None,
        status: OnlyFeeStatus,
        currency: OnlyCurrency | None = None,
        cumulative_notional: Decimal | None = None,
        cumulative_quantity: Decimal | None = None,
    ) -> tuple[OnlyFeeComponent, ...]:
        resolved_currency = self.currency if currency is None else currency
        quantum = Decimal(1).scaleb(-resolved_currency.precision)
        components = []
        for rule in self.rules:
            rule_notional = notional
            rule_quantity = quantity
            if rule.calculation_scope is OnlyFeeCalculationScope.ORDER_CUMULATIVE:
                if cumulative_notional is None or cumulative_quantity is None:
                    raise ValueError("ORDER_CUMULATIVE fee rule requires cumulative Order authority")
                rule_notional = cumulative_notional
                rule_quantity = cumulative_quantity
            raw_amount = rule.raw_amount(notional=rule_notional, quantity=rule_quantity)
            amount = rule.calculate(
                notional=rule_notional,
                quantity=rule_quantity,
                side=side,
                offset=offset,
                liquidity_role=liquidity_role,
            )
            raw_amount = raw_amount.quantize(quantum, rounding=ROUND_HALF_EVEN)
            amount = amount.quantize(quantum, rounding=ROUND_HALF_EVEN)
            if amount:
                components.append(
                    OnlyFeeComponent(
                        rule.fee_type,
                        rule.authority,
                        OnlyMoney(amount, resolved_currency),
                        status,
                        self.source,
                        self.schedule_id,
                        self.version,
                        self.effective_from,
                        {
                            "schedule_fingerprint": self.fingerprint,
                            "raw_amount": str(raw_amount),
                        },
                        rule.calculation_scope,
                    )
                )
        return tuple(components)


@dataclass(frozen=True, slots=True)
class OnlyMarketFeeSchedule(_OnlyBaseFeeSchedule):
    market: str = ""
    venue: str | None = None
    instrument_class: str | None = None


@dataclass(frozen=True, slots=True)
class OnlyBrokerFeeSchedule(_OnlyBaseFeeSchedule):
    broker_id: str = ""
    account_scope: str | None = None


class _OnlyFeeScheduleRegistry:
    def __init__(self) -> None:
        self._schedules: dict[str, list[_OnlyBaseFeeSchedule]] = {}

    def register(self, schedule: _OnlyBaseFeeSchedule) -> None:
        values = self._schedules.setdefault(schedule.schedule_id, [])
        if any(item.version == schedule.version for item in values):
            raise ValueError("fee schedules are immutable; id/version already registered")
        if any(_ranges_overlap(item, schedule) for item in values):
            raise ValueError("fee schedule effective ranges cannot overlap")
        values.append(schedule)
        values.sort(key=lambda item: (item.effective_from, item.version))

    def resolve_version(self, schedule_id: str, version: str) -> _OnlyBaseFeeSchedule:
        matches = [item for item in self._schedules.get(schedule_id, ()) if item.version == version]
        if len(matches) != 1:
            raise ValueError(f"expected exactly one fee schedule version for {schedule_id!r}@{version!r}")
        return matches[0]

    def resolve(self, schedule_id: str, trading_day: date) -> _OnlyBaseFeeSchedule:
        matches = [item for item in self._schedules.get(schedule_id, ()) if item.applies_on(trading_day)]
        if len(matches) != 1:
            raise ValueError(f"expected exactly one effective fee schedule for {schedule_id!r}")
        return matches[0]


class OnlyMarketFeeScheduleRegistry(_OnlyFeeScheduleRegistry):
    def resolve(self, schedule_id: str, trading_day: date) -> OnlyMarketFeeSchedule:
        value = super().resolve(schedule_id, trading_day)
        if not isinstance(value, OnlyMarketFeeSchedule):
            raise TypeError("market fee schedule registry contains invalid type")
        return value

    def resolve_version(self, schedule_id: str, version: str) -> OnlyMarketFeeSchedule:
        value = super().resolve_version(schedule_id, version)
        if not isinstance(value, OnlyMarketFeeSchedule):
            raise TypeError("market fee schedule registry contains invalid type")
        return value


class OnlyBrokerFeeScheduleRegistry(_OnlyFeeScheduleRegistry):
    def resolve(self, schedule_id: str, trading_day: date) -> OnlyBrokerFeeSchedule:
        value = super().resolve(schedule_id, trading_day)
        if not isinstance(value, OnlyBrokerFeeSchedule):
            raise TypeError("broker fee schedule registry contains invalid type")
        return value

    def resolve_version(self, schedule_id: str, version: str) -> OnlyBrokerFeeSchedule:
        value = super().resolve_version(schedule_id, version)
        if not isinstance(value, OnlyBrokerFeeSchedule):
            raise TypeError("broker fee schedule registry contains invalid type")
        return value


OnlyMarketFeeScheduleResolver = OnlyMarketFeeScheduleRegistry
OnlyBrokerFeeScheduleResolver = OnlyBrokerFeeScheduleRegistry
OnlyMarketFeeScheduleId = str
OnlyMarketFeeScheduleVersion = str
OnlyBrokerFeeScheduleId = str
OnlyBrokerFeeScheduleVersion = str


def only_builtin_market_fee_schedule_registry() -> OnlyMarketFeeScheduleRegistry:
    """Core-provided defaults; callers may register a versioned replacement."""
    from onlyalpha.domain.value import OnlyCurrency

    registry = OnlyMarketFeeScheduleRegistry()
    registry.register(
        OnlyMarketFeeSchedule(
            "GENERIC_T0_MARKET_FEES",
            "1",
            date(1970, 1, 1),
            None,
            OnlyCurrency("CNY"),
            "OnlyAlpha",
            (OnlyFeeRateRule(OnlyFeeType.EXCHANGE_FEE, OnlyFeeAuthority.MARKET, percent_rate=Decimal("0.001")),),
            "GENERIC",
        )
    )
    registry.register(
        OnlyMarketFeeSchedule(
            "GENERIC_FUTURES_MARKET_FEES",
            "1",
            date(1970, 1, 1),
            None,
            OnlyCurrency("CNY"),
            "OnlyAlpha",
            (OnlyFeeRateRule(OnlyFeeType.CONTRACT_FEE, OnlyFeeAuthority.VENUE, per_unit=Decimal("2")),),
            "GENERIC",
        )
    )
    registry.register(
        OnlyMarketFeeSchedule(
            "GENERIC_CRYPTO_MARKET_FEES",
            "1",
            date(1970, 1, 1),
            None,
            OnlyCurrency("USDT"),
            "OnlyAlpha",
            (
                OnlyFeeRateRule(
                    OnlyFeeType.TAKER_FEE,
                    OnlyFeeAuthority.VENUE,
                    percent_rate=Decimal("0.0005"),
                    liquidity_role="TAKER",
                ),
            ),
            "CRYPTO",
        )
    )
    registry.register(
        OnlyMarketFeeSchedule(
            "CN_A_SHARE_STANDARD_FEES",
            "2025.1",
            date(2025, 1, 1),
            None,
            OnlyCurrency("CNY"),
            "OnlyAlpha",
            (
                OnlyFeeRateRule(
                    OnlyFeeType.STAMP_DUTY, OnlyFeeAuthority.REGULATOR, percent_rate=Decimal("0.0005"), side="SELL"
                ),
                OnlyFeeRateRule(OnlyFeeType.TRANSFER_FEE, OnlyFeeAuthority.CLEARING, percent_rate=Decimal("0.00001")),
            ),
            "CN_A_SHARE",
        )
    )
    return registry


def only_builtin_broker_fee_schedule_registry() -> OnlyBrokerFeeScheduleRegistry:
    """Broker schedules are contract-specific; Core intentionally registers none."""

    return OnlyBrokerFeeScheduleRegistry()


def _ranges_overlap(left: _OnlyBaseFeeSchedule, right: _OnlyBaseFeeSchedule) -> bool:
    left_end = left.effective_to or date.max
    right_end = right.effective_to or date.max
    return left.effective_from < right_end and right.effective_from < left_end


def _normalize(value: object) -> object:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, OnlyCurrency):
        return value.code
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, dict):
        return {str(key): _normalize(item) for key, item in sorted(value.items(), key=lambda item: str(item[0]))}
    if isinstance(value, (list, tuple)):
        return [_normalize(item) for item in value]
    return value
