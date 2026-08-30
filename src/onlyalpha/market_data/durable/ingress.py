"""Durable acceptance boundary between adapters and remote databases."""

from __future__ import annotations

from collections.abc import Callable

from onlyalpha.data.evidence import OnlyRawProviderObservation
from onlyalpha.data.models import OnlyMarketDataInboundUpdate

from .models import (
    OnlyCanonicalMarketFactRecord,
    OnlyMarketDataProvenance,
    OnlyMarketDataRecordBundle,
    OnlyRawProviderEvidence,
)
from .wal import OnlyMarketDataWal


class OnlyMarketDataIngress:
    def __init__(
        self,
        wal: OnlyMarketDataWal,
        *,
        normalizer_id: str,
        normalizer_version: str,
        ingest_clock_ns: Callable[[], int],
        barrier: Callable[[str], None] | None = None,
    ) -> None:
        self._wal = wal
        self._normalizer_id = normalizer_id
        self._normalizer_version = normalizer_version
        self._ingest_clock_ns = ingest_clock_ns
        self._barrier = barrier or (lambda _stage: None)
        self._segment_id: str | None = None

    def begin_segment(self, segment_id: str | None = None) -> str:
        self._segment_id = self._wal.open_segment(segment_id)
        return self._segment_id

    def record(
        self,
        observation: OnlyRawProviderObservation,
        canonical_update: OnlyMarketDataInboundUpdate | tuple[OnlyMarketDataInboundUpdate, ...] | None,
    ) -> int:
        if self._segment_id is None:
            raise RuntimeError("MARKET_DATA_INGRESS_SEGMENT_NOT_OPEN")
        evidence = OnlyRawProviderEvidence.capture(
            source_id=observation.source_id,
            capture_session_id=observation.capture_session_id,
            provider=observation.provider,
            venue=observation.venue,
            market=observation.market,
            stream=observation.stream,
            provider_event_type=observation.provider_event_type,
            provider_event_id=observation.provider_event_id,
            provider_sequence=observation.provider_sequence,
            ts_event_ns=observation.ts_event_ns,
            ts_receive_ns=observation.ts_receive_ns,
            payload_codec=observation.payload_codec,
            provider_schema=observation.provider_schema,
            payload=observation.payload,
            provenance=OnlyMarketDataProvenance(observation.provenance),
        )
        updates = (
            ()
            if canonical_update is None
            else canonical_update
            if isinstance(canonical_update, tuple)
            else (canonical_update,)
        )
        facts = tuple(
            OnlyCanonicalMarketFactRecord.bind(
                update,
                evidence,
                segment_id=self._segment_id,
                ts_ingest_ns=self._ingest_clock_ns(),
                normalizer_id=self._normalizer_id,
                normalizer_version=self._normalizer_version,
            )
            for update in updates
        )
        self._barrier("C1")
        ordinal = self._wal.append(OnlyMarketDataRecordBundle(evidence, facts))
        self._barrier("C2")
        return ordinal

    def seal(self):  # type: ignore[no-untyped-def]
        segment = self._wal.seal()
        self._segment_id = None
        return segment


__all__ = ["OnlyMarketDataIngress"]
