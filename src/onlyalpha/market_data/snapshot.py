"""Immutable strategy-visible market-data snapshots."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from types import MappingProxyType

from onlyalpha.domain.enums import OnlySessionType
from onlyalpha.domain.identifiers import OnlyClusterId, OnlyInstrumentId, OnlyRuntimeId
from onlyalpha.domain.market import OnlyBar, OnlyBarType
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.indicator.base import OnlyIndicatorId, OnlyIndicatorValue, OnlyStructuredIndicatorValue
from onlyalpha.market_data.subscriptions import only_bar_type_id


class OnlyMarketDataSnapshotError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class OnlyBarSnapshot:
    latest_closed_bars: Mapping[OnlyBarType, OnlyBar]
    histories: Mapping[OnlyBarType, tuple[OnlyBar, ...]]
    partial_bars: Mapping[OnlyBarType, OnlyBar]
    data_versions: Mapping[OnlyBarType, int]

    def __post_init__(self) -> None:
        object.__setattr__(self, "latest_closed_bars", MappingProxyType(dict(self.latest_closed_bars)))
        object.__setattr__(self, "histories", MappingProxyType(dict(self.histories)))
        object.__setattr__(self, "partial_bars", MappingProxyType(dict(self.partial_bars)))
        object.__setattr__(self, "data_versions", MappingProxyType(dict(self.data_versions)))


@dataclass(frozen=True, slots=True)
class OnlyMarketDataSnapshot:
    """Consistent view created only after the synchronous data-ready barrier."""

    ts_event: OnlyTimestamp
    ts_init: OnlyTimestamp
    runtime_id: OnlyRuntimeId
    cluster_id: OnlyClusterId | None
    instrument_id: OnlyInstrumentId
    primary_bar_type: OnlyBarType
    primary_bar: OnlyBar
    updated_bar_types: frozenset[OnlyBarType]
    bars: OnlyBarSnapshot
    indicator_values: Mapping[OnlyIndicatorId, OnlyIndicatorValue]
    indicator_versions: Mapping[OnlyIndicatorId, int]
    trading_day: date
    session_type: OnlySessionType
    quality_flags: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.primary_bar.bar_type != self.primary_bar_type:
            raise OnlyMarketDataSnapshotError("primary Bar does not match primary_bar_type")
        if self.ts_event.unix_nanos != OnlyTimestamp.from_datetime(self.primary_bar.bar_end).unix_nanos:
            raise OnlyMarketDataSnapshotError("Snapshot ts_event must equal primary Bar end")
        object.__setattr__(self, "updated_bar_types", frozenset(self.updated_bar_types))
        object.__setattr__(self, "indicator_values", MappingProxyType(dict(self.indicator_values)))
        object.__setattr__(self, "indicator_versions", MappingProxyType(dict(self.indicator_versions)))

    @property
    def latest_closed_bars(self) -> Mapping[OnlyBarType, OnlyBar]:
        return self.bars.latest_closed_bars

    @property
    def data_versions(self) -> Mapping[OnlyBarType, int]:
        return self.bars.data_versions

    def latest_closed(self, bar_type: OnlyBarType) -> OnlyBar | None:
        return self.bars.latest_closed_bars.get(bar_type)

    def require_latest_closed(self, bar_type: OnlyBarType) -> OnlyBar:
        bar = self.latest_closed(bar_type)
        if bar is None:
            raise OnlyMarketDataSnapshotError(f"no closed Bar available: {only_bar_type_id(bar_type)}")
        return bar

    def current_partial(self, bar_type: OnlyBarType) -> OnlyBar | None:
        return self.bars.partial_bars.get(bar_type)

    def was_updated(self, bar_type: OnlyBarType) -> bool:
        return bar_type in self.updated_bar_types

    def require_same_event_time(self, bar_type: OnlyBarType) -> OnlyBar:
        bar = self.require_latest_closed(bar_type)
        if bar.bar_end != self.primary_bar.bar_end:
            raise OnlyMarketDataSnapshotError("requested Bar was not closed at primary event time")
        return bar

    def indicator(self, indicator_id: OnlyIndicatorId) -> OnlyIndicatorValue:
        return self.indicator_values.get(indicator_id)

    def require_indicator(self, indicator_id: OnlyIndicatorId) -> OnlyIndicatorValue:
        if indicator_id not in self.indicator_values:
            raise OnlyMarketDataSnapshotError(f"indicator is unavailable: {indicator_id}")
        return self.indicator_values[indicator_id]

    def history(self, bar_type: OnlyBarType, count: int) -> tuple[OnlyBar, ...]:
        if count <= 0:
            raise ValueError("history count must be positive")
        return self.bars.histories.get(bar_type, ())[-count:]

    def restrict(
        self,
        *,
        cluster_id: OnlyClusterId,
        bar_types: tuple[OnlyBarType, ...],
        primary_bar_type: OnlyBarType,
        indicator_ids: tuple[OnlyIndicatorId, ...],
    ) -> OnlyMarketDataSnapshot:
        allowed = frozenset(bar_types)
        primary = self.bars.latest_closed_bars.get(primary_bar_type)
        if primary is None or primary.bar_end != self.primary_bar.bar_end:
            raise OnlyMarketDataSnapshotError("primary Bar is not ready for this time slice")
        return OnlyMarketDataSnapshot(
            ts_event=OnlyTimestamp.from_datetime(primary.bar_end),
            ts_init=self.ts_init,
            runtime_id=self.runtime_id,
            cluster_id=cluster_id,
            instrument_id=self.instrument_id,
            primary_bar_type=primary_bar_type,
            primary_bar=primary,
            updated_bar_types=frozenset(item for item in self.updated_bar_types if item in allowed),
            bars=OnlyBarSnapshot(
                {key: value for key, value in self.bars.latest_closed_bars.items() if key in allowed},
                {key: value for key, value in self.bars.histories.items() if key in allowed},
                {key: value for key, value in self.bars.partial_bars.items() if key in allowed},
                {key: value for key, value in self.bars.data_versions.items() if key in allowed},
            ),
            indicator_values={key: value for key, value in self.indicator_values.items() if key in indicator_ids},
            indicator_versions={key: value for key, value in self.indicator_versions.items() if key in indicator_ids},
            trading_day=primary.trading_day,
            session_type=primary.session_type,
            quality_flags=self.quality_flags,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "ts_event_ns": self.ts_event.unix_nanos,
            "ts_init_ns": self.ts_init.unix_nanos,
            "runtime_id": str(self.runtime_id),
            "cluster_id": None if self.cluster_id is None else str(self.cluster_id),
            "instrument_id": self.instrument_id.to_dict(),
            "primary_bar_type": self.primary_bar_type.to_dict(),
            "primary_bar": self.primary_bar.to_dict(),
            "updated_bar_types": [item.to_dict() for item in sorted(self.updated_bar_types, key=only_bar_type_id)],
            "latest_closed_bars": [
                {"bar_type": key.to_dict(), "bar": value.to_dict()}
                for key, value in sorted(
                    self.bars.latest_closed_bars.items(), key=lambda item: only_bar_type_id(item[0])
                )
            ],
            "histories": [
                {"bar_type": key.to_dict(), "bars": [bar.to_dict() for bar in value]}
                for key, value in sorted(self.bars.histories.items(), key=lambda item: only_bar_type_id(item[0]))
            ],
            "data_versions": [
                {"bar_type": key.to_dict(), "version": value}
                for key, value in sorted(self.bars.data_versions.items(), key=lambda item: only_bar_type_id(item[0]))
            ],
            "indicator_values": [
                {"indicator_id": str(key), "value": self._encode_indicator(value)}
                for key, value in sorted(self.indicator_values.items())
            ],
            "indicator_versions": [
                {"indicator_id": str(key), "version": value} for key, value in sorted(self.indicator_versions.items())
            ],
            "trading_day": self.trading_day.isoformat(),
            "session_type": self.session_type.value,
            "quality_flags": list(self.quality_flags),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlyMarketDataSnapshot:
        def require_mapping(value: object, name: str) -> Mapping[str, object]:
            if not isinstance(value, Mapping):
                raise ValueError(f"{name} must be a mapping")
            return value

        def require_list(value: object, name: str) -> list[object]:
            if not isinstance(value, list):
                raise ValueError(f"{name} must be a list")
            return value

        latest: dict[OnlyBarType, OnlyBar] = {}
        for item in require_list(payload["latest_closed_bars"], "latest_closed_bars"):
            entry = require_mapping(item, "latest_closed_bars entry")
            latest[OnlyBarType.from_dict(require_mapping(entry["bar_type"], "bar_type"))] = OnlyBar.from_dict(
                require_mapping(entry["bar"], "bar")
            )
        histories: dict[OnlyBarType, tuple[OnlyBar, ...]] = {}
        for item in require_list(payload["histories"], "histories"):
            entry = require_mapping(item, "histories entry")
            bar_type = OnlyBarType.from_dict(require_mapping(entry["bar_type"], "bar_type"))
            histories[bar_type] = tuple(
                OnlyBar.from_dict(require_mapping(bar, "history Bar"))
                for bar in require_list(entry["bars"], "history Bars")
            )
        versions: dict[OnlyBarType, int] = {}
        for item in require_list(payload["data_versions"], "data_versions"):
            entry = require_mapping(item, "data_versions entry")
            versions[OnlyBarType.from_dict(require_mapping(entry["bar_type"], "bar_type"))] = int(str(entry["version"]))
        indicator_values: dict[OnlyIndicatorId, OnlyIndicatorValue] = {}
        for item in require_list(payload["indicator_values"], "indicator_values"):
            entry = require_mapping(item, "indicator_values entry")
            indicator_values[OnlyIndicatorId(str(entry["indicator_id"]))] = cls._decode_indicator(
                require_mapping(entry["value"], "indicator value")
            )
        indicator_versions: dict[OnlyIndicatorId, int] = {}
        for item in require_list(payload["indicator_versions"], "indicator_versions"):
            entry = require_mapping(item, "indicator_versions entry")
            indicator_versions[OnlyIndicatorId(str(entry["indicator_id"]))] = int(str(entry["version"]))
        updated = frozenset(
            OnlyBarType.from_dict(require_mapping(item, "updated BarType"))
            for item in require_list(payload["updated_bar_types"], "updated_bar_types")
        )
        primary_bar_type = OnlyBarType.from_dict(require_mapping(payload["primary_bar_type"], "primary_bar_type"))
        primary_bar = OnlyBar.from_dict(require_mapping(payload["primary_bar"], "primary_bar"))
        return cls(
            ts_event=OnlyTimestamp.from_unix_nanos(int(str(payload["ts_event_ns"]))),
            ts_init=OnlyTimestamp.from_unix_nanos(int(str(payload["ts_init_ns"]))),
            runtime_id=OnlyRuntimeId(str(payload["runtime_id"])),
            cluster_id=None if payload.get("cluster_id") is None else OnlyClusterId(str(payload["cluster_id"])),
            instrument_id=OnlyInstrumentId.from_dict(require_mapping(payload["instrument_id"], "instrument_id")),
            primary_bar_type=primary_bar_type,
            primary_bar=primary_bar,
            updated_bar_types=updated,
            bars=OnlyBarSnapshot(latest, histories, {}, versions),
            indicator_values=indicator_values,
            indicator_versions=indicator_versions,
            trading_day=date.fromisoformat(str(payload["trading_day"])),
            session_type=OnlySessionType(str(payload["session_type"])),
            quality_flags=tuple(str(item) for item in require_list(payload["quality_flags"], "quality_flags")),
        )

    @staticmethod
    def _encode_indicator(value: OnlyIndicatorValue) -> object:
        if isinstance(value, Decimal):
            return {"kind": "decimal", "value": str(value)}
        if isinstance(value, OnlyStructuredIndicatorValue):
            return {"kind": "structured", "value_type": value.value_type, "value": dict(value.to_dict())}
        return {"kind": "scalar", "value": value}

    @staticmethod
    def _decode_indicator(payload: Mapping[str, object]) -> OnlyIndicatorValue:
        if payload.get("kind") == "decimal":
            return Decimal(str(payload["value"]))
        if payload.get("kind") == "scalar":
            value = payload.get("value")
            if value is None or isinstance(value, str | int | bool):
                return value
        if payload.get("kind") == "structured" and payload.get("value_type") == "MACD":
            from onlyalpha.indicator.macd import OnlyMacdSnapshot

            value = payload.get("value")
            if isinstance(value, Mapping):
                return OnlyMacdSnapshot.from_dict(value)
        raise ValueError("invalid indicator value payload")
