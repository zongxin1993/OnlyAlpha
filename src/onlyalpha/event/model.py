"""Canonical event envelope."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from types import MappingProxyType
from uuid import UUID, uuid4


@dataclass(frozen=True, slots=True)
class OnlyEvent:
    """Immutable event envelope carrying isolation and tracing identifiers."""

    event_type: str
    timestamp: datetime
    engine_id: str
    runtime_id: str
    source: str
    sequence: int
    payload: object = None
    cluster_id: str | None = None
    metadata: Mapping[str, str] = field(default_factory=dict)
    event_id: UUID = field(default_factory=uuid4)
    ts_init: datetime | None = None

    def __post_init__(self) -> None:
        self._require_utc(self.timestamp, "event timestamp")
        if self.ts_init is None:
            object.__setattr__(self, "ts_init", self.timestamp)
        else:
            self._require_utc(self.ts_init, "event ts_init")
            if self.ts_init < self.timestamp:
                raise ValueError("event ts_init cannot precede ts_event")
        if self.sequence < 0:
            raise ValueError("event sequence cannot be negative")
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))

    @property
    def ts_event(self) -> datetime:
        """Canonical event occurrence time; `timestamp` is the compatibility field."""
        return self.timestamp

    def to_dict(self) -> dict[str, object]:
        """Return an API/storage-safe envelope with explicit UTC fields."""
        init_time = self.ts_init or self.timestamp
        return {
            "event_id": str(self.event_id),
            "event_type": self.event_type,
            "ts_event": self.timestamp.isoformat().replace("+00:00", "Z"),
            "ts_init": init_time.isoformat().replace("+00:00", "Z"),
            "engine_id": self.engine_id,
            "runtime_id": self.runtime_id,
            "cluster_id": self.cluster_id,
            "source": self.source,
            "sequence": self.sequence,
            "payload": self.payload,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> "OnlyEvent":
        ts_event_value = payload.get("ts_event", payload.get("timestamp"))
        if ts_event_value is None:
            raise ValueError("event payload requires ts_event")
        ts_init_value = payload.get("ts_init", ts_event_value)
        metadata_value = payload.get("metadata", {})
        if not isinstance(metadata_value, Mapping):
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
            metadata={str(key): str(value) for key, value in metadata_value.items()},
            event_id=UUID(str(payload["event_id"])),
            ts_init=datetime.fromisoformat(str(ts_init_value).replace("Z", "+00:00")),
        )

    @staticmethod
    def _require_utc(value: datetime, name: str) -> None:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(f"{name} must not be naive")
        if value.utcoffset() != timedelta(0):
            raise ValueError(f"{name} must be UTC")
