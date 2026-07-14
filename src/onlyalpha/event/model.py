"""Immutable, scoped, nanosecond-safe event envelopes."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import IntEnum, StrEnum
from types import MappingProxyType
from uuid import UUID, uuid4

from onlyalpha.core.time import only_datetime_to_unix_ns, only_unix_ns_to_datetime_utc
from onlyalpha.domain.errors import OnlyValidationError as OnlyDomainValidationError
from onlyalpha.domain.identifiers import OnlyClusterId, OnlyEngineId, OnlyRuntimeId
from onlyalpha.domain.market import OnlyBar
from onlyalpha.domain.time import only_require_utc


@dataclass(frozen=True, order=True, slots=True)
class OnlyEventId:
    """Strong event identity."""

    value: UUID

    @classmethod
    def new(cls) -> OnlyEventId:
        return cls(uuid4())

    @classmethod
    def parse(cls, value: str | UUID) -> OnlyEventId:
        return cls(value if isinstance(value, UUID) else UUID(value))

    def __str__(self) -> str:
        return str(self.value)


@dataclass(frozen=True, order=True, slots=True)
class OnlyCorrelationId:
    """Identity shared by events in one logical workflow."""

    value: UUID

    @classmethod
    def new(cls) -> OnlyCorrelationId:
        return cls(uuid4())

    @classmethod
    def parse(cls, value: str | UUID) -> OnlyCorrelationId:
        return cls(value if isinstance(value, UUID) else UUID(value))

    def __str__(self) -> str:
        return str(self.value)


@dataclass(frozen=True, order=True, slots=True)
class OnlyCausationId:
    """Identity of the event which caused another event."""

    value: UUID

    @classmethod
    def parse(cls, value: str | UUID) -> OnlyCausationId:
        return cls(value if isinstance(value, UUID) else UUID(value))

    def __str__(self) -> str:
        return str(self.value)


@dataclass(frozen=True, order=True, slots=True)
class OnlyEventType:
    """Stable event type name independent from Python class names."""

    value: str

    def __post_init__(self) -> None:
        normalized = self.value.strip()
        if not normalized:
            raise ValueError("event_type is required")
        object.__setattr__(self, "value", normalized)

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, order=True, slots=True)
class OnlyEventSource:
    """Validated event producer identity."""

    value: str

    def __post_init__(self) -> None:
        normalized = self.value.strip()
        if not normalized:
            raise ValueError("event source is required")
        object.__setattr__(self, "value", normalized)

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True, eq=False)
class OnlyEventSequence:
    """Non-negative producer sequence."""

    value: int

    def __post_init__(self) -> None:
        if isinstance(self.value, bool) or self.value < 0:
            raise ValueError("event sequence cannot be negative")

    def __int__(self) -> int:
        return self.value

    def __eq__(self, other: object) -> bool:
        if isinstance(other, OnlyEventSequence):
            return self.value == other.value
        return isinstance(other, int) and self.value == other

    def __hash__(self) -> int:
        return hash(self.value)


class OnlyEventPriority(IntEnum):
    """Delivery importance; never a MarketData workflow ordering mechanism."""

    LOW = 0
    NORMAL = 100
    HIGH = 200
    CRITICAL = 300


@dataclass(frozen=True, slots=True)
class OnlyEventScope:
    """Engine/Runtime/Cluster ownership used to prevent cross-runtime delivery."""

    engine_id: OnlyEngineId
    runtime_id: OnlyRuntimeId | None = None
    cluster_id: OnlyClusterId | None = None

    def __post_init__(self) -> None:
        if self.cluster_id is not None and self.runtime_id is None:
            raise ValueError("cluster event scope requires runtime_id")

    def includes(self, other: OnlyEventScope) -> bool:
        if self.engine_id != other.engine_id:
            return False
        if self.runtime_id is not None and self.runtime_id != other.runtime_id:
            return False
        return self.cluster_id is None or self.cluster_id == other.cluster_id


class OnlyKnownEventType(StrEnum):
    """Stable names for facts produced by this component."""

    BAR_RECEIVED = "BAR_RECEIVED"
    BAR_VALIDATED = "BAR_VALIDATED"
    DERIVED_BAR_CREATED = "DERIVED_BAR_CREATED"
    BAR_CACHE_UPDATED = "BAR_CACHE_UPDATED"
    INDICATOR_UPDATED = "INDICATOR_UPDATED"
    MARKET_DATA_SNAPSHOT_READY = "MARKET_DATA_SNAPSHOT_READY"
    MARKET_DATA_PIPELINE_FAILED = "MARKET_DATA_PIPELINE_FAILED"
    CLUSTER_BAR_HANDLED = "CLUSTER_BAR_HANDLED"
    CLUSTER_BAR_HANDLER_FAILED = "CLUSTER_BAR_HANDLER_FAILED"


@dataclass(frozen=True, slots=True)
class OnlyEvent:
    """Immutable event envelope with compatibility constructor ordering."""

    event_type: OnlyEventType | str
    timestamp: datetime
    engine_id: OnlyEngineId | str
    runtime_id: OnlyRuntimeId | str
    source: OnlyEventSource | str
    sequence: OnlyEventSequence | int
    payload: object = None
    cluster_id: OnlyClusterId | str | None = None
    metadata: Mapping[str, str] = field(default_factory=dict)
    event_id: OnlyEventId | UUID = field(default_factory=OnlyEventId.new)
    ts_init: datetime | None = None
    correlation_id: OnlyCorrelationId | UUID | None = None
    causation_id: OnlyCausationId | UUID | None = None
    priority: OnlyEventPriority = OnlyEventPriority.NORMAL
    timestamp_ns: int | None = None
    ts_init_ns: int | None = None

    def __post_init__(self) -> None:
        try:
            only_require_utc(self.timestamp, "event ts_event")
        except OnlyDomainValidationError as exc:
            raise ValueError(str(exc)) from exc
        init_time = self.timestamp if self.ts_init is None else self.ts_init
        try:
            only_require_utc(init_time, "event ts_init")
        except OnlyDomainValidationError as exc:
            raise ValueError(str(exc)) from exc
        if init_time < self.timestamp:
            raise ValueError("event ts_init cannot precede ts_event")
        object.__setattr__(self, "ts_init", init_time)
        object.__setattr__(self, "event_type", self._event_type(self.event_type))
        object.__setattr__(self, "engine_id", self._engine_id(self.engine_id))
        object.__setattr__(self, "runtime_id", self._runtime_id(self.runtime_id))
        object.__setattr__(self, "cluster_id", self._cluster_id(self.cluster_id))
        object.__setattr__(self, "source", self._source(self.source))
        object.__setattr__(self, "sequence", self._sequence(self.sequence))
        object.__setattr__(self, "event_id", self._event_id(self.event_id))
        object.__setattr__(self, "correlation_id", self._correlation_id(self.correlation_id))
        object.__setattr__(self, "causation_id", self._causation_id(self.causation_id))
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))
        event_ns = only_datetime_to_unix_ns(self.timestamp) if self.timestamp_ns is None else self.timestamp_ns
        init_ns = only_datetime_to_unix_ns(init_time) if self.ts_init_ns is None else self.ts_init_ns
        if only_unix_ns_to_datetime_utc(event_ns, allow_truncation=True) != self.timestamp:
            raise ValueError("timestamp_ns must represent timestamp")
        if only_unix_ns_to_datetime_utc(init_ns, allow_truncation=True) != init_time:
            raise ValueError("ts_init_ns must represent ts_init")
        if init_ns < event_ns:
            raise ValueError("event ts_init_ns cannot precede timestamp_ns")
        object.__setattr__(self, "timestamp_ns", event_ns)
        object.__setattr__(self, "ts_init_ns", init_ns)

    @property
    def ts_event(self) -> datetime:
        return self.timestamp

    @property
    def scope(self) -> OnlyEventScope:
        return OnlyEventScope(self.engine_id, self.runtime_id, self.cluster_id)  # type: ignore[arg-type]

    def to_dict(self) -> dict[str, object]:
        """Return a stable nanosecond-safe replay DTO."""
        return {
            "schema_version": 2,
            "event_id": str(self.event_id),
            "event_type": str(self.event_type),
            "ts_event_ns": self.timestamp_ns,
            "ts_init_ns": self.ts_init_ns,
            "ts_event": self.timestamp.isoformat().replace("+00:00", "Z"),
            "ts_init": self.ts_init.isoformat().replace("+00:00", "Z"),  # type: ignore[union-attr]
            "engine_id": str(self.engine_id),
            "runtime_id": str(self.runtime_id),
            "cluster_id": None if self.cluster_id is None else str(self.cluster_id),
            "source": str(self.source),
            "sequence": int(self.sequence),
            "correlation_id": None if self.correlation_id is None else str(self.correlation_id),
            "causation_id": None if self.causation_id is None else str(self.causation_id),
            "priority": self.priority.name,
            "payload": self._encode_payload(self.payload),
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlyEvent:
        if payload.get("schema_version") == 2:
            event_ns = int(str(payload["ts_event_ns"]))
            init_ns = int(str(payload["ts_init_ns"]))
            metadata = payload.get("metadata", {})
            if not isinstance(metadata, Mapping):
                raise ValueError("event metadata must be a mapping")
            return cls(
                event_type=str(payload["event_type"]),
                timestamp=only_unix_ns_to_datetime_utc(event_ns, allow_truncation=True),
                engine_id=str(payload["engine_id"]),
                runtime_id=str(payload["runtime_id"]),
                source=str(payload["source"]),
                sequence=int(str(payload["sequence"])),
                payload=cls._decode_payload(payload.get("payload")),
                cluster_id=None if payload.get("cluster_id") is None else str(payload["cluster_id"]),
                metadata={str(key): str(value) for key, value in metadata.items()},
                event_id=UUID(str(payload["event_id"])),
                ts_init=only_unix_ns_to_datetime_utc(init_ns, allow_truncation=True),
                correlation_id=(
                    None if payload.get("correlation_id") is None else UUID(str(payload["correlation_id"]))
                ),
                causation_id=None if payload.get("causation_id") is None else UUID(str(payload["causation_id"])),
                priority=OnlyEventPriority[str(payload["priority"])],
                timestamp_ns=event_ns,
                ts_init_ns=init_ns,
            )
        return cls._from_legacy_dict(payload)

    @classmethod
    def _from_legacy_dict(cls, payload: Mapping[str, object]) -> OnlyEvent:
        ts_event_value = payload.get("ts_event", payload.get("timestamp"))
        if ts_event_value is None:
            raise ValueError("event payload requires ts_event")
        ts_init_value = payload.get("ts_init", ts_event_value)
        metadata = payload.get("metadata", {})
        if not isinstance(metadata, Mapping):
            raise ValueError("event metadata must be a mapping")
        return cls(
            event_type=str(payload["event_type"]),
            timestamp=datetime.fromisoformat(str(ts_event_value).replace("Z", "+00:00")),
            engine_id=str(payload["engine_id"]),
            runtime_id=str(payload["runtime_id"]),
            source=str(payload["source"]),
            sequence=int(str(payload["sequence"])),
            payload=payload.get("payload"),
            cluster_id=None if payload.get("cluster_id") is None else str(payload["cluster_id"]),
            metadata={str(key): str(value) for key, value in metadata.items()},
            event_id=UUID(str(payload["event_id"])),
            ts_init=datetime.fromisoformat(str(ts_init_value).replace("Z", "+00:00")),
        )

    @staticmethod
    def _encode_payload(value: object) -> object:
        if isinstance(value, OnlyBar):
            return {"kind": "OnlyBar", "value": value.to_dict()}
        if isinstance(value, Mapping):
            return {"kind": "mapping", "value": {str(key): item for key, item in value.items()}}
        if value is None or isinstance(value, str | int | bool):
            return {"kind": "scalar", "value": value}
        raise ValueError(f"unsupported replay event payload: {type(value).__name__}")

    @staticmethod
    def _decode_payload(value: object) -> object:
        if not isinstance(value, Mapping):
            raise ValueError("event payload envelope must be a mapping")
        kind = value.get("kind")
        encoded = value.get("value")
        if kind == "OnlyBar":
            if not isinstance(encoded, Mapping):
                raise ValueError("OnlyBar payload must be a mapping")
            return OnlyBar.from_dict(encoded)
        if kind in {"mapping", "scalar"}:
            return encoded
        raise ValueError(f"unknown event payload kind: {kind}")

    @staticmethod
    def _event_type(value: OnlyEventType | str) -> OnlyEventType:
        return value if isinstance(value, OnlyEventType) else OnlyEventType(value)

    @staticmethod
    def _engine_id(value: OnlyEngineId | str) -> OnlyEngineId:
        return value if isinstance(value, OnlyEngineId) else OnlyEngineId(value)

    @staticmethod
    def _runtime_id(value: OnlyRuntimeId | str) -> OnlyRuntimeId:
        return value if isinstance(value, OnlyRuntimeId) else OnlyRuntimeId(value)

    @staticmethod
    def _cluster_id(value: OnlyClusterId | str | None) -> OnlyClusterId | None:
        return value if value is None or isinstance(value, OnlyClusterId) else OnlyClusterId(value)

    @staticmethod
    def _source(value: OnlyEventSource | str) -> OnlyEventSource:
        return value if isinstance(value, OnlyEventSource) else OnlyEventSource(value)

    @staticmethod
    def _sequence(value: OnlyEventSequence | int) -> OnlyEventSequence:
        return value if isinstance(value, OnlyEventSequence) else OnlyEventSequence(value)

    @staticmethod
    def _event_id(value: OnlyEventId | UUID) -> OnlyEventId:
        return value if isinstance(value, OnlyEventId) else OnlyEventId(value)

    @staticmethod
    def _correlation_id(value: OnlyCorrelationId | UUID | None) -> OnlyCorrelationId | None:
        return value if value is None or isinstance(value, OnlyCorrelationId) else OnlyCorrelationId(value)

    @staticmethod
    def _causation_id(value: OnlyCausationId | UUID | None) -> OnlyCausationId | None:
        return value if value is None or isinstance(value, OnlyCausationId) else OnlyCausationId(value)


class OnlyBarReceivedEvent(OnlyEvent):
    pass


class OnlyBarValidatedEvent(OnlyEvent):
    pass


class OnlyDerivedBarCreatedEvent(OnlyEvent):
    pass


class OnlyBarCacheUpdatedEvent(OnlyEvent):
    pass


class OnlyIndicatorUpdatedEvent(OnlyEvent):
    pass


class OnlyMarketDataSnapshotReadyEvent(OnlyEvent):
    pass


class OnlyMarketDataPipelineFailedEvent(OnlyEvent):
    pass


class OnlyClusterBarHandledEvent(OnlyEvent):
    pass


class OnlyClusterBarHandlerFailedEvent(OnlyEvent):
    pass
