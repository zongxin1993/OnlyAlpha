"""Canonical event envelope."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
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

    def __post_init__(self) -> None:
        if self.timestamp.tzinfo is None:
            raise ValueError("event timestamp must be timezone-aware")
        if self.sequence < 0:
            raise ValueError("event sequence cannot be negative")
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))
