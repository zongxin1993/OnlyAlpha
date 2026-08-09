"""Canonical, immutable Runtime environment and shared-resource identity."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass, fields, is_dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import cast

from onlyalpha.config import (
    OnlyAccountRuntimeConfig,
    OnlyBrokerRuntimeConfig,
    OnlyClusterRunConfig,
    OnlyDataSourceRuntimeConfig,
    OnlyUniverseConfig,
)
from onlyalpha.domain.calendar import OnlyTradingCalendar
from onlyalpha.domain.instrument import OnlyInstrument


def only_canonical_payload(value: object) -> object:
    """Project stable values into JSON-compatible canonical data."""

    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, float):
        return str(value)
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, Enum):
        return only_canonical_payload(value.value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Path):
        return value.as_posix()
    if isinstance(value, Mapping):
        return {
            str(key): only_canonical_payload(item) for key, item in sorted(value.items(), key=lambda item: str(item[0]))
        }
    if isinstance(value, (set, frozenset)):
        items = (only_canonical_payload(item) for item in value)
        return sorted(items, key=only_canonical_json)
    if isinstance(value, (tuple, list)):
        return [only_canonical_payload(item) for item in value]
    if is_dataclass(value) and not isinstance(value, type):
        return {
            item.name: only_canonical_payload(getattr(value, item.name))
            for item in fields(value)
            if not item.name.startswith("_")
        }
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        return only_canonical_payload(to_dict())
    if type(value).__str__ is not object.__str__:
        return str(value)
    raise TypeError(f"cannot canonicalize {type(value).__module__}.{type(value).__qualname__}")


def only_canonical_json(value: object) -> str:
    return json.dumps(only_canonical_payload(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def only_canonical_fingerprint(value: object) -> str:
    return hashlib.sha256(only_canonical_json(value).encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class OnlyDataSourceEnvironmentIdentity:
    source_id: str
    plugin_id: str
    enabled: bool
    data_version: str
    coverage_fingerprint: str
    config_fingerprint: str

    @property
    def fingerprint(self) -> str:
        return only_canonical_fingerprint(self)


@dataclass(frozen=True, slots=True)
class OnlyBrokerEnvironmentIdentity:
    gateway_id: str
    plugin_id: str
    enabled: bool
    config_fingerprint: str

    @property
    def fingerprint(self) -> str:
        return only_canonical_fingerprint(self)


@dataclass(frozen=True, slots=True)
class OnlyAccountEnvironmentIdentity:
    account_id: str
    gateway_id: str
    initial_currency: str
    initial_cash_fingerprint: str
    broker_fee_contract_id: str
    broker_fee_contract_version: str
    reconciliation_policy_id: str
    reconciliation_policy_version: str
    reconciliation_policy_currency: str

    @property
    def fingerprint(self) -> str:
        return only_canonical_fingerprint(self)


@dataclass(frozen=True, slots=True)
class OnlyReferenceEnvironmentIdentity:
    authority_kind: str
    authority_fingerprint: str

    @property
    def fingerprint(self) -> str:
        return only_canonical_fingerprint(self)


@dataclass(frozen=True, slots=True)
class OnlyMarketEnvironmentIdentity:
    profile_id: str
    profile_version: str | None
    overrides_fingerprint: str
    market_fee_pack_id: str
    market_fee_pack_version: str
    reference: OnlyReferenceEnvironmentIdentity

    @property
    def fingerprint(self) -> str:
        return only_canonical_fingerprint(self)


@dataclass(frozen=True, slots=True)
class OnlyPersistenceEnvironmentIdentity:
    backend: str
    checkpoint_enabled: bool
    config_fingerprint: str

    @property
    def fingerprint(self) -> str:
        return only_canonical_fingerprint(self)


@dataclass(frozen=True, slots=True)
class OnlyRuntimeEnvironmentIdentity:
    runtime_type: str
    start_time: str
    end_time: str
    clock_policy: str
    replay_fingerprint: str
    runtime_extensions_fingerprint: str
    base_currency_fingerprint: str
    data_sources: tuple[OnlyDataSourceEnvironmentIdentity, ...]
    brokers: tuple[OnlyBrokerEnvironmentIdentity, ...]
    accounts: tuple[OnlyAccountEnvironmentIdentity, ...]
    market: OnlyMarketEnvironmentIdentity
    persistence: OnlyPersistenceEnvironmentIdentity

    @property
    def fingerprint(self) -> str:
        return only_canonical_fingerprint(self)


@dataclass(frozen=True, slots=True)
class OnlyResourceClaim:
    resource_type: str
    resource_key: str
    fingerprint: str

    @property
    def key(self) -> str:
        return f"{self.resource_type}:{self.resource_key}"


class OnlyRuntimeEnvironmentBuilder:
    """Pure authority for Runtime grouping and shared-resource claims."""

    def build(self, config: OnlyClusterRunConfig) -> OnlyRuntimeEnvironmentIdentity:
        data_sources = tuple(
            sorted(
                (self._data_source(item) for item in config.data_sources),
                key=lambda item: (item.source_id, item.plugin_id),
            )
        )
        brokers = tuple(
            sorted(
                (self._broker(item) for item in config.brokers),
                key=lambda item: (item.gateway_id, item.plugin_id),
            )
        )
        accounts = tuple(sorted((self._account(item) for item in config.accounts), key=lambda item: item.account_id))
        reference = OnlyReferenceEnvironmentIdentity(
            "CN_A_SHARE_REFERENCE" if config.market.profile.value == "CN_A_SHARE_CASH" else "GENERIC_REFERENCE",
            only_canonical_fingerprint(
                {
                    "calendars": tuple(
                        sorted(
                            config.reference_data.calendars,
                            key=lambda item: str(cast(OnlyTradingCalendar, item).calendar_id),
                        )
                    ),
                    "instruments": tuple(
                        sorted(
                            config.reference_data.instruments,
                            key=lambda item: str(cast(OnlyInstrument, item).instrument_id),
                        )
                    ),
                    "ashare_instruments": config.reference_data.ashare_registry.records,
                    "universes": tuple(
                        sorted(
                            config.universes,
                            key=lambda item: cast(OnlyUniverseConfig, item).universe_id,
                        )
                    ),
                }
            ),
        )
        market = OnlyMarketEnvironmentIdentity(
            config.market.profile.value,
            config.market.version,
            only_canonical_fingerprint(config.market.overrides),
            config.market.fee_pack.pack_id,
            config.market.fee_pack.pack_version,
            reference,
        )
        persistence = OnlyPersistenceEnvironmentIdentity(
            config.runtime.persistence.backend.value,
            config.runtime.persistence.checkpoint.enabled,
            only_canonical_fingerprint(config.runtime.persistence),
        )
        replay = config.runtime.extensions.get("replay", {})
        return OnlyRuntimeEnvironmentIdentity(
            config.runtime_type,
            "" if config.start_time is None else config.start_time.isoformat(),
            "" if config.end_time is None else config.end_time.isoformat(),
            "HISTORICAL_REPLAY" if config.runtime_type == "BACKTEST" else "LIVE_CLOCK",
            only_canonical_fingerprint(replay),
            only_canonical_fingerprint(config.runtime.extensions),
            only_canonical_fingerprint(config.runtime.base_currency),
            data_sources,
            brokers,
            accounts,
            market,
            persistence,
        )

    def resource_claims(self, config: OnlyClusterRunConfig) -> tuple[OnlyResourceClaim, ...]:
        environment = self.build(config)
        claims = [
            *(
                OnlyResourceClaim("calendar", str(item.calendar_id), only_canonical_fingerprint(item))
                for item in config.reference_data.calendars
            ),
            *(
                OnlyResourceClaim("instrument", str(item.instrument_id), only_canonical_fingerprint(item))
                for item in config.reference_data.instruments
            ),
            *(
                OnlyResourceClaim("universe", item.universe_id, only_canonical_fingerprint(item))
                for item in config.universes
            ),
            *(OnlyResourceClaim("data_source", item.source_id, item.fingerprint) for item in environment.data_sources),
            *(OnlyResourceClaim("broker", item.gateway_id, item.fingerprint) for item in environment.brokers),
            *(OnlyResourceClaim("account", item.account_id, item.fingerprint) for item in environment.accounts),
        ]
        return tuple(sorted(claims, key=lambda item: item.key))

    @staticmethod
    def _data_source(value: object) -> OnlyDataSourceEnvironmentIdentity:
        source = cast(OnlyDataSourceRuntimeConfig, value)
        coverage = only_canonical_fingerprint(
            {
                "universe_ids": tuple(sorted(source.coverage.universe_ids)),
                "instrument_ids": tuple(sorted(str(item) for item in source.coverage.instrument_ids)),
            }
        )
        config = only_canonical_fingerprint({"batch_size": source.batch_size, "extensions": source.extensions})
        return OnlyDataSourceEnvironmentIdentity(
            str(source.source_id), source.plugin_id, source.enabled, str(source.data_version), coverage, config
        )

    @staticmethod
    def _broker(value: object) -> OnlyBrokerEnvironmentIdentity:
        broker = cast(OnlyBrokerRuntimeConfig, value)
        return OnlyBrokerEnvironmentIdentity(
            str(broker.gateway_id), broker.plugin_id, broker.enabled, only_canonical_fingerprint(broker.extensions)
        )

    @staticmethod
    def _account(value: object) -> OnlyAccountEnvironmentIdentity:
        account = cast(OnlyAccountRuntimeConfig, value)
        currency = str(account.initial_cash.currency.code)
        return OnlyAccountEnvironmentIdentity(
            str(account.account_id),
            str(account.gateway_id),
            currency,
            only_canonical_fingerprint(account.initial_cash),
            account.broker_fee_contract.contract_id,
            account.broker_fee_contract.contract_version,
            account.fee_reconciliation_policy.policy_id,
            account.fee_reconciliation_policy.policy_version,
            currency,
        )


__all__ = [name for name in globals() if name.startswith("Only") or name.startswith("only_")]
