"""Provider-neutral opaque evidence boundary exposed by DataSource adapters."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from onlyalpha.data.models import OnlyMarketDataInboundUpdate


@dataclass(frozen=True, slots=True)
class OnlyRawProviderObservation:
    source_id: str
    capture_session_id: str
    provider: str
    venue: str
    market: str
    stream: str
    provider_event_type: str
    ts_receive_ns: int
    payload: bytes
    provider_event_id: str | None = None
    provider_sequence: int | None = None
    ts_event_ns: int | None = None
    payload_codec: str = "application/json"
    provider_schema: str = "v1"
    provenance: str = "REALTIME_STREAM"


class OnlyProviderEvidenceSink(Protocol):
    def __call__(
        self,
        observation: OnlyRawProviderObservation,
        canonical_update: OnlyMarketDataInboundUpdate | tuple[OnlyMarketDataInboundUpdate, ...] | None,
    ) -> None: ...


__all__ = ["OnlyProviderEvidenceSink", "OnlyRawProviderObservation"]
