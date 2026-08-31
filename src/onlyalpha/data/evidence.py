"""Provider-neutral opaque evidence boundary exposed by DataSource adapters."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
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


class OnlyDurabilityState(StrEnum):
    WAL_DURABLE = "WAL_DURABLE"


@dataclass(frozen=True, slots=True)
class OnlyDurableRecordReceipt:
    segment_id: str
    ordinal: int
    durability_state: OnlyDurabilityState

    def __post_init__(self) -> None:
        if not self.segment_id.strip() or self.ordinal < 0:
            raise ValueError("DURABLE_RECORD_RECEIPT_INVALID")


class OnlyProviderEvidenceSink(Protocol):
    def __call__(
        self,
        observation: OnlyRawProviderObservation,
        canonical_update: OnlyMarketDataInboundUpdate | tuple[OnlyMarketDataInboundUpdate, ...] | None,
    ) -> OnlyDurableRecordReceipt: ...


__all__ = [
    "OnlyDurabilityState",
    "OnlyDurableRecordReceipt",
    "OnlyProviderEvidenceSink",
    "OnlyRawProviderObservation",
]
