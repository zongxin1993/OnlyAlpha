"""Immutable Market/Broker fee schedules and strict registries."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from onlyalpha.domain.value import OnlyCurrency
from onlyalpha.fee.models import OnlyFeeScheduleIdentity, only_fee_fingerprint
from onlyalpha.fee.policy import OnlyFeeRule, OnlyResolvedFeePolicy


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

    @property
    def fingerprint(self) -> str:
        return only_fee_fingerprint(self.payload())

    @property
    def identity(self) -> OnlyFeeScheduleIdentity:
        return OnlyFeeScheduleIdentity(self.schedule_id, self.version, self.fingerprint)

    def applies_on(self, trading_day: date) -> bool:
        return self.effective_from <= trading_day and (self.effective_to is None or trading_day < self.effective_to)

    def resolved_policies(self) -> tuple[OnlyResolvedFeePolicy, ...]:
        return tuple(
            OnlyResolvedFeePolicy(
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
        result: dict[str, object] = {
            "schedule_id": self.schedule_id,
            "version": self.version,
            "effective_from": self.effective_from.isoformat(),
            "effective_to": None if self.effective_to is None else self.effective_to.isoformat(),
            "currency": {"code": self.currency.code, "precision": self.currency.precision},
            "source": self.source,
            "rules": tuple(rule.payload() for rule in self.rules),
        }
        result.update(self.scope_payload())
        return result

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

    def scope_payload(self) -> dict[str, object]:
        return {"market": self.market, "venue": self.venue, "instrument_class": self.instrument_class}


@dataclass(frozen=True, slots=True)
class OnlyBrokerFeeSchedule(_OnlyBaseFeeSchedule):
    broker_id: str
    account_scope: str | None

    def __post_init__(self) -> None:
        super(OnlyBrokerFeeSchedule, self).__post_init__()
        if not self.broker_id.strip():
            raise ValueError("broker fee schedule requires broker ID")

    def scope_payload(self) -> dict[str, object]:
        return {"broker_id": self.broker_id, "account_scope": self.account_scope}


class _OnlyFeeScheduleRegistry:
    expected_type: type[_OnlyBaseFeeSchedule]

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
        if any(_ranges_overlap(item, schedule) for item in values):
            raise ValueError("FEE_SCHEDULE_EFFECTIVE_RANGE_OVERLAP")
        values.append(schedule)
        values.sort(key=lambda item: (item.effective_from, item.version))

    def resolve(self, schedule_id: str, trading_day: date) -> _OnlyBaseFeeSchedule:
        matches = tuple(item for item in self._schedules.get(schedule_id, ()) if item.applies_on(trading_day))
        if len(matches) != 1:
            raise ValueError("FEE_SCHEDULE_EFFECTIVE_VERSION_NOT_FOUND")
        return matches[0]

    def resolve_version(self, schedule_id: str, version: str, fingerprint: str | None = None) -> _OnlyBaseFeeSchedule:
        matches = tuple(item for item in self._schedules.get(schedule_id, ()) if item.version == version)
        if len(matches) != 1:
            raise ValueError("FEE_SCHEDULE_EXACT_VERSION_NOT_FOUND")
        value = matches[0]
        if fingerprint is not None and value.fingerprint != fingerprint:
            raise ValueError("FEE_SCHEDULE_FINGERPRINT_CONFLICT")
        return value

    def schedules(self) -> tuple[_OnlyBaseFeeSchedule, ...]:
        return tuple(
            item
            for schedule_id in sorted(self._schedules)
            for item in sorted(self._schedules[schedule_id], key=lambda value: (value.effective_from, value.version))
        )


class OnlyMarketFeeScheduleRegistry(_OnlyFeeScheduleRegistry):
    expected_type = OnlyMarketFeeSchedule

    def resolve(self, schedule_id: str, trading_day: date) -> OnlyMarketFeeSchedule:
        value = super().resolve(schedule_id, trading_day)
        assert isinstance(value, OnlyMarketFeeSchedule)
        return value

    def resolve_version(self, schedule_id: str, version: str, fingerprint: str | None = None) -> OnlyMarketFeeSchedule:
        value = super().resolve_version(schedule_id, version, fingerprint)
        assert isinstance(value, OnlyMarketFeeSchedule)
        return value


class OnlyBrokerFeeScheduleRegistry(_OnlyFeeScheduleRegistry):
    expected_type = OnlyBrokerFeeSchedule

    def resolve(self, schedule_id: str, trading_day: date) -> OnlyBrokerFeeSchedule:
        value = super().resolve(schedule_id, trading_day)
        assert isinstance(value, OnlyBrokerFeeSchedule)
        return value

    def resolve_version(self, schedule_id: str, version: str, fingerprint: str | None = None) -> OnlyBrokerFeeSchedule:
        value = super().resolve_version(schedule_id, version, fingerprint)
        assert isinstance(value, OnlyBrokerFeeSchedule)
        return value


def _ranges_overlap(left: _OnlyBaseFeeSchedule, right: _OnlyBaseFeeSchedule) -> bool:
    return left.effective_from < (right.effective_to or date.max) and right.effective_from < (
        left.effective_to or date.max
    )


__all__ = [
    "OnlyBrokerFeeSchedule",
    "OnlyBrokerFeeScheduleRegistry",
    "OnlyMarketFeeSchedule",
    "OnlyMarketFeeScheduleRegistry",
]
