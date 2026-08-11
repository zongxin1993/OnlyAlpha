"""Immutable scoped Market/Broker fee schedules and strict registries."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from onlyalpha.domain.identifiers import OnlyAccountId, OnlyInstrumentId
from onlyalpha.domain.time import OnlyTradingDay
from onlyalpha.domain.value import OnlyCurrency
from onlyalpha.fee.models import (
    OnlyBrokerFeeAccountScope,
    OnlyBrokerFeeAccountScopeType,
    OnlyFeeAuthority,
    OnlyFeeScheduleAuthority,
    OnlyFeeScheduleFamilyIdentity,
    OnlyFeeScheduleIdentity,
    only_fee_fingerprint,
)
from onlyalpha.fee.policy import OnlyFeeRule, OnlyResolvedFeePolicy


@dataclass(frozen=True, slots=True)
class OnlyMarketFeeApplicabilityContext:
    trading_day: OnlyTradingDay
    market_product_id: str
    market: str
    venue: str
    instrument_class: str
    instrument_id: OnlyInstrumentId


@dataclass(frozen=True, slots=True)
class OnlyBrokerFeeApplicabilityContext:
    trading_day: OnlyTradingDay
    broker_id: str
    account_id: OnlyAccountId
    instrument_id: OnlyInstrumentId


@dataclass(frozen=True, slots=True)
class _OnlyBaseFeeSchedule:
    schedule_id: str
    version: str
    effective_from: date
    effective_to: date | None
    currency: OnlyCurrency
    source: str
    rules: tuple[OnlyFeeRule, ...]

    def __post_init__(self) -> None:
        if not all((self.schedule_id.strip(), self.version.strip(), self.source.strip())):
            raise ValueError("fee schedule identity/source cannot be empty")
        if self.effective_to is not None and self.effective_to <= self.effective_from:
            raise ValueError("fee schedule effective range must increase")
        if not self.rules:
            raise ValueError("fee schedule must contain at least one rule")
        if len({item.rule_id for item in self.rules}) != len(self.rules):
            raise ValueError("fee schedule rule IDs must be unique")
        if len({item.resolution_policy for item in self.rules}) != 1:
            raise ValueError("fee schedule rules must use one resolution policy")

    @property
    def authority(self) -> OnlyFeeScheduleAuthority:
        raise NotImplementedError

    @property
    def fingerprint(self) -> str:
        return only_fee_fingerprint(self.payload())

    @property
    def scope_fingerprint(self) -> str:
        return only_fee_fingerprint(self.scope_payload())

    @property
    def identity(self) -> OnlyFeeScheduleIdentity:
        return OnlyFeeScheduleIdentity(self.authority, self.schedule_id, self.version, self.fingerprint)

    @property
    def family_identity(self) -> OnlyFeeScheduleFamilyIdentity:
        return OnlyFeeScheduleFamilyIdentity(self.authority, self.schedule_id, self.scope_fingerprint)

    def applies_on(self, trading_day: date) -> bool:
        return self.effective_from <= trading_day and (self.effective_to is None or trading_day < self.effective_to)

    def resolved_policies(self) -> tuple[OnlyResolvedFeePolicy, ...]:
        return tuple(
            OnlyResolvedFeePolicy(
                self.authority,
                self.schedule_id,
                self.version,
                self.fingerprint,
                self.source,
                self.currency,
                rule,
            )
            for rule in self.rules
        )

    def payload(self) -> dict[str, object]:
        return {
            "authority": self.authority.value,
            "schedule_id": self.schedule_id,
            "version": self.version,
            "effective_from": self.effective_from.isoformat(),
            "effective_to": None if self.effective_to is None else self.effective_to.isoformat(),
            "currency": {"code": self.currency.code, "precision": self.currency.precision},
            "source": self.source,
            "rules": tuple(rule.payload() for rule in self.rules),
            **self.scope_payload(),
        }

    def scope_payload(self) -> dict[str, object]:
        raise NotImplementedError


@dataclass(frozen=True, slots=True)
class OnlyMarketFeeSchedule(_OnlyBaseFeeSchedule):
    market: str
    venue: str | None
    instrument_class: str | None

    def __post_init__(self) -> None:
        super(OnlyMarketFeeSchedule, self).__post_init__()
        if not self.market.strip():
            raise ValueError("market fee schedule requires market")
        if any(rule.authority in {OnlyFeeAuthority.BROKER, OnlyFeeAuthority.PLATFORM} for rule in self.rules):
            raise ValueError("market fee schedule cannot contain Broker fee authority")

    @property
    def authority(self) -> OnlyFeeScheduleAuthority:
        return OnlyFeeScheduleAuthority.MARKET

    def scope_payload(self) -> dict[str, object]:
        return {
            "authority": self.authority.value,
            "market": self.market,
            "venue": self.venue,
            "instrument_class": self.instrument_class,
            "currency": self.currency.to_dict(),
        }

    def matches(self, context: OnlyMarketFeeApplicabilityContext) -> bool:
        return (
            self.applies_on(context.trading_day.value)
            and self.market == context.market
            and (self.venue is None or self.venue == context.venue)
            and (self.instrument_class is None or self.instrument_class == context.instrument_class)
        )

    def matches_scope(self, context: OnlyMarketFeeApplicabilityContext) -> bool:
        return (
            self.market == context.market
            and (self.venue is None or self.venue == context.venue)
            and (self.instrument_class is None or self.instrument_class == context.instrument_class)
        )


@dataclass(frozen=True, slots=True)
class OnlyBrokerFeeSchedule(_OnlyBaseFeeSchedule):
    broker_id: str
    account_scope: OnlyBrokerFeeAccountScope

    def __post_init__(self) -> None:
        super(OnlyBrokerFeeSchedule, self).__post_init__()
        if not self.broker_id.strip():
            raise ValueError("broker fee schedule requires broker ID")
        if any(rule.authority not in {OnlyFeeAuthority.BROKER, OnlyFeeAuthority.PLATFORM} for rule in self.rules):
            raise ValueError("broker fee schedule cannot contain Market fee authority")

    @property
    def authority(self) -> OnlyFeeScheduleAuthority:
        return OnlyFeeScheduleAuthority.BROKER

    def scope_payload(self) -> dict[str, object]:
        return {
            "authority": self.authority.value,
            "broker_id": self.broker_id,
            "account_scope": self.account_scope.to_dict(),
            "currency": self.currency.to_dict(),
        }

    def matches(self, context: OnlyBrokerFeeApplicabilityContext) -> bool:
        return self.applies_on(context.trading_day.value) and self.matches_scope(context)

    def matches_scope(self, context: OnlyBrokerFeeApplicabilityContext) -> bool:
        return self.broker_id == context.broker_id and (
            self.account_scope.scope_type is OnlyBrokerFeeAccountScopeType.ALL_ACCOUNTS
            or self.account_scope.account_id == context.account_id
        )


class _OnlyFeeScheduleRegistry:
    expected_type: type[_OnlyBaseFeeSchedule]
    authority: OnlyFeeScheduleAuthority

    def __init__(self) -> None:
        self._schedules: dict[str, list[_OnlyBaseFeeSchedule]] = {}

    def register(self, schedule: _OnlyBaseFeeSchedule) -> None:
        if not isinstance(schedule, self.expected_type):
            raise TypeError("fee schedule registry received the wrong schedule type")
        values = self._schedules.setdefault(schedule.schedule_id, [])
        same_version = next((item for item in values if item.version == schedule.version), None)
        if same_version is not None:
            code = (
                "FEE_SCHEDULE_FINGERPRINT_CONFLICT"
                if same_version.fingerprint != schedule.fingerprint
                else "FEE_SCHEDULE_DUPLICATE_VERSION"
            )
            raise ValueError(code)
        if any(item.scope_fingerprint != schedule.scope_fingerprint for item in values):
            raise ValueError("FEE_SCHEDULE_SCOPE_DRIFT")
        if any(_effective_ranges_overlap(item, schedule) for item in values):
            raise ValueError("FEE_SCHEDULE_AMBIGUOUS")
        values.append(schedule)
        values.sort(key=lambda item: (item.effective_from, item.version))

    def resolve_version(self, identity: OnlyFeeScheduleIdentity) -> _OnlyBaseFeeSchedule:
        if identity.authority is not self.authority:
            raise ValueError("ORDER_FEE_POLICY_AUTHORITY_CONFLICT")
        matches = tuple(
            item for item in self._schedules.get(identity.schedule_id, ()) if item.version == identity.version
        )
        if len(matches) != 1:
            raise ValueError("FEE_SCHEDULE_EXACT_VERSION_NOT_FOUND")
        value = matches[0]
        if value.fingerprint != identity.fingerprint:
            raise ValueError("FEE_SCHEDULE_FINGERPRINT_CONFLICT")
        return value

    def schedules(self) -> tuple[_OnlyBaseFeeSchedule, ...]:
        return tuple(
            item
            for schedule_id in sorted(self._schedules)
            for item in sorted(self._schedules[schedule_id], key=lambda value: (value.effective_from, value.version))
        )


def _effective_ranges_overlap(first: _OnlyBaseFeeSchedule, second: _OnlyBaseFeeSchedule) -> bool:
    first_to = first.effective_to or date.max
    second_to = second.effective_to or date.max
    return first.effective_from < second_to and second.effective_from < first_to


class OnlyMarketFeeScheduleRegistry(_OnlyFeeScheduleRegistry):
    expected_type = OnlyMarketFeeSchedule
    authority = OnlyFeeScheduleAuthority.MARKET

    def resolve_version(self, identity: OnlyFeeScheduleIdentity) -> OnlyMarketFeeSchedule:
        value = super().resolve_version(identity)
        assert isinstance(value, OnlyMarketFeeSchedule)
        return value

    def resolve_family(
        self, family: OnlyFeeScheduleFamilyIdentity, context: OnlyMarketFeeApplicabilityContext
    ) -> OnlyMarketFeeSchedule:
        if family.authority is not self.authority:
            raise ValueError("ORDER_FEE_POLICY_AUTHORITY_CONFLICT")
        candidates = tuple(self._schedules.get(family.schedule_id, ()))
        if any(item.scope_fingerprint != family.scope_fingerprint for item in candidates):
            raise ValueError("ORDER_FEE_SCOPE_AUTHORITY_CHANGED")
        matches = tuple(
            item for item in candidates if isinstance(item, OnlyMarketFeeSchedule) and item.matches(context)
        )
        if not matches:
            raise ValueError("FEE_SCHEDULE_NOT_FOUND")
        if len(matches) > 1:
            raise ValueError("FEE_SCHEDULE_AMBIGUOUS")
        return matches[0]


class OnlyBrokerFeeScheduleRegistry(_OnlyFeeScheduleRegistry):
    expected_type = OnlyBrokerFeeSchedule
    authority = OnlyFeeScheduleAuthority.BROKER

    def resolve_version(self, identity: OnlyFeeScheduleIdentity) -> OnlyBrokerFeeSchedule:
        value = super().resolve_version(identity)
        assert isinstance(value, OnlyBrokerFeeSchedule)
        return value

    def resolve_family(
        self, family: OnlyFeeScheduleFamilyIdentity, context: OnlyBrokerFeeApplicabilityContext
    ) -> OnlyBrokerFeeSchedule:
        if family.authority is not self.authority:
            raise ValueError("ORDER_FEE_POLICY_AUTHORITY_CONFLICT")
        candidates = tuple(self._schedules.get(family.schedule_id, ()))
        if any(item.scope_fingerprint != family.scope_fingerprint for item in candidates):
            raise ValueError("ORDER_FEE_SCOPE_AUTHORITY_CHANGED")
        matches = tuple(
            item for item in candidates if isinstance(item, OnlyBrokerFeeSchedule) and item.matches(context)
        )
        if not matches:
            raise ValueError("FEE_SCHEDULE_NOT_FOUND")
        if len(matches) > 1:
            raise ValueError("FEE_SCHEDULE_AMBIGUOUS")
        return matches[0]


__all__ = [name for name in globals() if name.startswith("Only")]
